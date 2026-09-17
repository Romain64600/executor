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
import { byText, byTextAll, tick } from "./dom_stub.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const SORT_JS = process.env.SORT_JS || path.join(ROOT, "src", "admin", "static", "sort.js");

const RUNS = { runs: [{ run_id: "scan-A", counts: { routed: 2 } },
                      { run_id: "scan-B", counts: { routed: 2 } }], busy: null };

const plan = (tag) => ({
  plan_digest: `digest-${tag}`,
  counts: { total: 10, routed: 3, target_lists: 1, unrouted_skips: 0, candidates: 0 },
  coverage: { pages_fetched: 1, truncated: false },
  by_list: {
    8: { count: 3, label: "Blacklist",
         offers: [{ store_id: "12", name: `offre ${tag} liste 8`, url: `https://m.test/${tag}/8`, reason: "x" }] },
    16: { count: 2, label: "Softwares",
          offers: [{ store_id: "12", name: `offre ${tag} liste 16`, url: `https://m.test/${tag}/16`, reason: "y" }] },
  },
  moved_tally: {},
});

let failures = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  ok   ${name}`); }
  catch (e) { failures++; console.log(`  FAIL ${name}\n       ${e.message.split("\n").join("\n       ")}`); }
}

// Brings the page to: plan A painted, load of B in flight, modal open on A.
async function upToTheOpenModal(overrides) {
  const app = await loadConsole(SORT_JS, overrides);
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

// Le plan A seul, affiché, sans aucun autre chargement en vol : le seul changement possible
// est alors l'OUVERTURE d'une autre fenêtre du MÊME scan — le cas que le garde par scan ne
// pouvait pas voir.
async function planASeul(overrides) {
  const app = await loadConsole(SORT_JS, overrides);
  await app.net.release("api/sort/runs", RUNS);
  await app.net.release("runs/scan-A/sort", plan("A"));
  return app;
}

async function ouvrir(app, n) {
  const cartes = byTextAll(app.$("#board"), "Voir les offres");
  assert.equal(cartes.length, 2, "le plan de test doit offrir deux listes");
  await cartes[n].fire("click");
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

await test("sans plan ouvert, un GO n'émet AUCUNE requête", async () => {
  // Romain, P2 : la version précédente n'affirmait que l'absence de POST, sans libérer la
  // lecture d'offset qui le précède — elle restait donc verte même sans le garde, puisque le
  // POST n'arrive qu'APRÈS cette lecture. On compte désormais TOUTES les requêtes.
  const app = await upToTheOpenModal();
  const go = app.$("#modal-actions").querySelector(".go-in");
  const canary = app.$("#modal-actions").querySelector(".primary");
  await app.$("#modal-close").fire("click");          // ferme la fenêtre → identité libérée
  const before = app.net.calls.length;
  go.value = "GO";
  await go.fire("input");
  // Sur le code CORRIGÉ, runAction refuse tout de suite. Sur une version ancienne il
  // partirait quand même et resterait suspendu : on absorbe, sinon le test se bloque sur
  // le défaut qu'il mesure.
  canary.fire("click").catch(() => {});
  await tick();
  const emises = app.net.calls.slice(before).map((c) => `${c.method} ${c.url}`);
  assert.deepEqual(emises, [],
    `un GO après fermeture ne doit émettre aucune requête, même pas la lecture d'offset`);
});

await test("une réponse de lancement tardive ne peint pas dans une autre fenêtre", async () => {
  // Romain, P2 : GO sur A → fermeture → la réponse du POST de A arrive. Le jeton protège les
  // requêtes de suivi, pas le LANCEMENT qui les précède : startPoll(A) redémarrait et
  // affichait « terminé (exit 0) » dans le panneau devenu celui d'une autre fenêtre.
  const app = await upToTheOpenModal();
  const go = app.$("#modal-actions").querySelector(".go-in");
  const canary = app.$("#modal-actions").querySelector(".primary");
  go.value = "GO";
  await go.fire("input");
  canary.fire("click").catch(() => {});
  await tick();
  await app.net.release("submit/status?offset=0", { offset: 3 });
  await tick();

  await app.$("#modal-close").fire("click");     // la fenêtre est fermée pendant l'envoi
  const before = app.net.calls.length;
  await app.net.release("/sort/move", { ok: true });   // la réponse du POST arrive enfin
  await tick();

  const suivi = app.net.calls.slice(before).filter((c) => c.url.includes("submit/status"));
  assert.deepEqual(suivi.map((c) => c.url), [],
    "aucun suivi ne doit démarrer : son panneau n'existe plus");
  assert.ok(!app.$("#modal-status").textContent.includes("terminé"),
    "le panneau ne doit pas recevoir la conclusion d'une action dont la fenêtre est fermée");
});

await test("la boucle du scan frais suit SON scan et retire sa génération", async () => {
  const app = await upToTheOpenModal({ confirm: () => true });
  app.$("#new-scan").fire("click").catch(() => {});
  await tick();
  await app.net.release("api/sort/scan", { run_id: "scan-frais-1" });
  await tick();
  const t1 = app.net.calls.filter((c) => c.url.includes("scan-frais-1/submit/status"));
  assert.ok(t1.length, `le sondage du scan doit viser son propre run.\n${app.net.calls.map((c) => c.url).join("\n")}`);

  // le tick est en vol ; un SECOND scan démarre
  app.$("#new-scan").fire("click").catch(() => {});
  await tick();
  await app.net.release("api/sort/scan", { run_id: "scan-frais-2" });
  await tick();
  assert.ok(app.net.calls.some((c) => c.url.includes("scan-frais-2/submit/status")),
    "le second scan doit sonder son propre run");

  // le tick PÉRIMÉ du premier répond enfin, en annonçant la fin : il ne doit rien déclencher
  const before = app.net.calls.filter((c) => c.url.includes("api/sort/runs")).length;
  await app.net.release("scan-frais-1/submit/status", { state: "done", events: [], busy: null });
  await tick();
  const after = app.net.calls.filter((c) => c.url.includes("api/sort/runs")).length;
  assert.equal(after, before,
    "le tick périmé a rechargé la liste des scans — il a donc conclu à la place du scan en cours");
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

await test("changer de LISTE dans le même scan retire aussi l'action précédente", async () => {
  // Romain, 3e passe : le garde ne comparait que le SCAN, donc passer de la liste 8 à la
  // liste 16 du MÊME scan le laissait passer et le résultat de la 8 atterrissait dans la 16.
  // Aucun autre plan n'est chargé ici : c'est bien l'OUVERTURE qui change, pas le scan.
  const app = await planASeul();
  await ouvrir(app, 0);
  await typeGoAndFire(app);

  await app.$("#modal-close").fire("click");
  await ouvrir(app, 1);
  assert.ok(app.$("#modal-title").textContent.includes("liste 16"), app.$("#modal-title").textContent);

  const before = app.net.calls.length;
  await app.net.release("/sort/move", { ok: true });   // la réponse de la liste 8 arrive
  await tick();

  assert.deepEqual(app.net.calls.slice(before).filter((c) => c.url.includes("submit/status")).map((c) => c.url), [],
    "aucun suivi ne doit démarrer dans la fenêtre d'une autre liste");
  assert.ok(!app.$("#modal-status").textContent.includes("liste 8"),
    `la fenêtre de la liste 16 a reçu le lancement de la 8 : ${app.$("#modal-status").textContent}`);
});

await test("un REFUS tardif ne peint pas dans une autre fenêtre ni ne réactive ses boutons", async () => {
  // Romain, 3e passe : « le catch intervient avant la vérification ». Un refus tardif de la
  // liste 8 s'affichait dans la 16 et réactivait SES boutons, en plein lancement.
  const app = await planASeul();
  await ouvrir(app, 0);
  await typeGoAndFire(app);

  await app.$("#modal-close").fire("click");
  await ouvrir(app, 1);
  const boutons = app.$("#modal-actions").querySelectorAll("button,input");
  boutons.forEach((b) => (b.disabled = true));         // la 16 est elle-même en cours de lancement

  await app.net.release("/sort/move", { error: { message: "plan_changed" } }, false);
  await tick();

  assert.ok(!app.$("#modal-status").textContent.includes("refusé"),
    `le refus de la liste 8 a été peint dans la fenêtre de la 16 : ${app.$("#modal-status").textContent}`);
  assert.ok(boutons.every((b) => b.disabled),
    "le refus d'une autre fenêtre a réactivé les boutons de celle-ci, en plein lancement");
});

await test("la lecture d'offset qui revient trop tard ne peint pas non plus", async () => {
  // Troisième attente du même chemin : si la fenêtre est remplacée pendant la lecture de
  // l'offset, écrire OFFSET et ouvrir le panneau viserait la NOUVELLE fenêtre.
  const app = await planASeul();
  await ouvrir(app, 0);
  const go = app.$("#modal-actions").querySelector(".go-in");
  const canary = app.$("#modal-actions").querySelector(".primary");
  go.value = "GO";
  await go.fire("input");
  canary.fire("click").catch(() => {});
  await tick();

  await app.$("#modal-close").fire("click");           // la fenêtre part AVANT la réponse
  await ouvrir(app, 1);
  const before = app.net.calls.length;
  await app.net.release("submit/status?offset=0", { offset: 3 });
  await tick();

  assert.ok(!app.$("#modal-status").textContent.includes("liste 8"),
    `le panneau de la liste 16 a reçu le lancement de la 8 : ${app.$("#modal-status").textContent}`);
  assert.deepEqual(app.net.calls.slice(before).map((c) => c.url), [],
    "aucune requête ne doit partir pour une fenêtre qui n'existe plus");
});

await test("la fermeture par Échap nettoie comme le bouton ✕", async () => {
  // Romain, 4e passe : un <dialog> se ferme nativement sur Échap, sans passer par nos
  // gestionnaires. La génération restait vivante et le suivi tournait encore, si bien qu'un
  // POST partait après la fermeture — contrairement au ✕.
  const app = await planASeul();
  await ouvrir(app, 0);
  const go = app.$("#modal-actions").querySelector(".go-in");
  const canary = app.$("#modal-actions").querySelector(".primary");
  go.value = "GO";
  await go.fire("input");
  canary.fire("click").catch(() => {});
  await tick();
  assert.ok(app.net.waiting().some((u) => u.includes("submit/status?offset=0")),
    "la lecture d'offset doit être en vol");

  await app.$("#offers-modal").pressEscape();         // Échap, pas le bouton
  assert.equal(app.$("#offers-modal").open, false);

  const before = app.net.calls.length;
  await app.net.release("submit/status?offset=0", { offset: 3 });
  await tick();

  assert.deepEqual(app.net.calls.slice(before).map((c) => `${c.method} ${c.url}`), [],
    "après Échap, plus aucune requête ne doit partir — surtout pas le POST de déplacement");
});

await test("Échap pendant le suivi arrête aussi le sondage", async () => {
  const app = await planASeul();
  await ouvrir(app, 0);
  await typeGoAndFire(app);
  await app.net.release("/sort/move", { ok: true });
  await tick();
  assert.ok(app.net.waiting().some((u) => u.includes("submit/status?offset=7")),
    `le suivi doit être en vol — en attente: ${app.net.waiting().join(", ")}`);

  await app.$("#offers-modal").pressEscape();
  const before = app.net.calls.length;
  await app.net.release("submit/status?offset=7",
    { state: "done", exit_code: 0, events: [], stdout_tail: "", offset: 9 });
  await tick();

  assert.equal(app.net.calls.filter((c) => c.url.includes("api/sort/runs")).length,
    app.net.calls.slice(0, before).filter((c) => c.url.includes("api/sort/runs")).length,
    "le tick retenu a conclu malgré Échap — finishStatus a rechargé la page");
});

console.log(failures ? `\n${failures} échec(s)` : "\ntout passe");
process.exit(failures ? 1 : 0);
