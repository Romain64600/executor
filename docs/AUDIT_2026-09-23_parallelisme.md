# Audit — faut-il louer d'autres VPS pour lancer plus de marchands en parallèle ?

Romain, 2026-09-23 : « Tu penses que je suis obligé de louer d'autres VPS pour lancer plus de
marchands en parallèle, ou on peut le faire sur les serveurs existants ? Audit, ne code pas. »

Lecture seule. Aucune ligne de code modifiée. Mesures prises le 2026-09-23 vers 18 h, pendant
que deux balayages tournaient (GOG sur la nouvelle machine, groupe A sur l'ancienne), et sur
les journaux de six balayages récents.

---

## 1. Réponse courte

**Non, pas obligé.** La limite d'aujourd'hui n'est pas la machine : c'est **un onglet de
navigateur par machine**, un choix logiciel (le verrou `state/browser.lock`, OP1). La nouvelle
machine tourne à environ un quart de sa capacité.

Mais « plus d'onglets sur la même machine » ne rapporte pas pareil selon les marchands, parce
que tous les onglets d'une machine partagent **la même IP**, donc le même budget de requêtes
envers AKS. Le détail est au §5.

## 2. Ce que les machines ont sous le pied

| | Nouvelle VM (217.76.57.126) | Ancienne VM (51.38.37.254) |
|---|---|---|
| Cœurs | 8 | 4 |
| Mémoire | 24 Go, **19 Go libres** | 7,7 Go, 4,2 Go disponibles |
| Charge, un balayage en cours | ~1,9 | ~1,3 |
| Onglet AKS de Chromium | ~1,5 Go, ~40 % d'un cœur | ~1,4 Go, ~27 % d'un cœur |

Un onglet de plus coûte environ 1,5 Go et un demi-cœur. La nouvelle machine peut en porter
**quatre sans effort**, davantage si besoin. L'ancienne, **un de plus**, soit deux onglets en tout : elle
fait aussi tourner d'autres services.

## 3. Où part le temps d'un balayage

Reconstitué page par page sur six balayages récents :

| Balayage | Pages | Navigateur occupé | Matching (HTTP seul) | Par offre créée |
|---|---|---|---|---|
| GOG, 23/09 | 35 | **86 %** | 14 % | 49 s |
| GameSeal, 21/09 | 81 | **88 %** | 12 % | 61 s |
| Nuit 16 marchands, 21/09 | 264 | 74 % | 26 % | 86 s |
| Groupe A, 22/09 | 115 | 68 % | 32 % | 81 s |
| Groupe B, 22/09 | 148 | 53 % | 47 % | 72 s |

L'extraction ne pèse presque rien (une dizaine de secondes par page). **Le vrai coût, c'est
l'écriture : environ une minute par offre créée**, dans l'onglet unique. Plus un marchand crée,
plus son balayage est lié au navigateur. C'est exactement là que plusieurs onglets paient.

## 4. Ce qui empêche aujourd'hui plusieurs onglets sur une machine

1. **Le code, et lui seul pour le matériel.** Le pilote CDP prend toujours le premier onglet
   (`pages[0]`), le verrou vaut pour toute la machine, et la console n'accepte qu'un run à la
   fois. Le verrou existe parce que deux processus sur le MÊME onglet corrompent leurs lectures
   et leurs modales ; sur des onglets distincts, ce risque disparaît. Il faudrait un jeu
   d'onglets, un verrou par onglet, et une console qui accepte plusieurs runs. C'est un
   chantier de quelques jours, tests compris, et pas une modification d'infrastructure.
2. **Le budget de requêtes AKS par IP.** Le matching sonde AKS environ 255 fois par minute.
   Le 10 septembre, à ~300 requêtes par minute, AKS a répondu par salves de 503. Deux
   matchings simultanés sur la même IP dépasseraient ce seuil. Il faudrait donc un limiteur
   PARTAGÉ par machine : les onglets écrivent en parallèle, mais se relaient pour sonder.
3. **Un même marchand ne se coupe pas en deux.** Deux onglets sur le même feed feraient glisser
   les pages l'un sous l'autre. Le parallélisme se fait par marchand, ce qui tombe bien : il y
   en a dix-sept.
4. **La tolérance d'AKS aux écritures simultanées sur un même compte.** Deux écrivains en
   parallèle sont prouvés : les groupes A et B ont tourné ensemble pendant des heures, sans
   incident. Au-delà de deux, on ne sait pas. Il faut un essai avant de généraliser.

Aujourd'hui le budget par IP n'est pas tendu : sur ~700 pages matchées ces trois derniers jours,
un seul arrêt pour throttling (G2A, le 21), et les sondes douteuses sont tombées de 115-124 par
balayage à 1-6 depuis que le sitemap a remplacé la recherche morte.

## 5. Ce que plusieurs onglets rapporteraient, marchand par marchand

Avec un limiteur partagé, le matching devient la ressource commune de la machine, et
l'écriture se parallélise.

* **Marchands qui créent beaucoup** — GOG, GameSeal. Page type : 2 min de matching pour 12 min
  de navigateur. Une seule IP peut alimenter jusqu'à **six onglets** avant que le matching ne
  sature. Le gain est presque proportionnel au nombre d'onglets.
* **Marchands qui créent peu** — CJS, Eneba, les pages profondes de Kinguin. Page type :
  1,3 min de matching pour 1,4 min de navigateur. Le matching sature déjà ; un deuxième onglet
  sur la même IP ne rapporte presque rien. **Pour eux, c'est une autre IP qui compte**, donc
  une autre machine — ou moins de requêtes.

## 6. Le levier le moins cher, avant tout le reste

**Une bonne part des requêtes du matching est perdue d'avance.** 35 % des offres n'ont aucune page
AKS, et chacune coûte en moyenne **4,7 sondes aveugles** qui répondent 404 — slug complet,
slug sans édition, tête de titre, variantes année et ancienne forme. Soit ~164 requêtes
gaspillées par page de 100 lignes.

Depuis hier, le matcher dispose de l'index sitemap, qui sait sans aucune requête si une page
existe. S'en servir AVANT de sonder supprimerait ces requêtes : moins de temps de matching par
page, et surtout un budget IP libéré pour d'autres onglets. C'est aussi le seul levier qui aide
les marchands qui créent peu.

## 7. Quand louer vaut vraiment le coup

* **Quand le budget par IP sature** : si des grâces de throttling ou des salves de 503
  réapparaissent avec plusieurs onglets, c'est une IP qu'on achète, pas du CPU.
* **Pour la résilience** : le 11 septembre, l'IP de la nouvelle machine a été bannie plusieurs
  heures. Avoir deux IP a permis de continuer. Une troisième ne serait pas du luxe si le
  volume devient critique.
* **Pas pour la puissance de calcul** : la nouvelle machine n'en manque pas.

## 8. Ce que je recommande, dans l'ordre

1. **Matching guidé par le sitemap** : ne sonder que les pages qui existent. Gain immédiat
   sur tous les marchands, et prérequis des étapes suivantes.
2. **Deux onglets sur la nouvelle machine, en essai** : un marchand qui crée beaucoup par
   onglet, un limiteur de sondes partagé, et on regarde les 503 pendant une journée.
3. **Si l'essai est propre** : quatre onglets sur la nouvelle machine, deux sur l'ancienne.
   C'est de l'ordre de trois fois le débit actuel sur les marchands qui créent beaucoup.
4. **Louer seulement si** l'étape 3 bute sur le budget IP, ou pour avoir une troisième IP de
   secours.

Rien de tout cela n'est écrit : c'est un audit.
