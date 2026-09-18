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

let RULES = [], PROPOSALS = [], RUN_ID = null, LISTS = {};
// « 21 » ne dit rien ; « 21 — Gift cards » se relit. Un id inconnu se voit.
const listLabel = (id) => LISTS[String(id)] || "liste inconnue";
const listCell = (id) => `${id} — ${listLabel(id)}`;

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "X-AKS-Admin": "1", "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d.error && d.error.message) || `HTTP ${r.status}`);
  return d;
}

function copy(text, msg) {
  navigator.clipboard?.writeText(text);
  $("#copy-msg").textContent = msg;
  setTimeout(() => ($("#copy-msg").textContent = ""), 2500);
}

// Une requête « sans désaccord » ne vise aucun vrai jeu et n'entre en conflit avec aucune
// autre liste. C'est le sous-ensemble qu'on peut coller sans rien arbitrer.
// AUDIT DU 2026-09-18 : `!r.measured` rendait « propre » TOUT ce qui n'était pas mesuré —
// donc, sans scan, la totalité des règles. Et une règle mesurée sur un scan TRONQUÉ affiche
// un collatéral nul par ABSENCE DE DONNÉES. Dans les deux cas il n'y a pas de preuve :
// le bouton ne doit rien promettre.
const clean = (r) => !!r.measured && !r.truncated && !r.collateral && !r.conflict;

function render() {
  const tb = $("#rules tbody");
  tb.replaceChildren(...RULES.map((r) => {
    const warn = r.collateral ? "bad" : (r.conflict ? "warn" : "");
    const cells = [
      el("td", {}, el("code", {}, r.sql)),
      el("td", { class: "rz" }, listCell(r.target)),
      el("td", { class: "rz tnum" }, r.measured ? String(r.hits) : "—"),
      el("td", { class: "rz tnum" }, r.measured ? String(r.agree) : "—"),
      el("td", { class: "rz tnum" }, r.measured ? String(r.conflict) : "—"),
      el("td", { class: "rz tnum " + warn }, r.measured ? String(r.collateral) : "—"),
      el("td", {}, el("button", { onclick: () => copy(r.sql, "requête copiée") }, "copier")),
    ];
    const row = el("tr", { class: warn }, cells);
    const notes = [];
    if (r.truncated) notes.push("mesuré sur un scan incomplet — ces comptes ne prouvent rien");
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

function renderProposals() {
  const box = $("#proposals-box");
  if (!PROPOSALS.length) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  // Le motif et la liste sont ÉDITABLES avant promotion (Romain 2026-09-18 : « dans le cas
  // où on a besoin d'hésiter, rajouter un tiret »). Toute édition rend la mesure affichée
  // périmée : on la refait, et le serveur la refait aussi avant d'accepter — éditer ne doit
  // pas devenir le moyen de contourner la seule garde de cette voie.
  $("#proposals tbody").replaceChildren(...PROPOSALS.map((p) => {
    const pat = el("input", { type: "text", value: p.pattern, class: "pat mono", size: "26" });
    const tgt = el("input", { type: "text", value: String(p.target), class: "rz mono", size: "4" });
    const tgtName = el("span", { class: "msg" }, listLabel(p.target));
    tgt.addEventListener("input", () => (tgtName.textContent = listLabel(tgt.value.trim())));
    const hits = el("td", { class: "rz tnum" }, String(p.hits));
    const agree = el("td", { class: "rz tnum" }, String(p.agree));
    const msg = el("span", { class: "msg" }, "");
    let fresh = true;

    const stale = () => {
      fresh = false;
      hits.textContent = "?"; agree.textContent = "?";
      msg.textContent = "édité — mesure à refaire";
    };
    pat.addEventListener("input", stale);
    tgt.addEventListener("input", stale);

    const remesure = async () => {
      const d = await post("api/sort/sql/measure",
                           { pattern: pat.value.trim(), target: tgt.value.trim(), run_id: RUN_ID });
      hits.textContent = d.measured ? String(d.hits) : "—";
      agree.textContent = d.measured ? String(d.agree) : "—";
      fresh = !!d.measured && !d.truncated && !d.collateral && !d.conflict;
      msg.textContent = !d.measured ? (d.note || "non mesurable")
        : d.truncated ? `✖ scan incomplet (${(d.coverage || {}).why || "couverture inconnue"}) — rien n'est prouvé`
        : d.collateral ? `✖ vise ${d.collateral} vrai(s) jeu(x) : ${(d.collateral_sample || []).join(" · ")}`
        : d.conflict ? `⚠ ${d.conflict} ligne(s) iraient sur une autre liste`
        : `✔ ${d.hits} ligne(s), aucun vrai jeu visé`;
      return d;
    };

    return el("tr", {}, [
      el("td", {}, [pat, msg]),
      el("td", { class: "rz" }, [tgt, tgtName]),
      hits, agree,
      el("td", {}, [
        el("button", {
          onclick: async (e) => {
            e.target.disabled = true;
            try { await remesure(); } catch (err) { msg.textContent = "erreur : " + err.message; }
            e.target.disabled = false;
          },
        }, "Mesurer"),
        el("button", {
          class: "primary",
          onclick: async (e) => {
            e.target.disabled = true;
            try {
              // Si le motif a été édité, on REMESURE tout seul au lieu d'exiger un clic de
              // plus : le serveur refera la mesure de son côté, donc rien n'est contourné,
              // et l'opérateur n'a pas à deviner qu'il manque une étape.
              if (!fresh) {
                const d = await remesure();
                if (!d.measured || d.truncated || d.collateral) {
                  e.target.disabled = false;
                  return;                      // remesure() a déjà écrit pourquoi
                }
              }
              await post("api/sort/sql/promote", {
                pattern: pat.value.trim(), target: tgt.value.trim(),
                run_id: RUN_ID, hits: p.hits, by: "console",
                // d'où elle vient : sans ça, un motif resserré laisse son original revenir
                origin: { pattern: p.pattern, target: String(p.target) },
              });
              $("#copy-msg").textContent = `${pat.value.trim()} promue — rechargement…`;
              location.reload();
            } catch (err) {
              e.target.disabled = false;
              msg.textContent = "refusée : " + err.message;
            }
          },
        }, "Promouvoir"),
        el("button", {
          title: "Ne plus proposer ce motif",
          onclick: async (e) => {
            e.target.disabled = true;
            try {
              await post("api/sort/sql/promote", {
                action: "dismiss", pattern: p.pattern, target: String(p.target), by: "console",
              });
              location.reload();
            } catch (err) {
              e.target.disabled = false;
              msg.textContent = "refus d'écarter : " + err.message;
            }
          },
        }, "Écarter"),
      ]),
    ]);
  }));
}

(async function init() {
  setStatus("Chargement…", true);
  try {
    const d = await api("api/sort/sql");
    RULES = d.rules || [];
    PROPOSALS = d.proposals || [];
    RUN_ID = d.run_id || null;
    LISTS = Object.fromEntries((d.lists || []).map((l) => [String(l.id), l.label]));
    $("#pending-id").textContent = d.pending_list || "9";
    $("#lists tbody").replaceChildren(...(d.lists || []).map((l) => el("tr", {}, [
      el("td", { class: "rz tnum" }, String(l.id)),
      el("td", {}, l.label),
    ])));
    const cov = d.coverage || {};
    $("#measured").className = d.measured && !d.truncated ? "note" : "note bad";
    $("#measured").textContent = !d.measured
      ? "Aucun scan de tri exploitable : les requêtes sont affichées SANS mesure. "
        + "Lance un scan de tri pour savoir ce qu'elles toucheraient."
      : d.truncated
        ? `⚠ SCAN INCOMPLET — ${cov.why || "couverture inconnue"}. Les comptes ci-dessous ne `
          + `portent que sur cet échantillon, alors que l'UPDATE balaie toute la table : un `
          + `collatéral à 0 ne prouve RIEN. Les propositions et l'arbitrage sont désactivés, `
          + `et la promotion sera refusée. Relance un scan complet (--max-pages 800).`
        : `Mesuré sur le scan ${d.run_id} — ${d.offers} offres, couverture complète `
          + `(${cov.pages_fetched}/${cov.feed_last_page} pages). Les comptes viennent de ce `
          + `scan, pas d'une estimation ; ils vieillissent avec lui.`;
    render();
    // Le bloc unique : certains préfèrent sélectionner à la main plutôt que se fier au
    // presse-papiers du navigateur, qui peut être refusé sans HTTPS ou sans geste direct.
    $("#all-sql").value = RULES.map((r) => r.sql).join("\n");
    const ret = d.retired || [];
    if (ret.length) {
      const box = el("div", { class: "note" }, [
        el("strong", {}, `${ret.length} règle(s) RETIRÉE(S) — ne pas les recoller depuis une ancienne liste :`),
        ...ret.map((r) => el("div", { class: "rz" }, `${r.pattern} — ${r.why}`)),
      ]);
      $("#measured").after(box);
    }
    renderProposals();
    const conf = d.conflicted || [];
    if (conf.length) {
      $("#conflicted-box").classList.remove("hidden");
      $("#conflicted tbody").replaceChildren(...conf.map((c) => el("tr", { class: "warn" }, [
        el("td", {}, el("code", {}, c.sql)),
        el("td", { class: "rz" }, listCell(c.target)),
        el("td", { class: "rz tnum" }, String(c.hits)),
        el("td", { class: "rz tnum" }, String(c.conflict)),
      ])));
    }
    setStatus(`${RULES.length} requêtes`
      + (PROPOSALS.length ? ` · ${PROPOSALS.length} proposition(s)` : ""));
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
