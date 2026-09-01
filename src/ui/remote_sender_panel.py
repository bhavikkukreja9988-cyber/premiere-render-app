"""The redesigned Sender experience (plan sections 10-15): drag a project in,
pick an online station, hit Send. No IP, no port, no pairing code.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from ..core.config import AppConfig, save_config
from ..core.log import get_logger
from ..core.project_probe import find_external_media, probe_project
from ..remote.client import RemoteClient
from ..remote.models import Station
from ..remote.send_gate import evaluate_send
from ..remote.sender_service import RemoteProgress, RemoteSendRequest, RemoteSendWorker
from ..remote.transport import RemoteError
from .sender_panel import open_in_file_manager
from .theme import BAD, OK, WARN

logger = get_logger("ui.remote_sender")

STATION_REFRESH_MS = 3000
GATE_REFRESH_MS = 1000


def _find_prproj_and_root(paths: List[Path]) -> Optional[tuple]:
    """From dropped/browsed paths, work out (project_root, prproj_relpath)."""
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".prproj":
            return path.parent, path.name
    for path in paths:
        if path.is_dir():
            matches = sorted(path.rglob("*.prproj"),
                             key=lambda p: (len(p.parts), p.name.lower()))
            matches = [m for m in matches if "Auto-Save" not in str(m)]
            if matches:
                return path, matches[0].relative_to(path).as_posix()
    return None


class DropArea(QLabel):
    """A large drop target for a .prproj file or a project folder."""

    files_dropped = Signal(list)

    _BASE_STYLE = ("QLabel { border: 2px dashed #444a5a; border-radius: 10px; "
                   "padding: 18px; }")
    _HOVER_STYLE = ("QLabel { border: 2px dashed #4d7cfe; border-radius: 10px; "
                    "padding: 18px; background: rgba(77, 124, 254, 0.08); }")

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(120)
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self._reset_text()
        self.setStyleSheet(self._BASE_STYLE)

    def _reset_text(self) -> None:
        self.setText(
            "DROP PREMIERE PROJECT HERE\n\n"
            "Drop a .prproj file or a Premiere project folder")

    def show_selection(self, name: str) -> None:
        self.setText(f"Project selected:\n{name}\n\n(drop another to replace it)")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self.setStyleSheet(self._HOVER_STYLE)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet(self._BASE_STYLE)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet(self._BASE_STYLE)
        mime: QMimeData = event.mimeData()
        paths = [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()


class RemoteSenderPanel(QWidget):
    progress_signal = Signal(object)
    state_signal = Signal(str, dict)
    probe_signal = Signal(object, object, object)   # sequences, error, external

    def __init__(self, client: RemoteClient, config: AppConfig) -> None:
        super().__init__()
        self.client = client
        self.config = config
        self.worker: Optional[RemoteSendWorker] = None
        self._project_root: Optional[Path] = None
        self._project_relpath: str = ""
        self._project_validated = False
        self._external_media: List[str] = []
        self._stations: List[Station] = []

        self._build()
        self.progress_signal.connect(self._on_progress)
        self.state_signal.connect(self._on_state)
        self.probe_signal.connect(self._on_probe_done)

        self._station_timer = QTimer(self)
        self._station_timer.timeout.connect(self._refresh_stations)
        self._station_timer.start(STATION_REFRESH_MS)
        self._refresh_stations()

        self._gate_timer = QTimer(self)
        self._gate_timer.timeout.connect(self._update_gate)
        self._gate_timer.start(GATE_REFRESH_MS)

    # -- construction -------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        heading = QLabel("Send a project")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        # Station picker ------------------------------------------------
        station_row = QHBoxLayout()
        station_row.addWidget(QLabel("Render Station:"))
        self.station_combo = QComboBox()
        self.station_combo.currentIndexChanged.connect(self._station_selected)
        station_row.addWidget(self.station_combo, 1)
        self.station_status = QLabel("checking…")
        station_row.addWidget(self.station_status)
        layout.addLayout(station_row)

        # Drop area -------------------------------------------------------
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._paths_selected)
        layout.addWidget(self.drop_area)

        browse_row = QHBoxLayout()
        browse_folder = QPushButton("Browse for a project folder…")
        browse_folder.clicked.connect(self._browse_folder)
        browse_file = QPushButton("Browse for a .prproj file…")
        browse_file.clicked.connect(self._browse_file)
        browse_row.addWidget(browse_folder)
        browse_row.addWidget(browse_file)
        browse_row.addStretch(1)
        layout.addLayout(browse_row)

        self.external_warning = QLabel("")
        self.external_warning.setWordWrap(True)
        self.external_warning.setStyleSheet(f"color: {WARN};")
        layout.addWidget(self.external_warning)

        # Options ---------------------------------------------------------
        options_box = QGroupBox("Options")
        form = QFormLayout(options_box)
        self.sequence_combo = QComboBox()
        self.sequence_combo.setEditable(True)
        form.addRow("Sequence", self.sequence_combo)

        self.preset_combo = QComboBox()
        self.preset_combo.setEditable(True)
        form.addRow("Preset", self.preset_combo)

        self.output_name_edit = QLineEdit()
        self.output_name_edit.setPlaceholderText("output file name")
        form.addRow("Output name", self.output_name_edit)

        out_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit(self.config.output_dir)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._pick_output_dir)
        out_row.addWidget(self.output_dir_edit, 4)
        out_row.addWidget(out_browse, 1)
        form.addRow("Save result to", out_row)

        self.delete_after_check = QCheckBox(
            "Delete received project after successful delivery")
        form.addRow("", self.delete_after_check)
        layout.addWidget(options_box)

        # Send + progress ---------------------------------------------------
        self.send_button = QPushButton("SEND")
        self.send_button.setObjectName("primary")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._start_send)
        layout.addWidget(self.send_button)

        self.gate_reason = QLabel("Drop or choose a Premiere project first.")
        self.gate_reason.setObjectName("hint")
        self.gate_reason.setWordWrap(True)
        layout.addWidget(self.gate_reason)

        self.phase_label = QLabel("")
        self.phase_label.setObjectName("heading")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("hint")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.phase_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.detail_label)

        button_row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_send)
        self.reveal_button = QPushButton("Open result folder")
        self.reveal_button.clicked.connect(
            lambda: open_in_file_manager(
                Path(self.output_dir_edit.text().strip() or self.config.output_dir)))
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        button_row.addWidget(self.reveal_button)
        layout.addLayout(button_row)
        layout.addStretch(1)

    # -- stations -------------------------------------------------------------
    def _refresh_stations(self) -> None:
        if not self.client.signed_in:
            return
        try:
            stations = self.client.stations.list_stations()
        except RemoteError as exc:
            self.station_status.setText(
                f"<span style='color:{BAD}'>{exc.user_message}</span>")
            return

        labels = [s.id for s in stations]
        if labels == [s.id for s in self._stations]:
            self._refresh_station_status_only(stations)
            return
        self._stations = stations
        current_id = self.station_combo.currentData()
        self.station_combo.blockSignals(True)
        self.station_combo.clear()
        for station in stations:
            marker = self._status_marker_plain(station)
            self.station_combo.addItem(f"{station.name}  {marker}", station.id)
        self.station_combo.blockSignals(False)

        # Restore selection: prefer the remembered station, else auto-pick the
        # only online one, matching plan section 8.
        target = current_id or self.config.last_station_id
        index = next((i for i in range(self.station_combo.count())
                      if self.station_combo.itemData(i) == target), -1)
        if index < 0:
            online_ones = [s for s in stations
                          if s.is_online(self.client.config.station_offline_after)]
            if len(online_ones) == 1:
                index = next(i for i in range(self.station_combo.count())
                            if self.station_combo.itemData(i) == online_ones[0].id)
        if index >= 0:
            self.station_combo.setCurrentIndex(index)
        self._refresh_station_status_only(stations)

    def _status_marker_plain(self, station: Station) -> str:
        """Plain-text 'Online' / 'Busy' / 'Offline' for the dropdown list."""
        if not station.is_online(self.client.config.station_offline_after):
            return "● Offline"
        if station.status == "busy":
            return "● Busy"
        return "● Online"

    def _refresh_station_status_only(self, stations: List[Station]) -> None:
        station = self._selected_station()
        if station is None:
            self.station_status.setText(
                "No render stations yet. Open this app on another PC and set "
                "it up as a Render Station — it'll appear here automatically.")
            return
        if not station.is_online(self.client.config.station_offline_after):
            colour, state = BAD, "Offline"
        elif station.status == "busy":
            colour, state = WARN, "Busy — rendering another job"
        else:
            colour, state = OK, "Online"
        self.station_status.setText(f"<span style='color:{colour}'>● {state}</span>")
        presets = list((station.capabilities or {}).get("presets") or [])
        current = self.preset_combo.currentText()
        self.preset_combo.clear()
        self.preset_combo.addItems(presets)
        self.preset_combo.setCurrentText(current)

    def _selected_station(self) -> Optional[Station]:
        station_id = self.station_combo.currentData()
        return next((s for s in self._stations if s.id == station_id), None)

    def _station_selected(self, _index: int) -> None:
        station = self._selected_station()
        if station:
            self.config.last_station_id = station.id
            save_config(self.config)
        self._refresh_station_status_only(self._stations)

    # -- project selection ----------------------------------------------------
    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the Premiere project folder", str(Path.home()))
        if folder:
            self._paths_selected([Path(folder)])

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a .prproj file", str(Path.home()),
            "Premiere Project (*.prproj)")
        if path:
            self._paths_selected([Path(path)])

    def _paths_selected(self, paths: List[Path]) -> None:
        found = _find_prproj_and_root(paths)
        if found is None:
            QMessageBox.warning(self, "No project found",
                                "That didn't contain a .prproj file.")
            return
        root, relpath = found
        self._project_root = root
        self._project_relpath = relpath
        self._project_validated = False
        self._external_media = []
        self.drop_area.show_selection(f"{root.name}/{relpath}")
        self.external_warning.setText("")
        if not self.output_name_edit.text().strip():
            self.output_name_edit.setText(Path(relpath).stem)
        self.sequence_combo.clear()
        self.sequence_combo.lineEdit().setPlaceholderText("checking project…")

        def work() -> None:
            info = probe_project(root / relpath)
            external = find_external_media(root / relpath, root)
            self.probe_signal.emit(info.sequences, info.error, external)

        threading.Thread(target=work, daemon=True, name="probe").start()

    def _on_probe_done(self, sequences, error, external) -> None:
        self.sequence_combo.clear()
        self.sequence_combo.addItems(list(sequences or []))
        if not sequences:
            self.sequence_combo.lineEdit().setPlaceholderText(
                "type the sequence name exactly as it appears in Premiere")
        self._external_media = list(external or [])
        self._project_validated = True
        if self._external_media:
            names = ", ".join(Path(p).name for p in self._external_media[:5])
            more = f" and {len(self._external_media) - 5} more" if \
                len(self._external_media) > 5 else ""
            self.external_warning.setText(
                "⚠ This project references media outside the selected folder "
                f"({names}{more}). Those files may be offline on the Render "
                "Station.")
        else:
            self.external_warning.setText("")

    def _pick_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should finished renders be saved?",
            self.output_dir_edit.text() or str(Path.home()))
        if folder:
            self.output_dir_edit.setText(folder)

    # -- send gate --------------------------------------------------------
    def _update_gate(self) -> None:
        station = self._selected_station()
        gate = evaluate_send(
            signed_in=self.client.signed_in,
            project_selected=self._project_root is not None,
            project_validated=self._project_validated,
            station=station, config=self.client.config)
        busy = self.worker is not None and self.worker.is_alive()
        self.send_button.setEnabled(gate.can_send and not busy)
        self.gate_reason.setText(
            "" if gate.can_send else gate.reason)
        if station:
            self._refresh_station_status_only(self._stations)

    # -- sending ------------------------------------------------------------
    def _start_send(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        station = self._selected_station()
        if station is None or self._project_root is None:
            return

        if self._external_media:
            answer = QMessageBox.question(
                self, "Media outside the project folder",
                "This project references media outside the selected folder. "
                "Those files may be offline on the Render Station.\n\n"
                "Send anyway?",
                QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                return

        output_dir = Path(self.output_dir_edit.text().strip() or
                          self.config.output_dir)
        self.config.output_dir = str(output_dir)
        save_config(self.config)

        request = RemoteSendRequest(
            station_id=station.id, folder=self._project_root,
            project_name=Path(self._project_relpath).stem,
            output_dir=output_dir,
            sequence=self.sequence_combo.currentText().strip(),
            preset=self.preset_combo.currentText().strip(),
            output_name=self.output_name_edit.text().strip(),
            delete_after_delivery=self.delete_after_check.isChecked(),
        )
        self.worker = RemoteSendWorker(
            self.client, request,
            on_progress=lambda p: self.progress_signal.emit(p),
            on_state=lambda kind, data: self.state_signal.emit(kind, data))
        self.worker.start()
        self.send_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.phase_label.setText("Starting…")

    def _cancel_send(self) -> None:
        if not self.worker:
            return
        answer = QMessageBox.question(
            self, "Cancel send?",
            "Cancel this send? Anything already uploaded will be discarded.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.worker.cancel()
            self.detail_label.setText("Cancelling…")

    # -- signal handlers --------------------------------------------------
    def _on_progress(self, progress: RemoteProgress) -> None:
        labels = {"scan": "Scanning project", "upload": "Uploading",
                  "uploaded": "Uploaded", "wait": "Reconnecting",
                  "render": "Rendering", "download": "Downloading result",
                  "done": "Finished"}
        self.phase_label.setText(labels.get(progress.phase, progress.phase.title()))
        self.progress_bar.setValue(int(max(0.0, min(1.0, progress.fraction)) * 1000))
        detail = progress.message
        if progress.bytes_total:
            detail += f"  —  {progress.bytes_done}/{progress.bytes_total}"
        self.detail_label.setText(detail)

    def _on_state(self, kind: str, data: dict) -> None:
        if kind == "complete":
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
