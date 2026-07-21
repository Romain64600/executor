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

### Confirmed request (captured read-only 2026-07-21, zero mutation)

Captured by trusted-clicking a row checkbox then Apply, with the outgoing request
recorded **and blocked** (`scripts`-style probe in the session tmp; nothing was
sent — `page_navigated:false`). The move is a **native form POST** to the current
list's feed URL:

```
POST https://www.allkeyshop.com/blog/wp-admin/admin.php?available=all&store=<store>&page=aks-merchant-feeds-<currentListId>&p=<n>
Content-Type: application/x-www-form-urlencoded
Body:  bulk[item][]=<offer_id>     (repeatable — one per offer to move)
       bulk[list]=<targetListId>
       bulk[priority]=             (empty unless changing priority)
       bulk[productId]=            (empty)
```

- **No nonce / CSRF token** — authorization is the logged-in admin **session
  cookie** only. So the writer can reproduce the operator action in-page (carries
  cookies) without scraping a token.
- **Selection registration is trusted-only:** a real (isTrusted) change on a row
  checkbox injects a hidden `<input name="bulk[item][]" value="<offer_id>">` into
  the `data-bulk-form`; a scripted `.checked=true` does **not** (so the writer
  must either trusted-click each checkbox or inject the hidden inputs itself).
- **Apply** is a native submit `<button>` inside `data-bulk-form`.

## Triage rules (skip reason → target list)

Romain's policy, captured 2026-07-21. The Learning UI pre-suggests where it can
and leaves the rest a per-offer pick (default = *garder*).

| skip reason | target | auto-suggestable? |
|---|---|---|
| software (`skip category` = app/antivirus/…) | 16 Softwares | yes (reason is deterministic) |
| **no AKS page found** | released **≤ 5 years → 22 Pages for creation**; else **27 Old games / No pages** | **NO — human pick** |
| forbidden region | 32-36 by region (AU/CA/ME/AF/SA) | yes (region is known) |
| gift card | 21 Gift cards | yes |
| account offer | 30 account | yes |
| uncertain | 13 I have a doubt | — |
| console / bundle / DLC | per-offer / often *garder* (no clean target) | no |

**Why "no AKS page" can't be auto-split (22 vs 27):** the 5-year rule needs a
release date, and **the feed gives none** (`releaseDate` = null on 100/100
offers observed; names rarely carry a year). No deterministic source without a
new external lookup (out of scope). So the operator picks 22 vs 27 per offer;
a 4-digit year in the name may be shown as a weak hint, never a default.

## Fail-closed writer sketch (sibling to the submitter)

Same discipline as submit (Romain 2026-07-21): validation file
(`{offer_id, current_list, target_list_label}`) → explicit go → locate the row
(id→URL fallback, `_locate_row`) → resolve `target_list_label`→id live from the
`bulk[list]` options → **register the offer(s)** (trusted checkbox click, or
inject the hidden `bulk[item][]`) → set `bulk[list]` → **trusted-click Apply**
(a real gesture — a scripted change is ignored, isTrusted) → **post-verify: the
offer left the source list** at refresh (the analogue of the submit's "gone from
feed" success) → JSONL log. No fire-and-forget. "Don't change the list"
dispositions are **no-ops** (never written), and so are dispositions still
flagged `suggested: true` in learning.json (D1 option b, Romain 2026-07-21 —
never confirmed by the operator).
