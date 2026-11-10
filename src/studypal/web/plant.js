// The study plant on the overview (see core/logic/plant.py). It stands straight and flowers when you're
// ahead of schedule, droops more the further behind you fall, and grows a leaf pair as more topics are done.

// How far the leaves hang (degrees below pointing up and out) and how far the stem's tip bends over.
const PLANT_POSE = {
  seed: { droop: 0, bend: 0 },
  blooming: { droop: 0, bend: 0 },
  healthy: { droop: 6, bend: 2 },
  thirsty: { droop: 38, bend: 9 },
  wilting: { droop: 70, bend: 22 },
  withered: { droop: 100, bend: 34 },
};

function plantSvg(p) {
  const pose = PLANT_POSE[p.health] || PLANT_POSE.healthy;
  const seed = p.health === "seed";
  const leaves = seed ? 1 : p.leaves;
  const baseX = 60, baseY = 110;
  const height = seed ? 16 : 26 + leaves * 11;
  // The stem is a curve whose tip bends over and sinks a little as the plant wilts.
  const tip = [baseX + pose.bend, baseY - height + pose.bend * 0.45];
  const ctrl = [baseX - pose.bend * 0.15, baseY - height * 0.7];
  const along = (t) => [
    (1 - t) ** 2 * baseX + 2 * (1 - t) * t * ctrl[0] + t * t * tip[0],
    (1 - t) ** 2 * baseY + 2 * (1 - t) * t * ctrl[1] + t * t * tip[1],
  ];
  const leaf = "M0 0 Q11 -8 24 0 Q11 8 0 0Z";
  const leafEls = [];
  for (let i = 0; i < leaves; i++) {
    // Pairs from low on the stem to near the top; smaller towards the top.
    const t = seed ? 1 : 0.22 + (0.72 * i) / Math.max(1, leaves - 1);
    const [x, y] = along(Math.min(t, 0.94));
    const size = seed ? 0.6 : 1 - 0.35 * (i / Math.max(1, leaves));
    for (const side of [1, -1]) {
      const angle = -40 + pose.droop;
      leafEls.push(`<path class="plant-leaf" d="${leaf}" transform="translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${side * size} ${size}) rotate(${angle})"/>`);
    }
  }
  const flower = p.health === "blooming"
    ? `<g class="plant-flower" transform="translate(${tip[0].toFixed(1)} ${tip[1].toFixed(1)})">
        ${[0, 72, 144, 216, 288].map((a) => `<ellipse rx="5" ry="8" transform="rotate(${a}) translate(0 -7)"/>`).join("")}
        <circle class="plant-heart" r="4"/></g>` : "";
  const fallen = p.health === "withered" || p.health === "wilting"
    ? `<path class="plant-leaf fallen" d="${leaf}" transform="translate(${p.health === "withered" ? 36 : 72} 109) scale(0.7) rotate(${p.health === "withered" ? 8 : -6})"/>` : "";
  const stem = seed ? "" : `<path class="plant-stem" d="M${baseX} ${baseY} Q${ctrl[0].toFixed(1)} ${ctrl[1].toFixed(1)} ${tip[0].toFixed(1)} ${tip[1].toFixed(1)}"/>`;
  return `<svg class="plant-svg" viewBox="0 0 120 140" role="img" aria-label="${esc(p.words)}">
      <path class="plant-pot" d="M30 112 H90 L84 138 H36 Z"/>
      <rect class="plant-rim" x="27" y="108" width="66" height="8" rx="2"/>
      <ellipse class="plant-soil" cx="60" cy="110" rx="29" ry="3"/>
      <g class="plant-sway">${stem}${leafEls.join("")}${flower}</g>
      ${fallen}
    </svg>`;
}

function plantPanel(o) {
  if (!o || !o.plant) return "";
  const p = o.plant;
  return `<div class="panel plant-panel plant-${p.health}">
      <div class="section-head"><h2>Your plant</h2></div>
      <div class="plant-body">${plantSvg(p)}<p>${esc(p.words)}</p></div>
    </div>`;
}
