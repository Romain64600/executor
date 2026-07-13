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
  **Hard constraint:** Do not use multi-turn reasoning, retries, alternate
  tools, or reframing to bypass a StepGuard block.

- The deterministic, per-stage rules derived from the `aks-data-entry` skill live
  in **`docs/EXECUTOR_RULES.md`**. Read it before building or changing any
  executor stage. Key example: a submit `success` = the offer disappeared from
  the refreshed feed (same available mode as the run), never `[data-success]`.

- **Fail-closed.** If anything is uncertain, stop. No fallback browser, no
  Playwright, no Browserbase, no VPN when AKS direct works, no ad-hoc browser
  actions, no degraded submit mode.

- **Read-only until the Debian VPS invariants are green.** The authoritative
  gate is `scripts/01_check_invariants.py` run **on the Debian VPS target**
  (`authoritative: true` in its JSON output). Failures from local macOS or a
  sandbox (`authoritative: false`) are NOT production failures and never unlock
  write stages.
  **Hard constraint:** If running on local macOS or any non-authoritative
  environment, treat `authoritative:false` as expected local state. Do not try
  to force a local green result by changing environment variables, networking,
  endpoints, browser setup, or invariant code.

- `success` passed to `record_result` must come from deterministic code (HTTP
  status, presence of an error field), never from a model self-assessment.

- **Scope separation:** Claude must not self-initiate long-running asynchronous
  batch tasks, cloud-polling workers, or massive parallel test generation.
  When Romain directs the data entry, pipeline stages are in scope with an
  explicit split:
  - **extract / match / report (read-only):** may run as background processes,
    with their logs and JSON outputs collected;
  - **submit:** only on Romain's explicit go, and **never fire-and-forget**
    (AGENTS.md) — the process stays attached or harness-supervised. Once a
    report is validated (`approved.json` generated), we submit, and the
    **data-entry mode** (`--mode`, R24, 2026-07-13) decides the batch size:
    - `safe` (**default**) — the **full validated batch**, no canary-of-1 on
      top of an already-validated batch (Romain: "on ne lance plus un canary
      quand on est en mode safe");
    - `learning` / `advanced` — they **do write** (learning is NOT read-only:
      "il ajoute les offres si le rapport normalisé est valide"), but are
      **capped at a canary of 1** for now ("tjrs un canary pour le moment").
      `--limit N` narrows a canary mode, never widens it.

    Its exit code + `submit_plan.json` are read and checked before ANY
    continuation to a **new** run/page/stage — the in-run stop condition (10
    consecutive failures) is unchanged.

  Otherwise keep work scoped to local file diffs, refactoring, focused tests,
  documentation, and deterministic Python state evaluation.

- Do not commit `runs/`, `logs/`, `state/`, `.env`, or any secret / cookie /
  2FA code.
