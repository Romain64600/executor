// La console de saisie auto, EXÉCUTÉE — les groupes de marchands (2026-09-22).
//
// Romain : « je ne vois pas les groupes A et B sur l'admin ». Un test qui lit auto.js comme
// du TEXTE n'aurait rien vu de cette panne : le code était écrit, il ne s'affichait pas.
// Ici on charge le vrai fichier livré dans un DOM bouchonné, on sert la charge utile réelle
// de /api/data-entry/merchants, et on regarde ce qui part quand on clique.

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole } from "./load_console.mjs";
import { tick } from "./dom_stub.mjs";

const ICI = path.dirname(fileURLToPath(import.meta.url));
// `AUTO_JS` permet de rejouer le harnais contre une console VOLONTAIREMENT cassée :
// un harnais qui ne devient jamais rouge ne prouve rien (leçon de sort_race).
const AUTO = process.env.AUTO_JS
  || path.join(ICI, "..", "..", "src", "admin", "static", "auto.js");

const MARCHANDS = {
  merchants: [{ name: "GameSeal", store_id: "126" }, { name: "Gamivo", store_id: "51" }],
  default_list: 9,
  lists: [
    { id: 9, label: "Pending offers" },
    { id: 30, label: "account" },
    { id: 22, label: "Pages for creation" },
  ],
  groups: [
    { name: "A", pending: 9355, merchants: [{ name: "GameSeal", store_id: "126" }] },
    { name: "B", pending: 10830, merchants: [{ name: "Gamivo", store_id: "51" }] },
  ],
};

async function demarrer() {
  const c = await loadConsole(AUTO);
  await c.net.release("api/data-entry/merchants", MARCHANDS);
  // La console demande ensuite l'état courant ; on répond « rien en cours ».
  for (const url of c.net.waiting()) {
    await c.net.release(url, { running: false, runs: [] }).catch(() => {});
  }
  await tick();
  return c;
}

const essais = [];
function test(nom, fn) { essais.push([nom, fn]); }

test("les deux groupes deviennent des boutons, avec leur charge", async () => {
  const c = await demarrer();
  for (const nom of ["A", "B"]) {
    const b = c.$("#launch-group-" + nom);
    assert.ok(b.has("click"), `le bouton du groupe ${nom} n'existe pas ou n'écoute rien`);
    assert.ok(b.textContent.includes(nom), `le bouton du groupe ${nom} ne le nomme pas`);
  }
  const note = c.$("#groups-note").textContent;
  assert.ok(note.includes("9355") || note.includes("9 355"), "la charge du groupe A manque");
  assert.ok(note.includes("GameSeal") || c.$("#launch-group-A").title.includes("GameSeal"),
            "les marchands du groupe ne sont indiqués nulle part");
});

test("sans GO tapé, le bouton est inerte et rien ne part", async () => {
  const c = await demarrer();
  const b = c.$("#launch-group-A");
  assert.equal(b.disabled, true, "le bouton doit être désactivé tant que GO n'est pas tapé");
  const avant = c.net.calls.length;
  await b.fire("click");
  await tick();
  assert.equal(c.net.calls.length, avant, "un clic sans GO a quand même envoyé une requête");
});

test("avec GO, le clic envoie le NOM du groupe — jamais une liste de cibles", async () => {
  const c = await demarrer();
  c.$("#go").value = "GO";
  await c.$("#go").fire("input");
  await tick();
  const b = c.$("#launch-group-A");
  assert.equal(b.disabled, false, "GO tapé : le bouton du groupe doit s'activer");
  // On n'ATTEND pas le clic : `launchGroup` reste suspendu sur sa requête, qu'on tient.
  // C'est le but du bouchon — voir ce qui PART avant que le serveur ait répondu.
  b.fire("click");
  await tick();
  const envoi = c.net.calls.filter((x) => x.method === "POST" && x.url.includes("data-entry/auto")).pop();
  assert.ok(envoi, "aucun lancement n'est parti");
  assert.equal(envoi.body.group, "A", "le nom du groupe doit voyager");
  assert.equal(envoi.body.targets, undefined,
               "la console ne doit PAS fabriquer la liste de marchands — le serveur la détend");
  assert.equal(envoi.body.all_allowlisted, undefined,
               "un groupe n'est pas un balayage de toute la liste blanche");
  assert.equal(envoi.body.confirm, "GO");
  assert.equal(envoi.body.all_pages, true, "un groupe couvre toutes les pages de ses marchands");
  // et la réponse du serveur remonte à l'écran, run_id compris
  await c.net.release("data-entry/auto", { run_id: "20260922-auto-A" });
  await tick();
  const msg = c.$("#launch-group-msg").textContent;
  assert.ok(msg.includes("20260922-auto-A"), "le run_id du lancement doit s'afficher : " + msg);
  assert.equal(c.$("#launch-group-B").disabled, true,
               "un run en cours : l'autre groupe reste hors de portée sur CETTE machine");
});

test("la liste balayée est proposée, la Pending par défaut", async () => {
  const c = await demarrer();
  const sel = c.$("#work-list");
  assert.equal(sel.children.length, 3, "les trois listes servies doivent être offertes");
  assert.equal(sel.value, "9", "la file Pending est le défaut");
  assert.ok(sel.children[0].textContent.includes("défaut"), "et elle est marquée comme tel");
});

test("changer de liste l'envoie au serveur, et le dit à l'écran", async () => {
  const c = await demarrer();
  c.$("#go").value = "GO";
  await c.$("#go").fire("input");
  c.$("#work-list").value = "30";
  await c.$("#work-list").fire("change");
  assert.ok(c.$("#list-note").textContent.includes("30"),
            "l'écran doit signaler qu'on ne balaie PAS la file habituelle");
  await tick();
  c.$("#launch-group-A").fire("click");
  await tick();
  const envoi = c.net.calls.filter((x) => x.method === "POST" && x.url.includes("data-entry/auto")).pop();
  assert.ok(envoi, "aucun lancement n'est parti");
  assert.equal(envoi.body.list, 30, "la liste choisie doit voyager avec le lancement");
});

test("sans choix explicite, c'est la file Pending qui part", async () => {
  const c = await demarrer();
  c.$("#go").value = "GO";
  await c.$("#go").fire("input");
  await tick();
  c.$("#launch-group-A").fire("click");
  await tick();
  const envoi = c.net.calls.filter((x) => x.method === "POST" && x.url.includes("data-entry/auto")).pop();
  assert.equal(envoi.body.list, 9);
});

test("un groupe lancé est SUIVI : statut, récapitulatif, puis boutons réarmés à la fin", async () => {
  // REVUE DE ROMAIN (2026-09-23) : « après le lancement, aucun startPolling() : l'écran reste
  // Prêt, le récapitulatif ne s'actualise pas et les boutons restent bloqués après la fin,
  // jusqu'au rechargement. Reproduit avec le simulateur JS. » Le voici, rejoué.
  const c = await demarrer();
  c.$("#go").value = "GO";
  await c.$("#go").fire("input");
  await tick();
  c.$("#launch-group-A").fire("click");
  await tick();
  const avant = c.net.calls.length;
  await c.net.release("data-entry/auto", { run_id: "20260923-auto-A" });
  await tick();
  const apres = c.net.calls.slice(avant).map((x) => x.url);
  assert.ok(apres.some((u) => u.includes("api/sort/runs")),
            "le suivi doit démarrer (interrogation du gestionnaire) : " + apres.join(", "));
  assert.equal(c.$("#busy-ind").classList.contains("hidden"), false,
               "l'indicateur d'activité doit s'allumer");
  assert.equal(c.$("#launch-group-B").disabled, true, "pendant le run, l'autre groupe est bloqué");
  // Le gestionnaire est redevenu libre : le tick demande alors le récapitulatif DU run lancé…
  await c.net.release("api/sort/runs", { busy: null, runs: [] });
  await tick();
  assert.ok(c.net.waiting().some((u) => u.includes("data-entry/recap?run=20260923-auto-A")),
            "le récapitulatif du run lancé doit être demandé : " + c.net.waiting().join(", "));
  // …qui porte une fin : le run est terminé.
  await c.net.release("data-entry/recap?run=20260923-auto-A",
                      { recap: { finished_at: "2026-09-23T20:00:00Z" } });
  await tick();
  assert.equal(c.$("#launch-group-B").disabled, false,
               "après la fin, les boutons doivent se réarmer SANS recharger la page");
  assert.equal(c.$("#busy-ind").classList.contains("hidden"), true);
});

test("un serveur sans groupes le DIT au lieu de laisser une case vide", async () => {
  const c = await loadConsole(AUTO);
  await c.net.release("api/data-entry/merchants", { merchants: MARCHANDS.merchants });
  await tick();
  assert.ok(c.$("#groups-note").textContent.includes("Aucun groupe"),
            "une console muette est exactement la panne qu'on corrige");
});

let rouges = 0;
for (const [nom, fn] of essais) {
  try { await fn(); console.log("ok   -", nom); }
  catch (e) { rouges++; console.log("FAIL -", nom, "\n      ", e.message); }
}
process.exit(rouges ? 1 : 0);
