# Audit complet — 2026-10-02

Portée : tout le projet au commit `75edb04` (code, écriture, exploitation, console, données de
production, tests, documentation) **et** les trois VPS. Romain : « On fait un audit complet du
projet en profondeur, tous ces aspects, de A à Z. GO ».

Méthode : sept dimensions relues en parallèle par sept agents indépendants, **en lecture seule**
(aucune écriture, aucun redémarrage, aucune requête vers AKS ; diagnostics ssh en lecture sur les
deux autres VPS, le compte `hermes` du VPS 3 jamais touché). Les décisions arrêtées de Romain
(`AGENTS.md`, « Reviewed decisions ») étaient interdites aux auditeurs : aucun constat ne les
rouvre. Les constats les plus lourds ont été **revérifiés à la main** (section suivante) sur les
vrais `submit_plan.json`, le vrai code et la vraie configuration.

Résultat : **0 P0** (aucune double écriture — 12 102 créations en 7 jours = 12 102 offres distinctes —,
aucune écriture sans garde, aucun secret dans le dépôt), **16 P1**, une trentaine de P2, des P3
d'hygiène — et **neuf décisions à prendre par Romain**.

## Ce que j'ai vérifié moi-même

| Constat | Vérification |
|---|---|
| A1 — monnaie Diablo IV « Platinum » écrite | 15 entrées `submitted: true` dans les `submit_plan.json` Wyrel (p21/p23/p34, passe 2), page `diablo-4-platinum-xbox-series`, édition = montant (500, 2800, 5700, 11500…) |
| A2 — CJS « … Access (Digital Download) » | 35 entrées `submitted` (Nioh 3 PS5, Epic Mickey Rebrushed Switch/PS, Madden NFL 27, UFC 6…) ; `classify_console("… Access")` → refus R45, `classify_console("… Access (Digital Download)")` → XBOX_SERIES accepté |
| A3 — E06 adopte un palier que le titre ne nomme pas | Bratz Rhythm & Style ×2 et Grind Survivors `submitted` en **Deluxe** |
| A4 — Eneba PC muet → GLOBAL implicite | `precheck_skip` None, `detect_region` → `('GLOBAL','2',True)` sur « Flight of the Paladin » |
| A5 — CJS console « Europe & UK » refusé | `classify_console` → `region_words ('Europe','UK')`, `region_base None` → refus « contradiction » avant toute lecture AKS |
| B1 — « créées » compte les « already exists » | sur TOUS les plans : 15 044 `submitted`, **991** dont le signal AKS ne porte que « already exists » (ligne déplacée en Blacklist, rien créé), **2** partielles serveur (Red Faction Gamerall p6, Dark Side of the Moon Eneba p42) |
| B2 — un état inconnu comptable comme créé | `scripts/10_data_entry_auto.py:432` : `created_ok = "gone" in ps.lower()` |
| C1 — plantage du balayage jamais signalé | `main()` de scripts/10 appelle `run_loop` / `run_pass` sans `try/except` ; `auto.js:279` garde `running = !rec.finished_at` quand le manager dit « libre » |
| D1 — clé `page-catalog` = code arbitraire | `/home/debian/.ssh/authorized_keys` (cette VM) : `restrict,command="/usr/bin/python3 -" … page-catalog ancien->nouveau VPS (2026-09-21)`, sans `from=` ; canal utilisé le 21/09 seulement |
| E1 — G2A « Steam Gift » refusé « no platform » | `declared_platform_of` → None et `explicit_platform_from_url` → None sur « OMG Zombies! Steam Gift GLOBAL » / `…-pc-steam-gift-global-…` (G2A lit la plateforme dans l'URL, et le scan ne connaît que `-steam-key-`) |
| E2 — « Saints Row » lu comme ROW | `precheck_skip` → « forbidden region: ROW » sur Gamerall « Saints Row (Steam) » ET Wyrel « Saints Row IV - Commander-In-Chief Pack (DLC) Standard PC Global » |
| E3 — Wyrel « Digital Deluxe » écrit en Standard | 100617873 / 100617761 « ROMANCE OF THE THREE KINGDOMS XIV: … EXPANSION PACK (PC) Digital Deluxe … Steam Gift » `submitted`, édition **Standard**, Steam Gift EU (259) / Steam Gift (25) |
| G1 — ssh par mot de passe, root compris | `sshd -T` : `permitrootlogin yes`, `passwordauthentication yes` (via `50-cloud-init.conf`), mot de passe root posé, **20 043** échecs depuis le dernier démarrage ; connexions root par mot de passe ACCEPTÉES du 23 au 30/09 depuis 217.65.139.x, 103.192.205.6, 150.228.85.54, 212.102.48.11, 193.19.207.x, 169.155.235.213 |

## Décisions à prendre (Romain)

1. **CJS « Access (Digital Download) »** : compte ou vraie clé ? — *Tranché le 07/10 : clé OU compte,
   seule la page CJS le dit et elle ne se lit pas → refus nommé `[R72]` ; 52 écrites en tout, à relire
   une par une (`audit_2026-10-02/cjs_access_ecrites.csv`).*
   35 offres déjà créées comme clés
   (A2). Si compte : correction manuelle des 35 + règle.
2. **Monnaie de jeu quand AKS a une page dédiée** (A1) : on garde les 15 « Diablo IV Platinum »
   et on amende « jeux seulement » pour ces pages-là, ou on les retire et on bloque « montant +
   nom de monnaie » ?
3. **Eneba PC sans aucune région** (A4) : silence = GLOBAL (comme Kinguin / MMOGA / Loaded, à
   écrire dans `eneba.py`), refus, ou lecture de la page Eneba (elle répond 200) ? 104 créations
   déjà faites en GLOBAL implicite, aucune erreur prouvée.
4. **Marchand ajouté en cours de boucle** (C4) : une passe (comportement actuel de la boucle) ou
   permanent (comportement de la relance de maintenance) ? Les deux doivent s'aligner. — *06/10 :
   la relance de maintenance suit désormais la boucle (une passe : ajouts dus remis en file,
   ré-audit Codex) ; reste à trancher si la boucle elle-même doit les garder.*
5. **Garde bloqué / dix échecs** (C5) : la passe continue sur les autres marchands (somme de deux
   décisions revues) — garder, ou arrêter la passe tout de suite ?
6. **Les adresses IP des connexions ssh root** (G1) : sont-elles toutes les tiennes ? Si une seule
   ne l'est pas, c'est une compromission à traiter avant tout le reste.
7. **La pile héritée sur l'ancienne VM** (G2 : conteneur `aks-agent-orchestrator` qui monte les
   clés privées de `debian`, `litellm-proxy`, `hermes-web-ui`, `hermes-gateway`) : morte ? Si oui,
   on l'arrête et on révoque ses clés.

8. **G2A « Steam Gift »** (E1) : 729 offres refusées sous un motif faux (« no platform in title »),
   0 entrée depuis le 10/08 — on les entre en Steam GIFT 25/259 (lire `-steam-gift-` dans l'URL),
   ou on les refuse exprès, avec un motif qui le dit ?
9. **Un mot de région placé AVANT un créneau de région explicite** (E2 : « Saints Row … Global »,
   « Planet Zoo … Oceania », « Pure Farming 2018 Germany Map … Global », ~50 refus) : propose
   que le créneau explicite l'emporte (« Global » dit la région, « Row » est un mot du nom) ; a
   minima, `row` ne doit pas être lu dans `saints-row`.

Plus deux questions de fond : les **snapshots fournisseur** des VPS sont-ils actifs (aucune
sauvegarde de `runs/`, `logs/`, `state/` n'existe de l'intérieur) ; et **Chromium** reste bloqué
4 majeures en retard (149/150 vs 154 security) — dette assumée (décision revue), à lever
seulement par une décision explicite, les trois machines ensemble.

---

## A. Logique de matching

Corpus : 25 771 offres distinctes, 3 602 candidats, 22 995 refus (boucles B du 29-30/09), et
15 478 enregistrements de création lus dans TOUS les `submit_plan.json`.

| # | Sév. | Constat | Où | Correctif |
|---|---|---|---|---|
| A1 | **P1** | Monnaie de jeu écrite : Wyrel « Diablo IV 11500 Platinum (Xbox Series X) … » → page `diablo-4-platinum-xbox-series`, édition = montant ; **15 créées**. `CATEGORY_SKIP` connaît POINTS/COINS/GEMS… mais pas PLATINUM ; `[R53b]` Wyrel ne lit le non-jeu que dans la fente « Other ». Eneba est refusé pour la même monnaie (« extra words ») : incohérence | `src/matcher.py:260`, `:440`, `src/merchants/wyrel.py:219` | motif « montant adjacent » `\b\d{3,6}\s+(PLATINUM|CP|COD POINTS|V-?BUCKS|ROBUX…)\b` — jamais PLATINUM nu (64 titres légitimes : « Company of Heroes 2: Platinum Edition »…) ; décision 2 |
| A2 | **P1 si compte** | CJS « <jeu> <plateforme> Access (Digital Download) » entré comme clé : l'ancre `" ACCESS $"` de `_non_game_marker` ne voit pas le suffixe ; `account_signal` ignore ACCESS → le dernier garde du submitter est aveugle aussi ; **35 créées** ; chez Kinguin la même livraison = compte (145 refus) | `src/console_keys.py:802`, `:757`, `src/submitter.py:144` | lire ACCESS comme item de LIVRAISON du créneau de plateforme (pas une ancre élargie : « Early Access », « Access Pass » doivent rester) + le faire connaître à `account_signal` (liste 30) ; décision 1 |
| A3 | **P1** | E06 « seau unique » adopte un PALIER (Deluxe/Gold) que le titre ne nomme pas : « Bratz Rhythm & Style PC/XBOX LIVE Key EUROPE » → Deluxe(7) ; **3 créées**. La décision E06 (21/09) visait « Early Access », pas un palier | `src/matcher.py:5086-5106` | refuser quand le seul seau porte un palier absent de `tokenize(guard_name)` ; garder l'adoption pour Early Access / libellés non-palier |
| A4 | P2 | Eneba PC muet (ni titre ni URL) → GLOBAL implicite ; 129 lignes, **104 créées** ; GameBoost/GamersOutlet sont refusés pour le même silence ; Eneba écrit GLOBAL en toutes lettres sur 806 / 5 515 lignes | `src/matcher.py:1817`, `src/merchants/eneba.py:139` | décision 3 |
| A5 | P2 | CJS console « Key: Europe & UK » refusé à chaque passe : **209 offres distinctes** (Yakuza 4/5/6, Smash Bros Ultimate, Steelrising…), zéro appel AKS ; `[R67]` l'applique au PC seulement | `src/matcher.py:5445`, `src/merchants/cjs.py:88` | `cjs.console_region_slot` sur le modèle de `loaded.py:67` (« Europe & UK » → « Europe ») |
| A6 | P2 | `match_extras_to_page_edition` : 1 édition compatible ⇒ refus, ≥ 2 ⇒ acceptation (et adoption de palier possible) — verdict dépendant du NOMBRE d'éditions de la page ; refus probables : « Fallout 76: Mojave Deluxe Edition » ×7, « Sea of Thieves: 2026 Premium Edition » ×3, « Space Engineers 2025 Complete Edition » ×8, « MX vs ATV Legends - 2026 Deluxe Edition » ×5 ; adoption de mauvais palier : 0 mesurée | `src/matcher.py:3896-3911` | une règle pour les deux branches : résidu = bruit de format OU paliers que le TITRE nomme ; branche `exact` sur `_EDITION_RESIDUE_NOISE` |
| A7 | P3 | Deux vocabulaires de verrous tenus à la main ont divergé : 47 pays (SINGAPORE, HONG KONG, NETHERLANDS, FRANCE, ITALY…) absents du scan générique → GLOBAL implicite, sauvé par le filet R16 (« extra words ») sous un faux motif | `src/matcher.py:164` vs `src/merchants/common.py:295` | dériver `FORBIDDEN_REGIONS` de `FORBIDDEN_WORDS` (hors exclusions délibérées) ou test d'inclusion |
| A8 | P3 | `docs/MERCHANTS.md:123` dit encore CJS « identité seule » (table périmée) | — | corriger la ligne |

Solide (vérifié sur le corpus) : le filet R16 tient (aucun candidat à région-pays non vendable) ;
CJS `[R67]` PC juste sur 2 743 lignes ; comptes et non-jeux refusés (Kinguin 145, Wyrel « Other »
2 634) ; cadeaux : 15 candidats GIFT tous à livraison explicite, aucun élargissement ; console :
refus de région avant toute lecture AKS, DLC(16) jamais hors R18.

## B. Chemin d'écriture et sa preuve

Neuf jours (640 plans, 8 531 entrées) : 8 360 « gone », 23 « STILL in feed » (tous expliqués par
P2-12), 7 UNKNOWN (**7/7 ont arrêté le run**), 14 coupures AVANT clic (toutes reprises), 85
« Bad request : paramètre offer », 34 « No offer was created », 3 « Unknown error », NO_SIGNAL 0,
`ten_consecutive_failures` 0, mode `safe` partout. 346 tests du chemin d'écriture verts.

| # | Sév. | Constat | Où | Correctif |
|---|---|---|---|---|
| B1 | **P1** | Le « succès » prouve que la ligne est CONSOMMÉE, pas qu'une offre est CRÉÉE : **991 / 15 044** entrées « créées » où AKS a répondu « This offer already exists for locale … » (ligne déplacée en liste 14 Blacklist, rien créé) ; **2** candidats multi-cibles où le serveur a sauté une cible (« Game page not created or empty descriptions ») et créé l'autre : page Xbox One de Red Faction (Gamerall) perdue en silence, comptée succès. Le signal `[data-success]` est capturé (1 500 c.) et jamais lu | `src/submitter.py:2055-2063`, `:2108` | le signal CLASSE une consommation déjà prouvée (jamais la preuve) : `created` / `duplicate` (compteur à part, succès pour la garde) / `server_partial` (signalé, à vérifier à la main) / `unknown` (signal tronqué) ; porter la capture à ~4 000 c. |
| B2 | **P1** | `created_ok = "gone" in ps.lower()` : un UNKNOWN de preuve par recherche porte « (never a 'gone' proof) » → compté créé dans le recap, les totaux de boucle, la pause et Discord (scripts/12 déjà corrigé, scripts/10 non) | `scripts/10_data_entry_auto.py:432` | `created_ok = bool(e.get("submitted"))` |
| B3 | **P1** | Rien n'est journalisé entre le clic « Create » et la fin de la preuve, et la grâce d'arrêt (75 s enfant / 90-120 s manager) est plus courte que des saisies réelles : sur 7 954 intervalles, médiane 51 s, **p99 105 s, max 880 s, 5,8 % > 75 s** ; « Arrêter » pendant une telle offre → SIGKILL entre clic et preuve → `submit_plan.json` jamais écrit, offre INCONNUE non signalée, créations de la page perdues du recap | `src/child_runner.py:27`, `src/admin/submit_manager.py:1300`, `scripts/05_submit.py:630` | `_log("create_clicked", …)` avant le clic + plan écrit après chaque offre ; marqueur « écriture en vol » consulté par l'alarme (attendre, borne dure ~180 s) — pas un simple allongement de 75 s (doit rester < 90/120 s) ; et compter les créations depuis le JSONL quand `rc ≠ 0` |
| B4 | P2 | Verrou navigateur et marqueur de run bornés à la racine du dépôt : deux clones sur ce VPS visent le même onglet CDP ; la preuve par MARCHE ne vérifie que `p=` dans l'href (ni store, ni list, ni available) | `src/browser_lock.py`, `src/run_marker.py`, `src/submitter.py:796`, `:838` | clé du verrou dérivée de l'endpoint CDP, hors dépôt ; comparer store/list/available |
| B5 | P2 | « Bad request : paramètre offer manquant » est PASSAGER (79 / 84 URL créées ensuite, même triplet) ; la doc l'attribue à la nature de l'offre | EXECUTOR_RULES §6 l. 2640, SUBMITTER_SPEC l. 160 | corriger la doc ; classer « passager côté serveur » dans le rapport |
| B6 | P2 | `_pin_fresh_row` préfère l'URL à l'id : une sœur au même chemin masque la ligne du candidat (vécu Wyrel 24/09) | `src/submitter.py:1360-1366` | priorité (url_key ∧ id) > (url_key ∧ nom) > url_key > id |
| B7 | P3 | Caractères de contrôle dans les libellés tapés (un `\n` final, 11 BOM dans le catalogue vivant) ; contexte de modale sans comparaison de `offer[buy_url]` | `_type_text_trusted`, `_MODAL_CTX_JS` | nettoyer ; comparer `offer[buy_url]` au candidat avant remplissage |

Solide : ligne cliquée = ligne du candidat (nom + clé URL + store, à l'index, à la relocalisation
et sur le rendu frais) ; 0 remap de catalogue sur 250 couples réellement soumis ; readback de
chaque rangée, un seul clic, jamais d'Enter ; reprise `prewrite` structurelle (14/14 reprises sans
rejeu) ; StepGuard 10 d'affilée par construction ; 27 « STILL » tous expliqués.

## C. Orchestration et exploitation

| # | Sév. | Constat | Où | Correctif |
|---|---|---|---|---|
| C1 | **P1** | Une mort brutale du balayage (exception, OOM, SIGKILL d'escalade) n'est dite nulle part : `loop.json` figé « running », console « en cours » à jamais, aucun Discord ; hors boucle, aucune notification n'existe du tout (c'est le mode de la relance de maintenance) | `scripts/10:1168-1182`, `src/admin/submit_manager.py:1231-1250`, `auto.js:277-279` | `try/except` dans `main` → `stopped_reason="crashed"` + notify ; `_supervise` notifie si `exit ∉ {0, 2}` ; la route recap renvoie l'état `admin_submit.json` ; `busy === null` ⇒ `running = false` |
| C2 | **P1** | = B3 vu du bouton « Arrêter » : 69 saisies > 75 s sur la boucle B (3,7 %, max 119 s) ; `scripts/18` s'en protège (`SAFE_STAGES`), le bouton non | `src/child_runner.py:27` | voir B3 |
| C3 | P1 hors boucle / P2 en boucle | Lignes importées EN TÊTE de feed pendant la passe : chaque insertion pousse une ligne ancienne derrière la frontière, sans trace (reproduit : 25 lignes perdues, `coverage=None`) ; une boucle les reprend, un balayage simple les perd | `src/data_entry_auto.py:554`, `:631-645` | mémoriser l'id max de la sonde, compter à la fin les ids supérieurs → `coverage: incomplete_rows_inserted (k)` ; hors boucle, relire |
| C4 | P2 | Marchand ajouté en cours de boucle : UNE passe pour la boucle, PERMANENT pour la relance de maintenance | `scripts/10:874-878`, `scripts/18:684-711` | décision 4 |
| C5 | P2 | Garde bloqué / dix échecs : la PASSE continue sur les autres marchands, seule la boucle s'arrête à sa fin | `scripts/10:787-793`, `src/sweep_loop.py:196-209` | décision 5 |
| C6 | P2 | Aucune rotation : `runs/` 785 Mo / 3 058 dossiers (+500 dossiers, +100 Mo par jour), `logs/` 4 227 fichiers ; `list_runs` déjà 8,5 s (`/api/runs`), > 1 min dans ≈ 30 j | `src/admin/runs.py:204-227` | rétention 14 j des dossiers de page, `list_runs` borné |
| C7 | P2 | Marqueur de run figé après SIGKILL : vivacité par pid seul ; après redémarrage un pid réutilisé « ressuscite » le run → lancements refusés (409) jusqu'à intervention | `src/run_marker.py:37-46` | `boot_id` + `starttime` dans le marqueur ; purge au démarrage si le boot a changé |
| C8 | P2 | Maintenance : les 5 correctifs du 02/10 tiennent ; restes : `finish()` prend l'onglet avant de regarder `busy` ; `postboot` relance un `pending.json` sans contrôler son âge ni le changement de boot ; `--loop-pause-s` non recopié ; `admin_children` illisible ne bloque pas `--pull` | `scripts/18:586`, `:786-797`, `:206-239`, `:407` | dans l'ordre |

Solide : reprise passagère sans rejeu (observée 5 fois en réel) ; la boucle dit ce qu'elle fait
(3 `loop_pass_finished` Discord, haltes nommées) ; pas de double lancement (marqueur, flock,
`_ensure_free`) ; tout HTTP vers AKS en `AKS/Staff` ; needrestart ne redémarre rien.

## D. Console admin et sécurité

| # | Sév. | Constat | Où | Correctif |
|---|---|---|---|---|
| D1 | **P1** | Clé `page-catalog` (21/09) dans `authorized_keys` de `debian` sur cette VM : `command="/usr/bin/python3 -"` exécute ce que le client envoie, sans `from=` ; clé privée sur l'ancienne VM ET dans le conteneur hérité (G2) ; canal mort depuis le 21/09 | hôte + `src/page_catalog.py:295-301` | retirer la ligne ; si ressuscité : script FIXE, `from=`, clé dédiée, options ssh de `overview.ssh_argv` |
| D2 | P2 | `POST /api/sort/sql/measure` accepte un motif sans vocabulaire : un motif à jokers gèle l'admin 2-3 min (GIL), y compris le frein « Arrêter » | `src/admin/sort_sql_view.py:334-366` | `SAFE_PATTERN` en tête de `measure_pattern` |
| D3 | P2 | L'app loopback n'a aucune auth propre : tout processus local déclenche les écritures avec l'identité Basic de son choix (maillon de D1) | `src/admin/app.py:327-335` | jeton injecté par nginx vérifié par l'app, ou socket Unix |
| D4 | P2 | `promote/dismiss/demote` écrivent `data/sort_sql_promoted.json` (suivi par git) depuis le web, `by` pris du corps | `app.py:665`, `:710` | identité Basic ; fichier vers `state/` |
| D5 | P2 | `href` construits depuis des données marchandes sans contrôle de schéma (neutralisé par la CSP) | `app.js:365,382,687`, `sort.js:268`, `urls.js:22` | `safeUrl()` partagé |
| D6 | P2 | CSP sans `base-uri`/`form-action` ; pas de HSTS ; pas de limitation de débit sur le 401 ; fail2ban absent (35 × 401 sur 135 270 lignes : pas d'attaque) | `_send_bytes`, nginx | compléter |
| D7 | P2 | Sorties brutes d'enfants servies sans filtre de texte (aucune fuite constatée) | `submit_manager.py:1238`, `app.py:817` | `scrub_text` |
| D8 | P2 | `from_run` du submit by-urls validé à la main | `submit_manager.py:1018-1020` | `safe_run_dir` + suffixe |

Solide : toutes les écritures réelles exigent le GO tapé + liaison sha + liste blanche serveur ;
CSRF (en-tête + Content-Type + Origin) ; traversée refusée (8 sondes) ; cookies jamais journalisés
ni rendus ; vue d'ensemble : ssh sans commande, `-F /dev/null`, `StrictHostKeyChecking=yes`,
photo scrubbée ; aucun secret dans git ni dans son historique.

## E. Données de production (25/09 → 02/10, les deux VM)

9 290 runs de page, 890 513 lignes relues, **49 208 offres distinctes, 12 151 candidates,
12 102 créées (99,6 %)** — B 8 251, A 3 851. Le submitter n'écarte presque rien : la qualité se
joue dans le matcher. **0 double création** (12 102 ids distincts, `.tryN` compris) ; 261 offres
approuvées dans deux runs, toutes expliquées (page coupée puis reprise, « Bad request » puis
créée). Créées par jour : 1 374 · 2 627 · 2 184 · 1 583 · 1 201 · 1 202 · 1 272 · 654 (02/10 en cours).

| Marchand | Offres | Cand. | Créées | Haltes | Note |
|---|---|---|---|---|---|
| Eneba (B) | 7 021 | 3 108 | 3 119 | 5 | 2 801 console |
| CJS-CDKeys (A+B) | 7 031 | 2 735 | 2 681 | 3 | 65 « STILL » le 25/09 (avant le correctif) |
| GameSeal (A) | 6 456 | 1 952 | 1 952 | 0 | |
| Gamivo (A+B) | 4 061 | 1 148 | 1 148 | 2 | 989 console |
| Wyrel (B) | 4 992 | 556 | 548 | 1 | |
| Discover.games (A) | 827 | 494 | 494 | 0 | |
| Kinguin (B) | 6 789 | 460 | 457 | 2 | 3 578 sans page AKS |
| Gamesplanet FR (A) | 636 | 338 | 335 | 2 | |
| GOG (A) | 2 960 | 315 | 315 | 0 | |
| Gamerall (A+B) | 916 | 255 | 253 | 0 | |
| G2A (A) | 2 858 | 203 | 203 | 0 | 729 « Steam Gift » refusés |
| GameBoost (A) | 2 230 | 174 | 174 | 0 | 1 421 cartes cadeaux |
| Driffle (A) | 590 | 136 | 133 | 0 | |
| Allyouplay (A+B) | 259 | 78 | 91 | 0 | 249 refusés avant `[R68]` |
| MMOGA, K4G, Loaded, Instant Gaming, Electronicfirst, GamersOutlet | 1 582 | 199 | 199 | 0 | |

**Échecs de saisie : 135 sur 12 334 réponses AKS (1,1 %)** — « Bad request : paramètre offer »
108 (passager : 98 re-créées à la passe suivante), « No offer was created » 24 (= 3 offres CJS
« Foregone … » retentées 7 fois chacune + Wyrel « Conclave » ×3 : refus AKS déterministe
martelé), « Unknown error » 3 (Allyouplay 30/09 ; 2 ont disparu du feed sans re-tentative :
probablement créées malgré l'erreur). **UNKNOWN : 23**, dont 13 avant tout clic (reprises au même
run) et 10 après un clic ; **7 jamais re-tentées et jamais revues au feed** → probablement créées,
à vérifier sur AKS. **« STILL in feed » : 74**, aucune réapparue, aucune re-tentée : 74 faux
« FAILED » de la preuve (65 CJS du 25/09 à 01:10-03:23 sur l'ancienne VM, code d'AVANT le
correctif `ee9f25c` ; mais 9 après lui : Wyrel ×8, Gamerall ×1). Reprises passagères 47 (toutes
CDP 45 s ou feed illisible avant écriture). Haltes 15 (déconnexion du 25/09 ~13:03 sur les deux
VPS ; `aks_throttled` Kinguin 01/10). Couverture partielle 10, rien d'anormal.

| # | Sév. | Constat | Correctif |
|---|---|---|---|
| E0 | **P1** (connu) | **125 clés CJS « Key: United Kingdom » écrites en GLOBAL** du 25 au 28/09 (Steam 122, EA 1, Epic 1) — le défaut corrigé par `[R67]` le 29/09 ; rien ne montre qu'elles ont été corrigées sur AKS (liste : [`audit_2026-10-02/cjs_uk_ecrites_en_global.csv`](audit_2026-10-02/cjs_uk_ecrites_en_global.csv), 125 offres relues sur les deux VM) | lot by-urls de correction, ou retrait |
| E1 | **P1** | G2A « Steam Gift » : **729 offres** (25 % des refus G2A) refusées « no platform in title and AKS page does not confirm Direct Publisher (R27) », **0 entrée depuis le 10/08** — `g2a.py` lit la plateforme dans l'URL (`url_platform_scan`) et `_url_platform_scan` ne connaît que `-steam-key-`, pas `-steam-gift-` | décision 8 : lire `-steam-gift-` → STEAM + livraison cadeau (GIFT 25 / 259), ou refus explicite nommé |
| E2 | P2 | Mots de NOM lus comme régions : « Saints Row » → ROW (44 refus dont ~35 faux : Wyrel 15, Gamerall 11, CJS 4…), Planet Zoo « Oceania / Asia / Americas » (Gamerall), « Germany Map », « Legendary Asia », « Ukraine Support », « North America 3 » — ~50 refus alors qu'un créneau explicite dit « Global » / « Europe » | décision 9 |
| E3 | P2 | Wyrel 100617873 / 100617761 « … Digital Deluxe … Steam Gift » écrites en **Standard** (le créneau d'édition dit Digital Deluxe ; R53c devait refuser un créneau sans seau, pas l'aplatir) ; G2A 101158991 « Double Kick Heroes (Xbox One) - Steam Key - EUROPE » écrite Play Anywhere (titre contradictoire) ; Gamesplanet FR 100753530 « SimCity 4: Deluxe Edition (Mac) », 100752507 « KOTOR II (Mac) » écrites sur la page PC (Allyouplay refuse les Mac, `[R68]`) | 5 corrections manuelles ; R53c : refus, pas Standard ; « (Mac) » = refus chez Gamesplanet ; « Steam Key » + « (Xbox One) » = contradiction |
| E4 | P2 | Refus AKS déterministe martelé : Foregone ×3 (7 tentatives), Conclave (3) — re-soumis à chaque passe | mémoire « même offre, même refus ≥ 2 → liste 30 + rapport » |
| E5 | P2 | Instant Gaming « region metadata missing/unparseable » : **82 offres, 19 % de ses refus, constant depuis le 21/09** (Pokémon Legends Z-A, RE7 Gold, Fallout 4 GOTY) — le lecteur de fiche semble cassé sur une partie du catalogue (20 créées sur 446 offres) | relire 3 fiches à la main, corriger le lecteur |
| E6 | P2 | « different/expanded product » à un seul mot d'écart : 1 087, dont 163 une ANNÉE (« Resident Evil 4 (2005) », « Destiny 2: Legacy Collection (2025) », « Rome: Total War Collection (2023) ») et 274 un nombre | l'année d'une version n'est pas un mot de produit — à trancher cas par cas (remake ≠ original) |
| E7 | P2 | Slug strict présent au sitemap mais « no page » : MMOGA 101039551 « Borderlands 2 [EU Key] » (crochet gardé ?), CJS « Lost Planet 2 … (Windows Live) », Kinguin « Bastion Code », « Honeycomb … EU (without CH/HR/RS) PS5 » | 4 cas à relire |
| E8 | P2 | 10 offres approuvées jamais tentées hors page en cours (Gamesplanet 100393351 / 350 / 332 encore pending le 01/10, vues 57-62 fois, plus jamais candidates — règle changée entre-temps, R59 ?) | relire une fois |
| E9 | P3 | Coûts décidés, comptés : CJS « PSN (Playstation) » 885 (P4 PlayStation = refus), CJS Argentina / ROW 751, GameBoost cartes cadeaux 1 421, Kinguin sans page AKS 3 578 (53 % de son feed : vraiment absentes, 2 manquées) ; GLOBAL implicite sur titre sans région : CJS ≈ 416 sans créneau (à confirmer : `[R67]` ne parle que du créneau présent), Kinguin 217, Eneba 90, MMOGA 51, Loaded 20 | — |

À vérifier à la main sur AKS (état inconnu, probablement créées) : Allyouplay 100391061 /
100391041 ; Kinguin 101140732 ; Eneba 101144799 / 101147044 ; Gamivo 100728122 ; CJS 101139740 /
101142139 ; Wyrel 100613527 ; Gamerall 101111368.

## F. Code, tests, documentation

| # | Sév. | Constat | Correctif |
|---|---|---|---|
| F1 | **P1** | La doc se contredit sur la liste blanche : README « 7 proven merchants » (l. 45) vs « 21 » (l. 760) ; Allyouplay/CJS/GameSeal/Eneba « expérimental, dry-run first » (l. 48) alors qu'ils écrivent depuis des jours ; MERCHANTS.md dit Difmark « parqué » (l. 124) et GameBoost « hors liste blanche » (l. 878) alors que GameBoost est dans le groupe A | régénérer la table de statut ; test « aucun nombre de marchands autre que `len(AUTO_MERCHANTS)` ; aucun marchand de la liste décrit “hors liste blanche” » |
| F2 | **P1** | Aucun harnais d'EXÉCUTION pour `urls.js` (chemin d'écriture by-urls, 546 l.), `app.js` (1 345 l.) et `sql.js` — relus comme TEXTE seulement, ce que le projet qualifie lui-même de « ne prouve rien » | `tests/js/urls.test.mjs` puis `app.js`, sur le modèle de `auto_live_page.test.mjs` |
| F3 | P2 | 82 % du temps de la suite (329 s / 399 s) : 55 tests ; 33 tests du mover durent exactement 7 ou 14 s = `empty_confirm_waits (1, 2, 4)` jamais coupé dans leurs fixtures | `m.empty_confirm_waits = (0, 0, 0)` ; pause d'invariants injectable dans 06/09 — gain ≈ 4,5 min |
| F4 | P2 | `_match_offer` 720 l. / 35 return / 13 variables partagées ≥ 200 l. ; `_console_plan` 520 l. / 49 return | trois extractions pures (`_software_candidate`, `_resolve_platform`, `_console_targets`), puis le bloc édition derrière un porteur ; preuve par corpus figé (identité des `Candidate` ET des `reason`) |
| F5 | P2 | Le plan de maintenabilité (lots 3-5) et l'outillage de corpus n'existent pas dans le dépôt | `docs/MAINTAINABILITY_PLAN.md` + `scripts/21_replay_corpus.py` |
| F6 | P2 | Règles codées sans ancre dans EXECUTOR_RULES : `[R55]/[R55b]`, R14, R32b, R32d | index des ids + test |
| F7 | P2 | Helpers JS copiés dans six pages (`$`, `el`, `api`, `setStatus`) ; échafaudage polling/recap dupliqué `auto.js`/`urls.js` | `common.js` |
| F8 | P2 | `_write_json_atomic` ×12, lecture de fiche marchand ×3 (Discover, Gamerall, Gamesplanet — Allyouplay reste sur `page_get`, `[R68]`) | `src/fsutil`, `common.fetch_merchant_page` |
| F9 | P2 | Tests dépendants du temps réel (`test_page_catalog:170`, `test_vps_overview:335`) | asserts sur le fait, horloge injectable |
| F10-12 | P3 | bruit de sortie (696 lignes `http.server`), HANDOFF daté du 15/09 avec du contenu du 27/09, 3 fonctions mortes (12 l.), constante dupliquée `CONSOLE_TOKENS` | nettoyage |

Solide : 3 324 tests verts, déterministes, indépendants de l'ordre ; `requests` seule dépendance
tierce (optionnelle) ; 0 TODO ; constantes spec ↔ code conformes (R30, R66, boucle, 3 cibles,
reprises, CDP) ; 10 d'affilée passé explicitement sur chaque chemin d'écriture ; artefacts, flags
et routes documentés tous présents dans le code.

## G. Infrastructure des trois VPS

B = cette VM (vmi3565249, groupe B), A = ancienne VM (vps-9ee9f9cf, groupe A), S = secours (vmi3615170).

| Point | B | A | S |
|---|---|---|---|
| OS | Debian 13.7, noyau à jour | Debian 12.15, à jour | Debian 13.7, **reboot requis** (noyau 111 installé) |
| Code live | main 75edb04 | main 75edb04 | **branche de travail `price-check-fixed-kind`, 5 fichiers indexés** — pas déployable tel quel |
| Services exécuteur | enabled + actifs | idem | idem |
| Services en plus | avahi | **hermes-gateway, hermes-web-ui :8648, litellm-proxy :8000, pf2-forwarder (36 001 redémarrages, script absent), docker `aks-agent-orchestrator` (host net, :8010, monte `/home/debian/.ssh`)** | price-check (hermes) |
| Chromium | 150.0.7871.100, hold ×3, UA 149 | 149.0.7827.196 | 150.0.7871.181 |
| Exposition (scan v4+v6) | 22/80/443 seuls | 22/80/443 seuls | 22/80/443 seuls + filtre owner |
| nginx / TLS | LE, 66 j, basic auth | 70 j ; **htpasswd du 29/07 : romain, remy (pas garance)** | 85 j |
| DNS au boot | systemd-resolved OK | resolvconf (réparé 30/09) OK | OK |
| sshd | **PasswordAuthentication yes, PermitRootLogin yes, root mdp posé** | yes / without-password, **debian (sudo) par mot de passe**, fail2ban installé mais EN ÉCHEC | **yes / yes, root mdp posé** |
| Disque / journal | 4 % ; journal 791 Mo | **59 %** ; runs 2,2 Go (9 915 dossiers), **journal 3,9 Go** | 3 % |
| Swap | 0 | 0 (7,6 Go RAM) | 0 |
| Clés de `debian` | `page-catalog` python3 - (D1) ; **copie de la clé de déploiement** | clé de déploiement **sans `from=`** ; `id_rsa`, `id_ed25519` de rôle inconnu | OK (`from=`) |
| Sauvegardes | aucune | aucune | aucune |

| # | Sév. | Constat | Correctif (après validation, jamais exécuté par l'audit) |
|---|---|---|---|
| G1 | **P1** | ssh par mot de passe sur les trois, root compris sur B et S ; `50-cloud-init.conf` l'emporte sur `sshd_config` ; 20 043 / 25 344 / 30 388 échecs en 2-3 jours ; root accepté par mot de passe depuis six plages d'IP (décision 6) | clé de Romain posée et TESTÉE, puis `/etc/ssh/sshd_config.d/10-durcissement.conf` : `PasswordAuthentication no`, `PermitRootLogin prohibit-password` (`Match User hermes` sur S si besoin) |
| G2 | **P1** | A : pile héritée vivante, conteneur qui monte toutes les clés privées de `debian` (dont celle qui exécute du Python sur B), configs 644 dans un home 755 lisible par `agent` (groupe docker) | décision 7 ; stop + disable, `chmod`, révocation des clés, `agent` hors du groupe docker |
| G3 | P2 | `pf2-forwarder` en boucle de crash (moitié du journal de A) | disable + rm |
| G4 | P2 | fail2ban de A : « no log file for sshd jail » (backend auto sans rsyslog) | `backend = systemd` |
| G5 | P2 | La session AKS de B n'a pas survécu au redémarrage du 30/09 (A oui) ; cause non établie ; relance automatique après reboot incertaine sur B | inscrire dans MAINTENANCE_VPS ; vérifier à la prochaine maintenance |
| G6 | P2 | Clé de déploiement (GitHub push + shell sur A et S) copiée chez `debian` sur B (ne sert qu'au `git pull`) ; acceptée sans `from=` sur A | clé GitHub lecture seule pour `debian`, `shred` de la copie ; `from=` sur A |
| G7 | P2 | htpasswd divergent (A sans garance) ; mot de passe console jamais tourné, en clair dans `.claude/settings.local.json` de A (600 aujourd'hui, 644 en juillet) et `/root/executor-admin.pass` sur B | rotation + copie du hash ; nettoyage des deux fichiers |
| G8 | P2 | Versions : A et B à 75edb04, `origin/main` à 0f6f916 (3 commits price-check de Romain) ; S sur une branche de travail | pull entre deux balayages ; S : commit/push puis `main` |
| G9 | P3 | Journal sans plafond ; pas de rotation ni de sauvegarde de `runs/`/`logs/`/`state/` (`sort_ledger.json` non recalculable) ; fuseaux mixtes (UTC sur A, Europe/Berlin sur B/S) ; avahi ; pas de swap ; S : `state/active_run.json` périmé ; `scratchpad/` non suivi dans le clone live de A | `journald.conf.d` 500 Mo ; rsync hebdo vers un dossier d'archive ; `Etc/UTC` ; swap 2 Go |

Solide : UA forcé et rendu par CDP sur les trois ; hold apt ; CDP/admin jamais exposés (scannés
en v4 et v6) ; basic auth ; DNS régénéré au démarrage partout ; horloges synchronisées ; `.env`
600 ; clé `aks-overview` bridée sur A et S ; unattended-upgrades sans redémarrage automatique.

---

## Plan de correction proposé (par lots, chacun avec sa suite verte et ses tests)

**Lot 0 — sécurité immédiate (hôtes, 1 h, après les décisions 6 et 7)** : G1 (clé puis mot de
passe ssh coupé, machine par machine, moi connecté dans une seconde session) ; D1 (retirer la
clé `page-catalog`) ; G6 (`from=` sur A, clé lecture seule pour `debian` sur B) ; G3/G4 (pf2,
fail2ban) ; G2 si la pile est morte ; G9 journal.

**Lot 1 — le chiffre « créées » et les états inconnus (code, ½ journée)** : B2 (une ligne), B1
(classification du signal : créées / doublons / partielles / inconnu, compteurs séparés dans
recap, console, Discord), C1 (plantage signalé + console), B3/C2 (trace `create_clicked`, plan
écrit après chaque offre, marqueur « en vol » qui retient l'alarme), C7 (marqueur avec boot).

**Lot 2 — matching (1 journée, après les décisions 1-3, 8-9)** : A1, A2, A3, A5, A6, A7, A8,
E1 (G2A gift), E2 (mot de nom avant créneau), E3 (R53c refus, Mac Gamesplanet, Steam Key + Xbox
One), E5 (lecteur Instant Gaming), E7 ; **corrections manuelles** : les 124 CJS UK (E0), les 5 de
E3, les 9 états inconnus.

**Lot 3 — exploitation (½ journée, après les décisions 4-5)** : C3 (lignes insérées comptées),
C4/C5, C6 (rétention 14 j + `list_runs`), C8 (restes maintenance), G5 (session après reboot),
E4 (refus déterministe non martelé), journal détaillé de la preuve de disparition (74 faux
« STILL »).

**Lot 4 — console et durcissement (½ journée)** : D2, D3, D4, D5, D6, D7, D8.

**Lot 5 — code, tests, doc (1 journée)** : F1 (doc + test de cohérence), F3 (−4,5 min de suite),
F2 (harnais `urls.js` puis `app.js`), F5 (plan + rejeu de corpus), F7/F8, puis F4 par étapes
prouvées au corpus.
