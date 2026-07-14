# AKS Controlled Executor

A deterministic, auditable, **fail-closed** executor for AllKeyShop (AKS)
merchant-feed data entry: scanning merchant-feed offers, matching them to AKS
product pages, and submitting them through the WordPress admin feed.

It replaces a free-form LLM agent ("Hermes") that improvised whenever it got
blocked — looping on the same failed action, falling back to forbidden tools, and
reporting submissions that never actually landed in the database. The new design
moves the risky work behind a scripted engine with a hard guardrail: the model
**builds and supervises**, but never free-hands browser actions.

> **New to the project?** Start with [`docs/NOOB.md`](docs/NOOB.md) — a
> beginner-friendly, analogy-driven walkthrough of the whole system (in French).

> **Status — full pipeline built; submitter live-proven.** Read-only foundations
> (Sprints 1–3) complete, and the write stage created its **first real AKS offers on
> 2026-07-06** (Driffle, `--submit --click-mode trusted`). All write stages stay
> gated behind green + authoritative invariants on the Debian VPS target. See
> [Roadmap](#roadmap).

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
  instructions. Never executes free-form AKS browser actions.
- **N8N** — optional, later: orchestration, validation UI, notifications, log
  archive.

**Principles**

- **Fail-closed.** If anything is uncertain, stop. No fallback browser, no
  Playwright, no Browserbase, no VPN when AKS direct works, no degraded submit.
- **Deterministic success.** Every recorded success comes from code — an HTTP
  status, a parsed error field, or *the offer disappearing from the refreshed
  feed (same available mode as the run)* — never from a model self-assessment.
- **Guarded execution.** Every stage runs through the StepGuard.
- **Read-only until green.** No write stage runs until the invariant checker is
  `authoritative: true` **and** `ok: true` on the Debian VPS target.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full decision record.

---

## Repository layout

```
aks-controlled-executor/
├── README.md
├── AGENTS.md                   # builder rules (Codex)
├── CLAUDE.md                   # builder rules (Claude) — imports AGENTS.md
├── docs/
│   ├── NOOB.md                 # beginner-friendly guide to the whole project (French)
│   ├── ARCHITECTURE.md         # roles & target flow
│   ├── INVARIANTS.md           # non-negotiable browser/network invariants
│   ├── SPRINT_1_PLAN.md        # read-only foundation scope
│   ├── EXECUTOR_RULES.md       # deterministic per-stage spec (from the skill)
│   ├── DATA_CONTRACTS.md       # stage I/O JSON schemas + run-log format
│   ├── AUDIT.md                # audit findings + resolution status
│   ├── CONTRIBUTING.md         # developer guide
│   └── CHANGELOG.md            # notable changes
├── .github/workflows/ci.yml    # CI: unittest suite + secret scan (push / PR)
├── scripts/
│   ├── 00_audit_env.sh         # read-only env audit, tags PASS/FAIL/N-A
│   ├── 01_check_invariants.py  # thin CLI over src/invariants.py (fail-closed JSON)
│   ├── 02_extract_feed.py      # read-only feed extractor CLI (gated on green invariants)
│   ├── 03_match.py             # read-only matcher CLI → candidates/skipped/report
│   ├── 04_validate.py          # validation CLI (template + check, fail-closed gate)
│   └── 05_submit.py            # submitter CLI — dry-run default; --submit = real write (trusted)
├── src/
│   ├── aks_env.py              # constants, pure validators, env classification, HTTP probes
│   ├── cdp_client.py           # read-only CDP /json/version client (no browser actions)
│   ├── cdp_session.py          # read-only CDP WebSocket session (navigate + evaluate)
│   ├── invariants.py           # invariant report builder — probes run through the StepGuard
│   ├── contracts.py            # stage I/O data contracts (RawSnapshot / NormalizedOffer)
│   ├── extractor.py            # Sprint 2 read-only feed extractor
│   ├── matcher.py              # Sprint 3 read-only matcher (candidates + skipped)
│   ├── validation.py           # Stage 3 validation gate (approve exact candidates)
│   ├── submit_session.py       # read-only + narrow WriteSubmitSession (trusted picks/target/click)
│   ├── submitter.py            # Stage 4 submitter — dry-run + real write path
│   ├── run_log.py              # append-only JSONL run logger (redacting)
│   └── step_guard.py           # deterministic, fail-closed StepGuard
├── tests/                      # unit tests (190)
├── config/  runs/  logs/  state/   # runtime dirs (runs/logs/state are gitignored)
└── .gitignore
```

---

## Requirements

- **Python 3.10+** — standard library only, no production dependencies.
- Production runtime target: a **Debian VPS** exposing the Hermes CDP proxy at
  `http://172.17.0.1:9223/json/version`.
- For the login stage only (`scripts/00b_login.py`, see
  [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md)): `AKS_WP_USER` and
  `AKS_WP_PASSWORD` in the environment (e.g. a `chmod 600` `.env` you
  `source`, already gitignored) — never a CLI arg, never committed.

---

## Quick start

```bash
# 1. Environment audit (read-only). Run on the Debian VPS target:
./scripts/00_audit_env.sh
#    → writes runs/audit_<timestamp>/audit.md
#    → final RESULT line: GREEN / RED / NON-AUTHORITATIVE

# 2. Invariant gate (read-only). Must be authoritative:true AND ok:true on the VPS:
python3 scripts/01_check_invariants.py

# 3. Unit tests (pure — run anywhere):
python3 -m unittest discover -s tests -v
```

**Environment classification.** The audit and the invariant checker detect where
they run. Only the real Debian VPS target is `authoritative`; a red result on
macOS, a dev box, or a sandbox is **not** a production failure and never unlocks
write stages. Override detection with `AKS_TARGET=vps` or `AKS_TARGET=dev`.

---

## Manual launch

For a terminal-only data-entry run, use the helper in
`manual_launch/run_executor.sh`. It wraps the existing scripts without adding any
LLM/agent call. It still preserves the hard validation gate: `prepare` stops
before approval, and real writes require the explicit `submit` command.

Start from the repo root:

```bash
cd /Users/romainlamarque/aks_code/executor
```

Prepare a run:

```bash
manual_launch/run_executor.sh prepare --merchant Driffle --store-id 127
```

This runs the audit, invariant gate, extraction, matcher, and validation-template
generation. It prints the generated run directory, for example:

```text
Prepared run:
  /Users/romainlamarque/aks_code/executor/runs/2026-07-13_101500_driffle
```

That directory is the `RUN_DIR` used by the next commands. You may pass it as an
absolute path:

```bash
manual_launch/run_executor.sh check /Users/romainlamarque/aks_code/executor/runs/2026-07-13_101500_driffle
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
starts, so a mid-task "retry past it" is impossible. See
[`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) §2 for how each rule from the
`aks-data-entry` skill maps onto a guard signal.

---

## Rules & docs

- [`docs/NOOB.md`](docs/NOOB.md) — beginner-friendly guide: what the project
  is, why it exists, and how the pipeline works, explained with analogies (French).
- [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) — the deterministic,
  per-stage specification derived from the `aks-data-entry` skill. The bridge
  from domain rules to code (extractor, matcher, submitter, post-save
  verification, reporting).
- [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md) — Stage 0b: the deterministic
  login/2FA design (credentials from the environment only, 2FA requested only
  once visible and ready, one attempt each).
- [`docs/INVARIANTS.md`](docs/INVARIANTS.md) — the non-negotiable browser/network
  invariants.
- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — builder rules for Codex
  and Claude.

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
  AKS slug resolve (`data-product-id` + editions), ≤100 candidates, normalized-text
  report. Pure core unit-tested; live AKS resolve runs on the VPS.
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
- [x] **Login / 2FA — Stage 0b** (`src/login_session.py`, `scripts/00b_login.py`,
  2026-07-14, Romain Option A): narrowly-scoped, deterministic login on
  explicit go only. Password from the environment, never stored/logged; a 2FA
  code is requested only once the field is confirmed visible and ready, one
  attempt each, no retry loop. See [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md).

---

## Safety

- Never commit `runs/`, `logs/`, `state/`, `.env`, cookies, or 2FA codes.
- Submission happens **only** through the AKS feed UI modal — never a direct
  `admin-ajax` XHR (the modal auto-assigns the merchant id).
- `[data-success]` is never proof of creation. An offer is "created" only after
  it disappears from the refreshed feed (same available mode as the run).
- 2FA is never requested before the field is visible and ready to submit
  immediately (Stage 0b, `docs/LOGIN_SPEC.md`) — one attempt each for the
  password and the code, no retry loop; after any login/2FA/CDP failure,
  stop and report.
