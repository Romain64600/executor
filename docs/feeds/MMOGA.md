# État du feed — MMOGA (store 12)

_Généré le 2026-09-11 15:06 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260911-083407-auto` — du 2026-09-11 08:34 UTC au 2026-09-11 08:54 UTC (20 min)
- **Pages parcourues** : 10 — 936 offres vues, 10 candidats, **10 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 1062 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-09-10 | 1052 |
| 2026-09-11 | 10 |

| Édition saisie | Offres |
|---|---|
| Standard | 840 |
| Deluxe | 103 |
| DLC | 26 |
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
| Steam (2) | 1018 |
| Ubisoft Global (50) | 11 |
| Epic Store (80) | 8 |
| Steam EU (9) | 7 |
| Origin (3) | 6 |
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

### Offres créées au dernier passage (10)

- Book of Demons → `book-of-demons-cd-key-compare-prices` (Standard, Steam (2))
- Age of Empires III - Definitive Edition (Steam Key) → `age-of-empires-3-definitive-edition-cd-key-compare-prices` (Standard, Steam (2))
- Wattam → `wattam-cd-key-compare-prices` (Standard, Steam (2))
- SWORD ART ONLINE Last Recollection - Deluxe Edition → `sword-art-online-last-recollection-cd-key-compare-prices` (Deluxe, Steam (2))
- Final Fantasy XIV - ENDWALKER → `final-fantasy-14-endwalker-cd-key-compare-prices` (DLC, Publisher (1))
- Square Dungeon 2 → `square-dungeon-2-cd-key-compare-prices` (Standard, Steam (2))
- Warhammer 40k Space Marine 2 - Gold Edition → `warhammer-40k-space-marine-2-cd-key-compare-prices` (Gold, Steam (2))
- Yakuza - Like a Dragon → `yakuza-like-a-dragon-cd-key-compare-prices` (Standard, Steam (2))
- Wild Bastards → `wild-bastards-cd-key-compare-prices` (Standard, Steam (2))
- The Jackbox Survey Scramble → `the-jackbox-survey-scramble-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

926 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 388 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 157 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 212 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 22 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 10 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 3 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 32 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Microsoft Store | 5 | plateforme Microsoft sans correspondance de région AKS | à apprendre |
| Régions verrouillées interdites | 2 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 53 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 13 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Plateforme non vérifiable | 13 | pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20) | vérifier à la main |
| Logiciels | 8 | édition / région logicielle non résolue sur la page AKS (R31) | vérifier à la main |
| Page AKS sans carte d'éditions | 3 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Rockstar sans région | 2 | plateforme Rockstar sans bucket de région AKS | à apprendre |
| Sonde AKS non fiable (transitoire) | 3 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |

### Consoles (Xbox / PlayStation / Switch) (388)

- Xbox Live Gold - 3 month subscription [EU] — `console`
- Nintendo eShop Card - 15 Euro — `console`
- Nintendo eShop Card - 25 Euro — `console`
- … 385 autres

### Sans page produit AKS (157)

- The Sims 3 - Generations (Addon) — `no AKS product page found (slug not 200)`
- The Sims 3 - Ambitions (Addon) — `no AKS product page found (slug not 200)`
- The Sims 3 Late Night Expansion Pack — `no AKS product page found (slug not 200)`
- … 154 autres

### DLC sans page AKS propre (212)

- Total War Attila - Empires of Sand Culture Pack (DLC) — `DLC in title`
- Stellaris - Plantoids Species Pack (DLC) — `DLC in title`
- Euro Truck Simulator 2 - Italia DLC — `DLC in title`
- … 209 autres

### Bundles / packs multi-jeux (22)

Motifs exacts : skip category (20), possible multi-game bundle (2).

- The Elder Scrolls Online + Morrowind — `possible multi-game bundle`
- Euro Truck Simulator 2 - Cargo Bundle (DLC) — `skip category: BUNDLE (no bundles/skins)`
- Dying Light - Shu Warrior Bundle (DLC) — `skip category: BUNDLE (no bundles/skins)`
- … 19 autres

### Monnaie in-game (points, coins, gems…) (10)

- 2000 Guild Wars 2 Gems Key — `skip category: GEMS`
- FIFA 22 - 2200 FUT Points [PC - Origin] — `skip category: POINTS`
- FIFA 23 - 2800 FUT Points [PC - Origin] — `skip category: POINTS`
- … 7 autres

### Cartes prépayées / gift cards / wallets (3)

- WoW - Gamecard Prepaid 60 days [EU] — `skip category: PREPAID`
- Valorant Gift Card 25 EUR — `skip category: GIFT CARD`
- Grand Theft Auto V Enhanced + Great White Shark Card Bundle Rockstar — `skip category: SHARK CARD`

### Passes in-game (Battle Pass, Game Pass…) (32)

- Max Payne 3 - Rockstar Pass — `skip category: PASS (in-game/battle pass)`
- Watch Dogs 2 - Season Pass — `skip category: SEASON PASS`
- LEGO Batman 3 - Beyond Gotham - Season Pass — `skip category: SEASON PASS`
- … 29 autres

### Microsoft Store (5)

- Minecraft Java & Bedrock Deluxe Collection (Microsoft Store / Windows Key) - EU — `skip category: MICROSOFT STORE`
- Minecraft - 1720 Minecoins (Microsoft Store / Windows Key) - EU — `skip category: MICROSOFT STORE`
- Minecraft - 3500 Minecoins (Microsoft Store / Windows Key) - EU — `skip category: MICROSOFT STORE`
- … 2 autres

### Régions verrouillées interdites (2)

- American Truck Simulator - New Mexico (DLC) — `forbidden region: MEXICO`
- Civilization VI - Maya & Gran Colombia Pack (DLC) — `forbidden region: COLOMBIA`

### Édition / variante absente de la page AKS (53)

Motifs exacts : different/expanded product (52), edition 'Deluxe' (1).

- The Sims 3: Showtime (Addon) — `different/expanded product — extra words: ['ADDON']`
- Europa Universalis IV - EU4 — `different/expanded product — extra words: ['EU4']`
- Final Fantasy XIV A Realm Reborn - Gamecard 60 days — `different/expanded product — extra words: ['GAMECARD', '60', 'DAYS']`
- … 50 autres

### Page AKS trouvée mais nom différent (13)

- Brink (Uncut) — `name mismatch, missing AKS words: ['COMPARE', 'AND', 'BUY']`
- No Man's Sky — `name mismatch, missing AKS words: ['MANS']`
- Deus Ex Human Revolution - Director's Cut — `name mismatch, missing AKS words: ['DIRECTORS']`
- … 10 autres

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

### Sonde AKS non fiable (transitoire) (3)

- Company of Heroes 3: Final Stand — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- The Lord of the Rings: War in the North - Legacy Edition — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- MARVEL Tōkon: Fighting Souls — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
