"""Persisted application settings and platform directory helpers."""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

APP_NAME = "FileSender"
IS_WINDOWS = sys.platform.startswith("win")


def app_data_dir() -> Path:
    """Return the per-user FileSender data directory."""
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def default_workspace() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("SystemDrive", "C:") + "/PremiereRenderStation")
    return Path.home() / "PremiereRenderStation"


def default_output_dir() -> Path:
    return Path.home() / "Videos" / "FileSender"


def default_station_name() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "render-station"


@dataclass
class AppConfig:
    """User/device configuration for the Remote V3 application."""

    # General
    log_level: str = "INFO"
    start_with_windows: bool = False
    first_run: bool = True

    # Render Station
    station_name: str = field(default_factory=default_station_name)
    workspace_dir: str = field(default_factory=lambda: str(default_workspace()))
    station_id: str = field(default_factory=lambda: f"RS-{uuid.uuid4().hex[:8]}")
    station_role_enabled: bool = True
    accept_jobs_automatically: bool = True
    retention_days: int = 0
    render_timeout_minutes: int = 720
    keep_completed_jobs: int = 25
    ame_path: str = ""
    default_preset: str = ""

    # Sender
    sender_name: str = field(default_factory=default_station_name)
    last_project_folder: str = ""
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    last_station_id: str = ""
    delete_remote_after_return: bool = False

    # Remote identity / session UI
    remote_username: str = ""

    @property
    def workspace(self) -> Path:
        return Path(self.workspace_dir)

    RETENTION_CHOICES = (
        ("Never", 0),
        ("1 day", 1),
        ("3 days", 3),
        ("7 days", 7),
        ("14 days", 14),
        ("30 days", 30),
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def config_path() -> Path:
    return app_data_dir() / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppConfig()
    known = set(AppConfig.__dataclass_fields__)
    values = {key: value for key, value in data.items() if key in known}
    return AppConfig(**values)


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
