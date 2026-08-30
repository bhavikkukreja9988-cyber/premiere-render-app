"""Chunking helpers.

The wire protocol streams files chunk by chunk (see ``core/protocol.py`` and
``transfer/transfer_engine.py``); this small helper keeps the MVP's
``ChunkManager`` name and ``split`` API, which the tests rely on, and adds a
matching file iterator used when reading large media off disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List

from ..core.protocol import CHUNK_SIZE


class ChunkManager:
    def split(self, data: bytes, size: int = CHUNK_SIZE) -> List[bytes]:
        """Split ``data`` into ``size``-byte chunks. Joining them restores it."""
        if size <= 0:
            raise ValueError("chunk size must be positive")
        return [data[i:i + size] for i in range(0, len(data), size)]

    def iter_file(self, path: Path, size: int = CHUNK_SIZE) -> Iterator[bytes]:
        """Yield a file's contents in chunks without loading it all into memory."""
        if size <= 0:
            raise ValueError("chunk size must be positive")
        with open(path, "rb") as handle:
            while True:
                block = handle.read(size)
                if not block:
                    return
                yield block
