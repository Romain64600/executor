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

let POLL = null, OFFSET = 0, BATCHED = false;

function renderCmds(id) {
  // The exact copyable CLI, tracking the "Batché" toggle. Batched = the fast
  // many-offers-per-Apply path; its canary must fire a >=2-item Apply (--limit 2)
  // and its full list needs that multi-item proof.
  const base = `python3 scripts/09_sort_move.py runs/${RUN_ID} --list ${id}`;
  const canaryCmd = BATCHED
    ? `${base} --execute --mode learning --batch --limit 2`
    : `${base} --execute --mode learning`;
  const batchCmd = BATCHED
    ? `${base} --execute --mode safe --batch --i-authorize-batch`
    : `${base} --execute --mode safe --i-authorize-batch`;
  $("#modal-cmds").replaceChildren(
    cmdRow("dry-run", base),
    cmdRow(BATCHED ? "canary multi-item" : "canary", canaryCmd),
    cmdRow(BATCHED ? "batch groupé" : "batch", batchCmd),
  );
}

function openList(id, g) {
  const [, family] = fam(id);
  $("#modal-title").textContent = `${g.label || family} — liste ${id} · ${fmt(g.count)} offres`;
  BATCHED = false;
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
  const relabel = () => {
    canary.textContent = BATCHED ? "Canary multi-item (2)" : "Canary (1 move)";
    batch.textContent = BATCHED ? `Batch groupé (${fmt(g.count)})` : `Batch (${fmt(g.count)})`;
  };
  toggle.addEventListener("change", () => { BATCHED = toggle.checked; relabel(); renderCmds(id); });
  const sync = () => { const ok = go.value.trim().toUpperCase() === "GO"; canary.disabled = batch.disabled = !ok; };
  go.addEventListener("input", sync);
  canary.addEventListener("click", () => runAction(id, "canary", go, BATCHED));
  batch.addEventListener("click", () => runAction(id, "batch", go, BATCHED));
  relabel();
  $("#modal-actions").replaceChildren(
    el("button", { onclick: () => runAction(id, "dry_run", null, false) }, "Dry-run"),
    el("span", { class: "aspacer" }),
    el("label", { class: "batched-toggle",
      title: "Moves groupés : N offres par Apply (~50-100× plus rapide). Le canary batché "
           + "fait un Apply de 2 (preuve multi-item) ; le lot complet exige cette preuve." },
      [toggle, " Batché (rapide)"]),
    el("span", { class: "aspacer" }),
    el("span", { class: "golabel" }, "GO :"), go, canary, batch,
    el("div", { class: "gatehint" },
      "Dry-run = aperçu (aucune écriture). Canary = déplacement prouvé (autorise la liste). "
      + "Batch = liste complète, exige un canary validé. « Batché » groupe N offres/Apply "
      + "(rapide) et exige un canary multi-item. Chaque move prouve source+cible (RV2)."),
  );
}

async function runAction(id, action, goInput, batched) {
  if ((action === "canary" || action === "batch")
      && (!goInput || goInput.value.trim().toUpperCase() !== "GO")) return;
  const body = { list_id: id, action };
  if (action !== "dry_run") body.confirm = "GO";
  if (batched) body.batched = true;
  $("#modal-actions").querySelectorAll("button,input").forEach((n) => (n.disabled = true));
  // The run's event log is shared across every action on this run — start
  // reading from its CURRENT end so the pane shows only THIS action's events,
  // not replayed history from earlier canaries/dry-runs.
  try {
    const base = await getJSON(`api/runs/${encodeURIComponent(RUN_ID)}/submit/status?offset=0`);
    OFFSET = base.offset ?? 0;
  } catch (e) { OFFSET = 0; }
  const tag = action.replace("_", "-") + (batched ? " (batché)" : "");
  showStatusPane(`▶ ${tag} — liste ${id} — lancement…`);
  setStatus(`Lancement ${tag}…`, true);
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

let SCAN_RUN = null, SCAN_POLL = null;
$("#new-scan").addEventListener("click", async () => {
  const b = $("#new-scan");
  if (BUSY) { setStatus(`Un run est déjà en cours (${BUSY.kind}).`); return; }
  if (!confirm("Lancer un scan frais tous-stores ?\nRead-only, plusieurs minutes. Il tourne côté serveur même si tu fermes l'onglet.")) return;
  b.disabled = true;
  setStatus("Scan frais — lancement…", true);
  try {
    const r = await postJSON("api/sort/scan", {});
    SCAN_RUN = r.run_id || (r.meta && r.meta.run_id);
    pollScan();
  } catch (e) {
    setStatus("Scan refusé : " + e.message);
    b.disabled = false;
  }
});

function pollScan() {
  if (SCAN_POLL) clearInterval(SCAN_POLL);
  const b = $("#new-scan");
  const tick = async () => {
    let s;
    try { s = await getJSON(`api/runs/${encodeURIComponent(SCAN_RUN)}/submit/status`); }
    catch (e) { return; }
    setBusy(s.busy || null);
    const pages = (s.events || []).filter((e) => e.event === "feed_page").length;
    if (s.state === "running") {
      setStatus(`Scan frais en cours…${pages ? " " + pages + " pages" : ""}`, true);
      return;
    }
    clearInterval(SCAN_POLL); SCAN_POLL = null;
    b.disabled = false;
    setStatus(`Scan terminé (${s.state}) — chargement du plan frais…`);
    await loadRuns();
    if (SCAN_RUN && [...$("#run-picker").options].some((o) => o.value === SCAN_RUN)) {
      $("#run-picker").value = SCAN_RUN;
      RUN_ID = SCAN_RUN;
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
$("#modal-close").addEventListener("click", () => { stopPoll(); $("#offers-modal").close(); });
$("#offers-modal").addEventListener("click", (e) => { if (e.target.id === "offers-modal") { stopPoll(); e.target.close(); } });

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
