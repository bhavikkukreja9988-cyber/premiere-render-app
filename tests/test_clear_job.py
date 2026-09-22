"""Clearing received jobs on the Render Station.

Covers the hand-operated "Clear selected job" / "Cancel render" actions and
the retention sweep's handling of failed jobs. Runs against a real
RemoteStationWorker, JobStore and workspace on disk, with the in-memory fake
Supabase standing in for the cloud.

The worker is deliberately NOT started in most tests: clearing doesn't need
the background threads, and leaving them off keeps every test deterministic.
"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.core import workspace
from src.core.config import AppConfig
from src.core.jobs import JobRecord, JobSpec, JobState
from src.remote.client import RemoteClient
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport
from src.remote.models import RemoteJobState
from src.remote.station_worker import RemoteStationWorker
from src.remote.storage import project_object_path
from src.remote.transport import OfflineError
from src.render.pipeline import RenderBackend


class _IdleBackend(RenderBackend):
    name = "idle"

    def render(self, record, job_root, progress, cancel):        # pragma: no cover
        raise AssertionError("render should not run in these tests")


class ClearJobTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)

        self.remote_config = RemoteConfig(url="https://x.supabase.co",
                                          publishable_key="pk",
                                          station_offline_after=45.0)
        self.transport = FakeTransport()
        self.client = RemoteClient(self.transport, self.remote_config)
        self.client.auth.ensure_signed_in("test-family")

        self.config = AppConfig(workspace_dir=str(base / "station"),
                                station_name="Render PC",
                                device_name="Render PC",
                                family_code="test-family",
                                retention_days=7)
        self.worker = RemoteStationWorker(self.client, self.config,
                                          backend=_IdleBackend())
        self.project_bucket = self.remote_config.bucket_project_files

    # -- helpers ----------------------------------------------------------
    def seed_job(self, cloud_state=RemoteJobState.QUEUED,
                 local_state=JobState.QUEUED, name="MyVideo"):
        """A job that exists in the cloud, on disk, and in the local store."""
        remote = self.client.jobs.create_job(self.config.station_id, name,
                                             family_code="test-family")
        self.client.jobs.set_state(remote.id, cloud_state)

        record = JobRecord(spec=JobSpec(job_id=remote.id, name=name),
                           state=local_state)
        self.worker.local_store.add(record)

        job_root = workspace.job_dir(self.config.workspace, remote.id)
        (job_root / "project").mkdir(parents=True)
        (job_root / "project" / "Edit.prproj").write_bytes(b"x" * 2048)

        self.transport.upload(
            self.project_bucket,
            project_object_path(self.transport.current_user_id, remote.id,
                                "Edit.prproj"),
            b"x" * 2048)
        return remote.id

    def job_dir_exists(self, job_id):
        return workspace.job_dir(self.config.workspace, job_id).exists()

    def cloud_files(self, job_id):
        prefix = f"user/{self.transport.current_user_id}/jobs/{job_id}/"
        return self.transport.list_objects(self.project_bucket, prefix)


class TestClearJob(ClearJobTestCase):
    def test_clears_local_folder_store_record_and_cloud_files(self):
        job_id = self.seed_job()
        ok, _ = self.worker.clear_job(job_id)
        self.assertTrue(ok)
        self.assertFalse(self.job_dir_exists(job_id))
        self.assertIsNone(self.worker.local_store.get(job_id))
        self.assertEqual(self.cloud_files(job_id), [])

    def test_stuck_job_is_not_downloaded_again_afterwards(self):
        # The important one: a job left "queued" in the cloud is exactly what
        # the recovery loop re-downloads. Clearing must stop that.
        job_id = self.seed_job(cloud_state=RemoteJobState.QUEUED)
        self.worker.clear_job(job_id)
        pending = [j.id for j in
                   self.client.jobs.pending_for_station(self.config.station_id)]
        self.assertNotIn(job_id, pending)

    def test_sender_is_told_why_and_can_retry(self):
        # FAILED (not CANCELLED) so the sender shows the reason + Retry.
        job_id = self.seed_job(cloud_state=RemoteJobState.RENDERING,
                               local_state=JobState.RENDERING)
        self.worker.clear_job(job_id)
        remote = self.client.jobs.get_job(job_id)
        self.assertIs(remote.state, RemoteJobState.FAILED)
        self.assertIn("Cleared on the render station", remote.error)
        self.assertIn("Render PC", remote.error)

    def test_already_finished_cloud_job_is_left_as_it_was(self):
        job_id = self.seed_job(cloud_state=RemoteJobState.COMPLETE,
                               local_state=JobState.COMPLETE)
        ok, _ = self.worker.clear_job(job_id)
        self.assertTrue(ok)
        self.assertIs(self.client.jobs.get_job(job_id).state,
                      RemoteJobState.COMPLETE)

    def test_refuses_the_job_that_is_rendering_right_now(self):
        job_id = self.seed_job(local_state=JobState.RENDERING)
        self.worker.manager._current = job_id
        ok, message = self.worker.clear_job(job_id)
        self.assertFalse(ok)
        self.assertIn("Cancel it first", message)
        self.assertTrue(self.job_dir_exists(job_id))
        self.assertIsNotNone(self.worker.local_store.get(job_id))

    def test_refuses_a_job_that_is_still_downloading(self):
        job_id = self.seed_job(local_state=JobState.TRANSFERRING)
        self.worker._downloading[job_id] = True
        ok, message = self.worker.clear_job(job_id)
        self.assertFalse(ok)
        self.assertIn("downloading", message)
        self.assertTrue(self.job_dir_exists(job_id))

    def test_nothing_is_deleted_if_the_cloud_cannot_be_reached(self):
        # Deleting locally while the cloud still says "queued" would make the
        # job silently come back, so the whole clear must be refused.
        job_id = self.seed_job()
        with mock.patch.object(self.client.jobs, "get_job",
                               side_effect=OfflineError("offline")):
            ok, message = self.worker.clear_job(job_id)
        self.assertFalse(ok)
        self.assertIn("nothing was deleted", message)
        self.assertTrue(self.job_dir_exists(job_id))
        self.assertIsNotNone(self.worker.local_store.get(job_id))

    def test_nothing_is_deleted_if_the_cloud_update_fails(self):
        job_id = self.seed_job()
        with mock.patch.object(self.client.jobs, "set_state",
                               side_effect=OfflineError("offline")):
            ok, message = self.worker.clear_job(job_id)
        self.assertFalse(ok)
        self.assertTrue(self.job_dir_exists(job_id))

    def test_job_missing_from_the_cloud_still_clears_locally(self):
        # E.g. the cloud row was already removed: local disk space is still
        # worth getting back.
        record = JobRecord(spec=JobSpec(job_id="orphan-job", name="Orphan"),
                           state=JobState.FAILED)
        self.worker.local_store.add(record)
        job_root = workspace.job_dir(self.config.workspace, "orphan-job")
        job_root.mkdir(parents=True)
        ok, _ = self.worker.clear_job("orphan-job")
        self.assertTrue(ok)
        self.assertFalse(job_root.exists())

    def test_clearing_a_pending_manual_job_forgets_it(self):
        job_id = self.seed_job(cloud_state=RemoteJobState.WAITING_FOR_STATION)
        self.worker.pending_manual[job_id] = self.client.jobs.get_job(job_id)
        self.worker.clear_job(job_id)
        self.assertNotIn(job_id, self.worker.pending_manual)


class TestCancelJob(ClearJobTestCase):
    def test_cancels_the_job_that_is_rendering(self):
        job_id = self.seed_job(local_state=JobState.RENDERING)
        self.worker.manager._current = job_id
        ok, _ = self.worker.cancel_job(job_id)
        self.assertTrue(ok)
        self.assertTrue(self.worker.manager._cancelled.get(job_id))

    def test_cannot_cancel_a_job_that_is_not_rendering(self):
        job_id = self.seed_job()
        ok, _ = self.worker.cancel_job(job_id)
        self.assertFalse(ok)


class TestJobListing(ClearJobTestCase):
    def test_lists_newest_first(self):
        first = self.seed_job(name="First")
        time.sleep(0.01)
        second = self.seed_job(name="Second")
        self.worker.local_store.update(second, message="touched")
        ids = [r.job_id for r in self.worker.list_local_jobs()]
        self.assertEqual(ids[0], second)
        self.assertIn(first, ids)

    def test_is_active_while_rendering_or_downloading(self):
        job_id = self.seed_job()
        self.assertFalse(self.worker.is_active(job_id))
        self.worker._downloading[job_id] = True
        self.assertTrue(self.worker.is_active(job_id))
        self.worker._downloading.pop(job_id)
        self.worker.manager._current = job_id
        self.assertTrue(self.worker.is_active(job_id))


class TestRetentionSweepOnStation(ClearJobTestCase):
    def test_old_failed_job_is_removed_locally_and_from_the_cloud(self):
        job_id = self.seed_job(cloud_state=RemoteJobState.FAILED,
                               local_state=JobState.FAILED)
        self.worker.local_store.get(job_id).completed_at = time.time() - 30 * 86400
        self.worker.retention.sweep()
        self.assertIsNone(self.worker.local_store.get(job_id))
        self.assertFalse(self.job_dir_exists(job_id))
        self.assertEqual(self.cloud_files(job_id), [])

    def test_recent_failed_job_is_kept(self):
        job_id = self.seed_job(cloud_state=RemoteJobState.FAILED,
                               local_state=JobState.FAILED)
        self.worker.local_store.get(job_id).completed_at = time.time() - 86400
        self.worker.retention.sweep()
        self.assertIsNotNone(self.worker.local_store.get(job_id))
        self.assertTrue(self.job_dir_exists(job_id))

    def test_stuck_job_is_never_swept_automatically(self):
        job_id = self.seed_job(local_state=JobState.RENDERING)
        record = self.worker.local_store.get(job_id)
        record.updated_at = time.time() - 365 * 86400
        self.worker.retention.sweep()
        self.assertIsNotNone(self.worker.local_store.get(job_id))


if __name__ == "__main__":
    unittest.main()
