"""Sign-in dialog.

Exactly what the plan asks for: a username field, a password field, and a
Log In button — nothing else. Signing in with a username that doesn't exist
yet creates the account automatically (a family shares one login, so there is
no separate "create account" step to walk anyone through).
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QFormLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.log import get_logger
from ..remote.client import RemoteClient
from ..remote.transport import AuthError, OfflineError, RemoteError
from .theme import BAD

logger = get_logger("ui.login")


class LoginDialog(QDialog):
    """Blocking sign-in dialog shown until a session is established."""

    def __init__(self, client: RemoteClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Sign in to Premiere Render App")
        self.setMinimumWidth(380)
        self.setModal(True)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        heading = QLabel("Sign in")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        hint = QLabel(
            "Everyone in the family uses the same username and password. "
            "Signing in with a new username creates it automatically.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("e.g. bhavikfamily")
        form.addRow("Username", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(self._submit)
        form.addRow("Password", self.password_edit)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {BAD};")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.login_button = QPushButton("Log In")
        self.login_button.setObjectName("primary")
        self.login_button.clicked.connect(self._submit)
        layout.addWidget(self.login_button)

        self.username_edit.setFocus()

    def _submit(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self.error_label.setText("Enter both a username and a password.")
            return

        self.login_button.setEnabled(False)
        self.login_button.setText("Signing in…")
        self.error_label.setText("")
        try:
            self.client.auth.sign_in_or_create(username, password)
            logger.info("signed in as %s", username)
            self.accept()
        except OfflineError as exc:
            self.error_label.setText(exc.user_message)
        except AuthError as exc:
            self.error_label.setText(exc.user_message)
        except RemoteError as exc:
            self.error_label.setText(exc.user_message)
            logger.warning("sign-in failed: %s", exc)
        finally:
            self.login_button.setEnabled(True)
            self.login_button.setText("Log In")
