"""Supabase-backed implementation of the RemoteTransport abstraction."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from ..core.log import get_logger
from .config import RemoteConfig
from .models import Session
from .transport import (
    AuthError,
    AuthorizationError,
    NotAuthenticatedError,
    NotFoundError,
    OfflineError,
    QuotaExceededError,
    RemoteError,
    RemoteTransport,
)

logger = get_logger("remote.supabase")
POLL_INTERVAL_SECONDS = 2.5
STORAGE_PAGE_SIZE = 1000


def _require_supabase():
    try:
        from supabase import create_client  # type: ignore
        return create_client
    except ImportError as exc:  # pragma: no cover
        raise RemoteError(
            "The FileSender cloud component is not installed. Rebuild the installer with the supplied requirements."
        ) from exc



# Text fragments that identify "couldn't reach the server" failures. Windows
# and Linux word DNS failures differently ("getaddrinfo failed" vs "Name or
# service not known"), and httpx wraps them in its own exception types, so
# both the exception type and its message are checked.
_NETWORK_MARKERS = (
    "getaddrinfo", "name or service not known", "nodename nor servname",
    "temporary failure", "network", "timeout", "timed out", "connection",
    "connecterror", "unreachable", "no route to host", "errno 11001",
    "errno 11004", "ssl", "eof occurred",
)


# Plan-limit refusals: file too big (413), storage/bandwidth over quota, or the
# 402 "fair use" restriction Supabase applies once free limits are exceeded.
_QUOTA_MARKERS = (
    "payload too large", "maximum allowed size", "entitytoolarge",
    "'statuscode': 413", "'statuscode': '413'", "'statuscode': 402",
    "'statuscode': '402'", "payment required", "quota", "usage limit",
    "exceed_storage", "exceed_egress",
)


def _is_network_error(exc: BaseException) -> bool:
    """True if the failure means "couldn't reach Supabase", not "Supabase said no"."""
    try:
        import httpx
        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
    except Exception:                                        # noqa: BLE001
        pass
    if isinstance(exc, OSError):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _NETWORK_MARKERS)

class SupabaseTransport(RemoteTransport):
    def __init__(self, config: RemoteConfig) -> None:
        self.config = config
        self._client = _require_supabase()(config.url, config.publishable_key)
        self._user_id = ""
        # Kept so an expired session can be renewed silently. These are the
        # family account's derived credentials, not anything the user typed.
        self._credentials: Optional[tuple] = None
        self._reauth_lock = threading.Lock()

    def sign_up(self, email: str, password: str) -> Session:
        try:
            res = self._client.auth.sign_up({"email": email, "password": password})
        except Exception as exc:  # noqa: BLE001
            # A network failure must NOT look like "wrong credentials":
            # the caller would then wrongly conclude the account is missing.
            if _is_network_error(exc):
                raise OfflineError(str(exc)) from exc
            raise AuthError(str(exc)) from exc
        session = self._session_from_auth(res)
        self._credentials = (email, password)
        return session

    def sign_in(self, email: str, password: str) -> Session:
        try:
            res = self._client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:  # noqa: BLE001
            if _is_network_error(exc):
                raise OfflineError(str(exc)) from exc
            raise AuthError(str(exc)) from exc
        session = self._session_from_auth(res)
        self._credentials = (email, password)
        return session

    def restore_session(self, session: Session) -> Session:
        try:
            self._client.auth.set_session(session.access_token, session.refresh_token)
            res = self._client.auth.refresh_session()
        except Exception as exc:  # noqa: BLE001
            raise NotAuthenticatedError(str(exc)) from exc
        return self._session_from_auth(res)

    def sign_out(self) -> None:
        try:
            self._client.auth.sign_out()
        except Exception:  # noqa: BLE001
            pass
        self._user_id = ""

    def _session_from_auth(self, res: Any) -> Session:
        user = getattr(res, "user", None)
        sess = getattr(res, "session", None)
        if not user or not sess:
            raise AuthError("Supabase did not return an authenticated session")
        self._user_id = str(user.id)
        return Session(
            user_id=str(user.id),
            username=(getattr(user, "email", "") or "").split("@", 1)[0],
            access_token=str(sess.access_token),
            refresh_token=str(sess.refresh_token),
            expires_at=float(getattr(sess, "expires_at", 0) or 0),
        )

    @property
    def current_user_id(self) -> str:
        return self._user_id

    def _require_session(self) -> None:
        if not self._user_id:
            raise NotAuthenticatedError("no active Supabase session")

    # -- calls with automatic recovery from an expired session --------------
    def _run(self, operation: Callable[[], Any]) -> Any:
        """Run one Supabase call; if the session has expired, renew it and
        retry once.

        Supabase sessions last about an hour. The client library refreshes
        them in the background, but if a refresh is missed (PC asleep, Wi-Fi
        down at the wrong moment) every later call fails with "JWT expired"
        and — before this — nothing ever recovered: a render station would
        silently stop working until the app was restarted.
        """
        self._require_session()
        try:
            return operation()
        except Exception as exc:                            # noqa: BLE001
            error = self._translate(exc)
            if isinstance(error, NotAuthenticatedError) and self._reauthenticate():
                try:
                    return operation()
                except Exception as retry_exc:              # noqa: BLE001
                    raise self._translate(retry_exc) from retry_exc
            raise error from exc

    def _reauthenticate(self) -> bool:
        with self._reauth_lock:
            if not self._credentials:
                return False
            email, password = self._credentials
            try:
                res = self._client.auth.sign_in_with_password(
                    {"email": email, "password": password})
                self._session_from_auth(res)
                logger.info("cloud session had expired; reconnected")
                return True
            except Exception as exc:                        # noqa: BLE001
                logger.warning("could not renew the cloud session: %s", exc)
                return False

    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        res = self._run(lambda: self._client.table(table).insert(row).execute())
        data = getattr(res, "data", None) or []
        return data[0] if data else row

    def update(self, table: str, match: Dict[str, Any], changes: Dict[str, Any]) -> List[Dict[str, Any]]:
        def op():
            query = self._client.table(table).update(changes)
            for key, value in match.items():
                query = query.eq(key, value)
            return query.execute()
        return getattr(self._run(op), "data", None) or []

    def select(self, table: str, match: Optional[Dict[str, Any]] = None,
               order_by: str = "", descending: bool = False) -> List[Dict[str, Any]]:
        def op():
            query = self._client.table(table).select("*")
            for key, value in (match or {}).items():
                query = query.eq(key, value)
            if order_by:
                query = query.order(order_by, desc=descending)
            return query.execute()
        return getattr(self._run(op), "data", None) or []

    def delete(self, table: str, match: Dict[str, Any]) -> None:
        def op():
            query = self._client.table(table).delete()
            for key, value in match.items():
                query = query.eq(key, value)
            return query.execute()
        self._run(op)

    def server_time(self) -> float:
        """Supabase's own clock (seconds since 1970), via the ``server_time``
        database function from migration 007."""
        res = self._run(lambda: self._client.rpc("server_time").execute())
        data = getattr(res, "data", None)
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            data = next(iter(data.values()), None)
        return float(data)

    def upload(self, bucket: str, object_path: str, data: bytes,
               on_progress: Optional[Callable[[int, int], None]] = None) -> str:
        self._run(lambda: self._client.storage.from_(bucket).upload(
            object_path,
            data,
            {
                "upsert": "true",
                "content-type": "application/octet-stream",
                "cache-control": "3600",
            },
        ))
        if on_progress:
            on_progress(len(data), len(data))
        return object_path

    def download(self, bucket: str, object_path: str,
                 on_progress: Optional[Callable[[int, int], None]] = None) -> bytes:
        data = self._run(lambda: self._client.storage.from_(bucket).download(object_path))
        payload = data or b""
        if on_progress:
            on_progress(len(payload), len(payload))
        return payload

    def remove_object(self, bucket: str, object_path: str) -> None:
        self._run(lambda: self._client.storage.from_(bucket).remove([object_path]))

    def list_objects(self, bucket: str, prefix: str) -> List[str]:
        """Recursively list descendant objects below a Storage folder prefix."""
        self._require_session()
        root = prefix.strip("/")
        results: List[str] = []
        stack = [root]

        while stack:
            folder = stack.pop()
            offset = 0
            while True:
                items = self._run(lambda: self._client.storage.from_(bucket).list(
                    folder,
                    {
                        "limit": STORAGE_PAGE_SIZE,
                        "offset": offset,
                        "sortBy": {"column": "name", "order": "asc"},
                    },
                ))
                items = items or []
                if not items:
                    break

                for item in items:
                    name = item.get("name") if isinstance(item, dict) else None
                    if not name:
                        continue
                    full = f"{folder}/{name}" if folder else name
                    metadata = item.get("metadata") if isinstance(item, dict) else None
                    is_folder = isinstance(item, dict) and item.get("id") in (None, "") and not metadata
                    if is_folder:
                        stack.append(full)
                    else:
                        results.append(full)

                if len(items) < STORAGE_PAGE_SIZE:
                    break
                offset += len(items)
        return sorted(results)

    def subscribe(self, table: str, match: Dict[str, Any],
                  callback: Callable[[str, Dict[str, Any]], None]):
        """Poll a scoped table for changes.

        Polling keeps the desktop client synchronous and avoids coupling the
        application to supabase-py's async Realtime API surface. The station
        also has an independent recovery sweep, so a missed poll does not lose
        a queued job.
        """
        stop = threading.Event()
        previous: Dict[str, Dict[str, Any]] = {}

        def snapshot() -> Dict[str, Dict[str, Any]]:
            rows = self.select(table, match)
            return {str(row.get("id", index)): dict(row) for index, row in enumerate(rows)}

        def run() -> None:
            nonlocal previous
            try:
                previous = snapshot()
            except RemoteError as exc:
                logger.debug("subscription initial poll failed: %s", exc)
            while not stop.wait(POLL_INTERVAL_SECONDS):
                try:
                    current = snapshot()
                    for key, row in current.items():
                        if key not in previous:
                            callback("INSERT", row)
                        elif row != previous[key]:
                            callback("UPDATE", row)
                    for key, row in previous.items():
                        if key not in current:
                            callback("DELETE", row)
                    previous = current
                except RemoteError as exc:
                    logger.debug("subscription poll failed: %s", exc)
                except Exception:  # noqa: BLE001
                    logger.exception("subscription poll crashed")

        threading.Thread(target=run, name=f"remote-poll-{table}", daemon=True).start()

        def unsubscribe() -> None:
            stop.set()

        return unsubscribe

    @staticmethod
    def _translate(exc: Exception) -> RemoteError:
        if _is_network_error(exc):
            return OfflineError(str(exc))
        text = str(exc).lower()
        if any(marker in text for marker in _QUOTA_MARKERS):
            return QuotaExceededError(str(exc))
        if "jwt" in text or "not authenticated" in text or "invalid token" in text or "401" in text:
            return NotAuthenticatedError(str(exc))
        if "row-level security" in text or "permission denied" in text or "policy" in text or "403" in text:
            return AuthorizationError(str(exc))
        if "not found" in text or "404" in text or "object not found" in text:
            return NotFoundError(str(exc))
        if "network" in text or "timeout" in text or "connection" in text or "temporary failure" in text or "name or service not known" in text:
            return OfflineError(str(exc))
        return RemoteError(str(exc))
