"""Small network utilities that don't belong to any one service.

The legacy LAN transport (src/network/) is no longer part of the production
runtime, but one tiny piece of it — figuring out this machine's LAN address —
is still useful as *informational* text shown to the station operator (never
used as a connection mechanism; the cloud transport doesn't need it).
"""

from __future__ import annotations

import socket


def local_ip() -> str:
    """Best guess at this machine's LAN address.

    No actual network traffic is sent — connecting a UDP socket just makes
    the OS pick a local address for that route, which is all we need.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
