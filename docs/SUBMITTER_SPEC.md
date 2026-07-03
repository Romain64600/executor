# SUBMITTER_SPEC.md — Stage 4 design (for approval, no code yet)

**Status: PROPOSAL. Nothing here is built.** This is the design of the only stage
that *writes* to AKS. Per the project's fail-closed rule, it exists for Romain to
review and approve the approach + gates **before** any submit code is written. The
first implementation will be **dry-run only** (no real clicks).

Grounded in `EXECUTOR_RULES.md` §6/§7 and the skill's submitter rules
(`[S09]` `[S17]` `[S18]` and the DB-proof override).

---

## 1. Purpose & non-negotiables

Take the **approved** offers (`approved.json` from Stage 3 validation) and create
them in AKS through the feed UI modal — nothing else.

It **never**:
- submits without a valid `approved.json` for the exact current candidates;
- uses a direct `admin-ajax` XHR, `form.submit()`, or `dispatchEvent` `[S09]`;
- trusts `[data-success]` as proof `[S18]`;
- retries the same submission in a loop, switches browser/VPN, or continues after
  an interruption;
- logs in or requests a 2FA code (out of scope — see §8).

---

## 2. Preconditions (fail-closed gates — all must pass before ANY write)

1. Invariants **green AND authoritative** on the VPS (`build_report`), same gate as
   the extractor.
2. `approved.json` present, and it re-validates against the **current**
   `candidates.json` (Stage 3 `load_validation`, fingerprint-exact). A stale or
   mismatched approval → STOP.
3. Mode is explicit: `--dry-run` is the **default**; real writes require
   `--submit`. There is no implicit submit.
4. The WP session in the CDP Chrome is **already logged in** (the extractor's
   assumption). If the feed redirects to `wp-login.php` → STOP "not logged in"
   (login is a later, separately-authorized sprint).

If any gate fails: STOP, write an error report, submit nothing.

---

## 3. The write-CDP boundary (key architectural point)

`src/cdp_session.py` is **read-only** and refuses `.click(` / `setValue` on
purpose. Submitting requires real writes, so we introduce a **separate, narrowly
scoped** session used **only** in the submit path, only after §2 gates pass:

- proposed `src/submit_session.py: WriteCdpSession` exposing exactly three write
  ops — `click(selector)`, `selectize_set(select_name, value)`, and
  `read(expression)` (read-only eval for verification) — and nothing else.
- It is instantiated **only** inside the submitter, guarded by `--submit`. In
  `--dry-run` the submitter uses the **read-only** session and never constructs the
  write session at all.

This keeps the read-only guarantee intact everywhere else; the write capability
lives in one small, auditable place that can't be reached without the gates.

---

## 4. Per-candidate flow (in order; fail-closed at every step)

For each offer in `approved.json`, wrapped in `StepGuard.run_step` with signature
`submit:{offer_id}` and **`max_failures_per_signature = 1`** (no blind retry `[S15]`):

1. **Refresh** the merchant pending feed from scratch (feeds are dynamic).
2. **Locate the exact current row** by offer id; verify title, URL, price,
   merchant, page — must match the approved candidate. Mismatch → STOP.
3. Open the modal from that row's `[data-create-offer]` button → `#TB_window`.
4. **Verify modal context** (`#TB_ajaxContent` present).
5. **Verify the select names** before filling — they vary per feed
   (`offer[region]`/`offer[edition]` vs `offer[region_id]`/`offer[edition_id]`) `[S17]`.
6. **(dry-run stops here)** — report exactly what *would* be set/clicked; no write.
7. **(submit only)** Set region/edition via `selectize.setValue(...)` on the
   verified names — not `.value =`.
8. **(submit only)** Click `#TB_ajaxContent .button-primary` "Create offer" — the
   only valid trigger `[S09]`.
9. Close via `#TB_closeWindowButton`; pace **≥ 500 ms** before the next `[S03]`.
10. **Post-save verification (§5).**

---

## 5. Deterministic success (the whole point) `[S18]` `[DB-proof]`

After a submit, **reload the pending feed** (`window.location`) and check the offer
**disappeared** from pending.

```
success = (offer_id NOT in refreshed pending feed)
```

This boolean — not `[data-success]`, not a model judgment — is what is passed to
`StepGuard.record_result`. If the offer is still present → the submission **failed**:
STOP that candidate, do **not** re-loop, write an error report. Reporting wording:
"soumis via modale UI, confirmé post-save côté feed (disparue du pending)" — never
"créé en base".

---

## 6. StepGuard, anti-loop, stop conditions

- Each candidate: one attempt (`max_failures_per_signature = 1`). A failure blocks
  that signature; the run stops for that offer.
- A second failure anywhere, or login/2FA/CDP failing twice → **STOP** the whole
  run, short diagnosis, wait for Romain `[S15]`.
- A new instruction / interruption cancels the run (new `task_id`); leftover
  approved offers are **not** auto-submitted.

---

## 7. Dry-run (the first thing I'll build)

`--dry-run` (default) runs steps 1–6 for every approved offer using the
**read-only** session: refresh, locate row, verify identity, open modal, verify
context + select names, and report — per offer — exactly what it *would* set
(region id, edition id) and click, plus any blocker found. **Zero writes.** Output:
`runs/<run_id>/submit_plan.json` + a normalized-text report. This lets us validate
the whole mechanism against the live feed with no risk before enabling `--submit`.

---

## 8. Login / 2FA — explicitly out of scope

The submitter assumes an already-authenticated WP session (like the extractor). It
will **never** request a 2FA code or automate login in this sprint. When/if login
is authorized later, the rule stands: ask for a code only when the `googleotp`
field is visible and can be submitted immediately; stop after two failures; never
pre-request `[I18]`.

---

## 9. Logging & reporting

- JSONL run log per candidate: `submit_attempt` (dry-run/submit), `post_save`
  (gone/still-present), plus the guard snapshot. Never log cookies / 2FA /
  `webSocketDebuggerUrl` (the `run_log` redaction already covers this).
- Final report: structured text, no tables; per offer, what happened and the
  post-save result.

---

## 10. Proposed files (built only after you approve)

- `src/submit_session.py` — the narrowly-scoped `WriteCdpSession` (§3).
- `src/submitter.py` — the per-candidate flow (§4–§6), dry-run + submit, pure
  orchestration testable with a fake session.
- `scripts/05_submit.py` — CLI, `--dry-run` default, `--submit` explicit; requires
  `approved.json`; enforces §2 gates.
- `tests/test_submitter.py` — flow, gates, success determination, dry-run-vs-submit,
  anti-loop — all with a fake session (the live write path runs on the VPS).

---

## 11. Open questions for you

1. **Dry-run depth:** should dry-run actually *open* each modal (read-only, to
   verify context + select names live), or stop at "row located + would open"?
   Opening is a better rehearsal but touches the UI (still no write).
2. **Batch size / pacing:** submit all approved at once (≥500 ms apart), or a hard
   cap per run (e.g. 10) with a pause?
3. **On first failure:** stop the entire run (strictest), or skip that one offer and
   continue the rest? The skill leans "stop and diagnose" — I propose **stop**.
4. **Merchant login check:** is the CDP Chrome reliably logged into WP when you run
   this, or do we need a pre-flight "am I logged in?" read (redirect to wp-login →
   abort)? I propose the pre-flight.

Tell me your calls on §11 (and any change to the gates), and I'll build the
**dry-run** submitter first.
