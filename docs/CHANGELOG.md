# Changelog — AKS Controlled Executor

Notable changes, newest first. Dates are UTC. Complements [`AUDIT.md`](AUDIT.md)
(findings) and the roadmap in [`../README.md`](../README.md).

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
