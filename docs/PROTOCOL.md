# Remote V3 Transport

Remote V3 does not use the old LAN wire protocol as the primary transport.

Sender and Render Station communicate through Supabase over HTTPS/Realtime and private Storage. They can be on different networks and in different locations.

## Control plane

Supabase Database stores:

- users / authenticated sessions
- stations
- station online state / last_seen
- jobs
- job files / hashes
- job events

Supabase Realtime provides live updates for station presence and job status where available.

## File plane

Large project files and returned MP4s use private Supabase Storage with resumable/chunked transfer.

Conceptual paths:

```text
project-files/user/{user_id}/jobs/{job_id}/project/...
render-results/user/{user_id}/jobs/{job_id}/output/...
```

Do not route multi-gigabyte files through an Edge Function.

## Job flow

```text
Sender authenticates
  -> verify selected station is online
  -> create a new Job ID
  -> upload project files
  -> mark job UPLOADED
  -> Render Station receives job
  -> download project
  -> queue/render locally
  -> upload and checksum MP4
  -> mark READY_FOR_DOWNLOAD
  -> Sender downloads and verifies MP4
  -> mark COMPLETE
  -> safely clean temporary cloud files
```

The exact internal API calls may change; the job state transitions are the important contract.

## Offline behavior

If a station is offline before Send begins, the Sender must not start the transfer.

If connectivity is lost after job creation, keep the job recoverable. Resume when connectivity returns.

If the Render Station is offline, it must not be considered available merely because its last known IP is reachable locally.

## Authentication

The user-facing login is only username + password.

The implementation may map the username to a synthetic email for Supabase Auth, but that value is internal and never shown to users.

Never send or store Supabase secret/service-role credentials in the desktop client.

## Security contract

- All remote traffic uses HTTPS/TLS and Supabase authenticated access.
- Storage buckets remain private.
- RLS limits rows/files to authorized users/stations/jobs.
- Every received file is checked against its expected SHA-256.
- Paths are validated before writing to the local workspace.
- The legacy LAN TCP/UDP protocol must not be exposed to the public internet.

## Legacy protocol

The previous PRAP/2 TCP/UDP protocol is retained in the repository only as migration/reference material. Its pairing-code, LAN discovery, and direct-socket behavior are not part of the Remote V3 product contract.
