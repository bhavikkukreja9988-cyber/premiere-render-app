"""Cloud Render Station worker.

Bridges Supabase remote jobs to the existing local JobStore/RenderManager and
Adobe Media Encoder pipeline. The worker is active only while FileSender is
open; stop() removes its heartbeat and marks the station offline.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .. import __version__
from ..core import workspace
from ..core.config import AppConfig
from ..core.jobs import JobRecord, JobSpec, JobState, JobStore
from ..core.log import get_logger
from ..core.retention import RetentionManager
from ..render.pipeline import RenderManager, build_backend
from .client import RemoteClient
from .models import RemoteJob, RemoteJobState
from .transport import RemoteError, friendly_message

logger = get_logger("remote.station_worker")

RECOVERY_POLL_SECONDS = 20.0
CLEANUP_POLL_SECONDS = 30.0


class RemoteStationWorker:
    """Own the cloud-visible presence and render queue for one station."""

    def __init__(self, client: RemoteClient, config: AppConfig,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 backend=None) -> None:
        self.client = client
        self.config = config
        self.on_event = on_event or (lambda kind, data: None)

        workspace.ensure_workspace(config.workspace)
        self.local_store = JobStore(
            workspace.jobs_file(config.workspace), jobs_root=config.workspace / "jobs"
        )

        if backend is None:
            try:
                from ..render import media_encoder as ame
                ame.install_agent()
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not install the Media Encoder agent: %s", exc)

        self.backend = backend or build_backend(config)
        self.manager = RenderManager(
            self.local_store, self.backend, config, self._on_local_event
        )
        self.retention = RetentionManager(
            self.local_store,
            config.workspace,
            retention_days_provider=lambda: self.config.retention_days,
            remove_job_dir=self._remove_job_everywhere,
            busy_job_provider=lambda: self.manager.current_job,
            on_event=self.on_event,
        )

        self._stop = threading.Event()
        self._recovery_thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._unsubscribe = None
        self._downloading: Dict[str, bool] = {}
        self._cloud_cleaned: Dict[str, bool] = {}
        self.pending_manual: Dict[str, RemoteJob] = {}
        self.started = False

    def start(self) -> None:
        """Register and expose this PC as an online Render Station."""
        if self.started:
            return
        capabilities = {
            "presets": self._local_presets(),
            "accepts_automatically": self.config.accept_jobs_automatically,
        }
        self.client.stations.register(
            self.config.station_id,
            self.config.device_name or self.config.station_name,
            app_version=__version__,
            local_ip=self._local_ip(),
            capabilities=capabilities,
            family_code=self.config.family_code,
            device_name=self.config.device_name or self.config.station_name,
        )
        self.client.stations.start_heartbeat(self.config.station_id)
        self.manager.start()
        self.retention.start()
        self._reconcile_local_results()
        self._unsubscribe = self.client.jobs.watch_station_jobs(
            self.config.station_id, self._on_remote_job_event
        )
        self._stop.clear()
        self._recovery_thread = threading.Thread(
            target=self._recovery_loop, name="remote-station-recovery", daemon=True
        )
        self._recovery_thread.start()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, name="remote-station-cleanup", daemon=True
        )
        self._cleanup_thread.start()
        self.started = True
        logger.info("remote station %s online", self.config.station_id)
        self.on_event("remote_station_online", {"station_id": self.config.station_id})

    def stop(self) -> None:
        """Stop all cloud worker activity and mark the station offline."""
        if not self.started:
            return
        self._stop.set()
        if self._unsubscribe:
            try:
                self._unsubscribe()
            except Exception:  # noqa: BLE001
                logger.debug("remote job subscription shutdown failed", exc_info=True)
            self._unsubscribe = None
        if self._recovery_thread:
            self._recovery_thread.join(timeout=2.0)
            self._recovery_thread = None
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=2.0)
            self._cleanup_thread = None
        self.retention.stop()
        self.manager.stop()
        try:
            self.client.stations.go_offline(self.config.station_id)
        except RemoteError as exc:
            logger.warning("could not mark station offline: %s", exc)
        self.started = False
        self.on_event("remote_station_offline", {"station_id": self.config.station_id})

    @staticmethod
    def _local_ip() -> str:
        try:
            from .network_utils import local_ip
            return local_ip()
        except Exception:  # noqa: BLE001
            return ""

    def _local_presets(self) -> list:
        try:
            from ..render import media_encoder as ame
            return [name for name, _ in ame.list_presets()]
        except Exception:  # noqa: BLE001
            return []

    def _reconcile_local_results(self) -> None:
        for record in self.local_store.list():
            if record.state not in (JobState.ENCODED, JobState.COMPLETE):
                continue
            output = Path(record.output_path) if record.output_path else None
            if not output or not output.is_file():
                continue
            try:
                remote_job = self.client.jobs.get_job(record.job_id)
                if remote_job and remote_job.state not in (
                    RemoteJobState.READY_FOR_DOWNLOAD,
                    RemoteJobState.COMPLETE,
                ):
                    self._upload_result(record.job_id, output)
            except RemoteError as exc:
                logger.debug("could not reconcile %s: %s", record.job_id[:8], exc)

    def _on_remote_job_event(self, event_type: str, job: RemoteJob) -> None:
        if job.state in (RemoteJobState.UPLOADED, RemoteJobState.WAITING_FOR_STATION):
            self._consider_job(job)
        elif job.state is RemoteJobState.CANCELLED:
            self._handle_cancel(job)

    def _recovery_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for job in self.client.jobs.pending_for_station(self.config.station_id):
                    self._consider_job(job)
            except RemoteError as exc:
                logger.debug("recovery sweep failed: %s", exc)
            self._stop.wait(RECOVERY_POLL_SECONDS)

    def _consider_job(self, job: RemoteJob) -> None:
        if self._downloading.get(job.id):
            return
        if job.state is RemoteJobState.WAITING_FOR_STATION:
            if self.config.accept_jobs_automatically:
                self.accept_pending(job.id)
            elif job.id not in self.pending_manual:
                self.pending_manual[job.id] = job
                self.on_event("job_awaiting_acceptance", {
                    "job_id": job.id, "label": job.display_label
                })
            return
        if job.state is RemoteJobState.UPLOADED:
            if self.config.accept_jobs_automatically:
                self._accept_and_download(job)
            elif job.id not in self.pending_manual:
                self.client.jobs.set_state(
                    job.id,
                    RemoteJobState.WAITING_FOR_STATION,
                    message="waiting for the station operator to accept",
                )
                self.pending_manual[job.id] = job
                self.on_event("job_awaiting_acceptance", {
                    "job_id": job.id, "label": job.display_label
                })
            return

        if job.state in (
            RemoteJobState.DOWNLOADING,
            RemoteJobState.QUEUED,
            RemoteJobState.RENDERING,
            RemoteJobState.ENCODED,
        ):
            local = self.local_store.get(job.id)
            if local is None:
                self._accept_and_download(job)
            elif local.state is JobState.ENCODED:
                output = Path(local.output_path) if local.output_path else None
                if output and output.is_file():
                    self._upload_result(job.id, output)
            elif local.state is JobState.COMPLETE:
                output = Path(local.output_path) if local.output_path else None
                if output and output.is_file() and job.state not in (
                    RemoteJobState.READY_FOR_DOWNLOAD,
                    RemoteJobState.COMPLETE,
                ):
                    self._upload_result(job.id, output)

    def accept_pending(self, remote_job_id: str) -> None:
        job = self.pending_manual.pop(remote_job_id, None)
        if job is None:
            job = self.client.jobs.get_job(remote_job_id)
        if job is not None:
            self._accept_and_download(job)

    def reject_pending(self, remote_job_id: str) -> None:
        self.pending_manual.pop(remote_job_id, None)
        self.client.jobs.set_state(
            remote_job_id,
            RemoteJobState.CANCELLED,
            message="rejected by the station operator",
        )

    # -- received-jobs management (Render Station tab) --------------------
    def list_local_jobs(self) -> List[JobRecord]:
        """Every job this PC has received, newest first."""
        return sorted(self.local_store.list(),
                      key=lambda r: r.updated_at or 0, reverse=True)

    def is_active(self, job_id: str) -> bool:
        """True while a job is being downloaded or rendered right now."""
        return (job_id == self.manager.current_job
                or bool(self._downloading.get(job_id)))

    def cancel_job(self, job_id: str) -> Tuple[bool, str]:
        """Stop the job that is rendering right now.

        Media Encoder checks for cancellation while it works, so the job ends
        up CANCELLED on its own shortly afterwards — at which point it can be
        cleared like any other finished job.
        """
        if job_id != self.manager.current_job:
            return False, "That job isn't rendering right now."
        self.manager.cancel(job_id)
        logger.info("render cancel requested for %s", job_id[:8])
        return True, "Cancelling — this can take a few seconds."

    def clear_job(self, job_id: str) -> Tuple[bool, str]:
        """Delete a received job from this PC and from the cloud.

        Order matters. The cloud is updated FIRST: a job still marked
        queued/rendering/downloading in the cloud is exactly what the
        recovery loop re-downloads on its next pass, so clearing only the
        local copy would make it silently come back. If the cloud can't be
        reached for a job that is still in progress there, nothing is
        deleted and the user is told why.
        """
        if job_id == self.manager.current_job:
            return False, ("This job is rendering right now. Cancel it first, "
                           "then clear it.")
        if self._downloading.get(job_id):
            return False, ("This job is still downloading. Wait for it to "
                           "finish, then clear it.")

        # 1. Cloud: stop it being picked up again, and tell the sender.
        try:
            remote = self.client.jobs.get_job(job_id)
        except RemoteError as exc:
            return False, ("Couldn't reach the cloud, so nothing was deleted "
                           f"(it could be downloaded again). {friendly_message(exc)}")
        if remote is not None and not remote.state.terminal:
            try:
                # FAILED rather than CANCELLED: the sender then shows the
                # reason together with its Retry button.
                self.client.jobs.set_state(
                    job_id, RemoteJobState.FAILED,
                    error=("Cleared on the render station "
                           f"({self.config.device_name or self.config.station_name})."),
                    message="cleared by the station operator")
            except RemoteError as exc:
                return False, ("Couldn't update the cloud, so nothing was "
                               f"deleted. {friendly_message(exc)}")

        # 2. Local + cloud files.
        self.pending_manual.pop(job_id, None)
        self._remove_job_everywhere(job_id)
        self.local_store.remove(job_id)
        logger.info("cleared job %s by hand", job_id[:8])
        self.on_event("job_cleared", {"job_id": job_id})
        return True, "Job cleared."

    def _remove_job_everywhere(self, job_id: str) -> None:
        """Delete a job's local folder and its cloud files.

        Used by both hand-clearing and the retention sweep. The cloud part is
        best-effort: a failure there is logged, never raised — local disk
        space is the thing the user is actually trying to get back.
        """
        workspace.remove_job_dir(self.config.workspace, job_id)
        try:
            self.client.storage.remove_job_objects(job_id)
            self._cloud_cleaned[job_id] = True
        except RemoteError as exc:
            logger.debug("cloud file cleanup for %s failed: %s", job_id[:8], exc)

    def _accept_and_download(self, job: RemoteJob) -> None:
        self._downloading[job.id] = True
        try:
            self.client.jobs.claim(job.id)
            entries = self.client.jobs.manifest_entries(job.id)
            if not entries:
                raise RemoteError("job has no files recorded")

            project_root = workspace.project_dir(self.config.workspace, job.id)
            # Publish real progress so the sender sees movement instead of a
            # silent wait. Scaled to 0-40% of the job: download is the first
            # of three phases (download, render, upload result).
            def _download_progress(path, done, total):
                fraction = (done / total) if total else 0.0
                self.client.jobs.report_progress(
                    job.id, fraction * 0.4,
                    f"Downloading {Path(path).name}")

            self.client.storage.download_project(
                job.id, entries, project_root,
                on_progress=_download_progress,
            )
            workspace.prepare_job_dirs(self.config.workspace, job.id)
            spec = JobSpec(
                job_id=job.id,
                name=job.project_name,
                project_relpath=str((job.metadata or {}).get("project_relpath", "")),
                sequence=job.sequence,
                preset_source="station",
                preset_ref=job.preset,
                output_name=job.output_name,
                sender_name="remote",
                file_count=len(entries),
                total_bytes=sum(e.size for e in entries),
                delete_after_return=job.delete_after_delivery,
            )
            self.local_store.add(JobRecord(
                spec=spec,
                label=job.display_label,
                state=JobState.QUEUED,
                message="queued from the cloud",
            ))
            self.client.jobs.set_state(
                job.id, RemoteJobState.QUEUED, message="queued on the render station"
            )
        except (RemoteError, OSError, ValueError, InterruptedError) as exc:
            message = friendly_message(exc)
            try:
                self.client.jobs.set_state(job.id, RemoteJobState.FAILED, error=message)
            except RemoteError:
                pass
            logger.error("%s failed during download: %s", job.id[:8], exc)
        finally:
            self._downloading.pop(job.id, None)

    def _handle_cancel(self, job: RemoteJob) -> None:
        self.manager.cancel(job.id)
        local = self.local_store.get(job.id)
        if local and not local.state.terminal:
            self.local_store.update(
                job.id,
                state=JobState.CANCELLED,
                message="cancelled by the sender",
            )

    def _on_local_event(self, kind: str, data: dict) -> None:
        job_id = data.get("job_id", "")
        if not job_id:
            return
        try:
            remote_job = self.client.jobs.get_job(job_id)
        except RemoteError:
            remote_job = None
        if remote_job is None:
            return

        if kind == "render_started":
            self.client.jobs.set_state(job_id, RemoteJobState.RENDERING, message="rendering")
            # 40% = download done. Rendering has no reliable percentage from
            # Media Encoder, so it sits at 40 with a clear label rather than
            # showing a fake climbing number.
            self.client.jobs.report_progress(job_id, 0.4, "Rendering in Media Encoder")
            self.client.stations.set_busy(self.config.station_id, True)
        elif kind == "render_finished":
            self._upload_result(job_id, Path(data.get("output", "")))
            self.client.stations.set_busy(self.config.station_id, False)
        elif kind == "render_failed":
            self.client.jobs.set_state(
                job_id, RemoteJobState.FAILED, error=data.get("error", "render failed")
            )
            self.client.jobs.report_progress(job_id, 0.0, "Render failed")
            self.client.stations.set_busy(self.config.station_id, False)

    def _upload_result(self, job_id: str, output_file: Path) -> None:
        if not output_file.is_file():
            self.client.jobs.set_state(
                job_id, RemoteJobState.FAILED,
                error=f"rendered file missing: {output_file}",
            )
            return
        try:
            self.client.jobs.set_state(job_id, RemoteJobState.UPLOADING_RESULT,
                                       message="uploading the rendered result")
            from ..core.manifest import hash_file
            self.client.jobs.report_progress(job_id, 0.7, "Uploading rendered file")
            digest = hash_file(output_file)
            self.client.storage.upload_result(
                job_id, output_file,
                on_progress=lambda done, total: self.client.jobs.report_progress(
                    job_id, 0.7 + (0.3 * (done / total if total else 1.0)),
                    "Uploading rendered file"),
            )
            self.client.jobs.report_progress(job_id, 1.0, "Ready to download")
            self.client.jobs.set_output_ready(job_id, output_file.name, digest)
            self.client.jobs.set_state(job_id, RemoteJobState.READY_FOR_DOWNLOAD,
                                       message="render complete; result ready")
            # Hand off to the existing, already-tested local retention system:
            # from here on, this job's local data is managed by the
            # configured retention policy, same as it always was.
            self.local_store.update(job_id, state=JobState.COMPLETE,
                                    message="delivered to the cloud")
            self.on_event("result_ready", {"job_id": job_id})
        except RemoteError as exc:
            self.client.jobs.set_state(job_id, RemoteJobState.FAILED,
                                       error=friendly_message(exc))

    # -- cleanup once the sender has confirmed delivery ----------------------
    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._sweep_cleanup()
            except RemoteError as exc:
                logger.debug("cleanup sweep failed: %s", exc)
            self._stop.wait(CLEANUP_POLL_SECONDS)

    def _sweep_cleanup(self) -> None:
        """Cloud storage is temporary transport, not permanent storage: once
        a job is fully delivered, remove its cloud files. The local copy
        follows the configured retention policy — or is removed immediately
        if the sender asked for that when the job was sent."""
        for job in self.client.jobs.list_jobs():
            if job.station_id != self.config.station_id:
                continue
            if job.state is not RemoteJobState.COMPLETE:
                continue
            if self._cloud_cleaned.get(job.id):
                continue
            try:
                self.client.storage.remove_job_objects(job.id)
            except RemoteError as exc:
                logger.debug("cloud cleanup failed for %s", job.id[:8], exc)
                continue
            self._cloud_cleaned[job.id] = True
            local = self.local_store.get(job.id)
            if local and local.spec.delete_after_return:
                workspace.remove_job_dir(self.config.workspace, job.id)
                self.local_store.remove(job.id)
                logger.info("removed local + cloud data for %s (delete "
                           "requested)", job.id[:8])
