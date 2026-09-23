"""Send-path audit: regression tests.

Every test here corresponds to a problem found while auditing the sending
path against how the REAL Supabase behaves (the rest of the suite uses a
simulated Supabase, which is how several of these went unnoticed):

  1. an expired login was never recovered;
  2. heartbeats used each PC's own clock, so clock differences made a
     running station look offline;
  3. a station ID could clash after a family-code change, leaving that PC
     permanently unable to come online;
  4. failed / cancelled sends left their files in Supabase forever;
  5. "storage full" showed a vague error;
  6. user-facing errors still talked about signing in and passwords;
  7. media paths with "&" in them were misread from the project file.
"""

import gzip
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from src.core.config import AppConfig
from src.core.project_probe import find_external_media
from src.remote import transport as transport_module
from src.remote.auth import AuthService
from src.remote.client import RemoteClient
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.models import RemoteJobState
from src.remote.sender_service import RemoteSendRequest, RemoteSendWorker
from src.remote.station_worker import RemoteStationWorker
from src.remote.stations import StationService
from src.remote.storage import project_object_path
from src.remote.supabase_transport import SupabaseTransport
from src.remote.transport import (NotAuthenticatedError, QuotaExceededError,
                                  RemoteError)
from src.render.pipeline import RenderBackend


def remote_config():
    return RemoteConfig(url="https://x.supabase.co", publishable_key="pk",
                        station_offline_after=45.0)


class _IdleBackend(RenderBackend):
    name = "idle"

    def render(self, record, job_root, progress, cancel):       # pragma: no cover
        raise AssertionError("not used")


# ---------------------------------------------------------------------------
# 1. Expired login is renewed automatically
# ---------------------------------------------------------------------------
class _Response:
    def __init__(self, data):
        self.data = data


class _ExpiringQuery:
    """Fails with Supabase's real "JWT expired" error until re-signed-in."""

    def __init__(self, client):
        self.client = client

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def order(self, *_, **__):
        return self

    def execute(self):
        if self.client.token_expired:
            raise Exception("{'code': 'PGRST301', 'message': 'JWT expired'}")
        return _Response([{"id": "row-1"}])


class _ExpiringClient:
    def __init__(self):
        self.token_expired = False
        self.sign_ins = 0
        client = self

        class _Auth:
            def sign_in_with_password(self, credentials):
                client.sign_ins += 1
                client.token_expired = False
                user = type("U", (), {"id": "user-1", "email": credentials["email"]})()
                session = type("S", (), {"access_token": "a", "refresh_token": "r",
                                         "expires_at": 0})()
                return type("R", (), {"user": user, "session": session})()

        self.auth = _Auth()

    def table(self, _name):
        return _ExpiringQuery(self)


class TestExpiredLoginRecovery(unittest.TestCase):
    def make_transport(self):
        transport = SupabaseTransport.__new__(SupabaseTransport)
        transport.config = remote_config()
        transport._client = _ExpiringClient()
        transport._user_id = ""
        transport._credentials = None
        transport._reauth_lock = threading.Lock()
        transport.sign_in("family@filesender.local", "pw")
        return transport

    def test_expired_login_is_renewed_and_the_call_succeeds(self):
        transport = self.make_transport()
        transport._client.token_expired = True        # an hour later...
        rows = transport.select("stations")
        self.assertEqual(rows, [{"id": "row-1"}])
        self.assertEqual(transport._client.sign_ins, 2)   # original + renewal

    def test_without_saved_credentials_the_expiry_is_reported(self):
        transport = self.make_transport()
        transport._credentials = None
        transport._client.token_expired = True
        with self.assertRaises(NotAuthenticatedError):
            transport.select("stations")


# ---------------------------------------------------------------------------
# 2. One clock for everyone
# ---------------------------------------------------------------------------
class TestClockDifferences(unittest.TestCase):
    def setUp(self):
        self.cloud = FakeTransport()
        self.render_pc = StationService(self.cloud.new_client(), remote_config())
        self.sender_pc = StationService(self.cloud.new_client(), remote_config())
        for service in (self.render_pc, self.sender_pc):
            AuthService(service.transport, remote_config()).ensure_signed_in("fam")

    def _render_pc_clock_behind(self, seconds):
        real_time = time.time
        fake_clock = mock.Mock()
        fake_clock.time.side_effect = lambda: real_time() - seconds
        return mock.patch("src.remote.stations.time", fake_clock)

    def test_station_with_a_slow_clock_still_shows_online(self):
        # Render PC's clock is 5 minutes slow. Heartbeats used to be stamped
        # with that clock, so the sender saw them as 5 minutes old: offline.
        with self._render_pc_clock_behind(300):
            self.render_pc.register("RS-R", "Render PC", "3", family_code="fam",
                                    device_name="Render PC")
            self.render_pc.beat("RS-R")
        self.assertTrue(self.sender_pc.is_online("RS-R"))

    def test_the_old_behaviour_really_was_broken(self):
        # Same scenario with the server clock unavailable (migration 007 not
        # run): this is exactly the bug — a running station shows offline.
        with mock.patch.object(FakeTransport, "server_time",
                               side_effect=RemoteError("function not found")):
            with self._render_pc_clock_behind(300):
                self.render_pc.register("RS-R", "Render PC", "3",
                                        family_code="fam", device_name="Render PC")
            self.assertFalse(self.sender_pc.is_online("RS-R"))

    def test_falls_back_to_the_local_clock_without_migration_007(self):
        with mock.patch.object(FakeTransport, "server_time",
                               side_effect=RemoteError("function not found")):
            now = self.sender_pc.server_now()
        self.assertAlmostEqual(now, time.time(), delta=2)

    def test_server_clock_is_used_when_available(self):
        self.cloud.server_clock_offset = 120.0
        service = StationService(self.cloud.new_client(), remote_config())
        AuthService(service.transport, remote_config()).ensure_signed_in("fam")
        self.assertAlmostEqual(service.server_now(), time.time() + 120, delta=2)


# ---------------------------------------------------------------------------
# 3. Station ID clash after a family-code change
# ---------------------------------------------------------------------------
class TestStationIdClash(unittest.TestCase):
    def test_worker_takes_a_fresh_id_and_comes_online(self):
        cloud = FakeTransport()
        # The ID is already registered under the OLD family's account.
        old = cloud.new_client()
        AuthService(old, remote_config()).ensure_signed_in("old-family")
        StationService(old, remote_config()).register(
            "RS-CLASH", "PC", "3", family_code="old-family", device_name="PC")

        new = RemoteClient(cloud.new_client(), remote_config())
        new.auth.ensure_signed_in("new-family")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = AppConfig(workspace_dir=tmp.name, station_id="RS-CLASH",
                           device_name="PC", family_code="new-family")
        worker = RemoteStationWorker(new, config, backend=_IdleBackend())
        with mock.patch("src.remote.station_worker.save_config") as saved:
            worker.start()
        self.addCleanup(worker.stop)

        self.assertNotEqual(config.station_id, "RS-CLASH")
        self.assertTrue(saved.called, "the new ID must be saved")
        self.assertTrue(worker.started)
        self.assertEqual([s.id for s in new.stations.list_stations()],
                         [config.station_id])


# ---------------------------------------------------------------------------
# 4. Dead jobs don't leave files in Supabase forever
# ---------------------------------------------------------------------------
class CloudFilesTestCase(unittest.TestCase):
    def setUp(self):
        self.cloud = FakeTransport()
        self.client = RemoteClient(self.cloud, remote_config())
        self.client.auth.ensure_signed_in("fam")
        self.bucket = remote_config().bucket_project_files

    def add_cloud_job(self, state, station_id="RS-OTHER", age_seconds=3600):
        job = self.client.jobs.create_job(station_id, "Proj", family_code="fam")
        self.client.jobs.set_state(job.id, state)
        self.cloud.update("jobs", {"id": job.id},
                          {"completed_at": time.time() - age_seconds})
        self.cloud.upload(self.bucket, project_object_path(
            self.cloud.current_user_id, job.id, "Edit.prproj"), b"x" * 100)
        return job.id

    def cloud_files(self, job_id):
        return self.cloud.list_objects(
            self.bucket, f"user/{self.cloud.current_user_id}/jobs/{job_id}/")


class TestFamilyWideCloudSweep(CloudFilesTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.worker = RemoteStationWorker(
            self.client, AppConfig(workspace_dir=tmp.name, device_name="PC",
                                   family_code="fam"),
            backend=_IdleBackend())

    def test_old_failed_job_for_another_pc_is_cleaned(self):
        job_id = self.add_cloud_job(RemoteJobState.FAILED)
        self.worker._sweep_cleanup()
        self.assertEqual(self.cloud_files(job_id), [])

    def test_old_cancelled_job_is_cleaned(self):
        job_id = self.add_cloud_job(RemoteJobState.CANCELLED)
        self.worker._sweep_cleanup()
        self.assertEqual(self.cloud_files(job_id), [])

    def test_recently_failed_job_is_left_alone_for_now(self):
        job_id = self.add_cloud_job(RemoteJobState.FAILED, age_seconds=60)
        self.worker._sweep_cleanup()
        self.assertNotEqual(self.cloud_files(job_id), [])

    def test_result_waiting_for_the_sender_is_never_touched(self):
        job_id = self.add_cloud_job(RemoteJobState.READY_FOR_DOWNLOAD,
                                    age_seconds=99999)
        self.worker._sweep_cleanup()
        self.assertNotEqual(self.cloud_files(job_id), [])

    def test_jobs_still_in_progress_are_never_touched(self):
        for state in (RemoteJobState.UPLOADED, RemoteJobState.QUEUED,
                      RemoteJobState.RENDERING, RemoteJobState.DOWNLOADING):
            job_id = self.add_cloud_job(state, age_seconds=99999)
            self.worker._sweep_cleanup()
            self.assertNotEqual(self.cloud_files(job_id), [], state)


class TestSenderCleansUpAfterItself(CloudFilesTestCase):
    def test_cancelled_send_removes_its_uploaded_files(self):
        StationService(self.cloud, remote_config()).register(
            "RS-R", "Render PC", "3", family_code="fam", device_name="Render PC")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = Path(tmp.name) / "project"
        project.mkdir()
        (project / "Edit.prproj").write_bytes(b"p" * 500)

        uploaded = threading.Event()
        worker = RemoteSendWorker(
            self.client,
            RemoteSendRequest(station_id="RS-R", folder=project,
                              project_name="Proj", output_dir=Path(tmp.name),
                              family_code="fam"),
            on_state=lambda kind, data: uploaded.set() if kind == "uploaded" else None)
        worker.start()
        self.assertTrue(uploaded.wait(10), "upload never finished")
        self.assertNotEqual(self.cloud_files(worker.job_id), [])
        worker.cancel()
        worker.join(10)
        self.assertEqual(self.cloud_files(worker.job_id), [])


# ---------------------------------------------------------------------------
# 5 + 6. Error messages
# ---------------------------------------------------------------------------
class TestErrorMessages(unittest.TestCase):
    def test_storage_full_is_recognised(self):
        for raw in ("{'statusCode': 413, 'error': 'Payload too large', "
                    "'message': 'The object exceeded the maximum allowed size'}",
                    "402 Payment Required: usage limit exceeded"):
            self.assertIsInstance(SupabaseTransport._translate(Exception(raw)),
                                  QuotaExceededError, raw)

    def test_storage_full_message_explains_the_limit(self):
        message = QuotaExceededError.user_message
        self.assertIn("1 GB", message)
        self.assertIn("5 GB", message)

    def test_no_message_mentions_signing_in_or_passwords(self):
        # There is no sign-in screen; telling people to sign in sends them
        # looking for something that doesn't exist.
        for name in dir(transport_module):
            cls = getattr(transport_module, name)
            if isinstance(cls, type) and issubclass(cls, RemoteError):
                text = cls.user_message.lower()
                for banned in ("sign in", "log in", "password", "username"):
                    self.assertNotIn(banned, text, f"{name}: {cls.user_message}")


# ---------------------------------------------------------------------------
# 7. "&" in media paths
# ---------------------------------------------------------------------------
class TestAmpersandPaths(unittest.TestCase):
    @staticmethod
    def as_xml_file_link(path):
        # How a path appears inside the project XML as a file:// link:
        # spaces URL-encoded, "&" XML-escaped.
        return path.as_posix().replace(" ", "%20").replace("&", "&amp;")

    def make_project(self, root, media_path):
        # Premiere writes media locations as file:// links (or C:\\ paths).
        xml = (f"<PremiereData><Media><ActualMediaFilePath>file://{media_path}"
               "</ActualMediaFilePath></Media></PremiereData>").encode()
        prproj = root / "Edit.prproj"
        prproj.write_bytes(gzip.compress(xml))
        return prproj

    def test_file_inside_the_project_with_an_ampersand_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Tips & Tricks"
            root.mkdir()
            inside = root / "A & B.mov"
            inside.write_bytes(b"x")
            prproj = self.make_project(root, self.as_xml_file_link(inside))
            self.assertEqual(find_external_media(prproj, root), [])

    def test_external_file_is_reported_with_its_real_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Project"
            root.mkdir()
            outside = Path(tmp) / "Elsewhere" / "Q&A.mov"
            outside.parent.mkdir()
            outside.write_bytes(b"x")
            prproj = self.make_project(root, self.as_xml_file_link(outside))
            hits = find_external_media(prproj, root)
            self.assertEqual(len(hits), 1)
            self.assertIn("Q&A.mov", hits[0])
            self.assertNotIn("&amp;", hits[0])



class TestWindowsLinksCrossPlatform(unittest.TestCase):
    """Checks the path extraction itself, so it runs identically on Windows
    and Linux. The Windows-only failure was a C:/ path pattern matching
    INSIDE a file:///C:/... link, producing a second, undecoded path with
    "%20" in it that pointed at a folder that doesn't exist."""

    def test_windows_file_link_yields_one_decoded_path(self):
        from src.core.project_probe import _media_path_candidates
        xml = ("<M><ActualMediaFilePath>file:///C:/Users/bhavi/"
               "Tips%20&amp;%20Tricks/A%20&amp;%20B.mov</ActualMediaFilePath></M>")
        self.assertEqual(_media_path_candidates(xml),
                         ["C:/Users/bhavi/Tips & Tricks/A & B.mov"])

    def test_plain_windows_paths_are_still_found(self):
        from src.core.project_probe import _media_path_candidates
        xml = ("<M><ActualMediaFilePath>D:\\Footage\\Q&amp;A clip.mp4"
               "</ActualMediaFilePath></M>")
        self.assertEqual(_media_path_candidates(xml),
                         ["D:\\Footage\\Q&A clip.mp4"])

    def test_no_percent_encoded_path_ever_comes_out_of_a_link(self):
        from src.core.project_probe import _media_path_candidates
        xml = "<M>file:///E:/My%20Project/clip%20one.mov</M>"
        for path in _media_path_candidates(xml):
            self.assertNotIn("%20", path)


if __name__ == "__main__":
    unittest.main()
