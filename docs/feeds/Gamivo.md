# État du feed — Gamivo (store 51)

_Généré le 2026-09-11 20:29 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260911-183000-auto` — du 2026-09-11 18:34 UTC au 2026-09-11 19:12 UTC (37 min)
- **Pages parcourues** : 26 — 2524 offres vues, 4 candidats, **4 créées**
- **Issue** : aucune halte
- **Non créées** : aucune (toutes les tentatives ont abouti)

## Offres ajoutées (cumul, tous passages)

**Total : 10 offres créées** (sweeps safe-auto + saisies par URLs).

| Jour | Créées |
|---|---|
| 2026-08-10 | 3 |
| 2026-09-09 | 1 |
| 2026-09-11 | 6 |

| Édition saisie | Offres |
|---|---|
| Standard | 8 |
| Collection | 1 |
| Premium | 1 |

| Région saisie | Offres |
|---|---|
| Publisher (1) | 10 |

Historique des passages :

| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |
|---|---|---|---|---|---|---|
| `20260810-154709-auto` | 2026-08-10 15:47 UTC | 59 | 5890 | 3 | 3 | coverage_incomplete_feed_grew (59→60 pages) |
| `20260909-121458-auto` | 2026-09-09 12:14 UTC | 30 | 3000 | 3 | 1 | coverage_incomplete_max_pages (feed has 55 pages) |
| `20260911-162000-auto` | 2026-09-11 16:14 UTC | 1 | 100 | 0 | 0 | match_failed_p30 |
| `20260911-162100-auto` | 2026-09-11 16:17 UTC | 30 | 3000 | 2 | 2 | — |
| `20260911-183000-auto` | 2026-09-11 18:34 UTC | 26 | 2524 | 4 | 4 | — |

### Offres créées au dernier passage (4)

- My Hero One's Justice 2 United States → `my-hero-ones-justice-2-cd-key-compare-prices` (Standard, Publisher (1))
- Age of Empires II Definitive Edition United States → `age-of-empires-2-definitive-edition-cd-key-compare-prices` (Standard, Publisher (1))
- Farming Simulator 15 United States → `farming-simulator-15-cd-key-compare-prices` (Standard, Publisher (1))
- Stronghold HD United States → `stronghold-hd-cd-key-compare-prices` (Standard, Publisher (1))

## Ce qui reste dans le feed et pourquoi

2520 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 3 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 1466 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 124 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 163 | règle : on ne saisit jamais de bundle | décision Romain |
| Monnaie in-game (points, coins, gems…) | 61 | règle : jeux uniquement, pas de monnaie | décision Romain |
| Passes in-game (Battle Pass, Game Pass…) | 3 | ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis | — |
| Abonnements | 12 | hors périmètre pour l'instant | à apprendre (type « subscription » AKS) |
| Régions verrouillées interdites | 209 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 11 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Page AKS trouvée mais nom différent | 8 | la page atteinte n'est pas ce produit (R01), fail-safe | vérifier à la main |
| Plateforme non vérifiable | 65 | pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20) | vérifier à la main |
| Page AKS sans carte d'éditions | 8 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Sonde AKS non fiable (transitoire) | 3 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Remaster / HD / édition anniversaire sans page dédiée | 12 | qualificatif absent du nom AKS (R01b) | créer la page dédiée sur AKS |
| Autres | 372 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (3)

- Xbox Game Pass for PC 1 Month US  United States — `console`
- Xbox Game Pass for PC 1 Month US  United States — `console`
- Xbox Game Pass for PC 1 Month US  United States — `console`

### Sans page produit AKS (1466)

- WWE 2K24 Cross-Gen Edition EN United States — `no AKS product page found (slug not 200)`
- The Dark Pictures Anthology Man of Medan United States — `no AKS product page found (slug not 200)`
- Sea of Thieves 2024 Deluxe Edition EN Egypt — `no AKS product page found (slug not 200)`
- … 1463 autres

### DLC sans page AKS propre (124)

Motifs exacts : DLC in title but AKS page 'fortnite' carries no DLC edition (29), DLC in title but AKS page 'tom-clancys-the-division-2' carries no DLC edition (13), DLC in title but AKS page 'hitman-world-of-assassination' carries no DLC edition (12), DLC in title but AKS page 'call-of-duty-black-ops-6' carries no DLC edition (12), DLC in title but AKS page 'atomic-heart' carries no DLC edition (10), DLC in title but AKS page 'dungeon-defenders-2' carries no DLC edition (10).

- Sword Art Online Alicization Lycoris - Premium Pass DLC EN United States — `DLC in title but AKS page 'sword-art-online-alicization-lycoris' carries no DLC edition — base game or wrong p`
- Roguebook - The Art of Roguebook DLC Global — `DLC in title but AKS page 'roguebook' carries no DLC edition — base game or wrong product, not entered (R43)`
- Dragon's Dogma 2 - Superior Weapon Quartet DLC EN EU — `DLC in title but AKS page 'dragons-dogma-2' carries no DLC edition — base game or wrong product, not entered (`
- … 121 autres

### Bundles / packs multi-jeux (163)

Motifs exacts : skip category (158), possible multi-game bundle (5).

- CoD Call of Duty Modern Warfare III 2023 - 4 Hours Rank XP + 4 Hours Weapon XP DLC EN Global — `possible multi-game bundle`
- CoD Call of Duty Modern Warfare III 2023 - 5 Hours Rank XP + 5 Hours Weapon XP DLC EN Global — `possible multi-game bundle`
- Sea of Thieves - Kraken Classic Bundle DLC EN Global — `skip category: BUNDLE (no bundles/skins)`
- … 160 autres

### Monnaie in-game (points, coins, gems…) (61)

- eFootball 2023 12000 Coins — `skip category: COINS`
- eFootball 2023 2150 Coins — `skip category: COINS`
- eFootball 2023 5800 Coins — `skip category: COINS`
- … 58 autres

### Passes in-game (Battle Pass, Game Pass…) (3)

- SMITE - Season 9 Starter Pass EN Global — `skip category: PASS (in-game/battle pass)`
- SMITE - Season 9 Starter Pass EN Global — `skip category: PASS (in-game/battle pass)`
- SMITE - Season 9 Starter Pass EN Global — `skip category: PASS (in-game/battle pass)`

### Abonnements (12)

- RuneScape - 1 Month Membership + 420 RuneCoins EN Global — `skip category: MEMBERSHIP`
- RuneScape - 1 Month Membership + 420 RuneCoins EN Global — `skip category: MEMBERSHIP`
- RuneScape - 1 Month Membership + 420 RuneCoins EN Global — `skip category: MEMBERSHIP`
- … 9 autres

### Régions verrouillées interdites (209)

- Dragon's Dogma 2 North America — `forbidden region: NORTH AMERICA`
- Dragon's Dogma 2 Deluxe Edition North America — `forbidden region: NORTH AMERICA`
- Marvel's Spider-Man The City that Never Sleeps DLC EN North America — `forbidden region: NORTH AMERICA`
- … 206 autres

### Édition / variante absente de la page AKS (11)

- Destiny 2 - The Collection EN United Kingdom — `different/expanded product — extra words: ['KINGDOM']`
- Destiny 2 - The Collection EN United Kingdom — `different/expanded product — extra words: ['KINGDOM']`
- Destiny 2 - The Collection EN United Kingdom — `different/expanded product — extra words: ['KINGDOM']`
- … 8 autres

### Page AKS trouvée mais nom différent (8)

- Ranch Simulator United States — `name mismatch, missing AKS words: ['CD', 'KEY']`
- Ranch Simulator United States — `name mismatch, missing AKS words: ['CD', 'KEY']`
- Ranch Simulator United States — `name mismatch, missing AKS words: ['CD', 'KEY']`
- … 5 autres

### Plateforme non vérifiable (65)

- Naruto Shippuden Ultimate Ninja Storm Trilogy United States — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- My Hero One's Justice 2 - Season Pass 2 DLC United States — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- One Piece Pirate Warriors 4 United States — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- … 62 autres

### Page AKS sans carte d'éditions (8)

- Goblin Vyke The Thief Tycoon Global — `AKS page carries no editions map — edition unverifiable (R19)`
- Goblin Vyke The Thief Tycoon Global — `AKS page carries no editions map — edition unverifiable (R19)`
- Goblin Vyke The Thief Tycoon Global — `AKS page carries no editions map — edition unverifiable (R19)`
- … 5 autres

### Sonde AKS non fiable (transitoire) (3)

- Achievement Hunter Overdose EN Global — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Achievement Hunter Pharaoh EN Global — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Achievement Hunter Princess EN Global — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`

### Remaster / HD / édition anniversaire sans page dédiée (12)

- The Sinking City - Remastered EN United States — `dangerous qualifier absent from AKS name: REMASTERED`
- The Sinking City - Remastered EN United States — `dangerous qualifier absent from AKS name: REMASTERED`
- The Sinking City - Remastered EN United States — `dangerous qualifier absent from AKS name: REMASTERED`
- … 9 autres

### Autres (372)

Motifs exacts : language restriction (298), preorder bonus (72), no region id for STEAM/GIFT US (2).

- Yu-Gi-Oh! ZEXAL Dark Mist Saga DLC EN/DE/FR/IT/ES United States — `language restriction`
- Yu-Gi-Oh! GX Leaders DLC EN/DE/FR/IT/ES United States — `language restriction`
- Katamari Damacy Reroll EN/DE/FR/IT/JA/ES United States — `language restriction`
- … 369 autres
