"""Regression tests for the bugs that made sending fail in real use.

Each test here maps to something that actually went wrong on the user's two
PCs, so a future refactor can't quietly reintroduce it. Uses the SAME family
code for "two real PCs in one household" scenarios, and DIFFERENT codes where
the test is specifically about cross-family isolation.
"""

import time
import unittest

from src.core.config import AppConfig
from src.remote.auth import AuthService
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.jobs import RemoteJobService
from src.remote.stations import StationService


def make_config(**over) -> RemoteConfig:
    base = dict(url="https://example.supabase.co", publishable_key="pk",
                station_offline_after=45.0)
    base.update(over)
    return RemoteConfig(**base)


class TwoPCTestCase(unittest.TestCase):
    """Simulates two real PCs, both using the SAME family code — exactly the
    user's actual setup of two PCs in one household."""

    FAMILY_CODE = "smiths"

    def setUp(self):
        self.remote_config = make_config()
        # One shared cloud, exactly like one real Supabase project.
        self.cloud = FakeTransport()

        # PC A — the sender
        self.auth_a = AuthService(self.cloud, self.remote_config)
        self.auth_a.ensure_signed_in(self.FAMILY_CODE)
        self.stations_a = StationService(self.cloud, self.remote_config)
        self.jobs_a = RemoteJobService(self.cloud, self.remote_config)

        # PC B — the render station (separate install, same family code)
        self.auth_b = AuthService(self.cloud, self.remote_config)
        self.auth_b.ensure_signed_in(self.FAMILY_CODE)
        self.stations_b = StationService(self.cloud, self.remote_config)


class TestOfflineBug(TwoPCTestCase):
    """The headline bug: both PCs had the app open, yet the sender insisted
    the render station was offline."""

    def test_second_pc_is_visible_to_the_first(self):
        self.stations_b.register("RS-B", "Render PC", "3.0.0",
                                 family_code=self.FAMILY_CODE,
                                 device_name="Render PC")
        visible = self.stations_a.list_stations(family_code=self.FAMILY_CODE)
        self.assertEqual([s.id for s in visible], ["RS-B"])

    def test_second_pc_reads_as_online_right_after_registering(self):
        self.stations_b.register("RS-B", "Render PC", "3.0.0",
                                 family_code=self.FAMILY_CODE,
                                 device_name="Render PC")
        station = self.stations_a.get_station("RS-B")
        self.assertTrue(station.is_online(self.remote_config.station_offline_after))

    def test_heartbeat_keeps_it_online(self):
        self.stations_b.register("RS-B", "Render PC", "3.0.0",
                                 family_code=self.FAMILY_CODE,
                                 device_name="Render PC")
        self.cloud.update("stations", {"id": "RS-B"},
                          {"last_seen": time.time() - 300})
        self.assertFalse(self.stations_a.is_online("RS-B"))
        self.stations_b.beat("RS-B")
        self.assertTrue(self.stations_a.is_online("RS-B"))


class TestSelfSendBug(TwoPCTestCase):
    """The sender's own PC appeared in its own dropdown, so a job could be
    sent to itself — uploading and downloading straight back, which looks
    identical to a failure."""

    def test_own_pc_never_appears_in_its_own_list(self):
        self.stations_a.register("RS-A", "Sender PC", "3.0.0",
                                 family_code=self.FAMILY_CODE, device_name="Sender PC")
        self.stations_b.register("RS-B", "Render PC", "3.0.0",
                                 family_code=self.FAMILY_CODE, device_name="Render PC")
        visible = self.stations_a.list_stations(
            family_code=self.FAMILY_CODE, exclude_station_id="RS-A")
        self.assertEqual([s.id for s in visible], ["RS-B"])

    def test_identical_hostnames_still_produce_distinct_names(self):
        self.stations_a.register("RS-A", "DESKTOP-PC", "3.0.0",
                                 family_code=self.FAMILY_CODE, device_name="Bhavik's PC")
        self.stations_b.register("RS-B", "DESKTOP-PC", "3.0.0",
                                 family_code=self.FAMILY_CODE, device_name="Studio PC")
        names = sorted(s.name for s in
                       self.stations_a.list_stations(family_code=self.FAMILY_CODE))
        self.assertEqual(names, ["Bhavik's PC", "Studio PC"])


class TestCrossFamilyIsolation(unittest.TestCase):
    """The security fix: two different families must be genuinely isolated
    at the database level (real auth.uid()-based RLS-equivalent scoping in
    the fake transport), not merely hidden from each other by an app-side
    filter that a technically capable stranger could bypass."""

    def setUp(self):
        self.remote_config = make_config()
        self.cloud = FakeTransport()

        # Independent sessions sharing one backend - exactly like two real,
        # differently-configured PCs talking to the same Supabase project.
        self.client_smiths = self.cloud.new_client()
        self.auth_smiths = AuthService(self.client_smiths, self.remote_config)
        self.auth_smiths.ensure_signed_in("smiths")
        self.stations_smiths = StationService(self.client_smiths, self.remote_config)
        self.jobs_smiths = RemoteJobService(self.client_smiths, self.remote_config)

        self.client_joneses = self.cloud.new_client()
        self.auth_joneses = AuthService(self.client_joneses, self.remote_config)
        self.auth_joneses.ensure_signed_in("joneses")
        self.stations_joneses = StationService(self.client_joneses, self.remote_config)

    def test_families_get_genuinely_different_accounts(self):
        # The actual security property: not just different family_code
        # column values, but different authenticated identities.
        self.assertNotEqual(self.auth_smiths.user_id, self.auth_joneses.user_id)

    def test_a_family_cannot_see_the_others_stations_even_without_a_filter(self):
        self.stations_smiths.register("RS-mine", "Mine", "3.0.0",
                                      family_code="smiths", device_name="Mine")
        self.stations_joneses.register("RS-theirs", "Theirs", "3.0.0",
                                       family_code="joneses", device_name="Theirs")

        # Deliberately call list_stations with NO family_code filter, as a
        # careless or malicious client might. Real isolation means this
        # still can't see the other family's row - the app-level filter
        # isn't what's protecting it.
        smiths_view = self.stations_smiths.list_stations()
        self.assertEqual([s.id for s in smiths_view], ["RS-mine"])

        joneses_view = self.stations_joneses.list_stations()
        self.assertEqual([s.id for s in joneses_view], ["RS-theirs"])

    def test_a_family_cannot_read_the_others_jobs_either(self):
        self.jobs_smiths.create_job("RS-mine", "Secret Smith Project",
                                    family_code="smiths")
        jobs_joneses = RemoteJobService(self.client_joneses, self.remote_config)
        self.assertEqual(jobs_joneses.list_jobs(), [])

    def test_changing_family_code_moves_a_device_to_the_new_family(self):
        self.stations_smiths.register("RS-B", "Render PC", "3.0.0",
                                      family_code="smiths", device_name="Render PC")
        self.assertEqual(len(self.stations_smiths.list_stations()), 1)

        # Simulate Settings -> change family code -> restart: a fresh auth +
        # station service pair signs into the NEW family's account and
        # re-registers there.
        client_new = self.cloud.new_client()
        auth_new = AuthService(client_new, self.remote_config)
        auth_new.ensure_signed_in("newcode")
        stations_new = StationService(client_new, self.remote_config)
        stations_new.register("RS-B", "Render PC", "3.0.0",
                              family_code="newcode", device_name="Render PC")

        # The device now lives under the new family entirely; the old
        # family's account never sees it appear there.
        self.assertEqual(len(stations_new.list_stations()), 1)


class TestProgressReporting(TwoPCTestCase):
    """There was no receiver-side feedback at all, so a running job looked
    identical to a stuck one."""

    def test_station_progress_is_visible_to_the_sender(self):
        job = self.jobs_a.create_job("RS-B", "MyVideo", family_code=self.FAMILY_CODE)
        jobs_b = RemoteJobService(self.cloud, self.remote_config)
        jobs_b.report_progress(job.id, 0.25, "Downloading clip.mov")

        seen = self.jobs_a.get_job(job.id)
        self.assertAlmostEqual(seen.progress, 0.25, places=3)
        self.assertEqual(seen.progress_label, "Downloading clip.mov")

    def test_progress_is_clamped(self):
        job = self.jobs_a.create_job("RS-B", "MyVideo", family_code=self.FAMILY_CODE)
        self.jobs_a.report_progress(job.id, 5.0, "bad value")
        self.assertLessEqual(self.jobs_a.get_job(job.id).progress, 1.0)
        self.jobs_a.report_progress(job.id, -3.0, "bad value")
        self.assertGreaterEqual(self.jobs_a.get_job(job.id).progress, 0.0)


class TestSetupGate(unittest.TestCase):
    def test_fresh_install_needs_setup(self):
        self.assertFalse(AppConfig().setup_complete)

    def test_setup_complete_once_named(self):
        config = AppConfig()
        config.device_name = "Bhavik's PC"
        config.family_code = "smiths"
        self.assertTrue(config.setup_complete)

    def test_whitespace_only_does_not_count(self):
        config = AppConfig()
        config.device_name = "   "
        config.family_code = "smiths"
        self.assertFalse(config.setup_complete)


if __name__ == "__main__":
    unittest.main()
