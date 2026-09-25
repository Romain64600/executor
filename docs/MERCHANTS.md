# Marchands — configuration et règles par marchand

> **Règle de Romain (répétée depuis le 2026-08-11, ultimatum du 2026-09-14) :** « pour la
> détection région / édition / plateforme, tu as un fichier de config par marchand. Et si tu
> ne l'as pas, tu dois l'avoir. » — **chaque marchand a son fichier ; la grammaire marchande
> ne vit jamais dans un module générique.** Tout marchand de la liste blanche safe-auto
> (`src/admin/auto_merchants.py`) a son `src/merchants/<marchand>.py` qui expose un
> `MerchantConfig` DÉCLARANT sa grammaire (plateforme / région / édition, PC ET console) et
> ses hooks ; les modules génériques (`src/matcher.py`, `src/console_keys.py`) ne gardent que
> le vocabulaire partagé et le pipeline. Le classifieur console R45 n'embarque plus aucune
> grammaire MMOGA / Gamivo / Eneba (segments de catégorie, runs d'URL, segment de magasin en
> tête, contrôles d'hôte) : tout cela est descendu dans les fichiers marchands le 2026-09-14.

Un seul endroit pour répondre à « comment l'executor lit ce marchand ? ». Pour chaque
marchand de la liste blanche safe-auto : identifiants, **fichier**, grammaire PC (sources
de la plateforme, de la région, de l'édition), grammaire console (familles, PC/Windows, slot
région), hooks implémentés (`src/merchant_config.py`, règles `[R32]` / `[R45]`), règles
spécifiques avec leur numéro dans `EXECUTOR_RULES.md`, statut live (éprouvé en data-entry
auto ou non) et profil du feed résiduel. L'état courant du feed (dernier passage, offres
ajoutées, ce qui reste) est dans `docs/feeds/<Marchand>.md`, régénéré par
`scripts/14_feed_status.py`.

## Le contrat de config marchand (`MerchantConfig`)

Tout comportement générique du matcher peut être ajouté, surchargé ou modifié par le
fichier `src/merchants/<marchand>.py` (Romain, 2026-08-28 : « un fichier config par
marchand »). La liaison nom du marchand → module (`merchant_config()`) vit dans le
**registre `src/merchants/registry.py`** (2026-09-14), importé à la fois par `src/matcher.py`
(qui continue d'exposer `merchant_config`) et par `src/console_keys.py` — sans import
circulaire (`python3 -c "import src.matcher, src.console_keys, src.merchants.registry"`
doit passer). Un fichier marchand n'importe jamais `src.matcher` ; ses hooks sont des
fonctions pures de la ligne de feed (titre, URL), sans réseau.

Champs disponibles :

| Champ | Rôle | Défaut |
|---|---|---|
| `domain` | l'URL de l'offre doit être sur ce domaine, sinon skip fail-closed | aucun contrôle |
| `url_ignore_substrings` | segments d'URL « bruit » retirés avant tout signal dérivé de l'URL (Difmark) | — |
| `url_platform_prefixes` | segment de tête de l'URL → plateforme (`steam` → STEAM…) | — |
| `title_is_platform_source` | la plateforme se lit dans le titre (True) ou seulement dans l'URL (G2A) | True |
| `url_platform_scan` | scanner le slug de l'URL pour la plateforme | False |
| `offer_page_resolver` | lire la page marchande de l'offre pour plateforme + région (Instant Gaming, Difmark) | — |
| `offer_page_readable` | False = la page marchande n'est pas lisible en HTTP (G2A 403) → fail-closed | True |
| `precheck(name, url)` | skip catégorique propre au marchand, avant les scans génériques `[R32e]` | — |
| `title_region(name)` | région déclarée par la grammaire du titre, autoritaire `[R32e]` | — |
| `resolve_name(name)` | texte remis à la résolution AKS (slug), les contrôles d'identité gardent le titre brut `[R32e]` | — |
| `url_platform(url)` | plateforme déclarée par la grammaire d'URL du marchand (Gamivo : run `-pc-steam-` entre le slug et le code région), consultée en premier par `explicit_platform_from_url` `[R46]` | — |
| `guard_name(name)` | **`[R32e]` (2026-09-14)** — le titre lu par les gardes d'identité (R01 mots AKS manquants, R16 mots en trop, R01b qualificatif dangereux) et par `detect_edition` pour une ligne PC : le titre brut par défaut (aucun marchand sans le hook ne change) ; un marchand dont la grammaire ajoute une note qui n'est PAS un mot de produit la retire ici — et elle seule (Kinguin « (valid until <Month> <Year>) » en FIN de titre seulement — correctif de revue 14/09 —, le mot de livraison « Altergift » chez K4G et Kinguin — décisions de Romain du 14/09 : « Kinguin valid until juin 2027 on rentre », « Steam Altergift = Steam Gift on rentre »). Le hook ne blanchit jamais un titre : les mots qu'il laisse sont toujours comparés au nom AKS, une réponse vide → titre brut | titre brut |
| `gift_delivery(name, url)` | **`[R32e]` (2026-09-14)** — le verdict « livraison gift » propre au marchand, superposé par `detect_region` comme bucket GIFT de la plateforme (Steam 25 / 259 / 2577 / 2572, Battle.net 570 / 567 / 568, Ubisoft 501 / 504 / 505 — les compartiments US / UK ont été mappés le 16/09, `[R50]` ; une base qu'une plateforme n'a vraiment pas garde le skip fail-closed « no region id ») : True / False l'emporte, None → lecture générique (segment d'URL `gift`, « GIFT » dans le titre). K4G / Kinguin « … Steam Altergift » dont le slug est d'accord → True (Romain 14/09 : « on rentre sous gift tous les altergifts ») ; le hook lit ses DEUX arguments : un conflit titre / URL (titre Altergift, slug `-cd-key`) ou un Altergift hors Steam n'est jamais un verdict — c'est le skip fail-closed du `precheck` marchand (correctifs de revue 14/09) | lecture générique |
| `console_url_families(url)` | **console `[R45]` (2026-09-14)** — les familles que l'URL déclare, dans l'ordre (sous-ensemble de XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2), OU une chaîne de skip (`"console: Xbox 360 (R45)"`, `"console: PC-only Xbox Live key (R45)"`, `"console: <MARKER> — not a game (R45)"`), OU `None` (l'URL ne dit rien) ; consulté par le classifieur générique SEULEMENT quand le titre ne déclare aucune famille | — |
| `console_pc_declared(name, url)` | **console `[R45]` (2026-09-14)** — True quand le marchand déclare PC / Windows à côté de la plateforme console (Gamivo : runs `-pc` / `-windows` ; Eneba : run `-windows-`) ; la lecture générique des phrases de titre (`/ Windows`, `PC/XBOX …`) reste générique | — |
| `console_region_slot(name)` | **console `[R45]` (2026-09-14)** — le TEXTE de région que le marchand écrit à côté de la phrase plateforme, tel quel (`"US"`, `"CA"`, `"Europe"`, `"United Kingdom"`, `"Hong Kong"`, `"EUROPE"`) ; la correspondance texte → base (uk / us / eu / global) ou label interdit reste générique dans `console_keys` (vocabulaire partagé) ; hook absent → le classifieur retombe sur ses lectures partagées de queue / crochets | — |
| `console_noise` | **console `[R45]` (2026-09-14)** — `tuple[str, ...]` de phrases marchandes à retirer de `resolve_name` EN PLUS des marqueurs partagés de magasin / livraison (`"Download Code"` MMOGA, `"Digital Key"` / `"Digital Code"` Driffle, `"CD Key"` Kinguin) ; un `re.Pattern` compilé est accepté pour les formes qu'un littéral ne sait pas écrire — la note `(valid until <Month> <Year>)` de Kinguin (`kinguin.VALID_UNTIL_RE`, un bruit depuis la décision de Romain du 14/09 : « Kinguin valid until juin 2027 on rentre ») | `()` |

**Consoles `[R45]` — ce qui est partagé et ce qui est marchand (2026-09-14).** Le
classifieur `src/console_keys.py` (`classify_console`, `console_marker_in_url`,
`console_page_identity`) garde le **vocabulaire partagé** : les familles et leurs pages /
buckets, la grammaire de TITRE (phrases entières `Xbox One / Series X|S`, `PS4 / PS5`,
`Nintendo Switch 2`, `X|S` ≡ `X/S` ≡ `XS`, « Series » nu normalisé, run de tête = nom du
jeu, suffixe « Nintendo Switch 2 Edition » = nom), les marqueurs partagés de magasin /
livraison (XBOX LIVE, PSN, NINTENDO ESHOP, MICROSOFT STORE, CD KEY, KEY, GIFT), les
marqueurs non-jeu de titre (GAME PASS, cartes, abonnements, ACCOUNT mot entier), la table
texte de région → base / label interdit, la lecture partagée des runs d'URL à tirets
(`xbox-one`, `xbox-series-x-s`, `ps4-ps5`, `nintendo-switch(-2)`…) et `console_marker_in_url`.
Tout ce qui est propre à un marchand — segments de catégorie MMOGA, runs Gamivo, segment de
magasin en tête et runs Eneba, slot région de chaque grammaire, phrases de bruit — est
DÉCLARÉ par le fichier marchand via les quatre hooks consoles ci-dessus ; le classifieur ne
teste plus ni l'hôte (`mmoga.com`, `gamivo.com`, `eneba.com`) ni le nom du marchand, il
demande la config au registre. Ordre : grammaire de titre (partagée) → si aucune famille
dans le titre, `console_url_families(url)` (tuple → familles ; chaîne → skip ; `None` →
l'URL ne dit rien → « console: no declared generation (R45) » si le titre n'en déclarait pas
non plus ; hook absent → lecture partagée des runs) → `console_pc_declared` en plus de la
phrase générique → `console_region_slot` (texte) → correspondance partagée → base / label /
mots ; `console_noise` retiré de `resolve_name` avec les marqueurs partagés. La branche
console est le **défaut depuis le 2026-09-15** (`--no-consoles` = PC seul) et un candidat
multi-cibles est écrit entier sur le modal v2 (plafond 3 cibles) — règles dans
`EXECUTOR_RULES.md` §4.10, §4.12 et §6 « Modal v2 ».

Mesure du 14/09 (lecture seule, sur les derniers lots sauvegardés du 12/09 ; GameSeal :
sweep du 15/07/2026) — **classifieur consoles** : comptages par marchand et par motif
IDENTIQUES avant / après le déplacement des grammaires (2 990 lignes consoles, 0 anomalie :
MMOGA 388, Kinguin 365, Gamivo 572, K4G 135, Driffle 112, G2A 42, Eneba 1 376 — `diff` vide
entre la mesure de référence prise avant la refonte et la mesure post-intégration) ; sur les
signaux complets (familles, PC, skip, `resolve_name`, slot région) 5 lignes / 2 990
diffèrent : 2 corrections Eneba par `console_region_slot` (« Dying Light Essentials Edition
(Without DE) XBOX LIVE Key EUROPE » lisait DE → GERMANY interdit, désormais base eu ; « Truck
Simulator Cargo Driver 2025 - USA (Windows/Xbox Series X|S) XBOX LIVE Key EUROPE » lisait
USA + EUROPE → « not mapped », désormais eu) et 3 slots K4G / Driffle plus larges que le
vocabulaire partagé (Luxembourg, Latvia, Lithuania) sur des lignes déjà non-jeu — aucune
saisie ne change. **Lignes PC** (précheck + plateforme + région + 1er slug, code du 14/09
vs code committé b6c96be) : Kinguin 66 lignes (34 prechecks explicites, 2 régions, 30 slugs),
K4G 228 (216 « ALTERGIFT », 12 slugs), Driffle 8, G2A 3, GameSeal 30, Gamivo / MMOGA / Eneba
0 ; **0 candidat enregistré ne change de classe**. Détail par marchand et par motif :
CHANGELOG 2026-09-14 « Mesure ».

Ce qui reste générique pour tous : pré-skips catégoriques (consoles, régions interdites,
prepaids, monnaies, bundles, skins, passes in-game, collections de DLC), résolution de la
page AKS par devinette de slug puis recherche AKS (R30, disjoncteur), gardes d'identité
R01 / R16 / R01b, DLC `[R43]`, éditions (R18, R39, R23), régions (§4.4, R44), plateformes
(R20), logiciels (R31), clés consoles `[R45]` (classifieur partagé, pages consoles, cibles
multiples — par défaut, `--no-consoles` pour un run PC seul), preuve de succès = disparition
du feed.

## Statut au 2026-09-15

| Marchand | Store id feed | Fichier (`src/merchants/`) | Hooks déclarés (14/09) | Éprouvé en safe-auto | Feed (pages) |
|---|---|---|---|---|---|
| Kinguin | 58 | `kinguin.py` (**nouveau**, `domain` sorti du registre) | PC : `precheck`, `title_region`, `resolve_name`, `guard_name`, `gift_delivery` (note « valid until » saisie — en fin de titre —, « PC Steam Altergift » = Steam Gift, 14/09 soir) — pas de `url_platform` (R32b) ; console : `console_url_families`, `console_region_slot`, `console_noise=("CD Key", VALID_UNTIL_RE)` | oui (142 pages d'historique + nuit du 11/09) | 67 |
| Gamivo | 51 | `gamivo.py` (4 hooks PC `[R46]` depuis le 12/09) | `console_url_families`, `console_pc_declared`, `console_region_slot` | oui — 6 saisies fausses du 11/09 à corriger | 56 |
| G2A | 38 | `g2a.py` | PC : `precheck`, `title_region` (queue ` - <RÉGION>`) + flags R32b ; console : `console_url_families`, `console_region_slot` | oui | 37 |
| MMOGA | 12 (page AKS : marchand 40) | `mmoga.py` | `console_url_families`, `console_region_slot`, `console_noise` | oui (1 265 créées les 10-12/09 ; premier sweep console réel le 15/09) | 8-10 |
| K4G | 92 | `k4g.py` (**nouveau**) | PC : `precheck`, `title_region`, `resolve_name`, `guard_name`, `gift_delivery` (Altergift = Steam Gift quand le slug est d'accord, 14/09 soir) ; console : `console_url_families`, `console_region_slot` | oui | 7 |
| Driffle | 127 | `driffle.py` (**nouveau**) | PC : `precheck`, `title_region` (1re parenthèse) ; console : `console_url_families`, `console_region_slot`, `console_noise` | oui | 6 |
| Instant Gaming | 28 | `instant_gaming.py` | PC : `offer_page_resolver` ; console : `console_url_families` → toujours None (déclaré : l'URL ne dit rien ; une plateforme console lue sur la page IG → plateforme None → skip R32) | oui | 4-5 |
| Eneba | 19 | `eneba.py` | `console_url_families`, `console_pc_declared`, `console_region_slot` | **non — dry-run du 12/09 fait (32 candidats, 90 % consoles), sweep réel sur go** | ≥ 30 |
| Allyouplay | 17 | `allyouplay.py` (**nouveau**, identité seule) | `domain="allyouplay.com"` (à confirmer au 1er dry-run) — aucun hook de grammaire (aucune donnée) | **non, dry-run d'abord** | ? |
| GameSeal | 126 | `gameseal.py` | `domain` ; PC : `precheck`, `title_region` (queue ` - <RÉGION>`), `resolve_name` (queue pelée, 20/09) ; console : `console_url_families`, `console_region_slot` | oui (1er balayage 19/09) | 1 090 écrites, 1 089 justes (audit du 20/09) |
| CJS-CDKeys | 30 | `cjs.py` (**nouveau**, identité seule) | `domain="cjs-cdkeys.com"` (à confirmer au 1er dry-run) — aucun hook de grammaire (aucune donnée) | **non, dry-run d'abord** | ? |
| Difmark | 167 | `difmark.py` | `console_url_families` (comptes) | parqué (hors liste blanche) | — |
| Wyrel | 162 | `wyrel.py` (16/09) | PC : `precheck` (`[R53a]` gabarit, `[R53b]` non-jeu à 3 signaux, `[R53c]` édition, `[R53d]` accord titre/URL, `[R53e]` fente plateforme inconnue), `title_region`, `resolve_name` ; console : `console_region_slot`, `console_noise` | **oui, allowlisté le 24/09** (groupe B) — 1re saisie : 15 / 15 créées le 17/09 | 60 |
| GameBoost | 157 | `gameboost.py` (**nouveau 15/09**) | PC : `precheck` (non-jeux + `[R47]` région obligatoire), `title_region`, `resolve_name` ; console : `console_region_slot` | **oui, allowlisté le 16/09** — 1er matching : 207 candidats / 992 lignes | 13 |
| GamersOutlet | 31 | `gamersoutlet.py` (**nouveau 15/09**) | PC : `precheck` (slot obligatoire + vocabulaire boutique fermé), `title_region`, `resolve_name`, `url_platform` | **oui, allowlisté le 16/09** — 1re saisie : 2 / 2 créées | 1 |
| Gamerall | 13 | `gamerall.py` (**nouveau 18/09**) | `precheck` (plateforme du titre obligatoire), `resolve_name`, `title_region`, `url_platform`/`url_region`, et surtout `offer_page_resolver` — région lue dans l'ordre **titre → URL → page**, la page n'étant ouverte que pour les ~18 % de lignes sans région | **oui, allowlisté le 19/09** — 1re saisie : 10 / 10 créées le 18/09 | 32 |
| Electronicfirst | 70 | `electronicfirst.py` (**nouveau 15/09**) | PC : `precheck` (non-jeux, logiciels, `[R49a]` EU partiel, `[R49b]` mot de région dans le nom, `[R49c]` console sans slot), `title_region`, `resolve_name` | **oui, allowlisté le 16/09** — parqué puis dé-parqué, défaut PUBLISHER/STEAM fermé par `[R51]` | 4 |

Plus aucun marchand « générique » : la ligne `"KINGUIN": MerchantConfig("Kinguin",
domain="kinguin.net")` inline du registre disparaît au profit de `kinguin.py`, et les six
fichiers nouveaux du 14/09 (Kinguin, K4G, Driffle, GameSeal, Allyouplay, CJS-CDKeys) sont
créés même quand ils ne déclarent encore aucun hook — un fichier qui ne déclare rien est le
constat documenté « aucune donnée, dry-run d'abord », pas une omission.

Ce que plusieurs fichiers marchands partagent SANS passer par un module générique vit dans
`src/merchants/common.py` : le vocabulaire des mots de région (texte → base eu / us / uk /
global, ou label `forbidden region: <LABEL>` du matcher — miroir des tables de
`console_keys` et de `gamivo.py`, tenu à la main), les chaînes de skip R45 (miroirs
byte-exacts de `console_keys`) et `make_config` (constructeur tolérant aux hooks consoles).
Un fichier marchand n'importe jamais `src.matcher`, `src.console_keys` ni le registre
(test-pinned) ; le registre (`src/merchants/registry.py`) importe les modules marchands, le
matcher et le classifieur importent le registre.

## Kinguin (store 58)

- **Fichier** : `src/merchants/kinguin.py` (**nouveau, 2026-09-14**) — `domain="kinguin.net"`
  (avant : entrée inline du registre dans `src/matcher.py`).
- **Feed** : filtré par l'URL `&store=58` (pas le menu déroulant) ; les URLs marchand
  gardent leurs `?params` (`nosalesbooster`, `currency`) tels quels (§4.6).
- **Grammaire PC** : `<Produit> [Édition] [Région] <Plateforme> CD Key`, ex. `Call of Duty:
  WWII - … DLC US PC Steam CD Key`. Plateforme lue dans le titre (source par défaut) ;
  région souvent absente → **GLOBAL implicite** sauf région interdite présente (§4.4) ;
  édition = règle générique du titre (R18 / E0x).
- **Grammaire console (R45)** : plateforme dans le titre, juste avant `CD Key` (`Xbox One /
  Xbox Series X|S`, `Xbox Series X|S / PC`, `PS5`, `PS4/PS5`, `Nintendo Switch`, `Nintendo
  Switch 2`) — familles lues par la grammaire de titre partagée ; PC/Windows = phrase
  générique (`/ PC`) ; la région (code 2 lettres) est AVANT la plateforme — c'est le **slot
  région** (`console_region_slot` → `"US"`, `"EU"`, `"CA"`, `"AU"`… ; la correspondance
  partagée donne EU / US / UK / GB → base, CA / AU / TR / AR / ZA / NA… → `forbidden region:
  <LABEL>` en précheck — correctif du 14/09 : le scan générique ne voyait ni « … US Xbox One
  … » ni le `-us-` en milieu de slug, 150 lignes CA/AU et 37 lignes US passaient en GLOBAL
  implicite). Le slug de l'URL reflète le titre (`-eu-xbox-one-xbox-series-x-s-cd-key`),
  sans segment de catégorie ; `… Account` / `… Access` (URL `-account` /
  `-online-account-activation`) = non-jeu → `console_url_families` renvoie `"console:
  ACCOUNT — not a game (R45)"` / ACCESS. Dernier lot : **365 consoles / 940 lignes** —
  One+Series 211, Series 79, PS5 16, PS4/PS5 15, Switch 13, Switch 2 12 (**saisissables
  depuis le 14/09** : famille SWITCH2, page `nintendo-switch-2`, buckets NINTENDO 99 / 99eu /
  99us / 992) ; **CA 83 / AU 77** en région interdite (skip avant toute résolution, effectif
  depuis le 14/09). P1 (Romain 14/09) : « clé PS5 seule = page PS5 seulement » — une ligne
  `PS5` ne cible jamais la page PS4, `PS4/PS5` cible les deux.
- **Hooks (14/09)** : `domain` ; PC — `precheck` (code de région avant la phrase
  plateforme hors vocabulaire vendable → `forbidden region: <LABEL>` avant tout sondage :
  TR / NA / SEA / CA / AU / DE / UAE / ANZ / ZA / BR / RoW / « EU/UK » ; `Account` / `Access`
  → `skip category: ACCOUNT`), `title_region` (le code « US » nu, invisible du scan générique,
  devient Steam US explicite au lieu d'un GLOBAL implicite + slug `…-us` en 404),
  `resolve_name` (code + phrase plateforme + livraison + « by Digital Distribution Hub » +
  « (valid until …) » retirés → slug du jeu : `…-dlc-eu` → `…-dlc`), `guard_name` (la note
  « (valid until …) » retirée — et elle seule — du titre lu par les gardes, 14/09 soir,
  ci-dessous) ; **pas de `url_platform`** : la plateforme reste lue dans le TITRE (R32b, Romain : « ça marche
  aujourd'hui »), `title_is_platform_source` inchangé. Console — `console_url_families`
  (marqueurs `-account` / `-online-account-activation` → non-jeu ; runs à tirets du slug =
  vocabulaire partagé) ; `console_region_slot` (code majuscule avant la phrase plateforme) ;
  `console_noise = ("CD Key", VALID_UNTIL_RE)`. **Note « (valid until <Month> <Year>) » —
  décision de Romain (14/09) : « Kinguin valid until juin 2027 on rentre »** — une date
  limite d'activation, pas un mot de produit : `guard_name` retire la note — et elle seule —
  du titre lu par les gardes d'identité (R01 / R16 / R01b) et `detect_edition` ;
  `resolve_name` la pèle pour le slug ; `console_noise` la porte (un `re.Pattern`) pour que
  les lignes consoles avec la note résolvent aussi. Avant : 79 lignes / lot en skip
  « different/expanded product — extra words: ['VALID', 'UNTIL', 'MARCH', '2027'] ». Rejeu
  (lecture seule, lot du 12/09, 79 lignes) : 76 passent le précheck, toutes STEAM GLOBAL (2)
  implicite sur le slug du jeu (inchangé) ; 61 avaient résolu leur page avec la note pour
  seuls mots en trop → **candidates désormais** ; 13 restent en 404 (même slug) ; 1 garde
  DLC (R43), 1 « missing AKS words: ['VR'] », 3 skips inchangés (ROW ×2, BUNDLE ×1). Seule
  la forme « (valid until <Month>[,] <Year>) » existe dans le corpus (89 / 89 lignes) ; toute
  autre orthographe reste dans la garde (fail-closed) ; **correctif de revue (14/09 soir) : la
  note n'est retirée qu'en FIN de titre** (`VALID_UNTIL_RE` ancré `\s*$`, comme le motif
  d'avant la décision ; 158 / 158 lignes du corpus, doublons compris, la portent en fin de
  titre) — une note au milieu du titre est une orthographe jamais vue : elle reste dans la
  garde (skip « extra words », fail-closed), jamais un retrait au milieu du nom. **Altergift
  Kinguin — correctif de revue (14/09 soir)** : « on rentre sous gift tous les altergifts »
  vaut aussi pour la livraison « Altergift » de Kinguin (1 ligne / lot, « Sons Of The Forest
  DE PC Steam Altergift » — GERMANY de toute façon ; avant, une ligne Altergift non interdite
  lisait STEAM GLOBAL (2) puis R16 « extra words: ['ALTERGIFT'] ») : `gift_delivery` → True
  pour « <Jeu> [<CODE>] PC Steam Altergift » quand le slug ne contredit pas (le slug Kinguin
  reflète le titre mais est souvent tronqué → silence accepté ; queue `-cd-key` / `-key` /
  compte contre un titre Altergift → « Kinguin delivery conflict », fail-closed) ; Altergift
  hors Steam → « Kinguin Altergift outside the Steam collocation », jamais le bucket gift
  d'une autre plateforme ; `guard_name` / `resolve_name` retirent le mot ; les lignes « Steam
  Gift » gardent la lecture générique (`gift_delivery` → None). Rejeu (lot du 12/09) : 1 ligne
  change (Sons Of The Forest DE : bucket GIFT 25 lu, précheck GERMANY inchangé), 0 candidate.
  Mesure du matin sur le lot du 12/09 (lignes PC, vs code
  committé) : 34 prechecks explicites (30 régions interdites qui finissaient en 404, 1
  relabel AFRICA → NORTH AMERICA, …), 2 régions (« Metro Awakening US PC Steam CD Key » :
  GLOBAL implicite → US), 30 slugs (21 DLC EU en 404 `…-dlc-eu` → `…-dlc`) ; 0 candidat
  touché ; 211 lignes consoles passent de « console » à un motif explicite en mode par défaut
  (CANADA 84, AUSTRALIA 77, ACCOUNT 37, …).
- **Statut live** : éprouvé en safe-auto (142 pages d'historique + nuit du 11/09).
- **Résiduel** : consoles, bundles, monnaies, titres sans page AKS, variantes d'édition.

## Gamivo (store 51)

- **Fichier** : `src/merchants/gamivo.py` (`[R46]` 2026-09-12 ; hooks consoles le 14/09).
- **Grammaire PC `[R46]` (2026-09-12)** : titre `<Jeu> [<Édition>] [<LANG>(/<LANG>)*] <Région>` —
  la région est une queue SANS séparateur, précédée ou non de codes langue majuscules
  (`Ravenswatch EN United Kingdom`, `Tiny Tina's Wonderlands United States`, `FIFA 23
  EN/PL/CS/RU/TR EU`, `KIBORG EN Colombia`, `Storebound ROW`) ; le titre ne nomme JAMAIS la
  plateforme. URL `gamivo.com/product/<slug>-<run plateforme>-<cc>[-<langues>]-<édition>` : le
  run plateforme (`pc-steam`, `steam`, `pc-steam-gift`, `steam-gift`, `pc-ea-app`, `origin`,
  `pc-ubisoft-connect`, `pc-battlenet`, `battle-net-gift`, `pc-gog`…) est ENTRE le slug et le
  code région, l'édition vient APRÈS le code (`tiny-tinas-wonderlands-pc-steam-us-standard`) ;
  variante avec `-pc` en fin (`…-steam-eu-standard-pc`). Édition = règle générique du titre.
  Lot du 12/09 (1 000 lignes) : queues United Kingdom 372, Colombia 310, Global 70, EU 64,
  United States 46, ROW 45, Canada 18, Netherlands 12, Australia 8, North America 6, Turkey
  6, CIS 3, Poland 3, Asia 2, Mexico 2, 22 sans queue (abonnements, cartes, logiciels) ;
  runs d'URL : consoles 802, Steam 115, EA 5, Battle.net 4, Ubisoft 1, GOG 1, 72 sans run.
  Un segment `-en-` / un code `EN` est un marqueur de langue, pas une région (MA7 retirée le
  2026-09-01) ; les verrous de l'ancienne grammaire (`…-steam-key-brazil`, `…-steam-key-ru`)
  restent détectés par les scans génériques (P2-6, P2-6b).
- **Hooks PC** — quatre hooks `[R32e]`, fonctions pures de la ligne de feed :
  `title_region` (United Kingdom / UK → uk, United States / USA → us, EU / Europe → eu,
  Global / Worldwide → global ; sensible à la casse — « The Last of Us » n'est pas US) ;
  `precheck` (toute autre queue de région → `forbidden region: <LABEL>` avec le vocabulaire
  du matcher — COLOMBIA, ROW, CANADA, NETHERLANDS, NORTH AMERICA, CIS, SOUTH EAST ASIA… —
  routée par `aks_lists.suggest_target_list` comme aujourd'hui ; sans queue de titre, le code
  de l'URL juste après le run décide : code interdit ou inconnu → `forbidden region:
  <LABEL|CODE>`, `us` / `uk` seulement dans l'URL → skip explicite « region US declared only
  in the URL … (R46) » car le scan générique ne lit pas un code en milieu de slug (il aurait
  saisi GLOBAL implicite), `eu` / `global` → scan générique ; queue vendable contredite par le
  code URL → skip fail-closed ; jamais un `-us-` nu : « among-us » passe) ; `resolve_name`
  (queue `[<LANGS>] <Région>` retirée avant la devinette de slug : `Ravenswatch`) ;
  `url_platform` (run d'URL → STEAM / EA / UBISOFT / BATTLENET / GOG / EPIC / ROCKSTAR ; le
  dernier run du chemin gagne — `epic-chef-pc-steam-us-standard` → Steam — et un run n'est
  cru que suivi d'un code région ou du marqueur `key` de l'ancienne grammaire ; run console →
  None, le classifieur R45 s'en charge ; rien de reconnu → None → chemin titre / R27
  fail-closed). Garde d'identité : `KINGDOM` en fin de titre après `UNITED`, une fois tout le
  nom AKS couvert, n'est plus un « mot en trop » (14 faux skips `extra words: ['KINGDOM']`
  sur le lot du 12/09 ; « Kingdom Come Deliverance » garde son mot).
- **Saisies fausses du 2026-09-11 — à corriger à la main sur AKS** (lots `20260911-162100`
  et `20260911-183000`, avant R46) : les 6 offres Gamivo créées sont toutes des `… United
  States`, saisies **Publisher (1) GLOBAL implicite / Standard**. Cinq clés Steam
  (`…-pc-steam-us-…`) à repasser en **Steam / US (8)** : 101042269 → AKS 84896 Tiny Tina's
  Wonderlands ; 100395414 → 31894 My Hero One's Justice 2 ; 100398623 → 29681 Age of Empires
  II Definitive Edition ; 100398639 → 3021 Farming Simulator 15 ; 100398707 → 2614 Stronghold
  HD. La sixième, 100728683 → 50562 Riders Republic, est une clé **Xbox** One/Series US
  (`…-xbox-xbox-one-series-us-premium`, saisie Premium sur la page PC) — fuite console, voir
  ci-dessous : pas Steam / US, à retirer de la page PC.
- **Grammaire console (R45)** : le titre ne porte JAMAIS la plateforme (569 des 572 lignes
  consoles du dernier lot ne sont détectables que par l'URL) ; run d'URL après le slug :
  `xbox-xbox-series` / `xbox-series` / `xbox-xboxseries` → Series ; `xbox-xbox-one-series` /
  `xbox-xboxoneseries` / `xbox-one-series` → One+Series ; `xbox-xboxone` → One ; suffixe `-pc`
  / `-windows` / `…windows` fusionné → PC déclaré ; `xbox-pc` seul → skip « PC-only Xbox Live
  key » ; `ps-ps5` / `psn-ps5` → PS5 ; `nintendo-nintendo-switch` → Switch ; région = queue
  « EN <Pays> » du titre (slot région : `"United Kingdom"`, `"Colombia"`…), que
  `detect_region_base` porte aussi via le hook `title_region` (R46) dans la branche console
  (vérifié le 14/09 : « Ravenswatch EN United Kingdom » + `…-xbox-xboxoneseries-uk-standard` →
  UK, buckets 226 / 305 — la moitié Gamivo du finding « région jamais lue » de la revue est
  réfutée) ; queue non vendue → `forbidden region` (précheck R46). La queue de langue
  (`EN`, `EN/PL/CS`) est de la grammaire Gamivo : elle est pelée par le fichier (hook
  `resolve_name`), plus aucune regex Gamivo dans `console_keys`. Mesure R46 (14/09) : 95
  lignes passent le précheck — STEAM 61 / BATTLENET 4 / EA 2 / GOG 1 ; 24 lignes butent encore
  sur le skip générique « language restriction » (préexistant). Dernier lot : **572 / 762** —
  Series 333, One+Series 207 ; **United Kingdom 258, Colombia 203**. **Fuite corrigée
  (2026-09-12)** : le garde console ne lisait que le titre → « Riders Republic Premium
  Edition United States » (`…/riders-republic-xbox-xbox-one-series-us-premium`, run
  `20260911-162100-auto-gamivo-s51-p28`) a été saisi PUBLISHER GLOBAL Premium sur la page PC
  (AKS 50562) — **à corriger à la main** ; `console_marker_in_url` (actif dans tous les modes)
  ferme la brèche.
- **Hooks consoles (cible 14/09)** : `console_url_families` (les runs Gamivo ci-dessus →
  familles ; `xbox-pc` seul → `"console: PC-only Xbox Live key (R45)"` ; rien → None) ;
  `console_pc_declared` (runs `-pc` / `-windows` / `windows` fusionné) ; `console_region_slot`
  (queue `[<LANGS>] <Région>` → texte de région tel quel). Pas de `console_noise` (aucune
  phrase de livraison propre).
- **Statut live** : éprouvé en safe-auto ; 6 saisies fausses du 11/09 à corriger à la main.
- **Résiduel** : 77 % « sans page AKS » sur les pages hautes (titres `<Jeu> EN United
  States`), régions interdites, restrictions de langue.
- **Comptes au MILIEU du slug (bug du 2026-09-24, corrigé le 25).** Gamivo écrit un compte
  `<jeu>-<plateforme>-account-<région>-<édition>` (`hitman-2-xbox-one-series-account-global-
  standard`, titre « Hitman 2 Global ») : l'ancien marqueur ne lisait `-account` qu'en FIN de
  chemin, et l'offre 101137320 a été créée comme clé « Xbox One Game Code » (page 23940) et
  Xbox Series (page 60188). Le jeton `account` est désormais lu n'importe où dans le chemin
  (EXECUTOR_RULES « ACCOUNT offers ») → « console: ACCOUNT — not a game (R45) », liste 30.

## G2A (store 38)

- **Fichier** : `src/merchants/g2a.py`.
- **Grammaire PC** : le titre n'est **pas fiable** pour la plateforme ; elle se lit dans le
  slug de l'URL (`title_is_platform_source=False`, `url_platform_scan=True`) `[R32b]` ;
  région = queue générique du titre / URL (§4.4) ; édition = règle générique du titre.
  « Green Gift » est un mode de livraison, pas un produit (le mot GREEN n'est pas un mot en
  trop, R38). `offer_page_readable=False` : G2A renvoie 403 aux requêtes HTTP hors
  navigateur, donc une plateforme lisible seulement sur la page de l'offre reste
  invérifiable → skip fail-closed `[R32c]`.
- **Grammaire console (R45)** : écrit « X/S » (`(Xbox Series X/S)`, `(Xbox Series X/S, PC)`,
  `Xbox One, PC` sans parenthèses, `(PS5)`, `(Nintendo Switch 2)`) — familles et PC déclaré
  lus par la grammaire de titre partagée ; magasin ` - Xbox Live Key - ` / ` - PSN Key - ` /
  ` - Nintendo eShop Key - ` (marqueurs partagés) ; région en queue (` - EUROPE`, ` - UNITED
  KINGDOM`…) = **slot région** (`console_region_slot` → `"EUROPE"`, `"UNITED KINGDOM"` ;
  pays non vendu → `forbidden region`, 14/09) ; `(Nintendo Switch 2)` → famille SWITCH2
  (saisissable) ; **One et Series sont des lignes séparées** (One+Series : 1 ligne sur 1 544
  toutes runs). URL `<slug>-xbox-series-x-s[-pc]-xbox-live-key-<région>-i<id>`
  (`url_platform_scan` déjà actif pour le PC ; runs = vocabulaire partagé). Dernier lot :
  **42 / 806**.
- **Hooks (14/09)** : `title_is_platform_source=False`, `url_platform_scan=True`,
  `offer_page_readable=False` (inchangés) ; PC — `precheck` / `title_region` : la queue
  ` - <RÉGION>` est TOUJOURS un slot région (une queue majuscule hors vocabulaire →
  `forbidden region: <TEXTE>`, fail-closed : SINGAPORE tombait en GLOBAL implicite) ;
  console — `console_url_families` (runs à tirets partagés sur le slug, id `-i<id>` ignoré) ;
  `console_region_slot` (queue ` - <RÉGION>`). Mesure (lot du 12/09, vs code committé) :
  2 prechecks (GIFT CARD → SINGAPORE, AFRICA → SOUTH AFRICA), 1 région (« Big Adventure:
  Trip to Europe 6 … Steam Gift - GLOBAL » : le générique lisait « Europe » dans le NOM →
  GIFT EU 259, la queue dit GLOBAL → GIFT 25) ; 0 candidat touché.
- **Statut live** : éprouvé en safe-auto.
- **Résiduel** : fort bruit hors jeux (2-3 % de rendement historique) : CIS / ROW / Turquie /
  Allemagne, monnaies, gift cards, skins.

## MMOGA (store 12, marchand 40 sur les pages AKS)

- **Fichier** : `src/merchants/mmoga.py` (2026-09-10 ; hooks consoles le 14/09).
- **Grammaire PC** : `mmoga.com/<Plateforme>-Games/<Produit>[-<CODE>-Key].html?ref=<affid>`.
  Plateforme = segment de catégorie de l'URL (`Steam-Games` → STEAM, `EA-Games` → EA, GOG,
  Epic, Ubisoft/Uplay, Rockstar, Battle.net/Blizzard, Windows → MICROSOFT ; `Xbox-Live`,
  `Playstation-Network`, `Nintendo` → console). Région = code 2 lettres **majuscules**
  juste avant le `Key` final (`Borderlands 2 EU Key` → EU ; `Among Us Key` → global), ou
  après le mot Key entre crochets / parenthèses (`(Steam Key EU)`, `[EU]`, `(EU)` pour un
  code connu seulement — `(PC)` n'est pas une région). Édition = règle générique du titre
  (`Battlefield 4 Premium` → Premium).
- **Hooks PC** : `domain`, `url_platform_prefixes`, `precheck` (code interdit
  RU/TR/BR/AR/CN/KR/JP/PL/UA/MX/PH/VN/TH → `forbidden region: <LABEL>`, code inconnu →
  skip fail-closed), `title_region` (EU/US/UK/GB → région autoritaire), `resolve_name`
  (retire la queue de région avant la devinette de slug) `[R32e]`.
- **Historique** : onboardé le 2026-09-10 directement en safe-auto (décision Romain) ; les
  DLC / Season Pass sont saisis sur leur page AKS propre depuis le 2026-09-11 `[R43]`.
- **Grammaire console (R45)** : plateforme dans le titre, en parenthèses ou après un tiret
  (`(Xbox One / Series X|S Download Code) - EU`, `(Xbox Series X|S Download Code)`, `Xbox
  Series X|S / Windows`, `- PS5 Download Code [EU]`, `- Nintendo Switch Download Code`) —
  familles et « / Windows » lus par la grammaire de titre partagée ; catégorie d'URL
  `Xbox-Live/Xbox-One-Game-Keys`, `Xbox-Live/Xbox-Series-XS-Game-Keys`,
  `Playstation-Network/Playstation-5-Game-Keys`, `…/Playstation-4-Game-Keys`, `Nintendo/Switch` —
  la catégorie ne donne que la génération BASSE (un cross-gen « Xbox One / Series X|S » est
  classé sous `Xbox-One-Game-Keys` ; c'est le titre qui déclare les deux) ;
  `Xbox-Live/Xbox-360-Game-Keys` → skip ; cartes / abonnements (`PSN-Cards-*`,
  `Nintendo-eShop-Cards`, `Playstation-Plus`, `Xbox-Live-Cards`, `Xbox-Live-Gold`) → non-jeu ;
  slot région = ` - EU` / `[EU]` / `(Steam Key EU)` / `EU Key`. Dernier lot : **388 / 723** —
  One+Series 149, Series 89, Switch 63, One 35, PS5 10, non-jeu 85 ; queue région EU 240
  (` - EU` 188, `[EU]` 44, `EU Key` 5, `[EU Key]` 3).
- **Hooks consoles (cible 14/09)** : `console_url_families` (segments de catégorie ci-dessus
  → familles ; `Xbox-360-Game-Keys` → `"console: Xbox 360 (R45)"` ; catégories cartes /
  abonnements → `"console: <MARKER> — not a game (R45)"` ; autre catégorie → None) —
  avant le 14/09 ces règles (`_MMOGA_CATEGORY_RULES`, `_MMOGA_NON_GAME_CATEGORY_RE`,
  `_parse_url_mmoga`) vivaient dans `console_keys` ; `console_region_slot` (` - EU`, `[EU]`,
  `(Steam Key EU)`, `EU Key` → `"EU"`) ; `console_noise = ("Download Code",)`.
- **Statut live** : éprouvé en safe-auto (1 265 créées les 10-12/09).
- **Résiduel** : 388 consoles — traitées par défaut depuis le 15/09 (dry-run consoles du
  15/09 : 663 offres → 174 candidats consoles, 489 skips ; premier sweep console réel le
  15/09, cf. HANDOFF §4) —, 157 sans page AKS, bundles, monnaies, passes, variantes d'édition.

## K4G (store 92)

- **Fichier** : `src/merchants/k4g.py` (**nouveau, 2026-09-14**).
- **Grammaire PC** : `<Produit> [Édition] [Région] <Plateforme> CD Key` **sans** parenthèses ni
  tirets séparateurs (`Monster Hunter Wilds Gold Edition Europe Steam CD Key`) ; plateforme
  dans le titre ; région en toutes lettres avant la plateforme (`Europe`, `United States`),
  lue par le scan générique ; édition = règle générique du titre ; la devinette de slug pèle
  les phrases finales plateforme / région (`_TRAILING_NOISE_PHRASES`, mécanisme générique)
  et les tirets internes sont ceux du nom du produit. Pagination `&p=N`.
- **Grammaire console (R45)** : `<Jeu> [Édition] <Région> <Plateforme> CD Key` — `XBOX
  One/Series X|S` 45, `XBOX Series X|S` 25, `PC/XBOX One/Series X|S` 9, `PC/XBOX Series X|S` 5,
  `PS5` 8, `PS4/PS5` 1, `Nintendo Switch` 13, `Nintendo Switch 2` 13 (dernier lot ; **Switch
  2 saisissable depuis le 14/09**, page `nintendo-switch-2`, buckets NINTENDO) — familles et
  `PC/XBOX …` lus par la grammaire de titre partagée ; région en toutes lettres avant la
  plateforme (Europe 75, United States 31) = **slot région** (`console_region_slot` →
  `"Europe"`, `"United States"` ; pays non vendu → `forbidden region: <LABEL>` en précheck,
  14/09 — jamais un GLOBAL implicite pour un mot de région retiré du titre) ; URL
  `/product/<slug>-<plateforme>-<région>-…-cd-key-<8 car.>` (`xbox-one-series-x-s`,
  `xbox-series-x-s`, `pc-xbox-one-series-x-s`, `nintendo-switch(-2)`, `playstation-5`,
  `ps4-ps5` — runs du vocabulaire partagé). Dernier lot : **135 / 592**.
- **Hooks (14/09)** : `domain` ; PC — `precheck` (nom de région en toutes lettres avant
  la phrase magasin hors vocabulaire vendable → `forbidden region: <LABEL>`), `title_region`
  (Europe / United States / Global — lecture identique au générique, désormais déclarée),
  `resolve_name` (région + magasin + livraison retirés, « Altergift » compris),
  `gift_delivery` et `guard_name` (Altergift = Steam Gift, ci-dessous) ; console —
  `console_url_families` (runs partagés sur le slug `/product/…`, exigés suivis d'un slug de
  région connu ; suffixe `-cd-key-<8 car.>` ignoré) ; `console_region_slot` (mot de région
  entre l'édition et la phrase plateforme, vocabulaire plus large que le partagé :
  Luxembourg, Mexico, UAE…). Mesure du matin (lot du 12/09, vs code committé) : 12 slugs ;
  0 candidat touché.
- **« Steam Altergift » = Steam Gift — décision de Romain (14/09) : « Steam Altergift =
  Steam Gift on rentre sous gift tous les altergifts »** (216 / 592 lignes du lot, jamais
  candidates avant ; le skip explicite `skip category: ALTERGIFT` du matin est retiré) :
  `gift_delivery` répond True pour le mot entier ALTERGIFT (insensible à la casse) et
  `detect_region` superpose le bucket GIFT Steam à la région de base du titre / de l'URL —
  GIFT (25) sans région ou Global, GIFT EU (259) pour Europe ; base US / UK sans bucket gift
  Steam → skip fail-closed « no region id for STEAM/GIFT US » (inchangé) ; région interdite
  (North America, Americas) → précheck inchangé ; plateforme STEAM (le titre colloque STEAM
  et ALTERGIFT). « Altergift » n'est jamais un mot de produit : `guard_name` retire ce mot —
  et lui seul — du titre des gardes (R16 comptait « extra words: ['ALTERGIFT'] »),
  `resolve_name` le retire du slug (`seafrog`, plus `seafrog-steam-altergift`). Rejeu
  (lecture seule, lot du 12/09, 218 lignes Altergift dédoublonnées) : 182 passent (STEAM
  GIFT 25 ×120, GIFT EU 259 ×62 ; 183 / 183 slugs des lignes non pré-skippées changent vers
  le slug du jeu — vs le run du 12/09, slug générique ; vs le fichier K4G du matin, 90378a6,
  2 slugs seulement, les deux lignes hors grammaire « … Steam Europe Altergift »), 36 skips (NORTH AMERICA 29, BUNDLE 3, AMERICAS 2, PASS 1, GIFT UK sans
  bucket 1) ; côté AKS (run enregistré) : 144 étaient des 404 sur `…-steam-altergift` →
  slug du jeu **à sonder au prochain dry-run**, 36 gardent d'autres mots en trop (R16 :
  « Plus Expansion Pack », « Treasure from Heaven », « Episode 3 »…), 2 garde SEASON PASS
  (R43) ; aucune ligne n'avait « ALTERGIFT » pour seul mot en trop → 0 candidate
  immédiate, 0 candidate enregistrée touchée. **Deux garde-fous fail-closed sur cette
  décision (correctifs de revue, 14/09 soir — `k4g.altergift_verdict`, lu par `precheck` et
  `gift_delivery`)** : (1) **le slug doit être d'accord** — K4G écrit la livraison dans le
  slug (`-altergift-` / `-alter-gift-`, 217 / 218 lignes Altergift du lot) ; UNE ligne disait
  le contraire, l'offre 101030313 « Trine 5: A Clockwork Conspiracy Steam Altergift » sur
  `…-steam-global-instant-cd-key-48V2PFDZ` (titre gift, URL clé — la classe de bucket, GIFT
  25 ou GLOBAL 2, ne se lit pas sur la ligne) → « K4G delivery conflict: title Altergift but
  URL says cd-key (no altergift segment) — not entered », avant tout sondage ; un slug sans
  aucun segment de livraison (hors grammaire d'URL) → même refus ; le conflit miroir (titre
  « CD Key », slug `-alter-gift-`, 0 ligne) est refusé aussi — la lecture générique `-gift-`
  aurait rangé une clé sous GIFT (25). (2) **Steam seulement** — « Steam Altergift = Steam
  Gift » nomme le mécanisme (216 / 216 lignes en grammaire disent « Steam », les 2 lignes
  hors grammaire « … Steam Europe Altergift » aussi) : un Altergift dont la phrase magasin
  n'est pas Steam (« Battle.net Altergift », « Steam / Epic Games Altergift ») ou absente est
  une grammaire jamais vue → « K4G Altergift outside the Steam collocation … — not
  entered », jamais le bucket gift d'une autre plateforme (Battle.net 570 / 567 existent),
  jamais une clé simple. Rejeu (lot du 12/09, 6 314 lignes tous marchands) : 1 seule ligne
  K4G change — Trine 5 (404 enregistré, désormais refus explicite) ; 0 candidate.
- **Statut live** : éprouvé en safe-auto.
- **Résiduel** : ~25 % de consoles, sans page AKS.

## Driffle (store 127)

- **Fichier** : `src/merchants/driffle.py` (**nouveau, 2026-09-14**).
- **Grammaire PC** : `<Produit> (<Région>) (PC) - <Plateforme> - Digital Key` ; plateforme
  dans le titre ; région dans la première parenthèse (Ga01 : l'URL décide devant le titre) ;
  **édition dans le slug de l'URL** (`slug_edition_text`, id `-p<id>` retiré — Romain
  2026-07-07 : le slug est l'identité canonique du marchand, il gagne sur le titre) ; champs
  `name` / `url`, `stock` = `y`/`n` ; modal `offer[region]` / `offer[edition]`. Feed
  dynamique → re-scan avant chaque submit (règle générale).
- **Grammaire console (R45)** : plateforme dans la 2e parenthèse — `(Xbox Series X|S)` 33,
  `(Xbox One / Xbox Series X|S)` 28, `(Xbox One)` 10, `(PS4 / PS5)` 8 + `(PS4/PS5)` 2, `(PS5)`
  5, `(PS4)` 5, `(Nintendo Switch)` 5, `(Nintendo Switch 2)` 1, `(PC / Xbox …)` = PC déclaré
  (phrase générique) — magasin ` - Xbox Live - ` / ` - PSN - ` / ` - Nintendo - ` (marqueurs
  partagés) ; région dans la 1re parenthèse (Global 42, Europe 41, United States 16) =
  **slot région** (`console_region_slot` → `"Europe"`, `"Global"`, `"Hong Kong"` ; `(Europe)`
  → eu ; `(Hong Kong)` → `forbidden region: HONG KONG`, 14/09) ; « 1 Random Xbox Game … » →
  pré-skip RANDOM (14/09, générique). L'URL écrit **`xbox-series-xs`**
  (`-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p…`, `-ps4-ps5-psn-digital-key-`).
  Dernier lot : **112 / 464**.
- **Hooks (14/09)** : `domain` ; PC — `precheck` (pays entre parenthèses hors vocabulaire
  générique → `forbidden region: <LABEL>` : France, Austria, Netherlands, Belgium, Egypt,
  Hong Kong, Latvia, Lithuania, Romania — avant, GLOBAL implicite sauvé par un skip de
  catégorie ou un 404), `title_region` (1re parenthèse — lecture identique au générique,
  déclarée et testée) ; pas de `resolve_name` (le retrait générique des parenthèses + queue
  donne déjà le slug du jeu) ; console — `console_url_families` (runs partagés dont
  l'orthographe `xbox-series-xs`, id `-p<id>` ignoré) ; `console_region_slot` (1re
  parenthèse) ; `console_noise = ("Digital Key", "Digital Code")`. Mesure (lot du 12/09, vs
  code committé) : 8 prechecks (2 cartes V-Bucks (France), 6 abonnements Tinder → région
  interdite au lieu de SUBSCRIPTION) ; 0 région, 0 slug, 0 candidat touché.
- **Statut live** : éprouvé en safe-auto.
- **Résiduel** : sans page AKS, consoles, bundles, monnaies, DLC sans page propre.

## Instant Gaming (store 28)

- **Fichier** : `src/merchants/instant_gaming.py`.
- **Grammaire PC** : titres **sans aucun jeton** (une clé Steam ressemble à un simple
  `<Produit>`), la région n'est pas dans le feed ; plateforme ET région viennent de la page
  marchande de l'offre, lue **une fois** (`data-platform` → plateforme, suffixe du `<title>`
  → région) `[R32]` / `[R33]` ; édition = règle générique du titre.
- **Hooks** : `offer_page_resolver=ig_offer_signals` ; une région non vendable renvoie
  `forbidden region: <label>` avec le routage habituel. Console (14/09) :
  `console_url_families` → toujours None (déclaré : l'URL IG ne dit rien) ; une plateforme
  console lue sur la page IG (« NINTENDO SWITCH », « XBOX », « PLAYSTATION 5 ») n'est pas
  dans `IG_PLATFORM_TEXT_MAP` → plateforme None → skip R32 « offer page names an
  unrecognized platform » — aucune saisie console depuis IG tant qu'un hook fondé sur la
  page n'est pas conçu (testé avec une page simulée).
- **Historique** : un sweep entier saisi avec une mauvaise région avant R33 (2026-08-13,
  corrigé) ; propre depuis.
- **Grammaire console (R45)** : la plateforme n'est PAS dans le feed (titres nus, URL
  `/en/<id>-/`) — elle vient de la page IG (`offer_page_resolver`) ; le classifieur R45 ne
  voit que les marqueurs du titre (dernier lot : 8 lignes, 7 Game Pass + 1 « Nintendo Switch
  2 Edition »). Hors périmètre console en v1 — **bloqué** : aucune saisie console depuis IG
  (README « Capability status »).
- **Statut live** : éprouvé en safe-auto.

## Eneba (store 19)

- **Fichier** : `src/merchants/eneba.py` (R29 ; hooks consoles le 14/09).
- **Grammaire PC** : le titre omet souvent la plateforme ; l'URL commence par le segment de
  plateforme (`eneba.com/steam-<slug>`, `gog-`, `epic-`, `uplay-` → UBISOFT, `origin-` →
  EA, `blizzard-` → BATTLENET, `windows-` → MICROSOFT) `[R29]`. Région dans le titre quand
  elle existe (`… Steam Key (PC) EUROPE`, `UNITED STATES`), sinon GLOBAL implicite ; édition
  = règle générique du titre. Titres avec caractères Unicode compatibilité (« Ⅱ ») → NFKC
  avant identité.
- **Hooks PC** : `url_platform_prefixes`.
- **Grammaire console (R45)** : `<Jeu> [(<Plateforme>)] XBOX LIVE Key <RÉGION>` — la région
  vient APRÈS le marqueur de clé (EUROPE 730, UNITED STATES 626) = **slot région**
  (`console_region_slot` → `"EUROPE"`, `"UNITED STATES"` ; un mot de région retiré du titre
  sans base vendable → skip, jamais GLOBAL implicite, 14/09) ; `-nintendo-switch-2-` → famille
  SWITCH2 (saisissable, 14/09) ; `(Xbox Series X|S)` 299, `(Windows/Xbox Series X|S)` 179 (PC
  déclaré), `PC/XBOX LIVE Key` 172 (clé PC vendue via Xbox Live → skip « PC-only ») ; URL :
  segment de tête `xbox-` / `psn-` / `nintendo-` (préfixe de MAGASIN, PAS une génération :
  `xbox-one-last-breath-…` est le jeu « One Last Breath » — 13 des 16 lignes « Xbox One » du
  lot du 12/09 étaient cet artefact), puis `-xbox-series-x-s-xbox-live-key-`,
  `-windows-xbox-series-x-s-`, `-ps4-ps5-`, `-nintendo-switch(-2)-`. Dernier lot : **1 376 /
  1 659 lignes consoles, dont 704 « XBOX LIVE Key » sans génération** (ni titre ni URL) →
  skip « console: no declared generation (R45) » (politique P4, à confirmer par Romain).
- **Hooks consoles (cible 14/09)** : `console_url_families` (segment de magasin en tête
  retiré, puis les runs Eneba `-xbox-series-x-s-` / `-ps4-ps5-` / `-ps5-` / `-ps4-` /
  `-nintendo-switch(-2)-` → familles ; `-pc-xbox-live-key-` → `"console: PC-only Xbox Live
  key (R45)"` ; rien → None → « no declared generation ») — avant le 14/09 `_parse_url_eneba`
  et le retrait du segment de tête vivaient dans `console_keys` ; `console_pc_declared` (run
  `-windows-`) ; `console_region_slot` (mot après `XBOX LIVE Key` / `PSN Key` / `Nintendo
  Key`). Précision (implémentation du 14/09) : `console_url_families` ne lit QUE le slot
  juste avant le dernier marqueur `-xbox-live-key` / `-xbox-key` / `-psn-key` / `-eshop-key`
  (URL Eneba = segment de magasin + titre slugifié) — un run de famille ailleurs dans le slug
  (nom du jeu) ou une URL sans marqueur → None → « no declared generation » (1 374 / 1 376
  URL du lot portent le marqueur, les 2 autres déclarent la famille dans le titre : 0 écart
  de comptage). `console_region_slot` (texte après « Key ») corrige 2 lignes du lot :
  « Dying Light Essentials Edition (Without DE) XBOX LIVE Key EUROPE » (DE lu comme région →
  GERMANY interdit, désormais eu) et « Truck Simulator Cargo Driver 2025 - USA (Windows/Xbox
  Series X|S) XBOX LIVE Key EUROPE » (USA + EUROPE → « not mapped », désormais eu).
- **Statut live** : **jamais balayé en réel** — dry-run du 2026-09-12 (32 candidats sur
  3 000 offres, 2 698 lignes consoles, voir CHANGELOG) ; sweep réel sur go de Romain
  seulement ; très fort taux de consoles (pages entières — les 704 lignes sans génération
  restent skippées, politique P4) et de régions interdites.

## Allyouplay (store 17)

- **Fichier** : `src/merchants/allyouplay.py` (**nouveau, 2026-09-14**, identité seule :
  store 17, `domain="allyouplay.com"` — à confirmer au premier dry-run ; un hôte faux fait
  échouer fermé chaque ligne (« offer URL not on allyouplay.com »), jamais une saisie).
- **Grammaire PC / console** : **aucune donnée** — jamais balayé, pas d'historique. Le fichier
  existe pour porter la règle (chaque marchand a son fichier) et recevoir la grammaire
  relevée au dry-run ; tant qu'il ne déclare rien, seuls le vocabulaire partagé et le
  générique s'appliquent (fail-closed).
- **Hooks** : `domain` seul (aucun hook de grammaire inventé sans lot observé).
- **Statut live** : dans la liste blanche mais **jamais balayé** ; un dry-run
  (`scripts/10 … --dry-run`) est exigé avant tout sweep réel (Romain, 2026-09-11).

## GameSeal (store 126)

- **Fichier** : `src/merchants/gameseal.py` (**nouveau, 2026-09-14**, `domain="gameseal.com"`
  — hôte des lignes du sweep de juillet 2026 et des tests).
- **Grammaire PC** (déclarée le 14/09 d'après le sweep de juillet 2026, à re-relever au
  premier dry-run) : `<Jeu> [(DLC)] (<Plateforme>) <Store> <Delivery> - <RÉGION>` (« Porter
  in the Castle (PC) Steam Key - GLOBAL ») ; la queue MAJUSCULE après le dernier tiret est
  TOUJOURS un slot région (GLOBAL 279, EU 21, UNITED STATES 18, UNITED KINGDOM 15, CANADA
  12, ROW 6, EMEA 3, BELGIUM 2, NA 1, AU 1, EU/NA 1) — hors vocabulaire → fail-closed.
- **Grammaire console (R45)** : sweep de juillet 2026, 33 / 1 610 : `(<Plateforme>) <Store>
  Key - <RÉGION>` (`(Xbox One / Xbox Series X|S) Xbox Live Key - EU`) — familles par la
  grammaire de titre partagée ; queue ` - <RÉGION>` = **slot région** (`console_region_slot`
  → `"EU"`, `"United States"`) ; URL `<slug>-xbox-one-xbox-series-x-s-xbox-live-key-eu` (runs
  du vocabulaire partagé).
- **Hooks (14/09)** : `domain` ; PC — `precheck` / `title_region` (la queue ` - <RÉGION>`
  explicite : « - NA » → NORTH AMERICA, « - AU » → AUSTRALIA, « - BELGIUM » — hors du
  vocabulaire générique, ces lignes finissaient en 404 ou en « extra words: ['NA'] ») ;
  console — `console_url_families` (runs partagés ; `xbox-360` → skip R45) ;
  `console_region_slot` (queue ` - <RÉGION>`). Mesure (sweep du 15/07, vs code committé) :
  30 prechecks (NORTH AMERICA 27, AUSTRALIA 1, BELGIUM 2) ; 0 candidat touché.
- **Hook `resolve_name` (20/09)** : la queue « <Store> <Livraison> - <RÉGION> » est pelée
  AVANT la résolution du slug — « Zombies Invasion (PC) Steam Gift**-** EU » →
  « Zombies Invasion (PC) » → `zombies-invasion`. Sans lui, le nettoyage générique gardait
  la queue quand le tiret était COLLÉ (il ne connaît « GLOBAL » que par sa liste de bruit —
  EU n'y est pas — et son découpage exige un tiret entouré d'espaces) : slug
  `…-steam-gift-eu`, inexistant. Mesure sur le balayage du 19/09 : **44 offres EU, 0 création,
  41 refus « no AKS product page found »**, contre 66 % de créations pour les EU bien
  espacées. Non-régression : sur les 1 090 lignes déjà écrites, 0 slug résolu perdu. La
  pelure est ancrée à la fin et faite UNE fois (« Christmas Gift Steam Key » → « Christmas
  Gift »), et les gardes d'identité (R01/R16) lisent toujours le titre BRUT.
- **Statut live** : dans la liste blanche mais **jamais balayé en safe-auto** ; dry-run
  d'abord (Romain, 2026-09-11). Premier balayage réel : 19-20/09 (`20260919-082932-auto`).

## CJS-CDKeys (store 30)

- **Fichier** : `src/merchants/cjs.py` (**nouveau, 2026-09-14**, identité seule : store 30,
  `CONFIG.name = "CJS-CDKeys"` (orthographe de la liste blanche), `domain="cjs-cdkeys.com"` —
  à confirmer au premier dry-run ; un hôte faux fait échouer fermé, jamais une saisie).
- **Grammaire PC / console** : **aucune donnée** — jamais balayé, pas d'historique ; même
  logique qu'Allyouplay : le fichier porte la règle et recevra la grammaire relevée au
  dry-run, rien n'est inventé d'ici là.
- **Hooks** : `domain` et, depuis le 24/09, `url_identity_params=("variation",)`.
- **`variation=` est l'identité de l'annonce (2026-09-24).** « …/Ash-of-Gods%3A-The-Way-Steam-
  Key.html?variation=609 » et « …?variation=608 » sont deux annonces (deux régions) sur le MÊME
  chemin. Chemin seul, la sœur restée au feed faisait sortir chaque création « STILL in feed » :
  13 fausses erreurs depuis le 20/09, dont 8 avec la sœur visible sur la même page du feed.
  `variation` rejoint désormais la clé d'identité (`submitter._url_key`, EXECUTOR_RULES §7).
- **Statut live** : dans la liste blanche, balayé en groupe B depuis le 22/09.

## Difmark (167, parqué) — **classe B** (Romain, 2026-09-21)

- **Fichier** : `src/merchants/difmark.py`.
- **Grammaire PC** : titres nus `<Nom> Standard Edition` ; chaque URL porte un segment
  `buy-console-account-` boilerplate, retiré avant tout signal (`url_ignore_substrings`),
  jamais un motif de skip. Plateforme et région lues sur la page de l'offre
  (`resolve_difmark_offer`). Hors liste blanche safe-auto.
- **Grammaire console (R45, règle du 14/09)** : les lignes « <Jeu> (Account) Standard
  Edition » (URL `buy-console-account-<slug>-nintendo-switch-account-<id>`, 393 lignes sur
  les runs sauvegardés) sont des **COMPTES**, jamais des clés — skip « console: ACCOUNT — not
  a game (R45) » (« Account » n'importe où dans le titre = marqueur partagé ; préfixe d'URL
  `buy-console-account-` + suffixe `-account-<id>` = grammaire Difmark). La revue du 12/09
  les avait vues classées clés Switch (compte saisi comme clé) ; un compte Difmark ne prend
  jamais la branche console.
- **Hooks (cible 14/09)** : `url_ignore_substrings` ; `console_url_families` (chemin
  `/buy-console-account-…-account-<id>` → `"console: ACCOUNT — not a game (R45)"`).
- **LA QUERY STRING PORTE TOUT (lecture de la liste 30, 2026-09-21).** Le feed *pending*
  (liste 9) de Difmark est VIDE : ses lignes vivent dans la liste **account (30)**, 299 pages.
  1 348 lignes distinctes lues sur cinq tranches réparties (pages 1-3, 75-77, 150-152,
  225-227, 297-299) : **chaque URL porte des paramètres structurés**, que le slug ne dit pas —
  `?referal=…&marketplace_id=<n>&edition_id=<n>&region_product_id=<n>&coupon=…&seller_id[]=…`,
  et `foreignId` vaut `<produit>-<région>-<édition>` sur 1 348 / 1 348.
  - `marketplace_id` = la boutique/plateforme, et il en dit PLUS que le slug : 8 → Xbox (490),
    5 → PlayStation (462, dont **212 lignes dont le slug ne nomme aucune plateforme**),
    2 → Steam (381), 10 → Epic (12), 14 → Microsoft (1).
  - `edition_id` = l'édition, et elle concorde avec le titre sur **1 348 / 1 348** : 780 =
    Standard (1 331 lignes, toutes titrées « Standard Edition », zéro exception), et les 17
    autres nomment toutes leur palier — 2 = Deluxe, 3 = Complete, 15 = Ultimate, 751 =
    Upgrade, 12 = Definitive, 1004 = Vault, 1463 = Early Access Pack.
  - `region_product_id` = **1 sur 1 347 lignes** (une seule exception, 59, sur un Season Pass
    PS4). L'emplacement est connu, mais la VALEUR ne discrimine pas : il faudrait la table de
    correspondance Difmark — ou ancrer une fois « 1 = ? » en ouvrant une page — avant d'en
    tirer une région AKS.
  - **La région n'est PAS dans le nom** : 0 sur 1 348 (les « trouvailles » d'un scan naïf sont
    des sous-chaînes — « Lily Fant**asia** », « the Devil is **in** the Details »).
  Conséquence : la plateforme et l'édition de Difmark sont lisibles **sans ouvrir la page
  marchande**.
- **CLASSE B — il n'y a pas de région géographique chez Difmark (Romain, 2026-09-21).** Sa
  décision, mot pour mot : « Difmark, tu peux considérer en classe B, car il n'y a pas de
  différentes régions géographiques. On a des régions spéciales (compte Steam, Epic, tout
  ça), mais on n'a pas de régionalisation. » La « région » d'une ligne Difmark, c'est le SEAU
  DE COMPTE de sa plateforme, pas un pays. **Ancré en lecture seule le même jour** sur les
  deux seules valeurs que `region_product_id` prend (1 sur 1 347 lignes, 59 sur une) :
  `resolve_difmark_offer` rend `raw_region='GLOBAL'` pour les deux, et le nom d'offre de la
  page le dit en toutes lettres — « DYNASTY WARRIORS 9 (XBX 1 ACCOUNT, **REGION FREE**) » et
  « Fallout 4 - Season Pass (PS4 ACCOUNT, **REGION FREE**) ». Un audit « trouvera » que
  `region_product_id` n'est pas mappé et voudra fermer : il n'y a rien à mapper, les deux
  valeurs observées désignent la même chose.
- **BRANCHE COMPTE + LISTE BLANCHE (Romain, 2026-09-21).** Deux décisions du même jour, après
  la première saisie réelle (10 offres créées et prouvées sur 13 candidats) :
  1. « Elle ne doit pas continuer à passer par la branche console. Elle doit être routée vers
     une branche compte. Elle utilisera la branche jeu ou la branche console selon le type
     d'account. » → `MerchantConfig.account_row` : le marchand déclare qu'une ligne est un
     COMPTE (grammaire d'URL Difmark : préfixe `/buy-console-account-`, suffixe
     `-account[-<id>]`), et cette ligne ne passe plus par le classifieur console — ni au
     précheck, ni au dispatch. Le refus « ACCOUNT — not a game » du 14/09 n'est plus le
     verdict de ces 107 lignes par page. **La sécurité tient désormais à l'AIGUILLAGE** : la
     branche compte exige une PAGE AKS « <plateforme> Account » ET un seau « Account » — un
     compte ne peut donc toujours pas entrer sur une page de clé (l'incident du 12/09). Les
     marqueurs NON-JEU restent dus (une « PSN Card (Account) », un « Game Pass (Account) »
     sont refusés comme partout), et le hook `console_url_families` reste en filet.
  2. « Ajouter difmark a la whitelist » → `("Difmark", "167")` dans `auto_merchants.py`.
- **Un seul type de compte est câblé : STEAM.** Romain : « t'as trouvé du Steam account, c'est
  très bien, ajoute-le. Quand tu trouveras du Epic account, tu ajouteras l'Epic account. »
  `DIFMARK_ACCOUNT_PAGE_KINDS = {"STEAM": "steam-account"}` et les seaux 412 / 480 / 578.
  Les autres types sont refusés en NOMMANT ce qui manque (« compte EPIC — pas encore de page
  ni de seau AKS confirmés pour ce type de compte »), via
  `DIFMARK_ACCOUNT_PLATFORMS_PENDING`. Mesure du 21/09 : **50 titres réels du feed sondés**
  sur `epic-account`, `playstation-account`, `ps4-account`, `xbox-one-account`,
  `xbox-series-account`, `windows-account` → **0 page**. Les gabarits existent chez AKS pour
  quelques blockbusters (`gta-5-epic-account`, `call-of-duty-black-ops-7-xbox-one-account`)
  mais pas pour ce catalogue — et le test qui tranche : « Train Sim World 7 » a sa page
  `…-steam-account` (offre créée le 21/09) et n'a ni `…-epic-account` ni
  `…-playstation-account`. Le facteur limitant est le catalogue AKS, pas notre grammaire.
- **À savoir avant de le balayer** : sa file Pending (liste 9) est **vide**, ses lignes vivent
  dans la liste *account* (30) — `scripts/02_extract_feed.py --list 30` et
  `scripts/05_submit.py --list 30`. Le balayage `scripts/10`, lui, lit toujours la liste 9.
- **Statut live** : parqué (hors liste blanche).
- **La page doit DIRE compte ou clé (2026-09-25).** Le 23/09, huit comptes de la liste 30 sont
  entrés comme clés Steam GLOBAL(2) : la branche Difmark ne croyait que le mot ACCOUNT de la
  page, et les libellés réels n'en ont pas — « ⭐️ Stellaris +14 Games [Steam/Global]
  [OFFLINE] », « Beasts of Bermuda [STEAM/GLOBAL][OFFLINE] » (OFFLINE = compte partagé hors
  ligne). Désormais : ACCOUNT ou OFFLINE dans le libellé (ou ACCOUNT dans le titre) → compte
  (page `…-steam-account`, seau Account, ou refus nommé si la page manque) ; le libellé clé du
  17/07 « <Jeu> (<plateforme>) … » ou le mot KEY → clé (la « vraie clé Difmark » revue le
  21/09 passe toujours : le « account » de l'URL est un GABARIT ici) ; tout autre libellé →
  refus « la page ne dit ni compte ni clé », jamais une clé par défaut. La garde finale du
  submitter laisse la page décider pour Difmark (seul le mot du titre y est contrôlé).

## GameBoost (store 157, liste blanche safe-auto depuis le 2026-09-16)

- **Fichier** : `src/merchants/gameboost.py`. **Hors liste blanche safe-auto**
  (`src/admin/auto_merchants.py`) : le fichier sert aux runs **supervisés** (02 → 03 → 04 →
  05), jamais à `/auto`.
- **Historique — pourquoi ce marchand avait été abandonné.** Un run GameBoost a été
  **annulé en direct le 2026-07-15** (`[R27]`, CHANGELOG) : des offres Steam partaient en
  Publisher parce que les titres de l'époque ne portaient aucun jeton de plateforme et que
  la vérité est sur la page de l'offre — **inatteignable, Cloudflare la bloque**. Romain ce
  jour-là : « il y a des offres steam qu'on détecte en publisher, ça c'est seulement
  renseigné sur la page marchand. » Les 33 candidats ont été jetés avant validation.
- **Ré-audit du 2026-09-15 (821 lignes uniques, pages 1-10 du feed, lecture seule).** Les
  titres déclarent aujourd'hui la plateforme dans la grande majorité des lignes et la région
  dans un peu plus de la moitié. La page marchand n'est **jamais** ouverte : ce qui n'est
  pas lisible dans le titre est refusé.
- **Grammaire PC** (lue depuis la FIN du titre) :
  `<Jeu>[ | <Édition>][ (<Édition>)][ (DLC)] (<Plateforme>)[ (<RÉGION>)]`,
  `<Jeu>[ (PC)] - <Plateforme> [CD ]Key[, PC][ - <RÉGION>]`,
  `<Jeu> <Plateforme> Key[ <RÉGION>]`. Lignes réelles : « Wardogs | Supporter Edition (PC) -
  Steam Key - United States » (us), « Sekiro: Shadows Die Twice (GOTY) (Xbox One) (EU) »
  (eu), « Stronghold 2: Steam Edition Steam Key EU » (eu — « Steam Edition » reste dans le
  nom, la découpe est ancrée à la fin), « METAL GEAR SOLID V: GROUND ZEROES Steam Gift
  GLOBAL » (le mot de livraison `Gift` est épluché, le bucket GIFT reste la lecture
  générique).
- **`[R47]` la région est OBLIGATOIRE dans un titre GameBoost (2026-09-15).** Contrairement
  à Kinguin ou MMOGA — où « pas de code » EST la façon d'écrire « global » — GameBoost écrit
  ses lignes mondiales en toutes lettres (`GLOBAL`, `Global`, `ROW`) et laisse le slot VIDE
  sur les lignes dont la région n'est que sur la page marchand : **137 des 821 lignes (17 %)**.
  Les saisir sur le défaut générique « GLOBAL implicite » filerait des clés régionalisées en
  monde entier — exactement le mode de panne de `[R27]`. Un titre sans slot région est donc
  un skip `precheck` fail-closed, jamais GLOBAL(2). Lever la règle demande la page marchand :
  même blocage qu'en juillet, ce n'est pas une règle à assouplir ici.
- **Non-jeux** : GameBoost est d'abord une place de boosting / comptes. Les annonces de clés
  sont des URL plates finissant par `-00-<id>` ; les cartes cadeaux et recharges vivent sous
  un segment `/gift-cards/` et s'écrivent avec des points médians (« Razer · Chile · 500
  CLP ») — **175 lignes sur 821 (21 %)**, skip catégoriel.
- **Plateforme** : lecture générique du titre (comme Kinguin, `title_is_platform_source`),
  aucun `offer_page_resolver` — la page n'est jamais lue. Un titre sans jeton de plateforme
  reste le skip fail-closed `[R27]`.
- **Verdicts sur les 821 lignes (2026-09-15)** : 430 passent le `precheck` (eu 258, us 115,
  global 57), 175 non-jeux, 137 sans région `[R47]`, 79 régions interdites (ROW 37, EMEA 19,
  NORTH AMERICA 6, TURKEY 4, CANADA 3, …). Tests : `tests/test_merchants_gameboost.py`.

## GamersOutlet (store 31, liste blanche safe-auto depuis le 2026-09-16)

- **Fichier** : `src/merchants/gamersoutlet.py`. Audité sur **la totalité du feed en attente
  du 2026-09-15** (20 lignes, une seule page — `runs/20260915-gamersoutlet`).
- **Grammaire PC** : `<Produit> [ (<OS>) ] ( <LIVRAISON> / <RÉGION> ) [ <qualificatif> ]`.
  Le slot est le **dernier groupe parenthésé contenant un `/`** — pas forcément en fin de
  titre (« Autodesk AutoCAD 2022 (Windows) (Lifetime/ Global) Commercial Version »), donc
  l'ancrage est le GROUPE. Livraison observée : « PC <Boutique> Key » 12/20 (Steam 6,
  Roblox 4, Rockstar 2) et « Lifetime License » / « Lifetime » 8/20.
- **`[R48]` le slot région est OBLIGATOIRE et son vocabulaire est fermé.** GamersOutlet écrit
  le mondial EXPLICITEMENT — « Global » au titre 20/20 et `-global` en fin de slug 20/20 — et
  ne laisse jamais le slot vide. Un titre muet n'a donc aucun sens prouvé chez ce marchand :
  il prendrait le GLOBAL implicite générique. Absence de slot, ou valeur hors vocabulaire
  partagé, = skip fail-closed. Coût aujourd'hui : 0 ligne sur 20 — la règle protège l'avenir.
- **`[R48]` la boutique acceptée et la plateforme lue sont LA MÊME donnée.** `STORE_PLATFORM`
  est la table du fichier ; `url_platform` la publie au matcher (le slug porte
  `-<boutique>-key-`, 12/12 des lignes clé). Toute boutique hors table est un skip « unknown
  store … never defaulted » — c'est là que s'arrêtent les 4 lignes Robux (`PC Roblox Key`), et
  c'est là que s'arrêteraient « PC EA Key » ou « PC Blizzard Key ». La revue adversariale du
  15/09 a montré qu'une liste recopiée à la main dérive de ce que `explicit_platform` rend
  vraiment : d'où la table unique.
- **Logiciels** (Adobe, CorelDRAW, Office, AutoCAD, Camtasia — 8/20) : livraison
  « Lifetime License », aucune boutique déclarée → route générique (contrôle plateforme de
  page R20/R27 puis le rattrapage logiciel `resolve_software_region`, R31). Jamais skippés ici.
- **Consoles** : aucune ligne dans le corpus. La porte livraison rend la main au classifieur
  partagé `[R45]` dès que la gauche nomme une console — **aucun hook console déclaré**.
- **Verdicts sur les 20 lignes** : 16 passent (toutes `global`), 4 skips « unknown store
  ROBLOX ». Tests : `tests/test_merchants_gamersoutlet.py`.
- **Statut live** : **allowlisté safe-auto le 2026-09-16**. 1re saisie le même jour — **2 / 2 créées** (Grand Theft Auto V
  Enhanced en Rockstar mondial 15, Polylithic en Steam mondial 2), prouvées par la disparition
  du feed. **Dans la liste blanche safe-auto depuis le 2026-09-16** (Romain : « On va whitelist
  Eletronicfirst et GamersOutlet ») ; `src/admin/auto_merchants.py` fait foi. Volume : la file complète du marchand fait ~19
  lignes dont 2 saisissables — surtout des licences logicielles absentes d'AKS et des recharges
  Roblox ; il faut attendre que la file se remplisse pour un lot de 10-15.

## Electronicfirst (store 70, liste blanche safe-auto depuis le 2026-09-16)

- **Fichier** : `src/merchants/electronicfirst.py`. Audité sur **323 lignes uniques**
  (feed complet, couverture prouvée — `runs/20260915-electronicfirst`).
- **Grammaire PC** — forme Kinguin, code région **en MAJUSCULES juste avant la phrase
  plateforme finale** : `<Jeu> [<Édition>] [DLC] [<RÉGION>[ (<note>)]] <Plateforme> <Livraison>`.
  Une seconde forme met le code en dernier, après la plateforme et sans mot de livraison
  (« Mortal Kombat: Legacy Kollection PS4 / PS5 UK »). Slot écrit sur 96 lignes : EU 71,
  US 10, RoW 4, FR 3, EU/NA 2, NA 2, EU/US/JP 1, UK/US 1, UK 1, EMEA 1. **Jamais un nom
  complet, jamais de minuscules.**
- **`[R49a]` clé EU partielle refusée** : 16 lignes portent une note collée au code — « EU
  (without DE) » ×13, « (without DE/NL/PL/AT) », « (without DE/NL/PL) », « (without FR, RU) ».
  AKS n'a pas de bucket « EU moins un pays » : la ligne n'est ni EU ni mondiale → skip.
- **`[R49b]` mot de région ÉPELÉ dans le nom avec slot vide refusé** : le slot est un CODE ;
  un titre qui écrit « Europe » dans son nom pendant que le slot est vide est ambigu et le
  scan générique minerait le mot du nom (« Big Adventure: Trip to Europe 9 » — 1 ligne).
- **`[R49c]` ligne CONSOLE sans slot refusée — il n'existe pas de SKU PSN / Xbox mondial.**
  C'est la règle porteuse, sortie de la revue adversariale du 15/09. Electronicfirst écrit la
  région sur **73 % de ses lignes console** contre 14,5 % de ses lignes PC : côté console le
  slot porte un vrai verrou, donc une console muette est bien plus probablement un verrou non
  écrit qu'un mondial. Laissées au GLOBAL implicite, 7 lignes partaient en monde entier, dont
  quatre jeux complets (Forza Motorsport, Forza Motorsport Premium, MSFS 2024 Premium Deluxe,
  Horror Adventure PS4/PS5). 18 lignes skippent aujourd'hui.
- **Lignes PC sans slot : GLOBAL implicite générique, mais À TITRE PROVISOIRE.** 227 lignes
  n'ont pas de code et le marchand n'écrit **aucun** mot mondial explicite (GLOBAL /
  Worldwide / WW : 0/323) — c'est la forme Kinguin / MMOGA. Mais contrairement à eux,
  Electronicfirst n'a **jamais été balayé**, donc la condition de validité est écrite et
  re-vérifiée à chaque lot : **le jour où une seule ligne écrit un slot qui résout à
  « global », le vide devient ambigu et le skip fail-closed `[R47]` s'applique à toutes les
  lignes muettes.** Le test `test_the_validity_condition_of_the_implicit_global` fige la
  mesure du 15/09 pour que ce jour-là la règle soit relue, pas conservée en silence.
- **Non-jeux** (21 lignes) : montant monétaire collé à un nombre (bons Lieferando, cartes PSN,
  recharges VALORANT), collocation « Game (e)Card » / « PSN Card » (jamais « Card » ni
  « Game » seuls — « Cards and Towers » et « Parkour Game 2 » sont de vrais jeux),
  abonnement (« PS Plus », « <N> Month(s) »), quantité de « Token(s) ». Logiciels (6) :
  portée de licence entre parenthèses « (2 PCs) », livraison « ISO Key » / « Bind Key »,
  préfixe « MS <produit> », segment d'URL `-lifetime-`.
- **Plateforme** : lecture générique du titre (`title_is_platform_source`, comme Kinguin) ;
  aucun hook console — la grammaire partagée lit seule les 75 lignes console, dont 8 Xbox
  Play Anywhere (« Xbox Series X|S / PC », « XBOX One / Xbox Series X|S / Windows 10 »).
- **Règle envisagée puis ÉCARTÉE** : un skip « trou de template » sur le double espace à la
  position du slot. Mesurée, elle est **inerte et bruitée** — des 5 lignes à double espace,
  2 portent déjà un slot, 2 ont le trou dans le NOM du produit (« Dakar Desert Rally-  Audi
  RS Q E-Tron… ») et la dernière est déjà refusée par `[R49c]`. Consigné pour qu'un audit
  ultérieur ne la repropose pas à l'aveugle.
- **Verdicts sur les 323 lignes** : 247 passent (eu 55, us 10, uk 1, 181 sans code), 18
  console sans slot `[R49c]`, 16 EU partielles `[R49a]`, 21 non-jeux, 14 régions interdites,
  6 logiciels, 1 `[R49b]`. Tests : `tests/test_merchants_electronicfirst.py`.
- **Statut live** : **1re saisie réelle le 2026-09-16 — 11 / 11 créées**, zéro échec, zéro
  arrêt, chacune prouvée par la disparition du feed : 4 lignes cross-gen Xbox One + Series
  (24eu / 302, 24us / 303), 1 Xbox Play Anywhere (MSFS 2024 Deluxe, 241 sur la page console ET
  la page PC), 1 Rockstar EU(152) débloquée le jour même par `[R50]`, 1 DLC EA App EU(3eu), et
  des lignes Steam / GOG / Publisher.
- **PARQUÉ le 2026-09-16** (Romain : « on mets ce marchant de cote pour le moment »).
  **Le défaut :** 2 des 11 offres sont parties en **PUBLISHER GLOBAL(1) au lieu de STEAM** —
  `Of Orcs and Men` (100401235) et `RoboCop: Rogue City - Collection` (100401259), corrigées à
  la main par Romain. Leur titre de feed est NU (ni plateforme, ni livraison, ni région) et
  l'URL n'est que le slug du nom, donc `detect_platform` rend le défaut ; `[R27]` laisse alors
  passer parce que la page AKS confirme « Direct Publisher » — ce qui ne dit rien de la clé de
  CE marchand. La page produit du marchand, seule source de vérité, est **Cloudflare-403**
  (UA navigateur comme UA neutre, vérifié le 16/09), donc aucun `offer_page_resolver` HTTP
  n'est possible. Le drapeau `offer_page_readable` (`[R32c]`) existe mais `src/matcher.py` ne
  le lit que pour les green gifts, pas dans la branche `[R27]`.
  **Chiffres pour la reprise :** 18 candidats PUBLISHER sur TOUS les runs sauvegardés, tous
  issus d'un titre nu (MMOGA 6, Electronicfirst 6, Gamivo 6) ; 2 360 lignes skippent déjà en
  « not defaulted (R27) ». Le trou n'est donc pas propre à ce marchand, et le refermer coûte au
  plus 18 lignes — dont certaines sont de vraies clés éditeur (`Minecraft - Java & Bedrock
  Edition` chez MMOGA). **FAIT le même jour — `[R51]`** : la branche `[R27]` ne
  résout plus un titre nu en PUBLISHER sur la seule foi de la page AKS ; le marchand doit
  déclarer qu'il lit sa propre page (`publisher_from_merchant_page`, défaut False) et aucun ne
  le déclare. Vérifié : les deux lignes sortent en skip « (R51) ». La décision revue
  d'`AGENTS.md` est mise à jour. Détail dans `src/merchants/electronicfirst.py`.

## Wyrel (store 162, liste blanche depuis le 24/09)

- **Fichier** : `src/merchants/wyrel.py`. Audité sur 100 lignes de la page 1 (16/09), trois
  lentilles puis trois contradicteurs. **60 pages de feed** — le plus volumineux de l'audit,
  et le plus lisible.
- **Grammaire** : un GABARIT À FENTES qui se lit intégralement depuis la fin, sans résidu
  (100/100) : `<Produit> [ "(" <TAG> ")" ] <ÉDITION> [ <PLATEFORME> ] <RÉGION> [ "Steam Gift" ]`.
  Région en NOM COMPLET (Global 53, Europe 19, United Kingdom 15, United States 12,
  Germany 1), édition obligatoire (Standard 95), fente plateforme (Other 48, Xbox One 7,
  PC 6, Xbox Series X/S 1, absente 38 — absente exactement quand le TAG vaut « PC »).
- **`[R53d]` les deux sources de région doivent CONCORDER.** L'URL répète la région en
  identifiant (`region=`) : bijection stricte sur le corpus, 1↔Global, 4↔Europe,
  8↔United States, 14↔United Kingdom, 19↔Germany, **zéro désaccord**. Aucun autre marchand
  ne nous donne une seconde source indépendante ; elle sert donc de CONTRÔLE et un désaccord
  prouvé est un skip. La comparaison porte sur les SENS, jamais sur les orthographes, et un
  identifiant hors table est toléré (il ne prouve rien).
- **`[R53b]` la fente plateforme « Other » EST le marqueur non-jeu** — c'est le mot du
  marchand pour « aucun appareil », donc le lire c'est lire sa déclaration, pas deviner. Le
  motif nomme le PRODUIT (GIFT CARD / WALLET / VOUCHER / CURRENCY), pas la fente, pour que le
  routage de listes fonctionne comme ailleurs. **Cette règle a été plus large pendant un
  jour, et les données l'ont resserrée** : sur les 100 lignes de la page 1, la revue exigeait
  TROIS signaux d'accord (fente « Other », pas de groupe `(<TAG>)`, `marketplace_id` hors
  {2, 8}), par crainte qu'une ligne « (PS5) … Other » soit un vrai jeu. La première tranche
  réelle (pages 1-10, **990 lignes**) a tranché les deux questions : `marketplace_id` ne
  sépare RIEN — l'identifiant 12 porte des lignes « Other » ET des lignes « PC » — et
  l'exiger produisait **98 faux refus** ; et un tag à côté de « Other » n'est pas une
  contradiction, les 4 lignes concernées sont de la MONNAIE de jeu nommant l'appareil
  (« eFootball 2023 12000 Coins (Xbox One) », « PUBG 11200 G COIN (PC) »). Sur 990 lignes la
  fente seule fait 228/228 non-jeux et ne touche aucune clé. Un audit qui ne lirait que la
  page 1 voudra rétablir la porte à trois signaux : elle a été mesurée fausse sur dix fois
  plus de données.
- **`[R53e]` le vocabulaire de la fente plateforme est OUVERT** (PC, Mac, Xbox One, Xbox
  Series X/S, PS4, PS5, Nintendo Switch, Switch 2…) et un mot inconnu est refusé PAR SON NOM.
  La page 1 sur 60 ne peut pas énumérer les appareils d'un marchand, et un « PS5 » non listé
  serait avalé par la fente ÉDITION en changeant le parse. Le départage se fait avec la
  seconde source : `edition_id` nomme l'édition, donc tout résidu que l'édition n'explique pas
  est une fente non déclarée.
- **`[R53c]` la fente ÉDITION passe si le vocabulaire partagé la MAPPE vraiment.** Mesuré sur
  990 lignes : « Standard » 700 → Standard(1) et « Deluxe Edition » / « Digital Deluxe » →
  Deluxe(7) doivent ENTRER ; « Collectors », « Zero », « Anniversary », « Classic » sont
  silencieusement APLATIS en Standard(1) par la lecture générique, ce qui classerait une
  édition collector sur le jeu de base — refusés en les NOMMANT.
- **Verdicts sur la tranche de 990 lignes (pages 1-10)** : **713 passent** vers la résolution
  AKS, 228 non-jeux nommés, 11 éditions non mappables. Le dry-run complet (matching AKS) sur
  la version précédente du fichier donnait 74 candidats ; il sera rejoué sur ces règles.
  Tests : `tests/test_merchants_wyrel.py` (24 tests).
- **Statut live** : **1re saisie réelle le 2026-09-17 — 15 / 15 créées, zéro refus**, chacune
  prouvée par la disparition du feed, arrêt propre sur la limite demandée. La grammaire
  `[R53]` tient donc en écriture réelle. Resté hors liste blanche safe-auto jusqu'au 24/09
  (le corpus ne couvrait que 10 pages sur 59). Dry-run de la tranche : 80 candidats sur 990 lignes — Steam 53,
  Xbox Series 13, Xbox One 11, Switch 2, Switch 2 ×1 ; 45 des 80 partent sous le compartiment
  **Steam Gift(25)**, la livraison que le marchand écrit en clair.
- **Liste blanche le 2026-09-24** (Romain : « Go Wyrel, corrige le motif, puis whitelist ce
  marchand »), **groupe B**, donc aussi dans le scan de nuit. Vérifié avant sur le scan
  tous-magasins du 21/09, **4 725 lignes** : la région du titre et le `region=` de l'URL
  concordent partout (17 identifiants, dont 5 = Rest of the world, 27 = Canada, 62 = Suède…).
  Verdicts de la grammaire : 3 428 passent vers la résolution AKS, 848 non-jeux nommés,
  213 éditions non mappables, 161 ROW, 73 verrous pays, 2 fentes plateforme inconnues.
- **« Rest of the world » (161 lignes, `region=5`) = `forbidden region: ROW`** (24/09).
  Avant, ce créneau manquait au vocabulaire partagé : le titre ne se lisait plus et la ligne
  tombait sur « no region slot » `[R53a]` — refusée, mais pour une fausse raison. Règle de
  Romain, même jour : **une ROW n'entre que si on prouve qu'elle s'active en Europe**, et ni
  le titre ni l'URL ne le prouvent. Enjeu mesuré au sitemap : 69 de ces lignes ont une page
  AKS (9 douteuses, 83 sans page).
- **Les pages Wyrel sont derrière Cloudflare** : lues depuis le navigateur du VPS le 24/09,
  une dizaine sont passées puis le défi « Performing security verification » ne s'est plus
  levé (4 pages de suite). Rien dans le fichier ne lit la page, et rien ne doit en dépendre :
  titre + URL suffisent, la seule inconnue étant la ROW, qui reste refusée.
- **La query de l'URL est l'identité de l'annonce (2026-09-24,
  `url_identity_params=("marketplace_id", "edition_id", "region")`).** Les variantes d'un
  produit partagent le chemin (« …-shores-unknown-pc-12345 ») et ne diffèrent que par
  `region=` / `edition_id=` / `marketplace_id=`. Chemin seul, la variante Global restée au feed
  faisait sortir la création de la variante Europe « STILL in feed » : **14 fausses erreurs le
  24/09** (AKS avait répondu « Offer created … feed entry deleted » pour les 14, aucune n'est
  réapparue). Ces trois paramètres rejoignent la clé d'identité ; `referal` et `coupon`, les
  mêmes partout, non (EXECUTOR_RULES §7).
- **Bilan du 24/09** (quatre lancements, trois arrêts passagers relancés à la main — la
  reprise automatique du même jour les aurait absorbés, EXECUTOR_RULES §14) : 2 790 lignes
  distinctes vues sur ~5 000, 117 candidats, **109 offres créées** (95 prouvées + 14 fausses
  « STILL in feed »). Les ~2 300 lignes jamais montrées tenaient au tri du feed, corrigé le même
  jour (`orderBy=id`).
- **`[R58]` « (PC) » sans boutique = Steam quand la page AKS ne vend QUE Steam** (Romain,
  2026-09-24 : « si on voit qu'il y a du Epic, du Ubisoft, du EA… on skip » ; « valable que
  pour Wyrel, dans sa config marchand »). Le crochet `pc_key_without_store` reconnaît
  « <Jeu> (PC) Standard <Région> » et « <DLC> (DLC) Standard PC <Région> », sans « Steam
  Gift » ; le `marketplace_id` n'y entre pas (il ne sépare rien). Sur les 418 lignes « (PC) »
  vues le 24/09 avec une page AKS : **217** sur une page « Steam » seul (elles peuvent entrer,
  si les autres contrôles passent), 180 sur une page qui vend aussi GOG, Epic, Ubisoft, EA,
  Microsoft, Xbox Play Anywhere ou l'éditeur (refusées, R27 / `[R51]`), 21 illisibles. (Un
  « NO GO » du même jour, sur une formulation antérieure, a été remplacé par cette règle.)

## Gamesplanet FR (store 55, `[R59]`, liste blanche le 25/09, groupe A)

- **Fichier** : `src/merchants/gamesplanet.py`. Revendeur OFFICIEL : titres nus (« Regulators »,
  « The Surge 2 - Premium Edition »), ni plateforme ni région.
- **Plateforme = le segment de livraison de l'URL**, écrit en clair avant l'identifiant :
  `…-steam-key--7963-1` (474 lignes sur 526 le 21/09), `-gog-key--` (12), `-epic-games-key--`
  (8), `-microsoft-store-download--` (16, famille « Windows 10 » R50), `-rockstar-key--` (3),
  plus Ubisoft / EA / Battle.net s'ils apparaissent. Un segment inconnu (`-arenanet-key--`,
  `-collection-download--`…) ou absent est refusé PAR SON NOM.
- **Région = la fiche produit** (HTTP 200, pas de Cloudflare). Sans bloc « REGION LOCK INFO », la
  clé n'est pas bridée ; sinon « It will NOT activate in: … » (liste courte en ligne, ou liste
  complète dans la fenêtre `#modal_regionlocks_details`) ou « It will ONLY activate in: … ».
  **Règle de Romain (25/09)**, sur les pays EXCLUS (pour « ONLY » : les absents) : ni UE, ni
  Royaume-Uni, ni USA exclus → GLOBAL ; UE autorisée, USA exclus → Europe ; un pays de l'UE exclu,
  USA autorisés → US ; UE et USA exclus → refus ; Royaume-Uni seul exclu → refus (non tranché) ;
  page illisible ou sans les repères d'une fiche → refus. Relevé sur 30 fiches : 12 sans bloc,
  16 « NOT » sans UE / UK / USA (Japon, Chine, Taïwan, ou 55 à 83 pays hors Europe), 2 « ONLY »
  Europe → 28 GLOBAL, 2 EU.
- **Essai à blanc du 25/09** (150 lignes tirées au hasard du scan du 21/09, AKS et fiches en
  direct, lecture seule) : **77 candidats** — Steam GLOBAL 62, Steam EU 10, Steam US 1, GOG GLOBAL
  3, Microsoft GLOBAL 1. Refus : 37 sans page AKS, 8 produit différent, 5 édition absente de la
  page, 4 verrou Gamesplanet, 3 bundles, 2 livraisons illisibles, 2 fiches illisibles…
  Tests : `tests/test_merchants_gamesplanet.py` (15, fiches réelles dans
  `tests/fixtures/gamesplanet/`), 6 mutations rougies.

## Discover.games (store 168, `[R60]`, fichier le 25/09 — pas encore en liste blanche)

- **Fichier** : `src/merchants/discover.py`. Boutique officielle à prix par pays : titre et URL
  NUS (« Potion Permit », `discover.games/games/<slug>`).
- **Tout vient de la fiche** (HTTP 200 après redirection vers `www.`), objet
  `sellableProductDetail` : `platform` (`STEAM`…) et `skus[].availableCountries`, les pays où
  chaque déclinaison est VENDUE (`["WW"]` = monde). Romain : « il faut vraiment lire la région
  sur la page » — c'est cette liste que la page affiche.
- **Région = règle de Romain `[R59]`** sur les pays NON couverts : `WW`, ou UE + UK + USA couverts
  → GLOBAL ; UE sans USA → EU ; USA sans l'UE → US ; sinon refus. AKS range déjà ainsi les
  boutiques officielles à prix par pays des mêmes pages (Fanatical, GamersGate, GMG, Humble,
  Steam : toutes en Steam GLOBAL, 15 pages lues le 25/09).
- **Produit introuvable** : fiche 404, sans `sellableProductDetail` ou sans déclinaison en vente
  → refus (« product not found »), jamais une région par défaut.
- **Essai à blanc du 25/09** (150 lignes du scan du 21/09, AKS et fiches en direct) : **106
  candidats** (Steam GLOBAL 104, Steam US 2). Refus : 21 sans page AKS, 15 fiches introuvables ou
  sans déclinaison, 3 produit différent, 2 verrou de région… Tests :
  `tests/test_merchants_discover.py` (11, extraits réels en `tests/fixtures/discover/`),
  5 mutations rougies.

## Ce qui n'est pas propre à un marchand

- Consoles (Xbox / PlayStation / Switch) `[R45]` (2026-09-12, hooks marchands le 14/09,
  écriture ouverte et défaut ON le 15/09) : classifieur partagé (`src/console_keys.py` —
  vocabulaire commun seulement, il interroge le registre pour les hooks du marchand), pages
  consoles AKS `buy-<slug>-<kind>-compare-prices/`, candidats multi-cibles (`targets`)
  écrits entiers sur le modal v2 (plafond 3 cibles) ; `--no-consoles` = run PC seul ;
  politiques P2-P5 à confirmer par Romain (EXECUTOR_RULES §4.12, §6, §10, §12).
- La correspondance texte de région → base vendable / label interdit (`EU` / `EUROPE` /
  `UNITED KINGDOM` / `Global`… ; `CA` → `CANADA`, `Hong Kong` → `HONG KONG`…) est du
  vocabulaire partagé : un fichier marchand fournit le TEXTE (`console_region_slot`), jamais
  la base.
- La liste blanche est contrôlée côté serveur (`rejection_reason`) : un marchand absent est
  refusé même si l'interface est contournée.

## Gamerall (store 13, marchand AKS 317, liste blanche safe-auto depuis le 2026-09-19)

Écrit le 2026-09-18 sur **783 lignes réelles** — pages 1-6 ET 26-31, pas une seule page. La
répartition est très inégale : la page 1 montre 11 % de lignes avec région, les pages 26-31 en
montrent **100 %**, l'ensemble 82 %. J'avais d'abord annoncé « 89 % sans région » d'après la
page 1 seule : c'était faux, et c'est la deuxième fois de la semaine qu'une page unique me fait
écrire une règle fausse (Wyrel, page 1 contre 990 lignes).

**Grammaire.** Le titre finit toujours par sa plateforme entre parenthèses — Steam 681, Xbox
Live 38, EA App 25, Ubisoft Connect 14, Nintendo Switch 7, PSN 4, Microsoft Store 3, GOG.com 2,
Epic Games 2, Rockstar 1 — et ne porte **jamais** de région. L'URL porte la plateforme (274
slugs sur 275) et, dans 82 % des cas, la région, dont le vocabulaire tient en trois mots :
`global` 514, `europe` 123, `usa` 6.

**Région absente ⇒ la page est ouverte** (arbitrage de Romain, 2026-09-18). Elle répond en 200
et porte sa région dans son JSON embarqué. Une page illisible, ou lisible sans région, est un
REFUS : jamais de repli sur GLOBAL, la règle qu'Instant Gaming s'est donnée après son audit #2.

**Deux correctifs de l'audit complet du soir même :**

- **Jeton Ubisoft.** Le fichier rendait `UPLAY`, un nom commercial que `REGION_IDS` ne connaît
  pas — tous les autres marchands normalisent en `UBISOFT`. Le matcher lisait `UBISOFT` dans le
  titre et `UPLAY` dans l'URL : les **14 lignes Ubisoft Connect** étaient refusées sur un faux
  « platform conflict », un refus mensonger et non lisible. Un test confronte désormais chaque
  jeton émis par ce fichier au vocabulaire du matcher.
- **Branche console.** Les lignes PSN / Nintendo Switch (11 lignes du corpus) n'ouvraient
  JAMAIS la page : la branche console du matcher ne consultait pas `offer_page_resolver` et
  tombait sur le GLOBAL implicite — l'inverse exact de la règle ci-dessus. Elle le consulte
  maintenant, pour la RÉGION seulement (la plateforme vient du classifieur console).

**Ordre de lecture : titre → URL → page**, du gratuit vers le coûteux (Romain : « mets un check
du titre par défaut avant d'ouvrir la page, ça reste plus opti »). Sur ce marchand le titre ne
donne rien aujourd'hui, 0 ligne sur 783 ; le crible existe pour le jour où ce feed changera
d'habitude, et parce que le contrat est le même pour tous les marchands.

**Premier matching** : 100 candidats sur 275 lignes (plafond atteint), **un seul refus de
grammaire**, 22 lignes perdues sur des sondages AKS instables. Première saisie de 10 offres le
jour même. Hors liste blanche tant qu'il n'a pas fait ses preuves.

**Deux défauts trouvés par les tests, pas en production** : la plateforme était cherchée par
simple présence dans le slug (la rubrique `steam-games-and-more` passait pour du Steam), et la
parenthèse de plateforme était cherchée ancrée en fin de titre — un titre portant une région ne
finit plus par elle, donc le crible du titre ne se serait jamais déclenché.
