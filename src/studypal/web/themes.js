"use strict";

// Colour themes. "system" follows the computer's light or dark mode (the colours in app.css); every other
// theme sets the same colour tokens itself. Most palettes match the terminal app's themes, including
// eight subject accents: a subject on one of the default colours is drawn in the theme's matching
// shade, so a blue subject stays blue but becomes Nord blue. A colour that isn't one of the defaults
// is always kept.

const COURSE_COLORS = ["#5b8def", "#e07a5f", "#3ba99c", "#b07fe0", "#d9a930", "#6fae5a", "#e0679a", "#7d8ba3"];

const LIGHT = {
  bg: "#e9eae6", surface: "#fafaf8", surface2: "#f0f1ed", text: "#17191c", muted: "#5d6166", faint: "#969a9e",
  border: "#dcded9", track: "#e3e5e0", accent: "#17191c", warn: "#b06d08", danger: "#c4202f", ok: "#1f7546",
};
const DARK = {
  bg: "#19191b", surface: "#242527", surface2: "#2c2d30", text: "#ecebe6", muted: "#a6a59f", faint: "#706f6b",
  border: "#3a3b3d", track: "#343537", accent: "#ecebe6", warn: "#e3a43a", danger: "#f0625c", ok: "#62c48c", dark: true,
};

// ---------- Daylight: colours that follow the time of day ----------
//
// Two ramps of keyframes, one light and one dark, each blended smoothly minute by minute. The light
// ramp runs from a rosy dawn through a bright, cool noon to a warm golden hour and a dim dusk; the dark
// ramp from a purple dusk through deep-blue night (darkest in the small hours) to a rosy pre-dawn. The
// switch between them is a step at DAYLIGHT_SWITCH, never a blend: halfway between a light and a dark
// background is a mid-grey that no text reads well on.

const DAYLIGHT_SWITCH = { lightFrom: 6 * 60 + 30, darkFrom: 20 * 60 + 30 };  // 06:30 and 20:30

const DAYLIGHT_LIGHT = [  // [minutes after midnight, colours]
  [6 * 60 + 30, { bg: "#f3e6e3", surface: "#fbf3f1", surface2: "#f6ebe8", border: "#e6d3cf", track: "#ecdcd8",
    text: "#2a2026", muted: "#6a5960", faint: "#a6959b", accent: "#b44d70", warn: "#b5741a", danger: "#c2393f", ok: "#3a8a5c" }],
  [9 * 60, { bg: "#eef3f2", surface: "#fbfdfc", surface2: "#f4f8f7", border: "#dbe5e3", track: "#e2eae8",
    text: "#1c2427", muted: "#617079", faint: "#97a3aa", accent: "#197887", warn: "#b5781a", danger: "#c43b3b", ok: "#2f8a5a" }],
  [13 * 60, { bg: "#f1f4f9", surface: "#ffffff", surface2: "#f7f9fc", border: "#e0e5ee", track: "#e5eaf2",
    text: "#1a1f29", muted: "#626a77", faint: "#99a0ac", accent: "#3a66de", warn: "#c08414", danger: "#cf3f3f", ok: "#2f8f5e" }],
  [17 * 60, { bg: "#f5f0e6", surface: "#fffcf6", surface2: "#faf5ec", border: "#e7dfce", track: "#ebe4d5",
    text: "#27231c", muted: "#665d50", faint: "#a39a8b", accent: "#9a5c14", warn: "#b5741a", danger: "#c43f33", ok: "#3f8a4f" }],
  [19 * 60 + 30, { bg: "#eddaca", surface: "#f7eadc", surface2: "#f1e2d2", border: "#ddc6b0", track: "#e3cfbb",
    text: "#2e2219", muted: "#6a5646", faint: "#a48e7a", accent: "#a94f20", warn: "#a86b14", danger: "#bb3a2e", ok: "#4a7f3e" }],
  [20 * 60 + 30, { bg: "#ddcfcb", surface: "#eadfdb", surface2: "#e3d7d3", border: "#cbbab5", track: "#d4c5c0",
    text: "#281f23", muted: "#5b4d53", faint: "#94858b", accent: "#93496d", warn: "#97621a", danger: "#ad3a3f", ok: "#45774f" }],
];

const DAYLIGHT_DARK = [  // minutes counted from 20:30, wrapping past midnight
  [20 * 60 + 30, { bg: "#2a2433", surface: "#342d40", surface2: "#3a3347", border: "#4a4158", track: "#463d54",
    text: "#efe7f0", muted: "#b6abbe", faint: "#82778c", accent: "#e88db4", warn: "#f0b45a", danger: "#f27c7c", ok: "#7fd1a0" }],
  [23 * 60, { bg: "#161a2b", surface: "#1e2336", surface2: "#242a3f", border: "#2f3650", track: "#2c334b",
    text: "#dfe4f2", muted: "#9ea7c0", faint: "#69728c", accent: "#8aa4ff", warn: "#e8b05a", danger: "#f07a80", ok: "#6fcf98" }],
  [24 * 60 + 3 * 60, { bg: "#0e111e", surface: "#151928", surface2: "#1a1f30", border: "#252b40", track: "#22283c",
    text: "#d0d5e3", muted: "#8c94aa", faint: "#5b637c", accent: "#7a8cd6", warn: "#d3a254", danger: "#df7076", ok: "#63b98a" }],
  [24 * 60 + 5 * 60 + 30, { bg: "#1d1b2c", surface: "#262337", surface2: "#2c2940", border: "#3a3550", track: "#36314b",
    text: "#e3ddeb", muted: "#a9a1b9", faint: "#746c86", accent: "#c79ae0", warn: "#e9b25c", danger: "#ee7d86", ok: "#78cfa0" }],
  [24 * 60 + 6 * 60 + 30, { bg: "#2b2333", surface: "#352c3e", surface2: "#3b3245", border: "#4b4056", track: "#473c52",
    text: "#efe5ec", muted: "#b9aab6", faint: "#857784", accent: "#ec9cac", warn: "#f0b45a", danger: "#f27c7c", ok: "#7fd1a0" }],
];

function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}
function mixHex(a, b, t) {
  const x = hexToRgb(a), y = hexToRgb(b);
  return rgbToHex(x.map((v, i) => v + (y[i] - v) * t));
}

// Daylight's colours at a given moment.
function daylightAt(date = new Date()) {
  let m = date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;
  const light = m >= DAYLIGHT_SWITCH.lightFrom && m < DAYLIGHT_SWITCH.darkFrom;
  const frames = light ? DAYLIGHT_LIGHT : DAYLIGHT_DARK;
  if (!light && m < DAYLIGHT_SWITCH.darkFrom) m += 24 * 60;  // after midnight: continue the evening's ramp
  let i = 0;
  while (i < frames.length - 2 && m >= frames[i + 1][0]) i++;
  const [t0, a] = frames[i], [t1, b] = frames[i + 1];
  const t = Math.min(1, Math.max(0, (m - t0) / (t1 - t0)));
  const out = { dark: !light };
  for (const k of Object.keys(a)) out[k] = mixHex(a[k], b[k], t);
  return out;
}

const THEMES = [
  { name: "system", label: "System", note: "Follows your computer's light or dark mode" },
  { name: "daylight", label: "Daylight", dynamic: true,
    note: "Changes with the time of day: bright and cool at noon, warm in the evening, dark and deep blue at night" },
  { name: "light", label: "Light", ...LIGHT },
  { name: "dark", label: "Dark", ...DARK },
  { name: "gruvbox", label: "Gruvbox dark", dark: true,
    bg: "#1d2021", surface: "#282828", surface2: "#32302f", text: "#ebdbb2", muted: "#a89984", faint: "#7c6f64",
    border: "#3c3836", track: "#3c3836", accent: "#83a598", warn: "#fabd2f", danger: "#fb4934", ok: "#b8bb26",
    accents: ["#83a598", "#fe8019", "#8ec07c", "#d3869b", "#fabd2f", "#b8bb26", "#fb4934", "#a89984"] },
  { name: "gruvbox-light", label: "Gruvbox light",
    bg: "#f2e5bc", surface: "#fbf1c7", surface2: "#f6ebc4", text: "#3c3836", muted: "#7c6f64", faint: "#a89984",
    border: "#e0d0a8", track: "#ebdbb2", accent: "#076678", warn: "#b57614", danger: "#9d0006", ok: "#79740e",
    accents: ["#076678", "#af3a03", "#427b58", "#8f3f71", "#b57614", "#79740e", "#9d0006", "#7c6f64"] },
  { name: "nord", label: "Nord", dark: true,
    bg: "#2e3440", surface: "#3b4252", surface2: "#434c5e", text: "#eceff4", muted: "#b4bccb", faint: "#7b88a1",
    border: "#4c566a", track: "#4c566a", accent: "#88c0d0", warn: "#ebcb8b", danger: "#bf616a", ok: "#a3be8c",
    accents: ["#88C0D0", "#D08770", "#8FBCBB", "#B48EAD", "#EBCB8B", "#A3BE8C", "#BF616A", "#81A1C1"] },
  { name: "dracula", label: "Dracula", dark: true,
    bg: "#21222c", surface: "#282a36", surface2: "#303341", text: "#f8f8f2", muted: "#b6b9d0", faint: "#6272a4",
    border: "#44475a", track: "#44475a", accent: "#bd93f9", warn: "#f1fa8c", danger: "#ff5555", ok: "#50fa7b",
    accents: ["#8BE9FD", "#FFB86C", "#50FA7B", "#BD93F9", "#F1FA8C", "#FF79C6", "#FF5555", "#6272A4"] },
  { name: "catppuccin-mocha", label: "Catppuccin Mocha", dark: true,
    bg: "#11111b", surface: "#1e1e2e", surface2: "#262637", text: "#cdd6f4", muted: "#a6adc8", faint: "#6c7086",
    border: "#313244", track: "#45475a", accent: "#89b4fa", warn: "#f9e2af", danger: "#f38ba8", ok: "#a6e3a1",
    accents: ["#89B4FA", "#FAB387", "#94E2D5", "#CBA6F7", "#F9E2AF", "#A6E3A1", "#F5C2E7", "#9399B2"] },
  { name: "catppuccin-latte", label: "Catppuccin Latte",
    bg: "#e6e9ef", surface: "#eff1f5", surface2: "#e9ecf2", text: "#4c4f69", muted: "#6c6f85", faint: "#9ca0b0",
    border: "#ccd0da", track: "#ccd0da", accent: "#1e66f5", warn: "#df8e1d", danger: "#d20f39", ok: "#40a02b",
    accents: ["#1E66F5", "#FE640B", "#179299", "#8839EF", "#DF8E1D", "#40A02B", "#EA76CB", "#7C7F93"] },
  { name: "tokyo-night", label: "Tokyo Night", dark: true,
    bg: "#16161e", surface: "#1a1b26", surface2: "#202230", text: "#c0caf5", muted: "#9aa5ce", faint: "#565f89",
    border: "#292e42", track: "#292e42", accent: "#7aa2f7", warn: "#e0af68", danger: "#f7768e", ok: "#9ece6a",
    accents: ["#7AA2F7", "#FF9E64", "#73DACA", "#BB9AF7", "#E0AF68", "#9ECE6A", "#F7768E", "#A9B1D6"] },
  { name: "solarized-dark", label: "Solarized dark", dark: true,
    bg: "#00212b", surface: "#002b36", surface2: "#073642", text: "#e3dcc8", muted: "#93a1a1", faint: "#657b83",
    border: "#0d4552", track: "#073642", accent: "#268bd2", warn: "#b58900", danger: "#dc322f", ok: "#859900",
    accents: ["#268bd2", "#cb4b16", "#2aa198", "#6c71c4", "#b58900", "#859900", "#d33682", "#93a1a1"] },
  { name: "solarized-light", label: "Solarized light",
    bg: "#eee8d5", surface: "#fdf6e3", surface2: "#f6f0dc", text: "#073642", muted: "#586e75", faint: "#93a1a1",
    border: "#e0d9c4", track: "#eee8d5", accent: "#268bd2", warn: "#b58900", danger: "#dc322f", ok: "#859900",
    accents: ["#268bd2", "#cb4b16", "#2aa198", "#6c71c4", "#b58900", "#859900", "#d33682", "#586e75"] },
  { name: "rose-pine", label: "Rosé Pine", dark: true,
    bg: "#191724", surface: "#1f1d2e", surface2: "#26233a", text: "#e0def4", muted: "#908caa", faint: "#6e6a86",
    border: "#403d52", track: "#26233a", accent: "#c4a7e7", warn: "#f6c177", danger: "#eb6f92", ok: "#9ccfd8",
    accents: ["#9ccfd8", "#f6c177", "#3e8fb0", "#c4a7e7", "#ea9a97", "#a3be8c", "#eb6f92", "#908caa"] },
  { name: "one-dark", label: "One Dark", dark: true,
    bg: "#21252b", surface: "#282c34", surface2: "#2f343e", text: "#dcdfe4", muted: "#abb2bf", faint: "#5c6370",
    border: "#3a3f4b", track: "#3a3f4b", accent: "#61afef", warn: "#e5c07b", danger: "#e06c75", ok: "#98c379",
    accents: ["#61AFEF", "#D19A66", "#56B6C2", "#C678DD", "#E5C07B", "#98C379", "#E06C75", "#ABB2BF"] },
  { name: "monokai", label: "Monokai", dark: true,
    bg: "#1e1f1c", surface: "#272822", surface2: "#2f302a", text: "#f8f8f2", muted: "#cfcfc2", faint: "#75715e",
    border: "#3e3d32", track: "#49483e", accent: "#66d9ef", warn: "#e6db74", danger: "#f92672", ok: "#a6e22e",
    accents: ["#66D9EF", "#FD971F", "#A6E22E", "#AE81FF", "#E6DB74", "#F92672", "#FD5FF0", "#75715E"] },
];

const THEMES_BY_NAME = Object.fromEntries(THEMES.map((t) => [t.name, t]));
let activeTheme = THEMES[0];

// The theme as it looks right now: "system" resolves to light or dark.
function resolvedTheme(theme = activeTheme, at = new Date()) {
  if (theme.dynamic) return daylightAt(at);
  if (theme.name !== "system") return theme;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? DARK : LIGHT;
}

// The colour to draw a subject in under the active theme.
function cc(color) {
  const i = COURSE_COLORS.indexOf(String(color || "").toLowerCase());
  return i >= 0 && activeTheme.accents ? activeTheme.accents[i] : color;
}

function applyTheme(name, at = new Date()) {
  const theme = THEMES_BY_NAME[name] || THEMES[0];
  activeTheme = theme;
  const root = document.documentElement;
  root.dataset.theme = theme.name;
  const tokens = ["bg", "surface", "surface-2", "text", "muted", "faint", "border", "track", "accent", "accent-text",
    "accent-soft", "warn", "warn-soft", "danger", "danger-soft", "ok", "ok-soft", "shadow"];
  if (theme.name === "system") {
    tokens.forEach((t) => root.style.removeProperty(`--${t}`));
    root.style.removeProperty("color-scheme");
    return;
  }
  const t = resolvedTheme(theme, at);
  const soft = (c) => `color-mix(in srgb, ${c} ${t.dark ? 22 : 15}%, ${t.surface})`;
  const values = {
    bg: t.bg, surface: t.surface, "surface-2": t.surface2, text: t.text, muted: t.muted, faint: t.faint,
    border: t.border, track: t.track, accent: t.accent, "accent-text": t.dark ? t.bg : "#ffffff",
    "accent-soft": soft(t.accent), warn: t.warn, "warn-soft": soft(t.warn), danger: t.danger,
    "danger-soft": soft(t.danger), ok: t.ok, "ok-soft": soft(t.ok),
    shadow: t.dark ? "0 1px 2px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.2)"
      : "0 1px 2px rgba(20,20,30,.05), 0 4px 16px rgba(20,20,30,.05)",
  };
  for (const [k, v] of Object.entries(values)) root.style.setProperty(`--${k}`, v);
  root.style.setProperty("color-scheme", t.dark ? "dark" : "light");
}

// A small picture of a theme for the picker: its background, a card, and a few of its colours.
function themePreview(theme) {
  const t = resolvedTheme(theme);
  const dots = (theme.accents || COURSE_COLORS).slice(0, 4).map((c) => `<i style="background:${c}"></i>`).join("");
  const day = (h) => daylightAt(new Date(2000, 0, 1, Math.floor(h), Math.round((h % 1) * 60))).bg;
  const sys = theme.name === "system"
    ? `<span class="tp-split" style="background:linear-gradient(135deg, ${LIGHT.bg} 50%, ${DARK.bg} 50%)"></span>`
    : theme.dynamic  // the whole day, from dawn to the small hours
      ? `<span class="tp-split" style="background:linear-gradient(90deg, ${[7, 10, 13, 17, 19.7, 21, 23, 3].map(day).join(", ")})"></span>` : "";
  return `<span class="tp" style="background:${t.bg};border-color:${t.border}">${sys}
    <span class="tp-card" style="background:${t.surface};border-color:${t.border}">
      <span class="tp-line" style="background:${t.text}"></span>
      <span class="tp-bar" style="background:${t.track}"><span style="background:${t.accent}"></span></span>
      <span class="tp-dots">${dots}</span>
    </span></span>`;
}

// Daylight moves on by itself: refresh its colours every minute while it's in use.
setInterval(() => { if (activeTheme.dynamic) applyTheme(activeTheme.name); }, 60000);

// ---------- font and text size ----------
// Chosen in Settings and kept per computer like the theme. The size scales every piece of text (app.css
// sets them in rem); the big condensed figures keep their own face.

const FONTS = [
  ["source", "Source Sans 3", '"Source Sans 3", -apple-system, "Segoe UI", system-ui, sans-serif', "Made for reading on screens"],
  ["atkinson", "Atkinson Hyperlegible", '"Atkinson Hyperlegible Next", -apple-system, "Segoe UI", sans-serif',
    "Made for low vision: every letter and digit distinct (zeros are slashed)"],
  ["system", "System font", '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif', "The computer's own (San Francisco on a Mac)"],
  ["serif", "Serif", 'Charter, "Iowan Old Style", Georgia, "Times New Roman", serif', "Like a printed book"],
];
const TEXT_SIZES = [["small", "Small", 0.92], ["normal", "Normal", 1], ["large", "Large", 1.12], ["larger", "Larger", 1.25]];

let activeType = { font: "source", size: "normal" };

function applyType(type) {
  const font = FONTS.find(([k]) => k === type.font) || FONTS[0];
  const size = TEXT_SIZES.find(([k]) => k === type.size) || TEXT_SIZES[1];
  activeType = { font: font[0], size: size[0] };
  document.documentElement.style.setProperty("--sans", font[2]);
  document.documentElement.style.fontSize = `${16 * size[2]}px`;
}
