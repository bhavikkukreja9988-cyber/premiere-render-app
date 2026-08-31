"""First-run setup wizard.

One guided flow instead of two separate dialogs: sign in, choose whether this
PC sends projects, receives them, or both, and — if it receives them —
configure the render station basics. Shown once; everything here can be
changed later in Settings.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..core.config import AppConfig, save_config
from ..remote.client import RemoteClient
from ..remote.transport import AuthError, OfflineError, RemoteError
from .theme import BAD


class _WelcomePage(QWidget):
    def __init__(self, client: RemoteClient) -> None:
        super().__init__()
        self.client = client
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        heading = QLabel("Welcome to Premiere Render App")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        hint = QLabel(
            "Everyone in the family signs in with the same username and "
            "password. Signing in with a new username creates it "
            "automatically — there's no separate sign-up step.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("e.g. bhavikfamily")
        form.addRow("Username", self.username_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password", self.password_edit)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {BAD};")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        layout.addStretch(1)

    def try_sign_in(self) -> bool:
        if self.client.signed_in:
            return True
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self.error_label.setText("Enter both a username and a password.")
            return False
        try:
            self.client.auth.sign_in_or_create(username, password)
            return True
        except (AuthError, OfflineError, RemoteError) as exc:
            self.error_label.setText(exc.user_message)
            return False


class _RolePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        heading = QLabel("How will this PC be used?")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        hint = QLabel("Pick at least one. You can change this later in Settings.")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        self.sender_check = QCheckBox(
            "Sender — pick a Premiere project on this PC and send it out")
        self.sender_check.setChecked(True)
        self.station_check = QCheckBox(
            "Render Station — receive projects and render them here")
        layout.addWidget(self.sender_check)
        layout.addWidget(self.station_check)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {BAD};")
        layout.addWidget(self.error_label)
        layout.addStretch(1)

    def validate(self) -> bool:
        if not self.sender_check.isChecked() and not self.station_check.isChecked():
            self.error_label.setText("Choose at least one option.")
            return False
        self.error_label.setText("")
        return True


class _StationPage(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        heading = QLabel("Render Station setup")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        form = QFormLayout()
        self.name_edit = QLineEdit(config.station_name)
        form.addRow("Station name", self.name_edit)

        storage_row = QHBoxLayout()
        self.storage_edit = QLineEdit(config.workspace_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_storage)
        storage_row.addWidget(self.storage_edit, 4)
        storage_row.addWidget(browse, 1)
        form.addRow("Store received projects in", storage_row)

        self.accept_check = QCheckBox("Accept incoming jobs automatically")
        self.accept_check.setChecked(config.accept_jobs_automatically)
        form.addRow("New jobs", self.accept_check)

        self.retention_combo = QComboBox()
        for label, days in AppConfig.RETENTION_CHOICES:
            self.retention_combo.addItem(label, days)
        current = next((i for i in range(self.retention_combo.count())
                        if self.retention_combo.itemData(i) == config.retention_days),
                       0)
        self.retention_combo.setCurrentIndex(current)
        form.addRow("Delete completed projects after", self.retention_combo)
        layout.addLayout(form)

        note = QLabel(
            "Media Encoder will be detected automatically. If it isn't found, "
            "you can set its location later in Settings.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def _pick_storage(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Where should received Premiere projects be stored?",
            self.storage_edit.text() or str(Path.home()))
        if folder:
            self.storage_edit.setText(folder)

    def apply(self, config: AppConfig) -> None:
        if self.name_edit.text().strip():
            config.station_name = self.name_edit.text().strip()
        if self.storage_edit.text().strip():
            config.workspace_dir = self.storage_edit.text().strip()
        config.accept_jobs_automatically = self.accept_check.isChecked()
        config.retention_days = int(self.retention_combo.currentData() or 0)


class SetupWizard(QDialog):
    """Sign in, choose a role, and configure the station in one flow."""

    def __init__(self, client: RemoteClient, config: AppConfig,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.config = config
        self.setWindowTitle("Set up Premiere Render App")
        self.setMinimumWidth(480)
        self.setModal(True)

        self.welcome_page = _WelcomePage(client)
        self.role_page = _RolePage()
        self.station_page = _StationPage(config)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome_page)
        self.stack.addWidget(self.role_page)
        self.stack.addWidget(self.station_page)

        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)

        button_row = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._go_back)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self._go_next)
        button_row.addWidget(self.back_button)
        button_row.addStretch(1)
        button_row.addWidget(self.next_button)
        layout.addLayout(button_row)

        if client.signed_in:
            self.stack.setCurrentWidget(self.role_page)
        self._update_buttons()

    def _current_index(self) -> int:
        return self.stack.currentIndex()

    def _update_buttons(self) -> None:
        self.back_button.setEnabled(
            self._current_index() > (1 if self.client.signed_in else 0))
        on_station_page = self.stack.currentWidget() is self.station_page
        wants_station = self.role_page.station_check.isChecked()
        is_last_page = on_station_page or (
            self.stack.currentWidget() is self.role_page and not wants_station)
        self.next_button.setText("Finish" if is_last_page else "Next")

    def _go_back(self) -> None:
        index = self._current_index()
        if index > 0:
            self.stack.setCurrentIndex(index - 1)
        self._update_buttons()

    def _go_next(self) -> None:
        current = self.stack.currentWidget()
        if current is self.welcome_page:
            if not self.welcome_page.try_sign_in():
                return
            self.stack.setCurrentWidget(self.role_page)
        elif current is self.role_page:
            if not self.role_page.validate():
                return
            if self.role_page.station_check.isChecked():
                self.stack.setCurrentWidget(self.station_page)
            else:
                self._finish()
                return
        elif current is self.station_page:
            self._finish()
            return
        self._update_buttons()

    def _finish(self) -> None:
        self.config.station_role_enabled = self.role_page.station_check.isChecked()
        if self.config.station_role_enabled:
            self.station_page.apply(self.config)
        self.config.first_run = False
        save_config(self.config)
        self.accept()
