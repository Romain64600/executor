// La console de saisie auto, EXÉCUTÉE — la page EN COURS (Romain, 2026-09-26 : « 4. Go »).
//
// Le 25/09, l'écran est resté une heure sur « 0 offres créées · 0 marchand » pendant que
// Gamesplanet FR saisissait sa page 3 : le recap n'était réécrit qu'à la FIN d'une page. Le
// balayage pose désormais `current` (page, run, étape) dans le recap du marchand ; la console
// l'affiche et, pendant la SAISIE, lit créées / échecs sur la route de run de la page
// (`api/runs/<run>` → created_count / failed_count, servie par l'admin tel qu'il tourne).

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole } from "./load_console.mjs";
import { tick } from "./dom_stub.mjs";

const ICI = path.dirname(fileURLToPath(import.meta.url));
// `AUTO_JS` rejoue le harnais contre une console VOLONTAIREMENT cassée (voir le test Python).
const AUTO = process.env.AUTO_JS
  || path.join(ICI, "..", "..", "src", "admin", "static", "auto.js");

const SWEEP = "20260926-100000-auto";
const PAGE = SWEEP + "-gamesplanet-fr-s55-p3";
const MARCHANDS = { merchants: [{ name: "Gamesplanet FR", store_id: "55" }], groups: [] };
const OCCUPE = { busy: { kind: "data_entry_auto", run_id: SWEEP }, runs: [] };

function recap(current, extra = {}) {
  return {
    run_id: SWEEP,
    recap: Object.assign({
      run_id: SWEEP, total_created: 0, halted: null,
      targets: [{ merchant: "Gamesplanet FR", store_id: "55",
                  recap: { pages: [], total_created: 0, current } }],
    }, extra),
  };
}

/** Un sweep déjà en cours au chargement : la console l'adopte et fait UN tour de sondage. */
async function adopter(rec) {
  const c = await loadConsole(AUTO);
  await c.net.release("api/data-entry/merchants", MARCHANDS);
  await c.net.release("api/sort/runs", OCCUPE);          // resumeIfActive
  await c.net.release("api/sort/runs", OCCUPE);          // premier tick
  await c.net.release("data-entry/recap?run=" + SWEEP, rec);
  await tick();
  return c;
}
const ecran = (c) => c.$("#recap-summary").textContent + "\n" + c.$("#recap-pages").textContent;

const essais = [];
function test(nom, fn) { essais.push([nom, fn]); }

test("SAISIE : la page en cours et ses compteurs, lus dans le journal de la page", async () => {
  const c = await adopter(recap({ page: 3, run: PAGE, stage: "submit", candidates: 52,
                                  approved: 52, since: "2026-09-26T10:00:00Z",
                                  stage_at: "2026-09-26T10:03:00Z" }));
  assert.ok(c.net.waiting().some((u) => u.includes("api/runs/" + PAGE)),
            "pendant la saisie, les compteurs de CETTE page doivent être demandés : "
            + c.net.waiting().join(", "));
  await c.net.release("api/runs/" + PAGE, { created_count: 39, failed_count: 1 });
  await tick();
  const texte = ecran(c);
  assert.ok(c.$("#recap-summary").textContent.includes("en cours : Gamesplanet FR · page 3"),
            "le résumé doit nommer le marchand et la page en cours : " + texte);
  assert.ok(texte.includes("39 créée(s) sur 52"), "les créées sur les candidats : " + texte);
  assert.ok(texte.includes("1 échec(s)"), "les échecs : " + texte);
  assert.ok(c.$("#recap-pages").textContent.includes("page 3 — en cours"),
            "un bloc « en cours » sous le marchand : " + texte);
  assert.ok(texte.includes("depuis 10:03 UTC"), "l'heure de l'étape : " + texte);
});

test("BOUCLE : le bandeau dit la passe, les passes finies et la prochaine (Romain, 2026-09-27)", async () => {
  const dans4min = new Date(Date.now() + 4 * 60000).toISOString().replace(/\.\d{3}Z$/, "Z");
  const rec = Object.assign(recap(null, { finished_at: "2026-09-26T12:00:00Z", total_created: 7 }), {
    pass_run_id: SWEEP + "-pass2",
    loop: { state: "pause", pass: 2, pause_s: 300, next_pass_at: dans4min,
            passes: [{ pass: 1, run_id: SWEEP, finished_at: "t", total_created: 1343 },
                     { pass: 2, run_id: SWEEP + "-pass2", finished_at: "t", total_created: 7 }] },
  });
  const c = await adopter(rec);
  const bandeau = c.$("#loop-banner").textContent;
  assert.ok(bandeau.includes("Boucle : passe 2 finie"), "la passe : " + bandeau);
  assert.ok(bandeau.includes("2 passe(s) finie(s) (1343 + 7 créées)"), "les passes finies et leurs créations : " + bandeau);
  assert.ok(bandeau.includes("prochaine passe (n° 3) dans 4 min"), "la prochaine passe : " + bandeau);
  assert.ok(c.$("#recap-run").textContent.includes(SWEEP + "-pass2"), "le recap affiché est celui de la passe courante");
  assert.ok(c.$("#stop-btn").has("click"), "« Arrêter » reste là, pause comprise");
  assert.equal(c.$("#stop-btn").disabled, false, "…et actif");
});

test("BOUCLE arrêtée : le motif s'affiche et clôt le suivi", async () => {
  const rec = Object.assign(recap(null, { finished_at: "2026-09-26T12:00:00Z", total_created: 0 }), {
    loop: { state: "stopped", pass: 3, pause_s: 300, stopped_reason: "session_expired",
            stopped_label: "session expirée — transfert de cookies requis",
            passes: [{ pass: 1, run_id: SWEEP, finished_at: "t", total_created: 12 },
                     { pass: 2, run_id: SWEEP + "-pass2", finished_at: "t", total_created: 3 },
                     { pass: 3, run_id: SWEEP + "-pass3", finished_at: "t", total_created: 0 }] },
  });
  const c = await loadConsole(AUTO);
  await c.net.release("api/data-entry/merchants", MARCHANDS);
  await c.net.release("api/sort/runs", OCCUPE);          // resumeIfActive : un run adopté…
  await c.net.release("api/sort/runs", { busy: null, runs: [] });   // …qui vient de finir
  await c.net.release("data-entry/recap?run=" + SWEEP, rec);
  await tick();
  const bandeau = c.$("#loop-banner").textContent;
  assert.ok(bandeau.includes("Boucle arrêtée après 3 passe(s) finie(s) (12 + 3 + 0 créées) : session expirée"), bandeau);
  assert.ok(c.$("#loop-banner").className.includes("stopped"), "le bandeau d'arrêt est marqué");
  assert.ok(c.$("#status").textContent.includes("Boucle arrêtée"), "le statut final dit l'arrêt de la boucle : " + c.$("#status").textContent);
});

test("MATCHING : l'étape s'affiche, sans aller chercher de compteurs", async () => {
  const c = await adopter(recap({ page: 5, run: SWEEP + "-x-s1-p5", stage: "match", offers: 100,
                                  since: "2026-09-26T10:00:00Z", stage_at: "2026-09-26T10:01:00Z" }));
  assert.ok(!c.net.waiting().some((u) => u.includes("api/runs/")),
            "hors saisie, aucun compteur à lire : " + c.net.waiting().join(", "));
  assert.ok(ecran(c).includes("matching de 100 offres"), ecran(c));
});

test("compteurs indisponibles : l'étape reste affichée, sans chiffres inventés", async () => {
  const c = await adopter(recap({ page: 3, run: PAGE, stage: "submit", candidates: 52,
                                  stage_at: "2026-09-26T10:03:00Z" }));
  await c.net.release("api/runs/" + PAGE, { error: { message: "boom" } }, false);
  await tick();
  const texte = ecran(c);
  assert.ok(texte.includes("saisie de 52 candidat(s)"), texte);
  assert.ok(!texte.includes("créée(s) sur"), "aucun compteur ne doit s'afficher : " + texte);
});

test("PAUSE après une erreur passagère : sa durée et son motif", async () => {
  const c = await adopter(recap({ page: 3, run: PAGE, stage: "pause", wait_s: 120,
                                  reason: "CdpTimeoutError", stage_at: "2026-09-26T10:03:00Z" }));
  assert.ok(ecran(c).includes("pause de 2 min après une erreur passagère (CdpTimeoutError)"), ecran(c));
});

test("un marchand qui vient de démarrer se voit AVANT sa première page", async () => {
  const c = await adopter({ run_id: SWEEP, recap: { run_id: SWEEP, total_created: 0, halted: null,
    targets: [{ merchant: "Gamesplanet FR", store_id: "55", recap: null }] } });
  const texte = ecran(c);
  assert.ok(texte.includes("Gamesplanet FR (store 55)"), texte);
  assert.ok(texte.includes("démarrage"), texte);
  assert.ok(c.$("#recap-summary").textContent.includes("1"), "un marchand, pas zéro");
});

test("un recap FINI ne montre rien « en cours », même s'il traîne un current", async () => {
  const c = await loadConsole(AUTO);
  await c.net.release("api/data-entry/merchants", MARCHANDS);
  await c.net.release("api/sort/runs", { busy: null, runs: [] });   // rien en cours
  await c.net.release("api/data-entry/recap", recap(
    { page: 3, run: PAGE, stage: "submit", candidates: 52 }));        // recap d'un crash
  await tick();
  assert.ok(!ecran(c).includes("en cours"), "un recap abandonné ne doit pas mentir : " + ecran(c));
  assert.ok(!c.net.waiting().some((u) => u.includes("api/runs/")), "aucun compteur demandé");
});

// ---- les HEURES (Romain, 2026-09-29 : « depuis l'admin, j'aimerais savoir quand le sweep a
// commencé ») : le lancement, la passe en boucle, chaque marchand, chaque page. ----
const il_y_a = (min) => new Date(Date.now() - min * 60000).toISOString().replace(/\.\d{3}Z$/, "Z");
const jh = (ts) => ts.slice(8, 10) + "/" + ts.slice(5, 7) + " à " + ts.slice(11, 16) + " UTC";

test("HEURES : le sweep dit quand il a commencé, et depuis combien de temps", async () => {
  const debut = il_y_a(102);
  const c = await adopter(recap({ page: 3, run: PAGE, stage: "match", offers: 100,
                                  since: "2026-09-29T10:00:00Z", stage_at: "2026-09-29T10:01:00Z" },
                                { started_at: debut }));
  const ligne = c.$("#recap-started").textContent;
  assert.ok(ligne.includes("Sweep commencé le " + jh(debut)), "le début, jour compris : " + ligne);
  assert.ok(/en cours depuis 1 h 4[12]/.test(ligne), "le temps écoulé : " + ligne);
  assert.ok(!c.$("#recap-started").className.includes("hidden"), "la ligne est visible");
  assert.ok(c.$("#recap-pages").textContent.includes("commencée à 10:00 UTC"),
            "la page en cours dit son début : " + ecran(c));
});

test("HEURES : chaque marchand et chaque page finie portent leur début et leur fin", async () => {
  const rec = { run_id: SWEEP, recap: {
    run_id: SWEEP, started_at: "2026-09-29T14:03:00Z", total_created: 5, halted: null,
    targets: [{ merchant: "Gamesplanet FR", store_id: "55",
                started_at: "2026-09-29T14:03:00Z", finished_at: "2026-09-29T15:45:00Z",
                recap: { total_created: 5, current: null, pages: [
                  { page: 2, run: "a", offers: 100, created: 5,
                    started_at: "2026-09-29T14:03:10Z", finished_at: "2026-09-29T14:20:40Z" },
                  { page: 1, run: "b", offers: 40, created: 0,
                    started_at: "2026-09-29T23:55:00Z", finished_at: "2026-09-30T00:10:00Z" }] } },
              { merchant: "K4G", store_id: "7", started_at: "2026-09-29T15:45:05Z", recap: null }],
  } };
  const c = await adopter(rec);
  const pages = c.$("#recap-pages").textContent;
  assert.ok(pages.includes("commencé le 29/09 à 14:03 UTC · fini le 29/09 à 15:45 UTC (1 h 42)"),
            "le marchand fini : " + pages);
  assert.ok(pages.includes("K4G (store 7) — 0 créées · commencé le 29/09 à 15:45 UTC"),
            "le marchand en cours, sans fin inventée : " + pages);
  assert.ok(pages.includes("14:03 → 14:20 UTC"), "la page finie : " + pages);
  assert.ok(pages.includes("29/09 à 23:55 UTC → 30/09 à 00:10 UTC"), "une page qui passe minuit : " + pages);
});

test("HEURES en BOUCLE : le lancement de la boucle ET le début de la passe courante", async () => {
  const debutBoucle = il_y_a(26 * 60);
  const rec = Object.assign(recap(null, { started_at: "2026-09-28T03:10:00Z" }), {
    pass_run_id: SWEEP + "-pass2",
    loop: { state: "running", pass: 2, pause_s: 300, started_at: debutBoucle,
            passes: [{ pass: 1, run_id: SWEEP, finished_at: "t", total_created: 383 }] },
  });
  const c = await adopter(rec);
  const ligne = c.$("#recap-started").textContent;
  assert.ok(ligne.includes("Boucle lancée le " + jh(debutBoucle)), ligne);
  assert.ok(ligne.includes("passe 2 commencée le 28/09 à 03:10 UTC"), ligne);
  assert.ok(/en cours depuis 2[56] h/.test(ligne), "compté depuis le lancement de la boucle : " + ligne);
});

test("HEURES d'un sweep FINI : la fin et la durée, rien « en cours »", async () => {
  const c = await loadConsole(AUTO);
  await c.net.release("api/data-entry/merchants", MARCHANDS);
  await c.net.release("api/sort/runs", { busy: null, runs: [] });
  await c.net.release("api/data-entry/recap", recap(null, {
    started_at: "2026-09-29T08:00:00Z", finished_at: "2026-09-29T13:12:00Z" }));
  await tick();
  const ligne = c.$("#recap-started").textContent;
  assert.ok(ligne.includes("Sweep commencé le 29/09 à 08:00 UTC · fini le 29/09 à 13:12 UTC (5 h 12)"), ligne);
  assert.ok(!ligne.includes("en cours"), ligne);
});

test("HEURES absentes (recap d'avant le 29/09) : rien d'inventé", async () => {
  const c = await adopter(recap(null));
  assert.equal(c.$("#recap-started").textContent, "", "pas de ligne de début sans horodatage");
  assert.ok(c.$("#recap-started").className.includes("hidden"), "la ligne est cachée");
  assert.ok(!ecran(c).includes("commencé"), ecran(c));
});

let rouges = 0;
for (const [nom, fn] of essais) {
  try { await fn(); console.log("ok   -", nom); }
  catch (e) { rouges++; console.log("FAIL -", nom, "\n      ", e.message); }
}
process.exit(rouges ? 1 : 0);
