# DATA_CONTRACTS.md — stage I/O schemas

The JSON shapes exchanged between executor stages, plus the run-log format. The
Stage 1/2 extractor shapes are enforced in code by `src/contracts.py`
(fail-closed: malformed input raises `ContractError`) and `src/run_log.py`;
later stages' shapes are defined by the producing code cited in each section
and re-verified by their consumers (submit-time approval re-derivation P1, the
FC5 mode gate, the FC3 block ledger). They implement the extractor output spec
in [`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) §3, and give each stage's "success"
predicate ([`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) §2) something concrete to
validate. Standard library only — no schema dependency.

## Pipeline overview

```
extractor   →  RawSnapshot         (verbatim feed + run metadata)      → runs/<run_id>/raw.json
extractor   →  NormalizedFeed      (typed, deduped offers)             → runs/<run_id>/offers.json
matcher     →  Candidate[] / SkippedOffer[] + R24 mode stamp           → runs/<run_id>/candidates.json, skipped.json, report.txt, match_meta.json
validation  →  template → filled file → approved batch                 → runs/<run_id>/validation.template.json, validation.json, approved.json
submitter   →  plan + human report (+ catalog / inspection / ledger)   → runs/<run_id>/submit_plan.json, submit_report.txt, session_catalog.json, modal_inspection.json, guard_ledger.json
admin page  →  supervised-run state file                               → runs/<run_id>/admin_submit.json
every stage →  RunLogger           (append-only JSONL events)          → logs/<run_id>.jsonl
```

`RawSnapshot` and `NormalizedFeed`/`NormalizedOffer` are frozen dataclasses with a
`to_dict()` for serialization. Build order: `RawSnapshot.create(...)` →
`NormalizedFeed.from_snapshot(snapshot)`. Everything under `runs/` and `logs/`
is operational state — gitignored, never committed.

## RawSnapshot

The feed exactly as fetched (each `raw_offers` entry is a `data-offer` dict, after
`unescape_attribute` — browser attribute-value semantics, only `;`-terminated
entity references decode, so `&currency=` survives — then `json.loads`;
skill rule `[F05]` as hardened 2026-07-08), plus run metadata.

```json
{
  "run_id": "2026-07-02-driffle-01",
  "merchant": "Driffle",
  "store_id": "127",
  "source_url": "https://www.allkeyshop.com/blog/wp-admin/admin.php?available=all&store=127&page=aks-merchant-feeds-9",
  "fetched_at": "2026-07-02T09:15:00Z",
  "pages_scanned": 4,
  "feed_last_page": 4,
  "offer_count": 300,
  "raw_offers": [ { "id": "92015031", "name": "...", "url": "https://...", "storeId": "127", "price": "12.34", "stock": "y" } ]
}
```

Validation (`RawSnapshot.create`): `run_id`, `merchant` non-empty; `source_url`
must be http(s); `pages_scanned >= 1`; every `raw_offers` entry must be a dict.
`pages_scanned` is how many pages this run FETCHED (a slice fetches 1);
`feed_last_page` is the feed's OWN advertised page count (`nav_max`), used by
the submit to auto-default `--max-pages` (2026-07-20). `0` = not recorded
(runs extracted before 2026-07-20). Same two fields propagate to `offers.json`.

## NormalizedOffer / NormalizedFeed

Typed, deduped rows. `offer_id`, `name`, `url` are mandatory; `url` must be a real
http(s) URL from the feed — **never invented or a placeholder** (skill rule "JAMAIS
INVENTER D'URL"). `store_id`/`price`/`stock` are optional and coerced to clean
strings (empty → `null`). Dedupe is by `offer_id` across pages (skill rule `[F03b]`).

```json
{
  "run_id": "2026-07-02-driffle-01",
  "merchant": "Driffle",
  "fetched_at": "2026-07-02T09:15:00Z",
  "feed_last_page": 4,
  "offer_count": 297,
  "offers": [
    {
      "offer_id": "92015031",
      "name": "Tower! Simulator 3",
      "url": "https://www.driffle.com/tower-simulator-3",
      "merchant": "Driffle",
      "store_id": "127",
      "price": "12.34",
      "stock": "y"
    }
  ]
}
```

Validation (`NormalizedOffer.from_raw` / `NormalizedFeed.from_snapshot`): missing
`id`/`name`/`url`, a non-http `url`, or an empty `merchant` raises `ContractError`.
`from_snapshot` is fail-closed — a malformed row aborts the feed (a parse bug to
fix, not to hide). Note: filtering (console/DLC/region SKIPs) is the **matcher's**
job, not the extractor's — normalization keeps every well-formed row.

## Candidate / SkippedOffer (matcher output)

`scripts/03_match.py` + `src/matcher.py` turn a `NormalizedFeed` into
`candidates.json` (list of `Candidate.to_dict()`) and `skipped.json` (list of
`SkippedOffer.to_dict()`), plus a normalized-text `report.txt` — text only, no
tables: one 5-line block per candidate, then a per-reason "Skipped summary".

```json
{
  "fingerprint": "92015031|12345|9|1",
  "offer": { "offer_id": "92015031", "name": "...", "url": "https://...", "merchant": "Driffle", "store_id": "127", "price": "12.34", "stock": "y" },
  "aks_product_id": "12345",
  "aks_url": "https://www.allkeyshop.com/blog/...",
  "aks_name": "Tower! Simulator 3",
  "platform": "STEAM",
  "region": { "label": "EU", "id": "9", "implicit": false },
  "edition": { "label": "Standard", "id": "1" },
  "targets": [
    { "platform": "STEAM", "aks_product_id": "12345", "aks_url": "https://www.allkeyshop.com/blog/...",
      "aks_name": "Tower! Simulator 3", "region_label": "EU", "region_id": "9",
      "edition_label": "Standard", "edition_id": "1" }
  ]
}
```

`offer` is the full `NormalizedOffer` dict. `platform` is one of the
`REGION_IDS` keys — STEAM, GOG, UBISOFT, EPIC, EA, BATTLENET or **PUBLISHER**
(R20 revision: a token-less title whose AKS page lists `Direct Publisher`) — or,
since R45 (2026-09-12, `REGION_IDS.update(CONSOLE_REGION_IDS)`), a console family
**XBOX_ONE / XBOX_SERIES / XBOX_PC / PS4 / PS5 / SWITCH** (only produced under
`--consoles`). A `SkippedOffer` is `{offer, reason}`.

**`targets` (R45) is ALWAYS present**, even on a PC candidate, where it holds exactly
one entry synthesised from the primary fields (`platform`, `aks_product_id`,
`aks_url`, `aks_name`, `region`, `edition`). Each entry is a `Target.to_dict()`
(`src/matcher.py`, frozen dataclass): `{platform, aks_product_id, aks_url, aks_name,
region_label, region_id, edition_label, edition_id}`. The first target IS the
primary (same page / bucket / edition as the top-level fields); the following ones
are the other AKS platform pages the same feed row must be filed on (Romain's
per-target region/edition overwrite, EXECUTOR_RULES §4.12). Console region labels
are the modal master label without its " (id)" suffix and without BOM
(`CONSOLE_REGION_LABELS`: "PS5", "Xbox/PC GLOBAL", "Playstation Game Code
EUROPE").

**`fingerprint`** is `offer_id|aks_product_id|region_id|edition_id` — the exact
submission identity Stage 3 keys on — **unchanged for a single target**. With more
than one target (R45) it becomes
`<primary>|+<id>:<region_id>:<edition_id>[,<id>:<region_id>:<edition_id>…]` over the
secondary targets, in order (`src/matcher.py` and `validation.candidate_fingerprint`
share the formula; the admin's `app.js` `fp()` mirrors it), so a change in ANY target
invalidates the approval.

A two-target console candidate (illustrative Kinguin row; the AKS ids are Hades'
real page ids of 2026-09-12 — PS4 page 85104, PS5 page 85105; primary = the first
declared family):

```json
{
  "fingerprint": "101050001|85104|88|1|+85105:88ps5h:1",
  "offer": { "offer_id": "101050001", "name": "Hades PS4/PS5 CD Key", "url": "https://www.kinguin.net/category/.../hades-ps4-ps5-cd-key", "merchant": "Kinguin", "store_id": "58", "price": "9.99", "stock": null },
  "aks_product_id": "85104",
  "aks_url": "https://www.allkeyshop.com/blog/buy-hades-ps4-compare-prices/",
  "aks_name": "Hades PS4",
  "platform": "PS4",
  "region": { "label": "Playstation Game Code GLOBAL", "id": "88", "implicit": true },
  "edition": { "label": "Standard", "id": "1" },
  "targets": [
    { "platform": "PS4", "aks_product_id": "85104", "aks_url": "https://www.allkeyshop.com/blog/buy-hades-ps4-compare-prices/",
      "aks_name": "Hades PS4", "region_label": "Playstation Game Code GLOBAL", "region_id": "88",
      "edition_label": "Standard", "edition_id": "1" },
    { "platform": "PS5", "aks_product_id": "85105", "aks_url": "https://www.allkeyshop.com/blog/buy-hades-ps5-compare-prices/",
      "aks_name": "Hades PS5", "region_label": "PS5", "region_id": "88ps5h",
      "edition_label": "Standard", "edition_id": "1" }
  ]
}
```

A console candidate is emitted only when EVERY declared platform resolved to a
verified AKS page, bucket and edition — never a partial `targets` list (EXECUTOR_RULES
§4.12 "Never partial"). `report.txt` prints one extra "↳" line per secondary target
("↳ PS5 85105 — Hades PS5 · PS5(88ps5h)").

## match_meta.json (FC5 — matched-mode stamp)

`scripts/03_match.py` records which R24 data-entry mode produced the batch, in a
**separate sidecar** — `candidates.json` stays a plain list, because the
validation triple's shape is load-bearing (FC5, audit 2026-07-17).

```json
{
  "run_id": "2026-07-02-driffle-01",
  "data_entry_mode": "safe",
  "matched_at": "2026-07-02T09:15:00Z",
  "consoles": false
}
```

- `data_entry_mode`: `safe` | `learning` | `advanced` (the matcher has no mode
  profiles yet — behaviour is identical, only the stamp differs).
- `matched_at` is the **feed's** `fetched_at`, not the match wall-clock time.
- `consoles` (R45, 2026-09-12): whether the batch was matched with
  `03_match --consoles` (console rows classified and resolved to their AKS console
  pages, multi-target candidates possible) or not (`false` / absent = the default:
  every console row skipped `console`). Stamped by `scripts/03_match.py`; the
  safe-auto sweep passes its own `--consoles` flag through (default off).

Consumers: `scripts/05_submit.py` and the admin's `SubmitManager` refuse a REAL
submit whose declared mode implies a **wider** batch than the matched mode — a
run matched under an unlock (canary of 1) must never take the full-batch `safe`
path. Absent file = legacy pre-FC5 run, accepted; unreadable file = fail-closed
abort. Narrower-or-equal submits stay allowed.

## Validation triple (Stage 3)

`src/validation.py` + `scripts/04_validate.py`. Three files, always siblings of
`candidates.json` in the run directory:

- **`validation.template.json`** (`template` subcommand): `{run_id,
  generated_at, validated_by: "", validated_at: "", instructions, candidates}`
  where each `candidates[]` entry is `{fingerprint, offer_id, merchant_title,
  aks_product_id, aks_name, platform, region_id, edition_id, targets, approve: false}`
  — `targets` (R45) is the candidate's target list reduced to `{platform,
  aks_product_id, region_id, edition_id}` per entry, so the operator sees every page
  the row will be filed on; `fingerprint` follows the same single-/multi-target
  formula as `candidates.json`.
- **`validation.json`**: the operator's filled copy — `approve: true` on the
  offers to submit, `validated_by` / `validated_at` filled in.
- **`approved.json`** (`check` subcommand): the list of the **exact current
  candidate dicts** (same shape as `candidates.json` entries) whose fingerprint
  was approved.

`load_validation` is fail-closed: a `run_id` mismatch, missing who/when, or an
approved `fingerprint` that is not an exact current candidate rejects the whole
file — never a partial approval (skill rule S15: a previous "oui" never
authorizes a new/changed batch). At submit time, `approved.json` alone is
**never** authority: every consuming mode of `05_submit.py` (dry-run, inspect,
submit) and the admin re-derive the approval from `candidates.json` +
`validation.json` via `verify_approved_against_source` and require an exact
match — a fabricated, hand-edited or stale `approved.json` refuses to load
(P1, Romain's audit 2026-07-08).

An admin **override** (platform / region / edition changed in the validation UI,
`validation_io._apply_override`) is refused on a candidate with more than one
target: `ValidationIOError("bad_override", "candidat multi-cibles (R45) : pas de
surcharge, relancer le match")` — the targets are derived together from the AKS
pages, so a per-field override cannot be kept coherent; re-run the match instead.
The UI shows such rows with a "N cibles (R45)" block (family · page id · region(id) per
target) inside the « Produit AKS » cell and the platform / region / edition selects
disabled.

## session_catalog.json (Stage 4 — `--catalog`)

`scripts/05_submit.py --catalog` writes the run's copy of the **global**
Édition + Région dropdown catalog, fetched ONCE per data-entry session by
`fetch_session_catalog` (`src/submitter.py`): read-only — it opens one current
offer's modal, enumerates both selects in full, no fill, no create. The ids
drift as AKS adds entries, so labels must be resolved against this live catalog,
never a hardcoded table (wrong-edition incident, 2026-07-06).

```json
{
  "ok": true,
  "offer_id": "92015031",
  "region_select": "offer[region]",
  "edition_select": "offer[edition]",
  "regions":  { "ok": true, "select_name": "offer[region]", "current_value": "",
                "rendered_count": 71, "rendered_options": [ { "data_value": "9", "text": "Steam EU (9)" } ],
                "select_option_count": 0, "select_options": [],
                "master_count": 71, "master_options": [ { "key": "9", "text": "Steam EU (9)" } ] },
  "editions": { "…": "same probe shape" }
}
```

On failure: `{"ok": false, "reason": "not_logged_in" | "no_openable_offer"}` —
the file is written either way; the CLI exits 2 when not ok. `region_select` /
`edition_select` record which select-name variant the modal uses
(`offer[region]` vs `offer[region_id]`, same for edition). `regions` /
`editions` are `probe_select_options` results; **`master_options`**
(`{key, text}`) is the list write runs resolve against (`resolve_catalog_id`:
unambiguous label match first, then matcher-id validation with a whole-word
label check — FC4; neither resolves → the offer is blocked, never forced).
A write run without a usable catalog aborts (`aborted: "catalog_unavailable"`).

Catalog facts that matter for the console buckets (R45, 2026-09-12; the 867-entry
region list was byte-identical in the 9 catalogs fetched 10-12/09): every `key` is a
**string**, and 182 region keys are non-numeric (`24eu`, `24us`, `88eu`, `88ps5h`,
`99eu`…) — `_norm_option_text` strips only a numeric `(\d+)` suffix, so those labels
(and `306`, below) resolve **through the id path only** (verified live:
`('Xbox/PC GLOBAL', '306')` → source `id`, `('PS5', '88ps5h')` → `id`,
`('Xbox Game Code EUROPE', '24eu')` → `id`; the same label with a wrong id → `None`,
blocked). The `306` master label is `"\ufeffXbox/PC GLOBAL (306)"` — a leading U+FEFF
(the `rendered_options` text has none, JS `trim()` strips it, yet it sorts last);
edition `480` carries one too. Consumers therefore keep `region_text` verbatim in
the plan but type the Selectize query WITHOUT U+FEFF (`region_query` /
`edition_query`, `src/submitter.py`).

## submit_plan.json (Stage 4 — dry-run and `--submit`)

The machine record of a submitter pass — `scripts/05_submit.py` writes the
`run()` result of `DryRunSubmitter`/`Submitter` (`src/submitter.py`) plus three
CLI-stamped keys. Per CLAUDE.md, its content + the process exit code are read
and checked before ANY continuation to a new run/page/stage. **Overwritten by
every later pass** on the same run dir (a dry-run after a real submit replaces
it) — the append-only JSONL run log is the durable per-offer history the admin's
`offer_submit_history` relies on first.

```json
{
  "aborted": null,
  "stopped": null,
  "feed_offers": 297,
  "write_attempts": 3,
  "created": 3,
  "plan": [ { "…": "one entry per processed offer, see below" } ],
  "catalog": { "offer_id": "92015031", "regions_count": 71, "editions_count": 34 },
  "data_entry_mode": "safe",
  "matched_mode": "safe",
  "limit": null
}
```

Top-level fields:

- `aborted`: `null`, or `"not_logged_in"` / `"catalog_unavailable"` /
  `"feed_unreadable"` — the run never reached the batch loop (`plan` empty; on
  `catalog_unavailable` the `catalog` key carries the failed fetch result).
- `stopped`: `null`, or `"limit_reached"` / `"guard_blocked"` /
  `"ten_consecutive_failures"` / `"feed_unreadable"` — the batch loop ended
  early; the `plan` built so far is preserved. On `feed_unreadable` the last
  entry's state is UNKNOWN (see `post_save` below).
- `feed_offers`: rows indexed by the pre-batch feed scan.
- `write_attempts` / `created` (P2, audit 2026-07-08 — attempts ≠ creations):
  integers on a completed write run — `write_attempts` counts every ready offer
  a write was attempted on, `created` only post-save-**proven** creations;
  `null` on a completed dry-run; the pre-loop aborted shapes carry `0`.
- `catalog`: present only when a session catalog was loaded (write runs) —
  a summary, not the full catalog (that lives in `session_catalog.json`).
- `data_entry_mode` / `matched_mode` / `limit` (stamped by the CLI, R24/FC5):
  the declared mode the pass ran under, the mode from `match_meta.json`
  (`null` on pre-FC5 runs), and the batch cap the mode produced (`null` = full
  approved batch; in write mode reaching it sets `stopped: "limit_reached"`).
- The run **kind** (dry-run vs real) is not a field: `null`
  `write_attempts`/`created` and `would_submit` entries mean dry-run;
  `admin_submit.json` records the kind explicitly for admin-launched passes.

Each `plan[]` entry (fields appear as the flow reaches them):

- Always: `offer_id` (the **current** feed row id — may differ from the
  approved id after a re-import), `merchant_title`, `aks_url`, `ready` (bool);
  normally also `aks_product_id`, `region_id`, `edition_id` (on the write path
  the ids are overwritten by the live-catalog resolution).
- Row location: `located_by: "url"` + `approved_offer_id` when the row was
  relocated by merchant-URL path (feed re-imports rotate ALL ids — K4G/G2A,
  2026-07-08); `id_mismatches` when the by-id row contradicted the candidate;
  `row_checked` / `fresh_row_checked` list the fields verified (P1 / SC5).
- Not processable: `blocker` (string) with `ready: false`.
- `targets` (R45, 2026-09-12): the candidate's normalised target list (an older
  `candidates.json` without the key → one entry, the primary target); on the write
  path every target's region / edition is resolved against the live catalog (any
  failure → blocker, as for a single target). **More than one target →
  `ready: false`, `blocker: "multi_target_unsupported_until_modal_verified"`** ("la
  saisie multi-cibles / overwrite par cible attend l'observation du nouveau modal
  (--inspect) — R45"): the per-target overwrite controls of Romain's new feed modal
  have not been observed yet, and a partial entry ("first target only") is
  forbidden because the creation consumes the feed row. One target = today's path,
  unchanged. A dry-run's `would_submit` lists every target.
- Modal: `page_url`, `modal`, `select_names`, `region_select`, `edition_select`.
- Write-path catalog resolution: `region_text` / `edition_text` and
  `region_resolution` / `edition_resolution` —
  `{id, text, source: "label"|"id", matcher_id, changed}` (`region_text` is the
  catalog master label verbatim — BOM included for bucket `306`; the typed query is
  the same text without U+FEFF, see `session_catalog.json` above).
- Dry-run: `would_submit` (human string, nothing clicked).
- Write: `create` (the fill+click diagnostic dict from the session: `status`,
  set/target read-backs, option counts, `form_validity`, `target_add`,
  `click_mode`, `click` geometry, `signal`, network `requests`),
  `submitted` (bool — true **only** on the post-save proof), and `post_save`:
  - `"gone from feed (available=<mode>)"` — the ONLY success (skill S18;
    never `[data-success]`), same available mode as the run;
  - `"STILL in feed (available=<mode>) — FAILED"`;
  - `"create not confirmed: <STATUS> — <reason>"` — the click never settled;
  - `"feed/CDP unreadable — offer state UNKNOWN, verify it by hand on AKS
    before any retry: <exc>"` — Create may already have fired when the verify
    scan died; the run stops (`stopped: "feed_unreadable"`) and the offer
    requires a manual feed check before any retry (FC1, audit 2026-07-17).

`submit_report.txt` is the human mirror of the same pass: a header
(mode, batch, counters, aborted/stopped) then one `[SKIP (…)]` / `[READY]` /
`[CREATED (…)]` / `[FAILED (…)]` line per plan entry with its diagnostics.

## modal_inspection.json (Stage 4 — `--inspect`, brief)

Read-only S18 forensics (`InspectSubmitter`): same result envelope as
`submit_plan.json` (`aborted` / `stopped` / `feed_offers` / `plan`;
`write_attempts` / `created` null; no CLI-stamped mode keys — written directly
by the `--inspect` branch), where each ready entry additionally carries
`inspection` (`inspect_modal_dom` DOM dump), `form_validity` (HTML5 validity
inventory) and `targets_probe` (the `offer[targets][]` field dump). No fill, no
clicks on Create. Defaults to a canary of 1.

## guard_ledger.json (FC3 — cross-process block ledger)

`runs/<run_id>/guard_ledger.json`, written by `BlockLedger`
(`src/step_guard.py`) — real (write) passes only; dry-runs stake nothing. The
in-memory StepGuard dies with its process, so this ledger applies G03 ("the
same approach failing twice → STOP") at run granularity, across processes.

```json
{
  "consecutive_blocked_runs": 2,
  "last_block": { "task_id": "2026-07-02-driffle-01", "rule": "…", "reason": "…", "at": "…Z" },
  "task_id": "2026-07-02-driffle-01",
  "updated_at": "…Z",
  "acknowledged": { "note": "operator --acknowledge-block on the CLI", "at": "…Z" }
}
```

Semantics: each real pass ending guard-blocked increments
`consecutive_blocked_runs` and records `last_block`; a clean pass resets it to
0. One blocked pass leaves the standard idempotent recovery pass free
(Romain, 2026-07-07); at ≥ 2 `05_submit.py` refuses to **start** another write
pass until the operator re-arms it with `--acknowledge-block` (recorded under
`acknowledged`, counter reset). The ledger never re-arms a live in-process
guard. Deliberately fail-**open** on a corrupt file (`{consecutive_blocked_runs:
0}`) — a broken ledger must not brick the pipeline; the in-run guard stays
fully armed either way.

## admin_submit.json (admin page — supervised-run state)

`runs/<run_id>/admin_submit.json`, written atomically by
`src/admin/submit_manager.py` — the on-disk half of "never fire-and-forget":
one file per run recording the spawned `05_submit.py` / `02_extract_feed.py`
child and its outcome.

```json
{
  "state": "running",
  "kind": "submit",
  "pid": 12345,
  "argv": ["python3", "scripts/05_submit.py", "runs/<id>/approved.json", "--merchant", "Driffle", "--store-id", "127", "--mode", "safe", "--submit"],
  "started_at": "…Z",
  "finished_at": null,
  "exit_code": null,
  "mode": "safe", "limit": null, "dry_run": false, "by": "romain",
  "approved_count": 12, "max_pages": null
}
```

- `state`: `running` → `done` (exit 0) or `failed` (exit ≠ 0). On server
  startup, `recover_orphans` rewrites a stale `running`: `interrupted` (pid
  dead — plus a French `note` telling the operator to inspect the feed and
  `submit_plan.json` before any resumption) or `orphaned` (pid still alive —
  should not happen with the cgroup kill; new runs are refused while it lives).
- `kind`: `submit` | `dry_run` | `catalog` | `extract`.
- `pid` / `argv` / `started_at` / `finished_at` / `exit_code`: the supervised
  child, verbatim.
- Per-kind `meta` keys are flattened at top level: submit/dry-run →
  `{mode, limit, dry_run, by, approved_count, max_pages}`; catalog →
  `{by, max_pages}`; extract → `{merchant, store_id, by}`.
- On finish the supervisor adds `stdout_tail` (last 64 KiB of the child's
  merged stdout/stderr).

The admin's status endpoint serves this file re-`redact()`-ed (same key-name
redaction as the run log).

## Run log (JSONL)

`src/run_log.py`'s `RunLogger` writes one JSON object per line to
`logs/<run_id>.jsonl` (gitignored). Each record carries `ts`, `run_id`, `event`,
plus arbitrary fields. **Secrets are redacted by key name before writing** — a
control token (`webSocketDebuggerUrl`), cookie, or 2FA code becomes
`***REDACTED***`, so it can never reach a log even if a caller passes it in.

```jsonl
{"event":"feed_fetch","merchant":"Driffle","pages_scanned":4,"run_id":"2026-07-02-driffle-01","ts":"2026-07-02T09:15:00Z"}
{"event":"guard_snapshot","guard":{"blocked":false,"task_id":"2026-07-02-driffle-01","counters":{"total_failures":0}},"run_id":"2026-07-02-driffle-01","ts":"2026-07-02T09:15:03Z"}
```

Redacted keys (case-insensitive, exact match so `token_count` is safe):
`webSocketDebuggerUrl`, `cookie(s)`, `set-cookie`, `authorization`, `password`,
`passwd`, `otp`, `googleotp`, `2fa`, `token`, `secret`, `api_key`, `apikey`.
Usage:

```python
from src.run_log import RunLogger
log = RunLogger(run_id)                 # → logs/<run_id>.jsonl
log.log("feed_fetch", merchant=merchant, pages_scanned=n)
log.log_guard(guard.snapshot())         # persist the StepGuard state per task
```

## Conventions

- Timestamps are UTC ISO-8601 `...Z`; clocks are injectable for tests.
- Machine data is JSON; event logs are JSONL; human reports are Markdown /
  normalized text (never tables — skill rule).
- Contracts never silently coerce away a violation — they raise. Fail-closed.
  The one deliberate exception is `guard_ledger.json`, fail-open by design
  (see its section): a broken ledger must not brick the pipeline while the
  in-run guard stays armed.
