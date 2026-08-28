from __future__ import annotations

import time
from pathlib import Path
from threading import Event, Thread
from typing import Callable


class OutputMonitor:
    def __init__(self, poll_interval: float = 1.0) -> None:
        self.poll_interval = poll_interval
        self._stop = Event()
        self._thread: Thread | None = None

    def find_latest(self, directory: str | Path, extensions: tuple[str, ...] = (".mp4", ".mov", ".mxf")) -> Path | None:
        folder = Path(directory)
        if not folder.exists():
            return None
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in extensions]
        return max(files, key=lambda p: p.stat().st_mtime, default=None)

    def watch(self, directory: str | Path, on_found: Callable[[Path], None], timeout: float | None = None) -> None:
        folder = Path(directory)
        started = time.monotonic()
        baseline = {p.name: p.stat().st_size for p in folder.glob("*") if p.is_file()}
        self._stop.clear()
        while not self._stop.is_set():
            candidates = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mxf"}] if folder.exists() else []
            for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
                old_size = baseline.get(path.name)
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if old_size is None or size != old_size:
                    if self._is_stable(path):
                        on_found(path)
                        return
            if timeout is not None and time.monotonic() - started >= timeout:
                return
            time.sleep(self.poll_interval)

    def start(self, directory: str | Path, on_found: Callable[[Path], None], timeout: float | None = None) -> None:
        self.stop()
        self._thread = Thread(target=self.watch, args=(directory, on_found, timeout), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _is_stable(self, path: Path) -> bool:
        try:
            first = path.stat().st_size
            time.sleep(min(self.poll_interval, 0.5))
            second = path.stat().st_size
            return first == second and first > 0
        except OSError:
            return False