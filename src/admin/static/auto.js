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
let SWEEP_RUNNING = false; // a data-entry-auto sweep is active (launched here OR elsewhere)
let LIVE_RUN_ID = null;    // le run AFFICHÉ — celui auquel un « + marchand » doit être lié
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
  const go = $("#go").value.trim().toUpperCase() === "GO";
  const ok = SUGGEST_READY && !SWEEP_RUNNING && collectTargets().length > 0 && go;
  // "Sweep de nuit": same typed GO, but no per-merchant row to fill — the server reads
  // the allowlist itself. Disabled while any run is active (Romain 2026-09-16: « sauf si
  // ce sweep est deja en cours »); the server refuses it too (409 submit_in_progress).
  const all = $("#launch-all");
  if (all) all.disabled = !(SUGGEST_READY && !SWEEP_RUNNING && go);
  // Les groupes suivent la même règle que le sweep de nuit : le GO tapé, et aucun run en
  // cours (une machine tient un seul onglet — le serveur répond 409 de toute façon).
  if (typeof GROUPS !== "undefined") {
    GROUPS.forEach((g) => {
      const b = $("#launch-group-" + g.name);
      if (b) b.disabled = !(SUGGEST_READY && !SWEEP_RUNNING && go);
    });
  }
  $("#launch").disabled = !ok;
  // Réfuteur du 2026-09-19 : « + marchand » restait actif après « Sweep terminé », et le clic
  // partait avec run_id=null. Le serveur exige maintenant le run_id ; côté écran, pas de
  // bouton sans run affiché.
  const live = $("#add-live-btn"); if (live) live.disabled = !SWEEP_RUNNING;
}
$("#add-target").addEventListener("click", () => { if (SUGGEST_READY) addTarget().focus(); });
$("#go").addEventListener("input", syncGo);

// ---- pages balayées (Romain 2026-09-24) ----
// « Pouvoir choisir à partir de quelle page je lance. Je lance toujours en direction de 1 […]
// on prend toutes les pages, ou on commence à la page 20 jusqu'à 1, ou de la page 10 jusqu'à
// 1. » UN réglage pour les trois boutons. « De la page N » = `max_pages: N` : le balayage part
// de min(N, dernière page du feed) et descend jusqu'à la 1 (data_entry_auto, start_page 1).
// L'ancien champ « Page de départ » envoyait `start_page`, qui est la page où le balayage
// S'ARRÊTE : taper 20 y aurait sauté les pages 19 à 1 — l'inverse de ce qu'on veut. Il est
// retiré de l'écran (le CLI garde --start-page).
function pageRange() {
  if (!$("#range-from").checked) return { all_pages: true };
  const v = String($("#from-page").value || "").trim();
  const n = parseInt(v, 10);
  if (!/^\d+$/.test(v) || !(n >= 1)) {
    throw new Error("« de la page N » : indique un entier ≥ 1, ou choisis « toutes »");
  }
  return { all_pages: false, max_pages: n };
}
function rangeLabel(r) { return r.all_pages ? "toutes les pages" : `pages ${r.max_pages} → 1`; }

// ---- launch ----
$("#launch").addEventListener("click", async () => {
  const targets = collectTargets();
  if (!targets.length || $("#go").value.trim().toUpperCase() !== "GO") return;
  // [11] the server re-enforces the typed GO (confirm=GO) like every other real-write
  // path — send it, not just gate the button client-side.
  const body = { targets, confirm: "GO", list: currentList() };
  try { Object.assign(body, pageRange()); }
  catch (e) { $("#launch-msg").textContent = "✖ " + e.message; return; }
  // [R45] consoles by default (Romain 2026-09-15); unticked = PC-only sweep (--no-consoles).
  body.consoles = $("#consoles").checked;
  // 2026-09-19 : ce bouton n'envoyait PAS `continue_on_halt`, donc il valait False — alors que
  // le bouton « sweep de nuit » le force depuis toujours. Romain a relancé trois marchands
  // (GameSeal, CJS, Gamivo) et a cherché la case : elle n'existait pas. Conséquence concrète :
  // une halte fail-closed sur le PREMIER marchand emporte tous les suivants, et c'est
  // précisément le lancement sélectif qu'on utilise pour reprendre après une halte. Cochée par
  // défaut, comme le sweep de nuit ; décocher = le lot s'arrête au premier marchand en échec.
  body.continue_on_halt = $("#continue-on-halt").checked;
  $("#launch").disabled = true;
  $("#launch-msg").textContent = "Lancement…";
  try {
    const r = await api("api/data-entry/auto", { method: "POST", body: JSON.stringify(body) });
    $("#launch-msg").textContent = "▶ sweep lancé : " + (r.run_id || "") + " · " + rangeLabel(body);
    SWEEP_RUNNING = true;
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
// ---- night sweep: every allowlisted merchant ----
$("#launch-all").addEventListener("click", async () => {
  if ($("#go").value.trim().toUpperCase() !== "GO" || SWEEP_RUNNING) return;
  // Par défaut couverture TOTALE (Romain 2026-09-18 : « on fait toutes les pages sauf lors
  // d'un arrêt pour sécurité ») ; depuis le 2026-09-24 le réglage « Pages » peut la borner à
  // « de la page N jusqu'à la 1 ».
  const body = { all_allowlisted: true, confirm: "GO", list: currentList() };
  try { Object.assign(body, pageRange()); }
  catch (e) { $("#launch-all-msg").textContent = "✖ " + e.message; return; }
  body.consoles = $("#consoles").checked;
  body.continue_on_halt = true;   // one merchant's fail-closed stop must not end the night
  $("#launch-all").disabled = true;
  $("#launch-all-msg").textContent = "Lancement du sweep de nuit (" + rangeLabel(body) + ")…";
  try {
    const r = await api("api/data-entry/auto", { method: "POST", body: JSON.stringify(body) });
    $("#launch-all-msg").textContent = "▶ sweep de nuit lancé : " + (r.run_id || "")
      + " · " + SUGGESTED.length + " marchand(s) · " + rangeLabel(body);
    SWEEP_RUNNING = true;
    setStatus("Sweep de nuit en cours…", true);
    $("#busy-ind").classList.remove("hidden");
    $("#busy-text").textContent = "sweep de nuit · " + SUGGESTED.length + " marchands";
    startPolling(r.run_id);
  } catch (e) {
    $("#launch-all-msg").textContent = "✖ refusé : " + e.message;
    setStatus("Refusé — " + e.message);
    syncGo();
  }
});
// ---- ajouter un marchand au sweep EN COURS (Romain 2026-09-19) ----
// Le sweep relit la file à chaque FRONTIÈRE de marchand : la cible ajoutée ne coupe rien,
// elle attend son tour. Le GO est exigé parce que c'est la même autorisation qu'un lancement —
// un marchand ajouté écrit sur AKS sans validation humaine.
function fillLiveMerchants() {
  const sel = $("#add-live-merchant");
  if (!sel || sel.options.length) return;
  sel.replaceChildren(...SUGGESTED.map((m) =>
    el("option", { value: `${m.name}|${m.store_id}` }, `${m.name} (${m.store_id})`)));
}

$("#add-live-btn").addEventListener("click", async () => {
  const msg = $("#add-live-msg");
  const raw = $("#add-live-merchant").value || "";
  const [merchant, store_id] = raw.split("|");
  if (!merchant || !store_id) { msg.textContent = "choisis un marchand"; return; }
  if (($("#add-live-go").value || "").trim().toUpperCase() !== "GO") {
    msg.textContent = "tape GO"; return;
  }
  $("#add-live-btn").disabled = true;
  try {
    const r = await api("api/data-entry/auto/add-target", {
      method: "POST",
      // Revue de Romain (2026-09-19) : lier l'ajout au run AFFICHÉ. Si le sweep A a fini et
      // que B a démarré entre l'affichage et le clic, le serveur refuse au lieu de faire
      // rejoindre B au marchand — avec les paramètres de B.
      body: JSON.stringify({ merchant, store_id, confirm: "GO", run_id: LIVE_RUN_ID }),
    });
    // Le run est NOMMÉ dans le message : l'opérateur voit à quoi son ajout est lié.
    msg.textContent = r.queued
      ? `✔ ${merchant} ajouté à ${r.run_id} — position ${r.position} dans la file`
      : `⚠ ${r.reason || "non pris"}`;
    $("#add-live-go").value = "";
  } catch (e) {
    msg.textContent = "✖ " + e.message;
  }
  syncGo();   // revue /code-review : pas de ré-armement inconditionnel — si le sweep a fini pendant l'attente, le bouton reste éteint
});

$("#stop-btn").addEventListener("click", async () => {
  $("#stop-btn").disabled = true;
  // Audit 2026-09-18 : un 200 ne prouve pas qu'un run a été arrêté. `stopped: null`
  // veut dire « rien à arrêter » — l'annoncer comme un arrêt était le mensonge du frein.
  try {
    const r = await api("api/sort/stop", { method: "POST", body: "{}" });
    if (r && r.stopped) setStatus("Arrêt demandé (entre pages)…", true);
    else { setStatus("Rien à arrêter — " + ((r && r.reason) || "aucun run en cours")); $("#stop-btn").disabled = false; }
  }
  catch (e) { setStatus("Stop refusé — " + e.message); $("#stop-btn").disabled = false; }
});

// ---- live recap ----
let POLL = null, POLL_SEQ = 0;
// The manager is the authoritative "is a sweep running" signal — it works even
// if the recap route is momentarily unavailable. undefined = transient error
// (don't declare finished on a blip); null = idle; {kind,run_id} = active.
async function fetchBusy() {
  try { const d = await api("api/sort/runs"); return d ? (d.busy || null) : null; }
  catch (e) { return undefined; }
}
function endSweepUi(finalText) {
  // Retire the generation too: clearInterval cannot cancel a tick already waiting on the
  // network, and such a tick would otherwise declare a LATER sweep finished (audit
  // 2026-09-17, même classe que le sondage du tri).
  POLL_SEQ++;
  clearInterval(POLL); POLL = null;
  SWEEP_RUNNING = false;
  LIVE_RUN_ID = null;       // plus de run affiché : un « + marchand » tardif n'a rien à lier
  $("#busy-ind").classList.add("hidden");
  setStatus(finalText);
  $("#stop-btn").disabled = false;
  syncGo();
}
function startPolling(runId) {
  LIVE_RUN_ID = runId || null;
  { const live = $("#add-live-btn"); if (live) live.disabled = !LIVE_RUN_ID; }   // un run affiché ⇒ on peut y ajouter
  $("#recap-card").classList.remove("hidden");
  $("#busy-ind").classList.remove("hidden");
  if (POLL) clearInterval(POLL);
  // This polling's generation. `tick` awaits TWICE, so it is checked after each await: a tick
  // left over from a previous sweep must never renderRecap into this one, and above all must
  // never reach endSweepUi — that would clear the LIVE interval and re-enable the GO while a
  // sweep is still writing on AKS.
  POLL_SEQ++;
  const seq = POLL_SEQ;
  const tick = async () => {
    const busy = await fetchBusy();
    if (seq !== POLL_SEQ) return;
    let d = null;
    try { d = await api("api/data-entry/recap" + (runId ? "?run=" + encodeURIComponent(runId) : "")); }
    catch (e) { d = null; }        // recap detail may be unavailable; busy still drives run state
    if (seq !== POLL_SEQ) return;
    if (d) renderRecap(d);
    const rec = d && d.recap;
    // Still running if the manager reports an auto sweep, or (busy unknown) on a
    // transient error; finished only once the manager is idle for this kind.
    let running;
    if (busy === undefined) running = true;
    else if (busy && busy.kind === "data_entry_auto") running = true;
    else if (rec) running = !rec.finished_at;
    else running = false;
    if (!running) {
      const cov = rec && rec.coverage_incomplete && rec.coverage_incomplete.length ? rec.coverage_incomplete : [];
      endSweepUi(rec && rec.halted ? ("Arrêté : " + rec.halted)
                 : (cov.length ? "Sweep terminé — couverture partielle : " + cov.join(" ; ") : "Sweep terminé."));
    }
  };
  tick(); POLL = setInterval(tick, 5000);
}
// On page load, adopt a sweep already running (launched here earlier, elsewhere,
// or before a reload) so the page shows it instead of looking merely "blocked".
async function resumeIfActive() {
  const busy = await fetchBusy();
  if (busy && busy.kind === "data_entry_auto") {
    SWEEP_RUNNING = true;
    $("#busy-text").textContent = "sweep en cours" + (busy.run_id ? " · " + busy.run_id : "");
    $("#launch-msg").textContent = "Un sweep est déjà en cours — attends la fin ou clique Arrêter.";
    setStatus("Sweep en cours…", true);
    startPolling(busy.run_id);
    return true;
  }
  return false;
}
// No sweep running: still show the LAST sweep's recap so the operator can audit
// it after the fact (the recap's whole purpose) instead of a bare launch form.
async function showLastRecap() {
  let d; try { d = await api("api/data-entry/recap"); } catch (e) { return; }
  if (d && d.recap) { $("#recap-card").classList.remove("hidden"); renderRecap(d); }
}
function renderRecap(d) {
  const rec = d && d.recap;
  $("#recap-run").textContent = d && d.run_id ? "· " + d.run_id : "";
  if (!rec) { $("#recap-summary").textContent = "En attente du premier scan…"; return; }
  const st = rec.finished_at ? (rec.halted ? "halted" : "done") : "running";
  const pill = $("#recap-status");
  // A coverage cap (max_pages / feed grew) is NOT a halt: the run is done, just not deep.
  const partial = (rec.coverage_incomplete && rec.coverage_incomplete.length) ||
                  (rec.targets || []).some(t => t.recap && t.recap.coverage);
  pill.textContent = rec.halted ? "ARRÊTÉ — " + rec.halted
                   : (rec.finished_at ? (partial ? "TERMINÉ — couverture partielle" : "TERMINÉ") : "EN COURS");
  pill.className = "pill " + st;
  const total = rec.total_created || 0;
  // La FILE d'ajouts, visible (revue /code-review 2026-09-19) : la réponse « NON garantie ;
  // le recap fait foi » renvoyait l'opérateur vers un recap dont l'écran n'affichait que les
  // marchands déjà démarrés — impossible de distinguer « en file, pas commencé » de « jamais
  // pris ». Chaque liste du recap a sa ligne, avec le nom du marchand.
  const names = (xs) => (xs || []).map((t) => t.merchant + (t.reason ? " (" + t.reason + ")" : "")).join(", ");
  const queueLines = [];
  if ((rec.targets_added || []).length) queueLines.push("+ ajoutés en cours de run : " + names(rec.targets_added));
  if ((rec.targets_not_reached || []).length) queueLines.push("✖ jamais atteints : " + names(rec.targets_not_reached));
  if ((rec.targets_refused || []).length) queueLines.push("⛔ refusés (liste blanche) : " + names(rec.targets_refused));
  if ((rec.targets_ignored || []).length) queueLines.push("— ignorés (déjà cibles) : " + names(rec.targets_ignored));
  if (rec.queue_closed) queueLines.push("file fermée — le sweep termine, plus d'ajout possible");
  $("#recap-summary").replaceChildren(
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String(total) }), el("div", { class: "kpi-l", text: "offres créées" })]),
    ...queueLines.map((t) => el("div", { class: "queue-line", text: t })),
    el("div", { class: "kpi" }, [el("div", { class: "kpi-n", text: String((rec.targets || []).length) }), el("div", { class: "kpi-l", text: "marchand(s)" })]),
  );
  const wrap = $("#recap-pages");
  wrap.replaceChildren();
  for (const t of (rec.targets || [])) {
    const sr = t.recap || {};
    wrap.append(el("h3", { class: "t-title", text: t.merchant + " (store " + t.store_id + ") — " + (sr.total_created || 0) + " créées" + (sr.halted ? " · " + sr.halted : "") + (sr.coverage ? " · couverture : " + sr.coverage : "") }));
    for (const p of (sr.pages || [])) {
      const tags = [];
      if (p.end_of_feed) tags.push("fin du feed");
      if (p.empty) tags.push("page vide (feed rétréci)");
      if (p.stopped_before_submit) tags.push("stop avant écriture");
      if (p.probe_unreliable) tags.push("⚠ " + p.probe_unreliable + " sonde(s) AKS non fiable(s)");
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

// ---- groupes de marchands (une machine, un groupe) ----
// Romain, 2026-09-22 : « je ne vois pas les groupes A et B sur l'admin ». La console ne les
// invente pas : elle affiche ce que le serveur lui envoie et lui renvoie un NOM de groupe —
// c'est le serveur qui le détend sur la liste blanche, comme pour le sweep de nuit.
let GROUPS = [];
// La liste AKS balayée (Romain, 2026-09-23 : « je voudrais pouvoir choisir la liste depuis
// l'admin. Par défaut on sera en pending offers, liste 9 »). La console ne fabrique pas ce
// catalogue : elle l'affiche tel que le serveur l'envoie, et lui renvoie un NOMBRE. Le
// serveur re-valide (entier, positif, jamais la Blacklist) — un client bricolé ne choisit
// donc pas une liste interdite par ce chemin.
let LISTS = [];
let DEFAULT_LIST = 9;

function renderLists() {
  const sel = $("#work-list");
  if (!sel) return;
  sel.replaceChildren();
  LISTS.forEach((l) => {
    const o = document.createElement("option");
    o.value = String(l.id);
    o.textContent = l.id === DEFAULT_LIST ? (l.label + " (" + l.id + ") — défaut")
                                          : (l.label + " (" + l.id + ")");
    if (l.id === DEFAULT_LIST) o.selected = true;
    sel.appendChild(o);
  });
  // …et on pose AUSSI `value`. `option.selected` suffit dans un navigateur, mais le rendre
  // explicite évite de dépendre de ce reflet — et le bouchon des tests, qui n'implémente
  // pas la sémantique du <select>, lit alors la même chose que l'écran réel.
  sel.value = String(DEFAULT_LIST);
  syncListNote();
}

function currentList() {
  const sel = $("#work-list");
  const v = sel && sel.value ? parseInt(sel.value, 10) : DEFAULT_LIST;
  return Number.isFinite(v) && v > 0 ? v : DEFAULT_LIST;
}

function syncListNote() {
  const note = $("#list-note");
  if (!note) return;
  const l = currentList();
  note.textContent = l === DEFAULT_LIST
    ? "file de travail habituelle"
    : "⚠ liste " + l + " — le submit prouvera la disparition dans CETTE liste";
}


function renderGroups() {
  const zone = $("#group-buttons");
  const note = $("#groups-note");
  if (!zone) return;
  zone.textContent = "";
  if (!GROUPS.length) {
    if (note) note.textContent = "Aucun groupe déclaré côté serveur.";
    return;
  }
  if (note) {
    note.textContent = GROUPS.map((g) => "groupe " + g.name + " : " + g.merchants.length
      + " marchand(s), ~" + g.pending + " lignes en attente").join(" · ") + ".";
  }
  GROUPS.forEach((g) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "danger";
    b.id = "launch-group-" + g.name;
    b.disabled = true;
    b.textContent = "Lancer le groupe " + g.name;
    b.title = g.merchants.map((m) => m.name).join(", ")
      + " — toutes les pages, un arrêt fail-closed n'arrête pas les autres marchands.";
    b.addEventListener("click", () => launchGroup(g));
    zone.appendChild(b);
  });
  syncGo();
}

async function launchGroup(group) {
  if ($("#go").value.trim().toUpperCase() !== "GO" || SWEEP_RUNNING) return;
  const body = { group: group.name, confirm: "GO",
                 continue_on_halt: true, consoles: $("#consoles").checked,
                 list: currentList() };
  try { Object.assign(body, pageRange()); }
  catch (e) { $("#launch-group-msg").textContent = "✖ " + e.message; return; }
  GROUPS.forEach((g) => { const b = $("#launch-group-" + g.name); if (b) b.disabled = true; });
  $("#launch-group-msg").textContent = "Lancement du groupe " + group.name + "…";
  try {
    const r = await api("api/data-entry/auto", { method: "POST", body: JSON.stringify(body) });
    $("#launch-group-msg").textContent = "▶ groupe " + group.name + " lancé : " + (r.run_id || "")
      + " · " + group.merchants.length + " marchand(s) · " + rangeLabel(body);
    // REVUE DE ROMAIN (2026-09-23) : « après le lancement, aucun startPolling() : l'écran
    // reste « Prêt », le récapitulatif ne s'actualise pas et les boutons restent bloqués
    // après la fin, jusqu'au rechargement ». Exact — ce bouton posait SWEEP_RUNNING et
    // s'arrêtait là, alors que les deux autres lancements suivent le run. Il fait désormais
    // exactement comme eux : statut, indicateur, suivi. C'est `startPolling` qui, à la fin
    // du run, relâche SWEEP_RUNNING et réarme les boutons.
    SWEEP_RUNNING = true;
    setStatus("Groupe " + group.name + " en cours…", true);
    $("#busy-ind").classList.remove("hidden");
    $("#busy-text").textContent = "groupe " + group.name + " · "
      + group.merchants.length + " marchand(s)";
    startPolling(r.run_id);
  } catch (e) {
    $("#launch-group-msg").textContent = "✖ " + (e && e.message ? e.message : e);
    syncGo();
  }
}

// ---- init ----
(async function init() {
  setStatus("Prêt");
  try {
    const d = await api("api/data-entry/merchants");
    SUGGESTED = (d && d.merchants) || [];
    GROUPS = (d && d.groups) || [];
    LISTS = (d && d.lists) || [];
    if (d && d.default_list) DEFAULT_LIST = d.default_list;
    renderLists();
    renderGroups();
    const sel = $("#work-list");
    if (sel) sel.addEventListener("change", syncListNote);
    const cnt = $("#all-count");
    if (cnt) cnt.textContent = "Aujourd'hui : " + SUGGESTED.length + " marchand(s) — "
      + SUGGESTED.map((m) => m.name).join(", ") + ".";
  } catch (e) { SUGGESTED = []; }
  SUGGEST_READY = SUGGESTED.length > 0;
  fillLiveMerchants();      // la liste « + marchand » du sweep en cours vient de la même source
  if (!SUGGEST_READY) {
    $("#add-target").disabled = true;
    $("#launch-msg").textContent = "✖ liste des marchands suggérés indisponible — lancement bloqué (fail-closed).";
    syncGo();
    return;
  }
  const first = SUGGESTED.some((m) => m.name === "Kinguin") ? "Kinguin" : SUGGESTED[0].name;
  addTarget(first);
  // Adopt an already-running sweep; else surface the last finished recap to audit.
  if (!(await resumeIfActive())) await showLastRecap();
  syncGo();
})();
