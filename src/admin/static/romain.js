"use strict";
// ---- FR / EN (Romain, 07/10/2026 : « comme t'as fait pour le guide, avoir une version anglaise et une version française »).
// French is the source text and the key: T("…") gives English when the page is in English (aks-lang, per browser, the
// same choice as the Price check tab). The questions and the answers stay in their language.
const LANG = (() => { try { return localStorage.getItem("aks-lang") === "en" ? "en" : "fr"; } catch (e) { return "fr"; } })();
const EN = {
 "récolte des décisions": "harvest of the decisions",
 "console": "console",
 "Réglée : la console l'enregistre dans quelques secondes.": "Settled: the console records it within seconds.",
 "Ta décision pour ": "Your decision for ",
 "Ta décision (facultatif) : elle part à Claude et reste ici": "Your decision (optional): it goes to Claude and stays here",
 "Envoi…": "Sending…",
 "Régler ": "Settle ",
 " · réglée par ": " · settled by ",
 " le ": " on ",
 " · offre ": " · offer ",
 " · à discuter par ": " · to discuss by ",
 "Ouvrir le report": "Open the report",
 "Toi seul vois les boutons « Régler ».": "Only you see the « Settle » buttons.",
 "Seul Romain peut régler une question.": "Only Romain can settle a question.",
 "Aucune question en cours.": "No open question.",
 "Pas encore de questions : le service de la console ne les a pas écrites.": "No questions yet: the console service has not written them.",
 "Aucun report à discuter.": "No report to discuss.",
 "Reports illisibles pour l'instant.": "Reports unreadable for now.",
 "Aucune question réglée.": "No settled question.",
 " réglée : la console l'enregistre et le dit à Claude": " settled: the console records it and tells Claude",
 " non réglée : ": " not settled: ",
 "Lecture des questions…": "Reading the questions…",
 "Questions à jour": "Questions up to date",
 "Questions illisibles : ": "Questions unreadable: ",
 "Relire les questions": "Read the questions again",
 "Basculer le thème": "Switch the theme"
};
const T = (fr) => (LANG === "en" && typeof fr === "string" && Object.prototype.hasOwnProperty.call(EN, fr) ? EN[fr] : fr);
// The "Romain" tab (Romain, 06/10/2026) : « un onglet Romain où il y a toutes les questions en cours, que tout le monde
// peut consulter, mais il n'y a que moi qui peux agir dessus » ; « il faudra jamais oublier de me reporter les questions
// en cours, même si elles ont été discutées avec Rémy ou Garance ». The questions come from the admin console (the
// price-check-console service files every « QUESTION POUR ROMAIN ») and from the harvest of the decisions; the reports
// « à discuter » from the monitor's export. Everyone reads; only Romain settles a question: the server checks his Basic
// identity, the page only hides the buttons from the others.
const $ = (s) => document.querySelector(s);
function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === "class") n.className = attrs[k];
    else if (k === "text") n.textContent = attrs[k];
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  }
  for (const c of [].concat(kids || [])) if (c != null) n.append(c);
  return n;
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "X-AKS-Admin": "1", "Content-Type": "application/json" } }, opts || {}));
  const t = await r.text();
  let d = null; try { d = t ? JSON.parse(t) : null; } catch (e) {}
  if (!r.ok) throw new Error((d && d.error && d.error.message) || ("HTTP " + r.status));
  return d;
}
const setStatus = (t, busy) => { const f = $("#status"); f.textContent = t; f.className = busy ? "busy" : "idle"; };
(function () {
  const saved = localStorage.getItem("aks-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    localStorage.setItem("aks-theme", cur);
  });
})();

// "2026-10-06T18:43:00+02:00" -> "06/10 18:43", as the server wrote it
function stamp(s) {
  const m = /^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(s || ""));
  return m ? m[2] + "/" + m[1] + " " + m[3] + ":" + m[4] : String(s || "");
}
const SOURCE = { "récolte": T("récolte des décisions"), "console": T("console") };

let DATA = null, REPORTS = null;
const ANSWERS = {};  // typed answers, kept across a refresh
const BUSY = new Set();
const SENT = new Set();  // settled here, until the console service writes it down

function questionCard(q, owner) {
  const kids = [el("div", { class: "rm-head" }, [el("b", { text: q.id || "?" }),
      " · " + (q.from_label || q.from || "?") + " · " + stamp(q.at) + " · " + (SOURCE[q.source] || q.source || "")]),
    el("p", { class: "rm-text", text: q.text || "" })];
  if (SENT.has(q.id)) {
    kids.push(el("p", { class: "rm-pending", text: T("Réglée : la console l'enregistre dans quelques secondes.") }));
  } else if (owner) {
    const box = el("textarea", { class: "rm-answer", rows: "2", maxlength: "2000", "aria-label": T("Ta décision pour ") + q.id,
      placeholder: T("Ta décision (facultatif) : elle part à Claude et reste ici") });
    box.value = ANSWERS[q.id] || "";
    box.addEventListener("input", () => { ANSWERS[q.id] = box.value; });
    const btn = el("button", { type: "button", class: "rm-close", text: BUSY.has(q.id) ? T("Envoi…") : T("Régler ") + q.id,
      onclick: () => settle(q.id) });
    btn.disabled = BUSY.has(q.id);
    kids.push(el("div", { class: "rm-actions" }, [box, btn]));
  }
  return el("article", { class: "rm-item", id: "q-" + (q.id || "") }, kids);
}

function settledCard(q) {
  return el("article", { class: "rm-item settled" }, [
    el("div", { class: "rm-head" }, [el("b", { text: q.id || "?" }), " · " + (q.from_label || q.from || "?") + " · " + stamp(q.at) +
      T(" · réglée par ") + (q.closed_by || "?") + T(" le ") + stamp(q.closed_at)]),
    el("p", { class: "rm-text", text: q.text || "" }),
    q.answer ? el("p", { class: "rm-answer-shown", text: "→ " + q.answer }) : null]);
}

function discussCard(r) {
  const d = r.decision || {};
  return el("article", { class: "rm-item" }, [
    el("div", { class: "rm-head" }, [el("b", { text: r.product || "?" }), " · " + (r.edition || "") + " · " + (r.merchant || "") +
      T(" · offre ") + r.offer + T(" · à discuter par ") + (d.by || "?") + T(" le ") + stamp(d.at)]),
    d.note ? el("p", { class: "rm-text", text: d.note }) : null,
    el("a", { href: "price-check#offer-" + encodeURIComponent(String(r.offer)), text: T("Ouvrir le report") })]);
}

function render() {
  const d = DATA || { questions: [] }, owner = d.role === "owner";
  const all = (d.questions || []).filter((q) => q && typeof q === "object");
  const open = all.filter((q) => q.status === "open"), closed = all.filter((q) => q.status === "closed").reverse();
  $("#rm-count").textContent = "— " + open.length;
  $("#rm-who").textContent = owner ? T("Toi seul vois les boutons « Régler ».") : T("Seul Romain peut régler une question.");
  $("#rm-questions").replaceChildren(...(open.length ? open.map((q) => questionCard(q, owner)) : [el("p", { class: "pc-empty",
    text: d.available ? T("Aucune question en cours.") : T("Pas encore de questions : le service de la console ne les a pas écrites.") })]));
  const discuss = ((REPORTS && REPORTS.reports) || []).filter((r) => r && r.decision && r.decision.decision === "a_discuter");
  $("#rm-discuss-count").textContent = "— " + discuss.length;
  $("#rm-reports").replaceChildren(...(discuss.length ? discuss.map(discussCard)
    : [el("p", { class: "pc-empty", text: REPORTS ? T("Aucun report à discuter.") : T("Reports illisibles pour l'instant.") })]));
  $("#rm-closed-count").textContent = "— " + closed.length;
  $("#rm-settled").replaceChildren(...(closed.length ? closed.slice(0, 50).map(settledCard)
    : [el("p", { class: "pc-empty", text: T("Aucune question réglée.") })]));
}

async function settle(id) {
  if (BUSY.has(id)) return;
  BUSY.add(id);
  render();
  try {
    await api("api/romain/questions/close", { method: "POST", body: JSON.stringify({ question: id, note: ANSWERS[id] || "" }) });
    SENT.add(id);
    delete ANSWERS[id];
    setStatus(id + T(" réglée : la console l'enregistre et le dit à Claude"), false);
    setTimeout(load, 3000);
  } catch (e) {
    setStatus(id + T(" non réglée : ") + e.message, false);
  } finally {
    BUSY.delete(id);
    render();
  }
}

async function load() {
  setStatus(T("Lecture des questions…"), true);
  try {
    DATA = await api("api/romain/questions");
    for (const q of DATA.questions || []) if (q && q.status === "closed") SENT.delete(q.id);
    setStatus(T("Questions à jour"), false);
  } catch (e) {
    setStatus(T("Questions illisibles : ") + e.message, false);
  }
  try { REPORTS = await api("api/price-check/reports"); } catch (e) { REPORTS = null; }
  render();
}
$("#refresh").addEventListener("click", load);
setInterval(() => { if (document.visibilityState !== "hidden") load(); }, 30 * 1000);
load();

// ---- FR / EN : the fixed texts of the page (07/10/2026) ----
if (document.documentElement) {
  document.documentElement.setAttribute("data-lang", LANG);
  document.documentElement.setAttribute("lang", LANG);
}
for (const id of ["refresh", "theme"]) {
  const n = $("#" + id);
  if (n && n.getAttribute && n.getAttribute("title")) n.setAttribute("title", T(n.getAttribute("title")));
}
(() => {
  const btn = $("#lang");
  if (!btn) return;
  btn.textContent = LANG === "en" ? "FR" : "EN";
  btn.setAttribute("title", LANG === "en" ? "Passer en français" : "Switch to English");
  btn.addEventListener("click", () => {
    try { localStorage.setItem("aks-lang", LANG === "en" ? "fr" : "en"); } catch (e) { /* no storage */ }
    if (typeof location !== "undefined") location.reload();
  });
})();
