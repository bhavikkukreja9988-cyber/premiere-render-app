"""Cloud storage transfer, keyed by job ID.

Object paths always include the job ID so repeated sends of the same project
never collide (each job is its own folder) and one job can never overwrite
another's files:

    project-files : user/{user_id}/jobs/{job_id}/project/{relpath}
    render-results: user/{user_id}/jobs/{job_id}/output/{filename}

Large files (at or above ``chunked_transfer.CHUNK_THRESHOLD``) are transferred
in fixed-size chunks that can resume after an interruption, instead of being
read or written whole — see ``chunked_transfer`` for how and why. Small files
(the common case for everything in a project except its big media) go as a
single object, which is simpler and has no resumability to gain from chunking.

``on_progress`` reports cumulative bytes across the *whole* operation
(``relpath, bytes_done_so_far, bytes_total_for_the_job``), not per-file, so a
caller can drive one overall progress bar without doing its own bookkeeping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from ..core.log import get_logger
from ..core.manifest import FileEntry, safe_join, validate_relpath
from . import chunked_transfer
from .config import RemoteConfig
from .transport import RemoteTransport

logger = get_logger("remote.storage")

ProgressFn = Callable[[str, int, int], None]     # (relpath, bytes_done, bytes_total)
CancelFn = Callable[[], bool]


def project_object_path(user_id: str, job_id: str, relpath: str) -> str:
    return f"user/{user_id}/jobs/{job_id}/project/{validate_relpath(relpath)}"


def result_object_path(user_id: str, job_id: str, filename: str) -> str:
    safe = Path(filename).name
    return f"user/{user_id}/jobs/{job_id}/output/{safe}"


class StorageService:
    def __init__(self, transport: RemoteTransport, config: RemoteConfig,
                 chunk_size: Optional[int] = None,
                 chunk_threshold: Optional[int] = None) -> None:
        self.transport = transport
        self.config = config
        # Overridable mainly for tests, which use tiny files and want to
        # exercise the chunked path without manufacturing a 32 MB fixture.
        self._chunk_size = chunk_size or chunked_transfer.CHUNK_SIZE
        self._chunk_threshold = chunk_threshold or chunked_transfer.CHUNK_THRESHOLD

    # -- sender: upload a project ----------------------------------------
    def upload_project(self, job_id: str, root: Path,
                       entries: List[FileEntry],
                       on_progress: Optional[ProgressFn] = None,
                       cancel: Optional[CancelFn] = None) -> List[str]:
        """Upload every manifest entry. Returns the storage paths written."""
        user_id = self.transport.current_user_id
        written: List[str] = []
        grand_total = sum(e.size for e in entries) or 1
        done_before = 0

        for entry in entries:
            if cancel and cancel():
                raise InterruptedError("cancelled")
            source = safe_join(root, entry.path)
            object_path = project_object_path(user_id, job_id, entry.path)

            def _progress(done_this_file: int, _total_this_file: int,
                         _entry=entry, _base=done_before) -> None:
                if on_progress:
                    on_progress(_entry.path, _base + done_this_file, grand_total)

            chunked_transfer.upload_file(
                self.transport, self.config.bucket_project_files, object_path,
                source, sha256=entry.sha256, chunk_size=self._chunk_size,
                threshold=self._chunk_threshold, on_progress=_progress,
                cancel=cancel)
            written.append(object_path)
            done_before += entry.size

        logger.info("uploaded %d project files for job %s", len(written),
                    job_id[:8])
        return written

    # -- station: download a project -------------------------------------
    def download_project(self, job_id: str, entries: List[FileEntry],
                         dest_root: Path,
                         on_progress: Optional[ProgressFn] = None,
                         cancel: Optional[CancelFn] = None) -> None:
        """Download every manifest entry into ``dest_root``, verifying hashes."""
        user_id = self.transport.current_user_id
        dest_root.mkdir(parents=True, exist_ok=True)
        grand_total = sum(e.size for e in entries) or 1
        done_before = 0

        for entry in entries:
            if cancel and cancel():
                raise InterruptedError("cancelled")
            object_path = project_object_path(user_id, job_id, entry.path)
            target = safe_join(dest_root, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)

            def _progress(done_this_file: int, _total_this_file: int,
                         _entry=entry, _base=done_before) -> None:
                if on_progress:
                    on_progress(_entry.path, _base + done_this_file, grand_total)

            chunked_transfer.download_file(
                self.transport, self.config.bucket_project_files, object_path,
                target, expected_sha256=entry.sha256, on_progress=_progress,
                cancel=cancel)
            done_before += entry.size

        logger.info("downloaded %d project files for job %s", len(entries),
                    job_id[:8])

    # -- station: upload the result --------------------------------------
    def upload_result(self, job_id: str, output_file: Path,
                      on_progress: Optional[Callable[[int, int], None]] = None,
                      cancel: Optional[CancelFn] = None) -> str:
        user_id = self.transport.current_user_id
        object_path = result_object_path(user_id, job_id, output_file.name)
        chunked_transfer.upload_file(
            self.transport, self.config.bucket_render_results, object_path,
            output_file, chunk_size=self._chunk_size,
            threshold=self._chunk_threshold, on_progress=on_progress,
            cancel=cancel)
        logger.info("uploaded result for job %s -> %s", job_id[:8], object_path)
        return object_path

    # -- sender: download the result -------------------------------------
    def download_result(self, job_id: str, filename: str, dest_dir: Path,
                        on_progress: Optional[Callable[[int, int], None]] = None,
                        cancel: Optional[CancelFn] = None) -> Path:
        user_id = self.transport.current_user_id
        object_path = result_object_path(user_id, job_id, filename)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / Path(filename).name
        counter = 1
        while target.exists():
            target = dest_dir / f"{Path(filename).stem} ({counter}){Path(filename).suffix}"
            counter += 1
        chunked_transfer.download_file(
            self.transport, self.config.bucket_render_results, object_path,
            target, on_progress=on_progress, cancel=cancel)
        logger.info("downloaded result for job %s -> %s", job_id[:8], target)
        return target

    # -- cleanup ----------------------------------------------------------
    def remove_job_objects(self, job_id: str) -> None:
        """Delete a job's cloud objects once they're safely no longer needed.

        Lists everything under the job's prefix, which naturally sweeps up
        chunk parts and manifest files too — they share the same prefix as the
        logical object path they belong to.
        """
        user_id = self.transport.current_user_id
        for bucket in (self.config.bucket_project_files,
                       self.config.bucket_render_results):
            prefix = f"user/{user_id}/jobs/{job_id}/"
            for object_path in self.transport.list_objects(bucket, prefix):
                self.transport.remove_object(bucket, object_path)
        logger.info("removed cloud objects for job %s", job_id[:8])
