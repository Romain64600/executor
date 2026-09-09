# RESUME — reprendre cette revue SANS repartir de zéro

Contexte : revue adversariale **en lecture seule** (« regarde mes 3 derniers commits, ne code
pas », Romain, 2026-09-08) des commits `184b2b8 → e7586f6` (HEAD). Deux runs de workflow ont
été coupés par la limite de session de l'abonnement (2026-09-08 17:53 et 2026-09-09 ~10:15).
Depuis, **tout l'état est sauvegardé ici, incrémentalement** — ne relance JAMAIS la revue
complète.

> **État final (2026-09-09, 17h) : revue TERMINÉE** (45 findings, 38 confirmés / 7 réfutés,
> critique de complétude rendu), **correctifs appliqués et re-vérifiés** (voir
> `docs/CHANGELOG.md` 2026-09-09 et `BILAN.md` §7). Il ne reste rien à reprendre ; ce dossier
> est conservé comme trace (`BILAN.md`, `REVIEW.md`, `RESUME.md` sont suivis par git ; l'outillage
> `state.json` / `*.js` / `build_progress.py` / `inputs/` est ignoré via `.gitignore`).

## Ce que contient ce dossier (non commité, gitignore-le ou commite-le sur décision de Romain)

| Fichier | Rôle |
|---|---|
| `REVIEW.md` | le bilan lisible, régénéré à chaque passage (findings gardés / indécis / réfutés / vérifiés corrects) |
| `state.json` | **source de vérité** : chaque finding avec ses 3 lentilles (`done` + verdict, `failed`, `started`, `missing`) et son statut agrégé |
| `continue_from_state.js` | script Workflow **prêt à lancer** qui ne fait QUE le travail manquant (lentilles absentes + critique) |
| `build_progress.py` | l'agrégateur : relit tous les journaux de workflow de toutes les sessions et régénère les 3 fichiers ci-dessus |
| `loop_build.sh` / `build.log` | boucle de régénération (60 s) lancée pendant le run ; se termine seule |
| `inputs/` | findings bruts du 2026-09-08 (parity/ops), findings HANDOFF §7 du spot-check, diffs, script original du workflow |

## Procédure de reprise (nouvelle session Claude, même machine)

1. `cd /root/aks-code/executor && python3 docs/audit_2026-09-09_last-commits/build_progress.py`
   → affiche `kept=… refuted=… undecided=…` et l'état du critique. Lis `REVIEW.md` §0.
2. S'il reste des indécis avec lentilles manquantes ou si le critique est « à relancer » :
   `Workflow({ scriptPath: "/root/aks-code/executor/docs/audit_2026-09-09_last-commits/continue_from_state.js" })`
   (ultracode / Workflow tool). Le script embarque les findings en attente et leurs lentilles
   manquantes ; il n'exécute rien d'autre. Ses verdicts sont écrits dans le journal de SA session,
   que `build_progress.py` relit (il scanne `~/.claude/projects/-root-aks-code-executor/*/subagents/workflows/wf_*`).
3. Relance `build_progress.py` (ou `loop_build.sh` en arrière-plan pendant le run) → `REVIEW.md` à jour.
4. Si tout est décidé et le critique fait : rédige le bilan final à Romain **depuis `REVIEW.md`**
   (français, classé par sévérité, réfutés et « vérifiés corrects » explicités). Pas de correctif
   sans son go — le mandat est « ne code pas ».

Si la même session est encore vivante, `Workflow({scriptPath: <script>, resumeFromRunId: "wf_29e81141-a6f"})`
rejoue le cache ; entre sessions, seul `continue_from_state.js` fonctionne.

## Règles de vote (identiques au workflow)

3 vérificateurs indépendants par finding — `reproduce` (reproduire le scénario / relire le doc
visé), `reread` (relecture indépendante du code à HEAD + comparaison pré-commit), `materiality`
(est-ce que ça compte ici : OPEN/CLOSED/NEUTRAL, atteignable en prod, pas une décision revue
d'AGENTS.md). Chacun est instruit de réfuter par défaut. **Gardé** = ≥2 non-réfutants ;
**réfuté** = ≥2 réfutants ; sinon **indécis**. Sévérité finale = médiane des sévérités corrigées
des lentilles non réfutantes.

## Garde-fous

- Lecture seule sur le repo : aucun `git` d'écriture, aucun fichier suivi modifié.
- Aucune requête vers allkeyshop.com ni hôte externe : expériences sur `127.0.0.1` uniquement
  (le staff User-Agent ne doit jamais sortir de la machine).
- Ne pas re-signaler les « Reviewed decisions » d'AGENTS.md (R25 retiré, software region catch-all).
