# Les chiffres de la présentation — méthode et date

Deux comptages, même méthode :

- **28 septembre 2026, 06 h 35 UTC (8 h 35, heure de Paris)** — les chiffres du **diaporama de
  3 minutes** (`presentation.html`). Section suivante.
- **27 septembre 2026 au matin (UTC)** — les chiffres de l'**annexe technique**
  (`annexe_technique/presentation_technique.html`), gardés tels quels plus bas : ses légendes
  disent « du 6 juillet au 27 septembre ».

## Comptage du 28/09/2026 à 06 h 35 UTC (diaporama de 3 minutes)

**Méthode** (la même que le 27/09, détaillée plus bas) : `outils/compter_creations.py`, en
**lecture seule**, sur le clone de production de chacun des deux serveurs, lancé le 28/09 entre
06:35:17 et 06:35:24 UTC ; les deux sorties sont additionnées (une offre créée disparaît de la file
d'attente, elle ne peut pas être comptée deux fois). Données fusionnées :
`outils/donnees_creations_2026-09-28.json` (lues par `outils/generer_3min.py`).

- **Total : 19 059** offres créées et prouvées, du 2026-07-06 au 2026-09-28 06:35 UTC (serveur 1 :
  10 118, serveur 2 : 8 941). **+ 1 742** depuis le comptage du 27/09 au matin.
- **Depuis le 8 septembre** (saisie automatique sur les 2 serveurs) : **18 637**. Avant : 422.
- **14 derniers jours complets (14 → 27 septembre)** : **16 500**.
- **Record : 2 627** le samedi 26/09/2026 (inchangé). Le 27/09, journée complète : **2 184**.
- Par mois : 2026-07 : 216, 2026-08 : 181, 2026-09 : 18 662 (dont 343 le 28/09 avant 06 h 35 UTC).
- **Marchands couverts : 21** = la liste blanche (`src/admin/auto_merchants.py`, `AUTO_MERCHANTS`,
  21 entrées le 28/09). 20 ont déjà des créations ; **Allyouplay** n'a pas encore été balayé.
  Discover.games (364) et Loaded (5), à 0 le 27/09, ont leurs premières créations.
- **Tests automatisés : 2 871** (`python3 -c "import unittest; print(unittest.defaultTestLoader.discover('tests').countTestCases())"`
  sur `origin/main` du 28/09 ; 2 840 le 27/09). Le texte dit « près de 2 900 ».
- **> 50 000** offres en attente : relevé du 25/09 (voir « Le backlog » plus bas), non refait le 28/09.

Le graphique du diaporama montre les **journées complètes** du 8 au 27 septembre (le 28 est
partiel) ; les jours sans barre (13 et 14/09) n'ont eu aucune création.

### Par marchand (28/09, 06 h 35 UTC)

| Marchand | Offres créées |
|---|---:|
| GameSeal | 5 915 |
| Gamerall | 2 414 |
| Eneba | 1 915 |
| MMOGA | 1 716 |
| Gamivo | 1 658 |
| GOG | 911 |
| CJS-CDKeys | 859 |
| Kinguin | 816 |
| Wyrel | 608 |
| GameBoost | 415 |
| K4G | 368 |
| G2A | 364 |
| Discover.games | 364 |
| Gamesplanet FR | 301 |
| Driffle | 199 |
| Instant Gaming | 152 |
| Difmark | 58 |
| Electronicfirst | 16 |
| GamersOutlet | 5 |
| Loaded | 5 |

### Par jour, depuis la mise en service (28/09, 06 h 35 UTC)

| Jour | Offres créées |
|---|---:|
| 08/09 | 23 |
| 09/09 | 16 |
| 10/09 | 772 |
| 11/09 | 941 |
| 12/09 | 42 |
| 15/09 | 568 |
| 16/09 | 328 |
| 17/09 | 513 |
| 18/09 | 477 |
| 19/09 | 1 695 |
| 20/09 | 2 561 |
| 21/09 | 1 412 |
| 22/09 | 1 236 |
| 23/09 | 857 |
| 24/09 | 668 |
| 25/09 | 1 374 |
| 26/09 | 2 627 |
| 27/09 | 2 184 |
| 28/09 | 343 (partiel, jusqu'à 06 h 35 UTC) |

Pour refaire ce comptage : voir l'en-tête de `outils/generer_3min.py` (deux lancements du compteur,
puis `--fusion`), et reporter les nouveaux chiffres ici.

---

## Comptage du 27/09/2026 au matin (annexe technique)

Arrêtés le **27 septembre 2026 au matin (UTC)**. Deux machines (« nouvelle VM » et « ancienne VM », les deux VPS de production).

### Offres créées

**Méthode.** Une offre est comptée quand le journal d'un run (`logs/<run>.jsonl`, sur le clone de production de chaque machine) porte un événement `submit_offer` avec `"success": true` — c'est-à-dire une saisie dont la preuve est faite : **l'offre a disparu du feed rafraîchi** (`post_save: "gone from feed"`). Aucun essai à blanc n'écrit cet événement. Le marchand est lu dans le fichier `approved.json` / `candidates.json` du run (store id), à défaut dans le nom du run. Les deux machines sont additionnées ; une offre créée disparaît du feed, elle ne peut pas être comptée deux fois. Script : `outils/compter_creations.py`, lancé sur chaque machine le 27/09 au matin ; les deux sorties sont fusionnées dans `outils/donnees_creations.json`.

- **Total : 17 317** offres créées et prouvées, du 2026-07-06 au 2026-09-27 (nouvelle VM 8 915, ancienne VM 8 402).
- **Depuis le 8 septembre 2026** (mise en service de la saisie automatique « safe-auto » sur les 2 VPS) : **16 895**. Avant : 422 (juillet–août, mises au point et premiers lots).
- **14 derniers jours (14 → 27 septembre)** : **15 101**.
- **Record : 2 627** le 26/09/2026.
- Par mois : 2026-07 : 216, 2026-08 : 181, 2026-09 : 16 920.

#### Par marchand

| Marchand | Offres créées | Note |
|---|---:|---|
| GameSeal | 5 908 | plus grosse file (5 522 lignes le 21/09), balayée plusieurs fois en entier |
| Gamerall | 2 414 | liste blanche le 19/09 |
| MMOGA | 1 716 |  |
| Gamivo | 1 540 |  |
| CJS-CDKeys | 859 |  |
| Eneba | 833 |  |
| Kinguin | 813 |  |
| GOG | 787 | liste blanche le 22/09 |
| Wyrel | 608 | liste blanche le 24/09 |
| GameBoost | 412 |  |
| K4G | 368 |  |
| G2A | 362 |  |
| Gamesplanet FR | 270 | liste blanche le 25/09 |
| Driffle | 196 |  |
| Instant Gaming | 152 |  |
| Difmark | 58 | liste « account » (30), saisie à la main |
| Electronicfirst | 16 | petite file |
| GamersOutlet | 5 | file de 9 lignes |
| Discover.games, Loaded | 0 | entrés en liste blanche le 26/09, pas encore balayés |

#### Par jour (14 → 27 septembre)

| Jour | Offres créées |
|---|---:|
| 15/09 | 568 |
| 16/09 | 328 |
| 17/09 | 513 |
| 18/09 | 477 |
| 19/09 | 1 695 |
| 20/09 | 2 561 |
| 21/09 | 1 412 |
| 22/09 | 1 236 |
| 23/09 | 857 |
| 24/09 | 668 |
| 25/09 | 1 374 |
| 26/09 | 2 627 |
| 27/09 | 785 |

Le 27 est une journée partielle (comptage le matin). Les jours absents de la table n'ont eu aucune création.

### Le système

| Chiffre | Valeur | Méthode |
|---|---|---|
| Marchands en liste blanche | 21 | `src/admin/auto_merchants.py` (AUTO_MERCHANTS), le 26/09 : 11 dans le groupe A, 9 dans le B, Difmark hors groupe |
| Fichiers de règles par marchand | 21 | `src/merchants/*.py` hors `common`, `registry`, `__init__` |
| Règles générales numérotées | 59 | identifiants `[Rnn]` distincts dans `docs/EXECUTOR_RULES.md` (numérotation jusqu'à R62 ; quelques numéros sont des sous-règles a/b/c) |
| Tests automatisés | 2 840 | `python3 -m unittest discover -s tests` le 27/09 (Python + console JS exécutée sous node) |
| Lignes de Python | ~35 000 | `wc -l src/*.py src/merchants/*.py scripts/*.py src/admin/*.py` |
| Commits | 521 | `git log --oneline \| wc -l`, premier commit le 1er juillet 2026 |
| Pages du sitemap AKS indexées | 213 599 | `state/aks_sitemap.json` (`pages`) sur la nouvelle VM |
| VPS | 2 | un groupe de marchands chacun ; groupe A ≈ 13 810 lignes en attente (mesure du 21/09), groupe B ≈ 15 555 |

### Le backlog (liste Pending, relevé du 25/09/2026)

Relecture complète de la liste Pending (`available=all`) le 25/09, après la correction du tri du feed (tri par identifiant : l'ancien tri par date renvoyait les mêmes pages et cachait ~13 000 lignes).

- **> 50 000** lignes en attente au total ; environ 80 % des lignes vues datent d'avant septembre ; il en arrive plusieurs centaines par jour.
- **~ 6 847** lignes console (PlayStation, Xbox, Switch) — périmètre ouvert par étapes depuis le 12/09 (P1 le 14/09, P2 à P5 le 25/09).
- **3 102** lignes hors jeu (cartes cadeaux, monnaies, comptes, bundles), à trier vers leurs listes.
- **1 589** lignes en région non vendable (« Rest of World », Amérique du Nord…).
- Pixelcodes / Software-codes : **3 085** produits de leur feed introuvables sur leur propre site (liste transmise aux marchands, 25/09).

### Corrections manuelles identifiées le 26/09

- 18 offres saisies sur la page du DLC alors qu'il s'agissait de l'édition jeu + DLC (à passer sur la page du jeu, édition du même nom) ; 4 offres sur la bonne page mais en édition DLC au lieu de l'édition nommée. Liste complète dans `docs/CHANGELOG.md`, entrée « [R18c] étape B » du 26/09.

### Cadence (mesures d'exploitation)

- ≈ 2,5 min pour lire et matcher une page de 100 offres ; ≈ 1 min par offre créée, preuve comprise (une page dense de 80 créations prend une heure et demie).
- Un groupe complet : 20 à 40 heures selon la charge (groupe B du 25-26/09 : 21 h 27, 1 343 créées ; groupe A du 25-27/09 : en cours au moment du comptage, 1 934 créées).
