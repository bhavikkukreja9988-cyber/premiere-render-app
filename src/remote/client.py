"""High-level remote client.

A single object the UI holds onto. It wires the services to one transport and
one config, so the UI never constructs transports or touches Supabase directly
(clean-architecture rule, plan section 68).

Use :func:`build_remote_client` to get a real Supabase-backed client, or pass a
``FakeTransport`` in tests.
"""

from __future__ import annotations

from typing import Optional

from ..core.log import get_logger
from .auth import AuthService
from .config import RemoteConfig, load_remote_config
from .jobs import RemoteJobService
from .stations import StationService
from .storage import StorageService
from .transport import RemoteTransport

logger = get_logger("remote.client")


class RemoteClient:
    def __init__(self, transport: RemoteTransport,
                 config: Optional[RemoteConfig] = None) -> None:
        self.config = config or load_remote_config()
        self.transport = transport
        self.auth = AuthService(transport, self.config)
        self.stations = StationService(transport, self.config)
        self.jobs = RemoteJobService(transport, self.config)
        self.storage = StorageService(transport, self.config)

    @property
    def signed_in(self) -> bool:
        return self.auth.signed_in

    @property
    def user_id(self) -> str:
        return self.auth.user_id


def build_remote_client(config: Optional[RemoteConfig] = None) -> RemoteClient:
    """Construct a real Supabase-backed client for the running app."""
    config = config or load_remote_config()
    from .supabase_transport import SupabaseTransport
    return RemoteClient(SupabaseTransport(config), config)
