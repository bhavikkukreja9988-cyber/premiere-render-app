from __future__ import annotations

from collections.abc import Iterator


class ChunkManager:
    DEFAULT_SIZE = 4 * 1024 * 1024

    def split(self, data: bytes, size: int = DEFAULT_SIZE) -> list[bytes]:
        if size <= 0:
            raise ValueError("Chunk size must be positive")
        return list(self.iter_chunks(data, size))

    def iter_chunks(self, data: bytes, size: int = DEFAULT_SIZE) -> Iterator[bytes]:
        if size <= 0:
            raise ValueError("Chunk size must be positive")
        for start in range(0, len(data), size):
            yield data[start : start + size]