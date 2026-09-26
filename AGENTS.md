# AKS Controlled Executor — Codex instructions

## Mission

You are Codex CLI working as a builder, not as a free-form executor.

Your job is to build a deterministic AKS controlled executor.

You may:
- write scripts;
- write tests;
- audit logs;
- improve docs;
- run read-only diagnostics;
- propose implementation plans.

You must not:
- manually submit AKS offers through ad-hoc browser actions;
- improvise browser workflows;
- bypass validation;
- use Browserbase;
- use Playwright fallback;
- launch VPN;
- self-trigger or automate the session re-auth (AKS is social-login only now,
  so re-auth is COOKIE TRANSFER — `docs/LOGIN_SPEC.md`,
  `src/admin/login_manager.py` — driven only by Romain's explicit submit in
  the console; a `NotLoggedInError` from another stage stays a fail-closed STOP,
  never a re-auth trigger).

## Known infrastructure

Host Chrome CDP:
http://127.0.0.1:9222/json/version

Docker bridge CDP proxy:
http://172.17.0.1:9223/json/version

Official endpoint for code running from Docker bridge:
http://172.17.0.1:9223/json/version

Required User-Agent:
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36

AKS direct URL:
https://www.allkeyshop.com/blog/

## Forbidden

- Browserbase
- browser_navigate for AKS execution
- Playwright fallback
- VPN fallback when AKS direct works
- /root/start-chromium.sh
- random 0.0.0.x CDP checks
- submitting without explicit validation file
- submitting without modal context verification
- fire-and-forget submission
- using old candidates from memory
- using previous feed state
- self-triggering the session re-auth (cookie transfer, `docs/LOGIN_SPEC.md` —
  Romain's explicit submit in the console only)
- changing process after Romain says "go"

## Required architecture

The deterministic, per-stage rules (extractor, matcher, submitter, post-save
verification, reporting) derived from the `aks-data-entry` skill are specified in
`docs/EXECUTOR_RULES.md`. Read and follow it when implementing any stage; it is
the authoritative bridge between the skill and this code.

Build in stages:

1. Environment audit script.
2. Read-only feed extractor.
3. Read-only matcher.
4. Candidate report generator.
5. Validation file generator.
6. Submitter locked behind validation.
7. Post-save verifier.
8. JSONL logs for every action.
9. Dry-run mode by default.

Session re-auth (`docs/LOGIN_SPEC.md`, `src/admin/login_manager.py`): AKS
disabled password login (social/OAuth only), so re-auth is COOKIE TRANSFER —
Romain completes the social login in his own browser and pastes the WP session
cookies into the console, which injects them (official CDP only) and proves the
session. The one flow that touches session secrets: cookie VALUES are never
logged/echoed/stored, injection is restricted to `allkeyshop.com`, Romain's
explicit submit only. Never self-triggered: a `NotLoggedInError` from another
stage stays a fail-closed STOP + error report.

## Fail-closed behavior

If anything is uncertain:
- stop;
- write an error report;
- do not fallback to another browser;
- do not continue to next candidate;
- do not submit.

## Submission constraints

The submitter must only process candidates from a validation JSON file.

For each candidate:
- refresh current merchant feed;
- locate exact current row;
- verify title, URL, merchant/store (price is a routing signal, never a
  blocker after URL/store confirm; page is recomputed by the current scan —
  EXECUTOR_RULES §6);
- open modal from that row;
- verify modal context;
- fill visible region/edition controls;
- click official visible submit button;
- refresh feed;
- verify post-save state: success = the offer disappeared from the refreshed
  feed, same available mode as the run.

No degraded mode.

## Coding preferences

- Python 3.
- Minimal dependencies.
- No new production dependency without asking Romain.
- **`node` is an approved TEST-ONLY dependency (Romain, 2026-09-17: « Installe node pour les
  tests JS »).** Debian package `nodejs` (20.x), standard library only — no npm install, no
  `package.json`, no lockfile, nothing added to the runtime or to the VPS write path. It
  exists so the browser console (`src/admin/static/*.js`) is EXECUTED by its tests instead of
  being spell-checked: `tests/js/` holds a stubbed DOM + a hand-released `fetch`, and
  `tests/test_console_js_simulation.py` runs it and SKIPS cleanly where node is absent. Do not
  extend it into an npm toolchain, and do not make any production stage depend on it.
- Scripts must be CLI-friendly.
- Outputs should be JSON or JSONL where practical.
- Human reports go in Markdown.
- Never store passwords, 2FA codes, or session cookies.
- Never commit secrets.

## Reviewed decisions — do NOT re-tighten (an audit will re-flag these)

These are deliberate, Romain-reviewed calls. An adversarial audit re-derives them as
"findings" every time; leave them AS-IS unless Romain explicitly changes his mind.

- **Chemin by-urls : l'index de localisation EST remplacé par la preuve après chaque création —
  laisser tel quel (audit complet du 2026-09-18, constat écarté).** Sur `--locate-by-search`
  les deux drapeaux sont vrais, donc `keep_index` vaut False et l'index bâti par
  `_index_by_search` (3 tentatives par candidat) est remplacé par les 0-1 lignes de la recherche
  de preuve. Le fait est exact ; il est DÉLIBÉRÉ. Sur ce chemin chaque offre est localisée par SA
  PROPRE recherche (`_relocate_by_url` re-cherche), il n'y a pas de fenêtre de page à préserver,
  et `test_by_urls_path_still_refreshes_its_index_from_the_search` épingle le comportement. Aucun
  effet sur la justesse — seulement du travail refait. Un audit le re-trouvera en citant le
  commentaire qui le précède : ne pas retourner une décision testée pour une économie non mesurée.

- **R01 : l'apostrophe est REPLIÉE, les mots-outils NON (audit complet du 2026-09-18).** Le repli
  de l'apostrophe dans `tokenize` est acquis (« Assassins Creed » couvre « Assassin's Creed ») —
  il ne peut faire matcher que des noms qui SIGNIFIENT la même chose. La seconde moitié du même
  constat — retirer THE / OF / AND du côté REQUIS, ou plier `&` en `AND` — a été délibérément
  abandonnée : elle, elle relâcherait l'identité. Un audit reproposera le paquet entier ; ne
  reprendre que la moitié déjà faite.

- **Une offre ÉPUISÉE (stock `n`, prix `0`) est une offre à SAISIR — Romain, 2026-09-21.** Sa
  ruling, après avoir regardé les lignes que l'audit GameSeal avait signalées : « à part le
  fait que ce soit out of stock, je vois pas d'erreurs. C'est peut-être des offres qui vont
  restocker à l'avenir. Vu que c'est dans leur feed en pending offers, vaut mieux les avoir au
  cas où, un jour, ils restockent. » C'est la même logique que le retrait de R25 : une offre
  PENDING est à ajouter, point. Le code est déjà d'accord — ni le stock ni le prix ne
  conditionnent quoi que ce soit dans `src/matcher.py` / `src/submitter.py` (le prix reste un
  signal de routage, jamais un bloqueur, EXECUTOR_RULES §6). Un audit « trouvera » ces lignes
  (le balayage GameSeal du 19-20/09 en a écrit 62 à prix `0`) et voudra un skip « offre
  épuisée » ou un garde « prix nul » : NE PAS l'ajouter.

- **[R18b] R18 se RETIRE quand le titre annonce un palier que la page ne nomme pas (2026-09-20,
  « le correctif que tu veux » — CONFIRMÉ le 2026-09-21 sur le cas concret, « garde ta règle »,
  après que Romain a lui-même écarté la lecture « ça rentre quand même » qui lui était proposée
  en regard de son ruling sur les offres épuisées).** R18 reste le SEUL juge du seau DLC(16) — la décision du
  17/09 est intacte : un titre sans marqueur sur une page mono-seau DLC entre en DLC(16). La
  seule exception ajoutée : si le titre marchand annonce un PALIER (Deluxe / Ultimate / Gold /
  Complete, lu par `detect_edition`) que le NOM DE LA PAGE AKS ne porte pas, R18 laisse la
  main — le marchand vend un SKU plus large que la page, et la vérification de page (P1-1)
  refuse. Déclencheur : « Call of Duty: Black Ops III Zombies Chronicles Deluxe Edition »
  (offre 100700366) écrite DLC(16) sur la page du DLC seul. Mesure avant application sur
  1 818 lignes écrites : 43 en DLC(16), 10 sans marqueur, UNE bascule — la fausse. Un audit
  « trouvera » que R18 a été affaibli (« un vrai DLC dont le titre dit Deluxe n'entre plus »)
  : il entre toujours si la page nomme le même palier (« Wortox Deluxe Chest »), et sinon
  c'est un refus, jamais une écriture fausse. Ne pas restaurer la préséance inconditionnelle.

- **Le disjoncteur de recherche R30 EXPIRE au bout de 30 min (2026-09-20, même GO).** Le
  commentaire de `scripts/03_match.py` a longtemps dit « sweep-scoped and has no expiry
  (Romain 2026-09-10) » — un audit qui relira le git voudra restaurer l'éternité. Mesure qui
  l'a fait tomber : le balayage `20260919-082932` (3 marchands, 30 h) a ouvert le disjoncteur
  66 SECONDES après son démarrage, 7 heures avant que GameSeal ne commence ; les 60 pages de
  GameSeal ont résolu au slug seul et 434 offres distinctes sont ressorties « no AKS product
  page found ». La décision du 10/09 précédait les balayages tout-pages multi-marchands. Le
  coût d'une re-sonde est borné (3 tentatives par page qui la tente, une fois par fenêtre).

- **Comptes : un signal explicite l'emporte, et le silence n'est jamais « clé » (2026-09-25,
  rapport de bug de Romain).** Un détecteur unique (`console_keys.account_signal`) : mot
  ACCOUNT du titre, jeton `account` n'importe où dans le chemin d'URL, ou la grammaire propre
  du marchand (`account_row`). Un marchand SANS grammaire propre : un compte est refusé et
  routé en liste 30. Difmark garde sa branche compte, où la PAGE décide : ACCOUNT / OFFLINE →
  compte, « (<plateforme>) » ou KEY → clé (la « vraie clé Difmark » du 21/09 reste valide :
  le « account » de ses URL est un gabarit), rien de tout cela → refus. Un audit voudra
  (a) faire du « account » d'URL Difmark un signal de compte — non, c'est un gabarit, il
  casserait les vraies clés ; (b) retomber sur « clé » quand la page Difmark se tait — non,
  c'est exactement l'erreur des huit « [OFFLINE] » du 23/09 ; (c) assouplir la garde finale
  du submitter (destination inconnue → bloquée) — non.

- **`[R58]` Wyrel : « (PC) » sans boutique + page AKS « Steam » SEUL = Steam — Romain,
  2026-09-24, pour Wyrel SEULEMENT** (« si une offre est marquée PC et qu'on n'a pas d'autre
  info, si sur la page Allkeyshop on a que du Steam, on l'ajoutera en Steam ; si on voit qu'il y
  a du Epic, du Ubisoft, du EA… on skip » — « et c'est valable que pour Wyrel, dans sa config
  marchand »). Un premier « NO GO » du même jour a été remplacé par cette règle, formulée par
  Romain lui-même. Déclarée par `wyrel.pc_key_without_store` (`MerchantConfig`) ; le matcher
  exige l'égalité STRICTE des plateformes officielles de la page avec {Steam}. Un audit
  proposera de l'étendre aux autres marchands (Kinguin, Gamivo… écrivent aussi « PC » sans
  boutique) ou d'accepter « Steam parmi d'autres » : ne pas le faire sans un nouveau go — pour
  tous les autres marchands, R27 / `[R51]` restent intacts.

- **Une clé ROW n'entre que si on PROUVE qu'elle s'active en Europe — Romain, 2026-09-24**
  (« les ROW, pour que tu puisses les ajouter, il faudra s'assurer qu'ils soient valables en
  Europe »). Ni le titre ni l'URL ne le prouvent ; la page marchand le pourrait, mais celle de
  Wyrel est derrière Cloudflare. « Rest of World » / « Rest of the World » en toutes lettres
  sont donc le même verrou que le sigle ROW (`matcher.FORBIDDEN_REGIONS`,
  `merchants/common.py`). Un audit « trouvera » 161 lignes Wyrel ROW perdues, dont 69 avec une
  page AKS : c'est le prix accepté tant qu'aucune lecture de page ne prouve l'Europe — ne pas
  les faire entrer en GLOBAL.

- **Déconnexion pendant un lot : le lot CONTINUE — Romain, 2026-09-26** (« le lot continue »).
  Avec `--continue-on-halt`, un « not logged in » arrête le marchand (halte de page, jamais une
  reprise automatique) puis le lot passe au suivant ; il arrêtait tout le lot avant. Aucune
  écriture n'en dépend : chaque étape revérifie la session avant d'écrire, et une session
  vraiment perdue arrête chaque marchand suivant à sa première lecture. La re-authentification
  reste le transfert de cookies par Romain, jamais déclenchée par le code. Un audit voudra
  « restaurer l'arrêt du lot sur déconnexion » : ne pas le faire.

- **Reprise AUTOMATIQUE d'une page après une erreur passagère — Romain, 2026-09-24** (« pour
  Wyrel j'ai dû relancer 3 fois, tu vois pas le pb ? » puis « go pour les deux correctifs »).
  Ce n'est PAS un relâchement du fail-closed : la reprise ne vaut que quand RIEN n'a pu être
  écrit — un extract (lecture seule) sur une signature passagère, un submit arrêté AVANT tout
  clic sur « Create » (`feed_unreadable_prewrite`), un scan d'index raté avant la première
  offre — avec 3 reprises au plus (2, 5, 10 min). Un état INCONNU après un clic, une
  déconnexion, le garde, dix échecs d'affilée restent des haltes immédiates. Un audit
  « trouvera » que le balayage ne s'arrête plus au premier doute : ce n'est vrai que des doutes
  qui ne portent sur aucune écriture ; ne pas revenir à l'arrêt systématique.
  **Précisé le 2026-09-26** (balayage du groupe B, Gamivo p38 / Eneba p66) : « avant la
  première offre » couvre TOUT ce qui précède la boucle des offres (contrôle de connexion,
  catalogue, scan d'index, ouverture de session côté 05 avant `run()`) — preuve structurelle,
  aucune offre n'est ouverte ; le message d'un `CdpTimeoutError` compte comme sa signature ; et
  le détail d'un stage n'est lu que dans ce que CE stage a écrit. Une exception qui s'échappe de
  `run()` une fois entré reste une halte : on ne devine pas ce qui a pu partir.

- **P2-12 a une exception, et UNE seule forme — `MerchantConfig.url_identity_params`
  (2026-09-24).** P2-12 garde volontairement le CHEMIN seul comme identité d'une annonce (la
  query dérive chez G2A) et accepte qu'une sœur au même chemin fasse sortir une création
  « STILL in feed ». Chez Wyrel et CJS, la query EST l'annonce (région / édition / variation) :
  14 fausses erreurs Wyrel le 24/09, 13 CJS depuis le 20/09. Seuls les paramètres qu'un
  marchand DÉCLARE rejoignent la clé ; un marchand qui ne déclare rien garde P2-12 à
  l'identique, et une ré-identification de la MÊME annonce reste « encore au feed ». Un audit
  proposera de rendre toute la query identitaire, ou de retirer l'exception : ni l'un ni
  l'autre.

- **`[R61]` Loaded : « (Europe & UK) » = Europe, et SANS région = GLOBAL — Romain, 2026-09-25**
  (« 1. Europe 2. comme Kinguin et MMOGA en global »). Le vocabulaire partagé lit « Europe & UK »
  comme deux régions à la fois, donc un verrou : c'est la grammaire de CE marchand qui tranche,
  dans `src/merchants/loaded.py`. Un audit « trouvera » une clé UK entrée en EU, ou une ligne sans
  région entrée mondiale : c'est la règle voulue, la même que Kinguin et MMOGA. Ne pas la
  généraliser aux autres marchands.

- **`[R59]` Gamesplanet FR : la région est la liste des pays EXCLUS de la fiche — Romain,
  2026-09-25** (« go pour Gamesplanet FR avec ta règle + un pays UE exclu mais États-Unis
  autorisés → US »). Ni UE, ni UK, ni USA exclus → GLOBAL (même avec 80 pays d'Asie / d'Amérique
  latine exclus : c'est ainsi qu'AKS range déjà Gamesplanet FR, 20 offres sur 28 en Steam GLOBAL
  sur 10 pages lues) ; UE sans USA → EU ; USA sans l'UE → US ; le reste → refus. Un audit
  « trouvera » une clé bridée en Asie entrée en GLOBAL : c'est la règle voulue, ne pas la durcir.

- **Software region catch-all (`resolve_software_region`, Fable finding [7], DECLINED
  2026-09-07).** When an AKS software page has a SINGLE region and it is a
  GLOBAL/PUBLISHER-type bucket, a merchant offer is filed under it even when the offer's
  own region label looks US/EU-locked. Rationale: software licences are global and the
  merchant region label is usually noise (R31, 2026-08-11 — locked by
  `test_region_lone_country_is_not_forced`). Romain reviewed the audit finding that wanted
  to fail-close this and said "laisse [7] tel quel, ne durcis pas". A GLOBAL offer under a
  lone COUNTRY region still skips (unchanged); only the lone GLOBAL/PUBLISHER catch-all is
  kept. Do not add a US/EU-locked refusal here.

- **R25 duplicate guard REMOVED — do NOT re-add (Romain 2026-09-08).** The matcher used
  to skip a candidate whose merchant already had a price on the AKS page for the resolved
  region/edition ("`<merchant>` already lists a price … (R25)", added 2026-07-15 vs stale
  matched batches). Romain's ruling: **a PENDING offer is TO BE ADDED, period** — we do
  not check "already on AKS". The old guard matched by `merchantName`, so an AKS auto-sync
  / other-channel price (page merchant id ≠ feed `store_id`) false-skipped genuinely new
  offers; staleness is now covered by the stable pending feed + submit-time prove-gone. An
  audit will "find" the missing duplicate guard — leave it removed (EXECUTOR_RULES §6
  "Duplicate guard [R25] — RETIRED").

- **R27's "Direct Publisher confirms it" exception is NARROWED by `[R51]` (Romain
  2026-09-16) — do NOT restore the old default.** R27 (below in spirit) let a title with no
  platform token be entered PUBLISHER when the AKS page confirmed `Direct Publisher`. Romain
  found the hole live: two Electronicfirst rows and a Gamivo Steam GLOBAL key
  (`resident-evil-raccoon-city-edition`) were entered PUBLISHER. His ruling: « avant de decider
  si publisher ou non on doit ouvrir la page marchant pour verifier la region et l edition, si
  on arrive pas a ouvrir la page marchant on skip l offre … on devrait ajouter cette securite
  par defaut pour tous les marchants ». The AKS line describes the GAME, not the merchant's
  key. Such a row is now REFUSED unless the merchant declares
  `MerchantConfig.publisher_from_merchant_page` (default **False** — safety on everywhere); no
  merchant declares it today. Cost measured before the change: 13 distinct candidates ever
  (MMOGA 5, Gamivo 6, Electronicfirst 2). An audit will "find" that genuine publisher keys
  (Minecraft Java & Bedrock, Fallout 76) no longer enter — that is the accepted price until a
  merchant page reader lands; do not re-open the default.

- **R18 for MARKERLESS titles — DURCI le 2026-09-17 (Romain : « go pour le durcissement,
  seul seau DLC decide ») : le seau DLC ne décide QUE s'il est le SEUL de la page.** Le
  déclencheur : une clé Rockstar de JEU DE BASE, « Grand Theft Auto Vice City », titre sans
  aucun marqueur, est entrée DLC(16) parce que sa page porte un seau DLC à côté de Standard.
  Désormais un titre sans marqueur exige `len(editions) == 1` ; un vrai DLC caché
  («Exoplanets Pack ») garde sa page mono-seau et entre juste. « Standard + DLC » est un
  AUTRE seau (id 518) et n'a jamais déclenché R18 — vérifié sur le catalogue vivant.
  Les titres MARQUÉS sont inchangés (R43 : own-page, DLC anonyme). Ceci REMPLACE la décision
  du 2026-09-11 ci-dessous, qui reste en note pour l'historique : un audit qui relirait le
  git y verrait « ne pas durcir » — c'est périmé, Romain a tranché l'inverse le 17.
  **Complété le 2026-09-18 :** le durcissement ne fermait qu'une porte sur trois. La
  vérification de page E05/R23 et la réconciliation P1-1 adoptaient le seau DLC par égalité de
  libellé, sans marqueur ni condition « seul seau » — « DLC Quest », un vrai jeu de base,
  ressortait DLC(16). Les deux portes écartent maintenant les seaux DLC : `edition_id == "16"`
  ne peut venir QUE de R18. Un audit « trouvera » qu'un vrai DLC caché sous un seau nommé
  « DLC Pack » n'est plus adopté — c'est voulu, R18 est le seul juge.
  **Complété le 2026-09-23 par `[R57]`, une BRANCHE de R18 et non une troisième porte**
  (Romain : « si on a déjà des offres DLC on ajoute en DLC », après audit sur tous les
  marchands). Un titre sans marqueur prend aussi le seau DLC quand QUATRE faits sont réunis :
  il se lit Standard, la page ne vend AUCUN Standard (c'est ce qui garde le cas Vice City), la
  ligne est sur la page À SON NOM, et la page d'un JEU PARENT existe aussi au sitemap
  (« Europa Universalis IV: Muslim Advisor Portraits » + `europa-universalis-iv`). Mesuré sur
  ~17 000 offres : 19 récupérées (GOG 15, K4G 4), toutes des DLC, zéro chez les quatorze
  autres marchands. Sans index sitemap frais, la branche reste fermée. Un audit « trouvera »
  un deuxième chemin vers DLC(16) : il est dans le `if` de R18, gardé par ces quatre
  conditions, chacune vérifiée seule par mutation. Ne pas l'élargir à « la page a un seau
  DLC » : c'est mot pour mot l'erreur Vice City.

- **P5 console : un titre SANS marqueur DLC peut entrer en DLC(16) — Romain, 2026-09-26**
  (« Ne bloque pas côté console »). Depuis P5 (25/09), chaque page cible console passe par
  `r43_dlc_page_refusal` et par R18 comme le PC : un titre console sans marqueur n'atteint le seau
  DLC(16) que par les mêmes verrous (seau DLC SEUL sur la page, R18b, `[R57]`). Un audit proposera
  d'interdire DLC(16) aux titres console sans marqueur : ne pas l'ajouter.

- **`[R62]` Clé Microsoft Store : la page AKS doit lister « Microsoft Windows », TOUTES routes
  confondues — Romain, 2026-09-26** (« … puis aligne l'ancien chemin Microsoft Store »). Une
  vérification, `matcher.page_sells_microsoft_store`, lue par la branche « (Windows) XBOX LIVE
  Key » et par le garde commun ; plus stricte que R20 : une liste de plateformes VIDE ne passe
  pas, et `require_page_platform=False` (GOG) ne la lève pas. Le libellé AKS est « Microsoft
  Windows » (27 pages lues le 26/09), jamais « Microsoft Store ». Un audit proposera
  d'accepter « Microsoft Store », de laisser passer une page sans plateformes « comme R20 », ou
  de rendre la preuve optionnelle par marchand : non. Coût mesuré : 3 candidates Gamesplanet sur
  44 (Avowed ×2, Hellblade II, pages sans « Microsoft Windows »), 0 des 40 créations.

- **`[R55b]` GOG : « Expansion - … » est un marqueur DLC — pour GOG SEULEMENT (Romain,
  2026-09-23 : « expansion veut dire DLC, non ? »).** Déclaré par `gog.dlc_marker`, le préfixe
  de rayon retiré du slug et des gardes. L'audit du même jour sur 88 titres « Expansion » de
  13 marchands a montré qu'AKS vend certaines extensions en ÉDITIONS — Diablo IV Vessel of
  Hatred {DLC, Deluxe, Ultimate}, Guild Wars 2 End of Dragons {DLC, Standard, Deluxe} — qu'un
  marqueur générique forcerait en DLC(16). Un audit proposera de rendre « Expansion »
  générique dans `DLC_TITLE_MARKERS` : ne pas le faire.

- **[HISTORIQUE, SUPERSÉDÉ LE 2026-09-17] R18 "DLC bucket on the page ⇒ edition DLC(16)" for
  MARKERLESS titles — KEPT (Romain 2026-09-11).** The R43 adversarial review showed live base-game pages carrying bucket 16
  (Stray Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake were entered DLC(16) on
  2026-09-10) and no deterministic page-level nature signal exists. Romain's ruling: "des
  fois, les titres n'ont pas de marqueur et sont des DLC" — the bucket keeps deciding, the
  three entries are not corrected. An audit will "find" this as a wrong-edition risk — leave
  R18 as is. (Titles that DO carry a DLC / Season Pass marker are governed by R43's stricter
  own-page + unnamed-DLC rules — those are not the same decision.)

- **Console targets = merchant-declared platforms only (R45 P1, Romain 2026-09-14) — do NOT
  add a sibling page (PS4 for a lone PS5 key, Xbox One for a lone Series key).** Romain's
  ruling: « clé PS5 seule = page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch
  et Switch 2 ». The console branch (`_console_plan`, EXECUTOR_RULES §4.12 P1) files a key on
  the AKS page of every platform the merchant DECLARES and AKS has — a lone declared platform
  → that page only; a cross-gen declaration ("PS4 / PS5", "Xbox One / Series X|S") → both
  pages; the PC page only as a Play Anywhere target (P2 — page-verified, or declared Xbox +
  PC since 2026-09-25, below). An audit will
  "find" the missing PS4 / Xbox One sibling ("the game exists on that page too") — there is
  no "page alone" policy and no switch for it; leave it out.

- **Consoles — trois réponses de Romain du 2026-09-26** (EXECUTOR_RULES §4.12.3 / §4.12.4 f bis).
  Un audit les reprendra comme des « trous » ou des « incohérences » ; elles sont voulues :
  - **P2 CONFIRMÉ : « Xbox + PC reste playanywhere, pas de pb »** — après vérification : 15
    créations P2 depuis le 25/09 16:30 UTC, 11 jeux, et les 11 pages PC AKS affichaient « Xbox
    Play Anywhere ». Xbox + PC DÉCLARÉS par le marchand = Play Anywhere, SANS lire la page PC.
    Ne pas remettre la vérification « la page PC doit lister Xbox Play Anywhere » pour P2.
  - **« 1. » — la clé Windows SEULE (« (Windows) XBOX LIVE Key », « PC/XBOX LIVE Key »,
    « Windows 11/Xbox Live Key », « (PC) - Xbox Live Key », Gamivo `-xbox-pc-`) n'est PAS P2.**
    Romain a répondu par une explication collée : une telle clé « s'active sur l'application
    Xbox de Windows (le store Microsoft) et fonctionnera sur PC » ; elle ne débloque la console
    que si le JEU est Xbox Play Anywhere — « ne vous fiez pas uniquement au titre du produit…
    vérifiez s'il est présent sur la liste officielle Xbox Play Anywhere ». Donc la page PC
    d'AKS tranche : « Xbox Play Anywhere » → cibles Play Anywhere (pages Xbox qu'AKS a + page
    PC, cases XBOX/PC ; la page PC seule si AKS n'a aucune page Xbox) ; sinon « Microsoft
    Windows » → clé Microsoft Store (MICROSOFT, Windows 10 : 246 / 244 / 245 / 249) sur la page
    PC ; sinon refus. C'est ainsi qu'AKS range déjà ces clés (lu le 26/09 sur 24 pages : Eneba
    « PC/XBOX LIVE » en XBOX/PC EU 241 sur les pages Play Anywhere, Eneba / G2A / GameBoost /
    Gamivo en 246 / 244 sur les pages « Microsoft Windows »). Un audit dira « c'est P2, traitez
    la comme Play Anywhere » : non, le titre ne dit pas que le JEU est Play Anywhere. Un titre
    qui écrit LUI-MÊME « Xbox » + PC (« (XBOX AND WINDOWS) », « (Xbox + PC) ») reste P2.
  - **« 2. les 2 » — le Xbox sans génération se lit dans le titre ET dans l'URL.** Pour un
    marchand SANS hook, un jeton `xbox` nu du slug (etailcard `xbox-global-games-<jeu>`,
    lootbar `…/<jeu>-xbox`) vaut le « Xbox » nu du titre (P4, les pages qu'AKS a) — sauf si un
    `pc` / `windows` le touche (ambigu) ou si le titre nomme une boutique PC (« … (PC) Steam
    Key » : l'URL seule ne fait jamais une clé Xbox) ; Gamivo, dans son fichier : `-xbox-<cc>`
    et `-xbox` final (magasin Xbox sans segment de plateforme), `-xbox-standard-<run>`. Une
    génération que l'URL DÉCLARE reste une plateforme déclarée (P1, cette page seulement).

- **Consoles — P2 élargi, P3, P4, P5 : DÉCIDÉS par Romain le 2026-09-25** (« P3 A, P5 A, P2 saisir
  sur les xbox déclarées et sur PC (on le considère Play Anywhere) » ; EXECUTOR_RULES §4.12).
  Un audit reprendra les trois comme des « trous » ; ils sont voulus :
  - **P2** — un marchand qui déclare Xbox + PC/Windows alors que la page PC d'AKS ne liste PAS
    « Xbox Play Anywhere » est traité COMME Play Anywhere : les pages Xbox déclarées + la page
    PC, toutes dans la case XBOX/PC (306 / 241 / 242 / 240). Ne pas restaurer le refus
    « … does not list Xbox Play Anywhere » (« la page AKS fait foi » était la décision de
    départ ; Romain l'a renversée). Bornes inchangées : « PC + famille NON-Xbox » reste le
    refus `contradictory delivery` ; sans page PC chez AKS, refus (jamais une cible perdue) ;
    P1 et le plafond de 3 cibles tiennent.
  - **P3** — une clé PS5 Europe / US / UK prend la case PlayStation de PS4 (`88eu` / `88us` /
    `88uk`), GLOBAL garde `88ps5h`. AKS range déjà ses offres PS5 ainsi (43 `88eu` + 41 `88us`
    à côté de 96 `88ps5h` sur 10 pages PS5 lues le 25/09). Un audit « trouvera » un seau
    « PS4 » sur une page PS5 : les libellés de la famille disent « Playstation Game Code »,
    pas PS4 ; ne pas remettre le refus « no region id for PS5/EU ».
  - **P4 Xbox — « Xbox sur les deux »** (même jour, ajout de Romain). Un Xbox SANS génération
    (« Tin & Kuna XBOX LIVE Key EUROPE », « (Xbox Live) », Gamivo `-xbox-xboxwindows-`) est LU
    comme la déclaration « Xbox One / Xbox Series X|S » (`generation_inferred`) : cibles = les
    pages qu'AKS A (onglet absent ou 404 → cette génération tombe ; les deux → « no AKS product
    page found (console) ») ; + PC / Windows → le cas P2. Un audit y verra une « page sœur »
    contraire à P1 : non — P1 interdit d'AJOUTER une génération à une génération DÉCLARÉE
    (inchangé, tout ou rien) ; ici le marchand n'en déclare aucune et Romain a tranché la
    lecture. Bornes : un item PlayStation / Nintendo dans le titre ou l'URL → pas de déduction ;
    PC / Windows à côté du seul magasin « Xbox Live » (« (Windows) XBOX LIVE Key ») = clé PC →
    la règle de la clé Windows ci-dessus (2026-09-26 ; refus « PC-only » avant). **P4 PlayStation = refus** (« … PSN Download Key (Playstation) … » reste
    « no declared generation ») ; Switch sans génération : refus inchangé.
  - **« Switch » dans un nom de jeu PC** (bug signalé par Romain, même jour) : un « Switch » nu
    HORS de tout créneau de plateforme, dans un titre qui déclare une boutique PC (PC / PCS /
    STEAM / WINDOWS / GOG / EPIC), est un mot du NOM — « Mighty Switch Force! Collection (PC)
    Steam Key » est une ligne PC (`console_marker_in_title`, lue par le classifieur ET le
    precheck). Les DEUX conditions sont voulues : « Everybody 1-2-Switch! » (exclusivité Switch,
    sans boutique PC) reste une ligne console. Ne pas élargir à « tout Switch hors créneau ».
  - **P5** — un DLC / season pass console entre, par la règle des DLC PC `[R43]` appliquée à
    CHAQUE page cible (`r43_dlc_page_refusal`, UNE implémentation partagée avec le PC) : page
    du DLC lui-même (slug du nom complet), seau DLC (16), sinon la ligne entière est refusée.
    Un titre SANS marqueur n'atteint DLC(16) que par R18 et ses verrous PC (seau DLC seul de
    la page…). Ne pas remettre le refus en bloc « DLC / season pass on console — not entered
    yet » ni une règle console à part.

- **Kinguin "(valid until <Month> <Year>)" keys are ENTERED (Romain 2026-09-14).** Romain's
  ruling: « Kinguin valid until juin 2027 on rentre ». The note is an activation deadline,
  not a product word: `kinguin.guard_name` strips it — and only it — from the title the
  R01 / R16 / R01b guards and `detect_edition` read (`MerchantConfig.guard_name`, R32e),
  `resolve_name` peels it for the slug, `console_noise` carries it for console rows; the row
  is entered like any Kinguin title (implicit GLOBAL unless a code says otherwise). Before:
  79 rows / batch skipped "different/expanded product — extra words: ['VALID', 'UNTIL', …]".
  An audit will "find" a merchant note laundered past the name gate — it is not: every other
  word of the title is still compared with the AKS name, and only the "(valid until
  <Month>[,] <Year>)" spelling is stripped (any other form stays in the guard). Leave it
  entered; do not re-add the extra-words skip. Review fix (2026-09-14, same evening): the
  strip is anchored to the title END (158 / 158 corpus rows are trailing) — a mid-title
  note stays in the guard; do not widen the strip to the middle of a title.

- **K4G "Steam Altergift" = Steam GIFT, ENTERED (Romain 2026-09-14).** Romain's ruling:
  « Steam Altergift = Steam Gift on rentre sous gift tous les altergifts ».
  `k4g.gift_delivery` answers True for the whole word ALTERGIFT (`MerchantConfig.gift_delivery`,
  R32e) and `detect_region` layers the Steam GIFT bucket on the base region — GIFT (25) for
  no region / Global, GIFT EU (259) for Europe, GIFT US (2577) and GIFT UK (2572) for those
  bases; forbidden regions (North America, Americas) keep their precheck skip.
  **Corrected 2026-09-16 (`[R50]`, Romain: « si ça existe le fichier marchand ne devrait pas
  affirmer le contraire, fix la config marchand »):** this decision used to state that a US /
  UK base "has no Steam gift bucket" and therefore failed closed. That premise was FALSE —
  the live region dropdown has carried Steam Gift US (2577) and Steam Gift UK (2572) all
  along, and they are now mapped, so those rows ENTER under their own bucket. The safety
  property is untouched: a locked gift never widens to the platform-global gift (25). An
  audit will re-derive the old "no gift_us/gift_uk" sentence from the git history — it is
  obsolete, do not restore it. "Altergift" is never a product word (`k4g.guard_name` /
  `resolve_name` drop it). The explicit "skip category: ALTERGIFT" precheck of the same
  morning (open question `OPEN_QUESTION_ALTERGIFT`, "no confirmed bucket") is removed — an
  audit will "find" an unconfirmed gift bucket and want the skip back; do not re-add it.
  Review fixes on that ruling (2026-09-14, same evening — also reviewed, fail-closed):
  (1) the slug must AGREE (`-altergift-` / `-alter-gift-`, 217 / 218 rows) — a `-cd-key`
  slug against an Altergift title (offer 101030313 "Trine 5 …", the one such row), a slug
  with no delivery segment, or the mirror conflict is a `precheck` skip ("K4G delivery
  conflict …"), never GIFT (25) and never GLOBAL (2): an audit will "find" a missed gift —
  leave it refused, the row itself contradicts both classes; (2) « Steam Altergift = Steam
  Gift » is Steam-ONLY — a non-Steam Altergift is "… outside the Steam collocation" (never
  Battle.net GIFT 570 / 567); (3) « tous les altergifts » covers Kinguin's own "Altergift"
  delivery (`kinguin.gift_delivery`, same gates) — an audit will "find" that as scope creep
  over a K4G ruling; it is Romain's wording, leave it.

