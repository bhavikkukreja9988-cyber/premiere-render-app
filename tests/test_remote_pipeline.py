"""Phase 7: the remote station worker driving the *real* local render
pipeline (JobStore + RenderManager), and the remote sender worker, both talking
through the in-memory fake Supabase. This is the test that proves the cloud
plumbing and the existing V2 render machinery are actually wired together."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from src.core.config import AppConfig
from src.core.jobs import JobState
from src.remote.client import RemoteClient
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.models import RemoteJobState
from src.remote.sender_service import RemoteSendRequest, RemoteSendWorker
from src.remote.station_worker import RemoteStationWorker
from src.render.pipeline import RenderBackend

RENDERED_BYTES = b"FAKE-CLOUD-MP4" * 500


class FakeBackend(RenderBackend):
    name = "fake"

    def render(self, record, job_root, progress, cancel):
        progress(0.5, "pretending to encode")
        output = job_root / "output" / record.spec.output_filename()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(RENDERED_BYTES)
        progress(1.0, "done")
        return output


def make_config(**over) -> RemoteConfig:
    base = dict(url="https://example.supabase.co", publishable_key="pk",
                station_offline_after=5.0)
    base.update(over)
    return RemoteConfig(**base)


def make_client(transport: FakeTransport, remote_config: RemoteConfig,
                username: str) -> RemoteClient:
    client = RemoteClient(transport, remote_config)
    client.auth.sign_up(username, "pw1234")
    return client


def make_project(root: Path) -> None:
    (root / "footage").mkdir(parents=True)
    (root / "Edit.prproj").write_bytes(b"pretend project" * 100)
    (root / "footage" / "a.mov").write_bytes(b"a" * (1024 * 100))


class RemotePipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project = base / "project"
        self.project.mkdir()
        make_project(self.project)
        self.output_dir = base / "returned"
        self.output_dir.mkdir()

        self.remote_config = make_config()
        # One fake cloud shared by both "PCs" — exactly like one real Supabase
        # project shared over the internet by two machines.
        self.transport = FakeTransport()
        self.sender = make_client(self.transport, self.remote_config, "family")
        # Same account (a family shares one login), different local config
        # (as if this were a second physical PC).
        self.station_client = RemoteClient(self.transport, self.remote_config)
        self.station_client.auth.sign_in("family", "pw1234")

        self.station_config = AppConfig(
            workspace_dir=str(base / "station"),
            station_name="Family Render PC",
            accept_jobs_automatically=True,
        )
        self.worker = RemoteStationWorker(
            self.station_client, self.station_config, backend=FakeBackend())
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.addCleanup(self.tmp.cleanup)

    def _run_send(self, **overrides) -> RemoteSendWorker:
        defaults = dict(
            station_id=self.station_config.station_id,
            folder=self.project, project_name="MyVideo",
            output_dir=self.output_dir, output_name="MyVideo_final",
        )
        defaults.update(overrides)
        request = RemoteSendRequest(**defaults)
        worker = RemoteSendWorker(self.sender, request)
        worker.start()
        worker.join(timeout=30)
        self.assertFalse(worker.is_alive(), "send worker did not finish in time")
        return worker

    def test_full_cloud_round_trip_through_the_real_pipeline(self):
        worker = self._run_send()
        self.assertEqual(worker.error, "")
        self.assertIsNotNone(worker.result_path)
        result = Path(worker.result_path)
        self.assertTrue(result.is_file())
        self.assertEqual(result.name, "MyVideo_final.mp4")
        self.assertEqual(result.read_bytes(), RENDERED_BYTES)

        job = self.sender.jobs.get_job(worker.job_id)
        self.assertEqual(job.state, RemoteJobState.COMPLETE)

        # The real local pipeline actually ran: the station's own JobStore has
        # a completed record with the cloud job's id.
        local_record = self.worker.local_store.get(worker.job_id)
        self.assertIsNotNone(local_record)
        self.assertEqual(local_record.state, JobState.COMPLETE)
        self.assertEqual(local_record.label, job.display_label)

    def test_same_project_sent_three_times_makes_three_independent_renders(self):
        results = [self._run_send() for _ in range(3)]
        self.assertTrue(all(w.error == "" for w in results))
        job_ids = {w.job_id for w in results}
        self.assertEqual(len(job_ids), 3)
        labels = sorted(self.sender.jobs.get_job(jid).display_label
                        for jid in job_ids)
        self.assertEqual(labels, ["Job-001", "Job-002", "Job-003"])
        # Each render produced its own output file, none overwritten.
        for worker in results:
            self.assertTrue(Path(worker.result_path).is_file())

    def test_manual_acceptance_holds_until_operator_accepts(self):
        self.station_config.accept_jobs_automatically = False
        # Give the recovery loop a moment to see the flag flip naturally via a
        # fresh job rather than racing the already-running thread.
        worker = RemoteSendWorker(
            self.sender,
            RemoteSendRequest(station_id=self.station_config.station_id,
                              folder=self.project, project_name="Manual",
                              output_dir=self.output_dir))
        worker.start()

        # Wait for the job to reach WAITING_FOR_STATION.
        deadline = time.time() + 10
        job = None
        while time.time() < deadline:
            jobs = self.sender.jobs.list_jobs()
            if jobs and jobs[0].state is RemoteJobState.WAITING_FOR_STATION:
                job = jobs[0]
                break
            time.sleep(0.2)
        self.assertIsNotNone(job, "job never reached WAITING_FOR_STATION in time")
        self.assertEqual(job.state, RemoteJobState.WAITING_FOR_STATION)
        self.assertIn(job.id, self.worker.pending_manual)

        self.worker.accept_pending(job.id)
        worker.join(timeout=30)
        self.assertEqual(worker.error, "")
        self.assertTrue(Path(worker.result_path).is_file())

    def test_cancel_before_pickup_is_reflected_locally(self):
        self.station_config.accept_jobs_automatically = False
        worker = RemoteSendWorker(
            self.sender,
            RemoteSendRequest(station_id=self.station_config.station_id,
                              folder=self.project, project_name="ToCancel",
                              output_dir=self.output_dir))
        worker.start()
        deadline = time.time() + 10
        job = None
        while time.time() < deadline:
            jobs = self.sender.jobs.list_jobs()
            if jobs and jobs[0].state is RemoteJobState.WAITING_FOR_STATION:
                job = jobs[0]
                break
            time.sleep(0.2)
        self.assertIsNotNone(job, "job never reached WAITING_FOR_STATION in time")
        self.worker.reject_pending(job.id)
        worker.join(timeout=10)
        self.assertEqual(
            self.sender.jobs.get_job(job.id).state, RemoteJobState.CANCELLED)

    def test_cleanup_removes_cloud_objects_after_delivery(self):
        worker = self._run_send()
        job_id = worker.job_id
        # Give the cleanup sweep a chance (poll interval is shortened below).
        self.worker._sweep_cleanup()
        remaining = self.transport.list_objects(
            self.remote_config.bucket_project_files,
            f"user/{self.sender.user_id}/jobs/{job_id}/")
        self.assertEqual(remaining, [])

    def test_delete_after_delivery_removes_local_workspace_too(self):
        worker = self._run_send(delete_after_delivery=True)
        job_id = worker.job_id
        from src.core import workspace as ws
        job_dir = ws.job_dir(self.station_config.workspace, job_id)
        self.assertTrue(job_dir.exists())
        self.worker._sweep_cleanup()
        self.assertFalse(job_dir.exists())
        self.assertIsNone(self.worker.local_store.get(job_id))


class ChunkedTransferThroughPipelineTest(unittest.TestCase):
    """Proves the chunking mechanism is actually reachable through the real
    Sender -> Station flow, not just correct in isolation (test_chunked_
    transfer.py covers the mechanism itself in detail)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project = base / "project"
        self.project.mkdir()
        (self.project / "Edit.prproj").write_bytes(b"pretend project" * 50)
        # A "large" media file — large only relative to the tiny threshold
        # this test configures below, not actually multi-megabyte.
        (self.project / "big_clip.mov").write_bytes(os.urandom(20_000))
        self.output_dir = base / "returned"
        self.output_dir.mkdir()

        self.remote_config = make_config()
        self.transport = FakeTransport()
        self.sender = make_client(self.transport, self.remote_config, "family")
        self.station_client = RemoteClient(self.transport, self.remote_config)
        self.station_client.auth.sign_in("family", "pw1234")

        # Force chunking to actually trigger without needing a real
        # multi-megabyte fixture file.
        from src.remote.storage import StorageService
        tiny_kwargs = dict(chunk_size=4_000, chunk_threshold=1_000)
        self.sender.storage = StorageService(self.transport, self.remote_config,
                                             **tiny_kwargs)
        self.station_client.storage = StorageService(self.transport,
                                                      self.remote_config,
                                                      **tiny_kwargs)

        self.station_config = AppConfig(
            workspace_dir=str(base / "station"),
            station_name="Family Render PC",
            accept_jobs_automatically=True,
        )
        self.worker = RemoteStationWorker(
            self.station_client, self.station_config, backend=FakeBackend())
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_large_media_file_is_chunked_and_survives_the_round_trip(self):
        request = RemoteSendRequest(
            station_id=self.station_config.station_id, folder=self.project,
            project_name="ChunkedVideo", output_dir=self.output_dir,
            output_name="ChunkedVideo_final")
        worker = RemoteSendWorker(self.sender, request)
        worker.start()
        worker.join(timeout=30)

        self.assertEqual(worker.error, "")
        self.assertTrue(Path(worker.result_path).is_file())
        self.assertEqual(Path(worker.result_path).read_bytes(), RENDERED_BYTES)

        original = (self.project / "big_clip.mov").read_bytes()
        received = (Path(self.station_config.workspace_dir) / "jobs" /
                   worker.job_id / "project" / "big_clip.mov")
        self.assertEqual(received.read_bytes(), original,
                         "chunked file must reassemble byte-exact on the station")

        # Prove chunking genuinely happened, rather than silently falling
        # back to a whole-file transfer.
        objects = self.transport.list_objects(
            self.remote_config.bucket_project_files,
            f"user/{self.sender.user_id}/jobs/{worker.job_id}/project/big_clip.mov")
        self.assertTrue(any(o.endswith(".manifest.json") for o in objects),
                        "expected a chunk manifest for the large file")
        self.assertTrue(any(".part" in o for o in objects),
                        "expected chunk parts for the large file")

        # The small .prproj file should NOT have been chunked.
        prproj_objects = self.transport.list_objects(
            self.remote_config.bucket_project_files,
            f"user/{self.sender.user_id}/jobs/{worker.job_id}/project/Edit.prproj")
        self.assertEqual(len(prproj_objects), 1)
        self.assertFalse(prproj_objects[0].endswith(".manifest.json"))


if __name__ == "__main__":
    unittest.main()
