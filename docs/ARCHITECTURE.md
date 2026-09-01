# FileSender Remote V3 Architecture

Remote V3 is the production architecture for FileSender.

Sender and Render Station may be in different homes and on different networks. They do not connect directly.

## System flow

```text
                    SUPABASE
        +-----------------------------+
        | Auth                        |
        | Postgres: stations/jobs     |
        | Private Storage             |
        | Status / polling            |
        +---------------+-------------+
                        |
              HTTPS     |     HTTPS
                        |
          +-------------+-------------+
          |                           |
       Sender PC                Render Station PC
          |                           |
          |                           +--> local workspace
          |                           +--> Media Encoder
          |                           +--> output verification
          |                           |
          +<------ returned MP4 ------+
```

## Layers

```text
PySide6 UI
    |
Core business logic
    |
Remote services
    |-- auth
    |-- stations
    |-- jobs
    |-- storage
    |-- status polling
    |
Supabase
    |
Local render pipeline
    |
Adobe Media Encoder + JSX agent
```

`src/core` remains free of Qt and network implementation details.
`src/remote` owns cloud integration. `src/render` owns local rendering. `src/ui` owns presentation/event wiring.

## Sender flow

```text
Select registered station
        |
Check cloud status
        |
Offline? --> block SEND
        |
Online/Busy
        |
Scan + hash project
        |
Re-check station status
        |
Create Job
        |
Upload project files to private Storage
        |
Wait for result state
        |
Download MP4
        |
Verify SHA-256
        |
Mark Job complete
```

Busy means the Render Station can still accept the job and queue it. Offline blocks sending.

## Render Station flow

```text
Open FileSender
      |
Authenticate / restore session
      |
Register station
      |
Heartbeat while app is open
      |
Find pending jobs
      |
Accept automatically OR ask operator
      |
Download + verify project
      |
Create isolated local job workspace
      |
Queue RenderManager
      |
Adobe Media Encoder
      |
Verify rendered output
      |
Upload MP4 to private Storage
      |
Mark result ready
      |
Wait for Sender acknowledgement
      |
Cloud cleanup / local retention
```

## Presence

Remote V3 uses `last_seen`/heartbeat as the source of truth for station availability. The current desktop client uses synchronous status polling and an independent station recovery sweep. This avoids coupling the production worker to an async Realtime event loop while still providing reliable recovery.

## Security

- Supabase Auth identifies the signed-in account.
- RLS isolates account-owned database rows.
- Storage buckets are private.
- Storage object paths include authenticated user ID and Job ID.
- Files are validated and SHA-256 verified.
- No direct TCP/UDP path is exposed to the public internet.

## Legacy

The old LAN implementation is historical/reference material only. It is not part of the Remote V3 runtime and must not be restored as the production transport.
