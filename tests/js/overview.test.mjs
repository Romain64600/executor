// La VUE D'ENSEMBLE des VPS, EXÉCUTÉE (Romain, 2026-09-30 : « Go pour l'onglet vue d'ensemble »).
//
// Le harnais charge le vrai `overview.js` dans le navigateur bouchonné, lui sert des réponses de
// `api/overview` à la main, et regarde l'écran : le badge UP / DOWN et son motif, la tâche en
// clair, les alertes, l'avertissement quand les machines ne sont pas sur le même commit, le
// rafraîchissement toutes les 15 s et « mis à jour il y a N s ». Et ce qui part vers l'admin :
// des GET relatifs sur `api/overview`, rien d'autre.

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole } from "./load_console.mjs";
import { tick } from "./dom_stub.mjs";

const ICI = path.dirname(fileURLToPath(import.meta.url));
// `OVERVIEW_JS` rejoue le harnais contre une page VOLONTAIREMENT cassée (voir le test Python).
const PAGE = process.env.OVERVIEW_JS
  || path.join(ICI, "..", "..", "src", "admin", "static", "overview.js");

const T0 = Date.parse("2026-09-30T15:00:00Z");

function snap(extra = {}) {
  return Object.assign({
    schema: 1, host: "vmi3565249", at: "2026-09-30T15:00:00Z",
    code: { sha: "2272e92", subject: "fix: maintenance", branch: "main" },
    services: { "aks-admin": "active", "aks-chromium": "active", nginx: "active" },
    admin: { reachable: true, busy: null }, uptime_s: 90061, load: [0.5, 0.4, 0.3], cpus: 8,
    disk: { path: "/", used_pct: 12.3, free_gb: 200 }, mem: { used_pct: 40 },
    task: { type: "aucune", label: "Rien en cours" }, logs: [], alerts: [], errors: {},
  }, extra);
}
function payload(hosts, extra = {}) {
  return Object.assign({ at: "2026-09-30T15:00:00Z", hosts, ttl_s: 10, cached: false, age_s: 0,
                         config: { file: "state/overview_hosts.json", configured: true, error: null } }, extra);
}
const PROD = {
  name: "cette-vm", label: "production · groupe B", local: true, console_url: ".",
  status: "up", down_reasons: [], reachable: true,
  snapshot: snap({
    task: { type: "balayage", label: "Balayage groupe A en boucle — passe 3, GOG page 12, saisie depuis 14:03 UTC",
            loop: true, state: "running", run_id: "20260930-080000-auto", started_at: "2026-09-30T08:00:00Z",
            created: { total: 1595, pass: 40, page: 2 } },
    alerts: ["Marchand arrêté — GameSeal: extract_failed_p3"],
    logs: [{ ts: "2026-09-30T14:06:00Z", event: "submit_offer", text: "offre 8 : créée", merchant: "GOG", page: 12 },
           { ts: "2026-09-30T14:04:00Z", event: "submit_offer", text: "offre 7 : créée", merchant: "GOG", page: 12 }],
    logs_live: true,
  }),
};
const ANCIENNE = {
  name: "ancienne-vm", label: "groupe A", console_url: "https://51.38.37.254.sslip.io/executor/",
  status: "down", down_reasons: ["délai de 10 s dépassé"], reachable: false, snapshot: null,
  error: "délai de 10 s dépassé",
};
const SECOURS = {
  name: "secours", label: "price check partagé", console_url: "https://169.58.5.63.sslip.io/executor/",
  status: "down", down_reasons: ["service aks-chromium failed"], reachable: true,
  snapshot: snap({ code: { sha: "26f4b60", subject: "feat: maintenance" },
                   alerts: ["Redémarrage requis par Debian (/var/run/reboot-required)"] }),
};

/** La page chargée, avec une horloge et des minuteries qu'on tient à la main. */
async function ouvrir() {
  const clock = { t: T0 };
  class FakeDate extends Date { static now() { return clock.t; } }
  const timers = [];
  const c = await loadConsole(PAGE, {
    Date: FakeDate,
    setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  });
  return Object.assign(c, { clock, timers, every: (ms) => timers.find((x) => x.ms === ms) });
}
const carte = (c, nom) => c.$("#host-" + nom);
const texte = (n) => (n ? n.textContent : "");

const essais = [];
function test(nom, fn) { essais.push([nom, fn]); }

test("UP / DOWN : le badge, le motif du DOWN, la tâche en clair, les alertes", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD, ANCIENNE, SECOURS]));
  const prod = carte(c, "cette-vm");
  assert.ok(prod, "une carte par machine");
  assert.equal(texte(prod.querySelector(".badge")), "UP");
  assert.ok(texte(prod).includes("Balayage groupe A en boucle — passe 3, GOG page 12, saisie depuis 14:03 UTC"),
            "la tâche en clair : " + texte(prod));
  assert.ok(texte(prod).includes("Créées : 1") && texte(prod).includes("page en cours : 2"), "les créées : " + texte(prod));
  assert.ok(texte(prod).includes("boucle lancée le 30/09 à 08:00 UTC"), "l'heure de lancement : " + texte(prod));
  assert.ok(texte(prod.querySelector(".alerts")).includes("Marchand arrêté — GameSeal"), "l'alerte en rouge");
  const lignes = prod.querySelectorAll(".log-line");
  assert.equal(lignes.length, 2);
  assert.ok(texte(lignes[0]).includes("offre 8 : créée") && texte(lignes[0]).includes("GOG p12"),
            "le plus récent d'abord, avec le marchand et la page : " + texte(lignes[0]));
  const anc = carte(c, "ancienne-vm");
  assert.equal(texte(anc.querySelector(".badge")), "DOWN");
  assert.ok(texte(anc.querySelector(".down-reasons")).includes("délai de 10 s dépassé"), "le motif du DOWN");
  const sec = carte(c, "secours");
  assert.equal(texte(sec.querySelector(".badge")), "DOWN", "un service clé arrêté = DOWN");
  assert.ok(texte(sec.querySelector(".down-reasons")).includes("service aks-chromium failed"));
  assert.ok(c.$("#status").textContent.includes("2 DOWN"), c.$("#status").textContent);
});

test("PRICE CHECK : la ligne du moniteur, un service à part de la saisie (Romain, 08/10/2026)", async () => {
  const c = await ouvrir();
  const running = { available: true, age_s: 7, open_reports: 2, modes: {
    "top-games": { running: false, last_end: "2026-10-08T20:31:53+0200", last_alerts: 1, next_at: "2026-10-08T20:34:23+0200" },
    "homepage": { running: true, progress: [407, 440], requested_by: "romain" } } };
  const quiet = { available: true, age_s: 400, open_reports: 1, modes: {
    "top-games": { running: false, last_end: "2026-10-08T20:31:53+0200", last_alerts: 0 } } };
  const check = Object.assign({}, PROD, { snapshot: snap({ price_check: running }) });
  const idle = Object.assign({}, ANCIENNE, { name: "veille", status: "up", down_reasons: [], snapshot: snap({ price_check: quiet }) });
  const none = Object.assign({}, ANCIENNE, { name: "sans", status: "up", down_reasons: [], snapshot: snap({ price_check: { available: false } }) });
  await c.net.release("api/overview", payload([check, idle, none, SECOURS]));
  const t = texte(carte(c, "cette-vm").querySelector(".task-pricecheck"));
  assert.ok(t.includes("Price check : contrôle en cours — homepage page 407 / 440 (demandé par romain)"), t);
  assert.ok(t.includes("dernier passage : tops 20:31 (1 alerte(s))") && t.includes("prochain 20:34") && t.includes("2 reports ouverts"), t);
  const v = texte(carte(c, "veille").querySelector(".task-pricecheck"));
  assert.ok(v.includes("entre deux passages") && v.includes("1 report ouvert") && v.includes("état d'il y a 7 min"), v);
  assert.ok(texte(carte(c, "sans").querySelector(".task-pricecheck")).includes("état du moniteur inconnu"));
  assert.equal(carte(c, "secours").querySelector(".task-pricecheck"), null, "une machine sans price check n'a pas la ligne");
});

test("LIENS : la console de chaque machine, jamais un lien javascript:", async () => {
  const c = await ouvrir();
  const piege = Object.assign({}, ANCIENNE, { name: "piege", console_url: "javascript:alert(1)" });
  await c.net.release("api/overview", payload([PROD, ANCIENNE, piege]));
  const lien = carte(c, "ancienne-vm").querySelector(".console-link");
  assert.equal(lien.getAttribute("href"), "https://51.38.37.254.sslip.io/executor/");
  assert.equal(lien.getAttribute("target"), "_blank");
  assert.equal(carte(c, "cette-vm").querySelector(".console-link").getAttribute("href"), ".");
  assert.equal(carte(c, "piege").querySelector(".console-link"), null, "pas de lien pour une URL douteuse");
});

test("VERSIONS : l'avertissement quand les machines ne sont pas sur le même commit", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD, ANCIENNE, SECOURS]));
  const v = c.$("#ov-version");
  assert.ok(v.textContent.includes("pas sur le même commit"), v.textContent);
  assert.ok(v.textContent.includes("cette-vm 2272e92") && v.textContent.includes("secours 26f4b60"), v.textContent);
  assert.ok(!v.className.includes("hidden"));
  // même commit partout : plus d'avertissement
  c.every(15000).fn();
  const pareil = Object.assign({}, SECOURS, { snapshot: snap() });
  await c.net.release("api/overview", payload([PROD, pareil]));
  assert.ok(c.$("#ov-version").className.includes("hidden"), "caché quand tout est aligné");
});

test("RAFRAÎCHISSEMENT : toutes les 15 s, et « mis à jour il y a N s »", async () => {
  const c = await ouvrir();
  assert.ok(c.every(15000), "un rafraîchissement toutes les 15 s");
  assert.ok(c.every(1000), "l'âge recompté chaque seconde");
  await c.net.release("api/overview", payload([PROD], { age_s: 3 }));
  c.every(1000).fn();
  assert.equal(c.$("#ov-age").textContent, "mis à jour à l'instant", "photo de 3 s");
  c.clock.t += 20000;
  c.every(1000).fn();
  assert.equal(c.$("#ov-age").textContent, "mis à jour il y a 23 s", "l'âge de la PHOTO du serveur");
  c.clock.t += 30000;
  c.every(1000).fn();
  assert.ok(c.$("#ov-age").className.includes("stale"), "au-delà de 45 s, l'âge se voit");
  // le tour suivant relit la route et redessine
  c.every(15000).fn();
  assert.ok(c.net.waiting().includes("api/overview"), "une nouvelle lecture : " + c.net.waiting().join(", "));
  const fini = Object.assign({}, PROD, { snapshot: snap({ task: { type: "aucune", label: "Rien en cours" } }) });
  await c.net.release("api/overview", payload([fini]));
  assert.ok(texte(carte(c, "cette-vm")).includes("Rien en cours"), texte(carte(c, "cette-vm")));
  c.every(1000).fn();
  assert.equal(c.$("#ov-age").textContent, "mis à jour à l'instant");
});

test("PANNE de lecture : la dernière photo reste, l'erreur est dite", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD]));
  c.every(15000).fn();
  await c.net.release("api/overview", { error: { message: "internal" } }, false);
  assert.ok(carte(c, "cette-vm"), "les cartes restent");
  assert.ok(c.$("#status").textContent.includes("lecture impossible"), c.$("#status").textContent);
});

test("ORDRE : une réponse plus ancienne n'écrase jamais la dernière", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD]));
  c.every(15000).fn();                // requête A
  c.every(15000).fn();                // requête B (plus récente)
  const vieux = Object.assign({}, PROD, { snapshot: snap({ task: { type: "aucune", label: "VIEUX" } }) });
  const neuf = Object.assign({}, PROD, { snapshot: snap({ task: { type: "aucune", label: "NEUF" } }) });
  assert.equal(c.net.waiting().length, 2);
  // A répond pendant que B est encore en route : A n'est plus la dernière demandée, elle ne
  // doit rien dessiner (sinon un réseau lent ferait reculer l'écran d'un tour).
  await c.net.release("api/overview", payload([vieux]));     // `release` sert la plus ancienne : A
  assert.ok(!texte(carte(c, "cette-vm")).includes("VIEUX"), "A ignorée");
  await c.net.release("api/overview", payload([neuf]));      // B
  assert.ok(texte(carte(c, "cette-vm")).includes("NEUF"), texte(carte(c, "cette-vm")));
});

test("LECTURE SEULE : seulement des GET relatifs sur api/overview", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD, ANCIENNE]));
  await c.$("#ov-refresh").fire("click");
  await c.net.release("api/overview", payload([PROD]));
  assert.ok(c.net.calls.length >= 2);
  for (const call of c.net.calls) {
    assert.equal(call.method, "GET", "aucune écriture : " + JSON.stringify(call));
    assert.equal(call.url, "api/overview", "chemin relatif (nginx sert sous /executor/) : " + call.url);
  }
});

test("CONFIGURATION : seule cette machine, et où déclarer les autres", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD], { config: { file: "state/overview_hosts.json", configured: false } }));
  const note = c.$("#ov-config");
  assert.ok(note.textContent.includes("state/overview_hosts.json"), note.textContent);
  assert.ok(!note.className.includes("hidden"));
});

test("FORMES : une carte mal formée n'emporte ni les autres ni la page (revue adverse du 30/09)", async () => {
  const c = await ouvrir();
  await c.net.release("api/overview", payload([PROD]));
  c.every(15000).fn();
  const neuf = Object.assign({}, PROD, { snapshot: snap({ task: { type: "aucune", label: "NEUF" } }) });
  // une machine sur un autre commit : alertes / journal / motifs qui ne sont pas des listes
  const tordue = {
    name: "tordue", status: "down", down_reasons: "pas une liste", reachable: true,
    snapshot: snap({ task: { type: "autre", label: "TACHE-X" }, alerts: "pas une liste",
                     logs: { a: 1 }, code: { sha: "abc1234" } }),
  };
  await c.net.release("api/overview", payload([neuf, tordue, null]));
  assert.ok(texte(carte(c, "cette-vm")).includes("NEUF"), "la page n'est pas figée : " + texte(carte(c, "cette-vm")));
  const t = carte(c, "tordue");
  assert.ok(t, "la carte mal formée est là");
  assert.equal(texte(t.querySelector(".badge")), "DOWN");
  assert.ok(texte(t).includes("TACHE-X"), "sa tâche reste lisible : " + texte(t));
  const illisible = carte(c, "?");
  assert.ok(illisible && texte(illisible).includes("carte illisible"), "une entrée illisible le dit, à sa place");
  assert.ok(c.$("#status").textContent.includes("3 machine(s)"), c.$("#status").textContent);
});

test("INTERROMPU : un balayage tué n'est jamais « fini le … »", async () => {
  const c = await ouvrir();
  const tue = Object.assign({}, PROD, { snapshot: snap({
    task: { type: "aucune", label: "Rien en cours — le dernier balayage s'est interrompu sans fin propre",
            last_sweep: { run_id: "20260930-080000-auto", loop: true, created: 622, interrupted: true,
                          last_seen_at: "2026-09-30T12:00:00Z" } },
    alerts: ["Boucle 20260930-080000-auto interrompue sans fin propre (processus disparu)"] }) });
  await c.net.release("api/overview", payload([tue]));
  const txt = texte(carte(c, "cette-vm"));
  assert.ok(txt.includes("INTERROMPU sans fin propre — dernière trace le 30/09 à 12:00 UTC"), txt);
  assert.ok(txt.includes("622 créée(s)"), txt);
  assert.ok(!txt.includes("fini le"), "jamais « fini le » : " + txt);
});

let rouges = 0;
for (const [nom, fn] of essais) {
  try { await fn(); console.log("ok   -", nom); }
  catch (e) { rouges++; console.log("FAIL -", nom, "\n      ", e.message); }
}
if (!rouges) console.log("tout passe");
process.exit(rouges ? 1 : 0);
