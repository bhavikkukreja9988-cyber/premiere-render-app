"""Check that the files from an update arrived exactly as they were sent.

Run from the repo folder:

    python scripts\\verify_update.py

It compares every file listed in scripts/update_manifest.txt with the
SHA-256 fingerprint recorded when the update was made. Any change at all —
a missing character, a lost line, a file that was never copied — shows up.

Line endings are ignored (Windows/Git may convert \\n to \\r\\n; that's
harmless), so only real content changes are reported.

Why this exists: copying code by pasting it (for example into GitHub's web
editor) can silently damage a file. One such damaged test file blocked the
installer build with "SyntaxError: expected ':'".
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "scripts" / "update_manifest.txt"


def fingerprint(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    if not MANIFEST.is_file():
        print(f"[FAIL] {MANIFEST} not found - copy it from the update zip.")
        return 1

    ok = bad = missing = 0
    problems = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        expected, rel = raw.split(None, 1)
        path = REPO_ROOT / rel
        if not path.is_file():
            missing += 1
            problems.append(f"MISSING   {rel}")
        elif fingerprint(path) != expected:
            bad += 1
            problems.append(f"CHANGED   {rel}")
        else:
            ok += 1

    print("=" * 64)
    print(" Update file check")
    print("=" * 64)
    for row in problems:
        print(f"  {row}")
    print(f"\n  {ok} OK, {bad} changed, {missing} missing")

    if problems:
        print("\n[FAIL] Some files don't match the update exactly.")
        print("       Copy those files again straight from the update zip -")
        print("       don't retype or paste their contents - then re-run:")
        print("           python scripts\\verify_update.py")
        return 1
    print("\n[ ok ] Every file matches the update exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
