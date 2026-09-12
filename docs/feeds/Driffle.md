# État du feed — Driffle (store 127)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020000-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:58 UTC (58 min)
- **Pages parcourues** : 6 — 509 offres vues, 1 candidats, **1 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 33 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-10 | 7 |
| 2026-08-26 | 1 |
| 2026-08-27 | 1 |
| 2026-09-01 | 10 |
| 2026-09-08 | 1 |
| 2026-09-09 | 3 |
| 2026-09-11 | 9 |
| 2026-09-12 | 1 |

| Édition saisie | Offres |
|---|---|
| Standard | 19 |
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
| Steam (2) | 13 |
| Steam EU (9) | 12 |
| Publisher (1) | 8 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260810-145249-auto` | 2026-08-10 14:52 UTC | 17 | 1635 | 7 | 7 | — |
| `20260909-121458-auto` | 2026-09-09 12:14 UTC | 5 | 498 | 7 | 3 | Gamivo: coverage_incomplete_max_pages (feed has 55 pages) |
| `20260911-155254-auto` | 2026-09-11 15:52 UTC | 1 | 0 | 0 | 0 | extract_failed_p1 |
| `20260911-160132-auto` | 2026-09-11 16:01 UTC | 6 | 505 | 9 | 9 | — |
| `20260912-020000-auto` | 2026-09-12 02:00 UTC | 6 | 509 | 1 | 1 | — |

### Offres créées au dernier passage (1)

- The Blood of Dawnwalker (Global) (PC) - Steam - Digital Key → `the-blood-of-dawnwalker-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

508 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 124 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 164 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 20 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 77 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 47 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 21 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 2 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Abonnements | 11 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Régions verrouillées interdites | 18 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 18 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 2 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Rockstar sans région | 1 | plateforme Rockstar sans bucket de région AKS | à apprendre |
| Autres | 3 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (124)

- Sniper Ghost Warrior Contracts 1 and 2 Double Pack (Europe) (Xbox One / Xbox Series X\|S) - Xbox Live - Digital Key — `console`
- NBA 2K27 - 15000 VC (Global) (Xbox Series X\|S) - Xbox Live - Digital Key — `console`
- Fortnite - Fresh Aura Outfits + 1,000 V-Bucks DLC (Global) (Xbox One / Xbox Series X\|S) - Xbox Live - Digital Key — `console`
- … 121 autres

### Sans page produit AKS (164)

- Fallout 76 Gone Fission Deluxe Edition (Europe) (PC) - Steam - Digital Key — `no AKS product page found (slug not 200)`
- Tom Clancy's Rainbow Six Siege Account with 15-25 Operators (Global) (PC) - Ubisoft Connect Account — `no AKS product page found (slug not 200)`
- Tom Clancy's Rainbow Six Siege Account with 45-55 Operators (Global) (PC) - Ubisoft Connect Account — `no AKS product page found (slug not 200)`
- … 161 autres

### DLC sans page AKS propre (20)

Motifs exacts : DLC in title but AKS page 'world-of-warcraft' carries no DLC edition (11), DLC in title but AKS page 'fortnite' carries no DLC edition (2), DLC in title but AKS page 'the-elder-scrolls-online' carries no DLC edition (2), DLC in title but AKS page 'lego-horizon-adventures' carries no DLC edition (1), DLC in title but AKS page 'the-immortal-john-triptych' carries no DLC edition (1), DLC in title but AKS page 'panzer-corps-2' carries no DLC edition (1).

- Fortnite - Ghost Monks Outfit DLC (Europe) (PC) - Epic Games - Digital Key — `DLC in title but AKS page 'fortnite' carries no DLC edition — base game or wrong product, not entered (R43)`
- LEGO Horizon Adventures - Upgrade to Digital Deluxe Edition DLC (Global) (PC) - Steam - Digital Key — `DLC in title but AKS page 'lego-horizon-adventures' carries no DLC edition — base game or wrong product, not e`
- Fortnite - Moon Bounce Emote DLC (Global) (PC) - Epic Games - Digital Key — `DLC in title but AKS page 'fortnite' carries no DLC edition — base game or wrong product, not entered (R43)`
- … 17 autres

### Bundles / packs multi-jeux (77)

Motifs exacts : skip category (58), possible multi-game bundle (19).

- Valorant Account 1-5 Skins AP Region Server (Global) (PC) - Valorant Account — `skip category: SKIN (no bundles/skins)`
- Tom Clancy's Rainbow Six Siege Account with 30-45 Total Skins (Global) (PC) - Ubisoft Connect Account — `skip category: SKIN (no bundles/skins)`
- Tom Clancy's Rainbow Six Siege Account with 80-100 Total Skins (Global) (PC) - Ubisoft Connect Account — `skip category: SKIN (no bundles/skins)`
- … 74 autres

### Monnaie in-game (points, coins, gems…) (47)

- Farlight 84 - 5 Diamonds — `skip category: DIAMONDS`
- Delta Force - 19440 + 4860 Delta Coins — `skip category: COINS`
- Delta Force - 6480 + 1620 Delta Coins — `skip category: COINS`
- … 44 autres

### Cartes prépayées / gift cards / wallets (21)

- Rewarble Patreon 190 USD Gift Card (Global) - Rewarble - Digital Key — `skip category: GIFT CARD`
- Rewarble Patreon 9 USD Gift Card (Global) - Rewarble - Digital Key — `skip category: GIFT CARD`
- Rewarble VISA 40 EUR Gift Card (Global) - Rewarble - Digital Key — `skip category: GIFT CARD`
- … 18 autres

### Passes in-game (Battle Pass, Game Pass…) (2)

- Arena Breakout - Advanced Battle Pass — `skip category: PASS (in-game/battle pass)`
- Arena Breakout - Premium Battle Pass — `skip category: PASS (in-game/battle pass)`

### Abonnements (11)

- Amazon Prime 1 Month Online Membership (Global) - Amazon Account — `skip category: MEMBERSHIP`
- Tinder Gold 1 Month Subscription (Belgium) - Digital Key — `skip category: SUBSCRIPTION`
- Tinder Gold 1 Month Subscription (Austria) - Digital Key — `skip category: SUBSCRIPTION`
- … 8 autres

### Régions verrouillées interdites (18)

- DRAGON BALL Sparking! ZERO (United States / Canada) (PC) - Steam - Digital Key — `forbidden region: CANADA`
- League of Legends Account Level 30+ Brazil Server (Global) (PC) - League of Legends Account — `forbidden region: BRAZIL`
- MARVEL Tōkon Fighting Souls Ultimate Edition (Asia) (PC) - Steam - Digital Key — `forbidden region: ASIA`
- … 15 autres

### Édition / variante absente de la page AKS (18)

- Fatal Fury City of the Wolves - Legend Edition (Europe) (PC) - Steam - Digital Key — `different/expanded product — extra words: ['LEGEND']`
- Far Cry 2 (Global) (PC) - Ubisoft Connect Account — `different/expanded product — extra words: ['ACCOUNT']`
- Fortnite - 12500 V-Bucks Card (France) - Epic Games - Digital Key — `different/expanded product — extra words: ['12500', 'V', 'BUCKS', 'CARD', 'FRANCE']`
- … 15 autres

### Page AKS trouvée mais nom différent (2)

- FINAL FANTASY (Global) (PC) - Steam Gift — `name mismatch, missing AKS words: ['PIXEL', 'REMASTER']`
- FINAL FANTASY (Global) (PC) - Steam Gift — `name mismatch, missing AKS words: ['PIXEL', 'REMASTER']`

### Rockstar sans région (1)

- Grand Theft Auto Vice City (Global) (PC) - Rockstar - Digital Key — `no region id for ROCKSTAR/GLOBAL`

### Autres (3)

Motifs exacts : no region id for EPIC/US (1), skip category (1), preorder bonus (1).

- Fortnite - Ghost Monks Outfit DLC (United States) (PC) - Epic Games - Digital Key — `no region id for EPIC/US`
- McAfee AntiVirus Plus (Global) - 10 Devices 1 Year - Digital Key — `skip category: ANTIVIRUS`
- Need for Speed Unbound Pre-Order Bonus DLC (EN) (Global) (PC) - EA Play - Digital Key — `preorder bonus`
