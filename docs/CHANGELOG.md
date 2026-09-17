# Changelog — AKS Controlled Executor

Notable changes, newest first. Dates are UTC. Complements [`AUDIT.md`](AUDIT.md)
(findings) and the roadmap in [`../README.md`](../README.md).

## 2026-09-17 — Stage 13 : le SQL de tri, généré et MESURÉ, jamais exécuté

Romain : « j'aimerais bien que tu me génères des requêtes SQL […] sur l'admin on aura un espace
où on pourra les copier-coller et nous aller les exécuter personnellement », avec des exemples
filtrant sur l'URL (`WHERE url LIKE '%-furniture-pack%' AND listId=9`). Sur sa confirmation
(« on filtre sur l'url »), `scripts/13_sort_sql.py`.

**Le script ne touche aucune base : il écrit du texte.** L'exécution reste manuelle, dans
phpMyAdmin. C'est justement pourquoi il est prudent : un `UPDATE` lancé à la main n'a ni garde
fail-closed, ni preuve de disparition, ni retour arrière. Chaque motif est donc MESURÉ sur le
feed avant d'être proposé — combien de lignes il vise, combien notre routeur enverrait sur
cette liste, combien sur une AUTRE, combien il laisse volontairement en pending, et surtout
combien sont de **vrais jeux à créer**. Une seule de ces dernières écarte le motif.

**La leçon de la première version, gardée en test.** Je minais d'abord tous les jetons d'URL
« purs » dans l'échantillon. Résultat : `%modern-warfare%` → Blacklist, plus
`%agatha-christie%`, `%marvel-tokon%`, `%familiar%`. Purs sur 10 % du feed, catastrophiques sur
100 % : ce sont des NOMS DE JEUX, pas des catégories. Les motifs ne viennent plus que du
VOCABULAIRE de routage (`forbidden region: X`, `skip category: Y`), c'est-à-dire du mot qui a
fait décider le routeur. `tests/test_sort_sql.py` verrouille précisément cette régression.

Deux modes : proposer, et **auditer un motif écrit à la main** avant de le lancer. Les treize
motifs de Romain passés au crible sur le scan du soir ne visent presque rien — le scan ne
couvre que 10 % du feed — sauf `%1-year%`, dont l'unique ligne visée est un VRAI JEU. Signal
utile : cette famille de motifs demande la passe complète avant d'être exécutée.

Garde-fous du texte produit : une seule forme de requête, vérifiée par expression régulière,
toujours bornée par `AND listId=9`, seul `listId` assigné, et le motif validé contre une liste
blanche de caractères (un motif à guillemet ou à espace est refusé, pas échappé).

## 2026-09-17 — R18 durci : seul un seau DLC SOLITAIRE décide d'un titre sans marqueur

Romain, en voyant une offre du sweep de la nuit : « Pourquoi l'executor a rentré cette offre
en DLC ? » — une clé Rockstar de **jeu de base**, « Grand Theft Auto Vice City », titre sans
le moindre marqueur, entrée en DLC(16).

**Diagnostic.** R18 décidait sur la seule PRÉSENCE d'un seau DLC dans le menu de la page, et
le code le disait explicitement : « even when a Standard bucket coexists ». Romain a d'abord
soupçonné une confusion d'étiquettes, ayant vu « Standard + DLC » dans l'admin ; le catalogue
vivant capturé par le sweep a tranché : « DLC » est l'id 16, « Standard + DLC » est l'id 518,
deux seaux distincts parmi la quarantaine contenant le mot DLC, et le détecteur ne retient que
la clé 16 ou le nom exactement égal à « DLC ». Ce n'était donc pas une confusion : la page
porte bien un vrai seau DLC, et R18 a fait ce pour quoi elle était écrite.

**Durcissement, sur son GO.** Pour un titre SANS marqueur, le seau DLC ne décide plus que s'il
est le SEUL de la page. Un vrai DLC caché garde sa page mono-seau et entre juste ; un jeu de
base dont la page offre aussi Standard repart en Standard. Les titres MARQUÉS sont inchangés
(R43). **Ceci remplace la décision « ne pas durcir » du 2026-09-11** — `AGENTS.md` porte
désormais la nouvelle règle, l'ancienne restant en note historique pour qu'un audit lisant le
git ne la restaure pas.

**Coût mesuré sur le sweep en cours** avant le changement : 6 offres entrées en DLC, dont 4
au titre marqué (correctes) et 2 décidées par R18 seule — Vice City (fausse) et un Hunt:
Showdown (probablement juste). Le durcissement ne touche que ces deux-là.

## 2026-09-17 — Un run lancé en ligne de commande est enfin visible dans la console

Romain : « On peut faire en sorte d'avoir un monitoring sur l'admin même lorsqu'on lance en
ligne de commande ? ». La moitié du chemin existait déjà : `/submit/status` lit les artefacts
d'un run sur le DISQUE, donc la console savait déjà AFFICHER n'importe quel run dont on
connaît l'identifiant. Ce qui manquait, c'est la DÉCOUVERTE : `SubmitManager` ne connaît que
les enfants qu'il a lancés lui-même, si bien qu'un sweep démarré depuis un terminal était
invisible et que le bouton « Lancer » ne le refusait même pas.

**`src/run_marker.py`** — l'orchestrateur (`scripts/10`) et la saisie manuelle (`scripts/05`)
déposent un marqueur au démarrage et le retirent en sortant. `SubmitManager.busy()` y retombe
quand il n'a rien à lui, **dans la forme que les pages affichent déjà** (`{run_id, kind}`) :
les deux consoles adoptent donc un run CLI **sans une ligne de JavaScript à changer**, et
`auto.js` le reprend par son `resumeIfActive` existant.

**La vivacité est décidée par le PID, jamais par l'âge.** Un run tué ne peut pas bloquer la
console indéfiniment, et un run long ne peut pas être pris pour un résidu — les deux cas se
sont produits le jour même : la saisie GameBoost a tourné 1 h 50, et une session SSH expirée
en a tué une autre en plein vol. Seul le propriétaire efface son marqueur, donc un run qui
sort tard n'efface pas celui qui l'a remplacé, et une écriture atomique interdit de lire un
marqueur à moitié écrit.

**`browser_lock.lock_status()`** lit le verrou **sans le prendre** — le prendre, fût-ce une
microseconde, ferait échouer fail-closed une étape qui le demanderait à cet instant. Il parse
l'étiquette déjà écrite (`<label> pid=<pid> since <stamp>`) et teste le PID, exactement ce que
le module prescrit depuis toujours à un lecteur. Exposé sous `browser` par `api/sort/runs`.

**Bénéfice au-delà de l'affichage :** un lancement depuis la console pendant un run CLI est
désormais refusé proprement (`cli_run_in_progress`) au lieu de mourir plus tard sur le verrou
du navigateur avec une erreur illisible. Le verrou reste la vraie exclusion mutuelle ; ceci
n'est que l'étiquette lisible posée par-dessus.

`tests/test_cli_run_visibility.py`, 17 tests. **Livré non déployé** : la prise d'effet exige
un redémarrage du service, impossible tant que le sweep de nuit tourne.

## 2026-09-17 (7e passe) — L'évènement `close` est DIFFÉRÉ : le retrait devient synchrone

Romain, sur `0f2c871` : « le nettoyage attend maintenant l'évènement `close`, qui est différé
dans le navigateur, contrairement au simulateur qui le déclenche immédiatement. Le standard
HTML confirme cet ordre. » Reproduit : GO → fermeture → réponse d'offset → **POST envoyé avant
le nettoyage**, au ✕ comme à Échap.

Il a raison, et mon simulateur mentait : il émettait `close` **synchronement**, ce qui cachait
exactement le défaut. Les étapes de fermeture d'un `<dialog>` METTENT EN FILE cet évènement,
donc une continuation en attente reprend la main entre le geste et le gestionnaire.

**Correction :** chaque chemin de fermeture que NOUS pilotons retire la fenêtre lui-même,
d'abord, avant d'appeler `close()`. `cancel` (Échap) est dispatché avec l'évènement clavier,
donc synchrone : c'est le crochet de ce chemin. `close` ne sert plus que de filet pour les fins
que nous ne pilotons pas — et il ne retire que si le dialogue est **encore fermé**, sinon un
évènement en file invaliderait la fenêtre rouverte entre-temps.

**Le simulateur a été corrigé avant le code** : `close()` met l'évènement en file via
`setImmediate` et rend une promesse, `pressEscape()` émet `cancel` synchronement puis ferme.
Sans cela le scénario de Romain restait invisible. C'est la deuxième fois aujourd'hui que le
harnais lui-même était le maillon faible ; un bouchon qui simplifie le navigateur cache des
défauts réels.

Deux scénarios de plus (15 au total), tous deux morts sous mutation : le ✕ pendant la lecture
d'offset ne laisse plus partir le POST, et l'évènement différé d'une fenêtre ne retire pas la
suivante. Un drapeau d'idempotence ajouté en cours de route a été **retiré** : aucun test ne
le tuait, la garde sur l'état du dialogue suffit, et je préfère moins d'état non testé.

## 2026-09-17 (6e passe) — Échap fermait la fenêtre sans rien nettoyer

Romain, sur `26d067e` : « seuls le bouton ✕ et le clic extérieur appellent `closeOffers`. La
fermeture native du `<dialog>` ne retire donc pas la génération et n'arrête pas le suivi. En
simulant cette fermeture pendant la lecture d'offset, le POST part encore après fermeture. »

Exact, et c'est une leçon de conception : le nettoyage était accroché aux **déclencheurs** au
lieu de l'**évènement**. Un `<dialog>` se ferme aussi sur Échap, nativement, sans passer par
aucun de nos gestionnaires — la génération restait vivante, le sondage tournait, et une action
lancée depuis cette fenêtre continuait comme si de rien n'était.

**Correction :** le nettoyage est accroché à l'évènement `close` du dialogue lui-même.
`close` est émis pour TOUTES les fins — le ✕, le clic extérieur, Échap (qui émet `cancel` puis
`close`), et tout `close()` appelé par le script — donc un seul écouteur les couvre, sans le
double déclenchement qu'aurait provoqué l'écoute simultanée de `cancel`. Les deux chemins
explicites se contentent désormais de DEMANDER la fermeture ; c'est l'écouteur qui travaille.

Le bouchon de test a dû apprendre la différence : `close()` émet maintenant l'évènement, et
`pressEscape()` rejoue la séquence native `cancel` puis `close`. Sans cela aucun test ne
pouvait distinguer les deux chemins — c'est le simulateur qui manquait, pas l'idée.

Deux scénarios de plus, tous deux morts sous mutation (retour au câblage sur les boutons) :
Échap pendant la lecture d'offset ne laisse plus partir le POST, et Échap pendant le suivi
arrête bien le sondage. Le harnais passe à 13 scénarios.

## 2026-09-17 (5e passe) — Une génération PAR OUVERTURE de fenêtre, erreurs comprises

Romain a audité `fdfcd10` et repris le garde en défaut sur deux cas, tous deux reproduits :

**1. `[P2]` Changer de LISTE dans le même scan contournait le garde.** GO sur la liste 8 →
fermeture → ouverture de la liste 16 → réponse tardive : le résultat de la 8 s'affichait dans
la 16. Le garde comparait le SCAN (`MODAL_RUN_ID !== runId`) ; or changer de liste garde le
même scan, donc il ne voyait rien.

**2. `[P2]` Une réponse d'ERREUR contournait entièrement le garde.** « Le catch intervient
avant la vérification » : un refus tardif de la liste 8 s'affichait dans la 16 **et réactivait
ses boutons**, en plein lancement de celle-ci.

**Correction : l'identité n'est plus le plan, c'est l'OUVERTURE.** `MODAL_SEQ` est incrémenté
à chaque `openList` ET à chaque fermeture ; `runAction` le capture au clic et le vérifie après
**chacune de ses trois attentes** — la lecture de l'offset, le chemin de succès du POST, et
son chemin d'erreur. Quand l'ouverture est périmée, l'action ne touche ni le panneau ni les
boutons : elle le dit sur la ligne de statut de la PAGE, qui n'appartient à aucune fenêtre.

**Ce que la mutation a appris.** Mon premier jeu de tests pour ce cas était vert **pour la
mauvaise raison** : je l'avais écrit sur le contexte qui charge aussi le plan B, si bien que
rouvrir une liste changeait le SCAN — l'ancien garde suffisait donc, et le mutant passait.
Le scénario est réécrit sur un contexte « plan A seul » où seule l'ouverture change. Sans
cette vérification par mutation, j'aurais livré un test inutile en croyant le contraire.

| garde retiré | test qui meurt |
|---|---|
| `gone()` sur le chemin de succès (retour au garde par scan) | changer de LISTE dans le même scan |
| `gone()` dans le `catch` | un REFUS tardif ne peint pas dans une autre fenêtre |
| `gone()` après la lecture d'offset | la lecture d'offset qui revient trop tard |

Le harnais passe à 11 scénarios.

## 2026-09-17 — Le contrôle du miroir `app.js` tourne enfin hors CI

Conséquence directe de l'arrivée de node : `tests/js/candidate_contract_check.js`, qui compare
le bloc de contrat candidat recopié dans `app.js` à `src/candidate_contract.py` sur 25 cas
partagés, ne s'exécutait **que** dans la CI, après un push ; côté Python on se contentait de
vérifier que le fichier existait, « node étant absent du VPS ». Ce n'est plus vrai. Le runner
est désormais EXÉCUTÉ depuis `tests/test_candidate_contract.py` (skip propre sans node), donc
une dérive du portage échoue sur la machine de développement et sur le VPS, pas seulement chez
GitHub. Vérifié en injectant une dérive dans le bloc miroir : le runner sort en erreur et le
test Python échoue. Le commentaire de `ci.yml` qui affirmait le contraire est corrigé.

## 2026-09-17 (4e passe) — Le lancement gardé lui aussi, les deux boucles voisines, et un faux vert

Premier audit de Romain **appuyé sur le harnais node livré le matin même**. Deux points, tous
deux réels, plus la correction des deux boucles de sondage voisines qu'il avait demandée.

**1. `[P2]` Une réponse de LANCEMENT tardive peignait dans la fenêtre d'un autre plan.** Son
repro : GO sur A → fermeture de la fenêtre → ouverture de B → la réponse du POST de A arrive →
`startPoll(A)` redémarrait et affichait « terminé (exit 0) » dans la fenêtre de B. Le jeton de
génération protège les requêtes de SUIVI ; il ne peut rien pour le lancement qui les précède.
**Correction :** le panneau appartient à la fenêtre OUVERTE — si elle a été fermée ou rouverte
sur un autre plan pendant l'envoi, l'action ne peint pas dans un panneau étranger et ne démarre
aucun suivi ; elle le dit sur la ligne de statut de la PAGE, qui n'appartient à aucune fenêtre.
L'action elle-même est partie et tourne côté serveur, ce que le message précise.

**2. `[P2]` Le test « sans plan ouvert » était un FAUX VERT.** Il n'affirmait que l'absence de
POST sans libérer la lecture d'offset qui le précède : sans le garde, le POST n'arrivait
simplement jamais dans la fenêtre du test. Romain l'a prouvé en supprimant le garde dans une
copie — les six scénarios restaient verts. Le test compte désormais **toutes** les requêtes
émises après le clic et exige la liste vide.

**3. Les deux boucles voisines.** `pollScan` relisait le global mutable `SCAN_RUN` dans son
tick (un second scan redirigeait le sondage du premier) et effaçait `SCAN_POLL` après son
`await` : run gelé en paramètre + génération `SCAN_SEQ`. `startPolling` d'`auto.js` reçoit la
même génération, avec deux vérifications puisque son tick attend deux fois, et `endSweepUi`
retire la génération — sans quoi un tick d'un sweep terminé pouvait déclarer fini un sweep
SUIVANT, effacer l'intervalle vivant et réactiver le GO pendant que l'autre écrit sur AKS.

**Vérification par MUTATION, désormais possible grâce à node.** Chaque nouveau garde a été
retiré d'une copie, et le test correspondant meurt :

| garde retiré | test qui échoue |
|---|---|
| `if (MODAL_RUN_ID !== runId)` avant le suivi | « une réponse de lancement tardive ne peint pas dans une autre fenêtre » |
| `if (!runId) return;` | « sans plan ouvert, un GO n'émet AUCUNE requête » |
| `if (seq !== SCAN_SEQ) return;` | « la boucle du scan frais suit SON scan et retire sa génération » |

Le harnais passe à 8 scénarios. Le stub sert maintenant `json()` ET `text()` (auto.js lit le
texte puis parse), et la confirmation est configurable.

**Réserve honnête sur `auto.js`.** Son garde est correct mais je n'ai pas su atteindre le
scénario par le chemin réel de l'interface : il exige deux sondages qui se chevauchent, or le
bouton de lancement est désactivé pendant un sweep. C'est de la défense en profondeur épinglée
structurellement, **sans repro vivant**, et `docs/AUDIT.md` le dit. `pollScan`, lui, est
exercé en vrai.

## 2026-09-17 — Le JavaScript de la console est enfin EXÉCUTÉ par ses tests (node approuvé)

Romain : « nos tests sont avec un simulateur formel ? ». Réponse honnête : non, et pire — pour
la console il n'y avait **aucune exécution**. Comptage fait le jour même sur les 2 080
méthodes de test : **2 016 exécutent vraiment le code, 64 ne vérifient qu'une orthographe, et
52 de ces 64 portent sur le front-end de la console**. Zéro test d'orthographe dans le matcher,
le submitter ou les règles marchandes. Le défaut était donc concentré exactement là où Romain
a trouvé ses deux bugs : ses repros EXÉCUTAIENT un scénario, mes tests vérifiaient une écriture.

Il a levé la contrainte d'`AGENTS.md` : « Installe node pour les tests JS ». **node est
désormais une dépendance de TEST** (paquet Debian `nodejs` 20.19.2, bibliothèque standard
seule — aucun `npm install`, aucun `package.json`, aucun `node_modules`, rien ajouté au
runtime ni au chemin d'écriture du VPS). Inscrit dans `AGENTS.md` pour qu'un audit ne le
relise pas comme une dérive, et le VPS n'ayant pas node, le test s'y met en SKIP propre.

`tests/js/` : un DOM bouchonné (`dom_stub.mjs`), un chargeur qui injecte les globales dans le
vrai fichier livré (`load_console.mjs`), et un `fetch` dont **les réponses sont libérées à la
main** — c'est ce qui permet d'entrelacer deux chargements de plan exactement comme dans le
repro de Romain. Le harnais pilote le vrai chemin d'interface (sélecteur de scan, bouton de
carte, champ GO, bouton canary) et n'affirme que sur **les requêtes qui sortent de la page**.

Six scénarios, et surtout leur pouvoir de discrimination, mesuré :

| version de `sort.js` | résultat |
|---|---|
| `507bdf8~1` (avant toute correction) | 3 échecs |
| `507bdf8` (gel au clic, 1re passe) | 3 échecs — **le repro de Romain reproduit** : le déplacement part sur `scan-B` alors que l'opérateur regarde les offres de `scan-A` |
| HEAD sans le jeton `POLL_SEQ` | le test du tick périmé échoue |
| HEAD | tout passe |

`tests/test_console_js_simulation.py` lance le harnais depuis la suite Python, se met en SKIP
si node est absent, et contient un **test de mutation** qui rejoue le harnais contre `507bdf8`
pour vérifier qu'il vire bien au ROUGE : un harnais toujours vert ne prouve rien.

**Ce que ce n'est PAS.** Pas une méthode formelle : ni vérificateur de modèle, ni preuve, ni
exploration par propriétés (l'inventaire de l'outillage confirme qu'il n'y a rien de tel dans
le dépôt, ni même d'analyseur statique). C'est une simulation des scénarios que nous avons
écrits ; elle ne dit rien de ceux auxquels nous n'avons pas pensé. Les tests structurels sont
conservés — ils coûtent peu et cassent si la forme du correctif est défaite — mais **en cas de
désaccord, la simulation fait autorité**, et c'est écrit dans leur en-tête.

## 2026-09-17 (2e passe) — Le gel au clic arrivait trop tard : l'identité suit désormais les cartes

Romain a audité `507bdf8` et l'a pris en défaut, repro JavaScript à l'appui : **geler au clic
ne suffisait pas**. Son scénario : le chargement de B démarre pendant que A est affiché ;
l'opérateur ouvre les offres de A ; B termine son chargement, la fenêtre reste sur A ; le GO
part sur **B**, avec l'empreinte de B. La modale n'étant jamais resynchronisée, l'opérateur
approuve en regardant les offres de A une action qui s'exécute sur B.

**Correction :** l'identité n'est plus prise au clic mais **à la peinture des cartes**, et elle
voyage avec elles — `render()` → `card(id, g, runId, planDigest)` → `openList(…)` →
`MODAL_RUN_ID` / `MODAL_DIGEST`. Tout ce que la modale montre et déclenche parle du même plan :
les commandes CLI copiables, l'offset du journal, le POST, le suivi. Fermer la modale libère
l'identité. Le repli `runId || PLAN_RUN_ID` du suivi est supprimé : sans plan ouvert,
`runAction` refuse avant d'appeler `startPoll`, et un repli ne ferait que suivre discrètement
un autre run. Geler l'empreinte pour la vie d'une modale est sûr parce que `src/sort_move.py`
est pur et n'écrit rien : un déplacement ne réécrit pas `sort_plan.json`, donc la séquence
dry-run → canary → batch d'une même modale garde une empreinte valable, et un 409 ne survient
que si le scan a été refait — précisément le cas où il DOIT survenir.

`tests/test_sort_audit_2026_09_17.py` passe à 21 tests : les 21 échouent avant la 1re passe,
et **14 échouent encore sur `507bdf8`**.

**Second point de l'audit — un drapeau inexistant dans la doc.** La note ajoutée le matin
conseillait `--prove-gone-scan` pour revenir à la marche complète sur le chemin MANUEL. Ce
drapeau n'existe que dans `scripts/10_data_entry_auto.py` ; `05_submit` ne le connaît pas. Sur
le chemin manuel il suffit de **retirer** `--prove-gone-by-search`. Corrigé dans
`docs/HANDOFF.md`, et un test vérifie désormais l'existence réelle des drapeaux cités.

**Revue adversariale de la même classe ailleurs (lecture seule, 25 agents).** Sept pistes
examinées sur les autres fichiers de la console, le serveur admin, les verrous et le
garde-fou ; **aucune n'a survécu à la réfutation**. Deux enseignements honnêtes : (1) la revue
avait bien retrouvé le défaut de Romain toute seule, mais ses réfuteurs l'ont écarté à tort —
le seuil « dans le doute, on réfute » est trop sévère pour un défaut réel ; (2) une piste
écartée mérite l'arbitrage de Romain, décrite dans `docs/AUDIT.md` : le tick de `startPoll`
lit le global `POLL` APRÈS son `await`, donc un tick resté en vol depuis un run terminé peut
tuer la boucle du run suivant et afficher la conclusion du précédent. Aucune écriture fautive,
mais un affichage qui ment. **Corrigé le jour même sur GO de Romain** (« fais le fix du
polling aussi ») : un jeton de génération `POLL_SEQ`, même patron que `LOAD_SEQ`. `stopPoll`
retire la génération courante (un `clearInterval` ne peut rien contre une requête déjà en vol),
`startPoll` prend le jeton juste après, et le tick le vérifie dès son retour d'`await`, avant
toute écriture. Quatre tests l'épinglent, dont l'ordre des instructions.

## 2026-09-17 — Audit de Romain : le GO du tri gelé au clic, et la preuve lente du chemin manuel

**1. Priorité haute — le GO du tri pouvait ENCORE viser un autre scan.** Le correctif du 16/09
avait fermé la course au REPEINT et ajouté l'empreinte côté serveur ; Romain a trouvé le trou
restant sur le chemin d'écriture : « l'action attend une réponse réseau avant de relire le scan
et son empreinte. Si le chargement d'un autre plan termine pendant cette attente : GO cliqué
sur A ; requête de déplacement envoyée pour B, avec l'empreinte valide de B. » `runAction`
lisait `PLAN_RUN_ID` / `PLAN.plan_digest` à TROIS moments séparés par deux `await`, et le garde
serveur ne peut rien voir : l'empreinte envoyée est bien l'empreinte COURANTE de B, donc le
déplacement passe — sur un plan que l'opérateur n'a jamais examiné.
**Correction :** l'identité du plan approuvé est GELÉE au clic, avant tout `await`
(`const runId` / `const planDigest`) ; la lecture de l'offset, le POST et le suivi lisent ces
constantes. `startPoll(runId)` prend le scan en paramètre (sinon il tailait le journal d'un
autre run). Ajouts : refus quand aucun plan n'est affiché, et avertissement visible dans le
panneau quand l'écran a changé pendant l'envoi (l'action reste celle qui a été approuvée, mais
les cartes à l'écran sont celles d'un autre scan). `tests/test_sort_audit_2026_09_17.py` — 10
tests, **tous les 10 échouent sur la version d'avant** (vérifié). L'assertion du 16/09 qui
exigeait l'ancienne écriture est mise à jour, même intention, garantie plus forte.
*Réserve :* Romain demandait une simulation des réponses réseau retardées ; elle exige
d'exécuter le JS et aucun moteur n'est installé (ni node/deno/quickjs, ni moteur Python), et
AGENTS.md interdit d'ajouter une dépendance sans son accord. Les assertions sont donc
STRUCTURELLES et le disent.

**2. Le chemin manuel payait la preuve lente — `--prove-gone-by-search` documenté
(`docs/HANDOFF.md`).** Romain : « Pourquoi on relit tout le feed alors que je ne purge plus les
offres ? » Réponse : rien à voir avec une purge. Deux formes de preuve existent depuis le GO du
2026-09-10 ; le sweep de nuit utilise la recherche filtrée, mais la ligne MANUELLE par marchand
était restée sur la marche complète du feed après CHAQUE création. Mesuré en production sur
GameBoost (12 pages / 1080 lignes) : **~85 s de re-marche par offre, soit 123 s par offre et
6 h 45 pour 198**. Avec le drapeau : **40 s par offre**, zéro relecture de page entre deux
écritures, ~2 h pour le lot. Les lignes WRITE de HANDOFF le portent désormais, avec la mesure.

**3. Reprise après arrêt opérateur — dé-approuver, jamais éditer `approved.json`.** Le run
GameBoost a été coupé proprement (`run_stopped reason=operator_stop`, dernière offre terminée
et prouvée avant l'arrêt, 7/7 créées, zéro refus). Rejouer le lot tel quel aurait commencé par
7 échecs consécutifs contre un seuil de 10 : marge de 3. Et `approved.json` ne se filtre PAS à
la main — `verify_approved_against_source` le re-dérive de `candidates.json` + `validation.json`
et refuse tout écart. La marche à suivre, appliquée : passer `approve: false` sur les offres
déjà créées dans `validation.json`, puis `04_validate.py check` régénère le lot (198 → 191,
aucune des 7 dedans). Complète la « LIMITE TROUVÉE » du 16/09 : un matching frais reste la
solution quand le feed a bougé, la dé-approbation suffit quand seule NOTRE passe l'a modifié.

## 2026-09-16 — Saisies réelles du jour : GameBoost 15/15, Wyrel en cours, et une limite du rejeu

**GameBoost (157)** — 1er matching réel (992 lignes, 13 pages) → 207 candidats ; **1re passe
de 15 offres : 15/15 créées**, zéro échec, chacune prouvée par la disparition du feed (un DLC
Hunt Showdown, un Sekiro GOTY sur page Xbox One, un MSFS 2024 Premium en Play Anywhere
multi-cibles, et des clés Steam Europe). Allowlisté safe-auto dans la foulée.

**LIMITE TROUVÉE — ne jamais rejouer un lot validé après une passe partielle.** La relance du
même `approved.json` pour « les 192 restantes » a créé **ZÉRO** offre : le lot repart du début,
donc ses dix premières lignes étaient les 15 déjà créées, chacune revenant « offer not in
current feed (by id and by URL) » — dix refus consécutifs, et le garde anti-emballement
(`ten_consecutive_failures`) a arrêté le run. Le garde a bien fonctionné ; le lot, lui, était
périmé. **La bonne marche à suivre est un matching frais** : refait le jour même (feed passé
de 992 à 1032 lignes) → **198 candidats, les 15 déjà saisies absentes du lot**, vérifié.

**Wyrel (162)** — **1re saisie réelle : 15 / 15 créées, zéro refus** (2026-09-17, serveur
secondaire), chacune prouvée par la disparition du feed, arrêt propre sur `limit_reached`. La
grammaire `[R53]` tient en écriture réelle. Son feed fait 59 pages, donc la
preuve par relecture complète coûte cher — 15 offres y prennent des heures là où GameBoost
(13 pages) en prenait cinquante minutes. Piste pour plus tard : la preuve par recherche ciblée
(`--prove-gone-by-search`), déjà utilisée par le sweep de nuit.

## 2026-09-16 — Audit de Romain : trois défauts de la console et du tri

**1. Priorité haute — le GO pouvait viser un autre scan que celui affiché.** En sélectionnant
deux scans rapidement, une réponse lente du premier repeignait l'écran par-dessus le second,
alors que « Déplacer » postait sur l'identifiant du second : « un canary peut alors déplacer
une offre d'un lot que tu n'as pas examiné ». Corrigé sur trois niveaux, comme Romain le
prescrivait : un JETON DE SÉQUENCE fait ignorer toute réponse périmée (`LOAD_SEQ`) ; toutes
les actions lisent désormais le run dont le plan est RÉELLEMENT à l'écran (`PLAN_RUN_ID`), plus
jamais la valeur courante du sélecteur ; et un déplacement réel doit porter l'EMPREINTE du plan
approuvé (`plan_digest`, rendue par le GET `…/sort`, digest des octets du fichier) que le
serveur vérifie — absente → 400 `plan_digest_required`, différente → 409 `plan_changed`. Un
dry-run n'en a pas besoin.

**2. Priorité moyenne — le scan de tri perdait les règles marchandes.** Le scan tous-magasins
lit le feed SANS filtre de magasin, donc chaque ligne est étiquetée « all-stores » et
`merchant_config()` ne trouvait rien alors que le `store_id` était connu. Reproduction de
Romain : une ligne MMOGA « Example Game RU Key » est routée Blacklist sous son vrai marchand et
devenait un candidat création NON routé dans le scan ; idem BR et CN. `src/merchants/registry.py`
publie maintenant `MERCHANT_STORE_IDS` et `merchant_for_store()` (cohérence avec
`AUTO_MERCHANTS` vérifiée par test), et `build_sort_plan` restaure l'identité canonique avant
classification. Vérifié : les 3 lignes passent de « 3 candidats, 0 routées » à « 0 candidat,
3 routées vers Blacklist ». Un magasin inconnu garde l'étiquette du feed et le comportement
générique — jamais un marchand deviné.

**3. Priorité moyenne — le nouveau sweep acceptait « false » comme activation.**
`all_allowlisted` était lu selon la valeur de vérité Python, donc la CHAÎNE `"false"` lançait
les 14 marchands. Même exigence que `consoles` : un vrai booléen JSON, sinon 400
`bad_all_allowlisted`, vérifié AVANT de remplir les cibles.

`tests/test_sort_audit_2026_09_16.py` (14 tests) plus 5 tests de comportement dans
`test_admin_app.py`. 2 053 tests, tous verts.

## 2026-09-16 — R53 : fichier marchand Wyrel (162) + repli des accents dans les scans catégoriels

Romain : « Skip gamesplanet FR, fais wyrel d'abord », puis « fix [le trou générique des
accents] ».

**Wyrel `[R53]`** — 60 pages de feed, le marchand le plus volumineux et le plus lisible de
l'audit. Son titre est un GABARIT À FENTES qui se lit intégralement depuis la fin, sans
résidu sur 100/100 lignes, et son URL répète les mêmes faits en identifiants numériques.
Cinq sous-règles, dont trois écrites par les contradicteurs :
* `[R53d]` **les deux sources de région doivent concorder** — bijection stricte titre ↔
  `region=` sur le corpus, zéro désaccord ; un désaccord prouvé est un skip. Aucun autre
  marchand ne nous offre une seconde source indépendante ;
* `[R53b]` **le filtre non-jeu exige trois signaux d'accord** (fente « Other », pas de groupe
  `(<TAG>)`, `marketplace_id` hors {2, 8}) : les trois tiennent sur 48/48 non-jeux et aucun
  sur les 52 vraies clés. Une porte à un seul signal traiterait « (PS5) … Other » de « pas un
  jeu » — un mensonge sur la ligne ; une contradiction a donc son propre skip, et le motif
  nomme le PRODUIT pour que le routage de listes marche ;
* `[R53e]` **le vocabulaire de la fente plateforme est OUVERT**, un mot inconnu est refusé par
  son nom : une page sur soixante ne peut pas énumérer les appareils d'un marchand, et un
  « PS5 » non listé serait avalé par la fente ÉDITION. Le départage utilise la seconde source,
  `edition_id`, elle aussi en bijection.
Verdicts : 47 passent, 48 non-jeux nommés, 5 éditions sans compartiment. Hors liste blanche.

**Repli des accents** — trouvé par un contradicteur sur GamesPlanet FR : toutes nos
exclusions catégorielles sont en ASCII anglais alors que les normaliseurs remplaçaient toute
lettre non-ASCII par une ESPACE, donc « CRÉDITS » devenait « CR » + « DITS » et l'entrée
`CREDITS` déjà présente ne matchait jamais. `fold_accents` (NFKD, marques combinantes
retirées) tourne désormais dans chacun de ces scans. Le repli ne peut que faire matcher un mot
du vocabulaire sur un texte qui le SIGNIFIE, il n'invente jamais de mot. **Rayon de souffle
mesuré avant livraison : sur les 397 lignes réelles portant un caractère non-ASCII, ZÉRO
verdict changé.** C'est un filet, pas un changement de comportement.

2 034 tests, tous verts.

## 2026-09-16 — GameBoost (157) rejoint la liste blanche safe-auto

Romain : « Ajoute Gameboost a la whiteliste ». `AUTO_MERCHANTS` passe de 13 à **14 marchands**.

Décidé après son **premier matching réel** : 992 offres extraites sur 13 pages (couverture
prouvée en 2 passes), **207 candidats** — Steam 131, Xbox Series 40, Xbox One 14, EA 11,
Ubisoft 9, Battle.net 1, PS4 1 — dont 22 multi-cibles Xbox Play Anywhere, et 49 DLC. Contrôles
qualité avant validation : **zéro PUBLISHER** (`[R51]` tient), zéro région implicite, zéro
doublon d'empreinte, aucune offre au-delà du plafond de 3 cibles. Puis une première passe de
saisie de 15 offres.

Son fichier (`[R47]`, 2026-09-15) refuse toute ligne sans mot de région — 181 lignes du feed
s'y arrêtent — ainsi que les cartes cadeaux (218) et les consoles sans génération déclarée
(117). C'est ce qui rend la saisie sans validation acceptable ici.

**Difmark (167) reste le seul marchand explicitement hors liste.** README (liste des 14 et
commande du scan de nuit), `docs/MERCHANTS.md`, `src/merchants/gameboost.py` et les tests
d'allowlist sont à jour dans le même commit ; la commande `--all-allowlisted` n'a PAS besoin
d'être retouchée, c'est tout son intérêt.

## 2026-09-16 — Console : bouton « sweep de nuit » (tous les marchands whitelistés)

Romain : « Dans l'onglet Data entry auto, je voudrais un bouton pour lancer un sweep sur tout
les marchands whitelisted (sauf si ce sweep est deja en cours) ».

Bouton **« Lancer le sweep de nuit (tous les marchands) »** dans la carte de lancement de
l'onglet Data entry auto, sous le lancement ciblé, séparé par un filet pour qu'on ne clique
pas l'un en croyant l'autre. Il affiche la liste blanche du jour (nom et compte) et n'exige
que le **GO tapé**, comme tout chemin d'écriture réelle.

Deux propriétés portent la fonctionnalité, toutes deux côté SERVEUR :
* la cible est **lue dans la liste blanche** (`all_allowlisted: true` → `auto_allowed_list()`
  dans `_post_data_entry_auto`) : le bouton n'envoie jamais de liste de marchands, donc il ne
  peut pas dériver le jour où un marchand est ajouté — même source que `--all-allowlisted`
  côté CLI. Une requête qui mélangerait `targets` est refusée (`targets_conflict`), une liste
  blanche vide échoue fermé (`allowlist_empty`) ;
* **« sauf si ce sweep est déjà en cours »** est tenu par le garde un-run-à-la-fois du manager
  (`_ensure_free` → 409 `submit_in_progress`), quel que soit le genre du run en cours ; la page
  grise le bouton en plus, mais ce n'est pas elle qui garantit la règle.

`continue_on_halt` est activé pour ce bouton : l'arrêt fail-closed d'un marchand ne doit pas
terminer la nuit. `tests/test_auto_night_sweep_button.py` (15 tests) épingle le bouton, la
provenance des cibles, le refus du mélange, le garde d'unicité et le GO. 2 006 tests.

## 2026-09-16 — `--all-allowlisted` : le scan de nuit lit sa cible dans la liste blanche

Romain : « Donne moi la commande a jour pour lancer tout les marchands whitelist (scan de
nuit) et maintien la dans le readme a chaque whitelist de nouveaux marchands ».

Une liste `--targets "MMOGA:12,Kinguin:58,…"` écrite à la main dérive dès qu'un marchand
rejoint la liste blanche — le sweep du 15/09 a tourné sur **7 marchands alors que 11 étaient
allowlistés**. `scripts/10_data_entry_auto.py --all-allowlisted` lit désormais ses cibles dans
`AUTO_MERCHANTS` : la commande documentée n'a plus jamais à être réécrite, c'est ce qui la
maintient à jour. Le drapeau refuse d'être combiné à `--targets` / `--merchant`.

La commande vit dans le **README**, section « Night sweep — every allowlisted merchant »,
avec l'aperçu read-only, la version réelle (WRITE, sur GO), l'explication de `--max-pages 10`
et `--continue-on-halt`, et l'état de la liste blanche au 16/09 (13 marchands, dont 4 jamais
balayés en réel : Eneba, CJS-CDKeys, Allyouplay, GameSeal). `docs/HANDOFF.md` renvoie à la
même commande. `tests/test_sweep_all_allowlisted.py` (6 tests) épingle le drapeau ET le fait
que le README ne re-liste pas les marchands à la main.

## 2026-09-16 — R52 : les clés de jeu Microsoft ne sont plus pré-exclues

Audit de Romain, le jour même de `[R50]` : « Les régions Microsoft sont ajoutées, mais deux
formulations de clés restent bloquées avant leur résolution … Cause : ces expressions figurent
encore dans CATEGORY_SKIP. Correction : retirer ces exclusions générales pour les clés de jeux,
en conservant les refus des cartes cadeaux, abonnements et recharges. »

`MICROSOFT KEY` et `MICROSOFT STORE` quittent `CATEGORY_SKIP`. Elles y étaient pour un motif
que `[R50]` a supprimé le matin même — §4.5 disait « MICROSOFT platform has no region mapping
→ fail-closed » (`[R17]`), et la famille Windows 10 est maintenant mappée (Global 246, EU 244,
US 245, UK 249). Mesuré sur tous les runs sauvegardés : **164 lignes (34 distinctes)** étaient
bloquées là, très majoritairement de vraies clés de jeu — Call of Duty ×7, GTA V Enhanced,
Skyrim Anniversary, Fallout 76, Rise of the Tomb Raider, Wasteland 3, Minecraft Dungeons II.

**Ce qui devait rester refusé l'est**, par deux entrées explicites qui remplacent les deux
retirées : `MICROSOFT STORE ACCOUNT` / `MICROSOFT ACCOUNT` (le mot ACCOUNT seul n'est pas un
marqueur sur le chemin PC) et `MINECOINS` (les bornes de mot empêchent `COINS` de matcher le
mot composé). Vérifié **ligne à ligne sur les 34** : 29 passent, 2 bundles, 2 Minecoins, 1
compte — aucun non-jeu ne s'échappe.

`[R17]` est marqué RETIRÉ dans `EXECUTOR_RULES.md` §4.5. `tests/test_microsoft_category_skip.py`
(9 tests) ; les 2 tests G2A qui épinglaient l'ancienne exclusion sont réécrits. 1 985 tests.

## 2026-09-16 — Electronicfirst et GamersOutlet passent en liste blanche safe-auto

Romain : « On va whitelist Eletronicfirst et Gamersoutlet ». Les deux rejoignent
`AUTO_MERCHANTS` — la liste passe de 11 à 13 marchands.

**Electronicfirst (70) est dé-parqué le jour même de son parking** : la cause du parking — 2
lignes entrées PUBLISHER au lieu de STEAM sur un titre nu — a été fermée de façon GÉNÉRIQUE
par `[R51]` quelques heures plus tard. Vérifié : `Of Orcs and Men` et `RoboCop: Rogue City -
Collection` sortent désormais en skip « (R51) », tandis que les lignes correctes du lot
(`Ink. PC Steam CD Key`…) restent des candidats. Le diagnostic reste dans le module comme
HISTORIQUE : c'est lui qui a produit `[R51]`.

**GamersOutlet (31)** rejoint la liste avec sa petite file (~19 lignes, ~2 saisissables) ;
le volume viendra avec le temps.

**GameBoost (157) reste hors liste** : son fichier existe pour les runs supervisés.

Docs tenues à jour dans le même commit (règle de Romain) : `README.md` (tableau des
marchands + un bloc neuf sur `[R50]` / `[R51]`), `docs/MERCHANTS.md` (tableau d'état et les
deux sections), `src/merchants/registry.py`, `src/admin/auto_merchants.py`, et les modules des
deux marchands. Les 3 tests qui épinglaient « hors liste blanche » sont réécrits, et
`test_merchants_registry_expectations` couvre les deux nouveaux modules.

## 2026-09-16 — R51 : la décision PUBLISHER exige la page du MARCHAND (sécurité par défaut)

Romain, après avoir vérifié la saisie Electronicfirst puis reproduit le cas sur Gamivo :
« avant de decider si publisher ou non on doit ouvrir la page marchant pour verifier la region
et l edition, si on arrive pas a ouvrir la page marchant on skip l offre … on devrait ajouter
cette securite par defaut pour tous les marchants ». Go donné le même jour.

**Le trou.** `[R27]` refuse un titre sans jeton de plateforme SAUF si la page AKS confirme
« Direct Publisher ». Or cette ligne décrit **le jeu** — le jeu existe aussi en version
éditeur — et ne dit rien de ce que vend CE marchand. Vérifié sur le code vivant :
`resident-evil-raccoon-city-edition` chez Gamivo, une clé Steam mondiale d'après Romain,
ressortait en PUBLISHER GLOBAL(1).

**La règle.** Une ligne dont la plateforme n'est NI dans le titre NI dans l'URL est refusée,
sauf si le marchand DÉCLARE qu'il lit sa propre page
(`MerchantConfig.publisher_from_merchant_page`, **défaut False** — la sécurité est active pour
tous les marchands, avec ou sans fichier de config). Aucun marchand ne le déclare aujourd'hui :
toutes les pages produit sondées le 16/09 sont Cloudflare-403 (Gamivo, Electronicfirst,
GamersOutlet, Kinguin, Driffle) ou refusées (G2A) ; celles qui répondent 200 (Eneba, GameSeal,
Instant Gaming, K4G, MMOGA) résolvent déjà la plateforme en amont ou n'ont pas de lecteur.

**Coût mesuré avant changement** : 13 candidats distincts sur TOUS les runs sauvegardés —
MMOGA 5, Gamivo 6, Electronicfirst 2 — contre 2 360 lignes déjà refusées par `[R27]`. Une
partie des 13 sont de vraies clés éditeur (`Minecraft - Java & Bedrock Edition`, `Fallout 76`,
MMOGA, page à 200) : elles redeviendront saisissables le jour où un lecteur de page marchand
existera, en basculant le drapeau avec le lecteur.

Inchangé : jeton de plateforme explicite, page Steam-only (toujours le skip `[R27]`, libellé
distinct), skip `[R20]` « no official platforms », chemin logiciel `[R31]`. La décision revue
d'`AGENTS.md` est mise à jour sur place. `tests/test_publisher_page_gate.py` (11 tests) ; les
4 tests qui figeaient l'ancien défaut sont réécrits, dont 3 sous l'opt-in pour que le
comportement `[R20]` reste épinglé. 1 976 tests, tous verts.

## 2026-09-16 — Electronicfirst PARQUÉ : plateforme entrée PUBLISHER au lieu de STEAM

Romain, après vérification de la saisie : « j ai trouve un exemple ou l on a ajoute l offre en
publisher a la place de Steam car on a pas la plateforme dans l url et du coup on aurait du
ouvrir la page », puis « on mets en commentaire les pb trouves sur electronicfirst dans sa
config marchant et on mets ce marchant de cote pour le moment ».

**Le défaut.** 2 des 11 offres du premier lot sont parties en PUBLISHER GLOBAL(1) au lieu de
STEAM : `Of Orcs and Men` (100401235) et `RoboCop: Rogue City - Collection` (100401259) —
Romain les a corrigées à la main. Leur titre de feed est NU (ni plateforme, ni livraison, ni
région) et l'URL n'est que le slug du nom, donc `detect_platform` rend son défaut ; `[R27]`
laisse alors passer parce que la page AKS confirme « Direct Publisher », ce qui ne dit rien de
la clé de CE marchand. C'est le mode de panne de `[R27]` lui-même (GameBoost, 2026-07-15),
dans la seule variante qu'il ne couvrait pas : titre muet + page qui confirme éditeur.

**Pourquoi « ouvrir la page » n'est pas la réponse aujourd'hui.** electronicfirst.com est
derrière Cloudflare : GET → 403 « Just a moment… », UA navigateur comme UA neutre (vérifié).
Un `offer_page_resolver` HTTP est donc impossible. Le drapeau `offer_page_readable` (`[R32c]`)
existe mais `src/matcher.py` ne le lit que pour les green gifts, pas dans la branche `[R27]`.

**Chiffré pour la reprise.** 18 candidats PUBLISHER sur TOUS les runs sauvegardés, tous issus
d'un titre nu — MMOGA 6, Electronicfirst 6, Gamivo 6 ; 2 360 lignes skippent déjà en « not
defaulted (R27) » (G2A 1 909, Gamivo 188, Electronicfirst 102, Instant Gaming 81, MMOGA 71,
Kinguin 5, Eneba 4). Le trou n'est donc pas propre à Electronicfirst et coûte au plus 18
lignes à refermer, dont certaines sont de vraies clés éditeur.

**Décision : marchand PARQUÉ**, fichier conservé, hors liste blanche, aucun nouveau lot. Le
diagnostic complet, les chiffres et la piste de correction (faire lire `offer_page_readable`
par la branche `[R27]`, à consigner dans `AGENTS.md` car `[R27]` est une décision revue) sont
écrits dans `src/merchants/electronicfirst.py` et `docs/MERCHANTS.md`. Aucun code du matcher
n'est modifié.

## 2026-09-16 — Première saisie réelle des deux nouveaux marchands : 13 / 13 créées

Romain : « faudra que t ai ajoute entre 10 et 15 offres par nouveau marchant et j irais
verifier le data entry », puis il a lancé les deux lignes d'écriture lui-même (le classifieur
bloque `05_submit` côté Claude).

**Electronicfirst (70) : 11 / 11 créées**, 11 tentatives d'écriture, zéro échec, zéro arrêt,
chacune prouvée par la disparition de la ligne du feed rafraîchi. Le lot couvre volontairement
toute la surface neuve : 4 lignes cross-gen Xbox One + Xbox Series (24eu / 302 et 24us / 303),
1 Xbox Play Anywhere (Microsoft Flight Simulator 2024 Deluxe, région 241 écrite sur la page
console ET sur la page PC, édition Deluxe), 1 Rockstar EU(152) débloquée le matin même par
`[R50]`, 1 DLC EA App EU(3eu), et des lignes Steam(2) / GOG(6) / Publisher(1) dont une édition
Collection. Cinq des onze sont multi-cibles, donc la fenêtre v2 a bien ajouté une seconde
ligne à chaque fois.

**GamersOutlet (31) : 2 / 2 créées** — Grand Theft Auto V Enhanced en Rockstar mondial (15) et
Polylithic en Steam mondial (2). C'est tout ce que sa file contenait de saisissable : sur 19
lignes, 7 sont des licences logicielles sans page AKS, 4 des recharges Roblox, 3 des timeouts
de la recherche AKS. Le lot de 10-15 demandé n'est pas atteignable sur ce marchand aujourd'hui
— sa file doit se remplir d'abord.

Les deux marchands restent **hors liste blanche safe-auto** : la saisie reste supervisée.

## 2026-09-16 — R50 (3e passe) : Microsoft tranché — Windows 10 aux jeux, microsoft software aux logiciels

Romain : « Windows 10 pour les jeux, microsoft software pour les logiciels. » Le menu des
régions porte deux familles Microsoft et elles se partagent par NATURE de produit, pas par
région.

Les **jeux** prennent la famille « Windows 10 … » dans `REGION_IDS` : Global 246, EU 244,
US 245, UK 249 ; les verrous (EMEA 248, ROW 247, FR 404, WINDOWS DE 356, CANADA 663) restent
hors table. Les **logiciels** ne lisent jamais cette table : le chemin logiciel `[R31]`
résout sa région sur les options de la PAGE AKS (`resolve_software_region`), et c'est là que
vit déjà la famille « microsoft software … » (global 532, eu 533, us 534, uk 548) — la
seconde moitié de la décision ne demandait aucun code, seulement l'arbitrage.

Débloque **73 lignes, toutes Eneba**, dont le fichier marchand déclare la plateforme depuis
le préfixe d'URL `windows-store-` : « FINAL FANTASY VIII Remastered WINDOWS EDITION (PC)
Windows Store Key EUROPE » devient candidat MICROSOFT EU(244) au lieu du refus « no region id
for MICROSOFT/EU ». Eneba étant sur la liste blanche safe-auto, le prochain balayage les
prendra.

Restent volontairement non mappés, parce que le menu ne les propose vraiment pas : les
cadeaux simples de Publisher / Epic / EA / GOG / Rockstar, un cadeau Battle.net ou Ubisoft UK,
et `gmg_gift_uk`. Le test « unknown platform fails closed » vérifie désormais le mécanisme
sur un jeton synthétique, puisque toute plateforme PC que l'on détecte est mappée.
1 965 tests, tous verts.

## 2026-09-16 — Audit de Romain sur f96b969 : deux défauts corrigés

Deux points remontés par l'audit de Romain, tous deux réels, tous deux corrigés.

**1. GamersOutlet comparait l'ORTHOGRAPHE des régions, pas leur sens.** Le contrôle
titre / URL opposait le texte du slot au slug (`region_slug(region) != url_run`), donc
« Global » contre `-worldwide`, « EU » contre `-europe` et « US » contre `-united-states`
déclenchaient un faux conflit. Les deux côtés passent désormais par le vocabulaire partagé
(`compound_region_kind`) et ce sont les SENS qui sont comparés ; un slug illisible reste
toléré (le titre est la déclaration), un désaccord réel refuse toujours. Aucune offre du
corpus n'était touchée — le défaut n'attendait qu'une orthographe alternative.
`src/merchants/gamersoutlet.py`.

**2. L'aperçu « Saisir » pouvait diverger sur une empreinte enregistrée périmée.**
`urls.js candFingerprint` lisait le champ `fingerprint` de la ligne quand il existait, alors
que le moteur (`data_entry_auto._candidates_by_store`) le RECALCULE systématiquement. Deux
offres différentes portant par accident la même empreinte enregistrée s'affichaient donc en
1 ligne pendant que le moteur en soumettait 2. L'aperçu recalcule maintenant toujours depuis
les champs, conformément au contrat commun (`src/candidate_contract.py`). Le port Python du
test suit, et un test neuf vérifie qu'une clé enregistrée identique sur deux offres
distinctes ne les fusionne plus. `src/admin/static/urls.js`.

1 961 tests, tous verts.

## 2026-09-16 — R50 (2e passe) : les compartiments CADEAU US / UK existaient aussi

Romain, après le premier correctif : « Tu as raison pour microsoft. Si ca existe le fichier
marchant ne devrait pas affirmer le contraire, fix la config marchant. »

Les fichiers marchands (`k4g.py`, `kinguin.py`), le contrat `merchant_config.py`, `AGENTS.md`,
`EXECUTOR_RULES.md`, `MERCHANTS.md` et `HANDOFF.md` AFFIRMAIENT qu'aucun compartiment
`gift_us` / `gift_uk` n'existait sur aucune plateforme, et une ligne Altergift US ou UK
partait donc en skip « no region id for STEAM/GIFT US ». C'était faux : le menu des régions
porte **Steam Gift US (2577)**, **Steam Gift UK (2572)**, **Battlenet Gift US (568)** et
toute la famille **Ubisoft Gift (501 / EU 504 / US 505)** — cette dernière n'était pas mappée
du tout. Tout est mappé.

La propriété de sécurité ne bouge pas : un cadeau verrouillé prend SON compartiment et ne
s'élargit jamais au cadeau mondial de la plateforme (25). Ce qui n'existe vraiment pas reste
absent et fail-closed : `gmg_gift_uk` (aucune plateforme), un cadeau Battle.net UK, un cadeau
Ubisoft UK, et tout cadeau simple EA / Epic / GOG / Publisher / Rockstar.

Conséquence métier : les lignes Altergift US et UK de K4G et Kinguin ENTRENT désormais sous
leur propre compartiment au lieu d'être refusées (13 lignes comptées sur les runs
sauvegardés). La décision revue d'AGENTS.md est corrigée sur place, avec la mention qu'un
audit retrouvera l'ancienne phrase dans l'historique git et ne doit pas la restaurer.

`tests/test_region_ids_catalog.py` passe à 14 tests (les compartiments cadeau figés, et
l'absence vérifiée là où le menu ne propose rien) ; les trois tests qui figeaient l'ancienne
affirmation sont réécrits sur le comportement corrigé. 1 959 tests, tous verts.

## 2026-09-16 — R50 : trois plateformes avaient des régions AKS jamais mappées (faux refus)

Romain, après le dry-run des nouveaux marchands : « Pour les regions Rockstar on a toutes les
regions dont tu as besoin meme la globale, verifie mieux, tu dois pouvoir aller chercher ca
dans le drop down des regions sur l'outil AKS feed. » Vérification faite dans le catalogue de
régions du feed (867 options, identiques sur les 11 catalogues sauvegardés du 10 au 15/09) :
il avait raison, et la même lacune existait sur deux voisins.

Mappages ajoutés : **Rockstar** global 15 (l'option nue « Rockstar (15) » EST le compartiment
mondial — même forme que « Publisher (1) », le menu ne porte aucun libellé « Rockstar
GLOBAL »), us 151, eu 152, uk 158 ; **Epic** us `80us`, uk `805` ; **EA** us `3us`, uk `3uk`.
Comptés sur tous les runs sauvegardés, ces trous valaient **35 lignes Rockstar** (29 global,
4 uk, 2 eu), **9 EA/US** et **8 EPIC/US** refusées à tort « no region id ». Les verrous de ces
familles (Rockstar APAC / ASIA / EMEA / LATAM / ROW / France / Allemagne / Pays-Bas / Moyen-
Orient) restent hors table : ce sont des régions interdites, pas des bases.

**Le mappage seul ne suffisait pas.** « ROCKSTAR » était déjà une phrase de bruit pour la
construction du slug mais pas un JETON de bruit pour le garde d'identité : la lacune était
invisible parce que la porte région tirait avant. Une fois les compartiments mappés, chaque
ligne Rockstar mourait un cran plus loin sur « different/expanded product — extra words:
['ROCKSTAR'] ». Le mot rejoint `NOISE_TOKENS` avec tous les autres mots de boutique (sans
risque : aucun nom de produit AKS des corpus sauvegardés ne le contient). Les deux
modifications sont une seule correction — vérifié sur les vraies lignes des deux nouveaux
marchands, qui deviennent des candidats GLOBAL(15), UK(158) et EU(152).

Restent volontairement non mappés et fail-closed : **MICROSOFT** — le menu propose DEUX
familles, « Windows 10 … » (244-249) et « microsoft software … » (532-562), choisir est une
décision métier, pas un mappage (73 lignes en attente) — et les compartiments GIFT de
PUBLISHER et EPIC, que le menu n'a pas (186 et 1 lignes, refus correct).

`tests/test_region_ids_catalog.py` (9 tests) fige les ids et interdit qu'un verrou soit mappé
comme base ; le test G2A « unknown platform fails closed » est réécrit sur MICROSOFT, le seul
cas restant. 1 954 tests, tous verts.

## 2026-09-15 — R48 / R49 : fichiers marchands GamersOutlet (31) et Electronicfirst (70)

Romain : « Fais GamersOutlet et Electronicfirst » — les deux marchands de tête de l'audit
« nouveaux marchands » dont la région et la plateforme se lisent sans ouvrir la page.

Méthode : extraction lecture seule des deux feeds complets (GamersOutlet 20 lignes, une page
— `runs/20260915-gamersoutlet` ; Electronicfirst 323 lignes uniques, couverture prouvée —
`runs/20260915-electronicfirst`), puis un workflow de 14 agents : trois lentilles
indépendantes par marchand (région / plateforme-consoles / non-jeux-livraison-édition), une
synthèse par marchand, et trois **contradicteurs adversariaux** par marchand chargés de
RÉFUTER chaque décision de politique. Trois décisions sur six ont été réfutées avec preuves
chiffrées, et les corrections sont intégrées.

**GamersOutlet `[R48]`.** Grammaire à slot parenthésé `( <LIVRAISON> / <RÉGION> )`. Le slot
est obligatoire (le marchand écrit « Global » explicitement 20/20 et ne laisse jamais le vide)
et son vocabulaire est fermé des deux côtés. Correction du contradicteur : la liste des
boutiques acceptées ne doit pas être recopiée à la main — `STORE_PLATFORM` est la table du
fichier et `url_platform` la publie au matcher, donc la boutique acceptée et la plateforme
lue sont la même donnée ; « PC EA Key » / « PC Blizzard Key » auraient sinon passé la porte
puis résolu aucune plateforme. La porte ROBUX proposée était **inerte** (les 4 lignes Robux
s'arrêtent déjà sur « unknown store ROBLOX ») : elle n'a pas été ajoutée. Verdicts : 16
passent, 4 skips.

**Electronicfirst `[R49]`.** Grammaire Kinguin (code MAJUSCULE avant la phrase plateforme),
plus une forme où le code est en dernier. Le contradicteur a **réfuté « vide = mondial »**
côté console, chiffres à l'appui : le slot ne porte JAMAIS de valeur mondiale (0/113 slots
écrits), c'est un champ de RESTRICTION ; le marchand écrit la région sur 73 % de ses lignes
console contre 14,5 % de ses lignes PC ; laissées au GLOBAL implicite, 7 lignes partaient en
monde entier dont quatre jeux complets (Forza Motorsport, Forza Motorsport Premium, MSFS 2024
Premium Deluxe, Horror Adventure PS4/PS5) — un code PSN/Xbox est lié au marché du store.
D'où `[R49c]` : ligne console sans slot = skip fail-closed. S'y ajoutent `[R49a]` EU partielle
(« EU (without DE) », 16 lignes — pas de bucket « EU moins un pays »), `[R49b]` mot de région
épelé dans le nom avec slot vide, et les skips non-jeux / logiciels. Les lignes PC muettes
gardent le GLOBAL implicite **à titre provisoire**, avec la condition de validité écrite et
figée par un test : le jour où un slot EF résout à « global », le vide devient ambigu et
`[R47]` s'applique. Verdicts : 247 passent (eu 55, us 10, uk 1, 181 sans code), 18 `[R49c]`,
16 `[R49a]`, 21 non-jeux, 14 régions interdites, 6 logiciels, 1 `[R49b]`.

Une règle « trou de template » (double espace à la position du slot) proposée par le
contradicteur a été **mesurée puis écartée** : inerte et bruitée (2 des 5 lignes ont le trou
dans le nom du produit, les autres sont déjà couvertes). Le refus est consigné dans le module
et dans `docs/MERCHANTS.md` pour qu'un audit ne la repropose pas à l'aveugle.

Les deux marchands restent **hors liste blanche safe-auto** : dry-run supervisé au premier
passage. Registre + `docs/MERCHANTS.md` (deux sections) + `EXECUTOR_RULES.md` §4.4 `[R48]` /
`[R49]` + README mis à jour ; `tests/test_merchants_gamersoutlet.py` (24 tests) et
`tests/test_merchants_electronicfirst.py` (24 tests) ; 1 945 tests au total, tous verts.

## 2026-09-15 — R47 : fichier marchand GameBoost (store 157), la région est obligatoire

Audit « nouveaux marchands potentiels » (Romain 2026-09-15 : « le but, c'est de trouver de
nouveaux marchands potentiels qu'on pourrait ajouter comme les marchands actuels… On veut
traiter en priorité ceux qui n'ont pas besoin d'avoir la page marchand »). GameBoost sort
en tête du dépouillement des 140 boutiques du feed, et Romain a posé la bonne question :
« on avait pas déjà essayé et dû ouvrir la page marchand car la région n'est pas toujours
renseignée ? » — **oui**. Le run GameBoost du 2026-07-15 a été **annulé en direct**
(`[R27]`) : titres sans jeton de plateforme, vérité sur la page de l'offre, page bloquée par
Cloudflare ; les 33 candidats ont été jetés avant validation et la boutique est restée hors
liste blanche.

Ré-audit sur le feed vivant (821 lignes uniques, pages 1-10, extraction lecture seule
`runs/20260915-gameboost-p2-10` + page 1 du dépouillement) : la grammaire a changé, les
titres déclarent aujourd'hui la plateforme dans la grande majorité des lignes — mais la
région reste absente d'une ligne sur six. D'où `src/merchants/gameboost.py` et la règle
`[R47]` : **un titre GameBoost sans mot de région est un skip fail-closed, jamais le GLOBAL
implicite générique.** C'est l'inverse de Kinguin / MMOGA, où « pas de code » EST la façon
d'écrire « global » : GameBoost écrit `GLOBAL` / `Global` / `ROW` en toutes lettres quand la
ligne est mondiale, donc un slot vide veut dire « seulement sur la page marchand ».

Verdicts du fichier sur les 821 lignes : **430 passent** (eu 258, us 115, global 57), 175
non-jeux (cartes cadeaux sous `/gift-cards/`, à points médians « Razer · Chile · 500 CLP » —
les annonces de clés sont des URL plates `…-00-<id>`), 137 sans région `[R47]`, 79 régions
interdites (ROW 37, EMEA 19, NORTH AMERICA 6, TURKEY 4, CANADA 3, MENA 2, GERMANY 2, …).
Quatre hooks : `precheck`, `title_region`, `resolve_name`, `console_region_slot` ; plateforme
laissée à la lecture générique du titre (`title_is_platform_source`, comme Kinguin) et
**aucun** `offer_page_resolver` — la page marchand n'est jamais ouverte, un titre sans
plateforme garde le skip `[R27]`. La découpe du nom est ancrée à la FIN du titre, donc
« Stronghold 2: Steam Edition Steam Key EU » résout « Stronghold 2: Steam Edition » et
« Nintendo Switch Sports (Switch) (EU) » résout « Nintendo Switch Sports ».

GameBoost reste **hors liste blanche safe-auto** (`src/admin/auto_merchants.py`) : le fichier
sert aux runs supervisés (02 → 03 → 04 → 05), pas à `/auto`. Registre
(`src/merchants/registry.py`) + `docs/MERCHANTS.md` + `EXECUTOR_RULES.md` §4.4 `[R47]` mis à
jour ; `tests/test_merchants_gameboost.py` (18 tests), 1 897 tests au total, tous verts.

## 2026-09-15 — Lot 2 : contrat des candidats et des cibles centralisé (`src/candidate_contract.py`, go Romain)

- **Une seule définition de l'identité d'un candidat.** L'empreinte de validation
  (`offer_id|aks_product_id|region_id|edition_id`, étendue `|+pid:rid:eid,…` en R45) et la
  normalisation des `targets` étaient écrites quatre fois — `matcher.Candidate.fingerprint` /
  `Target.to_dict`, `validation.candidate_fingerprint` / `candidate_targets` / `_target_ids`,
  `submitter.normalize_targets` / `_primary_target`, `app.js fp()` / `targetRegion()`. Elles
  vivent désormais dans **`src/candidate_contract.py`** (stdlib seule, n'importe aucun étage :
  `normalize_targets`, `fingerprint`, `primary_target`, `template_targets`, `to_nested_target`,
  `is_multi_target`, `flatten_target`, `MAX_TARGETS_PER_OFFER`, `CandidateContractError`).
  Les étages l'importent : le matcher (`Candidate.fingerprint` = `fingerprint(to_dict())`,
  `Target.to_dict` = `to_nested_target(asdict)`), la validation (`candidate_fingerprint` /
  `candidate_targets` = alias fins, refus re-levés en `ValidationError` — appelants inchangés :
  `04_validate`, `10`, `12`, `data_entry_auto`, console admin), le submitter
  (`normalize_targets` = alias fin, `MAX_TARGETS_PER_OFFER` importé), `validation_io`
  (`_mirror_primary_target` / `_is_multi_target`). **`app.js`** porte un **port littéral**
  du Python entre les marqueurs `// candidate-contract:begin` / `:end` (mêmes refus : cible
  sans id ou `targets[0]` ≠ primaire → throw, la ligne s'affiche verrouillée « candidat
  malformé » au lieu d'une empreinte `null`).
- **Exemples partagés** : `tests/fixtures/candidate_contract_examples.json` (25 cas — PC /
  logiciel / console 1-2-3 cibles, fichier pré-R45 sans `targets`, `targets` `[]` / `null` /
  `[{}]` / `["x"]`, forme plate du plan, ids numériques, id null / manquant → refus,
  `targets[0]` non miroir → refus, libellés verbatim avec / sans BOM, surcharge opérateur).
  `tests/test_candidate_contract.py` (17 tests) les rejoue sur le module, sur les alias
  validation / submitter, sur `validation_io` et sur des `Candidate` construits à 1 / 2 / 3
  cibles ; `tests/js/candidate_contract_check.js` les rejoue sur le bloc `app.js` sous node
  (nouvelle étape CI gardée par `hashFiles`, le VPS n'a pas node).
- **Preuve avant / après** (`scratchpad/lot2_fingerprint_diff.py`, lecture seule de
  `/home/debian/executor/runs/`) : **368 `candidates.json`, 1 941 candidats** (1 693 sans
  `targets`, 128 à une cible, 84 à deux, 36 à trois) — empreinte ancienne (`validation.py`
  de 5412136) = nouvelle = alias = clé `fingerprint` stockée par l'ancien matcher, cibles
  gabarit et cibles plan identiques : **0 différence**, 0 refus de part et d'autre.
- Comportement : identique octet pour octet sur tout le corpus. Seule nuance : une entrée
  `targets[]` malformée d'un candidat multi-cibles lève désormais aussi côté submitter
  (avant : conservée avec des ids `None` pour être bloquée à la résolution catalogue) — un
  tel candidat était déjà refusé par la validation avant d'atteindre `_prepare`
  (`verify_approved_against_source` re-dérive chaque empreinte), le chemin est inatteignable
  en pratique et reste fail-closed.
```

## 2026-09-15 — saisie par page : consoles par défaut (`scripts/11` / `scripts/12`, Romain)

- **Saisie par URLs de pages et consoles `[R45]`** — Romain : « les consoles sont prises en
  compte par défaut partout, y compris travailler sur une page de jeu ». `scripts/11` et
  `scripts/12` acceptent `--consoles` (**défaut**) / `--no-consoles`, passé à chaque
  `match_offer`. `scripts/11` accepte les **URLs de pages console** (`buy-<slug>-<kind>-
  compare-prices/`, kind ∈ ps4 / ps5 / xbox-one / xbox-series / nintendo-switch /
  nintendo-switch-2 ; `parse_page_url`, `PageRef`), les lit comme la page PC, les **refuse**
  sous `--no-consoles` avant tout fetch (`ConsolePageRefused`, par URL) ; recherche par
  l'**identité** de la page (« Hades PS5 » → « Hades ») ; résolution épinglée `PinnedPage`
  (ancre PC / pages sœurs lues depuis la barre d'onglets de la page épinglée, cache par jeu,
  garde anti-throttle partagée → `aborted: aks_throttled`) ; **qualification par cible** : un
  candidat est retenu ssi l'une de ses `targets` est la page demandée, gardé **entier** —
  une clé cross-gen demandée depuis une page console est écrite sur toutes ses pages
  déclarées, une clé Play Anywhere depuis la page PC qualifie par sa cible XBOX_PC, une clé
  d'une autre plateforme seule est ignorée avec raison explicite. Aperçu : `[page <kind>]`,
  lignes `↳` par cible, note cross-gen. `scripts/12` : flag informatif (log / JSON),
  transmis à rien — les candidats multi-cibles traversent le groupement par store entiers,
  empreinte étendue R45, `05_submit` lit `targets` dans `approved.json`. Tests :
  `tests/test_data_entry_by_urls.py` (69), `tests/test_data_entry_by_urls_submit.py` (7).
  **Non exercé sans navigateur/réseau** : la lecture réelle des pages console AKS par
  `scripts/11` (barre d'onglets live), le lancement admin avec le flag.

- **Audit 0eb1e8e → 5412136 : aperçu web — chaque cible affichée `[R45]`** (finding 1, high).
  L'aperçu « Saisie par jeux » (`urls.js`) n'affichait que la région/édition **primaire**
  d'un candidat : une clé PS4 + PS5 (2 `targets`) montrait une seule ligne, et l'opérateur
  confirmait le GO sans voir toutes les pages qui allaient être écrites. Désormais : (1) un
  KPI « page(s) cible(s) à écrire » = somme des cibles ; (2) chaque candidat multi-cibles
  affiche « à saisir ×N » puis **une ligne `target-row` par cible** — « `<plateforme> · page
  <aks_product_id> (<aks_name>) · <région> (<id>) · <édition> (<id>)` », avec l'URL de la
  page AKS cible cliquable ; une cible unique qui n'est **pas** la page du jeu est affichée
  de la même façon ; un candidat mono-cible sur la page du jeu garde sa ligne d'aujourd'hui
  (rien de caché : sa région/édition est celle de la cible) ; (3) le **modal « Saisir »** liste
  **toutes** les cibles de chaque candidat (`#confirm-targets`, une ligne « ↳ » par écriture)
  et annonce le total « **N offres sur T pages** » (`#confirm-t`) avant le champ GO. Lecture
  tolérante : `targets[]` imbriqués (`region:{label,id}`), forme plate (`region_label` /
  `region_id` / `edition_label` / `edition_id`) et **liste absente** (anciens aperçus → la
  cible primaire seule). Aucune dépendance, pas de style inline (CSP `default-src 'self'`) :
  les lignes réutilisent `.off` / `.logline` / `.log`.
  **Récapitulatif aligné sur le lot réellement soumis** (Romain, même jour : « il reste à
  aligner le récapitulatif sur le lot réellement soumis ») — les KPI « offres à saisir (lot) »
  et « page(s) cible(s) à écrire », le bouton « Saisir les N offre(s) » et le modal GO comptent
  le lot **tel que `scripts/12` le construit** (`urls.js submitBatch`, miroir de
  `_candidates_by_store`) : jeux non résolus / en erreur ignorés, groupes marchands sans
  `store_id` ignorés, et **par store une occurrence par empreinte complète** (`fingerprint` du
  candidat, sinon la formule du contrat `offer_id|aks_product_id|region_id|edition_id`
  + `|+pid:rid:eid,…` sur les cibles supplémentaires — `candFingerprint`). Cas Romain : deux
  URLs collées (Hades PS4 + Hades PS5), une seule offre G2A « Hades (PS4 / PS5) » trouvée
  par les deux recherches, deux cibles à chaque fois → avant « 2 offres sur 4 pages », le
  moteur n'en gardait qu'une → désormais « **1 offre sur 2 pages** ». Le modal liste le lot par
  marchand (store), chaque offre **une seule fois** (le doublon sous l'autre jeu est omis) ;
  le KPI signale « N trouvée(s), X doublon(s) entre jeux » quand ils diffèrent ; le tableau
  par jeu continue d'afficher l'offre sous chaque page cherchée. La clé du moteur est
  vérifiée : `_candidates_by_store` groupe par `store_id` et son `_seen` d'empreintes vit
  **par groupe store** — donc déjà `store_id + empreinte complète`, aucun changement de
  `scripts/12`. Test : `BatchMirrorTests` (port Python de la règle JS comparé au moteur sur
  la fixture Hades PS4/PS5 → 1 offre / 2 pages, sur une fixture mixte, et la formule de
  repli égale à `candidate_fingerprint`).
- **Audit 0eb1e8e → 5412136 : scripts/12 — cohérence du mode consoles avec l'aperçu `[R45]`**
  (finding 2, medium). `scripts/12` acceptait `--consoles` / `--no-consoles` **sans le
  comparer à l'aperçu** : lancé en CLI direct (sans le garde `consoles_mismatch` du manager
  admin), un candidat à deux cibles console partait dans `05_submit` même sous
  `--no-consoles`. Désormais `consoles_mode_refusal(from_recap, consoles)` tranche
  **avant toute préparation** (aucun sous-run, aucun triple, `run_by_urls_submit` jamais
  appelé) : (1) le **stamp `consoles`** du recap de l'aperçu (bool écrit par `scripts/11` ;
  absent sur les anciens aperçus) doit être égal au mode demandé, **dans les deux sens** —
  sinon exit 2 : « `consoles_mismatch: mode consoles de l'aperçu (true = --consoles) ≠ mode
  demandé (false = --no-consoles) — relancer l'aperçu ou le submit avec le même mode` » ;
  (2) **défense en profondeur** sous `--no-consoles` (aperçus sans stamp) : tout candidat dont
  les `targets` (ou le `platform` primaire) portent une plateforme console (`XBOX_ONE` /
  `XBOX_SERIES` / `XBOX_PC` / `PS4` / `PS5` / `SWITCH` / `SWITCH2` — `CONSOLE_FAMILIES` de
  `src/console_keys.py`) **ou** plus d'une cible refuse le lot, exit 2, les fautifs listés
  (`[marchand] nom (PS4, PS5, 2 cible(s))`, 5 max puis « …(+N) »). Le refus est écrit comme
  les autres : `recap.json` du run submit (`mode: submit`, `aborted: consoles_mismatch: …`,
  `merchants: []`), événement JSONL `submit_run_aborted` (`reason`, `consoles`,
  `preview_consoles`, `offenders[]`), ligne JSON sur stdout. Un stamp non-booléen
  (`"true"`, `null`) n'est **pas** un stamp : seul le scan des candidats décide. Sous
  `--consoles` (défaut) un aperçu sans stamp n'est pas scanné (les cibles consoles y sont
  légitimes). Le flag n'est toujours passé à **rien** en aval (05_submit lit les `targets`
  dans `approved.json`).

---

## 2026-09-15 — consoles par défaut partout (décision Romain « 1 »)

Après les deux canaries du modal v2 (1 cible, 2 cibles) et le dry-run consoles MMOGA du matin
(run `20260915-081607-dryrun-consoles` : 663 offres → **174 candidats consoles** — 89 à une
cible, 59 à deux cibles, 26 à trois cibles — et 489 skips), Romain a tranché « 1 » : les
consoles sont prises en compte **par défaut partout** — sweep safe-auto, lanceur de la console
admin, CLI du match, aperçu / saisie by-urls — avec un **opt-out explicite**.

- **`scripts/10_data_entry_auto.py`** : `--consoles` devient le **défaut** (le flag reste
  accepté, no-op explicite) ; nouveau **`--no-consoles`** (`dest=consoles`, `store_false`) pour
  un sweep PC seul ; `SweepConfig.consoles` par défaut `True` (`src/data_entry_auto.py`) ;
  le stamp `recap.json["consoles"]` est inchangé ; l'argv de `03_match` porte **toujours** le
  mode — `--consoles` ou `--no-consoles` — pour qu'un dossier de run montre le réglage
  (`_make_stages(consoles=True)` par défaut).
- **`scripts/03_match.py`** : `--consoles` par défaut `True` + `--no-consoles` ;
  `match_meta.json["consoles"]` et `match_feed(consoles=…)` inchangés (défaut de la
  bibliothèque toujours `False`).
- **Console admin** (`src/admin/app.py`, `src/admin/submit_manager.py`) :
  `POST /api/data-entry/auto` lit `consoles` (booléen JSON, **absent = true** ; autre chose
  qu'un booléen → 400 `bad_consoles`, rien de lancé — `_parse_consoles`) ;
  `SubmitManager.start_data_entry_auto(consoles=True)` ajoute `--consoles` / `--no-consoles` à
  l'argv de `scripts/10` et l'enregistre dans le meta (`admin_submit.json["consoles"]`). Même
  champ et même paire de flags pour l'aperçu by-urls (`start_data_entry_by_urls` →
  `scripts/11`) et la saisie by-urls (`start_data_entry_by_urls_submit` → `scripts/12`) —
  contrat avec le chantier parallèle sur 11 / 12 : flags aux mêmes orthographes, défaut `True`.
  Garde fail-closed : un submit by-urls dont le réglage contredit le stamp booléen `consoles`
  de l'aperçu (quand il existe dans `recap.json`) est refusé 409 `consoles_mismatch`.
- **UI** : case « Consoles (pages Xbox / PlayStation / Switch) » **cochée par défaut** dans le
  formulaire `/auto` (`auto.html` / `auto.js`) et dans le formulaire by-urls `/games`
  (`urls.html` / `urls.js` — envoyée à l'aperçu ET à la saisie, même réglage), transmise en
  `consoles` dans le corps JSON ; indication « décochez pour un sweep PC seulement ».
- **Tests** (+9 ; 262 verts sur les cinq modules `test_data_entry_auto_cli`,
  `test_data_entry_auto`, `test_match_cli`, `test_admin_app`, `test_admin_submit_manager`) :
  CLI 10 (défaut ON, `--no-consoles` avec / sans `--dry-run`, argv 03 explicite dans les deux
  sens, `--consoles` explicite = no-op), moteur (recap `consoles` true par défaut), CLI 03
  (défaut ON / `--no-consoles`), manager (argv + meta pour auto / by-urls / by-urls submit,
  garde `consoles_mismatch`), routes admin (auto / by-urls / by-urls submit avec et sans
  `"consoles": false`, valeur non booléenne refusée sans lancement).
- **Docs** : README (commandes + principes), HANDOFF (état + commandes : la ligne de nuit n'a
  plus besoin de `--consoles` ; backlog consoles 1-3 faits), EXECUTOR_RULES §4.3 / §4.12
  (item 6 : défaut ON, opt-out) / §12, DATA_CONTRACTS (`match_meta.consoles`,
  `recap.consoles`, corps de l'API admin, meta `admin_submit.json`), ce CHANGELOG. La phrase
  « `--consoles` exige `--dry-run` » du 14/09 reste en historique seulement.

## 2026-09-15 — écriture consoles ouverte : le garde « `--consoles` exige `--dry-run` » est levé (GO Romain)

Après les deux canaries (1 cible, 2 cibles), Romain : « go pour l'étape suivante » puis
« 1 » (retirer le garde-fou). `scripts/10_data_entry_auto.py --consoles` lance désormais un
sweep réel ; `05_submit` garde chaque entrée (forme `targets_v2`, plafond 3 cibles, relectures,
un seul clic). Dry-run consoles MMOGA du matin (run `20260915-081607-dryrun-consoles`) : voir
le bilan ci-dessous une fois terminé. Docs : README, EXECUTOR_RULES §4.12, HANDOFF.

## 2026-09-15 — canaries consoles sur le modal v2 : 1 cible OK, 2 cibles OK (bouton `+ Add another page`)

- **Canary 1 (1 cible)** — Legend of Mana (Nintendo Switch Download Code) - EU Key (offre
  MMOGA 101039824) → page « Legend of Mana Nintendo Switch » 64915, bucket `99eu`,
  Standard(1) : `create.status SUCCESS`, `created 1`, signal AKS « [product 64915] Offer
  created for locale en_EU and merchant 40 », ligne disparue du feed (667 → 666).
- **Canary 2, 1ʳᵉ tentative** — NBA 2K25 (Xbox One / Series X|S) - EU : échec fermé
  `TARGET_ROW_NOT_ADDED`, rien d'écrit : le `<button>` voisin du champ cible est le « × »
  `data-remove-target`, pas l'ajout de ligne → localisateur corrigé (`f0beee5`) ; à la
  relance la ligne n'était plus dans le feed (« offer not in current feed (by id and by URL) »,
  feed dynamique : 666 → 615 → 664 en une heure).
- **Canary 2, 2ᵉ tentative** — Diablo 2 - Resurrected [Xbox One / Series X|S Download Code]
  (offre 101039808) → page Xbox One 70479 `24` + page Xbox Series 70802 `300`, Standard(1) :
  ligne 1 ajoutée via `[data-add-target]` (« + Add another page », `type=button`), deux lignes
  relues avant le clic, formulaire valide (16 champs), un seul clic Create, `created 1`,
  ligne disparue du feed. Signal AKS capturé : « [product 70479] Offer created for locale
  en_EU and merchant 40 … » (texte tronqué à 160 caractères : la création sur la 2ᵉ page
  70802 reste à confirmer dans le back-office AKS ou sur la page une fois le cache
  rafraîchi — les pages AKS n'affichaient encore aucune des trois offres 1 h après).
- Le modal v2 est donc **prouvé en écriture** pour une cible (chemin PC identique) et pour deux
  cibles ; la saisie consoles peut reprendre en dry-run puis en sweep sur go.
- Boutons observés dans le modal (`--inspect`, `inspection.modal_buttons`) : « × »
  (`data-remove-target`, par ligne), « + Add another page » (`data-add-target`, hors lignes),
  Close (`data-action-close`, caché), Cancel (`data-action-cancel`), Create offer
  (`data-action-submit`, `button-primary`) — les trois derniers sont `type=submit`.

## 2026-09-14 — submitter: modal v2 (region/edition per target row), cap 3, no Enter

- **AKS feed tool change (Romain, 2026-09-14):** the "Create offer" modal now takes
  region and edition PER TARGET PAGE. Read-only inspection (run
  `20260914-inspect-consoles`): row 0 = `input[name="offer[targets][0][target]"]`
  (required, `pattern="(\d+)|(https?://.+)"`, `data-target-input`, next sibling
  `button.button` = add-row) + Selectize overrides `offer[targets][0][region]` /
  `[edition]` (`data-target-override`, not required); the old `offer[targets][]`
  no longer exists; global `offer[region]` / `offer[edition]` and the Create button
  unchanged; the form has `method=get`, no `action`.
- **Consequence before this change:** `add_target_trusted` looked for
  `offer[targets][]` → `NO_TARGETS_FIELD` → required target input empty →
  `FORM_INVALID` → no click. Fail-closed, but ZERO creations for EVERY merchant (PC
  included) since the tool change.
- **`src/submit_session.py`:** `modal_context()` now reports `modal_shape`
  (`targets_v2` / `targets_v1` / `unknown`, `_MODAL_CTX_JS`) + `modal_shape_detail`;
  `_TARGETS_READBACK_JS` reads both shapes (v1 inputs; v2 rows with target value +
  both override selects through both channels); new read-only
  `_ADD_ROW_BUTTON_PROBE_JS` (the `<button>` after the LAST row's target input, by
  DOM relation, with its `type` and a `submit_like` verdict); `_TARGETS_PROBE_JS`
  exposes `next_sib_button` so `--inspect` shows the add-row button's type. New
  write flow `WriteSubmitSession.fill_targets_v2_trusted(targets, region_select,
  edition_select)`: globals with the primary target's ids → row 0 (focus click +
  `Input.insertText`, readback == id, overrides set EXPLICITLY) → for each extra
  row: trusted add-row click proven by readback (`TARGET_ROW_NOT_ADDED` /
  `TARGETS_COUNT_MISMATCH`), fill like row 0 → validity gate → obstruction probe →
  full pre-click readback of both globals + every row (`VALUE_DRIFTED_BEFORE_CLICK`
  generalised) → ONE trusted Create click → poll. **`_press_enter` deleted**; the
  v1 `add_target_trusted` Enter commit fallback is now a fail-closed
  `NO_ADD_BUTTON` (Enter natively submits the `method=get` form).
- **`src/submitter.py`:** plan entry `modal_shape` (+ `modal_shape_detail`); shape
  gate: `unknown` → blocker `modal_shape_unknown` for every entry (real blocker,
  feeds the streak); R45 multi-target gate now shape-aware (`targets_v1` only);
  `targets_v2` entries ready with every target resolved in the catalog;
  `Submitter._process` routes v2 → `fill_targets_v2_trusted` (all targets, BOM-free
  queries), v1 → `fill_then_click_trusted`, anything else refused. **Cap
  `MAX_TARGETS_PER_OFFER = 3`** (Romain 2026-09-14: "3 ou 4 pour le moment") →
  blocker `too_many_targets` « plus de 3 cibles — plafond du modal AKS (Romain
  2026-09-14) » BEFORE locate/modal open; designed skip counted in
  `gated_too_many_targets` (no guard streak). Dry-run `would_submit` lists the v2
  rows; `--inspect` also dumps `modal_shape_unknown` entries.
- **Romain's three confirmations (2026-09-14), cited in code + SUBMITTER_SPEC §4c:**
  (1) the button next to the target input ADDS a row (readback still proves it);
  (2) empty per-target region/edition INHERIT the globals (overrides still set
  explicitly); (3) at most "3 ou 4" targets → cap 3.
- **Statuses added:** `MODAL_SHAPE_MISMATCH`, `NO_TARGETS`, `NO_TARGET_ID`,
  `NO_TARGET_INPUT`, `TARGET_VALUE_MISMATCH`, `NO_ROW_REGION_PICK`,
  `NO_ROW_EDITION_PICK`, `NO_ADD_BUTTON`, `ADD_BUTTON_UNSAFE`,
  `TARGET_ROW_NOT_ADDED`, `TARGETS_COUNT_MISMATCH`, `TARGETS_READBACK_UNREADABLE`
  (+ row-level `ROW_ADDED` / `ROW_FILLED`); blockers `modal_shape_unknown`,
  `too_many_targets`.
- **Tests:** `tests/test_submitter.py` — `V2ModalDom` + `V2DomWriteSession` (the
  REAL `fill_targets_v2_trusted` over a DOM fake: single-target end-to-end, two and
  three targets, add-row failure, submit-like button, count mismatch, row/global
  drift, row pick failure, FORM_INVALID, shape mismatch, empty id, still-in-feed);
  `ModalShapeTests`; `TooManyTargetsTests`; v1 fake without Enter; fakes default to
  `targets_v2`. `tests/test_embedded_js.py` registers `_ADD_ROW_BUTTON_PROBE_JS`.
  246 tests OK (submitter + embedded_js + submit_cli).
- **UNVERIFIED live, fail-closed:** the add-row button's `type` (refused if
  submit-like → run `--inspect` on a console candidate and read
  `targets_probe.targets[0].next_sib_button` before the first multi-target write);
  whether appended rows carry their own add button; inheritance is never used.
- **2026-09-15 — the two canaries + add-row locator fixed (canary 2).** Canary 1
  (Legend of Mana, Switch, MMOGA, mode `learning`) → **created**: offer 101039824
  on page 64915, 99 €, signal « Offer created for locale en_EU and merchant 40 » —
  the single-row v2 path works live end to end. Canary 2 (NBA 2K25 Xbox One +
  Series, two targets, run `20260914-canary-two-targets`) → **failed closed
  `TARGET_ROW_NOT_ADDED`**: the `<button>` that is the next sibling of the last
  row's target input is the row's **REMOVE button** (`button.button
  [data-remove-target]`, "×", `type=button`) — the trusted click added nothing
  (1 row read back), nothing was written. **Locator fixed** (`src/submit_session.py`,
  `_ADD_ROW_BUTTON_PROBE_JS`): never a `[data-remove-target]` element;
  `#TB_ajaxContent form [data-add-target]` (`<button>`/`<a>`) first, else the
  UNIQUE add-ish `<button type=button>` (data-\* names or text ~
  `/add|ajout|plus|\+/i`, not remove, not submit-like) — 0 or several →
  `NO_ADD_BUTTON`, no click; the diag records `add_button.matched_by`
  (`[data-add-target]` / `fallback:data-attr:<name>` / `fallback:text`) and, on
  refusal, every `<button>` considered in `add_button.candidates` with its
  `rejected` reason; `_add_button_refusal` refuses `data-remove-target` again on the
  Python side (defence in depth). `_add_target_row_trusted` now reads the row count
  **before** the click (`add.rows_before`, must equal the row index) and a count that
  went **down** after the click is the new status **`ROW_REMOVED`** (cleanup, no
  Create click). New read-only `_MODAL_BUTTONS_JS` / `SubmitSession.probe_modal_buttons()`,
  merged into `inspect_modal_dom()` → **`inspection.modal_buttons`** in
  `modal_inspection.json` (every `<button>` / `<a role=button>`: tag, type
  property + attribute, id, class, text ≤ 60, all data-\* attributes ≤ 40, visible,
  in_form, in_targets_container, in_row, path) so the next `--inspect` shows the real
  add button. **Tests** (`tests/test_submitter.py`): `V2ModalDom` models the per-row
  remove buttons (next to each input), a separate add button (`data-add-target` /
  plain fallback / none) and the Create button, `add_row_probe` mirrors the JS rule;
  new: only remove buttons → `NO_ADD_BUTTON` and nothing clicked, the live canary-2
  descriptor refused before any click, an "add" click that removes a row →
  `ROW_REMOVED` and no Create click, the fallback used only when unique (ambiguous →
  `NO_ADD_BUTTON`), row-count drift before the click, `inspection.modal_buttons`
  merge; `_MODAL_BUTTONS_JS` registered in `tests/test_embedded_js.py`. 223 tests OK
  (submitter + embedded_js; node absent on the dev box → the JS syntax check is
  skipped, brackets/quotes/read-only tokens checked by hand). Docs: SUBMITTER_SPEC
  §4c (locator rule, statuses table, verified/unverified), DATA_CONTRACTS modal v2
  (`create.rows[].add.rows_before` / `add_button.matched_by` / `candidates`,
  `inspection.modal_buttons`). **Still UNVERIFIED live:** `[data-add-target]` is an
  inference from the tool's naming — run `--inspect` on a multi-target candidate and
  read `inspection.modal_buttons` before the next multi-target canary.

---

## 2026-09-14 — Un fichier de config par marchand (règle de Romain) : hooks consoles, six nouveaux fichiers marchands

**Règle de Romain (répétée depuis le 2026-08-11, ultimatum du 14/09)** : « pour la détection
région / édition / plateforme, tu as un fichier de config par marchand. Et si tu ne l'as pas,
tu dois l'avoir. » Traduction dans le repo : **chaque marchand a son fichier ; la grammaire
marchande ne vit jamais dans un module générique.** Tout marchand de la liste blanche
safe-auto (`src/admin/auto_merchants.py` : Kinguin 58, Gamivo 51, G2A 38, MMOGA 12, K4G 92,
Driffle 127, Instant Gaming 28, Eneba 19, Allyouplay 17, GameSeal 126, CJS-CDKeys 30 ; plus
Difmark 167 parqué) a son `src/merchants/<marchand>.py` qui expose un `MerchantConfig`
DÉCLARANT sa grammaire et ses hooks ; `src/matcher.py` et `src/console_keys.py` ne gardent
que le vocabulaire partagé et le pipeline. Le classifieur R45 embarquait encore les
grammaires d'URL MMOGA / Gamivo / Eneba (segments de catégorie, runs, segment de magasin en
tête) et des contrôles d'hôte (`mmoga.com` / `gamivo.com` / `eneba.com`) : cela sort.

- **Contrat** (`src/merchant_config.py`, `[R32]` / `[R45]`) — quatre membres optionnels de
  plus, fonctions pures de la ligne de feed, sans réseau, sans import du matcher :
  `console_url_families(url)` → familles déclarées par l'URL dans l'ordre (sous-ensemble de
  XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2), ou une chaîne de skip (« console:
  Xbox 360 (R45) », « console: PC-only Xbox Live key (R45) », « console: <MARKER> — not a
  game (R45) »), ou None (l'URL ne dit rien) — consulté SEULEMENT quand le titre ne déclare
  aucune famille ; `console_pc_declared(name, url)` → le marchand déclare PC / Windows à
  côté de la plateforme console (runs Gamivo `-pc` / `-windows`, run Eneba `-windows-`) —
  la phrase générique du titre (`/ Windows`, `PC/XBOX …`) reste générique ;
  `console_region_slot(name)` → le TEXTE de région écrit à côté de la phrase plateforme, tel
  quel (« US », « CA », « Europe », « United Kingdom », « Hong Kong », « EUROPE ») — la
  correspondance texte → base (uk / us / eu / global) ou label interdit reste dans
  `console_keys` (vocabulaire partagé) ; hook absent → lectures partagées de queue /
  crochets ; `console_noise: tuple[str, ...] = ()` → phrases marchandes retirées de
  `resolve_name` en plus des marqueurs partagés (« Download Code » MMOGA, « Digital Key » /
  « Digital Code » Driffle, « CD Key » Kinguin — la note « (valid until <Month> <Year>) »
  de Kinguin n'était PAS un bruit le matin : question ouverte, tranchée le soir même — voir
  « Décisions de Romain (14/09, soir) » en fin d'entrée). Le CONTRAT des hooks PC (`precheck` / `title_region` / `resolve_name` / `url_platform` +
  `url_platform_prefixes`, `url_platform_scan`, `offer_page_resolver`, `domain`,
  `url_ignore_substrings`) ne change pas ; les nouveaux fichiers en DÉCLARENT (ci-dessous).
- **Registre** — la liaison nom → module (`merchant_config()`) passe dans
  `src/merchants/registry.py`, importé par `src/matcher.py` (qui continue de l'exposer) ET
  par `src/console_keys.py`, sans import circulaire (`python3 -c "import src.matcher,
  src.console_keys, src.merchants.registry"` passe). L'entrée inline `"KINGUIN":
  MerchantConfig("Kinguin", domain="kinguin.net")` du matcher disparaît au profit de
  `kinguin.py`.
- **Classifieur** (`src/console_keys.py`) — sortent : `_parse_url_mmoga` /
  `_MMOGA_CATEGORY_RULES` / `_MMOGA_NON_GAME_CATEGORY_RE` (→ `mmoga.py`), `_parse_url_gamivo`
  et `_GAMIVO_LANG_TAIL_RE` (→ `gamivo.py`), `_parse_url_eneba` + le retrait du segment de
  magasin en tête (→ `eneba.py`), la sélection par hôte / nom du marchand dans `_parse_url`.
  Restent (vocabulaire partagé) : familles, pages, buckets, grammaire de TITRE (phrases
  entières, `X|S` ≡ `X/S` ≡ `XS`, « Series » nu, run de tête = nom, suffixe « Nintendo
  Switch 2 Edition »), marqueurs partagés de magasin / livraison et non-jeu (GAME PASS,
  cartes, ACCOUNT mot entier), table texte de région → base / label, lecture partagée des
  runs à tirets (`xbox-one`, `xbox-series-x-s`, `ps4-ps5`, `nintendo-switch(-2)`),
  `console_marker_in_url`, `console_page_identity`, `extract_console_pages`.
- **Six nouveaux fichiers + `common.py`** — `kinguin.py` (`domain` sorti du registre ;
  PC : `precheck` (code de région avant la phrase plateforme hors vocabulaire vendable →
  `forbidden region: <LABEL>` avant tout sondage ; `Account` / `Access` → skip catégoriel),
  `title_region` (le code « US » nu → Steam US explicite au lieu d'un GLOBAL implicite + slug
  `…-us` en 404), `resolve_name` (code + phrase + livraison + « (valid until …) » retirés →
  slug du jeu) — **pas de `url_platform`** (R32b, « ça marche aujourd'hui ») ; console :
  `console_url_families` (`-account` / `-online-account-activation` → non-jeu, runs
  partagés), `console_region_slot` (code majuscule avant la phrase plateforme),
  `console_noise = ("CD Key",)` — la note « (valid until <Month> <Year>) » n'était PAS un
  bruit le matin, question ouverte tranchée le soir : saisie, voir en fin d'entrée),
  `k4g.py` (PC : `precheck` dont, le matin, « Steam Altergift » → `skip category:
  ALTERGIFT` explicite (216 / 592, 0 candidat jamais — tranché le soir : Altergift = Steam
  Gift, saisi, voir en fin d'entrée), `title_region`, `resolve_name` ; console :
  `console_url_families` (run suivi d'un slug de région connu), `console_region_slot` (mot
  de région en toutes lettres avant la plateforme)), `driffle.py` (PC : `precheck` (pays
  entre parenthèses hors vocabulaire générique), `title_region` (1re parenthèse) ; console :
  `console_url_families` avec l'orthographe `xbox-series-xs`, `console_region_slot`,
  `console_noise` « Digital Key » / « Digital Code »), `gameseal.py` (`domain="gameseal.com"`,
  PC : `precheck` / `title_region` sur la queue ` - <RÉGION>` (NA / AU / BELGIUM), console :
  `console_url_families` (`xbox-360` → skip R45), `console_region_slot`), `allyouplay.py` et
  `cjs.py` (identité seule : `domain` `allyouplay.com` / `cjs-cdkeys.com` à confirmer au
  premier dry-run — un hôte faux échoue fermé —, `CONFIG.name = "CJS-CDKeys"` ; jamais
  balayés, aucun hook de grammaire inventé). `src/merchants/common.py` (nouveau) porte ce
  que plusieurs fichiers marchands partagent sans module générique : vocabulaire des mots de
  région (texte → base / label interdit, miroir des tables de `console_keys` et `gamivo.py`),
  chaînes de skip R45 (miroirs byte-exacts) et `make_config`. Fichiers existants
  complétés : `mmoga.py` (`console_url_families` catégories + Xbox 360 + cartes /
  abonnements, `console_region_slot` ` - EU` / `[EU]` / `(Steam Key EU)` / `EU Key`,
  `console_noise` « Download Code »), `gamivo.py` (`console_url_families` runs + `xbox-pc`
  seul → PC-only, `console_pc_declared`, `console_region_slot` queue `[<LANGS>] <Région>`,
  `console_noise` = la regex de queue de langue construite sur la liste ISO de Gamivo —
  sortie de `console_keys`), `eneba.py` (`console_url_families` = le slot juste avant le
  dernier marqueur `-xbox-live-key` / `-psn-key` / `-eshop-key`, segment de magasin en tête
  jamais une génération, `-pc-` avant le marqueur → PC-only, sans marqueur → None ;
  `console_pc_declared` ; `console_region_slot` = mot après « Key »), `g2a.py` (PC :
  `precheck` / `title_region` — la queue ` - <RÉGION>` est TOUJOURS un slot, hors vocabulaire
  → fail-closed ; console : `console_url_families`, `console_region_slot`),
  `instant_gaming.py` (`console_url_families` → None, documenté : une plateforme console lue
  sur la page IG → plateforme None → skip R32), `difmark.py` (`console_url_families` : chemin
  `/buy-console-account-…-account-<id>` → compte, non-jeu). Détail par marchand :
  `docs/MERCHANTS.md`.
- **Comportement** — classifieur consoles : mêmes familles, mêmes skips, même ordre (titre
  partagé → hook URL du marchand → lecture partagée), fail-closed partout (un hook qui
  renvoie None ne fait jamais deviner une famille ; un résultat de hook hors contrat →
  skip « merchant URL hook … — not entered (R45) »). Deux changements de LECTURE assumés :
  (1) le slot région Eneba est le texte après « Key » (2 lignes corrigées, voir Mesure) ;
  (2) la queue de langue Gamivo (« EN », « EN/PL/CS/RU/TR ») n'est plus un vocabulaire
  partagé : `resolve_name_of("Ravenswatch EN United Kingdom")` sans marchand donne
  « Ravenswatch EN », avec `Gamivo` « Ravenswatch » (le matcher n'utilise que la version
  avec marchand ; « Final Fantasy XV Global » garde « XV », l'ancienne regex partagée
  IGNORECASE retirait 2 lettres quelconques). Les hooks PC des fichiers Kinguin / K4G /
  Driffle / G2A / GameSeal changent des SORTIES (mesurées ci-dessous) : toujours un skip
  rendu explicite / plus tôt (aucun sondage AKS) ou une région plus étroite, jamais une
  ligne skippée qui devient saisissable sauf la classe Kinguin « <Jeu> US PC Steam » (Steam
  US sur le vrai slug au lieu d'un 404) et les DLC « … EU » (slug du jeu). Tests existants
  qui épinglaient l'EMPLACEMENT de la grammaire ou l'état « Kinguin générique », ajustés :
  `tests/test_matcher.py` `ConsoleReviewFixesR45Tests.test_generic_read_is_implicit_for_the_kinguin_mid_slug_code`,
  `…test_implicit_read_with_a_removed_region_word_is_refused`,
  `…test_precheck_returns_the_grammar_forbidden_region` (la branche console du matcher est
  exercée sur un marchand sans hook « Shop » ; une ligne Kinguin garde la réponse du fichier
  marchand, plus tôt et tout aussi fail-closed : `forbidden region: CANADA` avant la porte
  console, « US » explicite) et `MerchantConfigR32Tests.test_config_reads_migrated_flags`
  (« Kinguin n'a pas de precheck » → `MerchantConfig("Plain")`) ; `tests/test_console_keys.py`
  restructuré (18 lignes partagées, hooks via un faux marchand, test `tokenize` « aucun nom
  de marchand dans le code », ordres d'import, `SlugRead`) — les 5 exemples Gamivo de
  `ResolveNameTests` déménagent dans `tests/test_merchants_gamivo.py`.
- **Mesure** (14/09, lecture seule, sur les derniers lots sauvegardés : `runs/20260912-02000*`
  Kinguin / K4G / Driffle / G2A / Gamivo / MMOGA, `20260912-080120` Eneba,
  `20260715-151202` GameSeal ; aucune requête réseau) —
  *Classifieur consoles* : comptages par marchand et par motif IDENTIQUES avant / après
  (2 990 lignes consoles, 0 anomalie — MMOGA 388, Kinguin 365, Gamivo 572, K4G 135, Driffle
  112, G2A 42, Eneba 1 376 ; `diff` vide entre la mesure de référence prise AVANT la refonte
  et la mesure post-intégration, registre câblé). Signaux complets (familles, PC, skip,
  `resolve_name`, slot région) : 5 lignes / 2 990 diffèrent — 2 corrections Eneba par le
  slot région (« Dying Light Essentials Edition (Without DE) … EUROPE » : DE → GERMANY
  interdit devient eu ; « Truck Simulator Cargo Driver 2025 - USA (Windows/Xbox Series X|S)
  … EUROPE » : « not mapped » devient eu) et 3 slots K4G / Driffle (Luxembourg, Latvia,
  Lithuania) sur des lignes déjà non-jeu — aucune saisie ne change.
  *Lignes PC* — `precheck_skip` + `explicit_platform_from_url` / `explicit_platform` +
  `detect_region` + 1er slug, code du 14/09 vs code committé b6c96be (effet de cette
  entrée) et vs l'outcome enregistré du run :

  | Marchand | lignes (PC / consoles) | précheck | région | 1er slug seul | candidats touchés |
  |---|---|---|---|---|---|
  | Kinguin | 940 (575 / 365) | 34 — 30 régions interdites avant sondage (TR 10, SEA 7, NA 6, AU 2, DE 2, CA 1, ANZ 1, EU/UK 1, UAE 1, ZA 1, BR 1 : toutes finissaient en 404 / « no region id » / garde DLC) ; 1 relabel AFRICA → NORTH AMERICA ; 3 autres | 2 (« Metro Awakening US PC Steam CD Key » : GLOBAL implicite (2) → US (8), slug `metro-awakening` au lieu du 404 `metro-awakening-us`) | 30 (21 DLC EU en 404 `…-dlc-eu` → `…-dlc`, 5 garde DLC, 4 pré-skips) | 0 |
  | K4G | 592 (457 / 135) | 216 « skip category: ALTERGIFT » (143 étaient des 404, 35 mots en trop, 29 NORTH AMERICA, 3 BUNDLE, 2 AMERICAS, 2 DLC, 1 PASS, 1 no region id) | 0 | 12 | 0 |
  | Driffle | 464 (352 / 112) | 8 (2 V-Bucks (France) → FRANCE ; 6 Tinder SUBSCRIPTION → AUSTRIA / NETHERLANDS / BELGIUM / EGYPT) | 0 | 0 | 0 |
  | G2A | 806 (764 / 42) | 2 (GIFT CARD → SINGAPORE ; AFRICA → SOUTH AFRICA) | 1 (« Big Adventure: Trip to Europe 6 … Steam Gift - GLOBAL » : GIFT EU 259 lu dans le nom → GIFT 25) | 0 | 0 |
  | GameSeal (07/2026) | 1 610 (1 577 / 33) | 30 (NORTH AMERICA 27, AUSTRALIA 1, BELGIUM 2 — 404 / mots en trop / DLC / throttled avant) | 0 | 0 | 0 |
  | Gamivo | 762 (190 / 572) | 0 | 0 | 0 | 0 |
  | MMOGA | 723 (335 / 388) | 0 | 0 | 0 | 0 |
  | Eneba | 1 659 (283 / 1 376) | 0 | 0 | 0 | 0 |

  **0 candidat enregistré ne change de classe** (aucun « candidat → skip », aucun changement
  de région ou de plateforme sur un candidat). Lignes consoles en mode PAR DÉFAUT (sans
  `--consoles`) : le précheck marchand précède la porte console, « console » devient un
  motif explicite — Kinguin 211 (CANADA 84, AUSTRALIA 77, ACCOUNT 37, ARGENTINA 3, NORTH
  AMERICA 2, ROW 2, TURKEY 2, EU/UK 2, COLOMBIA 1, SOUTH AFRICA 1), K4G 7, Driffle 8, G2A 5,
  GameSeal 4 — même fail-closed, listes routées par `suggest_target_list` (le plan R35
  proposera ces déplacements ; à montrer à Romain). Écart vs l'outcome ENREGISTRÉ (ce que le
  prochain sweep verra en plus) = la dérive du code générique depuis le run : GameSeal 742
  lignes dont 674 « TOP-UP » → « TOP UP » (orthographe du motif) et 14 skips logiciels levés
  (R31), Gamivo 16 lignes PC (Tinder NL, NordPass FR / IT / ES, System Shock SEA → régions
  interdites, R46 du 12/09) et 307 lignes consoles (fuite corrigée le 12/09 après le run).
  *Tests* : 1 629 → 1 750 découverts (+121) ; modules ajoutés
  `tests/test_merchants_{mmoga,gamivo,eneba,kinguin,k4g,driffle,g2a,gameseal,misc,registry_expectations}.py`
  : « Ran 114 tests / OK » ; `tests.test_console_keys` (70) + `tests.test_matcher` (434) :
  « Ran 504 tests / OK » ; suite complète `python3 -m unittest discover -s tests -t .` :
  « Ran 1750 tests in 357.788s / OK (skipped=2) ». Preuves e2e (classifieur réel, corps de
  pages AKS sauvegardés, aucun réseau) : Kinguin « Hades US Xbox One / Xbox Series X|S CD
  Key » → XBOX/PC US 242 sur One 85102 + Series 85103 + PC 26712 ; « Hades CA … » →
  `forbidden region: CANADA` ; Gamivo « Hades EN United Kingdom » `…-xbox-series-pc-uk-standard`
  → XBOX/PC UK 240 (Series + PC) ; MMOGA « NBA 2K25 (Xbox One / Series X|S Download Code) -
  EU » sur pages simulées sans carte de régions → 24eu + 302 (avec la carte réelle de Hades →
  XBOX/PC EU 241 ×3) ; Eneba « Hades (Xbox Series X|S) XBOX LIVE Key EUROPE » → Series 241 +
  PC 241 ; Difmark « (Account) » → skip ACCOUNT ; Kinguin « Street Fighter 6 EU Nintendo
  Switch 2 CD Key » → SWITCH2 188436 / 99eu ; `src/console_keys.py` ne nomme aucun marchand
  hors docstring (test `tokenize`).
- **Docs** — MERCHANTS (règle en tête, table du contrat + 4 hooks consoles, une section par
  marchand : fichier / grammaire PC / grammaire console / hooks / statut, six nouveaux
  fichiers, table de statut au 14/09), EXECUTOR_RULES §4.10 (« Console hooks », registre,
  chaque marchand a son fichier) et §4.12.3 (« vocabulaire partagé dans `console_keys` +
  hooks par marchand » — le bloc *URL grammar* réattribué aux fichiers marchands, slot
  région et `console_noise`), README (layout `src/merchants/`, principe « one config file
  per merchant », liste des docs, roadmap R45), HANDOFF (état, règle, backlog).
- **Reste à faire** — dry-run des nouveaux fichiers (`scripts/10 --targets "Kinguin:58"
  --dry-run --consoles`, puis K4G / Driffle ; Allyouplay / CJS / GameSeal en `--dry-run` PC
  d'abord, jamais balayés), relever les grammaires manquantes (Allyouplay, CJS, GameSeal PC)
  et les déclarer dans leur fichier ; trancher la question ouverte restante (queue « EU/UK »
  = skip) — Kinguin « valid until » et K4G Altergift sont tranchées ci-dessous.
- **Décisions de Romain (14/09, soir) — « Kinguin valid until juin 2027 on rentre, Steam
  Altergift = Steam Gift on rentre sous gift tous les altergifts. »** Les deux questions
  ouvertes du matin sont tranchées : deux hooks R32e de plus dans le contrat
  (`src/merchant_config.py`), plomberie seule dans `src/matcher.py`, la grammaire dans les
  fichiers marchands (`src/merchants/kinguin.py`, `src/merchants/k4g.py`).
  - `guard_name(name) -> str` — le titre lu par les gardes d'identité (R01 mots AKS
    manquants, R16 mots en trop, R01b qualificatif dangereux) et `detect_edition` pour une
    ligne PC ; titre brut par défaut (aucun autre marchand ne change). `_pc_plan` l'appelle
    à la place de `offer.name` ; une réponse vide → titre brut ; le hook ne blanchit jamais
    un titre (les mots qu'il laisse sont comparés comme avant — `MerchantHookTests`).
  - `gift_delivery(name, url) -> bool | None` — le verdict « livraison gift » du marchand,
    consulté en premier par `_detect_region_parts` ; True / False l'emporte, None → lecture
    générique (segment d'URL `gift`, « GIFT » dans le titre). `detect_region` superpose
    comme avant le bucket GIFT de la plateforme (Steam 25 / gift_eu 259, Battle.net 570 /
    567) ; pas de gift_us / gift_uk → skip « no region id » inchangé ; green gift intact.
  - **Kinguin** : la note « (valid until <Month> <Year>) » est une date limite
    d'activation, pas un mot de produit — `guard_name` la retire (et elle seule) du titre
    des gardes, `resolve_name` la pèle (déjà), `console_noise = ("CD Key", VALID_UNTIL_RE)`
    (un `re.Pattern` : les lignes consoles avec la note résolvent aussi).
    `OPEN_QUESTION_VALID_UNTIL` retiré, décision dans la docstring. Seule la forme
    « (valid until <Month>[,] <Year>) » existe dans le corpus (89 / 89 lignes) ; toute autre
    orthographe reste dans la garde (fail-closed).
  - **K4G** : le précheck `skip category: ALTERGIFT` du matin est retiré ; `gift_delivery`
    → True pour le mot entier ALTERGIFT (insensible à la casse) ; `guard_name` et
    `resolve_name` retirent le mot « Altergift » (et lui seul) — R16 ne le compte plus, le
    slug est celui du jeu (`seafrog`, plus `seafrog-steam-altergift`) ; plateforme STEAM
    (`explicit_platform` colloque déjà STEAM et ALTERGIFT) ; région = bucket GIFT Steam sur
    la base du titre / de l'URL : GIFT (25) sans région ou Global, GIFT EU (259) pour
    Europe, base US / UK → « no region id for STEAM/GIFT US » (fail-closed, inchangé), North
    America / Americas → `forbidden region` inchangé ; bundles, pass, R43 inchangés.
    `OPEN_QUESTION_ALTERGIFT` / `SKIP_ALTERGIFT` retirés.
  - **Rejeu** (lecture seule, sans réseau, `runs/20260912-020001-auto-kinguin-s58-p1..10`
    et `20260912-020000-auto-k4g-s92-p1..7`, lignes dédoublonnées par offer_id ;
    `precheck_skip` + plateforme + `detect_region` + 1er slug du code du soir ; l'outcome
    AKS est celui enregistré par le run) :

    | Lignes | total | passent précheck + bucket | plateforme / région / 1er slug | restent en skip | attendu côté AKS (run enregistré) |
    |---|---|---|---|---|---|
    | Kinguin « (valid until …) » | 79 | 76 | STEAM GLOBAL (2) implicite ×76, slug du jeu (inchangé : `resolve_name` pelait déjà la note) | 3 — ROW ×2, BUNDLE ×1 | **61 candidates** (page résolue, la note pour seuls mots en trop) ; 13 restent en 404 (même slug) ; 1 garde DLC (R43) ; 1 « missing AKS words: ['VR'] » |
    | K4G « Steam Altergift » | 218 | 182 | STEAM GIFT (25) ×120 explicite (URL `-steam-global-`), STEAM GIFT EU (259) ×62 ; slug du jeu (183 / 183 slugs des lignes non pré-skippées changent vs le run du 12/09, slug générique : `…-steam-altergift` → jeu ; vs le fichier K4G du matin — 90378a6 —, 2 slugs seulement) | 36 — NORTH AMERICA 29, BUNDLE 3, AMERICAS 2, PASS 1, GIFT UK sans bucket 1 | 144 étaient des 404 sur `…-steam-altergift` → slug du jeu **à sonder au prochain dry-run** ; 36 gardent d'autres mots en trop (R16 : « Plus Expansion Pack », « Treasure from Heaven », « Episode 3 »…) ; 2 garde SEASON PASS (R43) ; 0 candidate immédiate (aucune ligne n'avait « ALTERGIFT » pour seul mot en trop) |

    Exemples Kinguin (→ STEAM GLOBAL 2 implicite, slug) : GreedFall (`greedfall`), Time to
    Morp, Factory Town, Vampyr, Eldest Souls, Idle Colony, MR FARMBOY, Soulstice Deluxe
    Edition (`soulstice-deluxe-edition`, Deluxe réconciliée sur la page), For The King II,
    Keylocker | Turn Based Cyberpunk Action (404 avant, même slug) ; skips : Dead Cells RoW
    ×2 (`forbidden region: ROW`), SUPERHOT ONE OF US BUNDLE (BUNDLE). Exemples K4G (→ STEAM,
    bucket, slug) : Seafrog (GIFT 25, `seafrog`), True Fear: Forsaken Souls Part 3 (GIFT 25),
    Wirm (GIFT 25), Kingdom of Night Europe (GIFT EU 259, `kingdom-of-night`), Stronghold:
    Warlords Special Edition / … Europe (GIFT 25 / GIFT EU 259), Mato Anomalies - Treasure
    from Heaven / … Europe (GIFT 25 / 259 ; R16 « TREASURE FROM HEAVEN » sur la page Mato
    Anomalies), Sonic Origins - Plus Expansion Pack / … Europe (R16) ; skips : Mato Anomalies
    North America, Kingdom of Night North America, Cardaclysm North America, Deathbound
    Ultimate Edition North America… (`forbidden region: NORTH AMERICA`), Middle-earth: The
    Shadow Bundle Europe (BUNDLE), Far Cry 6 Game of the Year Upgrade Pass (PASS). **0
    candidate enregistrée ne change** sur les deux lots.
  - Tests : `tests/test_merchants_kinguin.py` (garde / slug / bruit console sur lignes
    réelles ; pipeline Vampyr → STEAM GLOBAL (2) Standard (1) implicite, Soulstice → Deluxe
    (10), contraste avec l'entrée générique d'avant ; R01b / R16 intacts),
    `tests/test_merchants_k4g.py` (`AltergiftPipelineTests` : Thief Simulator Europe → GIFT
    EU 259, sans région → GIFT 25 implicite, `-steam-global-` → GIFT 25 explicite, US / UK →
    « no region id », lignes du lot, règles conservées), `tests/test_matcher.py`
    `MerchantHookTests` (les deux hooks sur un faux marchand : blanchiment impossible,
    réponse vide, False l'emporte, green gift intact). `python3 -m unittest
    tests.test_merchants_kinguin tests.test_merchants_k4g tests.test_matcher
    tests.test_console_keys tests.test_merchants_registry_expectations` : « Ran 541 tests /
    OK ».
  - Docs : MERCHANTS (contrat + Kinguin + K4G + statut), EXECUTOR_RULES §4.4 / §4.10 / §11,
    README (six hooks), AGENTS « Reviewed decisions » (deux puces — un audit ne doit pas
    re-signaler ces saisies).
- **Correctifs de revue sur les deux décisions (14/09, soir — revue adverse de leur mise en
  œuvre ; fail-closed partout, la grammaire reste dans `src/merchants/<marchand>.py`)** :
  - **[1, haut] K4G — le slug doit être d'accord avec « Altergift »** : `gift_delivery`
    ignorait son argument `url`. Une ligne du lot (offre 101030313, `…-k4g-s92-p3`, « Trine
    5: A Clockwork Conspiracy Steam Altergift » sur `…-steam-global-instant-cd-key-48V2PFDZ`
    — 217 / 218 autres slugs Altergift portent `-alter-gift-`) serait passée en STEAM GIFT
    (25) alors que son URL dit clé (GLOBAL 2) : la classe de bucket ne se lit pas sur la
    ligne. Désormais `k4g.altergift_verdict(name, url)` (lu par `precheck` ET
    `gift_delivery`) : slug `-altergift-` / `-alter-gift-` → « gift » (le hook vaut True) ;
    slug `cd-key` sans segment altergift → « K4G delivery conflict: title Altergift but URL
    says cd-key (no altergift segment) — not entered (2026-09-14) », avant tout sondage ; slug
    sans aucun segment de livraison (hors grammaire d'URL) → même refus ; conflit miroir
    (titre « CD Key », slug `-alter-gift-`, 0 ligne) → refus aussi (la lecture générique
    `-gift-` aurait rangé une clé sous GIFT 25). Un Altergift refusé n'est jamais lu GIFT
    par `detect_region` (le hook répond None : le marchand ne s'en porte pas garant).
  - **[2, bas] Kinguin — `VALID_UNTIL_RE` ancré en fin de titre** (`\s*$`, comme le motif
    d'avant la décision ; 158 / 158 lignes du corpus, doublons compris, sont en fin de titre)
    : « Vampyr (Valid Until March 2027) PC Steam CD Key » n'est plus tronqué au milieu — la
    note reste dans la garde → « extra words: ['VALID', 'UNTIL', 'MARCH', '2027'] »
    (fail-closed). `TITLE_RE` était déjà ancré ; `console_noise` inchangé (le classifieur
    applique le motif au titre brut, note encore en fin).
  - **[3, bas] Kinguin — « on rentre sous gift tous les altergifts » vaut aussi pour la
    livraison « Altergift » de Kinguin** (1 ligne / lot, « Sons Of The Forest DE PC Steam
    Altergift » — GERMANY de toute façon ; une ligne non interdite lisait STEAM GLOBAL (2)
    puis R16 « extra words: ['ALTERGIFT'] ») : `kinguin.gift_delivery` → True pour « <Jeu>
    [<CODE>] PC Steam Altergift » (GIFT 25 / GIFT EU 259 ; US / UK → « no region id »),
    `guard_name` / `resolve_name` retirent le mot ; mêmes garde-fous que K4G — le slug (souvent
    tronqué → silence accepté) ne doit pas contredire (`-cd-key` / `-key` / compte → « Kinguin
    delivery conflict »), Altergift hors Steam → refus ; les lignes « Steam Gift » gardent la
    lecture générique (hook None).
  - **[4, bas] K4G / Kinguin — « Steam Altergift = Steam Gift » est Steam seulement** :
    `gift_delivery` était agnostique de la plateforme (« Seafrog Battle.net Altergift » →
    BATTLENET GIFT 570 / 567). 216 / 216 lignes en grammaire disent « Steam » (les 2 hors
    grammaire « … Steam Europe Altergift » aussi, toujours saisies GIFT EU 259) ; un Altergift
    dont la phrase magasin n'est pas Steam, est ambiguë (« Steam / Epic Games Altergift ») ou
    absente → « … Altergift outside the Steam collocation (title's store phrase is not
    Steam) — not entered (Romain 2026-09-14: « Steam Altergift = Steam Gift ») », jamais le
    bucket gift d'une autre plateforme, jamais une clé simple.
  - **[5, info]** la phrase « 183 / 183 slugs … changent » ci-dessus est relative au run du
    12/09 (slug générique) — vs le fichier K4G du matin (90378a6), 2 slugs seulement (les deux
    lignes hors grammaire). `docs/HANDOFF.md` (l. 283-284, `OPEN_QUESTION_VALID_UNTIL` /
    `OPEN_QUESTION_ALTERGIFT` encore listées ouvertes) reste à corriger par son propriétaire :
    les deux sont tranchées, les symboles retirés.
  - **Rejeu** (lecture seule, 6 314 lignes de tous les lots du 12/09, code du soir avant /
    après correctifs) : **2 lignes changent, 0 candidate** — K4G 101030313 Trine 5 (précheck
    None → conflit ; le run avait enregistré un 404) et Kinguin 101042255 Sons Of The Forest
    DE (bucket lu GLOBAL 2 → GIFT 25, garde sans « Altergift » ; précheck GERMANY inchangé).
  - Tests (une régression par constat) : `tests/test_merchants_k4g.py`
    `AltergiftGatesTests` (Trine 5 : refus avant sondage, jamais GIFT 25 ; même titre sur le
    slug habituel → GIFT 25 ; conflit miroir ; Battle.net / Epic / GOG / sans plateforme /
    PS5 → refus ; les 2 lignes « Steam Europe Altergift » entrent ; `url_delivery`),
    `tests/test_merchants_kinguin.py` `AltergiftTests` (GENERIC → R16 « ALTERGIFT », CONFIG →
    STEAM GIFT 25 implicite ; EU → 259 ; US → no region id ; DE → GERMANY ; « Steam Gift »
    inchangé ; conflit `-cd-key`, slug tronqué accepté, hors Steam) + note au milieu du titre
    non retirée (garde, `strip_valid_until`, pipeline R16), `tests/test_matcher.py`
    `RulingGatesLiveRegistryTests` (registre réel). `python3 -m unittest
    tests.test_merchants_kinguin tests.test_merchants_k4g tests.test_matcher
    tests.test_console_keys` : « Ran 548 tests / OK » (536 avant).

## 2026-09-14 — Consoles R45 : correctifs de la revue adverse, famille Switch 2, décision P1

**Décision de Romain (14/09) — P1 tranchée** : « clé PS5 seule = page PS5 seulement, pareil
pour Xbox Series, PS4, Xbox One, Switch et Switch 2 ». La politique « déclaration marchande ∧
page AKS » est donc DÉFINITIVE : une plateforme déclarée seule → sa page seulement, une
déclaration cross-gen (« PS4 / PS5 », « Xbox One / Series X|S ») → les deux pages ; jamais de
page sœur ajoutée (AGENTS.md « Reviewed decisions », EXECUTOR_RULES §4.12 P1 / §12). Le
commutateur « page seule » (`SECOND_PLATFORM_POLICY`) est retiré des docs — il n'a jamais
existé dans le code. P2-P5 restent ouvertes.

**Switch 2 saisissable — famille `SWITCH2`.** Les pages produit AKS Switch 2 existent (kind
`nintendo-switch-2` : « Street Fighter 6 Nintendo Switch 2 » id 188436, « ELDEN RING Tarnished
Edition Nintendo Switch 2 » id 188441 ; corps sauvegardés dans le scratchpad R45) et leurs
offres utilisent le **bucket de la famille NINTENDO** (carte des régions `{99: GLOBAL}`, prix en
région 99, `activationPlatform nintendo-eshop`) : la page porte la plateforme, le bucket la
région. `SWITCH2` devient une famille (`CONSOLE_PAGE_KIND['SWITCH2'] = 'nintendo-switch-2'`,
mêmes ids de bucket que SWITCH : 99 / 99eu / 99us / 992 ; `REGION_IDS` / `PLATFORM_LABEL` la
reçoivent par les merges existants) ; le skip « console: Switch 2 has no AKS bucket (R45) » est
retiré. Les lignes Switch 2 du dernier lot (Kinguin 12, K4G 12, G2A 1, Driffle 1) deviennent
saisissables sur leur page `nintendo-switch-2`. Tests : cible SWITCH2 → page
`nintendo-switch-2`, bucket 99 / 99eu ; l'onglet Switch 2 d'Elden Ring pointe vers « ELDEN RING
Tarnished Edition Nintendo Switch 2 » → skip d'identité, jamais saisi.

**Correctifs de la revue adverse du 12/09 (4 lentilles) — tous traités :**
- **[critique] Région de la branche console** (`src/matcher.py`). La moitié Gamivo du finding
  était RÉFUTÉE (le hook `title_region` R46 est porté par `detect_region_base` : « Ravenswatch
  EN United Kingdom » + `…-xbox-xboxoneseries-uk-standard` → UK, buckets 226 / 305 — test) ; la
  moitié Kinguin / K4G / Driffle / G2A / Eneba tenait (« Hades US Xbox One / Xbox Series X|S CD
  Key » → GLOBAL implicite : 37 lignes US, 150 lignes CA/AU passaient). Le classifieur expose
  désormais le SLOT région de chaque grammaire (`ConsoleSignal.region_base` /
  `region_label` / `region_words`) et le matcher applique, dans l'ordre : `precheck_skip` →
  `forbidden region: <LABEL>` dès qu'une région déclarée n'est pas vendable (CA, AU, TR, AR, ZA,
  Hong Kong…) ; `_console_plan` → la base grammaticale fait autorité ; sinon la lecture
  générique quand elle n'est PAS implicite ; les deux existent et diffèrent → skip « console:
  region contradiction (title/grammar vs URL) — not entered (R45) » ; lecture implicite alors
  qu'un mot de région a été retiré du titre → skip « console: merchant region '<mot>' not
  mapped to a sellable base — not entered (R45) » ; aucun mot de région → GLOBAL implicite comme
  avant. Jamais un GLOBAL implicite pour une clé verrouillée.
- **[moyen] R44 sur la branche console** : le plan garde le label de BASE (`_Plan.base_label`) et
  `match_offer` lance `region_phrase_in_aks_name` dessus, contre l'identité de page (suffixe
  plateforme retiré) ; la base grammaticale vaut hook marchand (pas de second-guess). « Air Force
  United States Pacific Xbox One » → skip R44 ; avec « US » déclaré → 24us.
- **[moyen] Gate multi-cibles ≠ échec** (`src/submitter.py`) : une entrée gated
  `multi_target_unsupported_until_modal_verified` seule n'appelle plus `guard.record_result`,
  n'alimente ni la série des 10 échecs consécutifs ni le StepGuard / BlockLedger, et est comptée
  dans `gated_multi_target` (nouveau compteur du résultat / `submit_plan.json`). 12 candidats
  bi-cibles puis un PC → le PC est traité, `stopped` None, `gated_multi_target` 12 (test ; un
  blocker réel — select absent — arrête toujours à 10). `scripts/10_data_entry_auto.py` refuse
  `--consoles` sans `--dry-run` (`parser.error("--consoles requires --dry-run until the
  per-target modal is observed (R45)")`).
- **[bas] Identité de page** : la comparaison plie les apostrophes (`_identity_tokens`) — « DreamWorks
  Spirit Lucky's Big Adventure » (page PC) = « DreamWorks Spirit Luckys Big Adventure Nintendo
  Switch » (faux skip réel du dry-run MMOGA du 12/09).
- **[bas] Motif R19 console** stampé « (R19, R45) » → `feed_status` le classe consoles, plus
  `stub_page` (regex `_R45_STAMP_RE`).
- **[bas] RANDOM** : un mot de plateforme CONSOLE (XBOX / PLAYSTATION / PSN / NINTENDO / SWITCH /
  PS4 / PS5) toléré entre RANDOM et GAME / KEY / ITEM (« 1 Random Xbox Game … » Driffle → pré-skip
  RANDOM) ; jamais STEAM / PC (« Lost in Random Steam Key » reste un jeu).
- **[bas] Gardes throttle** : le garde des pages consoles est `_ThrottleGuard(shared=<garde
  principal>)` — un seul compteur consécutif, une seule grâce, un seul `stats` : le sweep
  s'arrête après THROTTLE_MAX_CONSECUTIVE_UNRELIABLE sondes instables toutes sources confondues
  (avant : 2×).
- **[bas] Validation** : un id `None` dans une cible → `ValidationError("malformed target entry
  (R45): …")`, jamais « None » dans l'empreinte.
- **[haut] Comptes Difmark** et **[bas] « Xbox One/Series » sans X|S / jeton de tête faisant
  partie du nom** : corrigés dans le classifieur (`src/console_keys.py`, seconde session — voir
  MERCHANTS « Difmark » ; le compte n'est jamais une clé Switch). Détail : ACCOUNT mot entier
  n'importe où dans le titre, chemin `/buy-console-account-` ou suffixe `-account(-<id>)` →
  « console: ACCOUNT — not a game (R45) » ; « Xbox One/Series » (aussi « & », « , », « and »,
  entre parenthèses) normalisé en « Series X|S » avant l'analyse → (XBOX_ONE, XBOX_SERIES) ;
  un jeton SERIES / ONE encore collé à un séparateur après retrait de la phrase → nouveau skip
  « console: unparsed platform residue (R45) » (« (Series) » seul et équilibré = nom, « Get Them
  Out! (Series) ») ; un run console qui OUVRE le titre suivi d'un mot ordinaire = nom du jeu
  (« Nintendo World Championships », « Nintendo Switch Sports » : gardé dans `resolve_name`,
  jamais une déclaration ; seule la grammaire d'URL décide, les jetons du nom retirés du début
  du slug) ; « <Jeu> - Nintendo Switch 2 Edition » = suffixe de NOM, et s'il contredit la
  plateforme déclarée → nouveau skip « console: product name suffix '<Plateforme> Edition'
  contradicts the declared platform <FAM> — not entered (R45) » ; slot région lu depuis les
  mêmes runs que `resolve_name` (`resolve_name_and_regions`), deux bases vendables différentes
  dans un slot → `region_words` seul renseigné → skip côté matcher. 64 tests
  `tests/test_console_keys.py` (36 avant). Les deux nouveaux motifs portent le préfixe
  `console:` → famille consoles dans `feed_status`.
- **Mesure R46 Gamivo (14/09)** : 95 lignes passent le précheck — STEAM 61 / BATTLENET 4 / EA 2 /
  GOG 1 ; 24 lignes butent encore sur le skip générique « language restriction » (préexistant).
- **Docs** : DATA_CONTRACTS — les `targets` de `candidates.json` sont IMBRIQUÉES (`region:
  {label, id}`, `edition: {label, id}` ; les deux exemples JSON corrigés ; la forme à plat n'existe
  que dans `submit_plan.json` / `validation.template.json`), faits BOM (région 306 seule ;
  éditions 337, 452, 480, 573, 1155, 1448, 1583, 4bo, 5bo + clé `"\ufeff1380"`),
  `gated_multi_target`, SWITCH2 ; EXECUTOR_RULES §4.12 (P1 tranchée, Switch 2, règles région,
  série gate, `--consoles` ⇒ `--dry-run`, « aucune SAISIE console sans le flag » mais le scan
  d'URL reclasse 569 lignes Gamivo par lot en `console`, placeholder `<FAMILY>/<LABEL>`,
  `extract_page_platform` = plateforme de l'onglet actif, `detect_region` /
  `detect_region_base` lisent tous deux `_detect_region_parts`, carve-out `InspectSubmitter`
  en §6, §10 ligne SWITCH2, §12 P1 fermée) ; AGENTS.md « Reviewed decisions » (cibles console =
  plateformes déclarées seulement) ; MERCHANTS (slot région lu par le classifieur pour Kinguin /
  K4G / Driffle / G2A / Eneba, règle compte Difmark, Switch 2 saisissable, mesure R46) ; README ;
  HANDOFF (état, prochaines étapes, 1629 tests).
- **Reste à faire** : observer le nouveau modal (`--inspect`) → remplissage par cible ; réponses
  de Romain sur P2-P5 ; correction manuelle de Riders Republic ; dry-run consoles MMOGA / Kinguin
  (`--consoles --dry-run`) pour mesurer.

## 2026-09-12 — Consoles R45 — préparation (pages consoles, classifieur, cibles multiples, gate submit)

Romain : l'outil AKS feed va permettre d'**overwriter la région (= région/plateforme) et
l'édition par page cible** — une clé PS5 ajoutée sur la page PS5 ET sur la page PS4 (région
overwritée → PS4), une clé Xbox sur Xbox One, Xbox Series X et PC (PC SEULEMENT pour les jeux
Xbox Play Anywhere). Le chantier « PARKED » du 11/09 est rouvert : **préparé, verrouillé,
désactivé par défaut**. Rien ne change pour les sweeps safe-auto sans `--consoles`.

**Mesure réelle (2026-09-12, lecture seule, `03_match --consoles` sur les 388 lignes consoles
MMOGA du lot 20260912-020001) : 182 candidats / 206 skips.** Candidats : One+Series 42,
Switch 41, Series 32, One+Series+PC (Play Anywhere) 27, Series+PC 22, One 10, One+PC 6, PS5 2 ;
buckets EU majoritaires (302 ×53, 241 ×39, 24eu ×37, 99eu ×30). Skips : 37 catégories
(monnaies, bundles), 22 DLC console (P5), 30 non-jeu (PSN/Game Pass/eShop/Plus/Live), 17 sondes
AKS instables, 14 sans page AKS, 27 « pas de page AKS pour une famille déclarée » (P1 :
Skull & Bones, Starfield… déclarés One/Series par MMOGA alors qu'AKS n'a pas la page One),
13 mots en trop (packs de monnaie, éditions « Vault »/« Champions »), 4 PS5 EU sans bucket
(P3), 2 éditions absentes d'une page cible, 2 identités (« System Shock Remake Xbox One »,
apostrophe « Lucky's »/« Luckys » — faux skip à plier).

**Revue adverse (2026-09-12, 4 lentilles, réfutation partielle — session Max coupée avant le
lot de correctifs) — findings CONFIRMÉS, NON corrigés à ce commit ; le chemin `--consoles` est
OFF par défaut et documenté « dry-run seulement » tant qu'ils ne sont pas traités :**
- **[critique — chemin `--consoles` seulement]** la branche console lit la région avec le
  scan générique : les codes Kinguin/K4G placés AVANT la phrase plateforme (« … US Xbox One /
  Xbox Series X|S CD Key ») ne sont pas lus (implicit GLOBAL : 37 lignes US du dernier lot) et
  les codes CA/AU/TR/AR/ZA/NA/CO ne sont pas des skips « forbidden region » (150 lignes CA/AU
  → GLOBAL implicite) ; Driffle « (Hong Kong) », « European Union » idem. Gamivo est couvert
  par R46 (hook `title_region`, vérifié par le réfuteur). Correctif prévu : le classifieur
  expose `region_base` / `region_label` (lus dans le slot région de chaque grammaire) et le
  matcher refuse une lecture implicite quand un mot de région a été retiré du titre.
- **[haut]** Difmark « <Jeu> (Account) Standard Edition » (URL `buy-console-account-…-account-<id>`)
  classé comme clé Switch (compte entré comme clé) — `_non_game_marker` doit lire « Account »
  n'importe où dans le titre et le préfixe d'URL Difmark.
- **[moyen]** R44 (phrase de région = identité) est mort sur la branche console (le label de
  bucket n'est pas un label de région) — garder le label de base dans le plan.
- **[moyen]** une entrée gated `multi_target_unsupported_until_modal_verified` compte comme un
  échec : 10 entrées gated consécutives arrêtent le run et le sweep (`ten_consecutive_failures`),
  y compris en dry-run ; correctif prévu : skip conçu (compteur `gated_multi_target`) et
  `scripts/10 --consoles` refusé sans `--dry-run`.
- **[bas]** « Xbox One/Series » sans « X|S » → seule XBOX_ONE (résidu « /Series » → skip R16 par
  accident) ; jeton de tête faisant partie du nom (« Nintendo World Championships ») retiré du
  `resolve_name` (faux skip R01) ; « 1 Random Xbox Game » échappe au pré-skip RANDOM ; un id
  `None` dans une cible secondaire donne un fingerprint « None » (à refuser) ; deux gardes
  throttle indépendants doublent le budget de sondes instables avant `AksThrottled` ;
  candidats console : override région seule vers un bucket console avec plateforme STEAM
  accepté (asymétrie préexistante).
- **[docs]** DATA_CONTRACTS décrit les cibles de candidates.json à plat alors que
  `Target.to_dict()` les écrit imbriquées (`region: {label, id}`) ; « les sweeps se
  comportent exactement comme avant sans `--consoles` » est faux (le scan console de l'URL
  reclasse 569 lignes Gamivo par lot en « console ») ; HANDOFF « 1353 tests » périmé ; P1 est
  plus étroit que l'exemple littéral de Romain (clé PS5 seule → PS5 seulement) et
  `SECOND_PLATFORM_POLICY` n'existe pas dans le code ; motif R19 console classé `stub_page`.

- **Pages consoles découvertes** (lecture seule, UA AKS/Staff) : le constat (a) du 11/09 était
  faux — la sonde avait utilisé une mauvaise grammaire d'URL (`…-xbox-series-x-…-cd-key-…`). AKS
  a des pages produit consoles séparées `buy-<slug>-<kind>-compare-prices/` (kind `ps4` / `ps5`
  / `xbox-one` / `xbox-series` / `nintendo-switch` / `nintendo-switch-2` ; PC = `cd-key`),
  chacune avec son `data-product-id`, son nom (« Hades PS5 »), sa carte des régions, ses éditions
  (Hades : PC 26712, PS5 85105, PS4 85104, Xbox Series 85103, Xbox One 85102, Switch 47979). La
  barre d'onglets `aks-offer-tabulations` de chaque page liste les plateformes du jeu (un onglet
  peut pointer vers un AUTRE produit : Elden Ring → « Elden Ring Tarnished Edition Nintendo
  Switch 2 »). Play Anywhere est vérifiable sur la page PC (« Xbox Play Anywhere » dans
  `official platforms` : Forza Horizon 5 et Hades oui ; Street Fighter 6 et Elden Ring non) ;
  les offres PA vivent sous les buckets XBOX/PC (306/241/242/240) sur la page PC ET sur les
  pages Xbox One / Series (Hades : 306×4 sur les trois). Catalogue du modal (867 buckets,
  identiques sur les 9 catalogues des 10-12/09) : table famille × base région dans
  EXECUTOR_RULES §10 ; pas de bucket Switch 2, pas de PS5 EU/US/UK, pas de gift console ; ids
  non numériques (`88ps5h`, `24eu`) résolus par le chemin id de `resolve_catalog_id` (vérifié) ;
  label 306 avec BOM U+FEFF en tête (requête Selectize tapée sans BOM).
- **Classifieur `src/console_keys.py`** (pur, sans import du matcher) :
  `classify_console(name, url, merchant) -> ConsoleSignal | None` — familles DÉCLARÉES
  (XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH), `pc_declared`, `resolve_name` (titre sans
  marqueurs console / store / région, édition conservée), `skip_reason` « console: … (R45) » ;
  grammaire titre (mot entier, `X|S` ≡ `X/S` ≡ `XS`, cross-gen « Xbox One / Series X|S »,
  « PS4 / PS5 ») et grammaire URL par marchand (catégories MMOGA, run Gamivo après le slug,
  segments Eneba, générique ailleurs) ; skips fail-closed : Switch 2 (pas de bucket), Xbox 360,
  non-jeu (Game Pass, cartes, abonnements, Account / Access), clé PC-only via Xbox Live, console
  sans génération déclarée. Aussi `console_page_identity`, `extract_console_pages` (barre
  d'onglets → {kind: url}), `extract_page_platform`, `console_marker_in_url` ; tables
  `CONSOLE_REGION_IDS` / `CONSOLE_REGION_LABELS` / `CONSOLE_PLATFORM_LABEL` / `CONSOLE_PAGE_KIND`.
- **Matcher — candidats multi-cibles** : `REGION_IDS` / `PLATFORM_LABEL` étendus aux familles
  console ; `precheck_skip(consoles=…)` ; `AksResolution.console_pages` / `page_platform` ;
  `resolve_aks_url` (GET cadencé d'une page connue) ; branche console de `match_offer` : région
  de base (`detect_region_base`), page ancre (PC, sinon page console de la famille primaire),
  identité par le suffixe du nom de page, Play Anywhere = vérité de la page PC, une page cible
  vérifiée PAR famille déclarée (déclaration marchande ∧ page AKS — **jamais partiel**),
  édition vendue sur chaque page ; `Candidate.targets` (`Target`, toujours présent, une cible
  pour le PC), empreinte `primaire|+id:région:édition,…` au-delà d'une cible, ligne « ↳ » par
  cible dans le rapport ; `scripts/03_match.py --consoles` → `match_meta.json["consoles"]` ;
  `scripts/10_data_entry_auto.py --consoles` (défaut désactivé).
- **Submitter — gate fail-closed** : `entry["targets"]` normalisé (ancien `candidates.json` →
  cible primaire), résolution catalogue de CHAQUE cible ; **> 1 cible → `ready=False`, blocker
  `multi_target_unsupported_until_modal_verified`** (« la saisie multi-cibles / overwrite par
  cible attend l'observation du nouveau modal (--inspect) — R45 ») — jamais « la première cible
  seulement » (une saisie partielle consomme la ligne et perd la 2e plateforme) ; une cible =
  chemin actuel inchangé ; `region_query` / `edition_query` sans U+FEFF ; dry-run : `would_submit`
  liste toutes les cibles ; validation : même empreinte, `targets` dans le template, surcharge
  refusée sur un candidat multi-cibles (`bad_override`) ; console : bloc « N cibles (R45) »
  dans la cellule produit, selects désactivés ; `feed_status` : `console`, `console: …` et toute
  raison suffixée `(R45)` dans la famille consoles.
- **Fuite Riders Republic + fix URL** : le garde console ne lisait que le TITRE ; Gamivo (569 des
  572 lignes consoles) et Eneba portent la plateforme dans l'URL seule. Run
  `20260911-162100-auto-gamivo-s51-p28` : « Riders Republic Premium Edition United States »
  (`gamivo.com/product/riders-republic-xbox-xbox-one-series-us-premium`) saisi PUBLISHER GLOBAL(1)
  Premium(34), `created: 1` — une clé Xbox One/Series US est en ligne sur la page PC de Riders
  Republic (AKS 50562), **à corriger à la main**. Fix : `console_marker_in_url` dans
  `precheck_skip`, **actif dans tous les modes** (`--consoles` ou non).
- **Docs** : EXECUTOR_RULES §4.3 (correction du constat (a), renvoi), **§4.12** (règle complète,
  politiques P1-P5 à confirmer par Romain), §6 (cibles multiples), §10 (buckets consoles), §12
  (questions) ; DATA_CONTRACTS (`targets`, empreinte, `match_meta.consoles`, blocker, chemin id +
  BOM) ; MERCHANTS (grammaire console par marchand, volumes du dernier lot : MMOGA 388/723,
  Kinguin 365/940, Gamivo 572/762, K4G 135, Driffle 112, G2A 42, Eneba 1 376/1 659 dont 704 sans
  génération) ; README (`--consoles`, roadmap) ; HANDOFF (état, prochaines étapes, questions).
- **Reste à faire** : `--inspect` sur le nouveau modal de Romain → ajout du remplissage par cible
  (overwrite région / édition) ; dry-run consoles MMOGA / Kinguin (`--consoles --dry-run`) pour
  mesurer ; correction manuelle de Riders Republic ; réponses de Romain sur P1-P5.
- **Gamivo `[R46]` — grammaire titre + URL, quatre hooks de config marchand** (même jour, après
  le lot `20260912-020000`) : les 6 offres Gamivo créées le 11/09 sont TOUTES des `… United
  States` saisies **Publisher (1) GLOBAL implicite / Standard** — cinq clés Steam verrouillées US
  (`…-pc-steam-us-…`) : 101042269 → 84896 Tiny Tina's Wonderlands, 100395414 → 31894 My Hero
  One's Justice 2, 100398623 → 29681 Age of Empires II Definitive Edition, 100398639 → 3021
  Farming Simulator 15, 100398707 → 2614 Stronghold HD (**à corriger à la main : Steam / US**) ;
  la sixième, 100728683 → 50562 Riders Republic, est la clé Xbox de la fuite console ci-dessus.
  Cause : la grammaire actuelle de Gamivo met l'ÉDITION après le code région
  (`…-pc-steam-us-standard` — le slot final P2-6b ne se déclenche jamais), la région du titre est
  une queue sans séparateur (`Ravenswatch EN United Kingdom`) que `detect_region` ne lit pas, et
  le titre ne nomme jamais la plateforme (R27 → Publisher dès que la page liste Direct
  Publisher). Fix : `src/merchants/gamivo.py` — `title_region` (United Kingdom / United States /
  EU / Global → uk / us / eu / global), `precheck` (autre queue → `forbidden region: <LABEL>` ;
  sans queue, le code URL après le run : interdit / inconnu → skip, `us` / `uk` seulement dans
  l'URL → skip explicite R46, `eu` / `global` → générique ; contradiction titre / URL → skip),
  `resolve_name` (queue retirée avant le slug) et le nouveau hook `url_platform` de
  `MerchantConfig` (run d'URL → STEAM / EA / UBISOFT / BATTLENET / GOG / EPIC / ROCKSTAR, run
  console → None), consulté en premier par `explicit_platform_from_url` ; garde d'identité :
  `KINGDOM` en fin de titre après `UNITED`, nom AKS couvert, n'est plus un mot en trop. Mesure
  sur le lot du 12/09 (1 000 lignes, `gamivo_measure.py` du scratchpad) : 95 lignes passent le
  precheck (plateforme URL Steam 61, Battle.net 4, EA 2, GOG 1, 27 sans run = abonnements /
  logiciels / packs sans slot) ; régions EU 34, GLOBAL 35, US 11, gift 15 ; verrous filés
  Colombia 310, ROW 46, Canada 18, Netherlands 12, Australia 8, North America 6, Turkey 6, CIS 3,
  Poland 3, Asia 2, Mexico 2… ; consoles 419 (une queue interdite sur une ligne console est
  filée `forbidden region` avant `console`, comme sous `--consoles`) ; 0 contradiction titre /
  URL, 0 code `us` / `uk` sans queue de titre. Tests `GamivoConfigR46Tests` (16) ; docs
  EXECUTOR_RULES §4.4 / §4.10 / §11, MERCHANTS (section Gamivo + contrat), README, HANDOFF.

## 2026-09-12 — `docs/MERCHANTS.md` : la référence par marchand ; dry-run Eneba

Romain : « On a bien un doc avec chaque config marchand expliquée ? » — non, c'était réparti
entre EXECUTOR_RULES §4.10 (contrat R32), §11 (notes brèves) et les docstrings de
`src/merchants/*.py`. Nouveau `docs/MERCHANTS.md` : le contrat `MerchantConfig` champ par
champ, puis une section par marchand de la liste blanche (Kinguin, Gamivo, G2A, MMOGA, K4G,
Driffle, Instant Gaming, Eneba, Allyouplay, GameSeal, CJS-CDKeys, Difmark parqué) —
identifiants, grammaire titre / URL, hooks actifs, règles propres numérotées, statut
safe-auto, résiduel — et un tableau de statut. Lié depuis README « Rules & docs » et HANDOFF.
**Dry-run Eneba** (`20260912-075500-dryrun`, lecture seule, 07:50Z → 09:30Z) : 30 pages sur
59, 3 000 offres vues, **32 candidats** (plateforme lue dans l'URL `steam-…` / `origin-…`,
GLOBAL implicite ou EU/US du titre, éditions Complete/Deluxe/Premium/DLC(16) cohérentes,
pages AKS du bon jeu) ; écartées : **2 698 consoles (90 %)**, 147 catégories exclues, 77
régions interdites, 31 sans page AKS. Une même ligne (Cheap Golf, offer 101042157) vue sur
deux pages = reflow du feed entre deux extractions, pas un doublon (la 2e saisie la
trouverait absente du feed). Décision de sweep réel : Romain.

## 2026-09-12 — nuit multi-marchands : 460 offres créées sur 7 marchands, 0 halte

Romain (2026-09-11) : « tu continues jusqu'à demain matin » — un marchand par VPS, marchands
à historique safe-auto seulement. Soirée (16:19Z → 20:25Z) : nouveau VPS Driffle 9 → Kinguin
44 (pages 30-1) → G2A 56 → Instant Gaming 38 → G2A pages 31-37 : 8 ; ancien VPS MMOGA (DLC)
202 → Gamivo 2 → K4G 77 → Gamivo pages 31-56 : 4 → Kinguin pages 31-67 : 7. Tournée de nuit
02:00Z (10 premières pages) : nouveau VPS MMOGA 1, Kinguin 1, G2A 1 ; ancien VPS K4G 9,
Driffle 1, Gamivo 0, Instant Gaming 0. **Total 460 créées**, 0 halte, 4 non créées (2 refus
AKS 400, 1 sans signal, 1 « offer not in current feed » — disparue entre extract et submit).
Feeds désormais couverts en entier (Kinguin 67 pages, Gamivo 56, G2A 37, MMOGA 8, K4G 7,
Driffle 6, Instant Gaming 4-5) ; le résiduel est stable (consoles, sans page AKS, bundles,
monnaies, variantes d'édition). Documents `docs/feeds/*.md` régénérés avec l'historique des
deux VPS (runs de l'ancien VPS copiés : recap / submit_plan / skipped / match_meta /
candidates). Session AKS des deux navigateurs restaurée par transfert de cookies (Romain) après
le ban ; ban de l'IP du nouveau VPS levé à 13:55Z.

## 2026-09-11 — `--continue-on-halt` : lot multi-marchands qui ne s'arrête pas à la première halte

Romain : « après les deux marchands suivants, tu prendras d'autres marchands sur lesquels on
sait travailler (Kinguin, K4G…), tu continues jusqu'à demain matin ». Le lot multi-cibles de
`scripts/10` s'arrêtait à la première halte fail-closed d'un marchant (règle 2026-09 : une
session cassée touche tous les suivants). Nouveau flag `--continue-on-halt` : la halte est
consignée (`recap.halted_merchants`, `recap.halted` = liste), le marchand suivant est balayé
(son feed est indépendant), exit 2 à la fin s'il y a eu une halte ; un « not logged in »
(`halted_detail`) arrête toujours le lot. Console : `continue_on_halt` dans le POST
`/api/data-entry/auto` → argv. Tests : CLI (défaut = arrêt, flag = continue, login bounce =
arrêt), manager argv, handler. HANDOFF §7. Plan de nuit (Romain : « t'es sûr qu'Allyouplay et
Instant Gaming sont prêts ? » → vérification de l'historique : seuls Kinguin (142 pages
safe-auto), Gamivo (91), Driffle (22), MMOGA (11), G2A (10), Instant Gaming (8, config + R33)
et K4G (4) ont déjà tourné ; Eneba, Allyouplay, GameSeal, CJS-CDKeys sont en liste blanche
mais jamais balayés → exclus, dry-run d'abord un autre jour) : nouveau VPS Driffle → Kinguin,
G2A, Instant Gaming ; ancien VPS MMOGA → Gamivo, K4G (lot `20260911-162100-auto`, le premier
lot avec Eneba/Allyouplay/GameSeal ayant été arrêté proprement — `operator_stop` — avant
toute écriture).

## 2026-09-11 — sweep : le motif d'un extract en échec remonte dans le recap (« not logged in »)

Deux haltes `extract_failed_p1` dans la journée (ancien VPS 12:45Z, nouveau VPS 15:52Z,
Driffle) dont la cause — « not logged in (wp-login) », session AKS expirée → transfert de
cookies nécessaire — n'apparaissait que dans le log de page. `scripts/10` lit désormais le
dernier événement `aborted` de `logs/<run>.jsonl` (`_last_abort_reason`) : le détail devient
« extract: exit 2 (not logged in (wp-login)) » et le recap porte `halted_detail`. Tests
`ExtractAbortReasonTests`. Sweeps en parallèle (Romain : Driffle sur le nouveau VPS, Gamivo
sur l'ancien) : un marchand par VPS, jamais deux sur la même machine (un navigateur, un
verrou).

## 2026-09-11 — état du feed par marchand : `scripts/14_feed_status.py` → `docs/feeds/<MARCHAND>.md`

Romain : « un document par marchand pour expliquer l'état du feed : le dernier passage, ce
qu'on a ajouté d'offres et pourquoi on n'a pas ajouté ce qui reste ». `src/feed_status.py`
(fonctions pures sur `runs/` : recap des sweeps, `submit_plan.json` / `skipped.json` des pages,
runs by-urls du même store ; pas de réseau, pas de secret) + CLI `scripts/14_feed_status.py`.
Sections : dernier passage (run, durée, pages, vues / candidats / créées, halte, non créées),
offres ajoutées (cumul par jour / édition / région, historique des passages, liste du dernier
passage), ce qui reste et pourquoi (taxonomie des motifs de skip → famille, « pourquoi »,
« levier », exemples). Premier document : `docs/feeds/MMOGA.md`. Tests `test_feed_status`.

## 2026-09-11 — consoles : étude faite, chantier mis en attente (outil AKS feed à modifier)

Romain : « J'aimerais bien pouvoir traiter les consoles » → étude lecture seule (catalogue
du modal, pages AKS, feed MMOGA : 388 lignes console dont 79 non-jeux) consignée dans
EXECUTOR_RULES §4.3 (paragraphe « Console keys — PARKED ») : même page produit que le PC,
plateforme portée par le bucket de région (Xbox One 24/24eu…, Xbox Series 300/302…,
XBOX/PC 306/241…, PS4 88/88eu…, PS5 88ps5h, Nintendo 99/99eu…, pas de bucket Switch 2).
Bloqueur : une ligne de feed = une offre, consommée à la création → pas de 2e plateforme
pour le cross-gen (121/388 chez MMOGA). Décision Romain : « on reviendra sur les consoles
après modification de l'outil AKS feed ». Sweep DLC du jour : depuis l'ancien VPS (IP du
nouveau bannie jusqu'à 13:55Z), run `20260911-130500-auto`.

## 2026-09-11 — AKS/Staff par défaut vers allkeyshop.com (bannissement IP du VPS)

Vers 09:35Z, AKS a cessé de répondre au VPS (timeouts TCP sur 443/80, autres hôtes OK, AKS
joignable par Romain) : bannissement de l'IP 217.76.57.126 par l'anti-bot AKS après ~60
sondes de diagnostic en lecture seule envoyées avec l'UA navigateur (scripts ad hoc et
`curl` de l'agent ; le pipeline, lui, sonde toujours en `AKS/Staff`). Romain : « tu dois
utiliser l'user agent AKS/Staff pour éviter le ban ». `http_get` prend désormais
`AKS_STAFF_UA` par défaut pour tout hôte allkeyshop.com (UA explicite honoré, staff UA
toujours interdit ailleurs). Test `test_default_ua_towards_allkeyshop_is_the_staff_ua`.
EXECUTOR_RULES §4.6/4.7, HANDOFF, BROWSER_RUNBOOK. Sweep DLC en attente de la levée du ban.
Le ban a persisté > 3 h malgré le silence (drop réseau en amont du site : la liste blanche
par UA ne peut plus jouer) ; l'onglet Chromium resté sur wp-admin renvoyait un heartbeat en
UA navigateur → remis sur `about:blank`. Romain : « fais en sorte que ce qui te sert de
sonde ait l'UA AKS/Staff » → **`scripts/13_aks_ping.py`**, la sonde officielle (staff UA,
une requête, JSON, `--wait/--max` pour attendre une levée de ban) — HANDOFF, RUNBOOK.

## 2026-09-11 — matcher : DLC / Add-On / Season Pass saisis sur leur page AKS (R43)

GO de Romain (« apprendre à ajouter les DLC sur les pages AKS à édition DLC … inclus les
Season Pass »). Constat : 212 offres « DLC in title » et 27 « SEASON PASS » dans le feed
MMOGA restant ; sondage lecture seule sur 12 titres « (DLC) » : 9 se résolvent par simple
devinette de slug (marqueur retiré) sur **leur propre page AKS**, toutes avec le bucket DLC
(16), 3 sans page, 0 sur la page du jeu de base. Changement (`src/matcher.py`) :
- `dlc_title_marker` (SEASON PASS / EXPANSION PASS / DOWNLOADABLE CONTENT / ADD ON / ADDON /
  DLC, mots entiers, pluriels) remplace le pré-skip « DLC in title » et la catégorie
  `SEASON PASS` ; « Battle Pass » & co restent skippés (`PASS`).
- `strip_dlc_marker` retire DLC / Add-On / Downloadable Content du texte résolu (les mots
  Season/Expansion Pass restent : ils sont le slug AKS, `hearts-of-iron-iv-expansion-pass-2`).
- **Garde-fou R43** : titre marqué DLC ⇒ la page résolue doit porter le bucket DLC, sinon
  skip « `<MARKER>` in title but AKS page '…' carries no DLC edition — base game or wrong
  product, not entered (R43) », avant les gardes de nom (page du jeu de base atteinte par un
  palier de slug moins spécifique, stub R19, autre produit).
- R01b : qualificatifs `DLC` / `SEASON PASS` levés quand la page porte le bucket DLC
  (REMASTERED/HD/ANNIVERSARY jamais) ; R16 : les mots du marqueur ne sont pas des « mots en
  trop » (les mots propres du DLC doivent toujours coller au nom AKS — 2e filet).
- Édition saisie DLC(16) par R18, jamais Standard.
**Revue adversariale (workflow, 3 angles : saisie fantôme, regex/PASS, contrats aval)**
→ durcissements : (a) **règle de la page propre** — le bucket DLC seul ne prouve pas que la
page est CE DLC (une page de jeu de base peut en porter un) : un titre marqué DLC n'est
accepté que si le slug résolu est l'un de ses slugs de palier 1 (`own_page_slugs`,
`resolved_on_own_page`) ; atteint via les paliers moins spécifiques (mots d'édition
retirés, tête avant « - ») → skip « … resolved through a less specific slug tier … (R43) »
(204/205 candidats DLC du dry-run résolvent au palier 1) ; (b) levée R16 des mots du
marqueur **conditionnée à la preuve de page DLC** (`dlc_page=True` depuis `match_offer`
seulement) ; (c) classifieur et retrait **normalisés NFKC comme `tokenize`** (« ＤＬＣ »
pleine chasse) + pluriels/traits d'union (« DLCs », « Add-Ons », « Downloadable-Content ») ;
(d) passes : BATTLE / GAME / GROW / MONTHLY / WEEKLY PASS restent skippés même tagués
« (DLC) » ; un « <x> Pass (DLC) » (Year 1 Pass, Extra Pass — 5 lignes MMOGA ont leur page
DLC) et les Season / Expansion Pass vont en résolution, un « <x> Pass » non tagué reste
skippé ; (e) **DLC sans nom propre** (« <Jeu> (DLC) », pas de sous-titre) sur une page qui
vend aussi Standard → skip (indiscernable de la page du jeu de base portant un bucket
DLC) ; (f) **collections de DLC** (« DLC Pack / Collection / Bundle », « All DLC », « DLCs »)
= bundles → jamais saisies (`dlc_collection_marker`, « World's Fair Pack (DLC) » reste un
DLC) ; (g) un « DLC » en tête est un nom (« DLC Quest », vrai jeu) : rien retiré.
Effet mesuré sur les 215 candidats du dry-run : 0 collection, 1 forme sans nom (« Arma 3
Karts (DLC) », skip seulement si sa page vend aussi Standard), 204/205 au palier 1.
**Constats live de la revue, hors R43 (à corriger à la main sur AKS, décision Romain) :**
- **R18 saisit des jeux de base en DLC(16)** : des pages AKS de jeux de base portent le
  bucket 16 — *Stray Blade* (92993, page 7), *Aliens - Dark Descent* (115227, page 19),
  *DRAGON QUEST III HD-2D Remake* (116084, page 16) créés en DLC(16) le 2026-09-10. Aucun
  signal de nature de page trouvé (pas de champ type produit ; section « #basegame » et
  ordre des éditions incohérents). **Décision Romain 2026-09-11 : R18 reste tel quel**
  (« des fois, les titres n'ont pas de marqueur et sont des DLC »), les trois fiches ne
  sont pas à corriger ; consigné dans AGENTS.md « Reviewed decisions ». R43 est protégé
  par la règle de la page propre et le skip « sans nom » (titres marqués seulement).
- **9 offres MMOGA à queue de région « (Steam Key EU) » / « [EU] » saisies GLOBAL** le
  2026-09-10 (WWE 2K24 ×2, The Last of Us Part II Remastered, Marvel's Midnight Suns, Dragon
  Ball The Breakers Special, Wild West Dynasty ×2, Sengoku Dynasty Guide, NBA 2K24 Black
  Mamba) : seconde grammaire MMOGA `REGION_CODE_TAIL_RE` (code après le mot Key, entre
  crochets/parenthèses ; « (PC) » n'est pas une région) + `resolve_name` la retire. Tests
  `MmogaRulesTests.test_bracket_and_paren_region_tails`. EXECUTOR_RULES §4.4. Romain
  corrige les 9 fiches à la main (pages AKS : wwe-2k24 ×2, the-last-of-us-part-ii-remastered,
  marvels-midnight-suns, dragon-ball-the-breakers, wild-west-dynasty ×2, sengoku-dynasty,
  nba-2k24 — région saisie Steam (2) / Epic Store (80) → EU).
Tests (`DlcTitleR43Tests`) : classifieur, retrait du marqueur, DLC / Season Pass / Add-On
sur page DLC → candidat DLC(16) avec nom résolu sans marqueur, page du jeu de base → skip
R43, stub → skip R43, autre DLC → R01/R16, Remastered non levé, extras, pas de page ; routage
listes inchangé (garder). Docs : EXECUTOR_RULES §4.2/§4.3 `[R43]`/§4.5, HANDOFF §3.
**Dry-run match seul** (lecture seule, code R43, snapshots des 10 pages du sweep du matin,
disjoncteur partagé) : **215 candidats** (10 ce matin) dont 205 DLC/Season Pass entrés en
DLC(16) sur leur propre page AKS (206 candidats DLC(16), un jeu sans marqueur via R18) ;
**R43 a écarté 21 DLC** retombés sur la page du jeu de base (The Elder Scrolls Online ×4, Le Mans Ultimate ×2, Blood Bowl 3 ×2, Taxi Life ×2, Total
War Warhammer III, Fatal Fury Season Pass 3…) — aucun DLC candidat sur une page de jeu de
base ; cas fail-safe R01 : « The Sims 4 - Jungle Adventure (DLC) » tombé sur une page
« … Bundle ». Trouvaille du dry-run → **`[R44]`** : « Age of Empires III DE - United States
Civilization (DLC) » sortait région **US** (slug `-united-states-` lu comme un lock) ;
désormais `region_phrase_in_aks_name` : un mot de région (United States/USA, United
Kingdom, Europe — mots entiers) présent dans le nom du produit AKS rend la région
ambiguë → skip fail-closed, sauf région déclarée par la grammaire du marchand (hook MMOGA
« US Key », autoritaire) ou marqueur GLOBAL/EU explicite gagnant avant. Tests
`RegionIdentityPhraseR44Tests`. EXECUTOR_RULES §4.4.

## 2026-09-11 — sweep MMOGA du matin : 10 créées (les 10 refus 400 de la nuit), feed réduit à 10 pages

Run `20260911-083407-auto` (`--max-pages 30`), 08:34Z → 08:55Z (**21 min**), exit 0, 10 pages,
936 offres, **10 candidats → 10 créées** : exactement les 10 refus AKS 400 « paramètre
"offer" manquant » de la nuit (Jackbox Survey Scramble, Yakuza Like a Dragon, Wild Bastards,
Space Marine 2 Gold, FF XIV Endwalker, Square Dungeon 2, SAO Last Recollection Deluxe,
Wattam, Book of Demons, Age of Empires III DE) — confirmé transitoire côté AKS. Les 5
« sans signal » de la nuit (Shadows of the Damned, Karate Kid, The Invincible, Pro Cycling
Manager 2023, Double Dragon Gaiden) sont **absentes du feed** ce matin : AKS les a créées en
retard après notre fenêtre d'observation ; le verdict FAILED d'hier était fail-safe et aucun
doublon n'a été saisi (elles n'étaient plus à localiser). Reste du feed = écarts stables :
388 consoles, 212 DLC, 157 « no AKS product page found » (recherche AKS toujours en timeout
8 s → disjoncteur ouvert dès la page 10, 53-42 offres non recherchées par page), 70 bundles/
skins, 52 produits élargis, 13 noms non concordants, 12 plateformes non vérifiables, 8
éditions logicielles non résolues, 3 sondes non fiables, 3 sans carte d'éditions, 2 régions
interdites, 2 ROCKSTAR/GLOBAL sans id région.

## 2026-09-11 — sweep MMOGA complet : 922 créées sur 938 candidats, 20 pages, 0 halte

Run `20260910-170123-auto` (MMOGA store 12, `--max-pages 30`, feed de 20 pages), lancé
2026-09-10 17:01Z, fini 2026-09-11 03:00Z (**10 h**), exit 0, couverture complète, tous
leviers actifs : disjoncteur R30 ouvert dès la page 20 et gardé pour tout le sweep (aucune
recherche AKS ensuite), catalogue en cache, settle 1 s, timeout CDP 45 s, réessai de preuve.
**922 créées / 938 candidats (98,3 %)**, 33-39 s par offre (moyenne ≈ 36 s), 22-41 min par
page selon le nombre de candidats. **16 non créées**, toutes laissées dans le feed pour le
sweep suivant : 11 refus AKS 400 « paramètre "offer" manquant ou invalide » (transitoire
backend, aucun motif commun région/édition, jamais consécutifs) et 5 « sans signal » (la
requête de création n'a pas répondu dans les 40 sondages, preuve « toujours dans le feed »
→ FAILED, jamais UNKNOWN). **0 halte, 0 réessai de preuve nécessaire, 0 contexte modal
manquant.** Page 1 (dernière traitée) : 5 candidats sur 100, 31 « no AKS product page
found » dont 59 offres non recherchées (disjoncteur) — à reprendre par le sweep suivant si
la recherche AKS répond.

## 2026-09-10 — submit : preuve post-save réessayée une fois sur timeout CDP (socket intact)

2e halte `feed_unreadable` du jour (*End of Lines*, page 19 : Create réussi puis
`Runtime.evaluate` sans réponse en 45 s sur la preuve → UNKNOWN → sweep arrêté après 24
créations, offre vérifiée créée en lecture seule). Cause : la page admin AKS met parfois
plus de 45 s à répondre à la navigation de preuve juste après un Create — le socket, lui,
est intact. GO de Romain : `CdpTimeoutError(CdpCommandError)` levée par `_cmd` sur le seul
cas « no response within Ns » (EOF / close frame / flux coupé restent `CdpCommandError`), et
le submitter réessaie **une fois** la preuve post-save (lecture seule, navigations fraîches)
après `POST_SAVE_PROOF_RETRY_WAIT_S` = 5 s, événement `post_save_proof_retry` + champ
`post_save_proof_retry` dans le plan. Deuxième timeout, socket mort, `FeedScanError`,
`NotLoggedInError` : UNKNOWN + `stopped=feed_unreadable` comme avant. Tests : timeout =
sous-classe, socket mort ≠ timeout, réponse tardive ignorée par la commande suivante (CDP) ;
1 timeout → créée sans halte, 2 timeouts → UNKNOWN + stop, socket mort → jamais réessayé,
preuve par recherche réessayée à l'identique (submitter). Docs : EXECUTOR_RULES §7, HANDOFF §3.

## 2026-09-10 — disjoncteur R30 : ouvert pour tout le sweep (plus d'expiration 30 min)

Sweep MMOGA 30 pages (#2, tous leviers) : page 20 = 8/8 en 7 min (match 1 min : 3 échecs de
recherche → disjoncteur ouvert et persisté), page 19 démarre circuit pré-ouvert
(`search_circuit_preopened`, 71 offres non recherchées) et catalogue en cache
(`catalog_cache_hit`), match en 1 min au lieu de ~10, puis 24 créées sur 25 tentatives à
32-67 s par offre (moyenne 41 s) avant un arrêt fail-closed `feed_unreadable` : *End of Lines*
(AKS 122402) — Create réussi (signal « Offer created … merchant 40 »), puis `Runtime.evaluate`
sans réponse en 45 s sur la preuve post-save → UNKNOWN. Vérifié en lecture seule par l'aperçu
by-urls (`scripts/11 --targets MMOGA:12`, recherche du feed `available=all`) : aucune ligne
MMOGA pour ce jeu → **créée**. 2e halte de ce type en ~100 créations MMOGA sur la journée ;
une relance ne peut pas dupliquer (le feed fait foi à la localisation). Décision de Romain : les offres non
résolues par devinette d'URL n'ont pas à repasser par la recherche AKS à l'expiration d'un
TTL — elles restent dans le feed pending et seront reprises par le sweep suivant du marchand.
`scripts/03_match` : `SEARCH_CIRCUIT_TTL_S` / `open_until` retirés, `_search_circuit_is_open`
ne regarde que `open`, une page qui démarre circuit ouvert laisse le fichier tel quel (rien
appris), une page dont la recherche a été appelée sans échec l'efface. Le fichier vit dans le
répertoire du sweep : un nouveau sweep repart recherche active. Tests CLI 03 : fichier ancien
(`open_until` passé) → toujours pré-ouvert, fichier fermé/illisible → pas de pré-ouverture,
fichier armé sans `open_until`. Docs : EXECUTOR_RULES §4.7, HANDOFF §3.

## 2026-09-10 — sweep MMOGA 30 pages : 35 créées, UNKNOWN levé en lecture seule, timeout CDP submit 45 s

Sweep lancé par Romain (`--max-pages 30`, feed de 21 pages) : page 21 = 12/12, page 20 =
23 créées sur 32 candidats, puis arrêt fail-closed `feed_unreadable` : un `Runtime.evaluate`
sans réponse en 20 s **juste après** un Create réussi (signal AKS « Offer created … merchant
40 »), donc preuve post-save impossible → *Jurassic World Evolution 3 Deluxe* marquée
**UNKNOWN**. Vérification en lecture seule par la recherche du feed (la preuve du submitter) :
l'offre a **disparu du feed → créée** ; une relance ne peut pas la dupliquer (le feed fait
foi). *Tomb Raider: Legacy of Atlantis* : refus AKS « Bad request : paramètre "offer" manquant
ou invalide » (2e occurrence du jour ; remplissage identique à l'entrée Deluxe créée juste
après, donc transitoire côté backend) — toujours dans le feed, reprise au run suivant, pas de
re-tentative dans le run (règle fail-closed). Correctif : `SUBMIT_CDP_CMD_TIMEOUT_S` = 45 s pour
`SubmitSession` / `WriteSubmitSession` (les sessions lecture seule gardent 20 s) — la page
admin AKS peut bloquer 20-30 s sous lenteur backend, comme sa recherche.

## 2026-09-10 — sweep : −2 min par page (disjoncteur persistant, catalogue par sweep, settle 1 s)

Mesure sur le sweep MMOGA 30 pages (pages 20-21) : ~24 s d'extract, **~196 s de match**
(dont 3 × 20 s de timeouts de recherche avant l'ouverture du disjoncteur, à chaque page),
**~59 s de préparation du submit** (login, catalogue live, index), puis 34-38 s par offre.
Trois leviers sur GO de Romain, sans toucher aux règles ni à la preuve :
- **Disjoncteur R30 persistant par sweep** : `03_match --search-circuit-file
  <sweep>/search_circuit.json` (émis par `scripts/10`) — une page qui déclenche le
  disjoncteur ré-arme le fichier (expiration 30 min), les suivantes démarrent circuit ouvert
  (`match_meta.search_circuit_preopened`), une page dont la recherche a marché l'efface.
  `AKS_SEARCH_TIMEOUT_S` 20 → 8 s. Gain ≈ 60 s/page tant que la recherche AKS est morte.
- **Catalogue live une fois par sweep** : `05_submit --catalog-cache <sweep>/catalog.json`
  (émis par `scripts/10`) — cache valable 2 h et pour le même store, sinon fetch + écriture ;
  sans le flag, `run()` fetch comme avant. Gain ≈ 30-40 s/page.
- **Settle avant la modale 3 s → 1 s** (`ROW_PAGE_SETTLE`) quand la session expose la gate
  de readiness (qui fait désormais l'attente utile) ; 3 s conservées sinon. Gain ≈ 2 s/offre.
Tests : circuit pré-ouvert dans `match_feed`, fichier ouvert/expiré/ré-armé (CLI 03), cache
catalogue (aller-retour, autre store, périmé, non-ok), argv du sweep (03 + 05), settle court
avec sonde / 3 s sans. Docs : EXECUTOR_RULES §4.7 et §6.

## 2026-09-10 — modale : gate de readiness des scripts + un re-clic (clic perdu)

Sweep MMOGA n° 3 (attente de modale 23 s) : 7 des 9 offres bloquées la veille sont passées,
mais 3 sont restées « modal context missing » **sans jamais recevoir le contenu en 23 s**
(*God Eater 2*, *The Long Journey Home*, *The Crew 2 Gold*), alors qu'un second diagnostic
lecture-seule (GO Romain) ouvre leur modale à 0,0 s avec le formulaire complet
(`offer[merchant]=40` pré-rempli). Conclusion : ce n'est ni le produit ni la latence AJAX,
c'est le **clic lui-même qui est perdu** quand il part avant que les scripts de la page aient
lié le handler ThickBox (le settle de 3 s ne suffit pas toujours sous lenteur AKS — la leçon
du 20/07 en version aléatoire). Correctif : (a) gate lecture-seule avant le clic —
`page_scripts_state()` (`document.readyState == 'complete'` et `tb_show` défini), polling
`PAGE_SCRIPTS_READY_WAITS` ≈ 15 s ; (b) après `MODAL_RECLICK_AFTER_POLLS` = 3 lectures vides,
le clic est réémis **une fois** (ouvrir une modale n'a pas d'effet de bord) ; (c) sur échec
final, événement `modal_ctx_missing` avec le dernier contexte et l'état des scripts, pour ne
plus diagnostiquer à l'aveugle. *Assetto Corsa* : « Bad request : paramètre offer manquant »
renvoyé par AKS au Create — à observer au prochain run. Tests : gate, re-clic unique, échec
fermé avec un seul re-clic, pas de re-clic sans attente. Doc : EXECUTOR_RULES §6 étape 3.

## 2026-09-10 — MMOGA en safe-auto : 41 créations, attente de modale portée à ~23 s

Premiers sweeps safe-auto MMOGA (page 1, `--max-pages 1`, preuve post-save par recherche) :
run 1 = 33 candidats, **26 créées** (prouvées « disparues du feed »), 1 échec réel (clic sans
signal, offre restée dans le feed), 2 bloquées « modal context missing », arrêt fail-closed
sur un timeout CDP de 20 s AVANT tout clic (offre marquée UNKNOWN par prudence, rien d'écrit) ;
run 2 = 24 candidats, **15 créées**, exit 0, 9 bloquées « modal context missing ». Timing :
32-34 s par offre (contre ~100 s avant la preuve par recherche), dont ~9 s de preuve.
**Diagnostic en lecture seule (GO Romain)** : ré-ouvrir la modale de 3 lignes bloquées + 1
contrôle sert le formulaire (`offer[region]` / `offer[edition]`) **instantanément** — le
blocage n'est pas lié aux produits mais à la latence de l'AJAX ThickBox pendant le sweep (même
backend AKS que la recherche à 20-30 s). Correctif : `MODAL_CTX_WAITS` = 1/2/4/8/8 s (≈23 s,
relecture sans re-clic, `modal_ctx_render_wait` journalise le délai), distinct des attentes de
rendu du feed ; toujours fail-closed au bout du budget. Doc : EXECUTOR_RULES §6 étape 3.

## 2026-09-10 — sweep safe-auto : preuve post-save par la recherche du feed (GO Romain)

« On peut gagner du temps à l'écriture » : dans le sweep, le post-save re-balayait TOUT le
feed après chaque création (~1,5 s × 66 pages ≈ 100 s par offre sur Kinguin), alors que
by-urls prouve la disparition par la **recherche du feed filtrée par l'URL de l'offre**
(requête sur tout le feed, même mode `available`) depuis le 25/08. Sur GO de Romain, le
sweep utilise cette preuve par défaut : `05_submit --prove-gone-by-search`
(`Submitter.run(prove_gone_by_search=True)`), émis par `scripts/10` sauf
`--prove-gone-scan`. La localisation garde la fenêtre `--page-hint` (index conservé : les
0-1 lignes d'une recherche ne l'écrasent jamais) ; la re-localisation d'une ligne qui a
bougé passe aussi par la recherche. Gardes inchangés : recherche non rendue / bloquée /
débordante → `FeedScanError` → offre UNKNOWN, jamais un faux « gone ». Tests : câblage
`run()` → ctx, preuve par recherche + index conservé, chemin by-urls inchangé, re-localisation,
argv de 10 (défaut et `--prove-gone-scan`). Docs : EXECUTOR_RULES §7, HANDOFF §6.

## 2026-09-10 — `[R42]` chiffres romains ≡ chiffres (MMOGA « Crusader Kings III »)

Test de Romain par la page `/games` avec la page AKS « Crusader Kings 3 » : l'offre MMOGA
`Steam-Games/Crusader-Kings-III.html` n'a pas été détectée. Deux causes : l'aperçu datait
d'avant l'ajout de MMOGA à l'allowlist (store 12 non cherché), et surtout **III ≠ 3** pour
la recherche du feed (`Crusader Kings 3` / `crusader-kings-3`) comme pour l'identité R01
(« mot AKS manquant : 3 »). Règle générique : `tokenize` canonise II–XV en chiffres (R01/R16
acceptent les deux graphies), `build_slug_candidates` ajoute la graphie alternative après
chaque base (`crusader-kings-iii` puis `crusader-kings-3`, même palier, +1 sonde seulement
si un numéral existe), et la recherche feed de by-urls interroge les deux graphies par nom
et par URL (`meta.alt_terms`). Jamais I/V/X (mots réels : « V Rising », « Mega Man X »),
jamais une année. Tests : tokenisation, identité, slugs, `swap_numerals`, termes de
recherche. Docs : EXECUTOR_RULES §4.1 `[R42]`.

## 2026-09-10 — MMOGA : nouveau marchand via des hooks de config marchand `[R32e]`

Romain : « notre executor doit apprendre à ajouter les offres mmoga » et « un fichier de
config marchand par marchand, qui peut ajouter, overwrite, modifier des comportements
génériques ». Le contrat commun gagne **trois hooks optionnels** dans `MerchantConfig`
(`precheck(name, url)`, `title_region(name)`, `resolve_name(name)`), appelés en premier par
le matcher (repli sur la règle générique sur `None`) — le matcher reste agnostique. Le
hook région est autoritaire quand il se prononce ; `resolve_name` ne réécrit que le texte
envoyé à la résolution AKS, jamais celui des contrôles d'identité (R01/R16).

`src/merchants/mmoga.py` porte toute la grammaire
`mmoga.com/<Platform>-Games/<Product>[-<REGION>-Key].html?ref=<affid>` : plateforme par le
segment de catégorie de l'URL (`Steam-Games` → STEAM, `EA-Games` → EA…), région par le
**code MAJUSCULE avant « Key »** en fin de titre, lu **sensible à la casse** (`Among Us Key`
reste global), codes interdits → `forbidden region: <LABEL>`, code sans bucket AKS (DE, FR…)
→ skip fail-closed, slug résolu sans le suffixe (`borderlands-2`), `?ref=` ignoré, domaine
`mmoga.com` obligatoire. Vérifié sur les 3 URL d'exemple + cas limites. Tests :
`MerchantHookTests` (marchand factice, 3 hooks) + `MmogaRulesTests` (8 cas). Docs :
EXECUTOR_RULES §4.10 `[R32e]` + §11 MMOGA + §10, README `[R32]`. Store ids (Romain) :
**12** côté feed (`&store=12`, celui que tous les étages utilisent), 40 côté pages AKS.
Ajouté au sélecteur console (`app.js`) **et à l'allowlist safe-auto** (Romain, même jour :
« je préfère passer directement par /auto », avant tout run supervisé — signalé ; les
règles MMOGA échouent-fermé sur tout code région non mappé).

## 2026-09-10 — R30 : disjoncteur sur la recherche AKS + délai de grâce avant `AksThrottled`

Premier dry-run safe-auto Kinguin sur le nouveau VPS (lecture seule) : page 30 en ~21 min
parce que **59 offres sur 100** sont arrivées au repli R30 dont chaque requête `?s=` a
expiré (20 s) — mesuré directement : la recherche AKS répond en **22-28 s avec un 200 au
corps vide** (`Content-Length: 0`, timeout PHP côté WordPress probable). Puis page 29
arrêtée par le garde anti-throttling sur une rafale de **5 × 503 en 4 s** (pages produit
normales juste après). Décision Romain (« fais 1+2 ») :
- **Disjoncteur R30** (`_ThrottleGuard`, `SEARCH_CIRCUIT_BREAKER_FAILURES = 3`) : après 3
  échecs consécutifs de la recherche dans un run (timeout / corps vide / 5xx), plus aucun
  appel à la recherche pour le reste du run — `resolve_aks(search=False)` — les offres dont
  les slugs devinés font 404 deviennent « no AKS product page found » sans attendre 20 s.
  Les échecs de recherche **ne comptent plus** vers l'abort (ce n'est pas du throttling des
  pages produit). `match_meta.json` : `search_failures`, `search_circuit_open_offers` (à
  repasser quand la recherche AKS remarchera), `throttle_graces`.
- **Délai de grâce** (`THROTTLE_GRACE_S = 30`, `THROTTLE_MAX_GRACES = 2`) : au seuil des 5
  sondes non fiables consécutives sur des pages distinctes, attendre 30 s et retenter
  l'offre une fois ; `AksThrottled` seulement si ça échoue encore. Jamais sur un 429
  (arrêt immédiat). Même garde dans le flow by-urls (pas de sommeil sous un stub de test).
- Tests : grâce absorbée / grâce puis échec / 429 sans grâce / plafond de grâces ;
  disjoncteur (déclenchement, jamais d'abort, `search=` passé seulement aux résolveurs qui
  l'acceptent, bout-en-bout `match_feed` + `resolve_aks` reproduisant la page 30) ;
  `resolve_aks(search=False)`. Suite complète verte.
- **Trois formes d'URL AKS par slug deviné** (Romain, même jour : « essaie le current, puis
  le nouveau, puis l'ancien ») — `aks_page_urls(slug)` : (1) courante
  `buy-<slug>-cd-key-compare-prices/` ; (2) **nouvelle**, les pages créées depuis 2026
  portent l'année de sortie (`buy-fable-2026-cd-key-compare-prices/`) → essayée avec
  l'année en cours, la suivante et la précédente, sauf si le slug finit déjà par une année ;
  (3) **ancienne** (pages ≈2021, ex. Minecraft)
  `compare-and-buy-cd-key-for-digital-download-<slug>/`. **Borné après le dry-run n° 2**
  (10h22, arrêt `aks_throttled` dès la page 30 : sonder 5 formes × chaque palier de slug a
  fait monter le débit à ~200-300 req/min soutenues — chaque 404 AKS pèse 500 Ko — et AKS
  a répondu par des rafales de 503 ; hors charge, toutes les formes répondent 404
  proprement) : passe 1 = forme courante pour tous les paliers (coût inchangé), passe 2 =
  variantes année (année en cours, suivante) puis ancienne pour le slug **le plus
  spécifique seulement** → +3 sondes max par offre non résolue. MA1 conservé (un 5xx lève
  après une seule nouvelle tentative de la MÊME URL, `PROBE_TRANSIENT_RETRY_WAIT_S` = 2 s,
  jamais sur 429 ; jamais de palier inférieur). Les pages account gardent leur forme
  unique ; la résolution garde le slug réel de la page (`fable-2026`).

## 2026-09-09 — audit adversarial des 5 commits du 08/09 : 38 findings corrigés

Revue en lecture seule demandée par Romain (« regarde mes 3 derniers commits, ne code
pas ») des commits `184b2b8 → e7586f6`, menée en workflow multi-agents (5 chasseurs, 3
vérificateurs adversariaux par finding, critique de complétude), coupée trois fois par la
limite de session et reprise depuis son journal (état sauvegardé incrémentalement dans
`docs/audit_2026-09-09_last-commits/`, bilan `BILAN.md`). **45 findings, 38 confirmés, 7
réfutés, 0 critique, 2 majors.** Correctifs appliqués sur GO de Romain, puis re-vérifiés par
une seconde revue adversariale (137 agents, 40 remarques mineures intégrées).

- **[major, sécurité] Garde host-lock du staff-UA contournable** (`src/aks_env.py`
  `_allkeyshop_host`) : `urlsplit` lisait `www.allkeyshop.com` dans
  `https://evil.tld\@www.allkeyshop.com/x` alors que urllib3 (connexion keep-alive) s'arrête
  au `\` et se connectait à `evil.tld` avec `AKS/Staff` — reproduit 3× à HEAD. Le garde exige
  désormais un netloc non ambigu (`[A-Za-z0-9.-]` + `:port` optionnel, pas d'userinfo, de `\`,
  d'espace, ni de schéma non-http). Testé sur les deux backends contre un serveur local.
- **[major, ops] Défaut `--max-pages 30` = halte fail-closed du lot** : tout feed > 30 pages
  finissait `halted=coverage_incomplete_max_pages` → `break` + exit 2, marchands suivants
  jamais balayés, run « ARRÊTÉ » en console. Le cap est désormais **de la couverture** :
  champ `coverage` du recap du marchand (`incomplete_max_pages (feed has N pages)` /
  `incomplete_feed_grew (a→b pages)`), liste `coverage_incomplete` au niveau du lot, lot
  poursuivi, exit 0, pastille « TERMINÉ — couverture partielle ». `SweepConfig.max_pages`
  aligné à 30, placeholder `/auto` « 30 (défaut) », modale d'aide mise à jour.
  `--max-pages`/`--start-page` < 1 refusés (exit 2) ; le manager valide `max_pages` aussi.
- **Throttling AKS = STOP fail-closed** (critique de complétude) : `_ThrottleGuard` autour du
  résolveur de `match_feed` lève `AksThrottled` au premier **429** (slug deviné, recherche R30
  ou slug de repli) ou à **5 sondes non fiables consécutives sur des pages distinctes** ;
  `03_match` sort en 2 (`reason: aks_throttled`, sidecar `match_aborted.json`, rien d'autre
  écrit) → le sweep halte `match_failed_pN` avec la raison ; `match_meta.probe_unreliable` et
  le recap de page comptent les skips non fiables sous le seuil. Une recherche R30 en 429/5xx
  n'est plus « aucun résultat ». Même règle dans le flow by-urls (`recap.aborted =
  aks_throttled`, 429 jamais retenté).
- **Boucle host-locked keep-alive** : suit 10 redirects comme urllib (`range(11)`, l'ancien
  `range(10)` en suivait 9) ; `Location` re-quotée comme `http_error_302` (permalink UTF-8 →
  `%C3%A9`, plus de mojibake) ; `URLError` du plafond levée hors du `except` général (plus de
  double enrobage). Divergences résiduelles documentées dans la docstring, toutes fail-closed.
- **Session keep-alive env-blind** : `trust_env=False` (plus d'injection `Authorization` via
  `~/.netrc`, ni `REQUESTS_CA_BUNDLE`) ; proxies miroir de urllib (`getproxies` +
  `proxy_bypass` sur `host:port`).
- **by-urls** : pacing `AKS_PROBE_DELAY_S` entre URLs (la boucle de résolution était la
  rafale staff-UA la plus dense).
- **Tests** (+31, 1322 → 1353) : dispatcher `_http_open` et les DEUX backends réels contre un
  `http.server` 127.0.0.1 (no-redirect, host-lock same-host / off-host / `\@`, plain, HEAD,
  cookies, netrc) ; boucle host-locked (hop 2, Location relative/minuscule/absente, plafond
  10/11, `\@`, userinfo, `javascript:`, mojibake) ; garde strict ; miroir proxy ; session
  réelle (cap, cookies, `trust_env`) ; throttle (429 immédiat, 5 distincts, page cassée
  répétée, propagation status/slug, repli recherche) ; CLI 03 (abort/sidecar/compteur) ; CLI 10
  (cap = exit 0 + lot poursuivi, bornes < 1) ; by-urls (429 non retenté, abort du run,
  pacing) ; `Halo™Deluxe` non vacuous. Tests hermétiques aux variables proxy ; les tests
  exigeant `requests` sont `skipUnless` (suite stdlib-only à nouveau verte).
- **CI** : matrice Python 3.11 sans / avec `requests`. **Docs** : plancher Python 3.11+
  (README, CONTRIBUTING, RUNBOOK), `requests` optionnel via `apt python3-requests` (PEP 668),
  « même contrat de sonde » au lieu de « comportement identique », HANDOFF §1/§3/§4/§6/§7
  (commandes corrigées : `Eneba:19`, script 11 `--run-id --urls-file`, étape `04_validate
  check`, safe-auto marquée WRITE/GO avec `--dry-run`, `06_move` canary puis
  `--i-authorize-batch`, 08/09), EXECUTOR_RULES §4.1/§4.7/§14, commentaires du strip ™ et du
  pacing (attribution du ban 2026-08-28) réalignés.
- Réfutés (non modifiés) : `pip` sous PEP 668 (`python3-requests` déjà tiré par certbot),
  substring `"gone"` du recap (05 n'écrit jamais « NOT gone »), cas résiduels du matcher
  (ᵀᴹ/Ⓡ/№, choix testé), docstring « single seam », `Location: javascript:` sur la gate.

## 2026-09-08 — keep-alive : correctif fail-open trouvé par vérif adversariale

Vérif adversariale multi-agents du seam keep-alive (184b2b8) : 9 findings confirmés, dont
**1 CRITIQUE fail-open**. `_http_open_keepalive` testait `host_locked` AVANT `follow_redirects`,
alors que le fallback urllib teste `if not follow_redirects` en PREMIER. Conséquence : un
probe staff-UA en `follow_redirects=False` (la **gate d'invariants** `src/invariants.py` +
`03_match`) suivait un 3xx **same-domain** (307/308/303 WAF/canonical) jusqu'au 200 →
`ok=True`, là où urllib lève `HTTPError` → `ok=False`. Un 3xx same-domain sur `allkeyshop.com/
blog/` aurait fait passer la gate « read-only until green » au **VERT à tort** → risque de
débloquer les stages d'écriture. Corrigé : `_http_open_keepalive` teste `if not follow_redirects`
en premier (ne suit rien, le 3xx ressort en HTTPError comme urllib), `elif host_locked`, `else`
— miroir exact de l'ordre urllib. Régression-test ajouté (host_locked + no-redirect → HTTPError).
Vérifié : pas de fuite staff-UA off-domain, pas de wrong-entry (probes de résolution en
`follow_redirects=True`, identiques). Minors corrigés en même temps : (2/3) le strip des
symboles NFKC→lettres déplacé de `tokenize` vers **`normalize_apostrophes`** (couvre aussi
`cleaned_title`/`build_slug_candidates`) et élargi (`™®©℠℗℡№℅℀℁℆`) sans toucher aux lettres
math ni aux chiffres romains ; (4) l'except keepalive attrape désormais toute exception
non-`RequestException` (requests cassé au runtime) → `URLError`, préservant « ne lève jamais ».

Une **re-vérif adversariale** du seam corrigé (4 chasseurs, commit 54f1f88) a confirmé la
parité par mode (gate no-redirect + host-lock = urllib exactement, strip sans sur-strip). Seul
reste un écart **pré-existant et pathologique** : `requests` suit jusqu'à 30 redirects par
défaut vs 10 pour urllib — divergence uniquement sur une chaîne de 11-30 hops (jamais vue sur
AKS, hors gate). Fermé par `_SESSION.max_redirects = 10` (parité fail-closed exacte) + tests
(TooManyRedirects → URLError, ceiling = 10).

## 2026-09-08 — perf : keep-alive HTTP + pacing 0,15s + cap pages safe-auto

« Les sweep sont très longs. » Mesure : la résolution (`03_match`) est série, ~138 req/min,
et le coût par requête = **0,3s pacing (69%) + ~134ms réseau (connexion fraîche/urllib à
chaque probe)**. Contrainte : AKS/OVH a déjà ban l'IP **sous charge navigateur**, pas sur le
débit de probes → on vise des gains **sans multiplier le débit** (pas de concurrence). Trois
leviers (Romain) :
- **Keep-alive HTTP** (`src/aks_env.py`) : `requests.Session` persistante réutilise UNE
  connexion TLS sur les centaines de probes d'une page (~134ms → ~30-84ms) — même nombre de
  requêtes, ban-safe. `requests` est un accélérateur **optionnel** : `_http_open` garde le
  fallback urllib (contrat identique : HTTPResponse-like sur 2xx, `HTTPError` sur non-2xx,
  `StaffUaRedirectRefused` off-domain, `URLError` transport) → le cœur reste stdlib-only,
  la gate invariants tourne sans dépendance. Cookies désactivés sur la Session (statelessness
  urllib préservée → résolution déterministe). `requirements.txt` créé.
- **Pacing** `AKS_PROBE_DELAY_S` 0,3 → **0,15s** (`src/matcher.py`) : le vrai throttle. Série
  maintenue (pas de concurrence).
- **Cap** `scripts/10 --max-pages` 200 → **30** par défaut : le sweep balaie p_top→p1, et
  l'index submit n'est productif que sur ~28-30 pages ; les pages profondes sont du software/
  obscur qui 404 (matching le plus lent, ~0 candidat). Le flag `coverage_incomplete_max_pages`
  reste (honnête) — devenu le champ `coverage` du recap, plus une halte, le 2026-09-09 (voir
  cette entrée). Override pour un sweep profond délibéré.

Mesuré sur petits lots live : **~255 req/min** (1,85× l'actuel), **0 erreur 429/5xx**. Combiné
au cap (~55% des pages, les plus lentes, sautées), un marchand à feed profond gagne ~4× en
wall-clock. Concurrence gardée en réserve (seul levier qui monte le débit → risque ban).

## 2026-09-08 — matcher : symbole ™ collé dans un token (Eneba)

Les offres Eneba « STAR WARS Zero Company™ … » étaient skippées « name mismatch, missing AKS
words: ['COMPANY'] ». Cause : `normalize_apostrophes` fait un NFKC (voulu, « Empress Ⅱ » →
« II ») qui **décompose aussi ™ (U+2122) en les LETTRES « TM »** → « Company™ » → « COMPANYTM »
→ R01 échoue. Corrigé dans `tokenize` : retrait des symboles marque/service/copyright
(`™ ℠ ® © ℗`) **AVANT** le NFKC, remplacés par une espace (un symbole collé « Halo®Deluxe »
splitte quand même). Live : les 2 Eneba redeviennent candidates (Deluxe/GLOBAL, Standard/EU) ;
régression NFKC « Ⅱ » → II préservée.

## 2026-09-08 — matcher : R25 (skip doublon) RETIRÉ + pre-order = statut, pas produit

Sur Phantom Blade Zero (aperçu by-urls), 4 offres légitimes étaient ignorées à tort.
**(1) K4G "Digital Deluxe Edition PRE-ORDER"** → skip R16 "extra words: ['PRE','ORDER']" :
`PRE-ORDER` est un **statut de sortie**, pas un mot produit (le même jeu/édition en
pré-commande = même produit). `extra_significant_words` retire désormais la collocation
`PRE ORDER` et le token `PREORDER` — jamais quand `BONUS` suit (`PREORDER BONUS` reste une
édition-contenu distincte, skip amont `precheck_skip`). Phrase-level, pas du noise brut :
un vrai "Order"/"Pre" ailleurs reste significatif. Résultat : K4G → Deluxe(7)/GLOBAL(2) et
Deluxe(7)/EU(9), toutes deux nouvelles (K4G n'y était pas). **(2) Kinguin "Deluxe"/"Standard"**
→ skip **R25** "already lists a price". **R25 est RETIRÉ (Romain)** : une offre en **pending
est à ajouter, point** — on ne teste plus "déjà sur AKS". L'ancien garde (2026-07-15, batch
matché périmé) matchait par `merchantName` et sur-bloquait sur un prix d'un autre canal /
auto-sync AKS (id marchand page 47 ≠ store feed 58) ; la péremption est désormais couverte
par le pending feed stable + prove-gone au submit. `prices` reste extrait (routage/diag),
plus une source de skip. Deux sites retirés (chemin principal + software), doc §6 + AGENTS.md
"Reviewed decisions" (ne pas ré-ajouter). Live : les 4 offres → candidates. Suite verte.

## 2026-09-08 — matcher : « Key » nu de furniture retiré par le slug de l'URL

En confirmant l'aperçu top-15, plusieurs offres Minecraft légitimes (« Minecraft Java &
Bedrock Edition (PC) GLOBAL », « Minecraft Java Edition United States ») étaient
false-skippées « name mismatch, missing AKS words: ['KEY'] ». Cause : l'og:title de la
page 216 donne « Minecraft **Key** » et `extract_aks_name` préserve délibérément un « Key »
final (un vrai nom peut finir par Key — The Key / Skeleton Key), donc R01 exigeait « KEY »
dans le titre de l'offre. Le titre seul ne distingue pas furniture d'identité — **le slug
de l'URL, si** : `minecraft` ne porte pas « key » → le « Key » est de la furniture.
Ajouté `_strip_furniture_key(name, slug)`, appelé dans `_resolution_from_body` (choke point
slug+body, couvre pinned ET slug-guess) : retire un « Key »/« Keys » final si le slug ne le
porte pas ; sinon (`the-key`, `skeleton-key`) intact ; jamais réduit à vide ; slug vide →
conservateur. Live page 216 : nom résolu « Minecraft », les 3 offres deviennent candidates
(éd. 2063 / java, région 1), Terraria reste skippé (missing MINECRAFT). Romain 2026-09-08.

## 2026-09-08 — matcher : mot plateforme dans un nom d'édition = bruit de résidu (R39)

En creusant Minecraft (2 pages AKS), une offre « Minecraft Windows 10 Edition » était
skippée « produit étendu » sur la page 216 alors que l'édition « Windows 10 Edition » (140)
existe. Cause : `extra_significant_words` retire le mot PLATEFORME « Windows » de l'offre
(extras → `['10']`) mais l'édition garde `{WINDOWS,10,EDITION}` → le résidu du garde-fou
R39 (`_EDITION_RESIDUE_NOISE`) contenait WINDOWS, absent du set format-only → skip
asymétrique. Corrigé : `_EDITION_RESIDUE_NOISE = NOISE_TOKENS − tiers` (les mots
plateforme/format/région de NOISE_TOKENS sont du bruit ; les tokens de TIER — DELUXE/
ULTIMATE/GOLD/GOTY/… — restent distinctifs et échouent-fermés). Live : « Windows 10
Edition » → éd. 140, J&B (2063) / Bedrock (1010) inchangés, garde-fou tier intact (287→288).

## 2026-09-07 — matcher : `extract_aks_name` — noms AKS pollués par le marketing

En creusant pourquoi GTA 5 / BG3 / Helldivers 2 sortaient à 0 candidat, trouvé que
`extract_aks_name` laissait du texte marketing dans le nom (3/15 top-popular) : les
strips ancrés en `$` échouaient quand l'og:title portait le suffixe « - AllKeyShop.com »
(« GTA 5 **Steam Key** »), et la grammaire « Steam Key **at best Price (PC)** » n'était pas
gérée (« Baldur's Gate 3 Steam Key at best Price (PC) »). Ces mots parasites (STEAM/KEY/
PRICE/PC) devenaient des mots R01 requis → des offres réelles false-skippées. Réécrit :
strip du préfixe « Buy » + du suffixe site D'ABORD, puis coupe au PREMIER marqueur de
furniture (cd/plateforme + Key, « at best Price », « Compare Prices ») — un « Key » nu
reste préservé (The Key / Skeleton Key : un marqueur exige toujours cd/plateforme avant
Key). Live : GTA 5 → « GTA 5 », BG3 → « Baldur's Gate 3 », Helldivers 2 → « Helldivers 2 ».
Les 11 grammaires existantes inchangées (suite matcher verte, 287).

## 2026-09-07 — by-urls : accepter le format d'URL AKS `compare-and-buy`

`extract_slug` (scripts/11) ne connaissait que `buy-<slug>-cd-key-compare-prices/` et
`buy-<slug>-<platform>-account-compare-prices/`. Quelques anciens produits (Minecraft) ne
vivent QUE sous `compare-and-buy-cd-key-for-digital-download-<slug>/` (le format moderne
`buy-…` renvoie 404) → une URL top-popular légitime était rejetée « not an AKS product
URL ». Le parser accepte désormais aussi le préfixe `compare-and-buy-` de façon GÉNÉRALE
(milieu `cd-key-for-digital-download-` optionnel → slug propre quand présent). Le slug ne
sert que de gate + métadonnée (`AksResolution.slug`) ; l'identité produit vient du body,
donc la résolution live de Minecraft passe (id 216, 9 éditions, 13 régions). Formats
existants inchangés (tests de slug verts).

## 2026-09-07 — Revue Romain du pull e13ea6c..3a6278b (findings + résiduels)

Audit du lot Fable par Romain : 2 findings directs corrigés + 2 P2 résiduels antérieurs
traités (durcissements fail-closed).

- **P2 — validation `store_id` de `feed_url` incomplète** (`extractor.py`). Le fix `[39]`
  ne refusait que `''`/`0` alors que le contrat promet « entier ≥ 1 » : `-1`, `'abc'`, `3.7`
  et un ` 127 ` padded produisaient encore des `&store=` invalides/non normalisés.
  `feed_url` n'accepte plus que `None` (vue tous-stores) ou un **entier décimal
  strictement positif**, utilisé sous sa **forme normalisée** (`[0-9]+`, `int()` — pas de
  signe/espace/zéros de tête, rejette les chiffres non-ASCII).
- **P3 — espace final historique** dans `docs/CHANGELOG.md:206`. Retiré.
- **Résiduel P2 — corroboration `nav_max=0` mise en cache entre sweeps** (`extractor.py`).
  La sonde p=2 (fix `[20]`) était faite UNE fois par run ; un feed qui GROSSIT en
  multi-page (même drift nav) après le sweep 1 était alors silencieusement tronqué. Elle
  est re-corroborée à CHAQUE sweep → abort fail-closed au lieu d'une couverture mensongère.
- **Résiduel P2 — vide transitoire de `_read_one_page`** (`scripts/11`). `feed_ui=True +
  0 ligne` était cru dès la 1ère lecture (faux « 0 résultat » si les lignes rendent en
  retard). Empty-confirm ajouté (une re-lecture 0-wait puis le backoff de render-race),
  cohérent avec l'extractor/submitter — jamais un 0 silencieux sur un blip.

## 2026-09-06 — Gros audit Fable : P3 env/contracts (lot O — dernier)

Derniers findings CONFIRMÉS — clôt les 39.

- **[39] `feed_url` émettait l'URL-piège store arbitraire pour `''`/`0`** (`extractor.py`) →
  `&store=` / `&store=0` que AKS résout silencieusement vers UN store arbitraire. Seul
  `None` peut lâcher le filtre (vue tous-stores) ; `''`/`0`/`'0'` lèvent `ValueError`.
  Le gate admin `start_extract` durci à `int(store_id) >= 1` (« 0 ».isdigit() passait).
- **[40] redirect staff-UA hors-domaine refusé renvoyait `ok=True`** (`aks_env.py`) —
  contredit le contrat fail-closed (le code 3xx est dans ACCEPTED_AKS_STATUSES). Exception
  dédiée `StaffUaRedirectRefused` → `http_get` force `ok=False` (un refus est un miss
  fail-closed, jamais un succès).
- **[41] `RawSnapshot.create` levait ValueError/TypeError brut et tronquait les floats**
  (`contracts.py`) sur `pages_scanned`/`feed_last_page`. Type-check AVANT coercition (comme
  P3-7) : un non-int lève `ContractError` (typé), un float n'est plus tronqué, bool rejeté ;
  le clamp-négatif documenté de feed_last_page est conservé.

## 2026-09-06 — Gros audit Fable : P3 admin app (lot N)

- **[35] le champ body `by` écrasait l'identité authentifiée** sur chaque déclencheur
  d'écriture (`app.py`) → attribution d'écriture FORGEABLE. Précédence inversée partout :
  `str(self._basic_user() or body.get('by') or 'operateur')` — l'authentifié gagne, le
  body ne peut plus usurper l'attribution (9 sites).
- **[36] `do_GET` sans drain de corps (AS3)** → un GET-avec-corps laissait ses octets sur
  le flux keep-alive HTTP/1.1 → la requête suivante parsait depuis le milieu du corps
  (desync reproduit). `_drain_body()` (avec le chemin 413/close) est appelé en tête de
  `do_GET` comme dans `do_POST`.

## 2026-09-06 — Gros audit Fable : P3 sweep + triage (lot M)

- **[31] `all_gone` acceptait des absences FENÊTRÉES comme « prouvées par un full scan »**
  → les moves d'une liste étaient silencieusement sautés (offres hors fenêtre page-hint).
  Le mover pose désormais `entry['skip_scope']='window'|'whole_feed'` ; scripts/10 ne
  compte QUE `whole_feed` dans all_gone et remonte `window_missed` ; triage surface
  « window-missed — re-run sans --page-hint » et continue (jamais de mis-move).
- **[33] la sweep passait `--pace` à `05_submit`** qui n'a que `--pace-pages`/`--pace-offers`
  → `--pace` = préfixe AMBIGU → chaque sweep pacée haltait à son premier submit. Mappé sur
  les deux vrais flags (même spec Pacer).
- **[34] `scripts/10` sortait 0 même après un halt fail-closed** → un superviseur voyait
  un exit vert. Exit non-zéro dès que `recap['halted']` ≠ None/'operator_stop'.
- **[38] `execute_page_moves` vérifiait `operator_stop` APRÈS le `continue` all_gone et le
  fail moved<1** (`triage.py`) → un stop coïncidant avec moved==0 était avalé (ignoré,
  liste suivante traitée) ou mal-rapporté « moved 0 not validated ». Hissé juste après
  `_move_phase_broken(c)`, avant la branche moved<1 (parité avec la phase batch).

## 2026-09-06 — Gros audit Fable : P3 submitter catalog (lot L)

- **[28] `fetch_session_catalog` ne vérifiait jamais les résultats des sondes dropdown**
  (`submitter.py`) → `ok:True` avec des masters vides/illisibles → un catalogue INUTILISABLE
  qui brûlait tout le batch avec un blocker par-offre trompeur. Exige désormais
  `regions.ok` ET `editions.ok` ET des `master_options` non vides avant `ok:True` ; sinon
  `{ok:False, reason:'catalog_probe_unreadable'}` (le caller avorte d'emblée).

## 2026-09-06 — Gros audit Fable : P3 mover (lot K)

- **[29] `_reverify_row` adoptait la PREMIÈRE ligne même-chemin** : deux listings
  partageant un chemin URL (GLOBAL implicite + région-spécifique) → si le sibling
  différemment-nommé venait en premier, une offre encore présente devenait un
  `identity_mismatch` TERMINAL. Désormais on choisit la ligne même-chemin dont le NOM
  matche le plan ; une seule propre → adopte ; plusieurs → retriable ; terminal seulement
  si TOUTES les lignes même-chemin contredisent le nom.
- **[30] scan RV2 unitaire plafonné au max_pages du feed SOURCE** → une liste cible
  profonde rendait un Apply canary committé déterministiquement UNKNOWN. `_verify_on_target`
  utilise `max(max_pages, TARGET_SCAN_MAX_PAGES)` comme `_verify_group_on_target` (l'arrêt
  sur URL garde le cap généreux bon marché).
- **[32] register batché sondait `_bulk_row_present` avec l'id de scan STALE** avant la
  relocalisation par URL → une rotation d'id (re-import) bloquait à tort une offre
  présente et 10 blocages haltaient tout le store. `_reverify_row` (reloc URL + refresh
  id) est appelé D'ABORD, puis la sonde de présence utilise l'id rafraîchi (parité avec
  `Mover._move`).

## 2026-09-06 — Gros audit Fable : P3 cdp_session (lot J)

- **[27] exception JS in-page → `RuntimeError` nu** qui contournait `FEED_UNREADABLE_EXCS`
  → un crash d'evaluate post-clic échappait au handler UNKNOWN, sans entrée
  submit_plan.json (état de l'offre perdu). Lève désormais `CdpCommandError` (dans
  FEED_UNREADABLE_EXCS → chemin UNKNOWN fail-closed).
- **[42] ping WS pendant un poll idle** → un keepalive ping suivi de silence, SANS
  fragment de données accumulé, transformait un timeout bénin en `CdpCommandError`
  « stalled mid-frame » (sur-abort, possiblement après un clic dispatché). Le premier
  octet de la trame SUIVANTE (entre trames) renvoie None sur timeout quand aucun message
  n'est en cours ; un message PARTIEL (fragments bufferisés) lève toujours (stall réel).

## 2026-09-06 — Gros audit Fable : P3 matcher (lot I)

- **[25] édition logicielle unique auto-prise malgré un signal de licence contradictoire**
  (`matcher.py`) : une offre « 1 Year » / « OEM » / « 5 PC » sur une page à édition unique
  « Lifetime » était saisie en Lifetime (mauvaise licence). Avant l'auto-prise, tout token
  licence/durée non matché (`LIFETIME/OEM/RETAIL/LTSC/\d+ (PC|DEVICES|MONTHS|YEARS)`) →
  skip fail-closed. Sans signal → auto-prise conservée (R31).
- **[37] scan plateforme URL G2A** ratait `gog-com` / `epic-games` / `ea-app` / `battle-net`
  key-slugs + EA/ORIGIN/BATTLENET → clé région-locquée en STEAM implicite. Grammaire de
  collocation étendue (suffixe `-com/-games/-app/-net` entre le mot plateforme et « key »)
  + `_URL_PLATFORM_WORDS` (superset URL-only, pour ne pas polluer le scan titre). Un mot
  plateforme dans le nom du jeu (non collocaté à « key ») n'est jamais mal-lu.

## 2026-09-06 — Gros audit Fable : P2 AS1 TOCTOU (lot H)

- **[15] TOCTOU AS1 dans `start_submit`** (`submit_manager.py`, `app.py`) : le GO
  sha-vérifiait `approved.json` sur UNE lecture, mais l'enfant `05_submit` re-lisait le
  chemin LIVE — une sauvegarde de validation concurrente (autre onglet/opérateur) entre
  le GO et la lecture de l'enfant échangeait tout le triple (cohérent en interne), donc
  l'enfant re-vérifiait et soumettait un lot DIFFÉRENT de celui lié au GO. Corrigé comme
  le chemin by-urls (2026-08-25) : lecture des octets une seule fois, sha vérifiée sur
  CES octets, snapshot immuable `approved.submitted.json` remis à l'enfant (même run_dir,
  donc out_dir/candidates/validation/submit_plan restent là où le manager lit). Un swap
  de candidates/validation fait échouer-fermé la re-vérification de l'enfant, jamais une
  soumission du mauvais lot. Défense en profondeur : `_post_validation` refuse (409
  `run_active`) une re-validation tant qu'un run est actif sur ce run_dir.

## 2026-09-06 — Gros audit Fable : P2 scripts browser-gate (lot G)

- **[17] `06_move` sans SIGTERM coopératif** : le sweep « Arrêter » tuait un enfant de
  move réel en plein Apply. Miroir de `05_submit` : handler `_on_term` → flag `_STOP`,
  `should_stop=lambda: _STOP` passé à `Mover.run` (arrêt à une frontière de move, jamais
  mid-Apply).
- **[24] `scripts/11` pilote l'onglet AKS sans gate invariants ni endpoint validé** :
  ajout du gate `build_report(endpoint)` (vert ET authoritative) AVANT d'ouvrir la
  session — `build_report` inclut `validate_official_cdp_endpoint`, donc un `--endpoint`
  non-officiel échoue aussi le gate. Défense en profondeur : `ReadOnlyCdpSession.open()`
  refuse désormais tout endpoint non-officiel (couvre `SubmitSession`/`WriteSubmitSession`
  qui en héritent, et tout futur point d'entrée qui oublierait le gate).

## 2026-09-06 — Gros audit Fable : P2 admin (lot F)

Findings P2 CONFIRMÉS côté console admin (`src/admin/`).

- **[10] override plateforme sans re-choix de région** (`validation_io.py`) : les ids
  région sont PAR PLATEFORME (sans recouvrement). Changer la plateforme sans re-choisir
  la région laissait l'id région dans l'ancien namespace → l'écran de l'opérateur et
  l'écriture divergent. Un override plateforme seul est refusé fail-closed
  (`platform_region_mismatch`) ; l'opérateur re-choisit la région (validée contre le
  catalogue de session). Un override plateforme + région ensemble reste accepté.
- **[11] sweep safe-auto réel sans GO serveur** (`app.py`, `auto.js`) : `/api/data-entry/
  auto` écrit sans validation par-offre mais ne demandait AUCUN GO tapé côté serveur
  (contrairement à `_post_sort_move` et à la saisie by-urls). Ajout du même gate
  `confirm==GO` (400 `confirm_required` sinon) + `auto.js` l'envoie.
- **[16] Arrêter SIGKILL un Move/Apply de tri** (`submit_manager.py`) : `sort_canary` /
  `sort_batch` (runs d'ÉCRITURE) manquaient de `_STOP_GRACE_BY_KIND` → grâce par défaut
  12 s → SIGKILL en plein Apply. Ajoutés à 90 s (les kinds read-only gardent la grâce
  courte).

## 2026-09-06 — Gros audit Fable : P2 by-urls submit (lot E)

Findings P2 CONFIRMÉS sur le chemin de saisie par URLs (`src/data_entry_auto.py`,
`scripts/12`) — parité avec Safe-Auto (scripts/10).

- **[12] contournement de l'allowlist marchand** : `run_by_urls_submit` écrivait vers
  N'IMPORTE quel (marchand, store) issu de l'aperçu — il ne re-vérifiait pas l'allowlist
  `AUTO_MERCHANTS` que Safe-Auto impose. Pré-vol ajouté : tout groupe hors-allowlist
  refuse le batch ENTIER fail-closed (tout-ou-rien, avant le moindre `05_submit`).
- **[13] `created` dérivé d'une sous-chaîne « gone »** du texte humain `post_save` au
  lieu du booléen déterministe `submitted` de 05_submit → un vrai create dont le
  `post_save` omet « gone » était compté 0, un « …not gone… » aurait pu compter faux.
  Utilise `bool(e["submitted"])` ; `post_save` reste pour l'affichage.
- **[14] `submit_plan.json` illisible après exit 0 = marchand PROPRE** (P2-14 jamais
  miroité depuis scripts/10) → `plan_readable` suivi ; `ok = rc==0 and plan_readable`,
  donc `clean()` halte le batch au lieu de créditer un plan illisible.

## 2026-09-06 — Gros audit Fable : P2 mover (lot D)

Findings P2 CONFIRMÉS côté `mover.py` — sécurité du chemin d'écriture (Move-to-List).

- **[18] collision d'identité au montage du batch** → deux entrées de plan peuvent
  partager UN chemin URL marchand (listing GLOBAL implicite + listing région-spécifique
  sur un même chemin Kinguin, ou variantes quantité/devise — le sibling même-chemin
  P2-12) ou, après rotation d'id, un offer_id. `pending` clé par `_url_key` seul →
  la seconde ÉCRASAIT la première → une entrée disparaissait du rapport pendant que la
  ligne du sibling était physiquement déplacée (écriture mal-routable) ; le chemin
  deferred (liste) la traitait deux fois. Nouveau `_batch_intake` : toute collision
  `_url_key`/offer_id est EXCLUE + remontée (l'opérateur la déplace à la main — le
  verify set-wise par url_key ne peut pas attribuer un move à l'une de deux lignes
  même-chemin), jamais silencieusement droppée/doublée.
- **[19] RV2 fenêtré peut fabriquer un faux « moved »** depuis une ligne stale
  même-chemin déjà sur la liste cible. Sous une fenêtre (page-hint), la preuve
  « gone-from-source » du verify était fenêtrée → une offre simplement reflowée HORS
  fenêtre se lisait « gone » ; couplée à un RV2 qui trouve une ligne stale même-chemin
  sur la cible → faux « moved ». Correctif (option a du président) : la preuve
  gone-from-source du verify batché force le WHOLE-FEED dès qu'une fenêtre est active
  (comme déjà pour blacklist) — une offre encore présente sur la source (n'importe où)
  est vue présente → « STILL on source », jamais créditée depuis une ligne stale. Le
  locate initial reste fenêtré (vitesse). Chemin per-offre inchangé (design fenêtré revu,
  `test_page_hint_source_scans_stay_within_window`).

## 2026-09-06 — Gros audit Fable : P2 extractor (lot C)

Findings P2 CONFIRMÉS côté `extractor.py` (couverture read-only — un mensonge de
couverture corrompt tout l'aval).

- **[20] `nav_max=0` non corroboré sur une page 1 pleine** → la boucle `while page
  <= last_page` avec `last_page = max(last_page, nav_max, page)` fige `last_page=1`
  quand la page 1 a des lignes et `nav_max==0` → **p=2 jamais visitée**. Correct pour
  un vrai feed mono-page, mais une nav de pagination dérivée/re-rendue annonce le même
  `nav_max==0` sur un feed MULTI-page → troncature silencieuse annoncée « complète ».
  Sonde p=2 UNE fois : des lignes en p=2 prouvent la nav illisible → abort fail-safe
  (`FeedUnstableError`) ; une over-page vide confirme la page unique. Une seule sonde
  par run (le rendu de la nav est une propriété statique).
- **[21] lignes sans `id` silencieusement droppées** (les DEUX boucles d'union :
  `extract` sweeps + `extract_pages` slice) → une dérive de schéma data-offer devient
  un run « 0 offre, couverture complète ». Une ligne `data-offer` sans id non-vide lève
  désormais `FeedSchemaError` (chaque offre réelle porte un id ; une ligne sans id =
  schéma dérivé ou ligne non-offre). Fail-closed, jamais sous-extraire en silence.

## 2026-09-06 — Gros audit Fable : P2 matcher (lot B)

Suite du lot A. Findings P2 CONFIRMÉS côté `matcher.py` (tests de non-régression,
suite complète verte).

- **[6] pool R23 (E05) par SOUS-CHAÎNE brute** → adoptait un palier SURENSEMBLE de la
  page (« Complete » → « Complete Plus ») ou, pire, son propre palier nommé Bundle sous
  un id ≠ « 8 » (invisible au skip bundle) → **un bundle saisi**. Remplacé par l'égalité
  de jeu de tokens `_edition_key` (bruit de format retiré, GOTY étendu) + exclusion
  explicite BUNDLE/TRILOGY. Préférence nom-exact conservée → « Complete Pack »(92) reste
  l'adoption endossée (PACK = bruit de format). L'ancienne ambiguïté « Complete Pack »
  vs « Complete Deluxe Pack » disparaît (paliers distincts, désormais bien départagés).
- **[9] formes URL US/UK manquantes** (fusion 2 findings) : le slug `-usa`, un « USA »/
  « (USA) » nu en milieu de titre (US) et le code `-gb` (UK) tombaient en GLOBAL
  implicite → clé région-locquée mondiale. Ajoutés au `detect_region`, tous slot-gated
  (`_url_region_code`) → « among-us » et formes en milieu de slug jamais déclenchées.
  (Le slot `-uk` + `gmg_gift_uk` [8] avaient été traités au lot A.)
- **[7] resolve_software_region — DÉCLINÉ par Romain (2026-09-07), gardé tel quel.**
  L'auditeur signalait qu'une offre logicielle US/EU-locquée est classée sous une région
  page GLOBAL/PUBLISHER unique. **Ça CONTREDIT le choix R31 revu par Romain** (2026-08-11,
  `test_region_lone_country_is_not_forced` : « une région GLOBAL/PUBLISHER unique est
  prise pour un label inconnu » — les licences logicielles sont globales, le label région
  marchand est du bruit). Remonté à Romain, qui a tranché « laisse tel quel, ne durcis
  pas ». Comportement inchangé — décision délibérée, à ne pas re-durcir (les re-audits
  le re-signaleront).

## 2026-09-06 — Gros audit multi-agents (Fable) : correctifs P1 fail-open (lot A)

Audit adversarial de TOUT le codebase (13 « diggers » + un président Fable qui
dédoublonne / recoupe / classe) → 39 findings CONFIRMÉS. **Lot A = les 5 fail-open
P1** — les seuls défauts pouvant faire *entrer* une clé région-locquée ou *prouver à
tort* une offre « disparue » (le reste est fail-safe : sur-skip / sur-block).
Chaque correctif : commit atomique + test(s) de non-régression, suite complète verte.

- **P1 — vocabulaire région à la traîne** (`matcher.py`). `FORBIDDEN_REGIONS` /
  `_URL_FORBIDDEN_CODES` avaient divergé de `aks_lists._BLACKLIST_REGION_KEYWORDS` +
  `_REGION_LIST` : un lock encodé UNIQUEMENT dans le slug marchand
  (`…-steam-key-philippines`, `…-latin-america`, `…-poland`) échappait aux deux scans
  → `detect_region` tombait en GLOBAL implicite → **clé région-locquée saisie
  mondialement**, auto-approuvée en sweep safe-auto. Ajouté (titre + URL) : LATIN
  AMERICA / PHILIPPINES / MALAYSIA / INDONESIA / THAILAND / MEXICO / CHILE / COLOMBIA
  / PERU / POLAND / UKRAINE / CANADA / AFRICA / OCEANIA ; codes 2-lettres bas-collision
  (`pl/ua/mx/ph/vn/th`, gate slot). VIETNAM = URL-slot-only (`_URL_ONLY_FORBIDDEN_REGIONS`,
  gate `_url_region_code`) car il collisionne les jeux de guerre (« Rising Storm 2:
  Vietnam »). Routage en phase : Poland/Ukraine ajoutés à `_BLACKLIST_REGION_KEYWORDS`
  (→ Blacklist 8) ; Canada/Africa → leur liste dédiée (33/35).
- **P1 — codes langue = locks région avalés** (`matcher.py`, `extra_significant_words`).
  Un code final à la fois langue ET lock gris (RU/TR/AR/PL/UA) était neutralisé comme
  bruit de langue → une clé région-locquée devenait candidate GLOBAL/GIFT auto-validée.
  Ces codes (`_REGION_LOCK_LANG_CODES`) restent un extra significatif → skip fail-closed
  (« different/expanded product »). Les langues bénignes (FR/DE/EN…) restent avalées.
- **P1 — gift US/UK élargi en GLOBAL** (`matcher.py`, `detect_region`). Les deux
  branches gift résolvent le bucket EXACT par base, sans fallback global silencieux :
  `gift_us` / `gift_uk` / `gmg_gift_uk` n'existent sur aucune plateforme → gid None →
  skip fail-closed (label et id ne peuvent plus se contredire — la classe de bug P2-8,
  jamais corrigée pour us/uk). Bonus symétrique : slot `-uk` détecté comme base UK
  (miroir du `-us` P2-6b) — un `…-steam-key-uk` lisait GLOBAL implicite.
- **P1 — rescue édition R39 : montée de gamme silencieuse** (`matcher.py`,
  `match_extras_to_page_edition`). La branche « seule édition compatible » adoptait
  l'édition même quand elle portait un mot de GAMME distinctif absent du titre
  (`want={KNIGHTS} ⊆ {KNIGHTS,DELUXE,EDITION}`, DELUXE étant du bruit dans `want`) →
  écriture wrong-tier auto-approuvée. Elle exige désormais un résidu = bruit de FORMAT
  pur (`_EDITION_RESIDUE_NOISE`, garde les mots de gamme distinctifs ; `NOISE_TOKENS`
  est le MAUVAIS filtre — il liste DELUXE/ULTIMATE en bruit). Rescue Eisenwald
  « Knights Editon » (typo) préservé.
- **P1 — prove-gone : stall in-range pris pour past-the-end** (`submitter.py`,
  `_scan_feed`). `bc2507a` fait classer par `_read_feed_page` tout over-page vide
  nav_max=0 comme past-the-end (juste pour un feed mono-page). Sur un feed multi-page,
  un stall de page-N sous charge CDP rend la MÊME forme — mais une page antérieure a
  déjà annoncé nav_max≥N. Garde inter-pages (`nav_max_seen`) : contradiction →
  `FeedScanError`, jamais un faux « gone » (créa phantom). Feed mono-page
  (`nav_max_seen` 0 < page) et shrink légitime (nav courant ≠ 0) épargnés.

Reste (lots suivants) : 34 findings CONFIRMÉS hard-rule P2 + P2/P3 clairs.

## 2026-09-05 — Re-audit multi-agents de TOUTE la campagne (30 auditeurs adversariaux)

Re-audit adversarial de chaque correctif de la campagne 2026-09-02 (un auditeur par
fix, relecture du code courant + repro concrète). **25/28 SOLID** ; 2 auditeurs morts
sur erreur API transitoire (P2-6+P2-8, P3-7 — tous deux déjà vérifiés SOLID lors de
leurs tours dédiés). **3 anomalies, toutes fail-safe (aucune entrée/gone/phantom)**,
corrigées + vérifiées SOLID (suite complète 1260 tests) :

- **P1-3 — régression réintroduite par P1-3 lui-même** (`bc2507a`). P1-3 avait resserré
  le retour past-the-end de l'over-page à `1 <= nav_max < page`, supprimant le cas
  `nav_max == 0`. Or AKS renvoie `nav_max=0` pour une page unique, et `_scan_feed`
  n'est pas borné par nav_max → sur un feed **mono-page** il marche jusqu'à l'over-page
  (p=2, vide, nav_max=0) → aucun branchement de retour → **raise fail-closed → tout le
  scan avortait** (over-block de toutes les offres du feed). Retour past-the-end
  restauré après la boucle de confirmation A1 (miroir de l'extracteur ; plus sûr que
  l'avant-P1-3 grâce aux re-checks is_login/href/feed_ui). Test : feed mono-page
  `nav_max=0` (le fake modélisait `nav_max=1`, ce qui masquait le bug).
- **P3-6 — incomplet** (`f069591`). Le libellé window-aware ne couvrait pas le 3e site,
  le chemin `--deferred` par-store (`_drive_batched_deferred`), qui hardcodait encore
  « proven by the source scan » sous page-hint (scan pourtant windowed). Routé via
  `_absent_from_source_reason(ctx)` comme les deux autres sites. Label-only, no-write.
- **P2-7 — sur-promesse doc** (`36ec0b8`). Le commit affirmait que le word-boundary
  « ne peut pas créer de leak » : trop fort — un token monnaie/gift collé à un préfixe
  de marque minuscule (« Amazon eGift Card », « Garena eCoins ») échappe au precheck.
  Mais le filet AUTORITAIRE est en aval (pas de page jeu / R01 / extra-words) et les
  attrape (vérifié : « no AKS product page found »), donc **rien n'est saisi**. Doc-only :
  precheck = défense-en-profondeur, pas le filet ; ne pas durcir (indistinguable d'un
  mot-jeu embarqué). Test backstop (échappe le precheck + skip aval).

Reste : la sonde P2-13 (déjà auditée SOLID après tes 2 anomalies, commit `833c323`).

## 2026-09-02 — Multi-agent audit : correctifs P1 + P2 (matcher, submitter, mover, admin)

Audit adversarial multi-agents du projet (31 findings). Chaque correctif est un
commit atomique avec test(s) de non-régression et a été contre-vérifié par un
sous-agent adversarial. Les règles par-étape correspondantes sont dans
[`EXECUTOR_RULES.md`](EXECUTOR_RULES.md). Suite complète verte (**1217 tests**).

**P1 — faux succès / mauvaise saisie (tous corrigés, poussés) :**

- **P1 (langue)** — `181d996` : un code langue (`EN`, `FR`, …) n'est traité comme
  bruit que **lorsque TOUS les tokens du nom AKS sont couverts** (`aks_seen == aks`).
  Évite « The Garde » ⇄ « Garde », « A No Man's Sky » ⇄ « No Man's Sky ».
- **P1-1/P1-2 (éditions jeux)** — `e84af71` (R40) : les éditions devinées sont
  **page-vérifiées** contre la page résolue par égalité d'ensemble de tokens
  (modulo bruit de format `EDITION/PACK/DIGITAL/VERSION…`, alias GOTY), gaté sur
  `e05_page_verified`. Plus d'adoption d'un mauvais palier par sous-chaîne.
- **P1-3 (faux « gone » sur blanc transitoire)** — `d2a7d89` : `nav_max=0` est
  **confirmé** par re-lecture DOM (`EMPTY_CONFIRM_WAITS`, aligné sur
  `FEED_UI_RENDER_WAITS`) avant de prouver la disparition.
- **P1-5 (nav wedgée)** — `b7b8bb1` : l'extracteur **vérifie l'atterrissage** sur
  la page navigée (`href`/`_page_param`, `WedgedNavigationError`) avant de lire.
- **P1-4 (ligne ré-idée)** — `eb4d619` : le mover **relocalise par URL stable**
  une ligne ré-idée avant de la bloquer en terminal ; identité URL-first.

**P2 — durcissements fail-closed (corrigés, poussés) :**

- **P2-9 puis A3 (validated_by)** — `9b48662` + `b95e8a2` : `validated_by`
  autorise une écriture live (non-répudiation) ⇒ c'est l'**identité authentifiée**
  (Basic nginx), jamais le corps client ; **sans identité Basic fiable la
  validation est REFUSÉE fail-closed** (403 `authentication_required`), plus aucun
  fallback non authentifié.
- **P2-1 puis A2 (clic dégradé)** — `6e1ad92` + `6162731` : une vraie écriture est
  **trusted-only** ; le chemin de clic natif/dispatch dégradé est **supprimé**
  (plus d'opt-in `allow_degraded_click`).
- **P2-2 (allowlist marchands)** — `eafe4d0` : l'allowlist du mode auto est
  imposée au **cœur CLI déterministe** (`scripts/10`), pas seulement côté HTTP.
- **P2-3 (preview incomplète)** — `2ddfdfc` : le cœur submit by-urls **refuse une
  preview incomplète** (abandon/non-résolu/erreur/tronqué/count-mismatch), miroir
  du gate manager.
- **P2-4 (MOVE mal routé)** — `964017e` : `suggest_target_list` ne route **que** les
  raisons `skip category: …`, et sur le **token de catégorie** (avant toute
  parenthèse), jamais un free-substring de la raison entière. Un mot de titre
  incident dans une raison hors-catégorie (`extra words: ['account']`) ne peut plus
  déclencher un MOVE→liste sous `--move-execute` (prolonge Audit L8). Sweep old-vs-new
  sur tout `CATEGORY_SKIP` : zéro diff ; offres account réelles routées par
  `sort_plan.is_account_offer`.
- **P2-7 (CATEGORY_SKIP sous-chaîne + token SOFTWARE)** — `5e87768` : `precheck_skip`
  matche `CATEGORY_SKIP` en **mots entiers** (`_category_skip_pattern`), plus en
  sous-chaîne brute — fini les sur-skips de jeux valides ("Stratagems"→GEMS,
  "Checkpoints"→POINTS, "Laptop Upgrade"→TOP UP). Bord **lettre-only** : un token
  collé à un CHIFFRE (montant) skippe encore ("5000Gems"), collé à une LETTRE passe
  ("Gemstone") ; pluriels `S`/`ES` conservés ("Vouchers", "Season Passes"). Token
  `SOFTWARE` **retiré** (désormais classifieur `is_software`, pas un skip — atteint
  le chemin software R31). Résidu fail-safe documenté : "Gems of War" reste skippé
  (règle games-only). Vérifié : le patch ne peut qu'AJOUTER des matches → aucun
  nouveau leak, seuls des sur-skips fail-safe.
- **P2-6 (région interdite URL-encodée)** — `d1f0e78` : `precheck_skip` scanne aussi
  le **path de l'URL** pour `FORBIDDEN_REGIONS` (query strippée, bruit marchand retiré,
  word-boundary, même normalisation que le titre) — une région interdite présente
  seulement dans l'URL (Gamivo `…-brazil`) ne tombe plus en GLOBAL implicite. Même
  raison `forbidden region: <label>` → routage identique.
- **P2-6b (codes région 2-lettres + base `-us`)** — `3613feb` : les deux résidus de
  P2-6/P2-8 fermés. `_url_region_code` capte un code 2-lettres UNIQUEMENT dans un
  **region slot** (précédé d'un marqueur key/gift/plateforme ET en fin de path, suffixe
  produit `-i123`/`-p123` toléré) → exclut `among-us`, `lost-in-random`, `war-thunder`.
  Codes interdits `ru/tr/br/ar/cn/kr/jp` → skip routé (`in`/Inde exclu, trop de
  collisions ; `-india` complet déjà couvert). Le slot `-us` fixe la base US (compose
  avec P2-8 : EPIC US green gift → `gmg_gift_us` 635 ; STEAM sans bucket → skip
  fail-closed). Résidu pré-existant documenté : un **plain** gift US (`-gift-us`) entre
  encore sous le bucket gift global (la branche plain-gift ne gère que EU).
- **P2-8 (GMG green-gift → GLOBAL silencieux)** — `d1f0e78` : `detect_region` résout le
  bucket `gmg_gift` **exact par base**, sans fallback silencieux vers le gmg_gift
  GLOBAL. STEAM n'a pas `gmg_gift_us`, EPIC pas `gmg_gift_eu` ; l'ancien `or` rendait
  l'id GLOBAL sous un label "US"/"EU" (label ≠ id, région élargie, clé restreinte
  entrée mondialement). Base manquante → id `None` → skip fail-closed `no region id`
  (label et id ne peuvent plus diverger). Buckets existants inchangés.

**Lot d'hygiène P2/P3 — 15 findings restants (terminé).** Triage read-only en
parallèle (15 sous-agents, workflow `hygiene-audit-assess`), puis correctifs par
lot-de-fichier, chacun contre-vérifié ; diff complet re-vérifié adversarialement
(SOLID, suite complète **1243 tests**). Fait notable : le triage a **corrigé la
prémisse** de plusieurs findings — plusieurs « bugs » étaient en fait du fail-closed
délibéré ⇒ disposition **doc/test-only** plutôt qu'un correctif risqué.

- **Corrigés (code) :** P3-1 (`1c5ce59`, resolve fallback aussi sur page `-key-` nue),
  P3-2 (`1c5ce59`, whitelist skin `^Skin Deep` au lieu de `^Skins?`), P2-14
  (`6e4421e`, plan illisible après exit 0 → halt fail-closed), P3-5 (`6e4421e`,
  approve wrap `except Exception` → StageError typé), P2-10 (`b243004`, alarme SIGKILL
  armée UNE fois par stop), P2-11 (`b243004`, `value` ajouté à `REDACT_KEYS` +
  convergence `_SECRET_KEYS ⊆ REDACT_KEYS`), P2-15 (`b243004`, handler redirect
  host-locked : UA `AKS/Staff` ne fuit plus hors allkeyshop.com sur un 3xx),
  P3-7 (`b243004`, `isinstance(str)` → `ContractError` typé), P3-8 (`b243004`, reason
  d'abort = type d'exception seul, jamais `{exc}`).
- **Doc/label/test-only (comportement fail-closed délibéré, verrouillé) :** P3-3
  (`1c5ce59`, `continue` OST porteur, pas mort — routage testé), P3-4 (`d8a5706`,
  retry FeedScanError-only par conception ; CdpCommandError abort), P2-5 (`d8a5706`,
  scan sweep capé = UNKNOWN → abort intentionnel), P2-12 (`d8a5706`, siblings
  même-chemin → « échec » = fail-safe, ne pas relâcher la clé URL sous peine de
  ré-ouvrir le P0 K4G), P3-6 (`cdb5a5d`, label « WINDOWED » au lieu de « proven » sous
  page-hint), P2-13 (`6e4421e`, wiring nav_max→truncated d'abord DIFFÉRÉ — puis
  **DÉFINITIVEMENT CLOS** live, voir ci-dessous).

**P2-13 — DÉFINITIVEMENT CLOS (résolu live + vrai correctif + cap confirmé global).**
La sonde read-only `scripts/probe_p2_13_search_navmax.py` (lancée sur le VPS,
2026-09-04, commit `f13aa22`) a montré que la page de recherche AKS
`aks-merchant-feeds-search` **ne pagine pas** : `nav_max` toujours 0, `&p=N` re-sert la
même page, tout tient sur UNE page **plafonnée à 300 lignes distinctes** (« Steam »/
« Key »/« a » → 300 ; « e » → 151). Le wiring `nav_max→truncated` différé était donc
**inutile** (nav_max toujours 0). **Vrai correctif** (`f51e969`) : `_read_search_pages`
lit **la page 1 uniquement** et pose `truncated` ⟺ le cap est atteint (≥ 300) ;
l'ancienne heuristique 100-lignes/3-pages **re-lisait la même page** et **flaggait
`truncated` à tort pour tout résultat ≥ 100 lignes** (over-block). Vérifié SOLID (aucun
fail-open ; une recherche par-jeu n'approche jamais le cap). **Cap confirmé GLOBAL**
(`d03f61e`) : re-sonde multi-listes → « a » cape à exactement 300 sur liste 8
(Blacklist) ET 21 (Gift cards), les petites listes renvoient leur vrai compte (< 300),
`nav_max=0` partout. Plus de résidu ouvert sur P2-13 : `SEARCH_RESULT_CAP=300` est un
cap serveur global, étayé sur des listes de tailles très différentes ; la sonde reste
committée pour re-vérifier si AKS change le cap.

Résidus documentés restants (hors périmètre, fail-safe) : `-gift-us` plain gift
(P2-6b), « Gems of War » / « Points2Win » (P2-7/P2-6b), P2-11 sur-redaction cosmétique
de `target_add.value` (id produit, non secret). Campagne d'audit 2026-09-02
**TERMINÉE** — tous P1 + P2 + P3 traités et vérifiés ; **P2-13 définitivement clos**.

## 2026-07-31 — Tri : RV2 target-verify GLOBAL + mega-stores hors-scope (Gift cards)

Opération de tri Gift cards (liste 21) sur le scan frais `20260730-134546-sort`.

**Bug RV2 trouvé + corrigé (commit `d3faec0`).** Store 70 a compté 8 gift cards
« left source but NOT on target » ; un scan tous-stores read-only les a toutes
trouvées SUR la liste Gift cards. `_verify_on_target` / `_verify_group_on_target`
scannaient la liste cible sous le store SOURCE de l'offre (`?store=70`) ; une
liste cible est inter-stores et une offre juste déplacée peut être absente de sa
vue filtrée par store (rotation store/id au ré-import) tout en étant sur la liste.
Fix : scan cible GLOBAL (`store_id=None`) — l'URL marchande est propre au store,
un match global est sans ambiguïté. Ces faux négatifs sous-comptaient les moves ET
gonflaient les échecs → breaker guard + FC3 (refus du store suivant, en partie une
fausse alerte). +2 tests (par-groupe + différé), garde-fou vérifié (échoue sur le
code pré-fix). Actif au prochain run via le spawn sous-processus, sans restart.

**Mega-stores 126 & 162 hors-scope (décision Romain 2026-08-03).** Le feed source
de store 126 fait **920 pages** (~92k offres ; 1783 Gift cards dedans), 162 est
plus gros. La preuve fail-closed « parti de la source » exige un scan
full-coverage — infaisable par-groupe (K× 920 pages), rate-limit-risqué en différé
(plafond account `ERR_CONNECTION_REFUSED`). Même classe que account : un store à
feed source account-scale attend un mécanisme dédié. Petits/moyens stores GC
(92/19/38/127/58/70) faits (~260 déplacées). FC3 acquitté (`--acknowledge-block`).

## 2026-07-30 — Docs: align living docs on cookie-transfer re-auth

Password+2FA Stage 0b was already retired in code (2026-07-29: commits
`b42d878`, `2d8d859`). Living docs still pointed operators at
`scripts/00b_login.py` / `AKS_WP_*`. Aligned:

- `README.md`, `docs/ARCHITECTURE.md`, `docs/EXECUTOR_RULES.md` §9,
  `docs/NOOB.md`, `docs/SUBMITTER_SPEC.md` §8, `ops/BROWSER_RUNBOOK.md` §1.7
  / §3 step 10 — cookie transfer via `/executor/tri` → Se reconnecter.
- `src/admin/static/sort.html` — button title no longer promises a 2FA prompt.
- Historical audit / changelog entries for the old Stage 0b are left as-is.

## 2026-07-29 — Tri batché : robustesse + P1.6 (vérif différée par store) + fixes revue

Suite du tri batché. Deux temps.

**Robustesse (commit `0a789c4`).** `Mover._scan_retry` réessaie un blip
feed/CDP TRANSITOIRE (`FeedScanError`/`CdpCommandError`) jusqu'à 3× sur les scans
**read-only** du chemin batché (locate du drive, vérif source post-Apply, vérif
cible). Un batch Softwares avait avorté en perdant ~8 stores sur un blip après 2 h ;
il survit maintenant. `NotLoggedInError` n'est JAMAIS réessayé ; l'Apply non plus.

**P1.6 — vérif différée PAR STORE (commit `0e39e57`).** Option `--deferred`
(gate `--batch --mode safe`, sans `--limit`). `Mover._drive_batched_deferred` : UN
scan initial → groupe par page → tire les Applies pages **plus-haute-d'abord**
(reflow-safe : déplacer une page haute ne décale que les offres APRÈS elle, jamais
une page basse non traitée → pas de re-scan entre les Applies) → vérifie le store
ENTIER **une seule fois** (`_verify_registered_set`, partitionné par liste cible).
~G× moins de scans sur un store à G pages. **Compromis** : la fenêtre
d'attribution parallèle passe de ~secondes (par groupe) à par-store (~min), bornée
et gardée par le re-check d'identité + la preuve « coché-par-nous ». Refactor :
`_register_apply_page` + `_verify_registered_set` extraits, partagés avec le chemin
par-groupe (comportement inchangé).

Revue adversariale (11 agents) → 6 défauts confirmés (2 HIGH), tous corrigés :

- **HIGH — reflow → skip permanent.** Un opérateur parallèle retirant une offre
  d'une page BASSE pendant la fenêtre par-store faisait remonter les autres ;
  l'offre légitime, plus sur sa page attendue, était bloquée « not present » puis
  ledgerée `identity_blocked` (statut **résolu**) → **exclue à jamais** des runs
  incrémentaux. Fix : `_reverify_row` ne pose `identity_mismatch` que sur une vraie
  contradiction d'identité (name,url) ; `_ledger_status` (hissé au niveau module,
  testable) ne rend TERMINAL que moved / already_gone / identity_mismatch. Toute
  absence transitoire (not-present, vanished, glitch bulk/register/Apply, UNKNOWN,
  still-on-source, `apply_not_confirmed`) reste **hors ledger** → réessayée.
  `apply_not_confirmed` retiré de `sort_ledger.RESOLVED_STATUSES` (il a toujours
  voulu dire « retry »).
- **HIGH — levée mid-passe → drop silencieux.** Une erreur feed/CDP levée par
  `_register_apply_page` sur une page tardive perdait les offres déjà Applied des
  pages précédentes (accumulées, non encore vérifiées). Fix : la boucle différée +
  `_register_apply_page` (région Apply) + le dispatch batché de `run()` forcent
  toute offre in-flight en UNKNOWN + enregistrée + abort, sans jamais dérouler
  `run()` en perdant le plan (09 `break`ait sans capturer `result`).
- **LOW** : vérif différée partitionnée par liste cible ; 09 rejette
  `--deferred --limit` ; couverture UNKNOWN multi-pages (source + cible) ajoutée.

+18 tests (drive différé, reflow-safety, chemins UNKNOWN fail-closed, split
ledger terminal/transitoire, gates CLI). Suite complète verte.

**Console (commit `5811c4a`).** `/executor/tri` : case **« Différé (par store) »**
à côté de « Batché (rapide) », sous-option grisée tant que Batché est off, n'agit
que sur le **Batch complet** (jamais le canary) → ajoute `--deferred`.
`submit_manager.start_sort_move(deferred=…)` assemble l'argv et rejette
fail-closed (`bad_deferred`) les combos que le gate CLI refuse. **Pas encore
tourné en prod** au moment du commit (1er run réel du mode différé à surveiller).

## 2026-07-28 — Tri batché : P1 (Move-to-List groupé) + P1.5 (RV2 groupé) + P2 (gate multi-item) + console

`docs/SIMPLIFICATION_PLAN.md` : la lenteur du tri = le mover à 1 offre/Apply +
~3 scans plein-feed/offre (>1 h pour 213). Fix = batcher le `bulk[item][]`
répétable : enregistrer N offres sur une page source → UN Apply → vérifier le
groupe d'un coup. O(N)→O(pages).

- **P1 — mécanisme (commit `36cffd3`).** `Mover.run(batch=True)` (write-only, OFF
  par défaut — chemins per-offre/dry-run/canary INCHANGÉS). `_drive_batched` /
  `_move_group` ; nouveau `_scan_feed(full_coverage=True)` marche jusqu'à une fin
  de feed PROUVÉE (pas l'heuristique 2-vides) → le « parti » set-wise d'un groupe
  est fail-closed. Garde-fous : re-scan entre les Applies (reflow que le mover
  cause lui-même), re-check d'identité fraîche avant register, moved =
  coché-par-nous ET parti(dual-key) ET sur-cible(RV2), groupe vérifié juste après
  SON Apply (fenêtre parallèle en secondes), erreur feed après Apply → tout le
  groupe UNKNOWN, bulk[list] mismatch → pas d'Apply.
- **P1.5 — vérif cible groupée (commit `bce2687`).** P1 batchait le scan SOURCE
  mais laissait la preuve RV2 « présent sur cible » par offre. Fix :
  `_scan_feed(stop_on_urls={…})` + `_verify_group_on_target` → UN scan cible par
  groupe. `max_pages` cible découplé (`TARGET_SCAN_MAX_PAGES=2000`).
- **P2 — gate d'autorisation (commit `0dcf717`).** `MOVER_VERSION` 3→4. Résultat
  du mover expose `max_apply_items` ; un `--mode safe --batch` refuse une preuve
  faite d'un canary 1-item — exige un canary MULTI-item (`--mode learning --batch
  --limit 2..5`, un Apply ≥2 en une fois).
- **Incrémental (commit `4cd7070`).** Le tri saute les URLs déjà résolues au run
  précédent (ledger `sort_ledger`) ; `--full` ignore le ledger.
- **Console (commit `fdfd41c`).** Case **« Batché (rapide) »** sur `/executor/tri`
  → canary = `--batch --limit 2`, full = `--batch`.
- **PROUVÉ EN PROD (2026-07-29)** : un batch Softwares a déplacé **98 offres avec
  un unique Apply de 53 items** (`max_apply_items=53`) — le gain ~50× réalisé.

## 2026-07-23 — Stage 9 : writer sort-move (déplacement par liste, multi-store)

Romain 2026-07-23 : « le writer d'abord ». Exécute UNE liste cible du
`sort_plan.json` à la fois (validation par liste), en réutilisant le `Mover`
prouvé (RV2 : parti-de-la-source ET présent-sur-la-cible).

- `src/sort_move.py` (pur) : `build_sort_move_plan(run_dir, list_id)` → plan
  **par store** pour une liste (le mover est mono-store ; une liste couvre
  plusieurs stores → un plan mono-store par store). Exclut fail-closed les offres
  sans store_id / sans URL. Label cible résolu LIVE par le mover (ids drift).
- `src/move_auth.py` : autorisation de tri **séparée** (`sort_move_authorization.json`)
  — portée **par liste, cross-store** (drop store_id : le mécanisme de move est
  store-agnostique), liée au hash de `sort_plan.json`. Un canary prouvant une
  liste sur un store autorise ce **label** pour le batch, tous stores.
- `scripts/09_sort_move.py` : itère les stores d'une liste, dry-run par défaut,
  R24 (`learning` = canary de 1 ; `safe` = liste complète derrière
  `--i-authorize-batch` + autorisation de tri). Gate invariants + browser_lock +
  BlockLedger, jamais fire-and-forget. Résolution live du label vérifiée
  (Blacklist→8, Softwares→16, Gift cards→21, account→30).

## 2026-07-23 — Tri : corrections issues de l'audit adversarial du plan

Audit multi-agents du plan de tri (16 agents : FP sur les routées, FN sur les
candidats). 3 défauts corrigés + tests :

- **FP — jeux Windows Store mal classés Software** : `WINDOWS 10/11` retiré de
  `SOFTWARE_APP_TOKENS` (il matchait « Destiny 2 … Windows 10 Store Key »,
  « Fallout 76 … Windows 10/11 CD Key »). Remplacé par `_WINDOWS_OS_RE` qui
  n'attrape que la **licence OS** (`Windows 11 Pro/Home/OEM/Key…`), jamais le
  marqueur de plateforme (`… Store`, forme « 10/11 »).
- **FP — bundles jeu+OST mal Blacklistés** : la règle soundtrack/artbook ne se
  déclenche plus quand le **jeu de base est inclus** (`<jeu> + OST`,
  `… Soundtrack Edition`). Les soundtracks/artbooks standalone restent Blacklist.
- **FN — offres `(Account)` non routées** (Romain 2026-07-23 : « router vers
  account (30) ») : `matcher.is_account_offer` + routage **au niveau du tri**
  (`build_sort_plan`), délibérément PAS un skip precheck (le pipeline submit
  continue de résoudre les offres compte vers leur page account dédiée).

Plan re-dérivé hors-ligne sur `offers.json` (sans re-scan) : account 12 → **16 255**
(≈34 % du feed, Difmark), Softwares 326 → 310, Blacklist 75 → 61 ; routables
1 147 → **17 360**.

## 2026-07-23 — Stage 8 : scan « list sorting » tous stores (read-only, plan)

Romain 2026-07-23 : un mode qui passe sur **toutes** les Pending Offers, tous
stores confondus, et propose un **routage complet** vers les listes cibles.

Fait pivot (probé live) : `page=aks-merchant-feeds-9` **sans** paramètre `store=`
renvoie la list 9 **tous stores** (~30 pages ≈ 3 000 offres) — `store=` vide ou
`store=0` NE font PAS ça (ils retombent sur un store arbitraire). Chaque offre
porte son `storeId`/`listId`. ⚠️ Deux espaces d'ID distincts : *store* 38 = G2A,
*list* 38 = « binance ».

- `src/extractor.py` : `feed_url(store_id=None)` omet le filtre `store=` (vue
  tous-stores). `extract_pages`/`extract` acceptent `store_id=None`.
- `src/contracts.py` : `RawSnapshot.create(store_id=None)` → `""` (jamais
  « None »).
- `src/sort_plan.py` (nouveau, pur/déterministe) : `build_sort_plan` groupe les
  offres par liste cible via `precheck_skip` + `suggest_target_list` ; chaque
  offre est classée une seule fois (routée / non-routée « garder » / candidat
  création) ; `render_report` rend un rapport par liste. Aucune écriture.
- `scripts/08_sort_plan.py` (nouveau) : scan read-only tous-stores derrière le
  gate invariants + browser_lock ; écrit `sort_plan.json` + `report.txt`. Marque
  la couverture `truncated` si le feed annonce plus de pages que `--max-pages`
  (pas de cap silencieux).

Côté **write** (déplacements) : inchangé, toujours derrière le gate Stage 6 —
prochaine étape = writer avec **validation en bloc par liste** (Romain) + preuve
RV2 par move + autorisation versionnée + go explicite. Le scan ne déplace RIEN.

## 2026-07-23 — Matcher : random/lootbox + contenu non-jeu → Blacklist (8)

Romain 2026-07-23 : router vers **Blacklist (8)** les skins (déjà détectés), les
**soundtracks/artbooks/digital books** et les **random/lootbox**. Deux faux
positifs signalés par Romain et corrigés : "Lost in Random" (jeu) et "Blacksad:
Under the Skin" (jeu).

- `src/matcher.py` (`precheck_skip`) :
  - `NON_GAME_CONTENT_TOKENS` (Soundtrack/OST/Artbook/Art Book/Digital Artbook/
    Digital Book), word-boundary — `OST` en frontière de mot ne déclenche pas sur
    "Ghost"/"Frost".
  - **Random/lootbox** (`_RANDOM_LOOT_RE`) : discriminant **grammatical** — la
    lootbox utilise `RANDOM` comme *adjectif sur un nom de livraison générique*
    (un mot désignant « une chose distribuée », jamais l'identité d'un jeu) ; un
    vrai jeu utilise « Random » comme *nom propre* (« Lost **in** Random », «
    Random **Heroes** »). Deux tiers : noms **communs** (`GAME/KEY/ITEM`, présents
    aussi sur des offres normales) → uniquement **collés** à RANDOM (« Random Key
    ») ce qui exclut « Random Heroes Steam Key » / « Lost in Random Steam Key » (un
    mot de plateforme s'intercale) ; noms **forts** (`CASE/CRATE/DROP/SPINNER/LOOT/
    BUNDLE/MYSTERY/BOX/GACHA`, rares sur offres normales) → tolèrent quelques
    adjectifs (« RANDOM INDIE STEAM CASE »). Plus un **tirage quantifié** (« 1x
    Random… »). Testé **avant** les catégories → prime sur un `GIFT CARD` incident
    et sur `BUNDLE` (« Random Bundle » va bien en Blacklist).
  - **Skin guard** (`_SKIN_TITLE_PHRASE_RE`) : `Skin` sorti de la boucle brute.
    Un cosmétique se lit "`<arme/héros> Skin`" ; `Skin` précédé d'un article/
    possessif ("Under **the** Skin", "**Second** Skin") ou en **tête** de titre
    ("Skin Deep") est un mot de titre ordinaire → PAS un skip. Les vrais
    cosmétiques (Dragon Lore Skin, Rust Weapon Skins) restent skippés.
  - Vérifié : 16 exemples lootbox de Romain → tous Blacklist ; faux positifs
    inertes (Lost in Random ×3, Blacksad Under the Skin ×2, Skin Deep, Second
    Skin, Skinwalker, Ghost/Frost).
- `src/aks_lists.py` (`suggest_target_list`) : ces tokens de catégorie
  (`_BLACKLIST_CATEGORY_TOKENS` : skins + wear CS + soundtrack/artbook/digital
  book + random) → **`"8"`** (Blacklist). Les **bundles** partagent le suffixe
  "(no bundles/skins)" mais restent **exclus** (ils ne sont pas auto-blacklistés).
- Docs : `EXECUTOR_RULES.md` §5, skill `aks-data-entry` (SKILL.md, CORE_RULES,
  LEARNED_RULES S27). Disposition finale toujours via le gate Move-to-List
  (confirmation opérateur + canary + autorisation), inchangé.

## 2026-07-22 — Move-to-List : batch réactivé derrière flag + autorisation (étape 6)

Décision Romain, après le canary RV2/RV3 validé. `--execute --mode safe` (le
batch) n'est plus refusé inconditionnellement : il exige désormais une **double
garde** — le flag explicite `--i-authorize-batch` **ET** une autorisation RV3
(`move_authorization.json`) couvrant le plan (mover version × store × source ×
contexte d'extraction × listes cibles déjà validées par un canary). Sans l'un ou
l'autre → refus fail-closed. Chaque move du lot prouve toujours source+cible (RV2)
et une liste cible non validée par canary est refusée. Tests: gate à double garde
(sans flag / sans auth / auth non couvrante / autorisé). Suite verte.

## 2026-07-22 — Move-to-List : mover v3 (reflow-résilient) + canary RV2/RV3 validé

Un canary supervisé a révélé un blocage fail-closed : un re-import faisait
refluer la pagination entre l'index de départ et le move (`row id vanished`).
Fix `mover._relocate_before_move` : re-localisation par URL JUSTE AVANT le move
(résilient au reflow), MOVER_VERSION 2->3. Puis, sur données FRAÎCHES, un canary
supervisé a **réussi de bout en bout** : AWZ PC Cleaner déplacé liste 9 ->
Softwares, vérifié **parti de la source ET présent sur la cible** (RV2), et une
autorisation RV3 v1 (mover v3 × store × source × Softwares × extraction) générée.
Le batch reste verrouillé — réactivation = décision explicite distincte.

## 2026-07-22 — Move-to-List : preuve d'arrivée cible (RV2) + autorisation versionnée (RV3)

Revue post-canary (`docs/REVIEW_2026-07-22.md`). Le batch reste VERROUILLÉ
(RV1, `--execute --mode safe` refusé) ; ces deux briques préparent une future
réactivation qui restera une **décision explicite distincte**.

- **RV2** — le succès d'un move est désormais « parti de la source ET **présent
  sur la liste cible** » (`mover._verify_on_target`, scan `feed_page=aks-merchant-
  feeds-<cible>` par URL). Un move/delete d'un opérateur parallèle ne compte plus
  comme succès. Cible non intégralement vérifiable → **UNKNOWN**, arrêt fail-closed.
- **RV3** — `src/move_auth.py` : un canary vérifié **génère** une autorisation
  (`move_authorization.json`) liée à la **version du mover**, au store, à la
  source, aux **listes cibles validées** (label stable) et au **contexte
  d'extraction** (hash de skipped.json). `batch_authorized()` vérifie la
  couverture ; tout drift → hors périmètre. Ne réactive PAS le batch.

Tests: +12 (RV2 arrivée/absence cible, RV3 grant/scope/drift). Suite verte.

## 2026-07-22 — Learning : confirmation explicite des suggestions (SF2, option B)

Romain 2026-07-22 : la confirmation d'une disposition Move-to-list suggérée est
EXPLICITE (option B, la plus fidèle à D1-b). Bouton **« ✓ confirmer »** par offre
+ bouton global **« confirmer toutes les suggestions »** ; changer la valeur du
select confirme aussi (décision explicite) ; regarder le menu ne confirme plus
rien. Le mover ne consomme toujours que les dispositions `suggested != true`.

## 2026-07-22 — Stage 6 : 1er canary Move-to-List RÉUSSI + registration déterministe

Premier vrai move end-to-end, sur go de Romain : l'offre logicielle « IObit
Advanced SystemCare » (run G2A) déplacée de la liste 9 (pending) vers Softwares
(16), vérifiée **partie de la liste source** (le seul signal de succès).

Fix validé par le canary : la registration d'une offre dans le bulk form se fait
désormais par **injection déterministe** du hidden `bulk[item][]` (submit_session
`register_row`), et non plus par un clic trusted sur la case — ce dernier s'est
révélé fragile sur les pages paginées du feed (`click=CLICKED` mais le handler
async n'injectait pas le hidden ; fail-closed : rien n'était soumis). Le POST
natif de l'Apply (trusted) sérialise le hidden injecté à l'identique. Le 1er move
raté avait laissé l'offre intacte (aucune écriture partielle). Suite 743 verte.

## 2026-07-22 — D2 tranché : processus builder-offline officialisé

Romain 2026-07-22 : pas de moteur de règles apprises dans le repo. La
généralisation des annotations Learning en comportement du pipeline passe par
le **processus builder-offline** — `docs/LEARNING_PROCESS.md` (nouveau) :
learning.json est l'autorité d'intention humaine, le code l'autorité
d'exécution ; une annotation devient soit un move (Stage 6), soit une saisie
manuelle assistée, soit une règle matcher déterministe (testée/documentée/
committée/révocable) — jamais une règle appliquée automatiquement au runtime.
Le `scope` (exception/marchand/global/observation) porte la généralisation ;
une exception ne devient jamais une règle générale. EXECUTOR_RULES §13 pointe
le processus ; D2 fermé dans AUDIT_LEARNING.

## 2026-07-21 — Stage 6 : writer Move-to-List (brique B, dry-run par défaut)

Le mover — frère du submitter — déplace les offres non-matchées hors de leur
liste source vers la liste annotée. Mécanique confirmée read-only
(`docs/AKS_LISTS.md`) : POST natif du bulk form, register trusted-only.

- `src/move_plan.py` : construit le plan depuis les dispositions CONFIRMÉES de
  `learning.json` (target_list_id présent ET `suggested != true`, D1-b),
  jointes à `skipped.json` pour name+url ; orphelines/suggestions exclues
  (jamais silencieusement), source list dérivée de raw.json.
- `src/mover.py` : `resolve_list_id` (par LABEL live, les ids driftent),
  `DryRunMover` (locate + selectable, aucune écriture) et `Mover` (register
  trusted → set bulk[list] → Apply trusted → **vérif « gone from source »**).
  Réutilise les scans audités du submitter (`_scan_feed`/`_locate_row`/
  `_verify_gone`/`_url_key`).
- `src/submit_session.py` : `list_options` (read-only), `register_row`/
  `set_bulk_list`/`click_apply` (WriteSubmitSession).
- `scripts/06_move.py` : mêmes gates que Stage 5 — invariants verts+authoritative,
  browser_lock, dry-run par défaut (`--execute`), mode R24 (safe = plan complet ;
  learning/advanced = canary de 1), BlockLedger, JSONL. Jamais fire-and-forget.

Aucun move réel lancé — le 1er canary attend le go explicite de Romain.
Tests : +35 (mover 16, move_plan 3, + JS inventory). Suite 724 verte.

## 2026-07-21 — Learning (annotations) : vue admin + durcissement post-audit

**Attention au nom** : « Learning » (cette fonctionnalité, la vue d'annotations
admin) ≠ `--mode learning` (le mode de submit R24, un canary de 1 qui ÉCRIT).
Deux concepts sans rapport — voir EXECUTOR_RULES §13.

La vue Learning (commits `b7e930d`→`ec35712`) : par run, les offres non-matchées
groupées par raison de skip, annotables par offre — région/édition (vrais ids du
catalogue de session), commentaire, page AKS, disposition « Move to list »
(suggestion déterministe, défaut *garder*) — stockées dans
`runs/<id>/learning.json`. Aucun code pipeline ne consomme ce fichier : la
généralisation en règles matcher reste un processus builder-offline (jamais de
LLM runtime). Taxonomie des listes + mécanique du move : `docs/AKS_LISTS.md`.

Durcissement issu de l'audit `AUDIT_LEARNING_2026-07-21.md` (L1-L11) :

- **L1** — les éditions Learning posent `DIRTY` et le save resynchronise
  l'empreinte : l'auto-refresh 10 s n'efface plus une saisie en cours.
- **L2** — le save est un **merge** (jamais un remplacement) : suppression
  uniquement par signal `cleared` explicite ; précondition `base_sha`
  (409 `conflict` en écriture concurrente, pattern AS1) ; verrou serveur.
- **L3** — option fantôme « (hors catalogue) » : un id région/édition sauvegardé
  qui a dérivé du catalogue survit au rechargement et au re-save.
- **L5** — validation serveur fail-closed : liste cible ∈ catalogue + label
  cohérent, région/édition ∈ catalogue de session (grandfather sur valeur déjà
  stockée), `aks_url` au format page AKS, champs ≤ 2000 caractères.
- **L6** — `learning_log.jsonl` par run : un événement JSONL par save
  (sha avant/après, ids touchés/supprimés, auteur).
- **L8** — suggestions ancrées sur la catégorie de raison (plus de sous-chaîne
  libre : « steam-account » ne suggère plus la liste account).
- **L9-L11** — message correct sur run non matché ; panneau Learning chargé même
  si la validation échoue ; `by` = identité basic-auth d'abord ; `first_by`/
  `first_at` conservés à l'édition ; bannière stale mentionne les annotations.

Décisions de Romain (2026-07-21, même jour) :

- **D1 = (b)** → L4 FIXED : la préselection Move-to-list est persistée avec
  `suggested: true` tant que non manipulée (badge « suggéré — à confirmer ») ;
  toute manipulation du select la confirme. Le futur mover ne consommera que
  les dispositions confirmées.
- **D3 = oui** : champ `scope` par annotation (`exception_offre` /
  `regle_marchand` / `regle_globale` / `observation`) — seules les deux
  « règle » autorisent une généralisation par le builder.
- **D4 = oui** : champ `platform` (vocabulaire canonique, 12 tokens) — le
  cas 8 (correction de plateforme) est couvert ; une plateforme seule est une
  annotation valable.

Restent OUVERTES : D2 (moteur de règles dans le repo vs processus
builder-offline officialisé) et D5 (renommage UI).

Tests : 703 verts.

## 2026-07-21 — Admin extraction: two modes, full shop vs par page (Romain)

The admin's "Lancer l'extraction" only did a full sweep, so runs went out at
1142 offers (Kinguin) — against the one-page-at-a-time cadence
(EXECUTOR_RULES §11), which is what keeps a batch from going stale while the
feed re-imports. Added a mode selector:

- **Par page (100 offres)** — `start_extract(..., page="N")` passes
  `--pages N` (the extractor's slice mode, `partial: true`). The cadence norm:
  one page → match → report → validate → submit → next page.
- **Full shop** — `page=None`, the whole-feed sweep (unchanged).

`page` accepts `"N"` or `"N-M"` (validated `bad_page` otherwise). Tests +5.
658 green.

## 2026-07-20 — Submit speedup via tighter pacing (Romain); navigate settle stays 3 s

Romain: "vu que tu peux faire deux requêtes par seconde", the submit was far
too slow. The fix is the pacing (burst mitigation, never correctness):

- `--pace-offers` default `5-15` s → `0.5-1.5`, `--pace-pages` `1-3` s →
  `0.4-0.6` (≈ 2 req/s, AKS's tolerance per Romain).

A shorter `navigate` settle (3 s → 1 s) was also tried but **reverted the same
day**: reading feed rows works fast (SSR HTML), but the page's interactive JS
(jQuery/ThickBox that the create-offer click drives) is not initialized at 1 s,
so `open_offer_modal` clicked yet `#TB_ajaxContent` never loaded —
"modal context missing" on every offer (live Driffle). The settle is a real
in-page timing dependency, unlike the pacers. A successful offer's cost still
drops from ~30 s to ~18 s from the pacers alone.

**Settle split (the correct version).** The blanket cut was wrong, but the
FEED-SCAN navigates (`_read_feed_page`: index + the full post-save re-walk
after every creation — the bulk of a submit's time) open no modal and only
read SSR rows, so they now use a short `FEED_SCAN_SETTLE = 1.0 s`; the navigate
BEFORE a modal open (`_prepare`'s row page, the catalog fetch) keeps the 3 s
default. Extraction already proved 1 s reads rows fine. This reclaims the
post-save re-scan time without touching the modal timing that broke before.

## 2026-07-20 — REVERT FC4: it blocked every GLOBAL submit + admin panel shows only the current stage

**FC4 regression (urgent, live).** The 2026-07-17 audit fix FC4 made
`resolve_catalog_id`'s id-path require the matcher's region label to appear as
a word in the live dropdown text. But the AKS dropdown labels Steam's global/
worldwide region **`"Steam (2)"`**, while the matcher calls it **`GLOBAL`** —
synonyms for the same id 2, and "global" is not in "steam (2)". So FC4 blocked
GLOBAL — the most common region — on every real submit (Driffle 2026-07-20: all
offers `region not in session catalog (label='GLOBAL' id='2')`, 0 created).
Reverted: the id-path validates EXISTENCE only, as it did for the project's
whole history; the label-path still remaps a drifted id when the label uniquely
matches, and the human validates the region label in the report. The test
fixtures that hid this (region key 2 texted `"GLOBAL"` instead of `"Steam (2)"`)
are now realistic, with an explicit regression test. FC4's "id drifted to a
different region" concern was PLAUSIBLE-not-confirmed and stays open.

**Admin panel (Romain).** A run's log now accumulates extraction + matching +
submit events, so the progress panel replayed the whole history on each stage
launch (the confusing "sweep / terminé exit 0" lines under a fresh submit).
`startRun`/`startMatch` now seek the log tail to its current end, so the panel
shows only the stage just launched.

Tests: 652 green (FC4 tests replaced by the realistic-fixture regression test).

## 2026-07-20 — Admin: launch the matching step (stage 3) from the page (Romain)

The admin could launch extraction (stage 1) but not matching (stage 3), so an
extracted run showed "0 candidat / non matché" until someone ran
`03_match.py` by hand. Romain: "il faudrait ajouter un bouton pour cette étape
de validation." Added a **"Lancer le matching"** button (with an optional max-
candidates field) on the run panel.

- `SubmitManager.start_match(run_dir, by, max_candidates)` spawns
  `03_match.py offers.json [--max-candidates N]` (kind `match`), supervised
  like every other run. Read-only HTTP (no browser/CDP, no browser lock) but
  serialized under the same one-run-at-a-time gate. Requires `offers.json`
  (refuses `not_extracted` otherwise); rejects a non-positive max-candidates.
- `POST /api/runs/<id>/match` (`app.py::_post_match`). The UI reuses the run
  progress/poll machinery; when the match completes it re-opens the run, so
  the report + validation table populate automatically.

Tests: +9 (`StartMatchTests`, `MatchEndpointTests`). 651 green. Follow-up
offered but not built: auto-chain matching at the end of extraction.

**Live progression (same day, Romain: "on aurait voulu voir la progression
depuis l'admin").** The match button reused the submit progress panel, but
`03_match` emitted nothing, so the panel stayed silent until completion.
`match_feed` now takes an `on_progress` callback (called every 5 offers + at
the end with `{done, total, candidates, skipped}`); `03_match` logs these as
`match_progress` events to the run's JSONL, added to the admin's `UI_EVENTS`.
The UI shows a single live counter in the panel title —
"Matching : 150/226 — 5 candidat(s), 145 écarté(s)". Also fixed the
candidate-cap skip message (was hardcoded "max 100", now the actual cap).
Tests: +2. 653 green.

## 2026-07-20 — Submit auto-defaults --max-pages from the feed's own page count (Romain)

The P0.2 coverage check (SC4) aborts fail-closed if the batch-start feed index
hits the `--max-pages` ceiling while the feed advertises MORE pages. Difmark's
feed is ~357 pages, so the historical 40-page floor always aborted
(`feed_unreadable`, 0 attempts) unless the operator remembered to raise
`--max-pages` by hand. Now the extractor persists the feed's own advertised
page count and the submit derives the ceiling from it.

- `RawSnapshot` / `NormalizedFeed` gain `feed_last_page` (the pagination nav's
  `nav_max`, distinct from `pages_scanned` which a slice under-counts). Written
  to `raw.json` and `offers.json`; `0` when not recorded (legacy runs).
- `scripts/05_submit.py`: `--max-pages` now defaults to AUTO — reads
  `offers.json` `feed_last_page` and uses `max(40, ceil(pages × 1.3))` (30%
  churn headroom), floored at 40, falling back to 40 when unknown. An explicit
  `--max-pages` still overrides. The chosen value + reason is printed. The
  admin passes nothing when its (now "vide = auto") field is empty, so it
  auto-derives too — no admin backend change.

Tests: +7 (`DeriveMaxPagesTests` + contract round-trips). 644 green.

## 2026-07-18 — Difmark Account offers resolve the AKS account PAGE (Romain)

Rounds 1-2 (2026-07-17) got the account *region* right (Steam Account 412/…)
but still matched the game's `…-cd-key-…` page. Romain 2026-07-18: "pour les
offres Account, tu dois proposer la page Account, pas la page du jeu." AKS
carries a SEPARATE product page per account platform,
`buy-<slug>-<platform>-account-compare-prices/` — a distinct product (own
id/editions/prices). Verified live: `Final Knight Steam Account` = 187974
(vs the key page `Final Knight` = 171000), and every existing listing on the
account page (G2A included) uses region 412 — so account-page + account-region
is internally consistent.

- `aks_url(slug, page_kind)` + `resolve_aks(page_kind=…)` build the
  `…-<kind>-compare-prices/` URL; `DIFMARK_ACCOUNT_PAGE_KINDS = {"STEAM":
  "steam-account"}` (Steam-only confirmed for Difmark). No R30 site-search
  fallback for account pages (the result regex only knows `-cd-key-` slugs).
- `match_offer` gains an injectable `account_resolver`; account offers route
  through it. R01 compares against the game **identity** — `account_identity()`
  strips the "<platform> Account" page-type suffix from the AKS name
  ("Final Knight Steam Account" → "Final Knight"), which the feed title
  ("Final Knight Standard Edition") never carries. A resolved account-URL 200
  whose name lacks the suffix fails closed ("not an account page").
- Live end-to-end confirmed: a Difmark Steam-Account offer for Final Knight
  now resolves product 187974, region GLOBAL ACCOUNT(412); games with no AKS
  account page (key page also 404) correctly skip.
- Caveat (pre-existing): the generic "Standard Edition" title yields
  Standard(1) even when the account page's only edition is Early Access(5) —
  fail-closes at submit (product-scoped dropdown); surfaced for validation.

Tests: +7 (`AccountPageResolutionTests` + updated Difmark account tests). 637 green.

## 2026-07-17 — Audit P2.c : docs remises au niveau du code + skips §4.3 enfin codés (DO1-DO6)

Rafraîchissement produit par un workflow multi-agents (5 rédacteurs ancrés
sur le code + 5 vérificateurs factuels indépendants, leurs erreurs corrigées
avant écriture) :

- **NOOB.md** (DO1) — la contradiction canary/§4c est résolue en faveur de
  R24 ; ajout de l'Étape 0b, de la page opérateur, du verrou navigateur, du
  statut UNKNOWN, et d'une idée reçue n°10 retirant l'ancienne règle canary.
- **ARCHITECTURE.md** (DO2) — réécrit sur l'état réel (fini le N8N de jour 1) :
  stages 0b-5, layering des modules, admin, tab CDP unique, triple validé +
  liaison sha (AS1), match_meta (FC5), marqueur root (FC2).
- **README.md** (DO3) — arborescence réelle, compte de tests, page admin,
  registre d'audit ; le quick start ne mentionne plus AKS_TARGET=vps.
- **DATA_CONTRACTS.md** (DO4) — contrats des artefacts stages 4+ :
  submit_plan.json (dont post_save UNKNOWN et matched_mode),
  session_catalog.json, admin_submit.json, match_meta.json,
  guard_ledger.json, modal_inspection.json.
- **ops/BROWSER_RUNBOOK.md** (DO5, NOUVEAU) — le substrat navigateur enfin
  documenté, vérifié live : hold apt Chromium 149 (et pourquoi : le 150
  Debian SIGTRAP) couplé à l'UA épinglé, unités systemd, proxy socat 9223,
  politique UA-Switcher, procédures de récupération et checklist de
  reconstruction VM complète (marqueur FC2 inclus).
- **DO6** — les skips que §4.3 promettait depuis v1 existent enfin dans le
  matcher : « EU-NA » (FORBIDDEN_REGIONS, la normalisation de ponctuation
  fait matcher « EU NA ») et les country gifts (CZ/RU/TR/BR/AR/IN/CN
  ADJACENTS au mot GIFT — « Alice in Wonderland Steam Gift » ne skip pas).

Tests : +4 (630 verts).

## 2026-07-17 — Audit P2.b : transport CDP désync-proof, contrats de fakes, primitives login testées (SC7/SC8/TE2/TE4/TE5)

- **SC7** — `_page_ws_path` ne retient que les vrais onglets http(s)
  (`chrome-error://`, `devtools://`, `chrome://` exclus — l'ancien filtre par
  sous-chaîne laissait passer un onglet crashé) et préfère l'onglet déjà sur
  allkeyshop.com (suffix-spoof safe) quand le navigateur partagé en porte
  plusieurs. Décision documentée : PAS de reconnexion mid-run — un socket
  mort lève `CdpCommandError` et le run s'arrête fail-closed (reprendre sur
  un socket frais cacherait un restart navigateur à la preuve de
  disparition).
- **SC8** — framing WebSocket réécrit : opcodes gérés (Close → raise au lieu
  d'être parsé comme du texte, Ping → Pong répondu, Pong ignoré),
  fragmentation assemblée jusqu'à FIN, lecture EXACTE des en-têtes (un
  timeout/EOF mid-frame lève — l'ancien short-read de 2 octets désynchronisait
  le parsing pour toujours), `sendall` au lieu de `send`.
- **TE2** — `tests/test_fake_contracts.py` : chaque fake duck-typé de la
  suite est vérifié mécaniquement contre sa classe réelle — méthode fantôme
  ou paramètre renommé d'un côté = test rouge, fini la dérive silencieuse
  d'interface.
- **TE4** — les primitives réelles de `LoginSession` sont exécutées par les
  tests (les credentials ne sont JAMAIS tapés si le clic de focus du champ a
  échoué ; `verify_dashboard` exige URL ET DOM ; payloads JS read-only).
- **TE5** — `click_trusted_at_element` délègue son scroll à
  `_scroll_rect_into_viewport` : une seule implémentation, celle testée.

Tests : +27 (624 verts).

## 2026-07-17 — Audit P2.a : les gates déclaratifs deviennent mécaniques (FC2/FC3/FC4/FC5)

- **FC2** — `AKS_TARGET=vps` ne force plus `authoritative:true` : une seule
  variable d'env ne doit jamais déverrouiller les stages d'écriture. La seule
  autorité est désormais le **marqueur root** `/etc/aks-executor.target`
  (installé sur le VPS le 2026-07-17), qui doit être possédé par root, non
  modifiable par le groupe/autres, ET contenir le hostname de la machine (un
  marqueur copié ailleurs ne transfère rien). La direction inverse
  (`AKS_TARGET=dev` → force OFF) reste — forcer non-autoritaire est toujours
  sûr. Le shell audit (`00_audit_env.sh`) suit le même ancrage. Vérifié live :
  le gate reste vert+authoritative sur le VPS, zéro fenêtre rouge.
- **FC3** — G03 inter-processus (`BlockLedger`, `runs/<id>/guard_ledger.json`) :
  un blocage StepGuard mourait avec son process, rien n'empêchait une 3e passe
  identique après deux passes bloquées. Une passe de récupération sur le même
  run reste LIBRE (récupération idempotente standard, Romain 2026-07-07) ;
  deux passes réelles consécutives bloquées → la 3e exige
  `--acknowledge-block` (acquittement humain explicite, qui remet le compteur
  à zéro). Une passe propre remet aussi le compteur à zéro. Dry-runs exclus.
- **FC4** — `resolve_catalog_id` chemin id : l'existence de l'id ne vaut plus
  validation — le label du candidat doit apparaître comme mot entier dans le
  texte du catalogue live ("EU" ⊆ "Steam EU (9)") ; un id qui a dérivé vers
  une autre option ("BTC 1500 PLN") → None → blocker, jamais d'adoption
  aveugle du texte dérivé.
- **FC5** — le mode R24 est enfin traçable : `03_match --mode` (défaut safe,
  comportement identique tant que le matcher n'a pas de profils) tamponne
  `match_meta.json` ; `05_submit` ET l'admin refusent un submit réel dont le
  mode déclaré implique un lot PLUS LARGE que le mode matché (run matché en
  canary → jamais le chemin lot-complet `safe`). Runs pré-FC5 sans meta :
  acceptés. `submit_plan.json` enregistre `matched_mode`.

Tests : +20. 597 verts. Miroir EXECUTOR_RULES différé (chantier Difmark
parallèle sur le fichier).

## 2026-07-17 — Audit P1.c : GO lié au lot, plus d'orphelin, keep-alive sain, verrou navigateur (AS1/AS2/AS3/OP1)

- **AS1** — le « GO » tapé est désormais lié au CONTENU exact du lot affiché :
  la page capture le sha256 d'`approved.json` à l'ouverture du dialogue et le
  renvoie avec le submit réel ; le serveur refuse (`409 approved_changed`) si
  une validation concurrente (second opérateur, autre onglet) a régénéré le
  lot entre l'affichage et le GO. Sha absent → `400 approved_sha_required`
  (recharger la page). Exposé dans GET/POST validation.
- **AS2** — un échec (OSError) entre `Popen` et le démarrage de la
  supervision laissait un enfant VIVANT non supervisé — le seul chemin
  fire-and-forget du projet. L'enfant est maintenant tué (terminate→kill)
  avant de propager l'erreur, et le manager se libère.
- **AS3** — le corps de chaque POST est intégralement lu AVANT toute réponse
  (`_drain_body`) : les handlers sans corps (`/api/invariants/check`) et tous
  les chemins d'erreur précoces (CSRF 403…) laissaient les octets non lus
  désynchroniser la connexion keep-alive HTTP/1.1 — la requête suivante se
  parsait au milieu du corps précédent. Un corps > 2 Mo est refusé sans
  lecture avec fermeture de connexion (seul moyen de rester en phase).
- **OP1** — `src/browser_lock.py` : verrou `flock` inter-processus sur
  `state/browser.lock`, pris non-bloquant par chaque stage qui ouvre une
  session CDP (02 extract, 05 submit tous modes, 00b login). Un seul pilote
  pour l'unique onglet Chrome : une CLI lancée pendant un run admin (ou
  l'inverse) refuse de démarrer en nommant le détenteur, au lieu de corrompre
  les scans/modales de l'autre. L'admin est couvert sans changement : il
  spawn ces mêmes scripts. Libération par le noyau à la mort du process —
  pas de verrou fantôme.

Tests : +9 (SpawnFailClosedTests, ApprovedShaBindingTests, keep-alive,
BrowserLockTests, refus busy CLI). 565 verts.

## 2026-07-17 — Audit P1.a : huit correctifs matcher (MA1-MA8)

Tous confirmés par repro live pendant l'audit contre-vérifié du 2026-07-17 :

- **MA1** — `resolve_aks` : une erreur transitoire (429/5xx/timeout) ou un
  nom illisible sur un slug PLUS spécifique lève immédiatement au lieu
  d'être masqué par le 200 d'un tier moins spécifique (un titre deluxe
  atterrissait sur la page du jeu de base). C'est ce que la docstring
  promettait déjà.
- **MA2** — `explicit_platform` : word-boundary + départage par collocation
  `<PLATEFORME> [CD ]KEY/GIFT` — "Epic Chef … Steam Key" n'est plus EPIC,
  "Gogol's Quest" n'est plus GOG ; ambiguïté résiduelle → None (chemin
  token-less R27/R29, fail-closed).
- **MA3** — ANNIVERSARY/DEFINITIVE deviennent des qualifieurs dangereux
  (modèle REMASTERED) : "Skyrim Anniversary Edition" n'entre plus sur la
  page du jeu de base en Standard(1). Pas d'EDITION_HINTS possible : le
  catalogue maître n'a pas d'id numérique stable pour ces éditions.
- **MA4** — `gift` doit être un segment d'URL entier : "the-gifted-rabbit"
  ne propose plus GIFT(25).
- **MA5** — le pool R23 ne crashe plus (`AttributeError`) sur une map
  d'éditions à valeurs chaînes — un tel crash abortait tout le run de match.
- **MA6** — dérive de markup AKS bruyante : un bloc `"prices"` présent mais
  imparsable lève `AksPageUnparseable` → skip distinct, au lieu d'un ()
  silencieux qui désactivait le garde-fou anti-doublon R25. L'absence reste
  souple (les stubs sérialisent `"prices":[]` ; éditions/plateformes
  absentes déjà couvertes par R19/R20/R27).
- **MA7** — le marqueur Gamivo `-en-` (clé EN-only) est enfin codé — skip
  "language restriction", scopé gamivo.com.
- **MA8** — défense titre pour les régions : "EUROPE" nu en milieu de titre
  (grammaire K4G) et région dans une parenthèse non-première → EU au lieu
  de GLOBAL implicite.

Tests : +25 (8 classes AuditMaX). 555 verts. EXECUTOR_RULES §4.2/§4.4/§4.7
mis à jour.

## 2026-07-17 — Audit P1.b : le pick Selectize est vérifié, la ligne re-vérifiée sur le DOM frais (SC3/SC5)

Deux trous du chemin d'écriture confirmés par l'audit :

- **SC3** — le readback post-pick (`select.value` + `selectize.getValue()`)
  était lu mais jamais COMPARÉ à l'id cible : un clic trusted atterrissant
  sur l'option voisine passait `SELECTED`, et tous les gates suivants
  passaient aussi (le formulaire est valide avec n'importe quelle option).
  `select_via_trusted` exige maintenant l'égalité des deux canaux avec l'id
  visé (`WRONG_VALUE` sinon, `READBACK_UNREADABLE` si illisible), et
  `fill_then_click_trusted` re-lit les DEUX selects juste avant le clic
  Create (`VALUE_DRIFTED_BEFORE_CLICK` — dernière porte avant la seule
  écriture du pipeline).
- **SC5** — `_prepare` naviguait vers la page de la ligne (nouveau render)
  puis ouvrait la modale par id sans re-vérifier la ligne sur ce DOM frais ;
  un ré-import dans la fenêtre peut réattribuer l'id à un autre produit.
  La ligne est maintenant relue et re-vérifiée (`_row_check`, nom + chemin
  URL, prix non bloquant) avant `open_offer_modal` — ligne disparue ou id
  réutilisé → blocker, jamais de modale sur une ligne non vérifiée.

Tests : WRONG_VALUE, READBACK_UNREADABLE, VALUE_DRIFTED_BEFORE_CLICK,
FreshRowRecheckTests (3 scénarios). 526 tests verts. `SUBMITTER_SPEC.md`
§4/§4b mis à jour.

## 2026-07-17 — Audit P0.2 : la preuve post-save exige un scan positivement complet (FC1/SC1/SC2/SC4/SC6/TE1)

L'audit multi-agents du 2026-07-17 (`AUDIT_2026-07-17.md`) a confirmé un
angle mort systématique : le submitter inférait « offre disparue = créée »
de l'ABSENCE de données, sans jamais prouver que le scan avait réellement lu
le feed en entier. Quatre chemins produisaient un faux CREATED : un timeout
CDP silencieusement converti en `None` (lu « 0 lignes »), une page blanche
transitoire (déjà vue live le 2026-07-07 — l'extracteur s'en défendait, le
submitter non), une navigation échouée jamais vérifiée (le tab re-sert le
DOM précédent), et le plafond `max_pages` absorbé sans trace.

Corrections, en miroir de la discipline de l'extracteur :

- `src/cdp_session.py` : `_cmd` lève `CdpCommandError` sur timeout ou erreur
  protocole (fini le sentinel silencieux) ; `navigate` vérifie l'`errorText`
  de `Page.navigate`.
- `src/submit_session.py` : nouvelle sonde read-only `feed_page_state()`
  (`feed_ui`, `nav_max`, `is_login`, `href`) — les mêmes marqueurs
  déterministes que l'extracteur.
- `src/submitter.py` : `_read_feed_page` re-fetch une page blanche UNE fois
  puis classifie (fin de feed prouvée par les marqueurs, sinon
  `FeedScanError`) ; bounce login → `NotLoggedInError` ; `href` comparé à la
  page demandée (navigation coincée détectée) ; épuisement de `max_pages`
  avec un nav qui annonce plus de pages → `FeedScanError` au lieu d'une
  troncature silencieuse. Mid-batch : l'offre courante passe
  `post_save = "offer state UNKNOWN, verify it by hand"` (tentative comptée,
  création NON comptée), le run s'arrête `stopped="feed_unreadable"` en
  écrivant plan + logs. En début de batch : `aborted="feed_unreadable"`.
- `scripts/05_submit.py` : ces exceptions hors boucle → abort JSON propre,
  exit 2 (l'admin affiche l'échec).
- Tests : `tests/test_cdp_session.py` (nouveau, transport fail-closed) +
  `FeedScanFailClosedTests` (8 scénarios : blanche transitoire re-tentée,
  blanche persistante, bounce login, navigation coincée, cap dépassé, feed
  finissant exactement au cap, mort du tab après le clic Create → UNKNOWN,
  mort CDP avant modale). 520 tests verts.

Doc : `SUBMITTER_SPEC.md` §5 mis à jour. Le miroir `EXECUTOR_RULES.md` §7
suivra le commit du chantier Difmark en cours (session parallèle, fichier
partagé).

## 2026-07-16 — R30: AKS site-search fallback when every guessed slug 404s

Romain asked why the matcher only guesses a slug and never queries an LLM or
AKS's APIv2 to resolve the product page — and separately flagged a concrete
failure mode of a naive search fallback: a weak/no-match query gets padded by
AKS with unrelated "top games" filler, so a search hit can't be trusted on
its own. Decision: still no LLM (non-deterministic, would sit upstream of
every other check in this stage) and no APIv2, but add AKS's own WordPress
search (`/blog/?s=`) as a **fallback** — only after every guessed slug 404s
cleanly (a transient probe failure or unreadable page name still fails
closed and never reaches search) — with a **20s timeout** (the endpoint is
slow; the default 5s used everywhere else starves it) and each of up to 3
result slugs probed and identity-checked exactly like a guessed slug: same
R01 (every AKS word present in the title) / R01b (no dangerous qualifier)
gate, no shortcut.

Live-verified the filler risk is real but harmless: Eneba "Worms Collection
2014 Steam Key (PC) EUROPE" (no guessable AKS page) search-resolved to an
unrelated page ("Assassin's Creed Black Flag Resynced") — R01 correctly
SKIPped it (`missing AKS words: ASSASSIN'S, CREED, BLACK, FLAG, RESYNCED`).
Spot-checked against real skips from the same Eneba run: most token-less/
unusual titles still correctly resolve to nothing even with search enabled
— yield is low, as expected for the batch's failure modes, but the
mechanism never bypasses the identity gate.

## 2026-07-16 — R29: Eneba's URL carries a platform prefix the title doesn't

Same Eneba run as R28: candidate "Apothecarium: The Renaissance of Evil -
Premium Edition" had matched as `Publisher GLOBAL(1)`. Romain: "c'est Steam,
pas publisher." The title carries no platform word anywhere — it should have
hit R27's token-less-title skip, not Publisher, so this was actually a
second bug: `explicit_platform(offer.name)` correctly returned `None`, but
somewhere downstream it still resolved to Publisher instead of skipping.

Root cause was upstream of both: the merchant genuinely does declare the
platform, just not in the title. Every Eneba listing URL is
`eneba.com/<platform>-<slug>` — a leading platform-prefix path segment
(`eneba.com/steam-apothecarium-...`) present on every listing regardless of
whether the title repeats it. Fix: `explicit_platform_from_url`, checked as
a fallback after the title, scoped to `eneba.com` URLs only (no other
merchant's URL has a title-word this could false-positive against) and only
recognizing prefixes this codebase already has a platform constant for
(`steam`, `gog`, `epic`, `uplay`→UBISOFT, `origin`→EA, `blizzard`→BATTLENET,
`windows`→MICROSOFT).

Re-resolving with the fix live turned up a second finding: once correctly
Steam GLOBAL(2)/Premium(34), R25's duplicate guard caught it — Eneba
(merchant id 272) already has a price at that exact region/edition on AKS.
The wrong Publisher classification had been hiding a real duplicate, not
just mis-entering the platform.

`src/matcher.py` (`explicit_platform_from_url`, wired into `match_offer` as
`explicit_platform(offer.name) or explicit_platform_from_url(offer.url)`),
mirrored in `EXECUTOR_RULES.md` §4.4. 4 new tests, 476 total, all green.

## 2026-07-16 — R28: NFKC-normalize before tokenizing (Eneba "Road to Empress" escape)

Also same session: candidate "Glary Utilities PRO 5" (a PC cleaning/
optimization utility, same category as CCleaner/IObit) reached the Eneba
candidate list — added `GLARY` to `SOFTWARE_APP_TOKENS` (R22 gap), 1 test,
no design change.

Romain flagged a live mismatch: candidate "Road to Empress Ⅱ Steam Key (PC)
EUROPE" had matched AKS product "Road To Empress" — a different, unrelated
game (AKS has no page for the sequel — 404 on `road-to-empress-ii`). Root
cause: the merchant title used U+2161 ("Ⅱ", a single Unicode Roman numeral
codepoint), not two ASCII `I`s. `tokenize`'s `[A-Z0-9']+` regex silently
drops any character outside that class, so the sequel indicator vanished —
"Road to Empress Ⅱ" tokenized identically to "Road To Empress". The same
text feeds `build_slug_candidates`, so the wrong page was being *probed* in
the first place, not just wrongly approved by the R01/R01b word checks after.

Fix: NFKC-normalize before both (folded into the existing
`normalize_apostrophes` choke-point both call). NFKC is standard library,
zero new dependency, and is specifically designed to decompose compatibility
characters like Roman numerals into plain ASCII ("Ⅱ" → "II") — the real
distinguishing word now survives into slug-building and the identity checks.
Curly quotes stay a separate explicit replace (not an NFKC compatibility
decomposition of `'`).

`src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.1. 3 new tests, 472
total, all green. The Eneba run was re-matched with both fixes before
validation — nothing wrong reached `approved.json`.

## 2026-07-15 — R27: R26 was too broad — Gameboost proved the opposite failure mode

Same day as R26, a Gameboost data-entry run was cancelled live: Romain caught
that Steam offers were being entered as Publisher. R26 (hours earlier) made
any token-less title with *some* AKS page platform signal default to
PUBLISHER — right for DCS P-51D Mustang / A-10C Warthog (Kinguin), wrong for
Gameboost, whose actual platform truth lives on its own merchant page, which
this pipeline can't fetch (Cloudflare blocks it — see the Gameboost
merchant notes). Romain: *"il y a des offres steam qu'on détecte en
publisher, ça c'est seulement renseigné sur la page marchand."*

DCS and Gameboost turned out to be the **identical page-signal shape**
(token-less title, AKS page says "official platforms: Steam." only) with
**opposite ground truth** — proof that neither a Steam default nor a
Publisher default is safe for that shape. Fix: only a page that **explicitly
confirms `Direct Publisher`** resolves a token-less title anymore (unchanged
from R20/R26 for that case — Su-27 still enters PUBLISHER). Everything
short of that — Steam-only, any other non-Publisher-confirmed mix, or no
platform info at all — now **SKIPs** instead of guessing. DCS itself reverts
to skip; a human enters cases like it deliberately, matching the R19
stub-page philosophy (absent a real signal, don't guess in either direction).

`src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.4 and the aks-data-entry
skill's S31. 2 tests rewritten (skip instead of Publisher for the
Steam-only/mixed cases), 470 total, all green. The Gameboost batch (33
candidates) was cancelled before validation — nothing was submitted.

## 2026-07-15 — Admin page: human validation + supervised submit from a browser

New operator page at `https://<VPS_HOST>/executor/` (nginx HTTPS +
basic auth → loopback-only stdlib Python server, `scripts/07_admin_server.py` +
`src/admin/`). Per run: read the normalized report verbatim, approve/reject
each candidate, override platform/region/edition (choices restricted to the
run's own `session_catalog.json` — no catalog, no override), and launch
dry-run / catalog / real submit.

Invariants preserved by construction: every save regenerates the
`candidates.json` + `validation.json` + `approved.json` triple through the
real `04_validate.py check` (never a patched `approved.json`); overrides
rewrite the candidate with an `operator_override` audit field (original pick
frozen) + `operator_override`/`validation_saved` JSONL events; a real submit
spawns the unmodified `05_submit.py`, supervised to its exit code (never
fire-and-forget), one browser-driving run at a time, R24 modes with the
canary cap enforced pre-spawn, and the confirmation modal requires typing
`GO` — the operator's explicit go. Server hardening: loopback bind refusal,
per-run filename whitelist, anti-traversal run ids, custom-header CSRF guard,
log events re-passed through `redact()`. 69 new tests (454 total, green).
Install/runbook: [`../ops/INSTALL_ADMIN.md`](../ops/INSTALL_ADMIN.md).

Same-day additions (Romain): per-offer status **ajoutée / échec / en
attente** derived from the append-only JSONL log (∪ current
`submit_plan.json` — a later dry-run can't erase history; "created" is
sticky over later "not in feed" failures). Already-created offers are locked
in the UI and refused server-side at both gates (`already_created` on
validation save AND on submit start — verified live: the GameSeal 19-offer
batch with 12 created is unresubmittable as-is). Dark theme by default with
a top-right toggle (persisted). Auto-refresh every 10 s (run list, open run
via a server-state stamp, busy badge; unsaved edits are never clobbered — a
"Recharger" banner appears instead; CLI-launched submits stream their JSONL
events live). Deletion of erroneous entries (🗑 per row, "au lieu de les
soumettre"): removed from `candidates.json` at save, triple regenerated,
`candidate_deleted` JSONL event with the full payload; refused for created
offers and combined with approve/override. 470 tests green.

## 2026-07-15 — R26: token-less titles never default to Steam anymore

Live during a 100-candidate Kinguin `--submit` run (R25 already active): 6
offers in, candidate #4 (DCS: P-51D Mustang Digital Download CD Key — no
platform token in the title) had been created as Steam GLOBAL(2). Romain
flagged it live. The run was killed immediately (confirmed: exactly 6
`submit_offer` log entries, all successful, nothing further in flight).

The AKS page for DCS P-51D Mustang says "official platforms: Steam." only —
under the R20-era rule ("a defaulted Steam is trusted only when the page is
Steam-only"), that's exactly the case that keeps the Steam default. Sibling
DCS A-10C Warthog (still pending in the same batch) has the identical page
shape and would have hit the same bug. Romain: *"Si Steam, EA ou autres n'est
pas stipulé ça sera publisher pour ces offres."* Eagle Dynamics modules are
commonly sold as direct/publisher keys the page's own official-platforms
metadata doesn't enumerate — the page being "Steam-only" isn't proof the
merchant's token-less key is a Steam key.

Fix: R20's "Steam-only page → trust Steam" branch is gone. A token-less title
with *any* page platform signal now resolves PUBLISHER, unconditionally; only
a page with *no* official-platforms line at all still SKIPs (zero signal, not
a wrong default). `src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.4. 2
tests rewritten to match, 385 total, all green.

Scanning the remaining 94 pending candidates found exactly one more hit
(DCS A-10C Warthog) — re-resolved and corrected in place in `candidates.json`
(Publisher GLOBAL(1), DLC(16)) rather than a full 3663-offer re-match. The 6
already-submitted offers were removed from the pending set (already live, not
re-submitted). Validation was regenerated and the batch resumed. The one
already-created wrong offer (DCS P-51D Mustang, Steam GLOBAL(2)) needs a
manual DB correction — same remediation pattern as the Valve Complete Pack
escape (2026-07-13): Romain fixes the AKS entry by hand.

## 2026-07-15 — R25: duplicate guard against AKS's own price list

A 43-candidate Kinguin batch, matched the day before, was about to be
submitted when Romain flagged that offers matched a day earlier could already
have been added by a human working the same feed in parallel. The running
`--submit` was killed immediately (confirmed clean: zero submit-stage JSONL
log lines, no `submit_plan.json` written — it was still in its initial feed
index, no offer had been touched).

Checking candidate #5 (Darkwood, GOG GLOBAL(6), Standard(1)) against the AKS
page directly showed the real gap: the page's own price-comparison table
already listed a Kinguin price at `edition:"1", region:"6"` — the exact same
combo. This was not specific to "matched yesterday, stale by today" — the
matcher has **never** checked whether the current merchant already has a
price at the resolved region/edition, on any run, for any merchant. A
candidate only ever proved the offer was still live on the *merchant's own
feed*; it said nothing about whether AKS already had this exact price.

Fix: the AKS page's own `"prices":[…]` array (each entry carries
`merchantName`, `edition`, `region` — the same current-offers table a human
sees on the page) is now extracted at resolve time, zero extra requests, same
pattern as `editions`/`official_platforms`. A candidate whose merchant
already has an entry at the resolved region **and** edition is SKIPPED
("`<merchant>` already lists a price for this region/edition on AKS (R25)")
instead of being proposed as new.

`src/matcher.py` (`extract_prices`, `AksResolution.prices`, the R25 check in
`match_offer`), mirrored in `EXECUTOR_RULES.md` §4.7. 7 new tests (385 total,
all green). The stale Kinguin run (`20260714-180914-kinguin`) was discarded —
re-extracted and re-matched fresh with R25 active before any validation.

## 2026-07-14 — Stage 0b: login/2FA (LOGIN_SPEC.md, Option A)

A Kinguin extraction hit `NotLoggedInError`; Romain asked what it would take
to authorize the assistant to log in itself. Two options were on the table —
(A) a scripted login where the password stays in the environment and Romain
still supplies the 2FA code live every time, or (B) a stored TOTP secret for
fully autonomous login. **B was rejected**: it removes the human checkpoint on
an account that can create live offers and directly contradicts "never store
passwords or 2FA codes." Romain chose **A**.

Built per a short design doc first (`docs/LOGIN_SPEC.md`, same "propose, then
build" convention as `SUBMITTER_SPEC.md`):

- `src/login_session.py` — `LoginSession(WriteSubmitSession)` reuses the
  already-audited trusted-input primitives (`click_trusted_at_element`,
  `_type_text_trusted`) pointed at the WP login form instead of the offer
  modal; no new CDP mechanism. `run_login(...)` holds all the sequencing/
  decision logic as pure control flow over a `session` object — the fully
  unit-tested surface, mirroring `src/submitter.py`'s split.
- `scripts/00b_login.py` — CLI: invariants gate, then `AKS_WP_USER`/
  `AKS_WP_PASSWORD` from the environment only (never a CLI arg), then the
  flow.
- **2FA discipline unchanged from the skill's R0c / `SUBMITTER_SPEC.md` §8's
  pre-agreed rule**: the code is requested only once the 2FA field is
  confirmed visible and ready to submit immediately, never before.
- **One attempt each** for the password and the 2FA code, ever — no retry
  loop, anywhere, even across a second CLI invocation with the same run id
  (`StepGuard(max_attempts_per_signature=1, ...)`; tested explicitly).
- Deterministic success proof: current URL under `/wp-admin/` with no login/
  reauth marker, **and** the admin toolbar DOM node present — either alone can
  be fooled (redirect loop / cached partial page).
- Idempotent: an already-authenticated session is a no-op success, never a
  re-submit.
- Never self-triggered — a `NotLoggedInError` from another stage stays a
  fail-closed STOP + error report, exactly as before; this stage only runs on
  Romain's explicit go.
- Credentials/2FA code never logged: `RunLogger`'s existing key-name redaction
  (`password`, `otp`, `googleotp`, `2fa`, ...) already covered this, no new
  mechanism needed — and the module also never *constructs* a log record
  containing one in the first place.

`tests/test_login_session.py`, 12 new tests (378 total, all green) against a
duck-typed fake session — no CDP, no network. Mirrored in `AGENTS.md`
(refined the 2FA forbidden-list line, added a Stage 0b pointer),
`SUBMITTER_SPEC.md` §8, `EXECUTOR_RULES.md` §9, `README.md` (Requirements,
Roadmap, Safety, Rules & docs).

## 2026-07-13 — R23 P2 fixes: no bundle resurrection, no dict-order guessing

Romain's review of R23 (the page-verified edition lookup) surfaced two P2s
before they could bite live:

1. **Bundle resurrection.** The lookup didn't exclude a `Bundle`-labeled
   match. A title whose own AKS name embeds "Bundle"/"Pack"/"Trilogy" (e.g. a
   Trilogy-titled standalone product) could have the page's own Bundle-named
   entry picked up by R23 — either surfacing as a real Candidate under a
   non-`8` page id (invisible to the existing `edition_id == "8"` skip) or
   getting skipped where the offer used to pass through as Standard pre-R23.
   Fix: `edition_label == "Bundle"` now skips the page-lookup entirely and
   goes straight to Standard(1), same as pre-R23 — there is no such thing as
   a legitimate page-verified Bundle tier given the absolute "never bundles"
   rule.
2. **Dict-order guessing.** When more than one non-Standard page entry
   matched the detected label, `next(...)` silently took whichever the page
   happened to list first — not a matching criterion. Fix: prefer an exact
   (case-insensitive) name match; accept a substring match only when it is
   the sole one; multiple entries tied at the same specificity now SKIP
   ("ambiguous page-verified edition … (R23 P2)") instead of guessing.

`src/matcher.py`, mirrored in `EXECUTOR_RULES.md` §4.5. 3 new tests (366
total, all green).

## 2026-07-13 — R24 (submitter): data-entry modes drive the batch size

Romain generalized R23b into a mode: once the normalized report is validated we
submit, and **`--mode` decides how much of that validated batch goes in**.

| `--mode` | Batch | Why |
|---|---|---|
| `safe` (default) | full validated batch, **no canary** (R23b) | frozen matcher; validation is already the safety gate |
| `learning` | **canary of 1** | exploring one (category × merchant) unlock |
| `advanced` | **canary of 1** | validated unlocks, same cap for now |

**`learning` is NOT a read-only observation mode** — Romain, verbatim: *"le
learning n'est pas un mode d'observation, il ajoute les offres si le rapport
normalisé est valide"*. It writes, it is simply capped. (An earlier internal
design note had it as read-only with its artefacts structurally rejected by
`04_validate`/`05_submit`; that was an over-specification and is now corrected —
no mode is rejected at validation.)

In the canary modes the cap is **enforced, not defaulted** ("tjrs un canary pour
le moment"): a `--limit` above the cap exits 2 rather than being silently
clamped; a smaller `--limit` still narrows. The mode + resulting batch size are
recorded in `submit_plan.json` (`data_entry_mode`, `limit`) and in the
`submit_report.txt` header.

**Known limitation, deliberately documented:** the matcher has no mode profiles
yet, so the mode is *declared* on the CLI and cannot be cross-checked against the
run's artefacts. When `03_match` learns to stamp a mode into `candidates.json`,
`05_submit` MUST re-verify it and fail closed on a mismatch — otherwise a run
matched under an unlock could submit as `safe` and take the full-batch path.

`scripts/05_submit.py` (`--mode`, `mode_limit()`), `manual_launch/run_executor.sh`
(now forwards `--mode` / `--limit`; `--all` kept as a warned no-op), mirrored in
`CLAUDE.md`, `EXECUTOR_RULES.md` §6, `SUBMITTER_SPEC.md` §6, `README.md`,
`NOOB.md`. 9 new tests (`test_submit_cli.py`).

Same pass, from an audit of R23/R23b: `README.md`, `NOOB.md`,
`manual_launch/run_executor.sh` and `src/submitter.py`'s docstring still promised
a canary of 1 for a plain `submit` — i.e. a beginner following `NOOB.md` expected
**1** write and would have got the **whole batch**. Corrected. The launcher also
had no way to forward `--limit`, making R23b's documented escape hatch
unreachable from the one entry point Romain actually uses; it now forwards
`--mode` and `--limit`.

## 2026-07-13 — R23 (matcher) + R23b (submitter): Valve Complete Pack escape

Live correction on a fresh Driffle run: "Valve Complete Pack (Global) (PC) -
Steam Gift" matched AKS 831, but E05 (an edition word inside the AKS product's
own name is identity, not a real edition) collapsed it to Standard(1) — the
same collapse had already mis-submitted an earlier offer of the same product
that morning (Romain deleted the bad AKS entry by hand). The page's own
editions map for 831 is `{92: "Complete Pack", 1: "Standard"}` — a real
Standard-vs-Complete-Pack split the identity heuristic can't see. **R23**:
before collapsing to Standard, check the AKS page's own editions map (already
in hand, zero extra requests) for a non-Standard entry whose name contains the
detected label; a page-verified match wins over both the identity collapse and
the generic `EDITION_HINTS` id (which wasn't even this page's own id: 91
generic "Complete" vs. 831's actual 92 "Complete Pack"). No page match →
Standard(1) as before. `src/matcher.py`.

Separately, Romain requested a standing process change: **R23b** — a
`--submit` run no longer defaults to a canary of 1 before the full batch.
Validation (`approved.json`) is already the safety gate for *which* offers
submit; the per-offer failure handling and 10-consecutive-failure stop
condition are the safety net for *how* a run behaves, and neither needs a
canary on top. `--submit` now processes the full approved batch by default;
`--limit N` still narrows it explicitly. `--inspect` keeps its own
canary-of-1 default (diagnostic mode, not asked to change). `scripts/05_submit.py`,
mirrored in `CLAUDE.md`, `SUBMITTER_SPEC.md` §6, skill `LEARNED_RULES.md` S27.

## 2026-07-08 — R22: software/apps are never candidates (games only)

Live correction on Kinguin p.2: "EaseUS Todo Backup Workstation" reached
validation as candidate #2 — real AKS page, clean Publisher GLOBAL/Standard —
and Romain rejected it: "Skip c est une app". New categorical precheck
`SOFTWARE_APP_TOKENS` (word-boundary, same mechanism as bundles/skins): app
brands (EaseUS…Adobe, VPN brands) + product categories (Internet/Total
Security, VPN, Todo Backup…, Microsoft Office/Office 20xx, Windows 10/11/
Server), reason `software/app, not a game`. Deliberate non-matches where games
exist: NERO, AVG, bare OFFICE/WINDOWS/BACKUP — which surfaced that
`CATEGORY_SKIP` substring-matched `OFFICE`/`VPN` and would skip "The Office
Quest" or "…Officer…" titles: both moved to the word-boundary list. Mirrored
in EXECUTOR_RULES §4.3 and skill LEARNED_RULES R22; suite at 352.

## 2026-07-08 — Audit 5 (P3): secondary docs de-pending-ified

README, SUBMITTER_SPEC, CONTRIBUTING and AUDIT still phrased the success proof
as "gone from pending" (README §StepGuard example, SPEC §5, CONTRIBUTING
determinism rule) — the canonical docs were already correct, but an agent
reading only a secondary doc would relearn the stale rule. All now say "gone
from the refreshed feed (same `available` mode as the run)"; legitimate
`available=pending` mentions (end-of-merchant check) untouched. SPEC §2's row
step also carried the pre-audit-3 absolute "verify title, URL, price,
merchant, page" — aligned with the routing-signal rule and URL-path fallback.

## 2026-07-08 — Audit 4 (2×P2): post-save strings carry the real available mode; submit never fire-and-forget

Romain's read-only audit after pull, two P2s. **1** — `_verify_gone` already
checked the run's `available` mode, but the written proof still hardcoded
"pending": `entry["post_save"]` said `gone from pending` / `STILL in pending`
and the CLI rendered `CREATED (gone from pending)` while the default is
`--available all` — a reader of the artifacts would believe a pending-mode
proof that never ran. Now `post_save` reads `gone from feed (available=<mode>)`
/ `STILL in feed (available=<mode>) — FAILED`, and the CLI renders the entry's
own `post_save` string instead of composing its own (single source). Docstrings
de-pending-ified. **2** — CLAUDE.md's scope-separation bullet said pipeline
stages run "including as background processes", which rubbed against AGENTS.md's
forbidden "fire-and-forget submission". Split explicitly: background OK for the
read-only stages (extract/match/report) with logs collected; submit only on
Romain's go, never fire-and-forget — attached or harness-supervised, canary of
1 by default, exit code + `submit_plan.json` read before any continuation.
Still 350 tests.

## 2026-07-08 — Guidance refresh: CLAUDE.md hard constraints, AGENTS.md aligned, success wording fixed

CLAUDE.md revision from Romain applied verbatim: explicit hard constraints
(never bypass a StepGuard block via retries/reframing/alternate tools; never
force a green invariants result in a non-authoritative environment) and a
scope-separation note (pipeline stages incl. background runs are in scope when
Romain directs data entry, `--submit` only on his go; no self-initiated batch
workers). The submit success example now reads "disappeared from the refreshed
feed (same `available` mode as the run)" — the old "pending feed" wording had
become false: Kinguin `available=pending` is empty even with 1197 rows in
`all`, so "gone from pending" would be trivially true. Same fix mirrored in
EXECUTOR_RULES §2/§6/§7/§8, and AGENTS.md's submission constraints aligned
with audit 3 (price = routing signal, page recomputed, post-save success
criterion spelled out).

## 2026-07-08 — R21: merchant URL always complete + attribute-faithful entity decoding

Romain corrected the report rule live on Kinguin page 1: "il n'y a pas que G2A
qui a des paramètres" — the old format note "G2A: keep `?params`; others:
strip" was wrong, Kinguin rows carry real params too
(`?nosalesbooster=1&currency=EUR`). Rule rewritten (R21): the merchant URL is
always reported and stored **complete, exactly as the feed carries it**, for
every merchant; the URL *path* stays an internal comparison key in the
submitter, never a rewrite. The code already kept full URLs — the real defect
was decode fidelity: `html.unescape` also decodes semicolon-less legacy
entities, mangling `&currency=EUR` into `¤cy=EUR` inside `data-offer` URLs
(a browser keeps `&curren` when unterminated in an attribute). New
`unescape_attribute` in `src/extractor.py` decodes only `;`-terminated
references; `parse_offers_payload` uses it. EXECUTOR_RULES §4.6/§8/§11 and the
skill (SKILL.md format + LEARNED_RULES R21) updated. Tests 348 → 350.

## 2026-07-08 — Audit 3: price is a routing signal, not a blocker — rule made explicit, drift surfaced

Romain's third audit, one residual point: price is compared on the by-id path
but a drift then falls through to the URL identity with `check_price=False`,
so a price difference never blocks when name + URL (+ store) confirm the row —
deliberate, but the doc rule still just said "verify title, URL, price, page,
merchant". Resolved as **behavior intended, rule clarified**: live feeds
reprice constantly between extract and submit and price is never part of what
the modal enters, so blocking on it would be pure friction with zero
protection; on the by-id path the compare's real job is to distrust a
possibly-reused id and reroute to the URL identity. Now explicit in
EXECUTOR_RULES §6 step 2, `_row_check` and `_locate_row` docstrings — and the
drift is no longer silent: a by-id contradiction that ends in a successful URL
relocation is surfaced as `id_mismatches` in the plan entry and the
`row_relocated` log line (a store_id contradiction still blocks on both
paths). Tests updated: price-drift and id-reuse relocations assert their
`id_mismatches`, clean re-import relocation asserts none. Still 345.

## 2026-07-08 — Robustness pass: CLI tests for 05_submit.py, page recompute documented, header counters, annotations

Romain's five-point robustness follow-up, now that the big gaps are closed:
**1** — new `tests/test_submit_cli.py` exercises `scripts/05_submit.py`'s
`main()` in-process (fakes for `build_report`, sessions, submitters — no CDP):
missing validation.json/candidates.json refused, tampered or fabricated
approved.json refused in dry-run AND `--submit` (with proof no session is
ever opened), invariants-red abort, a valid triple passing the gate, and the
canary default (`limit=1`). **2** — "verify page" is deliberately satisfied
by RECOMPUTING the page from the current scan (no page is stored at approval;
pagination reflows): now documented in `_locate_row` + EXECUTOR_RULES §6, and
the recomputed `page_url` is surfaced in the plan entry and the
`row_relocated` log line. **3** — `_index_feed`'s return annotation caught up
with the audit-P1 detail dicts (`dict[str, dict[str, str]]`). **4** — the
`submit_report.txt` header now shows `created=` and `write_attempts=`
explicitly in write mode (audit P2 counters), smoke-tested at the CLI level.
**5** — `Candidate` docstring + EXECUTOR_RULES §8 state that `platform:
"PUBLISHER"` is a normal candidate value (R20 revision), so operators don't
assume the classic store platforms are the whole vocabulary.
Tests: 337 → 345.

## 2026-07-08 — Audit 2 (P2): docs no longer claim an `addItem` fallback in `select_via_trusted`

`docs/EXECUTOR_RULES.md` §6 step 5 and `docs/SUBMITTER_SPEC.md` §4b still said
the trusted Selectize pick had an `addItem(id, false)` fallback for
non-rendered options. The code and tests say the opposite since the
2026-07-06 wrong-edition incident (forcing `addItem` reads the generic master
catalog and created 3 wrong-edition offers): a non-rendered id returns
`NO_OPTION` and fails closed. Both docs now state the fail-closed behavior —
the doc rule is the authority, so the stale text was a regression risk.

## 2026-07-08 — Audit 2 (P1): full row verification on the by-id path before the modal

Romain's second local audit: `_locate_row` accepted a feed row as soon as
`offer_id in index`, but the index only mapped id → page_url — title/URL were
only compared on the URL-relocation path, and `_PAGE_ROWS_JS` only surfaced
id/url/name, so price and merchant were never verified (AGENTS.md requires
"verify title, URL, price, page, merchant" before the modal). Fixed:
`_PAGE_ROWS_JS` now also extracts `price` and `storeId` from `data-offer`;
`_scan_feed` keeps full row details per id; a new `_row_check` compares name +
URL path always, store_id and price when both sides carry a value (feed ids
are import-batch-scoped and reusable, so a mismatching by-id row is treated as
stale and falls through to the merchant-URL identity instead of being
trusted). On the URL-relocation path price is deliberately NOT compared
(re-imports legitimately refresh prices; price is never entered), but a
store_id contradiction blocks. Plan entries record the verified fields as
`row_checked` for the audit trail. Tests: 331 → 337 (RowVerificationTests:
id-reuse distrust, relocation, price drift vs match, store mismatch block).

## 2026-07-08 — R20 revised: token-less keys on publisher-direct AKS pages entered as PUBLISHER, not skipped

Romain's direct rule ("Rentrons les en publisher"), same-day revision — the
same arc as R18 (first response = skip, revision = enter with the right
metadata). When a title carries no platform token AND the resolved page's
"official platforms" list contains `Direct Publisher`, the key is a publisher
key: platform PUBLISHER, region ids from the live WP-admin dropdown catalog
(identical across the 07-07 and 07-08 session catalogs): `Publisher (1)` is
the GLOBAL bucket, EU 12, US 13, UK 266; no gift mapping → publisher gifts
fail closed. Steam-only pages keep the STEAM default; empty lists still skip
(unverifiable); mixes that are neither Steam-only nor publisher-direct still
skip (reworded reason). Live: the Su-27 offer now matches as
PUBLISHER GLOBAL(1) + DLC(16) on product 4496 — exactly Romain's manual DB
correction. Tests: 328 → 331.

## 2026-07-08 — Audit fixes: submit-time re-validation (P1a), hard validity gate (P1b), split write counters (P2), AKS/Staff UA host guard (#4)

Romain's local audit, four findings, all fixed fail-closed:
**P1a** — `scripts/05_submit.py` loaded `approved.json` directly, so a stale/
edited/fabricated file bypassed the strict validation. It now re-derives the
approved set from the sibling `candidates.json` + `validation.json`
(`src/validation.py:verify_approved_against_source`, exact-match on canonical
JSON) and aborts dry-run/inspect/submit alike on any mismatch or missing
source. Live-checked on both 2026-07-08 run dirs + a real tamper (refused).
**P1b** — `fill_then_click_trusted` continued to the click when
`form_validity()` returned `ok:false` (explicit degraded mode). Unreadable
validity now hard-blocks: new `FORM_VALIDITY_UNREADABLE` status, cleanup, no
click; `FORM_INVALID` tightened to `form_valid is not True`. The old test that
asserted the degrade was rewritten to assert the block.
**P2** — the submitter's single `writes` counter counted ready attempts, not
verified creations, overstating `submit_plan.json`. Split into
`write_attempts` (drives `--limit`, conservative) and `created`
(post-save-verified); both `None` outside write mode.
**#4** — `AKS/Staff` UA is allkeyshop.com-only (Romain: "pour les requêtes sur
allkeyshop et seulement celles-ci"): `AKS_STAFF_UA` moved to `src/aks_env.py`
and `http_get` raises on any non-`allkeyshop.com` host (suffix-spoof safe);
CDP browser keeps the Chrome 149 UA. Documented in EXECUTOR_RULES §1/§5/§6.
Tests: 319 → 328.

## 2026-07-08 — R20: title-derived platform verified against the AKS page's official-platforms list

Escape reported by Romain: G2A "Su-27 for DCS World" (run 20260708-152435,
offer 93547835) was entered Steam GLOBAL(2) but the product is
publisher-direct (Eagle Dynamics) — he fixed the DB by hand. Root cause:
`detect_platform` returns STEAM as a fail-open DEFAULT when no token matches
(same pattern as the R19 edition default, one escape earlier). The AKS page's
"official platforms:" line is the only deterministic signal; it is now
extracted at resolve time (`extract_official_platforms`, zero extra requests)
and gated in `match_offer` after R19: a DEFAULTED Steam needs a page list of
exactly `Steam` (empty list or any mix → skip, distinct reasons); an EXPLICIT
title token stays trusted (multi-platform pages are normal — Osmos Steam+GoG
page, Steam key) unless the token's known page name (Steam/GoG/Epic Store) is
absent from the list — contradiction → skip. Retro sweep of all 48
created/attempted offers across 27 AKS pages: Su-27 is the only platform
damage ever. Live check: Su-27 page → skip (R20); Frog Sqwad
(Steam+Xbox Play Anywhere page, explicit "Steam" title) → still a candidate.
Skill LEARNED_RULES R20 added + mirrored here. Tests: 307 → 319.

## 2026-07-08 — R19: empty editions map = stub AKS page → SKIP (edition unverifiable)

Escape reported by Romain: G2A "DCS: A-10C Warthog" (run 20260708-125905)
was submitted Standard(1) but is a DLC — he fixed the DB by hand. Its AKS
page is a stub (`"merchants":[],"editions":[],"prices":[],"regions":[]`,
zero offers): R18 had no DLC bucket to read and the title/slug carry no DLC
token, so the edition fell through to the Standard default — fail-open.
Sibling "DCS: P-51D Mustang" (populated map, DLC bucket) went in correctly
as DLC(16) in the same run. Sampling 25 candidate pages across G2A/K4G/
Driffle runs: 23 have a populated map (mono-edition pages still show
`1:Standard`); the 2 empty ones split one hidden DLC (A-10C) / one legit
standalone (K4G "Goblin Vyke") — emptiness cannot decide an edition either
way. `match_offer` now skips empty-map resolutions with a distinct reason
("AKS page carries no editions map — edition unverifiable (R19)") before the
R18 check; stub pages serialize the map as PHP `"editions":[]`, which the
object-only `extract_editions` already reads as `{}`. Trade-off: legit
standalones on stub pages (Goblin Vyke) are now skipped and stay visible in
`skipped.json` for manual entry. Skill LEARNED_RULES R19 added + mirrored
here. Tests: 303 → 307.

## 2026-07-08 — Submit: URL relocation keys on the path (G2A `uuid=` param drift)

Pre-submit check on the G2A go: 0/716 common products kept their offer id
across 24 h (second merchant confirming import-batch-scoped ids), and the
FULL merchant URL was only 96.4 % stable — the `?uuid=` param rotated on
26/716 rows while the URL path held 716/716 (and is unique in-feed for both
G2A 741/741 and K4G 250/250). Full-URL keying would have mis-skipped drifted
rows ("not in current feed") and, worse, could prove a false "gone from
pending" when a mid-run re-import rotates id + uuid together. `_url_key`
(path, params stripped) now keys `by_url`, `_locate_row` and the
`stop_on_url` disappearance probe. Report format unchanged (G2A candidate
URLs keep their params for Romain's links). Tests: 301 → 303 (param-drift
relocation + worst-case false-disappearance veto).

## 2026-07-08 — R18 revised: DLC bucket = candidate with edition DLC(16), not a skip

Romain's direct rule ("quand on a DLC … sur la page produit AKS on ajoute ça
en édition DLC, on ne skip pas") replaces the same-day skip below: the DLC
bucket on the resolved page states the product's NATURE, and the right entry
is the offer with edition DLC(16) — never Standard, even with a coexisting
Standard bucket. The page-nature override beats every title hint (E0x) and
the bundle-resolution guard ("Pack"/"Deluxe" in a DLC's own name is identity).
Bundle/Early Access buckets remain non-blocking and non-overriding. Skill R18
rewritten + `.hermes` synced; EXECUTOR_RULES: clause moved out of §4.3 (skip
list) into §4.5 (edition detection). Tests: 295 → 300 (net; suite also gained
the submit relocation tests below).

## 2026-07-08 — Submit: rows re-located by merchant URL across feed re-imports

First K4G write session failed 0/10 fail-closed ("offer not in current
feed"): AKS re-imported the feed between extraction (08:13) and submit
(09:26) and re-id'd EVERY row — 0/212 ids survived, while the merchant URL
stayed stable AND unique for all 212. `_scan_feed` now also builds
url → current row; a candidate absent by id is re-located by URL with an
exact-title check (fail-closed on drift), adopts the row's current id (logged
`row_relocated`), and the post-save disappearance proof requires the offer
gone under BOTH keys — id-only would false-positive "gone" whenever a
re-import rotates ids mid-run. Second pass created the canary (GUILTY GEAR
Xrd, relocated 93483480→93504363, gone from pending) with 3 correct
absent-by-both-keys skips.

## 2026-07-08 — Matcher: DLC bucket on the AKS page = skip (R18)

Romain's review of the first K4G candidate list (2026-07-07) caught 9 add-on
contents ("Exoplanets Pack", "Janthir Wilds Expansion", "Supporter Pack", …)
proposed as Standard(1): their titles carry no "DLC" word and match their own
AKS product pages token-perfectly, so R01/R16/R01b all stay silent. The
resolved page's editions map is the truth about the product's nature —
`match_offer` now skips whenever it contains the DLC bucket
(`_dlc_edition_on_page`: id 16, name-match "DLC" as the seatbelt if ids ever
move), even when a Standard bucket coexists ("Brotato: Abyssal Terrors" has
both and is still a DLC). Deliberately NOT extended to Bundle/Early Access
buckets: those describe other offers listed on the page, not the product
("GUILTY GEAR Xrd -SIGN-" {Standard, Bundle} and the Early Access indies were
valid candidates). Zero extra requests — the map was already extracted at
resolve time. Skill LEARNED_RULES R18 mirrored in EXECUTOR_RULES §4.3/§4.7.
Tests: 292 → 295.

## 2026-07-07 — Matcher: trailing-suffix slug peeling (K4G grammar)

First K4G run (226 offers) yielded 0 candidates: 95/226 fell in "no AKS
product page found" because `build_slug_candidates` only stripped parens and
dash-split the head — useless against K4G's separator-less `<Product>
[Edition] [Region] <Platform> CD Key` grammar, and the dash-split silently
amputated real dashed names ("Endless Space - Disharmony" → "endless-space",
a G2A-affecting bug too). Fix in `src/matcher.py`:

- `_strip_trailing_phrases` + `_TRAILING_NOISE_PHRASES`: iteratively peel
  end-anchored platform/region/format phrases (longest-first, word-boundary,
  case-insensitive). Bare `US`/`EU` deliberately excluded ("Among Us");
  `ORIGINS` ≠ `ORIGIN` by boundary.
- `build_slug_candidates` now tiered, most specific first: (1) full
  suffix-stripped name (keeps dashed subtitles), (2) + trailing edition words
  stripped (`_TRAILING_EDITION_PHRASES` = EDITION_HINTS vocab minus
  BUNDLE/PACK/TRILOGY/DLC), (3) legacy dash-split head (Driffle/G2A grammar).
  Over-stripping costs one probe; wrong-page 200s stay caught by R01 +
  extra-words guards.
- `NOISE_TOKENS` += CONNECT/GAMES/LAUNCHER/STORE so correct resolutions are
  not skipped as "different/expanded product" on storefront leftovers.
- `extract_aks_name`: (a) `html.unescape` — `Exile&#039;s` tokenized to
  EXILE/039/S and `&amp;` to AMP, falsely failing R01 on real matches; (b) AKS
  serves a second og:title grammar (`FIFA 21 PC KEY Compare Prices` — no Buy,
  no CD Key) → also split on "Compare Prices" and strip the trailing
  `PC KEY`/`PC` platform marker (bare trailing "Key" kept: "The Key" is a
  real name). Both grammars probed live before fixing.
- K4G note added to EXECUTOR_RULES §11. Tests: 285 → 292.

## 2026-07-07 — Second-pass audit of `src/submit_session.py`

The dedicated audit Romain requested (130 → 1204 lines). Full report appended
to [`AUDIT.md`](AUDIT.md). Verdict: **no P0/P1** — S02/S09/S10 compliant,
fail-closed guards wired and pinned by ~45 tests; the size is inline JS probes
+ incident-history docstrings, not rot. One drift fixed in the pass (SS1: the
module docstring still claimed "the create capability literally does not exist
here" while `WriteSubmitSession` lives in the same file). Six P2 notes filed
(tap leak on mid-flow exception, residual `PREPARED` status, scroll-logic
duplication, `CLICK_MODES` naming, `_press_enter` keypress gap → check on the
P4 canary, no `CSS.escape`) — candidates only if the file is reopened; no
refactor of the frozen, live-proven mechanism.

## 2026-07-07 — Chantier n°2: page-par-page + pacing humain

Invited by Romain's audit ("le prochain incrément logique") now that the
creation mechanism is frozen and live-proven. Addresses the burst / IP-ban risk
on large volumes: the true bursts were the submitter's full-feed `_scan_feed`
walks (index build + re-walk after **every** creation for post-save verify) and
the extractor's multi-sweep walks (e.g. G2A: 27 pages × ≥2 sweeps) — the old
0.5 s inter-offer pause was negligible against those.

- `src/pacing.py` (new) — `Pacer`: bounded-random `uniform(min,max)` waits,
  injectable rng/sleeper (tests never sleep), aggregate counters
  (`waits`, `total_waited_s`) logged once per run via `snapshot()`.
  `parse_pace_spec("0" | "3" | "2-5")`. Never a correctness mechanism —
  settle waits stay separate.
- `src/extractor.py` — paces before every page fetch after the first (both
  modes). New `extract_pages(first_page, last_page)` slice mode: fetches only
  the requested pages, once; result **always `partial: true`** (a slice never
  claims coverage — no sweeps, no `FeedUnstableError`); same fail-closed
  classification (login bounce, blank in-range page); reports `feed_last_page`
  so the operator plans the next slice.
- `src/submitter.py` — `page_pacer` between feed-scan page loads, `offer_pacer`
  between offers (skips offers not actually processed in write mode). The old
  `pace: float = 0.5` run() kwarg is removed. Engine stays neutral: pacers
  default to `None`; the CLIs are the opinionated layer.
- CLIs — `02_extract_feed.py`: `--pace` (default `2-5` s) and `--pages 3` /
  `--pages 3-5`; `05_submit.py`: `--pace-pages` (default `1-3` s),
  `--pace-offers` (default `5-15` s). `0` disables any of them.
- Tests: 260 → 285 (pacing unit tests, slice-mode extraction incl. past-end /
  empty-queue / blank-anomaly / dedupe / guard signatures, pacer wiring in
  extractor + submitter).

## 2026-07-07 — Invariant gate hardened: `no_openvpn_process`

A live audit found a Surfshark `openvpn` daemon running as root (no tun device,
so AKS direct still worked) — a tunnel coming up mid-batch would flip the egress
IP under an authenticated AKS session. The "VPN forbidden while AKS direct
works" rule was only enforced by the shell audit, not by the authoritative gate
that unlocks write stages.

- `src/aks_env.py` — pure `validate_no_openvpn(pids)` (fail-closed: `None` =
  undeterminable state = FAIL) + read-only `list_openvpn_pids()` probe
  (`pgrep -x openvpn`, same match as the shell audit).
- `src/invariants.py` — third StepGuard probe `openvpn_process` in
  `build_report`; check joins the fail-closed aggregate and the report gains an
  `openvpn` section. Guard consecutive-failure limit sized above the probe
  count so a fully-red environment still emits the JSON report instead of
  raising mid-build.
- Doc drift fixes from the same audit: README roadmap now checks off the
  implemented post-save verifier; `00_audit_env.sh` openvpn FAIL reworded.
- Tests: 251 → 260.

Effect on the VPS today: the gate is **red + authoritative**
(`no_openvpn_process` FAIL, pid 1819) until the daemon is stopped — write
stages stay locked, by design.

## 2026-07-06 — S18 RESOLVED: `offer[targets][]` fill → first live submissions

The Selectize-humanisé fix (2026-07-03) made region/edition valid but the form
still would not submit: a trusted click on "Create offer" fired **zero**
admin-ajax. A read-only probe (`probe_targets_field` / `_TARGETS_PROBE_JS`)
isolated the last empty `required` field — `offer[targets][]`, a bare
`<input type="text" required pattern="(\d+)|(https?://.+)">` with a sibling
"add" button (a chip/array field). It wants the **AKS product id** (numeric) or
an http(s) URL — both already on every candidate (`aks_product_id`, `aks_url`).

**Fix — fill `offer[targets][]` in the trusted path, before the validity gate:**

- `src/submit_session.py` — new `add_target_trusted(value)`: trusted CDP click to
  focus the field, `Input.insertText` to type the value, then commit via the
  **adjacent add-button** (trusted click) with a trusted-Enter (`_press_enter`,
  keyCode 13) fallback. Read-only readback (`_TARGETS_READBACK_JS`) confirms the
  input went `valid:true`. Wired into `fill_then_click_trusted(...,
  target_value=...)` as step 4, **before** the HTML5 validity gate.
- `src/submitter.py` — threads `candidate.aks_product_id` through `_prepare` →
  `_process` → `target_value` (cleanest value, matches `\d+`).
- **HTML5 validity gate is now a hard gate** (`form_validity()` /
  `_FORM_VALIDITY_JS`): if the `<form>` is still invalid after region + edition +
  target, the submitter returns a deterministic `FORM_INVALID` verdict and does
  **not** click — no ambiguous "click ignored", no wasted admin-ajax.
- `--click-mode` now **defaults to `trusted`** (the only mode proven to fire
  Driffle's handler); `native`/`dispatch` kept only as documented diagnostics.
- `scripts/05_submit.py` — report now prints `target_add=` (status/commit/value/
  readback) and `form_valid=`/`invalid_required=` per offer.

**First live-confirmed submissions (Romain-triggered `--submit`).** A canary of 1
(offer 93185190 **Demigod**, Steam EU(9)/Standard(1), run
`20260706-161225-driffle`) succeeded end-to-end: target filled
(`valid:true`), `form_valid:true`, trusted click → **admin-ajax
`…do=create_offer` → 200**, server signal `"[product 2101] Offer created for
locale en_EU and merchant 408"`, and — the only authoritative proof — **gone
from the refreshed pending feed** `[S18]`. We do **not** issue a direct XHR; the
trusted click drives the modal's own `create_offer` and we merely *observe* the
resulting request as a corroborating signal.

**First scaled batch** (run `20260706-162745-driffle`, `--limit 100
--available all`, 4 approved): **3 created** — Gambonanza, Hello Neighbor 2,
Heart of the Machine (all Steam EU(9)/Standard(1), all gone from pending). **1
clean fail (new Layer-5, server-side):** Serious Sam HD Double Pack
(GLOBAL(2)/Bundle(8)) — region/edition picked, form **valid**, target filled,
yet `create_offer` returned `Bad request: paramètre "offer" manquant ou
invalide`. Fail-closed caught it (status=ERROR → not submitted, no false
success, batch continued). This is **not** a regression — expect some
bundle/non-Standard offers to reject server-side even when the form is valid.

**190 tests green.** Commits `41c6bb5` (target fill) + `12fd2ec` (validity gate,
probe, default trusted).

## 2026-07-03 — Chantier n°1 extension: Selectize humanisé (no more `setValue`)

Canary #4 (FRACT OSC, offer 92625611) with `--click-mode trusted` proved the
trusted click LANDS on the correct button (`element_at_center.is_button: true`,
`button_style.pointer_events: auto`) — yet still `requests: []`. Enriched
`--inspect` probe revealed the real blocker: **`form_all_inputs_valid: false`**.
Three `required` text inputs are empty at click time:

- `offer[targets][]` — a real named data field, never filled by our setValue path.
- Two anonymous `<input type="text" required>` inside Selectize wrappers whose
  `parent_class` is `selectize-input items required invalid not-full has-options`
  — Selectize's own UI text input inherits `required` from the underlying
  `<select required>`, and stays empty when the value is set via `.selectize.setValue()`
  because that's a programmatic setter, not a real user interaction.

Consequence: HTML5 form validation blocks the `submit` event before any
handler fires. No handler ⇒ no XHR ⇒ `requests: []`.

**Fix — Selectize humanisé** (Chantier n°1 extension, authorized Romain 2026-07-03):
replace `setValue` with a trusted CDP click on the `.selectize-input` (opens
dropdown), wait 250 ms, trusted CDP click on `.selectize-dropdown-content
.option[data-value="{id}"]` (selects). Same handler chain as a real operator —
Selectize's own event listeners fire, likely populating `offer[targets][]` as
a side-effect. Still no `.click()`, no `dispatchEvent`, no `form.submit()`,
no XHR, no `setValue`. **169 tests green.**

- `src/submit_session.py` — new `select_via_trusted(select_name, value_id)`:
  reads `.selectize-input` rect (S02-safe `_SELECTIZE_INPUT_RECT_JS`),
  trusted CDP click at its center, 250 ms settle, reads
  `[data-value="{id}"]` rect (S02-safe `_SELECTIZE_OPTION_RECT_JS`,
  requires the dropdown visible), trusted CDP click, 200 ms settle,
  reads back `select.value` + `select.selectize.getValue()` + `select.validity.valid`
  (`_SELECTIZE_READBACK_JS`). All events `isTrusted: true`.
- `src/submit_session.py` — refactored the mousedown/dwell/mouseup sequence
  into a private `_trusted_click_at_rect(rect)` helper; `click_trusted_at_element`
  and `select_via_trusted` both use it. No behavior change for the button click.
- `src/submit_session.py` — `_TRUSTED_PREP_JS` no longer calls `setValue`;
  it only installs the network taps + captures pre-existing signal counts + texts
  + button visibility. `_TRUSTED_POLL_JS` now accepts a text CHANGE on an
  existing `[data-success]`/`[data-error]` template node as a valid ACK (Driffle
  updates a pre-existing `<p data-success>` textContent instead of adding a
  node — the previous "new node only" guard would have missed it).
- `src/submit_session.py` (`_INSPECT_MODAL_JS`) — enriched:
  `element_at_center` (`elementFromPoint` at button center), `button_style`
  (pointer_events / z_index / opacity / visibility / display), `form_inputs`
  (name / type / required / value_len / visible / willValidate / validity /
  parent_class), `form_all_inputs_valid`. Read-only, S02-safe.
- `src/submitter.py` — `Submitter._process` unchanged interface; still routes
  to `fill_then_click_trusted` when `click_mode='trusted'`. The internal
  orchestration now uses select_via_trusted twice + click_trusted_at_element.
- Tests: +6 (SelectViaTrusted 4 tests: success chain reads/clicks/readback,
  no_input early-out, no_option after open, S02 guard on the 3 new probes;
  FillThenClickTrusted +3: full success chain merges prep+picks+click+poll,
  region-pick failure triggers cleanup, edition-pick failure triggers cleanup).

**S09 dérogation étendue (2)** : la couche de synthèse trusted couvre maintenant
non seulement le clic sur "Create offer" mais aussi les interactions Selectize
UI (open dropdown + pick option). Toujours aucun `form.submit()`, aucun XHR,
aucun clavier synthétique. Post-save reste juge.

**Next diag** on the VPS (approved.json still points at offer 92625611):

```
python3 scripts/05_submit.py runs/driffle-canary-trusted-1625/approved.json \
    --merchant Driffle --store-id 127 --submit --click-mode trusted
```

Grille :
- `region_pick.status: SELECTED` + `readback.selectize_value` == region_id + `validity_valid: true` → Selectize UI clic OK.
- `requests: [POST admin-ajax.php … -> 200]` + offer gone from pending →
  **Chantier n°1 + Selectize humanisé confirmés**, gel du mécanisme.
- `region_pick.status: NO_OPTION` → dropdown open ok mais l'option n'était pas
  encore rendue (timing) → augmenter le settle post-open ou attendre
  `[data-value]` avant lecture rect.
- `requests: []` **encore** → épuisé les hypothèses connues, on ouvre DevTools
  live pour `getEventListeners(document)` sur la page pending.

## 2026-07-03 — Chantier n°1: `--click-mode trusted` (CDP `Input.dispatchMouseEvent`)

Canary #3 (Driffle) confirmed the S18 root cause: both `native` (`.click()`) and
`dispatch` (MouseEvent) produced `requests: []` with a visible, enabled Create
button. Driffle's handler almost certainly checks `event.isTrusted`, which is
`false` for any DOM-synthesized event. `Input.dispatchMouseEvent` is the only
CDP path that yields `isTrusted: true` — it's what a real desktop operator's
mouse produces. **163 tests green.**

- `src/submit_session.py` — new `click_trusted_at_element(selector)`:
  reads target rect + viewport via `evaluate_readonly` (S02-safe `_RECT_JS`);
  if outside viewport, sends one `Input.synthesizeScrollGesture` (mouse source,
  speed 800), waits **500 ms** for settle, re-reads rect; then
  `Input.dispatchMouseEvent` sequence `mouseMoved(cx,cy)` →
  `mousePressed(cx,cy,left,clickCount=1,buttons=1)` → **random 40-90 ms** dwell
  → `mouseReleased(cx,cy,left,clickCount=1,buttons=0)`. No `.click()`,
  no `dispatchEvent`, no `form.submit()`, no XHR, no keyboard.
- `src/submit_session.py` — new `fill_then_click_trusted(...)`: 2-phase orchestration.
  `_TRUSTED_PREP_JS` fills selectize + installs network taps
  (`window.fetch` / `XMLHttpRequest` wrapped into `window.__s18taps`) + records
  `pre_existing` counts + returns button state; CDP trusted click follows;
  `_TRUSTED_POLL_JS` waits for a NEW `[data-success]`/`[data-error]` node
  (pre-existing guard), reports `requests`/`polls`/`signal`, and restores the
  taps. `_TRUSTED_CLEANUP_JS` restores taps if the click cannot fire (rare).
- `src/submitter.py` — `Submitter` routes to `fill_then_click_trusted` when
  `click_mode='trusted'`; `fill_and_create` unchanged for `native`/`dispatch`.
  `ALL_CLICK_MODES = ('native','dispatch','trusted')` validated at `__init__`
  (`ValueError` on unknown). Post-save (offer gone from refreshed pending) is
  **strictly unchanged** and remains the ONLY success proof in every mode.
- `scripts/05_submit.py` — `--click-mode` accepts `trusted`; the text report
  prints one `trusted_click:` line with click coords + delay_ms + scrolled +
  viewport + rect + click status.
- +12 tests (trusted click sequence order, in-viewport vs out-of-viewport paths,
  scroll gesture params, element-disappears-after-scroll edge, `_RECT_JS`
  read-only guard, `fill_then_click_trusted` merges prep+poll on success,
  cleanup called on `NO_ELEMENT` click, `Submitter` refuses unknown
  `click_mode`, trusted-mode success + still-pending failure).

**S09 derogation étendue** (Romain, autorité n°1, 2026-07-03) : le bouton
officiel visible reste **la seule cible** ; seule la couche de synthèse
d'événement change (DOM → input CDP). `form.submit()` / XHR direct / clavier
synthétique **restent interdits**.

**Next diag on the VPS**:

```
python3 scripts/05_submit.py runs/<id>/approved.json \
    --merchant Driffle --store-id 127 --submit --click-mode trusted
```

Grille de lecture :
- `requests` contient un `POST /wp-admin/admin-ajax.php … -> 200` **et** offre
  disparue du pending → **succès Chantier n°1 confirmé**, gel du mécanisme.
- `requests` avec un 4xx/5xx → handler atteint mais rejet serveur (nonce,
  merchant id, payload) — nouvelle piste, voie DOM restée saine.
- `requests: []` **encore** → hypothèse trusted à revoir (rare : le handler
  écoute autre chose qu'un click, ex : sur le form via `submit`).

## 2026-07-03 — S18 investigation: `--inspect` modal DOM probe (read-only)

Canary #3 (Driffle) with the pre-existing signal guard active produced
`requests: []` + `status: NO_SIGNAL` in **both** `native` and `dispatch` click
modes: the click reaches no handler that fires an admin-ajax request. Prime
suspect now: the `.button-primary` sniper matches an element that has no
handler bound (WP admin `<a href="#">`, or a delegated listener not rebound
after the ThickBox AJAX load). Read-only DOM probe added to identify the
true submit-trigger element and its form, without clicking Create.

- `src/submit_session.py` — new `_INSPECT_MODAL_JS` + `SubmitSession.inspect_modal_dom()`:
  read-only probe returning `{ button: {tag, type_prop, type_attr, id, klass,
  href, name, text, data_attrs, path}, button_count_in_modal, form: {tag, id,
  klass, action, method, onsubmit_attr}, forms_in_modal, forms, modal_selects,
  data_success_in_modal[…], data_error_in_modal[…], data_success_in_doc,
  data_error_in_doc, tbwindow_style }`. Passes the S02 mutation guard (no
  click/submit/fetch/setValue/dispatchEvent).
- `src/submitter.py` — new `InspectSubmitter` (write_mode=False, event_name
  `inspect_offer`): reuses `_index_feed` / `_prepare` and calls
  `inspect_modal_dom` on each ready entry. No clicks on Create, no writes.
- `scripts/05_submit.py` — new `--inspect` flag (mutex with `--submit`; canary
  of 1 by default, `--limit N` / `--all` to widen). Writes `modal_inspection.json`.
- +6 tests (inspect flow, JSON parsing, S02 read-only guard on the probe JS).

**Next diag** on the VPS:

```
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle \
    --store-id 127 --inspect
```

Then inspect `runs/<id>/modal_inspection.json`. Reading grid:
- `button.tag=A` + `href='#'` → the real trigger is elsewhere (jQuery delegated
  handler somewhere up the DOM path); look at `button.data_attrs` for hints.
- `form.action` non-vide → soumission `<form>` classique ; le vrai geste est
  peut-être un `form.submit()` intercepté (S09-forbidden — regarder `data_attrs`
  et `onsubmit_attr`).
- `button_count_in_modal > 1` → on ciblait le mauvais bouton depuis le début.

## 2026-07-03 — S18 investigation: network taps + dispatch click mode (derogation)

Live canary #2 (Driffle) eliminated hypothesis #1: the selectize readback proved
`setValue` took perfectly (`region_set=9`, `edition_set=1`, options exact) — yet
`[data-success]` appeared with an **empty** signal text and the offer stayed in
pending. Prime suspect: a pre-existing (template/hidden) `[data-success]` node
being mistaken for the AJAX ack, and/or the native `.click()` not firing Driffle's
real submit handler. **144 tests green.**

- `src/submit_session.py` — `_FILL_CREATE_JS` instrumented:
  - **pre-existing signal guard**: `[data-success]`/`[data-error]` nodes are counted
    BEFORE the click; the poll only accepts a **new** node (count increased) —
    otherwise it ends `NO_SIGNAL`. `polls` + `pre_existing` land in the diag.
  - **network taps** (diagnostic only): `window.fetch` + `XMLHttpRequest` are wrapped
    around the click and restored after; the diag reports `via/method/url/status`
    for every request the click fired — never bodies, never headers/cookies. An
    empty `requests` list = the click never reached the network.
  - **button state** (`disabled`/`visible`/`text`) recorded pre-click.
  - **`click_mode='dispatch'`** — full `mousedown/mouseup/click` MouseEvent sequence
    **on the Create button ONLY**. This is an explicit, documented derogation from
    the S09 no-`dispatchEvent` rule, **authorized by Romain (2026-07-03, authority
    order #1)** after the native click was proven not to persist on Driffle. Still
    no `form.submit()`, no XHR submission; unknown modes raise (fail-closed).
- `src/submitter.py` — `Submitter(click_mode=...)` passes the mode through; the
  post-save feed check remains the ONLY success proof, unchanged, in both modes.
- `scripts/05_submit.py` — `--click-mode {native,dispatch}` (native default,
  refused without `--submit`); the text report now prints polls / pre_existing /
  button state and one `net:` line per captured request.
- +4 tests (dispatch pass-through, dispatch still fails when still-pending, native
  default, unknown mode refused).

Also today (infra, no code): AKS dropped the VPS IP at TCP level (curl `000`,
google OK, DNS OK, AKS up from elsewhere) — the documented skill pattern "AKS
bloque les IPs après un burst". Resolved by Romain via the skill's Surfshark
targeted-route rotation (`de-fra` TCP, `--route-nopull --route 176.31.53.220`);
invariants back green+authoritative. Known doc drift to resolve: `00_audit_env.sh`
still FAILs when an openvpn process runs — decision pending on wording it as
"forbidden when direct works / tolerated targeted-route when AKS drops the IP".

## 2026-07-02 — Stage 4: real submitter (WRITES, canary-first)

The real write path — approved by Romain, and validated end-to-end in **dry-run on
the VPS first** (modals open; Driffle selects are `offer[region]`/`offer[edition]`;
Battle.net Gift region resolves to 570). **138 tests green.**

- `src/submit_session.py` — `WriteSubmitSession(SubmitSession)` adds the ONE mutating
  op, `fill_and_create`: `selectize.setValue` on the verified select names, then
  click `#TB_ajaxContent .button-primary` (Promise + 500 ms; skill S09/S17/S19). No
  XHR, no `dispatchEvent`, no `form.submit()`.
- `src/submitter.py` — `Submitter` (real): `fill_and_create`, then **post-save
  verification** — re-scan the feed; `success = the offer disappeared from pending`
  (never `[data-success]`; skill S18). Shares its base flow with the dry-run.
- `scripts/05_submit.py` — `--submit` writes; **canary default = 1 offer**, `--all`
  for the full batch, `--limit N` otherwise. Gated on green + authoritative invariants
  + pre-flight login; one attempt per offer, skip + continue, stop after 10 consecutive.
- 5 tests (canary stops after 1, full batch, still-present = failure, unconfirmed
  click = failure, not-ready never writes).

First real run (canary):
`python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit`

## 2026-07-02 — Stage 4: submitter (DRY-RUN only, no writes)

The submit flow, dry-run only — **no writes**. **132 tests green.** Approach
approved by Romain (`docs/SUBMITTER_SPEC.md`).

- `src/submit_session.py` — `SubmitSession` (extends the read-only CDP session):
  list a page's offer ids, open an offer's modal, read the modal context, detect the
  WP login page. **No method fills a form or clicks "Create offer"** — the create
  capability does not exist in this build.
- `src/submitter.py` — `DryRunSubmitter`: pre-flight login check, locate the exact
  current row, open the modal, verify context + select names, report what it *would*
  submit. Per Romain's decisions: one attempt per offer; on failure log + skip +
  continue; stop the run after **10 consecutive** failures (StepGuard).
- `scripts/05_submit.py` — `--dry-run` (default), gated on green + authoritative
  invariants; `--submit` is **refused** (write path not built). Writes
  `submit_plan.json` + `submit_report.txt`.
- 7 tests (login abort, ready plan, skips, select-name conventions, stop-after-10).

Run on the VPS: `python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127`.

## 2026-07-02 — Stage 3: validation gate

Read-only validation — the fail-closed gate before any submission. **125 tests green.**

- `src/validation.py` — `validation_template` (operator fills approve + who/when)
  and `load_validation`, which verifies a filled file against the CURRENT
  candidates: `run_id` must match, `validated_by`/`validated_at` required, and every
  approved entry must be an exact current candidate by fingerprint
  (`offer_id|aks_product_id|region_id|edition_id`) — a re-match that changes a
  region/edition invalidates a stale approval (skill S15). Any problem rejects the
  whole file (never partially honored).
- `scripts/04_validate.py` — `template` writes `validation.template.json`; `check`
  verifies a filled `validation.json` and writes `approved.json`. Read-only.
- 9 tests. This approval is the lock the future submitter will require — no
  submission is possible without it.

## 2026-07-02 — Sprint 3: read-only matcher

The matcher stage is built (read-only). **Suite: 109 tests green.**

- `src/matcher.py` — ports EXECUTOR_RULES §4: apostrophe-normalized tokenizer,
  R01 strict name match, R01b dangerous-qualifier guard, categorical SKIP lists
  (console, forbidden region, currency/gift/sub, DLC, bundle, language
  restriction), platform + region (URL-first) + edition detection, AKS slug build
  + read-only resolve (`data-product-id` + editions), cap 100. `Candidate` +
  `SkippedOffer` dataclasses; `normalized_block` emits the skill's exact report
  format (`#N — … / 🎯 id — name / 🔗 url / 🎯 aks-url / Platform REGION(id), Edition(id)`).
- `scripts/03_match.py` — reads `offers.json`, resolves candidates against AKS
  (read-only GET), writes `candidates.json` + `skipped.json` + a normalized-text
  `report.txt` (no tables). Aborts if AKS is unreachable.
- 33 tests. Forbidden-region short tokens (NA/OTHER/SEA) excluded to avoid title
  collisions ("Sea of Thieves"); candidates are human-reviewed before any submit.
- Hardened from the first live Driffle run (272 → 5 candidates): added the
  different/expanded-product guard (≥2 extra significant words, or an extra version
  number → SKIP — e.g. GreedFall "The Dying World" ≠ base GreedFall) and Gift
  region detection (Steam 25/259, Battle.net 570/567). Re-validated: 5 → 3 clean
  candidates.

Run on the VPS: `python3 scripts/03_match.py runs/<run_id>/offers.json`.

## 2026-07-02 — Sprint 2: read-only feed extractor

The extractor stage is built (still strictly read-only). **Suite: 83 tests green.**
Unblocked by the VPS invariant gate going green + authoritative.

- `src/cdp_session.py` — stdlib raw-socket CDP session adapted from the skill's
  proven transport (no Origin header → avoids the Docker-terminal 403). Exposes
  only `navigate` + `evaluate_readonly`; refuses mutation-looking expressions
  (`.click(`, `dispatchEvent`, `setValue`, `admin-ajax`, `fetch(`…). Never clicks,
  fills, or submits. Zero new dependencies.
- `src/extractor.py` — `feed_url` (pagination `&p=N`), `parse_offers_payload`
  (`html.unescape` + `json.loads`, skill rule F05), paginated extraction through
  the StepGuard, dedupe-by-id → `RawSnapshot` + `NormalizedFeed`, logged via
  `RunLogger`.
- `scripts/02_extract_feed.py` — CLI that **refuses to run unless invariants are
  green AND authoritative**, then writes `runs/<run_id>/raw.json` + `offers.json`.
- 11 tests (feed URL, payload/entities, pagination/dedupe/stop rules, guard
  wiring, read-only refusal). The live CDP path runs on the VPS.

Run on the VPS: `python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127`.

## 2026-07-02 — P2 debt cleanup

Closed the P2 findings from `AUDIT.md`. **Suite: 72 tests green.**

- **C4 — StepGuard limits decoupled.** A new `max_failures_per_signature`
  (hard-block threshold) is distinct from `max_attempts_per_signature` (the
  pre-execution attempt ceiling); the success-then-failure asymmetry is now
  explicit and tested.
- **C5 — one blocked-decision builder.** `check()` and `run_step` both use
  `_blocked_decision(signature)`, preserving the real signature.
- **C6 — CDP client fails closed without probing** a non-official endpoint (no
  network I/O when the endpoint check fails).
- **S3 — audit config excerpt whitelisted.** `00_audit_env.sh` greps only
  `docker_extra_args`/`container_persistent`/`network` instead of dumping 20 lines
  of the Hermes config into the report.
- **T5 / T6 — coverage.** `current_environment` override logic and StepGuard edge
  cases (success-then-failure, blocked decision, record-while-blocked, snapshot
  counters) are now tested (+8).

Remaining: **S2** — delete the stale gitignored `runs/audit_2026-07-01` artifact
locally (the sandbox mount can't unlink it).

## 2026-07-02 — Sprint 2 foundations (G2, G3)

Closed the remaining pre-Sprint-2 gaps from `AUDIT.md`. **Suite: 64 tests green.**

- **G2 — data contracts** (`src/contracts.py`): `RawSnapshot`, `NormalizedOffer`,
  `NormalizedFeed` frozen dataclasses with stdlib validators (fail-closed
  `ContractError`), dedupe-by-id, `to_dict`. The enforced JSON shapes for the
  extractor's output — see [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md).
- **G3 — JSONL run logger** (`src/run_log.py`): append-only `logs/<run_id>.jsonl`
  with recursive secret redaction (never logs `webSocketDebuggerUrl`, cookies, or
  2FA) and `log_guard(...)` to persist a StepGuard snapshot per task.
- Docs: added `DATA_CONTRACTS.md`; +20 tests for the two modules.

The read-only extractor (Sprint 2) that produces these artifacts still waits on
green VPS invariants before it is built.

## 2026-07-02 — P1 audit remediation

Closed the P1 findings from `AUDIT.md`. This hardens the read-only Sprint-1
foundation and its tests; there is no write path yet, so no runtime behavior
changed for submissions. **Test suite: 44 green (was 28).**

### Correctness & fail-closed
- **C1 — the two gates now probe AKS identically.** The shell audit
  (`scripts/00_audit_env.sh`) and the Python checker both do a **GET**, do **not**
  follow redirects, accept only **200/301/302**, timeout **10 s**. The checker no
  longer uses HEAD, so `audit.md` and the invariant JSON can no longer contradict
  each other.
- **C2 — "reachable" tightened.** `validate_aks_direct_status` now accepts only
  **200/301/302** (was 200–399). `http_get` gained `follow_redirects` (default
  `True`); the AKS probe runs with `follow_redirects=False`, so a redirect to a
  login/geo wall surfaces as its real 3xx instead of being followed to a 200.
- **C3 — control-channel token redacted.** The CDP `webSocketDebuggerUrl` is no
  longer serialized; the report exposes only `webSocketDebuggerUrl_present: bool`
  via `redact_cdp_payload`.

### Security
- **S1 — `.gitignore` hardened** with credential/cookie/token/pem/har/`.DS_Store`
  patterns. Specific patterns only, so source files are never accidentally ignored.

### Architecture / wiring
- **G1 — the checker now runs its probes through the StepGuard.** `build_report`
  (extracted to `src/invariants.py`) wraps the AKS + CDP probes in
  `guard.run_step(...)` with deterministic success predicates and includes the
  guard snapshot in the report. This is the template every future stage follows.
- Refactor: `scripts/01_check_invariants.py` is now a thin CLI over
  `src/invariants.py` (which also makes the report logic testable).

### Tests & CI
- **T1 — CI added** (`.github/workflows/ci.yml`): unittest suite on Python 3.10 +
  a source-only secret scan, on every push / PR.
- **T2** — HTTP probes tested via a mocked IO seam (`_http_open`): 2xx / HTTPError
  / URLError / Timeout branches, the no-follow 302 case, and the HTTP method used.
- **T3** — `cdp_client.get_version` tested across all four outcomes + wrong-endpoint.
- **T4** — `src/invariants.build_report` tested: guard wiring, payload redaction,
  ok/authoritative, 302-accepted.

### Deliberately deferred (tracked in `AUDIT.md`)
P2 debt (C4, C5, C6, S2, S3, T5, T6) and the Sprint-2 foundations **G2** (data
contracts) and **G3** (JSONL run logs) remain open — these are net-new modules
rather than fixes, and are the recommended next increment.

## Historique déplacé depuis EXECUTOR_RULES (2026-09-15)

Lot 1 « remettre la documentation en cohérence » (Romain, 2026-09-15) : `docs/EXECUTOR_RULES.md` ne garde que les RÈGLES EN VIGUEUR ; les récits datés (audits, « avant ce correctif … », comptages de lots passés, incidents) sont déplacés ici, groupés par identifiant de règle, avec leur date d'origine et la section d'origine. Chaque règle garde un pointeur « historique : CHANGELOG <date> ». Aucun identifiant de règle n'a été retiré d'EXECUTOR_RULES (vérifié par script : ensemble des identifiants entre crochets conservé avant / après, titres de sections et lignes de tableaux inchangés, aucun U+FEFF).

### R28

- **2026-07-16 — EXECUTOR_RULES §4.1** (R28) : Eneba "Road to Empress" escape (2026-07-16): "Road to Empress Ⅱ" (U+2161, a single Unicode
Roman numeral codepoint, not two ASCII `I`s) tokenized to just ROAD/TO/EMPRESS — `tokenize`'s
regex silently dropped any character outside its class, so the sequel indicator vanished and
the offer matched the unrelated base game "Road To Empress" (AKS has no page for the sequel —
404). The same text fed `build_slug_candidates`, so the wrong page was being *probed* in the
first place, not just wrongly approved after tokenizing. Fix: NFKC-normalize before both —
standard-library, zero-dependency.

### R01b

- **2026-07-17 — EXECUTOR_RULES §4.2** (R01b / MA3) : Audit 2026-07-17 (MA3): `Anniversary` / `Definitive` were noise-whitelisted with no backstop,
so "Skyrim Anniversary Edition" entered the base-game page as Standard(1). They became
dangerous qualifiers of the different-product guard (R01b).

### R43

- **2026-09-11 — EXECUTOR_RULES §4.3** (R43) : Before R43 (until 2026-09-11) "DLC in title" (DLC / Add-On / Downloadable Content) and the
`SEASON PASS` category were pre-skips, so a DLC that announces itself never reached resolution
while a DLC that hides it ("Exoplanets Pack") was entered via R18. Measured 2026-09-11 on 12
MMOGA "(DLC)" titles: 9 resolve, by plain slug guessing once the marker is stripped, to their
OWN AKS page ("Northgard Svardilfari Clan of the Horse", "Railway Empire Great Britain &
Ireland", "Ready or Not Home Invasion"…) and all 9 carry the DLC bucket (16); 3 have no page.

- **2026-09-11 — EXECUTOR_RULES §4.3 (a) own-page rule** (R43) : Own-page rule measurement (adversarial review 2026-09-11): 204/205 dry-run DLC candidates
resolve at tier 1; the one loss, "Destiny 2: Year of Prophecy Ultimate Edition DLC", is a
fail-safe skip.

### R18

- **2026-09-11 — EXECUTOR_RULES §4.3** (R18) : R18 review (2026-09-11): the review found live base-game pages carrying bucket 16 (Stray
Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake — entered DLC(16) on 2026-09-10) and
no deterministic page-level nature signal (no product-type field; the "#basegame" related
section and the editions-map order are both inconsistent across sampled DLC / base pages).
Romain's ruling: "des fois, les titres n'ont pas de marqueur et sont des DLC" — the bucket
keeps deciding for a markerless title, and those three entries are NOT to be corrected (now
in AGENTS.md « Reviewed decisions »).

### R45

- **2026-09-11 / 2026-09-12 — EXECUTOR_RULES §4.3** (R45) : The 2026-09-11 study ("on reviendra sur les consoles après modification de l'outil AKS
feed") was reopened the next day. **Correction of finding (a) (2026-09-12):** the 11/09 probe
used a WRONG URL grammar (`…-xbox-series-x-…-cd-key-…`). Console product pages DO exist, at
`buy-<slug>-<kind>-compare-prices/` (Hades: PC 26712, PS5 85105, PS4 85104, Xbox Series
85103, Xbox One 85102, Switch 47979). Console offers therefore do NOT all live on the PC page
— only the Xbox family (`300`, and the XBOX/PC Play Anywhere buckets) was ever seen there.
Findings kept as history: (b) the feed modal's region catalog (867 buckets) has the console
families: Xbox One `24` / EU `24eu` / US `24us` / UK `226`, Xbox Series `300` / EU `302` /
US `303` / UK `305`, Xbox+Windows (Play Anywhere) `306` / EU `241` / US `242` / UK `240`,
PlayStation 4 `88` / EU `88eu` / US `88us` / UK `88uk`, PS5 `88ps5h` (single bucket),
Nintendo `99` / EU `99eu` / US `99us` / UK `992` — Switch 2 pages use the SAME Nintendo
family buckets (no separate Switch 2 bucket — 2026-09-14, table in EXECUTOR_RULES §10); (c)
MMOGA grammar: URL categories `Xbox-Live/Xbox-One-Game-Keys`,
`Xbox-Live/Xbox-Series-XS-Game-Keys`, `Nintendo/Switch`, `Playstation-Network`, platform in a
bracket of the title, region tail " - EU" / "[EU]", non-games among the console rows
(currencies, Xbox Live / eShop cards, subscriptions) that stay skipped; (d) the BLOCKER of
the pre-modal-v2 tool: one feed row = one offer, consumed by its creation, so a cross-gen key
could not get its second platform from the feed as it was — exactly what the per-target
overwrite of the new tool (modal v2, 2026-09-14) addresses.

- **2026-09-12 → 2026-09-15 — EXECUTOR_RULES §4.12** (R45 (§4.12 intro)) : Romain's trigger wording (2026-09-12): the AKS feed tool is being changed to OVERWRITE the
region (and the edition — "pas nécessaire mais ajoutée") PER TARGET PAGE: a PS5 key is added
on the PS5 page and also on the PS4 page by overwriting the region to PS4; an Xbox key goes
on Xbox One, Xbox Series X and — for Xbox Play Anywhere games ONLY — PC (P1 later narrowed
this to the DECLARED platforms only, 2026-09-14). `--consoles` was an opt-in flag, default
OFF, from 2026-09-12 to 14; the write of a multi-target candidate was fail-closed until the
new modal was observed (observed 2026-09-14 with `--inspect`, proven by the canaries of
2026-09-15). The adversarial review of 2026-09-12 (four lenses) was fixed on 2026-09-14 —
region read of the console branch, R44 on consoles, identity apostrophes, the R19 stamp,
RANDOM with a console word, the shared throttle guard, the submit-gate streak, null target
ids — and Switch 2 became the `SWITCH2` family (CHANGELOG 2026-09-14). Until the per-target
modal was observed the console branch was READ-ONLY (`scripts/10_data_entry_auto.py` refused
`--consoles` without `--dry-run`, 2026-09-14); the guard was lifted on Romain's GO of
2026-09-15 and the branch became the default the same day (decision « 1 »).

- **2026-09-14 — EXECUTOR_RULES §4.12.3** (R45 (SWITCH2)) : Switch 2 (2026-09-14): the "console: Switch 2 has no AKS bucket (R45)" skip was retired —
Kinguin 12, K4G 12, G2A 1, Driffle 1 rows of the latest batches became enterable on their
`nintendo-switch-2` page.

- **2026-09-14 — EXECUTOR_RULES §4.12.4** (R45 (review fixes 2026-09-14 — counts)) : Review fixes of 2026-09-14 (measurements behind them): 150 Kinguin CA / AU console rows used
to pass `precheck_skip` and read an implicit GLOBAL; Gamivo 254/264 and Kinguin 37 real rows
read GLOBAL in the console branch before the grammar region slot was authoritative; two
independent throttle guards doubled the budget before `AksThrottled`; the AKS Switch page
"DreamWorks Spirit Luckys Big Adventure" vs the PC page "Lucky's" was a real false skip on
the MMOGA dry-run (apostrophes now folded); the bucket text "Xbox Game Code US" made R44 dead
on consoles ("Air Force United States Pacific Xbox One" would have been entered US-locked).

- **2026-09-15 — EXECUTOR_RULES §4.12.4 (6)** (R45 (item 6 — default ON)) : Decision « 1 » (2026-09-15) followed the two modal-v2 canaries and the MMOGA console dry-run
(run `20260915-081607-dryrun-consoles`, 663 offers → 174 console candidates: 89
single-target, 59 two-target, 26 three-target; 489 skips).

- **2026-09-14 / 2026-09-15 — EXECUTOR_RULES §4.12.4 (6)** (R45 (item 6 — history / Gamivo count)) : URL console scan in every mode (2026-09-12): on the latest Gamivo batch 569 rows previously
filed "no AKS product page found" (241), "forbidden region: COLOMBIA" (206), "skip category:
BUNDLE" (26), "forbidden region: ROW" (26) / CANADA (17), "extra words: ['KINGDOM']" (11) now
all skip `console` under `--no-consoles` (feed_status: category consoles).

- **2026-09-12 — EXECUTOR_RULES §4.12** (R45 (the Riders Republic leak)) : The leak (found 2026-09-12): the console guard (`precheck_skip`) read the TITLE only; Gamivo
(569 of its 572 console rows) and Eneba (URL segment) carry the platform in the URL alone.
Run `20260911-162100-auto-gamivo-s51-p28`: "Riders Republic Premium Edition United States"
(`gamivo.com/product/riders-republic-xbox-xbox-one-series-us-premium`) matched PUBLISHER /
GLOBAL(1) implicit / Premium(34) through the token-less-title → Direct Publisher path and was
created (`created: 1`, post-save "gone from feed") — an Xbox One/Series, US-locked key is
live on the PC page of Riders Republic (AKS product 50562) as a Direct-Publisher GLOBAL
Premium offer, to be corrected by hand on AKS (EXECUTOR_RULES §12, HANDOFF). Fix:
`console_marker_in_url` in `precheck_skip`, active in every mode.

- **2026-09-12 / 2026-09-15 — EXECUTOR_RULES §4.12** (R45 (volumes)) : Volumes (latest batch per merchant, 2026-09-12): MMOGA 388 console rows / 723 (One+Series
149, Series 89, Switch 63, One 35, PS5 10, non-game 85; EU tail 240); Kinguin 365 / 940
(One+Series 211, Series 79, PS5 16, PS4/PS5 15, Switch 13, Switch 2 12 — enterable since
2026-09-14; CA 83 / AU 77 forbidden — skipped in `precheck_skip` since 2026-09-14); Gamivo
572 / 762, URL-only (Series 333, One+Series 207; United Kingdom 258, Colombia 203); K4G 135 /
592; Driffle 112 / 464; G2A 42 / 806 (spells "X/S", One and Series as separate rows); Eneba
1 376 / 1 659 of which 704 generation-less; Instant Gaming: the platform is not in the feed.
The MMOGA console dry-run of 2026-09-15 (run `20260915-081607-dryrun-consoles`, 663 offers):
174 console candidates — 89 single-target, 59 two-target, 26 three-target — and 489 skips;
this is the measurement behind Romain's decision « 1 ». Kinguin is the next dry-run.

- **2026-09-12 → 2026-09-15 — EXECUTOR_RULES §6** (R45 (multi-target submit gate)) : Multi-target submit gate, 2026-09-12 → 14: more than one target was the fail-closed blocker
`multi_target_unsupported_until_modal_verified` (`ready: false`, "la saisie multi-cibles /
overwrite par cible attend l'observation du nouveau modal (--inspect) — R45") because Romain's
new feed tool overwrote region / edition PER target page but its controls had not been
observed; the per-target fill was to be added ONLY after an `--inspect` pass had shown the
per-target controls (`modal_inspection.json`), never before. `InspectSubmitter` still opened
and dumped the modal of a gated entry — exactly the observation the gate waited for (done
2026-09-14, run `20260914-inspect-consoles`); the canaries of 2026-09-15 (Legend of Mana
Switch, one target; Diablo 2 Resurrected Xbox One + Series, two targets via
`[data-add-target]`) proved the write, and the gate now applies to the `targets_v1` shape
only.

- **2026-09-14 / 2026-09-15 — EXECUTOR_RULES §12** (R45 (§12 open item — modal semantics)) : Open item of 2026-09-12 (per-target overwrite semantics of the new modal: one Create with N
targets each carrying its own region / edition, or N Creates from one row? which controls?)
— answered by the `--inspect` pass of 2026-09-14 and the canaries of 2026-09-15.

### MMOGA

- **2026-09-11 — EXECUTOR_RULES §4.4** (MMOGA (second region grammar)) : Before the second MMOGA region grammar (2026-09-11), 9 of the 1 060 MMOGA offers created
2026-09-10/11 carried an EU tail and were entered GLOBAL (to be corrected by hand on AKS;
listed in CHANGELOG 2026-09-11).

### R32e

- **2026-09-14 — EXECUTOR_RULES §4.4** (R32e — Kinguin « valid until » / K4G Altergift) : Kinguin « (valid until …) » / K4G Altergift — history behind the 2026-09-14 rulings: before,
79 Kinguin rows / batch were skipped "extra words: ['VALID', 'UNTIL', …]"; only the "(valid
until <Month>[,] <Year>)" spelling exists in the corpus (89 / 89 rows) and 158 / 158 corpus
rows (duplicates included) carry it at the END of the title — hence the end-anchored strip
of the same-evening review fix. K4G: before, an explicit "skip category: ALTERGIFT" precheck
(removed); 217 / 218 Altergift slugs carry `-altergift-` / `-alter-gift-` — the one row that
disagreed, offer 101030313 "Trine 5: A Clockwork Conspiracy Steam Altergift" on
`…-instant-cd-key-48V2PFDZ`, is the "K4G delivery conflict" precheck skip. Replay on the
2026-09-12 batches: CHANGELOG 2026-09-14 (« Décisions de Romain (14/09, soir) » and its
« Correctifs de revue »).

### R46

- **2026-09-11 / 2026-09-12 — EXECUTOR_RULES §4.4** (R46) : On 2026-09-11 six Gamivo "… United States" keys were entered PUBLISHER GLOBAL(1) implicit —
the R27 default on a page listing Direct Publisher (list in `MERCHANTS.md`, to correct by
hand). R46 (2026-09-12) added the Gamivo grammar hooks.

- **2026-09-12 — EXECUTOR_RULES §4.4 (KINGDOM guard)** (R46) : The trailing-KINGDOM rule of the different-product guard removed 14 false `extra words:
['KINGDOM']` skips on the 2026-09-12 Gamivo batch.

### MA7

- **2026-09-01 — EXECUTOR_RULES §4.4** (MA7 (retired)) : MA7 retirement, Romain audit 2026-09-01: an earlier version of the language-code rule armed on
the FIRST common/noise token, so a leading article THE/A wrongly neutralized the code
("The En Garde" read as a language variant of "Garde"). Fixed the same day: position after the
FULL game name is the signal.

### P2-6

- **2026-09-02 — EXECUTOR_RULES §4.4** (P2-6) : Audit 2026-09-02 (P2-6): `precheck_skip` scanned `FORBIDDEN_REGIONS` on the TITLE only; a
forbidden region encoded solely in the merchant URL (Gamivo `…-steam-key-brazil`, clean
title) escaped and fell to `detect_region`, which knows only sellable buckets
(eu/global/us/uk) → implicit GLOBAL = a region-locked key entered worldwide (Gamivo's empty
config gave no R33 page-region rescue).

### P2-8

- **2026-09-02 — EXECUTOR_RULES §4.4** (P2-8 / R32c) : Audit 2026-09-02 (P2-8 / R32c): the old `_region_id(platform, key) or _region_id(platform,
"gmg_gift")` silently substituted the GLOBAL id when the per-base bucket was missing, while
the LABEL still read "GMG GIFT US"/"EU" — the label contradicted the id, the region was
silently widened, and a US-restricted key became enterable worldwide (and the mislabel
defeated the human validation gate).

### R20

- **2026-07-08 / 2026-07-15 — EXECUTOR_RULES §4.4** (R20 / R26 / R27) : R20 (2026-07-08, Su-27 escape): "Su-27 for DCS World Key GLOBAL" carried no platform token,
was defaulted STEAM and entered Steam GLOBAL(2) when the product is publisher-direct (Eagle
Dynamics); Romain had to fix the DB by hand. R26 (2026-07-15, DCS P-51D Mustang / A-10C
Warthog escape): both DCS pages say "official platforms: Steam." with no `Direct Publisher`
entry, yet Kinguin's own title omission was the real signal — R26 made any token-less title
with *some* page platform signal default to PUBLISHER. R27 (same day, Gameboost escape): R26
was too broad — hours later Gameboost proved the opposite failure mode (genuinely-Steam,
token-less offers defaulted to Publisher, because Gameboost's own truth lives on its merchant
page, unfetchable — Cloudflare blocks it). DCS and Gameboost are the identical page-signal
shape with opposite ground truth, hence R27's Direct-Publisher-only auto-resolve; the ids
(Publisher 1 / EU 12 / US 13 / UK 266) were read from the live session catalogs of
07-07/07-08, identical. DCS itself reverted to skip; Su-27 (page: Steam, Direct Publisher —
a genuine positive signal) stayed PUBLISHER.

- **2026-07-08 — EXECUTOR_RULES §4.4** (R20 (page vocabulary sweep)) : Sweep 2026-07-08 over every offer ever created/attempted (48 offers, 27 AKS pages, stubs
included): Su-27 was the only platform damage.

### R29

- **2026-07-16 — EXECUTOR_RULES §4.4** (R29) : R29 (2026-07-16): "Apothecarium: The Renaissance of Evil - Premium Edition" carried no
platform word anywhere in its title — it fell into R27's token-less branch and correctly
SKIPped there — but it is genuinely Steam, and Eneba says so in the URL prefix. The same case
also exposed an R25 interaction: once correctly resolved to Steam GLOBAL(2)/Premium(34), it
turned out to already be a duplicate on AKS (Eneba merchant id 272) — the wrong Publisher
classification had been hiding it from the (since-retired) duplicate check too.

### R19

- **2026-07-08 — EXECUTOR_RULES §4.5** (R19) : R19 (2026-07-08, DCS A-10C Warthog escape): A-10C (empty editions map) was entered
Standard(1) and Romain had to fix the DB by hand, while sibling DCS P-51D Mustang (populated
map, DLC bucket) was correctly entered DLC(16) by R18 in the same run. Measured 2026-07-08:
23/25 sampled candidate pages had a populated map — even mono-edition ones show
`1:Standard`; the two empty ones split one hidden DLC / one legit standalone, so emptiness
decides nothing.

### R23

- **2026-07-13 — EXECUTOR_RULES §4.5** (R23) : R23 (2026-07-13, Valve Complete Pack escape): the identity collapse had already mis-submitted
an earlier offer of this exact product that morning; Romain deleted the bad AKS entry by
hand.

### R40

- **2026-09-02 — EXECUTOR_RULES §4.5** (R40) : R40 (audit 2026-09-02, P1-1/P1-2): before the rule, `detect_edition`'s generic hardcoded id
was emitted with NO proof the resolved page sells that tier — a wrong-edition write surviving
human validation. Three adversarial-review rounds then closed a suffixed-label over-skip, a
substring wrong-tier adoption, an id-coincidence hole, and the "Digital Deluxe" false-skip.

### AKS/Staff UA

- **2026-09-11 — EXECUTOR_RULES §4.6** (AKS/Staff UA (§4.6)) : IP ban of 2026-09-11: the pipeline always probed with `AKS/Staff`, but ~60 ad-hoc read-only
diagnostics sent with the browser UA on 2026-09-11 got the VPS IP dropped at TCP level by the
AKS anti-bot for hours — sweeps, browser and console included. `http_get` then took the staff
UA by default towards allkeyshop.com.

### R30

- **2026-09-09 / 2026-09-10 — EXECUTOR_RULES §4.7** (R30 (search timeout)) : `AKS_SEARCH_TIMEOUT_S` went 20 → 8 s (2026-09-10). Measured 2026-09-09 on the new VPS: AKS
search answered in 22-28 s with an EMPTY 200 body — 59 offers × 20 s on one Kinguin page.

- **2026-07-16 — EXECUTOR_RULES §4.7** (R30) : R30 verified live (2026-07-16): Eneba "Worms Collection 2014 Steam Key (PC) EUROPE" (no
guessable AKS page) search-resolved to an unrelated page ("Assassin's Creed Black Flag
Resynced") — R01 correctly SKIPped it ("missing AKS words: ASSASSIN'S, CREED, BLACK, FLAG,
RESYNCED"). Real-world yield on the same Eneba skip batch was low (most token-less/unusual
titles still correctly resolve to nothing) but the mechanism is safe.

### MA1

- **2026-07-17 — EXECUTOR_RULES §4.7** (MA1) : MA1 (audit 2026-07-17): the docstring always promised the immediate fail-closed on a
transient answer on a guessed slug; the code only did it from that audit on — before, the
failure was collected and a less-specific tier's 200 could win.

### R25

- **2026-07-15 / 2026-09-08 — EXECUTOR_RULES §4.7** (R25 (retired)) : R25 was added 2026-07-15 (Kinguin/Darkwood escape): the resolve pass extracted the page's own
`"prices":[…]` list and a candidate whose merchant already matched the resolved region AND
edition was SKIPPED, to stop a STALE matched batch being re-submitted after the offer had
since been entered. Retired 2026-09-08: (1) it matched by `merchantName`, but the page price
can come from another channel / an AKS auto-sync — the page merchant id ≠ the operator's feed
`store_id` (Phantom Blade Zero 2026-09-08: page `Kinguin` id 47 vs feed store 58) — so it
false-skipped genuinely new offers; (2) staleness is now handled by the stable pending feed
(offers are kept, ids no longer rotate) + submit-time prove-gone.

### R32

- **2026-09-14 — EXECUTOR_RULES §4.10** (R32 / R45 (merchant files — measurement)) : Measurement of the 2026-09-14 move of merchant grammar into the merchant files (read-only,
on the last saved batches of 2026-09-12; GameSeal: the July 2026 sweep): console rows
classified per merchant and per reason are IDENTICAL before / after (2 990 console rows, 0
oddity — MMOGA 388, Kinguin 365, Gamivo 572, K4G 135, Driffle 112, G2A 42, Eneba 1 376); 5 /
2 990 full-signal diffs, all region-slot corrections on non-game or Eneba rows (no entry
changes). PC rows whose precheck / region / first slug differ from the committed code:
Kinguin 66, K4G 228, Driffle 8, G2A 3, GameSeal 30, Gamivo / MMOGA / Eneba 0 — every one a
skip made explicit / earlier or a narrower region, 0 recorded candidate changes class.
Per-merchant table: CHANGELOG 2026-09-14. Before R32 (2026-08-11), merchant-specific handling
was scattered (Kinguin's domain rule, Difmark's offer-page resolver + maps, Eneba's URL
prefixes; Gamivo's `-en-` language lock was there too until MA7 was retired 2026-09-01).

- **2026-08-11 — EXECUTOR_RULES §4.10** (R32 (Instant Gaming trigger)) : R32 trigger (2026-08-11): a whole Instant Gaming safe-auto sweep entered every offer as
PUBLISHER although they were STEAM (R27 defaulted the token-less titles).

### R33

- **2026-08-13 — EXECUTOR_RULES §4.10** (R33) : R33 (2026-08-13): a whole Instant Gaming sweep had entered 32/54 region-locked offers as
GLOBAL before the region was read from the IG page `<title>` / `og:title` suffix.

### S — submitter (EXECUTOR_RULES §6 : identité de ligne, index, modale, gate de validité, compteurs)

- **2026-07-07 / 2026-07-08 — EXECUTOR_RULES §6** (S — submitter row identity (§6 step 1)) : Row identity in the submitter: 2026-07-07 G2A — an offer drifted from page 2 to page 1 after
8 creations → ROW_NOT_FOUND (hence the index refreshed by every verify scan). K4G 2026-07-08:
0/212 ids survived 74 min; G2A: 0/716 in 24 h (hence ids are import-batch-scoped). Query
params drift across G2A re-imports (`uuid=` changed on 26/716 rows in 24 h while the path
held 716/716; unique in-feed for both merchants) — hence the merchant URL PATH as the stable
identity.

- **2026-09-01 — EXECUTOR_RULES §6** (S — index-scan miss (§6 step 1)) : Index-scan miss (hardened 2026-09-01): in a same-product multi-edition batch the bulk index
build dropped all-but-one (Whiteout Survival's 7 Frost-Stars editions entered 1/7 per run
while the other 6 sat in the feed). The Green Light Steam (2026-09-01): the "reflowing too
fast to pin" skip lost a stably-pending offer over two runs because the fresh row was pinned
by the scanned id instead of the stable URL.

- **2026-09-01 / 2026-09-10 — EXECUTOR_RULES §6** (S — modal context (§6 step 3)) : Modal context poll: hardened 2026-09-01 — an immediate read skipped a genuinely-open Kinguin
modal as "modal context missing (#TB_ajaxContent)" (Simpler Times); widened 2026-09-10 —
9/24 MMOGA offers were refused at the old 7 s feed-style budget. Lost-click defense
(2026-09-10, MMOGA): 3 rows were refused across two sweeps ("OPENED", no content ever) while
a read-only re-open served the form at 0.0 s — the click had fired before the ThickBox
handler was bound.

- **2026-07-08 — EXECUTOR_RULES §6** (S — validity gate (§6 step 7, audit P1b)) : Audit P1b (2026-07-08): the old code continued to the Create click when the validity probe
returned `ok:false` — an explicit degraded mode, removed.

- **2026-07-08 — EXECUTOR_RULES §6** (S — write counters (§6)) : Audit P2 (2026-07-08): the old single `writes` counter of `submit_plan.json` conflated
attempts and creations and overstated creations — split into `write_attempts` / `created`.

### P2-1

- **2026-09-02 — EXECUTOR_RULES §6 step 8** (P2-1 / A2) : Audit 2026-09-02 (P2-1 / A2): the old `native` (`button.click()`) and `dispatch` (MouseEvent)
click modes routed to the UNGUARDED `fill_and_create` — no SC3 read-back, no
`VALUE_DRIFTED_BEFORE_CLICK`, no `form_validity()` gate, no `NO_OPTION` guard — and produced
`isTrusted:false`. The degraded write path was removed from the write `Submitter`.

### R24

- **2026-07-17 — EXECUTOR_RULES §6** (R24 / FC5 (mode binding)) : Until FC5 (audit 2026-07-17) the mode was only *declared* on `05_submit` and could not be
cross-checked against the run ("open invariant, not yet enforceable"); FC5 made `03_match`
stamp it into `match_meta.json` and both writers refuse a wider submit mode.

### Post-save proof retry

- **2026-09-10 — EXECUTOR_RULES §7** (Post-save proof retry (§7)) : Post-save proof retry (2026-09-10): twice in ~100 MMOGA creations the AKS admin page took
longer than the 45 s command timeout to answer the proof navigation right after a successful
Create (signal "Offer created …"), so a created offer was marked UNKNOWN and the whole sweep
halted — hence the one bounded retry on `CdpTimeoutError`.

### Difmark

- **2026-07-17 — EXECUTOR_RULES §11** (Difmark (page-verified platform + region)) : Difmark batch 1 (2026-07-17, pages 1-10, 658 offers) showed the dominant failure mode:
501/652 skips (77%) were R27 ("no platform in title and AKS page does not confirm Direct
Publisher"). Live example: Afterlife VR (title has no platform word) used to default to
PUBLISHER via R27's AKS-page inference; the merchant's own page confirms `marketplace:
Steam` — entered as STEAM instead, the exact kind of silent mis-platforming R20/R26/R27 were
written to catch for other merchants (DCS/Su-27, Gameboost).

- **2026-07-17 / 2026-07-18 — EXECUTOR_RULES §11** (Difmark (account offers, rounds 1-3)) : Difmark account-vs-key escape, two rounds (Romain 2026-07-17, both caught from the normalized
report). Round 1: "je vois que pour Difmark, au lieu de Steam account, tu as lancé des Steam
dans ton rapport normalisé." — the pre-existing `STEAM ACCOUNT` categorical skip never fires
for Difmark (titles like "Rogue Loops Standard Edition", boilerplate "steam-account" URL
segment); the distinction only shows in the merchant's per-offer `offer_name` (e.g. `"Sekiro:
Shadows Die Twice GOTY"` for a genuine key), confirmed live on real batch-1 offers. Round 2,
immediate correction: "je voulais que tu renseignes la région Steam Account quand tu vois
Steam Account. Pourquoi... tu les mets en Steam normal, alors que c'est des Steam Account
aussi?" — the round-1 fix had treated an "ACCOUNT" `offer_name` as a skip; the Account
buckets were confirmed via a cached live dropdown snapshot
(`runs/20260708-081329-k4g/session_catalog.json`, `probe_select_options` on `offer[region]`,
867 rendered options — a 9-day-old snapshot, hence the re-verify note). Round 3 (2026-07-18):
rounds 1-2 got the region right (Account bucket 412/…) but still matched the game's
`…-cd-key-…` page; every existing listing on the account page 187974, G2A included, uses
region 412.

- **2026-07-17 — EXECUTOR_RULES §11** (Difmark (operating cadence)) : Difmark cadence (2026-07-17): the feed had 382 pages; confirmed live that day, an
`approved.json` built from one page fetch was already unusable by submit time, hitting first
`catalog_unavailable`/`no_openable_offer` (feed mid-reimport), then `feed_unreadable`
(coverage unproven at the default 40-page cap), then, once repopulated, 10 consecutive
failures because every approved id had rotated out from under it. The one-page cadence
superseded the earlier "batches of ~10 pages" guidance from the same day (itself a
correction on "don't sweep all 382 pages at once").

- **2026-07-20 — EXECUTOR_RULES §11** (Difmark (--max-pages auto-default)) : `--max-pages` auto-default (2026-07-20): the old 40-page floor always aborted on Difmark's
~357-page feed unless the operator raised it by hand — the manual-ceiling footgun the
auto-default removed.

### P1.6

- **2026-07-29 — EXECUTOR_RULES §13** (P1.6 (sort ledger)) : Revue P1.6 (2026-07-29) : la fenêtre différée par-store transformait un reflow bénin en
`identity_blocked` permanent → une offre légitime perdue à jamais — d'où la règle « seul le
TERMINAL est skippé » du ledger de tri.

### P1-4

- **2026-09-02 — EXECUTOR_RULES §13** (P1-4) : Audit 2026-09-02 (P1-4) : `_reverify_row` cherchait la ligne par id et ne relocalisait par
URL que si l'id avait disparu ; un id présent mais réattribué à un autre produit filait donc
direct en `identity_mismatch` TERMINAL sans jamais chercher l'URL stable ailleurs sur la page
→ une offre encore présente (déplacée vers un nouvel id, souvent sur la MÊME page) skippée à
jamais.

### RV2

- **2026-07-31 — EXECUTOR_RULES §13** (RV2 (target verify GLOBAL)) : RV2 scan cible GLOBAL (fix 2026-07-31) : le scoping par store donnait des faux « pas sur la
cible » qui sous-comptaient les moves ET gonflaient les échecs → breaker guard / FC3 à tort
(Gift cards 2026-07-31).

### R37

- **2026-08-17 — EXECUTOR_RULES §14** (R37) : R37 (2026-08-17) : sur un feed profond (Kinguin ~104 pages) la vérif RV2 unitaire coûtait
~6 min/move et la charge CDP longue faisait échouer une navigation (`Page.navigate` → halt) —
2 sweeps de suite calés ainsi. Revue adversariale (4 dimensions) : 2 défauts corrigés — la
garde R24 « widening » rejetait le `--limit 2` batché (exemptée pour `--batch`), et un
`move_plan.json` stale double-comptait sur abort précoce (unlink avant chaque invocation).

### P2-2

- **2026-09-02 — EXECUTOR_RULES §14** (P2-2) : Audit 2026-09-02 (P2-2) : `scripts/10` ne validait que `store_id.isdigit()` → `--targets
'Difmark:167'` (parké, non-vetté) pouvait balayer et créer en contournant le gate allowlist
que seul le handler HTTP re-vérifiait.

### P2-3

- **2026-09-02 — EXECUTOR_RULES §14** (P2-3) : Audit 2026-09-02 (P2-3) : `scripts/12` ne faisait que skipper les jeux non-résolus pour
soumettre le reste (couverture partielle expédiée sans le 409 de la console).

### P2-4

- **2026-09-02 — EXECUTOR_RULES §14** (P2-4) : Audit 2026-09-02 (P2-4) : l'ancien match sous-chaîne de `suggest_target_list` sur la raison
entière envoyait une offre « extra words: ['account'] » en MOVE→liste 30 sous
`--move-execute` sur un simple mot de titre.

