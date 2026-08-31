"""Remote job coordination through Supabase.

A job is one render request. Sending the same project many times creates many
jobs — this service never rejects a job because its files hash the same as an
earlier one. Job identity is a UUID; the human label (Job-001…) is derived per
user from how many jobs they already have.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from ..core.log import get_logger
from .config import RemoteConfig
from .models import JobEvent, JobFile, RemoteJob, RemoteJobState
from .transport import RemoteTransport, Unsubscribe

logger = get_logger("remote.jobs")


class RemoteJobService:
    def __init__(self, transport: RemoteTransport, config: RemoteConfig) -> None:
        self.transport = transport
        self.config = config

    # -- creation (sender) ------------------------------------------------
    def _next_label(self, user_id: str) -> str:
        existing = self.transport.select("jobs", {"user_id": user_id})
        return f"Job-{len(existing) + 1:03d}"

    def create_job(self, station_id: str, project_name: str, *,
                   sequence: str = "", preset: str = "", output_name: str = "",
                   delete_after_delivery: bool = False,
                   metadata: Optional[dict] = None) -> RemoteJob:
        """Create a new job row. Each call is a distinct job (new UUID)."""
        user_id = self.transport.current_user_id
        job = RemoteJob(
            user_id=user_id, station_id=station_id,
            display_label=self._next_label(user_id),
            project_name=project_name, sequence=sequence, preset=preset,
            output_name=output_name or project_name,
            status=RemoteJobState.CREATED.value,
            delete_after_delivery=delete_after_delivery,
            metadata=metadata or {},
        )
        row = self.transport.insert("jobs", job.to_row())
        created = RemoteJob.from_row(row)
        self.add_event(created.id, "created", f"job created for {station_id}")
        logger.info("created %s (%s) -> station %s",
                    created.display_label, created.id[:8], station_id)
        return created

    # -- files ------------------------------------------------------------
    def add_file(self, job_id: str, path: str, size: int, sha256: str,
                 storage_path: str) -> JobFile:
        record = JobFile(job_id=job_id, path=path, size=size, sha256=sha256,
                         storage_path=storage_path)
        self.transport.insert("job_files", record.to_row())
        return record

    def list_files(self, job_id: str) -> List[JobFile]:
        rows = self.transport.select("job_files", {"job_id": job_id},
                                     order_by="path")
        return [JobFile.from_row(r) for r in rows]

    def manifest_entries(self, job_id: str) -> List["FileEntry"]:
        """Reconstruct the transfer manifest from job_files for the downloader.

        The station never needs the sender to resend the manifest — it's
        already sitting in the database as job_files rows.
        """
        from ..core.manifest import FileEntry
        return [FileEntry(path=f.path, size=f.size, mtime=0.0, sha256=f.sha256)
                for f in self.list_files(job_id)]

    # -- events -----------------------------------------------------------
    def add_event(self, job_id: str, event_type: str, message: str = "") -> None:
        self.transport.insert("job_events", JobEvent(
            job_id=job_id, event_type=event_type, message=message).to_row())

    def list_events(self, job_id: str) -> List[JobEvent]:
        rows = self.transport.select("job_events", {"job_id": job_id},
                                     order_by="created_at")
        return [JobEvent.from_row(r) for r in rows]

    # -- state ------------------------------------------------------------
    def set_state(self, job_id: str, state: RemoteJobState, *,
                  message: str = "", error: str = "",
                  output_filename: str = "") -> None:
        changes: dict = {"status": state.value}
        now = time.time()
        if state is RemoteJobState.RENDERING:
            changes["started_at"] = now
        if state.terminal:
            changes["completed_at"] = now
        if error:
            changes["error"] = error
        if output_filename:
            changes["output_filename"] = output_filename
        self.transport.update("jobs", {"id": job_id}, changes)
        self.add_event(job_id, state.value, message)

    def set_output_ready(self, job_id: str, filename: str, sha256: str) -> None:
        """Station calls this once the result is uploaded and ready to fetch."""
        self.transport.update("jobs", {"id": job_id}, {
            "status": RemoteJobState.READY_FOR_DOWNLOAD.value,
            "output_filename": filename,
            "output_sha256": sha256,
        })
        self.add_event(job_id, RemoteJobState.READY_FOR_DOWNLOAD.value,
                       f"result ready: {filename}")

    def get_job(self, job_id: str) -> Optional[RemoteJob]:
        rows = self.transport.select("jobs", {"id": job_id})
        return RemoteJob.from_row(rows[0]) if rows else None

    def list_jobs(self) -> List[RemoteJob]:
        rows = self.transport.select("jobs", order_by="created_at",
                                     descending=True)
        return [RemoteJob.from_row(r) for r in rows]

    # -- station side -----------------------------------------------------
    def pending_for_station(self, station_id: str) -> List[RemoteJob]:
        """Jobs assigned to a station that it should pick up or resume."""
        rows = self.transport.select("jobs", {"station_id": station_id},
                                     order_by="created_at")
        jobs = [RemoteJob.from_row(r) for r in rows]
        return [j for j in jobs if j.state.recoverable_by_station]

    def claim(self, job_id: str) -> None:
        """Station marks a job as being downloaded/worked on."""
        self.set_state(job_id, RemoteJobState.DOWNLOADING,
                       message="station accepted the job")

    # -- realtime ---------------------------------------------------------
    def watch_station_jobs(self, station_id: str,
                           callback: Callable[[str, RemoteJob], None]
                           ) -> Unsubscribe:
        def on_change(event_type: str, row: dict) -> None:
            callback(event_type, RemoteJob.from_row(row))
        return self.transport.subscribe("jobs", {"station_id": station_id},
                                        on_change)

    def watch_job(self, job_id: str,
                  callback: Callable[[str, RemoteJob], None]) -> Unsubscribe:
        def on_change(event_type: str, row: dict) -> None:
            callback(event_type, RemoteJob.from_row(row))
        return self.transport.subscribe("jobs", {"id": job_id}, on_change)
