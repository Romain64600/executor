# AKS merchant-feed lists — taxonomy & "Move to List" mechanic

Captured read-only from the live admin on **2026-07-21** by
`scripts/diag_move_to_list.py` (G2A, store 38, list 9). No write was performed.

## What a "list" is

The merchant feed is **per-list**: the admin URL is
`admin.php?...&page=aks-merchant-feeds-<listId>`. Every offer row carries a
`listId` (seen in the `data-offer` payload). Our extractor only ever scans
**list 9 = "AKS Feeds"** (the default pending queue) — every offer we've
captured (2 780 across recent runs) is on list 9.

"Move to List" = change an offer's `listId` from 9 to another list.

## The lists (id → label, counts as observed 2026-07-21 — volatile)

| id | label | plausible triage target for our skips |
|----|-------|----------------------------------------|
| 6  | PRICE TEAM | |
| 8  | Blacklist | permanent excludes |
| **9**  | **AKS Feeds** (our pending queue) | (source) |
| 11 | No platform on page | "no platform" skips |
| 12 | Pages to sort for creation | games needing an AKS page created |
| 13 | I have a doubt | uncertain / defer |
| 14 | Blacklist (added on CDD) | |
| 16 | Softwares | "skip category" = software (antivirus, PDF tools…) |
| 17 | PRICE TEAM Priorities | |
| 21 | Gift cards | gift-card offers |
| 22 | Pages for creation | games needing an AKS page created |
| 23 | Crawler | |
| 26 | Blacklist Sofwares | permanent software excludes |
| 27 | Old games / No pages | "no AKS product page found" (old/absent games) |
| 28 | Server game cards | |
| 29 | TEST | **safe throwaway for verifying the write** |
| 30 | account | account offers (buy-…-account pages) |
| 31 | Blacklist Account | |
| 32 | Australia | "forbidden region" AU |
| 33 | Canada | "forbidden region" CA |
| 34 | Middle East | "forbidden region" ME |
| 35 | Africa | "forbidden region" AF |
| 36 | South America | "forbidden region" SA |
| 37 | Blacklist Gift Card | |
| 38 | binance | |
| 39 | remy | |
| 40 | Blake | |
| 41 | Top-Up | |
| 42 | Gift Card priority | |
| 43 | account priority | |
| 44 | New Shop List | |

**IDs may drift** (admin-configured; treat like the region/edition catalog —
[[session-catalog-editions-regions]]). The writer MUST resolve the target list
**by label → id from the live `bulk[list]` options at write time**, never from
this hardcoded table.

## The move control (bulk action)

The offers table sits in a **GET** form whose hidden context is
`available`, `store`, `page=aks-merchant-feeds-<currentListId>`, `p`.

- **Select offers:** each row checkbox is `name="bulk[item][]"` value=`<offer_id>`.
- **Target list:** `<select name="bulk[list]">`. Option values are the target
  `listId`s; two specials:
  - `''` → **"Don't change the list"** (= keep in the same list — Romain's
    defer choice; no write);
  - `'delete'` → Delete.
- **Trigger:** the **"Move to list…"** button submits the form.

So a move is, in essence, the checked offer ids + `bulk[list]=<targetId>` on the
current list's feed URL. **Open item before building the writer:** confirm the
*exact* fired request (plain GET vs a JS-added POST/nonce) by observing ONE real
move on a throwaway (list 29 "TEST"), on Romain's explicit go — never guessed.

## Fail-closed writer sketch (sibling to the submitter)

Same discipline as submit (Romain 2026-07-21): validation file
(`{offer_id, current_list, target_list_label}`) → explicit go → locate the row
(id→URL fallback, `_locate_row`) → resolve `target_list_label`→id live → replay
the move → **post-verify: the offer left list 9** at refresh (the analogue of
the submit's "gone from feed" success) → JSONL log. No fire-and-forget.
"Don't change the list" dispositions are **no-ops** (never written).
