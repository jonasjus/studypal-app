// Daily to-do lists: one list per day, today's by default, with the week around it to plan ahead. Ticking a
// to-do off throws a little confetti from its box; finishing the whole day's list throws a lot.

const TODO_ICONS = {
  todo: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="m8 12 3 3 5-6"/></svg>',
  later: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h12M13 7l5 5-5 5"/></svg>',
  prev: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
};

function todoRow(t, d) {
  // Move an unfinished to-do on to the next day (from today or a day gone by, to tomorrow; else one day on).
  const later = t.done ? "" : iconBtn("later", "todo-later", `data-id="${t.id}"`, d.is_today || d.is_past ? "Move to tomorrow" : "Move to the next day");
  return `<li class="row todo-row${t.done ? " done" : ""}" data-id="${t.id}">
      ${dragHandle()}
      <input type="checkbox" class="check todo-check" data-act="toggle-todo" data-id="${t.id}"${t.done ? " checked" : ""} aria-label="Done: ${esc(t.text)}">
      <div class="grow"><div class="title wrap">${esc(t.text)}</div>${t.done_label ? `<div class="sub">Done at ${esc(t.done_label)}</div>` : ""}</div>
      <span class="row-actions">${later}${iconBtn("edit", "edit-todo", `data-id="${t.id}"`, "Edit")}${iconBtn("trash", "delete-todo", `data-id="${t.id}"`, "Delete")}</span>
    </li>`;
}

function todoWeek(d) {
  return `<div class="todo-week" role="group" aria-label="This week">${d.week.map((w) => {
    const state = !w.total ? "" : w.done === w.total ? " all" : " some";
    const count = w.total ? `${w.done}/${w.total}` : "";
    return `<button class="todo-day${w.selected ? " on" : ""}${w.today ? " is-today" : ""}${state}" data-act="todo-day" data-day="${w.day}"
        ${w.selected ? 'aria-current="date"' : ""} title="${esc(`${w.label} ${w.date}${w.total ? `: ${w.done} of ${w.total} done` : ""}`)}">
        <span class="todo-day-name">${esc(w.label)}</span><span class="todo-day-date">${w.date}</span>
        <span class="todo-day-count">${count || "&nbsp;"}</span></button>`;
  }).join("")}</div>`;
}

function renderTodos(d) {
  const pct = d.total ? Math.round((100 * d.done) / d.total) : 0;
  const summary = !d.total ? "Nothing planned yet."
    : d.done === d.total ? `${d.total === 1 ? "Done" : `All ${d.total} done`}. Nice work! 🎉`
    : `${d.done} of ${d.total} done`;
  const behind = d.left_behind
    ? `<div class="todo-behind"><span>${d.left_behind} unfinished to-do${d.left_behind !== 1 ? "s" : ""} from earlier days.</span>
        <button class="btn small" data-act="todos-forward">Move to today</button></div>` : "";
  const empty = d.is_past ? "Nothing was planned for this day." : d.is_today
    ? "What do you want to get done today? Small, concrete steps work best, like \"Past exam 2022, questions 1–3\"."
    : "Plan ahead: add what you want to get done this day.";
  return `<div class="todo-page">
    <div class="todo-head">
      <h1>To-do</h1>
      <div class="todo-nav">
        <button class="icon-btn" data-act="todo-day" data-day="${d.prev}" title="Previous day" aria-label="Previous day">${TODO_ICONS.prev}</button>
        <div class="todo-when"><b>${esc(d.name)}</b>${d.name !== d.long_label ? `<span>${esc(d.long_label)}</span>` : ""}</div>
        <button class="icon-btn" data-act="todo-day" data-day="${d.next}" title="Next day" aria-label="Next day">${ICONS.chev}</button>
        ${d.is_today ? "" : `<button class="btn small ghost" data-act="todo-day" data-day="${d.today}">Today</button>`}
      </div>
    </div>
    ${todoWeek(d)}
    ${behind}
    <div class="panel todo-panel">
      <div class="todo-progress">
        <span class="todo-summary">${esc(summary)}</span>
        ${d.total ? `<div class="todo-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${d.total}" aria-valuenow="${d.done}" aria-label="${d.done} of ${d.total} done"><span style="width:${pct}%"></span></div>` : ""}
      </div>
      <form class="task-add" data-form="add-todo"><input id="todo-new" placeholder="Add a to-do and press Enter" autocomplete="off" aria-label="New to-do"></form>
      ${d.items.length ? `<ul class="list" data-sortable="todo">${d.items.map((t) => todoRow(t, d)).join("")}</ul>` : `<p class="empty-small">${esc(empty)}</p>`}
    </div>
  </div>`;
}

// ---------- confetti ----------

const CONFETTI_COLORS = ["#f2c14e", "#f78154", "#4d9de0", "#5fbb97", "#e15a97", "#a06cd5"];

function confetti(x, y, { count = 40, spread = 1, power = 1 } = {}) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const canvas = document.createElement("canvas");
  canvas.className = "confetti";
  const dpr = window.devicePixelRatio || 1;
  canvas.width = innerWidth * dpr;
  canvas.height = innerHeight * dpr;
  document.body.append(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const bits = Array.from({ length: count }, () => {
    const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 0.9 * spread;
    const speed = (5 + Math.random() * 7) * power;
    return {
      x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
      size: 5 + Math.random() * 5, turn: Math.random() * Math.PI, spin: (Math.random() - 0.5) * 0.4,
      color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)], round: Math.random() < 0.3,
    };
  });
  const started = performance.now();
  const frame = (t) => {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    const fade = Math.max(0, 1 - (t - started - 1400) / 600);
    for (const b of bits) {
      b.vy += 0.28;  // gravity
      b.vx *= 0.985;
      b.vy *= 0.985;
      b.x += b.vx;
      b.y += b.vy;
      b.turn += b.spin;
      ctx.save();
      ctx.globalAlpha = fade;
      ctx.translate(b.x, b.y);
      ctx.rotate(b.turn);
      ctx.fillStyle = b.color;
      if (b.round) { ctx.beginPath(); ctx.arc(0, 0, b.size / 2.4, 0, Math.PI * 2); ctx.fill(); }
      else ctx.fillRect(-b.size / 2, -b.size / 4, b.size, b.size / 2 * (0.4 + Math.abs(Math.cos(b.turn))));
      ctx.restore();
    }
    if (fade > 0) requestAnimationFrame(frame);
    else canvas.remove();
  };
  requestAnimationFrame(frame);
}

// The whole list done: bursts from both bottom corners and the middle.
function celebrate() {
  confetti(innerWidth * 0.1, innerHeight, { count: 90, spread: 0.5, power: 1.9 });
  confetti(innerWidth * 0.9, innerHeight, { count: 90, spread: 0.5, power: 1.9 });
  setTimeout(() => confetti(innerWidth / 2, innerHeight * 0.45, { count: 120, spread: 2, power: 1.1 }), 250);
}

// ---------- the sidebar's To-do and Statistics items ----------

let todoToday = null;  // {done, total}, for the sidebar

async function loadTodoToday() {
  try { todoToday = await call("todo_today"); } catch (e) { return; }
  const sub = $("#side-todo .side-sub");
  if (sub) sub.textContent = todoToday.total ? `${todoToday.done} of ${todoToday.total} done today` : "Plan your day";
}

function sideExtras(v) {
  const sub = !todoToday ? "" : todoToday.total ? `${todoToday.done} of ${todoToday.total} done today` : "Plan your day";
  return `<button id="side-todo" class="side-item${v.name === "todo" ? " active" : ""}" data-go="todo" title="To-do"${v.name === "todo" ? ' aria-current="page"' : ""}>
      <span class="side-badge plain">${TODO_ICONS.todo}</span><span class="side-text"><span class="side-label">To-do</span><span class="side-sub">${esc(sub)}</span></span></button>
    <button class="side-item${v.name === "stats" ? " active" : ""}" data-go="stats" title="Statistics"${v.name === "stats" ? ' aria-current="page"' : ""}>
      <span class="side-badge plain">${STATS_ICON}</span><span class="side-text"><span class="side-label">Statistics</span></span></button>`;
}

// ---------- wiring ----------

VIEWS.todo = { load: (day) => call("todos", day || null), render: (d) => renderTodos(d) };

async function toggleTodo(el) {
  const box = el.getBoundingClientRect();
  const r = await act("toggle_todo", Number(el.dataset.id));
  if (!r || !r.done) return;
  if (r.all_done) celebrate();
  else confetti(box.left + box.width / 2, box.top + box.height / 2);
}

Object.assign(actions, {
  "todo-day": (el) => go({ name: "todo", id: el.dataset.day }),
  "toggle-todo": (el) => toggleTodo(el),
  "delete-todo": (el) => act("delete_todo", Number(el.dataset.id)),
  "todo-later": (el) => {
    const d = state.data, next = d.is_today || d.is_past ? new Date(`${d.today}T12:00`) : new Date(`${d.day}T12:00`);
    next.setDate(next.getDate() + 1);
    const iso = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}-${String(next.getDate()).padStart(2, "0")}`;
    act("move_todo", Number(el.dataset.id), iso);
  },
  "todos-forward": () => act("bring_todos_forward"),
  "edit-todo": (el) => {
    const t = state.data.items.find((x) => x.id === Number(el.dataset.id));
    if (!t) return;
    openForm({
      title: "Edit to-do",
      fields: [{ name: "text", label: "What needs doing", value: t.text, required: true }],
      onSubmit: async (v) => { await call("edit_todo", t.id, v.text); },
    });
  },
});

Object.assign(SORTED, {
  todo: (items) => call("move_items", "todo", items.map((el) => Number(el.dataset.id))),
});

document.addEventListener("submit", async (e) => {
  if (e.target.dataset?.form !== "add-todo") return;
  e.preventDefault();
  const input = $("#todo-new");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const r = await act("add_todo", state.data.day, text);
  if (!r) input.value = text;
  $("#todo-new")?.focus();
});

// Pasting several lines adds them all as separate to-dos.
document.addEventListener("paste", (e) => {
  if (e.target.id !== "todo-new") return;
  const text = e.clipboardData?.getData("text") || "";
  if (!text.includes("\n")) return;
  e.preventDefault();
  act("add_todo", state.data.day, text).then(() => $("#todo-new")?.focus());
});
