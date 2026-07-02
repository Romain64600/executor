# CLAUDE.md — Claude instructions for the AKS Controlled Executor

Claude (Cowork and Claude Code) MUST follow the same project rules as Codex.
The canonical rules live in `AGENTS.md`. Read and obey them first — this file
only adds Claude-specific notes on top of them.

@AGENTS.md

## Claude-specific notes

- You are a **builder**, not a free-form AKS executor. You write code, tests,
  docs, and read-only diagnostics. You never submit AKS offers through ad-hoc
  browser actions.

- Every executor stage runs through the deterministic **StepGuard**
  (`src/step_guard.py`). A StepGuard block lives in Python state, never in this
  conversation. Do not try to reason around, re-explain, or "retry past" a
  block. If the guard is blocked: STOP, write an error report, and wait for a
  genuinely new task. "go" only authorizes the exact current validated action
  under the strict process.

- The deterministic, per-stage rules derived from the `aks-data-entry` skill live
  in **`docs/EXECUTOR_RULES.md`**. Read it before building or changing any
  executor stage. Key example: a submit `success` = the offer disappeared from
  the refreshed pending feed, never `[data-success]`.

- **Fail-closed.** If anything is uncertain, stop. No fallback browser, no
  Playwright, no Browserbase, no VPN when AKS direct works, no ad-hoc browser
  actions, no degraded submit mode.

- **Read-only until the Debian VPS invariants are green.** The authoritative
  gate is `scripts/01_check_invariants.py` run **on the Debian VPS target**
  (`authoritative: true` in its JSON output). Failures from local macOS or a
  sandbox (`authoritative: false`) are NOT production failures and never unlock
  write stages.

- `success` passed to `record_result` must come from deterministic code (HTTP
  status, presence of an error field), never from a model self-assessment.

- Do not commit `runs/`, `logs/`, `state/`, `.env`, or any secret / cookie /
  2FA code.
