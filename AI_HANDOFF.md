# FileSender Remote V3 — Developer Handoff

This branch contains the current Remote V3 production tree for FileSender.

## Product architecture

- Sender and Render Station can be on different networks and locations.
- Supabase is the production transport/control plane.
- Rendering happens locally on the Render Station with Adobe Media Encoder.
- The app is online only while FileSender is open; closing it stops the station worker/heartbeat.

## User-facing rules

Sender:
- Username + password only.
- No email, pairing code, IP address, or port entry.
- Render Stations are selected by name and cloud status.
- SEND is disabled when the selected station is offline.
- Busy stations can receive jobs and queue them.
- `.prproj` files and Premiere project folders can be dragged in.
- The same project can be sent repeatedly; each send is a new job.
- The original project is never modified or permanently duplicated.

Render Station:
- Opening FileSender makes the station online automatically.
- Closing FileSender makes it offline.
- No Go Online / Go Offline controls.
- No pairing-code UI.
- Local project storage and retention are configurable.
- `Accept incoming jobs automatically` controls automatic job acceptance.

## Production source boundaries

```text
src/core/      pure application logic
src/remote/    Supabase auth, station, job, storage and transfer logic
src/render/    Adobe Media Encoder integration
src/ui/        PySide6 UI
supabase/      reproducible database/RLS/realtime/storage migrations
tests/         active production tests
installer/     PyInstaller + Inno Setup
assets/        FileSender branding
```

Legacy LAN source is not part of the production runtime. Do not restore direct TCP, UDP discovery, pairing, or manual IP/port controls.

## Current validation status

The latest AI checkpoint reported 103 automated tests passing. The repository maintainer also verified that the active Python source compiles with `python -m compileall -q src tests scripts`.

That does NOT prove:

- live Supabase authentication/RLS
- real Storage transfer
- two-network operation
- Windows/PySide6 UI behavior
- real Premiere Pro / Media Encoder automation
- final installer install/uninstall

Those remain release-gate tests.

## Handoff rule

The Other AI writes code and provides complete ZIPs/change reports.
The repository maintainer uploads/organizes GitHub and handles merges.

Do not claim GitHub or live-service testing unless it actually happened.
