# Sprint 1 Plan

## Goal

Build the first read-only foundation for the AKS Controlled Executor:

- invariant checks for AKS direct access, CDP endpoint, and required User-Agent;
- a minimal CDP helper limited to `/json/version` metadata;
- a CLI checker that emits JSON and fails closed;
- pure tests for parsing and validation only.

## Target runtime

The production runtime target is a Debian VPS.

Local macOS development is allowed for scaffolding, unit tests, and pure parsing work, but local macOS audit failures for Debian-specific tools are not automatically production failures. Examples:

- `systemctl` checks are meaningful on Debian, not necessarily on macOS;
- `ss` is expected on Debian and may be absent locally;
- `/home/debian/.hermes/config.yaml` is a Debian runtime path;
- `172.17.0.1:9223` is the official Docker bridge CDP endpoint for the target runtime.

## Sprint 1 scope

In scope:

- `src/aks_env.py` for constants, pure validators, and read-only HTTP probes;
- `src/cdp_client.py` for a read-only CDP `/json/version` helper skeleton;
- `scripts/01_check_invariants.py` for JSON invariant reports;
- tests for pure parsing and validation functions;
- documentation of the Debian target assumption.

Out of scope:

- submitter;
- modal interaction;
- login automation;
- 2FA handling;
- Browserbase;
- Playwright fallback;
- VPN fallback;
- any browser write action;
- any ad-hoc AKS browser action.

## Fail-closed rules

The Sprint 1 checker exits non-zero if any required invariant fails:

- AKS direct URL is not reachable with an HTTP 2xx or 3xx status;
- the CDP endpoint is not exactly `http://172.17.0.1:9223/json/version`;
- `/json/version` is unreachable or malformed;
- `/json/version` does not expose `Browser`, `User-Agent`, and `webSocketDebuggerUrl`;
- the User-Agent is not exactly the required Chrome 149 Linux value.

No fallback endpoint is attempted. No browser action is attempted.

## Next sprint candidate

Sprint 2 can add a read-only feed extractor skeleton after the Debian runtime invariants are green. The extractor should still avoid submission, login automation, modal interaction, and any state mutation.
