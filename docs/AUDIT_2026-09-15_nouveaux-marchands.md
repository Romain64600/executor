# Audit 2026-09-15 — nouveaux marchands potentiels (lisibilité région / plateforme / édition)

Demande de Romain (2026-09-15) : « trouver de nouveaux marchands potentiels qu'on pourrait ajouter comme les marchands actuels » — pour chaque boutique du feed AKS non encore prise en charge, regarder une offre Steam et dire si la **région**, la **plateforme** (→ région AKS) et l'**édition** se lisent dans l'URL, dans le titre, ou dans les deux. Priorité aux marchands qui **n'ont pas besoin qu'on ouvre la page de l'offre**.

## Méthode

- Source : page 1 du feed AKS de chaque boutique (`available=all`, lecture seule, ancien VPS, `scratchpad/newmerchants/dump_new_merchants.py`), soit au plus 100 lignes par boutique — le feed ne donne que `name`, `url`, `price`, `store_id` ; aucune page marchand n'a été ouverte.
- Boutiques exclues : les 12 déjà prises en charge (Kinguin, Gamivo, G2A, MMOGA, K4G, Driffle, Instant Gaming, Eneba, Allyouplay, GameSeal, CJS-CDKeys, Difmark) et celles que le feed marque `stopped` / `NO REFRESH` / `OFF` / `crawler`.
- Lecture générique (`analyze_signals.py`, aucun fichier marchand) : vocabulaire plateforme (Steam, Epic, Ubisoft, EA, GOG, Battle.net, Rockstar, Microsoft Store, Xbox One / Series, PS4 / PS5, Switch…), région (GLOBAL / EU / US / UK / DE / LATAM / ASIA / RU / TR / autres codes), édition (Deluxe, Gold, Ultimate, Complete, Standard, DLC / Season Pass / Pack…). Un « PC » seul ne compte pas comme plateforme.
- Classes : **A** = URL/titre suffisent (plateforme + région lisibles) ; **B** = plateforme lisible, région implicite (politique boutique à valider une fois, comme Kinguin / MMOGA) ; **B-** = région lisible mais plateforme rarement déclarée ; **C** = ni plateforme ni région dans l'URL / le titre : page marchand nécessaire (comme Instant Gaming / Difmark) ; **VIDE** = aucune offre dans le feed (page 1, available=all).
- Les pourcentages sont des **présences de mots**, pas une preuve de justesse : la grammaire exacte (ordre, codes, cas) reste à déclarer dans un `src/merchants/<marchand>.py` avant toute saisie (règle « un fichier de config par marchand »).

## Conclusion — priorité aux marchands qui n'ont pas besoin de la page marchand

Romain (2026-09-15) : « Certains marchands s'y prêtent avec soit la composition de l'URL,
soit la composition de leur nom ou titre. D'autres ne s'y prêtent pas du tout et ne
pourront pas être ajoutés sans avoir ouvert la page de l'offre marchand. On veut traiter en
priorité ceux qui n'ont pas besoin d'avoir la page marchand. »

**Rang 1 — tout est dans l'URL et le titre, comme G2A ou Driffle.**

| Boutique | id | pages | ce qui se lit | exemple |
|---|---|---|---|---|
| **GameBoost** | 157 | 13 | plateforme, région en toutes lettres, édition | `Wardogs \| Supporter Edition (PC) - Steam Key - United States` |
| **GamersOutlet** ✅ | 31 | 1 | plateforme, région, dans le titre ET l'URL | `Polylithic (PC Steam Key / Global)` |
| **Electronicfirst** ✅ | 70 | 4 | plateforme, code région avant la plateforme (grammaire Kinguin) | `Warhammer 40,000: Dawn of War IV Commander Edition EU/NA PC Steam CD Key` |
| Royalcdkeys | 85 | 1 | plateforme, région partielle | — |
| My Nintendo Store FR / NL / UK | 153 / 154 / 155 | 2 | plateforme Switch et pays dans l'URL (boutiques officielles) | — |

**FAIT le 2026-09-15 — GameBoost (`src/merchants/gameboost.py`, `[R47]`).** Romain a
rappelé qu'un run GameBoost avait déjà été annulé en direct le 2026-07-15 (`[R27]`) parce
que la région et la plateforme n'étaient que sur la page marchand, bloquée par Cloudflare.
Ré-audit sur 821 lignes uniques (pages 1-10) : la grammaire a changé, la plateforme est
maintenant déclarée dans la grande majorité des titres, **mais la région manque encore sur
une ligne sur six**. Le fichier marchand lit ce que le titre déclare et refuse le reste —
`[R47]` : pas de mot de région ⇒ skip fail-closed, jamais le GLOBAL implicite. Verdicts :
430 lignes passent (eu 258, us 115, global 57), 175 non-jeux (cartes cadeaux), 137 sans
région, 79 régions interdites. GameBoost reste **hors liste blanche safe-auto** — runs
supervisés seulement. Détail : `docs/MERCHANTS.md` § GameBoost.

**FAIT le 2026-09-15 — GamersOutlet (`[R48]`) et Electronicfirst (`[R49]`).** Feeds complets
extraits en lecture seule (20 et 323 lignes), grammaire analysée par trois lentilles
indépendantes puis attaquée par trois contradicteurs adversariaux par marchand. GamersOutlet :
slot `( <livraison> / <région> )` obligatoire, table des boutiques du fichier publiée au
matcher — 16 lignes sur 20 passent. Electronicfirst : grammaire Kinguin, et la décision
« vide = mondial » a été RÉFUTÉE côté console (aucun SKU PSN/Xbox mondial ; 7 lignes dont
quatre jeux complets partaient en monde entier) → skip fail-closed `[R49c]` ; 247 lignes sur
323 passent. Les deux restent hors liste blanche safe-auto, dry-run supervisé d'abord.
Détail : `docs/MERCHANTS.md`.

**Rang 2 — plateforme lisible, région implicite** (même situation que Kinguin et MMOGA : il
faut arrêter une politique boutique une fois, puis c'est saisissable sans page marchand) :
Keycense (130, la livraison est lisible — `Wanderburg | Steam Altergift`, vocabulaire déjà
traité chez K4G), GamesPlanet FR (55, plateforme dans l'URL `…-steam-key--8717-1`),
GamingDragons (41, `buy-<jeu>-steam-key.html`), Playerland (163), StartSelect DE/FR/NL/IT/GB/ES/PT,
Ubisoft UK (133).

**Cas particulier — CDKeys (40).** Le titre ne dit presque rien (« Egging On PC ») mais la
vraie URL est encapsulée dans le lien affilié `go.loaded.com/c/…?u=<url réelle>` : une fois
le paramètre `u` décodé, la plateforme se lit (`…/egging-on-pc-steam`). Faisable sans page
marchand, à condition de décoder l'URL d'abord.

**Rang 3 — page marchand obligatoire, à écarter tant qu'on ne sait pas ouvrir leurs pages.**
GOG, Fanatical, GreenManGaming, GamersGate, GameBillet, DreamGame, Indiegala, EtailMarket,
DiscoverGames, PlanetPlay, PlaySum EU/UK/US, SoftwareCodes, wingamestore, Yuplay, HRK.
**Eldorado (145) est le pire cas** : toutes ses offres partagent la même URL sans
identifiant produit (`eldorado.gg/cd-keys/v/283?te_v1=0-20`), seul le titre porte un signal.

**Hors périmètre jeux.** eTailCard (152) et LdShop (169) vendent surtout des cartes cadeaux
et des recharges ; Cdkeysales (69) des abonnements (Duolingo…) ; Lootbar.gg (165) des
recharges.

**48 boutiques ont un feed vide en page 1** au moment du dépouillement : rien à saisir
aujourd'hui, à re-regarder quand elles se remplissent.

## Étalonnage sur les marchands actuels (même lecture générique, page 1 d'un run récent)

| Boutique | id | offres p1 | pages feed | classe | plateforme % URL / titre / l'un | région % URL / titre / l'un | mot d'édition % titre | Steam n / région % | plateformes vues | régions vues |
|---|---|---|---|---|---|---|---|---|---|---|
| Eneba | 19 | 100 |  | A | 100 / 100 / 100 | 99 / 99 / 99 | 36 | 5 / 100 | MSSTORE 95, XBOX 95, XBOX_SERIES 38, STEAM 5 | EU 95, GLOBAL 3, ASIA 2, US 1 |
| G2A | 38 | 100 |  | A | 82 / 82 / 82 | 100 / 99 / 100 | 33 | 68 / 100 | STEAM 68, MSSTORE 11, XBOX 11, XBOX_SERIES 10 | GLOBAL 100, EU 15, US 9, UK 8 |
| MMOGA | 12 | 100 |  | B | 85 / 41 / 85 | 22 / 22 / 22 | 39 | 52 / 27 | STEAM 52, MSSTORE 18, XBOX 17, XBOX_SERIES 10 | EU 21, US 1, DE 1 |
| Kinguin | 58 | 100 |  | B | 83 / 83 / 83 | 61 / 61 / 61 | 25 | 38 / 32 | STEAM 38, XBOX 36, XBOX_SERIES 35, XBOX_ONE 32 | OTHER 24, US 13, EU 10, UK 6 |
| Driffle | 127 | 100 |  | B- | 67 / 67 / 67 | 88 / 98 / 98 | 31 | 38 / 97 | STEAM 38, EPIC 10, UBISOFT 9, MSSTORE 9 | GLOBAL 71, EU 15, OTHER 5, US 4 |
| Instant Gaming | 28 | 100 |  | C | 0 / 0 / 0 | 0 / 4 / 4 | 18 | 0 / — |  | ASIA 3, DE 1, OTHER 1 |

**Difmark (167) — ajouté le 2026-09-21, Romain : « je vois pas difmark dans le tableau ».** Il
manquait pour deux raisons cumulées : la méthode excluait les 12 boutiques déjà prises en
charge (dont Difmark), et l'étalonnage ci-dessus n'a repris que les 6 marchands qui avaient un
run récent — Difmark est parqué, il n'en avait pas. Mesure faite le 21/09 sur **1 265 lignes
distinctes sauvegardées** (les `skipped.json` des runs d'août, pas un dump frais de page 1 : le
navigateur était pris par un `08_sort_plan`), avec une ré-implémentation du même comptage —
`analyze_signals.py` n'existe plus :

| Boutique | id | lignes | classe | plateforme % URL / titre | région % URL / titre | mot d'édition % titre |
|---|---|---|---|---|---|---|
| Difmark | 167 | 1 265 | C | **97** / 5 | **1** / 1 | 99 |

**Corrigé le 2026-09-21 — ces chiffres ignoraient la query string.** Les deux mesures
ci-dessus (et celle de juillet) coupaient l'URL au `?`. Or c'est LÀ que Difmark écrit ses
signaux : `marketplace_id` (plateforme), `edition_id` (édition, concordante avec le titre sur
1 348 / 1 348 lignes), `region_product_id` (région, mais constante à 1 sur 1 347). Détail et
méthode : `docs/MERCHANTS.md` § Difmark. Une lecture de signaux qui ne regarde que le chemin
de l'URL sous-estime donc les boutiques qui paramètrent leurs liens — à refaire pour les
autres classes C avant de les déclarer illisibles.

Nuance que ces chiffres imposent à l'étiquette « classe C » : chez Difmark la **plateforme est
bien dans l'URL** (`…-pc-epic-games-account-149270`, 97 %), c'est la **région** qui n'est nulle
part (1 %) — et c'est elle seule qui force l'ouverture de la page de l'offre
(`resolve_difmark_offer`). Le 99 % d'« édition » est un leurre : tous les titres finissent par
« Standard Edition », c'est du gabarit, pas une information. À rapprocher d'Instant Gaming,
l'autre référence de classe C, où **rien** n'est lisible (0 / 0). Enfin ces lignes sont très
majoritairement des **COMPTES** (`buy-console-account-…`), refusés par `[R45]` — la lecture
n'ouvre donc pas de voie de saisie, elle situe la boutique sur l'échelle.

Lecture : G2A / Eneba / Driffle écrivent tout dans l'URL et le titre (classe A) ; Kinguin et MMOGA déclarent la plateforme mais laissent la région implicite (GLOBAL par défaut, code pays sinon — classe B, saisis grâce à une politique boutique déclarée dans leur fichier marchand) ; Instant Gaming n'écrit rien dans ses titres (classe C) et n'est saisi que parce que son fichier marchand lit la page de l'offre (`data-platform`). Les nouvelles boutiques se rangent sur la même échelle.

## Résultat — boutiques non prises en charge

| classe | boutiques |
|---|---|
| A — URL/titre suffisent (plateforme + région lisibles) | 6 |
| B — plateforme lisible, région implicite (politique boutique à valider une fois, comme Kinguin / MMOGA) | 19 |
| B- — région lisible mais plateforme rarement déclarée | 6 |
| C — ni plateforme ni région dans l'URL / le titre : page marchand nécessaire (comme Instant Gaming / Difmark) | 24 |
| VIDE — aucune offre dans le feed (page 1, available=all) | 48 |

### Classe A — URL/titre suffisent (plateforme + région lisibles)

| Boutique | id | offres p1 | pages feed | classe | plateforme % URL / titre / l'un | région % URL / titre / l'un | mot d'édition % titre | Steam n / région % | plateformes vues | régions vues |
|---|---|---|---|---|---|---|---|---|---|---|
| My Nintendo Store FR | 153 | 100 | 2 | A | 100 / 4 / 100 | 100 / 15 / 100 | 20 | 0 / — | SWITCH 100, SWITCH2 1 | OTHER 100, DE 14, ASIA 1 |
| My Nintendo Store NL | 154 | 100 | 2 | A | 100 / 4 / 100 | 100 / 2 / 100 | 24 | 0 / — | SWITCH 100, SWITCH2 1 | OTHER 100, DE 1, ASIA 1 |
| My Nintendo Store UK | 155 | 100 | 2 | A | 100 / 5 / 100 | 100 / 3 / 100 | 36 | 0 / — | SWITCH 100, SWITCH2 2 | UK 100, OTHER 2, ASIA 1 |
| vidaplayer | 67 | 5 | 1 | A | 100 / 100 / 100 | 100 / 100 / 100 | 20 | 0 / — | MSSTORE 5, XBOX 5 | US 5 |
| KeyeKey | 120 | 2 | 1 | A | 100 / 100 / 100 | 100 / 100 / 100 | 0 | 0 / — | SWITCH 1, PS5 1 | US 2, ASIA 1 |
| PremiumCdkey | 60 | 1 | 1 | A | 100 / 100 / 100 | 100 / 100 / 100 | 0 | 1 / 100 | STEAM 1 | GLOBAL 1 |

### Classe B — plateforme lisible, région implicite (politique boutique à valider une fois, comme Kinguin / MMOGA)

| Boutique | id | offres p1 | pages feed | classe | plateforme % URL / titre / l'un | région % URL / titre / l'un | mot d'édition % titre | Steam n / région % | plateformes vues | régions vues |
|---|---|---|---|---|---|---|---|---|---|---|
| Keycense | 130 | 100 | 2 | B | 100 / 100 / 100 | 56 / 58 / 58 | 47 | 43 / 16 | XBOX 44, STEAM 43, XBOX_SERIES 43, XBOX_ONE 41 | EU 50, US 3, GLOBAL 3, ASIA 1 |
| eTailCard | 152 | 100 | 3 | B | 88 / 29 / 88 | 73 / 10 / 73 | 33 | 0 / — | XBOX 81, MSSTORE 10, SWITCH 5, EA 2 | GLOBAL 68, US 3, TR 1, OTHER 1 |
| GameBoost | 157 | 100 | 10 | B | 87 / 87 / 87 | 61 / 64 / 64 | 46 | 73 / 67 | STEAM 73, XBOX 13, XBOX_SERIES 8, MSSTORE 6 | GLOBAL 29, EU 15, US 10, OTHER 7 |
| LdShop | 169 | 100 | 2 | B | 93 / 92 / 93 | 50 / 53 / 64 | 6 | 0 / — | PSN 78, XBOX 15 | EU 28, US 15, ASIA 15, OTHER 11 |
| GamesPlanet FR | 55 | 100 | 6 | B | 99 / 4 / 99 | 4 / 4 / 4 | 31 | 95 / 3 | STEAM 95, MSSTORE 3, EPIC 1, UBISOFT 1 | DE 2, ASIA 2 |
| Electronicfirst | 70 | 100 | 4 | B | 81 / 81 / 81 | 42 / 45 / 45 | 56 | 51 / 27 | STEAM 51, XBOX 12, XBOX_SERIES 10, XBOX_ONE 10 | EU 25, DE 14, US 10, ASIA 4 |
| Royalcdkeys | 85 | 88 | 1 | B | 90 / 90 / 90 | 33 / 33 / 34 | 31 | 54 / 26 | STEAM 54, XBOX 11, XBOX_SERIES 10, XBOX_ONE 9 | EU 24, GLOBAL 3, OTHER 2, US 1 |
| GamingDragons | 41 | 80 | 1 | B | 98 / 44 / 98 | 1 / 29 / 29 | 46 | 43 / 2 | STEAM 43, XBOX 19, XBOX_SERIES 15, XBOX_ONE 9 | EU 13, ASIA 7, US 4, GLOBAL 3 |
| CDKeys | 40 | 76 | 1 | B | 88 / 66 / 88 | 74 / 74 / 74 | 34 | 17 / 24 | XBOX 43, XBOX_SERIES 33, STEAM 17, XBOX_ONE 13 | UK 44, EU 39, US 8, ASIA 3 |
| Playerland | 163 | 72 | 1 | B | 100 / 100 / 100 | 1 / 1 / 1 | 18 | 65 / 2 | STEAM 65, XBOX 7, XBOX_ONE 5, XBOX_SERIES 4 | ASIA 1 |
| Ubisoft UK | 133 | 38 | 1 | B | 100 / 8 / 100 | 0 / 0 / 0 | 68 | 0 / — | UBISOFT 38 |  |
| StartSelect DE | 105 | 11 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 18 | 9 / 0 | STEAM 9, XBOX 2 |  |
| StartSelect FR | 146 | 5 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 40 | 2 / 0 | STEAM 2, XBOX 2, BATTLENET 1 |  |
| StartSelect NL | 148 | 5 | 1 | B | 80 / 80 / 80 | 0 / 0 / 0 | 40 | 2 / 0 | STEAM 2, XBOX 2 |  |
| StartSelect IT | 149 | 4 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 50 | 2 / 0 | STEAM 2, XBOX 2 |  |
| StartSelect GB | 151 | 3 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 0 | 3 / 0 | STEAM 3 |  |
| StartSelect ES | 147 | 2 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 0 | 2 / 0 | STEAM 2 |  |
| StartSelect PT | 150 | 2 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 0 | 2 / 0 | STEAM 2 |  |
| Keys4us | 121 | 1 | 1 | B | 100 / 100 / 100 | 0 / 0 / 0 | 0 | 0 / — | MSSTORE 1 |  |

### Classe B- — région lisible mais plateforme rarement déclarée

| Boutique | id | offres p1 | pages feed | classe | plateforme % URL / titre / l'un | région % URL / titre / l'un | mot d'édition % titre | Steam n / région % | plateformes vues | régions vues |
|---|---|---|---|---|---|---|---|---|---|---|
| Wyrel | 162 | 100 | 60 | B- | 8 / 18 / 18 | 100 / 100 / 100 | 99 | 10 / 100 | STEAM 10, XBOX 8, XBOX_ONE 7, MSSTORE 1 | OTHER 100, GLOBAL 53, EU 19, UK 15 |
| Muve | 166 | 100 | 9 | B- | 42 / 42 / 42 | 54 / 54 / 54 | 28 | 34 / 100 | STEAM 34, XBOX 8, XBOX_SERIES 5, XBOX_ONE 4 | GLOBAL 28, EU 23, ASIA 3, OTHER 2 |
| Cdkeysales | 69 | 71 | 1 | B- | 0 / 0 / 0 | 10 / 80 / 80 | 15 | 0 / — |  | GLOBAL 57 |
| SCDKey | 4 | 55 | 1 | B- | 2 / 2 / 2 | 9 / 89 / 89 | 18 | 1 / 100 | STEAM 1 | GLOBAL 49 |
| GamersOutlet | 31 | 20 | 1 | B- | 65 / 70 / 70 | 100 / 100 / 100 | 25 | 6 / 100 | MSSTORE 6, STEAM 6, ROCKSTAR 2 | GLOBAL 20 |
| Lootbar.gg | 165 | 9 | 1 | B- | 11 / 0 / 11 | 0 / 100 / 100 | 11 | 0 / — | XBOX 1 | GLOBAL 9 |

### Classe C — ni plateforme ni région dans l'URL / le titre : page marchand nécessaire (comme Instant Gaming / Difmark)

| Boutique | id | offres p1 | pages feed | classe | plateforme % URL / titre / l'un | région % URL / titre / l'un | mot d'édition % titre | Steam n / région % | plateformes vues | régions vues |
|---|---|---|---|---|---|---|---|---|---|---|
| Eldorado | 145 | 100 | 13 | C | 41 / 44 / 44 | 34 / 34 / 34 | 0 | 3 / 0 | PSN 14, XBOX 9, MSSTORE 9, SWITCH 9 | TR 11, US 9, UK 5, EU 4 |
| GameBillet | 15 | 100 | 4 | C | 0 / 0 / 0 | 1 / 1 / 1 | 28 | 0 / — |  | ASIA 1 |
| PlanetPlay | 156 | 100 | 4 | C | 0 / 0 / 0 | 0 / 3 / 3 | 38 | 0 / — |  | ASIA 3 |
| PlaySum EU | 158 | 100 | 5 | C | 0 / 0 / 0 | 4 / 4 / 4 | 23 | 0 / — |  | OTHER 3, DE 2, EU 1 |
| PlaySum US | 160 | 100 | 2 | C | 0 / 0 / 0 | 6 / 6 / 6 | 28 | 0 / — |  | OTHER 3, DE 2, ASIA 1, EU 1 |
| PlaySum UK | 161 | 100 | 5 | C | 0 / 0 / 0 | 4 / 4 / 4 | 36 | 0 / — |  | EU 2, ASIA 1, DE 1, OTHER 1 |
| DiscoverGames | 168 | 100 | 5 | C | 0 / 0 / 0 | 3 / 3 / 3 | 7 | 0 / — |  | OTHER 2, ASIA 2 |
| GreenManGaming | 22 | 100 | 6 | C | 6 / 0 / 6 | 2 / 2 / 2 | 24 | 0 / — | XBOX 6, XBOX_SERIES 6 | ASIA 2 |
| GamersGate | 27 | 100 | 2 | C | 3 / 3 / 3 | 3 / 2 / 3 | 47 | 0 / — | GOG 3 | OTHER 2, ASIA 2 |
| GOG | 34 | 100 | 36 | C | 0 / 0 / 0 | 1 / 2 / 2 | 30 | 0 / — |  | US 1, ASIA 1 |
| DreamGame | 52 | 100 | 3 | C | 0 / 0 / 0 | 5 / 5 / 5 | 10 | 0 / — |  | ASIA 3, OTHER 2, EU 1 |
| SoftwareCodes | 6 | 100 | 39 | C | 0 / 0 / 0 | 3 / 3 / 3 | 31 | 0 / — |  | ASIA 2, OTHER 1 |
| Fanatical | 74 | 100 | 12 | C | 0 / 0 / 0 | 1 / 1 / 1 | 42 | 0 / — |  | OTHER 1 |
| Pixelcodes | 82 | 100 | 39 | C | 11 / 11 / 11 | 11 / 11 / 11 | 30 | 0 / — | PSN 7, XBOX 4 | US 9, UK 2 |
| Indiegala | 95 | 100 | 2 | C | 3 / 3 / 3 | 9 / 9 / 9 | 34 | 2 / 0 | STEAM 2, EA 1 | US 8, DE 1 |
| EtailMarket | 99 | 100 | 3 | C | 1 / 4 / 4 | 2 / 2 / 2 | 49 | 4 / 0 | STEAM 4 | ASIA 2 |
| wingamestore | 78 | 85 | 1 | C | 0 / 0 / 0 | 5 / 5 / 5 | 33 | 0 / — |  | US 1, EU 1, OTHER 1, ASIA 1 |
| Yuplay | 123 | 53 | 1 | C | 11 / 11 / 13 | 9 / 9 / 9 | 43 | 0 / — | XBOX 4, XBOX_SERIES 3, XBOX_ONE 2, EPIC 1 | ASIA 2, EU 2, US 1 |
| Softwareload | 68 | 42 | 1 | C | 0 / 7 / 7 | 0 / 0 / 0 | 24 | 0 / — | MSSTORE 3 |  |
| HRK | 14 | 31 | 1 | C | 42 / 23 / 42 | 39 / 39 / 39 | 48 | 2 / 0 | XBOX 6, XBOX_SERIES 6, MSSTORE 4, XBOX_ONE 3 | EU 8, GLOBAL 3, DE 1 |
| EpicKeys | 159 | 11 | 1 | C | 73 / 73 / 73 | 27 / 27 / 27 | 82 | 0 / — | MSSTORE 8 | GLOBAL 3 |
| Wincdkey | 132 | 6 | 1 | C | 17 / 50 / 50 | 0 / 0 / 0 | 0 | 0 / — | MSSTORE 3 |  |
| Bitcodes | 122 | 4 | 1 | C | 50 / 50 / 50 | 0 / 0 / 0 | 0 | 0 / — | MSSTORE 2 |  |
| Esdcodes | 131 | 1 | 1 | C | 0 / 0 / 0 | 0 / 0 / 0 | 0 | 0 / — |  |  |

### Feed vide (page 1 sans offre) ou extraction refusée

2Game EUR (53), 95gameshop (118), Aldi (73), Azzeki (138), Bcdkey (65), BigKidGaming (124), BuyGames (37), Bzfuture (63), DLGamerDe (10), DLGamerFr (11), DlGamerEu (8), DlgamerEs (9), EAPlay (125), Epicgames (102), Epicgames Free (115), FOXOXO (137), GVGMall (24), GameKeys4All (33), GameStop (93), GameThor (140), Gameceo (128), GamesLoadEu (16), Gamesporium (164), IGVault (94), Joybuggy2 (116), KeyToGame (129), Keyesd (96), Keywrld (134), Keyzing (141), LicenceHouse (136), Licensigo (143), MTC (77), Medion (90), Metenzi (142), Micromania (109), MicrosoftSoftwareSwap (144), Mrkeyshop (139), Noctre (106), OG4 (84), Origin2 (80), PlayAsia (44), Punktid (71), Recharge.com (112), Shopto (117), Store700 (113), Whokeys (66), Wizzykey (135), playasia_box (81)

## Exemples d'offres Steam (ce qui se lit dans l'URL / le titre)

Une à deux lignes par boutique des classes A et B (offre Steam si la boutique en a une, sinon la première offre lue).

**My Nintendo Store FR** (153, classe A)

- titre : `Metroid Ravenous`  
  URL : `https://nintendo-fr.sjv.io/c/1297091/2161712/22556?prodsku=000000000010019510&u=https%3A%2F%2Fstore.nintendo.com%2Ffr-fr%2Fmetroid-ravenous-000000000010019510`  
  lu — plateforme URL ['SWITCH'] / titre ∅ ; région URL ['OTHER'] / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Pikmin 4 – Mise à niveau Nintendo Switch 2 Edition + Académie Dandori`  
  URL : `https://nintendo-fr.sjv.io/c/1297091/2161712/22556?prodsku=000000000010016441&u=https%3A%2F%2Fstore.nintendo.com%2Ffr-fr%2Fpikmin-4-mise-a-niveau-nintendo-switc`  
  lu — plateforme URL ['SWITCH2', 'SWITCH'] / titre ['SWITCH2', 'SWITCH'] ; région URL ['OTHER'] / titre ∅ ; édition URL ['EDITION_WORD'] / titre ['EDITION_WORD'] ; livraison ∅

**My Nintendo Store NL** (154, classe A)

- titre : `Metroid Ravenous`  
  URL : `https://nintendo-nl.pxf.io/c/1297091/2161718/22561?prodsku=000000000010019510&u=https%3A%2F%2Fstore.nintendo.com%2Fnl-nl%2Fmetroid-ravenous-000000000010019510`  
  lu — plateforme URL ['SWITCH'] / titre ∅ ; région URL ['OTHER'] / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Pikmin 4 – Nintendo Switch 2 Edition + Dandori-academie-upgradepack`  
  URL : `https://nintendo-nl.pxf.io/c/1297091/2161718/22561?prodsku=000000000010016441&u=https%3A%2F%2Fstore.nintendo.com%2Fnl-nl%2Fpikmin-4-nintendo-switch-2-edition-da`  
  lu — plateforme URL ['SWITCH2', 'SWITCH'] / titre ['SWITCH2', 'SWITCH'] ; région URL ['OTHER'] / titre ∅ ; édition URL ['EDITION_WORD'] / titre ['EDITION_WORD'] ; livraison ∅

**My Nintendo Store UK** (155, classe A)

- titre : `Metroid Ravenous`  
  URL : `https://nintendo-uk.pxf.io/c/1297091/2161725/22585?prodsku=000000000010019510&u=https%3A%2F%2Fstore.nintendo.com%2Fen-gb%2Fmetroid-ravenous-000000000010019510`  
  lu — plateforme URL ['SWITCH'] / titre ∅ ; région URL ['UK'] / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Pikmin 4 – Nintendo Switch 2 Edition + Dandori Academy Upgrade Pack`  
  URL : `https://nintendo-uk.pxf.io/c/1297091/2161725/22585?prodsku=000000000010016441&u=https%3A%2F%2Fstore.nintendo.com%2Fen-gb%2Fpikmin-4-nintendo-switch-2-edition-da`  
  lu — plateforme URL ['SWITCH2', 'SWITCH'] / titre ['SWITCH2', 'SWITCH'] ; région URL ['UK'] / titre ∅ ; édition URL ['EDITION_WORD', 'DLC'] / titre ['EDITION_WORD', 'DLC'] ; livraison ∅

**vidaplayer** (67, classe A)

- titre : `1 Month Game Pass Essential (USA) (Xbox Live)`  
  URL : `https://www.vidaplayer.com/en/product/game-pass-xbox-live-usa/1-month-game-pass-essential`  
  lu — plateforme URL ['MSSTORE', 'XBOX'] / titre ['MSSTORE', 'XBOX'] ; région URL ['US'] / titre ['US'] ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `12 Month Game Pass Essential (USA) (Xbox Live)`  
  URL : `https://www.vidaplayer.com/en/product/game-pass-xbox-live-usa/12-month-game-pass-essential`  
  lu — plateforme URL ['MSSTORE', 'XBOX'] / titre ['MSSTORE', 'XBOX'] ; région URL ['US'] / titre ['US'] ; édition URL ∅ / titre ∅ ; livraison ∅

**KeyeKey** (120, classe A)

- titre : `Cuphead - The Delicious Last Course Nintendo eShop United States`  
  URL : `https://www.keyekey.com/nintendo-games/cuphead-the-delicious-last-course-nintendo-eshop-united-states`  
  lu — plateforme URL ['SWITCH'] / titre ['SWITCH'] ; région URL ['US'] / titre ['US'] ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Grand Theft Auto VI PS5 UNITED STATES (The Code in Box)`  
  URL : `https://www.keyekey.com/ps5-games/grand-theft-auto-vi-ps5-united-states-the-code-in-box`  
  lu — plateforme URL ['PS5'] / titre ['PS5'] ; région URL ['US', 'ASIA'] / titre ['US', 'ASIA'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']

**PremiumCdkey** (60, classe A)

- titre : `Dead Dragons Steam (PC) - Steam CD Key - GLOBAL`  
  URL : `https://www.premiumcdkeys.com/products/dead-dragons-steam-pc-steam-cd-key-global`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['GLOBAL'] / titre ['GLOBAL'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']

**Keycense** (130, classe B)

- titre : `Wanderburg | Steam Altergift`  
  URL : `https://www.keycense.com/wanderburg-steam-altergift`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']
- titre : `RoadCraft Year 1 Anniversary Edition | Steam`  
  URL : `https://www.keycense.com/roadcraft-year-1-anniversary-edition-steam`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ['EDITION_WORD', 'COMPLETE'] / titre ['EDITION_WORD', 'COMPLETE'] ; livraison ∅

**eTailCard** (152, classe B)

- titre : `Nintendo SE 1000 SEK`  
  URL : `https://etailcard.com/nintendo-sweden-nintendo-se-1000-sek-1357151`  
  lu — plateforme URL ['SWITCH'] / titre ['SWITCH'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Amazon SE 1000 SEK`  
  URL : `https://etailcard.com/amazon-sweden-amazon-se-1000-sek-4013418`  
  lu — plateforme URL ∅ / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅

**GameBoost** (157, classe B)

- titre : `Wardogs (PC) - Steam Key - Canada`  
  URL : `https://gameboost.com/wardogs-pc-steam-key-canada-00-78982`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['OTHER'] / titre ['OTHER'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']
- titre : `Wardogs (PC) - Steam Key - Turkey`  
  URL : `https://gameboost.com/wardogs-pc-steam-key-turkey-00-78980`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['TR'] / titre ['TR'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']

**LdShop** (169, classe B)

- titre : `Grand Theft Auto V(Xbox)(US)`  
  URL : `https://www.ldshop.gg/card/grand-theft-auto-v-xbox.html?compare=ak&skuId=20738&skuLabelId=1&source=allkeyshop&shareuid=9007311&channel=9007311&utm_source=allkey`  
  lu — plateforme URL ['XBOX'] / titre ['XBOX'] ; région URL ∅ / titre ['US'] ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Wuthering Waves - 6480+1600 Lunites Direct Top-Up - GLOBAL`  
  URL : `https://www.ldshop.gg/top-up/wuthering-waves.html?compare=ak&skuId=11170&skuLabelId=1&source=allkeyshop&shareuid=9007311&channel=9007311&utm_source=allkeyshop`  
  lu — plateforme URL ∅ / titre ∅ ; région URL ∅ / titre ['GLOBAL'] ; édition URL ∅ / titre ∅ ; livraison ∅

**GamesPlanet FR** (55, classe B)

- titre : `Dunebound Tactics`  
  URL : `https://fr.gamesplanet.com/game/dunebound-tactics-steam-key--8717-1`  
  lu — plateforme URL ['STEAM'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['KEY']
- titre : `Dying Light 2: Stay Human Digital Extras Edition`  
  URL : `https://fr.gamesplanet.com/game/dying-light-2-stay-human-digital-extras-edition-steam-key--4168-4`  
  lu — plateforme URL ['STEAM'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ['EDITION_WORD'] / titre ['EDITION_WORD'] ; livraison ['KEY']

**Electronicfirst** (70, classe B)

- titre : `Worm In Rotating Land PC Steam CD Key`  
  URL : `https://www.electronicfirst.com/worm-in-rotating-land-pc-steam-cd-key`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['ASIA'] / titre ['ASIA'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']
- titre : `Warhammer 40,000: Dawn of War IV Commander Edition EU/NA PC Steam CD Key`  
  URL : `https://www.electronicfirst.com/warhammer-40000-dawn-of-war-iv-commander-edition-euna-pc-steam-cd-key`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ['EU', 'US'] ; édition URL ['EDITION_WORD'] / titre ['EDITION_WORD'] ; livraison ['KEY']

**Royalcdkeys** (85, classe B)

- titre : `Dungeons of Blood and Dream PC Steam CD Key`  
  URL : `https://royalcdkeys.com/products/dungeons-of-blood-and-dream-pc-steam-cd-key`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['KEY']
- titre : `WARDOGS PC Steam CD Key`  
  URL : `https://royalcdkeys.com/products/wardogs-pc-steam-cd-key`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['KEY']

**GamingDragons** (41, classe B)

- titre : `Wanderburg`  
  URL : `https://www.gamingdragons.com/en/game/buy-wanderburg-steam-key.html`  
  lu — plateforme URL ['STEAM'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['KEY']
- titre : `FINAL FANTASY VII REVELATION PREMIUM EDITION`  
  URL : `https://www.gamingdragons.com/en/game/buy-final-fantasy-vii-revelation-premium-edition-steam-key.html`  
  lu — plateforme URL ['STEAM'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ['EDITION_WORD', 'PREMIUM'] / titre ['EDITION_WORD', 'PREMIUM'] ; livraison ['KEY']

**CDKeys** (40, classe B)

- titre : `Egging On PC`  
  URL : `https://go.loaded.com/c/1297091/2640470/18216?u=https://www.loaded.com/egging-on-pc-steam`  
  lu — plateforme URL ['STEAM'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Earth Must Die PC`  
  URL : `https://go.loaded.com/c/1297091/2640470/18216?u=https://www.loaded.com/earth-must-die-pc-steam`  
  lu — plateforme URL ['STEAM'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅

**Playerland** (163, classe B)

- titre : `shapez 2 - Factory Steam`  
  URL : `https://player.land/en/p-6055/9967-shapez-2-factory-steam`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Sniper: Ghost Warrior Trilogy Steam`  
  URL : `https://player.land/en/p-6017/9871-sniper-ghost-warrior-trilogy-steam`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅

**Ubisoft UK** (133, classe B)

- titre : `For Honor – The Keeper of Chains – Conqueror Hero Skin`  
  URL : `https://ubisoft.pxf.io/c/1297091/1211351/12050?prodsku=6939343126c8415fc5ce21f5&u=https%3A%2F%2Fstore.ubisoft.com%2F6939343126c8415fc5ce21f5.html&intsrc=CATF_92`  
  lu — plateforme URL ['UBISOFT'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `For Honor – Battle Bundle – Y10S3`  
  URL : `https://ubisoft.pxf.io/c/1297091/1211351/12050?prodsku=693933c626c8415fc5ce21f4&u=https%3A%2F%2Fstore.ubisoft.com%2F693933c626c8415fc5ce21f4.html&intsrc=CATF_92`  
  lu — plateforme URL ['UBISOFT'] / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ['DLC'] ; livraison ∅

**StartSelect DE** (105, classe B)

- titre : `Steam Karte €60`  
  URL : `https://startselect.com/steam/72532?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Steam Karte €80`  
  URL : `https://startselect.com/steam/72533?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅

**StartSelect FR** (146, classe B)

- titre : `Carte Steam €35`  
  URL : `https://startselect.com/steam/74360?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Steam Gift Card €50`  
  URL : `https://startselect.com/steam/74457?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

**StartSelect NL** (148, classe B)

- titre : `Steam Cadeaukaart €35`  
  URL : `https://startselect.com/steam/74360?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Steam Gift Card €50`  
  URL : `https://startselect.com/steam/74457?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

**StartSelect IT** (149, classe B)

- titre : `Card Steam €35`  
  URL : `https://startselect.com/steam/74360?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Steam Gift Card €50`  
  URL : `https://startselect.com/steam/74457?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

**StartSelect GB** (151, classe B)

- titre : `Steam Gift Card €35 (EURO accounts only)`  
  URL : `https://startselect.com/steam/74360?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']
- titre : `Steam Gift Card £35`  
  URL : `https://startselect.com/steam/74454?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

**StartSelect ES** (147, classe B)

- titre : `Tarjeta Steam €35`  
  URL : `https://startselect.com/steam/74360?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Steam Gift Card €50`  
  URL : `https://startselect.com/steam/74457?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

**StartSelect PT** (150, classe B)

- titre : `Cartao Steam €35`  
  URL : `https://startselect.com/steam/74360?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Steam Gift Card €50`  
  URL : `https://startselect.com/steam/74457?_ef_transaction_id=&utm_source=everflow&utm_medium=affiliate&oid=1&affid=12`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

**Keys4us** (121, classe B)

- titre : `Windows 10/11 Professional Digital Licence – Online Activation  Special Offer`  
  URL : `https://keys4us.com/product/%f0%9f%94%a5-windows-10-11-professional-digital-licence-online-activation-%f0%9f%94%a5-special-offer/`  
  lu — plateforme URL ['MSSTORE'] / titre ['MSSTORE'] ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅

**Wyrel** (162, classe B-)

- titre : `AENTITY (PC) Standard Europe Steam Gift`  
  URL : `https://wyrel.com/en/buy-cheap-aentity-gift-74354?referal=allkeyshop&marketplace_id=2&edition_id=780&region=4&coupon=allkeyshop`  
  lu — plateforme URL ∅ / titre ['STEAM'] ; région URL ['OTHER'] / titre ['EU'] ; édition URL ['EDITION_WORD'] / titre ['STANDARD'] ; livraison ['GIFT']
- titre : `Damage Sadistic Butchering of Humanity (PC) Standard Global Steam Gift`  
  URL : `https://wyrel.com/en/buy-cheap-damage-sadistic-butchering-of-humanity-gift-52213?referal=allkeyshop&marketplace_id=2&edition_id=780&region=1&coupon=allkeyshop`  
  lu — plateforme URL ∅ / titre ['STEAM'] ; région URL ['OTHER'] / titre ['GLOBAL'] ; édition URL ['EDITION_WORD'] / titre ['STANDARD'] ; livraison ['GIFT']

**Muve** (166, classe B-)

- titre : `Bomber Crew - Deluxe Edition (PC Steam) (ROW)`  
  URL : `https://muve.games/p/bomber-crew-deluxe-edition-pc-steam-row-2403601?affiliate_code=allkeyshop`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['GLOBAL'] / titre ['GLOBAL'] ; édition URL ['EDITION_WORD', 'DELUXE'] / titre ['EDITION_WORD', 'DELUXE'] ; livraison ['KEY']
- titre : `Bomber Crew (PC Steam) (ROW)`  
  URL : `https://muve.games/p/bomber-crew-pc-steam-row-2403600?affiliate_code=allkeyshop`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['GLOBAL'] / titre ['GLOBAL'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']

**Cdkeysales** (69, classe B-)

- titre : `Super Duolingo 1 Year Subscription`  
  URL : `https://www.cdkeysales.com/super-duolingo-1-year-subscription.html?currency=EUR`  
  lu — plateforme URL ∅ / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅
- titre : `Super Duolingo MAX 1 Year Subscription`  
  URL : `https://www.cdkeysales.com/super-duolingo-max-1-year-subscription.html?currency=EUR`  
  lu — plateforme URL ∅ / titre ∅ ; région URL ∅ / titre ∅ ; édition URL ∅ / titre ∅ ; livraison ∅

**SCDKey** (4, classe B-)

- titre : `Lossless Scaling Steam CD Key Global`  
  URL : `https://www.scdkey.com/lossless-scaling-steam-cd-key-global.html`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['GLOBAL'] / titre ['GLOBAL'] ; édition URL ∅ / titre ∅ ; livraison ['KEY']

**GamersOutlet** (31, classe B-)

- titre : `Hunt: Showdown 1896 – Sage of Joseon DLC (PC Steam Key / Global)`  
  URL : `https://www.gamers-outlet.net/en/hunt-showdown-1896-–-sage-of-joseon-pc-steam-key-global`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['GLOBAL'] / titre ['GLOBAL'] ; édition URL ∅ / titre ['DLC'] ; livraison ['KEY']
- titre : `Train Valley 2: Workshop Gems - Onyx DLC (PC Steam Key / Global)`  
  URL : `https://www.gamers-outlet.net/en/train-valley-2-workshop-gems-onyx-pc-steam-key-global`  
  lu — plateforme URL ['STEAM'] / titre ['STEAM'] ; région URL ['GLOBAL'] / titre ['GLOBAL'] ; édition URL ∅ / titre ['DLC'] ; livraison ['KEY']

**Lootbar.gg** (165, classe B-)

- titre : `100 G-Coin Global`  
  URL : `https://www.lootbar.com/gift-card/pubgcoins?assetid=678109&activate=direct`  
  lu — plateforme URL ∅ / titre ∅ ; région URL ∅ / titre ['GLOBAL'] ; édition URL ∅ / titre ∅ ; livraison ['GIFT']
- titre : `500+10 G-Coin Global`  
  URL : `https://www.lootbar.com/gift-card/pubgcoins?assetid=565199&activate=direct`  
  lu — plateforme URL ∅ / titre ∅ ; région URL ∅ / titre ['GLOBAL'] ; édition URL ∅ / titre ∅ ; livraison ['GIFT']

## Exemples classe C (page marchand nécessaire)

- **Eldorado** (145) — `CD Keys - Haste (PC) - Steam Key` — `https://www.eldorado.gg/cd-keys/v/283?te_v1=0-20`
- **GameBillet** (15) — `Total War: WARHAMMER III - Nagash – Lords of the End Times` — `https://www.gamebillet.com/total-war-warhammer-iii-nagash-lords-of-the-end-times-z`
- **PlanetPlay** (156) — `Dunebound Tactics` — `https://planetplay.com/store/games/6aa7699a2ce45a710574d384/`
- **PlaySum EU** (158) — `TT Isle of Man: Ride on the Edge 2` — `https://store.playsum.live/product/6b5cc2cb-b7c1-5b56-bc6e-ecf472da64a7/tt-isle-of-man-ride-on-the-edge-2`
- **PlaySum US** (160) — `Dungeon Brawls` — `https://store.playsum.live/product/37529ab6-3147-5e70-b5c0-0f540457065c/dungeon-brawls`
- **PlaySum UK** (161) — `TT Isle of Man: Ride on the Edge 2` — `https://store.playsum.live/product/6b5cc2cb-b7c1-5b56-bc6e-ecf472da64a7/tt-isle-of-man-ride-on-the-edge-2`
- **DiscoverGames** (168) — `Pathogenic` — `https://discover.games/games/pathogenic`
- **GreenManGaming** (22) — `Deep Rock Galactic` — `https://greenmangaming.sjv.io/c/1297091/1272000/15105?prodsku=Deep%20Rock%20Galactic%20ZTORM%20-%20PC&u=https%3A%2F%2Fwww.greenmangaming.com`
- **GamersGate** (27) — `Project Motor Racing: V8 Power Pack` — `https://www.gamersgate.com/product/project-motor-racing-v8-power-pack/?aff=allkeyshop`
- **GOG** (34) — `Stones Keeper: Director’s Cut` — `https://www.gog.com/en/game/stones_keeper_directors_cut`
- **DreamGame** (52) — `Dunebound Tactics` — `https://www.dreamgame.com/en/dunebound-tactics?affiliate=allkeyshop`
- **SoftwareCodes** (6) — `Adobe Creative Cloud 1 month` — `https://software-codes.com/product/adobe-creative-cloud-1-month-21d8c1`
- **Fanatical** (74) — `Cozy Builder` — `https://www.awin1.com/cread.php?awinmid=118821&awinaffid=303045&ued=https://www.fanatical.com/en/game/cozy-builder`
- **Pixelcodes** (82) — `Monster Hunter World: Iceborne Deluxe Kit` — `https://pixelcodes.com/product/monster-hunter-world-iceborne-deluxe-kit-140556`
- **Indiegala** (95) — `THE KING OF FIGHTERS XIV STEAM EDITION DELUXE PACK` — `https://www.indiegala.com/store/game/the-king-of-fighters-xiv-steam-edition-deluxe-pack/571260_deluxe_pack`
- **EtailMarket** (99) — `Farming Simulator 2011 - Equipment Pack 2 (Steam Version)` — `https://etail.market/farming-simulator-2011-equipment-pack-2`
- **wingamestore** (78) — `The Black Knight Chronicles - The Quest beyond Destiny: Foretold` — `https://www.wingamestore.com/product/19107/The-Black-Knight-Chronicles-The-Quest-beyond-Destiny-Foretold/?ars=cdd`
- **Yuplay** (123) — `Gears of War: E-Day Premium Upgrade + Advanced Access (PC & Xbox Series X|S)` — `https://www.yuplay.com/product/gears-of-war-e-day-premium-upgrade-pc-xbox-series-xs/`
- **Softwareload** (68) — `Web Designer 18 Premium` — `https://www.softwareload.eu/product.html?REF=863871&affil=33557`
- **HRK** (14) — `STAR WARS Zero Company Steam Edition` — `https://www.hrkgame.com/en/product/star-wars-zero-company-steam-edition`
- **EpicKeys** (159) — `Microsoft Windows 10 Home OEM & Office 2019 Pro Plus ISO, Bundle` — `https://www.epickeys.eu/microsoft-windows-10-home-oem-office-2019-pro-plus-iso-bundle-kw9-00131-bundle191`
- **Wincdkey** (132) — `Autodesk 3ds Max 2026 License Key for Windows - 1 Years` — `https://wincdkey.com/product/autodesk-3ds-max-2026-license-key/?attribute_duration=1+Years&`
- **Bitcodes** (122) — `Visio Professional 2024 Retail - Online Activation` — `https://bitcodes.co/product/visio-professional-2024-retail-online-activation/`
- **Esdcodes** (131) — `testtest` — `https://esdcodes.com/en/backup-software/testtesttest?esd=13&id_campaign=16`
