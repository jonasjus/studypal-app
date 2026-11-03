-- Research projects (StudyPal 2026-11): seven more kinds of row in study_rows.
-- Older app versions ignore rows of kinds they don't know, so they keep syncing.

alter table public.study_rows drop constraint study_rows_tbl_check;
alter table public.study_rows add constraint study_rows_tbl_check
  check (tbl in ('course', 'topic', 'source', 'chapter', 'section', 'weak_spot', 'deadline', 'session', 'sent',
                 'exam', 'exam_file', 'exam_question',
                 'project', 'project_note', 'project_entry', 'project_link', 'project_source', 'project_task',
                 'project_session'));
