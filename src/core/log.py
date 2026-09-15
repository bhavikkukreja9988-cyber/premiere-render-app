"""Logging: a rotating file in the app data dir plus an in-memory ring buffer
that the UI log tab reads from."""

from __future__ import annotations

import collections
import logging
import logging.handlers
from datetime import datetime
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

            current = directory / "app.log"
            previous = directory / "app-previous.log"

            # Start a FRESH log every launch, so a log sent for diagnosis
            # contains exactly one run and nothing else. The immediately
            # previous run is kept as a single backup — often the crash you
            # care about happened just before the restart.
            if current.exists():
                try:
                    if previous.exists():
                        previous.unlink()
                    current.replace(previous)
                except OSError:
                    pass

            # mode="w" (not append): belt and braces if the rename above
            # failed for any reason, e.g. the file was locked.
            file_handler = logging.FileHandler(current, mode="w",
                                               encoding="utf-8")
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)

            # Anchor the file so it's obvious which run is which when
            # several logs get sent at once.
            logging.getLogger("core.log").info(
                "=== FileSender %s starting — log began %s ===",
                _app_version(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except OSError:
            pass

        _configured = True


def _app_version() -> str:
    try:
        from .. import __version__
        return __version__
    except Exception:                                        # noqa: BLE001
        return "unknown"


def log_file_path():
    """Path of the current run's log file (may not exist yet)."""
    from pathlib import Path
    return app_data_dir() / "logs" / "app.log"


def previous_log_file_path():
    """Path of the previous run's log, kept for one restart."""
    from pathlib import Path
    return app_data_dir() / "logs" / "app-previous.log"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
