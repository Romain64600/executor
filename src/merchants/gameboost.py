"""GameBoost (feed store 157) — the title grammar, declared 2026-09-15.

**History — why this file exists and why it fails closed on the region.** A GameBoost
data-entry run was CANCELLED live on 2026-07-15 (`[R27]`, CHANGELOG): Steam offers were
being entered as Publisher because the titles of the day carried no platform token and
GameBoost's truth lived on its own offer page, which this pipeline cannot fetch
(Cloudflare blocks it). Romain, that day: *"il y a des offres steam qu'on détecte en
publisher, ça c'est seulement renseigné sur la page marchand."* The 33-candidate batch was
dropped before validation; the store has been off the safe-auto allowlist ever since
(`src/admin/auto_merchants.py`). Re-audited 2026-09-15 on the live feed (store 157, page 1,
100 rows): the titles NOW declare the platform in the great majority of rows, and the
region in about half — so part of the feed is enterable from the title alone, and the rest
still is not. This module reads what the title declares and **skips everything else**; it
never opens the merchant page (still unfetchable) and never guesses.

Grammar (feed title), parsed from the END::

    <Game>[ | <Edition>][ (<Edition>)][ (DLC)] (<Platform phrase>)[ (<REGION>)]
    <Game>[ (PC)] - <Platform> [CD ]Key[, PC][ - <REGION>]
    <Game> <Platform> Key[ <REGION>]

Real rows (2026-09-15)::

    Wardogs | Supporter Edition (PC) - Steam Key - United States   → STEAM, us
    Hunt: Showdown 1896 - Bones and Bounties (PC) - Steam Key - GLOBAL → STEAM, global
    Stronghold 2: Steam Edition Steam Key EU                        → STEAM, eu ("Steam
                                                                      Edition" stays in
                                                                      the name — the peel
                                                                      is anchored at the end)
    Sekiro: Shadows Die Twice (GOTY) (Xbox One) (EU)                → console row, eu
    Sid Meier's Civilization VII (Xbox One/ Xbox Series X|S) (EU)   → cross-gen, eu
    SCUM Eastern Furniture DLC (PC) - Steam Key - ROW               → forbidden region: ROW
    Wardogs (PC) - Steam Key - Turkey                               → forbidden region: TURKEY
    Adaptory (Steam)                                                → NO region → skip [R47]
    Command & Conquer 3: Kane's Wrath (DLC) (EA App)                → NO region → skip [R47]
    Razer · Chile · 500 CLP                                         → not a game (gift card)

`[R47]` **the region is MANDATORY in a GameBoost title (2026-09-15).** Unlike Kinguin or
MMOGA — where "no code" IS the merchant's way of writing "global" — GameBoost spells its
global rows out (`GLOBAL`, `Global`, `ROW`) and leaves the slot EMPTY on rows whose region
is only on the merchant page. 41 of the 100 rows of page 1 carry no region word. Entering
them on the generic implicit-GLOBAL default would file region-locked keys worldwide, which
is exactly the failure mode `[R27]` was opened for. So a title with no region slot is a
fail-closed ``precheck`` skip, never GLOBAL(2). Lifting it needs the merchant page — the
same blocker as 2026-07-15, not a rule to loosen here.

Non-game listings (GameBoost is first a boosting / accounts marketplace): the game-key
listings are flat URLs ending in ``-00-<id>``; gift cards and top-ups live under a
``/gift-cards/`` path segment and write their titles with middle dots ("Razer · Chile ·
500 CLP"). Both are categorical skips.

Self-contained: imports only ``src.merchant_config`` and ``src.merchants.common`` (the
shared region vocabulary) — never ``src.matcher`` nor ``src.console_keys``
(``src/merchants/__init__.py`` for the dependency direction).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    forbidden_reason,
    make_config,
    region_alternation,
    sellable_base,
    skip_not_a_game,
)

# ── title grammar ────────────────────────────────────────────────────────────────────
# The platform phrase GameBoost writes, either inside parentheses ("(Steam)", "(Xbox One/
# Xbox Series X|S)", "(Xbox Series X/S, Windows 10)") or as a "- <Platform> Key" run.
# Vocabulary only — the platform DETECTION itself stays the generic title read (like
# Kinguin, R32b): this module peels the phrase for the slug and anchors the region slot.
_PLATFORM_WORD = (
    r"Steam|GOG(?:\.com)?|Epic\s*Games(?:\s*Store)?|Epic|EA\s*App|EA\s*Play|Origin|"
    r"Ubisoft\s*Connect|Ubisoft|Uplay|Rockstar(?:\s*Games)?|Battle\.?net|Blizzard|"
    r"Microsoft\s*Store|Xbox\s*Live|Xbox\s*Series\s*X\s*[|/]\s*S|Xbox\s*Series\s*X/S|"
    r"Xbox\s*Series\s*X|Xbox\s*Series\s*S|Xbox\s*Series|Xbox\s*One|Xbox|"
    r"PlayStation\s*5|PlayStation\s*4|PlayStation|PS5|PS4|PSN|"
    r"Nintendo\s*eShop|eShop|Nintendo\s*Switch\s*2|Nintendo\s*Switch|Switch\s*2|Switch|"
    r"Nintendo|Windows\s*1[01]|Win\s*1[01]|Windows|PC|Mac"
)
# Inside ONE platform group GameBoost also abbreviates the continuations ("Xbox/One/Series/
# Xbox/Windows 11", "Xbox Series X|S", "Xbox One/ Xbox Series X|S"): after the first
# platform word, a bare generation word counts too. Only as a CONTINUATION — a standalone
# "One" or "Series" is never a platform.
_PLATFORM_CONT = rf"{_PLATFORM_WORD}|One|Series\s*X\s*[|/]\s*S|Series\s*X|Series\s*S|Series|X\s*[|/]\s*S|XS"
# One parenthesised platform group may list several platforms, separated by "/" or ",".
_PLATFORM_GROUP = rf"(?:{_PLATFORM_WORD})(?:\s*[/,]\s*(?:{_PLATFORM_CONT}))*"
# Delivery words GameBoost writes after the platform run. "Gift" is one of them ("METAL GEAR
# SOLID V: GROUND ZEROES Steam Gift GLOBAL"): peeled from the slug here, while the GIFT
# BUCKET itself stays the generic ``detect_region`` read of the raw title (no merchant
# gift_delivery hook — GameBoost writes the plain word, never an "Altergift").
_DELIVERY = r"(?:\s*(?:CD\s*)?Keys?|\s*Codes?|\s*Gifts?)"
_REGION = region_alternation()

# A trailing region slot: " - GLOBAL", " (EU)", " ROW", " (NORTH AMERICA)".
_REGION_TAIL_RE = re.compile(
    rf"(?:\s*[-–]\s*|\s*\(\s*|\s+)(?P<region>{_REGION})\s*\)?\s*$", re.IGNORECASE)
# A trailing platform / delivery run, with or without parentheses:
# " (Steam)", " - Steam Key", " - Xbox Series X Key, PC", " Steam Key", " (PC)".
_PLATFORM_TAIL_RE = re.compile(
    rf"(?:\s*[-–,]\s*|\s*\(\s*|\s+)(?P<run>{_PLATFORM_GROUP}){_DELIVERY}?"
    rf"(?:\s*,\s*(?:{_PLATFORM_GROUP}))?\s*\)?\s*$", re.IGNORECASE)
# " - Key" / " Key" left alone by the platform peel ("Blasphemous - Steam - Key (…)").
_BARE_DELIVERY_RE = re.compile(r"(?:\s*[-–,]\s*|\s*\(\s*)?(?:CD\s*)?(?:Keys?|Codes?|Gifts?)\s*\)?\s*$",
                               re.IGNORECASE)

# ── non-game listings ────────────────────────────────────────────────────────────────
# GameBoost sells boosting, accounts, gift cards and top-ups next to its game keys. The
# game-key listings are flat URLs ending in "-00-<id>"; everything else is a category path
# ("/gift-cards/razer/chile/500-clp", "/valorant/gift-cards/singapore/26-sgd",
# "/<game>/accounts/…", "/<game>/boosting/…").
_GAME_URL_RE = re.compile(r"-00-\d+$")
_CATEGORY_MARKERS = (
    ("gift-cards", "GIFT CARD"), ("gift-card", "GIFT CARD"), ("top-up", "TOP-UP"),
    ("top-ups", "TOP-UP"), ("accounts", "ACCOUNT"), ("account", "ACCOUNT"),
    ("boosting", "BOOSTING"), ("boost", "BOOSTING"), ("coaching", "COACHING"),
    ("items", "ITEMS"), ("currency", "CURRENCY"), ("skins", "SKINS"),
)


def _category_marker(url: str) -> str | None:
    """The non-game category a GameBoost URL path declares, or None for a game-key URL."""

    path = urlsplit(url or "").path.strip("/").lower()
    if not path:
        return None
    segments = path.split("/")
    if len(segments) == 1 and _GAME_URL_RE.search(segments[0]):
        return None                      # "<slug>-00-<id>" — a game-key listing
    for segment in segments:
        for marker, label in _CATEGORY_MARKERS:
            if segment == marker:
                return label
    return "NON-GAME LISTING"


# ── hooks ────────────────────────────────────────────────────────────────────────────
def region_slot(name: str) -> str | None:
    """The region word GameBoost writes at the END of the title, verbatim ("United States",
    "GLOBAL", "EU", "ROW", "NORTH AMERICA"), or None when the slot is empty.

    Read from the END so a game NAME carrying a region word ("Stronghold 2: Steam Edition",
    "Pro Evolution Soccer 2015 (EU)") is never mined mid-title: only the trailing slot
    counts. The short codes are case-sensitive in the shared vocabulary ("Us" in "The Last
    of Us" is not a code)."""

    m = _REGION_TAIL_RE.search(name or "")
    return m.group("region").strip() if m else None


def precheck(name: str, url: str) -> str | None:
    """GameBoost's categorical skips, in order:

    1. a non-game listing (gift card / top-up / account / boosting / items) → not a game;
    2. a trailing region word that is a LOCK → ``forbidden region: <LABEL>``;
    3. `[R47]` **no region word at all → fail-closed skip** (the region is only on the
       merchant page, which is unfetchable — never the generic implicit GLOBAL)."""

    marker = _category_marker(url)
    if marker is not None:
        return skip_not_a_game(marker)
    slot = region_slot(name)
    if slot is None:
        return ("GameBoost: no region in the title — region only on the merchant page, "
                "not fetchable (R47)")
    return forbidden_reason(slot)


def title_region(name: str) -> str | None:
    """"… - Steam Key - United States" → "us"; "… (EU)" → "eu"; "… - GLOBAL" → "global".
    A lock or an empty slot never reaches here (``precheck`` skipped the row first)."""

    slot = region_slot(name)
    return sellable_base(slot) if slot else None


def resolve_name(name: str) -> str:
    """The title handed to AKS resolution, with the trailing region / platform / delivery
    run peeled: "Wardogs | Supporter Edition (PC) - Steam Key - United States" → "Wardogs |
    Supporter Edition". The peel is ANCHORED AT THE END and applied at most a few times, so
    a platform word inside the game's own name survives ("Stronghold 2: Steam Edition Steam
    Key EU" → "Stronghold 2: Steam Edition")."""

    text = re.sub(r"\s+", " ", name or "").strip()
    text = _REGION_TAIL_RE.sub("", text).rstrip(" -–,")
    # "(PC) - Steam Key" / "- Steam - Key" = several trailing runs, peeled one at a time
    # (delivery word first, so a "<Platform> - Key" spelling collapses too).
    for _ in range(4):
        stripped = _BARE_DELIVERY_RE.sub("", text).rstrip(" -–,")
        stripped = _PLATFORM_TAIL_RE.sub("", stripped).rstrip(" -–,")
        if stripped == text or not stripped:
            break
        text = stripped
    return text or (name or "").strip()


def console_region_slot(name: str) -> str | None:
    """The console rows use the SAME trailing slot ("… (Xbox One) (EU)", "… - Xbox Live Key
    - United States") — hand the classifier the raw text."""

    return region_slot(name)


CONFIG = make_config(
    "GameBoost",
    domain="gameboost.com",
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    console_region_slot=console_region_slot,
    notes=(
        "feed store id 157. Platform stays TITLE-sourced (generic read, like Kinguin) — "
        "the offer page is Cloudflare-blocked (R27, 2026-07-15) and is never fetched. "
        "R47: a title with no region word is skipped, never entered GLOBAL."
    ),
)
