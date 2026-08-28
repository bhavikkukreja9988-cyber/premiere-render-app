from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Callable


class WorkflowState(str, Enum):
    IDLE = "Idle"
    CONNECTING = "Connecting"
    TRANSFERRING = "Transferring"
    RECEIVING = "Receiving"
    RENDERING = "Rendering"
    RETURNING = "Returning"
    COMPLETED = "Completed"
    ERROR = "Error"


@dataclass(frozen=True)
class WorkflowSnapshot:
    state: WorkflowState
    message: str = ""
    progress: int = 0


class Workflow:
    def __init__(self) -> None:
        self._snapshot = WorkflowSnapshot(WorkflowState.IDLE)
        self._lock = Lock()
        self._listeners: list[Callable[[WorkflowSnapshot], None]] = []

    def subscribe(self, listener: Callable[[WorkflowSnapshot], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def update(self, state: WorkflowState | str, message: str = "", progress: int | None = None) -> WorkflowSnapshot:
        if not isinstance(state, WorkflowState):
            state = WorkflowState(state)
        with self._lock:
            old = self._snapshot
            snapshot = WorkflowSnapshot(state, message, old.progress if progress is None else max(0, min(100, progress)))
            self._snapshot = snapshot
            listeners = list(self._listeners)
        for listener in listeners:
            listener(snapshot)
        return snapshot

    def get(self) -> WorkflowSnapshot:
        with self._lock:
            return self._snapshot