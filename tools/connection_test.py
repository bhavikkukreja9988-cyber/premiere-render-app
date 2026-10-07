"""FileSender connection test.

Answers one question before FileSender 4.0 is built:

    Can these two PCs, on their real networks, connect DIRECTLY?

Run it on both PCs at the same time. It does two things:

  1. A network check (automatic, about 10 seconds): asks public "STUN"
     servers what this PC looks like from the internet, and whether the
     router keeps the same outside address for different destinations
     (needed for a direct connection). Also checks for IPv6.

  2. A real direct-connection test (optional): each PC shows a code. Send
     your code to the other PC (WhatsApp, email - anything), paste theirs,
     and both PCs try to reach each other directly for up to 2 minutes.

The result is printed and saved to a text file to send back.

Nothing is installed, nothing is changed, no files are shared. Only tiny
test messages are sent. Standard library only, so it can be packaged as a
single .exe (see scripts/build_connection_test.bat).
"""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import subprocess
import secrets
import select
import socket
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

VERSION = "1.0"

# Public STUN servers. Two different providers so the "same outside address
# for different destinations" check compares genuinely different servers.
STUN_SERVERS: List[Tuple[str, int]] = [
    ("stun.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun1.l.google.com", 19302),
]

MAGIC_COOKIE = 0x2112A442
BINDING_REQUEST = 0x0001
BINDING_SUCCESS = 0x0101
ATTR_MAPPED_ADDRESS = 0x0001
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_XOR_MAPPED_ADDRESS_ALT = 0x8020

CODE_PREFIX = "FS1-"
PROBE = b"FSPROBE1 "
ACK = b"FSACK1 "

Addr = Tuple[str, int]


# ---------------------------------------------------------------------------
# STUN (RFC 5389) - just enough to ask "what's my outside address?"
# ---------------------------------------------------------------------------
def build_binding_request(transaction_id: bytes) -> bytes:
    return struct.pack("!HHI12s", BINDING_REQUEST, 0, MAGIC_COOKIE, transaction_id)


def parse_binding_response(data: bytes, transaction_id: bytes) -> Optional[Addr]:
    """Return the (ip, port) the STUN server saw, or None if not a match."""
    if len(data) < 20:
        return None
    msg_type, msg_len, cookie, txid = struct.unpack("!HHI12s", data[:20])
    if msg_type != BINDING_SUCCESS or cookie != MAGIC_COOKIE or txid != transaction_id:
        return None
    pos, end = 20, min(20 + msg_len, len(data))
    fallback: Optional[Addr] = None
    cookie_bytes = struct.pack("!I", MAGIC_COOKIE)
    while pos + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[pos:pos + 4])
        value = data[pos + 4:pos + 4 + attr_len]
        if len(value) >= 8:
            family = value[1]
            if attr_type in (ATTR_XOR_MAPPED_ADDRESS, ATTR_XOR_MAPPED_ADDRESS_ALT):
                port = struct.unpack("!H", value[2:4])[0] ^ (MAGIC_COOKIE >> 16)
                if family == 0x01 and len(value) >= 8:
                    raw = bytes(b ^ k for b, k in zip(value[4:8], cookie_bytes))
                    return socket.inet_ntop(socket.AF_INET, raw), port
                if family == 0x02 and len(value) >= 20:
                    key = cookie_bytes + transaction_id
                    raw = bytes(b ^ k for b, k in zip(value[4:20], key))
                    return socket.inet_ntop(socket.AF_INET6, raw), port
            elif attr_type == ATTR_MAPPED_ADDRESS:
                port = struct.unpack("!H", value[2:4])[0]
                if family == 0x01:
                    fallback = (socket.inet_ntop(socket.AF_INET, value[4:8]), port)
                elif family == 0x02 and len(value) >= 20:
                    fallback = (socket.inet_ntop(socket.AF_INET6, value[4:20]), port)
        pos += 4 + attr_len + ((4 - attr_len % 4) % 4)
    return fallback


def resolve(host: str, port: int, family: int) -> List[Addr]:
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_DGRAM)
    except OSError:
        return []
    seen, out = set(), []
    for info in infos:
        addr = info[4][:2]
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def stun_query(sock: socket.socket, server: Addr, timeout: float = 1.5,
               attempts: int = 3) -> Optional[Addr]:
    """Ask one STUN server what this socket looks like from outside."""
    for _ in range(attempts):
        txid = secrets.token_bytes(12)
        try:
            sock.sendto(build_binding_request(txid), server)
        except OSError:
            return None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([sock], [], [], remaining)
            if not ready:
                break
            try:
                data, _src = sock.recvfrom(2048)
            except OSError:
                break
            mapped = parse_binding_response(data, txid)
            if mapped:
                return mapped
    return None


# ---------------------------------------------------------------------------
# Network check
# ---------------------------------------------------------------------------
def primary_local_ip(family: int) -> Optional[str]:
    """This PC's own address on its network (no traffic is sent)."""
    target = ("8.8.8.8", 80) if family == socket.AF_INET else ("2001:4860:4860::8888", 80)
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect(target)
            return s.getsockname()[0]
    except OSError:
        return None


def check_family(family: int, servers: Sequence[Addr],
                 bind_host: Optional[str] = None) -> Dict:
    """Outside address and mapping behaviour for IPv4 or IPv6.

    ``bind_host`` is only for tests: binding to loopback avoids a Windows
    Firewall pop-up in the middle of an automated test run."""
    label = "IPv4" if family == socket.AF_INET else "IPv6"
    result: Dict = {"family": label, "available": False, "mappings": [],
                    "local_ip": primary_local_ip(family)}
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
        default_host = "0.0.0.0" if family == socket.AF_INET else "::"
        sock.bind((bind_host or default_host, 0))
    except OSError as exc:
        result["error"] = f"can't open a {label} socket ({exc})"
        return result

    try:
        used_ips = set()
        for host, port in servers:
            for addr in resolve(host, port, family):
                if addr[0] in used_ips:
                    continue
                mapped = stun_query(sock, addr)
                if mapped:
                    used_ips.add(addr[0])
                    result["mappings"].append({"server": f"{host}", "outside": list(mapped)})
                break
            if len(result["mappings"]) >= 2:
                break
    finally:
        sock.close()

    maps = result["mappings"]
    result["available"] = bool(maps)
    if len(maps) >= 2:
        ports = {tuple(m["outside"]) for m in maps}
        result["same_outside_address"] = len(ports) == 1
    if maps and result["local_ip"]:
        result["behind_router"] = maps[0]["outside"][0] != result["local_ip"]
    return result


def verdict(v4: Dict, v6: Dict) -> Tuple[str, str]:
    """(short verdict, plain-English explanation) for one PC."""
    if v6.get("available") and v6.get("behind_router") is False:
        return ("GOOD", "This PC has a public IPv6 address - the easiest case "
                        "for a direct connection.")
    if v4.get("available"):
        same = v4.get("same_outside_address")
        if same is True:
            return ("GOOD", "Your router keeps the same outside address for "
                            "different destinations, which is what a direct "
                            "connection needs.")
        if same is False:
            return ("HARD", "Your router (or internet provider) changes the "
                            "outside address for every destination. A direct "
                            "connection may still work if the OTHER PC's "
                            "result is GOOD, but it's unlikely if both are "
                            "HARD. The Supabase fallback would be used.")
        return ("UNSURE", "Only one test server answered, so the router's "
                          "behaviour couldn't be measured.")
    return ("NO INTERNET", "No test server answered. Check the internet "
                           "connection, or a firewall may be blocking UDP.")


# ---------------------------------------------------------------------------
# Connection codes
# ---------------------------------------------------------------------------
def make_code(name: str, peer_id: str, candidates: List[Addr]) -> str:
    payload = {"n": name[:40], "i": peer_id, "c": [[h, p] for h, p in candidates]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_body(body: str) -> Optional[Dict]:
    if len(body) % 4 == 1:                   # never valid base64
        return None
    try:
        raw = base64.urlsafe_b64decode((body + "=" * (-len(body) % 4)).encode())
        payload = json.loads(raw)
        candidates = [(str(h), int(p)) for h, p in payload["c"]]
        return {"name": str(payload.get("n", "other PC")),
                "id": str(payload["i"]), "candidates": candidates}
    except Exception:                         # noqa: BLE001
        return None


def read_code(code: str) -> Dict:
    """Read a code pasted from a chat app.

    Tolerates line breaks inside the code and text before or after it.
    Spaces are removed first (chat apps wrap long lines), which can glue a
    following word onto the code - and "-" is a legal code character - so
    the longest reading that decodes to a valid code wins.
    """
    compact = "".join(code.split())
    found = re.search(re.escape(CODE_PREFIX) + r"[A-Za-z0-9_\-]+", compact)
    if not found:
        raise ValueError("that doesn't look like a FileSender connection code")
    body = found.group(0)[len(CODE_PREFIX):]
    for length in range(len(body), 7, -1):
        peer = _decode_body(body[:length])
        if peer is not None:
            return peer
    raise ValueError("the code is incomplete or damaged - copy it again")


# ---------------------------------------------------------------------------
# Direct connection (UDP hole punching)
# ---------------------------------------------------------------------------
class Endpoint:
    """This PC's sockets for the test, kept open (and kept alive) until the
    other PC's code has been pasted in."""

    def __init__(self, servers: Sequence[Addr] = STUN_SERVERS,
                 bind_host_v4: str = "0.0.0.0", use_v6: bool = True) -> None:
        self.peer_id = secrets.token_hex(4)
        self.sockets: Dict[int, socket.socket] = {}
        self.candidates: List[Addr] = []
        self.servers = list(servers)
        self._stun_targets: List[Tuple[socket.socket, Addr]] = []
        self._stop = threading.Event()

        families = [(socket.AF_INET, (bind_host_v4, 0))]
        if use_v6:
            families.insert(0, (socket.AF_INET6, ("::", 0)))
        for family, bind_addr in families:
            try:
                sock = socket.socket(family, socket.SOCK_DGRAM)
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.bind(bind_addr)
            except OSError:
                continue
            self.sockets[family] = sock
            outside = None
            for host, port in self.servers:
                for addr in resolve(host, port, family)[:1]:
                    outside = stun_query(sock, addr)
                    if outside:
                        self._stun_targets.append((sock, addr))
                        break
                if outside:
                    break
            local_port = sock.getsockname()[1]
            if outside:
                self.candidates.append(outside)
            local_ip = primary_local_ip(family)
            if local_ip and (local_ip, local_port) not in self.candidates:
                self.candidates.append((local_ip, local_port))
            if family == socket.AF_INET and bind_host_v4 != "0.0.0.0":
                self.candidates.append((bind_host_v4, local_port))

        self._keepalive = threading.Thread(target=self._keep_mapping_open,
                                           daemon=True)
        self._keepalive.start()

    def _keep_mapping_open(self) -> None:
        # Routers forget an unused outside address after 30 s - 5 min. While
        # the user is swapping codes, ping the STUN server so it stays valid.
        while not self._stop.wait(15):
            for sock, server in self._stun_targets:
                try:
                    sock.sendto(build_binding_request(secrets.token_bytes(12)), server)
                except OSError:
                    pass

    def code(self, name: str) -> str:
        return make_code(name, self.peer_id, self.candidates)

    def connect(self, peer: Dict, seconds: float = 120.0,
                on_tick=None) -> Dict:
        """Both PCs send small probes to every address the other PC listed.
        Whichever gets through first proves a direct path exists."""
        if peer.get("id") == self.peer_id:
            # The code is on the clipboard, so pasting this PC's OWN code is
            # an easy mistake - and it would "succeed" by talking to itself.
            return {"ok": False, "own_code": True,
                    "reason": "that is THIS PC's own code - paste the code "
                              "from the OTHER PC"}
        targets: List[Tuple[socket.socket, Addr]] = []
        for host, port in peer["candidates"]:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = self.sockets.get(family)
            if sock:
                targets.append((sock, (host, port)))
        if not targets:
            return {"ok": False, "reason": "no usable addresses in the other PC's code"}

        ids = self.peer_id.encode() + b" " + peer["id"].encode()
        result: Dict = {"ok": False}
        start = time.monotonic()
        next_send = 0.0
        confirmed_until: Optional[float] = None

        while True:
            now = time.monotonic()
            if confirmed_until is not None and now >= confirmed_until:
                break
            if now - start > seconds:
                break
            if now >= next_send:
                # Each probe carries its send time; the reply echoes it back,
                # so the round-trip time is real (not "time since the first
                # attempt", which could be many seconds).
                probe = PROBE + ids + b" " + str(time.monotonic_ns()).encode()
                for sock, addr in targets:
                    try:
                        sock.sendto(probe, addr)
                    except OSError:
                        pass
                next_send = now + 0.3
                if on_tick:
                    on_tick(now - start)
            ready, _, _ = select.select(list(self.sockets.values()), [], [], 0.1)
            for sock in ready:
                try:
                    data, src = sock.recvfrom(2048)
                except OSError:
                    continue
                src = (src[0], src[1])
                parts = data.split(b" ")
                if len(parts) < 3 or parts[1].decode(errors="ignore") != peer["id"] \
                        or parts[2].decode(errors="ignore") != self.peer_id:
                    continue                  # STUN replies, strangers, other tests
                echoed = parts[3] if len(parts) > 3 else b""
                if data.startswith(PROBE):
                    try:
                        sock.sendto(ACK + ids + b" " + echoed, src)
                    except OSError:
                        pass
                rtt = None
                if data.startswith(ACK):
                    try:
                        rtt = round((time.monotonic_ns() - int(echoed)) / 1e6)
                    except ValueError:
                        rtt = None
                if data.startswith(PROBE) or data.startswith(ACK):
                    if not result["ok"]:
                        result = {"ok": True, "path": describe_path(src),
                                  "address": f"{src[0]}:{src[1]}",
                                  "seconds": round(now - start, 1),
                                  "rtt_ms": rtt}
                        # Keep answering briefly so the OTHER PC also
                        # receives our acks and reports success too.
                        confirmed_until = time.monotonic() + 4
                    elif result.get("rtt_ms") is None and rtt is not None:
                        result["rtt_ms"] = rtt
        if not result["ok"]:
            result["reason"] = ("no reply from the other PC within "
                                f"{int(seconds)} seconds")
        return result

    def close(self) -> None:
        self._stop.set()
        for sock in self.sockets.values():
            sock.close()


def describe_path(addr: Addr) -> str:
    ip = addr[0]
    if ":" in ip:
        return "direct over IPv6"
    first = ip.split(".")
    try:
        a, b = int(first[0]), int(first[1])
    except (ValueError, IndexError):
        return "direct"
    if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
        return "direct on the same local network"
    if a == 127:
        return "direct (same PC - test mode)"
    return "direct over the internet (IPv4)"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def copy_to_clipboard(text: str) -> bool:
    """Put the code on the clipboard (Windows' built-in "clip" command), so
    it can be pasted straight into WhatsApp/email."""
    if not sys.platform.startswith("win"):
        return False
    try:
        subprocess.run(["clip"], input=text.encode("ascii"), check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                       timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def result_path() -> Path:
    base = (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path.cwd())
    name = f"FileSender-connection-test-{datetime.now():%Y%m%d-%H%M%S}.txt"
    for folder in (base, Path.home() / "Desktop", Path.home()):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / name
            probe.write_text("", encoding="utf-8")
            return probe
        except OSError:
            continue
    return Path(name)


def format_report(name: str, v4: Dict, v6: Dict, short: str, explain: str,
                  punch: Optional[Dict], peer_name: str = "") -> str:
    lines = [
        "FileSender connection test " + VERSION,
        f"PC name:  {name}",
        f"Date:     {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"System:   {platform.platform()}",
        "",
        "NETWORK CHECK",
        f"  Result: {short}",
        f"  {explain}",
        "",
        "  IPv4: " + ("reachable" if v4.get("available") else "no answer"),
    ]
    for m in v4.get("mappings", []):
        lines.append(f"        seen as {m['outside'][0]}:{m['outside'][1]} by {m['server']}")
    if "same_outside_address" in v4:
        lines.append("        same outside address for different servers: "
                     + ("yes" if v4["same_outside_address"] else "NO"))
    lines.append("  IPv6: " + ("available" if v6.get("available") else "not available"))
    for m in v6.get("mappings", []):
        lines.append(f"        seen as [{m['outside'][0]}]:{m['outside'][1]} by {m['server']}")
    lines.append("")
    lines.append("DIRECT CONNECTION TEST")
    if punch is None:
        lines.append("  Skipped (no code from the other PC was entered).")
    elif punch.get("ok"):
        lines.append(f"  SUCCESS - connected to {peer_name or 'the other PC'} "
                     f"{punch['path']}")
        lines.append(f"  Took {punch['seconds']} s"
                     + (f", round trip {punch['rtt_ms']} ms" if punch.get("rtt_ms") else ""))
    else:
        lines.append(f"  FAILED - {punch.get('reason', 'unknown reason')}")
    return "\n".join(lines) + "\n"


def ask(prompt: str) -> str:
    """input() that treats a closed input as an empty answer."""
    try:
        return input(prompt)
    except EOFError:
        return ""


def run_direct_test(name: str) -> Tuple[Optional[Dict], str]:
    print("\n[2/2] Direct connection test")
    print("      Preparing (a few seconds)...")
    endpoint = Endpoint()
    try:
        my_code = endpoint.code(name)
        print("\nYOUR CODE - send this to the other PC (WhatsApp, email...):\n")
        print(my_code)
        if copy_to_clipboard(my_code):
            print("\n  (Already copied - just paste it into WhatsApp or email.)")
        print("\nWhen you have the OTHER PC's code, paste it below with Ctrl+V")
        print("and press Enter. (Or just press Enter to skip this part.)")

        peer: Optional[Dict] = None
        while peer is None:
            pasted = ask("\nOther PC's code: ").strip()
            if not pasted:
                return None, ""
            try:
                candidate = read_code(pasted)
            except ValueError as exc:
                print(f"  {exc}")
                continue
            if candidate["id"] == endpoint.peer_id:
                print("  That's THIS PC's own code (it's on the clipboard).")
                print("  Paste the code you RECEIVED from the other PC.")
                continue
            peer = candidate

        while True:
            print(f"\nTrying to reach {peer['name']} directly for up to 2 minutes.")
            print("The other PC must have pasted YOUR code and be trying too.")
            punch = endpoint.connect(
                peer, on_tick=lambda t: print(f"\r  trying... {int(t)} s ",
                                              end="", flush=True))
            print()
            if punch["ok"]:
                print(f"\n  SUCCESS - connected {punch['path']}.")
                return punch, peer["name"]
            print(f"\n  FAILED - {punch['reason']}.")
            again = ask("\nPress Enter to try again with the same codes "
                        "(both PCs should retry together),\n"
                        "or type n and press Enter to finish: ").strip().lower()
            if again.startswith("n"):
                return punch, peer["name"]
    finally:
        endpoint.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    print("=" * 62)
    print(" FileSender connection test")
    print("=" * 62)
    print("Run this on BOTH PCs at about the same time.\n")
    try:
        name = ask("Name for this PC (e.g. Bhavik): ").strip() or platform.node()

        print("\n[1/2] Checking this PC's network (up to 30 seconds)...")
        v4 = check_family(socket.AF_INET, STUN_SERVERS)
        v6 = check_family(socket.AF_INET6, STUN_SERVERS)
        short, explain = verdict(v4, v6)
        print(f"      Result: {short}")
        print(f"      {explain}")

        punch: Optional[Dict] = None
        peer_name = ""
        if short != "NO INTERNET":
            punch, peer_name = run_direct_test(name)
    except KeyboardInterrupt:
        print("\n\nStopped. Nothing was changed on this PC.")
        return 1

    report = format_report(name, v4, v6, short, explain, punch, peer_name)
    path = result_path()
    try:
        path.write_text(report, encoding="utf-8")
        print(f"\nResult saved to:\n  {path}\nPlease send that file back.")
    except OSError:
        print("\n" + report)
    ask("\nPress Enter to close.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
