"use strict";
// "Price check" — the reports of the first-price monitor (price-check repository). Each card is
// an offer leading an AllKeyShop page, judged SUSPECT, À VÉRIFIER or NON VÉRIFIABLE, with its
// AllKeyShop URL, its merchant URL and its reason. The operator decides (true positive / false
// positive / to discuss): the decision is appended to decisions.jsonl, which the monitor re-reads
// before its next pass. Nothing else is written, nothing is sent.
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

const STALE_SECONDS = 45 * 60;  // export older than this: the monitor may be stopped
const GONE_SECONDS = 60 * 60;   // offer not seen as first price for this long when exported
const REFRESH_MS = 2 * 60 * 1000;
const VERDICT_CLASS = { "SUSPECT": "v-suspect", "À VÉRIFIER": "v-verifier", "NON VÉRIFIABLE": "v-nv" };
// re-check (Romain, 02/10/2026: « on saura si elles sont réparées ou pas »): a flagged offer found OK again, or gone
// from its page, carries fixed_at; one found wrong again carries still_wrong_at. fixed_kind tells why it is OK:
// "repaired", the offer changed (URL, region, platform, edition) or left its page; "rule", nothing changed and a
// rule added since clears it: the alert was a false positive; "verified", it could not be verified before and is now
// verified OK (neither repaired nor a false positive). An entry fixed before fixed_kind existed is "repaired".
const isFixed = (r) => !!r.fixed_at;
const isRuleCleared = (r) => isFixed(r) && r.fixed_kind === "rule";
const isVerified = (r) => isFixed(r) && r.fixed_kind === "verified";
const isRepaired = (r) => isFixed(r) && r.fixed_kind !== "rule" && r.fixed_kind !== "verified";
// Romain, 03/10/2026: « que le report des problèmes sur les tops soit identifié des problèmes home page ». The monitor
// exports `mode`: "top-games" when the offer's page is in the tops right now (first 5 Popular, first 4 Coming soon PC),
// otherwise "homepage"; a top page is also in the homepage TOP 50 (`modes` lists both). An older export has no mode.
const MODE_BADGE = { "top-games": ["TOP", "m-top"], "homepage": ["HOMEPAGE", "m-home"] };
const MODE_TITLE = {
  "top-games": "Price check top : la page est dans les tops (5 premiers Popular, 4 premiers Coming soon PC)",
  "homepage": "Price check homepage : la page est dans les listes de la homepage (top clics, TOP 50)",
};
const isOpen = (r) => !decisionKey(r) && !isFixed(r);
// Romain, 03/10/2026: « je voudrais séparer les problèmes de premiers prix … premier prix = les 3 prix les moins chers
// par édition ». The monitor exports `first_price`; an older export: the rank in the edition (not an account offer).
const isFirstPrice = (r) => (typeof r.first_price === "boolean" ? r.first_price
  : Number.isInteger(r.edition_rank) && r.edition_rank >= 1 && r.edition_rank <= 3 && !r.account);

let DATA = null;         // last answer of api/price-check/reports
let LOADING = false;
const NOTES = {};        // notes being typed, per offer — they survive a re-render / refresh
const ERRORS = {};       // last refused decision, per offer
const BUSY = new Set();  // offers whose decision is being sent

// "2026-10-01 10:48" or "2026-10-01T12:45:00+02:00" → "01/10 10:48": the wall clock the
// server wrote (Europe/Berlin, the clock of the monitor's logs), never re-zoned by the browser.
function stamp(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(s || ""));
  return m ? `${m[3]}/${m[2]} ${m[4]}:${m[5]}` : String(s || "");
}
function ago(sec) {
  if (sec < 90) return "il y a " + Math.max(0, Math.round(sec)) + " s";
  if (sec < 90 * 60) return "il y a " + Math.round(sec / 60) + " min";
  if (sec < 48 * 3600) return "il y a " + Math.round(sec / 3600) + " h";
  return "il y a " + Math.round(sec / 86400) + " j";
}
const price = (p) => (typeof p === "number" ? p.toFixed(2).replace(".", ",") + " €" : "");
const shortLabel = (label) => String(label).split(" : ")[0];
const decisionKey = (r) => (r.decision && r.decision.decision) || "";
const labelOf = (key) => shortLabel((DATA && DATA.decisions && DATA.decisions[key]) || key);
const isGone = (r) => typeof r.seen_lag_seconds === "number" && r.seen_lag_seconds > GONE_SECONDS;
// "2e prix de l'édition (compte)": the offer's rank in its edition when it was checked (Top Offers / Full Page).
const rankLabel = (r) => (r.edition_rank ? (r.edition_rank === 1 ? "1er" : r.edition_rank + "e") +
  " prix de l'édition" + (r.account ? " (compte)" : "") : "");

// A link only for an http(s) URL: a value read from a file never becomes a clickable
// "javascript:" URL.
function link(label, url) {
  const safe = /^https?:\/\//i.test(String(url || ""));
  return el("div", { class: "pc-link" }, [
    el("span", { class: "pc-link-l", text: label }),
    !url ? el("span", { class: "pc-raw", text: "—" })
      : safe ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: url })
        : el("span", { class: "pc-raw", text: url }),
  ]);
}

function matchesFilters(r) {
  const v = $("#f-verdict").value;
  const d = $("#f-decision").value;
  const q = String($("#f-text").value || "").trim().toLowerCase();
  const m = $("#f-mode").value;
  if (m && r.mode !== m) return false;
  if ($("#f-first").checked && !isFirstPrice(r)) return false;
  if (v === "fixed" ? !isRepaired(r) : v === "rule" ? !isRuleCleared(r) : v === "verified" ? !isVerified(r)
    : v && (r.verdict !== v || isFixed(r))) return false;
  if (d === "none" && decisionKey(r)) return false;
  if (d && d !== "none" && decisionKey(r) !== d) return false;
  if ($("#f-live").checked && isGone(r)) return false;
  if (q) {
    const hay = [r.offer, r.product, r.edition, r.merchant, r.region, r.region_filter, r.list,
      r.merchant_url, ...(r.reasons || [])].join(" ").toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function renderSummary(reports) {
  const n = (f) => reports.filter(f).length;
  const kpi = (cls, value, label) => el("div", { class: "kpi " + cls }, [
    el("div", { class: "kpi-n", text: String(value) }), el("div", { class: "kpi-l", text: label })]);
  $("#pc-summary").replaceChildren(
    kpi("k-open", n(isOpen), "sans décision"),
    kpi("k-top", n((r) => isOpen(r) && r.mode === "top-games"), "tops à trancher"),
    kpi("k-home", n((r) => isOpen(r) && r.mode === "homepage"), "homepage à trancher"),
    kpi("k-first", n((r) => isOpen(r) && r.verdict === "SUSPECT" && isFirstPrice(r)), "premiers prix en erreur"),
    kpi("k-suspect", n((r) => r.verdict === "SUSPECT"), "SUSPECT"),
    kpi("k-verifier", n((r) => r.verdict === "À VÉRIFIER"), "À VÉRIFIER"),
    kpi("k-nv", n((r) => r.verdict === "NON VÉRIFIABLE"), "NON VÉRIFIABLE"),
    kpi("k-fixed", n(isRepaired), "réparées"),
    kpi("k-rule", n(isRuleCleared), "faux positifs levés"),
    kpi("k-verified", n(isVerified), "vérifiées OK"),
    kpi("", reports.length, "reports"));
}

function decisionLine(d) {
  return "Décision : " + labelOf(d.decision) + (d.by ? " — par " + d.by : "") +
    (d.at ? " le " + stamp(d.at) : "") + (d.note ? " — « " + d.note + " »" : "");
}

// A note typed and not saved yet (Romain, 05/10/2026 : Rémy typed his comments AFTER clicking the
// decision; the note had left, empty, with the click, and his comments stayed in the fields, never
// saved). On a decided report it is saved on its own: Entrée or « Enregistrer la note » records the
// same decision again, with the note. The card says a note is not saved, and leaving the page asks.
function unsavedNote(offer, r) {
  const typed = String(NOTES[offer] || "").trim();
  return Boolean(typed) && typed !== String((r && r.decision && r.decision.note) || "").trim();
}

function renderItem(r) {
  const offer = String(r.offer);
  const labels = (DATA && DATA.decisions) || {};
  const cur = decisionKey(r);
  const note = el("input", { class: "pc-note", type: "text", maxlength: "1000", autocomplete: "off",
    placeholder: cur ? "note : pourquoi (Entrée pour l'enregistrer)" : "note : pourquoi (facultatif)",
    "aria-label": "Note de décision" });
  note.value = NOTES[offer] != null ? NOTES[offer] : "";
  const saveNote = cur ? el("button", { type: "button", class: "pc-save-note", text: "Enregistrer la note",
    title: "Enregistre la note avec la décision déjà prise (" + labelOf(cur) + ")", onclick: () => decide(offer, cur) }) : null;
  const pending = el("span", { class: "pc-unsaved", text: cur
    ? "Note non enregistrée : Entrée ou « Enregistrer la note »"
    : "Note non enregistrée : elle part avec la décision, choisis-en une" });
  const showPending = () => {
    const open = unsavedNote(offer, r);
    note.classList.toggle("unsaved", open);
    pending.hidden = !open;
    if (saveNote) saveNote.hidden = !open;
  };
  showPending();
  note.addEventListener("input", () => { NOTES[offer] = note.value; showPending(); });
  note.addEventListener("keydown", (ev) => {
    if (!ev || ev.key !== "Enter") return;
    if (ev.preventDefault) ev.preventDefault();
    if (cur && unsavedNote(offer, r)) decide(offer, cur);
  });
  if (saveNote) saveNote.disabled = BUSY.has(offer);
  const buttons = Object.keys(labels).map((k) => {
    const b = el("button", { type: "button", class: "d-" + k + (cur === k ? " on" : ""), title: labels[k],
      text: shortLabel(labels[k]), onclick: () => decide(offer, k) });
    b.disabled = BUSY.has(offer);
    return b;
  });
  const where = [r.list, r.rank ? "#" + r.rank : "", r.at ? "· " + stamp(r.at) : ""].filter(Boolean).join(" ");
  const meta = [
    r.region ? "région AKS : " + r.region + (r.region_filter ? " (" + r.region_filter + ")" : "") : "",
    r.platform ? "plateforme : " + r.platform : "",
    r.method ? "contrôle : " + r.method : "",
    "offre " + offer,
  ].filter(Boolean).join(" · ");
  const before = (r.history || []).slice(0, -1).reverse();
  const was = r.fixed_from ? " (était " + r.fixed_from + ")" : "";
  const recheck = isRuleCleared(r)
    ? el("div", { class: "pc-rule", text: "Faux positif levé par une règle le " + stamp(r.fixed_at) + " : " +
      (r.fixed_how || "rien n'a changé dans l'offre") + was })
    : isVerified(r) ? el("div", { class: "pc-fixed", text: "Vérifiée OK au recontrôle le " + stamp(r.fixed_at) + " : " +
      (r.fixed_how || "vérifiée OK") + was })
    : isFixed(r) ? el("div", { class: "pc-fixed", text: "Réparée le " + stamp(r.fixed_at) + " : " + (r.fixed_how || "recontrôle OK") + was })
    : r.still_wrong_at ? el("div", { class: "pc-still", text: "Toujours en erreur au recontrôle du " + stamp(r.still_wrong_at) }) : null;
  const pill = isRuleCleared(r) ? "FAUX POSITIF LEVÉ" : isVerified(r) ? "VÉRIFIÉE OK" : isFixed(r) ? "RÉPARÉE" : (r.verdict || "?");
  const tone = isRuleCleared(r) ? "v-rule" : isFixed(r) ? "v-fixed" : (VERDICT_CLASS[r.verdict] || "v-nv");
  return el("article", { class: "pc-item " + tone + (cur ? " decided" : ""),
    id: "offer-" + offer }, [
    el("div", { class: "pc-head" }, [
      el("span", { class: "pc-verdict", text: pill }),
      MODE_BADGE[r.mode] ? el("span", { class: "pc-mode " + MODE_BADGE[r.mode][1], title: MODE_TITLE[r.mode],
        text: MODE_BADGE[r.mode][0] }) : null,
      isFirstPrice(r) ? el("span", { class: "pc-mode m-first", text: "PREMIER PRIX",
        title: "L'une des 3 offres de clé les moins chères de son édition : un SUSPECT part sur le salon des urgences" }) : null,
      el("span", { class: "pc-product", text: (r.product || "?") + (r.edition ? " · " + r.edition : "") }),
      rankLabel(r) ? el("span", { class: "pc-rank", text: rankLabel(r) }) : null,
      el("span", { class: "pc-merchant", text: [r.merchant, price(r.price)].filter(Boolean).join(" · ") }),
      el("span", { class: "pc-where", text: where }),
    ]),
    (r.reasons || []).length ? el("ul", { class: "pc-reasons" }, r.reasons.map((x) => el("li", { text: x }))) : null,
    recheck,
    el("div", { class: "pc-meta", text: meta }),
    isGone(r) ? el("div", { class: "pc-gone",
      text: "Plus vu en premier prix depuis le " + stamp(r.seen_at) + " : l'offre n'est plus en tête." }) : null,
    (r.notes || []).length ? el("ul", { class: "pc-notes" }, r.notes.map((x) => el("li", { text: x }))) : null,
    link("Page AllKeyShop", r.page_url),
    link("Offre marchand", r.merchant_url),
    // 03/10/2026 : le fil de feedback Discord de l'alerte (le bot l'ouvre ; on peut y trancher aussi)
    r.discord_thread ? link("Fil Discord", r.discord_thread) : null,
    el("div", { class: "pc-decide" }, [...buttons, note, saveNote, pending]),
    r.decision ? el("div", { class: "pc-decision", text: decisionLine(r.decision) }) : null,
    before.length ? el("div", { class: "pc-history", text: "Avant : " + before.map((h) =>
      labelOf(h.decision) + (h.by ? " (" + h.by + (h.at ? ", " + stamp(h.at) : "") + ")" : "")).join(" ; ") }) : null,
    ERRORS[offer] ? el("div", { class: "pc-msg", text: "Non enregistrée : " + ERRORS[offer] }) : null,
  ]);
}

function render() {
  if (!DATA) return;
  const reports = DATA.reports || [];
  renderSummary(reports);
  const shown = reports.filter(matchesFilters);
  $("#pc-list").replaceChildren(...(shown.length ? shown.map(renderItem) : [el("div", { class: "pc-empty",
    text: reports.length ? "Aucun report pour ces filtres." : "Aucun report : le moniteur n'a rien signalé." })]));
}

function renderFreshness() {
  const age = DATA.age_seconds;
  $("#pc-fresh").textContent = "— export du " + stamp(DATA.generated_at) +
    (typeof age === "number" ? " (" + ago(age) + ")" : "");
  const stale = typeof age === "number" && age > STALE_SECONDS;
  $("#pc-stale").classList.toggle("hidden", !stale);
  $("#pc-stale").textContent = stale ? "Dernier export du moniteur " + ago(age) +
    " : le service price-check est peut-être arrêté (systemctl status price-check)." : "";
}

async function load() {
  if (LOADING) return;
  LOADING = true;
  setStatus("Lecture des reports…", true);
  try {
    DATA = await api("api/price-check/reports");
    $("#pc-error").classList.add("hidden");
    renderFreshness();
    render();
    setStatus((DATA.reports || []).length + " report(s) lus dans " + DATA.dir, false);
  } catch (e) {
    $("#pc-error").textContent = "Reports illisibles : " + e.message;
    $("#pc-error").classList.remove("hidden");
    setStatus("Erreur : " + e.message, false);
  } finally {
    LOADING = false;
  }
}

async function decide(offer, key) {
  if (BUSY.has(offer)) return;
  BUSY.add(offer);
  delete ERRORS[offer];
  const note = NOTES[offer] || "";
  const was = decisionKey(((DATA && DATA.reports) || []).find((x) => String(x.offer) === offer) || {});
  render();
  setStatus(was === key ? "Enregistrement de la note…" : "Enregistrement de la décision…", true);
  try {
    const res = await api("api/price-check/decision", { method: "POST",
      body: JSON.stringify({ offer, decision: key, note }) });
    const rec = res && res.recorded;
    if (!rec || rec.offer !== offer || rec.decision !== key) throw new Error("réponse inattendue du serveur");
    const target = ((DATA && DATA.reports) || []).find((x) => String(x.offer) === offer);
    if (target) {
      target.history = [...(target.history || []), rec];
      target.decision = rec;
    }
    delete NOTES[offer];
    setStatus((was === key ? "Note enregistrée : " : "Décision enregistrée : ") + ((target && target.product) || offer) +
      " — " + labelOf(key) + (note.trim() ? " — « " + note.trim() + " »" : ""), false);
  } catch (e) {
    ERRORS[offer] = e.message;
    setStatus("Décision non enregistrée : " + e.message, false);
  } finally {
    BUSY.delete(offer);
    render();
  }
}

for (const id of ["#f-verdict", "#f-mode", "#f-decision", "#f-live", "#f-first"]) $(id).addEventListener("change", render);
$("#f-text").addEventListener("input", render);
$("#refresh").addEventListener("click", load);

// A link to one report (…/price-check#offer-<id>) opens the page filtered on that offer.
if (typeof location !== "undefined" && /^#offer-\d+$/.test(location.hash || "")) {
  $("#f-text").value = location.hash.slice("#offer-".length);
}

// Refresh in the background, but never under the operator's fingers: not while a note has
// the focus, not while a decision is being sent (typed notes survive a refresh anyway).
setInterval(() => {
  const a = document.activeElement;
  if (BUSY.size || (a && a.classList && a.classList.contains("pc-note"))) return;
  if (document.visibilityState === "hidden") return;
  load();
}, REFRESH_MS);

load();

// Leaving or reloading the page with a typed note not saved yet: the browser asks first (05/10/2026).
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("beforeunload", (ev) => {
    const reports = (DATA && DATA.reports) || [];
    if (!reports.some((r) => unsavedNote(String(r.offer), r))) return undefined;
    ev.preventDefault();
    ev.returnValue = "";
    return "";
  });
}

// ---- the two run buttons (Romain, 02/10/2026: « Price check top », « Price check homepage ») ----
// The admin never runs anything itself: it drops run-<mode>.request in the shared directory and the
// monitor (its own root process) reads it within seconds. status.json, written by the monitor, feeds the state.
const RUN_MODES = ["top-games", "homepage"];
const STATUS_MS = 10 * 1000;
let STATUS = null;

// "2026-10-02T17:55:21+0200" → seconds since midnight, as the server wrote it (no re-zoning)
function clockSeconds(s) {
  const m = /T(\d{2}):(\d{2}):(\d{2})/.exec(String(s || ""));
  return m ? (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) : null;
}
function duration(start, end) {
  const a = clockSeconds(start), b = clockSeconds(end);
  if (a == null || b == null) return "";
  let d = b - a;
  if (d < 0) d += 86400;
  if (d < 60) return d + " s";
  if (d < 3600) return Math.floor(d / 60) + " min " + String(d % 60).padStart(2, "0") + " s";
  return Math.floor(d / 3600) + " h " + String(Math.floor((d % 3600) / 60)).padStart(2, "0") + " min";
}

function renderRuns() {
  const st = STATUS;
  $("#pc-runs-note").textContent = st && st.available ? "— état du moniteur " + ago(st.age_seconds) : "";
  for (const mode of RUN_MODES) {
    const state = $("#state-" + mode), btn = $("#launch-" + mode);
    const pending = st && st.pending && st.pending[mode];
    if (!st || !st.available) {
      state.textContent = "État du moniteur inconnu (status.json absent) : le bouton dépose quand même la demande." +
        (pending ? " Demande en attente." : "");
      btn.disabled = !!pending;
      continue;
    }
    const m = st.modes[mode];
    if (!m) { state.textContent = "Mode non suivi par le moniteur."; btn.disabled = true; continue; }
    const parts = [];
    if (m.running) {
      parts.push("En cours" + (m.progress ? " : page " + m.progress[0] + " / " + m.progress[1] : "") +
        (m.requested_by ? " (demandé par " + m.requested_by + ")" : ""));
    } else if (m.last_end) {
      // a pass only checks offers never seen before: a quiet pass is the normal case, say so
      const about = [duration(m.last_start, m.last_end), m.pages ? m.pages + " pages lues" : "",
        m.last_requested_by ? "lancé depuis l'admin par " + m.last_requested_by : ""].filter(Boolean).join(", ");
      parts.push("Dernier passage " + stamp(m.last_start) + (about ? " (" + about + ")" : "") + " : " +
        (m.last_checked ? m.last_checked + " nouvelle(s) offre(s) contrôlée(s)" : "aucune nouvelle offre à contrôler") +
        ", " + (m.last_alerts || 0) + " alerte(s)");
    }
    const rc = m.last_recheck;
    if (rc && rc.at) {
      parts.push((rc.kind === "all" ? "Recontrôle complet " : "Recontrôle des offres signalées ") + stamp(rc.at) + " : " +
        (rc.checked || 0) + " offre(s), " + (rc.fixed || 0) + " réparée(s), " +
        (rc.rules ? rc.rules + " faux positif(s) levé(s) par une règle, " : "") +
        (rc.verified ? rc.verified + " vérifiée(s) OK, " : "") + (rc.new || 0) + " nouvelle(s) erreur(s), " +
        (rc.still || 0) + " toujours en erreur");
    }
    if (!m.running && m.next_at) parts.push("prochain passage " + stamp(m.next_at));
    if (pending) parts.push("demande en attente" + (pending.by ? " (" + pending.by + ")" : ""));
    state.textContent = parts.join(" · ") || "Aucun passage encore.";
    btn.disabled = !!pending || !!m.running;
  }
}

async function loadStatus() {
  try { STATUS = await api("api/price-check/status"); } catch (e) { STATUS = null; }
  renderRuns();
}

async function launch(mode) {
  const btn = $("#launch-" + mode), msg = $("#msg-" + mode);
  btn.disabled = true;
  msg.textContent = "";
  try {
    const r = await api("api/price-check/run", { method: "POST", body: JSON.stringify({ mode }) });
    const who = r && r.requested && r.requested.by ? " par " + r.requested.by : "";
    msg.textContent = "Demande déposée" + who + " : le moniteur la lit dans les secondes qui viennent.";
  } catch (e) {
    msg.textContent = "Refusé : " + e.message;
    btn.disabled = false;
  }
  await loadStatus();
}

for (const mode of RUN_MODES) $("#launch-" + mode).addEventListener("click", () => launch(mode));
setInterval(() => { if (document.visibilityState !== "hidden") loadStatus(); }, STATUS_MS);
loadStatus();
