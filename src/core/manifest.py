"""Project-folder scanning, hashing and receive-side path safety.

A *manifest* is the list of files that make up a Premiere project folder. It is
sent ahead of the payload so the render station can decide what it already has
(resume support) and verify what it got (integrity).
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import posixpath
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence

HASH_CHUNK = 1024 * 1024

#: Regenerable or lock files that should never travel across the network.
DEFAULT_IGNORE: tuple[str, ...] = (
    "*.prlock",
    "*.tmp",
    "*.temp",
    "~$*",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.cfa",                              # conformed audio, rebuilt by Premiere
    "*.pek",                              # peak files, rebuilt by Premiere
    "Adobe Premiere Pro Auto-Save/*",
    "Adobe Premiere Pro Video Previews/*",
    "Adobe Premiere Pro Audio Previews/*",
    "Adobe Premiere Pro Preview Files/*",
    "Media Cache/*",
    "Media Cache Files/*",
)

_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_ILLEGAL_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


class UnsafePathError(ValueError):
    """Raised when a manifest entry cannot be trusted on the receiving side."""


@dataclass(frozen=True)
class FileEntry:
    path: str          # POSIX-style path relative to the project root
    size: int
    mtime: float
    sha256: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "FileEntry":
        return FileEntry(
            path=str(d["path"]),
            size=int(d["size"]),
            mtime=float(d.get("mtime", 0.0)),
            sha256=str(d.get("sha256", "")),
        )


# -- path safety -----------------------------------------------------------
def validate_relpath(rel: str) -> str:
    """Return a normalised relative path, or raise :class:`UnsafePathError`.

    Everything a remote peer sends is hostile until proven otherwise. This
    rejects absolute paths, drive letters, UNC prefixes, ``..`` traversal,
    NT reserved device names and characters Windows cannot store.
    """
    if not rel or not isinstance(rel, str):
        raise UnsafePathError("empty path")
    if len(rel) > 1024:
        raise UnsafePathError("path too long")

    cleaned = rel.replace("\\", "/").strip()
    if cleaned.startswith("/") or cleaned.startswith("//"):
        raise UnsafePathError(f"absolute path rejected: {rel!r}")
    if re.match(r"^[A-Za-z]:", cleaned):
        raise UnsafePathError(f"drive-qualified path rejected: {rel!r}")
    if _ILLEGAL_CHARS.search(cleaned):
        raise UnsafePathError(f"illegal characters in path: {rel!r}")

    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if not parts:
        raise UnsafePathError(f"path resolves to nothing: {rel!r}")
    for part in parts:
        if part == "..":
            raise UnsafePathError(f"parent traversal rejected: {rel!r}")
        if part != part.strip() or part.endswith("."):
            raise UnsafePathError(f"unstorable path component: {rel!r}")
        if part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise UnsafePathError(f"reserved device name: {rel!r}")
    return posixpath.join(*parts)


def safe_join(root: Path, rel: str) -> Path:
    """Join ``rel`` under ``root`` and prove the result stays inside it."""
    root = Path(root).resolve()
    candidate = (root / PurePosixPath(validate_relpath(rel))).resolve()
    if candidate != root and root not in candidate.parents:
        raise UnsafePathError(f"path escapes workspace: {rel!r}")
    return candidate


# -- hashing ---------------------------------------------------------------
def hash_file(path: Path, chunk: int = HASH_CHUNK,
              progress: Optional[Callable[[int], None]] = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
            if progress:
                progress(len(block))
    return digest.hexdigest()


# -- scanning --------------------------------------------------------------
def is_ignored(rel: str, patterns: Sequence[str]) -> bool:
    rel_lower = rel.lower()
    name = posixpath.basename(rel_lower)
    for pattern in patterns:
        pat = pattern.lower()
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_lower, pat):
            return True
        if pat.endswith("/*") and (rel_lower + "/").startswith(pat[:-1]):
            return True
        if f"/{pat[:-2]}/" in f"/{rel_lower}" and pat.endswith("/*"):
            return True
    return False


def scan_folder(root: Path,
                ignore: Sequence[str] = DEFAULT_IGNORE,
                with_hash: bool = True,
                progress: Optional[Callable[[str, int, int], None]] = None,
                cancel: Optional[Callable[[], bool]] = None) -> List[FileEntry]:
    """Walk ``root`` and build a manifest.

    ``progress(current_path, files_done, bytes_done)`` is called as it goes so
    the UI can stay responsive while hashing a 200 GB folder.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a folder")

    entries: List[FileEntry] = []
    files_done = 0
    bytes_done = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        here = Path(dirpath)
        rel_dir = here.relative_to(root).as_posix()
        if rel_dir != ".":
            dirnames[:] = [d for d in dirnames
                           if not is_ignored(f"{rel_dir}/{d}", ignore)]
        else:
            dirnames[:] = [d for d in dirnames if not is_ignored(d, ignore)]

        for filename in sorted(filenames):
            if cancel and cancel():
                raise InterruptedError("scan cancelled")
            full = here / filename
            rel = full.relative_to(root).as_posix()
            if is_ignored(rel, ignore):
                continue
            if full.is_symlink() or not full.is_file():
                continue
            try:
                stat = full.stat()
            except OSError:
                continue
            digest = hash_file(full) if with_hash else ""
            entries.append(FileEntry(validate_relpath(rel), stat.st_size,
                                     stat.st_mtime, digest))
            files_done += 1
            bytes_done += stat.st_size
            if progress:
                progress(rel, files_done, bytes_done)

    return entries


def total_bytes(entries: Iterable[FileEntry]) -> int:
    return sum(e.size for e in entries)


def find_projects(entries: Iterable[FileEntry]) -> List[str]:
    """Return the .prproj paths in a manifest, shallowest first."""
    projects = [e.path for e in entries if e.path.lower().endswith(".prproj")]
    return sorted(projects, key=lambda p: (p.count("/"), p.lower()))


def diff_manifest(entries: Sequence[FileEntry], dest_root: Path) -> Dict[str, int]:
    """Work out what still has to be transferred into ``dest_root``.

    Returns ``{relpath: byte offset to resume from}``. A file already present
    with the right size and hash is omitted entirely; a truncated ``.part``
    file resumes from its current length.
    """
    needed: Dict[str, int] = {}
    for entry in entries:
        target = safe_join(dest_root, entry.path)
        partial = target.with_name(target.name + ".part")
        if target.exists() and target.stat().st_size == entry.size:
            if not entry.sha256 or hash_file(target) == entry.sha256:
                continue
            needed[entry.path] = 0
            continue
        if partial.exists() and partial.stat().st_size <= entry.size:
            needed[entry.path] = partial.stat().st_size
        else:
            needed[entry.path] = 0
    return needed


def verify_received(entries: Sequence[FileEntry], dest_root: Path) -> List[str]:
    """Return a list of human-readable problems; empty means the folder is good."""
    problems: List[str] = []
    for entry in entries:
        target = safe_join(dest_root, entry.path)
        if not target.exists():
            problems.append(f"missing: {entry.path}")
            continue
        actual = target.stat().st_size
        if actual != entry.size:
            problems.append(f"size mismatch: {entry.path} ({actual} != {entry.size})")
            continue
        if entry.sha256 and hash_file(target) != entry.sha256:
            problems.append(f"checksum mismatch: {entry.path}")
    return problems
