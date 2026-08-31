-- 001_initial_schema.sql
-- Premiere Render App — Remote V3 database schema.
-- Apply in the Supabase SQL editor or via the Supabase CLI. See
-- docs/SUPABASE_SETUP.md. Run migrations in numeric order.

-- Stations: one row per Render Station PC. Identity is independent of IP.
create table if not exists public.stations (
    id            text primary key,                 -- e.g. RS-xxxxxxxx
    user_id       uuid not null references auth.users (id) on delete cascade,
    name          text not null default '',
    status        text not null default 'offline',  -- online | offline | busy
    last_seen     double precision not null default 0,
    app_version   text not null default '',
    capabilities  jsonb not null default '{}'::jsonb,
    local_ip      text not null default '',          -- informational only
    created_at    double precision not null default extract(epoch from now()),
    updated_at    double precision not null default extract(epoch from now())
);
create index if not exists stations_user_idx on public.stations (user_id);

-- Jobs: one render request. Repeated sends of the same project are separate
-- rows with separate ids; never de-duplicated by content.
create table if not exists public.jobs (
    id                     uuid primary key default gen_random_uuid(),
    user_id                uuid not null references auth.users (id) on delete cascade,
    station_id             text references public.stations (id) on delete set null,
    display_label          text not null default '',
    project_name           text not null default '',
    sequence               text not null default '',
    preset                 text not null default '',
    output_name            text not null default '',
    status                 text not null default 'created',
    created_at             double precision not null default extract(epoch from now()),
    started_at             double precision not null default 0,
    completed_at           double precision not null default 0,
    output_filename        text not null default '',
    output_sha256          text not null default '',
    error                  text not null default '',
    delete_after_delivery  boolean not null default false,
    metadata               jsonb not null default '{}'::jsonb
);
create index if not exists jobs_user_idx    on public.jobs (user_id);
create index if not exists jobs_station_idx on public.jobs (station_id);
create index if not exists jobs_status_idx  on public.jobs (status);

-- Files that make up a job's project (the manifest, mirrored to the cloud).
create table if not exists public.job_files (
    id            uuid primary key default gen_random_uuid(),
    job_id        uuid not null references public.jobs (id) on delete cascade,
    path          text not null,
    size          bigint not null default 0,
    sha256        text not null default '',
    storage_path  text not null default '',
    created_at    double precision not null default extract(epoch from now())
);
create index if not exists job_files_job_idx on public.job_files (job_id);

-- Human-readable lifecycle events for a job (drives history + debugging).
create table if not exists public.job_events (
    id          uuid primary key default gen_random_uuid(),
    job_id      uuid not null references public.jobs (id) on delete cascade,
    event_type  text not null default '',
    message     text not null default '',
    created_at  double precision not null default extract(epoch from now())
);
create index if not exists job_events_job_idx on public.job_events (job_id);
