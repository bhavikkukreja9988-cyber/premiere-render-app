from __future__ import annotations

from pathlib import Path


class ReturnManager:
    def send(self, file: str | Path) -> dict:
        return {"file": str(file), "status": "Returning"}