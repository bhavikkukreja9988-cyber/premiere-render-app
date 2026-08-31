"""In-memory fake transport for tests and offline development.

It behaves like the real Supabase transport closely enough to test all the
business logic: it enforces the same per-user row scoping that Row Level
Security enforces in production, so a test that would leak another user's jobs
fails here too. It also delivers realtime callbacks synchronously on write.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .models import Session
from .transport import (AuthError, AuthorizationError, NotAuthenticatedError,
                        NotFoundError, RemoteError, RemoteTransport)

# Tables whose rows are owned via a direct ``user_id`` column.
USER_SCOPED_TABLES = {"stations", "jobs"}
# Tables owned indirectly through their parent job.
JOB_SCOPED_TABLES = {"job_files", "job_events"}


class _Account:
    def __init__(self, email: str, password: str) -> None:
        self.user_id = uuid.uuid4().hex
        self.email = email
        self.password = password


class FakeTransport(RemoteTransport):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._accounts: Dict[str, _Account] = {}       # email -> account
        self._by_id: Dict[str, _Account] = {}          # user_id -> account
        self._tables: Dict[str, List[Dict[str, Any]]] = {
            "stations": [], "jobs": [], "job_files": [], "job_events": [],
        }
        self._buckets: Dict[str, Dict[str, bytes]] = {}
        self._session: Optional[Session] = None
        self._subs: List[Dict[str, Any]] = []
        # Toggles for tests that exercise failure handling.
        self.fail_next_upload = False
        self.offline = False

    # -- helpers ----------------------------------------------------------
    def _require_user(self) -> str:
        if not self._session or not self._session.valid:
            raise NotAuthenticatedError("no active session")
        return self._session.user_id

    def _job_owner(self, job_id: str) -> Optional[str]:
        for row in self._tables["jobs"]:
            if row.get("id") == job_id:
                return row.get("user_id")
        return None

    def _owns_row(self, table: str, row: Dict[str, Any], user_id: str) -> bool:
        if table in USER_SCOPED_TABLES:
            return row.get("user_id") == user_id
        if table in JOB_SCOPED_TABLES:
            return self._job_owner(row.get("job_id", "")) == user_id
        return True

    # -- auth -------------------------------------------------------------
    def sign_up(self, email: str, password: str) -> Session:
        with self._lock:
            if self.offline:
                from .transport import OfflineError
                raise OfflineError("offline")
            email = email.lower()
            if email in self._accounts:
                raise AuthError("username already exists")
            account = _Account(email, password)
            self._accounts[email] = account
            self._by_id[account.user_id] = account
            return self._make_session(account)

    def sign_in(self, email: str, password: str) -> Session:
        with self._lock:
            if self.offline:
                from .transport import OfflineError
                raise OfflineError("offline")
            account = self._accounts.get(email.lower())
            if account is None or account.password != password:
                raise AuthError("bad credentials")
            return self._make_session(account)

    def restore_session(self, session: Session) -> Session:
        with self._lock:
            account = self._by_id.get(session.user_id)
            if account is None or session.refresh_token != f"refresh-{account.user_id}":
                raise NotAuthenticatedError("stale session")
            return self._make_session(account)

    def sign_out(self) -> None:
        with self._lock:
            self._session = None

    def _make_session(self, account: _Account) -> Session:
        self._session = Session(
            user_id=account.user_id,
            username=account.email.split("@")[0],
            access_token=f"access-{account.user_id}-{uuid.uuid4().hex[:6]}",
            refresh_token=f"refresh-{account.user_id}",
            expires_at=time.time() + 3600,
        )
        return self._session

    @property
    def current_user_id(self) -> str:
        return self._session.user_id if self._session else ""

    # -- database ---------------------------------------------------------
    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            user_id = self._require_user()
            row = dict(row)
            if table in USER_SCOPED_TABLES:
                # RLS would force this; enforce it here too.
                row.setdefault("user_id", user_id)
                if row["user_id"] != user_id:
                    raise AuthorizationError("cannot insert for another user")
            if table in JOB_SCOPED_TABLES and self._job_owner(
                    row.get("job_id", "")) != user_id:
                raise AuthorizationError("cannot attach to another user's job")
            self._tables.setdefault(table, []).append(row)
            self._emit(table, "INSERT", row)
            return dict(row)

    def update(self, table: str, match: Dict[str, Any],
               changes: Dict[str, Any]) -> List[Dict[str, Any]]:
        with self._lock:
            user_id = self._require_user()
            updated: List[Dict[str, Any]] = []
            for row in self._tables.get(table, []):
                if all(row.get(k) == v for k, v in match.items()):
                    if not self._owns_row(table, row, user_id):
                        continue
                    row.update(changes)
                    updated.append(dict(row))
                    self._emit(table, "UPDATE", row)
            return updated

    def select(self, table: str, match: Optional[Dict[str, Any]] = None,
               order_by: str = "", descending: bool = False
               ) -> List[Dict[str, Any]]:
        with self._lock:
            user_id = self._require_user()
            match = match or {}
            rows = [
                dict(row) for row in self._tables.get(table, [])
                if all(row.get(k) == v for k, v in match.items())
                and self._owns_row(table, row, user_id)
            ]
            if order_by:
                rows.sort(key=lambda r: r.get(order_by, 0), reverse=descending)
            return rows

    def delete(self, table: str, match: Dict[str, Any]) -> None:
        with self._lock:
            user_id = self._require_user()
            kept = []
            for row in self._tables.get(table, []):
                if all(row.get(k) == v for k, v in match.items()) and \
                        self._owns_row(table, row, user_id):
                    self._emit(table, "DELETE", row)
                    continue
                kept.append(row)
            self._tables[table] = kept

    # -- storage ----------------------------------------------------------
    def upload(self, bucket: str, object_path: str, data: bytes,
               on_progress: Optional[Callable[[int, int], None]] = None) -> str:
        with self._lock:
            self._require_user()
            if self.fail_next_upload:
                self.fail_next_upload = False
                raise RemoteError("simulated upload failure")
            self._buckets.setdefault(bucket, {})[object_path] = bytes(data)
        if on_progress:
            on_progress(len(data), len(data))
        return object_path

    def download(self, bucket: str, object_path: str,
                 on_progress: Optional[Callable[[int, int], None]] = None
                 ) -> bytes:
        with self._lock:
            self._require_user()
            store = self._buckets.get(bucket, {})
            if object_path not in store:
                raise NotFoundError(f"no such object: {object_path}")
            data = store[object_path]
        if on_progress:
            on_progress(len(data), len(data))
        return data

    def remove_object(self, bucket: str, object_path: str) -> None:
        with self._lock:
            self._require_user()
            self._buckets.get(bucket, {}).pop(object_path, None)

    def list_objects(self, bucket: str, prefix: str) -> List[str]:
        with self._lock:
            self._require_user()
            return sorted(k for k in self._buckets.get(bucket, {})
                          if k.startswith(prefix))

    # -- realtime ---------------------------------------------------------
    def subscribe(self, table: str, match: Dict[str, Any],
                  callback: Callable[[str, Dict[str, Any]], None]):
        entry = {"table": table, "match": match, "callback": callback}
        with self._lock:
            self._subs.append(entry)

        def unsubscribe() -> None:
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)
        return unsubscribe

    def _emit(self, table: str, event_type: str, row: Dict[str, Any]) -> None:
        for sub in list(self._subs):
            if sub["table"] != table:
                continue
            if all(row.get(k) == v for k, v in sub["match"].items()):
                try:
                    sub["callback"](event_type, dict(row))
                except Exception:
                    pass
