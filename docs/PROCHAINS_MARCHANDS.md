# Prochains marchands : ce qu'on a étudié, et où on en est

Romain, 2026-09-25 : « Garde une trace de ce que tu étudies quand je te demande le prochain
marchand, comme ça on saura à peu près sur quel marchand continuer. »

**Mode d'emploi.** Chaque fois que Romain demande « le prochain marchand », on AJOUTE une
section datée en haut de l'historique : la mesure, le classement, ce qui bloque, la décision.
Les marchands déjà en liste blanche sont dans `src/admin/auto_merchants.py` et
[`MERCHANTS.md`](MERCHANTS.md). Ce fichier ne garde que les candidats.

## Où on en est (tenu à jour)

| Rang | Marchand (store) | Lignes en attente* | Avec une page AKS* | Ce qui manque | Statut |
|---|---|---|---|---|---|
| ✓ | **Gamesplanet FR** (55) | 526 | 339 (64 %) | — | **fait** : fichier `[R59]` et liste blanche le 25/09 (groupe A) ; essai à blanc 77 candidats / 150 lignes |
| 2 | **Gamebillet** (15) | 268 | 192 (72 %) | plateforme et région (URL et titre muets ; la page liste les pays exclus) | **fichier écrit le 06/10 (`[R71]`, branche `gamebillet`, non fusionnée), aperçu à blanc 165 entrées / 268** ; en attente des décisions de Romain (modal vide = GLOBAL ? Mortal Kombat Legacy → US ? les 11 EU ; go + groupe) |
| 3 | **Muve** (166) | 605 | 322 (53 %) | titre lisible pour ~35 % des lignes ; pas de région sur la page ; « sans région = Europe » refusé par Romain (25/09) | ~140 lignes seulement, en refusant les lignes sans région |
| 4 | **Pixelcodes** (82) + **Software-codes** (6) | 1 547 + 1 538 | 1 377 + 1 365 (89 %) | **les produits du feed n'existent plus sur leurs sites** (API : « Product not found », 52 sur 52 testés ; sites devenus boutiques de logiciels) | à ne pas saisir ; liste « not found » en cours pour les marchands |
| 5 | **Discover.games** (168) | 440 | 370 (84 %) | — | **fichier écrit le 25/09 (`[R60]`), essai à blanc : 106 candidats sur 150 lignes ; en liste blanche le 26/09, groupe A** |
| 6 | **CDKeys → « Loaded »** (40) | 16 (21/09) | — | feed du jour à relire | **fichier écrit le 25/09 (`[R61]`, « Europe & UK » → Europe, sans région → GLOBAL) ; essai à blanc sur 16 lignes : 1 candidat ; en liste blanche le 26/09, groupe A** |
| **1** | **Greenmangaming** (22) | 482 | 318 (66 %) | titre muet, mais `prodsku` dit la plateforme (PC 444, Xbox 32, PS4 5) et la **fiche** (JSON embarqué) dit tout : `Drm`, édition (`Name`), pays EXCLUS, `Code` = `prodsku` | **étudié et codé le 09/10** (`[R73]`, `greenmangaming.py`, décisions de Romain : R59 bornée + ROW prouvé, consoles avec Xbox + PC, Standard, go) ; **aperçu à blanc le 09/10 : 218 entrées / 482** (dont 32 ROW à confirmer, `apercu_greenmangaming_2026-10-09.md`) ; liste blanche et groupe sur son go après lecture |
| ✓ | **Indiegala** (95) | 175 (21/09) | 30 (19 %, slug strict) | plateforme et région : ni titre ni URL ; la **fiche** les donne (« is provided via Steam Key », listes de pays, « Region locked product ») | **fichier écrit le 06/10** (`[R69]`), **aperçu à blanc le 06/10 : 34 entrées / 175** (`apercu_indiegala_2026-10-06.md`), **liste blanche le 06/10** (Romain : « go pour la liste blanche ») ; groupe à choisir ; Belmont's Curse (EU) reste refusée (Chypre ET les USA interdits), tant que Romain n'en décide pas autrement |
| ✓ | **eww.gg** (170, id de page AKS 1011) | **~10 400** (mesuré le 09/10 pendant la première passe ; feed réimporté par AKS chaque jour) | **~70 %** (3 143 créées sur 39 h, 0 halte) | rien : grammaire = Driffle (même société, Driffle UAB), fiche lisible en HTTP | **fichier `eww.py` + liste blanche le 07/10** (instruction de Romain : « lance le data entry pour ce nouveau shop »), première passe seule depuis l'admin du 07/10, **groupe C (seul) le 09/10** (« on créera le groupe A, B et C et on lancera un groupe par machine ») |

\* Mesuré sur le scan tous-magasins du 21/09, **avant** la correction du tri du feed (`orderBy=id`,
24/09) : ces comptes sont des minimums. Un nouveau scan tous-magasins les rafraîchira.

**Déjà faits** : Gamesplanet FR (liste blanche le 25/09, `[R59]`), Wyrel (liste blanche le 24/09, `[R53]` + `[R58]`), GOG (22/09), Gamerall
(19/09), GameBoost / Electronicfirst / GamersOutlet (16/09), Difmark (21/09).

---

## 2026-10-09 — « Formons-nous sur un nouveau marchand » : Greenmangaming (store 22)

Romain : « Choisis un marchand selon nos critères, soit assez facile à rentrer et qui ait des pending
offers disponibles. » Lecture seule : les 482 lignes GMG du scan du 21/09, 16 fiches GMG lues en HTTP
(bibliothèque standard, UA navigateur, 2 s entre deux), 16 pages AKS lues (UA AKS/Staff).

**Pourquoi lui.** C'est le plus gros stock restant hors liste blanche (482 lignes, 318 avec une page AKS
d'après le nom, 66 %), et l'obstacle du 25/09 (URL d'affiliation `sjv.io` illisible) est tombé avec
`[R68]` : comme Allyouplay, le feed passe par un redirecteur (`greenmangaming.sjv.io/c/…?prodsku=…&u=…`)
dont le paramètre `u` est la fiche — `MerchantConfig.affiliate_hosts` + `url_identity_params`
savent déjà faire. Gamebillet (268 lignes) reste prêt sur sa branche, en attente des décisions de Romain.

**Ce que disent le feed et la fiche.**
- Le titre est NU (« Reus 2 - Jurassic », « Cozy Builder ») ; 42 portent ™ / ®. Le `prodsku` de l'URL
  finit par la plateforme : « - PC » 444, « - Xbox Series XS » 24, « - Xbox One » 8,
  « - PlayStation 4 » 5 (crédits PSN), « - Windows 10 » 1. Jamais la boutique ni la région.
- **La fiche `www.greenmangaming.com/games/<slug>/` se lit en HTTP (200, 16 / 16)** et embarque un JSON
  produit de 114 champs. Ceux qui comptent : `Code` (= le `prodsku` du feed, 16 / 16 — l'identité
  ligne ↔ fiche se vérifie), `GameName`, `Name` (l'édition : « Standard Edition », « Bundle »,
  « 2 Pack Edition », ou vide), `Drm` (`["steam"]` 14 fois, `["xbox-one"]` NHL 27, `["microsoft"]`
  Minecraft Windows 10), `DrmFormats` (« Digital PC Download » / « Digital XBOX Download »),
  **`ExcludedCountries`** (codes ISO-2 des pays où la clé ne s'active pas : vide 13 fois,
  `["BB","BS"]` un DLC, `["CN","HK","MO",…]` Breath of Fire IV), `SystemRequirements[].PlatformName`
  (« PC », « Xbox Series X/S »), `DisplayEditionSelector` / `AssociatedVariants`, `IsSellable`,
  `IsEarlyAccess`, `Source` (« Authorised Distributor »). La page affiche « This product has no
  regional restrictions » quand la liste est vide, sinon la liste des pays.
- **Le modèle est donc celui de Gamesplanet FR `[R59]` et d'Allyouplay `[R68]`** : plateforme = `Drm`
  de la fiche (vocabulaire à fermer : steam / xbox-one / microsoft vus ; epic, uplay, origin, gog,
  rockstar… à découvrir à l'aperçu, tout inconnu = refus), région = `[R59]` sur les pays EXCLUS
  (aucun pays d'UE / UK / USA exclu → GLOBAL ; UE sans USA → US ; USA sans UE → EU ; mélange → refus),
  édition = `Name` de la fiche croisé avec le titre, identité = `Code` == `prodsku` (sinon refus : la
  fiche montre une autre variante).
- Dans les 482 titres : 76 « Pack / Bundle / Collection » (dont des « 2 Pack » — plusieurs clés,
  à refuser), 92 à l'air de DLC (`[R43]` / R18 comme ailleurs), 73 avec un mot d'édition, 5 « (MAC) »
  (refus), 8 prépayés (crédits PSN, Game Pass — hors périmètre). Aucune ligne en rupture, aucun prix 0.

**Comment AKS range déjà Greenmangaming** (16 pages lues : 6 des titres du feed — sans prix GMG, ce
sont des lignes en attente —, puis 10 pages de gros titres hors feed) : 5 pages sur 10 portent GMG,
**Steam GLOBAL (2)** dans la plupart des cas (Hogwarts Legacy, Monster Hunter Wilds, Civilization VII,
Elden Ring ×2), mais aussi **`steamrow`** (Elden Ring Standard, Warhammer 40K Gladius) et, sur Red
Dead Redemption 2, des seaux Rockstar dont `80row`. AKS utilise donc parfois un seau « ROW » pour GMG —
sans doute quand la fiche exclut des pays d'Asie —, ce que notre règle `[R59]` rangerait en GLOBAL
(c'est ainsi qu'AKS range Gamesplanet FR, 20 / 28). `steamrow` n'est dans aucune de nos tables.

**Décisions pour Romain avant d'écrire le fichier.**
1. **Région** : `[R59]` sur `ExcludedCountries` (GLOBAL tant qu'aucun pays UE / UK / USA n'est exclu,
   même avec la Chine ou le Brésil exclus), ou un seau ROW (`steamrow`) dès qu'un pays est exclu,
   comme AKS le fait parfois pour GMG ? Dans le second cas il faut d'abord lire le menu du modal
   (règle du 16/09 : vérifier le dropdown) et étendre les tables.
2. **Consoles** : les 32 lignes Xbox (`Drm` xbox-one, `prodsku` « Xbox Series XS » / « Xbox One ») suivent-
   elles la branche console (P1, génération DÉCLARÉE par le `prodsku`) ? Les 5 crédits PSN sont refusés.
3. **Éditions sans mot dans le titre** (« Standard Edition » dans `Name`, titre nu) : Standard(1) quand la
   page AKS vend Standard — le même choix que Gamebillet / Indiegala, que Romain a laissé passer.
4. **Go pour le fichier + l'aperçu à blanc** (`03_match` hors ligne sur les 482 lignes, une requête de
   fiche par ligne, ~20 min), puis liste blanche et groupe.

Rendement attendu : 300 à 320 lignes avec une page AKS, dont il faut retirer les Mac, packs, prépayés et
les éditions non vendues par la page — de l'ordre de 150 à 220 entrées au premier passage, en Steam
GLOBAL pour l'essentiel.

**Décisions de Romain (09/10, ~10:30 UTC), mot pour mot : « go pour Greenmangaming avec ta règle R59,
1. L'executor continue de rentrer l'offre en ROW mais il vérifie que ce soit bien dispo en EU + US avant
de l'ajouter, sinon il skip 2. consoles oui mais ça peut être xbox + PC sur certaines offres, 3. Standard
oui 4. OK, go ».** Lecture codée (`[R73]`, `src/merchants/greenmangaming.py`) :
1. liste d'exclusion vide → GLOBAL (`[R59]`) ; pays exclus mais ni l'UE, ni le Royaume-Uni, ni les USA →
   le seau **ROW** du menu (« Steam ROW (steamrow) », vérifié dans le catalogue du modal du 26/09, qui
   porte aussi Origin / Ubisoft / Epic / Battlenet / Publisher ROW) ; UE, UK ou USA exclus → refus,
   jamais le repli US / EU de `[R59]` ;
2. la génération Xbox est DÉCLARÉE par le suffixe du sku (P1) ; une fiche qui liste PC ET une Xbox
   déclare « Xbox + PC » (P2) ; la clé « - Windows 10 » (`Drm` microsoft) est une clé Microsoft Store
   PC ; les crédits PSN sont refusés ;
3. « Standard Edition » (ou `Name` vide) sur un titre nu → le chemin générique, Standard quand la page
   AKS le vend ; un palier que la fiche nomme et que le titre ne porte pas → refus ;
4. fichier + tests (11 fiches réelles en fixtures) + aperçu à blanc sur les 482 lignes
   (`docs/apercu_greenmangaming_2026-10-09.md`) ; liste blanche et groupe après lecture de l'aperçu.

**Aperçu à blanc du 09/10 (`docs/apercu_greenmangaming_2026-10-09.md`, lecture seule, 482 lignes, 0 sonde
AKS douteuse) : 218 entrées, 264 refus.** Entrées : Steam GLOBAL Standard 134, Steam GLOBAL DLC 20, **Steam
ROW 32** (22 Standard, 7 DLC, 3 éditions nommées — listées à part pour confirmation), Early Access 5, éditions
nommées (Deluxe, Enhanced, Starter, Ancestral…) 19, Xbox 13 lignes (10 Xbox Series / Xbox One en P1,
3 « Xbox + PC » par la page AKS Play Anywhere : EA SPORTS FC 27 Ultimate, Minecraft Dungeons II ×2), 1 Epic
(RPG MAKER UNITE Special Edition, `Drm` epic). **DRM vus sur les 218 fiches des entrées : steam 204, xbox-one 13, epicgames 1** (la fiche « microsoft » de Minecraft est refusée comme lot). Refus :
76 sans page AKS, 45 « produit différent / élargi », 43 lots (« 2 Pack » / « 4 Pack » / « Bundle »), 19
« skip category: BUNDLE », 17 fiches disparues de GMG (« title-no-longer-available », « game-unavailable »,
404 : des lignes en attente pour des produits que GMG ne vend plus), 12 éditions non vendues par la page,
8 pages AKS sans carte d'éditions, 7 monnaies / crédits, 5 « (MAC) », 5 « name mismatch », 3 consoles sans
page AKS, 2 « console: no declared generation » (« Switch Galaxy Ultra » — « Switch » dans un nom de jeu PC
sans mot de boutique dans le titre —, « MLB THE SHOW 19 STUBS » — monnaie non reconnue), le reste à
l'unité. Aucun refus « LOCK » : aucune fiche n'exclut l'UE, le Royaume-Uni ou les USA.

## 2026-10-07 — eww.gg : « Forme-toi sur ce marchand » (ID AKS 1011, ID feed ?)

Romain : « Forme toi sur ce marchant https://eww.gg/george-vs-bonny-pp-wars-global-pc-steam-digital-key-151108
ID AKS 1011 ID AKS feed ? ». Sonde du 07/10, lecture seule (une requête HTTP sur la fiche, une page AKS).

- **C'est une boutique de Driffle.** Le pied de page dit « Possédé et exploité par Driffle UAB,
  Naugarduko g. 3-401, 03231, Lithuania ». Le titre a la grammaire de Driffle à l'identique :
  `George VS Bonny PP Wars (Global) (PC) - Steam - Digital Key` = `<Jeu> (<Région>) (<Plateforme>) -
  <Boutique> - <Livraison>` (voir `src/merchants/driffle.py`, `[R45]` / R32). L'URL aussi, au suffixe
  près : `eww.gg/<slug>-<région>-<plateforme>-<boutique>-digital-key-<id>` (Driffle écrit `-p<id>`).
  Le fichier marchand serait donc **une déclinaison de `driffle.py`** (même `title_region`, même
  `precheck`, même grammaire console), domaine `eww.gg` et son propre store id.
- **La fiche se lit en HTTP** (200 avec un UA navigateur, Cloudflare présent mais servi ; redirection
  vers `/fr/`). Application Next.js ; le texte rendu porte « Plateforme Steam », « Région Monde »,
  « Version Standard », et un encart « Restrictions régionales » (« Pays autorisés », « Activable
  dans… ») dont la liste de pays n'est pas en clair dans le HTML (flux RSC) — à relire sur quelques
  fiches si on veut une règle `[R59]` sur les pays AUTORISÉS comme Allyouplay ; le titre suffit déjà
  pour la région et la plateforme comme chez Driffle.
- **ID AKS 1011 ≠ store id du feed.** Sur les pages AKS, les marchands ont un id de page (Kinguin 47,
  G2A 61, CJS 67, Gamivo 218, Eneba 272, Driffle 408, GameSeal 557, Wyrel 1001) différent du store
  id du feed (58, 38, 30, 51, 19, 127, 126, 162) : 1011 est l'id de page d'eww.gg, pas celui du feed.
  **eww.gg n'a aucune ligne dans le scan toutes-boutiques du 21/09** (0 URL `eww.gg` sur ~20 000
  lignes) : le marchand est arrivé après, ou n'avait pas encore d'offres en attente. Le store id du
  feed se lit dans le menu « store » de l'outil feed (session navigateur) ou dans la colonne store
  d'un extract toutes-boutiques frais (page 1, triée par id décroissant) — à faire à la prochaine
  pause de B, ou à lire par Romain dans son menu.
- **Sur AKS** : la page `george-vs-bonny-pp-wars` ne porte pas (encore) de prix eww.gg (Kinguin,
  GameSeal, Wyrel, G2A, Eneba, Driffle, Gamivo, CJS, Steam) ; rien à mesurer sur « comment AKS le
  range » tant qu'il n'a pas d'offres.

**Classement** : le plus simple de tous les marchands étudiés — grammaire déjà codée (Driffle), fiche
lisible en prime.

**Suite (07/10, 14 h 40 UTC)** — Romain : « Store ID 170 stop B et lance le data entry pour ce nouveau
shop, puis tu relanceras B depuis l'admin pour être sûr que j'ai le log ». Fait : `src/merchants/eww.py`
(déclinaison de `driffle.py`, registre store 170, liste blanche, hors groupe), tests ; B arrêtée à un
moment sûr, code tiré, admin redémarré, balayage eww.gg lancé seul depuis l'admin (une passe, toutes
pages, consoles), B relancée depuis l'admin à sa fin. Pas d'aperçu à blanc préalable (instruction de
Romain, grammaire éprouvée) : la première passe réelle en tient lieu — ses recap / log sont la mesure
du volume et du rendement.

## 2026-10-06 (soir) — « Quel marchand pourrait-on faire par la suite ? »

Réponse, dans l'ordre du tableau et des sondes :

1. **Gamebillet (15)** — 268 lignes en attente au 21/09, 192 avec une page AKS (72 %, le meilleur
   taux des candidats restants) ; titre et URL muets, mais la fiche se lit en HTTP (200) et porte
   une rubrique « Platform » et un bloc « restricted countries » ; AKS le range déjà en Steam
   GLOBAL (7 / 7 sur 10 pages lues le 25/09). Même modèle que Gamesplanet FR et Indiegala : un
   lecteur de fiche, plateforme lue, région = `[R59]` sur les pays exclus. Petite file, rendement
   attendu ≈ 100 à 150 lignes au premier passage.
2. **Greenmangaming (22), à re-mesurer** — 482 lignes, 318 avec une page AKS (66 %) ; écarté le
   25/09 pour son URL d'affiliation `sjv.io` illisible — depuis Allyouplay `[R68]`,
   `affiliate_hosts` / `landing_url` savent décoder ce redirecteur (la fiche est dans `u`), et la
   fiche GMG se lit en HTTP (sonde du 30/09). À remesurer avant de trancher : si la fiche donne
   plateforme et région, c'est le plus gros stock restant.
3. Muve (166) reste derrière : 605 lignes mais ~140 utilisables (pas de région sur la page,
   « sans région = Europe » refusé par Romain le 25/09).

## 2026-10-06 — Indiegala (95) : « regarde si possible de se former sur l'ajout auto »

**Mesure** (lecture seule ; feed = les 175 lignes du scan tous-magasins du 21/09, donc un
minimum ; 8 fiches lues en HTTP, 5 pages AKS lues) :

- **Grammaire du feed** : titre = nom du jeu seul (« Reach », « Monster Hunter Wilds Gold
  Edition », « SCUM Specialist Scout Pack ») ; URL `indiegala.com/store/game/<slug>/<id steam>[_del|_us|…]`.
  **Ni plateforme ni région** dans le titre ou l'URL (0 / 175), sauf 7 suffixes « (US) » / « (EU) »
  (SILENT HILL: Townfall ×2, PAC-MAN World 2 ×2, Katamari, Castlevania Belmont's Curse ×2).
  30 lignes bundle / pack / DLC / upgrade, 21 avec un palier (Deluxe, Gold, Ultimate…), 5 titres
  multilingues « A / B / C ». Les règles génériques en refusent 14 au precheck (bundles, DLC pack,
  pass) ; les 161 autres tomberaient aujourd'hui sur R27 / `[R51]` (plateforme inconnue) — zéro
  écriture possible sans lecteur de fiche.
- **La fiche est lisible** (HTTP 200, pas de Cloudflare, UA navigateur, 8 / 8) et dit tout :
  * plateforme : « *<Nom>* is provided via **Steam Key** » (8 / 8 Steam ; titre de page
    « <Nom> Steam Key | … ») — une autre valeur serait un refus nommé ;
  * DLC : « This content requires the base product » ;
  * région, trois blocs distincts à ne pas confondre :
    1. un encart latéral « Region locked product — It will only work in the region from where it
       is bought » (7 fiches sur 8, absent de Thunder Ray) : la clé est liée à la région d'ACHAT ;
    2. un avertissement d'article « **Region locked product** — The keys of this product can only
       be activated in the country they were purchased » (Reach seul) : verrou PAYS ;
    3. « **Country availability** » / « **Banned countries** » + liste de pays où la vente est
       interdite « as per publisher request » (MHW Gold 19 pays, SCUM 59, LBA2 78, Belmont's Curse
       (EU) 127, Castlevania bundle 219, SH Townfall (US) 227).
  Le bloc 3 est exactement la matière de la règle `[R59]` de Romain (Gamesplanet FR, pays
  EXCLUS) : ni UE, ni UK, ni USA exclus → GLOBAL ; UE autorisée sans USA → EU ; USA sans l'UE →
  US ; sinon refus. Les suffixes « (US) » / « (EU) » du titre concordent avec leurs listes (227 et
  127 pays interdits).
- **Pages AKS** : 30 des 161 lignes ont une page au slug strict (19 %) — des jeux indés pour
  l'essentiel absents d'AKS ; le reste relève de R64 / R66 (éditions, recherche catalogue).
  **AKS n'affiche aucune offre Indiegala** sur les 5 pages lues (le marchand existe dans sa
  liste d'icônes) : aucun précédent pour la région, c'est à Romain de la fixer.
- **Fiche périmée** : 1 / 8 (Attack on Titan 3 Digital Deluxe) renvoie à l'accueil → refus
  « fiche non identifiée » comme chez Allyouplay (lien canonique).

**Classement** : faisable, **même modèle qu'Allyouplay `[R68]`** (fichier `src/merchants/indiegala.py`
: `domain`, `offer_page_resolver` par bibliothèque standard, plateforme = « provided via », DLC =
« requires the base product », région = liste des pays interdits par `[R59]`, refus nommés pour
le verrou pays et la fiche périmée, `url_identity_params` inutile : l'id Steam est dans le chemin).
**Rendement faible** : ≈ 30 candidats sur 175 au premier passage, puis un filet. Coût : une
demi-journée (fichier + fixtures réelles + tests + aperçu à blanc sur le feed du jour).

**Ce que Romain doit trancher avant de coder** : (1) la règle de région — `[R59]` sur la liste
des pays interdits (proposé), et que fait-on de l'encart « liée à la région d'achat » présent
sur presque toutes les fiches (ignoré, comme la politique de vente de Gamesplanet ?) ; (2) le
verrou PAYS explicite (Reach) = refus (proposé) ; (3) go ou pas, vu le rendement.

**Suite (06/10, même jour)** — Romain : « Si on peut ouvrir la page, on trouvera les infos ».
Fichier écrit sur la branche `indiegala` : `src/merchants/indiegala.py` (`[R69]`, EXECUTOR_RULES ;
MERCHANTS « Indiegala (store 95) »), tests `tests/test_merchants_indiegala_r69.py` sur les 8 fiches
réelles (`tests/fixtures/indiegala/`), registre store 95 — hors liste blanche jusqu'à l'aperçu.
Codé tel que proposé : (1) `[R59]` sur les pays interdits, encart « région d'achat » ignoré ;
(2) verrou pays = refus. **À confirmer par Romain à l'aperçu** (règle proposée, pas revue) :
sur les 8 fiches, MHW Gold / SCUM / LBA2 / Thunder Ray → GLOBAL, SH Townfall (US) → US, le bundle
Castlevania → EU (refusé bundle), Reach → verrou, et **Belmont's Curse (EU) → refus « LOCK (EU +
US) »** : sa liste interdit les USA ET Chypre, donc l'UE n'est pas entière — tel quel (aucune
écriture fausse), ou « (EU) du titre + UE quasi complète → EU » ? Autre point : « Attack on Titan
3 / A.O.T. 3 » (2 lignes) reste entier → refus R01 au pire ; couper l'alias demande un go.
Prochaine étape : aperçu à blanc (`03_match`, lecture seule) sur le feed du jour, puis liste
blanche / groupe sur le go de Romain.

**Aperçu à blanc du 06/10** (`03_match` hors ligne sur les 175 lignes du scan du 21/09, HTTP seul,
index AKS de 12 h ; détail dans [`apercu_indiegala_2026-10-06.md`](apercu_indiegala_2026-10-06.md)) :
**34 candidats / 141 refus**, tous Steam — 22 GLOBAL Standard, 4 GLOBAL DLC (pages à seau DLC
unique), 1 Deluxe / 1 Gold / 1 Ultimate GLOBAL, 5 US par le suffixe « (US) » du titre confirmé par
la fiche (SH Townfall ×2, PAC-MAN World 2 ×2, Katamari). Les 8 fiches de l'étude sortent comme
prévu (MHW Gold, SCUM, LBA2 → GLOBAL ; Townfall → US ; bundle Castlevania → refus bundle ; Reach →
verrou pays ; Belmont's Curse (EU) → « LOCK (EU + US) » ; AOT3 Deluxe → fiche périmée). **Une
écriture fausse trouvée et fermée** : « Thunder Ray - Origin » — fiche DLC, titre sans marqueur,
ORIGIN lu comme du bruit de plateforme — sortait Standard(1) sur la page du JEU DE BASE ; la fiche
DLC est désormais une GARDE générique (`MerchantOfferSignals.dlc` → `matcher.page_dlc_refusal` :
une fiche DLC qui n'aboutit pas en DLC(16) est refusée, jamais un routage) ; les 4 autres fiches
DLC entrent toujours en DLC(16) sur leur propre page. Les refus : 39 fiches « direct download »
(ventes sans DRM, pas des clés Steam — refus voulu, plateforme inconnue d'AKS), 30 verrous « pays
d'achat », 27 sans page AKS (dont les 2 « Attack on Titan 3 / A.O.T. 3 » : AKS n'a aucune page
AOT 3 au sitemap — l'alias ne change rien aujourd'hui), 15 « mots en trop » (DLC / variantes sans
page), 6 bundles + 2 multi-jeux + 5 collections de DLC + 1 pass, 5 fiches sans « is provided via »
(illisibles, refus voulu), 2 Belmont's Curse (EU) en « LOCK (EU + US) », 4 noms cassés par le `\'`
du feed (« Collector\'s Cove », « PO\'ed », « Farmer\'s Dynasty » : `tokenize` en fait « COLLECTOR S »
— défaut GÉNÉRIQUE du feed, pas d'Indiegala : 109 offres Eneba / Gamerall refusées de la même façon
en production, à corriger côté extracteur sur un go), 1 Kao Anniversary (R64), 1 SNK Deluxe Pack
(édition ambiguë). **À trancher par Romain** : (1) Belmont's Curse (EU) — tel quel (refus strict
`[R59]`, Chypre + USA interdits) ou « (EU) du titre + UE quasi complète → EU » ; (2) go ou pas pour
la liste blanche + un groupe, vu le rendement (≈ 34 / 175, et le feed du 21/09 a 15 jours : un
extract frais demande un navigateur — A et B sont en boucle, le VPS 3 n'est pas à toucher sans go) ;
(3) le `\'` du feed, générique.

**Go de Romain (06/10, soir) : « go pour la liste blanche »**, après le tableau ligne par ligne
(fiche lue, page AKS, saisie du modal, ce que la page vend déjà, points à regarder : 5 premières
offres US de leur page, Little Big Adventure / Nightmare Frontier / Tabletop en Standard alors que
la page vend aussi Enhanced / Early Access). Indiegala (95) rejoint `AUTO_MERCHANTS` ; **groupe B**
(Romain, même soir : « groupe B pour Indiegala »).
Pour que ce soit vivant : tirer le code sur les clones et redémarrer l'admin entre deux balayages
(jamais sous une boucle). Belmont's Curse (EU) : pas tranché, reste refusée.

## 2026-09-25 (suite) — CDKeys, devenu « Loaded » (store 40)

Romain : « Pars sur CDKeys (nouveau nom du marchand est LOADED) », store 40.
- Scan du 21/09 : **16 lignes seulement** (le scan triait encore mal ; à remesurer sur le feed du
  jour). URL d'affiliation `go.loaded.com/c/…?u=https://www.loaded.com/<slug>` : la vraie URL est
  dans le paramètre `u`.
- Titres RICHES : « Towerborne Xbox/PC (Europe & UK) », « Attack on Titan 3 … PC (North America) »,
  « Red Dead Redemption 2: Ultimate Edition Xbox (WW) », « Super Mario Galaxy 2 Switch & Switch 2
  (Europe & UK) » ; le slug répète plateforme et région (`-pc-steam-eu`, `-xbox-pc-eu`, `-na`).
  Certains n'ont pas de région (« Zero Caliber 2 Remastered PC », slug `-pc-steam`).
- AKS range déjà Loaded (20 pages lues) : Steam GLOBAL 14, XBOX/PC EUROPE (241) 9, Xbox X|S
  EUROPE 7, Steam EU 4, STEAM EMEA 3, Xbox/PC 306, Ubisoft, Rockstar, PS5 EU / US, Switch EU.
- Décisions à prendre : « (Europe & UK) » → Europe (aujourd'hui le vocabulaire partagé en fait un
  VERROU, deux régions à la fois) ; une ligne sans région → GLOBAL comme MMOGA / Kinguin, ou refus ;
  « (North America) » reste refusé comme partout.

## 2026-09-25 (suite) — Discover.games codé

Romain : « go pour Discover.games », « il faut vraiment lire la région sur la page !!! ». Fichier
`src/merchants/discover.py` (`[R60]`) : plateforme et région lues sur la fiche
(`sellableProductDetail` : `platform`, `skus[].availableCountries`, `WW` = monde), règle `[R59]`.
Essai à blanc sur 150 lignes réelles : **106 candidats** (Steam GLOBAL 104, US 2). Les fiches
introuvables (404, ou sans déclinaison en vente) sont refusées. Prochain : **CDKeys / Loaded**
(store 40), demandé par Romain.

## 2026-09-25 (suite) — Pixelcodes : les produits du feed n'existent plus sur le site

Romain : « Je pense qu'on va partir sur Pixelcodes […] il faudra essayer d'ouvrir la page pour
être sûr que ce soit pas un product not found », puis « Tu me garderas une liste de produits not
found, que je pourrais transmettre aux marchands ».

- Les titres du feed Pixelcodes (scan du 21/09, 1 547 lignes importées le 16/09) sont nus :
  « Frogun », « Barotrauma » ; ~1 % disent une plateforme ou une région.
- La page produit est une application JavaScript (2,8 Ko de HTML), mais elle lit ses données
  dans une **API publique** : `https://pixelcodes.com/api/products/<slug>` (le slug de l'URL du
  feed). Pour un produit vivant, elle rend `categorySlug`, `regionRestrictions`, `platformType`,
  les `variants` (avec `platform`, `stockCount`)… ; sinon `{"error":"Product not found"}`.
- **40 lignes du feed tirées au hasard : 40 « Product not found ».** La recherche du site
  (`/api/products?q=`) ne trouve ni « frogun », ni « naruto », ni « barotrauma ». Le site
  d'aujourd'hui est une boutique de LOGICIELS : ses catégories sont antivirus, bureautique,
  systèmes, VPN… (293 produits en stock), aucune catégorie jeux.
- **Software-codes** (store 6) : même gabarit de site, même API ; 12 lignes sur 12 « not found ».
- **Discover.games** (store 168), à part : ses pages sont vivantes (`discover.games/games/mad-metal`
  → `www.`, titre « Buy Mad Metal Steam Key »). Candidat à étudier, autre famille.
- **Vérification complète (25/09, API, lecture seule) : 3 085 lignes sur 3 085 « Product not
  found »** — Pixelcodes 1 547 / 1 547, Software-codes 1 538 / 1 538. Listes à transmettre aux
  marchands, sur la nouvelle VM : `/tmp/tri/20260925-pixelcodes-produits-introuvables.csv` et
  `/tmp/tri/20260925-software-codes-produits-introuvables.csv` (URL produit, titre, id d'offre du
  feed, heure de vérification). Romain a demandé à Pixelcodes de corriger son feed (25/09).

## 2026-09-25 (suite) — Pourquoi Muve n'a que 35 % de lignes lisibles

Muve mélange **deux catalogues**, qu'on distingue à la fin de l'URL (605 lignes du 21/09) :

| Catalogue (fin d'URL) | Titre complet « (PC Steam) (ROW) » | Titre nu | Région seule « (EU) » | Plateforme seule |
|---|---|---|---|---|
| identifiant numérique (`…-2401190`), récent | 183 | 152 | 27 | 27 |
| hash hexadécimal (`…-93200d`), catalogue historique de muve.pl | 4 | 146 | 4 | 18 |
| autre (slug seul) | 23 | 12 | 2 | 7 |

- Le catalogue « hash » est celui de la boutique polonaise d'origine : titres NUS (« Yakuza Kiwami »).
- Le catalogue « numérique » écrit souvent tout, mais pas toujours (« Gambonanza »).
- **La page Muve se lit en HTTP** (237 Ko, données Nuxt) et porte des champs structurés
  `Platform: PC` et `DRM: Steam` — la plateforme est donc récupérable pour les lignes nues. Mais
  **aucun champ région** : seulement le message générique « The store does not distribute this
  product in your country ».
- AKS range les offres Muve existantes en Steam EU (9) et Windows EU (244).
- Pour aller au-delà des ~140 lignes lisibles : lire la plateforme sur la page, et une règle de
  Romain pour la région des lignes nues. **Décision du 25/09 : PAS de « Muve sans région =
  Europe ».** Aucun marchand n'a ce comportement : le défaut existant est l'inverse, « sans région
  = GLOBAL implicite » (MMOGA, Eneba, Kinguin, CJS, Electronicfirst, Gamivo, Difmark — relevé sur
  les approved.json des deux VM), et GameBoost, GamersOutlet, Wyrel, Gamerall, Gamesplanet
  refusent ou lisent la page. Un fichier Muve devrait donc REFUSER les lignes sans région (comme
  GameBoost `[R47]`) : ~140 lignes seulement.

## 2026-09-25 (suite) — « Il reste des marchands avec toutes les infos dans l'URL + le titre ? »

Mesure sur le scan du 21/09 (boutiques hors liste blanche, ≥ 20 lignes) : part des lignes dont le
titre ou l'URL disent À LA FOIS la plateforme et la région, et combien de celles-là ont une page
AKS.

| Boutique (store) | Lignes | Plateforme + région lisibles | … dont page AKS |
|---|---|---|---|
| Muve (166) | 605 | 214 (35 %) | 139 |
| etailcard (152) | 263 | 166 (63 %) | 82 — surtout des cartes / abonnements, pas des jeux |
| HRK (14) | 46 | 25 (54 %) | 17 |
| Keycense (130) | 124 | 45 (36 %) | 5 |
| Royalcdkeys (85) | 101 | 31 (31 %) | 7 |
| Gamingdragons (41) | 33 | 14 (42 %) | 6 |
| ldshop.gg (169) | 21 | 8 (38 %) | 6 |
| Pixelcodes, Software-codes, Discover.games, Indiegala, etail.market… | — | ~0 % | — |

**Réponse : il n'en reste presque plus.** Les marchands « tout dans le titre » sont déjà en liste
blanche. Seul **Muve** garde un volume utile (~140 lignes avec une page AKS dont le titre dit tout,
« AI LIMIT (PC Steam) (ROW) ») ; les autres sont minuscules. Les gros gisements restants
(Pixelcodes, Software-codes, Discover.games, Gamebillet, Greenmangaming) ont des titres NUS : il
faut lire leur page marchande (Gamebillet, lisible en HTTP) ou obtenir une règle de Romain.

## 2026-09-25 (suite) — Gamesplanet FR codé

Romain : « go pour Gamesplanet FR avec ta règle + un pays UE exclu mais États-Unis autorisés →
US ». Fichier `src/merchants/gamesplanet.py` (`[R59]`, détail dans [`MERCHANTS.md`](MERCHANTS.md)).
Essai à blanc sur 150 lignes réelles : **77 candidats** (Steam GLOBAL 62, Steam EU 10, Steam US 1,
GOG 3, Microsoft 1) ; 37 refus faute de page AKS. Extrapolé aux 526 lignes du 21/09 : ~270
offres, davantage avec le feed complet (tri corrigé). Prochaine étape : liste blanche, groupe A
(le plus léger). Ensuite : **Gamebillet**, même famille de travail.

## 2026-09-25 — « Qu'est-ce que tu vois comme prochain marchand facile et rentable ? »

**Méthode.** Pour chaque boutique hors liste blanche du scan du 21/09 :
1. les lignes en attente ;
2. celles dont la page AKS existe (index sitemap, lecture locale) ;
3. la part des titres et URL qui disent la plateforme et la région ;
4. **comment AKS range DÉJÀ ce marchand** : pour 10 pages AKS tirées au hasard par marchand, on a
   lu la table des prix (`extract_prices`), et donc les seaux région / édition des offres du
   marchand déjà présentes ;
5. si la page produit du marchand se lit en HTTP simple (sans navigateur).

**Ce qu'AKS montre déjà (10 pages chacun) :**
- Gamesplanet FR : 20 offres en Steam GLOBAL (2), 3 en Steam EU (9), 4 en GOG (6) — le
  marchand existe bien sur AKS, rangé surtout en GLOBAL ;
- Gamebillet (« GameBillet EU » sur AKS) : 7 sur 7 en Steam GLOBAL (2) ;
- Muve : Steam EU (9) et un seau 244 ;
- Greenmangaming : 2 en Steam GLOBAL (2) ;
- Pixelcodes, Software-codes, Discover.games : **aucune** offre à leur nom sur ces pages.

**Gamesplanet FR, le premier.**
- La **plateforme est dans l'URL**, écrite en clair : `…-steam-key--7963-1` (474 lignes sur 526),
  `-gog-key--` (12), `-epic-games-key--` (8), `-microsoft-store-download--` (16),
  `-rockstar-key--` (3), `-arenanet-key--` (5).
- La **région n'est ni dans le titre ni dans l'URL**, mais la page produit se lit en HTTP
  (200, 76 Ko) et porte un bloc « REGION LOCK INFO » : « It will NOT activate in:
  Afghanistan, Algeria, … » — la liste des pays EXCLUS.
- Il manque une règle, à trancher par Romain : comment une liste de pays exclus devient un
  seau AKS. Proposition : aucun pays de l'UE, ni le Royaume-Uni, ni les États-Unis exclus →
  GLOBAL ; UE autorisée mais États-Unis exclus → EU ; un pays de l'UE exclu → refus ; page
  illisible → refus.

**Gamebillet, le suivant.** URL et titre ne disent rien (`gamebillet.com/dunebound-tactics`),
mais la page se lit (200) et porte un bloc « restricted countries » et une rubrique
« Platform ». AKS le range toujours en Steam GLOBAL. Même famille de travail que Gamesplanet :
un lecteur de page marchande, sur le modèle de Gamerall `[R54]`.

**Pixelcodes / Software-codes / Discover.games, les plus gros mais les plus durs.** Près de
3 100 lignes avec une page AKS à eux trois, mais rien de lisible : titres nus (« Frogun »),
URL nues, page produit de 2,8 Ko qui ne contient que du JavaScript. Et AKS n'a aucune offre à
leur nom pour servir de modèle. Il faudrait soit une règle de Romain (« tout est Steam
GLOBAL »), soit lire les pages avec le navigateur. À garder pour après.
