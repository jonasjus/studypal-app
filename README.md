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
| Notifications | `study notify` on a schedule | While the app is open, also in the background, with a pling when a Pomodoro phase ends |
| Sync between computers | git (`study sync`) | Optional account, synced through Supabase |
| CLI | yes | no |
| Past exams, practice exams with Gemini, Groq or Ollama | no | yes |
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

Each subject has an **Exams** page (button on the subject page), listing its past and practice exams.
Click an exam to open its own page, with its files, its questions and the times you've taken it.

- **Past exams.** Add the exam paper (PDF or photos). If you have them, also add the solutions and
  your own answers, graded if possible. Click a file to open it in Preview.
- **Read questions.** StudyPal turns the exam into structured questions (`core/ingest.py`):
  1. *Parse.* Each file becomes Markdown, page by page. A page with a text layer is taken as it is
     (pypdfium2), and the next step writes its garbled formulas back as LaTeX; a scanned page goes to
     the model as an image to be transcribed, a few pages per request.
  2. *Extract.* The exam's Markdown goes to the model a few pages at a time, which lists the questions
     (number as printed, parent number, text, topic tags, type, points, whether it needs a figure); then
     the solutions' Markdown, for their answers. Pydantic checks both (`core/logic/questions.py`); entries that don't fit
     are left out and counted.
  3. *Match.* Answers are matched to questions by number (`3 b)` is `3b`, `Oppgave 2` is `2`). A question
     the solutions don't answer has no answer: the page says "No solution", and nothing is guessed.
     Solutions whose number matches no question are named in the message.
  4. *Mark.* Given your own answers, the model marks how each question went and notes what went wrong.
- **Marking.** Each question can be marked **Got it**, **Partly** or **Missed**, with a note on what
  went wrong. You can mark them yourself, also without a model, and add questions by hand.
  **What to practise** totals these by topic. A question that went badly can become a weak spot.
- **Practice exams.** `generate_exam(weak_topics, n)` (`core/generate.py`) writes n new questions in the
  same schema, each with a worked solution. For every weak topic it shows the model 3 to 5 past questions
  on it as examples (answered ones first, then ones that went badly), plus a few others for the style.
  The weak topics are what went badly (missed and partly right questions, low-confidence topics), or
  the whole course, or topics you pick. It's told about earlier practice questions so it doesn't repeat
  them. Each question says what it practises. Solutions are folded away until you open them. You mark
  practice questions the same way, so they feed into the next practice exam. **Print…** saves the
  exam as a web page, with the solutions on a separate page, and opens it in the browser.
- **Taking an exam.** **Take exam** starts an attempt, timed (the limit suggested is about 12 minutes a
  question) or not. The clock runs from the start, also while the page is closed, and the exam is handed
  in by itself when time is up. Answers are saved as you type. On handing in, the model grades each answer
  against the solution (`core/grade.py`, `core/logic/attempts.py`): points out of what the question is
  worth (its marks if every question has them, else 1 each), a verdict and feedback, plus a summary.
  Without a model, or to overrule it, you mark each answer **Right**, **Partly** or **Wrong**. The
  verdicts become how the exam's questions went (the latest attempt counts), so they feed into **What to
  practise** and the next practice exam. Each attempt keeps a copy of the questions as they were, so
  reading the exam again later doesn't change it, and attempts sync like everything else.

The model is chosen in Settings (the gear icon), and every provider is reached through the same
OpenAI-compatible chat API (`core/llm.py`):

| Provider | Models | Key |
|---|---|---|
| **Gemini** (default) | `gemini-3.8-flash` | `GEMINI_API_KEY`, or pasted in Settings; free from [Google AI Studio](https://aistudio.google.com/apikey) |
| Groq | `openai/gpt-oss-120b`, and `qwen/qwen3.8-27b` (preview) for scanned pages | `GROQ_API_KEY`, or Settings; free from the [Groq console](https://console.groq.com/keys) |
| Ollama | Any local model that reads images (`gemma3` by default) | None: it runs on this computer |

Free plans let a model take and write little per minute (Groq's free plan: 8,000 tokens a minute for
`gpt-oss-120b`, and 1,000 written tokens a minute for its image model). So the exam is read a few pages per
request (questions first, then solutions); a request whose answer is cut off is split in half and asked
again; a request over the per-minute limit asks for a shorter answer; practice-exam prompts carry fewer
example questions (1 to 5 per topic, shortened if needed); and a long practice exam is written in two
halves. Groq also stops answers at 1,024 tokens unless asked for more, so StudyPal asks for 8,192 and treats
an answer that used them all as cut off. While it waits for a per-minute limit, the progress line says so.

An environment variable wins over a key in Settings. Keys in Settings are kept in `prefs.json` on that
computer only (readable only by the user) and aren't synced; none are in this repository. Answers come
back as strict structured JSON. Rate limits (429) and busy servers are retried with exponential backoff
(2, 4, 8, 16 s, or as long as the server asks, up to a minute); a daily limit says so instead. The exam's
text and scanned pages are sent to the provider (not with Ollama); up to 40 pages per file. Photos are
shrunk to JPEG first, and iPhone photos (HEIC) are converted on a Mac (elsewhere, save them as JPG).

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

An app only runs on the kind of processor it was built for, so there are two Mac builds. GitHub makes both:
every push to `main` runs `.github/workflows/mac.yml` on macOS 15 (Sequoia) machines, one Intel and one Apple
Silicon. Each runs the tests, builds the app, opens it on Sequoia to check it works, and attaches
`StudyPal-mac-intel` or `StudyPal-mac-apple-silicon` to the run (kept for 30 days). To build without pushing,
go to Actions → Mac build → **Run workflow**. To find out which one a Mac needs:  → About This Mac shows a
**Chip** (Apple M1 or newer: Apple Silicon) or a **Processor** (Intel).

To build on this Mac instead (for this Mac's kind of processor):

```sh
sh packaging/build-mac.sh        # makes dist/StudyPal-mac.zip
```

The build records the oldest macOS the app runs on (macOS 15 for these builds), so an older Mac says so
plainly, and signs the app again at the end (ad hoc), since changing its Info.plist breaks PyInstaller's
signature and macOS calls an app with a broken signature "damaged".

Send them the zip. They unzip it and drag **StudyPal** into Applications.

The app isn't signed with an Apple developer certificate, so the first time it's opened macOS
says it can't check it for malware. On Sequoia, right-click → Open no longer gets past this. To open it anyway:

1. Double-click StudyPal and close the warning.
2. Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to
   the StudyPal message.
3. Confirm with **Open** (and your password). After this it opens normally.

Or in Terminal: `xattr -dr com.apple.quarantine /Applications/StudyPal.app`.

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
- `src/studypal/core/llm.py`: the model provider interface and its OpenAI-compatible client (Gemini,
  Groq, Ollama), with retries. `core/pages.py` takes PDF text and draws pages and photos as images
  ([pypdfium2](https://github.com/pypdfium2-team/pypdfium2) and Pillow). `core/ingest.py` reads an exam
  into questions; `core/logic/questions.py` has their Pydantic schema and the matching with solutions.
  `core/generate.py` writes new questions; its few-shot choice, prompt and the summary of what went
  badly are in `core/logic/exams.py`. The exam files folder is handled by `core/files.py`.
- `supabase/`: the cloud table, its security rules and auth settings.
- `src/studypal/api.py`: everything the window can ask for. Each public method takes and returns
  plain JSON, and problems come back as `{"error": "..."}` for the window to show.
- `src/studypal/web/`: the interface (plain HTML, CSS and JavaScript, no build step). `exams.js`
  is the Exams page, `research.js` the research projects (their card, page and note saving). `vendor/` holds [marked](https://marked.js.org/) 15.0.12 and
  [KaTeX](https://katex.org/) 0.16.22 (woff2 fonts only), for questions written in Markdown with
  maths, so they work offline.
- `src/studypal/core/sound.py`: the Pomodoro's pling, made as a WAV and played by the system (so it's heard
  with the window in the background), and keeping macOS from napping the app while a Pomodoro runs.
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
# smoke test: 4 subjects, 1 research, 13 list rows, accounts off, maths on, research on, pages on   (demo mode never has accounts)
```

The app icon is `packaging/icon.svg`. `icon.png` and `StudyPal.icns` are made from it.
