from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EncoderInfo:
    found: bool
    path: str | None


class MediaEncoder:
    DEFAULT_PATHS = (
        r"C:\Program Files\Adobe\Adobe Media Encoder\Adobe Media Encoder.exe",
        r"C:\Program Files\Adobe\Adobe Media Encoder 2025\Adobe Media Encoder.exe",
        r"C:\Program Files\Adobe\Adobe Media Encoder 2026\Adobe Media Encoder.exe",
    )

    def detect(self) -> EncoderInfo:
        env_path = os.environ.get("ADOBE_MEDIA_ENCODER")
        candidates = [env_path] if env_path else []
        candidates.extend(self.DEFAULT_PATHS)
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return EncoderInfo(True, str(Path(candidate)))
        return EncoderInfo(False, shutil.which("Adobe Media Encoder"))

    def queue(self, project: str | Path) -> dict:
        return {"project": str(project), "status": "Queued"}

    def start(self, project: str | Path | None = None) -> str:
        info = self.detect()
        if not info.found:
            return "EncoderNotFound"
        if project is not None:
            subprocess.Popen([info.path, str(project)], close_fds=True)
        else:
            subprocess.Popen([info.path], close_fds=True)
        return "Launching"