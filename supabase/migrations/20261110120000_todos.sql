-- Daily to-do lists (StudyPal 2026-11): one more kind of row in study_rows, a to-do that belongs to a day.
-- Older app versions ignore rows of kinds they don't know, so they keep syncing.

alter table public.study_rows drop constraint study_rows_tbl_check;
alter table public.study_rows add constraint study_rows_tbl_check
  check (tbl in ('course', 'topic', 'source', 'chapter', 'section', 'weak_spot', 'deadline', 'session', 'sent',
                 'exam', 'exam_file', 'exam_question', 'exam_attempt', 'course_note',
                 'project', 'project_note', 'project_entry', 'project_link', 'project_source', 'project_task',
                 'project_session', 'todo'));
