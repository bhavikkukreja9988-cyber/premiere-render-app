"""Directory layout for a render station workspace.

    <workspace>/
        jobs.json                  persisted job table
        jobs/<job_id>/project/     the received Premiere project folder
        jobs/<job_id>/output/      encoded files land here
        jobs/<job_id>/preset.epr   optional preset attached by the sender
        presets/                   station-side .epr library
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional


def ensure_workspace(root: Path) -> Path:
    root = Path(root)
    for sub in ("jobs", "presets"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def jobs_file(root: Path) -> Path:
    return Path(root) / "jobs.json"


def job_dir(root: Path, job_id: str) -> Path:
    return Path(root) / "jobs" / job_id


def project_dir(root: Path, job_id: str) -> Path:
    return job_dir(root, job_id) / "project"


def output_dir(root: Path, job_id: str) -> Path:
    return job_dir(root, job_id) / "output"


def prepare_job_dirs(root: Path, job_id: str) -> Path:
    directory = job_dir(root, job_id)
    (directory / "project").mkdir(parents=True, exist_ok=True)
    (directory / "output").mkdir(parents=True, exist_ok=True)
    return directory


def remove_job_dir(root: Path, job_id: str) -> None:
    shutil.rmtree(job_dir(root, job_id), ignore_errors=True)


def free_space_bytes(root: Path) -> int:
    try:
        return shutil.disk_usage(str(root)).free
    except OSError:
        return 0


def human_bytes(count: float) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(count) < step or unit == "TB":
            return f"{count:,.1f} {unit}" if unit != "B" else f"{int(count)} B"
        count /= step
    return f"{count:,.1f} TB"


def find_first(directory: Path, suffix: str) -> Optional[Path]:
    matches = sorted(Path(directory).rglob(f"*{suffix}"),
                     key=lambda p: (len(p.parts), p.name.lower()))
    return matches[0] if matches else None
