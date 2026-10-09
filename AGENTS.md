# AKS Controlled Executor — Codex instructions

## Mission

You are Codex CLI working as a builder, not as a free-form executor.

Your job is to build a deterministic AKS controlled executor.

You may:
- write scripts;
- write tests;
- audit logs;
- improve docs;
- run read-only diagnostics;
- propose implementation plans.

You must not:
- manually submit AKS offers through ad-hoc browser actions;
- improvise browser workflows;
- bypass validation;
- use Browserbase;
- use Playwright fallback;
- launch VPN;
- self-trigger or automate the session re-auth (AKS is social-login only now,
  so re-auth is COOKIE TRANSFER — `docs/LOGIN_SPEC.md`,
  `src/admin/login_manager.py` — driven only by Romain's explicit submit in
  the console; a `NotLoggedInError` from another stage stays a fail-closed STOP,
  never a re-auth trigger).

## Known infrastructure

Host Chrome CDP:
http://127.0.0.1:9222/json/version

Docker bridge CDP proxy:
http://172.17.0.1:9223/json/version

Official endpoint for code running from Docker bridge:
http://172.17.0.1:9223/json/version

Required User-Agent:
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36

AKS direct URL:
https://www.allkeyshop.com/blog/

## Forbidden

- Browserbase
- browser_navigate for AKS execution
- Playwright fallback
- VPN fallback when AKS direct works
- /root/start-chromium.sh
- random 0.0.0.x CDP checks
- submitting without explicit validation file
- submitting without modal context verification
- fire-and-forget submission
- using old candidates from memory
- using previous feed state
- self-triggering the session re-auth (cookie transfer, `docs/LOGIN_SPEC.md` —
  Romain's explicit submit in the console only)
- changing process after Romain says "go"

## Required architecture

The deterministic, per-stage rules (extractor, matcher, submitter, post-save
verification, reporting) derived from the `aks-data-entry` skill are specified in
`docs/EXECUTOR_RULES.md`. Read and follow it when implementing any stage; it is
the authoritative bridge between the skill and this code.

Build in stages:

1. Environment audit script.
2. Read-only feed extractor.
3. Read-only matcher.
4. Candidate report generator.
5. Validation file generator.
6. Submitter locked behind validation.
7. Post-save verifier.
8. JSONL logs for every action.
9. Dry-run mode by default.

Session re-auth (`docs/LOGIN_SPEC.md`, `src/admin/login_manager.py`): AKS
disabled password login (social/OAuth only), so re-auth is COOKIE TRANSFER —
Romain completes the social login in his own browser and pastes the WP session
cookies into the console, which injects them (official CDP only) and proves the
session. The one flow that touches session secrets: cookie VALUES are never
logged/echoed/stored, injection is restricted to `allkeyshop.com`, Romain's
explicit submit only. Never self-triggered: a `NotLoggedInError` from another
stage stays a fail-closed STOP + error report.

## Fail-closed behavior

If anything is uncertain:
- stop;
- write an error report;
- do not fallback to another browser;
- do not continue to next candidate;
- do not submit.

## Submission constraints

The submitter must only process candidates from a validation JSON file.

For each candidate:
- refresh current merchant feed;
- locate exact current row;
- verify title, URL, merchant/store (price is a routing signal, never a
  blocker after URL/store confirm; page is recomputed by the current scan —
  EXECUTOR_RULES §6);
- open modal from that row;
- verify modal context;
- fill visible region/edition controls;
- click official visible submit button;
- refresh feed;
- verify post-save state: success = the offer disappeared from the refreshed
  feed, same available mode as the run.

No degraded mode.

## Coding preferences

- Python 3.
- Minimal dependencies.
- No new production dependency without asking Romain.
- **`node` is an approved TEST-ONLY dependency (Romain, 2026-09-17: « Installe node pour les
  tests JS »).** Debian package `nodejs` (20.x), standard library only — no npm install, no
  `package.json`, no lockfile, nothing added to the runtime or to the VPS write path. It
  exists so the browser console (`src/admin/static/*.js`) is EXECUTED by its tests instead of
  being spell-checked: `tests/js/` holds a stubbed DOM + a hand-released `fetch`, and
  `tests/test_console_js_simulation.py` runs it and SKIPS cleanly where node is absent. Do not
  extend it into an npm toolchain, and do not make any production stage depend on it.
- Scripts must be CLI-friendly.
- Outputs should be JSON or JSONL where practical.
- Human reports go in Markdown.
- Never store passwords, 2FA codes, or session cookies.
- Never commit secrets.

## Reviewed decisions — do NOT re-tighten (an audit will re-flag these)

These are deliberate, Romain-reviewed calls. An adversarial audit re-derives them as
"findings" every time; leave them AS-IS unless Romain explicitly changes his mind.

- **`[R73]` Greenmangaming : la FICHE fait foi (DRM, édition, pays EXCLUS), et une clé à pays exclus
  entre en ROW si l'UE, le Royaume-Uni et les USA sont disponibles — Romain, 2026-10-09** (« go pour
  Greenmangaming avec ta règle R59, 1. L'executor continue de rentrer l'offre en ROW mais il vérifie que
  ce soit bien dispo en EU + US avant de l'ajouter, sinon il skip 2. consoles oui mais ça peut être xbox
  + PC sur certaines offres, 3. Standard oui 4. OK, go »). Le feed passe par le redirecteur Impact
  (`u` = fiche, `prodsku` = code produit = identité avec `u`) ; la fiche embarque un JSON (`var games`)
  dont l'édition `Code` == `prodsku` donne `Drm`, `Name`, `ExcludedCountries`, `SystemRequirements`.
  Un audit voudra : (a) retomber sur STEAM / GLOBAL quand la fiche est illisible — non (`[R51]`) ;
  (b) faire entrer « UE exclue » en US ou « USA exclus » en EU « puisque `[R59]` le fait » — non,
  Romain a borné : « sinon il skip » ; (c) ranger une clé à pays exclus en GLOBAL « comme Gamesplanet
  FR » — non, Romain a choisi le seau ROW (« Steam ROW (steamrow) », base `row` de `REGION_IDS`) avec
  la preuve UE + US ; (d) ouvrir la base `row` aux titres qui disent ROW — non, sans fiche pas de
  preuve, ROW reste une région interdite ; (e) inventer des seaux ROW pour GOG / Rockstar / Microsoft /
  consoles — non, le menu n'en a pas ou ce sont des verrous ; (f) prendre « la première édition » de la
  fiche quand le sku n'y est pas — non, c'est l'identité ; (g) lire `IsSellable` — non, une offre épuisée
  est à saisir ; (h) laisser entrer « 2 Pack » / « Bundle », ou un palier de la fiche que le titre ne
  nomme pas — non, refus ; (i) rendre aux hooks console la fiche de `u` au lieu de l'URL du feed — non,
  leur grammaire est celle du feed (le sku porte la génération). PAS en liste blanche tant que Romain
  n'a pas lu l'aperçu. EXECUTOR_RULES `[R73]`, `tests/test_merchants_greenmangaming_r73.py`.

- **eww.gg (store 170) : liste blanche et première passe SANS aperçu à blanc préalable — Romain,
  2026-10-07** (« Store ID 170 stop B et lance le data entry pour ce nouveau shop, puis tu relanceras
  B depuis l'admin pour être sûr que j'ai le log »). eww.gg est la seconde boutique de Driffle UAB,
  titre à la grammaire de Driffle à l'identique : `src/merchants/eww.py` en est la déclinaison. Un
  audit « trouvera » un marchand allowlisté sans aperçu ni fiche lue : c'est l'instruction de Romain,
  sur une grammaire déjà éprouvée en production — la première passe réelle (recap, log de l'admin)
  tient lieu de mesure — elle a mesuré ~10 400 lignes, ~70 % entrantes, et un feed RÉIMPORTÉ par AKS
  chaque jour (une passe ne le « finit » pas). **Groupe C, SEUL, depuis le 2026-10-09** (Romain : « on créera
  le groupe A, B et C et on lancera un groupe par machine », après un « On ajoutera ce marchand à la liste
  B » du même matin) : une passe de eww.gg vaut dix passes de A ou de B (41 h pour 73 pages contre ~2 h), un
  audit voudra le « répartir » ou fusionner C dans B pour l'équilibre des lignes — non : c'est la cadence
  des autres marchands qui est protégée, les groupes se mesurent en durée de passe. Ne pas en déduire
  que l'aperçu préalable n'est plus la règle pour un marchand à grammaire NOUVELLE.

- **`[R72]` CJS « Access (Digital Download) » : clé ou compte, SEULE LA PAGE le dit — Romain,
  2026-10-07** (« tu as rentré cette offre en clé à la place d'account car tu n'as sûrement pas
  ouvert la page », puis « ça ne va pas dire "Account". Account, on le voit que sur la page, avec un
  message : attention, ce jeu est un account »). La page CJS ne se lit pas (403) : ces lignes sont
  REFUSÉES, nommément, sans routage (`cjs.SKIP_ACCESS_UNVERIFIABLE`) — ni clé (52 écrites ainsi du
  17/09 au 30/09, `docs/audit_2026-10-02/cjs_access_ecrites.csv`, à relire une par une), ni « compte »
  (on ne le sait pas, donc pas la liste 30). Le générique est inchangé : « Access » en queue n'est pas
  un signal de compte (ma première correction le faisait, Romain l'a refusée). Un audit voudra :
  (a) router en liste 30 « puisque ce sont des comptes » — non, certains sont des clés ; (b) revenir à
  « clé console » faute de page — non, c'est l'erreur des 52 ; (c) un navigateur de contournement
  pour lire CJS — non (« Forbidden ») : la voie est un accès consenti par CJS (allowlist IP, API,
  champ de feed). EXECUTOR_RULES `[R72]`.

- **`[R70]` L'Amérique du Nord est une région VENDABLE, PC et consoles — Romain, 2026-10-06**
  (« tu sais ajouter ça, c'est "Steam NA" — pourquoi j'ai ce log », puis « go pour NA, PC et
  consoles »). `NORTH AMERICA` était dans `FORBIDDEN_REGIONS` depuis le début, d'avant la règle
  « vérifier le dropdown » (16/09) ; le menu du modal a STEAM NA (`steamna`), Steam Gift NA (2571),
  Origin NA (643), ubisoft na (606), battlenet na (625), xbox game code north america (582), Xbox
  Series NA Game Code (304), xbox/pc na (605), playstation game code na (610), nintendo game code
  north america (496) ; 1 260 offres distinctes refusées en production avant ça. Base `na` dans
  `SELLABLE_WORDS` (« NORTH AMERICA », code « NA » en capitales), le scan générique (nom entier
  partout, code « NA » seulement en créneau : queue, slot d'URL, parenthèse), le classifieur console
  et les tables de Gamivo / Loaded / Instant Gaming. Un audit voudra : (a) remettre NORTH AMERICA
  en verrou « parce qu'on est sur Global, Europe et US » (13/08) — non, Romain a tranché le 06/10
  sur les cases du menu ; (b) retomber sur US (8) ou GLOBAL pour GOG / EPIC / PUBLISHER / ROCKSTAR /
  MICROSOFT, qui n'ont pas de case NA — non, refus « no region id » ; (c) lire un « NA » nu en
  plein titre — non, collision avec des mots de jeux ; (d) faire entrer « EU NA », « AMERICAS » ou
  « EUROPE / NORTH AMERICA » — non, deux régions ou plus = verrou ; (e) utiliser « Publisher NA/SA
  (531) » pour une clé Publisher NA — non, le seau couvre l'Amérique du Sud. EXECUTOR_RULES
  `[R70]`, `tests/test_region_na_r70.py`.

- **`[R69]` Indiegala : la FICHE produit fait foi (plateforme + pays INTERDITS), la fiche DLC est
  une GARDE — Romain, 2026-10-06** (« Si on peut ouvrir la page, on trouvera les infos », puis, le
  tableau ligne par ligne lu — `docs/apercu_indiegala_2026-10-06.md`, 34 entrées / 175 —, « go pour
  la liste blanche », puis « groupe B pour Indiegala »). Titre et URL ne disent ni plateforme ni région : la fiche indiegala.com est
  lue pour CHAQUE ligne (`indiegala.page_get`, bibliothèque standard, UA navigateur) ; plateforme =
  « is provided via **Steam Key** » (libellé absent ou inconnu → refus, jamais STEAM par défaut :
  39 fiches « direct download » refusées à l'aperçu) ; région = `[R59]` sur la liste des pays
  INTERDITS (aucun pays d'UE / UK / USA → GLOBAL ; toute l'UE + UK sans les USA → US ; USA sans
  l'UE → EU ; mélange → refus) ; h3 « Region locked product » → refus ; suffixe « (US) / (EU) » du
  titre = `title_region`, doit s'accorder avec la fiche sinon refus. **La fiche DLC (« requires the
  base product ») est une garde générique** (`MerchantOfferSignals.dlc` → `matcher.page_dlc_refusal`) :
  elle ne choisit jamais le seau (R18 / `[R43]` / `[R57]` le font), mais une fiche DLC qui n'aboutit
  pas en DLC(16) est refusée — « Thunder Ray - Origin » (ORIGIN = bruit de plateforme, titre sans
  marqueur) sortait Standard(1) sur la page du jeu de base à l'aperçu. Romain a vu et laissé passer :
  les 5 entrées US qui sont la PREMIÈRE offre US de leur page (le formulaire propose la région), et
  Standard sur une page qui vend aussi Enhanced / Early Access quand le titre ne le dit pas. Un
  audit voudra : (a) retomber sur STEAM / GLOBAL quand la fiche est illisible — non (`[R51]`) ; (b)
  faire entrer Belmont's Curse (EU) en EU parce que « (EU) » est dans le titre — non : Chypre ET les
  USA sont interdits, pas tranché par Romain, refus ; (c) faire du `dlc` de la fiche un routage
  (« la fiche dit DLC, donc DLC(16) ») — non, c'est le seau de la page AKS et du titre qui décident,
  la fiche ne fait que refuser le reste ; (d) lire la fiche par `aks_env.http_get` — non, même raison
  que `[R68]` ; (e) couper « Attack on Titan 3 / A.O.T. 3 » à un alias — non : AKS n'a aucune page
  AOT 3, et un alias demande un go ; (f) remettre Indiegala hors liste blanche parce que le
  rendement est faible (≈ 34 / 175) — non, c'est le go de Romain, le rendement était connu.
  EXECUTOR_RULES `[R69]`, MERCHANTS « Indiegala (store 95) », `tests/test_merchants_indiegala_r69.py`.

- **`[R68]` Allyouplay : la FICHE produit fait foi (plateforme + pays autorisés) — Romain,
  2026-09-30** (« go pour 1 », puis « go pour la mise en ligne » après l'aperçu : 119 candidats PC
  Steam sur 296 lignes, toutes les lignes Xbox refusées sur leurs pays). Le feed Allyouplay passe
  par le redirecteur `anandadigitalbv.sjv.io` (la fiche est dans `u`, qui est aussi l'identité —
  `MerchantConfig.affiliate_hosts`, comme Loaded) ; les titres PC ne disent NI plateforme NI
  région. Ordre titre → codes du slug (`-ga-ste-` / `-ga-gog-`) → fiche ; région = règle `[R59]`
  sur les pays ABSENTS de `available_countries`. Un audit voudra : (a) retomber sur STEAM /
  GLOBAL quand la fiche est illisible, ou quand elle n'a pas « Platform » — non, refus (c'est
  exactement ce que `[R51]` interdit ; l'aperçu de la veille montrait 6 clés Xbox « GLOBAL
  implicite » qui étaient bridées à quelques pays) ; (b) lire la fiche par `aks_env.http_get` —
  non : son moteur `requests` envoie « User-agent » et le Cloudflare d'Allyouplay répond 403
  (241 / 241 au premier essai) ; `allyouplay.page_get` (bibliothèque standard) est voulu, et le
  moteur partagé des requêtes AKS ne doit pas changer pour ce marchand ; (c) faire entrer les
  « [Mac] », une clé « Mac OS » seule, « Platform: Elder Scrolls Online », ou X-COM (`-ga-gog-`
  contre « Platform: Steam ») — non, refus nommés ; (d) élargir `affiliate_hosts` à d'autres
  hôtes ou lire `u` pour un marchand qui ne le déclare pas — non ; (e) lire la région dans le
  titre ou l'URL « pour économiser la requête » — non, chez ce marchand ils n'en disent rien ;
  (f) sur la branche console, laisser un créneau de région du titre passer avant la fiche, ou
  ignorer la plateforme de la fiche (`console_page_authoritative`, revue adverse du 30/09) — non ;
  (g) revenir au terme de recherche `30655` (commun à tout le magasin) ou accepter une page de
  recherche de 300 lignes comme preuve de disparition — non, `[P2-13]` : elle ne pagine pas.
  EXECUTOR_RULES `[R68]`, `tests/test_merchants_allyouplay.py`, `tests/test_merchants_allyouplay_r68.py`.

- **`[R66]` Recherche catalogue AKS en dernier recours — Romain, 2026-09-29** (« La recherche
  AKS en dernier recours me semble indispensable », proposition 11 de l'audit « pas de page
  produit » du 28/09). Passe 5 de `resolve_aks`, index frais ou non, page clé PC seulement :
  l'API que le front du site appelle (`…/api/v2-1-250304/vakrs_catalogv2.php`, ≈ 500 o), des
  CANDIDATS seulement, chaque page relue et jugée par toutes les gardes. Elle revient
  VOLONTAIREMENT en partie sur « sitemap d'abord » (24/09) : au plus une requête par offre sans
  page, bornée par un budget de 1 000 par balayage et un cache de 14 jours (réponses vides
  comprises). Un audit voudra : (a) retirer la requête « puisque l'index fait autorité » — non,
  c'est la décision de Romain, l'index n'est pas exhaustif et ne devine aucun nom ; (b) deviner
  la nouvelle version quand l'API change (404, JSON différent) — non : refus nommé `(R66)`,
  recherche coupée pour le balayage, un humain relit `/blog/products/` ; (c) lâcher le filtre
  « chaque mot du nom du catalogue est dans le titre » pour gagner du rappel — non, c'est le côté
  requis de R01 (21 pages connues trouvées par l'API sur 24 au rejeu ; 15 non proposées — 12 par
  ce filtre, 3 pages console par la grammaire —, toutes refusées par R01 de toute façon) ; les alias (« COD », « GTA 5 ») restent une décision de
  Romain ; (d) laisser entrer Standard(1) / DLC(16) ou un logiciel sur une page dont le nom n'a pas
  tous les mots du titre — non, même règle que `[R64]` (« Marvel's Midnight Suns Digital+
  Edition » entrerait en Standard) ; (e) raccourcir la durée de vie des réponses vides — non :
  elles dominent (≈ 47 % des lignes n'ont vraiment pas de page), le budget ne suivrait plus ;
  (f) réutiliser `?s=` — morte depuis le 22/09, atteinte seulement sans session.
  **Revue adverse du même jour, en configuration de PRODUCTION (session posée — les tests `[R64]`
  / `[R65]` tournaient sans) : trois écritures fausses et des refus à tort, corrigés.** R01 / R16
  comparent des ENSEMBLES : « Nope Nope Nope Nope Nurses » (GameSeal 100698305, GOG 100461290)
  entrait sur « Nope Nope Nurses », « Legacy of Ancestors » (Kinguin 100997924) sur « Ancestor's
  Legacy » ; et la recherche passait AVANT les gabarits console : Eneba « Destiny 2: The Collection
  XBOX LIVE Key UNITED STATES » entrait sur `destiny-2-xbox-one-code` (le JEU DE BASE),
  Collection(98), pendant que « Priest Simulator: Vampire Show » et « Worms Armageddon:
  Anniversary Edition » étaient refusés. Désormais le nom proposé ET le nom lu doivent être
  COHÉRENTS avec le titre brut (`catalog_name_mismatch` : mots comptés, pas de mot répété en
  moins, article de tête gardé, même ordre ; le bruit seulement présent), la condition 3 de
  `[R64]` vaut pour la recherche, et une ligne console n'interroge le catalogue qu'après TOUS ses
  gabarits (`catalog="off"` puis `"only"`). La promesse (d) est donc vraie mot pour mot. Un audit
  voudra : (g) ne lire que les candidats que l'index publie, pour borner les lectures de pages —
  non : l'index n'est pas exhaustif (audit du 28/09 §4.4, `clue-cluedo-the-classic-mystery-game-
  cd-key` vivante et absente), la recherche est précisément le filet de ces trous ; `resolve_aks`
  rend la PREMIÈRE page cohérente, ≈ une lecture par ligne à candidat et par passe, mesurée ;
  (h) un budget par marchand — non : une part égale (1 000 / 8 = 125) ne couvrirait jamais GameSeal
  dans la durée de vie du cache (≈ 210 requêtes par passe), le budget partagé couvre le stock en ~9
  passes ; le coût est un délai pour les derniers marchands, dit dans `match_meta` (`budget_scope`) ;
  (i) remettre la recherche avant les gabarits console « pour trouver plus » — non, c'est l'écriture
  Destiny ; (j) relâcher la cohérence en ensembles, ou lire le bruit comme un mot compté — non,
  c'est l'écriture Nope, et « Microsoft Flight Simulator (Microsoft Store) » serait refusé à tort ;
  (k) faire entrer DRAGON BALL Z KAKAROT « Daima Edition » (3 offres) ou Starpoint Gemini 2
  « Gold Pack » (2) sur la page de base qui vend le seau du même nom, alors que le nom complet est
  publié ailleurs (Switch 2, Xbox) — non tranché : c'est la condition 3 de `[R64]`, un refus
  (jamais une écriture) ; pour Destiny 2 « The Collection », la page `destiny-2` vend AUSSI
  « Legacy Collection » : le seau n'y est pas certain ; (l) une coupure sans échéance sur un corps
  illisible — non : 30 min comme R30, seul un 404 / 410 (version retirée) coupe le balayage ;
  (m) laisser entrer, par ces rangs de repli, un palier nommé MOINS précis qu'un autre que la page
  vend et que le titre nomme (CJS / Gamerall « ESO Deluxe Collection: Necrom » en Deluxe(7), la
  page vend « Deluxe Collection Edition ») — non, refus. EXECUTOR_RULES `[R66]`,
  `tests/test_aks_search_r66.py`, `tests/test_aks_search_r66_revue.py`.

- **`[R64]` Rang de repli « nom d'édition retiré, confirmé par l'index » — Romain, 2026-09-29**
  (« go pour les corrections 1 et 2 et les vérifications », proposition 1 de l'audit « pas de page
  produit » du 28/09). « The Secret of Monkey Island: Special Edition » → la page de base
  `the-secret-of-monkey-island`, seau Special(41) ; « WWE 2K26 | King of Kings Edition » → 10860.
  Un audit voudra : (a) mettre ce rang dans `build_slug_candidates` ou juste après le rang 1 —
  non : `[R57]` lit `build_slug_candidates` (52 bascules) et, après le rang 1, 15 lignes déjà
  créées changeaient de page ; il vient APRÈS tous les rangs, dans `resolve_aks` seul ; (b)
  laisser entrer Standard(1) quand les mots retirés ne nomment aucun seau — non, c'est le cœur de
  la règle (« Marvel's Midnight Suns Digital+ Edition » serait entrée sur le mauvais palier) ;
  (c) retirer aussi DEFINITIVE / REMASTERED / ANNIVERSARY / REMAKE / HD… — non, décision revue ;
  (d) sonder la base sans que l'index la publie, ou lui donner une soupape — non ; (e) retirer les
  mots même quand le nom complet est publié sous un autre gabarit (`…-xbox-key`, compte…) — non,
  AKS en fait un autre produit ; (f) laisser un logiciel entrer par ce rang — non, refus voulu
  (licence unique adoptée sans être nommée). EXECUTOR_RULES `[R64]`,
  `tests/test_resolver_repli_r64_r65.py`.

- **`[R65]` Pages console « -key » / « -code » et page Xbox combinée — Romain, 2026-09-29** (même
  go, proposition 2). Sept gabarits de repli (`CONSOLE_FAMILY_TEMPLATES`), standard d'abord,
  sondés seulement si l'index les publie ; deux pages pour une même console → refus ; la méta de
  la page reste le juge ; P1 inchangé ; la page `-xbox-key` est rangée selon sa MÉTA et sert une
  génération DÉCLARÉE égale — et, depuis la règle 2b ci-dessous, un Xbox sans génération quand
  elle se déclare Xbox Series. Un audit voudra : (a) allonger `CONSOLE_PAGE_KINDS` — non, il
  nourrit `_AKS_PAGE_URL_RE` et `[R18c]` ; (b) choisir entre deux pages d'une même console
  (« la standard gagne ») — non, refus ; (c) la page combinée pour une génération DÉDUITE (P4) —
  **tranché le 2026-09-29, règle 2b ci-dessous** (« 2b, non tranché » jusque-là) ; (d) ajouter
  `ps4-game-code` / `key-nintendo-switch-2` — hors du go (5 lignes) ; (e) retirer le PRÉALABLE
  (un nom de pays suivi d'une région vendable reste dans le nom de garde console et dans le slug,
  `keep_country`) — non : sans lui, « Assassin's Creed Chronicles China (Europe) » entrerait sur
  la page de la trilogie. EXECUTOR_RULES `[R65]`.

- **Règle 2b `[R65]` — un Xbox SANS génération entre sur la page combinée déclarée Xbox Series —
  Romain, 2026-09-29**, après avoir vérifié les pages Microsoft des exemples, mot pour mot :
  « go pour la règle Xbox sans génération ». Une clé « XBOX LIVE Key » / « (Xbox Live) » (P4)
  dont le jeu n'a, côté Xbox Series, que la page `<slug>-xbox-key` (méta Xbox Series X) y entre
  en XBOX_SERIES, dans la région que la clé dit (UK 305, EU 302, US 303, sans région 300) ; quand
  AKS a aussi une page Xbox One, P4 inchangé : les deux pages. Un audit voudra : (a) élargir la
  région (« une clé UK sur une page combinée, autant GLOBAL ») — non, jamais : Eneba « Sora:
  Songs of the Stone XBOX LIVE Key UNITED KINGDOM » → 305, jamais 302 ni 300 ; (b) ajouter la
  page PC « puisque le jeu y est aussi » — non : ces clés ne déclarent ni PC ni Windows ; seuls
  P2 (page PC Play Anywhere, ou Xbox + PC déclarés) et la clé Windows l'ajoutent, inchangés ;
  (c) accepter une page combinée qui se déclare Xbox ONE — non, hors du go, refus explicite
  (`rule 2b covers a combined page declared Xbox Series only`) ; (d) choisir entre la combinée et
  une page Xbox Series standard — non, deux pages pour une console restent le refus `[R65]` ;
  (e) laisser entrer la page combinée SANS offre (Grizzy, Far Cry 3 — aucune carte d'éditions) —
  non, R19 la refuse comme toute page vide, et avec elle la ligne entière (P4) : Gamerall « Far
  Cry 3 - Classic Edition (Xbox Live) », créée le 25/09 sur la seule page Xbox One, est refusée
  tant que la page Series n'a pas d'offre — voulu, on ne perd pas une page qu'AKS a ; (f) une clé
  Windows Play Anywhere prend aujourd'hui One + combinée + page PC (« les pages Xbox qu'AKS a »,
  P4) — **À CONFIRMER PAR ROMAIN, pas une décision revue** : c'est une conséquence du même `if`,
  hors des quatre exemples du go, soumise dans le rapport du 29/09 ; ne pas la citer comme
  tranchée. **Revue adverse du même jour** (correctifs fail-closed de l'implémentation, soumis à
  Romain dans le rapport, pas des décisions de Romain) : (g) une combinée dont la méta ne nomme
  aucune génération Xbox (absente, « Xbox », « PC », deux générations) refuse la ligne — le
  gabarit combiné ne dit pas la génération, on ne saurait pas si c'est une seconde page de la
  console visée (une page STANDARD à méta muette reste acceptée) ; (h) une page Xbox Series
  publiée au même slug que la combinée compte : deux pages → refus ; (i) G2A
  `…-xbox-live-key-xbox-one-<région>-i<id>` est un Xbox One DÉCLARÉ (grammaire G2A seule, jamais
  générique). Les assouplir demande un go de Romain. EXECUTOR_RULES `[R65]` (règle 2b) et §4.12
  P4, `tests/test_resolver_repli_r64_r65.py` (`R65Regle2b`, `R65Regle2bRevue`).

- **`[R63]` Clés EA « English only » : case 31 sans verrou, 3euen sinon 3eu en Europe —
  Romain, 2026-09-28** : « go pour les clés EA English only en case 31 », puis, mot pour mot :
  « Une clee english only n est pas forcement bloque a la region Europe, si on a une info comme
  EU english only on renseignera EU en priorite si pas de region "EU english only" ». Lecture
  codée : une clé EA (EA app / Origin) marquée English only SANS verrou → **31** ; marquée
  English only ET verrouillée Europe → **3euen**, et si la page AKS ne porte pas 3euen → **3eu**
  (le verrou Europe prime sur la mention de langue) ; **jamais 31 pour une clé verrouillée
  Europe**. Le catalogue du formulaire porte TOUJOURS 3euen, donc « si pas de région "EU english
  only" » ne peut viser que la PAGE. Les trois noms de chaque seau (ne pas les confondre) :
  31 = formulaire « Origin English Only -OR- EN/PL -OR- EN/PL/RU (31) », filtre de page « EA
  ENG/POL/RUS ONLY », page publique « IN ENGLISH ONLY » ; 3euen = « Origin EU English Only
  (3euen) », « EA EU ENG ONLY », « EU IN ENGLISH ONLY » ; 3eu = « Origin EU (3eu) », « EA
  EUROPE ». Un audit voudra :
  (a) faire entrer EN/PL et EN/PL/RU en 31 « puisque le libellé AKS les nomme » — non, non
  tranché, ils restent « language restriction » ;
  (b) lire un EN / ENG / (EN) nu comme la mention — non, ONLY est obligatoire (Driffle « (EN) »,
  GameBoost « ENG » restent des questions ouvertes) ;
  (c) retirer l'exigence « la page porte 31 / 3euen / 3eu » au nom de `[R56]` (la liste de
  filtre dit « déjà vendu », pas « le formulaire le propose ») — c'est exact, et c'est VOULU :
  la consigne du 28/09 l'exige ; coût mesuré ce jour-là : 0 ligne ; ne la relâcher que sur un
  nouveau go ;
  (d) étendre la règle aux autres plateformes (Epic 476, Ubisoft EU 440, Steam Gift EU 472…) ou
  aux verrous US / UK — non, refus explicites `(R63)`, questions ouvertes ;
  (e) retirer la mention du titre partout — non : elle ne sort du slug et des gardes QUE sur la
  route `[R63]` (ENGLISH / ONLY / ENG ne sont pas des mots de bruit, `resolution_name` et
  l'export de la liste 22 la gardent) ;
  (f) retirer le filet « verrou écrit mais non lu » (`english_only_unread_lock`) parce que
  « [EU] » / « (EU Version) » / « (Europe & UK) » SANS la mention entrent en EA GLOBAL(3) — non :
  c'est une lacune préexistante de la lecture générique, signalée à Romain et non tranchée ; sur
  la route `[R63]` le verrou écrit interdit 31 (revue adverse du 28/09 : « (EU English Only) »
  partait en 31, verrou perdu — d'où la relecture sans la mention, `english_only_region`) ;
  (g) lire « (DE  EN Only) », « Polish English Only » comme la mention — non : une langue juste
  avant la phrase en fait une liste, « language restriction » ; mais « (Europe, English Only) »
  EST la mention (une région n'est pas une langue) ;
  (h) remettre un compte English only en « language restriction » — non : il suit la règle de
  tous les comptes, « skip category: ACCOUNT » → liste 30.
  EXECUTOR_RULES `[R63]`, `tests/test_english_only_r63.py`.

- **Chemin by-urls : l'index de localisation EST remplacé par la preuve après chaque création —
  laisser tel quel (audit complet du 2026-09-18, constat écarté).** Sur `--locate-by-search`
  les deux drapeaux sont vrais, donc `keep_index` vaut False et l'index bâti par
  `_index_by_search` (3 tentatives par candidat) est remplacé par les 0-1 lignes de la recherche
  de preuve. Le fait est exact ; il est DÉLIBÉRÉ. Sur ce chemin chaque offre est localisée par SA
  PROPRE recherche (`_relocate_by_url` re-cherche), il n'y a pas de fenêtre de page à préserver,
  et `test_by_urls_path_still_refreshes_its_index_from_the_search` épingle le comportement. Aucun
  effet sur la justesse — seulement du travail refait. Un audit le re-trouvera en citant le
  commentaire qui le précède : ne pas retourner une décision testée pour une économie non mesurée.

- **R01 : l'apostrophe est REPLIÉE, les mots-outils NON (audit complet du 2026-09-18).** Le repli
  de l'apostrophe dans `tokenize` est acquis (« Assassins Creed » couvre « Assassin's Creed ») —
  il ne peut faire matcher que des noms qui SIGNIFIENT la même chose. La seconde moitié du même
  constat — retirer THE / OF / AND du côté REQUIS, ou plier `&` en `AND` — a été délibérément
  abandonnée : elle, elle relâcherait l'identité. Un audit reproposera le paquet entier ; ne
  reprendre que la moitié déjà faite.

- **Une offre ÉPUISÉE (stock `n`, prix `0`) est une offre à SAISIR — Romain, 2026-09-21.** Sa
  ruling, après avoir regardé les lignes que l'audit GameSeal avait signalées : « à part le
  fait que ce soit out of stock, je vois pas d'erreurs. C'est peut-être des offres qui vont
  restocker à l'avenir. Vu que c'est dans leur feed en pending offers, vaut mieux les avoir au
  cas où, un jour, ils restockent. » C'est la même logique que le retrait de R25 : une offre
  PENDING est à ajouter, point. Le code est déjà d'accord — ni le stock ni le prix ne
  conditionnent quoi que ce soit dans `src/matcher.py` / `src/submitter.py` (le prix reste un
  signal de routage, jamais un bloqueur, EXECUTOR_RULES §6). Un audit « trouvera » ces lignes
  (le balayage GameSeal du 19-20/09 en a écrit 62 à prix `0`) et voudra un skip « offre
  épuisée » ou un garde « prix nul » : NE PAS l'ajouter.

- **`[R18c]` « <Jeu> <X> Edition » = jeu + DLC, jamais DLC(16) sur la page du DLC seul —
  Romain, 2026-09-26** (« go pour A, et B en attendant » ; « que pour les jeux + DLC et pas
  pour les DLC seuls » ; « faut pas se fier au prix … si tu ne trouves pas les infos sur la
  page, tu skip »). AKS range ces offres sur la page du JEU, dans l'édition du même nom (lu
  le 26/09 sur 11 jeux) ; 18 avaient été écrites en DLC(16) sur la page du DLC. Détection
  structurelle (mot EDITION absent du nom de la page, hors « Standard Edition », titre sans
  marqueur), JAMAIS le prix. Un audit « trouvera » un vrai DLC « … Edition » refusé : s'il est
  vraiment seul, la page AKS porte le mot (« Special Edition Content ») et il entre ; sinon
  c'est un doute, et un doute se refuse. **Étape A (même jour) :** le match est refait sur la
  page du JEU parent (préfixe publié le plus long au sitemap) et n'entre que dans l'édition que
  les mots du titre NOMMENT sur cette page ; sinon le refus reste. Un audit voudra « retomber sur
  Standard sur la page du jeu » ou « essayer un préfixe plus court » : ni l'un ni l'autre.
  **Étendu le même jour aux pages DLC à plusieurs seaux** (Romain : « Route-les aussi vers la
  page du jeu si le jeu est inclus (jeu + DLC) ») : page résolue avec un seau DLC et AUCUN
  Standard, qui ne vend pas l'édition du titre → même routage, même preuve. Une page qui vend
  Standard, ou le palier du titre, garde le chemin normal.

- **[R18b] R18 se RETIRE quand le titre annonce un palier que la page ne nomme pas (2026-09-20,
  « le correctif que tu veux » — CONFIRMÉ le 2026-09-21 sur le cas concret, « garde ta règle »,
  après que Romain a lui-même écarté la lecture « ça rentre quand même » qui lui était proposée
  en regard de son ruling sur les offres épuisées).** R18 reste le SEUL juge du seau DLC(16) — la décision du
  17/09 est intacte : un titre sans marqueur sur une page mono-seau DLC entre en DLC(16). La
  seule exception ajoutée : si le titre marchand annonce un PALIER (Deluxe / Ultimate / Gold /
  Complete, lu par `detect_edition`) que le NOM DE LA PAGE AKS ne porte pas, R18 laisse la
  main — le marchand vend un SKU plus large que la page, et la vérification de page (P1-1)
  refuse. Déclencheur : « Call of Duty: Black Ops III Zombies Chronicles Deluxe Edition »
  (offre 100700366) écrite DLC(16) sur la page du DLC seul. Mesure avant application sur
  1 818 lignes écrites : 43 en DLC(16), 10 sans marqueur, UNE bascule — la fausse. Un audit
  « trouvera » que R18 a été affaibli (« un vrai DLC dont le titre dit Deluxe n'entre plus »)
  : il entre toujours si la page nomme le même palier (« Wortox Deluxe Chest »), et sinon
  c'est un refus, jamais une écriture fausse. Ne pas restaurer la préséance inconditionnelle.

- **Le disjoncteur de recherche R30 EXPIRE au bout de 30 min (2026-09-20, même GO).** Le
  commentaire de `scripts/03_match.py` a longtemps dit « sweep-scoped and has no expiry
  (Romain 2026-09-10) » — un audit qui relira le git voudra restaurer l'éternité. Mesure qui
  l'a fait tomber : le balayage `20260919-082932` (3 marchands, 30 h) a ouvert le disjoncteur
  66 SECONDES après son démarrage, 7 heures avant que GameSeal ne commence ; les 60 pages de
  GameSeal ont résolu au slug seul et 434 offres distinctes sont ressorties « no AKS product
  page found ». La décision du 10/09 précédait les balayages tout-pages multi-marchands. Le
  coût d'une re-sonde est borné (3 tentatives par page qui la tente, une fois par fenêtre).

- **Comptes : un signal explicite l'emporte, et le silence n'est jamais « clé » (2026-09-25,
  rapport de bug de Romain).** Un détecteur unique (`console_keys.account_signal`) : mot
  ACCOUNT du titre, jeton `account` n'importe où dans le chemin d'URL, ou la grammaire propre
  du marchand (`account_row`). Un marchand SANS grammaire propre : un compte est refusé et
  routé en liste 30. Difmark garde sa branche compte, où la PAGE décide : ACCOUNT / OFFLINE →
  compte, « (<plateforme>) » ou KEY → clé (la « vraie clé Difmark » du 21/09 reste valide :
  le « account » de ses URL est un gabarit), rien de tout cela → refus. Un audit voudra
  (a) faire du « account » d'URL Difmark un signal de compte — non, c'est un gabarit, il
  casserait les vraies clés ; (b) retomber sur « clé » quand la page Difmark se tait — non,
  c'est exactement l'erreur des huit « [OFFLINE] » du 23/09 ; (c) assouplir la garde finale
  du submitter (destination inconnue → bloquée) — non.

- **`[R58]` Wyrel : « (PC) » sans boutique + page AKS « Steam » SEUL = Steam — Romain,
  2026-09-24, pour Wyrel SEULEMENT** (« si une offre est marquée PC et qu'on n'a pas d'autre
  info, si sur la page Allkeyshop on a que du Steam, on l'ajoutera en Steam ; si on voit qu'il y
  a du Epic, du Ubisoft, du EA… on skip » — « et c'est valable que pour Wyrel, dans sa config
  marchand »). Un premier « NO GO » du même jour a été remplacé par cette règle, formulée par
  Romain lui-même. Déclarée par `wyrel.pc_key_without_store` (`MerchantConfig`) ; le matcher
  exige l'égalité STRICTE des plateformes officielles de la page avec {Steam}. Un audit
  proposera de l'étendre aux autres marchands (Kinguin, Gamivo… écrivent aussi « PC » sans
  boutique) ou d'accepter « Steam parmi d'autres » : ne pas le faire sans un nouveau go — pour
  tous les autres marchands, R27 / `[R51]` restent intacts.

- **Une clé ROW n'entre que si on PROUVE qu'elle s'active en Europe — Romain, 2026-09-24**
  (« les ROW, pour que tu puisses les ajouter, il faudra s'assurer qu'ils soient valables en
  Europe »). Ni le titre ni l'URL ne le prouvent ; la page marchand le pourrait, mais celle de
  Wyrel est derrière Cloudflare. « Rest of World » / « Rest of the World » en toutes lettres
  sont donc le même verrou que le sigle ROW (`matcher.FORBIDDEN_REGIONS`,
  `merchants/common.py`). Un audit « trouvera » 161 lignes Wyrel ROW perdues, dont 69 avec une
  page AKS : c'est le prix accepté tant qu'aucune lecture de page ne prouve l'Europe — ne pas
  les faire entrer en GLOBAL.

- **La recherche de preuve AKS est insensible à la casse — Romain, 2026-09-26** (« go pour
  vérifier et corriger la recherche CJS »). Prouvé en lecture seule (`probe_search_rows.py`) :
  « ATLAS-… » rend « Starlink-Battle-for-Atlas-… ». Le contrôle des lignes replie donc la casse,
  ET chaque page (vide ou non) doit porter NOTRE terme dans son href. Un audit voudra « revenir
  au contrôle exact » (il fabriquait des UNKNOWN : trois arrêts CJS) ou « retirer le contrôle
  d'href » (c'est lui qui refuse une page périmée dont les lignes contiennent notre terme) :
  ni l'un ni l'autre.

- **La BOUCLE d'un groupe — Romain, 2026-09-27** (« qu'on puisse quand même aller l'arrêter,
  mais qu'il boucle », puis « 5 min de pause, sans limite, go pour la boucle »). `--loop` / case
  « Boucler » : des passes sans limite dans le même processus supervisé, 5 min de pause (30 si la
  passe a créé moins de 10 offres — Romain, 2026-09-28 : « go pour 30 min si moins de 10
  offres » ; c'était 0 le 27/09), « Arrêter » immédiat pause comprise. Elle s'arrête D'ELLE-MÊME dans trois
  cas, et trois seulement : session expirée (→ transfert de cookies par Romain, jamais de
  re-auth), garde bloqué (`guard_blocked` ou `ten_consecutive_failures`, audit de Romain du 29/09),
  TOUS les marchands de la passe arrêtés. Un audit voudra (a) retirer
  l'arrêt « tous arrêtés » (« un marchand seul se reprend, pourquoi pas tous ? ») — non : tous
  arrêtés = une panne systématique, boucler la martèlerait ; (b) une reconnexion automatique pour
  que la boucle survive à une session expirée — non, jamais (AGENTS « Mission ») ; (c) arrêter la
  boucle au premier marchand arrêté — non, c'est précisément ce qu'elle doit reprendre. Le
  webhook Discord (`AKS_DISCORD_WEBHOOK`, `.env`) est un secret : jamais journalisé, jamais
  commité ; sans lui, aucune notification, et un échec d'envoi n'arrête rien.

- **Déconnexion pendant un lot : le lot CONTINUE — Romain, 2026-09-26** (« le lot continue »).
  Avec `--continue-on-halt`, un « not logged in » arrête le marchand (halte de page, jamais une
  reprise automatique) puis le lot passe au suivant ; il arrêtait tout le lot avant. Aucune
  écriture n'en dépend : chaque étape revérifie la session avant d'écrire, et une session
  vraiment perdue arrête chaque marchand suivant à sa première lecture. La re-authentification
  reste le transfert de cookies par Romain, jamais déclenchée par le code. Un audit voudra
  « restaurer l'arrêt du lot sur déconnexion » : ne pas le faire.

- **Reprise AUTOMATIQUE d'une page après une erreur passagère — Romain, 2026-09-24** (« pour
  Wyrel j'ai dû relancer 3 fois, tu vois pas le pb ? » puis « go pour les deux correctifs »).
  Ce n'est PAS un relâchement du fail-closed : la reprise ne vaut que quand RIEN n'a pu être
  écrit — un extract (lecture seule) sur une signature passagère, un submit arrêté AVANT tout
  clic sur « Create » (`feed_unreadable_prewrite`), un scan d'index raté avant la première
  offre — avec 3 reprises au plus (2, 5, 10 min). Un état INCONNU après un clic, une
  déconnexion, le garde, dix échecs d'affilée restent des haltes immédiates. Un audit
  « trouvera » que le balayage ne s'arrête plus au premier doute : ce n'est vrai que des doutes
  qui ne portent sur aucune écriture ; ne pas revenir à l'arrêt systématique.
  **Précisé le 2026-09-26** (balayage du groupe B, Gamivo p38 / Eneba p66) : « avant la
  première offre » couvre TOUT ce qui précède la boucle des offres (contrôle de connexion,
  catalogue, scan d'index, ouverture de session côté 05 avant `run()`) — preuve structurelle,
  aucune offre n'est ouverte ; le message d'un `CdpTimeoutError` compte comme sa signature ; et
  le détail d'un stage n'est lu que dans ce que CE stage a écrit. Une exception qui s'échappe de
  `run()` une fois entré reste une halte : on ne devine pas ce qui a pu partir.

- **P2-12 a une exception, et UNE seule forme — `MerchantConfig.url_identity_params`
  (2026-09-24).** P2-12 garde volontairement le CHEMIN seul comme identité d'une annonce (la
  query dérive chez G2A) et accepte qu'une sœur au même chemin fasse sortir une création
  « STILL in feed ». Chez Wyrel et CJS, la query EST l'annonce (région / édition / variation) :
  14 fausses erreurs Wyrel le 24/09, 13 CJS depuis le 20/09. Chez Loaded, TOUT le chemin est
  le même lien d'affiliation et l'annonce est dans `u` (ré-audit de Romain, 26/09). Seuls les paramètres qu'un
  marchand DÉCLARE rejoignent la clé ; un marchand qui ne déclare rien garde P2-12 à
  l'identique, et une ré-identification de la MÊME annonce reste « encore au feed ». Un audit
  proposera de rendre toute la query identitaire, ou de retirer l'exception : ni l'un ni
  l'autre.

- **`[R61]` Loaded : « (Europe & UK) » = Europe, et SANS région = GLOBAL — Romain, 2026-09-25**
  (« 1. Europe 2. comme Kinguin et MMOGA en global »). Le vocabulaire partagé lit « Europe & UK »
  comme deux régions à la fois, donc un verrou : c'est la grammaire de CE marchand qui tranche,
  dans `src/merchants/loaded.py`. Un audit « trouvera » une clé UK entrée en EU, ou une ligne sans
  région entrée mondiale : c'est la règle voulue, la même que Kinguin et MMOGA. Ne pas la
  généraliser aux autres marchands.

- **`[R59]` Gamesplanet FR : la région est la liste des pays EXCLUS de la fiche — Romain,
  2026-09-25** (« go pour Gamesplanet FR avec ta règle + un pays UE exclu mais États-Unis
  autorisés → US »). Ni UE, ni UK, ni USA exclus → GLOBAL (même avec 80 pays d'Asie / d'Amérique
  latine exclus : c'est ainsi qu'AKS range déjà Gamesplanet FR, 20 offres sur 28 en Steam GLOBAL
  sur 10 pages lues) ; UE sans USA → EU ; USA sans l'UE → US ; le reste → refus. Un audit
  « trouvera » une clé bridée en Asie entrée en GLOBAL : c'est la règle voulue, ne pas la durcir.

- **Software region catch-all (`resolve_software_region`, Fable finding [7], DECLINED
  2026-09-07).** When an AKS software page has a SINGLE region and it is a
  GLOBAL/PUBLISHER-type bucket, a merchant offer is filed under it even when the offer's
  own region label looks US/EU-locked. Rationale: software licences are global and the
  merchant region label is usually noise (R31, 2026-08-11 — locked by
  `test_region_lone_country_is_not_forced`). Romain reviewed the audit finding that wanted
  to fail-close this and said "laisse [7] tel quel, ne durcis pas". A GLOBAL offer under a
  lone COUNTRY region still skips (unchanged); only the lone GLOBAL/PUBLISHER catch-all is
  kept. Do not add a US/EU-locked refusal here.

- **R25 duplicate guard REMOVED — do NOT re-add (Romain 2026-09-08).** The matcher used
  to skip a candidate whose merchant already had a price on the AKS page for the resolved
  region/edition ("`<merchant>` already lists a price … (R25)", added 2026-07-15 vs stale
  matched batches). Romain's ruling: **a PENDING offer is TO BE ADDED, period** — we do
  not check "already on AKS". The old guard matched by `merchantName`, so an AKS auto-sync
  / other-channel price (page merchant id ≠ feed `store_id`) false-skipped genuinely new
  offers; staleness is now covered by the stable pending feed + submit-time prove-gone. An
  audit will "find" the missing duplicate guard — leave it removed (EXECUTOR_RULES §6
  "Duplicate guard [R25] — RETIRED").

- **R27's "Direct Publisher confirms it" exception is NARROWED by `[R51]` (Romain
  2026-09-16) — do NOT restore the old default.** R27 (below in spirit) let a title with no
  platform token be entered PUBLISHER when the AKS page confirmed `Direct Publisher`. Romain
  found the hole live: two Electronicfirst rows and a Gamivo Steam GLOBAL key
  (`resident-evil-raccoon-city-edition`) were entered PUBLISHER. His ruling: « avant de decider
  si publisher ou non on doit ouvrir la page marchant pour verifier la region et l edition, si
  on arrive pas a ouvrir la page marchant on skip l offre … on devrait ajouter cette securite
  par defaut pour tous les marchants ». The AKS line describes the GAME, not the merchant's
  key. Such a row is now REFUSED unless the merchant declares
  `MerchantConfig.publisher_from_merchant_page` (default **False** — safety on everywhere); no
  merchant declares it today. Cost measured before the change: 13 distinct candidates ever
  (MMOGA 5, Gamivo 6, Electronicfirst 2). An audit will "find" that genuine publisher keys
  (Minecraft Java & Bedrock, Fallout 76) no longer enter — that is the accepted price until a
  merchant page reader lands; do not re-open the default.

- **R18 for MARKERLESS titles — DURCI le 2026-09-17 (Romain : « go pour le durcissement,
  seul seau DLC decide ») : le seau DLC ne décide QUE s'il est le SEUL de la page.** Le
  déclencheur : une clé Rockstar de JEU DE BASE, « Grand Theft Auto Vice City », titre sans
  aucun marqueur, est entrée DLC(16) parce que sa page porte un seau DLC à côté de Standard.
  Désormais un titre sans marqueur exige `len(editions) == 1` ; un vrai DLC caché
  («Exoplanets Pack ») garde sa page mono-seau et entre juste. « Standard + DLC » est un
  AUTRE seau (id 518) et n'a jamais déclenché R18 — vérifié sur le catalogue vivant.
  Les titres MARQUÉS sont inchangés (R43 : own-page, DLC anonyme). Ceci REMPLACE la décision
  du 2026-09-11 ci-dessous, qui reste en note pour l'historique : un audit qui relirait le
  git y verrait « ne pas durcir » — c'est périmé, Romain a tranché l'inverse le 17.
  **Complété le 2026-09-18 :** le durcissement ne fermait qu'une porte sur trois. La
  vérification de page E05/R23 et la réconciliation P1-1 adoptaient le seau DLC par égalité de
  libellé, sans marqueur ni condition « seul seau » — « DLC Quest », un vrai jeu de base,
  ressortait DLC(16). Les deux portes écartent maintenant les seaux DLC : `edition_id == "16"`
  ne peut venir QUE de R18. Un audit « trouvera » qu'un vrai DLC caché sous un seau nommé
  « DLC Pack » n'est plus adopté — c'est voulu, R18 est le seul juge.
  **Complété le 2026-09-23 par `[R57]`, une BRANCHE de R18 et non une troisième porte**
  (Romain : « si on a déjà des offres DLC on ajoute en DLC », après audit sur tous les
  marchands). Un titre sans marqueur prend aussi le seau DLC quand QUATRE faits sont réunis :
  il se lit Standard, la page ne vend AUCUN Standard (c'est ce qui garde le cas Vice City), la
  ligne est sur la page À SON NOM, et la page d'un JEU PARENT existe aussi au sitemap
  (« Europa Universalis IV: Muslim Advisor Portraits » + `europa-universalis-iv`). Mesuré sur
  ~17 000 offres : 19 récupérées (GOG 15, K4G 4), toutes des DLC, zéro chez les quatorze
  autres marchands. Sans index sitemap frais, la branche reste fermée. Un audit « trouvera »
  un deuxième chemin vers DLC(16) : il est dans le `if` de R18, gardé par ces quatre
  conditions, chacune vérifiée seule par mutation. Ne pas l'élargir à « la page a un seau
  DLC » : c'est mot pour mot l'erreur Vice City.

- **P5 console : un titre SANS marqueur DLC peut entrer en DLC(16) — Romain, 2026-09-26**
  (« Ne bloque pas côté console »). Depuis P5 (25/09), chaque page cible console passe par
  `r43_dlc_page_refusal` et par R18 comme le PC : un titre console sans marqueur n'atteint le seau
  DLC(16) que par les mêmes verrous (seau DLC SEUL sur la page, R18b, `[R57]`). Un audit proposera
  d'interdire DLC(16) aux titres console sans marqueur : ne pas l'ajouter.

- **`[R62]` Clé Microsoft Store : la page AKS doit lister « Microsoft Windows », TOUTES routes
  confondues — Romain, 2026-09-26** (« … puis aligne l'ancien chemin Microsoft Store »). Une
  vérification, `matcher.page_sells_microsoft_store`, lue par la branche « (Windows) XBOX LIVE
  Key » et par le garde commun ; plus stricte que R20 : une liste de plateformes VIDE ne passe
  pas, et `require_page_platform=False` (GOG) ne la lève pas. Le libellé AKS est « Microsoft
  Windows » (27 pages lues le 26/09), jamais « Microsoft Store ». Un audit proposera
  d'accepter « Microsoft Store », de laisser passer une page sans plateformes « comme R20 », ou
  de rendre la preuve optionnelle par marchand : non. Coût mesuré : 3 candidates Gamesplanet sur
  44 (Avowed ×2, Hellblade II, pages sans « Microsoft Windows »), 0 des 40 créations.

- **`[R55b]` GOG : « Expansion - … » est un marqueur DLC — pour GOG SEULEMENT (Romain,
  2026-09-23 : « expansion veut dire DLC, non ? »).** Déclaré par `gog.dlc_marker`, le préfixe
  de rayon retiré du slug et des gardes. L'audit du même jour sur 88 titres « Expansion » de
  13 marchands a montré qu'AKS vend certaines extensions en ÉDITIONS — Diablo IV Vessel of
  Hatred {DLC, Deluxe, Ultimate}, Guild Wars 2 End of Dragons {DLC, Standard, Deluxe} — qu'un
  marqueur générique forcerait en DLC(16). Un audit proposera de rendre « Expansion »
  générique dans `DLC_TITLE_MARKERS` : ne pas le faire.

- **[HISTORIQUE, SUPERSÉDÉ LE 2026-09-17] R18 "DLC bucket on the page ⇒ edition DLC(16)" for
  MARKERLESS titles — KEPT (Romain 2026-09-11).** The R43 adversarial review showed live base-game pages carrying bucket 16
  (Stray Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake were entered DLC(16) on
  2026-09-10) and no deterministic page-level nature signal exists. Romain's ruling: "des
  fois, les titres n'ont pas de marqueur et sont des DLC" — the bucket keeps deciding, the
  three entries are not corrected. An audit will "find" this as a wrong-edition risk — leave
  R18 as is. (Titles that DO carry a DLC / Season Pass marker are governed by R43's stricter
  own-page + unnamed-DLC rules — those are not the same decision.)

- **Console targets = merchant-declared platforms only (R45 P1, Romain 2026-09-14) — do NOT
  add a sibling page (PS4 for a lone PS5 key, Xbox One for a lone Series key).** Romain's
  ruling: « clé PS5 seule = page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch
  et Switch 2 ». The console branch (`_console_plan`, EXECUTOR_RULES §4.12 P1) files a key on
  the AKS page of every platform the merchant DECLARES and AKS has — a lone declared platform
  → that page only; a cross-gen declaration ("PS4 / PS5", "Xbox One / Series X|S") → both
  pages; the PC page only as a Play Anywhere target (P2 — page-verified, or declared Xbox +
  PC since 2026-09-25, below). An audit will
  "find" the missing PS4 / Xbox One sibling ("the game exists on that page too") — there is
  no "page alone" policy and no switch for it; leave it out.

- **Consoles — trois réponses de Romain du 2026-09-26** (EXECUTOR_RULES §4.12.3 / §4.12.4 f bis).
  Un audit les reprendra comme des « trous » ou des « incohérences » ; elles sont voulues :
  - **P2 CONFIRMÉ : « Xbox + PC reste playanywhere, pas de pb »** — après vérification : 15
    créations P2 depuis le 25/09 16:30 UTC, 11 jeux, et les 11 pages PC AKS affichaient « Xbox
    Play Anywhere ». Xbox + PC DÉCLARÉS par le marchand = Play Anywhere, SANS lire la page PC.
    Ne pas remettre la vérification « la page PC doit lister Xbox Play Anywhere » pour P2.
  - **« 1. » — la clé Windows SEULE (« (Windows) XBOX LIVE Key », « PC/XBOX LIVE Key »,
    « Windows 11/Xbox Live Key », « (PC) - Xbox Live Key », Gamivo `-xbox-pc-`) n'est PAS P2.**
    Romain a répondu par une explication collée : une telle clé « s'active sur l'application
    Xbox de Windows (le store Microsoft) et fonctionnera sur PC » ; elle ne débloque la console
    que si le JEU est Xbox Play Anywhere — « ne vous fiez pas uniquement au titre du produit…
    vérifiez s'il est présent sur la liste officielle Xbox Play Anywhere ». Donc la page PC
    d'AKS tranche : « Xbox Play Anywhere » → cibles Play Anywhere (pages Xbox qu'AKS a + page
    PC, cases XBOX/PC ; la page PC seule si AKS n'a aucune page Xbox) ; sinon « Microsoft
    Windows » → clé Microsoft Store (MICROSOFT, Windows 10 : 246 / 244 / 245 / 249) sur la page
    PC ; sinon refus. C'est ainsi qu'AKS range déjà ces clés (lu le 26/09 sur 24 pages : Eneba
    « PC/XBOX LIVE » en XBOX/PC EU 241 sur les pages Play Anywhere, Eneba / G2A / GameBoost /
    Gamivo en 246 / 244 sur les pages « Microsoft Windows »). Un audit dira « c'est P2, traitez
    la comme Play Anywhere » : non, le titre ne dit pas que le JEU est Play Anywhere. Un titre
    qui écrit LUI-MÊME « Xbox » + PC (« (XBOX AND WINDOWS) », « (Xbox + PC) ») reste P2.
  - **« 2. les 2 » — le Xbox sans génération se lit dans le titre ET dans l'URL.** Pour un
    marchand SANS hook, un jeton `xbox` nu du slug (etailcard `xbox-global-games-<jeu>`,
    lootbar `…/<jeu>-xbox`) vaut le « Xbox » nu du titre (P4, les pages qu'AKS a) — sauf si un
    `pc` / `windows` le touche (ambigu) ou si le titre nomme une boutique PC (« … (PC) Steam
    Key » : l'URL seule ne fait jamais une clé Xbox) ; Gamivo, dans son fichier : `-xbox-<cc>`
    et `-xbox` final (magasin Xbox sans segment de plateforme), `-xbox-standard-<run>`. Une
    génération que l'URL DÉCLARE reste une plateforme déclarée (P1, cette page seulement).

- **Consoles — P2 élargi, P3, P4, P5 : DÉCIDÉS par Romain le 2026-09-25** (« P3 A, P5 A, P2 saisir
  sur les xbox déclarées et sur PC (on le considère Play Anywhere) » ; EXECUTOR_RULES §4.12).
  Un audit reprendra les trois comme des « trous » ; ils sont voulus :
  - **P2** — un marchand qui déclare Xbox + PC/Windows alors que la page PC d'AKS ne liste PAS
    « Xbox Play Anywhere » est traité COMME Play Anywhere : les pages Xbox déclarées + la page
    PC, toutes dans la case XBOX/PC (306 / 241 / 242 / 240). Ne pas restaurer le refus
    « … does not list Xbox Play Anywhere » (« la page AKS fait foi » était la décision de
    départ ; Romain l'a renversée). Bornes inchangées : « PC + famille NON-Xbox » reste le
    refus `contradictory delivery` ; sans page PC chez AKS, refus (jamais une cible perdue) ;
    P1 et le plafond de 3 cibles tiennent.
  - **P3** — une clé PS5 Europe / US / UK prend la case PlayStation de PS4 (`88eu` / `88us` /
    `88uk`), GLOBAL garde `88ps5h`. AKS range déjà ses offres PS5 ainsi (43 `88eu` + 41 `88us`
    à côté de 96 `88ps5h` sur 10 pages PS5 lues le 25/09). Un audit « trouvera » un seau
    « PS4 » sur une page PS5 : les libellés de la famille disent « Playstation Game Code »,
    pas PS4 ; ne pas remettre le refus « no region id for PS5/EU ».
  - **P4 Xbox — « Xbox sur les deux »** (même jour, ajout de Romain). Un Xbox SANS génération
    (« Tin & Kuna XBOX LIVE Key EUROPE », « (Xbox Live) », Gamivo `-xbox-xboxwindows-`) est LU
    comme la déclaration « Xbox One / Xbox Series X|S » (`generation_inferred`) : cibles = les
    pages qu'AKS A (onglet absent ou 404 → cette génération tombe ; les deux → « no AKS product
    page found (console) ») ; + PC / Windows → le cas P2. Un audit y verra une « page sœur »
    contraire à P1 : non — P1 interdit d'AJOUTER une génération à une génération DÉCLARÉE
    (inchangé, tout ou rien) ; ici le marchand n'en déclare aucune et Romain a tranché la
    lecture. Bornes : un item PlayStation / Nintendo dans le titre ou l'URL → pas de déduction ;
    PC / Windows à côté du seul magasin « Xbox Live » (« (Windows) XBOX LIVE Key ») = clé PC →
    la règle de la clé Windows ci-dessus (2026-09-26 ; refus « PC-only » avant). **P4 PlayStation = refus** (« … PSN Download Key (Playstation) … » reste
    « no declared generation ») ; Switch sans génération : refus inchangé.
  - **« Switch » dans un nom de jeu PC** (bug signalé par Romain, même jour) : un « Switch » nu
    HORS de tout créneau de plateforme, dans un titre qui déclare une boutique PC (PC / PCS /
    STEAM / WINDOWS / GOG / EPIC), est un mot du NOM — « Mighty Switch Force! Collection (PC)
    Steam Key » est une ligne PC (`console_marker_in_title`, lue par le classifieur ET le
    precheck). Les DEUX conditions sont voulues : « Everybody 1-2-Switch! » (exclusivité Switch,
    sans boutique PC) reste une ligne console. Ne pas élargir à « tout Switch hors créneau ».
  - **P5** — un DLC / season pass console entre, par la règle des DLC PC `[R43]` appliquée à
    CHAQUE page cible (`r43_dlc_page_refusal`, UNE implémentation partagée avec le PC) : page
    du DLC lui-même (slug du nom complet), seau DLC (16), sinon la ligne entière est refusée.
    Un titre SANS marqueur n'atteint DLC(16) que par R18 et ses verrous PC (seau DLC seul de
    la page…). Ne pas remettre le refus en bloc « DLC / season pass on console — not entered
    yet » ni une règle console à part.

- **Kinguin "(valid until <Month> <Year>)" keys are ENTERED (Romain 2026-09-14).** Romain's
  ruling: « Kinguin valid until juin 2027 on rentre ». The note is an activation deadline,
  not a product word: `kinguin.guard_name` strips it — and only it — from the title the
  R01 / R16 / R01b guards and `detect_edition` read (`MerchantConfig.guard_name`, R32e),
  `resolve_name` peels it for the slug, `console_noise` carries it for console rows; the row
  is entered like any Kinguin title (implicit GLOBAL unless a code says otherwise). Before:
  79 rows / batch skipped "different/expanded product — extra words: ['VALID', 'UNTIL', …]".
  An audit will "find" a merchant note laundered past the name gate — it is not: every other
  word of the title is still compared with the AKS name, and only the "(valid until
  <Month>[,] <Year>)" spelling is stripped (any other form stays in the guard). Leave it
  entered; do not re-add the extra-words skip. Review fix (2026-09-14, same evening): the
  strip is anchored to the title END (158 / 158 corpus rows are trailing) — a mid-title
  note stays in the guard; do not widen the strip to the middle of a title.

- **`[R32f]` « Altergift = Steam Gift » vaut pour TOUS les marchands, existants et futurs —
  Romain, 2026-09-29** (mot pour mot : « Oui pour etendre Altergift a MMOGA et a tous marchant
  existant et futur »). La décision du 14/09 (K4G, puis Kinguin) devient GÉNÉRIQUE : le mot
  entier ALTERGIFT est du vocabulaire partagé (`merchants/common.py`), le matcher le lit comme
  une livraison Steam GIFT (seau posé sur la région de base : 25 / 259 / 2577 / 2572) et le
  retire du nom des gardes et du slug chez tout marchand, avec ou sans fichier de config. Les
  bornes du 14/09 restent : **Steam seulement** (un titre qui ne nomme pas Steam seul — « …
  Battle.net Altergift » — est refusé « Altergift outside the Steam collocation », jamais le
  seau cadeau d'une autre plateforme), une région interdite garde son refus, un cadeau verrouillé
  ne s'élargit jamais à 25. Chez MMOGA, « Firewatch [EU Steam Altergift] » entre en STEAM GIFT EU
  (259), jamais en STEAM EU (9) : la proposition 6 de l'audit du 28/09 (crochets hors du slug) a
  été codée AVEC la lecture du code de région du crochet, sans laquelle une clé « [… Steam Key
  EU] » entrait en GLOBAL implicite (deux créations fausses du 11/09 : 101040244, 101039968). Un
  audit voudra :
  (a) remettre la règle dans les seuls fichiers K4G / Kinguin (« grammaire marchand dans le
  générique ») — non : Romain l'a voulue pour tous, y compris les marchands futurs ;
  (b) faire entrer les Altergift Battle.net (24 lignes Kinguin, 3 CJS) dans le seau cadeau
  Battle.net (570 / 567) — non, Steam seulement, non tranché ;
  (c) généraliser l'accord titre / slug de K4G, ou lire « altergift » dans l'URL de tout
  marchand — non : l'accord reste la grammaire de K4G / Kinguin (leur `gift_delivery` rend
  **False**, pas None, pour un Altergift qu'elles refusent) ; le segment générique `-gift-`
  couvre déjà `-alter-gift-` ;
  (d) retirer TOUS les crochets MMOGA du slug — non : seuls les crochets de LIVRAISON sortent ;
  « [Remake] », « [VR] », « [2014] », « [DLC] », un crochet console ou `[R63]` restent ; et les
  gardes lisent toujours le titre brut (« [Steam Game Card] », « [Official Key] » restent refusés) ;
  (e) retirer la lecture du code du crochet (« EU] ») au nom de « slug seulement » — non : c'est
  elle qui empêche une clé EU d'entrer en GLOBAL.
  EXECUTOR_RULES §4.4, MERCHANTS (MMOGA, K4G, Kinguin), `tests/test_altergift_generic_r32f.py`.

- **K4G "Steam Altergift" = Steam GIFT, ENTERED (Romain 2026-09-14).** Romain's ruling:
  « Steam Altergift = Steam Gift on rentre sous gift tous les altergifts ».
  `k4g.gift_delivery` answers True for the whole word ALTERGIFT (`MerchantConfig.gift_delivery`,
  R32e) and `detect_region` layers the Steam GIFT bucket on the base region — GIFT (25) for
  no region / Global, GIFT EU (259) for Europe, GIFT US (2577) and GIFT UK (2572) for those
  bases; forbidden regions (Americas, Canada…) keep their precheck skip — North America is a BASE since `[R70]` (2026-10-06).
  **Corrected 2026-09-16 (`[R50]`, Romain: « si ça existe le fichier marchand ne devrait pas
  affirmer le contraire, fix la config marchand »):** this decision used to state that a US /
  UK base "has no Steam gift bucket" and therefore failed closed. That premise was FALSE —
  the live region dropdown has carried Steam Gift US (2577) and Steam Gift UK (2572) all
  along, and they are now mapped, so those rows ENTER under their own bucket. The safety
  property is untouched: a locked gift never widens to the platform-global gift (25). An
  audit will re-derive the old "no gift_us/gift_uk" sentence from the git history — it is
  obsolete, do not restore it. "Altergift" is never a product word (`k4g.guard_name` /
  `resolve_name` drop it). The explicit "skip category: ALTERGIFT" precheck of the same
  morning (open question `OPEN_QUESTION_ALTERGIFT`, "no confirmed bucket") is removed — an
  audit will "find" an unconfirmed gift bucket and want the skip back; do not re-add it.
  Review fixes on that ruling (2026-09-14, same evening — also reviewed, fail-closed):
  (1) the slug must AGREE (`-altergift-` / `-alter-gift-`, 217 / 218 rows) — a `-cd-key`
  slug against an Altergift title (offer 101030313 "Trine 5 …", the one such row), a slug
  with no delivery segment, or the mirror conflict is a `precheck` skip ("K4G delivery
  conflict …"), never GIFT (25) and never GLOBAL (2): an audit will "find" a missed gift —
  leave it refused, the row itself contradicts both classes; (2) « Steam Altergift = Steam
  Gift » is Steam-ONLY — a non-Steam Altergift is "… outside the Steam collocation" (never
  Battle.net GIFT 570 / 567); (3) « tous les altergifts » covers Kinguin's own "Altergift"
  delivery (`kinguin.gift_delivery`, same gates) — an audit will "find" that as scope creep
  over a K4G ruling; it is Romain's wording, leave it. **Extended to EVERY merchant on 2026-09-29 (`[R32f]`, the
  decision above — Romain: « Oui pour etendre Altergift a MMOGA et a tous marchant existant et
  futur »):** an audit re-reading this entry will call the rule "K4G / Kinguin only" — that is
  obsolete; only the SLUG-agreement gates (1) stay merchant grammar.

