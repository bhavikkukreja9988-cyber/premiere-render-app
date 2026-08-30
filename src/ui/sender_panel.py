"""Sender tab: choose a station, choose a project folder, ship it, get the MP4."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core.config import AppConfig, save_config
from ..core.jobs import JobSpec
from ..core.log import get_logger
from ..core.project_probe import probe_project
from ..core.workspace import human_bytes
from ..network.discovery import StationDiscovery, StationInfo
from ..transfer.transfer_engine import SendRequest, SendWorker, SenderClient, TransferProgress
from .theme import BAD, OK

logger = get_logger("ui.sender")


def open_in_file_manager(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        logger.warning("could not open %s: %s", path, exc)


class SenderPanel(QWidget):
    progress_signal = Signal(object)
    state_signal = Signal(str, dict)
    probe_signal = Signal(object, object)      # projects, sequences

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.worker: Optional[SendWorker] = None
        self.discovery = StationDiscovery(config.discovery_port)
        self._stations: List[StationInfo] = []
        self._last_result: Optional[Path] = None

        self._build()
        self.progress_signal.connect(self._on_progress)
        self.state_signal.connect(self._on_state)
        self.probe_signal.connect(self._on_probe_done)

        self.discovery.start()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_stations)
        self._refresh_timer.start(2000)

    # -- construction -----------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Station -------------------------------------------------------
        station_box = QGroupBox("Render station")
        station_form = QFormLayout(station_box)
        self.station_combo = QComboBox()
        self.station_combo.setPlaceholderText("searching the network…")
        self.station_combo.currentIndexChanged.connect(self._station_selected)
        station_form.addRow("Found on LAN", self.station_combo)

        host_row = QHBoxLayout()
        self.host_edit = QLineEdit(self.config.last_station_host)
        self.host_edit.setPlaceholderText("192.168.1.42")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(self.config.tcp_port)
        host_row.addWidget(self.host_edit, 3)
        host_row.addWidget(self.port_spin, 1)
        station_form.addRow("Address", host_row)

        code_row = QHBoxLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("6-digit code shown on the render station")
        self.code_edit.setMaxLength(12)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._test_connection)
        code_row.addWidget(self.code_edit, 3)
        code_row.addWidget(self.test_button, 1)
        station_form.addRow("Pairing code", code_row)

        self.station_status = QLabel("Not connected")
        self.station_status.setObjectName("hint")
        station_form.addRow("", self.station_status)
        layout.addWidget(station_box)

        # Project -------------------------------------------------------
        project_box = QGroupBox("Project")
        project_form = QFormLayout(project_box)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(self.config.last_project_folder)
        self.folder_edit.setPlaceholderText("folder containing the .prproj and media")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder_edit, 4)
        folder_row.addWidget(browse, 1)
        project_form.addRow("Project folder", folder_row)

        self.project_combo = QComboBox()
        self.project_combo.currentTextChanged.connect(self._project_changed)
        project_form.addRow("Project file", self.project_combo)

        self.sequence_combo = QComboBox()
        self.sequence_combo.setEditable(True)
        project_form.addRow("Sequence", self.sequence_combo)

        self.preset_combo = QComboBox()
        self.preset_combo.setEditable(True)
        self.preset_combo.setToolTip(
            "Media Encoder preset on the render station. Leave blank to use the "
            "station's default preset.")
        project_form.addRow("Preset", self.preset_combo)

        self.output_name_edit = QLineEdit()
        self.output_name_edit.setPlaceholderText("output file name (no extension)")
        project_form.addRow("Output name", self.output_name_edit)

        out_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit(self.config.output_dir)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._pick_output_dir)
        out_row.addWidget(self.output_dir_edit, 4)
        out_row.addWidget(out_browse, 1)
        project_form.addRow("Save result to", out_row)

        self.cleanup_check = QCheckBox("Delete my files from the station once returned")
        self.cleanup_check.setChecked(self.config.delete_remote_after_return)
        project_form.addRow("", self.cleanup_check)
        layout.addWidget(project_box)

        # Transfer ------------------------------------------------------
        transfer_box = QGroupBox("Transfer")
        transfer_layout = QVBoxLayout(transfer_box)
        self.phase_label = QLabel("Idle")
        self.phase_label.setObjectName("heading")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.detail_label = QLabel("Pick a station and a project folder to begin.")
        self.detail_label.setObjectName("hint")
        self.detail_label.setWordWrap(True)

        button_row = QHBoxLayout()
        self.send_button = QPushButton("Send to render station")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self._start_send)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_send)
        self.reveal_button = QPushButton("Open result folder")
        self.reveal_button.clicked.connect(
            lambda: open_in_file_manager(Path(self.output_dir_edit.text().strip()
                                              or self.config.output_dir)))
        button_row.addWidget(self.send_button)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        button_row.addWidget(self.reveal_button)

        transfer_layout.addWidget(self.phase_label)
        transfer_layout.addWidget(self.progress)
        transfer_layout.addWidget(self.detail_label)
        transfer_layout.addLayout(button_row)
        layout.addWidget(transfer_box)
        layout.addStretch(1)

        self.folder_edit.textChanged.connect(self._folder_changed)
        if self.config.last_project_folder:
            self._folder_changed(self.config.last_project_folder)

    # -- station list -----------------------------------------------------
    def _refresh_stations(self) -> None:
        stations = self.discovery.stations()
        if [s.label for s in stations] == [s.label for s in self._stations]:
            return
        self._stations = stations
        current = self.station_combo.currentData()
        self.station_combo.blockSignals(True)
        self.station_combo.clear()
        for station in stations:
            self.station_combo.addItem(station.label, station)
        index = next((i for i, s in enumerate(stations)
                      if current and s.host == getattr(current, "host", None)), -1)
        if index >= 0:
            self.station_combo.setCurrentIndex(index)
        self.station_combo.blockSignals(False)
        if not stations:
            self.station_combo.setPlaceholderText(
                "no stations broadcasting — type an address instead")

    def _station_selected(self, index: int) -> None:
        station = self.station_combo.itemData(index)
        if isinstance(station, StationInfo):
            self.host_edit.setText(station.host)
            self.port_spin.setValue(station.port)
            self.code_edit.setEnabled(station.requires_code)

    # -- project ----------------------------------------------------------
    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the Premiere project folder",
            self.folder_edit.text() or str(Path.home()))
        if folder:
            self.folder_edit.setText(folder)

    def _pick_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should finished renders be saved?",
            self.output_dir_edit.text() or str(Path.home()))
        if folder:
            self.output_dir_edit.setText(folder)

    def _folder_changed(self, text: str) -> None:
        folder = Path(text.strip())
        self.project_combo.clear()
        self.sequence_combo.clear()
        if not folder.is_dir():
            return
        projects = sorted((p.relative_to(folder).as_posix()
                           for p in folder.rglob("*.prproj")
                           if "Auto-Save" not in str(p)),
                          key=lambda p: (p.count("/"), p.lower()))
        self.project_combo.addItems(projects)
        if projects and not self.output_name_edit.text().strip():
            self.output_name_edit.setText(Path(projects[0]).stem)

    def _project_changed(self, relpath: str) -> None:
        folder = Path(self.folder_edit.text().strip())
        if not relpath or not folder.is_dir():
            return
        target = folder / relpath
        self.sequence_combo.clear()
        self.sequence_combo.setEnabled(False)
        self.sequence_combo.lineEdit().setPlaceholderText("reading project…")

        def work() -> None:
            info = probe_project(target)
            self.probe_signal.emit(info.sequences, info.error)

        threading.Thread(target=work, daemon=True, name="probe").start()

    def _on_probe_done(self, sequences, error) -> None:
        self.sequence_combo.setEnabled(True)
        self.sequence_combo.clear()
        self.sequence_combo.addItems(list(sequences or []))
        if not sequences:
            self.sequence_combo.lineEdit().setPlaceholderText(
                "type the sequence name exactly as it appears in Premiere")

    # -- connection -------------------------------------------------------
    def _client_args(self):
        return (self.host_edit.text().strip(), int(self.port_spin.value()),
                self.code_edit.text().strip(), self.config.sender_name)

    def _test_connection(self) -> None:
        host, port, code, name = self._client_args()
        if not host:
            QMessageBox.warning(self, "No address", "Enter the station's IP address.")
            return
        self.test_button.setEnabled(False)
        self.station_status.setText("connecting…")

        def work() -> None:
            try:
                with SenderClient(host, port, code, name, timeout=20) as client:
                    info = client.station_info
                    presets = client.presets()
                info["presets"] = presets
                self.state_signal.emit("probe_ok", info)
            except Exception as exc:                          # noqa: BLE001
                self.state_signal.emit("probe_failed", {"error": str(exc)})

        threading.Thread(target=work, daemon=True, name="probe-station").start()

    # -- sending ----------------------------------------------------------
    def _start_send(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        host, port, code, name = self._client_args()
        folder = Path(self.folder_edit.text().strip())
        if not host:
            QMessageBox.warning(self, "No station", "Enter the station's address.")
            return
        if not folder.is_dir():
            QMessageBox.warning(self, "No project folder",
                                "Choose the folder that holds your project.")
            return
        output_dir = Path(self.output_dir_edit.text().strip() or self.config.output_dir)

        spec = JobSpec(
            name=Path(self.project_combo.currentText()).stem or folder.name,
            project_relpath=self.project_combo.currentText(),
            sequence=self.sequence_combo.currentText().strip(),
            preset_source="station",
            preset_ref=self.preset_combo.currentText().strip(),
            output_name=self.output_name_edit.text().strip(),
            sender_name=name,
            delete_after_return=self.cleanup_check.isChecked(),
        )
        request = SendRequest(host=host, port=port, pairing_code=code,
                              sender_name=name, folder=folder, spec=spec,
                              output_dir=output_dir,
                              delete_remote=self.cleanup_check.isChecked())

        self.config.last_project_folder = str(folder)
        self.config.last_station_host = host
        self.config.output_dir = str(output_dir)
        self.config.delete_remote_after_return = self.cleanup_check.isChecked()
        save_config(self.config)

        self.worker = SendWorker(
            request,
            on_progress=lambda p: self.progress_signal.emit(p),
            on_state=lambda kind, data: self.state_signal.emit(kind, data))
        self.worker.start()
        self.send_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.phase_label.setText("Preparing…")

    def _cancel_send(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.detail_label.setText("Cancelling…")

    # -- signal handlers --------------------------------------------------
    def _on_progress(self, progress: TransferProgress) -> None:
        labels = {"scan": "Scanning project", "upload": "Uploading to station",
                  "queued": "Queued", "render": "Rendering",
                  "wait": "Waiting", "download": "Downloading result",
                  "done": "Finished"}
        self.phase_label.setText(labels.get(progress.phase, progress.phase.title()))
        self.progress.setValue(int(max(0.0, min(1.0, progress.fraction)) * 1000))
        detail = progress.message
        if progress.bytes_total:
            detail += (f"  —  {human_bytes(progress.bytes_done)}"
                       f" / {human_bytes(progress.bytes_total)}")
        if progress.speed_bps:
            detail += f"  ({human_bytes(progress.speed_bps)}/s)"
        self.detail_label.setText(detail)

    def _on_state(self, kind: str, data: dict) -> None:
        if kind == "probe_ok":
            free = human_bytes(float(data.get("free_bytes", 0)))
            self.station_status.setText(
                f"<span style='color:{OK}'>Connected to {data.get('name')}</span> — "
                f"{data.get('backend', 'unknown backend')}, {free} free, "
                f"{data.get('queue_length', 0)} job(s) in the queue")
            presets = data.get("presets") or []
            current = self.preset_combo.currentText()
            self.preset_combo.clear()
            self.preset_combo.addItems(presets)
            self.preset_combo.setCurrentText(current or data.get("default", ""))
            self.test_button.setEnabled(True)
        elif kind == "probe_failed":
            self.station_status.setText(
                f"<span style='color:{BAD}'>{data.get('error')}</span>")
            self.test_button.setEnabled(True)
        elif kind == "complete":
            self._last_result = Path(data.get("path", ""))
            self.send_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.phase_label.setText("Finished")
            self.detail_label.setText(f"Saved to {data.get('path')}")
        elif kind in ("failed", "cancelled"):
            self.send_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.phase_label.setText("Cancelled" if kind == "cancelled" else "Failed")
            if kind == "failed":
                self.detail_label.setText(
                    f"<span style='color:{BAD}'>{data.get('error', '')}</span>")

    def shutdown(self) -> None:
        if self.worker and self.worker.is_alive():
            self.worker.cancel()
        self.discovery.stop()
