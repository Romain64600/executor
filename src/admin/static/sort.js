"use strict";
// Tri des listes — triage console. Read-only view of a sort_plan.json: KPI
// summary + a kanban card per target list. Execution stays on the gated CLI
// (09_sort_move.py) — each card surfaces the exact copyable command, in order:
// dry-run → canary (learning) → batch (safe, --i-authorize-batch).

const $ = (s, r = document) => r.querySelector(s);
function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === "class") n.className = attrs[k];
    else if (k === "html") n.innerHTML = attrs[k];
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  }
  for (const c of [].concat(kids || [])) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c));
  return n;
}
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("fr-FR"));

// list id → category colour + human family
const FAMILY = {
  "8": ["red", "Blacklist"], "26": ["red", "Blacklist"], "14": ["red", "Blacklist"], "37": ["red", "Blacklist"], "31": ["red", "Blacklist"],
  "16": ["blue", "Softwares"], "21": ["amber", "Gift cards"], "42": ["amber", "Gift cards"],
  "30": ["purple", "Comptes"], "43": ["purple", "Comptes"],
  "32": ["teal", "Régionale"], "33": ["teal", "Régionale"], "34": ["teal", "Régionale"], "35": ["teal", "Régionale"], "36": ["teal", "Régionale"],
};
const fam = (id) => FAMILY[String(id)] || ["grey", "Liste"];
const CVAR = { red: "--c-red", blue: "--c-blue", amber: "--c-amber", purple: "--c-purple", teal: "--c-teal", grey: "--c-grey" };

let RUN_ID = null;
let PLAN = null;

function setStatus(msg, busy) { const f = $("#status"); f.textContent = msg; f.className = busy ? "busy" : "idle"; }
function banner(msg) { const b = $("#banner"); if (!msg) { b.className = "banner hidden"; return; } b.textContent = msg; b.className = "banner"; }

async function getJSON(url) {
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error?.message || `HTTP ${r.status}`);
  return r.json();
}

async function loadRuns() {
  setStatus("Chargement des scans…", true);
  const { runs } = await getJSON("api/sort/runs");
  const picker = $("#run-picker");
  picker.innerHTML = "";
  if (!runs.length) {
    $("#empty").textContent = "Aucun scan de tri. Lance scripts/08_sort_plan.py pour en produire un.";
    $("#console").classList.add("hidden"); $("#empty").classList.remove("hidden");
    setStatus("Prêt"); return;
  }
  for (const r of runs) {
    const routed = r.counts?.routed;
    picker.append(el("option", { value: r.run_id }, `${r.run_id}  ·  ${fmt(routed)} routables`));
  }
  RUN_ID = runs[0].run_id;
  picker.value = RUN_ID;
  await loadPlan();
}

async function loadPlan() {
  setStatus("Chargement du plan…", true);
  banner("");
  try {
    PLAN = await getJSON(`api/runs/${encodeURIComponent(RUN_ID)}/sort`);
  } catch (e) {
    $("#empty").textContent = "Plan illisible : " + e.message;
    $("#empty").classList.remove("hidden"); $("#console").classList.add("hidden");
    setStatus("Erreur"); return;
  }
  render();
  setStatus(`Plan chargé — ${fmt(PLAN.counts?.total)} offres`);
}

function render() {
  $("#empty").classList.add("hidden");
  $("#console").classList.remove("hidden");
  const c = PLAN.counts || {}, cov = PLAN.coverage || {};

  const kpi = (n, l, cls) => el("div", { class: "kpi " + (cls || "") },
    [el("div", { class: "n tnum" }, fmt(n)), el("div", { class: "l" }, l)]);
  const covText = cov.truncated
    ? `partielle — ${fmt(cov.pages_fetched)} / ${fmt(cov.feed_last_page)} pages`
    : `pleine — ${fmt(cov.pages_fetched)} pages`;
  $("#summary").replaceChildren(
    kpi(c.routed, "Routables → liste", "hi"),
    kpi(c.target_lists, "Listes cibles"),
    kpi(c.unrouted_skips, "À garder"),
    kpi(c.candidates, "Candidats création"),
    el("div", { class: "kpi cov" }, [
      el("div", { class: "l" }, "Couverture"),
      el("div", { class: "n tnum", style: "font-size:1rem" }, covText),
      el("div", { class: "l" }, `${fmt(c.total)} offres · tous stores`)]),
  );

  const lists = Object.entries(PLAN.by_list || {}).sort((a, b) => (b[1].count || 0) - (a[1].count || 0));
  $("#board").replaceChildren(...lists.map(([id, g]) => card(id, g)));

  $("#secondary").replaceChildren(
    note(c.unrouted_skips, "À garder — skips sans liste sûre (devises, console, DLC, bundles). Restent dans Pending, décision opérateur."),
    note(c.candidates, "Candidats création — passent le precheck. Traités par le flux Validation/Submit, hors tri."),
  );
}

function card(id, g) {
  const [color, family] = fam(id);
  const stores = new Set((g.offers || []).map((o) => o.store_id)).size;
  const c = el("div", { class: "card" }, [
    el("div", { class: "card-head" }, [
      el("span", { class: "label" }, g.label || family),
      el("span", { class: "chip mono", style: `background:var(${CVAR[color]}-bg);color:var(${CVAR[color]})` }, "liste " + id),
    ]),
    el("div", { class: "big tnum" }, [String(g.count), el("span", { class: "u" }, "offres")]),
    el("div", { class: "card-meta" }, [
      el("span", { class: "pill todo" }, "À valider"),
      el("span", {}, `${stores} store${stores > 1 ? "s" : ""}`),
      el("span", { class: "pill gate" }, "canary requis"),
    ]),
    el("div", { class: "card-actions" }, [
      el("button", { class: "linkbtn", onclick: () => openList(id, g) }, "Voir les offres →"),
      el("span", { class: "grow" }),
      el("button", { class: "small", title: "Commandes de déplacement (CLI supervisé)", onclick: () => openList(id, g) }, "Déplacer…"),
    ]),
  ]);
  c.style.setProperty("--stripe", `var(${CVAR[color]})`);
  return c;
}

function note(n, t) {
  return el("div", { class: "note" }, [el("div", { class: "n tnum" }, fmt(n)), el("div", { class: "t" }, t)]);
}

function cmdRow(tag, cmd) {
  return el("div", { class: "cmd" }, [
    el("span", { class: "tag" }, tag),
    el("code", {}, cmd),
    el("button", { onclick: (e) => { navigator.clipboard?.writeText(cmd); e.target.textContent = "copié"; setTimeout(() => e.target.textContent = "copier", 1200); } }, "copier"),
  ]);
}

function openList(id, g) {
  const [, family] = fam(id);
  $("#modal-title").textContent = `${g.label || family} — liste ${id} · ${fmt(g.count)} offres`;
  const base = `python3 scripts/09_sort_move.py runs/${RUN_ID} --list ${id}`;
  $("#modal-cmds").replaceChildren(
    cmdRow("dry-run", base),
    cmdRow("canary", `${base} --execute --mode learning`),
    cmdRow("batch", `${base} --execute --mode safe --i-authorize-batch`),
  );
  const tb = $("#modal-table tbody");
  tb.replaceChildren(...(g.offers || []).map((o) => el("tr", {}, [
    el("td", { class: "c-store" }, o.store_id || "—"),
    el("td", {}, [el("div", {}, o.name || ""), o.url ? el("a", { href: o.url, target: "_blank", rel: "noopener" }, o.url) : null]),
    el("td", { class: "rz" }, (o.reason || "").replace(/^skip category:\s*/, "")),
  ])));
  $("#offers-modal").showModal();
}

// theme, wiring
(function theme() {
  const saved = localStorage.getItem("sort-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const r = document.documentElement;
    const cur = r.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    r.setAttribute("data-theme", next); localStorage.setItem("sort-theme", next);
  });
})();
$("#run-picker").addEventListener("change", (e) => { RUN_ID = e.target.value; loadPlan(); });
$("#refresh").addEventListener("click", loadRuns);
$("#modal-close").addEventListener("click", () => $("#offers-modal").close());
$("#offers-modal").addEventListener("click", (e) => { if (e.target.id === "offers-modal") e.target.close(); });

loadRuns().catch((e) => { banner("Erreur de chargement : " + e.message); setStatus("Erreur"); });
