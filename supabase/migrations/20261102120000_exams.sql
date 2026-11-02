-- Exams: three more kinds of rows, and a private bucket for the files people add to exams
-- (PDFs and photos of past exams, solutions and their own answers).

alter table public.study_rows drop constraint study_rows_tbl_check;
alter table public.study_rows add constraint study_rows_tbl_check
  check (tbl in ('course', 'topic', 'source', 'chapter', 'section', 'weak_spot', 'deadline', 'session', 'sent',
                 'exam', 'exam_file', 'exam_question'));

insert into storage.buckets (id, name, public, file_size_limit)
values ('exam-files', 'exam-files', false, 52428800)
on conflict (id) do nothing;

-- Each account's files live in a folder named after its user id, and only that account can touch them.
create policy "Read own exam files" on storage.objects
  for select to authenticated
  using (bucket_id = 'exam-files' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "Add own exam files" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'exam-files' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "Change own exam files" on storage.objects
  for update to authenticated
  using (bucket_id = 'exam-files' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'exam-files' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "Delete own exam files" on storage.objects
  for delete to authenticated
  using (bucket_id = 'exam-files' and (storage.foldername(name))[1] = (select auth.uid())::text);
