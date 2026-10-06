// La SAISIE PAR JEU et ses LISTES, exécutée (Romain, 2026-10-06 : « pour la saisie par jeu, je
// voudrais que l'opérateur puisse choisir les listes ; elles seraient toutes cochées par défaut,
// sauf la blacklist »).
//
// Le harnais charge le vrai `urls.js` dans le navigateur bouchonné, lui sert le catalogue des
// listes (`api/data-entry/merchants` : `lists` + `blacklists`), et regarde : les cases (toutes
// cochées, les blacklists décochées et grisées), le compteur, le corps du POST de lancement
// (`lists`), le refus quand rien n'est coché, « tout cocher / tout décocher », et le lot du GO
// groupé par (magasin, liste) avec la liste écrite sur chaque bloc.

import { strict as assert } from "node:assert";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadConsole } from "./load_console.mjs";
import { tick } from "./dom_stub.mjs";

const ICI = path.dirname(fileURLToPath(import.meta.url));
// `URLS_JS` rejoue le harnais contre une page VOLONTAIREMENT cassée (voir le test Python).
const PAGE = process.env.URLS_JS
  || path.join(ICI, "..", "..", "src", "admin", "static", "urls.js");

const CATALOGUE = {
  merchants: [{ name: "G2A", store_id: "38" }], groups: [],
  lists: [{ id: 9, label: "Pending offers" }, { id: 22, label: "Pages for creation" }, { id: 30, label: "account" }],
  blacklists: [{ id: 8, label: "Blacklist" }, { id: 14, label: "Blacklist (added on CDD)" }],
  default_list: 9,
};
const URL = "https://www.allkeyshop.com/blog/buy-neon-beats-cd-key-compare-prices/";

function cand(id, pid = "205027") {
  return { offer: { offer_id: id, name: "Game " + id, url: "https://m/" + id }, aks_product_id: pid, aks_name: "X",
           region: { id: "2", label: "GLOBAL" }, edition: { id: "1", label: "Standard" } };
}

/** La page chargée, le catalogue servi, aucune reprise en cours, aucun ancien aperçu. */
async function ouvrir(recap = null) {
  const c = await loadConsole(PAGE);
  await c.net.release("api/data-entry/merchants", CATALOGUE);
  await c.net.release("api/sort/runs", { busy: null });
  await c.net.release("api/data-entry/by-urls/recap", recap ? { run_id: "r1", recap_sha256: "abc", recap } : { run_id: null, recap: null });
  await tick();
  return c;
}
const cases = (c) => c.$("#lists").querySelectorAll(".list-cb");
const parId = (c, id) => cases(c).find((i) => i.getAttribute("data-list") === String(id));
const posts = (c) => c.net.calls.filter((k) => k.method === "POST" && k.url.includes("api/data-entry/by-urls") && !k.url.includes("submit"));

const essais = [];
function test(nom, fn) { essais.push([nom, fn]); }

test("CATALOGUE : toutes cochées par défaut, les blacklists décochées et grisées", async () => {
  const c = await ouvrir();
  assert.equal(cases(c).length, 5, "trois listes de travail + deux blacklists");
  for (const id of [9, 22, 30]) {
    const i = parId(c, id);
    assert.ok(i, "case " + id);
    assert.equal(i.checked, true, "liste " + id + " cochée par défaut");
    assert.equal(i.disabled, false);
  }
  for (const id of [8, 14]) {
    const i = parId(c, id);
    assert.equal(i.checked, false, "blacklist " + id + " décochée");
    assert.equal(i.disabled, true, "blacklist " + id + " grisée");
  }
  assert.ok(c.$("#lists-count").textContent.includes("3 listes cochées"), c.$("#lists-count").textContent);
  assert.ok(c.$("#lists").textContent.includes("Pages for creation (22)"), "le libellé et l'id");
});

test("LANCEMENT : le corps du POST porte les listes cochées, dans l'ordre du catalogue", async () => {
  const c = await ouvrir();
  c.$("#urls").value = URL;
  c.$("#consoles").checked = true;     // le bouchon ne lit pas le HTML : la case « Consoles » est cochée dans la page
  c.$("#launch").fire("click");        // la réponse n'est jamais servie : on n'attend pas le gestionnaire
  await tick();
  const p = posts(c);
  assert.equal(p.length, 1, "un POST de lancement");
  assert.deepEqual(p[0].body.lists, [9, 22, 30]);
  assert.deepEqual(p[0].body.urls, [URL]);
  assert.equal(p[0].body.consoles, true);
});

test("CHOIX : une case décochée sort du corps ; rien de coché = refus sans POST ; tout cocher revient", async () => {
  const c = await ouvrir();
  c.$("#urls").value = URL;
  parId(c, 22).checked = false;
  await parId(c, 22).fire("change");
  assert.ok(c.$("#lists-count").textContent.includes("2 listes cochées"), c.$("#lists-count").textContent);
  c.$("#launch").fire("click");
  await tick();
  assert.deepEqual(posts(c)[0].body.lists, [9, 30]);
  // la réponse du lancement n'est jamais servie ici : on rouvre pour la suite
  const d = await ouvrir();
  d.$("#urls").value = URL;
  await d.$("#lists-none").fire("click");
  assert.ok(d.$("#lists-count").textContent.includes("0 liste cochée"), d.$("#lists-count").textContent);
  d.$("#launch").fire("click");
  await tick();
  assert.equal(posts(d).length, 0, "aucun POST sans liste");
  assert.ok(d.$("#launch-msg").textContent.includes("Coche au moins une liste"), d.$("#launch-msg").textContent);
  await d.$("#lists-all").fire("click");
  assert.ok(d.$("#lists-count").textContent.includes("3 listes cochées"));
  assert.equal(parId(d, 8).checked, false, "« tout cocher » ne touche pas aux blacklists");
});

test("APERÇU : la liste sur chaque bloc marchand, le lot du GO par (magasin, liste)", async () => {
  const recap = {
    mode: "dry-run", available: "all", consoles: true, lists: ["9", "22"], merchants: ["G2A"], aborted: null,
    totals: { games: 1, resolved: 1, candidates: 2 },
    games: [{ url: URL, resolved: true, aks_product_id: "205027", aks_name: "Neon Beats", aks_url: URL, page_kind: "cd-key",
              total_candidates: 2, search: { found: 2, off_allowlist: 0, truncated: false, per_list: { "9": 1, "22": 1 } },
              merchants: [{ merchant: "G2A", store_id: "38", list_id: "9", found: 1, candidates: [cand("1")], skipped: [] },
                          { merchant: "G2A", store_id: "38", list_id: "22", found: 1, candidates: [cand("2")], skipped: [] }] }],
  };
  const c = await ouvrir(recap);
  const texte = c.$("#recap-games").textContent;
  assert.ok(texte.includes("G2A · liste 22 Pages for creation"), "le bloc de la liste 22 nommé : " + texte);
  assert.ok(texte.includes("G2A · liste 9 Pending offers"), "le bloc de la liste 9 nommé : " + texte);
  assert.ok(texte.includes("liste 9 : 1, liste 22 : 1"), "les résultats par liste : " + texte);
  await c.$("#saisir").fire("click");
  await tick();
  assert.equal(c.$("#confirm-m").textContent, "2", "deux lots : (38, 9) et (38, 22)");
  assert.equal(c.$("#confirm-n").textContent, "2");
  const lot = c.$("#confirm-targets").textContent;
  assert.ok(lot.includes("liste 22 Pages for creation"), "le lot du GO dit la liste : " + lot);
  assert.ok(lot.includes("liste 9 Pending offers"), lot);
});

let rouges = 0;
for (const [nom, fn] of essais) {
  try { await fn(); console.log("ok   -", nom); }
  catch (e) { rouges++; console.log("FAIL -", nom, "\n      ", e.message); }
}
if (!rouges) console.log("tout passe");
process.exit(rouges ? 1 : 0);
