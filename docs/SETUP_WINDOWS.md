# Windows setup

FileSender connects PCs over the internet through Supabase. They don't need
to be on the same network, and there's nothing to configure about IP
addresses, ports, firewalls, usernames or passwords.

Complete [SUPABASE_SETUP.md](SUPABASE_SETUP.md) once before any PC runs the
app.

## Every PC

1. Install FileSender (`FileSender.exe`) and open it.
2. The first time, you're asked for:
   - **Name this PC** — how it appears in other PCs' lists, e.g.
     "Bhavik's PC". Use a **different** name on each PC.
   - **Family code** — use the **same** code on every PC in your household.
     PCs with matching codes can send renders to each other.
   - **Where to store received projects**, and how long to keep them
     (7 days by default).
3. That's it. You're never asked again. Both can be changed later in
   **Settings → This PC**.

Every PC can both send and receive — there's no separate "sender" or
"station" mode. Opening FileSender puts the PC online; closing it takes the
PC offline.

## PCs that will render

Adobe Media Encoder must be installed. FileSender installs its own Media
Encoder scripting agent automatically the first time it runs — there's
nothing to click and no Media Encoder preference to change.

**Settings → Render engine** shows whether automated rendering is active.
If it says *manual*, Media Encoder wasn't found or isn't responding.

## Sending a project

1. Drag a Premiere project folder (or `.prproj`) onto the drop area.
2. Pick the PC to render on. Only **other** PCs with your family code are
   listed — never this one.
3. Pick a sequence, preset and output name, then **Send**.
4. Progress is shown live: uploading → the other PC downloading → rendering
   → uploading the result → downloading it back to you.
5. If a send fails, the reason is shown along with a **Retry** button that
   keeps all your choices.

## If something goes wrong

Open the **Log** tab and click **Save log to file…**. The log starts fresh
every time FileSender opens, so the saved file covers just this run (plus the
one before it). Send that file for help.

## Troubleshooting

**The other PC isn't in the list.**
Check both PCs use exactly the same family code (**Settings → This PC**) and
that FileSender is open on the other PC. Presence can take up to ~45 seconds
to update.

**"Not connected to the cloud."**
Check the internet connection. If it's fine, save the log — the most common
cause is "Confirm email" still being on in Supabase (see
SUPABASE_SETUP.md, step 2).

**Jobs sit waiting and never render.**
On the rendering PC, check **Settings → Render engine**. If it isn't Adobe
Media Encoder, confirm Media Encoder is installed, then restart FileSender.
The agent's own log is at `%APPDATA%\FileSender\ame\agent.log`.

**Media is offline on the rendering PC.**
The project references files outside the folder that was sent. In Premiere,
use **File → Project Manager** to collect everything into one folder, then
send that folder.

## Uninstalling

**Settings → Apps → FileSender → Uninstall.** All of FileSender's own data
in `%APPDATA%\FileSender` is removed. If the PC has received projects stored,
you'll be asked whether to delete those too.
