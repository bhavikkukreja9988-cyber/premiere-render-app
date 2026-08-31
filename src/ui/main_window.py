from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..core.config import AppConfig, save_config
from ..core.log import get_logger, ring
from .first_run import FirstRunDialog
from .history_panel import JobHistoryPanel
from .pending_jobs_panel import PendingJobsPanel
from .remote_login import LoginDialog
from .remote_sender_panel import RemoteSenderPanel
from .sender_panel import SenderPanel
from .settings_panel import SettingsPanel
from .station_panel import StationPanel
from .theme import STYLESHEET

logger = get_logger("ui.main_window")


def _icon_path() -> Path:
    """Resolve the bundled Windows icon in source and PyInstaller builds."""
    if hasattr(sys, "_MEIPASS"):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        # src/ui/main_window.py -> repository root
        base = Path(__file__).resolve().parents[2]
    return base / "assets" / "FileSender.ico"


class LogPanel(QWidget):
    line_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setPlainText("\n".join(ring.tail(400)))

        buttons = QHBoxLayout()
        clear = QPushButton("Clear view")
        clear.clicked.connect(self.view.clear)
        hint = QLabel("Logs are also written to the app data folder.")
        hint.setObjectName("hint")
        buttons.addWidget(clear)
        buttons.addWidget(hint, 1)

        layout.addWidget(self.view)
        layout.addLayout(buttons)
        self.line_signal.connect(self.view.appendPlainText)
        ring.subscribe(lambda line: self.line_signal.emit(line))


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle(f"FileSender {__version__}")
        self.resize(1040, 860)
        self.setStyleSheet(STYLESHEET)

        # Set the application/window icon so the title bar and Windows taskbar
        # use the same FileSender branding as the executable/shortcuts.
        icon = _icon_path()
        if icon.exists():
            app_icon = QIcon(str(icon))
            self.setWindowIcon(app_icon)
            if self.windowHandle() is not None:
                self.windowHandle().setIcon(app_icon)

        self.remote_client = _try_build_remote_client(config)
        self.remote_worker = None
        self._bootstrap_cloud()
        self._start_remote_station_if_signed_in()

        self.remote_sender_panel: Optional[RemoteSenderPanel] = None
        if self.remote_client is not None:
            self.remote_sender_panel = RemoteSenderPanel(self.remote_client, config)

        self.sender_panel = SenderPanel(config)
        self.station_panel = StationPanel(config)
        self.station_panel.set_remote_conflict(self.remote_worker is not None)
        self.history_panel = JobHistoryPanel()
        self.history_panel.bind_client(self.remote_client)
        self.settings_panel = SettingsPanel(config, client=self.remote_client)
        self.log_panel = LogPanel()

        tabs = QTabWidget()
        if self.remote_sender_panel is not None:
            tabs.addTab(self.remote_sender_panel, "Send a project")
            tabs.addTab(self.sender_panel, "Local Network (Legacy)")
            tabs.addTab(self.station_panel, "Render Station (Legacy)")
        else:
            tabs.addTab(self.sender_panel, "Send a project")
            tabs.addTab(self.station_panel, "Render station")
        tabs.addTab(self.history_panel, "Job history")
        tabs.addTab(self.settings_panel, "Settings")
        tabs.addTab(self.log_panel, "Log")
        self.tabs = tabs

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 12, 14, 8)
        layout.setSpacing(10)
        self.pending_panel = PendingJobsPanel(self.remote_worker)
        layout.addWidget(self.pending_panel)
        layout.addWidget(tabs)
        self.setCentralWidget(container)

        self._update_status_bar()
        self._bind_timer = QTimer(self)
        self._bind_timer.timeout.connect(self._bind_history)
        self._bind_timer.start(1500)

        if config.first_run:
            QTimer.singleShot(200, self._show_first_run)

    def _bootstrap_cloud(self) -> None:
        if self.remote_client is None:
            return
        restored = self.remote_client.auth.restore()
        if self.config.first_run:
            from .setup_wizard import SetupWizard
            SetupWizard(self.remote_client, self.config, self).exec()
            return
        if not restored:
            LoginDialog(self.remote_client, self).exec()

    def _start_remote_station_if_signed_in(self) -> None:
        if self.remote_client is None or not self.remote_client.signed_in:
            return
        if not self.config.station_role_enabled:
            logger.info("cloud render station disabled by role choice")
            return
        try:
            from ..remote.station_worker import RemoteStationWorker
            self.remote_worker = RemoteStationWorker(
                self.remote_client, self.config, on_event=self._on_remote_event)
            self.remote_worker.start()
        except Exception as exc:  # noqa: BLE001
            logger.error("could not start the cloud render station: %s", exc)
            self.remote_worker = None

    def _on_remote_event(self, kind: str, data: dict) -> None:
        logger.debug("remote station event %s %s", kind, data)

    def _update_status_bar(self) -> None:
        if self.remote_client is None:
            self.statusBar().showMessage(
                "Cloud features unavailable. Please check the installation.")
        elif self.remote_client.signed_in:
            station_bit = (f" · Render Station: {self.config.station_name} "
                           f"({self.config.station_id})"
                           if self.remote_worker else "")
            self.statusBar().showMessage(
                f"Signed in as {self.remote_client.auth.username}{station_bit}")
        else:
            self.statusBar().showMessage(
                "Not signed in — sign in to use remote sending.")

    def _show_first_run(self) -> None:
        # SetupWizard handles the remote first-run configuration. Keep the
        # legacy dialog only as a fallback for installs without cloud support.
        if self.remote_client is None:
            dialog = FirstRunDialog(self.config, self)
            dialog.exec()
            self.settings_panel._load()

    def _bind_history(self) -> None:
        if self.remote_worker is not None:
            store = self.remote_worker.local_store
        elif self.station_panel.station is not None:
            store = self.station_panel.station.store
        else:
            store = None
        if getattr(self.history_panel.local, "_store", None) is not store:
            self.history_panel.bind_store(store)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.remote_worker is not None:
            try:
                self.remote_worker.stop()
            except Exception:  # noqa: BLE001
                logger.exception("error stopping the cloud render station")
        self.sender_panel.shutdown()
        self.station_panel.shutdown()
        if self.remote_sender_panel is not None:
            self.remote_sender_panel.shutdown()
        save_config(self.config)
        super().closeEvent(event)


def _try_build_remote_client(config: AppConfig):
    try:
        from ..remote.client import build_remote_client
        return build_remote_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cloud features unavailable: %s", exc)
        return None
