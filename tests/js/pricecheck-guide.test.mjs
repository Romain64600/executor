// The Price check team guide page (2026-10-03), EXECUTED: the real pricecheck-guide.js in the stubbed DOM.
// Romain: « quelqu'un qui a accès à l'admin a accès à ce guide ». The page carries both languages; the script shows
// one, remembers the choice, and obeys #en / #fr in the address.

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole } from "./load_console.mjs";
import { tick } from "./dom_stub.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = process.env.PRICECHECK_GUIDE_JS
  || path.join(HERE, "..", "..", "src", "admin", "static", "pricecheck-guide.js");

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), data };
}
const shows = (c, lang) => !c.$("#guide-" + lang).classList.contains("hidden");

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

// English by default since 07/10/2026 (Romain : « tout l'outil en anglais »), French one click away
test("English by default, French one click away, and the choice is kept", async () => {
  const storage = memoryStorage();
  const c = await loadConsole(SCRIPT, { localStorage: storage, location: { hash: "" } });
  assert.ok(shows(c, "en") && !shows(c, "fr"), "English first");
  assert.equal(c.$("#lang-en").getAttribute("aria-pressed"), "true");
  await c.$("#lang-fr").fire("click");
  await tick();
  assert.ok(shows(c, "fr") && !shows(c, "en"), "the French guide after a click on FR");
  assert.equal(c.$("#lang-fr").getAttribute("aria-pressed"), "true");
  assert.equal(storage.data.get("pc-guide-lang"), "fr");
  const again = await loadConsole(SCRIPT, { localStorage: storage, location: { hash: "" } });
  assert.ok(shows(again, "fr"), "the language chosen last time");
  // the admin's own choice (aks-lang) when the guide has none
  const admin = await loadConsole(SCRIPT, { localStorage: memoryStorage({ "aks-lang": "fr" }), location: { hash: "" } });
  assert.ok(shows(admin, "fr"), "the admin's language is not followed");
});

test("#en in the address opens the English guide (the help's link)", async () => {
  const c = await loadConsole(SCRIPT, { localStorage: memoryStorage({ "pc-guide-lang": "fr" }), location: { hash: "#en" } });
  assert.ok(shows(c, "en") && !shows(c, "fr"));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log("ok   - " + name); }
  catch (e) { failed++; console.log("FAIL - " + name + "\n       " + (e && e.message)); }
}
if (failed) process.exit(1);
