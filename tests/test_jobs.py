import gzip
import tempfile
import unittest
from pathlib import Path

from src.core.jobs import JobRecord, JobSpec, JobState, JobStore
from src.core.project_probe import probe_project

SAMPLE_PROJECT = """<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
  <Project ObjectID="1"><Name>My Edit</Name></Project>
  <Sequence ObjectID="7">
    <Name>Main Timeline</Name>
    <TrackGroups><TrackGroup><Name>Video 1</Name></TrackGroup></TrackGroups>
  </Sequence>
  <Sequence ObjectID="8">
    <Name>Instagram Cut</Name>
  </Sequence>
</PremiereData>
"""


class TestJobSpec(unittest.TestCase):
    def test_output_filename_sanitises_illegal_characters(self):
        spec = JobSpec(name="promo", output_name='final/cut:v2', container=".mp4")
        self.assertEqual(spec.output_filename(), "final_cut_v2.mp4")

    def test_output_filename_falls_back_to_job_name(self):
        self.assertEqual(JobSpec(name="promo").output_filename(), "promo.mp4")

    def test_roundtrip_ignores_unknown_keys(self):
        data = JobSpec(name="a").to_dict()
        data["unexpected_future_field"] = 1
        self.assertEqual(JobSpec.from_dict(data).name, "a")


class TestJobStore(unittest.TestCase):
    def test_updates_notify_listeners(self):
        store = JobStore()
        seen = []
        store.subscribe(lambda record: seen.append(record.state))
        store.add(JobRecord(spec=JobSpec(job_id="j1", name="x")))
        store.update("j1", state=JobState.QUEUED)
        self.assertEqual(seen[-1], JobState.QUEUED)

    def test_next_queued_is_oldest_first(self):
        store = JobStore()
        store.add(JobRecord(spec=JobSpec(job_id="new", created_at=200),
                            state=JobState.QUEUED))
        store.add(JobRecord(spec=JobSpec(job_id="old", created_at=100),
                            state=JobState.QUEUED))
        self.assertEqual(store.next_queued().job_id, "old")

    def test_persistence_requeues_interrupted_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            store = JobStore(path)
            store.add(JobRecord(spec=JobSpec(job_id="j1"), state=JobState.RENDERING))
            store.add(JobRecord(spec=JobSpec(job_id="j2"), state=JobState.COMPLETE))

            reloaded = JobStore(path)
            self.assertEqual(reloaded.get("j1").state, JobState.QUEUED)
            self.assertEqual(reloaded.get("j2").state, JobState.COMPLETE)

    def test_terminal_states(self):
        self.assertTrue(JobState.FAILED.terminal)
        self.assertFalse(JobState.RENDERING.terminal)


class TestProjectProbe(unittest.TestCase):
    def _write(self, path: Path, compress: bool) -> Path:
        data = SAMPLE_PROJECT.encode("utf-8")
        if compress:
            path.write_bytes(gzip.compress(data))
        else:
            path.write_bytes(data)
        return path

    def test_reads_sequences_from_gzipped_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp) / "Edit.prproj", compress=True)
            info = probe_project(path)
            self.assertEqual(info.sequences, ["Main Timeline", "Instagram Cut"])

    def test_reads_sequences_from_plain_xml_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp) / "Edit.prproj", compress=False)
            self.assertIn("Main Timeline", probe_project(path).sequences)

    def test_unreadable_project_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.prproj"
            path.write_bytes(b"not a project at all")
            info = probe_project(path)
            self.assertEqual(info.sequences, [])


class TestExternalMediaDetection(unittest.TestCase):
    def test_flags_media_outside_the_project_folder(self):
        from src.core.project_probe import find_external_media
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MyProject"
            root.mkdir()
            outside = Path(tmp) / "Elsewhere"
            outside.mkdir()
            inside_file = root / "footage" / "insidefile.mov"
            inside_file.parent.mkdir()
            inside_file.write_bytes(b"x")
            outside_file = outside / "outsidefile.mov"
            outside_file.write_bytes(b"x")

            xml = (
                b"<PremiereData><Media><ActualMediaFilePath>"
                + f"file://{inside_file.as_posix()}".encode()
                + b"</ActualMediaFilePath></Media><Media>"
                + b"<ActualMediaFilePath>"
                + f"file://{outside_file.as_posix()}".encode()
                + b"</ActualMediaFilePath></Media></PremiereData>"
            )
            prproj = root / "Edit.prproj"
            prproj.write_bytes(gzip.compress(xml))

            hits = find_external_media(prproj, root)
            self.assertTrue(any("outsidefile.mov" in h for h in hits))
            self.assertFalse(any("insidefile.mov" in h for h in hits))

    def test_no_external_media_returns_empty(self):
        from src.core.project_probe import find_external_media
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MyProject"
            root.mkdir()
            inside_file = root / "clip.mov"
            inside_file.write_bytes(b"x")
            xml = (b"<PremiereData><Media><ActualMediaFilePath>file://"
                  + inside_file.as_posix().encode()
                  + b"</ActualMediaFilePath></Media></PremiereData>")
            prproj = root / "Edit.prproj"
            prproj.write_bytes(gzip.compress(xml))
            self.assertEqual(find_external_media(prproj, root), [])

    def test_never_raises_on_garbage_input(self):
        from src.core.project_probe import find_external_media
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prproj = root / "broken.prproj"
            prproj.write_bytes(b"\x00\x01garbage not gzip or xml")
            self.assertEqual(find_external_media(prproj, root), [])


if __name__ == "__main__":
    unittest.main()
