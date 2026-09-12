# État du feed — Instant Gaming (store 28)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020000-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:58 UTC (58 min)
- **Pages parcourues** : 4 — 399 offres vues, 0 candidats, **0 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 98 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-11 | 60 |
| 2026-09-11 | 38 |

| Édition saisie | Offres |
|---|---|
| Standard | 71 |
| Deluxe | 11 |
| Ultimate | 5 |
| Collection | 4 |
| DLC | 3 |
| Ultimate Collection | 2 |
| Honeyglow Woods Edition | 1 |
| Aviator Edition | 1 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 92 |
| Publisher (1) | 6 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260811-113118-auto` | 2026-08-11 11:31 UTC | 4 | 368 | 8 | 6 | — |
| `20260811-131613-auto` | 2026-08-11 13:16 UTC | 4 | 381 | 54 | 54 | — |
| `20260911-161908-auto` | 2026-09-11 16:19 UTC | 5 | 437 | 38 | 38 | — |
| `20260912-020000-auto` | 2026-09-12 02:00 UTC | 4 | 399 | 0 | 0 | — |

## Ce qui reste dans le feed et pourquoi

399 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 8 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 158 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| Bundles / packs multi-jeux | 10 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 12 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 4 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Régions verrouillées interdites | 105 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 2 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS sans carte d'éditions | 2 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Sonde AKS non fiable (transitoire) | 96 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Autres | 2 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (8)

- Xbox Game Pass Premium 3 Months — `console`
- Xbox Game Pass Ultimate 1 Month — `console`
- Xbox Game Pass Ultimate 3 Months — `console`
- … 5 autres

### Sans page produit AKS (158)

- SONIC PICO PARK — `no AKS product page found (slug not 200)`
- Dungeon Brawls — `no AKS product page found (slug not 200)`
- Romancing SaGa 3: Destinies United — `no AKS product page found (slug not 200)`
- … 155 autres

### Bundles / packs multi-jeux (10)

Motifs exacts : possible multi-game bundle (6), skip category (4).

- Attack on Titan 3 - A.O.T.3 Digital Deluxe Edition + Advanced access — `possible multi-game bundle`
- Attack on Titan 3 - A.O.T.3 Digital Deluxe Edition + Advanced access — `possible multi-game bundle`
- Attack on Titan 3 - A.O.T.3 Digital Deluxe Edition + Advanced access — `possible multi-game bundle`
- … 7 autres

### Monnaie in-game (points, coins, gems…) (12)

- All Hail the Orb — `skip category: ORB (in-game currency)`
- Train Valley 2: Workshop Gems - Onyx — `skip category: GEMS`
- Tom Clancy’s Rainbow Six Siege 3,300 R6 Credits — `skip category: CREDITS`
- … 9 autres

### Passes in-game (Battle Pass, Game Pass…) (4)

- Indie Pass 1 Month — `skip category: PASS (in-game/battle pass)`
- Indie Pass 1 Month — `skip category: PASS (in-game/battle pass)`
- Indie Pass 1 Year — `skip category: PASS (in-game/battle pass)`
- … 1 autres

### Régions verrouillées interdites (105)

- Dumb Ways to Build — `forbidden region: LATIN AMERICA`
- Valheim — `forbidden region: LATIN AMERICA`
- Dumb Ways to Build — `forbidden region: EUROPE & USA & CANADA`
- … 102 autres

### Édition / variante absente de la page AKS (2)

Motifs exacts : edition 'Ultimate Collection' (1), different/expanded product (1).

- METAL SLUG ULTIMATE COLLECTION — `edition 'Ultimate Collection'(348) not sold on the resolved AKS page — guessed edition unverified (audit P1-1)`
- Total War: WARHAMMER III – Lords of the End Times — `different/expanded product — extra words: ['LORDS', 'END', 'TIMES']`

### Page AKS sans carte d'éditions (2)

- Okko The Exiled — `AKS page carries no editions map — edition unverifiable (R19)`
- Fate/EXTRA Record — `AKS page carries no editions map — edition unverifiable (R19)`

### Sonde AKS non fiable (transitoire) (96)

- SONIC PICO PARK — `Instant Gaming offer page unreadable — unverifiable (R32): IG offer page region metadata missing/unparseable (`
- Fading Echo — `Instant Gaming offer page unreadable — unverifiable (R32): IG offer page region metadata missing/unparseable (`
- House Flipper 2 — `Instant Gaming offer page unreadable — unverifiable (R32): IG offer page region metadata missing/unparseable (`
- … 93 autres

### Autres (2)

Motifs exacts : Instant Gaming offer page names an unrecognized platform (1), Instant Gaming platform conflict (1).

- Sea of Thieves Premium Edition — `Instant Gaming offer page names an unrecognized platform — not entered (R32)`
- World of Warcraft: Shadowlands Epic Edition — `Instant Gaming platform conflict: title=EPIC vs offer page=BATTLENET — not entered (audit #1)`
