# HANDOFF — reprise du projet sur un nouveau serveur

Ce document est le **point d'entrée de reprise** (migration serveur / nouvelle session
Claude). Il capture l'ÉTAT, les DÉCISIONS et les GOTCHAS qui, jusqu'ici, vivaient dans la
mémoire hors-repo de Claude et **ne voyagent donc PAS avec un `git clone`**. Lis-le en
premier, puis `AGENTS.md` + `CLAUDE.md` (les règles), puis `docs/EXECUTOR_RULES.md` (les
règles par étage). Dernière mise à jour : **2026-09-09** (voir `git log` pour le commit courant).

> ⚠️ Aucun secret ici (cookies WP, mots de passe, codes 2FA n'entrent jamais dans le repo).

---

## 1. Ce qu'est le projet (résumé)

Pipeline **déterministe et fail-closed** de saisie de données pour les feeds marchands
d'AllKeyShop (AKS). Étapes : `02 extract` (scan feed via CDP) → `03 match` (résolution AKS
read-only + règles R01…R40, écrit `candidates.json` / `skipped.json` / `match_meta.json` /
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
`ops/INSTALL_ADMIN.md §1`) ; gate `ok:true` + `authoritative:true` ; suite 1353 OK en `debian`.
`ufw` actif (OpenSSH, Nginx Full, 9223 restreint à `docker0` — posé par Romain, Claude n'a pas la
permission). Reste : le transfert des cookies WP (profil vierge). L'ancien VPS était
`vps-9ee9f9cf`.

**Hermes (superviseur conversationnel) — PAS requis par l'executor :** services
`hermes-gateway`, `hermes-web-ui` ; pip `litellm` / `openai` / `gunicorn`. Seul le pont CDP
(`hermes-cdp-proxy`) partage le préfixe de nom mais EST requis. Ne pas réinstaller si tu ne
veux que l'executor + sa page.

## 3. État courant (2026-09-09)

Tout est poussé sur `origin/main`, suite verte (**1353 tests**). Travaux récents (voir
`docs/CHANGELOG.md` pour le détail) :
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
  **R18 expose 3 jeux de base saisis DLC(16)** (Stray Blade, Aliens Dark Descent, Dragon
  Quest III HD-2D Remake) — décision Romain en attente (EXECUTOR_RULES §4.3 fin de `[R43]`).
- **MMOGA** (2026-09-10) : nouveau marchand porté par `src/merchants/mmoga.py` via les
  **hooks de config marchand** `[R32e]` (`precheck` / `title_region` / `resolve_name` —
  un fichier marchand peut ajouter ou surcharger le générique). Store id feed **12** (page
  AKS : 40) ; dans le sélecteur console ET dans l'allowlist safe-auto (décision Romain
  2026-09-10, sans run supervisé préalable). **`[R42]`** : chiffres romains II–XV ≡ chiffres
  (identité, slugs, recherche feed by-urls) — « Crusader Kings III » = page AKS « Crusader
  Kings 3 ».

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
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit   # WRITE (safe: lot validé complet) — sur GO
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit --mode learning   # canary de 1 (WRITE) — sur GO
```

**Safe-auto sweep (multi-marchands, par page, highest-first) :**
```sh
python3 scripts/10_data_entry_auto.py --targets "Kinguin:58,Eneba:19" --run-id <id> --dry-run   # APERÇU read-only (extract + match + plan, rien d'écrit)
python3 scripts/10_data_entry_auto.py --targets "Kinguin:58,Eneba:19" --run-id <id>             # WRITE auto-approuvé (safe, défaut --max-pages 30) — sur GO
python3 scripts/10_data_entry_auto.py --targets "Kinguin:58" --max-pages 30 --triage            # + plan Move-to-List des skips (WRITE) — sur GO
# Cap atteint = champ coverage du recap (pas une halte) ; le lot continue.
# Recap live : runs/<run-id>/recap.json (par page, incrémental).
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
- **La mémoire de Claude vit HORS du repo** (`~/.claude/projects/.../memory/`) et **ne migre
  pas**. Ce document est le pont ; sur le nouveau serveur, Claude repart sans mémoire — d'où
  ce HANDOFF.
