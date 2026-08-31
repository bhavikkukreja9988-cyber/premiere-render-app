"""Job History tab.

Two views: this PC's own local job records (unchanged from V2), and the cloud
job history for the signed-in account — which is authoritative across
locations, since a Sender and a Render Station may be nowhere near each other.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core.jobs import JobRecord, JobStore
from .sender_panel import open_in_file_manager
from .theme import state_colour

LOCAL_COLUMNS = ["Job", "Project", "Status", "Started", "Completed", "Output"]
CLOUD_COLUMNS = ["Job", "Project", "Render Station", "Status", "Created",
                 "Completed", "Output", "Error"]


def _fmt_time(value: float) -> str:
    if not value:
        return "—"
    return time.strftime("%H:%M", time.localtime(value))


class LocalHistoryTable(QWidget):
    """This PC's own job records (unchanged from V2)."""

    def __init__(self) -> None:
        super().__init__()
        self._store: Optional[JobStore] = None
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.hint = QLabel("Every render job this PC has received, newest first.")
        self.hint.setObjectName("hint")
        layout.addWidget(self.hint)

        self.table = QTableWidget(0, len(LOCAL_COLUMNS))
        self.table.setHorizontalHeaderLabels(LOCAL_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        open_output = QPushButton("Open output file")
        open_output.clicked.connect(self._open_output)
        buttons.addWidget(open_output)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def bind_store(self, store: Optional[JobStore]) -> None:
        self._store = store
        self.refresh()

    def refresh(self) -> None:
        records: List[JobRecord] = self._store.list() if self._store else []
        if not records:
            self.table.setRowCount(0)
            self.hint.setText(
                "No jobs yet. Job history appears here once this PC has acted "
                "as a render station.")
            return
        self.hint.setText("Every render job this PC has received, newest first.")
        selected = self.table.currentRow()
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            label = QTableWidgetItem(record.display_label)
            label.setData(Qt.UserRole, record.output_path)
            project = QTableWidgetItem(record.spec.name or "—")
            status = QTableWidgetItem(record.state.value)
            status.setForeground(QColor(state_colour(record.state.value)))
            started = QTableWidgetItem(_fmt_time(record.started_at))
            completed = QTableWidgetItem(_fmt_time(record.completed_at))
            output_name = Path(record.output_path).name if record.output_path \
                else "—"
            output = QTableWidgetItem(record.error or output_name)
            if record.error:
                output.setForeground(QColor(state_colour("failed")))

            for col, item in enumerate((label, project, status, started,
                                        completed, output)):
                self.table.setItem(row, col, item)
        if 0 <= selected < len(records):
            self.table.selectRow(selected)

    def _open_output(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        output_path = item.data(Qt.UserRole) if item else ""
        if output_path and Path(output_path).exists():
            open_in_file_manager(Path(output_path).parent)


class CloudHistoryTable(QWidget):
    """The signed-in account's cloud job history — authoritative across
    locations, since Sender and Render Station may be far apart."""

    def __init__(self) -> None:
        super().__init__()
        self._client = None
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.hint = QLabel("Sign in to see your cloud job history.")
        self.hint.setObjectName("hint")
        layout.addWidget(self.hint)

        self.table = QTableWidget(0, len(CLOUD_COLUMNS))
        self.table.setHorizontalHeaderLabels(CLOUD_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

    def bind_client(self, client) -> None:
        self._client = client
        self.refresh()

    def refresh(self) -> None:
        if self._client is None or not self._client.signed_in:
            self.table.setRowCount(0)
            self.hint.setText("Sign in to see your cloud job history.")
            return
        try:
            jobs = self._client.jobs.list_jobs()
        except Exception:                                    # noqa: BLE001
            return
        if not jobs:
            self.table.setRowCount(0)
            self.hint.setText("No cloud jobs yet — send a project to get started.")
            return
        self.hint.setText(
            "Every job on this account, from any Sender or Render Station.")
        selected = self.table.currentRow()
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            status = QTableWidgetItem(job.status)
            status.setForeground(QColor(state_colour(job.status)))
            error_item = QTableWidgetItem(job.error)
            if job.error:
                error_item.setForeground(QColor(state_colour("failed")))
            values = [
                QTableWidgetItem(job.display_label),
                QTableWidgetItem(job.project_name or "—"),
                QTableWidgetItem(job.station_id or "—"),
                status,
                QTableWidgetItem(_fmt_time(job.created_at)),
                QTableWidgetItem(_fmt_time(job.completed_at)),
                QTableWidgetItem(job.output_filename or "—"),
                error_item,
            ]
            for col, item in enumerate(values):
                self.table.setItem(row, col, item)
        if 0 <= selected < len(jobs):
            self.table.selectRow(selected)


class JobHistoryPanel(QWidget):
    """Tabbed local + cloud history."""

    def __init__(self) -> None:
        super().__init__()
        self.local = LocalHistoryTable()
        self.cloud = CloudHistoryTable()

        layout = QVBoxLayout(self)
        heading = QLabel("Job history")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        tabs = QTabWidget()
        tabs.addTab(self.cloud, "Cloud (all jobs)")
        tabs.addTab(self.local, "This PC (local)")
        layout.addWidget(tabs, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)

    def bind_store(self, store: Optional[JobStore]) -> None:
        self.local.bind_store(store)

    def bind_client(self, client) -> None:
        self.cloud.bind_client(client)

    def refresh(self) -> None:
        self.local.refresh()
        self.cloud.refresh()
