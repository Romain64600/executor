# État du feed — G2A (store 38)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020001-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:47 UTC (47 min)
- **Pages parcourues** : 10 — 1000 offres vues, 1 candidats, **1 créées**
- **Issue** : aucune halte, couverture : `incomplete_max_pages (feed has 37 pages)`
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 100 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-10 | 24 |
| 2026-08-25 | 1 |
| 2026-09-07 | 4 |
| 2026-09-08 | 1 |
| 2026-09-11 | 64 |
| 2026-09-12 | 1 |
| tria-ge--e | 5 |

| Édition saisie | Offres |
|---|---|
| Standard | 64 |
| DLC | 22 |
| Deluxe | 8 |
| Gold | 2 |
| Complete | 2 |
| Supporter Edition | 1 |
| Ultimate | 1 |

| Région saisie | Offres |
|---|---|
| Steam (2) | 56 |
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
| `20260912-020001-auto` | 2026-09-12 02:00 UTC | 10 | 1000 | 1 | 1 | — |

### Offres créées au dernier passage (1)

- Seafrog (PC) - Steam Key - GLOBAL → `seafrog-cd-key-compare-prices` (Standard, Steam (2))

## Ce qui reste dans le feed et pourquoi

999 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 47 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 246 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 2 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 84 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 1 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Cartes prépayées / gift cards / wallets | 4 | hors périmètre (prepaids) | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 5 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Abonnements | 3 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Microsoft Store | 3 | plateforme Microsoft sans correspondance de région AKS | à apprendre |
| Régions verrouillées interdites | 196 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 25 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 6 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Plateforme non vérifiable | 349 | pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20) | vérifier à la main |
| Logiciels | 3 | édition / région logicielle non résolue sur la page AKS (R31) | vérifier à la main |
| Page AKS sans carte d'éditions | 6 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Autres | 19 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (47)

- Shadowrun Trilogy (Xbox Series X/S) - Xbox Live Key - EUROPE — `console`
- Jurassic World Evolution: Expansion Collection (Xbox One) - Xbox Live Key - EUROPE — `console`
- Train Sim World 6 \| Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM — `console`
- … 44 autres

### Sans page produit AKS (246)

- Komplete 26 Select \| Beats (PC, Mac) (1 Device, Lifetime) - Native Instruments Key - GLOBAL — `no AKS product page found (slug not 200)`
- Murder Mystery 2 Icewing - Roblox Player Trade - GLOBAL — `no AKS product page found (slug not 200)`
- Murder Mystery 2 Sakura Knife - Roblox Player Trade - GLOBAL — `no AKS product page found (slug not 200)`
- … 243 autres

### DLC sans page AKS propre (2)

Motifs exacts : DLC in title but AKS page 'before-exit-gas-station' carries no DLC edition (1), SEASON PASS in title but AKS page 'paladins-season-pass-2022' carries no DLC edition (1).

- Before Exit: Gas Station - Midnight DLC (PC) - Steam Key - GLOBAL — `DLC in title but AKS page 'before-exit-gas-station' carries no DLC edition — base game or wrong product, not e`
- Paladins Season Pass 2022 (PC) - Steam Gift - GLOBAL — `SEASON PASS in title but AKS page 'paladins-season-pass-2022' carries no DLC edition — base game or wrong prod`

### Bundles / packs multi-jeux (84)

Motifs exacts : skip category (83), possible multi-game bundle (1).

- Lightyear Frontier: Supporter Pack: Pioneer Bundle (PC) - Steam Key - EUROPE — `skip category: BUNDLE (no bundles/skins)`
- Lightyear Frontier: Supporter Pack: Pioneer Bundle (PC) - Steam Key - GLOBAL — `skip category: BUNDLE (no bundles/skins)`
- Heileen Bundle Steam Gift EUROPE — `skip category: BUNDLE (no bundles/skins)`
- … 81 autres

### Monnaie in-game (points, coins, gems…) (1)

- Train Valley 2: Workshop Gems - Onyx (PC) - Steam Key - GLOBAL — `skip category: GEMS`

### Cartes prépayées / gift cards / wallets (4)

- VALORANT Gift Card 45.98 SGD - Riot Key - SINGAPORE — `skip category: GIFT CARD`
- Perplexity Manual Top-Up - Max 1 Month - Perplexity - GLOBAL — `skip category: TOP UP`
- Perplexity Manual Top-Up - Pro 1 Year - Perplexity - GLOBAL — `skip category: TOP UP`
- … 1 autres

### Passes in-game (Battle Pass, Game Pass…) (5)

- Insurgency: Sandstorm - Year 2 Pass (PC) - Steam Gift - GLOBAL — `skip category: PASS (in-game/battle pass)`
- Insurgency: Sandstorm - Year 2 Pass (PC) - Steam Gift - GLOBAL — `skip category: PASS (in-game/battle pass)`
- ONE PIECE: PIRATE WARRIORS 4 - Character Pass (PC) - Steam Gift - GLOBAL — `skip category: PASS (in-game/battle pass)`
- … 2 autres

### Abonnements (3)

- Nastia AI Membership Basic 12 Months - NastiaAI Key - GLOBAL — `skip category: MEMBERSHIP`
- Nastia AI Membership Unlimited 12 Months - NastiaAI Key - GLOBAL — `skip category: MEMBERSHIP`
- Nastia AI Membership Unlimited 12 Months - NastiaAI Key - GLOBAL — `skip category: MEMBERSHIP`

### Microsoft Store (3)

- Mafia: Definitive Edition (PC) - Microsoft Store Account - GLOBAL — `skip category: MICROSOFT STORE`
- Minecraft Dungeons II \| Deluxe Edition (PC) - Microsoft Store Key - GLOBAL — `skip category: MICROSOFT STORE`
- Call of Duty: Black Ops 6 - Vault Edition Upgrade (PC) - Microsoft Store Key - GLOBAL — `skip category: MICROSOFT STORE`

### Régions verrouillées interdites (196)

- Idle Colony (PC) - Steam Key - NORTH AMERICA — `forbidden region: NORTH AMERICA`
- Halloween: The Game (PC) - Steam Key - NORTH AMERICA — `forbidden region: NORTH AMERICA`
- Norton 360 Platinum (20 Devices, 1 Year) - Norton Key - CANADA — `forbidden region: CANADA`
- … 193 autres

### Édition / variante absente de la page AKS (25)

- Dungeon Defenders II - Celestial Vault Pack (PC) - Steam Key - GLOBAL — `different/expanded product — extra words: ['CELESTIAL', 'VAULT']`
- Age of Empires III: Definitive Edition - The Baltic Powers (PC) - Steam Key - GLOBAL — `different/expanded product — extra words: ['BALTIC', 'POWERS']`
- DJMAX RESPECT V - V LIBERTY V PACK (PC) - Steam Key - GLOBAL — `different/expanded product — extra words: ['LIBERTY']`
- … 22 autres

### Page AKS trouvée mais nom différent (6)

- Cafe Stella and the Reaper's Butterflies (PC) - Steam Key - GLOBAL — `name mismatch, missing AKS words: ['CAF']`
- Cafe Stella and the Reaper's Butterflies (PC) - Steam Key - EUROPE — `name mismatch, missing AKS words: ['CAF']`
- It's Quiz Time Steam Gift EUROPE — `name mismatch, missing AKS words: ['ITS']`
- … 3 autres

### Plateforme non vérifiable (349)

- Mia's Hunt (PC) - Steam Gift - GLOBAL — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- Steam Squad Steam Gift GLOBAL — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- Fort Defense - Atlantic Ocean Steam Gift GLOBAL — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- … 346 autres

### Logiciels (3)

- Gecata by Movavi 5 - Game Recording Software (PC) - Steam Gift - GLOBAL — `software edition unresolved on the AKS page (1 editions, none in title) — not guessed (R31)`
- Gecata by Movavi 5 - Game Recording Software (PC) - Steam Gift - EUROPE — `software edition unresolved on the AKS page (1 editions, none in title) — not guessed (R31)`
- Gecata by Movavi 5 - Game Recording Software (PC) - Steam Gift - GLOBAL — `software edition unresolved on the AKS page (1 editions, none in title) — not guessed (R31)`

### Page AKS sans carte d'éditions (6)

- WAKFU - Excarnus Pack Steam Gift GLOBAL — `AKS page carries no editions map — edition unverifiable (R19)`
- Ecco the Dolphin Steam Gift GLOBAL — `AKS page carries no editions map — edition unverifiable (R19)`
- Tiny Thief Steam Gift GLOBAL — `AKS page carries no editions map — edition unverifiable (R19)`
- … 3 autres

### Autres (19)

Motifs exacts : skip category (10), no region id for PUBLISHER/GIFT (9).

- Gunman Contracts: Stand Alone (PC) - Steam Account - GLOBAL — `skip category: STEAM ACCOUNT`
- Pillars of Eternity II: Deadfire (PC) - Steam Account - GLOBAL — `skip category: STEAM ACCOUNT`
- Police Tactics: Imperio (PC) - Steam Account - GLOBAL — `skip category: STEAM ACCOUNT`
- … 16 autres
