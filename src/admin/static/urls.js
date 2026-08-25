"use strict";
// "Saisie par jeux" — paste AKS page URLs, launch a READ-ONLY dry-run that
// searches the feed for each game across the vetted merchants and previews what
// would be entered. No writes here (submit is a separate, gated step).
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

// ---- theme + doc ----
(function () {
  const saved = localStorage.getItem("aks-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    localStorage.setItem("aks-theme", cur);
  });
})();
$("#doc-btn").addEventListener("click", () => $("#doc-modal").showModal());
$("#doc-modal").addEventListener("click", (e) => { if (e.target.id === "doc-modal") e.target.close(); });

let RUNNING = false;   // a by-urls run is active (launched here OR elsewhere)

// ---- URL input ----
function parseUrls() {
  return $("#urls").value.split(/[\s,]+/).map((u) => u.trim()).filter(Boolean);
}
function syncLaunch() {
  const n = parseUrls().length;
  $("#urls-count").textContent = n + " URL" + (n > 1 ? "s" : "");
  $("#launch").disabled = RUNNING || n === 0;
}
$("#urls").addEventListener("input", syncLaunch);

// ---- launch ----
$("#launch").addEventListener("click", async () => {
  const urls = parseUrls();
  if (!urls.length) return;
  $("#launch").disabled = true;
  $("#launch-msg").textContent = "Lancement de l'aperçu…";
  try {
    const r = await api("api/data-entry/by-urls", { method: "POST", body: JSON.stringify({ urls }) });
    $("#launch-msg").textContent = "▶ aperçu lancé : " + (r.run_id || "");
    RUNNING = true;
    setStatus("Aperçu en cours…", true);
    $("#busy-ind").classList.remove("hidden");
    $("#busy-text").textContent = "aperçu · " + urls.length + " jeu(x)";
    startPolling(r.run_id);
  } catch (e) {
    $("#launch-msg").textContent = "✖ refusé : " + e.message;
    setStatus("Refusé — " + e.message);
    syncLaunch();
  }
});
$("#stop-btn").addEventListener("click", async () => {
  $("#stop-btn").disabled = true;
  try { await api("api/sort/stop", { method: "POST", body: "{}" }); setStatus("Arrêt demandé…", true); }
  catch (e) { setStatus("Stop refusé — " + e.message); $("#stop-btn").disabled = false; }
});

// ---- live recap ----
let POLL = null;
async function fetchBusy() {
  try { const d = await api("api/sort/runs"); return d ? (d.busy || null) : null; }
  catch (e) { return undefined; }   // transient — don't declare finished on a blip
}
function endUi(finalText) {
  clearInterval(POLL); POLL = null;
  RUNNING = false;
  $("#busy-ind").classList.add("hidden");
  setStatus(finalText);
  $("#stop-btn").disabled = false;
  syncLaunch();
}
// ---- live log ----
let LOG_OFFSET = 0;
function fmtLogEvent(ev) {
  const n = ev.event || "";
  if (n === "run_start") return `▶ démarrage · ${ev.urls} URL(s), ${ev.merchants} marchand(s)`;
  if (n === "game_resolved") return ev.ok
    ? `🎯 résolu : ${ev.aks_name} (AKS ${ev.aks_product_id})`
    : `❌ non résolu : ${ev.url} — ${ev.reason || ""}`;
  if (n === "game_start") return `— ${ev.aks_name} : recherche (tous marchands)…`;
  if (n === "game_searched") return `   ⟳ ${ev.found} résultat(s) tous marchands` + (ev.off_allowlist ? ` · ${ev.off_allowlist} hors-liste ignoré(s)` : "") + (ev.truncated ? " · (tronqué)" : "");
  if (n === "candidate") return `   ✔ [${ev.merchant}] ${ev.name} — ${ev.region}, ${ev.edition}`;
  if (n === "merchant_done") return `   · ${ev.merchant} : ${ev.found} trouvée(s) · ${ev.candidates} à saisir` + (ev.skipped ? ` · ${ev.skipped} ignorée(s)` : "");
  if (n === "game_done") return ev.error ? `⚠ ${ev.aks_name} : ${ev.error}` : `✓ ${ev.aks_name} : ${ev.candidates} à saisir`;
  if (n === "run_done") return `■ terminé · ${ev.resolved} résolu(s), ${ev.candidates} à saisir`;
  if (n === "run_aborted") return `■ arrêté : ${ev.reason}`;
  return null;
}
function appendLog(events) {
  const box = $("#log");
  for (const ev of (events || [])) {
    const line = fmtLogEvent(ev);
    if (line == null) continue;
    const cls = ev.event === "candidate" ? "ok" : (ev.ok === false || ev.error || ev.event === "run_aborted") ? "no" : "";
    box.append(el("div", { class: "logline" + (cls ? " " + cls : "") }, line));
  }
  if ($("#autoscroll").checked) box.scrollTop = box.scrollHeight;
}
async function pollLog(runId) {
  try {
    const d = await api("api/data-entry/by-urls/log?offset=" + LOG_OFFSET + (runId ? "&run=" + encodeURIComponent(runId) : ""));
    if (d && Array.isArray(d.events)) { appendLog(d.events); LOG_OFFSET = d.offset || LOG_OFFSET; }
  } catch (e) { /* transient — keep polling */ }
}

function startPolling(runId) {
  $("#recap-card").classList.remove("hidden");
  $("#log-card").classList.remove("hidden");
  $("#busy-ind").classList.remove("hidden");
  LOG_OFFSET = 0; $("#log").replaceChildren();   // replay this run's log from the top
  if (POLL) clearInterval(POLL);
  const tick = async () => {
    const busy = await fetchBusy();
    await pollLog(runId);
    let d = null;
    try { d = await api("api/data-entry/by-urls/recap" + (runId ? "?run=" + encodeURIComponent(runId) : "")); }
    catch (e) { d = null; }
    if (d) renderRecap(d);
    let running;
    if (busy === undefined) running = true;                      // transient error
    else if (busy && busy.kind === "data_entry_by_urls") running = true;
    else running = false;                                        // manager idle → done
    if (!running) {
      const rec = d && d.recap;
      endUi(rec && rec.aborted ? ("Arrêté : " + rec.aborted) : "Aperçu terminé.");
    }
  };
  tick(); POLL = setInterval(tick, 2000);   // ~real-time log
}
async function resumeIfActive() {
  const busy = await fetchBusy();
  if (busy && busy.kind === "data_entry_by_urls") {
    RUNNING = true;
    $("#busy-text").textContent = "aperçu en cours" + (busy.run_id ? " · " + busy.run_id : "");
    $("#launch-msg").textContent = "Un aperçu est déjà en cours — attends la fin ou clique Arrêter.";
    setStatus("Aperçu en cours…", true);
    startPolling(busy.run_id);
    return true;
  }
  return false;
}
async function showLastRecap() {
  let d; try { d = await api("api/data-entry/by-urls/recap"); } catch (e) { return; }
  if (d && d.recap) {
    $("#recap-card").classList.remove("hidden");
    renderRecap(d);
    // Replay the finished run's log too, so the operator can read what happened.
    LOG_OFFSET = 0; $("#log").replaceChildren();
    $("#log-card").classList.remove("hidden");
    await pollLog(d.run_id);
  }
}

function renderRecap(d) {
  const rec = d && d.recap;
  $("#recap-run").textContent = d && d.run_id ? "· " + d.run_id : "";
  if (!rec) { $("#recap-summary").textContent = "En attente de la résolution…"; return; }
  const t = rec.totals || {};
  const pill = $("#recap-status");
  const running = RUNNING;
  pill.textContent = rec.aborted ? ("ARRÊTÉ — " + rec.aborted) : (running ? "EN COURS" : "TERMINÉ");
  pill.className = "pill " + (rec.aborted ? "halted" : (running ? "running" : "done"));
  $("#recap-summary").replaceChildren(
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(t.candidates || 0) }), el("div", { class: "kpi-l", text: "offres à saisir" })]),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: (t.resolved || 0) + "/" + (t.games || 0) }), el("div", { class: "kpi-l", text: "jeu(x) résolu(s)" })]),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String((rec.merchants || []).length) }), el("div", { class: "kpi-l", text: "marchand(s)" })]),
  );
  const wrap = $("#recap-games");
  wrap.replaceChildren();
  for (const g of (rec.games || [])) {
    if (!g.resolved) {
      wrap.append(el("div", { class: "pg game-unresolved" }, [
        el("div", { class: "pg-head" }, [
          el("span", { class: "pg-n", text: "❌ non résolu" }),
          el("span", { class: "pg-m", text: g.url }),
        ]),
        el("div", { class: "off no" }, [el("span", { class: "off-st", text: g.reason || "" })]),
      ]));
      continue;
    }
    const kids = [el("div", { class: "pg-head" }, [
      el("span", { class: "pg-n", text: "🎯 " + (g.aks_name || "") }),
      el("span", { class: "pg-m", text: "AKS " + g.aks_product_id + " · " + (g.total_candidates || 0) + " à saisir" }),
    ]),
      el("div", { class: "game-url dim", text: g.url })];
    if (g.error) {
      kids.push(el("div", { class: "off no" }, [el("span", { class: "off-st", text: "⚠ " + g.error + (g.detail ? " — " + g.detail : "") })]));
      wrap.append(el("div", { class: "pg" }, kids));
      continue;
    }
    if (g.search) kids.push(el("div", { class: "game-url dim", text: g.search.found + " résultat(s) tous marchands" + (g.search.off_allowlist ? " · " + g.search.off_allowlist + " hors-liste" : "") + (g.search.truncated ? " · tronqué" : "") }));
    for (const per of (g.merchants || [])) {
      const cands = per.candidates || [];
      const nSk = (per.skipped || []).length;
      if (!cands.length && !nSk) continue;   // merchant with nothing found — omit
      kids.push(el("div", { class: "m-title", text: per.merchant + " — " + cands.length + " à saisir" + (nSk ? " · " + nSk + " ignorée(s)" : "") }));
      for (const c of cands) {
        const o = c.offer || {}, reg = c.region || {}, ed = c.edition || {};
        kids.push(el("div", { class: "off ok" }, [
          el("span", { class: "off-name", text: o.name || "" }),
          el("span", { class: "off-id", text: reg.label ? reg.label + "(" + reg.id + ") · " + (ed.label || "") + "(" + (ed.id || "") + ")" : "" }),
          el("span", { class: "off-st", text: "à saisir" }),
        ]));
      }
    }
    if ((g.total_candidates || 0) === 0) kids.push(el("div", { class: "off no" }, [el("span", { class: "off-st", text: "(aucune offre à saisir trouvée)" })]));
    wrap.append(el("div", { class: "pg" }, kids));
  }
}

// ---- init ----
(async function init() {
  setStatus("Prêt");
  syncLaunch();
  if (!(await resumeIfActive())) await showLastRecap();
})();
