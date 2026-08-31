import unittest
import tempfile
from pathlib import Path

from src.core.manifest import (DEFAULT_IGNORE, UnsafePathError,
                               diff_manifest, hash_file, safe_join, scan_folder,
                               validate_relpath, verify_received)


def make_tree(root: Path) -> None:
    (root / "footage").mkdir(parents=True)
    (root / "Adobe Premiere Pro Auto-Save").mkdir(parents=True)
    (root / "Edit.prproj").write_bytes(b"project-bytes")
    (root / "footage" / "clip.mp4").write_bytes(b"x" * 4096)
    (root / "footage" / "clip.cfa").write_bytes(b"cache")
    (root / "Adobe Premiere Pro Auto-Save" / "Edit-1.prproj").write_bytes(b"old")
    (root / "Edit.prlock").write_bytes(b"lock")


class TestPathSafety(unittest.TestCase):
    def test_normalises_windows_separators(self):
        self.assertEqual(validate_relpath("footage\\clip.mp4"), "footage/clip.mp4")

    def test_rejects_traversal(self):
        for bad in ("../secret.txt", "footage/../../etc/passwd", "a/../../b"):
            with self.assertRaises(UnsafePathError):
                validate_relpath(bad)

    def test_rejects_absolute_and_drive_paths(self):
        for bad in ("/etc/passwd", "C:/Windows/system32", "//server/share/x"):
            with self.assertRaises(UnsafePathError):
                validate_relpath(bad)

    def test_rejects_reserved_and_illegal_names(self):
        for bad in ("CON", "nul.txt", "a/lpt1", 'bad"name', "trail."):
            with self.assertRaises(UnsafePathError):
                validate_relpath(bad)

    def test_safe_join_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(safe_join(root, "a/b.txt"), (root / "a" / "b.txt").resolve())
            with self.assertRaises(UnsafePathError):
                safe_join(root, "../outside.txt")


class TestScan(unittest.TestCase):
    def test_skips_regenerable_and_lock_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tree(root)
            paths = {entry.path for entry in scan_folder(root, DEFAULT_IGNORE)}
            self.assertIn("Edit.prproj", paths)
            self.assertIn("footage/clip.mp4", paths)
            self.assertNotIn("footage/clip.cfa", paths)
            self.assertNotIn("Edit.prlock", paths)
            self.assertFalse(any(p.startswith("Adobe Premiere Pro Auto-Save")
                                 for p in paths))

    def test_hashes_match_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tree(root)
            for entry in scan_folder(root):
                self.assertEqual(entry.sha256, hash_file(root / entry.path))


class TestResume(unittest.TestCase):
    def test_diff_reports_partial_offsets_and_skips_complete_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / "src", Path(tmp) / "dst"
            source.mkdir()
            dest.mkdir()
            (source / "a.bin").write_bytes(b"a" * 1000)
            (source / "b.bin").write_bytes(b"b" * 1000)
            (source / "c.bin").write_bytes(b"c" * 1000)
            entries = scan_folder(source)

            (dest / "a.bin").write_bytes(b"a" * 1000)          # already there
            (dest / "b.bin.part").write_bytes(b"b" * 400)      # half transferred

            needed = diff_manifest(entries, dest)
            self.assertNotIn("a.bin", needed)
            self.assertEqual(needed["b.bin"], 400)
            self.assertEqual(needed["c.bin"], 0)

    def test_verify_detects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / "src", Path(tmp) / "dst"
            source.mkdir()
            dest.mkdir()
            (source / "a.bin").write_bytes(b"a" * 64)
            entries = scan_folder(source)
            (dest / "a.bin").write_bytes(b"z" * 64)
            problems = verify_received(entries, dest)
            self.assertEqual(len(problems), 1)
            self.assertIn("checksum", problems[0])


if __name__ == "__main__":
    unittest.main()
