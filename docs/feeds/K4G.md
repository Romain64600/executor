# État du feed — K4G (store 92)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020000-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:58 UTC (58 min)
- **Pages parcourues** : 7 — 618 offres vues, 10 candidats, **9 créées**
- **Issue** : aucune halte
- **Non créées (1)**, laissées dans le feed pour le passage suivant :
  - Monster Hunter Wilds Gold Edition Europe Steam CD Key — offer not in current feed (by id and by URL)

## Offres ajoutées (cumul, tous passages)

**Total : 119 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-07 | 28 |
| 2026-09-07 | 1 |
| 2026-09-08 | 4 |
| 2026-09-11 | 77 |
| 2026-09-12 | 9 |

| Édition saisie | Offres |
|---|---|
| Standard | 76 |
| DLC | 32 |
| Deluxe | 7 |
| Complete | 1 |
| Supporter Edition | 1 |
| Collection | 1 |
| Champion Edition | 1 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 64 |
| Steam EU (9) | 53 |
| Origin EU (3eu) | 1 |
| GOG Global (6) | 1 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260807-115728-auto` | 2026-08-07 11:57 UTC | 4 | 352 | 29 | 28 | — |
| `20260911-162100-auto` | 2026-09-11 16:17 UTC | 7 | 663 | 78 | 77 | — |
| `20260912-020000-auto` | 2026-09-12 02:00 UTC | 7 | 618 | 10 | 9 | — |

### Offres créées au dernier passage (9)

- Super Fantasy Kingdom Europe Steam CD Key → `super-fantasy-kingdom-cd-key-compare-prices` (Standard, Steam EU (9))
- Little Big Adventure – Twinsen’s Quest Steam CD Key → `little-big-adventure-twinsens-quest-cd-key-compare-prices` (Standard, Steam (2))
- Broken Sword - Shadow of the Templars: Reforged Europe Steam CD Key → `broken-sword-shadow-of-the-templars-reforged-cd-key-compare-prices` (Standard, Steam EU (9))
- Lethal Honor - Order of the Apocalypse Europe Steam CD Key → `lethal-honor-order-of-the-apocalypse-cd-key-compare-prices` (Standard, Steam EU (9))
- Thief Simulator Europe Steam CD Key → `thief-simulator-cd-key-compare-prices` (Standard, Steam EU (9))
- The Legend of Heroes: Trails of Cold Steel IV - Standard Cosmetic Set Steam CD Key → `the-legend-of-heroes-trails-of-cold-steel-iv-standard-cosmetic-set-cd-key-compare-prices` (DLC, Steam (2))
- Mato Anomalies Europe Steam CD Key → `mato-anomalies-cd-key-compare-prices` (Standard, Steam EU (9))
- WARNO - Nemesis #2 - Plateau d'Albion Steam CD Key → `warno-nemesis-2-plateau-dalbion-cd-key-compare-prices` (DLC, Steam (2))
- STEINS;GATE 0 Steam CD Key → `steins-gate-0-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

608 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 144 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 262 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 2 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 24 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 9 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 24 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 2 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Abonnements | 6 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Régions verrouillées interdites | 59 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 55 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 5 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Page AKS sans carte d'éditions | 3 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Autres | 13 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (144)

- Icarus Console Edition Europe XBOX Series X\|S CD Key — `console`
- Trepang2 Standard Edition Europe PC/XBOX Series X\|S CD Key — `console`
- Borderlands 3 Ultimate Edition Europe PS4/PS5 CD Key — `console`
- … 141 autres

### Sans page produit AKS (262)

- Octahedron: Transfixed Collector's Edition Steam CD Key — `no AKS product page found (slug not 200)`
- Kingdom Eighties Rad Deluxe Edition Steam CD Key — `no AKS product page found (slug not 200)`
- WARRIORS: Abyss Hack'n'Dash Ultimate Edition Steam CD Key — `no AKS product page found (slug not 200)`
- … 259 autres

### DLC sans page AKS propre (2)

- Watch Dogs: Legion - Season pass Steam Altergift — `SEASON PASS in title but AKS page 'watch-dogs-legion' carries no DLC edition — base game or wrong product, not`
- Watch Dogs: Legion - Season pass Europe Steam Altergift — `SEASON PASS in title but AKS page 'watch-dogs-legion' carries no DLC edition — base game or wrong product, not`

### Bundles / packs multi-jeux (24)

Motifs exacts : skip category (21), possible multi-game bundle (3).

- Middle-earth: The Shadow Bundle Europe Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- Mortal Kombat 11 Ultimate Add-On Bundle Europe Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- DEAD CELLS: THE BAD SEED BUNDLE Europe Steam CD Key — `skip category: BUNDLE (no bundles/skins)`
- … 21 autres

### Monnaie in-game (points, coins, gems…) (9)

- Pokémon GO Coins 15500 PokemonGO Manual Top-Up — `skip category: COINS`
- Apex Legends 23000 Coins Ea App Manual Top-Up — `skip category: COINS`
- Apex Legends 6700 Coins Ea App Manual Top-Up — `skip category: COINS`
- … 6 autres

### Cartes prépayées / gift cards / wallets (24)

- Tinder Plus 6 Months Tinder Manual Top-Up — `skip category: TOP UP`
- Tinder Gold 1 Month Tinder Manual Top-Up — `skip category: TOP UP`
- Tinder Platinum 1 Month Tinder Manual Top-Up — `skip category: TOP UP`
- … 21 autres

### Passes in-game (Battle Pass, Game Pass…) (2)

- Far Cry 6 Game of the Year Upgrade Pass Steam Altergift — `skip category: PASS (in-game/battle pass)`
- Tom Clancy's Rainbow Six Siege - Year 5 Pass Europe Ubisoft Connect CD Key — `skip category: PASS (in-game/battle pass)`

### Abonnements (6)

- Duolingo Super Subscription 12 Months Europe Duolingo CD Key — `skip category: SUBSCRIPTION`
- Crunchyroll Mega Fan Subscription 1 Month Crunchyroll Manual Top-Up — `skip category: SUBSCRIPTION`
- Duolingo Super Subscription 12 Months Duolingo CD Key — `skip category: SUBSCRIPTION`
- … 3 autres

### Régions verrouillées interdites (59)

- ASTRONEER Suit Bundle North America Steam CD Key — `forbidden region: NORTH AMERICA`
- Sonic Origins - Plus Expansion Pack North America Steam Altergift — `forbidden region: NORTH AMERICA`
- Mifinity eVoucher 900 ZAR South Africa Mifinity CD Key — `forbidden region: AFRICA`
- … 56 autres

### Édition / variante absente de la page AKS (55)

Motifs exacts : different/expanded product (54), edition 'Complete' (1).

- Lies of P - Deluxe Edition Upgrade Steam CD Key — `different/expanded product — extra words: ['UPGRADE']`
- Dune: Awakening - The Water Wars Europe Steam CD Key — `different/expanded product — extra words: ['WATER', 'WARS']`
- Dune: Awakening - The Water Wars Steam CD Key — `different/expanded product — extra words: ['WATER', 'WARS']`
- … 52 autres

### Page AKS trouvée mais nom différent (5)

- Yu-Gi-Oh! Waking the Dragons: Joey’s Journey Europe Steam CD Key — `name mismatch, missing AKS words: ['JOEYS']`
- Yu-Gi-Oh! Waking the Dragons: Yugi’s Journey Europe Steam CD Key — `name mismatch, missing AKS words: ['YUGIS']`
- Final Fantasy II Steam CD Key — `name mismatch, missing AKS words: ['PIXEL', 'REMASTER']`
- … 2 autres

### Page AKS sans carte d'éditions (3)

- Ambrosia Sky Steam CD Key — `AKS page carries no editions map — edition unverifiable (R19)`
- Goblin Vyke: The Thief Tycoon Steam CD Key — `AKS page carries no editions map — edition unverifiable (R19)`
- Goblin Vyke: The Thief Tycoon Steam CD Key — `AKS page carries no editions map — edition unverifiable (R19)`

### Autres (13)

Motifs exacts : skip category (9), preorder bonus (2), no region id for STEAM/GIFT UK (1), no region id for EPIC/US (1).

- Killing Floor 3 + Pre-Order Bonus Steam CD Key — `preorder bonus`
- Killing Floor 3 + Pre-Order Bonus Europe Steam CD Key — `preorder bonus`
- Wirm Steam Account — `skip category: STEAM ACCOUNT`
- … 10 autres
