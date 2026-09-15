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
2b. **Re-verify the row on the FRESH render** (audit 2026-07-17, SC5): the
   modal-opening navigate produces a NEW page load, minutes after the index
   scan — the row must still be there under that id AND still match the
   candidate (name, URL path; `check_price=False`). A vanished row or an id
   reused by a mid-run re-import → STOP that candidate (blocker), never open
   a modal on an unverified row.
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
   **The post-pick readback is COMPARED to the target id** (audit 2026-07-17,
   SC3): both channels (`select.value` + `selectize.getValue()`) must equal the
   wanted id, else the pick fails `WRONG_VALUE` (a trusted click can land on a
   neighbouring option and every later gate would still pass — the form is
   valid with ANY option). An unreadable readback fails `READBACK_UNREADABLE`.
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
3b. **Pre-click value-drift gate** (audit 2026-07-17, SC3): immediately before
   the Create click, BOTH selects are read back one last time and must still
   hold their target ids — anything between the verified picks and the click
   (target typing, scrolls, a stray dropdown) could have changed a value with
   the form staying valid. A mismatch fails `VALUE_DRIFTED_BEFORE_CLICK`, no
   click.
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

> **§4b step 2 is the `targets_v1` shape only.** Since the AKS feed-tool change
> of 2026-09-14 the live modal is `targets_v2` (§4c) and `offer[targets][]` no
> longer exists; the chip-field flow is kept as the old fallback, **minus its
> trusted-Enter commit** (an Enter in this form submits it natively — removed,
> `NO_ADD_BUTTON` fails closed instead).

---

## 4c. Modal v2 (2026-09-14): targets per row

Romain changed the AKS feed tool on 2026-09-14: the "Create offer" modal now takes
**region and edition PER TARGET PAGE**. Observed read-only by `scripts/05_submit.py
--inspect` (run `20260914-inspect-consoles`, 3 plan entries — the DOM facts below
come from `inspection.form_inputs`, `inspection.modal_selects`,
`targets_probe.targets`, `form_validity`, `select_names`) and **confirmed by hand
by Romain on 2026-09-14** (three confirmations, cited where they apply).

### Observed DOM

- **Global selects, unchanged:** `select[name="offer[region]"]` and
  `select[name="offer[edition]"]` — Selectize, `required` through Selectize's own
  text input (the two unnamed `selectize-input items required invalid` inputs).
  Hidden prefilled `offer[merchant]` (number) and `offer[buy_url]` (url).
- **Target row 0 (NEW):**
  - `input[name="offer[targets][0][target]"]` — `type=text`, **required**,
    `pattern="(\d+)|(https?://.+)"`, attribute `data-target-input`, visible;
    its **next sibling is `button.button[data-remove-target]` — the row's REMOVE
    button** (text "×"; `type=button`). **Canary 2 (2026-09-15, run
    `20260914-canary-two-targets`, NBA 2K25 Xbox One + Series) proved it:** the
    first locator clicked that sibling as "add-row", nothing was added (1 row read
    back → `TARGET_ROW_NOT_ADDED`, no write). The real **add button lives
    elsewhere in the form** — markup UNVERIFIED (most likely `data-add-target`
    by the tool's naming; read `inspection.modal_buttons` on the next
    `--inspect`);
  - `select[name="offer[targets][0][region]"]` — Selectize,
    `data-target-override="region"`, **not** required;
  - `select[name="offer[targets][0][edition]"]` — Selectize,
    `data-target-override="edition"`, **not** required.
- The old `input[name="offer[targets][]"]` **no longer exists**.
- **Create button, unchanged:** `div#TB_window > div#TB_ajaxContent > div > form >
  div.modal-choices > button.modal-choice.button.button-primary`
  (`data-action-submit`, text "Create offer").
- **The `<form>` has `method=get` and no `action`.** Pressing **Enter** inside one
  of its text inputs would **submit the form natively = an uncontrolled write**.
  No method of `submit_session.py` presses Enter in the modal any more
  (`_press_enter` deleted; v1's Enter commit fallback → `NO_ADD_BUTTON`).
- `select_names` now read `['offer[edition]', 'offer[region]',
  'offer[targets][0][edition]', 'offer[targets][0][region]']` — `_prepare`'s
  preference for `offer[region]` / `offer[edition]` still holds.

**Romain's confirmations (2026-09-14):**
1. a button of the row block **adds a new target row** (works by hand) — canary
   2 (2026-09-15) showed the one **next to** the input is the REMOVE button, so
   the add button is located by the §4c locator rule below; the code still
   **proves** row *i* exists after the click (readback), never assumes it, and
   a row count that went DOWN is `ROW_REMOVED`;
2. **empty per-target region/edition inherit** the global `offer[region]` /
   `offer[edition]` (tested by him) — the overrides are nevertheless **always set
   explicitly** on every row; inheritance is never relied on;
3. the modal takes **"3 ou 4 pour le moment"** targets — the submitter enforces a
   hard cap **`MAX_TARGETS_PER_OFFER = 3`** per candidate (`src/submitter.py`).

### Shape detection (read-only, every modal)

`SubmitSession.modal_context()` (`_MODAL_CTX_JS`) reports `modal_shape`:
`targets_v2` when row 0's three controls all exist in `#TB_ajaxContent`,
`targets_v1` when `input[name="offer[targets][]"]` exists, else `unknown`
(`modal_shape_detail` says which probes hit). `_prepare` stores it on the plan
entry (`entry["modal_shape"]`) and gates on it **after** the read-only checks and
the catalog resolution, **before** any write:

- `unknown` → blocker **`modal_shape_unknown`** for **every** entry (nothing is
  filled; message « la forme du modal Create offer n'est ni targets_v1 ni
  targets_v2 — rien n'est saisi (fail-closed) ; --inspect pour observer le DOM »).
  A **real** blocker: it feeds the StepGuard streak, so a changed tool stops a
  sweep after 10 entries. `--inspect` still dumps such an entry's modal.
- `targets_v1` + more than one target → the R45 blocker
  `multi_target_unsupported_until_modal_verified` (unchanged message; a designed
  skip, `gated_multi_target`).
- `targets_v2` → **ready** once every target's region/edition resolved in the
  live catalog (`_resolve_from_catalog`, per target; the per-target `*_text` is
  the Selectize query, BOM-stripped). Single-target candidates (every PC offer)
  follow the same v2 path with one row — **the only working path since the tool
  change**.
- more than `MAX_TARGETS_PER_OFFER` targets → blocker **`too_many_targets`**
  (message « plus de 3 cibles — plafond du modal AKS (Romain 2026-09-14) »),
  set **before** the row is located or its modal opened; a designed skip
  (`gated_too_many_targets`, no guard streak).

Dry-run `would_submit` for v2 lists the rows: `set offer[region]=…,
offer[edition]=…, targets_v2 rows [row 0: target=<id> region=<id>
edition=<id>; row 1: …], click .button-primary (NOT clicked — dry-run)`.

### Fill order (`WriteSubmitSession.fill_targets_v2_trusted`, trusted CDP only)

0. Read-only shape check on the open modal → `MODAL_SHAPE_MISMATCH` if it does
   not read `targets_v2`; an empty target list → `NO_TARGETS`.
1. Prep JS (network taps + pre-existing signal snapshot; NO fill).
2. **Global `offer[region]` / `offer[edition]`** via `select_via_trusted` with the
   **primary** (first) target's ids and typed catalog text — SC3 readback inside
   → `NO_REGION_PICK` / `NO_EDITION_PICK`.
3. **Row 0** (`_fill_target_row_trusted`): trusted focus click on
   `input[name="offer[targets][0][target]"]` (`NO_TARGET_INPUT`),
   `Input.insertText(aks_product_id)` — **no add-row click, no Enter** — readback:
   the row's target value must **equal** the id (`TARGET_VALUE_MISMATCH`; an
   empty id is never guessed: `NO_TARGET_ID`); then the two overrides
   **explicitly**: `select_via_trusted("offer[targets][0][region]", region_id,
   query=text)` and `…[edition]` → `NO_ROW_REGION_PICK` / `NO_ROW_EDITION_PICK`.
4. **Each extra target *i* ≥ 1** (`_add_target_row_trusted(i)`):
   - **readback BEFORE anything**: exactly *i* rows must exist
     (`TARGETS_COUNT_MISMATCH`; unreadable → `TARGETS_READBACK_UNREADABLE`) —
     `add.rows_before`;
   - **add-button locator** (`_ADD_ROW_BUTTON_PROBE_JS`, read-only, rewritten
     2026-09-15 after canary 2 — **never by DOM relation to the input any more**):
     1. **never** an element carrying `data-remove-target` (the JS excludes it
        AND `_add_button_refusal` refuses it again on the Python side);
     2. `#TB_ajaxContent form [data-add-target]` (`<button>` or `<a>`) — exactly
        one → chosen, `add_button.matched_by = "[data-add-target]"`; several →
        `NO_ADD_BUTTON` (`ambiguous_add_button`);
     3. otherwise the fallback: every `<button>` of the form whose `type`
        property is `button`, not `[data-remove-target]`, not submit-like, whose
        **data-\* attribute names or text match `/add|ajout|plus|\+/i`** —
        chosen **only when exactly one** exists (`matched_by =
        "fallback:data-attr:<name>"` / `"fallback:text"`); 0 → `NO_ADD_BUTTON`
        (`no_add_button_candidate`), >1 → `NO_ADD_BUTTON` (`ambiguous_add_button`).
        Every `<button>` considered is listed in `add_button.candidates` with its
        `rejected` reason (`remove` / `submit_like` / `not_addish`) so the plan
        explains itself without a new `--inspect`;
   - the chosen element must **not be submit-like** — `<button>` with `type` ≠
     `button`, an `<a>` whose `href` navigates, `data-action-submit`,
     `button-primary` → `ADD_BUTTON_UNSAFE`, not clicked (a submit-type click
     would natively submit the form); it must still follow row *i-1* exactly
     (`NO_ADD_BUTTON`); after a scroll it must be re-found with the same
     `matched_by`;
   - trusted click, then a **readback AFTER**: **fewer rows than before →
     `ROW_REMOVED`** (the click was a remove — the flow stops, cleanup, no Create
     click; defence in depth over the locator); more than *i+1* rows →
     `TARGETS_COUNT_MISMATCH`; row *i* absent or without its target input **and
     both** override selects → `TARGET_ROW_NOT_ADDED`. Then row *i* is filled
     like row 0.
5. `form_validity()` hard gate (`FORM_INVALID` / `FORM_VALIDITY_UNREADABLE`),
   pre-click obstruction probe (`CLICK_PATH_OBSTRUCTED`).
6. **Last gate before the click — full readback** (`pre_click_readback`): both
   global selects (`select.value`) **and every row** — target value, region and
   edition override through both channels (`select.value` +
   `selectize.getValue()`) — must still equal the wanted ids →
   `VALUE_DRIFTED_BEFORE_CLICK` (reason names the row and field); the row count
   must equal `len(targets)` → `TARGETS_COUNT_MISMATCH`.
7. ONE trusted click on "Create offer" (`NO_TRUSTED_CLICK`), poll
   (`SUCCESS` / `ERROR` / `NO_SIGNAL`).

Every failure cleans the taps up and returns **without clicking** — "never a
partial console entry": either every row is proven filled or nothing is created.
Post-save (§5) remains the **only** success proof; `Submitter._process` treats
any status outside `SUCCESS` / `NO_SIGNAL` as `create not confirmed: <STATUS> —
<reason>`.

### Statuses added on 2026-09-14

Session (`create.status`): `MODAL_SHAPE_MISMATCH`, `NO_TARGETS`, `NO_TARGET_ID`,
`NO_TARGET_INPUT`, `TARGET_VALUE_MISMATCH`, `NO_ROW_REGION_PICK`,
`NO_ROW_EDITION_PICK`, `NO_ADD_BUTTON` (v1 and v2), `ADD_BUTTON_UNSAFE`,
`TARGET_ROW_NOT_ADDED`, `TARGETS_COUNT_MISMATCH`, `TARGETS_READBACK_UNREADABLE`;
row-level `ROW_ADDED` / `ROW_FILLED`; `VALUE_DRIFTED_BEFORE_CLICK` generalised to
the rows. Plan blockers: `modal_shape_unknown`, `too_many_targets`. Run result:
`gated_too_many_targets` (next to `gated_multi_target`).

**Added 2026-09-15 (canary 2):** `ROW_REMOVED` (`create.status` and row-level
`add.status`). The add-row statuses, precisely:

| status | meaning | clicked? |
|---|---|---|
| `NO_ADD_BUTTON` | no unique add button (`no_add_button_candidate` / `ambiguous_add_button`), the candidate carries `data-remove-target`, is not a `<button>`/`<a>`, the rows moved, or it was not re-found after a scroll | no |
| `ADD_BUTTON_UNSAFE` | the unique candidate is submit-like (`type` ≠ `button`, navigating `<a>`, `data-action-submit`, `button-primary`) | no |
| `ROW_REMOVED` | the click made the row count go DOWN (the located button removed a row) | add only — never Create |
| `TARGET_ROW_NOT_ADDED` | the click left row *i* absent or incomplete (canary 2's outcome with the sibling remove button) | add only — never Create |

### Verified live (2026-09-15)

- **Canary 1** (Legend of Mana, Switch, MMOGA) → **created** (offer 101039824 on
  page 64915, 99 €, signal « Offer created for locale en_EU and merchant 40 »):
  the single-row v2 path (globals + row 0 + explicit overrides + one Create click)
  works end to end.
- **Canary 2** (NBA 2K25 Xbox One + Series, two targets) → **failed closed**
  `TARGET_ROW_NOT_ADDED`: the sibling `<button>` of the target input is
  `button.button[data-remove-target]` ("×", `type=button`); its click added nothing
  (1 row read back), nothing was written. The locator is rewritten (above).

### UNVERIFIED live (the code fails closed on each)

- the **real add button's markup**: `[data-add-target]` is an inference from the
  tool's naming; if it is absent, the fallback needs a UNIQUE add-ish
  `<button type=button>` — otherwise `NO_ADD_BUTTON` with the `candidates` list.
  Run `--inspect` on a multi-target candidate and read
  `inspection.modal_buttons` before the next multi-target write;
- the add button's `type`: a type-less `<button>` inside a form is a submit
  button → refused (`ADD_BUTTON_UNSAFE`); `modal_buttons[].type_prop` shows it;
- whether the appended rows (and their remove buttons) change the button set
  (the locator re-runs before every extra row; ambiguity → `NO_ADD_BUTTON`);
- the inheritance of empty overrides (confirmed by Romain) is **never used** —
  every row's overrides are set and read back.

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

**"Gone" requires a POSITIVELY complete, readable walk (audit 2026-07-17,
FC1/SC1/SC2/SC4/SC6).** Absence of data is not absence of the offer. The
verify scan (and the batch-start index) now prove their own coverage:

- a **CDP timeout or protocol error raises** (`CdpCommandError`) instead of
  flowing through as "0 rows" (`src/cdp_session.py`); `Page.navigate`'s
  `errorText` is checked;
- a **blank page** is re-fetched once, then only two blank states are
  accepted — past-the-end (feed UI + nav advertising fewer pages) or an empty
  queue on page 1 (feed UI, no pagination) — anything else raises
  `FeedScanError` (the extractor's `EmptyPageAnomaly` discipline, carried
  over via `SubmitSession.feed_page_state()`);
- a **login bounce mid-scan** raises `NotLoggedInError`;
- the browser's `location.href` must match the page navigated to (a wedged
  tab re-serving the previous DOM is detected, not re-read as fresh pages);
- exhausting `max_pages` while the feed's own nav advertises **more** pages
  raises instead of silently truncating coverage.

Mid-batch, any of these marks the current offer
`post_save = "… offer state UNKNOWN, verify it by hand …"` (the attempt is
counted, the creation is NOT), stops the run with
`stopped="feed_unreadable"`, and still writes `submit_plan.json` + logs. At
batch start they abort with `aborted="feed_unreadable"` before any write.

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

## 8. Session re-auth — a separate path, see `LOGIN_SPEC.md`

The submitter itself still assumes an already-authenticated WP session (like the
extractor) and never automates login inline — that stays out of scope *for this
stage*. Re-auth is **cookie transfer** only (`docs/LOGIN_SPEC.md`,
`src/admin/login_manager.py`, `src/login_session.py`, 2026-07-29): AKS is
social-login only, so the old password+2FA Stage 0b was retired. The operator
pastes WP session cookies into `/executor/tri` → Se reconnecter; never
self-triggered by another stage's `NotLoggedInError`.

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
