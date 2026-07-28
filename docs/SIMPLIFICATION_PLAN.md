# Plan de simplification — chemin de tri (Move-to-List)

_Établi 2026-07-28 à partir d'une analyse multi-agents (5 zones) + revue de
sûreté adversariale par zone. Verdict global : **1 seule vraie simplification**
apporte tout le gain ; les raccourcis de vérification proposés à côté sont
**rejetés** (ils échangent un invariant contre un gain négligeable)._

## Constat

Un batch de 213 offres prenait **>1 h**. La cause n'est PAS le scan read-only
(Stage 8) ni la rotation d'ID. C'est le **mover qui déplace 1 offre par Apply**
et paie **~3 scans de feed PAR offre** :

- `_relocate_before_move` : scan partiel du feed source par URL ;
- 1 `Apply` (POST natif, 1 seul `bulk[item][]`) ;
- `_verify_gone` : **scan complet** du feed source (il faut prouver l'absence
  → il va jusqu'à la fin prouvée du feed) — le coût dominant ;
- `_verify_on_target` : scan de la liste cible.

→ pour 213 offres : ~213 scans complets + ~426 partiels ≈ 45-70 min de scan pur.
Le formulaire AKS accepte pourtant **`bulk[item][]` répétable** : on jette cette
capacité en cochant une offre à la fois.

## LA simplification (celle qui compte)

**Grouper par page source, cocher N offres, UN seul Apply, vérifier le groupe
en une fois.**

```
AVANT (par offre, ×N) : relocate-scan → navigate → cocher 1 id → Apply →
                        verify_gone (scan complet) → verify_on_target
APRÈS (par page源) :    index 1× → pour chaque page ayant des offres du plan :
                        navigate(page) → pour chaque offre : re-check identité
                        (nom+URL) sur la page fraîche → cocher son id ;
                        set_bulk_list 1× → Apply 1× (le POST déplace TOUS les
                        bulk[item][]) → vérifier LE GROUPE : 1 scan source
                        complet (tous partis) + 1 scan cible (tous arrivés)
```

**Gain** : le nombre de scans passe de `O(N)` à `O(pages)`, **indépendant de la
taille du batch**. 213 offres sur ~3 pages : ~640 scans → une poignée. Le batch
**>1 h tombe à ~1-2 min**. Et account 16k, aujourd'hui **infaisable** (~80 h à
18 s/offre), devient faisable (~1-2 h).

## Les garde-fous qu'on GARDE (non négociables)

La revue de sûreté a été unanime : la vitesse vient du **batch de l'Apply**, PAS
d'un affaiblissement des vérifs. On garde donc, ré-exprimés « par groupe » :

1. **Vérif par GROUPE, juste après son Apply** — jamais une seule vérif différée
   en fin de batch. Sinon la fenêtre d'attribution passe de ~2 s à >1 h et un
   opérateur parallèle qui déplace la même offre vers la même liste serait
   crédité comme notre succès (invariant 3).
2. **Re-scan / re-index du feed source ENTRE deux Apply** — chaque Apply vide la
   liste source → les pages suivantes remontent (reflow). Ne jamais réutiliser
   les URLs de page capturées à l'index initial. (C'est le reflow que le mover
   **provoque lui-même** ; les ID stables n'impliquent PAS une pagination
   stable.)
3. **Re-check d'identité (nom+URL) sur la page fraîche AVANT de cocher chaque
   id** (EXECUTOR_RULES §6). Une offre absente / identité changée = SKIP « déjà
   déplacée », jamais un move au mauvais endroit.
4. **`moved` = (cochée par NOUS dans cet Apply) ET partie de la source ET
   présente sur la cible.** Jamais déduit des deux scans seuls (trou opérateur
   parallèle + Apply silencieusement raté).
5. **Les deux scans de vérif restent fail-closed** : couverture prouvée
   (fin de feed atteinte), `FeedScanError` → état **UNKNOWN**, jamais une
   absence non prouvée lue comme « parti ». Sur erreur feed/CDP après l'Apply :
   tout le groupe en vol → UNKNOWN + artefact « vérifier à la main ».
6. **`record_result` + breaker 10-échecs + ledger + tally PAR GROUPE** (pas en
   fin de batch) → le breaker mord AVANT l'Apply suivant, blast radius borné.
7. **`MOVER_VERSION` 3→4 (RV3)** : une autorisation canary v3 ne doit pas couvrir
   le nouveau mécanisme multi-item. Et **re-gagner le canary avec un VRAI Apply
   multi-item** — un canary cap-1 ne prouve pas la sérialisation multi-item.
8. **Cap batch = mode `safe` uniquement** ; learning/advanced cochent au plus
   `limit` ids par Apply (un canary de 1 ne doit JAMAIS déplacer une page
   entière). `--limit N` borne, n'élargit jamais.
9. **ID stables = fast-path GATÉ, pas un pari.** C'est une habitude humaine
   (Romain ne delete plus), pas une garantie machine. On garde le fallback par
   URL load-bearing + un **tripwire** au démarrage (un échantillon d'ids doit
   encore pointer sur la même URL ; sinon fail-closed). `--full` force
   `ids_stable=False` (mode delete/reimport).

## Ce qu'on NE fait PAS (raccourcis rejetés par la sûreté)

- **Vérif « parti » sur une seule page (id absent)** — REJETÉ. Fail-open : une
  page blanche / rebond login lue « vide » = fausse disparition ; aveugle au
  reflow ; s'appuie à 100 % sur le bras cible. On **garde `_verify_gone` en scan
  complet double-clé (id ET URL)** — une fois batché, il ne tourne qu'1× par
  groupe, donc déjà bon marché.
- **Navigate direct vers la page indexée (sans scan de relocalisation)** —
  REJETÉ. Le mover cause le reflow ; l'offre a bougé de page. Le scan-par-URL de
  `_relocate_before_move` reste porteur.
- **Stage 8 en scan « delta/frontière »** — REJETÉ. Aucun backstop de
  couverture : une offre neuve routable reflowée au-delà de la fenêtre est
  **silencieusement perdue à chaque cycle**, sans rattrapage aval. Et Stage 8
  (read-only, paced) **n'est pas le goulot** — le ledger URL restreint déjà le
  mover au delta non résolu. Si un jour on veut du delta : `--full` planifié
  **obligatoire** comme réconciliateur + `offers.json` = union complète.
- **Retirer le jumeau Stage 6 (`06_move.py`, `move_plan.py`)** — nettoyage
  légitime (la console ne pilote que 08/09) mais **orthogonal** : commit séparé,
  après sign-off qu'aucun appelant hors-console n'en dépend.

## Ordre de build (chaque étape livrable + testée)

- **P1 — Le batch (tout le gain).** `register_rows([...ids])` (boucle sur le JS
  d'injection déjà idempotent) + Apply groupé par page source + **vérif complète
  par groupe** (double-clé source + cible). Mode `safe` only. Re-scan entre
  Apply (garde-fou 2). Tests : reflow multi-pages, groupe partiel, page blanche.
- **P2 — Autorisation & comptabilité.** `MOVER_VERSION`→4, re-gagner le canary
  multi-item, `record_result`/breaker/ledger/tally **par groupe**, cap `safe`
  (garde-fous 6-8).
- **P3 — Fast-path ID gaté (optionnel).** Tripwire ID→URL + locate id-first avec
  fallback URL conservé ; `--full` force le mode complet (garde-fou 9). Gain de
  localisation en plus, sans toucher aux vérifs.
- **Différé / séparé.** Stage 8 delta (non recommandé) ; retrait Stage 6
  (commit distinct, sign-off).

## En une phrase

La vitesse vient **d'un seul geste** : cocher plusieurs offres → un Apply →
**une** vérif de groupe avec **les scans complets qu'on fait déjà confiance**.
Tout le reste (vérif 1-page, navigate direct, scan delta) est une fausse
économie qui brade un invariant. On implémente P1 (+P2 pour l'autorisation),
et un batch d'>1 h devient ~2 min — account 16k inclus.
