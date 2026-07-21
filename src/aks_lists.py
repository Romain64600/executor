"""AKS merchant-feed lists — catalog + deterministic triage suggestions.

Captured read-only 2026-07-21 (``docs/AKS_LISTS.md``, probe
``scripts/diag_move_to_list.py``). The feed is per-list
(``page=aks-merchant-feeds-<id>``); we scan list 9 = "AKS Feeds" (pending).

**IDs may drift** like the region/edition catalog. This catalog drives the
Learning dropdown and the *suggested* target only. The eventual move writer MUST
re-resolve the chosen **label -> id live** at write time, never trust these ids.
"""

from __future__ import annotations

import re

PENDING_LIST_ID = "9"  # "AKS Feeds" — the default pending queue we scan.

# id -> label, as observed 2026-07-21. Useful triage targets first, then the
# blacklists / niche lists. "" (garder) and "delete" are NOT here on purpose:
# the UI adds a "garder" default and delete is out of scope for the move triage.
LISTS: list[dict[str, str]] = [
    {"id": "16", "label": "Softwares"},
    {"id": "27", "label": "Old games / No pages"},
    {"id": "22", "label": "Pages for creation"},
    {"id": "12", "label": "Pages to sort for creation"},
    {"id": "13", "label": "I have a doubt"},
    {"id": "21", "label": "Gift cards"},
    {"id": "30", "label": "account"},
    {"id": "41", "label": "Top-Up"},
    {"id": "28", "label": "Server game cards"},
    {"id": "32", "label": "Australia"},
    {"id": "33", "label": "Canada"},
    {"id": "34", "label": "Middle East"},
    {"id": "35", "label": "Africa"},
    {"id": "36", "label": "South America"},
    {"id": "11", "label": "No platform on page"},
    {"id": "23", "label": "Crawler"},
    {"id": "6", "label": "PRICE TEAM"},
    {"id": "17", "label": "PRICE TEAM Priorities"},
    {"id": "42", "label": "Gift Card priority"},
    {"id": "43", "label": "account priority"},
    {"id": "44", "label": "New Shop List"},
    {"id": "8", "label": "Blacklist"},
    {"id": "14", "label": "Blacklist (added on CDD)"},
    {"id": "26", "label": "Blacklist Sofwares"},
    {"id": "31", "label": "Blacklist Account"},
    {"id": "37", "label": "Blacklist Gift Card"},
    {"id": "28", "label": "Server game cards"},
]

# Dedup while preserving order (guards against an accidental repeat above).
_seen: set[str] = set()
LISTS = [x for x in LISTS if not (x["id"] in _seen or _seen.add(x["id"]))]

_LABEL_BY_ID = {x["id"]: x["label"] for x in LISTS}

# forbidden region label (in the skip reason) -> regional list id. Only these
# five regions have a list; NORTH AMERICA / ROW / CIS / KOREA / ... have none,
# so they fall through to "garder".
_REGION_LIST = {
    "australia": "32",
    "canada": "33",
    "middle east": "34",
    "africa": "35",
    "south america": "36",
}


def label_for(list_id: str) -> str:
    """The catalog label for a list id (or '' if unknown — ids may drift)."""

    return _LABEL_BY_ID.get(str(list_id), "")


def suggest_target_list(reason: str) -> str | None:
    """Deterministic target-list suggestion from a skip reason, or None (garder).

    Only the confident mappings suggest; everything ambiguous (no AKS page →
    needs the 5-year human call, console, bundles, in-game currency,
    subscriptions, regions without a list) returns None so the UI defaults to
    "garder" and the operator decides. See ``docs/AKS_LISTS.md``."""

    r = (reason or "").lower()
    if not r:
        return None
    # software / app (e.g. "skip category: SOFTWARE", "... IOBIT (software/app...)")
    if "software" in r:
        return "16"
    if "gift card" in r or "giftcard" in r:
        return "21"
    if "account" in r:
        return "30"
    if r.startswith("forbidden region"):
        region = r.split(":", 1)[1].strip() if ":" in r else ""
        return _REGION_LIST.get(region)  # None for NA / ROW / CIS / KOREA / …
    return None


_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def year_in_name(name: str) -> str | None:
    """A 4-digit year found in an offer name (a weak hint for the 22-vs-27 call)."""

    m = _YEAR_RE.search(name or "")
    return m.group(0) if m else None
