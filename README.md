# Premiere Render App — Remote V3

FileSender is a Windows application for sending Adobe Premiere Pro projects to a remote Render Station, rendering them with Adobe Media Encoder, and returning the finished MP4.

The Sender and Render Station can be in completely different locations and on different networks. Supabase provides the cloud coordination, authentication, realtime status, and temporary file storage.

## User experience

### Sender

1. Sign in with username + password.
2. Select the Render Station shown by name.
3. The station must be **Online** before Send is enabled.
4. Drag a `.prproj` file or Premiere project folder into the drop area.
5. Click **Send**.
6. The project transfers to the station, renders, and the MP4 returns automatically.

No IP address, port, pairing code, ZIP creation, or port forwarding is required.

The same Premiere project may be sent repeatedly. Every send is a separate job.

### Render Station

1. Open FileSender.
2. Sign in with username + password.
3. Choose/confirm the Render Station role and station name.
4. Configure the local project storage location and retention period.
5. Optionally enable **Accept incoming jobs automatically**.

While FileSender is open, the station is online and sends a heartbeat to Supabase. When FileSender is closed, it stops its heartbeat and goes offline. There is no hidden background FileSender service.

The station's local IP may be displayed as informational/debug information only. It is not the remote connection mechanism.

## Architecture

```text
Sender PC
   |
   | HTTPS / Supabase
   v
Supabase
   |\
   | \-- Auth / Stations / Jobs / Realtime
   |
   \---- Private Storage
             |
             v
      Render Station PC
             |
             v
   Premiere Pro / Media Encoder
             |
             v
        Rendered MP4
             |
             v
        Supabase Storage
             |
             v
          Sender PC
```

The Render Station performs the actual Adobe rendering locally. Supabase is the remote control/storage layer, not the render engine.

## Authentication

The normal UI uses only:

- Username
- Password
- Log In

There is no email field, magic link, OTP, or pairing code.

The current implementation maps the username to a synthetic Supabase Auth email internally so Supabase email/password authentication can still be used without exposing email to the user.

Sessions are persisted locally so users normally remain signed in between application launches.

Never commit Supabase secret/service-role keys or database passwords.

## Supabase project

Project name: `File Sender`

Project URL:
`https://dyvhlaljbgpyywrofrbg.supabase.co`

The client uses the Supabase publishable key. Privileged secrets stay server-side and are never embedded in FileSender.exe.

See [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md).

## Transfer and jobs

Projects are uploaded to private, job-specific cloud storage using resumable/chunked transfer for large files.

A Project and a Job are different concepts:

```text
MyVideo -> Job-001
MyVideo -> Job-002
MyVideo -> Job-003
```

The same project can be submitted any number of times. Matching hashes must never cause a new job to be rejected.

The Sender's original project is never modified or permanently duplicated.

## Offline rule

If the selected Render Station is offline, the **Send** button must be disabled.

If the station disconnects after a job has been created/uploaded, the cloud job remains recoverable. When the station reconnects, it can resume pending work.

## Render Station settings

- Station name
- Project storage location
- Accept incoming jobs automatically
- Delete completed projects after N days
- Media Encoder location / preset

No Go Online/Go Offline controls are part of the final product.

## Media Encoder

The existing Media Encoder / ExtendScript integration is preserved where possible.

The target flow is:

```text
Receive project
  -> validate
  -> local job workspace
  -> Media Encoder queue
  -> render in background
  -> verify MP4
  -> upload result
```

Media Encoder should remain minimized/below-normal priority and should not steal focus from the Render Station operator.

## Local storage and cleanup

Each remote job gets its own local workspace on the Render Station.

Completed jobs may be deleted according to the configured retention period.

The optional Sender setting **Delete received project after successful delivery** only affects the Render Station copy. It never deletes the Sender's original project.

Cloud files are temporary transport data and should be deleted when the job is safely complete and no longer needs recovery.

## Legacy LAN code

The repository still contains the original V2 LAN implementation for migration/reference purposes.

The LAN implementation is **not** the final Remote V3 architecture.

Do not extend the legacy system as the primary path.

The final normal UI must not expose:

- Go Online
- Go Offline
- Pairing code
- Manual IP entry
- Manual port entry

## Build the Windows installer

Use:

```text
scripts\build_installer.bat
```

The expected installer is:

```text
dist_installer\FileSender.exe
```

The installed application must uninstall normally through Windows Settings or Control Panel.

See [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md).

## Testing status

Automated tests cover the core, remote, transfer, and rendering logic. The latest handoff reported 99 automated tests passing.

That does not prove the real system is finished. The following still require real testing:

- Live Supabase project
- Two different networks
- Multi-gigabyte internet transfer
- Windows UI
- Real Premiere Pro / Adobe Media Encoder
- Full installed EXE workflow

Do not call the system production-ready until the real end-to-end workflow has been verified.

## Developer documentation

- [`AI_DEVELOPER_GUIDE.md`](AI_DEVELOPER_GUIDE.md) — authoritative development rules
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Remote V3 architecture
- [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md) — Supabase setup
- [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md) — Windows installer build
- [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md) — Windows / Adobe setup
- [`docs/REMOTE_V3_GAP_CLOSING_CHANGE_REPORT.txt`](docs/REMOTE_V3_GAP_CLOSING_CHANGE_REPORT.txt) — latest handoff status
