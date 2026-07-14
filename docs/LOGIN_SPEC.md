# LOGIN_SPEC.md — Stage 0b design

**Status: BUILT** (approved by Romain 2026-07-14, "ok, parfait, lances toi").
Option A from Romain's 2026-07-14 request ("que dois je changer pour que tu
puisse le faire toi même?"): a scripted login where the password never leaves
the environment and Romain still supplies the 2FA code live, every time. Not
Option B (a stored TOTP secret / fully autonomous login) — that removes the
human checkpoint on an account that can create live offers and directly
contradicts "never store passwords or 2FA codes." This doc only proposes A.

`SUBMITTER_SPEC.md` §8 already pre-agreed the shape of this the day it was
written: *"When/if login is authorized later, the rule stands: ask for a code
only when the `googleotp` field is visible and can be submitted immediately;
stop after two failures; never pre-request."* This spec is that later.

---

## 1. Purpose & non-negotiables

Authenticate the WP-admin session in the **official** CDP Chrome tab
(`172.17.0.1:9223`, host `9222`) — nothing else. Every other stage
(extractor, matcher, submitter) already assumes an authenticated session; this
stage is what produces one, on request, instead of Romain doing it by hand.

It **never**:
- stores the password, the 2FA code, or any cookie in a file, log, commit, or
  run artifact — both are read from the environment / stdin at run time only;
- requests a 2FA code before the `googleotp` (or equivalent) field is visible
  and ready to submit immediately — no pre-request, ever;
- retries a wrong password or a wrong 2FA code — **one attempt each**, then
  STOP (repeated failed logins can lock or flag the account; this is not a
  place to loop);
- uses Browserbase, `browser_navigate`, or any ad-hoc browser action — the
  official CDP endpoint only, same as every other stage;
- self-triggers. Login only runs on Romain's explicit go, same as `--submit`.
  A `NotLoggedInError` from the extractor/submitter stays a fail-closed STOP +
  error report (current behavior) — it must never auto-invoke this stage.

---

## 2. Preconditions (fail-closed gates — all before touching the login form)

1. Invariants **green AND authoritative** (`build_report`), same gate as every
   write-capable stage.
2. `AKS_WP_USER` and `AKS_WP_PASSWORD` present in the environment (not a CLI
   arg — args can leak into shell history / `ps`). Missing either → STOP
   before opening any session, distinct reason, no partial attempt.
3. Read-only probe first: is the CDP tab already on an authenticated
   WP-admin page? If yes, **no-op** — report `already_logged_in: true` and
   exit 0. Login is idempotent; it never re-submits credentials into an
   already-open dashboard.

---

## 3. The write-CDP boundary

Same pattern as the submitter (`SUBMITTER_SPEC.md` §3): a new, narrowly
scoped write session — `LoginSession` in `src/submit_session.py` or a
sibling module — exposing only what filling a login form needs, reusing the
**already-audited trusted-input primitives** from `WriteSubmitSession`
(`_type_text_trusted`, trusted click via `Input.dispatchMouseEvent`) rather
than inventing new browser-automation mechanics. No new class of risk is
introduced at the CDP layer — same `isTrusted:true` keystrokes/clicks already
proven on the submit path, pointed at a different form.

---

## 4. Per-step flow (in order; fail-closed at every step)

1. Read-only probe (§2.3): current URL / DOM already dashboard-shaped →
   no-op success.
2. Navigate the CDP tab to the WP login URL.
3. Verify the **username** and **password** fields are present by name/id
   before typing — an unreadable or unexpected login form → STOP
   (`LOGIN_FORM_UNREADABLE`), never guess a selector.
4. Trusted-type `AKS_WP_USER` into the username field, `AKS_WP_PASSWORD` into
   the password field (envvar values held in memory only, never
   interpolated into any log line or JS string that gets logged).
5. Trusted click on the login submit button.
6. Poll (bounded, short interval) for one of three outcomes:
   - the 2FA field (`googleotp` or equivalent) becomes visible → go to 7;
   - the dashboard loads directly (2FA not required this session) → go to 9;
   - an error message renders (bad username/password) → STOP
     (`LOGIN_REJECTED`), report it, no retry.
   - timeout with none of the above → STOP (`LOGIN_TIMEOUT`), no retry.
7. **2FA field visible and ready** → prompt Romain for the code (stdin,
   interactive; the process stays attached, same "never fire-and-forget"
   rule as submit) — **never before this point**.
8. Trusted-type the code, trusted click submit. Wrong code → STOP
   immediately (`2FA_REJECTED`) — do **not** ask for a second code in the
   same run (matches `SUBMITTER_SPEC.md` §8's pre-agreed "stop after two
   failures" as an outer bound; in practice this spec proposes stopping
   after the **first** wrong code, since a wrong 2FA code from a live TOTP
   is almost always a stale/mistyped one-shot, and looping invites lockout).
9. **Deterministic success proof** (§5) — never a self-assessment.

---

## 5. Deterministic success (the whole point, same philosophy as §5 of
`SUBMITTER_SPEC.md`)

Success = the CDP tab's current URL is under `/wp-admin/` **and** does not
contain a login/action-required query (`wp-login.php`, `action=login`,
`reauth=1`), **and** a known dashboard-only DOM marker is present (e.g. the
admin toolbar `#wpadminbar`). Both checks, not one — a URL check alone can be
fooled by a redirect loop; a DOM check alone can be fooled by a cached
partial page. Anything short of both → `LOGIN_UNVERIFIED`, not success.

---

## 6. Logging & reporting

- JSONL run log per step (`login_page_opened`, `credentials_filled`,
  `post_submit_state`, `2fa_field_visible`, `2fa_submitted`, `post_2fa_state`,
  `login_result`) with **boolean/structural facts only** — `credentials_filled`
  carries no value at all, never a password/code. Redaction is
  `src/run_log.py`'s existing `RunLogger`/`REDACT_KEYS` mechanism (it already
  redacts `password`, `otp`, `googleotp`, `2fa`, `token`, `secret` by key name)
  — no second redaction mechanism was needed.
- stdout: one JSON result object (`status`, `run_id`, and `aborted`/`reason`
  on failure). No separate report file — a single-attempt stage has nothing a
  JSONL log line + the stdout result don't already cover.

---

## 7. Decisions (Romain, 2026-07-14)

1. **Env var names** — `AKS_WP_USER` / `AKS_WP_PASSWORD`, no existing
   convention to match.
2. **Where they live** — a `.env` you source before running (already
   gitignored: `.env` / `.env.*`); `chmod 600` it. Not committed as an
   example file either — `.env.*` would gitignore any `.env.example` too, so
   the two names are documented here and in `README.md` instead.
3. **Retry-after-timeout** — any ambiguity STOPS outright; no bounded
   re-check. Consistent with the rest of the project's fail-closed posture.
4. **Session lifetime** — once per data-entry session, on explicit go, same
   cadence as logging in by hand today. Never a per-run auto-check-and-relogin.

---

## 8. Built files

- `src/login_session.py` — `LoginSession(WriteSubmitSession)` (thin CDP
  state-query/action primitives only) + `run_login(...)` (all sequencing/
  decision logic, fully unit-tested against a duck-typed fake session).
- `scripts/00b_login.py` — CLI: invariants gate, env-var gate, opens
  `LoginSession`, calls `run_login`, prints the JSON result.
- `tests/test_login_session.py` — 12 tests: already-logged-in no-op, happy
  path with/without 2FA, 2FA never requested before the field is visible,
  unreadable form, bad password (no retry), timeout, wrong 2FA code (no
  second attempt), empty code, `verify_dashboard` false after an apparent
  success, same-run-id second call is guard-blocked, no credential ever
  appears in a logged event.
- `AGENTS.md`: "ask for 2FA in advance" refined to the precise rule (only
  before the field is visible), pointing here; added a Stage 0b line.
- `SUBMITTER_SPEC.md` §8: points here instead of "out of scope."
- `README.md`: Roadmap entry, Safety line, Rules & docs link, `AKS_WP_USER`/
  `AKS_WP_PASSWORD` documented under Requirements.
