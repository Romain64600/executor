# Changelog — AKS Controlled Executor

Notable changes, newest first. Dates are UTC. Complements [`AUDIT.md`](AUDIT.md)
(findings) and the roadmap in [`../README.md`](../README.md).

## 2026-07-07 — Second-pass audit of `src/submit_session.py`

The dedicated audit Romain requested (130 → 1204 lines). Full report appended
to [`AUDIT.md`](AUDIT.md). Verdict: **no P0/P1** — S02/S09/S10 compliant,
fail-closed guards wired and pinned by ~45 tests; the size is inline JS probes
+ incident-history docstrings, not rot. One drift fixed in the pass (SS1: the
module docstring still claimed "the create capability literally does not exist
here" while `WriteSubmitSession` lives in the same file). Six P2 notes filed
(tap leak on mid-flow exception, residual `PREPARED` status, scroll-logic
duplication, `CLICK_MODES` naming, `_press_enter` keypress gap → check on the
P4 canary, no `CSS.escape`) — candidates only if the file is reopened; no
refactor of the frozen, live-proven mechanism.

## 2026-07-07 — Chantier n°2: page-par-page + pacing humain

Invited by Romain's audit ("le prochain incrément logique") now that the
creation mechanism is frozen and live-proven. Addresses the burst / IP-ban risk
on large volumes: the true bursts were the submitter's full-feed `_scan_feed`
walks (index build + re-walk after **every** creation for post-save verify) and
the extractor's multi-sweep walks (e.g. G2A: 27 pages × ≥2 sweeps) — the old
0.5 s inter-offer pause was negligible against those.

- `src/pacing.py` (new) — `Pacer`: bounded-random `uniform(min,max)` waits,
  injectable rng/sleeper (tests never sleep), aggregate counters
  (`waits`, `total_waited_s`) logged once per run via `snapshot()`.
  `parse_pace_spec("0" | "3" | "2-5")`. Never a correctness mechanism —
  settle waits stay separate.
- `src/extractor.py` — paces before every page fetch after the first (both
  modes). New `extract_pages(first_page, last_page)` slice mode: fetches only
  the requested pages, once; result **always `partial: true`** (a slice never
  claims coverage — no sweeps, no `FeedUnstableError`); same fail-closed
  classification (login bounce, blank in-range page); reports `feed_last_page`
  so the operator plans the next slice.
- `src/submitter.py` — `page_pacer` between feed-scan page loads, `offer_pacer`
  between offers (skips offers not actually processed in write mode). The old
  `pace: float = 0.5` run() kwarg is removed. Engine stays neutral: pacers
  default to `None`; the CLIs are the opinionated layer.
- CLIs — `02_extract_feed.py`: `--pace` (default `2-5` s) and `--pages 3` /
  `--pages 3-5`; `05_submit.py`: `--pace-pages` (default `1-3` s),
  `--pace-offers` (default `5-15` s). `0` disables any of them.
- Tests: 260 → 285 (pacing unit tests, slice-mode extraction incl. past-end /
  empty-queue / blank-anomaly / dedupe / guard signatures, pacer wiring in
  extractor + submitter).

## 2026-07-07 — Invariant gate hardened: `no_openvpn_process`

A live audit found a Surfshark `openvpn` daemon running as root (no tun device,
so AKS direct still worked) — a tunnel coming up mid-batch would flip the egress
IP under an authenticated AKS session. The "VPN forbidden while AKS direct
works" rule was only enforced by the shell audit, not by the authoritative gate
that unlocks write stages.

- `src/aks_env.py` — pure `validate_no_openvpn(pids)` (fail-closed: `None` =
  undeterminable state = FAIL) + read-only `list_openvpn_pids()` probe
  (`pgrep -x openvpn`, same match as the shell audit).
- `src/invariants.py` — third StepGuard probe `openvpn_process` in
  `build_report`; check joins the fail-closed aggregate and the report gains an
  `openvpn` section. Guard consecutive-failure limit sized above the probe
  count so a fully-red environment still emits the JSON report instead of
  raising mid-build.
- Doc drift fixes from the same audit: README roadmap now checks off the
  implemented post-save verifier; `00_audit_env.sh` openvpn FAIL reworded.
- Tests: 251 → 260.

Effect on the VPS today: the gate is **red + authoritative**
(`no_openvpn_process` FAIL, pid 1819) until the daemon is stopped — write
stages stay locked, by design.

## 2026-07-06 — S18 RESOLVED: `offer[targets][]` fill → first live submissions

The Selectize-humanisé fix (2026-07-03) made region/edition valid but the form
still would not submit: a trusted click on "Create offer" fired **zero**
admin-ajax. A read-only probe (`probe_targets_field` / `_TARGETS_PROBE_JS`)
isolated the last empty `required` field — `offer[targets][]`, a bare
`<input type="text" required pattern="(\d+)|(https?://.+)">` with a sibling
"add" button (a chip/array field). It wants the **AKS product id** (numeric) or
an http(s) URL — both already on every candidate (`aks_product_id`, `aks_url`).

**Fix — fill `offer[targets][]` in the trusted path, before the validity gate:**

- `src/submit_session.py` — new `add_target_trusted(value)`: trusted CDP click to
  focus the field, `Input.insertText` to type the value, then commit via the
  **adjacent add-button** (trusted click) with a trusted-Enter (`_press_enter`,
  keyCode 13) fallback. Read-only readback (`_TARGETS_READBACK_JS`) confirms the
  input went `valid:true`. Wired into `fill_then_click_trusted(...,
  target_value=...)` as step 4, **before** the HTML5 validity gate.
- `src/submitter.py` — threads `candidate.aks_product_id` through `_prepare` →
  `_process` → `target_value` (cleanest value, matches `\d+`).
- **HTML5 validity gate is now a hard gate** (`form_validity()` /
  `_FORM_VALIDITY_JS`): if the `<form>` is still invalid after region + edition +
  target, the submitter returns a deterministic `FORM_INVALID` verdict and does
  **not** click — no ambiguous "click ignored", no wasted admin-ajax.
- `--click-mode` now **defaults to `trusted`** (the only mode proven to fire
  Driffle's handler); `native`/`dispatch` kept only as documented diagnostics.
- `scripts/05_submit.py` — report now prints `target_add=` (status/commit/value/
  readback) and `form_valid=`/`invalid_required=` per offer.

**First live-confirmed submissions (Romain-triggered `--submit`).** A canary of 1
(offer 93185190 **Demigod**, Steam EU(9)/Standard(1), run
`20260706-161225-driffle`) succeeded end-to-end: target filled
(`valid:true`), `form_valid:true`, trusted click → **admin-ajax
`…do=create_offer` → 200**, server signal `"[product 2101] Offer created for
locale en_EU and merchant 408"`, and — the only authoritative proof — **gone
from the refreshed pending feed** `[S18]`. We do **not** issue a direct XHR; the
trusted click drives the modal's own `create_offer` and we merely *observe* the
resulting request as a corroborating signal.

**First scaled batch** (run `20260706-162745-driffle`, `--limit 100
--available all`, 4 approved): **3 created** — Gambonanza, Hello Neighbor 2,
Heart of the Machine (all Steam EU(9)/Standard(1), all gone from pending). **1
clean fail (new Layer-5, server-side):** Serious Sam HD Double Pack
(GLOBAL(2)/Bundle(8)) — region/edition picked, form **valid**, target filled,
yet `create_offer` returned `Bad request: paramètre "offer" manquant ou
invalide`. Fail-closed caught it (status=ERROR → not submitted, no false
success, batch continued). This is **not** a regression — expect some
bundle/non-Standard offers to reject server-side even when the form is valid.

**190 tests green.** Commits `41c6bb5` (target fill) + `12fd2ec` (validity gate,
probe, default trusted).

## 2026-07-03 — Chantier n°1 extension: Selectize humanisé (no more `setValue`)

Canary #4 (FRACT OSC, offer 92625611) with `--click-mode trusted` proved the
trusted click LANDS on the correct button (`element_at_center.is_button: true`,
`button_style.pointer_events: auto`) — yet still `requests: []`. Enriched
`--inspect` probe revealed the real blocker: **`form_all_inputs_valid: false`**.
Three `required` text inputs are empty at click time:

- `offer[targets][]` — a real named data field, never filled by our setValue path.
- Two anonymous `<input type="text" required>` inside Selectize wrappers whose
  `parent_class` is `selectize-input items required invalid not-full has-options`
  — Selectize's own UI text input inherits `required` from the underlying
  `<select required>`, and stays empty when the value is set via `.selectize.setValue()`
  because that's a programmatic setter, not a real user interaction.

Consequence: HTML5 form validation blocks the `submit` event before any
handler fires. No handler ⇒ no XHR ⇒ `requests: []`.

**Fix — Selectize humanisé** (Chantier n°1 extension, authorized Romain 2026-07-03):
replace `setValue` with a trusted CDP click on the `.selectize-input` (opens
dropdown), wait 250 ms, trusted CDP click on `.selectize-dropdown-content
.option[data-value="{id}"]` (selects). Same handler chain as a real operator —
Selectize's own event listeners fire, likely populating `offer[targets][]` as
a side-effect. Still no `.click()`, no `dispatchEvent`, no `form.submit()`,
no XHR, no `setValue`. **169 tests green.**

- `src/submit_session.py` — new `select_via_trusted(select_name, value_id)`:
  reads `.selectize-input` rect (S02-safe `_SELECTIZE_INPUT_RECT_JS`),
  trusted CDP click at its center, 250 ms settle, reads
  `[data-value="{id}"]` rect (S02-safe `_SELECTIZE_OPTION_RECT_JS`,
  requires the dropdown visible), trusted CDP click, 200 ms settle,
  reads back `select.value` + `select.selectize.getValue()` + `select.validity.valid`
  (`_SELECTIZE_READBACK_JS`). All events `isTrusted: true`.
- `src/submit_session.py` — refactored the mousedown/dwell/mouseup sequence
  into a private `_trusted_click_at_rect(rect)` helper; `click_trusted_at_element`
  and `select_via_trusted` both use it. No behavior change for the button click.
- `src/submit_session.py` — `_TRUSTED_PREP_JS` no longer calls `setValue`;
  it only installs the network taps + captures pre-existing signal counts + texts
  + button visibility. `_TRUSTED_POLL_JS` now accepts a text CHANGE on an
  existing `[data-success]`/`[data-error]` template node as a valid ACK (Driffle
  updates a pre-existing `<p data-success>` textContent instead of adding a
  node — the previous "new node only" guard would have missed it).
- `src/submit_session.py` (`_INSPECT_MODAL_JS`) — enriched:
  `element_at_center` (`elementFromPoint` at button center), `button_style`
  (pointer_events / z_index / opacity / visibility / display), `form_inputs`
  (name / type / required / value_len / visible / willValidate / validity /
  parent_class), `form_all_inputs_valid`. Read-only, S02-safe.
- `src/submitter.py` — `Submitter._process` unchanged interface; still routes
  to `fill_then_click_trusted` when `click_mode='trusted'`. The internal
  orchestration now uses select_via_trusted twice + click_trusted_at_element.
- Tests: +6 (SelectViaTrusted 4 tests: success chain reads/clicks/readback,
  no_input early-out, no_option after open, S02 guard on the 3 new probes;
  FillThenClickTrusted +3: full success chain merges prep+picks+click+poll,
  region-pick failure triggers cleanup, edition-pick failure triggers cleanup).

**S09 dérogation étendue (2)** : la couche de synthèse trusted couvre maintenant
non seulement le clic sur "Create offer" mais aussi les interactions Selectize
UI (open dropdown + pick option). Toujours aucun `form.submit()`, aucun XHR,
aucun clavier synthétique. Post-save reste juge.

**Next diag** on the VPS (approved.json still points at offer 92625611):

```
python3 scripts/05_submit.py runs/driffle-canary-trusted-1625/approved.json \
    --merchant Driffle --store-id 127 --submit --click-mode trusted
```

Grille :
- `region_pick.status: SELECTED` + `readback.selectize_value` == region_id + `validity_valid: true` → Selectize UI clic OK.
- `requests: [POST admin-ajax.php … -> 200]` + offer gone from pending →
  **Chantier n°1 + Selectize humanisé confirmés**, gel du mécanisme.
- `region_pick.status: NO_OPTION` → dropdown open ok mais l'option n'était pas
  encore rendue (timing) → augmenter le settle post-open ou attendre
  `[data-value]` avant lecture rect.
- `requests: []` **encore** → épuisé les hypothèses connues, on ouvre DevTools
  live pour `getEventListeners(document)` sur la page pending.

## 2026-07-03 — Chantier n°1: `--click-mode trusted` (CDP `Input.dispatchMouseEvent`)

Canary #3 (Driffle) confirmed the S18 root cause: both `native` (`.click()`) and
`dispatch` (MouseEvent) produced `requests: []` with a visible, enabled Create
button. Driffle's handler almost certainly checks `event.isTrusted`, which is
`false` for any DOM-synthesized event. `Input.dispatchMouseEvent` is the only
CDP path that yields `isTrusted: true` — it's what a real desktop operator's
mouse produces. **163 tests green.**

- `src/submit_session.py` — new `click_trusted_at_element(selector)`:
  reads target rect + viewport via `evaluate_readonly` (S02-safe `_RECT_JS`);
  if outside viewport, sends one `Input.synthesizeScrollGesture` (mouse source,
  speed 800), waits **500 ms** for settle, re-reads rect; then
  `Input.dispatchMouseEvent` sequence `mouseMoved(cx,cy)` →
  `mousePressed(cx,cy,left,clickCount=1,buttons=1)` → **random 40-90 ms** dwell
  → `mouseReleased(cx,cy,left,clickCount=1,buttons=0)`. No `.click()`,
  no `dispatchEvent`, no `form.submit()`, no XHR, no keyboard.
- `src/submit_session.py` — new `fill_then_click_trusted(...)`: 2-phase orchestration.
  `_TRUSTED_PREP_JS` fills selectize + installs network taps
  (`window.fetch` / `XMLHttpRequest` wrapped into `window.__s18taps`) + records
  `pre_existing` counts + returns button state; CDP trusted click follows;
  `_TRUSTED_POLL_JS` waits for a NEW `[data-success]`/`[data-error]` node
  (pre-existing guard), reports `requests`/`polls`/`signal`, and restores the
  taps. `_TRUSTED_CLEANUP_JS` restores taps if the click cannot fire (rare).
- `src/submitter.py` — `Submitter` routes to `fill_then_click_trusted` when
  `click_mode='trusted'`; `fill_and_create` unchanged for `native`/`dispatch`.
  `ALL_CLICK_MODES = ('native','dispatch','trusted')` validated at `__init__`
  (`ValueError` on unknown). Post-save (offer gone from refreshed pending) is
  **strictly unchanged** and remains the ONLY success proof in every mode.
- `scripts/05_submit.py` — `--click-mode` accepts `trusted`; the text report
  prints one `trusted_click:` line with click coords + delay_ms + scrolled +
  viewport + rect + click status.
- +12 tests (trusted click sequence order, in-viewport vs out-of-viewport paths,
  scroll gesture params, element-disappears-after-scroll edge, `_RECT_JS`
  read-only guard, `fill_then_click_trusted` merges prep+poll on success,
  cleanup called on `NO_ELEMENT` click, `Submitter` refuses unknown
  `click_mode`, trusted-mode success + still-pending failure).

**S09 derogation étendue** (Romain, autorité n°1, 2026-07-03) : le bouton
officiel visible reste **la seule cible** ; seule la couche de synthèse
d'événement change (DOM → input CDP). `form.submit()` / XHR direct / clavier
synthétique **restent interdits**.

**Next diag on the VPS**:

```
python3 scripts/05_submit.py runs/<id>/approved.json \
    --merchant Driffle --store-id 127 --submit --click-mode trusted
```

Grille de lecture :
- `requests` contient un `POST /wp-admin/admin-ajax.php … -> 200` **et** offre
  disparue du pending → **succès Chantier n°1 confirmé**, gel du mécanisme.
- `requests` avec un 4xx/5xx → handler atteint mais rejet serveur (nonce,
  merchant id, payload) — nouvelle piste, voie DOM restée saine.
- `requests: []` **encore** → hypothèse trusted à revoir (rare : le handler
  écoute autre chose qu'un click, ex : sur le form via `submit`).

## 2026-07-03 — S18 investigation: `--inspect` modal DOM probe (read-only)

Canary #3 (Driffle) with the pre-existing signal guard active produced
`requests: []` + `status: NO_SIGNAL` in **both** `native` and `dispatch` click
modes: the click reaches no handler that fires an admin-ajax request. Prime
suspect now: the `.button-primary` sniper matches an element that has no
handler bound (WP admin `<a href="#">`, or a delegated listener not rebound
after the ThickBox AJAX load). Read-only DOM probe added to identify the
true submit-trigger element and its form, without clicking Create.

- `src/submit_session.py` — new `_INSPECT_MODAL_JS` + `SubmitSession.inspect_modal_dom()`:
  read-only probe returning `{ button: {tag, type_prop, type_attr, id, klass,
  href, name, text, data_attrs, path}, button_count_in_modal, form: {tag, id,
  klass, action, method, onsubmit_attr}, forms_in_modal, forms, modal_selects,
  data_success_in_modal[…], data_error_in_modal[…], data_success_in_doc,
  data_error_in_doc, tbwindow_style }`. Passes the S02 mutation guard (no
  click/submit/fetch/setValue/dispatchEvent).
- `src/submitter.py` — new `InspectSubmitter` (write_mode=False, event_name
  `inspect_offer`): reuses `_index_feed` / `_prepare` and calls
  `inspect_modal_dom` on each ready entry. No clicks on Create, no writes.
- `scripts/05_submit.py` — new `--inspect` flag (mutex with `--submit`; canary
  of 1 by default, `--limit N` / `--all` to widen). Writes `modal_inspection.json`.
- +6 tests (inspect flow, JSON parsing, S02 read-only guard on the probe JS).

**Next diag** on the VPS:

```
python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle \
    --store-id 127 --inspect
```

Then inspect `runs/<id>/modal_inspection.json`. Reading grid:
- `button.tag=A` + `href='#'` → the real trigger is elsewhere (jQuery delegated
  handler somewhere up the DOM path); look at `button.data_attrs` for hints.
- `form.action` non-vide → soumission `<form>` classique ; le vrai geste est
  peut-être un `form.submit()` intercepté (S09-forbidden — regarder `data_attrs`
  et `onsubmit_attr`).
- `button_count_in_modal > 1` → on ciblait le mauvais bouton depuis le début.

## 2026-07-03 — S18 investigation: network taps + dispatch click mode (derogation)

Live canary #2 (Driffle) eliminated hypothesis #1: the selectize readback proved
`setValue` took perfectly (`region_set=9`, `edition_set=1`, options exact) — yet
`[data-success]` appeared with an **empty** signal text and the offer stayed in
pending. Prime suspect: a pre-existing (template/hidden) `[data-success]` node
being mistaken for the AJAX ack, and/or the native `.click()` not firing Driffle's
real submit handler. **144 tests green.**

- `src/submit_session.py` — `_FILL_CREATE_JS` instrumented:
  - **pre-existing signal guard**: `[data-success]`/`[data-error]` nodes are counted
    BEFORE the click; the poll only accepts a **new** node (count increased) —
    otherwise it ends `NO_SIGNAL`. `polls` + `pre_existing` land in the diag.
  - **network taps** (diagnostic only): `window.fetch` + `XMLHttpRequest` are wrapped
    around the click and restored after; the diag reports `via/method/url/status`
    for every request the click fired — never bodies, never headers/cookies. An
    empty `requests` list = the click never reached the network.
  - **button state** (`disabled`/`visible`/`text`) recorded pre-click.
  - **`click_mode='dispatch'`** — full `mousedown/mouseup/click` MouseEvent sequence
    **on the Create button ONLY**. This is an explicit, documented derogation from
    the S09 no-`dispatchEvent` rule, **authorized by Romain (2026-07-03, authority
    order #1)** after the native click was proven not to persist on Driffle. Still
    no `form.submit()`, no XHR submission; unknown modes raise (fail-closed).
- `src/submitter.py` — `Submitter(click_mode=...)` passes the mode through; the
  post-save feed check remains the ONLY success proof, unchanged, in both modes.
- `scripts/05_submit.py` — `--click-mode {native,dispatch}` (native default,
  refused without `--submit`); the text report now prints polls / pre_existing /
  button state and one `net:` line per captured request.
- +4 tests (dispatch pass-through, dispatch still fails when still-pending, native
  default, unknown mode refused).

Also today (infra, no code): AKS dropped the VPS IP at TCP level (curl `000`,
google OK, DNS OK, AKS up from elsewhere) — the documented skill pattern "AKS
bloque les IPs après un burst". Resolved by Romain via the skill's Surfshark
targeted-route rotation (`de-fra` TCP, `--route-nopull --route 176.31.53.220`);
invariants back green+authoritative. Known doc drift to resolve: `00_audit_env.sh`
still FAILs when an openvpn process runs — decision pending on wording it as
"forbidden when direct works / tolerated targeted-route when AKS drops the IP".

## 2026-07-02 — Stage 4: real submitter (WRITES, canary-first)

The real write path — approved by Romain, and validated end-to-end in **dry-run on
the VPS first** (modals open; Driffle selects are `offer[region]`/`offer[edition]`;
Battle.net Gift region resolves to 570). **138 tests green.**

- `src/submit_session.py` — `WriteSubmitSession(SubmitSession)` adds the ONE mutating
  op, `fill_and_create`: `selectize.setValue` on the verified select names, then
  click `#TB_ajaxContent .button-primary` (Promise + 500 ms; skill S09/S17/S19). No
  XHR, no `dispatchEvent`, no `form.submit()`.
- `src/submitter.py` — `Submitter` (real): `fill_and_create`, then **post-save
  verification** — re-scan the feed; `success = the offer disappeared from pending`
  (never `[data-success]`; skill S18). Shares its base flow with the dry-run.
- `scripts/05_submit.py` — `--submit` writes; **canary default = 1 offer**, `--all`
  for the full batch, `--limit N` otherwise. Gated on green + authoritative invariants
  + pre-flight login; one attempt per offer, skip + continue, stop after 10 consecutive.
- 5 tests (canary stops after 1, full batch, still-present = failure, unconfirmed
  click = failure, not-ready never writes).

First real run (canary):
`python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit`

## 2026-07-02 — Stage 4: submitter (DRY-RUN only, no writes)

The submit flow, dry-run only — **no writes**. **132 tests green.** Approach
approved by Romain (`docs/SUBMITTER_SPEC.md`).

- `src/submit_session.py` — `SubmitSession` (extends the read-only CDP session):
  list a page's offer ids, open an offer's modal, read the modal context, detect the
  WP login page. **No method fills a form or clicks "Create offer"** — the create
  capability does not exist in this build.
- `src/submitter.py` — `DryRunSubmitter`: pre-flight login check, locate the exact
  current row, open the modal, verify context + select names, report what it *would*
  submit. Per Romain's decisions: one attempt per offer; on failure log + skip +
  continue; stop the run after **10 consecutive** failures (StepGuard).
- `scripts/05_submit.py` — `--dry-run` (default), gated on green + authoritative
  invariants; `--submit` is **refused** (write path not built). Writes
  `submit_plan.json` + `submit_report.txt`.
- 7 tests (login abort, ready plan, skips, select-name conventions, stop-after-10).

Run on the VPS: `python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127`.

## 2026-07-02 — Stage 3: validation gate

Read-only validation — the fail-closed gate before any submission. **125 tests green.**

- `src/validation.py` — `validation_template` (operator fills approve + who/when)
  and `load_validation`, which verifies a filled file against the CURRENT
  candidates: `run_id` must match, `validated_by`/`validated_at` required, and every
  approved entry must be an exact current candidate by fingerprint
  (`offer_id|aks_product_id|region_id|edition_id`) — a re-match that changes a
  region/edition invalidates a stale approval (skill S15). Any problem rejects the
  whole file (never partially honored).
- `scripts/04_validate.py` — `template` writes `validation.template.json`; `check`
  verifies a filled `validation.json` and writes `approved.json`. Read-only.
- 9 tests. This approval is the lock the future submitter will require — no
  submission is possible without it.

## 2026-07-02 — Sprint 3: read-only matcher

The matcher stage is built (read-only). **Suite: 109 tests green.**

- `src/matcher.py` — ports EXECUTOR_RULES §4: apostrophe-normalized tokenizer,
  R01 strict name match, R01b dangerous-qualifier guard, categorical SKIP lists
  (console, forbidden region, currency/gift/sub, DLC, bundle, language
  restriction), platform + region (URL-first) + edition detection, AKS slug build
  + read-only resolve (`data-product-id` + editions), cap 100. `Candidate` +
  `SkippedOffer` dataclasses; `normalized_block` emits the skill's exact report
  format (`#N — … / 🎯 id — name / 🔗 url / 🎯 aks-url / Platform REGION(id), Edition(id)`).
- `scripts/03_match.py` — reads `offers.json`, resolves candidates against AKS
  (read-only GET), writes `candidates.json` + `skipped.json` + a normalized-text
  `report.txt` (no tables). Aborts if AKS is unreachable.
- 33 tests. Forbidden-region short tokens (NA/OTHER/SEA) excluded to avoid title
  collisions ("Sea of Thieves"); candidates are human-reviewed before any submit.
- Hardened from the first live Driffle run (272 → 5 candidates): added the
  different/expanded-product guard (≥2 extra significant words, or an extra version
  number → SKIP — e.g. GreedFall "The Dying World" ≠ base GreedFall) and Gift
  region detection (Steam 25/259, Battle.net 570/567). Re-validated: 5 → 3 clean
  candidates.

Run on the VPS: `python3 scripts/03_match.py runs/<run_id>/offers.json`.

## 2026-07-02 — Sprint 2: read-only feed extractor

The extractor stage is built (still strictly read-only). **Suite: 83 tests green.**
Unblocked by the VPS invariant gate going green + authoritative.

- `src/cdp_session.py` — stdlib raw-socket CDP session adapted from the skill's
  proven transport (no Origin header → avoids the Docker-terminal 403). Exposes
  only `navigate` + `evaluate_readonly`; refuses mutation-looking expressions
  (`.click(`, `dispatchEvent`, `setValue`, `admin-ajax`, `fetch(`…). Never clicks,
  fills, or submits. Zero new dependencies.
- `src/extractor.py` — `feed_url` (pagination `&p=N`), `parse_offers_payload`
  (`html.unescape` + `json.loads`, skill rule F05), paginated extraction through
  the StepGuard, dedupe-by-id → `RawSnapshot` + `NormalizedFeed`, logged via
  `RunLogger`.
- `scripts/02_extract_feed.py` — CLI that **refuses to run unless invariants are
  green AND authoritative**, then writes `runs/<run_id>/raw.json` + `offers.json`.
- 11 tests (feed URL, payload/entities, pagination/dedupe/stop rules, guard
  wiring, read-only refusal). The live CDP path runs on the VPS.

Run on the VPS: `python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127`.

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
