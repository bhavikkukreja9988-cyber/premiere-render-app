"""Best-effort reader for Premiere Pro project files.

A ``.prproj`` is a gzip-compressed XML document. We only need the sequence
names so the sender can pick one from a dropdown instead of typing it, so this
parser is deliberately forgiving: anything it cannot understand falls back to
"let the user type the name", and an unreadable project never blocks a send.
"""

from __future__ import annotations

import gzip
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

GZIP_MAGIC = b"\x1f\x8b"
MAX_XML_BYTES = 400 * 1024 * 1024      # refuse absurd projects rather than swap


@dataclass
class ProjectInfo:
    path: str
    sequences: List[str]
    version: str = ""
    readable: bool = True
    error: str = ""


def _open_project(path: Path) -> io.BufferedReader:
    with open(path, "rb") as probe:
        magic = probe.read(2)
    if magic == GZIP_MAGIC:
        return gzip.open(path, "rb")          # type: ignore[return-value]
    return open(path, "rb")


def read_sequence_names(path: Path) -> List[str]:
    """Return sequence names in document order, de-duplicated."""
    names: List[str] = []
    seen = set()
    depth = 0
    sequence_depth: Optional[int] = None
    pending_name: Optional[str] = None

    stream = _open_project(Path(path))
    try:
        for event, elem in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                depth += 1
                if elem.tag == "Sequence" and sequence_depth is None:
                    sequence_depth = depth
                    pending_name = None
                continue

            # end event
            if sequence_depth is not None and elem.tag == "Name" \
                    and depth == sequence_depth + 1 and pending_name is None:
                pending_name = (elem.text or "").strip()

            if elem.tag == "Sequence" and sequence_depth == depth:
                if pending_name and pending_name not in seen:
                    seen.add(pending_name)
                    names.append(pending_name)
                sequence_depth = None
                pending_name = None

            depth -= 1
            elem.clear()
    finally:
        try:
            stream.close()
        except Exception:
            pass
    return names


def _fallback_regex_scan(path: Path) -> List[str]:
    """Some project versions nest <Name> deeper than we walk. Sweep the raw XML
    for sequence blocks as a last resort."""
    try:
        stream = _open_project(Path(path))
        with stream:
            blob = stream.read(MAX_XML_BYTES).decode("utf-8", errors="ignore")
    except OSError:
        return []
    names: List[str] = []
    seen = set()
    for block in re.findall(r"<Sequence\b.*?</Sequence>", blob, flags=re.S)[:500]:
        match = re.search(r"<Name>(.*?)</Name>", block, flags=re.S)
        if match:
            name = match.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def probe_project(path: Path) -> ProjectInfo:
    path = Path(path)
    if not path.is_file():
        return ProjectInfo(str(path), [], readable=False, error="file not found")
    try:
        names = read_sequence_names(path)
        if not names:
            names = _fallback_regex_scan(path)
        return ProjectInfo(str(path), names, readable=True)
    except Exception as exc:                      # noqa: BLE001 - never fatal
        names = _fallback_regex_scan(path)
        return ProjectInfo(str(path), names, readable=bool(names), error=str(exc))


# -- external media detection (best effort) ---------------------------------
# Premiere stores absolute media paths as file:// URLs and, on Windows, plain
# drive-letter paths, inside opaque binary/XML blobs whose exact schema varies
# by version. This is a heuristic, not a full parser: it looks for path-shaped
# strings and flags ones that clearly point outside the project folder. It can
# miss things and can also over-flag; it exists to warn, not to block silently.
# The drive-letter pattern must not match inside a word — without the lookbehind
# it happily matches the "e:" in "fil(e:)//C:/..." and produces a mangled
# "e://C:/..." path that then looks like external media.
_WIN_PATH_RE = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/][^"<>\x00-\x1f]{3,400}')
# Windows file URLs appear both as file:///C:/... and file://C:/..., so the
# third slash has to be optional or Windows paths are missed entirely.
_FILE_URL_RE = re.compile(r'file://(?:localhost)?/?[^"\s<>\x00-\x1f]{3,400}')
_MAX_EXTERNAL_HITS = 25


def _file_url_to_path(url: str) -> str:
    from urllib.parse import unquote, urlsplit
    parsed = urlsplit(url)
    raw = unquote(parsed.path)
    # Windows URLs come in two shapes:
    #   file:///C:/...  -> netloc "",   path "/C:/..."
    #   file://C:/...   -> netloc "C:", path "/..."   (drive lands in netloc)
    # Without handling the second form the drive letter is silently dropped
    # and the resulting path is wrong.
    netloc = unquote(parsed.netloc)
    if re.fullmatch(r"[A-Za-z]:", netloc):
        return netloc + raw
    if re.match(r"^/[A-Za-z]:", raw):
        raw = raw[1:]
    return raw


def find_external_media(prproj_path: Path, project_root: Path) -> List[str]:
    """Return likely-external absolute media paths referenced by the project.

    Best-effort and capped; never raises. An empty list means either nothing
    was found or the project could not be scanned — callers should treat that
    as "no warning", not as a guarantee everything is included.
    """
    try:
        stream = _open_project(Path(prproj_path))
        with stream:
            blob = stream.read(MAX_XML_BYTES)
        text = blob.decode("utf-8", errors="ignore")
    except OSError:
        return []

    root = Path(project_root).resolve()
    found: List[str] = []
    seen = set()

    candidates: List[str] = []
    for match in _FILE_URL_RE.finditer(text):
        candidates.append(_file_url_to_path(match.group(0)))
    for match in _WIN_PATH_RE.finditer(text):
        candidates.append(match.group(0))

    for raw in candidates:
        if len(found) >= _MAX_EXTERNAL_HITS:
            break
        cleaned = raw.replace("\\", "/").rstrip("\x00")
        if cleaned in seen:
            continue
        seen.add(cleaned)
        try:
            candidate_path = Path(cleaned)
            if not candidate_path.is_absolute():
                continue
            resolved = candidate_path.resolve()
        except (OSError, ValueError):
            continue
        if root in resolved.parents or resolved == root:
            continue
        # Skip Premiere's own program/plugin paths, not the user's media.
        lowered = str(resolved).lower()
        if any(marker in lowered for marker in
               ("adobe premiere pro", "adobe media encoder", "common files",
                "\\windows\\", "/windows/")):
            continue
        found.append(str(resolved))
    return found
