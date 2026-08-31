-- 002_rls_policies.sql
-- Row Level Security: every user sees only their own stations, jobs, files and
-- events. A family shares one account, so members see each other's stations and
-- jobs; different families (different accounts) are fully isolated.
-- Apply after 001_initial_schema.sql.

alter table public.stations   enable row level security;
alter table public.jobs       enable row level security;
alter table public.job_files  enable row level security;
alter table public.job_events enable row level security;

-- --- stations -------------------------------------------------------------
drop policy if exists stations_owner_all on public.stations;
create policy stations_owner_all on public.stations
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- --- jobs -----------------------------------------------------------------
drop policy if exists jobs_owner_all on public.jobs;
create policy jobs_owner_all on public.jobs
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- --- job_files: access follows the parent job's ownership -----------------
drop policy if exists job_files_owner_all on public.job_files;
create policy job_files_owner_all on public.job_files
    for all
    using (exists (
        select 1 from public.jobs j
        where j.id = job_files.job_id and j.user_id = auth.uid()))
    with check (exists (
        select 1 from public.jobs j
        where j.id = job_files.job_id and j.user_id = auth.uid()));

-- --- job_events: same rule ------------------------------------------------
drop policy if exists job_events_owner_all on public.job_events;
create policy job_events_owner_all on public.job_events
    for all
    using (exists (
        select 1 from public.jobs j
        where j.id = job_events.job_id and j.user_id = auth.uid()))
    with check (exists (
        select 1 from public.jobs j
        where j.id = job_events.job_id and j.user_id = auth.uid()));
