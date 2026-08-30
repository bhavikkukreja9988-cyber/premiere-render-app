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
