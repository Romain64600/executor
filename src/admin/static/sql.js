"use strict";
// Tri par SQL — affiche les requêtes de src/sort_sql_rules.py, MESURÉES contre le dernier
// scan de tri, prêtes à copier. Rien n'est exécuté ici : Romain les colle dans phpMyAdmin.
// C'est ce qui remplace le déplacement par le navigateur, dont le succès était la disparition
// PROUVÉE de la ligne. Ce contrôle d'après n'existe plus, donc tout se joue sur la mesure
// d'avant : on l'affiche à côté de chaque requête au lieu de la cacher.

const $ = (s, r = document) => r.querySelector(s);
const setStatus = (t, busy) => { const f = $("#status"); f.textContent = t; f.className = busy ? "busy" : "idle"; };

async function api(path) {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d.error && d.error.message) || `HTTP ${r.status}`);
  return d;
}

function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === "class") n.className = attrs[k];
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  }
  for (const c of [].concat(kids || [])) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c));
  return n;
}

let RULES = [];

function copy(text, msg) {
  navigator.clipboard?.writeText(text);
  $("#copy-msg").textContent = msg;
  setTimeout(() => ($("#copy-msg").textContent = ""), 2500);
}

// Une requête « sans désaccord » ne vise aucun vrai jeu et n'entre en conflit avec aucune
// autre liste. C'est le sous-ensemble qu'on peut coller sans rien arbitrer.
const clean = (r) => !r.measured || (!r.collateral && !r.conflict);

function render() {
  const tb = $("#rules tbody");
  tb.replaceChildren(...RULES.map((r) => {
    const warn = r.collateral ? "bad" : (r.conflict ? "warn" : "");
    const cells = [
      el("td", {}, el("code", {}, r.sql)),
      el("td", { class: "rz" }, String(r.target)),
      el("td", { class: "rz tnum" }, r.measured ? String(r.hits) : "—"),
      el("td", { class: "rz tnum" }, r.measured ? String(r.agree) : "—"),
      el("td", { class: "rz tnum" }, r.measured ? String(r.conflict) : "—"),
      el("td", { class: "rz tnum " + warn }, r.measured ? String(r.collateral) : "—"),
      el("td", {}, el("button", { onclick: () => copy(r.sql, "requête copiée") }, "copier")),
    ];
    const row = el("tr", { class: warn }, cells);
    const notes = [];
    if (r.flag) notes.push("⚠ " + r.flag);
    if (r.collateral) {
      notes.push("vrais jeux visés : " + (r.collateral_sample || []).join(" · "));
    }
    if (!notes.length) return row;
    const note = el("tr", { class: "noterow" },
      el("td", { colspan: "7" }, el("div", { class: "rz" }, notes.join("  —  "))));
    const frag = document.createDocumentFragment();
    frag.append(row, note);
    return frag;
  }));
}

(async function init() {
  setStatus("Chargement…", true);
  try {
    const d = await api("api/sort/sql");
    RULES = d.rules || [];
    $("#measured").textContent = d.measured
      ? `Mesuré sur le scan ${d.run_id} — ${d.offers} offres. Les comptes viennent de ce scan, `
        + `pas d'une estimation ; ils vieillissent avec lui.`
      : "Aucun scan de tri disponible : les requêtes sont affichées SANS mesure. "
        + "Lance un scan de tri pour savoir ce qu'elles toucheraient.";
    render();
    setStatus(`${RULES.length} requêtes`);
  } catch (e) {
    setStatus("Erreur : " + e.message);
  }
  $("#copy-all").addEventListener("click", () =>
    copy(RULES.map((r) => r.sql).join("\n"), `${RULES.length} requêtes copiées`));
  $("#copy-safe").addEventListener("click", () => {
    const keep = RULES.filter(clean);
    copy(keep.map((r) => r.sql).join("\n"),
         `${keep.length} requêtes copiées (${RULES.length - keep.length} écartées)`);
  });
})();

(function theme() {
  const saved = localStorage.getItem("aks-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const r = document.documentElement;
    const cur = r.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    r.setAttribute("data-theme", next); localStorage.setItem("aks-theme", next);
  });
})();
