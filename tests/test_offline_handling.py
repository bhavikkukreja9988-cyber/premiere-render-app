"""Network failures during sign-in must be treated as "offline", not "no account".

Real failure seen on Windows: `[Errno 11001] getaddrinfo failed` (DNS couldn't
resolve the Supabase host). The live transport used to wrap EVERY sign-in
exception as an AuthError, so the app concluded the family account didn't
exist, tried to create it, and logged the misleading "could not create the
family account". It also never retried.
"""

import unittest

from src.remote.auth import AuthService
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.supabase_transport import SupabaseTransport, _is_network_error
from src.remote.transport import AuthError, OfflineError


class ConnectError(Exception):
    """Stand-in for httpx.ConnectError (httpx may not be installed in tests)."""


class AuthApiError(Exception):
    """Stand-in for gotrue's AuthApiError."""


class TestNetworkErrorDetection(unittest.TestCase):
    def test_windows_dns_failure_from_the_real_log(self):
        self.assertTrue(_is_network_error(
            ConnectError("[Errno 11001] getaddrinfo failed")))

    def test_other_network_failures(self):
        for exc in (OSError("[Errno -2] Name or service not known"),
                    Exception("The read operation timed out"),
                    ConnectionRefusedError("connection refused")):
            self.assertTrue(_is_network_error(exc), exc)

    def test_real_auth_errors_are_not_network_errors(self):
        for message in ("Invalid login credentials", "User already registered",
                        "Email not confirmed"):
            self.assertFalse(_is_network_error(AuthApiError(message)), message)

    def test_permission_errors_are_not_network_errors(self):
        self.assertFalse(_is_network_error(
            Exception("new row violates row-level security policy")))


class _FailingAuth:
    def __init__(self, exc):
        self.exc = exc

    def sign_in_with_password(self, credentials):
        raise self.exc

    def sign_up(self, credentials):
        raise self.exc


class TestLiveTransportSignIn(unittest.TestCase):
    """Exercises the real SupabaseTransport sign-in wrappers without a
    network, by swapping in a client whose auth calls raise."""

    def transport_raising(self, exc):
        transport = SupabaseTransport.__new__(SupabaseTransport)
        transport._client = type("C", (), {"auth": _FailingAuth(exc)})()
        transport._user_id = ""
        return transport

    def test_dns_failure_on_sign_in_raises_offline(self):
        transport = self.transport_raising(
            ConnectError("[Errno 11001] getaddrinfo failed"))
        with self.assertRaises(OfflineError):
            transport.sign_in("a@b.local", "pw")

    def test_dns_failure_on_sign_up_raises_offline(self):
        transport = self.transport_raising(
            ConnectError("[Errno 11001] getaddrinfo failed"))
        with self.assertRaises(OfflineError):
            transport.sign_up("a@b.local", "pw")

    def test_wrong_password_still_raises_auth_error(self):
        transport = self.transport_raising(
            AuthApiError("Invalid login credentials"))
        with self.assertRaises(AuthError):
            transport.sign_in("a@b.local", "pw")


class TestAuthServiceWhenOffline(unittest.TestCase):
    def test_offline_does_not_attempt_to_create_an_account(self):
        # If "offline" were mistaken for "no account", the service would call
        # sign_up — creating accounts is the wrong reaction to a DNS failure.
        transport = FakeTransport()
        calls = []
        original_sign_up = transport.sign_up

        def tracking_sign_up(email, password):
            calls.append(email)
            return original_sign_up(email, password)

        transport.sign_up = tracking_sign_up
        transport.offline = True
        auth = AuthService(transport, RemoteConfig(url="x", publishable_key="y"))
        self.assertFalse(auth.ensure_signed_in("292005"))
        self.assertEqual(calls, [])

    def test_connects_once_the_network_is_back(self):
        # The app now retries; the same AuthService must succeed on a later
        # attempt without needing a restart.
        transport = FakeTransport()
        auth = AuthService(transport, RemoteConfig(url="x", publishable_key="y"))
        transport.offline = True
        self.assertFalse(auth.ensure_signed_in("292005"))
        transport.offline = False
        self.assertTrue(auth.ensure_signed_in("292005"))
        self.assertTrue(auth.signed_in)

    def test_auth_service_has_no_username_attribute(self):
        # The status bar used to read auth.username, which no longer exists,
        # and would have crashed the app the first time it connected.
        auth = AuthService(FakeTransport(), RemoteConfig(url="x", publishable_key="y"))
        self.assertFalse(hasattr(auth, "username"))


if __name__ == "__main__":
    unittest.main()
