from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Callable


@dataclass
class TransferProgress:
    status: str = "Idle"
    progress: int = 0
    bytes_done: int = 0
    total_bytes: int = 0
    message: str = ""


class TransferEngine:
    def __init__(self) -> None:
        self._progress = TransferProgress()
        self._lock = Lock()
        self.cancel_event = Event()
        self.listeners: list[Callable[[TransferProgress], None]] = []

    def subscribe(self, listener: Callable[[TransferProgress], None]) -> None:
        self.listeners.append(listener)

    def _emit(self, state: TransferProgress) -> None:
        for listener in self.listeners:
            listener(state)

    @property
    def progress(self) -> int:
        with self._lock:
            return self._progress.progress

    @property
    def status(self) -> str:
        with self._lock:
            return self._progress.status

    def start(self, total_bytes: int = 0, message: str = "") -> None:
        self.cancel_event.clear()
        self._set(TransferProgress("Transferring", 0, 0, total_bytes, message))

    def update(self, value: int, bytes_done: int | None = None, message: str = "") -> None:
        with self._lock:
            current = self._progress
            new = TransferProgress("Transferring", max(0, min(100, value)), current.bytes_done if bytes_done is None else bytes_done, current.total_bytes, message)
        self._set(new)

    def complete(self, message: str = "") -> None:
        with self._lock:
            total = self._progress.total_bytes
            done = total or self._progress.bytes_done
        self._set(TransferProgress("Completed", 100, done, total, message))

    def fail(self, message: str) -> None:
        self._set(TransferProgress("Error", self.progress, self._progress.bytes_done, self._progress.total_bytes, message))

    def cancel(self) -> None:
        self.cancel_event.set()
        self._set(TransferProgress("Cancelled", self.progress, self._progress.bytes_done, self._progress.total_bytes, "Cancelled by user"))

    def _set(self, state: TransferProgress) -> None:
        with self._lock:
            self._progress = state
        self._emit(state)

    def transmit_file(self, source: str | Path, writer: Callable[[bytes], None], chunk_size: int = 1024 * 1024) -> None:
        path = Path(source)
        total = path.stat().st_size
        self.start(total)
        sent = 0
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(chunk_size):
                    if self.cancel_event.is_set():
                        return
                    writer(chunk)
                    sent += len(chunk)
                    percent = int(sent * 100 / total) if total else 100
                    self.update(percent, sent, path.name)
            self.complete(path.name)
        except Exception as exc:
            self.fail(str(exc))
            raise