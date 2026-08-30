"""Full round trip over a real TCP socket with a stubbed render backend.

This is the test that matters: it exercises the handshake, pairing, manifest
validation, chunked upload, resume bookkeeping, queueing, result streaming and
the acknowledgement that closes the job out.
"""

import tempfile
import time
import unittest
from pathlib import Path

from src.core.config import AppConfig
from src.core.jobs import JobSpec, JobState
from src.core.protocol import Msg, ProtocolError, RemoteError
from src.transfer import transfer_engine as sender_module
from src.transfer.transfer_engine import SendRequest, SendWorker, SenderClient
from src.network.session import RenderStation
from src.render.pipeline import RenderBackend

RENDERED_BYTES = b"FAKE-MP4-PAYLOAD" * 500


class FakeBackend(RenderBackend):
    """Pretends to be Media Encoder: writes an output file and returns."""

    name = "fake"

    def render(self, record, job_root, progress, cancel):
        progress(0.5, "pretending to encode")
        output = job_root / "output" / record.spec.output_filename()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(RENDERED_BYTES)
        progress(1.0, "done")
        return output


def make_project(root: Path) -> None:
    (root / "footage").mkdir(parents=True)
    (root / "Edit.prproj").write_bytes(b"pretend project" * 100)
    (root / "footage" / "a.mov").write_bytes(b"a" * (1024 * 300))
    (root / "footage" / "b.wav").write_bytes(b"b" * (1024 * 64))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self._original_poll = sender_module.POLL_SECONDS
        sender_module.POLL_SECONDS = 0.2

        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project = base / "project"
        self.output = base / "returned"
        self.project.mkdir()
        self.output.mkdir()
        make_project(self.project)

        self.config = AppConfig(
            workspace_dir=str(base / "station"),
            tcp_port=0,
            require_pairing=True,
            pairing_code="424242",
            broadcast_presence=False,
            station_name="test-station",
        )
        self.station = RenderStation(self.config, backend=FakeBackend())
        self.port = self.station.start()
        self.addCleanup(self.station.stop)
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        sender_module.POLL_SECONDS = self._original_poll

    def _request(self, **overrides) -> SendRequest:
        spec = JobSpec(name="promo", project_relpath="Edit.prproj",
                       sequence="Main Timeline", output_name="promo_final")
        defaults = dict(host="127.0.0.1", port=self.port, pairing_code="424242",
                        sender_name="edit-pc", folder=self.project, spec=spec,
                        output_dir=self.output)
        defaults.update(overrides)
        return SendRequest(**defaults)

    def _run_worker(self, request, timeout=60) -> SendWorker:
        worker = SendWorker(request)
        worker.start()
        worker.join(timeout=timeout)
        self.assertFalse(worker.is_alive(), "worker did not finish in time")
        return worker

    # -- happy path -------------------------------------------------------
    def test_full_round_trip(self):
        worker = self._run_worker(self._request())
        self.assertEqual(worker.error, "")
        self.assertIsNotNone(worker.result_path)
        returned = Path(worker.result_path)
        self.assertTrue(returned.is_file())
        self.assertEqual(returned.name, "promo_final.mp4")
        self.assertEqual(returned.read_bytes(), RENDERED_BYTES)

        records = self.station.store.list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].state, JobState.COMPLETE)
        self.assertEqual(records[0].spec.sequence, "Main Timeline")

    def test_transferred_folder_matches_the_original(self):
        self._run_worker(self._request())
        job_id = self.station.store.list()[0].job_id
        received = Path(self.config.workspace_dir) / "jobs" / job_id / "project"
        for relative in ("Edit.prproj", "footage/a.mov", "footage/b.wav"):
            self.assertEqual((received / relative).read_bytes(),
                             (self.project / relative).read_bytes(),
                             f"{relative} did not arrive intact")

    def test_resume_skips_files_already_on_the_station(self):
        first = self._run_worker(self._request())
        self.assertEqual(first.error, "")

        # Re-offer the same job id: the station should ask for nothing.
        spec = self.station.store.list()[0].spec
        with SenderClient("127.0.0.1", self.port, "424242", "edit-pc") as client:
            from src.core.manifest import scan_folder
            entries = scan_folder(self.project)
            client.conn.send(Msg.JOB_OFFER, {"spec": spec.to_dict(),
                                             "manifest": [e.to_dict() for e in entries]})
            accept = client.conn.recv(expect=Msg.JOB_ACCEPT)
            self.assertEqual(accept.get("need"), {})

    # -- failure paths ----------------------------------------------------
    def test_wrong_pairing_code_is_rejected(self):
        with self.assertRaises(RemoteError):
            with SenderClient("127.0.0.1", self.port, "000000", "intruder"):
                pass

    def test_missing_pairing_code_is_rejected(self):
        with self.assertRaises(ProtocolError):
            with SenderClient("127.0.0.1", self.port, "", "intruder"):
                pass

    def test_traversal_in_manifest_is_refused(self):
        with SenderClient("127.0.0.1", self.port, "424242", "edit-pc") as client:
            spec = JobSpec(name="evil")
            manifest = [{"path": "../../escaped.txt", "size": 4,
                         "mtime": 0, "sha256": ""}]
            client.conn.send(Msg.JOB_OFFER, {"spec": spec.to_dict(),
                                             "manifest": manifest})
            with self.assertRaises(RemoteError) as caught:
                client.conn.recv()
            self.assertEqual(caught.exception.code, "unsafe_manifest")

    def test_status_for_unknown_job(self):
        with SenderClient("127.0.0.1", self.port, "424242", "edit-pc") as client:
            client.conn.send(Msg.STATUS_REQ, {"job_id": "does-not-exist"})
            with self.assertRaises(RemoteError):
                client.conn.recv()

    def test_station_reports_itself(self):
        with SenderClient("127.0.0.1", self.port, "424242", "edit-pc") as client:
            info = client.station_info
        self.assertEqual(info["name"], "test-station")
        self.assertTrue(info["requires_code"])
        self.assertEqual(info["backend"], "fake")

    def test_failed_render_is_reported_to_the_sender(self):
        class BrokenBackend(RenderBackend):
            name = "broken"

            def render(self, record, job_root, progress, cancel):
                raise RuntimeError("Media Encoder exploded")

        self.station.manager.backend = BrokenBackend()
        worker = self._run_worker(self._request())
        self.assertIn("exploded", worker.error)
        self.assertIsNone(worker.result_path)
        self.assertEqual(self.station.store.list()[0].state, JobState.FAILED)


if __name__ == "__main__":
    unittest.main()
