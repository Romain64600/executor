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

// The scan whose plan is ACTUALLY on screen, and a sequence token so a slow answer from a
// previously selected scan can never repaint over a newer one (audit de Romain 2026-09-16:
// « le GO peut viser un autre scan que celui affiché » — plan A displayed, move sent for B).
// Every action reads PLAN_RUN_ID, never the picker's current value. And a GATED action does
// not read it at all: the identity of the plan the CARDS were painted from travels with them
// (render → card → openList → MODAL_RUN_ID / MODAL_DIGEST), so a plan that finishes loading
// while a modal is open cannot redirect the GO (audit de Romain 2026-09-17, deux passes).
let PLAN_RUN_ID = null;
let LOAD_SEQ = 0;

async function loadPlan() {
  const seq = ++LOAD_SEQ;
  const wanted = RUN_ID;
  setStatus("Chargement du plan…", true);
  banner("");
  let plan;
  try {
    plan = await getJSON(`api/runs/${encodeURIComponent(wanted)}/sort`);
  } catch (e) {
    if (seq !== LOAD_SEQ) return;            // a newer load owns the screen
    $("#empty").textContent = "Plan illisible : " + e.message;
    $("#empty").classList.remove("hidden"); $("#console").classList.add("hidden");
    setStatus("Erreur"); return;
  }
  if (seq !== LOAD_SEQ) return;              // stale answer — drop it, never repaint
  PLAN = plan;
  PLAN_RUN_ID = wanted;
  render();
  setStatus(`Plan chargé — ${fmt(PLAN.counts?.total)} offres`);
}

function fmtAge(ms) {
  const h = ms / 3.6e6;
  if (h < 1) return `${Math.round(ms / 6e4)} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${Math.round(h / 24)} j`;
}

function planAgeBanner() {
  const b = $("#banner");
  const at = PLAN.fetched_at;
  if (!at) { b.className = "banner hidden"; return; }
  const age = Date.now() - Date.parse(at);
  if (age >= 2 * 3.6e6) {   // >2h → stale, mostly phantoms
    b.textContent = `⚠ Plan scanné il y a ${fmtAge(age)} — churn / dérive d'identité depuis. `
      + `Re-scanne avant de batcher, sinon la plupart seront des phantoms (déjà parties / identité changée).`;
    b.className = "banner";
  } else {
    b.className = "banner hidden";
  }
}

function render() {
  $("#empty").classList.add("hidden");
  $("#console").classList.remove("hidden");
  const c = PLAN.counts || {}, cov = PLAN.coverage || {};
  planAgeBanner();

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

  // The identity of the plan these cards are painted from travels WITH them (audit de
  // Romain 2026-09-17, 2e passe). Freezing at the click was still too late: a loadPlan()
  // landing between the click and the GO swapped the globals while the modal kept showing
  // the offers of the plan the operator had opened. Bound here, the whole chain
  // card → openList → commandes → GO → suivi speaks about ONE plan.
  const runId = PLAN_RUN_ID, planDigest = PLAN && PLAN.plan_digest;
  const lists = Object.entries(PLAN.by_list || {}).sort((a, b) => (b[1].count || 0) - (a[1].count || 0));
  $("#board").replaceChildren(...lists.map(([id, g]) => card(id, g, runId, planDigest)));

  $("#secondary").replaceChildren(
    note(c.unrouted_skips, "À garder — skips sans liste sûre (devises, console, bundles, DLC sans page AKS propre). Restent dans Pending, décision opérateur."),
    note(c.candidates, "Candidats création — passent le precheck. Traités par le flux Validation/Submit, hors tri."),
  );
}

function card(id, g, runId, planDigest) {
  const [color, family] = fam(id);
  const stores = new Set((g.offers || []).map((o) => o.store_id)).size;
  const moved = ((PLAN.moved_tally || {})[id] || {}).moved_total || 0;
  const meta = [
    el("span", { class: "pill todo" }, "au plan"),
    el("span", {}, `${stores} store${stores > 1 ? "s" : ""}`),
  ];
  const movedTitle = family === "Blacklist"
    ? "réellement déplacées (cumul ; départ source prouvé — éviction, cible non re-scannée)"
    : "réellement déplacées (cumul, prouvé source+cible RV2)";
  meta.push(moved > 0
    ? el("span", { class: "pill moved", title: movedTitle }, `✔ ${fmt(moved)} déplacées`)
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
      el("button", { class: "linkbtn", onclick: () => openList(id, g, runId, planDigest) }, "Voir les offres →"),
      el("span", { class: "grow" }),
      el("button", { class: "small", title: "Commandes de déplacement (CLI supervisé)", onclick: () => openList(id, g, runId, planDigest) }, "Déplacer…"),
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

let POLL = null, POLL_SEQ = 0, OFFSET = 0, BATCHED = false, DEFERRED = false;
// The plan the OPEN modal belongs to — set when it opens, cleared when it closes. Every
// command shown, every GO and every poll reads these, never the mutable PLAN_RUN_ID / PLAN.
// MODAL_SEQ identifies the OPENING itself, not just the plan (audit de Romain, 3e passe):
// changing list inside the SAME scan is a new window too, and an action launched from the
// previous one must not paint into it — comparing the run alone could not see that.
let MODAL_RUN_ID = null, MODAL_DIGEST = null, MODAL_SEQ = 0;

function renderCmds(id) {
  // The exact copyable CLI, tracking the "Batché" toggle. Batched = the fast
  // many-offers-per-Apply path; its canary must fire a >=2-item Apply (--limit 2)
  // and its full list needs that multi-item proof. "Différé" (P1.6) only rides on
  // the batched FULL list — one verify per store — never the canary.
  const base = `python3 scripts/09_sort_move.py runs/${MODAL_RUN_ID} --list ${id}`;
  const canaryCmd = BATCHED
    ? `${base} --execute --mode learning --batch --limit 2`
    : `${base} --execute --mode learning`;
  const batchCmd = BATCHED
    ? `${base} --execute --mode safe --batch --i-authorize-batch${DEFERRED ? " --deferred" : ""}`
    : `${base} --execute --mode safe --i-authorize-batch`;
  $("#modal-cmds").replaceChildren(
    cmdRow("dry-run", base),
    cmdRow(BATCHED ? "canary multi-item" : "canary", canaryCmd),
    cmdRow(BATCHED ? "batch groupé" : "batch", batchCmd),
  );
}

function openList(id, g, runId, planDigest) {
  const [, family] = fam(id);
  // Take the identity of the plan these offers came from BEFORE anything is rendered, and
  // retire whatever the PREVIOUS opening had in flight.
  MODAL_SEQ++;
  MODAL_RUN_ID = runId || null;
  MODAL_DIGEST = planDigest || null;
  $("#modal-title").textContent = `${g.label || family} — liste ${id} · ${fmt(g.count)} offres`;
  BATCHED = false;
  DEFERRED = false;
  buildActions(id, g);
  renderCmds(id);
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
  const toggle = el("input", { type: "checkbox" });
  // "Différé (par store)" is a sub-option of Batché that rides ONLY on the full
  // Batch (not the canary) — disabled until Batché is on.
  const dtoggle = el("input", { type: "checkbox", disabled: "" });
  const relabel = () => {
    canary.textContent = BATCHED ? "Canary multi-item (2)" : "Canary (1 move)";
    batch.textContent = BATCHED
      ? `Batch groupé${DEFERRED ? " différé" : ""} (${fmt(g.count)})`
      : `Batch (${fmt(g.count)})`;
  };
  toggle.addEventListener("change", () => {
    BATCHED = toggle.checked;
    // Deferred only makes sense batched — clear + disable it when Batché is off.
    dtoggle.disabled = !BATCHED;
    if (!BATCHED) { DEFERRED = false; dtoggle.checked = false; }
    relabel();
    renderCmds(id);
  });
  dtoggle.addEventListener("change", () => { DEFERRED = dtoggle.checked; relabel(); renderCmds(id); });
  const sync = () => { const ok = go.value.trim().toUpperCase() === "GO"; canary.disabled = batch.disabled = !ok; };
  go.addEventListener("input", sync);
  canary.addEventListener("click", () => runAction(id, "canary", go, BATCHED, false));
  batch.addEventListener("click", () => runAction(id, "batch", go, BATCHED, DEFERRED));
  relabel();
  $("#modal-actions").replaceChildren(
    el("button", { onclick: () => runAction(id, "dry_run", null, false, false) }, "Dry-run"),
    el("span", { class: "aspacer" }),
    el("label", { class: "batched-toggle",
      title: "Moves groupés : N offres par Apply (~50-100× plus rapide). Le canary batché "
           + "fait un Apply de 2 (preuve multi-item) ; le lot complet exige cette preuve." },
      [toggle, " Batché (rapide)"]),
    el("label", { class: "batched-toggle deferred-toggle",
      title: "Vérif différée PAR STORE : le lot complet ne re-scanne qu'UNE fois par store "
           + "(au lieu d'une fois par groupe/page) → ~G× moins de scans sur un gros feed. "
           + "Exige « Batché ». Élargit la fenêtre d'attribution aux minutes (bornée au store)." },
      [dtoggle, " Différé (par store)"]),
    el("span", { class: "aspacer" }),
    el("span", { class: "golabel" }, "GO :"), go, canary, batch,
    el("div", { class: "gatehint" },
      "Dry-run = aperçu (aucune écriture). Canary = déplacement prouvé (autorise la liste). "
      + "Batch = liste complète, exige un canary validé. « Batché » groupe N offres/Apply "
      + "(rapide) et exige un canary multi-item. « Différé » = une vérif par store sur le lot "
      + "complet (plus rapide, fenêtre par store). Chaque move prouve le départ source ; la "
      + "cible est vérifiée (RV2), sauf éviction blacklist (cible non re-scannée)."),
  );
}

async function runAction(id, action, goInput, batched, deferred) {
  if ((action === "canary" || action === "batch")
      && (!goInput || goInput.value.trim().toUpperCase() !== "GO")) return;
  // The action belongs to the plan THIS MODAL was opened from — not to whatever the page
  // has loaded since (audit de Romain 2026-09-17, 2e passe: « le gel au clic arrive trop
  // tard », B chargé pendant que la fenêtre de A reste ouverte). The identity was bound at
  // render time and carried card → openList → here; the server's digest gate cannot catch
  // a swap on its own, since the swapped-in digest is genuinely that run's current one.
  const runId = MODAL_RUN_ID;
  const planDigest = MODAL_DIGEST;
  const seq = MODAL_SEQ;        // THIS opening. Checked after every await, errors included.
  if (!runId) return;                       // no open plan → nothing was approved
  // The pane and the buttons belong to the window that is open NOW. Once this opening is
  // retired — closed, or replaced by another list of the SAME scan — nothing below may
  // touch them: a late answer would otherwise paint one list's outcome into another's
  // window and re-enable ITS buttons mid-launch (audit de Romain, 3e passe).
  const gone = () => seq !== MODAL_SEQ;
  const abandon = (what) => {
    setStatus(`${what} sur ${runId} (liste ${id}) — la fenêtre a été fermée depuis`);
    if (goInput) goInput.value = "";
  };
  const body = { list_id: id, action };
  if (action !== "dry_run") body.confirm = "GO";
  if (batched) body.batched = true;
  // Deferred is a batched FULL-list option only — never on the canary/dry-run.
  if (deferred && batched && action === "batch") body.deferred = true;
  $("#modal-actions").querySelectorAll("button,input").forEach((n) => (n.disabled = true));
  // The run's event log is shared across every action on this run — start
  // reading from its CURRENT end so the pane shows only THIS action's events,
  // not replayed history from earlier canaries/dry-runs.
  let base = null;
  try {
    base = await getJSON(`api/runs/${encodeURIComponent(runId)}/submit/status?offset=0`);
  } catch (e) { base = null; }
  if (gone()) return;                       // window replaced while we read the log offset
  OFFSET = (base && base.offset) ?? 0;
  const tag = action.replace("_", "-")
    + (batched ? (body.deferred ? " (batché · différé)" : " (batché)") : "");
  showStatusPane(`▶ ${tag} — liste ${id} — lancement…`);
  setStatus(`Lancement ${tag}…`, true);
  try {
    // the run the plan on screen AT THE CLICK came from, plus that plan's identity — the
    // server still refuses the move if the two no longer agree (409 plan_changed)
    body.plan_digest = planDigest;
    await postJSON(`api/runs/${encodeURIComponent(runId)}/sort/move`, body);
  } catch (e) {
    // The REFUSAL is bound to its window exactly like the success is: before this check a
    // late error from list 8 painted "✖ refusé" into list 16 and re-enabled ITS buttons.
    if (gone()) { abandon("Action refusée"); return; }
    appendStatus("✖ refusé : " + e.message);
    setStatus("Refusé — " + e.message);
    $("#modal-actions").querySelectorAll("button,input").forEach((n) => (n.disabled = false));
    return;
  }
  // The status pane belongs to the window that is open NOW. If it was closed, or replaced by
  // another list — of this scan or another — while the POST was in flight, this action's
  // output has no home: painting would show one list's "terminé (exit 0)" inside another's
  // window, and startPoll would tail it there. The action itself is fine and running
  // server-side — we say so on the page's own status line, which belongs to no window.
  if (gone()) { abandon("Action lancée"); return; }
  if (PLAN_RUN_ID !== runId) {
    // the action is the one that was approved; the CARDS on screen are another scan's
    appendStatus(`⚠ le scan affiché a changé pendant l'envoi — cette action porte sur ${runId}`, "bad");
  }
  if (goInput) goInput.value = "";
  startPoll(runId);
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
// Stopping also RETIRES the current generation: clearInterval cannot cancel a tick whose
// getJSON is already in flight, so the generation token is what actually disarms it.
function stopPoll() { POLL_SEQ++; if (POLL) { clearInterval(POLL); POLL = null; } }

function fmtEvent(ev) {
  const n = ev.event || "";
  if (n === "feed_indexed") return `· feed indexé (${fmt(ev.offers)} offres)`;
  if (n === "row_relocated") return `· offre relocalisée (${ev.current_offer_id})`;
  if (n === "move_submitted") return `→ Apply envoyé (offre ${ev.current_offer_id} → liste ${ev.target_list_id})`;
  if (n === "move_verified") {
    if (!ev.moved) return `✖ non confirmé (${ev.on_target === false ? "absent cible" : "encore source"})`;
    if (ev.target === "blacklist") return `✔ évincé → blacklist (départ source prouvé ; cible non re-scannée)`;
    return `✔ MOVED — prouvé source+cible`;
  }
  if (n === "move_blocked") return `⛔ bloqué : ${ev.reason || ""}`;
  if (n === "move_skipped") return `↷ ignoré : ${ev.reason || ""}`;
  if (n === "run_stopped") return `■ stop : ${ev.reason || ""}`;
  if (n === "aborted") return `■ abandon : ${ev.reason || ""}`;
  return null;
}

function startPoll(runId) {
  stopPoll();
  // the run THIS action was approved on (the open modal's). No fallback to the mutable
  // PLAN_RUN_ID: runAction refuses before calling us when there is no open plan, and a
  // fallback would quietly tail another run's event log.
  const rid = runId;
  // This poll's generation (audit 2026-09-17, GO de Romain). `tick` is async: a tick whose
  // answer lands AFTER the modal was closed and another action started would otherwise run
  // on the NEW poll's state — its stopPoll() would clear the LIVE interval, its OFFSET write
  // would corrupt the new run's log window, and finishStatus() would paint the PREVIOUS
  // run's conclusion and exit code into the pane. Same token pattern as LOAD_SEQ.
  const seq = POLL_SEQ;
  const tick = async () => {
    let s;
    try { s = await getJSON(`api/runs/${encodeURIComponent(rid)}/submit/status?offset=${OFFSET}`); }
    catch (e) { return; }
    if (seq !== POLL_SEQ) return;   // retired generation — touch nothing
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
  const saved = localStorage.getItem("aks-theme");   // shared key across tabs
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const r = document.documentElement;
    const cur = r.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    r.setAttribute("data-theme", next); localStorage.setItem("aks-theme", next);
  });
})();
$("#run-picker").addEventListener("change", (e) => { RUN_ID = e.target.value; loadPlan(); });
$("#refresh").addEventListener("click", loadRuns);
$("#doc-btn").addEventListener("click", () => $("#doc-modal").showModal());  // close = native form method="dialog"
$("#doc-modal").addEventListener("click", (e) => { if (e.target.id === "doc-modal") e.target.close(); });

let SCAN_POLL = null, SCAN_SEQ = 0;
// Same generation discipline as the move poll: clearInterval cannot cancel a tick already
// waiting on the network, so retiring the generation is what actually disarms it.
function stopScanPoll() { SCAN_SEQ++; if (SCAN_POLL) { clearInterval(SCAN_POLL); SCAN_POLL = null; } }
$("#new-scan").addEventListener("click", async () => {
  const b = $("#new-scan");
  if (BUSY) { setStatus(`Un run est déjà en cours (${BUSY.kind}).`); return; }
  if (!confirm("Lancer un scan frais tous-stores ?\nRead-only, plusieurs minutes. Il tourne côté serveur même si tu fermes l'onglet.")) return;
  b.disabled = true;
  setStatus("Scan frais — lancement…", true);
  try {
    const r = await postJSON("api/sort/scan", {});
    pollScan(r.run_id || (r.meta && r.meta.run_id));
  } catch (e) {
    setStatus("Scan refusé : " + e.message);
    b.disabled = false;
  }
});

function pollScan(runId) {
  stopScanPoll();
  const seq = SCAN_SEQ;      // this scan-poll's generation
  const rid = runId;         // frozen: a later scan must not redirect this one's tick
  const b = $("#new-scan");
  const tick = async () => {
    let s;
    try { s = await getJSON(`api/runs/${encodeURIComponent(rid)}/submit/status`); }
    catch (e) { return; }
    if (seq !== SCAN_SEQ) return;   // retired generation — touch nothing
    setBusy(s.busy || null);
    const pages = (s.events || []).filter((e) => e.event === "feed_page").length;
    if (s.state === "running") {
      setStatus(`Scan frais en cours…${pages ? " " + pages + " pages" : ""}`, true);
      return;
    }
    stopScanPoll();
    b.disabled = false;
    setStatus(`Scan terminé (${s.state}) — chargement du plan frais…`);
    await loadRuns();
    if (rid && [...$("#run-picker").options].some((o) => o.value === rid)) {
      $("#run-picker").value = rid;
      RUN_ID = rid;
      loadPlan();
    }
  };
  SCAN_POLL = setInterval(tick, 5000);
  tick();
}
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
// Retiring the open window must be SYNCHRONOUS with the closing gesture (audit de Romain,
// 5e passe). The previous version hung the cleanup on the dialog's "close" event — correct in
// coverage, too late in time: per the HTML standard a dialog's close steps QUEUE that event,
// so an awaited continuation can resume between the gesture and the handler and still fire
// its POST. So every closing path retires the window itself, first, and the "close" /
// "cancel" listeners remain only as the net for endings we do not drive (Escape, a script
// close()). Retiring twice for the same window is harmless — the guards compare inequality —
// and the "close" listener's own check is what stops a deferred event from ever retiring the
// NEXT opening.
function closeOffers() {
  MODAL_SEQ++;
  stopPoll();
  MODAL_RUN_ID = null;
  MODAL_DIGEST = null;
}
// "cancel" (Échap) is dispatched WITH the key event, while the dialog is still open — it is
// the synchronous hook for that path. "close" is queued, so by the time it runs the operator
// may already have opened ANOTHER list: retire on it only if the dialog is still closed,
// otherwise a deferred event from the previous window would retire the new one.
$("#offers-modal").addEventListener("cancel", closeOffers);
$("#offers-modal").addEventListener("close", () => { if (!$("#offers-modal").open) closeOffers(); });
$("#modal-close").addEventListener("click", () => { closeOffers(); $("#offers-modal").close(); });
$("#offers-modal").addEventListener("click", (e) => {
  if (e.target.id === "offers-modal") { closeOffers(); e.target.close(); }
});

// ---- Reconnexion par transfert de cookies (AKS = social login only) ---------
// L'opérateur remplit Nom + Valeur par cookie WP ; le JS assemble l'objet cookie
// (domaine .allkeyshop.com, path /, secure+httpOnly) et l'envoie. Le serveur
// filtre/vérifie et prouve la session (dashboard). Aucune valeur n'est loggée.
function loginMsg(txt, cls) { const m = $("#login-msg"); m.textContent = txt; m.className = "login-msg" + (cls ? " " + cls : ""); }

// The WP cookies wp-admin needs over HTTPS, each with its OWN placeholder so the
// operator knows exactly which cookie goes on which row.
const LOGIN_COOKIE_HINTS = ["wordpress_logged_in_…", "wordpress_sec_…"];

function addLoginRow(placeholder) {
  const nameIn = el("input", { type: "text", class: "lr-name", placeholder: placeholder || "wordpress_… (autre cookie)", autocomplete: "off", spellcheck: "false" });
  const valIn = el("input", { type: "text", class: "lr-val", placeholder: "valeur du cookie", autocomplete: "off", spellcheck: "false" });
  const rm = el("button", { type: "button", class: "lr-rm", title: "Retirer cette ligne" }, "✕");
  const row = el("div", { class: "login-row" }, [nameIn, valIn, rm]);
  nameIn.addEventListener("input", updatePreview);
  valIn.addEventListener("input", updatePreview);
  rm.addEventListener("click", () => { row.remove(); updatePreview(); });
  $("#login-rows").append(row);
  return nameIn;
}

function collectLoginCookies() {
  const out = [];
  $("#login-rows").querySelectorAll(".login-row").forEach((row) => {
    const name = $(".lr-name", row).value.trim();
    const value = $(".lr-val", row).value.trim();
    if (name && value) out.push({ name, value, domain: ".allkeyshop.com", path: "/", secure: true, httpOnly: true });
  });
  return out;
}

function updatePreview() {
  const cookies = collectLoginCookies();
  const pv = $("#login-preview");
  const n = cookies.length;
  const sec = cookies.some((c) => c.name.startsWith("wordpress_sec_"));
  const logged = cookies.some((c) => c.name.startsWith("wordpress_logged_in_"));
  if (n === 0) { pv.textContent = ""; pv.className = "login-preview"; }
  else {
    pv.textContent = `${n} cookie(s) · wordpress_sec_ ${sec ? "✓" : "✗"} · wordpress_logged_in_ ${logged ? "✓" : "✗"}`
      + ((!sec && !logged) ? " — aucun cookie WP d'auth, la session ne s'ouvrira pas" : "");
    pv.className = "login-preview " + ((sec || logged) ? "ok" : "warn");
  }
  $("#login-inject").disabled = n === 0;
}

function resetLoginRows() {
  $("#login-rows").replaceChildren();
  LOGIN_COOKIE_HINTS.forEach((hint) => addLoginRow(hint));   // one row per needed cookie, own hint
  updatePreview();
}

$("#login-addrow").addEventListener("click", () => addLoginRow().focus());
$("#login-btn").addEventListener("click", () => {
  loginMsg(""); resetLoginRows();
  $("#login-modal").showModal();
  const first = $("#login-rows .lr-name"); if (first) first.focus();
});
$("#login-close").addEventListener("click", () => { resetLoginRows(); $("#login-modal").close(); });
$("#login-inject").addEventListener("click", async () => {
  const cookies = collectLoginCookies();
  if (!cookies.length) { loginMsg("Remplis au moins un cookie (nom + valeur).", "err"); return; }
  $("#login-inject").disabled = true;
  loginMsg("Injection + vérification de la session…");
  try {
    const r = await postJSON("api/login/cookies", { cookies });
    resetLoginRows();               // drop the session cookie values from the DOM
    if (r.status === "logged_in") loginMsg(`✓ Session rétablie (${r.cookies_injected} cookie(s) injecté(s), dashboard vérifié).`, "ok");
    else if (r.status === "not_logged_in") loginMsg("✖ Cookies injectés mais session NON authentifiée — vérifie que tu as bien wordpress_sec_ et/ou wordpress_logged_in_.", "err");
    else loginMsg("✖ " + (r.reason || r.status || "échec"), "err");
  } catch (e) {
    resetLoginRows();
    loginMsg("✖ " + e.message, "err");
  }
});

loadRuns().catch((e) => { banner("Erreur de chargement : " + e.message); setStatus("Erreur"); });
