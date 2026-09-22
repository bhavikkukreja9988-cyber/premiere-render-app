"""Tests for the spec's job-identity, repeated-send and retention rules."""

import tempfile
import time
import unittest
from pathlib import Path

from src.core.jobs import JobRecord, JobSpec, JobState, JobStore
from src.core.retention import RetentionManager, eligible_for_deletion


class TestJobIdentity(unittest.TestCase):
    def test_each_spec_gets_a_unique_id(self):
        # Sending the same project repeatedly must yield distinct job ids.
        ids = {JobSpec(name="MyVideo").job_id for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_store_assigns_sequential_labels(self):
        store = JobStore()
        a = store.add(JobRecord(spec=JobSpec(name="MyVideo")))
        b = store.add(JobRecord(spec=JobSpec(name="MyVideo")))
        c = store.add(JobRecord(spec=JobSpec(name="MyVideo")))
        self.assertEqual([a.label, b.label, c.label],
                         ["Job-001", "Job-002", "Job-003"])
        self.assertEqual(len({a.job_id, b.job_id, c.job_id}), 3)

    def test_counter_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            store = JobStore(path)
            store.add(JobRecord(spec=JobSpec(name="a")))
            store.add(JobRecord(spec=JobSpec(name="b")))
            reloaded = JobStore(path)
            nxt = reloaded.add(JobRecord(spec=JobSpec(name="c")))
            self.assertEqual(nxt.label, "Job-003")

    def test_state_json_is_written_per_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.json", jobs_root=root / "jobs")
            record = store.add(JobRecord(spec=JobSpec(name="x")))
            state = root / "jobs" / record.label / "state.json"
            self.assertTrue(state.is_file())

    def test_display_label_falls_back_without_a_label(self):
        record = JobRecord(spec=JobSpec(job_id="abcdef0123456789"))
        self.assertEqual(record.display_label, "Job-abcdef01")


class TestRetention(unittest.TestCase):
    def _record(self, state, days_ago=10, job_id="j"):
        record = JobRecord(spec=JobSpec(job_id=job_id, name="n"), state=state)
        record.completed_at = time.time() - days_ago * 86400
        return record

    def test_only_completed_and_old_are_eligible(self):
        self.assertTrue(eligible_for_deletion(self._record(JobState.COMPLETE), 7))
        self.assertFalse(eligible_for_deletion(self._record(JobState.COMPLETE, 3), 7))

    def test_never_when_retention_is_zero(self):
        self.assertFalse(eligible_for_deletion(self._record(JobState.COMPLETE), 0))

    def test_in_progress_states_are_never_auto_deleted(self):
        # Anything not finished stays put no matter how old — it might still
        # be in use. A genuinely stuck job is cleared by hand instead.
        for state in (JobState.RENDERING, JobState.TRANSFERRING, JobState.QUEUED,
                      JobState.RETURNING, JobState.ENCODED, JobState.CREATED):
            self.assertFalse(eligible_for_deletion(self._record(state, 365), 7),
                             state)

    def test_failed_and_cancelled_jobs_are_deleted_after_retention(self):
        # These used to be kept forever and silently filled the drive with
        # full copies of projects that were never rendered.
        for state in (JobState.FAILED, JobState.CANCELLED):
            self.assertTrue(eligible_for_deletion(self._record(state, 10), 7),
                            state)

    def test_recent_failures_are_kept_for_the_retention_window(self):
        # The window is the grace period for inspecting what went wrong.
        for state in (JobState.FAILED, JobState.CANCELLED):
            self.assertFalse(eligible_for_deletion(self._record(state, 3), 7),
                             state)

    def test_failed_jobs_follow_never_delete_too(self):
        self.assertFalse(eligible_for_deletion(self._record(JobState.FAILED, 999), 0))

    def test_currently_rendering_job_is_protected(self):
        record = self._record(JobState.COMPLETE, job_id="busy")
        self.assertFalse(
            eligible_for_deletion(record, 7, protected_job_id="busy"))

    def test_sweep_removes_only_eligible_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.json", jobs_root=root / "jobs")
            old = store.add(JobRecord(spec=JobSpec(name="old"),
                                      state=JobState.COMPLETE))
            old.completed_at = time.time() - 30 * 86400
            old_failed = store.add(JobRecord(spec=JobSpec(name="old failed"),
                                             state=JobState.FAILED))
            old_failed.completed_at = time.time() - 30 * 86400
            new_failed = store.add(JobRecord(spec=JobSpec(name="new failed"),
                                             state=JobState.FAILED))
            new_failed.completed_at = time.time() - 1 * 86400
            stuck = store.add(JobRecord(spec=JobSpec(name="stuck"),
                                        state=JobState.RENDERING))
            stuck.updated_at = time.time() - 90 * 86400
            removed_dirs = []
            manager = RetentionManager(
                store, root, lambda: 7,
                lambda job_id: removed_dirs.append(job_id),
                lambda: None)
            removed = manager.sweep()
            self.assertEqual(sorted(removed),
                             sorted([old.display_label, old_failed.display_label]))
            self.assertIsNone(store.get(old.job_id))
            self.assertIsNone(store.get(old_failed.job_id))
            self.assertIsNotNone(store.get(new_failed.job_id))
            self.assertIsNotNone(store.get(stuck.job_id))


if __name__ == "__main__":
    unittest.main()
