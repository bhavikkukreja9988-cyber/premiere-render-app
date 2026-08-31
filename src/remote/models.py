"""Remote domain models shared across the transport, services and UI.

These mirror the Supabase tables but are plain dataclasses so the rest of the
app never imports a database library. The transport layer converts rows to and
from these.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class RemoteJobState(str, Enum):
    """Cloud job lifecycle, coordinated through Supabase.

    This is the cross-network state. It intentionally lines up with the local
    :class:`src.core.jobs.JobState` where they overlap (queued, rendering,
    complete, failed, cancelled) so the render pipeline can be reused, and adds
    the transfer states that only exist in the remote world.
    """

    CREATED = "created"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    WAITING_FOR_STATION = "waiting_for_station"
    DOWNLOADING = "downloading"
    QUEUED = "queued"
    RENDERING = "rendering"
    ENCODED = "encoded"
    UPLOADING_RESULT = "uploading_result"
    READY_FOR_DOWNLOAD = "ready_for_download"
    DOWNLOADING_RESULT = "downloading_result"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (RemoteJobState.COMPLETE, RemoteJobState.FAILED,
                        RemoteJobState.CANCELLED)

    @property
    def active_transfer(self) -> bool:
        """States during which cloud files must not be deleted."""
        return self in (
            RemoteJobState.UPLOADING, RemoteJobState.UPLOADED,
            RemoteJobState.WAITING_FOR_STATION, RemoteJobState.DOWNLOADING,
            RemoteJobState.QUEUED, RemoteJobState.RENDERING,
            RemoteJobState.ENCODED, RemoteJobState.UPLOADING_RESULT,
            RemoteJobState.READY_FOR_DOWNLOAD, RemoteJobState.DOWNLOADING_RESULT,
        )

    @property
    def recoverable_by_station(self) -> bool:
        """States a station should pick up or resume when it comes online."""
        return self in (
            RemoteJobState.UPLOADED, RemoteJobState.WAITING_FOR_STATION,
            RemoteJobState.DOWNLOADING, RemoteJobState.QUEUED,
            RemoteJobState.RENDERING,
        )


@dataclass
class Station:
    id: str = field(default_factory=lambda: f"RS-{uuid.uuid4().hex[:8]}")
    user_id: str = ""
    name: str = ""
    status: str = "offline"           # "online" | "offline" | "busy"
    last_seen: float = 0.0            # epoch seconds
    app_version: str = ""
    capabilities: Dict[str, Any] = field(default_factory=dict)
    local_ip: str = ""               # informational only
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def is_online(self, offline_after: float, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.last_seen) <= offline_after

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "Station":
        known = {f for f in Station.__dataclass_fields__}
        return Station(**{k: v for k, v in (row or {}).items() if k in known})


@dataclass
class RemoteJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str = ""
    station_id: str = ""
    display_label: str = ""
    project_name: str = ""
    sequence: str = ""
    preset: str = ""
    output_name: str = ""
    status: str = RemoteJobState.CREATED.value
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    output_filename: str = ""
    output_sha256: str = ""
    error: str = ""
    delete_after_delivery: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def state(self) -> RemoteJobState:
        try:
            return RemoteJobState(self.status)
        except ValueError:
            return RemoteJobState.CREATED

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "RemoteJob":
        known = {f for f in RemoteJob.__dataclass_fields__}
        return RemoteJob(**{k: v for k, v in (row or {}).items() if k in known})


@dataclass
class JobFile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    job_id: str = ""
    path: str = ""                    # relative path inside the project
    size: int = 0
    sha256: str = ""
    storage_path: str = ""           # object key in the bucket
    created_at: float = field(default_factory=time.time)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "JobFile":
        known = {f for f in JobFile.__dataclass_fields__}
        return JobFile(**{k: v for k, v in (row or {}).items() if k in known})


@dataclass
class JobEvent:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    job_id: str = ""
    event_type: str = ""
    message: str = ""
    created_at: float = field(default_factory=time.time)

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "JobEvent":
        known = {f for f in JobEvent.__dataclass_fields__}
        return JobEvent(**{k: v for k, v in (row or {}).items() if k in known})


@dataclass
class Session:
    """A signed-in session, persisted so users don't re-enter credentials."""

    user_id: str = ""
    username: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0

    @property
    def valid(self) -> bool:
        return bool(self.user_id and self.access_token)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Session":
        known = {f for f in Session.__dataclass_fields__}
        return Session(**{k: v for k, v in (d or {}).items() if k in known})
