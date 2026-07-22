# Changelog — AKS Controlled Executor

Notable changes, newest first. Dates are UTC. Complements [`AUDIT.md`](AUDIT.md)
(findings) and the roadmap in [`../README.md`](../README.md).

## 2026-07-22 — Learning : confirmation explicite des suggestions (SF2, option B)

Romain 2026-07-22 : la confirmation d'une disposition Move-to-list suggérée est
EXPLICITE (option B, la plus fidèle à D1-b). Bouton **« ✓ confirmer »** par offre
+ bouton global **« confirmer toutes les suggestions »** ; changer la valeur du
select confirme aussi (décision explicite) ; regarder le menu ne confirme plus
rien. Le mover ne consomme toujours que les dispositions `suggested != true`.

## 2026-07-22 — Stage 6 : 1er canary Move-to-List RÉUSSI + registration déterministe

Premier vrai move end-to-end, sur go de Romain : l'offre logicielle « IObit
Advanced SystemCare » (run G2A) déplacée de la liste 9 (pending) vers Softwares
(16), vérifiée **partie de la liste source** (le seul signal de succès).

Fix validé par le canary : la registration d'une offre dans le bulk form se fait
désormais par **injection déterministe** du hidden `bulk[item][]` (submit_session
`register_row`), et non plus par un clic trusted sur la case — ce dernier s'est
révélé fragile sur les pages paginées du feed (`click=CLICKED` mais le handler
async n'injectait pas le hidden ; fail-closed : rien n'était soumis). Le POST
natif de l'Apply (trusted) sérialise le hidden injecté à l'identique. Le 1er move
raté avait laissé l'offre intacte (aucune écriture partielle). Suite 743 verte.

## 2026-07-22 — D2 tranché : processus builder-offline officialisé

Romain 2026-07-22 : pas de moteur de règles apprises dans le repo. La
généralisation des annotations Learning en comportement du pipeline passe par
le **processus builder-offline** — `docs/LEARNING_PROCESS.md` (nouveau) :
learning.json est l'autorité d'intention humaine, le code l'autorité
d'exécution ; une annotation devient soit un move (Stage 6), soit une saisie
manuelle assistée, soit une règle matcher déterministe (testée/documentée/
committée/révocable) — jamais une règle appliquée automatiquement au runtime.
Le `scope` (exception/marchand/global/observation) porte la généralisation ;
une exception ne devient jamais une règle générale. EXECUTOR_RULES §13 pointe
le processus ; D2 fermé dans AUDIT_LEARNING.

## 2026-07-21 — Stage 6 : writer Move-to-List (brique B, dry-run par défaut)

Le mover — frère du submitter — déplace les offres non-matchées hors de leur
liste source vers la liste annotée. Mécanique confirmée read-only
(`docs/AKS_LISTS.md`) : POST natif du bulk form, register trusted-only.

- `src/move_plan.py` : construit le plan depuis les dispositions CONFIRMÉES de
  `learning.json` (target_list_id présent ET `suggested != true`, D1-b),
  jointes à `skipped.json` pour name+url ; orphelines/suggestions exclues
  (jamais silencieusement), source list dérivée de raw.json.
- `src/mover.py` : `resolve_list_id` (par LABEL live, les ids driftent),
  `DryRunMover` (locate + selectable, aucune écriture) et `Mover` (register
  trusted → set bulk[list] → Apply trusted → **vérif « gone from source »**).
  Réutilise les scans audités du submitter (`_scan_feed`/`_locate_row`/
  `_verify_gone`/`_url_key`).
- `src/submit_session.py` : `list_options` (read-only), `register_row`/
  `set_bulk_list`/`click_apply` (WriteSubmitSession).
- `scripts/06_move.py` : mêmes gates que Stage 5 — invariants verts+authoritative,
  browser_lock, dry-run par défaut (`--execute`), mode R24 (safe = plan complet ;
  learning/advanced = canary de 1), BlockLedger, JSONL. Jamais fire-and-forget.

Aucun move réel lancé — le 1er canary attend le go explicite de Romain.
Tests : +35 (mover 16, move_plan 3, + JS inventory). Suite 724 verte.

## 2026-07-21 — Learning (annotations) : vue admin + durcissement post-audit

**Attention au nom** : « Learning » (cette fonctionnalité, la vue d'annotations
admin) ≠ `--mode learning` (le mode de submit R24, un canary de 1 qui ÉCRIT).
Deux concepts sans rapport — voir EXECUTOR_RULES §13.

La vue Learning (commits `b7e930d`→`ec35712`) : par run, les offres non-matchées
groupées par raison de skip, annotables par offre — région/édition (vrais ids du
catalogue de session), commentaire, page AKS, disposition « Move to list »
(suggestion déterministe, défaut *garder*) — stockées dans
`runs/<id>/learning.json`. Aucun code pipeline ne consomme ce fichier : la
généralisation en règles matcher reste un processus builder-offline (jamais de
LLM runtime). Taxonomie des listes + mécanique du move : `docs/AKS_LISTS.md`.

Durcissement issu de l'audit `AUDIT_LEARNING_2026-07-21.md` (L1-L11) :

- **L1** — les éditions Learning posent `DIRTY` et le save resynchronise
  l'empreinte : l'auto-refresh 10 s n'efface plus une saisie en cours.
- **L2** — le save est un **merge** (jamais un remplacement) : suppression
  uniquement par signal `cleared` explicite ; précondition `base_sha`
  (409 `conflict` en écriture concurrente, pattern AS1) ; verrou serveur.
- **L3** — option fantôme « (hors catalogue) » : un id région/édition sauvegardé
  qui a dérivé du catalogue survit au rechargement et au re-save.
- **L5** — validation serveur fail-closed : liste cible ∈ catalogue + label
  cohérent, région/édition ∈ catalogue de session (grandfather sur valeur déjà
  stockée), `aks_url` au format page AKS, champs ≤ 2000 caractères.
- **L6** — `learning_log.jsonl` par run : un événement JSONL par save
  (sha avant/après, ids touchés/supprimés, auteur).
- **L8** — suggestions ancrées sur la catégorie de raison (plus de sous-chaîne
  libre : « steam-account » ne suggère plus la liste account).
- **L9-L11** — message correct sur run non matché ; panneau Learning chargé même
  si la validation échoue ; `by` = identité basic-auth d'abord ; `first_by`/
  `first_at` conservés à l'édition ; bannière stale mentionne les annotations.

Décisions de Romain (2026-07-21, même jour) :

- **D1 = (b)** → L4 FIXED : la préselection Move-to-list est persistée avec
  `suggested: true` tant que non manipulée (badge « suggéré — à confirmer ») ;
  toute manipulation du select la confirme. Le futur mover ne consommera que
  les dispositions confirmées.
- **D3 = oui** : champ `scope` par annotation (`exception_offre` /
  `regle_marchand` / `regle_globale` / `observation`) — seules les deux
  « règle » autorisent une généralisation par le builder.
- **D4 = oui** : champ `platform` (vocabulaire canonique, 12 tokens) — le
  cas 8 (correction de plateforme) est couvert ; une plateforme seule est une
  annotation valable.

Restent OUVERTES : D2 (moteur de règles dans le repo vs processus
builder-offline officialisé) et D5 (renommage UI).

Tests : 703 verts.

## 2026-07-21 — Admin extraction: two modes, full shop vs par page (Romain)

The admin's "Lancer l'extraction" only did a full sweep, so runs went out at
1142 offers (Kinguin) — against the one-page-at-a-time cadence
(EXECUTOR_RULES §11), which is what keeps a batch from going stale while the
feed re-imports. Added a mode selector:

- **Par page (100 offres)** — `start_extract(..., page="N")` passes
  `--pages N` (the extractor's slice mode, `partial: true`). The cadence norm:
  one page → match → report → validate → submit → next page.
- **Full shop** — `page=None`, the whole-feed sweep (unchanged).

`page` accepts `"N"` or `"N-M"` (validated `bad_page` otherwise). Tests +5.
658 green.

## 2026-07-20 — Submit speedup via tighter pacing (Romain); navigate settle stays 3 s

Romain: "vu que tu peux faire deux requêtes par seconde", the submit was far
too slow. The fix is the pacing (burst mitigation, never correctness):

- `--pace-offers` default `5-15` s → `0.5-1.5`, `--pace-pages` `1-3` s →
  `0.4-0.6` (≈ 2 req/s, AKS's tolerance per Romain).

A shorter `navigate` settle (3 s → 1 s) was also tried but **reverted the same
day**: reading feed rows works fast (SSR HTML), but the page's interactive JS
(jQuery/ThickBox that the create-offer click drives) is not initialized at 1 s,
so `open_offer_modal` clicked yet `#TB_ajaxContent` never loaded —
"modal context missing" on every offer (live Driffle). The settle is a real
in-page timing dependency, unlike the pacers. A successful offer's cost still
drops from ~30 s to ~18 s from the pacers alone.

**Settle split (the correct version).** The blanket cut was wrong, but the
FEED-SCAN navigates (`_read_feed_page`: index + the full post-save re-walk
after every creation — the bulk of a submit's time) open no modal and only
read SSR rows, so they now use a short `FEED_SCAN_SETTLE = 1.0 s`; the navigate
BEFORE a modal open (`_prepare`'s row page, the catalog fetch) keeps the 3 s
default. Extraction already proved 1 s reads rows fine. This reclaims the
post-save re-scan time without touching the modal timing that broke before.

## 2026-07-20 — REVERT FC4: it blocked every GLOBAL submit + admin panel shows only the current stage

**FC4 regression (urgent, live).** The 2026-07-17 audit fix FC4 made
`resolve_catalog_id`'s id-path require the matcher's region label to appear as
a word in the live dropdown text. But the AKS dropdown labels Steam's global/
worldwide region **`"Steam (2)"`**, while the matcher calls it **`GLOBAL`** —
synonyms for the same id 2, and "global" is not in "steam (2)". So FC4 blocked
GLOBAL — the most common region — on every real submit (Driffle 2026-07-20: all
offers `region not in session catalog (label='GLOBAL' id='2')`, 0 created).
Reverted: the id-path validates EXISTENCE only, as it did for the project's
whole history; the label-path still remaps a drifted id when the label uniquely
matches, and the human validates the region label in the report. The test
fixtures that hid this (region key 2 texted `"GLOBAL"` instead of `"Steam (2)"`)
are now realistic, with an explicit regression test. FC4's "id drifted to a
different region" concern was PLAUSIBLE-not-confirmed and stays open.

**Admin panel (Romain).** A run's log now accumulates extraction + matching +
submit events, so the progress panel replayed the whole history on each stage
launch (the confusing "sweep / terminé exit 0" lines under a fresh submit).
`startRun`/`startMatch` now seek the log tail to its current end, so the panel
shows only the stage just launched.

Tests: 652 green (FC4 tests replaced by the realistic-fixture regression test).

## 2026-07-20 — Admin: launch the matching step (stage 3) from the page (Romain)

The admin could launch extraction (stage 1) but not matching (stage 3), so an
extracted run showed "0 candidat / non matché" until someone ran
`03_match.py` by hand. Romain: "il faudrait ajouter un bouton pour cette étape
de validation." Added a **"Lancer le matching"** button (with an optional max-
candidates field) on the run panel.

- `SubmitManager.start_match(run_dir, by, max_candidates)` spawns
  `03_match.py offers.json [--max-candidates N]` (kind `match`), supervised
  like every other run. Read-only HTTP (no browser/CDP, no browser lock) but
  serialized under the same one-run-at-a-time gate. Requires `offers.json`
  (refuses `not_extracted` otherwise); rejects a non-positive max-candidates.
- `POST /api/runs/<id>/match` (`app.py::_post_match`). The UI reuses the run
  progress/poll machinery; when the match completes it re-opens the run, so
  the report + validation table populate automatically.

Tests: +9 (`StartMatchTests`, `MatchEndpointTests`). 651 green. Follow-up
offered but not built: auto-chain matching at the end of extraction.

**Live progression (same day, Romain: "on aurait voulu voir la progression
depuis l'admin").** The match button reused the submit progress panel, but
`03_match` emitted nothing, so the panel stayed silent until completion.
`match_feed` now takes an `on_progress` callback (called every 5 offers + at
the end with `{done, total, candidates, skipped}`); `03_match` logs these as
`match_progress` events to the run's JSONL, added to the admin's `UI_EVENTS`.
The UI shows a single live counter in the panel title —
"Matching : 150/226 — 5 candidat(s), 145 écarté(s)". Also fixed the
candidate-cap skip message (was hardcoded "max 100", now the actual cap).
Tests: +2. 653 green.

## 2026-07-20 — Submit auto-defaults --max-pages from the feed's own page count (Romain)

The P0.2 coverage check (SC4) aborts fail-closed if the batch-start feed index
hits the `--max-pages` ceiling while the feed advertises MORE pages. Difmark's
feed is ~357 pages, so the historical 40-page floor always aborted
(`feed_unreadable`, 0 attempts) unless the operator remembered to raise
`--max-pages` by hand. Now the extractor persists the feed's own advertised
page count and the submit derives the ceiling from it.

- `RawSnapshot` / `NormalizedFeed` gain `feed_last_page` (the pagination nav's
  `nav_max`, distinct from `pages_scanned` which a slice under-counts). Written
  to `raw.json` and `offers.json`; `0` when not recorded (legacy runs).
- `scripts/05_submit.py`: `--max-pages` now defaults to AUTO — reads
  `offers.json` `feed_last_page` and uses `max(40, ceil(pages × 1.3))` (30%
  churn headroom), floored at 40, falling back to 40 when unknown. An explicit
  `--max-pages` still overrides. The chosen value + reason is printed. The
  admin passes nothing when its (now "vide = auto") field is empty, so it
  auto-derives too — no admin backend change.

Tests: +7 (`DeriveMaxPagesTests` + contract round-trips). 644 green.

## 2026-07-18 — Difmark Account offers resolve the AKS account PAGE (Romain)

Rounds 1-2 (2026-07-17) got the account *region* right (Steam Account 412/…)
but still matched the game's `…-cd-key-…` page. Romain 2026-07-18: "pour les
offres Account, tu dois proposer la page Account, pas la page du jeu." AKS
carries a SEPARATE product page per account platform,
`buy-<slug>-<platform>-account-compare-prices/` — a distinct product (own
id/editions/prices). Verified live: `Final Knight Steam Account` = 187974
(vs the key page `Final Knight` = 171000), and every existing listing on the
account page (G2A included) uses region 412 — so account-page + account-region
is internally consistent.

- `aks_url(slug, page_kind)` + `resolve_aks(page_kind=…)` build the
  `…-<kind>-compare-prices/` URL; `DIFMARK_ACCOUNT_PAGE_KINDS = {"STEAM":
  "steam-account"}` (Steam-only confirmed for Difmark). No R30 site-search
  fallback for account pages (the result regex only knows `-cd-key-` slugs).
- `match_offer` gains an injectable `account_resolver`; account offers route
  through it. R01 compares against the game **identity** — `account_identity()`
  strips the "<platform> Account" page-type suffix from the AKS name
  ("Final Knight Steam Account" → "Final Knight"), which the feed title
  ("Final Knight Standard Edition") never carries. A resolved account-URL 200
  whose name lacks the suffix fails closed ("not an account page").
- Live end-to-end confirmed: a Difmark Steam-Account offer for Final Knight
  now resolves product 187974, region GLOBAL ACCOUNT(412); games with no AKS
  account page (key page also 404) correctly skip.
- Caveat (pre-existing): the generic "Standard Edition" title yields
  Standard(1) even when the account page's only edition is Early Access(5) —
  fail-closes at submit (product-scoped dropdown); surfaced for validation.

Tests: +7 (`AccountPageResolutionTests` + updated Difmark account tests). 637 green.

## 2026-07-17 — Audit P2.c : docs remises au niveau du code + skips §4.3 enfin codés (DO1-DO6)

Rafraîchissement produit par un workflow multi-agents (5 rédacteurs ancrés
sur le code + 5 vérificateurs factuels indépendants, leurs erreurs corrigées
avant écriture) :

- **NOOB.md** (DO1) — la contradiction canary/§4c est résolue en faveur de
  R24 ; ajout de l'Étape 0b, de la page opérateur, du verrou navigateur, du
  statut UNKNOWN, et d'une idée reçue n°10 retirant l'ancienne règle canary.
- **ARCHITECTURE.md** (DO2) — réécrit sur l'état réel (fini le N8N de jour 1) :
  stages 0b-5, layering des modules, admin, tab CDP unique, triple validé +
  liaison sha (AS1), match_meta (FC5), marqueur root (FC2).
- **README.md** (DO3) — arborescence réelle, compte de tests, page admin,
  registre d'audit ; le quick start ne mentionne plus AKS_TARGET=vps.
- **DATA_CONTRACTS.md** (DO4) — contrats des artefacts stages 4+ :
  submit_plan.json (dont post_save UNKNOWN et matched_mode),
  session_catalog.json, admin_submit.json, match_meta.json,
  guard_ledger.json, modal_inspection.json.
- **ops/BROWSER_RUNBOOK.md** (DO5, NOUVEAU) — le substrat navigateur enfin
  documenté, vérifié live : hold apt Chromium 149 (et pourquoi : le 150
  Debian SIGTRAP) couplé à l'UA épinglé, unités systemd, proxy socat 9223,
  politique UA-Switcher, procédures de récupération et checklist de
  reconstruction VM complète (marqueur FC2 inclus).
- **DO6** — les skips que §4.3 promettait depuis v1 existent enfin dans le
  matcher : « EU-NA » (FORBIDDEN_REGIONS, la normalisation de ponctuation
  fait matcher « EU NA ») et les country gifts (CZ/RU/TR/BR/AR/IN/CN
  ADJACENTS au mot GIFT — « Alice in Wonderland Steam Gift » ne skip pas).

Tests : +4 (630 verts).

## 2026-07-17 — Audit P2.b : transport CDP désync-proof, contrats de fakes, primitives login testées (SC7/SC8/TE2/TE4/TE5)

- **SC7** — `_page_ws_path` ne retient que les vrais onglets http(s)
  (`chrome-error://`, `devtools://`, `chrome://` exclus — l'ancien filtre par
  sous-chaîne laissait passer un onglet crashé) et préfère l'onglet déjà sur
  allkeyshop.com (suffix-spoof safe) quand le navigateur partagé en porte
  plusieurs. Décision documentée : PAS de reconnexion mid-run — un socket
  mort lève `CdpCommandError` et le run s'arrête fail-closed (reprendre sur
  un socket frais cacherait un restart navigateur à la preuve de
  disparition).
- **SC8** — framing WebSocket réécrit : opcodes gérés (Close → raise au lieu
  d'être parsé comme du texte, Ping → Pong répondu, Pong ignoré),
  fragmentation assemblée jusqu'à FIN, lecture EXACTE des en-têtes (un
  timeout/EOF mid-frame lève — l'ancien short-read de 2 octets désynchronisait
  le parsing pour toujours), `sendall` au lieu de `send`.
- **TE2** — `tests/test_fake_contracts.py` : chaque fake duck-typé de la
  suite est vérifié mécaniquement contre sa classe réelle — méthode fantôme
  ou paramètre renommé d'un côté = test rouge, fini la dérive silencieuse
  d'interface.
- **TE4** — les primitives réelles de `LoginSession` sont exécutées par les
  tests (les credentials ne sont JAMAIS tapés si le clic de focus du champ a
  échoué ; `verify_dashboard` exige URL ET DOM ; payloads JS read-only).
- **TE5** — `click_trusted_at_element` délègue son scroll à
  `_scroll_rect_into_viewport` : une seule implémentation, celle testée.

Tests : +27 (624 verts).

## 2026-07-17 — Audit P2.a : les gates déclaratifs deviennent mécaniques (FC2/FC3/FC4/FC5)

- **FC2** — `AKS_TARGET=vps` ne force plus `authoritative:true` : une seule
  variable d'env ne doit jamais déverrouiller les stages d'écriture. La seule
  autorité est désormais le **marqueur root** `/etc/aks-executor.target`
  (installé sur le VPS le 2026-07-17), qui doit être possédé par root, non
  modifiable par le groupe/autres, ET contenir le hostname de la machine (un
  marqueur copié ailleurs ne transfère rien). La direction inverse
  (`AKS_TARGET=dev` → force OFF) reste — forcer non-autoritaire est toujours
  sûr. Le shell audit (`00_audit_env.sh`) suit le même ancrage. Vérifié live :
  le gate reste vert+authoritative sur le VPS, zéro fenêtre rouge.
- **FC3** — G03 inter-processus (`BlockLedger`, `runs/<id>/guard_ledger.json`) :
  un blocage StepGuard mourait avec son process, rien n'empêchait une 3e passe
  identique après deux passes bloquées. Une passe de récupération sur le même
  run reste LIBRE (récupération idempotente standard, Romain 2026-07-07) ;
  deux passes réelles consécutives bloquées → la 3e exige
  `--acknowledge-block` (acquittement humain explicite, qui remet le compteur
  à zéro). Une passe propre remet aussi le compteur à zéro. Dry-runs exclus.
- **FC4** — `resolve_catalog_id` chemin id : l'existence de l'id ne vaut plus
  validation — le label du candidat doit apparaître comme mot entier dans le
  texte du catalogue live ("EU" ⊆ "Steam EU (9)") ; un id qui a dérivé vers
  une autre option ("BTC 1500 PLN") → None → blocker, jamais d'adoption
  aveugle du texte dérivé.
- **FC5** — le mode R24 est enfin traçable : `03_match --mode` (défaut safe,
  comportement identique tant que le matcher n'a pas de profils) tamponne
  `match_meta.json` ; `05_submit` ET l'admin refusent un submit réel dont le
  mode déclaré implique un lot PLUS LARGE que le mode matché (run matché en
  canary → jamais le chemin lot-complet `safe`). Runs pré-FC5 sans meta :
  acceptés. `submit_plan.json` enregistre `matched_mode`.

Tests : +20. 597 verts. Miroir EXECUTOR_RULES différé (chantier Difmark
parallèle sur le fichier).

## 2026-07-17 — Audit P1.c : GO lié au lot, plus d'orphelin, keep-alive sain, verrou navigateur (AS1/AS2/AS3/OP1)

- **AS1** — le « GO » tapé est désormais lié au CONTENU exact du lot affiché :
  la page capture le sha256 d'`approved.json` à l'ouverture du dialogue et le
  renvoie avec le submit réel ; le serveur refuse (`409 approved_changed`) si
  une validation concurrente (second opérateur, autre onglet) a régénéré le
  lot entre l'affichage et le GO. Sha absent → `400 approved_sha_required`
  (recharger la page). Exposé dans GET/POST validation.
- **AS2** — un échec (OSError) entre `Popen` et le démarrage de la
  supervision laissait un enfant VIVANT non supervisé — le seul chemin
  fire-and-forget du projet. L'enfant est maintenant tué (terminate→kill)
  avant de propager l'erreur, et le manager se libère.
- **AS3** — le corps de chaque POST est intégralement lu AVANT toute réponse
  (`_drain_body`) : les handlers sans corps (`/api/invariants/check`) et tous
  les chemins d'erreur précoces (CSRF 403…) laissaient les octets non lus
  désynchroniser la connexion keep-alive HTTP/1.1 — la requête suivante se
  parsait au milieu du corps précédent. Un corps > 2 Mo est refusé sans
  lecture avec fermeture de connexion (seul moyen de rester en phase).
- **OP1** — `src/browser_lock.py` : verrou `flock` inter-processus sur
  `state/browser.lock`, pris non-bloquant par chaque stage qui ouvre une
  session CDP (02 extract, 05 submit tous modes, 00b login). Un seul pilote
  pour l'unique onglet Chrome : une CLI lancée pendant un run admin (ou
  l'inverse) refuse de démarrer en nommant le détenteur, au lieu de corrompre
  les scans/modales de l'autre. L'admin est couvert sans changement : il
  spawn ces mêmes scripts. Libération par le noyau à la mort du process —
  pas de verrou fantôme.

Tests : +9 (SpawnFailClosedTests, ApprovedShaBindingTests, keep-alive,
BrowserLockTests, refus busy CLI). 565 verts.

## 2026-07-17 — Audit P1.a : huit correctifs matcher (MA1-MA8)

Tous confirmés par repro live pendant l'audit contre-vérifié du 2026-07-17 :

- **MA1** — `resolve_aks` : une erreur transitoire (429/5xx/timeout) ou un
  nom illisible sur un slug PLUS spécifique lève immédiatement au lieu
  d'être masqué par le 200 d'un tier moins spécifique (un titre deluxe
  atterrissait sur la page du jeu de base). C'est ce que la docstring
  promettait déjà.
- **MA2** — `explicit_platform` : word-boundary + départage par collocation
  `<PLATEFORME> [CD ]KEY/GIFT` — "Epic Chef … Steam Key" n'est plus EPIC,
  "Gogol's Quest" n'est plus GOG ; ambiguïté résiduelle → None (chemin
  token-less R27/R29, fail-closed).
- **MA3** — ANNIVERSARY/DEFINITIVE deviennent des qualifieurs dangereux
  (modèle REMASTERED) : "Skyrim Anniversary Edition" n'entre plus sur la
  page du jeu de base en Standard(1). Pas d'EDITION_HINTS possible : le
  catalogue maître n'a pas d'id numérique stable pour ces éditions.
- **MA4** — `gift` doit être un segment d'URL entier : "the-gifted-rabbit"
  ne propose plus GIFT(25).
- **MA5** — le pool R23 ne crashe plus (`AttributeError`) sur une map
  d'éditions à valeurs chaînes — un tel crash abortait tout le run de match.
- **MA6** — dérive de markup AKS bruyante : un bloc `"prices"` présent mais
  imparsable lève `AksPageUnparseable` → skip distinct, au lieu d'un ()
  silencieux qui désactivait le garde-fou anti-doublon R25. L'absence reste
  souple (les stubs sérialisent `"prices":[]` ; éditions/plateformes
  absentes déjà couvertes par R19/R20/R27).
- **MA7** — le marqueur Gamivo `-en-` (clé EN-only) est enfin codé — skip
  "language restriction", scopé gamivo.com.
- **MA8** — défense titre pour les régions : "EUROPE" nu en milieu de titre
  (grammaire K4G) et région dans une parenthèse non-première → EU au lieu
  de GLOBAL implicite.

Tests : +25 (8 classes AuditMaX). 555 verts. EXECUTOR_RULES §4.2/§4.4/§4.7
mis à jour.

## 2026-07-17 — Audit P1.b : le pick Selectize est vérifié, la ligne re-vérifiée sur le DOM frais (SC3/SC5)

Deux trous du chemin d'écriture confirmés par l'audit :

- **SC3** — le readback post-pick (`select.value` + `selectize.getValue()`)
  était lu mais jamais COMPARÉ à l'id cible : un clic trusted atterrissant
  sur l'option voisine passait `SELECTED`, et tous les gates suivants
  passaient aussi (le formulaire est valide avec n'importe quelle option).
  `select_via_trusted` exige maintenant l'égalité des deux canaux avec l'id
  visé (`WRONG_VALUE` sinon, `READBACK_UNREADABLE` si illisible), et
  `fill_then_click_trusted` re-lit les DEUX selects juste avant le clic
  Create (`VALUE_DRIFTED_BEFORE_CLICK` — dernière porte avant la seule
  écriture du pipeline).
- **SC5** — `_prepare` naviguait vers la page de la ligne (nouveau render)
  puis ouvrait la modale par id sans re-vérifier la ligne sur ce DOM frais ;
  un ré-import dans la fenêtre peut réattribuer l'id à un autre produit.
  La ligne est maintenant relue et re-vérifiée (`_row_check`, nom + chemin
  URL, prix non bloquant) avant `open_offer_modal` — ligne disparue ou id
  réutilisé → blocker, jamais de modale sur une ligne non vérifiée.

Tests : WRONG_VALUE, READBACK_UNREADABLE, VALUE_DRIFTED_BEFORE_CLICK,
FreshRowRecheckTests (3 scénarios). 526 tests verts. `SUBMITTER_SPEC.md`
§4/§4b mis à jour.

## 2026-07-17 — Audit P0.2 : la preuve post-save exige un scan positivement complet (FC1/SC1/SC2/SC4/SC6/TE1)

L'audit multi-agents du 2026-07-17 (`AUDIT_2026-07-17.md`) a confirmé un
angle mort systématique : le submitter inférait « offre disparue = créée »
de l'ABSENCE de données, sans jamais prouver que le scan avait réellement lu
le feed en entier. Quatre chemins produisaient un faux CREATED : un timeout
CDP silencieusement converti en `None` (lu « 0 lignes »), une page blanche
transitoire (déjà vue live le 2026-07-07 — l'extracteur s'en défendait, le
submitter non), une navigation échouée jamais vérifiée (le tab re-sert le
DOM précédent), et le plafond `max_pages` absorbé sans trace.

Corrections, en miroir de la discipline de l'extracteur :

- `src/cdp_session.py` : `_cmd` lève `CdpCommandError` sur timeout ou erreur
  protocole (fini le sentinel silencieux) ; `navigate` vérifie l'`errorText`
  de `Page.navigate`.
- `src/submit_session.py` : nouvelle sonde read-only `feed_page_state()`
  (`feed_ui`, `nav_max`, `is_login`, `href`) — les mêmes marqueurs
  déterministes que l'extracteur.
- `src/submitter.py` : `_read_feed_page` re-fetch une page blanche UNE fois
  puis classifie (fin de feed prouvée par les marqueurs, sinon
  `FeedScanError`) ; bounce login → `NotLoggedInError` ; `href` comparé à la
  page demandée (navigation coincée détectée) ; épuisement de `max_pages`
  avec un nav qui annonce plus de pages → `FeedScanError` au lieu d'une
  troncature silencieuse. Mid-batch : l'offre courante passe
  `post_save = "offer state UNKNOWN, verify it by hand"` (tentative comptée,
  création NON comptée), le run s'arrête `stopped="feed_unreadable"` en
  écrivant plan + logs. En début de batch : `aborted="feed_unreadable"`.
- `scripts/05_submit.py` : ces exceptions hors boucle → abort JSON propre,
  exit 2 (l'admin affiche l'échec).
- Tests : `tests/test_cdp_session.py` (nouveau, transport fail-closed) +
  `FeedScanFailClosedTests` (8 scénarios : blanche transitoire re-tentée,
  blanche persistante, bounce login, navigation coincée, cap dépassé, feed
  finissant exactement au cap, mort du tab après le clic Create → UNKNOWN,
  mort CDP avant modale). 520 tests verts.

Doc : `SUBMITTER_SPEC.md` §5 mis à jour. Le miroir `EXECUTOR_RULES.md` §7
suivra le commit du chantier Difmark en cours (session parallèle, fichier
partagé).

## 2026-07-16 — R30: AKS site-search fallback when every guessed slug 404s

Romain asked why the matcher only guesses a slug and never queries an LLM or
AKS's APIv2 to resolve the product page — and separately flagged a concrete
failure mode of a naive search fallback: a weak/no-match query gets padded by
AKS with unrelated "top games" filler, so a search hit can't be trusted on
its own. Decision: still no LLM (non-deterministic, would sit upstream of
every other check in this stage) and no APIv2, but add AKS's own WordPress
search (`/blog/?s=`) as a **fallback** — only after every guessed slug 404s
cleanly (a transient probe failure or unreadable page name still fails
closed and never reaches search) — with a **20s timeout** (the endpoint is
slow; the default 5s used everywhere else starves it) and each of up to 3
result slugs probed and identity-checked exactly like a guessed slug: same
R01 (every AKS word present in the title) / R01b (no dangerous qualifier)
gate, no shortcut.

Live-verified the filler risk is real but harmless: Eneba "Worms Collection
2014 Steam Key (PC) EUROPE" (no guessable AKS page) search-resolved to an
unrelated page ("Assassin's Creed Black Flag Resynced") — R01 correctly
SKIPped it (`missing AKS words: ASSASSIN'S, CREED, BLACK, FLAG, RESYNCED`).
Spot-checked against real skips from the same Eneba run: most token-less/
unusual titles still correctly resolve to nothing even with search enabled
— yield is low, as expected for the batch's failure modes, but the
mechanism never bypasses the identity gate.

## 2026-07-16 — R29: Eneba's URL carries a platform prefix the title doesn't

Same Eneba run as R28: candidate "Apothecarium: The Renaissance of Evil -
Premium Edition" had matched as `Publisher GLOBAL(1)`. Romain: "c'est Steam,
pas publisher." The title carries no platform word anywhere — it should have
hit R27's token-less-title skip, not Publisher, so this was actually a
second bug: `explicit_platform(offer.name)` correctly returned `None`, but
somewhere downstream it still resolved to Publisher instead of skipping.

Root cause was upstream of both: the merchant genuinely does declare the
platform, just not in the title. Every Eneba listing URL is
`eneba.com/<platform>-<slug>` — a leading platform-prefix path segment
(`eneba.com/steam-apothecarium-...`) present on every listing regardless of
whether the title repeats it. Fix: `explicit_platform_from_url`, checked as
a fallback after the title, scoped to `eneba.com` URLs only (no other
merchant's URL has a title-word this could false-positive against) and only
recognizing prefixes this codebase already has a platform constant for
(`steam`, `gog`, `epic`, `uplay`→UBISOFT, `origin`→EA, `blizzard`→BATTLENET,
`windows`→MICROSOFT).

Re-resolving with the fix live turned up a second finding: once correctly
Steam GLOBAL(2)/Premium(34), R25's duplicate guard caught it — Eneba
(merchant id 272) already has a price at that exact region/edition on AKS.
The wrong Publisher classification had been hiding a real duplicate, not
just mis-entering the platform.

`src/matcher.py` (`explicit_platform_from_url`, wired into `match_offer` as
`explicit_platform(offer.name) or explicit_platform_from_url(offer.url)`),
mirrored in `EXECUTOR_RULES.md` §4.4. 4 new tests, 476 total, all green.

## 2026-07-16 — R28: NFKC-normalize before tokenizing (Eneba "Road to Empress" escape)

Also same session: candidate "Glary Utilities PRO 5" (a PC cleaning/
optimization utility, same category as CCleaner/IObit) reached the Eneba
candidate list — added `GLARY` to `SOFTWARE_APP_TOKENS` (R22 gap), 1 test,
no design change.

Romain flagged a live mismatch: candidate "Road to Empress Ⅱ Steam Key (PC)
EUROPE" had matched AKS product "Road To Empress" — a different, unrelated
game (AKS has no page for the sequel — 404 on `road-to-empress-ii`). Root
cause: the merchant title used U+2161 ("Ⅱ", a single Unicode Roman numeral
codepoint), not two ASCII `I`s. `tokenize`'s `[A-Z0-9']+` regex silently
drops any character outside that class, so the sequel indicator vanished —
"Road to Empress Ⅱ" tokenized identically to "Road To Empress". The same
text feeds `build_slug_candidates`, so the wrong page was being *probed* in
the first place, not just wrongly approved by the R01/R01b word checks after.

Fix: NFKC-normalize before both (folded into the existing
`normalize_apostrophes` choke-point both call). NFKC is standard library,
zero new dependency, and is specifically designed to decompose compatibility
characters like Roman numerals into plain ASCII ("Ⅱ" → "II") — the real
distinguishing word now survives into slug-building and the identity checks.
Curly quotes stay a separate explicit replace (not an NFKC compatibility
decomposition of `'`).

`src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.1. 3 new tests, 472
total, all green. The Eneba run was re-matched with both fixes before
validation — nothing wrong reached `approved.json`.

## 2026-07-15 — R27: R26 was too broad — Gameboost proved the opposite failure mode

Same day as R26, a Gameboost data-entry run was cancelled live: Romain caught
that Steam offers were being entered as Publisher. R26 (hours earlier) made
any token-less title with *some* AKS page platform signal default to
PUBLISHER — right for DCS P-51D Mustang / A-10C Warthog (Kinguin), wrong for
Gameboost, whose actual platform truth lives on its own merchant page, which
this pipeline can't fetch (Cloudflare blocks it — see the Gameboost
merchant notes). Romain: *"il y a des offres steam qu'on détecte en
publisher, ça c'est seulement renseigné sur la page marchand."*

DCS and Gameboost turned out to be the **identical page-signal shape**
(token-less title, AKS page says "official platforms: Steam." only) with
**opposite ground truth** — proof that neither a Steam default nor a
Publisher default is safe for that shape. Fix: only a page that **explicitly
confirms `Direct Publisher`** resolves a token-less title anymore (unchanged
from R20/R26 for that case — Su-27 still enters PUBLISHER). Everything
short of that — Steam-only, any other non-Publisher-confirmed mix, or no
platform info at all — now **SKIPs** instead of guessing. DCS itself reverts
to skip; a human enters cases like it deliberately, matching the R19
stub-page philosophy (absent a real signal, don't guess in either direction).

`src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.4 and the aks-data-entry
skill's S31. 2 tests rewritten (skip instead of Publisher for the
Steam-only/mixed cases), 470 total, all green. The Gameboost batch (33
candidates) was cancelled before validation — nothing was submitted.

## 2026-07-15 — Admin page: human validation + supervised submit from a browser

New operator page at `https://<VPS_HOST>/executor/` (nginx HTTPS +
basic auth → loopback-only stdlib Python server, `scripts/07_admin_server.py` +
`src/admin/`). Per run: read the normalized report verbatim, approve/reject
each candidate, override platform/region/edition (choices restricted to the
run's own `session_catalog.json` — no catalog, no override), and launch
dry-run / catalog / real submit.

Invariants preserved by construction: every save regenerates the
`candidates.json` + `validation.json` + `approved.json` triple through the
real `04_validate.py check` (never a patched `approved.json`); overrides
rewrite the candidate with an `operator_override` audit field (original pick
frozen) + `operator_override`/`validation_saved` JSONL events; a real submit
spawns the unmodified `05_submit.py`, supervised to its exit code (never
fire-and-forget), one browser-driving run at a time, R24 modes with the
canary cap enforced pre-spawn, and the confirmation modal requires typing
`GO` — the operator's explicit go. Server hardening: loopback bind refusal,
per-run filename whitelist, anti-traversal run ids, custom-header CSRF guard,
log events re-passed through `redact()`. 69 new tests (454 total, green).
Install/runbook: [`../ops/INSTALL_ADMIN.md`](../ops/INSTALL_ADMIN.md).

Same-day additions (Romain): per-offer status **ajoutée / échec / en
attente** derived from the append-only JSONL log (∪ current
`submit_plan.json` — a later dry-run can't erase history; "created" is
sticky over later "not in feed" failures). Already-created offers are locked
in the UI and refused server-side at both gates (`already_created` on
validation save AND on submit start — verified live: the GameSeal 19-offer
batch with 12 created is unresubmittable as-is). Dark theme by default with
a top-right toggle (persisted). Auto-refresh every 10 s (run list, open run
via a server-state stamp, busy badge; unsaved edits are never clobbered — a
"Recharger" banner appears instead; CLI-launched submits stream their JSONL
events live). Deletion of erroneous entries (🗑 per row, "au lieu de les
soumettre"): removed from `candidates.json` at save, triple regenerated,
`candidate_deleted` JSONL event with the full payload; refused for created
offers and combined with approve/override. 470 tests green.

## 2026-07-15 — R26: token-less titles never default to Steam anymore

Live during a 100-candidate Kinguin `--submit` run (R25 already active): 6
offers in, candidate #4 (DCS: P-51D Mustang Digital Download CD Key — no
platform token in the title) had been created as Steam GLOBAL(2). Romain
flagged it live. The run was killed immediately (confirmed: exactly 6
`submit_offer` log entries, all successful, nothing further in flight).

The AKS page for DCS P-51D Mustang says "official platforms: Steam." only —
under the R20-era rule ("a defaulted Steam is trusted only when the page is
Steam-only"), that's exactly the case that keeps the Steam default. Sibling
DCS A-10C Warthog (still pending in the same batch) has the identical page
shape and would have hit the same bug. Romain: *"Si Steam, EA ou autres n'est
pas stipulé ça sera publisher pour ces offres."* Eagle Dynamics modules are
commonly sold as direct/publisher keys the page's own official-platforms
metadata doesn't enumerate — the page being "Steam-only" isn't proof the
merchant's token-less key is a Steam key.

Fix: R20's "Steam-only page → trust Steam" branch is gone. A token-less title
with *any* page platform signal now resolves PUBLISHER, unconditionally; only
a page with *no* official-platforms line at all still SKIPs (zero signal, not
a wrong default). `src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.4. 2
tests rewritten to match, 385 total, all green.

Scanning the remaining 94 pending candidates found exactly one more hit
(DCS A-10C Warthog) — re-resolved and corrected in place in `candidates.json`
(Publisher GLOBAL(1), DLC(16)) rather than a full 3663-offer re-match. The 6
already-submitted offers were removed from the pending set (already live, not
re-submitted). Validation was regenerated and the batch resumed. The one
already-created wrong offer (DCS P-51D Mustang, Steam GLOBAL(2)) needs a
manual DB correction — same remediation pattern as the Valve Complete Pack
escape (2026-07-13): Romain fixes the AKS entry by hand.

## 2026-07-15 — R25: duplicate guard against AKS's own price list

A 43-candidate Kinguin batch, matched the day before, was about to be
submitted when Romain flagged that offers matched a day earlier could already
have been added by a human working the same feed in parallel. The running
`--submit` was killed immediately (confirmed clean: zero submit-stage JSONL
log lines, no `submit_plan.json` written — it was still in its initial feed
index, no offer had been touched).

Checking candidate #5 (Darkwood, GOG GLOBAL(6), Standard(1)) against the AKS
page directly showed the real gap: the page's own price-comparison table
already listed a Kinguin price at `edition:"1", region:"6"` — the exact same
combo. This was not specific to "matched yesterday, stale by today" — the
matcher has **never** checked whether the current merchant already has a
price at the resolved region/edition, on any run, for any merchant. A
candidate only ever proved the offer was still live on the *merchant's own
feed*; it said nothing about whether AKS already had this exact price.

Fix: the AKS page's own `"prices":[…]` array (each entry carries
`merchantName`, `edition`, `region` — the same current-offers table a human
sees on the page) is now extracted at resolve time, zero extra requests, same
pattern as `editions`/`official_platforms`. A candidate whose merchant
already has an entry at the resolved region **and** edition is SKIPPED
("`<merchant>` already lists a price for this region/edition on AKS (R25)")
instead of being proposed as new.

`src/matcher.py` (`extract_prices`, `AksResolution.prices`, the R25 check in
`match_offer`), mirrored in `EXECUTOR_RULES.md` §4.7. 7 new tests (385 total,
all green). The stale Kinguin run (`20260714-180914-kinguin`) was discarded —
re-extracted and re-matched fresh with R25 active before any validation.

## 2026-07-14 — Stage 0b: login/2FA (LOGIN_SPEC.md, Option A)

A Kinguin extraction hit `NotLoggedInError`; Romain asked what it would take
to authorize the assistant to log in itself. Two options were on the table —
(A) a scripted login where the password stays in the environment and Romain
still supplies the 2FA code live every time, or (B) a stored TOTP secret for
fully autonomous login. **B was rejected**: it removes the human checkpoint on
an account that can create live offers and directly contradicts "never store
passwords or 2FA codes." Romain chose **A**.

Built per a short design doc first (`docs/LOGIN_SPEC.md`, same "propose, then
build" convention as `SUBMITTER_SPEC.md`):

- `src/login_session.py` — `LoginSession(WriteSubmitSession)` reuses the
  already-audited trusted-input primitives (`click_trusted_at_element`,
  `_type_text_trusted`) pointed at the WP login form instead of the offer
  modal; no new CDP mechanism. `run_login(...)` holds all the sequencing/
  decision logic as pure control flow over a `session` object — the fully
  unit-tested surface, mirroring `src/submitter.py`'s split.
- `scripts/00b_login.py` — CLI: invariants gate, then `AKS_WP_USER`/
  `AKS_WP_PASSWORD` from the environment only (never a CLI arg), then the
  flow.
- **2FA discipline unchanged from the skill's R0c / `SUBMITTER_SPEC.md` §8's
  pre-agreed rule**: the code is requested only once the 2FA field is
  confirmed visible and ready to submit immediately, never before.
- **One attempt each** for the password and the 2FA code, ever — no retry
  loop, anywhere, even across a second CLI invocation with the same run id
  (`StepGuard(max_attempts_per_signature=1, ...)`; tested explicitly).
- Deterministic success proof: current URL under `/wp-admin/` with no login/
  reauth marker, **and** the admin toolbar DOM node present — either alone can
  be fooled (redirect loop / cached partial page).
- Idempotent: an already-authenticated session is a no-op success, never a
  re-submit.
- Never self-triggered — a `NotLoggedInError` from another stage stays a
  fail-closed STOP + error report, exactly as before; this stage only runs on
  Romain's explicit go.
- Credentials/2FA code never logged: `RunLogger`'s existing key-name redaction
  (`password`, `otp`, `googleotp`, `2fa`, ...) already covered this, no new
  mechanism needed — and the module also never *constructs* a log record
  containing one in the first place.

`tests/test_login_session.py`, 12 new tests (378 total, all green) against a
duck-typed fake session — no CDP, no network. Mirrored in `AGENTS.md`
(refined the 2FA forbidden-list line, added a Stage 0b pointer),
`SUBMITTER_SPEC.md` §8, `EXECUTOR_RULES.md` §9, `README.md` (Requirements,
Roadmap, Safety, Rules & docs).

## 2026-07-13 — R23 P2 fixes: no bundle resurrection, no dict-order guessing

Romain's review of R23 (the page-verified edition lookup) surfaced two P2s
before they could bite live:

1. **Bundle resurrection.** The lookup didn't exclude a `Bundle`-labeled
   match. A title whose own AKS name embeds "Bundle"/"Pack"/"Trilogy" (e.g. a
   Trilogy-titled standalone product) could have the page's own Bundle-named
   entry picked up by R23 — either surfacing as a real Candidate under a
   non-`8` page id (invisible to the existing `edition_id == "8"` skip) or
   getting skipped where the offer used to pass through as Standard pre-R23.
   Fix: `edition_label == "Bundle"` now skips the page-lookup entirely and
   goes straight to Standard(1), same as pre-R23 — there is no such thing as
   a legitimate page-verified Bundle tier given the absolute "never bundles"
   rule.
2. **Dict-order guessing.** When more than one non-Standard page entry
   matched the detected label, `next(...)` silently took whichever the page
   happened to list first — not a matching criterion. Fix: prefer an exact
   (case-insensitive) name match; accept a substring match only when it is
   the sole one; multiple entries tied at the same specificity now SKIP
   ("ambiguous page-verified edition … (R23 P2)") instead of guessing.

`src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.5. 3 new tests (366
total, all green).

## 2026-07-13 — R24 (submitter): data-entry modes drive the batch size

Romain generalized R23b into a mode: once the normalized report is validated we
submit, and **`--mode` decides how much of that validated batch goes in**.

| `--mode` | Batch | Why |
|---|---|---|
| `safe` (default) | full validated batch, **no canary** (R23b) | frozen matcher; validation is already the safety gate |
| `learning` | **canary of 1** | exploring one (category × merchant) unlock |
| `advanced` | **canary of 1** | validated unlocks, same cap for now |

**`learning` is NOT a read-only observation mode** — Romain, verbatim: *"le
learning n'est pas un mode d'observation, il ajoute les offres si le rapport
normalisé est valide"*. It writes, it is simply capped. (An earlier internal
design note had it as read-only with its artefacts structurally rejected by
`04_validate`/`05_submit`; that was an over-specification and is now corrected —
no mode is rejected at validation.)

In the canary modes the cap is **enforced, not defaulted** ("tjrs un canary pour
le moment"): a `--limit` above the cap exits 2 rather than being silently
clamped; a smaller `--limit` still narrows. The mode + resulting batch size are
recorded in `submit_plan.json` (`data_entry_mode`, `limit`) and in the
`submit_report.txt` header.

**Known limitation, deliberately documented:** the matcher has no mode profiles
yet, so the mode is *declared* on the CLI and cannot be cross-checked against the
run's artefacts. When `03_match` learns to stamp a mode into `candidates.json`,
`05_submit` MUST re-verify it and fail closed on a mismatch — otherwise a run
matched under an unlock could submit as `safe` and take the full-batch path.

`scripts/05_submit.py` (`--mode`, `mode_limit()`), `manual_launch/run_executor.sh`
(now forwards `--mode` / `--limit`; `--all` kept as a warned no-op), mirrored in
`CLAUDE.md`, `EXECUTOR_RULES.md` §6, `SUBMITTER_SPEC.md` §6, `README.md`,
`NOOB.md`. 9 new tests (`test_submit_cli.py`).

Same pass, from an audit of R23/R23b: `README.md`, `NOOB.md`,
`manual_launch/run_executor.sh` and `src/submitter.py`'s docstring still promised
a canary of 1 for a plain `submit` — i.e. a beginner following `NOOB.md` expected
**1** write and would have got the **whole batch**. Corrected. The launcher also
had no way to forward `--limit`, making R23b's documented escape hatch
unreachable from the one entry point Romain actually uses; it now forwards
`--mode` and `--limit`.

## 2026-07-13 — R23 (matcher) + R23b (submitter): Valve Complete Pack escape

Live correction on a fresh Driffle run: "Valve Complete Pack (Global) (PC) -
Steam Gift" matched AKS 831, but E05 (an edition word inside the AKS product's
own name is identity, not a real edition) collapsed it to Standard(1) — the
same collapse had already mis-submitted an earlier offer of the same product
that morning (Romain deleted the bad AKS entry by hand). The page's own
editions map for 831 is `{92: "Complete Pack", 1: "Standard"}` — a real
Standard-vs-Complete-Pack split the identity heuristic can't see. **R23**:
before collapsing to Standard, check the AKS page's own editions map (already
in hand, zero extra requests) for a non-Standard entry whose name contains the
detected label; a page-verified match wins over both the identity collapse and
the generic `EDITION_HINTS` id (which wasn't even this page's own id: 91
generic "Complete" vs. 831's actual 92 "Complete Pack"). No page match →
Standard(1) as before. `src/matcher.py`.

Separately, Romain requested a standing process change: **R23b** — a
`--submit` run no longer defaults to a canary of 1 before the full batch.
Validation (`approved.json`) is already the safety gate for *which* offers
submit; the per-offer failure handling and 10-consecutive-failure stop
condition are the safety net for *how* a run behaves, and neither needs a
canary on top. `--submit` now processes the full approved batch by default;
`--limit N` still narrows it explicitly. `--inspect` keeps its own
canary-of-1 default (diagnostic mode, not asked to change). `scripts/05_submit.py`,
mirrored in `CLAUDE.md`, `SUBMITTER_SPEC.md` §6, skill `LEARNED_RULES.md` S27.

## 2026-07-08 — R22: software/apps are never candidates (games only)

Live correction on Kinguin p.2: "EaseUS Todo Backup Workstation" reached
validation as candidate #2 — real AKS page, clean Publisher GLOBAL/Standard —
and Romain rejected it: "Skip c est une app". New categorical precheck
`SOFTWARE_APP_TOKENS` (word-boundary, same mechanism as bundles/skins): app
brands (EaseUS…Adobe, VPN brands) + product categories (Internet/Total
Security, VPN, Todo Backup…, Microsoft Office/Office 20xx, Windows 10/11/
Server), reason `software/app, not a game`. Deliberate non-matches where games
exist: NERO, AVG, bare OFFICE/WINDOWS/BACKUP — which surfaced that
`CATEGORY_SKIP` substring-matched `OFFICE`/`VPN` and would skip "The Office
Quest" or "…Officer…" titles: both moved to the word-boundary list. Mirrored
in EXECUTOR_RULES §4.3 and skill LEARNED_RULES R22; suite at 352.

## 2026-07-08 — Audit 5 (P3): secondary docs de-pending-ified

README, SUBMITTER_SPEC, CONTRIBUTING and AUDIT still phrased the success proof
as "gone from pending" (README §StepGuard example, SPEC §5, CONTRIBUTING
determinism rule) — the canonical docs were already correct, but an agent
reading only a secondary doc would relearn the stale rule. All now say "gone
from the refreshed feed (same `available` mode as the run)"; legitimate
`available=pending` mentions (end-of-merchant check) untouched. SPEC §2's row
step also carried the pre-audit-3 absolute "verify title, URL, price,
merchant, page" — aligned with the routing-signal rule and URL-path fallback.

## 2026-07-08 — Audit 4 (2×P2): post-save strings carry the real available mode; submit never fire-and-forget

Romain's read-only audit after pull, two P2s. **1** — `_verify_gone` already
checked the run's `available` mode, but the written proof still hardcoded
"pending": `entry["post_save"]` said `gone from pending` / `STILL in pending`
and the CLI rendered `CREATED (gone from pending)` while the default is
`--available all` — a reader of the artifacts would believe a pending-mode
proof that never ran. Now `post_save` reads `gone from feed (available=<mode>)`
/ `STILL in feed (available=<mode>) — FAILED`, and the CLI renders the entry's
own `post_save` string instead of composing its own (single source). Docstrings
de-pending-ified. **2** — CLAUDE.md's scope-separation bullet said pipeline
stages run "including as background processes", which rubbed against AGENTS.md's
forbidden "fire-and-forget submission". Split explicitly: background OK for the
read-only stages (extract/match/report) with logs collected; submit only on
Romain's go, never fire-and-forget — attached or harness-supervised, canary of
1 by default, exit code + `submit_plan.json` read before any continuation.
Still 350 tests.

## 2026-07-08 — Guidance refresh: CLAUDE.md hard constraints, AGENTS.md aligned, success wording fixed

CLAUDE.md revision from Romain applied verbatim: explicit hard constraints
(never bypass a StepGuard block via retries/reframing/alternate tools; never
force a green invariants result in a non-authoritative environment) and a
scope-separation note (pipeline stages incl. background runs are in scope when
Romain directs data entry, `--submit` only on his go; no self-initiated batch
workers). The submit success example now reads "disappeared from the refreshed
feed (same `available` mode as the run)" — the old "pending feed" wording had
become false: Kinguin `available=pending` is empty even with 1197 rows in
`all`, so "gone from pending" would be trivially true. Same fix mirrored in
EXECUTOR_RULES §2/§6/§7/§8, and AGENTS.md's submission constraints aligned
with audit 3 (price = routing signal, page recomputed, post-save success
criterion spelled out).

## 2026-07-08 — R21: merchant URL always complete + attribute-faithful entity decoding

Romain corrected the report rule live on Kinguin page 1: "il n'y a pas que G2A
qui a des paramètres" — the old format note "G2A: keep `?params`; others:
strip" was wrong, Kinguin rows carry real params too
(`?nosalesbooster=1&currency=EUR`). Rule rewritten (R21): the merchant URL is
always reported and stored **complete, exactly as the feed carries it**, for
every merchant; the URL *path* stays an internal comparison key in the
submitter, never a rewrite. The code already kept full URLs — the real defect
was decode fidelity: `html.unescape` also decodes semicolon-less legacy
entities, mangling `&currency=EUR` into `¤cy=EUR` inside `data-offer` URLs
(a browser keeps `&curren` when unterminated in an attribute). New
`unescape_attribute` in `src/extractor.py` decodes only `;`-terminated
references; `parse_offers_payload` uses it. EXECUTOR_RULES §4.6/§8/§11 and the
skill (SKILL.md format + LEARNED_RULES R21) updated. Tests 348 → 350.

## 2026-07-08 — Audit 3: price is a routing signal, not a blocker — rule made explicit, drift surfaced

Romain's third audit, one residual point: price is compared on the by-id path
but a drift then falls through to the URL identity with `check_price=False`,
so a price difference never blocks when name + URL (+ store) confirm the row —
deliberate, but the doc rule still just said "verify title, URL, price, page,
merchant". Resolved as **behavior intended, rule clarified**: live feeds
reprice constantly between extract and submit and price is never part of what
the modal enters, so blocking on it would be pure friction with zero
protection; on the by-id path the compare's real job is to distrust a
possibly-reused id and reroute to the URL identity. Now explicit in
EXECUTOR_RULES §6 step 2, `_row_check` and `_locate_row` docstrings — and the
drift is no longer silent: a by-id contradiction that ends in a successful URL
relocation is surfaced as `id_mismatches` in the plan entry and the
`row_relocated` log line (a store_id contradiction still blocks on both
paths). Tests updated: price-drift and id-reuse relocations assert their
`id_mismatches`, clean re-import relocation asserts none. Still 345.

## 2026-07-08 — Robustness pass: CLI tests for 05_submit.py, page recompute documented, header counters, annotations

Romain's five-point robustness follow-up, now that the big gaps are closed:
**1** — new `tests/test_submit_cli.py` exercises `scripts/05_submit.py`'s
`main()` in-process (fakes for `build_report`, sessions, submitters — no CDP):
missing validation.json/candidates.json refused, tampered or fabricated
approved.json refused in dry-run AND `--submit` (with proof no session is
ever opened), invariants-red abort, a valid triple passing the gate, and the
canary default (`limit=1`). **2** — "verify page" is deliberately satisfied
by RECOMPUTING the page from the current scan (no page is stored at approval;
pagination reflows): now documented in `_locate_row` + EXECUTOR_RULES §6, and
the recomputed `page_url` is surfaced in the plan entry and the
`row_relocated` log line. **3** — `_index_feed`'s return annotation caught up
with the audit-P1 detail dicts (`dict[str, dict[str, str]]`). **4** — the
`submit_report.txt` header now shows `created=` and `write_attempts=`
explicitly in write mode (audit P2 counters), smoke-tested at the CLI level.
**5** — `Candidate` docstring + EXECUTOR_RULES §8 state that `platform:
"PUBLISHER"` is a normal candidate value (R20 revision), so operators don't
assume the classic store platforms are the whole vocabulary.
Tests: 337 → 345.

## 2026-07-08 — Audit 2 (P2): docs no longer claim an `addItem` fallback in `select_via_trusted`

`docs/EXECUTOR_RULES.md` §6 step 5 and `docs/SUBMITTER_SPEC.md` §4b still said
the trusted Selectize pick had an `addItem(id, false)` fallback for
non-rendered options. The code and tests say the opposite since the
2026-07-06 wrong-edition incident (forcing `addItem` reads the generic master
catalog and created 3 wrong-edition offers): a non-rendered id returns
`NO_OPTION` and fails closed. Both docs now state the fail-closed behavior —
the doc rule is the authority, so the stale text was a regression risk.

## 2026-07-08 — Audit 2 (P1): full row verification on the by-id path before the modal

Romain's second local audit: `_locate_row` accepted a feed row as soon as
`offer_id in index`, but the index only mapped id → page_url — title/URL were
only compared on the URL-relocation path, and `_PAGE_ROWS_JS` only surfaced
id/url/name, so price and merchant were never verified (AGENTS.md requires
"verify title, URL, price, page, merchant" before the modal). Fixed:
`_PAGE_ROWS_JS` now also extracts `price` and `storeId` from `data-offer`;
`_scan_feed` keeps full row details per id; a new `_row_check` compares name +
URL path always, store_id and price when both sides carry a value (feed ids
are import-batch-scoped and reusable, so a mismatching by-id row is treated as
stale and falls through to the merchant-URL identity instead of being
trusted). On the URL-relocation path price is deliberately NOT compared
(re-imports legitimately refresh prices; price is never entered), but a
store_id contradiction blocks. Plan entries record the verified fields as
`row_checked` for the audit trail. Tests: 331 → 337 (RowVerificationTests:
id-reuse distrust, relocation, price drift vs match, store mismatch block).

## 2026-07-08 — R20 revised: token-less keys on publisher-direct AKS pages entered as PUBLISHER, not skipped

Romain's direct rule ("Rentrons les en publisher"), same-day revision — the
same arc as R18 (first response = skip, revision = enter with the right
metadata). When a title carries no platform token AND the resolved page's
"official platforms" list contains `Direct Publisher`, the key is a publisher
key: platform PUBLISHER, region ids from the live WP-admin dropdown catalog
(identical across the 07-07 and 07-08 session catalogs): `Publisher (1)` is
the GLOBAL bucket, EU 12, US 13, UK 266; no gift mapping → publisher gifts
fail closed. Steam-only pages keep the STEAM default; empty lists still skip
(unverifiable); mixes that are neither Steam-only nor publisher-direct still
skip (reworded reason). Live: the Su-27 offer now matches as
PUBLISHER GLOBAL(1) + DLC(16) on product 4496 — exactly Romain's manual DB
correction. Tests: 328 → 331.

## 2026-07-08 — Audit fixes: submit-time re-validation (P1a), hard validity gate (P1b), split write counters (P2), AKS/Staff UA host guard (#4)

Romain's local audit, four findings, all fixed fail-closed:
**P1a** — `scripts/05_submit.py` loaded `approved.json` directly, so a stale/
edited/fabricated file bypassed the strict validation. It now re-derives the
approved set from the sibling `candidates.json` + `validation.json`
(`src/validation.py:verify_approved_against_source`, exact-match on canonical
JSON) and aborts dry-run/inspect/submit alike on any mismatch or missing
source. Live-checked on both 2026-07-08 run dirs + a real tamper (refused).
**P1b** — `fill_then_click_trusted` continued to the click when
`form_validity()` returned `ok:false` (explicit degraded mode). Unreadable
validity now hard-blocks: new `FORM_VALIDITY_UNREADABLE` status, cleanup, no
click; `FORM_INVALID` tightened to `form_valid is not True`. The old test that
asserted the degrade was rewritten to assert the block.
**P2** — the submitter's single `writes` counter counted ready attempts, not
verified creations, overstating `submit_plan.json`. Split into
`write_attempts` (drives `--limit`, conservative) and `created`
(post-save-verified); both `None` outside write mode.
**#4** — `AKS/Staff` UA is allkeyshop.com-only (Romain: "pour les requêtes sur
allkeyshop et seulement celles-ci"): `AKS_STAFF_UA` moved to `src/aks_env.py`
and `http_get` raises on any non-`allkeyshop.com` host (suffix-spoof safe);
CDP browser keeps the Chrome 149 UA. Documented in EXECUTOR_RULES §1/§5/§6.
Tests: 319 → 328.

## 2026-07-08 — R20: title-derived platform verified against the AKS page's official-platforms list

Escape reported by Romain: G2A "Su-27 for DCS World" (run 20260708-152435,
offer 93547835) was entered Steam GLOBAL(2) but the product is
publisher-direct (Eagle Dynamics) — he fixed the DB by hand. Root cause:
`detect_platform` returns STEAM as a fail-open DEFAULT when no token matches
(same pattern as the R19 edition default, one escape earlier). The AKS page's
"official platforms:" line is the only deterministic signal; it is now
extracted at resolve time (`extract_official_platforms`, zero extra requests)
and gated in `match_offer` after R19: a DEFAULTED Steam needs a page list of
exactly `Steam` (empty list or any mix → skip, distinct reasons); an EXPLICIT
title token stays trusted (multi-platform pages are normal — Osmos Steam+GoG
page, Steam key) unless the token's known page name (Steam/GoG/Epic Store) is
absent from the list — contradiction → skip. Retro sweep of all 48
created/attempted offers across 27 AKS pages: Su-27 is the only platform
damage ever. Live check: Su-27 page → skip (R20); Frog Sqwad
(Steam+Xbox Play Anywhere page, explicit "Steam" title) → still a candidate.
Skill LEARNED_RULES R20 added + mirrored here. Tests: 307 → 319.

## 2026-07-08 — R19: empty editions map = stub AKS page → SKIP (edition unverifiable)

Escape reported by Romain: G2A "DCS: A-10C Warthog" (run 20260708-125905)
was submitted Standard(1) but is a DLC — he fixed the DB by hand. Its AKS
page is a stub (`"merchants":[],"editions":[],"prices":[],"regions":[]`,
zero offers): R18 had no DLC bucket to read and the title/slug carry no DLC
token, so the edition fell through to the Standard default — fail-open.
Sibling "DCS: P-51D Mustang" (populated map, DLC bucket) went in correctly
as DLC(16) in the same run. Sampling 25 candidate pages across G2A/K4G/
Driffle runs: 23 have a populated map (mono-edition pages still show
`1:Standard`); the 2 empty ones split one hidden DLC (A-10C) / one legit
standalone (K4G "Goblin Vyke") — emptiness cannot decide an edition either
way. `match_offer` now skips empty-map resolutions with a distinct reason
("AKS page carries no editions map — edition unverifiable (R19)") before the
R18 check; stub pages serialize the map as PHP `"editions":[]`, which the
object-only `extract_editions` already reads as `{}`. Trade-off: legit
standalones on stub pages (Goblin Vyke) are now skipped and stay visible in
`skipped.json` for manual entry. Skill LEARNED_RULES R19 added + mirrored
here. Tests: 303 → 307.

## 2026-07-08 — Submit: URL relocation keys on the path (G2A `uuid=` param drift)

Pre-submit check on the G2A go: 0/716 common products kept their offer id
across 24 h (second merchant confirming import-batch-scoped ids), and the
FULL merchant URL was only 96.4 % stable — the `?uuid=` param rotated on
26/716 rows while the URL path held 716/716 (and is unique in-feed for both
G2A 741/741 and K4G 250/250). Full-URL keying would have mis-skipped drifted
rows ("not in current feed") and, worse, could prove a false "gone from
pending" when a mid-run re-import rotates id + uuid together. `_url_key`
(path, params stripped) now keys `by_url`, `_locate_row` and the
`stop_on_url` disappearance probe. Report format unchanged (G2A candidate
URLs keep their params for Romain's links). Tests: 301 → 303 (param-drift
relocation + worst-case false-disappearance veto).

## 2026-07-08 — R18 revised: DLC bucket = candidate with edition DLC(16), not a skip

Romain's direct rule ("quand on a DLC … sur la page produit AKS on ajoute ça
en édition DLC, on ne skip pas") replaces the same-day skip below: the DLC
bucket on the resolved page states the product's NATURE, and the right entry
is the offer with edition DLC(16) — never Standard, even with a coexisting
Standard bucket. The page-nature override beats every title hint (E0x) and
the bundle-resolution guard ("Pack"/"Deluxe" in a DLC's own name is identity).
Bundle/Early Access buckets remain non-blocking and non-overriding. Skill R18
rewritten + `.hermes` synced; EXECUTOR_RULES: clause moved out of §4.3 (skip
list) into §4.5 (edition detection). Tests: 295 → 300 (net; suite also gained
the submit relocation tests below).

## 2026-07-08 — Submit: rows re-located by merchant URL across feed re-imports

First K4G write session failed 0/10 fail-closed ("offer not in current
feed"): AKS re-imported the feed between extraction (08:13) and submit
(09:26) and re-id'd EVERY row — 0/212 ids survived, while the merchant URL
stayed stable AND unique for all 212. `_scan_feed` now also builds
url → current row; a candidate absent by id is re-located by URL with an
exact-title check (fail-closed on drift), adopts the row's current id (logged
`row_relocated`), and the post-save disappearance proof requires the offer
gone under BOTH keys — id-only would false-positive "gone" whenever a
re-import rotates ids mid-run. Second pass created the canary (GUILTY GEAR
Xrd, relocated 93483480→93504363, gone from pending) with 3 correct
absent-by-both-keys skips.

## 2026-07-08 — Matcher: DLC bucket on the AKS page = skip (R18)

Romain's review of the first K4G candidate list (2026-07-07) caught 9 add-on
contents ("Exoplanets Pack", "Janthir Wilds Expansion", "Supporter Pack", …)
proposed as Standard(1): their titles carry no "DLC" word and match their own
AKS product pages token-perfectly, so R01/R16/R01b all stay silent. The
resolved page's editions map is the truth about the product's nature —
`match_offer` now skips whenever it contains the DLC bucket
(`_dlc_edition_on_page`: id 16, name-match "DLC" as the seatbelt if ids ever
move), even when a Standard bucket coexists ("Brotato: Abyssal Terrors" has
both and is still a DLC). Deliberately NOT extended to Bundle/Early Access
buckets: those describe other offers listed on the page, not the product
("GUILTY GEAR Xrd -SIGN-" {Standard, Bundle} and the Early Access indies were
valid candidates). Zero extra requests — the map was already extracted at
resolve time. Skill LEARNED_RULES R18 mirrored in EXECUTOR_RULES §4.3/§4.7.
Tests: 292 → 295.

## 2026-07-07 — Matcher: trailing-suffix slug peeling (K4G grammar)

First K4G run (226 offers) yielded 0 candidates: 95/226 fell in "no AKS
product page found" because `build_slug_candidates` only stripped parens and
dash-split the head — useless against K4G's separator-less `<Product>
[Edition] [Region] <Platform> CD Key` grammar, and the dash-split silently
amputated real dashed names ("Endless Space - Disharmony" → "endless-space",
a G2A-affecting bug too). Fix in `src/matcher.py`:

- `_strip_trailing_phrases` + `_TRAILING_NOISE_PHRASES`: iteratively peel
  end-anchored platform/region/format phrases (longest-first, word-boundary,
  case-insensitive). Bare `US`/`EU` deliberately excluded ("Among Us");
  `ORIGINS` ≠ `ORIGIN` by boundary.
- `build_slug_candidates` now tiered, most specific first: (1) full
  suffix-stripped name (keeps dashed subtitles), (2) + trailing edition words
  stripped (`_TRAILING_EDITION_PHRASES` = EDITION_HINTS vocab minus
  BUNDLE/PACK/TRILOGY/DLC), (3) legacy dash-split head (Driffle/G2A grammar).
  Over-stripping costs one probe; wrong-page 200s stay caught by R01 +
  extra-words guards.
- `NOISE_TOKENS` += CONNECT/GAMES/LAUNCHER/STORE so correct resolutions are
  not skipped as "different/expanded product" on storefront leftovers.
- `extract_aks_name`: (a) `html.unescape` — `Exile&#039;s` tokenized to
  EXILE/039/S and `&amp;` to AMP, falsely failing R01 on real matches; (b) AKS
  serves a second og:title grammar (`FIFA 21 PC KEY Compare Prices` — no Buy,
  no CD Key) → also split on "Compare Prices" and strip the trailing
  `PC KEY`/`PC` platform marker (bare trailing "Key" kept: "The Key" is a
  real name). Both grammars probed live before fixing.
- K4G note added to EXECUTOR_RULES §11. Tests: 285 → 292.

## 2026-07-07 — Second-pass audit of `src/submit_session.py`

The dedicated audit Romain requested (130 → 1204 lines). Full report appended
to [`AUDIT.md`](AUDIT.md). Verdict: **no P0/P1** — S02/S09/S10 compliant,
fail-closed guards wired and pinned by ~45 tests; the size is inline JS probes
+ incident-history docstrings, not rot. One drift fixed in the pass (SS1: the
module docstring still claimed "the create capability literally does not exist
here" while `WriteSubmitSession` lives in the same file). Six P2 notes filed
(tap leak on mid-flow exception, residual `PREPARED` status, scroll-logic
duplication, `CLICK_MODES` naming, `_press_enter` keypress gap → check on the
P4 canary, no `CSS.escape`) — candidates only if the file is reopened; no
refactor of the frozen, live-proven mechanism.

## 2026-07-07 — Chantier n°2: page-par-page + pacing humain

Invited by Romain's audit ("le prochain incrément logique") now that the
creation mechanism is frozen and live-proven. Addresses the burst / IP-ban risk
on large volumes: the true bursts were the submitter's full-feed `_scan_feed`
walks (index build + re-walk after **every** creation for post-save verify) and
the extractor's multi-sweep walks (e.g. G2A: 27 pages × ≥2 sweeps) — the old
0.5 s inter-offer pause was negligible against those.

- `src/pacing.py` (new) — `Pacer`: bounded-random `uniform(min,max)` waits,
  injectable rng/sleeper (tests never sleep), aggregate counters
  (`waits`, `total_waited_s`) logged once per run via `snapshot()`.
  `parse_pace_spec("0" | "3" | "2-5")`. Never a correctness mechanism —
  settle waits stay separate.
- `src/extractor.py` — paces before every page fetch after the first (both
  modes). New `extract_pages(first_page, last_page)` slice mode: fetches only
  the requested pages, once; result **always `partial: true`** (a slice never
  claims coverage — no sweeps, no `FeedUnstableError`); same fail-closed
  classification (login bounce, blank in-range page); reports `feed_last_page`
  so the operator plans the next slice.
- `src/submitter.py` — `page_pacer` between feed-scan page loads, `offer_pacer`
  between offers (skips offers not actually processed in write mode). The old
  `pace: float = 0.5` run() kwarg is removed. Engine stays neutral: pacers
  default to `None`; the CLIs are the opinionated layer.
- CLIs — `02_extract_feed.py`: `--pace` (default `2-5` s) and `--pages 3` /
  `--pages 3-5`; `05_submit.py`: `--pace-pages` (default `1-3` s),
  `--pace-offers` (default `5-15` s). `0` disables any of them.
- Tests: 260 → 285 (pacing unit tests, slice-mode extraction incl. past-end /
  empty-queue / blank-anomaly / dedupe / guard signatures, pacer wiring in
  extractor + submitter).

## 2026-07-07 — Invariant gate hardened: `no_openvpn_process`

A live audit found a Surfshark `openvpn` daemon running as root (no tun device,
so AKS direct still worked) — a tunnel coming up mid-batch would flip the egress
IP under an authenticated AKS session. The "VPN forbidden while AKS direct
works" rule was only enforced by the shell audit, not by the authoritative gate
that unlocks write stages.

- `src/aks_env.py` — pure `validate_no_openvpn(pids)` (fail-closed: `None` =
  undeterminable state = FAIL) + read-only `list_openvpn_pids()` probe
  (`pgrep -x openvpn`, same match as the shell audit).
- `src/invariants.py` — third StepGuard probe `openvpn_process` in
  `build_report`; check joins the fail-closed aggregate and the report gains an
  `openvpn` section. Guard consecutive-failure limit sized above the probe
  count so a fully-red environment still emits the JSON report instead of
  raising mid-build.
- Doc drift fixes from the same audit: README roadmap now checks off the
  implemented post-save verifier; `00_audit_env.sh` openvpn FAIL reworded.
- Tests: 251 → 260.

Effect on the VPS today: the gate is **red + authoritative**
(`no_openvpn_process` FAIL, pid 1819) until the daemon is stopped — write
stages stay locked, by design.

## 2026-07-06 — S18 RESOLVED: `offer[targets][]` fill → first live submissions

The Selectize-humanisé fix (2026-07-03) made region/edition valid but the form
still would not submit: a trusted click on "Create offer" fired **zero**
admin-ajax. A read-only probe (`probe_targets_field` / `_TARGETS_PROBE_JS`)
isolated the last empty `required` field — `offer[targets][]`, a bare
`<input type="text" required pattern="(\d+)|(https?://.+)">` with a sibling
"add" button (a chip/array field). It wants the **AKS product id** (numeric) or
an http(s) URL — both already on every candidate (`aks_product_id`, `aks_url`).

**Fix — fill `offer[targets][]` in the trusted path, before the validity gate:**

- `src/submit_session.py` — new `add_target_trusted(value)`: trusted CDP click to
  focus the field, `Input.insertText` to type the value, then commit via the
  **adjacent add-button** (trusted click) with a trusted-Enter (`_press_enter`,
  keyCode 13) fallback. Read-only readback (`_TARGETS_READBACK_JS`) confirms the
  input went `valid:true`. Wired into `fill_then_click_trusted(...,
  target_value=...)` as step 4, **before** the HTML5 validity gate.
- `src/submitter.py` — threads `candidate.aks_product_id` through `_prepare` →
  `_process` → `target_value` (cleanest value, matches `\d+`).
- **HTML5 validity gate is now a hard gate** (`form_validity()` /
  `_FORM_VALIDITY_JS`): if the `<form>` is still invalid after region + edition +
  target, the submitter returns a deterministic `FORM_INVALID` verdict and does
  **not** click — no ambiguous "click ignored", no wasted admin-ajax.
- `--click-mode` now **defaults to `trusted`** (the only mode proven to fire
  Driffle's handler); `native`/`dispatch` kept only as documented diagnostics.
- `scripts/05_submit.py` — report now prints `target_add=` (status/commit/value/
  readback) and `form_valid=`/`invalid_required=` per offer.

**First live-confirmed submissions (Romain-triggered `--submit`).** A canary of 1
(offer 93185190 **Demigod**, Steam EU(9)/Standard(1), run
`20260706-161225-driffle`) succeeded end-to-end: target filled
(`valid:true`), `form_valid:true`, trusted click → **admin-ajax
`…do=create_offer` → 200**, server signal `"[product 2101] Offer created for
locale en_EU and merchant 408"`, and — the only authoritative proof — **gone
from the refreshed pending feed** `[S18]`. We do **not** issue a direct XHR; the
trusted click drives the modal's own `create_offer` and we merely *observe* the
resulting request as a corroborating signal.

**First scaled batch** (run `20260706-162745-driffle`, `--limit 100
--available all`, 4 approved): **3 created** — Gambonanza, Hello Neighbor 2,
Heart of the Machine (all Steam EU(9)/Standard(1), all gone from pending). **1
clean fail (new Layer-5, server-side):** Serious Sam HD Double Pack
(GLOBAL(2)/Bundle(8)) — region/edition picked, form **valid**, target filled,
yet `create_offer` returned `Bad request: paramètre "offer" manquant ou
invalide`. Fail-closed caught it (status=ERROR → not submitted, no false
success, batch continued). This is **not** a regression — expect some
bundle/non-Standard offers to reject server-side even when the form is valid.

**190 tests green.** Commits `41c6bb5` (target fill) + `12fd2ec` (validity gate,
probe, default trusted).

## 2026-07-03 — Chantier n°1 extension: Selectize humanisé (no more `setValue`)

Canary #4 (FRACT OSC, offer 92625611) with `--click-mode trusted` proved the
trusted click LANDS on the correct button (`element_at_center.is_button: true`,
`button_style.pointer_events: auto`) — yet still `requests: []`. Enriched
`--inspect` probe revealed the real blocker: **`form_all_inputs_valid: false`**.
Three `required` text inputs are empty at click time:

- `offer[targets][]` — a real named data field, never filled by our setValue path.
- Two anonymous `<input type="text" required>` inside Selectize wrappers whose
  `parent_class` is `selectize-input items required invalid not-full has-options`
  — Selectize's own UI text input inherits `required` from the underlying
  `<select required>`, and stays empty when the value is set via `.selectize.setValue()`
  because that's a programmatic setter, not a real user interaction.

Consequence: HTML5 form validation blocks the `submit` event before any
handler fires. No handler ⇒ no XHR ⇒ `requests: []`.

**Fix — Selectize humanisé** (Chantier n°1 extension, authorized Romain 2026-07-03):
replace `setValue` with a trusted CDP click on the `.selectize-input` (opens
dropdown), wait 250 ms, trusted CDP click on `.selectize-dropdown-content
.option[data-value="{id}"]` (selects). Same handler chain as a real operator —
Selectize's own event listeners fire, likely populating `offer[targets][]` as
a side-effect. Still no `.click()`, no `dispatchEvent`, no `form.submit()`,
no XHR, no `setValue`. **169 tests green.**

- `src/submit_session.py` — new `select_via_trusted(select_name, value_id)`:
  reads `.selectize-input` rect (S02-safe `_SELECTIZE_INPUT_RECT_JS`),
  trusted CDP click at its center, 250 ms settle, reads
  `[data-value="{id}"]` rect (S02-safe `_SELECTIZE_OPTION_RECT_JS`,
  requires the dropdown visible), trusted CDP click, 200 ms settle,
  reads back `select.value` + `select.selectize.getValue()` + `select.validity.valid`
  (`_SELECTIZE_READBACK_JS`). All events `isTrusted: true`.
- `src/submit_session.py` — refactored the mousedown/dwell/mouseup sequence
  into a private `_trusted_click_at_rect(rect)` helper; `click_trusted_at_element`
  and `select_via_trusted` both use it. No behavior change for the button click.
- `src/submit_session.py` — `_TRUSTED_PREP_JS` no longer calls `setValue`;
  it only installs the network taps + captures pre-existing signal counts + texts
  + button visibility. `_TRUSTED_POLL_JS` now accepts a text CHANGE on an
  existing `[data-success]`/`[data-error]` template node as a valid ACK (Driffle
  updates a pre-existing `<p data-success>` textContent instead of adding a
  node — the previous "new node only" guard would have missed it).
- `src/submit_session.py` (`_INSPECT_MODAL_JS`) — enriched:
  `element_at_center` (`elementFromPoint` at button center), `button_style`
  (pointer_events / z_index / opacity / visibility / display), `form_inputs`
  (name / type / required / value_len / visible / willValidate / validity /
  parent_class), `form_all_inputs_valid`. Read-only, S02-safe.
- `src/submitter.py` — `Submitter._process` unchanged interface; still routes
  to `fill_then_click_trusted` when `click_mode='trusted'`. The internal
  orchestration now uses select_via_trusted twice + click_trusted_at_element.
- Tests: +6 (SelectViaTrusted 4 tests: success chain reads/clicks/readback,
  no_input early-out, no_option after open, S02 guard on the 3 new probes;
  FillThenClickTrusted +3: full success chain merges prep+picks+click+poll,
  region-pick failure triggers cleanup, edition-pick failure triggers cleanup).

**S09 dérogation étendue (2)** : la couche de synthèse trusted couvre maintenant
non seulement le clic sur "Create offer" mais aussi les interactions Selectize
UI (open dropdown + pick option). Toujours aucun `form.submit()`, aucun XHR,
aucun clavier synthétique. Post-save reste juge.

**Next diag** on the VPS (approved.json still points at offer 92625611):

```
python3 scripts/05_submit.py runs/driffle-canary-trusted-1625/approved.json \
    --merchant Driffle --store-id 127 --submit --click-mode trusted
```

Grille :
- `region_pick.status: SELECTED` + `readback.selectize_value` == region_id + `validity_valid: true` → Selectize UI clic OK.
- `requests: [POST admin-ajax.php … -> 200]` + offer gone from pending →
  **Chantier n°1 + Selectize humanisé confirmés**, gel du mécanisme.
- `region_pick.status: NO_OPTION` → dropdown open ok mais l'option n'était pas
  encore rendue (timing) → augmenter le settle post-open ou attendre
  `[data-value]` avant lecture rect.
- `requests: []` **encore** → épuisé les hypothèses connues, on ouvre DevTools
  live pour `getEventListeners(document)` sur la page pending.

## 2026-07-03 — Chantier n°1: `--click-mode trusted` (CDP `Input.dispatchMouseEvent`)

Canary #3 (Driffle) confirmed the S18 root cause: both `native` (`.click()`) and
`dispatch` (MouseEvent) produced `requests: []` with a visible, enabled Create
button. Driffle's handler almost certainly checks `event.isTrusted`, which is
`false` for any DOM-synthesized event. `Input.dispatchMouseEvent` is the only
CDP path that yields `isTrusted: true` — it's what a real desktop operator's
mouse produces. **163 tests green.**

- `src/submit_session.py` — new `click_trusted_at_element(selector)`:
  reads target rect + viewport via `evaluate_readonly` (S02-safe `_RECT_JS`);
  if outside viewport, sends one `Input.synthesizeScrollGesture` (mouse source,
  speed 800), waits **500 ms** for settle, re-reads rect; then
  `Input.dispatchMouseEvent` sequence `mouseMoved(cx,cy)` →
  `mousePressed(cx,cy,left,clickCount=1,buttons=1)` → **random 40-90 ms** dwell
  → `mouseReleased(cx,cy,left,clickCount=1,buttons=0)`. No `.click()`,
  no `dispatchEvent`, no `form.submit()`, no XHR, no keyboard.
- `src/submit_session.py` — new `fill_then_click_trusted(...)`: 2-phase orchestration.
  `_TRUSTED_PREP_JS` fills selectize + installs network taps
  (`window.fetch` / `XMLHttpRequest` wrapped into `window.__s18taps`) + records
  `pre_existing` counts + returns button state; CDP trusted click follows;
  `_TRUSTED_POLL_JS` waits for a NEW `[data-success]`/`[data-error]` node
  (pre-existing guard), reports `requests`/`polls`/`signal`, and restores the
  taps. `_TRUSTED_CLEANUP_JS` restores taps if the click cannot fire (rare).
- `src/submitter.py` — `Submitter` routes to `fill_then_click_trusted` when
  `click_mode='trusted'`; `fill_and_create` unchanged for `native`/`dispatch`.
  `ALL_CLICK_MODES = ('native','dispatch','trusted')` validated at `__init__`
  (`ValueError` on unknown). Post-save (offer gone from refreshed pending) is
  **strictly unchanged** and remains the ONLY success proof in every mode.
- `scripts/05_submit.py` — `--click-mode` accepts `trusted`; the text report
  prints one `trusted_click:` line with click coords + delay_ms + scrolled +
  viewport + rect + click status.
- +12 tests (trusted click sequence order, in-viewport vs out-of-viewport paths,
  scroll gesture params, element-disappears-after-scroll edge, `_RECT_JS`
  read-only guard, `fill_then_click_trusted` merges prep+poll on success,
  cleanup called on `NO_ELEMENT` click, `Submitter` refuses unknown
  `click_mode`, trusted-mode success + still-pending failure).

**S09 derogation étendue** (Romain, autorité n°1, 2026-07-03) : le bouton
officiel visible reste **la seule cible** ; seule la couche de synthèse
d'événement change (DOM → input CDP). `form.submit()` / XHR direct / clavier
synthétique **restent interdits**.

**Next diag on the VPS**:

```
python3 scripts/05_submit.py runs/<id>/approved.json \
    --merchant Driffle --store-id 127 --submit --click-mode trusted
```

Grille de lecture :
- `requests` contient un `POST /wp-admin/admin-ajax.php … -> 200` **et** offre
  disparue du pending → **succès Chantier n°1 confirmé**, gel du mécanisme.
- `requests` avec un 4xx/5xx → handler atteint mais rejet serveur (nonce,
  merchant id, payload) — nouvelle piste, voie DOM restée saine.
- `requests: []` **encore** → hypothèse trusted à revoir (rare : le handler
  écoute autre chose qu'un click, ex : sur le form via `submit`).

## 2026-07-03 — S18 investigation: `--inspect` modal DOM probe (read-only)

Canary #3 (Driffle) with the pre-existing signal guard active produced
`requests: []` + `status: NO_SIGNAL` in **both** `native` and `dispatch` click
modes: the click reaches no handler that fires an admin-ajax request. Prime
suspect now: the `.button-primary` sniper matches an element that has no
handler bound (WP admin `<a href="#">`, or a delegated listener not rebound
after the ThickBox AJAX load). Read-only DOM probe added to identify the
true submit-trigger element and its form, without clicking Create.

- `src/submit_session.py` — new `_INSPECT_MODAL_JS` + `SubmitSession.inspect_modal_dom()`:
  read-only probe returning `{ button: {tag, type_prop, type_attr, id, klass,
  href, name, text, data_attrs, path}, button_count_in_modal, form: {tag, id,
  klass, action, method, onsubmit_attr}, forms_in_modal, forms, modal_selects,
  data_success_in_modal[…], data_error_in_modal[…], data_success_in_doc,
  data_error_in_doc, tbwindow_style }`. Passes the S02 mutation guard (no
  click/submit/fetch/setValue/dispatchEvent).
- `src/submitter.py` — new `InspectSubmitter` (write_mode=False, event_name
  `inspect_offer`): reuses `_index_feed` / `_prepare` and calls
  `inspect_modal_dom` on each ready entry. No clicks on Create, no writes.
- `scripts/05_submit.py` — new `--inspect` flag (mutex with `--submit`; canary
  of 1 by default, `--limit N` / `--all` to widen). Writes `modal_inspection.json`.
- +6 tests (inspect flow, JSON parsing, S02 read-only guard on the probe JS).

**Next diag** on the VPS:

```
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle \
    --store-id 127 --inspect
```

Then inspect `runs/<id>/modal_inspection.json`. Reading grid:
- `button.tag=A` + `href='#'` → the real trigger is elsewhere (jQuery delegated
  handler somewhere up the DOM path); look at `button.data_attrs` for hints.
- `form.action` non-vide → soumission `<form>` classique ; le vrai geste est
  peut-être un `form.submit()` intercepté (S09-forbidden — regarder `data_attrs`
  et `onsubmit_attr`).
- `button_count_in_modal > 1` → on ciblait le mauvais bouton depuis le début.

## 2026-07-03 — S18 investigation: network taps + dispatch click mode (derogation)

Live canary #2 (Driffle) eliminated hypothesis #1: the selectize readback proved
`setValue` took perfectly (`region_set=9`, `edition_set=1`, options exact) — yet
`[data-success]` appeared with an **empty** signal text and the offer stayed in
pending. Prime suspect: a pre-existing (template/hidden) `[data-success]` node
being mistaken for the AJAX ack, and/or the native `.click()` not firing Driffle's
real submit handler. **144 tests green.**

- `src/submit_session.py` — `_FILL_CREATE_JS` instrumented:
  - **pre-existing signal guard**: `[data-success]`/`[data-error]` nodes are counted
    BEFORE the click; the poll only accepts a **new** node (count increased) —
    otherwise it ends `NO_SIGNAL`. `polls` + `pre_existing` land in the diag.
  - **network taps** (diagnostic only): `window.fetch` + `XMLHttpRequest` are wrapped
    around the click and restored after; the diag reports `via/method/url/status`
    for every request the click fired — never bodies, never headers/cookies. An
    empty `requests` list = the click never reached the network.
  - **button state** (`disabled`/`visible`/`text`) recorded pre-click.
  - **`click_mode='dispatch'`** — full `mousedown/mouseup/click` MouseEvent sequence
    **on the Create button ONLY**. This is an explicit, documented derogation from
    the S09 no-`dispatchEvent` rule, **authorized by Romain (2026-07-03, authority
    order #1)** after the native click was proven not to persist on Driffle. Still
    no `form.submit()`, no XHR submission; unknown modes raise (fail-closed).
- `src/submitter.py` — `Submitter(click_mode=...)` passes the mode through; the
  post-save feed check remains the ONLY success proof, unchanged, in both modes.
- `scripts/05_submit.py` — `--click-mode {native,dispatch}` (native default,
  refused without `--submit`); the text report now prints polls / pre_existing /
  button state and one `net:` line per captured request.
- +4 tests (dispatch pass-through, dispatch still fails when still-pending, native
  default, unknown mode refused).

Also today (infra, no code): AKS dropped the VPS IP at TCP level (curl `000`,
google OK, DNS OK, AKS up from elsewhere) — the documented skill pattern "AKS
bloque les IPs après un burst". Resolved by Romain via the skill's Surfshark
targeted-route rotation (`de-fra` TCP, `--route-nopull --route 176.31.53.220`);
invariants back green+authoritative. Known doc drift to resolve: `00_audit_env.sh`
still FAILs when an openvpn process runs — decision pending on wording it as
"forbidden when direct works / tolerated targeted-route when AKS drops the IP".

## 2026-07-02 — Stage 4: real submitter (WRITES, canary-first)

The real write path — approved by Romain, and validated end-to-end in **dry-run on
the VPS first** (modals open; Driffle selects are `offer[region]`/`offer[edition]`;
Battle.net Gift region resolves to 570). **138 tests green.**

- `src/submit_session.py` — `WriteSubmitSession(SubmitSession)` adds the ONE mutating
  op, `fill_and_create`: `selectize.setValue` on the verified select names, then
  click `#TB_ajaxContent .button-primary` (Promise + 500 ms; skill S09/S17/S19). No
  XHR, no `dispatchEvent`, no `form.submit()`.
- `src/submitter.py` — `Submitter` (real): `fill_and_create`, then **post-save
  verification** — re-scan the feed; `success = the offer disappeared from pending`
  (never `[data-success]`; skill S18). Shares its base flow with the dry-run.
- `scripts/05_submit.py` — `--submit` writes; **canary default = 1 offer**, `--all`
  for the full batch, `--limit N` otherwise. Gated on green + authoritative invariants
  + pre-flight login; one attempt per offer, skip + continue, stop after 10 consecutive.
- 5 tests (canary stops after 1, full batch, still-present = failure, unconfirmed
  click = failure, not-ready never writes).

First real run (canary):
`python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit`

## 2026-07-02 — Stage 4: submitter (DRY-RUN only, no writes)

The submit flow, dry-run only — **no writes**. **132 tests green.** Approach
approved by Romain (`docs/SUBMITTER_SPEC.md`).

- `src/submit_session.py` — `SubmitSession` (extends the read-only CDP session):
  list a page's offer ids, open an offer's modal, read the modal context, detect the
  WP login page. **No method fills a form or clicks "Create offer"** — the create
  capability does not exist in this build.
- `src/submitter.py` — `DryRunSubmitter`: pre-flight login check, locate the exact
  current row, open the modal, verify context + select names, report what it *would*
  submit. Per Romain's decisions: one attempt per offer; on failure log + skip +
  continue; stop the run after **10 consecutive** failures (StepGuard).
- `scripts/05_submit.py` — `--dry-run` (default), gated on green + authoritative
  invariants; `--submit` is **refused** (write path not built). Writes
  `submit_plan.json` + `submit_report.txt`.
- 7 tests (login abort, ready plan, skips, select-name conventions, stop-after-10).

Run on the VPS: `python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127`.

## 2026-07-02 — Stage 3: validation gate

Read-only validation — the fail-closed gate before any submission. **125 tests green.**

- `src/validation.py` — `validation_template` (operator fills approve + who/when)
  and `load_validation`, which verifies a filled file against the CURRENT
  candidates: `run_id` must match, `validated_by`/`validated_at` required, and every
  approved entry must be an exact current candidate by fingerprint
  (`offer_id|aks_product_id|region_id|edition_id`) — a re-match that changes a
  region/edition invalidates a stale approval (skill S15). Any problem rejects the
  whole file (never partially honored).
- `scripts/04_validate.py` — `template` writes `validation.template.json`; `check`
  verifies a filled `validation.json` and writes `approved.json`. Read-only.
- 9 tests. This approval is the lock the future submitter will require — no
  submission is possible without it.

## 2026-07-02 — Sprint 3: read-only matcher

The matcher stage is built (read-only). **Suite: 109 tests green.**

- `src/matcher.py` — ports EXECUTOR_RULES §4: apostrophe-normalized tokenizer,
  R01 strict name match, R01b dangerous-qualifier guard, categorical SKIP lists
  (console, forbidden region, currency/gift/sub, DLC, bundle, language
  restriction), platform + region (URL-first) + edition detection, AKS slug build
  + read-only resolve (`data-product-id` + editions), cap 100. `Candidate` +
  `SkippedOffer` dataclasses; `normalized_block` emits the skill's exact report
  format (`#N — … / 🎯 id — name / 🔗 url / 🎯 aks-url / Platform REGION(id), Edition(id)`).
- `scripts/03_match.py` — reads `offers.json`, resolves candidates against AKS
  (read-only GET), writes `candidates.json` + `skipped.json` + a normalized-text
  `report.txt` (no tables). Aborts if AKS is unreachable.
- 33 tests. Forbidden-region short tokens (NA/OTHER/SEA) excluded to avoid title
  collisions ("Sea of Thieves"); candidates are human-reviewed before any submit.
- Hardened from the first live Driffle run (272 → 5 candidates): added the
  different/expanded-product guard (≥2 extra significant words, or an extra version
  number → SKIP — e.g. GreedFall "The Dying World" ≠ base GreedFall) and Gift
  region detection (Steam 25/259, Battle.net 570/567). Re-validated: 5 → 3 clean
  candidates.

Run on the VPS: `python3 scripts/03_match.py runs/<run_id>/offers.json`.

## 2026-07-02 — Sprint 2: read-only feed extractor

The extractor stage is built (still strictly read-only). **Suite: 83 tests green.**
Unblocked by the VPS invariant gate going green + authoritative.

- `src/cdp_session.py` — stdlib raw-socket CDP session adapted from the skill's
  proven transport (no Origin header → avoids the Docker-terminal 403). Exposes
  only `navigate` + `evaluate_readonly`; refuses mutation-looking expressions
  (`.click(`, `dispatchEvent`, `setValue`, `admin-ajax`, `fetch(`…). Never clicks,
  fills, or submits. Zero new dependencies.
- `src/extractor.py` — `feed_url` (pagination `&p=N`), `parse_offers_payload`
  (`html.unescape` + `json.loads`, skill rule F05), paginated extraction through
  the StepGuard, dedupe-by-id → `RawSnapshot` + `NormalizedFeed`, logged via
  `RunLogger`.
- `scripts/02_extract_feed.py` — CLI that **refuses to run unless invariants are
  green AND authoritative**, then writes `runs/<run_id>/raw.json` + `offers.json`.
- 11 tests (feed URL, payload/entities, pagination/dedupe/stop rules, guard
  wiring, read-only refusal). The live CDP path runs on the VPS.

Run on the VPS: `python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127`.

## 2026-07-02 — P2 debt cleanup

Closed the P2 findings from `AUDIT.md`. **Suite: 72 tests green.**

- **C4 — StepGuard limits decoupled.** A new `max_failures_per_signature`
  (hard-block threshold) is distinct from `max_attempts_per_signature` (the
  pre-execution attempt ceiling); the success-then-failure asymmetry is now
  explicit and tested.
- **C5 — one blocked-decision builder.** `check()` and `run_step` both use
  `_blocked_decision(signature)`, preserving the real signature.
- **C6 — CDP client fails closed without probing** a non-official endpoint (no
  network I/O when the endpoint check fails).
- **S3 — audit config excerpt whitelisted.** `00_audit_env.sh` greps only
  `docker_extra_args`/`container_persistent`/`network` instead of dumping 20 lines
  of the Hermes config into the report.
- **T5 / T6 — coverage.** `current_environment` override logic and StepGuard edge
  cases (success-then-failure, blocked decision, record-while-blocked, snapshot
  counters) are now tested (+8).

Remaining: **S2** — delete the stale gitignored `runs/audit_2026-07-01` artifact
locally (the sandbox mount can't unlink it).

## 2026-07-02 — Sprint 2 foundations (G2, G3)

Closed the remaining pre-Sprint-2 gaps from `AUDIT.md`. **Suite: 64 tests green.**

- **G2 — data contracts** (`src/contracts.py`): `RawSnapshot`, `NormalizedOffer`,
  `NormalizedFeed` frozen dataclasses with stdlib validators (fail-closed
  `ContractError`), dedupe-by-id, `to_dict`. The enforced JSON shapes for the
  extractor's output — see [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md).
- **G3 — JSONL run logger** (`src/run_log.py`): append-only `logs/<run_id>.jsonl`
  with recursive secret redaction (never logs `webSocketDebuggerUrl`, cookies, or
  2FA) and `log_guard(...)` to persist a StepGuard snapshot per task.
- Docs: added `DATA_CONTRACTS.md`; +20 tests for the two modules.

The read-only extractor (Sprint 2) that produces these artifacts still waits on
green VPS invariants before it is built.

## 2026-07-02 — P1 audit remediation

Closed the P1 findings from `AUDIT.md`. This hardens the read-only Sprint-1
foundation and its tests; there is no write path yet, so no runtime behavior
changed for submissions. **Test suite: 44 green (was 28).**

### Correctness & fail-closed
- **C1 — the two gates now probe AKS identically.** The shell audit
  (`scripts/00_audit_env.sh`) and the Python checker both do a **GET**, do **not**
  follow redirects, accept only **200/301/302**, timeout **10 s**. The checker no
  longer uses HEAD, so `audit.md` and the invariant JSON can no longer contradict
  each other.
- **C2 — "reachable" tightened.** `validate_aks_direct_status` now accepts only
  **200/301/302** (was 200–399). `http_get` gained `follow_redirects` (default
  `True`); the AKS probe runs with `follow_redirects=False`, so a redirect to a
  login/geo wall surfaces as its real 3xx instead of being followed to a 200.
- **C3 — control-channel token redacted.** The CDP `webSocketDebuggerUrl` is no
  longer serialized; the report exposes only `webSocketDebuggerUrl_present: bool`
  via `redact_cdp_payload`.

### Security
- **S1 — `.gitignore` hardened** with credential/cookie/token/pem/har/`.DS_Store`
  patterns. Specific patterns only, so source files are never accidentally ignored.

### Architecture / wiring
- **G1 — the checker now runs its probes through the StepGuard.** `build_report`
  (extracted to `src/invariants.py`) wraps the AKS + CDP probes in
  `guard.run_step(...)` with deterministic success predicates and includes the
  guard snapshot in the report. This is the template every future stage follows.
- Refactor: `scripts/01_check_invariants.py` is now a thin CLI over
  `src/invariants.py` (which also makes the report logic testable).

### Tests & CI
- **T1 — CI added** (`.github/workflows/ci.yml`): unittest suite on Python 3.10 +
  a source-only secret scan, on every push / PR.
- **T2** — HTTP probes tested via a mocked IO seam (`_http_open`): 2xx / HTTPError
  / URLError / Timeout branches, the no-follow 302 case, and the HTTP method used.
- **T3** — `cdp_client.get_version` tested across all four outcomes + wrong-endpoint.
- **T4** — `src/invariants.build_report` tested: guard wiring, payload redaction,
  ok/authoritative, 302-accepted.

### Deliberately deferred (tracked in `AUDIT.md`)
P2 debt (C4, C5, C6, S2, S3, T5, T6) and the Sprint-2 foundations **G2** (data
contracts) and **G3** (JSONL run logs) remain open — these are net-new modules
rather than fixes, and are the recommended next increment.
