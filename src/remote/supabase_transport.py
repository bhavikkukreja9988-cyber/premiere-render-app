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


class SupabaseTransport(RemoteTransport):
    def __init__(self, config: RemoteConfig) -> None:
        self.config = config
        self._client = _require_supabase()(config.url, config.publishable_key)
        self._user_id = ""

    def sign_up(self, email: str, password: str) -> Session:
        try:
            res = self._client.auth.sign_up({"email": email, "password": password})
        except Exception as exc:  # noqa: BLE001
            raise AuthError(str(exc)) from exc
        return self._session_from_auth(res)

    def sign_in(self, email: str, password: str) -> Session:
        try:
            res = self._client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthError(str(exc)) from exc
        return self._session_from_auth(res)

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

    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        self._require_session()
        try:
            res = self._client.table(table).insert(row).execute()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        data = getattr(res, "data", None) or []
        return data[0] if data else row

    def update(self, table: str, match: Dict[str, Any], changes: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._require_session()
        try:
            query = self._client.table(table).update(changes)
            for key, value in match.items():
                query = query.eq(key, value)
            res = query.execute()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return getattr(res, "data", None) or []

    def select(self, table: str, match: Optional[Dict[str, Any]] = None,
               order_by: str = "", descending: bool = False) -> List[Dict[str, Any]]:
        self._require_session()
        try:
            query = self._client.table(table).select("*")
            for key, value in (match or {}).items():
                query = query.eq(key, value)
            if order_by:
                query = query.order(order_by, desc=descending)
            res = query.execute()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return getattr(res, "data", None) or []

    def delete(self, table: str, match: Dict[str, Any]) -> None:
        self._require_session()
        try:
            query = self._client.table(table).delete()
            for key, value in match.items():
                query = query.eq(key, value)
            query.execute()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def upload(self, bucket: str, object_path: str, data: bytes,
               on_progress: Optional[Callable[[int, int], None]] = None) -> str:
        self._require_session()
        try:
            self._client.storage.from_(bucket).upload(
                object_path,
                data,
                {
                    "upsert": "true",
                    "content-type": "application/octet-stream",
                    "cache-control": "3600",
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        if on_progress:
            on_progress(len(data), len(data))
        return object_path

    def download(self, bucket: str, object_path: str,
                 on_progress: Optional[Callable[[int, int], None]] = None) -> bytes:
        self._require_session()
        try:
            data = self._client.storage.from_(bucket).download(object_path)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        payload = data or b""
        if on_progress:
            on_progress(len(payload), len(payload))
        return payload

    def remove_object(self, bucket: str, object_path: str) -> None:
        self._require_session()
        try:
            self._client.storage.from_(bucket).remove([object_path])
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

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
                try:
                    items = self._client.storage.from_(bucket).list(
                        folder,
                        {
                            "limit": STORAGE_PAGE_SIZE,
                            "offset": offset,
                            "sortBy": {"column": "name", "order": "asc"},
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    raise self._translate(exc) from exc
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
        text = str(exc).lower()
        if "jwt" in text or "not authenticated" in text or "invalid token" in text or "401" in text:
            return NotAuthenticatedError(str(exc))
        if "row-level security" in text or "permission denied" in text or "policy" in text or "403" in text:
            return AuthorizationError(str(exc))
        if "not found" in text or "404" in text or "object not found" in text:
            return NotFoundError(str(exc))
        if "network" in text or "timeout" in text or "connection" in text or "temporary failure" in text or "name or service not known" in text:
            return OfflineError(str(exc))
        return RemoteError(str(exc))
