"use strict";

// The exams page: past exams (with their files and how each question went) and practice exams that
// Gemini writes from them. Loaded after app.js; uses its helpers, and adds to its `actions`.

// ---------- drawing ----------

const ROLE_LABELS = { exam: "Exam", solution: "Solutions", attempt: "My answers" };
const RESULT_LABELS = { ok: "Got it", partial: "Partly", missed: "Missed" };
const ICON_SPARK = '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z"/></svg>';
const ICON_FILE = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>';

state.openExams = (() => { try { return new Set(JSON.parse(localStorage.getItem("studypal.openExams") || "[]")); } catch (e) { return new Set(); } })();
state.openAnswers = new Set();

function saveOpenExams() {
  try { localStorage.setItem("studypal.openExams", JSON.stringify([...state.openExams])); } catch (e) { /* only a convenience */ }
}

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
  const answerLabel = exam.kind === "practice" ? "Solution" : exam.has_solution ? "Answer (from the solutions)" : "Suggested answer (by Gemini)";
  return `<div class="q${q.result ? ` r-${q.result}` : ""}">
    <div class="q-head">
      <span class="q-num">${esc(q.number || "·")}</span>
      ${q.topic ? `<span class="tag topic-tag">${esc(q.topic)}</span>` : ""}
      ${q.marks ? `<span class="faint">${esc(q.marks)} ${/^\d+(\.\d+)?$/.test(q.marks) ? (q.marks === "1" ? "mark" : "marks") : ""}</span>` : ""}
      <span class="q-res" role="group" aria-label="How did it go?">${seg}</span>
      <button class="icon-btn small" data-act="q-menu" data-id="${q.id}" aria-label="Question options">${ICONS.more}</button>
    </div>
    ${q.why ? `<div class="q-why">${ICON_SPARK} ${esc(q.why)}</div>` : ""}
    <div class="md q-prompt">${md(q.prompt) || '<p class="faint">No question text.</p>'}</div>
    ${q.note ? `<div class="q-note"><b>What went wrong:</b> ${esc(q.note)}</div>` : ""}
    ${q.answer ? `<details class="q-answer" data-id="${q.id}"${open ? " open" : ""}><summary>${answerLabel}</summary>
      <div class="md">${md(q.answer)}</div></details>` : ""}
  </div>`;
}

function examPanel(e, d) {
  const open = state.openExams.has(e.id);
  const meta = [e.kind === "practice" ? `Made ${e.created_label}` : e.taken_on, e.score ? `Score: ${e.score}` : "",
    e.counts.total ? plural(e.counts.total, "question") : ""].filter(Boolean).join(" · ");
  const fileChips = e.files.map((f) => `<button class="file-chip${f.available ? "" : " missing"}" data-act="open-exam-file" data-id="${f.id}"
      title="${f.available ? "Open" : "Not downloaded to this computer yet"}">${ICON_FILE}<span>${esc(f.name)}</span><small>${esc(ROLE_LABELS[f.role] || f.role)}</small></button>`).join("");
  const canRead = e.kind === "past" && e.files.some((f) => f.role === "exam");
  const readBtn = canRead ? `<button class="btn small${e.counts.total ? " ghost" : ""}" data-act="read-exam" data-id="${e.id}"
      title="Gemini reads the files and lists the questions">${ICON_SPARK} ${e.counts.total ? "Read again" : "Read questions"}</button>` : "";
  let body = "";
  if (open) {
    const intro = e.kind === "practice" && e.notes ? `<div class="md exam-intro">${md(e.notes)}</div>` : "";
    const notes = e.kind === "past" && e.notes ? `<p class="muted exam-notes">${esc(e.notes)}</p>` : "";
    const qs = e.questions.length ? e.questions.map((q) => questionBlock(q, e)).join("")
      : `<p class="empty-small">${canRead
        ? (d.gemini ? "Click <b>Read questions</b> and Gemini lists them, with answers. Then mark how each one went." : "Set up Gemini to have the questions listed for you, or add them by hand.")
        : "Add the exam paper (a PDF or photos) so the questions can be read from it, or add them by hand."}
        <button class="btn small ghost" data-act="add-question" data-id="${e.id}">+ Add a question by hand</button></p>`;
    body = `${fileChips ? `<div class="file-chips">${fileChips}</div>` : ""}${notes}${intro}<div class="qs">${qs}</div>`;
  }
  return `<div class="panel source exam${open ? " open" : ""}" id="exam-${e.id}">
    <div class="source-head foldable" data-act="fold-exam" data-id="${e.id}">
      <button class="chev${open ? " open" : ""}" data-act="fold-exam" data-id="${e.id}" aria-label="Show questions" aria-expanded="${open}">${ICONS.chev}</button>
      <div class="grow"><h3>${esc(e.title)}</h3><div class="muted">${esc(meta) || (e.kind === "past" ? "No questions listed yet" : "")}</div></div>
      <span class="counts">${resultCounts(e.counts)}</span>
      ${readBtn}
      ${e.kind === "practice" ? `<button class="btn small ghost" data-act="print-exam" data-id="${e.id}" title="Save as a page to print">Print…</button>` : ""}
      <button class="icon-btn small" data-act="exam-menu" data-id="${e.id}" aria-label="More">${ICONS.more}</button>
    </div>
    ${body}
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
  const setup = d.gemini ? "" : `<div class="panel panel-body gemini-setup">
      <div class="grow"><b>Set up Gemini to read exams and write practice exams</b>
      <p class="muted">Google's Gemini needs an API key, which is free. It takes a minute to get one.</p></div>
      <button class="btn primary" data-act="gemini-setup">Set up Gemini</button></div>`;
  const past = d.past.length ? d.past.map((e) => examPanel(e, d)).join("")
    : `<div class="panel panel-body"><p class="muted" style="margin:0">Add the past exams for ${esc(c.code)}: the exam paper, and the solutions and your own (graded) answers if you have them. Gemini lists the questions, and you mark which ones went badly.</p></div>`;
  const practice = d.practice.length ? d.practice.map((e) => examPanel(e, d)).join("")
    : `<div class="panel panel-body"><p class="muted" style="margin:0">${d.past.length
      ? "Make a practice exam: new questions in the style of your past exams, aimed at what you struggled with."
      : "Practice exams are written in the style of your past exams. Add some first, or make one from your topics alone."}</p></div>`;
  return `<div class="subject-head" style="--course:${esc(cc(c.color))}">
    <div class="crumbs"><button class="btn small ghost" data-act="open-subject" data-id="${c.id}">${ICONS.back} ${esc(c.code)} ${esc(c.name)}</button></div>
    <div class="title-line"><h1>Exams</h1>
      <div class="title-actions">
        <button class="btn" data-act="add-exam" data-course="${c.id}">+ Add past exam</button>
        <button class="btn primary" data-act="make-exam" data-course="${c.id}">${ICON_SPARK} Make practice exam</button>
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
      state.openExams.add(r.id);
      saveOpenExams();
      return r;
    },
  });
  form.querySelector(".form-error").insertAdjacentHTML("beforebegin", `<div class="field"><span>Files</span>
      <div class="file-rows"></div>
      <div><button type="button" class="btn small" data-files="add">+ Add files…</button></div>
      <small>PDFs or photos. Add the exam itself, and if you have them the solutions and your own answers (graded if possible): with your answers, Gemini can tell which questions went badly.</small></div>`);
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
  const exam = [...state.data.past, ...state.data.practice].find((e) => e.id === examId);
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

function geminiFields(g) {
  return [
    { name: "gemini_key", label: "Gemini API key", type: "password", value: "",
      placeholder: g.has_key ? `Saved (${g.key_hint || "hidden"}). Paste a new one to replace it` : "Paste your key here",
      hint: `Used to read exams and write practice exams. Get a free key at <a href="${esc(g.key_url)}" target="_blank" rel="noopener">aistudio.google.com/apikey</a> (sign in with Google, then <b>Create API key</b>). It's kept on this computer only.` },
    { name: "gemini_model", label: "Gemini model", type: "select", value: g.model, options: g.models },
    ...(g.has_key ? [{ name: "gemini_forget", label: "Remove the saved key from this computer", type: "checkbox", value: false }] : []),
  ];
}

async function geminiForm() {
  const g = await call("gemini_settings");
  openForm({
    title: "Set up Gemini", wide: true, submit: "Save",
    intro: "StudyPal uses Google's Gemini to read your past exams and write new ones. It needs your own API key:<ol class=\"steps\"><li>Open <a href=\"" + esc(g.key_url) + "\" target=\"_blank\" rel=\"noopener\">aistudio.google.com/apikey</a> and sign in with a Google account.</li><li>Click <b>Create API key</b> and copy it.</li><li>Paste it below.</li></ol>The free key has daily limits, which is plenty for a few exams a day. Your exams are sent to Google when Gemini reads them.",
    fields: geminiFields(g),
    onSubmit: async (v) => {
      if (!v.gemini_key && !g.has_key) throw new UserError("Paste your API key first.");
      return call("save_gemini", { key: v.gemini_key, model: v.gemini_model, forget: !!v.gemini_forget });
    },
  });
}

function makeExamForm(courseId) {
  const d = state.data;
  if (!d.gemini) { geminiForm(); return; }
  const files = d.past.reduce((n, e) => n + e.files.filter((f) => f.role !== "attempt").length, 0);
  const marked = d.tally.reduce((n, t) => n + t.missed + t.partial, 0);
  const uses = [files ? `${plural(d.past.filter((e) => e.files.length).length, "past exam")} (${plural(files, "file")})` : "",
    marked ? `${plural(marked, "question")} you missed or got partly right` : "",
    d.weak_open ? plural(d.weak_open, "open weak spot") : ""].filter(Boolean);
  const form = openForm({
    title: "Make a practice exam", wide: true, submit: "Make exam",
    intro: uses.length ? `Gemini uses ${uses.join(", ")}, and your topics.` : "There are no past exams or marked questions yet, so Gemini goes by your topics alone.",
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
      const button = f.querySelector("button[type=submit]");
      const started = Date.now();
      const label = () => { button.textContent = `Gemini is writing… ${Math.round((Date.now() - started) / 1000)}s`; };
      label();
      const clock = setInterval(label, 1000);
      f.classList.add("working");
      try {
        const topic_ids = [...f.querySelectorAll("[data-topic]:checked")].map((x) => Number(x.dataset.topic));
        const r = await call("make_exam", { ...v, course_id: courseId, topic_ids });
        state.openExams.add(r.id);
        saveOpenExams();
        setTimeout(() => document.getElementById(`exam-${r.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
        return r;
      } finally {
        clearInterval(clock);
        button.textContent = "Make exam";
        f.classList.remove("working");
      }
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

// A busy note over the page while Gemini reads (it can take a minute).
function busy(message) {
  const el = document.createElement("div");
  el.className = "busy";
  const started = Date.now();
  el.innerHTML = `<div class="busy-box"><span class="spinner"></span><span class="busy-text"></span></div>`;
  const text = el.querySelector(".busy-text");
  const draw = () => { text.textContent = `${message} ${Math.round((Date.now() - started) / 1000)}s`; };
  draw();
  const clock = setInterval(draw, 1000);
  document.body.append(el);
  return () => { clearInterval(clock); el.remove(); };
}

async function readExam(id) {
  const e = state.data.past.find((x) => x.id === id);
  if (!state.data.gemini) { geminiForm(); return; }
  if (e.counts.total && !(await confirmBox("Read the questions again?",
    `The ${plural(e.counts.total, "question")} listed now are replaced, along with how you marked them.`, "Read again"))) return;
  const done = busy("Gemini is reading the exam (this can take a few minutes)…");
  try {
    const r = await call("read_exam", id);
    state.openExams.add(id);
    saveOpenExams();
    toast(r.message);
    await refresh();
    scheduleSync();
  } catch (err) {
    toast(err.message, true);
  } finally {
    done();
  }
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

// ---------- clicks ----------

Object.assign(actions, {
  "open-exams": (el) => go({ name: "exams", id: Number(el.dataset.id) }),
  "add-exam": (el) => examForm(Number(el.dataset.course)),
  "make-exam": (el) => makeExamForm(Number(el.dataset.course)),
  "gemini-setup": () => geminiForm(),
  "fold-exam": (el) => {
    const id = Number(el.dataset.id);
    state.openExams.has(id) ? state.openExams.delete(id) : state.openExams.add(id);
    saveOpenExams();
    $("#view").innerHTML = renderExams(state.data);
  },
  "read-exam": (el) => readExam(Number(el.dataset.id)),
  "open-exam-file": async (el) => { try { await call("open_exam_file", Number(el.dataset.id)); } catch (e) { toast(e.message, true); } },
  "add-question": (el) => questionForm(Number(el.dataset.id)),
  "q-result": (el) => act("set_question_result", Number(el.dataset.id), el.dataset.result),
  "print-exam": async (el) => {
    const e = state.data.practice.find((x) => x.id === Number(el.dataset.id));
    try { const r = await call("save_printable", e.title, printableHtml(e)); if (r.message) toast(r.message); } catch (err) { toast(err.message, true); }
  },
  "q-menu": (el) => {
    const id = Number(el.dataset.id);
    const exam = [...state.data.past, ...state.data.practice].find((e) => e.questions.some((q) => q.id === id));
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
    const e = [...state.data.past, ...state.data.practice].find((x) => x.id === id);
    const items = [];
    if (e.kind === "past") items.push({ label: "Edit details and files", onClick: () => examForm(state.view.id, e) });
    else items.push({ label: "Print or save…", onClick: () => actions["print-exam"](el) });
    items.push({ label: "Add a question by hand", onClick: () => { state.openExams.add(id); saveOpenExams(); questionForm(id); } });
    items.push("-", { label: "Delete exam…", danger: true, onClick: async () => {
      if (await confirmBox(`Delete “${e.title}”?`, e.kind === "past" ? "Its files and questions are removed, and how you marked them." : "Its questions and how you marked them are removed.")) act("delete_exam", id);
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
