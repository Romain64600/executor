# Audit d'intégration — coutures Learning → Move-to-List — 2026-07-21

Audit des CONTRATS entre fichiers du pipeline (admin `app.js` → `learning_io` →
`learning.json` → `move_plan` → `mover`), les pièces ayant déjà été auditées en
isolation. Workflow interrompu par la limite de session (2 coutures /4 tracées,
phase de réfutation non exécutée) — les findings ci-dessous sont donc **vérifiés
manuellement par lecture du code**, pas par réfutation adversariale.

## Findings corrigés (tous P2)

### SF1. `suggested` fail-OPEN au trust boundary — FIXED (commit à venir)
`move_plan.py` excluait sur `ann.get("suggested") is True` (strict). Une entrée à
`target_list_id` présent mais `suggested` non-booléen-strict (JSON `1`, `"true"`)
passait comme move CONFIRMÉ (fail-OPEN dans un projet fail-closed). Non déclenché
par l'UI (learning_io écrit toujours `bool True`), mais le builder ne doit pas
faire confiance à l'amont. **Fix** : exclusion sur toute valeur *truthy*
(`if ann.get("suggested"):`) — défense en profondeur. Une clé absente reste
« confirmé » (contrat inchangé).

### SF2. Impossible de confirmer une suggestion « telle quelle » — FIXED (option B, 2026-07-22)
Le seul signal de confirmation était l'événement `change` du select, qui ne se
déclenche que si la valeur CHANGE : re-sélectionner la liste déjà suggérée ne
confirmait rien → l'offre restait exclue du plan, sans feedback. **Décision
Romain : option B** (confirmation EXPLICITE, la plus fidèle à D1-b — un défaut ne
devient jamais une décision par accident). **Fix** : un bouton **« ✓ confirmer »**
par offre suggérée (+ un bouton global **« confirmer toutes les suggestions »**) ;
changer la valeur du select reste une confirmation (décision explicite) ; regarder
le menu ne confirme plus rien. Feedback visuel « ✔ confirmé ».


### SF3. Une disposition confirmée devient orpheline après un re-match — FIXED
`build_move_plan` joignait par `offer_id` contre `skipped.json`. Les ids tournent
à chaque re-import ([[feed-reimport-id-rotation]]) ; une disposition confirmée
sur un run re-matché devenait « orpheline » et était EXCLUE, alors que l'offre
existe sous un nouvel id avec la même URL — le reste du pipeline résout par URL,
pas cette couture. **Fix** : `learning_io` fige la **`merchant_url`** dans
l'annotation au save (identité stable), et `build_move_plan` fait un fallback de
join par `_url_key` quand l'`offer_id` a tourné (l'entry porte le nouvel id +
`annotated_offer_id`).

### SF4. `cleared` gardé derrière `bad_offer` — FIXED
`save_annotations` rejetait tout `offer_id` absent de `skipped.json` (bad_offer)
AVANT de traiter `cleared`. Une annotation périmée (id tourné) ne pouvait donc ni
être déplacée (orpheline, désormais relocalisée par SF3) ni **effacée** (bad_offer)
→ coincée à vie. **Fix** : `cleared` est traité AVANT la validation d'appartenance
— supprimer ne dépend jamais de l'offre encore présente.

## Coutures non tracées ce passage (limite de session) — analyse manuelle

- **validate-vs-resolve** : `learning_io` valide `target_list_id ∈ LISTS` +
  label cohérent ; le mover résout par LABEL live. Un drift de label AKS ⇒ le
  mover **abort fail-closed** (voulu). L'ambiguïté de label est gardée (MV5).
- **dead-end-fields** : `region/edition/platform/scope/comment/aks_url` ne sont
  consommés par AUCUN code (pas de saisie assistée construite). C'est le **gap
  connu D2** (moteur de règles vs builder-offline) — capture délibérée pour le
  processus builder — **D2 TRANCHÉ (Romain 2026-07-22)** : on officialise le
  processus builder-offline, documenté dans `docs/LEARNING_PROCESS.md`.

## Journal
- 2026-07-21 : audit coutures (workflow interrompu, findings vérifiés à la main).
  SF1-SF4 FIXED + tests. SF2 : décision UX ouverte à l'époque ; D2 ouvert.
- 2026-07-22 : D2 tranché (builder-offline, `docs/LEARNING_PROCESS.md`) ;
  SF2 tranché → option B (bouton « confirmer » explicite + « tout confirmer »).
