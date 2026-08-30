"""Job History tab.

A read-only table of every job the station knows about, so the user can see
what happened without opening log files: job label, project, status, start and
finish times, output file and any error.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..core.jobs import JobRecord, JobStore
from .sender_panel import open_in_file_manager
from .theme import state_colour

COLUMNS = ["Job", "Project", "Status", "Started", "Completed", "Output"]


def _fmt_time(value: float) -> str:
    if not value:
        return "—"
    return time.strftime("%H:%M", time.localtime(value))


class JobHistoryPanel(QWidget):
    """Shows the station's job list; empty until a station has run."""

    def __init__(self) -> None:
        super().__init__()
        self._store: Optional[JobStore] = None
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1500)

    def bind_store(self, store: Optional[JobStore]) -> None:
        self._store = store
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel("Job history")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        self.hint = QLabel(
            "Every render job this PC has received, newest first.")
        self.hint.setObjectName("hint")
        layout.addWidget(self.hint)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
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

    def _records(self) -> List[JobRecord]:
        return self._store.list() if self._store else []

    def refresh(self) -> None:
        records = self._records()
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
            output_name = Path(record.output_path).name if record.output_path else "—"
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
