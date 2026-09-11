# État du feed — Kinguin (store 58)

_Généré le 2026-09-11 20:29 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260911-190500-auto` — du 2026-09-11 19:14 UTC au 2026-09-11 20:15 UTC (1 h 00)
- **Pages parcourues** : 37 — 3633 offres vues, 7 candidats, **7 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 122 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-05 | 17 |
| 2026-08-06 | 5 |
| 2026-09-01 | 4 |
| 2026-09-07 | 1 |
| 2026-09-08 | 27 |
| 2026-09-11 | 51 |
| tria-ge--e | 17 |

| Édition saisie | Offres |
|---|---|
| Standard | 96 |
| DLC | 17 |
| Deluxe | 5 |
| Complete | 3 |
| Special | 1 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 103 |
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

### Offres créées au dernier passage (7)

- Big Fish Legend Steam CD Key → `big-fish-legend-cd-key-compare-prices` (Standard, Steam (2))
- Beats Of Fury PC Steam CD Key → `beats-of-fury-cd-key-compare-prices` (Standard, Steam (2))
- Saga of the Moon Priestess Steam CD Key → `saga-of-the-moon-priestess-cd-key-compare-prices` (Standard, Steam (2))
- Forge Steam CD Key → `forge-cd-key-compare-prices` (Standard, Steam (2))
- Memory of Memorie: A Chill Story PC Steam CD Key → `memory-of-memorie-a-chill-story-cd-key-compare-prices` (Standard, Steam (2))
- Radio Commander: Squad Management DLC PC Steam CD Key → `radio-commander-squad-management-cd-key-compare-prices` (DLC, Steam (2))
- Unheard Screams - King Leopold II rule over the Congo Steam CD Key → `unheard-screams-king-leopold-2-rule-over-the-congo-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

3626 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 884 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 2203 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 152 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 216 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 12 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 28 | hors périmètre (prepaids) | décision Romain |
| Régions verrouillées interdites | 25 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 51 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 4 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Logiciels | 5 | édition / région logicielle non résolue sur la page AKS (R31) | vérifier à la main |
| Page AKS sans carte d'éditions | 1 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Sonde AKS non fiable (transitoire) | 3 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Autres | 42 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (884)

- Little Droid EU Nintendo Switch / Switch 2 CD Key — `console`
- Unicorn Overlord - ATLUS X Vanillaware Heraldry Pack DLC EU (without DE) PS5 CD Key — `console`
- Tom Clancy's The Division 2 - Warlords Of New York Expansion DLC US XBOX One / Xbox Series X\|S CD Key — `console`
- … 881 autres

### Sans page produit AKS (2203)

- RAGER PC Steam CD Key — `no AKS product page found (slug not 200)`
- Survivor Spark Steam CD Key — `no AKS product page found (slug not 200)`
- Dawn of Kagura: Maika's Story - The Dragon's Wrath PC Steam CD Key — `no AKS product page found (slug not 200)`
- … 2200 autres

### DLC sans page AKS propre (152)

Motifs exacts : DLC in title but AKS page 'oddworld-new-n-tasty' carries no DLC edition (15), DLC in title but AKS page 'djmax-respect-v' carries no DLC edition (14), DLC in title but AKS page 'overwatch-2' carries no DLC edition (14), ADD ON in title but AKS page 'train-simulator-2017' carries no DLC edition (14), DLC in title but AKS page 'battlefleet-gothic-armada' carries no DLC edition (13), DLC in title but AKS page 'pioner' carries no DLC edition (13).

- Over The Top: WWI - Elite Armored DLC PC Steam CD Key — `DLC in title but AKS page 'over-the-top-wwi' carries no DLC edition — base game or wrong product, not entered `
- DragonSword Awakening - Deluxe Pack DLC PC Steam CD Key — `DLC in title but AKS page 'dragonsword-awakening' carries no DLC edition — base game or wrong product, not ent`
- Wild Terra 2: New Lands - Christmas Pack DLC CD Key — `DLC in title but AKS page 'wild-terra-2-new-lands' carries no DLC edition — base game or wrong product, not en`
- … 149 autres

### Bundles / packs multi-jeux (216)

Motifs exacts : skip category (196), possible multi-game bundle (20).

- TechSmith Software Bundle CD Key (2 Devices) — `skip category: BUNDLE (no bundles/skins)`
- Windows 10 Professional OEM 3 Keys Bundle — `skip category: BUNDLE (no bundles/skins)`
- The Caligula Effect: Overdose - Swimsuit Bundle DLC Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- … 213 autres

### Monnaie in-game (points, coins, gems…) (12)

- CaseBattles.gg 1000 Gems Code — `skip category: GEMS`
- CaseBattles.gg 1000 Gems Code — `skip category: GEMS`
- CaseBattles.gg 1000 Gems Code — `skip category: GEMS`
- … 9 autres

### Cartes prépayées / gift cards / wallets (28)

- RewUp PayPal 50 EUR Gift Card — `skip category: GIFT CARD`
- RewUp PayPal 50 EUR Gift Card — `skip category: GIFT CARD`
- RewUp PayPal 50 EUR Gift Card — `skip category: GIFT CARD`
- … 25 autres

### Régions verrouillées interdites (25)

- Smalland: Survive the Wilds EU/NA PC Steam CD Key — `forbidden region: EU NA`
- Final Fantasy VII Remake & Rebirth: Twin Pack RoW PC Steam CD Key — `forbidden region: ROW`
- Smalland: Survive the Wilds EU/NA PC Steam CD Key — `forbidden region: EU NA`
- … 22 autres

### Édition / variante absente de la page AKS (51)

- MAGIX Music Maker - Breakbeat Electronic Breaks Digital Download CD Key — `different/expanded product — extra words: ['BREAKBEAT', 'ELECTRONIC', 'BREAKS']`
- AVG PC TuneUp 2020 Key (2 Years / 1 PC) — `different/expanded product — extra words: ['2', 'YEARS', '1']`
- AVG PC TuneUp 2020 Key (2 Years / 1 PC) — `different/expanded product — extra words: ['2', 'YEARS', '1']`
- … 48 autres

### Page AKS trouvée mais nom différent (4)

- Amerzone: The Explorer's Legacy (2025) Deluxe Edition PC Steam CD Key — `name mismatch, missing AKS words: ['EXPLORERS']`
- Amerzone: The Explorer's Legacy (2025) Deluxe Edition PC Steam CD Key — `name mismatch, missing AKS words: ['EXPLORERS']`
- Amerzone: The Explorer's Legacy (2025) Deluxe Edition PC Steam CD Key — `name mismatch, missing AKS words: ['EXPLORERS']`
- … 1 autres

### Logiciels (5)

- EaseUS Partition Master Professional 2026 Key (1 Month / 2 PCs) — `software edition unresolved on the AKS page (2 editions, none in title) — not guessed (R31)`
- AVG Internet Security 2025 Key (2 Years / 5 Devices) — `software edition unresolved on the AKS page (2 editions, none in title) — not guessed (R31)`
- EaseUS Partition Master Professional 2026 Key (1 Month / 2 PCs) — `software edition unresolved on the AKS page (2 editions, none in title) — not guessed (R31)`
- … 2 autres

### Page AKS sans carte d'éditions (1)

- Reveal The Deep Steam Gift — `AKS page carries no editions map — edition unverifiable (R19)`

### Sonde AKS non fiable (transitoire) (3)

- Color Splash: Mushrooms PC Steam CD Key — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Qrabbles PC Steam CD Key — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- PhotoFiltre Studio 11 CD Key (3 PCs) — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`

### Autres (42)

- Nioh 2 The Complete Edition EN Language Only US PC Steam CD Key — `language restriction`
- Nioh 2 The Complete Edition EN Language Only US PC Steam CD Key — `language restriction`
- Call of Duty: Modern Warfare II Endowment (C.O.D.E.) - Protector Pack DLC EN Language Only Battle.net CD Key — `language restriction`
- … 39 autres
