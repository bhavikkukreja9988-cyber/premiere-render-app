"""First-run setup.

Two things, once: what to call this PC, and the family code that decides which
other PCs it can see. No username, no password, no sender/receiver choice —
every install can both send and receive, and signs in to the shared account
silently in the background.

The family code is the visibility boundary. Devices that type the same code
see each other; devices that don't, don't.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.config import AppConfig, normalise_family_code, save_config
from ..core.log import get_logger
from .theme import BAD, MUTED

logger = get_logger("ui.setup")


class SetupWizard(QDialog):
    """Shown once, on first launch."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Set up FileSender")
        self.setMinimumWidth(460)
        self.setModal(True)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        heading = QLabel("Welcome to FileSender")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        blurb = QLabel(
            "Name this PC, and choose a family code. Every PC that uses the "
            "same family code can send renders to the others.")
        blurb.setObjectName("hint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        form = QFormLayout()
        form.setSpacing(10)

        self.device_name = QLineEdit()
        self.device_name.setPlaceholderText("e.g. Bhavik's PC")
        self.device_name.textChanged.connect(self._validate)
        form.addRow("Name this PC", self.device_name)

        self.family_code = QLineEdit()
        self.family_code.setPlaceholderText("e.g. smith-family")
        self.family_code.textChanged.connect(self._validate)
        form.addRow("Family code", self.family_code)
        layout.addLayout(form)

        code_hint = QLabel(
            "Type the same family code on every PC in your household. Treat "
            "it like a shared password — anyone who knows it can see your "
            "PCs and send them jobs.")
        code_hint.setObjectName("hint")
        code_hint.setWordWrap(True)
        layout.addWidget(code_hint)

        # Render station storage — only relevant if this PC receives jobs,
        # but every PC can, so it's always asked. Sensible default provided.
        storage_row = QHBoxLayout()
        self.storage_dir = QLineEdit(self.config.workspace_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_storage)
        storage_row.addWidget(self.storage_dir, 4)
        storage_row.addWidget(browse, 1)
        storage_form = QFormLayout()
        storage_form.addRow("Store received projects in", storage_row)

        self.retention = QComboBox()
        for label, days in AppConfig.RETENTION_CHOICES:
            self.retention.addItem(label, days)
        # Default to 7 days rather than "Never": the station otherwise fills
        # its drive silently, which surprised the user during testing.
        seven = next((i for i in range(self.retention.count())
                      if self.retention.itemData(i) == 7), 0)
        self.retention.setCurrentIndex(seven)
        storage_form.addRow("Delete finished or failed jobs after", self.retention)

        self.accept_auto = QCheckBox("Accept incoming jobs automatically")
        self.accept_auto.setChecked(True)
        storage_form.addRow("", self.accept_auto)
        layout.addLayout(storage_form)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {BAD};")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.finish_btn = QPushButton("Get Started")
        self.finish_btn.setObjectName("primary")
        self.finish_btn.setEnabled(False)
        self.finish_btn.clicked.connect(self._finish)
        layout.addWidget(self.finish_btn)

        self.device_name.setFocus()

    def _validate(self) -> None:
        ok = bool(self.device_name.text().strip() and
                  self.family_code.text().strip())
        self.finish_btn.setEnabled(ok)

    def _pick_storage(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should received Premiere projects be stored?",
            self.storage_dir.text() or str(Path.home()))
        if folder:
            self.storage_dir.setText(folder)

    def _finish(self) -> None:
        name = self.device_name.text().strip()
        code = self.family_code.text().strip()
        if not name or not code:
            self.error.setText("Both a PC name and a family code are needed.")
            return

        self.config.device_name = name
        # Normalised so "Smith Family" and "smith family" match — a mismatch
        # here silently hides PCs from each other, which is exactly the class
        # of bug this whole redesign set out to remove.
        self.config.family_code = normalise_family_code(code)
        self.config.station_name = name
        if self.storage_dir.text().strip():
            self.config.workspace_dir = self.storage_dir.text().strip()
        self.config.retention_days = int(self.retention.currentData() or 0)
        self.config.accept_jobs_automatically = self.accept_auto.isChecked()
        self.config.first_run = False
        save_config(self.config)
        logger.info("setup complete: %s / %s", name, self.config.family_code)
        self.accept()
