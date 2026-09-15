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
let RECAP_DATA = null;       // the dry-run recap shown (the Saisir summary lists ITS targets)
let SUBMIT_MERCHANTS = 0;    // distinct merchants with candidates in the shown recap

// ---- targets [R45] ----
// Every page / region / edition a candidate WILL be written on. A preview candidate
// carries targets[] = [{platform, aks_product_id, aks_url, aks_name, region:{label,id},
// edition:{label,id}}] (targets[0] mirrors the primary fields); a cross-gen key has one
// target per declared platform page and is written on ALL of them (never split).
// Tolerated: the flat shape {region_label, region_id, edition_label, edition_id} and a
// missing list (older previews → the primary fields as the sole target). Nothing the
// submit will write is hidden from the operator (audit 2026-09-15, finding 1).
function labelId(obj, key, flatLabel, flatId) {
  const nested = obj ? obj[key] : null;
  if (nested && typeof nested === "object") {
    return { label: nested.label || "", id: nested.id != null ? String(nested.id) : "" };
  }
  return { label: (obj && obj[flatLabel]) || "", id: (obj && obj[flatId] != null) ? String(obj[flatId]) : "" };
}
function normTarget(t) {
  const o = t || {};
  return {
    platform: o.platform || "",
    aks_product_id: o.aks_product_id != null ? String(o.aks_product_id) : "",
    aks_url: o.aks_url || "",
    aks_name: o.aks_name || "",
    region: labelId(o, "region", "region_label", "region_id"),
    edition: labelId(o, "edition", "edition_label", "edition_id"),
  };
}
function candTargets(c) {
  const list = (c && Array.isArray(c.targets)) ? c.targets.filter((t) => t && typeof t === "object") : [];
  return (list.length ? list : [c || {}]).map(normTarget);
}
// "<platform> · page <id> (<aks_name>) · <region_label> (<region_id>) · <edition_label> (<edition_id>)"
function fmtTarget(t) {
  return (t.platform || "?") + " · page " + (t.aks_product_id || "?") + (t.aks_name ? " (" + t.aks_name + ")" : "")
    + " · " + (t.region.label || "?") + " (" + (t.region.id || "?") + ")"
    + " · " + (t.edition.label || "?") + " (" + (t.edition.id || "?") + ")";
}
// One preview line per target (class target-row), with the AKS page URL when known.
function targetRow(t, i, n) {
  const txt = fmtTarget(t);
  return el("div", { class: "off ok target-row" }, [
    el("span", { class: "off-name", text: "↳ " + txt, title: txt }),
    el("span", { class: "off-id", text: "cible " + (i + 1) + "/" + n }),
    el("span", { class: "off-st", text: "à saisir" }),
    offLink(t.aks_url),
  ]);
}
function plural(n, one, many) { return n + " " + (n > 1 ? many : one); }

// ---- the batch scripts/12 REALLY submits [R45] ----
// Mirror of src/data_entry_auto._candidates_by_store (Romain 2026-09-15: « aligner le
// récapitulatif sur le lot réellement soumis »): games not resolved or in error are
// dropped, merchant groups without a store_id are dropped, and within one STORE one
// candidate per fingerprint (a merchant can appear under several pasted games — the same
// offer found twice is submitted ONCE). The per-game table keeps showing what each page
// found; the KPIs, the Saisir button and the GO summary count THIS batch.
function candFingerprint(c) {
  if (c && typeof c.fingerprint === "string" && c.fingerprint) return c.fingerprint;
  // Fallback for a preview without the key = candidate_contract.fingerprint / app.js fp():
  // offer_id|aks_product_id|region_id|edition_id, plus "|+pid:rid:eid,…" over the EXTRA
  // targets (R45). Never throws here (display only) — a malformed row still counts once.
  const o = (c && c.offer) || {};
  const reg = labelId(c, "region", "region_label", "region_id"), ed = labelId(c, "edition", "edition_label", "edition_id");
  const primary = [o.offer_id, c ? c.aks_product_id : null, reg.id, ed.id].map((v) => (v == null ? "" : String(v))).join("|");
  const raw = (c && Array.isArray(c.targets)) ? c.targets : [];
  if (raw.length <= 1) return primary;
  const extra = raw.slice(1).map((t) => { const n = normTarget(t); return [n.aks_product_id, n.region.id, n.edition.id].join(":"); }).join(",");
  return primary + "|+" + extra;
}
function submitBatch(rec) {
  const order = [], groups = new Map();
  for (const g of ((rec && rec.games) || [])) {
    if (!g.resolved || g.error) continue;
    for (const per of (g.merchants || [])) {
      const sid = per.store_id == null ? "" : String(per.store_id);
      if (!sid) continue;
      let grp = groups.get(sid);
      if (!grp) {
        grp = { merchant: per.merchant || "", store_id: sid, rows: [], seen: new Set() };
        groups.set(sid, grp); order.push(sid);
      }
      for (const c of (per.candidates || [])) {
        const key = candFingerprint(c);
        if (grp.seen.has(key)) continue;   // same offer under another pasted game → once
        grp.seen.add(key);
        grp.rows.push({ name: (c.offer || {}).name || "", targets: candTargets(c) });
      }
    }
  }
  return order.map((sid) => groups.get(sid)).filter((grp) => grp.rows.length);
}
function batchCounts(groups) {
  let offers = 0, targets = 0;
  for (const grp of groups) for (const r of grp.rows) { offers += 1; targets += r.targets.length; }
  return { offers, targets, merchants: groups.length };
}

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
    // [R45] consoles by default (Romain 2026-09-15); unticked = PC-only preview (--no-consoles).
    const r = await api("api/data-entry/by-urls", { method: "POST", body: JSON.stringify({ urls, consoles: $("#consoles").checked }) });
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
  RECAP_DATA = rec;
  const t = rec.totals || {};
  // [R45] the batch as scripts/12 builds it (deduped per store by fingerprint) — the
  // KPIs, the Saisir button and the GO summary count THIS, not the per-game finds.
  const bc = batchCounts(submitBatch(rec));
  SUBMIT_MERCHANTS = bc.merchants;
  const found = Number(t.candidates || 0);
  const dupes = Math.max(0, found - bc.offers);
  const pill = $("#recap-status");
  const running = RUNNING;
  pill.textContent = rec.aborted ? ("ARRÊTÉ — " + rec.aborted) : (running ? "EN COURS" : "TERMINÉ");
  pill.className = "pill " + (rec.aborted ? "halted" : (running ? "running" : "done"));
  $("#recap-summary").replaceChildren(
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(bc.offers) }), el("div", { class: "kpi-l", text: "offres à saisir (lot)" + (dupes ? " · " + found + " trouvée(s), " + dupes + " doublon(s) entre jeux" : "") })]),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(bc.targets) }), el("div", { class: "kpi-l", text: "page(s) cible(s) à écrire" })]),
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
        const o = c.offer || {};
        const reg = labelId(c, "region", "region_label", "region_id"), ed = labelId(c, "edition", "edition_label", "edition_id");
        const targets = candTargets(c);
        const multi = targets.length > 1;
        kids.push(el("div", { class: "off ok" }, [
          el("span", { class: "off-name", text: o.name || "", title: o.name || "" }),
          el("span", { class: "off-id", text: (reg.label ? reg.label + "(" + reg.id + ") · " + ed.label + "(" + ed.id + ")" : "") + (multi ? " · " + targets.length + " cibles" : "") }),
          el("span", { class: "off-st", text: multi ? "à saisir ×" + targets.length : "à saisir" }),
          offLink(o.url),
        ]));
        // [R45] every target page of a multi-target candidate (a cross-gen key is
        // written on ALL its declared pages, never split) — and a lone target that is
        // NOT the game's own page. A plain single-target candidate on the game's page
        // keeps the one line above (its region/edition IS the target's).
        const offPage = targets.length === 1 && targets[0].aks_product_id
          && targets[0].aks_product_id !== String(g.aks_product_id);
        if (multi || offPage) targets.forEach((tg, i) => kids.push(targetRow(tg, i, targets.length)));
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
  const canSubmit = !RUNNING && !SUBMIT_RUNNING && !rec.aborted && (t.candidates > 0) && (bc.offers > 0) && RECAP_SHA;
  $("#submit-bar").classList.toggle("hidden", !canSubmit);
  $("#saisir-n").textContent = String(bc.offers);   // the deduped batch, not the per-game finds
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
  if (!RECAP_RUN || !RECAP_SHA || !RECAP_DATA) return;
  // [R45] the GO summary is the batch scripts/12 will really submit (per store, one
  // candidate per fingerprint — a duplicate under another pasted game is omitted) and
  // lists EVERY target it will write, one line per page / region / edition, with the
  // total (« 3 offres sur 5 pages »).
  const batch = submitBatch(RECAP_DATA);
  const bc = batchCounts(batch);
  $("#confirm-n").textContent = String(bc.offers);
  $("#confirm-m").textContent = String(bc.merchants);
  $("#confirm-t").textContent = plural(bc.offers, "offre", "offres") + " sur " + plural(bc.targets, "page", "pages");
  const box = $("#confirm-targets");
  box.replaceChildren();
  for (const grp of batch) {
    box.append(el("div", { class: "logline", text: "— " + grp.merchant + " (store " + grp.store_id + ") : " + plural(grp.rows.length, "offre", "offres") }));
    for (const r of grp.rows) {
      box.append(el("div", { class: "logline", text: "  " + r.name + (r.targets.length > 1 ? " — " + r.targets.length + " cibles" : "") }));
      for (const tg of r.targets) box.append(el("div", { class: "logline ok target-row", text: "     ↳ " + fmtTarget(tg) }));
    }
  }
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
      // [R45] same "Consoles" setting as the preview (the server refuses a mismatch, 409).
      body: JSON.stringify({ from_run: RECAP_RUN, recap_sha256: RECAP_SHA, confirm: "GO", consoles: $("#consoles").checked }),
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
