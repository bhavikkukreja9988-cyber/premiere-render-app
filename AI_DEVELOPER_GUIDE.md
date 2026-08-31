# AI Developer Guide — Remote V3

Read this before modifying the project. Remote V3 is the target architecture. Do not redesign unrelated parts of the application.

## Product

FileSender is one Windows application with two roles: Sender and Render Station.

The Sender and Render Station may be in different homes and different networks. They communicate through Supabase over the internet. The Render Station performs the actual Adobe Premiere Pro / Media Encoder render locally.

The app works only while it is open. Closing FileSender stops its remote station worker/heartbeat; no Windows service, scheduled task, or hidden background FileSender process should remain.

## Required user experience

### Sender
- No IP address entry in normal use.
- No port entry.
- No pairing code.
- Automatically show registered Render Stations and their online/offline status.
- Remember the selected station.
- Disable SEND when the selected station is offline.
- Allow the same Premiere project to be sent repeatedly; every send is a new Job ID.
- Support drag-and-drop of a `.prproj` file or Premiere project folder.
- Do not modify or permanently duplicate the original Sender project.

### Render Station
- No Go Online / Go Offline buttons.
- No pairing-code UI.
- Opening FileSender makes the station online automatically.
- Closing FileSender makes it offline.
- Show station name, status, and local IP only as informational/debug data.
- Provide one main setting: `Accept incoming jobs automatically`.
- If enabled, jobs are downloaded and queued automatically.
- If disabled, show Accept / Reject controls for pending jobs.
- Persist the local project workspace and retention settings.

## Authentication

Use simple Supabase username + password from the user's perspective.

The UI must show only:
- Username
- Password
- Log In

No email, magic link, OTP, or pairing code.

Internally, the current implementation maps the username to a synthetic email because Supabase Auth uses email/password accounts. Keep that implementation centralized and do not expose the synthetic email to users.

Persist the authenticated session locally so normal application restarts do not require another login.

Never put a Supabase secret/service-role key or database password in the desktop application.

## Supabase

Project:
File Sender

Project URL:
https://dyvhlaljbgpyywrofrbg.supabase.co

Client configuration uses the Supabase publishable key. Keep privileged secrets out of source control and out of the executable.

Use:
- Supabase Auth
- Supabase Postgres
- Supabase Storage
- Supabase Realtime
- Edge Functions only for small control-plane/backend operations when needed

Do not proxy large Premiere uploads/downloads through Edge Functions.

Use private Storage buckets and authenticated/scoped access.

## Remote architecture

Target flow:

Sender PC
  -> Supabase Storage / Database / Realtime
  -> Render Station
  -> local Premiere Pro / Adobe Media Encoder
  -> Supabase
  -> Sender PC

Do not require:
- Same LAN
- Direct TCP Sender -> Station
- UDP LAN discovery
- Router port forwarding
- Static/public IP configuration
- Exposing the Render Station's TCP port to the internet

## Station presence

Station identity is stable and does not depend on IP address.

Persist a Station ID and station name. The station sends periodic heartbeat/last_seen updates while FileSender is open.

The Sender determines availability using the station's cloud status/last_seen, not by testing a local IP.

If heartbeat stops beyond the configured timeout, the station is OFFLINE.

## Sender offline rule

This is mandatory:

If the selected Render Station is offline, SEND must be disabled.

If it becomes offline before the transfer starts, do not create/upload a large job.

If it disconnects after a job is created or uploaded, do not lose the job. Keep the cloud job recoverable and allow the Render Station to continue when it reconnects.

## Job model

Keep Project and Job separate.

A Project is the Premiere project/files.

A Job is one render request.

Example:
MyVideo -> Job-001
MyVideo -> Job-002
MyVideo -> Job-003

Never reject Job-002 just because Job-001 has identical file hashes.

Use a unique backend Job ID (UUID recommended) and a readable display label such as `Job-001`.

Recommended lifecycle:
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

Adapt the existing JobState/remote state models rather than creating duplicate business logic unnecessarily.

## Storage

Use job-specific private storage paths such as:

project-files/user/{user_id}/jobs/{job_id}/project/...
render-results/user/{user_id}/jobs/{job_id}/output/...

Large files must use resumable/chunked transfer.

Cloud storage is temporary job transport, not a permanent file drive.

Preferred lifecycle:
Sender uploads project -> Render Station downloads -> renders -> uploads MP4 -> Sender downloads -> safe cloud cleanup.

Never delete files still required by an active/recoverable job.

## Local Render Station workspace

Keep configurable local storage, e.g.:

C:\PremiereRenderStation\Jobs\{job_id}\

Every job gets its own workspace. Never let repeated submissions overwrite one another.

Retention is for completed, safely returned projects only.

## Delete-after-return

Keep the option:
`Delete received project after successful delivery`

It affects the Render Station copy only. It must never delete or modify the original Sender project.

## Project handling

The user should never have to manually create a ZIP.

The app may internally stage/package/chunk data, but temporary staging must be cleaned automatically.

Validate all project paths before writing.

Hash files with SHA-256 for integrity and verification.

If the project references media outside the selected project folder, warn the user before sending.

## Media Encoder

Preserve the existing Media Encoder / JSX implementation where possible.

Render flow:
receive -> validate -> local workspace -> queue Media Encoder -> monitor -> verify MP4 -> upload result.

Media Encoder should run minimized/below-normal priority without stealing focus, as established by the existing implementation.

Do not claim real Adobe integration is verified until tested on a real Windows machine with the installed Adobe version.

## Architecture boundaries

Keep these concerns separate:
- `src/core`: business logic, manifests, jobs, workspace, validation; no Qt and no network implementation details.
- `src/remote`: Supabase transport/services/auth/stations/jobs/storage/realtime.
- `src/render`: Media Encoder and rendering pipeline.
- `src/ui`: PySide6 presentation and event wiring.

UI must not contain raw Supabase/database logic.

## Legacy LAN code

The repository contains V2 LAN code under `src/network/` and related documentation.

It is legacy reference/fallback code only. It is NOT the target Remote V3 architecture.

Do not extend LAN discovery, pairing codes, direct TCP, or UDP broadcast as the primary solution.

Before final release, remove or isolate obsolete LAN-only UI/configuration so the normal product does not expose:
- Go Online
- Go Offline
- Pairing code
- Manual IP/port entry

## Testing

Run:

python -m unittest discover -s tests -t .

Keep automated tests passing.

Add tests for:
- username/password auth
- session restore
- station registration
- heartbeat and offline detection
- station listing
- SEND disabled while offline
- repeated submissions of the same project
- storage authorization
- resumable upload/download
- job recovery after disconnect
- automatic vs manual job acceptance
- retention/cleanup
- result verification

Do not edit tests just to force a pass.

Automated tests do not prove live Supabase, Windows UI, two-network transfer, or real Media Encoder behavior.

## Installer

Final product is a normal Windows installer named:
`FileSender.exe`

Uninstall must work through Windows Settings -> Apps -> Installed Apps and Control Panel -> Programs and Features.

No command-line uninstall.

## Development order

1. Finish Supabase schema/RLS/storage and username/password auth.
2. Finish stable station identity and online/offline heartbeat.
3. Finish Sender station selection and offline SEND gate.
4. Finish remote resumable project transfer.
5. Connect remote jobs to the existing local render pipeline.
6. Finish MP4 return and verification.
7. Finish retention and delete-after-return.
8. Remove/hide legacy LAN UI/config from normal product flow.
9. Build installer.
10. Test on two real Windows PCs using different networks.
11. Test real Premiere Pro + Adobe Media Encoder.

## Handoff

The Other AI develops code and provides complete ZIPs/change reports.

The repository maintainer handles GitHub uploads, branch organization, and merges.

Do not claim GitHub has been updated unless it actually has been.
