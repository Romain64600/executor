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
> gated behind green + authoritative invariants on the Debian VPS target. A full
> multi-agent audit ran on **2026-07-17**; its findings are tracked in
> [`docs/AUDIT_2026-07-17.md`](docs/AUDIT_2026-07-17.md). See [Roadmap](#roadmap).

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
- **Admin page** — the operator's validation UI on the VPS
  (`https://51.38.37.254.sslip.io/executor/`, nginx HTTPS + basic auth):
  read the normalized report, approve/reject/override candidates, launch a
  supervised dry-run/submit. See [`ops/INSTALL_ADMIN.md`](ops/INSTALL_ADMIN.md).
- **N8N** — optional, later: orchestration, notifications, log archive.

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
executor/
├── README.md
├── AGENTS.md                   # builder rules (Codex)
├── CLAUDE.md                   # builder rules (Claude) — imports AGENTS.md
├── .github/workflows/ci.yml    # CI: unittest suite + secret scan (push / PR)
├── docs/
│   ├── NOOB.md                 # beginner-friendly guide to the whole project (French)
│   ├── ARCHITECTURE.md         # roles & target flow
│   ├── INVARIANTS.md           # non-negotiable browser/network invariants
│   ├── SPRINT_1_PLAN.md        # read-only foundation scope
│   ├── EXECUTOR_RULES.md       # deterministic per-stage spec (from the skill)
│   ├── SUBMITTER_SPEC.md       # Stage 4 submitter spec (dry-run + trusted write path)
│   ├── AKS_LISTS.md            # Stage 6 Move-to-List: list taxonomy + move mechanic
│   ├── LEARNING_PROCESS.md     # learning → pipeline: the builder-offline process (D2)
│   ├── LOGIN_SPEC.md           # Stage 0b login/2FA spec
│   ├── DATA_CONTRACTS.md       # stage I/O JSON schemas + run-log format
│   ├── AUDIT.md                # Sprint 1 audit (2026-07-02) — fully resolved
│   ├── AUDIT_2026-07-17.md     # audit register 2026-07-17 — findings tracked OPEN → FIXED
│   ├── CONTRIBUTING.md         # developer guide
│   ├── CHANGELOG.md            # notable changes
│   └── ua-switcher-aks-staff.json  # UA-Switcher policy config (AKS/Staff UA)
├── scripts/
│   ├── 00_audit_env.sh         # read-only env audit, tags PASS/FAIL/N-A
│   ├── 00b_login.py            # Stage 0b login/2FA CLI — explicit go only, one attempt each
│   ├── 01_check_invariants.py  # thin CLI over src/invariants.py (fail-closed JSON)
│   ├── 02_extract_feed.py      # read-only feed extractor CLI (gated on green invariants)
│   ├── 03_match.py             # read-only matcher CLI → candidates/skipped/report
│   ├── 04_validate.py          # validation CLI (template + check, fail-closed gate)
│   ├── 05_submit.py            # submitter CLI — dry-run default; --submit = real write (trusted)
│   ├── 06_move.py              # Stage 6 Move-to-List writer — dry-run default; --execute = real move
│   └── 07_admin_server.py      # admin page server (loopback only, behind nginx basic auth)
├── manual_launch/
│   └── run_executor.sh         # terminal-only launcher: prepare / check / dry-run / submit
├── ops/                        # admin page install: systemd unit, nginx vhost, runbook
├── src/
│   ├── admin/                  # admin page: HTTP app (app.py), safe run access (runs.py),
│   │                           #   validation triple regen (validation_io.py), supervised
│   │                           #   submit (submit_manager.py), Learning annotations
│   │                           #   (learning_io.py), static/ UI
│   ├── aks_env.py              # constants, pure validators, env classification, HTTP probes
│   ├── browser_lock.py         # advisory flock on state/browser.lock — one tab, one navigator (OP1)
│   ├── cdp_client.py           # read-only CDP /json/version client (no browser actions)
│   ├── cdp_session.py          # read-only CDP WebSocket session (navigate + evaluate)
│   ├── invariants.py           # invariant report builder — probes run through the StepGuard
│   ├── contracts.py            # stage I/O data contracts (RawSnapshot / NormalizedOffer)
│   ├── extractor.py            # Sprint 2 read-only feed extractor
│   ├── matcher.py              # Sprint 3 read-only matcher (candidates + skipped)
│   ├── validation.py           # Stage 3 validation gate (approve exact candidates)
│   ├── submit_session.py       # read-only + narrow WriteSubmitSession (trusted picks/target/click)
│   ├── submitter.py            # Stage 4 submitter — dry-run + real write path
│   ├── mover.py                # Stage 6 Move-to-List writer (the submitter's sibling)
│   ├── move_plan.py            # Stage 6 plan builder — confirmed learning.json dispositions
│   ├── aks_lists.py            # merchant-feed list catalog + deterministic triage suggestions
│   ├── login_session.py        # Stage 0b login/2FA session (reuses the trusted-input primitives)
│   ├── pacing.py               # bounded-random pacing between page loads / submissions
│   ├── run_log.py              # append-only JSONL run logger (redacting)
│   └── step_guard.py           # deterministic, fail-closed StepGuard
├── tests/                      # unit tests (743)
├── runs/  logs/  state/        # runtime dirs (gitignored)
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

# 3. Unit tests (743, pure — run anywhere):
python3 -m unittest discover -s tests
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

### Stage 6 — Move to List

`scripts/06_move.py` + `src/mover.py` is the **submitter's sibling**: a writer
that moves a non-matched offer **out of its source list** into the list the
operator annotated. The move plan is built from the run's **confirmed**
Move-to-list dispositions (`src/move_plan.py`, from `learning.json`) — *garder*
and still-`suggested` dispositions are never in a plan. Same fail-closed
discipline as the submitter: invariants green + authoritative, one CDP tab under
the browser lock, **dry-run by default** (`--execute` writes), a **mandatory
canary on the first real move** (`--mode learning`; `--mode safe`, the full plan,
is refused until a canary has verified), explicit go, never fire-and-forget.
Success = **the offer left the source list** on the refreshed feed (the analogue
of the submit's "gone from feed").

```bash
# Plan only — dry-run (default). No write:
python3 scripts/06_move.py runs/<id> --store-id 38

# First real move must be a canary of 1 (--mode learning), on explicit go:
python3 scripts/06_move.py runs/<id> --store-id 38 --execute --mode learning

# Once a canary has verified, the full confirmed plan (--mode safe):
python3 scripts/06_move.py runs/<id> --store-id 38 --execute --mode safe
```

See [`docs/AKS_LISTS.md`](docs/AKS_LISTS.md) for the list taxonomy and the move
mechanic.

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
- [`docs/LEARNING_PROCESS.md`](docs/LEARNING_PROCESS.md) — how a Learning
  annotation becomes pipeline behaviour: the builder-offline process (decision
  D2) — a move, an assisted manual entry, or a tested/documented/committed
  matcher rule; never a rule auto-applied at runtime, no rule engine in the repo.
- [`docs/AKS_LISTS.md`](docs/AKS_LISTS.md) — Stage 6 Move-to-List: the
  merchant-feed list taxonomy and the deterministic (read-only-captured) move
  mechanic.
- [`docs/LOGIN_SPEC.md`](docs/LOGIN_SPEC.md) — Stage 0b: the deterministic
  login/2FA design (credentials from the environment only, 2FA requested only
  once visible and ready, one attempt each).
- [`docs/INVARIANTS.md`](docs/INVARIANTS.md) — the non-negotiable browser/network
  invariants.
- [`docs/AUDIT_2026-07-17.md`](docs/AUDIT_2026-07-17.md) — the audit register:
  findings from the 2026-07-17 multi-agent audit, each tracked `OPEN` → `FIXED`
  with date and commit. Complements [`docs/AUDIT.md`](docs/AUDIT.md) (Sprint 1
  audit, 2026-07-02, fully resolved).
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
- [x] **Stage 6 — Move-to-List writer** (`src/mover.py`, `src/move_plan.py`,
  `scripts/06_move.py`, 2026-07-21) — the submitter's sibling: moves a
  non-matched offer out of its source list into the annotated target list; plan
  built from the confirmed `learning.json` dispositions. Dry-run by default
  (`--execute` writes), canary-of-1 on the first real move (`--mode learning`),
  explicit go, never fire-and-forget; success = the offer left the source list.
  **No real move has run yet** — the first canary awaits Romain's explicit go.
  See [`docs/AKS_LISTS.md`](docs/AKS_LISTS.md).
- [x] **Runtime hardening** (`src/browser_lock.py`, `src/pacing.py`) —
  advisory `flock` on `state/browser.lock` so only one process drives the
  single CDP tab at a time (fail-closed: busy lock = refuse to start; OP1,
  audit 2026-07-17), and bounded-random pacing (`--pace MIN-MAX`) between page
  loads/submissions with counters recorded in the run log.

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
