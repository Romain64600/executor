# DATA_CONTRACTS.md — stage I/O schemas

The JSON shapes exchanged between executor stages, plus the run-log format. These
are enforced in code by `src/contracts.py` (fail-closed: malformed input raises
`ContractError`) and `src/run_log.py`. They implement the extractor output spec in
[`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) §3, and give each stage's "success"
predicate ([`EXECUTOR_RULES.md`](EXECUTOR_RULES.md) §2) something concrete to
validate. Standard library only — no schema dependency.

## Pipeline overview

```
extractor  →  RawSnapshot        (verbatim feed + run metadata)     → runs/<run_id>/raw.json
extractor  →  NormalizedFeed     (typed, deduped offers)            → runs/<run_id>/offers.json
matcher    →  candidates/skipped (Sprint 3 — not yet contracted)
every stage → RunLogger          (append-only JSONL events)         → logs/<run_id>.jsonl
```

`RawSnapshot` and `NormalizedFeed`/`NormalizedOffer` are frozen dataclasses with a
`to_dict()` for serialization. Build order: `RawSnapshot.create(...)` →
`NormalizedFeed.from_snapshot(snapshot)`.

## RawSnapshot

The feed exactly as fetched (each `raw_offers` entry is a `data-offer` dict, after
`html.unescape` then `json.loads` — skill rule `[F05]`), plus run metadata.

```json
{
  "run_id": "2026-07-02-driffle-01",
  "merchant": "Driffle",
  "store_id": "127",
  "source_url": "https://www.allkeyshop.com/blog/wp-admin/admin.php?available=all&store=127&page=aks-merchant-feeds-9",
  "fetched_at": "2026-07-02T09:15:00Z",
  "pages_scanned": 4,
  "offer_count": 300,
  "raw_offers": [ { "id": "92015031", "name": "...", "url": "https://...", "storeId": "127", "price": "12.34", "stock": "y" } ]
}
```

Validation (`RawSnapshot.create`): `run_id`, `merchant` non-empty; `source_url`
must be http(s); `pages_scanned >= 1`; every `raw_offers` entry must be a dict.

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
`otp`, `googleotp`, `2fa`, `token`, `secret`, `api_key`. Usage:

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
