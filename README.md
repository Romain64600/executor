# AKS Controlled Executor

A deterministic, auditable, **fail-closed** executor for AllKeyShop (AKS)
merchant-feed data entry: scanning merchant-feed offers, matching them to AKS
product pages, and submitting them through the WordPress admin feed.

It replaces a free-form LLM agent ("Hermes") that improvised whenever it got
blocked — looping on the same failed action, falling back to forbidden tools, and
reporting submissions that never actually landed in the database. The new design
moves the risky work behind a scripted engine with a hard guardrail: the model
**builds and supervises**, but never free-hands browser actions.

> **Resuming on a new server, or a fresh session?** Read
> [`docs/HANDOFF.md`](docs/HANDOFF.md) FIRST — current state, the from-scratch
> bring-up pointer, the decisions/gotchas that live outside the repo, and the
> backlog. Then `AGENTS.md` + `CLAUDE.md` (the rules).

> **New to the project?** Start with [`docs/NOOB.md`](docs/NOOB.md) — a
> beginner-friendly, analogy-driven walkthrough of the whole system (in French).

> **Status (2026-09-15) — full pipeline built and live; consoles entered by default.** The
> write stage created its **first real AKS offers on 2026-07-06** (Driffle); the safe-auto
> sweep runs on the proven merchants (460 offers created over one night on 2026-09-11/12);
> **console keys** (multi-target submit on the AKS modal v2) were proven by two canaries on
> **2026-09-15** and are ON by default everywhere since Romain's decision « 1 » of the same
> day. All write stages stay gated behind green + authoritative invariants on the Debian VPS
> target. Audits: **2026-07-17** ([`docs/AUDIT_2026-07-17.md`](docs/AUDIT_2026-07-17.md)),
> **2026-09-02** and **2026-09-05/06** (P1 + P2 fixed, [`docs/CHANGELOG.md`](docs/CHANGELOG.md)).
> See [Capability status](#capability-status-2026-09-15) and [Roadmap](#roadmap).

---

## Capability status (2026-09-15)

What a newcomer may expect from the current code — one line per capability, its state
(**disponible** / **expérimental** / **bloqué**), the condition under which it applies, and
the rule that governs it. The rule text lives ONLY in
[`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md); this table never restates it.

| Capability | State | Condition | Rule |
|---|---|---|---|
| Safe-auto PC sweep (`scripts/10_data_entry_auto.py`, admin `/auto`) on the 7 proven merchants — Kinguin 58, Gamivo 51, Driffle 127, MMOGA 12, G2A 38, Instant Gaming 28, K4G 92 | **disponible** | Romain's go; invariants green + authoritative on the VPS; one merchant per VPS; `--mode safe` = the full validated batch, prove-gone by feed search | EXECUTOR_RULES §14 `[R35]`, §6 `[R24]`, §7; per-merchant status in [`docs/MERCHANTS.md`](docs/MERCHANTS.md) |
| Console keys — matcher branch, multi-target submit on the AKS modal v2 (cap 3 targets), sweep / admin console / by-URL with **consoles ON by default**, `--no-consoles` to opt out | **disponible** since 2026-09-15 | Proven by two canaries (one target, then two via `[data-add-target]`); the first real MMOGA console sweep runs on 2026-09-15 — read its `recap.json` before the next merchant; P1 decided (declared platforms only), P2-P5 still to confirm with Romain | EXECUTOR_RULES §4.12 `[R45]`, §6 « Modal v2 », §10 (buckets); [`docs/SUBMITTER_SPEC.md`](docs/SUBMITTER_SPEC.md) §4c |
| Entry from a **console page URL** (`scripts/11` preview → `scripts/12` « Saisir », admin `/games`): `buy-<slug>-<kind>-compare-prices/`, kind ∈ ps4 / ps5 / xbox-one / xbox-series / nintendo-switch / nintendo-switch-2 | **disponible, non encore exercé en réel** | Code landed 2026-09-15 (unit-tested; no live read of a console page's tab bar yet); a candidate qualifies iff one of its targets is the requested page and is entered WHOLE; a console URL is refused per URL under `--no-consoles` | EXECUTOR_RULES §14 « Saisie par page » `[R45]` |
| Sweeps on Eneba 19, Allyouplay 17, GameSeal 126, CJS-CDKeys 30 | **expérimental** | Allowlisted but never swept for real — `--dry-run` first, read `skipped.json` / `candidates.json`, then Romain's go (Eneba dry-run of 2026-09-12: 32 candidates, 90 % console rows) | [`docs/MERCHANTS.md`](docs/MERCHANTS.md) (status table), EXECUTOR_RULES §4.10 `[R32]` |
| PS5 keys outside GLOBAL ("PS5 … [EU]") | **bloqué** | Fail-closed skip `no region id for PS5/EU (R45)`: the modal has a single PS5 bucket (`88ps5h`), no PS5 EU / US / UK — policy P3 awaiting Romain (create the buckets in the tool, or keep skipping) | EXECUTOR_RULES §4.12 P3, §10 |
| Eneba "XBOX LIVE Key" rows without a generation (title and URL silent) | **bloqué** | Fail-closed skip `console: no declared generation (R45)` — no declared platform, nothing to file (policy P4, awaiting Romain) | EXECUTOR_RULES §4.12.3 / P4 |
| Console DLC / season passes | **bloqué** | Fail-closed skip `console: DLC / season pass on console — not entered yet (R45)` (policy P5, v1) — PC DLC ARE entered on their own DLC page `[R43]` | EXECUTOR_RULES §4.12.4 (b) / P5; §4.3 `[R43]` |
| Instant Gaming console keys | **bloqué** | The platform is not in the IG feed (bare titles, `/en/<id>-/` URLs) and a console platform read on the IG page is not in `IG_PLATFORM_TEXT_MAP` → skip `[R32]` — no console entry from IG until a page-based hook exists | [`docs/MERCHANTS.md`](docs/MERCHANTS.md) « Instant Gaming », EXECUTOR_RULES §4.10 |
| Difmark 167 | **bloqué** | Parked, outside the safe-auto allowlist (`scripts/10` and the admin refuse it fail-closed); its account rows are never console keys (`console: ACCOUNT — not a game (R45)`); a first real submit needs a fresh catalog re-verification | EXECUTOR_RULES §14 `[P2-2]`, §11 « Difmark »; [`docs/MERCHANTS.md`](docs/MERCHANTS.md) |

---

## Why

A general-purpose agent is the wrong tool for high-stakes, repetitive data entry.
When blocked, it improvises — and improvisation here means: retrying a dead CDP
call six times, switching to a non-sanctioned browser, rotating a VPN that
wasn't needed, or (worst) trusting a `[data-success]` UI flash and reporting an
offer as created when it never hit the database.

This project inverts the model's role. A deterministic engine does the work; the
model writes, tests, and audits that engine. Every "success" is decided by code,
and a deterministic circuit-breaker (the [StepGuard](#the-stepguard)) stops the
process the instant a failure pattern appears — a stop that lives in program
state and cannot be argued away by a language model.

---

## Design

**Roles**

- **Builder** (Claude / Codex) — writes code, tests, docs, read-only
  diagnostics. Never submits offers through ad-hoc browser actions.
- **Controlled Executor** — the deterministic engine. Dry-run by default;
  submits only against an explicit validation file.
- **Hermes** — optional conversational supervisor. Reads reports, relays
  instructions. Never executes free-form AKS browser actions. "Optional" refers
  only to this conversational layer — **not** to the CDP proxy that shares the
  Hermes name (see [Requirements](#requirements)): that socat bridge is
  **required** for every browser-driving stage.
- **Admin page** — the operator's validation UI on the VPS
  (`https://<VPS_HOST>/executor/`, nginx HTTPS + basic auth):
  read the normalized report, approve/reject/override candidates, launch a
  supervised dry-run/submit. See [`ops/INSTALL_ADMIN.md`](ops/INSTALL_ADMIN.md).
- **N8N** — optional, later: orchestration, notifications, log archive.

**Principles**

- **Fail-closed.** If anything is uncertain, stop. No fallback browser, no
  Playwright, no Browserbase, no VPN when AKS direct works, no degraded submit.
  A **fail-closed STOP** and a **deterministic skip** are not the same mechanism:
  a STOP fires on doubt or anomaly (feed unreadable, modal context missing, an
  unresolvable pick), halts the whole run, and writes an error report; a skip is
  a rule firing on a known shape (a bundle, a console key, a gift card) that
  drops that one offer and lets the run continue.
- **Deterministic success.** Every recorded success comes from code, never a
  model self-assessment. A **write** never counts a bare HTTP 200 as success —
  a 200 proves only that a request was served, not that the data landed. Success
  is a deterministic **business** signal: a submit succeeds when *the offer
  disappears from the refreshed feed* (same available mode as the run), a Stage 6
  move when *the offer leaves its source list*. Only read-only steps (the
  invariant gate, resolve probes) legitimately read an HTTP status or a parsed
  error field as their outcome.
- **Guarded execution.** Every stage runs through the StepGuard.
- **Read-only until green.** No write stage runs until the invariant checker is
  `authoritative: true` **and** `ok: true` on the Debian VPS target.
- **Games — and AKS-listed software** `[R31]`. The matcher enters games and,
  since 2026-08-11, **software AKS actually sells** (Windows / Office / Adobe /
  media tools). Software is entered only when its **region and licence edition**
  (OEM / Retail / 1 PC / 1 Month …) are read **from the AKS page** — never a
  guessed "Standard" (some software pages have no Standard at all). When the
  edition or region can't be pinned to the page, the offer is **skipped**, not
  guessed. Games are untouched. See
  [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) **§4.9**.
- **Start from the merchant config** `[R32]`. Merchant-specific rules live in one
  place — `src/merchant_config.py` (`MerchantConfig`), read by the matcher via
  `merchant_config(offer.merchant)`. A merchant's config carries e.g. its domain
  (Kinguin) or an offer-page platform resolver (Instant Gaming lists Steam keys
  under token-less titles → the real platform is read from the IG offer page, not
  defaulted to Publisher). Since 2026-09-10 a merchant file (`src/merchants/<name>.py`)
  can also **add or override generic behaviour** through six optional hooks —
  `precheck`, `title_region`, `resolve_name`, `url_platform`, `guard_name`, `gift_delivery`
  (MMOGA's "`<Product> <CODE>
  Key`" grammar lives entirely in `src/merchants/mmoga.py`; Gamivo's title-tail + URL-run
  grammar in `src/merchants/gamivo.py`, `[R46]` 2026-09-12; Kinguin's "(valid until <Month>
  <Year>)" note entered and K4G's "Steam Altergift" = Steam Gift — Romain's rulings of
  2026-09-14 — in `src/merchants/kinguin.py` / `k4g.py`, §4.4). **One config file per
  merchant — Romain's rule (repeated since 2026-08-11, ultimatum 2026-09-14):** « pour la
  détection région / édition / plateforme, tu as un fichier de config par marchand. Et si
  tu ne l'as pas, tu dois l'avoir » — **every merchant of the safe-auto allowlist has its
  file** (Kinguin, K4G, Driffle, GameSeal, Allyouplay, CJS-CDKeys added on 2026-09-14; GameBoost 157, GamersOutlet 31 and Electronicfirst 70 on 2026-09-15 — `[R47]` / `[R48]` / `[R49]`, the three new merchants of the discovery audit: each fails closed where its titles do not declare the region (a silent GameBoost or GamersOutlet row, a silent Electronicfirst CONSOLE row); all three joined the safe-auto allowlist on 2026-09-16),
  merchant grammar never lives in a generic module, and four **console hooks** `[R45]` —
  `console_url_families`, `console_pc_declared`, `console_region_slot`, `console_noise` —
  moved the MMOGA / Gamivo / Eneba URL grammars out of `src/console_keys.py`, which keeps
  only the shared vocabulary. The name → module registry is `src/merchants/registry.py`
  (imported by the matcher and the classifier, no circular import). Per-merchant grammar
  and hooks: [`docs/MERCHANTS.md`](docs/MERCHANTS.md). See **§4.10**.
- **Region buckets + the PUBLISHER decision** `[R50]` / `[R51]` (2026-09-16). `REGION_IDS` is
  read from the live AKS dropdown (`catalog.json`, 867 options, identical across the 11
  catalogs saved 2026-09-10 → 15), and three platforms were missing buckets it had always
  carried — Rockstar (global / eu / us / uk), Epic (us / uk), EA (us / uk) — plus the Steam /
  Battle.net / Ubisoft gift buckets for US & UK, plus Microsoft, arbitrated by Romain
  (« Windows 10 pour les jeux, microsoft software pour les logiciels »: games take the Windows
  10 family 244-249 here, software resolves from the AKS PAGE via `[R31]`). 138 rows were
  refused "no region id" by mistake. `[R51]`: the AKS page's `Direct Publisher` line describes
  the GAME, not the merchant's key — a row whose platform is in NEITHER the title NOR the URL
  is now REFUSED unless the merchant declares that it reads its own page
  (`publisher_from_merchant_page`, default False, so the safety is on for every merchant).
  See **§4.4**.
- **Console keys — multi-target candidates, live** `[R45]` (2026-09-12 → 15). AKS has
  separate console product pages (`buy-<slug>-<kind>-compare-prices/`), and the AKS feed
  tool (modal v2) takes the region (= region/platform) and the edition **per target page**.
  Under the console branch — the **default since 2026-09-15** (Romain's decision « 1 »),
  `--no-consoles` for a PC-only run — the matcher classifies a console row from its title
  AND URL (shared vocabulary in `src/console_keys.py`, merchant grammar in each
  `src/merchants/<name>.py`), resolves one verified AKS page + bucket + edition **per
  DECLARED platform** (P1, Romain 2026-09-14: a lone "PS5" key → the PS5 page only, a
  "PS4 / PS5" key → both pages; PC only as page-verified *Xbox Play Anywhere*) and emits a
  candidate with one or several `targets`, or skips the whole row — **never a partial
  entry**, since a creation consumes the feed row. The submitter writes every target in
  ONE creation (modal v2, cap 3 targets, each row proven by readback; proven by two
  canaries on 2026-09-15). Policies P2-P5 await Romain's confirmation. Rules:
  [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) **§4.12** / §6 « Modal v2 »; status
  per merchant: [`docs/MERCHANTS.md`](docs/MERCHANTS.md).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full decision record.

---

## Repository layout

```
executor/
├── README.md
├── AGENTS.md                   # builder rules (Codex)
├── CLAUDE.md                   # builder rules (Claude) — imports AGENTS.md
├── .github/workflows/ci.yml    # CI: unittest suite + secret scan (push / PR)
├── docs/
│   ├── NOOB.md                 # beginner-friendly guide to the whole project (French)
│   ├── HANDOFF.md              # resume point: state, decisions, gotchas, backlog, reading order
│   ├── MERCHANTS.md            # one section per merchant: file, grammar, hooks, safe-auto status
│   ├── feeds/<Merchant>.md     # live feed state per merchant (scripts/14_feed_status.py)
│   ├── ARCHITECTURE.md         # roles & target flow
│   ├── INVARIANTS.md           # non-negotiable browser/network invariants
│   ├── SPRINT_1_PLAN.md        # read-only foundation scope
│   ├── EXECUTOR_RULES.md       # deterministic per-stage spec (from the skill)
│   ├── SUBMITTER_SPEC.md       # Stage 4 submitter spec (dry-run + trusted write path)
│   ├── AKS_LISTS.md            # Stage 6 Move-to-List: list taxonomy + move mechanic
│   ├── LEARNING_PROCESS.md     # learning → pipeline: the builder-offline process (D2)
│   ├── LOGIN_SPEC.md           # session re-auth: cookie transfer (password+2FA retired)
│   ├── DATA_CONTRACTS.md       # stage I/O JSON schemas + run-log format
│   ├── AUDIT.md                # Sprint 1 audit (2026-07-02) — fully resolved
│   ├── AUDIT_2026-07-17.md     # audit register 2026-07-17 — findings tracked OPEN → FIXED
│   ├── CONTRIBUTING.md         # developer guide
│   ├── CHANGELOG.md            # notable changes
│   └── ua-switcher-aks-staff.json  # UA-Switcher policy config (AKS/Staff UA)
├── scripts/
│   ├── 00_audit_env.sh         # read-only env audit, tags PASS/FAIL/N-A
│   ├── 01_check_invariants.py  # thin CLI over src/invariants.py (fail-closed JSON)
│   ├── 02_extract_feed.py      # read-only feed extractor CLI (gated on green invariants)
│   ├── 03_match.py             # read-only matcher CLI → candidates/skipped/report
│   ├── 04_validate.py          # validation CLI (template + check, fail-closed gate)
│   ├── 05_submit.py            # submitter CLI — dry-run default; --submit = real write (trusted)
│   ├── 06_move.py              # Stage 6 Move-to-List writer — dry-run default; --execute = real move
│   ├── 07_admin_server.py      # admin page server (loopback only, behind nginx basic auth)
│   ├── 08_sort_plan.py         # Stage 9 sort classifier → move plan
│   ├── 09_sort_move.py         # Stage 9 sort-move writer (batched / deferred)
│   ├── 10_data_entry_auto.py   # safe-auto sweep (extract → match → approve → submit per page; consoles by default)
│   ├── 11_data_entry_by_urls.py         # entry from AKS page URLs — read-only preview (PC and console pages)
│   ├── 12_data_entry_by_urls_submit.py  # entry from AKS page URLs — submit of a validated preview (safe)
│   ├── 13_aks_ping.py          # the ONLY sanctioned AKS reachability probe (AKS/Staff UA)
│   └── 14_feed_status.py       # per-merchant feed state → docs/feeds/<Merchant>.md (read-only on runs/)
├── manual_launch/
│   └── run_executor.sh         # terminal-only launcher: prepare / check / dry-run / submit
├── ops/                        # admin page install: systemd unit, nginx vhost, runbook
├── src/
│   ├── admin/                  # admin page: HTTP app (app.py), safe run access (runs.py),
│   │                           #   validation triple regen (validation_io.py), supervised
│   │                           #   submit (submit_manager.py), cookie-transfer re-auth
│   │                           #   (login_manager.py), Learning annotations (learning_io.py),
│   │                           #   static/ UI
│   ├── aks_env.py              # constants, pure validators, env classification, HTTP probes
│   ├── browser_lock.py         # advisory flock on state/browser.lock — one tab, one navigator (OP1)
│   ├── cdp_client.py           # read-only CDP /json/version client (no browser actions)
│   ├── cdp_session.py          # read-only CDP WebSocket session (navigate + evaluate)
│   ├── invariants.py           # invariant report builder — probes run through the StepGuard
│   ├── contracts.py            # stage I/O data contracts (RawSnapshot / NormalizedOffer)
│   ├── extractor.py            # Sprint 2 read-only feed extractor
│   ├── matcher.py              # Sprint 3 read-only matcher (candidates + skipped) — generic pipeline only
│   ├── merchant_config.py      # MerchantConfig contract: data fields + PC hooks (R32e) + console hooks (R45, 2026-09-14)
│   ├── merchants/              # ONE FILE PER MERCHANT (Romain's rule, 2026-09-14) — grammar + hooks, never in a generic module
│   │   ├── registry.py         #   merchant name → module CONFIG (imported by matcher AND console_keys, no cycle)
│   │   ├── common.py           #   shared by the merchant files ONLY (region words, R45 skip strings, make_config) — never imports matcher / console_keys
│   │   ├── kinguin.py  k4g.py  driffle.py  gameseal.py  allyouplay.py  cjs.py   # new 2026-09-14
│   │   ├── mmoga.py  gamivo.py  eneba.py  g2a.py  instant_gaming.py                     # existing
│   │   └── difmark.py          #   parked merchant (outside the safe-auto allowlist)
│   ├── console_keys.py         # R45 console classifier — SHARED vocabulary only (families, title phrases, page kinds, bucket table); merchant grammar via hooks — pure
│   ├── data_entry_auto.py      # safe-auto sweep engine (scripts/10) + by-urls submit core (scripts/12)
│   ├── triage.py               # R35 per-page ADD / MOVE / SKIP classifier + page moves (--triage)
│   ├── feed_status.py          # per-merchant feed state report (scripts/14) — pure functions on runs/
│   ├── validation.py           # Stage 3 validation gate (approve exact candidates)
│   ├── submit_session.py       # read-only + narrow WriteSubmitSession (trusted picks/target/click)
│   ├── submitter.py            # Stage 4 submitter — dry-run + real write path
│   ├── mover.py                # Stage 6 Move-to-List writer (the submitter's sibling)
│   ├── move_plan.py            # Stage 6 plan builder — confirmed learning.json dispositions
│   ├── move_auth.py            # RV3 canary-granted move authorization (scoped, versioned)
│   ├── sort_plan.py  sort_move.py  sort_ledger.py   # Stage 8/9 all-stores sort plan, batched sort-move writer, incremental ledger
│   ├── aks_lists.py            # merchant-feed list catalog + deterministic triage suggestions
│   ├── login_session.py        # cookie-transfer primitives (set_cookies + verify_dashboard)
│   ├── pacing.py               # bounded-random pacing between page loads / submissions
│   ├── run_log.py              # append-only JSONL run logger (redacting)
│   └── step_guard.py           # deterministic, fail-closed StepGuard
├── tests/                      # unit tests
├── runs/  logs/  state/        # runtime dirs (gitignored)
└── .gitignore
```

---

## Requirements

- **Python 3.11+** (Debian 12 target; urllib gained 308-redirect support in 3.11,
  so the two HTTP backends only behave identically on 3.11+) — the core is
  standard-library only. The sole **optional** dependency is `requests`
  (`requirements.txt`): when installed it backs the AKS resolve probes with an HTTP
  keep-alive Session (~1.85× faster matching, ban-safe — same request count); when
  absent the code falls back to urllib with the same probe contract (status / ok /
  body) — the wire shape differs (keep-alive, gzip) and the few known divergences are
  all fail-closed (see `_http_open_keepalive`), never a less-closed outcome — so the
  invariant gate stays dependency-free (the keep-alive Session ignores `~/.netrc` and
  the CA-bundle env vars; proxy env vars are mirrored from urllib's own handling).
- Production runtime target: a **Debian VPS** whose **CDP proxy is required** for
  every browser-driving stage — a socat bridge exposing the headless Chromium on
  the Docker bridge at `http://172.17.0.1:9223/json/version` (the official
  endpoint; `ops/BROWSER_RUNBOOK.md` §1.3). This bridge is mandatory even though
  the Hermes conversational supervisor is optional; the two only share a name.
- Session re-auth is **cookie transfer** only (AKS is social-login only;
  password+2FA Stage 0b is retired). From `/executor/tri` → 🔑 Se reconnecter,
  paste the WP session cookies after completing social login in your own
  browser. Cookie VALUES are session secrets — never logged, stored, or
  committed. See [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md).

---

## Quick start

```bash
# 1. Environment audit (read-only). Run on the Debian VPS target:
./scripts/00_audit_env.sh
#    → writes runs/audit_<timestamp>/audit.md
#    → final RESULT line: GREEN / RED / NON-AUTHORITATIVE

# 2. Invariant gate (read-only). Must be authoritative:true AND ok:true on the VPS:
python3 scripts/01_check_invariants.py

# 3. Unit tests (pure — run anywhere; 2087 tests on 2026-09-17, ~6 min, hermetic):
python3 -m unittest discover -s tests

# 3b. The browser console's JS is EXECUTED, not spell-checked. Needs the Debian
#     package `nodejs` (test-only dependency, Romain's go 2026-09-17); the Python
#     test SKIPS cleanly without it:
node tests/js/sort_race.test.mjs
```

**Environment classification.** The audit and the invariant checker detect where
they run. Only the real Debian VPS target is `authoritative`; a red result on
macOS, a dev box, or a sandbox is **not** a production failure and never unlocks
write stages. Authority comes ONLY from the root-installed marker
`/etc/aks-executor.target` (content = hostname; FC2, audit 2026-07-17) —
`AKS_TARGET=dev` can force NON-authoritative for local work, and there is
deliberately no override in the other direction.

---

## Manual launch

For a terminal-only data-entry run, use the helper in
`manual_launch/run_executor.sh`. It wraps the existing scripts without adding any
LLM/agent call. It still preserves the hard validation gate: `prepare` stops
before approval, and real writes require the explicit `submit` command.

(The admin page on the VPS drives these same scripts from the browser — this
section is the terminal equivalent.)

Start from the repo root:

```bash
cd /home/debian/executor
```

Prepare a run:

```bash
manual_launch/run_executor.sh prepare --merchant Driffle --store-id 127
```

This runs the audit, invariant gate, extraction, matcher, and validation-template
generation. It prints the generated run directory, for example:

```text
Prepared run:
  /home/debian/executor/runs/2026-07-13_101500_driffle
```

That directory is the `RUN_DIR` used by the next commands. You may pass it as an
absolute path:

```bash
manual_launch/run_executor.sh check /home/debian/executor/runs/2026-07-13_101500_driffle
```

or, when already in the repo root, as a relative path:

```bash
manual_launch/run_executor.sh check runs/2026-07-13_101500_driffle
```

After `prepare`, edit `RUN_DIR/validation.template.json` manually: set
`approve: true` only on the exact candidates you want, and fill
`validated_by` / `validated_at`. Then verify the validation file:

```bash
manual_launch/run_executor.sh check runs/2026-07-13_101500_driffle
```

`check` writes `approved.json` and saves the validated template as
`validation.json`. Both `candidates.json` and `validation.json` must sit next to
`approved.json`; the submitter re-checks them before any dry-run or real submit.

Rehearse the submitter without writing to AKS:

```bash
manual_launch/run_executor.sh dry-run runs/2026-07-13_101500_driffle --merchant Driffle --store-id 127
```

Submit — `--mode` (default `safe`) decides the batch size `[R24]`. In `safe`, the
validated report **is** the safety gate, so the **whole approved batch** goes in
(no canary):

```bash
manual_launch/run_executor.sh submit runs/2026-07-13_101500_driffle --merchant Driffle --store-id 127
```

`learning` and `advanced` also write, but are capped at a **canary of 1** offer
for now (`--limit N` can narrow that cap, never widen it):

```bash
manual_launch/run_executor.sh submit runs/2026-07-13_101500_driffle --merchant Driffle --store-id 127 --mode learning
```

Optional extraction flags can be passed during `prepare`:

```bash
manual_launch/run_executor.sh prepare --merchant Driffle --store-id 127 --pages 3-5 --pace 2-5
```

`--pages` creates a partial page slice; do not treat it as full-feed coverage.

**Console keys — consoles by DEFAULT, `--no-consoles` to opt out** `[R45]` (default **on**
since 2026-09-15, Romain's decision « 1 »). The read-only matcher (03), the safe-auto sweep
(10), the admin launcher (`/auto` checkbox « Consoles », checked) and the by-urls preview /
« Saisir » (11 / 12) all take consoles into account by default: console rows are classified
and resolved to their AKS console pages instead of being skipped `console`, and a key sold
for several platforms becomes a **multi-target** candidate (`targets` in
`candidates.json`, stamped `consoles: true` in `match_meta.json` / `recap.json`).
`--consoles` is still accepted as an explicit no-op; **`--no-consoles`** (03, 10, 11, 12,
and the admin body field `"consoles": false`) restores the PC-only behaviour (stamped
`consoles: false`); the mode is written on the child argv either way, so a run dir always
shows it. `05_submit` gates every entry (shape `targets_v2`, cap 3 targets, per-row
readbacks). Rules: [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) §4.12 (matcher) and
§6 « Modal v2 » (submitter); history (opt-in phase, `--dry-run` guard, canaries):
[`docs/CHANGELOG.md`](docs/CHANGELOG.md) 2026-09-12 → 15.

**Saisir depuis une page console** `[R45]` (Romain 2026-09-15 : « les consoles sont prises
en compte par défaut partout, y compris travailler sur une page de jeu »). L'aperçu par
URLs (`scripts/11_data_entry_by_urls.py`, bouton « Aperçu » → « Saisir ») accepte les
**pages console** AKS (`buy-<slug>-<kind>-compare-prices/`, `kind` ∈ `ps4` / `ps5` /
`xbox-one` / `xbox-series` / `nintendo-switch` / `nintendo-switch-2`) en plus de la page PC.
En bref : `--consoles` est le défaut sur `scripts/11` ET `scripts/12` (`--no-consoles` =
run PC seul, une URL console est alors **refusée** avant tout fetch) ; la recherche du feed
se fait sur l'**identité** de la page (« Hades PS5 » → « Hades ») ; les pages sœurs sont
lues depuis la barre d'onglets de la page épinglée (garde anti-throttle partagée) ; un
candidat est retenu **ssi l'une de ses cibles est la page demandée** et il est gardé
**entier** (une clé cross-gen demandée depuis une page console est écrite sur toutes ses
pages déclarées — jamais scindée, jamais de page sœur ajoutée) ; `scripts/12` transmet les
candidats entiers à `05_submit --mode safe` (modal v2, plafond 3 cibles, preuve =
disparition du feed). Règle complète : [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md)
§14 « Saisie par page » et §4.12. **État : code livré le 2026-09-15, pas encore exercé en
réel** (lecture live d'une page console par `scripts/11` à faire sur le VPS).

```bash
python3 scripts/11_data_entry_by_urls.py --run-id <id> --urls "https://www.allkeyshop.com/blog/buy-hades-ps5-compare-prices/"                # consoles par défaut
python3 scripts/11_data_entry_by_urls.py --run-id <id> --urls "<url>" --no-consoles     # run PC seul (une URL console est refusée)
python3 scripts/12_data_entry_by_urls_submit.py --from-run <id> --run-id <id>-submit    # --consoles / --no-consoles acceptés, informatifs
```

---

```bash
python3 scripts/03_match.py runs/<id>/offers.json                                # read-only, consoles INCLUDED: console rows classified, multi-target candidates
python3 scripts/03_match.py runs/<id>/offers.json --no-consoles                  # read-only, PC only (console rows skipped `console`)
python3 scripts/10_data_entry_auto.py --targets "MMOGA:12" --run-id <id> --dry-run   # read-only preview of a sweep, consoles included
python3 scripts/10_data_entry_auto.py --targets "MMOGA:12" --run-id <id> --no-consoles   # real PC-only sweep (on GO)
```

### Night sweep — every allowlisted merchant

Romain, 2026-09-16: *« donne moi la commande a jour pour lancer tout les marchands whitelist
(scan de nuit) et maintien la dans le readme a chaque whitelist de nouveaux marchands »*.
`--all-allowlisted` READS its targets from `AUTO_MERCHANTS` (`src/admin/auto_merchants.py`),
so **this command never has to be rewritten when a merchant joins the allowlist** — that is
what keeps it up to date. Do not replace it with a hand-written `--targets` list: the
2026-09-15 sweep ran 7 merchants while 11 were allowlisted, exactly that drift.

Read-only preview first:

```bash
python3 scripts/10_data_entry_auto.py --all-allowlisted --run-id <id> --dry-run
```

The real night sweep (WRITES, on Romain's GO — never fire-and-forget, keep it supervised):

```bash
tmux new -s sweep
sudo -u debian -H bash -c 'cd /home/debian/executor && python3 scripts/10_data_entry_auto.py \
  --all-allowlisted \
  --run-id "$(date -u +%Y%m%d-%H%M%S)-auto" \
  --max-pages 10 --continue-on-halt \
  2>&1 | tee "logs/sweep-$(date -u +%Y%m%d)-night.stdout"'
```

**Run it under `tmux`, not `setsid nohup &`** (2026-09-17). The old form here was
fire-and-forget, which AGENTS.md forbids and which this very line contradicted. It also
detaches the run from any supervision. `tmux` keeps it attached to a terminal you can come
back to (`tmux attach -t sweep`, `Ctrl-b d` to detach) and it survives a dropped SSH session
— which is exactly how a GameBoost write lost 62 offers on 2026-09-17: the session timed out
("Timeout, client not responding") and took the attached process with it.

`--max-pages 10` caps each merchant (Kinguin has 67 pages, G2A 38 — a full pass would take
all night); `--continue-on-halt` makes one merchant's fail-closed stop skip to the next
instead of ending the sweep. The recap lands in `runs/<run-id>/recap.json`, one entry per
merchant with `created` and any `halted` reason. Consoles are INCLUDED by default `[R45]`;
add `--no-consoles` for a PC-only pass.

**Allowlist as of 2026-09-16 (14 merchants)** — the command above derives this list itself,
it is reproduced only so a reader knows what a night sweep covers: Kinguin 58, G2A 38,
Driffle 127, Eneba 19, K4G 92, Gamivo 51, Instant Gaming 28, CJS-CDKeys 30, Allyouplay 17,
GameSeal 126, GameBoost 157, Electronicfirst 70, GamersOutlet 31, MMOGA 12. Four of them
(Eneba, CJS-CDKeys, Allyouplay, GameSeal) have never had a real sweep — preview them with
`--dry-run` before the first write pass.

---

## Learning (annotations)

The read-only matcher writes `skipped.json` for every feed offer it did **not**
turn into a candidate, each with its skip reason. The **Learning view** of the
admin page (`Learning — offres non-matchées`) groups those offers by reason and
lets the operator annotate them **per offer**:

- **region / edition** — real ids from the run's live session catalog (never
  hardcoded — catalog ids drift between sessions);
- **platform** — a canonical token (`STEAM`, `PS5`, `PUBLISHER`, …);
- **comment** — why the matcher missed, or any signal for the builder;
- **AKS page** (`aks_url`) — the product page the matcher failed to find;
- **scope** — `exception_offre` / `regle_marchand` / `regle_globale` /
  `observation` (see below);
- **Move to list** — a triage disposition (default *garder* = no action).

Annotations are stored in `runs/<id>/learning.json`, with a `learning_log.jsonl`
audit trail (one JSONL event per save). The save is a **fail-closed merge**:
never a full replace, deletion only via an explicit `cleared` signal, a
`base_sha` precondition (409 on a concurrent write), and every field validated
server-side (target list ∈ catalog, region/edition ∈ the session catalog,
`aks_url` an AKS blog page, each field ≤ 2000 chars).

> **Name collision — read this.** The *Learning view* (annotations, above) is
> **not** the submit `--mode learning` (R24, a canary-of-1 that **writes**, see
> [Manual launch](#manual-launch)). They share a word and nothing else — one
> captures human intent for the builder, the other decides a submit batch size.

**No pipeline stage reads `learning.json` at runtime.** There is deliberately
**no learned-rule engine in the repo** — no runtime LLM, no rule auto-applied to
a run. Generalizing an annotation into pipeline behaviour goes through the
**builder-offline process** (decision D2, 2026-07-22): `learning.json` is the
authority of *human intent*, the **code** is the authority of *execution*. An
annotation becomes exactly one of three things:

1. a **Move to list** → **Stage 6** (the one tooled path, below);
2. an **assisted manual entry** — for an exact offer the matcher couldn't route
   but which has an AKS page, the builder reads the annotated region / edition /
   `aks_url` and constructs the candidate **by hand**, then submits it through
   Stage 5. This path is **deliberately not automated** — it is a one-off
   builder task (typically `scope = exception_offre`), not a tool;
3. a **deterministic matcher rule** — **only** when `scope ∈ {regle_marchand,
   regle_globale}`: the builder codes the rule, unit-tests it, documents it
   (EXECUTOR_RULES / CHANGELOG), adds a numbered `LEARNED_RULE` to the
   `aks-data-entry` skill, and commits it (so it is **revocable by revert**). An
   `exception_offre` or `observation` never becomes a general rule — the `scope`
   is the contract.

See [`docs/LEARNING_PROCESS.md`](docs/LEARNING_PROCESS.md) for the full process
and its guard-rails.

### Stage 6 / Stage 9 — Move to List

`src/mover.py` is the **submitter's sibling**: a writer that moves an offer **out
of its source list** into a target list. Two front-ends drive it, same fail-closed
discipline as the submitter (invariants green + authoritative, one CDP tab under
the browser lock, **dry-run by default**, explicit go, never fire-and-forget).
Success is proven **RV2**: the offer left the source list (proven dual-key, id+URL)
**and** landed on the target list — never from an HTTP 200 / a click.

- **Stage 6 — `scripts/06_move.py`** (learning-driven, per offer): moves a
  non-matched offer into the list the operator annotated. Plan from the run's
  **confirmed** Move-to-list dispositions (`src/move_plan.py`, from
  `learning.json`) — *garder* / still-`suggested` are never in a plan.
- **Stage 9 — `scripts/09_sort_move.py`** (classifier-driven, per target list,
  multi-store): moves every offer the sort classifier routes to a list. `--mode`
  R24 gate: `learning` = supervised canary, `safe` = full list behind
  `--i-authorize-batch` + a canary-granted **sort authorization** (per label,
  cross-store, bound to the scan hash).

The **batched** mechanism (`--batch`, P1→P1.6) registers many offers on one source
page → **one native Apply** → verifies the group at once (`bulk[item][]` is
repeatable) — the ~50-100× speedup, proven in prod (a single 53-item Apply). It is
gated on a **multi-item canary** (`--mode learning --batch --limit 2`, an Apply of
≥2). `--deferred` (P1.6) further defers the source+target verify to **once per
store** (pages highest-first, reflow-safe) — ~G× fewer scans on a big feed, at a
per-store (vs per-group) attribution window. Incremental by default (a resolved
`sort_ledger` skips done URLs; `--full` ignores it). Runs supervised from the
console (`/executor/tri`: **Batché** + **Différé** toggles) or the CLI.

```bash
# Dry-run (default) — plan only, no write:
python3 scripts/09_sort_move.py runs/<id> --list 16

# Multi-item canary (earns the batched authorization), on explicit go:
python3 scripts/09_sort_move.py runs/<id> --list 16 --execute --mode learning --batch --limit 2

# Full batched list (needs the canary-granted authorization):
python3 scripts/09_sort_move.py runs/<id> --list 16 --execute --mode safe --batch --i-authorize-batch

# …with the per-store deferred verify (P1.6, full batch only — no --limit):
python3 scripts/09_sort_move.py runs/<id> --list 16 --execute --mode safe --batch --i-authorize-batch --deferred
```

See [`docs/AKS_LISTS.md`](docs/AKS_LISTS.md) for the list taxonomy and the move
mechanic, and [`docs/CHANGELOG.md`](docs/CHANGELOG.md) (2026-07-28/29) for the
batched P1→P1.6 progression.

---

## The StepGuard

`src/step_guard.py` is the fail-closed backbone every stage runs through. It has
no reasoning — it decides purely from the recorded history of step attempts, so a
block lives in Python state and cannot be reinterpreted by a model.

```python
from src.step_guard import StepGuard

guard = StepGuard(max_attempts_per_signature=2)   # one retry, then stop
guard.start_task("session-2026-07-02")            # id set by the loop, not the model

def submit():
    ...  # perform the action

guard.run_step(
    "submit", "offer=92015031",
    action=submit,
    success_predicate=lambda r: r["gone_from_feed"],  # deterministic success
)
```

Guarantees: the same action can't be hammered (repeated-signature failure blocks
at the 2nd failure); thrashing across actions is capped (consecutive-failure and
per-task budget blocks); a block clears **only** when a genuinely new `task_id`
starts, so a mid-task "retry past it" is impossible.

**StepGuard vs. BlockLedger — what survives a process.** The StepGuard is
**in-memory and per-process**: its block lives in Python state and dies when the
process exits, so simply re-running a script starts from a blank guard. To carry
the skill's anti-loop rule (G03) *across* processes, each write stage also keeps
a **persisted, cross-process `BlockLedger`** in the run directory
(`runs/<id>/guard_ledger.json` for submit, `move_guard_ledger.json` for Stage 6).
It counts a run's consecutive *blocked* passes on disk — one free recovery pass
after a block (the standard idempotent re-pass), a third consecutive blocked pass
needs an explicit `--acknowledge-block`. The in-run StepGuard is always fully
armed either way; the ledger only refuses to *start* a fresh blocked-history run
(FC3, `src/step_guard.py`).

See [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) §2 for how each rule from
the `aks-data-entry` skill maps onto a guard signal.

---

## Rules & docs

**Reading order for a newcomer:** this README (what exists — the
[capability status](#capability-status-2026-09-15)) →
[`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) (the rules in force, per stage) →
[`docs/MERCHANTS.md`](docs/MERCHANTS.md) (how each merchant is read, its status) →
[`docs/HANDOFF.md`](docs/HANDOFF.md) (current state, decisions, gotchas, commands, backlog,
coherence check). The rule text lives in EXECUTOR_RULES only; every other document links
to its section.

- [`docs/NOOB.md`](docs/NOOB.md) — beginner-friendly guide: what the project
  is, why it exists, and how the pipeline works, explained with analogies (French).
- [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) — the deterministic,
  per-stage specification derived from the `aks-data-entry` skill. The bridge
  from domain rules to code (extractor, matcher, submitter, post-save
  verification, reporting).
- [`docs/LEARNING_PROCESS.md`](docs/LEARNING_PROCESS.md) — how a Learning
  annotation becomes pipeline behaviour: the builder-offline process (decision
  D2) — a move, an assisted manual entry, or a tested/documented/committed
  matcher rule; never a rule auto-applied at runtime, no rule engine in the repo.
- [`docs/AKS_LISTS.md`](docs/AKS_LISTS.md) — Stage 6 Move-to-List: the
  merchant-feed list taxonomy and the deterministic (read-only-captured) move
  mechanic.
- [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md) — session re-auth by cookie
  transfer (password+2FA Stage 0b retired): operator social-login, paste WP
  cookies into `/executor/tri` → Se reconnecter; values never logged/stored.
- [`docs/INVARIANTS.md`](docs/INVARIANTS.md) — the non-negotiable browser/network
  invariants.
- [`docs/AUDIT_2026-07-17.md`](docs/AUDIT_2026-07-17.md) — the audit register:
  findings from the 2026-07-17 multi-agent audit, each tracked `OPEN` → `FIXED`
  with date and commit. Complements [`docs/AUDIT.md`](docs/AUDIT.md) (Sprint 1
  audit, 2026-07-02, fully resolved). The **2026-09-02** multi-agent audit
  (P1 + P2 fixes) is logged in [`docs/CHANGELOG.md`](docs/CHANGELOG.md), with the
  per-stage rules in [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md).
- [`docs/MERCHANTS.md`](docs/MERCHANTS.md) — one section per merchant: store ids, its
  file (`src/merchants/<name>.py` — one per allowlisted merchant, Romain's rule of
  2026-09-14), PC grammar (platform / region / edition sources), console grammar
  (families, PC/Windows, region slot), merchant-config hooks (R32 / R45), merchant-specific
  rules, safe-auto status, residual feed profile; the live feed state is in
  `docs/feeds/<Merchant>.md`.
- [`docs/HANDOFF.md`](docs/HANDOFF.md) — resume point (state, reviewed decisions,
  gotchas, frequent commands, backlog, coherence check).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the pieces fit (pipeline table,
  module layering, the single CDP tab, the validation triple, the admin page).
- [`docs/SUBMITTER_SPEC.md`](docs/SUBMITTER_SPEC.md) — the write stage as built: trusted
  Selectize picks, modal v2 targets per row (§4c), statuses.
- [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) — stage I/O JSON shapes + run-log
  format.
- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — developer guide (setup, tests, StepGuard
  use, adding a stage or a merchant rule, commit rules).
- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — builder rules for Codex
  and Claude, including the « Reviewed decisions » an audit must not re-flag.

---

## Roadmap

- [x] **Sprint 1 — read-only foundations:** invariant checks (run through the
  StepGuard), read-only CDP `/json/version` client, deterministic StepGuard,
  environment-aware audit, unit tests, and CI. Audited; all P1 + P2 findings
  remediated (see [`docs/AUDIT.md`](docs/AUDIT.md) / [`docs/CHANGELOG.md`](docs/CHANGELOG.md)).
- [x] **Sprint 2 — read-only feed extractor** — built (`src/extractor.py`,
  `src/cdp_session.py`, `scripts/02_extract_feed.py`): navigates the merchant feed
  read-only via CDP, paginates (`&p=N`), dedupes, emits RawSnapshot +
  NormalizedFeed; gated at runtime on green + authoritative invariants. Pure core
  unit-tested; **first live run happens on the VPS**.
- [x] **Sprint 3 — read-only matcher** (`src/matcher.py`, `scripts/03_match.py`):
  strict name match (R01/R01b), SKIP lists, region-from-URL, edition detection,
  AKS slug resolve (`data-product-id` + editions), a default **100-candidate cap**
  (`match_feed(max_candidates=100)`, override with `03_match --max-candidates`),
  normalized-text report. The cap mirrors the one-page-at-a-time cadence — a feed
  page is ~100 offers (EXECUTOR_RULES §4.8/§11), so one page's worth is the
  natural ceiling and a guard-rail against an over-broad match flooding a batch.
  Pure core unit-tested; live AKS resolve runs on the VPS.
- [x] **Validation** (`src/validation.py`, `scripts/04_validate.py`) — fail-closed
  gate: approve exact candidates by fingerprint; no submission without it.
- [x] **Submitter — built & live-proven** (`src/submitter.py`,
  `src/submit_session.py`, `scripts/05_submit.py`): dry-run rehearsal + real write
  path. Real `--submit` (default `--click-mode trusted`) makes **trusted** Selectize
  picks for region/edition, fills `offer[targets][]` with the `aks_product_id`,
  passes a hard **HTML5 validity gate**, clicks "Create offer" with a trusted CDP
  event, and verifies post-save (`success = offer gone from the refreshed feed, same available mode`, never
  `[data-success]`). **First real AKS offers created 2026-07-06** (Demigod canary +
  3 batch). Batch size is the data-entry **`--mode`**'s call (`safe` = full
  validated batch, no canary; `learning`/`advanced` = canary of 1) `[R24]`; gated +
  StepGuard (skip+continue, stop after 10). See
  [`docs/SUBMITTER_SPEC.md`](docs/SUBMITTER_SPEC.md) §4b.
- [x] **Data contracts + JSONL run-log infrastructure** (`src/contracts.py`,
  `src/run_log.py`) — ready for the stages above to use.
- [x] **Post-save verifier** — implemented inside the submitter (`_verify_gone`):
  after every click, the whole refreshed feed is re-scanned; `success = offer no
  longer present` (never `[data-success]`). Since 2026-07-07 the same scan also
  refreshes the batch row index (pagination reflow).
- [x] **Session re-auth — cookie transfer** (`src/admin/login_manager.py`,
  `src/login_session.py`, 2026-07-29): AKS is social-login only, so the old
  password+2FA Stage 0b (`scripts/00b_login.py`) was retired. The operator
  completes social login in their own browser, pastes the WP session cookies
  into `/executor/tri` → 🔑 Se reconnecter; the server injects them (official
  CDP only) and proves the session with `verify_dashboard`. Explicit go only,
  never self-triggered by a `NotLoggedInError`. Cookie VALUES are never
  logged/echoed/stored. See [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md).
- [x] **Admin operator page** (`src/admin/`, `scripts/07_admin_server.py`,
  `ops/`) — live on the VPS at `/executor/`: loopback-only stdlib HTTP app
  behind nginx HTTPS + basic auth, systemd-supervised (`aks-admin.service`).
  Serves the normalized report, lets the operator approve/reject/override
  candidates (validation triple regenerated server-side), and launches
  supervised extract/dry-run/submit runs — never fire-and-forget. See
  [`ops/INSTALL_ADMIN.md`](ops/INSTALL_ADMIN.md).
- [x] **Learning (annotations)** (`src/admin/learning_io.py`, `src/aks_lists.py`,
  Learning view in the admin page, 2026-07-21) — for a matched run, the
  non-matched offers (`skipped.json`) grouped by reason and annotated per offer
  (region/edition ids, platform, comment, AKS page, scope, Move-to-list
  disposition) into `runs/<id>/learning.json`. **Capture only** — no pipeline
  stage reads it at runtime; generalization runs through the builder-offline
  process (D2, 2026-07-22). See
  [`docs/LEARNING_PROCESS.md`](docs/LEARNING_PROCESS.md).
- [x] **Stage 6 — Move-to-List writer — unit canary only; batch is open**
  (`src/mover.py`, `src/move_plan.py`, `scripts/06_move.py`, 2026-07-21) — the
  submitter's sibling: moves a non-matched offer out of its source list into the
  annotated target list; plan built from the confirmed `learning.json`
  dispositions. Dry-run by default (`--execute` writes), canary-of-1 on a real
  move (`--mode learning`), explicit go, never fire-and-forget; success = the
  offer left the source list. **First unit canary succeeded 2026-07-22** (IObit
  Advanced SystemCare, G2A run, list 9 → Softwares 16). The **batch path
  (`--execute --mode safe`) stays blocked** — a successful unit canary does not
  unlock it (see the open item below). See [`docs/AKS_LISTS.md`](docs/AKS_LISTS.md).
- [x] **Move-to-List batch — behind a double gate** (2026-07-22). Both
  conditions are built (`docs/REVIEW_2026-07-22.md` RV2/RV3): a move now proves
  the offer is **gone from the source AND present on the target list** (RV2,
  `mover._verify_on_target`; a target that can't be fully scanned → UNKNOWN,
  fail-closed), and a verified unit canary **grants a scoped, versioned
  authorization** (`src/move_auth.py`: mover version × store × source × target
  lists × extraction hash). `--execute --mode safe` now requires **both** the
  explicit `--i-authorize-batch` flag **and** an authorization covering the plan;
  either missing → refused. A canary (`--mode learning`) stays the only way to
  validate a new target list / fresh data before a batch can cover it. Validated
  live 2026-07-22 (unit canary AWZ PC Cleaner → Softwares, gone+present proven).
- [x] **Runtime hardening** (`src/browser_lock.py`, `src/pacing.py`) —
  advisory `flock` on `state/browser.lock` so only one process drives the
  single CDP tab at a time (fail-closed: busy lock = refuse to start; OP1,
  audit 2026-07-17), and bounded-random pacing (`--pace MIN-MAX`) between page
  loads/submissions with counters recorded in the run log.
- [x] **Stage 9 — sort-move + batched mechanism (P1→P1.6)** (`src/sort_move.py`,
  `src/move_auth.py`, `src/sort_ledger.py`, `scripts/09_sort_move.py`,
  2026-07-23→29) — moves every offer the sort classifier routes to a target list,
  per list, across stores. The **batched** path (`--batch`) registers many offers
  on one source page → one native Apply → group-verified RV2 (P1), one target scan
  per group (P1.5), gated on a **multi-item canary** authorization (P2). **P1.6
  `--deferred`** defers the source+target verify to once per store (pages
  highest-first, reflow-safe) — ~G× fewer scans on a big feed, at a per-store
  attribution window. Incremental (`sort_ledger`; only terminal outcomes —
  moved / gone / true identity contradiction — are skipped, transient misses
  retry). Bounded retry on a transient feed/CDP blip. **Proven in prod
  2026-07-29** (a single 53-item Apply moved a page at once). Console toggles
  **Batché** / **Différé** on `/executor/tri`. See
  [`docs/CHANGELOG.md`](docs/CHANGELOG.md) (2026-07-28/29).
- [x] **Console keys `[R45]` — live, ON by default** (`src/console_keys.py`, matcher
  `targets`, submitter v2, 2026-09-12 → 15; was "parked" on 2026-09-11). Console product
  pages found (`buy-<slug>-<kind>-compare-prices/`), title + URL classifier (shared
  vocabulary in `console_keys` + the console hooks of each merchant file, 2026-09-14),
  one verified AKS page / bucket / edition per declared platform, Play Anywhere read from
  the PC page. The 2026-09-12 adversarial
  review is fixed (2026-09-14: region slot of each grammar, R44 on consoles, identity
  apostrophes, gate ≠ failure, shared throttle guard…), P1 is decided (declared platforms
  only) and Switch 2 is the `SWITCH2` family. The per-target modal v2 was observed
  (`--inspect`, 2026-09-14) and proven by two canaries (2026-09-15: one target, then two
  via `[data-add-target]`); the "`--consoles` requires `--dry-run`" guard was lifted the
  same day, and Romain's decision « 1 » made **consoles the default everywhere**
  (`--no-consoles` / `"consoles": false` to opt out; MMOGA dry-run: 174 console
  candidates); entry from a **console page URL** (`scripts/11` / `12`, EXECUTOR_RULES §14)
  landed the same day — not yet exercised live. Policies
  P2-P5 to confirm with Romain; Riders Republic
  (Gamivo Xbox key entered as PC on 2026-09-11) to correct by hand, like the five Gamivo
  US Steam keys entered Publisher GLOBAL the same day (`[R46]`, `docs/MERCHANTS.md`). See
  [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) §4.12.
- [x] **Contrat des candidats** (`src/candidate_contract.py`, Lot 2 2026-09-15) — l'identité
  d'un candidat (cibles normalisées + empreinte de validation) définie une seule fois ;
  matcher, validation, submitter, `validation_io` et le port `app.js` la lisent, vérifiés
  contre `tests/fixtures/candidate_contract_examples.json` (Python + node en CI).

---

## Safety

- Never commit `runs/`, `logs/`, `state/`, `.env`, cookies, or 2FA codes.
- Submission happens **only** through the AKS feed UI modal — never a direct
  `admin-ajax` XHR (the modal auto-assigns the merchant id).
- `[data-success]` is never proof of creation. An offer is "created" only after
  it disappears from the refreshed feed (same available mode as the run).
- If a write stops in **UNKNOWN** state (feed/CDP unreadable mid-run — the offer
  may or may not have been written), verify the real state **by hand on AKS
  before any retry**; never replay blindly (a blind retry can double-create).
  Runbook: [`ops/BROWSER_RUNBOOK.md`](ops/BROWSER_RUNBOOK.md) §2.5.
- Session re-auth is **cookie transfer** only (`docs/LOGIN_SPEC.md`): never
  self-triggered; cookie VALUES never logged/stored; a `NotLoggedInError` from
  any other stage is a fail-closed STOP + error report — wait for Romain's
  explicit go on `/executor/tri` → Se reconnecter.
