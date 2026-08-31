-- 004_storage.sql
-- Private Storage buckets for project files and render results, with access
-- scoped to the owning user by object path. Object keys look like:
--   user/{user_id}/jobs/{job_id}/project/...
--   user/{user_id}/jobs/{job_id}/output/...
-- so the first two path segments encode ownership.
-- Apply after 003_realtime.sql.

-- Create the buckets (private: public = false).
insert into storage.buckets (id, name, public)
values ('project-files', 'project-files', false)
on conflict (id) do nothing;

insert into storage.buckets (id, name, public)
values ('render-results', 'render-results', false)
on conflict (id) do nothing;

-- Helper: the object path must start with 'user/<caller uid>/'.
-- storage.foldername(name) returns the path segments as an array.

-- project-files policies -----------------------------------------------------
drop policy if exists project_files_rw on storage.objects;
create policy project_files_rw on storage.objects
    for all
    using (
        bucket_id = 'project-files'
        and (storage.foldername(name))[1] = 'user'
        and (storage.foldername(name))[2] = auth.uid()::text)
    with check (
        bucket_id = 'project-files'
        and (storage.foldername(name))[1] = 'user'
        and (storage.foldername(name))[2] = auth.uid()::text);

-- render-results policies ----------------------------------------------------
drop policy if exists render_results_rw on storage.objects;
create policy render_results_rw on storage.objects
    for all
    using (
        bucket_id = 'render-results'
        and (storage.foldername(name))[1] = 'user'
        and (storage.foldername(name))[2] = auth.uid()::text)
    with check (
        bucket_id = 'render-results'
        and (storage.foldername(name))[1] = 'user'
        and (storage.foldername(name))[2] = auth.uid()::text);
