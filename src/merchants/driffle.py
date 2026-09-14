"""Driffle (feed store 127) — the title grammar, declared (2026-09-14, Romain's rule R32 / R45).

Grammar seen on the 2026-09-12 batch (``runs/20260912-020000-auto-driffle-s127-p1..6``,
464 rows)::

    <Game> [<Edition>] [(<Region>)] [(<Platform>)] - <Store> - <Delivery>
    <Game> (<Region>) (<Platform>) - <Store> Gift            (Battle.net Gift, Steam Gift, Meta Quest Gift)
    <Game> (<Region>) (<Platform>) - <Store> Account         (Ubisoft Connect / Epic Games / League of Legends Account)

* ``(<Region>)`` — the FIRST bracket naming a region: Global 259, Europe 66, United
  States 20, Asia 3, North America 3, MENA 2, Turkey 2, Germany 2, France 2, Austria 2,
  Netherlands 2, United Kingdom 2, "United States / Canada" 1, Poland / Belgium / Egypt /
  South Africa / Hong Kong / ROW / Romania / Latvia / Lithuania 1. Other brackets are NOT
  regions: "(SIEE)", "(Essential)", "(2020)", "(EN)", "(EN/CS)", "(+400 Bonus)", "(DLC)".
* ``(<Platform>)`` — ``(PC)`` 172, ``(PC / Mac)`` 30, ``(PC / Mac / Linux)`` 10; console
  (R45): ``(Xbox Series X|S)`` 31, ``(Xbox One / Xbox Series X|S)`` 28, ``(Xbox One)`` 10,
  ``(PS4 / PS5)`` 8, ``(PS5)`` 5, ``(PS4)`` 5, ``(Nintendo Switch)`` 5, ``(Nintendo Switch
  2)`` 1, ``(PC / Xbox One / Xbox Series X|S)`` = PC declared — read by the shared console
  grammar.
* ``<Store>`` — Steam 113, Xbox Live 82, Battle.net (Gift) 47, PSN 19, Rewarble 18, EA Play
  10, Nintendo 6, Epic Games 5, … ; ``<Delivery>`` — ``Digital Key`` 315 (``Digital Code``
  in some URLs), ``Gift``, ``Account``.

Real rows::

    Fatal Fury City of the Wolves Special Edition (Global) (PC) - Steam - Digital Key   → global
    Uncle Billy's Dream Bundle (Europe) (PC) - Steam - Digital Key                       → eu
    DRAGON BALL Sparking! ZERO (United States / Canada) (PC) - Steam - Digital Key       → forbidden region: CANADA
    Fortnite - 12500 V-Bucks Card (France) - Epic Games - Digital Key                    → forbidden region: FRANCE
    Xbox Game Pass Core (Essential) 1 Month (Latvia) - Xbox Live - Digital Key           → forbidden region: LATVIA
    Mario Kart 8 Deluxe - Booster Course Pass DLC (Hong Kong) (Nintendo Switch) - Nintendo - Digital Key → "Hong Kong"
    Little Nightmares - Tengu Mask DLC (SIEE) (PS4) - PSN - Digital Key                  → no region bracket

URL: ``driffle.com/<slug>-<region>-<platform>-<store>-digital-key-p<id>`` (``-digital-
code-p<id>``), spelling **``xbox-series-xs``** (``-europe-xbox-one-xbox-series-xs-xbox-live-
digital-key-p…``, ``-ps4-ps5-psn-digital-key-``, ``-eu-nintendo-switch-nintendo-digital-code-``);
the edition lives in the slug (``slug_edition_text``, Romain 2026-07-07 — generic, kept).

Why the hooks: the generic parens scan already reads EU / GLOBAL / US in any bracket
(MA8) and the URL ``-united-kingdom-`` slot — ``title_region`` is now the EXPLICIT, tested
source of that read (results identical); ``precheck`` adds the country brackets the
generic FORBIDDEN_REGIONS vocabulary does not know (France, Austria, Netherlands,
Belgium, Egypt, Hong Kong, Latvia, Lithuania, Romania — before this they fell to an
implicit GLOBAL and were only saved by a category skip or a 404 slug). No
``resolve_name`` (the generic parens + tail peel already yields the game slug). Pure
functions of the feed row; no matcher / console_keys import.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    compound_region_kind,
    forbidden_reason,
    make_config,
    sellable_base,
)

_BRACKET_RE = re.compile(r"\(([^()]*)\)")


def region_bracket(name: str) -> str | None:
    """The text of the first bracket that names a region of the vocabulary, verbatim
    ("Europe", "Global", "Hong Kong", "United States / Canada"), or None when no bracket
    is a region ("(SIEE)", "(EN)", "(2020)", "(PC / Mac)" are not)."""

    for group in _BRACKET_RE.findall(name or ""):
        text = group.strip()
        if text and compound_region_kind(text) is not None:
            return text
    return None


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """A region bracket that is not sellable → ``forbidden region: <LABEL>`` (Asia, MENA,
    Turkey, France, Hong Kong, "United States / Canada" → CANADA …); else None."""

    text = region_bracket(name)
    return forbidden_reason(text) if text else None


def title_region(name: str) -> str | None:
    """"(Global)" → "global", "(Europe)" / "(EU)" → "eu", "(United States)" → "us",
    "(United Kingdom)" → "uk"; no region bracket → None (generic URL scan)."""

    text = region_bracket(name)
    return sellable_base(text) if text else None


# ── hooks (R45 console contract) ─────────────────────────────────────────────────────
def console_region_slot(name: str) -> str | None:
    """The region bracket text, verbatim ("Europe", "Global", "Hong Kong")."""

    return region_bracket(name)


_URL_RUN_RE = re.compile(
    r"-(?P<run>(?:(?:pc|mac|linux|ps4|ps5|xbox-one|xbox-series-xs|xbox-series-x-s|"
    r"nintendo-switch-2|nintendo-switch)-)+)(?:xbox-live|psn|nintendo|xbox)-digital-(?:key|code)-p\d+/?$"
)
_URL_TOKEN_FAMILY = {
    "xbox-one": "XBOX_ONE", "xbox-series-xs": "XBOX_SERIES", "xbox-series-x-s": "XBOX_SERIES",
    "ps4": "PS4", "ps5": "PS5", "nintendo-switch-2": "SWITCH2", "nintendo-switch": "SWITCH",
}


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """Families the Driffle slug declares before the console store + delivery tail:
    ``…-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p9988263`` → XBOX_ONE,
    XBOX_SERIES; ``…-ps4-ps5-psn-digital-key-p…`` → PS4, PS5; ``…-eu-nintendo-switch-
    nintendo-digital-code-p…`` → SWITCH; nothing recognised → None."""

    path = urlsplit(url or "").path.lower()
    m = _URL_RUN_RE.search(path)
    if not m:
        return None
    families: list[str] = []
    for token in re.findall(r"xbox-series-x-s|xbox-series-xs|xbox-one|nintendo-switch-2|nintendo-switch|ps4|ps5",
                            m.group("run")):
        fam = _URL_TOKEN_FAMILY[token]
        if fam not in families:
            families.append(fam)
    return tuple(families) or None


CONFIG = make_config(
    "Driffle",
    domain="driffle.com",
    precheck=precheck,
    title_region=title_region,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    console_noise=("Digital Key", "Digital Code"),
    notes=("feed store 127; stock y/n; title '<Game> (<Region>) (<Platform>) - <Store> - Digital "
           "Key' — region = the first bracket of the vocabulary; edition in the URL slug (2026-09-14)"),
)
