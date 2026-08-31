"""The SEND-button gate.

This is the plan's critical rule (sections 7 and 56): a job must never be sent
to an offline station, and SEND is enabled only when every precondition holds.
Keeping this as one pure function makes it trivially testable and impossible for
the UI to get subtly wrong — the UI just calls ``evaluate`` and reflects it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import Station
from .config import RemoteConfig


@dataclass(frozen=True)
class SendGate:
    can_send: bool
    reason: str            # human-readable; shown when can_send is False


def evaluate_send(*, signed_in: bool, project_selected: bool,
                  project_validated: bool, station: Optional[Station],
                  config: RemoteConfig, now: Optional[float] = None) -> SendGate:
    """Return whether SEND may be enabled, with a friendly reason if not."""
    if not signed_in:
        return SendGate(False, "Sign in to send a project.")
    if not project_selected:
        return SendGate(False, "Drop or choose a Premiere project first.")
    if not project_validated:
        return SendGate(False, "Checking the project…")
    if station is None:
        return SendGate(False, "Choose a render station.")
    if not station.is_online(config.station_offline_after, now):
        return SendGate(
            False,
            "Render Station is offline. Open FileSender on the Render Station "
            "before sending.")
    return SendGate(True, "")
