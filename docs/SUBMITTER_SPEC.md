# SUBMITTER_SPEC.md — Stage 4 design (for approval, no code yet)

**Status: BUILT & LIVE-PROVEN** (approved by Romain; dry-run validated end-to-end
on the VPS first, then the real write path added with a canary default of 1;
**first live submissions confirmed 2026-07-06** — see §4b. **Canary-of-1 default
removed 2026-07-13** (R23b, Romain): a submit run only ever processes an
already-validated `approved.json`, so validation is the safety gate and the full
batch is now the default; `--limit N` still narrows it explicitly). This is the
design of the only stage that *writes* to AKS. See `CHANGELOG.md` for the build +
resolution entries.

Grounded in `EXECUTOR_RULES.md` §6/§7 and the skill's submitter rules
(`[S09]` `[S17]` `[S18]` and the DB-proof override).

> **§4.7–§4.8 below describe the ORIGINAL (`setValue` + native `.button-primary`)
> mechanism, which is SUPERSEDED.** It produced `isTrusted:false` events that
> Driffle's handler ignores, and left `offer[targets][]` empty so HTML5 form
> validation blocked the submit. The real, live-proven mechanism (trusted Selectize
> picks + `offer[targets][]` fill + HTML5 validity gate + trusted click) is in
> **§4b**.

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

1. **Refresh** the merchant feed from scratch (feeds are dynamic; same
   `available` mode as the run).
2. **Locate the exact current row** by offer id — full row check (name, URL
   path; store/price when both sides carry values); a by-id mismatch falls
   back to the **merchant URL path** identity (`check_price=False`): price is
   a routing signal, never a blocker, and page is recomputed by the current
   scan (EXECUTOR_RULES §6). No row by either key, or a store contradiction →
   STOP.
3. Open the modal from that row's `[data-create-offer]` button → `#TB_window`.
4. **Verify modal context** (`#TB_ajaxContent` present).
5. **Verify the select names** before filling — they vary per feed
   (`offer[region]`/`offer[edition]` vs `offer[region_id]`/`offer[edition_id]`) `[S17]`.
6. **(dry-run stops here)** — report exactly what *would* be set/clicked; no write.
7. **(submit only — SUPERSEDED, see §4b)** ~~Set region/edition via
   `selectize.setValue(...)`~~ → trusted Selectize picks + fill `offer[targets][]`
   + HTML5 validity gate.
8. **(submit only — SUPERSEDED, see §4b)** ~~Click `.button-primary` via
   `.click()`~~ → **trusted** CDP click (`isTrusted:true`) on "Create offer" `[S09]`.
9. Close via `#TB_closeWindowButton`; pace **≥ 500 ms** before the next `[S03]`.
10. **Post-save verification (§5).**

---

## 4b. The real write mechanism (S18 RESOLVED, live-proven 2026-07-06)

Steps 7–8 above are **superseded**. The working submit path (`WriteSubmitSession.
fill_then_click_trusted`, `--click-mode trusted` which is now the default) is:

1. **Trusted Selectize picks for region + edition** (`select_via_trusted`): a CDP
   `Input.dispatchMouseEvent` (`isTrusted:true`) on the `.selectize-input` to open
   the dropdown, then a trusted click on the `[data-value="{id}"]` option. If the
   wanted id is **not rendered** in the product-scoped dropdown the pick returns
   `NO_OPTION` and fails closed — there is **no `addItem` fallback** (`addItem`
   reads the generic master catalog; forcing it created 3 wrong-edition offers
   on 2026-07-06). `setValue()` is **not** used — it produces `isTrusted:false`
   and leaves Selectize's own `required` text input empty.
2. **Fill `offer[targets][]`** (`add_target_trusted`) — the missing piece.
   `offer[targets][]` is a bare `<input type="text" required
   pattern="(\d+)|(https?://.+)">` with a sibling add-button (chip/array field).
   Trusted click to focus → `Input.insertText` types the **`aks_product_id`**
   (numeric, matches `\d+`) → commit via the **adjacent add-button** (trusted
   click), with a trusted-Enter (keyCode 13) fallback. Readback confirms
   `valid:true`.
3. **HTML5 validity gate** (`form_validity()`) — a **hard gate**. With region,
   edition, and target filled, the `<form>` goes valid (`form_valid:true,
   invalid_required:[]`). If it is still invalid, the submitter returns a
   deterministic `FORM_INVALID` verdict and does **not** click. This is why the
   old path silently fired zero admin-ajax: three `required` fields
   (`offer[targets][]` + the two Selectize text inputs) were empty, so the browser
   refused to dispatch the `submit` event.
4. **Trusted click on "Create offer"** — drives the modal's **own**
   `admin-ajax …do=create_offer`. We never issue a direct XHR (the merchant id is
   auto-assigned by the modal — a direct XHR would use the wrong one `[S09]`); the
   admin-ajax `200` + server signal `"Offer created for locale …"` are observed as
   **corroborating** signals only. Authoritative proof stays §5 (gone from the refreshed feed).

**Live proof (2026-07-06):** Demigod canary (offer 93185190, Steam EU(9)/Standard)
+ 3 batch creations (Gambonanza, Hello Neighbor 2, Heart of the Machine) — all
`target_add=ADDED`, `form_valid=true`, `create_offer 200`, gone from the
refreshed feed.

**Layer 5 (known, expected):** some bundle / non-Standard offers reject
server-side — `create_offer` returns `Bad request: paramètre "offer" manquant ou
invalide` **even when the form is valid** (seen on Serious Sam HD Double Pack,
GLOBAL/Bundle). Fail-closed handles it: `status=ERROR` → not submitted, no false
success, batch continues. Not a regression.

---

## 5. Deterministic success (the whole point) `[S18]` `[DB-proof]`

After a submit, **reload the feed** (`window.location`), in the **same
`available` mode the run scans**, and check the offer **disappeared**.

```
success = (offer NOT in the refreshed feed — same available mode as the run)
```

This boolean — not `[data-success]`, not a model judgment — is what is passed to
`StepGuard.record_result`. If the offer is still present → the submission **failed**:
STOP that candidate, do **not** re-loop, write an error report. Reporting wording:
"soumis via modale UI, confirmé post-save côté feed (disparue du feed
rafraîchi, même available que le run)" — never
"créé en base".

---

## 6. StepGuard, anti-loop, stop conditions

- Each candidate: **one attempt** — never retry the same offer.
- On a per-offer failure: **log it, skip that offer, continue** with the rest.
- **Stop the whole run after 10 consecutive failures** (a success resets the
  streak). StepGuard config: `max_attempts_per_signature=1`,
  `max_failures_per_signature=2` (so one per-offer failure does not global-block),
  `max_consecutive_failures=10`, and `max_failures_per_task` disabled (so only the
  "10 in a row" rule stops the run, not a cumulative budget).
- A new instruction / interruption cancels the run (new `task_id`); leftover
  approved offers are **not** auto-submitted `[S15]`.
- **Batch size = the data-entry mode `[R23b]` → `[R24]` (2026-07-13, Romain):**
  once the normalized report is validated we submit, and `--mode` sets the batch:
  - `safe` (**default**) — the **full validated batch, no canary**: validation
    (`approved.json`) already is the safety gate for which offers submit.
  - `learning` — exploring one (category × merchant) unlock. It **does write**
    ("il ajoute les offres si le rapport normalisé est valide"), but is capped
    at a **canary of 1** for now.
  - `advanced` — validated unlocks; same canary cap for now.

  In the canary modes the cap is enforced, not merely defaulted: `--limit N`
  narrows it, never widens it (a wider `--limit` exits 2). The per-offer and
  10-consecutive-failure stop conditions above are unchanged and remain the
  actual safety net during a run.

---

## 7. Dry-run (the first thing I'll build)

`--dry-run` (default) runs steps 1–6 for every approved offer using the
**read-only** session: refresh, locate row, verify identity, open modal, verify
context + select names, and report — per offer — exactly what it *would* set
(region id, edition id) and click, plus any blocker found. **Zero writes.** Output:
`runs/<run_id>/submit_plan.json` + a normalized-text report. This lets us validate
the whole mechanism against the live feed with no risk before enabling `--submit`.

---

## 8. Login / 2FA — a separate stage, see `LOGIN_SPEC.md`

The submitter itself still assumes an already-authenticated WP session (like the
extractor) and never requests a 2FA code or automates login inline — that stays
out of scope *for this stage*. Login is now built as its own stage
(`docs/LOGIN_SPEC.md`, `src/login_session.py`, `scripts/00b_login.py`,
2026-07-14, Romain Option A): a code is requested only when the 2FA field is
visible and ready to submit immediately, one attempt each for the password and
the code, never a retry loop, never self-triggered by another stage's
`NotLoggedInError`.

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

## 11. Decisions (Romain, 2026-07-02)

1. **Dry-run opens each modal** — full read-only rehearsal (verify context + select
   names live), no fill, no create.
2. **No batch cap for now** — process all approved offers, ≥500 ms apart.
3. **On failure: log + skip that offer + continue.** Stop the whole run only after
   **10 consecutive failures** (§6).
4. **Pre-flight login check: yes** — redirect to `wp-login` → abort "not logged in".

Build order: **dry-run only** first. In that build, the create capability does not
exist — the session can open a modal and read, but has **no method** that fills or
clicks "Create offer". The real write path is a separate, explicitly-authorized
build.
