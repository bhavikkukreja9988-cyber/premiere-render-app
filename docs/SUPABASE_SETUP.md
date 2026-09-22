# Supabase setup

One-time setup of the cloud project that FileSender uses to connect PCs.

> Never put the **secret key**, **service-role key**, or **database password**
> in the app, the repo, or these docs. The app only ever uses the public URL
> and the **publishable** key, which are safe to ship.

## 1. Project details

- URL: `https://dyvhlaljbgpyywrofrbg.supabase.co`
- Publishable key: already built into the app (`src/remote/config.py`).

## 2. Turn off email confirmation (important)

**Authentication → Providers → Email → turn OFF "Confirm email."**

There is no login screen in FileSender. Each **family code** silently maps to
its own internal account with a synthetic address (e.g.
`family-3f9a…@filesender.local`) that can never receive email. If
confirmation is left on, the account is created but can never be used, and the
app will report that it can't connect — permanently, for that family
code.

## 3. Run the migrations, in order

Open **SQL Editor**, paste each file's contents, run it, confirm "Success,"
then move to the next. **All six are required.**

1. `001_initial_schema.sql` — tables: stations, jobs, job_files, job_events
2. `002_rls_policies.sql` — Row Level Security
3. `003_realtime.sql` — live updates for presence, jobs and events
4. `004_storage.sql` — the two private buckets
5. `005_authenticated_storage_policies.sql` — storage access for signed-in
   accounts only, each account limited to its own folder
6. `006_family_scoped_accounts.sql` — adds device names, family codes and
   live progress columns, and restores per-account isolation

**Do not skip 005 or 006.** Without 006, the app tries to write columns that
don't exist: PCs fail to register, and every station appears offline.

Every migration is safe to run more than once.

## 4. Check the buckets

**Storage** should show two **private** buckets: `project-files` and
`render-results`. If they're missing, re-run `004_storage.sql`. Do **not**
make them public.

## 5. Check realtime

**Database → Replication:** `stations`, `jobs` and `job_events` should be in
the `supabase_realtime` publication. `003_realtime.sql` adds them.

## How accounts work

- There is no username or password. Each PC is set up once with a **name**
  and a **family code**.
- Every PC that types the **same** family code silently signs into the
  **same** account, so they can see and send to each other.
- A **different** family code is a completely separate account. Row Level
  Security enforces this in the database itself — it is not just hidden in
  the app.
- Treat the family code like a shared password: anyone who knows it can see
  your PCs and send them jobs.
