"""Application entry for the FileSender desktop client."""

from __future__ import annotations

import sys

from .core.config import AppConfig, load_config
from .core.log import logger, setup_logging


class PremiereRenderApp:
    """Launch the single FileSender desktop application."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        setup_logging(self.config.log_level)

    def start(self) -> int:
        """Launch the desktop UI and return the process exit code."""
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            print(
                "PySide6 is not installed. Run: pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 2

        from .ui.main_window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("FileSender")
        app.setApplicationDisplayName("FileSender")
        window = MainWindow(self.config)
        window.show()
        return app.exec()
