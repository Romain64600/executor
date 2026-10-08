"use strict";
// Vue d'ensemble des VPS — LECTURE SEULE (Romain, 2026-09-30 : « Go pour l'onglet vue d'ensemble »).
// Une carte par machine : UP / DOWN et pourquoi, la tâche en cours en clair, les créées, la
// version du code, la charge, les alertes en rouge, les 20 derniers événements, et le lien vers
// SA console. Aucun bouton n'agit sur une machine : la page ne fait que des GET sur
// `api/overview` (chemin RELATIF — nginx sert la console sous /executor/).
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
async function api(path) {
  const r = await fetch(path, { headers: { "X-AKS-Admin": "1" } });
  const t = await r.text();
  let d = null; try { d = t ? JSON.parse(t) : null; } catch (e) {}
  if (!r.ok) throw new Error((d && d.error && d.error.message) || ("HTTP " + r.status));
  return d;
}
const setStatus = (t, busy) => { const f = $("#status"); f.textContent = t; f.className = busy ? "busy" : "idle"; };

// ---- thème (même interrupteur que les autres onglets) ----
(function () {
  let saved = null;
  try { saved = localStorage.getItem("aks-theme"); } catch (e) { saved = null; }
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    try { localStorage.setItem("aks-theme", cur); } catch (e) {}
  });
})();
$("#doc-btn").addEventListener("click", () => $("#doc-modal").showModal());
$("#doc-modal").addEventListener("click", (e) => { if (e.target.id === "doc-modal") e.target.close(); });

// ---- petites mises en forme ----
const REFRESH_MS = 15000;
const STALE_S = 45;
const isStamp = (ts) => typeof ts === "string" && ts.length >= 16 && !Number.isNaN(Date.parse(ts));
const hhmm = (ts) => (isStamp(ts) ? ts.slice(11, 16) + " UTC" : "");
const jourHeure = (ts) => (isStamp(ts) ? ts.slice(8, 10) + "/" + ts.slice(5, 7) + " à " + ts.slice(11, 16) + " UTC" : "");
// Le lien « Ouvrir la console » : http(s) ou la console de cette machine (« . »), jamais autre
// chose (le serveur filtre déjà ; on refiltre ce qu'on met dans un href).
function safeUrl(u) {
  if (u === "." || u === "./") return ".";
  return typeof u === "string" && /^https?:\/\/[^\s"'<>\\]+$/.test(u) ? u : null;
}
function duree(sec) {
  if (typeof sec !== "number" || !(sec >= 0)) return "?";
  const j = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (j) return j + " j " + h + " h";
  if (h) return h + " h " + String(m).padStart(2, "0");
  return m + " min";
}
function ageText(sec) {
  if (sec < 5) return "mis à jour à l'instant";
  if (sec < 90) return "mis à jour il y a " + Math.round(sec) + " s";
  return "mis à jour il y a " + Math.round(sec / 60) + " min";
}
const nombre = (n) => (typeof n === "number" ? n.toLocaleString("fr-FR") : String(n));

// ---- les versions : les machines sont-elles sur le même commit ? ----
const liste = (v) => (Array.isArray(v) ? v : []);
function versionWarning(hosts) {
  const shas = [];
  for (const h of liste(hosts)) {
    const code = h && h.snapshot && h.snapshot.code;
    if (code && code.sha) shas.push([h.name, code.sha]);
  }
  const distinct = new Set(shas.map((x) => x[1]));
  if (distinct.size <= 1) return null;
  return "⚠ Les machines ne sont pas sur le même commit : "
    + shas.map((x) => x[0] + " " + x[1]).join(" · ");
}

// ---- une carte ----
const LOGS_OPEN = {};     // l'état ouvert / fermé du journal de chaque machine, gardé d'un rafraîchissement à l'autre
function taskMeta(task) {
  const out = [];
  if (!task) return out;
  const c = task.created;
  if (c && c.total != null) {
    let t = "Créées : " + nombre(c.total);
    const det = [];
    if (task.loop && c.pass != null && task.state === "running") det.push("passe en cours : " + nombre(c.pass));
    if (c.page != null) det.push("page en cours : " + nombre(c.page));
    if (det.length) t += " (" + det.join(", ") + ")";
    out.push(t);
  }
  if (isStamp(task.started_at)) out.push((task.loop ? "boucle lancée le " : "lancé le ") + jourHeure(task.started_at));
  if (task.run_id) out.push("run " + task.run_id);
  const last = task.last_sweep;
  if (last && last.run_id) {
    let t = "Dernier balayage : " + last.run_id + " — " + nombre(last.created || 0) + " créée(s)";
    if (last.interrupted) {
      // Processus disparu (redémarrage de l'admin, OOM, SIGKILL) : jamais « fini le … ».
      t += ", INTERROMPU sans fin propre";
      if (isStamp(last.last_seen_at)) t += " — dernière trace le " + jourHeure(last.last_seen_at);
    } else {
      if (isStamp(last.ended_at)) t += ", fini le " + jourHeure(last.ended_at);
      if (last.stopped_label) t += " (" + last.stopped_label + ")";
      else if (last.halted) t += " (" + last.halted + ")";
    }
    out.push(t);
  }
  return out;
}
// Romain, 08/10/2026 : « pourquoi notre VM annonce ce statut à la place de dire que ça check ? » — le moniteur price
// check est un service à part de la saisie ; sa ligne vient de status.json et reports.json (snapshot.price_check).
function priceCheckLine(pc) {
  if (!pc || typeof pc !== "object") return null;
  if (!pc.available) return "Price check : état du moniteur inconnu (status.json absent)";
  const hm = (s) => { const m = /T(\d{2}:\d{2})/.exec(String(s || "")); return m ? m[1] : "?"; };
  const modes = pc.modes && typeof pc.modes === "object" ? pc.modes : {};
  const names = { "top-games": "tops", "homepage": "homepage" };
  const running = Object.keys(modes).filter((m) => modes[m] && modes[m].running);
  const parts = [];
  if (running.length) {
    parts.push("contrôle en cours — " + running.map((m) => {
      const st = modes[m], p = Array.isArray(st.progress) && st.progress.length === 2 ? " page " + st.progress[0] + " / " + st.progress[1] : "";
      return (names[m] || m) + p + (st.requested_by ? " (demandé par " + st.requested_by + ")" : "");
    }).join(", "));
  } else {
    parts.push("entre deux passages");
  }
  const last = Object.keys(modes).filter((m) => modes[m] && modes[m].last_end && !modes[m].running)
    .map((m) => (names[m] || m) + " " + hm(modes[m].last_end) + (modes[m].last_alerts ? " (" + modes[m].last_alerts + " alerte(s))" : ""));
  if (last.length) parts.push("dernier passage : " + last.join(", "));
  const next = Object.keys(modes).filter((m) => modes[m] && modes[m].next_at && !modes[m].running).map((m) => modes[m].next_at).sort()[0];
  if (next) parts.push("prochain " + hm(next));
  if (pc.open_reports != null) parts.push(pc.open_reports + " report" + (pc.open_reports === 1 ? "" : "s") + " ouvert" + (pc.open_reports === 1 ? "" : "s"));
  if (pc.age_s != null && pc.age_s > 120) parts.push("état d'il y a " + Math.round(pc.age_s / 60) + " min");
  return "Price check : " + parts.join(" · ");
}
function facts(s) {
  const rows = [];
  const add = (k, v) => { if (v) rows.push(el("div", { class: "fact" }, [el("span", { class: "fk", text: k }), el("span", { class: "fv", text: v })])); };
  if (s.code && s.code.sha) add("Code", s.code.sha + (s.code.branch && s.code.branch !== "main" ? " (" + s.code.branch + ")" : "") + " — " + (s.code.subject || ""));
  else if (s.errors && s.errors.code) add("Code", "illisible (" + s.errors.code + ")");
  if (s.uptime_s != null) add("En route depuis", duree(s.uptime_s));
  if (Array.isArray(s.load)) add("Charge", s.load.join(" / ") + (s.cpus ? " (" + s.cpus + " CPU)" : ""));
  if (s.disk && s.disk.used_pct != null) add("Disque " + (s.disk.path || "/"), Math.round(s.disk.used_pct) + " % (" + s.disk.free_gb + " Go libres)");
  if (s.mem && s.mem.used_pct != null) add("Mémoire", Math.round(s.mem.used_pct) + " %");
  const m = s.last_maintenance;
  if (m && (m.finished_at || m.exit != null)) add("Dernière maintenance", (jourHeure(m.finished_at) || "?") + " — code " + (m.exit != null ? m.exit : "?"));
  if (s.at) add("Photo", hhmm(s.at));
  return rows;
}
function logList(logs) {
  return el("ol", { class: "log" }, logs.map((it) => el("li", { class: "log-line" + (/ABANDON|arrêt :|UNKNOWN|ÉCHEC/.test(it.text || "") ? " bad" : "") }, [
    el("span", { class: "log-ts", text: isStamp(it.ts) ? it.ts.slice(11, 19) : "" }),
    it.merchant ? el("span", { class: "log-where", text: it.merchant + (it.page != null ? " p" + it.page : "") }) : null,
    el("span", { class: "log-text", text: it.text || it.event || "" }),
  ])));
}
function renderHost(h) {
  const up = h.status === "up";
  const s = h.snapshot || null;
  const card = el("article", { class: "card host " + (up ? "up" : "down"), id: "host-" + h.name });
  card.append(el("header", { class: "host-head" }, [
    el("div", { class: "host-id" }, [
      el("h2", { class: "host-name", text: h.name }),
      el("span", { class: "host-label", text: [h.label, s && s.host && s.host !== h.name ? s.host : null].filter(Boolean).join(" · ") }),
    ]),
    el("span", { class: "badge " + (up ? "up" : "down"), text: up ? "UP" : "DOWN" }),
  ]));
  const reasons = liste(h.down_reasons);
  if (!up && reasons.length) {
    card.append(el("ul", { class: "down-reasons" }, reasons.map((r) => el("li", { text: String(r) }))));
  }
  if (s) {
    const task = s.task || {};
    card.append(el("div", { class: "task task-" + (task.type || "autre"), text: task.label || "Rien en cours" }));
    const meta = taskMeta(task);
    if (meta.length) card.append(el("div", { class: "task-meta" }, meta.map((t) => el("span", { text: t }))));
    const pcLine = priceCheckLine(s.price_check);
    if (pcLine) card.append(el("div", { class: "task task-pricecheck", text: pcLine }));
    // Une photo d'une autre version peut avoir une autre forme (revue adverse du 2026-09-30) :
    // le serveur la normalise déjà, la page revérifie ce qu'elle parcourt.
    const alerts = liste(s.alerts);
    if (alerts.length) card.append(el("ul", { class: "alerts" }, alerts.map((a) => el("li", { text: String(a) }))));
    card.append(el("div", { class: "facts" }, facts(s)));
    const open = LOGS_OPEN[h.name] !== false;
    const logs = liste(s.logs).filter((it) => it && typeof it === "object");
    const det = el("details", { class: "logs" }, [
      el("summary", { text: (s.logs_live ? "Journal du run en cours" : "Journal du dernier run") + " — " + logs.length + " événement(s)" }),
      logs.length ? logList(logs) : el("p", { class: "dim-note", text: "Aucun événement." }),
    ]);
    if (open) det.setAttribute("open", "");
    det.addEventListener("toggle", () => { LOGS_OPEN[h.name] = !!det.open; });
    card.append(det);
  }
  const url = safeUrl(h.console_url);
  if (url) {
    card.append(el("a", { class: "console-link", href: url, target: url === "." ? null : "_blank",
                          rel: "noopener noreferrer", text: h.local ? "Ouvrir la console (cette machine)" : "Ouvrir la console ↗" }));
  }
  return card;
}

// ---- la page ----
let LAST_OK = null;      // Date.now() du dernier rafraîchissement réussi
let SEQ = 0;
// Une carte qui ne se dessine pas n'emporte pas les autres : elle dit pourquoi, à sa place.
function cardOrError(h) {
  try { return renderHost(h); }
  catch (e) {
    const name = String((h && h.name) || "?");
    const up = !!h && h.status === "up";
    return el("article", { class: "card host " + (up ? "up" : "down"), id: "host-" + name }, [
      el("header", { class: "host-head" }, [
        el("div", { class: "host-id" }, [el("h2", { class: "host-name", text: name })]),
        el("span", { class: "badge " + (up ? "up" : "down"), text: up ? "UP" : "DOWN" }),
      ]),
      el("ul", { class: "down-reasons" }, [el("li", { text: "carte illisible — " + ((e && e.message) || e) })]),
    ]);
  }
}
function render(d) {
  const hosts = liste(d && d.hosts);
  $("#ov-hosts").replaceChildren(...hosts.map(cardOrError));
  const warn = versionWarning(hosts);
  const v = $("#ov-version");
  v.textContent = warn || "";
  v.className = "ov-warnline" + (warn ? "" : " hidden");
  const cfg = $("#ov-config");
  const c = (d && d.config) || {};
  let note = "";
  if (c.error) note = "⚠ Configuration des machines : " + c.error;
  else if (!c.configured) note = "Seule cette machine est affichée — les autres se déclarent dans " + (c.file || "state/overview_hosts.json") + " (voir ops/VUE_D_ENSEMBLE.md).";
  cfg.textContent = note;
  cfg.className = "ov-note" + (note ? (c.error ? " bad" : "") : " hidden");
  const down = hosts.filter((h) => !h || h.status !== "up").length;
  setStatus(hosts.length + " machine(s) · " + (down ? down + " DOWN" : "toutes UP"), false);
}
function tickAge() {
  const a = $("#ov-age");
  if (LAST_OK == null) { a.className = "ov-age"; return; }
  const sec = Math.max(0, (Date.now() - LAST_OK) / 1000);
  a.textContent = ageText(sec);
  a.className = "ov-age" + (sec > STALE_S ? " stale" : "");
}
async function refresh() {
  const seq = ++SEQ;
  let d;
  try { d = await api("api/overview"); }
  catch (e) {
    if (seq !== SEQ) return;
    setStatus("✖ lecture impossible — " + e.message + " (dernière photo gardée)", false);
    tickAge();
    return;
  }
  if (seq !== SEQ) return;   // une réponse plus ancienne que la dernière demandée n'écrase rien
  try { render(d); }
  catch (e) {
    setStatus("✖ affichage impossible — " + ((e && e.message) || e) + " (dernière photo gardée)", false);
    tickAge();
    return;
  }
  // L'âge affiché est celui de la PHOTO du serveur (gardée 10 s), pas celui de la requête.
  LAST_OK = Date.now() - 1000 * (d && typeof d.age_s === "number" ? d.age_s : 0);
  tickAge();
}
$("#ov-refresh").addEventListener("click", () => { refresh(); });

(function init() {
  setStatus("Chargement…", true);
  refresh();
  setInterval(refresh, REFRESH_MS);
  setInterval(tickAge, 1000);
})();
