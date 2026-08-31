"""Real Supabase transport.

Wraps the ``supabase`` Python client behind the :class:`RemoteTransport`
interface. The library is imported lazily so the rest of the app (and the whole
test suite) works without it installed; only actually constructing a
``SupabaseTransport`` requires it.

This class is intentionally thin: it maps interface calls to Supabase client
calls and translates errors into the app's exception types. It has not been
exercised against a live Supabase project in this environment — see the change
report's "requires real testing" section.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..core.log import get_logger
from .config import RemoteConfig
from .models import Session
from .transport import (AuthError, AuthorizationError, NotAuthenticatedError,
                        NotFoundError, OfflineError, RemoteError,
                        RemoteTransport)

logger = get_logger("remote.supabase")


def _require_supabase():
    try:
        from supabase import create_client  # type: ignore
        return create_client
    except ImportError as exc:                   # pragma: no cover - env dependent
        raise RemoteError(
            "The 'supabase' package is not installed. Run: pip install supabase"
        ) from exc


class SupabaseTransport(RemoteTransport):
    def __init__(self, config: RemoteConfig) -> None:
        create_client = _require_supabase()
        self.config = config
        self._client = create_client(config.url, config.publishable_key)
        self._user_id = ""

    # -- auth -------------------------------------------------------------
    def sign_up(self, email: str, password: str) -> Session:
        try:
            res = self._client.auth.sign_up({"email": email, "password": password})
        except Exception as exc:                 # noqa: BLE001
            raise AuthError(str(exc)) from exc
        return self._session_from_auth(res)

    def sign_in(self, email: str, password: str) -> Session:
        try:
            res = self._client.auth.sign_in_with_password(
                {"email": email, "password": password})
        except Exception as exc:                 # noqa: BLE001
            raise AuthError(str(exc)) from exc
        return self._session_from_auth(res)

    def restore_session(self, session: Session) -> Session:
        try:
            self._client.auth.set_session(session.access_token,
                                          session.refresh_token)
            res = self._client.auth.refresh_session()
        except Exception as exc:                 # noqa: BLE001
            raise NotAuthenticatedError(str(exc)) from exc
        return self._session_from_auth(res)

    def sign_out(self) -> None:
        try:
            self._client.auth.sign_out()
        except Exception:                        # noqa: BLE001
            pass
        self._user_id = ""

    def _session_from_auth(self, res: Any) -> Session:
        user = getattr(res, "user", None)
        sess = getattr(res, "session", None)
        if not user or not sess:
            raise AuthError("no session returned")
        self._user_id = user.id
        return Session(
            user_id=user.id,
            username=(user.email or "").split("@")[0],
            access_token=sess.access_token,
            refresh_token=sess.refresh_token,
            expires_at=float(getattr(sess, "expires_at", 0) or 0),
        )

    @property
    def current_user_id(self) -> str:
        return self._user_id

    # -- database ---------------------------------------------------------
    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            res = self._client.table(table).insert(row).execute()
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)
        data = getattr(res, "data", None) or []
        return data[0] if data else row

    def update(self, table: str, match: Dict[str, Any],
               changes: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            query = self._client.table(table).update(changes)
            for key, value in match.items():
                query = query.eq(key, value)
            res = query.execute()
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)
        return getattr(res, "data", None) or []

    def select(self, table: str, match: Optional[Dict[str, Any]] = None,
               order_by: str = "", descending: bool = False
               ) -> List[Dict[str, Any]]:
        try:
            query = self._client.table(table).select("*")
            for key, value in (match or {}).items():
                query = query.eq(key, value)
            if order_by:
                query = query.order(order_by, desc=descending)
            res = query.execute()
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)
        return getattr(res, "data", None) or []

    def delete(self, table: str, match: Dict[str, Any]) -> None:
        try:
            query = self._client.table(table).delete()
            for key, value in match.items():
                query = query.eq(key, value)
            query.execute()
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)

    # -- storage ----------------------------------------------------------
    def upload(self, bucket: str, object_path: str, data: bytes,
               on_progress: Optional[Callable[[int, int], None]] = None) -> str:
        try:
            storage = self._client.storage.from_(bucket)
            storage.upload(object_path, data,
                           {"upsert": "true", "content-type":
                            "application/octet-stream"})
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)
        if on_progress:
            on_progress(len(data), len(data))
        return object_path

    def download(self, bucket: str, object_path: str,
                 on_progress: Optional[Callable[[int, int], None]] = None
                 ) -> bytes:
        try:
            data = self._client.storage.from_(bucket).download(object_path)
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)
        if on_progress and data is not None:
            on_progress(len(data), len(data))
        return data or b""

    def remove_object(self, bucket: str, object_path: str) -> None:
        try:
            self._client.storage.from_(bucket).remove([object_path])
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)

    def list_objects(self, bucket: str, prefix: str) -> List[str]:
        try:
            items = self._client.storage.from_(bucket).list(prefix)
        except Exception as exc:                 # noqa: BLE001
            raise self._translate(exc)
        names = []
        for item in items or []:
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                names.append(f"{prefix.rstrip('/')}/{name}")
        return names

    # -- realtime ---------------------------------------------------------
    def subscribe(self, table: str, match: Dict[str, Any],
                  callback: Callable[[str, Dict[str, Any]], None]):
        """Subscribe via Supabase Realtime.

        Realtime filters accept a single column filter; we filter the first
        match key server-side and re-check the rest in the handler.
        """
        channel_name = f"{table}-{'-'.join(f'{k}:{v}' for k, v in match.items())}"
        channel = self._client.channel(channel_name)

        def handler(payload: Dict[str, Any]) -> None:
            record = payload.get("new") or payload.get("old") or {}
            if all(record.get(k) == v for k, v in match.items()):
                callback(payload.get("eventType", "UPDATE"), record)

        filter_str = None
        if match:
            key, value = next(iter(match.items()))
            filter_str = f"{key}=eq.{value}"
        channel.on_postgres_changes(
            event="*", schema="public", table=table, filter=filter_str,
            callback=handler)
        channel.subscribe()

        def unsubscribe() -> None:
            try:
                self._client.remove_channel(channel)
            except Exception:                    # noqa: BLE001
                pass
        return unsubscribe

    # -- error translation ------------------------------------------------
    def _translate(self, exc: Exception) -> RemoteError:
        text = str(exc).lower()
        if "jwt" in text or "not authenticated" in text or "401" in text:
            return NotAuthenticatedError(str(exc))
        if "row-level security" in text or "policy" in text or "403" in text:
            return AuthorizationError(str(exc))
        if "not found" in text or "404" in text:
            return NotFoundError(str(exc))
        if "network" in text or "timeout" in text or "connection" in text:
            return OfflineError(str(exc))
        return RemoteError(str(exc))
