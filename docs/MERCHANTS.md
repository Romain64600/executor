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
| `gift_delivery(name, url)` | **`[R32e]` (2026-09-14)** — le verdict « livraison gift » propre au marchand, superposé par `detect_region` comme bucket GIFT de la plateforme (Steam 25 / gift_eu 259, Battle.net 570 / 567 ; pas de gift_us / gift_uk → skip fail-closed « no region id ») : True / False l'emporte, None → lecture générique (segment d'URL `gift`, « GIFT » dans le titre). K4G / Kinguin « … Steam Altergift » dont le slug est d'accord → True (Romain 14/09 : « on rentre sous gift tous les altergifts ») ; le hook lit ses DEUX arguments : un conflit titre / URL (titre Altergift, slug `-cd-key`) ou un Altergift hors Steam n'est jamais un verdict — c'est le skip fail-closed du `precheck` marchand (correctifs de revue 14/09) | lecture générique |
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
| GameSeal | 126 | `gameseal.py` (**nouveau**) | `domain` ; PC : `precheck`, `title_region` (queue ` - <RÉGION>`) ; console : `console_url_families`, `console_region_slot` | **non, dry-run d'abord** | ? |
| CJS-CDKeys | 30 | `cjs.py` (**nouveau**, identité seule) | `domain="cjs-cdkeys.com"` (à confirmer au 1er dry-run) — aucun hook de grammaire (aucune donnée) | **non, dry-run d'abord** | ? |
| Difmark | 167 | `difmark.py` | `console_url_families` (comptes) | parqué (hors liste blanche) | — |

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
- **Statut live** : dans la liste blanche mais **jamais balayé en safe-auto** ; dry-run
  d'abord (Romain, 2026-09-11).

## CJS-CDKeys (store 30)

- **Fichier** : `src/merchants/cjs.py` (**nouveau, 2026-09-14**, identité seule : store 30,
  `CONFIG.name = "CJS-CDKeys"` (orthographe de la liste blanche), `domain="cjs-cdkeys.com"` —
  à confirmer au premier dry-run ; un hôte faux fait échouer fermé, jamais une saisie).
- **Grammaire PC / console** : **aucune donnée** — jamais balayé, pas d'historique ; même
  logique qu'Allyouplay : le fichier porte la règle et recevra la grammaire relevée au
  dry-run, rien n'est inventé d'ici là.
- **Hooks** : `domain` seul.
- **Statut live** : dans la liste blanche mais **jamais balayé** ; dry-run exigé avant tout
  sweep réel (Romain, 2026-09-11).

## Difmark (167, parqué)

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
- **Statut live** : parqué (hors liste blanche).

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
