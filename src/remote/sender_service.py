"""Remote sender worker."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from ..core.log import get_logger
from ..core.manifest import DEFAULT_IGNORE, scan_folder, total_bytes
from .client import RemoteClient
from .models import RemoteJob, RemoteJobState
from .transport import OfflineError, RemoteError, friendly_message

logger = get_logger("remote.sender_service")

POLL_SECONDS = 1.0
MAX_CONSECUTIVE_ERRORS = 60


@dataclass
class RemoteProgress:
    phase: str = "idle"
    fraction: float = 0.0
    message: str = ""
    bytes_done: int = 0
    bytes_total: int = 0


@dataclass
class RemoteSendRequest:
    station_id: str
    folder: Path
    project_name: str
    output_dir: Path
    project_relpath: str = ""
    sequence: str = ""
    preset: str = ""
    output_name: str = ""
    delete_after_delivery: bool = False
    ignore: Sequence[str] = field(default_factory=lambda: DEFAULT_IGNORE)


class RemoteSendWorker(threading.Thread):
    def __init__(self, client: RemoteClient, request: RemoteSendRequest,
                 on_progress: Optional[Callable[[RemoteProgress], None]] = None,
                 on_state: Optional[Callable[[str, dict], None]] = None) -> None:
        super().__init__(name="remote-send", daemon=True)
        self.client = client
        self.request = request
        self.on_progress = on_progress or (lambda p: None)
        self.on_state = on_state or (lambda kind, data: None)
        self._cancel = threading.Event()
        self.result_path: Optional[Path] = None
        self.job_id = ""
        self.error = ""

    def cancel(self) -> None:
        self._cancel.set()
        if self.job_id:
            try:
                self.client.jobs.set_state(
                    self.job_id, RemoteJobState.CANCELLED,
                    message="cancelled by the sender",
                )
            except RemoteError:
                pass

    def run(self) -> None:
        req = self.request
        try:
            self._report("scan", 0.0, "scanning project folder")
            entries = scan_folder(
                req.folder,
                ignore=req.ignore,
                with_hash=True,
                progress=lambda path, files, done: self._report(
                    "scan", 0.0, f"hashing {files} files ({path})"
                ),
                cancel=self._cancel.is_set,
            )
            if not entries:
                raise RuntimeError("that folder has no files to send")
            total_bytes(entries)

            if not self.client.stations.is_online(req.station_id):
                raise OfflineError("Render Station is offline")

            job = self.client.jobs.create_job(
                req.station_id,
                req.project_name,
                sequence=req.sequence,
                preset=req.preset,
                output_name=req.output_name,
                delete_after_delivery=req.delete_after_delivery,
                metadata={"project_relpath": req.project_relpath},
            )
            self.job_id = job.id
            self.on_state("created", {"job_id": job.id, "label": job.display_label})
            self.client.jobs.set_state(job.id, RemoteJobState.UPLOADING)

            def upload_progress(path: str, done: int, total: int) -> None:
                self._report("upload", done / total if total else 1.0, path, done, total)

            self.client.storage.upload_project(
                job.id,
                req.folder,
                entries,
                on_progress=upload_progress,
                cancel=self._cancel.is_set,
            )
            for entry in entries:
                storage_path = (
                    f"user/{self.client.user_id}/jobs/{job.id}/project/{entry.path}"
                )
                self.client.jobs.add_file(
                    job.id, entry.path, entry.size, entry.sha256, storage_path
                )
            self.client.jobs.set_state(
                job.id,
                RemoteJobState.UPLOADED,
                message="waiting for the render station",
            )
            self.on_state("uploaded", {"job_id": job.id})

            final = self._wait_for_result(job.id)
            self._report("download", 0.0, "fetching the rendered file")
            dest = self.client.storage.download_result(
                job.id,
                final.output_filename,
                req.output_dir,
                on_progress=lambda done, total: self._report(
                    "download",
                    done / total if total else 1.0,
                    final.output_filename,
                    done,
                    total,
                ),
                cancel=self._cancel.is_set,
            )

            if final.output_sha256:
                from ..core.manifest import hash_file
                if hash_file(dest) != final.output_sha256:
                    dest.unlink(missing_ok=True)
                    raise RuntimeError("the returned file failed its checksum")

            self.client.jobs.set_state(job.id, RemoteJobState.COMPLETE)
            self.result_path = dest
            self._report("done", 1.0, f"saved {dest.name}")
            self.on_state("complete", {"job_id": job.id, "path": str(dest)})
        except InterruptedError:
            self.error = "cancelled"
            self.on_state("cancelled", {"job_id": self.job_id})
        except (RemoteError, OSError, RuntimeError) as exc:
            message = friendly_message(exc)
            self.error = message
            if self.job_id:
                try:
                    self.client.jobs.set_state(self.job_id, RemoteJobState.FAILED, error=message)
                except RemoteError:
                    pass
            self.on_state("failed", {"job_id": self.job_id, "error": message})
            logger.error("remote job %s failed: %s", self.job_id[:8] or "?", exc)
        except Exception as exc:  # noqa: BLE001
            message = friendly_message(exc)
            self.error = message
            self.on_state("failed", {"job_id": self.job_id, "error": message})
            logger.exception("remote send worker crashed")

    def _wait_for_result(self, job_id: str) -> RemoteJob:
        consecutive_errors = 0
        while not self._cancel.is_set():
            try:
                job = self.client.jobs.get_job(job_id)
                consecutive_errors = 0
            except (RemoteError, OfflineError) as exc:
                consecutive_errors += 1
                self._report("wait", 0.0, f"reconnecting… ({friendly_message(exc)})")
                if consecutive_errors > MAX_CONSECUTIVE_ERRORS:
                    raise RuntimeError(
                        f"Lost contact with the server: {friendly_message(exc)}"
                    )
                time.sleep(POLL_SECONDS)
                continue

            if job is None:
                raise RuntimeError("the job disappeared")
            if job.state is RemoteJobState.READY_FOR_DOWNLOAD:
                return job
            if job.state is RemoteJobState.FAILED:
                raise RuntimeError(job.error or "render failed")
            if job.state is RemoteJobState.CANCELLED:
                raise InterruptedError("cancelled")

            label = {
                RemoteJobState.UPLOADED: "waiting for the render station",
                RemoteJobState.WAITING_FOR_STATION: "waiting for the station operator to accept",
                RemoteJobState.DOWNLOADING: "render station is downloading",
                RemoteJobState.QUEUED: "queued for rendering",
                RemoteJobState.RENDERING: "rendering",
                RemoteJobState.ENCODED: "finishing up",
                RemoteJobState.UPLOADING_RESULT: "uploading the result",
            }.get(job.state, job.state.value)
            if job.state is RemoteJobState.QUEUED:
                try:
                    ahead = self.client.jobs.queue_position(job_id)
                except RemoteError:
                    ahead = 0
                if ahead > 0:
                    label = f"queued — {ahead} job{'s' if ahead != 1 else ''} ahead of you"
            self._report("render", 0.0, label)
            time.sleep(POLL_SECONDS)
        raise InterruptedError("cancelled")

    def _report(self, phase: str, fraction: float, message: str,
               done: int = 0, total: int = 0) -> None:
        self.on_progress(RemoteProgress(phase, fraction, message, done, total))
