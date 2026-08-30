"""PRAP/2 — Premiere Render App Protocol, version 2.

Framing
-------
Every message on the wire is::

    [4 bytes big-endian header length][UTF-8 JSON header][optional raw payload]

The JSON header always contains::

    {"t": "<message type>", "p": {...}, "n": <payload byte count>}

``n`` is 0 for control-only messages. Binary payloads (file chunks) are never
JSON-encoded, so large media streams cost nothing in encoding overhead.

The protocol is deliberately synchronous and request/response shaped: the
sender drives every exchange, which means the render station never needs an
inbound connection back to the sender. That keeps the app working on networks
where only one machine can accept inbound TCP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

PROTOCOL_VERSION = 2
DEFAULT_TCP_PORT = 49872
DEFAULT_DISCOVERY_PORT = 49873

CHUNK_SIZE = 1024 * 1024          # 1 MiB streaming chunk
MAX_HEADER_BYTES = 1024 * 1024    # sanity limit for a JSON header
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
SOCKET_TIMEOUT = 60.0


class ProtocolError(Exception):
    """Raised on malformed frames, unexpected message types or auth failure."""


class RemoteError(Exception):
    """Raised when the peer replies with an ERROR message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Msg:
    """Message type constants."""

    HELLO = "hello"
    HELLO_OK = "hello_ok"
    AUTH = "auth"
    AUTH_OK = "auth_ok"

    JOB_OFFER = "job_offer"
    JOB_ACCEPT = "job_accept"

    FILE_BEGIN = "file_begin"
    FILE_CHUNK = "file_chunk"
    FILE_END = "file_end"
    FILE_OK = "file_ok"

    TRANSFER_DONE = "transfer_done"
    JOB_QUEUED = "job_queued"

    STATUS_REQ = "status_req"
    STATUS = "status"
    CANCEL = "cancel"
    CANCEL_OK = "cancel_ok"

    RESULT_FETCH = "result_fetch"
    RESULT_BEGIN = "result_begin"
    RESULT_CHUNK = "result_chunk"
    RESULT_END = "result_end"
    RESULT_ACK = "result_ack"

    PRESETS_REQ = "presets_req"
    PRESETS = "presets"

    PING = "ping"
    PONG = "pong"
    BYE = "bye"
    ERROR = "error"


@dataclass
class Message:
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    data: bytes = b""

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    """Read exactly ``count`` bytes or raise."""
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(min(65536, count - len(buf)))
        if not chunk:
            raise ProtocolError("connection closed by peer")
        buf.extend(chunk)
    return bytes(buf)


class Connection:
    """A framed message channel over a TCP socket."""

    def __init__(self, sock: socket.socket, timeout: float = SOCKET_TIMEOUT) -> None:
        self.sock = sock
        self.sock.settimeout(timeout)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.peer = self._peer_name()

    def _peer_name(self) -> str:
        try:
            name = self.sock.getpeername()
        except OSError:
            return "<disconnected>"
        if isinstance(name, tuple) and len(name) >= 2:
            return f"{name[0]}:{name[1]}"
        return str(name) or "<local>"

    # -- send / receive ---------------------------------------------------
    def send(self, msg_type: str, payload: Optional[Dict[str, Any]] = None,
             data: bytes = b"") -> None:
        header = json.dumps(
            {"t": msg_type, "p": payload or {}, "n": len(data)},
            separators=(",", ":"),
        ).encode("utf-8")
        if len(header) > MAX_HEADER_BYTES:
            raise ProtocolError("header too large")
        self.sock.sendall(struct.pack(">I", len(header)) + header)
        if data:
            self.sock.sendall(data)

    def recv(self, expect: Optional[str] = None) -> Message:
        raw_len = _recv_exact(self.sock, 4)
        (header_len,) = struct.unpack(">I", raw_len)
        if header_len == 0 or header_len > MAX_HEADER_BYTES:
            raise ProtocolError(f"bad header length {header_len}")
        try:
            header = json.loads(_recv_exact(self.sock, header_len).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProtocolError(f"bad header: {exc}") from exc

        msg_type = header.get("t")
        if not isinstance(msg_type, str):
            raise ProtocolError("header missing message type")
        payload = header.get("p") or {}
        if not isinstance(payload, dict):
            raise ProtocolError("header payload must be an object")
        n = int(header.get("n") or 0)
        if n < 0 or n > MAX_PAYLOAD_BYTES:
            raise ProtocolError(f"bad payload length {n}")
        data = _recv_exact(self.sock, n) if n else b""

        msg = Message(msg_type, payload, data)
        if msg_type == Msg.ERROR:
            raise RemoteError(str(payload.get("code", "error")),
                              str(payload.get("message", "")))
        if expect is not None and msg_type != expect:
            raise ProtocolError(f"expected {expect!r}, got {msg_type!r}")
        return msg

    def error(self, code: str, message: str) -> None:
        try:
            self.send(Msg.ERROR, {"code": code, "message": message})
        except OSError:
            pass

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def connect(host: str, port: int = DEFAULT_TCP_PORT,
            timeout: float = 15.0) -> Connection:
    sock = socket.create_connection((host, port), timeout=timeout)
    return Connection(sock)


# -- pairing ---------------------------------------------------------------
def new_nonce() -> str:
    return os.urandom(16).hex()


def auth_token(pairing_code: str, nonce: str) -> str:
    """HMAC-SHA256 of the nonce keyed by the station's pairing code.

    The code itself never crosses the network, so a passive listener on the
    LAN cannot replay a job submission against the station.
    """
    return hmac.new(pairing_code.strip().encode("utf-8"),
                    nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def check_auth(pairing_code: str, nonce: str, token: str) -> bool:
    return hmac.compare_digest(auth_token(pairing_code, nonce), str(token or ""))
