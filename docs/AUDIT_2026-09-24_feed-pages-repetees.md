# Audit : pourquoi le feed d'AKS renvoie les mêmes lignes sur plusieurs pages

Romain, 2026-09-24 : « go pour chercher pourquoi AKS renvoie les mêmes lignes ».

Diagnostic en lecture seule. On a mesuré sur les balayages des 21 au 24/09, sur les deux VM,
puis ouvert six fois la page du feed Wyrel dans le navigateur officiel, sans aucun clic. Aucun
code n'a été modifié.

---

## 1. La cause

**Le feed marchand est trié par date de création seulement, et des milliers de lignes ont la
même date à la seconde près.**

- Par défaut, la page `aks-merchant-feeds` trie par `createdAt`, du plus récent au plus ancien.
  Page 1 : Wyrel, créées du 20 au 24/09. Page 51 : juin-juillet.
- Les marchands sont importés en masse. Chez Wyrel, plus de 2 000 lignes portent
  `2026-07-30 13:41:16` ou `:17`. Chez Kinguin, les blocs `2026-08-24 15:07:38` et `:39` en
  comptent plus de 3 000. Même chose chez GameSeal le `2026-08-01 09:03:50`, et chez Gamivo le
  `2026-07-27 09:02:15`.
- Quand beaucoup de lignes ont la même date, la base de données ne garantit **aucun ordre**
  entre elles. Chaque page (`LIMIT 100 OFFSET n`) pioche alors cent lignes du bloc sans règle :
  on retombe sur les mêmes, et d'autres ne sortent jamais.

**Preuve** : dans les 7 balayages mesurés, **chaque page 100 % répétée est une page où les cent
lignes ont exactement la même date de création**, sans une seule exception (Kinguin 24 sur 24,
GameSeal 19 sur 19, Gamivo 13 sur 13, Wyrel 11 sur 11, GOG 6 sur 6…). Les marchands sans gros
import simultané (Driffle, Instant Gaming, MMOGA, G2A) n'ont **aucune** page répétée.

## 2. Ce que ça coûte

**Des lignes que nos balayages ne voient jamais.** Si les pages *p* à *q* ne contiennent
qu'une seule date, le bloc compte au moins *(q − p + 1) × 100* lignes. On le compare aux lignes
distinctes réellement vues sur ces pages. Minimum de lignes **jamais montrées**, par passe :

| Marchand | Balayage | Places dans les blocs | Lignes vues | Jamais montrées (au moins) |
|---|---|---|---|---|
| GameSeal | 21/09 | 7 000 | 2 719 | **4 281** |
| GameSeal | 23/09 | 5 300 | 1 692 | **3 608** |
| Kinguin | 22/09 | 4 600 | 1 012 | **3 588** |
| Kinguin | 24/09 | 4 500 | 955 | **3 545** |
| Gamivo | 22/09 | 2 900 | 980 | **1 920** |
| Wyrel | 24/09 | 3 400 | 1 650 | **1 750** |
| GOG | 23/09 | 2 500 | 1 359 | **1 141** |
| Eneba | 24/09 | 1 100 | 330 | **770** |
| CJS-CDKeys | 22/09 | 1 300 | 727 | **573** |
| GameBoost | 23/09 | 800 | 616 | 184 |
| Gamerall | 22/09 | 800 | 667 | 133 |

Sur une passe de tous les marchands, **plus de 13 000 lignes en attente** n'apparaissent jamais.
Le tirage n'est pas le même d'une passe à l'autre, donc certaines finissent par sortir, mais au
hasard. C'est une bonne part de l'écart entre les ~55 000 offres en attente et ce que nos scans
comptent : le scan tous-magasins du 21/09 n'a vu que 38 197 lignes, et il trie de la même façon.

**Du temps perdu** : une page répétée coûtait un matching complet (~2 min) et rejouait les
échecs (« Conclave » chez Wyrel, retentée sur quatre pages). Depuis le 24/09, ces pages sont
sautées (`skipped_repeated`), mais ça ne fait pas apparaître les lignes cachées.

## 3. Le remède : un tri sur une clé unique

La page propose dans ses en-têtes les tris `orderBy=createdAt | name | price | productId |
releaseDate` (`order=asc|desc`). Aucun de ces champs n'est unique. **Mais le serveur accepte
aussi `orderBy=id`, que l'écran ne propose pas.** Vérifié le 24/09 en lecture seule sur Wyrel :

- `&p=1&orderBy=id&order=desc` : 101140588, 101140587, 101140586… soit les ids strictement
  décroissants, les plus récents d'abord ;
- `&p=44&orderBy=id&order=desc` : 100612958, 100612954, 100612953…, strictement décroissants,
  au milieu du bloc du 30/07.

`id` est unique, donc l'ordre est **déterministe** : chaque ligne a une seule place, chaque page
est différente de la voisine, et aucune ligne n'est sautée. `id` croît avec l'import, donc
`order=desc` garde la même logique que le tri actuel : les plus récentes en page 1.

### Deux façons de l'appliquer

1. **Côté AKS, une ligne.** Ajouter un départage au tri par défaut :
   `ORDER BY createdAt DESC, id DESC`. Toutes les listes de l'outil en profitent, pour tout le
   monde. C'est la correction propre, et c'est à demander au dev AKS.
2. **Côté executor, sans attendre AKS.** Ajouter `&orderBy=id&order=desc` à **toutes** les URL
   de feed que le pipeline construit : l'extraction (`src/extractor.py`), le rechargement et la
   localisation dans le submitter, la preuve de disparition, le déplacement vers les listes,
   le scan tous-magasins. C'est obligatoire partout : si deux étapes d'un même run ne trient
   pas pareil, une ligne n'a plus le même numéro de page, et la localisation du submitter se
   trompe de page. Tests à prévoir, et un essai à blanc sur un marchand à gros blocs (Kinguin)
   avant de l'activer : lignes distinctes vues, contre lignes lues.

**Voie 2 codée le 2026-09-24** (Romain : « go pour la 2 ») : `extractor.feed_url`, la seule
fabrique d'URL de feed du pipeline, ajoute `FEED_ORDER = "&orderBy=id&order=desc"` à chaque URL,
et un test refuse une URL de feed fabriquée ailleurs. La voie 1 reste à demander au dev AKS.

## 4. Ce qui reste vrai après le remède

- Une ligne **ajoutée pendant** un balayage apparaît en page 1 et décale tout d'un cran vers les
  pages hautes. En descendant de la dernière page vers la 1, on peut donc en manquer autant
  qu'il en est arrivé pendant la passe. La passe suivante les rattrape. C'est le comportement
  d'aujourd'hui, en mieux.
- Le comptage `distinct_offers` du recap devient la mesure honnête de couverture : avec un tri
  unique, il doit être égal au nombre de lignes lues, aux créations près.
