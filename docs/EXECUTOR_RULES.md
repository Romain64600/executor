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
- The real page count comes from the feed's own pagination nav (`.tablenav`
  links, rendered on every page incl. past-the-end) — bound the scan by it,
  never by "first empty page" heuristics.
- Some feeds re-order between page fetches (G2A 2026-07-07: 762 rows seen /
  482 distinct in one pass) → repeat **full sweeps**, unioning by offer id,
  until a whole sweep adds 0 new offers. Sweeps exhausted while still finding
  new ids = abort loudly (`FeedUnstableError`), coverage not proven.
- A blank in-range page is NEVER accepted at face value (seen live 2026-07-07:
  transient blank render on page 1 passed as "empty feed"): re-fetch once,
  then only two blank states are legitimate — page 1 with feed UI and **no**
  pagination (empty queue) or a past-the-end page after a mid-sweep shrink.
  Anything else aborts loudly (`EmptyPageAnomaly`).
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

## 4. Stage 2 — Matcher (pure, deterministic)

Consumes the normalized offers JSON; emits candidates JSON + skipped JSON. No
network side effects except read-only AKS slug `200` checks.

### 4.1 Name match — necessary condition `[R01]`
Tokenize the AKS product name (NFKC-normalize, then apostrophes
`U+2019/U+2018 → '`). **Every meaningful word of the AKS name must be present
in the merchant title.** One word missing → **SKIP**. (Necessary, not
sufficient.)
**NFKC first `[R28]` (2026-07-16, Eneba "Road to Empress" escape):** "Road to
Empress Ⅱ" (U+2161, a single Unicode Roman numeral codepoint, not two ASCII
`I`s) tokenized to just ROAD/TO/EMPRESS — `tokenize`'s `[A-Z0-9']+` regex
silently drops any character outside that class, so the sequel indicator
vanished and the offer matched the unrelated base game "Road To Empress"
(AKS has no page for the sequel — 404). The same text feeds
`build_slug_candidates`, so the wrong page was being *probed* in the first
place, not just wrongly approved after tokenizing. Fix: NFKC-normalize
before both — standard-library, zero-dependency, and specifically designed
to decompose compatibility characters like Roman numerals into plain ASCII
("Ⅱ" → "II"). Curly quotes stay a separate explicit replace (not an NFKC
compatibility decomposition of `'`).

### 4.2 Different-product guard — `[R01b]`
Even if all words match, **SKIP** when the merchant title carries a dangerous
qualifier absent from the AKS name: `Remaster(ed)`, `HD`, `Reboot`, `Remake`,
`Redux`, `Season Pass`, `DLC`, `Upgrade`, `Skin`, `Soundtrack`,
`Digital Book/Artbook`, and since the 2026-07-17 audit (`MA3`) `Anniversary` /
`Definitive` — they were noise-whitelisted with no backstop, so "Skyrim
Anniversary Edition" entered the base-game page as Standard(1); the live
master catalog has no stable plain numeric id for either, so there is no safe
EDITION_HINTS entry — doubt goes to skip, and dedicated "… Anniversary/
Definitive Edition" AKS pages (name carries the word) are unaffected. Never
add a remaster to a base-game page unless the AKS page explicitly matches the
remaster `[critical learned rule]`.

### 4.3 Immediate SKIP list `[CORE_RULES][P04]`
Console (Xbox/PS/Nintendo); forbidden regions
(RoW/AMERICAS/ASIA/OTHER/North America/EU-NA/EMEA/NA/Eastern Europe/SEA/Middle
East/Turkey/Germany); Country Gift (CZ/RU/TR/BR/AR/IN/CN);
PREPAID/SOFTWARE/VPN/Subscription/Voucher/Gift Card/Currency; language
restrictions (EN/FR/ES "… Languages Only", EN/CS);
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
never enter bundles); **Microsoft Store Key / Microsoft Key**
(key-type marker only — "Microsoft Flight Simulator … Steam Key" stays Steam;
MICROSOFT platform has no region mapping → fail-closed) `[R17]`;
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

### 4.4 Region & platform — **URL and AKS page decide, not the title** `[Ga01]`
Derive region from the offer URL when the merchant encodes it there
(e.g. Gamivo `…-steam-global` / `-eu` / `-gift-eu`; look for
`-gift-`) `[GAMIVO]`. Kinguin Steam titles often omit the region → accept as
**GLOBAL implicit** unless a forbidden region is present `[KINGUIN]`.
**`MA7` RETIRED (2026-09-01, Romain: "EN = english only … on a quasi toutes les
régions qui ont leur version EN only").** A Gamivo `-en-` URL segment used to skip
as an EN-only *language restriction*; a language variant now ENTERS as the same
product. A language code (EN/FR/DE/…, `LANGUAGE_TOKENS`) counts as noise in the
different-product guard **only once EVERY AKS-name token has already been covered**
before it (nothing of the game name remains after it) — so "Hard Bullet VR Gift EN
Global" / "Neon Beats FR Global" enter, while a code with a game-name token still to
come stays a significant title word so a different (shorter) product is still caught:
"En Garde" / "The En Garde" / "Legend En Garde" ≠ "Garde"-family, "No Man's Sky" / "A
No Man's Sky" ≠ "Man's Sky" (Romain audit 2026-09-01 — an earlier rule armed on the
FIRST common/noise token, so a leading article THE/A wrongly neutralized the code).
Position after the FULL game name is the signal, never a global neutralization.
Audit 2026-07-17 hardenings: `gift` must be its own URL segment (`MA4` —
`the-gifted-rabbit` no longer proposes GIFT(25)); title-side defense in
depth for regions (`MA8`): bare `EUROPE` mid-title (K4G grammar) and a
region in ANY parenthesised group (not only the first) now map to EU/…
instead of implicit GLOBAL.
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

**Platform is page-verified, fail-closed `[R20]` (2026-07-08, Su-27 escape):**
`detect_platform`'s STEAM is a **default**, not a detection — "Su-27 for DCS
World Key GLOBAL" carries no platform token, was defaulted STEAM and entered
Steam GLOBAL(2) when the product is publisher-direct (Eagle Dynamics); Romain
had to fix the DB by hand. The only deterministic signal is the resolved AKS
page's "official platforms:" line (extracted at resolve time, zero extra
requests).
**Revision `[R26]` (2026-07-15, DCS P-51D Mustang / A-10C Warthog escape):**
a token-less title is no longer trusted as Steam even when that list is
exactly `Steam` — both DCS pages say "official platforms: Steam." with no
`Direct Publisher` entry, yet Kinguin's own title omission was the real
signal. R26 made any token-less title with *some* page platform signal
default to PUBLISHER.
**Revision `[R27]` (same day, Gameboost escape):** R26 was too broad. Hours
later, Gameboost proved the opposite failure mode — genuinely-Steam,
token-less offers got defaulted to Publisher too, because Gameboost's own
truth lives on its merchant page, which is unfetchable (Cloudflare blocks it
— see the merchant's own notes). Romain: *"il y a des offres steam qu'on
détecte en publisher, ça c'est seulement renseigné sur la page marchand."*
DCS and Gameboost are the **identical page-signal shape** (token-less title,
AKS page Steam-only) with **opposite ground truth** — neither a Steam default
nor a Publisher default is safe there. The only signal strong enough to
auto-resolve is a page that **explicitly confirms `Direct Publisher`**
(region `Publisher (1)`, the dropdown's GLOBAL bucket; EU 12, US 13, UK 266 —
ids read from the live session catalogs of 07-07/07-08, identical; no gift
mapping → publisher gifts fail closed). Anything short of that —
Steam-only, any other mix without Direct Publisher, or no platform info at
all — now SKIPs ("platform unverifiable, not defaulted (R27)"). DCS itself
reverts to skip; a human enters cases like it deliberately, same as the
`R19` stub-page philosophy: absent a real signal, don't guess in either
direction. Su-27 (page: Steam, Direct Publisher — a genuine positive signal)
is unaffected, still PUBLISHER.
**Eneba URL prefix `[R29]` (2026-07-16):** "Apothecarium: The Renaissance of
Evil - Premium Edition" carries no platform word anywhere in its title — it
fell into R27's token-less branch and correctly SKIPped there — but it's
genuinely Steam, and Eneba says so, just not in the title: every Eneba
listing URL is `eneba.com/<platform>-<slug>`, a leading platform-prefix path
segment present regardless of what the title repeats. `explicit_platform_from_url`
checks this **only** for `eneba.com` URLs (no other merchant's URL has a
title-word this could false-positive against) and only recognizes prefixes
this codebase already has a platform constant for (`steam`, `gog`, `epic`,
`uplay`→UBISOFT, `origin`→EA, `blizzard`→BATTLENET, `windows`→MICROSOFT);
console/currency/software prefixes (`nintendo`, `xbox`, `psn`, `top`,
`other`, `riot`, …) are left unmapped — already caught by the
console/currency/software-app categorical skips before platform detection
runs. Checked as a fallback after the title (`explicit_platform(offer.name)
or explicit_platform_from_url(offer.url)`), so an explicit title token still
wins when both are present. The same case also exposed an R25 interaction:
once correctly resolved to Steam GLOBAL(2)/Premium(34), it turned out to
already be a duplicate on AKS (Eneba merchant id 272) — the wrong Publisher
classification had been hiding it from the duplicate check too.
An **explicit** title token is the merchant's declaration and is
trusted — multi-platform pages are normal (an Osmos Steam+GoG page takes a
Steam key) — **except** when the token has a known page vocabulary
(STEAM→`Steam`, GOG→`GoG`, EPIC→`Epic Store`) and that name is totally absent
from the page list: contradiction → SKIP. Tokens without a vocabulary entry
(EA, UBISOFT, …) get no cross-check. Sweep 2026-07-08 over every offer ever
created/attempted (48 offers, 27 AKS pages, stubs included): Su-27 was the
only platform damage; page vocabulary observed live: Steam, GoG, Epic Store,
Direct Publisher, Xbox Play Anywhere, Nintendo eShop, Xbox.

### 4.5 Edition detection (fallback hints — dropdown is truth) `[E0x]`
**Stub guard first `[R19]` (2026-07-08, DCS A-10C Warthog escape):** an
**empty** editions map on the resolved AKS page is a stub record —
`"merchants":[],"editions":[],"prices":[],"regions":[]` in the page blob,
zero offers (PHP serializes the empty map as `[]`, not `{}`). Such a page can
vouch for no edition and can hide a DLC: A-10C (empty map) was entered
Standard(1) and Romain had to fix the DB by hand, while sibling DCS P-51D
Mustang (populated map, DLC bucket) was correctly entered DLC(16) by `[R18]`
in the same run. Neither the feed row nor the page carries any other
deterministic edition signal (measured 2026-07-08: 23/25 sampled candidate
pages had a populated map — even mono-edition ones show `1:Standard`; the two
empty ones split one hidden DLC / one legit standalone, so emptiness decides
nothing). **SKIP with a distinct reason** ("AKS page carries no editions map —
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
Standard). Systematic — the map is already in hand at resolve time.
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
before. The same mis-collapse had already mis-submitted an earlier offer of
this exact product that morning; Romain deleted the bad AKS entry by hand.

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
`detect_edition`'s generic hardcoded id (Deluxe→7, Gold→10, GOTY→9, …) was emitted with
NO proof the resolved page sells that tier → a wrong-edition write surviving human
validation ("Sniper Elite 4 Deluxe" on a base-only page; a slug-parasite
`…-complete-edition`). Now a non-Standard game edition is RECONCILED against the page's
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
Standard(1) is the safe canonical fallback and is exempt. (Three adversarial-review
rounds: closed a suffixed-label over-skip, a substring wrong-tier adoption, an
id-coincidence hole, and the "Digital Deluxe" false-skip.)

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

### 4.7 AKS resolution
Build the slug from the AKS name (lowercase, `[^a-z0-9] → -`), verify
`/blog/buy-{slug}-cd-key-compare-prices/` returns **200**, then extract
`data-product-id` (the AKS_ID) and `<title>`. Extract available editions from
the embedded `"editions":{…}` JSON `[EDITIONS.md]`.
**A transient (403/429/5xx/timeout) or name-unreadable answer on ANY guessed
slug raises IMMEDIATELY (`MA1`, audit 2026-07-17):** slug tiers go from most
to least specific, so collecting the failure and letting a less-specific
tier's 200 win silently resolved the wrong product tier (a deluxe title
landing on the base page). The docstring always promised the immediate
fail-closed; now the code does it.
**Markup drift is loud (`MA6`):** a `"prices"` block that is PRESENT but no
longer parses raises `AksPageUnparseable` → distinct skip ("AKS page markup
drifted"), never a silent empty tuple that would turn the R25 duplicate
guard off. Absence stays soft — stub pages legitimately serialize
`"prices":[]`, and absent editions/platform lines are already covered
fail-closed by R19 (empty map → skip) and R20/R27 (no platform info →
token-less skip).
**If the AKS product name cannot be read from the resolved page, the offer is
SKIPPED with a distinct reason — never fall back to the offer title as the AKS
name** (that turns the §4.1 identity check into a tautology; 2026-07-07 a
Microsoft Store Key offer surfaced as a "Steam US" candidate this way) `[R15]`.
**Duplicate guard `[R25]` (2026-07-15, Kinguin/Darkwood escape):** the same
resolve pass also extracts the page's own `"prices":[…]` current-offers list
— each entry carries `merchantName`, `edition`, `region`. A candidate whose
merchant already has an entry matching the resolved region **and** edition is
SKIPPED ("`<merchant>` already lists a price for this region/edition on AKS
(R25)") — the offer is still live on the merchant's own feed (that's what got
it this far), but AKS already has this exact price, from an earlier run, a
human operator working the same feed in parallel, or any other source. This
was caught live: candidate Darkwood (GOG GLOBAL(6), Standard(1)) had a
Kinguin price at that exact region/edition already on the page when Romain
flagged that a prior day's matched batch could be stale by submit time.
Zero extra requests — the price list is already in hand at resolve time,
same pattern as the editions/platforms checks below.

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
a guessed slug. Verified live: Eneba "Worms Collection 2014 Steam Key (PC)
EUROPE" (no guessable AKS page) search-resolved to an unrelated page
("Assassin's Creed Black Flag Resynced") — R01 correctly SKIPped it
("missing AKS words: ASSASSIN'S, CREED, BLACK, FLAG, RESYNCED"). Real-world
yield on the same Eneba skip batch was low (most token-less/unusual titles
still correctly resolve to nothing) but the mechanism is safe: search only
ever *proposes* a page, it never bypasses the identity gate.

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
5. R25 duplicate check + build `Candidate(platform="SOFTWARE", …)`.

`extract_regions` (`AksResolution.regions`) exposes the page region dropdown. The
list-**sort** console is unaffected — it still groups software under the Softwares
list via `is_software_title` (no page fetch). Doubt still goes to skip `[G02]`.

### 4.10 Per-merchant config — "start from the merchant config" `[R32]` (2026-08-11)

Merchant-specific handling was scattered (Kinguin's domain rule, Difmark's
offer-page resolver + maps, Eneba's URL prefixes; Gamivo's `-en-` language lock
was here too until MA7 was retired 2026-09-01).
Romain: **each merchant should start from its own config** — its specific
instructions. `src/merchant_config.py` `MerchantConfig` is the single declarative
place; `match_offer` reads `merchant_config(offer.merchant)` and applies it. A
merchant with **no** config keeps the generic behaviour (platform/region/edition
from the feed title + URL).

Trigger: a whole **Instant Gaming** safe-auto sweep entered every offer as
**PUBLISHER** although they were **STEAM**. IG lists Steam keys under **token-less**
feed titles on multi-platform AKS pages, so R27 defaulted them to Publisher — but
the real platform lives only on **the IG offer page** (`data-platform="Steam"`).

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
CDP/headless is needed**. A whole IG sweep had entered 32/54 region-locked offers as
GLOBAL before this; they now resolve their real region. The page is fetched ONCE per
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
  `Turkey` / `EMEA` …). Left in place; the operator decides. The five regions with a
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

---

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
user, never the request body `[P2-9]` (audit 2026-09-02):** it authorizes live
offer creation (non-repudiation), so `_post_validation` overwrites it with
`_basic_user()` — the authenticated identity wins over any client-supplied value
(mirrors L11, `_post_learning`). A no-auth standalone/dev request falls back to the
body field (production always carries the nginx-validated Authorization header).
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

## 6. Stage 4 — Submitter (dry-run by default, locked behind validation)

For each validated candidate, in order, fail-closed:

1. Refresh the current merchant feed again; locate the **exact current row**
   (feeds are dynamic — re-scan, never trust saved page numbers) `[DRIFFLE][GOG]`.
   In a batch, each creation shrinks the feed and **reflows the pagination**, so
   a row index built at batch start goes stale (2026-07-07 G2A: offer drifted
   from page 2 to page 1 after 8 creations → ROW_NOT_FOUND). The post-save
   verify scan walks the whole refreshed feed anyway — its result **replaces**
   the row index after every verified creation (zero extra page loads).
   **Offer ids are import-batch-scoped, not row identities**: AKS re-imports a
   feed on its own schedule and re-ids EVERY row (K4G 2026-07-08: 0/212 ids
   survived 74 min; G2A: 0/716 in 24 h). The stable row identity is the
   **merchant URL path** — query params drift across G2A re-imports (`uuid=`
   changed on 26/716 rows in 24 h while the path held 716/716; unique in-feed
   for both merchants). A candidate absent by id is re-located by URL path +
   **exact-title check** (fail-closed on any drift) and adopts the row's
   current id (`row_relocated` in the log). Absent by id AND path = the offer
   genuinely left the feed (worked in parallel / delisted) — a correct SKIP.
   **An index-scan miss is NOT trusted as that SKIP** (hardened 2026-09-01): the
   bulk index build (`_index_by_search` for by-urls; `_scan_page_window` for a
   sweep) can transiently drop a present offer — in a same-product multi-edition
   batch it dropped all-but-one (Whiteout Survival's 7 Frost-Stars editions entered
   1/7 per run while the other 6 sat in the feed). Before giving up, `_prepare`
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
   fresh_row`): the feed rotates every id on each re-import, so an id-match reads
   a still-present row as gone — the "reflowing too fast to pin" skip that lost a
   stably-pending offer over two runs (The Green Light Steam, 2026-09-01). The
   URL-matched row yields its CURRENT id for the modal open, and a slow JS render
   is render-polled (re-read, no re-navigate) before concluding absence. A row
   genuinely absent by URL (worked in parallel / delisted), or a URL now pointing
   at a different product, → blocker; never open a modal on an unverified row.
3. Open the modal from that row's `[data-create-offer]` button (`#TB_window`).
   The click returns as soon as it fires — the ThickBox loads `#TB_ajaxContent`
   ASYNCHRONOUSLY — so the modal context is **render-polled** (re-read, NO
   re-click) with the feed render-wait backoff before concluding it is missing
   (hardened 2026-09-01: an immediate read skipped a genuinely-open Kinguin modal
   as "modal context missing (#TB_ajaxContent)" — Simpler Times). Still absent
   after the backoff → fail-closed skip.
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
   `FORM_VALIDITY_UNREADABLE`, clean up, never click (audit P1b, 2026-07-08:
   the old code continued to the click on `ok:false` — explicit degraded mode,
   now removed).
8. Submit by a **trusted CDP click** (`isTrusted:true`) on the modal "Create offer"
   button — the only trigger Driffle's handler honours `[S09]`. It drives the
   modal's **own** `admin-ajax do=create_offer`; we never issue a direct XHR
   (the merchant id is auto-assigned by the modal).
   **A real write is `trusted`-only `[P2-1]` (audit 2026-09-02).** The `native`
   (`button.click()`) and `dispatch` (MouseEvent) click modes route to the UNGUARDED
   `fill_and_create` — no SC3 read-back, no `VALUE_DRIFTED_BEFORE_CLICK`, no
   `form_validity()` gate, no `NO_OPTION` guard (the very guards steps 5–7 add) — and
   produce `isTrusted:false` (proven not to persist). They are diagnostics only:
   `scripts/05 --submit` refuses them, and `Submitter` refuses a non-trusted
   `click_mode` unless an explicit `allow_degraded_click` opt-in is set (never in
   production). No degraded write path is selectable.
9. Verify post-save (§7), then close via `#TB_closeWindowButton`.
10. Pacing ≥ 500 ms between submissions `[S03]` — implemented as bounded-random
    pacers (`src/pacing.py`): `--pace-offers` (default `5-15` s) between offers,
    and `--pace-pages` (default `1-3` s) between feed-scan page loads — the real
    burst source, since the full feed is re-walked for the index **and after
    every creation** for post-save verify. `0` disables either. Pacing is never
    a correctness mechanism.

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

**Open invariant (not yet enforceable):** the matcher has no mode profiles yet,
so the mode is *declared* on `05_submit` and cannot be cross-checked against the
run. When `03_match` stamps a mode into `candidates.json`, `05_submit` MUST
re-verify it and fail closed on a mismatch — a run matched under an unlock must
never be submittable as `safe` and take the full-batch path.

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
from the refreshed feed"). The old single `writes` counter conflated the two
and overstated creations.

---

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
`StepGuard.record_result`. The mode matters: on Kinguin `available=pending` is
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
  first-read `[]`. A past-the-end page with `nav_max>=1` (nav rendered) stays a
  fast return — the nav proved the page count, no ambiguity;
- a login bounce mid-scan raises `NotLoggedInError`;
- the browser's `location.href` must match the page navigated to (a wedged
  tab re-serving the previous DOM is detected, never re-read as fresh pages);
- exhausting `max_pages` while the feed's nav advertises MORE pages raises
  instead of silently truncating coverage.

Mid-batch, any of these marks the current offer `post_save = "… offer state
UNKNOWN, verify it by hand …"` (attempt counted, creation NOT), stops the run
with `stopped="feed_unreadable"`, and still writes `submit_plan.json` + logs.
At batch start they abort with `aborted="feed_unreadable"` before any write.

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

**Merchant store ids** (verify against feed): Kinguin 58, G2A 38, Driffle 127,
Eneba 19, GameSeal 126, K4G 92, CJS 30, Instant Gaming 28, Gameboost 157,
Gamivo 51, Allyouplay 17, GOG 34, Difmark 167.

---

## 11. Per-merchant deterministic notes (brief)

- **G2A**: heavy non-game noise (~2-3% yield); SKIP CIS/ROW/
  Turkey/Germany/currency/gift cards/skins.
- **Kinguin**: filter by URL `&store=58`, not dropdown; candidate URL must
  contain `kinguin.net`; URLs carry `?params` (`nosalesbooster`, `currency`) —
  report them as-is (§4.6); Steam region often implicit GLOBAL.
- **Gamivo**: URL decides region (`-global`/`-eu`/`-gift-`), not the title.
  (`-en-` is a language marker, not a region, and no longer skips — MA7 retired.)
- **Driffle**: `name`/`url` fields; `stock` is `"y"`/`"n"`; modal selects are
  `offer[region]`/`offer[edition]`; dynamic feed → re-scan before submit.
- **GOG**: everything is GOG GLOBAL(6)/Standard(1) unless the AKS page says
  otherwise; ~50% DLC/demo/OST → filter hard; modal only, never XHR.
- **K4G**: store 92; titles read `<Product> [Edition] [Region] <Platform> CD
  Key` with NO parens/dash separators → slug building must peel trailing
  platform/region phrases (matcher `_TRAILING_NOISE_PHRASES`), and dashes
  inside product names are real ("Endless Space - Disharmony"); heavy
  console share (~25%); pagination `&p=N`, sweep until 0 new offers.
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
  - **Page-verified platform + region (Romain 2026-07-17).** Batch 1 (pages
    1-10, 658 offers) showed the dominant Difmark failure mode: 501/652
    skips (77%) were R27 ("no platform in title and AKS page does not
    confirm Direct Publisher") because Difmark's AKS-feed titles are
    typically bare `<Name> [Edition] Standard Edition` — no platform word at
    all — on top of the region gap ("il y a des offres Steam EUROPE qui ne
    sont pas indiquées dans l'URL"). For both signals, the merchant's own
    page is strictly more reliable than inferring from AKS's page, so
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
    Live example: Afterlife VR (title has no platform word) used to default
    to PUBLISHER via R27's AKS-page inference; the merchant's own page
    confirms `marketplace: Steam` — now entered as STEAM instead, the exact
    kind of silent mis-platforming R20/R26/R27 were written to catch for
    other merchants (DCS/Su-27, Gameboost). The R20 cross-check against the
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
  - **Account-vs-key escape, two rounds (Romain 2026-07-17, both caught from
    the normalized report).** Round 1: "je vois que pour Difmark, au lieu de
    Steam account, tu as lancé des Steam dans ton rapport normalisé." The
    pre-existing `STEAM ACCOUNT` categorical skip (`CATEGORY_SKIP`, checks
    `offer.name`) NEVER actually fires for Difmark — its AKS-feed titles
    never carry the word "Account" at all ("Rogue Loops Standard Edition"),
    and the URL's "steam-account" segment is boilerplate present on every
    listing regardless of delivery type. The **only** place the distinction
    shows up is the merchant's own per-offer `offer_name`
    (`"Rogue Loops (Steam Account) / Region GLOBAL / Edition Standard"` vs a
    genuine key's differently-shaped name, e.g. `"Sekiro: Shadows Die
    Twice GOTY"` or `"RIMWORLD [STEAM/GLOBAL] [OFFLINE]"` — confirmed live
    on real batch-1 offers) — so the merchant page is fetched
    **unconditionally** for every Difmark offer, not only when
    platform/region are ambiguous.
    **Round 2, immediate correction: "je voulais que tu renseignes la région
    Steam Account quand tu vois Steam Account. Pourquoi... tu les mets en
    Steam normal, alors que c'est des Steam Account aussi?"** The round-1 fix
    treated an "ACCOUNT" `offer_name` as a skip (reusing `CATEGORY_SKIP`'s
    STEAM ACCOUNT reasoning, which really does mean "un-enterable" for other
    merchants like G2A). Wrong for Difmark: AKS's own region dropdown
    (`offer[region]` select) carries a **parallel "Account" bucket for many
    platforms** — `Steam Account (412)`, `Steam EU Account (480)`, `Steam
    Row Account (577)`, `steam account us (578)`, and equivalents for Epic/
    Nintendo/PlayStation/Xbox/Windows/Ubisoft/Origin/Publisher/Subscription
    — a legitimate, distinct region for account-delivery listings, not a
    dead end. Confirmed via a cached live dropdown snapshot
    (`runs/20260708-081329-k4g/session_catalog.json`, `probe_select_options`
    on `offer[region]`, 867 rendered options). Fix: an `offer_name`
    containing "ACCOUNT" no longer skips — it redirects the region lookup to
    `DIFMARK_STEAM_ACCOUNT_REGION_IDS` (base key → id, Steam platform only,
    no UK entry exists) instead of the normal `REGION_IDS["STEAM"]`; the
    reported `region_label` becomes e.g. `"GLOBAL ACCOUNT"` /
    `"EU ACCOUNT"` so the report visibly distinguishes them from plain
    Steam. A platform other than Steam, or a region with no confirmed
    Account variant (UK), still fails closed — SKIP, never a guessed id
    (G02). **Ids came from a 9-day-old catalog snapshot — re-verify against
    a fresh dropdown fetch (P06, "dropdown is truth") before Difmark's first
    real submit.**
    **Round 3 (Romain 2026-07-18): the account offer must resolve AKS's
    dedicated account PAGE, not the game key page.** Rounds 1-2 got the
    *region* right (Account bucket 412/…) but still matched the game's
    `…-cd-key-…` page. AKS actually carries a SEPARATE product page per
    account platform — `buy-<slug>-<platform>-account-compare-prices/` — a
    distinct product with its own id/editions/prices (verified live:
    `Final Knight Steam Account` = 187974, editions `{5:"Early Access"}`,
    while the key page `Final Knight` = 171000; and every existing listing on
    187974, G2A included, uses region 412 — so page-account + region-account
    is internally consistent). Implementation: `aks_url(slug, page_kind)` +
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
    entrer et on le rentre." Difmark's feed is large (382 pages) and
    refreshes multiple times a day, deleting and recreating every offer id
    on each refresh (confirmed live 2026-07-17: an `approved.json` built
    from one page fetch was already unusable by submit time, hitting first
    `catalog_unavailable`/`no_openable_offer` — feed mid-reimport — then
    `feed_unreadable` — coverage unproven at the default 40-page cap — then,
    once repopulated, 10 consecutive failures because every approved id had
    rotated out from under it). The fix isn't only a bigger `--max-pages`;
    it's cadence: **extract exactly ONE page (100 offers) → match → send the
    report → Romain validates what's enterable → submit that page's
    validated batch → only then move to the next page.** Never extract/match
    several pages ahead of what's about to be validated+submitted — a batch
    sitting unsubmitted while the feed refreshes again is dead on arrival.
    This supersedes the earlier "batches of ~10 pages" guidance from the
    same day (that was already a correction on "don't sweep all 382 pages at
    once" — this narrows it further, to one page, once the id-rotation
    frequency became clear).
  - **`--max-pages` auto-defaults from the feed's own page count (2026-07-20).**
    The submit's batch-start coverage scan aborts (`feed_unreadable`) if it hits
    the `--max-pages` ceiling while the feed advertises more pages (§7/SC4);
    the old 40-page floor always aborted on Difmark's ~357-page feed unless the
    operator raised it by hand. The extractor now persists the feed's advertised
    page count (`feed_last_page` in `raw.json`/`offers.json`), and `05_submit`
    defaults `--max-pages` to `max(40, ceil(feed_last_page × 1.3))` (30% churn
    headroom) — an explicit `--max-pages` still overrides, and the effective
    value + reason is printed. This removes the manual-ceiling footgun; it does
    NOT change the cadence rule above (still one page at a time). NB: only runs
    extracted with this change carry `feed_last_page` — a pre-2026-07-20 run's
    `offers.json` lacks it and falls back to the 40 floor (re-extract to benefit).

---

## 12. Open items to confirm against the evolving skill

- Merchant id inconsistencies in the skill (e.g. Gamivo merchant `—` vs `218`) —
  resolve from the live dropdown at runtime, not from tables.
- Full `references/*.md` may add merchant rules; fold them into §11 as they land.

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
  reste **hors ledger** et est **réessayée** au run suivant. Règle née d'une revue
  P1.6 (2026-07-29) : la fenêtre différée par-store transformait un reflow bénin en
  `identity_blocked` permanent → une offre légitime perdue à jamais.
  **`_reverify_row` : l'URL est l'identité, l'id ne l'est jamais `[P1-4]` (audit
  2026-09-02).** L'id est instable (chaque ré-import le fait tourner ET peut le
  RÉATTRIBUER à un autre produit). `_reverify_row` cherchait la ligne par id et ne
  relocalisait par URL que si l'id avait **disparu** ; un id **présent mais réattribué
  à un autre produit** filait donc direct en `identity_mismatch` TERMINAL sans jamais
  chercher l'URL stable ailleurs sur la page → une offre encore présente (déplacée
  vers un nouvel id, souvent sur la MÊME page) skippée à jamais. Corrigé : quand l'id
  est absent **ou** est un autre produit, RELOCALISER par l'URL ; trouvée → adopter son
  id courant et continuer ; URL absente de cette page → **retriable** (reflow/partie),
  jamais terminal. `identity_mismatch` reste réservé au vrai cas : l'URL est **présente**
  mais nomme un autre produit (slug réutilisé) ou store contradictoire. Vérifié en
  adverse : aucun move de mauvais produit possible (le `_row_check` final re-vérifie
  name+url+store après relocalisation).
- **RV2 = scan cible GLOBAL, jamais par store (`_verify_on_target` /
  `_verify_group_on_target`, fix 2026-07-31)** : la présence sur la liste cible se
  prouve sur la vue **tous-stores** (`store_id=None`), pas sous le store source de
  l'offre. Une liste cible est inter-stores et une offre juste déplacée peut être
  ABSENTE de sa vue filtrée par store (rotation store/id au ré-import,
  [[feed-reimport-id-rotation]]) tout en étant sur la liste. L'URL marchande est
  propre au store → un match global est sans ambiguïté (pas de faux positif). Le
  scoping par store donnait des faux « pas sur la cible » qui sous-comptaient les
  moves ET gonflaient les échecs → breaker guard / FC3 à tort (Gift cards 2026-07-31).
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
Le handler HTTP le re-vérifie déjà (`app.py _post_data_entry_auto`), mais l'entrypoint
DÉTERMINISTE qui lance réellement les écritures (`scripts/10`) ne validait que
`store_id.isdigit()` → `--targets 'Difmark:167'` (parké, non-vetté) pouvait balayer et
créer en contournant le gate. `scripts/10` applique désormais **la même allowlist**,
fail-closed (store canonique imposé), refusant tout le batch sur un miss.

**Aperçu incomplet = refus au cœur by-urls `[P2-3]` (audit 2026-09-02).** Un
aperçu by-urls n'est saisissable que COMPLET. Le handler console refuse un aperçu
partiel (`aborted`, un jeu non-résolu / `error` / `search.truncated`, ou
`len(games) != totals.games`), mais `scripts/12` appelle `run_by_urls_submit`
(`src/data_entry_auto`) DIRECTEMENT, hors handler — et ne faisait que **skipper**
les jeux non-résolus pour soumettre le reste (couverture partielle expédiée sans le
409 de la console). `preview_incomplete_reason` (mêmes conditions que le manager) est
maintenant appliqué au cœur : `run_by_urls_submit` **abort fail-closed** (aucune
saisie) sur un aperçu partiel.

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
feed profond (Kinguin ~104 pages) c'est **~6 min/move** et la charge CDP longue fait
échouer une navigation (`Page.navigate` → halt) — 2 sweeps de suite calés ainsi. Correctif :
`06_move --batch/--deferred` (déjà côté tri) enregistre N offres → **un Apply + une vérif
de groupe** (deferred : une fois par store), **~G× moins de scans**, sans affaiblir la
couverture. Discipline : un batch batché exige un **canary MULTI-ITEM** (un Apply ≥2 offres
prouve le mécanisme) — `move_auth.multi_item_proven`, `batch_authorized(require_multi_item)`.
L'orchestrateur (`scripts/10`) : liste ≥2 offres → canary `--batch --limit 2` puis batch
`--batch --deferred` ; liste à 1 offre → unitaire. Revue adversariale (4 dimensions) : 2
défauts corrigés — la garde R24 « widening » rejetait le `--limit 2` batché (exemptée pour
`--batch`), et un `move_plan.json` stale double-comptait sur abort précoce (unlink avant
chaque invocation).
