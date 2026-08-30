"""Logging: a rotating file in the app data dir plus an in-memory ring buffer
that the UI log tab reads from."""

from __future__ import annotations

import collections
import logging
import logging.handlers
import threading
from typing import Callable, Deque, List, Optional

from .config import app_data_dir

_configured = False
_lock = threading.Lock()


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.records: Deque[str] = collections.deque(maxlen=capacity)
        self._subscribers: List[Callable[[str], None]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        self.records.append(line)
        for callback in list(self._subscribers):
            try:
                callback(line)
            except Exception:
                pass

    def subscribe(self, callback: Callable[[str], None]) -> None:
        self._subscribers.append(callback)

    def tail(self, count: int = 500) -> List[str]:
        return list(self.records)[-count:]


ring = RingBufferHandler()


def setup_logging(level: str = "INFO", log_dir: Optional[str] = None) -> None:
    global _configured
    with _lock:
        if _configured:
            logging.getLogger().setLevel(level.upper())
            return
        fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
                                datefmt="%H:%M:%S")
        root = logging.getLogger()
        root.setLevel(level.upper())

        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)

        ring.setFormatter(fmt)
        root.addHandler(ring)

        try:
            from pathlib import Path
            directory = Path(log_dir) if log_dir else app_data_dir() / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                directory / "app.log", maxBytes=2_000_000, backupCount=3,
                encoding="utf-8")
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except OSError:
            pass

        _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
