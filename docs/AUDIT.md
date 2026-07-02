# AUDIT — AKS Controlled Executor

**Date:** 2026-07-02 · **Scope:** whole repo (Sprint 1 read-only foundations).
**Method:** close code review + an independent second-pass audit (subagent) +
evidence gathering (git, grep, test run). No files were modified for this audit.

## Executive summary

For a Sprint-1 read-only foundation the codebase is **solid and genuinely
fail-closed**. `step_guard.py` is a correct, well-tested state machine; the
environment-classification split (`authoritative` vs not) is right and tested; the
invariant checker exits non-zero on failure; the shell audit is read-only.

**No P0 (blocking) issues.** The findings are edge cases, secret-hygiene
hardening, test-coverage gaps in exactly the code that decides "reachable", and
the scaffolding that must exist before Sprint 2. Counts: **0 × P0, 13 × P1,
9 × P2.**

**Fix first (before Sprint 2):** `C1` (the two gates use different HTTP methods
and can contradict each other), `C2` (a redirect to a login/geo wall is reported
as "reachable"), `C3`/`S1` (secret hygiene), and `T2`/`T3`/`T4` (the
reachability/gate code is the least-tested code in the repo).

Severity: **P0** = blocks / unsafe now · **P1** = fix before building write
stages · **P2** = nice-to-have / debt.

> **Resolution status (2026-07-02).** All audit findings are addressed
> (**72 tests green**): P1 — C1, C2, C3, S1, G1, G2, G3, T1–T4; P2 — C4, C5, C6,
> S3, T5, T6. The only item left is **S2** — delete the stale
> `runs/audit_2026-07-01` artifact (gitignored, never in VCS; the sandbox can't
> unlink it, so remove it locally with `rm -rf runs/audit_20260701_150912`). See
> [`CHANGELOG.md`](CHANGELOG.md) and [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md). The
> read-only extractor (Sprint 2) stays gated on green VPS invariants.

---

## Axis 1 — Correctness & fail-closed adherence

### C1 · P1 · AKS reachability uses a different HTTP method in the two gates
`scripts/00_audit_env.sh:66` probes AKS with a **GET**
(`curl -s -o /dev/null -w '%{http_code}' … /blog/`), while
`scripts/01_check_invariants.py:32` → `src/aks_env.py` `http_head_status()` uses a
**HEAD**. AKS is behind Apache + a strict CSP; many such stacks answer HEAD and
GET differently (405/403/redirect vs 200). So the shell audit can say `GREEN`
while the authoritative invariant gate says the AKS check failed, or vice-versa —
yet the roadmap gates write stages on both. Timeouts also differ (shell 10 s;
the checker calls `http_head_status` with `--timeout` default **5 s**).
**Fix:** use one method for both. Standardize on GET (AKS returns a real 200 to
GET) — either switch the checker to the existing `http_get`, or the shell to
`curl -I` — and align the timeout.

### C2 · P1 · "AKS reachable" is looser than the documented invariant and follows redirects
`src/aks_env.py` `validate_aks_direct_status` accepts **200–399**
(`200 <= status < 400`), but `INVARIANTS.md` / `EXECUTOR_RULES.md` / the skill
define the allowed set as **200/301/302**. Moreover `urllib`'s `urlopen`
**follows redirects by default**, so a 301/302 to `wp-login.php`, a captcha, or a
geo wall is transparently followed and the final `200` is reported as
"reachable". This is the classic "silently passes when it should fail".
**Fix:** tighten to the documented set and decide redirect policy deliberately —
either don't auto-follow and validate the first hop, or follow and assert the
final URL is same-origin AKS and not a login page.

### C3 · P1 · Reports serialize raw headers/body and print the CDP control-channel token
`HttpProbeResult` keeps full `headers` and `body`
(`src/aks_env.py` `_response_to_probe`, `http_head_status`), and
`scripts/01_check_invariants.py` prints `"payload": cdp_result.payload` to stdout
— which includes `webSocketDebuggerUrl`, a live browser-control channel. AKS GET
responses also carry `Set-Cookie` (e.g. `ip_country_code`). Even though the gate
is read-only, this puts a control token and cookies into stdout / any redirected
log. **Fix:** don't serialize raw headers/body in reports; redact
`webSocketDebuggerUrl` to a boolean "present"; keep only `status` + a whitelist
(`Browser`, `User-Agent`).

### C4 · P2 · StepGuard conflates "attempt" and "failure" against one limit
`src/step_guard.py`: `check()` counts **attempts** (success + failure) against
`max_attempts_per_signature`, while the hard block counts **failures** against the
same number. With the default `2`, "one retry then stop" holds only for
pure-failure sequences; a *success then failure* of one signature exhausts the
attempt ceiling and yields a soft deny rather than a hard block. Defensible, but
a latent trap for Sprint-2 authors. **Fix:** give the hard block its own name
(`max_failures_per_signature`) distinct from the attempt ceiling, or document the
asymmetry at the block site. (Ties to T6 — add a test pinning the intended
success-then-failure behavior.)

### C5 · P2 · Two divergent "blocked decision" builders
`check()` builds a blocked `GuardDecision` inline (with the real `signature`),
while `run_step` uses `_block_decision()` (which hard-codes `signature=None`).
Harmless today, refactor hazard. **Fix:** route both through one helper.

### C6 · P2 · Read-only CDP client will still probe an arbitrary `--endpoint`
`scripts/01_check_invariants.py` exposes `--endpoint` with no allow-list;
`ReadOnlyCdpClient.get_version` records a failing endpoint check (so the gate
fails closed — good) but still issues the GET to the operator-supplied host
first. This contradicts the "no random `0.0.0.x` probes / only `172.17.0.1:9223`"
invariant. **Fix:** refuse to send the request when `validate_official_cdp_endpoint`
fails, or drop `--endpoint` (the default is the only sanctioned value).

*Positive:* `checks_to_dict` aggregates with `all(...)`; `websocket_url()`
hard-raises; the checker returns non-zero on `not ok`. Fail-closed where it counts.

---

## Axis 2 — Security & secrets

### S1 · P1 · `.gitignore` lacks the credential/cookie/token patterns the docs promise
Current ignore list is only `runs/ logs/ state/ .env *.pyc __pycache__/`. There
is no rule for `*.pem *.key *.crt *.p12`, `cookies* *.cookies`, `.env.* env.*`,
`*.har` (network captures leak cookies/tokens), `*.otp *.2fa`, `auth*.json`,
`config/*.local.*`, or `.DS_Store` — yet `README.md` (Safety) and `AGENTS.md`
commit to "never commit cookies or 2FA codes." When login/2FA land (Sprint 4+), a
stray `cookies.txt` or `.har` would be trivially committable. **Fix:** expand
`.gitignore` now. *(Verified: no secret is currently committed — the tracked tree
is clean.)*

### S2 · P2 · Stale, sensitive run artifact on disk (and format-drifted)
`runs/audit_20260701_150912/audit.md` is **not tracked** (correctly gitignored),
but it sits unencrypted in the working tree and contains recon-grade data: a full
CSP domain list, a `Set-Cookie`, and a Docker inventory naming several unrelated
internal projects (names redacted here — this audit doc is committable; see the
on-disk file for specifics). It was also produced by an **older audit script**
than the current
`00_audit_env.sh` (different format), so anyone reading it as "example output" is
misled. **Fix:** delete stale run artifacts from the working tree; if a sample is
wanted, store a **redacted** one under `docs/`, not `runs/`. *(I can delete it on
your say-so.)*

### S3 · P2 · The audit report can capture Hermes config secrets
`scripts/00_audit_env.sh` dumps up to 20 lines of
`/home/debian/.hermes/config.yaml` (`grep -nA20 '^terminal:'`) into the report; if
that config holds tokens/hostnames they land in `runs/…/audit.md` (protected only
by `.gitignore`). **Fix:** whitelist the specific non-secret keys you need instead
of `-A20`, or drop the excerpt from the persisted report.

*Positive:* the shell script is genuinely read-only, quotes its variables, uses no
`sudo`/`eval` on external input, and gates its non-zero exit on the authoritative
target only.

---

## Axis 3 — Test coverage

Current suite: **28 tests, all green**, but concentrated on pure functions. The
IO/decision code is the least covered.

### T1 · P1 · No CI, no test-runner config
No `.github/`, `Makefile`, `pyproject.toml`, `tox.ini`, or pre-commit config. The
README advertises the test command but nothing runs it automatically and nothing
enforces the "no secrets" rule. **Fix:** add a minimal GitHub Actions workflow
running `python3 -m unittest` on 3.10+, plus a grep/`gitleaks` secret scan.

### T2 · P1 · HTTP probe functions are entirely untested
`http_get`, `http_head_status`, `_response_to_probe` (`src/aks_env.py`) have zero
tests — none of the 2xx/3xx, `HTTPError`, `URLError`, `TimeoutError` branches.
This is the code that decides "reachable." **Fix:** patch
`src.aks_env.urlopen` and test each branch, including an assertion on the request
method (would have caught C1).

### T3 · P1 · `cdp_client.get_version` is almost untested
`tests/test_cdp_client.py` only checks that `websocket_url()` raises. None of
`get_version`'s four outcomes are covered (probe-not-ok, non-JSON body, full pass,
bad UA/shape). **Fix:** patch `src.cdp_client.http_get` with crafted
`HttpProbeResult`s and assert `.ok`, `.error`, and the emitted check names.

### T4 · P1 · The invariant checker has no tests
`build_report`, `main`, and the exit-code contract in
`scripts/01_check_invariants.py` are untested. **Fix:** monkeypatch
`http_head_status` + `ReadOnlyCdpClient.get_version`, assert `report["ok"]`,
`report["authoritative"]`, and `main()`'s return code.

### T5 · P2 · `current_environment` override logic untested
`classify_environment` (pure) is well tested, but the `AKS_TARGET=vps|dev|…`
override and the marker-file fallback are not. **Fix:** parametrized test setting
`AKS_TARGET` and patching `os.path.exists` / `platform.system`.

### T6 · P2 · A few StepGuard branches uncovered
The already-blocked `check()` path, `snapshot()` counters, the "record while
blocked is a no-op" early return, and the success-then-failure asymmetry (C4) are
not directly asserted. **Fix:** add targeted cases — especially one that pins the
intended success-then-failure contract.

---

## Axis 4 — Gaps vs the roadmap (before Sprint 2 is safe)

Sprint 1 is legitimately complete. The following must exist before the read-only
extractor and everything after it:

### G1 · P1 · StepGuard is not wired into any runnable stage
The guard exists and is tested, but `01_check_invariants.py` does not route its
probes through it and there is no executor loop calling `start_task` / `run_step`.
The core premise ("every stage runs through the StepGuard") is currently
unenforced by construction. **Fix:** wrap even the read-only checker's AKS + CDP
probes in `run_step` with deterministic `success_predicate`s, so Sprint 2 has a
working template and the guard is exercised end-to-end.

### G2 · P1 · No data contracts for extractor outputs
`EXECUTOR_RULES.md` §3 specifies raw-snapshot + normalized-offer JSON with fields
`id/name/url/storeId/price/stock`, `html.unescape` before `json.loads`, `&p=N`
pagination and dedupe-by-id — none of it exists as a dataclass/validator.
**Fix:** land `RawSnapshot` / `NormalizedOffer` dataclasses + stdlib validators
(no new deps) so the "≥0 offers extracted" success predicate has something to
validate against. (Recommend a `docs/DATA_CONTRACTS.md` next.)

### G3 · P1 · No JSONL run-log infrastructure
The roadmap lists "immutable JSONL run logs" but nothing persists structured
events; `StepGuard.snapshot()` is serializable but never written. **Fix:** a tiny
append-only JSONL logger under the gitignored `logs/`, persisting
`guard.snapshot()` per task, with a redaction policy (ties to C3 — never log
`webSocketDebuggerUrl` / cookies).

### G4 · P2 · Validation-file schema (Stage 3) not yet designed
`EXECUTOR_RULES.md` §5 requires exact candidate ids + `run_id` / `validated_by` /
`validated_at`, and "a previous 'oui' never authorizes a new batch." Design it
together with the guard: the validation file's `run_id` should map to the
StepGuard `task_id`. Highest-risk future component — flag the coupling now.

### G5 · P2 · No explicit seam for the future action-capable CDP
`websocket_url()` raises by design (correct for read-only). Sprint 4 will need a
controlled action client; there is no interface boundary yet that the guard +
validation file would drive. **Fix (later):** a thin "modal submit" port stub to
make the fail-closed boundary explicit; ensure Sprint 2 does not introduce a
WS/action path.

### G6 · P2 · Minor doc/skill drift
(a) the 200–399 vs 200/301/302 looseness (= C2); (b) the stale `audit.md` format
drift (= S2). The skill's matcher/edition/region tables (EXECUTOR_RULES §4/§10/§11)
are spec-only so far — expected at this stage, no code depends on them yet.

---

## Prioritized action plan

**Before Sprint 2 (P1):**
`C1` align HTTP method + timeout · `C2` tighten AKS status + redirect policy ·
`C3` redact headers/body & `webSocketDebuggerUrl` · `S1` expand `.gitignore` ·
`T1` add CI + secret scan · `T2`/`T3`/`T4` test the probe layer, `get_version`,
and the checker · `G1` wire StepGuard into the checker as the template ·
`G2` data contracts · `G3` JSONL logging.

**Debt (P2):** `C4` `C5` `C6` `S2` `S3` `T5` `T6` `G4` `G5` `G6`.

**None are P0** — nothing is unsafe as-is; the repo is read-only and fail-closed.

## Module verdicts
- `src/step_guard.py` — solid; only C4/C5 nits.
- `src/aks_env.py` — good pure validators; weak spots are the probe layer (C3, T2)
  and the loose status range (C2).
- `src/cdp_client.py` — clean, correctly refuses actions; undertested (T3), probes
  any `--endpoint` (C6).
- `scripts/01_check_invariants.py` — correct exit/authoritative semantics; needs
  guard wiring (G1), tests (T4), redaction (C3).
- `scripts/00_audit_env.sh` — read-only, well-guarded; method mismatch (C1) and
  config-excerpt leak (S3).
