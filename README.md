# FileSender / Premiere Render App

A Windows application for sending Adobe Premiere Pro projects from one PC to a remote Render Station, rendering them with Adobe Media Encoder, and automatically returning the finished MP4.

The Sender and Render Station do NOT need to be on the same network or in the same location.

## Remote V3 architecture

```text
Sender PC
   |
   | HTTPS / Supabase Storage + Realtime
   v
Supabase
   |
   | HTTPS / Realtime
   v
Render Station PC
   |
   v
Adobe Media Encoder
   |
   v
Rendered MP4
   |
   v
Supabase
   |
   v
Sender PC
```

Supabase provides authentication, station registration, job coordination, realtime status, and temporary cloud storage. The Render Station performs the actual Premiere Pro / Adobe Media Encoder render locally.

## User experience

### Render Station

Open FileSender and sign in with a username and password.

The Render Station automatically becomes online while the application is open and goes offline when the application is closed. It does not run as a hidden background service after the app is closed.

There is no normal-use pairing code, Go Online button, or Go Offline button.

The Render Station can show its local IP address as informational/debug information only. The Sender does not use the IP address to connect.

The Render Station has an **Accept incoming jobs automatically** setting.

- Enabled: incoming jobs are accepted automatically.
- Disabled: the station shows an Accept / Reject prompt.

### Sender

The Sender sees the registered Render Stations automatically through Supabase.

The user does not need to enter an IP address or port.

If the selected Render Station is offline, the Send button is disabled.

The user can drag either a `.prproj` file or a Premiere project folder into the Sender and click Send.

The same Premiere project may be sent multiple times. Every Send creates a separate Job ID and independent render workspace.

The original Premiere project on the Sender is never moved, modified, or permanently duplicated.

## Project transfer

FileSender performs packaging, hashing, upload, download, verification, and resume internally. Users do not need to create ZIP files manually.

Large files use chunked/resumable transfer so interrupted multi-gigabyte transfers can continue rather than restarting from zero.

Files are verified with SHA-256 after transfer.

## Jobs

A Project and a Job are different concepts.

A project may produce multiple independent jobs:

```text
MyVideo
  -> Job-001
  -> Job-002
  -> Job-003
```

Identical project hashes do NOT cause a new job to be rejected.

## Receiver storage

The Render Station stores each job in its own workspace under the user-selected storage location.

Example:

```text
C:\PremiereRenderStation\
    Jobs\
        Job-001\
        Job-002\
        Job-003\
```

Completed jobs can be automatically deleted according to the configured retention period.

The Sender can also request deletion of a received job after successful MP4 delivery.

## Windows installer

The project produces a normal Windows installer named:

```text
FileSender.exe
```

Build it on Windows with:

```text
scripts\build_installer.bat
```

The finished installer is produced at:

```text
dist_installer\FileSender.exe
```

The installed application must appear in Windows Settings → Apps and Control Panel → Programs and Features for normal uninstall.

## Supabase

The Remote V3 backend uses:

- Supabase Auth
- Supabase Postgres
- Supabase Storage
- Supabase Realtime
- Edge Functions only for small control-plane operations where required

The desktop application must never contain a Supabase secret/service-role key.

See `docs/SUPABASE_SETUP.md` for setup instructions and `supabase/migrations/` for reproducible database/storage configuration.

## Development

The Other AI is responsible for coding and automated testing.

The repository maintainer handles GitHub uploads, branch organization, pull requests, and merging.

The current remote development branch is:

```text
feature/v3-supabase-remote
```

Do not merge into `main` until real Windows, real Adobe Media Encoder, live Supabase, and two-different-network testing have passed.
