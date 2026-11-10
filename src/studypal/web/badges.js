// Collectible badges, earned by studying (see core/logic/badges.py). They live in the sidebar, out of the way:
// its "Badges" item lists every badge with what it takes and how close you are. They're loaded with the
// sidebar after each change, so a badge you've just earned gets a toast once, whichever page you're on.

function badgeMedal(b) {
  const tip = b.earned ? `${b.name}: ${b.description}` : `${b.name} (not yet): ${b.description}`;
  return `<span class="medal${b.earned ? "" : " locked"}${b.tier ? ` tier-${b.tier}` : ""}" title="${esc(tip)}" role="img" aria-label="${esc(tip)}">
      <span aria-hidden="true">${b.icon}</span></span>`;
}

let sideBadges = null;  // the collection, as last loaded for the sidebar

// The sidebar's "Badges" item, at the bottom above the account. It opens the full list.
function renderSideBadges() {
  const b = sideBadges, el = $("#side-badges");
  if (!b) { el.innerHTML = ""; return; }
  el.innerHTML = `<button class="side-item" data-act="badges" title="Badges: ${b.earned} of ${b.total} collected">
      <span class="side-badge plain side-medal" aria-hidden="true">🏅</span>
      <span class="side-text"><span class="side-label">Badges</span><span class="side-sub">${b.earned} of ${b.total} collected</span></span></button>`;
}

async function loadBadges() {
  try { sideBadges = await call("badges"); } catch (e) { return; }  // keep what's shown
  renderSideBadges();
  announceBadges(sideBadges);
}

function badgeRow(b) {
  const status = b.earned
    ? `<span class="badge-earned">${b.earned_label ? `Earned ${esc(b.earned_label)}` : "Earned"}</span>`
    : b.target > 1
      ? `<span class="badge-progress"><span class="badge-track"><span style="width:${Math.round((100 * b.current) / b.target)}%"></span></span>${b.current} / ${b.target}</span>`
      : `<span class="badge-progress">Not yet</span>`;
  return `<li class="badge-row${b.earned ? "" : " locked"}">${badgeMedal(b)}
      <div class="grow"><div class="title">${esc(b.name)}</div><div class="sub">${esc(b.description)}</div></div>
      ${status}</li>`;
}

function showBadges() {
  const b = sideBadges;
  if (!b) return;
  $("#modal-root").innerHTML = `<div class="backdrop">
    <div class="modal wide" role="dialog" aria-modal="true" aria-labelledby="badges-title">
      <h3 id="badges-title">Badges</h3>
      <p class="intro">You've collected ${b.earned} of ${b.total}. They're earned by studying, and time you logged before counts too.</p>
      <ul class="badge-list">${b.items.map(badgeRow).join("")}</ul>
      <div class="modal-actions"><button type="button" class="btn primary" data-modal="close">Done</button></div>
    </div></div>`;
  modalClose = closeModal;
  const root = $("#modal-root .backdrop");
  root.addEventListener("mousedown", (e) => { if (e.target === root) closeModal(); });
  $("[data-modal=close]", root).addEventListener("click", closeModal);
  $("[data-modal=close]", root).focus();
}

// Toast the badges earned since last time, then remember they've been shown.
const announcedBadges = new Set();  // so two quick refreshes don't both announce the same badge

async function announceBadges(badges) {
  const fresh = badges ? badges.items.filter((b) => badges.new.includes(b.id) && !announcedBadges.has(b.id)) : [];
  if (!fresh.length) return;
  fresh.forEach((b) => announcedBadges.add(b.id));
  if (fresh.length === 1) toast(`${fresh[0].icon} New badge: ${fresh[0].name}!`);
  else toast(`🏅 ${fresh.length} new badges! Open Badges in the sidebar to see them.`);
  try { await call("badges_seen", fresh.map((b) => b.id)); } catch (e) { /* it'll be announced again next time */ }
}

Object.assign(actions, { badges: () => showBadges() });
