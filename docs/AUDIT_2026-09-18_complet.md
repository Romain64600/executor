# Audit complet — 2026-09-18

Portée : tout le dépôt au commit `9cc9960`, avec priorité à la **logique métier**.
Méthode : 12 dimensions auditées en parallèle, chaque constat ensuite attaqué par deux agents
indépendants — l'un chargé de le **réfuter**, l'autre de le **reproduire en exécutant le vrai
code** — puis une passe de complétude sur ce que les 12 silos avaient manqué.
93 agents, 2 758 appels d'outils, 2 h 13.

Résultat brut : 40 constats, 2 réfutés, 38 retenus, 3 ajoutés par la passe de complétude.
Après dédoublonnage (trois dimensions avaient trouvé le même défaut Gamerall, deux le même
défaut de la branche console) : **36 constats**, dont **8 P1**.

Les décisions arrêtées de Romain listées dans `AGENTS.md` (« Reviewed decisions — do NOT
re-tighten ») étaient interdites aux auditeurs. Aucun constat ci-dessous ne les rouvre.

## Ce que j'ai vérifié moi-même, à la main

Sept constats ont été reproduits ou relus ligne à ligne par moi, indépendamment des agents :

| Constat | Vérification |
|---|---|
| `matcher.py:3169` — jeu de base entré en DLC | `DLC Quest` + page `{1:Standard, 16:DLC}` → **DLC(16)**. Mono-seau → Standard(1). `{1, 'DLC Pack'}` → **DLC Pack(4711)**. |
| `matcher.py:3360` — branche console sans garde de région | URL Gamerall `/playstation/…-ps5` → `families=('PS5',)`, `region_base=None` → **GLOBAL implicite**, `offer_page_resolver` jamais appelé. |
| `gamerall.py:60` — jeton `UPLAY` | « Assassins Creed Mirage (Ubisoft Connect) » → `SKIP: platform conflict title=UBISOFT vs page=UPLAY`. |
| `submit_manager.py:1128` — bouton Arrêter | `stop_active()` → `{'stopped': None}` en **HTTP 200** ; `busy()` retombe pourtant sur le marqueur disque ; aucun `.js` ne lit `stopped`. |
| `13_sort_sql.py:98` — mesure CLI | `_like('%digital_extras%', '…-digital-extras')` = **True**, `'digital_extras' in url` = **False**. |
| `validation.py:146` — `approve` | `if not entry.get("approve")` : la chaîne `"false"` est vraie en Python. |
| `sort_sql_view.py:255` — scan tronqué | `grep -n coverage` → **zéro occurrence**, alors que `sort.js:153` affiche déjà la couverture partielle. |

## Les trois que je corrigerais en premier

1. **`submit_manager.py:1128` — le frein d'urgence ne freine pas.** Un run lancé au terminal
   apparaît bien dans la console (le marqueur disque est lu), le bouton « Arrêter » s'affiche,
   le clic répond 200 et l'écran dit « Arrêt demandé » — mais rien n'est arrêté. **C'est vrai
   en ce moment même** : le sweep de l'ancien VPS a été lancé en ligne de commande.
   Correctif serveur, ~6 lignes, aucun changement côté navigateur.

2. **`matcher.py:3169` — le durcissement R18 du 17/09 n'a fermé qu'une porte sur trois.**
   `DLC Quest`, un vrai jeu de base que `EXECUTOR_RULES.md §4.3 (f)` nomme explicitement,
   repart en DLC(16) par la vérification de page E05/R23, qui adopte le seau DLC par simple
   égalité de libellé — sans exiger de marqueur, sans la condition « seul seau ». C'est
   exactement la classe d'erreur que tu as fait corriger hier.

3. **`13_sort_sql.py:98` + `sort_sql_view.py:255` — la mesure SQL ment encore, deux fois.**
   Le correctif `_` = joker d'hier n'a été posé que sur la vue console ; le script CLI que le
   README documente pour auditer ta liste quotidienne sous-compte toujours. Et un scan tronqué
   (`--max-pages 60` par défaut) est rendu `measured: true`, donc un collatéral nul par
   absence de données passe pour un collatéral nul par sûreté.

## Le reste en un coup d'œil

| | Emplacement | Constat |
|---|---|---|
| **P1** | `scripts/13_sort_sql.py:98` | Le stage 13 mesure encore en sous-chaîne littérale : il annonce 0 ligne là où le LIKE en déplace 2 |
| **P1** | `src/admin/sort_sql_view.py:255` | Un scan TRONQUÉ est déclaré « mesuré » : le collatéral tombe à zéro par couverture partielle |
| **P1** | `src/admin/submit_manager.py:1128` | Le bouton « Arrêter » ne peut pas arrêter un run lancé en ligne de commande, mais répond 200 et les trois consoles annoncent « Arrêt demandé » |
| **P1** | `src/admin/validation_io.py:177` | Surcharge opérateur : changer la région seule accepte un seau d'une AUTRE plateforme — la garde symétrique existe mais ne ferme que dans un sens |
| **P1** | `src/matcher.py:3169` | Le durcissement R18 du 17/09 ne ferme qu'une des trois portes vers le seau DLC(16) |
| **P1** | `src/matcher.py:3360` | La voie console n'ouvre jamais la page marchand : région GLOBAL implicite au lieu du refus fail-closed |
| **P1** | `src/matcher.py:930` | Un nom de pays dans le TITRE DU JEU est lu comme verrou de région → l'offre part en MOVE vers Blacklist(8) |
| **P1** | `src/validation.py:146` | « approve » est lu en vérité Python : la chaîne "false" approuve l'offre |
| **P2** | `docs/EXECUTOR_RULES.md:670` | La spec autoritaire et docs/MERCHANTS.md affirment que trois marchands sont hors liste blanche safe-auto ; le code les y a mis |
| **P2** | `scripts/05_submit.py:566` | FC3 : un run AVORTÉ (aucune écriture) remet à zéro le compteur cross-process de runs bloqués |
| **P2** | `scripts/10_data_entry_auto.py:506` | `write_marker` écrase un marqueur VIVANT : un simple `--dry-run` rend le sweep de 30 h invisible et rouvre le lancement depuis la console |
| **P2** | `scripts/10_data_entry_auto.py:567` | Un stop opérateur efface les haltes fail-closed déjà enregistrées et rend le code de sortie vert |
| **P2** | `src/admin/app.py:518` | La porte anti-collatéral de la promotion ne se ferme pas quand la mesure est impossible |
| **P2** | `src/admin/static/app.js:1099` | app.js n'a aucun jeton de génération : une réponse tardive attribue le bilan d'un run au run suivant et ressuscite le sondage après stopPolling() |
| **P2** | `src/admin/static/sql.js:53` | « Copier seulement les requêtes sans désaccord » copie TOUT quand rien n'est mesuré |
| **P2** | `src/extractor.py:622` | Le sondage de pagination du sweep passe par le mode « slice », qui n'a pas la garde nav_max=0 : un feed de 107 pages peut être balayé sur 1 page et déclaré complet |
| **P2** | `src/matcher.py:1245` | Le mot « Global » dans le NOM DU JEU écrase une région US/UK réelle → clé verrouillée saisie en GLOBAL |
| **P2** | `src/matcher.py:2799` | Le garde « DLC anonyme » de R43 s'ouvre dès que le seau Standard de la page n'est pas la clé "1" |
| **P2** | `src/matcher.py:2934` | Le sauvetage par « extras » écrase le palier d'édition du titre (Deluxe classé sous l'édition de base) |
| **P2** | `src/matcher.py:3188` | La règle absolue « on n'entre JAMAIS de bundle » n'est verrouillée par aucun test |
| **P2** | `src/matcher.py:3457` | La plateforme réelle de la page AKS cible n'est jamais vérifiée : `page_platform` est extrait puis jeté |
| **P2** | `src/matcher.py:579` | « MICROSOFT » absent de NOISE_TOKENS : toute ligne dont le titre nomme le Microsoft Store est refusée en « extra words » (le défaut ROCKSTAR, non corrigé pour Microsoft) |
| **P2** | `src/matcher.py:617` | Un code pays 2 lettres en fin de titre (DE, TH, ID…) est avalé comme « marqueur de langue » : la clé verrouillée part en GLOBAL(2) |
| **P2** | `src/matcher.py:687` | Les accents ne sont repliés ni pour l'identité ni pour le slug : le repli de 2026-09-16 s'est arrêté au precheck |
| **P2** | `src/matcher.py:735` | R01 exige l'apostrophe et les mots-outils au caractère près, alors que le générateur de slug sonde déjà les deux orthographes |
| **P2** | `src/merchants/g2a.py:122` | `console_pc_declared` absent chez G2A / GameSeal / Driffle / K4G : la garde P2 « Xbox + PC sans Play Anywhere » ne se déclenche jamais |
| **P2** | `src/merchants/gamerall.py:60` | Gamerall : le jeton de plateforme « UPLAY » n'existe pas dans le vocabulaire du matcher — 100 % des lignes Ubisoft Connect refusées sur un faux conflit |
| **P2** | `tests/test_submitter.py:2806` | Faux vert : le test qui « verrouille » la preuve de couverture du prove-gone-by-search ne l'atteint jamais |
| **P3** | `scripts/10_data_entry_auto.py:518` | `recap.json`, le contrat de la passe lu en direct par la console, est réécrit à chaque page sans écriture atomique |
| **P3** | `src/admin/app.py:310` | Le champ `browser` (état du verrou navigateur) est servi sur deux routes et lu par aucune page — le correctif du 2026-09-18 n'a jamais atteint le client |
| **P3** | `src/candidate_contract.py:234` | Un id primaire `null` entre dans l'empreinte sous la forme littérale « None » |
| **P3** | `src/merchants/eneba.py:54` | Commentaires périmés depuis [R50] : Eneba et MMOGA promettent un refus fail-closed pour Rockstar / Windows qui n'existe plus |
| **P3** | `src/submitter.py:1849` | Chemin by-urls : l'index de localisation est effacé après CHAQUE création, contre l'intention du commentaire qui le précède |
| **P3** | `src/submitter.py:310` | Le remap libellé→id live (« the wrong-edition fix ») est inerte pour tout seau de région à id non numérique — donc pour 9 des 21 seaux console de [R45] |
| **P3** | `src/validation.py:153` | Deux entrées approuvées pour la même empreinte : le lot entier s'arrête après le 1er ajout |
| **P3** | `tests/test_sort_sql_console.py:399` | La garde qui protège la décision « Kinguin valid until » ne ferme pas, et son test n'inspecte que la moitié de la surface |

## P1 — à corriger (8)

### P1.1 `scripts/13_sort_sql.py:98` — Le stage 13 mesure encore en sous-chaîne littérale : il annonce 0 ligne là où le LIKE en déplace 2

**Le défaut.** `measure()` cherche `needle in _slug(u)` — sous-chaîne littérale, sur l'URL amputée de sa query string (`_slug`, ligne 90). La correction `[P1]` du 18/09, qui compile le motif en LIKE MySQL (`_` = joker, `%` = `.*`, URL entière), n'a été appliquée qu'à `src/admin/sort_sql_view.py`. Le script CLI — celui que le README documente pour auditer la liste quotidienne AVANT de la lancer — ment donc toujours, dans le sens dangereux : il sous-compte.

**Comment ça casse.** Romain veut vérifier la règle `%digital_extras%` → 8 avant de la coller : `python3 scripts/13_sort_sql.py --run-id <scan> --check "%digital_extras%:8"`. Le script répond « vise 0 | collatéral 0 » et le verdict « 0 ligne(s) seulement — ne se généralise pas ». Or `_` est un JOKER en SQL : `UPDATE … WHERE url LIKE '%digital_extras%'` sélectionne bel et bien `…/some-game-digital-extras`. Deux vrais jeux partent en Blacklist avec un audit qui a dit zéro. Même chose pour `%costume_pack%` et `%digital_deluxe_content%` (les trois règles de `RULES` qui portent un `_`), et pour tout motif visant un paramètre d'URL, que `_slug` supprime alors que la colonne `url` le contient. Le mode `--rules`, qui passe les 53 règles en revue d'un coup, produit le même sous-comptage sur toute la liste.

**Vérifié directement.** Vérifié par moi : `_like('%digital_extras%', '…/some-game-digital-extras')` = **True**, `'digital_extras' in url` = **False**.

**Correctif proposé.** Une seule implémentation de la mesure, partagée — mais PAS en important depuis `src.admin.sort_sql_view` (cela ferait dépendre un script CLI de la vue admin). Remonter `_like_re` / `_like` (et leur commentaire d'origine, sort_sql_view.py:62-70) dans `src/sort_sql_promoted.py`, module que la vue importe DÉJÀ (`sort_sql_promoted.SAFE_PATTERN`, sort_sql_view.py:144), puis faire importer les deux côtés depuis là.

Dans `scripts/13_sort_sql.py` : supprimer `_slug` (l.87-90 — usage unique vérifié, la seule occurrence est l.98) et remplacer l.97-98 par `hits = [u for u in dest if _like(pattern, u)]`, en retirant le `needle = pattern.strip("%").lower()` devenu inutile.

Tant qu'on y est, même duplication à refermer : le `SAFE_PATTERN` local du script (l.56, `^[%A-Za-z0-9._/+-]+$`) est PLUS LÂCHE que le partagé (`src/sort_sql_promoted.py:29`, `^%[A-Za-z0-9._/+-]+%$` — qui exige les `%` encadrants


### P1.2 `src/admin/sort_sql_view.py:255` — Un scan TRONQUÉ est déclaré « mesuré » : le collatéral tombe à zéro par couverture partielle

**Le défaut.** `sort_sql_payload` charge `sort_plan.json` mais ne lit jamais son bloc `coverage` : un scan qui n'a lu que 60 pages sur ~639 est rendu avec `measured: true`, et les compteurs `collateral` / `conflict` — la SEULE garde de la voie SQL, puisqu'il n'y a plus de preuve après coup — sont calculés sur cet échantillon alors que l'`UPDATE` collé dans phpMyAdmin, lui, balaie toute la table.

**Comment ça casse.** Romain lance la commande documentée dans le docstring de `scripts/08_sort_plan.py` (« `python3 scripts/08_sort_plan.py` # full all-stores pass »). Le défaut `--max-pages 60` (08_sort_plan.py:57) fait lire 60 pages sur les ~639 que le feed annonce (chiffre du docstring de `start_sort_scan`, submit_manager.py:565) : `coverage = {partial: true, pages_fetched: 60, feed_last_page: 639, truncated: true}`. Ce run devient le plus récent, donc `_latest_sort_run` (tri par mtime, ligne 50-59) le choisit pour /sql. La page affiche « Mesuré sur le scan … » et `%-1-month-%` → 21 ressort à `collatéral 0` alors que sur le scan complet de 49 899 offres elle visait 232 lignes dont 35 vrais jeux (YouTube Premium, Duolingo — chiffres du message de commit 3e69139). Romain copie la requête : 35 jeux vendables partent en liste 21. C'est mot pour mot le piège « purs sur 10 % du feed, catastrophiques sur 100 % » que trois docstrings du module citent comme la catastrophe à éviter. Même effet avec le `--pages 3-10` proposé en exemple dans le même docstring.

**Vérifié directement.** Vérifié par moi : `grep -n coverage src/admin/sort_sql_view.py` → **zéro occurrence**, alors que `sort.js:153` affiche déjà « partielle — X / Y pages » pour ce champ.

**Correctif proposé.** Garder l'orientation proposée (refus aux portes, honnêteté dans la bannière — forcer `measured:false` viderait la page à chaque scan par défaut), avec quatre précisions :

1. Clé de décision : `coverage.truncated` UNIQUEMENT — jamais `coverage.partial`, câblé à `True` en dur (08_sort_plan.py:150) et donc incapable de discriminer.
2. Absence de `coverage` = TRONQUÉ (fail-closed). Le plan est lu partout en `.get(...)` ; un `sort_plan.json` sans le bloc (plan ancien, écrit à la main, autre producteur) ne doit pas être traité comme une couverture pleine.
3. Portes à fermer, par ordre de gravité :
   - `_mine` (sort_sql_view.py:131) retourne `[]` sur un scan tronqué. Une proposition est une RÈGLE PERMANENTE déduite d'un échantillon : la refuser franchement, ne pas se contenter de l'annoter. Même traitement pour `_conflicted_seeds`.
   - `measure_pattern` (l.275) remonte `coverage` ; la porte 


### P1.3 `src/admin/submit_manager.py:1128` — Le bouton « Arrêter » ne peut pas arrêter un run lancé en ligne de commande, mais répond 200 et les trois consoles annoncent « Arrêt demandé »

**Le défaut.** `busy()` retombe volontairement sur le marqueur disque pour faire apparaître dans les consoles un run lancé au terminal (`source: "cli"`), mais `stop_active()` ne connaît que `self._active` : sur ce run il renvoie `{"stopped": null, "reason": "aucun run en cours"}` en HTTP 200, et les trois consoles traitent tout 200 comme un succès — le frein d'urgence d'un sweep qui ÉCRIT sur AKS annonce un arrêt qui n'a jamais été demandé.

**Comment ça casse.** Sweep de nuit lancé au terminal : `python3 scripts/10_data_entry_auto.py --targets Kinguin:58 --all-pages` (scripts/10_data_entry_auto.py:506 pose le marqueur `state/active_run.json`, kind `data_entry_auto`). Romain ouvre /executor/auto : `resumeIfActive()` lit `busy = {kind:"data_entry_auto", source:"cli"}`, met `SWEEP_RUNNING = true`, affiche `#busy-ind` — donc le bouton « Arrêter », qui vit dans `.busy-ind` (auto.html:24). Il voit passer des créations douteuses dans le recap et clique « Arrêter ». POST /api/sort/stop → 200 `{stopped:null}`. auto.js:143 fait `await api(...)` puis `setStatus("Arrêt demandé (entre pages)…", true)` sans regarder `stopped` ; le bouton reste désactivé jusqu'à `endUi()`, donc il ne peut même pas réessayer. Le sweep continue à créer des offres sur le site vivant pendant des heures, l'écran affichant « Arrêt demandé ».

**Vérifié directement.** Vérifié par moi : `stop_active()` rend `{'stopped': None}` en 200 quand `self._active is None`, alors que `busy()` (l.1096) retombe bien sur le marqueur disque. Aucun `*.js` ne lit `stopped`.

**Correctif proposé.** Correction CÔTÉ SERVEUR UNIQUEMENT, ~6 lignes, aucun changement client requis, aucune capacité nouvelle.

Dans `stop_active()` (src/admin/submit_manager.py:1125-1128), remplacer le retour muet quand `self._active is None` :

    with self._mutex:
        active = self._active
    if active is None:
        marker = read_marker(self.repo_root)
        if marker is not None:
            raise SubmitStartError(
                "cli_run_not_stoppable",
                f"run lancé en ligne de commande ({marker.get('kind')} sur "
                f"{marker.get('run_id')}, pid {marker.get('pid')}) — "
                "arrête-le dans son terminal",
                detail={"run_id": marker.get("run_id"), "pid": marker.get("pid")},
            )
        return {"stopped": None, "reason": "aucun run en cours"}

Pourquoi c'est suffisant, vérifié dans le code : `SubmitStartError` a `http_status=409` p


### P1.4 `src/admin/validation_io.py:177` — Surcharge opérateur : changer la région seule accepte un seau d'une AUTRE plateforme — la garde symétrique existe mais ne ferme que dans un sens

**Le défaut.** `_apply_override` ne valide un `region_id` surchargé que contre le catalogue de session GLOBAL (`_catalog_entry(catalog["regions"], …)`), jamais contre `REGION_IDS[candidate['platform']]` — alors que la branche « changement de plateforme » juste en dessous (ligne 186-205) refuse fail-closed exactement la même incohérence, en la nommant : « region ids are PER-PLATFORM … the operator's screen and the write disagree ».

**Comment ça casse.** Candidat PC/STEAM (page cd-key, région EU id 9). L'opérateur ouvre la console d'admin ; le `<select>` région est peuplé avec `catalog.regions` ENTIER (src/admin/static/app.js:396 — les ~867 options de toutes les plateformes, aucun filtrage par plateforme côté client) : « Steam (2) », « PS5 (88ps5h) », « Xbox Series (300) », « Battlenet GLOBAL (45) » se suivent dans la même liste. Un mauvais clic sur « PS5 (88ps5h) » est ACCEPTÉ : le candidat devient platform=STEAM / region={label:'PS5 (88ps5h)', id:'88ps5h'}, mirroré dans targets[0], nouvelle empreinte recalculée. Aucun étage en aval ne rattrape : `src/validation.py`, `src/candidate_contract.py`, `scripts/04_validate.py`, `scripts/05_submit.py` et `src/submitter.py` ne référencent jamais `REGION_IDS` ; `resolve_catalog_id` retrouve l'option par son libellé et rend 88ps5h. Résultat publié : un seau PS5 écrit sur une page produit PC.

**Correctif proposé.** Dans la branche `if "region_id" in changes:`, après avoir trouvé l'entrée catalogue, exiger que l'id appartienne à la plateforme EFFECTIVE du candidat (celle d'après surcharge, donc `changes.get('platform', candidate['platform'])`) : `if str(entry['key']) not in {str(v) for v in REGION_IDS.get(platform_eff, {}).values()}` → `ValidationIOError('platform_region_mismatch', …)`, avec le même message que la branche plateforme. Complément utile côté UI : filtrer `catalog.regions` sur `REGION_IDS[candidate.platform]` dans `select('region', …)` (app.js:396) pour que l'écran ne propose pas un choix que l'API doit refuser. Verrouiller par un test symétrique de `test_admin_validation_io` (surcharge région seule vers un seau étranger → refus).

> Trouvé par la passe de complétude (les 12 dimensions l'avaient manqué), non contre-vérifié.


### P1.5 `src/matcher.py:930` — Un nom de pays dans le TITRE DU JEU est lu comme verrou de région → l'offre part en MOVE vers Blacklist(8)

**Le défaut.** Le balayage `for region in FORBIDDEN_REGIONS: if f" {region} " in padded` s'applique au titre ENTIER sans exiger de créneau de région : tout jeu dont le nom contient China / India / Russia / Japan / Poland / Ukraine / Australia… est refusé en « forbidden region: <PAYS> », puis routé par `aks_lists.suggest_target_list` vers la Blacklist (8) ou une liste régionale — alors que la ligne déclare GLOBAL dans son titre ET dans son URL.

**Comment ça casse.** Une ligne G2A réelle « Assassin's Creed Chronicles: China (PC) - Steam Key - GLOBAL », URL …-china-steam-key-global-i…, donne `precheck_skip` = 'forbidden region: CHINA' → `suggest_target_list` = '8' (Blacklist). Dans un sweep `scripts/10 --triage --move-execute`, chaque page s'auto-autorise canary→batch ([R36], §14) : aucun humain ne relit la page, et `aks_lists.is_blacklist_label` fait SAUTER la vérif RV2 présent-sur-cible (« éviction »). Un jeu légitime, vendable en GLOBAL, est donc physiquement sorti du feed de travail vers la Blacklist, sans revue et sans preuve sur la liste cible. Idem pour « Crusader Kings II: Rajas of India », « Cities: Skylines - Content Creator Pack: Modern Japan », « Ukraine War Stories », « Civilization VI - Poland Civilization and Scenario Pack » ; « Civilization VI - Australia … » part, lui, en liste 32 (Australie). La variante console est pire : `classify_console("Assassin's Creed Chronicles: China (PS4)", …)` rend region_label='CHINA' ET resolve_name="Assassin's Creed Chronicles" — le nom du produit est amputé du mot qui le distingue de ses deux jumea

**Correctif proposé.** Ancrer les noms de pays complets sur un CRÉNEAU de région, exactement comme le dépôt le fait déjà pour VIETNAM et les codes à 2 lettres (`_url_region_code`) : queue de titre après « - », groupe entre parenthèses, ou `-<marqueur>-<pays>` en fin de chemin d'URL ; et ne jamais déclencher sur un mot en milieu de titre quand le créneau de la ligne déclare déjà une région vendable (GLOBAL/EU/US/UK). Trois sites à corriger ensemble, sinon le correctif est à moitié fait : le scan titre (930), le scan URL (943-945, même collision sur `…-chronicles-china-steam-key-global`) et `_TRAILING_NOISE_PHRASES` (~1430, `*FORBIDDEN_REGIONS`) qui ampute le slug (« china » retiré → mauvaise page sondée même precheck corrigé). Ne PAS retirer les noms de pays de `FORBIDDEN_REGIONS` : cela rouvrirait le P1 du 2026-09-06 (verrou dans le slug → GLOBAL implicite). Ajouter enfin un test de non-régression sur la trilo

> Trouvé par la passe de complétude (les 12 dimensions l'avaient manqué), non contre-vérifié.


### P1.6 `src/matcher.py:3169` — Le durcissement R18 du 17/09 ne ferme qu'une des trois portes vers le seau DLC(16)

**Le défaut.** Le garde-fou « seul seau DLC décide » (ligne 3096-3097 : marqueur de titre OU len(editions)==1) ne protège QUE la branche R18. Deux autres producteurs d'édition adoptent le seau DLC de la page par simple égalité de libellé, sans exiger de marqueur et sans la condition len==1 : la vérification page R23/E05 (ligne 3169, `if ekey == want_key`) et la réconciliation P1-1 (ligne 3217). Il suffit que `detect_edition` rende DLC(16) — ce qui arrive dès que `\bDLC\b` figure dans le titre OU dans le slug de l'URL marchande — pour qu'un JEU DE BASE reparte en DLC(16), exactement la classe d'erreur que Romain a corrigée à la main le 17/09 (« Grand Theft Auto Vice City »).

**Comment ça casse.** Offre « DLC Quest - Steam Key GLOBAL » (vrai jeu de base ; EXECUTOR_RULES.md §4.3 (f) le nomme explicitement : « a leading "DLC" is a name ("DLC Quest", a real game) … its own page resolves Standard »). `dlc_title_marker` rend None (exception du DLC en tête), donc R43 ne s'applique pas et R18 ne se déclenche pas (page multi-seaux). Mais `detect_edition("DLC Quest")` = ('DLC','16'), E05 voit « DLC » dans le nom AKS « DLC Quest » → `e05_page_verified=True`, et la boucle 3162-3170 trouve le seau 16 de la page (`_edition_key("DLC") == {DLC}`) et l'adopte. Résultat : candidat DLC(16) au lieu de Standard(1). Les pages de jeux de base portent bel et bien ce seau (constat vivant du 10-11/09 cité dans la spec : Stray Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake, et Vice City le 17/09). Deux variantes prouvées de la même porte : (a) un slug d'URL marchande contenant « -dlc- » avec un titre sans le moindre marqueur passe par P1-1 (3217) et donne aussi DLC(16) ; (b) « PACK » étant un mot de format pour `_edition_key`, un seau nommé « DLC Pack » (le catalogue vivant en compte « une q

**Vérifié directement.** Reproduit par moi : `DLC Quest` + page {1:Standard, 16:DLC} → édition **DLC(16)**. La même offre sur une page mono-seau → Standard(1). Variante `{1:Standard, 4711:'DLC Pack'}` → **DLC Pack(4711)**.

**Correctif proposé.** Le correctif proposé fonctionne (vérifié : 545 tests verts, comportements A/C/D corrigés, R18 et R43 intacts), mais il porte un défaut de motif qu'il faut corriger avant de le poser.

1) src/matcher.py:3167-3169 — ajouter l'exclusion DLC à côté de BUNDLE/TRILOGY dans la boucle R23/E05 :
       if ekey & {"BUNDLE", "TRILOGY"}:
           continue
       if eid == "16" or ekey == {"DLC"}:
           continue      # [R18] seule autorité sur le seau DLC (durcissement 2026-09-17)
   Effet : « DLC Quest » sur une page {1,16} ou {1,'DLC Pack'} retombe sur l'effondrement E05 -> Standard(1), conforme à EXECUTOR_RULES.md:383.

2) src/matcher.py:3214-3217 — même exclusion dans la compréhension P1-1, MAIS ne pas laisser le skip générique mentir. Tel quel, le patch fait sortir le cas C avec « edition 'DLC'(16) not sold on the resolved AKS page — guessed edition unverified (audit P1-1) », ce qui est f


### P1.7 `src/matcher.py:3360` — La voie console n'ouvre jamais la page marchand : région GLOBAL implicite au lieu du refus fail-closed

**Le défaut.** `_console_plan` décide la région à partir du seul titre/URL (`detect_region_base`) et n'appelle JAMAIS `MerchantConfig.offer_page_resolver`, contrairement à `_pc_plan` (l. 2625-2649) : pour tout marchand dont la région ne vit que sur sa propre page (Gamerall [R54], Instant Gaming [R32/R33], Difmark via `difmark_offer_resolver`), une ligne console tombe sur le GLOBAL implicite au lieu du refus fail-closed que ces fiches marchands existent pour garantir.

**Comment ça casse.** Gamerall (store 13, saisie en cours depuis le 18/09 : « 10/10 créées »), ligne console réelle du gabarit mesuré `<Nom> (<Plateforme>)` — « Mario Kart 8 Deluxe (Nintendo Switch) », URL `https://gamerall.com/nintendo-switch-games/mario-kart-8-deluxe-nintendo-switch`. C'est une des 18 % de lignes dont R54 a mesuré que la région n'est NI dans le titre NI dans l'URL (« Nintendo Switch » 7 lignes / 783). `precheck` laisse passer (`url_region` None → « la page tranchera »), puis la voie console conclut implicit GLOBAL : candidat SWITCH, bucket 99 « NINTENDO GAME CODE GLOBAL », `region_implicit=True`. Si la page Gamerall dit « Europe », une clé Switch EU est publiée en GLOBAL sur AKS — exactement le mode de panne que R54 (« page illisible ou sans région = refus, jamais de repli sur GLOBAL ») et R33 (« un sweep IG entier a entré 32/54 offres region-locked en GLOBAL ») interdisent.

**Vérifié directement.** Reproduit par moi : `classify_console` sur une URL Gamerall `/playstation/...-ps5` rend `families=('PS5',)`, `region_base=None`, `region_words=()` → la branche tombe dans `base='global', implicit=True` sans jamais appeler `offer_page_resolver`.

**Note de triage.** Reproduit par moi. Portée réelle : **Gamerall seul**. Instant Gaming, l'autre marchand à résolveur de page, déclare `console_url_families → None` : aucune ligne console. Gamerall n'est dans aucun sweep en cours.

**Correctif proposé.** La correction proposée est bonne sur la RÉGION, naïve sur la PLATEFORME. À affiner ainsi :

1) Dans `_console_plan`, avant le bloc région (src/matcher.py l. 3360), appeler `merchant_config(offer.merchant).offer_page_resolver(offer.url, offer.name)` quand il est déclaré, et n'en reprendre QUE le contrat région :
   - toute exception → `SkippedOffer(offer, f"{offer.merchant} offer page unreadable — unverifiable (R32): {exc}")`, mot pour mot comme `_pc_plan` (même chaîne, pour que le routage de `feed_status` / `suggest_target_list` reste inchangé) ;
   - `region_resolved=True` et `region_base` non nul → source AUTORITAIRE, au même rang que `sig.region_base` : contradiction avec le créneau grammatical console (`sig.region_base`) → skip explicite ; sinon `base = _sig.region_base`, `implicit = False` ;
   - `region_resolved=True` et `region_base` None → `SkippedOffer(offer, f"forbidden region:


### P1.8 `src/validation.py:146` — « approve » est lu en vérité Python : la chaîne "false" approuve l'offre

**Le défaut.** `load_validation` décide l'approbation avec `if not entry.get("approve")` : toute valeur JSON non-falsy vaut « oui », y compris la CHAÎNE "false" / "non" / "0" — et comme `verify_approved_against_source` re-dérive avec exactement le même prédicat, la re-vérification au moment du submit confirme l'approbation au lieu de la refuser.

**Comment ça casse.** Flux manuel documenté (EXECUTOR_RULES §5 ; le champ `instructions` du template dit littéralement « Set approve:true for the offers to submit »). L'opérateur veut REFUSER l'offre Kinguin 101050001 (Hades PS4) et écrit dans validation.json `"approve": "false"` — guillemets de trop, ou un outil/tableur qui sérialise les booléens en chaînes. `04_validate.py check` répond `{"valid": true, "approved": 1}` et sort en 0 ; approved.json contient l'offre refusée ; `05_submit.py --submit --mode safe` la crée sur AKS. L'unique porte avant une écriture live s'ouvre sur un refus.

**Vérifié directement.** Vérifié par moi : `if not entry.get("approve")` — toute chaîne non vide est vraie en Python.

**Note de triage.** Déclencheur : une faute de frappe de l'opérateur dans `validation.json` (`"approve": "false"` au lieu de `false`). Rare — mais c'est le seul fichier du dépôt dont la raison d'être est de fermer.

**Correctif proposé.** La correction proposée tient ; je l'affine sur le point d'application.

Un SEUL point de correction couvre les deux portes (04_validate et la re-vérification de 05_submit, qui passe par `load_validation`) — `src/validation.py`, dans la boucle de `load_validation` :

    value = entry.get("approve", False)          # clé absente -> refus
    if not isinstance(value, bool):
        raise ValidationError(
            f"approve doit être un booléen JSON (true / false), reçu {value!r} "
            f"pour {entry.get('fingerprint')!r} — fichier refusé en entier"
        )
    if not value:
        continue

Lever (et non ignorer) est conforme au §5 : jamais d'honneur partiel, `04_validate.py check` sort déjà en 2 sur `ValidationError`. Ne PAS « corriger » en traitant la chaîne comme falsy : un fichier mal typé doit être renvoyé à l'humain, pas deviné.

Même exigence sur les deux sites console,


## P2 — à corriger quand tu veux (20)

### P2.1 `src/matcher.py:617` — Un code pays 2 lettres en fin de titre (DE, TH, ID…) est avalé comme « marqueur de langue » : la clé verrouillée part en GLOBAL(2)

**Le défaut.** `_REGION_LOCK_LANG_CODES` ne protège que 5 codes (RU/TR/AR/PL/UA) alors que 17 autres codes de `LANGUAGE_TOKENS` sont, dans le dépôt lui-même, des libellés de région INTERDITE ; pour ces 17, la garde « mots supplémentaires » (ligne 788) est désarmée, aucun extra n'est levé, et `detect_region` retombe sur GLOBAL(2) implicite — une clé verrouillée Allemagne / Thaïlande / Indonésie est publiée mondiale.

**Comment ça casse.** Ligne de feed « Cyberpunk 2077 DE Steam CD Key » (marchand sans crochet de région sur ce gabarit : GameSeal hors de son créneau « - <REGION> », ou Eneba / AllYouPlay / CJS-CDKeys qui n'ont aucun hook région). `precheck_skip` → None (le scan titre cherche « GERMANY », pas « DE » ; `_URL_FORBIDDEN_CODES` n'a pas « de »), `extra_significant_words` waive DE en langue, `detect_region` → ('GLOBAL','2',implicit=True) → Candidate GLOBAL(2). La MÊME ligne avec RU est refusée. Idem TH (Thaïlande) et ID (Indonésie), et 14 autres (IT, ES, FR, NL, PT, RO, SK, HU, BG, HR, LT, LV, NO, FI).

**Note de triage.** Ramené de P1 à P2 : le vérificateur a démontré que DE est un faux positif DOCUMENTÉ (docs/MERCHANTS.md:86-88, Eneba « Without DE ») et que « id » a été volontairement exclu des codes URL. Le seul défaut net est **TH**, présent dans `_URL_FORBIDDEN_CODES` et absent de `_REGION_LOCK_LANG_CODES` — le miroir que le commentaire revendique est cassé.

**Correctif proposé.** Resserrer très fort, et REJETER le correctif proposé.

À FAIRE (le seul défaut net) : ajouter "TH" à _REGION_LOCK_LANG_CODES (src/matcher.py:617) — c'est le seul code qui casse l'invariant que le commentaire des lignes 614-616 revendique — et verrouiller l'invariant par un test : LANGUAGE_TOKENS ∩ {c.upper() for c, _ in _URL_FORBIDDEN_CODES} ⊆ _REGION_LOCK_LANG_CODES, pour que le miroir ne puisse plus dériver quand on ajoutera un code URL. Mettre à jour la note §4.11 d'EXECUTOR_RULES dans le même commit (règle « docs dans le même commit »).

À NE PAS FAIRE :
- Ne pas ajouter DE. Le dépôt porte le faux positif documenté « (Without DE) » (docs/MERCHANTS.md:86-88), et le seul marchand observé à écrire DE comme région (Kinguin) l'attrape déjà dans son créneau.
- Ne pas ajouter ID. Le dépôt a explicitement exclu "id" de _URL_FORBIDDEN_CODES comme trop collisionnel (matcher.py:211-216, « "id" 


### P2.2 `docs/EXECUTOR_RULES.md:670` — La spec autoritaire et docs/MERCHANTS.md affirment que trois marchands sont hors liste blanche safe-auto ; le code les y a mis

**Le défaut.** EXECUTOR_RULES.md (« LA spec métier, autorité ») écrit que GameBoost « stays OFF the safe-auto allowlist: the file serves SUPERVISED runs only » (l. 670) et que Electronicfirst/GamersOutlet « stay OFF the safe-auto allowlist: supervised dry-run first » (l. 651) ; docs/MERCHANTS.md répète « hors liste blanche » dans les trois en-têtes et corps de section. Or `src/admin/auto_merchants.py` les a tous les trois dans `AUTO_MERCHANTS` depuis le 2026-09-16, c'est-à-dire autorisés à écrire sur AKS SANS relecture humaine.

**Comment ça casse.** Un opérateur (ou un agent) qui suit la spec conclut qu'une passe GameBoost doit être supervisée (02 → 03 → 04 → 05) et qu'un lancement `/executor/auto` sera refusé fail-closed. En réalité `rejection_reason('GameBoost','157')` rend `None` : le sweep part et crée les offres sans validation. Sur les trois marchands les MOINS éprouvés du parc — GamersOutlet n'a qu'une vingtaine de lignes jamais balayées, GameBoost avait vu son run annulé en direct le 2026-07-15 — c'est précisément là que la question « y a-t-il une relecture ? » doit avoir une réponse juste.

**Correctif proposé.** La correction proposée contient une ERREUR à retirer, et il lui manque un emplacement.

À RETIRER — `docs/MERCHANTS.md:800` : cette ligne appartient à la section **Wyrel** (`## Wyrel (store 162, supervisé)`, l. 752-819), pas à Electronicfirst. Wyrel n'est PAS dans `AUTO_MERCHANTS` (vérifié à l'exécution ; `tests/test_merchants_wyrel.py:232` l'assert en `assertNotIn`). « Reste hors liste blanche safe-auto (le corpus ne couvre que 10 pages sur 59) » y est donc EXACT : la « corriger » introduirait une nouvelle fausseté.

À CORRIGER (6 emplacements) :
- `docs/EXECUTOR_RULES.md:651` — « Both merchants stay OFF… » → « Electronicfirst and GamersOutlet joined the safe-auto allowlist on 2026-09-16 » + la condition de dé-parquage (pour Electronicfirst : le défaut PUBLISHER/STEAM fermé par `[R51]`).
- `docs/EXECUTOR_RULES.md:670-671` — la phrase enjambe DEUX lignes (le constat ne cite que 670) : « 


### P2.3 `scripts/05_submit.py:566` — FC3 : un run AVORTÉ (aucune écriture) remet à zéro le compteur cross-process de runs bloqués

**Le défaut.** `ledger.record(task_id=run_id, blocked=bool(snapshot.get("blocked")), …)` est appelé inconditionnellement dès que `write` est vrai, y compris quand `submitter.run()` a renvoyé un dict `aborted` (aucune offre touchée, garde jamais armée). `BlockLedger.record(blocked=False)` remet `consecutive_blocked_runs` à 0 — l'unique anti-boucle inter-processus du projet (FC3 / G03 : « la même approche échoue deux fois → STOP ») est effacée par une passe qui n'a rien fait.

**Comment ça casse.** Séquence réelle : passe 1 réelle → 10 échecs consécutifs → `guard.blocked` → ledger `consecutive_blocked_runs=1`. Passe 2 (recovery idempotente documentée) → bloquée aussi → `=2`, `requires_ack()` True, la 3e passe exigerait `--acknowledge-block`. Entre-temps la session WP expire (cookie transfer à refaire — cas courant sur ce projet). Passe 3 : `run()` fait son navigate pré-vol, `session.is_login_page()` est vrai, retourne `{"aborted": "not_logged_in", …}` — un dict, PAS une exception, donc le `except FEED_UNREADABLE_EXCS` (l. 554) ne l'intercepte pas ; le flot tombe sur `if write: ledger.record(blocked=False)` → `consecutive_blocked_runs=0`. Le script écrit quand même `submit_plan.json` et sort avec le code 0. Passe 4 : elle repart sans aucun acquittement humain, exactement la 3e tentative identique que G03 interdit. Mêmes effets avec `aborted="catalog_unavailable"` et `aborted="feed_unreadable"` (échec du scan d'index) — trois avortements sans écriture qui remettent le compteur à zéro.

**Correctif proposé.** La correction proposée tient : envelopper le bloc `ledger.record` (`scripts/05_submit.py` l. 563-570) dans `if write and not result.get("aborted"):`. Un avortement laisse alors la série FC3 telle quelle — il ne la crédite ni ne la débite. Préférer ce test à « `result["plan"]` non vide » : un plan vide peut aussi venir d'un `--limit` ou d'un lot sans candidat localisable, cas où la passe a réellement tourné. Ne PAS étendre au-delà : `operator_stop` (`aborted=None`, `plan=[]`, `submitter.py` l. 1479-1482) remettrait encore le compteur à 0, c'est hors périmètre de ce constat. Documenter au passage `docs/DATA_CONTRACTS.md` §guard_ledger.json (« a clean pass resets it to 0 » → préciser qu'une passe avortée n'est pas une passe propre) et ajouter à `tests/test_submit_cli.py` le cas « counter=1 + résultat avorté → le compteur reste 1 », aujourd'hui non couvert.


### P2.4 `scripts/10_data_entry_auto.py:506` — `write_marker` écrase un marqueur VIVANT : un simple `--dry-run` rend le sweep de 30 h invisible et rouvre le lancement depuis la console

**Le défaut.** `run_marker.write_marker` (src/run_marker.py:136-152) écrase inconditionnellement `state/active_run.json`, alors que sa docstring ne promet que « Overwrites any marker left by a dead process ». `scripts/05_submit.py:350` a reçu la garde correspondante le 2026-09-18 (« NE PAS écraser le marqueur d'un run PARENT ») mais `scripts/10` l'appelle sans aucune garde. Comme `clear_marker` ne supprime que si le `run_id` correspond, c'est le second process — celui qui a écrasé — qui efface le fichier en sortant : le run survivant n'a plus AUCUN marqueur, et la gate console `_ensure_free` (src/admin/submit_manager.py:324, `cli_run_in_progress`) cesse de refuser un lancement concurrent. Le verrou navigateur ne rattrape pas : il n'est tenu que par les ENFANTS (02/05/06) et il est LIBRE entre deux étapes du sweep.

**Comment ça casse.** Le sweep de couverture totale tourne depuis un terminal (recette README `--all-allowlisted --all-pages --continue-on-halt`). Romain lance à côté un aperçu documenté comme inoffensif : `scripts/10 --dry-run --targets Kinguin:58`. Ce dry-run écrase le marqueur (le commentaire l. 504-505 dit pourtant « A dry-run is marked too — it drives the browser just the same, and a console launch during one must be refused »), prend le flock entre deux enfants du sweep, finit, et son `atexit clear_marker` SUPPRIME le fichier. Le sweep de 30 h continue mais n'est plus visible dans la console, le bouton « Lancer » ne refuse plus, et un run console démarré à ce moment prend le flock entre deux enfants du sweep : la prochaine étape du sweep sort en `BrowserBusyError` (exit 2) → `extract_failed_pN` / `submit_not_clean_pN`, et l'ordre « page haute d'abord » (reflow-safe) est rompu par un second scrutateur qui crée des offres dans les pages basses pas encore traitées.

**Correctif proposé.** Garde DANS `src/run_marker.write_marker` (pas au point d'appel), pour que tout appelant futur en hérite — et alignée sur la docstring existante : refuser SEULEMENT si `read_marker(repo_root)` renvoie un marqueur vivant dont le `run_id` DIFFÈRE. Un marqueur à pid mort reste écrasé (l'auto-guérison documentée est préservée) ; un même `run_id` reste écrasé (relance avec `--run-id`). Lever une exception dédiée (ou renvoyer le marqueur existant sans écrire).

Dans `scripts/10_data_entry_auto.py`, traiter ce refus comme un abort fail-closed : `print(json.dumps({"aborted": True, "reason": "un run est déjà en cours (<kind> sur <run_id>, pid <pid>) — attends sa fin ou arrête-le dans son terminal"})); return 2`. Déplacer l'appel AVANT `sweep_dir.mkdir(parents=True, exist_ok=True)` (~l. 496) pour qu'un abort ne laisse pas un `runs/<run-id>/` vide derrière lui. C'est aussi la bonne réponse à un seco


### P2.5 `scripts/10_data_entry_auto.py:567` — Un stop opérateur efface les haltes fail-closed déjà enregistrées et rend le code de sortie vert

**Le défaut.** Avec `--continue-on-halt`, chaque halte fail-closed d'un marchand est accumulée dans `recap["halted"]` (ligne 561) pour que le code de sortie soit 2. Mais si un stop opérateur survient ENSUITE, `if _RUNNER.stopped: recap["halted"] = "operator_stop"` (l. 566-567, et le jumeau l. 522-523) écrase cette chaîne, et le retour final `return 0 if recap["halted"] in (None, "operator_stop") else 2` (l. 583) rend 0. La passe sort VERTE alors que des marchands se sont arrêtés fail-closed — exactement ce que [34] (Fable re-audit 2026-09-06) interdit : « exit non-zero when the sweep HALTED fail-closed, so a supervising caller (manager / CI) sees the failure instead of a green exit 0 ». CLAUDE.md fait du code de sortie une gate : « Its exit code + submit_plan.json are read and checked before ANY continuation to a new run/page/stage ».

**Comment ça casse.** Sweep de nuit `--all-allowlisted --all-pages --continue-on-halt`. MarchandA s'arrête `submit_not_clean_p12` (ex. `ten_consecutive_failures`) ; `--continue-on-halt` l'enregistre et passe à MarchandB. Pendant MarchandB, Romain clique « Arrêter » dans la console → SIGTERM → `_RUNNER.stopped = True`, `run_sweep` renvoie `halted="operator_stop"` → la branche halte est sautée → l. 567 remplace `"MarchandA: submit_not_clean_p12"` par `"operator_stop"` → exit 0. Le superviseur (manager / CI / opérateur qui relit la ligne de sortie) voit un run réussi et enchaîne sur le run suivant sans jamais voir la halte de MarchandA.

**Correctif proposé.** La correction proposée tient — je l'ai VÉRIFIÉE sur une copie temporaire (/tmp, dépôt jamais modifié), 6 scénarios, zéro régression sur les 4 cas légitimes :

  halte puis stop opérateur   : rc 0 → 2, halted 'MarchandA: submit_not_clean_p12; operator_stop'
  halte puis stop entre march.: rc 0 → 2, idem
  run propre                  : rc 0, halted None            (inchangé)
  stop opérateur seul         : rc 0, halted 'operator_stop'  (inchangé — [34] préservé)
  halte simple (défaut)       : rc 2, halted 'A: submit_not_clean_p3'  (inchangé)
  continue-on-halt seul       : rc 2, halted 'A: submit_not_clean_p3'  (inchangé)

Les deux tests existants `test_default_first_halt_stops_the_batch` et `test_continue_on_halt_sweeps_the_next_merchant` (tests/test_data_entry_auto_cli.py:469-482) restent verts, ainsi que `test_login_bounce_still_stops_the_batch`.

TROIS AJOUTS à la correction proposée 


### P2.6 `src/admin/app.py:518` — La porte anti-collatéral de la promotion ne se ferme pas quand la mesure est impossible

**Le défaut.** `if check.get("measured") and check.get("collateral")` : quand `measure_pattern` ne peut PAS mesurer (aucun scan, ou run_id disparu), il renvoie `measured: false` sans `collateral`, la condition est fausse, et `sort_sql_promoted.promote()` — qui ne contrôle que le vocabulaire du motif, l'existence de la liste et l'absence de doublon — accepte. La garde décrite trois lignes plus haut comme « la seule garde qui protège cette voie » est franchie par l'absence de données, pas par la sûreté.

**Comment ça casse.** La page /sql est ouverte avec `RUN_ID = "tri-20260917-1426"`. Le run est ensuite purgé ou remplacé (les scans de tri sont des runs comme les autres). Romain clique « Promouvoir » sur une proposition non éditée : sql.js:142 voit `fresh === true`, saute la remesure et poste directement. Côté serveur `_latest_sort_run(runs_dir, "tri-20260917-1426")` renvoie None → `measured: false` → la porte ne se déclenche pas → la règle entre dans `data/sort_sql_promoted.json`, fichier VERSIONNÉ et commité, d'où elle ressort dans `rules`, dans `all_sql` et dans les deux boutons « copier » de chaque run suivant. Le pire cas est celui que trois docstrings du projet citent nommément : `%modern-warfare%` → Blacklist promue sans qu'une seule ligne n'ait été mesurée.

**Correctif proposé.** Dans `src/admin/app.py`, après les retours anticipés `dismiss`/`demote` (qui n'ont pas besoin de mesure) et AVANT le test de collatéral, fermer la porte sur l'absence de mesure :

    check = measure_pattern(self.state.runs_dir, str(body.get("pattern", "")),
                            str(body.get("target", "")), str(body.get("run_id") or ""))
    if not check.get("measured"):
        raise ApiError(400, "promotion_unmeasured",
                       f"{check.get('note') or 'motif non mesurable'} — promotion refusée ; "
                       f"relance un scan de tri puis recharge /sql")
    if check.get("collateral"):
        ...  # inchangé

Le message doit dire quoi faire : après la correction, un RUN_ID périmé refuse au lieu de dégrader, et l'opérateur doit savoir que recharger la page (ou relancer un scan) débloque. Ne PAS faire retomber `_latest_sort_run(runs_dir, wanted)` sur le 


### P2.7 `src/admin/static/app.js:1099` — app.js n'a aucun jeton de génération : une réponse tardive attribue le bilan d'un run au run suivant et ressuscite le sondage après stopPolling()

**Le défaut.** La console Validation & Submit est la seule des quatre à n'avoir jamais reçu la discipline LOAD_SEQ / POLL_SEQ / MODAL_SEQ / SCAN_SEQ appliquée à sort.js, auto.js et urls.js : `pollStatus()` relit `CURRENT.runId` au retour du réseau au lieu d'un id figé, et ré-arme `POLL_TIMER` (ligne 1099) après que `stopPolling()` (ligne 1052) l'a annulé. Un tick en vol du run A repeint et re-sonde le contexte du run B.

**Comment ça casse.** Un submit RÉEL tourne sur le run A ; Romain clique le run B dans la liste pendant qu'un tick de sondage de A est en vol. `openRun(B)` appelle `stopPolling()` (0 timer) et vide les panneaux. La réponse de A arrive ensuite : (a) si A est terminé, `renderFinal(status)` → `renderStatusSummary` construit `LAST_TERMINAL` avec `CURRENT.runId` (= B) et les chiffres de A : le pied de page persistant affiche « ✔ submit sur B — done — créées : 12 / tentatives : 12 » alors que les 12 offres créées sur AKS appartiennent à A ; (b) si A tourne encore, la ligne 1099 ré-arme le timer que stopPolling venait de supprimer, et le tick suivant interroge `api/runs/B/submit/status?offset=77` avec l'offset d'octets du journal de A — la fenêtre de log de B est lue depuis une position arbitraire (et `tail_log_events` remet à 0 si l'offset dépasse la taille, rejouant tout le journal de B).

**Correctif proposé.** La correction proposée est bonne (jeton POLL_SEQ calqué sur sort.js:409/439, `rid` figé avant l'await, sortie après CHAQUE await avant d'écrire LOG_OFFSET / d'appendre dans #events / de ré-armer / d'appeler renderFinal). Deux ajouts nécessaires pour que le trou soit réellement bouché :

1) `refreshStatus` (1160) et `idleTick` (1229) souffrent du même défaut et sont même plus larges : tous deux font `await api(.../${CURRENT.runId}/submit/status...)` puis écrivent `LOG_OFFSET = status.offset` (1174, 1247) et appellent `startPolling()` (1181, 1250) sans revérifier que `CURRENT.runId` est toujours celui qu'ils ont interrogé. `idleTick` enchaîne 2-3 requêtes séquentielles toutes les 10 s : c'est la fenêtre de course la plus large du fichier. Il faut y figer `rid` et sortir sur `rid !== CURRENT.runId` après chaque await, exactement comme dans pollStatus.

2) `pollStatus` doit remettre `POLL_TI


### P2.8 `src/admin/static/sql.js:53` — « Copier seulement les requêtes sans désaccord » copie TOUT quand rien n'est mesuré

**Le défaut.** Le prédicat `clean = (r) => !r.measured || (!r.collateral && !r.conflict)` classe une règle NON MESURÉE comme « sans désaccord ». Le bouton `#copy-safe` copie donc les 53 requêtes, `%puzzle%` et `%-1-month-%` comprises, et annonce « 0 écartées » — ce qui rouvre côté client exactement le trou que la correction serveur `[P2]` du 18/09 (`IncompleteScan`) venait de fermer.

**Comment ça casse.** Sur un déploiement frais, après une rotation de `runs/`, ou dès que `offers.json` d'un scan est illisible, `sort_sql_payload` renvoie `measured: false` pour chaque règle (c'est le comportement voulu par la correction P2). Romain ouvre /sql, clique « copier seulement les requêtes sans désaccord » — le bouton qui affirme trier — reçoit « 53 requêtes copiées (0 écartées) » et les colle dans phpMyAdmin. Passent alors `%puzzle%` (qui vise un GENRE de jeu : tout jeu de puzzle vendable part en Blacklist 8, contradiction déjà écrite dans `FLAGGED`), `%-1-month-%` (232 lignes dont 35 vrais jeux), `%-outfit-%` (71 dont 53 DLC de tenues Fortnite) et `%-robux-%` (18 dont 9). Le nom du bouton et son compte « 0 écartées » affirment un tri qui n'a jamais eu lieu.

**Correctif proposé.** 1. `const clean = (r) => r.measured && !r.collateral && !r.conflict;` — alignement sur la ligne 114 du même fichier. En état non mesuré le bouton devient fail-closed et cohérent avec sa propre bannière : « 0 requête copiée (53 écartées, dont 53 non mesurées) ».
2. Distinguer les non mesurées dans le message du bouton (sql.js:231-235) : « N copiées (M écartées, dont K non mesurées) » — sinon un opérateur lit « écartées » comme « en désaccord » alors qu'on n'en sait rien.
3. NE PAS reprendre le `&& !r.truncated` proposé : j'ai grepé, aucun champ `truncated` n'existe dans le payload de `sort_sql_view.py` ni nulle part sur cette voie (les seuls `truncated` du dépôt sont ceux de urls.js / sort.js / submit_manager.py, sans rapport). Cette clause vient d'un autre constat et introduirait un prédicat toujours vrai.
4. Remplacer tests/test_sort_sql_console.py:476 par un test qui EXÉCUTE le prédica


### P2.9 `src/extractor.py:622` — Le sondage de pagination du sweep passe par le mode « slice », qui n'a pas la garde nav_max=0 : un feed de 107 pages peut être balayé sur 1 page et déclaré complet

**Le défaut.** `extract_pages()` (mode slice) fait de `nav_max` lu au PREMIER read la valeur autoritaire de `feed_last_page`, sans la corroboration que `extract()` (mode sweep) applique à la même forme ([20], ligne 473 : page 1 pleine de lignes + `nav_max == 0` → sonder p=2 → `FeedUnstableError`). Or c'est exactement ce mode que `scripts/10` utilise (`02_extract_feed.py --pages <N>`) pour sa sonde de départ, et `src/data_entry_auto.py:210` en fait la borne haute `top` de TOUTE la passe. Un seul read où les lignes sont rendues mais pas encore la nav réduit silencieusement un feed multi-pages à 1 page, avec `halted=None` et `coverage=None` — le contraire de la règle EXECUTOR_RULES §3 : « The real page count comes from the feed's own pagination nav … bound the scan by it, never by "first empty page" heuristics ».

**Comment ça casse.** Sweep de nuit `scripts/10 --all-allowlisted --all-pages --continue-on-halt`. Sur Kinguin (107 pages réelles), la sonde `02 --pages 1` lit la page 1 : 20 lignes `data-offer` rendues, `feed_ui=true`, mais `.tablenav` pas encore peuplé → `nav_max=0`. `extract_pages` renvoie `feed_last_page = max(0, 0, 1) = 1`. `run_sweep` pose `feed_last=1`, `top=1`, `capped=False` : il balaie la page 1, s'arrête, et écrit `coverage: null`, `halted: null`. 106 pages (≈ 2 120 offres) ne sont jamais ni extraites ni matchées, et le recap affirme une passe propre et complète. Variante : si le re-read de la page 1 par la boucle voit la nav, `max_seen(107) > feed_last(1)` et la troncature est ré-étiquetée `incomplete_feed_grew (1→107 pages)` — ce n'est toujours PAS une halte, et les 106 pages restent non balayées.

**Correctif proposé.** La correction proposée vise la bonne couche — garder la sonde p=2, mais affûtée sur deux points.

1) PORTER [20] dans `extract_pages`, forme exacte : `if page == first_page == 1 and feed_ui and nav_max == 0 and page_offers:` → sonder p=2 via `_settled_page_state` ; des lignes en p2 ⇒ `FeedUnstableError` (jamais de troncature silencieuse) ; une over-page vide confirme le feed mono-page et la tranche continue inchangée. C'est bien l'extracteur qui doit porter la garde, et non `run_sweep` : (i) `run_sweep` est pur et n'a pas de session pour sonder ; (ii) vérifié à l'exécution, `run_sweep` tronque À L'IDENTIQUE si `feed_last_page` est `None` (`feed_last = probe.feed_last_page if probe.feed_last_page else cfg.start_page`, data_entry_auto.py:210) — faire renvoyer 0 par l'extracteur ne corrigerait donc rien.

2) ABANDONNER le « complément » proposé (re-lire la page avec le backoff `FEED_UI_REND


### P2.10 `src/matcher.py:579` — « MICROSOFT » absent de NOISE_TOKENS : toute ligne dont le titre nomme le Microsoft Store est refusée en « extra words » (le défaut ROCKSTAR, non corrigé pour Microsoft)

**Le défaut.** Le commentaire de matcher.py:589 affirme « every other store word was already noise here » : c'est faux. `MICROSOFT` n'est pas dans `NOISE_TOKENS`, alors que `_TRAILING_NOISE_PHRASES` (l.1425) contient bien « MICROSOFT STORE » pour la construction du slug. La garde d'identité [R16] lit donc « MICROSOFT » comme un mot de produit et refuse la ligne, exactement comme elle refusait les lignes Rockstar avant l'ajout du 16/09.

**Comment ça casse.** Ligne Kinguin de grammaire standard (« Microsoft Store » fait partie de `kinguin._PC_ITEM`) : « Age of Empires IV PC Microsoft Store CD Key », URL kinguin.net, page AKS « Age of Empires IV » (regions {'246': 'Windows 10 GLOBAL'}, official_platforms ('Microsoft Store',)). `match_offer` renvoie SkippedOffer « different/expanded product — extra words: ['MICROSOFT'] ». Même chose pour tout marchand qui écrit la boutique dans le titre : Gamerall « … (Microsoft Store) » (3 lignes / 783), Electronicfirst (`_PLATFORM_WORD` inclut `Microsoft\s*Store`), GameBoost (idem), G2A (`_STORE` inclut `Microsoft\s*Store`), GameSeal (« Microsoft Store Key » listé dans sa grammaire).

**Correctif proposé.** Le correctif proposé est nécessaire mais INCOMPLET tel quel ; trois précisions :

1) `NOISE_TOKENS` += "MICROSOFT" (matcher.py:579, à côté de ROCKSTAR). Suffisant pour les marchands dont le TITRE est la source plateforme (Kinguin, GameSeal, Electronicfirst, Gamerall, GameBoost) et pour Eneba (préfixe d'URL `windows-`) : vérifié, Kinguin et Eneba deviennent `Candidate MICROSOFT 246 Standard`.

2) INSUFFISANT pour G2A, qui est probablement le gros de la population des 164 lignes (la grammaire « X (PC) - Microsoft Store Key - EUROPE » est son `_TAIL_RE`, et le helper de tests R52 utilise des URL g2a.com). G2A a `title_is_platform_source=False` : la plateforme vient de `_url_platform_scan`, dont `_URL_PLATFORM_WORDS` (matcher.py:1190 env.) ignore microsoft/windows, et dont l'alternance de suffixe `(?:connect|com|games|app|net)` n'accepte pas `store` — donc `-microsoft-store-key-` ne déclare 


### P2.11 `src/matcher.py:687` — Les accents ne sont repliés ni pour l'identité ni pour le slug : le repli de 2026-09-16 s'est arrêté au precheck

**Le défaut.** `normalize_apostrophes` (le normaliseur unique qu'appellent `tokenize`, `cleaned_title` et `build_slug_candidates`) fait le strip des symboles puis NFKC, mais ne replie PAS les diacritiques, alors que `fold_accents` (ligne 2338) existe dans le même module et sert déjà à `_norm_tokens` / `precheck_skip`. La regex `[A-Z0-9']+` de `tokenize` (ligne 727) et le `[^a-z0-9]+ → '-'` de `_slug_variants` (ligne 1512) suppriment donc la lettre accentuée : (a) le slug fabriqué est faux → l'offre légitime n'est jamais résolue ; (b) R01/R16 sont STRUCTURELLEMENT incapables de rattraper un slug tronqué qui atterrit sur un AUTRE produit, puisque la même lettre est effacée des deux côtés de la comparaison.

**Comment ça casse.** Fail-open : ligne marchande « Ōkami Steam Key GLOBAL ». `build_slug_candidates` produit `['kami']` (le Ō tombe, le tiret de tête est strippé), donc on sonde `buy-kami-cd-key-compare-prices/` — la page d'un AUTRE jeu. `missing_aks_words('Kami','Ōkami Steam Key GLOBAL')` = [], `extra_significant_words` = [], `dangerous_qualifier` = None → Candidate sur la mauvaise page produit. Fail-safe mais massif : une page AKS écrite en ASCII (« Le Chateau des Ombres ») contre un titre marchand accentué (« Le Château des Ombres (PC) Steam Key EU ») → `missing AKS words: ['CHATEAU']`, et dans l'autre sens `extra words: ['CH','TEAU']` ; « Röki » et « Roki » se refusent mutuellement alors que c'est la BONNE page, y compris quand la recherche de repli R30 l'a trouvée.

**Correctif proposé.** La correction proposée tient, je la précise plutôt que la remplacer. (1) Replier les diacritiques DANS `normalize_apostrophes` (src/matcher.py:687), APRÈS le strip `_NFKC_LETTER_SYMBOL_RE` et À LA PLACE du NFKC — vérifié par exécution que NFKD + suppression des combinantes est un sur-ensemble strict du NFKC exigé par [R28] : « Ⅱ »→II, « ＤＬＣ »→DLC, « ﬁ »→fi, « Company™ »→COMPANY (l'ordre strip-d'abord doit rester), et `tokenize('Company™ Ⅱ')` → `['COMPANY','2']` (R42 intact). (2) Non-régression mesurée : avec ce normaliseur patché à chaud, 597 tests de test_matcher / test_accent_folding / test_console_keys / test_candidate_contract / test_merchants_{kinguin,k4g,g2a,mmoga} passent — aucun module n'importe `normalize_apostrophes` par son nom (grep : seul un commentaire dans les tests), donc le patch global couvre bien tokenize / cleaned_title / build_slug_candidates ; le correcteur doit tou


### P2.12 `src/matcher.py:735` — R01 exige l'apostrophe et les mots-outils au caractère près, alors que le générateur de slug sonde déjà les deux orthographes

**Le défaut.** `missing_aks_words` exige que CHAQUE token du nom AKS soit présent tel quel dans le titre marchand, apostrophe comprise (`tokenize` garde `'` à l'intérieur du token via `[A-Z0-9']+`) et mots-outils compris (THE/OF/AND/A), alors que §4.1 ne demande que « every MEANINGFUL word ». Or `_slug_variants` (ligne 1512) sonde explicitement les DEUX orthographes d'apostrophe et `match_extras_to_page_edition` (ligne 2475) plie l'apostrophe : la bonne page AKS est donc trouvée, puis refusée par la garde d'identité.

**Comment ça casse.** Titre marchand sans apostrophe (orthographe très fréquente, c'est celle du slug marchand) : « Assassins Creed Valhalla Ubisoft Connect Key ». `build_slug_candidates` donne `assassins-creed-valhalla`, la page AKS « Assassin's Creed Valhalla » répond 200 — puis `missing_aks_words` renvoie `["ASSASSIN'S"]` → « name mismatch, missing AKS words ». Toute la famille apostrophée du catalogue est concernée (Tom Clancy's, Marvel's, Baldur's Gate, No Man's Sky, Sid Meier's, Dragon's Dogma, Five Nights at Freddy's). Variante mots-outils : nom AKS « Salt and Sanctuary » contre titre marchand « Salt & Sanctuary Steam Key » → `['AND']` (le `&` est jeté par la regex de tokens) ; le sens inverse passe, puisque AND est dans `NOISE_TOKENS` côté extras — c'est l'asymétrie qui est le défaut.

**Correctif proposé.** Corriger la LIGNE src/matcher.py:728 (et non :735, qui n'est que le consommateur) : replier l'apostrophe dans `tokenize` en copiant exactement `_identity_tokens` (src/matcher.py:3286) — `t.replace("'", "")` puis abandon des tokens vides — pour que les deux replis ne puissent plus diverger. Rayon d'action MESURÉ (monkeypatch de `M.tokenize`, aucun module de production n'importe `tokenize` hors src/matcher.py — grep vérifié) : 810 tests joués (tests.test_matcher + test_merchants_* + test_candidate_contract + test_console_keys + test_match_cli + test_contracts + test_accent_folding), 2 échecs SEULEMENT, et ce sont les deux assertions qui épinglent le comportement lui-même (test_matcher.py:108 `test_normalizes_apostrophes`, :235 `test_r01_apostrophe_mismatch_is_missing`) — aucune règle métier touchée. Comme pour `fold_accents` (tests/test_accent_folding.py : « folding can only make a vocabul


### P2.13 `src/matcher.py:1245` — Le mot « Global » dans le NOM DU JEU écrase une région US/UK réelle → clé verrouillée saisie en GLOBAL

**Le défaut.** Dans `_detect_region_parts`, la branche GLOBAL est testée AVANT US et UK et elle lit `"-global" in url` en sous-chaîne nue plus `" GLOBAL " / " WORLDWIDE "` en plein milieu du titre — donc un produit dont le NOM PROPRE contient le mot « Global » (Counter-Strike: Global Offensive) fait gagner GLOBAL(2) contre un verrou US/UK pourtant explicite dans le slot de région de l'URL ou dans la queue du titre.

**Comment ça casse.** Ligne Eneba réelle : titre « Counter-Strike: Global Offensive Prime Status Upgrade Steam Key », URL `…/steam-counter-strike-global-offensive-prime-status-upgrade-steam-key-united-states`. Le slug porte `-united-states` (slot de région propre, branche US ligne 1250). Mais `"-global" in url` est vrai via `-global-offensive-` (et `" GLOBAL "` est vrai dans le titre), donc la branche ligne 1245 gagne : base=global, implicit=False → Steam GLOBAL(2) au lieu de Steam US(8). `precheck_skip` ne dit rien (US est vendable), `[R44]` ne rattrape pas (`_REGION_IDENTITY_PHRASES` ligne 840 n'a pas d'entrée "GLOBAL"), et `implicit=False` fait passer la ligne pour une région LUE, donc auto-approuvable en sweep safe-auto. Résultat publié sur AKS : une clé US-only vendue au monde entier. Amplification console : `_console_plan` étape (c) ligne 3370 prend `generic_base` dès que `not generic_implicit` — la même ligne en version Xbox/PS file le seau GLOBAL de CHAQUE famille déclarée.

**Correctif proposé.** La correction proposée casserait des grammaires réelles — à ne PAS appliquer telle quelle.

À REJETER :
- (1) « slot terminal `-<marker>-global` en fin de chemin » : j'ai vérifié par exécution que le `-global` en MILIEU de slug est la grammaire NORMALE de plusieurs marchands — Driffle `x-global-pc-steam-digital-key-p1` → ('GLOBAL','2',False), K4G `…-steam-global-altergift-alter-gift-XXXX` → ('GIFT','25',False), Gamivo `…-pc-steam-en-global` → ('GLOBAL','2',False). Les passer en implicite est une régression documentée à l'envers (CHANGELOG:1746 « `-steam-global-` → GIFT 25 explicite »), et l'implicite a des effets : refus console quand `sig.region_words` est non vide (matcher.py:3374) et branche `if implicit and is_difmark` (matcher.py:2697).
- (3) `"GLOBAL": ("GLOBAL","WORLDWIDE")` dans `_REGION_IDENTITY_PHRASES` : `r44_label = plan.base_label or region_label` vaut « GLOBAL » AUSSI pour 


### P2.14 `src/matcher.py:2799` — Le garde « DLC anonyme » de R43 s'ouvre dès que le seau Standard de la page n'est pas la clé "1"

**Le défaut.** Le garde fail-closed du DLC sans nom propre (R43 (d) : « <Jeu> (DLC) » sur une page qui vend AUSSI Standard → skip) teste la présence de Standard par la CLÉ littérale `"1" in resolution.editions`, alors que le reste de la même fonction teste Standard par le NOM (`ename.strip().upper() == "STANDARD"`, lignes 3164 et 3216). Dès que la page ne porte pas la clé "1" — page multi-seaux sans Standard, ou Standard rangé sous un autre id — le garde ne se déclenche pas, `resolved_on_own_page` passe trivialement (le nom démarqué EST le slug du jeu de base) et R18 estampille DLC(16) sur la page du JEU DE BASE.

**Comment ça casse.** Offre « Neon Beats (DLC) - Steam Key GLOBAL » (marqueur DLC, aucun sous-titre : le cas « DLC anonyme » que R43 (d) veut refuser), page du jeu de base dont la carte des éditions ne contient pas la clé "1" — par exemple {16: 'DLC', 518: 'Standard + DLC'} (les deux seaux existent côte à côte dans le catalogue vivant, CHANGELOG 2026-09-17), {16: 'DLC', 7: 'Deluxe Edition'}, {16: 'DLC', 5: 'Early Access'} ou simplement un Standard rangé sous un autre id {16: 'DLC', 777: 'Standard'}. Dans les quatre cas le candidat sort en DLC(16) sur la page du jeu de base, alors que la page {1: 'Standard', 16: 'DLC'} skippe correctement. La spec dit pourtant « a DLC-only page ({16} without Standard) still enters » : une page à deux seaux n'est pas DLC-only, et R18 (3097) en juge d'ailleurs par `len(editions) == 1` — trois définitions différentes de « page DLC seule » cohabitent dans le même fichier.

**Correctif proposé.** REJETER la variante « par le nom » proposée dans le constat : je l'ai évaluée sur les mêmes cartes, `any(k == "1" or _edition_entry_name(v).strip().upper() == "STANDARD" ...)` renvoie **False** sur {16:'DLC', 518:'Standard + DLC'} (« Standard + DLC » ≠ « STANDARD ») — elle rate le cas le plus plausible et n'attrape que le {777:'Standard'} théorique.

Retenir le prédicat qui implémente littéralement la spec (« a DLC-only page ({16} without Standard) still enters ») : le garde se déclenche dès que la page porte un seau AUTRE que le seau DLC. En src/matcher.py:2799 :

    non_dlc_buckets = [k for k, v in resolution.editions.items()
                       if k != "16" and _edition_entry_name(v).strip().upper() != "DLC"]
    if (dlc_marker not in (None, *_DLC_PASS_MARKERS) and non_dlc_buckets
            and not re.search(r"\s[-–—:|]\s|:\s", cleaned_title(strip_dlc_marker(offer.name)))):

et 

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


### P2.15 `src/matcher.py:2934` — Le sauvetage par « extras » écrase le palier d'édition du titre (Deluxe classé sous l'édition de base)

**Le défaut.** Quand `match_extras_to_page_edition` réussit, `edition_from_extras` court-circuite complètement `detect_edition` (branche `elif` du bloc édition). Or les mots de palier (DELUXE, ULTIMATE, GOLD, GOTY, PREMIUM, COMPLETE, COLLECTION…) sont dans `NOISE_TOKENS`, donc ils n'entrent JAMAIS dans `want` : le contrôle de résidu ajouté par la re-revue Fable 2026-09-06 (ligne 2494) n'est valable que dans UN sens — il refuse bien « Knights → Knights Deluxe », mais rien ne refuse « Knights Deluxe → Knights ». Le palier déclaré par le marchand est perdu en silence et l'offre est écrite sous l'édition de base de la page.

**Comment ça casse.** Offre « Legends of Eisenwald - Knight's Deluxe Edition - Steam Key GLOBAL » (le produit même que la règle du sauvetage cite en exemple, mais dans sa déclinaison Deluxe), nom AKS « Legends of Eisenwald ». `extra_significant_words` rend ["KNIGHT'S"] (DELUXE est du bruit), `match_extras_to_page_edition` adopte le seul seau compatible « Knights Editon » (2723) — résidu {EDITION}, pur bruit de format — et `detect_edition`, qui rendait pourtant ('Deluxe','7'), n'est jamais appelé. Le candidat part en « Knights Editon »(2723). Pire : même quand la page vend explicitement « Deluxe Edition »(7), le résultat est identique, donc la donnée publiée reste fausse alors que le bon seau existait sur la page. Aucun garde en aval ne rattrape : ni le refus des bundles (2934 saute le bloc `edition_id == "8"`), ni la réconciliation P1-1 (elle ne tourne que dans la branche `else`).

**Correctif proposé.** Le principe de la correction est bon mais sa formulation ferait des faux skips. Trois raffinements, mesurés :

1. Les paliers doivent être ceux que le MARCHAND ajoute, pas ceux du produit : `tiers = (set(tokenize(guard_name)) & _EDITION_TIER_TOKENS) - set(tokenize(identity_name))`. Sans la soustraction, « Ultimate Admiral: Age of Sail », « Homeworld Remastered Collection » ou un DLC nommé « Deluxe Pack » (le mot est DANS le nom AKS) seraient refusés à tort. Coût mesuré des deux variantes sur les 125 sauvetages réels du corpus : 0 régression pour la variante naïve comme pour la variante soustraite — mais seule la soustraite reste sûre hors corpus.

2. Comparer au `_edition_key` du libellé adopté, pas à `tokenize` brut, pour que l'alias GOTY ↔ « Game of the Year » ne fasse pas skipper une adoption correcte.

3. Placer la garde AU SITE D'APPEL (matcher.py:2934, où `guard_name` et `identity_


### P2.16 `src/matcher.py:3188` — La règle absolue « on n'entre JAMAIS de bundle » n'est verrouillée par aucun test

**Le défaut.** Le garde-fou final de la règle dure de Romain (2026-07-07) — `if edition_id == "8": return SkippedOffer(offer, "bundle edition resolved — no bundles ever")` — n'est jamais pris par la suite : la condition ligne 3187 est évaluée, mais la branche ligne 3188 n'est exécutée par aucun des 2237 tests. Le supprimer laisse la suite verte ET fait entrer un bundle comme candidat.

**Comment ça casse.** Une ligne marchand « Neon Beats Pack (PC) Steam Key GLOBAL » (le mot PACK, pas BUNDLE : `BUNDLE_SKIN_TOKENS` ne couvre que BUNDLE/BUNDLES, donc le skip catégoriel ne se déclenche pas), sur une page AKS dont la carte d'éditions porte un palier nommé Bundle à côté de Standard — forme que EXECUTOR_RULES §4.5 documente comme réelle (« GUILTY GEAR Xrd {Standard, Bundle} », ligne ~805). `detect_edition` rend (Bundle, 8). Si ce garde-fou disparaît d'une refactorisation, la réconciliation R40 juste en dessous — qui commente explicitement « A "Bundle"(8) guess already returned above » et n'exclut donc PAS les bundles — adopte l'id réel de la page et publie l'offre sous « Bundle Edition ». Un bundle créé sur le site vivant, et aucun test ne tombe.

**Correctif proposé.** Ajouter à tests/test_matcher.py (classe MatchOfferTests) trois cas, en assertant la RAISON EXACTE — pas seulement `assertIsInstance(SkippedOffer)` : R40, deux lignes plus bas, émet aussi un skip (« guessed edition unverified (audit P1-1) ») et un `assertIsInstance` lâche resterait vert après la régression.

1) Cas TITRE, page portant un palier Bundle (LE cas qui compte, le seul qui distingue le garde-fou de la réconciliation R40) :
   result = match_offer(_offer("Neon Beats Pack (PC) - Steam Key - GLOBAL"),
                        self._resolver(editions={"1": {"name": "Standard"}, "444": {"name": "Bundle Edition"}}))
   self.assertIsInstance(result, SkippedOffer)
   self.assertNotIsInstance(result, Candidate)
   self.assertEqual(result.reason, "bundle edition resolved — no bundles ever")
   (Sans le garde-fou : `Candidate ('Bundle Edition','444')` — vérifié.)

2) Cas SLUG, même page (fo


### P2.17 `src/matcher.py:3457` — La plateforme réelle de la page AKS cible n'est jamais vérifiée : `page_platform` est extrait puis jeté

**Le défaut.** Le seul contrôle d'une page cible console est la comparaison de NOMS `_identity_tokens(console_page_identity(page.aks_name)) == _identity_tokens(identity_name)` — or `console_page_identity` retire précisément le suffixe de plateforme, donc « Hades PS4 », « Hades PS5 » et « Hades » sont tous égaux à « Hades ». Le seul signal qui distinguerait les pages, `AksResolution.page_platform` (l. 1744, rempli l. 1982 depuis `<meta data-itemprop="platform">`), n'est lu par AUCUNE décision : le bucket d'une famille est écrit sur la page que l'onglet (ou la devinette de slug, l. 3393) a rendue, quelle que soit sa plateforme réelle.

**Comment ça casse.** Deux chemins, tous deux exécutés. (a) Ancre console : quand les paliers de slug PC renvoient 404, le code sonde `buy-<slug>-ps5-compare-prices/` ; `http_get` suit les 301/302 même domaine (canonicalisation) et `_response_to_probe` conserve l'URL DEMANDÉE — une redirection WordPress vers la page PC renvoie donc un 200 portant le corps de la page PC. Ligne Kinguin « Hades PS5 CD Key » → candidat cible **produit AKS 26712 « Hades » (la page PC)** avec le bucket **88ps5h « PS5 »** : une clé console créée sur le produit PC, la panne « Riders Republic » à l'envers. (b) Onglet : si le `href` de l'onglet `ps5` sert la page PS4, la cible est construite en `platform=PS5`, bucket `88ps5h`, sur le produit **85104 « Hades PS4 »** — le contrôle d'identité ne peut pas le voir. La spec §4.12.1 documente déjà que les onglets pointent parfois ailleurs (Elden Ring → Tarnished Edition Switch 2), c'est même la raison d'être du contrôle d'identité.

**Correctif proposé.** La correction proposée tient, avec trois précisions qui décident de sa justesse :

1. **La table inverse doit être bâtie sur le vocabulaire de la META, pas sur les titres d'onglets** — les deux divergent, et la fixture le montre : `_tab_active("Xbox Series", "Xbox Series X")` (tests/test_console_keys.py:724) → `title=" Xbox Series"` mais `content="Xbox Series X"`. Jeu attendu par famille, d'après §4.12.1 et les asserts de tests/test_console_keys.py:755-793 : XBOX_PC/PC → `PC`, PS4 → `PS4`, PS5 → `PS5`, XBOX_ONE → `Xbox One`, XBOX_SERIES → `Xbox Series X`, SWITCH → `Switch`, SWITCH2 → `Switch 2`. Comparaison insensible à la casse contre exactement ces valeurs ; toute autre valeur, `""` incluse, est un refus fail-closed (« console: la page <url> annonce la plateforme <X>, pas <FAMILY> — non entrée (R45) »). Le refus sur `""` est cohérent avec les normes du projet (R19 sur une carte d'éditi

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


### P2.18 `src/merchants/g2a.py:122` — `console_pc_declared` absent chez G2A / GameSeal / Driffle / K4G : la garde P2 « Xbox + PC sans Play Anywhere » ne se déclenche jamais

**Le défaut.** EXECUTOR_RULES §4.12.3 dit que `k4g.py`, `driffle.py`, `g2a.py` et `gameseal.py` utilisent « the shared runs on their slug » — or la lecture partagée `slug_families` renvoie `pc_declared` (adjacence `pc`/`windows`), tandis que les quatre fiches implémentent leur propre `_URL_RUN_RE` qui CONSOMME le jeton `pc` dans le groupe `run` et jette l'information, et aucune des quatre ne déclare `console_pc_declared`. Résultat : `ConsoleSignal.pc_declared` reste False, et la garde P2 de `_console_plan` (l. 3411-3416, « merchant declares Xbox + PC but the AKS page does not list Xbox Play Anywhere — not entered (R45) ») est morte pour ces marchands.

**Comment ça casse.** Ligne G2A écrite dans le docstring même du hook : `.../call-of-duty-black-ops-6-xbox-series-x-s-pc-xbox-live-key-united-kingdom-i10000339529001`, titre « Call of Duty: Black Ops 6 - Xbox Live Key - UNITED KINGDOM ». Le marchand déclare Xbox Series X|S **et PC** dans son slug. La page AKS du jeu ne liste pas « Xbox Play Anywhere » (official platforms Steam / Battle.net). La spec P2 exige un skip (contradiction non arbitrée) ; le code produit un candidat entré en Xbox Series UK, bucket 305. Même chose pour Driffle (`...-europe-pc-xbox-one-xbox-series-xs-xbox-live-digital-key-p...`), GameSeal (`...-pc-xbox-one-xbox-series-x-s-xbox-live-key-eu`) et K4G (préfixe `-(?:pc-)?` de `_URL_RUN_RE`, l. 308).

**Correctif proposé.** La correction proposée tient ; deux précisions pour qu'elle soit sûre.

(a) Préférer l'alternative UNIFORME, qui ferme le trou pour tout marchand présent ET futur portant un hook `console_url_families` : dans `src/console_keys.py`, branche hook (l. 859-863), compléter le signal comme le fait déjà la branche sans hook —
    families = list(declared)
    if cfg.console_pc_declared is None:
        pc_declared = pc_declared or _generic_url_read(url, title.leading_tokens).pc_declared
Attention à la SIGNATURE : `_generic_url_read(url, leading)` prend le second argument (l. 666) ; l'appeler à un seul argument, comme l'écrit le constat, n'enlèverait pas le nom de jeu miroir du slug et ferait fausser un titre comme « PC Building Simulator » (le run de tête doit rester écarté). La garde `cfg.console_pc_declared is None` évite de doubler la grammaire des marchands qui répondent déjà (Gamivo, Eneba

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


### P2.19 `src/merchants/gamerall.py:60` — Gamerall : le jeton de plateforme « UPLAY » n'existe pas dans le vocabulaire du matcher — 100 % des lignes Ubisoft Connect refusées sur un faux conflit

**Le défaut.** `gamerall.PLATFORM_TEXT` mappe « Ubisoft Connect » / « Uplay » vers le jeton `"UPLAY"`, alors que le vocabulaire du matcher est `"UBISOFT"` (`_PLATFORM_WORDS` et surtout la clé de `REGION_IDS`, src/matcher.py:536). Le `offer_page_resolver` renvoie donc une plateforme que ni le contrôle de conflit ni `_region_id` ne reconnaissent.

**Comment ça casse.** Ligne Gamerall réelle « Far Cry 6 (Ubisoft Connect) », URL `gamerall.com/pc-games/far-cry-6-ubisoft-connect-global`. `explicit_platform` (titre) donne UBISOFT ; `gamerall.offer_signals` donne UPLAY ; `_pc_plan` (src/matcher.py:2641) compare les deux et refuse : « Gamerall platform conflict: title=UBISOFT vs offer page=UPLAY — not entered (audit #1) ». Le motif AFFIRME un conflit qui n'existe pas : les deux sources disent la même chose, c'est l'orthographe du jeton qui diffère. Et même sans ce garde-fou la ligne mourrait un cran plus loin, `_region_id('UPLAY','global')` valant None (`REGION_IDS` n'a pas de clé UPLAY) → « region 'global' unavailable for UPLAY (R33) ». Les 14 lignes Ubisoft Connect mesurées sur les 783 du relevé [R54] (et toute future ligne Uplay) sont donc structurellement insaisissables. Pas de mauvaise donnée publiée — un refus fail-closed — mais un refus permanent sur un motif trompeur, juste après que Romain a demandé ce marchand.

**Vérifié directement.** Reproduit par moi : « Assassins Creed Mirage (Ubisoft Connect) » → `SKIP: Gamerall platform conflict: title=UBISOFT vs offer page=UPLAY`. Le fichier marchand se contredit lui-même.

**Correctif proposé.** La correction proposée est bonne mais incomplète sur trois points — telle quelle elle casse la suite de tests.

1) Le jeton, dans `src/merchants/gamerall.py` : ligne 60 `"UBISOFT CONNECT": "UBISOFT"`, ligne 61 `"UPLAY": "UBISOFT"`, ligne 92 `("-ubisoft-connect", "UBISOFT")`, ligne 95 `("-uplay", "UBISOFT")`.

2) Le test existant AFFIRME le défaut et doit changer dans le même commit : `tests/test_merchants_gamerall.py:50` `("Anno 1800 (Ubisoft Connect)", "UPLAY")` → `"UBISOFT"`. Ajouter aussi un cas `url_platform` pour `-ubisoft-connect-…` et `-uplay-…` (il n'y en a aucun aux lignes 100-103).

3) Le garde-fou générique réclamé : oui, mais il doit EXEMPTER les jetons consoles. `XBOX`, `NINTENDO`, `PSN` ne sont pas des clés de `REGION_IDS` (les familles sont `XBOX_ONE` / `XBOX_SERIES` / `PS4` / `PS5` / `SWITCH`) et ne passent jamais par le contrôle de conflit, `offer_page_resolver` n'étant 



### P2.20 `tests/test_submitter.py:2806` — Faux vert : le test qui « verrouille » la preuve de couverture du prove-gone-by-search ne l'atteint jamais

**Le défaut.** `test_scan_search_overflow_raises_fail_closed` capture une `FeedScanError` levée par une AUTRE garde (submitter.py:737, dérive de page) ; la garde qu'il prétend tester — `submitter.py:1001-1002`, « coverage unproven » — n'est exécutée par AUCUN des 2237 tests, et la supprimer laisse la suite entièrement verte.

**Comment ça casse.** Un sweep safe-auto tourne avec `--prove-gone-by-search` (le mode de preuve du balayage non validé). La recherche AKS renvoie des lignes jusqu'à la dernière page du budget (`search_scan_max_pages`) et la navigation annonce davantage de pages. Aujourd'hui `_scan_search` lève « coverage unproven » et le run s'arrête en UNKNOWN. Qu'une édition future supprime ou inverse ce `if` (un `<=` devenu `<`, une refactorisation de `_scan_search`) et l'absence non prouvée devient une absence prouvée : `_verify_gone` conclut « gone from feed », `submitted: true` est écrit dans `submit_plan.json` pour une offre toujours en attente — une FAUSSE preuve de succès sur la seule preuve de succès du projet. Aucun test ne tombe.

**Correctif proposé.** La correction proposée est juste sur le fond (je l'ai vérifiée : elle atteint bien submitter.py:1002), avec deux affinements.

1) Corriger le test d'overflow — tests/test_submitter.py:2806-2808 :
   r1, r2, r3 = trois lignes dont l'URL contient le terme (ex. https://m/hot-p1, /hot-p1-b, /hot-p1-c)
   sub = self._sub(_SearchFake([[r1], [r2], [r3]], nav_max=99))   # 3 pages SERVIES, nav en annonce 99
   sub.search_scan_max_pages = 3
   with self.assertRaisesRegex(FeedScanError, "coverage unproven"):
       sub._scan_search("127", "aks-merchant-feeds-9", "all", "https://m/hot-p1")
   C'est l'assertion nue `assertRaises(FeedScanError)` qui a laissé le faux vert survivre : l'ancrage sur le message est la partie qui empêche la rechute, car la garde de dérive de page lève la MÊME classe d'exception.

2) NE PAS jeter la fixture actuelle : la renommer en test distinct (p. ex. `test_scan_search_re


## P3 — dette et pièges de lecture (8)

### P3.1 `scripts/10_data_entry_auto.py:518` — `recap.json`, le contrat de la passe lu en direct par la console, est réécrit à chaque page sans écriture atomique

**Le défaut.** `persist()` écrit `runs/<run>/recap.json` avec un `write_text` nu — troncature puis réécriture en place — et il est appelé après CHAQUE page (`on_page` → `persist`, l. 538-541) pendant toute la nuit. Le dépôt a pourtant une convention d'écriture atomique établie pour ses fichiers de contrat (`_write_atomic` mkstemp+`os.replace` dans src/admin/validation_io.py:71, src/admin/submit_manager.py:96, src/move_auth.py:68, src/sort_ledger.py:65, src/admin/learning_io.py:44 ; tmp+`replace` dans src/run_marker.py:62 avec le commentaire « atomic: a reader never sees a half-written marker »). `recap.json` est justement le fichier que la console relit en boucle (src/admin/app.py:786) et dont `src/feed_status.py:172` tire les documents par marchand committés sous `docs/feeds/`.

**Comment ça casse.** Le manager SIGKILL l'orchestrateur après sa grâce de 120 s (`_STOP_GRACE_BY_KIND["data_entry_auto"] = 120.0`, submit_manager.py:1114) — ou la session SSH tombe — pendant un `write_text` de `persist()`. `recap.json` reste définitivement tronqué : `feed_status.summarize_pass` ne le voit plus comme un dict (`if not isinstance(recap, dict): continue`, feed_status.py:173) et fait disparaître SILENCIEUSEMENT toute la passe de la nuit du document du marchand, tandis que `/api/data-entry/recap` renvoie `recap: null` (app.py:797, `except (OSError, ValueError)`). Les offres créées existent toujours sur AKS, mais l'artefact d'audit que Romain relit pour « supprimer les erreurs après coup » a disparu. Variante bénigne mais fréquente : un poll de la console tombe dans la fenêtre de réécriture et affiche « pas de recap » alors que la passe avance.

**Correctif proposé.** Appliquer la convention d'écriture atomique déjà en place dans le dépôt (mkstemp dans le MÊME dossier que la cible + `os.replace`, cf. src/admin/validation_io.py:71 et src/run_marker.py:62) à TOUTES les écritures répétées de `recap.json` — le tmp reste dans `runs/<run>/`, donc même système de fichiers, `os.replace` est atomique :
- scripts/10_data_entry_auto.py:518 (`persist()`, appelé à chaque page via `on_page`) ;
- scripts/11_data_entry_by_urls.py:545-547 (`_flush()`, appelé l. 575, 586, 595, 612) ainsi que les deux écritures d'abandon l. 785 et 805 ;
- **à ajouter au constat d'origine, qui l'a manqué : scripts/12_data_entry_by_urls_submit.py:250-251** (`flush(recap)` passé à `run_by_urls_submit` et appelé par marchand PENDANT la saisie réelle, plus l'écriture d'abandon l. 243). C'est le recap d'un run d'ÉCRITURE : c'est celui dont la perte coûte le plus cher, et il est écrit exacteme

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


### P3.2 `src/admin/app.py:310` — Le champ `browser` (état du verrou navigateur) est servi sur deux routes et lu par aucune page — le correctif du 2026-09-18 n'a jamais atteint le client

**Le défaut.** `lock_status()` est calculé et renvoyé sur /api/runs (ligne 341) ET sur /api/sort/runs (ligne 310), mais aucun fichier de src/admin/static/ ne mentionne `browser` : l'indicateur « l'onglet unique est-il pris » demandé par Romain n'existe sur aucune page. Le commentaire lignes 303-307 affirme pourtant que le bug « champ posé sur une route que personne ne lit » a été « corrigé le 2026-09-18 après vérification en production » — le champ a été ajouté à la route sondée sans être retiré de l'autre, et surtout sans être jamais rendu.

**Comment ça casse.** Romain ouvre /executor/tri pendant qu'un run tient le verrou navigateur (par exemple une reconnexion par cookies, qui prend `browser_lock(label="admin_cookie_login")`, ou un run CLI sans marqueur encore écrit). Il attend l'indicateur promis et ne voit rien : la page n'affiche que `busy`. Il lance une action, qui échoue plus tard côté enfant sur `BrowserBusyError` — précisément le diagnostic que ce champ devait donner avant le clic. Le coût secondaire : deux routes calculent un `lock_status()` mort à chaque sondage (toutes les 4 s dans sort.js, 5 s dans auto.js, 2 s dans urls.js).

**Correctif proposé.** La correction proposée (une pastille dans `setBusy()`) est bonne mais insuffisante : elle informe sans EMPÊCHER le clic, alors que l'exécution montre que `_ensure_free()` laisse passer le lancement. Ordre recommandé.

1. Fermer la garde côté serveur (le vrai correctif, celui qui supprime le `BrowserBusyError` tardif) : dans `SubmitManager._ensure_free()` (src/admin/submit_manager.py:312), après le test du marqueur, lire `lock_status(self.repo_root)` et lever `SubmitStartError("browser_busy", f"l'onglet du navigateur est pris par {st['label']} (pid {st['pid']}, depuis {st['since']}) — attends sa fin")` quand `st["held"]` est vrai. `lock_status` ne prend PAS le flock (contrat verrouillé par tests/test_cli_run_visibility.py:110-117), donc ceci ne peut pas faire échouer fail-closed une étape qui demanderait le verrou au même instant. Nuance à assumer : une réutilisation de PID sur une étique


### P3.3 `src/candidate_contract.py:234` — Un id primaire `null` entre dans l'empreinte sous la forme littérale « None »

**Le défaut.** Le refus « un id null n'entre jamais dans une identité » (correctif du 2026-09-14, `flatten_target`) ne couvre QUE `targets[1:]` : `fingerprint` interpole les ids primaires dans une f-string sans contrôle, et `normalize_targets` court-circuite vers `primary_target` (tolérant) dès que `len(targets) <= 1`. Le même dict-cible est REFUSÉ en position 1 et ACCEPTÉ en position 0. DATA_CONTRACTS.md affirme pourtant : « A null aks_product_id / region.id / edition.id in any target is refused by the shared contract … never the literal "None" in a fingerprint » — c'est faux pour le primaire.

**Comment ça casse.** Un candidates.json qui n'a pas été écrit par le matcher courant (édition à la main, ancien format, sortie d'un outil tiers) porte `region.id: null` avec une seule cible miroir. `fingerprint()` rend `'101050001|85104|None|1'` ; le template de validation montre à l'opérateur `region_id: null` ; `load_validation` approuve cette identité incomplète et `verify_approved_against_source` la confirme. Au submit, `_resolve_from_catalog` (src/submitter.py:525) passe `"" if matcher_id is None else matcher_id` à `resolve_catalog_id`, qui résout alors par LIBELLÉ : pour l'édition « Standard » il rend l'id 1 et l'écriture part avec un id que l'approbation ne portait pas. (Pour une région « GLOBAL » la résolution par libellé échoue → blocker : ce côté-là ferme bien.) Je n'ai trouvé AUCUN chemin d'émission côté matcher — il garde `if region_id is None: return SkippedOffer(…)` (matcher.py:2725 et 3068) et `_bucket` (3423) — d'où P3 : promesse de contrat rompue et identité incomplète approuvée, pas une donnée fausse publiée par le pipeline nominal.

**Correctif proposé.** Le correctif proposé est bon dans l'esprit mais NE SE DÉCLENCHERAIT PAS tel qu'écrit, et sa seconde moitié est risquée.

(a) « récupérer `primary_ids(candidate)` et lever si l'un vaut None » ne marche pas : `primary_ids` fait `str(candidate["region"]["id"])` AVANT tout test, donc le None arrive déjà sous forme de chaîne « None ». Prouvé : `primary_ids(c)` -> `('85104', 'None', '1')`. Un test `is None` en aval ne verra jamais rien.
   Bonne forme : faire porter le refus à `primary_ids` lui-même, sur les valeurs BRUTES avant `str()` (l'analogue primaire de `target_ids` -> `flatten_target`) : refuser `None` ET `""` pour aks_product_id / region.id / edition.id, puis faire construire la partie `primary` de `fingerprint` PAR `primary_ids(...)` au lieu de la f-string nue (candidate_contract.py:229-232). Cela seul suffit à fermer la porte d'approbation : `validation_template` -> `candidate_finge

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


### P3.4 `src/merchants/eneba.py:54` — Commentaires périmés depuis [R50] : Eneba et MMOGA promettent un refus fail-closed pour Rockstar / Windows qui n'existe plus

**Le défaut.** Les tables de préfixes d'URL portent des commentaires qui garantissent une sécurité supprimée par `[R50]` (2026-09-16) : eneba.py:54 « "windows": "MICROSOFT",  # no REGION_IDS entry -> fail-closed skip, not Steam », mmoga.py:57 « "rockstar": "ROCKSTAR",  # no plain-key REGION_IDS entry → fail-closed skip, not Steam » et mmoga.py:60 (même phrase pour "windows"). R50 a précisément AJOUTÉ ces compartiments (ROCKSTAR global 15 / us 151 / eu 152 / uk 158 ; MICROSOFT famille Windows 10 : global 246 / eu 244 / us 245 / uk 249). Ces lignes entrent donc désormais en base au lieu d'être refusées, et le commentaire dit l'inverse.

**Comment ça casse.** Le prochain lecteur qui ajoute un préfixe d'URL à Eneba ou MMOGA recopie le motif documenté — « je mappe le préfixe vers un jeton sans compartiment, le matcher refusera » — alors que ce raisonnement est faux depuis R50 pour ROCKSTAR et MICROSOFT, et qu'il est de toute façon fragile : c'est `REGION_IDS` qui décide, pas la table du marchand. Le même commentaire rend invisible le fait que ces lignes échappent au contrôle R20 « plateforme du titre absente des official platforms » : `PAGE_PLATFORM_NAMES` ne contient ni ROCKSTAR ni MICROSOFT, donc `page_name` vaut None et le test de contradiction (src/matcher.py:3071-3077) est intégralement sauté pour ces deux familles — un angle mort qui n'existait pas tant que ces lignes mouraient sur « no region id ». Je n'ai pas pu prouver hors ligne que les pages AKS écrivent bien « Rockstar » dans leur ligne « official platforms », donc je ne classe pas cet angle mort comme défaut de données : je le signale comme conséquence non documentée.

**Correctif proposé.** Corriger les CINQ commentaires périmés (le constat n'en voyait que trois), sans toucher à une seule ligne de comportement :

1. src/merchants/eneba.py:54 — `"windows": "MICROSOFT",` → commentaire : « compartiment Windows 10 mappé depuis [R50] (global 246 / eu 244 / us 245 / uk 249) — la ligne ENTRE ; ce mappage existe pour ne pas retomber sur le défaut STEAM. »
2. src/merchants/mmoga.py:57 — `"rockstar": "ROCKSTAR",` → « compartiments Rockstar mappés depuis [R50] (global 15 / eu 152 / us 151 / uk 158) — la ligne ENTRE ; avant R50 seul gmg_gift existait, d'où l'ancienne mention "no plain-key entry". »
3. src/merchants/mmoga.py:60 — `"windows": "MICROSOFT",` → même formulation qu'en (1).
4. src/matcher.py:1038 (`_PLATFORM_WORDS`, chemin titre partagé par TOUS les marchands) — même correction que (2). C'est le site le plus important, absent du constat d'origine.
5. src/matcher.py:1085 (bran


### P3.5 `src/submitter.py:310` — Le remap libellé→id live (« the wrong-edition fix ») est inerte pour tout seau de région à id non numérique — donc pour 9 des 21 seaux console de [R45]

**Le défaut.** `_norm_option_text` ne retire le suffixe d'id du libellé catalogue que s'il est purement numérique (`re.sub(r"\s*\(\d+\)\s*$", …)`). Les seaux console à id alphanumérique (24eu, 24us, 88eu, 88us, 88uk, 88ps5h, 99eu, 99us, 992…) gardent donc « (24eu) » dans le texte normalisé, la comparaison de libellé échoue toujours, et `resolve_catalog_id` retombe systématiquement sur la voie `source="id"` — celle qui, par construction, « validates EXISTENCE only ».

**Comment ça casse.** Le catalogue vivant renumérote un seau console (le dépôt pose cette dérive en principe : en-tête de src/aks_lists.py « IDs may drift like the region/edition catalog », §4.8 « The live WP-admin dropdown is the source of truth … static tables are only a guide »). Pour « Xbox Game Code EUROPE » (24eu) la protection prévue — « Prefer it (this is the wrong-edition fix: trust the live label→id over a possibly-stale matcher id) » — ne s'exécute jamais : si l'id 24eu existe encore mais désigne désormais un autre seau, il est accepté tel quel et écrit. Impact AUJOURD'HUI nul en écriture (un id disparu échoue fermé sur `by_id`) : c'est une garde éteinte, pas un défaut vivant — d'où le P3.

**Correctif proposé.** Élargir la regex de `_norm_option_text` au vocabulaire réel des ids : `r"\s*\([0-9a-z]+\)\s*$"` (insensible à la casse), ce qui couvre 24eu / 88ps5h / 992 sans toucher aux libellés d'édition (qui ne portent pas de suffixe). Vérifier au passage le BOM : `﻿` n'est pas retiré par `_norm_option_text` alors que `_strip_bom` existe déjà pour la frappe Selectize — « Xbox/PC GLOBAL » (306) ne se résout aujourd'hui par libellé que parce que le BOM est en TÊTE et que la comparaison est une égalité stricte ; le normaliser rendrait la voie libellé fiable pour les 21 seaux. Ajouter un test qui, pour chaque entrée de CONSOLE_REGION_LABELS, exige `resolve_catalog_id(...)['source'] == 'label'`.

> Trouvé par la passe de complétude (les 12 dimensions l'avaient manqué), non contre-vérifié.


### P3.6 `src/submitter.py:1849` — Chemin by-urls : l'index de localisation est effacé après CHAQUE création, contre l'intention du commentaire qui le précède

**Le défaut.** `keep_index = ctx.get("prove_gone_by_search") and not ctx.get("search_locate")` vaut False sur le chemin by-urls (`--locate-by-search`, où les deux drapeaux sont vrais). L'index `ctx["index"]` / `ctx["by_url"]` — construit par `_index_by_search` avec 3 tentatives par candidat — est donc vidé et remplacé par les 0-1 lignes de la recherche de preuve après chaque création. Le commentaire juste au-dessus (l. 1843-1848) pose pourtant la règle inverse : « never wipe it with the search's 0-1 rows ». La règle est honorée pour le sweep (page-hint) et violée pour by-urls.

**Comment ça casse.** Lot by-urls de N candidats chez un marchand (chemin `scripts/12_data_entry_by_urls_submit.py`, `05_submit --mode safe --submit --locate-by-search`). Dès la 1re création, l'index est vidé : chaque candidat suivant rate `_locate_row` (« offer not in current feed (by id and by URL) ») et doit repasser par `_relocate_by_url`, qui lance `_scan_search` UNE seule fois, sans les 3 tentatives de `_index_by_search`. Or un `FeedScanError` transitoire (rendu lent de la page de recherche, navigate coincé sous charge CDP — exactement le blip que `_index_by_search` retente depuis 2026-08-26 « a live creation was missed this way ») remonte, run()`  l'attrape en `feed_unreadable`, `stopped="feed_unreadable"`, et `scripts/12` escalade en `submit_not_clean:<marchand>` qui interrompt tout le lot multi-marchands. Second effet : toutes les entrées après la 1re création sont journalisées `submit_row_relocated` avec un `stale_offer_id` qui n'était pas périmé — bruit dans la piste d'audit du seul stage qui écrit.

**Correctif proposé.** La correction d'une ligne proposée est la bonne, mais telle quelle elle laisse un test au rouge et un fixeur risque de la révoquer. Livrer les quatre morceaux ensemble :

(a) src/submitter.py:1849 → `keep_index = bool(ctx.get("prove_gone_by_search"))` (retirer `and not ctx.get("search_locate")`).

(b) Réécrire le test qui verrouille le comportement actuel : tests/test_submitter.py::SweepProveGoneBySearchTests::test_by_urls_path_still_refreshes_its_index_from_the_search affirme `set(ctx["index"]) == {"9"}` et le commente « unchanged by-urls behaviour ». Il doit désormais affirmer que l'index est CONSERVÉ sous `search_locate=True` (et garder l'assertion sweep existante, inchangée).

(c) Réécrire le commentaire l.1843-1848 pour couvrir les deux chemins : une preuve par recherche ne couvre que l'offre cherchée, donc sous l'un comme l'autre des chemins adossés à la recherche `fresh_index` n'e

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


### P3.7 `src/validation.py:153` — Deux entrées approuvées pour la même empreinte : le lot entier s'arrête après le 1er ajout

**Le défaut.** `load_validation` boucle sur les entrées de validation.json sans jamais vérifier l'unicité des empreintes approuvées : la même empreinte listée deux fois produit DEUX fois le même dict candidat dans approved.json, et `verify_approved_against_source` re-dérive le même doublon — la garde anti-falsification est donc d'accord. La console refuse ce cas (`duplicate_decision`, validation_io.py:287) ; le flux CLI manuel, celui que la spec §5 documente, ne le refuse pas.

**Comment ça casse.** L'opérateur remplit validation.json à la main et duplique une entrée par copier-coller (ou concatène deux templates du même run) : l'offre 101050001 apparaît deux fois avec `approve: true`. `04_validate.py check` sort en 0 avec `approved: 2`. Au submit, `Submitter.run` construit `signature = f"submit:{offer_id}"` (submitter.py:1539) et le StepGuard de 05_submit est configuré avec `max_attempts_per_signature=1` : la 2e occurrence est REFUSÉE par la garde, ce qui met `stopped = "guard_blocked"` puis `break` — le lot s'interrompt là et toutes les offres validées suivantes ne sont jamais saisies. En plus, la FC3 (BlockLedger, 05_submit.py:499) compte ce blocage : deux passes ainsi terminées exigent ensuite un `--acknowledge-block` humain. Un doublon de frappe transforme un lot safe validé en demi-lot plus une garde à déverrouiller à la main.

**Correctif proposé.** Garder la correction proposée, avec deux ajustements.
1. Dans `load_validation` (src/validation.py, avant la boucle d'approbation), refuser TOUTE empreinte dupliquée dans `data["candidates"]` — approuvée ou non : un doublon non approuvé est la même édition manuelle malformée. Même discipline que la console : `raise ValidationError(f"la même empreinte apparaît deux fois dans la validation : {fingerprint}")`, fichier rejeté en entier (§5, jamais d'approbation partielle). Aucun effet de bord côté console (elle refuse déjà en amont, `duplicate_decision`) ni côté safe-auto (une décision par candidat, `_seen`). Ne toucher ni à la formule d'empreinte ni à la re-dérivation exacte de `verify_approved_against_source`.
2. Retirer du constat la partie FC3 / `--acknowledge-block` : elle est fausse (refus souple ⇒ `blocked=False` ⇒ la passe est comptée propre). Si on veut aussi rendre l'arrêt lisible,


### P3.8 `tests/test_sort_sql_console.py:399` — La garde qui protège la décision « Kinguin valid until » ne ferme pas, et son test n'inspecte que la moitié de la surface

**Le défaut.** `test_no_rule_blacklists_an_activation_deadline` ne parcourt que `RULES` (la liste écrite à la main), alors que `sort_sql_payload` fusionne les motifs PROMUS dans le même tableau `rules` et le même bloc `all_sql` que Romain colle dans phpMyAdmin ; et `sort_sql_promoted.promote()` ne consulte jamais `RETIRED`, si bien que `%valid-until%` → Blacklist peut revenir par la console sans qu'un seul test ne bronche.

**Comment ça casse.** Depuis la console `/sql`, une promotion de `%valid-until%` vers la liste 8 (Blacklist) est acceptée : elle s'écrit dans `data/sort_sql_promoted.json` (versionné, donc propagé aux deux serveurs), `sort_sql_view` la rend comme n'importe quelle règle et l'agrège dans `all_sql`. Romain colle le bloc, et les clés portant « (valid until <mois> <année>) » repartent en Blacklist — exactement ce que la décision arbitrée du 2026-09-14 interdit et que le retrait du 18/09 avait acté. `test_no_rule_blacklists_an_activation_deadline` reste vert parce qu'il ne regarde pas le magasin promu.

**Correctif proposé.** Quatre points, le (4) étant le plus important et absent du constat d'origine :

(1) `src/sort_sql_promoted.py`, avant le contrôle de doublon de la ligne 115 : `from src.sort_sql_rules import RETIRED` puis `if pattern in RETIRED: raise ValueError(RETIRED[pattern])`. Le test porte sur le MOTIF SEUL, pas sur `(motif, cible)` : `RETIRED` est un `dict[motif, raison]` sans cible, et `%valid-until%` est faux vers n'importe quelle liste. `app.py` transforme déjà tout `ValueError` en 400 `bad_promotion` avec le message — la raison de retrait, déjà rédigée, s'affiche telle quelle. Rien d'autre à changer.

(2) `src/admin/sort_sql_view.py::_mine` : filtrer `seen` par motif (`if pattern in RETIRED: continue`). Attention, la rédaction du constat ne type-checke pas : `known` est un ensemble de tuples `(pattern, target)` et `RETIRED` un dict motif→raison ; on ne peut pas l'unir à `known`. À étiqueter co

> Un des deux vérificateurs a réfuté ce constat — à trancher avant de coder.


## Constats réfutés par la contre-vérification (2)

- `src/merchants/gamerall.py:182` — Gamerall : le crible de région du TITRE traduit « ROW » par GLOBAL, en contradiction avec les deux autres tables du même fichier et avec [R34]
  
  Rejeté : Le scénario annoncé est IMPOSSIBLE avec le code tel qu'il est, et il l'est pour N'IMPORTE QUEL mot de région, pas seulement ROW.

1) PREUVE PAR CONSTRUCTION — `title_region` et `precheck` du même fichier sont mutuellement exclusifs. `title_region` (gamerall.py:195-211) ne renvoie non-None que si le texte APRÈS la dernière parenthèse est non vide (`if not tail.strip(): return None`). Or `_PLATFORM_
- `src/submitter.py:994` — Preuve « disparue du feed » par recherche : nav_max=0 sur une page AVEC lignes est accepté comme « unique page de résultats » → faux gone
  
  Rejeté : Le constat repose sur une prémisse que le dépôt a déjà tranchée LIVE et documentée : il n'existe pas de « page 2 de résultats » sur la page de recherche AKS.

1) Fait établi, contradictoire avec le scénario. `docs/EXECUTOR_RULES.md:109-115` — « EXCEPTION — the `aks-merchant-feeds-search` page does NOT paginate `[P2-13]` (resolved live 2026-09-04, `scripts/probe_p2_13_search_navmax.py`). The all-me
