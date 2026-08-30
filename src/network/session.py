"""The render station: a threaded TCP server that receives project folders,
queues them for Media Encoder, and streams the finished file back.

Every connection is treated as untrusted until it proves it knows the pairing
code, and every path in a manifest is validated before a byte is written.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core import workspace
from ..core.config import AppConfig
from ..core.jobs import JobRecord, JobSpec, JobState, JobStore
from ..core.log import get_logger
from ..core.manifest import (FileEntry, UnsafePathError, diff_manifest, hash_file,
                             safe_join, verify_received)
from ..core.protocol import (CHUNK_SIZE, Connection, Message, Msg, PROTOCOL_VERSION,
                             ProtocolError, check_auth, new_nonce)
from ..render.pipeline import RenderManager, RenderBackend, build_backend
from .discovery import StationBeacon, local_ip

logger = get_logger("net.station")

ACCEPT_BACKLOG = 8
SESSION_TIMEOUT = 300.0


class ClientSession:
    """Handles one sender connection from handshake to disconnect."""

    def __init__(self, station: "RenderStation", conn: Connection) -> None:
        self.station = station
        self.conn = conn
        self.config = station.config
        self.store = station.store
        self.authenticated = not station.config.require_pairing
        self.nonce = new_nonce()
        self.sender_name = "unknown"
        self.job_id: Optional[str] = None
        self.manifest: List[FileEntry] = []
        self._file = None
        self._file_path: Optional[Path] = None
        self._file_rel: str = ""
        self._received = 0

    # -- helpers ----------------------------------------------------------
    def _require_auth(self) -> None:
        if not self.authenticated:
            raise ProtocolError("not authenticated")

    def _job_root(self) -> Path:
        assert self.job_id
        return workspace.job_dir(self.config.workspace, self.job_id)

    def _manifest_file(self) -> Path:
        return self._job_root() / "manifest.json"

    def _load_manifest(self, job_id: str) -> List[FileEntry]:
        path = workspace.job_dir(self.config.workspace, job_id) / "manifest.json"
        if not path.is_file():
            return []
        try:
            return [FileEntry.from_dict(d)
                    for d in json.loads(path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, KeyError):
            return []

    # -- main loop --------------------------------------------------------
    def run(self) -> None:
        try:
            hello = self.conn.recv(expect=Msg.HELLO)
            self.sender_name = str(hello.get("sender_name", "unknown"))
            if int(hello.get("protocol", 0)) != PROTOCOL_VERSION:
                self.conn.error("protocol_mismatch",
                                f"station speaks protocol v{PROTOCOL_VERSION}")
                return
            self.conn.send(Msg.HELLO_OK, self.station.describe(nonce=self.nonce))

            while True:
                msg = self.conn.recv()
                if msg.type == Msg.BYE:
                    return
                if not self._dispatch(msg):
                    return
        except ProtocolError as exc:
            logger.info("session %s ended: %s", self.conn.peer, exc)
            self.conn.error("protocol_error", str(exc))
        except (OSError, socket.timeout) as exc:
            logger.debug("session %s dropped: %s", self.conn.peer, exc)
        except Exception as exc:                              # noqa: BLE001
            logger.exception("session %s crashed", self.conn.peer)
            self.conn.error("internal_error", str(exc))
        finally:
            self._close_file(discard=True)
            self.conn.close()

    def _dispatch(self, msg: Message) -> bool:
        handlers: Dict[str, Callable[[Message], bool]] = {
            Msg.AUTH: self._on_auth,
            Msg.PING: self._on_ping,
            Msg.PRESETS_REQ: self._on_presets,
            Msg.JOB_OFFER: self._on_job_offer,
            Msg.FILE_BEGIN: self._on_file_begin,
            Msg.FILE_CHUNK: self._on_file_chunk,
            Msg.FILE_END: self._on_file_end,
            Msg.TRANSFER_DONE: self._on_transfer_done,
            Msg.STATUS_REQ: self._on_status_req,
            Msg.RESULT_FETCH: self._on_result_fetch,
            Msg.RESULT_ACK: self._on_result_ack,
            Msg.CANCEL: self._on_cancel,
        }
        handler = handlers.get(msg.type)
        if handler is None:
            self.conn.error("unknown_message", f"unsupported: {msg.type}")
            return False
        return handler(msg)

    # -- handlers ---------------------------------------------------------
    def _on_auth(self, msg: Message) -> bool:
        if not self.config.require_pairing:
            self.authenticated = True
        else:
            token = str(msg.get("token", ""))
            if not check_auth(self.config.pairing_code, self.nonce, token):
                logger.warning("bad pairing code from %s", self.conn.peer)
                self.conn.error("auth_failed", "wrong pairing code")
                return False
            self.authenticated = True
        self.conn.send(Msg.AUTH_OK, {"ok": True})
        return True

    def _on_ping(self, msg: Message) -> bool:
        self.conn.send(Msg.PONG, {"time": time.time()})
        return True

    def _on_presets(self, msg: Message) -> bool:
        self._require_auth()
        from ..render import media_encoder as ame
        presets = [name for name, _ in ame.list_presets()]
        self.conn.send(Msg.PRESETS, {"presets": presets,
                                     "default": self.config.default_preset})
        return True

    def _on_job_offer(self, msg: Message) -> bool:
        self._require_auth()
        spec = JobSpec.from_dict(msg.get("spec", {}))
        entries_raw = msg.get("manifest", [])
        if not spec.job_id or not isinstance(entries_raw, list) or not entries_raw:
            self.conn.error("bad_offer", "job id and a non-empty manifest are required")
            return False

        try:
            entries = [FileEntry.from_dict(item) for item in entries_raw]
            for entry in entries:
                safe_join(workspace.project_dir(self.config.workspace, spec.job_id),
                          entry.path)
        except (UnsafePathError, KeyError, TypeError, ValueError) as exc:
            logger.warning("rejected manifest from %s: %s", self.conn.peer, exc)
            self.conn.error("unsafe_manifest", str(exc))
            return False

        needed_bytes = sum(entry.size for entry in entries)
        free = workspace.free_space_bytes(self.config.workspace)
        if free and needed_bytes * 1.5 > free:
            self.conn.error(
                "insufficient_space",
                f"station has {workspace.human_bytes(free)} free, "
                f"job needs about {workspace.human_bytes(needed_bytes * 1.5)}")
            return False

        self.job_id = spec.job_id
        self.manifest = entries
        workspace.prepare_job_dirs(self.config.workspace, spec.job_id)
        self._manifest_file().write_text(
            json.dumps([e.to_dict() for e in entries]), encoding="utf-8")

        record = self.store.get(spec.job_id)
        if record is None:
            spec.sender_name = spec.sender_name or self.sender_name
            spec.file_count = len(entries)
            spec.total_bytes = needed_bytes
            record = JobRecord(spec=spec, state=JobState.TRANSFERRING,
                               message=f"receiving from {self.sender_name}")
            self.store.add(record)
        else:
            self.store.update(spec.job_id, state=JobState.TRANSFERRING,
                              message="resuming transfer")

        project_root = workspace.project_dir(self.config.workspace, spec.job_id)
        needed = diff_manifest(entries, project_root)
        already = needed_bytes - sum(
            entry.size for entry in entries if entry.path in needed)
        self._received = already
        self.store.update(spec.job_id, bytes_received=already,
                          progress=(already / needed_bytes) if needed_bytes else 1.0)

        logger.info("job %s offered by %s: %d files, %s (%d to transfer)",
                    spec.job_id[:8], self.sender_name, len(entries),
                    workspace.human_bytes(needed_bytes), len(needed))
        self.conn.send(Msg.JOB_ACCEPT, {"job_id": spec.job_id, "need": needed,
                                        "chunk_size": CHUNK_SIZE})
        self.station.emit("job_offered", {"job_id": spec.job_id})
        return True

    def _on_file_begin(self, msg: Message) -> bool:
        self._require_auth()
        if not self.job_id:
            self.conn.error("no_job", "send a job offer first")
            return False
        rel = str(msg.get("path", ""))
        offset = int(msg.get("offset", 0))
        try:
            target = safe_join(
                workspace.project_dir(self.config.workspace, self.job_id), rel)
        except UnsafePathError as exc:
            self.conn.error("unsafe_path", str(exc))
            return False

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        mode = "r+b" if offset and partial.exists() else "wb"
        self._close_file(discard=True)
        self._file = open(partial, mode)
        if offset:
            self._file.seek(offset)
            self._file.truncate(offset)
        self._file_path = target
        self._file_rel = rel
        return True

    def _on_file_chunk(self, msg: Message) -> bool:
        if self._file is None:
            self.conn.error("no_file", "file_begin must precede file_chunk")
            return False
        self._file.write(msg.data)
        self._received += len(msg.data)
        if self.job_id:
            record = self.store.get(self.job_id)
            total = record.spec.total_bytes if record else 0
            self.store.update(self.job_id, bytes_received=self._received,
                              progress=(self._received / total) if total else 0.0,
                              message=f"receiving {self._file_rel}")
        return True

    def _on_file_end(self, msg: Message) -> bool:
        if self._file is None or self._file_path is None:
            self.conn.error("no_file", "no file in progress")
            return False
        partial = Path(str(self._file_path) + ".part")
        self._close_file()
        expected = str(msg.get("sha256", ""))
        if expected:
            actual = hash_file(partial)
            if actual != expected:
                partial.unlink(missing_ok=True)
                self.conn.error("checksum_mismatch",
                                f"{self._file_rel} arrived corrupted")
                return False
        partial.replace(self._file_path)
        self.conn.send(Msg.FILE_OK, {"path": self._file_rel})
        return True

    def _on_transfer_done(self, msg: Message) -> bool:
        self._require_auth()
        if not self.job_id:
            self.conn.error("no_job", "nothing to finish")
            return False
        entries = self.manifest or self._load_manifest(self.job_id)
        project_root = workspace.project_dir(self.config.workspace, self.job_id)
        problems = verify_received(entries, project_root)
        if problems:
            self.store.update(self.job_id, state=JobState.FAILED,
                              error="; ".join(problems[:5]),
                              message="transfer verification failed")
            self.conn.error("verify_failed", "; ".join(problems[:5]))
            return False

        self.store.update(self.job_id, state=JobState.QUEUED, progress=0.0,
                          message="queued for render")
        self.conn.send(Msg.JOB_QUEUED, {"job_id": self.job_id,
                                        "queue_length": self.station.queue_length()})
        self.station.emit("job_queued", {"job_id": self.job_id})
        logger.info("job %s queued for render", self.job_id[:8])
        return True

    def _on_status_req(self, msg: Message) -> bool:
        self._require_auth()
        job_id = str(msg.get("job_id", "")) or (self.job_id or "")
        record = self.store.get(job_id)
        if record is None:
            self.conn.error("unknown_job", f"no such job: {job_id}")
            return True
        payload = record.to_dict()
        payload["queue_length"] = self.station.queue_length()
        self.conn.send(Msg.STATUS, payload)
        return True

    def _on_result_fetch(self, msg: Message) -> bool:
        self._require_auth()
        job_id = str(msg.get("job_id", ""))
        offset = int(msg.get("offset", 0))
        record = self.store.get(job_id)
        if record is None or not record.output_path:
            self.conn.error("no_result", "no encoded file for that job yet")
            return True
        output = Path(record.output_path)
        if not output.is_file():
            self.conn.error("no_result", f"missing output file: {output}")
            return True

        size = output.stat().st_size
        self.store.update(job_id, state=JobState.RETURNING, progress=0.0,
                          message="sending result back")
        self.conn.send(Msg.RESULT_BEGIN, {"job_id": job_id, "filename": output.name,
                                          "size": size, "offset": offset,
                                          "sha256": hash_file(output)})
        sent = offset
        with open(output, "rb") as handle:
            handle.seek(offset)
            while True:
                block = handle.read(CHUNK_SIZE)
                if not block:
                    break
                self.conn.send(Msg.RESULT_CHUNK, {}, block)
                sent += len(block)
                self.store.update(job_id, progress=sent / size if size else 1.0)
        self.conn.send(Msg.RESULT_END, {"job_id": job_id, "size": size})
        logger.info("job %s: streamed %s back to %s", job_id[:8],
                    workspace.human_bytes(size), self.sender_name)
        return True

    def _on_result_ack(self, msg: Message) -> bool:
        self._require_auth()
        job_id = str(msg.get("job_id", ""))
        record = self.store.get(job_id)
        if record is None:
            self.conn.error("unknown_job", f"no such job: {job_id}")
            return True
        updated = self.store.update(job_id, state=JobState.COMPLETE, progress=1.0,
                                    message="delivered")
        # Reply before cleaning up so the sender knows the job is closed out and
        # does not race ahead of the state change.
        self.conn.send(Msg.STATUS, (updated or record).to_dict())
        self.station.emit("job_complete", {"job_id": job_id})
        if bool(msg.get("delete_remote")) or record.spec.delete_after_return:
            workspace.remove_job_dir(self.config.workspace, job_id)
            logger.info("job %s: workspace cleaned up on request", job_id[:8])
        self.station.prune_history()
        return True

    def _on_cancel(self, msg: Message) -> bool:
        self._require_auth()
        job_id = str(msg.get("job_id", ""))
        self.station.cancel_job(job_id)
        self.conn.send(Msg.CANCEL_OK, {"job_id": job_id})
        return True

    # -- file handling ----------------------------------------------------
    def _close_file(self, discard: bool = False) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass
            self._file = None
        if discard:
            self._file_path = None
            self._file_rel = ""


class RenderStation:
    """Owns the listening socket, the job store and the render worker."""

    def __init__(self, config: AppConfig,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 backend: Optional[RenderBackend] = None) -> None:
        self.config = config
        self.on_event = on_event or (lambda kind, data: None)
        workspace.ensure_workspace(config.workspace)
        self.store = JobStore(workspace.jobs_file(config.workspace))
        self.backend = backend or build_backend(config)
        self.manager = RenderManager(self.store, self.backend, config, self.emit)
        self.beacon = StationBeacon(self.describe, config.discovery_port)
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._sessions = 0
        self._lock = threading.Lock()
        self.bound_port = 0

    # -- lifecycle --------------------------------------------------------
    def start(self) -> int:
        if self._thread and self._thread.is_alive():
            return self.bound_port
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", self.config.tcp_port))
        server.listen(ACCEPT_BACKLOG)
        server.settimeout(1.0)
        self._server = server
        self.bound_port = server.getsockname()[1]

        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, name="station",
                                        daemon=True)
        self._thread.start()
        self.manager.start()
        if self.config.broadcast_presence:
            self.beacon.start()
        logger.info("render station listening on %s:%s (workspace %s)",
                    local_ip(), self.bound_port, self.config.workspace)
        self.emit("station_started", {"port": self.bound_port, "host": local_ip()})
        return self.bound_port

    def stop(self) -> None:
        self._stop.set()
        self.beacon.stop()
        self.manager.stop()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("render station stopped")
        self.emit("station_stopped", {})

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- server -----------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stop.is_set() and self._server is not None:
            try:
                client, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve_client, args=(client, addr),
                             name=f"session-{addr[0]}", daemon=True).start()

    def _serve_client(self, sock: socket.socket, addr) -> None:
        with self._lock:
            self._sessions += 1
        logger.debug("connection from %s", addr)
        try:
            ClientSession(self, Connection(sock, timeout=SESSION_TIMEOUT)).run()
        finally:
            with self._lock:
                self._sessions -= 1

    # -- station facts ----------------------------------------------------
    def describe(self, nonce: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.config.station_name,
            "port": self.bound_port or self.config.tcp_port,
            "protocol": PROTOCOL_VERSION,
            "busy": self.manager.busy,
            "queue_length": self.queue_length(),
            "requires_code": self.config.require_pairing,
            "backend": self.backend.name,
            "free_bytes": workspace.free_space_bytes(self.config.workspace),
        }
        if nonce:
            payload["nonce"] = nonce
        return payload

    def queue_length(self) -> int:
        return sum(1 for record in self.store.list()
                   if record.state in (JobState.QUEUED, JobState.RENDERING))

    def cancel_job(self, job_id: str) -> None:
        record = self.store.get(job_id)
        if record is None or record.state.terminal:
            return
        self.manager.cancel(job_id)
        self.store.update(job_id, state=JobState.CANCELLED, message="cancelled")
        self.emit("job_cancelled", {"job_id": job_id})

    def requeue(self, job_id: str) -> None:
        record = self.store.get(job_id)
        if record is None:
            return
        self.store.update(job_id, state=JobState.QUEUED, progress=0.0, error="",
                          message="re-queued")

    def prune_history(self) -> None:
        """Keep the completed-job list from growing without bound."""
        finished = [r for r in self.store.list() if r.state.terminal]
        for record in finished[self.config.keep_completed_jobs:]:
            self.store.remove(record.job_id)

    def emit(self, kind: str, data: dict) -> None:
        try:
            self.on_event(kind, data)
        except Exception:                                    # noqa: BLE001
            logger.debug("event listener failed for %s", kind)


# ---------------------------------------------------------------------------
# Compatibility helpers
#
# The prototype exposed a small ``NetworkSession`` / ``Peer`` pair at this path.
# The real work now lives in ``RenderStation`` (the receiving side) and in
# ``transfer.transfer_engine.SenderClient`` (the sending side). These thin
# wrappers keep the original names and a minimal JSON-message API available for
# quick connectivity checks and for code that imported them directly.
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass  # noqa: E402


@_dataclass
class Peer:
    """A render station a sender can reach."""
    host: str
    port: int = 49872
    name: str = ""

    @property
    def address(self):
        return (self.host, self.port)


class NetworkSession:
    """A minimal framed connection to a peer.

    This is a convenience wrapper over :class:`~..core.protocol.Connection` for
    lightweight message exchange and connectivity checks. Full job transfer uses
    :class:`~..transfer.transfer_engine.SenderClient` instead.
    """

    def __init__(self) -> None:
        self._conn: Optional[Connection] = None
        self.peer: Optional[Peer] = None

    @property
    def connected(self) -> bool:
        return self._conn is not None

    def connect(self, peer: Peer, timeout: float = 15.0) -> Peer:
        from ..core.protocol import connect as _connect
        self._conn = _connect(peer.host, peer.port, timeout=timeout)
        self.peer = peer
        return peer

    def send_json(self, obj: dict, msg_type: str = Msg.PING) -> None:
        if self._conn is None:
            raise ConnectionError("not connected")
        self._conn.send(msg_type, obj)

    def recv_json(self) -> dict:
        if self._conn is None:
            raise ConnectionError("not connected")
        return dict(self._conn.recv().payload)

    def disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self.peer = None
