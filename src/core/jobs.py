"""Job model shared by the sender and the render station."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class JobState(str, Enum):
    CREATED = "created"
    TRANSFERRING = "transferring"
    QUEUED = "queued"
    RENDERING = "rendering"
    ENCODED = "encoded"          # MP4 exists on the station
    RETURNING = "returning"      # streaming back to the sender
    COMPLETE = "complete"        # sender has the file and acknowledged it
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobState.COMPLETE, JobState.FAILED, JobState.CANCELLED)


@dataclass
class JobSpec:
    """Everything the station needs to know to render a submitted folder."""

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "untitled"
    project_relpath: str = ""          # e.g. "MyEdit/MyEdit.prproj"
    sequence: str = ""                 # empty -> station renders the first sequence
    preset_source: str = "station"     # "station" | "attached" | "default"
    preset_ref: str = ""               # preset name, or relpath of an attached .epr
    output_name: str = ""              # without extension; defaults to the job name
    container: str = ".mp4"
    sender_name: str = ""
    file_count: int = 0
    total_bytes: int = 0
    created_at: float = field(default_factory=time.time)
    delete_after_return: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JobSpec":
        known = {f for f in JobSpec.__dataclass_fields__}
        return JobSpec(**{k: v for k, v in (d or {}).items() if k in known})

    def output_filename(self) -> str:
        stem = (self.output_name or self.name or "render").strip()
        for bad in '<>:"/\\|?*':
            stem = stem.replace(bad, "_")
        return f"{stem or 'render'}{self.container}"


@dataclass
class JobRecord:
    spec: JobSpec
    state: JobState = JobState.CREATED
    progress: float = 0.0              # 0..1 for the current phase
    message: str = ""
    error: str = ""
    bytes_received: int = 0
    output_path: str = ""
    updated_at: float = field(default_factory=time.time)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict(),
            "state": self.state.value,
            "progress": round(self.progress, 4),
            "message": self.message,
            "error": self.error,
            "bytes_received": self.bytes_received,
            "output_path": self.output_path,
            "updated_at": self.updated_at,
            "history": self.history[-40:],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JobRecord":
        return JobRecord(
            spec=JobSpec.from_dict(d.get("spec", {})),
            state=JobState(d.get("state", "created")),
            progress=float(d.get("progress", 0.0)),
            message=str(d.get("message", "")),
            error=str(d.get("error", "")),
            bytes_received=int(d.get("bytes_received", 0)),
            output_path=str(d.get("output_path", "")),
            updated_at=float(d.get("updated_at", time.time())),
            history=list(d.get("history", [])),
        )

    @property
    def job_id(self) -> str:
        return self.spec.job_id


class JobStore:
    """Thread-safe job table with crash-safe JSON persistence.

    The station keeps its queue here so a restart mid-batch does not lose
    jobs that have already been transferred.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.RLock()
        self._jobs: Dict[str, JobRecord] = {}
        self._listeners: List[Callable[[JobRecord], None]] = []
        if self._path and self._path.exists():
            self.load()

    # -- listeners --------------------------------------------------------
    def subscribe(self, callback: Callable[[JobRecord], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def _notify(self, record: JobRecord) -> None:
        for callback in list(self._listeners):
            try:
                callback(record)
            except Exception:  # a broken UI listener must never kill a render
                pass

    # -- access -----------------------------------------------------------
    def add(self, record: JobRecord) -> JobRecord:
        with self._lock:
            self._jobs[record.job_id] = record
            self._save_locked()
        self._notify(record)
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(),
                          key=lambda r: r.spec.created_at, reverse=True)

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._save_locked()

    def next_queued(self) -> Optional[JobRecord]:
        with self._lock:
            queued = [r for r in self._jobs.values() if r.state is JobState.QUEUED]
            queued.sort(key=lambda r: r.spec.created_at)
            return queued[0] if queued else None

    def update(self, job_id: str, *, state: Optional[JobState] = None,
               progress: Optional[float] = None, message: Optional[str] = None,
               error: Optional[str] = None, bytes_received: Optional[int] = None,
               output_path: Optional[str] = None) -> Optional[JobRecord]:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if state is not None and state is not record.state:
                record.state = state
                record.history.append({"t": time.time(), "state": state.value,
                                       "message": message or ""})
            if progress is not None:
                record.progress = max(0.0, min(1.0, progress))
            if message is not None:
                record.message = message
            if error is not None:
                record.error = error
            if bytes_received is not None:
                record.bytes_received = bytes_received
            if output_path is not None:
                record.output_path = output_path
            record.updated_at = time.time()
            self._save_locked()
        self._notify(record)
        return record

    # -- persistence ------------------------------------------------------
    def _save_locked(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(
                json.dumps([r.to_dict() for r in self._jobs.values()], indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError:
            pass

    def load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        with self._lock:
            for item in data:
                try:
                    record = JobRecord.from_dict(item)
                except Exception:
                    continue
                # A job that was mid-render when the app closed cannot be
                # resumed inside Media Encoder, so re-queue it.
                if record.state in (JobState.RENDERING, JobState.RETURNING):
                    record.state = JobState.QUEUED
                    record.message = "re-queued after restart"
                self._jobs[record.job_id] = record
