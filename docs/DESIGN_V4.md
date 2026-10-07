# FileSender 4.0 — design decisions

Agreed before development. Build only after the connection test
(`docs/CONNECTION_TEST_GUIDE.txt`) has been run on both real PCs.

## Why 4.0

Version 3 moved every file through Supabase Storage. On Supabase's free plan
that caps a project at about 1 GB (total storage) and roughly 5 GB of
downloads per month — too small for video work. It also polled so often that
the job list alone could eat the monthly bandwidth.

## 1. Files go directly from PC to PC

Supabase becomes a **message board only**: which PCs are online, which jobs
exist, and how two PCs can reach each other. Project files and rendered
videos never touch Supabase (except the fallback below).

The PCs are in **different houses**, so the main path is a direct internet
connection made by "hole punching": both PCs send to each other at the same
moment, using Supabase to swap addresses and coordinate. IPv6 is tried first
when both sides have it.

Order of attempts for each transfer:

1. Direct over IPv6
2. Direct over IPv4 (hole punching)
3. Same local network (if the PCs ever happen to be together)
4. **Fallback: Supabase Storage, small projects only** — only if every
   direct attempt fails. Limit about **700 MB** per project, which leaves room
   in the free plan's 1 GB for the rendered video on its way back. Anything
   larger gets a clear message instead of a failed upload.

**Both PCs must be on while files move** (agreed). The finished video waits
on the render PC and is delivered the next time the sender is online.

Open technical choice, to settle after the connection test: the reliable,
encrypted transfer protocol on top of the punched UDP path (the leading
option is QUIC via `aioquic`, which provides encryption, resending of lost
packets and speed control). Its speed must be measured on the real
connection before committing.

Security: only PCs in the same family account can open a connection; each
transfer is authorised by a one-time token published through Supabase, and
all data is encrypted in transit.

Windows Firewall will ask once per PC to allow FileSender — click **Allow**.

## 2. Keeping Supabase awake

Free projects pause after about 7 days without activity.

- While running, the app records when it last reached Supabase and sends a
  tiny request (the server time, a few bytes) once a day.
- A small **Windows scheduled task** does the same once a day even when the
  app is closed, and exits in under a second.
- Settings shows "Supabase last kept awake: …".
- If the project is paused anyway, the app says so plainly (instead of "no
  internet") and points to the dashboard's Restore button.

## 3. Much lighter polling

| What | 3.x | 4.0 |
|---|---|---|
| "I'm online" heartbeat | 15 s | **60 s** |
| Counted as offline after | 45 s | **3 min** |
| Render PC checks for new jobs | ~2 s | **30 s** |
| Sender refreshes the PC list | ~3 s | **30 s**, only while that tab is open |
| Job history | whole table every ~2 s | **last 50**, every **60 s**, only while open |
| During an active job | same as idle | **5–10 s** |
| Logging | every request | **problems only** |

Queries ask only for what they need (unfinished jobs for this PC, recent
history), never the whole table.

## 4. Database: start over with one file

The seven migration files are replaced by:

- `supabase/reset.sql` — run **once** to remove the version 3 tables,
  functions and policies.
- `supabase/filesender.sql` — the whole setup in one file.
- A single health-check query (as in `SUPABASE_CHECKLIST.txt`).

Same Supabase project, so the URL and key in the app don't change. Storage
buckets are kept only for the small-project fallback.

## 5. Kept from 3.x

Render pipeline and Media Encoder agent, family codes (each code is its own
Supabase account), the shared server clock, job list with Cancel/Clear,
retention, reconnect after network loss or expired login, the log panel and
the file-integrity checks.

## 6. Removed

Chunked cloud uploads as the main path, cloud clean-up of full projects, the
1 GB warning (replaced by the fallback limit message).

## 7. Process

- New branch `feature/v4-direct`; version **4.0.0**. The working 3.2 stays
  untouched as a fallback.
- The Premiere plugin waits until 4.0 works.
- Every update ships with `scripts/update_manifest.txt`; run
  `python scripts\verify_update.py` after copying files, and upload files to
  GitHub as files (never paste their contents).
