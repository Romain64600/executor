# État du feed — MMOGA (store 12)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020001-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:47 UTC (47 min)
- **Pages parcourues** : 8 — 723 offres vues, 1 candidats, **1 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 1265 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-09-10 | 1052 |
| 2026-09-11 | 212 |
| 2026-09-12 | 1 |

| Édition saisie | Offres |
|---|---|
| Standard | 840 |
| DLC | 229 |
| Deluxe | 103 |
| Ultimate | 14 |
| Gold | 12 |
| Complete | 6 |
| Premium | 4 |
| Special | 4 |
| Legendary | 4 |
| Supporter Edition | 3 |
| … 42 autres | 46 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 1201 |
| Origin (3) | 19 |
| Ubisoft Global (50) | 15 |
| Steam EU (9) | 9 |
| Epic Store (80) | 9 |
| Publisher (1) | 5 |
| Epic Store EU (80eu) | 3 |
| Origin EU (3eu) | 2 |
| GOG Global (6) | 1 |
| Steam Gift (25) | 1 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260910-093606-auto` | 2026-09-10 09:36 UTC | 1 | 32 | 14 | 0 | submit_not_clean_p22 |
| `20260910-095032-auto` | 2026-09-10 09:50 UTC | 1 | 100 | 33 | 26 | submit_not_clean_p1 |
| `20260910-141557-auto` | 2026-09-10 14:15 UTC | 1 | 100 | 24 | 15 | — |
| `20260910-150236-auto` | 2026-09-10 15:02 UTC | 1 | 100 | 16 | 12 | — |
| `20260910-152531-auto` | 2026-09-10 15:25 UTC | 1 | 100 | 8 | 8 | — |
| `20260910-153443-auto` | 2026-09-10 15:34 UTC | 2 | 128 | 44 | 35 | submit_not_clean_p20 |
| `20260910-161854-auto` | 2026-09-10 16:18 UTC | 2 | 186 | 68 | 32 | submit_not_clean_p19 |
| `20260910-170123-auto` | 2026-09-10 17:01 UTC | 20 | 1953 | 938 | 922 | — |
| `20260911-083407-auto` | 2026-09-11 08:34 UTC | 10 | 936 | 10 | 10 | — |
| `20260911-125000-auto` | 2026-09-11 12:45 UTC | 1 | 0 | 0 | 0 | extract_failed_p1 |
| `20260911-130500-auto` | 2026-09-11 13:04 UTC | 10 | 926 | 204 | 202 | — |
| `20260912-020001-auto` | 2026-09-12 02:00 UTC | 8 | 723 | 1 | 1 | — |

### Offres créées au dernier passage (1)

- LEGO Batman 3 - Beyond Gotham - Season Pass → `lego-batman-3-beyond-gotham-season-pass-cd-key-compare-prices` (DLC, Steam (2))

## Ce qui reste dans le feed et pourquoi

722 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 388 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 177 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 21 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 23 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 10 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 3 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 5 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Microsoft Store | 5 | plateforme Microsoft sans correspondance de région AKS | à apprendre |
| Régions verrouillées interdites | 2 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 41 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 15 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Plateforme non vérifiable | 13 | pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20) | vérifier à la main |
| Logiciels | 8 | édition / région logicielle non résolue sur la page AKS (R31) | vérifier à la main |
| Page AKS sans carte d'éditions | 3 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Rockstar sans région | 2 | plateforme Rockstar sans bucket de région AKS | à apprendre |
| Sonde AKS non fiable (transitoire) | 5 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Région ambiguë (mot de région dans le nom du produit) | 1 | R44 : doute → skip | vérifier à la main |

### Consoles (Xbox / PlayStation / Switch) (388)

- Xbox Live Gold - 3 month subscription [EU] — `console`
- Nintendo eShop Card - 15 Euro — `console`
- Nintendo eShop Card - 25 Euro — `console`
- … 385 autres

### Sans page produit AKS (177)

- The Sims 3 - Generations (Addon) — `no AKS product page found (slug not 200)`
- The Sims 3 - Ambitions (Addon) — `no AKS product page found (slug not 200)`
- The Sims 3 Late Night Expansion Pack — `no AKS product page found (slug not 200)`
- … 174 autres

### DLC sans page AKS propre (21)

Motifs exacts : DLC in title but AKS page 'the-elder-scrolls-online' carries no DLC edition (4), DLC in title resolved through a less specific slug tier (2), DLC in title but AKS page 'blood-bowl-3' carries no DLC edition (2), DLC in title but AKS page 'taxi-life-a-city-driving-simulator' carries no DLC edition (2), DLC in title but AKS page 'le-mans-ultimate' carries no DLC edition (2), DLC in title but AKS page 'mount-blade-warband' carries no DLC edition (1).

- Mount & Blade Warband - Viking Conquest Reforged Edition (DLC) — `DLC in title but AKS page 'mount-blade-warband' carries no DLC edition — base game or wrong product, not enter`
- Railway Empire - Northern Europe (DLC) — `DLC in title but AKS page 'railway-empire' carries no DLC edition — base game or wrong product, not entered (R`
- Naruto to Boruto Shinobi Striker - Season Pass 5 DLC (Steam Key) - EU — `SEASON PASS in title but AKS page 'naruto-to-boruto-shinobi-striker' carries no DLC edition — base game or wro`
- … 18 autres

### Bundles / packs multi-jeux (23)

Motifs exacts : skip category (21), possible multi-game bundle (2).

- The Elder Scrolls Online + Morrowind — `possible multi-game bundle`
- Euro Truck Simulator 2 - Cargo Bundle (DLC) — `skip category: BUNDLE (no bundles/skins)`
- Dying Light - Shu Warrior Bundle (DLC) — `skip category: BUNDLE (no bundles/skins)`
- … 20 autres

### Monnaie in-game (points, coins, gems…) (10)

- 2000 Guild Wars 2 Gems Key — `skip category: GEMS`
- FIFA 22 - 2200 FUT Points [PC - Origin] — `skip category: POINTS`
- FIFA 23 - 2800 FUT Points [PC - Origin] — `skip category: POINTS`
- … 7 autres

### Cartes prépayées / gift cards / wallets (3)

- WoW - Gamecard Prepaid 60 days [EU] — `skip category: PREPAID`
- Valorant Gift Card 25 EUR — `skip category: GIFT CARD`
- Grand Theft Auto V Enhanced + Great White Shark Card Bundle Rockstar — `skip category: SHARK CARD`

### Passes in-game (Battle Pass, Game Pass…) (5)

- Max Payne 3 - Rockstar Pass — `skip category: PASS (in-game/battle pass)`
- Dragon Ball FighterZ - FighterZ Pass — `skip category: PASS (in-game/battle pass)`
- Street Fighter  6 - Year 1 Character Pass — `skip category: PASS (in-game/battle pass)`
- … 2 autres

### Microsoft Store (5)

- Minecraft Java & Bedrock Deluxe Collection (Microsoft Store / Windows Key) - EU — `skip category: MICROSOFT STORE`
- Minecraft - 1720 Minecoins (Microsoft Store / Windows Key) - EU — `skip category: MICROSOFT STORE`
- Minecraft - 3500 Minecoins (Microsoft Store / Windows Key) - EU — `skip category: MICROSOFT STORE`
- … 2 autres

### Régions verrouillées interdites (2)

- American Truck Simulator - New Mexico (DLC) — `forbidden region: MEXICO`
- Civilization VI - Maya & Gran Colombia Pack (DLC) — `forbidden region: COLOMBIA`

### Édition / variante absente de la page AKS (41)

Motifs exacts : different/expanded product (40), edition 'Deluxe' (1).

- Europa Universalis IV - EU4 — `different/expanded product — extra words: ['EU4']`
- Final Fantasy XIV A Realm Reborn - Gamecard 60 days — `different/expanded product — extra words: ['GAMECARD', '60', 'DAYS']`
- Hearts of Iron IV - Together for Victory (Expansion) — `different/expanded product — extra words: ['EXPANSION']`
- … 38 autres

### Page AKS trouvée mais nom différent (15)

- Brink (Uncut) — `name mismatch, missing AKS words: ['COMPARE', 'AND', 'BUY']`
- No Man's Sky — `name mismatch, missing AKS words: ['MANS']`
- Deus Ex Human Revolution - Director's Cut — `name mismatch, missing AKS words: ['DIRECTORS']`
- … 12 autres

### Plateforme non vérifiable (13)

Motifs exacts : no platform in title and AKS page does not confirm Direct Publisher (12), title says Epic Store but AKS official platforms exclude it (1).

- Destiny 2: Year of Prophecy — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- Disney Epic Mickey Rebrushed — `title says Epic Store but AKS official platforms exclude it (R20)`
- Dungeons of Hinterberg — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- … 10 autres

### Logiciels (8)

- Bitdefender Internet Security - 3 PC/1year — `software edition unresolved on the AKS page (12 editions, none in title) — not guessed (R31)`
- Mount & Blade — `software edition unresolved on the AKS page (6 editions, none in title) — not guessed (R31)`
- Kaspersky Standard (3 Devices / 1 Year) - EU — `software edition unresolved on the AKS page (8 editions, none in title) — not guessed (R31)`
- … 5 autres

### Page AKS sans carte d'éditions (3)

- Resident Evil 7 - Gold Edition — `AKS page carries no editions map — edition unverifiable (R19)`
- McAfee Total Protection Plus (3 Devices / 1 Year) — `AKS page carries no editions map — edition unverifiable (R19)`
- Helldivers 2 - Super Citizen Edition — `AKS page carries no editions map — edition unverifiable (R19)`

### Rockstar sans région (2)

- Grand Theft Auto IV - GTA 4 Complete Edition (Rockstar Key) — `no region id for ROCKSTAR/GLOBAL`
- Grand Theft Auto V Enhanced Edition Rockstar — `no region id for ROCKSTAR/GLOBAL`

### Sonde AKS non fiable (transitoire) (5)

- Avatar - Frontiers of Pandora (Ubisoft Connect Key) - EU — `AKS probe unreliable (throttled?): avatar -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com', por`
- The Witcher 3: Wild Hunt Remastered - GOG Key — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Football Manager 2027 (Steam) — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- … 2 autres

### Région ambiguë (mot de région dans le nom du produit) (1)

- Age of Empires III Definitive Edition - United States Civilization (DLC) — `region US read from 'UNITED STATES', which is part of the AKS product name 'Age of Empires 3 Definitive Editio`
