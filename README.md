# FileSender

A Windows desktop app for families: send an Adobe Premiere Pro project from one
PC to another PC (the **Render Station**) in a different house, render it there
with Adobe Media Encoder, and get the finished video back automatically.

**Current version: 3.3.0** (Supabase transport). The next major version,
**4.0**, sends files directly PC-to-PC — see [`docs/DESIGN_V4.md`](docs/DESIGN_V4.md).

## Using it

**Setting up a PC (once)**

1. Install `FileSender.exe` and open it.
2. Enter a **name for this PC** (different on every PC) and a **family code**
   (the **same** on every PC in your household). That's all — there is no
   username, password, or login screen.
3. Choose where received projects are stored and how long finished or failed
   jobs are kept (7 days by default).

Every PC can both send and render. Opening FileSender puts the PC online;
closing it takes it offline.

**Sending a project**

1. Drag a Premiere project folder or `.prproj` onto the **Send a project** tab.
2. Pick the PC to render on. Only **other** PCs with your family code are
   listed.
3. Pick a sequence, preset and output name, then **Send**.
4. Progress is shown live; the finished video downloads to your output folder.
   If a send fails, the reason is shown with a **Retry** button.

**On the rendering PC**, the **Render Station** tab lists received jobs with
their progress, and lets you **Cancel render** or **Clear** a failed/stuck job.

**If something goes wrong:** Log tab → **Save log to file…**, and send the
file. The log starts fresh every time FileSender opens.

## Important limits (Supabase free plan)

In 3.x every project passes through Supabase Storage:

- **1 GB of stored files in total** — projects over about 1 GB can't be sent.
  FileSender warns when you pick one that large.
- **5 GB of downloads per month** (the render PC's download and yours both count).
- **Projects pause after ~7 days of low activity** — restore from the dashboard.

Version 4.0 removes the file-size limits by sending files directly between PCs.

## How it works (3.x)

```text
Sender PC ──HTTPS──► Supabase (accounts, PCs online, jobs, temporary files)
                          │
                          ▼
                  Render Station PC ──► local job folder ──► Media Encoder
                          │
                          └── rendered video ──► Supabase ──► Sender PC
```

Each family code is its own Supabase account; the database's Row Level
Security keeps families apart. Cloud files are temporary and deleted once a
job is delivered, failed or cancelled.

## Repository layout

```text
src/core/      business logic: config, jobs, manifests, retention, logging
src/remote/    Supabase: accounts, stations, jobs, storage, transfers
src/render/    Adobe Media Encoder integration (JSX agent, render queue)
src/ui/        PySide6 desktop UI
supabase/      database setup (migrations 001-007)
tools/         connection_test.py - checks two PCs can connect directly (for 4.0)
tests/         automated tests (no network, PySide6 or Adobe needed)
scripts/       build, preflight and file-integrity scripts
installer/     PyInstaller + Inno Setup (needs Inno Setup 6.6 or newer)
assets/        FileSender.ico
docs/          setup, design and release documents
```

## For developers

Start with [`AI_HANDOFF.md`](AI_HANDOFF.md) (current state) and
[`AI_DEVELOPER_GUIDE.md`](AI_DEVELOPER_GUIDE.md) (rules and architecture).

```text
python -m unittest discover -s tests -t .     # run the tests
scripts\build_installer.bat                   # build dist_installer\FileSender.exe
python scripts\verify_update.py               # check copied files arrived intact
```

Supabase setup and checks: [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md)
and [`docs/SUPABASE_CHECKLIST.txt`](docs/SUPABASE_CHECKLIST.txt).
Windows setup for users: [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md).

Never put a Supabase secret/service-role key or the database password in the
app or the repository — only the public URL and publishable key belong here.
