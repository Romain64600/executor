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
| 3 | **Muve** (166) | 605 | 322 (53 %) | titre lisible pour ~40 % des lignes seulement | à étudier |
| 4 | **Pixelcodes** (82) + **Software-codes** (6) | 1 547 + 1 538 | 1 377 + 1 365 (89 %) | tout : titre et URL muets, page en JavaScript (illisible sans navigateur), aucune offre déjà sur AKS pour s'en inspirer | gros potentiel, difficile |
| 5 | **Discover.games** (168) | 440 | 370 (84 %) | idem Pixelcodes (aucune offre déjà sur AKS) | difficile |
| — | Greenmangaming (22) | 482 | 318 (66 %) | URL d'affiliation illisible (sjv.io), titre muet | pas prioritaire |

\* Mesuré sur le scan tous-magasins du 21/09, **avant** la correction du tri du feed (`orderBy=id`,
24/09) : ces comptes sont des minimums. Un nouveau scan tous-magasins les rafraîchira.

**Déjà faits** : Gamesplanet FR (liste blanche le 25/09, `[R59]`), Wyrel (liste blanche le 24/09, `[R53]` + `[R58]`), GOG (22/09), Gamerall
(19/09), GameBoost / Electronicfirst / GamersOutlet (16/09), Difmark (21/09).

---

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
