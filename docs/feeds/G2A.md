# État du feed — G2A (store 38)

_Généré le 2026-09-11 20:29 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260911-201147-auto` — du 2026-09-11 20:11 UTC au 2026-09-11 20:28 UTC (16 min)
- **Pages parcourues** : 7 — 620 offres vues, 8 candidats, **8 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 99 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-10 | 24 |
| 2026-08-25 | 1 |
| 2026-09-07 | 4 |
| 2026-09-08 | 1 |
| 2026-09-11 | 64 |
| tria-ge--e | 5 |

| Édition saisie | Offres |
|---|---|
| Standard | 63 |
| DLC | 22 |
| Deluxe | 8 |
| Gold | 2 |
| Complete | 2 |
| Supporter Edition | 1 |
| Ultimate | 1 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 55 |
| Steam EU (9) | 30 |
| Steam Gift EU (259) | 5 |
| Steam Gift (25) | 4 |
| Steam US (8) | 2 |
| Ubisoft EU (54) | 1 |
| Ubisoft US (55) | 1 |
| Ubisoft Global (50) | 1 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260810-091857-auto` | 2026-08-10 09:18 UTC | 10 | 988 | 24 | 24 | — |
| `20260911-161908-auto` | 2026-09-11 16:19 UTC | 30 | 3000 | 57 | 56 | — |
| `20260911-201147-auto` | 2026-09-11 20:11 UTC | 7 | 620 | 8 | 8 | — |

### Offres créées au dernier passage (8)

- Dragon Ball: Xenoverse 2 - Legendary Pack 1 (PC) - Steam Key - GLOBAL → `dragon-ball-xenoverse-2-legendary-pack-1-cd-key-compare-prices` (DLC, Steam (2))
- Microsoft Flight Simulator 2024 \| Premium Deluxe Edition (PC) - Steam Key - GLOBAL → `microsoft-flight-simulator-2024-cd-key-compare-prices` (Deluxe, Steam (2))
- Galactic Civilizations IV: Species Pack (PC) - Steam Key - GLOBAL → `galactic-civilizations-iv-species-pack-cd-key-compare-prices` (DLC, Steam (2))
- Microsoft Flight Simulator 2024 \| Premium Deluxe Edition (PC) - Steam Key - EUROPE → `microsoft-flight-simulator-2024-cd-key-compare-prices` (Deluxe, Steam EU (9))
- R-Type Dimensions III (PC) - Steam Key - GLOBAL → `r-type-dimensions-3-cd-key-compare-prices` (Standard, Steam (2))
- Final Fantasy XIV: Dawntrail (PC) - Steam Key - GLOBAL → `final-fantasy-14-dawntrail-cd-key-compare-prices` (DLC, Steam (2))
- Blackthorn Arena: Reforged - Shadow of Wuxia (PC) - Steam Key - GLOBAL → `blackthorn-arena-reforged-shadow-of-wuxia-cd-key-compare-prices` (DLC, Steam (2))
- C O S M Steam Key GLOBAL → `c-o-s-m-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

612 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 160 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 210 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| Bundles / packs multi-jeux | 72 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 59 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 20 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 8 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Abonnements | 2 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Microsoft Store | 14 | plateforme Microsoft sans correspondance de région AKS | à apprendre |
| Régions verrouillées interdites | 40 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 13 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 1 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Plateforme non vérifiable | 1 | pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20) | vérifier à la main |
| Page AKS sans carte d'éditions | 1 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Sonde AKS non fiable (transitoire) | 3 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Autres | 8 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (160)

- FINAL FANTASY XIV ONLINE COMPLETE COLLECTOR'S EDITION (Xbox Series X/S) - Xbox Live Key - EUROPE — `console`
- FINAL FANTASY XIII (Xbox One) - Xbox Live Key - EUROPE — `console`
- LIGHTNING RETURNS: FINAL FANTASY XIII (Xbox One) - Xbox Live Key - EUROPE — `console`
- … 157 autres

### Sans page produit AKS (210)

- Riot Access Code 788 HKD - Riot Key - HONG KONG — `no AKS product page found (slug not 200)`
- Riot Access Code 158 HKD - Riot Key - HONG KONG — `no AKS product page found (slug not 200)`
- Riot Access Code 78 HKD - Riot Key - HONG KONG — `no AKS product page found (slug not 200)`
- … 207 autres

### Bundles / packs multi-jeux (72)

Motifs exacts : skip category (50), possible multi-game bundle (22).

- The LEGO Games Bundle (PC) - Steam Gift - GLOBAL — `skip category: BUNDLE (no bundles/skins)`
- The LEGO Games Bundle (PC) - Steam Gift - EUROPE — `skip category: BUNDLE (no bundles/skins)`
- Call of Duty: Black Ops 7 - Exclusive Domino's Reward Set Bundle (All Devices) - Call of Duty Official Key - GLOBAL — `skip category: BUNDLE (no bundles/skins)`
- … 69 autres

### Monnaie in-game (points, coins, gems…) (59)

- MiocAI Pack 50 Credits - miocai Key - GLOBAL — `skip category: CREDITS`
- MiocAI Pack 250 Credits - miocai Key - GLOBAL — `skip category: CREDITS`
- MiocAI Pack 1000 Credits - miocai Key - GLOBAL — `skip category: CREDITS`
- … 56 autres

### Cartes prépayées / gift cards / wallets (20)

- Grand Theft Auto V Enhanced & Great White Shark Card Bundle (PC) - Microsoft Store Key - EUROPE — `skip category: SHARK CARD`
- Cryptocurrency: Wallets, Investing & Trading - Eduxpress Key - GLOBAL — `skip category: WALLET`
- Cryptonow Bitcoin Voucher 50 CHF - Cryptonow Key - SWITZERLAND — `skip category: VOUCHER`
- … 17 autres

### Passes in-game (Battle Pass, Game Pass…) (8)

- Mobile Legends: Bang Bang Twilight Pass - UNITED STATES — `skip category: PASS (in-game/battle pass)`
- Mobile Legends: Bang Bang Weekly Diamond Pass - UNITED STATES — `skip category: PASS (in-game/battle pass)`
- Lebara Data Pass S 1 Month - Lebara Data Key - FRANCE — `skip category: PASS (in-game/battle pass)`
- … 5 autres

### Abonnements (2)

- Audible Membership 1 Month - Audible Key - GLOBAL — `skip category: MEMBERSHIP`
- Alpha Academy Prime Membership Lifetime - Alpha Academy Key - GLOBAL — `skip category: MEMBERSHIP`

### Microsoft Store (14)

- Cataclismo (PC) - Microsoft Store Key - EUROPE — `skip category: MICROSOFT STORE`
- CALL OF DUTY: MODERN WARFARE \| Digital Standard Edition (PC) - Microsoft Store Key - EUROPE — `skip category: MICROSOFT STORE`
- Visual Studio 2017 \| Essential (PC) (1 PC, Lifetime) - Microsoft Key - GLOBAL — `skip category: MICROSOFT KEY`
- … 11 autres

### Régions verrouillées interdites (40)

- Breakout 13 \| Complete Edition (PC) - Steam Gift - NORTH AMERICA — `forbidden region: NORTH AMERICA`
- Cthulhu: The Cosmic Abyss (PC) - Steam Gift - NORTH AMERICA — `forbidden region: NORTH AMERICA`
- Farming Simulator 25 \| Beans & Alpacas Pre-Order Edition (PC) - Steam Key - EUROPE / NORTH AMERICA — `forbidden region: NORTH AMERICA`
- … 37 autres

### Édition / variante absente de la page AKS (13)

- Deck of Ashes - Print-Ready Posters (PC) - Steam Key - GLOBAL — `different/expanded product — extra words: ['PRINT', 'READY', 'POSTERS']`
- Total War: Warhammer III - Tides of Torment (PC) - Steam Key - EUROPE — `different/expanded product — extra words: ['TIDES', 'TORMENT']`
- Total War: Warhammer III - Thrones of Decay (PC) - Steam Gift - EUROPE — `different/expanded product — extra words: ['THRONES', 'DECAY']`
- … 10 autres

### Page AKS trouvée mais nom différent (1)

- Assassin's Creed Chronicles Trilogy (PC) - Epic Games Key - GLOBAL — `name mismatch, missing AKS words: ['ASSASSINS']`

### Plateforme non vérifiable (1)

- Resident Evil 2 (PC) - Steam Gift - GLOBAL — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`

### Page AKS sans carte d'éditions (1)

- Cannon Fodder 2 GOG.COM Key GLOBAL — `AKS page carries no editions map — edition unverifiable (R19)`

### Sonde AKS non fiable (transitoire) (3)

- Riot Access Code 24.99 USD - Riot Key - UNITED STATES — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- AcePDF Converter & Editor (PC, Mac) (1 Device, Lifetime) - AcePDF Key - GLOBAL — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Resident Evil 0 (PC) - Steam Key - UNITED STATES — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`

### Autres (8)

Motifs exacts : skip category (7), G2A green gift (1).

- Canva Business 1 Month - Canva Activation Link - GLOBAL — `skip category: ACTIVATION LINK`
- M4A4 \| Neo-Noir (Field-Tested) - Steam Player Trade - GLOBAL — `skip category: STEAM PLAYER TRADE`
- Glock-18 \| Water Elemental (Minimal Wear) - Steam Player Trade - GLOBAL — `skip category: STEAM PLAYER TRADE`
- … 5 autres
