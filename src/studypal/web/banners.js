// Course banners: a sign made from the course (its code set large on its colour, over a faint pattern its
// code and name pick), or a picture of your own. course.banner is "" or "gen:<n>" for a pattern (n picks
// another one), else the key of the picture, fetched once and kept here.

const bannerImages = {};  // key -> data URL ("" while it hasn't arrived on this computer)

function bannerSeed(text) {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return h;
}

function bannerRandom(seed) {  // mulberry32: the same course always draws the same banner
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function bannerVariant(c) {
  const m = /^gen:(\d+)$/.exec(c.banner || "");
  return m ? Number(m[1]) : 0;
}

function generatedBanner(c) {
  const variant = bannerVariant(c);
  const rnd = bannerRandom(bannerSeed(`${c.code}|${c.name}|${variant}`));
  const color = esc(cc(c.color));
  const W = 1200, H = 200;
  const style = Math.floor(rnd() * 5);
  let shapes = "";
  if (style === 0) {  // soft waves
    for (let i = 0; i < 6; i++) {
      const y = 30 + i * 30 + rnd() * 20, a = 14 + rnd() * 26, p = rnd() * W;
      let d = `M0 ${y}`;
      for (let x = 0; x <= W; x += 40) d += ` L${x} ${(y + a * Math.sin((x + p) / (90 + i * 20))).toFixed(1)}`;
      shapes += `<path d="${d}" fill="none" stroke="#fff" stroke-opacity="${(0.1 + rnd() * 0.12).toFixed(2)}" stroke-width="${(1.5 + rnd() * 2.5).toFixed(1)}"/>`;
    }
  } else if (style === 1) {  // circles
    for (let i = 0; i < 14; i++) {
      shapes += `<circle cx="${(rnd() * W).toFixed(0)}" cy="${(rnd() * H).toFixed(0)}" r="${(12 + rnd() * 90).toFixed(0)}"
        fill="#fff" fill-opacity="${(0.04 + rnd() * 0.08).toFixed(2)}"/>`;
    }
  } else if (style === 2) {  // dot grid fading to the right
    for (let x = 20; x < W; x += 28) for (let y = 14; y < H; y += 28) {
      const o = (x / W) * 0.3 * (0.4 + rnd() * 0.6);
      shapes += `<circle cx="${x}" cy="${y}" r="2.4" fill="#fff" fill-opacity="${o.toFixed(2)}"/>`;
    }
  } else if (style === 3) {  // diagonal bands
    for (let i = 0; i < 9; i++) {
      const x = rnd() * W * 1.2 - 100, w = 20 + rnd() * 90;
      shapes += `<polygon points="${x},${H} ${x + w},${H} ${x + w + 160},0 ${x + 160},0" fill="#fff" fill-opacity="${(0.04 + rnd() * 0.08).toFixed(2)}"/>`;
    }
  } else {  // triangles
    for (let i = 0; i < 18; i++) {
      const x = rnd() * W, y = rnd() * H, s = 16 + rnd() * 60, r = rnd() * 360;
      shapes += `<polygon points="0,${-s} ${s * 0.87},${s / 2} ${-s * 0.87},${s / 2}" transform="translate(${x.toFixed(0)} ${y.toFixed(0)}) rotate(${r.toFixed(0)})"
        fill="#fff" fill-opacity="${(0.04 + rnd() * 0.08).toFixed(2)}"/>`;
    }
  }
  // The course code, set large like a route sign and cropped by the edge; the pattern stays a faint texture.
  const left = rnd() < 0.5;
  const code = esc(String(c.code).toUpperCase());
  return `<svg class="banner-art" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <rect width="${W}" height="${H}" fill="${color}"/>
    <g opacity=".55">${shapes}</g>
    <text x="${left ? 28 : W - 28}" y="${H - 4}" text-anchor="${left ? "start" : "end"}" font-family="Barlow Condensed, Arial Narrow, sans-serif"
      font-weight="700" font-size="190" letter-spacing="-3" fill="#fff" fill-opacity=".9">${code}</text></svg>`;
}

const isPictureBanner = (c) => !!c.banner && !c.banner.startsWith("gen:");

// The banner for a course: `size` is "card" (a strip on the overview) or "page" (the subject page, with a
// button to change it).
function courseBanner(c, size = "page") {
  const picture = isPictureBanner(c);
  const url = picture ? bannerImages[c.banner] : "";
  return `<div class="course-banner on-${size}" style="--course:${esc(cc(c.color))}">
    ${generatedBanner(c)}
    ${picture ? `<img class="banner-img" alt="" data-banner-key="${esc(c.banner)}"${url ? ` src="${url}"` : " hidden"}>` : ""}
    ${size === "page" ? `<button class="btn small banner-change" data-act="banner-menu" data-id="${c.id}">Change banner</button>` : ""}
  </div>`;
}

// Fill in pictures that weren't loaded yet when the page was drawn.
async function loadBannerImages() {
  const imgs = [...document.querySelectorAll("img[data-banner-key][hidden]")];
  for (const key of new Set(imgs.map((i) => i.dataset.bannerKey))) {
    if (!(key in bannerImages)) {
      bannerImages[key] = "";
      try { bannerImages[key] = (await call("banner_image", key)).url || ""; } catch (e) { /* keeps the pattern */ }
      if (!bannerImages[key]) setTimeout(() => delete bannerImages[key], 30000);  // may arrive with the next sync
    }
    if (bannerImages[key]) document.querySelectorAll(`img[data-banner-key="${CSS.escape(key)}"]`).forEach((i) => { i.src = bannerImages[key]; i.hidden = false; });
  }
}
const bannersAfterRender = afterRender;
afterRender = () => { bannersAfterRender(); loadBannerImages(); };

function pickBannerInBrowser() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    // On the iPhone, "image/*" makes iOS hand over a JPEG (it can't convert HEIC in the browser).
    input.accept = document.documentElement.classList.contains("phone-app") ? "image/*" : ".png,.jpg,.jpeg,.webp,.heic,.heif";
    input.addEventListener("change", () => {
      const f = input.files[0];
      if (!f) return resolve(null);
      const r = new FileReader();
      r.onload = () => resolve({ name: f.name, data: String(r.result).split(",")[1] || "" });
      r.readAsDataURL(f);
    });
    input.click();
  });
}

Object.assign(actions, {
  "banner-menu": (el) => {
    const id = Number(el.dataset.id), c = state.data.course;
    const picture = isPictureBanner(c);
    openMenu(el, [
      { label: "Choose a picture…", onClick: async () => {
        try {
          const r = await call("choose_banner_image");
          const picked = r.browser ? await pickBannerInBrowser() : (r.path ? { path: r.path } : null);
          if (!picked) return;
          toast("Adding the picture…");
          await act("set_course_banner", id, picked);
        } catch (e) { toast(e.message, true); }
      } },
      { label: picture ? "Use a pattern instead" : "Another pattern", onClick: () =>
        act("set_course_banner", id, { generated: picture ? bannerVariant(c) : bannerVariant(c) + 1 }) },
      ...(!picture && bannerVariant(c) ? [{ label: "Back to the first pattern", onClick: () => act("set_course_banner", id, {}) }] : []),
    ]);
  },
});
