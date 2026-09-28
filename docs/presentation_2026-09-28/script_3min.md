# Script de la présentation — 3 minutes

Présentation du **lundi 28 septembre 2026**, pour toute l'équipe : RH, SEO, data entry,
managers, développeurs. Le diaporama à projeter est `presentation.html` (7 diapositives) ; ce
texte y est repris tel quel dans les notes (touche **N**, avec un chrono).

- **Durée visée : moins de 3 minutes.** Les durées ci-dessous totalisent **2:50** (170 s) : les
  10 dernières secondes sont une marge, pas un objectif. Débit de référence : ~130 mots par minute,
  plus une seconde par changement de diapositive.
- **Total : 351 mots** (≈ 2 min 42 s à 130 mots/min ; les nombres dits en toutes lettres,
  « deux mille six cents », en ajoutent quelques-uns).
- **Comptage des mots** : seules les lignes citées (`> …`) sont dites ; on compte les suites de
  caractères séparées par des espaces qui contiennent au moins une lettre ou un chiffre (« l'offre »
  = 1 mot, « 50 000 » = 2, un tiret seul = 0). `outils/generer_3min.py` refait ce compte et refuse
  de construire le diaporama si un en-tête ne correspond plus au texte.
- Les chiffres dits sont arrondis ; les chiffres exacts sont à l'écran et dans `chiffres.md`
  (comptage du 28/09 à 8 h 35).

**Avant de commencer.** Imprimer ce texte (secours). Ouvrir `presentation.html`, **F** pour le
plein écran, puis **T** au moment de parler : le chrono démarre au chargement de la page, T le
remet à zéro. Si l'écran de l'ordinateur est recopié sur le projecteur, **ne pas appuyer sur N** :
les notes s'afficheraient pour la salle. Ouvrir d'avance l'annexe technique dans un second onglet
pour les questions des développeurs.

| Diapositive | Durée visée | Mots | Fin visée |
|---|---:|---:|---:|
| 1 — Titre | 12 s | 25 | 0:12 |
| 2 — Le problème | 28 s | 58 | 0:40 |
| 3 — La solution | 33 s | 70 | 1:13 |
| 4 — Les résultats | 22 s | 39 | 1:35 |
| 5 — La confiance | 34 s | 70 | 2:09 |
| 6 — Ce que ça change pour vous | 29 s | 63 | 2:38 |
| 7 — La suite, merci | 12 s | 26 | 2:50 |
| **Total** | **170 s** | **351** | |

---

## 1 — Titre · 12 s · 25 mots

> Bonjour à tous ! En trois minutes : un robot qui prend en charge la saisie répétitive des
> offres marchands, et qui contrôle chacune de ses saisies.

Conseil : sourire, poser le cadre, passer vite. Appuyer sur T (chrono) juste avant de commencer.

## 2 — Le problème · 28 s · 58 mots

> Le problème. Chaque prix affiché sur AllKeyShop, c'est l'offre d'un marchand. Ces offres
> arrivent dans une file d'attente, et tant qu'une offre attend, son prix n'est pas sur le site.
> Pour chacune, il faut trouver le jeu, la plateforme, la région, l'édition… à la main. La
> semaine dernière, plus de 50 000 attendaient, la plupart depuis des semaines.

Conseil : montrer l'exemple à droite (le titre du marchand, puis les quatre choix). Marquer une
pause après « 50 000 ».

## 3 — La solution · 33 s · 70 mots

> Notre solution : un robot qui reprend les gestes répétitifs, en quatre étapes. Un : il lit la
> file d'attente. Deux : il trouve la bonne page produit. Trois : il choisit la plateforme, la
> région, l'édition, dans le vrai formulaire d'AllKeyShop. Et quatre, le plus important : il
> retourne voir la file d'attente. Si l'offre n'y est plus, c'est qu'elle est bien enregistrée.
> C'est sa preuve. Il tourne jour et nuit, sur deux serveurs.

Conseil : montrer chaque étape du doigt en disant son numéro ; appuyer sur l'étape 4.

## 4 — Les résultats · 22 s · 39 mots

> Les résultats. Depuis cet été, plus de 19 000 offres ont été saisies, chacune contrôlée. Le
> record : plus de 2 600 en une seule journée. Et 21 marchands sont pris en charge. Le graphique
> montre la montée en puissance.

Conseil : laisser les trois chiffres parler ; ne pas commenter chaque barre, ne pas donner le jour
du record (il dépend du fuseau horaire, voir les questions en fin de texte).

## 5 — La confiance · 34 s · 70 mots

> Aller vite ne sert à rien si c'est faux. La règle d'or : dans le doute, il ne saisit pas. Une
> offre pas claire ? Il la laisse à l'équipe, et note pourquoi. Au moindre problème, il s'arrête
> et le signale. Ce n'est pas une IA qui devine : il applique des règles écrites, vérifiées par
> près de 2 900 tests automatiques. Et un humain le lance, et peut l'arrêter à tout moment.

Conseil : c'est le message le plus important pour le public non technique — le dire lentement.

## 6 — Ce que ça change pour vous · 29 s · 63 mots

> Qu'est-ce que ça change pour vous ? Pour l'équipe data entry : le répétitif part au robot, les
> cas délicats restent entre vos mains. Pour le SEO : plus de prix, sur plus de pages produits, mis en
> ligne plus vite. Pour les managers : des chiffres précis, offre par offre. Et pour toute
> l'équipe : moins de copier-coller, plus de temps pour ce qui demande du jugement.

Conseil : regarder chaque groupe en parlant de lui. Si la question de l'emploi vient : le robot
prend le répétitif ; tout ce qui demande du jugement (les offres qu'il refuse, les corrections, les
nouveaux marchands) reste à l'équipe. Ne rien promettre au nom des RH.

## 7 — La suite, merci · 12 s · 26 mots

> La suite : de nouveaux marchands, et, à l'étude, un branchement direct sur AllKeyShop, sans
> passer par le formulaire. Vos retours sont les bienvenus. Merci ! Des questions ?

### Questions probables (réponses courtes)

- **« C'est de l'IA ? »** Il ne devine rien : il applique des règles écrites, décidées une par
  une et testées. Si on insiste : il a été construit avec l'aide d'une IA, mais ce qui tourne suit
  des règles fixes.
- **« Et s'il se trompe ? »** C'est rare. Quand on trouve une erreur, on corrige la règle et on
  liste les offres concernées pour les reprendre : le 26/09, 22 offres mal rangées (18 sur la page produit
  d'un contenu additionnel au lieu de celle du jeu, 4 dans la mauvaise édition), règle corrigée le
  jour même.
- **« Il en reste combien ? »** Les 50 000 sont le relevé du 25/09 ; la file bouge, il arrive
  plusieurs centaines d'offres par jour. Une partie n'est pas pour le robot : environ 3 100 hors jeu
  (cartes cadeaux, comptes…) et 1 600 dans des régions qu'on ne vend pas.
- **« Pourquoi des creux dans le graphique ? »** Ça dépend des marchands traités ce jour-là et de la
  part de leurs offres que le robot peut saisir ; les 13 et 14/09, aucune saisie.
- **« Le jour du record ? »** Journées comptées en heure UTC : 2 627 le 26/09. En heure de Paris, le
  jour du record change (le 20/09 selon la relecture). Dire « plus de 2 600 en une journée », sans
  nommer le jour.
- **« Combien de temps à la main ? »** Aucun chiffre mesuré : ne répondre que si tu en as un fiable.
  Le robot : environ une minute par offre, contrôle compris.
- **Questions techniques** : ouvrir l'annexe `annexe_technique/presentation_technique.html`
  (19 diapositives, schémas). Ses chiffres datent du 27/09 au matin (17 317 offres) : le total
  diffère de celui du jour, c'est normal.
