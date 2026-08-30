"""LAN discovery over UDP broadcast.

The station shouts a small JSON beacon every couple of seconds; senders listen
and build a live list. Typing an IP by hand still works and is the fallback
whenever broadcast is blocked (some corporate switches and most VPNs drop it).
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from ..core.log import get_logger
from ..core.protocol import DEFAULT_DISCOVERY_PORT, PROTOCOL_VERSION

logger = get_logger("net.discovery")

BEACON_INTERVAL = 2.0
STATION_TTL = 8.0
MAGIC = "premiere-render-app"


@dataclass
class StationInfo:
    name: str
    host: str
    port: int
    protocol: int = PROTOCOL_VERSION
    busy: bool = False
    queue_length: int = 0
    requires_code: bool = True
    last_seen: float = 0.0

    @property
    def label(self) -> str:
        state = "busy" if self.busy else "idle"
        lock = " 🔒" if self.requires_code else ""
        return f"{self.name} — {self.host}:{self.port} ({state}){lock}"


def local_ip() -> str:
    """Best guess at this machine's LAN address (no traffic is actually sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class StationBeacon:
    """Broadcasts station presence while the station is listening."""

    def __init__(self, status_provider: Callable[[], dict],
                 port: int = DEFAULT_DISCOVERY_PORT) -> None:
        self.status_provider = status_provider
        self.port = port
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="beacon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while not self._stop.is_set():
                try:
                    payload = dict(self.status_provider())
                    payload["magic"] = MAGIC
                    payload["protocol"] = PROTOCOL_VERSION
                    packet = json.dumps(payload).encode("utf-8")
                    sock.sendto(packet, ("255.255.255.255", self.port))
                except OSError as exc:
                    logger.debug("beacon send failed: %s", exc)
                except Exception as exc:                    # noqa: BLE001
                    logger.debug("beacon error: %s", exc)
                self._stop.wait(BEACON_INTERVAL)
        finally:
            sock.close()


class StationDiscovery:
    """Listens for beacons and keeps a fresh station list."""

    def __init__(self, port: int = DEFAULT_DISCOVERY_PORT,
                 on_change: Optional[Callable[[List[StationInfo]], None]] = None) -> None:
        self.port = port
        self.on_change = on_change
        self._stations: Dict[str, StationInfo] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="discovery",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def stations(self) -> List[StationInfo]:
        cutoff = time.time() - STATION_TTL
        with self._lock:
            for key in [k for k, s in self._stations.items() if s.last_seen < cutoff]:
                self._stations.pop(key, None)
            return sorted(self._stations.values(), key=lambda s: s.name.lower())

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.port))
        except OSError as exc:
            logger.warning("cannot listen for stations on %s: %s", self.port, exc)
            sock.close()
            return
        sock.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    payload = json.loads(data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if payload.get("magic") != MAGIC:
                    continue
                info = StationInfo(
                    name=str(payload.get("name") or addr[0]),
                    host=addr[0],
                    port=int(payload.get("port") or 0),
                    protocol=int(payload.get("protocol") or 0),
                    busy=bool(payload.get("busy")),
                    queue_length=int(payload.get("queue_length") or 0),
                    requires_code=bool(payload.get("requires_code", True)),
                    last_seen=time.time(),
                )
                if not info.port:
                    continue
                with self._lock:
                    self._stations[f"{info.host}:{info.port}"] = info
                if self.on_change:
                    try:
                        self.on_change(self.stations())
                    except Exception:                        # noqa: BLE001
                        pass
        finally:
            sock.close()
