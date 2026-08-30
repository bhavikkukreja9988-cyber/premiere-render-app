"""Main window: one application, two roles."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..core.config import AppConfig, save_config
from ..core.log import ring
from .sender_panel import SenderPanel
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
        self.resize(980, 820)
        self.setStyleSheet(STYLESHEET)

        self.sender_panel = SenderPanel(config)
        self.station_panel = StationPanel(config)
        self.log_panel = LogPanel()

        tabs = QTabWidget()
        tabs.addTab(self.sender_panel, "Send a project")
        tabs.addTab(self.station_panel, "Render station")
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

    def _tab_changed(self, index: int) -> None:
        self.config.role = "station" if index == 1 else "sender"
        save_config(self.config)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.sender_panel.shutdown()
        self.station_panel.shutdown()
        save_config(self.config)
        super().closeEvent(event)
