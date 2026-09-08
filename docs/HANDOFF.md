# HANDOFF — reprise du projet sur un nouveau serveur

Ce document est le **point d'entrée de reprise** (migration serveur / nouvelle session
Claude). Il capture l'ÉTAT, les DÉCISIONS et les GOTCHAS qui, jusqu'ici, vivaient dans la
mémoire hors-repo de Claude et **ne voyagent donc PAS avec un `git clone`**. Lis-le en
premier, puis `AGENTS.md` + `CLAUDE.md` (les règles), puis `docs/EXECUTOR_RULES.md` (les
règles par étage). Dernière mise à jour : **2026-09-08**, commit `9ddf185`.

> ⚠️ Aucun secret ici (cookies WP, mots de passe, codes 2FA n'entrent jamais dans le repo).

---

## 1. Ce qu'est le projet (résumé)

Pipeline **déterministe et fail-closed** de saisie de données pour les feeds marchands
d'AllKeyShop (AKS). Étapes : `02 extract` (scan feed via CDP) → `03 match` (résolution AKS
read-only + règles R01…R40) → `04 report` → validation → `05 submit` (écriture via la modale
UI officielle) → prove-gone. Claude est **builder** (code/tests/docs/diagnostics read-only),
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
- **Deps** : `pip install -r requirements.txt` (optionnel — `requests` pour le keep-alive ;
  fallback urllib sinon). Le cœur reste stdlib-only.
- **Gate avant tout write** : `python3 scripts/01_check_invariants.py` doit rendre `ok:true`
  ET `authoritative:true` **sur le VPS**. Un rouge en local/sandbox (`authoritative:false`)
  est normal et ne débloque rien.
- **Session** = cookies WP collés par Romain via la console (login social only ; jamais
  auto-déclenché ; `docs/LOGIN_SPEC.md`). Profil vierge au démarrage.
- **Chromium gelé à 149** (150 SIGTRAP). Ne pas upgrader.

## 3. État courant (2026-09-08, `9ddf185`)

Tout est poussé sur `origin/main`, suite verte (**1322 tests**). Travaux récents (voir
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

## 4. Backlog / prochaines étapes

- **Daemon H24** (data-entry auto multi-marchands, admin dispo en //) : **audité, mandat
  DIFFÉRÉ par Romain** — PAS de code daemon tant qu'il n'a pas ratifié par écrit le mandat GO
  permanent (un daemon H24 auto-submit = le « batch long auto-initié / fire-and-forget »
  interdit par CLAUDE.md). Quand on le construira : **Archi A** (systemd séparé, survit au
  restart admin) — préférence de Romain. Faits durs : 1 seul onglet Chrome + verrou machine-
  wide → pas de vrai // browser (seul le lock-free tourne en // : match/report, console) ;
  session WP TTL borne le H24 → park fail-closed + notif sur session morte, jamais d'auto-
  réparation. Synthèse complète : voir le CHANGELOG / l'historique de session.
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
  « ajoutée ».
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

## 7. Règles de travail (rappel)

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
