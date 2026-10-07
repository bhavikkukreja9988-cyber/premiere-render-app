# AI Developer Guide — FileSender

Read `AI_HANDOFF.md` first. This guide is the rulebook and the map of the code
for version **3.3.0**. The agreed design for **4.0** is `docs/DESIGN_V4.md`;
where they differ, 4.0 work follows `DESIGN_V4.md`.

Preserve what works and make focused changes. Don't redesign unrelated parts.

## Product rules (binding)

**Setup and identity**
- No login screen, username, password, email, OTP or pairing code.
- First run asks for exactly two things: a **PC name** and a **family code**.
  Both can be changed in Settings → This PC; changing the family code shows a
  warning that the other PCs must change too.
- Every PC can both send and render. No Go Online/Offline controls: the app
  open = online, closed = offline. No hidden background process after closing.

**Sending**
- The user never enters an IP address or port.
- PCs are listed by name with Online / Busy / Offline status, only PCs with the
  same family code, and **never this PC itself**.
- SEND is disabled while the chosen PC is offline; the worker checks again
  just before creating the job. Busy PCs stay sendable (jobs queue).
- Drag-and-drop of a `.prproj` or a project folder; external-media warning.
- The same project can be sent any number of times — never de-duplicate jobs
  by hash (hashes are only for integrity and resume).
- The sender's original project is never modified, moved or copied.
- On failure, show the reason and a **Retry** button (a retry is a new job).

**Rendering**
- Media Encoder runs minimised, below-normal priority, without stealing focus.
- The JSX agent is installed automatically before the render backend is chosen;
  Settings → Render engine shows whether automation or the manual fallback is
  active.
- Render Station tab: received-jobs list with progress, **Cancel render**,
  **Clear selected job**, **Open job folder**.

## Accounts and security (`src/remote/auth.py`)

Each family code is its **own Supabase account**, signed into silently:

- `family_account_email(code)` → `family-<24 hex>@filesender.local`
- `family_account_password(code)` → `Fs1-<48 hex>` (52 characters)

Both are derived deterministically (SHA-256, different salts) from the
**normalised** family code (lower-case, single spaces), so every PC with the
same code reaches the same account. First use creates the account.

Hard limits learned from the live service:
- Supabase rejects passwords over **72 characters** (bcrypt). The fake
  transport enforces the same rule.
- **"Confirm email" must be OFF** in Supabase, or new accounts never get a
  session.

Row Level Security keys every row on `auth.uid()`, so different family codes
are isolated by the database itself, not just hidden by the app.

Only the public project URL and publishable key belong in the client
(`src/remote/config.py`). Never commit secret/service-role keys, the database
password, or session tokens.

## Connection and recovery

- `main_window.py` connects on a **background thread** and retries after
  5, 10, 20, 30, then every 60 seconds — the app never blocks on the network
  and recovers by itself (e.g. when it starts before Wi-Fi).
- `supabase_transport.py` routes every call through `_run()`: if the session
  has expired it signs in again silently and retries once.
- Network failures are `OfflineError`, never `AuthError` (otherwise a DNS
  failure looks like "account doesn't exist"). Plan limits are
  `QuotaExceededError`. User-facing messages (`transport.py`) must never
  mention signing in or passwords — a test enforces this.

## Presence (`src/remote/stations.py`)

- Heartbeat every **15 s**; a PC is offline after **45 s** without one
  (`remote/config.py`).
- All "online" decisions use **Supabase's clock**: migration 007 stamps
  `last_seen` server-side and `server_now()` corrects for this PC's clock
  (re-checked every 5 minutes). Without migration 007 it falls back to the
  local clock.
- Station IDs (`RS-xxxxxxxx`) are unique across the whole database. If an ID is
  taken by another account (after a family-code change), the worker takes a
  fresh ID and saves it (`StationIdTakenError`).

## Jobs and files (3.x)

Remote states:

```text
created -> uploading -> uploaded -> waiting_for_station -> downloading ->
queued -> rendering -> encoded -> uploading_result -> ready_for_download ->
downloading_result -> complete          (or failed / cancelled)
```

- The render PC publishes live progress (`progress`, `progress_label`):
  download 0-40 %, render 40 %, result upload 70-100 %.
- Storage buckets (private): `project-files`, `render-results`. Paths:
  `user/{user_id}/jobs/{job_id}/project/...` and `.../output/...`.
- Files ≥ 32 MB go in **8 MB chunks** with resume (`chunked_transfer.py`) —
  safely under the free plan's 50 MB per-file limit.
- Cloud files are temporary. They're removed when a job completes, when a send
  fails or is cancelled (sender side), and by every PC's background sweep for
  any finished/failed/cancelled job in the family **10 minutes** after it ends.
  Never touch files of a job still in progress or `ready_for_download`.
- Local received jobs follow retention (finished **and** failed/cancelled jobs
  after N days; in-progress jobs never automatically). Clearing a job by hand
  updates the cloud **first** — otherwise the recovery loop re-downloads it.

## Free plan limits (why 4.0 exists)

1 GB of stored files in total, 5 GB of downloads per month, 50 MB per file, and
the project pauses after ~7 days of inactivity. The sender warns at ~0.9 GB.

## Code map

```text
src/core/    config.py (AppConfig, family code), jobs.py (JobStore), manifest.py
             (folder scan, ignore list), project_probe.py (sequences, external
             media), retention.py, workspace.py, log.py, autostart.py,
             plugin_inbox.py (for the future Premiere plugin; not wired in yet)
src/remote/  auth.py, client.py, config.py, stations.py, jobs.py, storage.py,
             chunked_transfer.py, sender_service.py, station_worker.py,
             send_gate.py, transport.py (errors), supabase_transport.py (live),
             fake_transport.py (tests)
src/render/  media_encoder.py, pipeline.py (RenderManager), output_monitor.py,
             jsx/PremiereRenderAgent.jsx (agent folder must match APP_NAME)
src/ui/      main_window.py, setup_wizard.py, remote_sender_panel.py,
             remote_station_panel.py, settings_panel.py, history_panel.py,
             pending_jobs_panel.py, helpers.py, theme.py
tools/       connection_test.py (standalone direct-connection test)
```

The UI must not contain raw database logic. Tall tabs are wrapped in scroll
areas so the window can be resized.

## Database (`supabase/migrations/`)

Run in order: 001 schema, 002 RLS, 003 realtime, 004 buckets, 005 storage
policies, 006 family columns + per-account RLS, 007 server clock. The health
check in `docs/SUPABASE_CHECKLIST.txt` (Step 5) verifies all of it. 4.0
replaces these with one reset script and one setup file.

## Logging

`%APPDATA%\FileSender\logs\app.log` starts fresh each launch; the previous run
is kept as `app-previous.log`. Web-library request logging is suppressed to
warnings. Log tab → Save log to file exports both.

## Installer

- `scripts\build_installer.bat`: preflight → dependencies → tests → PyInstaller
  → Inno Setup → `dist_installer\FileSender.exe`. It refuses to build if any
  test fails.
- `installer/FileSender.iss` needs **Inno Setup 6.6.0+** (`CreateCustomForm`
  takes its size as arguments since 6.6.0).
- Uninstall removes `%APPDATA%\FileSender` and asks (with the folder size)
  whether to delete received projects too.
- Icon: `assets/FileSender.ico` (all entries BMP; PNG entries break
  PyInstaller with WinError 87).

## Testing

```text
python -m unittest discover -s tests -t .
```

No network, PySide6 or Adobe needed — `fake_transport.py` stands in for
Supabase. Keep it **faithful** to the real service (it enforces primary keys,
the 72-character password limit and per-account isolation); several real bugs
were hidden by a fake that was more lenient than Supabase.

Don't weaken tests to make them pass. When fixing a bug, add a test that fails
without the fix.

Tests can't prove the live service, two real networks, the Windows UI or real
Media Encoder — see `docs/RELEASE_CHECKLIST.md`.

## Delivering changes

- Deliver ZIPs with repo-relative paths, apply notes, and a regenerated
  `scripts/update_manifest.txt` (SHA-256 of every delivered file).
- The maintainer runs `python scripts\verify_update.py` after copying files
  and uploads to GitHub **as files** — pasting code into GitHub's web editor
  has corrupted a file before.
- Never claim live or GitHub testing that didn't happen.
