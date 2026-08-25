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

// A clickable source URL for a search-result offer (candidate or skipped), on its
// own full-width line so the operator can open/verify it. null when there is no URL.
function offLink(url) {
  if (!url) return null;
  return el("a", { class: "off-url", href: url, target: "_blank", rel: "noopener noreferrer", title: url, text: url });
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

let RUNNING = false;         // a by-urls dry-run (aperçu) is active
let SUBMIT_RUNNING = false;  // a by-urls SUBMIT (Saisir) is active
let RECAP_SHA = null;        // sha of the dry-run recap shown (binds the Saisir GO, AS1)
let RECAP_RUN = null;        // the dry-run run id to submit from
let SUBMIT_MERCHANTS = 0;    // distinct merchants with candidates in the shown recap

// ---- URL input ----
function parseUrls() {
  return $("#urls").value.split(/[\s,]+/).map((u) => u.trim()).filter(Boolean);
}
function syncLaunch() {
  const n = parseUrls().length;
  $("#urls-count").textContent = n + " URL" + (n > 1 ? "s" : "");
  // Only disable while a run is active — NOT on an empty field. A hard reload can
  // restore the textarea value without firing 'input' (so syncLaunch never re-enabled
  // it), leaving the button silently disabled; instead the click handler validates and
  // gives a visible message when the field is empty (2026-08-25).
  $("#launch").disabled = RUNNING;
}
$("#urls").addEventListener("input", syncLaunch);
$("#urls").addEventListener("change", syncLaunch);
$("#urls").addEventListener("paste", () => setTimeout(syncLaunch, 0));

// ---- launch ----
$("#launch").addEventListener("click", async () => {
  const urls = parseUrls();
  if (!urls.length) {
    $("#launch-msg").textContent = "✖ Colle au moins une URL de page AKS dans le champ.";
    return;
  }
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
  SUBMIT_RUNNING = false;
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
  if (n === "skipped") return `   ✖ ${ev.merchant} ignorée : ${ev.name || ""} · ${ev.reason || ""}\n      ${ev.url || ""}`;
  if (n === "merchant_done") return `   · ${ev.merchant} : ${ev.found} trouvée(s) · ${ev.candidates} à saisir` + (ev.skipped ? ` · ${ev.skipped} ignorée(s)` : "");
  if (n === "game_done") return ev.error ? `⚠ ${ev.aks_name} : ${ev.error}` : `✓ ${ev.aks_name} : ${ev.candidates} à saisir`;
  if (n === "run_done") return `■ terminé · ${ev.resolved} résolu(s), ${ev.candidates} à saisir`;
  if (n === "run_aborted") return `■ arrêté : ${ev.reason}`;
  // ---- submit (Saisir) events ----
  if (n === "submit_run_start") return `▶ SAISIE — depuis l'aperçu ${ev.from_run || ""}`;
  if (n === "merchant_submit") return `— ${ev.merchant} (store ${ev.store_id}) : saisie de ${ev.attempted} offre(s)…`;
  if (n === "merchant_submitted") return ev.halted ? `   ⚠ ${ev.merchant} : ${ev.halted}` : `   ✔ ${ev.merchant} : ${ev.created}/${ev.attempted} créée(s)`;
  if (n === "submit_run_done") return `■ SAISIE terminée · ${ev.created} créée(s) sur ${ev.merchants} marchand(s)`;
  if (n === "submit_run_aborted") return `■ SAISIE arrêtée : ${ev.reason}`;
  return null;
}
function appendLog(events) {
  const box = $("#log");
  for (const ev of (events || [])) {
    const line = fmtLogEvent(ev);
    if (line == null) continue;
    const ok = ev.event === "candidate" || (ev.event === "merchant_submitted" && !ev.halted);
    const bad = ev.ok === false || ev.error || ev.halted || ev.event === "run_aborted" || ev.event === "submit_run_aborted";
    const cls = bad ? "no" : (ok ? "ok" : "");
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
      if (d) renderRecap(d);   // re-render with RUNNING=false → the "Saisir" button appears
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
  if (busy && busy.kind === "data_entry_by_urls_submit") {
    SUBMIT_RUNNING = true;
    $("#recap-card").classList.remove("hidden");
    $("#busy-text").textContent = "saisie en cours" + (busy.run_id ? " · " + busy.run_id : "");
    $("#launch-msg").textContent = "Une saisie est déjà en cours — attends la fin ou clique Arrêter.";
    setStatus("Saisie en cours…", true);
    startSubmitPolling(busy.run_id);
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
  if (rec.mode === "submit") return renderSubmitRecap(d, rec);
  // ---- dry-run (aperçu) recap ----
  RECAP_SHA = d.recap_sha256 || null;
  RECAP_RUN = d.run_id || null;
  SUBMIT_MERCHANTS = new Set((rec.games || []).flatMap((g) => (g.merchants || [])
    .filter((m) => (m.candidates || []).length).map((m) => m.store_id))).size;
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
      const skips = per.skipped || [];
      if (!cands.length && !skips.length) continue;   // merchant with nothing found — omit
      kids.push(el("div", { class: "m-title", text: per.merchant + " — " + cands.length + " à saisir" + (skips.length ? " · " + skips.length + " ignorée(s)" : "") }));
      for (const c of cands) {
        const o = c.offer || {}, reg = c.region || {}, ed = c.edition || {};
        kids.push(el("div", { class: "off ok" }, [
          el("span", { class: "off-name", text: o.name || "", title: o.name || "" }),
          el("span", { class: "off-id", text: reg.label ? reg.label + "(" + reg.id + ") · " + (ed.label || "") + "(" + (ed.id || "") + ")" : "" }),
          el("span", { class: "off-st", text: "à saisir" }),
          offLink(o.url),
        ]));
      }
      // Skipped search results — shown WITH their source URL + reason so the operator
      // can eyeball what was ignored without asking (Romain 2026-08-25).
      for (const s of skips) {
        kids.push(el("div", { class: "off skip" }, [
          el("span", { class: "off-name", text: s.name || "", title: s.name || "" }),
          el("span", { class: "off-id", text: "" }),
          el("span", { class: "off-st", text: "ignorée" }),
          s.reason ? el("span", { class: "off-why", text: s.reason }) : null,
          offLink(s.url),
        ]));
      }
    }
    if ((g.total_candidates || 0) === 0) kids.push(el("div", { class: "off no" }, [el("span", { class: "off-st", text: "(aucune offre à saisir trouvée)" })]));
    // Off-allowlist search results (non-vetted merchants) — shown with their URL too,
    // so every search result is visible even though these can't be entered.
    const offList = g.off_allowlist_offers || [];
    if (offList.length) {
      kids.push(el("div", { class: "m-title dim", text: "Hors-liste (marchands non autorisés) — " + offList.length }));
      for (const o of offList) {
        kids.push(el("div", { class: "off skip" }, [
          el("span", { class: "off-name", text: o.name || "", title: o.name || "" }),
          el("span", { class: "off-id", text: o.store_id ? "store " + o.store_id : "" }),
          el("span", { class: "off-st", text: "hors-liste" }),
          offLink(o.url),
        ]));
      }
    }
    wrap.append(el("div", { class: "pg" }, kids));
  }
  // "Saisir" is offered only on a FINISHED, non-aborted dry-run with candidates.
  const canSubmit = !RUNNING && !SUBMIT_RUNNING && !rec.aborted && (t.candidates > 0) && RECAP_SHA;
  $("#submit-bar").classList.toggle("hidden", !canSubmit);
  $("#saisir-n").textContent = String(t.candidates || 0);
}

// ---- submit recap (Saisir) ----
function renderSubmitRecap(d, rec) {
  $("#submit-bar").classList.add("hidden");
  const t = rec.totals || {};
  const pill = $("#recap-status");
  pill.textContent = rec.aborted ? ("ARRÊTÉ — " + rec.aborted) : (SUBMIT_RUNNING ? "SAISIE EN COURS" : "SAISIE TERMINÉE");
  pill.className = "pill " + (rec.aborted ? "halted" : (SUBMIT_RUNNING ? "running" : "done"));
  $("#recap-summary").replaceChildren(
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(t.created || 0) }), el("div", { class: "kpi-l", text: "créées" })]),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(t.attempted || 0) }), el("div", { class: "kpi-l", text: "tentées" })]),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String((rec.merchants || []).length) }), el("div", { class: "kpi-l", text: "marchand(s)" })]),
  );
  const wrap = $("#recap-games");
  wrap.replaceChildren();
  for (const m of (rec.merchants || [])) {
    const kids = [el("div", { class: "pg-head" }, [
      el("span", { class: "pg-n", text: m.merchant + " (store " + m.store_id + ")" }),
      el("span", { class: "pg-m", text: (m.created || 0) + "/" + (m.attempted || 0) + " créées" + (m.halted ? " · ⚠ " + m.halted : "") }),
    ])];
    for (const o of (m.offers || [])) {
      kids.push(el("div", { class: "off " + (o.created ? "ok" : "no") }, [
        el("span", { class: "off-name", text: o.name || "" }),
        el("span", { class: "off-id", text: o.aks_id ? "AKS " + o.aks_id : "" }),
        el("span", { class: "off-st", text: o.created ? "créée" : (o.post_save || "?") }),
      ]));
    }
    wrap.append(el("div", { class: "pg" }, kids));
  }
}

// ---- Saisir (write) ----
$("#saisir").addEventListener("click", () => {
  if (!RECAP_RUN || !RECAP_SHA) return;
  $("#confirm-n").textContent = $("#saisir-n").textContent;
  $("#confirm-m").textContent = String(SUBMIT_MERCHANTS || "?");
  $("#confirm-go").value = "";
  $("#confirm-submit").disabled = true;
  $("#confirm-msg").textContent = "";
  $("#confirm-modal").showModal();
});
$("#confirm-modal").addEventListener("click", (e) => { if (e.target.id === "confirm-modal") e.target.close(); });
$("#confirm-go").addEventListener("input", () => {
  $("#confirm-submit").disabled = $("#confirm-go").value.trim().toUpperCase() !== "GO";
});
$("#confirm-submit").addEventListener("click", async () => {
  if ($("#confirm-go").value.trim().toUpperCase() !== "GO") return;
  $("#confirm-submit").disabled = true;
  $("#confirm-msg").textContent = "Lancement…";
  try {
    const r = await api("api/data-entry/by-urls/submit", {
      method: "POST",
      body: JSON.stringify({ from_run: RECAP_RUN, recap_sha256: RECAP_SHA, confirm: "GO" }),
    });
    $("#confirm-modal").close();
    SUBMIT_RUNNING = true;
    $("#launch-msg").textContent = "▶ saisie lancée : " + (r.run_id || "");
    setStatus("Saisie en cours…", true);
    $("#busy-ind").classList.remove("hidden");
    $("#busy-text").textContent = "saisie · " + (r.run_id || "");
    $("#submit-bar").classList.add("hidden");
    startSubmitPolling(r.run_id);
  } catch (e) {
    $("#confirm-msg").textContent = "✖ refusé : " + e.message;
    $("#confirm-submit").disabled = false;
  }
});

function startSubmitPolling(runId) {
  $("#log-card").classList.remove("hidden");
  $("#busy-ind").classList.remove("hidden");
  LOG_OFFSET = 0; $("#log").replaceChildren();
  if (POLL) clearInterval(POLL);
  const tick = async () => {
    const busy = await fetchBusy();
    await pollLog(runId);
    let d = null;
    try { d = await api("api/data-entry/by-urls/submit/recap" + (runId ? "?run=" + encodeURIComponent(runId) : "")); }
    catch (e) { d = null; }
    if (d) renderRecap(d);
    let running;
    if (busy === undefined) running = true;
    else if (busy && busy.kind === "data_entry_by_urls_submit") running = true;
    else running = false;
    if (!running) {
      SUBMIT_RUNNING = false;
      const rec = d && d.recap;
      endUi(rec && rec.aborted ? ("Saisie arrêtée : " + rec.aborted) : "Saisie terminée.");
      if (d) renderRecap(d);   // final render with SUBMIT_RUNNING=false (pill → terminé)
    }
  };
  tick(); POLL = setInterval(tick, 2000);
}

// ---- init ----
(async function init() {
  setStatus("Prêt");
  syncLaunch();
  if (!(await resumeIfActive())) await showLastRecap();
})();
