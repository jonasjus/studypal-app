# StudyPal

The `study` terminal tracker as a regular desktop app: a window you click around in, with no
terminal and no keyboard shortcuts to learn. It's meant for people who'd never open a terminal.

It keeps the same ideas as `study`: subjects with a cram timeline (how much material is done
against how much time has passed), topics, weak spots, deadlines, study time with a timer or
Pomodoro, and reading lists. The data layer (`src/studypal/core/`) is a copy of `study`'s storage
and logic, so the two behave the same. They don't share a database.

| | `study` (terminal) | StudyPal (this app) |
|---|---|---|
| Data | `~/.local/share/study/study.db` | macOS: `~/Library/Application Support/StudyPal/studypal.db`<br>Windows: `%APPDATA%\StudyPal\studypal.db` |
| Settings | `config.toml` | Settings dialog (gear icon), stored in the database |
| Notifications | `study notify` on a schedule | While the window is open |
| Sync between computers | git (`study sync`) | Optional account, synced through Supabase |
| CLI | yes | no |
| Past exams, practice exams with Gemini | no | yes |
| Research projects | no | yes |

## Accounts and the cloud

Anyone can use StudyPal on their own computer without an account. Creating one (from the welcome
screen, or **Sign in** in the top bar) saves their data in Supabase, so it survives a lost laptop
and can be used from more than one computer.

- **It still works offline.** The app always works on a local copy and syncs it: when it starts,
  a few seconds after each change, and every minute (to pick up changes from other computers). The
  top bar shows "Saved online · 14:05", or "Offline · saved on this computer" until the network is back.
- **Merging** is the same row-by-row merge `study` uses for git sync (`core/logic/merge.py`):
  changes to different things on two computers both survive, and if the same thing changed on
  both, the newer change wins.
- **Data made before signing up** can be moved into the new account (a checkbox in the sign-up form,
  on by default). Signing in to an existing account on a computer that already has subjects offers
  the same.
- **Signing out** syncs one last time, then removes that computer's copy of the account's data (it's
  in the cloud). If the last sync can't happen, it asks first.
- **Several accounts** can be signed in on one computer at once. The account button in the top bar
  shows who's in use; its menu lists everyone signed in and "This computer only", and clicking one
  switches straight to it, with no signing out and in. Each account keeps its own copy on the computer
  (`accounts/<user id>/`); switching saves the one you leave first, and if that can't happen (offline)
  its changes stay and sync the next time you use it. "Add another account…" signs in or creates
  one more. The accounts are remembered in `accounts.json` (an `account.json` from before is converted).
- **The account menu** also has Sync now, Change password, Sign out and Delete this account, all for
  the account in use. Signing out or deleting moves on to the next signed-in account, if there is one.

Each account's rows are private. Row-level security lets a signed-in user read and write only their
own rows, so the public anon key in the app can't be used to see anyone else's data.

### Setting up the Supabase project

This is done: the app uses the `studypal` project (ref `jyicurszzboxaggvktqc`, Stockholm), and
`src/studypal/cloud.json` points at it. The steps, for setting it up again somewhere else:

1. Create a project (the CLI is fine): `supabase projects create studypal --org-id <org> --region eu-north-1`
2. Link this folder and set it up:
   ```sh
   supabase link --project-ref <project-ref>
   supabase db push        # the study_rows table (with every kind of row), the exam-files bucket, their security rules, delete_my_account()
   supabase config push    # auth: 8-character passwords, no email confirmation (see supabase/config.toml)
   ```
3. Put the project URL and the publishable key (`supabase projects api-keys --project-ref <ref>`,
   the `sb_publishable_...` one) into `src/studypal/cloud.json`, then rebuild the app. That key is
   meant to be public. Never put the secret or service_role key there.

Without a URL in `cloud.json` (or `STUDYPAL_SUPABASE_URL` / `STUDYPAL_SUPABASE_ANON_KEY` in the
environment), the app has no accounts and works on the computer only.

**Password resets and email confirmation** need email. Supabase's built-in email only delivers to
the project's own team members, so both are off. Until you add your own SMTP server
(Authentication → SMTP), reset a forgotten password from the dashboard: Authentication → Users.

### What's stored

One table, `study_rows`: for each row in someone's local database, the account it belongs to, which
table it's from, its stable id and its fields as JSON. Settings (Pomodoro lengths and so on), the
running timer and the Pomodoro stay on each computer.

Exam files (PDFs and photos) go in a private Storage bucket, `exam-files`, in a folder per account
(`<user id>/<sha256>.pdf`). The security rules let each account reach only its own folder. A file
is stored under the hash of its contents, so it has the same name on every computer. Files go up
after the exam's rows, and a computer downloads the ones its exams need but it doesn't have yet.
Files no exam uses any more are removed, but only once they've been in the bucket for 15 minutes,
because another computer may be just about to add the exam that uses one. Deleting an account
deletes its files first, since the database can't remove them itself.

## Exams

Each subject has an **Exams** page (button on the subject page).

- **Past exams.** Add the exam paper (PDF or photos). If you have them, also add the solutions and
  your own answers, graded if possible. Click a file to open it in Preview.
- **Read questions.** Gemini lists the exam's questions, transcribed with their maths and linked to
  the subject's topics. It adds the answers from the solutions, or writes a short one itself when
  there are no solutions (the page says which). Given your own answers, it also marks how each
  question went and notes what went wrong.
- **Marking.** Each question can be marked **Got it**, **Partly** or **Missed**, with a note on what
  went wrong. You can mark them yourself, also without Gemini, and add questions by hand.
  **What to practise** totals these by topic. A question that went badly can become a weak spot.
- **Practice exams.** Gemini writes a new exam (short, half or full length) in the style of the past
  papers and solutions. It aims at what went badly: the missed and partly right questions with their
  notes, open weak spots, and topics with low confidence. You can also cover the course like the real
  exam does, or pick topics. It's told about earlier practice questions so it doesn't repeat them.
  Each question says what it practises. Solutions are folded away until you open them. You mark
  practice questions the same way, so they feed into the next practice exam. **Print…** saves the
  exam as a web page, with the solutions on a separate page, and opens it in the browser.

Gemini needs an API key: free from [Google AI Studio](https://aistudio.google.com/apikey), pasted under
Settings (the gear icon). Like the theme, it's kept in `prefs.json` on that computer only (readable
only by the user) and isn't synced. `GEMINI_API_KEY` in the environment works too. The default
model is `gemini-3.8-flash`; Settings can switch to `gemini-4-argon` for hard maths. If a model is
retired, StudyPal falls back to `gemini-flash-latest`. Exam files are sent to Google whenever
Gemini reads or writes an exam. Each request carries up to 45 MB of files (Gemini takes 50 MB), newest
exams first.

## Research

Research projects (a thesis, a paper, a side project) sit in the overview's list with the subjects,
drawn as dashed cards with a **Research** label and a bar of their tasks. Drag any card by the handle
on its left edge to change the order (or focus the handle and press Alt+↑/↓). Until you do, subjects
come first, soonest exam first, as before. A project's status is idea, active, paused or done; done
projects move to **Finished** with finished subjects.

A project's page has its dates, tags, a Markdown description and one-click shortcuts, then tabs:

- **Notes**: as many as you like, in Markdown with maths. They save as you type (and before anything
  redraws the page), show when they were created and last edited, and can be searched.
- **Journal**: dated entries for experiments, results and decisions, newest first.
- **Tasks**: next steps to tick off, in an order you drag.
- **References**: title, authors, year, link or DOI, to read / reading / read, and an annotation.
  Filter by status, drag to reorder, copy one or all as APA.
- **Shortcuts**: links to Overleaf, Zotero, Scholar, arXiv, a repo, a notebook, a dataset. The
  icon is guessed from the address (or picked). They open in the computer's browser, or in Zotero or
  Obsidian for `zotero://` and `obsidian://` links. Nothing else opens, so a shortcut can't start a program.
- **Time**: **Start working** runs the same timer or Pomodoro as for a subject. Project time is
  kept apart from subject time, and the week chart stacks it on top in its own colour.

Project time has its own table (`project_session`) rather than sessions without a subject, so an
older version of the app syncing the same account never meets a session it can't store. Older versions
skip research rows when they sync. One thing they can't keep is the order you've dragged the list into:
when an older version next syncs, the order goes back to soonest exam first. So update every computer
that shares an account.

## Themes

Settings (the gear icon) has a theme picker: **System** (follows the computer's light or dark mode),
**Daylight**, Light, Dark, and the terminal app's themes (Gruvbox, Nord, Dracula, Catppuccin, Tokyo
Night, Solarized, Rosé Pine, One Dark, Monokai). Clicking one previews it; Cancel goes back. The theme
belongs to the computer (`prefs.json`), not to an account. Subjects on a default colour take the
theme's matching shade.

**Daylight** changes with the time of day, updating every minute: a rosy dawn, a fresh morning, bright
and cool at noon, warm in the afternoon, amber at golden hour, then dark from 20:30 (purple dusk,
deep-blue night, darkest in the small hours) until 06:30. It blends smoothly within the light hours and
within the dark ones, but switches between them in one step, since halfway between light and dark is a
grey nothing reads well on. Its colours are checked to stay readable at every point of the day.

## Giving it to someone

### Mac

```sh
sh packaging/build-mac.sh        # makes dist/StudyPal-mac.zip
```

Send them `dist/StudyPal-mac.zip`. They unzip it and drag **StudyPal** into Applications.

The app isn't signed with an Apple developer certificate, so the first time it's opened macOS
says it can't check it for malware. To open it anyway:

1. Double-click StudyPal and close the warning.
2. Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to
   the StudyPal message.
3. Confirm with **Open**. After this it opens normally.

The build runs on the same kind of Mac it was built on. Built on Apple Silicon (M1 or newer),
it won't run on an older Intel Mac. To support one, build on an Intel Mac.

### Windows

Windows apps have to be built on Windows. GitHub does it: every push to `main` runs
`.github/workflows/windows.yml` on a Windows machine. It runs the tests, builds the app, checks
that it opens, and attaches `StudyPal-windows` to the run. To build without pushing, go to Actions →
Windows build → **Run workflow**. Download the zip from the run's page (it's kept for 30 days).

To build it yourself on a Windows PC with Python 3.11+:

```bat
py -3.11 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
packaging\build-windows.bat
```

Send them `dist\StudyPal-windows.zip`. They unzip it anywhere and double-click `StudyPal.exe`.
If SmartScreen warns about an unknown app, they click **More info → Run anyway**. The window uses
Edge WebView2, which comes with Windows 10 and 11.

## How it's built

- `src/studypal/core/`: storage and study logic copied from `study` (models, SQLite storage,
  cram timeline, countdowns, Pomodoro, reading lists, notifications, and the sync merge). Changed only
  where the app needs it: where the data lives (`paths.py`), the notification name, opening SQLite so
  the window's worker threads can use it, and new rows' ids starting with their creation time (so
  rows synced to another computer keep their order).
- `src/studypal/core/cloud.py`: accounts (Supabase Auth) and syncing with the `study_rows` table and
  the exam-files bucket, using only the standard library for HTTP. `core/dataset.py` turns the
  database into rows and back.
- `src/studypal/core/gemini.py`: the Gemini API (`generateContent` with JSON output). The prompts
  and the summary of what went badly are in `core/logic/exams.py`, and the exam files folder is
  handled by `core/files.py`.
- `supabase/`: the cloud table, its security rules and auth settings.
- `src/studypal/api.py`: everything the window can ask for. Each public method takes and returns
  plain JSON, and problems come back as `{"error": "..."}` for the window to show.
- `src/studypal/web/`: the interface (plain HTML, CSS and JavaScript, no build step). `exams.js`
  is the Exams page, `research.js` the research projects (their card, page and note saving). `vendor/` holds [marked](https://marked.js.org/) 15.0.12 and
  [KaTeX](https://katex.org/) 0.16.22 (woff2 fonts only), for questions written in Markdown with
  maths, so they work offline.
- `src/studypal/app.py`: opens the window with [pywebview](https://pywebview.flowrl.com/), which
  uses the system's own web view (WebKit on macOS, Edge WebView2 on Windows).

## Development

```sh
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"
.venv/bin/pytest

.venv/bin/studypal --demo              # the app with sample data (thrown away on quit; no accounts)
.venv/bin/studypal --demo --debug      # with the web inspector (right-click → Inspect)
.venv/bin/python -m studypal.devserver --demo   # the interface in a browser at http://localhost:8765
```

In the browser version, `#subject/3`, `#reading/3` or `#research/1` at the end of the address opens that page
directly.

To check a fresh build works end to end (page loads, reaches Python, draws the overview):

```sh
STUDYPAL_NOTIFIER=print dist/StudyPal.app/Contents/MacOS/StudyPal --demo --smoke-test
# smoke test: 4 subjects, 1 research, 13 list rows, accounts off, maths on, research on   (demo mode never has accounts)
```

The app icon is `packaging/icon.svg`. `icon.png` and `StudyPal.icns` are made from it.
