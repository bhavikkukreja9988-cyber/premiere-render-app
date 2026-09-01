# Windows setup and troubleshooting

## Render station PC

1. **Install the app** (or run from source) and open the **Render station** tab.
2. **Set the workspace** to a drive with room for incoming projects — a job
   needs roughly 1.5× the project folder size.
3. **Install the Media Encoder agent.** Click the button; it writes
   `PremiereRenderAgent.jsx` into
   `%APPDATA%\Adobe\Startup Scripts CC\Adobe Media Encoder\`.
4. **Restart Adobe Media Encoder** so it loads the agent at startup.
5. **Allow scripting** in Media Encoder:
   *Edit → Preferences → General → Allow Scripts to Write Files and Access Network.*
6. **Open the firewall** once, from an elevated PowerShell:

   ```powershell
   New-NetFirewallRule -DisplayName "Premiere Render App (TCP)" `
     -Direction Inbound -Protocol TCP -LocalPort 49872 -Action Allow -Profile Private
   New-NetFirewallRule -DisplayName "Premiere Render App (discovery)" `
     -Direction Inbound -Protocol UDP -LocalPort 49873 -Action Allow -Profile Private
   ```

7. Click **Go online** and note the IP address and 6-digit pairing code.

Verify the setup at any time:

```powershell
python -m src.main --check
```

## Editing PC

Nothing to install beyond the app. Pick the station from the list, enter the
pairing code, choose the project folder, send.

## Background rendering

The render runs without interrupting whoever is using the render PC. Media
Encoder is launched minimised, at below-normal priority, and never takes focus,
and the agent starts each batch automatically. You can keep working; renders
proceed behind your other windows. If you would rather watch, just un-minimise
Media Encoder from the taskbar — that does not affect the job.

## Troubleshooting

**No stations appear in the list.**
Broadcast is blocked (common on VPNs and guest networks). Type the station's IP
and port directly — everything else works normally.

**"Connection refused".**
The station app is closed, it is not online, or the firewall rule is missing.
The station must have the app open with **Go online** active.

**"wrong pairing code".**
The code changes when regenerated. Read it off the station's screen.

**Jobs stay queued and never render.**
Check the station's Media Encoder box. If it says *not reporting*: Media Encoder
is closed, the agent is not installed, or scripting is not allowed in
Preferences. The agent's own log is at
`%APPDATA%\PremiereRenderApp\ame\agent.log`.

**Media Encoder opens the project but renders the wrong sequence.**
The sequence name must match exactly, including case and trailing spaces. Leave
it blank to let Media Encoder use the project's default.

**Media offline in Media Encoder.**
The project references media outside the folder you sent. Use *File → Collect
Files* (or consolidate) in Premiere so everything lives under one folder, then
send that folder.

**The render finishes but nothing comes back.**
The sender must stay open — it polls, then downloads. If it was closed, reopen
it; the job stays on the station and the file is in the job's `output/` folder.

**Manual fallback.**
If the station shows the *Manual* backend, it will queue jobs and wait for a
file to appear in `<workspace>\jobs\<job_id>\output\`. Render it yourself in
Premiere or Media Encoder, drop the file there, and the return transfer happens
automatically.
