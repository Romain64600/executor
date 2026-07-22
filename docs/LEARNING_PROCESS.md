# Learning → comportement du pipeline : le processus builder-offline (officiel)

**Décision D2 (Romain 2026-07-22)** : l'Executor n'a **PAS** de moteur de règles
apprises dans le repo (pas de stockage de règles appliquées automatiquement à
runtime, pas de statut/rollback/priorité gérés par du code). La généralisation
des annotations Learning en comportement du pipeline passe par le **processus
builder-offline** décrit ici, et **rien d'autre**.

## Pourquoi (et pas un moteur runtime)

Un moteur qui stockerait des « règles apprises » et les appliquerait
automatiquement introduirait exactement ce que le projet interdit : une décision
non déterministe, difficile à expliquer, à tester et à révoquer proprement. Le
modèle du projet est *« you are a builder »* — **le builder EST le moteur**,
hors-ligne, sous revue humaine. Une annotation n'agit jamais seule : elle
devient soit du **code déterministe testé et committé**, soit une **saisie
manuelle**, soit un **move** (Stage 6). Jamais de LLM au runtime
([[learning-mode-no-runtime-llm]]).

`learning.json` est **l'autorité d'intention humaine** ; le **code** est
l'autorité d'exécution. Le pont entre les deux est humain (builder, assisté LLM),
traçable et révocable.

## Les entrées : `runs/<id>/learning.json`

Par offre non-matchée, l'opérateur annote depuis l'admin (panneau Learning) :

| champ | sens | consommé par |
|---|---|---|
| `target_list_id` / `target_list_label` | disposition « Move to list » | **Stage 6** (`06_move.py`) — outillé |
| `region_id` / `edition_id` / `platform` | correction pour saisie manuelle | **builder** (saisie assistée) |
| `aks_url` | la page produit AKS que le matcher a ratée | **builder** (saisie assistée) |
| `comment` | pourquoi le matcher a échoué / signal | **builder** (règle matcher) |
| `scope` | `exception_offre` / `regle_marchand` / `regle_globale` / `observation` | **builder** — porte la généralisation (D3) |
| `merchant_url` | URL marchande figée (identité stable) | writer + relocalisation |
| `suggested` | disposition Move non encore confirmée (D1-b) | filtrée par `move_plan` |
| `by` / `at` / `first_by` / `first_at` | traçabilité | audit |

## Les quatre sorties, selon la disposition

**1. `target_list` → Stage 6 (outillé).** Le seul chemin automatisé. `move_plan.py`
construit le plan des dispositions confirmées, `06_move.py` déplace (dry-run par
défaut, canary obligatoire au 1er move, go explicite). Rien à faire à la main.

**2. `region`/`edition`/`platform`/`aks_url` → saisie manuelle assistée
(builder).** Pour une offre **exacte** que le matcher n'a pas su router mais qui a
une page AKS : les annotations sont des **notes** pour le builder, qui construit
le candidat à la main (page AKS → `aks_product_id`, région/édition annotées) et le
soumet via Stage 5. **Ce chemin n'est délibérément pas outillé en automatique** —
c'est une saisie one-off, typiquement `scope = exception_offre`.

**3. `comment` + `scope` → règle matcher déterministe (builder).** **Uniquement**
si `scope ∈ {regle_marchand, regle_globale}` : le builder lit le pattern
récurrent et écrit une **règle matcher en code** — reproduite, **testée**,
**documentée**, ajoutée aux `LEARNED_RULES` du skill `aks-data-entry`, et
**committée** (donc **révocable par revert**). `scope = exception_offre` ou
`observation` → **PAS** de règle générale (une exception/observation n'est jamais
généralisée).

**4. Observation retenue → aucune action (encore).** Une annotation peut aussi
n'être qu'une **observation conservée** : elle documente un cas (commentaire,
`scope = observation`) mais ne déclenche **rien** — ni move, ni saisie, ni règle
— parce que la preuve est insuffisante ou la décision pas encore prise. C'est un
état **légitime et explicite**, pas un oubli : l'annotation reste dans
`learning.json` comme mémoire pour le builder, en attente de plus de preuves
concordantes (qui la feront basculer vers la sortie 1/2/3) ou d'une décision.

## Le cycle (checklist officielle)

1. **Extract → match** : le run produit `skipped.json` (non-matchées) + le rapport.
2. **Annotation** : l'opérateur annote dans l'admin (région/édition/plateforme/
   commentaire/page AKS/scope/move-to-list), enregistre → `learning.json`.
3. **Lecture** : le builder lit `learning.json` (panneau Learning ou fichier).
4. **Action par disposition** :
   - **Move** → Stage 6 : dry-run, puis canary de 1 (`--mode learning`), puis
     lot (`--mode safe`) — **sur go explicite** de Romain à chaque écriture.
   - **exception_offre + region/edition/aks_url** → saisie manuelle assistée
     (builder construit le candidat + Stage 5, go explicite).
   - **regle_marchand/regle_globale + comment** → **règle matcher** : reproduire
     le cas, coder la règle déterministe, **test unitaire**, **doc**
     (EXECUTOR_RULES / CHANGELOG), **LEARNED_RULE** numérotée, **commit** citant
     le run/offer d'origine.
5. **Validation** : re-run extract→match ; l'offre ne doit plus être dans
   `skipped.json` (la règle route correctement). L'annotation source peut alors
   être effacée (`cleared`) ou archivée.

## Garde-fous (invariants du processus)

- **Le `scope` est une portée maximale *proposée*, pas un contrat de validité.**
  Il exprime une **intention** (« je pense que ça se généralise à ce marchand /
  à tous »), jamais une preuve. `regle_marchand`/`regle_globale` *autorisent* le
  builder à **envisager** une généralisation — qu'il doit toujours **valider**
  (reproduire, tester sur des cas réels) avant de coder la règle et d'en fixer la
  portée effective, qui peut être **plus étroite** que proposée. `exception_offre`
  / `observation` / non renseigné → jamais de règle générale. Une exception ne
  devient jamais une règle générale par le seul choix du scope.
- **Force de preuve.** Une seule correction (`exception_offre`) reste locale.
  Plusieurs annotations concordantes justifient une règle marchand ; ne
  généraliser `regle_globale` (multi-marchands) qu'avec des preuves suffisantes.
- **Toute règle est explicable, testable, documentée, révocable** (revert). C'est
  le même modèle que [[skill-improvement-on-escape]] (« chaque escape → une
  LEARNED_RULE numérotée »).
- **Fail-closed.** Dans le doute sur la généralisation : ne pas coder de règle,
  laisser en observation / saisie manuelle.
- **Pas de moteur, donc pas de conflit/priorité/rollback à gérer par du code** :
  ces problèmes (règles contradictoires, désactivation, priorité historique vs
  apprise) n'existent pas ici — ils seraient l'objet d'un moteur, écarté par D2.
  L'ordre et la priorité des règles matcher restent ceux du **code** (revu,
  déterministe), pas d'un registre de règles.

## Si un jour on veut outiller davantage

Officialiser le processus builder-offline **ne ferme pas** l'évolution : on
pourrait plus tard outiller la *saisie manuelle assistée* (construire le candidat
depuis `aks_url`+region/edition automatiquement) ou proposer des *ébauches* de
règle depuis les commentaires. Mais toute évolution reste **build-time** et **sous
revue** — jamais une règle appliquée automatiquement au runtime. Ce serait une
décision explicite ultérieure, pas un glissement.

## Voir aussi

- `docs/EXECUTOR_RULES.md` §13 — les deux sens de « learning », capture-seulement.
- `docs/AKS_LISTS.md` — Stage 6 (Move-to-List) et la mécanique du move.
- `docs/AUDIT_LEARNING_2026-07-21.md` — d'où vient D2.
- Skill `aks-data-entry`, `references/rules/LEARNED_RULES.md` — les règles issues
  du processus.
