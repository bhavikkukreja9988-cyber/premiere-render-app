import socket
import unittest

from src.core.protocol import (Connection, Msg, ProtocolError, RemoteError,
                               auth_token, check_auth, new_nonce)


class ProtocolTestBase(unittest.TestCase):
    def setUp(self):
        left, right = socket.socketpair()
        self.a = Connection(left, timeout=5)
        self.b = Connection(right, timeout=5)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)


class TestFraming(ProtocolTestBase):
    def test_control_message_roundtrip(self):
        self.a.send(Msg.HELLO, {"protocol": 2, "sender_name": "edit-pc"})
        msg = self.b.recv(expect=Msg.HELLO)
        self.assertEqual(msg.get("sender_name"), "edit-pc")
        self.assertEqual(msg.data, b"")

    def test_binary_payload_is_byte_exact(self):
        blob = bytes(range(256)) * 400
        self.a.send(Msg.FILE_CHUNK, {"path": "clip.mp4"}, blob)
        msg = self.b.recv(expect=Msg.FILE_CHUNK)
        self.assertEqual(msg.data, blob)

    def test_messages_do_not_bleed_into_each_other(self):
        self.a.send(Msg.FILE_CHUNK, {}, b"one")
        self.a.send(Msg.FILE_CHUNK, {}, b"two")
        self.a.send(Msg.FILE_END, {"sha256": "abc"})
        self.assertEqual(self.b.recv().data, b"one")
        self.assertEqual(self.b.recv().data, b"two")
        self.assertEqual(self.b.recv().type, Msg.FILE_END)

    def test_unicode_paths_survive(self):
        self.a.send(Msg.FILE_BEGIN, {"path": "footage/日本語/ клип.mp4"})
        self.assertEqual(self.b.recv().get("path"), "footage/日本語/ клип.mp4")

    def test_unexpected_type_raises(self):
        self.a.send(Msg.PONG, {})
        with self.assertRaises(ProtocolError):
            self.b.recv(expect=Msg.HELLO_OK)

    def test_error_message_becomes_exception(self):
        self.a.error("auth_failed", "wrong pairing code")
        with self.assertRaises(RemoteError) as caught:
            self.b.recv()
        self.assertEqual(caught.exception.code, "auth_failed")

    def test_closed_peer_raises(self):
        self.a.close()
        with self.assertRaises(ProtocolError):
            self.b.recv()


class TestPairing(unittest.TestCase):
    def test_token_matches_for_the_right_code(self):
        nonce = new_nonce()
        self.assertTrue(check_auth("123456", nonce, auth_token("123456", nonce)))

    def test_token_fails_for_the_wrong_code(self):
        nonce = new_nonce()
        self.assertFalse(check_auth("123456", nonce, auth_token("654321", nonce)))

    def test_token_is_nonce_bound(self):
        token = auth_token("123456", new_nonce())
        self.assertFalse(check_auth("123456", new_nonce(), token))


if __name__ == "__main__":
    unittest.main()
