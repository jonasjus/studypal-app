-- StudyPal's cloud copy of each account's data.
--
-- The app keeps working on a local SQLite database and syncs it here row by row, the same way
-- `study` syncs through git: each local row becomes one row here, keyed by its stable uid, with
-- its fields as JSON. Merging happens in the app, so the database only has to store rows and
-- keep every account's rows private.

create table public.study_rows (
  user_id    uuid not null default auth.uid() references auth.users on delete cascade,
  tbl        text not null check (tbl in ('course', 'topic', 'source', 'chapter', 'section',
                                          'weak_spot', 'deadline', 'session', 'sent')),
  uid        text not null check (length(uid) between 1 and 200),
  data       jsonb not null,
  synced_at  timestamptz not null default now(),
  primary key (user_id, tbl, uid)
);

alter table public.study_rows enable row level security;

create policy "Read own rows" on public.study_rows
  for select to authenticated using (user_id = (select auth.uid()));
create policy "Add own rows" on public.study_rows
  for insert to authenticated with check (user_id = (select auth.uid()));
create policy "Change own rows" on public.study_rows
  for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy "Delete own rows" on public.study_rows
  for delete to authenticated using (user_id = (select auth.uid()));

create or replace function public.touch_synced_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.synced_at := now();
  return new;
end;
$$;

create trigger study_rows_touch before update on public.study_rows
  for each row execute function public.touch_synced_at();

-- Lets someone delete their own account (and with it, all their rows) from the app.
create or replace function public.delete_my_account() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then
    raise exception 'Not signed in';
  end if;
  delete from auth.users where id = auth.uid();
end;
$$;

revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;
