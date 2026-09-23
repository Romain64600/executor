# Audit des refus GOG — balayage du 2026-09-23

Romain : « Les offres qui ont été skippées pour GOG, ça vient d'où ? On n'a pas la page ? Il y
a une autre raison ? Audit ça, s'il te plaît, fais-moi un rapport. »

Lecture seule, aucun code modifié. Corpus : les **16 premières pages** du balayage
`20260923-gog-full` (pages 36 → 21, les plus anciennes du feed), lues le 2026-09-23 vers 09 h
UTC pendant que le balayage continuait. Le balayage est toujours en cours ; les chiffres
définitifs viendront à sa fin.

---

## 1. La réponse courte

**Oui, c'est d'abord la page qui manque — mais pas seulement, et presque tous les refus sont
justes.**

| Motif | Offres | Part | Juste ? |
|---|---|---|---|
| Pas de page AKS | 345 | 55,5 % | oui, à 1,4 % près |
| Produit différent : DLC ou goodie résolu sur la page du jeu | 102 | 16,4 % | oui |
| Bundle ou lot | 61 | 9,8 % | oui, règle absolue |
| Édition absente de la page (E06) | 35 | 5,6 % | **décision à prendre** |
| Démo | 31 | 5,0 % | oui |
| DLC sans page propre (R43) | 21 | 3,4 % | oui |
| Nom AKS différent (R01) | 12 | 1,9 % | oui |
| Non-jeu : bande-son, artbook, monnaie, pass | 11 | 1,8 % | oui |
| Autres | 4 | 0,6 % | un faux positif, voir §6 |

622 offres distinctes refusées. Les motifs sont comptés par **offre**, pas par ligne : voir §7.

Contexte technique, vérifié sur les 16 pages : l'index sitemap faisait autorité (213 415
pages), et il n'y a eu **aucun** échec de recherche, aucune sonde douteuse, aucun disjoncteur.
Un « pas de page » n'est donc pas une panne réseau : c'est qu'aucun slug deviné ne répond ET
qu'AKS ne publie aucune page de clé sous ce nom.

## 2. « Pas de page AKS » — 345 offres

Chaque verdict a été confronté au sitemap d'AKS, puis à la page d'un parent possible.

| Cause | Offres | Part |
|---|---|---|
| Aucune page, ni pour le produit ni pour un jeu parent | 274 | 79,4 % |
| Le jeu de base a une page, pas cette édition ou cet upgrade | 38 | 11,0 % |
| La page de la série existe, le produit est un dérivé (DLC, épisode) | 28 | 8,1 % |
| **La page existe, cachée par le préfixe GOG « Expansion - »** | **5** | **1,4 %** |

Les 274 premières sont de vrais absents : romans visuels obscurs (« Amatsutsumi »), drames
audio (« Kindred Spirits on the Roof Drama CD Vol.4 »), DLC mineurs sans page
(« Stellaris: Horizon Signal »).

Les 38 suivantes sont des **produits d'upgrade** — « Shardlight: Special Edition Upgrade »,
« STASIS: Deluxe Edition Upgrade » — ou des éditions sans page propre — « Kingdom: New Lands
Royal Edition », « Overcooked: Gourmet Edition ». Le jeu existe sur AKS, pas ce produit-là.
Un upgrade ne se range pas sur la page du jeu de base : ce serait vendre le jeu entier au prix
d'un complément. Refus juste.

**Le seul défaut trouvé** est le préfixe. GOG titre certains DLC Paradox
« Expansion - Crusader Kings II: Holy Fury ». Notre constructeur de slug garde le préfixe
(`expansion-crusader-kings-ii-holy-fury`) et n'essaie jamais `crusader-kings-ii-holy-fury`,
qui existe. Sur les 3 473 lignes GOG, **16 titres** portent ce préfixe, dont **14** ont une
page une fois le préfixe retiré. Correctif possible : retirer « Expansion - » dans
`src/merchants/gog.py`, crochet `resolve_name`. Rien n'est fait tant que tu ne l'as pas dit.

## 3. « Produit différent » — 102 offres

GOG vend beaucoup de DLC et de goodies titrés « <Jeu> - <Contenu> » :

    Devil May Cry 4 Special Edition - Unlock All Modes
    Oddworld: New 'n' Tasty - Scrub Abe
    Homeworld: Deserts of Kharak - Expedition Guide
    Hotline Miami 2: Wrong Number - Digital Comics
    Satellite Reign - Reboot Prequel Novella
    Overload - Playable Teaser

Le contenu n'a pas de page ; le matcher retombe sur la page du JEU, et le garde des mots en
trop (R16) refuse, puisque « Unlock All Modes » n'est pas dans le nom AKS « Devil May Cry 4
Special Edition ». C'est exactement ce que ce garde doit faire : écrire ce DLC sur la page du
jeu serait un produit faux. Les mots en trop les plus fréquents confirment la nature de ces
lignes : SUPPORTER (10), SET (6), UPGRADE (5), ART, EXTRAS, POSTER, GUIDE, COMICS, NOVELLA.

## 4. « Édition absente de la page » — 35 offres, une décision à prendre

C'est le seul groupe où la règle, et non la donnée, décide. **20 de ces 35 offres sont des
DLC GOG sans aucun marqueur DLC dans le titre** :

    Europa Universalis IV: Muslim Advisor Portraits     page : Collection · DLC
    Warhammer 40,000: Armageddon - Ork Hunters          page : Complete · DLC
    Talisman Character - Jester                         page : Bundle · DLC
    Chernobylite - Red Trees Pack                       page : Deluxe · DLC

Le titre se lit « Standard », la page ne vend pas de Standard, donc E06 refuse. R18 pourrait
les ranger en DLC, mais depuis ton durcissement du 17/09, un titre sans marqueur ne prend le
seau DLC **que si c'est le seul seau de la page**. Ici la page porte aussi « Collection » ou
« Complete », donc R18 se retire, volontairement : c'est la règle qui a arrêté l'erreur
« Grand Theft Auto Vice City » en DLC.

17 des 35 ont une page à leur propre nom, celle que le matcher essaie en premier, ce qui renforce l'hypothèse DLC.
La question pour toi : **faut-il, pour GOG seulement, laisser le seau DLC décider quand la
page est la page PROPRE du produit, même si elle porte d'autres seaux ?** Je ne l'ai pas
touchée : c'est un assouplissement d'une règle que tu as durcie, et il ne se décide pas sans
toi.

## 5. Les refus justes, sans surprise

* **Bundles et lots — 61 offres.** Tous portent « Bundle » ou « + » dans le titre. Certains
  sont en réalité des packs cosmétiques d'un seul jeu (« Dying Light: Volatile Hunter
  Bundle », « Potion Permit - Summer Bundle »), mais la règle « jamais de bundle » est absolue
  depuis le 7 juillet, et je ne la discute pas ici.
* **Démos — 31 offres.** Produit gratuit, rien à comparer.
* **DLC sans page propre, R43 — 21 offres.** « Goliath - Summertime Gnarkness DLC » résolu sur
  la page `goliath` : le DLC n'a pas sa page, la page du jeu n'est pas la sienne.
* **Nom différent, R01 — 12 offres,** et **non-jeux — 11** (bande-son, artbook, orbes, pass).

## 6. Un faux positif isolé

« Succubus - Ukraine Support » est refusé pour **région interdite : UKRAINE**. C'est un DLC
caritatif ; « Ukraine » est dans son nom, pas dans sa région. Chez GOG la région est toujours
mondiale, mais le contrôle générique des régions interdites passe avant le crochet GOG. Une
seule ligne, et le produit n'a probablement pas de page de toute façon. À corriger dans
`gog.py` en même temps que le préfixe, si tu le veux.

## 7. Une observation qui n'est pas un refus : les relectures

Les 16 pages ont lu **1 544 lignes, mais seulement 852 offres distinctes**. 152 offres ont été
lues et matchées trois fois ou plus. C'est la mécanique du balayage : chaque création retire
une ligne du feed, les pages glissent, et les lignes refusées réapparaissent sur la page
suivante. Aucun effet sur la justesse — une offre refusée reste refusée — mais près de la
moitié du temps de matching est refait. C'est aussi pourquoi ce rapport compte en offres et
non en lignes.

## 8. Ce que je recommande

1. **Retirer le préfixe « Expansion - »** dans `gog.py`. 14 offres récupérables sur les 3 473
   lignes, zéro risque : c'est une étiquette de rayon, pas un mot du produit.
2. **Neutraliser le contrôle de région interdite pour GOG**, pour la même raison que
   `title_region` répond déjà « global ». Une ligne aujourd'hui.
3. **Trancher la question du §4.** C'est la seule où il y a du volume à gagner, une vingtaine
   d'offres sur ces 16 pages, et c'est aussi la seule qui touche une règle revue.

Le reste des refus est juste et ne se récupère pas : AKS n'a pas la page, ou le produit n'est
pas celui de la page.
