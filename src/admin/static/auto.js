"use strict";
// Data Entry Auto console — launch a safe-auto sweep, watch the live recap.
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

// ---- theme ----
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

// ---- suggested merchants (the authoritative allowlist) ----
// Safe-auto writes without validation, so ONLY server-vetted merchants may run.
// The picker offers exactly these; the store is derived, never typed; the
// server re-checks on launch. Empty list (fetch failed) ⇒ launching stays off.
let SUGGESTED = [];       // [{name, store_id}] from /api/data-entry/merchants
let SUGGEST_READY = false;
function merchantOptions() {
  const opts = [el("option", { value: "", text: "Marchand…" })];
  for (const m of SUGGESTED) opts.push(el("option", { value: m.name, text: m.name + " (store " + m.store_id + ")" }));
  return opts;
}
const storeFor = (name) => { const m = SUGGESTED.find((x) => x.name === name); return m ? m.store_id : ""; };

// ---- targets ----
function addTarget(merchant) {
  const m = el("select", { class: "t-merchant" }, merchantOptions());
  if (merchant) m.value = merchant;
  const s = el("input", { type: "text", class: "t-store", readonly: "readonly", tabindex: "-1", placeholder: "—", value: storeFor(m.value) });
  const rm = el("button", { type: "button", class: "t-rm", title: "Retirer", text: "✕" });
  const row = el("div", { class: "t-row" }, [m, s, rm]);
  rm.addEventListener("click", () => { row.remove(); syncGo(); });
  m.addEventListener("change", () => { s.value = storeFor(m.value); syncGo(); });
  $("#targets").append(row);
  return m;
}
function collectTargets() {
  const out = [];
  for (const row of $("#targets").querySelectorAll(".t-row")) {
    const merchant = row.querySelector(".t-merchant").value.trim();
    const store_id = storeFor(merchant);           // canonical store, never user-typed
    if (merchant && /^\d+$/.test(store_id)) out.push({ merchant, store_id });
  }
  return out;
}
function syncGo() {
  const ok = SUGGEST_READY && collectTargets().length > 0 && $("#go").value.trim().toUpperCase() === "GO";
  $("#launch").disabled = !ok;
}
$("#add-target").addEventListener("click", () => { if (SUGGEST_READY) addTarget().focus(); });
$("#go").addEventListener("input", syncGo);

// ---- launch ----
$("#launch").addEventListener("click", async () => {
  const targets = collectTargets();
  if (!targets.length || $("#go").value.trim().toUpperCase() !== "GO") return;
  const body = { targets };
  const mp = parseInt($("#max-pages").value, 10); if (mp > 0) body.max_pages = mp;
  const sp = parseInt($("#start-page").value, 10); if (sp > 0) body.start_page = sp;
  $("#launch").disabled = true;
  $("#launch-msg").textContent = "Lancement…";
  try {
    const r = await api("/api/data-entry/auto", { method: "POST", body: JSON.stringify(body) });
    $("#launch-msg").textContent = "▶ sweep lancé : " + (r.run_id || "");
    setStatus("Sweep en cours…", true);
    $("#busy-ind").classList.remove("hidden");
    $("#busy-text").textContent = "sweep " + targets.map((t) => t.merchant).join(", ");
    startPolling(r.run_id);
  } catch (e) {
    $("#launch-msg").textContent = "✖ refusé : " + e.message;
    setStatus("Refusé — " + e.message);
    syncGo();
  }
});
$("#stop-btn").addEventListener("click", async () => {
  $("#stop-btn").disabled = true;
  try { await api("/api/sort/stop", { method: "POST", body: "{}" }); setStatus("Arrêt demandé (entre pages)…", true); }
  catch (e) { setStatus("Stop refusé — " + e.message); $("#stop-btn").disabled = false; }
});

// ---- live recap ----
let POLL = null;
function startPolling(runId) {
  $("#recap-card").classList.remove("hidden");
  if (POLL) clearInterval(POLL);
  const tick = async () => {
    let d; try { d = await api("/api/data-entry/recap" + (runId ? "?run=" + encodeURIComponent(runId) : "")); }
    catch (e) { return; }
    renderRecap(d);
    const rec = d && d.recap;
    const running = rec && !rec.finished_at;
    if (!running) {
      clearInterval(POLL); POLL = null;
      $("#busy-ind").classList.add("hidden");
      setStatus(rec && rec.halted ? ("Arrêté : " + rec.halted) : "Sweep terminé.");
      $("#stop-btn").disabled = false; syncGo();
    }
  };
  tick(); POLL = setInterval(tick, 5000);
}
function renderRecap(d) {
  const rec = d && d.recap;
  $("#recap-run").textContent = d && d.run_id ? "· " + d.run_id : "";
  if (!rec) { $("#recap-summary").textContent = "En attente du premier scan…"; return; }
  const st = rec.finished_at ? (rec.halted ? "halted" : "done") : "running";
  const pill = $("#recap-status");
  pill.textContent = rec.halted ? "ARRÊTÉ — " + rec.halted : (rec.finished_at ? "TERMINÉ" : "EN COURS");
  pill.className = "pill " + st;
  const total = rec.total_created || 0;
  $("#recap-summary").replaceChildren(
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(total) }), el("div", { class: "kpi-l", text: "offres créées" })]),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String((rec.targets || []).length) }), el("div", { class: "kpi-l", text: "marchand(s)" })]),
  );
  const wrap = $("#recap-pages");
  wrap.replaceChildren();
  for (const t of (rec.targets || [])) {
    const sr = t.recap || {};
    wrap.append(el("h3", { class: "t-title", text: t.merchant + " (store " + t.store_id + ") — " + (sr.total_created || 0) + " créées" + (sr.halted ? " · " + sr.halted : "") }));
    for (const p of (sr.pages || [])) {
      const tags = [];
      if (p.end_of_feed) tags.push("fin du feed");
      if (p.empty) tags.push("page vide (feed rétréci)");
      if (p.stopped_before_submit) tags.push("stop avant écriture");
      if (p.error) tags.push("⚠ " + p.error);
      const head = el("div", { class: "pg-head" }, [
        el("span", { class: "pg-n", text: "page " + p.page }),
        el("span", { class: "pg-m", text: (p.offers != null ? p.offers + " offres" : "") + (p.candidates != null ? " · " + p.candidates + " candidats" : "") + (p.created != null ? " · " + p.created + " créées" : "") }),
        tags.length ? el("span", { class: "pg-tag", text: tags.join(" · ") }) : null,
      ]);
      const kids = [head];
      for (const o of (p.offers_created || [])) {
        kids.push(el("div", { class: "off " + (o.created ? "ok" : "no") }, [
          el("span", { class: "off-name", text: o.name || "" }),
          el("span", { class: "off-id", text: o.aks_id ? "AKS " + o.aks_id : "" }),
          el("span", { class: "off-st", text: o.created ? "créée" : (o.post_save || "?") }),
        ]));
      }
      wrap.append(el("div", { class: "pg" }, kids));
    }
  }
}

// ---- init ----
(async function init() {
  setStatus("Prêt");
  try {
    const d = await api("/api/data-entry/merchants");
    SUGGESTED = (d && d.merchants) || [];
  } catch (e) { SUGGESTED = []; }
  SUGGEST_READY = SUGGESTED.length > 0;
  if (!SUGGEST_READY) {
    $("#add-target").disabled = true;
    $("#launch-msg").textContent = "✖ liste des marchands suggérés indisponible — lancement bloqué (fail-closed).";
    syncGo();
    return;
  }
  const first = SUGGESTED.some((m) => m.name === "Kinguin") ? "Kinguin" : SUGGESTED[0].name;
  addTarget(first);
  syncGo();
})();
