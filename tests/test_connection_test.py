"""Tests for tools/connection_test.py.

No internet is needed: STUN servers are simulated on 127.0.0.x, and the
direct-connection test runs between two endpoints on this machine.
"""

import socket
import struct
import threading
import unittest

from tools import connection_test as ct


def xor_mapped_response(txid: bytes, ip: str, port: int) -> bytes:
    """A STUN Binding Success response, encoded like a real server does."""
    cookie = struct.pack("!I", ct.MAGIC_COOKIE)
    if ":" in ip:
        raw = socket.inet_pton(socket.AF_INET6, ip)
        key = cookie + txid
        family = 0x02
    else:
        raw = socket.inet_pton(socket.AF_INET, ip)
        key = cookie
        family = 0x01
    xored = bytes(b ^ k for b, k in zip(raw, key))
    value = struct.pack("!BBH", 0, family, port ^ (ct.MAGIC_COOKIE >> 16)) + xored
    attr = struct.pack("!HH", ct.ATTR_XOR_MAPPED_ADDRESS, len(value)) + value
    return struct.pack("!HHI12s", ct.BINDING_SUCCESS, len(attr), ct.MAGIC_COOKIE, txid) + attr


class FakeStunServer:
    """Answers every Binding Request with a fixed "outside" address."""

    def __init__(self, host: str, reported: tuple):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, 0))
        self.addr = self.sock.getsockname()
        self.reported = reported
        self.sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, src = self.sock.recvfrom(2048)
            except OSError:
                continue
            if len(data) >= 20:
                txid = data[8:20]
                self.sock.sendto(xor_mapped_response(txid, *self.reported), src)

    def close(self):
        self._stop.set()
        self._thread.join(1)
        self.sock.close()


class TestStunParsing(unittest.TestCase):
    def test_ipv4_round_trip(self):
        txid = b"123456789012"
        data = xor_mapped_response(txid, "203.0.113.7", 54321)
        self.assertEqual(ct.parse_binding_response(data, txid), ("203.0.113.7", 54321))

    def test_ipv6_round_trip(self):
        txid = b"abcdefghijkl"
        data = xor_mapped_response(txid, "2001:db8::42", 40000)
        self.assertEqual(ct.parse_binding_response(data, txid), ("2001:db8::42", 40000))

    def test_reply_to_a_different_request_is_ignored(self):
        data = xor_mapped_response(b"123456789012", "203.0.113.7", 1)
        self.assertIsNone(ct.parse_binding_response(data, b"xxxxxxxxxxxx"))

    def test_garbage_is_ignored(self):
        self.assertIsNone(ct.parse_binding_response(b"hello", b"123456789012"))


class TestNetworkCheck(unittest.TestCase):
    def check_with(self, first_port, second_port):
        a = FakeStunServer("127.0.0.1", ("198.51.100.9", first_port))
        b = FakeStunServer("127.0.0.2", ("198.51.100.9", second_port))
        try:
            # Loopback only: no Windows Firewall pop-up during test runs.
            return ct.check_family(socket.AF_INET, [a.addr, b.addr],
                                   bind_host="127.0.0.1")
        finally:
            a.close()
            b.close()

    def test_router_that_keeps_one_outside_address_is_good(self):
        v4 = self.check_with(40000, 40000)
        self.assertTrue(v4["available"])
        self.assertTrue(v4["same_outside_address"])
        self.assertEqual(ct.verdict(v4, {})[0], "GOOD")

    def test_router_that_changes_address_per_destination_is_hard(self):
        v4 = self.check_with(40000, 40001)
        self.assertFalse(v4["same_outside_address"])
        self.assertEqual(ct.verdict(v4, {})[0], "HARD")

    def test_public_ipv6_is_good(self):
        v6 = {"available": True, "behind_router": False}
        self.assertEqual(ct.verdict({}, v6)[0], "GOOD")

    def test_no_answers_means_no_internet(self):
        self.assertEqual(ct.verdict({"available": False}, {"available": False})[0],
                         "NO INTERNET")


class TestCodes(unittest.TestCase):
    def test_round_trip(self):
        code = ct.make_code("Bhavik", "ab12cd34",
                            [("203.0.113.7", 5000), ("2001:db8::1", 6000)])
        peer = ct.read_code(code)
        self.assertEqual(peer["name"], "Bhavik")
        self.assertEqual(peer["candidates"], [("203.0.113.7", 5000), ("2001:db8::1", 6000)])

    def test_survives_line_breaks_from_chat_apps(self):
        code = ct.make_code("PC", "ab12cd34", [("203.0.113.7", 5000)])
        broken = code[:20] + "\n" + code[20:40] + "  \n " + code[40:]
        self.assertEqual(ct.read_code(broken)["id"], "ab12cd34")

    def test_damaged_code_is_rejected_clearly(self):
        code = ct.make_code("PC", "ab12cd34", [("203.0.113.7", 5000)])
        with self.assertRaises(ValueError):
            ct.read_code(code[:-10])
        with self.assertRaises(ValueError):
            ct.read_code("hello")


class TestDirectConnection(unittest.TestCase):
    """Two "PCs" on this machine swap codes and find each other, exactly as
    the real test does across the internet."""

    def make(self):
        return ct.Endpoint(servers=[], bind_host_v4="127.0.0.1", use_v6=False)

    def test_two_pcs_connect_directly(self):
        pc_a, pc_b = self.make(), self.make()
        try:
            peer_of_a = ct.read_code(pc_b.code("B"))
            peer_of_b = ct.read_code(pc_a.code("A"))
            results = {}
            ta = threading.Thread(target=lambda: results.update(
                a=pc_a.connect(peer_of_a, seconds=10)))
            tb = threading.Thread(target=lambda: results.update(
                b=pc_b.connect(peer_of_b, seconds=10)))
            ta.start(); tb.start(); ta.join(15); tb.join(15)
            self.assertTrue(results["a"]["ok"], results["a"])
            self.assertTrue(results["b"]["ok"], results["b"])
            self.assertIn("direct", results["a"]["path"])
        finally:
            pc_a.close()
            pc_b.close()

    def test_wrong_partner_never_connects(self):
        # Probes are tagged with both IDs, so a stray packet from some other
        # test (or anyone else) can never count as success.
        pc_a, pc_b, stranger = self.make(), self.make(), self.make()
        try:
            wrong = ct.read_code(stranger.code("X"))
            wrong["candidates"] = ct.read_code(pc_b.code("B"))["candidates"]
            threading.Thread(target=lambda: pc_b.connect(
                ct.read_code(pc_a.code("A")), seconds=2), daemon=True).start()
            result = pc_a.connect(wrong, seconds=2)
            self.assertFalse(result["ok"])
        finally:
            for pc in (pc_a, pc_b, stranger):
                pc.close()


class TestMistakesPeopleMake(unittest.TestCase):
    def make(self):
        return ct.Endpoint(servers=[], bind_host_v4="127.0.0.1", use_v6=False)

    def test_own_code_is_rejected_not_reported_as_success(self):
        # The code sits on the clipboard, so Ctrl+V in the window pastes THIS
        # PC's code. It used to "succeed" by talking to itself - a false
        # result that would have decided the whole 4.0 design wrongly.
        pc = self.make()
        try:
            result = pc.connect(ct.read_code(pc.code("Bhavik")), seconds=2)
            self.assertFalse(result["ok"])
            self.assertTrue(result.get("own_code"))
        finally:
            pc.close()

    def test_code_with_text_around_it_is_accepted(self):
        code = ct.make_code("PC", "ab12cd34", [("203.0.113.7", 5000)])
        message = f"Here's my code: {code} - thanks!"
        self.assertEqual(ct.read_code(message)["id"], "ab12cd34")

    def test_round_trip_time_is_real_not_time_since_first_try(self):
        pc_a, pc_b = self.make(), self.make()
        try:
            results = {}
            peer_a, peer_b = ct.read_code(pc_b.code("B")), ct.read_code(pc_a.code("A"))
            ta = threading.Thread(target=lambda: results.update(a=pc_a.connect(peer_a, seconds=8)))
            tb = threading.Thread(target=lambda: results.update(b=pc_b.connect(peer_b, seconds=8)))
            ta.start(); tb.start(); ta.join(12); tb.join(12)
            rtts = [r["rtt_ms"] for r in results.values() if r.get("rtt_ms") is not None]
            self.assertTrue(rtts, results)
            self.assertLess(max(rtts), 500)       # loopback: milliseconds, not seconds
        finally:
            pc_a.close(); pc_b.close()


class TestProgramFlow(unittest.TestCase):
    """Runs the real interactive flow with typed answers simulated."""

    def test_own_code_first_then_the_right_one(self):
        from unittest import mock
        captured, answers, peer = {}, [], ct.Endpoint(
            servers=[], bind_host_v4="127.0.0.1", use_v6=False)
        peer_result = {}

        def fake_clipboard(code):
            captured["mine"] = code
            # The other PC receives our code and starts trying right away.
            threading.Thread(target=lambda: peer_result.update(
                r=peer.connect(ct.read_code(code), seconds=10)), daemon=True).start()
            return True

        def fake_ask(prompt):
            answers.append(prompt)
            if "Other PC's code" in prompt:
                # First paste: our own code (the clipboard mistake). Second:
                # the right one.
                return captured["mine"] if len(answers) == 1 else peer.code("Studio PC")
            return "n"

        try:
            with mock.patch.object(ct, "Endpoint", lambda: ct.Endpoint.__new__(ct.Endpoint) and
                                   ct.Endpoint(servers=[], bind_host_v4="127.0.0.1", use_v6=False)) \
                    if False else mock.patch.object(ct, "copy_to_clipboard", fake_clipboard), \
                 mock.patch.object(ct, "ask", fake_ask), \
                 mock.patch.object(ct, "STUN_SERVERS", []):
                original_init = ct.Endpoint.__init__

                def loopback_init(self, servers=(), bind_host_v4="127.0.0.1", use_v6=False):
                    original_init(self, servers=[], bind_host_v4="127.0.0.1", use_v6=False)

                with mock.patch.object(ct.Endpoint, "__init__", loopback_init):
                    punch, name = ct.run_direct_test("Bhavik")
            self.assertTrue(punch["ok"], punch)
            self.assertEqual(name, "Studio PC")
            self.assertEqual(sum("Other PC's code" in a for a in answers), 2)
        finally:
            peer.close()

    def test_no_internet_still_saves_a_report(self):
        import os, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(ct, "check_family", return_value={"available": False}), \
                     mock.patch.object(ct, "ask", return_value=""):
                    self.assertEqual(ct.main(), 0)
                reports = [f for f in os.listdir(tmp) if f.startswith("FileSender-connection-test")]
                self.assertEqual(len(reports), 1)
            finally:
                os.chdir(cwd)

    def test_ctrl_c_exits_cleanly(self):
        from unittest import mock
        with mock.patch.object(ct, "ask", side_effect=KeyboardInterrupt):
            self.assertEqual(ct.main(), 1)


class TestReport(unittest.TestCase):
    def test_success_report(self):
        text = ct.format_report("Bhavik", {"available": True, "mappings": []},
                                {"available": False}, "GOOD", "fine",
                                {"ok": True, "path": "direct over IPv6",
                                 "seconds": 1.2, "rtt_ms": 35}, "Studio PC")
        self.assertIn("SUCCESS", text)
        self.assertIn("Studio PC", text)

    def test_skipped_report(self):
        text = ct.format_report("Bhavik", {}, {}, "GOOD", "fine", None)
        self.assertIn("Skipped", text)


if __name__ == "__main__":
    unittest.main()
