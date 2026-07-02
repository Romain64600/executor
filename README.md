# AKS Controlled Executor

A deterministic, auditable, **fail-closed** executor for AllKeyShop (AKS)
merchant-feed data entry: scanning pending merchant offers, matching them to AKS
product pages, and submitting them through the WordPress admin feed.

It replaces a free-form LLM agent ("Hermes") that improvised whenever it got
blocked — looping on the same failed action, falling back to forbidden tools, and
reporting submissions that never actually landed in the database. The new design
moves the risky work behind a scripted engine with a hard guardrail: the model
**builds and supervises**, but never free-hands browser actions.

> **Status — Sprint 1 (read-only foundations) complete.** All write stages are
> gated behind green invariants on the Debian VPS target. See [Roadmap](#roadmap).

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
  pending feed* — never from a model self-assessment.
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
│   ├── ARCHITECTURE.md         # roles & target flow
│   ├── INVARIANTS.md           # non-negotiable browser/network invariants
│   ├── SPRINT_1_PLAN.md        # read-only foundation scope
│   └── EXECUTOR_RULES.md       # deterministic per-stage spec (from the skill)
├── scripts/
│   ├── 00_audit_env.sh         # read-only env audit, tags PASS/FAIL/N-A
│   └── 01_check_invariants.py  # read-only invariant gate → JSON, fail-closed
├── src/
│   ├── aks_env.py              # constants, pure validators, env classification, HTTP probes
│   ├── cdp_client.py           # read-only CDP /json/version client (no browser actions)
│   └── step_guard.py           # deterministic, fail-closed StepGuard
├── tests/                      # pure unit tests
├── config/  runs/  logs/  state/   # runtime dirs (runs/logs/state are gitignored)
└── .gitignore
```

---

## Requirements

- **Python 3.10+** — standard library only, no production dependencies.
- Production runtime target: a **Debian VPS** exposing the Hermes CDP proxy at
  `http://172.17.0.1:9223/json/version`.

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
    success_predicate=lambda r: r["gone_from_pending"],  # deterministic success
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

- [`docs/EXECUTOR_RULES.md`](docs/EXECUTOR_RULES.md) — the deterministic,
  per-stage specification derived from the `aks-data-entry` skill. The bridge
  from domain rules to code (extractor, matcher, submitter, post-save
  verification, reporting).
- [`docs/INVARIANTS.md`](docs/INVARIANTS.md) — the non-negotiable browser/network
  invariants.
- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — builder rules for Codex
  and Claude.

---

## Roadmap

- [x] **Sprint 1 — read-only foundations:** invariant checks, read-only CDP
  `/json/version` client, deterministic StepGuard, environment-aware audit, pure
  unit tests.
- [ ] **Sprint 2 — read-only feed extractor** (gated on green VPS invariants):
  refresh the pending feed from scratch, extract current offers, snapshot JSON.
- [ ] **Sprint 3 — read-only matcher:** port the skill's matching rules
  (strict name match, region-from-URL, edition detection, SKIP lists, ≤100).
- [ ] **Validation** — generate a validation file requiring exact candidate ids.
- [ ] **Submitter** — dry-run by default, locked behind validation; submit only
  via the AKS feed UI modal; `success = offer gone from the refreshed pending feed`.
- [ ] **Post-save verifier + JSONL run logs.**

---

## Safety

- Never commit `runs/`, `logs/`, `state/`, `.env`, cookies, or 2FA codes.
- Submission happens **only** through the AKS feed UI modal — never a direct
  `admin-ajax` XHR (the modal auto-assigns the merchant id).
- `[data-success]` is never proof of creation. An offer is "created" only after
  it disappears from the refreshed pending feed.
- 2FA is never requested in advance; after two login/2FA/CDP failures, stop and
  report.
