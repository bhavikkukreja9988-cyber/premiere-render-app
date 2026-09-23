"""Remote Render Station status/control panel."""

from __future__ import annotations

from pathlib import Path

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import workspace
from ..core.config import AppConfig, save_config
from ..core.log import get_logger
from ..remote.network_utils import local_ip
from .helpers import open_in_file_manager
from .theme import MUTED, OK, WARN, state_colour

logger = get_logger("ui.remote_station")


class RemoteStationPanel(QWidget):
    """Simple cloud station status/control and settings; no LAN controls."""

    def __init__(self, config: AppConfig, get_worker=None) -> None:
        super().__init__()
        self.config = config
        self._get_worker = get_worker
        self._worker = None
        self._size_cache = {}
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

        outer.addWidget(self._build_jobs_box(), 1)

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
        self.station_name_label.setText(self.config.device_name or self.config.station_name)
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
        self._refresh_jobs(worker)
        if worker is None or not getattr(worker, "started", False):
            self.status_label.setText(
                f"<span style='color:{MUTED}'>Offline — waiting to connect "
                "to the cloud</span>")
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
        self.station_name_label.setText(self.config.device_name or self.config.station_name)
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

    # -- received jobs ------------------------------------------------------
    _COLUMNS = ("Job", "Project", "Status", "Progress", "Last update", "Size")

    _STATUS_TEXT = {
        "created": "Waiting",
        "transferring": "Downloading",
        "queued": "Queued",
        "rendering": "Rendering",
        "encoded": "Rendered",
        "returning": "Sending back",
        "complete": "Done",
        "failed": "Failed",
        "cancelled": "Cancelled",
    }

    def _build_jobs_box(self) -> QGroupBox:
        box = QGroupBox("Received jobs")
        layout = QVBoxLayout(box)

        self.jobs_table = QTableWidget(0, len(self._COLUMNS))
        self.jobs_table.setHorizontalHeaderLabels(self._COLUMNS)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.jobs_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.jobs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.jobs_table.verticalHeader().setVisible(False)
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.jobs_table.itemSelectionChanged.connect(self._update_job_buttons)
        layout.addWidget(self.jobs_table)

        buttons = QHBoxLayout()
        self.cancel_job_button = QPushButton("Cancel render")
        self.cancel_job_button.setToolTip(
            "Stop the job that is rendering right now.")
        self.cancel_job_button.clicked.connect(self._cancel_selected)
        buttons.addWidget(self.cancel_job_button)

        self.clear_job_button = QPushButton("Clear selected job")
        self.clear_job_button.setToolTip(
            "Delete this job's files from this PC and from the cloud. "
            "Use this for failed or stuck jobs.")
        self.clear_job_button.clicked.connect(self._clear_selected)
        buttons.addWidget(self.clear_job_button)

        self.open_job_button = QPushButton("Open job folder")
        self.open_job_button.clicked.connect(self._open_selected_folder)
        buttons.addWidget(self.open_job_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.jobs_hint = QLabel("")
        self.jobs_hint.setObjectName("hint")
        self.jobs_hint.setWordWrap(True)
        layout.addWidget(self.jobs_hint)

        self._update_job_buttons()
        return box

    def _selected_job_id(self) -> str:
        rows = self.jobs_table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.jobs_table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else ""

    def _refresh_jobs(self, worker) -> None:
        self._worker = worker
        records = worker.list_local_jobs() if worker is not None else []
        selected = self._selected_job_id()

        self.jobs_table.setRowCount(len(records))
        reselect = -1
        for row, record in enumerate(records):
            state = record.state.value
            active = worker.is_active(record.job_id)

            label = QTableWidgetItem(record.display_label)
            label.setData(Qt.UserRole, record.job_id)

            status = QTableWidgetItem(self._STATUS_TEXT.get(state, state))
            status.setForeground(QColor(state_colour(state)))
            if record.error:
                status.setToolTip(record.error)

            if state in ("rendering", "transferring") or active:
                progress_text = f"{int(round(record.progress * 100))}%"
            elif state in ("complete", "encoded"):
                progress_text = "100%"
            else:
                progress_text = "—"

            values = [
                label,
                QTableWidgetItem(record.spec.name or "—"),
                status,
                QTableWidgetItem(progress_text),
                QTableWidgetItem(self._ago(record.updated_at)),
                QTableWidgetItem(self._job_size_text(record.job_id)),
            ]
            for col, item in enumerate(values):
                self.jobs_table.setItem(row, col, item)
            if record.job_id == selected:
                reselect = row

        if reselect >= 0:
            self.jobs_table.selectRow(reselect)
        if not records:
            self.jobs_hint.setText(
                "No jobs received yet. Jobs sent to this PC appear here.")
        self._update_job_buttons()

    def _update_job_buttons(self) -> None:
        worker = self._worker
        job_id = self._selected_job_id()
        has_selection = bool(job_id) and worker is not None
        rendering = has_selection and job_id == worker.manager.current_job
        active = has_selection and worker.is_active(job_id)

        self.cancel_job_button.setEnabled(bool(rendering))
        self.clear_job_button.setEnabled(has_selection and not active)
        self.open_job_button.setEnabled(has_selection)

        if not has_selection:
            if self.jobs_table.rowCount():
                self.jobs_hint.setText(
                    "Select a job to clear it or open its folder. Finished and "
                    "failed jobs are also removed automatically after the "
                    "retention period.")
        elif rendering:
            self.jobs_hint.setText(
                "This job is rendering. Cancel it first if you want to clear it.")
        elif active:
            self.jobs_hint.setText(
                "This job is still downloading. It can be cleared once it "
                "finishes.")
        else:
            self.jobs_hint.setText(
                "Clearing deletes this job's files from this PC and the cloud. "
                "If it hasn't finished, the sender is told and can retry.")

    def _cancel_selected(self) -> None:
        worker = self._worker
        job_id = self._selected_job_id()
        if worker is None or not job_id:
            return
        answer = QMessageBox.question(
            self, "Cancel render?",
            "Stop rendering this job? You can clear it afterwards.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        _ok, message = worker.cancel_job(job_id)
        self.jobs_hint.setText(message)

    def _clear_selected(self) -> None:
        worker = self._worker
        job_id = self._selected_job_id()
        if worker is None or not job_id:
            return
        record = worker.local_store.get(job_id)
        name = record.display_label if record else job_id[:8]
        size = self._job_size_text(job_id)
        answer = QMessageBox.question(
            self, "Clear job?",
            f"Delete {name} from this PC?\n\n"
            f"This frees {size} and removes its files from the cloud. "
            "If the job hadn't finished, the sender will be told and can "
            "retry.\n\nThis can't be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        ok, message = worker.clear_job(job_id)
        if not ok:
            QMessageBox.warning(self, "Couldn't clear job", message)
        self._refresh()

    def _open_selected_folder(self) -> None:
        job_id = self._selected_job_id()
        if not job_id:
            return
        folder = workspace.job_dir(self.config.workspace, job_id)
        if folder.exists():
            open_in_file_manager(folder)
        else:
            self.jobs_hint.setText("This job's folder no longer exists.")

    # -- formatting ---------------------------------------------------------
    @staticmethod
    def _ago(timestamp) -> str:
        if not timestamp:
            return "—"
        seconds = max(0, time.time() - float(timestamp))
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{int(seconds // 60)} min ago"
        if seconds < 86400:
            return f"{int(seconds // 3600)} h ago"
        return f"{int(seconds // 86400)} d ago"

    def _job_size_text(self, job_id: str) -> str:
        """Size of a job's folder on disk. Cached briefly: walking a big
        project folder every 2-second refresh would make the UI stutter."""
        cache = self._size_cache
        cached = cache.get(job_id)
        now = time.time()
        if cached and now - cached[0] < 30:
            return cached[1]

        folder = workspace.job_dir(self.config.workspace, job_id)
        total = 0
        try:
            for path in folder.rglob("*"):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        text = self._format_bytes(total)
        cache[job_id] = (now, text)
        return text

    @staticmethod
    def _format_bytes(size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.1f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.0f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B" if size else "—"
