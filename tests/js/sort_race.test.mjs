// LIVE simulation of Romain's repro — the one the structural tests cannot perform.
// node dependency approved by Romain on 2026-09-17 ("Installe node pour les tests JS").
//
// His scenario, verbatim:
//   1. le chargement de B démarre ; A reste affiché ;
//   2. l'utilisateur ouvre les offres de A ;
//   3. B termine son chargement ; la fenêtre reste sur A ;
//   4. GO envoie B avec l'empreinte de B.
//
// Here the network answers are RELEASED BY HAND, so step 3 really lands between steps 2
// and 4. The assertion is on the request that leaves the page: which run, which digest.

import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadConsole } from "./load_console.mjs";
import { byText, tick } from "./dom_stub.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const SORT_JS = process.env.SORT_JS || path.join(ROOT, "src", "admin", "static", "sort.js");

const RUNS = { runs: [{ run_id: "scan-A", counts: { routed: 2 } },
                      { run_id: "scan-B", counts: { routed: 2 } }], busy: null };

const plan = (tag) => ({
  plan_digest: `digest-${tag}`,
  counts: { total: 10, routed: 3, target_lists: 1, unrouted_skips: 0, candidates: 0 },
  coverage: { pages_fetched: 1, truncated: false },
  by_list: { 8: { count: 3, label: "Blacklist",
                  offers: [{ store_id: "12", name: `offre ${tag}`, url: `https://m.test/${tag}`, reason: "x" }] } },
  moved_tally: {},
});

let failures = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  ok   ${name}`); }
  catch (e) { failures++; console.log(`  FAIL ${name}\n       ${e.message.split("\n").join("\n       ")}`); }
}

// Brings the page to: plan A painted, load of B in flight, modal open on A.
async function upToTheOpenModal() {
  const app = await loadConsole(SORT_JS);
  await app.net.release("api/sort/runs", RUNS);
  await app.net.release("runs/scan-A/sort", plan("A"));

  // 1. the operator switches the picker to B — its answer is NOT released yet
  await app.$("#run-picker").fire("change", { target: { value: "scan-B" } });
  await tick();
  assert.ok(app.net.waiting().some((u) => u.includes("scan-B")), "le chargement de B doit être en vol");

  // 2. while A is still on screen, the operator opens A's offers
  const open = byText(app.$("#board"), "Voir les offres");
  assert.ok(open, "le bouton d'ouverture de la carte est introuvable");
  await open.fire("click");
  assert.equal(app.$("#offers-modal").open, true, "la fenêtre doit être ouverte");

  // 3. NOW B finishes loading, behind the open modal
  await app.net.release("runs/scan-B/sort", plan("B"));
  return app;
}

async function typeGoAndFire(app) {
  const go = app.$("#modal-actions").querySelector(".go-in");
  const canary = app.$("#modal-actions").querySelector(".primary");
  assert.ok(go && canary, "le champ GO ou le bouton canary est introuvable");
  go.value = "GO";
  await go.fire("input");
  // NE PAS attendre le clic : runAction reste suspendu sur le réseau tant que nous n'avons
  // pas libéré sa réponse — l'attendre ici bloquerait le test sur lui-même.
  const running = canary.fire("click");
  // Renvoyer cette promesse ferait attendre l'appelant SUR ELLE (runAction reste suspendu
  // tant que le POST n'est pas libéré) : on l'absorbe ici.
  running.catch(() => {});
  await tick();
  await app.net.release("submit/status?offset=0", { offset: 7 });
  await tick();
}

await test("le GO part sur le scan OUVERT, pas sur celui chargé entre-temps", async () => {
  const app = await upToTheOpenModal();
  await typeGoAndFire(app);
  const move = app.net.calls.find((c) => c.url.includes("/sort/move"));
  assert.ok(move, `aucun POST de déplacement.\nappels: ${app.net.calls.map((c) => c.url).join("\n  ")}`);
  assert.ok(move.url.includes("/runs/scan-A/"),
    `le déplacement part sur ${move.url} — il devait porter sur scan-A (les offres affichées)`);
  assert.equal(move.body.plan_digest, "digest-A",
    "l'empreinte envoyée doit être celle du plan que l'opérateur a examiné");
});

await test("la lecture de l'offset du journal vise elle aussi le scan ouvert", async () => {
  const app = await upToTheOpenModal();
  await typeGoAndFire(app);
  const status = app.net.calls.find((c) => c.url.includes("submit/status?offset=0"));
  assert.ok(status, "aucune lecture d'offset");
  assert.ok(status.url.includes("/runs/scan-A/"), `offset lu sur ${status.url}`);
});

await test("le suivi sonde le scan ouvert", async () => {
  const app = await upToTheOpenModal();
  await typeGoAndFire(app);
  await app.net.release("/sort/move", { ok: true });
  await tick();
  const poll = app.net.calls.filter((c) => c.url.includes("submit/status?offset=") && !c.url.includes("offset=0"));
  assert.ok(poll.length, "le suivi n'a pas démarré");
  for (const p of poll) assert.ok(p.url.includes("/runs/scan-A/"), `suivi sur ${p.url}`);
});

await test("les commandes copiables nomment le scan ouvert", async () => {
  const app = await upToTheOpenModal();
  const txt = app.$("#modal-cmds").textContent;
  assert.ok(txt.includes("runs/scan-A"), `commandes affichées: ${txt.slice(0, 200)}`);
  assert.ok(!txt.includes("runs/scan-B"), "une commande nomme le scan qui vient d'être chargé");
});

await test("sans plan ouvert, un GO n'envoie rien", async () => {
  const app = await upToTheOpenModal();
  const go = app.$("#modal-actions").querySelector(".go-in");
  const canary = app.$("#modal-actions").querySelector(".primary");
  await app.$("#modal-close").fire("click");          // ferme la fenêtre → identité libérée
  go.value = "GO";
  await go.fire("input");
  // Sur le code CORRIGÉ, runAction refuse tout de suite. Sur une version ancienne il
  // partirait quand même et resterait suspendu : on absorbe, sinon le test se bloque sur
  // le défaut qu'il mesure.
  canary.fire("click").catch(() => {});
  await tick();
  assert.ok(!app.net.calls.some((c) => c.url.includes("/sort/move")),
    "un GO après fermeture ne doit rien envoyer");
});

await test("un tick de sondage périmé ne touche pas le run suivant", async () => {
  // Le 3e défaut du jour : `tick` est asynchrone, donc clearInterval ne peut rien contre une
  // requête déjà partie. Un tick d'un run TERMINÉ reprenait la main sur l'état du run SUIVANT.
  // Observable sans rien exposer : finishStatus() appelle refreshBusy() (GET api/sort/runs) et
  // loadPlan() (GET runs/<id>/sort). S'ils apparaissent, le tick périmé a agi.
  const app = await upToTheOpenModal();
  await typeGoAndFire(app);
  await app.net.release("/sort/move", { ok: true });
  await tick();
  assert.ok(app.net.waiting().some((u) => u.includes("submit/status?offset=7")),
    "le 1er tick du sondage doit être en vol");

  // la fenêtre est fermée puis une NOUVELLE action est lancée : un second sondage démarre
  await app.$("#modal-close").fire("click");
  const open = byText(app.$("#board"), "Voir les offres");
  await open.fire("click");
  await typeGoAndFire(app);
  await app.net.release("/sort/move", { ok: true });
  await tick();

  const before = app.net.calls.length;
  const busyBefore = app.net.calls.filter((c) => c.url.includes("api/sort/runs")).length;
  const planBefore = app.net.calls.filter((c) => /runs\/scan-[AB]\/sort$/.test(c.url)).length;

  // le tick PÉRIMÉ répond enfin, et annonce un run terminé
  await app.net.release("submit/status?offset=7",
    { state: "done", exit_code: 0, events: [], stdout_tail: "", offset: 99 });
  await tick();

  const busyAfter = app.net.calls.filter((c) => c.url.includes("api/sort/runs")).length;
  const planAfter = app.net.calls.filter((c) => /runs\/scan-[AB]\/sort$/.test(c.url)).length;
  assert.equal(busyAfter, busyBefore,
    "le tick périmé a déclenché refreshBusy — il a donc exécuté finishStatus");
  assert.equal(planAfter, planBefore,
    "le tick périmé a rechargé le plan — il a donc exécuté finishStatus");
  assert.ok(app.net.calls.length >= before, "aucun appel ne doit disparaître");
});

console.log(failures ? `\n${failures} échec(s)` : "\ntout passe");
process.exit(failures ? 1 : 0);
