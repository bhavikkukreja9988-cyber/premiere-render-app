"""Main FileSender window for the Remote V3 product."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core.config import AppConfig, save_config
from ..core.log import get_logger, ring
from .history_panel import JobHistoryPanel
from .pending_jobs_panel import PendingJobsPanel
from .remote_login import LoginDialog
from .remote_sender_panel import RemoteSenderPanel
from .remote_station_panel import RemoteStationPanel
from .settings_panel import SettingsPanel
from .setup_wizard import SetupWizard
from .theme import STYLESHEET

logger = get_logger("ui.main_window")


def _icon_path() -> Path:
    """Resolve the bundled FileSender icon in source and PyInstaller builds."""
    if hasattr(sys, "_MEIPASS"):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
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


def _try_build_remote_client(config: AppConfig):
    try:
        from ..remote.client import build_remote_client
        return build_remote_client()
    except Exception as exc:  # noqa: BLE001
        logger.exception("cloud client could not be initialized")
        return None


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle(f"FileSender {__version__}")
        self.resize(1040, 860)
        self.setStyleSheet(STYLESHEET)

        icon = _icon_path()
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        self.remote_client = _try_build_remote_client(config)
        self.remote_worker = None
        self.remote_sender_panel: Optional[RemoteSenderPanel] = None

        if self.remote_client is not None:
            self._bootstrap_cloud()
            self._start_remote_station_if_signed_in()
            self.remote_sender_panel = RemoteSenderPanel(
                self.remote_client, config
            )

        self.history_panel = JobHistoryPanel()
        self.remote_station_panel = RemoteStationPanel(
            config, get_worker=lambda: self.remote_worker
        )
        self.history_panel.bind_client(self.remote_client)
        self.settings_panel = SettingsPanel(
            config,
            client=self.remote_client,
            on_sign_out=self._handle_sign_out,
            on_signed_in=self._handle_signed_in,
            get_station_backend=self._current_backend_name,
        )
        self.log_panel = LogPanel()

        tabs = QTabWidget()
        if self.remote_sender_panel is not None:
            tabs.addTab(self.remote_sender_panel, "Send a project")
        else:
            unavailable = QLabel(
                "Cloud features could not be initialized. Rebuild the installer "
                "with the bundled dependencies and try again."
            )
            unavailable.setWordWrap(True)
            unavailable.setObjectName("hint")
            tabs.addTab(unavailable, "Send a project")
        tabs.addTab(self.remote_station_panel, "Render Station")
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

    def _bootstrap_cloud(self) -> None:
        if self.remote_client is None:
            return
        restored = self.remote_client.auth.restore()
        if self.config.first_run:
            SetupWizard(self.remote_client, self.config, self).exec()
            return
        if not restored:
            LoginDialog(self.remote_client, self).exec()

    def _start_remote_station_if_signed_in(self) -> None:
        if self.remote_client is None or not self.remote_client.signed_in:
            return
        if not self.config.station_role_enabled:
            return
        try:
            from ..remote.station_worker import RemoteStationWorker
            self.remote_worker = RemoteStationWorker(
                self.remote_client, self.config, on_event=self._on_remote_event
            )
            self.remote_worker.start()
        except Exception as exc:  # noqa: BLE001
            logger.exception("could not start the cloud render station")
            QMessageBox.critical(
                self,
                "Render Station unavailable",
                f"FileSender could not start the Render Station.\n\n{exc}",
            )
            self.remote_worker = None

    def _handle_sign_out(self) -> None:
        if self.remote_worker is not None:
            try:
                self.remote_worker.stop()
            except Exception:  # noqa: BLE001
                logger.exception("error stopping render station during sign-out")
            self.remote_worker = None
        if self.remote_client is not None:
            self.remote_client.auth.sign_out()
        self.pending_panel.set_worker(None)
        self._update_status_bar()

    def _handle_signed_in(self) -> None:
        self._start_remote_station_if_signed_in()
        self.pending_panel.set_worker(self.remote_worker)
        self._update_status_bar()

    def _current_backend_name(self) -> str:
        return self.remote_worker.backend.name if self.remote_worker else ""

    def _on_remote_event(self, kind: str, data: dict) -> None:
        logger.debug("remote station event %s %s", kind, data)

    def _update_status_bar(self) -> None:
        if self.remote_client is None:
            self.statusBar().showMessage("Cloud connection unavailable.")
        elif self.remote_client.signed_in:
            station_bit = (
                f" · Render Station: {self.config.station_name}"
                if self.remote_worker else ""
            )
            self.statusBar().showMessage(
                f"Signed in as {self.remote_client.auth.username}{station_bit}"
            )
        else:
            self.statusBar().showMessage(
                "Not signed in — sign in to use remote sending."
            )

    def _bind_history(self) -> None:
        store = self.remote_worker.local_store if self.remote_worker else None
        if getattr(self.history_panel.local, "_store", None) is not store:
            self.history_panel.bind_store(store)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.remote_worker is not None:
            try:
                self.remote_worker.stop()
            except Exception:  # noqa: BLE001
                logger.exception("error stopping remote station")
        if self.remote_sender_panel is not None:
            self.remote_sender_panel.shutdown()
        save_config(self.config)
        super().closeEvent(event)
