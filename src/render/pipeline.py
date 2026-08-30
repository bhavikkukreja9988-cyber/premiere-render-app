"""Render backends and the worker that drains the station's job queue."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from ..core import workspace
from ..core.config import AppConfig
from ..core.jobs import JobRecord, JobState, JobStore
from ..core.log import get_logger
from . import media_encoder as ame
from .media_encoder import RenderError

logger = get_logger("render.pipeline")

ProgressFn = Callable[[float, str], None]
CancelFn = Callable[[], bool]


class RenderBackend:
    """Turns a received project folder into an encoded file."""

    name = "backend"

    def available(self) -> Tuple[bool, str]:
        return True, ""

    def render(self, record: JobRecord, job_root: Path,
               progress: ProgressFn, cancel: CancelFn) -> Path:
        raise NotImplementedError


def resolve_project_file(record: JobRecord, project_root: Path) -> Path:
    """Find the .prproj the sender asked for, falling back to the only one there."""
    relpath = record.spec.project_relpath
    if relpath:
        candidate = project_root / relpath
        if candidate.is_file():
            return candidate
    found = workspace.find_first(project_root, ".prproj")
    if found is None:
        raise RenderError("no .prproj file found in the transferred folder")
    return found


class AmeBackend(RenderBackend):
    """Drives Adobe Media Encoder through the installed ExtendScript agent."""

    name = "Adobe Media Encoder"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def available(self) -> Tuple[bool, str]:
        status = ame.probe(self.config.ame_path)
        if not status.exe:
            return False, "Adobe Media Encoder was not found on this PC"
        if not status.agent_installed:
            return False, "the Media Encoder agent script is not installed"
        return True, f"{status.exe} ({status.version or 'unknown version'})"

    def _preset_for(self, record: JobRecord, job_root: Path) -> str:
        spec = record.spec
        if spec.preset_source == "attached" and spec.preset_ref:
            attached = job_root / "project" / spec.preset_ref
            if attached.is_file():
                return str(attached)
            logger.warning("attached preset %s missing, falling back", spec.preset_ref)
        if spec.preset_source in ("station", "attached") and spec.preset_ref:
            resolved = ame.resolve_preset(spec.preset_ref)
            if resolved:
                return resolved
        return ame.resolve_preset(self.config.default_preset)

    def render(self, record: JobRecord, job_root: Path,
               progress: ProgressFn, cancel: CancelFn) -> Path:
        exe = ame.find_media_encoder(self.config.ame_path)
        if exe is None:
            raise RenderError("Adobe Media Encoder was not found on this PC")
        ame.install_agent()
        if not ame.is_ame_running():
            progress(0.0, "starting Media Encoder")
            ame.launch_ame(exe)
            for _ in range(60):
                if cancel():
                    raise RenderError("cancelled")
                if ame.is_ame_running():
                    break
                time.sleep(2)

        project = resolve_project_file(record, job_root / "project")
        output = job_root / "output" / record.spec.output_filename()
        preset = self._preset_for(record, job_root)
        logger.info("rendering %s (sequence=%r preset=%r) -> %s",
                    project.name, record.spec.sequence, preset, output.name)

        return ame.submit_and_wait(
            record.job_id, project, record.spec.sequence, preset, output,
            timeout_seconds=max(60, self.config.render_timeout_minutes * 60),
            progress=progress, cancel=cancel,
        )


class ManualBackend(RenderBackend):
    """No automation: an operator renders the job and drops the file in
    ``output/``. Keeps the app useful on a station without a working agent."""

    name = "Manual (watch output folder)"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def render(self, record: JobRecord, job_root: Path,
               progress: ProgressFn, cancel: CancelFn) -> Path:
        from .output_monitor import OutputMonitor

        out_dir = job_root / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        progress(0.0, f"waiting for a file in {out_dir}")
        monitor = OutputMonitor(out_dir)
        try:
            return monitor.wait_for_output(
                timeout=max(60, self.config.render_timeout_minutes * 60),
                progress=lambda message: progress(0.5, message),
                cancel=cancel,
            )
        except InterruptedError:
            raise RenderError("cancelled")
        except TimeoutError:
            raise RenderError("timed out waiting for a manually rendered file")


class RenderManager:
    """Single-worker queue drainer: QUEUED -> RENDERING -> ENCODED / FAILED."""

    def __init__(self, store: JobStore, backend: RenderBackend,
                 config: AppConfig,
                 on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        self.store = store
        self.backend = backend
        self.config = config
        self.on_event = on_event or (lambda kind, data: None)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._cancelled: Dict[str, bool] = {}
        self._current: Optional[str] = None

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="render-manager",
                                        daemon=True)
        self._thread.start()
        logger.info("render manager started (backend: %s)", self.backend.name)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def cancel(self, job_id: str) -> None:
        self._cancelled[job_id] = True

    @property
    def current_job(self) -> Optional[str]:
        return self._current

    @property
    def busy(self) -> bool:
        return self._current is not None

    # -- worker -----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            record = self.store.next_queued()
            if record is None:
                self._stop.wait(1.5)
                continue
            self._render_one(record)

    def _render_one(self, record: JobRecord) -> None:
        job_id = record.job_id
        self._current = job_id
        self._cancelled.pop(job_id, None)
        job_root = workspace.job_dir(self.config.workspace, job_id)

        def progress(value: float, message: str) -> None:
            self.store.update(job_id, progress=value, message=message)

        def cancelled() -> bool:
            return bool(self._cancelled.get(job_id)) or self._stop.is_set()

        self.store.update(job_id, state=JobState.RENDERING, progress=0.0,
                          message=f"rendering via {self.backend.name}")
        self.on_event("render_started", {"job_id": job_id})
        try:
            output = self.backend.render(record, job_root, progress, cancelled)
            self.store.update(job_id, state=JobState.ENCODED, progress=1.0,
                              message=f"encoded: {output.name}",
                              output_path=str(output))
            self.on_event("render_finished", {"job_id": job_id,
                                              "output": str(output)})
            logger.info("job %s encoded -> %s", job_id, output)
        except RenderError as exc:
            state = JobState.CANCELLED if str(exc) == "cancelled" else JobState.FAILED
            self.store.update(job_id, state=state, error=str(exc),
                              message=str(exc))
            self.on_event("render_failed", {"job_id": job_id, "error": str(exc)})
            logger.error("job %s failed: %s", job_id, exc)
        except Exception as exc:                       # noqa: BLE001
            self.store.update(job_id, state=JobState.FAILED, error=str(exc),
                              message=f"unexpected error: {exc}")
            self.on_event("render_failed", {"job_id": job_id, "error": str(exc)})
            logger.exception("job %s crashed the render worker", job_id)
        finally:
            self._current = None


def build_backend(config: AppConfig) -> RenderBackend:
    """Pick Media Encoder when it is usable, otherwise fall back to manual."""
    backend = AmeBackend(config)
    ok, detail = backend.available()
    if ok:
        logger.info("using Media Encoder backend: %s", detail)
        return backend
    logger.warning("Media Encoder unavailable (%s) - using manual backend", detail)
    return ManualBackend(config)
