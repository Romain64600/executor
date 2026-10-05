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
  mode: "homepage", modes: ["homepage"], mode_label: "Price check homepage",
};
const TRAP = {
  ...TORO, offer: "140000001", verdict: "NON VÉRIFIABLE", product: "Piège", reasons: ["URL sans nom du produit"],
  merchant_url: "javascript:alert(1)", decision: { decision: "faux", note: "", by: "remi", at: "2026-10-01T11:00:00+02:00" },
  history: [{ decision: "faux", note: "", by: "remi", at: "2026-10-01T11:00:00+02:00" }],
  seen_at: "2026-09-30 08:00", seen_lag_seconds: 90000, edition_rank: 1,
};
const FIXED = { ...TORO, offer: "140000002", verdict: "OK", product: "Réparé", reasons: [], decision: null, history: [],
  fixed_at: "2026-10-02 18:30", fixed_how: "recontrôle OK", fixed_from: "SUSPECT", seen_lag_seconds: 60 };
const STILL = { ...TORO, offer: "140000003", product: "Toujours faux", still_wrong_at: "2026-10-02 18:31", seen_lag_seconds: 60 };
// 02/10/2026: an offer that could not be verified (NON VÉRIFIABLE) and is verified OK at a re-check
const VERIFIED = { ...TORO, offer: "140000005", verdict: "OK", product: "Vérifiée", reasons: [], decision: null, history: [],
  fixed_at: "2026-10-02 22:10", fixed_kind: "verified", fixed_how: "vérifiée OK au recontrôle", fixed_from: "NON VÉRIFIABLE",
  seen_lag_seconds: 60 };
// 02/10/2026: UFC 5 at Eneba, found OK at the 18:37 re-check with nothing changed: a rule cleared an old false positive
const RULE = { ...TORO, offer: "140000004", verdict: "OK", product: "UFC 5", reasons: [], decision: null, history: [],
  fixed_at: "2026-10-02 18:37", fixed_kind: "rule", fixed_how: "ancien faux positif : rien n'a changé, levé par une règle",
  fixed_from: "SUSPECT", seen_lag_seconds: 60 };
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
  assert.ok(after.textContent.includes("✔ Traité par romain le 01/10 12:45 : Vrai positif"), after.textContent);
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
  assert.ok(!el.textContent.includes("Traité par"), "a refused decision is shown as recorded");
});

// Romain, 05/10/2026: Rémy typed his comments AFTER clicking the decision; the note had left, empty,
// with the click, and his comments stayed in the fields, never saved. A note on a decided report is
// now saved on its own, an unsaved note says so, and leaving the page with one asks first.
const DECIDED = { ...TORO, offer: "140000006", product: "Décidé", seen_lag_seconds: 60,
  decision: { decision: "faux", note: "", by: "remy", at: "2026-10-05T15:20:00+02:00" },
  history: [{ decision: "faux", note: "", by: "remy", at: "2026-10-05T15:20:00+02:00" }] };
const posts = (c) => c.net.calls.filter((x) => x.method === "POST").length;

test("a note typed after the decision is saved on its own, with Enter or its button", async () => {
  const c = await start({ ...REPORTS, reports: [TORO, DECIDED] });
  let el = card(c, DECIDED.offer);
  assert.ok(el.querySelector(".pc-save-note").hidden, "the save button shows with nothing to save");
  assert.ok(el.querySelector(".pc-unsaved").hidden, "an empty note says it is not saved");
  const note = el.querySelector(".pc-note");
  note.value = "la page AKS est bien un DLC";
  await note.fire("input");
  assert.ok(!el.querySelector(".pc-unsaved").hidden, "an unsaved note does not say so");
  assert.ok(note.classList.contains("unsaved"), "an unsaved note is not marked");
  assert.ok(!el.querySelector(".pc-save-note").hidden, "no way to save the note alone");
  const before = posts(c);
  await note.fire("keydown", { key: "Enter", preventDefault() {} });
  await tick();
  assert.equal(posts(c), before + 1, "Enter sent nothing");
  assert.deepEqual(lastPost(c).body, { offer: DECIDED.offer, decision: "faux", note: "la page AKS est bien un DLC" });
  await c.net.release("api/price-check/decision", { recorded: { offer: DECIDED.offer, decision: "faux",
    note: "la page AKS est bien un DLC", by: "remy", at: "2026-10-05T15:40:00+02:00" } });
  await tick();
  el = card(c, DECIDED.offer);
  assert.ok(el.textContent.includes("« la page AKS est bien un DLC »"), "the saved note is not shown: " + el.textContent);
  assert.ok(el.querySelector(".pc-unsaved").hidden, "a saved note still says it is not saved");
  const again = el.querySelector(".pc-note");
  again.value = "vu avec Romain";
  await again.fire("input");
  el.querySelector(".pc-save-note").fire("click");
  await tick();
  assert.deepEqual(lastPost(c).body, { offer: DECIDED.offer, decision: "faux", note: "vu avec Romain" });
});

test("a note typed before any decision says it leaves with the decision, and Enter sends nothing", async () => {
  const c = await start();
  const el = card(c, TORO.offer);
  assert.equal(el.querySelector(".pc-save-note"), null, "a note cannot be saved without a decision");
  const note = el.querySelector(".pc-note");
  note.value = "Metal Garden";
  await note.fire("input");
  const pending = el.querySelector(".pc-unsaved");
  assert.ok(!pending.hidden && pending.textContent.includes("elle part avec ta décision"), "the note does not say how it is saved");
  const before = posts(c);
  await note.fire("keydown", { key: "Enter", preventDefault() {} });
  await tick();
  assert.equal(posts(c), before, "Enter recorded a decision nobody chose");
});

test("leaving the page with an unsaved note asks first, never without one", async () => {
  const handlers = {};
  const c = await loadConsole(CONSOLE, { window: { addEventListener(kind, fn) { handlers[kind] = fn; } } });
  await c.net.release("api/price-check/reports", JSON.parse(JSON.stringify(REPORTS)));
  await tick();
  assert.ok(handlers.beforeunload, "no guard on leaving the page");
  const quiet = { prevented: false, preventDefault() { this.prevented = true; } };
  handlers.beforeunload(quiet);
  assert.ok(!quiet.prevented, "leaving is held with nothing unsaved");
  const note = card(c, TORO.offer).querySelector(".pc-note");
  note.value = "Metal Garden";
  await note.fire("input");
  const ev = { prevented: false, returnValue: undefined, preventDefault() { this.prevented = true; } };
  handlers.beforeunload(ev);
  assert.ok(ev.prevented && ev.returnValue === "", "leaving with an unsaved note does not ask");
});

// Romain, 05/10/2026 : « mettre le texte à gauche, les boutons à droite et spécifier ça dans l'admin ».
test("the decision reads in two steps: ① the note on the left, ② the decision on the right", async () => {
  const c = await start();
  const zone = card(c, TORO.offer).querySelector(".pc-decide");
  const steps = zone.children.filter((n) => n.classList && n.classList.contains("pc-step"));
  assert.equal(steps.length, 2, "the decision is not in two steps");
  assert.ok(steps[0].classList.contains("pc-step-note") && steps[0].querySelector(".pc-note"), "the note is not the first step");
  assert.ok(steps[0].textContent.includes("1Pourquoi ? (seulement si besoin)"), steps[0].textContent);
  assert.ok(steps[1].classList.contains("pc-step-decision") && steps[1].textContent.includes("2Ta décision"), steps[1].textContent);
  assert.deepEqual(steps[1].querySelectorAll("button").map((b) => b.textContent), ["Vrai positif", "Faux positif", "À discuter"]);
  // Romain, 05/10/2026 : « si on est d'accord avec l'erreur décrite sur le report, il n'y a pas de raison de commenter »
  assert.ok(zone.textContent.includes("D'accord avec l'erreur décrite ? Clique directement ta décision, sans note."), zone.textContent);
});

test("a decided report shows its saved note, and another decision keeps it", async () => {
  const saved = { ...DECIDED.decision, note: "la fiche dit ROW" };
  const NOTED = { ...DECIDED, offer: "140000007", decision: saved, history: [saved] };
  const c = await start({ ...REPORTS, reports: [NOTED] });
  const el = card(c, NOTED.offer);
  assert.equal(el.querySelector(".pc-note").value, "la fiche dit ROW", "the saved note is not in the field");
  assert.ok(el.querySelector(".pc-unsaved").hidden, "a saved note is flagged as not saved");
  assert.ok(el.querySelector(".pc-decide").textContent.includes("la note la suit"), "the card does not say how to change");
  buttons(el).find((b) => b.textContent === "Vrai positif").fire("click");
  await tick();
  assert.deepEqual(lastPost(c).body, { offer: NOTED.offer, decision: "vrai", note: "la fiche dit ROW" });
});

test("the « Comment trancher » box remembers being folded", async () => {
  const store = { "pc-howto": "closed" };
  const c = await loadConsole(CONSOLE, { localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } } });
  const box = c.$("#pc-howto");
  assert.equal(box.open, false, "a folded box opens again");
  box.open = true;
  await box.fire("toggle");
  assert.equal(store["pc-howto"], "open", "opening the box is not remembered");
});

// Romain, 05/10/2026 : « rend plus clair le fait qu'une tâche a été traitée par un opérateur et quel opérateur l'a traitée ».
test("a handled report says who handled it at the top of its card, an open one says it is to handle", async () => {
  const c = await start({ ...REPORTS, reports: [TORO, DECIDED] });
  const done = card(c, DECIDED.offer).querySelector(".pc-done");
  assert.ok(done, "a handled report does not say so at the top of its card");
  assert.equal(done.textContent, "✔ Traité par remy · Faux positif");
  assert.ok(done.classList.contains("d-faux"), "the badge does not take the decision's colour");
  assert.ok(card(c, DECIDED.offer).querySelector(".pc-decision").textContent.startsWith("✔ Traité par remy le 05/10 15:20 : Faux positif"),
    card(c, DECIDED.offer).querySelector(".pc-decision").textContent);
  assert.equal(card(c, TORO.offer).querySelector(".pc-done"), null, "an open report says it was handled");
  assert.equal(card(c, TORO.offer).querySelector(".pc-todo").textContent, "À traiter");
});

test("the « Traité par » filter shows one operator's reports or the ones nobody handled, and counts them", async () => {
  const c = await start({ ...REPORTS, reports: [TORO, DECIDED, TRAP] });
  const sel = c.$("#f-by");
  assert.deepEqual(sel.children.filter((o) => o.tagName === "OPTION").map((o) => o.getAttribute("value")), ["", "none", "remi", "remy"]);
  sel.value = "remy";
  await sel.fire("change");
  assert.deepEqual(shown(c), ["offer-" + DECIDED.offer]);
  sel.value = "none";
  await sel.fire("change");
  assert.deepEqual(shown(c), ["offer-" + TORO.offer]);
  assert.equal(c.$("#pc-by").textContent, "Traités par : remi 1 · remy 1");
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
                   last_end: "2026-10-02T15:00:40+0200", last_checked: 3, last_alerts: 1, next_at: "2026-10-02T15:03:10+0200",
                   last_requested_by: "romain" },
    "homepage": { label: "Price check homepage", running: true, pages: 430, progress: [120, 430], requested_by: "romain" },
  },
  pending: { "top-games": null, "homepage": null },
};

test("the two run buttons show the monitor's state and send the mode", async () => {
  const c = await start();
  await c.net.release("api/price-check/status", JSON.parse(JSON.stringify(STATUS)));
  await tick();
  const top = c.$("#state-top-games").textContent, home = c.$("#state-homepage").textContent;
  assert.ok(top.includes("3 nouvelle(s) offre(s)") && top.includes("1 alerte(s)") && top.includes("prochain passage 02/10 15:03"), top);
  assert.ok(top.includes("40 s") && top.includes("9 pages lues") && top.includes("lancé depuis l'admin par romain"), top);
  assert.ok(home.includes("En cours : page 120 / 430") && home.includes("romain"), home);
  assert.ok(c.$("#launch-homepage").disabled, "the homepage button must be disabled while that pass runs");
  assert.ok(!c.$("#launch-top-games").disabled, "the top button must be clickable");
  c.$("#launch-top-games").fire("click");
  await tick();
  const post = lastPost(c);
  assert.ok(post && post.url === "api/price-check/run", "no run request left the page");
  assert.deepEqual(post.body, { mode: "top-games" });
  assert.ok(c.$("#launch-top-games").disabled, "the button must be disabled while the request is sent");
  await c.net.release("api/price-check/run", { requested: { mode: "top-games", by: "romain", at: "2026-10-02T15:01:00+02:00" } });
  await tick();
  assert.ok(c.$("#msg-top-games").textContent.includes("Demande déposée par romain"), c.$("#msg-top-games").textContent);
});

test("re-check: a repaired offer says so, its filter finds it, a still-wrong one says so", async () => {
  const c = await start({ ...REPORTS, reports: [TORO, FIXED, STILL] });
  const fixed = card(c, FIXED.offer);
  assert.ok(fixed.textContent.includes("RÉPARÉE") && fixed.textContent.includes("Réparée le 02/10 18:30 : recontrôle OK (était SUSPECT)"),
            fixed.textContent);
  assert.ok(card(c, STILL.offer).textContent.includes("Toujours en erreur au recontrôle du 02/10 18:31"));
  assert.ok(c.$("#pc-summary").textContent.includes("réparées"));
  c.$("#f-verdict").value = "fixed";
  await c.$("#f-verdict").fire("change");
  assert.deepEqual(shown(c), ["offer-" + FIXED.offer]);
  c.$("#f-verdict").value = "SUSPECT";
  await c.$("#f-verdict").fire("change");
  assert.ok(!shown(c).includes("offer-" + FIXED.offer), "a repaired offer is not a SUSPECT");
});

test("re-check: a false positive cleared by a rule is not a repair", async () => {
  const c = await start({ ...REPORTS, reports: [TORO, FIXED, RULE] });
  const rule = card(c, RULE.offer);
  assert.ok(rule.textContent.includes("FAUX POSITIF LEVÉ") && !rule.textContent.includes("RÉPARÉE"), rule.textContent);
  assert.ok(rule.textContent.includes("Faux positif levé par une règle le 02/10 18:37 : ancien faux positif : rien n'a changé, levé par une règle (était SUSPECT)"),
            rule.textContent);
  const summary = c.$("#pc-summary").textContent;
  assert.ok(summary.includes("1réparées") && summary.includes("1faux positifs levés"), summary);
  c.$("#f-verdict").value = "fixed";
  await c.$("#f-verdict").fire("change");
  assert.deepEqual(shown(c), ["offer-" + FIXED.offer], "the repaired filter lists the rule-cleared offer");
  c.$("#f-verdict").value = "rule";
  await c.$("#f-verdict").fire("change");
  assert.deepEqual(shown(c), ["offer-" + RULE.offer]);
});

test("re-check: an offer verified OK is neither repaired nor a false positive", async () => {
  const c = await start({ ...REPORTS, reports: [TORO, FIXED, RULE, VERIFIED] });
  const v = card(c, VERIFIED.offer);
  assert.ok(v.textContent.includes("VÉRIFIÉE OK") && !v.textContent.includes("RÉPARÉE") && !v.textContent.includes("FAUX POSITIF"),
            v.textContent);
  assert.ok(v.textContent.includes("Vérifiée OK au recontrôle le 02/10 22:10 : vérifiée OK au recontrôle (était NON VÉRIFIABLE)"),
            v.textContent);
  const summary = c.$("#pc-summary").textContent;
  assert.ok(summary.includes("1réparées") && summary.includes("1faux positifs levés") && summary.includes("1vérifiées OK"), summary);
  for (const [value, offer] of [["fixed", FIXED.offer], ["rule", RULE.offer], ["verified", VERIFIED.offer]]) {
    c.$("#f-verdict").value = value;
    await c.$("#f-verdict").fire("change");
    assert.deepEqual(shown(c), ["offer-" + offer], value);
  }
});

test("each report says whether it is a top games or a homepage problem, and the mode filter separates them", async () => {
  // Romain, 03/10/2026: « que le report des problèmes sur les tops soit identifié des problèmes home page »
  const TOP = { ...TORO, offer: "140000006", product: "EA SPORTS FC 27", list: "Popular", rank: 1, mode: "top-games",
    modes: ["top-games", "homepage"], mode_label: "Price check top" };
  const OLD = { ...TORO, offer: "140000007", product: "Ancien export" };
  delete OLD.mode;
  const c = await start({ ...REPORTS, reports: [TORO, TOP, OLD] });
  assert.ok(card(c, TOP.offer).textContent.includes("TOP") && !card(c, TOP.offer).textContent.includes("HOMEPAGE"),
            card(c, TOP.offer).textContent);
  assert.ok(card(c, TORO.offer).textContent.includes("HOMEPAGE"), card(c, TORO.offer).textContent);
  assert.ok(!/TOP|HOMEPAGE/.test(card(c, OLD.offer).textContent.replace("TOP 50", "")), "an export without mode shows no badge");
  const summary = c.$("#pc-summary").textContent;
  assert.ok(summary.includes("1tops à trancher") && summary.includes("1homepage à trancher"), summary);
  c.$("#f-mode").value = "top-games";
  await c.$("#f-mode").fire("change");
  assert.deepEqual(shown(c), ["offer-" + TOP.offer]);
  c.$("#f-mode").value = "homepage";
  await c.$("#f-mode").fire("change");
  assert.deepEqual(shown(c), ["offer-" + TORO.offer]);
  c.$("#f-mode").value = "";
  await c.$("#f-mode").fire("change");
  assert.equal(shown(c).length, 3);
});

test("first-price problems are marked and can be shown alone", async () => {
  // Romain, 03/10/2026: « séparer les problèmes de premiers prix … premier prix = les 3 prix les moins chers par édition »
  const FIRST = { ...TORO, offer: "140000008", product: "Monster Hunter Wilds", edition_rank: 2, first_price: true };
  const LOW = { ...TORO, offer: "140000009", product: "F1 25", edition_rank: 11, first_price: false };
  const OLDRANK = { ...TORO, offer: "140000010", product: "Ancien export", edition_rank: 3 };
  delete OLDRANK.first_price;
  const c = await start({ ...REPORTS, reports: [FIRST, LOW, OLDRANK] });
  assert.ok(card(c, FIRST.offer).textContent.includes("PREMIER PRIX"), card(c, FIRST.offer).textContent);
  assert.ok(!card(c, LOW.offer).textContent.includes("PREMIER PRIX"), card(c, LOW.offer).textContent);
  assert.ok(card(c, OLDRANK.offer).textContent.includes("PREMIER PRIX"), "an older export: the rank in the edition decides");
  assert.ok(c.$("#pc-summary").textContent.includes("2premiers prix en erreur"), c.$("#pc-summary").textContent);
  c.$("#f-first").checked = true;
  await c.$("#f-first").fire("change");
  assert.deepEqual(shown(c), ["offer-" + FIRST.offer, "offer-" + OLDRANK.offer]);
});

test("a report links its Discord feedback thread, never a non-http one", async () => {
  // 03/10/2026: each alert has a feedback thread on Discord, where one can decide too
  const WITH = { ...TORO, offer: "140000011", discord_thread: "https://discord.com/channels/77/903" };
  const BAD = { ...TORO, offer: "140000012", discord_thread: "javascript:alert(1)" };
  const c = await start({ ...REPORTS, reports: [TORO, WITH, BAD] });
  const a = anchors(card(c, WITH.offer)).find((x) => x.getAttribute("href") === WITH.discord_thread);
  assert.ok(a && card(c, WITH.offer).textContent.includes("Fil Discord"), card(c, WITH.offer).textContent);
  assert.ok(!card(c, TORO.offer).textContent.includes("Fil Discord"), "no thread, no link");
  assert.ok(!anchors(card(c, BAD.offer)).some((x) => String(x.getAttribute("href")).startsWith("javascript")),
            "a javascript: thread link is never clickable");
});

test("the state line tells the last re-check", async () => {
  const c = await start();
  const st = JSON.parse(JSON.stringify(STATUS));
  st.modes["top-games"].last_recheck = { at: "2026-10-02T18:30:00+0200", kind: "all", checked: 70, fixed: 2, new: 1, still: 3, unknown: 0 };
  st.modes["homepage"].last_recheck = { at: "2026-10-02T18:37:00+0200", kind: "flagged", checked: 9, fixed: 0, rules: 4, new: 0, still: 5, unknown: 0 };
  await c.net.release("api/price-check/status", st);
  await tick();
  const top = c.$("#state-top-games").textContent;
  assert.ok(top.includes("Recontrôle complet 02/10 18:30 : 70 offre(s), 2 réparée(s), 1 nouvelle(s) erreur(s), 3 toujours en erreur"), top);
  const home = c.$("#state-homepage").textContent;
  assert.ok(home.includes("Recontrôle des offres signalées 02/10 18:37 : 9 offre(s), 0 réparée(s), 4 faux positif(s) levé(s) par une règle, 0 nouvelle(s) erreur(s), 5 toujours en erreur"), home);
});

test("a quiet pass says there was nothing new to check", async () => {
  const c = await start();
  const quiet = JSON.parse(JSON.stringify(STATUS));
  quiet.modes["top-games"].last_checked = 0;
  quiet.modes["top-games"].last_alerts = 0;
  delete quiet.modes["top-games"].last_requested_by;
  await c.net.release("api/price-check/status", quiet);
  await tick();
  const top = c.$("#state-top-games").textContent;
  assert.ok(top.includes("aucune nouvelle offre à contrôler, 0 alerte(s)"), top);
  assert.ok(!top.includes("lancé depuis"), top);
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
