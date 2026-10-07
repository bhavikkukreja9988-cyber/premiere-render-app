# FileSender — Developer Handoff

Read this first, then `AI_DEVELOPER_GUIDE.md`. The agreed plan for the next
major version is in `docs/DESIGN_V4.md`.

## Where things stand (version 3.3.0)

FileSender sends Premiere Pro projects between PCs in **different houses**,
renders them with Adobe Media Encoder on the receiving PC, and returns the
video. In 3.x, Supabase carries everything: accounts, presence, jobs and the
files themselves.

### Proven on the real Windows PC with the live Supabase project

Taken from real application logs — nothing here is assumed:

- Installer builds and installs (`FileSender.exe`); the automated tests pass on
  Windows as part of that build.
- Silent sign-in to the family account (no login screen).
- Station registration and the 15-second heartbeat.
- The shared server clock (`server_time()` from migration 007) answers.
- Adobe Media Encoder 2026 is detected and the render backend starts.
- Closing the app marks the station offline.

### NOT yet proven (only covered by automated tests)

- A real send between two PCs — the second PC isn't set up yet.
- A real render returning a video.
- The uninstaller's clean-up dialog.
- A direct PC-to-PC connection between the two houses — run
  `tools/connection_test.py` (see `docs/CONNECTION_TEST_GUIDE.txt`) on both
  PCs first; its result decides how 4.0 is built.

## Product rules (still binding)

- **No login screen.** Setup asks only for a PC name and a family code.
- The user never enters an IP address, port or pairing code.
- Every PC can send and render; there are no "Go Online/Offline" controls.
- A PC never appears in its own send list.
- The same project can be sent any number of times; each send is a new job.
- The sender's original project is never modified, moved or duplicated.
- Never put a Supabase secret/service-role key or database password in the app
  or the repository.

## What changed since 3.2.0 (all covered by tests)

- Family-code accounts: a deterministic per-family Supabase account; the
  derived password is 52 characters (Supabase rejects more than 72).
- Reconnects automatically after network loss and after an expired session.
- Online status uses Supabase's clock (PCs with wrong clocks no longer look
  offline); station-ID clashes after a family-code change are fixed
  automatically.
- Failed/cancelled jobs are cleaned up (cloud files after 10 minutes, local
  files after the retention period); Render Station tab has a job list with
  Cancel render / Clear selected job.
- Clear error messages for storage-full and setup problems; a warning before
  sending a project too big for the free plan.
- Media paths containing "&" or URL-encoded spaces are read correctly.
- Logs start fresh each launch, can be saved from the Log tab, and no longer
  record every web request.
- `scripts/verify_update.py` + `scripts/update_manifest.txt` check that copied
  files arrived unchanged; `scripts/preflight.py` (build step 1) rejects any
  damaged Python file with its exact line.
- `tools/connection_test.py`: the direct-connection test for 4.0.

## Next steps

1. Run the connection test on both PCs and record the result.
2. Build 4.0 as described in `docs/DESIGN_V4.md` on a new branch
   (`feature/v4-direct`), keeping this branch as a working fallback.
3. The Premiere Pro plugin waits until 4.0 works.

## Working rules

- The developer AI writes code, runs the tests and delivers ZIPs with apply
  notes and an updated `scripts/update_manifest.txt`.
- The repository maintainer uploads to GitHub **as files** (never by pasting
  contents) and runs `python scripts\verify_update.py`.
- Never claim something was tested live unless a real log or screenshot shows
  it.
