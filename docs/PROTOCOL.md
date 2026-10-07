# FileSender Protocol (3.x)

Version 3.x uses authenticated Supabase database and private Storage operations over HTTPS. (Version 4.0 will move file transfer to direct PC-to-PC connections, with Supabase used for coordination only — see `DESIGN_V4.md`.)

## Authentication

There is no login screen. Each **family code** maps to its own Supabase account
(`family-<hash>@filesender.local`, derived password of 52 characters), signed
into silently; the first PC to use a code creates the account. See
`AI_DEVELOPER_GUIDE.md` → Accounts and security.

## Station presence

The Render Station registers a stable Station ID with its PC name and family
code, then sends a heartbeat every 15 seconds. Supabase stamps `last_seen`
with its own clock (migration 007), and every PC compares against Supabase's
clock, so differences between PC clocks don't matter. A PC is Online when its
`last_seen` is within 45 seconds. Busy is separate and remains sendable.

## Job lifecycle

```text
created
  -> uploading
  -> uploaded
  -> waiting_for_station
  -> downloading
  -> queued
  -> rendering
  -> encoded
  -> uploading_result
  -> ready_for_download
  -> downloading_result
  -> complete
```

Failure/cancellation may end in `failed` or `cancelled`.

## Project transfer

Every Send action creates a unique Job ID. Identical project hashes are allowed across different jobs.

Project metadata is recorded in `jobs`; manifest entries are recorded in `job_files`.

Storage paths:

```text
project-files/user/{user_id}/jobs/{job_id}/project/...
render-results/user/{user_id}/jobs/{job_id}/output/...
```

Large files use application-level chunk objects plus a manifest. Interrupted uploads reuse parts that are already present. Interrupted downloads reuse complete local chunks.

## Render result

The Render Station uploads the finished output and records its SHA-256. The Sender verifies the checksum before marking the Job complete.

## Reliability

The station has an independent recovery sweep in addition to status polling. A missed status update should not permanently strand a queued job.

The app reconnects by itself after a network loss (retrying after 5, 10, 20, 30
and then every 60 seconds) and renews an expired session automatically.

Cloud files are temporary: removed when a job completes, when a send fails or
is cancelled, and by a family-wide sweep 10 minutes after any job ends.

The Sender re-polls job state while waiting for the result and retries transient errors.

If the station is Offline before job creation, Send is blocked. If it goes Offline after a job exists, the cloud job remains recoverable.

## Security

Database rows are protected by RLS. Storage buckets are private. Client code must never contain a service-role/secret key or database password.

## History

The original LAN version used a framed TCP protocol, UDP discovery and pairing
codes; that code has been removed. Version 4.0 reintroduces **direct**
connections in a new form (hole punching coordinated through Supabase, no
manual IPs, ports or pairing codes) — see `DESIGN_V4.md`.
