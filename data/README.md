# `data/` — les données que la console écrit et qui doivent être VERSIONNÉES

Ce répertoire n'est pas `state/`. La différence est délibérée : `state/` est local à une
machine et gitignoré (verrous, marqueurs de run), tandis que `data/` est commité, parce que
son contenu doit être IDENTIQUE sur les deux serveurs.

* `sort_sql_promoted.json` — les motifs de tri promus depuis la console `/sql` (et ceux
  explicitement écartés). Sans versionnement, le nouveau VPS et l'ancien dériveraient, chacun
  avec ses propres règles, et la liste que Romain colle dans phpMyAdmin dépendrait de la
  machine depuis laquelle il l'a ouverte. Le fichier se relit et se corrige à la main.

Après une promotion faite dans la console, penser à commiter ce fichier et à tirer sur les
deux serveurs — c'est le seul geste manuel de cette voie.
