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
| Login / 2FA / CDP fails 2× → STOP `[S15][I18b]` | login/2FA/CDP steps sized with `max_attempts_per_signature = 2`; second failure hard-blocks |
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
`Digital Book/Artbook`. Never add a remaster to a base-game page unless the AKS
page explicitly matches the remaster `[critical learned rule]`.

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
rejects in §6); multi-game bundles/collections;
**ANY software/application — games only** — categorical, word-boundary
brand + category tokens (`SOFTWARE_APP_TOKENS`: EaseUS/Avast/…/Adobe, VPN
brands, Internet/Total Security, Todo Backup/Data Recovery/…, Microsoft
Office/Office 20xx/365/Home, Windows 10/11/Server), even with a real AKS page
and clean platform/region (Romain, direct rule 2026-07-08, after "EaseUS Todo
Backup Workstation" reached validation on Kinguin p.2). Deliberately NOT
matched: `NERO` (the game N.E.R.O.), `AVG` (genre tag), bare
OFFICE/WINDOWS/BACKUP — `OFFICE`/`VPN` moved out of the substring category
list to word-boundary for this reason `[R22]`;
DLC/extension without base game; title with **≥1 significant word** absent from
the AKS name (platform/format/region/edition noise excluded, incl. `COM` from
"GOG.COM"; tightened from the CORE ≥2 floor on 2026-07-07 after the
"Offworld Trading Company - Interdimensional" DLC escaped with a single extra
word — doubt goes to skip) `[R16]`; **Microsoft Store Key / Microsoft Key**
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
(e.g. Gamivo `…-steam-global` / `-eu` / `-gift-eu`; look for `-en-` and
`-gift-`) `[GAMIVO]`. Kinguin Steam titles often omit the region → accept as
**GLOBAL implicit** unless a forbidden region is present `[KINGUIN]`.

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
instead of hand-editing `validation.json`. Same gate, same artifacts: every
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
2b. **Re-verify the row on the FRESH render** (audit 2026-07-17, SC5): the
   modal-opening navigate produces a NEW page load, minutes after the index
   scan — the row must still be there under that id AND still match the
   candidate (name + URL path, `check_price=False`) on the fresh DOM. A
   vanished row, or an id a mid-run re-import handed to a different product,
   → blocker; never open a modal on an unverified row.
3. Open the modal from that row's `[data-create-offer]` button (`#TB_window`).
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

## 9. Login / 2FA policy — Stage 0b, built (`LOGIN_SPEC.md`, 2026-07-14)

The rules below were fixed ahead of time and now govern the built stage
(`src/login_session.py`, `scripts/00b_login.py`; design in
[`LOGIN_SPEC.md`](LOGIN_SPEC.md)):

- Never ask for a 2FA code in advance. Ask **only** when the 2FA field is
  visible **and** the code can be typed and submitted immediately `[I18][2FA
  override]`.
- **One attempt each** for the password and the 2FA code, ever — a wrong one
  is a hard STOP in the same run, not "two then stop" (repeated failed logins
  can lock/flag the account; login is not a place to retry). Diagnose, wait
  for Romain, a fresh run is a new attempt.
- On connection loss, first check whether the existing Chrome session is still
  logged in (`already_logged_in()`, idempotent no-op); only invoke this stage
  if the feed redirects to `wp-login.php`, and only on Romain's explicit go —
  a `NotLoggedInError` from another stage stays a fail-closed STOP + error
  report, never an auto-trigger for this one `[S15]`.
- Password/code never stored, logged, or committed — read from the
  environment (`AKS_WP_USER`/`AKS_WP_PASSWORD`) and stdin only; redaction is
  `src/run_log.py`'s existing `RunLogger` key-name mechanism.

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
- **Gamivo**: URL decides region (`-global`/`-eu`/`-gift-`/`-en-`), not the title.
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
  - **`STEAM ACCOUNT` still applies to Difmark.** The Rogue Loops example
    above is a genuine full-credential account sale ("you will receive all
    the necessary login credentials…", confirmed on the merchant page) —
    correctly rejected by the pre-existing `CATEGORY_SKIP` entry, unrelated
    to the URL/region/platform fixes. In batch 1, none of the 658 sampled
    titles actually contained "Steam Account" (that wording lives in
    Difmark's own page `<title>`/URL slug, not the AKS-feed title field) —
    whether Difmark also lists genuine CD keys under a distinguishable title
    is still unconfirmed pending further batches.

---

## 12. Open items to confirm against the evolving skill

- Merchant id inconsistencies in the skill (e.g. Gamivo merchant `—` vs `218`) —
  resolve from the live dropdown at runtime, not from tables.
- Full `references/*.md` may add merchant rules; fold them into §11 as they land.
