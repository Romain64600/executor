# AKS Controlled Executor — Architecture

A map of the system as it runs today. The per-stage behavioural rules live in
`docs/EXECUTOR_RULES.md` (the authoritative bridge from the `aks-data-entry`
skill to this code); this file describes how the pieces fit together.
Rewritten 2026-07-17 (audit DO2: the previous version predated Stage 0b and
the admin page, and still attributed the validation UI to a hypothetical N8N).

## Roles

- **Builders (Codex CLI, Claude Code)** — write code, tests, docs, read-only
  diagnostics. Never free-form AKS browser actions (`AGENTS.md`, `CLAUDE.md`).
- **Executor** — the deterministic pipeline below. No improvisation, dry-run
  by default, submission only from a validation file.
- **Operator (Romain / parallel operators)** — validates candidates and gives
  the explicit go, either via the CLI scripts or via the admin page at
  `/executor/`. The "validation UI" once penciled in for a future N8N is this
  admin page; there is no N8N and no orchestration layer.

## Pipeline

Stage numbers follow `EXECUTOR_RULES.md`; script numbers are historical and
offset by one (02 = Stage 1, …). Every artifact lands in `runs/<run_id>/`,
every event in the append-only `logs/<run_id>.jsonl`.

| Stage | Script | What it does | Artifacts |
|---|---|---|---|
| gate | `scripts/01_check_invariants.py` | Read-only invariant report (AKS reachable, no OpenVPN, official CDP endpoint + UA), `authoritative` flag | JSON on stdout |
| 0b login | `scripts/00b_login.py` | WP-admin login + 2FA in the CDP tab. Explicit go only, one attempt each for password and code, credentials from env only, 2FA asked only once the field is visible | log only |
| 1 extract | `scripts/02_extract_feed.py` | Read-only feed walk over CDP; repeated full sweeps until one adds zero new ids (coverage proof); blank in-range pages retried once then classified or aborted (`EmptyPageAnomaly`, seen live 2026-07-07) | `raw.json`, `offers.json` |
| 2 match | `scripts/03_match.py` | Pure rules + read-only AKS GETs: skip tables, platform/region/edition detection, slug guessing + R30 site-search fallback, R01/R01b name checks. Doubt → skip | `candidates.json`, `skipped.json`, `report.txt`, `match_meta.json` |
| 3 validate | `scripts/04_validate.py` | `template` writes the fill-in file; `check` verifies it against the current candidates and writes `approved.json` — the only writer of that file, CLI and admin flows alike | `validation.template.json`, `validation.json`, `approved.json` |
| 4 submit | `scripts/05_submit.py` | Default dry-run; `--catalog` / `--inspect` / `--submit` modes. Real writes fill region/edition/targets and click the visible "Create offer" via a trusted CDP click | `submit_plan.json`, `submit_report.txt`, `session_catalog.json`, `guard_ledger.json` |
| 5 post-save verify | inside `src/submitter.py` | Success = the offer disappeared from the refreshed feed, same `available` mode as the run — never `[data-success]` | part of `submit_plan.json` |

### The invariant gate (FC2)

Every browser-driving stage refuses to start unless
`build_report()` (`src/invariants.py`) is **green AND authoritative**.
`authoritative` is true only on the Debian VPS target: Linux plus the
root-installed marker `/etc/aks-executor.target` — root-owned, not
group/world-writable, content equal to this machine's hostname
(`src/aks_env.py:marker_authorizes`). The old `AKS_TARGET=vps` env-var force
was removed (FC2, audit 2026-07-17): the env var can only force
*non*-authoritative (`dev`/`sandbox`/`local`), never on. A red result with
`authoritative:false` (macOS, CI sandbox) is not a production failure and
never unlocks write stages.

### Data-entry modes (R24) and the mode binding (FC5)

`--mode safe` (default) submits the **full validated batch**; `learning` /
`advanced` do write but are capped at a **canary of 1** (`--limit` may narrow
a canary, never widen it — refused, not clamped). Since FC5 (audit
2026-07-17), `03_match --mode` stamps the mode into `match_meta.json`, and
both `05_submit.py` and the admin's `SubmitManager` refuse a real submit whose
declared mode is *wider* than the matched one (`mode_widens_match`): a run
matched under a canary unlock can never take the full-batch `safe` path.
Absent meta = pre-FC5 legacy run, accepted.

## Module layering

Foundation (no browser, no state):

- `src/contracts.py` — dataclass contracts for stage I/O (`RawSnapshot`,
  `NormalizedFeed`, `NormalizedOffer`); malformed input raises
  `ContractError`, never a silent pass.
- `src/aks_env.py` — invariant checks, environment classification
  (`marker_authorizes`, `current_environment`), read-only HTTP probes; the
  `AKS/Staff` UA is refused for any non-allkeyshop.com host (audit #4,
  2026-07-08).
- `src/invariants.py` — assembles the gate report, probes run through a
  StepGuard.
- `src/cdp_client.py` — Sprint-1 relic: HTTP `/json/version` metadata checks
  only, still used by the gate.

Cross-cutting:

- `src/step_guard.py` — **StepGuard**: the deterministic fail-closed backbone.
  `check()` before every step, `record_result()` after, with `success`
  computed by deterministic code (HTTP status, error-field presence), never a
  model self-assessment. Blocks on repeated-signature failure, consecutive
  failures, or the failure budget; a block clears only when a genuinely *new*
  task starts. **BlockLedger** (FC3, audit 2026-07-17) extends G03 across
  processes: state in `runs/<id>/guard_ledger.json`, one free recovery pass
  after a blocked run, two consecutive blocked passes require an explicit
  `--acknowledge-block` on the third.
- `src/run_log.py` — append-only JSONL logger; secret-named keys
  (`password`, `otp`, `token`, `webSocketDebuggerUrl`, cookies, …) are
  redacted before serialization.
- `src/pacing.py` — bounded-random delays between page loads / offers (burst
  mitigation). Never a correctness mechanism; counters logged.
- `src/browser_lock.py` — cross-process advisory `flock` on
  `state/browser.lock` (OP1, audit 2026-07-17): the CDP architecture drives
  ONE tab, and both the CLI scripts and the admin's spawned children navigate
  it. Every stage that opens a CDP session takes the lock non-blocking; busy
  = refuse to start (exit 2), never queue, never share the tab. The kernel
  releases it when the holder dies.

Stage logic:

- `src/extractor.py` — `FeedExtractor`: sweep-until-stable coverage proof,
  page-state markers (`feed_ui`, `nav_max`, `is_login`), blank-page
  retry-once-then-classify discipline, `extract_pages` slice mode (always
  reported partial).
- `src/matcher.py` — the rule pile (classification tables, `REGION_IDS`,
  `EDITION_HINTS`, R01…R30). Pure except `resolve_aks`, whose HTTP client is
  injectable. Every past live escape has a numbered rule and a regression
  test.
- `src/validation.py` — fingerprints and the triple verification (see below).
- `src/submitter.py` — `_SubmitterBase` (feed scan/index, row location under
  dual identity, modal prep) with `DryRunSubmitter`, `InspectSubmitter` and
  `Submitter` (the only writer) on top; `fetch_session_catalog`.
- `src/submit_session.py` — the CDP session split (see next section) plus all
  embedded page-probe JS.
- `src/login_session.py` — `LoginSession` + `run_login`: Stage 0b, reusing
  the already-audited trusted-input primitives; one attempt each, never a
  retry loop, credentials never in a log record.

Scripts under `scripts/` are thin CLIs: argument parsing, the invariant gate,
the browser lock, artifact writing. The logic lives in `src/` and is
unit-tested with fake sessions (`python3 -m unittest discover -s tests`; the
whole suite is hermetic — no browser, no network).

## The single browser tab (CDP)

One headless Chromium runs on the VPS under systemd (`aks-chromium.service`,
CDP on `127.0.0.1:9222`; the package is apt-held at 149 because Debian's 150
build SIGTRAPs under this headless/CDP setup — the pinned Chrome/149 UA must
match the running major as a consequence). A socat
relay exposes it on the Docker bridge as `172.17.0.1:9223` — the **official
endpoint** (`OFFICIAL_CDP_ENDPOINT`); nothing else is ever probed.

- `src/cdp_session.py` — `ReadOnlyCdpSession`: raw-WebSocket CDP client,
  stdlib only, no Origin header on the handshake (avoids Chrome's 403 from
  the Docker terminal). It exposes only `navigate` and `evaluate_readonly`,
  refusing expressions containing mutation tokens (`.click(`, `fetch(`, …) —
  a footgun-preventer, not a security boundary. Since the 2026-07-17 audit
  the transport is loud: timeouts, protocol errors, `Page.navigate`
  `errorText` and any broken-stream state raise `CdpCommandError` instead of
  degrading into silent `None`s (SC1/SC6/SC8), and tab selection only
  considers http(s) targets, preferring the one already on allkeyshop.com
  (SC7). There is deliberately no mid-run reconnect: a dead socket aborts the
  run fail-closed.
- `src/submit_session.py` — two classes, one strict boundary.
  `SubmitSession` (dry-run) adds read + open-modal + read-only probes and has
  **no method that fills a form or clicks "Create offer"**.
  `WriteSubmitSession` adds the single mutating flow — fill region/edition/
  targets, trusted CDP click on the visible Create button (`isTrusted:true`,
  the only mode proven to fire Driffle's handler — Chantier n°1,
  2026-07-03). No `form.submit()`, no direct XHR (S09).
  `scripts/05_submit.py` instantiates the write class only under `--submit`.
- `LoginSession` extends `WriteSubmitSession` to point the same trusted-input
  primitives at the WP login form (Option A, 2026-07-14).

## Fail-closed philosophy

If anything is uncertain: stop, write an error report, never fall back.
Concretely:

- `success` always comes from deterministic code; the sole success proof for
  a write is **post-save disappearance**: the offer absent from the refreshed
  feed under BOTH identities — row id and merchant-URL path (`_url_key`),
  because re-imports rotate every id (K4G 2026-07-08: 0/212 ids survived
  74 minutes) while the URL path is stable.
- The disappearance proof requires a **positively complete scan** (audit
  2026-07-17, FC1/SC2/SC4/FC6): `_read_feed_page` retries a blank render once
  and only returns empty rows as a *proven* end-of-feed (feed UI rendered and
  the pagination nav agrees); a login bounce raises `NotLoggedInError`; a
  browser URL that does not match the navigated page raises `FeedScanError`;
  exhausting `max_pages` while the nav advertises more pages raises instead
  of silently truncating. Success is never inferred from absence of data.
- Mid-batch, any `FEED_UNREADABLE_EXCS` marks the current offer's state
  **UNKNOWN** (Create may already have been clicked), records it for a manual
  check, and stops the run (`stopped="feed_unreadable"`).
- The write path re-resolves region/edition ids against the live session
  catalog fetched once per run (ids drift as AKS adds entries; the matcher's
  hardcoded ids are not authoritative); an unresolvable label blocks the
  offer — forcing a pick is what created the 2026-07-06 wrong-edition offers.
- One attempt per offer, run stopped after 10 consecutive failures
  (SUBMITTER_SPEC §6), all through the StepGuard.

## The validation triple

No submission without a validation file approving the EXACT current
candidates. A candidate's identity is its fingerprint
`offer_id|aks_product_id|region_id|edition_id`, so any re-match that changes a
pick invalidates a stale approval (S15).

- `candidates.json` + `validation.json` + `approved.json` are **one unit**:
  `verify_approved_against_source` (`src/validation.py`) re-derives the
  approval from the first two and requires `approved.json` to match exactly.
  A fabricated, hand-edited or stale file refuses to load.
- That re-derivation runs at submit time in two independent places: inside
  `scripts/05_submit.py` (every mode that consumes `approved.json`) and in
  the admin's `SubmitManager._verify_triple` before any spawn (P1a audit,
  2026-07-08).
- The admin page never patches one file alone: every save regenerates the
  whole triple, `approved.json` being written by the real
  `04_validate.py check` subprocess, exactly as in the manual flow
  (`src/admin/validation_io.py`).
- The client-visible `candidates_sha256` guards validation saves against a
  concurrently changed candidate set (`stale_candidates`), and — AS1, audit
  2026-07-17 — a real submit must echo the `approved_sha256` captured when
  the GO dialog was shown: a concurrent regeneration of the triple yields a
  409 `approved_changed` instead of silently submitting a different batch.

## The admin operator page

`scripts/07_admin_server.py` serves the page from loopback `:8650`
(non-loopback bind refused without `--allow-external`); nginx terminates TLS
and enforces basic auth in front, proxying `/executor/`
(`ops/nginx-executor.conf`). It runs under systemd as
`aks-admin.service`: default cgroup kill mode means restarting the service
also kills an in-flight submit child — supervision is never silently lost.

- `src/admin/app.py` — HTTP layer only: routing, custom-header CSRF guard on
  every POST (`X-AKS-Admin: 1` + JSON content-type + Origin/Host check, no
  CORS), full body drain before any response (AS3), security headers, JSON
  error model.
- `src/admin/runs.py` — the only filesystem access path: `safe_run_dir`
  (anti-traversal) and the `RUN_FILES` whitelist of per-run artifacts; no
  generic file service.
- `src/admin/validation_io.py` — operator decisions
  (approve/override/delete) to a consistent triple. Region/edition overrides
  must come from the run's own `session_catalog.json` (no free-text ids); the
  matcher's original pick is frozen in an `operator_override` audit field and
  every change/deletion is logged to the JSONL.
- `src/admin/submit_manager.py` — supervised, one-at-a-time spawns of the
  unmodified stage scripts (extract, catalog, dry-run, submit — never
  fire-and-forget): a supervisor thread waits for the exit code and persists
  the outcome to `runs/<id>/admin_submit.json`; a bookkeeping failure after
  `Popen` kills the child before propagating (AS2); orphaned "running" state
  files are reconciled at startup. It re-enforces the mode/canary caps, the
  triple, the AS1 sha binding, the FC5 mode binding, and refuses re-approving
  an offer already created (`already_created` — creations are derived from
  the JSONL `submit_offer` events and sticky).
- `src/admin/static/` — vanilla JS (`app.js`), relative URLs, all dynamic
  content through `textContent` (never `innerHTML` with data), CSRF header on
  every POST.

The admin needs no browser lock of its own: it spawns the same scripts, so
its children inherit the `flock` protection.

## Run state on disk

- `runs/<id>/` — all stage artifacts (see the pipeline table) plus
  `guard_ledger.json` and `admin_submit.json`.
- `logs/<run_id>.jsonl` — the immutable, redacted event log; also the source
  of truth for per-offer submit history in the admin UI.
- `state/browser.lock` — the cross-process tab lock.

None of `runs/`, `logs/`, `state/`, `.env` is ever committed.
