# premiere-render-app

Windows desktop MVP for sending a Premiere Pro project folder to a render station on the same LAN.

## MVP
- PySide6 desktop UI with Sender and Render Station modes
- Direct TCP PC-to-PC project-folder transfer
- Chunked streaming for large files
- Safe relative-path validation on receiving side
- Transfer progress reporting
- Render-station online/offline mode
- Adobe Media Encoder detection and launch helper
- Output monitoring helper for completed video files
- PyInstaller Windows build script
- Core unit tests

## Run
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

## Build
Run `scripts\\build_windows.bat` on Windows. The executable is generated under `dist\\PremiereRenderApp\\`.

## Network
Both PCs must be on a network that permits inbound TCP traffic on port `49872`. The render station listens while the app is open.

## Next milestone
Full Adobe Media Encoder queue/control automation and automatic MP4 return transfer are the next production features.