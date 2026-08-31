"""Start-with-Windows support.

Uses the per-user ``Run`` registry key so no admin rights are needed and it only
affects the current user. A no-op on non-Windows platforms.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import IS_WINDOWS
from .log import get_logger

logger = get_logger("core.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PremiereRenderApp"


def _launch_command() -> str:
    """The command Windows should run at login."""
    if getattr(sys, "frozen", False):
        # Installed app: run the packaged executable directly.
        return f'"{Path(sys.executable).resolve()}"'
    # Running from source: launch via the interpreter.
    return f'"{Path(sys.executable).resolve()}" -m src.main'


def set_start_with_windows(enabled: bool) -> bool:
    """Enable or disable launch at login. Returns True on success."""
    if not IS_WINDOWS:
        logger.info("start-with-Windows requested on a non-Windows OS; ignoring")
        return False
    try:
        import winreg  # type: ignore
    except ImportError:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE)
    except FileNotFoundError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
    try:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
            logger.info("registered start-with-Windows")
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
                logger.info("removed start-with-Windows")
            except FileNotFoundError:
                pass
        return True
    finally:
        winreg.CloseKey(key)


def is_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        try:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except (ImportError, OSError):
        return False
