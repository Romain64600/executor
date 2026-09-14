"""GameSeal (feed store 126) — the title grammar, declared (2026-09-14, Romain's rule R32 / R45).

Never swept in safe-auto (docs/MERCHANTS.md: « non, dry-run d'abord »). The only data is
the July 2026 sweep (``runs/20260715-151202-gameseal``, 1 610 rows — 674 top-ups, 238
diamonds …) plus a 2-row by-urls run. Grammar seen there::

    <Game> [(DLC)] (<Platform>) <Store> <Delivery> - <REGION>        ("Porter in the Castle (PC) Steam Key - GLOBAL")
    <Game> - <n> <Currency> Direct Top-Up - <REGION>                   (top-ups, generic category skips)
    <Product> <Amount> <CCY> Key - <REGION>                            (gift cards)

* ``<Store> <Delivery>`` — ``Steam Key`` 219, ``Steam Gift`` (with a dash or an en-dash
  before the region: "Steam Gift – GLOBAL"), ``Xbox Live Key`` 17, ``GOG.com Key`` 9,
  ``Official website Key`` 13, ``Epic Games Key``, ``Ubisoft Connect Key``, ``EA App Key``,
  ``PSN Key``, ``Nintendo Key``, ``Microsoft Store Key``, ``Rockstar Games Launcher Key``,
  ``Battle.net Key`` …
* ``<REGION>`` — the UPPERCASE tail after the last dash: GLOBAL 279, EU 21, UNITED STATES
  18, UNITED KINGDOM 15, CANADA 12, ROW 6, EMEA 3, BELGIUM 2, NORTH AMERICA 1, AU 1,
  EU/NA 1. Always a region slot → an uppercase tail outside the vocabulary fails closed.
* ``(<Platform>)`` — ``(PC)`` 251; console (R45): ``(Xbox One / Xbox Series X|S)`` 15,
  ``(PC / Xbox One / Xbox Series X|S)`` 2, ``(Xbox 360 / Xbox One)`` 2, ``(PS4 / PS5)`` 2,
  ``(PS4)`` 1, ``(Nintendo Switch)`` 2 — read by the shared console grammar.

Real rows::

    Destroy All Humans! (PC) Steam Key - AU                          → forbidden region: AUSTRALIA (was "extra words: ['AU']")
    lastminute.com Travel Gift Card 5 EUR Key - BELGIUM              → forbidden region: BELGIUM
    Resident Evil 7: Biohazard Gold Edition (PC) Steam Key - EMEA    → forbidden region: EMEA
    War Thunder - US Starter Bundle (DFC) (PC) Steam Gift – GLOBAL   → global (en dash)
    Another World - 20th Anniversary Edition (Xbox One / Xbox Series X|S) Xbox Live Key - EU → slot "EU"

URL: ``gameseal.com/<slug>-<platform tokens>-<store>-key-<region>``
(``…-xbox-one-xbox-series-x-s-xbox-live-key-eu``, ``…-xbox-360-xbox-one-xbox-live-key-united-states``);
a second shape ``gameseal.com/detail/<hex id>`` carries nothing.

Hooks: ``domain`` (docs/MERCHANTS.md — the host of the July rows), ``title_region`` /
``precheck`` (the explicit tail read; AU / BELGIUM were outside the generic vocabulary),
``console_region_slot``, ``console_url_families`` (Xbox 360 → the R45 skip). The PC grammar
is to be re-read at the first dry-run. Pure functions of the feed row; no matcher /
console_keys import.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    SKIP_XBOX_360,
    compound_region_kind,
    make_config,
    normalise_region_text,
    sellable_base,
)

# The words that close the product / delivery part before the " - <REGION>" tail (a
# delivery word, or a subscription length: "Xbox Game Pass Premium 1 Month - EU").
_DELIVERY = (
    r"Keys?|Gift|Top-?Up|Card|Code|Account|Subscription|Pass|Voucher|Points|Coins|Bundle|"
    r"Months?|Days?|Years?|Trial|Non-Stackable"
)
_REGION_TEXT = r"[A-Z][A-Z0-9 /&+,]{0,40}"
_TAIL_RE = re.compile(
    rf"(?:{_DELIVERY})\s*[-–—]\s*(?P<region>(?-i:{_REGION_TEXT}))\s*$", re.IGNORECASE
)


def region_tail(name: str) -> str | None:
    """The uppercase region text after the last dash, verbatim ("GLOBAL", "EU", "UNITED
    STATES", "AU", "EU/NA"), or None."""

    m = _TAIL_RE.search(name or "")
    text = m.group("region").strip() if m else ""
    return text or None


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """A tail region that is not sellable → ``forbidden region: <LABEL>``; a tail outside
    the vocabulary → ``forbidden region: <TEXT>`` (fail-closed); otherwise None."""

    text = region_tail(name)
    if not text:
        return None
    kind = compound_region_kind(text)
    if kind is None:
        return f"forbidden region: {normalise_region_text(text)}"
    return f"forbidden region: {kind[1]}" if kind[0] == "forbidden" else None


def title_region(name: str) -> str | None:
    """" - GLOBAL" → "global", " - EU" → "eu", " - UNITED STATES" → "us", " - UNITED
    KINGDOM" → "uk"; no tail → None."""

    text = region_tail(name)
    return sellable_base(text) if text else None


# ── hooks (R45 console contract) ─────────────────────────────────────────────────────
def console_region_slot(name: str) -> str | None:
    """The " - <REGION>" tail, verbatim ("EU", "GLOBAL", "UNITED STATES")."""

    return region_tail(name)


_URL_RUN_RE = re.compile(
    r"-(?P<run>(?:(?:pc|ps4|ps5|xbox-360|xbox-one|xbox-series-x-s|nintendo-switch-2|nintendo-switch)-)+)"
    r"(?:[a-z0-9]+-){0,4}?(?:key|gift)-"
)
_URL_TOKEN_FAMILY = {
    "xbox-one": "XBOX_ONE", "xbox-series-x-s": "XBOX_SERIES", "ps4": "PS4", "ps5": "PS5",
    "nintendo-switch-2": "SWITCH2", "nintendo-switch": "SWITCH",
}


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """Families the GameSeal slug declares: ``…-xbox-one-xbox-series-x-s-xbox-live-key-eu``
    → XBOX_ONE, XBOX_SERIES; ``…-ps4-ps5-psn-key-…`` → PS4, PS5; ``…-xbox-360-xbox-one-…``
    → the R45 Xbox 360 skip; nothing recognised → None."""

    path = urlsplit(url or "").path.lower()
    m = _URL_RUN_RE.search(path)
    if not m:
        return None
    if "xbox-360" in m.group("run"):
        return SKIP_XBOX_360
    families: list[str] = []
    for token in re.findall(r"xbox-series-x-s|xbox-one|nintendo-switch-2|nintendo-switch|ps4|ps5", m.group("run")):
        fam = _URL_TOKEN_FAMILY[token]
        if fam not in families:
            families.append(fam)
    return tuple(families) or None


CONFIG = make_config(
    "GameSeal",
    domain="gameseal.com",
    precheck=precheck,
    title_region=title_region,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    notes=("feed store 126 — never swept in safe-auto (dry-run first, Romain 2026-09-11); "
           "grammar from the July 2026 sweep: '<Game> (<Platform>) <Store> Key - <REGION>' (2026-09-14)"),
)
