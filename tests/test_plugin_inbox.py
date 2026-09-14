"""Tests for the Premiere plugin inbox hand-off."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.core import plugin_inbox
from src.core.plugin_inbox import PluginJobRequest


class InboxTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        patcher = mock.patch.object(plugin_inbox, "inbox_dir",
                                    return_value=self.inbox)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_job(self, name="job-1.json", **fields):
        payload = {
            "source": "premiere-uxp-plugin",
            "project_path": str(self.root / "Edit.prproj"),
            "project_name": "Edit.prproj",
            "sequence": "Main",
            "station_id": "RS-1",
            "preset": "H.264",
            "output_name": "out",
        }
        payload.update(fields)
        path = self.inbox / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class TestReadPending(InboxTestCase):
    def test_reads_a_well_formed_job(self):
        (self.root / "Edit.prproj").write_bytes(b"x")
        self.write_job()
        pending = plugin_inbox.read_pending()
        self.assertEqual(len(pending), 1)
        request = pending[0]
        self.assertEqual(request.sequence, "Main")
        self.assertEqual(request.station_id, "RS-1")
        self.assertTrue(request.valid)

    def test_project_folder_is_the_prproj_parent(self):
        project = self.root / "MyEdit" / "Edit.prproj"
        project.parent.mkdir()
        project.write_bytes(b"x")
        self.write_job(project_path=str(project))
        request = plugin_inbox.read_pending()[0]
        self.assertEqual(request.project_folder, project.parent)

    def test_missing_project_file_is_not_valid(self):
        self.write_job(project_path=str(self.root / "gone.prproj"))
        request = plugin_inbox.read_pending()[0]
        self.assertFalse(request.valid)

    def test_non_prproj_is_not_valid(self):
        other = self.root / "notes.txt"
        other.write_bytes(b"x")
        self.write_job(project_path=str(other))
        self.assertFalse(plugin_inbox.read_pending()[0].valid)

    def test_unreadable_file_is_discarded_not_raised(self):
        bad = self.inbox / "job-bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        self.assertEqual(plugin_inbox.read_pending(), [])
        self.assertFalse(bad.exists())

    def test_tmp_files_are_ignored(self):
        # The plugin writes .tmp then renames; a .tmp must never be read as
        # a complete job.
        (self.inbox / "job-99.tmp").write_text("{}", encoding="utf-8")
        self.assertEqual(plugin_inbox.read_pending(), [])

    def test_stale_jobs_are_discarded(self):
        path = self.write_job()
        old = time.time() - (plugin_inbox.MAX_AGE_SECONDS + 60)
        os.utime(path, (old, old))
        self.assertEqual(plugin_inbox.read_pending(), [])
        self.assertFalse(path.exists())

    def test_jobs_are_returned_oldest_first(self):
        (self.root / "Edit.prproj").write_bytes(b"x")
        self.write_job("job-1.json", sequence="First")
        self.write_job("job-2.json", sequence="Second")
        pending = plugin_inbox.read_pending()
        self.assertEqual([r.sequence for r in pending], ["First", "Second"])

    def test_missing_inbox_returns_empty(self):
        for entry in self.inbox.iterdir():
            entry.unlink()
        self.inbox.rmdir()
        self.assertEqual(plugin_inbox.read_pending(), [])


class TestConsume(InboxTestCase):
    def test_consume_removes_the_file(self):
        (self.root / "Edit.prproj").write_bytes(b"x")
        path = self.write_job()
        request = plugin_inbox.read_pending()[0]
        plugin_inbox.consume(request)
        self.assertFalse(path.exists())

    def test_consume_without_source_file_is_safe(self):
        plugin_inbox.consume(PluginJobRequest(project_path="x"))


class TestWatcher(InboxTestCase):
    def test_watcher_delivers_and_consumes(self):
        (self.root / "Edit.prproj").write_bytes(b"x")
        self.write_job()
        seen = []
        watcher = plugin_inbox.PluginInboxWatcher(lambda r: seen.append(r))
        watcher.start()
        deadline = time.time() + 10
        while time.time() < deadline and not seen:
            time.sleep(0.1)
        watcher.stop()
        self.assertEqual(len(seen), 1)
        self.assertEqual(list(self.inbox.glob("job-*.json")), [])

    def test_handler_failure_still_consumes(self):
        # A request that crashes the handler must not retry forever.
        (self.root / "Edit.prproj").write_bytes(b"x")
        self.write_job()
        calls = []

        def boom(request):
            calls.append(request)
            raise RuntimeError("handler exploded")

        watcher = plugin_inbox.PluginInboxWatcher(boom)
        watcher.start()
        deadline = time.time() + 10
        while time.time() < deadline and not calls:
            time.sleep(0.1)
        time.sleep(0.3)
        watcher.stop()
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(self.inbox.glob("job-*.json")), [])


if __name__ == "__main__":
    unittest.main()
