-- 007_server_clock.sql
-- One clock for everyone: Supabase's.
--
-- WHY: a station's "last seen" time used to be written with the render PC's
-- own clock, and the sender compared it against the SENDER's clock. If the
-- two PCs' clocks disagreed by more than 45 seconds, the station looked
-- permanently offline even while it was heartbeating every 15 seconds.
--
-- This migration:
--   1. stamps stations.last_seen with the database's own time whenever a
--      heartbeat writes it, whatever time the PC sent;
--   2. adds server_time(), so each PC can compare against that same clock.
--
-- Apply after 006_family_scoped_accounts.sql. Safe to run more than once.
-- The app still works if this migration is missing (it falls back to each
-- PC's own clock, as before) - it just can't correct clock differences.

create or replace function public.server_time()
returns double precision
language sql
stable
as $$
    select extract(epoch from now())::double precision
$$;

grant execute on function public.server_time() to authenticated;

create or replace function public.stations_stamp_last_seen()
returns trigger
language plpgsql
as $$
begin
    -- Only when last_seen is actually being written. Marking a station
    -- offline (which doesn't touch last_seen) must not refresh it.
    if tg_op = 'INSERT' then
        new.last_seen := extract(epoch from now())::double precision;
    elsif new.last_seen is distinct from old.last_seen then
        new.last_seen := extract(epoch from now())::double precision;
    end if;
    return new;
end
$$;

drop trigger if exists stations_stamp_last_seen on public.stations;

create trigger stations_stamp_last_seen
    before insert or update on public.stations
    for each row
    execute function public.stations_stamp_last_seen();
