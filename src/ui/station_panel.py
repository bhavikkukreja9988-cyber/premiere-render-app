"""Render station tab: run the listener, wire up Media Encoder, watch the queue."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.config import AppConfig, new_pairing_code, save_config
from ..core.log import get_logger
from ..core.workspace import human_bytes, output_dir
from ..network.discovery import local_ip
from ..network.session import RenderStation
from ..render import media_encoder as ame
from ..render.pipeline import build_backend
from .sender_panel import open_in_file_manager
from .theme import MUTED, OK, WARN, state_colour

logger = get_logger("ui.station")

COLUMNS = ["Job", "From", "State", "Progress", "Detail"]


class StationPanel(QWidget):
    refresh_signal = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.station: Optional[RenderStation] = None
        self._build()
        self.refresh_signal.connect(self._refresh_jobs)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_jobs)
        self._timer.start(1000)
        self._refresh_ame()
        if config.autostart_station:
            self._toggle_station()

    # -- construction -----------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Listener ------------------------------------------------------
        listener_box = QGroupBox("This PC as a render station")
        listener_form = QFormLayout(listener_box)

        self.name_edit = QLineEdit(self.config.station_name)
        listener_form.addRow("Station name", self.name_edit)

        port_row = QHBoxLayout()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.config.tcp_port)
        self.broadcast_check = QCheckBox("Announce on the network")
        self.broadcast_check.setChecked(self.config.broadcast_presence)
        port_row.addWidget(self.port_spin, 1)
        port_row.addWidget(self.broadcast_check, 2)
        listener_form.addRow("Port", port_row)

        code_row = QHBoxLayout()
        self.code_label = QLabel(self.config.pairing_code)
        self.code_label.setObjectName("heading")
        self.code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.require_code_check = QCheckBox("Require this code")
        self.require_code_check.setChecked(self.config.require_pairing)
        regenerate = QPushButton("New code")
        regenerate.clicked.connect(self._regenerate_code)
        code_row.addWidget(self.code_label)
        code_row.addWidget(self.require_code_check)
        code_row.addWidget(regenerate)
        code_row.addStretch(1)
        listener_form.addRow("Pairing code", code_row)

        workspace_row = QHBoxLayout()
        self.workspace_edit = QLineEdit(self.config.workspace_dir)
        workspace_browse = QPushButton("Browse…")
        workspace_browse.clicked.connect(self._pick_workspace)
        workspace_row.addWidget(self.workspace_edit, 4)
        workspace_row.addWidget(workspace_browse, 1)
        listener_form.addRow("Workspace", workspace_row)

        control_row = QHBoxLayout()
        self.toggle_button = QPushButton("Go online")
        self.toggle_button.setObjectName("primary")
        self.toggle_button.clicked.connect(self._toggle_station)
        self.status_label = QLabel("Offline — nothing can reach this PC")
        self.status_label.setObjectName("hint")
        control_row.addWidget(self.toggle_button)
        control_row.addWidget(self.status_label, 1)
        listener_form.addRow("", control_row)
        layout.addWidget(listener_box)

        # Media Encoder -------------------------------------------------
        ame_box = QGroupBox("Adobe Media Encoder")
        ame_layout = QVBoxLayout(ame_box)
        self.ame_label = QLabel("checking…")
        self.ame_label.setWordWrap(True)
        ame_buttons = QHBoxLayout()
        install_button = QPushButton("Install Media Encoder agent")
        install_button.clicked.connect(self._install_agent)
        recheck_button = QPushButton("Re-check")
        recheck_button.clicked.connect(self._refresh_ame)
        logs_button = QPushButton("Open agent folder")
        logs_button.clicked.connect(lambda: open_in_file_manager(ame.agent_base()))
        ame_buttons.addWidget(install_button)
        ame_buttons.addWidget(recheck_button)
        ame_buttons.addWidget(logs_button)
        ame_buttons.addStretch(1)
        ame_layout.addWidget(self.ame_label)
        ame_layout.addLayout(ame_buttons)
        layout.addWidget(ame_box)

        # Queue ---------------------------------------------------------
        queue_box = QGroupBox("Queue")
        queue_layout = QVBoxLayout(queue_box)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        queue_layout.addWidget(self.table)

        job_buttons = QHBoxLayout()
        for label, slot in (("Open output folder", self._open_output),
                            ("Re-queue", self._requeue),
                            ("Cancel job", self._cancel_job),
                            ("Remove from list", self._remove_job)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            if label == "Cancel job":
                button.setObjectName("danger")
            job_buttons.addWidget(button)
        job_buttons.addStretch(1)
        queue_layout.addLayout(job_buttons)
        layout.addWidget(queue_box, 1)

    # -- station control --------------------------------------------------
    def _apply_settings(self) -> None:
        self.config.station_name = self.name_edit.text().strip() or self.config.station_name
        self.config.tcp_port = int(self.port_spin.value())
        self.config.broadcast_presence = self.broadcast_check.isChecked()
        self.config.require_pairing = self.require_code_check.isChecked()
        self.config.workspace_dir = self.workspace_edit.text().strip() or \
            self.config.workspace_dir
        save_config(self.config)

    def _toggle_station(self) -> None:
        if self.station and self.station.running:
            self.station.stop()
            self.station = None
            self.toggle_button.setText("Go online")
            self.status_label.setText("Offline — nothing can reach this PC")
            self._set_settings_enabled(True)
            return

        self._apply_settings()
        try:
            self.station = RenderStation(self.config, on_event=self._on_event,
                                         backend=build_backend(self.config))
            port = self.station.start()
        except OSError as exc:
            QMessageBox.critical(
                self, "Could not start",
                f"Port {self.config.tcp_port} is not available:\n{exc}\n\n"
                "Another copy of the app may already be online.")
            self.station = None
            return

        self.station.store.subscribe(lambda record: self.refresh_signal.emit())
        self.toggle_button.setText("Go offline")
        self.status_label.setText(
            f"<span style='color:{OK}'>Online</span> — senders should use "
            f"{local_ip()} : {port}   ·   backend: {self.station.backend.name}")
        self._set_settings_enabled(False)
        self._refresh_jobs()

    def _set_settings_enabled(self, enabled: bool) -> None:
        for widget in (self.name_edit, self.port_spin, self.workspace_edit,
                       self.require_code_check, self.broadcast_check):
            widget.setEnabled(enabled)

    def _regenerate_code(self) -> None:
        self.config.pairing_code = new_pairing_code()
        self.code_label.setText(self.config.pairing_code)
        save_config(self.config)

    def _pick_workspace(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should incoming projects be stored?",
            self.workspace_edit.text() or str(Path.home()))
        if folder:
            self.workspace_edit.setText(folder)

    # -- Media Encoder ----------------------------------------------------
    def _refresh_ame(self) -> None:
        status = ame.probe(self.config.ame_path)
        colour = OK if status.ready else WARN
        lines = [f"<span style='color:{colour}'>"
                 f"{'Ready' if status.ready else 'Needs attention'}</span>"]
        lines.append(f"Executable: {status.exe or 'not found'}")
        lines.append(f"Agent: {'v' + status.agent_version if status.agent_installed else 'not installed'}"
                     f" · {'running' if status.agent_alive else 'not reporting'}")
        for note in status.notes:
            lines.append(f"<span style='color:{MUTED}'>{note}</span>")
        self.ame_label.setText("<br>".join(lines))

    def _install_agent(self) -> None:
        try:
            target = ame.install_agent(force=True)
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.critical(self, "Install failed", str(exc))
            return
        QMessageBox.information(
            self, "Agent installed",
            f"Installed to:\n{target}\n\n"
            "Now restart Adobe Media Encoder, and make sure "
            "Preferences → General → 'Allow Scripts to Write Files and Access "
            "Network' is ticked.")
        self._refresh_ame()

    # -- queue table ------------------------------------------------------
    def _on_event(self, kind: str, data: dict) -> None:
        logger.debug("station event %s %s", kind, data)
        self.refresh_signal.emit()

    def _selected_job_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _refresh_jobs(self) -> None:
        if not self.station:
            self.table.setRowCount(0)
            return
        records = self.station.store.list()
        selected = self._selected_job_id()
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            name = QTableWidgetItem(record.spec.name or record.job_id[:8])
            name.setData(Qt.UserRole, record.job_id)
            state = QTableWidgetItem(record.state.value)
            state.setForeground(QColor(state_colour(record.state.value)))
            detail = record.error or record.message

            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(record.spec.sender_name))
            self.table.setItem(row, 2, state)
            # Reuse the existing bar: rebuilding widgets every second flickers.
            bar = self.table.cellWidget(row, 3)
            if not isinstance(bar, QProgressBar):
                bar = QProgressBar()
                bar.setRange(0, 1000)
                self.table.setCellWidget(row, 3, bar)
            bar.setValue(int(record.progress * 1000))
            bar.setFormat(f"{record.progress * 100:.0f}%")
            self.table.setItem(row, 4, QTableWidgetItem(detail))
            if selected == record.job_id:
                self.table.selectRow(row)

        busy = self.station.manager.busy
        queued = self.station.queue_length()
        free = human_bytes(
            self.station.describe().get("free_bytes", 0))
        self.status_label.setText(
            f"<span style='color:{OK}'>Online</span> — {local_ip()} : "
            f"{self.station.bound_port}   ·   "
            f"{'rendering' if busy else 'idle'}, {queued} in queue   ·   {free} free")

    def _open_output(self) -> None:
        job_id = self._selected_job_id()
        if job_id and self.station:
            open_in_file_manager(output_dir(self.config.workspace, job_id))

    def _requeue(self) -> None:
        job_id = self._selected_job_id()
        if job_id and self.station:
            self.station.requeue(job_id)

    def _cancel_job(self) -> None:
        job_id = self._selected_job_id()
        if job_id and self.station:
            self.station.cancel_job(job_id)

    def _remove_job(self) -> None:
        job_id = self._selected_job_id()
        if not job_id or not self.station:
            return
        record = self.station.store.get(job_id)
        if record and not record.state.terminal:
            QMessageBox.warning(self, "Job is active",
                                "Cancel the job before removing it.")
            return
        answer = QMessageBox.question(
            self, "Remove job",
            "Remove this job from the list and delete its files from the workspace?")
        if answer == QMessageBox.Yes:
            from ..core.workspace import remove_job_dir
            remove_job_dir(self.config.workspace, job_id)
            self.station.store.remove(job_id)
            self._refresh_jobs()

    def shutdown(self) -> None:
        if self.station:
            self.station.stop()
            self.station = None
