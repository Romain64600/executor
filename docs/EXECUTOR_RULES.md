# EXECUTOR_RULES.md — deterministic spec derived from the aks-data-entry skill

**Status: v1, synced to the skill (which is still being improved).**
Source of truth for *domain* rules is the `aks-data-entry` skill
(`SKILL.md` + `references/`). This file translates that skill into a
**deterministic, per-stage specification** the Controlled Executor must
implement. When the skill and this file disagree, the skill wins and this file
must be updated. `AGENTS.md` / `CLAUDE.md` remain the *builder* rules.

Skill snapshot ingested: CORE_RULES (2026-06-29), LEARNED_RULES (2026-06-30),
REGIONS_PLATFORMS (2026-06-25), ERRORS (2026-06-25), merchant files
(2026-06-25 → 06-30). Rule codes in brackets (e.g. `[R01]`, `[S18]`) point back
to the skill so this file stays traceable.

The guiding principle is identical to the skill's and to `AGENTS.md`:
**accuracy > speed, fail-closed, never improvise.** Every "success" the executor
records must come from deterministic code, never from a model self-assessment.

---

## 0. Authority order

From the skill's PRIORITY ENTRYPOINT:

1. Latest direct instruction from Romain for the **current active task**.
2. This deterministic spec + `AGENTS.md` / `CLAUDE.md`.
3. `references/rules/LEARNED_RULES.md`, then `references/rules/CORE_RULES.md`.
4. Merchant-specific file.
5. Other infra/reference files.

If two rules conflict → stop and follow the highest-priority one. A validation
given in a previous task is void after any interruption `[S15]`.

---

## 1. Session contract — cross-cutting invariants (always active)

These map directly to `src/aks_env.py` / `scripts/01_check_invariants.py` and
must be green **on the Debian VPS target** (`authoritative: true`) before any
stage that touches the browser runs `[S24][S25]`.

- AKS direct returns `200/301/302` — checked before anything `[S20]`.
- CDP is used **only** through the Docker-bridge proxy
  `http://172.17.0.1:9223/json/version` from the Hermes terminal `[S24]`.
- Chrome User-Agent is exactly
  `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36`
  and does **not** contain `HeadlessChrome` `[S24]`.
- The `AKS/Staff` User-Agent is for **allkeyshop.com requests only** — never
  for merchant or any other hosts (Romain, audit #4, 2026-07-08).
  `src/aks_env.py:http_get` enforces it fail-closed (`ValueError` on any
  non-`allkeyshop.com` host, suffix-spoof safe); the CDP browser keeps the
  required Chrome UA above. Mirrors the host Chrome UA-Switcher policy
  (AKS domains only).
- CDP `/json/version` exposes `Browser`, `User-Agent`, `webSocketDebuggerUrl`.
- OpenVPN is **not** used when AKS direct works `[S20]`.
- No stale AKS scripts are running.

**Forbidden by default** `[S24]`: `127.0.0.1:9222` from the Docker terminal;
random `0.0.0.x` probes; Browserbase / `browser_navigate` as a substitute for
strict CDP; Playwright; launching/rotating VPN when direct works;
`/root/start-chromium.sh`; fake crawler User-Agent.

Fail-closed: if any invariant is red on the authoritative target → **STOP**, no
fallback, write an error report.

---

## 2. StepGuard mapping — how the skill's stop-rules become code

The skill is full of "the agent looped / improvised and it failed" lessons.
`src/step_guard.py` enforces these deterministically. Every stage runs its
actions through the guard.

| Skill rule | StepGuard mechanism |
|---|---|
| Same approach fails 2× → STOP, diagnose, don't retry a 3rd time `[G03][anti-boucle]` | `max_attempts_per_signature = 2` → `repeated_signature_failure` block |
| Re-auth / CDP fails 2× → STOP `[S15][I18b]` | cookie-transfer / CDP steps sized with `max_attempts_per_signature = 2`; second failure hard-blocks |
| Don't thrash between browsers/VPN/scripts `[S15]` | consecutive-failure and per-task failure-budget blocks |
| A block cannot be argued away by the model | block lives in `StepGuard` state, cleared only by a genuinely new `task_id` (`start_task`) |
| New instruction / interruption cancels the old task `[S15]` | the loop assigns a new `task_id` per user intent; leftover work cannot pass `check()` |

**`success` inputs to `record_result` (deterministic only):**

- Extractor: feed HTTP `200` **and** JSON parsed **and** ≥0 offers extracted.
- AKS slug check: HTTP `200` on the product URL.
- Submit: **the offer disappeared from the freshly-refreshed feed (same
  `available` mode as the run)** `[S10][S18]` — never `[data-success]`, never a
  model judgment.

---

## 3. Stage 1 — Extractor (read-only)

**Source of offers is the WordPress AKS merchant feed, never the merchant
site** `[F01]`.

- Refresh the current merchant feed **from scratch** every session; use
  only offers visible in the freshly refreshed feed; never reuse candidates from
  memory or a previous session `[S25][fresh-feed override]`.
- Scan via `available=all` (HTML). `available=pending` is AJAX and is used only
  to confirm remaining pending at the end `[F02][F07]`.
- Filter by store with the **URL parameter** `&store=<id>`, not the on-page
  dropdown — the dropdown can return third-party URLs (Kinguin trap) `[KINGUIN]`.
- Pagination is `&p=N` (**not** `paged=N`); dedupe by offer id across all pages;
  scan every page `[F03][F03b]`.
- **Every feed URL carries `&orderBy=id&order=desc` (2026-09-24, Romain : « go pour la 2 »).**
  The default sort is `createdAt` ALONE, and a bulk import gives the same second to thousands
  of rows: between them the database guarantees no order, so each `&p=N` draws a random
  hundred from the block — repeated pages, and more than 13 000 pending rows never shown per
  pass (`docs/AUDIT_2026-09-24_feed-pages-repetees.md`). The server accepts `orderBy=id`
  (not offered by the screen): unique, hence deterministic, and `desc` keeps the newest rows on
  page 1. It is set in the ONE URL factory (`extractor.feed_url`, constant `FEED_ORDER`) so
  every stage of a run — extract, submitter refresh/locate/prove-gone, mover, all-stores scan —
  sees the same row on the same page; a test refuses a feed URL built anywhere else. The
  SEARCH page (`aks-merchant-feeds-search`) carries the same sort since 2026-09-25 (Romain's
  review: the prove-gone search escaped it), and a search result page whose rows were ALL
  already read raises `FeedScanError` — overlapping pages are never a disappearance proof.
- The real page count comes from the feed's own pagination nav (`.tablenav`
  links, rendered on every page incl. past-the-end) — bound the scan by it,
  never by "first empty page" heuristics.
- **EXCEPTION — the `aks-merchant-feeds-search` page does NOT paginate `[P2-13]`
  (resolved live 2026-09-04, `scripts/probe_p2_13_search_navmax.py`).** The
  all-merchants SEARCH renders ALL matches on ONE page: `nav_max` is always 0 and
  `&p=N` re-serves the same page, capped SERVER-SIDE at **300 distinct rows**
  ("Steam"/"Key"/"a" → 300; "e" → 151). So the by-urls search reads page 1 ONLY and
  flags `truncated` iff the result HIT the cap (a sub-cap result is complete). Do NOT
  apply the `.tablenav` nav rule here (nav is absent) nor a 100-row/3-page heuristic
  (it re-read the same page and false-flagged truncated for any ≥100-row result).
- Some feeds re-order between page fetches (G2A 2026-07-07: 762 rows seen /
  482 distinct in one pass) → repeat **full sweeps**, unioning by offer id,
  until a whole sweep adds 0 new offers. Sweeps exhausted while still finding
  new ids = abort loudly (`FeedUnstableError`), coverage not proven.
- A blank in-range page is NEVER accepted at face value (seen live 2026-07-07:
  transient blank render on page 1 passed as "empty feed"): re-fetch once,
  then only two blank states are legitimate — page 1 with feed UI and **no**
  pagination (empty queue) or a past-the-end page after a mid-sweep shrink.
  Anything else aborts loudly (`EmptyPageAnomaly`).
- **The submitter's `_read_feed_page` MUST mirror the extractor's past-the-end
  classification.** A confirmed empty over-page (`page > 1`, feed UI up) with
  `nav_max < page` — which **INCLUDES `nav_max == 0`** — is PAST-THE-END, returned as
  `[]`, not an error. `nav_max == 0` is the shape AKS renders for a **single-page
  feed** (one page, no pagination nav), and `_scan_feed` is not nav_max-bounded, so it
  walks to the over-page (p=2). Narrowing the return to `1 <= nav_max < page` (the P1-3
  regression, fixed `bc2507a` in the 2026-09-05 re-audit) makes a single-page feed
  RAISE on its over-page → the whole scan aborts `feed_unreadable` → an over-block of
  every offer in that feed. Keep the submitter and `extractor.py`'s
  (`page > 1 and feed_ui and nav_max < page`) classification identical.
- **Testing caution — model `nav_max == 0` for single-page feeds in fakes.** AKS
  reports `nav_max = 0` for a single result page (not 1). This exact quirk has now
  caused **three** bugs (`_scan_search` locate, the `truncated` heuristic, the P1-3
  over-page above) — each hidden because a test fake modelled one page as `nav_max = 1`.
  A fake MUST render a single page as `nav_max = 0`; the OVER-PAGE (`p > 1`) shape then
  DIFFERS by scanner and must match reality, or the fake masks the branch it should test:
  - **FEED fake** (`_read_feed_page` / `_scan_feed`) — render the over-page EMPTY but
    STILL on `p > 1` (href on p2, `feed_ui=True`, `nav_max=0`). THAT is the PAST-THE-END
    branch the P1-3 rule above protects (see `SinglePageNavZeroSession`). Do NOT re-serve
    page 1 — that is a DIFFERENT branch (the `&p=` wedge, caught by the href-drift guard),
    so a feed fake that re-serves p1 never exercises past-the-end.
  - **SEARCH fake** (`_scan_search` / `_read_search_pages`) — an out-of-range `&p=`
    RE-SERVES page 1 (the search's real behavior, P2-13 probe 2026-09-04); the locate's
    stop-at-`nav_max` is what bounds it. This is the opposite of the feed over-page.
- **The browser must have LANDED on the page navigated to `[P1-5]` (audit
  2026-09-02).** `PAGE_STATE_JS` now returns `href`, and every page read
  (`_assert_landed`, both sweep and slice modes) checks `_page_param(href) ==
  page`. A wedged `Page.navigate` (commits but re-serves the PREVIOUS page's DOM,
  leaving `location.href` on the prior url — a real CDP-under-load hazard the
  submitter already guards, SC6) would otherwise feed page N-1's rows: they all
  dedupe into `seen` (`new=0`), so the sweep falsely proves coverage while page N
  goes silently unread → a sub-covered snapshot reported as complete. A mismatch
  aborts loudly (`WedgedNavigationError`, a subclass of `EmptyPageAnomaly`).
- `data-offer` is HTML-entity-encoded → `html.unescape()` **before**
  `json.loads()` `[F05]`.
- For large feeds (>50 offers) filter in-page JS to return only relevant PC rows
  so the payload fits the return limit (skill Phase 1).
- Fields available in `data-offer`: `id`, `name` (title — not `title`), `url`
  (not `buy_url`), `storeId`, `price`, `stock`. Names vary per merchant — verify.
- **Pacing between page fetches** (burst / IP-ban mitigation): a bounded-random
  wait (`Pacer`, `src/pacing.py`) before every page fetch after the first.
  CLI `--pace MIN-MAX`, default `2-5` s, `0` disables. Pacing is **never a
  correctness mechanism** — settle waits and retries are separate and stay.
- **Page-par-page slice mode** (`--pages 3` or `--pages 3-5`): fetches ONLY the
  requested pages, once, for working a large feed one slice at a time. The
  result is **always `partial: true`** — a slice NEVER claims coverage (no
  sweeps, no `FeedUnstableError`); never treat a slice output as a full-feed
  snapshot. Same fail-closed classification as sweep mode: login bounce →
  `NotLoggedInError`; blank in-range page after one re-fetch →
  `EmptyPageAnomaly`; only two legitimate early stops (empty queue on page 1,
  past-the-end page). The output reports `feed_last_page` (from the pagination
  nav) so the operator can plan the next slice.

**Never** open the submit modal, submit, edit, or log in from this stage. Write
a raw snapshot JSON + a normalized offers JSON.

Implemented in `src/extractor.py` + `scripts/02_extract_feed.py`, driving a
read-only CDP session (`src/cdp_session.py`, navigate + evaluate only). Output
shapes: see [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md).

---


**La garde `[20]` vaut aussi pour le mode TRANCHE (audit complet, 2026-09-18).** `extract_pages`
faisait du `nav_max` lu au premier read la valeur autoritaire de `feed_last_page`, sans la
corroboration que le mode SWEEP applique à la même forme (page 1 pleine de lignes + `nav_max == 0`
→ sonder p=2 → `FeedUnstableError`). Or c'est CE mode que `scripts/10` utilise pour sa sonde de
pagination (`02_extract_feed.py --pages <N>`) : un feed de 107 pages dont la nav dérive pouvait
être balayé sur UNE page et déclaré complet. Même sonde, même refus, jamais de troncature
silencieuse ; une over-page vide confirme le feed mono-page et la tranche continue inchangée.

## 4. Stage 2 — Matcher (pure, deterministic)

Consumes the normalized offers JSON; emits candidates JSON + skipped JSON. No
network side effects except read-only AKS slug `200` checks.

### 4.1 Name match — necessary condition `[R01]`
Tokenize the AKS product name (strip trademark/legal symbols
`™ ℠ № ℡ © ® ℗ ℅ ℀ ℁ ℆` to a space, then **NFKD + retrait des marques combinantes**, then
apostrophes `U+2019/U+2018 → '`, **puis repli de l'apostrophe**). **Every meaningful word of
the AKS name must be present in the merchant title.** One word missing → **SKIP**.
(Necessary, not sufficient.)

**Deux replis complétés le 2026-09-18 (audit complet).** Le repli d'accents du 2026-09-16
s'était arrêté aux scans CATÉGORIELS : ni l'identité ni le slug ne repliaient quoi que ce soit,
alors que la regex `[A-Z0-9']+` JETTE silencieusement ce qui sort de sa classe — « Kādomon »
devenait « K DOMON », l'identité échouait et la mauvaise page AKS était sondée. NFKD **remplace**
NFKC : c'est un sur-ensemble strict (même décomposition de compatibilité, donc `[R28]` tient —
« Ⅱ »→II, « ＤＬＣ »→DLC, « ﬁ »→fi) auquel s'ajoute la décomposition canonique dont on retire les
marques. L'apostrophe, elle, est repliée dans `tokenize` — comme `_identity_tokens` le fait pour
les pages console depuis le 2026-09-14 et comme `_slug_variants` sonde déjà les deux
orthographes : R01 l'exigeait au caractère près, donc « Assassins Creed » ne couvrait pas
« Assassin's Creed ». Un faux REFUS, jamais une fausse saisie ; le repli ne peut faire matcher
que des noms qui SIGNIFIENT la même chose (même argument que `fold_accents`). La moitié
« mots-outils » du constat (THE / OF / AND retirés du côté requis) est délibérément ABANDONNÉE :
elle relâcherait l'identité.
**NFKC first `[R28]` (2026-07-16):** NFKC-normalize BEFORE both `tokenize` and
`build_slug_candidates` — `tokenize`'s `[A-Z0-9']+` regex silently drops any character
outside that class, and NFKC decomposes compatibility characters such as the single-codepoint
Roman numeral "Ⅱ" (U+2161) into plain ASCII ("II"), so a sequel indicator never vanishes from
the identity check nor from the probed slug. Curly quotes stay a separate explicit replace
(not an NFKC compatibility decomposition of `'`). Historique : CHANGELOG 2026-07-16 (Eneba
« Road to Empress » escape).
**Symbol strip before NFKC (2026-09-08, Eneba `Company™`):** NFKC decomposes `™`
into the letters `TM` glued to the word (`COMPANYTM`), so these symbols are
replaced by a space BEFORE NFKC in `normalize_apostrophes` (covers tokenize /
cleaned_title / build_slug_candidates). `©`/`®`/`℗` have no NFKC decomposition
(`tokenize`'s `[A-Z0-9']+` would drop them anyway); they sit in the same strip so
that `cleaned_title` — the AKS search query and the slug candidates — never
carries them.

**Roman numerals ≡ digits `[R42]` (2026-09-10, MMOGA "Crusader Kings III" vs the AKS page
"Crusader Kings 3"):** a sequel number is the same word whichever way it is written.
`tokenize` canonicalises standalone II–XV to digits (so `[R01]` / `[R16]` accept either
spelling), `build_slug_candidates` tries the other spelling right after each base
(`crusader-kings-iii` then `crusader-kings-3`, same tier, one extra probe only when a
numeral exists) and the by-urls feed search (scripts/11) queries both spellings by name
and by URL. Deliberately NOT I, V, X (real title words: "V Rising", "Mega Man X") — those
stay letters, fail-closed; a year (`Fable 2026`) is never a numeral.

### 4.2 Different-product guard — `[R01b]`
Even if all words match, **SKIP** when the merchant title carries a dangerous
qualifier absent from the AKS name: `Remaster(ed)`, `HD`, `Reboot`, `Remake`,
`Redux`, `Season Pass`, `DLC` (both waived when the resolved page carries the DLC
bucket — the page IS the DLC, §4.3 `[R43]`), `Upgrade`, `Skin`, `Soundtrack`,
`Digital Book/Artbook`, and since the 2026-07-17 audit (`MA3`) `Anniversary` /
`Definitive` — the live master catalog has no stable plain numeric id for either, so
there is no safe EDITION_HINTS entry: doubt goes to skip, and dedicated "… Anniversary/
Definitive Edition" AKS pages (name carries the word) are unaffected (historique :
CHANGELOG 2026-07-17, MA3). Never
add a remaster to a base-game page unless the AKS page explicitly matches the
remaster `[critical learned rule]`.

### 4.3 Immediate SKIP list `[CORE_RULES][P04]`
Console (Xbox/PS/Nintendo — the `console` skip fires on a title OR URL marker; lifted
by the console branch — `--consoles`, the DEFAULT since 2026-09-15, `--no-consoles`
restores the skip — §4.12 `[R45]`); forbidden regions
(RoW/AMERICAS/ASIA/OTHER/North America/EU-NA/EMEA/NA/Eastern Europe/SEA/Middle
East/Turkey/Germany); Country Gift (CZ/RU/TR/BR/AR/IN/CN);
Prepaid/Subscription/Voucher/Gift Card/Wallet/in-game currency
(Points/Coins/Gems/Diamonds/Credits/Top-Up)/Membership/Steam Account
(`CATEGORY_SKIP`); language
restrictions (EN/FR/ES "… Languages Only", EN/CS);
**`CATEGORY_SKIP` is matched WORD-BOUNDARY, not raw substring** `[P2-7]` (audit
2026-09-02): a raw substring silently over-skipped valid games ("Stratagems"→GEMS,
"Checkpoints"→POINTS, "Laptop Upgrade"→"TOP UP"). Each token now matches as whole
words (`_category_skip_pattern`): internal spaces accept any punctuation
("Gift-Card" ≡ "Gift Card"), an optional `S`/`ES` keeps plurals caught
("Vouchers", "Antiviruses"), and the boundary is **letter-only** so a token glued
to a DIGIT (an amount — the strongest currency signal) still skips ("5000Gems",
"Wallet100") while a game word glued to a LETTER passes ("Gemstone"). `SOFTWARE` was
**dropped** from the list (a title literally containing "software" would jump the
R31 software path — §4.6); it is now a classifier, not a skip. Known fail-SAFE
residual: a bare currency word that is genuinely a game's leading word ("Gems of
War") stays skipped — the games-only/no-currency hard rule forbids the reverse
error, so doubt → skip (the operator can enter it by hand). **This precheck is
defense-in-depth, NOT the leak-proof games-only net** (re-audit 2026-09-05): the same
letter boundary that keeps "Stratagems" lets a currency/gift token glued to a
lowercase brand prefix escape ("Amazon eGift Card", "Garena eCoins") — precheck
returns None for these. The AUTHORITATIVE non-game filter is downstream (no AKS game
page / R01 / extra-words), which still catches them, so none is entered; do NOT
tighten precheck with a brand-prefix heuristic (indistinguishable from an embedded
game word without re-breaking games);
**ANY bundle and ANY skin** — categorical, word-boundary on the title
(`Bundle(s)`/`Skin(s)`), even single-game/cosmetic bundles that have their own
token-perfect AKS product page (Romain, direct rule 2026-07-07, after the
Overwatch "Genji Mythic Weapon Skin Bundle" candidate was wrongly proposed;
generalizes the G2A "skip skins" note in §11 and the Layer-5 server-side bundle
rejects in §6); multi-game bundles/collections. `Skin(s)` is guarded
(`_SKIN_TITLE_PHRASE_RE`, Romain 2026-07-23): a cosmetic reads "`<weapon/hero>
Skin`", so `Skin` preceded by an article/possessive ("Blacksad: Under **the**
Skin", "**Second** Skin", "Save **Your** Skin") or **leading** the title ("Skin
Deep") is an ordinary title word, NOT a cosmetic — not a skip;
**non-game content** — soundtracks (`Soundtrack`/`OST`), artbooks
(`Artbook`/`Art Book`/`Digital Artbook`), digital books
(`NON_GAME_CONTENT_TOKENS`, word-boundary; `OST` is word-boundary so "Ghost"/
"Frost" do not fire), Romain 2026-07-23 → **Blacklist (8)**;
**random / lootbox keys & items** (`_RANDOM_LOOT_RE`, Romain 2026-07-23,
examples): the tell is **grammatical** — a lootbox uses `RANDOM` as an *adjective
on a generic delivery noun* (a word naming "a thing dispensed", never a game's
identity); a real game uses "Random" as a *proper noun* ("**Lost in** Random",
"Random **Heroes**"). Two tiers: **common** delivery nouns (`GAME/KEY/ITEM`, also
seen on ordinary offers) count only **directly** after `RANDOM` ("Random Key") —
which keeps "Random Heroes Steam Key" / "Lost in Random Steam Key" out (a platform
word sits between); **strong** delivery nouns (`CASE/CRATE/DROP/SPINNER/LOOT/
BUNDLE/MYSTERY/BOX/GACHA`, rare in normal offers) may span a couple of adjectives
("RANDOM INDIE STEAM CASE"). Also fires on a **quantified draw** ("1x Random…",
"10 x Random…"). Checked **before** the category loops so it primes over an
incidental `GIFT CARD` token ("…RANDOM CASE GIFT CARD…") and over `BUNDLE` (so
"Random Bundle" reaches Blacklist, not the bundle-excluded route). "Random … Skin"
lootboxes route via the `Skin` cosmetic rule → **Blacklist (8)**;
**Software/application — NO LONGER an immediate skip** `[R31]` (Romain
2026-08-11, revising the R22 games-only skip): software AKS actually sells IS
entered, but only via the dedicated **software path** (§4.6) which reads the
licence edition/region from the page and skips when it can't. `SOFTWARE_APP_TOKENS`
(EaseUS/Avast/…/Adobe, VPN brands, Internet/Total Security, Microsoft Office,
Windows 10/11/Server, Bigasoft, Video Converter/Screen Recorder) + `_WINDOWS_OS_RE`
are now **classifiers** (`is_software_title` / `is_software`), not skips.
Deliberately NOT matched as software: `NERO` (game N.E.R.O.), `AVG` (genre tag),
bare OFFICE/WINDOWS/BACKUP. (The list-**sort** console still groups software under
the Softwares list via `is_software_title` — that workflow is unchanged.)
`[R22 superseded by R31]`;
DLC/extension without base game; title with **≥1 significant word** absent from
the AKS name (platform/format/region/edition noise excluded, incl. `COM` from
"GOG.COM"; tightened from the CORE ≥2 floor on 2026-07-07 after the
"Offworld Trading Company - Interdimensional" DLC escaped with a single extra
word — doubt goes to skip) `[R16]` — **UNLESS every extra token names ONE page
edition** (page-verified rescue `[R39]`, 2026-09-01): "Legends of Eisenwald -
Knight's Edition" (URL `…-knights-edition-…`) → the page's own "Knights Editon"
(id 2723), so the KNIGHTS token is that edition's qualifier, not a different
product. The match is on the distinctive token, apostrophe-folded ("Knight's" ==
"knights") and tolerant of AKS's "Editon" typo (never the "Edition" suffix), and
it also resolves the offer TO that page edition instead of a guessed Standard.
Resolution is DETERMINISTIC (Romain review 2026-09-01): exactly ONE compatible
edition → resolve; ≥2 compatible → the title has no signal to choose, so None
(skip) UNLESS a SINGLE edition's distinctive tokens EXACTLY equal the wanted
tokens — never a guess by token count or dict order ("KNIGHTS" fits both "Knights
Edition" and "Knights Deluxe Edition" → skip). An extra in NO page edition — a
distinguishing subtitle like "… Valhalla Edition" on the base game's page, which
has no Valhalla edition — stays a skip; a Bundle-named edition is never rescued (we
never enter bundles);
(**`[R17]` RETIRÉ le 2026-09-16 par `[R52]`** — "Microsoft Store Key" / "Microsoft Key"
n'excluent plus une clé de JEU : le motif invoqué, « MICROSOFT platform has no region
mapping », a disparu avec `[R50]` qui a mappé la famille Windows 10. Voir `[R52]` ci-dessous ;
le marqueur reste un signal de type de clé — "Microsoft Flight Simulator … Steam Key" reste
Steam) ;
year/version absent from AKS name; edition not present in the AKS dropdown;
resolved AKS page whose **editions map is empty** (stub record, zero offers —
edition unverifiable) `[R19]`; **platform unverified against the AKS page's
"official platforms" list** — a defaulted STEAM on a page that is neither
Steam-only nor publisher-direct (or lists no platforms), or an explicit title
platform that the page list contradicts (§4.4) `[R20]`.
(A `Direct Publisher` entry on the page is NOT a skip for a token-less title —
it assigns platform PUBLISHER, §4.4 `[R20]` revision.)
(A DLC bucket on the resolved AKS page is NOT a skip — it assigns the DLC
edition, §4.5 `[R18]`.)

**DLC / Add-On / Season Pass titles are ENTERED, on their own AKS page `[R43]`
(Romain GO 2026-09-11, "apprendre à ajouter les DLC … inclus les Season Pass";
historique — the former "DLC in title" / `SEASON PASS` pre-skips and the 2026-09-11
measurement : CHANGELOG 2026-09-11).** The marker (`dlc_title_marker`: SEASON PASS, EXPANSION
PASS, DOWNLOADABLE CONTENT, ADD ON, ADDON, DLC — word-boundary, plurals) is now a
**classifier**: (1) the title is resolved with the DLC / Add-On / Downloadable Content
words removed (`strip_dlc_marker`; Season / Expansion Pass words are KEPT — they are
the AKS slug, `hearts-of-iron-iv-expansion-pass-2`); (2) **the resolved page MUST carry
the DLC bucket** — a base-game page reached through a less specific slug tier, a stub
map `[R19]` or any other product is a fail-closed skip `"<MARKER> in title but AKS page
'<slug>' carries no DLC edition — base game or wrong product, not entered (R43)"`,
raised BEFORE the name guards so the reason is explicit; (3) on a DLC page the R01b
`DLC` / `SEASON PASS` qualifiers are waived (the page IS the DLC; REMASTERED/HD/
ANNIVERSARY… are not) and the marker words are not "extra words" for `[R16]` — but
the DLC's OWN words still must match the AKS name (R01 missing words / R16 extras
stay the second net: "… Crimson Moon (DLC)" on the "Tidal Wave" DLC page skips);
(4) the edition is **DLC(16)** by `[R18]`, never Standard. In-game / battle passes
("Royal Grow Pass", "Battle Pass", "Game Pass" — even tagged "(DLC)") stay the `PASS`
category skip; only SEASON / EXPANSION PASS bypass it. The list-sort router keeps the
R43 reason as "garder" (an operator call), like the old "DLC in title".
**Adversarial review 2026-09-11 (three refute lenses) hardened R43:** (a) **own-page
rule** — the DLC bucket alone does not prove the page is THIS DLC (a base-game page can
carry one, e.g. a DLC once filed under it), so a DLC-marked title is accepted only when
the resolved slug is one of its OWN tier-1 slugs (`own_page_slugs` / `resolved_on_own_page`:
the full cleaned name, apostrophe and [R42] numeral spellings, year-suffixed or legacy
shape); a resolution reached through the edition-stripped or dash-split base-game tiers
skips `"… resolved through a less specific slug tier ('hunt-showdown' is not the page of
…) — not the DLC's own page, not entered (R43)"` (historique — dry-run counts :
CHANGELOG 2026-09-11); (b) the R16 marker waiver is **gated on the DLC-page proof**
(`extra_significant_words(..., dlc_page=True)` from `match_offer` only — any other
caller still counts "DLC" as an extra word, the pre-R43 behaviour); (c) the classifier
and the stripper are **NFKC-normalised like `tokenize`** (a fullwidth "ＤＬＣ" classifies
exactly as the token it becomes, so the waiver and the guard cannot disagree) and accept
the plural / hyphenated forms ("DLCs", "Add-Ons", "Downloadable-Content"); (d) **unnamed
DLC** — a marker with no DLC name of its own ("<Game> (DLC)", "<Game> Add-On": no
subtitle left once the marker and the market noise are stripped) on a page that ALSO
sells Standard(1) is indistinguishable from the base game's own page carrying a DLC
bucket (live 2026-09-11: the Stray Blade, Aliens Dark Descent and Dragon Quest III HD-2D
Remake base pages all carry bucket 16) → skip `"… without a DLC name of its own … (R43)"`;
a DLC-only page ({16} without Standard) still enters; (e) **DLC collections are
bundles** — "DLC Pack / Collection / Bundle / Set", "All / Complete / Every DLC", "DLCs"
(`dlc_collection_marker`, direction-aware: "World's Fair Pack (DLC)" is ONE content pack
and stays a DLC) → `skip category: … (DLC collection — no bundles)`; (f) a **leading
"DLC" is a name** ("DLC Quest", a real game): no marker, nothing stripped, its own page
resolves Standard; (g) **passes**: in-game / subscription passes (BATTLE, GAME, GROW,
MONTHLY, WEEKLY PASS) stay the `PASS` skip even when tagged "(DLC)"; a tagged "<x> Pass"
("Year 1 Pass (DLC)", "Extra Pass (DLC)" — 5 MMOGA rows resolve to their own DLC page)
and the season / expansion passes (tagged or not) go to resolution; an untagged
"<x> Pass" stays the `PASS` skip as before.

**R18 for markerless titles — DURCI le 2026-09-17 (Romain : « go pour le durcissement, seul
seau DLC decide »).** Pour un titre SANS marqueur, le seau DLC ne décide QUE s'il est le SEUL
que la page propose (`len(editions) == 1`). Déclencheur : une clé Rockstar de JEU DE BASE,
« Grand Theft Auto Vice City », est entrée DLC(16) parce que sa page porte un seau DLC à côté
de Standard. Un vrai DLC caché (« Exoplanets Pack ») garde sa page mono-seau et entre juste ;
un jeu de base dont la page offre aussi Standard repart en Standard. « Standard + DLC » est un
AUTRE seau (id 518) et n'a jamais déclenché R18. Les titres MARQUÉS restent gouvernés par R43
(own-page, DLC anonyme), inchangés. Ceci REMPLACE la décision « ne pas durcir » du 2026-09-11
(historique : AGENTS.md et CHANGELOG).

**Complété le 2026-09-18 (audit complet) — `[R18]` est le SEUL juge du seau DLC.** Le
durcissement du 17 ne fermait qu'une porte sur trois : deux autres producteurs adoptaient le
seau DLC de la page par simple égalité de libellé, sans marqueur et sans la condition « seul
seau » — la vérification de page E05/R23 et la réconciliation P1-1. Reproduit : « DLC Quest »,
un vrai JEU DE BASE que le §4.3 (f) nomme explicitement, sur une page `{1: Standard, 16: DLC}`
ressortait en DLC(16) ; idem sous un seau nommé « DLC Pack » (PACK est du bruit de format, la
clé de comparaison valait {DLC}). Les deux portes écartent désormais les seaux DLC, et la
réconciliation refuse en NOMMANT R18 au lieu de mentir (« not sold on the resolved AKS page »
alors que la page le vend — motif faux, et qui alimente le routeur de tri des listes).
Invariant : après le bloc édition, `edition_id == "16"` ne peut venir que de R18.

**Console keys — see §4.12 `[R45]` (2026-09-12).** Romain's AKS feed tool OVERWRITES the
region (= region/PLATFORM) and the edition PER TARGET PAGE, so one feed row can be filed on
several AKS pages. The full rule — page model (§4.12.1: separate console product pages
`buy-<slug>-<kind>-compare-prices/`, one product id per page), classifier, multi-target
candidates, policies (P1 DECIDED by Romain on 2026-09-14, P2-P5 à confirmer), the submit
path (§6, modal v2) — lives in §4.12; the code runs under `--consoles`, the DEFAULT since
Romain's decision « 1 » of 2026-09-15 (`--no-consoles` opts out). Bucket table: §10.
Invariant (d): **one feed row = one offer, and creating it consumes the row** (our proof), so
a cross-gen key ("Xbox One / Series X|S"; "PS4 / PS5") is filed on ALL its declared pages in
ONE creation or not at all — the `[R45]` "never partial" rule (§4.12, §6). Historique (the
2026-09-11 "parked" study, the corrected finding (a) on the page URL grammar, findings
(b)-(c)) : CHANGELOG 2026-09-11 / 2026-09-12.

### 4.4 Region & platform — **URL and AKS page decide, not the title** `[Ga01]`
**MMOGA second region grammar (adversarial review 2026-09-11):** besides "<Product>
<CODE> Key", MMOGA writes the code AFTER the key word inside a trailing bracket —
"WWE 2K24 - Deluxe Edition (Steam Key EU)", "Marvel's Midnight Suns - Epic Games Store
Key [EU]", "Wild West Dynasty - Ultimate Edition [EU]", "The Sims 4 - For Rent DLC (EA App
Key EU)". `mmoga.region_code` now reads both (`REGION_CODE_TAIL_RE`; a bare "[XX]" / "(XX)"
only for a KNOWN sellable / forbidden code, so "(PC)" is not a region; a "(… Key XX)" slot
takes any code, unmapped → skip), `resolve_name` strips the tail before slug building
(historique — the 9 EU-tail offers entered GLOBAL before this rule, to correct by hand :
CHANGELOG 2026-09-11).
**A region phrase that is part of the AKS PRODUCT NAME is identity, not a lock
`[R44]`** (R43 dry-run 2026-09-11): "Age of Empires III Definitive Edition - United
States Civilization (DLC)" carries `-united-states-` in its merchant slug and the URL
scan read it as US — a GLOBAL DLC would have been entered US-locked. After resolution
`match_offer` re-checks the detected label against the page name
(`region_phrase_in_aks_name`: US ↔ "United States"/"USA", UK ↔ "United Kingdom",
EU ↔ "Europe" — whole words; "Europa Universalis" is not "Europe") and **skips**
`"region US read from 'UNITED STATES', which is part of the AKS product name … —
region ambiguous, not entered (R44)"` — fail-closed, never a guessed region. Not
applied when the merchant's own title grammar declared the region (MMOGA "… US Key",
`title_region` hook — authoritative `[R32e]`), nor when an explicit GLOBAL / EU marker
won the scan first (the `detect_region` order: hook → EU → GLOBAL → US → UK → parens).
Derive region from the offer URL when the merchant encodes it there
(e.g. Gamivo `…-steam-global` / `-eu` / `-gift-eu`; look for
`-gift-`) `[GAMIVO]`. Kinguin Steam titles often omit the region → accept as
**GLOBAL implicit** unless a forbidden region is present `[KINGUIN]`.
**Kinguin "(valid until <Month> <Year>)" and K4G / Kinguin "Steam Altergift" — Romain's
rulings (2026-09-14): « Kinguin valid until juin 2027 on rentre, Steam Altergift = Steam Gift
on rentre sous gift tous les altergifts » — reviewed decisions (AGENTS.md « Reviewed
decisions »: an audit must not re-flag them; historique, corpus counts and replays :
CHANGELOG 2026-09-14).** Rules in force: (1) the Kinguin note is an activation deadline, not
a product word — `kinguin.guard_name` strips it, and only it, from the title the `[R01]` /
`[R16]` / `[R01b]` guards and `detect_edition` read (`guard_name` hook, §4.10), `resolve_name`
peels it for the slug, `console_noise` carries it for console rows; the row is entered like
any Kinguin title (implicit GLOBAL unless a code says otherwise); ONLY the "(valid until
<Month>[,] <Year>)" spelling, anchored to the title END (`kinguin.VALID_UNTIL_RE`, `\s*$`),
is stripped — a mid-title note or any other form stays in the guard and is the fail-closed
`extra words: ['VALID', 'UNTIL', …]` skip. (2) An Altergift is a Steam GIFT:
`k4g.gift_delivery` / `kinguin.gift_delivery` → True for the whole word ALTERGIFT
(`gift_delivery` hook, §4.10) and `detect_region` layers the Steam GIFT bucket on the base
region the title / URL declare — GIFT (25) for no region / Global, GIFT EU (259) for Europe;
a US / UK base takes GIFT US (2577) / GIFT UK (2572) since `[R50]` (2026-09-16 — the buckets
were in the dropdown all along); a base a platform really lacks keeps the fail-closed "no region id"
skip; forbidden regions (North America, Americas) keep their precheck skip; `guard_name` /
`resolve_name` drop the word "Altergift" (never a product word). Fail-closed gates on (2):
the slug must AGREE (`k4g.altergift_verdict`: `-altergift-` / `-alter-gift-` in the K4G
slug; Kinguin's often-truncated slug may be silent but must not carry a `-cd-key` / `-key` /
account tail) — a `-cd-key` slug against an Altergift title is the precheck skip "K4G
delivery conflict: title Altergift but URL says cd-key (no altergift segment) — not entered"
(gift 25 or key GLOBAL 2 cannot be known from the row), a slug with no delivery segment and
the mirror conflict (title "CD Key", slug `-alter-gift-`) are refused too; « Steam Altergift
= Steam Gift » is Steam-ONLY — an Altergift whose store phrase is not Steam is "… outside
the Steam collocation — not entered", never another platform's GIFT bucket, never a plain
key; Kinguin's own "Altergift" delivery ("<Game> [<CODE>] PC Steam Altergift" → GIFT 25 /
GIFT EU 259) is covered, "Steam Gift" rows keep the generic read.
**Gamivo grammar `[R46]` (2026-09-12).** Gamivo's CURRENT grammar defeats every generic
read: the title is `<Game> [<Edition>] [<LANG>(/<LANG>)*] <Region>` — a trailing region
phrase with no separator ("Ravenswatch EN United Kingdom", "Tiny Tina's Wonderlands United
States", "FIFA 23 EN/PL/CS/RU/TR EU"), never a platform — and the URL is
`gamivo.com/product/<slug>-<platform run>-<cc>[-<langs>]-<edition>`: the EDITION token
follows the region code (`…-pc-steam-us-standard`, so the P2-6b trailing slot never fires;
a second form ends with `-pc`: `…-steam-eu-standard-pc`). `src/merchants/gamivo.py`
carries the grammar through four hooks (§4.10; historique — the six "… United States" keys
entered PUBLISHER GLOBAL(1) on 2026-09-11 before this rule, to correct by hand, listed in
`MERCHANTS.md` : CHANGELOG 2026-09-12): `title_region` (United Kingdom / United
States / EU / Global tails → uk / us / eu / global, case-sensitive: "The Last of Us" is not
US); `precheck` (any other tail → `forbidden region: <LABEL>` in the matcher's own label
vocabulary — COLOMBIA, ROW, CANADA, NETHERLANDS, NORTH AMERICA, CIS, SOUTH EAST ASIA… — so
`suggest_target_list` files them as today; no title tail → the URL code right after the
platform run decides: forbidden or unknown code → `forbidden region: <LABEL|CODE>`, a
mid-slug `us` / `uk` with no title tail → an explicit R46 skip because the generic scan
cannot read it and would enter implicit GLOBAL, `eu` / `global` → the generic scan; a
sellable tail contradicted by the URL code → skip; never a bare `-us-` anywhere, "among-us"
is safe); `resolve_name` (the tail peeled off before slug guessing); `url_platform` (the run
→ STEAM / EA / UBISOFT / BATTLENET / GOG / EPIC / ROCKSTAR; the LAST run in the path wins,
trusted only when a region code or the old `key` marker follows it; a console run → None,
the R45 classifier owns the row; nothing recognised → None → the title / R27 fail-closed
path). `-gift` in the run still yields the platform's gift bucket through `detect_region`.
The different-product guard treats a trailing **KINGDOM** as the "United Kingdom" region
phrase ONLY once every AKS-name token is covered AND UNITED precedes it — "Kingdom Come
Deliverance" / "Total War Three Kingdoms" keep their name word (never a false `extra words:
['KINGDOM']` skip). The old grammar (`…-steam-key-brazil`,
`…-steam-en-global`) keeps its P2-6 / P2-6b / MA7 behaviour. Tests: `GamivoConfigR46Tests`.
**Wyrel grammar `[R53]` (2026-09-16).** Wyrel (feed store 162, **60 pages**) writes a SLOT
TEMPLATE that parses end-to-end from the title's END, with no residue on 100/100 rows:
`<Product> [ "(" <TAG> ")" ] <EDITION> [ <PLATFORM> ] <REGION> [ "Steam Gift" ]`. The region
is a FULL NAME (Global 53, Europe 19, United Kingdom 15, United States 12, Germany 1), never
a code. `src/merchants/wyrel.py` carries five sub-rules, three of them written by the
adversarial review. `[R53a]` a title that does not parse — no readable region slot at the end
— is refused (the region is never implicit here). `[R53d]` **the two region sources must
agree**: the URL repeats the region as `region=<id>`, in strict bijection with the title slot
on the corpus (1↔Global, 4↔Europe, 8↔United States, 14↔United Kingdom, 19↔Germany, **zero
disagreement**) — no other merchant gives us a second independent source, so a PROVEN
disagreement is a fail-closed skip; the comparison is of MEANINGS, never spellings, and an
unknown id is tolerated. `[R53b]` **the platform slot "Other" IS the non-game marker** — the merchant's own word for
"no device" — and the reason names the PRODUCT (GIFT CARD / WALLET / VOUCHER / CURRENCY) so
`suggest_target_list` routes it. The rule was WIDER for a day and the data narrowed it: on
page 1 the review required three agreeing signals (slot, no `(<TAG>)` group, a
`marketplace_id` outside {2, 8}); the first real slice (pages 1-10, **990 rows**) showed
`marketplace_id` separates nothing (id 12 carries both classes) and that requiring it cost
**98 false refusals**, while a tag next to "Other" is in-game currency naming its device, not
a contradiction. The slot alone is 228/228 non-games there and never touches a key.
`[R53e]` **the platform-slot vocabulary is OPEN** and an unknown word is refused BY NAME: page
1 of 60 cannot enumerate a merchant's devices, and an unlisted "PS5" would be swallowed by the
EDITION slot and change the parse — the second source (`edition_id`, also in bijection) tells
a long edition name from an undeclared slot. `[R53c]` the edition slot passes when the shared vocabulary really
MAPS it ("Standard" → Standard(1), "Deluxe Edition" / "Digital Deluxe" → Deluxe(7)) and is
refused BY NAME when the generic read would silently FLATTEN it to Standard ("Collectors",
"Zero", "Anniversary", "Classic") — filing a collector's edition on the base game. Verdicts on the corpus: 47 pass, 48 non-game, 5 edition. Store 162
joined the safe-auto allowlist on **2026-09-24** (group B); its « Rest of the world » slot
is a `forbidden region: ROW` (§4.11). Tests: `tests/test_merchants_wyrel.py`.
**Accents folded in the categorical scans (2026-09-16).** Every skip vocabulary here is ASCII
English (`CATEGORY_SKIP`, `CURRENCY_TOKENS`, `BUNDLE_SKIN_TOKENS`, `FORBIDDEN_REGIONS`) while
the normalisers replaced any non-ASCII letter by a SPACE — so on a localised storefront
"CRÉDITS" became the junk tokens "CR" + "DITS" and the `CREDITS` entry that was already there
never matched (found by the adversarial review of GamesPlanet FR; Romain: « ça ne coûte rien
sur ce corpus mais c'est une faiblesse réelle sur toute boutique localisée »). `fold_accents`
(NFKD, combining marks dropped) now runs in every one of those scans. Folding can only make a
vocabulary word match text that MEANS it — it never invents a word, and an accented title with
no vocabulary word is untouched. Blast radius measured before shipping: on the **397 rows
carrying a non-ASCII character** across the saved runs, **0 verdict changes**. Tests:
`tests/test_accent_folding.py`.
**Microsoft game keys are no longer pre-skipped `[R52]` (2026-09-16).** Audit de Romain, le
jour même de `[R50]` : « Les régions Microsoft sont ajoutées, mais deux formulations de clés
restent bloquées avant leur résolution … Cause : ces expressions figurent encore dans
CATEGORY_SKIP. Correction : retirer ces exclusions générales pour les clés de jeux, en
conservant les refus des cartes cadeaux, abonnements et recharges. » `MICROSOFT KEY` et
`MICROSOFT STORE` quittent `CATEGORY_SKIP` : elles y étaient parce que « MICROSOFT platform has
no region mapping » (`[R17]`, §4.5), motif supprimé par `[R50]` (famille Windows 10 — Global
246 / EU 244 / US 245 / UK 249). Mesuré sur tous les runs sauvegardés : **164 lignes (34
distinctes)** étaient bloquées là, très majoritairement de vraies clés de jeu (Call of Duty ×7,
GTA V Enhanced, Skyrim Anniversary, Fallout 76, Rise of the Tomb Raider, Wasteland 3, Minecraft
Dungeons II…). **Ce qui devait rester refusé l'est, par deux entrées explicites qui remplacent
les deux retirées** (« en conservant les refus … ») : `MICROSOFT STORE ACCOUNT` / `MICROSOFT
ACCOUNT` (le mot ACCOUNT seul n'est pas un marqueur sur le chemin PC — « Mafia: Definitive
Edition … - Microsoft Store Account - GLOBAL ») et `MINECOINS` (les bornes de mot empêchent
`COINS` de matcher le mot composé — « Minecraft - 1720 Minecoins … »). Les bundles restaient
déjà pris par `BUNDLE`, et les logiciels Microsoft (Visual Studio, Project, Windows Enterprise)
partent sur le chemin LOGICIEL `[R31]`, page-dirigé. Vérifié ligne à ligne sur les 34 : 29
passent, 2 bundles, 2 Minecoins, 1 compte. Tests :
`tests/test_microsoft_category_skip.py`.
**`[R58]` Wyrel « (PC) » + AKS page Steam-ONLY → STEAM (2026-09-24, Wyrel only).** Romain :
« si une offre est marquée PC et qu'on n'a pas d'autre info, si sur la page Allkeyshop on a que
du Steam, on l'ajoutera en Steam ; si on voit qu'il y a du Epic, du Ubisoft, du EA… on skip » —
« et c'est valable que pour Wyrel, dans sa config marchand ». A merchant whose grammar says
« PC key, no store » declares it with `MerchantConfig.pc_key_without_store(name, url)` (only
`wyrel.py` does). For such a row with no platform read anywhere else, the matcher enters STEAM
iff the page's official platforms are EXACTLY {Steam}; any other official platform on the page
(Epic, GOG, Ubisoft, EA, Microsoft Windows, Xbox Play Anywhere, Direct Publisher…) leaves the
R27 / `[R51]` refusal below untouched. Every other merchant: unchanged. Measured on the 418
Wyrel « (PC) » rows seen on 2026-09-24: 217 on a Steam-only page.

**The PUBLISHER decision needs the MERCHANT's own page `[R51]` (2026-09-16).** `[R27]`
refuses a title with no platform token UNLESS the AKS page confirms `Direct Publisher`. That
exception is the hole: the AKS line describes the **GAME** (the game also exists as a
publisher key) and says nothing about what THIS merchant sells. Romain, after checking the
first Electronicfirst batch: « j ai trouve un exemple ou l on a ajoute l offre en publisher a
la place de Steam car on a pas la plateforme dans l url et du coup on aurait du ouvrir la
page », then, reproducing it on Gamivo (`resident-evil-raccoon-city-edition`, a Steam GLOBAL
key, entered PUBLISHER GLOBAL(1) by the live code): « avant de decider si publisher ou non on
doit ouvrir la page marchant pour verifier la region et l edition, si on arrive pas a ouvrir
la page marchant on skip l offre … on devrait ajouter cette securite par defaut pour tous les
marchants ». So a row whose platform is in NEITHER the title NOR the URL is now refused —
"no platform in title or URL — the AKS page's 'Direct Publisher' describes the game, not this
merchant's key, and the merchant page is not read (R51)" — unless the merchant DECLARES that
it reads its own page (`MerchantConfig.publisher_from_merchant_page`, **default False**, so
the safety is on for every merchant, config or not). No merchant declares it today: every
product page probed on 2026-09-16 is Cloudflare-403 (Gamivo, Electronicfirst, GamersOutlet,
Kinguin, Driffle) or refused outright (G2A); the merchants whose page ANSWERS 200 (Eneba,
GameSeal, Instant Gaming, K4G, MMOGA) either already resolve the platform upstream or have no
reader yet. Measured cost over every saved run: **13 distinct candidates** — MMOGA 5, Gamivo 6,
Electronicfirst 2 — against 2 360 rows that already skip on `[R27]`. Some of the 13 are
plausibly REAL publisher keys (`Minecraft - Java & Bedrock Edition`, `Fallout 76`, both MMOGA,
whose page answers 200): they become recoverable the day a merchant page reader lands, by
flipping the flag together with the reader. What R51 does NOT touch: an explicit platform
token, the Steam-only page (still the `[R27]` skip, distinct wording), the `[R20]` "no official
platforms" skip, and the `[R31]` software path (which returns earlier). Tests:
`tests/test_publisher_page_gate.py`.
**Region buckets re-verified against the live dropdown `[R50]` (2026-09-16).** Romain:
« pour les regions Rockstar on a toutes les regions dont tu as besoin meme la globale,
verifie mieux, tu dois pouvoir aller chercher ca dans le drop down des regions sur l'outil
AKS feed. » He was right, and the same defect sat on two neighbours. `REGION_IDS` is read
from the live session catalog (`catalog.json`, 867 options, IDENTICAL across the 11 catalogs
saved 2026-09-10 → 15), and three platforms were missing buckets the dropdown has had all
along — so the matcher refused rows with "no region id for <PLATFORM>/<BASE>", a **FALSE
refusal**, not a missing bucket: **ROCKSTAR** global 15 ("Rockstar (15)", the plain option IS
the global bucket — same shape as "Publisher (1)", the dropdown has no "Rockstar GLOBAL"
label), us 151, eu 152, uk 158; **EPIC** us `80us`, uk `805`; **EA** us `3us`, uk `3uk`.
Counted on every saved run: 35 Rockstar rows, 9 EA/US, 8 EPIC/US. Region LOCKS of those
families (Rockstar APAC 157 / ASIA 155 / EMEA 153 / LATAM 154 / ROW 156 / FRANCE 335 /
Germany 336 / Netherlands 337 / MIDDLE EAST 338) stay OUT — they are forbidden regions, not
bases. **The mapping alone delivers nothing**: "ROCKSTAR" was already a trailing noise PHRASE
for slug building but not a noise TOKEN, so once the region gate stopped firing first every
Rockstar row died one step later on "different/expanded product — extra words:
['ROCKSTAR']". The word joins `NOISE_TOKENS` alongside every other store word (safe: no AKS
product name in the saved corpora contains it). The two edits are ONE fix. **MICROSOFT, arbitrated 2026-09-16** (Romain: « Windows 10 pour les jeux, microsoft software
pour les logiciels »): the dropdown carries TWO Microsoft families, and they split by NATURE,
not by region. GAMES take the "Windows 10 …" family in `REGION_IDS` — Global 246 / EU 244 /
US 245 / UK 249, locks EMEA 248 / ROW 247 / FR 404 / WINDOWS DE 356 / CANADA 663 out. SOFTWARE
never reads `REGION_IDS` at all: the `[R31]` software path resolves its region from the AKS
PAGE's own options (`resolve_software_region`), which is where the "microsoft software …"
family (global 532 / eu 533 / us 534 / uk 548) already lives — the second half of the ruling
needed no code, only the arbitration. This unblocks 73 rows, all Eneba, whose merchant file
declares the platform from the `windows-store-` URL prefix. Still unmapped and still
fail-closed on purpose: the GIFT buckets the dropdown genuinely has none of (PUBLISHER, EPIC,
EA, GOG, ROCKSTAR plain gifts; a Battle.net or Ubisoft gift UK; `gmg_gift_uk`). Tests:
`tests/test_region_ids_catalog.py`.
**GamersOutlet grammar `[R48]` (2026-09-15).** GamersOutlet (feed store 31) writes a
parenthesised **delivery / region slot** on every row — `<Product> [ (<OS>) ] ( <DELIVERY> /
<REGION> ) [ <qualifier> ]` — and the slot is the LAST parenthesised group containing a "/",
not necessarily the end of the title. Two closed vocabularies follow. (1) **The region slot
is mandatory**: the merchant writes the worldwide region EXPLICITLY ("Global" in the title
20/20, "-global" as the last slug token 20/20) and never leaves it empty, so a silent title
has no proven meaning and would take the generic implicit GLOBAL — absence of slot, or a
value outside the shared vocabulary, is a fail-closed `precheck` skip (cost today: 0 rows of
20). (2) **The delivery half's store vocabulary is this merchant file's own table**
(`STORE_PLATFORM`), and `url_platform` publishes the SAME table to the matcher (the slug
carries `-<store>-key-`, 12/12 key rows) so the accepted store and the read platform can
never drift — a store outside it is "unknown store … never defaulted", which is where the
four Robux rows stop ("PC Roblox Key") and where "PC EA Key" / "PC Blizzard Key" would stop.
Software rows ("Lifetime License", 8/20) declare no store and keep the generic route (R20 /
R27 page check, then the R31 software catch-all). A left half naming a console hands the row
to the shared `[R45]` classifier — no console hook is declared. A title / URL region conflict
is refused; a slug with no region run is tolerated (the merchant's slugs are not always
faithful). Tests: `tests/test_merchants_gamersoutlet.py`.
**Electronicfirst grammar `[R49]` (2026-09-15).** Electronicfirst (feed store 70) has the
Kinguin shape — an UPPERCASE region code immediately before the final platform phrase,
`<Game> [<Edition>] [DLC] [<REGION>[ (<note>)]] <Platform phrase> <Delivery>` — plus a second
form that puts the code LAST, after the platform phrase and with no delivery word ("Mortal
Kombat: Legacy Kollection PS4 / PS5 UK"). Slot vocabulary measured on 323 rows: EU 71, US 10,
RoW 4, FR 3, EU/NA 2, NA 2, EU/US/JP 1, UK/US 1, UK 1, EMEA 1 — never a full name, never
lower case. Four fail-closed sub-rules. `[R49a]` a **partial EU key** ("EU (without DE)",
16 rows) is refused: AKS has no bucket for EU minus a country, so the row is neither EU nor
global. `[R49b]` a region word **spelled out in the product NAME while the slot is empty** is
refused — the slot is a CODE, and the generic scan would mine the name word ("Big Adventure:
Trip to Europe 9"). `[R49c]` a **CONSOLE row with an empty slot** is refused: there is no
worldwide PSN / Xbox SKU, the merchant writes the region on 73 % of its console rows against
14.5 % of its PC rows, and the generic implicit GLOBAL would have filed 7 rows worldwide
including four full games (Forza Motorsport, Forza Motorsport Premium, MSFS 2024 Premium
Deluxe, Horror Adventure PS4/PS5). `[R49d]` non-game and software listings are categorical
skips (monetary amount next to a number; "Game (e)Card" / "PSN Card" collocations, never a
bare "Card" or "Game"; "PS Plus" / "<N> Month(s)"; a quantity of "Token(s)"; licence scope
"(2 PCs)", "ISO Key" / "Bind Key", "MS <product>", a `-lifetime-` slug). **PC rows with an
empty slot keep the generic implicit GLOBAL, PROVISIONALLY**: the merchant writes no explicit
worldwide word (0 / 323), the Kinguin / MMOGA shape — but it has never been swept, so the
validity condition is pinned by a test and re-measured on every corpus: the day a slot reads
"global", the empty slot becomes ambiguous and `[R47]`'s skip applies to every silent row.
Platform stays title-sourced; no console hook (the shared classifier reads the 75 console
rows, 8 of them Xbox Play Anywhere). A "template gap" rule (double space at the slot
position) was measured, found INERT and noisy, and deliberately NOT added — see
`docs/MERCHANTS.md`. Both merchants JOINED the safe-auto allowlist on **2026-09-16** (Romain:
« On va whitelist Eletronicfirst et GamersOutlet ») — `src/admin/auto_merchants.py` is the
authority. (This sentence read « stay OFF the safe-auto allowlist: supervised dry-run first »
until the 2026-09-18 audit found the spec contradicting the code for two days.)
Tests: `tests/test_merchants_electronicfirst.py`.
**GameBoost grammar `[R47]` (2026-09-15).** GameBoost (feed store 157) writes its region
at the END of the title, in full words, and leaves the slot EMPTY on the rows whose region
is only on its own offer page — which is Cloudflare-blocked and is NEVER fetched (the
blocker that got the 2026-07-15 batch cancelled, `[R27]`). So, unlike Kinguin / MMOGA where
"no code" IS the merchant's way of writing GLOBAL, **a GameBoost title with no region word
is a fail-closed `precheck` skip, never the implicit GLOBAL(2)** — 137 of the 821 rows of
pages 1-10 (2026-09-15). `src/merchants/gameboost.py` carries the grammar through four
hooks: `precheck` (non-game listings — the game-key URLs are flat `…-00-<id>`, gift cards
and top-ups live under `/gift-cards/` and write middle dots, 175 / 821 → `console: GIFT CARD
— not a game (R45)`; then a region LOCK → `forbidden region: <LABEL>` in the shared
vocabulary; then the missing-slot skip); `title_region` (trailing `United States` / `EUROPE`
/ `EU` / `GLOBAL` → us / eu / global, read from the END so "The Last of Us" and "Europa
Universalis" keep their name words); `resolve_name` (the trailing region / platform /
delivery runs peeled — `Gift` and `Nintendo eShop` included — anchored at the end, so
"Stronghold 2: Steam Edition Steam Key EU" resolves "Stronghold 2: Steam Edition");
`console_region_slot` (the console rows use the same trailing slot). The platform stays the
generic TITLE read (`title_is_platform_source`, like Kinguin) with **no** `offer_page_resolver`
— a token-less title keeps the `[R27]` fail-closed skip. GameBoost JOINED the safe-auto
allowlist on **2026-09-16** (Romain: « Ajoute Gameboost a la whiteliste ») —
`src/admin/auto_merchants.py` is the authority. (This sentence read « stays OFF … SUPERVISED
runs only » until the 2026-09-18 audit found the spec contradicting the code.)
Tests: `tests/test_merchants_gameboost.py`.
**`MA7` RETIRED (2026-09-01, Romain: "EN = english only … on a quasi toutes les
régions qui ont leur version EN only").** A Gamivo `-en-` URL segment used to skip
as an EN-only *language restriction*; a language variant now ENTERS as the same
product. A language code (EN/FR/DE/…, `LANGUAGE_TOKENS`) counts as noise in the
different-product guard **only once EVERY AKS-name token has already been covered**
before it (nothing of the game name remains after it) — so "Hard Bullet VR Gift EN
Global" / "Neon Beats FR Global" enter, while a code with a game-name token still to
come stays a significant title word so a different (shorter) product is still caught:
"En Garde" / "The En Garde" / "Legend En Garde" ≠ "Garde"-family, "No Man's Sky" / "A
No Man's Sky" ≠ "Man's Sky" (Romain audit 2026-09-01). Position after the FULL game name is
the signal, never a global neutralization — never arm on the FIRST common/noise token (a
leading article THE/A must not neutralize the code). Historique : CHANGELOG 2026-09-01.
Audit 2026-07-17 hardenings: `gift` must be its own URL segment (`MA4` —
`the-gifted-rabbit` no longer proposes GIFT(25)); title-side defense in
depth for regions (`MA8`): bare `EUROPE` mid-title (K4G grammar) and a
region in ANY parenthesised group (not only the first) now map to EU/…
instead of implicit GLOBAL.
**Forbidden region in the URL is a skip `[P2-6]` (audit 2026-09-02).** The
`FORBIDDEN_REGIONS` scan of `precheck_skip` runs on the TITLE **and** on the URL **path**
(query stripped, merchant noise removed, word-boundary, same normalization as the title)
and returns the **same** `forbidden region: <label>` reason → identical routing — a
forbidden region encoded solely in the merchant URL (Gamivo `…-steam-key-brazil`, clean
title) must never fall to `detect_region` (which knows only sellable buckets) and become an
implicit GLOBAL. Historique : CHANGELOG 2026-09-02 (P2-6).
**Bare 2-letter region codes + the `-us` base `[P2-6b]` (audit 2026-09-02).** A forbidden
region also appears as a bare 2-letter slug code (`…-steam-key-ru`), and a US-locked key as
`…-steam-key-us` (which `detect_region` didn't read → implicit GLOBAL). Both are now caught
by `_url_region_code`, gated on a **region slot**: the code must be immediately preceded by a
region-context marker (`key`/`gift`/`code`/platform) AND **trailing** (end of the path,
optionally a merchant product-id suffix `-i123`/`-p123`). That excludes the English-word
collisions — `among-us` (`us` not marker-preceded), `lost-in-random` / `the-key-in-the-lock`
(`in` excluded + not a trailing slot), `war-thunder` (`ar` inside a word). Forbidden codes
`ru/tr/br/ar/cn/kr/jp` → `forbidden region: <FULL NAME>` (same routing); **`in` (India) is
deliberately excluded** (too collision-heavy — full `-india` is caught by the name/URL scan).
The `-us` slot sets base US, composing with P2-8 (EPIC US green gift → `gmg_gift_us`; STEAM
lacks it → fail-closed skip). Residual (pre-existing, NOT this fix): a US **plain** gift
(`-gift-us`) still enters under the global gift bucket (the plain-gift branch only
special-cases EU; there is no `gift_us` id) — flagged for future hardening.
**GMG green-gift resolves the EXACT per-base bucket, no silent global fallback `[P2-8,
R32c]` (audit 2026-09-02).** A Green Man Gaming "Green Gift" maps to the platform's
dedicated `gmg_gift` region. STEAM has `gmg_gift`+`gmg_gift_eu` (no `_us`); EPIC has
`gmg_gift`+`gmg_gift_us` (no `_eu`). `detect_region` resolves ONLY the exact per-base
bucket; a base the platform lacks → id `None` → clean fail-closed `no region id for
<platform>/<label>` skip (label and id can never disagree — never a silent GLOBAL
substitution under a "GMG GIFT US"/"EU" label), the same stance as a GOG plain gift → None.
Historique : CHANGELOG 2026-09-02 (P2-8).
**Platform declaration is word-boundary + collocation (`MA2`):** the old raw
substring, fixed-order checks let a game-name word override the merchant's
declaration ("Epic Chef … Steam Key" → EPIC, "Gogol's Quest" → GOG).
Single-word tokens (STEAM/GOG/EPIC/UBISOFT/UPLAY/ROCKSTAR) are word-boundary;
when several appear, the one collocated with the key-type marker
(`<PLATFORM> [CD ]KEY/GIFT/ALTERGIFT`) is the declaration; still ambiguous →
None and the token-less path (URL prefix R29, page-verified R20/R27) decides
fail-closed. Multi-word declarations (EA APP, **EA PLAY**, MICROSOFT STORE/KEY,
BATTLE.NET) are collocations.
**EA Play `[R38]` (2026-09-01, Driffle FC 24 escape; tightened same day, Romain
review):** "EA Play" is the EA app storefront/brand (region ids live under `EA`),
so a game key sold *on EA Play* is an EA-platform product like "EA App" —
`explicit_platform` returns `EA` for it. Both the platform detection and the
different-product guard treat it as the **exact collocation only**, NOT a broad
rule: `explicit_platform` matches `\bEA (?:APP|PLAY|ORIGIN)\b` (word-boundary, so
"EA **Player**"/"EA **Playground**" do NOT read as EA), and the guard drops `PLAY`
ONLY when it is immediately preceded by `EA` (never universal `NOISE`, so a
standalone "… Play …" stays a significant word). Anti-regression: "Foul Play" is
not tagged EA; "Foo Play Steam Key" still flags `PLAY` as an extra.

**Platform is page-verified, fail-closed `[R20]` (2026-07-08):** `detect_platform`'s
STEAM is a **default**, not a detection — a token-less title must never be entered Steam
on a publisher-direct product. The only deterministic signal is the resolved AKS page's
"official platforms:" line (extracted at resolve time, zero extra requests). Historique
(Su-27 escape) : CHANGELOG 2026-07-08.
**Revision `[R26]` (2026-07-15):** a token-less title is not trusted as Steam even when the
page list is exactly `Steam` (the merchant's own title omission is a signal); R26 defaulted
such titles to PUBLISHER and was superseded the same day by `[R27]` — historique (DCS
P-51D Mustang / A-10C Warthog escape) : CHANGELOG 2026-07-15.
**Revision `[R27]` (2026-07-15):** a token-less title with a Steam-only page has NO safe
default in either direction (the same page-signal shape carries opposite ground truths —
DCS is publisher-direct, Gameboost is genuinely Steam; Romain: *"il y a des offres steam
qu'on détecte en publisher, ça c'est seulement renseigné sur la page marchand."*). The only
signal strong enough to auto-resolve is a page that **explicitly confirms `Direct
Publisher`** (region `Publisher (1)`, the dropdown's GLOBAL bucket; EU 12, US 13, UK 266;
no gift mapping → publisher gifts fail closed). Anything short of that — Steam-only, any
other mix without Direct Publisher, or no platform info at all — SKIPs ("platform
unverifiable, not defaulted (R27)"); a human enters such cases deliberately, same as the
`R19` stub-page philosophy: absent a real signal, don't guess in either direction.
Historique (Gameboost escape, DCS revert) : CHANGELOG 2026-07-15.
**Eneba URL prefix `[R29]` (2026-07-16):** every Eneba listing URL is
`eneba.com/<platform>-<slug>`, a leading platform-prefix path segment present regardless
of what the title repeats — a token-less Eneba title is therefore not left to R27's
token-less branch when the URL declares the platform (historique — "Apothecarium" case :
CHANGELOG 2026-07-16). `explicit_platform_from_url`
checks this **only** for `eneba.com` URLs (no other merchant's URL has a
title-word this could false-positive against) and only recognizes prefixes
this codebase already has a platform constant for (`steam`, `gog`, `epic`,
`uplay`→UBISOFT, `origin`→EA, `blizzard`→BATTLENET, `windows`→MICROSOFT);
console/currency/software prefixes (`nintendo`, `xbox`, `psn`, `top`,
`other`, `riot`, …) are left unmapped — already caught by the
console/currency/software-app categorical skips before platform detection
runs. Checked as a fallback after the title (`explicit_platform(offer.name)
or explicit_platform_from_url(offer.url)`), so an explicit title token still
wins when both are present.
An **explicit** title token is the merchant's declaration and is
trusted — multi-platform pages are normal (an Osmos Steam+GoG page takes a
Steam key) — **except** when the token has a known page vocabulary
(STEAM→`Steam`, GOG→`GoG`, EPIC→`Epic Store`) and that name is totally absent
from the page list: contradiction → SKIP. Tokens without a vocabulary entry
(EA, UBISOFT, …) get no cross-check. Page vocabulary observed live (sweep 2026-07-08 over
every offer ever created/attempted; historique : CHANGELOG 2026-07-08): Steam, GoG, Epic
Store, Direct Publisher, Xbox Play Anywhere, Nintendo eShop, Xbox.

### 4.5 Edition detection (fallback hints — dropdown is truth) `[E0x]`
**Stub guard first `[R19]` (2026-07-08, DCS A-10C Warthog escape):** an
**empty** editions map on the resolved AKS page is a stub record —
`"merchants":[],"editions":[],"prices":[],"regions":[]` in the page blob,
zero offers (PHP serializes the empty map as `[]`, not `{}`). Such a page can
vouch for no edition and can hide a DLC; neither the feed row nor the page carries any
other deterministic edition signal (even mono-edition pages show `1:Standard`, and an empty
map splits hidden DLCs and legit standalones — emptiness decides nothing). Historique
(A-10C Warthog escape, 2026-07-08 measurement) : CHANGELOG 2026-07-08. **SKIP with a
distinct reason** ("AKS page carries no editions map —
edition unverifiable (R19)"), whatever the title hints say. Trade-off accepted:
a legit standalone on a stub page (e.g. K4G "Goblin Vyke") is skipped too and
stays visible in `skipped.json` for manual entry.
**Page-nature override next `[R18]` (2026-07-08, revising the 07-07 skip):**
a DLC bucket in the resolved AKS page's editions map (id 16, or name "DLC" if
the id ever moves) means the product ITSELF is a DLC — a title can hide it
with no "DLC" word ("Exoplanets Pack", "Janthir Wilds Expansion") and match
its own AKS page token-perfectly. The candidate's edition is **DLC(16)**,
never Standard, even when a Standard bucket coexists ("Brotato: Abyssal
Terrors" has both); the page's nature beats every title hint below (a "Pack"
or "Deluxe" in a DLC's own name is identity, not an edition, and the
bundle-resolution guard does not apply). Do NOT extend to Bundle/Early Access
buckets: those describe other offers listed on the page, not the product's
nature (GUILTY GEAR Xrd {Standard, Bundle} and Early Access indies stay
Standard). Systematic — the map is already in hand at resolve time. Since `[R43]`
(2026-09-11) the same bucket is also the MANDATORY proof for a title that announces
its DLC / season-pass nature — absent bucket → skip, never a base-game entry.
Otherwise, title hints:
`DLC→16`, `Complete/Complete Season→91` (≠ Deluxe), `Deluxe→7`, `Gold→10`,
`GOTY→9`, `Collection` (no Trilogy/Bundle)→98`, `Bundle/Pack/Trilogy→8`,
`Premium→34`, `Ultimate→21`, `Ultimate Collection→348`, else `Standard→1`.
"Collection"/"Gold" **in the AKS name** = part of the game name → Standard(1)
`[CORE rule 4]`. These are hints only; §4.7 overrides.

**Page-verified exception to the identity collapse `[R23]` (2026-07-13, Valve
Complete Pack escape):** "in the AKS name → Standard(1)" above assumes a
name-embedded edition word is never a real edition, but some products
genuinely sell both — AKS 831 "Valve Complete Pack" carries `{92: "Complete
Pack", 1: "Standard"}` on its own page, a real split the identity heuristic
can't see (and the generic hint id, 91 for "Complete", isn't even this page's
own id — 92). Before collapsing to Standard, check the page's own editions map
(already in hand, zero extra requests) for a non-Standard entry whose name
contains the detected label; a page-verified match wins over both the
collapse and the generic hint id. No match on the page → Standard(1) as
before. Historique (Valve Complete Pack escape) : CHANGELOG 2026-07-13.

**Two P2 fixes on R23 (2026-07-13, Romain's review):** (1) **never
page-verify a `Bundle` label** — "we never enter bundles, ever" is absolute,
so there is no legitimate page-verified Bundle tier to resurrect. Without this
guard, a title whose own AKS name happens to embed "Bundle"/"Pack"/"Trilogy"
(e.g. a Trilogy-titled standalone product) could have its page's own
Bundle-named entry picked up — either surfacing as a Candidate under a
non-`8` page id (invisible to the `edition_id == "8"` skip in §6) or getting
skipped where the offer used to pass through as Standard pre-R23; either way
a silent behavior change. (2) **pick deterministically, never by page/dict
order** — prefer an exact (case-insensitive) name match; a substring match is
only accepted when it is the sole one. Multiple distinct non-Standard entries
tied at the same specificity is a guess, not a page-verified pick — SKIP
("ambiguous page-verified edition … (R23 P2)") instead of silently taking
whichever entry the page happened to list first.

**Guessed game editions are page-verified too `[R40]` (audit 2026-09-02, P1-1/P1-2).**
R23 above only fires when the edition word is IN the AKS name. The COMMON case — the
edition is in the merchant TITLE or URL slug but NOT the AKS name — bypassed it, so
`detect_edition`'s generic hardcoded id (Deluxe→7, Gold→10, GOTY→9, …) must never be
emitted without proof that the resolved page sells that tier (a wrong-edition write would
survive human validation — "Sniper Elite 4 Deluxe" on a base-only page; a slug-parasite
`…-complete-edition`). A non-Standard game edition is RECONCILED against the page's
own map by **token-set equality modulo format noise** (`_edition_key`: strip
`Edition`/`Pack`/`Digital`/`Version` + stopwords, expand `GOTY`→`Game of the Year`): the
page edition whose distinctive tokens EXACTLY equal the guess is adopted **with the
page's real id** (a page sells Deluxe under its own id 12, labelled "Deluxe Edition");
>1 match → SKIP (ambiguous); 0 match → SKIP ("guessed edition unverified"). Not bare
equality (over-skips suffixed labels) and NOT substring (would enter a wrong tier:
"Gold"⊂"Marigold Edition", "Deluxe"⊂"Deluxe Plus Edition"). The guessed id is NOT
trusted even when it coincidentally exists on the page — it must EARN its place via the
label match, else a page listing that id under a different tier ("Winter Pack" at id 7)
would be entered under the wrong label. Runs ONLY when R23 did not already verify.
Standard(1) is the safe canonical fallback and is exempt. Historique (three
adversarial-review rounds) : CHANGELOG 2026-09-02 (R40).


**Deux portes refermées le 2026-09-18 (audit complet).**

1. **Le garde « DLC anonyme » de `[R43]`** testait la présence de Standard par la CLÉ LITTÉRALE
   « 1 », alors que le reste de la même fonction le teste par le NOM. Une page dont le Standard
   s'appelle « Standard + DLC » (id 518, vu vivant) ou vit sous un autre id ouvrait donc le garde
   et un DLC ANONYME entrait. La spec dit « a DLC-only page ({16} without Standard) still
   enters » : le garde se déclenche maintenant dès que la page porte un seau AUTRE que le seau
   DLC. La variante « tester Standard par le nom » a été évaluée et REJETÉE — « Standard + DLC »
   ≠ « STANDARD », elle rate justement le cas le plus plausible.

2. **Le sauvetage par « extras »** court-circuite `detect_edition` (branche `elif` du bloc
   édition). Or les mots de PALIER (DELUXE, ULTIMATE, GOLD, GOTY, PREMIUM…) sont dans
   `NOISE_TOKENS`, donc ils n'entrent jamais dans `extras` : un titre « <Jeu> Deluxe
   <qualificatif> » pouvait être adopté sous le seau du qualificatif, palier PERDU — une écriture
   de mauvaise édition. Le seau adopté doit désormais porter les paliers que le **marchand
   ajoute** — ceux du titre MOINS ceux du nom AKS, sinon « Ultimate Admiral: Age of Sail » ou
   « Homeworld Remastered Collection » seraient refusés à tort — comparés via `_edition_key` pour
   que l'alias GOTY ↔ « Game of the Year » ne fasse pas rater une adoption correcte. Sinon :
   skip `(R39)` avec un motif distinct et routable.

### 4.6 URL hygiene
The merchant URL is kept **complete, exactly as the feed carries it** — never
strip query params in artifacts or reports. G2A is not the only merchant with
meaningful params (Romain, 2026-07-08): Kinguin rows carry
`?nosalesbooster=1&currency=EUR`, G2A carries `?uuid=…&___currency=…`
(stripping G2A → 404) `[R21]`. Row identity in the submitter compares the URL
*path* internally (`_url_key`, §6 step 2) — a comparison key, never a rewrite
of the stored or displayed URL. Fidelity includes entity decoding: `data-offer`
blobs decode with browser attribute semantics (only `;`-terminated references),
so a raw `&currency=EUR` in a query string survives instead of becoming
`¤cy=EUR` (`unescape_attribute`, seen live on Kinguin 2026-07-08). Verify the
URL domain matches the merchant (e.g. must contain `kinguin.net` for Kinguin)
`[KINGUIN]`.

**Every HTTP request to allkeyshop.com carries the `AKS/Staff` User-Agent — by default
(2026-09-11).** `http_get` switches to `AKS_STAFF_UA` for any allkeyshop.com host when no
UA is given (an explicit UA is honoured; the staff UA stays forbidden on any other host,
audit #4). Rule for humans and agents alike: **never send the Chrome UA to AKS over HTTP**
(curl included: `-A AKS/Staff`; the official probe is `scripts/13_aks_ping.py`) — the AKS
anti-bot bans the VPS IP for hours on browser-UA HTTP probes; CDP browsing keeps the Chrome
UA, that is a different channel. Historique (IP ban of 2026-09-11) : CHANGELOG 2026-09-11.

### 4.7 AKS resolution

**URL shapes per guessed slug (Romain 2026-09-10).** Pass 1 probes the current shape
`buy-<slug>-cd-key-compare-prices/` for every slug tier (most → least specific). Pass 2,
for the MOST specific slug only, probes `buy-<slug>-<year>-cd-key-compare-prices/` for this
year and next (AKS pages created since 2026 carry the release year, e.g. `buy-fable-2026-…`;
skipped when the slug already ends with a year), then the legacy
`compare-and-buy-cd-key-for-digital-download-<slug>/` (≈2021 pages such as Minecraft) —
bounded to +3 probes per unresolvable offer (probing every shape of every tier drove
~300 req/min and 503 bursts). `MA1` holds: a 5xx / transport failure on a guessed page is
retried ONCE on the same URL after 2 s, then raises — never a lower tier; a 429 is never
retried. Account kinds keep their single shape (`aks_page_urls`, `_probe_guessed_page`,
`src/matcher.py`).

**L'index sitemap — passe 3 (2026-09-22) et « sitemap d'abord » (2026-09-24).** `src/aks_sitemap.py`
relève le sitemap d'AKS (55 `page-sitemap*.xml`, UA `AKS/Staff`, `Crawl-delay` 0,5 s) dans
`state/aks_sitemap.json` : 213 525 pages `buy-<slug>-<gabarit>-compare-prices/` et, depuis le
24/09, les **154 pages anciennes** `compare-and-buy-cd-key-for-digital-download-<slug>/` dans
une liste À PART (`legacy`, `legacy_indexed`). Il ne fait autorité que **frais (≤ 7 jours) et
complet** ; sinon `sitemap_index()` rend `None` et le matcher se comporte exactement comme
avant lui. Quand il fait autorité :
- **Passes 1-2, sitemap d'abord** (Romain : « go pour le matching sitemap d'abord ») : on ne
  sonde que les formes que l'index CONFIRME — `has_page(<slug>-<gabarit>)` pour les formes
  courante et année, `has_legacy(slug)` pour la forme ancienne (gardée telle quelle si l'index
  ne l'a pas cherchée). **Soupape** : la toute première sonde (tier 1, forme courante) part
  toujours, confirmée ou non — le sitemap est une photo et une page neuve porte le nom complet
  du jeu (`buy-the-front-cd-key` répondait 200 le 24/09, absente du relevé du 23, présente dans
  celui du 24). L'ordre des tiers et `MA1` sont intacts : une réponse douteuse sur une sonde
  gardée lève toujours immédiatement. Mesuré sur les 24 000 lignes du scan tous-magasins du
  21/09 qui passent le precheck : **2,82 → 1,16 sonde par offre (−59 %)**, une offre sans page
  passe de 4,58 sondes à **une seule**, et les 14 006 résolutions simulées sont identiques.
- **Passe 3** : les gabarits de clé que les passes 1-2 ne sondent pas (`-key`, `-game-code`,
  `-download-code`) et la même question à la ponctuation près (`flat_page`), jamais une page
  compte ni console. Une URL déjà sondée en passe 1-2 n'est pas re-sondée.
- **La recherche R30 n'est plus appelée** (morte depuis le 22/09 : `HTTP 200`, corps vide).
- `match_meta.json.sitemap_first` dit pour chaque page si le mode était actif, contre quel
  relevé, et combien de sondes il a évitées (`probes_skipped`) ou laissées à la soupape
  (`valve_unconfirmed`).

**Le risque qui reste, dit franchement : la fraîcheur.** Une page créée par AKS après le
relevé n'est trouvée que par la soupape — si son slug est celui du nom complet. Sous un autre
tier, elle attend le relevé suivant ; la ligne reste en liste 9 (« pas de page AKS ») et l'export
de tri, qui lit le même index, peut l'envoyer en 22. **Relevé automatique depuis le 24/09**
(Romain : « oui pour le refresh auto ») : `scripts/10_data_entry_auto.py --sitemap-refresh` — que
la console passe TOUJOURS — relève l'index avant la première page s'il a plus de **20 h**, s'il
manque, s'il est troué ou s'il ignore les pages anciennes (`aks_sitemap.ensure_fresh`). Écriture
atomique (le matcher le relit à chaque page), jamais une halte : un réseau en panne ou un relevé
troué laisse l'index complet précédent en place et le recap le dit (`sitemap_refresh`). À la
main : `python3 scripts/16_sitemap_index.py --refresh`. Passé 7 jours sans relevé, le mode se
coupe tout seul.

**Une page coupée par une erreur PASSAGÈRE est refaite (2026-09-24, Romain : « pour Wyrel j'ai
dû relancer 3 fois, tu vois pas le pb ? » puis « go pour les deux correctifs »).** Les trois
arrêts du 24/09 étaient passagers et sans écriture en jeu : deux pages du feed muettes 20 s à
l'extraction (`CdpTimeoutError`), un `net::ERR_CONNECTION_REFUSED` avant tout clic. `run_sweep`
refait désormais la page — ré-extraction, match, approbation, saisie — après une pause de 2,
puis 5, puis 10 min (`SweepConfig.transient_retry_waits`), au plus trois fois, puis la halte
d'avant. Seulement quand RIEN n'a pu être écrit : un extract en échec (lecture seule) sur une
signature passagère (`TRANSIENT_SIGNATURES` : `CdpTimeoutError`, `net::ERR_CONNECTION_REFUSED /
RESET / CLOSED / TIMED_OUT / EMPTY_RESPONSE / NETWORK_CHANGED / INTERNET_DISCONNECTED /
ADDRESS_UNREACHABLE / NAME_NOT_RESOLVED`, la sonde de départ comprise), un submit arrêté
`feed_unreadable_prewrite`, ou un submit dont le scan d'index d'avant la première offre a
échoué (`aborted="feed_unreadable"`). Restent des haltes IMMÉDIATES : l'état INCONNU après un
clic (`feed_unreadable`), une déconnexion (`not logged in`, `not_logged_in`), le garde,
`ten_consecutive_failures`, un échec de match ou d'approbation. Les offres créées avant la
coupure sont prouvées : elles restent au compte de la page, et les traces d'écriture de la
tentative coupée sont gardées (`submit_plan.try1.json`, `submit_report.try1.txt`,
`approved.try1.json`). La mesure de couverture de la tentative coupée est effacée, sans quoi
la reprise passerait pour une page « déjà vue » et serait sautée. « Arrêter » reste immédiat
pendant une pause (tranches de 5 s au plus). Chaque reprise est inscrite dans l'entrée de page
(`transient_retries`) et comptée au recap.

**Une page déjà entièrement vue n'est pas rejouée (2026-09-24, Romain : « go pour sauter les
pages vides »).** Le feed d'AKS renvoie parfois la même centaine d'offres pour des numéros de page
différents : le 24/09, Wyrel a lu cinq fois les mêmes lignes (pages 45 → 41) et retenté
« Conclave », qu'AKS refuse à chaque fois, sur quatre pages ; Kinguin a 44 pages sur 120 dans ce
cas, GameSeal 51 sur 208. `run_sweep` saute désormais le matching, la saisie et le déplacement
d'une page dont TOUS les ids ont déjà été servis dans le même balayage (`skipped_repeated: true`)
: chacune de ses offres a déjà été matchée, puis saisie ou refusée. Une page partiellement neuve,
ou sans mesure (`offer_ids` absent ou en échec), est traitée comme avant. La couverture reste
dite honnêtement (`incomplete_repeated_pages`) : sauter une page ne fait pas voir les lignes
qu'AKS n'a jamais servies.

**Throttle guard (2026-09-09, audit/critic).** Below the per-slug rule `MA1` (a
transient answer on a *guessed* slug raises immediately → per-offer skip "AKS probe
unreliable"), the match stage has a stage-level STOP: the **first `429`** on any AKS
probe (guessed slug, site-search GET, or a search-fallback slug), or
**`THROTTLE_MAX_CONSECUTIVE_UNRELIABLE` = 5 consecutive unreliable probes on distinct
AKS pages** (a repeat of the same failing page does not count; any clean resolution
resets) — after **one grace** (Romain 2026-09-10: sleep `THROTTLE_GRACE_S` = 30 s, retry
that offer once, abort only if it still fails; never for a 429; at most
`THROTTLE_MAX_GRACES` = 2 per run) — raises `AksThrottled`. `scripts/03_match.py` then exits **2** with stdout
`{"aborted": true, "reason": "aks_throttled"}`, logs `match_aborted`, writes only the
sidecar `match_aborted.json` (no candidates/skipped/match_meta) — so a safe-auto sweep
halts `match_failed_p<N>` with the reason in its recap instead of recording a throttled
page as clean. Below the bar, `match_meta.json.probe_unreliable` counts the unreliable
skips (and the sweep page entry carries `probe_unreliable`). A non-200 site search other
than 404/410 is unreliable, not "no result". The by-urls preview (scripts/11) applies the
same rule to its URL resolves (`recap.aborted = aks_throttled`; a 429 is never retried).
**R30 circuit breaker (Romain 2026-09-10; expire depuis le 2026-09-20 — §4.7):** site-search failures never count toward the
abort (they say nothing about the product pages AKS throttles); after
`SEARCH_CIRCUIT_BREAKER_FAILURES` = 3 consecutive search failures (timeout / empty body /
5xx) in one run, the search is not called again for the rest of that run — offers whose
guessed slugs all 404 are then "no AKS product page found" without the 20 s wait, and
`match_meta.json.search_circuit_open_offers` counts them (a second pass once AKS search
works again is worthwhile); `search_failures` and `throttle_graces` are recorded too.
**Sweep-scoped persistence (Romain GO 2026-09-10, "gagner du temps"):** `scripts/10` hands
`03_match --search-circuit-file <sweep>/search_circuit.json`; a page that trips the breaker
arms the file, the next pages start with the circuit OPEN (`search_circuit_preopened`, no
3 × timeout tax per page), a page whose search was actually called and never failed clears
it. **No expiry (Romain 2026-09-10):** once open, the breaker stays open for the REST OF THE
SWEEP — the pages never re-probe the search mid-sweep; the offers left unresolved by the URL
guesses stay in the pending feed and are simply picked up by the next sweep of that merchant.
The file lives in the sweep directory, so a new sweep always starts with the search on.
`AKS_SEARCH_TIMEOUT_S` = 8 s (a slow answer was never a useful one; historique — the 20 s
timeout and the 2026-09-09 measurement : CHANGELOG 2026-09-10).
Build the slug from the AKS name (lowercase, `[^a-z0-9] → -`), verify
`/blog/buy-{slug}-cd-key-compare-prices/` returns **200**, then extract
`data-product-id` (the AKS_ID) and `<title>`. Extract available editions from
the embedded `"editions":{…}` JSON `[EDITIONS.md]`.
**A transient (403/429/5xx/timeout) or name-unreadable answer on ANY guessed
slug raises IMMEDIATELY (`MA1`, audit 2026-07-17):** slug tiers go from most
to least specific, so collecting the failure and letting a less-specific
tier's 200 win would silently resolve the wrong product tier (a deluxe title
landing on the base page). Historique : CHANGELOG 2026-07-17 (MA1).
**Markup drift is loud (`MA6`):** a `"prices"` block that is PRESENT but no
longer parses raises `AksPageUnparseable` → distinct skip ("AKS page markup
drifted"), never a silent empty tuple (which would have disarmed the since-retired
R25 duplicate guard). Absence stays soft — stub pages legitimately serialize
`"prices":[]`, and absent editions/platform lines are already covered
fail-closed by R19 (empty map → skip) and R20/R27 (no platform info →
token-less skip).
**If the AKS product name cannot be read from the resolved page, the offer is
SKIPPED with a distinct reason — never fall back to the offer title as the AKS
name** (that turns the §4.1 identity check into a tautology; 2026-07-07 a
Microsoft Store Key offer surfaced as a "Steam US" candidate this way) `[R15]`.
**Duplicate guard `[R25]` — RETIRED (Romain 2026-09-08, reviewed decision).** An offer
that is still in the **pending feed is TO BE ADDED, period** — the matcher never
second-guesses it against the page's own `"prices":[…]` table (the page merchant id is not
the feed `store_id`; staleness is covered by the stable pending feed + submit-time
prove-gone). `prices` is still extracted (price routing / diagnostics) but is never a skip
source. Do **not** re-add the guard — rationale in AGENTS.md « Reviewed decisions »
(historique — the 2026-07-15 guard and the Phantom Blade Zero false skip : CHANGELOG
2026-09-08).

The extracted editions map doubles as a product-nature check: DLC bucket
present → the product is a DLC → edition DLC(16) per §4.5 `[R18]`. Systematic
— the map is already in hand at resolve time (zero extra requests) — not "on
suspicion" only. An **empty** map is a stub record → SKIP per §4.5 `[R19]`
(stub pages serialize it as `"editions":[]` — the object-only extraction
yields `{}` there by design). The same resolve pass extracts the page's
"official platforms:" list (`extract_official_platforms`) that feeds the §4.4
platform gate `[R20]`.

**Site-search fallback `[R30]` (2026-07-16):** when every guessed slug 404s
(deliberately no LLM/APIv2 resolution step — a model call is not
deterministic and would sit upstream of every other check in this stage;
resolution stays plain HTTP + regex, arbitrated by the same R01/R01b identity
gate as everything else), fall back to AKS's own WordPress search
(`/blog/?s={cleaned title}`, 20s timeout — the endpoint is slow, 5s starves
it) before giving up. Extracts up to 3 product-page slugs from the results
HTML and probes each exactly like a guessed slug — same `_resolution_from_body`
path, same downstream §4.1/§4.1b checks. Only runs after slug-guessing is
**cleanly exhausted** (every candidate 404/empty) — a transient probe failure
(`AksProbeUnreliable`) or an unreadable page name (`AksNameUnreadable`) still
fails closed and never reaches search, same as before. Romain flagged the
real risk directly: AKS pads a weak/no-match search with unrelated "top
games" filler, so a search hit is **not** trusted on its own — it is just
another candidate page, subject to the exact same R01/R01b identity checks as
a guessed slug — search only ever *proposes* a page, it never bypasses the identity gate
(historique — live verification on an Eneba batch : CHANGELOG 2026-07-16).

**`[E06]` L'édition retenue doit être VENDUE par la page (2026-09-21, Romain : « normalement
tu es censé aller voir la page AKS comme pour les jeux normaux, voir si on est en standard ou
en DLC sur cette page »).** Dernier contrôle du bloc édition, après tous ses producteurs : si
l'id retenu n'est pas une clef de la carte d'éditions de la page, la page à **un seul seau**
l'impose (une page `{5: Early Access}` entre en Early Access — « toutes les offres seront
rentrées en early access à la place de standard »), et **plusieurs seaux sans correspondance**
est un refus fail-closed qui NOMME ce que la page vend. Le seau **DLC(16) est hors périmètre**
— [R18] en est le seul juge et émet son id canonique même si la page range son DLC sous un
autre id. Ce qui l'a imposé : Standard était exempté de toute vérification de page
(« the safe canonical fallback »), et « Diablo IV Lord of Hatred » est entrée Standard sur une
page `{16, 7, 21}` qui ne vend pas Standard — 5 des 10 premières écritures Difmark, 1 page sur
60 chez GameSeal. La branche console appliquait déjà la règle à ses pages cibles (§4.12).

**Le disjoncteur R30 EXPIRE (2026-09-20).** Le marqueur persisté (`search_circuit.json`, dans
le dossier du balayage) reste de portée balayage, mais il n'est plus éternel :
`SEARCH_CIRCUIT_TTL_S` = 30 min, au-delà la page suivante re-sonde la recherche et ré-arme le
fichier si elle échoue encore. Ce qui l'a imposé : le balayage `20260919-082932` a ouvert le
disjoncteur **66 secondes** après son démarrage (5 échecs pendant Gamivo), 7 heures avant que
GameSeal ne commence — ses 60 pages ont donc résolu au slug seul, sans jamais chercher, et
**434 offres distinctes** en sont ressorties « no AKS product page found ». Un audit relira le
commentaire du 10/09 (« sweep-scoped and has no expiry ») et voudra restaurer l'éternité :
c'est périmé, la décision d'origine précédait les balayages de 30 h à plusieurs marchands.

### 4.8 Limits & doubt
Max **100** candidates by default unless Romain asks otherwise `[S26]`. Doubt
after investigation → **SKIP**, do not ask `[G02]`. The live WP-admin dropdown is
the source of truth for region **and** edition; static tables are only a guide
`[CORE rule 7][P06][E04]`.

Implemented in `src/matcher.py` + `scripts/03_match.py` (read-only GET resolve).
Candidates are for Romain's validation, never auto-submitted; short forbidden
tokens (NA/OTHER/SEA) are excluded from the SKIP list to avoid title collisions.

### 4.9 Software entry — page-driven licence edition `[R31]` (2026-08-11)

Romain revised the R22 "software is games-only, always skip" rule: **software AKS
actually sells IS entered**, provided we resolve its **region and — above all —
its licence edition** from the AKS page itself, never a guessed default. Software
editions are licence types (`OEM`, `Retail`, `1 PC`, `5 PC`, `Lifetime License`,
`1 Month`, `LTSC …`, `N Edition`) and some pages carry **no Standard at all**
(Adobe Creative Cloud = `1 Month` / `3 Months`), so the game "default to
Standard(1)" would enter a **non-existent** edition — the exact bug this rule
fixes.

Flow in `match_offer` (after the AKS page resolves, **before** the game platform
gate R20 — a software key has no Steam/Publisher token and software pages often
list no `official_platforms`):

1. **Classify** `is_software(offer, resolution)` = a software brand/category token
   in the title (`is_software_title`) **or** the page carrying a software-only
   label (`_SOFTWARE_PAGE_EDITION_MARKERS`: OEM/RETAIL/LTSC/N EDITION/LIFETIME
   LICENSE/MICROSOFT ACCOUNT BIND/PHONE ACTIVATION). Both are precise — no game
   carries a software brand or an OEM/RETAIL edition, so **games are untouched**.
2. **Name gate** still applies: `missing_aks_words` must be empty (the offer
   contains the product name → no wrong-product match, e.g. "Windows 11 **Home**"
   ≠ the "Windows 11 **Pro**" page). The game-tuned `extra_significant_words` /
   `dangerous_qualifier` gates are **skipped** for software (a licence title
   legitimately adds version/edition words the concise AKS name omits).
3. **Edition** `resolve_software_edition`: the page edition **label** appearing in
   the merchant title, **longest wins** ("Retail 5 PC" over "Retail"/"5 PC");
   exactly one longest → take it; a tie → **skip**; none in title → take it only
   if the page has a **single** edition, else **skip** (Adobe with no duration,
   Bigasoft with Standard + 1-PC-Lifetime → we do NOT guess).
4. **Region** `resolve_software_region`: exact page filter-name match, else a
   unique substring (offer `GLOBAL` inside page `PUBLISHER GLOBAL`), else a single
   page region; anything ambiguous → **skip**. The page region **id** is used
   (`GLOBAL` = 532 "Microsoft Software", `PUBLISHER GLOBAL` = 1), never the generic
   per-platform id.
5. Build `Candidate(platform="SOFTWARE", …)` (the R25 duplicate check that used
   to sit here is RETIRED — Romain 2026-09-08, see the Duplicate guard note above).

`extract_regions` (`AksResolution.regions`) exposes the page region dropdown. The
list-**sort** console is unaffected — it still groups software under the Softwares
list via `is_software_title` (no page fetch). Doubt still goes to skip `[G02]`.

### 4.10 Per-merchant config — "start from the merchant config" `[R32]` (2026-08-11)

**Override hooks `[R32e]` (Romain 2026-09-10 — « un fichier de config marchand par
marchand, qui peut ajouter, overwrite, modifier des comportements génériques »).** Besides
its data fields, a `MerchantConfig` may carry optional pure functions of the feed row
(no network, no `src.matcher` import) — four PC-side hooks and, since 2026-09-14, four
console-side hooks; the matcher / classifier calls each FIRST and falls through to the
generic rule when it returns `None`, so the generic modules stay merchant-agnostic:
- `precheck(name, url) -> reason | None` — an extra categorical skip, evaluated right after
  the domain check and before the generic console / forbidden-region / category scans;
- `title_region(name) -> "eu" | "us" | "uk" | "global" | None` — the region the merchant's
  title grammar declares; **authoritative when it speaks** (the merchant's URL is derived
  from the same title, the generic URL/title scan cannot know better);
- `resolve_name(name) -> str` — the text handed to AKS resolution (slug guessing + site
  search) instead of the raw title; the identity checks (`[R01]`, `[R16]`) keep the RAW
  title, so a hook can never launder a title past the name gate;
- `url_platform(url) -> platform token | None` — the platform the merchant's URL grammar
  declares; consulted FIRST by `explicit_platform_from_url`, before the
  `url_platform_prefixes` / `url_platform_scan` modes (Gamivo `…-pc-steam-us-standard`,
  `[R46]` 2026-09-12); None falls through;
- `guard_name(name) -> str` (2026-09-14) — the title the identity guards (`[R01]` missing
  AKS words, `[R16]` extra words, `[R01b]` dangerous qualifier) and `detect_edition` read for
  a PC row: the RAW title by default (every merchant without the hook, unchanged); a merchant
  whose grammar appends a note that is NOT a product word strips that note — and only it.
  The hook never launders a title: the words it leaves are still compared with the AKS
  name, an empty answer falls back to the raw title. Romain's rulings of 2026-09-14: Kinguin
  "(valid until <Month> <Year>)" — « Kinguin valid until juin 2027 on rentre » (trailing
  only, review fix); the delivery word "Altergift", K4G and Kinguin — « Steam Altergift =
  Steam Gift on rentre »;
- `gift_delivery(name, url) -> bool | None` (2026-09-14) — the merchant's OWN gift-delivery
  verdict, consulted first by the region scan and layered by `detect_region` as the
  platform's GIFT bucket (Steam 25 / 259 / 2577 / 2572, Battle.net 570 / 567 / 568, Ubisoft
  501 / 504 / 505 — US / UK mapped by `[R50]` 2026-09-16; a base a platform really lacks keeps
  the fail-closed "no region id" skip); True / False wins, None → the
  generic read (a `gift` URL segment, " GIFT " / "GIFT)" in the title). K4G / Kinguin: a
  "… Steam Altergift" row whose slug agrees → True (Romain: « on rentre sous gift tous les
  altergifts »). The hook reads BOTH arguments — a title / URL delivery conflict (title
  Altergift, slug `-cd-key`) or a non-Steam Altergift is never a verdict: it is the merchant
  `precheck`'s fail-closed skip (review fixes 2026-09-14, §4.4), so no row is filed under a
  bucket class the row itself contradicts.
First user: MMOGA (`src/merchants/mmoga.py`, §11 — the first three). Gamivo uses the first
four (`src/merchants/gamivo.py`, §4.4 `[R46]`); Kinguin and K4G add `guard_name` +
`gift_delivery` (2026-09-14). Tests: `MerchantHookTests` (throwaway merchant, the six
hooks) + `RulingGatesLiveRegistryTests` + `MmogaRulesTests` + `GamivoConfigR46Tests` +
`tests/test_merchants_{kinguin,k4g}.py`.

**Console hooks `[R45]` (2026-09-14 — Romain's rule, repeated since 2026-08-11, ultimatum
2026-09-14: « pour la détection région / édition / plateforme, tu as un fichier de config
par marchand. Et si tu ne l'as pas, tu dois l'avoir »).** The R45 classifier
(`src/console_keys.py`, §4.12.3) used to embed the MMOGA / Gamivo / Eneba URL grammars
(category segments, URL runs, leading store segment) and merchant host checks. That is
merchant grammar, so it moves into the merchant files; `console_keys` keeps ONLY the shared
vocabulary (families, title phrases, store / delivery markers, the region-text → base
table, the shared hyphen-run read, `console_marker_in_url`) and consults the merchant
config through the registry. Four more optional members of `MerchantConfig`, all pure
functions of the feed row:
- `console_url_families(url) -> tuple[family, ...] | str | None` — the families the URL
  DECLARES, in order (a subset of XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2),
  or a fail-closed skip-reason string (`"console: Xbox 360 (R45)"`, `"console: PC-only
  Xbox Live key (R45)"`, `"console: <MARKER> — not a game (R45)"`), or `None` (the URL
  says nothing); the generic classifier consults it ONLY when the title declares no
  family (MMOGA category segments, Gamivo runs, Eneba store prefix + runs, Kinguin /
  Difmark account URLs);
- `console_pc_declared(name, url) -> bool` — the merchant declares PC / Windows next to
  the console platform (Gamivo `-pc` / `-windows` runs, Eneba `-windows-` run); the
  generic title-phrase check (`/ Windows`, `PC/XBOX …`, `(Xbox Series X/S, PC)`) stays
  generic and is OR-ed with it;
- `console_region_slot(name) -> str | None` — the region TEXT the merchant writes next to
  the platform phrase, verbatim (`"US"`, `"CA"`, `"Europe"`, `"United Kingdom"`, `"Hong
  Kong"`, `"EUROPE"`); the mapping text → base (uk / us / eu / global) or forbidden label
  stays in `console_keys` (shared vocabulary). When absent, the classifier falls back to
  its shared tail / bracket reads;
- `console_noise: tuple[str, ...] = ()` — merchant phrases stripped from `resolve_name` in
  addition to the shared store / delivery markers (`"Download Code"` MMOGA, `"Digital
  Key"` / `"Digital Code"` Driffle, `"CD Key"` Kinguin); a compiled pattern is accepted for
  the forms a literal cannot spell — Kinguin's "(valid until <Month> <Year>)" note
  (`kinguin.VALID_UNTIL_RE`), noise since Romain's ruling of 2026-09-14 (§4.4).
**Registry.** The binding merchant name → module (`merchant_config()`) lives in
`src/merchants/registry.py`, imported by both `src/matcher.py` (which keeps re-exporting
`merchant_config`) and `src/console_keys.py` — no circular import (`python3 -c "import
src.matcher, src.console_keys, src.merchants.registry"` must pass); `console_keys` never
imports `src.matcher`, a merchant file never imports either. **Every merchant of the
safe-auto allowlist has its file** — `kinguin.py` (the inline `domain="kinguin.net"`
registry entry moves there), `k4g.py`, `driffle.py`, `gameseal.py`, `allyouplay.py`,
`cjs.py` are created on 2026-09-14 next to `mmoga.py`, `gamivo.py`, `eneba.py`,
`g2a.py`, `instant_gaming.py` (`difmark.py` parked); a file that declares no hook yet
(Allyouplay, CJS-CDKeys: never swept, no data) is the documented statement "no data, dry-run
first", never an omission. Per-merchant grammar and hooks: [`MERCHANTS.md`](MERCHANTS.md).
Historique (the before / after measurement of the 2026-09-14 move — 2 990 console rows
identical, 0 recorded candidate changing class — and the per-merchant table) : CHANGELOG
2026-09-14.

Romain: **each merchant should start from its own config** — its specific
instructions. `src/merchant_config.py` `MerchantConfig` is the single declarative
place; `match_offer` reads `merchant_config(offer.merchant)` and applies it. A
merchant with **no** config keeps the generic behaviour (platform/region/edition
from the feed title + URL) — since 2026-09-14 that is only the fallback for a merchant
OUTSIDE the safe-auto allowlist: every allowlisted merchant has its file (Romain's rule
above), and « la grammaire marchande ne vit jamais dans un module générique ».

Rationale: IG lists Steam keys under **token-less** feed titles on multi-platform AKS
pages, so R27 alone would default them to Publisher — the real platform lives only on
**the IG offer page** (`data-platform="Steam"`). Historique (the IG sweep entered
PUBLISHER) : CHANGELOG 2026-08-11.

`MerchantConfig` fields (migrated incrementally, no regression on Difmark/Gamivo/
Eneba which keep their existing code, now *represented* in the config):
- `domain` — the offer URL must be on this host (Kinguin → kinguin.net);
- `url_ignore_substrings` — URL boilerplate stripped before URL-derived signals
  (Difmark → `buy-console-account-`);
- `offer_platform_resolver(offer_url) -> platform token | None` — when the platform
  is not in the title, read it from the merchant's **own offer page**. Instant
  Gaming → `resolve_ig_offer` (reads `data-platform`, maps via `IG_PLATFORM_TEXT_MAP`;
  an unrecognized value → **skip**; an unreadable page → **skip** `[R32]`). The
  edition stays in the feed title (game path); the AKS page platform gate `[R20]`
  then verifies the page-read platform normally.

Fail-closed: a token-less IG offer never defaults to Publisher — it either enters
with the page-read platform or skips. New merchants that need page-read
platform/region get a config entry, not scattered `if merchant == …` branches.

**Platform cross-check extended (R32, 2026-08-13):** the R20 page cross-check now
covers **Ubisoft/EA/Battle.net** too (`PAGE_PLATFORM_NAMES` += `Ubisoft Connect` /
`EA app` / `Battle.net`; AKS vocabulary verified live). A page-resolved platform
enters ONLY when the AKS page lists it, else fail-closed skip — closes the gap
where an IG Ubisoft/EA/Battle.net offer entered on a Steam-only AKS page.
`extract_official_platforms` also fixed (it truncated `Battle.net`→`Battle` at the
first `.`, losing the rest of the list).

**Instant Gaming REGION `[R33]` (2026-08-13 — was a KNOWN LIMITATION, now solved).**
IG feed titles/URLs carry no region, and the IG page's region *dropdown* is
JavaScript-rendered (invisible to `http_get`). But the region IS in the page's
static `<title>` / `og:title` **trailing segment** — `"… - PC (Steam) - Latin
America"` (no suffix = worldwide). `extract_ig_region` reads that suffix, so **no
CDP/headless is needed** (historique — 32/54 region-locked IG offers entered GLOBAL before
this rule : CHANGELOG 2026-08-13). The page is fetched ONCE per
offer (same fetch that reads `data-platform`), with a normal browser UA (never the
AKS staff UA off-AKS). Unreadable page → fail-closed skip.

**Region is resolved even when the title declares a platform, and both the platform
AND the region fail closed (audit, Romain 2026-08-14).** Two hardening fixes on top
of R33:
- **Resolve unconditionally** (`e6e9a2c`): the offer-page resolver runs for a
  configured IG offer even if the feed title already carries a platform token — the
  region is NEVER in an IG title, so gating on `declared_platform is None` would let a
  region-locked `"…Steam…"` title default to implicit GLOBAL (R33's exact bug class).
  Region-safety must not depend on platform-resolution.
- **Verify, don't blindly trust, the platform** (audit #1): if the title declared one
  platform and the page (authoritative for this listing) another, that CONFLICT is a
  fail-closed skip — not a silent trust of the title.
- **Region parse fails closed** (audit #2): `extract_ig_region` is now tri-state — a
  region label, `""` for a POSITIVELY-worldwide title (`"… (<Platform>)"` with no
  suffix), or **`None`** when no `og:title`/`<title>` carries the recognizable
  `"(<Platform>)"` anchor (layout change / malformed / reordered metadata). A `None`
  region raises → the caller skips. Worldwide now needs a positive signal; a missing
  or unparseable region **never** silently defaults to GLOBAL.
- **The worldwide anchor is validated as a real platform** (audit #2b, 2026-08-14): a
  trailing `"(…)"` is trusted as the platform anchor ONLY when its content names a
  platform (`_IG_TITLE_PLATFORM_KEYWORDS` — Steam / Epic / GOG / Ubisoft / EA /
  Battle.net / Xbox / PlayStation / Nintendo …, keyword containment). So a decorator
  parens like `"Game (Deluxe)"` / `"(2007)"` no longer reads as worldwide → GLOBAL;
  an unrecognized parens → `None` → skip.

### 4.11 Region policy & blacklist — MERCHANT-AGNOSTIC `[R34]` (2026-08-13)

Romain 2026-08-13: *"on est sur Global, Europe et US. Le reste, on skippe et
certaines régions qu'on va blacklist, comme les Latam, le Brésil et les régions
d'Asie"* + *"les régions russes aussi"*. Three dispositions for a resolved region:

- **ENTER** — `Global` / `Europe` / `US` / `UK` (Romain confirmed 2026-08-13: UK
  enters like Europe). A sellable base region ⇒ candidate with that region id.
- **BLACKLIST** — `LATAM` / `Latin America` / `Brazil` / `Argentina` / other Latin
  countries, `Asia` (+ China / Japan / Korea / India / SEA countries), `Russia` /
  `CIS` / `RU`. ⇒ routed to the **Blacklist** list (8) so it leaves the entry feed.
- **SKIP (garder)** — any other non-sellable region (`ROW` / `North America` /
  `Turkey` / `EMEA` …). Left in place; the operator decides. **ROW spelled out
  (2026-09-24)**: « Rest of World » / « Rest of the World » are the same lock as the
  `ROW` code — in the generic scan (`FORBIDDEN_REGIONS` → `forbidden region: REST OF
  WORLD`) and in the shared merchant vocabulary (`src/merchants/common.py` → `ROW`).
  Before, only the code was known: CJS « … Steam Key: Rest of World » read an implicit
  GLOBAL(2) (3 rows of the 21/09 scan, none ever written) and Wyrel's 161 « Rest of the
  world » rows were refused for the wrong reason (`[R53a]`, title unparsable). Romain,
  same day: *a ROW key enters only if it is proven to activate in Europe* — neither the
  title nor the URL proves it, and the merchant page that might (Wyrel) is behind
  Cloudflare. The five regions with a
  dedicated list (`Australia`→32, `Canada`→33, `Middle East`→34, `Africa`→35,
  `South America`→36) still route there.

**One source of truth, no page fetch when the region is already known** (Romain:
*"si on connaît déjà ta région, on peut te trier"*). The blacklist lives ONLY in
`aks_lists.suggest_target_list`, keyed on the `forbidden region: <label>` skip
reason. Whether the region came from the **feed title** (Kinguin `Brazil` → skip in
`precheck_skip`, no page opened) or an **offer page** (Instant Gaming, `match_offer`
emits the same `forbidden region: <label>` reason), routing is identical. Matching is
keyword-containment (+ bare `RU` token) so wording variants (`Russia & CIS`) still
route; it runs only on an already-non-sellable region, so it can never touch a
`Global/EU/US/UK` offer. Decisions (Romain 2026-08-13): UK **enters** like Europe;
the bare `South America` label **keeps its list 36** (LATAM/Brazil/Argentina still
blacklist). Remaining open item: a merchant whose region is neither in the title nor
page-resolved (e.g. a Kinguin bare 2-letter `BR`) is NOT detected today → it still
defaults GLOBAL; such a merchant needs its own region source (config resolver) before
a sweep, exactly like IG got one.

**La région est la DERNIÈRE chose déclarée (audit complet, 2026-09-18, `[P1]`).** Le balayage
des noms de pays s'appliquait au texte ENTIER — titre et chemin d'URL — sans exiger de créneau :
tout jeu dont le NOM contient China / India / Japan / Ukraine / Poland était refusé
« forbidden region: <PAYS> », puis routé par `suggest_target_list` vers la **Blacklist (8)**.
Cinq lignes G2A réelles, toutes GLOBAL dans le titre ET dans l'URL, le prouvaient :
« Assassin's Creed Chronicles: China », « Crusader Kings II: Rajas of India », « Cities:
Skylines … Modern Japan », « Ukraine War Stories », « Civilization VI - Poland Civilization
and Scenario Pack ». Dans un sweep `--triage --move-execute`, chaque page s'auto-autorise
(`[R36]`, §14) et `is_blacklist_label` fait sauter la vérification présent-sur-cible : des jeux
vendables sortaient physiquement du feed vers la Blacklist, sans revue et sans preuve.

**Correction du 2026-09-19 (Romain) : on part de la DERNIÈRE occurrence du pays, pas de la
première.** Le premier jet lisait `find`, donc un verrou RÉPÉTÉ disparaissait : « Assassin's
Creed Chronicles **China** Global Steam Key **CHINA** » s'arrêtait au CHINA du NOM DU JEU, voyait
GLOBAL après lui, concluait « nom de produit » — et la clé verrouillée Chine entrait en
GLOBAL(2), chez Kinguin comme chez Gamivo. La règle dit « la région est la dernière chose
déclarée » : il faut donc partir de la dernière.

Règle : un nom de pays suivi, plus loin dans le même texte, d'un **marqueur de région vendable**
(GLOBAL / WORLDWIDE / WW / EU / EUROPE / US / USA / UK) appartient au NOM DU PRODUIT, pas au
créneau. Ce qui reste refusé : « … Steam Key BRAZIL », « Hades RUSSIA PC Steam CD Key », et —
c'est le point qui protège le `[P1]` du 2026-09-06 — « Cyberpunk 2077 Global Steam Key BRAZIL »,
où le verrou vient APRÈS le mot vendable. Aucun pays n'est retiré de `FORBIDDEN_REGIONS` : le
verrou dans le slug reste attrapé, et les deux scans gardent leur défense en profondeur.
La même règle gouverne le TROISIÈME site du même défaut : le strip itératif de `cleaned_title`
amputait « Rajas of India » en « Rajas of » une fois GLOBAL / KEY / STEAM retirés — mauvaise
page AKS sondée même le precheck corrigé.

**Le miroir langue / verrou est vérifié par test (même audit).** Le commentaire de
`_REGION_LOCK_LANG_CODES` revendique de miroiter la décision P2-6b (« the SAME trailing code a
forbidden region ») — or `TH` figurait dans `_URL_FORBIDDEN_CODES` depuis le 2026-09-06 sans y
être ajouté : le même code était verrou dans l'URL et langue dans le titre. `TH` rejoint
l'ensemble, et l'invariant `LANGUAGE_TOKENS ∩ codes URL ⊆ _REGION_LOCK_LANG_CODES` est
désormais verrouillé par test, pour qu'il ne puisse plus dériver. Les autres codes de langue qui
nomment aussi un pays (DE, IT, ES…) ne sont PAS ajoutés : le faux positif « (Without DE) » est
documenté dans `MERCHANTS.md`, et `id` a été écarté comme trop collisionnel — ce sont des
décisions prises, pas des oublis.

### 4.12 Console keys — region/platform, console pages, multi-target candidates `[R45]` (2026-09-12)

**Trigger (Romain 2026-09-12).** The AKS feed tool OVERWRITES the region (and the edition)
PER TARGET PAGE, where "region" means region/PLATFORM — one feed row can be filed on several
AKS pages in ONE creation (modal v2, §6). This section supersedes the 2026-09-11 "PARKED"
study (§4.3). The code runs under `--consoles` — **the DEFAULT since 2026-09-15** (Romain's
decision « 1 »); `--no-consoles` is the PC-only opt-out. Real console writes are allowed
(Romain's GO of 2026-09-15 after the modal v2 was observed with `--inspect` and proven by
two canaries — one target, then two). **P1 is DECIDED** (Romain 2026-09-14: « clé PS5 seule
= page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch et Switch 2 »); P2-P5
below are still **à confirmer par Romain** (listed in §12). Historique (the opt-in / default
OFF phase of 2026-09-12 → 14, the "`--consoles` requires `--dry-run`" guard of 2026-09-14,
the adversarial review of 2026-09-12 fixed on 2026-09-14, the canaries) : CHANGELOG
2026-09-12, 2026-09-14, 2026-09-15.

**4.12.1 Page model — verified read-only 2026-09-12 (UA `AKS/Staff`).** AKS has SEPARATE
console product pages: `buy-<slug>-<kind>-compare-prices/`, kind ∈ `ps4` / `ps5` /
`xbox-one` / `xbox-series` / `nintendo-switch` / `nintendo-switch-2` (PC = `cd-key`).
Each is its own product — own `data-product-id`, own name ("Hades PS5", "Hades Xbox
Series", "Hades Nintendo Switch"), own region map and editions, and NO "official
platforms" line (empty). Hades: PC **26712** · PS5 **85105** (regions `88ps5h` PS5,
`88ac`) · PS4 **85104** (`88` GLOBAL, `454`) · Xbox Series **85103** (`300`, `302`,
`470`, `306`, `241`, `471`, `301`) · Xbox One **85102** (`24`, `24eu`, `436`, `306`,
`241`, `24ac`) · Switch **47979** (`99` GLOBAL). (Historique — the 11/09 probe with a wrong
URL grammar : CHANGELOG 2026-09-12.)
- **The tab bar is the platform list of the game.** Every page (PC and console) carries
  `<ul class="aks-offer-tabulations">`: the current page as `<span class="active"
  title=" PC"><meta data-itemprop="platform" content="PC"/>`, every other platform as
  `<a href="https://www.allkeyshop.com/blog/buy-<slug>-<kind>-compare-prices/"
  class="inactive" title=" PS5">`; the game-info "Platforms" table
  (`game-info-table-label`) lists the same set. `extract_console_pages(body) -> {kind:
  url}` and `extract_page_platform(body)` → the ACTIVE tab's platform ("PC", "PS4",
  "PS5", "Xbox One", "Xbox Series X", "Switch") or "" read them into
  `AksResolution.console_pages` / `AksResolution.page_platform`. A tab can point to ANOTHER
  product (Elden Ring → "Elden Ring Tarnished Edition Nintendo Switch 2") — hence the
  identity check of 4.12.4 (g).
- **The regions map is an offers-present list, not a platform list**: Hades' PC page has
  Xbox One / Series tabs but no `300` bucket. Platform existence is read from the tab
  bar, never from the regions map. Page-side `filter_name` and modal labels differ for the
  same id (page `300` = "XBOX X|S GLOBAL", modal = "Xbox Series (300)"; page `306` =
  "XBOX/PC") — match by **id only**, never by label.
- **Play Anywhere is page-verifiable on the PC page**: `official platforms:` contains
  "Xbox Play Anywhere" (Forza Horizon 5: `Microsoft Windows, Xbox Play Anywhere, Xbox,
  Steam`; Hades: `Xbox Play Anywhere, Epic Store, Steam`; Street Fighter 6: `Xbox, Steam`
  — no; Elden Ring: `Steam` — no). PA offers live under the XBOX/PC buckets
  (`306`/`241`/`242`/`240`) on the PC page AND on the Xbox One / Xbox Series pages (Hades:
  `306`×4 on all three pages; Forza PC: `306`×62, `241`×48, `270`×6, `471`×1, all
  `activationPlatform=xbox-play-anywhere`). No feed spells "Play Anywhere": merchants
  write "/ Windows", "PC/XBOX …", "(Windows/Xbox Series X|S)", "Xbox One, PC".
- **Modal buckets** (867-entry catalog, byte-identical in the 9 catalogs of 10-12/09):
  the family × base-region table is in §10 (`CONSOLE_REGION_IDS`). Absent = fail-closed:
  **no PS5 EU/US/UK** (PS5 = the single `88ps5h`), no console gift bucket. Ids are
  strings and 182 keys are non-numeric (`24eu`, `88ps5h`, `99eu`…): `resolve_catalog_id`
  resolves them through the **id path** (verified on the live catalog:
  `('GLOBAL','306')`, `('PS5','88ps5h')`, `('EU','24eu')`). **BOM facts** (catalog
  `20260912-080120-auto`): the `306` master label carries a leading U+FEFF
  (`"\ufeffXbox/PC GLOBAL (306)"` — the rendered option has none and sorts last) and it is
  the ONLY region label with one; ten edition labels (`337`, `452`, `480`, `573`,
  `1155`, `1448`, `1583`, `4bo`, `5bo`) and one edition KEY (`"\ufeff1380"`) carry one
  too — the Selectize `region_query` / `edition_query` are typed WITHOUT the BOM (§6).
- **Switch 2 (2026-09-14).** AKS Switch 2 product pages EXIST (kind `nintendo-switch-2`:
  "Street Fighter 6 Nintendo Switch 2" id **188436**, "ELDEN RING Tarnished Edition
  Nintendo Switch 2" id **188441**, bodies saved in the R45 scratchpad) and their offers
  use the **Nintendo family bucket** (regions map `{99: GLOBAL}`, prices region `99`,
  `activationPlatform nintendo-eshop`): the PAGE carries the platform, the BUCKET the
  region. `SWITCH2` is therefore a family of its own (page kind `nintendo-switch-2`)
  with the SAME bucket ids as SWITCH (`99` / `99eu` / `99us` / `992`); the 2026-09-12
  "console: Switch 2 has no AKS bucket (R45)" skip is retired.

**4.12.2 Vocabulary.** **Family** = a console platform, a `REGION_IDS` key like the PC
platforms: `XBOX_ONE`, `XBOX_SERIES`, `XBOX_PC` (the Play Anywhere target), `PS4`, `PS5`,
`SWITCH`, `SWITCH2` (`CONSOLE_FAMILIES`; SWITCH2 since 2026-09-14). Xbox 360 is recognised
by the classifier → skip (no bucket). **Region base** = global / eu / us / uk; forbidden regions take the
same paths as PC (§4.11). **Bucket** = the modal "region" id = region/platform.
**Target** = (family, AKS product page (id, url, name), bucket (label, id), edition
(label, id)). **Anchor page** = the PC page when it exists (existing resolution: slug
tiers + R30 search), else the console page of the primary declared family guessed by slug
(`page_kind` = kind; no R30 search for console kinds — like accounts).
`CONSOLE_PAGE_KIND`: XBOX_ONE → `xbox-one`, XBOX_SERIES → `xbox-series`, XBOX_PC →
`cd-key`, PS4 → `ps4`, PS5 → `ps5`, SWITCH → `nintendo-switch`, SWITCH2 →
`nintendo-switch-2`. `CONSOLE_PLATFORM_LABEL`: "Xbox One", "Xbox Series X|S", "Xbox / PC
(Play Anywhere)", "PS4", "PS5", "Nintendo Switch", "Nintendo Switch 2".

**4.12.3 Classifier — `src/console_keys.py`** (pure: `re`, `dataclasses`,
`urllib.parse`; NO import of `src.matcher`; since 2026-09-14 it reaches the merchant
config through `src/merchants/registry.py` — **shared vocabulary in `console_keys` +
per-merchant hooks**, §4.10 "Console hooks": the module holds no merchant grammar and no
merchant host / name check any more). `classify_console(name, url, merchant) ->
ConsoleSignal | None` returns `None` when the row carries NO console marker at all (title
tokens XBOX / PLAYSTATION / PS4 / PS5 / PSN / NINTENDO / SWITCH, or
`console_marker_in_url(url)`), else a frozen `ConsoleSignal`:
- `families`: the families DECLARED by the merchant, in order of appearance,
  deduplicated, among XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2 (never
  XBOX_PC);
- `pc_declared`: the platform phrase names PC / Windows( 10| 11)? next to a console family
  ("Xbox Series X|S / Windows", "PC/XBOX One/Series X|S", "(Xbox Series X/S, PC)",
  "(Windows/Xbox Series X|S)", "Xbox One, PC") — the shared title-phrase read — OR the
  merchant's `console_pc_declared(name, url)` hook says so (Gamivo `-pc` / `-windows`
  runs, Eneba `-windows-` run — merchant grammar, in the merchant file since 2026-09-14);
- `resolve_name`: the title without its platform / store / region markers, **edition
  KEPT** ("FIFA 23 - Ultimate Edition ( Xbox One / Series X|S Download Code ) - EU" →
  "FIFA 23 - Ultimate Edition") — it feeds the slug guess AND the R01 / R16 / R01b guards
  and `detect_edition` (PC rows keep `offer.name`). Removed: the platform phrase and its
  brackets ("(Xbox One / Series X|S Download Code)", "[PS5]", "(PS4 / PS5)"), the
  shared store / delivery markers (XBOX LIVE, PSN, NINTENDO ESHOP, MICROSOFT STORE, CD
  KEY, KEY, GIFT) plus the merchant's own `console_noise` phrases ("Download Code" MMOGA,
  "Digital Key" / "Digital Code" Driffle, "CD Key" Kinguin — declared
  in the merchant file since 2026-09-14), the region tails (" - EU", "[EU]", "(Europe)",
  "EU Key", "Europe" before the platform; Gamivo's "EN United Kingdom" tail — language
  codes included — is Gamivo grammar, peeled by `gamivo.py`'s `resolve_name` hook, no
  Gamivo regex left here), then separators are normalised ("Game - - EU" → "Game").
  Verified on the 40 raw rows of the feed study (tests);
- `skip_reason`: a fail-closed "console: … (R45)" string, or `None`;
- `region_base` / `region_label` / `region_words` (review fix 2026-09-14) — the REGION
  SLOT of the merchant's console grammar: `region_base` a sellable base (global / eu /
  us / uk) or `None`; `region_label` the label of a declared region AKS does not sell
  (CA → "CANADA", AU, TR, AR, ZA, "Hong Kong"…) or `None`; `region_words` the region
  words the classifier removed from `resolve_name`, so the matcher can refuse an
  implicit read that would silently drop them (4.12.4 (c)). The slot TEXT comes from the
  merchant's `console_region_slot(name)` hook when the file declares one (verbatim —
  Kinguin / K4G the word before the platform phrase, Driffle the first parenthesis, G2A /
  GameSeal the " - <REGION>" tail, Eneba the word after "<STORE> Key", MMOGA " - EU" /
  "[EU]" / "(… Key EU)" / "EU Key", Gamivo the "[<LANGS>] <Region>" tail — 2026-09-14),
  else from the shared tail / bracket reads on the SAME furniture runs `resolve_name`
  strips (`resolve_name_and_regions(name) -> (name, words)`); the mapping text → base is
  SHARED vocabulary and stays here: EU / EUROPE / EUROPEAN UNION → eu, US / USA / UNITED
  STATES → us, UK / GB /
  UNITED KINGDOM → uk, GLOBAL / WORLDWIDE / WW → global; the 2-letter codes mirror MMOGA
  `FORBIDDEN_CODES` (+ CA / AU / ZA / NA / CO / SG / HK / IN / DE / AT / NL / RO; `EU/NA`
  → "EU NA", the matcher spelling); a full or unknown name → its upper-cased text
  (CANADA, NORTH AMERICA, HONG KONG, ROW, EU WEST, EU/UK…). Any forbidden / unknown
  word wins the label; two DIFFERENT sellable bases in one slot ("EU (European Union +
  UK)", "… - USA (…) Key EUROPE") → both `None` with `region_words` set — the matcher
  skips (never a guessed base). 2-letter codes are UPPERCASE-only ("Hell is Us", "The
  Last of Us Part I EU PS5" → eu).

*Title grammar* (whole-word, case-insensitive, `X|S` ≡ `X/S` ≡ `XS`): XBOX_SERIES ← "Xbox
Series X|S", "Xbox Series X/S", "Xbox Series X", "Xbox Series", "Series X|S" (after "Xbox
One /"); XBOX_ONE ← "Xbox One" / "XBOX One"; cross-gen "Xbox One / Series X|S", "Xbox One
/ Xbox Series X|S", "XBOX One/Series X|S", "Xbox One & Xbox Series X|S", "Xbox One, Xbox
Series X/S" → (XBOX_ONE, XBOX_SERIES); PS5 ← "PS5", "PlayStation 5"; PS4 ← "PS4",
"PlayStation 4"; "PS4 / PS5", "PS4/PS5", "PS4 & PS5" → (PS4, PS5); SWITCH ← "Nintendo
Switch" not followed by "2"; SWITCH2 ← "Switch 2" / "Nintendo Switch 2" (2026-09-14).
Review fixes 2026-09-14 (R45): a BARE "Series" (optionally "X" / "S") right after "Xbox
One" + separator ("Xbox One/Series", "Xbox One & Series", "(Xbox One / Series)") is
normalised to the canonical "Series X|S" BEFORE parsing → (XBOX_ONE, XBOX_SERIES) with a
clean `resolve_name` (a bare "Series" anywhere else stays a name word — "World Series of
Poker"); a console run that OPENS the title and is followed by a plain word is part of
the GAME NAME ("Nintendo World Championships: NES Edition …", "Nintendo Switch Sports
…", "Xbox Fitness (…)", "PlayStation All-Stars Battle Royale …") — kept in
`resolve_name`, never a declaration; when it is the ONLY title run the URL grammar
decides, with the mirrored name tokens dropped from the slug start
(`nintendo-switch-sports-cd-key` → "no declared generation", `…-nintendo-switch-cd-key`
→ SWITCH); "<Game> - Nintendo Switch 2 Edition" (ONE platform item immediately followed
by "Edition") is a product-NAME suffix kept in `resolve_name`, not a declaration (the
R01 / R16 guards compare it with the AKS page name as usual).
*URL grammar* (ONLY when the title declares no family) — **shared vocabulary in
`console_keys` + per-merchant hooks (2026-09-14, R32 / R45).** The classifier asks the
registry for the merchant's `MerchantConfig` and calls `console_url_families(url)`: a
tuple → the declared families; a `"console: … (R45)"` string → that skip; `None` → the URL
says nothing (→ "console: no declared generation (R45)" when the title declared nothing
either); hook absent → the shared hyphen-run read below. The module no longer tests the
host (`mmoga.com` / `gamivo.com` / `eneba.com`) nor the merchant name — the grammars
that used to live here (`_parse_url_mmoga` / `_MMOGA_CATEGORY_RULES` /
`_MMOGA_NON_GAME_CATEGORY_RE`, `_parse_url_gamivo`, `_parse_url_eneba` + the leading
store-segment drop, `_GAMIVO_LANG_TAIL_RE`) are declared by the merchant files
([`MERCHANTS.md`](MERCHANTS.md)):
- shared (`console_keys`, every merchant): hyphen-delimited runs `xbox-one`,
  `xbox-series-x-s` / `xbox-series-xs` / `xbox-series`, `ps4`, `ps5`, `ps4-ps5`,
  `playstation-4/5`, `nintendo-switch(-2)?` — never a "one" followed by a game word; a
  merchant hook may apply this shared read to its own cleaned path (Eneba after dropping
  its store prefix; Kinguin / K4G / Driffle / G2A / GameSeal slugs mirror the title);
- `mmoga.py` — category segment: `Xbox-Live/Xbox-One-Game-Keys` → XBOX_ONE,
  `Xbox-Live/Xbox-Series-XS-Game-Keys` → XBOX_SERIES,
  `Playstation-Network/Playstation-5-Game-Keys` → PS5, `…/Playstation-4-Game-Keys` → PS4,
  `Nintendo/Switch` → SWITCH. The category gives the LOWER generation only — a cross-gen
  "Xbox One / Series X|S" row is filed under `Xbox-One-Game-Keys`; the title phrase is
  what declares both. `Xbox-Live/Xbox-360-Game-Keys` → "console: Xbox 360 (R45)"; card /
  subscription categories (`PSN-Cards-*`, `Nintendo-eShop-Cards`, `Playstation-Plus`,
  `Xbox-Live-Cards`, `Xbox-Live-Gold`) → "console: <MARKER> — not a game (R45)";
- `gamivo.py` — URL run after the slug: `xbox-xbox-series`, `xbox-series`,
  `xbox-xboxseries` → XBOX_SERIES; `xbox-xbox-one-series`, `xbox-xboxoneseries`,
  `xbox-one-series` → (XBOX_ONE, XBOX_SERIES); `xbox-xboxone`, `xbox-one` → XBOX_ONE;
  `ps-ps5`, `psn-ps5` → PS5; `ps4-ps5` → (PS4, PS5); `nintendo-nintendo-switch` → SWITCH;
  `xbox-pc` alone → "console: PC-only Xbox Live key (R45)"; suffixes `-pc`, `-windows`,
  fused `windows` (`xboxserieswindows`, `xboxoneserieswindows`) → `console_pc_declared`;
- `eneba.py` — the leading `xbox-` / `psn-` / `nintendo-` segment is a STORE prefix,
  never a generation (`xbox-one-last-breath-…` is not an Xbox One row) and is dropped
  first; then `-xbox-series-x-s-` → XBOX_SERIES, `-ps4-ps5-` → (PS4, PS5), `-ps5-` /
  `-ps4-`, `-nintendo-switch-2-` → SWITCH2 (2026-09-14; was a skip), `-nintendo-switch-`
  → SWITCH; `-windows-xbox-series-x-s-` → `console_pc_declared`; `-pc-xbox-live-key-` →
  "console: PC-only Xbox Live key (R45)"; an `xbox-…-xbox-live-key-` WITHOUT a generation
  → `None` → "console: no declared generation (R45)";
- `kinguin.py` — `-account` / `-online-account-activation` → "console: ACCOUNT — not a
  game (R45)" / ACCESS; `difmark.py` — `/buy-console-account-…-account-<id>` → "console:
  ACCOUNT — not a game (R45)" (the ACCOUNT title word itself is a shared marker);
- `k4g.py`, `driffle.py` (`xbox-series-xs` spelling, `-p<id>` ignored), `g2a.py`
  (`-i<id>` ignored), `gameseal.py` — the shared runs on their slug; `allyouplay.py`,
  `cjs.py` — identity only (`domain`, to confirm at the first dry-run; never swept, no data).
`console_marker_in_url(url) -> bool` = a console token in the URL PATH (XBOX /
PLAYSTATION / PSN / NINTENDO / PS4 / PS5 as hyphen- or slash-delimited segments; not
SWITCH alone) — the fix of the Gamivo leak below.

*Fail-closed skips of the classifier* (`skip_reason`), all of the form "console: … (R45)":
- ~~"console: Switch 2 has no AKS bucket (R45)"~~ — RETIRED 2026-09-14: "Switch 2" /
  "Nintendo Switch 2" / `-nintendo-switch-2-` declare the `SWITCH2` family (enterable on
  the `nintendo-switch-2` page, Nintendo buckets; historique : CHANGELOG 2026-09-14);
- "console: Xbox 360 (R45)" — "Xbox 360" (shared title read), MMOGA
  `Xbox-Live/Xbox-360-Game-Keys` (`mmoga.py` `console_url_families`);
- "console: <marker> — not a game (R45)" — whole-word GAME PASS, XBOX LIVE GOLD, XBOX
  LIVE CARD, XBOX GIFT CARD, PSN CARD, PLAYSTATION (NETWORK )?(CARD|CREDIT|PLUS|STORE
  CARD), PS PLUS, PLAYSTATION PLUS, (NINTENDO )?ESHOP CARD, NINTENDO SWITCH ONLINE, "<x>
  Access" (Kinguin, URL `-online-account-activation`), ACCOUNT as a whole word ANYWHERE
  in the title ("Madness Beverage (Account) Standard Edition") or **`account` as a
  standalone token ANYWHERE in the URL path** (URL-decoded, split on non-alphanumerics,
  query ignored — `console_keys.url_path_account_token`; the end-anchored `-account` /
  `-account-<digits>` suffix of 2026-09-14 missed Gamivo's
  `…-xbox-one-series-account-global-standard`, entered as an « Xbox One Game Code » key on
  2026-09-24 — see « ACCOUNT offers » below), the MMOGA card / subscription
  categories. Since 2026-09-14 the title markers are shared vocabulary while the URL
  markers are merchant grammar returned as "console: <MARKER> — not a game (R45)" by
  `console_url_families` (`kinguin.py`, `difmark.py`, `mmoga.py`). V-BUCKS / VC / POINTS
  etc. stay covered by `CATEGORY_SKIP` upstream (§4.3);
- "console: PC-only Xbox Live key (R45)" — Gamivo `xbox-pc` alone (`gamivo.py`), Eneba
  `-pc-xbox-live-key-` (`eneba.py`) — both through `console_url_families` (a PC key sold
  through Xbox Live / Microsoft Store is neither a console offer nor a proven Play
  Anywhere one);
- "console: no declared generation (R45)" — a console marker without any family: Eneba
  "<Game> XBOX LIVE Key <REGION>" (**704** of its 1 376 console rows carry no generation
  in title OR URL), bare "PSN", bare "Nintendo" **[P4]**;
- "console: unparsed platform residue (R45)" (2026-09-14, `SKIP_RESIDUE`) — a SERIES /
  ONE token still glued to a separator once the platform phrase is removed ("/Series",
  "& Series", "(Series", "Series)", "One /"): the grammar did not parse the whole phrase
  → never a partial console entry. A balanced standalone "(Series)" / "(One)" is a name
  ("Get Them Out! (Series)", 2 real Eneba rows) and "-" / ":" / plain-word neighbours are
  exempt (0 residue rows in the latest batches);
- "console: product name suffix '<Platform label> Edition' contradicts the declared
  platform <FAMILY[/FAMILY]> — not entered (R45)" (2026-09-14) — a "<Game> - Nintendo
  Switch 2 Edition" name suffix filed under ANOTHER declared platform (MMOGA
  `/Nintendo/Switch/` category, a title run naming another family): the declaration and
  the name disagree → skip, never resolved in either's favour.

`console_page_identity(aks_name) -> str` strips the page-name suffix ("Hades Xbox Series"
→ "Hades", "Hades PS5" → "Hades") so a console page can be compared to the anchor.

**4.12.4 Matcher integration (`src/matcher.py`).**
1. `REGION_IDS.update(CONSOLE_REGION_IDS)`; `PLATFORM_LABEL.update(CONSOLE_PLATFORM_LABEL)`
   → `validation_io` and `/api/meta` accept the families automatically.
   `PAGE_PLATFORM_NAMES` is unchanged (no R20 / R27 on console rows; `sw=False`).
2. `precheck_skip(offer, *, consoles=False)`: the console scan = a title token
   (`CONSOLE_TOKENS`, as before) OR `console_marker_in_url(offer.url)` — **the URL scan is
   active in EVERY mode**. `consoles=False` → `"console"` (byte-identical for titles; new
   for URL-only rows — the Gamivo / Eneba leak fix). `consoles=True` → `sig =
   classify_console(...)`: its `skip_reason` is returned; then a declared region the
   grammar could not map to a sellable base (`sig.region_label`) returns "forbidden
   region: <LABEL>" — the PC wording, same router (review fix 2026-09-14; historique :
   CHANGELOG 2026-09-14); otherwise the
   remaining scans (forbidden regions, categories, bundles, skins…) CONTINUE as usual
   and `None` is returned. Position: that of the current console scan.
3. `AksResolution` gains `console_pages: dict[str, str]` (kind → url, from the tab bar)
   and `page_platform: str` (filled in `_resolution_from_body`). `resolve_aks_url(url,
   http_get_fn=http_get) -> AksResolution | None`: a throttled GET of one KNOWN page URL
   through `_probe_guessed_page` (404/410 → `None`; unreliable → `AksProbeUnreliable`;
   the slug is read from `buy-(.+?)-(?:<kinds>)-compare-prices`). `match_feed` wraps it in
   a `_ThrottleGuard(shared=<main guard>)` when the production resolver is used — ONE
   consecutive-unreliable count, one grace budget and one `stats` dict across anchor
   probes and page reads, so the sweep aborts after THROTTLE_MAX_CONSECUTIVE_UNRELIABLE
   unreliable probes on distinct pages whichever resolver they hit (review fix
   2026-09-14 — never two independent guards; historique : CHANGELOG 2026-09-14).
4. `match_offer(..., page_resolver=resolve_aks_url, consoles=False)` — the console branch
   (consoles=True, `classify_console` not `None`, no `skip_reason`), at the AKS-resolution
   point:
   a. `families = sig.families`; `guard_name = sig.resolve_name` (R01 / R16 / R01b and
      `detect_edition` read `guard_name` instead of `offer.name`; PC rows: `guard_name =
      offer.name`, unchanged);
   b. `dlc_title_marker(offer.name)` → skip "console: DLC / season pass on console — not
      entered yet (R45)" **[P5]**;
   c. region (review fix 2026-09-14 — NEVER an implicit GLOBAL for a region word the
      merchant wrote; historique : CHANGELOG 2026-09-14):
      `detect_region_base(offer) -> (base, label, implicit, gift)` is the generic
      title/URL read (`detect_region` and `detect_region_base` both read the shared
      `_detect_region_parts` scan, which carries the merchant `title_region` hooks — R46
      Gamivo: "Ravenswatch EN United Kingdom" + `…-xbox-xboxoneseries-uk-standard` → uk,
      buckets `226` / `305`); gift → skip "console: gift delivery has no console bucket
      (R45)". Then, in order: the grammar slot `sig.region_base`, when set, is
      authoritative (if the generic read is NOT implicit and differs → skip "console:
      region contradiction (title/grammar vs URL) — not entered (R45)"); else, when the
      classifier's region words name **more than one sellable base**
      (`distinct_region_bases(sig.region_words)`, 2026-09-19) → skip "console: merchant
      region contradiction <mots> — no single sellable base, not entered (R45)" (au-dessus
      du résolveur marchand : un titre contradictoire ne coûte pas une page) ; else the
      merchant's `offer_page_resolver`, when it declares one — son résolveur EST la lecture
      ordonnée complète (titre → URL → page), fail-closed (`[R33]` / `[R54]`) ; else the generic
      read when it is not implicit; else, if the classifier removed a region word
      (`sig.region_words`) → skip "console: merchant region '<word>' not mapped to a
      sellable base — not entered (R45)"; else implicit GLOBAL (no region word at all —
      the Kinguin-style default, as before). The BASE label is kept in the plan
      (`_Plan.base_label`) for R44. Per family `REGION_IDS[fam].get(base)` — `None` →
      skip "no region id for <FAMILY>/<LABEL> (R45)" (e.g. `PS5/EU`) for the WHOLE offer
      ("PS5 … [EU]" skips: no PS5 EU/US/UK bucket exists **[P3]**);
   d. anchor: `pc_res = resolver(guard_name)`; if `None`: `resolver(guard_name,
      page_kind=CONSOLE_PAGE_KIND[primary])` (no R30 search for console kinds); `None` →
      "no AKS product page found (console) (R45)";
   e. identity: `identity_name = console_page_identity(anchor.aks_name)`; R01 / R16 /
      R01b on `guard_name`;
   f. Play Anywhere **[P2]**: `pa = pc_res is not None and "XBOX PLAY ANYWHERE" in
      {p.upper() for p in pc_res.official_platforms}`. `sig.pc_declared and not pa` → skip
      "console: merchant declares Xbox + PC but the AKS page does not list Xbox Play
      Anywhere — not entered (R45)" (contradiction, never resolved in the merchant's
      favour). `pa` with a declared Xbox family → every Xbox target takes the XBOX_PC
      bucket and the PC page becomes an additional target (bucket XBOX_PC), whether or not
      the merchant wrote "+ PC"; otherwise One → XBOX_ONE, Series → XBOX_SERIES;
   g. target pages **[P1: merchant declaration ∧ AKS page]**: for each declared family,
      `url = anchor.console_pages.get(kind)` (a console anchor is its own page); absent →
      skip "console: AKS has no <family> page for '<identity>' — declared platform
      unverifiable (R45)"; `page_resolver(url)` → `None` → skip; identity
      `_identity_tokens(console_page_identity(page.aks_name)) ==
      _identity_tokens(identity_name)` — tokens with apostrophes FOLDED (review fix
      2026-09-14: "Luckys" on a Switch page equals "Lucky's" on the PC page; historique :
      CHANGELOG 2026-09-14), else skip "console page
      '<name>' is not '<identity>' (R45)" (the Elden Ring Tarnished Edition case — also on
      the `nintendo-switch-2` tab: "ELDEN RING Tarnished Edition Nintendo Switch 2", AKS
      188441, is not Elden Ring); `page.editions` empty → skip "AKS <FAMILY> page carries
      no editions map — edition unverifiable (R19, R45)";
   h. `resolution` = the primary page (first declared family), `platform` = the primary
      family, `region_label` / `region_id` = the primary bucket; then the common flow
      (R44 — on the BASE label `plan.base_label` against the page IDENTITY, the grammar's
      `region_base` authoritative like a merchant hook (review fix 2026-09-14: R44 reads the
      BASE label, never the bucket text "Xbox Game Code US" — "Air Force United States
      Pacific Xbox One" skips R44; historique : CHANGELOG 2026-09-14) —, R19, the edition
      block R18 / E05 / R23 / P1-1 unchanged);
   i. after the edition block: every secondary target must sell the resolved edition
      (`edition_id in page.editions`), else skip "edition <label>(<id>) not sold on the
      <family> page (R45)"; then `targets` and the `Candidate` are built.
5. `Candidate.targets: tuple[Target, ...]` — `Target(platform, aks_product_id, aks_url,
   aks_name, region_label, region_id, edition_label, edition_id)` (frozen dataclass,
   `to_dict`). `Candidate.to_dict()` ALWAYS emits `"targets": [...]` (a PC candidate: one
   target synthesised from the primary fields). `fingerprint`: unchanged for one target;
   otherwise `primary + "|+" + ",".join(f"{aks_product_id}:{region_id}:{edition_id}" for
   the secondary targets)`. `normalized_block`: one extra line per secondary target
   ("↳ PS4 85104 — Hades PS4 · Playstation Game Code GLOBAL(88)"). Console region labels
   in the Candidate come from `CONSOLE_REGION_LABELS[id]` — the master label without its
   " (id)" suffix and without BOM ("PS5", "Xbox/PC GLOBAL", "Playstation Game Code
   EUROPE"); `resolve_catalog_id` falls back to the id path (verified). Shapes:
   [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md).
6. `match_feed(..., consoles=False)` (the library default is unchanged); the CLIs and the
   admin are **console-ON by default** — Romain's decision « 1 » of 2026-09-15 (historique
   — the MMOGA console dry-run behind it : CHANGELOG 2026-09-15):
   `scripts/03_match.py` (`--consoles` default `True`, kept as an explicit no-op;
   **`--no-consoles`** opts out) stamps `match_meta.json["consoles"]`;
   `scripts/10_data_entry_auto.py` / `src/data_entry_auto.py` (`SweepConfig.consoles`
   default `True`, `--no-consoles` opts out) stamp `recap.json["consoles"]` and ALWAYS
   write the mode on the 03 argv — `--consoles` or `--no-consoles` — so a run dir shows
   it; the admin (`POST /api/data-entry/auto`, by-urls preview and « Saisir ») reads the
   JSON boolean body field `consoles` (absent = `true`; a non-boolean is refused 400
   `bad_consoles`), the UI checkbox « Consoles » is checked by default, and the manager
   appends the same flag pair to `scripts/10` / `11` / `12` and records `consoles` in
   `admin_submit.json`. `05_submit` gates every entry by shape / cap / readbacks (§6).
   **No console ENTRY under `--no-consoles`** — but the URL console scan
   (`console_marker_in_url`) is active in EVERY mode, so a URL-only console row skips
   `console` there instead of a page-level reason ("no AKS product page found", "forbidden
   region: …", "extra words: ['KINGDOM']"…; feed_status: category consoles). Historique
   (default OFF 2026-09-12 → 14, the `--dry-run` guard of 2026-09-14, the 569-row Gamivo
   count) : CHANGELOG 2026-09-14 / 2026-09-15.

**Never partial.** A console candidate exists ONLY when EVERY declared family resolved to
a verified page + bucket + edition; any failing family skips the WHOLE offer with the
reason above. A feed row is consumed by its first creation (§4.3 finding (d)), so entering
"the first target only" would silently lose the second platform — forbidden at match time
(no partial `targets`) and at submit time (§6 gate). No region, edition or platform is ever
guessed: doubt → skip with an explicit reason string.

**Policies (P1 decided; P2-P5 à confirmer par Romain — also listed in §12).**
- **P1 "merchant declaration ∧ AKS page" — DECIDED (Romain 2026-09-14: « clé PS5 seule =
  page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch et Switch 2 »)**: a
  target is added only if the merchant DECLARES the platform AND the AKS page of the game
  exists for it. A lone declared platform → that page ONLY (a lone "PS5" key → the PS5
  page, never PS4 as well; a lone "Xbox Series X|S" key → the Series page, never Xbox
  One); a cross-gen declaration ("PS4 / PS5", "Xbox One / Series X|S") → both pages. No
  sibling page is ever added (AGENTS.md "Reviewed decisions"); there is no "page alone"
  switch.
- **P2 Play Anywhere = the PC page's truth** ("Xbox Play Anywhere" in `official
  platforms`): merchant "+ PC/Windows" WITHOUT PA on the page → skip (contradiction); PA on
  the page WITHOUT a merchant mention → PA targets (XBOX/PC bucket on PC + One + Series).
  **Domaine borné le 2026-09-20** : cette porte ne juge que les familles XBOX. Xbox Play
  Anywhere n'existe ni sur Nintendo ni sur PlayStation, et la garde se déclenchait pourtant
  dès que « PC » était déclaré à côté de N'IMPORTE quelle famille : « FINAL FANTASY VIII -
  REMASTERED (PC) (Nintendo Switch) Nintendo Key - EU » (GameSeal, offre 100703022) a été
  refusée 22 fois avec un motif affirmant un Xbox absent du titre. Une déclaration « PC +
  famille non-Xbox » reste un REFUS — une clé eShop ne s'active pas sur PC, la déclaration
  marchande se contredit et on ne devine pas laquelle est vraie — mais sous son vrai motif
  (`contradictory delivery`). Un audit « trouvera » qu'une clé Switch pourrait entrer sur sa
  page : ce serait deviner, laisser le refus.
- **P3 PS5 outside GLOBAL** ("PS5 … [EU]") → skip: no PS5 EU/US/UK bucket exists — Romain
  can create them in the tool.
- **P4 Eneba's 704 "XBOX LIVE Key" rows without a generation** → skip (no declaration).
- **P5 console DLC / season pass** → skip in v1.

**URL-only console rows.** Gamivo and Eneba carry the platform in the URL alone (the title
never names it), so the console guard of `precheck_skip` reads the TITLE **and** the URL
(`console_marker_in_url`), **active in every mode** — such a row skips `console`
(`--no-consoles`) or is classified (default); a console key must never reach the
token-less-title → Direct Publisher path of the PC branch. Historique (the Riders Republic
leak of 2026-09-11, AKS product 50562, to be corrected by hand — §12) : CHANGELOG
2026-09-12.

**Reason-string vocabulary.** `console` — flag off, any console marker in title OR URL
(unchanged text for titles). `console: … (R45)` — flag on, the classifier's and the
branch's fail-closed skips (Xbox 360, not a game, PC-only Xbox Live key, no declared
generation, "console: unparsed platform residue (R45)" and "console: product name suffix
'<Platform label> Edition' contradicts the declared platform <FAMILY> — not entered
(R45)" — the two classifier skips of 2026-09-14 (4.12.3) — DLC on console, gift delivery, Play Anywhere contradiction, missing family
page, the region refusals of 2026-09-14 — "console: merchant region '<word>' not mapped
to a sellable base — not entered (R45)", "console: region contradiction (title/grammar
vs URL) — not entered (R45)" — and the branch's defensive refusals: "console: unknown platform family
'<family>' — not entered (R45)" (a declared XBOX_PC / unknown key), "console: no product
name left once the platform markers are removed (R45)", "console: AKS page name '<name>'
has no product identity (R45)", "console: AKS <family> page <url> not found (404) —
declared platform unverifiable (R45)" — the tab URL answered 404/410). The remaining R45
skips keep their page-level wording: "no region id for <FAMILY>/<LABEL> (R45)" (e.g.
`PS5/EU` — the uppercase LABEL, not the lowercase base), "no AKS product page found
(console) (R45)", "console page '<name>' is not '<identity>' (R45)", "edition
<label>(<id>) not sold on the <FAMILY> page (R45)". A target page without an editions map
skips as "AKS <FAMILY> page carries no editions map — edition unverifiable (R19, R45)"
(the PC R19 wording, family-qualified and stamped R45 since 2026-09-14). A declared
region the grammar cannot sell skips in `precheck_skip` as "forbidden region: <LABEL>"
(the PC wording — the same router files it). `feed_status.categorize_reason` files
`console`, `console: …` AND any reason carrying an `(R45)` or `(R19, R45)` stamp under the
consoles family (lever text updated for R45) — so the page-level R45 wordings above land
there too, never in `no_page` / `stub_page` / `other`; `aks_lists.suggest_target_list`
keeps them all in place (no list). The `<FAMILY>` placeholder is the family KEY
(`XBOX_SERIES`, `PS5`, …), not the `CONSOLE_PLATFORM_LABEL` text.

**Volumes.** Console rows per merchant and per grammar (latest batches) live in
[`MERCHANTS.md`](MERCHANTS.md) and `docs/feeds/<Merchant>.md`; historique (the 2026-09-12
batch counts, the MMOGA console dry-run of 2026-09-15 behind decision « 1 ») : CHANGELOG
2026-09-12 / 2026-09-15. Instant Gaming: the platform is not in the feed (no console entry
from IG, MERCHANTS.md).

---


**Deux gardes console refermées le 2026-09-18 (audit complet).**

- **`console_pc_declared` complété pour les marchands à hook.** Les quatre marchands qui
  déclarent `console_url_families` (G2A, GameSeal, Driffle, K4G) CONSOMMENT le jeton `pc` dans
  leur propre expression et jetaient l'information, et aucun ne déclare `console_pc_declared` :
  la garde P2 « Xbox + PC sans Play Anywhere vérifié » ne pouvait JAMAIS se déclencher chez eux.
  La branche à hook complète maintenant le signal avec la lecture générique du slug, exactement
  comme la branche sans hook — sauf si le marchand a explicitement pris la main.
- **Le résolveur du marchand passe AVANT le balayage générique (corrigé le 2026-09-19,
  Romain).** La garde posée la veille vivait dans le DERNIER `else` de la branche console : le
  balayage générique la précédait, et ce balayage lit les mots du NOM DU JEU. « 51 Worldwide
  Games (Nintendo Switch) », sans région dans l'URL, produisait un GLOBAL **explicite** sur le
  seul mot « Worldwide » du titre — la page marchande n'était jamais ouverte, même simulée
  indisponible. Pour un marchand qui déclare `offer_page_resolver`, son résolveur EST la lecture
  ordonnée complète (titre → URL → page) : il passe donc juste après le créneau de grammaire
  console, avant tout balayage générique et avant le GLOBAL implicite.
- **Deux bases VENDABLES dans le créneau = refus, AU-DESSUS du résolveur (corrigé le
  2026-09-19, Romain : « Gamerall accepte des régions contradictoires »).** Le contrat de
  `ConsoleSignal` disait déjà que des mots de région ne désignant pas UNE base vendable unique
  sont un refus, mais la remontée du résolveur marchand (ci-dessus, même jour) l'avait
  court-circuité : la branche `elif _page_resolver is not None:` ne contrôlait rien, et
  « Hades (Nintendo Switch) GLOBAL US » descendait jusqu'à elle pour ressortir **candidat
  GLOBAL(99)** ; « EUROPE USA » ressortait **EU(99eu)**. L'ordre est donc : créneau de grammaire
  → **contradiction** → résolveur marchand → balayage générique → GLOBAL implicite, avec le
  refus « console: merchant region contradiction `<mots>` — no single sellable base, not entered
  (R45) ». Étant au-dessus du résolveur, un titre contradictoire **ne coûte pas une page**.
  Le prédicat est `sig.region_words` (les mots retirés À CÔTÉ de la phrase de plateforme), **pas**
  un désaccord avec le balayage générique : celui-ci lit les mots du NOM DU JEU et refuserait à
  tort « 51 Worldwide Games » (générique GLOBAL explicite, page Europe). Mesuré : `region_words`
  vaut `()` sur ce titre-là et `('GLOBAL', 'US')` sur celui de Romain. Les mots non vendables
  sont ignorés du prédicat (`distinct_region_bases`) : « GLOBAL CANADA » reste un verrou
  interdit et garde son aiguillage propre.
- **La plateforme de la page cible est vérifiée.** Le seul contrôle était une comparaison de
  NOMS — or `console_page_identity` retire précisément le suffixe de plateforme, donc
  « Hades PS4 », « Hades PS5 » et « Hades » sont tous égaux : une barre d'onglets pointant vers
  la page d'une AUTRE génération passait. `page_platform` était extrait puis JETÉ. La table
  inverse est bâtie sur le vocabulaire de la **méta** (« Xbox Series X »), qui diffère de celui
  des onglets (« Xbox Series »). Prudence assumée : une méta absente ou d'un vocabulaire inconnu
  ne prouve rien et ne refuse rien ; seule une méta nommant une AUTRE famille fait échouer la
  cible.

### ACCOUNT offers — one detector, a written precedence, a last guard (2026-09-25)

Bug report pasted by Romain: the Gamivo offer « Hitman 2 Global »,
`/product/hitman-2-xbox-one-series-account-global-standard`, was created as an **Xbox One
Game Code** key (page 23940) and an Xbox Series key (page 60188). Root cause: the URL
account marker was read only at the END of the path, and Gamivo writes
`<game>-<platform>-account-<region>-<edition>`. The same family of error hit Difmark: eight
« [Steam/Global][OFFLINE] » accounts of the account list (30) were entered as Steam keys
under GLOBAL(2) on 2026-09-23, because the Difmark branch read the page's silence as « key ».

**One detector** — `console_keys.account_signal(name, url, merchant)`, reused by the console
classifier, `matcher.is_account_offer` / `precheck_skip`, the sort, the Difmark branch and
the submitter. **Precedence**:
1. the title carries ACCOUNT as a whole word → `"title"`;
2. a merchant with its OWN account grammar (`MerchantConfig.account_row` — Difmark) →
   `"merchant"`: its URL is template (every Difmark URL says « account », keys included —
   reviewed 2026-09-21), the row takes the account branch and the merchant PAGE decides;
3. otherwise `account` as a standalone token of the URL PATH (URL-decoded, lower-cased,
   non-alphanumerics as separators, anywhere, query ignored, the merchant's
   `url_ignore_substrings` removed first) → `"url"`. « accounting » is not the token.
No trusted source states « key » explicitly for merchants without their own grammar, so
nothing overrides signals 1 and 3; the « key » reading is only the default when none fires.

**Where an account goes:** a merchant WITHOUT `account_row` → console rows « console: ACCOUNT
— not a game (R45) », every other row « skip category: ACCOUNT (…) » (the LAST precheck, so
existing reasons keep their label) — both routed to the account list (30) by
`aks_lists.suggest_target_list` / the sort: the manual-review queue. Difmark → its account
branch, which now requires the page to SAY what it sells: ACCOUNT or OFFLINE in the page
wording (or ACCOUNT in the title) → the `…-steam-account` page and « Account » bucket, or a
named refusal when that page is missing; the 2026-07-17 key wording « <Game> (<platform>) … »
or the word KEY → key; anything else (« [Steam/Global] » alone) → refused (« la page ne dit
ni compte ni clé »), never a key by default.

**Last guard before any write** — `submitter.offer_type_mismatch`, run in `_prepare` BEFORE
the row is located or its modal opened, and again in `Submitter._process` right before the
Create click. Each target is checked on its own (an Xbox One + Xbox Series candidate has two
destinations). Destination = ACCOUNT when its region label says ACCOUNT or its AKS page is a
`…-account-compare-prices` page; neither label nor page → UNKNOWN. Account offer → key /
game-code destination: blocked. Key offer → account destination: blocked. Unknown
destination: blocked. For a `"merchant"` signal (Difmark) the page decided in the matcher:
only the title word and the unknown rule are enforced. Blocker `offer_type_mismatch: <why>`
— a real refusal (feeds the failure streak), never a designed skip, nothing is filled.

## 5. Stage 3 — Validation

No submission without an explicit validation file for the **exact current
candidates** of the **current active task** `[S15]`. The validator takes the
candidates JSON and requires: exact candidate ids, `run_id`, `validated_by`,
`validated_at`. A previous "oui" never authorizes a new/later batch.

Implemented in `src/validation.py` + `scripts/04_validate.py`. Candidates are
matched by fingerprint (`offer_id|aks_product_id|region_id|edition_id`), so a
re-match that changes region/edition invalidates a stale approval; any problem
rejects the whole file (fail-closed). See [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md).

**Submit-time re-verification (audit P1, 2026-07-08):** `approved.json` alone
is never authority. `scripts/05_submit.py` re-derives the approved set from the
sibling `candidates.json` + `validation.json`
(`verify_approved_against_source`) and refuses to run — dry-run, inspect
**and** submit — when `approved.json` does not match the re-derivation exactly
(stale, hand-edited, or fabricated) or when either source file is missing.
`validated_by` / `validated_at` / fingerprints are thus re-checked at the
moment of submission, not only at 04_validate time.

**Admin page (2026-07-15):** the operator can validate from the web page
(`src/admin/`, `scripts/07_admin_server.py`, behind nginx HTTPS + basic auth)
instead of hand-editing `validation.json`. **`validated_by` is the AUTHENTICATED
user, never the request body `[P2-9, A3]` (audit 2026-09-02):** it authorizes live
offer creation (non-repudiation), so `_post_validation` overwrites it with
`_basic_user()` — the authenticated identity wins over any client-supplied value
(mirrors L11, `_post_learning`). With NO reliable Basic identity (Authorization
header absent or malformed → `_basic_user()` None), validation is **REFUSED
fail-closed (403 `authentication_required`)** — no unauthenticated fallback to a
client value (A3). Production always carries the nginx-validated Authorization header.
Same gate, same artifacts: every
save regenerates the full `candidates.json` + `validation.json` +
`approved.json` triple through the real `04_validate.py check` — the page can
never patch `approved.json` alone. Operator overrides (region/edition, from
the run's own `session_catalog.json` only; platform, informational) rewrite
the candidate entry with a recomputed fingerprint and an `operator_override`
audit field that freezes the matcher's original pick, plus
`operator_override` / `validation_saved` JSONL events. A save is refused when
`candidates.json` changed since page load (sha256), when an override id is
not in the session catalog, or when the resulting fingerprints collide. The
page's "Soumettre" click (authenticated, confirmation modal requiring the
literal `GO`) is the operator's explicit go; the submit itself is the
unmodified `05_submit.py`, spawned supervised (exit code + `submit_plan.json`
read back — never fire-and-forget), one browser-driving run at a time, R24
modes with the canary cap enforced before the spawn.

**No re-adding (2026-07-15):** the page derives a per-offer status from the
append-only JSONL run log (`submit_offer` events; primary — it survives
`submit_plan.json` being overwritten by a later dry-run) unioned with the
current `submit_plan.json`: **ajoutée** (confirmed created — sticky, a later
"not in feed" failure never demotes it), **échec** (attempted, blocker shown,
re-approvable), **en attente** (never attempted). Created offers are locked in
the UI (unchecked, disabled) and blocked server-side at BOTH gates: saving a
validation that approves one is refused whole (`already_created`), and a
submit whose approved batch intersects the created set is refused before the
spawn (`already_created`) — re-submitting a partially-completed batch requires
re-validating with the created offers excluded.

**Deleting erroneous entries (2026-07-15):** the operator can mark a candidate
entry as a matcher error to delete it *instead of submitting it* (`delete:
true` in the save payload). The entry is removed from `candidates.json` before
the triple is regenerated — it can never reach `approved.json` or a submit.
Refused in combination with approve/override (`bad_delete`) and for
already-created offers (`delete_created` — the entry documents a real add).
Every deletion is logged to the append-only JSONL (`candidate_deleted`, full
candidate payload, who/when) — the matcher's output is never silently lost.
`report.txt` stays untouched (it is the matcher's historical artifact); the
page's table is the operational view.

---


**`approve` doit être un booléen JSON (audit complet, 2026-09-18, `[P1]`).** La décision se
lisait en VÉRITÉ PYTHON (`if not entry.get("approve")`) : la chaîne `"false"` — des guillemets
de trop, ou un tableur qui sérialise les booléens en texte — valait `True` et APPROUVAIT
l'offre. Et comme `verify_approved_against_source` re-dérive avec le même prédicat, la
re-vérification au moment du submit CONFIRMAIT l'approbation au lieu de la refuser : l'unique
porte avant une écriture live s'ouvrait sur un refus. Une valeur non booléenne lève désormais
`ValidationError` et le fichier est refusé EN ENTIER — jamais deviné, jamais honoré à moitié.

**Les seaux de région sont PAR PLATEFORME, dans les DEUX sens (même audit, `[P1]`).** La
surcharge opérateur ne validait un `region_id` que contre le catalogue de session GLOBAL — les
options de TOUTES les plateformes, que le `<select>` de la console présente d'ailleurs sans
filtrage. Un mauvais clic sur « PS5 (88ps5h) » était donc accepté sur un candidat STEAM, et
aucun étage en aval ne rattrapait (ni `validation.py`, ni `candidate_contract`, ni le
submitter ne consultent `REGION_IDS`). La branche « changement de plateforme » refusait pourtant
déjà l'incohérence symétrique. Refus `platform_region_mismatch` quand la région seule change et
que l'id appartient PROUVABLEMENT à une autre famille ; un id qu'aucune famille ne revendique
n'est pas réfutable et passe ; re-choisir les DEUX ensemble reste une décision explicite de
l'opérateur et reste acceptée.

## 6. Stage 4 — Submitter (dry-run by default, locked behind validation)

For each validated candidate, in order, fail-closed:

1. Refresh the current merchant feed again; locate the **exact current row**
   (feeds are dynamic — re-scan, never trust saved page numbers) `[DRIFFLE][GOG]`.
   In a batch, each creation shrinks the feed and **reflows the pagination**, so
   a row index built at batch start goes stale. The post-save
   verify scan walks the whole refreshed feed anyway — its result **replaces**
   the row index after every verified creation (zero extra page loads).
   **Offer ids are import-batch-scoped, not row identities**: AKS re-imports a
   feed on its own schedule and re-ids EVERY row. The stable row identity is the
   **merchant URL path** — query params drift across re-imports while the path holds
   (unique in-feed). Historique (G2A reflow 2026-07-07, K4G / G2A id-rotation
   measurements 2026-07-08) : CHANGELOG 2026-07-08. A candidate absent by id is re-located by URL path +
   **exact-title check** (fail-closed on any drift) and adopts the row's
   current id (`row_relocated` in the log). Absent by id AND path = the offer
   genuinely left the feed (worked in parallel / delisted) — a correct SKIP.
   **An index-scan miss is NOT trusted as that SKIP** (hardened 2026-09-01): the
   bulk index build (`_index_by_search` for by-urls; `_scan_page_window` for a
   sweep) can transiently drop a present offer (historique — the Whiteout Survival
   same-product multi-edition batch : CHANGELOG 2026-09-01). Before giving up, `_prepare`
   RE-LOCATES that one candidate alone by its stable URL — via the feed SEARCH on
   the by-urls path, a bounded feed scan on a sweep (BOTH paths now, parity). Found
   → adopt + proceed; genuinely absent → keep the fail-closed blocker; **UNREADABLE
   → the FeedScanError/CdpCommandError PROPAGATES** (unknown state, never swallowed
   as "not found") so the run loop stops `feed_unreadable` and no further candidate
   is processed (AGENTS.md: uncertainty → STOP).
   Post-save disappearance (§7) is proven under BOTH keys: id-only would
   false-positive "gone" whenever a mid-run re-import re-ids a still-pending
   row.
2. Verify title, URL, price, merchant, page, row identity against the candidate.
   "Page" is deliberately **recomputed by the current scan**, never compared to
   an approved-time value: no page number is stored at approval (step 1: saved
   page numbers are never trusted — pagination reflows). The recomputed page is
   surfaced as `page_url` in the plan entry and in the `row_relocated` log line.
   **Price is a routing signal, not a blocker** (audit 3, 2026-07-08): on the
   by-id path a price mismatch (both sides present) distrusts the id — possibly
   reused by a re-import — and reroutes to the URL identity. Once name + URL
   path (+ store when present) confirm the row, price drift is **deliberately
   non-blocking**: live feeds reprice constantly between extract and submit,
   and price is never part of what the modal enters. The drift stays visible —
   it is surfaced as `id_mismatches` in the plan entry and the `row_relocated`
   log line. A **store_id** contradiction, by contrast, blocks on both paths.
2b. **Re-verify the row on the FRESH render** (audit 2026-07-17, SC5; hardened
   2026-09-01): the modal-opening navigate produces a NEW page load, minutes
   after the index scan — re-find the row on the fresh DOM and re-match the
   candidate (name + URL path, `check_price=False`) before opening its modal.
   The row is pinned by its **stable URL first, NOT the scanned id** (`_pin_
   fresh_row`): the feed rotates every id on each re-import, so an id-match would read
   a still-present row as gone (historique — the "reflowing too fast to pin" skip, The
   Green Light Steam : CHANGELOG 2026-09-01). The
   URL-matched row yields its CURRENT id for the modal open, and a slow JS render
   is render-polled (re-read, no re-navigate) before concluding absence. A row
   genuinely absent by URL (worked in parallel / delisted), or a URL now pointing
   at a different product, → blocker; never open a modal on an unverified row.
3. Open the modal from that row's `[data-create-offer]` button (`#TB_window`).
   The click returns as soon as it fires — the ThickBox loads `#TB_ajaxContent`
   ASYNCHRONOUSLY — so the modal context is **render-polled** (re-read) with its own
   backoff `MODAL_CTX_WAITS` = 1/2/4/8/8 s (≈23 s) before concluding it is missing
   (hardened 2026-09-01, widened 2026-09-10 — never an immediate read, never the 7 s
   feed-style budget; historique : CHANGELOG 2026-09-01 / 2026-09-10). **Lost-click defense
   (2026-09-10, MMOGA):** the click only works once the page scripts have bound the
   ThickBox handler, and under AKS slowness the 3 s navigate settle is not always enough
   — a click fired earlier is silently lost ("OPENED", no content ever). So (a) before
   the click the submitter polls `page_scripts_state()` (readyState `complete` +
   `tb_show` defined, `PAGE_SCRIPTS_READY_WAITS` ≈15 s, read-only), and (b) after
   `MODAL_RECLICK_AFTER_POLLS` = 3 empty polls the click is re-issued **once** (opening a
   modal has no side effect). Still absent after the backoff → fail-closed skip, logged
   `modal_ctx_missing` with the last context and page-scripts probe. With the gate in place
   the fixed navigate settle before a modal open is `ROW_PAGE_SETTLE` = 1 s (was the 3 s
   default; a session without the probe keeps 3 s — Romain GO 2026-09-10).
4. **Verify the select names before filling** — they vary per feed:
   `offer[region]`/`offer[edition]` on some, `offer[region_id]`/`offer[edition_id]`
   on others. Wrong name → silent `selectize` failure → false `[data-success]`
   `[S17]`. Read them:
   `Array.from(document.querySelectorAll('#TB_ajaxContent select')).map(e=>e.name)`.
5. Pick region/edition via **trusted Selectize** (`select_via_trusted`): a CDP
   `Input.dispatchMouseEvent` (`isTrusted:true`) opens the `.selectize-input`
   dropdown, a trusted click selects `[data-value="{id}"]`. If the wanted id is
   **not rendered** in the product-scoped dropdown, the pick fails closed with
   `NO_OPTION` — there is **no `addItem` fallback**: `addItem` reads Selectize's
   generic master catalog (e.g. `"1"→"Standard"` for every product) and on
   2026-07-06 that exact force created 3 wrong-edition offers. **Not**
   `selectize.setValue(...)` either — that is `isTrusted:false` and leaves
   Selectize's own `required` text input empty (S18, 2026-07-06).
   **The post-pick readback is compared to the target id** (audit 2026-07-17,
   SC3): both channels (`select.value` + `selectize.getValue()`) must equal
   the wanted id — a trusted click can land on a neighbouring option with
   every later gate still passing (the form is valid with ANY option). A
   mismatch fails `WRONG_VALUE`; an unreadable readback fails
   `READBACK_UNREADABLE`. Just before the Create click, BOTH selects are read
   back one last time (`VALUE_DRIFTED_BEFORE_CLICK` on any change since the
   picks — last gate before the pipeline's one write).
6. Fill **`offer[targets][]`** (`add_target_trusted`) with the candidate's
   `aks_product_id` — trusted focus click, `Input.insertText`, commit via the
   adjacent add-button (trusted-Enter fallback). This is the last empty `required`
   field; without it the form never validates.
7. **HTML5 validity gate** (`form_validity()`, a hard gate): the `<form>` must be
   valid (`form_valid:true`) — else return `FORM_INVALID` and do **not** click.
   An **unreadable** probe (`ok:false`) blocks the same way — return
   `FORM_VALIDITY_UNREADABLE`, clean up, never click (audit P1b, 2026-07-08 — no
   degraded mode; historique : CHANGELOG 2026-07-08).
8. Submit by a **trusted CDP click** (`isTrusted:true`) on the modal "Create offer"
   button — the only trigger Driffle's handler honours `[S09]`. It drives the
   modal's **own** `admin-ajax do=create_offer`; we never issue a direct XHR
   (the merchant id is auto-assigned by the modal).
   **A real write is `trusted`-only `[P2-1, A2]` (audit 2026-09-02).** The `native`
   (`button.click()`) and `dispatch` (MouseEvent) click modes produce `isTrusted:false`
   (proven not to persist) and bypass the guards of steps 5–7; the degraded write path is
   **REMOVED** from the write `Submitter` (A2): its `__init__` accepts ONLY `trusted`
   and raises on anything else — **no opt-in escape hatch** ("no degraded mode").
   `scripts/05 --submit` also refuses `native`/`dispatch` at the CLI (defense in depth).
   Historique : CHANGELOG 2026-09-02 (P2-1 / A2).
9. Verify post-save (§7), then close via `#TB_closeWindowButton`.
10. Pacing ≥ 500 ms between submissions `[S03]` — implemented as bounded-random
    pacers (`src/pacing.py`): `--pace-offers` (default `5-15` s) between offers,
    and `--pace-pages` (default `1-3` s) between feed-scan page loads — the real
    burst source, since the full feed is re-walked for the index **and after
    every creation** for post-save verify. `0` disables either. Pacing is never
    a correctness mechanism.

**Multi-target candidates `[R45]` (2026-09-12; written whole on the modal v2 since
2026-09-15).** A candidate carries `targets` (always ≥ 1 —
[`DATA_CONTRACTS.md`](DATA_CONTRACTS.md); §4.12). `_prepare` normalises `entry["targets"]`
(an older `candidates.json` without the key → the primary target) and
`_resolve_from_catalog` resolves the region AND the edition of EVERY target against the
live catalog (any target failing → blocker). **One target = the single-row v2 path** (every
PC offer; steps 1-10 above with one target row). **Several targets = ONE creation with one
target row per page** (the "Modal v2" rules below: cap `MAX_TARGETS_PER_OFFER` = 3, every
row proven by readback, one Create click) — never "the first target only": a creation
consumes the feed row (§4.3 (d)), so a partial entry would silently lose the second
platform. **Designed skips, not failures** (review fix 2026-09-14): an entry gated ONLY by
`multi_target_unsupported_until_modal_verified` (a multi-target candidate on a
`targets_v1` modal — the historical chip field) or by `too_many_targets` feeds neither the
10-consecutive-failures streak nor the StepGuard / BlockLedger accounting
(`guard.record_result` is not called for it) and is counted in the run result's
`gated_multi_target` / `gated_too_many_targets`, so such a batch never stops the run
(`ten_consecutive_failures`) nor halts the safe-auto sweep — the entries after it are
processed. `InspectSubmitter` (`--inspect`) opens and dumps the modal of a gated entry
(read-only; `ready` stays false). `DryRunSubmitter` lists every target in `would_submit`;
the admin validation refuses an override on a multi-target candidate
(`ValidationIOError("bad_override", "candidat multi-cibles (R45) : pas de surcharge,
relancer le match")`) and its row shows a "N cibles (R45)" block (family · page id ·
region(id) per target) inside the « Produit AKS » cell, with the platform / region /
edition selects disabled. **BOM (bucket 306):** the master label of "Xbox/PC GLOBAL (306)"
starts with U+FEFF (the rendered option has none); `region_query` / `edition_query` are
the catalog text WITHOUT U+FEFF — `_type_text_trusted` would otherwise dispatch the BOM as
a key event — while `region_text` stays verbatim in the plan. Non-numeric ids (`88ps5h`,
`24eu`, `99eu`…) and `306` resolve through `resolve_catalog_id`'s **id path** (verified on
the live catalog, §4.12.1). Historique (the fail-closed gate "until the modal is observed",
2026-09-12 → 14, the observation of 2026-09-14 and the canaries of 2026-09-15) : CHANGELOG
2026-09-12 / 2026-09-14 / 2026-09-15.

**Absolutely forbidden** `[SUBMISSION HARD OVERRIDE][S09][GOG]`: direct
`admin-ajax` XHR; `form.dispatchEvent(...)`; `form.submit()`; any "fire and
forget"; degraded submit mode; inventing a `buy_url` (must be extracted from the
feed). The merchant id is auto-assigned by the modal — a direct XHR would use the
wrong one.

If any step fails → do not retry the same offer blindly, do not switch browser.
Per [`SUBMITTER_SPEC.md`](SUBMITTER_SPEC.md) §6 (Romain's decision) the batch policy
is: log + skip the failing offer + continue, and stop the whole run after 10
consecutive failures.

**Batch size = the data-entry mode `[R24]`** (2026-07-13, Romain). Once the
normalized report is validated, we submit; `--mode` decides how much of that
validated batch goes in:

| `--mode` | Batch | Rationale |
|---|---|---|
| `safe` (default) | **Full validated batch, no canary** `[R23b]` | Frozen matcher behaviour. Validation (`approved.json`) is already the safety gate for *which* offers submit, so no canary on top of it. |
| `learning` | **Canary of 1** | Exploring one (category × merchant) unlock. It **does write** — Romain: *"le learning n'est pas un mode d'observation, il ajoute les offres si le rapport normalisé est valide"* — but stays capped for now. |
| `advanced` | **Canary of 1** | Validated unlocks; same cap for now. |

The canary is a **cap, not a default**, in `learning`/`advanced` ("tjrs un
canary pour le moment"): `--limit N` can narrow it, never widen it — a `--limit`
above the cap is refused (exit 2), not silently clamped. The per-offer and
10-consecutive-failure stop conditions above are unchanged and remain the actual
safety net *during* a run.

**Mode binding (FC5, audit 2026-07-17 — enforced):** `03_match --mode` stamps the mode
into `match_meta.json`; `05_submit` and the admin `SubmitManager` refuse a real submit
whose declared mode is *wider* than the matched one (`mode_widens_match`) — a run matched
under an unlock can never take the full-batch `safe` path. Absent meta = pre-FC5 legacy
run, accepted. (The matcher has no mode profiles: behaviour is identical for the three
modes, only the stamp differs.)

Both the DRY-RUN and the **real write path** are built in
`src/submitter.py` + `src/submit_session.py` + `scripts/05_submit.py`; the real path
(steps 5–8, `--submit --click-mode trusted`) is **live-proven** (first confirmed
Driffle creations 2026-07-06 — see [`SUBMITTER_SPEC.md`](SUBMITTER_SPEC.md) §4b).
Note the **Layer-5** case: some bundle/non-Standard offers reject server-side
(`Bad request: paramètre "offer" manquant ou invalide`) even when the form is
valid — fail-closed skips them, not a regression.

`submit_plan.json` reports two write counters (audit P2, 2026-07-08):
`write_attempts` (ready rows the write path attempted — the conservative count
that drives `--limit`) and `created` (verified creations, i.e. post-save "gone
from the refreshed feed") — never a single counter conflating the two.

---

**Modal v2 — region / edition per target row (2026-09-14):**

**Modal shape (2026-09-14).** Before any fill the submitter reads the open modal's
shape (`modal_context().modal_shape`, read-only): `targets_v2` = the current AKS
tool (row 0 `offer[targets][0][target]` + override selects `…[0][region]` /
`…[0][edition]`), `targets_v1` = the historical `offer[targets][]` chip field,
`unknown` = anything else. `unknown` blocks EVERY entry (`modal_shape_unknown`,
nothing filled; feeds the 10-consecutive-failures stop). The plan entry carries
`modal_shape`.

**Targets per row (v2).** One row per target of the candidate, in order; the FIRST
target is the primary whose ids also go to the global `offer[region]` /
`offer[edition]`. Row 0 exists; each extra row is added with a trusted click on the
button right after the LAST row's target input (DOM relation, never text) and is
PROVEN present by readback before it is filled. Per row: the AKS product id typed
with `Input.insertText` (readback must equal the id — never a guessed id), then
the region and edition overrides set EXPLICITLY through the trusted Selectize pick
(empty overrides inherit the globals — Romain 2026-09-14 — but inheritance is
never relied on). Before the ONE Create click: HTML5 validity gate, obstruction
probe, then a full readback of both globals and every row (values and row count)
— any drift or count mismatch → no click. Never a partial console entry: either
every row is proven filled or nothing is created; post-save (gone from the
refreshed feed, same `available`) stays the only success proof.

**Never Enter.** The modal form has `method=get` and no `action`: an Enter
keypress in one of its text inputs submits it natively. No stage synthesizes an
Enter in the modal; the v1 chip field's Enter commit fallback is gone
(`NO_ADD_BUTTON` fails closed). A submit-like add-row button (`type` ≠ `button`,
`data-action-submit`, `button-primary`) is never clicked (`ADD_BUTTON_UNSAFE`).

**Cap.** `MAX_TARGETS_PER_OFFER = 3` (Romain 2026-09-14, "3 ou 4 pour le
moment"): a candidate with more targets is blocked (`too_many_targets`) before its
row is located or its modal opened — a designed skip (`gated_too_many_targets`),
like the R45 gate.

**R45 gate (updated).** `multi_target_unsupported_until_modal_verified` now applies
only when the modal is NOT `targets_v2` (i.e. the v1 chip field) and the candidate
has more than one target. On v2 a multi-target candidate is written whole.

---

---


**Le remap libellé→id vivant couvre enfin les seaux console (audit complet, 2026-09-18).**
`_norm_option_text` ne retirait le suffixe `(id)` d'un libellé de catalogue que s'il était
PUREMENT NUMÉRIQUE. Les 9 seaux console de `[R45]` à id alphanumérique (24eu, 24us, 88eu, 88us,
88uk, 88ps5h, 99eu, 99us, 992) gardaient donc « (88ps5h) » dans le texte normalisé, la
comparaison de libellé échouait TOUJOURS, et `resolve_catalog_id` retombait systématiquement sur
la voie « valider l'id du matcher » — c'est-à-dire que la voie PRÉFÉRÉE, celle qui existe
justement pour rattraper un id qui a dérivé (« the wrong-edition fix »), était inerte pour eux.
Le BOM est retiré au passage : `_strip_bom` existait déjà pour la frappe Selectize, mais un
libellé qui en porte un ne comparait jamais.

## 7. Stage 5 — Post-save verification (the deterministic success signal)

This is THE rule of the skill `[DB proof override][S10][S18]`.

- `.button-primary` is only the valid submit **trigger**.
- `[data-success]` is only a positive **UI signal**, confirmed as a false
  positive even with the correct button click `[S18]`.
- **Neither is proof.** After every submission, reload the feed
  (`window.location.href`) and confirm the offer **disappeared** from the
  refreshed feed, in the **same `available` mode the run scans**. If it is
  still present → the submission failed → do not re-loop the same action; STOP
  and diagnose `[R0b]`.

`success = (offer no longer in the refreshed feed, same available mode as the
run)`. This boolean is what the submitter passes to
`StepGuard.record_result`.

**Two accepted forms of the refreshed-feed proof (Romain GO 2026-09-10).** (a) The
whole-feed WALK to a proven end (the historical form; still the by-merchant manual
default and `scripts/10 --prove-gone-scan`). (b) The feed **SEARCH filtered by the
offer's URL** in the run's `available` mode — a whole-feed filtered query, so an absence
is a genuine whole-feed absence (the by-urls proof since 2026-08-25); now the safe-auto
sweep's default (`05_submit --prove-gone-by-search`, ~2 s instead of ~100 s per offer on
a 66-page feed). Same fail-closed guards as the walk: an unrendered / wedged / overflowing
search raises `FeedScanError` → the offer is UNKNOWN, never a false "gone"; the search
term data-check rejects a re-served foreign DOM. Under the search proof the sweep keeps
its page-hint locate index (the search's 0-1 rows never replace it); a row that reflowed
is re-found by the search re-locate. The mode matters: on Kinguin `available=pending` is
empty even with 1197 rows in `available=all` (2026-07-08), so "gone from
pending" would be trivially — and falsely — true.

**"Gone" requires a POSITIVELY complete, readable walk** (audit 2026-07-17,
FC1/SC1/SC2/SC4/SC6 — absence of data is not absence of the offer). The
verify scan (and the batch-start index) prove their own coverage:

- a CDP timeout or protocol error **raises** (`CdpCommandError`,
  `src/cdp_session.py`) instead of flowing through as "0 rows";
  `Page.navigate`'s `errorText` is checked;
- a blank page is re-fetched once, then only two blank states are accepted —
  past-the-end (feed UI + nav advertising fewer pages) or empty queue on
  page 1 — anything else raises `FeedScanError` (the extractor's §3
  discipline, via `SubmitSession.feed_page_state()`);
  **`nav_max=0` is confirmed, never trusted on the first read `[P1-3]` (audit
  2026-09-02).** An empty page with the feed UI up but `nav_max=0` is AMBIGUOUS: a
  genuine empty queue (page 1, no results) OR a transient blank where the rows AND
  the pagination nav are still loading into the already-rendered shell (2026-07-07).
  The `_wait_for_feed_ui` poll does not catch it (feed_ui is already True), so a
  single read would prove a FALSE end-of-feed → false 'gone' → phantom creation
  (this scan backs both the whole-feed prove-gone AND the by-urls search-locate).
  It is CONFIRMED by re-reading the DOM (no re-navigate) with the `EMPTY_CONFIRM_
  WAITS` backoff — the SAME slow-render headroom as `FEED_UI_RENDER_WAITS`, because
  page-1-empty is the phantom-critical branch — before returning `[]`; if a
  re-read never ran (misconfig) it falls through to the fail-closed raise, never a
  first-read `[]`. **Each confirm re-read re-checks the LIVE signals `[A1]` (audit
  2026-09-02):** the session can EXPIRE during the backoff wait (bouncing to wp-login,
  rows=[] and feed_ui dropping) — so a login bounce raises `NotLoggedInError`, an href
  that no longer names this page raises `FeedScanError`, and the empty is trusted only
  while `feed_ui` still holds; otherwise it was not a genuine empty. A past-the-end
  page with `nav_max>=1` (nav rendered) stays a fast return — the nav proved the page
  count, no ambiguity;
- a login bounce mid-scan raises `NotLoggedInError`;
- the browser's `location.href` must match the page navigated to (a wedged
  tab re-serving the previous DOM is detected, never re-read as fresh pages);
- exhausting `max_pages` while the feed's nav advertises MORE pages raises
  instead of silently truncating coverage.

Mid-batch, any of these marks the current offer `post_save = "… offer state
UNKNOWN, verify it by hand …"` (attempt counted, creation NOT), stops the run
with `stopped="feed_unreadable"`, and still writes `submit_plan.json` + logs.
At batch start they abort with `aborted="feed_unreadable"` before any write — a login
bounce there is named apart since 2026-09-24: `aborted="not_logged_in"`.

**Before the click is not « unknown » (2026-09-24, Romain : « go pour les deux
correctifs »).** `_prepare` only READS — navigate, re-find the row, OPEN the modal, read its
context; the click on « Create » lives in `_process`. A failure raised by `_prepare` (the
entry does not exist yet) therefore leaves the offer INTACT: `post_save = "feed/CDP
unreadable BEFORE any write — offer untouched (no Create click): …"` and
`stopped="feed_unreadable_prewrite"` — still a stop of the run. It was « The House » on
Wyrel, 24/09 14:00 (`net::ERR_CONNECTION_REFUSED` on the reload), labelled « verify it by
hand » while nothing had left. A `NotLoggedInError` there, and ANY failure raised by
`_process` (during or after the click), stay the UNKNOWN + `feed_unreadable` above.

**The listing's identity may live in its URL query (2026-09-24).** `_url_key` — the
identity the proof, the locate and the mover compare — is the URL PATH, query stripped
(P2-12, below in `_verify_gone`): the query drifts on G2A (`uuid=`). But two merchants put
the LISTING in the query: Wyrel separates the variants of one product by `marketplace_id`,
`edition_id` and `region` on a shared path, CJS by `variation=`. Path-only, the surviving
sibling of another region kept every creation « STILL in feed » — 14 false failures on
Wyrel on 24/09 (AKS had answered « Offer created … feed entry deleted » for all 14, none
reappeared), 13 on CJS since 20/09. `MerchantConfig.url_identity_params` names the params
that make the listing — Wyrel `("marketplace_id", "edition_id", "region")`, CJS
`("variation",)` — and ONLY those join the key (`path?k=v&…`, sorted); `referal` /
`coupon` / any other param stay out. A re-id of the SAME listing keeps the same key, so the
K4G id-rotation guard holds; a merchant that declares nothing keeps P2-12 exactly. The feed
SEARCH still searches the last PATH segment (`_url_path`): the search matches the stored
URL's text.

**One bounded retry of the proof on a CDP command TIMEOUT (Romain GO 2026-09-10;
historique — the two MMOGA halts behind it : CHANGELOG 2026-09-10).** The AKS admin page
can take longer than the 45 s command timeout to answer the proof navigation right after
a successful Create. The proof is read-only, so re-running it can never create: when
`_verify_gone` raises
`CdpTimeoutError` (the `_cmd` "no response within Ns" case — the WebSocket is intact, a
late answer to the timed-out id is discarded by the next command's id match) the
submitter logs `post_save_proof_retry`, waits `POST_SAVE_PROOF_RETRY_WAIT_S` = 5 s and
re-runs the SAME proof (feed walk or search, fresh navigations) once; the entry keeps
`post_save_proof_retry`. A second timeout, a dead socket (`CdpCommandError`: EOF, close
frame, mid-frame stall — never retried), `FeedScanError` or `NotLoggedInError` stay the
UNKNOWN + `stopped="feed_unreadable"` above. The relaunch is safe by construction
either way: the submitter only writes what it re-locates in the refreshed feed.

**Verification method is UI/feed only** `[S12]` — do **not** verify by direct DB
query, network payload inspection, XHR, admin-ajax, or curl backend probing.

---

## 8. Reporting

- Structured text, **never markdown tables**, one offer per block `[S13][CORE]`.
- Per-offer normalized format:

  ```
  #N — <full merchant title, copied from the WP feed>
  🎯 <AKS_ID> — <AKS product name>
  🔗 <real merchant URL from the feed>   (always complete, ?params included — all merchants, R21)
  🎯 https://www.allkeyshop.com/blog/buy-{slug}-cd-key-compare-prices/
  <Platform> <REGION(ID)>, <Edition(ID)>
  ```
- Region in UPPERCASE with id: `GLOBAL(2)`, `EU(9)`, `US(8)`, `UK(71)`,
  `EMEA(emea)`. No `?` in id fields. Every field mandatory — if one is missing,
  don't present, go extract it `[CORE 5-point check]`.
- `<Platform>` is any `REGION_IDS` key rendered via `PLATFORM_LABEL` — Steam,
  GOG, Ubisoft, Epic, EA App, Battle.net, **or Publisher** (`platform:
  "PUBLISHER"` in `candidates.json`, R20 revision §4.4). A `Publisher
  GLOBAL(1)` block is a normal candidate, not an anomaly — the classic store
  platforms are not the whole vocabulary.
- Post-save wording: "soumis via la modale UI, confirmé post-save côté feed/UI"
  or "disparue du feed rafraîchi (même available que le run)". **Never** "créé en base / en DB / confirmé en
  base" unless a real DB check was actually done (not the standard flow)
  `[S13][S14]`.
- Never declare a merchant "finished" without checking `available=pending` on all
  pages `[G05]`.

---

## 9. Session re-auth — cookie transfer (`LOGIN_SPEC.md`, 2026-07-29)

AKS disabled username/password login (social/OAuth only). The old password+2FA
Stage 0b (`scripts/00b_login.py`, `run_login`) is **retired**. Re-auth is
**cookie transfer** only (`src/admin/login_manager.py`, `src/login_session.py`;
design in [`LOGIN_SPEC.md`](LOGIN_SPEC.md)):

- The operator completes the social login in their **own** browser, then pastes
  the WP session cookies (`wordpress_logged_in_*`, `wordpress_sec_*`) into the
  admin console (`/executor/tri` → 🔑 Se reconnecter). The server injects them
  via CDP `Network.setCookies` (official endpoint only) and proves the session
  with `verify_dashboard` (URL under `/wp-admin/` AND `#wpadminbar` present).
- **Explicit operator submit only** — never self-triggered. A
  `NotLoggedInError` from another stage stays a fail-closed STOP + error
  report; wait for Romain's go on the console `[S15]`.
- Cookie VALUES are session secrets — never logged, echoed, stored, or
  committed. Injection is restricted to `allkeyshop.com` by exact host/suffix
  match. Fail-closed on missing cookies / red invariants / browser busy.
- On connection loss, first check whether the existing Chrome session is still
  logged in; only invoke re-auth if the feed redirects to `wp-login.php`, and
  only on Romain's explicit go.

---

## 10. Region / platform / edition reference (fallback hints only)

The live WP-admin dropdown is the source of truth `[P06]`. Use this table only
as a hint / sanity check. Each platform has its own ids.

| Platform | GLOBAL | EU | US | UK | Gift | Gift EU |
|---|---|---|---|---|---|---|
| Steam | 2 | 9 | 8 | 71 | 25 | 259 |
| GOG | 6 | 62 | 63 | 64 | — | — |
| Ubisoft Connect | 50 | 54 | 55 | 52 | — | — |
| Epic Games | 80 | 80eu | — | — | — | — |
| Origin / EA App | 3 | 3eu | — | — | — | — |
| Battle.net | 45 | 4 | 41 | 47 | 570 | 567 |
| Publisher (Direct) | 1 | 12 | 13 | 266 | — | — |

Notes: Steam Gift EU EN = 472, EN Language = 261 (a language restriction, not
GLOBAL). Editions: Standard 1, Deluxe 7, Bundle 8, GOTY 9, Gold 10, DLC 16,
Ultimate 21, Premium 34, Complete 91 (≠ Deluxe), Collection 98, Ultimate
Collection 348.

**Console buckets `[R45]`** (2026-09-12; `CONSOLE_REGION_IDS` in `src/console_keys.py`;
the 867-entry modal catalog, byte-identical in the 9 catalogs of 10-12/09; §4.12). Labels
are the master text without the " (id)" suffix (`CONSOLE_REGION_LABELS`):

| Family (platform) | GLOBAL | EU | US | UK |
|---|---|---|---|---|
| XBOX_ONE (Xbox One) | 24 "Xbox One Game Code" | 24eu "Xbox Game Code EUROPE" | 24us "Xbox Game Code US" | 226 "Xbox Game Code UK" |
| XBOX_SERIES (Xbox Series X\|S) | 300 "Xbox Series" | 302 "Xbox Series EU Game Code" | 303 "Xbox Series US Game Code" | 305 "Xbox Series Uk Game Code" |
| XBOX_PC (Xbox / PC — Play Anywhere) | 306 "Xbox/PC GLOBAL" (BOM in the master label) | 241 "XBOX/PC EU" | 242 "XBOX/PC US" | 240 "XBOX/PC UK" |
| PS4 | 88 "Playstation Game Code GLOBAL" | 88eu "Playstation Game Code EUROPE" | 88us "Playstation Game Code US" | 88uk "Playstation Game Code UK" |
| PS5 | 88ps5h "PS5" | — | — | — |
| SWITCH (Nintendo Switch) | 99 "NINTENDO GAME CODE GLOBAL" | 99eu "Nintendo GAME CODE EU" | 99us "Nintendo GAME CODE US" | 992 "Nintendo GAME CODE UK" |
| SWITCH2 (Nintendo Switch 2 — page kind `nintendo-switch-2`, 2026-09-14) | 99 (same Nintendo family) | 99eu | 99us | 992 |

Notes: **known, NOT entered** — every other game-code bucket of these families (104 in
the catalog: NA / ROW / EMEA / English-only / country buckets such as `227` "Xbox Game
Code ROW", `231` "Xbox Game Code EU/US/UK" (a composite), `236` EMEA, `304` "Xbox Series
NA Game Code", `345` "Xbox series ROW", `470` "Xbox Series Game Code EU English only",
`400` "Playstation Code ROW", `448` "NINTENDO GAME CODE ROW", `496` "nintendo game code
north america", the per-country ids) is never selected: a non-base region takes the PC
dispositions of §4.11 (blacklist / skip), never a "nearest" bucket. Refused as well:
**no PS5 EU/US/UK, no console gift bucket** (Switch 2 pages use the Nintendo family
buckets — there is no separate Switch 2 bucket, 2026-09-14); subscriptions, PSN /
eShop cards, accounts (`24ac`, `88ac`, `454` "PS4 Account", `301`…) and Xbox 360 (`23`,
`23eu`, `23us`). Label facts: the PS4 family never says "PS4" (only "PS4 Account (454)",
an account); `24`, `300` and `88ps5h` carry no region word; ids are strings and the
alphanumeric ones (`24eu`, `88ps5h`, `99eu`…) resolve by id only (§6). The page-side
`filter_name` differs from the modal label for the same id (page `300` = "XBOX X|S
GLOBAL") — match by id, never by label. Console-flavoured editions exist in the catalog
(`1909` Next Gen Edition, `2006` Console Edition, `2257` Cross-Gen Edition, `3942` PS4
Edition…) but none was seen on a sampled page; the edition stays the page's own list (R18).

**Merchant store ids** (verify against feed): Kinguin 58, G2A 38, Driffle 127,
Eneba 19, GameSeal 126, K4G 92, CJS 30, Instant Gaming 28, Gameboost 157,
Gamivo 51, Allyouplay 17, GOG 34, Difmark 167, MMOGA 12 (its AKS page merchant id is 40 — the feed store id is what every stage uses, 2026-09-10).

---

## 11. Per-merchant deterministic notes (brief)

- **G2A**: heavy non-game noise (~2-3% yield); SKIP CIS/ROW/
  Turkey/Germany/currency/gift cards/skins.
- **Kinguin**: filter by URL `&store=58`, not dropdown; candidate URL must
  contain `kinguin.net`; URLs carry `?params` (`nosalesbooster`, `currency`) —
  report them as-is (§4.6); Steam region often implicit GLOBAL; the "(valid until <Month>
  <Year>)" activation note is entered — stripped from the guard only, trailing only
  (`kinguin.guard_name`, Romain 2026-09-14, §4.4); "… PC Steam Altergift" = a Steam GIFT
  (25 / 259) when the slug does not contradict the title (`kinguin.gift_delivery`, §4.4).
- **MMOGA** (2026-09-10, `src/merchants/mmoga.py`; feed store id **12** — `&store=12`, the id
  every stage uses; the AKS product-page merchant id is 40, like Kinguin 58/47): URL
  `mmoga.com/<Platform>-Games/<Product>[-<REGION>-Key].html?ref=<affid>`.
  Platform = the URL category segment (`Steam-Games` → STEAM, `EA-Games` → EA, GOG/Epic/
  Ubisoft/Uplay/Rockstar/Battle.net/Windows mapped; console categories unmapped → console
  skip / fail-closed — classified under `--consoles`, §4.12 `[R45]`). Region = an **UPPERCASE 2-letter code right before the trailing
  "Key"** (`Borderlands 2 EU Key` → EU 9, `… US Key` → US 8, `… UK Key` → UK 71), read
  **case-sensitively**: `Among Us Key` (Us) is a global key. A forbidden code (RU/TR/BR/…)
  skips with the same `forbidden region: <LABEL>` string as everywhere; an **unmapped**
  code (DE, FR, …) skips `forbidden region: <CODE>` — fail-closed, never an implicit
  worldwide entry (price: a rare false skip on "… GO Key"-style acronyms). Resolution uses
  the title with the `<CODE> Key` tail peeled (`borderlands-2`, not the 404
  `borderlands-2-eu`); edition from the generic title rule (`Battlefield 4 Premium` →
  Premium); `?ref=615` is affiliate noise kept verbatim (§4.6) and ignored by every signal;
  a non-`mmoga.com` URL fails closed. In the safe-auto allowlist since 2026-09-10 on
  Romain's explicit decision (« je préfère passer directement par /auto »), before any
  supervised validated run — the first sweeps are the validation; watch the recap.
- **Gamivo** (`src/merchants/gamivo.py`, `[R46]` 2026-09-12; feed store id **51**): region =
  the TITLE tail (`… EN United Kingdom` → UK 71, `… United States` → US 8, `… EU` → EU 9,
  `… Global` → GLOBAL 2; any other tail — Colombia, ROW, Canada, Netherlands… — → forbidden-
  region skip, routed by the one router), platform = the URL run between the slug and the
  region code (`…-pc-steam-us-standard` → Steam, `-pc-ea-app-` → EA, `-pc-ubisoft-connect-`
  → Ubisoft, `-pc-battlenet-` / `-battle-net-gift-` → Battle.net, `-pc-gog-` → GOG; console
  runs → §4.12 `[R45]`); `-gift` in the run → the platform's gift bucket; resolution uses the
  title with the `[<LANGS>] <Region>` tail peeled. `-en-` / `EN` is a language marker, not a
  region (MA7 retired); the old grammar (`-global`/`-eu`/`-steam-key-<lock>`) is still read by
  the generic scans (§4.4).
- **Driffle**: `name`/`url` fields; `stock` is `"y"`/`"n"`; modal selects are
  `offer[region]`/`offer[edition]`; dynamic feed → re-scan before submit.
- **GOG**: everything is GOG GLOBAL(6)/Standard(1) unless the AKS page says
  otherwise; ~50% DLC/demo/OST → filter hard; modal only, never XHR.
- **K4G**: store 92; titles read `<Product> [Edition] [Region] <Platform> CD
  Key` with NO parens/dash separators → slug building must peel trailing
  platform/region phrases (matcher `_TRAILING_NOISE_PHRASES`), and dashes
  inside product names are real ("Endless Space - Disharmony"); heavy
  console share (~25%); pagination `&p=N`, sweep until 0 new offers; "… Steam Altergift"
  = a Steam GIFT (Romain 2026-09-14: `k4g.gift_delivery` → GIFT 25 / GIFT EU 259, the word
  dropped from the guard and the slug, §4.4) WHEN the slug agrees (`-altergift-` /
  `-alter-gift-`) — a `-cd-key` slug against an Altergift title (Trine 5, offer 101030313),
  a slug without any delivery segment, the mirror conflict, or a non-Steam Altergift is the
  precheck's fail-closed skip (review fixes 2026-09-14).
- **Difmark**: store id 167. Every product URL carries a literal
  `buy-console-account-` path segment regardless of what's actually sold —
  boilerplate, not a signal. **Never a skip reason**; it is stripped
  (case-insensitively) before any URL-derived matching signal — both region
  (Ga01, URL wins over title) and edition-from-slug — is computed (matcher
  `strip_merchant_url_noise` / `MERCHANT_URL_IGNORE_SUBSTRINGS`, Romain
  2026-07-17). The stored/reported offer URL itself is left untouched (§4.6).
  Real example: `https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307?referal=allkeyshop&marketplace_id=2&edition_id=780&region_product_id=1&seller_id[]=275327&seller_id[]=2300110`
  is read as `https://difmark.com/en/rogue-loops-steam-account-166307?...` —
  the `edition_id=780`/`region_product_id=1` query params are Difmark's own
  internal ids (no known mapping to AKS ids) and are not used as a signal;
  region/edition still come from the (cleaned) path text and the title.
  - **Page-verified platform + region (Romain 2026-07-17).** Difmark's AKS-feed titles
    are typically bare `<Name> [Edition] Standard Edition` — no platform word — and the
    region is not in the URL either ("il y a des offres Steam EUROPE qui ne sont pas
    indiquées dans l'URL"), so the generic path would R27-skip almost everything
    (historique — batch 1 counts : CHANGELOG 2026-07-17). For both signals, the merchant's
    own page is strictly more reliable than inferring from AKS's page, so
    `match_offer` fetches it directly for Difmark instead of falling through
    to the generic R20/R27 title/AKS-page logic: plain GETs only (no
    CDP/browser — "les pages marchand, tu peux les curl") to the product URL,
    then the `url_top_offer_with_get_params` link that page embeds, landing
    on a small JSON API whose `offer_attributes` carry authoritative
    `marketplace` and `region` text (`resolve_difmark_offer` →
    `DifmarkOfferAttributes`, `src/matcher.py`). One fetch pair serves BOTH
    signals when both are missing — not fetched twice. Known vocabulary:
    platform `Steam` only so far (`DIFMARK_PLATFORM_TEXT_MAP`); region
    `Global`/`Europe`/`United States`/`United Kingdom`
    (`DIFMARK_REGION_TEXT_MAP`). Anything outside either map, or a
    page/API that can't be read, fails closed — SKIP, never a guess (G02).
    (Historique — the Afterlife VR example : CHANGELOG 2026-07-17.) The R20 cross-check against the
    AKS page's own official-platforms list still applies on top (a
    page-verified Steam that the AKS page doesn't list under "official
    platforms" still fails closed) — its skip message says "Difmark
    merchant page says X", not "title says X", when the source was the
    merchant page.
  - Confirmed live: the site-wide "regions" dropdown embedded on every
    Difmark page (a residence/currency continent picker: `{"value":1,
    "text":"Europe"}`, ...) is a *different* vocabulary from the per-offer
    `region` attribute above — decoding the URL's `region_product_id`
    through that dropdown would have been silently wrong (id 1 = "Europe"
    there, but the real per-offer attribute for that same example was
    `region: Global`).
  - **Account offers (Romain 2026-07-17, rounds 1-2; historique — the two report
    escapes and Romain's quotes : CHANGELOG 2026-07-17).** Difmark's AKS-feed titles
    never carry the word "Account" and the URL's "steam-account" segment is boilerplate on
    every listing, so the `STEAM ACCOUNT` categorical skip never fires for Difmark; the
    **only** place the account-vs-key distinction shows up is the merchant's own per-offer
    `offer_name` (`"Rogue Loops (Steam Account) / Region GLOBAL / Edition Standard"` vs a
    genuine key's differently-shaped name, e.g. `"RIMWORLD [STEAM/GLOBAL] [OFFLINE]"`) —
    so the merchant page is fetched **unconditionally** for every Difmark offer, not only
    when platform/region are ambiguous. An "ACCOUNT" `offer_name` is NOT a skip: AKS's own
    region dropdown (`offer[region]` select) carries a **parallel "Account" bucket for
    many platforms** — `Steam Account (412)`, `Steam EU Account (480)`, `Steam Row Account
    (577)`, `steam account us (578)`, and equivalents for Epic/Nintendo/PlayStation/Xbox/
    Windows/Ubisoft/Origin/Publisher/Subscription — a legitimate, distinct region for
    account-delivery listings. The region lookup is redirected to
    `DIFMARK_STEAM_ACCOUNT_REGION_IDS` (base key → id, Steam platform only, no UK entry
    exists) instead of the normal `REGION_IDS["STEAM"]`; the reported `region_label`
    becomes e.g. `"GLOBAL ACCOUNT"` / `"EU ACCOUNT"` so the report visibly distinguishes
    them from plain Steam. A platform other than Steam, or a region with no confirmed
    Account variant (UK), fails closed — SKIP, never a guessed id (G02). **The ids came
    from a catalog snapshot (`runs/20260708-081329-k4g/session_catalog.json`) — re-verify
    against a fresh dropdown fetch (P06, "dropdown is truth") before Difmark's first real
    submit.**
    **Round 3 (Romain 2026-07-18): the account offer must resolve AKS's dedicated
    account PAGE, not the game key page.** AKS carries a SEPARATE product page per
    account platform — `buy-<slug>-<platform>-account-compare-prices/` — a distinct
    product with its own id/editions/prices (verified live: `Final Knight Steam Account`
    = 187974, editions `{5:"Early Access"}`, while the key page `Final Knight` = 171000;
    every existing listing on 187974 uses region 412 — page-account + region-account is
    internally consistent). Implementation: `aks_url(slug, page_kind)` +
    `resolve_aks(page_kind=…)` build `…-<kind>-compare-prices/`
    (`DIFMARK_ACCOUNT_PAGE_KINDS={"STEAM":"steam-account"}`, Steam-only
    confirmed); `match_offer` routes account offers through the injectable
    `account_resolver`. **No R30 site-search fallback for account pages** (the
    result regex only knows `-cd-key-` slugs) — they rely on slug-guessing.
    The account page's name ends with the page-kind words
    ("Final Knight **Steam Account**"), page-TYPE metadata the feed title
    ("Final Knight Standard Edition") never carries, so R01 compares against
    the stripped **identity** (`account_identity()` → "Final Knight"); a
    resolved account-URL 200 whose name lacks the suffix fails closed ("not an
    account page"). Caveat (pre-existing, unchanged): the generic Difmark
    "Standard Edition" title yields Standard(1) even when the account page's
    only edition is Early Access(5) — safe (product-scoped dropdown
    fail-closes at submit), but surfaced in the report for human validation.
  - **Operating cadence — one page at a time (Romain 2026-07-17).** "Faut se
    rappeler que la prochaine fois, on fait page par page. On prend les 100
    offres de la page et on regarde. On envoie un rapport sur ce qu'on peut
    entrer et on le rentre." Difmark's feed is large (hundreds of pages) and
    refreshes multiple times a day, deleting and recreating every offer id on each
    refresh, so a batch matched ahead of its submit is dead on arrival. Cadence:
    **extract exactly ONE page (100 offers) → match → send the
    report → Romain validates what's enterable → submit that page's
    validated batch → only then move to the next page.** Never extract/match
    several pages ahead of what's about to be validated+submitted. Historique (the
    2026-07-17 dead-on-arrival batch, the earlier "~10 pages" guidance) : CHANGELOG
    2026-07-17.
  - **`--max-pages` auto-defaults from the feed's own page count (2026-07-20).**
    The submit's batch-start coverage scan aborts (`feed_unreadable`) if it hits
    the `--max-pages` ceiling while the feed advertises more pages (§7/SC4) — a fixed
    40-page floor cannot cover a several-hundred-page feed (historique : CHANGELOG
    2026-07-20). The extractor persists the feed's advertised
    page count (`feed_last_page` in `raw.json`/`offers.json`), and `05_submit`
    defaults `--max-pages` to `max(40, ceil(feed_last_page × 1.3))` (30% churn
    headroom) — an explicit `--max-pages` still overrides, and the effective
    value + reason is printed. It does
    NOT change the cadence rule above (still one page at a time). NB: only runs
    extracted with this change carry `feed_last_page` — a pre-2026-07-20 run's
    `offers.json` lacks it and falls back to the 40 floor (re-extract to benefit).

---

## 12. Open items to confirm against the evolving skill

- Merchant id inconsistencies in the skill (e.g. Gamivo merchant `—` vs `218`) —
  resolve from the live dropdown at runtime, not from tables.
- Full `references/*.md` may add merchant rules; fold them into §11 as they land.
- **Console keys `[R45]` — questions for Romain (2026-09-12, §4.12; the code runs under
  `--consoles`, the DEFAULT since 2026-09-15 — `--no-consoles` opts out —, and the
  multi-target write is proven by the canaries of 2026-09-15, §6):**
  - ~~**P1**~~ **CLOSED 2026-09-14** — Romain: « clé PS5 seule = page PS5 seulement, pareil
    pour Xbox Series, PS4, Xbox One, Switch et Switch 2 » = "merchant declaration ∧ AKS
    page", a lone declared platform → that page only, cross-gen → both (§4.12 P1,
    AGENTS.md "Reviewed decisions"). No "page alone" switch.
  - **P2** Play Anywhere = the PC page's truth: merchant "+ PC/Windows" WITHOUT PA on the
    page → skip; PA on the page WITHOUT a merchant mention → PA targets (XBOX/PC bucket on
    PC + One + Series). Confirm both directions.
  - **P3** PS5 outside GLOBAL ("PS5 … [EU]") → skip today; create PS5 EU/US/UK buckets in
    the tool, or keep skipping?
  - **P4** Eneba's 704 generation-less "XBOX LIVE Key" rows → skip (no declaration) — or
    read the Eneba page?
  - **P5** console DLC / season pass → skip in v1.
  - ~~**Per-target overwrite semantics of the new modal**~~ **CLOSED 2026-09-14/15** —
    observed with `--inspect` (2026-09-14) and proven by the two canaries (2026-09-15):
    ONE Create with N target rows (`offer[targets][i][target|region|edition]`, cap 3,
    `[data-add-target]` adds a row), each row carrying its own region / edition — §6
    "Modal v2", `SUBMITTER_SPEC.md` §4c. Still to confirm on AKS: the creation on the
    second page of canary 2 (Diablo 2 Resurrected, Xbox Series 70802) once the page cache
    refreshes (CHANGELOG 2026-09-15).
  - The "PS4" reading of the "Playstation Game Code …" family (`88` / `88eu` / `88us` /
    `88uk`): the labels never say PS4 — confirm `88` is the PS4 bucket, not a generic
    PlayStation one.
  - **Riders Republic (AKS 50562)**: the Gamivo Xbox One/Series US key entered PUBLISHER
    GLOBAL Premium on 2026-09-11 (§4.12 "The leak") is to be corrected by hand.

---

## 13. « Learning » — deux sens, ne jamais les confondre

1. **`--mode learning`** (R24, §submit) : un mode de SOUMISSION. Il ÉCRIT
   (canary de 1). Rien à voir avec les annotations.
2. **La vue Learning de l'admin** (2026-07-21) : capture d'annotations humaines
   par offre NON-matchée d'un run — région/édition (ids réels du catalogue de
   session), commentaire, page AKS, disposition « Move to list » (défaut
   *garder* = aucune action). Stockée dans `runs/<id>/learning.json`
   (+ `learning_log.jsonl`, un événement JSONL par save).

Règles de la vue Learning (audit `AUDIT_LEARNING_2026-07-21.md`) :

- **Processus officiel (D2, Romain 2026-07-22)** : la généralisation des
  annotations passe par le **processus builder-offline** — voir
  `docs/LEARNING_PROCESS.md`. Il n'y a **pas** de moteur de règles apprises
  dans le repo (pas de règle appliquée automatiquement au runtime).
- **Capture seulement.** Aucun code pipeline ne lit `learning.json`. La
  généralisation en règles matcher est un processus builder-offline : le LLM
  propose, la règle finale est du code déterministe testé + documenté + commité.
  Jamais de LLM runtime dans le pipeline.
- **Save = merge fail-closed** : jamais de remplacement intégral ; suppression
  uniquement par `cleared` explicite ; précondition `base_sha` (409 en conflit) ;
  champs validés côté serveur (liste ∈ catalogue, région/édition ∈ catalogue de
  session, `aks_url` = page AKS, ≤ 2000 caractères).
- **Une annotation n'est PAS une règle.** C'est une donnée source, tracée
  (`by`/`at`/`first_by`/`first_at`). Une correction spécifique à une offre ne
  devient une règle générale que par le processus builder (règle explicable,
  testée, documentée, révocable par revert).
- **Portée explicite (D3, Romain 2026-07-21)** : chaque annotation porte un
  champ `scope` ∈ {`exception_offre`, `regle_marchand`, `regle_globale`,
  `observation`}. Le `scope` est une **portée maximale *proposée* (une
  intention), pas une preuve de validité** (RV5, 2026-07-22) : `regle_marchand`/
  `regle_globale` *autorisent* le builder à **envisager** une généralisation
  qu'il doit **valider** (reproduire, tester) avant de coder — la portée
  effective peut être plus étroite. Non renseigné = observation = pas de règle.
  La généralisation ne se déduit JAMAIS d'un commentaire libre. Une 4ᵉ
  disposition possible : **observation retenue** (aucune action encore — preuve
  insuffisante), voir `docs/LEARNING_PROCESS.md`.
- **Plateforme (D4, Romain 2026-07-21)** : champ `platform` ∈ vocabulaire
  canonique (`ANNOTATION_PLATFORMS`, learning_io) — la correction de
  plateforme est une annotation à part entière (une plateforme seule suffit).
- **Suggestion ≠ décision (D1 option b, Romain 2026-07-21)** : la disposition
  Move-to-list pré-suggérée est persistée avec `suggested: true` tant que
  l'opérateur n'a pas manipulé le select (toute manipulation = confirmation,
  le flag tombe). **Le mover ne consomme QUE les dispositions avec
  `suggested != true`.**
- **Le mover Move-to-List** (Stage 6, `scripts/06_move.py` + `src/mover.py`,
  construit 2026-07-21) est un writer frère du submitter : plan de validation
  construit depuis les dispositions CONFIRMÉES de `learning.json`
  (`src/move_plan.py`) → invariants verts + authoritative → **dry-run par
  défaut** (`--execute` pour écrire) → go explicite → locate row (id→URL) →
  résolution liste cible par LABEL live → register (injection du hidden bulk[item][]) → set
  bulk[list] → clic trusted Apply → **vérif post-action : l'offre a quitté la
  liste source** (seul signal de succès) → logs JSONL + BlockLedger. Mode R24
  (safe = plan complet ; learning/advanced = canary de 1). Jamais
  fire-and-forget. Les dispositions *garder* et `suggested: true` ne sont
  JAMAIS dans un plan (filtrées par le builder).
- **Batch (`--mode safe`)** : réactivé (2026-07-22) derrière une **double garde** — le flag `--i-authorize-batch` ET une **autorisation** issue d'un canary vérifié (`src/move_auth.py`, liée à mover version × store × source × extraction × listes cibles validées). Chaque move du lot prouve source **ET** cible (RV2). Le canary unitaire (`--mode learning`) reste la seule voie pour VALIDER une nouvelle liste cible / de nouvelles données avant qu'un batch puisse les couvrir.
- **Tri batché — Stage 9** (`scripts/09_sort_move.py` + `src/sort_move.py`,
  2026-07-23→29) : même `Mover`/RV2, mais piloté par le **classifieur de tri** (une
  liste cible à la fois, multi-store) et non les annotations. Le mécanisme
  **batché** (`--batch`, P1→P1.6) enregistre N offres sur une page source → **UN
  Apply natif** (`bulk[item][]` répétable) → vérifie le groupe d'un coup (~50-100×).
  Gardes déterministes : re-check d'identité fraîche avant chaque register ;
  `moved = coché-par-nous ET parti-source (scan PROUVÉ, dual-key id+URL) ET
  présent-cible (RV2)` ; une erreur feed/CDP après un Apply → tout l'in-flight
  **UNKNOWN** (jamais « moved »), fail-closed + abort. **P1.6 `--deferred`** (lot
  complet `safe` uniquement, sans `--limit`) diffère la vérif source+cible à **une
  fois par store** — pages **plus-haute-d'abord** (reflow-safe : déplacer une page
  haute ne décale que les offres après elle) ; fenêtre d'attribution par-store.
- **Ledger de tri — seul le TERMINAL est skippé (`src/sort_ledger.py`,
  `_ledger_status`)** : le mode incrémental saute les URLs déjà **résolues**. Est
  terminal (skip définitif) UNIQUEMENT : `moved`, `already_gone` (parti prouvé), ou
  `identity_mismatch` (la ligne échoue le contrôle d'identité (name,url) — id/slug
  réattribué à un AUTRE produit). Toute absence **transitoire** — row not-present /
  vanished au moment du move (un opérateur parallèle qui reflow le feed), glitch
  bulk/register/Apply, feed-error UNKNOWN, still-on-source, `apply_not_confirmed` —
  reste **hors ledger** et est **réessayée** au run suivant (règle issue de la revue
  P1.6 du 2026-07-29 — un reflow bénin ne doit jamais devenir un blocage permanent ;
  historique : CHANGELOG 2026-07-29).
  **`_reverify_row` : l'URL est l'identité, l'id ne l'est jamais `[P1-4]` (audit
  2026-09-02).** L'id est instable (chaque ré-import le fait tourner ET peut le
  RÉATTRIBUER à un autre produit). Règle : quand l'id
  est absent **ou** est un autre produit, RELOCALISER par l'URL ; trouvée → adopter son
  id courant et continuer ; URL absente de cette page → **retriable** (reflow/partie),
  jamais terminal. `identity_mismatch` reste réservé au vrai cas : l'URL est **présente**
  mais nomme un autre produit (slug réutilisé) ou store contradictoire. Vérifié en
  adverse : aucun move de mauvais produit possible (le `_row_check` final re-vérifie
  name+url+store après relocalisation). Historique (l'id réattribué filé en
  `identity_mismatch` terminal) : CHANGELOG 2026-09-02 (P1-4).
- **RV2 = scan cible GLOBAL, jamais par store (`_verify_on_target` /
  `_verify_group_on_target`, fix 2026-07-31)** : la présence sur la liste cible se
  prouve sur la vue **tous-stores** (`store_id=None`), pas sous le store source de
  l'offre. Une liste cible est inter-stores et une offre juste déplacée peut être
  ABSENTE de sa vue filtrée par store (rotation store/id au ré-import,
  [[feed-reimport-id-rotation]]) tout en étant sur la liste. L'URL marchande est
  propre au store → un match global est sans ambiguïté (pas de faux positif) ; un
  scoping par store donnerait des faux « pas sur la cible » (historique — Gift cards
  2026-07-31 : CHANGELOG 2026-07-31).
- **Store à feed source account-scale = HORS-SCOPE du pipeline batché (décision
  Romain 2026-08-03)** : la preuve fail-closed « parti de la source » exige un scan
  source full-coverage ; sur un feed de plusieurs **centaines de pages** (account
  ~290 ; Gift cards store 162 6494 offres dans un feed de **920 pages** ; store 126
  1783 dans 920 pages) ce scan est soit infaisable en par-groupe (K× le walk
  complet), soit rate-limité en différé (`net::ERR_CONNECTION_REFUSED`, plafond
  account). Le gain batché n'est réel que pour un store dont le **feed source est
  parcourable**. Les mega-stores attendent un mécanisme dédié (preuve « parti »
  ciblée sans full-coverage, ou ops natives AKS) — chantier séparé.

---

## 14. Workflow unifié par page — ADD / MOVE / SKIP `[R35]` (2026-08-13)

> **Cap de pages = couverture, pas une halte (2026-09-09).** Le défaut `--max-pages 30` du
> safe-auto s'arrête aux 30 pages les moins profondes ; un feed plus long est enregistré
> dans le champ `coverage` du recap du marchand (`incomplete_max_pages (feed has N pages)`,
> idem `incomplete_feed_grew (a→b pages)`), jamais dans `halted` : le lot continue, exit 0.

Romain : *« vu qu'on passe page par page, on peut ajouter des offres safe. Par la
même … envoyer certaines offres dans certaines listes … et on skippe ce qu'on a à
skipper. Puis on passe à la suivante. »* Une seule passe sur une page du feed
marchand classe **chaque** offre en exactement une action :

- **ADD** — `match_offer` renvoie un Candidate → entrée (safe-auto submit) ;
- **MOVE** — skip routable (`suggest_target_list` mappe la raison vers une liste)
  → déplacement hors du feed ;
- **SKIP** — skip sans liste (garder) → laissé en place.

Le classifieur (`src/triage.py` : `triage_offer` / `build_page_triage`) s'appuie sur
la décision **complète** de `match_offer`, pas sur `precheck_skip` seul — donc un
signal visible seulement sur la page marchande (région Instant Gaming) route
correctement (un IG *Steam RU* devient MOVE→Blacklist, pas un ADD GLOBAL muet). Le
tri tous-stores (`src/sort_plan.py`) reste, lui, precheck-only (échelle account, pas
de fetch par offre).

**Allowlist marchand = gate AUTORITATIF au cœur `[P2-2]` (audit 2026-09-02).**
Safe-auto ÉCRIT sans validation humaine, donc la liste des marchands vettés
(`auto_merchants.rejection_reason`) est un gate autoritatif, pas une suggestion UI.
Le handler HTTP le re-vérifie (`app.py _post_data_entry_auto`) ET l'entrypoint
DÉTERMINISTE qui lance réellement les écritures (`scripts/10`) applique **la même
allowlist**, fail-closed (store canonique imposé), refusant tout le batch sur un miss — un
marchand parqué (`Difmark:167`) ne peut pas balayer ni créer en contournant le gate
(historique : CHANGELOG 2026-09-02, P2-2).

**Aperçu incomplet = refus au cœur by-urls `[P2-3]` (audit 2026-09-02).** Un
aperçu by-urls n'est saisissable que COMPLET. Le handler console refuse un aperçu
partiel (`aborted`, un jeu non-résolu / `error` / `search.truncated`, ou
`len(games) != totals.games`), et comme `scripts/12` appelle `run_by_urls_submit`
(`src/data_entry_auto`) DIRECTEMENT, hors handler, `preview_incomplete_reason` (mêmes
conditions que le manager) est appliqué au cœur : `run_by_urls_submit` **abort
fail-closed** (aucune saisie) sur un aperçu partiel — jamais « skipper les jeux
non-résolus et soumettre le reste » (historique : CHANGELOG 2026-09-02, P2-3).

**Routage MOVE ancré sur la CATÉGORIE, jamais un free-substring `[P2-4]` (audit
2026-09-02, prolonge Audit L8).** `suggest_target_list` ne route **que** les raisons
`skip category: …`, et uniquement sur le **token de catégorie** (texte après le
« : », avant toute « (parenthèse) ») — jamais la raison entière ni la parenthèse. Le
matcher émet des raisons hors-catégorie qui interpolent des tokens de titre bruts
(`different/expanded product — extra words: ['account']`) : un match sous-chaîne sur la
raison entière enverrait une telle offre en **MOVE→liste 30 sous `--move-execute`** sur un
simple mot de titre (historique : CHANGELOG 2026-09-02, P2-4). Les émetteurs `skip category:` réels
n'interpolent que du vocabulaire fixe (`CATEGORY_SKIP`/`BUNDLE_SKIN_TOKENS`/…), donc
l'ancrage sur le token conserve toutes les routes légitimes (SOFTWARE→16, GIFT
CARD/STEAM GIFT CARD→21, STEAM ACCOUNT→30, skins/OST/artbooks→8) tout en fermant le
vecteur. Les offres *account* réelles sont routées à part par
`sort_plan.is_account_offer` (marqueur `(Account)`), pas par du texte libre.

**Intégration au sweep safe-auto** (`src/data_entry_auto.run_sweep`, opt-in
`--triage` de `scripts/10`). Ordre par page, reflow-safe (page la plus haute
d'abord) : extract → match → (approve + submit des ADD, **vérifiés**) → **move des
MOVE** → page suivante. Le move tourne aussi sur une page 0-ADD (une page peut être
tout en skips). Fail-closed identique au submit : un move non-clean **halt** tout le
sweep (`MoveOutcome.clean()`), un stop opérateur avant un write l'empêche.

**Le move est plus verrouillé que le submit.** Un batch `06_move --mode safe` est
**refusé** tant qu'un **canary `learning` (move de 1) n'a pas validé chaque liste
cible** (autorisation RV3, `src/move_auth.py`, §13). Donc le pas MOVE du sweep est
**dry-run par défaut** (Romain 2026-08-13) : il **planifie** les moves de la page
(`triage_moves.json`, pur, sans navigateur, depuis `skipped.json`) sans rien
déplacer ; les ADD, eux, sont écrits pour de vrai. `--triage` absent = sweep
ADD-only historique, inchangé.

**`--move-execute` = canary-puis-batch PAR PAGE, auto-autorisant `[R36]` (2026-08-14).**
L'autorisation RV3 est liée au **hash exact de l'extraction** (`skipped.json`,
`src/move_auth.extraction_id`) — elle **ne peut donc pas être pré-accordée** pour une
page future (chaque page a un nouveau `skipped.json`). Chaque page s'auto-autorise
donc, **liste par liste** (`src/triage.execute_page_moves`) : (1) un **canary**
(`06_move --mode learning` = move de 1, prouve RV2 gone-source + present-cible →
`grant_from_canary` accorde l'autorisation pour CE run_dir) ; (2) un **batch**
(`06_move --mode safe --i-authorize-batch`, désormais couvert) déplace le reste.
Fail-closed : un canary qui bouge 0 (liste non validée) ou toute phase cassée
(abort / stop non-bénin) → halt du sweep. Subtilité vérifiée en revue adversariale :
le signal de **succès** d'un canary est `stopped="limit_reached"` (il a bougé son 1
et atteint le cap) — c'est **bénin** (comme `data_entry_auto._BENIGN_STOPPED`), pas
une panne ; sinon le batch ne tournerait jamais. Double garde contre un bulk non
validé : le garde `moved>=1` ET le `batch_authorized` propre à 06_move.

**Vérif BATCHÉE `[R37]` (2026-08-17).** La vérif RV2 unitaire fait un **scan feed-entier
par move** (« parti de la source » exige une couverture complète — jamais une fenêtre
page-hint, sinon fail-open sur re-import/opérateur parallèle, revue 2026-08-06). Sur un
feed profond c'est plusieurs minutes par move et une charge CDP qui fait échouer des
navigations (historique — Kinguin ~104 pages, 2 sweeps calés : CHANGELOG 2026-08-17).
`06_move --batch/--deferred` (déjà côté tri) enregistre N offres → **un Apply + une vérif
de groupe** (deferred : une fois par store), **~G× moins de scans**, sans affaiblir la
couverture. Discipline : un batch batché exige un **canary MULTI-ITEM** (un Apply ≥2 offres
prouve le mécanisme) — `move_auth.multi_item_proven`, `batch_authorized(require_multi_item)`.
L'orchestrateur (`scripts/10`) : liste ≥2 offres → canary `--batch --limit 2` puis batch
`--batch --deferred` ; liste à 1 offre → unitaire. La garde R24 « widening » exempte le
`--limit 2` batché (`--batch`) ; `move_plan.json` est supprimé (unlink) avant chaque
invocation pour qu'un plan stale ne soit jamais compté (historique — revue adversariale :
CHANGELOG 2026-08-17).

**Saisie par page = consoles par défaut `[R45]` (Romain 2026-09-15).** « Travailler sur une
page de jeu » (`scripts/11` aperçu → `scripts/12` saisie, console admin « Saisir ») suit la
même décision que le sweep : `--consoles` est le **défaut** sur les deux scripts,
`--no-consoles` = l'ancien run PC seul. Règles déterministes, fail-closed :

1. **URL** : `buy-<slug>-<kind>-compare-prices/`, `kind` ∈ `ps4 ps5 xbox-one xbox-series
   nintendo-switch nintendo-switch-2` (`parse_page_url` → `PageRef(slug, kind)` ; les formes
   PC `cd-key` / `-key-` / `compare-and-buy-…` et `<plateforme>-account` gardent leur
   lecture ; l'alternative KEY passe en premier — un slug PC contenant « ps4 » reste la page
   PC ; `nintendo-switch-2` est reconnu avant `nintendo-switch`). Une page console est lue
   comme la page PC (`resolve_pinned`, mêmes retries bornés, jamais de devinette de slug).
   Sous `--no-consoles` une URL console est **refusée avant tout fetch** (`ConsolePageRefused`),
   rapportée par URL (`resolved: false`), les autres URLs continuent.
2. **Recherche** : page console → terme nom = `console_page_identity(aks_name)` (« Hades
   Xbox Series » → « Hades »), terme url = slug du jeu ; jamais le suffixe plateforme (le
   marchand écrit « Hades (PS4 / PS5) », pas « Hades Xbox Series »). R42 (chiffres romains)
   s'applique à l'identité.
3. **Résolution épinglée** (`PinnedPage`) : le matcher demande `resolver(name)` (page PC,
   ancre du plan console) et `resolver(name, page_kind=k)` (page console de kind `k`, ancre
   sans page PC), puis `page_resolver(url)` par onglet déclaré. La page épinglée répond sa
   propre kind (et, si elle n'est pas console — PC ou account — la demande PC nue, comme
   avant) ; toute autre kind est servie depuis **sa barre d'onglets** (`console_pages`) via
   le lecteur de pages (lecture seule, `resolve_aks_url`), `None` sans onglet (→ le skip
   fail-closed du matcher « no AKS product page found (console) » / « AKS has no <fam>
   page »). Cache d'une lecture par page sœur et par jeu ; la page épinglée n'est jamais
   relue ; une erreur de probe n'est jamais mise en cache. Le lecteur de pages est enveloppé
   dans un `_ThrottleGuard` **partageant** l'état de la garde de résolution des URLs (un
   flux de probes, un abort : 429 ou 5 non-fiables consécutives → `aborted: aks_throttled`,
   `game.error: aks_throttled`, jamais un skip « error: » par ligne).
4. **Qualification** : un candidat est retenu **ssi l'une de ses `targets` est la page
   demandée** (`_off_page_reason`) ; il est gardé **entier** (toutes ses pages), jamais
   réduit à la page demandée. « Une clé cross-gen demandée depuis une page console est
   écrite sur toutes ses pages déclarées » (P1 inchangé : jamais de page sœur ajoutée).
   Page PC + `--consoles` : candidats PC comme avant + clés Xbox Play Anywhere (cible
   XBOX_PC = page PC) ; une clé console sans PA depuis la page PC → skip explicite `not on
   the requested page <pid>: this offer targets <fam> <pid> …`. Page PC + `--no-consoles` :
   strictement l'ancien comportement (skip « console »).
5. **Saisie** (`scripts/12`) : flag accepté, transmis à rien ; groupement par store inchangé
   (dicts candidats entiers, empreinte étendue R45) ; `05_submit` lit `targets` dans
   `approved.json`.

---

### `[R59]` Gamesplanet FR (store 55) — plateforme dans l'URL, région sur la fiche (2026-09-25)

Romain : « go pour Gamesplanet FR avec ta règle + un pays UE exclu mais États-Unis autorisés →
US ». `src/merchants/gamesplanet.py` : la plateforme vient du segment de livraison de l'URL
(`-steam-key--`, `-gog-key--`, `-epic-games-key--`, `-microsoft-store-download--`,
`-rockstar-key--`…), un segment inconnu est refusé par son nom ; la région vient du bloc
« REGION LOCK INFO » de la fiche produit (`offer_page_resolver`), lu en HTTP. Règle, sur les pays
exclus (pour une liste « ONLY » : les absents) : ni UE, ni UK, ni USA → GLOBAL ; UE sans USA →
EU ; USA sans (toute) l'UE → US ; ni l'un ni l'autre → refus `forbidden region: GAMESPLANET LOCK
(EU + US)` ; UK seul exclu → refus `… (UK)` ; fiche illisible ou sans ses repères (`prod-data`,
`platform badge`) → refus R32, jamais un GLOBAL par défaut. La page AKS doit toujours vendre la
plateforme de l'URL (R20).

### `[R54]` Gamerall (store 13) — région : titre → URL → page (2026-09-18)

**Dans la liste blanche safe-auto depuis le 2026-09-19** (Romain : « Tu peux ajouter Gamerall
aux marchands whitelisted ? ») — `src/admin/auto_merchants.py` fait foi. Il écrit donc sur AKS
sans relecture humaine. Ce qui le rend acceptable : sa règle de région est la plus stricte du
dépôt (page ouverte quand titre et URL se taisent, refus quand la page est illisible ou muette,
jamais de repli sur GLOBAL), sa 1re saisie a fait 10 / 10, et les deux défauts trouvés par
l'audit du 18/09 au soir — le jeton `UPLAY` inconnu de `REGION_IDS` et la branche console qui
n'ouvrait jamais la page — sont corrigés et verrouillés par test. À savoir tout de même : ces
deux correctifs sont POSTÉRIEURS à la seule saisie réelle du marchand, donc sa première passe
en safe-auto est aussi la première mise à l'épreuve de la configuration corrigée.

Le titre de Gamerall finit par sa plateforme entre parenthèses et ne porte jamais de région ;
l'URL porte la plateforme et, dans 82 % des cas, la région (`global` / `europe` / `usa`).
Pour les lignes sans région, **la page marchand est ouverte** et sa valeur `Region` lue
(arbitrage de Romain, 2026-09-18) : le mécanisme est celui d'Instant Gaming
(`MerchantConfig.offer_page_resolver`), pas un nouveau lecteur.

Ordre imposé, du gratuit vers le coûteux : **titre, puis URL, puis page**. Le résolveur reçoit
désormais le titre en plus de l'URL — contrat élargi le même jour pour tous les marchands.

Fail-closed : page injoignable, réponse non conforme, ou page lisible sans région exploitable
⇒ **refus**, jamais un repli sur GLOBAL. Une région lue mais non vendable remonte son libellé
brut, dont le routage (Blacklist / garder) reste décidé en un seul endroit.

**Corrigé le 2026-09-19 (Romain) : deux régions dans un titre = REFUS, pas la première.**
Romain : « Gamerall accepte des régions contradictoires. Avec `Hades (Nintendo Switch) GLOBAL
US`, le classifieur détecte deux régions incompatibles. Le résolveur marchand prend ensuite la
première et produit un candidat GLOBAL (99). `EUROPE USA` produit pareillement EU (99eu). »
La queue du titre était lue au `search` : la première région gagnait, la seconde disparaissait
en silence. Elle est lue ENTIÈRE (`title_regions`, `finditer`) — un titre n'est déclaré lisible
qu'après avoir été lu en entier. Deux BASES différentes (le dédoublonnage porte sur la base :
« WORLDWIDE GLOBAL » dit deux fois la même chose) ⇒ refus nommant les deux zones, dans
`precheck`, donc **avant `url_region` et avant toute ouverture de page** — un titre
contradictoire ne coûte pas une requête, et le refus vaut pour la branche PC comme pour la
branche console (`precheck_skip` est appelé en tête de `match_offer`, avant l'aiguillage).
`title_region` LÈVE (`GamerallTitleAmbiguous`) au lieu de rendre `None` : rendre `None` ferait
descendre `offer_signals` sur l'URL puis sur la page et entrerait la clé sur une région que le
titre CONTREDIT — un repli déguisé, exactement ce que cette règle interdit.

**Corrigé le 2026-09-19 (Romain) : un SEUL lecteur de parenthèse.** `title_region` lisait la
DERNIÈRE parenthèse depuis le 18/09, mais `title_platform`, `resolve_name` et `precheck`
exigeaient encore qu'elle TERMINE le titre. « Hades (Steam) EUROPE » était donc refusé au
précontrôle (« plateforme non reconnue en fin de titre »), et la lecture de région du TITRE —
celle que cette règle place en PREMIER, avant l'URL et la page — devenait inaccessible. Les deux
lectures divergeaient : c'est précisément la divergence qui a produit le défaut. `resolve_name`
coupe désormais AVANT la parenthèse, pour que la queue de région parte avec elle (sans quoi le
slug sondé serait « hades-europe »).

**Corrigé le 2026-09-18 (audit complet), deux défauts du même fichier :**

1. **Les jetons de plateforme sont ceux du matcher, jamais le nom commercial.** Le fichier
   rendait `UPLAY` pour Ubisoft Connect — un nom que `REGION_IDS` ne connaît pas, là où tous
   les autres marchands normalisent en `UBISOFT`. Le matcher lisait donc `UBISOFT` dans le
   titre et `UPLAY` dans l'URL : **100 % des lignes Ubisoft Connect étaient refusées** sur un
   faux « platform conflict: title=UBISOFT vs offer page=UPLAY », c'est-à-dire un refus
   MENSONGER, pas un refus lisible. Verrouillé par un test qui confronte chaque jeton émis au
   vocabulaire de `REGION_IDS`.
2. **La branche CONSOLE consulte désormais `offer_page_resolver`.** Elle ne le faisait jamais :
   une URL `/playstation/…-ps5` donne `families=('PS5',)`, `region_base=None`, aucun mot de
   région → GLOBAL implicite, page jamais ouverte, `GamerallPageUnreadable` jamais déclenché.
   C'est exactement ce que cette règle interdit. La branche console ne lit QUE la région : la
   plateforme vient du classifieur console, et la confronter au jeton PC du résolveur
   produirait un faux conflit (PSN / NINTENDO ne sont pas des familles PC). Vaut aussi pour
   `[R33]` (Instant Gaming), qui n'était pas exposé faute de famille console déclarée.
