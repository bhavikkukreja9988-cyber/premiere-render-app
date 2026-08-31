# Premiere Render App

A small Windows app for sending an Adobe Premiere Pro project to another PC on
your home network, rendering it there in Adobe Media Encoder, and getting the
finished MP4 back automatically.

Built for family use: Person A picks a project folder and sends it; the render
PC receives it, renders it quietly in the background, and returns the MP4 —
without interrupting whoever is using the render PC.

One app, two roles. The PC that edits runs it as a **Sender**. The PC that
renders runs it as a **Render Station**. There is no server, no accounts, no
payments, and nothing runs once the app is closed.

## How it works

```
Person A (Sender PC)                 Render Station PC
--------------------                 -----------------
pick project folder
        |
        |  send over the LAN  ------->  receive + verify
                                              |
                                        Media Encoder renders
                                        (background, minimised)
                                              |
   save the MP4  <-------  return + verify  <--+
```

The Sender drives everything, so only the Render Station needs a firewall
opening. Each step is its own connection, so a laptop sleeping through a long
render just reconnects afterwards instead of losing the job.

## Build the Windows installer (FileSender.exe)

The app ships as a normal Windows installer. On a Windows PC:

```
scripts\build_installer.bat
```

This checks your machine, builds the app, and produces the installer at
`dist_installer\FileSender.exe`. Run that to install the app like any other
program (Start Menu entry, uninstall via Windows Settings → Apps). People who
install it need **no** Python or developer tools.

Full, click-by-click instructions — including the two free tools to install
first — are in [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md). To check your PC is
ready before building, run `python scripts\preflight.py`.

## Run from source (for development)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

Other entry points:

```powershell
python -m src.main --station     # run a headless render station (no window)
python -m src.main --check       # check Media Encoder + agent, then exit
python -m unittest discover -s tests -t .
```

## Setting up the render PC (one time)

1. Open the app, go to the **Render station** tab.
2. Click **Install Media Encoder agent**, then restart Adobe Media Encoder.
3. In Media Encoder: **Preferences → General → Allow Scripts to Write Files
   and Access Network** (tick it).
4. Click **Go online**. Note the IP address and 6-digit code shown.

Full steps and firewall commands are in [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md).

The render runs in the background: Media Encoder opens minimised, at
below-normal priority, and never steals focus — so the render PC stays usable.

## Sending a project

1. On the editing PC, open the **Send a project** tab.
2. Pick the render station from the list (or type its IP) and enter the code.
3. Choose the project folder. The `.prproj` and its sequences are detected
   for you; pick a Media Encoder preset from the station's list and name the
   output.
4. Click **Send to render station**.

The app copies only what the station doesn't already have, waits through the
render, then downloads the MP4 and checks it before saving.

> **Tip:** in Premiere, use **File → Collect Files** (or Project Manager) so all
> media lives inside one folder before sending. Projects that point at media
> elsewhere on your drive will show as offline on the render PC.

## Network

- **TCP 49872** — project transfer and MP4 return (inbound on the station).
- **UDP 49873** — station discovery broadcast (optional; typing an IP works
  without it).

This is a home-LAN tool: traffic is not encrypted, so don't forward these ports
to the internet.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layers and data flow
- [`docs/PROTOCOL.md`](docs/PROTOCOL.md) — the wire protocol
- [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md) — setup and troubleshooting
- [`AI_DEVELOPER_GUIDE.md`](AI_DEVELOPER_GUIDE.md) — for anyone (or any AI)
  continuing the project

## Status

Working end to end in code, with an automated test suite (57 tests) covering
the protocol, transfer, resume, verification, job queue, job identity, repeated
sends of the same project, retention/cleanup, and a full send-render-return
cycle against a stub renderer. Still to verify on real hardware: the live Media
Encoder scripting hook and the on-screen UI, neither of which can be exercised
without Windows + Media Encoder. Run `python -m src.main --check` on the render
PC to confirm that half.

## Features

- **Send the same project as many times as you like** — each send is its own
  render job (`Job-001`, `Job-002`, …) with isolated storage. Your original
  project is never moved, copied permanently, or modified.
- **Automatic background render** — Media Encoder runs minimised, below-normal
  priority, no focus stealing.
- **Automatic MP4 return** — checksummed, resumable, saved where you choose.
- **Receiver-side cleanup** — optionally delete *received* projects after a set
  number of days. Only ever deletes safely-completed jobs; never touches ones
  that are transferring, rendering, failed, or incomplete.
- **Job history** — see every job's status, times, output and errors without
  opening a log file.
- **Settings** — one place for storage location, retention, station name,
  Media Encoder path, preset, pairing code, output folder, and startup options.
