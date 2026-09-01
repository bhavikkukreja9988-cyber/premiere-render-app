# Windows setup

FileSender connects a Sender PC and a Render Station PC over the internet
through Supabase — they do not need to be on the same network, and there is
nothing to configure about IP addresses, ports, or pairing codes. This page
covers the one-time setup on each PC.

## Both PCs

1. Install FileSender (`FileSender.exe`) and launch it.
2. On first launch, sign in with a username and password. Everyone who
   should share render stations signs in with the same username and password —
   this is the simple shared family-account workflow.
3. During first-run setup, choose how this PC will be used: **Sender**,
   **Render Station**, or both. You can change this later in Settings.

No firewall rule is needed on either PC. FileSender only makes normal
outbound HTTPS connections to Supabase; nothing needs to accept an inbound
connection.

## Render Station PC

If you chose Render Station (or both), configure:

- **Station name** — the name shown to Senders.
- **Project storage location** — where received Premiere projects and media
  are stored while they render. Use a drive with enough free space for the
  projects you expect to receive.
- **Accept incoming jobs automatically** — on by default. Turn it off when
  you want an operator to approve each job with Accept/Reject.
- **Delete completed projects after** — optional cleanup for completed local
  received-project data. It never deletes the Sender's original project.
- **Adobe Media Encoder** — FileSender detects the installed encoder and
  installs its scripting agent automatically when the station starts.

### One Adobe setting is required

Open **Adobe Media Encoder** and enable:

**Edit → Preferences → General → Allow Scripts to Write Files and Access Network**

This Adobe setting must be enabled by the user; FileSender cannot safely
change it for you.

Opening FileSender puts the Render Station online automatically. Closing
FileSender stops the station worker/heartbeat and makes it offline. There is
no **Go Online**, **Go Offline**, IP, port, or pairing-code workflow.

## Sender PC

The Sender needs only the installed FileSender application and an internet
connection. It does not need Python, Git, Premiere Pro, Media Encoder, or
any developer tools.

After signing in:

1. Render Stations appear by name with **Online / Busy / Offline** status.
2. Select a station. An offline station cannot receive a new job and the
   **SEND** button is disabled.
3. Drag a `.prproj` file or Premiere project folder into the drop area, or use
   Browse.
4. Choose the sequence/preset/output settings.
5. Click **SEND**.

Busy stations remain sendable because jobs can queue. The same Premiere
project may be sent repeatedly; every send creates a new Job.

## Project files and external media

FileSender sends a project folder and validates/hash-checks the files that
are included. If the Premiere project references media outside the folder,
resolve that before sending (for example, collect/consolidate the project's
media in Premiere). The Sender should warn when it can detect external
references.

The Sender's original project is not modified, moved, or permanently
duplicated by FileSender.

## Troubleshooting

**No stations appear.**

Make sure the Render Station PC has FileSender open, is signed into the same
family account, and has the Render Station role enabled. It may take up to
the configured heartbeat timeout for status to update.

**Station says Offline while FileSender is open.**

Check that the Render Station has internet access and that FileSender can
reach Supabase. The station status is based on its heartbeat, not its local
IP address.

**SEND is disabled.**

Read the message below the button. Common reasons are: not signed in, no
project selected, project validation still running, or the selected station
is Offline.

**Jobs remain queued.**

Check **Settings → Render station → Render engine**. If Adobe Media Encoder
is unavailable, FileSender will show that instead of silently pretending that
automatic rendering is working. Make sure Media Encoder is installed and
that **Allow Scripts to Write Files and Access Network** is enabled.

**Media Encoder renders the wrong sequence.**

Make sure the selected sequence name matches the project exactly. Leaving
the sequence blank lets the render pipeline use the project's default
sequence where supported.

**The result does not return immediately.**

The Sender can be closed while the Render Station continues processing the
cloud job. Reopen FileSender later and it will resume status polling and
result download when the MP4 is ready.

**Manual render fallback.**

If automatic Adobe Media Encoder automation is genuinely unavailable, the
Render Station exposes the manual fallback state. The job remains recoverable
until a valid rendered output is provided, after which FileSender can return
it to the Sender.

## Developer-only check

From a source checkout, the local diagnostic command is:

```powershell
python -m src.main --check
```

Normal installed users do not need Python to use FileSender.
