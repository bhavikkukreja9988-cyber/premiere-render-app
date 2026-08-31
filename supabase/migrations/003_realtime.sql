-- 003_realtime.sql
-- Enable Supabase Realtime so the Sender and Render Station get live updates
-- (station presence, new jobs, job status changes) without any direct
-- socket between them. RLS still governs what each subscriber can see.
-- Apply after 002_rls_policies.sql.

-- Add the tables to the realtime publication. (In a fresh Supabase project the
-- publication 'supabase_realtime' already exists.)
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public'
      and tablename = 'stations') then
    alter publication supabase_realtime add table public.stations;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public'
      and tablename = 'jobs') then
    alter publication supabase_realtime add table public.jobs;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public'
      and tablename = 'job_events') then
    alter publication supabase_realtime add table public.job_events;
  end if;
end $$;

-- Ensure UPDATE/DELETE realtime payloads include the full old row so clients
-- can match filters on removed rows.
alter table public.stations   replica identity full;
alter table public.jobs       replica identity full;
alter table public.job_events replica identity full;
