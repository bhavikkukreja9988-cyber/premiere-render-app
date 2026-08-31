"""Authentication service.

The user types only a username and password. Internally that maps to a Supabase
email/password account (see ``config.username_to_email``). Sessions are
persisted locally so the app signs in silently on subsequent launches.

Session storage is a JSON file in the app data dir with owner-only permissions.
This is adequate for a family tool; a future hardening step could move the
refresh token into the OS credential store.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional

from ..core.config import app_data_dir
from ..core.log import get_logger
from .config import RemoteConfig, username_to_email
from .models import Session
from .transport import AuthError, NotAuthenticatedError, RemoteTransport

logger = get_logger("remote.auth")


def session_path() -> Path:
    return app_data_dir() / "session.json"


class AuthService:
    def __init__(self, transport: RemoteTransport, config: RemoteConfig) -> None:
        self.transport = transport
        self.config = config
        self._session: Optional[Session] = None

    @property
    def session(self) -> Optional[Session]:
        return self._session

    @property
    def signed_in(self) -> bool:
        return self._session is not None and self._session.valid

    @property
    def user_id(self) -> str:
        return self._session.user_id if self._session else ""

    @property
    def username(self) -> str:
        return self._session.username if self._session else ""

    # -- operations -------------------------------------------------------
    def sign_up(self, username: str, password: str) -> Session:
        if len(password) < 4:
            raise AuthError("Please choose a password of at least 4 characters.")
        email = username_to_email(username, self.config.username_email_domain)
        session = self.transport.sign_up(email, password)
        session.username = username.strip()
        self._session = session
        self._persist()
        logger.info("created account for %s", username)
        return session

    def sign_in(self, username: str, password: str) -> Session:
        email = username_to_email(username, self.config.username_email_domain)
        session = self.transport.sign_in(email, password)
        session.username = username.strip()
        self._session = session
        self._persist()
        logger.info("signed in as %s", username)
        return session

    def sign_in_or_create(self, username: str, password: str) -> Session:
        """Convenience for a family tool: sign in, creating the account if new."""
        try:
            return self.sign_in(username, password)
        except AuthError:
            # Could be "no such account" or "wrong password". Try to create;
            # if the username already exists this raises and we surface the
            # original bad-credentials meaning.
            try:
                return self.sign_up(username, password)
            except AuthError:
                raise AuthError(
                    "That username or password was not accepted.") from None

    def restore(self) -> bool:
        """Restore a persisted session on startup. Returns True on success."""
        stored = self._load()
        if stored is None:
            return False
        try:
            session = self.transport.restore_session(stored)
            session.username = stored.username or session.username
            self._session = session
            self._persist()
            logger.info("restored session for %s", session.username)
            return True
        except (NotAuthenticatedError, Exception) as exc:  # noqa: BLE001
            logger.info("stored session could not be restored: %s", exc)
            return False

    def sign_out(self) -> None:
        try:
            self.transport.sign_out()
        finally:
            self._session = None
            try:
                session_path().unlink(missing_ok=True)
            except OSError:
                pass

    # -- persistence ------------------------------------------------------
    def _persist(self) -> None:
        if not self._session:
            return
        path = session_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._session.to_dict()), encoding="utf-8")
            try:
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # owner-only
            except OSError:
                pass
        except OSError as exc:
            logger.warning("could not persist session: %s", exc)

    def _load(self) -> Optional[Session]:
        path = session_path()
        if not path.exists():
            return None
        try:
            return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
