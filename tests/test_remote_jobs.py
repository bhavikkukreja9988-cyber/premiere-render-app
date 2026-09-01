"""Tests for remote jobs, repeated sends, storage, the send gate, and a full
cloud round trip — all against the in-memory fake transport."""

import tempfile
import unittest
from pathlib import Path

from src.core.manifest import scan_folder
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.auth import AuthService
from src.remote.jobs import RemoteJobService
from src.remote.models import RemoteJobState, Station
from src.remote.send_gate import evaluate_send
from src.remote.stations import StationService
from src.remote.storage import StorageService


def make_config(**over) -> RemoteConfig:
    base = dict(url="https://example.supabase.co", publishable_key="pk",
                station_offline_after=1.0)
    base.update(over)
    return RemoteConfig(**base)


def signed_in_services(config):
    transport = FakeTransport()
    auth = AuthService(transport, config)
    auth.sign_up("owner", "pw12")
    return (transport,
            StationService(transport, config),
            RemoteJobService(transport, config),
            StorageService(transport, config))


class TestRemoteJobs(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        (self.transport, self.stations, self.jobs,
         self.storage) = signed_in_services(self.config)
        self.stations.register("RS-1", "Render PC", "2.0.0")

    def test_same_project_sent_three_times_makes_three_jobs(self):
        made = [self.jobs.create_job("RS-1", "MyVideo") for _ in range(3)]
        self.assertEqual([j.display_label for j in made],
                         ["Job-001", "Job-002", "Job-003"])
        self.assertEqual(len({j.id for j in made}), 3)
        # Never rejected, all present in history.
        self.assertEqual(len(self.jobs.list_jobs()), 3)

    def test_job_state_transitions_record_events(self):
        job = self.jobs.create_job("RS-1", "MyVideo")
        self.jobs.set_state(job.id, RemoteJobState.RENDERING, message="go")
        self.jobs.set_state(job.id, RemoteJobState.COMPLETE, message="done")
        refreshed = self.jobs.get_job(job.id)
        self.assertEqual(refreshed.state, RemoteJobState.COMPLETE)
        self.assertTrue(refreshed.started_at > 0 and refreshed.completed_at > 0)
        types = [e.event_type for e in self.jobs.list_events(job.id)]
        self.assertIn("rendering", types)
        self.assertIn("complete", types)

    def test_pending_for_station_recoverable_only(self):
        a = self.jobs.create_job("RS-1", "A")
        b = self.jobs.create_job("RS-1", "B")
        self.jobs.set_state(a.id, RemoteJobState.UPLOADED)
        self.jobs.set_state(b.id, RemoteJobState.COMPLETE)
        pending = {j.id for j in self.jobs.pending_for_station("RS-1")}
        self.assertIn(a.id, pending)
        self.assertNotIn(b.id, pending)

    def test_jobs_isolated_between_users(self):
        self.jobs.create_job("RS-1", "Secret")
        other_auth = AuthService(self.transport, self.config)
        other_auth.sign_up("stranger", "pw12")
        other_jobs = RemoteJobService(self.transport, self.config)
        self.assertEqual(other_jobs.list_jobs(), [])

    def test_realtime_fires_on_new_job(self):
        seen = []
        self.jobs.watch_station_jobs("RS-1",
                                     lambda ev, job: seen.append((ev, job.id)))
        job = self.jobs.create_job("RS-1", "MyVideo")
        self.assertTrue(any(jid == job.id for _, jid in seen))

    def test_queue_position_counts_earlier_active_jobs_on_the_same_station(self):
        a = self.jobs.create_job("RS-1", "A")
        b = self.jobs.create_job("RS-1", "B")
        c = self.jobs.create_job("RS-1", "C")
        self.jobs.set_state(a.id, RemoteJobState.QUEUED)
        self.jobs.set_state(b.id, RemoteJobState.RENDERING)
        self.jobs.set_state(c.id, RemoteJobState.QUEUED)
        # c was created after both a and b, so both count as ahead of it.
        self.assertEqual(self.jobs.queue_position(c.id), 2)
        # a was created before b and c, so nothing counts as ahead of it.
        self.assertEqual(self.jobs.queue_position(a.id), 0)

    def test_queue_position_ignores_jobs_not_actively_queued_or_rendering(self):
        a = self.jobs.create_job("RS-1", "A")
        b = self.jobs.create_job("RS-1", "B")
        self.jobs.set_state(a.id, RemoteJobState.COMPLETE)
        self.jobs.set_state(b.id, RemoteJobState.QUEUED)
        self.assertEqual(self.jobs.queue_position(b.id), 0)

    def test_queue_position_ignores_other_stations(self):
        self.stations.register("RS-2", "Other PC", "2.0.0")
        a = self.jobs.create_job("RS-1", "A")
        b = self.jobs.create_job("RS-2", "B")
        self.jobs.set_state(a.id, RemoteJobState.QUEUED)
        self.jobs.set_state(b.id, RemoteJobState.QUEUED)
        self.assertEqual(self.jobs.queue_position(b.id), 0)

    def test_queue_position_of_unknown_job_is_zero(self):
        self.assertEqual(self.jobs.queue_position("does-not-exist"), 0)


class TestSendGate(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def _online_station(self):
        import time
        return Station(id="RS-1", name="PC", last_seen=time.time())

    def _offline_station(self):
        import time
        return Station(id="RS-1", name="PC", last_seen=time.time() - 100)

    def test_blocked_until_signed_in(self):
        gate = evaluate_send(signed_in=False, project_selected=True,
                             project_validated=True,
                             station=self._online_station(), config=self.config)
        self.assertFalse(gate.can_send)

    def test_blocked_when_offline_station(self):
        gate = evaluate_send(signed_in=True, project_selected=True,
                             project_validated=True,
                             station=self._offline_station(), config=self.config)
        self.assertFalse(gate.can_send)
        self.assertIn("offline", gate.reason.lower())

    def test_blocked_without_project(self):
        gate = evaluate_send(signed_in=True, project_selected=False,
                             project_validated=False,
                             station=self._online_station(), config=self.config)
        self.assertFalse(gate.can_send)

    def test_enabled_when_all_conditions_met(self):
        gate = evaluate_send(signed_in=True, project_selected=True,
                             project_validated=True,
                             station=self._online_station(), config=self.config)
        self.assertTrue(gate.can_send)
        self.assertEqual(gate.reason, "")


class TestCloudRoundTrip(unittest.TestCase):
    """Sender uploads -> station downloads -> station uploads result ->
    sender downloads result, all through the shared fake cloud."""

    def test_full_round_trip(self):
        config = make_config()
        transport = FakeTransport()
        auth = AuthService(transport, config)
        auth.sign_up("family", "pw12")

        stations = StationService(transport, config)
        jobs = RemoteJobService(transport, config)
        storage = StorageService(transport, config)
        stations.register("RS-1", "Render PC", "2.0.0")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "Edit.prproj").write_bytes(b"prproj" * 50)
            (project / "clip.mov").write_bytes(b"video-bytes" * 100)
            entries = scan_folder(project)

            # Sender creates the job and uploads the project.
            job = jobs.create_job("RS-1", "MyVideo", output_name="MyVideo")
            jobs.set_state(job.id, RemoteJobState.UPLOADING)
            storage.upload_project(job.id, project, entries)
            for e in entries:
                jobs.add_file(job.id, e.path, e.size, e.sha256,
                              f"user/{auth.user_id}/jobs/{job.id}/project/{e.path}")
            jobs.set_state(job.id, RemoteJobState.UPLOADED)

            # Station downloads into its own workspace and verifies hashes.
            station_ws = root / "station" / job.id / "project"
            storage.download_project(job.id, entries, station_ws)
            for e in entries:
                self.assertEqual((station_ws / e.path).read_bytes(),
                                 (project / e.path).read_bytes())

            # Station "renders" and uploads the result.
            output = root / "station" / job.id / "output" / "MyVideo.mp4"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"FAKE-MP4" * 200)
            jobs.set_state(job.id, RemoteJobState.RENDERING)
            storage.upload_result(job.id, output)
            jobs.set_state(job.id, RemoteJobState.READY_FOR_DOWNLOAD,
                           output_filename="MyVideo.mp4")

            # Sender downloads the result.
            dest = root / "returned"
            returned = storage.download_result(job.id, "MyVideo.mp4", dest)
            self.assertEqual(returned.read_bytes(), output.read_bytes())
            jobs.set_state(job.id, RemoteJobState.COMPLETE)

            # Cleanup removes cloud objects safely.
            storage.remove_job_objects(job.id)
            self.assertEqual(
                transport.list_objects(config.bucket_project_files,
                                       f"user/{auth.user_id}/jobs/{job.id}/"),
                [])

        self.assertEqual(jobs.get_job(job.id).state, RemoteJobState.COMPLETE)


if __name__ == "__main__":
    unittest.main()
