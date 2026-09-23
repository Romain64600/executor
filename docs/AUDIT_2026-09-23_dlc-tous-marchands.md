# Audit — faut-il étendre les deux règles DLC de GOG à tous les marchands ?

Romain, 2026-09-23 : « go pour 1 et 3, mais avant, audit pour voir si on ferait pas mieux
d'ajouter ces comportements à tous les marchands. »

Les deux règles en question :

1. **« Expansion » veut dire DLC** — né du préfixe GOG « Expansion - Crusader Kings II: Holy
   Fury ».
2. **« S'il y a déjà des offres DLC, on ajoute en DLC »** — pour les DLC dont le titre ne dit
   pas qu'ils en sont.

Corpus : **17 458 offres distinctes** de tous les balayages récents — la nuit du 21 au 22
(seize marchands), GameSeal le 21, les groupes A et B le 22, GOG le 23. Les pages AKS
nécessaires ont été lues en direct (UA `AKS/Staff`) et le sitemap sert pour l'existence des
pages.

---

## Réponse courte

| Règle | Portée retenue | Pourquoi |
|---|---|---|
| 1. « Expansion » = DLC | **GOG seulement** | Générique, elle casserait des extensions vendues en éditions |
| 3. Le DLC reconnu à sa page et à celle de son jeu | **Tous les marchands** | 19 récupérées, toutes justes, rien de cassé |

## Règle 1 — « Expansion » : GOG seulement

**88 offres** de 13 marchands contiennent le mot « Expansion » hors « Expansion Pass ». Relues
une à une : dans les 88 cas, le mot désigne bien une extension de jeu. Mais **AKS ne range pas
toutes les extensions dans le seau DLC.** Lu en direct :

| Page AKS | Seaux |
|---|---|
| `diablo-4-vessel-of-hatred` | DLC · Deluxe · Expansion Bundle · Ultimate |
| `guild-wars-2-end-of-dragons` | DLC · Standard · Deluxe · Complete Collection |
| `world-of-warcraft-the-war-within` | Heroic · Epic |
| `the-sims-4-cottage-living` | DLC |

Un marqueur « Expansion » générique ferait suivre ces lignes le chemin des DLC marqués (R43),
qui range en DLC(16). Une offre « Diablo IV Vessel of Hatred Expansion Deluxe » partirait en
DLC au lieu de Deluxe ; une extension World of Warcraft, dont la page n'a pas de seau DLC,
serait refusée. Aucune de ces lignes n'est entrée aujourd'hui, donc la régression serait
latente, mais elle est certaine au premier cas qui se présente.

Et le gain hors GOG serait quasi nul : les seules lignes qu'il débloquerait (quatre K4G
« Talisman - The … Expansion ») sont déjà récupérées par la règle 3.

**Chez GOG, en revanche, le marqueur est nécessaire, pas seulement le retrait du préfixe.**
Sur les 14 pages des titres « Expansion - », 13 portent un autre seau que le DLC (« Royal
Collection », « Imperial Collection ») et deux portent même un **Standard** (Jade Dragon, The
Old Gods). Sans marqueur, ces deux-là seraient rangés en Standard — faux. Avec le marqueur :
14 offres en DLC au lieu d'une.

## Règle 3 — le DLC reconnu à sa page et à celle de son jeu : tous les marchands

La demande telle quelle — « s'il y a déjà des offres DLC, on ajoute en DLC » — rouvrirait
l'erreur du 17 septembre : la page du jeu de base « Grand Theft Auto Vice City » portait un seau
DLC à côté du Standard, et le jeu est entré en DLC. La règle écrite exige donc **quatre faits
réunis** :

1. le titre ne porte ni marqueur DLC ni mot d'édition ;
2. la page ne vend **aucun** Standard — c'est ce qui garde le cas Vice City ;
3. la ligne est sur la page **à son propre nom** ;
4. la page d'un **jeu parent** existe aussi — « Europa Universalis IV: Muslim Advisor
   Portraits » et `europa-universalis-iv`. C'est ce qui sépare un DLC d'un jeu de base.

Sur les 17 458 offres, **41 refus** portaient sur une page à seau DLC. La règle en récupère
**19** :

| Marchand | Récupérées |
|---|---|
| GOG | 15 |
| K4G | 4 |
| les 14 autres | 0 |

Les 19, relues une à une, sont toutes des DLC : « Europa Universalis IV: Songs of the New
World », « Sticky Business: Camp Zinnias », quatre extensions Talisman, « Craft The World -
Sisters in Arms », « Neon Abyss - Chrono Trap »… Les 22 autres restent refusées : 11 parce que
la page à leur nom n'existe pas, 11 parce que je ne trouve pas la page du jeu parent. C'est le
côté sûr.

Pourquoi presque rien chez les autres marchands : les revendeurs écrivent « (DLC) » dans leurs
titres, et ces lignes passent déjà par R43. GOG ne l'écrit jamais.

**Effet sur les offres déjà acceptées : aucun, par construction.** La règle ne s'ouvre que
sur une page sans Standard, là où un titre « Standard » était refusé. Elle ne peut que
transformer un refus en DLC, jamais changer une entrée existante.

## Ce qui est écrit

* `src/merchants/gog.py` — `dlc_marker`, `resolve_name` et `guard_name` pour le préfixe
  « Expansion - », et lui seul.
* `src/merchant_config.py` — le crochet générique `dlc_marker`, vide par défaut.
* `src/matcher.py` — `derived_dlc_page` `[R57]`, placée **dans** la condition de R18 : R18
  reste le seul juge du seau DLC, avec une branche de plus.
* `AGENTS.md` — les deux décisions, avec la consigne de ne pas rendre « Expansion »
  générique et de ne pas élargir `[R57]`.

Chaque condition a été retirée une à une : sept mutations, sept tests rouges. Il a fallu trois
tests de plus pour y arriver, parce qu'au premier passage trois conditions étaient masquées par
leurs voisines.
