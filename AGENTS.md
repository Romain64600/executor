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
- self-trigger or automate the session re-auth (AKS is social-login only now,
  so re-auth is COOKIE TRANSFER — `docs/LOGIN_SPEC.md`,
  `src/admin/login_manager.py` — driven only by Romain's explicit submit in
  the console; a `NotLoggedInError` from another stage stays a fail-closed STOP,
  never a re-auth trigger).

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
- self-triggering the session re-auth (cookie transfer, `docs/LOGIN_SPEC.md` —
  Romain's explicit submit in the console only)
- changing process after Romain says "go"

## Required architecture

The deterministic, per-stage rules (extractor, matcher, submitter, post-save
verification, reporting) derived from the `aks-data-entry` skill are specified in
`docs/EXECUTOR_RULES.md`. Read and follow it when implementing any stage; it is
the authoritative bridge between the skill and this code.

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

Session re-auth (`docs/LOGIN_SPEC.md`, `src/admin/login_manager.py`): AKS
disabled password login (social/OAuth only), so re-auth is COOKIE TRANSFER —
Romain completes the social login in his own browser and pastes the WP session
cookies into the console, which injects them (official CDP only) and proves the
session. The one flow that touches session secrets: cookie VALUES are never
logged/echoed/stored, injection is restricted to `allkeyshop.com`, Romain's
explicit submit only. Never self-triggered: a `NotLoggedInError` from another
stage stays a fail-closed STOP + error report.

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
- verify title, URL, merchant/store (price is a routing signal, never a
  blocker after URL/store confirm; page is recomputed by the current scan —
  EXECUTOR_RULES §6);
- open modal from that row;
- verify modal context;
- fill visible region/edition controls;
- click official visible submit button;
- refresh feed;
- verify post-save state: success = the offer disappeared from the refreshed
  feed, same available mode as the run.

No degraded mode.

## Coding preferences

- Python 3.
- Minimal dependencies.
- No new production dependency without asking Romain.
- Scripts must be CLI-friendly.
- Outputs should be JSON or JSONL where practical.
- Human reports go in Markdown.
- Never store passwords, 2FA codes, or session cookies.
- Never commit secrets.

## Reviewed decisions — do NOT re-tighten (an audit will re-flag these)

These are deliberate, Romain-reviewed calls. An adversarial audit re-derives them as
"findings" every time; leave them AS-IS unless Romain explicitly changes his mind.

- **Software region catch-all (`resolve_software_region`, Fable finding [7], DECLINED
  2026-09-07).** When an AKS software page has a SINGLE region and it is a
  GLOBAL/PUBLISHER-type bucket, a merchant offer is filed under it even when the offer's
  own region label looks US/EU-locked. Rationale: software licences are global and the
  merchant region label is usually noise (R31, 2026-08-11 — locked by
  `test_region_lone_country_is_not_forced`). Romain reviewed the audit finding that wanted
  to fail-close this and said "laisse [7] tel quel, ne durcis pas". A GLOBAL offer under a
  lone COUNTRY region still skips (unchanged); only the lone GLOBAL/PUBLISHER catch-all is
  kept. Do not add a US/EU-locked refusal here.

- **R25 duplicate guard REMOVED — do NOT re-add (Romain 2026-09-08).** The matcher used
  to skip a candidate whose merchant already had a price on the AKS page for the resolved
  region/edition ("`<merchant>` already lists a price … (R25)", added 2026-07-15 vs stale
  matched batches). Romain's ruling: **a PENDING offer is TO BE ADDED, period** — we do
  not check "already on AKS". The old guard matched by `merchantName`, so an AKS auto-sync
  / other-channel price (page merchant id ≠ feed `store_id`) false-skipped genuinely new
  offers; staleness is now covered by the stable pending feed + submit-time prove-gone. An
  audit will "find" the missing duplicate guard — leave it removed (EXECUTOR_RULES §6
  "Duplicate guard [R25] — RETIRED").

- **R18 "DLC bucket on the page ⇒ edition DLC(16)" for MARKERLESS titles — KEPT (Romain
  2026-09-11).** The R43 adversarial review showed live base-game pages carrying bucket 16
  (Stray Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake were entered DLC(16) on
  2026-09-10) and no deterministic page-level nature signal exists. Romain's ruling: "des
  fois, les titres n'ont pas de marqueur et sont des DLC" — the bucket keeps deciding, the
  three entries are not corrected. An audit will "find" this as a wrong-edition risk — leave
  R18 as is. (Titles that DO carry a DLC / Season Pass marker are governed by R43's stricter
  own-page + unnamed-DLC rules — those are not the same decision.)

