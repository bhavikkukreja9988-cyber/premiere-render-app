# Premiere Render App

A Windows desktop app for sending an Adobe Premiere Pro project folder to a render station on the same LAN and receiving the finished video back.

## Repository status

- `main` — stable MVP baseline. Do not use this branch for experimental work.
- `develop` — integration branch for changes that are ready to be combined and tested.
- `feature/*` — one task/feature at a time.
- `chore/*` — repository maintenance and tooling.
- `archive/*` — historical snapshots; never treated as active source.

The current V2 work is intentionally kept on `feature/v2-transfer-render-return` until the full implementation has been uploaded and validated on Windows with Premiere Pro + Media Encoder.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

## Validate the code

Run from the repository root:

```powershell
python -m unittest discover -s tests -t .
```

The tests are standard-library based and do not require PySide6 or a network connection.

## Build Windows executable

```powershell
scripts\build_windows.bat
```

## Repository map

```text
src/                     application source
  core/                  pure domain logic; no Qt/sockets
  network/               LAN discovery and TCP sessions
  transfer/              project/file transfer
  render/                Media Encoder integration and output monitoring
  return_transfer/       finished-video return path
  ui/                    PySide6 desktop UI

tests/                   automated tests
scripts/                 Windows build/run helpers
docs/                    architecture, setup and development docs
archive/                 historical snapshots only
.github/                 GitHub workflow and contribution templates
```

## Development rules

1. Read `AI_DEVELOPER_GUIDE.md` before changing the project.
2. Read `docs/REPOSITORY_MAP.md` before moving files or changing architecture.
3. Never replace `src/`, `tests/`, or `scripts/` wholesale unless a task explicitly requires it and the change is reviewed.
4. Keep commits focused: one feature/fix per branch where practical.
5. Run the test suite before and after changes.
6. Do not commit `.venv/`, `build/`, `dist/`, caches, logs, or secrets.
7. Real Media Encoder behavior must be tested on Windows; passing unit tests alone is not proof of Adobe integration.

## Project goal

The target workflow is:

Premiere project folder → secure LAN transfer → render-station queue → Adobe Media Encoder render → finished-output detection → checksum-verified MP4 return.
