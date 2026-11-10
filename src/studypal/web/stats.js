// The Statistics page: your study habits from all the time you've logged (see core/logic/habits.py).
// Figures up top, then charts: the last 12 weeks, every day of the last half year, when in the day and
// week you study, and what on. Every chart shows its values on hover and keyboard focus, and has a table.

const STATS_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>';

// A chart mark that shows its value on hover and focus: the value leads, the label follows.
const tipAttrs = (value, label) => `tabindex="0" data-tip-value="${esc(value)}" data-tip-label="${esc(label)}" aria-label="${esc(`${label}: ${value}`)}"`;

// Clean hour ticks for an axis reaching `max` minutes: [0, step, 2·step, ...] in minutes.
function hourTicks(max) {
  const hours = max / 60;
  const step = [0.5, 1, 2, 5, 10, 20, 50].find((s) => hours / s <= 4) || 100;
  const top = Math.max(step, Math.ceil(hours / step) * step);
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step * 60);
}

const tickLabel = (m) => (m === 0 ? "0" : m < 60 ? `${m}m` : `${+(m / 60).toFixed(1)}h`);

// Columns from one baseline, with hairline gridlines at clean hour ticks. `cols`: [{label, minutes, length,
// tip, strong, axis}] — `axis` is the text under the column ("" to leave it out), `strong` marks the column the
// story is about (drawn in the full ink; the others are quieter) and gets its value printed on its cap.
function columnChart(cols, { height = 150, labelEvery = 1 } = {}) {
  const ticks = hourTicks(Math.max(1, ...cols.map((c) => c.minutes)));
  const top = ticks[ticks.length - 1];
  const grid = ticks.map((t) => `<div class="cc-grid" style="bottom:${(100 * t) / top}%"><span>${tickLabel(t)}</span></div>`).join("");
  const bars = cols.map((c, i) => {
    const h = (100 * c.minutes) / top;
    return `<div class="cc-col${c.strong ? " strong" : ""}" ${tipAttrs(c.length || "0m", c.tip)}>
        ${c.strong && c.minutes ? `<span class="cc-value" style="bottom:${h}%">${esc(c.length)}</span>` : ""}
        <span class="cc-bar" style="height:${h}%"></span>
        <span class="cc-label">${i % labelEvery === 0 ? esc(c.axis ?? c.label) : ""}</span></div>`;
  }).join("");
  return `<div class="cc" style="--plot:${height}px"><div class="cc-plot">${grid}<div class="cc-cols">${bars}</div></div></div>`;
}

function tableView(headers, rows) {
  return `<details class="table-view"><summary>Show as table</summary>
    <table><thead><tr>${headers.map((h, i) => `<th${i ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((v, i) => `<td${i ? ' class="num"' : ""}>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></details>`;
}

function statTile(label, value, sub = "", delta = "") {
  return `<div class="stat-tile"><span class="stat-label">${esc(label)}</span><span class="stat-value">${esc(value)}</span>
    ${delta}${sub ? `<span class="stat-sub">${esc(sub)}</span>` : ""}</div>`;
}

function weekDelta(d) {
  if (d.week_change === null) return "";
  const up = d.week_change >= 0;
  return `<span class="stat-delta ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(d.week_change)}% <span>vs last week by now</span></span>`;
}

// The calendar of every day: a column per week, a row per weekday, darker for more study time.
const HEAT_BINS = [[0, "None"], [1, "Under 30m"], [30, "30m–1h"], [60, "1–2h"], [120, "2h or more"]];
const heatLevel = (m) => HEAT_BINS.reduce((lvl, [from], i) => (m >= from ? i : lvl), 0);

function heatmap(d) {
  const weeks = [];
  d.days.forEach((x, i) => { (weeks[Math.floor(i / 7)] ||= []).push(x); });
  const months = weeks.map((w, i) => {
    const first = w[0].label.split(" ");
    const prev = i ? weeks[i - 1][0].label.split(" ")[2] : null;
    return `<span>${first[2] !== prev ? esc(first[2]) : ""}</span>`;
  }).join("");
  const dayNames = d.weekdays.map((w, i) => `<span>${i % 2 === 0 ? esc(w.label) : ""}</span>`).join("");
  const cols = weeks.map((w) => `<div class="heat-week">${w.map((x) =>
    `<span class="heat-cell l${heatLevel(x.minutes)}${x.today ? " is-today" : ""}" ${tipAttrs(x.minutes ? x.length : "Nothing", x.label)}></span>`).join("")}</div>`).join("");
  const legend = HEAT_BINS.map(([, label], i) => `<span class="heat-key"><span class="heat-cell l${i}"></span>${esc(label)}</span>`).join("");
  return `<div class="heat-wrap"><div class="heat">
      <div class="heat-months" style="grid-template-columns:repeat(${weeks.length}, var(--cell))">${months}</div>
      <div class="heat-body"><div class="heat-days">${dayNames}</div><div class="heat-grid">${cols}</div></div>
    </div></div><div class="heat-legend">${legend}</div>`;
}

function subjectBars(d) {
  const max = Math.max(1, ...d.subjects.map((s) => s.minutes));
  const total = d.subjects.reduce((n, s) => n + s.minutes, 0) || 1;
  return `<ul class="hbars">${d.subjects.map((s) => {
    const color = s.research ? "var(--research)" : cc(s.color);
    return `<li ${tipAttrs(s.length, `${s.label} · ${Math.round((100 * s.minutes) / total)}% of your time`)}>
      <span class="hb-name"><i style="background:${esc(color)}"></i>${esc(s.label)}</span>
      <span class="hb-track"><span class="hb-bar" style="width:${(100 * s.minutes) / max}%;background:${esc(color)}"></span></span>
      <span class="hb-value">${esc(s.length)}</span></li>`;
  }).join("")}</ul>`;
}

function renderStats(d) {
  const head = `<div class="stats-head"><h1>Statistics</h1>
    <p class="muted">From all the study time you've logged, for subjects and research projects alike.</p></div>`;
  if (d.empty) {
    return `<div class="stats-page">${head}<div class="panel panel-body"><p class="empty-small">Log some study time, and your
      study habits show up here: how much you study, your streaks, and when and what you study.</p></div></div>`;
  }
  const streakSub = d.current_streak && !d.studied_today ? "Study today to keep it going" : `Longest: ${d.longest_streak} day${d.longest_streak !== 1 ? "s" : ""}`;
  const t = d.todos;
  const tiles = `<div class="stat-tiles">
    ${statTile("Studied in total", d.total, `${d.sessions} sessions on ${d.study_days} days`)}
    ${statTile("This week", d.this_week, "", weekDelta(d))}
    ${statTile("Streak", `${d.current_streak} day${d.current_streak !== 1 ? "s" : ""}`, streakSub)}
    ${statTile("Average session", d.average_session, `Longest: ${d.longest_session}`)}
    ${statTile("To-dos done this week", t.week ? `${t.done_week} of ${t.week}` : "None yet",
      t.month ? `${Math.round((100 * t.done_month) / t.month)}% done in the last 30 days` : "Plan your days on the To-do page")}
  </div>`;

  const peakWeek = d.weeks.reduce((a, b) => (b.minutes > a.minutes ? b : a));
  const weeks = columnChart(d.weeks.map((w) => ({ ...w, tip: `Week of ${w.label}${w.current ? " (this week)" : ""}`,
    axis: w.current ? "This week" : w.label, strong: w.current || w === peakWeek })), { labelEvery: 1 });
  const peakHour = d.hours.reduce((a, b) => (b.minutes > a.minutes ? b : a));
  const hourName = (h) => `${String(h).padStart(2, "0")}:00`;
  const hours = columnChart(d.hours.map((h) => ({ ...h, label: hourName(h.hour), axis: h.hour % 6 === 0 ? hourName(h.hour) : "",
    tip: `${hourName(h.hour)}–${hourName((h.hour + 1) % 24)}`, strong: h === peakHour })), { height: 120 });
  const peakDay = d.weekdays.reduce((a, b) => (b.minutes > a.minutes ? b : a));
  const weekdays = columnChart(d.weekdays.map((w) => ({ ...w, tip: w.long, strong: w === peakDay })), { height: 120 });

  return `<div class="stats-page">${head}${tiles}
    <div class="stats-grid">
      <section class="panel chart-card wide">
        <div class="section-head"><h2>Study time, last 12 weeks</h2></div>
        <div class="panel-body">${weeks}${tableView(["Week of", "Study time"], d.weeks.map((w) => [w.label, w.length]))}</div>
      </section>
      <section class="panel chart-card wide">
        <div class="section-head"><h2>Every day, last 6 months</h2></div>
        <div class="panel-body">${heatmap(d)}${tableView(["Day", "Study time"], d.days.filter((x) => x.minutes).map((x) => [x.label, x.length]))}</div>
      </section>
      <section class="panel chart-card">
        <div class="section-head"><h2>Time of day</h2></div>
        <div class="panel-body"><p class="chart-note">You study most around <b>${hourName(peakHour.hour)}</b>.</p>
          ${hours}${tableView(["Hour", "Study time"], d.hours.filter((h) => h.minutes).map((h) => [`${hourName(h.hour)}–${hourName((h.hour + 1) % 24)}`, h.length]))}</div>
      </section>
      <section class="panel chart-card">
        <div class="section-head"><h2>Day of the week</h2></div>
        <div class="panel-body"><p class="chart-note">Your biggest day is <b>${esc(peakDay.long)}</b>.</p>
          ${weekdays}${tableView(["Day", "Study time"], d.weekdays.map((w) => [w.long, w.length]))}</div>
      </section>
      <section class="panel chart-card wide">
        <div class="section-head"><h2>What you study</h2></div>
        <div class="panel-body">${subjectBars(d)}${tableView(["Subject", "Study time"], d.subjects.map((s) => [s.label, s.length]))}</div>
      </section>
    </div></div>`;
}

VIEWS.stats = { load: () => call("statistics"), render: (d) => renderStats(d) };

// ---------- the tooltip, shared by every chart ----------

const chartTip = document.createElement("div");
chartTip.className = "chart-tip";
chartTip.setAttribute("role", "tooltip");
chartTip.hidden = true;
document.body.append(chartTip);

function showTip(el) {
  const value = document.createElement("b"), label = document.createElement("span");
  value.textContent = el.dataset.tipValue;
  label.textContent = el.dataset.tipLabel;
  chartTip.replaceChildren(value, label);
  chartTip.hidden = false;
  const r = el.getBoundingClientRect(), w = chartTip.offsetWidth, h = chartTip.offsetHeight;
  const left = Math.min(innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2));
  const top = r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8;
  chartTip.style.left = `${left}px`;
  chartTip.style.top = `${top}px`;
}

const hideTip = () => { chartTip.hidden = true; };
document.addEventListener("pointerover", (e) => { const el = e.target.closest?.("[data-tip-value]"); if (el) showTip(el); else hideTip(); });
document.addEventListener("focusin", (e) => { const el = e.target.closest?.("[data-tip-value]"); if (el) showTip(el); else hideTip(); });
document.addEventListener("scroll", hideTip, true);
