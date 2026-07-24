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

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "X-AKS-Admin": "1", "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error?.message || `HTTP ${r.status}`);
  return data;
}

let BUSY = null;

function setBusy(busy) {
  BUSY = busy;
  const ind = $("#busy-ind");
  if (busy) {
    $("#busy-text").textContent =
      `${String(busy.kind || "run").replace("sort_", "").replace("_", "-")} en cours…`;
    ind.classList.remove("hidden");
  } else {
    ind.classList.add("hidden");
  }
  document.body.classList.toggle("is-busy", !!busy);
}

async function refreshBusy() {
  try { const d = await getJSON("api/sort/runs"); setBusy(d.busy || null); } catch (e) { /* ignore */ }
}

async function loadRuns() {
  setStatus("Chargement des scans…", true);
  const { runs, busy } = await getJSON("api/sort/runs");
  setBusy(busy || null);
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
  const moved = ((PLAN.moved_tally || {})[id] || {}).moved_total || 0;
  const meta = [
    el("span", { class: "pill todo" }, "au plan"),
    el("span", {}, `${stores} store${stores > 1 ? "s" : ""}`),
  ];
  meta.push(moved > 0
    ? el("span", { class: "pill moved", title: "réellement déplacées (cumul, prouvé RV2)" }, `✔ ${fmt(moved)} déplacées`)
    : el("span", { class: "pill gate" }, "canary requis"));
  const c = el("div", { class: "card" }, [
    el("div", { class: "card-head" }, [
      el("span", { class: "label" }, g.label || family),
      el("span", { class: "chip mono", style: `background:var(${CVAR[color]}-bg);color:var(${CVAR[color]})` }, "liste " + id),
    ]),
    el("div", { class: "big tnum", title: "compteur du plan (instantané figé du scan)" },
      [String(g.count), el("span", { class: "u" }, "au plan")]),
    el("div", { class: "card-meta" }, meta),
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

let POLL = null, OFFSET = 0;

function openList(id, g) {
  const [, family] = fam(id);
  $("#modal-title").textContent = `${g.label || family} — liste ${id} · ${fmt(g.count)} offres`;
  buildActions(id, g);
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
  stopPoll();
  $("#modal-status").classList.add("hidden");
  $("#modal-status").replaceChildren();
  $("#offers-modal").showModal();
}

function buildActions(id, g) {
  const go = el("input", { type: "text", placeholder: "GO", class: "go-in", autocomplete: "off" });
  const canary = el("button", { class: "primary", disabled: "" }, "Canary (1 move)");
  const batch = el("button", { class: "danger", disabled: "" }, `Batch (${fmt(g.count)})`);
  const sync = () => { const ok = go.value.trim().toUpperCase() === "GO"; canary.disabled = batch.disabled = !ok; };
  go.addEventListener("input", sync);
  canary.addEventListener("click", () => runAction(id, "canary", go));
  batch.addEventListener("click", () => runAction(id, "batch", go));
  $("#modal-actions").replaceChildren(
    el("button", { onclick: () => runAction(id, "dry_run", null) }, "Dry-run"),
    el("span", { class: "aspacer" }),
    el("span", { class: "golabel" }, "GO :"), go, canary, batch,
    el("div", { class: "gatehint" },
      "Dry-run = aperçu (aucune écriture). Canary = 1 déplacement prouvé (autorise la liste). "
      + "Batch = liste complète, exige un canary validé. Chaque move prouve source+cible (RV2)."),
  );
}

async function runAction(id, action, goInput) {
  if ((action === "canary" || action === "batch")
      && (!goInput || goInput.value.trim().toUpperCase() !== "GO")) return;
  const body = { list_id: id, action };
  if (action !== "dry_run") body.confirm = "GO";
  $("#modal-actions").querySelectorAll("button,input").forEach((n) => (n.disabled = true));
  // The run's event log is shared across every action on this run — start
  // reading from its CURRENT end so the pane shows only THIS action's events,
  // not replayed history from earlier canaries/dry-runs.
  try {
    const base = await getJSON(`api/runs/${encodeURIComponent(RUN_ID)}/submit/status?offset=0`);
    OFFSET = base.offset ?? 0;
  } catch (e) { OFFSET = 0; }
  showStatusPane(`▶ ${action.replace("_", "-")} — liste ${id} — lancement…`);
  setStatus(`Lancement ${action}…`, true);
  try {
    await postJSON(`api/runs/${encodeURIComponent(RUN_ID)}/sort/move`, body);
  } catch (e) {
    appendStatus("✖ refusé : " + e.message);
    setStatus("Refusé — " + e.message);
    $("#modal-actions").querySelectorAll("button,input").forEach((n) => (n.disabled = false));
    return;
  }
  if (goInput) goInput.value = "";
  startPoll();
}

function showStatusPane(msg) {
  const p = $("#modal-status");
  p.classList.remove("hidden");
  p.replaceChildren();
  appendStatus(msg);   // OFFSET is set by the caller to the log's current end
}
function appendStatus(line, cls) {
  const p = $("#modal-status");
  p.append(el("div", { class: "logline" + (cls ? " " + cls : "") }, line));
  p.scrollTop = p.scrollHeight;
}
function stopPoll() { if (POLL) { clearInterval(POLL); POLL = null; } }

function fmtEvent(ev) {
  const n = ev.event || "";
  if (n === "feed_indexed") return `· feed indexé (${fmt(ev.offers)} offres)`;
  if (n === "row_relocated") return `· offre relocalisée (${ev.current_offer_id})`;
  if (n === "move_submitted") return `→ Apply envoyé (offre ${ev.current_offer_id} → liste ${ev.target_list_id})`;
  if (n === "move_verified") return ev.moved ? `✔ MOVED — prouvé source+cible` : `✖ non confirmé (${ev.on_target ? "" : "absent cible"})`;
  if (n === "move_blocked") return `⛔ bloqué : ${ev.reason || ""}`;
  if (n === "move_skipped") return `↷ ignoré : ${ev.reason || ""}`;
  if (n === "run_stopped") return `■ stop : ${ev.reason || ""}`;
  if (n === "aborted") return `■ abandon : ${ev.reason || ""}`;
  return null;
}

function startPoll() {
  stopPoll();
  const tick = async () => {
    let s;
    try { s = await getJSON(`api/runs/${encodeURIComponent(RUN_ID)}/submit/status?offset=${OFFSET}`); }
    catch (e) { return; }
    OFFSET = s.offset ?? OFFSET;
    for (const ev of (s.events || [])) { const line = fmtEvent(ev); if (line) appendStatus(line); }
    const running = s.state === "running";
    setBusy(s.busy || null);
    setStatus(running ? "Déplacement en cours…" : `Terminé (${s.state})`, running);
    if (!running) { stopPoll(); finishStatus(s); }
  };
  POLL = setInterval(tick, 1500);
  tick();
}

function finishStatus(s) {
  const tail = (s.stdout_tail || "").trim().split("\n").filter(Boolean).slice(-3);
  for (const line of tail) appendStatus(line, /moved=|MOVED/.test(line) ? "ok" : (/refus|abort|FAILED|BLOCK/i.test(line) ? "bad" : ""));
  appendStatus(s.exit_code === 0 ? "— terminé (exit 0)" : `— terminé (exit ${s.exit_code})`, s.exit_code === 0 ? "ok" : "bad");
  $("#modal-actions").querySelectorAll("button,input").forEach((n) => (n.disabled = false));
  refreshBusy().catch(() => {});          // clear the busy indicator
  loadPlan().catch(() => {});             // refresh the cards' moved tally
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
$("#stop-btn").addEventListener("click", async () => {
  const b = $("#stop-btn");
  b.disabled = true;
  b.textContent = "Arrêt…";
  try {
    await postJSON("api/sort/stop", {});
    appendStatus("■ arrêt demandé — le run s'arrête au prochain point sûr (fin de page/offre)…");
    setStatus("Arrêt demandé…", true);
  } catch (e) {
    setStatus("Arrêt : " + e.message);
  }
  setTimeout(() => { b.disabled = false; b.textContent = "Arrêter"; refreshBusy(); }, 1500);
});
setInterval(refreshBusy, 4000);   // keep the busy indicator live across tabs/runs
$("#modal-close").addEventListener("click", () => { stopPoll(); $("#offers-modal").close(); });
$("#offers-modal").addEventListener("click", (e) => { if (e.target.id === "offers-modal") { stopPoll(); e.target.close(); } });

loadRuns().catch((e) => { banner("Erreur de chargement : " + e.message); setStatus("Erreur"); });
