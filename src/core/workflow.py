"""High-level workflow state shared by the UI and the core.

The MVP shipped this as a stub (an ``Idle`` string). It is now a small, real
state machine with immutable snapshots, which is what the UI binds to and what
``tests/test_core.py`` exercises.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional


class WorkflowState(str, Enum):
    IDLE = "Idle"
    CONNECTING = "Connecting"
    SCANNING = "Scanning"
    TRANSFERRING = "Transferring"
    QUEUED = "Queued"
    RENDERING = "Rendering"
    RETURNING = "Returning"
    COMPLETE = "Complete"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass(frozen=True)
class WorkflowSnapshot:
    state: WorkflowState
    message: str = ""
    progress: int = 0            # 0..100
    at: float = 0.0


class Workflow:
    """Thread-safe current-state holder with change notification."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot = WorkflowSnapshot(WorkflowState.IDLE, "", 0, time.time())
        self._listeners: List[Callable[[WorkflowSnapshot], None]] = []

    def subscribe(self, callback: Callable[[WorkflowSnapshot], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def update(self, state: WorkflowState, message: str = "",
               progress: Optional[int] = None) -> WorkflowSnapshot:
        with self._lock:
            if progress is None:
                progress = self._snapshot.progress
            progress = max(0, min(100, int(progress)))
            self._snapshot = WorkflowSnapshot(state, message, progress, time.time())
            listeners = list(self._listeners)
            snapshot = self._snapshot
        for callback in listeners:
            try:
                callback(snapshot)
            except Exception:
                pass
        return snapshot

    def get(self) -> WorkflowSnapshot:
        with self._lock:
            return self._snapshot
