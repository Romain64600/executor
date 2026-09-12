# État du feed — Kinguin (store 58)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020001-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:47 UTC (47 min)
- **Pages parcourues** : 10 — 1000 offres vues, 1 candidats, **1 créées**
- **Issue** : aucune halte, couverture : `incomplete_max_pages (feed has 67 pages)`
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 123 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-05 | 17 |
| 2026-08-06 | 5 |
| 2026-09-01 | 4 |
| 2026-09-07 | 1 |
| 2026-09-08 | 27 |
| 2026-09-11 | 51 |
| 2026-09-12 | 1 |
| tria-ge--e | 17 |

| Édition saisie | Offres |
|---|---|
| Standard | 97 |
| DLC | 17 |
| Deluxe | 5 |
| Complete | 3 |
| Special | 1 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 104 |
| GOG Global (6) | 10 |
| Steam EU (9) | 3 |
| Steam Gift (25) | 2 |
| Publisher (1) | 1 |
| Ubisoft Global (50) | 1 |
| Steam UK (71) | 1 |
| Ubisoft EU (54) | 1 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260805-112034-auto` | 2026-08-05 11:20 UTC | 30 | 3000 | 17 | 17 | coverage_incomplete_max_pages (feed has 123 pages) |
| `20260805-165843-auto` | 2026-08-05 16:58 UTC | 44 | 4394 | 74 | 0 | match_failed_p80 |
| `20260806-084020-auto` | 2026-08-06 08:40 UTC | 30 | 3000 | 5 | 5 | coverage_incomplete_max_pages (feed has 122 pages) |
| `20260908-094906-auto` | 2026-09-08 09:49 UTC | 4 | 349 | 3 | 0 | submit_not_clean_p63 |
| `20260908-160023-auto` | 2026-09-08 16:00 UTC | 30 | 3000 | 46 | 25 | coverage_incomplete_max_pages (feed has 65 pages) |
| `20260911-161908-auto` | 2026-09-11 16:19 UTC | 30 | 3000 | 44 | 44 | — |
| `20260911-190500-auto` | 2026-09-11 19:14 UTC | 37 | 3633 | 7 | 7 | — |
| `20260912-020001-auto` | 2026-09-12 02:00 UTC | 10 | 1000 | 1 | 1 | — |

### Offres créées au dernier passage (1)

- Dungeons of Blood and Dream PC Steam CD Key → `dungeons-of-blood-and-dream-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

999 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 388 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 318 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 22 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 14 | règle : on ne saisit jamais de bundle | décision Romain |
| Cartes prépayées / gift cards / wallets | 109 | hors périmètre (prepaids) | décision Romain |
| Abonnements | 37 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Régions verrouillées interdites | 26 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 75 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 2 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Logiciels | 1 | édition / région logicielle non résolue sur la page AKS (R31) | vérifier à la main |
| Rockstar sans région | 3 | plateforme Rockstar sans bucket de région AKS | à apprendre |
| Autres | 4 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (388)

- Onimusha: Way of the Sword EU PS5 CD Key — `console`
- Star Wars Zero Company Deluxe Edition US PS5 CD Key — `console`
- Blocky Farm XBOX One / Xbox Series X\|S Account — `console`
- … 385 autres

### Sans page produit AKS (318)

- Warhammer 40,000: Gladius - Relics of War - Lord of Skulls DLC EU PC Steam CD Key — `no AKS product page found (slug not 200)`
- Darksiders Genesis TR PC Steam CD Key — `no AKS product page found (slug not 200)`
- Metro Awakening US PC Steam CD Key — `no AKS product page found (slug not 200)`
- … 315 autres

### DLC sans page AKS propre (22)

Motifs exacts : DLC in title but AKS page 'fortnite' carries no DLC edition (4), DLC in title but AKS page 'god-of-weapons' carries no DLC edition (2), DLC in title but AKS page 'rpg-maker-mv' carries no DLC edition (2), DLC in title but AKS page 'overcooked-2' carries no DLC edition (1), DLC in title but AKS page 'taxi-life-a-city-driving-simulator' carries no DLC edition (1), DLC in title but AKS page 'meadow' carries no DLC edition (1).

- Fortnite - Frosty Visions Wrap DLC PC Epic Games CD Key — `DLC in title but AKS page 'fortnite' carries no DLC edition — base game or wrong product, not entered (R43)`
- Fortnite - Taffy Wrap DLC PC Epic Games CD Key — `DLC in title but AKS page 'fortnite' carries no DLC edition — base game or wrong product, not entered (R43)`
- Overcooked! 2 - Campfire Cook Off DLC EU PC Steam CD Key — `DLC in title but AKS page 'overcooked-2' carries no DLC edition — base game or wrong product, not entered (R43`
- … 19 autres

### Bundles / packs multi-jeux (14)

Motifs exacts : skip category (11), possible multi-game bundle (3).

- Hearts of Iron IV: Ultimate Bundle 2020 PC Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- Our Life Bundle PC Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- Our Life Bundle PC Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- … 11 autres

### Cartes prépayées / gift cards / wallets (109)

- Google Play SAR 12 Gift Card SA — `skip category: GIFT CARD`
- ASOS $100 Gift Card AU — `skip category: GIFT CARD`
- Tokopedia IDR 10000 Gift Card ID — `skip category: GIFT CARD`
- … 106 autres

### Abonnements (37)

- GeForce NOW Game+ - 3 Months Subscription TR — `skip category: SUBSCRIPTION`
- Super Duolingo 12 Month Subscription Link — `skip category: SUBSCRIPTION`
- Adobe Creative Cloud Photography Plan - 1 Year Subscription Key AU — `skip category: SUBSCRIPTION`
- … 34 autres

### Régions verrouillées interdites (26)

- Bus Simulator 27 RoW PC Steam CD Key — `forbidden region: ROW`
- Dead Cells - The Bad Seed DLC RoW PC Steam CD Key (valid until March 2027) — `forbidden region: ROW`
- Dead Cells RoW PC Steam CD Key (valid until March 2027) — `forbidden region: ROW`
- … 23 autres

### Édition / variante absente de la page AKS (75)

- GreedFall PC Steam CD Key (valid until June 2027) — `different/expanded product — extra words: ['VALID', 'UNTIL', 'JUNE', '2027']`
- Time to Morp PC Steam CD Key (valid until June 2027) — `different/expanded product — extra words: ['VALID', 'UNTIL', 'JUNE', '2027']`
- Factory Town PC Steam CD Key (valid until June 2027) — `different/expanded product — extra words: ['VALID', 'UNTIL', 'JUNE', '2027']`
- … 72 autres

### Page AKS trouvée mais nom différent (2)

- Budget Cuts Ultimate PC Steam CD Key (valid until June 2027) — `name mismatch, missing AKS words: ['VR']`
- Farmer's Dynasty 2 Complete Edition PC Steam CD Key — `name mismatch, missing AKS words: ['FARMERS']`

### Logiciels (1)

- CCleaner Professional 2021 Key (2 Years / 1 PC) — `software edition unresolved on the AKS page (1 editions, none in title) — not guessed (R31)`

### Rockstar sans région (3)

Motifs exacts : no region id for ROCKSTAR/GLOBAL (2), no region id for ROCKSTAR/UK (1).

- Grand Theft Auto V Enhanced DE PC Rockstar Digital Download CD Key — `no region id for ROCKSTAR/GLOBAL`
- Grand Theft Auto V Enhanced BR PC Rockstar Digital Download CD Key — `no region id for ROCKSTAR/GLOBAL`
- Grand Theft Auto V Enhanced UK PC Rockstar Digital Download CD Key — `no region id for ROCKSTAR/UK`

### Autres (4)

Motifs exacts : skip category (3), language restriction (1).

- Far Cry 5 - Season Pass EU Uplay Activation Link — `skip category: ACTIVATION LINK`
- Bitdefender Antivirus For Mac 2026 EU Key (2 Years / 3 Devices) — `skip category: ANTIVIRUS`
- Deadlight: Director's Cut English Language Only Steam CD Key — `language restriction`
- … 1 autres
