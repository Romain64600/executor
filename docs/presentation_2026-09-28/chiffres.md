# Les chiffres de la présentation — méthode et date

Arrêtés le **27 septembre 2026 au matin (UTC)**. Deux machines (« nouvelle VM » et « ancienne VM », les deux VPS de production).

## Offres créées

**Méthode.** Une offre est comptée quand le journal d'un run (`logs/<run>.jsonl`, sur le clone de production de chaque machine) porte un événement `submit_offer` avec `"success": true` — c'est-à-dire une saisie dont la preuve est faite : **l'offre a disparu du feed rafraîchi** (`post_save: "gone from feed"`). Aucun essai à blanc n'écrit cet événement. Le marchand est lu dans le fichier `approved.json` / `candidates.json` du run (store id), à défaut dans le nom du run. Les deux machines sont additionnées ; une offre créée disparaît du feed, elle ne peut pas être comptée deux fois. Script : `outils/compter_creations.py`, lancé sur chaque machine le 27/09 au matin ; les deux sorties sont fusionnées dans `outils/donnees_creations.json`.

- **Total : 17 317** offres créées et prouvées, du 2026-07-06 au 2026-09-27 (nouvelle VM 8 915, ancienne VM 8 402).
- **Depuis le 8 septembre 2026** (mise en service de la saisie automatique « safe-auto » sur les 2 VPS) : **16 895**. Avant : 422 (juillet–août, mises au point et premiers lots).
- **14 derniers jours (14 → 27 septembre)** : **15 101**.
- **Record : 2 627** le 26/09/2026.
- Par mois : 2026-07 : 216, 2026-08 : 181, 2026-09 : 16 920.

### Par marchand

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

### Par jour (14 → 27 septembre)

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

## Le système

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

## Le backlog (liste Pending, relevé du 25/09/2026)

Relecture complète de la liste Pending (`available=all`) le 25/09, après la correction du tri du feed (tri par identifiant : l'ancien tri par date renvoyait les mêmes pages et cachait ~13 000 lignes).

- **> 50 000** lignes en attente au total ; environ 80 % des lignes vues datent d'avant septembre ; il en arrive plusieurs centaines par jour.
- **~ 6 847** lignes console (PlayStation, Xbox, Switch) — périmètre ouvert par étapes depuis le 12/09 (P1 le 14/09, P2 à P5 le 25/09).
- **3 102** lignes hors jeu (cartes cadeaux, monnaies, comptes, bundles), à trier vers leurs listes.
- **1 589** lignes en région non vendable (« Rest of World », Amérique du Nord…).
- Pixelcodes / Software-codes : **3 085** produits de leur feed introuvables sur leur propre site (liste transmise aux marchands, 25/09).

## Corrections manuelles identifiées le 26/09

- 18 offres saisies sur la page du DLC alors qu'il s'agissait de l'édition jeu + DLC (à passer sur la page du jeu, édition du même nom) ; 4 offres sur la bonne page mais en édition DLC au lieu de l'édition nommée. Liste complète dans `docs/CHANGELOG.md`, entrée « [R18c] étape B » du 26/09.

## Cadence (mesures d'exploitation)

- ≈ 2,5 min pour lire et matcher une page de 100 offres ; ≈ 1 min par offre créée, preuve comprise (une page dense de 80 créations prend une heure et demie).
- Un groupe complet : 20 à 40 heures selon la charge (groupe B du 25-26/09 : 21 h 27, 1 343 créées ; groupe A du 25-27/09 : en cours au moment du comptage, 1 934 créées).
