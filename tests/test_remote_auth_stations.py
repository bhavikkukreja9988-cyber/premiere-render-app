"""Tests for the remote auth and station services (against the fake transport)."""

import time
import unittest

from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.auth import AuthService, family_account_email, family_account_password
from src.remote.stations import StationService
from src.remote.transport import OfflineError


def make_config(**over) -> RemoteConfig:
    base = dict(url="https://example.supabase.co", publishable_key="pk",
                heartbeat_interval=0.05, station_offline_after=1.0)
    base.update(over)
    return RemoteConfig(**base)


class TestFamilyAccountDerivation(unittest.TestCase):
    """Pure functions: same family code must always reach the same account,
    different codes must never collide. This is the actual security
    boundary now - worth testing directly, not just through AuthService."""

    def test_same_code_gives_same_credentials(self):
        self.assertEqual(family_account_email("smiths"), family_account_email("smiths"))
        self.assertEqual(family_account_password("smiths"), family_account_password("smiths"))

    def test_different_codes_give_different_credentials(self):
        self.assertNotEqual(family_account_email("smiths"), family_account_email("joneses"))
        self.assertNotEqual(family_account_password("smiths"), family_account_password("joneses"))

    def test_normalisation_makes_near_identical_codes_match(self):
        # "Smith Family" and "smith family" must reach the SAME account, or
        # two PCs typing it slightly differently silently can't see each
        # other - the exact class of bug this whole feature exists to fix.
        self.assertEqual(family_account_email("  Smith  Family "),
                         family_account_email("smith family"))

    def test_email_and_password_are_not_trivially_related(self):
        # Different derivation salts, so one can't be reconstructed from the
        # other even though both come from the same family code.
        email = family_account_email("smiths")
        password = family_account_password("smiths")
        self.assertNotIn("smiths", email)
        self.assertNotIn("smiths", password)
        self.assertNotEqual(email.split("@")[0], password)


class TestAuthService(unittest.TestCase):
    """No login screen, but real per-family isolation: each family code
    silently signs into its OWN Supabase account, deterministically derived
    so every PC using the same code reaches the same account, and different
    codes are genuinely different accounts - not just a client-side filter."""

    def setUp(self):
        self.transport = FakeTransport()
        self.auth = AuthService(self.transport, make_config())

    def test_first_use_creates_the_family_account(self):
        self.assertTrue(self.auth.ensure_signed_in("smiths"))
        self.assertTrue(self.auth.signed_in)
        self.assertTrue(self.auth.user_id)

    def test_second_pc_with_the_same_code_reaches_the_same_account(self):
        # This is the property that fixes the original bug: two real PCs in
        # one household must land in the same account, or they can't see
        # each other and the station looks permanently offline.
        self.auth.ensure_signed_in("smiths")
        first_user = self.auth.user_id

        other_pc = AuthService(self.transport, make_config())
        other_pc.ensure_signed_in("smiths")
        self.assertEqual(other_pc.user_id, first_user)

    def test_different_family_codes_get_different_accounts(self):
        # This is the property that fixes the security gap: two different
        # families must be genuinely isolated at the database level, not
        # just hidden from each other by a UI filter.
        self.auth.ensure_signed_in("smiths")
        smiths_user = self.auth.user_id

        other_pc = AuthService(self.transport, make_config())
        other_pc.ensure_signed_in("joneses")
        self.assertNotEqual(other_pc.user_id, smiths_user)

    def test_near_identical_codes_still_match(self):
        self.auth.ensure_signed_in("Smith Family")
        first_user = self.auth.user_id
        other_pc = AuthService(self.transport, make_config())
        other_pc.ensure_signed_in("smith family")
        self.assertEqual(other_pc.user_id, first_user)

    def test_repeated_calls_are_idempotent(self):
        self.auth.ensure_signed_in("smiths")
        user_id = self.auth.user_id
        self.assertTrue(self.auth.ensure_signed_in("smiths"))
        self.assertEqual(self.auth.user_id, user_id)

    def test_switching_family_code_reauthenticates(self):
        self.auth.ensure_signed_in("smiths")
        smiths_user = self.auth.user_id
        self.auth.ensure_signed_in("joneses")
        self.assertTrue(self.auth.signed_in)
        self.assertNotEqual(self.auth.user_id, smiths_user)

    def test_empty_family_code_fails_without_raising(self):
        self.assertFalse(self.auth.ensure_signed_in(""))
        self.assertFalse(self.auth.ensure_signed_in("   "))
        self.assertFalse(self.auth.signed_in)

    def test_offline_reports_failure_without_raising(self):
        self.transport.offline = True
        self.assertFalse(self.auth.ensure_signed_in("smiths"))
        self.assertFalse(self.auth.signed_in)

    def test_no_password_api_is_exposed(self):
        # Guards against a visible login screen creeping back in.
        for removed in ("sign_up", "sign_in", "sign_in_or_create"):
            self.assertFalse(hasattr(self.auth, removed),
                             f"{removed} should not be a public method")


class TestStationService(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.config = make_config()
        self.auth = AuthService(self.transport, self.config)
        self.auth.ensure_signed_in("test-family")
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

    def test_stations_are_scoped_by_family_code(self):
        # The family code replaced per-user isolation. Two households sharing
        # the built-in account must still not see each other.
        self.stations.register("RS-mine", "Mine", "2.0.0",
                               family_code="smiths", device_name="Mine")
        self.stations.register("RS-theirs", "Theirs", "2.0.0",
                               family_code="joneses", device_name="Theirs")
        mine = {s.id for s in self.stations.list_stations(family_code="smiths")}
        self.assertEqual(mine, {"RS-mine"})

    def test_own_station_is_excluded_from_the_list(self):
        # Sending a job to yourself uploads and downloads it right back, which
        # looks exactly like a failure. The sender must not offer itself.
        self.stations.register("RS-me", "This PC", "2.0.0",
                               family_code="smiths", device_name="This PC")
        self.stations.register("RS-other", "Other PC", "2.0.0",
                               family_code="smiths", device_name="Other PC")
        visible = {s.id for s in self.stations.list_stations(
            family_code="smiths", exclude_station_id="RS-me")}
        self.assertEqual(visible, {"RS-other"})

    def test_device_name_is_what_shows_up(self):
        # Two PCs used to show identical hostnames, making them impossible to
        # tell apart in the dropdown. The user-chosen name must win.
        self.stations.register("RS-1", "ignored-hostname", "2.0.0",
                               family_code="smiths", device_name="Bhavik's PC")
        station = self.stations.get_station("RS-1")
        self.assertEqual(station.device_name, "Bhavik's PC")
        self.assertEqual(station.name, "Bhavik's PC")


if __name__ == "__main__":
    unittest.main()
