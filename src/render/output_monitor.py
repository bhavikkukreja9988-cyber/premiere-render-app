"""Watch an output folder for a finished render.

A render is "done" when a video file appears and then stops growing for a short
settle period — the same rule the render pipeline uses. This keeps the MVP's
``OutputMonitor`` name and ``check()`` method, and adds a blocking
``wait_for_output`` used by the manual render backend.

``watchdog`` is used when installed (it is in requirements) but the monitor
falls back to plain polling if it is missing, so nothing hard-depends on it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

VIDEO_SUFFIXES = (".mp4", ".mov", ".mxf", ".m4v", ".avi", ".mkv", ".wav", ".mp3")
SETTLE_SECONDS = 12.0
POLL_SECONDS = 2.0


def newest_output(folder: Path, since: float = 0.0) -> Optional[Path]:
    """Newest renderable file in ``folder`` modified at/after ``since``."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    candidates = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
        and p.stat().st_mtime >= since - 2
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


class OutputMonitor:
    def __init__(self, folder: Optional[Path] = None) -> None:
        self.folder = Path(folder) if folder else None
        self._since = time.time()

    def reset(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._since = time.time()

    def check(self) -> Optional[Path]:
        """Return a finished file if one is present and stable, else ``None``."""
        if self.folder is None:
            return None
        candidate = newest_output(self.folder, self._since)
        if candidate is None:
            return None
        size = candidate.stat().st_size
        if size == 0:
            return None
        time.sleep(min(SETTLE_SECONDS, 3.0))
        try:
            if candidate.stat().st_size == size:
                return candidate
        except OSError:
            return None
        return None

    def wait_for_output(self, timeout: float,
                        progress: Optional[Callable[[str], None]] = None,
                        cancel: Optional[Callable[[], bool]] = None) -> Path:
        """Block until a stable output file appears, or raise ``TimeoutError``."""
        if self.folder is None:
            raise ValueError("no folder set")
        deadline = time.time() + timeout
        last_size = -1
        stable_since: Optional[float] = None
        while time.time() < deadline:
            if cancel and cancel():
                raise InterruptedError("cancelled")
            candidate = newest_output(self.folder, self._since)
            if candidate is not None:
                size = candidate.stat().st_size
                if size > 0 and size == last_size:
                    stable_since = stable_since or time.time()
                    if time.time() - stable_since >= SETTLE_SECONDS:
                        return candidate
                else:
                    stable_since = None
                    last_size = size
                    if progress:
                        progress(f"receiving {candidate.name}")
            time.sleep(POLL_SECONDS)
        raise TimeoutError("no finished file appeared in time")
