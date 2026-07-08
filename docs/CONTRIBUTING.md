# CONTRIBUTING — developer guide

How to build, test, and extend the AKS Controlled Executor. Read this with
[`../AGENTS.md`](../AGENTS.md) / [`../CLAUDE.md`](../CLAUDE.md) (builder rules) and
[`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) (the deterministic per-stage spec). Known
issues and priorities live in [`AUDIT.md`](AUDIT.md).

## Golden rule

You are a **builder**, not a free-form AKS executor. You write code, tests, docs,
and read-only diagnostics. You never submit offers through ad-hoc browser actions,
and you never add a fallback (Browserbase, Playwright, VPN-when-direct-works,
degraded submit). **If anything is uncertain, stop.**

---

## Setup

- **Python 3.10+**, standard library only. There are **no third-party
  dependencies**, and none may be added without Romain's explicit approval
  (`AGENTS.md`). No virtualenv is required for the current code.
- Clone, then work from the repo root; scripts and tests assume it as CWD.

```bash
git clone https://github.com/Romain64600/executor.git aks-controlled-executor
cd aks-controlled-executor
```

---

## Running things

```bash
# Read-only environment audit (human Markdown report under runs/).
# Run on the Debian VPS target for an authoritative result.
./scripts/00_audit_env.sh
#   → runs/audit_<timestamp>/audit.md ; final line: GREEN / RED / NON-AUTHORITATIVE

# Read-only invariant gate (machine JSON). The authoritative production gate.
python3 scripts/01_check_invariants.py
#   → exits non-zero if any invariant fails (fail-closed)
#   → "authoritative": true only on the Debian VPS target

# Unit tests (pure — run anywhere).
python3 -m unittest discover -s tests -v

# Read-only feed extractor (VPS only — needs the live CDP session).
# Refuses to run unless invariants are green + authoritative.
python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127
```

**Environment classification.** Both tools detect where they run; only the real
Debian VPS is `authoritative`. A red result on macOS/dev/sandbox is **not** a
production failure and never unlocks write stages. Force detection with
`AKS_TARGET=vps` or `AKS_TARGET=dev` (see `src/aks_env.py: current_environment`).

---

## Testing

- Framework: stdlib `unittest`. One test module per source module, under
  `tests/`, named `test_<module>.py`.
- Prefer **pure** tests (no network, no clock, no filesystem). Inject seams:
  - `StepGuard(clock=lambda: "2026-01-01T00:00:00Z")` for deterministic timestamps.
  - Patch IO at the boundary — e.g. `unittest.mock.patch("src.aks_env.urlopen", …)`
    to test `http_get` / `http_head_status` branches, or patch
    `src.cdp_client.http_get` to drive `ReadOnlyCdpClient.get_version` outcomes.
    (These two areas are the current coverage gaps — see `AUDIT.md` T2/T3.)
- A test that asserts **behavior at a boundary** is worth more than one that
  restates the implementation. Example: assert the HTTP *method* used for the AKS
  probe, so the shell/Python gates can't silently diverge (AUDIT.md C1).
- Run the whole suite before every commit; it must stay green. CI
  (`.github/workflows/ci.yml`) runs the suite + a source secret-scan on every
  push/PR, but still run it locally first (the sandbox builder can't push, so it
  won't trigger CI for you).
- The invariant report logic lives in `src/invariants.py` (`build_report`), which
  runs its probes through the StepGuard — use it as the template for new stages.
  Mock the IO seams in tests: `src.aks_env._http_open`, `src.cdp_client.http_get`,
  or `src.invariants.http_get` / `src.invariants.ReadOnlyCdpClient`.

---

## Coding conventions

- `from __future__ import annotations` at the top; full type hints; modern union
  syntax (`int | None`).
- Model results as **frozen dataclasses** with a `to_dict()` when they get logged
  (see `CheckResult`, `StepAttempt`). Immutability is deliberate.
- **Fail-closed** helpers: aggregate with `all(...)`, return a structured result
  rather than raising for expected "not reachable" states, and raise loudly for
  states that must never happen (e.g. `websocket_url()` in read-only mode).
- **Determinism:** any `success` value must come from code (HTTP status, a parsed
  error field, "offer gone from the refreshed feed, same available mode as the run") — **never** a model
  self-assessment. This is the single most important rule; see `EXECUTOR_RULES.md`
  §2/§7.
- Outputs: JSON for machine data, JSONL for event logs, Markdown for human
  reports. CLI scripts print JSON to stdout and use exit codes.
- **Never** log or serialize secrets or control tokens (cookies, 2FA codes,
  `webSocketDebuggerUrl`). Redact at the boundary (AUDIT.md C3).
- Keep scripts read-only until the Debian VPS invariants are green.

---

## Using the StepGuard

Every executor stage runs its actions through `src/step_guard.py`. The block lives
in Python state and cannot be reasoned around by a model.

```python
from src.step_guard import StepGuard, StepGuardError

guard = StepGuard(max_attempts_per_signature=2)  # one retry, then stop
guard.start_task(run_id)          # id set by the loop per user intent, NOT the model

try:
    guard.run_step(
        "extract", f"feed:{merchant}:p{page}",
        action=lambda: fetch_page(merchant, page),
        success_predicate=lambda r: r.http_status == 200 and r.offers is not None,
    )
except StepGuardError as exc:
    stop_and_report(exc.decision)  # do NOT retry, do NOT fall back
```

Rules of use:
- Call `start_task(run_id)` once per user intent. Re-using the same id never clears
  a block — only a genuinely new id does. Map the validation file's `run_id` to
  this `task_id` (AUDIT.md G4).
- Pass a **deterministic** `success_predicate`. For submit, success =
  `offer_disappeared_from_refreshed_feed` (same `available` mode as the run), never `[data-success]`.
- On a `StepGuardError`, stop and write an error report. Never retry the same
  signature, never switch browser/VPN/tool.
- Persist `guard.snapshot()` to the JSONL run log (once G3 lands).

---

## Adding a new executor stage

1. Read [`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) for that stage's deterministic
   rules (extractor / matcher / submitter / reporting).
2. Stay **read-only** until `scripts/01_check_invariants.py` is `authoritative` and
   `ok` on the VPS. No write stage before the gate is green.
3. Define the data contract first (dataclasses + stdlib validators); add it to
   `docs/DATA_CONTRACTS.md` (AUDIT.md G2).
4. Route every external action through the StepGuard with a deterministic success
   predicate.
5. Write tests (pure where possible; mock IO at the boundary) and keep the suite
   green.
6. Emit JSONL run logs; never log secrets.
7. No fallback, no degraded mode. Uncertain → stop and report.

---

## Git / commit & push

- **Never commit** `runs/`, `logs/`, `state/`, `.env`, cookies, 2FA codes,
  tokens, or `*.pem`/`*.har` (harden `.gitignore` per AUDIT.md S1).
- Commit messages: imperative, scoped (e.g. `Add read-only feed extractor`).
- Keep the suite green before committing.

Note for the Claude/Cowork builder: the sandbox **cannot** write to `.git` or
authenticate to GitHub, so it cannot commit or push. Do that locally:

```bash
git add -A
git commit -m "<message>"
git push
# if git complains about a lock: rm -f .git/index.lock
```
