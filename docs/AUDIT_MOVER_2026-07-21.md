# Audit du writer Move-to-List (Stage 6) — 2026-07-21

Review adversariale du writer Move-to-List (commit `3465cb6`) AVANT tout move
réel : 5 dimensions en parallèle (fausse-preuve-de-succès, fail-closed, builder
de plan, CLI/gates, régression) + réfutation adversariale (2 réfutateurs/finding).
22 findings vérifiés → consolidés ci-dessous (~14 réels après dédup), 8 réfutés.

Registre vivant (pattern AUDIT_2026-07-17) : OPEN → FIXED + commit en journal.

## P1 — à corriger AVANT tout canary

### MV1. Move de la MAUVAISE offre si un re-import ré-ide la row (garde SC5 manquant) — FIXED (commit 9b479d0)
`mover.py` `_move` agit sur `current_offer_id`/`page_url` capturés par `_locate_row`
au DÉBUT du run, puis sur la page fraîche ne vérifie QUE `bulk_row_present`
(existence id + form) avant de cocher/Apply. Il ne re-lit jamais name/URL sur le
DOM frais. Le submitter corrige exactement ce danger (`_prepare`, SC5,
`submitter.py:531-556` : re-lit `page_offer_rows`, re-`_row_check`). Les
re-imports rotent TOUS les ids ([[feed-reimport-id-rotation]]) ; entre l'index de
départ et un move par-offre (minutes plus tard, ou tout le lot en `--mode safe`),
un re-import peut réassigner l'id du plan à un AUTRE produit → on déplace le
mauvais, et `_verify_gone(id, url)` voit l'ancienne URL toujours là → `gone=False`
→ l'offre visée est reportée FAILED, le mauvais move est SILENCIEUX.
**Fix** : dans `_move`, après navigate, re-lire `page_offer_rows`, re-`_row_check`
(name+url) ; bloquer sur mismatch ; relocaliser par URL si l'id a disparu.

### MV2. Tout blocker `_locate_row` avalé en SKIP « déjà déplacé » — FIXED (commit 9b479d0)
`mover.py:163` pose `entry['skipped']` et `continue` AVANT `guard.record_result`
→ les échecs de localisation ne nourrissent jamais le breaker 10-échecs ; et le
set avalé inclut de VRAIES contradictions d'identité (mismatch title/store/url),
pas seulement « absent ». Effet : un plan lancé contre un mauvais store/source, un
feed périmé, ou après un re-import massif → tout en SKIP → `moved=0, attempts=0`,
zéro blocage guard, exit 0 — indistinguable d'un no-op idempotent propre.
**Fix** : distinguer « absent (idempotent) » de « présent-mais-contredit »
(fail-closed) ; router les échecs de localisation via `guard.record_result`.

### MV3. `build_move_plan` admet une URL marchande vide → preuve de disparition id-seule (falsifiable) — FIXED (commit 9b479d0)
`move_plan.py:74` n'exclut que si `skipped_map.get(id) is None`, pas si l'url est
vide, malgré sa raison affichée « pas d'URL pour relocaliser ». Une offre à
`url=''` est admise → `_verify_gone` avec `stop_on_url=None` → « gone » prouvé par
id SEUL → un re-import ré-ide l'offre encore présente → FAUX « gone from source ».
**Fix** : exclure (surfacer) les entries à url vide/blanche — la garantie que le
commentaire promet déjà.

### MV4. Le DRY-RUN (défaut) s'auto-bloque au-delà de 10 offres — FIXED (commit 9b479d0)
`DryRunMover._move` retourne toujours `False`, et `run()` appelle
`guard.record_result(..., success=False)` pour chaque entry (non gated sur
write_mode). Le même `StepGuard(max_consecutive_failures=10)` est passé au
DryRunMover → la 10ᵉ offre bloque le guard, la 11ᵉ est refusée → un dry-run de
>10 dispositions confirmées n'affiche que 10 offres avec un `stopped=guard_blocked`
alarmant. Le dry-run EST le défaut (preview pré-canary). Le submitter évite ça
(`DryRunSubmitter._process` retourne `bool(ready)` = succès).
**Fix** : un dry-run row located+selectable enregistre un succès (comme le submit).

## P2 — sûreté du 1er move

### MV5. `resolve_list_id` prend le 1er match de label sans garde d'ambiguïté — FIXED (commit 9b479d0)
Des labels de liste dupliqués misrouteraient le move en silence (le
`resolve_catalog_id` du submitter exige un match UNIQUE). **Fix** : collecter tous
les matches, >1 → fail-closed (comme un label non résolu).

### MV6. `--execute --mode safe` par défaut = plan COMPLET sur un writer jamais testé live — FIXED (commit 9b479d0)
Aucun garde-fou « 1er move = canary ». **Fix proposé (fail-closed)** : tant
qu'aucun move réussi n'est au `move_guard_ledger`/`move_plan.json`, refuser
`--execute --mode safe` et exiger `--mode learning` (canary de 1). **Décision de
Romain.**

### MV7. Pas de settle entre l'Apply (POST natif) et le re-scan de vérif — FIXED (commit 9b479d0)
`mover.py:285` navigue immédiatement pour vérifier → peut annuler le POST
in-flight ; le submitter attend délibérément. **Fix** : après `click_apply`
CLICKED, attendre la navigation du POST (poll href/readyState) avant `_verify_gone`.

### MV8. Index de départ early-terminé (2 pages sans nouveaux ids) → offre en page ultérieure = faux « absent » — FIXED (commit 9b479d0)
`_scan_feed` s'arrête après `empty>=2` quand il indexe sans cible. **Fix** : sur
un locate-miss, scan de confirmation ciblé (`stop_on`=id+url, va jusqu'à la fin
prouvée) AVANT de conclure « absent ».

### MV9. Stop `guard.blocked` manquant après `record_result` — FIXED (commit 9b479d0)
Si le 10ᵉ échec est la dernière entry du plan, `stopped=None` (le submitter ajoute
`if guard.blocked: stopped=...; break`). **Fix** : idem submitter.

### MV10. Overrides `--store-id`/`--source-list` non réconciliés avec raw.json — FIXED (commit 9b479d0)
Un mismatch dégrade en faux « already moved » silencieux. **Fix** : si un override
diffère de `plan_doc`, refuser (fail-closed).

### MV11. Exception CDP dans `set_bulk_list`/`click_apply` échappe l'abort structuré — FIXED (commit 9b479d0)
Après le register, une `RuntimeError` (hors `FEED_UNREADABLE_EXCS`) remonterait
sans artefact ni snapshot guard. **Fix** : wrapper les étapes write → abort
fail-closed (entry post_verify UNKNOWN, record_result(False), artefact écrit).

### MV12. Post-verify prouve le DÉPART de la source, pas l'ARRIVÉE sur la cible — FIXED (commit 9b479d0, doc — pas de confirmation cible, décision Romain)
Le move/delete d'un opérateur parallèle compterait comme succès. **Fix** :
documenter que `moved` = « a quitté la source » ; option (désactivée par défaut)
de confirmer la présence sur la liste cible.

### MV13. Cohérence learning.json ↔ skipped.json non vérifiée + docstrings surévaluées — FIXED (commit 9b479d0)
`build_move_plan` fait confiance à l'appariement id sans vérifier l'identité
d'extraction ; « submit-grade gate » surévalue (pas de fingerprint façon
`verify_approved_against_source`). **Fix** : mitigé par MV1 (re-check identité au
move) ; documenter honnêtement (learning.json = autorité d'intention humaine), et
noter un stamp d'extraction comme amélioration.

### MV14. `resolve_list_id` ignore `target_id_hint` alors que la docstring promet un fallback — FIXED (commit 9b479d0)
**Fix** : label-only fail-closed — retirer le param inutilisé + corriger la doc.

### MV15. Tests manquants (pré-canary) — FIXED (commit 9b479d0)
>10 offres en dry-run (garde MV4), listes cibles divergentes, feed source
multi-pages, re-id mid-run (MV1), url vide exclue (MV3), ambiguïté de label (MV5),
override incohérent (MV10).

## Réfutés (ne pas corriger)

- Register proof tautologique / Apply clique le 1er bouton / sélecteur checkbox :
  réfutés (le scope `form[data-bulk-form]` distingue le hidden ; Apply EST le bon
  bouton ; `[value="<id>"]` cible la bonne case).
- `confirmed` fail-open, provenance opérateur absente, delete/'' specials dans
  resolve : réfutés (les specials ne matchent aucun label « Move to X » ;
  `suggested` filtré par le builder).

## Décisions pour Romain

- **MV6** : → **TRANCHÉE : canary obligatoire** (Romain 2026-07-21), implémentée commit 9b479d0.
- **MV12** : → **TRANCHÉE : « gone from source » seul + doc** (Romain 2026-07-21), commit 9b479d0.

## Journal
- 2026-07-22 : **1er canary RÉUSSI** (IObit → Softwares, gone-from-source vérifié).
  Registration passée du clic trusted (fragile sur pages paginées) à l'injection
  déterministe du hidden `bulk[item][]`.
- 2026-07-21 : review adversariale (commit `3465cb6`), registre créé, tout OPEN.
- 2026-07-21 : GO Romain (MV6=canary obligatoire, MV12=gone-from-source seul). MV1-MV15 tous FIXED — commit 9b479d0, suite 738 verte. Le writer est prêt pour un 1er
  canary (`--execute --mode learning`) sur go explicite de Romain.
