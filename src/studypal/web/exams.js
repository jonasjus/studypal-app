"use strict";

// The exams page: past exams (with their files and how each question went) and practice exams that
// the model writes from them. Loaded after app.js; uses its helpers, and adds to its `actions`.

// ---------- drawing ----------

const ROLE_LABELS = { exam: "Exam", solution: "Solutions", attempt: "My answers" };
const RESULT_LABELS = { ok: "Got it", partial: "Partly", missed: "Missed" };
const ICON_SPARK = '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z"/></svg>';
const ICON_FILE = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>';

state.openAnswers = new Set();

// The exams on the page being shown: the list's, or the one exam's.
function allExams() {
  const d = state.data || {};
  return d.exam && d.exam.questions ? [d.exam] : [...(d.past || []), ...(d.practice || [])];
}
const findExam = (id) => allExams().find((e) => e.id === Number(id));

function resultCounts(c) {
  if (!c.total) return "";
  const parts = [];
  if (c.missed) parts.push(`<span class="rc missed">${c.missed} missed</span>`);
  if (c.partial) parts.push(`<span class="rc partial">${c.partial} partly</span>`);
  if (c.ok) parts.push(`<span class="rc ok">${c.ok} got it</span>`);
  if (c.unmarked) parts.push(`<span class="faint">${c.unmarked} not marked</span>`);
  return parts.join(" ");
}

function questionBlock(q, exam) {
  const open = state.openAnswers.has(q.id);
  const seg = ["ok", "partial", "missed"].map((r) => `<button class="res ${r}${q.result === r ? " on" : ""}" data-act="q-result"
      data-id="${q.id}" data-result="${q.result === r ? "" : r}" aria-pressed="${q.result === r}"
      title="${q.result === r ? "Click again to clear" : `Mark as ${RESULT_LABELS[r].toLowerCase()}`}">${RESULT_LABELS[r]}</button>`).join("");
  const answerLabel = exam.kind === "practice" ? "Solution" : exam.has_solution ? "Answer (from the solutions)" : "Answer";
  // A read exam never guesses an answer: say so instead.
  const noAnswer = exam.kind === "past" && !q.answer
    ? `<p class="faint q-noanswer">No solution${exam.has_solution ? ": the solutions don't answer this one" : " yet: add the solutions and read the exam again"}.</p>` : "";
  const points = q.marks ? `${esc(q.marks)} ${/^\d+(\.\d+)?$/.test(q.marks) ? (q.marks === "1" ? "point" : "points") : ""}` : "";
  return `<div class="q${q.result ? ` r-${q.result}` : ""}">
    <div class="q-head">
      <span class="q-num">${esc(q.number || "·")}</span>
      ${q.topic ? `<span class="tag topic-tag">${esc(q.topic)}</span>` : ""}
      ${(q.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}
      ${q.type_label ? `<span class="q-type">${esc(q.type_label)}</span>` : ""}
      ${q.has_figure ? `<span class="q-type" title="The question relies on a figure in the exam paper">${ICON_FILE} figure</span>` : ""}
      ${points ? `<span class="faint">${points}</span>` : ""}
      <span class="q-res" role="group" aria-label="How did it go?">${seg}</span>
      <button class="icon-btn small" data-act="q-menu" data-id="${q.id}" aria-label="Question options">${ICONS.more}</button>
    </div>
    ${q.why ? `<div class="q-why">${ICON_SPARK} ${esc(q.why)}</div>` : ""}
    <div class="md q-prompt">${md(q.prompt) || '<p class="faint">No question text.</p>'}</div>
    ${q.note ? `<div class="q-note"><b>What went wrong:</b> ${esc(q.note)}</div>` : ""}
    ${q.answer ? `<details class="q-answer" data-id="${q.id}"${open ? " open" : ""}><summary>${answerLabel}</summary>
      <div class="md">${md(q.answer)}</div></details>` : noAnswer}
  </div>`;
}

function readButton(e) {
  const canRead = e.kind === "past" && e.files.some((f) => f.role === "exam");
  return state.jobs[`read:${e.id}`] ? jobLine(`read:${e.id}`)
    : canRead ? `<button class="btn small${e.counts.total ? " ghost" : ""}" data-act="read-exam" data-id="${e.id}"
      title="Reads the files and lists the questions, with the answers from the solutions">${ICON_SPARK} ${e.counts.total ? "Read again" : "Read questions"}</button>` : "";
}

function examMeta(e) {
  return [e.kind === "practice" ? `Made ${e.created_label}` : e.taken_on, e.score ? `Score: ${e.score}` : "",
    e.counts.total ? plural(e.counts.total, "question") : ""].filter(Boolean).join(" · ");
}

function attemptWords(t) {
  if (!t.count) return "";
  const best = t.best !== null ? ` · best ${t.best}%` : "";
  return `Taken ${t.count === 1 ? "once" : `${t.count} times`}${t.latest !== null ? ` · last ${t.latest}%` : ""}${t.count > 1 ? best : ""}`;
}

// The list's card for one exam: click it to open the exam's own page.
function examCard(e) {
  const t = e.attempts;
  return `<div class="panel exam exam-card" id="exam-${e.id}" tabindex="0" data-act="open-exam" data-id="${e.id}">
    <div class="source-head">
      <div class="grow"><h3>${esc(e.title)}</h3>
        <div class="muted">${esc(examMeta(e)) || (e.kind === "past" ? "No questions listed yet" : "")}</div>
        ${t.count ? `<div class="attempt-words">${esc(attemptWords(t))}</div>` : ""}</div>
      <span class="counts">${resultCounts(e.counts)}</span>
      ${t.open ? `<button class="btn small primary" data-act="open-take" data-id="${t.open}">Continue exam</button>` : e.counts.total ? "" : readButton(e)}
      <button class="icon-btn small" data-act="exam-menu" data-id="${e.id}" aria-label="More">${ICONS.more}</button>
      <span class="exam-go" aria-hidden="true">${ICONS.chev}</span>
    </div>
  </div>`;
}

function examQuestions(e, d) {
  const canRead = e.kind === "past" && e.files.some((f) => f.role === "exam");
  return e.questions.length ? e.questions.map((q) => questionBlock(q, e)).join("")
    : `<p class="empty-small">${state.jobs[`read:${e.id}`] ? "Reading the questions. They'll show up here when it's done."
      : canRead
      ? (d.ai ? "Click <b>Read questions</b> to have them listed, with the answers from the solutions. Then take the exam, or mark how each one went." : "Set up a model to have the questions listed for you, or add them by hand.")
      : "Add the exam paper (a PDF or photos) so the questions can be read from it, or add them by hand."}
      <button class="btn small ghost" data-act="add-question" data-id="${e.id}">+ Add a question by hand</button></p>`;
}

function fileChips(files) {
  return files.map((f) => `<button class="file-chip${f.available ? "" : " missing"}" data-act="open-exam-file" data-id="${f.id}"
      title="${f.available ? "Open" : "Not downloaded to this computer yet"}">${ICON_FILE}<span>${esc(f.name)}</span>${f.role ? `<small>${esc(ROLE_LABELS[f.role] || f.role)}</small>` : ""}</button>`).join("");
}

function scoreClass(p) {
  return p === null || p === undefined ? "" : p >= 70 ? "good" : p >= 40 ? "mid" : "low";
}

function attemptsPanel(d) {
  const e = d.exam;
  const rows = d.attempt_list.map((a) => {
    const p = a.score.percent;
    const right = !a.finished ? `<span class="tag">Being taken</span>`
      : state.jobs[`grade:${a.id}`] ? '<span class="spinner small"></span>'
      : p !== null ? `<span class="attempt-score ${scoreClass(p)}">${p}%</span>` : '<span class="faint">Not graded</span>';
    return `<li class="attempt-row" data-act="${a.finished ? "open-attempt" : "open-take"}" data-id="${a.id}" tabindex="0">
      <div class="grow"><div>${esc(a.started_label)}</div>
        <div class="muted small-text">${a.finished ? `${esc(a.time_label)}${a.minutes ? ` of ${a.minutes} min` : ""} · ${a.answered}/${a.questions} answered`
          : a.minutes ? `${a.minutes}-minute limit` : "No time limit"}</div></div>
      ${right}
      <button class="icon-btn small" data-act="attempt-row-menu" data-id="${a.id}" data-finished="${a.finished ? 1 : ""}" aria-label="Attempt options">${ICONS.more}</button></li>`;
  }).join("");
  return `<div class="panel">
    <div class="section-head"><h2>Attempts</h2></div>
    ${rows ? `<ul class="list attempts">${rows}</ul>` : `<p class="empty-small">${e.questions.length
      ? "Take the exam against the clock, then have your answers graded. Each attempt is kept here."
      : "Once the exam has questions, you can take it here against the clock."}</p>`}
  </div>`;
}

// One exam's own page: its files and questions, and the times it's been taken.
function renderExam(d) {
  const c = d.course, e = d.exam, open = e.attempts.open;
  const intro = e.kind === "practice" && e.notes ? `<div class="md exam-intro">${md(e.notes)}</div>` : "";
  const notes = e.kind === "past" && e.notes ? `<p class="muted exam-notes">${esc(e.notes)}</p>` : "";
  const chips = fileChips(e.files);
  const take = open ? `<button class="btn primary" data-act="open-take" data-id="${open}">${ICONS.play} Continue exam</button>`
    : `<button class="btn primary" data-act="take-exam" data-id="${e.id}"${e.questions.length ? "" : " disabled title=\"The exam has no questions yet\""}>${ICONS.play} Take exam</button>`;
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-act="open-exams" data-id="${c.id}">${ICONS.back} ${esc(c.code)} exams</button></div>
    <div class="title-line"><h1>${esc(e.title)}</h1>
      <span class="tag">${e.kind === "practice" ? "Practice exam" : "Past exam"}</span>
      <div class="title-actions">
        ${readButton(e)}
        ${e.kind === "practice" ? `<button class="btn" data-act="print-exam" data-id="${e.id}" title="Save as a page to print">Print…</button>` : ""}
        ${take}
        <button class="icon-btn" data-act="exam-menu" data-id="${e.id}" aria-label="More">${ICONS.more}</button>
      </div>
    </div>
    ${examMeta(e) ? `<p class="muted exam-meta">${esc(examMeta(e))} ${resultCounts(e.counts) ? `· ${resultCounts(e.counts)}` : ""}</p>` : ""}
  </div>
  <div class="grid" style="--course:${esc(cc(c.color))}">
    <div class="stack">
      <div class="panel exam exam-page">
        ${chips ? `<div class="file-chips">${chips}</div>` : ""}${notes}${intro}
        <div class="qs">${examQuestions(e, d)}</div>
      </div>
    </div>
    <aside class="stack">${attemptsPanel(d)}</aside>
  </div>`;
}

function practicePanel(d) {
  const rows = d.tally.filter((t) => t.missed || t.partial).slice(0, 8);
  const max = Math.max(1, ...rows.map((t) => t.missed * 2 + t.partial));
  const list = rows.map((t) => `<li class="tally">
      <div class="tally-top"><span class="grow">${t.title ? esc(t.title) : '<span class="muted">No topic</span>'}</span>
        <span class="muted">${[t.missed ? `${t.missed} missed` : "", t.partial ? `${t.partial} partly` : ""].filter(Boolean).join(" · ")}</span></div>
      <div class="tally-bar"><div class="m" style="width:${pct((t.missed * 2) / max)}"></div><div class="p" style="width:${pct(t.partial / max)}"></div></div>
    </li>`).join("");
  const extra = [d.weak_open ? `${plural(d.weak_open, "open weak spot")}` : "",
    d.shaky_topics.length ? `low confidence in ${d.shaky_topics.slice(0, 4).map(esc).join(", ")}${d.shaky_topics.length > 4 ? "…" : ""}` : ""].filter(Boolean);
  return `<div class="panel">
    <div class="section-head"><h2>What to practise</h2></div>
    ${list ? `<ul class="list tallies">${list}</ul>` : '<p class="empty-small">Mark questions as <b>Missed</b> or <b>Partly</b> and the topics that went badly show up here.</p>'}
    ${extra.length ? `<p class="empty-small" style="padding-top:0">Also: ${extra.join("; ")}.</p>` : ""}
    <p class="empty-small" style="padding-top:0">Practice exams aim at these first.</p>
  </div>`;
}

function renderExams(d) {
  const c = d.course;
  const setup = d.ai ? "" : `<div class="panel panel-body ai-setup">
      <div class="grow"><b>Set up a model to read exams and write practice exams</b>
      <p class="muted">Gemini or Groq need an API key, which is free and takes a minute to get. Ollama runs on this computer and needs none.</p></div>
      <button class="btn primary" data-act="ai-setup">Set up</button></div>`;
  const past = d.past.length ? d.past.map(examCard).join("")
    : `<div class="panel panel-body"><p class="muted" style="margin:0">Add the past exams for ${esc(c.code)}: the exam paper, and the solutions and your own (graded) answers if you have them. StudyPal lists the questions, and you mark which ones went badly.</p></div>`;
  const writing = state.jobs[`make:${c.id}`]
    ? `<div class="panel panel-body job-card">${jobLine(`make:${c.id}`)}<span class="muted">You can keep using StudyPal meanwhile.</span></div>` : "";
  const practice = writing + (d.practice.length || writing ? d.practice.map(examCard).join("")
    : `<div class="panel panel-body"><p class="muted" style="margin:0">${d.past.length
      ? "Make a practice exam: new questions in the style of your past exams, aimed at what you struggled with."
      : "Practice exams are written in the style of your past exams. Add some first, or make one from your topics alone."}</p></div>`);
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-act="open-subject" data-id="${c.id}">${ICONS.back} ${esc(c.code)} ${esc(c.name)}</button></div>
    <div class="title-line"><h1>Exams</h1>
      <div class="title-actions">
        <button class="btn" data-act="add-exam" data-course="${c.id}">+ Add past exam</button>
        <button class="btn primary" data-act="make-exam" data-course="${c.id}"${state.jobs[`make:${c.id}`] ? " disabled" : ""}>${ICON_SPARK} ${state.jobs[`make:${c.id}`] ? "Writing…" : "Make practice exam"}</button>
      </div>
    </div>
  </div>
  <div class="grid" style="--course:${esc(cc(c.color))}">
    <div class="stack">
      ${setup}
      <div class="section-head"><h2>Past exams</h2></div>
      ${past}
      <div class="section-head" style="margin-top:12px"><h2>Practice exams</h2></div>
      ${practice}
    </div>
    <aside class="stack">${practicePanel(d)}</aside>
  </div>`;
}

// ---------- forms ----------

// Guess what a file is from its name: solutions, your own answers, or else the exam itself.
function guessRole(name) {
  const n = name.toLowerCase();
  if (/(solution|løsning|losning|losn|fasit|answer[ _-]?key|sensor|mark[ _-]?scheme|\blf\b|_lf|-lf)/.test(n)) return "solution";
  if (/(my[ _-]?answer|mine|besvarelse|graded|attempt|retting|kandidat)/.test(n)) return "attempt";
  return "exam";
}

// Files picked in a plain browser (the dev server) are read here and sent as base64.
function pickInBrowser() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ".pdf,.png,.jpg,.jpeg,.webp,.heic,.heif,.txt,.md";
    input.addEventListener("change", async () => {
      const out = [];
      for (const f of input.files) {
        const data = await new Promise((ok) => {
          const r = new FileReader();
          r.onload = () => ok(String(r.result).split(",")[1] || "");
          r.readAsDataURL(f);
        });
        out.push({ name: f.name, data, size: f.size > 1048576 ? `${(f.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB` });
      }
      resolve(out);
    });
    input.click();
  });
}

function examForm(courseId, exam = null) {
  const pending = [];  // files to add: {name, size, role, path | data}
  const removed = new Set();
  const form = openForm({
    title: exam ? "Edit past exam" : "Add a past exam", wide: true, submit: exam ? "Save" : "Add",
    fields: [
      { name: "title", label: "Name", value: exam?.title ?? "", placeholder: "e.g. Exam spring 2024" },
      { row: [
        { name: "taken_on", label: "When (optional)", value: exam?.taken_on ?? "", placeholder: "June 2024" },
        { name: "score", label: "Your score (optional)", value: exam?.score ?? "", placeholder: "e.g. 62/100 or C" },
      ] },
      { name: "notes", label: "Notes (optional)", type: "textarea", rows: 2, value: exam?.notes ?? "", placeholder: "e.g. Ran out of time on the last question" },
    ],
    onSubmit: async (v) => {
      const add = pending.map((f) => (f.path ? { role: f.role, path: f.path } : { role: f.role, name: f.name, data: f.data }));
      const r = await call("save_exam", { ...v, id: exam?.id ?? "", course_id: courseId, add, remove: [...removed] });
      // A new exam opens on its own page, ready to have its questions read.
      if (!exam) { state.view = { name: "exam", id: r.id }; $("#view").scrollTop = 0; }
      return r;
    },
  });
  form.querySelector(".form-error").insertAdjacentHTML("beforebegin", `<div class="field"><span>Files</span>
      <div class="file-rows"></div>
      <div><button type="button" class="btn small" data-files="add">+ Add files…</button></div>
      <small>PDFs or photos. Add the exam itself, and if you have them the solutions and your own answers (graded if possible): with your answers, StudyPal can tell which questions went badly.</small></div>`);
  const rows = form.querySelector(".file-rows");
  const draw = () => {
    const existing = (exam?.files || []).filter((f) => !removed.has(f.id));
    const roleSelect = (i, role) => `<select class="input small" data-files="role" data-i="${i}">${Object.entries(ROLE_LABELS).map(([k, l]) =>
      `<option value="${k}"${k === role ? " selected" : ""}>${l}</option>`).join("")}</select>`;
    rows.innerHTML = existing.map((f) => `<div class="file-row">${ICON_FILE}<span class="grow">${esc(f.name)}</span>
        <span class="faint">${esc(ROLE_LABELS[f.role])} · ${esc(f.size)}</span>
        <button type="button" class="icon-btn small" data-files="remove-old" data-id="${f.id}" aria-label="Remove">${ICONS.trash}</button></div>`).join("")
      + pending.map((f, i) => `<div class="file-row new">${ICON_FILE}<span class="grow">${esc(f.name)}</span>
        <span class="faint">${esc(f.size)}</span>${roleSelect(i, f.role)}
        <button type="button" class="icon-btn small" data-files="remove-new" data-i="${i}" aria-label="Remove">${ICONS.trash}</button></div>`).join("")
      || '<p class="faint" style="margin:0">No files yet.</p>';
  };
  form.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-files]");
    if (!b || b.tagName === "SELECT") return;
    if (b.dataset.files === "add") {
      let picked = [];
      try {
        const r = await call("choose_exam_files");
        picked = r.browser ? await pickInBrowser() : r.files;
      } catch (err) { form.querySelector(".form-error").textContent = err.message; return; }
      for (const f of picked) pending.push({ ...f, role: guessRole(f.name) });
      // The first file is usually the exam paper.
      if (pending.length && !pending.some((f) => f.role === "exam") && !(exam?.files || []).some((f) => f.role === "exam" && !removed.has(f.id))) pending[0].role = "exam";
      const title = form.querySelector("[name=title]");
      const paper = pending.find((f) => f.role === "exam") || pending[0];
      if (!title.value && paper) title.value = paper.name.replace(/\.[a-z0-9]+$/i, "").replace(/[_-]+/g, " ");
    }
    if (b.dataset.files === "remove-new") pending.splice(Number(b.dataset.i), 1);
    if (b.dataset.files === "remove-old") removed.add(Number(b.dataset.id));
    draw();
  });
  form.addEventListener("change", (e) => {
    if (e.target.dataset.files === "role") pending[Number(e.target.dataset.i)].role = e.target.value;
  });
  draw();
}

function questionForm(examId, q = null) {
  const exam = findExam(examId);
  openForm({
    title: q ? `Question ${q.number}` : "Add a question", wide: true, submit: q ? "Save" : "Add",
    fields: [
      { row: [
        { name: "number", label: "Number", value: q?.number ?? "", placeholder: "2b" },
        { name: "marks", label: "Marks (optional)", value: q?.marks ?? "" },
        { name: "topic_id", label: "Topic", type: "select", value: q?.topic_id ?? "",
          options: [["", "— No topic —"], ...state.data.topics.map((t) => [t.id, t.title])] },
      ] },
      { name: "result", label: "How did it go?", type: "seg", value: q?.result ?? "",
        options: [["", "Not marked"], ["ok", "Got it"], ["partial", "Partly"], ["missed", "Missed"]] },
      { name: "note", label: "What went wrong (optional)", type: "textarea", rows: 2, value: q?.note ?? "",
        placeholder: "e.g. Forgot the chain rule on the inner function", hint: "Practice exams use this to aim at the same mistake." },
      { name: "prompt", label: "Question", type: "textarea", rows: 5, value: q?.prompt ?? "", hint: "Maths can be written as $x^2$." },
      { name: "answer", label: exam?.kind === "practice" ? "Solution" : "Answer (optional)", type: "textarea", rows: 4, value: q?.answer ?? "" },
    ],
    onSubmit: (v) => call("save_question", { ...v, id: q?.id ?? "", exam_id: examId }),
  });
}

// The model fields, in the setup form and in Settings: which provider, and its key or (Ollama) model.
function aiFields(g) {
  const keyField = (name) => {
    const k = g.keys[name];
    return { only: [name], name: `key_${name}`, label: `${k.name} API key`, type: "password", value: "",
      placeholder: k.from_env ? `Taken from ${k.env}` : k.has_key ? `Saved (${k.key_hint || "hidden"}). Paste a new one to replace it` : "Paste your key here",
      hint: `Free from <a href="${esc(k.key_url)}" target="_blank" rel="noopener">${esc(k.key_url.replace(/^https:\/\//, ""))}</a>. Kept on this computer only${k.from_env ? ` (${esc(k.env)} is set, and wins)` : ""}.` };
  };
  const forget = (name) => (g.keys[name].has_key && !g.keys[name].from_env
    ? [{ only: [name], name: `forget_${name}`, label: `Remove the saved ${g.keys[name].name} key from this computer`, type: "checkbox", value: false }] : []);
  return [
    { name: "ai_provider", label: "Model provider", type: "select", value: g.provider, options: g.providers,
      hint: "Reads your exams (scanned pages and maths too) and writes practice exams." },
    ...Object.keys(g.keys).flatMap((name) => [keyField(name), ...forget(name)]),
    { only: ["ollama"], row: [
      { name: "ollama_model", label: "Ollama model", value: g.ollama_model, placeholder: "gemma3", hint: "One that reads images, e.g. gemma3 or qwen2.5vl" },
      { name: "ollama_url", label: "Address", value: g.ollama_url },
    ] },
  ];
}

// Show only the chosen provider's fields.
function linkProviderFields(form) {
  const update = () => {
    const which = form.querySelector("select[name=ai_provider]")?.value;
    form.querySelectorAll("[data-only]").forEach((el) => { if (el.querySelector("[name^=key_], [name^=forget_], [name^=ollama_]")) el.hidden = !el.dataset.only.split(" ").includes(which); });
  };
  form.addEventListener("change", (e) => { if (e.target.name === "ai_provider") update(); });
  update();
}

function aiValues(v, g) {
  return {
    provider: v.ai_provider,
    keys: Object.fromEntries(Object.keys(g.keys).map((name) => [name, v[`key_${name}`] || ""])),
    forget: Object.keys(g.keys).filter((name) => v[`forget_${name}`]),
    ollama_model: v.ollama_model, ollama_url: v.ollama_url,
  };
}

async function aiForm() {
  const g = await call("ai_settings");
  const form = openForm({
    title: "Set up a model", wide: true, submit: "Save",
    intro: "StudyPal uses a language model to read your past exams and write new ones. <b>Gemini</b> (Google) and <b>Groq</b> have free API keys: open the link under the key field, sign in, create a key and paste it here. <b>Ollama</b> runs a model on this computer instead: install it from ollama.com and download a model that reads images. Your exams are sent to the provider you pick (not with Ollama).",
    fields: aiFields(g),
    onSubmit: async (v) => {
      const k = g.keys[v.ai_provider];
      if (k && !k.has_key && !v[`key_${v.ai_provider}`]) throw new UserError("Paste your API key first.");
      return call("save_ai", aiValues(v, g));
    },
  });
  linkProviderFields(form);
}

function makeExamForm(courseId) {
  const d = state.data;
  if (!d.ai) { aiForm(); return; }
  const read = d.past.filter((e) => e.counts.total).length;
  const unread = d.past.length - read;
  const marked = d.tally.reduce((n, t) => n + t.missed + t.partial, 0);
  const uses = [read ? `the questions of ${plural(read, "past exam")}` : "",
    marked ? `${plural(marked, "question")} you missed or got partly right` : "",
    d.weak_open ? plural(d.weak_open, "open weak spot") : ""].filter(Boolean);
  const form = openForm({
    title: "Make a practice exam", wide: true, submit: "Make exam",
    intro: (uses.length ? `It's written from ${uses.join(", ")}, and your topics: a few past questions on each topic are shown to the model as examples.` : "There are no read past exams or marked questions yet, so it goes by your topics alone.")
      + (unread ? ` ${unread === 1 ? "One past exam hasn't" : `${unread} past exams haven't`} been read yet: press <b>Read questions</b> on ${unread === 1 ? "it" : "them"} first so they can be used ${unread === 1 ? "it" : "them"}.` : ""),
    fields: [
      { name: "size", label: "How long?", type: "choices", value: "short", options: [
        ["short", "Short", "4 to 6 questions, about 45 minutes"],
        ["half", "Half an exam", "About half as long as a real one"],
        ["full", "Full exam", "As long as the real exam"]] },
      { name: "focus", label: "What should it focus on?", type: "choices", value: marked || d.weak_open || d.shaky_topics.length ? "struggles" : "balanced", options: [
        ["struggles", "What I struggled with", "Most questions practise what went badly before; the rest covers the course"],
        ["balanced", "Like the real exam", "Covers the course the way the exam does, with a few questions on weak points"],
        ["topics", "Only some topics", "Pick the topics below"]] },
      { name: "topics_pick", label: "Topics", type: "html", html: d.topics.length
        ? `<div class="topic-picks">${d.topics.map((t) => `<label class="pick"><input type="checkbox" class="check" data-topic="${t.id}"><span>${esc(t.title)}</span></label>`).join("")}</div>`
        : '<p class="faint" style="margin:0">This subject has no topics yet.</p>' },
      { name: "wishes", label: "Anything else? (optional)", type: "textarea", rows: 2, placeholder: "e.g. more proofs, no multiple choice, write it in English" },
    ],
    onSubmit: async (v, f) => {
      if (v.focus === "topics" && !f.querySelector("[data-topic]:checked")) throw new UserError("Pick the topics the exam should be about.");
      const topic_ids = [...f.querySelectorAll("[data-topic]:checked")].map((x) => Number(x.dataset.topic));
      runJob(`make:${courseId}`, courseId, "a practice exam", async () => {
        const r = await call("make_exam", { ...v, course_id: courseId, topic_ids });
        toast(r.message);
        scheduleSync();
        if (state.view.name === "exams" && state.view.id === courseId) {
          setTimeout(() => document.getElementById(`exam-${r.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
        }
      });
    },
  });
  const picks = form.querySelector("[data-field=topics_pick]");
  const update = () => {
    const on = form.querySelector("input[name=focus]:checked")?.value === "topics";
    if (picks) picks.style.display = on ? "" : "none";
  };
  form.addEventListener("change", update);
  update();
}

// ---------- the model working in the background ----------

// Reading an exam or writing one takes a while (a request per few pages). It runs while you carry on: the
// exam shows a spinner with how far it's got, the top bar shows it's busy from any page, and a
// message says when it's done. Keys are "read:<exam id>", "make:<course id>" and "grade:<attempt id>", as in api.py.
state.jobs = {};  // key -> {course, title, text, started}
let jobsTimer = null;

function jobText(key) {
  const j = state.jobs[key];
  return j ? `${j.text} · ${Math.round((Date.now() - j.started) / 1000)}s` : "";
}

function jobLine(key) {
  return `<span class="job" data-job="${esc(key)}"><span class="spinner small"></span><span class="job-text">${esc(jobText(key))}</span></span>`;
}

function renderJobs() {
  const keys = Object.keys(state.jobs);
  const el = $("#jobs");
  if (!keys.length) { el.innerHTML = ""; return; }
  const first = state.jobs[keys[0]];
  const what = keys.length > 1 ? `${keys.length} jobs running`
    : `${keys[0].startsWith("make:") ? "Writing" : keys[0].startsWith("grade:") ? "Grading" : "Reading"} ${first.title}`;
  el.innerHTML = `<button class="jobs-pill" data-act="open-job" data-course="${first.course}" title="Show the exams page">
    <span class="spinner small"></span><span>${esc(what)}</span></button>`;
  for (const key of keys) {
    document.querySelectorAll(`[data-job="${CSS.escape(key)}"] .job-text`).forEach((t) => { t.textContent = jobText(key); });
  }
}

async function pollJobs() {
  if (!Object.keys(state.jobs).length) { clearInterval(jobsTimer); jobsTimer = null; return; }
  try {
    const now = await call("ai_jobs");
    for (const [key, text] of Object.entries(now)) if (state.jobs[key]) state.jobs[key].text = text;
  } catch (e) { /* the next look tries again */ }
  renderJobs();
}

// Start `work` in the background as job `key`; the page redraws when it starts and when it's done.
async function runJob(key, course, title, work) {
  state.jobs[key] = { course, title, text: "Starting…", started: Date.now() };
  renderJobs();
  if (!jobsTimer) jobsTimer = setInterval(pollJobs, 1000);
  const examPage = () => ["exams", "exam", "attempt"].includes(state.view.name);
  if (examPage()) refresh();
  try {
    await work();
  } catch (err) {
    toast(`${title}: ${err.message}`, true);
  } finally {
    delete state.jobs[key];
    renderJobs();
    if (examPage()) await refresh();
  }
}

async function readExam(id) {
  const e = findExam(id);
  if (!state.data.ai) { aiForm(); return; }
  if (e.counts.total && !(await confirmBox("Read the questions again?",
    `The ${plural(e.counts.total, "question")} listed now are replaced, along with how you marked them.`, "Read again"))) return;
  runJob(`read:${id}`, state.data.course.id, e.title, async () => {
    const r = await call("read_exam", id);
    toast(r.message);
    scheduleSync();
  });
}

// ---------- printing ----------

function printableHtml(e) {
  const qs = e.questions.map((q) => `<section class="q"><h3>Question ${esc(q.number)}${q.marks ? ` <small>(${esc(q.marks)}${/^\d+$/.test(q.marks) ? " marks" : ""})</small>` : ""}</h3>${md(q.prompt)}</section>`).join("");
  const sols = e.questions.map((q) => `<section class="q"><h3>${esc(q.number)}</h3>${md(q.answer)}</section>`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(e.title)}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.css">
<style>
body { font: 15px/1.55 Georgia, "Times New Roman", serif; max-width: 760px; margin: 40px auto; padding: 0 24px; color: #111; }
h1 { font-size: 26px; margin: 0 0 8px; } h2 { font-size: 20px; margin-top: 32px; } h3 { font-size: 16px; margin: 0 0 6px; }
h3 small { font-weight: normal; color: #555; } .intro { border: 1px solid #ccc; padding: 4px 16px; border-radius: 6px; margin: 16px 0 24px; }
.q { margin: 0 0 28px; break-inside: avoid; } table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 3px 8px; }
pre { background: #f4f4f4; padding: 8px 12px; overflow-x: auto; } .solutions { break-before: page; }
@media print { body { margin: 0 auto; } }
</style></head><body>
<h1>${esc(e.title)}</h1>${e.notes ? `<div class="intro">${md(e.notes)}</div>` : ""}
${qs}
<div class="solutions"><h2>Solutions</h2>${sols}</div>
</body></html>`;
}

// ---------- taking an exam ----------

// While an exam is being taken, the answers live here as they're typed and are saved a moment later, so
// nothing is lost if the window closes. The page isn't redrawn under the cursor while it's being taken.
const take = { id: null, answers: {}, timer: null, handingIn: false };

function saveAnswersSoon() {
  clearTimeout(take.timer);
  const id = take.id, answers = { ...take.answers };
  take.timer = setTimeout(() => call("save_answers", id, answers).catch(() => {}), 800);
}

async function flushAnswers() {
  clearTimeout(take.timer);
  if (take.id && Object.keys(take.answers).length) {
    try { await call("save_answers", take.id, take.answers); } catch (e) { /* handing in sends them again */ }
  }
}

function clockText(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(sec).padStart(2, "0")}`;
}

// d: the exam page's data (the exam, the suggested time limit, and whether a model is set up).
function takeForm(d) {
  const e = d.exam, examId = e.id;
  const n = e.questions.length;
  const form = openForm({
    title: `Take “${e.title}”`, submit: "Start",
    intro: `${plural(n, "question")}. The clock starts when you press Start, and keeps running if you leave the page or close StudyPal, like a real exam. Your answers are saved as you write.`
      + (d.ai ? " When you hand in, the model grades your answers against the solutions." : " When you hand in, you mark your answers against the solutions (or set up a model to grade them)."),
    fields: [
      { name: "timing", label: "Time", type: "choices", value: "timed", options: [
        ["timed", "Timed", "Counts down, and hands in by itself when time is up"],
        ["untimed", "No time limit", "A stopwatch only"]] },
      { name: "minutes", label: "Minutes", type: "number", value: d.suggested_minutes, min: 1, max: 600,
        hint: "Suggested from the number of questions. Use the real exam's time if you know it." },
    ],
    onSubmit: async (v) => {
      const minutes = v.timing === "timed" ? Number(v.minutes) : 0;
      if (v.timing === "timed" && !(minutes >= 1 && minutes <= 600)) throw new UserError("Give a time limit between 1 and 600 minutes.");
      const r = await call("start_attempt", { exam_id: examId, minutes });
      state.view = { name: "take", id: r.id };
      $("#view").scrollTop = 0;
      return null;
    },
  });
  const minutes = form.querySelector("[name=minutes]").closest(".field");
  const update = () => { minutes.style.display = form.querySelector("input[name=timing]:checked")?.value === "timed" ? "" : "none"; };
  form.addEventListener("change", update);
  update();
}

// Multiple choice: the options listed in the question ("A. ...", "b) ...", "(c) ..."), taken out of the
// question so they can be buttons. null when the question doesn't list at least two, in order from A.
const OPTION_LINE = /^\s*(?:[-*]\s+)?(?:\*\*)?\(?([A-Ha-h])[.)](?:\*\*)?\s+(.+?)\s*$/;
function choiceOptions(prompt) {
  const lines = (prompt || "").split("\n"), options = [], rest = [];
  for (const line of lines) {
    const m = line.match(OPTION_LINE);
    if (m && m[1].toUpperCase().charCodeAt(0) - 65 === options.length) options.push({ key: m[1].toUpperCase(), text: m[2] });
    else rest.push(line);
  }
  if (options.length < 2) return null;
  const multi = /answer\(s\)|all that apply|one or more|more than one|alternativ\(er\)|ett eller flere/i.test(prompt);
  return { stem: rest.join("\n").replace(/\n{3,}/g, "\n\n").trim(), options, multi };
}
const chosenKeys = (answer) => new Set([...(answer || "").matchAll(/^([A-H])\./gm)].map((m) => m[1]));
const TF = [["True", "True"], ["False", "False"]];

// How a question is answered while taking an exam: buttons for true or false and for multiple choice with
// its options listed, else a text box.
function takeAnswerInput(i, text) {
  const type = i.question_type;
  if (type === "true_false") {
    const now = text.trim().toLowerCase();
    return { prompt: i.prompt, input: `<div class="take-choices tf" role="group" aria-label="True or false">${TF.map(([v, label]) =>
      `<button class="take-choice${now === v.toLowerCase() ? " on" : ""}" data-act="take-choice" data-index="${i.index}" data-value="${v}"
        aria-pressed="${now === v.toLowerCase()}">${label}</button>`).join("")}</div>` };
  }
  const mc = type === "multiple_choice" ? choiceOptions(i.prompt) : null;
  if (mc) {
    const on = chosenKeys(text);
    return { prompt: mc.stem, input: `<div class="take-choices" role="group" aria-label="${mc.multi ? "Pick one or more" : "Pick one"}">
      ${mc.options.map((o) => `<button class="take-choice opt${on.has(o.key) ? " on" : ""}" data-act="take-choice" data-index="${i.index}"
        data-key="${o.key}" data-multi="${mc.multi ? 1 : ""}" aria-pressed="${on.has(o.key)}"><span class="opt-key">${o.key}</span>
        <span class="md">${md(o.text)}</span></button>`).join("")}
      ${mc.multi ? '<p class="faint take-choice-hint">Pick all that are right.</p>' : ""}</div>` };
  }
  return { prompt: i.prompt, input: `<textarea class="take-answer" id="ans-${i.index}" data-index="${i.index}" rows="${Math.min(18, Math.max(4, text.split("\n").length + 1))}"
        placeholder="Your answer. Maths can be written as $x^2$.">${esc(text)}</textarea>
      <div class="md take-preview" data-preview="${i.index}"${/[$\\]/.test(text) ? "" : " hidden"}>${/[$\\]/.test(text) ? md(text) : ""}</div>` };
}

function setTakeAnswer(i, value) {
  take.answers[i] = value;
  saveAnswersSoon();
  updateTakeCount();
  document.querySelector(`.take-dot[data-index="${i}"]`)?.classList.toggle("done", !!value.trim());
}

function renderTake(d) {
  const a = d.attempt, c = d.course;
  if (a.finished) { state.view = { name: "attempt", id: a.id }; return renderAttempt(d); }
  if (take.id !== a.id) { take.id = a.id; take.answers = {}; take.handingIn = false; }
  const answerOf = (i) => (i.index in take.answers ? take.answers[i.index] : i.answer) || "";
  const paper = d.exam.files[0];
  const nav = a.items.map((i) => `<button class="take-dot${answerOf(i).trim() ? " done" : ""}" data-act="take-jump" data-index="${i.index}"
      title="Question ${esc(i.number)}">${esc(i.number || i.index + 1)}</button>`).join("");
  const qs = a.items.map((i) => {
    const text = answerOf(i), view = takeAnswerInput(i, text);
    const worth = i.marks ? `${esc(i.marks)}${/^\d+([.,]\d+)?$/.test(i.marks) ? (i.marks === "1" ? " point" : " points") : ""}` : "";
    return `<section class="take-q" id="tq-${i.index}">
      <div class="q-head"><span class="q-num">${esc(i.number || i.index + 1)}</span>${worth ? `<span class="faint">${worth}</span>` : ""}
        ${i.has_figure ? `<span class="q-type">${ICON_FILE} uses a figure${paper ? ` in <button class="link" data-act="open-exam-file" data-id="${paper.id}">the exam paper</button>` : ""}</span>` : ""}</div>
      <div class="md q-prompt">${md(view.prompt)}</div>
      ${view.input}
    </section>`;
  }).join("");
  return `<div class="take" id="take-${a.id}" style="--course:${esc(cc(c.color))}">
    <div class="take-bar">
      <div class="take-title"><b>${esc(d.exam.title)}</b><span class="muted" id="take-count"></span></div>
      <div class="take-nav">${nav}</div>
      <span class="take-clock" id="take-clock" title="${a.minutes ? `Time left of ${a.minutes} minutes` : "Time so far"}"></span>
      <button class="btn ghost" data-act="open-exam" data-id="${a.exam_id}" title="The clock keeps running">Leave</button>
      <button class="btn ghost" data-act="abandon-take" data-id="${a.id}" title="Throw this attempt away">Abandon…</button>
      <button class="btn primary" data-act="hand-in">Hand in</button>
    </div>
    <div class="take-qs">${qs}
      <div class="take-end"><button class="btn primary" data-act="hand-in">Hand in</button></div>
    </div>
  </div>`;
}

function updateTakeCount() {
  const el = $("#take-count");
  if (!el || !state.data?.attempt) return;
  const items = state.data.attempt.items;
  const done = items.filter((i) => ((i.index in take.answers ? take.answers[i.index] : i.answer) || "").trim()).length;
  el.textContent = `${done} of ${items.length} answered`;
}

function tickTake() {
  const el = $("#take-clock");
  const a = state.data?.attempt;
  if (!el || !a || a.finished || state.view.name !== "take") return;
  const passed = (Date.now() - state.takeAt) / 1000;
  if (a.seconds_left === null) { el.textContent = clockText(a.elapsed + passed); return; }
  const left = a.seconds_left - passed;
  el.textContent = clockText(left);
  el.classList.toggle("low", left < 300);
  if (left <= 0 && !take.handingIn) {
    if (modalClose) modalClose();  // e.g. the "Hand in?" question, left open
    toast("Time's up. Your answers have been handed in.");
    handIn(true);
  }
}
setInterval(tickTake, 1000);

async function handIn(timeUp = false) {
  const a = state.data.attempt, courseId = state.data.course.id, title = state.data.exam.title;
  if (!timeUp) {
    const blank = a.items.filter((i) => !((i.index in take.answers ? take.answers[i.index] : i.answer) || "").trim()).length;
    const ok = await new Promise((resolve) => {
      openForm({ title: "Hand in?", intro: blank ? `${plural(blank, "question")} ${blank === 1 ? "has" : "have"} no answer yet. You can't change your answers after handing in.`
        : "You can't change your answers after handing in.", fields: [], submit: "Hand in", onSubmit: async () => { resolve(true); return null; }, onCancel: () => resolve(false) });
    });
    if (!ok) return;
  }
  take.handingIn = true;
  clearTimeout(take.timer);
  let r;
  try {
    r = await call("hand_in", a.id, take.answers);
  } catch (e) { take.handingIn = false; toast(e.message, true); return; }
  take.id = null;
  take.answers = {};
  state.view = { name: "attempt", id: a.id };
  $("#view").scrollTop = 0;
  scheduleSync();
  if (r.grade) gradeAttempt(a.id, courseId, title);
  else await refresh();
}

function gradeAttempt(id, courseId, title) {
  runJob(`grade:${id}`, courseId, title, async () => {
    const r = await call("grade_attempt", id);
    toast(r.message);
    scheduleSync();
  });
}

const VERDICT_LABELS = { ok: "Right", partial: "Partly", missed: "Wrong" };

function renderAttempt(d) {
  const a = d.attempt, c = d.course, e = d.exam;
  if (!a.finished) return renderTake(d);
  const grading = state.jobs[`grade:${a.id}`];
  const sc = a.score;
  const hero = `<div class="panel attempt-hero">
      <div class="attempt-big ${scoreClass(sc.percent)}">${grading ? '<span class="spinner"></span>' : sc.percent !== null ? `${sc.percent}%` : "–"}</div>
      <div class="grow">
        <div class="attempt-points">${grading ? jobLine(`grade:${a.id}`) : sc.marked ? `${sc.got} of ${sc.max} points${sc.marked < sc.total ? ` · ${sc.total - sc.marked} not graded yet` : ""}` : "Not graded yet"}</div>
        <div class="muted">${esc(a.started_label)} · ${esc(a.time_label)}${a.minutes ? ` of ${a.minutes} min` : ""} · ${a.answered} of ${a.questions} answered${a.graded === "model" ? " · graded by the model" : a.graded === "self" ? " · marked by you" : ""}</div>
        ${!grading && !sc.marked ? `<p class="attempt-hint">${d.ai ? "Have the model grade it, or mark each answer yourself below." : "Mark each answer against the solution below, or set up a model to grade it for you."}</p>` : ""}
      </div>
      ${grading ? "" : d.ai ? `<button class="btn${sc.marked ? "" : " primary"}" data-act="grade-attempt" data-id="${a.id}">${ICON_SPARK} ${a.graded === "model" ? "Grade again" : "Grade with model"}</button>`
        : `<button class="btn" data-act="ai-setup">Set up a model</button>`}
    </div>`;
  const summary = a.summary && !grading ? `<div class="panel panel-body attempt-summary">${ICON_SPARK}<div class="md">${md(a.summary)}</div></div>` : "";
  const items = a.items.map((i) => {
    const seg = ["ok", "partial", "missed"].map((r) => `<button class="res ${r}${i.verdict === r ? " on" : ""}" data-act="attempt-verdict"
        data-index="${i.index}" data-verdict="${i.verdict === r ? "" : r}" aria-pressed="${i.verdict === r}"
        title="${i.verdict === r ? "Click again to clear" : `Mark as ${VERDICT_LABELS[r].toLowerCase()}`}">${VERDICT_LABELS[r]}</button>`).join("");
    const got = i.verdict ? `<span class="attempt-q-points">${Number(i.points ?? 0)} / ${i.worth}</span>` : `<span class="faint">${i.worth} ${i.worth === 1 ? "point" : "points"}</span>`;
    return `<div class="q${i.verdict ? ` r-${i.verdict}` : ""}">
      <div class="q-head"><span class="q-num">${esc(i.number || i.index + 1)}</span>${got}
        <span class="q-res" role="group" aria-label="How did it go?">${seg}</span></div>
      <div class="md q-prompt">${md(i.prompt)}</div>
      <div class="your-answer"><div class="label">Your answer</div>${(i.answer || "").trim() ? `<div class="md">${md(i.answer)}</div>` : '<p class="faint">No answer.</p>'}</div>
      ${i.feedback ? `<div class="q-why attempt-feedback">${ICON_SPARK} <div class="md">${md(i.feedback)}</div></div>` : ""}
      ${i.solution ? `<details class="q-answer"${i.verdict ? "" : " open"}><summary>Solution</summary><div class="md">${md(i.solution)}</div></details>`
        : '<p class="faint q-noanswer">No solution for this one.</p>'}
    </div>`;
  }).join("");
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-act="open-exam" data-id="${e.id}">${ICONS.back} ${esc(e.title)}</button></div>
    <div class="title-line"><h1>Results</h1>
      <div class="title-actions">
        <button class="btn" data-act="take-again" data-id="${e.id}">${ICONS.play} Take again</button>
        <button class="icon-btn" data-act="attempt-menu" data-id="${a.id}" aria-label="More">${ICONS.more}</button>
      </div>
    </div>
  </div>
  <div class="attempt-page" style="--course:${esc(cc(c.color))}">
    ${hero}${summary}
    <div class="panel exam"><div class="qs">${items}</div></div>
  </div>`;
}

async function loadAttempt(id) {
  const d = await call("attempt", id);
  state.takeAt = Date.now();
  return d;
}

Object.assign(VIEWS, {
  exam: { load: (id) => call("exam", id), render: (d) => renderExam(d) },
  // While it's being taken, the 30-second refresh only updates the clock, not the page being typed into.
  take: { load: loadAttempt, render: (d) => renderTake(d),
    keep: (d) => !d.attempt.finished && !!document.getElementById(`take-${d.attempt.id}`) },
  attempt: { load: loadAttempt, render: (d) => renderAttempt(d) },
});

// After a redraw of the exam being taken: its count and clock straight away.
const examsAfterRender = afterRender;
afterRender = () => { examsAfterRender(); if (state.view.name === "take") { updateTakeCount(); tickTake(); } };

document.addEventListener("input", (e) => {
  const t = e.target;
  if (!t.classList?.contains("take-answer")) return;
  const i = Number(t.dataset.index);
  setTakeAnswer(i, t.value);
  const preview = document.querySelector(`[data-preview="${i}"]`);
  if (preview) {
    const show = /[$\\]/.test(t.value);
    preview.hidden = !show;
    if (show) preview.innerHTML = md(t.value);
  }
  // Grow with the answer.
  if (t.scrollHeight > t.clientHeight) t.rows = Math.min(30, t.rows + 2);
});

// ---------- clicks ----------

Object.assign(actions, {
  "open-exams": (el) => go({ name: "exams", id: Number(el.dataset.id) }),
  "add-exam": (el) => examForm(Number(el.dataset.course)),
  "make-exam": (el) => makeExamForm(Number(el.dataset.course)),
  "ai-setup": () => aiForm(),
  "open-job": (el) => go({ name: "exams", id: Number(el.dataset.course) }),
  "open-exam": async (el) => { if (state.view.name === "take") await flushAnswers(); go({ name: "exam", id: Number(el.dataset.id) }); },
  "take-exam": () => takeForm(state.data),
  "take-again": async (el) => {
    try { takeForm(await call("exam", Number(el.dataset.id))); } catch (e) { toast(e.message, true); }
  },
  "open-take": (el) => go({ name: "take", id: Number(el.dataset.id) }),
  "open-attempt": (el) => go({ name: "attempt", id: Number(el.dataset.id) }),
  "take-jump": (el) => {
    const q = document.getElementById(`tq-${el.dataset.index}`);
    q?.scrollIntoView({ behavior: "smooth", block: "start" });
    setTimeout(() => (document.getElementById(`ans-${el.dataset.index}`) || q?.querySelector(".take-choice.on, .take-choice"))
      ?.focus({ preventScroll: true }), 300);
  },
  "take-choice": (el) => {
    const i = Number(el.dataset.index), group = el.closest(".take-choices");
    const buttons = [...group.querySelectorAll(".take-choice")];
    if (el.dataset.value) {  // true or false: click again to clear
      buttons.forEach((b) => { const on = b === el && !el.classList.contains("on"); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
    } else {
      const on = !el.classList.contains("on");
      if (!el.dataset.multi) buttons.forEach((b) => { b.classList.remove("on"); b.setAttribute("aria-pressed", false); });
      el.classList.toggle("on", on);
      el.setAttribute("aria-pressed", on);
    }
    const item = state.data.attempt.items.find((x) => x.index === i);
    const mc = el.dataset.value ? null : choiceOptions(item.prompt);
    const value = el.dataset.value
      ? (group.querySelector(".take-choice.on")?.dataset.value || "")
      : mc.options.filter((o) => buttons.find((b) => b.dataset.key === o.key)?.classList.contains("on")).map((o) => `${o.key}. ${o.text}`).join("\n");
    setTakeAnswer(i, value);
  },
  "abandon-take": async (el) => {
    const id = Number(el.dataset.id), examId = state.data.exam.id;
    if (!(await confirmBox("Abandon this attempt?", "Your answers so far are thrown away and it isn't graded. You can take the exam again afterwards."))) return;
    clearTimeout(take.timer);
    take.id = null;
    take.answers = {};
    state.view = { name: "exam", id: examId };
    act("delete_attempt", id);
  },
  "attempt-row-menu": (el) => {
    const id = Number(el.dataset.id), finished = !!el.dataset.finished;
    openMenu(el, [{ label: finished ? "Delete this attempt…" : "Abandon this attempt…", danger: true, onClick: async () => {
      const ok = finished
        ? await confirmBox("Delete this attempt?", "Your answers and grades for it are removed. How the exam's questions are marked stays as it is.")
        : await confirmBox("Abandon this attempt?", "Your answers so far are thrown away and it isn't graded. You can take the exam again afterwards.");
      if (!ok) return;
      if (take.id === id) { clearTimeout(take.timer); take.id = null; take.answers = {}; }
      act("delete_attempt", id);
    } }]);
  },
  "hand-in": () => handIn(false),
  "grade-attempt": (el) => {
    const d = state.data;
    gradeAttempt(Number(el.dataset.id), d.course.id, d.exam.title);
  },
  "attempt-verdict": (el) => act("set_attempt_verdict", state.data.attempt.id, Number(el.dataset.index), el.dataset.verdict),
  "attempt-menu": (el) => {
    const id = Number(el.dataset.id), examId = state.data.exam.id;
    openMenu(el, [{ label: "Delete this attempt…", danger: true, onClick: async () => {
      if (!(await confirmBox("Delete this attempt?", "Your answers and grades for it are removed. How the exam's questions are marked stays as it is."))) return;
      state.view = { name: "exam", id: examId };
      act("delete_attempt", id);
    } }]);
  },
  "read-exam": (el) => readExam(Number(el.dataset.id)),
  "open-exam-file": async (el) => { try { await call("open_exam_file", Number(el.dataset.id)); } catch (e) { toast(e.message, true); } },
  "add-question": (el) => questionForm(Number(el.dataset.id)),
  "q-result": (el) => act("set_question_result", Number(el.dataset.id), el.dataset.result),
  "print-exam": async (el) => {
    const e = findExam(el.dataset.id);
    try { const r = await call("save_printable", e.title, printableHtml(e)); if (r.message) toast(r.message); } catch (err) { toast(err.message, true); }
  },
  "q-menu": (el) => {
    const id = Number(el.dataset.id);
    const exam = allExams().find((e) => e.questions.some((q) => q.id === id));
    const q = exam.questions.find((x) => x.id === id);
    openMenu(el, [
      { label: "Edit, add a note or topic", onClick: () => questionForm(exam.id, q) },
      ...(q.result === "missed" || q.result === "partial" ? [{ label: "Add to weak spots", onClick: () => act("question_to_weak", id) }] : []),
      { label: "Copy question", onClick: () => copyRich(q.prompt, md(q.prompt)).then((ok) => toast(ok ? "Copied." : "Couldn't copy.", !ok)) },
      "-",
      { label: "Delete question", danger: true, onClick: () => act("delete_question", id) },
    ]);
  },
  "exam-menu": (el) => {
    const id = Number(el.dataset.id);
    const e = findExam(id);
    const items = [];
    const courseId = state.data.course.id;
    if (e.kind === "past") items.push({ label: "Edit details and files", onClick: () => examForm(courseId, e) });
    else items.push({ label: "Print or save…", onClick: () => actions["print-exam"](el) });
    items.push({ label: "Add a question by hand", onClick: () => questionForm(id) });
    items.push("-", { label: "Delete exam…", danger: true, onClick: async () => {
      const what = e.kind === "past" ? "Its files and questions are removed, and how you marked them" : "Its questions and how you marked them are removed";
      if (!(await confirmBox(`Delete “${e.title}”?`, `${what}, along with the times you've taken it.`))) return;
      if (state.view.name === "exam") state.view = { name: "exams", id: courseId };
      act("delete_exam", id);
    } });
    openMenu(el, items);
  },
});

document.addEventListener("toggle", (e) => {
  if (e.target.matches?.("details.q-answer")) {
    const id = Number(e.target.dataset.id);
    e.target.open ? state.openAnswers.add(id) : state.openAnswers.delete(id);
  }
}, true);
