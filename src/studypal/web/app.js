"use strict";

// ---------- talking to Python ----------

// Every call goes to the Api class in api.py. Actions answer {error: "..."} when something's wrong.
async function call(name, ...args) {
  const result = await window.pywebview.api[name](...args);
  if (result && typeof result === "object" && !Array.isArray(result) && result.error) {
    throw new UserError(result.error);
  }
  return result;
}

class UserError extends Error {}

// Run an action, show any problem as a toast, then redraw what's on screen.
async function act(name, ...args) {
  try {
    const result = await call(name, ...args);
    if (result && result.message) toast(result.message);
    await refresh();
    scheduleSync();
    return result;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

// ---------- small helpers ----------

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${Math.max(0, Math.min(100, x * 100)).toFixed(2)}%`;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const pad = (n) => String(n).padStart(2, "0");

// ---------- Markdown with maths ----------

const mdCache = new Map();

// Exam questions, research notes and the like come as Markdown with $...$ maths. HTML in them is shown as text, never run.
function md(text) {
  const src = String(text ?? "");
  if (mdCache.has(src)) return mdCache.get(src);
  const maths = [];
  const keep = (tex, display) => { maths.push({ tex, display }); return `\u0000${maths.length - 1}\u0000`; };
  let t = src
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => keep(m, true))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => keep(m, true))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, m) => keep(m, false))
    .replace(/(^|[^\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)/g, (_, pre, m) => pre + keep(m, false));
  t = t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let html;
  try {
    html = window.marked ? marked.parse(t, { gfm: true, breaks: true }) : `<p>${t.replace(/\n/g, "<br>")}</p>`;
  } catch (e) {
    html = `<p>${t.replace(/\n/g, "<br>")}</p>`;
  }
  // Links only to the web; nothing else that could do something.
  html = html.replace(/<a href="(?!https?:)[^"]*"/g, "<a").replace(/<a href=/g, '<a target="_blank" rel="noopener" href=');
  html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => {
    const m = maths[Number(i)];
    if (!window.katex) return esc(m.display ? `$$${m.tex}$$` : `$${m.tex}$`);
    try {
      // The text was escaped for HTML before marked saw it; KaTeX needs it as typed.
      const tex = m.tex.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
      return katex.renderToString(tex, { displayMode: m.display, throwOnError: false, output: "html" });
    } catch (e) {
      return esc(m.tex);
    }
  });
  if (mdCache.size > 800) mdCache.clear();
  mdCache.set(src, html);
  return html;
}

function localNow() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function localDate(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function clock(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function toast(message, isError = false) {
  if (!message) return;
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), isError ? 6000 : 3500);
}

const ICONS = {
  plus: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  person: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
  home: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></svg>',
  edit: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>',
  more: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>',
  play: '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M7 4.5v15l12-7.5z"/></svg>',
  back: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  chev: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  check: '<svg class="menu-check" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  copy: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  exam: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1z"/><path d="M16 5h2a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2"/><path d="M9 12l2 2 4-4"/></svg>',
  book: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg>',
  research: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 3v6.5L4.6 18.4A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.4-2.6L14 9.5V3"/><path d="M7.5 15h9"/></svg>',
  grip: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
};
// The handle that drags a card or row to a new place (see `sortable` below).
const dragHandle = (label = "Drag to reorder") =>
  `<button class="drag-handle" data-act="drag" title="${esc(label)}" aria-label="${esc(label)}">${ICONS.grip}</button>`;
const iconBtn = (icon, act, attrs = "", title = "") =>
  `<button class="icon-btn small" data-act="${act}" ${attrs} title="${esc(title)}" aria-label="${esc(title)}">${ICONS[icon]}</button>`;

// ---------- state ----------

const state = {
  view: { name: "overview" },
  data: null,          // what the current view was drawn from
  running: null,       // the timer or Pomodoro, as of `runningAt`
  runningAt: 0,
  phaseEnded: false,   // the Pomodoro countdown reached zero and we've asked Python to catch up
  collapsed: new Set(),// reading-list chapters folded away
  account: null,       // {configured, signed_in, email, local_subjects, sync}
  openSources: (() => { try { return new Set(JSON.parse(localStorage.getItem("studypal.openSources") || "[]")); } catch (e) { return new Set(); } })(),
  readingView: (() => { try { return localStorage.getItem("studypal.readingView") || "book"; } catch (e) { return "book"; } })(),
  syncing: false,
};

function saveOpenSources() {
  try { localStorage.setItem("studypal.openSources", JSON.stringify([...state.openSources])); } catch (e) { /* only a convenience */ }
}

// ---------- drawing ----------

function timeline(p, color, big = false) {
  const behind = p.is_behind
    ? `<div class="tl-behind" style="left:${pct(p.done)};width:${pct(p.elapsed - p.done)}"></div>` : "";
  const today = p.show_today ? `<div class="tl-today" style="left:${pct(p.elapsed)}"></div>` : "";
  return `<div class="tl${big ? " big" : ""}" style="--course:${esc(color)}">
    <div class="tl-done" style="width:${pct(p.done)}"></div>${behind}${today}</div>`;
}

function progressWords(p) {
  return `<span class="muted">${esc(p.words)}</span>${p.behind_words ? ` <span class="behind">· ${esc(p.behind_words)}</span>` : ""}`;
}

function subjectCard(c) {
  const close = c.progress.days_left >= 0 && c.progress.days_left <= 2;
  return `<div class="card has-banner" style="--course:${esc(cc(c.color))}" tabindex="0" data-act="open-subject" data-id="${c.id}" data-kind="course">
    ${courseBanner(c, "card")}
    ${dragHandle()}
    <div class="card-top">
      <span class="code">${esc(c.code)}</span>
      <span class="card-name">${esc(c.name)}</span>
      <span class="card-exam${close ? " close" : ""}">${esc(c.exam_words)} · ${esc(c.exam_label)}</span>
    </div>
    ${timeline(c.progress, cc(c.color))}
    <div class="card-words">${progressWords(c.progress)}</div>
    <div class="card-facts">${esc(c.facts)}</div>
    <div class="card-actions">
      <button class="btn small" data-act="start-studying" data-course="${c.id}">${ICONS.play} Study</button>
      <button class="btn small" data-act="log-time" data-course="${c.id}">Log time</button>
    </div>
  </div>`;
}

function deadlineRow(d, { showCourse = true } = {}) {
  const sub = [showCourse ? d.course_code : null, d.due_label].filter(Boolean).join(" · ");
  const remove = d.is_course_exam ? "" : iconBtn("trash", "delete-deadline", `data-id="${d.id}"`, "Delete");
  return `<li class="row${d.done ? " done" : ""}">
    <input type="checkbox" class="check" data-act="toggle-deadline" data-id="${d.id}" ${d.done ? "checked" : ""} title="Mark done">
    <div class="grow">
      <div class="title wrap">${esc(d.title)}</div>
      <div class="sub">${esc(sub)}</div>
    </div>
    <span class="when u-${d.urgency}">${esc(d.when)}</span>
    <span class="row-actions">${iconBtn("edit", "edit-deadline", `data-id="${d.id}"`, "Edit")}${remove}</span>
  </li>`;
}

function weakRow(w, { showCourse = true } = {}) {
  const where = [showCourse ? w.course_code : null, w.topic, w.age].filter(Boolean).join(" · ");
  return `<li class="row${w.resolved ? " done" : ""}">
    <input type="checkbox" class="check" data-act="toggle-weak" data-id="${w.id}" ${w.resolved ? "checked" : ""} title="I've got this now">
    <div class="grow">
      <div class="title wrap">${esc(w.description)}</div>
      <div class="sub">${esc(where)}</div>
    </div>
    ${w.resolved ? "" : `<span class="tag ${w.priority}">${{ high: "high", med: "medium", low: "low" }[w.priority]}</span>`}
    <span class="row-actions">${iconBtn("edit", "edit-weak", `data-id="${w.id}"`, "Edit")}${iconBtn("trash", "delete-weak", `data-id="${w.id}"`, "Delete")}</span>
  </li>`;
}

// Study time per day, with research time stacked on top of course time in its own colour.
function weekChart(d) {
  const max = Math.max(60, ...d.week.map((x) => x.minutes));
  const bars = d.week.map((x) => {
    if (!x.minutes) return `<div class="bar-wrap"><span class="bar-val"></span><div class="bar zero" style="height:2px"></div></div>`;
    const height = Math.max(4, (x.minutes / max) * 80);
    const research = x.research_minutes ? Math.max(3, height * x.research_minutes / x.minutes) : 0;
    return `<div class="bar-wrap" title="${esc(x.length)}${x.research_minutes ? ` · ${esc(minutesWords(x.research_minutes))} research` : ""}">
      <span class="bar-val">${esc(x.length)}</span>
      <div class="bar-stack" style="height:${height}px">
        ${research ? `<div class="bar research" style="height:${research}px"></div>` : ""}
        ${x.course_minutes ? `<div class="bar" style="flex:1"></div>` : ""}
      </div>
    </div>`;
  }).join("");
  const labels = d.week.map((x) => `<span class="${x.today ? "now" : ""}">${esc(x.label)}</span>`).join("");
  const legend = d.week_has_research ? `<div class="legend week-legend"><span><i style="background:var(--accent)"></i>subjects</span>
    <span><i style="background:var(--research)"></i>research</span></div>` : "";
  return `<div class="panel">
    <div class="section-head"><h2>This week</h2><span class="muted">${esc(d.week_total)}</span></div>
    <div class="week">${bars}</div><div class="week-labels">${labels}</div>${legend}
  </div>`;
}

function minutesWords(m) {
  const h = Math.floor(m / 60);
  return h ? `${h}h${m % 60 ? ` ${m % 60}m` : ""}` : `${m}m`;
}

// A course or a research project in the overview's list.
const listCard = (x) => x.kind === "project" ? projectCard(x) : subjectCard(x);

function renderOverview(d) {
  if (!d.list.length && !d.done_list.length) {
    return `<div class="welcome">
      <h1>Welcome to StudyPal</h1>
      <p>Keep track of your subjects, what you've covered, and when your exams are, all in one place.</p>
      <ol class="steps">
        <li><b>Add a subject</b> with the date you want to start studying and the exam date.</li>
        <li><b>List its topics</b>: the chapters or themes you need to know.</li>
        <li>As you work, <b>mark topics as reviewed</b> and log your study time.</li>
      </ol>
      <p class="muted">Doing research too? <button class="link" data-act="add-project">Add a research project</button> for its notes, journal, references and tasks.</p>
      ${accountWelcome()}
    </div>`;
  }
  const done = d.done_list.length
    ? `<details class="done-pane"${state.showDone ? " open" : ""} data-act-toggle="done">
        <summary>Finished (${d.done_list.length})</summary>
        <div class="cards" style="margin-top:10px" data-sortable="overview">${d.done_list.map(listCard).join("")}</div>
      </details>` : "";
  return `${greeting(d.greeting)}
  <div class="grid">
    <section>
      <div class="section-head">
        <h2>Subjects &amp; research</h2>
        <span><button class="btn small ghost" data-act="add-project">${ICONS.research} Add research</button>
        <button class="btn small" data-act="add-course">+ Add subject</button></span>
      </div>
      <div class="cards" data-sortable="overview">${d.list.map(listCard).join("") || '<p class="muted">Everything is marked finished.</p>'}</div>
      ${d.courses.length ? `<div class="legend">
        <span><i style="background:var(--accent)"></i>material done</span>
        <span><i style="background:repeating-linear-gradient(135deg,var(--warn) 0 3px,transparent 3px 5px)"></i>behind schedule</span>
        <span><i style="background:var(--text);width:3px;height:12px"></i>today</span>
      </div>` : ""}
      ${done}
    </section>
    <aside class="stack">
      <div class="panel">
        <div class="section-head"><h2>Deadlines</h2><button class="btn small ghost" data-act="add-deadline">+ Add</button></div>
        ${d.deadlines.length ? `<ul class="list">${d.deadlines.map((x) => deadlineRow(x)).join("")}</ul>` : '<p class="empty-small">Nothing due. Nice.</p>'}
      </div>
      <div class="panel">
        <div class="section-head"><h2>Weak spots</h2><button class="btn small ghost" data-act="add-weak">+ Add</button></div>
        ${d.weak_spots.length ? `<ul class="list">${d.weak_spots.map((x) => weakRow(x)).join("")}</ul>` : '<p class="empty-small">Things you find hard go here, so you remember to come back to them.</p>'}
      </div>
      ${weekChart(d)}
    </aside>
  </div>`;
}

function greeting(g) {
  return `<div class="greeting"><h1>${esc(g.hello)}!</h1><p>${esc(g.text)}</p></div>`;
}

// Every active subject together, in a thin bar pinned to the bottom of the window.
function renderOverall(o) {
  const el = $("#overall");
  if (!o || state.view.name !== "overview") { el.innerHTML = ""; el.hidden = true; return; }
  el.hidden = false;
  const mood = o.mood_words ? `<span class="tag mood-${o.mood}">${esc(o.mood_words)}</span>` : "";
  el.innerHTML = `<span class="overall-label">Overall</span>
    <div class="overall-bar" title="${esc(o.words)} · ${esc(o.total_time)} studied in total">${timeline(o, "var(--accent)")}</div>
    <span class="overall-percent">${o.percent}%</span>${mood}`;
}

const STATUSES = [["not_started", "Not started"], ["in_progress", "In progress"], ["reviewed", "Reviewed"], ["confident", "Confident"]];

function topicRow(t) {
  const options = STATUSES.map(([v, l]) => `<option value="${v}"${v === t.status ? " selected" : ""}>${l}</option>`).join("");
  const dots = [1, 2, 3, 4, 5].map((n) =>
    `<button class="${n <= t.confidence ? "on" : ""}" data-act="confidence" data-id="${t.id}" data-value="${n}" title="Confidence ${n} of 5" aria-label="Confidence ${n} of 5"></button>`).join("");
  const reading = t.reading && t.reading.required
    ? `<span class="reading-mini">${ICONS.book} ${t.reading.read}/${t.reading.required}</span>` : "";
  return `<li class="row topic-row">
    <select class="status s-${t.status}" data-change="topic-status" data-id="${t.id}" aria-label="Status">${options}</select>
    <div class="grow"><div class="title">${esc(t.title)}</div>
      <div class="sub ${t.stale ? "stale" : ""}">Last studied ${esc(t.last_studied)}${t.stale ? " · time for a refresher" : ""}</div></div>
    ${reading}
    <span class="conf" title="How confident you feel">${dots}</span>
    <span class="row-actions">${iconBtn("play", "start-studying", `data-course="${state.view.id}" data-topic="${t.id}"`, "Study this topic")}${iconBtn("edit", "edit-topic", `data-id="${t.id}"`, "Edit")}${iconBtn("trash", "delete-topic", `data-id="${t.id}"`, "Delete")}</span>
  </li>`;
}

function renderSubject(d) {
  const c = d.course, p = c.progress;
  // Near either end the label would sit on top of the start or exam date; the marker alone says enough there.
  const todayLabel = p.show_today && p.elapsed > 0.12 && p.elapsed < 0.88
    ? `<span class="mid" style="left:${pct(p.elapsed)}">today</span>` : "";
  const sessions = d.sessions.map((s) => `<li class="row">
      <div class="grow"><div class="title">${esc(s.started_label)}</div>
        <div class="sub">${esc([s.topic, s.note].filter(Boolean).join(" · ") || "—")}</div></div>
      <span class="when">${esc(s.length)}</span>
      <span class="row-actions">${iconBtn("edit", "edit-session", `data-id="${s.id}"`, "Edit")}${iconBtn("trash", "delete-session", `data-id="${s.id}"`, "Delete")}</span>
    </li>`).join("");
  const readingLabel = d.reading.required ? `Reading list · ${d.reading.read}/${d.reading.required}` : "Reading list";
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-go="overview">${ICONS.back} All subjects</button></div>
    ${courseBanner(c, "page")}
    <div class="title-line">
      <span class="code">${esc(c.code)}</span><h1>${esc(c.name)}</h1>
      ${c.done ? '<span class="tag">finished</span>' : ""}
      <div class="title-actions">
        <button class="btn" data-act="open-reading" data-id="${c.id}">${ICONS.book} ${esc(readingLabel)}</button>
        <button class="btn" data-act="open-exams" data-id="${c.id}">${ICONS.exam} ${d.exams ? `Exams · ${d.exams}` : "Exams"}</button>
        <button class="btn" data-act="log-time" data-course="${c.id}">Log time</button>
        <button class="btn primary" data-act="start-studying" data-course="${c.id}">${ICONS.play} Start studying</button>
        <button class="icon-btn" data-act="course-menu" data-id="${c.id}" title="More" aria-label="More">${ICONS.more}</button>
      </div>
    </div>
    <div class="panel hero">
      <div class="hero-top">
        <span class="big">${esc(c.exam_words)} · ${esc(c.exam_label)}</span>
        <span>${progressWords(p)}</span>
      </div>
      ${timeline(p, cc(c.color), true)}
      <div class="tl-labels"><span>Started ${esc(c.cram_start_label)}</span>${todayLabel}<span>Exam ${esc(c.exam_label)}</span></div>
      ${c.notes ? `<p class="muted" style="margin:12px 0 0">${esc(c.notes)}</p>` : ""}
    </div>
  </div>
  <div class="grid" style="--course:${esc(cc(c.color))}">
    <section class="panel">
      <div class="section-head"><h2>Topics · ${d.topics_done}/${d.topics.length} done</h2>
        <span><button class="btn small ghost" data-act="add-topics" data-course="${c.id}">+ Add several</button>
        <button class="btn small" data-act="add-topic" data-course="${c.id}">+ Add topic</button></span></div>
      ${d.topics.length ? `<ul class="list">${d.topics.map(topicRow).join("")}</ul>`
        : `<p class="empty-small">List what you need to learn for this subject. Mark each topic <b>Reviewed</b> or <b>Confident</b> as you go, and the bar above fills up.</p>`}
    </section>
    <aside class="stack">
      <div class="panel">
        <div class="section-head"><h2>Weak spots</h2><button class="btn small ghost" data-act="add-weak" data-course="${c.id}">+ Add</button></div>
        ${d.weak_spots.length ? `<ul class="list">${d.weak_spots.map((x) => weakRow(x, { showCourse: false })).join("")}</ul>` : '<p class="empty-small">None noted.</p>'}
      </div>
      <div class="panel">
        <div class="section-head"><h2>Deadlines</h2><button class="btn small ghost" data-act="add-deadline" data-course="${c.id}">+ Add</button></div>
        <ul class="list">${d.deadlines.map((x) => deadlineRow(x, { showCourse: false })).join("")}</ul>
      </div>
      <div class="panel">
        <div class="section-head"><h2>Study time</h2><span class="muted">${esc(d.week_total)} this week · ${esc(d.total)} total</span></div>
        ${sessions ? `<ul class="list">${sessions}</ul>` : '<p class="empty-small">No study time logged yet.</p>'}
      </div>
    </aside>
  </div>`;
}

function meter(r) {
  return `<div class="meter" title="${r.read} of ${r.required} needed parts read"><div style="width:${pct(r.fraction)}"></div></div>`;
}

function readingCounts(r) {
  const optional = r.optional ? ` <span class="faint">+${r.optional_read}/${r.optional} optional</span>` : "";
  return `<span class="muted">${r.read}/${r.required}</span>${optional}`;
}

function sectionRow(x) {
  const notes = [x.required ? "" : "optional", x.own_topic ? `→ ${esc(x.topic)}` : ""].filter(Boolean).join(" · ");
  return `<div class="sec${x.read ? " read" : ""}${x.required ? "" : " optional"}" data-act="toggle-section" data-id="${x.id}"
    role="checkbox" aria-checked="${x.read}" title="${x.read ? "Read. Click to untick" : "Click when you've read it"}">
    <span class="sec-box"></span>
    <span class="sec-num">${esc(x.number)}</span>
    <span class="sec-title">${esc(x.title)}</span>
    ${notes ? `<span class="sec-note">${notes}</span>` : ""}
    <button class="icon-btn small sec-menu" data-act="section-menu" data-id="${x.id}" data-required="${x.required ? 1 : 0}" aria-label="Section options">${ICONS.more}</button>
  </div>`;
}

// One chapter. In the topic view it may show only some of its sections (`sections`), and says which book it's from.
function chapterBlock(ch, { sections = ch.sections, from = null, progress = ch.progress } = {}) {
  const open = !state.collapsed.has(ch.id);
  const whole = sections.length === ch.sections.length;
  const sub = from ? `${esc(from)}${whole ? "" : " · some sections"}` : ch.topic ? `Counts toward: ${esc(ch.topic)}` : "";
  const doneWhole = !ch.sections.length && ch.read;  // a chapter without sections, ticked off
  return `<div class="chapter${doneWhole ? " read" : ""}">
    <div class="chapter-head">
      ${ch.sections.length ? `<button class="chev${open ? " open" : ""}" data-act="fold" data-id="${ch.id}" aria-label="Show sections" aria-expanded="${open}">${ICONS.chev}</button>` : '<span class="chev-gap"></span>'}
      ${whole ? `<input type="checkbox" class="check" data-act="chapter-read" data-id="${ch.id}" ${progress.complete ? "checked" : ""} title="${ch.sections.length ? "Mark the whole chapter read" : "Mark the chapter read"}" ${progress.required ? "" : "disabled"}>` : '<span class="check-gap"></span>'}
      <span class="num">${esc(ch.number)}</span>
      <div class="grow"><div class="title">${esc(ch.title) || '<span class="faint">Untitled chapter</span>'}</div>
        ${sub ? `<div class="sub">${sub}</div>` : ""}</div>
      ${readingCounts(progress)} ${meter(progress)}
      ${iconBtn("edit", "edit-chapter", `data-id="${ch.id}"`, "Edit chapter")}
      ${iconBtn("trash", "delete-chapter", `data-id="${ch.id}"`, "Delete chapter")}
    </div>
    ${open && sections.length ? `<div class="sections">${sections.map(sectionRow).join("")}</div>` : ""}
  </div>`;
}

function sectionsProgress(sections) {
  const p = { read: 0, required: 0, optional_read: 0, optional: 0 };
  for (const x of sections) {
    if (x.required) { p.required++; p.read += x.read ? 1 : 0; } else { p.optional++; p.optional_read += x.read ? 1 : 0; }
  }
  p.fraction = p.required ? p.read / p.required : 0;
  p.complete = p.required > 0 && p.read === p.required;
  return p;
}

const KIND_LABELS = { book: "Book", article: "Article", web: "Web page", notes: "Lecture notes" };

function citeButton(s, label = "Copy APA") {
  return `<button class="btn small ghost cite-btn" data-act="copy-apa" data-id="${s.id}" title="${esc(s.reference.text)}">${ICONS.copy} ${label}</button>`;
}

// A book starts folded up to one line; opening it shows its chapters and their sections.
function sourcePanel(s) {
  const n = s.chapters.length;
  const open = n > 0 && state.openSources.has(s.id);
  const meta = [s.author, s.year, s.kind !== "book" ? KIND_LABELS[s.kind] : "", n ? plural(n, "chapter") : ""].filter(Boolean).join(" · ");
  const fold = n ? `data-act="fold-source" data-id="${s.id}"` : "";
  return `<div class="panel source${open ? " open" : ""}">
    <div class="source-head${n ? " foldable" : ""}" ${fold}>
      ${n ? `<button class="chev${open ? " open" : ""}" ${fold} aria-label="Show chapters" aria-expanded="${open}">${ICONS.chev}</button>` : '<span class="chev-gap"></span>'}
      <div class="grow"><h3>${esc(s.title)}</h3>
        <div class="muted">${esc(meta)}${s.topic ? ` <span class="tag topic-tag">${esc(s.topic)}</span>` : ""}</div></div>
      ${n ? `${readingCounts(s.progress)} ${meter(s.progress)}` : ""}
      ${citeButton(s)}
      <button class="btn small" data-act="add-chapter" data-id="${s.id}">+ Chapter</button>
      <button class="icon-btn small" data-act="source-menu" data-id="${s.id}" aria-label="More">${ICONS.more}</button>
    </div>
    ${open ? s.chapters.map((ch) => chapterBlock(ch)).join("") : ""}
  </div>`;
}

// Everything on the list sorted under the topic it counts toward: a section's own topic, else its chapter's, else its book's.
function topicGroups(d) {
  const groups = new Map([...d.topics.map((t) => [t.id, { topic: t, sources: new Map(), chapters: [] }]),
                          [null, { topic: null, sources: new Map(), chapters: [] }]]);
  const group = (id) => groups.get(groups.has(id) ? id : null);
  for (const s of d.sources) {
    if (!s.chapters.length) group(s.topic_id).sources.set(s.id, s);
    for (const ch of s.chapters) {
      if (!ch.sections.length) {
        const g = group(ch.group);
        g.chapters.push({ s, ch, sections: [] });
        g.sources.set(s.id, s);
        continue;
      }
      const bySection = new Map();
      for (const x of ch.sections) {
        const key = groups.has(x.group) ? x.group : null;
        if (!bySection.has(key)) bySection.set(key, []);
        bySection.get(key).push(x);
      }
      for (const [key, sections] of bySection) {
        const g = groups.get(key);
        g.chapters.push({ s, ch, sections });
        g.sources.set(s.id, s);
      }
    }
  }
  return [...groups.values()].filter((g) => g.sources.size);
}

function renderByTopic(d) {
  return topicGroups(d).map((g) => {
    // A chapter without sections counts as one thing to read.
    const entryProgress = (e) => (e.sections.length ? sectionsProgress(e.sections) : e.ch.progress);
    const progress = g.chapters.map(entryProgress).reduce((a, p) => ({
      read: a.read + p.read, required: a.required + p.required,
      optional_read: a.optional_read + p.optional_read, optional: a.optional + p.optional }),
      { read: 0, required: 0, optional_read: 0, optional: 0 });
    progress.fraction = progress.required ? progress.read / progress.required : 0;
    progress.complete = progress.required > 0 && progress.read === progress.required;
    const literature = [...g.sources.values()].map((s) => `<span class="lit">
        <span class="lit-title">${esc(s.title)}</span>${s.year ? `<span class="faint">${esc(s.year)}</span>` : ""}
        <button class="icon-btn small" data-act="copy-apa" data-id="${s.id}" title="Copy APA reference" aria-label="Copy APA reference for ${esc(s.title)}">${ICONS.copy}</button>
      </span>`).join("");
    const chapters = g.chapters.map((e) => chapterBlock(e.ch, { sections: e.sections, from: e.s.title, progress: entryProgress(e) })).join("");
    const ids = [...g.sources.keys()].join(",");
    return `<div class="panel source">
      <div class="source-head">
        <div class="grow"><h3>${g.topic ? esc(g.topic.title) : '<span class="muted">Not linked to a topic</span>'}</h3></div>
        ${progress.required ? `${readingCounts(progress)} ${meter(progress)}` : ""}
        <button class="btn small ghost" data-act="copy-apa-list" data-ids="${ids}" title="Copy the references for this topic as an APA reference list">${ICONS.copy} Copy all APA</button>
      </div>
      <div class="lits">${literature}</div>
      ${chapters}
    </div>`;
  }).join("");
}

function renderReading(d) {
  const c = d.course;
  const byTopic = state.readingView === "topic";
  const body = byTopic ? renderByTopic(d) : d.sources.map(sourcePanel).join("");
  const toggle = d.sources.length ? `<div class="seg view-toggle" role="radiogroup" aria-label="Group the list">
      <label><input type="radio" name="reading-view" value="book" data-change="reading-view"${byTopic ? "" : " checked"}>By book</label>
      <label><input type="radio" name="reading-view" value="topic" data-change="reading-view"${byTopic ? " checked" : ""}>By topic</label>
    </div>` : "";
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-act="open-subject" data-id="${c.id}">${ICONS.back} ${esc(c.code)} ${esc(c.name)}</button></div>
    <div class="title-line"><h1>Reading list</h1>
      ${d.progress.required ? `<span class="muted">${d.progress.read} of ${d.progress.required} needed parts read</span>` : ""}
      <div class="title-actions">${toggle}<button class="btn primary" data-act="add-source" data-course="${c.id}">+ Add literature</button></div>
    </div>
    <p class="muted" style="margin:8px 0 0">Click a section to tick it off. Grayed-out sections are optional and don&apos;t count toward progress.${byTopic ? " Link a book, chapter or section to a topic to group it here." : ""}</p>
  </div>
  <div style="max-width:1280px;margin:0 auto;--course:${esc(cc(c.color))}">${body || `<div class="panel panel-body"><p class="muted" style="margin:0">Add the books, articles, web pages or lecture notes you need to read for ${esc(c.code)}. You can paste a table of contents and the sections are set up for you.</p></div>`}</div>`;
}

// ---------- copying references ----------

// Copies with formatting (italics) where it can, so pasting into Word or Google Docs keeps it. Each way
// puts exactly the reference's own HTML on the clipboard, never the app's fonts and colours.
async function copyRich(text, html) {
  // 1. The clipboard API (browsers, and app windows that allow it).
  try {
    await navigator.clipboard.write([new ClipboardItem({
      "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([text], { type: "text/plain" }) })]);
    return true;
  } catch (e) { /* not allowed here */ }
  // 2. Python puts it on the system clipboard (formatted on macOS, plain text on Windows).
  try { await call("copy_to_clipboard", text, html); return true; } catch (e) { /* no luck */ }
  // 3. Select it and copy, with neutral styling so the app's look doesn't come along.
  const holder = document.createElement("div");
  holder.innerHTML = html;
  holder.style.cssText = "all:initial;position:fixed;left:-9999px;top:0;color:#000;background:#fff;white-space:pre-wrap";
  document.body.append(holder);
  const range = document.createRange();
  range.selectNodeContents(holder);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  sel.removeAllRanges();
  holder.remove();
  return ok;
}

async function copyReferences(sources) {
  // An APA reference list is sorted by its entries' first words.
  const refs = sources.map((s) => s.reference).sort((a, b) => a.text.localeCompare(b.text));
  const text = refs.map((r) => r.text).join("\n");
  const html = refs.map((r) => `<p>${r.html}</p>`).join("");
  const ok = await copyRich(text, html);
  toast(ok ? (refs.length === 1 ? "APA reference copied." : `${refs.length} APA references copied.`)
    : "Couldn't copy. Select the reference in the edit window and copy it from there.", !ok);
}

function renderRunning() {
  const r = state.running, el = $("#running");
  if (!r) { el.innerHTML = ""; return; }
  const what = `<div class="what"><b>${r.project_id ? `${ICONS.research} ` : ""}${esc(r.label || r.course_code)}${r.topic ? ` · ${esc(r.topic)}` : ""}</b>`;
  if (r.kind === "timer") {
    el.innerHTML = `<div class="running"><span class="pulse"></span><span class="clock" id="clock"></span>
      ${what}<small>Studying. Stop when you're done and the time is saved.</small></div>
      <div class="actions"><button class="btn ghost" data-act="timer-cancel">Discard</button>
      <button class="btn primary" data-act="timer-stop">Stop and save</button></div></div>`;
  } else {
    const isBreak = r.phase === "short_break" || r.phase === "long_break";
    const ready = r.phase === "ready";
    // Focus time is up: the clock counts the extra minutes until you choose to take the break.
    const over = r.phase === "focus" && r.focus_done;
    const sub = ready ? "Break's over. Start the next focus block when you're ready."
      : isBreak ? "Take a break. Stand up, drink some water."
      : over ? `Focus block ${r.completed + 1} done. Keep going as long as you like${r.paused ? " · paused" : ""}`
      : `Focus block ${r.completed + 1}${r.paused ? " · paused" : ""}`;
    const main = ready ? `<button class="btn primary" data-act="pomo-next">Start focus</button>`
      : isBreak ? `<button class="btn" data-act="pomo-next">Skip break</button>`
      : over ? `<button class="btn primary" data-act="pomo-break">Let's take a break</button>`
      : `<button class="btn" data-act="pomo-pause">${r.paused ? "Resume" : "Pause"}</button>`;
    el.innerHTML = `<div class="running${isBreak || ready ? " break" : ""}${over ? " overtime" : ""}${r.paused ? " paused" : ""}"><span class="pulse"></span>
      <span class="clock" id="clock"></span>
      ${what}<small>${esc(over ? "Time for a break" : r.phase_label)} · ${esc(sub)}</small></div>
      <div class="actions">${main}<button class="btn${over ? "" : " primary"}" data-act="pomo-stop">Stop and save</button></div></div>`;
  }
  updateClock();
}

function updateClock() {
  const r = state.running, el = $("#clock");
  if (!r || !el) return;
  const passed = (Date.now() - state.runningAt) / 1000;
  if (r.kind === "timer") {
    el.textContent = clock(r.elapsed_seconds + passed);
  } else if (r.phase === "focus" && r.focus_done) {
    el.textContent = `+${clock(r.overtime_seconds + (r.paused ? 0 : passed))}`;
  } else if (r.remaining_seconds === null) {
    el.textContent = "—";
  } else {
    const left = r.paused ? r.remaining_seconds : r.remaining_seconds - passed;
    el.textContent = clock(left);
    if (left <= 0 && !state.phaseEnded) {
      state.phaseEnded = true;
      tick();
    }
  }
}

function renderBanner(b) {
  const el = $("#banner");
  const line = (d) => `${esc(d.title)}${d.course_code && !d.title.includes(d.course_code) ? ` (${esc(d.course_code)})` : ""} ${esc(d.when)}`;
  let html = "";
  if (b.overdue.length) html += `<div class="banner"><span>Overdue: ${b.overdue.map(line).join(" · ")}</span></div>`;
  if (b.soon.length) html += `<div class="banner soon"><span>Due within a day: ${b.soon.map(line).join(" · ")}</span></div>`;
  el.innerHTML = html;
}

async function refresh() {
  const main = $("#view");
  const scroll = main.scrollTop;
  const v = state.view;
  let data;
  await beforeRefresh();
  const focus = keepFocus();
  const view = VIEWS[v.name] || VIEWS.overview;
  try {
    data = await view.load(v.id);
  } catch (e) {
    if (v.name !== "overview") { state.view = { name: "overview" }; return refresh(); }
    main.innerHTML = `<p class="loading">${esc(e.message)}</p>`;
    return;
  }
  state.data = data;
  if (v.name === "overview") {
    $("#today").textContent = data.today;
    state.colors = data.colors;
    state.nextColor = data.next_color;
    renderBanner(data.banner);
  }
  // A page being typed into can ask not to be redrawn under the cursor (taking an exam).
  if (!(view.keep && view.keep(data))) main.innerHTML = view.render(data);
  renderOverall(v.name === "overview" ? data.overall : null);
  if ("running" in data) {
    state.running = data.running;
    state.runningAt = Date.now();
    state.phaseEnded = false;
    renderRunning();
  }
  main.scrollTop = scroll;
  restoreFocus(focus);
  afterRender();
  loadSidebar();
}

// Each page: how to load its data (given the view's id) and draw it. exams.js adds its own pages.
const VIEWS = {
  overview: { load: () => call("overview"), render: (d) => renderOverview(d) },
  subject: { load: (id) => call("subject", id), render: (d) => renderSubject(d) },
  reading: { load: (id) => call("reading", id), render: (d) => renderReading(d) },
  exams: { load: (id) => call("exams", id), render: (d) => renderExams(d) },
  research: { load: (id) => call("research", id), render: (d) => renderResearch(d) },
};

function renderView() {
  const v = state.view;
  $("#view").innerHTML = (VIEWS[v.name] || VIEWS.overview).render(state.data);
  if (v.name === "overview") renderOverall(state.data.overall);
}

// Redrawing replaces the page, which would throw away the cursor in a field you're typing in (a note saving
// itself, the clock ticking). Put it back where it was. Pages with their own needs set these hooks.
let beforeRefresh = async () => {};
let afterRender = () => {};

function keepFocus() {
  const el = document.activeElement;
  if (!el || !el.id || !$("#view").contains(el)) return null;
  return { id: el.id, start: el.selectionStart, end: el.selectionEnd, scroll: el.scrollTop };
}

function restoreFocus(f) {
  const el = f && document.getElementById(f.id);
  if (!el) return;
  el.focus({ preventScroll: true });
  try { el.setSelectionRange(f.start, f.end); } catch (e) { /* not a text field */ }
  el.scrollTop = f.scroll;
}

function go(view) {
  state.view = view;
  $("#view").scrollTop = 0;
  refresh();
}

async function tick() {
  try {
    const r = await call("tick");
    r.messages.forEach((m) => toast(m));
  } catch (e) { /* the next tick tries again */ }
  await refresh();
}

// ---------- dialogs ----------

let modalClose = null;

function closeModal() {
  $("#modal-root").innerHTML = "";
  modalClose = null;
}

// fields: [{name, label, type, value, options, hint, required, ...}] or {row: [...]}.
function fieldHtml(f) {
  if (f.only) return `<div data-only="${f.only.join(" ")}">${fieldHtml({ ...f, only: undefined })}</div>`;
  if (f.row) return `<div class="field-row">${f.row.map(fieldHtml).join("")}</div>`;
  const id = `f-${f.name}`;
  const hint = f.hint ? `<small>${f.hint}</small>` : "";
  const v = f.value ?? "";
  let input;
  switch (f.type) {
    case "hidden":
      return `<input type="hidden" name="${f.name}" value="${esc(v)}">`;
    case "html":
      return `<div class="field" data-field="${f.name}"><span>${esc(f.label)}</span>${f.html}</div>`;
    case "textarea":
      input = `<textarea id="${id}" name="${f.name}" placeholder="${esc(f.placeholder || "")}" rows="${f.rows || 6}">${esc(v)}</textarea>`;
      break;
    case "select":
      input = `<select class="input" id="${id}" name="${f.name}">${(f.options || []).map(([ov, ol]) =>
        `<option value="${esc(ov)}"${String(ov) === String(v) ? " selected" : ""}>${esc(ol)}</option>`).join("")}</select>`;
      break;
    case "seg":
      input = `<div class="seg">${f.options.map(([ov, ol]) =>
        `<label><input type="radio" name="${f.name}" value="${esc(ov)}"${String(ov) === String(v) ? " checked" : ""}>${esc(ol)}</label>`).join("")}</div>`;
      break;
    case "choices":
      input = `<div class="choices">${f.options.map(([ov, title, desc]) =>
        `<label class="choice"><input type="radio" name="${f.name}" value="${esc(ov)}"${String(ov) === String(v) ? " checked" : ""}>
          <span><b>${esc(title)}</b><small>${esc(desc)}</small></span></label>`).join("")}</div>`;
      break;
    case "color":
      input = `<input type="hidden" name="${f.name}" value="${esc(v)}"><div class="swatches">${f.options.map((c) =>
        `<button type="button" class="swatch${c === v ? " on" : ""}" style="background:${esc(cc(c))}" data-color="${esc(c)}" aria-label="Colour ${esc(c)}"></button>`).join("")}</div>`;
      break;
    case "themes":
      input = `<div class="theme-grid">${THEMES.map((t) => `<label class="theme-opt" title="${esc(t.note || t.label)}">
          <input type="radio" name="${f.name}" value="${t.name}"${t.name === v ? " checked" : ""}>
          ${themePreview(t)}<span>${esc(t.label)}</span></label>`).join("")}</div>`;
      break;
    case "checkbox":
      return `<label class="field" style="flex-direction:row;align-items:center;gap:8px"><input type="checkbox" class="check" name="${f.name}"${v ? " checked" : ""}><span style="font-weight:500">${esc(f.label)}</span></label>`;
    default:
      input = `<input type="${f.type || "text"}" id="${id}" name="${f.name}" value="${esc(v)}" placeholder="${esc(f.placeholder || "")}"${f.min !== undefined ? ` min="${f.min}"` : ""}${f.max !== undefined ? ` max="${f.max}"` : ""} autocomplete="off">`;
  }
  return `<label class="field" for="${id}"><span>${esc(f.label)}</span>${input}${hint}</label>`;
}

function formValues(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "radio") { if (el.checked) out[el.name] = el.value; }
    else if (el.type === "checkbox") out[el.name] = el.checked;
    else out[el.name] = el.value;
  }
  return out;
}

// Opens a form. onSubmit(values) may throw a UserError, which is shown in the form and keeps it open.
function openForm({ title, intro = "", fields, submit = "Save", danger = false, wide = false, onSubmit, onChange, onCancel = null, extra = "" }) {
  $("#modal-root").innerHTML = `<div class="backdrop">
    <form class="modal${wide ? " wide" : ""}" novalidate>
      <h3>${esc(title)}</h3>${intro ? `<p class="intro">${intro}</p>` : ""}
      ${fields.map(fieldHtml).join("")}
      <div class="form-error" role="alert"></div>
      <div class="modal-actions">${extra}
        <button type="button" class="btn" data-modal="cancel">Cancel</button>
        <button type="submit" class="btn ${danger ? "danger solid" : "primary"}">${esc(submit)}</button>
      </div>
    </form></div>`;
  const form = $("#modal-root form");
  const errorEl = $(".form-error", form);
  const cancel = () => { if (onCancel) onCancel(); closeModal(); };
  modalClose = cancel;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.textContent = "";
    const button = $("button[type=submit]", form);
    button.disabled = true;
    try {
      const result = await onSubmit(formValues(form), form);
      closeModal();
      if (result && result.message) toast(result.message);
      await refresh();
      scheduleSync();
    } catch (err) {
      errorEl.textContent = err.message;
      button.disabled = false;
    }
  });
  form.addEventListener("click", (e) => {
    const sw = e.target.closest(".swatch");
    if (sw) {
      form.querySelectorAll(".swatch").forEach((s) => s.classList.toggle("on", s === sw));
      sw.closest(".field").querySelector("input[type=hidden]").value = sw.dataset.color;
    }
    if (e.target.closest("[data-modal=cancel]")) cancel();
  });
  if (onChange) form.addEventListener("change", (e) => onChange(e.target, form));
  $(".backdrop").addEventListener("mousedown", (e) => { if (e.target.classList.contains("backdrop")) cancel(); });
  const first = form.querySelector("input:not([type=hidden]):not([type=radio]), textarea, select");
  if (first) first.focus();
  return form;
}

function confirmBox(title, message, yes = "Delete") {
  return new Promise((resolve) => {
    openForm({
      title, intro: esc(message), fields: [], submit: yes, danger: true,
      onSubmit: async () => resolve(true),
    });
    const cancel = $("#modal-root [data-modal=cancel]");
    cancel.addEventListener("click", () => resolve(false));
  });
}

function openMenu(anchor, items) {
  closeMenu();
  const menu = document.createElement("div");
  menu.className = "menu";
  menu.innerHTML = items.map((it, i) => it === "-" ? "<hr>"
    : it.disabled ? `<div class="menu-label">${esc(it.label)}</div>`
    : `<button data-i="${i}" class="${it.danger ? "danger" : ""}${it.html ? " rich" : ""}">${it.html || esc(it.label)}</button>`).join("");
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w))}px`;
  menu.style.top = `${r.bottom + h + 8 > window.innerHeight ? r.top - h - 4 : r.bottom + 4}px`;
  menu.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-i]");
    if (!b) return;
    closeMenu();
    items[Number(b.dataset.i)].onClick();
  });
  setTimeout(() => document.addEventListener("mousedown", outsideMenu), 0);
}
function outsideMenu(e) { if (!e.target.closest(".menu")) closeMenu(); }
function closeMenu() {
  document.querySelectorAll(".menu").forEach((m) => m.remove());
  document.removeEventListener("mousedown", outsideMenu);
}

// ---------- account and cloud sync ----------

function accountWelcome() {
  const a = state.account;
  if (!a || !a.configured || a.signed_in) {
    return `<button class="btn primary" data-act="add-course">Add your first subject</button>`;
  }
  return `<div class="welcome-account">
      <p>Create a free account to keep your subjects safe online and use StudyPal on more than one computer.</p>
      <div class="welcome-buttons">
        <button class="btn primary" data-act="sign-up">Create an account</button>
        <button class="btn" data-act="sign-in">I have an account</button>
      </div>
      <button class="link" data-act="add-course">Or just start on this computer</button>
    </div>`;
}

const SYNC_LABELS = {
  synced: (a) => `Saved online${a.sync.at ? ` · ${a.sync.at}` : ""}`,
  offline: () => "Offline · saved on this computer",
  error: () => "Not synced",
  idle: () => "Saved online",
};

// A coloured initial per account, so it's easy to see at a glance which one is in use.
function avatar(email) {
  const colors = activeTheme.accents || COURSE_COLORS;
  let h = 0;
  for (const ch of email || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `<span class="avatar" style="background:${colors[h % colors.length]}">${esc((email || "?")[0].toUpperCase())}</span>`;
}

function renderAccount() {
  const a = state.account, el = $("#account");
  if (!a || !a.configured) { el.innerHTML = ""; return; }
  if (!a.signed_in) {
    const you = `<span class="avatar local">${ICONS.person}</span>`;
    el.innerHTML = a.accounts.length
      ? `<button class="sync-chip s-local" data-act="account-menu" title="Not using an account. Click to switch.">${you}<span class="chip-email">This computer only</span><span class="sync-dot"></span></button>`
      : `<button class="sync-chip s-local" data-act="sign-in" title="Sign in">${you}<span class="chip-email">Sign in</span></button>`;
    return;
  }
  const status = state.syncing ? "syncing" : a.sync.status;
  const label = state.syncing ? "Syncing…" : SYNC_LABELS[a.sync.status](a);
  const showStatus = status !== "synced" && status !== "idle";
  const tip = `${a.email} · ${label}${a.sync.message ? ` · ${a.sync.message}` : ""}`;
  el.innerHTML = `<button class="sync-chip s-${status}" data-act="account-menu" title="${esc(tip)}">
    ${avatar(a.email)}<span class="chip-email">${esc(a.email)}</span>${showStatus ? `<span class="chip-status">${esc(label)}</span>` : ""}<span class="sync-dot"></span></button>`;
}

async function switchAccount(userId) {
  closeMenu();
  state.syncing = true;
  renderAccount();
  let r;
  try { r = await window.pywebview.api.switch_account(userId); } finally { state.syncing = false; }
  if (r.error) { toast(r.error, true); renderAccount(); return; }
  state.view = { name: "overview" };
  await loadAccount();
  await refresh();
  if (r.message) toast(r.message);
}

async function loadAccount() {
  try { state.account = await call("account"); } catch (e) { state.account = null; }
  renderAccount();
}

let syncTimer = null;
function scheduleSync(delay = 2500) {
  if (!state.account || !state.account.signed_in) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncNow, delay);
}

async function syncNow({ quiet = true } = {}) {
  if (!state.account || !state.account.signed_in || state.syncing) return;
  state.syncing = true;
  renderAccount();
  let r;
  try {
    r = await window.pywebview.api.cloud_sync();
  } finally {
    state.syncing = false;
  }
  if (r && r.signed_out) {
    toast(r.error, true);
    await loadAccount();
    await refresh();
    return;
  }
  if (r && r.sync) state.account.sync = r.sync;
  renderAccount();
  if (r && r.changed) await refresh();
  if (!quiet && r && r.sync) {
    toast(r.sync.status === "synced" ? "Everything is saved online." : r.sync.message, r.sync.status !== "synced");
  }
}

async function signInForm(email = "") {
  await loadAccount();  // how many subjects this computer has right now
  const a = state.account;
  const fields = [
    { name: "email", label: "Email", type: "email", value: email, placeholder: "you@example.com" },
    { name: "password", label: "Password", type: "password" },
  ];
  if (a.local_subjects) fields.push({ name: "bring", type: "checkbox", value: false,
    label: `Also add the ${plural(a.local_subjects, "subject")} on this computer to my account` });
  openForm({
    title: a.signed_in ? "Add another account" : "Sign in", fields, submit: "Sign in",
    intro: a.signed_in ? `${esc(a.email)} stays signed in. You can switch between accounts from the menu in the top bar.` : "",
    extra: `<button type="button" class="link left" data-act="sign-up">Create an account instead</button>`,
    onSubmit: (v) => call("sign_in", v.email, v.password, !!v.bring).then(afterAccountChange),
  });
}

async function signUpForm() {
  await loadAccount();  // how many subjects this computer has right now
  const a = state.account;
  const fields = [
    { name: "email", label: "Email", type: "email", placeholder: "you@example.com" },
    { name: "password", label: "Choose a password", type: "password", hint: "At least 8 characters." },
  ];
  if (a.local_subjects) fields.push({ name: "bring", type: "checkbox", value: true,
    label: `Move the ${plural(a.local_subjects, "subject")} on this computer into the account` });
  openForm({
    title: "Create an account",
    intro: "Your subjects are saved online, so they're safe if something happens to this computer, and you can sign in on another one.",
    fields, submit: "Create account",
    extra: `<button type="button" class="link left" data-act="sign-in">I already have an account</button>`,
    onSubmit: async (v) => {
      const r = await call("sign_up", v.email, v.password, !!v.bring);
      if (r.confirm) {
        setTimeout(() => signInForm(v.email), 0);
        return { message: r.message };
      }
      return afterAccountChange(r);
    },
  });
}

async function afterAccountChange(result) {
  state.view = { name: "overview" };
  await loadAccount();
  return result;
}

function passwordForm() {
  openForm({
    title: "Change password",
    fields: [{ name: "password", label: "New password", type: "password", hint: "At least 8 characters." }],
    onSubmit: (v) => call("change_password", v.password),
  });
}

async function signOut() {
  let r = await window.pywebview.api.sign_out(false);
  if (r.unsynced) {
    if (!(await confirmBox("Sign out anyway?", r.error, "Sign out anyway"))) return;
    r = await window.pywebview.api.sign_out(true);
  }
  if (r.error) { toast(r.error, true); return; }
  toast(r.message);
  await afterAccountChange(r);
  await refresh();
}

// ---------- sidebar ----------

// Quick access to every active subject and research project. Folds down to a rail of coloured badges;
// which way it was left is remembered on this computer.
let sideItems = { courses: [], projects: [] };

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle("side-collapsed", collapsed);
  const b = $(".side-toggle");
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.setAttribute("aria-expanded", String(!collapsed));
  try { localStorage.setItem("studypal.sidebar", collapsed ? "collapsed" : "open"); } catch (e) { /* only a convenience */ }
}

async function loadSidebar() {
  try {
    const [courses, projects] = await Promise.all([call("courses"), call("projects")]);
    sideItems = { courses: activeSubjects(courses), projects: projects.filter((p) => !p.done) };
  } catch (e) { /* keep what's shown */ }
  renderSidebar();
}

function sideLink({ act, id, color, badge, label, sub, active }) {
  return `<button class="side-item${active ? " active" : ""}" data-act="${act}" data-id="${id}" title="${esc(label)}"${active ? ' aria-current="page"' : ""}>
    <span class="side-badge" style="background:${esc(color)}">${esc(badge)}</span>
    <span class="side-text"><span class="side-label">${esc(label)}</span>${sub ? `<span class="side-sub">${esc(sub)}</span>` : ""}</span></button>`;
}

function renderSidebar() {
  const v = state.view, { courses, projects } = sideItems;
  const courseId = ["subject", "reading", "exams"].includes(v.name) ? v.id
    : ["exam", "take", "attempt"].includes(v.name) ? state.data?.course?.id : null;
  const projectId = v.name === "research" ? v.id : null;
  const head = (title, act, what) => `<div class="side-head"><span>${title}</span>${iconBtn("plus", act, "", `Add ${what}`)}</div>`;
  $("#side-nav").innerHTML = `
    <button class="side-item${v.name === "overview" ? " active" : ""}" data-go="overview" title="Overview">
      <span class="side-badge plain">${ICONS.home}</span><span class="side-text"><span class="side-label">Overview</span></span></button>
    ${head("Subjects", "add-course", "a subject")}
    ${courses.length ? courses.map((c) => sideLink({ act: "open-subject", id: c.id, color: cc(c.color), badge: (c.code || c.name).slice(0, 3),
        label: `${c.code} ${c.name}`.trim(), sub: c.exam_label ? `Exam ${c.exam_label}` : "", active: c.id === courseId })).join("")
      : `<p class="side-empty">No subjects yet</p>`}
    ${head("Research", "add-project", "a research project")}
    ${projects.length ? projects.map((p) => sideLink({ act: "open-research", id: p.id, color: cc(p.color), badge: p.title.slice(0, 1).toUpperCase(),
        label: p.title, sub: p.due_words, active: p.id === projectId })).join("")
      : `<p class="side-empty">No research projects yet</p>`}`;
}

// ---------- the forms ----------

async function subjectsWithTopics() {
  return await call("courses");
}

// What study time can be for: active subjects and research projects, as "course:3" / "project:5".
async function studyTargets(includeAll = false) {
  const [courses, projects] = await Promise.all([call("courses"), call("projects")]);
  const subjects = includeAll ? courses : activeSubjects(courses);
  const research = projects.filter((p) => includeAll || !p.done);
  return {
    courses,
    options: [...subjects.map((c) => [`course:${c.id}`, `${c.code} ${c.name}`]),
              ...research.map((p) => [`project:${p.id}`, `Research · ${p.title}`])],
  };
}

const targetOf = (value) => {
  const [kind, id] = String(value || "").split(":");
  return { course_id: kind === "course" ? Number(id) : null, project_id: kind === "project" ? Number(id) : null };
};

// Keeps a form's topic list in step with what's picked; research projects have no topics.
function linkTargetTopics(courses) {
  return (target, form) => {
    if (target.name !== "target") return;
    const select = form.querySelector("select[name=topic_id]");
    if (!select) return;
    const { course_id } = targetOf(target.value);
    select.innerHTML = topicOptions(courses, course_id).map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
    select.closest(".field").style.display = course_id ? "" : "none";
  };
}

function needSomething(options) {
  if (options.length) return true;
  toast("Add a subject or a research project first.");
  courseForm();
  return false;
}

function topicOptions(courses, courseId) {
  const c = courses.find((x) => String(x.id) === String(courseId));
  return [["", "— Whole subject —"], ...(c ? c.topics.map((t) => [t.id, t.title]) : [])];
}

// Keeps a form's topic list in step with its subject list.
function linkTopicPicker(courses) {
  return (target, form) => {
    if (target.name !== "course_id") return;
    const select = form.querySelector("select[name=topic_id]");
    if (!select) return;
    select.innerHTML = topicOptions(courses, target.value).map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  };
}

function needSubjects(courses) {
  if (courses.length) return true;
  toast("Add a subject first.");
  courseForm();
  return false;
}

function activeSubjects(courses) {
  return courses.filter((c) => !c.done);
}

function courseForm(course = null) {
  const isNew = !course;
  openForm({
    title: isNew ? "Add a subject" : `Edit ${course.code}`,
    intro: isNew ? "A subject is a course you're taking an exam in." : "",
    fields: [
      { name: "id", type: "hidden", value: course?.id ?? "" },
      { row: [
        { name: "name", label: "Name", value: course?.name ?? "", placeholder: "Machine Learning" },
        { name: "code", label: "Short code", value: course?.code ?? "", placeholder: "INF301", hint: "Shown on deadlines and lists" },
      ] },
      { row: [
        { name: "cram_start", label: "Start studying", type: "date", value: course?.cram_start ?? localDate(), hint: "When you begin preparing" },
        { name: "exam_date", label: "Exam date", type: "date", value: course?.exam_date ?? localDate(30) },
      ] },
      { name: "color", label: "Colour", type: "color", value: course?.color ?? state.nextColor ?? (state.colors || [])[0], options: state.colors || [] },
      { name: "notes", label: "Notes (optional)", type: "textarea", rows: 3, value: course?.notes ?? "", placeholder: "Exam format, allowed aids, room…" },
    ],
    submit: isNew ? "Add subject" : "Save",
    onSubmit: async (v) => {
      const r = await call("save_course", v);
      if (isNew) state.view = { name: "subject", id: r.id };
      return r;
    },
  });
  $("#modal-root textarea").style.fontFamily = "inherit";
}

function topicForm(courseId, topic = null) {
  openForm({
    title: topic ? "Edit topic" : "Add a topic",
    fields: [
      { name: "id", type: "hidden", value: topic?.id ?? "" },
      { name: "course_id", type: "hidden", value: courseId },
      { name: "title", label: "Topic", value: topic?.title ?? "", placeholder: "e.g. Support vector machines" },
      { name: "status", label: "Where are you with it?", type: "select", value: topic?.status ?? "not_started", options: STATUSES },
      { name: "confidence", label: "How confident do you feel? (1–5)", type: "seg", value: topic?.confidence ?? 1, options: [[1, "1"], [2, "2"], [3, "3"], [4, "4"], [5, "5"]] },
    ],
    submit: topic ? "Save" : "Add topic",
    onSubmit: (v) => call("save_topic", v),
  });
}

function topicsForm(courseId) {
  openForm({
    title: "Add several topics",
    intro: "One topic per line. Copying a list from the course page or syllabus works well.",
    fields: [{ name: "text", label: "Topics", type: "textarea", rows: 9, placeholder: "Linear regression\nLogistic regression\nNeural networks" }],
    submit: "Add topics",
    onSubmit: async (v) => {
      const r = await call("add_topics", courseId, v.text);
      return { message: `Added ${plural(r.added, "topic")}.` };
    },
  });
  $("#modal-root textarea").style.fontFamily = "inherit";
}

async function weakForm(courseId = null, weak = null) {
  const courses = activeSubjects(await subjectsWithTopics());
  if (!needSubjects(courses)) return;
  const cid = weak?.course_id ?? courseId ?? courses[0].id;
  openForm({
    title: weak ? "Edit weak spot" : "Note a weak spot",
    intro: weak ? "" : "Something you find hard or keep getting wrong, so you remember to come back to it.",
    fields: [
      { name: "id", type: "hidden", value: weak?.id ?? "" },
      { name: "description", label: "What's tricky?", value: weak?.description ?? "", placeholder: "e.g. Deriving the dual form" },
      { row: [
        { name: "course_id", label: "Subject", type: "select", value: cid, options: courses.map((c) => [c.id, `${c.code} ${c.name}`]) },
        { name: "topic_id", label: "Topic (optional)", type: "select", value: weak?.topic_id ?? "", options: topicOptions(courses, cid) },
      ] },
      { name: "priority", label: "How important?", type: "seg", value: weak?.priority ?? "med", options: [["low", "Low"], ["med", "Medium"], ["high", "High"]] },
    ],
    submit: weak ? "Save" : "Add",
    onSubmit: (v) => call("save_weak", v),
    onChange: linkTopicPicker(courses),
  });
}

async function deadlineForm(courseId = null, d = null) {
  const courses = activeSubjects(await subjectsWithTopics());
  const fields = [
    { name: "id", type: "hidden", value: d?.id ?? "" },
    { name: "title", label: "What's due?", value: d?.title ?? "", placeholder: "e.g. Problem set 4" },
    { name: "due_at", label: "Due", type: "datetime-local", value: d?.due_at ?? `${localDate(7)}T23:59` },
  ];
  if (!d?.is_course_exam) {
    fields.push({ row: [
      { name: "course_id", label: "Subject", type: "select", value: d?.course_id ?? courseId ?? "",
        options: [["", "— Not for a subject —"], ...courses.map((c) => [c.id, `${c.code} ${c.name}`])] },
      { name: "kind", label: "Kind", type: "select", value: d?.kind ?? "assignment",
        options: [["assignment", "Assignment"], ["exam", "Exam or test"], ["milestone", "Other milestone"]] },
    ] });
  }
  openForm({
    title: d ? "Edit deadline" : "Add a deadline",
    intro: d?.is_course_exam ? "This is the subject's exam. Changing the date here moves the exam date too." : "",
    fields, submit: d ? "Save" : "Add deadline",
    onSubmit: (v) => call("save_deadline", v),
  });
}

async function sessionForm(courseId = null, s = null, projectId = null) {
  const { courses, options } = await studyTargets(Boolean(s));
  if (!s && !needSomething(options)) return;
  const picked = s ? (s.project_id ? `project:${s.project_id}` : `course:${s.course_id}`)
    : projectId ? `project:${projectId}` : courseId ? `course:${courseId}` : options[0][0];
  const cid = targetOf(picked).course_id;
  const topic = { name: "topic_id", label: "Topic (optional)", type: "select", value: s?.topic_id ?? "", options: topicOptions(courses, cid) };
  const fields = [
    { name: "id", type: "hidden", value: s?.id ?? "" },
    s ? { name: "target", type: "hidden", value: picked } : { row: [
      { name: "target", label: "What did you work on?", type: "select", value: picked, options },
      topic,
    ] },
  ];
  if (s && cid) fields.push(topic);
  fields.push(
    { row: [
      { name: "hours", label: "Hours", type: "number", min: 0, max: 24, value: s ? Math.floor(s.minutes / 60) : 1 },
      { name: "minutes", label: "Minutes", type: "number", min: 0, max: 59, value: s ? s.minutes % 60 : 0 },
    ] },
    { name: "started_at", label: "When did you start?", type: "datetime-local", value: s?.started_at ?? localNow() },
    { name: "note", label: "Note (optional)", value: s?.note ?? "", placeholder: "e.g. Read chapter 7" },
  );
  openForm({
    title: s ? "Edit study time" : "Log study time",
    intro: s ? "" : "For studying you did without the timer running.",
    fields, submit: s ? "Save" : "Log it",
    onSubmit: (v) => call("save_session", { ...v, ...targetOf(v.target) }),
    onChange: linkTargetTopics(courses),
  });
  if (!cid) $("#modal-root select[name=topic_id]")?.closest(".field")?.style.setProperty("display", "none");
}

async function startForm(courseId = null, topicId = null, projectId = null) {
  if (state.running) { toast("You're already studying. Stop that first."); return; }
  const { courses, options } = await studyTargets();
  if (!needSomething(options)) return;
  const settings = await call("get_settings");
  const picked = projectId ? `project:${projectId}` : courseId ? `course:${courseId}` : options[0][0];
  const cid = targetOf(picked).course_id;
  openForm({
    title: "Start studying",
    fields: [
      { row: [
        { name: "target", label: "What are you working on?", type: "select", value: picked, options },
        { name: "topic_id", label: "Topic (optional)", type: "select", value: topicId ?? "", options: topicOptions(courses, cid) },
      ] },
      { name: "mode", label: "How?", type: "choices", value: state.lastMode || "timer", options: [
        ["timer", "Timer", "Runs until you press stop, then the time is saved."],
        ["pomodoro", "Pomodoro", `${settings.focus_minutes} minutes of focus, then a ${settings.short_break_minutes}-minute break. Each focus block is saved automatically.`],
      ] },
    ],
    submit: "Start",
    onSubmit: async (v) => {
      state.lastMode = v.mode;
      const t = targetOf(v.target);
      const topic = t.course_id && v.topic_id ? Number(v.topic_id) : null;
      await call(v.mode === "pomodoro" ? "pomo_start" : "timer_start", t.course_id, topic, t.project_id);
    },
    onChange: linkTargetTopics(courses),
  });
  if (!cid) $("#modal-root select[name=topic_id]").closest(".field").style.display = "none";
}

async function settingsForm() {
  const s = await call("get_settings");
  const where = await call("data_location");
  const g = await call("ai_settings");
  const before = activeTheme.name;
  const form = openForm({
    title: "Settings", wide: true,
    onCancel: () => setTheme(before, false),
    onChange: (el) => {
      if (el.name === "theme") setTheme(el.value, false);
      if (el.name === "sound" && el.checked) call("preview_sound").catch(() => {});  // so you hear what it sounds like
    },
    fields: [
      { name: "theme", label: "Theme", type: "themes", value: before },
      { row: [
        { name: "focus_minutes", label: "Focus block (min)", type: "number", min: 1, value: s.focus_minutes },
        { name: "short_break_minutes", label: "Short break (min)", type: "number", min: 1, value: s.short_break_minutes },
      ] },
      { row: [
        { name: "long_break_minutes", label: "Long break (min)", type: "number", min: 1, value: s.long_break_minutes },
        { name: "long_break_every", label: "Long break after every", type: "number", min: 1, value: s.long_break_every, hint: "focus blocks" },
      ] },
      { row: [
        { name: "week_start", label: "Week starts on", type: "select", value: s.week_start,
          options: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => [i, d]) },
        { name: "stale_after_days", label: "Remind me to revisit topics after", type: "number", min: 1, value: s.stale_after_days, hint: "days without studying them" },
      ] },
      { name: "notifications", label: "Show notifications for deadlines and Pomodoro breaks", type: "checkbox", value: !!s.notifications },
      { name: "sound", label: "Pling when a Pomodoro focus block or break ends", type: "checkbox", value: !!s.sound },
      ...aiFields(g),
    ],
    extra: `<button type="button" class="btn left" data-act="export">Save a backup…</button>`,
    intro: `<span class="faint" style="font-size:12px">Your data is stored in ${esc(where)}</span>`,
    onSubmit: async (v) => {
      await setTheme(v.theme, true);
      const rest = Object.fromEntries(Object.entries(v).filter(([k]) => k !== "theme" && !/^(ai_|key_|forget_|ollama_)/.test(k)));
      await call("save_ai", aiValues(v, g));
      return call("save_settings", { ...rest, notifications: rest.notifications ? 1 : 0, sound: rest.sound ? 1 : 0 });
    },
  });
  linkProviderFields(form);
  form.scrollTop = 0;  // open at the theme picker, not at the first text field
}

function sourceForm(courseId, source = null, topics = []) {
  const kind = source?.kind || "book";
  const fields = [
    { name: "id", type: "hidden", value: source?.id ?? "" },
    { name: "course_id", type: "hidden", value: courseId },
    { name: "kind", label: "What is it?", type: "seg", value: kind,
      options: [["book", "Book"], ["article", "Article"], ["web", "Web page"], ["notes", "Lecture notes"]] },
    { name: "title", label: "Title", value: source?.title ?? "", placeholder: "e.g. Pattern recognition and machine learning",
      hint: "APA uses sentence case: only the first word, proper nouns and the word after a colon get a capital." },
    { row: [
      { name: "author", label: "Authors", value: source?.author ?? "", placeholder: "Bishop, Christopher M.; Nasrabadi, Nasser",
        hint: "Surname, first names. Separate authors with ; (an organisation can be written as it is)." },
      { name: "year", label: "Year", value: source?.year ?? "", placeholder: "2006" },
    ] },
    { only: ["book"], row: [
      { name: "publisher", label: "Publisher", value: source?.publisher ?? "", placeholder: "Springer" },
      { name: "edition", label: "Edition", value: source?.edition ?? "", placeholder: "2" },
    ] },
    { only: ["article"], name: "journal", label: "Journal", value: source?.journal ?? "", placeholder: "Journal of Machine Learning Research" },
    { only: ["article"], row: [
      { name: "volume", label: "Volume", value: source?.volume ?? "" },
      { name: "issue", label: "Issue", value: source?.issue ?? "" },
      { name: "pages", label: "Pages", value: source?.pages ?? "", placeholder: "1-25" },
    ] },
    { only: ["web"], name: "publisher", label: "Website name", value: source?.publisher ?? "", placeholder: "Leave out if it's the same as the author" },
    { only: ["notes"], name: "publisher", label: "Institution", value: source?.publisher ?? "", placeholder: "University of Bergen" },
    { name: "link", label: "DOI or link (optional)", value: source?.link ?? "", placeholder: "10.1007/978-0-387-45528-0 or https://…" },
    { name: "topic_id", label: "Belongs to topic", type: "select", value: source?.topic_id ?? "",
      options: [["", "— No topic —"], ...topics.map((t) => [t.id, t.title])],
      hint: "Everything in it counts toward this topic. A chapter or section can be linked to a different one." },
  ];
  if (!source) fields.push({ name: "contents", label: "Table of contents (optional)", type: "textarea", rows: 6,
    placeholder: "6 Kernel Methods\n6.1 Dual representations ..... 293\n6.2 Constructing kernels ..... 294",
    hint: "Paste the contents page. Lines starting with a number become chapters and sections; page numbers are ignored." });
  const form = openForm({
    title: source ? "Edit literature" : "Add literature", wide: true, fields,
    submit: source ? "Save" : "Add",
    onSubmit: async (v) => {
      const r = await call("save_source", v);
      if (!source) { state.openSources.add(r.id); saveOpenSources(); }
      return r;
    },
  });
  form.querySelector(".form-error").insertAdjacentHTML("beforebegin",
    `<div class="apa-preview"><span>Reference (APA 7)</span><div class="apa-text"></div></div>`);
  // The same field name appears once per kind (publisher); only the visible one is sent.
  const update = () => {
    const k = form.querySelector("input[name=kind]:checked").value;
    form.querySelectorAll("[data-only]").forEach((el) => {
      const on = el.dataset.only.split(" ").includes(k);
      el.hidden = !on;
      el.querySelectorAll("input, select, textarea").forEach((i) => { i.disabled = !on; });
    });
  };
  let timer = null;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const r = await call("apa_preview", formValues(form));
        form.querySelector(".apa-text").innerHTML = r.html;
      } catch (e) { form.querySelector(".apa-text").textContent = ""; }
    }, 150);
  };
  form.addEventListener("change", (e) => { if (e.target.name === "kind") update(); preview(); });
  form.addEventListener("input", preview);
  update();
  preview();
}

function chapterForm(sourceId, topics) {
  openForm({
    title: "Add a chapter",
    fields: [
      { name: "source_id", type: "hidden", value: sourceId },
      { row: [
        { name: "number", label: "Chapter number", placeholder: "6" },
        { name: "title", label: "Title (optional)", placeholder: "Kernel Methods" },
      ] },
      { name: "sections", label: "Sections", placeholder: "1-5, 7", hint: "Which sections to read. In chapter 6, “1-5, 7” means 6.1 to 6.5 and 6.7. Leave empty for none." },
      { name: "topic_id", label: "Counts toward topic (optional)", type: "select", value: "", options: [["", "— None —"], ...topics.map((t) => [t.id, t.title])] },
      { name: "optional", label: "These sections are optional reading", type: "checkbox", value: false },
    ],
    submit: "Add chapter",
    onSubmit: async (v) => {
      const r = await call("add_chapter", v);
      return { message: r.added ? `Added ${plural(r.added, "section")}.` : "" };
    },
  });
}

function chapterEditForm(ch, topics) {
  openForm({
    title: `Edit chapter ${ch.number}`,
    fields: [
      { name: "id", type: "hidden", value: ch.id },
      { row: [
        { name: "number", label: "Number", value: ch.number },
        { name: "title", label: "Title", value: ch.title },
      ] },
      { name: "topic_id", label: "Counts toward topic", type: "select", value: ch.topic_id ?? "", options: [["", "— None —"], ...topics.map((t) => [t.id, t.title])],
        hint: "Reading a section counts as studying that topic." },
    ],
    onSubmit: (v) => call("save_chapter", v),
  });
}

function pasteForm(sourceId) {
  openForm({
    title: "Paste table of contents", wide: true,
    intro: "Lines starting with a number become chapters and sections. Page numbers and dots are ignored. Sections you already have are kept.",
    fields: [{ name: "text", label: "Contents", type: "textarea", rows: 12, placeholder: "7 Sparse Kernel Machines\n7.1 Maximum Margin Classifiers ..... 325\n7.2 Relevance Vector Machines ..... 345" }],
    submit: "Add",
    onSubmit: (v) => call("import_contents", sourceId, v.text),
  });
}

// ---------- finding things in the current data ----------

function findIn(list, id) { return (list || []).find((x) => String(x.id) === String(id)); }
function currentDeadline(id) { return findIn(state.data.deadlines, id); }
function currentWeak(id) { return findIn(state.data.weak_spots, id); }
function currentChapter(id) {
  for (const s of state.data.sources) { const ch = findIn(s.chapters, id); if (ch) return ch; }
  return null;
}

// ---------- clicks ----------

const actions = {
  "open-subject": (el) => go({ name: "subject", id: Number(el.dataset.id) }),
  "open-reading": (el) => go({ name: "reading", id: Number(el.dataset.id) }),
  "add-course": () => courseForm(),
  "start-studying": (el) => startForm(el.dataset.course ? Number(el.dataset.course) : null, el.dataset.topic ? Number(el.dataset.topic) : null,
    el.dataset.project ? Number(el.dataset.project) : null),
  "log-time": (el) => {
    const inProject = state.view.name === "research";
    sessionForm(el.dataset.course ? Number(el.dataset.course) : (!inProject && state.view.name !== "overview" ? state.view.id : null), null,
      el.dataset.project ? Number(el.dataset.project) : (inProject ? state.view.id : null));
  },
  "drag": () => {},  // the handle's own click does nothing; dragging is handled in `sortable`
  settings: () => settingsForm(),
  "toggle-sidebar": () => setSidebarCollapsed(!document.body.classList.contains("side-collapsed")),
  "sign-in": () => signInForm(),
  "sign-up": () => signUpForm(),
  "account-menu": (el) => {
    const a = state.account;
    const items = [{ label: "Accounts on this computer", disabled: true }];
    for (const acc of a.accounts) {
      items.push({ label: acc.email, html: `${avatar(acc.email)}<span class="menu-grow">${esc(acc.email)}</span>${acc.active ? ICONS.check : ""}`,
        onClick: () => (acc.active ? null : switchAccount(acc.user_id)) });
    }
    items.push({ label: "This computer only", html: `<span class="avatar local">·</span><span class="menu-grow">This computer only</span>${a.signed_in ? "" : ICONS.check}`,
      onClick: () => (a.signed_in ? switchAccount(null) : null) });
    items.push({ label: "Add another account…", onClick: () => signInForm() });
    if (a.signed_in) {
      items.push("-",
        { label: "Sync now", onClick: () => syncNow({ quiet: false }) },
        { label: "Change password", onClick: () => passwordForm() },
        { label: `Sign out of ${a.email}`, onClick: () => signOut() },
        "-",
        { label: "Delete this account…", danger: true, onClick: async () => {
          if (await confirmBox("Delete your account?", `${a.email} and everything saved in it are deleted, online and on this computer. This can't be undone.`, "Delete account")) {
            const r = await act("delete_account");
            if (r) await afterAccountChange(r).then(refresh);
          }
        } });
    }
    openMenu(el, items);
  },
  export: async () => { try { const r = await call("export_markdown"); if (r.message) toast(r.message); } catch (e) { toast(e.message, true); } },

  "course-menu": (el) => {
    const c = state.data.course;
    openMenu(el, [
      { label: "Edit subject", onClick: () => courseForm(c) },
      { label: c.done ? "Move back to active subjects" : "Mark as finished", onClick: async () => {
        await act("set_course_done", c.id, !c.done);
        if (!c.done) toast(`${c.code} moved to Finished subjects. Nothing was deleted.`);
      } },
      "-",
      { label: "Delete subject…", danger: true, onClick: async () => {
        if (await confirmBox(`Delete ${c.code}?`, "This deletes the subject with all its topics, weak spots, deadlines, study time and reading list. It can't be undone. If you're just done with it, use “Mark as finished” instead.")) {
          state.view = { name: "overview" };
          await act("delete_course", c.id);
        }
      } },
    ]);
  },

  "add-topic": (el) => topicForm(Number(el.dataset.course)),
  "add-topics": (el) => topicsForm(Number(el.dataset.course)),
  "edit-topic": (el) => topicForm(state.view.id, findIn(state.data.topics, el.dataset.id)),
  "delete-topic": async (el) => {
    const t = findIn(state.data.topics, el.dataset.id);
    if (await confirmBox("Delete topic?", `“${t.title}” will be removed. Study time logged on it is kept.`)) act("delete_topic", t.id);
  },
  confidence: (el) => act("set_confidence", Number(el.dataset.id), Number(el.dataset.value)),

  "add-weak": (el) => weakForm(el.dataset.course ? Number(el.dataset.course) : null),
  "edit-weak": (el) => weakForm(null, currentWeak(el.dataset.id)),
  "toggle-weak": (el) => act("toggle_weak", Number(el.dataset.id)),
  "delete-weak": async (el) => { if (await confirmBox("Delete weak spot?", currentWeak(el.dataset.id).description)) act("delete_weak", Number(el.dataset.id)); },

  "add-deadline": (el) => deadlineForm(el.dataset.course ? Number(el.dataset.course) : null),
  "edit-deadline": (el) => deadlineForm(null, currentDeadline(el.dataset.id)),
  "toggle-deadline": (el) => act("toggle_deadline", Number(el.dataset.id)),
  "delete-deadline": async (el) => { if (await confirmBox("Delete deadline?", currentDeadline(el.dataset.id).title)) act("delete_deadline", Number(el.dataset.id)); },

  "edit-session": (el) => sessionForm(null, findIn(state.data.sessions, el.dataset.id)),
  "delete-session": async (el) => {
    const s = findIn(state.data.sessions, el.dataset.id);
    if (await confirmBox("Delete study time?", `${s.length} on ${s.started_label} will be removed.`)) act("delete_session", s.id);
  },

  "timer-stop": () => act("timer_stop"),
  "timer-cancel": async () => { if (await confirmBox("Discard this session?", "The time on the clock won't be saved.", "Discard")) act("timer_cancel"); },
  "pomo-pause": () => act("pomo_pause"),
  "pomo-next": () => act("pomo_next"),
  "pomo-break": () => act("pomo_break"),
  "pomo-stop": () => act("pomo_stop"),

  "add-source": (el) => sourceForm(Number(el.dataset.course), null, state.data.topics),
  "copy-apa": (el) => copyReferences([findIn(state.data.sources, el.dataset.id)]),
  "copy-apa-list": (el) => copyReferences(el.dataset.ids.split(",").map((id) => findIn(state.data.sources, id))),
  "source-menu": (el) => {
    const s = findIn(state.data.sources, el.dataset.id);
    openMenu(el, [
      { label: "Edit details, reference or topic", onClick: () => sourceForm(state.view.id, s, state.data.topics) },
      { label: "Paste table of contents", onClick: () => pasteForm(s.id) },
      "-",
      { label: "Delete…", danger: true, onClick: async () => {
        if (await confirmBox(`Delete “${s.title}”?`, "Its chapters and sections are removed from the reading list.")) act("delete_source", s.id);
      } },
    ]);
  },
  "add-chapter": (el) => {
    state.openSources.add(Number(el.dataset.id));
    saveOpenSources();
    chapterForm(Number(el.dataset.id), state.data.topics);
  },
  "edit-chapter": (el) => chapterEditForm(currentChapter(el.dataset.id), state.data.topics),
  "delete-chapter": async (el) => {
    const ch = currentChapter(el.dataset.id);
    if (await confirmBox(`Delete chapter ${ch.number}?`, "Its sections are removed too.")) act("delete_chapter", ch.id);
  },
  "chapter-read": (el) => act("set_chapter_read", Number(el.dataset.id), el.checked),
  "fold-source": (el) => {
    const id = Number(el.dataset.id);
    state.openSources.has(id) ? state.openSources.delete(id) : state.openSources.add(id);
    saveOpenSources();
    $("#view").innerHTML = renderReading(state.data);
  },
  fold: (el) => {
    const id = Number(el.dataset.id);
    state.collapsed.has(id) ? state.collapsed.delete(id) : state.collapsed.add(id);
    $("#view").innerHTML = renderReading(state.data);
  },
  "toggle-section": (el) => act("toggle_section", Number(el.dataset.id)),
  "section-menu": (el) => {
    const id = Number(el.dataset.id), required = el.dataset.required === "1";
    openMenu(el, [
      { label: required ? "Make optional" : "Make needed", onClick: () => act("set_section_required", id, !required) },
      "-",
      { label: "Delete section", danger: true, onClick: () => act("delete_section", id) },
    ]);
  },
};

document.addEventListener("click", (e) => {
  const goEl = e.target.closest("[data-go]");
  if (goEl) { go({ name: goEl.dataset.go }); return; }
  const el = e.target.closest("[data-act]");
  if (!el || !actions[el.dataset.act]) return;
  // A button inside a clickable card or section does its own thing, not the card's.
  e.stopPropagation();
  if (el.tagName !== "INPUT") e.preventDefault();
  actions[el.dataset.act](el, e);
});

// A link in a note, question or reference opens in the computer's browser: following it inside this window
// would replace the app with the web page.
document.addEventListener("click", (e) => {
  const link = e.target.closest("a[href]");
  if (!link || e.defaultPrevented) return;
  e.preventDefault();
  call("open_link", link.getAttribute("href")).catch((err) => toast(err.message, true));
}, true);

// ---------- dragging to reorder ----------

// Drag a card or row by its handle to a new place in its list. `[data-sortable]` names the list; each item
// has data-id (and data-kind in the overview, where courses and projects mix). Pointer events rather than
// HTML drag and drop, which behaves differently in each system's web view.
const SORTED = {
  // The active and finished lists share one order, so moving something back keeps its place.
  overview: () => call("reorder", [...document.querySelectorAll("[data-sortable=overview] > [data-id]")]
    .map((el) => ({ kind: el.dataset.kind, id: Number(el.dataset.id) }))),
};

document.addEventListener("pointerdown", (e) => {
  const handle = e.target.closest(".drag-handle");
  if (!handle || e.button !== 0) return;
  const list = handle.closest("[data-sortable]");
  const item = handle.closest("[data-id]");
  if (!list || !item || item.parentElement !== list) return;
  e.preventDefault();
  const siblings = () => [...list.children].filter((x) => x.dataset.id);
  const before = siblings().map((x) => x.dataset.id).join(",");
  item.classList.add("dragging");
  list.classList.add("sorting");
  // Listen on the window, not the handle: moving the item in the page would drop a pointer capture.
  const move = (ev) => {
    const over = siblings().find((x) => {
      if (x === item) return false;
      const r = x.getBoundingClientRect();
      return ev.clientY >= r.top && ev.clientY <= r.bottom && ev.clientX >= r.left && ev.clientX <= r.right;
    });
    if (!over) return;
    const r = over.getBoundingClientRect();
    const sideways = list.dataset.axis === "x";
    const after = sideways ? ev.clientX > r.left + r.width / 2 : ev.clientY > r.top + r.height / 2;
    list.insertBefore(item, after ? over.nextSibling : over);
  };
  const end = async () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    item.classList.remove("dragging");
    list.classList.remove("sorting");
    const items = siblings();
    if (items.map((x) => x.dataset.id).join(",") === before) return;
    try {
      await SORTED[list.dataset.sortable](items, list);
      scheduleSync();
    } catch (err) {
      toast(err.message, true);
    }
    refresh();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
});

document.addEventListener("keydown", (e) => {
  // Keyboard reordering: Alt + up/down on a focused handle.
  const handle = e.target.closest?.(".drag-handle");
  if (!handle || !e.altKey || !["ArrowUp", "ArrowDown"].includes(e.key)) return;
  const list = handle.closest("[data-sortable]"), item = handle.closest("[data-id]");
  if (!list || !item) return;
  e.preventDefault();
  const other = e.key === "ArrowUp" ? item.previousElementSibling : item.nextElementSibling;
  if (!other || !other.dataset.id) return;
  list.insertBefore(item, e.key === "ArrowUp" ? other : other.nextSibling);
  SORTED[list.dataset.sortable]([...list.children].filter((x) => x.dataset.id), list)
    .then(() => { scheduleSync(); return refresh(); })
    .then(() => document.querySelector(`[data-sortable="${list.dataset.sortable}"] [data-id="${item.dataset.id}"] .drag-handle`)?.focus())
    .catch((err) => toast(err.message, true));
});

document.addEventListener("change", (e) => {
  const el = e.target;
  if (el.dataset.change === "topic-status") act("set_topic_status", Number(el.dataset.id), el.value);
  if (el.dataset.change === "reading-view") {
    state.readingView = el.value;
    try { localStorage.setItem("studypal.readingView", el.value); } catch (e) { /* only a convenience */ }
    $("#view").innerHTML = renderReading(state.data);
  }
});

document.addEventListener("toggle", (e) => {
  if (e.target.matches?.("details.done-pane")) state.showDone = e.target.open;
}, true);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (document.querySelector(".menu")) closeMenu();
    else if (modalClose) modalClose();
    else if (state.view.name === "reading" || state.view.name === "exams") go({ name: "subject", id: state.view.id });
    else if (state.view.name === "subject" || state.view.name === "research") go({ name: "overview" });
    else if (state.view.name === "exam") go({ name: "exams", id: state.data.course.id });
    else if (state.view.name === "attempt") go({ name: "exam", id: state.data.exam.id });
    // Taking an exam: Escape does nothing, so it can't be left by accident.
  }
  if (e.key === "Enter" && e.target.matches?.(".card, .exam-card")) actions[e.target.dataset.act](e.target);
});

// ---------- themes ----------

// Apply a theme and redraw (subject colours follow it). With save, it's remembered for this computer.
async function setTheme(name, save) {
  applyTheme(name);
  try { localStorage.setItem("studypal.theme", name); } catch (e) { /* the saved one still loads */ }
  if (save) {
    try { await call("set_theme", name, resolvedTheme().bg); } catch (e) { toast(e.message, true); }
  }
  if (state.data) renderView();
  renderAccount();
  renderSidebar();
}

// Before anything is drawn: the last theme used here, so the window doesn't flash in the wrong colours.
try { applyTheme(localStorage.getItem("studypal.theme") || "system"); } catch (e) { /* default */ }

// ---------- start ----------

function start() {
  try { setSidebarCollapsed(localStorage.getItem("studypal.sidebar") === "collapsed"); } catch (e) { /* open */ }
  // #subject/3 or #reading/3 opens straight onto that page (handy when working on the interface).
  const m = location.hash.match(/^#(subject|reading|exams|research|exam|take|attempt)\/(\d+)$/);
  if (m) state.view = { name: m[1], id: Number(m[2]) };
  call("get_theme").then((name) => {
    if (name !== activeTheme.name) setTheme(name, false);
    // Daylight's colour changes, so remember the current one for the window's next opening.
    if (name === "daylight") call("set_theme", name, resolvedTheme().bg).catch(() => {});
  }).catch(() => {});
  loadAccount().then(refresh).then(tick).then(() => syncNow());
  setInterval(updateClock, 1000);
  setInterval(tick, 30000);
  setInterval(() => syncNow(), 60000);  // picks up changes made on other computers
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener("pywebviewready", start);
