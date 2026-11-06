// Stands in for pywebview's bridge on the iPhone: the page's calls go to Python running in a Web Worker
// (worker.js), and Python's requests to open a tab, notify or save a file are done here.

(() => {
  const demo = new URLSearchParams(location.search).has("demo");
  const worker = new Worker("worker.js", { type: "module" });
  const waiting = new Map();
  let nextId = 1;

  // Safari only opens a tab straight from a tap, so calls that end in one open it now and fill it in later.
  const OPENS_TAB = new Set(["open_link", "open_exam_file", "save_printable"]);
  let pendingTab = null;

  function show(url) {
    if (pendingTab && !pendingTab.closed) { pendingTab.location = url; pendingTab = null; }
    else window.open(url, "_blank", "noopener");
  }

  function blobUrl(parts, mime) {
    const url = URL.createObjectURL(new Blob(parts, { type: mime }));
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return url;
  }

  let audio;
  function pling() {
    try {
      audio = audio || new AudioContext();
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.2, audio.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.6);
      o.connect(g).connect(audio.destination);
      o.start();
      o.stop(audio.currentTime + 0.6);
    } catch (e) { /* no sound: the toast still says it */ }
  }

  const HOST = {
    open_url: (m) => show(m.url),
    open_html: (m) => show(blobUrl([m.html], "text/html")),
    open_file: (m) => show(blobUrl([Uint8Array.from(atob(m.data), (c) => c.charCodeAt(0))], m.mime)),
    download: (m) => {
      const a = document.createElement("a");
      a.href = blobUrl([m.text], m.mime);
      a.download = m.name;
      a.click();
    },
    notify: (m) => {
      if ("Notification" in window && Notification.permission === "granted") new Notification(m.title, { body: m.body });
    },
    play: () => pling(),
  };

  worker.onerror = (e) => {
    console.error("StudyPal worker:", e.message);
    const view = document.getElementById("view");
    if (view) view.innerHTML = `<p class="loading">StudyPal couldn't start: ${e.message}. Check the connection and reload.</p>`;
  };

  worker.onmessage = (e) => {
    const m = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
    if (m.host) return HOST[m.host] && HOST[m.host](m);
    if (m.step) {
      console.info("StudyPal:", m.step);
      const loading = document.querySelector("#view .loading");
      if (loading) loading.textContent = `${m.step}…`;
      return;
    }
    if (m.ready) { document.documentElement.classList.remove("py-loading"); return; }
    if (m.failed) {
      const view = document.getElementById("view");
      if (view) view.innerHTML = `<p class="loading">StudyPal couldn't start: ${m.failed}. Check the connection and reload.</p>`;
      return;
    }
    const p = waiting.get(m.id);
    if (p) { waiting.delete(m.id); p(JSON.parse(m.result)); }
  };

  function call(name, args) {
    if (OPENS_TAB.has(name)) {
      if (pendingTab && !pendingTab.closed) pendingTab.close();
      pendingTab = window.open("", "_blank");
    }
    const id = nextId++;
    return new Promise((resolve) => { waiting.set(id, resolve); worker.postMessage({ id, name, args }); })
      .then((r) => {
        if (OPENS_TAB.has(name) && r && r.error && pendingTab) { pendingTab.close(); pendingTab = null; }
        return r;
      });
  }

  window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => call(name, args) }) };
  document.documentElement.classList.add("py-loading", "phone-app");
  worker.postMessage({ start: true, demo });

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    // An update replaces the service worker; reload once so the page is the new version too.
    if (navigator.serviceWorker.controller) {
      navigator.serviceWorker.addEventListener("controllerchange", () => location.reload(), { once: true });
    }
    navigator.serviceWorker.register("sw.js", { updateViaCache: "none" }).catch(() => { /* works without, just not offline */ });
  }
})();
