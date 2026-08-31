"""First-run setup dialog.

Shown once, on first launch, so the render station has a sensible project
storage location and a name before anything is received. Everything here can be
changed later in Settings.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.config import AppConfig, save_config



class FirstRunDialog(QDialog):
    """Collects the storage location and station name on first launch."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Welcome to Premiere Render App")
        self.setMinimumWidth(560)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        heading = QLabel("Quick setup")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        blurb = QLabel(
            "This PC can send Premiere projects and also act as a render "
            "station that receives and renders them. You can change any of "
            "this later in Settings.")
        blurb.setObjectName("hint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit(self.config.station_name)
        form.addRow("Name for this PC", self.name_edit)

        storage_row = QHBoxLayout()
        self.storage_edit = QLineEdit(self.config.workspace_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_storage)
        storage_row.addWidget(self.storage_edit, 4)
        storage_row.addWidget(browse, 1)
        form.addRow("Store received projects in", storage_row)

        note = QLabel(
            "Received Premiere projects and their media are stored here while "
            "they render. Pick a drive with plenty of free space.")
        note.setObjectName("hint")
        note.setWordWrap(True)

        layout.addLayout(form)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Get started")
        buttons.accepted.connect(self._accept)
        layout.addWidget(buttons)

    def _pick_storage(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should received Premiere projects be stored?",
            self.storage_edit.text() or str(Path.home()))
        if folder:
            self.storage_edit.setText(folder)

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        storage = self.storage_edit.text().strip()
        if name:
            self.config.station_name = name
        if storage:
            self.config.workspace_dir = storage
        self.config.first_run = False
        save_config(self.config)
        self.accept()
