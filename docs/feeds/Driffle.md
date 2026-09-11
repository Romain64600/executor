# État du feed — Driffle (store 127)

_Généré le 2026-09-11 16:19 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260911-160132-auto` — du 2026-09-11 16:01 UTC au 2026-09-11 16:18 UTC (17 min)
- **Pages parcourues** : 6 — 505 offres vues, 9 candidats, **9 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 32 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-10 | 7 |
| 2026-08-26 | 1 |
| 2026-08-27 | 1 |
| 2026-09-01 | 10 |
| 2026-09-08 | 1 |
| 2026-09-09 | 3 |
| 2026-09-11 | 9 |

| Édition saisie | Offres |
|---|---|
| Standard | 18 |
| Deluxe | 3 |
| Knights Editon | 1 |
| 499 Frost Stars | 1 |
| 999 Frost Stars | 1 |
| 299 Frost Stars | 1 |
| 4999 Frost Stars | 1 |
| 1999 Frost Stars | 1 |
| 99 Frost Stars | 1 |
| 9999 Frost Stars | 1 |
| … 3 autres | 3 |

| Région saisie | Offres |
|---|---|
| Steam EU (9) | 12 |
| Steam (2) | 12 |
| Publisher (1) | 8 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260810-145249-auto` | 2026-08-10 14:52 UTC | 17 | 1635 | 7 | 7 | — |
| `20260909-121458-auto` | 2026-09-09 12:14 UTC | 5 | 498 | 7 | 3 | Gamivo: coverage_incomplete_max_pages (feed has 55 pages) |
| `20260911-155254-auto` | 2026-09-11 15:52 UTC | 1 | 0 | 0 | 0 | extract_failed_p1 |
| `20260911-160132-auto` | 2026-09-11 16:01 UTC | 6 | 505 | 9 | 9 | — |

### Offres créées au dernier passage (9)

- The Spirit and the Mouse (Europe) (PC / Mac) - Steam - Digital Key → `the-spirit-and-the-mouse-cd-key-compare-prices` (Standard, Steam EU (9))
- Nightmare Frontier (Global) (PC) - Steam - Digital Key → `nightmare-frontier-cd-key-compare-prices` (Standard, Steam (2))
- Goat Simulator 3 - Multiverse of Nonsense DLC (Global) (PC) - Steam - Digital Key → `goat-simulator-3-multiverse-of-nonsense-cd-key-compare-prices` (DLC, Steam (2))
- Stygian Outer Gods (Europe) (PC) - Steam - Digital Key → `stygian-outer-gods-cd-key-compare-prices` (Standard, Steam EU (9))
- Tennis Manager 2022 (Europe) (PC / Mac) - Steam - Digital Key → `tennis-manager-2022-cd-key-compare-prices` (Standard, Steam EU (9))
- Cthulhu's Reach - Devil Reef (Global) (PC) - Steam - Digital Key → `cthulhus-reach-devil-reef-cd-key-compare-prices` (Standard, Steam (2))
- Fatal Fury City of the Wolves (Europe) (PC) - Steam - Digital Key → `fatal-fury-city-of-the-wolves-cd-key-compare-prices` (Standard, Steam EU (9))
- Fatal Fury City of the Wolves (Global) (PC) - Steam - Digital Key → `fatal-fury-city-of-the-wolves-cd-key-compare-prices` (Standard, Steam (2))
- Microsoft Flight Simulator 2024 - Deluxe Edition (Europe) (PC) - Steam - Digital Key → `microsoft-flight-simulator-2024-cd-key-compare-prices` (Deluxe, Steam EU (9))

## Ce qui reste dans le feed et pourquoi

496 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 122 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 158 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 20 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 75 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 47 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 14 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 2 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Abonnements | 11 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Régions verrouillées interdites | 15 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 21 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 2 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Rockstar sans région | 1 | plateforme Rockstar sans bucket de région AKS | à apprendre |
| Sonde AKS non fiable (transitoire) | 5 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Autres | 3 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (122)

- Fortnite - Fresh Aura Outfits + 1,000 V-Bucks DLC (Global) (Xbox One / Xbox Series X\|S) - Xbox Live - Digital Key — `console`
- Fortnite - Fresh Aura Outfits + 1,000 V-Bucks DLC (Europe) (Xbox One / Xbox Series X\|S) - Xbox Live - Digital Key — `console`
- Fortnite - Fresh Aura Outfits + 1,000 V-Bucks DLC (United States) (Xbox One / Xbox Series X\|S) - Xbox Live - Digital Key — `console`
- … 119 autres

### Sans page produit AKS (158)

- Tom Clancy's Rainbow Six Siege Account with 15-25 Operators (Global) (PC) - Ubisoft Connect Account — `no AKS product page found (slug not 200)`
- Tom Clancy's Rainbow Six Siege Account with 35-45 Operators (Global) (PC) - Ubisoft Connect Account — `no AKS product page found (slug not 200)`
- Rocket League Account Level 50+ (Global) (PC) - Epic Games Account — `no AKS product page found (slug not 200)`
- … 155 autres

### DLC sans page AKS propre (20)

Motifs exacts : DLC in title but AKS page 'world-of-warcraft' carries no DLC edition (11), DLC in title but AKS page 'fortnite' carries no DLC edition (2), DLC in title but AKS page 'the-elder-scrolls-online' carries no DLC edition (2), DLC in title but AKS page 'lego-horizon-adventures' carries no DLC edition (1), DLC in title but AKS page 'the-immortal-john-triptych' carries no DLC edition (1), DLC in title but AKS page 'panzer-corps-2' carries no DLC edition (1).

- Fortnite - Ghost Monks Outfit DLC (Europe) (PC) - Epic Games - Digital Key — `DLC in title but AKS page 'fortnite' carries no DLC edition — base game or wrong product, not entered (R43)`
- LEGO Horizon Adventures - Upgrade to Digital Deluxe Edition DLC (Global) (PC) - Steam - Digital Key — `DLC in title but AKS page 'lego-horizon-adventures' carries no DLC edition — base game or wrong product, not e`
- Fortnite - Moon Bounce Emote DLC (Global) (PC) - Epic Games - Digital Key — `DLC in title but AKS page 'fortnite' carries no DLC edition — base game or wrong product, not entered (R43)`
- … 17 autres

### Bundles / packs multi-jeux (75)

Motifs exacts : skip category (56), possible multi-game bundle (19).

- Valorant Account 1-5 Skins AP Region Server (Global) (PC) - Valorant Account — `skip category: SKIN (no bundles/skins)`
- Tom Clancy's Rainbow Six Siege Account with 30-45 Total Skins (Global) (PC) - Ubisoft Connect Account — `skip category: SKIN (no bundles/skins)`
- Tom Clancy's Rainbow Six Siege Account with 15-30 Total Skins (Global) (PC) - Ubisoft Connect Account — `skip category: SKIN (no bundles/skins)`
- … 72 autres

### Monnaie in-game (points, coins, gems…) (47)

- Farlight 84 - 5 Diamonds — `skip category: DIAMONDS`
- Delta Force - 19440 + 4860 Delta Coins — `skip category: COINS`
- Delta Force - 6480 + 1620 Delta Coins — `skip category: COINS`
- … 44 autres

### Cartes prépayées / gift cards / wallets (14)

- Rewarble Patreon 35 USD Gift Card (Global) - Rewarble - Digital Key — `skip category: GIFT CARD`
- Rewarble VISA 130 EUR Gift Card (Global) - Rewarble - Digital Key — `skip category: GIFT CARD`
- Rewarble VISA 140 EUR Gift Card (Global) - Rewarble - Digital Key — `skip category: GIFT CARD`
- … 11 autres

### Passes in-game (Battle Pass, Game Pass…) (2)

- Arena Breakout - Advanced Battle Pass — `skip category: PASS (in-game/battle pass)`
- Arena Breakout - Premium Battle Pass — `skip category: PASS (in-game/battle pass)`

### Abonnements (11)

- Amazon Prime 1 Month Online Membership (Global) - Amazon Account — `skip category: MEMBERSHIP`
- Tinder Plus - 1 Month Subscription (Austria) - Digital Key — `skip category: SUBSCRIPTION`
- Tinder Gold 1 Month Subscription (Austria) - Digital Key — `skip category: SUBSCRIPTION`
- … 8 autres

### Régions verrouillées interdites (15)

- League of Legends Account Level 30+ Brazil Server (Global) (PC) - League of Legends Account — `forbidden region: BRAZIL`
- For The King II - Smoke and Steel Cosmetic Pack DLC (MENA) (PC) - Steam - Digital Key — `forbidden region: MENA`
- MARVEL Tōkon Fighting Souls Ultimate Edition (Asia) (PC) - Steam - Digital Key — `forbidden region: ASIA`
- … 12 autres

### Édition / variante absente de la page AKS (21)

- WARDOGS (MEA) (PC) - Steam - Digital Key — `different/expanded product — extra words: ['MEA']`
- Far Cry 2 (Global) (PC) - Ubisoft Connect Account — `different/expanded product — extra words: ['ACCOUNT']`
- Fortnite - 12500 V-Bucks Card (France) - Epic Games - Digital Key — `different/expanded product — extra words: ['12500', 'V', 'BUCKS', 'CARD', 'FRANCE']`
- … 18 autres

### Page AKS trouvée mais nom différent (2)

- FINAL FANTASY (Global) (PC) - Steam Gift — `name mismatch, missing AKS words: ['PIXEL', 'REMASTER']`
- FINAL FANTASY (Global) (PC) - Steam Gift — `name mismatch, missing AKS words: ['PIXEL', 'REMASTER']`

### Rockstar sans région (1)

- Grand Theft Auto Vice City (Global) (PC) - Rockstar - Digital Key — `no region id for ROCKSTAR/GLOBAL`

### Sonde AKS non fiable (transitoire) (5)

- Metro Franchise Pack (Global) (PC) - Steam - Digital Key — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Doom 3 Pack DLC (Global) (PC) - Steam - Digital Key — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- DCS MiG-15bis by Belsimtek DLC (Global) (PC) - Digital Key — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- … 2 autres

### Autres (3)

Motifs exacts : no region id for EPIC/US (1), skip category (1), preorder bonus (1).

- Fortnite - Ghost Monks Outfit DLC (United States) (PC) - Epic Games - Digital Key — `no region id for EPIC/US`
- McAfee AntiVirus Plus (Global) - 10 Devices 1 Year - Digital Key — `skip category: ANTIVIRUS`
- Need for Speed Unbound Pre-Order Bonus DLC (EN) (Global) (PC) - EA Play - Digital Key — `preorder bonus`
