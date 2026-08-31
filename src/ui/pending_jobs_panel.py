"""Manual job-acceptance banner.

When "Accept incoming jobs automatically" is off, a job that reaches the
station sits in ``RemoteStationWorker.pending_manual`` until the operator acts
on it. This widget shows those jobs as a small banner above the tabs — plan
section 26's "New render job available [Accept] [Reject]" — and stays hidden
whenever there is nothing waiting.
"""

from __future__ import annotations

import threading
from typing import Dict

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .theme import PANEL_ALT, WARN


class PendingJobsPanel(QWidget):
    def __init__(self, remote_worker=None) -> None:
        super().__init__()
        self.remote_worker = remote_worker
        self._rows: Dict[str, QWidget] = {}
        self._build()
        self.setVisible(False)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1500)

    def set_worker(self, remote_worker) -> None:
        self.remote_worker = remote_worker
        self.refresh()

    def _build(self) -> None:
        self.setStyleSheet(
            f"QWidget#pendingBanner {{ background: {PANEL_ALT}; "
            f"border: 1px solid {WARN}; border-radius: 8px; }}")
        self.setObjectName("pendingBanner")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        heading = QLabel("New render job — waiting for your approval")
        heading.setStyleSheet(f"color: {WARN}; font-weight: 600;")
        outer.addWidget(heading)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        outer.addLayout(self.rows_layout)

    def refresh(self) -> None:
        if self.remote_worker is None:
            self.setVisible(False)
            return

        pending = dict(self.remote_worker.pending_manual)

        for job_id in list(self._rows):
            if job_id not in pending:
                row = self._rows.pop(job_id)
                self.rows_layout.removeWidget(row)
                row.deleteLater()

        for job_id, job in pending.items():
            if job_id in self._rows:
                continue
            self._rows[job_id] = self._make_row(job_id, job)
            self.rows_layout.addWidget(self._rows[job_id])

        self.setVisible(bool(pending))

    def _make_row(self, job_id: str, job) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        project = getattr(job, "project_name", "") or "untitled"
        label_text = getattr(job, "display_label", job_id[:8])
        label = QLabel(f"{label_text} — {project}")
        layout.addWidget(label, 1)

        accept_button = QPushButton("Accept")
        accept_button.setObjectName("primary")
        accept_button.clicked.connect(lambda: self._respond(job_id, accept=True))
        reject_button = QPushButton("Reject")
        reject_button.setObjectName("danger")
        reject_button.clicked.connect(lambda: self._respond(job_id, accept=False))
        layout.addWidget(accept_button)
        layout.addWidget(reject_button)
        return row

    def _respond(self, job_id: str, accept: bool) -> None:
        if self.remote_worker is None:
            return
        target = (self.remote_worker.accept_pending if accept
                  else self.remote_worker.reject_pending)
        threading.Thread(target=target, args=(job_id,), daemon=True,
                         name="pending-job-response").start()
        self.remote_worker.pending_manual.pop(job_id, None)
        self.refresh()
