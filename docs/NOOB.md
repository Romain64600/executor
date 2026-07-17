# Le projet expliqué aux débutants (guide « noob »)

> Ce guide explique le projet **sans supposer aucune connaissance préalable**.
> Il est volontairement rédigé en français et avec des analogies de la vie
> courante. Pour les spécifications exactes, voir les autres documents de
> `docs/` (en anglais), dont les principaux sont listés [à la fin](#pour-aller-plus-loin).

---

## 1. C'est quoi, ce projet, en une phrase ?

C'est un **robot de saisie de données, prudent et vérifiable**, qui ajoute des
offres de jeux vidéo sur le site AllKeyShop — et qui préfère **s'arrêter**
plutôt que de deviner quand quelque chose est incertain.

---

## 2. Le contexte : AllKeyShop et la « saisie de flux marchand »

**AllKeyShop (AKS)** est un comparateur de prix de clés de jeux vidéo. Des
vendeurs (les « marchands » : Driffle, G2A, Kinguin, K4G…) envoient à AKS une
liste d'offres à ajouter au site : c'est le **flux marchand** (*merchant
feed*), une sorte de liste de tâches visible dans l'administration WordPress
d'AKS.

Le travail à faire, offre par offre :

1. lire une offre du flux (ex. « Elden Ring Deluxe Edition — Steam — EU ») ;
2. trouver la **bonne fiche produit** sur AllKeyShop ;
3. saisir l'offre dans le bon formulaire (bonne région, bonne édition) ;
4. vérifier qu'elle a **vraiment** été créée.

C'est répétitif, mais chaque erreur pollue la base de données du site. C'est
donc un travail où **l'exactitude compte plus que la vitesse**.

---

## 3. L'histoire : pourquoi ce projet existe

Avant, ce travail était confié à un agent IA « libre » nommé **Hermès** : un
modèle de langage qui pilotait un navigateur à sa guise. Problème : quand il
était bloqué, il **improvisait** :

- il réessayait six fois la même action morte ;
- il basculait sur un navigateur non autorisé ;
- il allumait un VPN dont personne n'avait besoin ;
- et le pire : il voyait un petit message vert « succès » à l'écran et
  annonçait « offre créée ! »… alors que **rien** n'était entré en base.

> **Analogie.** Hermès était comme un stagiaire zélé chargé de livrer des
> colis : porte fermée ? Il passe par la fenêtre. Mauvais immeuble ? Il en
> essaie un autre. Puis il annonce « livré ! » alors que le colis est encore
> dans la camionnette.

La solution n'a pas été de chercher « un meilleur stagiaire », mais de
**changer les rôles** :

- le travail risqué est fait par un **moteur déterministe** (des scripts
  Python qui font toujours la même chose dans le même ordre) ;
- l'IA (Claude / Codex) devient un **bâtisseur** (*builder*) : elle écrit,
  teste et audite le code du moteur, mais **ne touche jamais** au navigateur
  pour soumettre une offre elle-même ;
- Hermès est rétrogradé en superviseur optionnel : il lit des rapports, il ne
  pilote plus rien.

---

## 4. Les trois principes à retenir

### a) *Fail-closed* : dans le doute, on s'arrête

Comme la porte d'un coffre-fort de banque : au moindre problème, elle se
**verrouille**. Elle ne s'ouvre jamais « pour que ça continue d'avancer ».
Concrètement : pas de navigateur de secours, pas de VPN de contournement, pas
de mode dégradé. Une incertitude → un rapport d'erreur et un arrêt propre.
**Un arrêt n'est pas un bug : c'est le comportement voulu.**

### b) Le succès est décidé par du code, jamais par une opinion

Un « succès » enregistré vient toujours d'un fait vérifiable par programme :
un code HTTP, un champ d'erreur, ou — pour une soumission — **la disparition
de l'offre du flux rechargé**. Jamais d'un modèle qui « trouve que ça a l'air
d'avoir marché ».

> **Analogie.** C'est vérifier son relevé bancaire au lieu de croire le popup
> « Paiement réussi ! ». Le popup peut mentir (il l'a fait) ; le relevé, non.

### c) Un humain valide, la machine exécute

Aucune offre n'est soumise sans qu'un humain (Romain) ait approuvé **cette
offre précise** dans un fichier de validation. Une fois le lot approuvé, c'est
le **mode de saisie** qui dit combien d'offres partent (règle R24, 2026-07-13,
détaillée en section 5) :

- en mode `safe` — le mode par défaut, comportement éprouvé — le robot soumet
  **tout le lot validé** d'un coup : la validation humaine est déjà le
  garde-fou, on n'empile pas un « canari » par-dessus ;
- dans les modes d'exploration (`learning`, `advanced`), où l'on teste une
  nouveauté, il est bridé à **une seule** offre (le « canari »), le temps de
  vérifier que la nouveauté se passe bien.

---

## 5. La chaîne de montage : le pipeline

Le projet est une suite de scripts numérotés, comme les postes d'une chaîne de
montage. Les étapes 00 à 04 sont en **lecture seule** (elles ne peuvent rien
modifier sur le site). Seules deux étapes « écrivent » quelque chose : l'étape
0b (la connexion, qui saisit les identifiants — uniquement sur ordre
explicite) et l'étape 05 (la soumission — verrouillée).

```
00 audit ──► 01 invariants ──► 02 extraction ──► 03 matching ──► 04 validation ──► 05 soumission
(état des     (feu vert          (lire le flux      (trier &        (approbation      (écrire, enfin —
 lieux)        obligatoire)       marchand)          associer)       HUMAINE)          avec preuve)
```

(À côté de la chaîne : l'étape **0b** — la connexion — remet la session en
état quand elle a expiré, uniquement à la demande. Voir plus bas.)

### Étape 00 — `scripts/00_audit_env.sh` : l'état des lieux

Un script bash qui vérifie l'environnement (AllKeyShop joignable, pas de VPN
actif, navigateur correct…) et écrit un rapport lisible dans
`runs/audit_<horodatage>/audit.md`. Résultat final : `GREEN`, `RED`, ou
`NON-AUTHORITATIVE` (voir la section 7).

### Étape 01 — `scripts/01_check_invariants.py` : le feu vert

Vérifie trois **invariants** (des conditions non négociables) :

1. AllKeyShop répond en accès direct (statut HTTP 200, 301 ou 302) ;
2. **aucun** processus OpenVPN ne tourne ;
3. le navigateur est joignable sur le **bon** point de contrôle (la
   « télécommande » du navigateur, expliquée en section 7), avec exactement
   la bonne carte d'identité de navigateur (le *User-Agent*, épinglé sur
   Chrome version 149).

Il imprime un JSON avec deux booléens : `ok` (tout est vert ?) et
`authoritative` (suis-je sur la vraie machine de production ?). **Aucune étape
d'écriture ne se déverrouille tant que les deux ne sont pas vrais.**

### Étape 0b — `scripts/00b_login.py` : la connexion (la seule étape qui touche aux identifiants)

Toutes les autres étapes supposent une session déjà connectée à
l'administration WordPress d'AKS. Quand la session a expiré, cette étape se
reconnecte — **uniquement sur ordre explicite de Romain**, jamais toute seule
(une étape qui découvre qu'elle est déconnectée s'arrête avec un rapport
d'erreur ; elle ne relance jamais le login elle-même). Elle exige d'abord,
elle aussi, le feu vert des invariants.

Ses règles sont volontairement rigides : le mot de passe vient de
l'environnement (jamais d'un fichier, d'un journal ou d'un commit) ; le code
2FA n'est demandé que lorsque le champ est **visible et prêt** à être soumis
immédiatement — jamais en avance ; et chacun n'a droit qu'à **une seule
tentative** : un échec = arrêt, jamais de boucle de réessai (des connexions
ratées en rafale peuvent faire bloquer le compte). Si la session est déjà
connectée, l'étape ne fait rien et le dit.

### Étape 02 — `scripts/02_extract_feed.py` : l'extracteur (lecture seule)

Il feuillette les pages du flux marchand dans l'admin WordPress d'AKS et
récolte toutes les lignes d'offres. Subtilité importante : le flux **mélange
ses lignes** entre deux chargements de page. Un seul passage rate donc des
offres, c'est prouvé (sur G2A : 762 lignes vues, seulement 482 distinctes en
un passage).

> **Analogie.** C'est compter des moutons dans un pré où ils changent de
> parc sans arrêt : on refait des tours complets en notant les numéros de
> boucle d'oreille, et on ne fait confiance au comptage que lorsqu'un tour
> entier n'apporte **aucun** nouveau numéro.

Il produit deux fichiers dans `runs/<run_id>/` :

- `raw.json` — les lignes d'offres telles que lues dans la page (déjà
  dédoublonnées par identifiant), conservées pour l'audit ;
- `offers.json` — la version nettoyée et typée (champs normalisés,
  vérifiés un à un).

S'il est renvoyé vers la page de login, ou qu'une page est vide sans
explication, il **s'arrête bruyamment** au lieu de rendre un flux vide en
silence.

### Étape 03 — `scripts/03_match.py` : le matcheur (lecture seule)

Le videur de boîte de nuit du projet : il examine chaque offre avec une
**check-list écrite**, jamais « au feeling » :

- il écarte d'office tout ce qui n'est pas un **jeu PC simple** : consoles,
  régions interdites, cartes cadeaux, DLC dans le titre, **bundles et skins**
  (règle catégorique, aucune exception), **logiciels et applications**
  (règle R22 : *games only*) ;
- il détermine la plateforme, la **région** (lue dans l'URL du marchand, qui
  a priorité sur le titre) et l'**édition** (lue d'abord dans le *slug* de
  l'URL — la partie lisible de l'adresse, ex. `...-deluxe-edition-...`) ;
- il devine l'URL de la fiche produit AllKeyShop et la vérifie par une simple
  lecture HTTP ;
- il exige que **chaque mot** du nom du produit AKS apparaisse dans le titre
  du marchand (règle R01, correspondance stricte — pas de « à peu près ») ;
  un mot en trop dangereux (« Remastered », « DLC »…) est aussi éliminatoire.

Au moindre doute → l'offre est **écartée** (*skip*), avec la raison notée dans
`skipped.json`. C'est voulu : un jeu écarté à tort reste visible et
rattrapable par un humain ; une offre fausse acceptée abîme la base de données
sans que personne ne le voie. Qu'une grande majorité d'offres soit écartée est
**normal** (rendement G2A : ~2-3 %).

Il produit : `candidates.json` (les offres retenues, 100 maximum),
`skipped.json` (les écartées + raisons) et `report.txt` (le rapport pour
Romain, au format fixe de blocs de 5 lignes — jamais de tableaux, jamais de
prix).

### Étape 04 — `scripts/04_validate.py` : la validation humaine

Le script génère `validation.template.json`, où chaque candidat a
`approve: false`. **Un humain** édite ce fichier à la main : il passe
`approve: true` sur les offres choisies et remplit `validated_by` et
`validated_at`. Puis le script vérifie le fichier rempli et produit
`approved.json` : la liste exacte des offres autorisées. (Aujourd'hui, la
**page opérateur** — voir plus bas — fait cette édition à ta place, en cochant
des cases ; le mécanisme derrière est exactement le même.)

Chaque candidat est identifié par une **empreinte** (*fingerprint*) :
`offer_id|aks_product_id|region_id|edition_id`. Si l'un de ces éléments change
plus tard (par exemple une autre édition détectée), l'empreinte change et
l'ancienne approbation devient **caduque**.

> **Analogie.** On approuve une voiture par son numéro de châssis, pas par
> « la berline bleue ». Si la voiture est changée après signature, la
> signature ne vaut plus rien.

Un seul problème dans le fichier (signature ou date manquante, une empreinte
approuvée qui ne correspond plus à un candidat actuel) → **tout le fichier
est rejeté**. Jamais d'approbation partielle.

### Étape 05 — `scripts/05_submit.py` : le soumetteur (le seul qui écrit)

Verrouillé de trois façons :

1. **Répétition générale par défaut** : sans option, c'est un *dry-run* — il
   rejoue le début de la procédure (retrouver chaque ligne, ouvrir la fenêtre
   de saisie, vérifier son contexte et ses listes déroulantes) mais ne
   remplit **rien** (ni région, ni édition, ni cible) et ne clique **jamais**
   sur « Create offer ». La vraie écriture exige l'option explicite
   `--submit`.
2. **Re-vérification de l'approbation** : `approved.json` seul ne fait pas
   autorité. Le soumetteur re-dérive la liste approuvée depuis
   `candidates.json` + `validation.json` et exige une correspondance exacte.
   Un `approved.json` bricolé à la main ou périmé → refus de démarrer.
3. **Le mode décide de la taille du lot** (`--mode`, défaut `safe`). Une fois le
   rapport normalisé validé, on soumet — et le mode dit *combien* :
   - `safe` : le **lot validé complet**, **sans canari**. Le rapport validé
     *est* le garde-fou : il dit déjà quelles offres partent.
   - `learning` : on explore un déblocage (catégorie × marchand). Ce mode
     **écrit vraiment** (il ajoute les offres dès que le rapport est valide),
     mais il est **bridé à 1 offre** pour le moment.
   - `advanced` : déblocages validés ; même bridage à 1 pour le moment.

   Dans `learning` / `advanced` le canari est un **plafond**, pas un défaut :
   `--limit N` peut le **réduire**, jamais l'élargir (un `--limit` plus grand
   est refusé).

   ⚠️ Retiens bien : `submit` **sans option** écrit **tout le lot validé**, pas
   une seule offre.

Pour chaque offre, le soumetteur : recharge le flux, retrouve la ligne
**actuelle** exacte (par identifiant *et* par URL marchande, car AKS
renumérote toutes ses lignes à chaque réimport), ouvre la fenêtre de saisie
depuis cette ligne, vérifie son contexte, choisit région et édition par de
**vrais clics** envoyés au navigateur (pas de valeurs injectées en douce — ça
a déjà créé de fausses éditions), vérifie que le formulaire est **valide au
sens HTML5** (un formulaire invalide est refusé par le navigateur *en
silence*, sans erreur — c'est un piège connu), et clique enfin sur le vrai
bouton « Create offer ».

**Et ensuite, la preuve.** Voir §6, c'est le cœur du projet.

En cas d'échec sur une offre : on **ne réessaie jamais** la même offre ; on
note, on passe à la suivante ; et après 10 échecs consécutifs, tout le run
s'arrête. Les résultats sont écrits dans `submit_plan.json` (machine) et
`submit_report.txt` (humain) — qui distinguent volontairement les
**tentatives** d'écriture des créations **vérifiées**.

### La page opérateur : `/executor/` (le chemin normal aujourd'hui)

Depuis juillet 2026, plus besoin d'éditer les fichiers JSON à la main : une
page web servie par le VPS (adresse en `/executor/`, protégée par HTTPS et un
mot de passe) est le poste de travail normal de l'opérateur. Elle permet de :

- vérifier les invariants et lancer une extraction pour un marchand ;
- lire le rapport et cocher/décocher chaque candidat — avec, si besoin,
  correction de la région ou de l'édition (uniquement parmi les valeurs du
  catalogue du run), ou suppression d'une erreur du matcheur (toujours
  journalisée, jamais perdue en silence) ;
- enregistrer : la page repasse par le **vrai** script de validation et
  régénère le trio `candidates.json` + `validation.json` + `approved.json`
  — elle ne peut jamais retoucher `approved.json` tout seul ;
- lancer la répétition générale (*dry-run*) puis, sur décision, la vraie
  soumission : le bouton « Soumettre » ouvre une confirmation qui exige de
  taper `GO`, et c'est le **même** `05_submit.py` qui tourne, surveillé de
  bout en bout (jamais lancé-puis-oublié).

La page affiche aussi l'état de chaque offre (**ajoutée** / **échec** / **en
attente**) et **verrouille** les offres déjà créées : impossible de les
réapprouver ou de les resoumettre par accident.

### Le lanceur en ligne de commande : `manual_launch/run_executor.sh`

L'alternative à la page, pour dérouler la chaîne au terminal sans mémoriser
cinq scripts — un enchaîneur à quatre commandes :

```bash
manual_launch/run_executor.sh prepare --merchant Driffle --store-id 127   # étapes 00→04 (template)
# ... éditer runs/<run>/validation.template.json à la main ...
manual_launch/run_executor.sh check   runs/<run>                          # vérifie → approved.json
manual_launch/run_executor.sh dry-run runs/<run> --merchant Driffle --store-id 127
manual_launch/run_executor.sh submit  runs/<run> --merchant Driffle --store-id 127   # mode safe : TOUT le lot validé
manual_launch/run_executor.sh submit  runs/<run> --merchant Driffle --store-id 127 --mode learning   # canari de 1
```

(`--store-id` est le numéro identifiant le magasin du marchand chez AKS —
par exemple Driffle = 127 ; on le lit dans l'URL du flux marchand.)

`prepare` s'arrête **toujours** avant toute écriture, et `submit` n'est lancé
que sur décision explicite.

---

## 6. La preuve de succès : « l'offre a disparu du flux »

C'est LA règle du projet, née de la pire panne d'Hermès.

Le flux marchand est la **liste de tâches** du site : les offres encore à
saisir. Quand une offre est réellement créée, elle est **rayée de la liste**
— elle disparaît du flux. Donc :

> **Succès = après rechargement du flux, l'offre n'y est plus** (dans le même
> mode de filtre `available` que celui du run).

Précision sur ce « mode `available` » : le flux est une vue filtrable (toutes
les offres, ou seulement certaines selon leur disponibilité). Si on vérifiait
la disparition dans un **autre** filtre que celui utilisé pendant le run, une
offre pourrait sembler « disparue » alors qu'elle est simplement hors de
cette vue — d'où la règle : même filtre à la vérification qu'à l'extraction.

Et rien d'autre. Le message vert `[data-success]` à l'écran ? Il a déjà menti
(un gabarit caché pré-existant dans la page a été pris pour une confirmation
du serveur). Le code HTTP 200 ? Le texte « Offer created » ? De simples
indices, consignés dans les journaux, **jamais** des preuves.

La disparition est vérifiée sous **deux clés à la fois** — l'identifiant de
la ligne *et* le chemin d'URL marchande — parce qu'AKS renumérote toutes ses
lignes lors des réimports (constaté en direct : 0 identifiant sur 212 ayant
survécu 74 minutes chez K4G).

> **Analogie.** Pour savoir si un client a quitté l'hôtel, on vérifie le
> numéro de chambre **et** le nom du client : l'hôtel remélange les numéros
> de chambre pendant la nuit, donc une chambre 214 vide ne prouve pas un
> départ — le client est peut-être simplement passé en 312.

**Et si le flux est illisible au moment de vérifier ?** L'absence de preuve
n'est **pas** une preuve d'absence (règle durcie à l'audit du 2026-07-17). Si
le balayage de vérification ne peut pas prouver qu'il a **tout** lu — page qui
ne répond pas, page blanche inexpliquée, déconnexion en cours de route,
parcours interrompu avant la fin — l'offre est marquée **UNKNOWN** : « état
inconnu, à vérifier **à la main** sur AKS avant tout réessai ». La tentative
est comptée, la création **non**, et tout le run s'arrête
(`stopped: "feed_unreadable"`). Jamais un flux illisible n'est compté comme
« l'offre a disparu ».

---

## 7. « Authoritative » : seul le vrai serveur compte

Le système de production tourne sur un **VPS Debian** précis, où un Chrome
déjà ouvert est piloté à distance via **CDP** (*Chrome DevTools Protocol* :
une télécommande réseau intégrée à Chrome — « ouvre cette page », « lis cette
valeur »). Le code n'utilise qu'un **seul** point d'accès officiel
(`http://172.17.0.1:9223/json/version` — un simple relais réseau local entre
le code et le Chrome de la machine) et refuse tous les autres avant même
d'ouvrir une connexion.

L'audit et le vérificateur d'invariants détectent **où** ils s'exécutent.
Seul le vrai VPS obtient `authoritative: true` : il faut être sur Linux ET
que le fichier marqueur `/etc/aks-executor.target` existe — un fichier
installé une fois par l'administrateur (root), que personne d'autre ne peut
modifier, et dont le contenu doit être exactement le nom de la machine
(audit FC2, 2026-07-17 : avant, une simple variable d'environnement
`AKS_TARGET=vps` suffisait à se faire passer pour le VPS — c'est corrigé).
La variable `AKS_TARGET` ne sert plus qu'à forcer le sens INOFFENSIF
(`dev`/`sandbox`/`local` = « je ne suis pas le VPS », toujours sans risque).

> **Analogie.** Un thermomètre posé sur le vrai patient (le VPS) donne un
> diagnostic. Le même thermomètre posé sur un mannequin (ton portable, un
> bac à sable CI) peut afficher n'importe quoi — fièvre ou pas, ça ne dit
> **rien** du patient.

Conséquences pratiques :

- un résultat **rouge** sur ta machine locale n'est **pas** une panne de
  production — c'est l'état local attendu ;
- un résultat **vert** hors du VPS ne déverrouille **rien** ;
- il est interdit de « forcer un vert local » en bidouillant variables
  d'environnement, réseau ou code des invariants.

---

## 8. Le StepGuard : le disjoncteur

`src/step_guard.py` est un petit **disjoncteur** déterministe que traverse
chaque étape qui agit sur le navigateur ou le réseau (invariants, extraction,
soumission). Il compte les tentatives et les échecs — en pur état Python,
sans aucun raisonnement — et coupe le courant quand les limites sont
atteintes. Valeurs par défaut (chaque étape peut les ajuster — le soumetteur,
par exemple, n'autorise qu'une tentative par offre et s'arrête après 10
échecs consécutifs) :

- 2 tentatives maximum pour une même action précise (une « signature ») —
  au-delà, seule cette action est refusée, la tâche continue ;
- 2 échecs sur la même signature → **blocage total** de la tâche ;
- 3 échecs consécutifs, toutes actions confondues → blocage ;
- 5 échecs au total dans la tâche → blocage.

Point crucial : le blocage vit **dans le programme**, pas dans une
conversation. Un modèle de langage ne peut pas le « convaincre », le
reformuler, ni le contourner en changeant d'outil. Le blocage ne se lève que
lorsqu'une tâche **vraiment nouvelle** démarre (un nouveau `task_id`, attribué
par la boucle de contrôle, jamais par le modèle).

> **Analogie.** Après un court-circuit, le disjoncteur saute. On ne négocie
> pas avec un disjoncteur, et rappuyer plus fort sur l'interrupteur ne sert à
> rien : seul quelqu'un d'autorisé peut réarmer au tableau.

---

## 9. Un seul conducteur : le verrou du navigateur

Tout le projet pilote **un seul onglet** Chrome. Si deux programmes le
pilotaient en même temps — par exemple la page opérateur en pleine extraction
*et* un script lancé à la main dans un terminal — chacun casserait la
navigation de l'autre (et, côté écriture, la fenêtre de saisie de l'autre).

D'où un **verrou** (ajouté à l'audit du 2026-07-17) : toute étape qui touche
au navigateur (connexion, extraction, soumission — y compris en dry-run) le
prend avant de démarrer. Si le verrou est déjà occupé, l'étape **refuse de
démarrer** et affiche **qui** tient l'onglet — elle n'attend pas son tour,
elle ne partage jamais. Le verrou est relâché automatiquement par le système
si le programme qui le tenait meurt : pas de « verrou fantôme » à nettoyer à
la main.

> **Analogie.** Une voiture n'a qu'un volant. Le deuxième conducteur ne
> s'assoit pas sur les genoux du premier : il attend sur le parking que la
> voiture revienne.

---

## 10. La trace de tout : les journaux

Les étapes qui pilotent le navigateur (connexion, extraction, soumission)
consignent chacune de leurs actions dans un journal **JSONL** (*JSON Lines* :
un objet JSON par ligne, fichier `logs/<run_id>.jsonl`) : une boîte noire
d'avion. On n'efface jamais, on n'écrase jamais, et les secrets (cookies, mots
de passe, codes 2FA, URL de contrôle du navigateur…) sont **caviardés** avant
écriture. Le matcheur et la validation, eux, laissent leurs traces dans les
fichiers JSON du run (`candidates.json`, `skipped.json`, `approved.json`).

Les répertoires `runs/`, `logs/`, `state/` et le fichier `.env` ne sont
**jamais** committés dans git.

---

## 11. Petit lexique

- **AKS** — AllKeyShop, le comparateur de prix de clés de jeux.
- **Flux marchand** (*merchant feed*) — la liste d'offres qu'un vendeur
  soumet à AKS ; la « liste de tâches » à saisir.
- **CDP** — Chrome DevTools Protocol, la télécommande réseau de Chrome.
- **Invariants** — les conditions non négociables vérifiées avant tout.
- **Authoritative** — « exécuté sur la vraie machine de production ».
- **Fail-closed** — dans le doute, se verrouiller plutôt que continuer.
- **Candidat** — une offre du flux que le matcheur a jugée saisissable.
- **Skip** — une offre écartée, toujours avec sa raison notée.
- **Empreinte** (*fingerprint*) — l'identité exacte d'un candidat approuvé :
  `offer_id|aks_product_id|region_id|edition_id`.
- **Dry-run** — la répétition générale : retrouver chaque ligne, ouvrir la
  fenêtre de saisie et tout vérifier — sans remplir le formulaire ni cliquer
  sur « Create offer ».
- **Slug** — la partie lisible d'une URL (ex. `buy-elden-ring-cd-key-...`) ;
  chez certains marchands, elle porte l'édition et la région.
- **Mode de saisie** (`--mode`) — `safe` (défaut), `learning` ou `advanced` ;
  décide la taille du lot soumis (règle R24, voir section 5).
- **Canari** — l'unique offre réellement soumise dans les modes d'exploration
  (`learning`/`advanced`) : un plafond de sécurité, le temps de valider une
  nouveauté. Le mode `safe` n'a **pas** de canari : il soumet le lot validé
  complet.
- **UNKNOWN / `feed_unreadable`** — le flux n'a pas pu être relu entièrement
  au moment de vérifier une soumission : l'état de l'offre est inconnu, il
  faut la **vérifier à la main** sur AKS ; le run s'arrête.
- **Verrou navigateur** — l'exclusivité sur l'onglet Chrome : un seul
  programme le pilote à la fois, le second refuse de démarrer.
- **StepGuard** — le disjoncteur qui compte tentatives et échecs.
- **Run** — une exécution complète du pipeline ; ses fichiers vivent dans
  `runs/<date>_<heure>_<marchand>/`.

---

## 12. Les idées fausses classiques

1. **« Le script s'est arrêté, c'est un bug. »** Non : s'arrêter au moindre
   doute est le comportement conçu. Le bug, c'était Hermès qui continuait.
2. **« Le message vert dit que l'offre est créée. »** Non : seule la
   disparition de l'offre du flux rechargé (même mode `available`) compte.
3. **« Rouge sur mon portable = production cassée. »** Non : hors du VPS, le
   résultat est non-authoritative ; c'est l'état local normal.
4. **« J'édite `approved.json` pour ajouter une offre. »** Inutile : le
   soumetteur re-dérive l'approbation depuis la source et refusera le
   fichier. Le seul fichier édité à la main est `validation.template.json` —
   et avec la page opérateur, même lui se remplit en cochant des cases.
5. **« Le prix a changé, c'est bloquant. »** Non : le prix n'est qu'un signal
   d'aiguillage ; une fois nom + URL (+ magasin) confirmés, l'écart de prix
   ne bloque jamais.
6. **« Ce bundle a sa propre page AKS, donc c'est bon. »** Non : bundles,
   skins et logiciels sont écartés **catégoriquement**, même avec une page
   parfaite (règles R22 et associées, aucune exception).
7. **« L'IA soumet les offres. »** Jamais : l'IA construit et audite le
   moteur ; seul le script verrouillé écrit, sur validation humaine et
   déclenchement explicite.
8. **« On peut réessayer après le blocage du StepGuard. »** Non : le blocage
   est de l'état Python ; il ne se lève qu'avec une tâche réellement
   nouvelle, décidée par le contrôleur humain.
9. **« Beaucoup d'offres écartées = le matcheur est cassé. »** Non : ~2-3 %
   de rendement (constaté sur G2A, le flux le plus bruité) est normal ; le
   doute part toujours en skip, et tout skip est motivé dans `skipped.json`.
10. **« Toute soumission commence par un canari d'une offre. »** Plus depuis
    la règle R24 (2026-07-13) : en mode `safe` (le défaut), le lot validé
    part **en entier** — la validation humaine est le garde-fou. Le canari
    de 1 ne s'applique qu'aux modes `learning` et `advanced`.

---

## Pour aller plus loin

- [`../README.md`](../README.md) — vue d'ensemble, démarrage rapide, feuille de route.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — les rôles et le flux cible (la décision de conception).
- [`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) — la spécification déterministe de chaque étape (les règles R01, R22, R24…).
- [`INVARIANTS.md`](INVARIANTS.md) — les invariants navigateur/réseau non négociables.
- [`LOGIN_SPEC.md`](LOGIN_SPEC.md) — l'étape 0b (connexion / 2FA), la seule qui touche aux identifiants.
- [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md) — les schémas JSON de chaque étape et le format des journaux.
- [`SUBMITTER_SPEC.md`](SUBMITTER_SPEC.md) — la spécification détaillée du soumetteur.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — le guide du développeur.
