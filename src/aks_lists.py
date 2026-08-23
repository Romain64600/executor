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


def is_blacklist_label(label: str | None) -> bool:
    """Is a MOVE target a blacklist-class list ("Blacklist", "Blacklist Account",
    …)? Classified by the CANONICAL label our routing assigned (``label_for`` /
    ``suggest_target_list``), NEVER by the live-resolved list id — list ids drift
    (module header; ``resolve_list_id`` re-resolves label→id at write time), so
    mapping a live id back through the static catalog would both defeat this and
    risk misclassifying a drifted non-blacklist id AS blacklist (adversarial
    review 2026-08-23). The label is drift-immune: it is our own routing name.

    A Move to a blacklist list is junk EVICTION from the working feed — the Apply
    (registered-by-us, CLICKED) plus a WHOLE-FEED gone-from-source proof is proof
    enough, so the RV2 present-on-target walk is SKIPPED (the Blacklist is ~2500
    pages; that walk cost ~8h for one page's moves, 2026-08-22; Romain
    2026-08-23)."""
    s = str(label or "").strip().lower()
    if s.startswith("move to "):        # tolerate the live DOM option text form
        s = s[len("move to "):]
    return s.startswith("blacklist")

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

# Region blacklist (Romain 2026-08-13): "on est sur Global, Europe et US. Le reste,
# on skippe et certaines régions qu'on va blacklist, comme les Latam, le Brésil et
# les régions d'Asie" + "les régions russes aussi". MERCHANT-AGNOSTIC and the single
# source of truth: any `forbidden region: <label>` whose label matches one of these
# routes to Blacklist (8), whether the region came from the feed title (Kinguin
# "Brazil") or an offer page (Instant Gaming). Checked BEFORE _REGION_LIST, so it
# also captures "south america" (= LATAM). Keyword containment (+ bare "ru") absorbs
# wording variants ("Russia & CIS", "Latin America (LATAM)"); it runs only on an
# already-forbidden region, so it can never touch a sellable Global/EU/US/UK offer.
# NB: bare "south america" is intentionally NOT here — it keeps its dedicated
# regional list (36) via _REGION_LIST. LATAM / Brazil / Argentina / etc. still
# blacklist. (Open Q to Romain 2026-08-13: blacklist the "South America" label too?)
_BLACKLIST_REGION_KEYWORDS = (
    "latam", "latin america", "brazil", "brasil", "argentina",
    "mexico", "chile", "colombia", "peru",
    "asia", "china", "japan", "korea", "india", "indonesia", "thailand",
    "vietnam", "philippines", "malaysia",
    "russia", "cis",
)


def _is_blacklisted_region(region: str) -> bool:
    r = (region or "").strip().lower()
    if " ru " in f" {r} ":  # bare RU code as a whole token ("RU", "RU ONLY")
        return True
    return any(kw in r for kw in _BLACKLIST_REGION_KEYWORDS)

# Romain 2026-07-23: these exact skip-category tokens are routed to Blacklist (8)
# — skins (+ CS wear grades), non-game content (soundtracks / artbooks / digital
# books) and random/lootbox keys & items. NOT "bundle" (shares the
# "(no bundles/skins)" suffix but a bundle is a different call).
_BLACKLIST_CATEGORY_TOKENS = frozenset({
    "skin", "skins", "field tested", "minimal wear", "factory new",
    "battle scarred", "well worn",
    "soundtrack", "ost", "artbook", "art book", "digital artbook", "digital book",
    "random",  # random/lootbox keys & items (2026-07-23)
})


def label_for(list_id: str) -> str:
    """The catalog label for a list id (or '' if unknown — ids may drift)."""

    return _LABEL_BY_ID.get(str(list_id), "")


def suggest_target_list(reason: str) -> str | None:
    """Deterministic target-list suggestion from a skip reason, or None (garder).

    Only the confident mappings suggest; everything ambiguous (no AKS page →
    needs the 5-year human call, console, bundles, in-game currency,
    subscriptions, regions without a list) returns None so the UI defaults to
    "garder" and the operator decides. See ``docs/AKS_LISTS.md``."""

    r = (reason or "").strip().lower()
    if not r:
        return None
    # Audit L8: anchor on the reason CATEGORY, never a free substring of the
    # whole reason — "no AKS steam-account product page found" must NOT suggest
    # the account list. Slug-hyphenated tokens ("steam-account") don't count.
    if r.startswith("forbidden region"):
        region = r.split(":", 1)[1].strip() if ":" in r else ""
        if _is_blacklisted_region(region):
            return "8"  # LATAM / Brazil / Asia / Russia → Blacklist (Romain 2026-08-13)
        return _REGION_LIST.get(region)  # None for NA / ROW / TURKEY / EMEA / …
    if r.startswith("no aks"):
        return None  # 22-vs-27 is the operator's 5-year call (docs/AKS_LISTS.md)
    haystack = r.split(":", 1)[1] if r.startswith("skip category") and ":" in r else r
    # Blacklist (Romain 2026-07-23): skins, soundtracks, artbooks -> Blacklist (8).
    # NOT bundles (which share the "(no bundles/skins)" suffix) — match the exact
    # category token before the parenthetical, so "BUNDLE" is excluded.
    if r.startswith("skip category"):
        token = haystack.split("(")[0].strip()
        if token in _BLACKLIST_CATEGORY_TOKENS:
            return "8"
    # software / app (e.g. "skip category: SOFTWARE", "... IOBIT (software/app...)")
    if "software" in haystack:
        return "16"
    if "gift card" in haystack or "giftcard" in haystack:
        return "21"
    if _ACCOUNT_WORD_RE.search(haystack):
        return "30"
    return None


# "account" as a standalone word — excludes slug forms like "steam-account".
_ACCOUNT_WORD_RE = re.compile(r"(?<![\w-])account(?![\w-])")

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def year_in_name(name: str) -> str | None:
    """A 4-digit year found in an offer name (a weak hint for the 22-vs-27 call)."""

    m = _YEAR_RE.search(name or "")
    return m.group(0) if m else None
