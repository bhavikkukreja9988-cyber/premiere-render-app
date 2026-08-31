"""The transport abstraction.

Every remote operation the app needs is declared here as an interface. Two
implementations exist:

  * ``SupabaseTransport`` — the real one, talking to Supabase over HTTPS.
  * ``FakeTransport``     — an in-memory stand-in used by the tests and for
                            offline development.

Business logic (auth, stations, jobs, storage services) depends only on this
interface, never on a database library. That keeps the app testable without a
network and swappable if the backend ever changes.

Errors are translated into a small set of human-meaningful exceptions so the UI
can show friendly messages (see the plan's error-message rules) instead of raw
backend jargon.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol

from .models import Session


class RemoteError(Exception):
    """Base class for all remote-layer failures."""

    user_message = "Something went wrong talking to the server."


class NotAuthenticatedError(RemoteError):
    user_message = "Please sign in again."


class AuthError(RemoteError):
    user_message = "That username or password was not accepted."


class OfflineError(RemoteError):
    user_message = ("Could not reach the server. Check your internet "
                    "connection and try again.")


class AuthorizationError(RemoteError):
    user_message = "File transfer could not be authorized. Please sign in again."


class NotFoundError(RemoteError):
    user_message = "The requested item was not found."


def friendly_message(exc: Exception) -> str:
    """A message safe to show someone who isn't a developer.

    ``RemoteError`` and its subclasses carry a curated ``user_message``
    ("Render Station is offline...") that is unrelated to whatever raw text the
    exception was constructed with. Other exceptions raised in this codebase
    are already written in plain English, so their ``str()`` is used as-is.
    Always prefer this over ``str(exc)`` anywhere the text might reach a user.
    """
    return getattr(exc, "user_message", None) or str(exc)


class Unsubscribe(Protocol):
    def __call__(self) -> None: ...


class RemoteTransport:
    """Interface for all cloud operations. See module docstring."""

    # -- auth -------------------------------------------------------------
    def sign_up(self, email: str, password: str) -> Session:
        raise NotImplementedError

    def sign_in(self, email: str, password: str) -> Session:
        raise NotImplementedError

    def restore_session(self, session: Session) -> Session:
        """Validate/refresh a stored session, returning a fresh one."""
        raise NotImplementedError

    def sign_out(self) -> None:
        raise NotImplementedError

    @property
    def current_user_id(self) -> str:
        raise NotImplementedError

    # -- database (row operations, already scoped to the signed-in user) --
    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def update(self, table: str, match: Dict[str, Any],
               changes: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def select(self, table: str, match: Optional[Dict[str, Any]] = None,
               order_by: str = "", descending: bool = False
               ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete(self, table: str, match: Dict[str, Any]) -> None:
        raise NotImplementedError

    # -- storage ----------------------------------------------------------
    def upload(self, bucket: str, object_path: str, data: bytes,
               on_progress: Optional[Callable[[int, int], None]] = None) -> str:
        raise NotImplementedError

    def download(self, bucket: str, object_path: str,
                 on_progress: Optional[Callable[[int, int], None]] = None
                 ) -> bytes:
        raise NotImplementedError

    def remove_object(self, bucket: str, object_path: str) -> None:
        raise NotImplementedError

    def list_objects(self, bucket: str, prefix: str) -> List[str]:
        raise NotImplementedError

    # -- realtime ---------------------------------------------------------
    def subscribe(self, table: str, match: Dict[str, Any],
                  callback: Callable[[str, Dict[str, Any]], None]) -> Unsubscribe:
        """Subscribe to row changes. ``callback(event_type, row)``.

        Implementations may fall back to polling if realtime is unavailable.
        Returns a callable that cancels the subscription.
        """
        raise NotImplementedError
