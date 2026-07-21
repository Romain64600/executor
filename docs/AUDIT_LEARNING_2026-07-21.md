# Audit Learning — 2026-07-21

Audit critique de la fonctionnalité **Learning** (annotations humaines des offres
non-matchées, admin) demandé par Romain. Méthode : 6 critiques indépendants par
dimension (correctness, faux-apprentissage, régression, tests, traçabilité,
sécurité) + vérification adversariale (2 réfutateurs/finding) + vérifications
manuelles ligne-à-ligne. 51 findings bruts → consolidés ci-dessous ; 3 réfutés.

Registre vivant (pattern AUDIT_2026-07-17) : chaque fix passe OPEN → FIXED avec
le commit en journal.

## Périmètre audité

`src/admin/learning_io.py`, `src/aks_lists.py`, routes `/learning` de
`src/admin/app.py`, `src/admin/runs.py`, section learning de
`src/admin/static/app.js` + `index.html` + `style.css`, tests associés,
`docs/AKS_LISTS.md` (commits b7e930d → 17868c2).

## Fait structurant (assumé, pas un bug)

**Le « moteur de règles apprises » n'existe pas.** `learning.json` n'est consommé
par aucun code pipeline : le flux réel s'arrête à *capture → stockage*. La
généralisation en règles matcher est un processus builder-offline (humain + LLM
propose, code déterministe ensuite), conforme à « learning-mode-no-runtime-llm ».
Les étapes *analyse → proposition de règle → validation → application → rollback*
sont des décisions d'architecture À PRENDRE (voir « Décisions métier »), pas des
régressions.

---

## P0 — critique

### L1. Annotations en cours de saisie détruites par l'auto-refresh — FIXED (2026-07-21, commit 7524f93)
- **Où** : `app.js` (`DIRTY` posé uniquement par la table Validation, l.1032-1033 ;
  `idleTick` recharge silencieusement au changement d'empreinte, l.966-971 ;
  `detailStamp` inclut les mtimes de tous les fichiers du run, dont `learning.json`).
- **Scénario** : l'opérateur enregistre une partie de ses annotations, continue de
  taper → sa propre sauvegarde change l'empreinte → ≤10 s plus tard `openRun`
  silencieux → tout ce qui a été tapé depuis est effacé sans trace.
- **Fix** : marquer `DIRTY` sur toute édition dans `#learning-groups` + rafraîchir
  l'empreinte (`CURRENT.stamp`/`detail`) après un save Learning réussi.
- **Statut** : FIXED (commit 7524f93) — DIRTY sur #learning-groups + re-stamp après save

### L2. Save = remplacement intégral : pertes silencieuses croisées — FIXED (2026-07-21, commit 7524f93)
- **Où** : `learning_io.py:133-161` (`stored` reconstruit du POST, pas de merge),
  `app.py:407-411` (pas de lock, pas de précondition — contrairement à
  `_post_validation` : lock + pattern sha AS1).
- **Scénarios prouvés** : (a) deux onglets/opérateurs (réalité documentée du
  projet) : le save de B efface les annotations que A vient de faire ; (b) un
  re-match régénère `skipped.json` → les offres devenues matchées sortent des
  groupes → le save suivant supprime leurs annotations (région/édition pour
  saisie manuelle, dispositions Move-to-list non exécutées) sans avertissement.
- **Fix** : merge côté serveur (les offer_ids absents du POST sont conservés),
  suppression uniquement sur signal explicite `cleared`, précondition
  `learning_sha256` (409 en conflit, pattern AS1), lock.
- **Statut** : FIXED (commit 7524f93) — merge + cleared + base_sha/409 + verrou

## P1 — important

### L3. `learnSelect` efface une région/édition sauvegardée dont l'id a dérivé — FIXED (2026-07-21, commit 7524f93)
- **Où** : `app.js:452-462`. Si `ann.region_id` n'est plus dans le catalogue de
  session courant (ids qui driftent — fait documenté) ou si le catalogue est
  absent, aucune option n'est `selected` → le save suivant écrit `''` et efface
  l'annotation. La fonction `select()` du panneau Validation a exactement le
  garde manquant (option fantôme préfixée, l.397-404).
- **Fix** : répliquer le garde (option `{value: currentId, text: region_text}`
  quand l'id sauvegardé n'est pas dans les options). **Vérifié V2.**
- **Statut** : FIXED (commit 7524f93) — option fantôme + grandfather serveur

### L4. La suggestion Move-to-list pré-sélectionnée devient une décision humaine au 1er save — OPEN (attente décision D1)
- **Où** : `app.js:506-509` (préselection `suggested_list_id`) + `531-534` (toute
  row avec `target_list_id` non vide est envoyée) + `learning_io.py` (stampée
  `by/at`, indistinguable d'un choix explicite).
- **Risque** : un seul « Enregistrer » (p.ex. pour un commentaire) persiste la
  disposition suggérée de TOUTES les offres à suggestion comme décision
  opérateur — le futur mover les traiterait comme un go humain. Viole « le
  défaut ne doit pas devenir la décision ». **Vérifié V2 (2 critiques).**
- **Décision Romain requise** : (a) suggestion en hint seul (pas de préselection),
  ou (b) préselection conservée mais flag `suggested: true` tant que non
  manipulée, le mover ne consommant que les dispositions confirmées.
- **Statut** : OPEN

### L5. Aucune validation serveur des champs — FIXED (2026-07-21, commit 7524f93)
- **Où** : `learning_io.py:142-147`. `target_list_id='delete'`, `'999'`, couple
  id/label incohérent, `region_id` hors catalogue de session, `aks_url`
  arbitraire (`javascript:`…) sont stockés tels quels. La docstring promet des
  « real ids from the live session catalog » ; seule l'UI contraint — pas la
  frontière serveur (fail-open, contraire au projet). **Vérifié V2.**
- **Fix** : `target_list_id ∈ LISTS` + label cohérent (`label_for`),
  region/edition ∈ catalogue de session quand `catalog.json` présent, `aks_url`
  au format page produit AKS (`https://www.allkeyshop.com/blog/…`), limites de
  taille par champ. Refus `LearningError` sinon.
- **Statut** : FIXED (commit 7524f93) — bad_list/bad_list_label/bad_region/bad_edition/bad_url/too_long

### L6. Aucun log JSONL du save Learning — FIXED (2026-07-21, commit 7524f93)
- **Où** : `_post_learning` (`app.py:407-411`) n'écrit aucun événement.
  L'architecture requise (AGENTS.md, « JSONL logs for every action ») et la
  pratique du projet (submit/match loggés) ne sont pas suivies ; combiné à
  L2, un écrasement était irrécupérable (aucune trace de l'état précédent).
- **Fix** : événement JSONL par save (run, by, at, n avant/après, offer_ids
  touchés, sha avant/après) dans le log du run.
- **Statut** : FIXED (commit 7524f93) — learning_log.jsonl append-only

### L7. Collision de nommage « learning » (mode submit R24) vs « Learning » (annotations) — FIXED docs (2026-07-21, commit 7524f93) ; renommage UI = D5 OUVERTE
- **Où** : `--mode learning` = mode d'ÉCRITURE canary de 1 (05_submit, R24) ;
  « Learning » = la vue d'annotations. Le CHANGELOG et EXECUTOR_RULES ne
  définissent que le premier ; la fonctionnalité auditée n'est documentée nulle
  part dans le repo (aucune entrée CHANGELOG, EXECUTOR_RULES muet). Risque de
  confusion opérateur/agent réel (l'UI radio « apprentissage — canary de 1 »
  coexiste avec le panneau « Learning »).
- **Fix** : documenter la fonctionnalité (CHANGELOG + EXECUTOR_RULES §Learning),
  distinguer explicitement les deux sens, envisager un renommage UI
  (« Annotations » ?) — décision Romain pour le renommage.
- **Statut** : FIXED docs (commit 7524f93) ; renommage UI = D5 OUVERTE

## P2 — améliorations

### L8. `suggest_target_list` matche par sous-chaîne sur la raison entière — FIXED (2026-07-21, commit 7524f93)
`aks_lists.py:88-99` : `"account" in r` avant le préfixe `forbidden region` ;
une raison contenant « steam-account » (page account) suggérerait la liste 30 à
tort. **V2.** Fix : ancrer sur la catégorie (`skip category: X` exacte,
préfixes délimités), pas la sous-chaîne libre.

### L9. Run jamais matché : message faux — FIXED (2026-07-21, commit 7524f93)
`app.js:436` : sans `skipped.json`, la vue dit « Aucune offre non-matchée pour ce
run » (faux : le run n'est pas matché). **V2.** Fix : distinguer « pas encore
matché » (via stages) de « 0 skips ».

### L10. offer_id dupliqué/vide, entrée non-dict dans skipped.json — FIXED (2026-07-21, commit 7524f93)
`learning_io.py` : offer_id dupliqué → dernière row gagne en silence ; offer_id
vide whitelisté si présent dans skipped.json ; entrée non-dict → 500 au save.
**V2.** Fix : ignorer les entrées malformées/ids vides à la constitution de
`valid_ids`, dernier-gagne documenté + testé.

### L11. Divers (groupés) — FIXED (2026-07-21, commit 7524f93) (sauf ids de listes build-time : mitigé + documenté, probe optionnel non planifié)
- `openRun` : une erreur ≠ `no_candidates` de `loadValidation` saute
  `loadLearning` (panneau vide sans explication). Fix : charger le Learning
  même en cas d'échec de la validation + hint d'erreur.
- Bannière stale : ne mentionne pas les annotations Learning dans son message.
  Fix : élargir le texte.
- `by` libre prime sur l'identité basic-auth ; `by`/`at` re-tamponnés à chaque
  save (perte de l'auteur initial). Fix : basic-auth d'abord, `at` initial
  conservé au merge.
- Ids de listes figés au build (`aks_lists.py`) : suggestion stockée fausse si
  drift avant le writer — mitigé : le writer re-résoudra par LABEL live
  (documenté), le label est stocké avec l'id.
- Tests manquants purement techniques : échelle réelle (100 offres/page),
  CSRF dédié à `POST /learning` (403 sans en-tête), Unicode de bout en bout
  (`ensure_ascii=False` via HTTP), sémantique de remplacement/merge.

## Réfutés (ne pas « corriger »)

- `_category` fusionne les `skip category: X` en un groupe : volontaire
  (groupement), la raison complète reste par offre.
- `year_in_name` sur les années de titre (2077…) : hint explicitement faible,
  jamais un défaut, documenté.
- `learning.json` non auto-porteur (offer_id sans name/url) : les ids sont
  stables AU SEIN d'un run (le drift est inter-imports) et `skipped.json` du
  même run porte name/url — la jointure est déterministe. Amélioration
  possible (dénormaliser name/url) mais pas un défaut.
- `_write_json_atomic` sans fsync : pattern uniforme du projet
  (validation_io, submit_manager) — pas un défaut propre au Learning.

## Cartographie des 18 cas de test demandés

| # | Cas | État |
|---|-----|------|
| 1 | Correction exacte une-offre | Capture couverte (round-trip testé) ; pas de marqueur « exception vs généralisable » → décision D3 |
| 2 | Règle mono-marchand | N/A moteur absent ; le marchand est implicite via le run |
| 3 | Règle multi-marchands | N/A moteur absent |
| 4 | Offre → blacklist | Capture couverte (listes 8/14/26/31/37) ; test dédié à ajouter |
| 5 | Offre → page for creation | Capture couverte (liste 22) ; test dédié à ajouter |
| 6 | Offre → South America | Capture + suggestion auto testées (36) |
| 7 | Correction région | Capture + test |
| 8 | Correction plateforme | **NON COUVERT — aucun champ plateforme** → décision D4 |
| 9 | Correction édition | Capture + test |
| 10 | Règles contradictoires | N/A moteur absent |
| 11 | Règle trop générale | Partiel : ambigus → garder testé ; L8 corrige le substring |
| 12 | Règle dupliquée | N/A moteur ; dédup catalogue listes testée |
| 13 | Règle désactivée/rollback | N/A moteur ; L2/L6 donnent trace + récupérabilité |
| 14 | Donnée incomplète | Partiel : bad_offer/bad_body/empty testés ; L10 complète |
| 15 | Confiance insuffisante → revue | Par design : défaut = garder (= revue humaine) ; pas de champ confiance → D3 |
| 16 | Conflit règle historique vs apprise | N/A moteur ; priorité de fait aux règles historiques |
| 17 | Correction isolée sans preuve | Processus builder-offline, non outillé dans le repo → D3 |
| 18 | Corrections concordantes → généralisation | Idem D3 |

## Décisions métier requises (Romain)

- **D1 (= L4)** : suggestion Move-to-list — (a) hint seul (pas de préselection),
  ou (b) préselection conservée + flag `suggested: true` tant que non manipulée,
  le futur mover ne consommant que les dispositions confirmées ? → OUVERTE
- **D2** : construire le moteur de règles apprises dans le repo (schéma règle :
  id, scope, conditions, action, source humaine, confiance, statut
  proposé/validé/actif/désactivé, date, exemples, rollback — comme spécifié),
  ou entériner le processus builder-offline actuel en le documentant comme
  officiel ? Les cas 2,3,10,12,13,16,17,18 en dépendent. → OUVERTE
- **D3** : ajouter à l'annotation un champ **scope** explicite
  (`exception_offre | regle_marchand | regle_globale | observation`) pour que la
  généralisation ne repose plus sur l'interprétation d'un commentaire libre ? → OUVERTE
- **D4** : ajouter un champ **plateforme** à l'annotation (cas 8) ? → OUVERTE
- **D5** : renommage UI de « Learning » (collision avec `--mode learning` R24) ? → OUVERTE

## Journal

- 2026-07-21 : audit initial (6 critiques + vérification adversariale,
  interrompue par la limite de session — 10 findings V2, le reste vérifié
  manuellement ligne-à-ligne). Registre créé, tout OPEN.
- 2026-07-21 : L1, L2, L3, L5, L6, L8, L9, L10, L11 FIXED + L7 (volet docs :
  CHANGELOG, EXECUTOR_RULES §13) — commit `7524f93`, suite 696 verts.
  Restent OUVERTS : L4 (bloqué par D1) et les décisions D1-D5.
