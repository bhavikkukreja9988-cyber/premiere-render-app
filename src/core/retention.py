"""Receiver-side retention and cleanup.

The render station may auto-delete *received* projects once a job is safely
finished and older than the configured window. This never touches the sender's
original project — it only removes data the station itself received.

Safety is the whole point of this module. It will only ever delete a job that:

  * is in the COMPLETE state (the file was returned and acknowledged), and
  * has been complete for longer than the retention window, and
  * is not the job currently rendering.

It will never delete a job that is transferring, queued, rendering, returning,
failed, cancelled, partially received, or otherwise not cleanly complete — those
may still be needed or under inspection.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from .jobs import JobRecord, JobState, JobStore
from .log import get_logger

logger = get_logger("core.retention")

#: States that are safe to auto-delete. Deliberately only one.
DELETABLE_STATES = (JobState.COMPLETE,)

CHECK_INTERVAL_SECONDS = 300.0        # re-evaluate every 5 minutes


def eligible_for_deletion(record: JobRecord, retention_days: int,
                          now: Optional[float] = None,
                          protected_job_id: str = "") -> bool:
    """Decide whether one job may be auto-deleted.

    ``retention_days <= 0`` means "never delete", so this always returns False.
    """
    if retention_days <= 0:
        return False
    if record.job_id == protected_job_id:
        return False
    if record.state not in DELETABLE_STATES:
        return False
    reference = record.completed_at or record.updated_at
    if not reference:
        return False
    now = time.time() if now is None else now
    age_days = (now - reference) / 86400.0
    return age_days >= retention_days


class RetentionManager:
    """Background sweeper that enforces the retention policy on the station."""

    def __init__(self, store: JobStore, workspace_dir: Path,
                 retention_days_provider: Callable[[], int],
                 remove_job_dir: Callable[[str], None],
                 busy_job_provider: Callable[[], Optional[str]],
                 on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        self.store = store
        self.workspace_dir = Path(workspace_dir)
        self._retention_days = retention_days_provider
        self._remove_job_dir = remove_job_dir
        self._busy_job = busy_job_provider
        self.on_event = on_event or (lambda kind, data: None)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="retention",
                                        daemon=True)
        self._thread.start()
        logger.info("retention manager started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def sweep(self) -> List[str]:
        """Delete every eligible job now. Returns the labels removed."""
        retention_days = self._retention_days()
        if retention_days <= 0:
            return []
        protected = self._busy_job() or ""
        removed: List[str] = []
        for record in self.store.list():
            if eligible_for_deletion(record, retention_days,
                                     protected_job_id=protected):
                label = record.display_label
                try:
                    self._remove_job_dir(record.job_id)
                    self.store.remove(record.job_id)
                    removed.append(label)
                    logger.info("retention: removed %s (%d-day policy)",
                                label, retention_days)
                except OSError as exc:
                    logger.warning("retention: could not remove %s: %s",
                                   label, exc)
        if removed:
            self.on_event("retention_cleanup", {"removed": removed})
        return removed

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep()
            except Exception:                       # noqa: BLE001 - never die
                logger.exception("retention sweep failed")
            self._stop.wait(CHECK_INTERVAL_SECONDS)
