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

Ce qui reste générique pour tous : pré-skips catégoriques (consoles, régions interdites,
prepaids, monnaies, bundles, skins, passes in-game, collections de DLC), résolution de la
page AKS par devinette de slug puis recherche AKS (R30, disjoncteur), gardes d'identité
R01 / R16 / R01b, DLC `[R43]`, éditions (R18, R39, R23), régions (§4.4, R44), plateformes
(R20), logiciels (R31), preuve de succès = disparition du feed.

## Statut au 2026-09-12

| Marchand | Store id feed | Config marchand | Éprouvé en safe-auto | Feed (pages) |
|---|---|---|---|---|
| Kinguin | 58 | générique | oui (142 pages d'historique + nuit du 11/09) | 67 |
| Gamivo | 51 | `gamivo.py` (vide depuis MA7) | oui | 56 |
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
- **Résiduel** : consoles, bundles, monnaies, titres sans page AKS, variantes d'édition.

## Gamivo (store 51)

- **Grammaire** : la région est dans l'**URL** (`…-steam-global`, `-eu`, `-gift-eu`,
  `-us`, un code pays en position finale), jamais dans le titre `[GAMIVO]` ; un segment
  `-en-` est un marqueur de langue, pas une région (MA7 retirée le 2026-09-01) ; les
  verrous de région encodés seulement dans l'URL sont détectés (P2-6, P2-6b).
- **Config** : `gamivo.py` = `MerchantConfig("Gamivo")`, aucune règle propre restante.
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
- **Résiduel** : 388 consoles (en attente de l'outil AKS feed multi-plateforme), 157 sans
  page AKS, bundles, monnaies, passes, variantes d'édition.

## K4G (store 92)

- **Grammaire** : `<Produit> [Édition] [Région] <Plateforme> CD Key` **sans** parenthèses ni
  tirets séparateurs (`Monster Hunter Wilds Gold Edition Europe Steam CD Key`) ; la
  devinette de slug pèle les phrases finales plateforme / région
  (`_TRAILING_NOISE_PHRASES`) et les tirets internes sont ceux du nom du produit.
- **Config** : générique. Pagination `&p=N`.
- **Résiduel** : ~25 % de consoles, sans page AKS.

## Driffle (store 127)

- **Grammaire** : `<Produit> (<Région>) (PC) - <Plateforme> - Digital Key` ; la région est
  dans la première parenthèse (Ga01) ; `stock` = `y`/`n`.
- **Config** : générique. Feed dynamique → re-scan avant chaque submit (règle générale).
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

## Eneba (store 19)

- **Grammaire** : le titre omet souvent la plateforme ; l'URL commence par le segment de
  plateforme (`eneba.com/steam-<slug>`, `gog-`, `epic-`, `uplay-` → UBISOFT, `origin-` →
  EA, `blizzard-` → BATTLENET, `windows-` → MICROSOFT) `[R29]`. Région dans le titre quand
  elle existe (`… Steam Key (PC) EUROPE`, `UNITED STATES`), sinon GLOBAL implicite. Titres
  avec caractères Unicode compatibilité (« Ⅱ ») → NFKC avant identité.
- **Config** : `eneba.py` — `url_platform_prefixes`.
- **Statut** : dry-run du 2026-09-12 (voir CHANGELOG) ; très fort taux de consoles (pages
  entières) et de régions interdites.

## Allyouplay (17), GameSeal (126), CJS-CDKeys (30)

- Dans la liste blanche mais **jamais balayés** : pas de module, pas d'historique. Un dry-run
  (`scripts/10 … --dry-run`) est exigé avant tout sweep réel (Romain, 2026-09-11).

## Difmark (167, parqué)

- **Grammaire** : titres nus `<Nom> Standard Edition` ; chaque URL porte un segment
  `buy-console-account-` boilerplate, retiré avant tout signal (`url_ignore_substrings`),
  jamais un motif de skip. Plateforme et région lues sur la page de l'offre
  (`resolve_difmark_offer`). Hors liste blanche safe-auto.

## Ce qui n'est pas propre à un marchand

- Consoles (Xbox / PlayStation / Switch) : étude faite, chantier en attente de l'outil AKS
  feed multi-plateforme (EXECUTOR_RULES §4.3 « Console keys — PARKED »).
- La liste blanche est contrôlée côté serveur (`rejection_reason`) : un marchand absent est
  refusé même si l'interface est contournée.
