# État du feed — Gamivo (store 51)

_Généré le 2026-09-12 02:59 UTC par `scripts/14_feed_status.py` à partir des runs sur disque ; régénérer après chaque passage._

## Dernier passage

- **Run** `20260912-020000-auto` — du 2026-09-12 02:00 UTC au 2026-09-12 02:58 UTC (58 min)
- **Pages parcourues** : 10 — 1000 offres vues, 0 candidats, **0 créées**
- **Issue** : aucune halte, couverture : `incomplete_max_pages (feed has 56 pages)`
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
| `20260912-020000-auto` | 2026-09-12 02:00 UTC | 10 | 1000 | 0 | 0 | — |

## Ce qui reste dans le feed et pourquoi

1000 offres écartées au dernier passage, par famille :

| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |
|---|---|---|---|
| Consoles (Xbox / PlayStation / Switch) | 3 | l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, consommée à la création) ; chantier mis en attente (2026-09-11) | modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3) |
| Sans page produit AKS | 407 | aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne pendant le passage) | créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique) |
| DLC sans page AKS propre | 33 | le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe sur la page du jeu de base, jamais saisie (R43) | créer la page du DLC sur AKS |
| Bundles / packs multi-jeux | 58 | règle : on ne saisit jamais de bundle | décision Romain |
| Cartes prépayées / gift cards / wallets | 16 | hors périmètre (prepaids) | décision Romain |
| Régions verrouillées interdites | 409 | région non vendue (RoW, LATAM, RU, TR…) | décision Romain |
| Édition / variante absente de la page AKS | 28 | le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16) | ajouter l'édition sur la page AKS, ou vérifier à la main |
| Plateforme non vérifiable | 11 | pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20) | vérifier à la main |
| Page AKS sans carte d'éditions | 1 | page AKS vide (stub), édition invérifiable (R19) | compléter la page sur AKS |
| Sonde AKS non fiable (transitoire) | 3 | AKS a répondu en erreur ou timeout pendant le passage | reprise automatique au passage suivant |
| Autres | 31 | voir le motif exact | — |

### Consoles (Xbox / PlayStation / Switch) (3)

- PlayStation Network Card PSN EUR CY €10 — `console`
- Nintendo eShop PLN PL 32zł — `console`
- Xbox Game Pass Premium 3 Months IN  India — `console`

### Sans page produit AKS (407)

- Silent Hill Townfall PRE-PURCHASE Global — `no AKS product page found (slug not 200)`
- Minecraft Dungeons II PRE-PURCHASE Deluxe Edition Global — `no AKS product page found (slug not 200)`
- Minecraft Dungeons II PRE-PURCHASE Deluxe Edition EU — `no AKS product page found (slug not 200)`
- … 404 autres

### DLC sans page AKS propre (33)

Motifs exacts : DLC in title but AKS page 'fortnite' carries no DLC edition (4), DLC in title but AKS page 'thehunter-call-of-the-wild' carries no DLC edition (3), DLC in title but AKS page 'tekken-8' carries no DLC edition (3), DLC in title but AKS page 'halo-campaign-evolved' carries no DLC edition (2), DLC in title but AKS page 'total-war-attila' carries no DLC edition (2), DLC in title but AKS page 'commandos-origins' carries no DLC edition (2).

- Fortune's Tavern The Fantasy Tavern Simulator - Play the Mayor DLC EN Global — `DLC in title but AKS page 'fortunes-tavern-the-fantasy-tavern-simulator' carries no DLC edition — base game or`
- theHunter Call of the Wild - Hirschfelden Veteran Cosmetic Pack DLC EN EU — `DLC in title but AKS page 'thehunter-call-of-the-wild' carries no DLC edition — base game or wrong product, no`
- DOOM The Dark Ages - Revelations Gift DLC EN Global — `DLC in title but AKS page 'doom-the-dark-ages' carries no DLC edition — base game or wrong product, not entere`
- … 30 autres

### Bundles / packs multi-jeux (58)

Motifs exacts : skip category (56), possible multi-game bundle (2).

- Middle-Earth - The Shadow Bundle EN/DE/FR/IT/PL/PT/RU/ES EU — `skip category: BUNDLE (no bundles/skins)`
- Tony Hawk's Pro Skater 3 + 4 Deluxe Edition EN United Kingdom — `possible multi-game bundle`
- Kingdom Come Deliverance - Saga Bundle EN United Kingdom — `skip category: BUNDLE (no bundles/skins)`
- … 55 autres

### Cartes prépayées / gift cards / wallets (16)

- JoJo's Bizarre Adventure Golden Spirit 120 JoNotes Direct Top-Up — `skip category: TOP UP`
- JoJo's Bizarre Adventure Golden Spirit 2380 JoNotes Direct Top-Up — `skip category: TOP UP`
- JoJo's Bizarre Adventure Golden Spirit 300 JoNotes Direct Top-Up — `skip category: TOP UP`
- … 13 autres

### Régions verrouillées interdites (409)

- The Mound Omen of Cthulhu Deluxe Edition Asia — `forbidden region: ASIA`
- Kingdom Come Deliverance II Royal Edition EN Canada — `forbidden region: CANADA`
- Quantum Break EN North America — `forbidden region: NORTH AMERICA`
- … 406 autres

### Édition / variante absente de la page AKS (28)

- Death Stranding - Director's Cut EN United Kingdom — `different/expanded product — extra words: ["DIRECTOR'S", 'CUT', 'KINGDOM']`
- Rin The Last Child United Kingdom — `different/expanded product — extra words: ['KINGDOM']`
- Resident Evil 2 Remake United Kingdom — `different/expanded product — extra words: ['REMAKE', 'KINGDOM']`
- … 25 autres

### Plateforme non vérifiable (11)

- Lies Of P United States — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- Tales of Arise United States — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- Trine 4 The Nightmare Prince United States — `no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted (R2`
- … 8 autres

### Page AKS sans carte d'éditions (1)

- Movavi Video Editor Plus 2021 - Magic World Set Global — `AKS page carries no editions map — edition unverifiable (R19)`

### Sonde AKS non fiable (transitoire) (3)

- KIBORG EN United Kingdom — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- MotoGP 25 EN United Kingdom — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`
- Grand Theft Auto V Enhanced Edition EN United Kingdom — `AKS probe unreliable (throttled?): site search -> <urlopen error HTTPSConnectionPool(host='www.allkeyshop.com'`

### Autres (31)

Motifs exacts : language restriction (27), preorder bonus (3), skip category (1).

- The Blood of Dawnwalker - Pre-Order Bonus DLC EN Global — `preorder bonus`
- The Blood of Dawnwalker Pre-Order Bonus Edition EU — `preorder bonus`
- Fallout 76 Gone Fission Deluxe Edition EN/DE/FR/IT/PL/CS/NL EU — `language restriction`
- … 28 autres
