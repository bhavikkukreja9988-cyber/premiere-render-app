"""Pre-build environment check for Premiere Render App.

Run this before building the installer. It checks, one by one, that everything
needed is present and prints a clear PASS/FAIL for each, with exactly what to do
about any failure. It never changes anything — it only looks.

    python scripts\\preflight.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GREEN = "PASS"
RED = "FAIL"
YELLOW = "WARN"


def line(status: str, title: str, detail: str = "") -> bool:
    mark = {"PASS": "[ ok ]", "FAIL": "[FAIL]", "WARN": "[warn]"}[status]
    print(f"{mark} {title}")
    if detail:
        for row in detail.splitlines():
            print(f"        {row}")
    return status != RED


def check_windows() -> bool:
    if sys.platform.startswith("win"):
        return line(GREEN, "Running on Windows")
    return line(
        RED, "Not running on Windows",
        "The installer can only be built on a Windows PC.\n"
        "Copy this project to a Windows machine and run the build there.")


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        return line(GREEN, f"Python {major}.{minor} detected")
    return line(
        RED, f"Python {major}.{minor} is too old",
        "Install Python 3.10 or newer from https://www.python.org/downloads/\n"
        "During install, tick 'Add python.exe to PATH'.")


def check_pip() -> bool:
    try:
        import pip  # noqa: F401
        return line(GREEN, "pip is available")
    except ImportError:
        return line(
            RED, "pip is missing",
            "Reinstall Python and ensure pip is included (it is by default).")


def check_module(mod: str, install_hint: str) -> bool:
    try:
        __import__(mod)
        return line(GREEN, f"Python package '{mod}' is installed")
    except ImportError:
        return line(
            YELLOW, f"Python package '{mod}' is not installed yet",
            f"The build script installs it automatically. To do it by hand:\n"
            f"    pip install {install_hint}")


def check_pyside6() -> bool:
    try:
        import PySide6  # noqa: F401
        return line(GREEN, "PySide6 is installed")
    except ImportError:
        return line(
            YELLOW, "PySide6 is not installed yet",
            "The build script installs it automatically. To do it by hand:\n"
            "    pip install PySide6")


def check_inno() -> bool:
    found = shutil.which("ISCC") or shutil.which("ISCC.exe")
    if not found:
        for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files")):
            candidate = Path(base) / "Inno Setup 6" / "ISCC.exe"
            if candidate.is_file():
                found = str(candidate)
                break
    if found:
        return line(GREEN, "Inno Setup compiler (ISCC) found", found)
    return line(
        RED, "Inno Setup is not installed",
        "The installer is built with Inno Setup 6 (free).\n"
        "1. Download it from https://jrsoftware.org/isdl.php\n"
        "2. Install it (default options are fine).\n"
        "3. Re-run this check.")


def check_agent_present() -> bool:
    agent = REPO_ROOT / "src" / "render" / "jsx" / "PremiereRenderAgent.jsx"
    if agent.is_file():
        return line(GREEN, "Media Encoder agent script is present")
    return line(
        RED, "Media Encoder agent script is missing",
        f"Expected at: {agent}\n"
        "The project is incomplete; re-extract it from the ZIP.")


def check_spec_present() -> bool:
    spec = REPO_ROOT / "installer" / "PremiereRenderApp.spec"
    iss = REPO_ROOT / "installer" / "FileSender.iss"
    ok = spec.is_file() and iss.is_file()
    if ok:
        return line(GREEN, "Installer scripts are present")
    return line(RED, "Installer scripts are missing",
                f"Expected: {spec}\n          {iss}")


def check_icon_present() -> bool:
    icon = REPO_ROOT / "assets" / "FileSender.ico"
    if icon.is_file():
        return line(GREEN, "App icon is present")
    return line(
        RED, "App icon is missing",
        f"Expected at: {icon}\n"
        "The Inno Setup build step will fail without it. Re-extract the "
        "project or restore assets/FileSender.ico.")


def main() -> int:
    print("=" * 64)
    print(" Premiere Render App - build environment check")
    print("=" * 64)
    checks = [
        check_windows(),
        check_python(),
        check_pip(),
        check_pyside6(),
        check_module("supabase", "supabase"),
        check_module("PyInstaller", "pyinstaller"),
        check_inno(),
        check_agent_present(),
        check_spec_present(),
        check_icon_present(),
    ]
    print("-" * 64)
    if all(checks):
        print("All required checks passed. You can build the installer:")
        print("    scripts\\build_installer.bat")
        return 0
    print("One or more required checks FAILED (see [FAIL] lines above).")
    print("Fix those, then run this check again:")
    print("    python scripts\\preflight.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
