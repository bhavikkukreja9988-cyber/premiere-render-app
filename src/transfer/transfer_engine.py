"""Sender side: package a project folder, ship it, wait, bring the file home."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from ..core.jobs import JobSpec, JobState
from ..core.log import get_logger
from ..core.manifest import (DEFAULT_IGNORE, FileEntry, hash_file, scan_folder,
                             total_bytes)
from ..core.protocol import (CHUNK_SIZE, Connection, Msg, PROTOCOL_VERSION,
                             ProtocolError, RemoteError, auth_token, connect)

logger = get_logger("net.sender")

POLL_SECONDS = 5.0


@dataclass
class TransferProgress:
    phase: str = "idle"
    fraction: float = 0.0
    message: str = ""
    bytes_done: int = 0
    bytes_total: int = 0
    speed_bps: float = 0.0


ProgressFn = Callable[[TransferProgress], None]


class SenderClient:
    """One short-lived conversation with a render station."""

    def __init__(self, host: str, port: int, pairing_code: str = "",
                 sender_name: str = "sender", timeout: float = 60.0) -> None:
        self.host = host
        self.port = port
        self.pairing_code = pairing_code
        self.sender_name = sender_name
        self.timeout = timeout
        self.conn: Optional[Connection] = None
        self.station_info: Dict = {}

    # -- connection -------------------------------------------------------
    def open(self) -> Dict:
        self.conn = connect(self.host, self.port, timeout=15.0)
        self.conn.sock.settimeout(self.timeout)
        try:
            self.conn.send(Msg.HELLO, {"protocol": PROTOCOL_VERSION,
                                       "sender_name": self.sender_name})
            hello = self.conn.recv(expect=Msg.HELLO_OK)
            self.station_info = dict(hello.payload)

            if self.station_info.get("requires_code", True):
                nonce = str(self.station_info.get("nonce", ""))
                if not self.pairing_code:
                    raise ProtocolError("this station requires a pairing code")
                self.conn.send(Msg.AUTH,
                               {"token": auth_token(self.pairing_code, nonce)})
            else:
                self.conn.send(Msg.AUTH, {"token": ""})
            self.conn.recv(expect=Msg.AUTH_OK)
        except BaseException:
            # A failed handshake must not leave a socket dangling: __enter__
            # never returned, so no caller can close it for us.
            self.conn.close()
            self.conn = None
            raise
        return self.station_info

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.send(Msg.BYE, {})
            except OSError:
                pass
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "SenderClient":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _require(self) -> Connection:
        if self.conn is None:
            raise ProtocolError("not connected")
        return self.conn

    # -- operations -------------------------------------------------------
    def presets(self) -> List[str]:
        conn = self._require()
        conn.send(Msg.PRESETS_REQ, {})
        return list(conn.recv(expect=Msg.PRESETS).get("presets", []))

    def submit(self, spec: JobSpec, root: Path, entries: Sequence[FileEntry],
               progress: Optional[ProgressFn] = None,
               cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """Offer the job, upload whatever the station still needs, finish."""
        conn = self._require()
        grand_total = total_bytes(entries)
        spec.file_count = len(entries)
        spec.total_bytes = grand_total

        conn.send(Msg.JOB_OFFER, {"spec": spec.to_dict(),
                                  "manifest": [e.to_dict() for e in entries]})
        accept = conn.recv(expect=Msg.JOB_ACCEPT)
        needed: Dict[str, int] = dict(accept.get("need", {}))
        chunk = int(accept.get("chunk_size", CHUNK_SIZE)) or CHUNK_SIZE

        by_path = {entry.path: entry for entry in entries}
        pending = [by_path[path] for path in needed if path in by_path]
        to_send = sum(entry.size - needed[entry.path] for entry in pending)
        already = grand_total - to_send
        sent = 0
        started = time.time()

        if progress:
            progress(TransferProgress(
                "upload", already / grand_total if grand_total else 1.0,
                f"{len(pending)} of {len(entries)} files to send",
                already, grand_total))

        for entry in pending:
            if cancel and cancel():
                raise InterruptedError("cancelled")
            offset = needed.get(entry.path, 0)
            source = root / entry.path
            conn.send(Msg.FILE_BEGIN, {"path": entry.path, "offset": offset,
                                       "size": entry.size})
            digest = hashlib.sha256()
            if offset:
                # Re-hash the part we already delivered so the station's
                # end-of-file check still matches.
                with open(source, "rb") as handle:
                    remaining = offset
                    while remaining > 0:
                        block = handle.read(min(chunk, remaining))
                        if not block:
                            break
                        digest.update(block)
                        remaining -= len(block)
            with open(source, "rb") as handle:
                handle.seek(offset)
                while True:
                    if cancel and cancel():
                        raise InterruptedError("cancelled")
                    block = handle.read(chunk)
                    if not block:
                        break
                    digest.update(block)
                    conn.send(Msg.FILE_CHUNK, {}, block)
                    sent += len(block)
                    if progress:
                        elapsed = max(0.001, time.time() - started)
                        progress(TransferProgress(
                            "upload",
                            (already + sent) / grand_total if grand_total else 1.0,
                            entry.path, already + sent, grand_total,
                            sent / elapsed))
            conn.send(Msg.FILE_END, {"path": entry.path,
                                     "sha256": entry.sha256 or digest.hexdigest()})
            conn.recv(expect=Msg.FILE_OK)

        conn.send(Msg.TRANSFER_DONE, {"job_id": spec.job_id})
        queued = conn.recv(expect=Msg.JOB_QUEUED)
        if progress:
            progress(TransferProgress("queued", 1.0, "queued on the render station",
                                      grand_total, grand_total))
        return dict(queued.payload)

    def status(self, job_id: str) -> Dict:
        conn = self._require()
        conn.send(Msg.STATUS_REQ, {"job_id": job_id})
        return dict(conn.recv(expect=Msg.STATUS).payload)

    def cancel_job(self, job_id: str) -> None:
        conn = self._require()
        conn.send(Msg.CANCEL, {"job_id": job_id})
        conn.recv(expect=Msg.CANCEL_OK)

    def fetch_result(self, job_id: str, dest_dir: Path,
                     progress: Optional[ProgressFn] = None,
                     cancel: Optional[Callable[[], bool]] = None) -> Path:
        conn = self._require()
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        conn.send(Msg.RESULT_FETCH, {"job_id": job_id, "offset": 0})
        begin = conn.recv(expect=Msg.RESULT_BEGIN)
        filename = Path(str(begin.get("filename", f"{job_id}.mp4"))).name
        size = int(begin.get("size", 0))
        expected_hash = str(begin.get("sha256", ""))

        target = dest_dir / filename
        counter = 1
        while target.exists():
            target = dest_dir / f"{Path(filename).stem} ({counter}){Path(filename).suffix}"
            counter += 1
        partial = target.with_suffix(target.suffix + ".part")

        received = 0
        started = time.time()
        with open(partial, "wb") as handle:
            while True:
                msg = conn.recv()
                if msg.type == Msg.RESULT_END:
                    break
                if msg.type != Msg.RESULT_CHUNK:
                    raise ProtocolError(f"unexpected {msg.type} during result transfer")
                handle.write(msg.data)
                received += len(msg.data)
                if progress:
                    elapsed = max(0.001, time.time() - started)
                    progress(TransferProgress(
                        "download", received / size if size else 0.0,
                        filename, received, size, received / elapsed))
                if cancel and cancel():
                    raise InterruptedError("cancelled")

        if expected_hash and hash_file(partial) != expected_hash:
            partial.unlink(missing_ok=True)
            raise ProtocolError("returned file failed its checksum")
        partial.replace(target)
        return target

    def ack_result(self, job_id: str, delete_remote: bool = False) -> Dict:
        """Confirm delivery. The station replies with the closed-out record."""
        conn = self._require()
        conn.send(Msg.RESULT_ACK, {"job_id": job_id, "delete_remote": delete_remote})
        return dict(conn.recv(expect=Msg.STATUS).payload)


@dataclass
class SendRequest:
    host: str
    port: int
    pairing_code: str
    sender_name: str
    folder: Path
    spec: JobSpec
    output_dir: Path
    delete_remote: bool = False
    ignore: Sequence[str] = field(default_factory=lambda: DEFAULT_IGNORE)


class SendWorker(threading.Thread):
    """Runs one job end to end: scan, upload, wait, download, acknowledge.

    Each phase opens its own short connection, so a station reboot or a laptop
    sleeping through a two-hour render only costs a retry, not the job.
    """

    def __init__(self, request: SendRequest,
                 on_progress: Optional[ProgressFn] = None,
                 on_state: Optional[Callable[[str, dict], None]] = None) -> None:
        super().__init__(name=f"send-{request.spec.job_id[:8]}", daemon=True)
        self.request = request
        self.on_progress = on_progress or (lambda p: None)
        self.on_state = on_state or (lambda kind, data: None)
        self._cancel = threading.Event()
        self.result_path: Optional[Path] = None
        self.error: str = ""

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _client(self, timeout: float = 60.0) -> SenderClient:
        req = self.request
        return SenderClient(req.host, req.port, req.pairing_code,
                            req.sender_name, timeout=timeout)

    def run(self) -> None:
        job_id = self.request.spec.job_id
        try:
            self._report("scan", 0.0, "scanning project folder")
            entries = scan_folder(
                self.request.folder, ignore=self.request.ignore, with_hash=True,
                progress=lambda path, files, done: self._report(
                    "scan", 0.0, f"hashing {files} files ({path})", done, 0),
                cancel=self._cancel.is_set)
            if not entries:
                raise RuntimeError("that folder has no files to send")

            with self._client(timeout=120.0) as client:
                self.on_state("connected", client.station_info)
                client.submit(self.request.spec, self.request.folder, entries,
                              progress=self.on_progress,
                              cancel=self._cancel.is_set)
            self.on_state("queued", {"job_id": job_id})

            record = self._wait_for_render(job_id)
            if record is None:
                return

            self._report("download", 0.0, "fetching the rendered file")
            with self._client(timeout=120.0) as client:
                path = client.fetch_result(job_id, self.request.output_dir,
                                           progress=self.on_progress,
                                           cancel=self._cancel.is_set)
                client.ack_result(job_id, self.request.delete_remote)
            self.result_path = path
            self._report("done", 1.0, f"saved {path.name}")
            self.on_state("complete", {"job_id": job_id, "path": str(path)})
            logger.info("job %s complete -> %s", job_id[:8], path)

        except InterruptedError:
            self.error = "cancelled"
            self.on_state("cancelled", {"job_id": job_id})
        except (RemoteError, ProtocolError, OSError, RuntimeError) as exc:
            self.error = str(exc)
            self.on_state("failed", {"job_id": job_id, "error": str(exc)})
            logger.error("job %s failed: %s", job_id[:8], exc)
        except Exception as exc:                              # noqa: BLE001
            self.error = str(exc)
            self.on_state("failed", {"job_id": job_id, "error": str(exc)})
            logger.exception("job %s crashed the send worker", job_id[:8])

    def _wait_for_render(self, job_id: str) -> Optional[dict]:
        """Poll the station until the job is encoded, failed or cancelled."""
        consecutive_errors = 0
        while not self._cancel.is_set():
            try:
                with self._client(timeout=30.0) as client:
                    record = client.status(job_id)
                consecutive_errors = 0
            except (RemoteError, ProtocolError, OSError) as exc:
                consecutive_errors += 1
                self._report("wait", 0.0,
                             f"station unreachable ({exc}); retrying")
                if consecutive_errors > 40:
                    raise RuntimeError(f"lost contact with the station: {exc}")
                time.sleep(POLL_SECONDS)
                continue

            state = JobState(record.get("state", "queued"))
            fraction = float(record.get("progress", 0.0))
            message = str(record.get("message", ""))
            self.on_state("status", record)

            if state in (JobState.ENCODED, JobState.RETURNING, JobState.COMPLETE):
                return record
            if state is JobState.FAILED:
                raise RuntimeError(record.get("error") or "render failed")
            if state is JobState.CANCELLED:
                raise InterruptedError("cancelled on the station")

            queue_position = int(record.get("queue_length", 0))
            label = "rendering" if state is JobState.RENDERING else \
                f"queued ({queue_position} ahead)"
            self._report("render", fraction, message or label)
            time.sleep(POLL_SECONDS)

        raise InterruptedError("cancelled")

    def _report(self, phase: str, fraction: float, message: str,
                done: int = 0, total: int = 0) -> None:
        self.on_progress(TransferProgress(phase, fraction, message, done, total))


class TransferEngine:
    """Simple progress/status tracker for a transfer.

    ``SendWorker`` above runs the actual multi-phase job. ``TransferEngine`` is
    the lightweight status object the UI and tests use to reason about a single
    transfer's byte progress independently of the worker thread.
    """

    def __init__(self) -> None:
        self.total = 0
        self.done = 0
        self.progress = 0            # 0..100
        self.status = "Idle"

    def start(self, total: int = 0) -> None:
        self.total = max(0, int(total))
        self.done = 0
        self.progress = 0
        self.status = "Transferring"

    def update(self, done: int, total: Optional[int] = None) -> None:
        if total is not None:
            self.total = max(0, int(total))
        self.done = max(0, int(done))
        if self.total > 0:
            self.progress = min(100, int(self.done * 100 / self.total))
        else:
            self.progress = 0
        self.status = "Transferring"

    def complete(self) -> None:
        self.done = self.total
        self.progress = 100
        self.status = "Completed"

    def fail(self, reason: str = "") -> None:
        self.status = "Failed"
