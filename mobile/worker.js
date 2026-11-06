// Runs StudyPal's Python (the same Api as the desktop app) with Pyodide, off the page's thread, so a long
// call (reading an exam, a sync) never freezes the screen. The page sends {id, name, args}; the reply is
// {id, result}. Python asks the page for things only it can do with {host: ...} messages (see webrun.py).

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";

let py, handle, saving = Promise.resolve(), dirty = false;

// The data folder lives in IndexedDB. It's written back after each call.
function persist() {
  if (!dirty) return saving;
  dirty = false;
  saving = saving.then(() => new Promise((resolve) => py.FS.syncfs(false, () => resolve())));
  return saving;
}

const step = (text) => self.postMessage({ step: text });

async function start(demo) {
  step("Loading Python");
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  py = await loadPyodide({ indexURL: PYODIDE });
  step("Loading packages");
  await py.loadPackage(["pydantic", "pillow"]);
  step("Opening your data");
  py.FS.mkdirTree("/data");
  py.FS.mount(py.FS.filesystems.IDBFS, {}, "/data");
  await new Promise((resolve, reject) => py.FS.syncfs(true, (e) => (e ? reject(e) : resolve())));
  step("Starting StudyPal");
  const zip = await (await fetch("studypal.zip", { cache: "no-cache" })).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/lib/studypal-app" });
  py.runPython(`
import sys
sys.path.insert(0, "/lib/studypal-app")
from studypal import webrun
webrun.start(demo=${demo ? "True" : "False"})
`);
  handle = py.pyimport("studypal.webrun").handle;
  dirty = true;
  await persist();
}

let ready;
self.onmessage = async (e) => {
  const msg = e.data;
  if (msg.start !== undefined) {
    ready = start(msg.demo).then(() => self.postMessage({ ready: true }),
      (err) => self.postMessage({ failed: String(err && err.message || err) }));
    return;
  }
  await ready;
  let result;
  try {
    result = handle(msg.name, JSON.stringify(msg.args || []));
  } catch (err) {
    result = JSON.stringify({ error: `Something went wrong: ${err.message || err}` });
  }
  dirty = true;  // IndexedDB only gets the files that changed, so this is cheap
  self.postMessage({ id: msg.id, result });
  persist();
};
