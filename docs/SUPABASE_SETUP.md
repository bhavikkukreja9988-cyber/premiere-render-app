# Supabase setup

This app uses Supabase as the cloud layer that lets a Sender and a Render
Station talk to each other over the internet — different homes, different
networks, no port forwarding. This guide connects the app to the Supabase
project and applies the database, security and storage setup.

You do this once, in the Supabase dashboard. It takes about ten minutes.

> **Secrets:** only the *publishable* key goes in the app (it already is, in
> `src/remote/config.py`). Never put the **secret key**, **service-role key**,
> or **database password** in the app, the repo, or these docs.

## 1. The project

Already created:

- **Project:** File Sender
- **URL:** `https://dyvhlaljbgpyywrofrbg.supabase.co`
- **Publishable key:** `sb_publishable_...` (already in `src/remote/config.py`)

To point a build at a *different* Supabase project, set environment variables
before launching — no code change needed:

```
SUPABASE_URL=https://YOURPROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_yourkey
```

## 2. Turn off email confirmation (important)

The app signs users in with a **username and password**. Internally each
username becomes a synthetic address like `bhavik@filesender.local`, which can
never receive email. So email confirmation must be off, or logins will hang
waiting for a confirmation click.

Dashboard → **Authentication → Providers → Email**:

- Ensure **Email** is enabled.
- **Turn OFF “Confirm email.”**
- Leave phone/OAuth providers off (not used).

## 3. Apply the database migrations

Dashboard → **SQL Editor**, then run each file in
`supabase/migrations/` **in order**:

1. `001_initial_schema.sql` — tables: stations, jobs, job_files, job_events
2. `002_rls_policies.sql` — Row Level Security (each account sees only its own)
3. `003_realtime.sql` — live updates for presence, jobs and events
4. `004_storage.sql` — the two private buckets and their access rules

Paste the contents of each file, run it, confirm “Success,” move to the next.

*(Alternatively, with the Supabase CLI: `supabase db push` after linking the
project. The dashboard method needs no CLI install.)*

## 4. Confirm the buckets

Dashboard → **Storage**. You should see two **private** buckets:

- `project-files`
- `render-results`

If they aren’t there, re-run `004_storage.sql`. Do **not** make them public.

## 5. Confirm Realtime

Dashboard → **Database → Replication** (or **Realtime**). The `stations`,
`jobs` and `job_events` tables should be in the `supabase_realtime`
publication. `003_realtime.sql` adds them; this is just a visual check.

## 6. How the app uses it

- **Sign in:** username + password. The session is remembered locally so the
  app signs in silently next time.
- **A family shares one account.** Everyone who should share render stations
  signs into the same username/password. Different accounts are fully isolated
  by RLS — one family can never see another’s stations, jobs or files.
- **Presence:** while FileSender is open in Render Station mode it sends a
  heartbeat; the station shows online. Close the app and it goes offline. There
  is no background server left running.
- **Transfer:** project files upload to `project-files`, the result MP4 to
  `render-results`, both under `user/<id>/jobs/<job id>/…`. Cloud files are
  temporary transport and are removed once the job is delivered.

## 7. What must stay private

Never share or commit:

- the Supabase **secret** / **service-role** key
- the **database password**
- anything from **Project Settings → API** labelled secret

The app only ever needs the URL and the publishable key.

## 8. Not yet verified

The cloud code has not been run against the live project from the development
environment (no network there). The first real test happens on Windows with the
installed app. See `CHANGE_REPORT.txt` → “requires real testing.”
