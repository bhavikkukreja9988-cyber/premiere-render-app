"""Application object — the entry class the MVP referenced from ``main.py``.

Kept as ``PremiereRenderApp`` with a ``start()`` method so the original entry
point still works, but now it actually launches the GUI (or a headless render
station) instead of printing a line.
"""

from __future__ import annotations

import sys

from .core.config import AppConfig, load_config, save_config
from .core.log import get_logger, setup_logging

logger = get_logger("app")


class PremiereRenderApp:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.mode = "station" if self.config.role == "station" else "sender"
        setup_logging(self.config.log_level)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.config.role = "station" if mode == "station" else "sender"
        save_config(self.config)

    def start(self) -> int:
        """Launch the desktop UI. Returns the process exit code."""
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            print("PySide6 is not installed. Run: pip install -r requirements.txt",
                  file=sys.stderr)
            return 2
        from .ui.main_window import MainWindow

        logger.info("starting desktop app")
        qt_app = QApplication.instance() or QApplication(sys.argv)
        qt_app.setApplicationName("Premiere Render App")
        window = MainWindow(self.config)
        window.show()
        return qt_app.exec()

    def start_station(self) -> int:
        """Run a headless render station until interrupted."""
        import signal
        import time

        from .network.discovery import local_ip
        from .network.session import RenderStation

        station = RenderStation(self.config)
        port = station.start()
        print(f"Render station '{self.config.station_name}' online at "
              f"{local_ip()}:{port}")
        if self.config.require_pairing:
            print(f"Pairing code: {self.config.pairing_code}")
        print("Press Ctrl+C to stop.")

        stopping = {"now": False}
        signal.signal(signal.SIGINT, lambda *_: stopping.__setitem__("now", True))
        try:
            while not stopping["now"]:
                time.sleep(0.5)
        finally:
            station.stop()
        return 0
