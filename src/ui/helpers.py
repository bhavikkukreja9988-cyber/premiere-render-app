"""Small shared UI helpers.

``open_in_file_manager`` used to live in the legacy ``sender_panel.py``, which
was removed with the rest of the LAN code. It isn't LAN-specific, and two
panels still need it, so it lives here now rather than being duplicated or
re-attached to some unrelated panel.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..core.log import get_logger

logger = get_logger("ui.helpers")


def open_in_file_manager(path: Path) -> None:
    """Reveal a file or folder in the OS file manager. Never raises."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        logger.warning("could not open %s: %s", path, exc)
