// The "Romain" tab, EXECUTED (2026-10-06).
//
// Romain : « un onglet Romain où il y a toutes les questions en cours, que tout le monde peut consulter, mais il n'y a
// que moi qui peux agir dessus » ; « il faudra jamais oublier de me reporter les questions en cours ». Loaded as shipped,
// in the stubbed DOM, with the real shapes of api/romain/questions and api/price-check/reports.

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole as loadPage } from "./load_console.mjs";
// English by default since 07/10/2026: the scenarios below read the French page unless they ask for English
const IN_FRENCH = { localStorage: { getItem: (k) => (k === "aks-lang" ? "fr" : null), setItem() {} } };
const loadConsole = (path, overrides = {}) => loadPage(path, { ...IN_FRENCH, ...overrides });
import { tick } from "./dom_stub.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// `ROMAIN_JS` replays the harness against a deliberately broken page: a harness that never goes red proves nothing.
const PAGE = process.env.ROMAIN_JS || path.join(HERE, "..", "..", "src", "admin", "static", "romain.js");

const QUESTIONS = { available: true, owner: "romain", questions: [
  { id: "Q1", at: "2026-10-06T18:43:00+02:00", from: "claude", from_label: "Claude", source: "récolte",
    text: "Garder merchants/battlestategames.toml ?", status: "open" },
  { id: "Q2", at: "2026-10-06T18:50:00+02:00", from: "remy", from_label: "Rémy", source: "console",
    text: "Dawnwalker chez Eneba : erreur ?", status: "open" },
  { id: "Q0", at: "2026-10-06T10:00:00+02:00", from: "garance", from_label: "Garance", source: "console", text: "Ancienne",
    status: "closed", closed_by: "romain", closed_at: "2026-10-06T11:00:00+02:00", answer: "on garde" }] };
const REPORTS = { reports: [
  { offer: "138082170", product: "Dying Light The Beast", edition: "Standard", merchant: "GameBoost",
    decision: { decision: "a_discuter", note: "activable aux US et en EU ?", by: "remy", at: "2026-10-05T15:42:00+02:00" } },
  { offer: "1", product: "Tranché", decision: { decision: "vrai", by: "remy" } }] };

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   - " + name); } catch (e) { failed++; console.log("FAIL - " + name + "\n" + e.stack); }
}
const buttons = (n) => n.querySelectorAll("button");
const anchors = (n) => n.querySelectorAll("a");
async function start(role) {
  const c = await loadConsole(PAGE);
  await c.net.release("api/romain/questions", { ...JSON.parse(JSON.stringify(QUESTIONS)), role, me: role === "owner" ? "romain" : "remy" });
  await c.net.release("api/price-check/reports", JSON.parse(JSON.stringify(REPORTS)));
  await tick();
  return c;
}

await test("everyone sees the open questions, the reports to discuss and the settled ones; only Romain gets the buttons", async () => {
  const c = await start("team");
  assert.ok(c.$("#q-Q1") && c.$("#q-Q2"), "an open question is missing");
  assert.equal(c.$("#rm-count").textContent, "— 2");
  assert.equal(buttons(c.$("#rm-questions")).length, 0, "someone else than Romain can settle");
  assert.ok(c.$("#rm-who").textContent.includes("Seul Romain"), c.$("#rm-who").textContent);
  assert.ok(c.$("#rm-questions").textContent.includes("récolte des décisions"), "the source is not shown");
  assert.ok(c.$("#rm-settled").textContent.includes("→ on garde"), c.$("#rm-settled").textContent);
  const discuss = c.$("#rm-reports");
  assert.ok(discuss.textContent.includes("Dying Light The Beast") && !discuss.textContent.includes("Tranché"), discuss.textContent);
  assert.ok(anchors(discuss).some((a) => a.getAttribute("href") === "price-check#offer-138082170"), "no link to the report");
});

await test("a doubt on a report carries its links on the card", async () => {
  // Romain, 08/10/2026 : « quand tu as un doute sur les reports, tu peux les renvoyer sur l'onglet Romain »
  const c = await loadConsole(PAGE);
  const doubt = { id: "Q13", at: "2026-10-08T14:00:00+02:00", from: "claude", from_label: "Claude", source: "report", status: "open",
    text: "Ready Or Not · Bundle · Keycense (offer 136576203): the page has an LSPD Bundle edition with 32 offers.", offer: "136576203",
    links: { page: "https://www.allkeyshop.com/blog/buy-ready-or-not-cd-key-compare-prices/",
             merchant: "https://www.keycense.com/ready-or-not-lspd-bundle-steam", thread: "https://discord.com/channels/1/2",
             evil: "javascript:alert(1)" } };
  await c.net.release("api/romain/questions", { ...JSON.parse(JSON.stringify(QUESTIONS)), questions: [doubt], role: "owner", me: "romain" });
  await c.net.release("api/price-check/reports", JSON.parse(JSON.stringify(REPORTS)));
  await tick();
  const card = c.$("#q-Q13");
  assert.ok(card && card.textContent.includes("doute sur un report"), "the source is not shown");
  const hrefs = anchors(card).map((a) => a.getAttribute("href"));
  assert.deepEqual(hrefs, ["https://www.allkeyshop.com/blog/buy-ready-or-not-cd-key-compare-prices/",
    "https://www.keycense.com/ready-or-not-lspd-bundle-steam", "https://discord.com/channels/1/2", "price-check#offer-136576203"]);
  assert.ok(anchors(card).slice(0, 3).every((a) => a.getAttribute("rel") === "noopener"), "an external link without noopener");
  assert.equal(buttons(card).length, 1, "Romain cannot settle it");
});

await test("Romain settles a question with his answer", async () => {
  const c = await start("owner");
  const card = c.$("#q-Q1");
  const box = card.querySelectorAll("textarea")[0];
  box.value = "on garde la règle";
  await box.fire("input");
  const btn = buttons(card).find((b) => b.textContent === "Régler Q1");
  assert.ok(btn, "Romain has no button");
  btn.fire("click");
  await tick();
  const sent = [...c.net.calls].reverse().find((x) => x.method === "POST");
  assert.deepEqual([sent.url, sent.body], ["api/romain/questions/close", { question: "Q1", note: "on garde la règle" }]);
  await c.net.release("api/romain/questions/close", { requested: { kind: "close", question: "Q1" } });
  assert.ok(c.$("#q-Q1").textContent.includes("la console l'enregistre"), c.$("#q-Q1").textContent);
  assert.equal(buttons(c.$("#q-Q1")).length, 0, "a settled question can be settled twice");
});

await test("a refused settlement says why and keeps the button", async () => {
  const c = await start("owner");
  buttons(c.$("#q-Q2")).find((b) => b.textContent === "Régler Q2").fire("click");
  await tick();
  await c.net.release("api/romain/questions/close", { error: { code: "owner_only", message: "seul Romain peut le faire" } }, false);
  assert.ok(c.$("#status").textContent.includes("Q2 non réglée : seul Romain peut le faire"), c.$("#status").textContent);
  assert.ok(buttons(c.$("#q-Q2")).some((b) => b.textContent === "Régler Q2"), "the button is gone after a refusal");
});

// 07/10/2026 : « une version anglaise et une version française » ; the questions stay in their language
await test("in English: the interface is translated, the questions stay as they are", async () => {
  const c = await loadConsole(PAGE, { localStorage: { getItem: (k) => (k === "aks-lang" ? "en" : null), setItem() {} } });
  await c.net.release("api/romain/questions", { ...JSON.parse(JSON.stringify(QUESTIONS)), role: "owner", me: "romain" });
  await c.net.release("api/price-check/reports", JSON.parse(JSON.stringify(REPORTS)));
  await tick();
  assert.ok(buttons(c.$("#q-Q1")).some((b) => b.textContent === "Settle Q1"), "the button is not translated");
  assert.ok(c.$("#q-Q1").textContent.includes("Garder merchants/battlestategames.toml ?"), "the question was translated");
  assert.ok(c.$("#rm-who").textContent.includes("Only you see"), c.$("#rm-who").textContent);
  assert.ok(c.$("#rm-reports").textContent.includes("Open the report"), c.$("#rm-reports").textContent);
  assert.equal(c.$("#lang").textContent, "FR");
});

if (failed) { console.log(failed + " FAIL"); process.exit(1); }
