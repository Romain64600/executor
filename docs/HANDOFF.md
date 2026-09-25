# HANDOFF — reprise du projet sur un nouveau serveur

Ce document est le **point d'entrée de reprise** (migration serveur / nouvelle session
Claude). Il capture l'ÉTAT, les DÉCISIONS et les GOTCHAS qui, jusqu'ici, vivaient dans la
mémoire hors-repo de Claude et **ne voyagent donc PAS avec un `git clone`**. Reprise de
session : lis-le en premier, puis `AGENTS.md` + `CLAUDE.md` (les règles), puis
`docs/EXECUTOR_RULES.md` (les règles par étage). Nouveau sur le projet : l'ordre est
`README.md` → `docs/EXECUTOR_RULES.md` → `docs/MERCHANTS.md` → ce HANDOFF (voir §9).
Dernière mise à jour : **2026-09-15** (voir `git log` pour le commit courant).

> ⚠️ Aucun secret ici (cookies WP, mots de passe, codes 2FA n'entrent jamais dans le repo).

---

## 1. Ce qu'est le projet (résumé)

Pipeline **déterministe et fail-closed** de saisie de données pour les feeds marchands
d'AllKeyShop (AKS). Étapes : `02 extract` (scan feed via CDP) → `03 match` (résolution AKS
read-only + règles R01…R46, écrit `candidates.json` / `skipped.json` / `match_meta.json` /
`report.txt`) → `04 validate` (`check` → `approved.json`) → `05 submit` (écriture via la
modale UI officielle) → prove-gone. Claude est **builder** (code/tests/docs/diagnostics read-only),
pas exécuteur libre. Voir `README.md`, `docs/ARCHITECTURE.md`.

Interfaces : CLI (`scripts/NN_*.py`) + page opérateur `/executor/` (service `aks-admin`,
nginx basic-auth). Onglets : `/executor/` (par-marchand), `/tri`, `/auto` (safe-auto sweep),
`/games` (saisie par liste d'URLs AKS = flow by-urls, scripts 11/12).

## 2. Bring-up du nouveau serveur

**La checklist de reconstruction de zéro existe déjà : `ops/BROWSER_RUNBOOK.md §3`** (dans
l'ordre : Chromium 149 + hold → politique UA-Switcher → `aks-chromium.service` → pont socat
`hermes-cdp-proxy.service` → pare-feu → nginx+admin via `ops/INSTALL_ADMIN.md` → marqueur FC2
→ gate invariants → cookies → tests). Points DURS spécifiques à une migration :

- **Marqueur d'autorité FC2** (`/etc/aks-executor.target`) : `sudo sh -c 'hostname >
  /etc/aks-executor.target'` **sur le nouveau box**. Il doit contenir le hostname de CETTE
  machine — copier le marqueur d'un autre box NE transfère PAS l'autorité (`marker_authorizes`,
  `src/aks_env.py`). Sans marqueur valide → `authoritative:false` → **toutes les écritures
  restent verrouillées** (read-only until green, `CLAUDE.md`).
- **Deps** : `sudo apt install python3-requests` (optionnel — `requests` pour le keep-alive ;
  fallback urllib sinon ; `pip install -r requirements.txt` est refusé par PEP 668 sur
  l'interpréteur système de Debian 12 comme 13, cf. `ops/BROWSER_RUNBOOK.md §3`). Le cœur reste
  stdlib-only. Nomenclature complète : §2.1.
- **Gate avant tout write** : `python3 scripts/01_check_invariants.py` doit rendre `ok:true`
  ET `authoritative:true` **sur le VPS**. Un rouge en local/sandbox (`authoritative:false`)
  est normal et ne débloque rien.
- **Session** = cookies WP collés par Romain via la console (login social only ; jamais
  auto-déclenché ; `docs/LOGIN_SPEC.md`). Profil vierge au démarrage.
- **Chromium gelé à 149** (150 SIGTRAP). Ne pas upgrader.

### 2.1 Nomenclature — ce qui est installé sur le VPS (bill of materials)

Inventaire réel (vérifié live 2026-09-09). Install pas-à-pas : `ops/BROWSER_RUNBOOK.md §1/§3`
+ `ops/INSTALL_ADMIN.md`.

**Paquets apt — requis :**

| Paquet | Version | Rôle |
|---|---|---|
| `python3` | 3.11 | cœur de l'executor (stdlib only) |
| `chromium` + `chromium-common` + `chromium-sandbox` | **149.0.7827.196**, `apt-mark hold` | navigateur headless piloté en CDP (150 = SIGTRAP) |
| `socat` | 1.7.4 | pont CDP `9222 → 172.17.0.1:9223` |
| `docker-ce` | 29.x | fournit l'interface `docker0` (172.17.0.1) que le pont socat bind |
| `nginx` | 1.22 | sert la page `/executor/` |
| `certbot` + `python3-certbot-nginx` | 2.1 | TLS (domaine sslip.io, renouvellement `certbot.timer`) |
| `ufw` | 0.36 | pare-feu (9223 restreint au réseau docker) |

**Paquet apt — optionnel (accélérateur) :**
- `python3-requests` (2.28) → **keep-alive HTTP** (~1,85×, ban-safe). Sans lui, fallback urllib
  identique. ⚠️ Debian 12 : installer via **apt**, PAS `pip` (bloqué par PEP 668 sur
  l'interpréteur système). `requirements.txt` documente la dépendance.

**Config & services (repo → système) — requis :**

| Élément | Emplacement | Source dans le repo |
|---|---|---|
| Policy UA-Switcher + extension forcée | `/etc/chromium/policies/managed/aks-ua-switcher.json` | `docs/ua-switcher-aks-staff.json` |
| Marqueur d'autorité (= hostname du box) | `/etc/aks-executor.target` | — (root, par machine) |
| Chromium headless CDP 9222 | `aks-chromium.service` | `ops/BROWSER_RUNBOOK.md §1.2` |
| Pont socat 9223 (REQUIS malgré le nom « hermes ») | `hermes-cdp-proxy.service` | `ops/BROWSER_RUNBOOK.md §1.3` |
| Page opérateur `/executor/` | `aks-admin.service` | `ops/aks-admin.service` |
| nginx vhost + basic-auth + TLS | `<IP>.sslip.io.conf`, `/etc/nginx/.htpasswd_executor` | `ops/nginx-executor.conf`, `ops/INSTALL_ADMIN.md` |

⚠️ Le vhost nginx **et le cert TLS sont liés à l'IP** (domaine sslip.io) → nouvelle IP = nouveau
vhost + nouveau certificat.

**Nouveau VPS `vmi3565249` (217.76.57.126, Debian 13 trixie) — reconstruit le 2026-09-09** selon
cette nomenclature, avec ces écarts vérifiés live : Python **3.13** + `python3-requests` 2.32
(apt) ; **Chromium 150.0.7871.100-1~deb13u1** (149 n'existe pas pour trixie ; le build trixie
tourne headless **sans SIGTRAP**, `apt-mark hold` posé ; l'unité force toujours l'UA
`Chrome/149.0.0.0`, donc l'invariant passe — bumper `REQUIRED_USER_AGENT` reste une décision
explicite de Romain, cf. RUNBOOK §1.1) ; `docker.io` 26 (paquet Debian, fournit `docker0`) ;
socat 1.8 ; nginx 1.26 ; certbot 4.0 ; console `https://217.76.57.126.sslip.io/executor/`
(mot de passe initial dans `/root/executor-admin.pass`, root-only — à faire tourner via
`ops/INSTALL_ADMIN.md §1`) ; gate `ok:true` + `authoritative:true` ; suite 1579 OK (2026-09-13 ; 1 846 tests au 2026-09-15).
`ufw` actif (OpenSSH, Nginx Full, 9223 restreint à `docker0` — posé par Romain, Claude n'a pas la
permission). Reste : le transfert des cookies WP (profil vierge). L'ancien VPS était
`vps-9ee9f9cf`.

**Hermes (superviseur conversationnel) — PAS requis par l'executor :** services
`hermes-gateway`, `hermes-web-ui` ; pip `litellm` / `openai` / `gunicorn`. Seul le pont CDP
(`hermes-cdp-proxy`) partage le préfixe de nom mais EST requis. Ne pas réinstaller si tu ne
veux que l'executor + sa page.

## 3. État courant (2026-09-15)

Tout est poussé sur `origin/main`, suite verte (**1 846 tests** découverts le 2026-09-15 —
modal v2, consoles par défaut, saisie par page console, fichiers marchands inclus). **En
cours le 15/09 : le premier sweep console RÉEL (MMOGA)** — lire son `recap.json` (créées,
`gated_*`, halte) avant tout marchand suivant ; la table « Capability status » du README
résume ce qui est disponible / expérimental / bloqué. Travaux
récents (voir
`docs/CHANGELOG.md` pour le détail) :
- **Consoles par défaut partout (15/09, décision Romain « 1 »)** : après les deux canaries du
  modal v2 et le dry-run consoles MMOGA (663 offres → 174 candidats consoles : 89 à une cible,
  59 à deux, 26 à trois ; 489 skips), `scripts/10` / `scripts/03` / le lanceur `/auto` / l'aperçu
  et la saisie by-urls prennent les consoles en compte **sans flag** ; **`--no-consoles`** (ou
  `"consoles": false` dans le corps JSON de la console, case « Consoles » décochée) = PC seul.
  `--consoles` reste accepté (no-op explicite) ; le mode est toujours écrit sur l'argv de
  `03_match` (`--consoles` / `--no-consoles`), dans `match_meta.json`, `recap.json` et
  `admin_submit.json` (`consoles`).
- **Saisie depuis une page console (15/09)** : `scripts/11` accepte les URLs de pages
  console (`buy-<slug>-<kind>-compare-prices/`), page épinglée + pages sœurs lues depuis sa
  barre d'onglets, qualification « une des cibles = la page demandée », candidat gardé
  entier ; `scripts/12` inchangé (candidats entiers → `05_submit --mode safe`). **Code livré,
  pas encore exercé en réel** (lecture live d'une page console à faire). EXECUTOR_RULES §14.
- **Documentation remise en cohérence (15/09, lot 1)** : EXECUTOR_RULES ne garde que les
  règles en vigueur (l'historique daté est dans CHANGELOG « Historique déplacé depuis
  EXECUTOR_RULES »), README porte la table d'état des capacités, les autres docs renvoient
  aux sections d'EXECUTOR_RULES au lieu de recopier les règles (§9).
- Campagne d'audit Fable : 38/39 findings corrigés (1 décliné, cf. §5).
- Correctifs matcher : `extract_aks_name` (noms marketing), R39 (mot plateforme = bruit
  d'édition), « Key » nu retiré par le slug, URL `compare-and-buy`.
- **R25 (skip doublon) RETIRÉ** — « pending = à ajouter » (cf. §5).
- **Pre-order = statut** (pas un produit différent) ; **symbole ™** retiré avant NFKC (bug
  Eneba « Company™ »).
- **Perf** : keep-alive HTTP + pacing 0,15s + cap `--max-pages 30` (safe-auto) → ~1,85× / ~4×
  sur feed profond, ban-safe. Un **fail-open critique** (keep-alive suivait un 3xx en mode
  no-redirect → gate au vert à tort) a été trouvé par vérif adversariale multi-agents et
  corrigé (`54f1f88`), puis durci (`9ddf185`).
- **Audit 2026-09-09** (38 findings confirmés / 7 réfutés), correctifs appliqués : garde
  host-lock strict (`_allkeyshop_host`), cap `--max-pages` = couverture (champ `coverage` du
  recap, plus une halte), throttling AKS = abort fail-closed (premier 429, ou 5 sondes non
  fiables consécutives sur des pages distinctes → `03_match` exit 2, stdout
  `reason: aks_throttled`, sidecar `match_aborted.json`, même règle dans le flow by-urls →
  `recap.aborted = aks_throttled`), `trust_env` off sur la Session keep-alive (proxies miroir
  urllib), tests réels des deux backends HTTP, matrice CI sans/avec `requests`, HANDOFF §7
  corrigé. Détail : `docs/CHANGELOG.md` (2026-09-09) et `docs/audit_2026-09-09_last-commits/`.
- **2026-09-10** (premier dry-run Kinguin sur le nouveau VPS) : **disjoncteur R30** (3 échecs
  consécutifs de la recherche AKS → plus d'appel pour le reste du run ; la recherche AKS répond
  en 22-28 s avec un corps vide depuis ce box) et **délai de grâce** avant `AksThrottled`
  (30 s puis une nouvelle tentative, jamais sur 429, 2 grâces/run). `match_meta.json` porte
  `search_failures` / `search_circuit_open_offers` / `throttle_graces`. Le disjoncteur est
  **persisté par sweep** (`<sweep>/search_circuit.json`, sans expiration — Romain 2026-09-10 :
  une fois ouvert il le reste jusqu'à la fin du sweep, les offres non résolues par URL
  attendent le sweep suivant). **Preuve post-save réessayée une fois** sur timeout de
  commande CDP (`CdpTimeoutError`, socket intact ; jamais sur socket mort) — la page admin
  AKS a mis > 45 s à répondre après un Create réussi, 2× sur ~100 créations, chaque fois
  une halte du sweep avec l'offre UNKNOWN (EXECUTOR_RULES §7). **Trois formes d'URL
  AKS** par slug deviné : courante (tous paliers) → avec année (`buy-fable-2026-…`, pages
  créées depuis 2026) → ancienne (`compare-and-buy-cd-key-for-digital-download-<slug>/`,
  ≈2021), les deux dernières pour le slug le plus spécifique seulement (+3 sondes max ; le
  ×5 initial a déclenché des 503). Une 2e tentative après 2 s sur un 5xx, jamais sur 429.
- **Jamais l'UA navigateur vers AKS en HTTP** (2026-09-11) : ~60 sondes ad hoc en UA Chrome
  ont fait bannir l'IP du VPS par l'anti-bot AKS (timeouts TCP pendant des heures, sweeps et
  console bloqués). `http_get` envoie `AKS/Staff` par défaut vers allkeyshop.com ; en `curl`,
  toujours `-A AKS/Staff`. Le pipeline l'a toujours fait ; la règle vaut pour les diagnostics.
  **Nuit multi-marchands : `python3 scripts/10_data_entry_auto.py --all-allowlisted`
  --max-pages 30 --continue-on-halt`** (2026-09-11, Romain : « tu continues jusqu'à demain
  matin » ; **consoles incluses par défaut depuis le 15/09** — aucun `--consoles` à ajouter,
  `--no-consoles` pour un sweep PC seul) — une halte fail-closed sur un marchand (offre
  UNKNOWN, feed illisible, 10 échecs)
  est consignée dans `recap.halted_merchants` et le marchand suivant est quand même balayé ;
  une session expirée (« not logged in ») arrête tout ; exit 2 s'il y a eu au moins une halte.
  Sans le flag, la première halte arrête le lot (comportement historique). Via la console :
  champ `continue_on_halt: true` dans le POST `/api/data-entry/auto`. Un marchand par VPS,
  jamais deux sur la même machine (un navigateur, un verrou).
  **Référence par marchand : `docs/MERCHANTS.md`** (2026-09-12 — identifiants, grammaire du
  feed, hooks de config, règles propres, statut safe-auto, résiduel) ; à tenir à jour à chaque
  nouveau marchand ou nouvelle règle marchand.
  **État du feed par marchand : `python3 scripts/14_feed_status.py --merchant MMOGA --store-id 12
  --out docs/feeds/MMOGA.md`** (Romain 2026-09-11 : « un document par marchand » — dernier
  passage, offres ajoutées, ce qui reste et pourquoi ; lecture seule sur `runs/`, à régénérer
  après chaque passage et à commiter).
  **Sonde officielle : `python3 scripts/13_aks_ping.py`** (staff UA, une requête, JSON ;
  `--wait 900 --max 16` = une sonde par quart d'heure jusqu'à réponse) — ne plus « pinger »
  AKS autrement.
- **DLC / Add-On / Season Pass saisis `[R43]`** (2026-09-11, GO Romain) : plus de pré-skip
  « DLC in title » ni de catégorie `SEASON PASS` — le titre est résolu marqueur retiré
  (`strip_dlc_marker`, les mots Season/Expansion Pass restent : ils sont le slug AKS) et la
  page trouvée **doit** porter l'édition DLC (16), sinon skip fail-closed « … carries no DLC
  edition (R43) » (page du jeu de base, stub, autre produit) ; édition saisie DLC(16) par R18 ;
  R01b `DLC`/`SEASON PASS` levés sur une page DLC, mots du marqueur ignorés par R16 ; les
  passes in-game (« Battle Pass ») restent skippés. Sondage 2026-09-11 : 9/12 DLC MMOGA ont
  leur page AKS propre avec le bucket DLC. EXECUTOR_RULES §4.3 `[R43]`. Dry-run : 215
  candidats sur le feed MMOGA restant. **`[R44]`** (trouvé par ce dry-run) : un mot de région
  faisant partie du nom du produit AKS (« … United States Civilization ») rend la région
  ambiguë → skip, sauf région déclarée par la grammaire du marchand (EXECUTOR_RULES §4.4).
  Revue adversariale → règle de la page propre (palier 1 seulement), DLC sans nom → skip,
  collections de DLC = bundles, passes in-game skippés ; **seconde grammaire de région MMOGA**
  « (Steam Key EU) » / « [EU] » (9 offres saisies GLOBAL le 2026-09-10 à corriger à la main) ;
  **R18 gardé tel quel sur décision Romain** malgré 3 jeux de base saisis DLC(16) (Stray
  Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake — pas à corriger) : « des fois,
  les titres n'ont pas de marqueur et sont des DLC » (AGENTS.md « Reviewed decisions »).
- **MMOGA** (2026-09-10) : nouveau marchand porté par `src/merchants/mmoga.py` via les
  **hooks de config marchand** `[R32e]` (`precheck` / `title_region` / `resolve_name` / `url_platform` `[R46]` —
  un fichier marchand peut ajouter ou surcharger le générique). Store id feed **12** (page
  AKS : 40) ; dans le sélecteur console ET dans l'allowlist safe-auto (décision Romain
  2026-09-10, sans run supervisé préalable). **`[R42]`** : chiffres romains II–XV ≡ chiffres
  (identité, slugs, recherche feed by-urls) — « Crusader Kings III » = page AKS « Crusader
  Kings 3 ».
- **Consoles `[R45]` — en production, ACTIVÉ PAR DÉFAUT depuis le 15/09** (préparé le
  2026-09-12, verrouillé jusqu'aux canaries du 15/09). Romain :
  l'outil AKS feed va overwriter la région (= région/plateforme) et l'édition PAR page cible
  (clé PS5 → pages PS5 + PS4 ; clé Xbox → Xbox One + Xbox Series X + PC seulement en Play
  Anywhere). Faits vérifiés : AKS a des **pages produit consoles séparées**
  `buy-<slug>-<kind>-compare-prices/` (kind `ps4` / `ps5` / `xbox-one` / `xbox-series` /
  `nintendo-switch` / `nintendo-switch-2` — le constat « pas de page console » du 11/09 venait
  d'une mauvaise grammaire d'URL), barre d'onglets = plateformes du jeu, Play Anywhere lisible
  dans `official platforms` de la page PC, buckets du modal par famille × base région
  (EXECUTOR_RULES §10 ; pas de Switch 2, pas de PS5 EU/US/UK). Code : `src/console_keys.py`
  (`classify_console`, titre ET URL — vocabulaire partagé ; la grammaire par marchand vient
  des hooks consoles de `src/merchants/<marchand>.py` depuis le 14/09, bullet suivant),
  `Candidate.targets` (`Target`,
  toujours ≥ 1 ; empreinte étendue au-delà d'une cible), `scripts/03_match.py --consoles` /
  `scripts/10 --consoles` (**défaut ON depuis le 15/09**, décision Romain « 1 » — le flag est un
  no-op explicite, **`--no-consoles`** = PC seul ; le `--dry-run` obligatoire du 14/09 est **levé
  le 15/09** sur GO de Romain après les deux canaries — écriture consoles autorisée, `05_submit`
  garde chaque entrée ; historique : flag OFF par défaut du 12/09 au 14/09, `--dry-run`
  obligatoire avec le flag le 14/09 ; avec `--no-consoles` : aucune SAISIE console, mais le scan
  console de l'URL reclasse les lignes consoles URL-seules en `console` — 569 lignes Gamivo par
  lot), submitter v2 : une cible = chemin PC, plusieurs cibles = lignes `offer[targets][]` du
  modal v2 (plafond 3, relectures, un seul clic — prouvé par les canaries du 15/09 ; historique :
  **> 1 cible = blocker `multi_target_unsupported_until_modal_verified`** tant que le modal
  n'avait pas été observé avec `--inspect`, jamais « la première cible seulement » — une saisie
  consomme la ligne du feed ; une entrée gated est un skip conçu (`gated_multi_target`), jamais
  un échec du StepGuard). **Revue adverse du 12/09 corrigée le
  14/09** (CHANGELOG « Consoles R45 : correctifs ») : région de la branche console lue dans le
  slot de chaque grammaire (`region_base` / `region_label` / `region_words`, jamais un GLOBAL
  implicite pour une clé verrouillée ; Gamivo via le hook R46), R44 sur le label de base,
  identité de page sans apostrophes, R19 stampé « (R19, R45) », RANDOM + mot console, gardes
  throttle partagés, ids `None` refusés. **P1 tranchée par Romain (14/09)** : « clé PS5 seule =
  page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch et Switch 2 » — jamais de
  page sœur (AGENTS.md). **Switch 2 saisissable** : famille `SWITCH2`, page
  `nintendo-switch-2` (SF6 188436, Elden Ring Tarnished 188441), buckets NINTENDO (99…).
  **Fuite corrigée** : le garde console ne
  lisait que le titre → un Xbox One/Series US Gamivo (« Riders Republic Premium Edition United
  States », run `20260911-162100-auto-gamivo-s51-p28`) est entré PUBLISHER GLOBAL Premium sur la
  page PC (AKS 50562) — à corriger à la main ; `console_marker_in_url` scanne l'URL dans tous
  les modes. Règle complète : EXECUTOR_RULES §4.12 ; contrats : DATA_CONTRACTS ; grammaire par
  marchand et volumes : MERCHANTS.md.
- **Un fichier de config par marchand — règle de Romain (répétée depuis le 2026-08-11,
  ultimatum du 2026-09-14)** : « pour la détection région / édition / plateforme, tu as un
  fichier de config par marchand. Et si tu ne l'as pas, tu dois l'avoir. » → **chaque
  marchand a son fichier ; la grammaire marchande ne vit jamais dans un module générique.**
  État : tout marchand de la liste blanche safe-auto a son `src/merchants/<marchand>.py`
  exposant un `MerchantConfig` (six fichiers créés le 14/09 : `kinguin.py`, `k4g.py`,
  `driffle.py`, `gameseal.py`, `allyouplay.py`, `cjs.py` — Allyouplay et CJS en
  déclaration seule, jamais balayés, aucun hook inventé) ; le contrat gagne quatre hooks
  consoles `[R45]` (`console_url_families`, `console_pc_declared`, `console_region_slot`,
  `console_noise`) et le classifieur `src/console_keys.py` ne garde que le vocabulaire
  partagé (les grammaires d'URL MMOGA / Gamivo / Eneba et les contrôles d'hôte en sortent) ;
  le registre nom → module est `src/merchants/registry.py`, importé par le matcher ET le
  classifieur sans import circulaire. Référence : `docs/MERCHANTS.md` (fichier, grammaire PC,
  grammaire console, hooks, statut par marchand), EXECUTOR_RULES §4.10 « Console hooks » et
  §4.12.3, CHANGELOG 2026-09-14. Mesure avant / après (14/09, lecture seule sur les lots du
  12/09) : classifieur consoles IDENTIQUE (2 990 lignes, 0 écart de comptage) ; lignes PC dont
  le précheck / la région / le slug changent vs le code committé : Kinguin 66, K4G 228, Driffle
  8, G2A 3, GameSeal 30, Gamivo / MMOGA / Eneba 0 ; 0 candidat touché ; 211 lignes consoles
  Kinguin passent de « console » à un motif explicite en mode par défaut (CANADA 84,
  AUSTRALIA 77, ACCOUNT 37…) — détail dans le CHANGELOG. **Quand tu ajoutes un marchand ou une règle marchande : le fichier
  marchand d'abord, jamais un `if merchant == …` ni une regex marchande dans `matcher.py` /
  `console_keys.py`.**

## 4. Backlog / prochaines étapes

- **Daemon H24** (data-entry auto multi-marchands, admin dispo en //) : **audité, mandat
  DIFFÉRÉ par Romain** — PAS de code daemon tant qu'il n'a pas ratifié par écrit le mandat GO
  permanent (un daemon H24 auto-submit = le « batch long auto-initié / fire-and-forget »
  interdit par CLAUDE.md). Quand on le construira : **Archi A** (systemd séparé, survit au
  restart admin) — préférence de Romain. Faits durs : 1 seul onglet Chrome + verrou machine-
  wide → pas de vrai // browser (seul le lock-free tourne en // : match/report, console) ;
  session WP TTL borne le H24 → park fail-closed + notif sur session morte, jamais d'auto-
  réparation. La synthèse tient dans ce paragraphe (il n'existe pas d'entrée CHANGELOG
  dédiée) ; à compléter ici si le mandat est ratifié.
- **Concurrence de résolution** : SEUL levier vitesse restant, gardé **en réserve** — c'est
  le seul qui augmente le débit de requêtes AKS (→ risque de re-ban OVH ; le ban historique
  était sous charge navigateur, pas débit de probes). À sortir seulement sur go de Romain,
  avec un rate-limiter et un rodage prudent.
- **Consoles `[R45]` — prochaines étapes** (dans l'ordre) :
  0. ~~Corriger les findings de la revue adverse du 12/09~~ — **FAIT le 14/09** (CHANGELOG
     « Consoles R45 : correctifs de la revue adverse ») : région de la branche console, comptes
     Difmark, R44, gate multi-cibles, identité, R19, RANDOM, throttle, validation ; P1 tranchée ;
     Switch 2 = famille SWITCH2. (Historique : le flag est resté OFF par défaut et **dry-run
     seulement** jusqu'au 15/09.)
  1. ~~**Observer le nouveau modal** de Romain en lecture seule~~ — **FAIT le 14/09**
     (`--inspect`, run `20260914-inspect-consoles` : lignes `offer[targets][i][target|region|
     edition]`, bouton `[data-add-target]`).
  2. ~~**Ajouter le remplissage par cible**~~ — **FAIT le 14/09 → 15/09** : submitter v2
     (plafond 3, relectures, un seul clic), canaries 1 cible (Legend of Mana Switch) et 2 cibles
     (Diablo 2 Resurrected One + Series) OK ; garde « `--consoles` exige `--dry-run` » levé.
  3. ~~**Dry-run consoles** pour mesurer~~ — **FAIT le 15/09** sur MMOGA (run
     `20260915-081607-dryrun-consoles` : 663 offres → **174 candidats consoles** — 89 à une
     cible, 59 à deux, 26 à trois — et 489 skips) ; sur ce chiffre Romain a tranché « 1 » :
     **consoles par défaut partout**, `--no-consoles` pour un sweep PC seul. Reste à mesurer
     Kinguin (`scripts/10 --targets "Kinguin:58" --dry-run`, consoles incluses ; 365 lignes
     consoles dans le dernier lot) ; lire `candidates.json` (`targets`) et `skipped.json`
     (motifs `console: … (R45)`).
  4. **Corriger Riders Republic à la main** sur AKS (produit 50562 : l'offre Gamivo Xbox
     One/Series US saisie PUBLISHER GLOBAL Premium le 2026-09-11).
  5. **Premier sweep console RÉEL (MMOGA, 15/09, en cours)** : lire le recap (créées,
     `gated_too_many_targets`, `gated_multi_target`, halte éventuelle), vérifier sur AKS
     quelques créations à 2-3 cibles (cache des pages AKS lent : plusieurs heures), puis
     seulement enchaîner Kinguin ; **exercer la saisie depuis une page console** (`scripts/11`
     sur une URL `…-ps5-compare-prices/`, aperçu seulement) avant le premier « Saisir » console.
- **Un fichier par marchand — suite (règle du 14/09)** : dry-run des nouveaux fichiers
  (`scripts/10 --targets "Kinguin:58" --dry-run` — consoles incluses par défaut depuis le
  15/09 —, puis K4G / Driffle) et lecture
  des `skipped.json` (motifs `console: … (R45)` inchangés attendus) ; Allyouplay / CJS-CDKeys /
  GameSeal en `--dry-run` PC d'abord (jamais balayés) pour relever leur grammaire et la
  déclarer dans leur fichier (`domain` déclaré, à confirmer). Les deux questions des fichiers
  marchands sont **tranchées le 14/09 (soir)** : Kinguin « (valid until <mois> <année>) » =
  note de validité, on entre (hook `guard_name`, 79 lignes / lot) ; K4G « Steam Altergift » =
  Steam Gift, on entre sous le bucket GIFT (hook `gift_delivery`, 216 / 592 ; gift US 2577 /
  UK 2572 mappés le 16/09, `[R50]` — la phrase « sans bucket → skip » était fausse). Reste ouverte : la queue « EU/UK » = skip.
- **Questions pour Romain (R45, à confirmer — EXECUTOR_RULES §12)** : ~~P1~~ **tranchée le
  14/09** (« clé PS5 seule = page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch
  et Switch 2 » — déclaration marchande ∧ page AKS, jamais de page sœur) ; ~~P2, P3, P5~~
  **tranchées le 25/09** (« P3 A, P5 A, P2 saisir sur les xbox déclarées et sur PC ») : P2 Xbox +
  PC sans Play Anywhere sur la page = Play Anywhere (pages Xbox + page PC, case XBOX/PC) ; P3 PS5
  hors GLOBAL = cases PlayStation 88eu / 88us / 88uk ; P5 DLC console = R43 sur chaque page cible ;
  ~~P4~~ **tranchée le même jour** : Xbox sans génération = « Xbox sur les deux » (One + Series,
  les pages qu'AKS a ; + PC = P2), PlayStation sans génération = refus ; ~~sémantique de l'overwrite par cible dans le nouveau modal~~ **tranchée par
  l'observation (14/09) et les canaries (15/09)** : UN Create avec N lignes cibles portant
  chacune sa région / édition (SUBMITTER_SPEC §4c) — reste à confirmer côté AKS la création
  sur la 2ᵉ page du canary 2 (Diablo 2 Resurrected, Xbox Series 70802) une fois le cache
  rafraîchi ; le bucket 88 « Playstation Game Code » est-il bien PS4 (le label ne dit jamais
  PS4).

## 5. Décisions revues — NE PAS re-durcir/re-défaire (un audit les re-signalera)

Ces décisions sont dans `AGENTS.md` § « Reviewed decisions ». Rappel :
- **R25 duplicate guard RETIRÉ** (2026-09-08) : une offre en pending est **à ajouter**, on ne
  teste plus « déjà sur AKS ». L'ancien garde matchait par nom et sur-bloquait sur un prix
  d'un autre canal / auto-sync (id marchand page ≠ store feed). La péremption est couverte par
  le pending feed stable + prove-gone. **Ne pas ré-ajouter.**
- **Software region catch-all** (`resolve_software_region`, finding Fable [7], DÉCLINÉ
  2026-09-07) : région GLOBAL/PUBLISHER unique de page → on classe l'offre dessus même si son
  label région semble US/EU-locké. Ne pas fail-close ça.

## 6. Gotchas opérationnels (non évidents, étaient en mémoire)

- **Succès submit = `prove-gone`** : l'offre a disparu du feed rafraîchi (même `available`
  mode que le run). **JAMAIS** `[data-success]` (faux positif prouvé — selectize silencieux).
  C'est LA règle du skill (`docs/EXECUTOR_RULES.md §7`). Ne jamais faire confiance au toast
  « ajoutée ». Deux formes admises de la preuve : le re-balayage complet du feed (manuel par
  marchand, `scripts/10 --prove-gone-scan`) ou la **recherche du feed filtrée par l'URL de
  l'offre** (by-urls depuis le 25/08 ; **défaut du sweep safe-auto depuis le GO de Romain du
  2026-09-10**, `05 --prove-gone-by-search`, ~2 s au lieu de ~100 s par offre).
- **Le feed re-import fait tourner TOUS les ids** ; identité stable = **chemin d'URL marchand**
  (`_url_key`), pas l'id. Le submitter épingle par l'URL. (Romain : « on garde les pending
  maintenant » → ids stables dans la fenêtre extract→submit, mais le code reste robuste à la
  rotation.)
- **Index submit peu profond** : productif seulement sur ~28-30 premières pages → défaut
  `--max-pages 30` (safe-auto). Feed profond = software/obscur qui 404 (matching le plus lent,
  ~0 candidat).
- **Deux clones sur le VPS** : le clone de dev `/root/aks-code/executor` (éditions + `git`
  commit / push via la clé de déploiement SSH) et le clone live `/home/debian/executor`
  (`git pull` seulement, celui que les services exécutent) — ne jamais `cd` dans le clone
  live avant une écriture relative ou une commande git.
- **Ancien VPS (`51.38.37.254`, vps-9ee9f9cf) tenu à jour** (Romain 2026-09-15) : à chaque
  déploiement du VPS courant, le clone `/home/debian/executor` de l'ancien VPS est aussi
  ramené au même commit (SSH `debian` + clé de déploiement, `git pull --ff-only origin main`,
  `sudo -n systemctl restart aks-admin`) et la suite de tests y est rejouée (Python 3.11).
  Sa session AKS reste expirée : transfert de cookies dans SA console avant tout run.
- **Un seul onglet Chrome + verrou `state/browser.lock`** (flock machine-wide, non-bloquant,
  fail-closed) : pas de vrai parallèle browser. Swap marchand ET data-entry se disputent ce
  verrou → séquentiel.
- **Games + Software (R31)** uniquement. **Jamais** de bundle / skin / soundtrack / lootbox /
  gift-card-as-product (règles catégorielles `precheck_skip`). DLC → édition DLC de la page si
  elle existe. Pre-order → statut (résout à l'édition réelle).
- **Learning mode = pas de LLM runtime** : annotations humaines déterministes → règle matcher
  build-time. Jamais de LLM à l'exécution.
- **`--max-pages` du sweep n'est PAS passé à `05_submit`** (il utilise `--page-hint` + son
  propre auto-défaut plein-feed) → le prove-gone couvre tout le feed même avec le cap.
  Cap atteint = **couverture, pas une halte** : `run_sweep` l'enregistre dans le champ
  `coverage` du recap du marchand (`incomplete_max_pages (feed has 60 pages)` ou
  `incomplete_feed_grew (2→4 pages)`), pas dans `halted` ; le `recap.json` du lot les liste
  dans `coverage_incomplete` (`"<marchand>: <coverage>"`) ; le lot passe au marchand suivant
  et le process sort en 0 (l'onglet `/auto` l'affiche « TERMINÉ — couverture partielle »,
  pas « ARRÊTÉ »). `--max-pages`/`--start-page` < 1 sont refusés (exit 2).

## 7. Commandes fréquentes

Toujours depuis `/home/debian/executor`. Les `--help` de chaque script font foi ; le
`manual_launch/run_executor.sh` enveloppe le flow par-marchand (prepare / check / dry-run /
submit — l'étape `check` écrit `approved.json`).

**Gate & santé (read-only, à faire souvent) :**
```sh
python3 scripts/01_check_invariants.py          # DOIT être ok:true ET authoritative:true (VPS) avant tout write
python3 -m unittest discover -s tests           # suite complète (~6 min, mono-process) ; -q pour le résumé
curl -s http://127.0.0.1:9222/json/version      # Chrome hôte (UA Chrome/149)
curl -s http://172.17.0.1:9223/json/version     # pont CDP officiel (celui qu'utilise le code)
cat state/browser.lock                           # qui tient l'onglet (label ; flock réel = kernel)
```

**Services (systemd) :**
```sh
systemctl status aks-chromium hermes-cdp-proxy aks-admin
sudo systemctl restart aks-chromium              # navigateur planté (récup : BROWSER_RUNBOOK §2.1)
# ⚠️ NE JAMAIS restart aks-admin pendant un submit en cours (tue l'enfant 05).
```

**Pipeline par-marchand (manuel) :** extract → match → validation (check) → submit.
```sh
python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127         # → runs/<id>/offers.json
python3 scripts/03_match.py runs/<id>/offers.json                            # → candidates.json, skipped.json, match_meta.json, report.txt
python3 scripts/04_validate.py template runs/<id>/candidates.json            # → validation.template.json (à remplir, puis copier en validation.json)
python3 scripts/04_validate.py check runs/<id>/candidates.json runs/<id>/validation.json   # vérifie validation.json → écrit approved.json (05 le re-vérifie contre candidates.json + validation.json voisins : un approved.json non vérifié / périmé est refusé)
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127            # DRY-RUN (défaut)
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit --prove-gone-by-search   # WRITE (safe: lot validé complet) — sur GO
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit --mode learning --prove-gone-by-search   # canary de 1 (WRITE) — sur GO
```

**`--prove-gone-by-search` sur toute saisie manuelle (2026-09-17).** Sans lui, la preuve
post-écriture est la MARCHE complète du feed après CHAQUE création (forme (a) d'EXECUTOR_RULES
« Two accepted forms of the refreshed-feed proof »), restée le défaut du chemin manuel alors que
le sweep de nuit utilise la recherche depuis le GO du 2026-09-10. Mesuré sur GameBoost le
2026-09-17 (feed de 12 pages / 1080 lignes) : ~85 s de re-marche par offre, soit **123 s par
offre et 6 h 45 pour 198** ; la même preuve par recherche filtrée tient en ~2 s. Les deux formes
prouvent une absence sur TOUT le feed et partagent les mêmes garde-fous fail-closed (une
recherche non rendue = `FeedScanError` → offre UNKNOWN, jamais un faux « gone »).
Pour revenir à la marche historique sur le chemin MANUEL, il suffit de retirer
`--prove-gone-by-search` : `05_submit` n'a pas de `--prove-gone-scan`, ce drapeau
appartient à `scripts/10_data_entry_auto.py` (il y désactive le défaut du sweep).
Erreur signalée par Romain le 2026-09-17 dans la 1re rédaction de cette note.

**Safe-auto sweep (multi-marchands, par page, highest-first) :**
```sh
python3 scripts/10_data_entry_auto.py --all-allowlisted --run-id <id> --dry-run                # SCAN DE NUIT, aperçu read-only : TOUTE la liste blanche (cible lue dans AUTO_MERCHANTS — voir README « Night sweep »)
python3 scripts/10_data_entry_auto.py --all-allowlisted --run-id <id> --max-pages 10 --continue-on-halt   # SCAN DE NUIT réel (WRITE) — sur GO
python3 scripts/10_data_entry_auto.py --targets "Kinguin:58,Eneba:19" --run-id <id> --dry-run   # APERÇU read-only (extract + match + plan, rien d'écrit)
python3 scripts/10_data_entry_auto.py --targets "Kinguin:58,Eneba:19" --run-id <id>             # WRITE auto-approuvé (safe, défaut --max-pages 30) — sur GO
python3 scripts/10_data_entry_auto.py --targets "Kinguin:58" --max-pages 30 --triage            # + plan Move-to-List des skips (WRITE) — sur GO
# Cap atteint = champ coverage du recap (pas une halte) ; le lot continue.
# Recap live : runs/<run-id>/recap.json (par page, incrémental).
```

**Consoles (R45 — PAR DÉFAUT depuis le 15/09, décision Romain « 1 ») :**
```sh
python3 scripts/03_match.py runs/<id>/offers.json                                  # match read-only, consoles INCLUSES : lignes consoles classées, candidats multi-cibles (targets)
python3 scripts/03_match.py runs/<id>/offers.json --no-consoles                    # match read-only PC seul : toute ligne console (titre OU URL) skippée « console »
python3 scripts/10_data_entry_auto.py --targets "MMOGA:12" --run-id <id> --dry-run # APERÇU d'un sweep, consoles incluses (rien d'écrit)
python3 scripts/10_data_entry_auto.py --targets "MMOGA:12" --run-id <id>           # WRITE consoles + PC (sur GO) ; --no-consoles = PC seul
# --consoles reste accepté (no-op explicite). Le mode est écrit sur l'argv de 03 (--consoles / --no-consoles),
# dans match_meta.json et recap.json (« consoles »), et dans admin_submit.json pour un run lancé par la console.
# Historique : flag OFF par défaut du 12/09 au 14/09 ; --dry-run obligatoire avec le flag le 14/09 (levé le 15/09 après les deux canaries).
```

**Saisie par liste d'URLs AKS (by-urls, onglet /games) :**
```sh
python3 scripts/11_data_entry_by_urls.py --run-id <id> --urls-file <fichier>   # APERÇU dry-run (résout + cherche le feed + plan) ; --urls "u1 u2" en alternative
# Le submit by-urls (12) part de l'aperçu, sur GO, via la console (« Saisir »).
```

**Move / tri de listes :**
```sh
python3 scripts/06_move.py runs/<id> --store-id 38                                            # dry-run (plan only)
python3 scripts/06_move.py runs/<id> --store-id 38 --execute --mode learning                  # canary de 1 (WRITE) — sur GO
python3 scripts/06_move.py runs/<id> --store-id 38 --execute --mode safe --i-authorize-batch  # plan confirmé complet (WRITE, exige le canary préalable — RV3) — sur GO
# Tri all-stores (Pending) : 08 planifie (read-only), 09 exécute UNE liste cible (même séquence learning → safe --i-authorize-batch).
python3 scripts/08_sort_plan.py --run-id <sort-id>                                            # read-only → runs/<sort-id>/sort_plan.json + report.txt
python3 scripts/09_sort_move.py runs/<sort-id> --list 8                                       # dry-run (liste 8) ; puis --execute --mode learning, puis --execute --mode safe --i-authorize-batch — sur GO
```

**Diagnostic d'un run en cours (read-only, ne pas toucher au browser) :**
```sh
pgrep -af "10_data_entry_auto|05_submit|03_match"    # qu'est-ce qui tourne
python3 -m json.tool runs/<run-id>/recap.json        # état / prove-gone par offre (created + "gone from feed")
```

**Git (à chaque changement) :** `git add -A && git commit && git push` (maj `/docs` + `README` d'abord).

## 8. Règles de travail (rappel)

- **Fail-closed** : dans le doute, STOP + rapport d'erreur. Pas de fallback browser/VPN/
  Playwright/Browserbase. Endpoint CDP officiel uniquement (`172.17.0.1:9223`).
- **Submit** : seulement sur go EXPLICITE de Romain ; **jamais fire-and-forget** (process
  supervisé). Le `success` de `record_result` vient de code déterministe, jamais d'une auto-
  évaluation du modèle.
- **Re-auth = transfert de cookies**, Romain-only, jamais auto-déclenché. `NotLoggedInError`
  d'une autre étape = STOP fail-closed.
- **À chaque changement** : mettre à jour `/docs` + `README` + **`git push`** (pas seulement
  commit local). Consigne répétée de Romain.
- **Un fichier de config par marchand** (Romain, 2026-09-14) : toute détection région /
  édition / plateforme propre à un marchand (PC comme console) se déclare dans
  `src/merchants/<marchand>.py` via les hooks de `MerchantConfig` ; `matcher.py` et
  `console_keys.py` ne portent que le vocabulaire partagé et le pipeline. Pas de fichier →
  on le crée, même en déclaration seule.
- **La mémoire de Claude vit HORS du repo** (`~/.claude/projects/.../memory/`) et **ne migre
  pas**. Ce document est le pont ; sur le nouveau serveur, Claude repart sans mémoire — d'où
  ce HANDOFF.

## 9. Cohérence documentaire (vérifiée le 2026-09-15 — lot 1)

**Ordre de lecture d'un nouvel arrivant** (un lecteur du README, des règles et du code doit
recevoir les MÊMES consignes) :

1. `README.md` — ce qui existe, la table « Capability status » (disponible / expérimental /
   bloqué, avec la condition et la règle), le lancement manuel ;
2. `docs/EXECUTOR_RULES.md` — les règles EN VIGUEUR par étage (le seul endroit où une règle
   est écrite ; les autres docs renvoient à ses sections `§N.M`) ;
3. `docs/MERCHANTS.md` — comment chaque marchand est lu (fichier, grammaire PC / console,
   hooks, statut safe-auto) ; puis `docs/feeds/<Marchand>.md` pour l'état du feed ;
4. ce `docs/HANDOFF.md` — état courant, décisions revues (§5 → `AGENTS.md`), gotchas,
   commandes, backlog ; puis `AGENTS.md` / `CLAUDE.md` (règles du builder),
   `docs/ARCHITECTURE.md`, `docs/SUBMITTER_SPEC.md`, `docs/DATA_CONTRACTS.md`.

**Vérifications faites le 2026-09-15** :

- EXECUTOR_RULES : l'historique daté (audits, « avant ce correctif … », comptages de lots,
  incidents) a été déplacé dans `docs/CHANGELOG.md` § « Historique déplacé depuis
  EXECUTOR_RULES (2026-09-15) », groupé par identifiant de règle avec sa date ; chaque règle
  garde un pointeur « historique : CHANGELOG <date> ». Preuve par script : l'ensemble des
  identifiants entre crochets (`[R…]`, `[P…]`, `[S…]`, `[MA…]`, `[FC…]`, `[CORE_RULES]`,
  `[DB proof override]`…) est **conservé** (147 identifiants distincts avant, 150 après —
  les 3 ajouts sont les références au modal v2 ; 0 perdu ; 245 occurrences avant et après),
  titres de sections (`## N.`, `### N.M`) et lignes de tableaux **inchangés**, aucun U+FEFF ;
  2 598 → 2 445 lignes.
- Commandes : chaque flag cité dans README / HANDOFF / MERCHANTS / CONTRIBUTING /
  ARCHITECTURE / SUBMITTER_SPEC a été vérifié contre l'`argparse` des scripts
  (`--consoles` / `--no-consoles` sur 03 / 10 / 11 / 12, `--dry-run`, `--continue-on-halt`,
  `--triage` / `--move-execute`, `--prove-gone-scan` / `--prove-gone-by-search`,
  `--max-pages` / `--start-page`, `--mode` / `--limit`, `--inspect` / `--catalog` /
  `--click-mode`, `--execute` / `--i-authorize-batch` / `--batch` / `--deferred` / `--full`,
  `--pages` / `--pace` / `--max-sweeps`, `--search-circuit-file`, `--wait` / `--max`,
  `--out`) et contre `manual_launch/run_executor.sh` (prepare / check / dry-run / submit ;
  `--pages`, `--pace`, `--mode`, `--limit`).
- Énoncés périmés corrigés : « `--consoles` exige `--dry-run` » et « défaut désactivé »
  (MERCHANTS), « le submitter refuse un candidat multi-cibles » (README, EXECUTOR_RULES §6),
  « open invariant (not yet enforceable) » du mode R24 (EXECUTOR_RULES §6 → FC5 appliqué),
  `AKS_TARGET=vps` (CONTRIBUTING — retiré depuis FC2), « once G3 lands » (CONTRIBUTING),
  `[data-add-target]` « UNVERIFIED » (SUBMITTER_SPEC → prouvé par le canary 2), tableau
  ARCHITECTURE sans les scripts 06-14, comptes de tests (1 846 le 2026-09-15).
- Suite de tests : `python3 -m unittest discover -s tests -t .` → 1 846 tests découverts
  le 2026-09-15.
