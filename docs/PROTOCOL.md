# FileSender Remote V3 Protocol

Remote V3 uses authenticated Supabase database and private Storage operations over HTTPS. The production client does not use direct Sender-to-Station TCP or UDP discovery.

## Authentication

User-facing:

```text
Username + Password
```

The username is internally mapped to a synthetic email-shaped Supabase Auth identity. The synthetic address is never shown to users.

## Station presence

The Render Station registers a stable Station ID and periodically updates `status`, `last_seen`, `app_version`, and `capabilities`.

The Sender treats a station as Online when its recent `last_seen` is within the configured timeout. Busy is separate and remains sendable.

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

The Sender re-polls job state while waiting for the result and retries transient errors.

If the station is Offline before job creation, Send is blocked. If it goes Offline after a job exists, the cloud job remains recoverable.

## Security

Database rows are protected by RLS. Storage buckets are private. Client code must never contain a service-role/secret key or database password.

## Legacy

The previous framed TCP protocol, UDP discovery and pairing authentication are historical reference only. They are not part of the Remote V3 runtime.
