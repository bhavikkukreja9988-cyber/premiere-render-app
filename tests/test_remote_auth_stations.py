"""Tests for the remote auth and station services (against the fake transport)."""

import time
import unittest

from src.remote.config import RemoteConfig, username_to_email
from src.remote.fake_transport import FakeTransport
from src.remote.auth import AuthService
from src.remote.stations import StationService
from src.remote.transport import AuthError, OfflineError


def make_config(**over) -> RemoteConfig:
    base = dict(url="https://example.supabase.co", publishable_key="pk",
                heartbeat_interval=0.05, station_offline_after=1.0)
    base.update(over)
    return RemoteConfig(**base)


class TestUsernameMapping(unittest.TestCase):
    def test_username_maps_to_synthetic_email(self):
        self.assertEqual(username_to_email("Bhavik"), "bhavik@filesender.local")

    def test_existing_email_passes_through(self):
        self.assertEqual(username_to_email("a@b.com"), "a@b.com")

    def test_empty_username_rejected(self):
        with self.assertRaises(ValueError):
            username_to_email("   ")


class TestAuthService(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.auth = AuthService(self.transport, make_config())

    def test_sign_up_then_signed_in(self):
        self.auth.sign_up("bhavik", "secret")
        self.assertTrue(self.auth.signed_in)
        self.assertEqual(self.auth.username, "bhavik")
        self.assertTrue(self.auth.user_id)

    def test_sign_in_wrong_password(self):
        self.auth.sign_up("bhavik", "secret")
        self.transport.sign_out()
        with self.assertRaises(AuthError):
            self.auth.sign_in("bhavik", "wrong")

    def test_sign_in_or_create_is_idempotent_login(self):
        first = self.auth.sign_in_or_create("dad", "pw12")
        self.transport.sign_out()
        second = self.auth.sign_in_or_create("dad", "pw12")
        self.assertEqual(first.user_id, second.user_id)

    def test_offline_sign_in_raises_friendly(self):
        self.transport.offline = True
        with self.assertRaises(OfflineError):
            self.auth.sign_in("x", "y")


class TestStationService(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.config = make_config()
        self.auth = AuthService(self.transport, self.config)
        self.auth.sign_up("owner", "pw12")
        self.stations = StationService(self.transport, self.config)

    def test_register_and_find(self):
        self.stations.register("RS-abc", "Bhavik Render PC", "2.0.0")
        found = self.stations.get_station("RS-abc")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Bhavik Render PC")
        self.assertTrue(self.stations.is_online("RS-abc"))

    def test_station_goes_offline_when_stale(self):
        self.stations.register("RS-abc", "PC", "2.0.0")
        # Force last_seen into the past beyond the window.
        self.transport.update("stations", {"id": "RS-abc"},
                              {"last_seen": time.time() - 10})
        self.assertFalse(self.stations.is_online("RS-abc"))

    def test_beat_refreshes_presence(self):
        self.stations.register("RS-abc", "PC", "2.0.0")
        self.transport.update("stations", {"id": "RS-abc"},
                              {"last_seen": time.time() - 10})
        self.assertFalse(self.stations.is_online("RS-abc"))
        self.stations.beat("RS-abc")
        self.assertTrue(self.stations.is_online("RS-abc"))

    def test_go_offline_marks_status(self):
        self.stations.register("RS-abc", "PC", "2.0.0")
        self.stations.go_offline("RS-abc")
        self.assertEqual(self.stations.get_station("RS-abc").status, "offline")

    def test_online_stations_filters_by_last_seen(self):
        self.stations.register("RS-live", "Live", "2.0.0")
        self.stations.register("RS-dead", "Dead", "2.0.0")
        self.transport.update("stations", {"id": "RS-dead"},
                              {"last_seen": time.time() - 100})
        online = {s.id for s in self.stations.online_stations()}
        self.assertIn("RS-live", online)
        self.assertNotIn("RS-dead", online)

    def test_stations_are_isolated_between_users(self):
        # Another user's station must never be visible.
        self.stations.register("RS-mine", "Mine", "2.0.0")
        other_auth = AuthService(self.transport, self.config)
        other_auth.sign_up("stranger", "pw12")
        other_stations = StationService(self.transport, self.config)
        self.assertEqual(other_stations.list_stations(), [])


if __name__ == "__main__":
    unittest.main()
