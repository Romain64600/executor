# Marchands — configuration et règles par marchand

Un seul endroit pour répondre à « comment l'executor lit ce marchand ? ». Pour chaque
marchand de la liste blanche safe-auto (`src/admin/auto_merchants.py`) : identifiants,
grammaire du feed (titre / URL), hooks de la config marchand (`src/merchant_config.py`,
règle `[R32]`), règles spécifiques avec leur numéro dans `EXECUTOR_RULES.md`, statut
(éprouvé en data-entry auto ou non) et profil du feed résiduel. L'état courant du feed
(dernier passage, offres ajoutées, ce qui reste) est dans `docs/feeds/<Marchand>.md`,
régénéré par `scripts/14_feed_status.py`.

## Le contrat de config marchand (`MerchantConfig`)

Tout comportement générique du matcher peut être ajouté, surchargé ou modifié par le
fichier `src/merchants/<marchand>.py` (Romain, 2026-08-28 : « un fichier config par
marchand »). Champs disponibles :

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

**Consoles `[R45]` (2026-09-12) : aucun nouveau champ.** La classification console est
générique — `src/console_keys.py` (`classify_console`, `console_marker_in_url`,
`console_page_identity`) lit le titre ET l'URL, et la grammaire d'URL propre à chaque marchand
(catégories MMOGA, run Gamivo, segments Eneba, générique ailleurs) vit dans ce module, pas
dans la config marchand. Activation par `--consoles` (défaut désactivé) ; la saisie d'un
candidat multi-cibles est verrouillée dans le submitter tant que le nouveau modal n'est pas
observé (`EXECUTOR_RULES.md` §4.12 et §6).

Ce qui reste générique pour tous : pré-skips catégoriques (consoles, régions interdites,
prepaids, monnaies, bundles, skins, passes in-game, collections de DLC), résolution de la
page AKS par devinette de slug puis recherche AKS (R30, disjoncteur), gardes d'identité
R01 / R16 / R01b, DLC `[R43]`, éditions (R18, R39, R23), régions (§4.4, R44), plateformes
(R20), logiciels (R31), clés consoles `[R45]` (classifieur, pages consoles, cibles multiples —
sous `--consoles`), preuve de succès = disparition du feed.

## Statut au 2026-09-12

| Marchand | Store id feed | Config marchand | Éprouvé en safe-auto | Feed (pages) |
|---|---|---|---|---|
| Kinguin | 58 | générique | oui (142 pages d'historique + nuit du 11/09) | 67 |
| Gamivo | 51 | `gamivo.py` (4 hooks `[R46]` depuis le 12/09) | oui — 6 saisies fausses du 11/09 à corriger | 56 |
| G2A | 38 | `g2a.py` | oui | 37 |
| MMOGA | 12 (page AKS : marchand 40) | `mmoga.py` | oui (1 265 créées les 10-12/09) | 8-10 |
| K4G | 92 | générique | oui | 7 |
| Driffle | 127 | générique | oui | 6 |
| Instant Gaming | 28 | `instant_gaming.py` | oui | 4-5 |
| Eneba | 19 | `eneba.py` | **dry-run du 12/09 en cours** | ≥ 30 |
| Allyouplay | 17 | générique | **non, dry-run d'abord** | ? |
| GameSeal | 126 | générique | **non, dry-run d'abord** | ? |
| CJS-CDKeys | 30 | générique | **non, dry-run d'abord** | ? |
| Difmark | 167 | `difmark.py` | parqué (hors liste blanche) | — |

## Kinguin (store 58)

- **Feed** : filtré par l'URL `&store=58` (pas le menu déroulant) ; les URLs marchand
  gardent leurs `?params` (`nosalesbooster`, `currency`) tels quels (§4.6).
- **Grammaire** : `<Produit> [Édition] [Région] <Plateforme> CD Key`, ex. `Call of Duty:
  WWII - … DLC US PC Steam CD Key`. Plateforme lue dans le titre ; région souvent absente
  → **GLOBAL implicite** sauf région interdite présente (§4.4).
- **Config** : générique (pas de module).
- **Consoles (R45)** : plateforme dans le titre, juste avant `CD Key` (`Xbox One / Xbox Series
  X|S`, `Xbox Series X|S / PC`, `PS5`, `PS4/PS5`, `Nintendo Switch`, `Nintendo Switch 2`) ; la
  région (code 2 lettres) est AVANT la plateforme ; `… Account` / `… Access` (URL `-account` /
  `-online-account-activation`) = non-jeu → skip. Le slug de l'URL reflète le titre
  (`-eu-xbox-one-xbox-series-x-s-cd-key`), sans segment de catégorie. Dernier lot : **365
  consoles / 940 lignes** — One+Series 211, Series 79, PS5 16, PS4/PS5 15, Switch 13, Switch 2
  12 (pas de bucket AKS → skip) ; **CA 83 / AU 77** en région interdite (skip avant toute
  résolution).
- **Résiduel** : consoles, bundles, monnaies, titres sans page AKS, variantes d'édition.

## Gamivo (store 51)

- **Grammaire `[R46]` (2026-09-12)** : titre `<Jeu> [<Édition>] [<LANG>(/<LANG>)*] <Région>` —
  la région est une queue SANS séparateur, précédée ou non de codes langue majuscules
  (`Ravenswatch EN United Kingdom`, `Tiny Tina's Wonderlands United States`, `FIFA 23
  EN/PL/CS/RU/TR EU`, `KIBORG EN Colombia`, `Storebound ROW`) ; le titre ne nomme JAMAIS la
  plateforme. URL `gamivo.com/product/<slug>-<run plateforme>-<cc>[-<langues>]-<édition>` : le
  run plateforme (`pc-steam`, `steam`, `pc-steam-gift`, `steam-gift`, `pc-ea-app`, `origin`,
  `pc-ubisoft-connect`, `pc-battlenet`, `battle-net-gift`, `pc-gog`…) est ENTRE le slug et le
  code région, l'édition vient APRÈS le code (`tiny-tinas-wonderlands-pc-steam-us-standard`) ;
  variante avec `-pc` en fin (`…-steam-eu-standard-pc`). Lot du 12/09 (1 000 lignes) : queues
  United Kingdom 372, Colombia 310, Global 70, EU 64, United States 46, ROW 45, Canada 18,
  Netherlands 12, Australia 8, North America 6, Turkey 6, CIS 3, Poland 3, Asia 2, Mexico 2,
  22 sans queue (abonnements, cartes, logiciels) ; runs d'URL : consoles 802, Steam 115, EA 5,
  Battle.net 4, Ubisoft 1, GOG 1, 72 sans run. Un segment `-en-` / un code `EN` est un marqueur
  de langue, pas une région (MA7 retirée le 2026-09-01) ; les verrous de l'ancienne grammaire
  (`…-steam-key-brazil`, `…-steam-key-ru`) restent détectés par les scans génériques (P2-6,
  P2-6b).
- **Config** : `gamivo.py` — quatre hooks `[R32e]`, fonctions pures de la ligne de feed :
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
- **Consoles (R45)** : le titre ne porte JAMAIS la plateforme (569 des 572 lignes consoles du
  dernier lot ne sont détectables que par l'URL) ; run d'URL après le slug : `xbox-xbox-series` /
  `xbox-series` / `xbox-xboxseries` → Series ; `xbox-xbox-one-series` / `xbox-xboxoneseries` /
  `xbox-one-series` → One+Series ; `xbox-xboxone` → One ; suffixe `-pc` / `-windows` / `…windows`
  fusionné → PC déclaré ; `xbox-pc` seul → skip « PC-only Xbox Live key » ; `ps-ps5` / `psn-ps5`
  → PS5 ; `nintendo-nintendo-switch` → Switch ; région = queue « EN <Pays> » du titre / code pays
  de l'URL avant le jeton d'édition. Dernier lot : **572 / 762** — Series 333, One+Series 207 ;
  **United Kingdom 258, Colombia 203**. **Fuite corrigée (2026-09-12)** : le garde console ne
  lisait que le titre → « Riders Republic Premium Edition United States »
  (`…/riders-republic-xbox-xbox-one-series-us-premium`, run
  `20260911-162100-auto-gamivo-s51-p28`) a été saisi PUBLISHER GLOBAL Premium sur la page PC
  (AKS 50562) — **à corriger à la main** ; `console_marker_in_url` (actif dans tous les modes)
  ferme la brèche.
- **Résiduel** : 77 % « sans page AKS » sur les pages hautes (titres `<Jeu> EN United
  States`), régions interdites, restrictions de langue.

## G2A (store 38)

- **Grammaire** : le titre n'est **pas fiable** pour la plateforme ; elle se lit dans le
  slug de l'URL (`title_is_platform_source=False`, `url_platform_scan=True`) `[R32b]`.
  « Green Gift » est un mode de livraison, pas un produit (le mot GREEN n'est pas un mot en
  trop, R38).
- **Config** : `g2a.py`. `offer_page_readable=False` : G2A renvoie 403 aux requêtes HTTP
  hors navigateur, donc une plateforme lisible seulement sur la page de l'offre reste
  invérifiable → skip fail-closed `[R32c]`.
- **Consoles (R45)** : écrit « X/S » (`(Xbox Series X/S)`, `(Xbox Series X/S, PC)`, `Xbox One,
  PC` sans parenthèses, `(PS5)`, `(Nintendo Switch 2)`), magasin ` - Xbox Live Key - ` / ` - PSN
  Key - ` / ` - Nintendo eShop Key - `, région en queue (` - EUROPE`, ` - UNITED KINGDOM`…) ;
  **One et Series sont des lignes séparées** (One+Series : 1 ligne sur 1 544 toutes runs). URL
  `<slug>-xbox-series-x-s[-pc]-xbox-live-key-<région>-i<id>` (`url_platform_scan` déjà actif
  pour le PC). Dernier lot : **42 / 806**.
- **Résiduel** : fort bruit hors jeux (2-3 % de rendement historique) : CIS / ROW / Turquie /
  Allemagne, monnaies, gift cards, skins.

## MMOGA (store 12, marchand 40 sur les pages AKS)

- **Grammaire** : `mmoga.com/<Plateforme>-Games/<Produit>[-<CODE>-Key].html?ref=<affid>`.
  Plateforme = segment de catégorie de l'URL (`Steam-Games` → STEAM, `EA-Games` → EA, GOG,
  Epic, Ubisoft/Uplay, Rockstar, Battle.net/Blizzard, Windows → MICROSOFT ; `Xbox-Live`,
  `Playstation-Network`, `Nintendo` → console). Région = code 2 lettres **majuscules**
  juste avant le `Key` final (`Borderlands 2 EU Key` → EU ; `Among Us Key` → global), ou
  après le mot Key entre crochets / parenthèses (`(Steam Key EU)`, `[EU]`, `(EU)` pour un
  code connu seulement — `(PC)` n'est pas une région).
- **Config** : `mmoga.py` — `domain`, `url_platform_prefixes`, `precheck` (code interdit
  RU/TR/BR/AR/CN/KR/JP/PL/UA/MX/PH/VN/TH → `forbidden region: <LABEL>`, code inconnu →
  skip fail-closed), `title_region` (EU/US/UK/GB → région autoritaire), `resolve_name`
  (retire la queue de région avant la devinette de slug) `[R32e]`.
- **Historique** : onboardé le 2026-09-10 directement en safe-auto (décision Romain) ; les
  DLC / Season Pass sont saisis sur leur page AKS propre depuis le 2026-09-11 `[R43]`.
- **Consoles (R45)** : plateforme dans le titre, en parenthèses ou après un tiret (`(Xbox One /
  Series X|S Download Code) - EU`, `(Xbox Series X|S Download Code)`, `Xbox Series X|S / Windows`,
  `- PS5 Download Code [EU]`, `- Nintendo Switch Download Code`) ; catégorie d'URL
  `Xbox-Live/Xbox-One-Game-Keys`, `Xbox-Live/Xbox-Series-XS-Game-Keys`,
  `Playstation-Network/Playstation-5-Game-Keys`, `…/Playstation-4-Game-Keys`, `Nintendo/Switch` —
  la catégorie ne donne que la génération BASSE (un cross-gen « Xbox One / Series X|S » est classé
  sous `Xbox-One-Game-Keys` ; c'est le titre qui déclare les deux) ; `Xbox-Live/Xbox-360-Game-Keys`
  → skip ; cartes / abonnements (`PSN-Cards-*`, `Nintendo-eShop-Cards`, `Playstation-Plus`,
  `Xbox-Live-Cards`, `Xbox-Live-Gold`) → non-jeu. Dernier lot : **388 / 723** — One+Series 149,
  Series 89, Switch 63, One 35, PS5 10, non-jeu 85 ; queue région EU 240 (` - EU` 188, `[EU]` 44,
  `EU Key` 5, `[EU Key]` 3).
- **Résiduel** : 388 consoles (R45 préparé — `--consoles` désactivé par défaut, saisie
  multi-cibles en attente du nouveau modal ; dry-run à faire), 157 sans page AKS, bundles,
  monnaies, passes, variantes d'édition.

## K4G (store 92)

- **Grammaire** : `<Produit> [Édition] [Région] <Plateforme> CD Key` **sans** parenthèses ni
  tirets séparateurs (`Monster Hunter Wilds Gold Edition Europe Steam CD Key`) ; la
  devinette de slug pèle les phrases finales plateforme / région
  (`_TRAILING_NOISE_PHRASES`) et les tirets internes sont ceux du nom du produit.
- **Config** : générique. Pagination `&p=N`.
- **Consoles (R45)** : `<Jeu> [Édition] <Région> <Plateforme> CD Key` — `XBOX One/Series X|S`
  45, `XBOX Series X|S` 25, `PC/XBOX One/Series X|S` 9, `PC/XBOX Series X|S` 5, `PS5` 8,
  `PS4/PS5` 1, `Nintendo Switch` 13, `Nintendo Switch 2` 13 (dernier lot) ; région en toutes
  lettres avant la plateforme (Europe 75, United States 31) ; URL
  `/product/<slug>-<plateforme>-<région>-…-cd-key-<8 car.>` (`xbox-one-series-x-s`,
  `xbox-series-x-s`, `pc-xbox-one-series-x-s`, `nintendo-switch(-2)`, `playstation-5`,
  `ps4-ps5`). Dernier lot : **135 / 592**.
- **Résiduel** : ~25 % de consoles, sans page AKS.

## Driffle (store 127)

- **Grammaire** : `<Produit> (<Région>) (PC) - <Plateforme> - Digital Key` ; la région est
  dans la première parenthèse (Ga01) ; `stock` = `y`/`n`.
- **Config** : générique. Feed dynamique → re-scan avant chaque submit (règle générale).
- **Consoles (R45)** : plateforme dans la 2e parenthèse — `(Xbox Series X|S)` 33, `(Xbox One /
  Xbox Series X|S)` 28, `(Xbox One)` 10, `(PS4 / PS5)` 8 + `(PS4/PS5)` 2, `(PS5)` 5, `(PS4)` 5,
  `(Nintendo Switch)` 5, `(Nintendo Switch 2)` 1, `(PC / Xbox …)` = PC déclaré — magasin ` - Xbox
  Live - ` / ` - PSN - ` / ` - Nintendo - ` ; région dans la 1re parenthèse (Global 42, Europe 41,
  United States 16). L'URL écrit **`xbox-series-xs`**
  (`-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p…`, `-ps4-ps5-psn-digital-key-`).
  Dernier lot : **112 / 464**.
- **Résiduel** : sans page AKS, consoles, bundles, monnaies, DLC sans page propre.

## Instant Gaming (store 28)

- **Grammaire** : titres **sans aucun jeton** (une clé Steam ressemble à un simple
  `<Produit>`), la région n'est pas dans le feed.
- **Config** : `instant_gaming.py` — `offer_page_resolver=ig_offer_signals` : la page
  marchande de l'offre est lue **une fois** (`data-platform` → plateforme, suffixe du
  `<title>` → région) `[R32]` / `[R33]` ; une région non vendable renvoie
  `forbidden region: <label>` avec le routage habituel.
- **Historique** : un sweep entier saisi avec une mauvaise région avant R33 (2026-08-13,
  corrigé) ; propre depuis.
- **Consoles (R45)** : la plateforme n'est PAS dans le feed (titres nus, URL `/en/<id>-/`) — elle
  vient de la page IG (`offer_page_resolver`) ; le classifieur R45 ne voit que les marqueurs du
  titre (dernier lot : 8 lignes, 7 Game Pass + 1 « Nintendo Switch 2 Edition »). Hors périmètre
  console en v1.

## Eneba (store 19)

- **Grammaire** : le titre omet souvent la plateforme ; l'URL commence par le segment de
  plateforme (`eneba.com/steam-<slug>`, `gog-`, `epic-`, `uplay-` → UBISOFT, `origin-` →
  EA, `blizzard-` → BATTLENET, `windows-` → MICROSOFT) `[R29]`. Région dans le titre quand
  elle existe (`… Steam Key (PC) EUROPE`, `UNITED STATES`), sinon GLOBAL implicite. Titres
  avec caractères Unicode compatibilité (« Ⅱ ») → NFKC avant identité.
- **Config** : `eneba.py` — `url_platform_prefixes`.
- **Consoles (R45)** : `<Jeu> [(<Plateforme>)] XBOX LIVE Key <RÉGION>` — la région vient APRÈS
  le marqueur de clé (EUROPE 730, UNITED STATES 626) ; `(Xbox Series X|S)` 299,
  `(Windows/Xbox Series X|S)` 179 (PC déclaré), `PC/XBOX LIVE Key` 172 (clé PC vendue via Xbox
  Live → skip « PC-only ») ; URL : segment de tête `xbox-` / `psn-` / `nintendo-` (préfixe de
  magasin, PAS une génération : `xbox-one-last-breath-…`), puis `-xbox-series-x-s-xbox-live-key-`,
  `-windows-xbox-series-x-s-`, `-ps4-ps5-`, `-nintendo-switch(-2)-`. Dernier lot : **1 376 / 1 659
  lignes consoles, dont 704 « XBOX LIVE Key » sans génération** (ni titre ni URL) → skip
  « console: no declared generation (R45) » (politique P4, à confirmer par Romain).
- **Statut** : dry-run du 2026-09-12 (voir CHANGELOG) ; très fort taux de consoles (pages
  entières) et de régions interdites.

## Allyouplay (17), GameSeal (126), CJS-CDKeys (30)

- Dans la liste blanche mais **jamais balayés** : pas de module, pas d'historique. Un dry-run
  (`scripts/10 … --dry-run`) est exigé avant tout sweep réel (Romain, 2026-09-11).
- **Consoles (R45)** : aucune donnée pour Allyouplay et CJS ; GameSeal (sweep de juillet 2026,
  33 / 1 610) écrit `(<Plateforme>) <Store> Key - <RÉGION>` (`(Xbox One / Xbox Series X|S) Xbox
  Live Key - EU`), URL `<slug>-xbox-one-xbox-series-x-s-xbox-live-key-eu` (grammaire générique).

## Difmark (167, parqué)

- **Grammaire** : titres nus `<Nom> Standard Edition` ; chaque URL porte un segment
  `buy-console-account-` boilerplate, retiré avant tout signal (`url_ignore_substrings`),
  jamais un motif de skip. Plateforme et région lues sur la page de l'offre
  (`resolve_difmark_offer`). Hors liste blanche safe-auto.

## Ce qui n'est pas propre à un marchand

- Consoles (Xbox / PlayStation / Switch) `[R45]` (2026-09-12) : classifieur générique
  (`src/console_keys.py`), pages consoles AKS `buy-<slug>-<kind>-compare-prices/`, candidats
  multi-cibles (`targets`), activation `--consoles` (défaut désactivé), submit verrouillé
  (`multi_target_unsupported_until_modal_verified`) tant que le nouveau modal de Romain n'a pas
  été observé avec `--inspect` ; politiques P1-P5 à confirmer par Romain (EXECUTOR_RULES §4.12,
  §6, §10, §12).
- La liste blanche est contrôlée côté serveur (`rejection_reason`) : un marchand absent est
  refusé même si l'interface est contournée.
