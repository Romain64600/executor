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
| 2 | **Gamebillet** (15) | 268 | 192 (72 %) | plateforme et région (URL et titre muets ; la page liste les pays exclus) | à étudier après Gamesplanet |
| 3 | **Muve** (166) | 605 | 322 (53 %) | titre lisible pour ~35 % des lignes ; pas de région sur la page ; « sans région = Europe » refusé par Romain (25/09) | ~140 lignes seulement, en refusant les lignes sans région |
| 4 | **Pixelcodes** (82) + **Software-codes** (6) | 1 547 + 1 538 | 1 377 + 1 365 (89 %) | **les produits du feed n'existent plus sur leurs sites** (API : « Product not found », 52 sur 52 testés ; sites devenus boutiques de logiciels) | à ne pas saisir ; liste « not found » en cours pour les marchands |
| 5 | **Discover.games** (168) | 440 | 370 (84 %) | — | **fichier écrit le 25/09 (`[R60]`), essai à blanc : 106 candidats sur 150 lignes ; en liste blanche le 26/09, groupe A** |
| 6 | **CDKeys → « Loaded »** (40) | 16 (21/09) | — | feed du jour à relire | **fichier écrit le 25/09 (`[R61]`, « Europe & UK » → Europe, sans région → GLOBAL) ; essai à blanc sur 16 lignes : 1 candidat ; en liste blanche le 26/09, groupe A** |
| — | Greenmangaming (22) | 482 | 318 (66 %) | URL d'affiliation illisible (sjv.io), titre muet | pas prioritaire |
| ✓ | **Indiegala** (95) | 175 (21/09) | 30 (19 %, slug strict) | plateforme et région : ni titre ni URL ; la **fiche** les donne (« is provided via Steam Key », listes de pays, « Region locked product ») | **fichier écrit le 06/10** (`[R69]`), **aperçu à blanc le 06/10 : 34 entrées / 175** (`apercu_indiegala_2026-10-06.md`), **liste blanche le 06/10** (Romain : « go pour la liste blanche ») ; groupe à choisir ; Belmont's Curse (EU) reste refusée (Chypre ET les USA interdits), tant que Romain n'en décide pas autrement |

\* Mesuré sur le scan tous-magasins du 21/09, **avant** la correction du tri du feed (`orderBy=id`,
24/09) : ces comptes sont des minimums. Un nouveau scan tous-magasins les rafraîchira.

**Déjà faits** : Gamesplanet FR (liste blanche le 25/09, `[R59]`), Wyrel (liste blanche le 24/09, `[R53]` + `[R58]`), GOG (22/09), Gamerall
(19/09), GameBoost / Electronicfirst / GamersOutlet (16/09), Difmark (21/09).

---

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
la page vend aussi Enhanced / Early Access). Indiegala (95) rejoint `AUTO_MERCHANTS` ; **le groupe
reste à choisir par Romain** (hors groupe en attendant, raison écrite dans `merchant_groups.py`).
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
