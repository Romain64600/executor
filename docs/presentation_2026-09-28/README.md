# Présentation du 28 septembre 2026 — Saisie automatique des offres marchands

Dossier de présentation du projet (**AKS Controlled Executor**), préparé le 27/09/2026 pour la
présentation de Romain du lundi 28/09. Tout est en français, sans secret (aucun cookie, jeton,
mot de passe ni adresse de machine : on dit « 2 VPS »).

## Contenu

| Fichier | Ce que c'est |
|---|---|
| `presentation.html` | Le diaporama, **autonome** (un seul fichier, aucune requête réseau) : 19 diapositives, schémas inclus. |
| `notes_orateur.md` | Les notes de l'orateur, diapositive par diapositive (3 à 6 lignes chacune). Les mêmes notes sont dans le diaporama (touche **N**). |
| `chiffres.md` | Tous les chiffres cités, **avec leur méthode et leur date** (offres créées au total, par marchand, par jour ; marchands, règles, tests, backlog). |
| `schemas/*.svg` | Les schémas, réutilisables tels quels dans PowerPoint, Google Slides ou Keynote (glisser-déposer). |
| `schemas/*.mmd` | Les sources Mermaid des schémas de flux, pour les re-dessiner ailleurs (mermaid.live, Notion, GitHub…). |
| `outils/` | Ce qui a servi à fabriquer le dossier : `generer.py` (dessine les SVG et assemble le diaporama), `presentation.gabarit.html` (le texte des diapositives), `donnees_creations.json` (les chiffres bruts). |

## Utiliser le diaporama

1. Ouvrir `presentation.html` dans un navigateur (Chrome, Firefox, Safari, Edge).
2. **F** ou F11 pour le plein écran.
3. **→ / espace** diapositive suivante, **←** précédente, **Début / Fin** pour sauter au début ou à la fin.
4. **N** affiche ou masque les notes de l'orateur en bas de l'écran (utile sur un second écran, ou pour répéter).
5. **Ctrl+P** imprime une diapositive par page, notes comprises (format paysage).
6. Un lien vers une diapositive précise : `presentation.html#8`.

## Réutiliser les schémas

- Les SVG de `schemas/` sont en 1600 × 900 (16:9) et restent nets à toute taille. Dans PowerPoint :
  *Insertion → Images → ce fichier* ; dans Google Slides : glisser le fichier sur la diapositive.
- Pour modifier un schéma : éditer `outils/generer.py` (les textes sont en clair, en français) puis
  lancer `python3 docs/presentation_2026-09-28/outils/generer.py` depuis la racine du dépôt. Le
  diaporama est réassemblé en même temps.
- Les fichiers `.mmd` décrivent les mêmes flux en Mermaid, pour un rendu automatique ailleurs.

## À compléter par Romain

- Diapositive 1 : ton nom et ton rôle (le texte « nom / rôle à compléter » est souligné en pointillé).
- Diapositive 12 (console) : une démonstration en direct remplace avantageusement la diapositive si
  la salle a le réseau.
- Les chiffres ont été arrêtés le **27/09/2026 au matin** (voir `chiffres.md`) ; pour les rafraîchir
  le lundi, relancer la méthode décrite dans `chiffres.md` et `outils/generer.py`.

## Où sont les détails

`README.md` du dépôt (exploitation), `docs/EXECUTOR_RULES.md` (les règles), `docs/MERCHANTS.md`
(chaque marchand), `docs/ARCHITECTURE.md` (les pièces), `docs/CHANGELOG.md` (l'historique),
`AGENTS.md` (les décisions revues).
