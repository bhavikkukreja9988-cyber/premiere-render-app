"""Plugin inbox — job requests handed over from the Premiere Pro panel.

The UXP plugin can't upload anything itself (sandboxed JS runtime, no access
to our Supabase stack), so it drops a small JSON file here and launches the
app. This module turns those files into normal send requests, reusing the
exact same path a manual send takes — nothing about the transfer, hashing or
tracking is duplicated.

Contract with the plugin (src/main.js writes this):

    %APPDATA%/FileSender/inbox/job-<timestamp>.json
    {
      "source": "premiere-uxp-plugin",
      "project_path": "C:/Edits/MyFilm/MyFilm.prproj",
      "project_name": "MyFilm.prproj",
      "sequence": "Main Timeline",
      "station_id": "RS-a1b2c3d4",
      "preset": "H.264 High",
      "output_name": "MyFilm_v3"
    }

The plugin writes to a .tmp name and renames, so a file appearing with a
.json suffix is always complete.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .config import app_data_dir
from .log import get_logger

logger = get_logger("core.plugin_inbox")

POLL_SECONDS = 2.0
#: Job files older than this are ignored — a stale file from a crashed
#: session shouldn't suddenly start an upload days later.
MAX_AGE_SECONDS = 3600.0


@dataclass
class PluginJobRequest:
    """One send request handed over by the Premiere plugin."""

    project_path: str
    project_name: str = ""
    sequence: str = ""
    station_id: str = ""
    preset: str = ""
    output_name: str = ""
    source_file: Optional[Path] = None

    @property
    def project_folder(self) -> Path:
        """The folder to send — the directory containing the .prproj."""
        return Path(self.project_path).parent

    @property
    def valid(self) -> bool:
        path = Path(self.project_path)
        return bool(self.project_path) and path.is_file() and path.suffix.lower() == ".prproj"


def inbox_dir() -> Path:
    return app_data_dir() / "inbox"


def ensure_inbox() -> Path:
    directory = inbox_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _parse(path: Path) -> Optional[PluginJobRequest]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("ignoring unreadable job file %s: %s", path.name, exc)
        return None

    if not isinstance(data, dict):
        return None

    request = PluginJobRequest(
        project_path=str(data.get("project_path", "")),
        project_name=str(data.get("project_name", "")),
        sequence=str(data.get("sequence", "")),
        station_id=str(data.get("station_id", "")),
        preset=str(data.get("preset", "")),
        output_name=str(data.get("output_name", "")),
        source_file=path,
    )
    return request


def read_pending() -> List[PluginJobRequest]:
    """Return every complete, still-fresh job file, oldest first.

    Files are consumed (deleted) by :func:`consume`, not here, so a caller
    that fails to act on a request doesn't silently lose it.
    """
    directory = inbox_dir()
    if not directory.is_dir():
        return []

    requests: List[PluginJobRequest] = []
    now = time.time()
    for path in sorted(directory.glob("job-*.json")):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age > MAX_AGE_SECONDS:
            logger.info("discarding stale plugin job %s (%.0f min old)",
                        path.name, age / 60)
            _discard(path)
            continue
        request = _parse(path)
        if request is None:
            _discard(path)
            continue
        requests.append(request)
    return requests


def consume(request: PluginJobRequest) -> None:
    """Delete a request's file once it has been acted on."""
    if request.source_file:
        _discard(request.source_file)


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("could not remove %s: %s", path, exc)


class PluginInboxWatcher:
    """Polls the inbox and hands new requests to a callback.

    Polling rather than filesystem events: the inbox sees a file every few
    minutes at most, the directory is tiny, and polling behaves identically
    whether the folder is local, synced, or on a network share.
    """

    def __init__(self, on_request: Callable[[PluginJobRequest], None]) -> None:
        self.on_request = on_request
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ensure_inbox()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="plugin-inbox",
                                        daemon=True)
        self._thread.start()
        logger.info("watching plugin inbox at %s", inbox_dir())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for request in read_pending():
                    try:
                        self.on_request(request)
                    except Exception:                        # noqa: BLE001
                        logger.exception("plugin job handler failed")
                    finally:
                        # Consume either way: a request that crashed the
                        # handler would otherwise retry forever every tick.
                        consume(request)
            except Exception:                                # noqa: BLE001
                logger.exception("plugin inbox sweep failed")
            self._stop.wait(POLL_SECONDS)
