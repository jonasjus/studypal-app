"use strict";

// Research projects: their card in the overview's list, and their page with notes (saved while you type),
// a dated journal, tasks, references, shortcuts to tools and study time. Loaded after app.js; uses its
// helpers, and adds to its `actions`.

const PROJECT_TABS = [["notes", "Notes"], ["journal", "Journal"], ["tasks", "Tasks"], ["sources", "References"],
  ["tools", "Shortcuts"], ["time", "Time"]];
const PROJECT_STATUS_LABELS = { idea: "Idea", active: "Active", paused: "Paused", done: "Done" };
const READING_STATUS = [["to_read", "To read"], ["reading", "Reading"], ["read", "Read"]];
const LINK_KINDS = {
  writing: ["Writing", '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'],
  references: ["References", '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M8 7h8M8 11h6"/>'],
  search: ["Search", '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'],
  code: ["Code", '<path d="m8 8-5 4 5 4"/><path d="m16 8 5 4-5 4"/><path d="m14 4-4 16"/>'],
  notebook: ["Notebook", '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 3v18"/><path d="M12 8h5M12 12h5"/>'],
  data: ["Data", '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'],
  docs: ["Docs", '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M8 13h8M8 17h5"/>'],
  other: ["Other", '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'],
};
// Common tools, offered as one-click shortcuts while a project has none.
const LINK_SUGGESTIONS = [
  ["Overleaf", "https://www.overleaf.com/project"], ["Zotero", "zotero://select/library"],
  ["Google Scholar", "https://scholar.google.com/"], ["arXiv", "https://arxiv.org/"],
  ["GitHub", "https://github.com/"], ["Colab", "https://colab.research.google.com/"],
];

const linkIcon = (kind, size = 16) =>
  `<svg class="link-icon k-${esc(kind)}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${(LINK_KINDS[kind] || LINK_KINDS.other)[1]}</svg>`;

function remembered(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
}
function remember(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* only a convenience */ }
}

state.researchTab = remembered("studypal.researchTab", "notes");
state.openNote = {};         // "research:<id>" or "notes:<course id>" -> the note shown
state.noteDraft = null;      // {id, title, body} typed but not saved yet
state.notePreview = false;
state.noteSearch = "";
state.noteTopic = "";        // a subject's notes shown: "" all, "none" without a topic, else a topic id

// The notes editor serves both a project's notes and a subject's (the Notes page); these say which.
const courseNotes = () => state.view.name === "notes";
const noteKey = () => `${state.view.name}:${state.view.id}`;
const noteCall = (what) => (courseNotes() ? `${what}_course_note` : `${what}_note`);
state.sourceFilter = "all";

// ---------- the card in the overview ----------

function projectCard(p) {
  const segments = Math.min(p.tasks_total, 24);
  const done = p.tasks_total ? Math.round((p.tasks_done / p.tasks_total) * segments) : 0;
  const bar = p.tasks_total
    ? `<div class="task-bar" title="${p.tasks_done} of ${p.tasks_total} tasks done">${Array.from({ length: segments }, (_, i) =>
      `<i class="${i < done ? "on" : ""}"></i>`).join("")}</div>` : `<div class="task-bar empty"><i></i></div>`;
  const tags = p.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(" ");
  return `<div class="card research s-${esc(p.status)}" style="--course:${esc(cc(p.color))}" tabindex="0" data-act="open-research" data-id="${p.id}" data-kind="project">
    ${p.due_days === null || p.due_days === undefined ? '<div class="tt-when over"><span class="tt-num">–</span></div>'
      : countdown({ days_left: p.due_days })}
    ${dragHandle()}
    <div class="card-top">
      <span class="kind-label">${ICONS.research} Research</span>
      <span class="card-name">${esc(p.title)}</span>
      <span class="card-exam"><span class="tag status-tag st-${esc(p.status)}">${esc(p.status_label)}</span>${p.end_label ? ` <span>Due ${esc(p.end_label)}</span>` : ""}</span>
    </div>
    ${bar}
    <div class="card-words">${p.tasks_total ? `<span>${p.tasks_done}/${p.tasks_total} tasks</span>` : '<span class="muted">No tasks yet</span>'}
      ${p.next_task ? `<span class="muted">Next: ${esc(p.next_task)}</span>` : ""}</div>
    <div class="card-facts">${metaParts(p.facts)}${tags ? ` <span class="card-tags">${tags}</span>` : ""}</div>
    <div class="card-actions">
      <button class="btn small" data-act="start-studying" data-project="${p.id}">${ICONS.play} Work</button>
      <button class="btn small" data-act="log-time" data-project="${p.id}">Log time</button>
    </div>
  </div>`;
}

// ---------- the project page ----------

function renderResearch(d) {
  const p = d.project;
  const counts = { notes: d.notes.length, journal: d.entries.length, tasks: d.tasks.length ? `${d.tasks_done}/${d.tasks.length}` : 0,
    sources: d.sources.length, tools: d.links.length, time: 0 };
  if (!PROJECT_TABS.some(([k]) => k === state.researchTab)) state.researchTab = "notes";
  const tabs = PROJECT_TABS.map(([key, label]) => `<button class="tab${state.researchTab === key ? " on" : ""}" role="tab"
      aria-selected="${state.researchTab === key}" data-act="research-tab" data-tab="${key}">${label}${counts[key] ? ` <span class="count">${counts[key]}</span>` : ""}</button>`).join("");
  const dates = [p.start_label && `Started ${esc(p.start_label)}`, p.end_label && `target ${esc(p.end_label)} (${esc(p.due_words)})`].filter(Boolean).join(" · ");
  const chips = d.links.map((x) => `<button class="link-chip" data-act="open-link" data-url="${esc(x.url)}" title="${esc(x.url)}">${linkIcon(x.kind, 14)}<span>${esc(x.name)}</span></button>`).join("");
  return `<div class="subject-head research-head" style="--course:${esc(cc(p.color))}">
    <div class="crumbs"><button class="btn small ghost" data-go="overview">${ICONS.back} Overview</button></div>
    <div class="title-line">
      <span class="kind-label big">${ICONS.research} Research</span><h1>${esc(p.title)}</h1>
      <select class="status-pick st-${esc(p.status)}" data-change="project-status" data-id="${p.id}" aria-label="Status">
        ${d.statuses.map(([v, l]) => `<option value="${v}"${v === p.status ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
      <div class="title-actions">
        <button class="btn" data-act="log-time" data-project="${p.id}">Log time</button>
        <button class="btn primary" data-act="start-studying" data-project="${p.id}">${ICONS.play} Start working</button>
        <button class="icon-btn" data-act="project-menu" title="More" aria-label="More">${ICONS.more}</button>
      </div>
    </div>
    <div class="panel hero research-hero">
      <div class="hero-top">
        <span class="muted">${dates || "No dates set"}</span>
        <span class="muted">${esc(d.week_total)} this week · ${esc(d.total)} in total</span>
      </div>
      ${p.tags.length ? `<div class="tags-line">${p.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
      ${p.description ? `<div class="md project-description">${md(p.description)}</div>` : ""}
      <div class="link-chips">${chips}<button class="link-chip add" data-act="add-link">+ Shortcut</button></div>
    </div>
  </div>
  <div class="research-body" style="--course:${esc(cc(p.color))}">
    <nav class="tabs" role="tablist">${tabs}</nav>
    <section class="panel tab-panel">${RESEARCH_TABS[state.researchTab](d)}</section>
  </div>`;
}

const RESEARCH_TABS = {
  notes: notesTab,
  journal: journalTab,
  tasks: tasksTab,
  sources: sourcesTab,
  tools: toolsTab,
  time: timeTab,
};

function noteMatches(n, query) {
  if (!query) return true;
  const hay = `${n.title}\n${n.body}`.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

function topicMatches(n) {
  if (!courseNotes() || !state.noteTopic) return true;
  return state.noteTopic === "none" ? !n.topic_id : String(n.topic_id) === state.noteTopic;
}

function currentNote(d) {
  const id = state.openNote[noteKey()];
  const shown = d.notes.filter(topicMatches);
  return shown.find((n) => n.id === id) || shown[0] || null;
}

// A subject's note can point to one of its topics; the list can show just one topic's notes.
function noteTopicPicker(d, note) {
  if (!courseNotes()) return "";
  const options = d.topics.map((t) => `<option value="${t.id}"${t.id === note.topic_id ? " selected" : ""}>${esc(t.title)}</option>`).join("");
  return `<select class="input note-topic" data-change="note-topic" data-id="${note.id}" aria-label="Topic">
    <option value="">No topic</option>${options}</select>`;
}

function noteTopicFilter(d) {
  if (!courseNotes() || !d.topics.length) return "";
  const opt = (v, label) => `<option value="${v}"${state.noteTopic === v ? " selected" : ""}>${esc(label)}</option>`;
  return `<select class="input note-filter" data-change="note-filter" aria-label="Show notes about">
    ${opt("", "All topics")}${opt("none", "No topic")}${d.topics.map((t) => opt(String(t.id), t.title)).join("")}</select>`;
}

function noteSnippet(body) {
  return body.replace(/\$\$[\s\S]*?\$\$/g, " … ").replace(/[#*_`>$\\-]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 90);
}

function notesTab(d) {
  const note = currentNote(d);
  if (note) state.openNote[noteKey()] = note.id;
  const shown = d.notes.filter(topicMatches);
  const items = shown.map((n) => `<li class="note-item${note && n.id === note.id ? " on" : ""}" data-act="open-note" data-id="${n.id}"
      data-search="${esc(`${n.title}\n${n.body}`)}"${noteMatches(n, state.noteSearch) ? "" : " hidden"}>
      <div class="note-name">${esc(n.title || "Untitled note")}</div>
      ${n.topic && !state.noteTopic ? `<div class="note-topic-tag">${esc(n.topic)}</div>` : ""}
      <div class="note-snip">${esc(noteSnippet(n.body)) || '<span class="faint">Empty</span>'}</div>
      <div class="note-when">${esc(n.updated_label)}</div>
    </li>`).join("");
  let editor;
  if (!note) {
    const what = !courseNotes() ? "Notes are for ideas, meeting notes, derivations, anything you want to keep."
      : state.noteTopic && state.noteTopic !== "none"
        ? `No notes about ${esc(d.topics.find((t) => String(t.id) === state.noteTopic)?.title || "this topic")} yet.`
        : "Notes are for summaries, worked examples, things to remember. A note can point to one of the topics, so you find it from there.";
    editor = `<div class="note-empty"><p>${what}
      They're saved as you type, and support <b>Markdown</b> and maths like <code>$E = mc^2$</code>.</p>
      <button class="btn primary" data-act="add-note">+ New note</button></div>`;
  } else {
    const draft = state.noteDraft && state.noteDraft.id === note.id ? state.noteDraft : note;
    const body = state.notePreview
      ? `<div class="md note-preview" data-act="note-edit-here" title="Click to edit">${md(draft.body) || '<p class="faint">Nothing written yet.</p>'}</div>`
      : `<textarea id="note-body" class="note-body" data-note="${note.id}" placeholder="Write here. **Bold**, - lists, $maths$ and [links](https://…) work." spellcheck="true">${esc(draft.body)}</textarea>`;
    editor = `<div class="note-bar">
        <input id="note-title" class="note-title" data-note="${note.id}" value="${esc(draft.title)}" placeholder="Untitled note" autocomplete="off">
        <div class="seg small-seg"><label><input type="radio" name="note-mode" data-change="note-mode" value="edit"${state.notePreview ? "" : " checked"}>Write</label><label><input type="radio" name="note-mode" data-change="note-mode" value="preview"${state.notePreview ? " checked" : ""}>Preview</label></div>
        <button class="icon-btn" data-act="note-menu" data-id="${note.id}" title="More" aria-label="More">${ICONS.more}</button>
      </div>
      ${courseNotes() ? `<div class="note-about"><span class="muted">About</span>${noteTopicPicker(d, note)}</div>` : ""}
      ${body}
      <div class="note-foot"><span>Created ${esc(note.created_label)}</span><span id="note-saved">${state.noteDraft && state.noteDraft.id === note.id ? "Not saved yet…" : `Saved · edited ${esc(note.updated_label)}`}</span></div>`;
  }
  return `<div class="notes">
    <aside class="note-list">
      <div class="note-tools">
        <input type="search" id="note-search" placeholder="Search notes" value="${esc(state.noteSearch)}" autocomplete="off" aria-label="Search notes">
        <button class="btn small" data-act="add-note" title="New note">+ New</button>
      </div>
      ${noteTopicFilter(d) ? `<div class="note-tools">${noteTopicFilter(d)}</div>` : ""}
      ${shown.length ? `<ul>${items}</ul><p class="note-none faint"${shown.some((n) => noteMatches(n, state.noteSearch)) ? " hidden" : ""}>No notes match.</p>` : `<p class="faint note-none">${d.notes.length ? "No notes about this topic." : "No notes yet."}</p>`}
    </aside>
    <div class="note-editor">${editor}</div>
  </div>`;
}

function journalTab(d) {
  const entries = d.entries.map((e) => `<li class="entry" data-id="${e.id}">
      <div class="entry-day">${esc(e.day_label)}</div>
      <div class="md entry-body">${md(e.body)}</div>
      <span class="row-actions">${iconBtn("edit", "edit-entry", `data-id="${e.id}"`, "Edit")}${iconBtn("trash", "delete-entry", `data-id="${e.id}"`, "Delete")}</span>
    </li>`).join("");
  return `<div class="section-head tab-head"><h2>Journal</h2><button class="btn small" data-act="add-entry">+ New entry</button></div>
    ${entries ? `<ol class="journal">${entries}</ol>`
      : '<p class="empty-small">A dated log of what you tried and what came out of it: experiments, results, decisions. Future you writing the methods section will be grateful.</p>'}`;
}

function tasksTab(d) {
  const rows = d.tasks.map((t) => `<li class="row task-row${t.done ? " done" : ""}" data-id="${t.id}">
      ${dragHandle()}
      <input type="checkbox" class="check" data-act="toggle-task" data-id="${t.id}"${t.done ? " checked" : ""} aria-label="Done">
      <div class="grow"><div class="title wrap">${esc(t.text)}</div>${t.done_label ? `<div class="sub">Done ${esc(t.done_label)}</div>` : ""}</div>
      <span class="row-actions">${iconBtn("edit", "edit-task", `data-id="${t.id}"`, "Edit")}${iconBtn("trash", "delete-task", `data-id="${t.id}"`, "Delete")}</span>
    </li>`).join("");
  return `<div class="section-head tab-head"><h2>Next steps · ${d.tasks_done}/${d.tasks.length} done</h2></div>
    <form class="task-add" data-form="add-task"><input id="task-new" placeholder="Add a next step and press Enter" autocomplete="off" aria-label="New task"></form>
    ${rows ? `<ul class="list" data-sortable="task">${rows}</ul>` : '<p class="empty-small">Nothing planned yet.</p>'}`;
}

function sourcesTab(d) {
  const shown = d.sources.filter((s) => state.sourceFilter === "all" || s.status === state.sourceFilter);
  const filters = [["all", `All ${d.sources.length}`], ...READING_STATUS.map(([v, l]) => [v, `${l} ${d.reading[v]}`])];
  const rows = shown.map((s) => `<li class="row source-row" data-id="${s.id}">
      ${dragHandle()}
      <select class="status-pick rs-${esc(s.status)}" data-change="source-status" data-id="${s.id}" aria-label="Reading status">
        ${READING_STATUS.map(([v, l]) => `<option value="${v}"${v === s.status ? " selected" : ""}>${l}</option>`).join("")}</select>
      <div class="grow">
        <div class="title wrap">${s.link ? `<a href="${esc(s.link)}">${esc(s.title)}</a>` : esc(s.title)}</div>
        <div class="sub">${esc([s.authors.split(";").map((a) => a.split(",")[0].trim()).filter(Boolean).join(", "), s.year].filter(Boolean).join(" · ") || "—")}</div>
        ${s.annotation ? `<div class="annotation">${esc(s.annotation)}</div>` : ""}
      </div>
      <span class="row-actions">${iconBtn("copy", "copy-project-apa", `data-id="${s.id}"`, "Copy APA reference")}${iconBtn("edit", "edit-project-source", `data-id="${s.id}"`, "Edit")}${iconBtn("trash", "delete-project-source", `data-id="${s.id}"`, "Delete")}</span>
    </li>`).join("");
  return `<div class="section-head tab-head"><h2>References</h2>
      <span>${d.sources.length ? `<button class="btn small ghost" data-act="copy-project-apa-all">${ICONS.copy} Copy all as APA</button>` : ""}
      <button class="btn small" data-act="add-project-source">+ Add reference</button></span></div>
    ${d.sources.length ? `<div class="filter-line"><div class="seg small-seg">${filters.map(([v, l]) =>
      `<label><input type="radio" name="source-filter" data-change="source-filter" value="${v}"${state.sourceFilter === v ? " checked" : ""}>${esc(l)}</label>`).join("")}</div></div>` : ""}
    ${rows ? `<ul class="list" data-sortable="source">${rows}</ul>`
      : d.sources.length ? '<p class="empty-small">None with this status.</p>'
      : '<p class="empty-small">Papers, books and pages for this project, with where you are in reading them and a line on why they matter.</p>'}`;
}

function toolsTab(d) {
  const rows = d.links.map((x) => `<li class="row link-row" data-id="${x.id}">
      ${dragHandle()}
      <span class="link-badge k-${esc(x.kind)}">${linkIcon(x.kind)}</span>
      <div class="grow"><div class="title"><button class="link" data-act="open-link" data-url="${esc(x.url)}">${esc(x.name)}</button></div>
        <div class="sub">${esc(x.host)} · ${esc((LINK_KINDS[x.kind] || LINK_KINDS.other)[0])}</div></div>
      <span class="row-actions">${iconBtn("edit", "edit-link", `data-id="${x.id}"`, "Edit")}${iconBtn("trash", "delete-link", `data-id="${x.id}"`, "Delete")}</span>
    </li>`).join("");
  const suggestions = LINK_SUGGESTIONS.filter(([name]) => !d.links.some((x) => x.name.toLowerCase() === name.toLowerCase()))
    .map(([name, url], i) => `<button class="link-chip" data-act="suggest-link" data-i="${i}">+ ${esc(name)}</button>`).join("");
  return `<div class="section-head tab-head"><h2>Shortcuts</h2><button class="btn small" data-act="add-link">+ Add shortcut</button></div>
    ${rows ? `<ul class="list" data-sortable="link">${rows}</ul>` : '<p class="empty-small">One click to the tools this project lives in: the Overleaf draft, the Zotero collection, the repo, the notebook, the dataset.</p>'}
    ${suggestions ? `<div class="suggest"><span class="muted">Quick add:</span> ${suggestions}</div>` : ""}`;
}

function timeTab(d) {
  const rows = d.sessions.map((s) => `<li class="row">
      <div class="grow"><div class="title">${esc(s.started_label)}</div><div class="sub">${esc(s.note || "—")}</div></div>
      <span class="when">${esc(s.length)}</span>
      <span class="row-actions">${iconBtn("edit", "edit-project-session", `data-id="${s.id}"`, "Edit")}${iconBtn("trash", "delete-project-session", `data-id="${s.id}"`, "Delete")}</span>
    </li>`).join("");
  return `<div class="section-head tab-head"><h2>Time</h2><span class="muted">${esc(d.week_total)} this week · ${esc(d.total)} total</span></div>
    ${rows ? `<ul class="list">${rows}</ul>` : `<p class="empty-small">Press <b>Start working</b> for a timer or Pomodoro, and the time shows up here and in the week chart.</p>`}`;
}

// ---------- a subject's Notes page ----------

function renderNotes(d) {
  const c = d.course;
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-act="open-subject" data-id="${c.id}">${ICONS.back} ${esc(c.code)} ${esc(c.name)}</button></div>
    <div class="title-line"><h1>Notes</h1>${d.notes.length ? `<span class="h-count">${d.notes.length}</span>` : ""}</div>
  </div>
  <section class="panel tab-panel course-notes" style="--course:${esc(cc(c.color))}">${notesTab(d)}</section>`;
}

// ---------- notes: saved while you type ----------

let noteTimer = null;
let noteSaving = null;

function noteChanged() {
  const title = $("#note-title"), body = $("#note-body");
  const id = Number((title || body).dataset.note);
  const saved = state.data.notes.find((n) => n.id === id);
  state.noteDraft = { id, title: title ? title.value : saved.title, body: body ? body.value : (state.noteDraft?.body ?? saved.body) };
  const label = $("#note-saved");
  if (label) label.textContent = "Saving…";
  clearTimeout(noteTimer);
  noteTimer = setTimeout(saveNote, 700);
}

async function saveNote() {
  clearTimeout(noteTimer);
  if (noteSaving) await noteSaving;
  const draft = state.noteDraft;
  if (!draft) return;
  noteSaving = (async () => {
    try {
      const saved = await call(noteCall("save"), draft);
      // Only clean if nothing more was typed while this was on its way.
      if (state.noteDraft && state.noteDraft.title === draft.title && state.noteDraft.body === draft.body) state.noteDraft = null;
      const note = state.data?.notes?.find((n) => n.id === saved.id);
      if (note) Object.assign(note, { ...saved, topic_id: note.topic_id, topic: note.topic });
      const item = document.querySelector(`.note-item[data-id="${saved.id}"]`);
      if (item) {
        item.querySelector(".note-name").textContent = saved.title || "Untitled note";
        item.querySelector(".note-snip").textContent = noteSnippet(saved.body);
        item.querySelector(".note-when").textContent = saved.updated_label;
        item.dataset.search = `${saved.title}\n${saved.body}`;
      }
      const label = $("#note-saved");
      if (label && !state.noteDraft) label.textContent = `Saved · edited ${saved.updated_label}`;
      scheduleSync(5000);
    } catch (e) {
      const label = $("#note-saved");
      if (label) label.textContent = "Not saved";
      toast(e.message, true);
      if (/deleted/.test(e.message)) state.noteDraft = null;
    }
  })();
  await noteSaving;
  noteSaving = null;
}

// Whatever redraws the page (a sync, the clock, leaving it) saves the note first.
beforeRefresh = async () => { if (state.noteDraft) await saveNote(); };
window.addEventListener("blur", () => { if (state.noteDraft) saveNote(); });

function filterNotes() {
  const items = document.querySelectorAll(".note-item");
  let any = false;
  items.forEach((li) => {
    const show = noteMatches({ title: "", body: li.dataset.search }, state.noteSearch);
    li.hidden = !show;
    any = any || show;
  });
  const none = $(".note-none");
  if (none && items.length) none.hidden = any;
}

document.addEventListener("input", (e) => {
  if (e.target.id === "note-title" || e.target.id === "note-body") noteChanged();
  if (e.target.id === "note-search") { state.noteSearch = e.target.value; filterNotes(); }
});
document.addEventListener("focusout", (e) => {
  if ((e.target.id === "note-title" || e.target.id === "note-body") && state.noteDraft) saveNote();
});
document.addEventListener("keydown", (e) => {
  // Tab in a note indents instead of leaving the field; ⌘S / Ctrl+S saves straight away.
  if (e.target.id === "note-body" && e.key === "Tab" && !e.shiftKey) {
    e.preventDefault();
    document.execCommand("insertText", false, "  ");
  }
  if ((e.target.id === "note-body" || e.target.id === "note-title") && e.key.toLowerCase() === "s" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    saveNote();
  }
  if (e.target.id === "note-title" && e.key === "Enter") { e.preventDefault(); $("#note-body")?.focus(); }
});

// ---------- forms ----------

function projectForm(p = null) {
  const isNew = !p;
  openForm({
    title: isNew ? "Add a research project" : "Edit project",
    intro: isNew ? "A thesis, a paper, a side project: anything you're investigating rather than taking an exam in." : "",
    wide: true,
    fields: [
      { name: "id", type: "hidden", value: p?.id ?? "" },
      { name: "title", label: "Title", value: p?.title ?? "", placeholder: "Uncertainty in small language models" },
      { name: "description", label: "Description (optional)", type: "textarea", rows: 4, value: p?.description ?? "",
        placeholder: "The question, the plan, who's supervising…", hint: "Markdown and $maths$ work here." },
      { row: [
        { name: "status", label: "Status", type: "select", value: p?.status ?? "active", options: Object.entries(PROJECT_STATUS_LABELS) },
        { name: "tags", label: "Tags (optional)", value: p?.tags_text ?? "", placeholder: "thesis, nlp", hint: "Separated by commas" },
      ] },
      { row: [
        { name: "start_on", label: "Started", type: "date", value: p ? p.start_on ?? "" : localDate() },
        { name: "end_on", label: "Target date (optional)", type: "date", value: p?.end_on ?? "", hint: "A deadline or when you hope to be done" },
      ] },
      { name: "color", label: "Colour", type: "color", value: p?.color ?? state.nextColor ?? (state.colors || [])[0], options: state.colors || [] },
    ],
    submit: isNew ? "Add project" : "Save",
    onSubmit: async (v) => {
      const r = await call("save_project", v);
      if (isNew) { state.view = { name: "research", id: r.id }; state.researchTab = "notes"; }
      return r;
    },
  });
  $("#modal-root textarea").style.fontFamily = "inherit";
}

function entryForm(projectId, e = null) {
  openForm({
    title: e ? "Edit journal entry" : "New journal entry",
    wide: true,
    fields: [
      { name: "id", type: "hidden", value: e?.id ?? "" },
      { name: "day", label: "Day", type: "date", value: e?.day ?? localDate() },
      { name: "body", label: "What happened?", type: "textarea", rows: 9, value: e?.body ?? "",
        placeholder: "Ran the baseline: accuracy 0.91, ECE 0.064. Next: try label smoothing.", hint: "Markdown and $maths$ work here." },
    ],
    submit: e ? "Save" : "Add entry",
    onSubmit: (v) => call("save_entry", { ...v, project_id: projectId }),
  });
  $("#modal-root textarea").style.fontFamily = "inherit";
}

function linkForm(projectId, link = null, preset = null) {
  openForm({
    title: link ? "Edit shortcut" : "Add a shortcut",
    fields: [
      { name: "id", type: "hidden", value: link?.id ?? "" },
      { name: "url", label: "Address", value: link?.url ?? preset?.[1] ?? "", placeholder: "https://www.overleaf.com/project/…",
        hint: "A web address, a DOI, or a zotero:// or obsidian:// link." },
      { row: [
        { name: "name", label: "Name", value: link?.name ?? preset?.[0] ?? "", placeholder: "Thesis draft" },
        { name: "category", label: "Icon", type: "select", value: link?.category || "auto",
          options: [["auto", "Guess from the address"], ...Object.entries(LINK_KINDS).map(([k, [l]]) => [k, l])] },
      ] },
    ],
    submit: link ? "Save" : "Add",
    onSubmit: (v) => call("save_link", { ...v, project_id: projectId }),
  });
}

function projectSourceForm(projectId, s = null) {
  openForm({
    title: s ? "Edit reference" : "Add a reference",
    wide: true,
    fields: [
      { name: "id", type: "hidden", value: s?.id ?? "" },
      { name: "title", label: "Title", value: s?.title ?? "", placeholder: "Attention is all you need" },
      { row: [
        { name: "authors", label: "Authors", value: s?.authors ?? "", placeholder: "Vaswani, Ashish; Shazeer, Noam", hint: "Last name, first name; separated by semicolons" },
        { name: "year", label: "Year", value: s?.year ?? "", placeholder: "2017" },
      ] },
      { row: [
        { name: "link", label: "Link or DOI (optional)", value: s?.link ?? "", placeholder: "10.48550/arXiv.1706.03762" },
        { name: "status", label: "Reading", type: "seg", value: s?.status ?? "to_read", options: READING_STATUS },
      ] },
      { name: "annotation", label: "Annotation (optional)", type: "textarea", rows: 3, value: s?.annotation ?? "",
        placeholder: "Why it matters for this project, what to take from it" },
    ],
    submit: s ? "Save" : "Add",
    onSubmit: (v) => call("save_project_source", { ...v, project_id: projectId }),
  });
  $("#modal-root textarea").style.fontFamily = "inherit";
}

function taskForm(t) {
  openForm({
    title: "Edit task",
    fields: [{ name: "id", type: "hidden", value: t.id }, { name: "text", label: "Task", value: t.text }],
    onSubmit: (v) => call("save_task", v),
  });
}

// ---------- actions ----------

const inData = (key, id) => findIn(state.data[key], id);

// A filtered list was dragged: fit its new order back in among the items that weren't shown.
function mergedOrder(all, shown) {
  const visible = new Set(shown);
  const queue = [...shown];
  return all.map((id) => (visible.has(id) ? queue.shift() : id));
}

Object.assign(SORTED, {
  task: (items) => call("move_items", "task", items.map((el) => Number(el.dataset.id))),
  link: (items) => call("move_items", "link", items.map((el) => Number(el.dataset.id))),
  source: (items) => call("move_items", "source", mergedOrder(state.data.sources.map((s) => s.id), items.map((el) => Number(el.dataset.id)))),
});

async function copyApa(sources) {
  const text = sources.map((s) => s.apa).join("\n");
  try {
    await call("copy_to_clipboard", text, sources.map((s) => `<p>${esc(s.apa)}</p>`).join(""));
    toast(sources.length > 1 ? `Copied ${sources.length} references.` : "Copied the reference.");
  } catch (e) {
    toast(e.message, true);
  }
}

Object.assign(actions, {
  "open-research": (el) => go({ name: "research", id: Number(el.dataset.id) }),
  "add-project": () => projectForm(),
  "research-tab": (el) => {
    state.researchTab = el.dataset.tab;
    remember("studypal.researchTab", el.dataset.tab);
    refresh();
  },
  "project-menu": () => {
    const p = state.data.project;
    openMenu($("[data-act=project-menu]"), [
      { label: "Edit project", onClick: () => projectForm(p) },
      { label: p.done ? "Move back to active" : "Mark as done", onClick: async () => {
        await act("set_project_status", p.id, p.done ? "active" : "done");
        if (!p.done) toast(`“${p.title}” moved to Finished. Nothing was deleted.`);
      } },
      "-",
      { label: "Delete project…", danger: true, onClick: async () => {
        if (await confirmBox(`Delete “${p.title}”?`, "This deletes the project with all its notes, journal, tasks, references, shortcuts and study time. It can't be undone. If you're just done with it, mark it as done instead.")) {
          state.view = { name: "overview" };
          await act("delete_project", p.id);
        }
      } },
    ]);
  },

  "open-notes": async (el) => {
    await beforeRefresh();
    state.noteTopic = "";
    state.noteSearch = "";
    go({ name: "notes", id: Number(el.dataset.id) });
  },
  // From a topic on the subject page: its notes, or a new one about it if there are none yet.
  "topic-notes": async (el) => {
    const courseId = state.view.id, topicId = Number(el.dataset.topic);
    const topic = state.data.topics.find((t) => t.id === topicId);
    state.noteTopic = String(topicId);
    state.noteSearch = "";
    state.notePreview = false;
    try {
      if (topic && !topic.notes) {
        const n = await call("add_course_note", courseId, topicId);
        state.openNote[`notes:${courseId}`] = n.id;
        scheduleSync();
      }
      state.view = { name: "notes", id: courseId };
      $("#view").scrollTop = 0;
      await refresh();
      if (topic && !topic.notes) $("#note-title")?.focus();
    } catch (e) {
      toast(e.message, true);
    }
  },
  "add-note": async () => {
    await beforeRefresh();
    try {
      const topic = courseNotes() && state.noteTopic && state.noteTopic !== "none" ? Number(state.noteTopic) : null;
      const n = await (courseNotes() ? call("add_course_note", state.view.id, topic) : call("add_note", state.view.id));
      state.openNote[noteKey()] = n.id;
      state.notePreview = false;
      state.noteSearch = "";
      await refresh();
      $("#note-title")?.focus();
      scheduleSync();
    } catch (e) {
      toast(e.message, true);
    }
  },
  "open-note": async (el) => {
    await beforeRefresh();
    state.openNote[noteKey()] = Number(el.dataset.id);
    refresh();
  },
  "note-edit-here": async () => {
    state.notePreview = false;
    await refresh();
    $("#note-body")?.focus();
  },
  "note-menu": (el) => {
    const n = inData("notes", el.dataset.id);
    openMenu(el, [
      { label: "Copy as Markdown", onClick: () => call("copy_to_clipboard", `# ${n.title}\n\n${n.body}`, md(n.body)).then(() => toast("Copied.")) },
      "-",
      { label: "Delete note…", danger: true, onClick: async () => {
        if (await confirmBox(`Delete “${n.title || "Untitled note"}”?`, "The note is deleted for good.")) {
          state.noteDraft = null;
          clearTimeout(noteTimer);
          act(noteCall("delete"), n.id);
        }
      } },
    ]);
  },

  "add-entry": () => entryForm(state.view.id),
  "edit-entry": (el) => entryForm(state.view.id, inData("entries", el.dataset.id)),
  "delete-entry": async (el) => {
    const e = inData("entries", el.dataset.id);
    if (await confirmBox("Delete journal entry?", `${e.day_label}: ${noteSnippet(e.body)}`)) act("delete_entry", e.id);
  },

  "toggle-task": (el) => act("toggle_task", Number(el.dataset.id)),
  "edit-task": (el) => taskForm(inData("tasks", el.dataset.id)),
  "delete-task": (el) => act("delete_task", Number(el.dataset.id)),

  "add-project-source": () => projectSourceForm(state.view.id),
  "edit-project-source": (el) => projectSourceForm(state.view.id, inData("sources", el.dataset.id)),
  "delete-project-source": async (el) => {
    const s = inData("sources", el.dataset.id);
    if (await confirmBox("Delete reference?", s.title)) act("delete_project_source", s.id);
  },
  "copy-project-apa": (el) => copyApa([inData("sources", el.dataset.id)]),
  "copy-project-apa-all": () => copyApa(state.data.sources),

  "add-link": () => linkForm(state.view.id),
  "suggest-link": (el) => {
    const left = LINK_SUGGESTIONS.filter(([name]) => !state.data.links.some((x) => x.name.toLowerCase() === name.toLowerCase()));
    linkForm(state.view.id, null, left[Number(el.dataset.i)]);
  },
  "edit-link": (el) => linkForm(state.view.id, inData("links", el.dataset.id)),
  "delete-link": async (el) => {
    const x = inData("links", el.dataset.id);
    if (await confirmBox("Delete shortcut?", x.name)) act("delete_link", x.id);
  },
  "open-link": (el) => call("open_link", el.dataset.url).catch((e) => toast(e.message, true)),

  "edit-project-session": (el) => sessionForm(null, inData("sessions", el.dataset.id)),
  "delete-project-session": async (el) => {
    const s = inData("sessions", el.dataset.id);
    if (await confirmBox("Delete this study time?", `${s.started_label} · ${s.length}`)) act("delete_project_session", s.id);
  },
});

document.addEventListener("change", (e) => {
  const el = e.target;
  const change = el.dataset?.change;
  if (change === "project-status") act("set_project_status", Number(el.dataset.id), el.value);
  if (change === "source-status") act("set_source_status", Number(el.dataset.id), el.value);
  if (change === "source-filter") { state.sourceFilter = el.value; refresh(); }
  if (change === "note-topic") {
    // Showing one topic's notes, the list follows the note to its new topic rather than losing it.
    if (state.noteTopic) state.noteTopic = el.value || "none";
    beforeRefresh().then(() => act("save_course_note", { id: Number(el.dataset.id), topic_id: el.value ? Number(el.value) : null }));
  }
  if (change === "note-filter") {
    beforeRefresh().then(() => { state.noteTopic = el.value; refresh(); });
  }
  if (change === "note-mode") {
    state.notePreview = el.value === "preview";
    beforeRefresh().then(refresh).then(() => { if (!state.notePreview) $("#note-body")?.focus(); });
  }
});

document.addEventListener("submit", async (e) => {
  if (e.target.dataset?.form !== "add-task") return;
  e.preventDefault();
  const input = $("#task-new");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const r = await act("save_task", { project_id: state.view.id, text });
  if (!r) input.value = text;
  $("#task-new")?.focus();
});
