"""Adobe Media Encoder control.

Media Encoder has no supported command line, so automation goes through its
ExtendScript startup-script hook: we install ``PremiereRenderAgent.jsx`` into
the per-user startup scripts folder, and the agent polls a queue directory for
jobs. Python writes jobs, the agent renders them, and both sides communicate
through small key=value files under ``%APPDATA%/PremiereRenderApp/ame``.

Because a scripting bridge inside a GUI application is never fully reliable,
completion is detected two ways at once: the agent's status file *and* a direct
watch on the output file (appears, then stops growing). Either one is enough.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..core.config import IS_WINDOWS, app_data_dir
from ..core.log import get_logger

logger = get_logger("render.ame")

AGENT_FILENAME = "PremiereRenderAgent.jsx"
STABLE_SECONDS = 12.0          # output must stop growing this long to count as done
POLL_SECONDS = 2.0

VIDEO_SUFFIXES = (".mp4", ".mov", ".mxf", ".m4v", ".avi", ".mkv", ".wav", ".mp3")


class RenderError(RuntimeError):
    """Raised when Media Encoder fails, refuses or never produces a job."""


@dataclass
class AmeStatus:
    exe: str = ""
    version: str = ""
    agent_installed: bool = False
    agent_version: str = ""
    agent_alive: bool = False
    running: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.exe) and self.agent_installed


# -- discovery -------------------------------------------------------------
def _candidate_roots() -> List[Path]:
    roots: List[Path] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value) / "Adobe")
    roots.append(Path("C:/Program Files/Adobe"))
    unique: List[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def find_media_encoder(explicit: str = "") -> Optional[Path]:
    """Locate ``Adobe Media Encoder.exe``.

    Order: explicit setting, ``ADOBE_MEDIA_ENCODER`` env var, then the standard
    install roots, newest version first.
    """
    for candidate in (explicit, os.environ.get("ADOBE_MEDIA_ENCODER", "")):
        if candidate:
            path = Path(candidate)
            if path.is_file():
                return path

    found: List[Tuple[float, Path]] = []
    for root in _candidate_roots():
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or "media encoder" not in child.name.lower():
                continue
            for exe in (child / "Adobe Media Encoder.exe",
                        child / "Support Files" / "Adobe Media Encoder.exe"):
                if exe.is_file():
                    match = re.search(r"(\d{4}|\d+\.\d+)", child.name)
                    rank = float(match.group(1)) if match else 0.0
                    found.append((rank, exe))
    if not found:
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def ame_version_from_path(exe: Optional[Path]) -> str:
    if not exe:
        return ""
    for part in exe.parts:
        match = re.search(r"Media Encoder\s+(.+)$", part, flags=re.I)
        if match:
            return match.group(1).strip()
    return ""


def is_ame_running() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        output = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Adobe Media Encoder.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "Adobe Media Encoder.exe" in output


def launch_ame(exe: Path) -> None:
    """Start Media Encoder in the background without stealing focus.

    This is the "don't disturb me while I'm working" requirement: the station
    operator should be able to keep using their PC while jobs render. We ask
    Windows to open the window minimised and not to activate it, so Media
    Encoder starts behind whatever the operator is doing.
    """
    logger.info("launching Media Encoder (background): %s", exe)
    kwargs = {"cwd": str(exe.parent)}
    if IS_WINDOWS:
        SW_SHOWMINNOACTIVE = 7
        STARTF_USESHOWWINDOW = 0x00000001
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_SHOWMINNOACTIVE
        kwargs["startupinfo"] = startupinfo
        # DETACHED so closing our app never takes Media Encoder down with it;
        # BELOW_NORMAL so a long render leaves CPU for foreground work.
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        )
    try:
        subprocess.Popen([str(exe)], **kwargs)
    except OSError as exc:
        logger.error("could not launch Media Encoder: %s", exc)
        raise


# -- agent plumbing --------------------------------------------------------
def agent_base() -> Path:
    """Must match ``Folder.userData/PremiereRenderApp/ame`` inside the JSX."""
    return app_data_dir() / "ame"


def agent_dirs() -> Dict[str, Path]:
    base = agent_base()
    return {"base": base, "queue": base / "queue", "status": base / "status"}


def ensure_agent_dirs() -> Dict[str, Path]:
    dirs = agent_dirs()
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def startup_scripts_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Adobe" / "Startup Scripts CC" / "Adobe Media Encoder"


def bundled_agent_source() -> Path:
    """Where the agent .jsx lives, both from source and inside a frozen build."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "src" / "render" / "jsx" / AGENT_FILENAME
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parent / "jsx" / AGENT_FILENAME


def _agent_version(text: str) -> str:
    match = re.search(r'AGENT_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def install_agent(force: bool = False) -> Path:
    """Copy the agent into the AME startup-scripts folder. Returns its path."""
    source = bundled_agent_source()
    if not source.is_file():
        raise RenderError(f"agent script missing from build: {source}")
    target_dir = startup_scripts_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / AGENT_FILENAME

    if target.exists() and not force:
        current = _agent_version(target.read_text(encoding="utf-8", errors="ignore"))
        newest = _agent_version(source.read_text(encoding="utf-8", errors="ignore"))
        if current == newest:
            return target
    shutil.copy2(source, target)
    ensure_agent_dirs()
    logger.info("installed Media Encoder agent -> %s", target)
    return target


def uninstall_agent() -> None:
    target = startup_scripts_dir() / AGENT_FILENAME
    if target.exists():
        target.unlink()


def agent_status() -> Tuple[bool, str, bool]:
    """(installed, version, alive-recently)."""
    target = startup_scripts_dir() / AGENT_FILENAME
    installed = target.is_file()
    version = _agent_version(target.read_text(encoding="utf-8", errors="ignore")) \
        if installed else ""
    alive_file = agent_base() / "agent.alive"
    alive = alive_file.is_file() and is_ame_running()
    return installed, version, alive


def probe(explicit_exe: str = "") -> AmeStatus:
    exe = find_media_encoder(explicit_exe)
    installed, version, alive = agent_status()
    status = AmeStatus(
        exe=str(exe) if exe else "",
        version=ame_version_from_path(exe),
        agent_installed=installed,
        agent_version=version,
        agent_alive=alive,
        running=is_ame_running(),
    )
    if not exe:
        status.notes.append(
            "Media Encoder not found. Set its full path in Settings or the "
            "ADOBE_MEDIA_ENCODER environment variable.")
    if not installed:
        status.notes.append(
            "Agent script not installed. Click 'Install Media Encoder agent'.")
    elif not alive:
        status.notes.append(
            "Agent installed but not reporting. Restart Media Encoder, and enable "
            "Preferences > General > 'Allow Scripts to Write Files and Access "
            "Network'.")
    return status


# -- presets ---------------------------------------------------------------
def preset_dirs() -> List[Path]:
    dirs: List[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = Path(appdata) / "Adobe" / "Adobe Media Encoder"
        if root.is_dir():
            for version_dir in sorted(root.iterdir(), reverse=True):
                presets = version_dir / "Presets"
                if presets.is_dir():
                    dirs.append(presets)
    dirs.append(app_data_dir() / "presets")
    return dirs


def list_presets() -> List[Tuple[str, str]]:
    """Return ``[(display name, absolute path)]`` for every .epr we can see."""
    seen: Dict[str, str] = {}
    for directory in preset_dirs():
        if not directory.is_dir():
            continue
        for epr in sorted(directory.rglob("*.epr")):
            seen.setdefault(epr.stem, str(epr))
    return sorted(seen.items())


def resolve_preset(reference: str) -> str:
    """Accept a preset name or an absolute .epr path; return a path or ''."""
    if not reference:
        return ""
    path = Path(reference)
    if path.is_file():
        return str(path)
    for name, location in list_presets():
        if name.lower() == reference.strip().lower():
            return location
    return ""


# -- job submission --------------------------------------------------------
def _write_job_file(job_id: str, project: Path, sequence: str,
                    preset: str, output: Path) -> Path:
    dirs = ensure_agent_dirs()
    lines = [
        f"job_id={job_id}",
        f"project={project.resolve().as_posix()}",
        f"sequence={sequence or ''}",
        f"preset={Path(preset).as_posix() if preset else ''}",
        f"output={output.resolve().as_posix()}",
        f"created={int(time.time())}",
    ]
    tmp = dirs["queue"] / f"{job_id}.job.tmp"
    final = dirs["queue"] / f"{job_id}.job"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(final)                      # atomic: the agent never sees a half file
    return final


def read_status(job_id: str) -> Dict[str, str]:
    path = agent_dirs()["status"] / f"{job_id}.status"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    result: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def clear_job(job_id: str) -> None:
    dirs = agent_dirs()
    for path in (dirs["queue"] / f"{job_id}.job",
                 dirs["status"] / f"{job_id}.status"):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def newest_output(output_dir: Path, since: float) -> Optional[Path]:
    """Newest renderable file written into ``output_dir`` after ``since``."""
    if not output_dir.is_dir():
        return None
    candidates = [
        path for path in output_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in VIDEO_SUFFIXES
        and path.stat().st_mtime >= since - 2
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def submit_and_wait(job_id: str, project: Path, sequence: str, preset: str,
                    output: Path, timeout_seconds: float = 43200.0,
                    progress: Optional[Callable[[float, str], None]] = None,
                    cancel: Optional[Callable[[], bool]] = None) -> Path:
    """Hand a job to Media Encoder and block until the file is written."""
    output.parent.mkdir(parents=True, exist_ok=True)
    clear_job(job_id)
    started = time.time()
    _write_job_file(job_id, project, sequence, preset, output)
    if progress:
        progress(0.0, "waiting for Media Encoder to accept the job")

    accepted = False
    last_size = -1
    stable_since: Optional[float] = None
    deadline = started + timeout_seconds

    while True:
        if cancel and cancel():
            clear_job(job_id)
            raise RenderError("cancelled")
        if time.time() > deadline:
            clear_job(job_id)
            raise RenderError("render timed out")

        status = read_status(job_id)
        state = status.get("state", "")
        if state == "error":
            clear_job(job_id)
            raise RenderError(status.get("message", "Media Encoder reported an error"))
        if state in ("accepted", "rendering") and not accepted:
            accepted = True
            if progress:
                progress(0.02, "Media Encoder accepted the job")
        if state == "rendering" and progress:
            try:
                progress(max(0.02, min(0.98, float(status.get("progress", 0.0)))),
                         "rendering")
            except ValueError:
                pass

        produced = output if output.exists() else newest_output(output.parent, started)
        if produced is not None and produced.exists():
            size = produced.stat().st_size
            if size > 0 and size == last_size:
                stable_since = stable_since or time.time()
                if time.time() - stable_since >= STABLE_SECONDS:
                    if progress:
                        progress(1.0, "render complete")
                    clear_job(job_id)
                    return produced
            else:
                stable_since = None
                last_size = size
                if progress and not accepted:
                    progress(0.5, "writing output")

        if state == "complete" and produced is not None and produced.exists():
            # Give the muxer a beat to flush, then accept the agent's word.
            time.sleep(3)
            if progress:
                progress(1.0, "render complete")
            clear_job(job_id)
            return produced

        if not accepted and time.time() - started > 180 and produced is None:
            clear_job(job_id)
            raise RenderError(
                "Media Encoder never picked up the job. Check that it is running, "
                "that the agent script is installed, and that scripting is allowed "
                "in its preferences.")

        time.sleep(POLL_SECONDS)
