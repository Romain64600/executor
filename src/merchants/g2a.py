"""G2A (feed store 38) — platform from the URL slug, region from the title tail.

R32b (migrated 2026-08-28): G2A titles are unreliable for the platform; the slug carries it
instead (…-steam-key-…, …-ubisoft-connect-key-…, …-rockstar-…). A green-gift slug
(…-green-gift-key-…) carries NO platform token → None → fail-closed (its real platform
is only on the G2A offer page, which hard-blocks fetches — GMG handling is pending).
``title_is_platform_source=False`` / ``url_platform_scan=True`` / ``offer_page_readable=False``
and the green-gift rules are UNTOUCHED.

Title grammar, declared 2026-09-14 (Romain's rule R32 / R45; 2026-09-12 batch
``runs/20260912-020001-auto-g2a-s38-p1..10``, 806 rows)::

    <Game> [| <Edition>] [(<Platform>[, PC])] - <Store> <Delivery> - <REGION>      (742 rows)
    <Game> <Store> <Delivery> <REGION>                                              (64 rows, old grammar)
    <Game> - <Store> - <Delivery> <REGION>                                          ("The Sapling - Steam - Gift GLOBAL")

* ``<Store> <Delivery>`` — ``Steam Gift`` 590, ``Steam Key`` 56, ``Xbox Live Key`` 37,
  ``Steam Account`` 10, ``Roblox Player Trade`` 7, ``EA App Key``, ``PSN Key``, ``Microsoft
  Store Key``, ``Nintendo eShop Key``, ``Call of Duty Official Key``, ``Xbox Live Gift`` …
* ``<REGION>`` — the UPPERCASE tail after the last dash: GLOBAL 346, EUROPE 224, NORTH
  AMERICA 132, UNITED KINGDOM 12, MENA 5, UNITED STATES 5, CANADA 4, CIS 4, CHINA 2,
  SINGAPORE / SOUTH AFRICA / GERMANY / JAPAN / TURKEY / ROW / POLAND / "EUROPE / NORTH
  AMERICA" 1. It is ALWAYS a region slot (the delivery word precedes it) — an uppercase
  tail outside the vocabulary fails closed as ``forbidden region: <TEXT>``.
* ``(<Platform>)`` — ``(PC)`` 660; console (R45): ``(Xbox Series X/S)`` 15, ``(Xbox Series
  X/S, PC)`` 15, ``(Xbox One)`` 3, ``Xbox One, PC`` (no parens) 2, ``(PS5)`` 2, ``(Nintendo
  Switch 2)`` 1, ``(PC, PS5, PS4, Xbox Series X/S, Xbox One)`` 1 — G2A spells "X/S" and
  lists One and Series as SEPARATE rows; read by the shared console grammar.

Real rows::

    Puzzle Forge Dungeon (PC) - Steam Gift - EUROPE                                   → eu
    Ultimate Zombie Defense 2 (PC) - Steam Key - NORTH AMERICA                        → forbidden region: NORTH AMERICA
    VALORANT Gift Card 45.98 SGD - Riot Key - SINGAPORE                               → forbidden region: SINGAPORE
    Hunt: Showdown 1896 - Sage of Joseon (PC) - Steam Key - EUROPE / NORTH AMERICA    → forbidden region: NORTH AMERICA
    Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM → slot "UNITED KINGDOM"
    Steam Squad Steam Gift GLOBAL                                                     → global (old grammar)

URL: ``g2a.com/<slug>-<platform tokens>[-pc]-<store>-key-<region>-i<id>?___currency=…`` —
``…-xbox-series-x-s-pc-xbox-live-key-united-kingdom-i10000512449018``,
``…-ps5-ps4-xbox-series-x-s-xbox-one-call-of-duty-official-key-…``.

Why the region hooks: the generic tail read (``rsplit(" - ")``) already yields EU / GLOBAL
/ US / UK and FORBIDDEN_REGIONS covers most locks — ``title_region`` / ``precheck`` make
the declaration explicit and close the gap on tails outside the generic vocabulary
(SINGAPORE fell to implicit GLOBAL, saved only by the GIFT CARD skip). Pure functions of
the feed row; no matcher / console_keys import.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    compound_region_kind,
    make_config,
    normalise_region_text,
    sellable_base,
)

_DELIVERY = r"Keys?|Gift|Account|Trade|Code|Card|Top-?Up|Subscription|Pass|Voucher|Points|Coins"
_STORE = (
    r"Steam|GOG(?:\.com)?|Epic\s+Games(?:\s+Store)?|EA\s+App|Origin|Ubisoft\s+Connect|Uplay|"
    r"Rockstar(?:\s+Games)?(?:\s+Launcher)?|Battle\.net|Microsoft\s+Store|Xbox\s+Live|PSN|"
    r"Nintendo\s+eShop"
)
_REGION_TEXT = r"[A-Z][A-Z0-9 /&+,]{0,40}"
# " - <Store> <Delivery> - <REGION>" — the tail after the last dash, uppercase.
_TAIL_RE = re.compile(
    rf"(?:{_DELIVERY})\s*[-–—]\s*(?P<region>(?-i:{_REGION_TEXT}))\s*$", re.IGNORECASE
)
# Old grammar: "<Game> Steam Gift GLOBAL" / "<Game> - Steam - Gift GLOBAL" / "… Steam Key CIS".
_OLD_TAIL_RE = re.compile(
    rf"\s(?:{_STORE})\s*[-–—]?\s*(?:Gift|Key)\s+(?P<region>(?-i:{_REGION_TEXT}))\s*$", re.IGNORECASE
)


def region_tail(name: str) -> str | None:
    """The uppercase region text of the title tail, verbatim ("EUROPE", "NORTH AMERICA",
    "EUROPE / NORTH AMERICA", "SINGAPORE"), or None when the title has no region slot."""

    for rx in (_TAIL_RE, _OLD_TAIL_RE):
        m = rx.search(name or "")
        if m:
            text = m.group("region").strip()
            if text:
                return text
    return None


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """A tail region that is not sellable → ``forbidden region: <LABEL>``; a tail outside
    the vocabulary → ``forbidden region: <TEXT>`` (fail-closed: the slot is always a
    region); no tail / a sellable tail → None."""

    text = region_tail(name)
    if not text:
        return None
    kind = compound_region_kind(text)
    if kind is None:
        return f"forbidden region: {normalise_region_text(text)}"
    return f"forbidden region: {kind[1]}" if kind[0] == "forbidden" else None


def title_region(name: str) -> str | None:
    """" - EUROPE" → "eu", " - GLOBAL" → "global", " - UNITED STATES" → "us", " - UNITED
    KINGDOM" → "uk"; the old "Steam Gift GLOBAL" grammar too; no tail → None."""

    text = region_tail(name)
    return sellable_base(text) if text else None


# ── hooks (R45 console contract) ─────────────────────────────────────────────────────
def console_region_slot(name: str) -> str | None:
    """The " - <REGION>" tail, verbatim ("EUROPE", "UNITED KINGDOM", "CANADA")."""

    return region_tail(name)


_URL_RUN_RE = re.compile(
    r"-(?P<run>(?:(?:pc|ps4|ps5|xbox-one|xbox-series-x-s|nintendo-switch-2|nintendo-switch)-)+)"
    r"(?:[a-z0-9]+-){0,4}?(?:key|gift)-"
)
_URL_TOKEN_FAMILY = {
    "xbox-one": "XBOX_ONE", "xbox-series-x-s": "XBOX_SERIES", "ps4": "PS4", "ps5": "PS5",
    "nintendo-switch-2": "SWITCH2", "nintendo-switch": "SWITCH",
}


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """Families the G2A slug declares before the store key marker (the ``-i<id>`` suffix
    ignored): ``…-xbox-series-x-s-pc-xbox-live-key-united-kingdom-i…`` → XBOX_SERIES;
    ``…-ps5-ps4-xbox-series-x-s-xbox-one-call-of-duty-official-key-…`` → PS5, PS4,
    XBOX_SERIES, XBOX_ONE; ``…-nintendo-switch-2-nintendo-eshop-key-…`` → SWITCH2."""

    path = urlsplit(url or "").path.lower()
    m = _URL_RUN_RE.search(path)
    if not m:
        return None
    families: list[str] = []
    for token in re.findall(r"xbox-series-x-s|xbox-one|nintendo-switch-2|nintendo-switch|ps4|ps5", m.group("run")):
        fam = _URL_TOKEN_FAMILY[token]
        if fam not in families:
            families.append(fam)
    return tuple(families) or None


CONFIG = make_config(
    "G2A",
    title_is_platform_source=False,
    url_platform_scan=True,
    # G2A hard-blocks non-browser fetches (403), so a green-gift's real platform — only
    # on its offer page — is unverifiable yet → fail-closed skip until browser
    # page-opening lands (R32c). The maintained "can't open page" list.
    offer_page_readable=False,
    precheck=precheck,
    title_region=title_region,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    notes=("feed store 38; platform from the slug (R32b), region = the uppercase ' - <REGION>' "
           "title tail (2026-09-14); ?params kept verbatim"),
)
