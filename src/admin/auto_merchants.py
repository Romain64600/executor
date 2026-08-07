"""Allowlist of merchants eligible for UNVALIDATED safe-auto data entry.

Safe-auto (`/executor/auto`) sweeps a feed and **adds offers without human
validation**. Unlike the main page's free-text merchant entry (a mere typing
shortcut), this list is an *authoritative gate*: a merchant absent here cannot
be launched in auto mode. The frontend only offers these as suggestions, and
`POST /api/data-entry/auto` re-checks server-side so a hand-crafted request
can't bypass the UI (fail-closed).

Keep it in sync with what is actually vetted for unvalidated writing. Adding a
merchant here is a deliberate act: it authorises the pipeline to create its
offers on AKS with no operator review.
"""

from __future__ import annotations

# Ordered (name, store_id) — mirrors the AKS store id. Order drives display.
# Scope decided with Romain (2026-08-07): the mainstream CD-key sellers.
AUTO_MERCHANTS: list[tuple[str, str]] = [
    ("Kinguin", "58"),          # proven in safe-auto this session
    ("G2A", "38"),
    ("Driffle", "127"),
    ("Eneba", "19"),
    ("K4G", "92"),
    ("Gamivo", "51"),
    ("Instant Gaming", "28"),
    ("CJS-CDKeys", "30"),
    ("Allyouplay", "17"),
    ("GameSeal", "126"),
]

# Deliberately NOT suggested (enforcement is simply "absent from the list";
# named here for humans):
#   Difmark (167)  — parked 2026-08-07, feed is console/Epic/Windows (~0 enterable).
#   Gameboost (157) — boosting/accounts, not vetted for unvalidated auto entry.

_BY_NAME: dict[str, tuple[str, str]] = {
    name.casefold(): (name, store) for name, store in AUTO_MERCHANTS
}


def allowed_list() -> list[dict[str, str]]:
    """The suggestions, as JSON-friendly dicts (for the GET route / UI)."""
    return [{"name": name, "store_id": store} for name, store in AUTO_MERCHANTS]


def rejection_reason(merchant: str, store_id: str) -> str | None:
    """None if (merchant, store_id) is allowed for auto; else a human message.

    Enforces the canonical store too: since the UI derives the store from the
    picked merchant, a mismatched store means a tampered/stale request — refuse.
    """
    name = (merchant or "").strip()
    hit = _BY_NAME.get(name.casefold())
    if hit is None:
        return (f"« {name or '(vide)'} » n'est pas dans la liste des marchands "
                "suggérés — data-entry auto restreint aux marchands vettés")
    if hit[1] != str(store_id or "").strip():
        return (f"{hit[0]} attend le store {hit[1]}, pas "
                f"« {str(store_id or '').strip() or '(vide)'} »")
    return None


def is_allowed(merchant: str, store_id: str) -> bool:
    return rejection_reason(merchant, store_id) is None
