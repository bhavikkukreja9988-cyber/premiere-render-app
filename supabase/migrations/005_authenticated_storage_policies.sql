-- FileSender Remote V3 — authenticated Storage policies
-- Replaces the initial public-role storage policies with explicitly
-- authenticated-user policies while keeping both buckets private.
--
-- Run this after 004_storage.sql in the Supabase SQL Editor.
-- Safe to run more than once: the previous policies are dropped first.

-- project-files -------------------------------------------------------------
drop policy if exists project_files_rw on storage.objects;
create policy project_files_rw
on storage.objects
for all
to authenticated
using (
    bucket_id = 'project-files'
    and (storage.foldername(name))[1] = 'user'
    and (storage.foldername(name))[2] = (select auth.uid()::text)
)
with check (
    bucket_id = 'project-files'
    and (storage.foldername(name))[1] = 'user'
    and (storage.foldername(name))[2] = (select auth.uid()::text)
);

-- render-results ------------------------------------------------------------
drop policy if exists render_results_rw on storage.objects;
create policy render_results_rw
on storage.objects
for all
to authenticated
using (
    bucket_id = 'render-results'
    and (storage.foldername(name))[1] = 'user'
    and (storage.foldername(name))[2] = (select auth.uid()::text)
)
with check (
    bucket_id = 'render-results'
    and (storage.foldername(name))[1] = 'user'
    and (storage.foldername(name))[2] = (select auth.uid()::text)
);
