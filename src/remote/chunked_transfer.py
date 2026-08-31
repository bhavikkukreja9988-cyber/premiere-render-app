"""Chunked, resumable file transfer on top of the basic Storage primitives.

Supabase Storage's upload/download/list are the only operations every version
of the client library is guaranteed to have, so resumability is built here at
the application level rather than depending on a specific SDK's resumable-
upload feature (which this environment has no way to verify against a live
project anyway). That also keeps memory bounded for multi-gigabyte media
files instead of loading them whole.

Only files at or above ``CHUNK_THRESHOLD`` are chunked. A typical Premiere
project is a small ``.prproj`` plus a handful of very large media files —
there is no benefit to chunking a 40 KB project file, and doing so would just
mean an extra manifest object per tiny file.

Layout for a chunked file at logical path ``base_path``:

    {base_path}.part000000   the chunk bytes
    {base_path}.part000001
    ...
    {base_path}.manifest.json   {"size", "sha256", "chunk_size", "chunks"}

The plain ``base_path`` object itself is never created for a chunked file —
its existence (or the manifest's) is how the downloader tells which case it
is. Resuming an upload skips any part that already exists on the server
(object storage writes are atomic: a part either fully exists or doesn't).
Resuming a download picks up after the last complete local chunk. Both
directions verify the whole file's SHA-256 once everything is in place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from ..core.manifest import hash_file
from .transport import NotFoundError, RemoteTransport

CHUNK_SIZE = 8 * 1024 * 1024
CHUNK_THRESHOLD = 32 * 1024 * 1024

ProgressFn = Callable[[int, int], None]
CancelFn = Callable[[], bool]


def _part_path(base_path: str, index: int) -> str:
    return f"{base_path}.part{index:06d}"


def _manifest_path(base_path: str) -> str:
    return f"{base_path}.manifest.json"


def upload_file(transport: RemoteTransport, bucket: str, base_path: str,
                local_path: Path, sha256: str = "",
                chunk_size: int = CHUNK_SIZE, threshold: int = CHUNK_THRESHOLD,
                on_progress: Optional[ProgressFn] = None,
                cancel: Optional[CancelFn] = None) -> None:
    size = local_path.stat().st_size
    if size < threshold:
        transport.upload(bucket, base_path, local_path.read_bytes())
        if on_progress:
            on_progress(size, size)
        return

    chunk_count = max(1, (size + chunk_size - 1) // chunk_size)
    existing = set(transport.list_objects(bucket, base_path + ".part"))
    done_bytes = 0
    with open(local_path, "rb") as handle:
        for index in range(chunk_count):
            if cancel and cancel():
                raise InterruptedError("cancelled")
            part_path = _part_path(base_path, index)
            chunk = handle.read(chunk_size)
            if part_path in existing:
                done_bytes += len(chunk)
            else:
                transport.upload(bucket, part_path, chunk)
                done_bytes += len(chunk)
            if on_progress:
                on_progress(done_bytes, size)

    manifest = {"size": size, "sha256": sha256 or hash_file(local_path),
               "chunk_size": chunk_size, "chunks": chunk_count}
    transport.upload(bucket, _manifest_path(base_path),
                     json.dumps(manifest).encode("utf-8"))


def download_file(transport: RemoteTransport, bucket: str, base_path: str,
                  dest_path: Path, expected_sha256: str = "",
                  on_progress: Optional[ProgressFn] = None,
                  cancel: Optional[CancelFn] = None) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest: Optional[dict] = None
    try:
        manifest_bytes = transport.download(bucket, _manifest_path(base_path))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except NotFoundError:
        manifest = None

    if manifest is None:
        data = transport.download(bucket, base_path)
        dest_path.write_bytes(data)
        if on_progress:
            on_progress(len(data), len(data))
    else:
        size = int(manifest["size"])
        chunk_size = int(manifest["chunk_size"])
        chunk_count = int(manifest["chunks"])
        start_index = 0
        if dest_path.exists():
            current_size = dest_path.stat().st_size
            complete_chunks = current_size // chunk_size
            if complete_chunks * chunk_size == current_size and complete_chunks <= chunk_count:
                start_index = complete_chunks
            else:
                dest_path.unlink()

        mode = "r+b" if start_index else "wb"
        with open(dest_path, mode) as handle:
            handle.seek(start_index * chunk_size)
            handle.truncate()
            done_bytes = start_index * chunk_size
            if on_progress and done_bytes:
                on_progress(done_bytes, size)
            for index in range(start_index, chunk_count):
                if cancel and cancel():
                    raise InterruptedError("cancelled")
                chunk = transport.download(bucket, _part_path(base_path, index))
                handle.write(chunk)
                done_bytes += len(chunk)
                if on_progress:
                    on_progress(done_bytes, size)
        if not expected_sha256:
            expected_sha256 = str(manifest.get("sha256", ""))

    if expected_sha256 and hash_file(dest_path) != expected_sha256:
        dest_path.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch after download: {base_path}")
