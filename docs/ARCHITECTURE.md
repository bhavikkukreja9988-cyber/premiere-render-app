# Remote V3 Architecture

Remote V3 is the target architecture for FileSender.

The Sender and Render Station can be in different homes and on different networks. They do not connect to each other directly.

## Layers

```text
UI (PySide6)
 |
Core business logic
 |
Remote services (Supabase)
 |\
 | \-- Auth / Stations / Jobs / Realtime
 |
 \---- Private Storage / resumable transfer
 |
Render pipeline
 |
Adobe Media Encoder + ExtendScript agent
 |
Output verification
```

## Main flow

```text
Sender PC
  |
  |  authenticate / create job
  v
Supabase Database + Storage + Realtime
  |
  |  station heartbeat / job assignment
  v
Render Station PC
  |
  |  download project
  v
Local job workspace
  |
  v
Adobe Media Encoder
  |
  v
Rendered MP4
  |
  |  upload result
  v
Supabase Storage
  |
  v
Sender PC downloads and verifies result
```

## Sender rules

- No normal-use IP address entry.
- No manual port entry.
- No pairing code.
- Show registered stations by name and cloud status.
- Remember the selected station ID.
- Disable Send while the selected station is offline.
- Every Send action creates a new Job, even when the project files are identical to a previous job.

## Render Station rules

- Opening FileSender starts the cloud station worker and heartbeat automatically.
- Closing FileSender stops the worker and marks the station offline.
- No Go Online / Go Offline buttons in the final UI.
- No pairing-code UI in the final UI.
- Local IP may be displayed only as informational/debug information.
- `Accept incoming jobs automatically` controls whether newly uploaded jobs are accepted without operator approval.

## Authentication

The user-facing authentication is only:

```text
Username
Password
Log In
```

The current client maps the username to a synthetic email internally for Supabase email/password Auth. This implementation detail must not appear in the UI.

Persist the session locally so normal launches do not require another login.

## Job lifecycle

Recommended states:

```text
CREATED
UPLOADING
UPLOADED
WAITING_FOR_STATION
DOWNLOADING
QUEUED
RENDERING
ENCODED
UPLOADING_RESULT
READY_FOR_DOWNLOAD
DOWNLOADING_RESULT
COMPLETE
FAILED
CANCELLED
```

The cloud database is authoritative for cross-network coordination. Local state is authoritative for the active render workspace and Media Encoder recovery.

## Storage

Use private, job-specific Storage paths:

```text
project-files/user/{user_id}/jobs/{job_id}/project/...
render-results/user/{user_id}/jobs/{job_id}/output/...
```

Large files use resumable/chunked transfer.

Cloud storage is temporary transport, not a permanent user drive.

## Security

- Use authenticated users and station identity.
- Protect database rows with Row Level Security.
- Keep Storage buckets private.
- Never embed Supabase secret/service-role credentials in the desktop app.
- Do not expose the Render Station's LAN TCP server to the internet.
- Do not require public IP or port forwarding.
- Validate paths and verify SHA-256 hashes before accepting files.

## Media Encoder

The existing render pipeline and ExtendScript agent should be reused.

The remote worker translates a cloud job into the existing local render pipeline:

```text
cloud job
 -> local workspace
 -> existing JobStore / RenderManager
 -> Adobe Media Encoder
 -> output verification
 -> cloud result upload
```

Media Encoder remains minimized/below-normal priority and must not steal focus.

## Legacy LAN implementation

The repository still contains the original LAN modules under `src/network/` and the old protocol documentation.

These are migration/reference code only. They are not the Remote V3 transport.

Do not extend them as the primary architecture.

Before final release, obsolete LAN UI/configuration should be removed or isolated so normal users never see pairing codes, manual IP/ports, Go Online, or Go Offline controls.

## Testing

Automated tests must remain independent of the live network where possible.

Real release validation requires:

1. Windows installer test
2. Username/password login against the live Supabase project
3. Two PCs on different networks
4. Station online/offline behavior
5. Large/resumable project transfer
6. Real Premiere Pro / Media Encoder render
7. Returned MP4 verification
8. Cleanup/retention

Passing unit tests alone is not sufficient to declare the remote system complete.
