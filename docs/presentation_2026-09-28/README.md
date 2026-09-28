# Présentation du 28 septembre 2026 — Saisie automatique des offres marchands

Dossier de présentation du projet (**AKS Controlled Executor**) pour la présentation de Romain du
lundi 28/09, devant toute l'équipe : RH, SEO, data entry, managers, développeurs. Tout est en
français, sans secret (aucun cookie, jeton, mot de passe ni adresse de machine : on dit « 2 serveurs »).

**Deux niveaux :**

1. **La présentation de 3 minutes — à projeter.** `presentation.html` (7 diapositives, public non
   technique, zéro jargon) et son texte `script_3min.md`.
2. **L'annexe technique — pour les questions des développeurs.** `annexe_technique/`
   (19 diapositives, schémas détaillés, chiffres arrêtés au 27/09 au matin).

## Contenu

| Fichier | Ce que c'est |
|---|---|
| `presentation.html` | **Le diaporama de 3 minutes**, autonome (un seul fichier, aucune requête réseau) : 7 diapositives — titre, le problème, la solution en 4 étapes, les résultats, la confiance, ce que ça change pour chacun, la suite. |
| `script_3min.md` | **Le texte à dire**, diapositive par diapositive, avec la durée visée et le nombre de mots (378 mots ≈ 2 min 40 s ; 3 min avec les enchaînements). Le même texte est dans les notes du diaporama (touche **N**). |
| `chiffres.md` | Tous les chiffres cités, **avec leur méthode et leur date** : comptage du 28/09 à 06 h 35 UTC (diaporama de 3 minutes) et du 27/09 au matin (annexe). |
| `annexe_technique/presentation_technique.html` | La version longue (19 diapositives, 25-30 min) : architecture, parcours d'une offre, règles, sécurité, exploitation, résultats par marchand. |
| `annexe_technique/notes_orateur_technique.md` | Ses notes d'orateur (aussi dans le diaporama, touche **N**). |
| `schemas/*.svg`, `schemas/*.mmd` | Les schémas de l'annexe, réutilisables dans PowerPoint, Google Slides, Keynote (SVG) ou Mermaid (`.mmd`). |
| `outils/` | Les générateurs et les données : `generer_3min.py` + `presentation_3min.gabarit.html` + `donnees_creations_2026-09-28.json` (diaporama de 3 minutes) ; `generer.py` + `presentation.gabarit.html` + `donnees_creations.json` (annexe et schémas, 27/09) ; `compter_creations.py` (le compteur, lecture seule). |

## Présenter (3 minutes)

1. Ouvrir `presentation.html` dans un navigateur (Chrome, Firefox, Safari, Edge) — aucun réseau requis.
2. **F** : plein écran (F11 marche aussi).
3. **→ / espace / Entrée** : diapositive suivante ; **←** : précédente ; **Début / Fin** : première / dernière.
4. **N** : notes de l'orateur (le texte à dire) + un **chrono** en haut à gauche, qui indique la fin
   visée de la diapositive en cours (il change de couleur en cas de retard). **T** remet le chrono à zéro.
5. Deux écrans : ouvrir une seconde fenêtre sur `presentation.html?notes` (notes affichées d'office)
   pour l'orateur, et projeter l'autre.
6. **Ctrl+P** : une diapositive par page (format 16:9, sans les notes — le texte est dans `script_3min.md`).
7. Lien direct vers une diapositive : `presentation.html#4`.

Déroulé : 15 s titre · 25 s problème · 40 s solution · 30 s résultats · 30 s confiance · 30 s
« pour vous » · 10 s suite et merci = **3:00**.

**À compléter par Romain** : diapositive 1, « Romain · rôle à compléter » (souligné en pointillé),
dans `outils/presentation_3min.gabarit.html`, puis relancer le générateur (ci-dessous).

## Modifier ou rafraîchir

- **Le texte des diapositives** : `outils/presentation_3min.gabarit.html`. **Le texte dit** :
  `script_3min.md` (les notes du diaporama en sont tirées ; si un texte change, mettre à jour son
  nombre de mots dans l'en-tête et le tableau — le générateur refuse sinon et dit quoi corriger).
- **Reconstruire** : `python3 docs/presentation_2026-09-28/outils/generer_3min.py` depuis la
  racine du dépôt. Il vérifie : SVG bien formés, 7 diapositives au plus, aucune adresse réseau,
  aucun mot technique à l'écran ni dans le texte dit, ≤ 430 mots et ≤ 180 s.
- **Rafraîchir les chiffres** (lecture seule sur les 2 serveurs de production) : la marche à suivre
  est en tête de `outils/generer_3min.py` (deux lancements de `compter_creations.py`, puis
  `--fusion`). Reporter ensuite les chiffres dans `chiffres.md`.
- **L'annexe** : `python3 docs/presentation_2026-09-28/outils/generer.py` redessine les schémas
  et réassemble `annexe_technique/presentation_technique.html` (chiffres du 27/09, figés : ses
  légendes datent la période).

## Où sont les détails

`README.md` du dépôt (exploitation), `docs/EXECUTOR_RULES.md` (les règles), `docs/MERCHANTS.md`
(chaque marchand), `docs/ARCHITECTURE.md` (les pièces), `docs/CHANGELOG.md` (l'historique),
`AGENTS.md` (les décisions revues).
