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

let rouges = 0;
for (const [nom, fn] of essais) {
  try { await fn(); console.log("ok   -", nom); }
  catch (e) { rouges++; console.log("FAIL -", nom, "\n      ", e.message); }
}
process.exit(rouges ? 1 : 0);
