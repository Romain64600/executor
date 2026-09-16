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
  account = a Steam GIFT — Romain's ruling, 2026-09-14, see below), ``Manual Top-Up`` (19),
  ``Account`` (8, the generic STEAM ACCOUNT skip), ``Key``, ``Gift``.
* ``<Region name>`` — in full letters, IMMEDIATELY before the store phrase: Europe 118,
  North America 42, United States 10, United Kingdom 3, Asia 3, Mexico 2, China / Turkey /
  EMEA / Americas / Germany / Luxembourg / United Arab Emirates / Canada 1 (+ the console
  rows' Europe 75 / United States 31). No name → the URL slot decides (``-steam-global-``,
  read by the generic scan) — implicit GLOBAL otherwise.

Real rows::

    Broken Sword - Shadow of the Templars: Reforged Europe Steam CD Key   → eu, "Broken Sword - Shadow of the Templars: Reforged"
    Mato Anomalies North America Steam Altergift                          → forbidden region: NORTH AMERICA
    Thief Simulator Europe Steam Altergift                                → STEAM, GIFT EU (259), "Thief Simulator"
    Seafrog Steam Altergift  (…/seafrog-steam-global-altergift-…)         → STEAM, GIFT (25)
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
(which does not know "Altergift").

**Altergift = Steam Gift — Romain's ruling (2026-09-14): « Steam Altergift = Steam Gift on
rentre sous gift tous les altergifts ».** A "… Steam Altergift" row (216 / 592 of the batch)
is ENTERED as a Steam GIFT: ``gift_delivery`` answers True for a Steam Altergift whose URL
agrees, and ``detect_region`` layers the Steam GIFT bucket on the base region the title /
URL declare — GIFT (25) for no region / Global, GIFT EU (259) for Europe, GIFT US (2577) and
GIFT UK (2572) for those bases (`[R50]`, 2026-09-16 — Romain: « si ça existe le fichier
marchand ne devrait pas affirmer le contraire, fix la config marchand »: this file used to
state that no ``gift_us`` / ``gift_uk`` existed in ``REGION_IDS`` and that a US / UK row
failed closed; the buckets were in the live AKS dropdown all along and are now mapped, so
those rows ENTER — the safety property is untouched, a locked gift never widens to the
global gift 25); a forbidden region (North America, Americas…) is still the precheck skip. "Altergift" is never a product word: ``guard_name`` drops that
word — and nothing else — from the title the identity guards read (R16 used to count it:
"extra words: ['ALTERGIFT']"), ``resolve_name`` drops it for the slug. The platform is STEAM
(``explicit_platform`` already collocates STEAM with ALTERGIFT). Formerly the open question
OPEN_QUESTION_ALTERGIFT (an explicit "skip category: ALTERGIFT" precheck, removed).

Two fail-closed gates on that ruling (review fixes, 2026-09-14 — ``altergift_verdict``,
read by ``precheck`` and ``gift_delivery``; AGENTS.md "Fail-closed behavior: if anything is
uncertain, stop"):

* **the URL must agree.** K4G writes the delivery in the slug too (``-altergift-`` /
  ``-alter-gift-``; 217 / 218 Altergift rows of the batch). ONE row said otherwise — offer
  101030313 "Trine 5: A Clockwork Conspiracy Steam Altergift", slug ``…-steam-global-instant-
  cd-key-48V2PFDZ``: the title says gift, the URL says key. Which bucket class is right
  (Steam GIFT 25 or Steam key GLOBAL 2) cannot be known from the row → "K4G delivery
  conflict: title Altergift but URL says cd-key (no altergift segment) — not entered". A
  slug with NO delivery segment at all is outside the K4G URL grammar → the same refusal
  ("URL carries no altergift segment"); the mirror conflict (title "CD Key", slug
  ``-alter-gift-``; 0 rows) is refused too — the generic ``-gift-`` read would have filed a
  key under GIFT (25).
* **Steam only.** The ruling names the mechanism: « Steam Altergift = Steam Gift » — an
  Altergift is a Steam gift sent from a K4G account; 216 / 216 grammar rows say "Steam"
  (the 2 out-of-grammar rows "… Steam Europe Altergift" too). An Altergift whose store
  phrase is not Steam ("Battle.net Altergift", "Steam / Epic Games Altergift") or absent is
  a grammar never seen → "K4G Altergift outside the Steam collocation … — not entered",
  never another platform's GIFT bucket (Battle.net 570 / 567 exist), never a plain key.

Pure functions of the feed row; no matcher / console_keys import.
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

# DECIDED (Romain 2026-09-14): « Steam Altergift = Steam Gift on rentre sous gift tous les
# altergifts ». The word, whole and case-insensitive ("Altergift" in the title, "altergift" /
# "alter-gift" in the slug): the delivery marker of a Steam gift sent from a K4G account —
# a Steam GIFT bucket row (gift_delivery), never a product word (guard_name / resolve_name).
_ALTERGIFT_RE = re.compile(r"\bAltergift\b", re.IGNORECASE)
# The slug's delivery segments (review fix 2026-09-14, finding [1] — the URL must agree with
# the title's "Altergift"): a gift segment "altergift" / "alter-gift" (217 / 218 rows), the
# key segment "cd-key" ("…-steam-global-instant-cd-key-48V2PFDZ", the Trine 5 row).
_URL_GIFT_SEGMENT_RE = re.compile(r"(?:^|[-/])(?:altergift|alter-gift)(?:[-/]|$)")
_URL_KEY_SEGMENT_RE = re.compile(r"(?:^|[-/])cd-key(?:[-/]|$)")
_STEAM_RE = re.compile(r"\bSteam\b", re.IGNORECASE)
# A store / console phrase that is NOT Steam, anywhere in an out-of-grammar title (review fix
# 2026-09-14, finding [4] — « Steam Altergift = Steam Gift »: the Steam collocation is part
# of the ruling). The bare "PC" / "Mac" / "Windows" items are not stores; a bare "Origin" is
# a name word for the matcher too (R14) and is left out.
_STORE_ITEM = (
    r"GOG(?:\.com)?|Epic\s+Games(?:\s+Store)?|EA\s+App|EA\s+Origin|Ubisoft\s+Connect|Uplay|"
    r"Rockstar(?:\s+Games)?(?:\s+Launcher)?|Battle\.net|Microsoft\s+Store|Official\s+Website"
)
_OTHER_PLATFORM_RE = re.compile(
    rf"\b(?:{_STORE_ITEM}|XBOX|PS4|PS5|PSN|PlayStation|Nintendo)\b", re.IGNORECASE
)

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
    """The title carries the whole word ALTERGIFT (case-insensitive) — K4G's Steam-gift
    delivery ("Seafrog Steam Altergift"); "Thief Simulator Europe Steam CD Key" does not."""

    return _ALTERGIFT_RE.search(name or "") is not None


def drop_altergift(name: str) -> str:
    """``name`` without the word "Altergift" — and nothing else (whitespace collapsed);
    unchanged when the word is absent."""

    if not is_altergift(name):
        return name or ""
    return re.sub(r"\s+", " ", _ALTERGIFT_RE.sub(" ", name)).strip()


def is_steam_altergift(name: str) -> bool:
    """The title is an Altergift AND its store phrase is Steam — Romain's « Steam Altergift
    = Steam Gift » (2026-09-14). In the grammar: the run right before "Altergift" is exactly
    "Steam" ("Seafrog Steam Altergift"; "Seafrog Battle.net Altergift" and "Seafrog Steam /
    Epic Games Altergift" are not). Outside the grammar (the batch's 2 "… Steam Europe
    Altergift" rows): the whole word Steam is present and no other store / console phrase
    is ("Some ALTERGIFT Thing" is not)."""

    if not is_altergift(name):
        return False
    m = parse_title(name)
    if m is not None:
        return (m.group("delivery").upper() == "ALTERGIFT"
                and re.sub(r"\s+", " ", m.group("run").strip()).upper() == "STEAM")
    return _STEAM_RE.search(name) is not None and _OTHER_PLATFORM_RE.search(name) is None


def url_delivery(url: str) -> str | None:
    """What the K4G slug says about the delivery: ``"gift"`` for an "altergift" /
    "alter-gift" segment (it wins when both are present: "…-cd-key-alter-gift-8Z9GIX0E"
    is a gift row), ``"key"`` for a "cd-key" segment, None when the slug carries neither
    (outside the K4G URL grammar). The query string never speaks for the product."""

    path = urlsplit(url or "").path.lower()
    if _URL_GIFT_SEGMENT_RE.search(path):
        return "gift"
    if _URL_KEY_SEGMENT_RE.search(path):
        return "key"
    return None


def altergift_verdict(name: str, url: str) -> str | None:
    """The one Altergift decision of the K4G grammar, shared by ``precheck`` and
    ``gift_delivery`` (Romain 2026-09-14: « Steam Altergift = Steam Gift on rentre sous gift
    tous les altergifts » + the fail-closed rule — review fixes of the same day):

    * ``"gift"`` — a Steam Altergift whose slug agrees ("-altergift-" / "-alter-gift-"):
      entered as the Steam GIFT bucket (217 / 218 rows of the 2026-09-12 batch);
    * a skip reason (str) — the title says Altergift but the store phrase is not Steam
      (never seen; never another platform's gift bucket, never a plain key), or the slug
      contradicts / says nothing ("Trine 5: A Clockwork Conspiracy Steam Altergift" on
      ``…-steam-global-instant-cd-key-48V2PFDZ``: the only such row — gift or key cannot be
      known from the row), or the mirror conflict (title "CD Key" / "Key", slug
      "-alter-gift-"; 0 rows — the generic "-gift-" read would file a key under GIFT);
    * None — not an Altergift row at all: the generic read decides.
    """

    if is_altergift(name):
        if not is_steam_altergift(name):
            return ("K4G Altergift outside the Steam collocation (title's store phrase is not "
                    "Steam) — not entered (Romain 2026-09-14: « Steam Altergift = Steam Gift »)")
        said = url_delivery(url)
        if said == "gift":
            return "gift"
        if said == "key":
            return ("K4G delivery conflict: title Altergift but URL says cd-key (no altergift "
                    "segment) — not entered (2026-09-14)")
        return ("K4G delivery conflict: title Altergift but URL carries no altergift segment "
                "— not entered (2026-09-14)")
    m = parse_title(name)
    if m is not None and m.group("delivery").upper() in ("CD KEY", "KEY") and url_delivery(url) == "gift":
        return ("K4G delivery conflict: title CD Key but URL says altergift — not entered "
                "(2026-09-14)")
    return None


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """Categorical skips of the K4G grammar, before the generic scans:
    1. a region name that is not sellable → ``forbidden region: <LABEL>`` (a sellable name /
       no name → title_region + the generic URL slot);
    2. the Altergift gates of :func:`altergift_verdict` — a non-Steam Altergift or a
       title / URL delivery conflict → its fail-closed reason (review fixes 2026-09-14).
    A Steam Altergift whose slug agrees is NOT a skip (Romain 2026-09-14: entered as a Steam
    gift — see gift_delivery)."""

    text = region_text(name)
    reason = forbidden_reason(text) if text else None
    if reason:
        return reason
    verdict = altergift_verdict(name, url)
    return verdict if verdict not in (None, "gift") else None


def gift_delivery(name: str, url: str) -> bool | None:
    """K4G's own gift-delivery verdict for ``detect_region`` (Romain 2026-09-14: « on rentre
    sous gift tous les altergifts »): True when :func:`altergift_verdict` says ``"gift"`` —
    a Steam Altergift whose slug agrees → the Steam GIFT bucket layered on the base region
    (25 / 259); None otherwise → the generic read decides (a "… Steam Gift" row keeps its
    " GIFT " reading; a refused Altergift row was already stopped by ``precheck`` — the
    merchant does not vouch for it, review fix 2026-09-14)."""

    return True if altergift_verdict(name, url) == "gift" else None


def guard_name(name: str) -> str:
    """The title the identity guards (R01 / R16 / R01b) and ``detect_edition`` read: the raw
    title with the word "Altergift" dropped — nothing else ("Thief Simulator Europe Steam
    Altergift" → "Thief Simulator Europe Steam"; region / store words stay and are the
    guards' usual noise, edition words stay and are weighed as before)."""

    return drop_altergift(name) or name


def title_region(name: str) -> str | None:
    """"Game Europe Steam CD Key" → "eu"; "Game United States …" → "us"; no name → None
    (the generic scan reads the URL's ``-global`` / ``-united-states-`` slot)."""

    text = region_text(name)
    return sellable_base(text) if text else None


def resolve_name(name: str) -> str:
    """"Kingdom Two Crowns Call of Olympus Europe Steam CD Key" → "Kingdom Two Crowns Call
    of Olympus" (same first slug as the generic peel; edition words kept); "Seafrog Steam
    Altergift" → "Seafrog" (the slug is the game's, never "…-altergift"). A title outside
    the grammar is unchanged but for the word "Altergift" (2026-09-14)."""

    m = parse_title(name)
    if m is None:
        return drop_altergift(name) or name
    return m.group("head").strip() or name


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
    guard_name=guard_name,                # "Altergift" is never a product word (Romain 2026-09-14)
    gift_delivery=gift_delivery,          # "… Steam Altergift" = Steam GIFT bucket when the URL agrees (Romain 2026-09-14)
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    notes=("feed store 92 (&p=N pagination); title '<Game> [Edition] [<Region name>] <Store> "
           "CD Key|Altergift' with no separators — region = full name before the store; "
           "Altergift = Steam gift, entered when the slug agrees (2026-09-14)"),
)
