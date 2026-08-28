# Premiere Render App — MVP

Windows application for sending a Premiere Pro project from one PC to a render station on the same network.

## Current MVP

- Qt desktop UI with Sender and Render Station modes
- Direct TCP PC-to-PC project-folder transfer
- Chunked streaming for large files
- Safe relative-path validation on the receiving side
- Transfer progress reporting
- Render-station online/offline mode
- Adobe Media Encoder detection via environment variable and common Windows install paths
- Output monitoring helper for completed video files
- PyInstaller build script for Windows
- Core unit tests

## Run from source

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

## Build EXE

Run `scripts\\build_windows.bat`. The generated executable will be under `dist\\PremiereRenderApp\\`.

## Network

Both PCs must be on a network that permits inbound TCP traffic on port `49872`. The render station listens on all local interfaces while the app is open.

## Adobe Media Encoder

Set `ADOBE_MEDIA_ENCODER` to the full path of `Adobe Media Encoder.exe` when its install location is non-standard. The current MVP detects and launches Media Encoder, but full queue/control automation still needs to be added for production use.