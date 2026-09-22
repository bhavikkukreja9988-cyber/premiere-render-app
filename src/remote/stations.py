"""Station registration, heartbeat and presence.

A station has a stable identity that does not depend on its IP address. While
FileSender is open in station mode it heartbeats; the backend (and the Sender)
decide online/offline purely from ``last_seen``. There is no "go online"
button — opening the app is going online, closing it is going offline.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

from ..core.log import get_logger
from .config import RemoteConfig
from .models import Station
from .transport import RemoteError, RemoteTransport

logger = get_logger("remote.stations")


class StationIdTakenError(RemoteError):
    """This PC's station ID already belongs to a different account.

    Happens after the family code is changed (or an old config is kept across
    an upgrade): the ID is still registered under the previous account, which
    this account can't see, and station IDs are unique across the whole
    database. The fix is simply to give this PC a fresh ID.
    """

    user_message = "This PC needed a new station ID; it will re-register."


def _is_duplicate_key(exc: Exception) -> bool:
    text = str(exc).lower()
    return "duplicate key" in text or "23505" in text or "_pkey" in text


class StationService:
    def __init__(self, transport: RemoteTransport, config: RemoteConfig) -> None:
        self.transport = transport
        self.config = config
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._station: Optional[Station] = None

    @property
    def station(self) -> Optional[Station]:
        return self._station

    # -- registration -----------------------------------------------------
    def register(self, station_id: str, name: str, app_version: str,
                 local_ip: str = "", capabilities: Optional[dict] = None,
                 family_code: str = "", device_name: str = "") -> Station:
        """Create or update this PC's station row and mark it online now."""
        user_id = self.transport.current_user_id
        now = self.server_now()
        existing = self.transport.select("stations", {"id": station_id})
        station = Station(
            id=station_id, user_id=user_id, name=device_name or name,
            family_code=family_code, device_name=device_name or name,
            status="online", last_seen=now, app_version=app_version,
            capabilities=capabilities or {}, local_ip=local_ip,
            updated_at=now,
        )
        if existing:
            self.transport.update("stations", {"id": station_id}, {
                "name": device_name or name, "device_name": device_name or name,
                "family_code": family_code,
                "status": "online", "last_seen": now,
                "app_version": app_version, "local_ip": local_ip,
                "capabilities": station.capabilities, "updated_at": now,
            })
        else:
            try:
                self.transport.insert("stations", station.to_row())
            except RemoteError as exc:
                if _is_duplicate_key(exc):
                    raise StationIdTakenError(str(exc)) from exc
                raise
        self._station = station
        logger.info("registered station %s (%s)", station_id, name)
        return station

    # -- heartbeat --------------------------------------------------------
    def start_heartbeat(self, station_id: str) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._run_heartbeat, args=(station_id,),
            name="station-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _run_heartbeat(self, station_id: str) -> None:
        while not self._stop.is_set():
            try:
                self.beat(station_id)
            except Exception as exc:                        # noqa: BLE001
                logger.debug("heartbeat failed: %s", exc)
            self._stop.wait(self.config.heartbeat_interval)

    def beat(self, station_id: str, status: str = "online") -> None:
        now = self.server_now()
        self.transport.update("stations", {"id": station_id},
                              {"last_seen": now, "status": status,
                               "updated_at": now})

    def set_busy(self, station_id: str, busy: bool) -> None:
        self.beat(station_id, status="busy" if busy else "online")

    def go_offline(self, station_id: str) -> None:
        """Stop heartbeating and mark offline. Called when the app closes."""
        self._stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2.0)
        try:
            self.transport.update("stations", {"id": station_id},
                                  {"status": "offline",
                                   "updated_at": time.time()})
        except Exception as exc:                            # noqa: BLE001
            logger.debug("could not mark offline: %s", exc)
        logger.info("station %s offline", station_id)

    # -- discovery (sender side) -----------------------------------------
    def list_stations(self, family_code: str = "",
                      exclude_station_id: str = "") -> List[Station]:
        """Stations in this family, newest heartbeat first.

        ``exclude_station_id`` removes this PC from its own list — sending a
        job to yourself uploads to the cloud and downloads it straight back,
        which looks exactly like a failure and is never what anyone wants.
        """
        match = {"family_code": family_code} if family_code else None
        rows = self.transport.select("stations", match, order_by="name")
        stations = [Station.from_row(r) for r in rows]
        if exclude_station_id:
            stations = [s for s in stations if s.id != exclude_station_id]
        return stations

    #: How often to re-check the difference between this PC's clock and
    #: Supabase's. Clocks drift slowly; once every few minutes is plenty.
    CLOCK_CHECK_SECONDS = 300.0

    def server_now(self) -> float:
        """The current time on Supabase's clock.

        "Online" means "heartbeat within the last 45 s", so every PC must
        measure against the SAME clock. Uses a cached offset between this PC
        and Supabase, refreshed every few minutes. If the server_time()
        function isn't available (migration 007 not run yet) this falls back
        to the local clock — exactly the old behaviour.
        """
        local = time.time()
        checked = getattr(self, "_clock_checked_at", None)
        if checked is None or local - checked > self.CLOCK_CHECK_SECONDS:
            self._clock_checked_at = local
            try:
                server = float(self.transport.server_time())
                self._clock_offset = server - time.time()
                if abs(self._clock_offset) > 30:
                    logger.warning("this PC's clock is %.0f s off from the "
                                   "cloud; correcting for it", self._clock_offset)
            except Exception as exc:                        # noqa: BLE001
                logger.debug("server clock unavailable (%s); using local", exc)
        return local + getattr(self, "_clock_offset", 0.0)

    def online_stations(self, now: Optional[float] = None) -> List[Station]:
        offline_after = self.config.station_offline_after
        now = self.server_now() if now is None else now
        return [s for s in self.list_stations()
                if s.is_online(offline_after, now)]

    def get_station(self, station_id: str) -> Optional[Station]:
        rows = self.transport.select("stations", {"id": station_id})
        return Station.from_row(rows[0]) if rows else None

    def is_online(self, station_id: str, now: Optional[float] = None) -> bool:
        station = self.get_station(station_id)
        if station is None:
            return False
        now = self.server_now() if now is None else now
        return station.is_online(self.config.station_offline_after, now)
