"""Return the finished MP4 to the sender.

In this design the *sender* pulls the result (it drives every exchange, so only
the render station needs an inbound firewall rule). The station side of the
return lives in ``network/session.py``; this module is the thin, named entry
point the architecture doc references, wrapping the sender client's
``fetch_result`` so callers outside the UI can trigger a return in one call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..transfer.transfer_engine import SenderClient, TransferProgress


class ReturnManager:
    """Pulls one job's rendered file back from a station to a local folder."""

    def __init__(self, host: str, port: int, pairing_code: str = "",
                 name: str = "sender") -> None:
        self.host = host
        self.port = port
        self.pairing_code = pairing_code
        self.name = name

    def fetch(self, job_id: str, dest_dir: Path,
              delete_remote: bool = False,
              progress: Optional[Callable[[TransferProgress], None]] = None,
              cancel: Optional[Callable[[], bool]] = None) -> Path:
        """Download the encoded file, verify it, acknowledge, return its path."""
        with SenderClient(self.host, self.port, self.pairing_code,
                          self.name, timeout=120) as client:
            path = client.fetch_result(job_id, Path(dest_dir),
                                        progress=progress, cancel=cancel)
            client.ack_result(job_id, delete_remote=delete_remote)
        return path
