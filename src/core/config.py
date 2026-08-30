"""Persisted application settings and platform directory helpers."""

from __future__ import annotations

import json
import os
import random
import socket
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

APP_NAME = "PremiereRenderApp"
IS_WINDOWS = sys.platform.startswith("win")


def app_data_dir() -> Path:
    """Per-user data directory (``%APPDATA%\\PremiereRenderApp`` on Windows).

    ``Folder.userData`` in ExtendScript resolves to ``%APPDATA%`` too, which is
    how the Python side and the Media Encoder agent script agree on where the
    job queue lives without any templating.
    """
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
    return Path.home() / "Videos" / "PremiereRenderApp"


def default_station_name() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "render-station"


def new_pairing_code() -> str:
    return f"{random.randint(0, 999999):06d}"


@dataclass
class AppConfig:
    role: str = "sender"
    tcp_port: int = 49872
    discovery_port: int = 49873
    chunk_size: int = 1024 * 1024
    log_level: str = "INFO"

    station_name: str = field(default_factory=default_station_name)
    workspace_dir: str = field(default_factory=lambda: str(default_workspace()))
    require_pairing: bool = True
    pairing_code: str = field(default_factory=new_pairing_code)
    autostart_station: bool = False
    broadcast_presence: bool = True
    ame_path: str = ""
    default_preset: str = ""
    render_timeout_minutes: int = 720
    keep_completed_jobs: int = 25
    retention_days: int = 0

    last_project_folder: str = ""
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    last_station_host: str = ""
    sender_name: str = field(default_factory=default_station_name)
    delete_remote_after_return: bool = False

    start_with_windows: bool = False
    first_run: bool = True

    @property
    def workspace(self) -> Path:
        return Path(self.workspace_dir)

    RETENTION_CHOICES = (
        ("Never", 0), ("1 day", 1), ("3 days", 3), ("7 days", 7),
        ("14 days", 14), ("30 days", 30),
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
    known = {f for f in AppConfig.__dataclass_fields__}
    return AppConfig(**{k: v for k, v in data.items() if k in known})


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
