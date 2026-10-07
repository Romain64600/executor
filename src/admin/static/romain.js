"use strict";
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
const SOURCE = { "récolte": "récolte des décisions", "console": "console" };

let DATA = null, REPORTS = null;
const ANSWERS = {};  // typed answers, kept across a refresh
const BUSY = new Set();
const SENT = new Set();  // settled here, until the console service writes it down

function questionCard(q, owner) {
  const kids = [el("div", { class: "rm-head" }, [el("b", { text: q.id || "?" }),
      " · " + (q.from_label || q.from || "?") + " · " + stamp(q.at) + " · " + (SOURCE[q.source] || q.source || "")]),
    el("p", { class: "rm-text", text: q.text || "" })];
  if (SENT.has(q.id)) {
    kids.push(el("p", { class: "rm-pending", text: "Réglée : la console l'enregistre dans quelques secondes." }));
  } else if (owner) {
    const box = el("textarea", { class: "rm-answer", rows: "2", maxlength: "2000", "aria-label": "Ta décision pour " + q.id,
      placeholder: "Ta décision (facultatif) : elle part à Claude et reste ici" });
    box.value = ANSWERS[q.id] || "";
    box.addEventListener("input", () => { ANSWERS[q.id] = box.value; });
    const btn = el("button", { type: "button", class: "rm-close", text: BUSY.has(q.id) ? "Envoi…" : "Régler " + q.id,
      onclick: () => settle(q.id) });
    btn.disabled = BUSY.has(q.id);
    kids.push(el("div", { class: "rm-actions" }, [box, btn]));
  }
  return el("article", { class: "rm-item", id: "q-" + (q.id || "") }, kids);
}

function settledCard(q) {
  return el("article", { class: "rm-item settled" }, [
    el("div", { class: "rm-head" }, [el("b", { text: q.id || "?" }), " · " + (q.from_label || q.from || "?") + " · " + stamp(q.at) +
      " · réglée par " + (q.closed_by || "?") + " le " + stamp(q.closed_at)]),
    el("p", { class: "rm-text", text: q.text || "" }),
    q.answer ? el("p", { class: "rm-answer-shown", text: "→ " + q.answer }) : null]);
}

function discussCard(r) {
  const d = r.decision || {};
  return el("article", { class: "rm-item" }, [
    el("div", { class: "rm-head" }, [el("b", { text: r.product || "?" }), " · " + (r.edition || "") + " · " + (r.merchant || "") +
      " · offre " + r.offer + " · à discuter par " + (d.by || "?") + " le " + stamp(d.at)]),
    d.note ? el("p", { class: "rm-text", text: d.note }) : null,
    el("a", { href: "price-check#offer-" + encodeURIComponent(String(r.offer)), text: "Ouvrir le report" })]);
}

function render() {
  const d = DATA || { questions: [] }, owner = d.role === "owner";
  const all = (d.questions || []).filter((q) => q && typeof q === "object");
  const open = all.filter((q) => q.status === "open"), closed = all.filter((q) => q.status === "closed").reverse();
  $("#rm-count").textContent = "— " + open.length;
  $("#rm-who").textContent = owner ? "Toi seul vois les boutons « Régler »." : "Seul Romain peut régler une question.";
  $("#rm-questions").replaceChildren(...(open.length ? open.map((q) => questionCard(q, owner)) : [el("p", { class: "pc-empty",
    text: d.available ? "Aucune question en cours." : "Pas encore de questions : le service de la console ne les a pas écrites." })]));
  const discuss = ((REPORTS && REPORTS.reports) || []).filter((r) => r && r.decision && r.decision.decision === "a_discuter");
  $("#rm-discuss-count").textContent = "— " + discuss.length;
  $("#rm-reports").replaceChildren(...(discuss.length ? discuss.map(discussCard)
    : [el("p", { class: "pc-empty", text: REPORTS ? "Aucun report à discuter." : "Reports illisibles pour l'instant." })]));
  $("#rm-closed-count").textContent = "— " + closed.length;
  $("#rm-settled").replaceChildren(...(closed.length ? closed.slice(0, 50).map(settledCard)
    : [el("p", { class: "pc-empty", text: "Aucune question réglée." })]));
}

async function settle(id) {
  if (BUSY.has(id)) return;
  BUSY.add(id);
  render();
  try {
    await api("api/romain/questions/close", { method: "POST", body: JSON.stringify({ question: id, note: ANSWERS[id] || "" }) });
    SENT.add(id);
    delete ANSWERS[id];
    setStatus(id + " réglée : la console l'enregistre et le dit à Claude", false);
    setTimeout(load, 3000);
  } catch (e) {
    setStatus(id + " non réglée : " + e.message, false);
  } finally {
    BUSY.delete(id);
    render();
  }
}

async function load() {
  setStatus("Lecture des questions…", true);
  try {
    DATA = await api("api/romain/questions");
    for (const q of DATA.questions || []) if (q && q.status === "closed") SENT.delete(q.id);
    setStatus("Questions à jour", false);
  } catch (e) {
    setStatus("Questions illisibles : " + e.message, false);
  }
  try { REPORTS = await api("api/price-check/reports"); } catch (e) { REPORTS = null; }
  render();
}
$("#refresh").addEventListener("click", load);
setInterval(() => { if (document.visibilityState !== "hidden") load(); }, 30 * 1000);
load();
