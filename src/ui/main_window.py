"""Main window: one application, two roles — now cloud-connected.

On launch this tries to build a Supabase-backed remote client, restore a saved
session or ask the user to sign in, and — if signed in — start the cloud
render-station worker automatically (no "Go Online" button; being open is
being online, per the remote plan). The legacy same-network Sender/Render
Station tabs are kept for backward compatibility but are clearly labelled
"(Legacy)", and the legacy Render Station is disabled while the cloud worker
owns the same local job workspace, to avoid two render queues fighting over
one folder.

If the ``supabase`` package isn't installed, or the user skips signing in, the
app still runs — it just falls back to the legacy local-network tabs, and the
new cloud Sender panel shows "Sign in to send a project" via the same gate
logic used everywhere else.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent
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
    """Best-effort: build a Supabase-backed remote client, or None.

    Never raises — a missing ``supabase`` package or an unreachable network
    must not stop the app from opening; it just means the cloud tabs fall back
    to their signed-out state.
    """
    try:
        from ..remote.client import build_remote_client
        return build_remote_client()
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("cloud features unavailable: %s", exc)
        return None


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle(f"Premiere Render App {__version__}")
        self.resize(1040, 860)
        self.setStyleSheet(STYLESHEET)

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
        self.settings_panel = SettingsPanel(
            config, client=self.remote_client,
            on_sign_out=self._handle_sign_out,
            on_signed_in=self._handle_signed_in,
            get_station_backend=self._current_backend_name)
        self.log_panel = LogPanel()

        tabs = QTabWidget()
        if self.remote_sender_panel is not None:
            tabs.addTab(self.remote_sender_panel, "Send a project")
            tabs.addTab(self.sender_panel, "Local Network (Legacy)")
            tabs.addTab(self.station_panel, "Render Station (Legacy)")
        else:
            # No cloud available this run: the legacy tabs are the only way
            # to send or receive, so give them the primary names.
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

    # -- cloud bootstrap ----------------------------------------------------
    def _bootstrap_cloud(self) -> None:
        """One guided flow on first run (sign in + role + station setup);
        just a plain sign-in prompt on every later launch if the restored
        session didn't come back. If the cloud isn't available at all, this
        does nothing — the old storage-only FirstRunDialog handles that case
        from __init__'s caller instead."""
        if self.remote_client is None:
            return

        restored = self.remote_client.auth.restore()
        if self.config.first_run:
            from .setup_wizard import SetupWizard
            SetupWizard(self.remote_client, self.config, self).exec()
            # SetupWizard sets first_run = False and saves the config itself,
            # whether or not sign-in succeeded — a skipped sign-in just means
            # the remote panels stay in their signed-out state.
            return

        if not restored:
            dialog = LoginDialog(self.remote_client, self)
            dialog.exec()
            # If the user closed the dialog without signing in, remote_client
            # simply stays signed-out; every remote panel already degrades
            # gracefully via the send-gate / "sign in" hints.

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
        except Exception as exc:                              # noqa: BLE001
            logger.error("could not start the cloud render station: %s", exc)
            self.remote_worker = None

    def _handle_sign_out(self) -> None:
        """Sign out immediately, no app restart needed.

        Order matters: the worker must stop (and mark the station offline)
        *while still authenticated* — stopping it after the session is
        cleared would mean its final "I'm offline now" update gets rejected.
        """
        if self.remote_worker is not None:
            try:
                self.remote_worker.stop()
            except Exception:                                 # noqa: BLE001
                logger.exception("error stopping the cloud render station "
                                 "during sign-out")
            self.remote_worker = None
        if self.remote_client is not None:
            self.remote_client.auth.sign_out()
        self.station_panel.set_remote_conflict(False)
        self.pending_panel.set_worker(None)
        self._update_status_bar()

    def _handle_signed_in(self) -> None:
        """A fresh sign-in happened (from Settings); bring the cloud station
        up immediately if this PC is meant to have one, no restart needed."""
        self._start_remote_station_if_signed_in()
        self.station_panel.set_remote_conflict(self.remote_worker is not None)
        self.pending_panel.set_worker(self.remote_worker)
        self._update_status_bar()

    def _current_backend_name(self) -> str:
        """Which render engine the cloud station is actually using right now
        ("Adobe Media Encoder" or the manual fallback), or "" if the cloud
        station isn't running. Read live by Settings so a silent fallback to
        manual rendering is always visible somewhere, not just in the legacy
        tab."""
        return self.remote_worker.backend.name if self.remote_worker else ""

    def _on_remote_event(self, kind: str, data: dict) -> None:
        logger.debug("remote station event %s %s", kind, data)
        # No action needed here: PendingJobsPanel polls
        # remote_worker.pending_manual directly and shows Accept/Reject rows
        # for anything waiting.

    def _update_status_bar(self) -> None:
        if self.remote_client is None:
            self.statusBar().showMessage(
                "Cloud features unavailable (the 'supabase' package isn't "
                "installed). Using local-network mode only.")
        elif self.remote_client.signed_in:
            station_bit = (f" · Render Station: {self.config.station_name} "
                           f"({self.config.station_id})"
                           if self.remote_worker else "")
            self.statusBar().showMessage(
                f"Signed in as {self.remote_client.auth.username}{station_bit}")
        else:
            self.statusBar().showMessage(
                "Not signed in — open Settings or restart the app to sign in "
                "and use the cloud Sender.")

    def _show_first_run(self) -> None:
        dialog = FirstRunDialog(self.config, self)
        dialog.exec()
        self.settings_panel._load()

    def _bind_history(self) -> None:
        # Point the "local" history tab at whichever job store is actually
        # active: the cloud worker's if it's running, otherwise the legacy
        # LAN station's if that's online, otherwise nothing.
        if self.remote_worker is not None:
            store = self.remote_worker.local_store
        elif self.station_panel.station is not None:
            store = self.station_panel.station.store
        else:
            store = None
        if getattr(self.history_panel.local, "_store", None) is not store:
            self.history_panel.bind_store(store)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Stop the cloud worker first: this marks the station offline and
        # stops its heartbeat/subscriptions before anything else tears down,
        # so no hidden process is left believing it's still reachable.
        if self.remote_worker is not None:
            try:
                self.remote_worker.stop()
            except Exception:                                 # noqa: BLE001
                logger.exception("error stopping the cloud render station")
        self.sender_panel.shutdown()
        self.station_panel.shutdown()
        if self.remote_sender_panel is not None:
            self.remote_sender_panel.shutdown()
        save_config(self.config)
        super().closeEvent(event)
