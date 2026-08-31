"""Settings tab for the Remote V3 product.

The final normal Settings UI exposes cloud/account, Render Station, Sender and
General settings. Legacy LAN-only controls are intentionally hidden; legacy
network modules may remain in the repository only as migration/reference code.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ..core.config import AppConfig, save_config
from ..core.log import get_logger
from .theme import MUTED, OK

logger = get_logger("ui.settings")


class SettingsPanel(QWidget):
    def __init__(self, config: AppConfig, client=None) -> None:
        super().__init__()
        self.config = config
        self.client = client
        self._build()
        self._load()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        account_box = QGroupBox("Account")
        account_form = QFormLayout(account_box)
        self.account_label = QLabel("Not signed in")
        sign_out = QPushButton("Sign out")
        sign_out.clicked.connect(self._sign_out)
        account_row = QHBoxLayout()
        account_row.addWidget(self.account_label, 1)
        account_row.addWidget(sign_out)
        account_form.addRow("Signed in as", account_row)
        outer.addWidget(account_box)

        station_box = QGroupBox("Render station")
        station_form = QFormLayout(station_box)

        self.station_name = QLineEdit()
        station_form.addRow("Station name", self.station_name)

        self.station_role_enabled = QCheckBox(
            "Also act as a Render Station (receive and render projects)")
        station_form.addRow("", self.station_role_enabled)

        storage_row = QHBoxLayout()
        self.storage_dir = QLineEdit()
        storage_browse = QPushButton("Browse…")
        storage_browse.clicked.connect(self._pick_storage)
        storage_row.addWidget(self.storage_dir, 4)
        storage_row.addWidget(storage_browse, 1)
        station_form.addRow("Project storage location", storage_row)

        self.accept_automatically = QCheckBox(
            "Accept incoming jobs automatically")
        station_form.addRow("Incoming jobs", self.accept_automatically)

        self.retention = QComboBox()
        for label, days in AppConfig.RETENTION_CHOICES:
            self.retention.addItem(label, days)
        self.retention.addItem("Custom…", -1)
        self.retention.currentIndexChanged.connect(self._retention_changed)
        self.retention_custom = QSpinBox()
        self.retention_custom.setRange(1, 3650)
        self.retention_custom.setSuffix(" days")
        self.retention_custom.setVisible(False)
        retention_row = QHBoxLayout()
        retention_row.addWidget(self.retention, 1)
        retention_row.addWidget(self.retention_custom, 1)
        station_form.addRow("Delete completed projects after", retention_row)

        retention_note = QLabel(
            "Only safely completed received projects are eligible for automatic "
            "cleanup. The Sender's original project is never touched.")
        retention_note.setObjectName("hint")
        retention_note.setWordWrap(True)
        station_form.addRow("", retention_note)

        ame_row = QHBoxLayout()
        self.ame_path = QLineEdit()
        self.ame_path.setPlaceholderText("auto-detected if left blank")
        ame_browse = QPushButton("Browse…")
        ame_browse.clicked.connect(self._pick_ame)
        ame_row.addWidget(self.ame_path, 4)
        ame_row.addWidget(ame_browse, 1)
        station_form.addRow("Media Encoder location", ame_row)

        self.default_preset = QLineEdit()
        self.default_preset.setPlaceholderText("Media Encoder preset name")
        station_form.addRow("Default export preset", self.default_preset)

        self.station_id_label = QLabel()
        self.station_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        station_form.addRow("Station ID", self.station_id_label)
        outer.addWidget(station_box)

        sender_box = QGroupBox("Sender")
        sender_form = QFormLayout(sender_box)

        out_row = QHBoxLayout()
        self.output_dir = QLineEdit()
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._pick_output)
        out_row.addWidget(self.output_dir, 4)
        out_row.addWidget(out_browse, 1)
        sender_form.addRow("Output folder", out_row)

        self.sender_name = QLineEdit()
        sender_form.addRow("Sender name", self.sender_name)

        last_label = QLabel(
            "The selected Render Station is remembered automatically. "
            "No IP address is required.")
        last_label.setObjectName("hint")
        last_label.setWordWrap(True)
        sender_form.addRow("Render Station", last_label)
        outer.addWidget(sender_box)

        general_box = QGroupBox("General")
        general_form = QFormLayout(general_box)
        self.start_with_windows = QCheckBox("Start this app when Windows starts")
        general_form.addRow("Startup", self.start_with_windows)
        self.log_level = QComboBox()
        self.log_level.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])
        general_form.addRow("Logging level", self.log_level)
        outer.addWidget(general_box)

        save_row = QHBoxLayout()
        self.saved_label = QLabel("")
        self.saved_label.setObjectName("hint")
        save_button = QPushButton("Save settings")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._save)
        save_row.addWidget(self.saved_label, 1)
        save_row.addWidget(save_button)
        outer.addLayout(save_row)
        outer.addStretch(1)

    def _load(self) -> None:
        c = self.config
        self.station_name.setText(c.station_name)
        self.station_role_enabled.setChecked(c.station_role_enabled)
        self.storage_dir.setText(c.workspace_dir)
        self.accept_automatically.setChecked(c.accept_jobs_automatically)
        self._set_retention(c.retention_days)
        self.ame_path.setText(c.ame_path)
        self.default_preset.setText(c.default_preset)
        self.station_id_label.setText(c.station_id)
        self.output_dir.setText(c.output_dir)
        self.sender_name.setText(c.sender_name)
        self.start_with_windows.setChecked(c.start_with_windows)
        self.log_level.setCurrentText(c.log_level)
        self._refresh_account_label()

    def _refresh_account_label(self) -> None:
        if self.client and self.client.signed_in:
            self.account_label.setText(
                f"<span style='color:{OK}'>{self.client.auth.username}</span>")
        else:
            self.account_label.setText(
                f"<span style='color:{MUTED}'>Not signed in</span>")

    def _set_retention(self, days: int) -> None:
        for i in range(self.retention.count()):
            if self.retention.itemData(i) == days:
                self.retention.setCurrentIndex(i)
                self.retention_custom.setVisible(False)
                return
        self.retention.setCurrentIndex(self.retention.count() - 1)
        self.retention_custom.setValue(max(1, days))
        self.retention_custom.setVisible(True)

    def _retention_changed(self, _index: int) -> None:
        self.retention_custom.setVisible(self.retention.currentData() == -1)

    def _current_retention_days(self) -> int:
        data = self.retention.currentData()
        return int(self.retention_custom.value()) if data == -1 else int(data)

    def _save(self) -> None:
        c = self.config
        c.station_name = self.station_name.text().strip() or c.station_name
        c.station_role_enabled = self.station_role_enabled.isChecked()
        c.workspace_dir = self.storage_dir.text().strip() or c.workspace_dir
        c.accept_jobs_automatically = self.accept_automatically.isChecked()
        c.retention_days = self._current_retention_days()
        c.ame_path = self.ame_path.text().strip()
        c.default_preset = self.default_preset.text().strip()
        c.output_dir = self.output_dir.text().strip() or c.output_dir
        c.sender_name = self.sender_name.text().strip() or c.sender_name
        c.start_with_windows = self.start_with_windows.isChecked()
        c.log_level = self.log_level.currentText()
        save_config(c)
        self._apply_start_with_windows(c.start_with_windows)
        self.saved_label.setText(f"<span style='color:{OK}'>Settings saved.</span>")

    def _apply_start_with_windows(self, enabled: bool) -> None:
        try:
            from ..core import autostart
            autostart.set_start_with_windows(enabled)
        except Exception as exc:
            logger.warning("could not update Windows startup: %s", exc)

    def _pick_storage(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should received Premiere projects be stored?",
            self.storage_dir.text() or str(Path.home()))
        if folder:
            self.storage_dir.setText(folder)

    def _pick_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should finished renders be saved?",
            self.output_dir.text() or str(Path.home()))
        if folder:
            self.output_dir.setText(folder)

    def _pick_ame(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Locate Adobe Media Encoder.exe",
            self.ame_path.text() or "C:/Program Files/Adobe",
            "Adobe Media Encoder (Adobe Media Encoder.exe);;All files (*.*)")
        if path:
            self.ame_path.setText(path)

    def _sign_out(self) -> None:
        if self.client:
            self.client.auth.sign_out()
        self._refresh_account_label()
        QMessageBox.information(
            self, "Signed out", "You have been signed out. Restart FileSender "
            "before using the Render Station again.")
