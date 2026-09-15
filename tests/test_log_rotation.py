"""Tests for per-run log rotation.

The point of this behaviour: when something goes wrong, the user clicks
"Save log to file…" and sends one file. That file must contain exactly the
run that went wrong — not months of accumulated history, and not a log that
was silently truncated mid-run by a size limit.
"""

import importlib
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class LogRotationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._detach_handlers)

    def _detach_handlers(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            try:
                handler.close()
            except Exception:                                # noqa: BLE001
                pass
            root.removeHandler(handler)

    def run_app_launch(self, message: str):
        """Simulate one complete app launch that writes one log line."""
        self._detach_handlers()
        import src.core.log as log
        importlib.reload(log)
        with mock.patch.object(log, "app_data_dir", return_value=self.root):
            log._configured = False
            log.setup_logging("INFO")
            log.get_logger("test").info(message)
            for handler in logging.getLogger().handlers:
                handler.flush()

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def read(self, name: str) -> str:
        return (self.logs_dir / name).read_text(encoding="utf-8")


class TestFreshLogPerRun(LogRotationTestCase):
    def test_first_run_creates_the_log(self):
        self.run_app_launch("first run")
        self.assertTrue((self.logs_dir / "app.log").is_file())
        self.assertIn("first run", self.read("app.log"))

    def test_second_run_starts_a_clean_log(self):
        # The whole point: a log sent for diagnosis covers ONE run.
        self.run_app_launch("first run")
        self.run_app_launch("second run")
        current = self.read("app.log")
        self.assertIn("second run", current)
        self.assertNotIn("first run", current)

    def test_previous_run_is_kept_as_a_backup(self):
        # The crash you care about often happened just before the restart.
        self.run_app_launch("first run")
        self.run_app_launch("second run")
        self.assertIn("first run", self.read("app-previous.log"))

    def test_only_two_log_files_ever_accumulate(self):
        for i in range(5):
            self.run_app_launch(f"run {i}")
        files = sorted(p.name for p in self.logs_dir.iterdir())
        self.assertEqual(files, ["app-previous.log", "app.log"])

    def test_backup_always_holds_the_immediately_previous_run(self):
        self.run_app_launch("run one")
        self.run_app_launch("run two")
        self.run_app_launch("run three")
        self.assertIn("run two", self.read("app-previous.log"))
        self.assertNotIn("run one", self.read("app-previous.log"))
        self.assertIn("run three", self.read("app.log"))

    def test_log_starts_with_a_version_banner(self):
        # Makes it obvious which build produced a log that gets sent in.
        self.run_app_launch("hello")
        self.assertIn("FileSender", self.read("app.log"))
        self.assertIn("starting", self.read("app.log"))


class TestLogPaths(LogRotationTestCase):
    def test_path_helpers_point_at_the_right_files(self):
        import src.core.log as log
        importlib.reload(log)
        with mock.patch.object(log, "app_data_dir", return_value=self.root):
            self.assertEqual(log.log_file_path().name, "app.log")
            self.assertEqual(log.previous_log_file_path().name,
                             "app-previous.log")
            self.assertEqual(log.log_file_path().parent.name, "logs")


if __name__ == "__main__":
    unittest.main()
