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
  "source_url": "https://www.allkeyshop.com/blog/wp-admin/admin.php?available=all&store=127&page=aks-merchant-feeds-9&orderBy=id&order=desc",
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
      "aks_name": "Tower! Simulator 3",
      "region": { "label": "EU", "id": "9" }, "edition": { "label": "Standard", "id": "1" } }
  ]
}
```

`offer` is the full `NormalizedOffer` dict. `platform` is one of the
`REGION_IDS` keys — STEAM, GOG, UBISOFT, EPIC, EA, BATTLENET or **PUBLISHER**
(R20 revision: a token-less title whose AKS page lists `Direct Publisher`) — or,
since R45 (2026-09-12, `REGION_IDS.update(CONSOLE_REGION_IDS)`), a console family
**XBOX_ONE / XBOX_SERIES / XBOX_PC / PS4 / PS5 / SWITCH / SWITCH2** (SWITCH2 since
2026-09-14 — page kind `nintendo-switch-2`, the Nintendo bucket ids; only produced by the
console branch — `--consoles`, the default since 2026-09-15; `--no-consoles` opts out). A
`SkippedOffer` is `{offer, reason}`.

### Candidate identity — the shared contract (`src/candidate_contract.py`)

Since Lot 2 (2026-09-15, Romain's go) the identity of a candidate — its **target
list** and its **fingerprint** — is defined ONCE, in `src/candidate_contract.py`
(standard library only; it imports nothing from the stages, the stages import it).
Every stage reads that module, never a second copy of the formula:

- `src/matcher.py` — `Candidate.fingerprint` = `candidate_contract.fingerprint(to_dict()
  without the key)`, `Candidate.to_dict()` stamps it; `Target.to_dict()` =
  `to_nested_target(asdict(target))` (the dataclass fields ARE the canonical flat target).
- `src/validation.py` — `candidate_fingerprint` / `candidate_targets` are thin aliases of
  `fingerprint` / `template_targets`; a contract refusal is re-raised as
  `ValidationError` (same message), so `scripts/04_validate.py`, `scripts/10` / `12`,
  `src/data_entry_auto.py` and `src/admin/app.py` are unchanged.
- `src/submitter.py` — `normalize_targets` is a thin alias of the contract's;
  `MAX_TARGETS_PER_OFFER` (3, Romain 2026-09-14) is defined in the contract and imported.
- `src/admin/validation_io.py` — `_mirror_primary_target` = `to_nested_target(primary_target(c))`,
  `_is_multi_target` = `is_multi_target`.
- `src/admin/static/app.js` — `fp()` / `normalizeTargets()` / `primaryTarget()` are a
  **literal port** between the `// candidate-contract:begin` / `:end` markers, verified
  against the same examples by `tests/js/candidate_contract_check.js` (node, CI step
  guarded by `hashFiles`; the VPS has no node — `tests/test_candidate_contract.py` guards
  the block's presence there).

The shared examples are **`tests/fixtures/candidate_contract_examples.json`** — a list of
`{name, candidate, expected_fingerprint | expect_error, expected_targets |
expect_targets_error}` (PC / software / console 1-2-3 targets, pre-R45 file, degenerate
`targets`, flat plan shape, null id, mirror mismatch, verbatim labels…). To change the
identity: change the module AND the fixture first, then the `app.js` block.

**Three target shapes**, all produced / consumed through the module:

- **nested** — `candidates.json` `targets[]` entry (`matcher.Target.to_dict()`,
  `to_nested_target`): `{platform, aks_product_id, aks_url, aks_name, region: {label, id},
  edition: {label, id}}` — the same shape as the top-level fields;
- **flat** — the canonical form, `submit_plan.json` `targets[]` (`normalize_targets`,
  `TARGET_KEYS`): `{platform, aks_product_id, aks_url, aks_name, region_label, region_id,
  edition_label, edition_id}`, ids as strings;
- **template** — `validation.template.json` `targets[]` (`template_targets`,
  `TEMPLATE_TARGET_KEYS`): `{platform, aks_product_id, region_id, edition_id}`.

**`targets` (R45) is ALWAYS present** in a `candidates.json` written by the matcher, even
on a PC candidate, where it holds exactly one entry synthesised from the primary fields.
The FLAT shape never appears in `candidates.json` (doc fix 2026-09-14). The first target IS
the primary (same page / bucket / edition as the top-level fields — the validated identity,
what an operator override rewrites; `validation_io` keeps `targets[0]` mirrored); the
following ones are the other AKS platform pages the same feed row must be filed on
(Romain's per-target region/edition overwrite, EXECUTOR_RULES §4.12). Console region labels
are the modal master label without its " (id)" suffix and without BOM
(`CONSOLE_REGION_LABELS`: "PS5", "Xbox/PC GLOBAL", "Playstation Game Code EUROPE"); the
contract carries labels verbatim (they never enter the fingerprint).

**`normalize_targets(candidate)`** — no `targets` key (pre-R45 file), `null`, a non-list,
an empty list or a SINGLE entry (whatever it holds: `[{}]`, `["x"]`, a drifted hand edit)
→ ONE flat target built from the PRIMARY fields; two or more entries → each flattened as
written (nested or flat form, in order). An entry that is not an object, or whose
`aks_product_id` / region id / edition id is missing or `null`, is refused —
`CandidateContractError("malformed target entry (R45): …")` (a `ValueError`;
`ValidationError` through the validation aliases) — never the literal "None" / "null" in
an identity (review fix 2026-09-14). A target is never dropped and never guessed.

**`fingerprint(candidate)`** is `offer_id|aks_product_id|region_id|edition_id` from the
primary fields — the exact submission identity Stage 3 keys on — **unchanged for zero /
one target**. With more than one target (R45) it becomes
`<primary>|+<id>:<region_id>:<edition_id>[,<id>:<region_id>:<edition_id>…]` over the
secondary targets, in order, so a change in ANY target invalidates the approval.
`targets[0]` must mirror the primary ids — otherwise
`CandidateContractError("targets[0] does not mirror the primary … (R45) — re-run the
match: <offer_id>")`. The candidate's own `fingerprint` key is informational: always
recomputed from the fields, never read. A missing primary key raises `KeyError` (the
safe-auto sweep turns it into a stage error).

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
      "aks_name": "Hades PS4",
      "region": { "label": "Playstation Game Code GLOBAL", "id": "88" }, "edition": { "label": "Standard", "id": "1" } },
    { "platform": "PS5", "aks_product_id": "85105", "aks_url": "https://www.allkeyshop.com/blog/buy-hades-ps5-compare-prices/",
      "aks_name": "Hades PS5",
      "region": { "label": "PS5", "id": "88ps5h" }, "edition": { "label": "Standard", "id": "1" } }
  ]
}
```

(P1, decided by Romain on 2026-09-14: the two targets exist because the merchant declared
BOTH generations — a lone "Hades PS5 CD Key" yields the PS5 target only, never a PS4
sibling.) A null `aks_product_id` / `region.id` / `edition.id` in any target is refused
by the shared contract (`candidate_contract.CandidateContractError("malformed target entry
(R45): …")`, `ValidationError` through `validation.candidate_fingerprint`) — never the
literal "None" in a fingerprint (fix 2026-09-14).

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
  "consoles": true,
  "sitemap_first": {"active": true, "fetched_at": "2026-09-24T12:34:12Z",
                    "legacy_indexed": true, "probes_skipped": 312, "valve_unconfirmed": 38}
}
```

- `data_entry_mode`: `safe` | `learning` | `advanced` (the matcher has no mode
  profiles yet — behaviour is identical, only the stamp differs).
- `matched_at` is the **feed's** `fetched_at`, not the match wall-clock time.
- `consoles` (R45, 2026-09-12): whether the batch was matched with the console branch
  (console rows classified and resolved to their AKS console pages, multi-target
  candidates possible). **`true` is the default since 2026-09-15** (Romain's decision
  « 1 »: `03_match --consoles` is the default, kept as an explicit no-op); `false` = an
  explicit `03_match --no-consoles` (PC-only: every console row skipped `console`). A
  sidecar written before 2026-09-15 without the key was a PC-only match. Stamped by
  `scripts/03_match.py`; the safe-auto sweep always passes its own mode through
  (`--consoles` / `--no-consoles`, explicit either way).
- `sitemap_first` (2026-09-24, EXECUTOR_RULES §4.7): `active` = a fresh, complete sitemap
  index was loaded, so passes 1-2 probed only the index-confirmed URL shapes plus the tier-1
  valve; `fetched_at` = the index snapshot the page was matched against; `legacy_indexed` =
  that snapshot also listed the old `compare-and-buy-…` pages; `probes_skipped` = blind probes
  avoided on this page; `valve_unconfirmed` = tier-1 probes sent although the index did not
  list them. With `active: false` the matcher behaved exactly as before the index. Also
  present in the counter set: `probe_unreliable`, `search_failures`,
  `search_circuit_open_offers`, `throttle_graces` (§4.7).

## recap.json (safe-auto sweep, `scripts/10_data_entry_auto.py`)

`runs/<run-id>/recap.json` (per-page, incremental) carries, next to `targets`,
`total_created`, `halted`, `halted_merchants`, `coverage_incomplete`:

- `consoles` (bool, R45): the console mode of the WHOLE sweep — `true` (the default
  since 2026-09-15, `SweepConfig.consoles`) or `false` (`--no-consoles`, PC-only). Every
  page of the sweep was matched in that mode; the per-target `recap` dicts written by
  `run_sweep` repeat the same `consoles` stamp.

- **La couverture se compte en OFFRES depuis le 2026-09-20.** Chaque `recap` de cible porte
  `distinct_offers` (le nombre d'offer_id DIFFÉRENTS que le balayage a vus) et
  `pages_without_new_offers` (les numéros de page qui n'ont apporté AUCUN id nouveau) ; chaque
  entrée de page porte `new_offers` et, le cas échéant, `repeated_page: true` — depuis le
  2026-09-24, une telle page n'est plus ni matchée ni saisie et porte aussi
  `skipped_repeated: true`, `candidates: 0`, `created: 0`. Depuis le 2026-09-24 aussi, une
  page REFAITE après une erreur passagère porte `transient_retries: [{attempt, wait_s, stage
  ("extract" | "submit"), reason, created_before}]` (les créations d'avant la coupure restent
  dans `created` / `offers_created`), et chaque `recap` compte `transient_retries` (total). Le
  plan de saisie peut finir `stopped: "feed_unreadable_prewrite"` (panne AVANT tout clic,
  offre intacte) et `aborted: "not_logged_in"` (déconnexion au scan d'index) ; depuis le
  2026-09-26, `aborted: "feed_unreadable"` couvre tout échec feed/CDP d'AVANT la boucle des
  offres (contrôle de connexion, catalogue, scan d'index, ouverture de session côté 05), plan
  écrit avec `write_attempts: 0` et, côté 05, un champ `reason` ; les traces d'une
  tentative coupée sont renommées `submit_plan.tryN.json` / `submit_report.tryN.txt` /
  `approved.tryN.json`. Le recap du BALAYAGE porte
  `sitemap_refresh` quand `--sitemap-refresh` est passé : `{refreshed, reason, fetched_at,
  error?, pages?, legacy_pages?, …}` (`aks_sitemap.ensure_fresh`). Quand cette
  liste n'est pas vide et qu'aucun plafond ne parle déjà, `coverage` vaut
  `incomplete_repeated_pages (N page(s) sans offre nouvelle : …)`.
  Pourquoi : sur `20260919-082932`, les pages 86→73 ont rendu QUATORZE fois la même centaine
  d'offres (empreinte identique) et 58→53 six fois de plus — 5 861 lignes lues pour 2 059
  distinctes, et un recap qui publiait `coverage: null`. **Ce n'est jamais une halte** (une
  page réellement vide est légitime, un plafond garde la priorité sur la ligne `coverage`) :
  c'est la seule preuve de couverture que le balayage sache produire. La mesure vient de
  `Stages.offer_ids` (optionnel) ; absent ou en erreur, le balayage se comporte comme avant.

- **La page EN COURS depuis le 2026-09-26** (Romain : « 4. Go »). Chaque `recap` de cible porte
  `current` : `null` entre deux pages et à la fin, sinon `{page, run, since, stage, stage_at}`
  plus ce que l'étape sait déjà — `offers` (dès le matching), `candidates` et `approved` (dès la
  saisie), `movable` (déplacement), `attempt` (≥ 2 sur une reprise), `wait_s` et `reason`
  (pause). `stage` ∈ `probe` (lecture de la page de départ pour connaître la taille du feed),
  `extract`, `match`, `submit`, `move`, `pause`. `run` est le run de la PAGE
  (`<sweep>-<marchand>-s<store>-p<N>`) ; `since` / `stage_at` ont le format des `ts` des
  journaux (`2026-09-26T10:03:00Z`). Le recap est réécrit (`persist`, atomique) à chaque
  changement d'étape (`run_sweep(on_progress=…)`) et dès qu'un marchand démarre (sa cible
  apparaît avec `recap: null`). Pendant la saisie, la console lit les créées / échecs sur
  `GET /api/runs/<run>` (`created_count` / `failed_count`, tirés du journal
  `logs/<run>.jsonl` — route existante, aucune route nouvelle). Pur affichage : rien ne décide
  d'une écriture sur `current`, et un `on_progress` en échec est ignoré.

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
  aks_product_id, region_id, edition_id}` per entry (`candidate_contract.template_targets`),
  so the operator sees every page the row will be filed on; `fingerprint` is
  `candidate_contract.fingerprint` — the same single-/multi-target formula as
  `candidates.json` (see "Candidate identity — the shared contract").
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
(the `rendered_options` text has none, JS `trim()` strips it, yet it sorts last) — and
region `306` is the ONLY region label with a BOM; ten edition labels (`337`, `452`,
`480`, `573`, `1155`, `1448`, `1583`, `4bo`, `5bo`) and one edition KEY
(`"\ufeff1380"`) carry one too (catalog `20260912-080120-auto`, checked 2026-09-14).
Consumers therefore keep `region_text` verbatim in the plan but type the Selectize
query WITHOUT U+FEFF (`region_query` / `edition_query`, `src/submitter.py`, stripped
the same way for both selects).

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
  "gated_multi_target": 0,
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
- `gated_multi_target` (R45 review fix, 2026-09-14): entries gated ONLY by the
  `multi_target_unsupported_until_modal_verified` blocker — designed skips (no write
  attempted, row untouched) that feed neither the 10-consecutive-failures streak nor
  the StepGuard, so a batch of them never yields `stopped: "ten_consecutive_failures"`.
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
- `targets` (R45, 2026-09-12): the candidate's normalised target list — the canonical
  FLAT shape of `candidate_contract.normalize_targets` (an older `candidates.json`
  without the key → one entry, the primary target); on the write
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

### Modal v2 (2026-09-14) — plan entry, statuses, counters

**`submit_plan.json` plan entry (2026-09-14):**

- `modal_shape` (string): `"targets_v2"` | `"targets_v1"` | `"unknown"` — read from
  the open modal; absent when the entry was blocked before its modal opened
  (`too_many_targets`, `offer_type_mismatch: …` — 2026-09-25 —, row not located).
- `modal_shape_detail` (object, when the session reports it):
  `{v2_target0, v2_region0, v2_edition0, v1_input}` booleans — which shape probes
  hit.
- `blocker` new values: `"modal_shape_unknown"`, `"too_many_targets"` — both with
  a French `blocker_message`.
- `would_submit` (dry-run, v2): `set offer[region]=<id>, offer[edition]=<id>,
  targets_v2 rows [row 0: target=<pid> region=<id> edition=<id>; row 1: …],
  click .button-primary (NOT clicked — dry-run)`; gated entries:
  `NOT ready (<blocker>) — targets: …`.
- `create` (write path, v2) — `fill_targets_v2_trusted`'s diag: `status`,
  `modal_shape: "targets_v2"`, `targets_count`, `region_target` / `edition_target`
  (primary ids), `region_pick` / `edition_pick`, `region_set` / `edition_set`,
  `rows: [{row, add?: {row, rows_before, add_button, scroll?, click?, readback?,
  status, reason?}, fill: {row, aks_product_id, region_id, edition_id, focus,
  typed, readback, region_pick, edition_pick, status, reason?}}]`,
  `form_validity`, `click_path`, `pre_click_readback: {region, edition, targets}`,
  `click`, then the poll fields (`polls`, `requests`, `signal`). `reason`
  accompanies every fail-closed status.
- `create.rows[].add` (2026-09-15, canary 2 — the add-button locator):
  - `rows_before` (int): the row count read back BEFORE any click (must equal the
    row index);
  - `add_button` — `_ADD_ROW_BUTTON_PROBE_JS`'s result minus the rect keys: `ok`,
    `last_row`, `tag`, `type_prop`, `type_attr`, `id`, `klass`, `href`, `attrs`
    (attribute names), `data_attrs` (`{name: value≤40}`), `text` (≤ 40), `visible`,
    `is_remove` (carries `data-remove-target` — never clicked), `submit_like`,
    **`matched_by`**: `"[data-add-target]"` | `"fallback:data-attr:<name>"` |
    `"fallback:text"` — which locator rule selected the element; `candidates_count`.
    On `ok: false`: `reason` ∈ `no_modal` | `no_target_rows` |
    `no_add_button_candidate` | `ambiguous_add_button`, plus `candidates:
    [{…same descriptor…, rejected: "remove" | "submit_like" | "not_addish" | null,
    matched_by?}]` — every `<button>` of the form the fallback considered;
  - `click` / `readback` present only when the button was clicked; `readback` is
    the row readback AFTER the click (`row_count` compared to `rows_before`).
- `create.status` new values: `MODAL_SHAPE_MISMATCH`, `NO_TARGETS`, `NO_TARGET_ID`,
  `NO_TARGET_INPUT`, `TARGET_VALUE_MISMATCH`, `NO_ROW_REGION_PICK`,
  `NO_ROW_EDITION_PICK`, `NO_ADD_BUTTON`, `ADD_BUTTON_UNSAFE`,
  `TARGET_ROW_NOT_ADDED`, `TARGETS_COUNT_MISMATCH`, `TARGETS_READBACK_UNREADABLE`,
  **`ROW_REMOVED`** (2026-09-15: the add click made the row count go down — no
  Create click); `VALUE_DRIFTED_BEFORE_CLICK` may now name a row (`row <i>
  <field> reads …`). Row-level statuses: `ROW_ADDED`, `ROW_FILLED` (and the same
  fail-closed values on `add.status` / `fill.status`).
- `post_save` on a refused create: `create not confirmed: <STATUS> — <reason>`.

**Run result (`submit_plan.json` top level / `05_submit` summary):**
`gated_too_many_targets` (int) next to `gated_multi_target` — designed skips,
never failures.

**JSONL `submit_offer` / `dry_run_offer` / `inspect_offer` events:** new fields
`modal_shape`, `gated_too_many_targets` (bool) next to `gated_multi_target`.

**`--inspect` (`modal_inspection.json`):** `targets_probe.targets[]` entries gain
`next_sib_button: {tag, type_prop, type_attr, klass, data_attrs, text}` when the
control is followed by a `<button>` (live: the row's REMOVE button —
`data-remove-target`, "×"; canary 2, 2026-09-15); `modal_context` reports
`modal_shape` + `modal_shape_detail`; entries blocked by `modal_shape_unknown`
are inspected too.

**`inspection.modal_buttons`** (2026-09-15, `_MODAL_BUTTONS_JS`, read-only) — every
`<button>`, `<a role="button">`, `<a data-add-target>` and `<a data-remove-target>`
of `#TB_ajaxContent`, in DOM order, so the real add button is READ before a
multi-target write: `{ok, count, row_count, container: {tag, id, klass, path} |
null, buttons: [{tag, type_prop (BUTTON only), type_attr, id, klass, href (A only),
role, text (≤ 60), data_attrs ({name: value≤40}, ALL data-\* attributes), visible,
in_form, in_targets_container, in_row (index of the target row whose wrapper holds
the button, else null), path (≤ 6 ancestors)}]}`. The **targets container** is the
parent of row 0's wrapper, the wrapper being the closest ancestor of
`input[name="offer[targets][0][target]"]` that also holds the row's two override
selects. `{ok: false, reason, buttons: []}` when the modal / result is missing;
absent altogether when `inspection.modal_ok` is false with no result.

## modal_inspection.json (Stage 4 — `--inspect`, brief)

Read-only S18 forensics (`InspectSubmitter`): same result envelope as
`submit_plan.json` (`aborted` / `stopped` / `feed_offers` / `plan`;
`write_attempts` / `created` null; no CLI-stamped mode keys — written directly
by the `--inspect` branch), where each ready entry additionally carries
`inspection` (`inspect_modal_dom` DOM dump, including `modal_buttons` — every
button of the modal, 2026-09-15), `form_validity` (HTML5 validity inventory) and
`targets_probe` (the `offer[targets][]` field dump). No fill, no clicks on Create.
Defaults to a canary of 1.

## guard_ledger.json (FC3 — cross-process block ledger)

**Une passe AVORTÉE n'est pas une passe propre (audit complet, 2026-09-18).** `ledger.record(blocked=False)` remet `consecutive_blocked_runs` à 0 — l'unique anti-boucle INTER-PROCESSUS du projet. Il était appelé dès que le run était en mode écriture, y compris quand `submitter.run()` avait renvoyé un `aborted` : aucune offre touchée, garde jamais armée, et pourtant la série effacée. Un abort ne crédite ni ne débite désormais : la série reste telle quelle. (`operator_stop` reste hors périmètre.)

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
- `kind`: `submit` | `dry_run` | `catalog` | `extract` | `data_entry_auto` |
  `data_entry_by_urls` | `data_entry_by_urls_submit` (| the sort kinds).
- `pid` / `argv` / `started_at` / `finished_at` / `exit_code`: the supervised
  child, verbatim.
- Per-kind `meta` keys are flattened at top level: submit/dry-run →
  `{mode, limit, dry_run, by, approved_count, max_pages}`; catalog →
  `{by, max_pages}`; extract → `{merchant, store_id, by}`; data_entry_auto →
  `{targets: [{merchant, store_id}], by, run_id, max_pages, continue_on_halt, consoles}`;
  data_entry_by_urls → `{by, run_id, urls, mode: "dry-run", consoles}`;
  data_entry_by_urls_submit → `{by, from_run, run_id, candidates, consoles}`.
  `consoles` (bool, R45, 2026-09-15) is the console mode the manager put on the child's
  argv (`--consoles` / `--no-consoles`, explicit either way) — `true` by default.
- **Admin API bodies (JSON) that carry `consoles`** — Romain's decision « 1 » of
  2026-09-15 (consoles by default everywhere, explicit opt-out):
  - `POST /api/data-entry/auto` — `{targets: [{merchant, store_id}] | group | all_allowlisted,
    confirm: "GO", all_pages? | max_pages?, start_page?, continue_on_halt?, consoles?, list?}`
    — the console sends `all_pages: true` (« toutes ») or `all_pages: false, max_pages: N`
    (« de la page N jusqu'à la 1 », 2026-09-24) and never `start_page` (the page where the
    sweep STOPS; CLI only);
  - `POST /api/data-entry/by-urls` — `{urls: [...] | "u1 u2", consoles?}`;
  - `POST /api/data-entry/by-urls/submit` — `{from_run, recap_sha256, confirm: "GO",
    consoles?}`.

  `consoles` is a JSON **boolean**; **absent = `true`** (the UI checkbox « Consoles
  (pages Xbox / PlayStation / Switch) » is checked by default and sends `false` when
  unticked). Anything else (`"false"`, `0`, `"yes"`) is refused `400 bad_consoles`
  before any launch — the mode of a real-write launch is never guessed. A by-urls submit
  whose `consoles` disagrees with the boolean `consoles` stamped in the preview's
  `recap.json` (when that stamp exists) is refused `409 consoles_mismatch`.
- On finish the supervisor adds `stdout_tail` (last 64 KiB of the child's
  merged stdout/stderr).

The admin's status endpoint serves this file re-`redact()`-ed (same key-name
redaction as the run log).

## by-urls preview — pages consoles (2026-09-15)

Ajouts `[R45]` (2026-09-15), tous rétro-compatibles (nouvelles clés seulement) :

- `recap.consoles` (bool) — le mode de l'aperçu (`--consoles` défaut true).
- `recap.games[].page_kind` — `"cd-key"` | `"account"` | `"ps4"` | `"ps5"` | `"xbox-one"` |
  `"xbox-series"` | `"nintendo-switch"` | `"nintendo-switch-2"` (kind de l'URL demandée).
- `recap.games[].search.page_kind` — idem ; `search.name_term` est l'identité de la page
  pour une page console (« Hades »), `search.url_term` le slug du jeu.
- `recap.games[].reason` (URL non résolue) peut valoir `"ConsolePageRefused: console page
  (<kind>) refused under --no-consoles — …"` (aucun fetch effectué).
- `recap.games[].error` peut valoir `"aks_throttled"` (429 / lectures de pages cibles non
  fiables pendant le match ; `recap.aborted = "aks_throttled"`, `detail` = message).
- `recap.games[].merchants[].skipped[].reason` peut valoir `"not on the requested page
  <pid>: this offer targets <PLATFORM> <pid>[, …] — not entered from this page (R45)"`
  (candidat valide du matcher dont aucune cible n'est la page demandée).
- `recap.games[].merchants[].candidates[]` — forme inchangée (`Candidate.to_dict`, §Candidate) :
  `targets[]` toujours présent, plusieurs entrées pour une clé cross-gen / Play Anywhere,
  `fingerprint` étendu `…|+<pid>:<rid>:<eid>`. Jamais scindé par l'aperçu ni par la saisie.
- `report.txt` : suffixe `[page <kind>]` sur la ligne 🎯 d'une page console ; lignes
  `↳ <PLATFORM> <pid> — <nom> · <label>(<id>)` par cible supplémentaire ; note
  « (N cibles : une clé cross-gen … écrite sur toutes ses pages déclarées) ».
- Log JSONL (`logs/<id>.jsonl`) : `run_start.consoles`, `game_start.page_kind`,
  `candidate.targets` (nombre de cibles) ; saisie : `submit_run_start.consoles` (flag reçu)
  et `submit_run_start.preview_consoles` (`recap.consoles` de l'aperçu, `null` si absent).
- Sortie JSON de `scripts/11` et `scripts/12` : clé `consoles` (bool).

---

### Audit 2026-09-15 — `consoles` lu par `scripts/12`, cibles dans l'aperçu web

#### `recap.json` (aperçu by-urls, `scripts/11`) : `consoles` est LU par `scripts/12`

À ajouter au paragraphe du recap dry-run by-urls (clé `consoles`) :

- `consoles` (bool, R45) n'est plus seulement informatif : **`scripts/12` le lit**
  (`consoles_mode_refusal`) et refuse fail-closed, exit 2, un submit lancé dans l'autre mode
  (`--consoles` vs `false`, `--no-consoles` vs `true`) — même garde que le
  `consoles_mismatch` (409) du manager admin, mais appliquée aussi au lancement CLI direct.
  **Absent** (aperçu antérieur au stamp) ou **non booléen** : pas de comparaison ; sous
  `--no-consoles` le contenu décide (tout candidat à plateforme console dans `targets[]` /
  `platform`, ou à plus d'une cible, refuse le lot). Le recap doit donc rester la **copie
  immuable** du manager (`source_recap.json`, P1) : c'est elle qui porte le stamp comparé.

#### `recap.json` (submit by-urls, `scripts/12`) : refus `consoles_mismatch`

À ajouter à la liste des `aborted` du recap submit :

- `aborted: "consoles_mismatch: …"` — le mode consoles demandé ne correspond pas à
  l'aperçu (stamp `consoles` opposé, ou, sous `--no-consoles`, un candidat console /
  multi-cibles). Écrit **avant** toute préparation : `merchants: []`, `totals`
  `{merchants: 0, attempted: 0, created: 0}`, aucun sous-run `<run_id>-s<store>`. Tronqué à
  400 caractères (les fautifs complets sont dans le JSONL).

#### `logs/<run_id>.jsonl` (submit by-urls) : `submit_run_aborted` porte les fautifs

- `submit_run_aborted` peut maintenant précéder tout `merchant_submit` : champs `reason`
  (« consoles_mismatch: … »), `consoles` (bool demandé), `preview_consoles` (le stamp de
  l'aperçu, `null` si absent), `offenders` (liste, vide pour un désaccord de stamp ; sinon
  `{merchant, store_id, offer_id, name, platforms: [...], targets: n}` par candidat refusé).

#### aperçu web (`api/data-entry/by-urls/recap`) : ce que l'UI lit

- L'UI (`urls.js`) lit, par candidat, `targets[]` (`{platform, aks_product_id, aks_url,
  aks_name, region:{label,id}, edition:{label,id}}`) pour afficher **chaque** cible et
  compter les écritures (KPI « page(s) cible(s) à écrire », total « N offres sur T pages » du
  modal Saisir). Tolérance : forme plate (`region_label`, `region_id`, `edition_label`,
  `edition_id`) et `targets` absent (→ la cible primaire = les champs du candidat). Les
  nombres annoncés (« offres à saisir (lot) », « page(s) cible(s) à écrire », « N offres sur
  T pages » du modal Saisir, `#saisir-n`) sont ceux du **lot dédoublonné comme
  `_candidates_by_store`** (par store, une occurrence par `fingerprint` — le champ écrit par le
  matcher dans chaque candidat de l'aperçu, sinon la formule du contrat) ; le KPI
  `totals.candidates` du recap reste le compte par jeu et n'est plus affiché qu'en complément
  (« N trouvée(s), X doublon(s) entre jeux »). Le manager garde `totals.candidates` pour
  `nothing_to_submit` / `meta.candidates` (compte par jeu, pas le lot).

## sort_plan.json — le bloc `coverage`

`scripts/08_sort_plan.py` écrit `coverage` via `src.sort_plan.coverage_from_stats` :
`partial` (toujours `True` — un scan est une photo), `pages_fetched`, `feed_last_page` (le
MAXIMUM de pagination vu pendant la marche), **`feed_last_page_final`** (la dernière
pagination réellement LUE) et **`ended_past_end`** (la marche a vu la page d'après-la-fin),
puis `truncated`.

**`truncated` se juge sur les deux témoins OBSERVÉS, jamais sur le maximum (2026-09-21).**
Une marche longue voit la liste rétrécir sous elle : le scan `20260921-072420-sort` a lu
566 pages annoncées en page 1 et s'est terminé page 489 sur une page vide (`nav_max=488`).
Comparer 566 à 489 déclarait tronqué — et la console tait TOUTE proposition de requête sur
un plan tronqué (`src/admin/sort_sql_view.py` : `proposals = [] if coverage["truncated"]`).
Une tranche explicite (`--pages`) reste tronquée par nature ; des statistiques sans les
témoins (runs d'avant le 21/09) retombent sur l'ancien verdict — fail-closed.

Un plan re-jugé après coup porte la trace de l'opération : `recomputed_at`,
`recomputed_note` et `recomputed_from` (les valeurs d'origine), pour qu'un lecteur voie
que la couverture a été recalculée et sur quelle preuve.

## state/page_catalog.db — le catalogue des pages AKS (2026-09-21)

SQLite, une ligne par **(slug, gabarit)**, alimentée par `03_match --page-catalog` avec ce que
le match a DÉJÀ lu. Colonnes : `slug`, `page_kind` (cd-key / steam-account / ps4 / ps5 /
xbox-one / xbox-series / nintendo-switch…), `url`, `product_id`, `aks_name`, **`nature`**
(`standard` / `dlc` / `early_access` / `inconnue`), `early_access_until`, `editions` et
`regions` (JSON, cartes brutes), `official_platforms`, `console_pages`, `page_platform`,
`read_at` (UTC), `source`.

La **nature** décrit le CONTENU, le **gabarit** décrit la page : une page peut être à la fois
« compte Steam » et « accès anticipé ». `src.page_catalog.describe()` rend la phrase.

Base **partagée** entre les deux VPS : `<user>@<hôte>:<chemin>` ouvre un tunnel SSH multiplexé
(ControlMaster) et travaille en accès GROUPÉS. `journal_mode=WAL` + `busy_timeout` : deux
balayages qui écrivent en même temps ne se bloquent pas. Trois invariants : jamais un échec en
cache, une durée de vie de 30 jours à la lecture (rien n'est effacé), et **aucune erreur ne
remonte** — disjoncteur après deux échecs. Le catalogue ne décide jamais à la place d'une
lecture fraîche : au moment d'écrire une offre, la carte d'éditions relue reste l'autorité.

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

**`logs/<run-de-page>-stages.log` — le dernier recours (2026-09-20).** La sortie standard ET
l'erreur de chaque stage enfant du balayage y sont appendues (`CooperativeChildRunner`,
`output_path`). C'est la seule trace d'un CRASH : un stage qui lève avant d'avoir un journal
(la fenêtre `build_report`, par exemple) n'écrit aucun évènement `aborted`. `scripts/10` en
relit la dernière ligne utile (`_stage_crash_tail`) pour le recap, et seulement quand aucun
évènement journalisé ne parle. Fichier gitignoré comme le reste de `logs/`.

**L'évènement `aborted` est le canal du POURQUOI (2026-09-19).** Le sweep (`scripts/10`) lance ses
stages avec la sortie standard jetée (`src/child_runner.py`) et relit la raison d'un stage non nul
dans le jsonl du run de page : le DERNIER `aborted` porteur d'un `reason` (`_last_abort_reason`,
tronqué à 160 caractères) devient `exit N (<reason>)` dans le recap — pour l'extraction ET pour le
submit. Contrat pour `02_extract` et `05_submit` : **toute sortie fail-closed en 2 écrit d'abord
`{"event": "aborted", "reason": …}`** — invariants (avec le nom des contrôles rouges),
revalidation, FC5, FC3, feed/CDP illisible, verrou navigateur (run_id déduit du chemin
`approved.json`). Un `return 2` sans `aborted` est une régression : le recap redirait « exit 2 »
sans cause, comme Gamerall `20260919-152446` page 26.

## Conventions

- Timestamps are UTC ISO-8601 `...Z`; clocks are injectable for tests.
- Machine data is JSON; event logs are JSONL; human reports are Markdown /
  normalized text (never tables — skill rule).
- Contracts never silently coerce away a violation — they raise. Fail-closed.
  The one deliberate exception is `guard_ledger.json`, fail-open by design
  (see its section): a broken ledger must not brick the pipeline while the
  in-run guard stays armed.


## `recap.json` — écriture ATOMIQUE (audit complet, 2026-09-18)

`recap.json` est le contrat que la console relit EN DIRECT pendant qu'un run tourne. Il était
réécrit en place (troncature puis réécriture) après CHAQUE page, toute la nuit : une lecture
tombant dans la fenêtre voyait un JSON coupé. Sweep (`scripts/10`) et by-urls (`scripts/11`,
`scripts/12`) utilisent maintenant la convention déjà en place ailleurs dans le dépôt —
fichier temporaire dans le MÊME dossier, donc même système de fichiers, puis `os.replace`.

## `state/active_run.json` — on ne vole pas le marqueur d'un run vivant (2026-09-18)

`write_marker` écrasait inconditionnellement, alors que sa docstring ne promettait que
« overwrites any marker left by a dead process ». Un simple `--dry-run` lancé pendant un sweep
de 30 h volait donc le marqueur : le sweep devenait INVISIBLE dans les consoles, et le bouton
« Lancer » s'y rouvrait. `ActiveRunExists` est levé quand un marqueur VIVANT porte un AUTRE
`run_id` ; un pid mort reste écrasé (l'auto-guérison est préservée) et le même `run_id` aussi.
Le sweep rend maintenant son marqueur à la FIN de `main()`, pas seulement à l'`atexit`.


## `runs/<run>/targets_queue.json` — ajouter un marchand à un sweep EN COURS (2026-09-19)

Romain : « On a l'option pour ajouter un marchand à un sweep en cours ? ». Il n'y en avait
aucune : `scripts/10_data_entry_auto.py` lisait `--targets` une fois au démarrage et itérait
une liste figée. Couper un sweep de plusieurs heures pour y ajouter un marchand, c'était perdre
le balayage en cours.

**Forme** — une liste JSON, ordonnée par ajout :

```json
[{"merchant": "Gamerall", "store_id": "13", "by": "romain", "at": "2026-09-19T08:43:57Z"}]
```

**Un seul écrivain, un seul lecteur.** La console (`SubmitManager.add_sweep_target`) est le
SEUL écrivain du fichier : elle lit, ajoute, réécrit atomiquement, sous son mutex. Le sweep est
le SEUL lecteur : il ne réécrit jamais ce fichier, il retient en mémoire ce qu'il a déjà pris.
Il n'y a donc aucune lecture-modification-écriture concurrente sur la file.

**L'état « fermée » vit dans le recap, pas dans un fichier à part.** `recap["queue_closed"]`
est écrit par le sweep, atomiquement (`persist()`), et relu par la console à chaque ajout — elle
lit déjà le recap pour connaître le plan. Une première version portait cet état dans un
fichier `targets_queue.closed` ; ses deux cas spéciaux (fermer après la boucle, effacer au
démarrage) ont chacun ouvert un défaut (revue `/code-review`, 2026-09-19). Le recap est rebâti
à chaque lancement (aucun héritage), stampé sur toute sortie, et il est ce que la console
affiche.

**La fermeture est PUBLIÉE, jamais seulement en mémoire (revue de Romain, 2026-09-19).** Sur
une sortie par `break` (stop opérateur, halte fail-closed), le drapeau ne touchait le disque
qu'au tout dernier `persist()` : entre-temps la console lisait encore « ouverte », répondait
`queued: true`, et l'entrée tombait APRÈS la relecture finale — ni balayée, ni inscrite dans
`targets_not_reached`. Toute sortie passe désormais par le même `close_queue(True)` que la
boucle, qui écrit ET persiste avant de relire.

**Le protocole de fin, et pourquoi l'ORDRE est la garantie.** À chaque frontière de marchand le
sweep relit la file. Quand il n'a plus rien à balayer : il écrit `queue_closed: true` **puis**
relit une dernière fois. Un ajout que la console a accepté sans avoir vu la fermeture a été
écrit avant elle, donc la relecture qui la suit le voit — c'est un happens-before, pas une
fenêtre « supposée nulle ». Si cette relecture rapporte une retardataire, le sweep la traite et
**rouvre** la file (`queue_closed: false`) pendant son balayage — sans quoi la console refuserait
pendant des heures un ajout que le lecteur aurait pris — puis referme à la vraie fin. Sur
TOUTE sortie (fin naturelle, stop opérateur, halte fail-closed), le sweep ferme, fait une
dernière relecture d'**enregistrement**, et inscrit `targets_not_reached` : les cibles prises
mais jamais démarrées, et les ajouts arrivés trop tard. Un ajout accepté ne disparaît jamais
sans trace.

**Côté console, dans l'ordre :** `run_id` **obligatoire** et égal au run actif (`409
run_required` / `409 run_mismatch` — sinon un clic sur un onglet qui a vu « Sweep terminé »
rejoindrait n'importe quel sweep B, avec les paramètres de B) ; `queue_closed` **avant tout le
reste** (`409 sweep_finishing`, sans rien écrire — même pour un doublon, sinon une relance après
« NON garantie » recevrait 200 « déjà dans la file ») ; puis le dédoublonnage contre `planned ∪
targets ∪ targets_added` (`queued: false`, « déjà cible de ce sweep ») ; puis l'écriture ; puis
une **re-vérification** de `queue_closed` — s'il vient de passer à `true`, la réponse est
`queued: false` « prise en charge NON garantie ; le recap fait foi » au lieu d'une promesse. La
liste blanche est vérifiée par la route ET par le lecteur du sweep (`take_from_queue`) :
`Difmark:167` écrit à la main dans le fichier est refusé et inscrit `targets_refused`, jamais
balayé. Chaque issue est journalisée dans `logs/<run>.jsonl` (`add_target_queued` /
`_ignored` / `_uncertain` / `_refused`).

**Ce que le sweep inscrit dans le recap** — `planned` (le plan complet, initial + pris, tenu à
jour), `targets_added` (pris dans la file), `targets_refused` (liste blanche), `targets_ignored`
(doublon du plan initial écrit à la main — un ajout pris par ce run n'est PAS re-tracé aux
relectures suivantes), `targets_not_reached`, `queue_closed`. La console les affiche sous le
compteur du recap.

**Au lancement** — la file n'est effacée que sur une **relance** (un `recap.json` existe déjà) :
un dossier neuf de la console, qui déclare le run occupé AVANT de lancer le processus, peut
déjà contenir un ajout fait pendant le démarrage — il est pour ce run. Et `write_marker`
n'accepte le MÊME `run_id` que depuis son propre processus (ou après sa mort) : une relance
depuis l'historique du shell pendant que le run tourne est refusée au lieu de voler ses
fichiers.

**La fenêtre résiduelle, dite honnêtement** — un SIGKILL du sweep entre l'écriture de
`queue_closed: true` et la relecture qui la suit laisse dans la file un ajout déjà accepté, sans
`finished_at` ni `targets_not_reached`. La console refuse ensuite tout nouvel ajout
(`no_sweep_running`, le marqueur ayant un pid mort), mais cet ajout-là ne se retrouve qu'en
comparant `targets_queue.json` et `targets_added`. C'est le prix d'un canal fichier sans
transaction ; il est nommé plutôt que nié.
