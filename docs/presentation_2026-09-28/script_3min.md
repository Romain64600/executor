# Script de la présentation — 3 minutes

Présentation du **lundi 28 septembre 2026**, pour toute l'équipe : RH, SEO, data entry,
managers, développeurs. Le diaporama à projeter est `presentation.html` (7 diapositives) ; ce
texte y est repris tel quel dans les notes (touche **N**, avec un chrono).

- **Durée visée : 3 minutes** (180 s). Débit de référence : ~140 mots par minute, à l'oral, en
  comptant les changements de diapositive.
- **Total : 378 mots** (≈ 2 min 40 s à 140 mots/min) — la marge couvre les enchaînements.
- **Comptage des mots** : seules les lignes citées (`> …`) sont dites ; on compte les suites de
  caractères séparées par des espaces qui contiennent au moins une lettre ou un chiffre (« l'offre »
  = 1 mot, « 50 000 » = 2, un tiret seul = 0). `outils/generer_3min.py` refait ce compte et refuse
  de construire le diaporama si un en-tête ne correspond plus au texte.
- Les chiffres dits sont arrondis ; les chiffres exacts sont à l'écran et dans `chiffres.md`
  (comptage du 28/09 à 8 h 35).

| Diapositive | Durée visée | Mots | Fin visée |
|---|---:|---:|---:|
| 1 — Titre | 15 s | 36 | 0:15 |
| 2 — Le problème | 25 s | 58 | 0:40 |
| 3 — La solution | 40 s | 76 | 1:20 |
| 4 — Les résultats | 30 s | 57 | 1:50 |
| 5 — La confiance | 30 s | 64 | 2:20 |
| 6 — Ce que ça change pour vous | 30 s | 66 | 2:50 |
| 7 — La suite, merci | 10 s | 21 | 3:00 |
| **Total** | **180 s** | **378** | |

---

## 1 — Titre · 15 s · 36 mots

> Bonjour à tous ! En trois minutes, je vous présente un projet qui change la saisie des offres
> marchands : un robot qui saisit les offres comme le ferait un opérateur, et qui vérifie
> chacune de ses saisies.

Conseil : sourire, poser le cadre, passer vite.

## 2 — Le problème · 25 s · 58 mots

> D'abord, le problème. Sur AllKeyShop, chaque prix affiché sur la fiche d'un jeu, c'est l'offre
> d'un marchand. Les marchands nous envoient leurs offres, et elles arrivent dans une file
> d'attente. Pour chacune, il faut trouver le bon jeu, la plateforme, la région, l'édition… à la
> main, une par une. La semaine dernière, plus de 50 000 offres attendaient.

Conseil : marquer une pause après « 50 000 ».

## 3 — La solution · 40 s · 76 mots

> Notre solution : un robot qui fait le travail d'un opérateur, en quatre étapes. Un : il lit la
> file d'attente. Deux : il trouve la bonne fiche du jeu. Trois : il remplit la bonne case —
> plateforme, région, édition — dans le vrai formulaire d'AllKeyShop. Et quatre, le plus
> important : il vérifie. Il retourne dans la file d'attente et contrôle que l'offre en est bien
> sortie. C'est sa preuve. Et il travaille jour et nuit, sur deux serveurs en parallèle.

Conseil : montrer chaque étape du doigt en disant son numéro ; appuyer sur « il vérifie ».

## 4 — Les résultats · 30 s · 57 mots

> Les résultats. Depuis cet été, plus de 19 000 offres ont été saisies et vérifiées, presque
> toutes en septembre, depuis que le robot tourne en continu. Le record : plus de 2 600 offres
> en une seule journée, samedi dernier. Et 21 marchands sont déjà couverts. Chaque barre, c'est
> une journée : on voit bien la montée en puissance.

Conseil : laisser les trois chiffres parler ; ne pas commenter chaque barre.

## 5 — La confiance · 30 s · 64 mots

> Mais aller vite ne sert à rien si c'est faux. Alors la règle d'or, c'est : dans le doute, il ne
> saisit pas. Si une offre n'est pas claire, il la laisse dans la file d'attente pour un humain,
> et il note pourquoi. Au moindre problème, il s'arrête et nous prévient sur Discord. Et c'est
> toujours un humain qui le lance, le surveille et l'arrête.

Conseil : c'est le message le plus important pour le public non technique — le dire lentement.

## 6 — Ce que ça change pour vous · 30 s · 66 mots

> Concrètement, qu'est-ce que ça change pour vous ? Pour l'équipe data entry : moins de saisie
> répétitive, et les cas délicats restent entre vos mains. Pour le SEO : plus de prix, sur plus
> de fiches, mis en ligne plus vite. Pour les managers : un suivi en direct et des chiffres
> vérifiables. Et pour les développeurs : chaque règle est écrite et protégée par près de 2 900
> tests automatiques.

Conseil : regarder chaque groupe en parlant de lui. Si la question de l'emploi vient aux
questions : le robot prend le répétitif ; tout ce qui demande du jugement (les offres qu'il
refuse, les cas délicats, les corrections, les nouveaux marchands) reste à l'équipe.

## 7 — La suite, merci · 10 s · 21 mots

> La suite : ajouter de nouveaux marchands, et étudier une connexion directe au système
> d'AllKeyShop. Merci ! Je réponds volontiers à vos questions.

Conseil : pour les questions techniques, ouvrir l'annexe `annexe_technique/presentation_technique.html`
(19 diapositives, schémas détaillés).
