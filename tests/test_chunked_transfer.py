"""Tests for chunked/resumable transfer — the part that actually matters for
large Premiere media files. Uses small chunk sizes so the tests run fast, and
a counting wrapper around the fake transport so "did we actually skip
re-sending/re-fetching that chunk" can be verified directly, not just inferred
from timing."""

import os
import tempfile
import unittest
from pathlib import Path

from src.remote import chunked_transfer as ct
from src.remote.auth import AuthService
from src.remote.config import RemoteConfig
from src.remote.fake_transport import FakeTransport

BUCKET = "project-files"


def make_config() -> RemoteConfig:
    return RemoteConfig(url="https://example.supabase.co", publishable_key="pk")


class CountingTransport:
    """Wraps a real transport, counting calls to upload()/download() by
    object path so tests can prove a resumed transfer skipped what it should."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.upload_calls = {}
        self.download_calls = {}

    def upload(self, bucket, object_path, data, on_progress=None):
        self.upload_calls[object_path] = self.upload_calls.get(object_path, 0) + 1
        return self._inner.upload(bucket, object_path, data, on_progress=on_progress)

    def download(self, bucket, object_path, on_progress=None):
        self.download_calls[object_path] = self.download_calls.get(object_path, 0) + 1
        return self._inner.download(bucket, object_path, on_progress=on_progress)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def signed_in_transport() -> FakeTransport:
    transport = FakeTransport()
    AuthService(transport, make_config()).sign_up("family", "pw1234")
    return transport


class TestSmallFiles(unittest.TestCase):
    def test_small_file_uploads_as_a_single_object_no_manifest(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "clip.mov"
            source.write_bytes(b"small file contents")
            ct.upload_file(transport, BUCKET, "job1/clip.mov", source,
                           threshold=1024 * 1024)
            objects = transport.list_objects(BUCKET, "job1/")
            self.assertEqual(objects, ["job1/clip.mov"])

            dest = Path(tmp) / "out" / "clip.mov"
            ct.download_file(transport, BUCKET, "job1/clip.mov", dest)
            self.assertEqual(dest.read_bytes(), source.read_bytes())


class TestChunkedRoundTrip(unittest.TestCase):
    def _make_large_source(self, tmp: Path, size: int) -> Path:
        source = tmp / "big.mov"
        source.write_bytes(os.urandom(size))
        return source

    def test_large_file_chunks_and_reassembles_byte_exact(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_large_source(root, 50_000)
            ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                           chunk_size=8_000, threshold=1_000)

            objects = transport.list_objects(BUCKET, "job1/big.mov")
            self.assertEqual(len(objects), 8)
            self.assertTrue(any(o.endswith(".manifest.json") for o in objects))

            dest = root / "out" / "big.mov"
            ct.download_file(transport, BUCKET, "job1/big.mov", dest)
            self.assertEqual(dest.read_bytes(), source.read_bytes())

    def test_progress_reports_monotonically_up_to_the_full_size(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_large_source(root, 30_000)
            seen = []
            ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                           chunk_size=5_000, threshold=1_000,
                           on_progress=lambda done, total: seen.append((done, total)))
            self.assertTrue(seen)
            self.assertEqual(seen[-1], (30_000, 30_000))
            self.assertEqual([p[1] for p in seen], [30_000] * len(seen))
            self.assertEqual(seen, sorted(seen))


class TestUploadResume(unittest.TestCase):
    def test_resume_skips_parts_already_on_the_server(self):
        inner = signed_in_transport()
        counting = CountingTransport(inner)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "big.mov"
            source.write_bytes(os.urandom(24_000))

            with open(source, "rb") as handle:
                inner.upload(BUCKET, "job1/big.mov.part000000", handle.read(8_000))
                inner.upload(BUCKET, "job1/big.mov.part000001", handle.read(8_000))

            ct.upload_file(counting, BUCKET, "job1/big.mov", source,
                           chunk_size=8_000, threshold=1_000)

            self.assertNotIn("job1/big.mov.part000000", counting.upload_calls)
            self.assertNotIn("job1/big.mov.part000001", counting.upload_calls)
            self.assertEqual(counting.upload_calls.get("job1/big.mov.part000002"), 1)

            dest = root / "out.mov"
            ct.download_file(inner, BUCKET, "job1/big.mov", dest)
            self.assertEqual(dest.read_bytes(), source.read_bytes())


class TestDownloadResume(unittest.TestCase):
    def test_resume_skips_chunks_already_written_locally(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "big.mov"
            source.write_bytes(os.urandom(24_000))
            ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                           chunk_size=8_000, threshold=1_000)

            dest = root / "big.mov"
            dest.write_bytes(source.read_bytes()[:8_000])

            counting = CountingTransport(transport)
            ct.download_file(counting, BUCKET, "job1/big.mov", dest)

            self.assertNotIn("job1/big.mov.part000000", counting.download_calls)
            self.assertEqual(counting.download_calls.get("job1/big.mov.part000001"), 1)
            self.assertEqual(dest.read_bytes(), source.read_bytes())

    def test_corrupt_partial_local_file_is_discarded_and_restarted(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "big.mov"
            source.write_bytes(os.urandom(24_000))
            ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                           chunk_size=8_000, threshold=1_000)

            dest = root / "big.mov"
            dest.write_bytes(b"x" * 3_333)

            ct.download_file(transport, BUCKET, "job1/big.mov", dest)
            self.assertEqual(dest.read_bytes(), source.read_bytes())


class TestIntegrityAndCancellation(unittest.TestCase):
    def test_checksum_mismatch_raises_and_removes_the_file(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "big.mov"
            source.write_bytes(os.urandom(20_000))
            ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                           chunk_size=6_000, threshold=1_000)

            with self.assertRaises(ValueError):
                dest = root / "out.mov"
                ct.download_file(transport, BUCKET, "job1/big.mov", dest,
                                 expected_sha256="0" * 64)
            self.assertFalse((root / "out.mov").exists())

    def test_cancel_during_upload_raises_and_stops(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big.mov"
            source.write_bytes(os.urandom(40_000))
            calls = {"n": 0}

            def cancel_after_two():
                calls["n"] += 1
                return calls["n"] > 2

            with self.assertRaises(InterruptedError):
                ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                               chunk_size=8_000, threshold=1_000,
                               cancel=cancel_after_two)
            self.assertFalse(any(o.endswith(".manifest.json") for o in
                                 transport.list_objects(BUCKET, "job1/")))

    def test_cancel_during_download_raises_and_stops(self):
        transport = signed_in_transport()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "big.mov"
            source.write_bytes(os.urandom(40_000))
            ct.upload_file(transport, BUCKET, "job1/big.mov", source,
                           chunk_size=8_000, threshold=1_000)

            calls = {"n": 0}

            def cancel_after_two():
                calls["n"] += 1
                return calls["n"] > 2

            dest = root / "out.mov"
            with self.assertRaises(InterruptedError):
                ct.download_file(transport, BUCKET, "job1/big.mov", dest,
                                 cancel=cancel_after_two)


if __name__ == "__main__":
    unittest.main()
