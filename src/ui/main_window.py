"""Main FileSender window for the Remote V3 product."""

from __future__ import annotations

import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core.config import AppConfig, save_config
from ..core.log import (get_logger, log_file_path,
                        previous_log_file_path, ring)
from .helpers import open_in_file_manager
from .history_panel import JobHistoryPanel
from .pending_jobs_panel import PendingJobsPanel
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
    """Live log view with a one-click way to get the log out of the app.

    The whole point of the Save button is diagnosis: when something goes
    wrong, one click produces a single file covering exactly this run,
    ready to send. Logs start fresh on every launch (see core.log), so a
    saved log never contains months of unrelated history.
    """

    line_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setPlainText("\n".join(ring.tail(400)))
        # Monospace keeps timestamps and levels aligned, which makes a wall
        # of log lines far easier to scan.
        self.view.setFont(QFont("Consolas", 9))
        layout.addWidget(self.view)

        buttons = QHBoxLayout()

        self.save_button = QPushButton("Save log to file…")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip(
            "Save this run's log as a single file you can send for help.")
        self.save_button.clicked.connect(self._save_log)
        buttons.addWidget(self.save_button)

        self.folder_button = QPushButton("Open log folder")
        self.folder_button.clicked.connect(self._open_folder)
        buttons.addWidget(self.folder_button)

        self.copy_button = QPushButton("Copy to clipboard")
        self.copy_button.clicked.connect(self._copy_log)
        buttons.addWidget(self.copy_button)

        clear = QPushButton("Clear view")
        clear.setToolTip("Clears only this view — the log file is untouched.")
        clear.clicked.connect(self.view.clear)
        buttons.addWidget(clear)

        buttons.addStretch(1)
        layout.addLayout(buttons)

        hint = QLabel(
            "The log starts fresh each time FileSender opens. "
            "If something goes wrong, click <b>Save log to file…</b> and send "
            "the file — it covers just this run.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.line_signal.connect(self.view.appendPlainText)
        ring.subscribe(lambda line: self.line_signal.emit(line))

    # -- actions ----------------------------------------------------------
    def _save_log(self) -> None:
        """Write this run's log (plus the previous run, if present) to one
        file the user chooses."""
        default_name = (f"FileSender-log-"
                        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt")
        target, _ = QFileDialog.getSaveFileName(
            self, "Save log", str(Path.home() / "Desktop" / default_name),
            "Text files (*.txt);;All files (*)")
        if not target:
            return

        try:
            Path(target).write_text(self._collect_log_text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not save log",
                                f"The log could not be written:\n{exc}")
            return

        QMessageBox.information(
            self, "Log saved",
            f"Saved to:\n{target}\n\nYou can attach this file when asking "
            "for help.")

    def _collect_log_text(self) -> str:
        """This run's log, with the previous run appended if it exists.

        Reads the files rather than the on-screen view: the view is capped
        at 5000 lines and may have been cleared, while the file is complete.
        Falls back to the in-memory ring buffer if the files can't be read.
        """
        parts = [
            "FileSender log export",
            f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"App version: {__version__}",
            f"Platform: {platform.platform()}",
            "",
        ]

        current = log_file_path()
        previous = previous_log_file_path()

        wrote_any = False
        try:
            if current.is_file():
                parts += ["=" * 70, "CURRENT RUN", "=" * 70, "",
                          current.read_text(encoding="utf-8", errors="replace")]
                wrote_any = True
        except OSError as exc:
            parts.append(f"(could not read current log: {exc})")

        try:
            if previous.is_file():
                parts += ["", "=" * 70, "PREVIOUS RUN", "=" * 70, "",
                          previous.read_text(encoding="utf-8", errors="replace")]
                wrote_any = True
        except OSError:
            pass

        if not wrote_any:
            parts += ["=" * 70, "IN-MEMORY LOG (log file unavailable)",
                      "=" * 70, "", "\n".join(ring.tail(5000))]

        return "\n".join(parts)

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self._collect_log_text())
        QMessageBox.information(self, "Copied",
                                "The log has been copied to the clipboard.")

    def _open_folder(self) -> None:
        folder = log_file_path().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        open_in_file_manager(folder)


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
        """Set up this device, then connect silently.

        There is no login step any more: the app signs into a shared built-in
        account in the background. The only thing the user is ever asked is
        what to call this PC and which family code it belongs to.
        """
        # Ask for a device name + family code if this is a fresh install, or
        # if an older install predates them (upgrade path).
        if self.config.first_run or not self.config.setup_complete:
            SetupWizard(self.config, self).exec()

        if self.remote_client is None:
            return
        if not self.remote_client.auth.ensure_signed_in(self.config.family_code):
            logger.warning("could not connect to the cloud on startup")

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
