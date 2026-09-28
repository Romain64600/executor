# Audit des refus « pas de page produit AKS » (2026-09-28)

Romain : « go pour l'étude des pas de page produit ».

La question : quand le matcher refuse une offre avec le motif `no AKS product page found`,
est-ce que (a) AllKeyShop n'a vraiment pas la page, (b) la page existe et notre résolveur la
rate, ou (c) l'offre n'est pas un vrai produit ?

L'étude est en **lecture seule**. Aucune écriture AKS, aucun navigateur, aucun code modifié.
Trois agents enquêteurs ont fait 337 requêtes vers AKS, puis la contre-vérification en a fait
27 : **364 en tout**, avec l'agent « AKS/Staff », au moins 3 s d'écart et au plus deux 5xx par
agent. La production est restée saine pendant l'étude. La synthèse, les tests sur la
population entière et la correction de ce rapport ont été faits hors ligne, sans aucune
requête.

**Version corrigée (28/09, soir).** Ce rapport intègre une contre-vérification à l'aveugle des
verdicts (§1) et une revue adverse des correctifs proposés (§6). Trois lignes « absentes »
étaient en fait des pages ratées, plusieurs chiffres de synthèse étaient mal présentés, et
quatre propositions ne pouvaient pas partir telles qu'écrites. Tous les chiffres ci-dessous
sont recalculés (`corrige/recalc.py`).

---

## 0. Résumé en 5 lignes

1. **14 409 offres** sont refusées « pas de page » (14 255 lignes distinctes) : pass 9 du groupe A, plus la boucle en cours et la boucle précédente du groupe B.
2. **(a) La page manque vraiment pour 47 %** des lignes (IC 95 % : 40–54 %), soit **6 715 lignes** (5 729–7 701). Un second estimateur, calé sur les indices du sitemap, donne 57 %. Mais il dépend de l'échantillon : c'est une borne haute plausible, pas une fourchette. La liste pour l'équipe catalogue compte 7 663 produits.
3. **(b) La page existe mais le résolveur la rate pour 41 %** (34–47 %), soit 5 815 lignes. Côté console, c'est même 84 %. Mais trouver la page ne suffit pas : au rejeu, les gardes de nom (R01, R01b, R27…) bloquent 42 % des ratées (56 % de celles qu'on a pu rejouer). Ce sont des décisions déjà revues, à laisser telles quelles.
4. **(c) 3,0 % ne sont pas des produits** (monnaie de jeu, films, abonnements, bons). 9,1 % restent incertaines, dont 85 lignes Wyrel console jamais tirées.
5. **Deux correctifs rapportent l'essentiel** : retirer le nom d'édition quand le sitemap confirme la page du jeu, et reconnaître les pages console en « -key ». Avec les contraintes de la revue, ils rapportent **environ 460 à 1 150 offres**. Tous les correctifs sûrs réunis : **environ 540 à 1 320**. Le reste est une longue traîne ou attend une décision.

---

## 1. Ce qui a été mesuré, et comment

**Population.** Elle regroupe toutes les offres dont le motif de refus commence par
`no AKS product page found`, console comprise. Elle vient de trois sources :

- **A-pass9** : run `20260927-145503-auto-pass9`, ancien VPS, 10 marchands ;
- **B-courant** : run `20260926-221601-auto`, cette machine, copie figée le 2026-09-28 à 16 h 26 UTC. CJS était encore en cours. Eneba s'est arrêté sur `submit_not_clean_p24`, donc ses pages p1 à p23 n'ont jamais été matchées ;
- **B-boucle-précédente** : run `20260925-194851`, pour les marchands que la boucle en cours n'avait pas encore atteints (Wyrel, Gamerall, K4G, Electronicfirst).

Les doublons sont repliés par (marchand, titre normalisé). Cela donne 14 255 lignes, dont
12 003 PC et 2 252 console. Elles portent 14 364 identifiants d'offre distincts : **une ligne
vaut une offre, à 1 % près**. Tous les chiffres ci-dessous s'entendent donc en lignes ou en
offres indifféremment.

**Échantillon.** Il compte 340 lignes, tirées avec la graine 20260928. Il est stratifié par
(marchand, PC ou console) : au moins 15 lignes PC et 2 lignes console par marchand, le reste
en proportion du volume.

Trois enquêteurs ont jugé chaque ligne. Leurs preuves :

- le sitemap du 28/09 ;
- la page AKS lue ;
- la recherche catalogue AKS.

Chaque ligne classée « ratée » a ensuite été **rejouée hors ligne dans le vrai
`match_offer`**, avec la page trouvée injectée, pour savoir si elle serait réellement entrée.

**Contre-vérification des verdicts.** Un quatrième agent, qui n'avait pas vu les verdicts, a
tiré 30 lignes (15 ratées, 15 absentes, graine 424242). Il a rendu ses propres verdicts à
l'aveugle, puis les a comparés.

- **Accord : 29 sur 30, soit 96,7 %** (Wilson 83–99 %). Ratées : 15/15 (80–100 %). Absentes : 14/15 (70–99 %). Pour 3 absentes, faute d'accès aux sites marchands, l'accord est par défaut.
- **Le désaccord** : Wyrel « Starpoint Gemini 2 Gold Pack (DLC) Standard PC Global ». L'enquêteur l'avait classée absente (« page Xbox seulement »). Or la page PC du jeu, <https://www.allkeyshop.com/blog/buy-starpoint-gemini-2-cd-key-compare-prices/>, a le seau 603 « Gold Pack », avec 9 offres vivantes.
- **La même erreur hors tirage.** Les enquêteurs ont contrôlé les slugs, mais pas toujours les seaux déjà vendus sur la page du jeu de base. Un balayage ciblé des 145 absentes de l'échantillon (titre avec Pack, Edition, Collection… et page du jeu de base au sitemap) sort 17 candidates. Sur les 5 vérifiées :
  - GOG « Alone in the Dark: The Trilogy 1+2+3 » : erreur confirmée, le seau 5246 « Trilogy Bundle » existe ;
  - MMOGA « Destiny 2: The Collection » : erreur probable, le seau 98 « Collection » existe (6 offres) ;
  - Arizona Sunshine Remake Upgrade et Sonny Legacy Collection : verdict juste.
  - Les 12 autres lignes (11 produits) ne sont pas vérifiées. Elles sont signalées « à revérifier » dans `pages_absentes.csv`.
- **Correction appliquée** : les trois lignes passent d'absente à ratée. Elles n'ont pas été rejouées dans `match_offer`, donc elles comptent en « rejeu incomplet ».

**Extrapolation.** L'estimateur de référence est stratifié, avec correction de population
finie (Cochran). L'intervalle vaut ±1,96 σ. Les parts par marchand utilisent un intervalle de
Wilson par strate, calculé sur un n effectif corrigé de la population finie.

La strate Wyrel console (165 lignes) est post-stratifiée. Ses 3 lignes tirées sont toutes de
la monnaie « skate SV Bucks » ; elles ne représentent que les 80 lignes de monnaie. Les 85
autres lignes n'ont aucun représentant : elles comptent « incertaines (non échantillonnées) »,
sans variance, et ne sont imputées à aucun verdict. On y trouve de vrais jeux : Pokemon
Scarlet, Mario Tennis Fever (Switch 2), Just Dance 2026, EA Sports WRC, des DLC Sims 4.

Un second estimateur est **calé** sur cinq groupes d'indices hors ligne. Ces groupes sont
connus pour les 14 255 lignes :

- aucun indice (9 286 lignes) ;
- un correctif déterministe du §4 retrouve une page (2 037) ;
- seul un voisin flou existe au sitemap (2 728) ;
- motif de non-produit (175) ;
- page déjà listée au sitemap du run, refusée plus loin (29). Aucune ligne de l'échantillon n'y tombe : ces lignes comptent « ratées », puisque la page existe par définition.

**Les deux estimateurs n'encadrent pas la réponse.** Le calé n'est pas indépendant de
l'échantillon. Le groupe « un correctif retrouve la page » pèse 25 % de l'échantillon pondéré
contre 14 % de la population, et le groupe « aucun indice » 51 % contre 65 %. Deux
explications sont possibles : le hasard sur des strates lourdes, ou des règles écrites à
partir des lignes de l'échantillon elles-mêmes. Pour EDITION, l'échantillon est touché
1,8 fois plus que la population ; pour BRUIT, 6,2 fois. Dans le second cas, le calé surestime
les absentes. Le stratifié fait donc foi, et le calé sert de borne haute plausible.

**Tests sur la population entière.** Chaque correctif candidat a été appliqué aux 14 255
lignes avec le vrai code du matcher : `cleaned_title`, `build_slug_candidates`,
`classify_console` et l'index sitemap du 28/09 (213 780 pages). On compte les lignes pour
lesquelles le correctif ferait sonder une URL **que l'index publie**. C'est la *portée*.

Le *gain estimé* vaut la portée multipliée par la part qui entre au rejeu, parmi les lignes
de l'échantillon que le même test touche. Si une ligne absente ou incertaine est touchée,
elle compte pour 0. Quand le test ne touche pas 5 lignes de l'échantillon, on prend le taux le
plus prudent entre ce test et la conversion de la famille dans l'échantillon. Les portées
tiennent compte des contraintes de la revue adverse (§6).

## 2. Les chiffres

| Verdict | Lignes (estimation stratifiée) | IC 95 % | Part | Estimateur calé (IC approx.) |
|---|---|---|---|---|
| **(a) page absente d'AKS** | **6 715** | 5 729 – 7 701 | 47 % (40–54) | 8 081 (7 083 – 9 079) |
| **(b) page présente, ratée par le résolveur** | **5 815** | 4 919 – 6 711 | 41 % (34–47) | 4 587 (3 729 – 5 446) |
| (c) pas un produit | 428 | 126 – 731 | 3,0 % (0,9–5,1) | 233 (69 – 397) |
| incertaine | 1 297 | 719 – 1 875 | 9,1 % (5,0–13,2) | 1 354 (659 – 2 049) |

Chaque colonne fait 14 255. L'incertaine compte les 85 lignes Wyrel console non
échantillonnées.

| Découpage | Absente | Ratée | Pas un produit | Incertaine |
|---|---|---|---|---|
| PC (12 003) | 55 % (6 567) | 33 % (3 923) | 2,8 % | 9,8 % |
| Console (2 252) | 7 % (148) | **84 % (1 892 ; IC 1 657–2 127)** | 3,9 % | 5,5 % |
| Groupe A (5 414) | 56 % | 36 % | 1,5 % | 6,8 % |
| Groupe B (8 841) | 42 % | 44 % | 3,9 % | 10,5 % |

Par marchand (IC 95 % entre parenthèses). La dernière colonne donne le nombre de lignes de la
population qu'un correctif déterministe (§4) retrouve. GOG, MMOGA et Wyrel sont corrigés (§1).

| Marchand | Groupe | Lignes (PC / console) | Éch. | Absente | Ratée | Pas un produit | Incertaine | Correctif déterministe |
|---|---|---|---|---|---|---|---|---|
| Kinguin | B | 3 693 (3 505 / 188) | 28 | 64 % (46–81) | 20 % (8–38) | 4 % (1–21) | 11 % (4–31) | 136 |
| GameSeal | A | 2 377 (2 298 / 79) | 24 | 64 % (44–82) | 31 % (15–52) | 0 % (0–17) | 5 % (1–24) | 215 |
| GOG | A | 1 601 (1 601 / 0) | 20 | 60 % (39–78) | 40 % (22–61) | 0 % (0–16) | 0 % (0–16) | 72 |
| Wyrel | B | 1 506 (1 341 / 165) | 22 | 33 % (17–55) | 47 % (28–68) | 5 % (2–20) | 15 % (8–36) | 171 |
| Eneba | B | 1 277 (575 / 702) | 23 | 28 % (12–60) | 64 % (34–82) | 0 % (0–30) | 8 % (3–40) | 459 |
| Gamivo | B | 976 (402 / 574) | 21 | 23 % (14–57) | 72 % (39–82) | 0 % (0–33) | 5 % (2–40) | 384 |
| CJS-CDKeys | B | 813 (524 / 289) | 21 | 11 % (4–44) | 66 % (35–80) | 11 % (4–44) | 11 % (4–44) | 215 |
| G2A | A | 672 (593 / 79) | 20 | 36 % (19–63) | 29 % (11–52) | 5 % (1–30) | 30 % (13–56) | 118 |
| Gamerall | B | 347 (296 / 51) | 18 | 0 % (0–25) | 95 % (67–99) | 5 % (1–33) | 0 % (0–25) | 105 |
| Gamesplanet FR | A | 148 (148 / 0) | 15 | 13 % (4–36) | 60 % (37–80) | 0 % (0–19) | 27 % (11–51) | 21 |
| MMOGA | A | 145 (129 / 16) | 17 | 6 % (1–32) | 77 % (51–92) | 17 % (5–42) | 0 % (0–24) | 43 |
| Instant Gaming | A | 142 (142 / 0) | 15 | 100 % (81–100) | 0 % (0–19) | 0 % | 0 % | 5 |
| Driffle | A | 138 (112 / 26) | 17 | 62 % (32–79) | 22 % (9–53) | 16 % (6–48) | 0 % | 10 |
| K4G | B | 123 (108 / 15) | 17 | 41 % (23–68) | 24 % (8–49) | 12 % (4–39) | 24 % (8–49) | 20 |
| GameBoost | A | 112 (55 / 57) | 17 | 10 % (4–54) | 84 % (40–92) | 0 % | 6 % (2–50) | 40 |
| Electronicfirst | B | 106 (96 / 10) | 17 | 71 % (46–88) | 18 % (7–45) | 0 % | 11 % (2–33) | 8 |
| Discover.games | A | 66 (66 / 0) | 15 | 40 % (22–62) | 47 % (27–68) | 0 % | 13 % (4–35) | 12 |
| GamersOutlet | A | 9 | 9 (tout) | 78 % | 22 % | 0 % | 0 % | 3 |
| Loaded | A | 4 | 4 (tout) | 50 % | 50 % | 0 % | 0 % | 0 |

Deux profils se dégagent :

- **Kinguin, GameSeal, GOG, Instant Gaming et Electronicfirst** : la page manque le plus souvent. Ce sont de petits jeux Steam récents, des DLC GOG et des logiciels.
- **Gamerall, Gamivo, Eneba, CJS, MMOGA et GameBoost** : la page existe le plus souvent et nous la ratons. Chez Eneba et Gamivo, c'est surtout la console.

## 3. (a) Pages vraiment absentes

Extrapolé à la population :

| Nature | Lignes | IC 95 % |
|---|---|---|
| Page à créer (jeu ou logiciel) | 5 414 | 4 479 – 6 350 |
| Page à créer (DLC ou contenu) | 1 009 | 571 – 1 448 |
| AKS n'a que d'autres plateformes (console seule ou PC seul) | 133 | 0 – 288 |
| **Page existante, édition à ajouter** | 88 | 14 – 162 |
| **Page existante, plateforme à ajouter** (Meta Quest) | 69 | 0 – 152 |

La version précédente comptait environ 172 lignes de trop en DLC : VMware vSphere Hypervisor
(poids 140), MS SQL Server 2022 (25) et Kingdom Eighties Rad Deluxe Edition (7), qui sont du
logiciel ou un jeu. Elles sont reclassées.

Exemples vérifiés, où la recherche catalogue AKS ne renvoie rien :

- Kinguin « Aura Farming PC Steam CD Key » (<https://www.kinguin.net/category/555404/aura-farming-pc-steam-cd-key>) ;
- GameSeal « Picaro (PC) Steam Gift - GLOBAL » ;
- Instant Gaming « Capybara Simulator » ;
- le DLC GOG « Europa Universalis IV: The Rus Awakening ».

Les **éditions à ajouter** ne sont **pas** des pages à créer, car la page existe déjà. Deux
exemples, que la contre-vérification demande de relire (§1) :

- « Farming Simulator 25 Beans & Alpacas Edition » (Instant Gaming) : d'après l'enquêteur, la page <https://www.allkeyshop.com/blog/buy-farming-simulator-25-cd-key-compare-prices/> n'a pas ce seau ;
- « Dragon Ball Xenoverse 2 Blue Saiyan Edition » (K4G) : même constat sur <https://www.allkeyshop.com/blog/buy-dragon-ball-xenoverse-2-cd-key-compare-prices/>.

**Listes produites** : `/tmp/tri/` sur cette machine, et une copie dans le répertoire de
travail.

- **`pages_absentes.csv`** : 7 663 produits, 9 275 offres. Le fichier est agrégé par produit (slug de rang 1 + plateforme), une ligne par produit, trié par nombre d'offres.
  - **Retirés** : Starpoint Gemini 2 Gold Pack, Alone in the Dark: The Trilogy 1+2+3 et Destiny 2: The Collection. La page et le seau existent déjà (§1).
  - **Doublons fusionnés** : SUPERHOT VR Meta Quest, Tinhead et World End Economica Complete apparaissaient deux fois, sous deux types. Le type confirmé l'emporte.
  - 140 produits sont **confirmés** par l'échantillon : 122 pages à créer, 10 éditions à ajouter, 6 « autres plateformes seulement » et 2 plateformes à ajouter, avec l'URL AKS de la page existante.
  - **11 d'entre eux portent le statut « confirmé (échantillon), à revérifier »**. Ce sont les 12 lignes que le balayage ciblé de la contre-vérification n'a pas pu vérifier : Sonic the Hedgehog 4 Complete, Shadow of War High Resolution Texture Pack, Guardians of Graxia Map Pack, RIDE 2015 Top Bikes Pack 1, NieR Automata GOTY Upgrade (PS5), Kingdom Eighties Rad Deluxe, Bunker 21 Extended, Farming Simulator 25 Beans & Alpacas (deux produits), Dying Light The Beast RL Definitive, Dragon Ball Xenoverse 2 Blue Saiyan. La page du jeu de base vend peut-être déjà le seau.
  - 7 523 sont **prédits**. La prédiction repose sur trois conditions :
    - aucun indice au sitemap ;
    - aucun correctif du §4 ne retrouve de page ;
    - pas un non-produit.

    Par construction, aucun voisin n'existe au sitemap : la classe d'erreur du §1 (seau déjà sur la page du jeu) y est donc moins probable.
  - **Précision mesurée du « prédit » : 75 % vraiment absentes**, 14 % ratées, 10 % incertaines, sur 162 lignes de l'échantillon. Elle est **probablement optimiste** : ces lignes ont servi à écrire les règles (§1). **Avant d'envoyer la liste, vérifier environ 30 lignes neuves du groupe « aucun indice », par un agent qui n'a pas vu les règles.**
  - Répartition : 5 561 jeux, 1 427 DLC ou contenus, 675 logiciels ; 7 161 produits PC. 709 produits sont en attente chez plusieurs marchands.
- **`pages_a_verifier.csv`** : 2 022 produits, 2 705 offres. Un voisin existe au sitemap : nom plus long, suite, ou tête avant « : ». **Seulement 38 % sont vraiment absentes** (82 lignes de l'échantillon). Ne rien créer sans vérifier.

**Conséquence pour l'export vers la liste 22** (`src/sort_sql_ids.py`, fonction `partition`).
Cet export traite le sitemap comme une preuve d'absence. Or, parmi les lignes sans aucun
indice, 14 % ont en fait une page et 10 % restent douteuses. Un lot parti en 22 sur la seule
foi du sitemap contient donc environ une ligne sur sept dont la page existe. Les causes sont
un autre nom, un palier ou une ancienne forme d'URL (§4.4).

## 4. (b) Pages ratées : causes, gains, correctifs

### 4.1 Trouver la page ne suffit pas

Chacune des 144 lignes « ratées » de l'échantillon a été rejouée dans le vrai `match_offer`,
avec la page trouvée injectée. Les 3 lignes reclassées ratées par la contre-vérification ne
l'ont pas été. Résultat, pondéré sur les 5 815 lignes ratées :

| Issue du rejeu | Part |
|---|---|
| **Entre** (correctif du résolveur seul) | **21,4 %** |
| Entre si le bruit marchand est aussi retiré du nom de garde (fichier marchand) | 7,0 % |
| Entrerait si R43 reconnaissait la variante de slug comme « page propre » | 3,2 % |
| **Bloquée par une garde** : R01 (26 lignes), mots en trop (20), R27 (6), R43, R19… | **41,7 %** |
| Refusée par la branche console | 1,3 % |
| Rejeu incomplet (page console non lue, lecture de la page marchand R32 impossible hors ligne, ou ligne reclassée par la contre-vérification) | 25,3 % |

Les gardes bloquent donc 42 % de toutes les ratées, soit **56 % de celles qui ont pu être
rejouées**. En comptant les lignes qui n'entrent qu'avec le bruit marchand retiré, c'est 65 %.
Moins d'un tiers des pages ratées rapporterait donc une saisie avec un simple correctif de
slug. **Aucune proposition ci-dessous n'assouplit R01, R01b, R27, R43 ou les décisions revues
d'AGENTS.md.** Là où une garde bloque, le rapport le dit et s'arrête.

**Réserve.** 15 % du poids des lignes « entre » (Blood Bowl 2 Legendary, Wasteland 2
Director's Cut Classic, shapez 2 Supporter) reposent sur une carte d'éditions écrite à la main
par les enquêteurs, avec des identifiants non numériques (« Legendary(legendary) »). Le seau
ne vient donc pas de `_resolution_from_body`. Pour Blood Bowl 2, la contre-vérification a
confirmé que le seau existe sur la page.

### 4.2 Familles, portée sur la population entière et gain

Le classement suit le gain estimé. La « portée » compte les lignes où l'index publie l'URL
que le correctif ferait sonder, en exclusif et dans l'ordre du tableau. La colonne « après
contraintes » applique les conditions de la revue adverse (§6).

| # | Famille | Lignes ratées (éch., extrapolées) | Portée telle qu'écrite | **Portée après contraintes** | **Gain estimé** | Décision nécessaire ? |
|---|---|---|---|---|---|---|
| 1 | **Palier nommé non retiré** (« Special / King of Kings / Karakuri / Supporter Edition ») | 2 070 (1 381–2 760) | 1 079 | **1 008** | **320 – 784** | non |
| 2 | **Gabarits console « -key » / « -code »** (onglets et sondes) | 403 (88–717) | 389 | **389** | **138 – 364** | non (préalable, §6) |
| 2b | Page Xbox combinée `-xbox-key` | (inclus) | 31 | 31 | 6 – 31 | oui, pour les générations déduites |
| 3 | **Bruit marchand non retiré** (« Digital Copy », « Windows Store »…) | 963 (371–1 555), surestimé (voir note) | 92 (+24 apostrophes échappées Eneba) | **66** + 26 à décider | **36 – 66** | oui pour « KING's Drop », « EN Language », « Steam Edition » |
| 4 | Mots vides (AKS écrit `age-wonders-3`, `lego-movie-videogame`) | 147 (51–244) | 62 | **50** mots internes + 12 article en tête | **23 – 50** | oui pour l'article en tête |
| 5 | Mots de nature du DLC (« Loco Add-On », « Expansion ») | 350 (91–609) | 144 | — | 0 – 74 | oui (R43, variante de slug) |
| 6 | Chiffre romain V / X, nombre en lettres | 265 (0–542) | 86 | — | ≈ 0 sans décision (0 – 60) | oui (V/X exclus de R42 exprès) |
| 7 | Page ancienne publiée pour un slug de rang > 1 | 34 (0–74) | 35 | 35 | 9 – 35 | non (+ lecture du nom, §4.4) |
| 8 | Crochets `[ ]` gardés (MMOGA) | 34 (6–62) | 22 | **14** (slug seul) + 8 crochets porteurs de sens | ≈ 7 | oui pour Altergift chez MMOGA |
| 9 | Double titre « A / B » (« biohazard », « A.O.T. ») | 56 (0–120) | 32 | 32 | 5 – 9 | non |
| 10 | Graphie 40K (« 40.000 », ou page en « 40000 ») | 104 (0–251) | 38 | 38 | 0 – 3 | — |
| 11 | Titre CJK avec le nom anglais entre parenthèses | — | 2 | 2 | 2 | non |
| — | Nom AKS non dérivable (abréviation, mot inséré, préfixe éditeur) | 778 (367–1 189) | voir « flou » | — | 136 – 353 (éch.) | oui (alias) |
| — | Titre marchand différent (court, faute, mot en trop) | 407 (70–744) | voir « flou » | — | ≈ 7 | oui (R01) |
| — | Correspondance floue sur l'index (plafond) | — | 2 253 | — | 84 – 195 | à écarter (R01 bloque 92 %) |
| — | Tête avant « : » | 41 | 503 | — | 43 – 55 | à écarter (surtout DLC → jeu de base) |
| — | Page hors de l'index sitemap | 120 (33–207) | non mesurable hors ligne | — | 19 – 56 (éch.) | voir §4.4 |

Notes :

- **Ligne 1.** Elle compte les 3 lignes reclassées par la contre-vérification (Starpoint, Alone in the Dark, Destiny 2). Le correctif tel qu'écrit (Edition, Version, Collection) ne couvre que Destiny 2 ; « Gold Pack » et « The Trilogy 1+2+3 » restent hors de sa portée. Son taux d'entrée a été mesuré sur les 40 lignes de l'échantillon qui ont inspiré la règle : il est probablement optimiste.
- **Ligne 3.** L'échantillon surestime cette famille. Deux lignes Kinguin « KING's Drop » y pèsent 140 chacune, alors que la population entière n'en compte que 10 (9 dans la portée). Le test sur la population entière donne la vraie portée.
- **Lignes 2, 4, 7, 10.** Le test sur la population touche moins de 5 lignes de l'échantillon. La borne basse prend donc le taux le plus prudent entre ce test et la conversion de la famille dans l'échantillon. D'où LEGACY 9–35 et MOTS-VIDES 23–50. La version précédente avait pris 10 et 40 sans le dire.

**Total des correctifs sûrs, après contraintes : environ 540 à 1 320 offres.** Ce total couvre
les familles 1, 2, 3 (partie sûre), 4 (mots internes), 7, 8 (slug seul), 9, 10 et 11. Les
familles 1 et 2 en font environ 85 % (460 – 1 150). Les parties qui attendent une décision
(2b, 5, 6, et une part de 3, 4 et 8) n'y sont pas. Tous les correctifs tels qu'écrits,
décisions comprises, donneraient 680 – 1 600, mais certains au prix de saisies fausses (§6).

### 4.3 Exemples réels

1. **Palier nommé.** GameSeal « The Secret of Monkey Island: Special Edition (PC) Steam Key » : le slug tenté `the-secret-of-monkey-island-special` n'existe pas. La page de base <https://www.allkeyshop.com/blog/buy-the-secret-of-monkey-island-cd-key-compare-prices/> a le seau Special (41). Au rejeu, la ligne **entre** en STEAM EU, Special(41). Même cas pour :
   - G2A « WWE 2K26 | King of Kings Edition » : <https://www.allkeyshop.com/blog/buy-wwe-2k26-cd-key-compare-prices/>, seau 10860 ;
   - GOG « Ground Control 2: Operation Exodus Special Edition ».

   Le repli de rang 2 (`_TRAILING_EDITION_PHRASES`) ne connaît que Deluxe, Gold, Complete, etc. **Contre-exemple** : « Destiny 2: The Collection » atteindrait `destiny-2` sans aucun mot en trop, donc en Standard(1), alors que la page a le seau Collection (98). C'est pourquoi ce rang ne doit jamais mener à Standard(1) (§6).
2. **Gabarits console.** Eneba « Priest Simulator: Vampire Show (Xbox Series X|S) » : AKS publie <https://www.allkeyshop.com/blog/buy-priest-simulator-vampire-show-xbox-series-key-compare-prices/>. Au rejeu, la ligne **entre** en Xbox Series EU Game Code (302). Pourtant la branche console ne sonde que `-xbox-one` et `-xbox-series`, et `extract_console_pages` ignore les onglets `-xbox-one-key`, `-xbox-series-key`, `-xbox-one-code` et `-xbox-series-x`. Parmi les 298 lignes console dont l'ancre PC est listée et la génération déduite (Eneba surtout), environ 250 ont leurs pages Xbox sous ces gabarits.
   - G2A « NHL 27 | Deluxe Edition (Xbox Series X/S) » : sa page est la page combinée <https://www.allkeyshop.com/blog/buy-nhl-27-xbox-key-compare-prices/>, méta Series. Aujourd'hui personne ne sonde `-xbox-key`. Au rejeu, avec ce gabarit sondé et rangé en Series, la ligne entre en Xbox Series, Deluxe(7).
   - Eneba « Grizzy and the Lemmings - Crazy Party XBOX LIVE Key » est refusée. Sa page `-xbox-key` se déclare Series alors que la ligne vise aussi One. C'est la décision 2b.
   - **Contre-exemple** : Driffle « Assassin's Creed Chronicles China (Europe) (Xbox One / Xbox Series X|S) ». `classify_console` efface CHINA comme mot de région. Le correctif trouverait alors la page générique ou la trilogie, et l'épisode Chine seul y entrerait. D'où le préalable du §6.
3. **Bruit marchand.**
   - Kinguin « Balatro PC Steam CD Key KING's Drop » : la page <https://www.allkeyshop.com/blog/buy-balatro-cd-key-compare-prices/> existe. Aujourd'hui R01 refuse sur KINGS / DROP. Une fois le suffixe retiré du nom de garde, la ligne entre en STEAM GLOBAL. Mais on ignore ce qu'est un « KING's Drop » : les URL sont à code aléatoire, c'est à Romain de trancher.
   - CJS « Verdun Digital Copy CD Key (Xbox One) » : la page <https://www.allkeyshop.com/blog/buy-verdun-xbox-one-compare-prices/> existe. Sans « Digital Copy », la ligne entre en Xbox One Game Code.
4. **Crochets.** MMOGA « The Last of Us : Part I [PC] [Steam] » → <https://www.allkeyshop.com/blog/buy-the-last-of-us-part-i-cd-key-compare-prices/> : la ligne entre. **Contre-exemple rejoué dans le vrai `match_offer`** : « Firewatch [EU Steam Altergift] ». Aujourd'hui, elle est refusée (« extra words: ['ALTERGIFT'] »). Avec les crochets retirés du nom de garde, elle entrerait en **STEAM EU(9), le seau des clés**, alors que la même ligne chez K4G va en STEAM GIFT EU(259). Il faut donc retirer les crochets du slug seulement.
5. **Mots vides.** Gamerall « Age of Wonders III (Steam) » → <https://www.allkeyshop.com/blog/buy-age-wonders-3-cd-key-compare-prices/> : la ligne entre en STEAM GLOBAL (mot interne « of »). À l'inverse, Eneba « Flynn & Freckles » reste refusée (« missing AKS words: ['AND'] »). C'est la décision revue sur « & », à laisser telle quelle.
6. **Page ancienne.** MMOGA « Borderlands 2 - Game of the Year Edition » : la page <https://www.allkeyshop.com/blog/compare-and-buy-cd-key-for-digital-download-borderlands-2/> n'est sondée que pour le slug de rang 1. Pour le slug `borderlands-2`, la ligne entre en GOTY(9).
7. **Garde qui bloque, décision revue.**
   - GameBoost « S.T.A.L.K.E.R.: Shadow of Chornobyl » → <https://www.allkeyshop.com/blog/buy-s-t-l-k-e-r-shadow-chernobyl-cd-key-compare-prices/> : R01 exige STALKER et CHERNOBYL.
   - CJS « Call of Duty: Black Ops Cold War » → <https://www.allkeyshop.com/blog/buy-cod-black-ops-cold-war-cd-key-compare-prices/> : R01 exige COD. Seule une table d'alias décidée par Romain ferait entrer ces lignes.

### 4.4 Trois défauts systémiques

**1. L'index sitemap n'est pas exhaustif.** Il n'était donc pas une preuve d'absence. Les
trois enquêteurs ont lu, chacun de leur côté, des pages vivantes que l'index ignore :

- `buy-<slug>-cd-key-digital-download-best-price/` : Sins of a Solar Empire Rebellion, Sims 3, LEGO Batman 2 ;
- `buy-call-of-duty-black-ops-2-cd-key-digital-download/` (id 336) ;
- `compare-cd-key-for-digital-download-sid-meiers-civilization-v/` ;
- le suffixe WordPress `…-compare-prices-2/` (JWE2 Dominion Biosyn) ;
- `buy-sonic-the-hedgehog-4-episode-i-xbox-360/` ;
- une page ancienne absente de la liste `legacy`, `compare-and-buy-cd-key-for-digital-download-guild-wars-2/`. `sitemap_first_probes` a donc écarté la sonde (`has_legacy` = False) ;
- une page de forme courante absente de l'index, `clue-cluedo-the-classic-mystery-game-cd-key`.

`aks_sitemap._PAGE_RE` et `_LEGACY_RE` jettent en silence toute autre forme d'URL. Environ
120 lignes ratées sont concernées d'après l'échantillon. L'effet principal porte sur la
liste 22 (§3).

**2. La recherche de secours R30 n'est jamais appelée en production.** Quand l'index est
frais, `resolve_aks` rend `None` avant la recherche : c'est la branche
`if sitemap_is_authoritative()`. Les 377 runs de page lus comptent 0 échec de recherche, ce
qui confirme qu'aucune n'a été lancée.

Il n'existe donc aucun filet pour un nom qu'on ne sait pas deviner. `?s=` est d'ailleurs mort
(délai dépassé à 20 s). En revanche, deux points d'entrée fonctionnent :

- la recherche de l'en-tête, `/blog/products/?search_name=`, qui pèse 2,8 Mo par appel ;
- l'API catalogue `…/api/v2-1-250304/vakrs_catalogv2.php?action=CatalogV2&search_name=…&fields=id,name,link,type`, qui répond environ 500 octets en 0,1 s (29 réponses 200, un 503).

**3. Le nom de certaines pages anciennes est illisible.** `extract_aks_name` lit « Compare and
Buy » sur `…-la-noire/`, `…-shogun-2/` et `…-red-orchestra-2/`, et « Compare » sur la page
Civilization V. R01 refuse alors toute ligne, même avec la bonne page. La page Borderlands 2,
elle, se lit correctement.

## 5. (c) Pas un produit

Environ 3,0 % des lignes sont dans ce cas (IC 0,9–5,1 %). La version précédente disait
3,6 % : elle extrapolait « pas un produit » aux 165 lignes Wyrel console, alors que 85
d'entre elles ne sont pas de la monnaie (§1). Côté console, la part tombe de 7,7 % à 3,9 %.

Sur la population entière, 175 lignes (179 offres) portent un motif déterministe de
non-produit. **La précision est de 14 sur 14** sur l'échantillon.

| Motif | Lignes | Exemples |
|---|---|---|
| Monnaie de jeu | 107 | Robux, SV Bucks (skate), « 7590 Echoes » (Identity V), « 9900 Unknown Cash », « 25236460 Gold » |
| Argent GTA Online, paliers « Shark » | 22 | « 3,500,000 - Whale Shark » |
| Abonnement « N Month(s) » | 22 | EA Play 12 Month, Deezer Premium 12 Month, LOTRO 12 Month Game Time |
| Film (Vudu / Paramount) | 14 | « All Quiet on the Western Front (2022) Vudu Code » |
| Clé ou boîte mystère | 7 | « Oktoberfest Chest Mystery Key », « GAMESCOM Awards Mystery Key » |
| Porte-monnaie / bon | 3 | « Mifinity eVoucher » : VOUCHER ne matche pas le mot composé |

Ces lignes sont déjà refusées, faute de page. Le vrai risque est qu'elles partent en liste 22
ou dans la liste pour le catalogue. Elles sont exclues des deux CSV.

**Attention : ces motifs ne doivent pas refuser une saisie.** Appliqués dans le matcher, ils
refuseraient de vrais produits :

- 3 lignes déjà créées sur cette machine tombent sous « une année suivie de Gold » : « Construction Simulator 2015 Gold Edition », « Car Mechanic Simulator 2015 Gold Edition », « Supreme Ruler 2020 Gold Edition » ;
- AKS a de vraies pages pour ce que visent d'autres motifs : `mystery-box-escape-the-room-*`, `feline-forensics-and-the-meowseum-mystery-key`, `eso-plus-12-months-cd-key`, `6-months-gold-xbox-live-code`, `ea-access-12-months-ps4`, `gtao-*-shark-cash-card-*`, `1000-crystals-star-wars-battlefront-2-*`.

Leur place est dans l'export de la liste 22, pas dans le pré-contrôle (proposition 8).

Deux autres lignes ont bien une page mais auraient dû être refusées pour une autre raison :

- CJS « Apocalypse Party EN/ZH/ZH » : une liste de langues, et `ZH` est absent de la regex de langue ;
- K4G « LOTR War in the North NA/AU » : le sigle de région n'est pas lu.

## 6. Propositions, classées par gain

Aucune n'a été codée : **tout attend ton go.** Chacune respecte « config par marchand » pour
ce qui relève de la grammaire d'un marchand. Chacune se relit sur un corpus figé avant d'être
fusionnée : le corpus des **lignes déjà créées**, pas seulement celui des refus.

Une revue adverse a cherché, pour chaque proposition, un contre-exemple réel. Les niveaux de
preuve sont : [a] rejoué dans le vrai `match_offer` sur une page AKS en cache ; [b] simulation
hors ligne des gardes, qui sous-estime R01 ; [c] présence dans l'index sitemap ou dans le
corpus des candidats. **Quatre propositions ne pouvaient pas partir telles qu'écrites : 1, 2,
6 et 8.** Le tableau donne leur version corrigée ; le détail suit.

| # | Proposition (version corrigée) | Où | Portée | Gain | Risque | Go |
|---|---|---|---|---|---|---|
| **1** | **Nom d'édition retiré, confirmé par l'index.** Retirer de 1 à 3 mots avant « Edition / Version / Collection » et ne sonder la base que si `has_page` la confirme. Actif seulement si `sitemap_is_authoritative()`, donc aucune sonde à l'aveugle. Ne **jamais** retirer DEFINITIVE, REMASTERED, ANNIVERSARY… (décision revue). **Trois conditions ajoutées par la revue** : (1) un rang à part, lu par `resolve_aks` seul, ajouté **après tous les rangs existants** ; (2) jamais Standard(1) par ce rang ; (3) rien retiré quand le nom complet est publié sous un autre gabarit. | `src/matcher.py` : une nouvelle fonction de rangs de repli, appelée par `resolve_aks` après `build_slug_candidates`, que `sitemap_first_probes` filtre. **Pas** dans `build_slug_candidates` | 1 008 (Gamivo, GameSeal, CJS, Eneba en tête) | **320 – 784** | Faible avec les conditions : une page de base sans le seau refuse | oui |
| **2** | **Gabarits console « -key » et « -code ».** Reconnaître `xbox-one-key`, `xbox-series-key`, `ps4-key`, `ps5-key`, `nintendo-switch-2-key`, `xbox-one-code` et `xbox-series-x` dans la barre d'onglets, chaque gabarit rattaché à sa console. Les sonder quand l'index les publie. La méta de plateforme de la page reste le juge ; P1 est inchangé. **Préalable** : garder les noms de pays dans le nom de garde console. **Ordre** : gabarit standard d'abord, « -key » en repli, refus si deux pages différentes répondent pour une même console. | `src/console_keys.py` : table gabarit → console, lue par `_PAGE_KIND_RE` et `extract_console_pages` ; `src/matcher.py` : `_console_plan` essaie tous les gabarits de la console. Ne pas allonger `CONSOLE_PAGE_KINDS` (il nourrit `_AKS_PAGE_URL_RE` et R18c). `classify_console` : noms de pays | 389, dont 298 à génération déduite (Eneba 272) | **138 – 364** | Moyen : rejoué sur 3 lignes seulement ; relecture sur un corpus Eneba figé | oui |
| 2b | Page Xbox **combinée** `-xbox-key`, rangée selon la console que la page déclare. Au rejeu, une ligne qui déclare Series entre (NHL 27). 757 slugs ont à la fois une page `-xbox-key` et une page `-xbox-one-key` ou `-series-key` : même règle de priorité et de refus qu'en 2. Pour une génération **déduite**, il faut dire si P4 vaut aussi pour une page unique. | idem | 31 | 6 – 31 | Mauvaise génération si la page se trompe | **décision** |
| **3** | **Bruit marchand** retiré dans les fichiers marchands, du nom de recherche et du nom de garde : CJS « Digital Copy », « CD Key For Battle.net: Unused… », « : Do not include… » ; Eneba « Windows (10) Store » et « \\' » échappé (24 lignes : `collector-s`, `founder-s`) ; GameSeal « â€“ » (caractères mal décodés) ; Discover « Save N% on … on Steam ». **« in-game » est retiré de la proposition** : aucune ligne touchée, et le mot fait partie de vrais noms (« RESIDENT EVIL 3 All In-game Rewards Unlock », « Football Manager 2022 In-game Editor »). | `src/merchants/cjs.py`, `eneba.py`, `gameseal.py`, `discover.py` : `guard_name` / `resolve_name` | 66 (+24 apostrophes) | **36 – 66** | Faible : chaque motif est ancré sur la grammaire du marchand | oui ; **décision** pour Kinguin « KING's Drop » (9), CJS « EN Language » (8, [R63]) et « Steam Edition » (9) |
| 4 | **Mots vides internes, côté slug seulement.** Variante sans of / a / an / and / the **à l'intérieur** du nom, sondée si l'index la confirme. R01 n'est pas touché, et « & » ≠ AND reste la règle revue. Même rang à part que 1. Jamais dans `own_page_slugs` (ce serait assouplir R43). | même fonction que 1 | 50 | 23 – 50 | Faible | oui ; **décision** pour l'article en tête (12 lignes) |
| 5 | **Pages anciennes à tous les rangs.** Proposer `compare-and-buy-…-<slug>/` pour chaque slug que `has_legacy` confirme, pas seulement le rang 1, **après** les pages console au nom complet. Lire aussi le nom des pages « Compare and Buy » / « Compare », en ne visant que ces formes anciennes. | `resolve_aks` (passe 2) ; `extract_aks_name` / `_strip_furniture_key` | 35 | 9 – 35 | Faible : R43 refuse déjà un DLC sur la page du jeu | oui |
| **6** | **Crochets MMOGA, du slug seulement.** Le nom de garde garde le contenu des crochets : une ligne Altergift reste refusée, tout comme « [Steam Game Card] » et « [Official Key] ». | `src/merchants/mmoga.py` : `resolve_name` | 14 | ≈ 7 | Faible sous cette forme | oui ; **décision** pour étendre « Altergift = Steam Gift » à MMOGA |
| 7 | **Double titre « A / B ».** Sonder A seul, puis A sans le second nom, si l'index les publie. Ne pas sonder « B seul ». | même fonction que 1 | 32 | 5 – 9 | Faible | oui |
| **8** | **Non-produits exclus de la liste 22, pas refusés au matcher.** Monnaie (Robux, Bucks, « <n> Echoes / Cash »), paliers Shark GTA, films Vudu / Paramount, eVoucher / Mifinity, « N Month(s) », clé ou boîte mystère. Motif « Gold » limité à un nombre de monnaie, jamais « <année> Gold Edition ». | `src/sort_sql_ids.py` : `non_game_reason` (que `partition` appelle déjà en premier). **Pas** `CATEGORY_SKIP` / `precheck_skip` | 175 | 0 saisie, mais hors de la liste 22 | Nul sur les saisies | oui |
| 9 | **Sitemap : compter les formes rejetées.** À chaque rafraîchissement, journaliser le nombre de `<loc>` que `_PAGE_RE` et `_LEGACY_RE` écartent, par forme. Le prochain relevé planifié dira s'il suffit d'élargir les deux expressions. **Aucune requête en plus.** | `src/aks_sitemap.py` : `refresh` | ≈ 120 (éch.) | 19 – 56 | Nul (mesure seule) | oui |
| 10 | **Liste 22 : ne pas traiter le sitemap comme une preuve.** Garder en attente les lignes que la fonction de rangs de repli (1, 4, 7) ou un correctif 2 à 6 retrouve, et annoncer au lot que ≈ 14 % des lignes restantes ont une page. | `src/sort_sql_ids.py` : `partition` | tout lot 22 | évite ≈ 1 ligne sur 7 déplacée à tort | Nul | oui |
| 11 | **Recherche catalogue AKS en dernier recours.** L'API `vakrs_catalogv2` (≈ 500 o) quand ni le slug ni l'index ne trouvent rien. Candidats seulement, gardes R01 inchangées. Il faut un budget de requêtes par balayage et un cache par titre, car les mêmes lignes reviennent à chaque boucle. L'adresse porte une version (`v2-1-250304`) qui peut changer sans préavis. Revient en partie sur « sitemap d'abord » (24/09). | `resolve_aks` / `search_aks_slugs` (R30) | 778 + 407 lignes à nom non dérivable | faible tant que R01 reste (≈ 17 % et 2 % entrent au rejeu) | Charge réseau, risque de ban | **décision** |
| 12 | Chiffres V / X et nombres en lettres, seulement si l'index confirme la variante. | `swap_numerals` / `tokenize` | 86 | ≈ 0 sans assouplir R42 | R42 exclut V / X exprès : `v-rising-*`, `sonic-x-shadow-generations-*`, `street-fighter-x-tekken-*`, `x-morph-defense-*`, `mega-man-x-*` | **décision**, à ne pas faire |

### 6.1 Ce que la revue adverse a trouvé

**Proposition 1 (nom d'édition retiré).**

- **L'emplacement change des saisies actuelles [c].** `derived_dlc_page` (R57, décision revue « ne pas l'élargir ») lit `build_slug_candidates` pour sa condition 4. Avec les nouvelles variantes, 52 titres du corpus basculent de faux à vrai : des packs Sims 4 (« The Sims 4: Lovestruck » trouve `sims-4`), mais aussi des jeux de base (« Prince of Persia: The Forgotten Sands » via `prince-persia`, « Over The Top: WWI »). D'où la fonction à part, lue par `resolve_aks` seul.
- **L'ordre compte.** `resolve_aks` rend la première page qui répond, sans consulter les gardes. Placé juste après le rang 1, le nouveau rang change la page de 15 lignes déjà créées : « Blasphemous 2 Mea Culpa Edition » → `blasphemous-2`, « ESO – Necrom Collection » → `the-elder-scrolls-online`, « EU IV – Common Sense Collection » → `europa-universalis-iv`, « Galactic Civilizations IV: Supernova Edition »… Ajouté après tous les rangs existants, il n'en change aucune.
- **Standard(1) sans seau prouvé [b].** Les mots retirés sont souvent tous dans `NOISE_TOKENS` (STEAM, WINDOWS, DIGITAL, USA, FULL, EPIC, VERSION, PRE-ORDER, COLLECTION…). Le garde des mots en trop ne voit alors plus rien, et `detect_edition` rend Standard. Mesuré sur la portée exclusive : 35 lignes. Cas faux ou douteux :
  - « FINAL FANTASY VII WINDOWS EDITION XBOX LIVE Key » irait sur des pages Xbox : mauvaise plateforme ;
  - « Marvel's Midnight Suns Digital+ Edition » : mauvais palier ;
  - « Wolfenstein The New Order DE Version » : la version allemande entrerait en GLOBAL ;
  - « Destiny 2: The Collection » : Standard au lieu de Collection (98).

  Une ligne atteinte par ce rang n'entre donc que via `edition_from_extras`, ou via un palier `detect_edition` vérifié sur la page. Coût : une quinzaine de lignes légitimes (« PC Edition », « Full Version », « Pre-Order Edition »). Ce n'est pas un assouplissement formel de R18c, qui ne vise que les pages de DLC, mais c'est son principe : sur la page du jeu, seul un seau nommé par les mots du titre est accepté.
- **Nom complet publié ailleurs.** 38 lignes de la portée exclusive ont leur nom complet publié sous un autre gabarit : `f1-25-2026-season-edition-xbox-key`, `dear-esther-landmark-edition-*`, `two-point-hospital-full-health-collection-*`. AKS les traite comme des produits distincts. La revue comptait 53 lignes et 27 lignes Standard sur son propre périmètre ; les 38 et 35 ci-dessus sont mesurés sur la portée exclusive (71 lignes en tout, portée 1 079 → 1 008).
- Les rangs à 2 ou 3 mots retirés tombent souvent sur un autre jeu : « Lifeless Planet Premier Edition » → `lifeless`, « Duke Nukem Forever Collection » → `duke-nukem`, « Kerbal Space Program: Complete Edition » → `kerbal-space`. Le garde des mots en trop les a toutes bloquées dans la simulation, mais tout repose sur lui.

**Proposition 2 (gabarits console).**

- **Un mauvais produit entrerait [b + c].** Driffle « Assassin's Creed Chronicles China (Europe) (Xbox One / Xbox Series X|S) » et « … - India (Europe) … » : `classify_console` rend « Assassin's Creed Chronicles », car CHINA et INDIA sont retirés comme mots de région. Le correctif trouverait `assassins-creed-chronicles-xbox-one-code`, et l'épisode Chine seul entrerait sur la page de la trilogie. La bonne page, `assassins-creed-chronicles-china-xbox-one`, n'est jamais sondée. Le chemin PC a corrigé ce défaut le 18/09 (`_TRAILING_NOISE_PHRASES_KEEP_COUNTRY`) ; le classifieur console, non. C'est le préalable.
- **Pages en double pour une même console** : 5 slugs en Xbox One (`star-wars-battlefront-2`, `project-cars`…), 5 en Xbox Series (`assassins-creed-valhalla`…), 11 en PS4. D'où la règle d'ordre et de refus.
- La table de la simulation (XBOX_ONE → `xbox-series-key`, XBOX_SERIES → `xbox-one-key`) **viole P1**. Une seule ligne l'a touchée (MOUTHOLE) ; il ne faut pas la recopier.
- 5 des 389 lignes reposent sur des gabarits absents de la proposition : `key-nintendo-switch-2` (4) et `ps4-game-code` (1). `nintendo-switch-key` et `ps5-game-code` n'ont aucune page dans l'index.
- Sur les pages en cache, 24 des 68 barres d'onglets relient bien des pages « -key » ou « -code » : reconnaître les onglets suffit.

**Proposition 3 (bruit marchand).** « in-game » est retiré (voir le tableau). La portée de 92
comptait 9 « Steam Edition » (absent de la proposition), 8 « EN Language » (décision [R63] en
attente) et 9 « KING's Drop », dont on ne sait pas ce qu'il désigne. Il reste 66 lignes sûres.

**Proposition 4 (mots vides).** Ce n'est pas un assouplissement de R01 côté mots requis. Mais
THE, A, AN, OF et AND sont du bruit côté mots en trop : un titre « The X » posé sur la page
« X » passe sans aucun mot en trop. L'index contient 77 paires `the-x` / `x` qu'AKS range comme
des produits distincts : `the-lords-of-the-fallen` / `lords-of-the-fallen`, `the-bunker` /
`bunker`, `the-crow` / `crow`, `the-exorcist` / `exorcist`, `the-descent` / `descent`. D'où la
limite aux mots internes. 2 lignes sont des DLC marqués (Wolfenstein II Season Pass, EU4
Cossacks) : R43 les refuse, et c'est voulu.

**Proposition 5 (pages anciennes).** Les rangs PC plus courts passeraient avant une page
console au nom complet : « Minecraft Ultimate Collection » prendrait l'ancienne page
`minecraft`, alors que `minecraft-ultimate-collection-xbox-one-key` existe. Sur les pages
anciennes en cache (Borderlands 2, Guild Wars 2, Black Ops 2), éditions, régions et plateformes
se lisent correctement.

**Proposition 6 (crochets MMOGA), bloquante telle qu'écrite [a].** « Firewatch [EU Steam
Altergift] », rejouée sur la vraie page Firewatch : refusée aujourd'hui, elle entrerait en
STEAM EU(9) si les crochets quittaient le nom de garde. MMOGA n'a pas de `gift_delivery`.
Étendre la décision « Altergift = Steam Gift » à MMOGA revient à Romain. D'ici là : slug
seulement, ce qui ramène la portée à 14 lignes.

**Proposition 7 (double titre).** Tout ce qui a été simulé est bloqué par les mots en trop ou
entre sur le même jeu (RE7, Devil Slayer Raksasi). La simulation essayait aussi « B seul »
(Sledgehammer / Gear Grinder, NIS Classics Vol. 3) : refusé, mais hors de la proposition, et à
ne pas coder.

**Proposition 8 (non-produits), bloquante dans le matcher [c].** Voir §5 : 3 lignes déjà créées
et plusieurs pages AKS réelles tombent sous les motifs. Le pré-contrôle va aussi contre la
docstring de `_category_skip_pattern` (« le chemin pas-de-page est le filtre non-jeu qui fait
autorité », « ne pas durcir »). Dans `non_game_reason`, un faux positif ne fait que retirer une
ligne de la liste 22.

**Propositions 9 et 10.** Rien à signaler. La 10 hérite de la fonction de rangs de repli.

## 7. Limites de la méthode

- **L'échantillon est petit par strate** : 15 à 28 lignes PC par marchand, 2 à 6 lignes console. Les intervalles par marchand sont larges. Les strates Kinguin PC (poids 140 par ligne), GameSeal PC (109) et Eneba console (117) pilotent les totaux. C'est pourquoi chaque famille déterministe a aussi été comptée sur la **population entière** : c'est ce chiffre qui fait foi pour la portée.
- **9 strates sur 33 ont un échantillon unanime** : 1 486 lignes à variance nulle. Le cas Wyrel console (3 lignes « SV Bucks » tirées, environ 0,06 % de chances) est corrigé par post-stratification (§1). En remplaçant les strates unanimes par (x+½)/(n+1) dans la variance, l'IC console des ratées passe de 74–94 % à 70–98 %. Les IC globaux des absentes et des ratées bougent de 0,2 point ; celui des non-produits s'élargit à 0–6,2 %.
- **Les deux estimateurs divergent** : 47 % d'absentes en stratifié contre 57 % une fois calés sur les indices hors ligne. Le calé dépend de l'échantillon (§1) et n'encadre pas le stratifié. Le stratifié fait foi. Le classement des correctifs ne change pas.
- **25 % des ratées n'ont pas pu être rejouées jusqu'au bout.** Trois raisons : des pages console jamais téléchargées (budget réseau), la lecture de la page marchand (R32) impossible hors ligne (Discover.games, Gamesplanet FR), et les 3 lignes reclassées par la contre-vérification. Les gains sont donc donnés en fourchette : la borne basse compte ces lignes comme refusées, la borne haute comme entrées.
- **15 % des lignes « entre » reposent sur une carte d'éditions écrite à la main** (§4.1).
- **Les taux d'entrée sont mesurés sur les lignes qui ont inspiré les règles**, surtout pour EDITION et BRUIT. Les gains sont donc probablement optimistes.
- **La portée repose sur l'index du 28/09**, qui a des trous (§4.4). La famille « page hors de l'index » ne se mesure donc pas hors ligne.
- **Une « absence » repose sur une recherche catalogue sans résultat et un contrôle des slugs.** La contre-vérification a montré que les seaux déjà vendus sur la page du jeu de base n'ont pas toujours été lus (§1). Un produit qu'AKS range sous un tout autre nom resterait aussi classé absent. Deux confirmations lancées à l'aveugle sur environ 31 ont basculé (MSFS sous `flight-simulator`, Guild Wars 2 en page ancienne).
- **Le groupe B est une photo.** CJS était encore en cours, Eneba s'est arrêté à p24 et ses pages p1 à p23 n'ont jamais été matchées. Wyrel, Gamerall, K4G et Electronicfirst viennent de la boucle du 25/09. Le code rejoué est celui de c85cf7f, identique à 1c8b081 pour `src/`. Une seule ligne sur 11 998 diffère du run : un effet de [R63], ajouté le 28/09.
- **Les gains sont des ordres de grandeur, pas des promesses.** Un correctif se valide par une relecture sur un corpus figé (lignes créées comprises), puis par un run sans soumission, avant toute écriture.

## 8. Fichiers

Répertoire de travail : `/root/.claude/jobs/cf6a123a/tmp/nopage/`.

| Fichier | Contenu |
|---|---|
| `population.json`, `sample_{1,2,3}.json`, `build_population.py` | population rejouée, échantillon |
| `verdicts_{1,2,3}.json` | verdicts et preuves des trois enquêteurs |
| `synth/merged_verdicts.json` | 340 verdicts fusionnés, famille unifiée, rejeu `match_offer` (version d'origine) |
| `synth/stats.json`, `synth/gains.json` | extrapolations et gains de la version d'origine |
| `synth/population_hits.json` | tests des correctifs sur les 14 255 lignes |
| `synth/fixes.py`, `synth/population_test.py`, `synth/replay_all.py` | code des tests, hors ligne, rejouable |
| `recheck/` | contre-vérification : `my_blind_verdicts.json`, `recheck_findings.json`, `cat_results.json`, `page_results.json`, `requests.jsonl` |
| `review/` | revue adverse : `guard_sim.py` / `.json`, `replay_cx.py` (Firewatch), `fix8_false_pos_candidates.json` |
| `corrige/recalc.py`, `corrige/constraints.py` | recalcul de ce rapport, hors ligne |
| `corrige/merged_verdicts_corrige.json`, `corrige/stats_corrige.json` | verdicts corrigés, chiffres, gains après contraintes |
| `corrige/build_lists_corrige.py` | reconstruction des deux CSV |
| `pages_absentes.csv`, `pages_a_verifier.csv` | listes corrigées pour l'équipe catalogue (copie dans `/tmp/tri/`) |
| `corrige/pages_absentes_v1.csv`, `corrige/pages_a_verifier_v1.csv` | listes d'avant la correction |
