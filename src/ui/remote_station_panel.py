"""Remote Render Station status/control panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..core.config import AppConfig, save_config
from ..core.log import get_logger
from ..remote.network_utils import local_ip
from .theme import MUTED, OK, WARN

logger = get_logger("ui.remote_station")


class RemoteStationPanel(QWidget):
    """Simple cloud station status and settings; no LAN controls."""

    def __init__(self, config: AppConfig, get_worker=None) -> None:
        super().__init__()
        self.config = config
        self._get_worker = get_worker
        self._build()
        self._load()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)
        self._refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        heading = QLabel("Render Station")
        heading.setObjectName("heading")
        outer.addWidget(heading)

        status_box = QGroupBox("Station status")
        form = QFormLayout(status_box)
        self.status_label = QLabel("Offline")
        self.station_name_label = QLabel()
        self.station_id_label = QLabel()
        self.ip_label = QLabel()
        self.engine_label = QLabel("—")
        self.current_job_label = QLabel("Idle")
        form.addRow("Status", self.status_label)
        form.addRow("Station name", self.station_name_label)
        form.addRow("Station ID", self.station_id_label)
        form.addRow("Local IP (info)", self.ip_label)
        form.addRow("Render engine", self.engine_label)
        form.addRow("Current job", self.current_job_label)
        outer.addWidget(status_box)

        settings_box = QGroupBox("Render settings")
        settings_form = QFormLayout(settings_box)
        self.accept_check = QCheckBox("Accept incoming jobs automatically")
        settings_form.addRow("New jobs", self.accept_check)

        storage_row = QHBoxLayout()
        self.storage_edit = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_storage)
        storage_row.addWidget(self.storage_edit, 1)
        storage_row.addWidget(browse)
        settings_form.addRow("Project storage", storage_row)

        self.retention_label = QLabel()
        settings_form.addRow("Retention", self.retention_label)
        outer.addWidget(settings_box)

        note = QLabel(
            "FileSender is automatically Online while this app is open. "
            "Closing FileSender takes this station Offline. No IP address, "
            "port, pairing code, or background server is required.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        outer.addWidget(note)

        save = QPushButton("Save render settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        outer.addWidget(save)
        outer.addStretch(1)

    def _load(self) -> None:
        self.station_name_label.setText(self.config.station_name)
        self.station_id_label.setText(self.config.station_id)
        self.ip_label.setText(local_ip())
        self.accept_check.setChecked(self.config.accept_jobs_automatically)
        self.storage_edit.setText(self.config.workspace_dir)
        self.retention_label.setText(self._retention_text(self.config.retention_days))

    @staticmethod
    def _retention_text(days: int) -> str:
        if days <= 0:
            return "Never"
        return f"{days} day" if days == 1 else f"{days} days"

    def _refresh(self) -> None:
        worker = self._get_worker() if self._get_worker else None
        if worker is None or not getattr(worker, "started", False):
            self.status_label.setText(f"<span style='color:{MUTED}'>Offline</span>")
            self.engine_label.setText("—")
            self.current_job_label.setText("Idle")
            return

        engine = getattr(worker.backend, "name", "Unknown")
        current = getattr(worker.manager, "current_job", None)
        if current:
            state, colour, text = "Busy", WARN, str(current)
        else:
            state, colour, text = "Online", OK, "Idle"
        self.status_label.setText(f"<span style='color:{colour}'>● {state}</span>")
        self.engine_label.setText(engine)
        self.current_job_label.setText(text)
        self.station_name_label.setText(self.config.station_name)
        self.station_id_label.setText(self.config.station_id)
        self.ip_label.setText(local_ip())

    def _browse_storage(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should received Premiere projects be stored?",
            self.storage_edit.text() or str(Path.home()))
        if folder:
            self.storage_edit.setText(folder)

    def _save(self) -> None:
        self.config.accept_jobs_automatically = self.accept_check.isChecked()
        if self.storage_edit.text().strip():
            self.config.workspace_dir = self.storage_edit.text().strip()
        save_config(self.config)
        self.retention_label.setText(self._retention_text(self.config.retention_days))
        self.status_label.setText(
            f"<span style='color:{OK}'>Saved.</span>")
