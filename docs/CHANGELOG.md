# Changelog — AKS Controlled Executor

Notable changes, newest first. Dates are UTC. Complements [`AUDIT.md`](AUDIT.md)
(findings) and the roadmap in [`../README.md`](../README.md).

## 2026-07-03 — S18 investigation: network taps + dispatch click mode (derogation)

Live canary #2 (Driffle) eliminated hypothesis #1: the selectize readback proved
`setValue` took perfectly (`region_set=9`, `edition_set=1`, options exact) — yet
`[data-success]` appeared with an **empty** signal text and the offer stayed in
pending. Prime suspect: a pre-existing (template/hidden) `[data-success]` node
being mistaken for the AJAX ack, and/or the native `.click()` not firing Driffle's
real submit handler. **144 tests green.**

- `src/submit_session.py` — `_FILL_CREATE_JS` instrumented:
  - **pre-existing signal guard**: `[data-success]`/`[data-error]` nodes are counted
    BEFORE the click; the poll only accepts a **new** node (count increased) —
    otherwise it ends `NO_SIGNAL`. `polls` + `pre_existing` land in the diag.
  - **network taps** (diagnostic only): `window.fetch` + `XMLHttpRequest` are wrapped
    around the click and restored after; the diag reports `via/method/url/status`
    for every request the click fired — never bodies, never headers/cookies. An
    empty `requests` list = the click never reached the network.
  - **button state** (`disabled`/`visible`/`text`) recorded pre-click.
  - **`click_mode='dispatch'`** — full `mousedown/mouseup/click` MouseEvent sequence
    **on the Create button ONLY**. This is an explicit, documented derogation from
    the S09 no-`dispatchEvent` rule, **authorized by Romain (2026-07-03, authority
    order #1)** after the native click was proven not to persist on Driffle. Still
    no `form.submit()`, no XHR submission; unknown modes raise (fail-closed).
- `src/submitter.py` — `Submitter(click_mode=...)` passes the mode through; the
  post-save feed check remains the ONLY success proof, unchanged, in both modes.
- `scripts/05_submit.py` — `--click-mode {native,dispatch}` (native default,
  refused without `--submit`); the text report now prints polls / pre_existing /
  button state and one `net:` line per captured request.
- +4 tests (dispatch pass-through, dispatch still fails when still-pending, native
  default, unknown mode refused).

Also today (infra, no code): AKS dropped the VPS IP at TCP level (curl `000`,
google OK, DNS OK, AKS up from elsewhere) — the documented skill pattern "AKS
bloque les IPs après un burst". Resolved by Romain via the skill's Surfshark
targeted-route rotation (`de-fra` TCP, `--route-nopull --route 176.31.53.220`);
invariants back green+authoritative. Known doc drift to resolve: `00_audit_env.sh`
still FAILs when an openvpn process runs — decision pending on wording it as
"forbidden when direct works / tolerated targeted-route when AKS drops the IP".

## 2026-07-02 — Stage 4: real submitter (WRITES, canary-first)

The real write path — approved by Romain, and validated end-to-end in **dry-run on
the VPS first** (modals open; Driffle selects are `offer[region]`/`offer[edition]`;
Battle.net Gift region resolves to 570). **138 tests green.**

- `src/submit_session.py` — `WriteSubmitSession(SubmitSession)` adds the ONE mutating
  op, `fill_and_create`: `selectize.setValue` on the verified select names, then
  click `#TB_ajaxContent .button-primary` (Promise + 500 ms; skill S09/S17/S19). No
  XHR, no `dispatchEvent`, no `form.submit()`.
- `src/submitter.py` — `Submitter` (real): `fill_and_create`, then **post-save
  verification** — re-scan the feed; `success = the offer disappeared from pending`
  (never `[data-success]`; skill S18). Shares its base flow with the dry-run.
- `scripts/05_submit.py` — `--submit` writes; **canary default = 1 offer**, `--all`
  for the full batch, `--limit N` otherwise. Gated on green + authoritative invariants
  + pre-flight login; one attempt per offer, skip + continue, stop after 10 consecutive.
- 5 tests (canary stops after 1, full batch, still-present = failure, unconfirmed
  click = failure, not-ready never writes).

First real run (canary):
`python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit`

## 2026-07-02 — Stage 4: submitter (DRY-RUN only, no writes)

The submit flow, dry-run only — **no writes**. **132 tests green.** Approach
approved by Romain (`docs/SUBMITTER_SPEC.md`).

- `src/submit_session.py` — `SubmitSession` (extends the read-only CDP session):
  list a page's offer ids, open an offer's modal, read the modal context, detect the
  WP login page. **No method fills a form or clicks "Create offer"** — the create
  capability does not exist in this build.
- `src/submitter.py` — `DryRunSubmitter`: pre-flight login check, locate the exact
  current row, open the modal, verify context + select names, report what it *would*
  submit. Per Romain's decisions: one attempt per offer; on failure log + skip +
  continue; stop the run after **10 consecutive** failures (StepGuard).
- `scripts/05_submit.py` — `--dry-run` (default), gated on green + authoritative
  invariants; `--submit` is **refused** (write path not built). Writes
  `submit_plan.json` + `submit_report.txt`.
- 7 tests (login abort, ready plan, skips, select-name conventions, stop-after-10).

Run on the VPS: `python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127`.

## 2026-07-02 — Stage 3: validation gate

Read-only validation — the fail-closed gate before any submission. **125 tests green.**

- `src/validation.py` — `validation_template` (operator fills approve + who/when)
  and `load_validation`, which verifies a filled file against the CURRENT
  candidates: `run_id` must match, `validated_by`/`validated_at` required, and every
  approved entry must be an exact current candidate by fingerprint
  (`offer_id|aks_product_id|region_id|edition_id`) — a re-match that changes a
  region/edition invalidates a stale approval (skill S15). Any problem rejects the
  whole file (never partially honored).
- `scripts/04_validate.py` — `template` writes `validation.template.json`; `check`
  verifies a filled `validation.json` and writes `approved.json`. Read-only.
- 9 tests. This approval is the lock the future submitter will require — no
  submission is possible without it.

## 2026-07-02 — Sprint 3: read-only matcher

The matcher stage is built (read-only). **Suite: 109 tests green.**

- `src/matcher.py` — ports EXECUTOR_RULES §4: apostrophe-normalized tokenizer,
  R01 strict name match, R01b dangerous-qualifier guard, categorical SKIP lists
  (console, forbidden region, currency/gift/sub, DLC, bundle, language
  restriction), platform + region (URL-first) + edition detection, AKS slug build
  + read-only resolve (`data-product-id` + editions), cap 100. `Candidate` +
  `SkippedOffer` dataclasses; `normalized_block` emits the skill's exact report
  format (`#N — … / 🎯 id — name / 🔗 url / 🎯 aks-url / Platform REGION(id), Edition(id)`).
- `scripts/03_match.py` — reads `offers.json`, resolves candidates against AKS
  (read-only GET), writes `candidates.json` + `skipped.json` + a normalized-text
  `report.txt` (no tables). Aborts if AKS is unreachable.
- 33 tests. Forbidden-region short tokens (NA/OTHER/SEA) excluded to avoid title
  collisions ("Sea of Thieves"); candidates are human-reviewed before any submit.
- Hardened from the first live Driffle run (272 → 5 candidates): added the
  different/expanded-product guard (≥2 extra significant words, or an extra version
  number → SKIP — e.g. GreedFall "The Dying World" ≠ base GreedFall) and Gift
  region detection (Steam 25/259, Battle.net 570/567). Re-validated: 5 → 3 clean
  candidates.

Run on the VPS: `python3 scripts/03_match.py runs/<run_id>/offers.json`.

## 2026-07-02 — Sprint 2: read-only feed extractor

The extractor stage is built (still strictly read-only). **Suite: 83 tests green.**
Unblocked by the VPS invariant gate going green + authoritative.

- `src/cdp_session.py` — stdlib raw-socket CDP session adapted from the skill's
  proven transport (no Origin header → avoids the Docker-terminal 403). Exposes
  only `navigate` + `evaluate_readonly`; refuses mutation-looking expressions
  (`.click(`, `dispatchEvent`, `setValue`, `admin-ajax`, `fetch(`…). Never clicks,
  fills, or submits. Zero new dependencies.
- `src/extractor.py` — `feed_url` (pagination `&p=N`), `parse_offers_payload`
  (`html.unescape` + `json.loads`, skill rule F05), paginated extraction through
  the StepGuard, dedupe-by-id → `RawSnapshot` + `NormalizedFeed`, logged via
  `RunLogger`.
- `scripts/02_extract_feed.py` — CLI that **refuses to run unless invariants are
  green AND authoritative**, then writes `runs/<run_id>/raw.json` + `offers.json`.
- 11 tests (feed URL, payload/entities, pagination/dedupe/stop rules, guard
  wiring, read-only refusal). The live CDP path runs on the VPS.

Run on the VPS: `python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127`.

## 2026-07-02 — P2 debt cleanup

Closed the P2 findings from `AUDIT.md`. **Suite: 72 tests green.**

- **C4 — StepGuard limits decoupled.** A new `max_failures_per_signature`
  (hard-block threshold) is distinct from `max_attempts_per_signature` (the
  pre-execution attempt ceiling); the success-then-failure asymmetry is now
  explicit and tested.
- **C5 — one blocked-decision builder.** `check()` and `run_step` both use
  `_blocked_decision(signature)`, preserving the real signature.
- **C6 — CDP client fails closed without probing** a non-official endpoint (no
  network I/O when the endpoint check fails).
- **S3 — audit config excerpt whitelisted.** `00_audit_env.sh` greps only
  `docker_extra_args`/`container_persistent`/`network` instead of dumping 20 lines
  of the Hermes config into the report.
- **T5 / T6 — coverage.** `current_environment` override logic and StepGuard edge
  cases (success-then-failure, blocked decision, record-while-blocked, snapshot
  counters) are now tested (+8).

Remaining: **S2** — delete the stale gitignored `runs/audit_2026-07-01` artifact
locally (the sandbox mount can't unlink it).

## 2026-07-02 — Sprint 2 foundations (G2, G3)

Closed the remaining pre-Sprint-2 gaps from `AUDIT.md`. **Suite: 64 tests green.**

- **G2 — data contracts** (`src/contracts.py`): `RawSnapshot`, `NormalizedOffer`,
  `NormalizedFeed` frozen dataclasses with stdlib validators (fail-closed
  `ContractError`), dedupe-by-id, `to_dict`. The enforced JSON shapes for the
  extractor's output — see [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md).
- **G3 — JSONL run logger** (`src/run_log.py`): append-only `logs/<run_id>.jsonl`
  with recursive secret redaction (never logs `webSocketDebuggerUrl`, cookies, or
  2FA) and `log_guard(...)` to persist a StepGuard snapshot per task.
- Docs: added `DATA_CONTRACTS.md`; +20 tests for the two modules.

The read-only extractor (Sprint 2) that produces these artifacts still waits on
green VPS invariants before it is built.

## 2026-07-02 — P1 audit remediation

Closed the P1 findings from `AUDIT.md`. This hardens the read-only Sprint-1
foundation and its tests; there is no write path yet, so no runtime behavior
changed for submissions. **Test suite: 44 green (was 28).**

### Correctness & fail-closed
- **C1 — the two gates now probe AKS identically.** The shell audit
  (`scripts/00_audit_env.sh`) and the Python checker both do a **GET**, do **not**
  follow redirects, accept only **200/301/302**, timeout **10 s**. The checker no
  longer uses HEAD, so `audit.md` and the invariant JSON can no longer contradict
  each other.
- **C2 — "reachable" tightened.** `validate_aks_direct_status` now accepts only
  **200/301/302** (was 200–399). `http_get` gained `follow_redirects` (default
  `True`); the AKS probe runs with `follow_redirects=False`, so a redirect to a
  login/geo wall surfaces as its real 3xx instead of being followed to a 200.
- **C3 — control-channel token redacted.** The CDP `webSocketDebuggerUrl` is no
  longer serialized; the report exposes only `webSocketDebuggerUrl_present: bool`
  via `redact_cdp_payload`.

### Security
- **S1 — `.gitignore` hardened** with credential/cookie/token/pem/har/`.DS_Store`
  patterns. Specific patterns only, so source files are never accidentally ignored.

### Architecture / wiring
- **G1 — the checker now runs its probes through the StepGuard.** `build_report`
  (extracted to `src/invariants.py`) wraps the AKS + CDP probes in
  `guard.run_step(...)` with deterministic success predicates and includes the
  guard snapshot in the report. This is the template every future stage follows.
- Refactor: `scripts/01_check_invariants.py` is now a thin CLI over
  `src/invariants.py` (which also makes the report logic testable).

### Tests & CI
- **T1 — CI added** (`.github/workflows/ci.yml`): unittest suite on Python 3.10 +
  a source-only secret scan, on every push / PR.
- **T2** — HTTP probes tested via a mocked IO seam (`_http_open`): 2xx / HTTPError
  / URLError / Timeout branches, the no-follow 302 case, and the HTTP method used.
- **T3** — `cdp_client.get_version` tested across all four outcomes + wrong-endpoint.
- **T4** — `src/invariants.build_report` tested: guard wiring, payload redaction,
  ok/authoritative, 302-accepted.

### Deliberately deferred (tracked in `AUDIT.md`)
P2 debt (C4, C5, C6, S2, S3, T5, T6) and the Sprint-2 foundations **G2** (data
contracts) and **G3** (JSONL run logs) remain open — these are net-new modules
rather than fixes, and are the recommended next increment.
