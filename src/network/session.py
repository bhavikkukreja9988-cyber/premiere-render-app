from __future__ import annotations

import json
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAGIC = b"PRA1"
HEADER_SIZE = 8
MAX_JSON = 1024 * 1024
DEFAULT_PORT = 49872


@dataclass(frozen=True)
class Peer:
    host: str
    port: int = DEFAULT_PORT
    name: str = "Render Station"


class NetworkSession:
    def __init__(self, peer: Peer | None = None, sock: socket.socket | None = None) -> None:
        self.peer = peer
        self.socket = sock
        self.connected = sock is not None

    def connect(self, device: Peer | str, port: int = DEFAULT_PORT, timeout: float = 5.0) -> Peer:
        peer = device if isinstance(device, Peer) else Peer(str(device), port)
        sock = socket.create_connection((peer.host, peer.port), timeout=timeout)
        sock.settimeout(None)
        self.socket = sock
        self.peer = peer
        self.connected = True
        return peer

    def disconnect(self) -> None:
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()
        self.socket = None
        self.connected = False

    def send_json(self, payload: dict) -> None:
        self._require_socket()
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_JSON:
            raise ValueError("Message is too large")
        self.socket.sendall(MAGIC + struct.pack(">I", len(raw)) + raw)

    def recv_json(self) -> dict:
        self._require_socket()
        magic = self._read_exact(len(MAGIC))
        if magic != MAGIC:
            raise ConnectionError("Invalid protocol header")
        length = struct.unpack(">I", self._read_exact(4))[0]
        if length > MAX_JSON:
            raise ValueError("Message is too large")
        return json.loads(self._read_exact(length).decode("utf-8"))

    def send_file(self, path: str | Path, on_progress: Callable[[int, int], None] | None = None, chunk_size: int = 1024 * 1024) -> None:
        self._require_socket()
        path = Path(path)
        total = path.stat().st_size
        self.send_json({"type": "file-start", "name": path.name, "size": total})
        sent = 0
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                self.socket.sendall(struct.pack(">I", len(chunk)) + chunk)
                sent += len(chunk)
                if on_progress:
                    on_progress(sent, total)
        self.send_json({"type": "file-end", "name": path.name})

    def receive_file(self, destination: str | Path, header: dict, on_progress: Callable[[int, int], None] | None = None) -> Path:
        self._require_socket()
        name = Path(str(header["name"])).name
        total = int(header["size"])
        target_dir = Path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        received = 0
        with target.open("wb") as handle:
            while received < total:
                length = struct.unpack(">I", self._read_exact(4))[0]
                if length <= 0 or received + length > total:
                    raise ConnectionError("Invalid file chunk length")
                data = self._read_exact(length)
                handle.write(data)
                received += length
                if on_progress:
                    on_progress(received, total)
        return target

    def _require_socket(self) -> None:
        if not self.socket:
            raise ConnectionError("Not connected")

    def _read_exact(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self.socket.recv(remaining)
            if not chunk:
                raise ConnectionError("Connection closed unexpectedly")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    hostname = socket.gethostname()
    for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
        addresses.add(info[4][0])
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addresses.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in addresses if not a.startswith("127."))