"""GamersOutlet (feed store 31) — the title grammar, declared 2026-09-15 `[R48]`.

Audited on the WHOLE of the day's pending feed (20 rows, `feed_last_page=1`, read-only
extraction `runs/20260915-gamersoutlet`). Small corpus, but a strikingly regular grammar:
every row carries a parenthesised **delivery / region slot**.

Grammar (title, 20/20)::

    <Product> [ (<OS>) ] ( <DELIVERY> / <REGION> ) [ <licence qualifier> ]

The slot is the LAST parenthesised group containing a "/". It is not always the end of the
title — "Autodesk AutoCAD 2022 (Windows) (Lifetime/ Global) Commercial Version" — so the
anchor is the GROUP, never the end of the string.

Real rows::

    Polylithic (PC Steam Key / Global)                              → STEAM, global
    Grand Theft Auto V Enhanced (PC Rockstar Key / Global)          → ROCKSTAR, global
    Hunt: Showdown 1896 - Sage of Joseon DLC (PC Steam Key / Global)→ STEAM, global, DLC
    Adobe Photoshop 2026 (Windows) (Lifetime License / Global)      → software licence
    Roblox 10000 Robux (PC Roblox Key / Global)                     → skip: ROBLOX has no
                                                                      AKS platform bucket

`[R48]` **the region slot is MANDATORY, and its vocabulary is closed.** GamersOutlet writes
the worldwide region EXPLICITLY — "Global" in the title 20/20 and "-global" as the last slug
token 20/20 — and never leaves the slot empty (0/20). So, unlike Kinguin / MMOGA where the
ABSENCE of a code is the merchant's way of writing "global", a silent GamersOutlet title has
no proven meaning: it would take the generic implicit GLOBAL and could file a region-locked
key worldwide. A title with no slot, or a slot whose region is outside the shared
vocabulary, is a fail-closed `precheck` skip. Cost today: 0 rows of 20 — the rule is there to
hold when the feed changes, not to refuse anything now.

`[R48]` **the delivery half of the slot is a closed vocabulary too, and the accepted stores
are THIS file's table.** The left half is "PC <Store> Key" (12/20 — Steam 6, Roblox 4,
Rockstar 2) or "Lifetime License" / "Lifetime" (8/20, software). `STORE_PLATFORM` maps the
stores that have an AKS platform bucket; ``url_platform`` publishes the SAME table to the
matcher, so the store the precheck accepts and the platform the matcher reads are one piece
of data (adversarial review 2026-09-15: a hand-copied allow-list drifts from what
``explicit_platform`` really returns, and "PC EA Key" / "PC Blizzard Key" would have been
accepted by the gate and then resolved to no platform at all). Any store outside the table —
ROBLOX among them, which is why the four Robux rows stop here — is a fail-closed skip, never
a Steam or Publisher default (`[R27]`).

Software rows ("Lifetime License") keep the generic route: no store platform is declared, so
they reach the R20 / R27 page check and, when the AKS page has a single global bucket, the
software catch-all (`resolve_software_region`, R31). They are NOT skipped here.

Console rows: none in the corpus (0/20). The delivery gate hands any row whose left half
names a console back to the shared classifier (`[R45]`) rather than judging it — 16 probes
written in the proven grammar showed the shared reading already handles them, so this file
declares NO console hook.

Self-contained: imports only ``src.merchant_config`` and ``src.merchants.common`` — never
``src.matcher`` nor ``src.console_keys``.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    REGION_SLUGS,
    compound_region_kind,
    forbidden_reason,
    make_config,
    region_slug,
    sellable_base,
)

# ── the slot ─────────────────────────────────────────────────────────────────────────
# The LAST parenthesised group containing a "/" is the delivery / region slot. Anchored on
# the GROUP, not on the end of the title (1/20 rows carry a trailing qualifier after it).
_PAREN_GROUP_RE = re.compile(r"\(([^()]*)\)")

# ── the delivery half ────────────────────────────────────────────────────────────────
# Stores observed or plausible in "PC <Store> Key", mapped to OUR platform token. This table
# is the single source of truth: ``url_platform`` publishes it to the matcher and
# ``precheck`` refuses anything outside it. Only spellings that yield a real AKS platform
# bucket are here — a store without one must fail closed, not default.
STORE_PLATFORM: dict[str, str] = {
    "STEAM": "STEAM",
    "GOG": "GOG", "GOG.COM": "GOG",
    "EPIC": "EPIC", "EPIC GAMES": "EPIC", "EPIC GAMES STORE": "EPIC",
    "UBISOFT": "UBISOFT", "UBISOFT CONNECT": "UBISOFT", "UPLAY": "UBISOFT",
    "EA APP": "EA", "ORIGIN": "EA",
    "BATTLE.NET": "BATTLENET", "BATTLENET": "BATTLENET",
    "ROCKSTAR": "ROCKSTAR", "ROCKSTAR GAMES": "ROCKSTAR",
}
# Software licence deliveries — no store platform is declared; the row keeps the generic
# route (page platform check, then the R31 software region catch-all).
_LICENCE_DELIVERIES = frozenset({"LIFETIME", "LIFETIME LICENSE", "LIFETIME LICENCE"})
# A left half naming a console hands the row back to the shared R45 classifier untouched.
_CONSOLE_WORDS = (
    "XBOX", "PLAYSTATION", "PSN", "PS3", "PS4", "PS5", "NINTENDO", "SWITCH", "WII", "3DS",
)
# "PC" / "MAC" are device words in the left half, never the store. "WINDOWS" is deliberately
# NOT one: GamersOutlet writes the OS in its own parenthesised group ("(Windows)"), so a
# "Windows" inside the slot belongs to a STORE name ("Windows Store") and must reach the
# store gate whole — otherwise the refusal would name 'STORE' instead of 'WINDOWS STORE'.
_DEVICE_WORDS = frozenset({"PC", "MAC", "PC/MAC", "PC / MAC"})
_DELIVERY_MARKERS = frozenset({"KEY", "KEYS", "CD KEY", "CODE", "DIGITAL KEY", "DIGITAL CODE"})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).upper()


def slot(name: str) -> tuple[str, str] | None:
    """The (delivery, region) halves of the title's slot, verbatim, or None when the title
    carries no parenthesised group containing a "/".

    The region half is the LONGEST FINAL run of "/"-separated parts that the shared
    vocabulary reads as ONE region — so "Xbox One / Xbox Series X|S Key / Global" splits
    after the key word, and "… / EU/NA" keeps the compound lock whole."""

    groups = [(m.group(1), m.span()) for m in _PAREN_GROUP_RE.finditer(name or "")]
    slots = [g for g in groups if "/" in g[0]]
    if not slots:
        return None
    inner = slots[-1][0]
    parts = [p.strip() for p in inner.split("/")]
    best: tuple[str, str] | None = None
    for cut in range(1, len(parts)):          # longest readable final run first
        region = "/".join(parts[cut:]).strip()
        if compound_region_kind(region) is not None:
            best = (" / ".join(parts[:cut]).strip(), region)
            break
    if best is None:
        # no readable region in the slot — hand back the raw split so precheck can refuse
        # it by NAME (never silently)
        best = (" / ".join(parts[:-1]).strip(), parts[-1])
    return best


def _slot_span(name: str) -> tuple[int, int] | None:
    groups = [(m.group(1), m.span()) for m in _PAREN_GROUP_RE.finditer(name or "")]
    slots = [g for g in groups if "/" in g[0]]
    return slots[-1][1] if slots else None


def _store_of(delivery: str) -> str | None:
    """The store named in the delivery half ("PC Steam Key" → "STEAM"), or None."""

    words = _norm(delivery)
    if not words:
        return None
    tokens = [t for t in re.split(r"\s+", words) if t]
    # strip the leading device word(s) and the trailing delivery marker
    while tokens and tokens[0] in _DEVICE_WORDS:
        tokens.pop(0)
    while tokens and (tokens[-1] in _DELIVERY_MARKERS or " ".join(tokens[-2:]) in _DELIVERY_MARKERS):
        if " ".join(tokens[-2:]) in _DELIVERY_MARKERS:
            tokens = tokens[:-2]
        else:
            tokens.pop()
    return " ".join(tokens) or None


# ── URL ──────────────────────────────────────────────────────────────────────────────
_URL_STORE_RE = re.compile(
    r"-(" + "|".join(sorted((region_slug(s) for s in STORE_PLATFORM), key=len, reverse=True))
    + r")-(?:cd-)?keys?(?:-|$)")


def url_platform(url: str) -> str | None:
    """The platform the slug declares — "…-pc-steam-key-global" → STEAM. The SAME table the
    delivery gate accepts, so the two can never drift. A software slug ("…-lifetime-license-
    global", 8/8) declares no store → None, and the generic route decides."""

    path = urlsplit(url or "").path.lower()
    m = _URL_STORE_RE.search(path)
    if not m:
        return None
    return STORE_PLATFORM.get(m.group(1).replace("-", " ").upper()) or STORE_PLATFORM.get(
        m.group(1).replace("-", ".").upper())


def _url_region(url: str) -> str | None:
    """The region run at the END of the slug ("…-key-global" → "global"), or None."""

    path = urlsplit(url or "").path.lower().rstrip("/")
    tail = path.rsplit("/", 1)[-1]
    for words in (3, 2, 1):
        run = "-".join(tail.split("-")[-words:])
        if run in REGION_SLUGS:
            return run
    return None


def _url_region_kind(url: str) -> tuple[str, str] | None:
    """What the slug's trailing region run MEANS — ("base", "eu") / ("forbidden", "ROW") —
    or None when the slug carries no readable region.

    Read through the shared vocabulary, never as text: a slug has no case, so the run is
    upper-cased before resolution ("eu" → "EU", "united-states" → "UNITED STATES")."""

    run = _url_region(url)
    if run is None:
        return None
    return compound_region_kind(run.replace("-", " ").upper())


# ── hooks ────────────────────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """GamersOutlet's categorical skips, in order (every one fail-closed):

    1. no "(<delivery> / <region>)" slot → the region is never implicit here `[R48]`;
    2. a slot region outside the shared vocabulary → refused by name;
    3. a region LOCK → ``forbidden region: <LABEL>``;
    4. the slug's trailing region run contradicting the title's → refused;
    5. a delivery half naming a store with no AKS platform bucket → refused (`[R27]`: never
       a Steam or Publisher default). A console left half hands the row to the shared R45
       classifier; a licence delivery keeps the generic software route."""

    parts = slot(name)
    if parts is None:
        return ("GamersOutlet: no '(<delivery> / <region>)' slot in the title — the region "
                "is never implicit here (R48)")
    delivery, region = parts
    kind = compound_region_kind(region)
    if kind is None:
        return (f"GamersOutlet: unknown region slot {region!r} — not in the shared "
                "vocabulary (R48)")
    if kind[0] == "forbidden":
        return forbidden_reason(region)
    # The title and the slug must MEAN the same region, not spell it the same way: the
    # merchant writes "Global" in the title and "-worldwide" in the slug, "EU" and "-europe",
    # "US" and "-united-states" (audit 2026-09-16 — comparing the two spellings raised a
    # false conflict). Only a genuine disagreement refuses; an unreadable slug run is
    # tolerated, the title is the declaration.
    url_kind = _url_region_kind(url)
    if url_kind is not None and url_kind != kind:
        return (f"GamersOutlet: title/URL region conflict ({region!r} says {kind[1]}, slug "
                f"says {url_kind[1]}) — refusing to guess (R48)")
    up = _norm(delivery)
    if any(w in up.split() or w in up for w in _CONSOLE_WORDS):
        return None                      # the shared console classifier owns this row (R45)
    if up in _LICENCE_DELIVERIES:
        return None                      # software licence — generic route (R20/R27, R31)
    store = _store_of(delivery)
    if store is None:
        return (f"GamersOutlet: unknown delivery slot {delivery!r} — grammar never "
                "observed (R48)")
    if store not in STORE_PLATFORM:
        return (f"GamersOutlet: unknown store {store!r} in the delivery slot — no AKS "
                "platform bucket, never defaulted (R48)")
    return None


def title_region(name: str) -> str | None:
    """The slot's region half → "eu" / "us" / "uk" / "global". Authoritative: it is read
    BEFORE any generic title/URL scan, so a region word inside the PRODUCT name ("Train Sim
    World 4: EU Loco Add-On (PC Steam Key / Global)") can never win over the slot."""

    parts = slot(name)
    return sellable_base(parts[1]) if parts else None


def resolve_name(name: str) -> str:
    """The title handed to AKS resolution: the slot group and the OS group removed, wherever
    they sit. "Autodesk AutoCAD 2022 (Windows) (Lifetime/ Global) Commercial Version" →
    "Autodesk AutoCAD 2022 Commercial Version"."""

    text = re.sub(r"\s+", " ", name or "").strip()
    span = _slot_span(text)
    if span is not None:
        text = (text[: span[0]] + " " + text[span[1] :]).strip()
    text = re.sub(r"\s*\(\s*(?:PC|Mac|Windows|PC\s*/\s*Mac)\s*\)\s*", " ", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–,")
    return text or (name or "").strip()


CONFIG = make_config(
    "GamersOutlet",
    domain="gamers-outlet.net",
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    url_platform=url_platform,
    notes=(
        "feed store id 31. R48: the '(<delivery> / <region>)' slot is mandatory (the "
        "merchant writes 'Global' explicitly, 20/20), its region vocabulary is the shared "
        "one and its store vocabulary is STORE_PLATFORM — anything else fails closed. "
        "Off the safe-auto allowlist: supervised dry-run first (one region value and no "
        "console row observed so far)."
    ),
)
