-- 006_family_scoped_accounts.sql
-- Restores REAL database-enforced isolation between families.
--
-- A prior draft of this migration (never applied - numbered 005, now
-- deleted to avoid colliding with the already-applied
-- 005_authenticated_storage_policies.sql) added family_code/device_name/
-- progress columns but left stations/jobs/job_files/job_events wide open
-- (`using (true)`), relying only on the app choosing to filter by family
-- code. That is a client-side convenience filter, not a security boundary:
-- any client with the public key could read past it.
--
-- The fix is on the application side (src/remote/auth.py): each family code
-- now derives its OWN deterministic Supabase account, so auth.uid() is
-- genuinely different per family again. This migration restores ownership-
-- based RLS to match - the same shape as the original 002_rls_policies.sql,
-- now applied on top of the family_code/device_name/progress columns.
--
-- Apply after 005_authenticated_storage_policies.sql. Safe to run even if
-- the never-applied draft 005_family_code.sql was never run - every
-- statement here is `if not exists` / `create or replace`.

-- --- schema (unchanged from the draft; kept for display/history purposes -
--     no longer the security boundary, auth.uid() is) --------------------
alter table public.stations  add column if not exists family_code text not null default '';
alter table public.stations  add column if not exists device_name text not null default '';
alter table public.jobs      add column if not exists family_code text not null default '';
alter table public.jobs      add column if not exists progress real not null default 0;
alter table public.jobs      add column if not exists progress_label text not null default '';

create index if not exists stations_family_idx on public.stations (family_code);
create index if not exists jobs_family_idx     on public.jobs (family_code);

-- --- policies: real ownership checks, not `using (true)` -------------------
drop policy if exists stations_shared_all   on public.stations;
drop policy if exists jobs_shared_all       on public.jobs;
drop policy if exists job_files_shared_all  on public.job_files;
drop policy if exists job_events_shared_all on public.job_events;
-- Also drop the original per-user policy names in case this is applied to a
-- database that still has them from 002_rls_policies.sql.
drop policy if exists stations_owner_all   on public.stations;
drop policy if exists jobs_owner_all       on public.jobs;
drop policy if exists job_files_owner_all  on public.job_files;
drop policy if exists job_events_owner_all on public.job_events;

create policy stations_owner_all on public.stations
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy jobs_owner_all on public.jobs
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy job_files_owner_all on public.job_files
    for all
    using (exists (
        select 1 from public.jobs j
        where j.id = job_files.job_id and j.user_id = auth.uid()))
    with check (exists (
        select 1 from public.jobs j
        where j.id = job_files.job_id and j.user_id = auth.uid()));

create policy job_events_owner_all on public.job_events
    for all
    using (exists (
        select 1 from public.jobs j
        where j.id = job_events.job_id and j.user_id = auth.uid()))
    with check (exists (
        select 1 from public.jobs j
        where j.id = job_events.job_id and j.user_id = auth.uid()));
