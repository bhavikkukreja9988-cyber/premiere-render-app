# AI Developer Guide — FileSender Remote V3

Read this before changing the project. Preserve working parts and make focused changes. Do not redesign unrelated systems.

## Product

FileSender is one Windows application with Sender and Render Station roles. Sender and Render Station can be on completely different networks and physical locations.

The production transport is Supabase over the internet. The old V2 LAN implementation is legacy/reference material only and must not become the primary path again.

## Non-negotiable UX

### Sender

- No normal-use IP address entry.
- No port entry.
- No pairing code.
- Show registered Render Stations by name with cloud-derived Online / Busy / Offline status.
- Disable **SEND** while the selected station is Offline.
- Re-check station availability immediately before creating a cloud job.
- Busy stations remain sendable because jobs can queue.
- Remember the selected station.
- Support drag-and-drop of either a `.prproj` file or a Premiere project folder.
- Do not permanently duplicate or modify the Sender's original project.
- The same project may be sent repeatedly; every send is a new Job.

### Render Station

- Opening FileSender starts the remote station worker and heartbeat automatically.
- Closing FileSender stops the worker and marks the station offline.
- No **Go Online** / **Go Offline** controls.
- No pairing-code UI.
- Local IP may exist only as diagnostic information and must never be required for connection.
- **Accept incoming jobs automatically** controls whether a newly uploaded job starts without operator approval.
- Keep the local project storage location and retention setting configurable.
- Do not leave a hidden FileSender background process running after the app closes.

## Authentication

User-facing authentication is only:

```text
Username
Password
Log In
```

No email, magic link, OTP, or pairing code should be requested from the user.

The current Supabase adapter maps the username to a synthetic email identity internally because Supabase email/password Auth expects an email-shaped identifier. This implementation detail must never appear in the UI.

Persist the authenticated session so normal launches do not require another login. Never embed a Supabase secret/service-role key or database password in the desktop application.

## Supabase

Project:

```text
File Sender
https://dyvhlaljbgpyywrofrbg.supabase.co
```

The client uses the public project URL and publishable key. Sensitive backend credentials remain server-side and out of source control.

Use:

- Supabase Auth
- Supabase Postgres
- private Supabase Storage
- authenticated/scoped database and storage access
- the current polling presence/status model for the synchronous desktop client

Do not proxy large Premiere uploads/downloads through an Edge Function.

Large transfers use direct Storage access with resumable/chunked transfer.

## Station identity and presence

Station identity is stable and independent of IP address.

Persist:

- station ID
- station name
- owner/user ID
- status
- last_seen
- app version
- capabilities

While FileSender is running in Render Station mode, update heartbeat/last_seen. If heartbeats stop beyond the configured timeout, the station is Offline.

## Sender offline rule

This is mandatory:

```text
Offline station -> SEND disabled -> no large upload
```

Also perform a second availability check in the worker immediately before job creation to close the race between UI state and actual station state.

If a station becomes unavailable after a job is created/uploaded, keep the job recoverable. Do not delete cloud data required by the job.

## Jobs

Keep Project and Job separate.

Project = Premiere project and its files.

Job = one render request.

Example:

```text
MyVideo -> Job-001
MyVideo -> Job-002
MyVideo -> Job-003
```

Never de-duplicate jobs using content hashes. Hashes are for integrity, resume, and verification.

Use a backend UUID plus a readable display label.

Recommended remote states:

```text
created
uploading
uploaded
waiting_for_station
downloading
queued
rendering
encoded
uploading_result
ready_for_download
downloading_result
complete
failed
cancelled
```

## Storage

Private buckets:

```text
project-files
render-results
```

Object layout:

```text
user/{user_id}/jobs/{job_id}/project/...
user/{user_id}/jobs/{job_id}/output/...
```

Every job has isolated paths.

For large files, use resumable/chunked application-level transfer. Chunk discovery must list the containing folder and filter object names rather than assuming Storage `list()` treats a complete object path as a prefix.

Storage cleanup must recursively find descendants under the job prefix. Never delete an active or recoverable job's files.

## Database and RLS

The migrations must be reproducible from the repository.

RLS must ensure a signed-in account can only access its own stations, jobs, job files, job events, and storage objects.

The current release intentionally uses simple username/password authentication for family use. Do not add email collection to the UI.

## Render pipeline

Preserve the existing local render machinery:

```text
remote job
 -> local job workspace
 -> existing JobStore / RenderManager
 -> Media Encoder
 -> output verification
 -> cloud result upload
```

Media Encoder should run minimized/below-normal priority without stealing focus.

The Render Station should automatically install the JSX agent before selecting the render backend.

If Media Encoder is genuinely unavailable, Settings must make the manual fallback visible instead of silently waiting.

## Architecture boundaries

Keep these boundaries:

```text
src/core      pure business logic
src/remote    Supabase/cloud transport and remote services
src/render    Media Encoder/render execution
src/ui        PySide6 presentation
```

The UI must not contain raw database logic.

The normal product must not expose legacy LAN UI or settings.

## Legacy/reference material

Legacy LAN implementation should remain outside the production source tree, under an explicitly named archive/reference location if retained.

It is not part of the Remote V3 runtime.

Do not restore direct TCP, UDP discovery, pairing-code authentication, manual IP entry, or Go Online/Go Offline controls to the production workflow.

## Configuration

Client configuration is centralized. Only the public Supabase URL and publishable key belong in the desktop client.

Never commit:

- service-role/secret keys
- database passwords
- private credentials
- user session tokens

## Installer

Final product installer:

```text
FileSender.exe
```

It must bundle the application runtime and required dependencies so normal users do not need Python or developer tools.

Uninstall must work through Windows Settings -> Apps and Control Panel -> Programs and Features.

The FileSender Windows icon is `assets/FileSender.ico` and should be used for the executable, installer, shortcuts, title bar, and taskbar.

## Testing

Run:

```powershell
python -m unittest discover -s tests -t .
```

Automated tests should not require PySide6, a live network, or Adobe software.

Do not modify tests simply to force them to pass.

A passing fake-transport suite does not prove live Supabase, two-network transfer, Windows UI, or real Media Encoder automation.

Before release, test on real Windows machines:

1. username/password login against the live Supabase project
2. station registration and heartbeat
3. offline SEND blocking
4. two different networks
5. large/resumable transfer
6. repeated sends of the same project
7. real Premiere Pro / Adobe Media Encoder render
8. MP4 return/checksum verification
9. retention and delete-after-delivery
10. FileSender.exe install/uninstall

## Handoff

The Other AI develops code, runs automated tests, and provides complete repository ZIPs plus change reports.

The repository maintainer handles GitHub uploads, branch organization, and merges.

Never claim GitHub was updated unless it actually was.
