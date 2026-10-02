// The "Price check" console, EXECUTED (2026-10-01).
//
// Romain: « ce rapport interactif de price check devrait être dans l'admin ». The page shows the
// first-price monitor's reports and records a decision per report. Loaded here as shipped, in
// the stubbed DOM, with the real shape of /api/price-check/reports; we look at what is shown and
// at what leaves the page when a decision is clicked.

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole } from "./load_console.mjs";
import { tick } from "./dom_stub.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// `PRICECHECK_JS` replays the harness against a deliberately broken console: a harness that
// never goes red proves nothing (lesson of sort_race).
const CONSOLE = process.env.PRICECHECK_JS
  || path.join(HERE, "..", "..", "src", "admin", "static", "pricecheck.js");

const DECISIONS = { vrai: "Vrai positif : alerter", faux: "Faux positif : ne pas alerter", a_discuter: "À discuter" };
const TORO = {
  offer: "140421891", verdict: "SUSPECT", product: "TORO 2 Nintendo Switch", edition: "Standard",
  merchant: "Nintendo eShop FR", price: 5.99, region: "GLOBAL", region_filter: "", platform: "nintendo-eshop",
  reasons: ["autre produit chez le marchand : « Metal Garden » au lieu de « TORO 2 Nintendo Switch » (URL de la version en-GB)"],
  notes: [], method: "URL de la version en-GB",
  merchant_url: "https://www.nintendo.com/fr-fr/Jeux/Jeux-a-telecharger/Metal-Garden-3177422.html",
  page_url: "https://www.allkeyshop.com/blog/buy-toro-2-nintendo-switch-compare-prices/",
  list: "TOP 50 · Nintendo Popular", rank: 56, at: "2026-09-30 16:15", decision: null, history: [],
  edition_rank: 2, account: false, page_first: false, seen_at: "2026-10-01 12:39", seen_lag_seconds: 600,
};
const TRAP = {
  ...TORO, offer: "140000001", verdict: "NON VÉRIFIABLE", product: "Piège", reasons: ["URL sans nom du produit"],
  merchant_url: "javascript:alert(1)", decision: { decision: "faux", note: "", by: "remi", at: "2026-10-01T11:00:00+02:00" },
  history: [{ decision: "faux", note: "", by: "remi", at: "2026-10-01T11:00:00+02:00" }],
  seen_at: "2026-09-30 08:00", seen_lag_seconds: 90000, edition_rank: 1,
};
const REPORTS = {
  dir: "/var/lib/price-check", generated_at: "2026-10-01T12:38:40+0200", age_seconds: 120,
  decisions: DECISIONS, reports: [TORO, TRAP],
};

async function start(payload = REPORTS) {
  const c = await loadConsole(CONSOLE);
  await c.net.release("api/price-check/reports", JSON.parse(JSON.stringify(payload)));
  await tick();
  return c;
}
const card = (c, offer) => c.$("#offer-" + offer);
// the stub creates any unknown "#id" on demand: what is SHOWN is read from the rendered list itself
const shown = (c) => c.$("#pc-list").children.filter((n) => n.tagName === "ARTICLE").map((n) => n.id);
const buttons = (el) => el.querySelectorAll("button");
const anchors = (el) => el.querySelectorAll("a");
const lastPost = (c) => [...c.net.calls].reverse().find((x) => x.method === "POST");

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("each report is shown with its reason, its rank and its two URLs", async () => {
  const c = await start();
  const el = card(c, TORO.offer);
  assert.ok(el && el.tagName === "ARTICLE", "the TORO 2 report is not rendered");
  const text = el.textContent;
  assert.ok(text.includes("Metal Garden"), "the reason is missing");
  assert.ok(text.includes("2e prix de l'édition"), "the rank in the edition is missing");
  const hrefs = anchors(el).map((a) => a.getAttribute("href"));
  assert.ok(hrefs.includes(TORO.page_url), "no link to the AllKeyShop page");
  assert.ok(hrefs.includes(TORO.merchant_url), "no link to the merchant");
  assert.ok(c.$("#pc-summary").textContent.includes("sans décision"), "the summary is missing");
});

test("a javascript: URL from the file is never a clickable link", async () => {
  const c = await start();
  const el = card(c, TRAP.offer);
  assert.ok(el, "the second report is not rendered");
  assert.ok(!anchors(el).some((a) => String(a.getAttribute("href")).startsWith("javascript")),
            "a javascript: URL became a link");
  assert.ok(el.textContent.includes("javascript:alert(1)"), "the raw URL should still be shown as text");
});

test("deciding sends the offer, the decision and the note, then shows who decided", async () => {
  const c = await start();
  const el = card(c, TORO.offer);
  const note = el.querySelector(".pc-note");
  note.value = "Metal Garden";
  await note.fire("input");
  const vrai = buttons(el).find((b) => b.textContent === "Vrai positif");
  assert.ok(vrai, "no « Vrai positif » button");
  vrai.fire("click");
  await tick();
  const post = lastPost(c);
  assert.ok(post, "no request left the page");
  assert.equal(post.url, "api/price-check/decision");
  assert.deepEqual(post.body, { offer: TORO.offer, decision: "vrai", note: "Metal Garden" });
  assert.ok(buttons(card(c, TORO.offer)).every((b) => b.disabled), "the buttons stay clickable while sending");
  await c.net.release("api/price-check/decision",
    { recorded: { offer: TORO.offer, decision: "vrai", note: "Metal Garden", by: "romain", at: "2026-10-01T12:45:00+02:00" } });
  await tick();
  const after = card(c, TORO.offer);
  assert.ok(after.textContent.includes("Décision : Vrai positif — par romain le 01/10 12:45"), after.textContent);
  assert.ok(buttons(after).find((b) => b.textContent === "Vrai positif").classList.contains("on"));
  assert.ok(buttons(after).every((b) => !b.disabled), "the buttons stay disabled after the answer");
});

test("a refused decision is shown on its card and the buttons come back", async () => {
  const c = await start();
  buttons(card(c, TORO.offer)).find((b) => b.textContent === "Faux positif").fire("click");
  await tick();
  await c.net.release("api/price-check/decision", { error: { code: "bad_decision", message: "décision inconnue" } }, false);
  await tick();
  const el = card(c, TORO.offer);
  assert.ok(el.textContent.includes("Non enregistrée : décision inconnue"), "the refusal is not shown");
  assert.ok(buttons(el).every((b) => !b.disabled), "the buttons stay disabled after a refusal");
  assert.ok(!el.textContent.includes("Décision :"), "a refused decision is shown as recorded");
});

test("an old export is flagged, a fresh one is not", async () => {
  const fresh = await start();
  assert.ok(fresh.$("#pc-stale").classList.contains("hidden"), "a fresh export is flagged");
  const old = await start({ ...REPORTS, age_seconds: 4 * 3600 });
  assert.ok(!old.$("#pc-stale").classList.contains("hidden"), "an export 4 h old is not flagged");
  assert.ok(old.$("#pc-stale").textContent.includes("price-check"), "the warning does not name the service");
});

test("filters: undecided only, and still leading only", async () => {
  const c = await start();
  assert.deepEqual(shown(c), ["offer-" + TORO.offer, "offer-" + TRAP.offer]);
  c.$("#f-decision").value = "none";
  await c.$("#f-decision").fire("change");
  assert.deepEqual(shown(c), ["offer-" + TORO.offer], "« Sans décision » keeps a decided report");
  c.$("#f-decision").value = "";
  c.$("#f-live").checked = true;
  await c.$("#f-live").fire("change");
  assert.deepEqual(shown(c), ["offer-" + TORO.offer], "« encore en tête » keeps an offer gone since yesterday");
});

test("a report no longer leading says so", async () => {
  const c = await start();
  assert.ok(card(c, TRAP.offer).textContent.includes("Plus vu en premier prix depuis le 30/09 08:00"));
  assert.ok(!card(c, TORO.offer).textContent.includes("Plus vu en premier prix"));
});

test("an unreadable export is an error on screen, never an empty list", async () => {
  const c = await loadConsole(CONSOLE);
  await c.net.release("api/price-check/reports", { error: { code: "no_reports", message: "reports.json absent" } }, false);
  await tick();
  assert.ok(!c.$("#pc-error").classList.contains("hidden"), "no error banner");
  assert.ok(c.$("#pc-error").textContent.includes("reports.json absent"));
});

const STATUS = {
  available: true, age_seconds: 3, offers: "top-offers", updated_at: "2026-10-02T15:00:03+0200",
  modes: {
    "top-games": { label: "Price check top", running: false, pages: 9, last_start: "2026-10-02T15:00:00+0200",
                   last_end: "2026-10-02T15:00:40+0200", last_checked: 3, last_alerts: 1, next_at: "2026-10-02T15:03:10+0200" },
    "homepage": { label: "Price check homepage", running: true, pages: 430, progress: [120, 430], requested_by: "romain" },
  },
  pending: { "top-games": null, "homepage": null },
};

test("the two run buttons show the monitor's state and send the mode", async () => {
  const c = await start();
  await c.net.release("api/price-check/status", JSON.parse(JSON.stringify(STATUS)));
  await tick();
  const top = c.$("#state-top-games").textContent, home = c.$("#state-homepage").textContent;
  assert.ok(top.includes("3 offre(s)") && top.includes("1 alerte(s)") && top.includes("prochain passage 02/10 15:03"), top);
  assert.ok(home.includes("En cours : page 120 / 430") && home.includes("romain"), home);
  assert.ok(c.$("#launch-homepage").disabled, "the homepage button must be disabled while that pass runs");
  assert.ok(!c.$("#launch-top-games").disabled, "the top button must be clickable");
  c.$("#launch-top-games").fire("click");
  await tick();
  const post = lastPost(c);
  assert.ok(post && post.url === "api/price-check/run", "no run request left the page");
  assert.deepEqual(post.body, { mode: "top-games" });
  assert.ok(c.$("#launch-top-games").disabled, "the button stays clickable while the request is sent");
  await c.net.release("api/price-check/run", { requested: { mode: "top-games", by: "romain", at: "2026-10-02T15:01:00+02:00" } });
  await tick();
  assert.ok(c.$("#msg-top-games").textContent.includes("Demande déposée par romain"), c.$("#msg-top-games").textContent);
});

test("a refused launch says why and gives the button back", async () => {
  const c = await start();
  await c.net.release("api/price-check/status", JSON.parse(JSON.stringify(STATUS)));
  await tick();
  c.$("#launch-top-games").fire("click");
  await tick();
  await c.net.release("api/price-check/run", { error: { code: "already_requested", message: "un passage est déjà demandé" } }, false);
  await tick();
  assert.ok(c.$("#msg-top-games").textContent.includes("Refusé : un passage est déjà demandé"));
  assert.ok(!c.$("#launch-top-games").disabled, "the button must come back after a refusal");
});

test("without status.json the buttons still work and say the state is unknown", async () => {
  const c = await start();
  await c.net.release("api/price-check/status", { available: false, modes: {}, pending: { "top-games": null, "homepage": { by: "remi" } } });
  await tick();
  assert.ok(c.$("#state-top-games").textContent.includes("inconnu"));
  assert.ok(!c.$("#launch-top-games").disabled);
  assert.ok(c.$("#launch-homepage").disabled, "a pending request disables its button");
});

let red = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log("ok   -", name); }
  catch (e) { red++; console.log("FAIL -", name, "\n      ", e.message); }
}
process.exit(red ? 1 : 0);
