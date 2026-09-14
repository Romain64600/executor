"""K4G (feed store 92) — the title grammar, declared (2026-09-14, Romain's rule R32 / R45).

Grammar seen on the 2026-09-12 batch (``runs/20260912-020000-auto-k4g-s92-p1..7``, 592
rows) — NO parentheses, NO dash separators (the dashes are the product's own: "Endless
Space - Disharmony")::

    <Game> [<Edition>] [<Region name>] <Store phrase> <Delivery>

* ``<Store phrase>`` — PC: ``Steam`` (345 rows: 129 "Steam CD Key" + 216 "Steam
  Altergift"), ``Epic Games``, ``Ubisoft Connect``, ``Battle.net``, ``GOG``, ``EA App`` /
  ``Ea App``; console (R45): ``XBOX One/Series X|S``, ``XBOX Series X|S``, ``PC/XBOX
  One/Series X|S``, ``XBOX One/PC/XBOX Series X|S``, ``PS5``, ``PS4/PS5``, ``Nintendo
  Switch``, ``Nintendo Switch 2``, ``XBOX Live`` (passes / cards) — the families are read
  by the shared console grammar; a software VENDOR phrase (``EaseUS CD Key``, ``Trend Micro
  CD Key``, ``Microsoft CD Key``) is NOT in this grammar → generic behaviour, unchanged.
* ``<Delivery>`` — ``CD Key`` (222), ``Altergift`` (216: a Steam gift sent from a K4G
  account — no confirmed AKS bucket, 0 candidates ever, see OPEN_QUESTION_ALTERGIFT),
  ``Manual Top-Up`` (19), ``Account`` (8, the generic STEAM ACCOUNT skip), ``Key``, ``Gift``.
* ``<Region name>`` — in full letters, IMMEDIATELY before the store phrase: Europe 118,
  North America 42, United States 10, United Kingdom 3, Asia 3, Mexico 2, China / Turkey /
  EMEA / Americas / Germany / Luxembourg / United Arab Emirates / Canada 1 (+ the console
  rows' Europe 75 / United States 31). No name → the URL slot decides (``-steam-global-``,
  read by the generic scan) — implicit GLOBAL otherwise.

Real rows::

    Broken Sword - Shadow of the Templars: Reforged Europe Steam CD Key   → eu, "Broken Sword - Shadow of the Templars: Reforged"
    Mato Anomalies North America Steam Altergift                          → forbidden region: NORTH AMERICA
    Goblin Vyke: The Thief Tycoon Steam CD Key                            → no name (URL …-steam-global-…)
    Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key             → region slot "Canada"
    Pokémon Scarlet Europe Nintendo Switch 2 CD Key                       → region slot "Europe"
    Mifinity eVoucher 100 DKK Denmark Mifinity CD Key                     → not in the grammar (generic)

URL: ``k4g.com/product/<slug>-[pc-]<platform tokens>[-xbox]-<region>-[instant-]<delivery>-
[<edition>-]cd-key-<8 chars>`` — ``xbox-one-series-x-s``, ``xbox-series-x-s``,
``playstation-5``, ``ps4-ps5``, ``nintendo-switch``, ``nintendo-switch-2``; region slugs
``europe`` / ``united-states`` / ``global`` / ``north-america`` / ``canada`` …

Why the hooks: the generic scan already reads "EUROPE" mid-title (MA8) and the URL's
``-united-states-`` / ``-global`` slots, and FORBIDDEN_REGIONS covers North America /
Asia / Mexico / Canada — the file makes that declaration EXPLICIT and adds what the
generic vocabulary lacks (United Arab Emirates, Luxembourg, Denmark → explicit
``forbidden region`` instead of a 404 slug); ``resolve_name`` peels the region + store +
delivery so the slug is the game's without relying on the generic trailing-phrase peel
(which does not know "Altergift"). Pure functions of the feed row; no matcher /
console_keys import.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    REGION_SLUGS,
    forbidden_reason,
    make_config,
    region_alternation,
    sellable_base,
)

# OPEN QUESTION for Romain (2026-09-14): 216 / 592 rows of the batch are "… Steam
# Altergift" — a Steam gift delivered from a K4G account. AKS has a Steam GIFT bucket (25 /
# 259) but nobody confirmed an Altergift belongs there; today those rows end as a 404 slug
# (144), a forbidden region (29) or "extra words: ['ALTERGIFT']" — never a candidate.
# Until ruled, they are skipped EXPLICITLY (no AKS probe) with the reason below (routed
# "garder" by aks_lists.suggest_target_list).
OPEN_QUESTION_ALTERGIFT = (
    "K4G 'Steam Altergift' rows (216/592 of the 2026-09-12 batch): enter under the Steam "
    "GIFT bucket, or keep skipping? (explicit skip until Romain rules — 2026-09-14)"
)
SKIP_ALTERGIFT = "skip category: ALTERGIFT (K4G gift delivery — no confirmed bucket, question for Romain)"

# ── title grammar ────────────────────────────────────────────────────────────────────
_PC_ITEM = (
    r"PC|Mac|Windows(?:\s+1[01])?|Steam|GOG(?:\.com)?|Epic\s+Games(?:\s+Store)?|EA\s+App|"
    r"EA\s+Origin|Origin|Ubisoft\s+Connect|Uplay|Rockstar(?:\s+Games)?(?:\s+Launcher)?|"
    r"Battle\.net|Microsoft\s+Store|Official\s+Website"
)
_CONSOLE_ITEM = (
    r"XBOX\s+Live|XBOX\s+One|XBOX\s+Series(?:\s*X\s*[|/]\s*S|\s*XS)?|Series(?:\s*X\s*[|/]\s*S|\s*XS)|"
    r"XBOX|PS4|PS5|PS|PSN|PlayStation\s*[45]|Nintendo\s+Switch(?:\s+2)?|Nintendo\s+eShop|Nintendo"
)
_ITEM = rf"(?:{_PC_ITEM}|{_CONSOLE_ITEM})"
_RUN = rf"{_ITEM}(?:\s*/\s*{_ITEM})*"
_DELIVERY = r"CD\s+Key|Key|Altergift|Gift|Account|Manual\s+Top-?Up"
TITLE_RE = re.compile(
    rf"^(?P<head>.*?)(?:\s+(?P<region>{region_alternation()}))?\s+(?P<run>{_RUN})\s+"
    rf"(?P<delivery>{_DELIVERY})\s*$",
    re.IGNORECASE,
)


def parse_title(name: str) -> "re.Match[str] | None":
    """The grammar match (``head`` / ``region`` / ``run`` / ``delivery``), or None for a
    title outside the grammar (software vendors, top-ups, cards) — generic rules apply."""

    return TITLE_RE.match(name or "")


def region_text(name: str) -> str | None:
    """The region name written before the store phrase, verbatim ("Europe", "North
    America", "United Arab Emirates"), or None."""

    m = parse_title(name)
    return m.group("region") if m else None


def is_altergift(name: str) -> bool:
    m = parse_title(name)
    return bool(m and m.group("delivery").upper() == "ALTERGIFT")


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """1. an Altergift delivery → explicit skip (OPEN_QUESTION_ALTERGIFT);
    2. a region name that is not sellable → ``forbidden region: <LABEL>``;
    otherwise None (a sellable name / no name → title_region + the generic URL slot)."""

    if is_altergift(name):
        return SKIP_ALTERGIFT
    text = region_text(name)
    return forbidden_reason(text) if text else None


def title_region(name: str) -> str | None:
    """"Game Europe Steam CD Key" → "eu"; "Game United States …" → "us"; no name → None
    (the generic scan reads the URL's ``-global`` / ``-united-states-`` slot)."""

    text = region_text(name)
    return sellable_base(text) if text else None


def resolve_name(name: str) -> str:
    """"Kingdom Two Crowns Call of Olympus Europe Steam CD Key" → "Kingdom Two Crowns Call
    of Olympus" (same first slug as the generic peel; edition words kept). Unchanged when
    the title is outside the grammar."""

    m = parse_title(name)
    return (m.group("head").strip() or name) if m else name


# ── hooks (R45 console contract) ─────────────────────────────────────────────────────
def console_region_slot(name: str) -> str | None:
    """The region TEXT between the edition and the platform phrase, verbatim ("Europe",
    "United States", "Canada", "Global")."""

    return region_text(name)


_URL_RUN_RE = re.compile(
    r"-(?:pc-)?(?P<run>xbox-one-series-x-s|xbox-series-x-s|xbox-one|playstation-5|playstation-4|"
    r"ps4-ps5|ps5|ps4|nintendo-switch-2|nintendo-switch)(?:-xbox)?-(?P<region>[a-z]+(?:-[a-z]+){0,3}?)"
    r"-(?:instant-)?(?:cd-key|altergift|alter-gift|gift|account)"
)
_URL_RUN_FAMILIES = {
    "xbox-one-series-x-s": ("XBOX_ONE", "XBOX_SERIES"),
    "xbox-series-x-s": ("XBOX_SERIES",),
    "xbox-one": ("XBOX_ONE",),
    "playstation-5": ("PS5",),
    "playstation-4": ("PS4",),
    "ps4-ps5": ("PS4", "PS5"),
    "ps5": ("PS5",),
    "ps4": ("PS4",),
    "nintendo-switch-2": ("SWITCH2",),
    "nintendo-switch": ("SWITCH",),
}


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """Families the K4G slug declares: ``…-xbox-one-series-x-s-xbox-europe-instant-cd-key-…``
    → XBOX_ONE, XBOX_SERIES; ``…-playstation-5-europe-cd-key-…`` → PS5; ``…-nintendo-switch-
    2-europe-cd-key-…`` → SWITCH2. The run must be followed by a KNOWN region slug and the
    delivery ("…-nintendo-switch-2-edition-upgrade-pack-…" is a product name → None)."""

    path = urlsplit(url or "").path.lower()
    for m in _URL_RUN_RE.finditer(path):
        if m.group("region") in REGION_SLUGS:
            return _URL_RUN_FAMILIES[m.group("run")]
    return None


CONFIG = make_config(
    "K4G",
    domain="k4g.com",
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    notes=("feed store 92 (&p=N pagination); title '<Game> [Edition] [<Region name>] <Store> "
           "CD Key|Altergift' with no separators — region = full name before the store (2026-09-14)"),
)
