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
from .transport import RemoteTransport

logger = get_logger("remote.stations")


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
                 local_ip: str = "", capabilities: Optional[dict] = None) -> Station:
        """Create or update this PC's station row and mark it online now."""
        user_id = self.transport.current_user_id
        now = time.time()
        existing = self.transport.select("stations", {"id": station_id})
        station = Station(
            id=station_id, user_id=user_id, name=name, status="online",
            last_seen=now, app_version=app_version,
            capabilities=capabilities or {}, local_ip=local_ip,
            updated_at=now,
        )
        if existing:
            self.transport.update("stations", {"id": station_id}, {
                "name": name, "status": "online", "last_seen": now,
                "app_version": app_version, "local_ip": local_ip,
                "capabilities": station.capabilities, "updated_at": now,
            })
        else:
            self.transport.insert("stations", station.to_row())
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
        self.transport.update("stations", {"id": station_id},
                              {"last_seen": time.time(), "status": status,
                               "updated_at": time.time()})

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
    def list_stations(self) -> List[Station]:
        rows = self.transport.select("stations", order_by="name")
        return [Station.from_row(r) for r in rows]

    def online_stations(self, now: Optional[float] = None) -> List[Station]:
        offline_after = self.config.station_offline_after
        return [s for s in self.list_stations()
                if s.is_online(offline_after, now)]

    def get_station(self, station_id: str) -> Optional[Station]:
        rows = self.transport.select("stations", {"id": station_id})
        return Station.from_row(rows[0]) if rows else None

    def is_online(self, station_id: str, now: Optional[float] = None) -> bool:
        station = self.get_station(station_id)
        if station is None:
            return False
        return station.is_online(self.config.station_offline_after, now)
