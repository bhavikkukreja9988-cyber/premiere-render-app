# FileSender

FileSender is a Windows desktop app for sending Adobe Premiere Pro projects to a remote Render Station, rendering them with Adobe Media Encoder, and receiving the finished MP4 back.

The Sender and Render Station can be in completely different locations and on different networks. The normal product uses Supabase over the internet; it does not require LAN discovery, direct TCP connections, IP entry, port forwarding, or pairing codes.

## Normal workflow

### Sender

1. Open FileSender and sign in with a username and password.
2. Choose a Render Station shown by name.
3. The station must be **Online** before **SEND** is enabled.
4. Drag a `.prproj` file or a Premiere project folder into the drop area.
5. Review the detected sequence/preset and output location.
6. Click **SEND**.
7. The project uploads, renders on the selected station, and the MP4 returns automatically.

The Sender never needs the station's IP address, port, pairing code, or a manually created ZIP. The same project may be sent repeatedly; every send creates a separate Job.

### Render Station

1. Install FileSender on the PC that has Premiere Pro / Adobe Media Encoder.
2. Sign in with the family username and password.
3. Enable the Render Station role.
4. Choose the local project-storage location.
5. Optionally enable **Accept incoming jobs automatically**.
6. Leave FileSender open when you want the PC to be available for rendering.

Opening FileSender makes the station online automatically. Closing FileSender stops its cloud worker and heartbeat and marks it offline. There is no normal-use **Go Online**, **Go Offline**, or pairing-code workflow.

## Important behavior

- **Offline station:** SEND is disabled and the worker re-checks station availability immediately before creating the cloud job.
- **Busy station:** a busy station remains sendable; jobs queue behind existing work.
- **Repeated sends:** identical projects are never rejected just because their hashes match. Each send is a new Job.
- **Sender originals:** the original project is never modified, moved, or permanently duplicated by FileSender.
- **Render workspaces:** each job gets an isolated local workspace on the Render Station.
- **Cleanup:** completed received projects can be removed automatically according to the Render Station retention setting. Cloud transfer files are temporary transport data.
- **Result delivery:** returned MP4 files are checksum-verified before the job is marked complete.

## Architecture

```text
Sender PC
   |
   | HTTPS / authenticated API
   v
Supabase
   |-- Auth
   |-- Postgres jobs/stations/events
   |-- Private Storage
   |-- Presence/status polling
   v
Render Station PC
   |
   v
Local job workspace
   |
   v
Adobe Media Encoder
   |
   v
Rendered MP4
   |
   v
Supabase Storage
   |
   v
Sender downloads and verifies result
```

The old V2 LAN implementation is historical reference only and is not part of the Remote V3 production path.

## Repository layout

```text
src/
  core/              business logic, manifests, jobs, workspace, retention
  remote/            Supabase auth, stations, jobs, storage, transport
  render/            Media Encoder integration and render queue
  ui/                PySide6 desktop UI

supabase/
  migrations/        reproducible database/RLS/realtime/storage setup
  functions/         backend functions only when required

assets/              FileSender.ico

tests/               automated core + remote tests
scripts/             Windows build and preflight scripts
installer/           PyInstaller + Inno Setup configuration
docs/                architecture, setup, build, health, and release docs
```

## Build the Windows installer

On a Windows build PC, run:

```text
scripts\build_installer.bat
```

The script prepares dependencies, runs the automated tests, builds the PyInstaller application, and creates:

```text
dist_installer\FileSender.exe
```

That installer is what normal Sender and Render Station users install. They do not need Python or developer tools.

See [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md) for the complete Windows build procedure.

## Supabase setup

The project is configured for the existing File Sender Supabase project using the public project URL and publishable key in `src/remote/config.py`.

Before the first live test, apply the migrations in `supabase/migrations/` using [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md).

Never place a Supabase secret/service-role key, database password, or other privileged credential in the desktop application or repository.

## Testing

Run:

```text
python -m unittest discover -s tests -t .
```

The automated suite is designed not to require a live Supabase connection, PySide6, or Adobe software. Passing those tests does not prove the live network, real Windows UI, or real Media Encoder integration.

## Release readiness

Before merging Remote V3 into `main`, verify:

- Live Supabase username/password authentication
- RLS and private Storage access
- Sender ↔ Render Station on two different networks
- Offline SEND blocking
- Large-file/resumable transfer
- Repeated sends of the same project
- Real Premiere Pro / Adobe Media Encoder rendering
- Automatic result return and checksum verification
- Retention and delete-after-delivery
- FileSender.exe installation and Windows uninstall

See [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).
