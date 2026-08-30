"""Main window: one application, two roles."""

from __future__ import annotations

from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..core.config import AppConfig, save_config
from ..core.log import ring
from .first_run import FirstRunDialog
from .history_panel import JobHistoryPanel
from .sender_panel import SenderPanel
from .settings_panel import SettingsPanel
from .station_panel import StationPanel
from .theme import STYLESHEET


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
        self.setWindowTitle(f"Premiere Render App {__version__}")
        self.resize(1000, 840)
        self.setStyleSheet(STYLESHEET)

        self.sender_panel = SenderPanel(config)
        self.station_panel = StationPanel(config)
        self.history_panel = JobHistoryPanel()
        self.settings_panel = SettingsPanel(config)
        self.log_panel = LogPanel()

        tabs = QTabWidget()
        tabs.addTab(self.sender_panel, "Send a project")
        tabs.addTab(self.station_panel, "Render station")
        tabs.addTab(self.history_panel, "Job history")
        tabs.addTab(self.settings_panel, "Settings")
        tabs.addTab(self.log_panel, "Log")
        tabs.setCurrentIndex(1 if config.role == "station" else 0)
        tabs.currentChanged.connect(self._tab_changed)
        self.tabs = tabs

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 12, 14, 8)
        layout.addWidget(tabs)
        self.setCentralWidget(container)

        self.statusBar().showMessage(
            "Both PCs must run this app, on the same network, while a job is active.")

        self._bind_timer = QTimer(self)
        self._bind_timer.timeout.connect(self._bind_history)
        self._bind_timer.start(1500)

        if config.first_run:
            QTimer.singleShot(200, self._show_first_run)

    def _show_first_run(self) -> None:
        dialog = FirstRunDialog(self.config, self)
        dialog.exec()
        self.settings_panel._load()

    def _bind_history(self) -> None:
        store = self.station_panel.station.store if self.station_panel.station else None
        if getattr(self.history_panel, "_store", None) is not store:
            self.history_panel.bind_store(store)

    def _tab_changed(self, index: int) -> None:
        if index == 0:
            self.config.role = "sender"
            save_config(self.config)
        elif index == 1:
            self.config.role = "station"
            save_config(self.config)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.sender_panel.shutdown()
        self.station_panel.shutdown()
        save_config(self.config)
        super().closeEvent(event)
