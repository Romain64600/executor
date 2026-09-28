# Notes de l'orateur — annexe technique (version longue, 19 diapositives)

Une entrée par diapositive. Les mêmes notes sont dans `presentation_technique.html` (touche **N**).
C'est la version longue, pour les questions des développeurs ; la présentation de 3 minutes est
`../presentation.html` (script : `../script_3min.md`). Chiffres arrêtés le 27/09 au matin.
Durée visée : 25 à 30 minutes, questions comprises. Les diapositives 5 à 7 et 10 sont les
« schémas » : y passer du temps, le reste va vite.

## 1 — Titre

Une phrase d'accroche : « des dizaines de milliers d'offres marchands attendent d'être ajoutées à
la main ; on a construit une machine qui les ajoute avec la rigueur d'un humain soigneux, et qui
s'arrête au moindre doute ». Annoncer le plan : le problème, ce qu'on a construit, comment ça
marche, ce que ça a donné, la suite.

## 2 — Le problème

Les chiffres viennent d'une relecture complète de la liste Pending le 25/09 (plus de 500 pages).
Une bonne partie de l'attente est ancienne : 80 % des lignes vues datent d'avant septembre, et il
en arrive plusieurs centaines par jour. Anecdote utile : l'outil renvoyait les mêmes pages en
boucle (tri instable sur la date de création, bulk imports à la même seconde) ; on a fixé le tri
sur l'identifiant, et ~13 000 lignes jamais montrées sont apparues.

## 3 — Ce qu'on a construit

Insister sur « déterministe » : deux passages sur la même ligne donnent la même décision, et la
décision est expliquée (motif de refus nommé, lisible dans un rapport). Et sur « le vrai
formulaire » : on ne fabrique pas d'appel caché, on fait ce qu'un opérateur ferait, vérifié à
chaque pas. Le mot à retenir : **fail-closed**.

## 4 — En chiffres

Méthode : une offre est comptée quand le journal porte une saisie réussie **et prouvée** (l'offre
a disparu du feed rafraîchi). Journaux des deux machines additionnés, doublons impossibles (une
offre créée disparaît du feed). Détail dans `chiffres.md`. Le record du 26/09 : le groupe A et la
fin du groupe B tournaient en même temps, avec les nouvelles règles console.

## 5 — Vue d'ensemble (schéma)

Trois zones : l'opérateur ; le VPS (console + exécuteur + navigateur piloté + journal) ; AKS
(wp-admin pour lire le feed et écrire ; le site public et son sitemap pour reconnaître les
produits, en lecture HTTP). Deux VPS identiques, chacun un groupe de marchands. Le navigateur est
un vrai Chrome avec la session WordPress : c'est lui qui écrit, jamais un appel fabriqué. Le
sitemap AKS (213 599 pages) est lu d'abord : il évite des recherches inutiles.

## 6 — Le pipeline (schéma)

Une page = 100 offres. Cinq étapes séparées par StepGuard : l'étape suivante ne démarre que sur
un résultat valide (fichier présent, lisible, complet) — un blocage est un arrêt, pas une
négociation. Tout est écrit : fichiers du run et journal JSONL. Le balayage prend les pages de la
plus haute vers la 1 : les créations font remonter les lignes, donc on ne rate rien.

## 7 — Le parcours d'une offre (schéma)

Lire de haut en bas : à chaque étape, on avance ou on refuse avec un motif écrit. À droite, les
refus les plus fréquents. Ce qui décide : le fichier du marchand (sa grammaire de titre / URL /
page produit) et les règles générales numérotées. Le prix n'est **jamais** un juge (Romain : « faut pas
se fier au prix »). Un doute = un refus : la ligne reste au feed pour un humain.

## 8 — Des décisions réelles

Ce sont de vraies lignes des balayages des 25 et 26 septembre. Chaque décision correspond à une
règle écrite et testée : Play Anywhere confirmé sur la page PC ; PS5 hors GLOBAL → case
PlayStation de la génération (P3) ; « <Jeu> <X> Edition » = jeu + DLC → page du jeu (R18c, décidé
le 26/09 après avoir relu comment AKS range déjà ces offres : 25 offres « Mea Culpa Edition » sur
la page du jeu) ; Gamesplanet lit sa page produit ; Microsoft Store exige « Microsoft Windows » sur la
page (R62). Les deux refus illustrent le fail-closed.

## 9 — Où vivent les règles

La connaissance métier n'est ni dans une tête ni dans un prompt : elle est dans des fichiers
relus, testés, versionnés. Un fichier par marchand (21) ; 59 règles numérotées ; chaque décision
de Romain devient une règle, un test, et une « décision revue » consignée pour qu'un audit futur
ne la défasse pas. Les cas limites sont mesurés avant d'être appliqués (rejeu en lecture seule).

## 10 — Fail-closed (schéma)

La frise, de gauche à droite : rien ne démarre sans les invariants (machine autorisée, navigateur
officiel) ; rien ne passe une étape sans résultat valide ; on ne saisit que ce qui a été validé ;
la ligne et la modale sont vérifiées ; le vrai bouton ; la preuve. En bas : ce qui arrête (état
inconnu après un clic, dix échecs, session perdue) et ce qui est repris (une panne **avant** toute
écriture, 2 / 5 / 10 minutes, trois fois au plus). La reconnexion n'est jamais automatique.

## 11 — La preuve de saisie

Le cœur de la confiance : pour chaque offre créée, on peut relire la preuve de sa disparition du
feed. Exemple récent (26/09) : trois arrêts CJS venaient d'une recherche AKS insensible à la casse
que notre contrôle prenait pour une page étrangère ; on a corrigé le contrôle **sans affaiblir la
preuve** (la page doit porter notre terme dans son adresse), et les trois offres étaient bien
créées.

## 12 — La console d'admin

Si la salle a le réseau, montrer `/executor/auto` : les boutons de groupe avec la liste des
marchands, un récap de balayage, la page en cours. Rappeler que la console ne calcule rien : elle
affiche ce que le serveur envoie et renvoie un nom de groupe que le serveur re-valide. La
reconnexion (transfert de cookies) est la seule opération qui touche des secrets : les valeurs ne
sont jamais journalisées.

## 13 — L'exploitation (schéma)

Deux VPS, un groupe chacun, lancés le soir et suivis le lendemain. Ordres de grandeur : 2,5
minutes pour lire et matcher une page, une minute par offre créée (preuve comprise). Un groupe
complet : 20 à 40 heures selon la charge. Les groupes sont un point de départ, équilibrés sur la
charge en attente ; on les rééquilibre sur les durées observées.

## 14 — Résultats par marchand (schéma)

GameSeal domine parce que sa file est la plus grosse (5 500 lignes le 21/09) et qu'elle a été
balayée en entier plusieurs fois. Les petits chiffres ne sont pas des échecs : petites files
(GamersOutlet, Electronicfirst) ou entrées récentes (Gamesplanet FR le 25/09 ; Discover.games et
Loaded entrés le 26/09, pas encore balayés). Difmark se saisit à la main (liste « account »).

## 15 — Résultats par jour (schéma)

Les gros jours sont les nuits de groupe complètes sur les deux machines. Les creux : journées sans
balayage, ou consacrées aux corrections et aux nouvelles règles. Le 27 est une journée partielle
(chiffres arrêtés le matin).

## 16 — Les marchands couverts

Priorité aux boutiques dont le feed dit tout (titre + URL) ; ensuite celles dont la page produit est
lisible en HTTP (Gamesplanet FR, Discover.games) ; les boutiques derrière Cloudflare (Wyrel) ne
peuvent pas être lues, on ne dépend donc jamais de leur page. Trois marchands ajoutés en trois
jours. Pixelcodes / Software-codes : 3 085 produits de leur feed introuvables sur leur site — la
liste leur a été transmise.

## 17 — La qualité

Deux erreurs trouvées et corrigées grâce au dispositif, la même journée du 26/09 : les éditions
« jeu + DLC » rangées sur la page du DLC (18 offres, détectées en relisant les pages AKS ; règle
R18c, 13 routées correctement dès le lendemain) ; les faux « état inconnu » de la recherche CJS.
Dans les deux cas : mesure, correction, test, décision consignée.

## 18 — Ce qui reste, et la suite

Pas de date sur le prepaid : les 13 questions ouvertes (authentification, idempotence, format des
erreurs…) conditionnent tout. Sur les marchands : un par jour est tenable quand le feed est
lisible ; zéro quand le feed pointe vers des produits disparus. Les 22 offres à corriger à la
main sont listées dans le CHANGELOG du 26/09.

## 19 — Merci

Proposer une démonstration si le public est technique : un essai à blanc sur une page d'un
marchand, la lecture du rapport de refus, puis le récap d'un balayage de la nuit.
