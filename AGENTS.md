# AKS Controlled Executor — Codex instructions

## Mission

You are Codex CLI working as a builder, not as a free-form executor.

Your job is to build a deterministic AKS controlled executor.

You may:
- write scripts;
- write tests;
- audit logs;
- improve docs;
- run read-only diagnostics;
- propose implementation plans.

You must not:
- manually submit AKS offers through ad-hoc browser actions;
- improvise browser workflows;
- bypass validation;
- use Browserbase;
- use Playwright fallback;
- launch VPN;
- ask for 2FA in advance.

## Known infrastructure

Host Chrome CDP:
http://127.0.0.1:9222/json/version

Docker bridge CDP proxy:
http://172.17.0.1:9223/json/version

Official endpoint for code running from Docker bridge:
http://172.17.0.1:9223/json/version

Required User-Agent:
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36

AKS direct URL:
https://www.allkeyshop.com/blog/

## Forbidden

- Browserbase
- browser_navigate for AKS execution
- Playwright fallback
- VPN fallback when AKS direct works
- /root/start-chromium.sh
- random 0.0.0.x CDP checks
- submitting without explicit validation file
- submitting without modal context verification
- fire-and-forget submission
- using old candidates from memory
- using previous feed state
- asking for 2FA in advance
- changing process after Romain says "go"

## Required architecture

Build in stages:

1. Environment audit script.
2. Read-only feed extractor.
3. Read-only matcher.
4. Candidate report generator.
5. Validation file generator.
6. Submitter locked behind validation.
7. Post-save verifier.
8. JSONL logs for every action.
9. Dry-run mode by default.

## Fail-closed behavior

If anything is uncertain:
- stop;
- write an error report;
- do not fallback to another browser;
- do not continue to next candidate;
- do not submit.

## Submission constraints

The submitter must only process candidates from a validation JSON file.

For each candidate:
- refresh current merchant feed;
- locate exact current row;
- verify title, URL, price, page, merchant;
- open modal from that row;
- verify modal context;
- fill visible region/edition controls;
- click official visible submit button;
- refresh feed;
- verify post-save state.

No degraded mode.

## Coding preferences

- Python 3.
- Minimal dependencies.
- No new production dependency without asking Romain.
- Scripts must be CLI-friendly.
- Outputs should be JSON or JSONL where practical.
- Human reports go in Markdown.
- Never store passwords or 2FA codes.
- Never commit secrets.
