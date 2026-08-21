# Réconciliation live — G2A liste 21 (Gift cards), 2026-08-21

Nettoyage ponctuel des offres laissées en état **UNKNOWN** par le bug de verify
*deferred* (re-scan source post-Apply lu avant le reflow). Le bug est corrigé
(commit `f1bd976`, `mover._scan_source_settled` — poll du re-scan) ; ce document
ferme la boucle **incident → fix → preuve** pour les offres déjà touchées.

## Incident

Run `triage-exec-g2a-0821-140831` (G2A, store 38, feed frais, 1 page) :
- **86 gift cards** Apply-soumises vers la **liste 21** (Gift cards).
- Le verify *deferred* a re-scanné la source **immédiatement** après un gros Apply
  (90 offres) et l'a lue **avant le reflow AKS** → les 86 ont été vues « still on
  source » → marquées `moved=False, on_target=None`.
- **Audit du run : `total_moved: 2`** (le seul canary confirmé), **86 « à vérifier
  à la main »**. Fail-closed a joué *safe* (aucun move faux revendiqué), mais
  l'audit **sous-comptait massivement**.

## Méthode (read-only, fail-closed)

Script : `scripts`-hors-arbre, sous `browser_lock`, session `SubmitSession`
(read-only), primitive `_scan_feed` (celle du RV2). Identité par **`url_key`
(path)** — les id G2A tournent au re-import, le path est stable.

- **Scan source** : store 38, `aks-merchant-feeds-9`, `available=all` → **910
  offres vues** (feed entier, ~13 p, couverture complète).
- **Scan cible** : liste 21 en **global** (`store=None`), 63 pages → **5871 offres
  vues** (couverture complète).
- Croisement des 86 `url_key` : présent-cible ∧ absent-source = *moved*.

Les deux scans ont atteint une **fin de feed prouvée** → réconciliation
**définitive**, pas partielle.

## Résultat

| Seau | Compte |
|---|---|
| **MOVED** (présent liste 21, absent source) | **85** |
| **NOT MOVED** (encore sur la source) | **1** |
| ON BOTH / NEITHER | 0 / 0 |

- **85/86 ont réellement bougé** — le verify buggé avait faux-négativé les 85.
- **1 non déplacée** : `The North Face Gift Card 500 AED` (offer `100753653`,
  `…/the-north-face-gift-card-500-aed-northface-key-united-arab-emirates-…`).
  Encore sur la source → sera reprise par le prochain triage (verify corrigé).

**Vérité corrigée du run** : **87 déplacées** (85 + 2 canary), pas 2. `1` non
déplacée. Zéro doublon (aucune ON BOTH), zéro perte (aucune NEITHER).

## Portée

- Détail machine : `runs/triage-exec-g2a-0821-140831-g2a-s38-p1/reconcile_86.json`
  (non versionné — `runs/` est ignoré).
- Le fix `f1bd976` rend les runs futurs **auto-corrects** ; cette réconciliation
  ne sera pas nécessaire de façon récurrente.
- Aucune écriture n'a été faite pendant la réconciliation.
