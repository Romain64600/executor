"""Kinguin (feed store 58; AKS page merchant 47) — the title grammar, declared (2026-09-14).

Romain's rule (R32, 2026-08-11 → 2026-09-14): « pour la détection région / édition /
plateforme, tu as un fichier de config par marchand ». Until now Kinguin was the inline
``MerchantConfig("Kinguin", domain="kinguin.net")`` registry entry (EXECUTOR_RULES §11) and
everything else was the generic behaviour. This module DECLARES what the 2026-09-12 batch
(``runs/20260912-020001-auto-kinguin-s58-p1..10``, 940 rows) actually writes and implements
the deterministic hooks. Platform stays TITLE-sourced (R32b, Romain: « ça marche
aujourd'hui ») — no ``url_platform`` hook, ``title_is_platform_source`` untouched.

Grammar (title)::

    <Game> [<Edition>] [<REGION>] <Platform phrase> <Delivery> [by Digital Distribution Hub]
           [(valid until <Month> <Year>)]

* ``<Platform phrase>`` — PC: ``PC Steam`` (299 rows), ``Steam``, ``PC Windows [10]``,
  ``PC Ubisoft Connect``, ``PC Epic Games``, ``PC Battle.net``, ``EA App``, ``GOG``,
  ``Rockstar``, ``Microsoft Store``, ``PC Official Website``, ``PC/MAC``; console (R45):
  ``Xbox One / Xbox Series X|S``, ``XBOX One / Xbox Series X|S / PC``, ``Xbox Series X|S``,
  ``PS5``, ``PS4/PS5``, ``Nintendo Switch``, ``Nintendo Switch 2`` — read by the shared
  console grammar (``src/console_keys.py``); here the phrase only anchors the region slot.
* ``<Delivery>`` — ``CD Key`` (the norm), ``Key``, ``Steam Gift`` (5), ``Altergift`` (1),
  ``Account`` (8) / ``Access`` (29 — URL ``-online-account-activation``): account listings,
  never keys; ``Activation Link``.
* ``<REGION>`` — an UPPERCASE 2-letter code (or ``RoW`` / ``NA`` / ``SEA`` / ``UAE`` /
  ``ANZ`` / ``European Union``) IMMEDIATELY before the platform phrase: EU 44, US 11, TR 11,
  NA 9, SEA 7, CA 5, AU 4, RoW 13 + the console rows' CA 83 / AU 77. No code → implicit
  GLOBAL (the generic default). ``Us`` in "Among Us" / "The Last of Us" is never a code
  (mixed case); ``II`` / ``HD`` / ``VR`` / ``PC`` are not in the vocabulary → name words.

Real rows::

    Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key         → region slot "US"
    Crusader Kings III - Royal Court DLC RoW PC Steam CD Key      → forbidden region: ROW
    Call of Duty: World at War SEA PC Steam Gift                  → forbidden region: SOUTH EAST ASIA
    Sons Of The Forest DE PC Steam Altergift                      → forbidden region: GERMANY
    Rocket League UAE PC Steam Gift                               → forbidden region: UNITED ARAB EMIRATES
    Shardstorm PC Steam CD Key                                    → no code, name "Shardstorm"
    Project MIKHAIL: A Muv-Luv War Story PC Steam CD Key (valid until May 2027)
    Blocky Farm XBOX One / Xbox Series X|S Account                → account listing (skip)
    NHL 22 PS4 Access  (…/nhl-22-ps4-access)                      → access listing (skip)

URL: ``kinguin.net/category/<id>/<slug>`` — the slug mirrors the title
(``…-us-xbox-one-xbox-series-x-s-cd-key``, ``-account``, ``-online-account-activation``),
often truncated at ~80 characters, ``?params`` kept verbatim (§4.6).

Why the hooks (measured on the batch, see the 2026-09-14 report):

* ``title_region`` — the generic scan reads " EU " / " UK " but NOT the bare " US " (P2-6b
  keeps the URL "-us" to a trailing slot, and "Among Us" forbids a title-wide read), so
  "Game US PC Steam CD Key" fell to implicit GLOBAL with the slug ``game-us`` (404 → "no
  AKS product page found"). With the grammar slot the row is Steam US on ``game``.
* ``precheck`` — TR / NA / SEA / CA / AU / DE / UAE / ANZ before the platform phrase were
  invisible (not FORBIDDEN_REGIONS words, and the URL code sits mid-slug): they ended as a
  404 skip by luck of the slug. Now an explicit ``forbidden region: <LABEL>`` (routed by
  ``aks_lists.suggest_target_list``), before any AKS probe. ``Account`` / ``Access`` rows
  are account listings → categorical skip.
* ``resolve_name`` — the code and the platform phrase peeled so the slug is the game's.
  The ``(valid until <Month> <Year>)`` note is peeled too (the generic parens strip
  already drops it) — but the R01b guard reads the RAW title, so those 79 rows/batch
  STAY skipped "extra words: ['VALID', 'UNTIL', …]" — see OPEN_QUESTION_VALID_UNTIL.
* ``console_region_slot`` — the same code read, handed to the R45 classifier verbatim.
* ``console_url_families`` — the slug's console run and the account / access markers.

Pure functions of the feed row; no network; no ``src.matcher`` / ``src.console_keys``
import (the registry imports this module).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    FORBIDDEN_WORDS,
    SELLABLE_WORDS,
    forbidden_reason,
    make_config,
    region_kind,
    sellable_base,
    skip_not_a_game,
)

# OPEN QUESTION for Romain (2026-09-14): 79 rows of the 2026-09-12 batch carry a Kinguin
# activation-deadline note "(valid until <Month> <Year>)" (60 of them end as "different/
# expanded product — extra words: ['VALID', 'UNTIL', 'MAY', '2027']"). No ruling is recorded
# (docs/feeds/Kinguin.md lists them among the skips). Until Romain says such keys are
# wanted, the note stays an extra-words SKIP: resolve_name peels it (slug), the identity
# guard keeps the raw title, and it is deliberately NOT in console_noise (that would make
# console rows with the note enterable). To enter them once ruled: add "VALID"/"UNTIL"
# handling in the guard (generic) — not here.
OPEN_QUESTION_VALID_UNTIL = (
    "Kinguin '(valid until <Month> <Year>)' keys: enterable? (79 rows/batch, skipped as "
    "extra words until Romain rules — 2026-09-14)"
)

# ── title grammar ────────────────────────────────────────────────────────────────────
_PC_ITEM = (
    r"PC|Mac|Windows(?:\s+1[01])?|Steam|GOG(?:\.com)?|Epic\s+Games(?:\s+Store)?|EA\s+App|"
    r"EA\s+Origin|Origin|Ubisoft\s+Connect|Uplay|Rockstar(?:\s+Games)?(?:\s+Launcher)?|"
    r"Battle\.net|Microsoft\s+Store|Official\s+Website"
)
_CONSOLE_ITEM = (
    r"Xbox\s+One|Xbox\s+Series(?:\s*X\s*[|/]\s*S|\s*XS)?|Series(?:\s*X\s*[|/]\s*S|\s*XS)|"
    r"Xbox\s*X\s*[|/]\s*S|Xbox|PS4|PS5|PlayStation\s*[45]|Nintendo\s+Switch(?:\s+2)?"
)
_ITEM = rf"(?:{_PC_ITEM}|{_CONSOLE_ITEM})"
_RUN = rf"{_ITEM}(?:\s*/\s*{_ITEM}|\s+{_ITEM})*"
_DELIVERY = (
    r"Digital\s+Download\s+CD\s+Key|CD\s+Key|Key|Gift|Altergift|Account|Access|"
    r"Activation\s+Link"
)
# "(valid until May 2027)" and the comma variant "(valid until May, 2027)" (5 rows).
_VALID_UNTIL = r"\(valid\s+until\s+[A-Za-z]+,?\s+\d{4}\)"
_BY_HUB = r"by\s+Digital\s+Distribution\s+Hub"
# The region slot: Kinguin writes CODES ("EU", "CA", "RoW", "SEA", "UAE"), in capitals —
# every vocabulary word is matched CASE-SENSITIVELY in capitals (a scoped (?-i:) group
# inside the case-insensitive pattern), plus the two spellings Kinguin writes otherwise,
# "RoW" and "European Union". So "Among Us", "Deus Ex GO", "Game II" keep their words and
# a Title-Case country in a game name ("Sad Virus Egypt PC Steam CD Key") is a name word,
# not a lock — the R45 classifier's shared read still speaks for console rows.
_CODE_ALT = (
    r"(?-i:" + "|".join(re.escape(w).replace(r"\ ", r"\s+")
                          for w in sorted({*SELLABLE_WORDS, *FORBIDDEN_WORDS}, key=len, reverse=True))
    + r")|(?-i:RoW)|European\s+Union"
)
TITLE_RE = re.compile(
    rf"^(?P<head>.*?)(?:\s+(?P<region>{_CODE_ALT}))?\s+(?P<run>{_RUN})\s+"
    rf"(?P<delivery>{_DELIVERY})(?:\s+(?P<hub>{_BY_HUB}))?(?:\s*(?P<valid>{_VALID_UNTIL}))?\s*$",
    re.IGNORECASE,
)
_VALID_UNTIL_RE = re.compile(rf"\s*{_VALID_UNTIL}\s*$", re.IGNORECASE)
_ACCOUNT_DELIVERIES = frozenset({"ACCOUNT", "ACCESS"})
_ACCOUNT_URL_RE = re.compile(r"(?:-account|-access)/?$|online-account-activation")


def parse_title(name: str) -> "re.Match[str] | None":
    """The grammar match (groups ``head`` / ``region`` / ``run`` / ``delivery`` / ``hub`` /
    ``valid``), or None when the title is not in the Kinguin grammar (gift cards,
    software "… Key (2 Years / 5 PCs)", mystery boxes) — the generic rules then apply."""

    return TITLE_RE.match(name or "")


def region_text(name: str) -> str | None:
    """The region word written right before the platform phrase, verbatim ("US", "CA",
    "RoW", "European Union"), or None."""

    m = parse_title(name)
    return m.group("region") if m else None


def is_account_listing(name: str, url: str) -> bool:
    """"<Game> <Platform> Account" / "… Access" (URL ``-account`` /
    ``-online-account-activation`` / ``-access``): an account listing, never a key."""

    m = parse_title(name)
    if m and m.group("delivery").upper() in _ACCOUNT_DELIVERIES:
        return True
    path = urlsplit(url or "").path.lower()
    return _ACCOUNT_URL_RE.search(path) is not None


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """Categorical skips of the Kinguin grammar, before the generic scans:
    1. an account / access listing → ``skip category: ACCOUNT (…)`` (never a key);
    2. a region code that is not sellable → ``forbidden region: <LABEL>`` (the matcher
       vocabulary: CA → CANADA, AU → AUSTRALIA, RoW → ROW, SEA → SOUTH EAST ASIA …).
    A sellable code (EU / US / UK / GB / European Union) or no code → None."""

    if is_account_listing(name, url):
        return "skip category: ACCOUNT (Kinguin account / access listing — not a key)"
    text = region_text(name)
    return forbidden_reason(text) if text else None


def title_region(name: str) -> str | None:
    """"Game US PC Steam CD Key" → "us"; "Game EU …" → "eu"; "Game European Union …" →
    "eu"; no code / forbidden code → None (precheck already skipped the latter)."""

    text = region_text(name)
    return sellable_base(text) if text else None


def resolve_name(name: str) -> str:
    """The text handed to AKS resolution: the region code, the platform phrase, the
    delivery word, the "by Digital Distribution Hub" note and the "(valid until …)" note
    peeled ("Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key" → "Hobo: Tough Life").
    A title outside the grammar is returned unchanged (only a trailing validity note is
    dropped)."""

    m = parse_title(name)
    if m is None:
        return _VALID_UNTIL_RE.sub("", name or "") or name
    return m.group("head").strip() or name


# ── hooks (R45 console contract) ─────────────────────────────────────────────────────
def console_region_slot(name: str) -> str | None:
    """The region TEXT next to the platform phrase, verbatim ("US", "CA", "RoW",
    "European Union") — the text → base / label mapping stays in ``console_keys``."""

    return region_text(name)


# Slug tail "<run>[-pc]-cd-key" mirrors the title's console phrase; the slug is often
# truncated (~80 chars) — then the tail is missing and the URL says nothing (None).
_URL_RUN_RE = re.compile(
    r"-(?P<run>xbox-one-xbox-series-x-s|xbox-one-series-x-s|xbox-series-x-s|xbox-one|"
    r"ps4-ps5|ps5|ps4|nintendo-switch-2|nintendo-switch)(?:-pc)?-(?:cd-key|key|gift|altergift)/?$"
)
_URL_RUN_FAMILIES = {
    "xbox-one-xbox-series-x-s": ("XBOX_ONE", "XBOX_SERIES"),
    "xbox-one-series-x-s": ("XBOX_ONE", "XBOX_SERIES"),
    "xbox-series-x-s": ("XBOX_SERIES",),
    "xbox-one": ("XBOX_ONE",),
    "ps4-ps5": ("PS4", "PS5"),
    "ps5": ("PS5",),
    "ps4": ("PS4",),
    "nintendo-switch-2": ("SWITCH2",),
    "nintendo-switch": ("SWITCH",),
}


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """Families the Kinguin slug declares (``…-eu-xbox-one-xbox-series-x-s-cd-key`` →
    XBOX_ONE, XBOX_SERIES; ``-ps4-ps5-cd-key`` → PS4, PS5; ``-nintendo-switch-2-cd-key`` →
    SWITCH2), the account / access skip (``-account`` → "console: ACCOUNT — not a game
    (R45)", ``-online-account-activation`` / ``-access`` → ACCESS), or None."""

    path = urlsplit(url or "").path.lower()
    if re.search(r"-account/?$", path):
        return skip_not_a_game("ACCOUNT")
    if "online-account-activation" in path or re.search(r"-access/?$", path):
        return skip_not_a_game("ACCESS")
    m = _URL_RUN_RE.search(path)
    return _URL_RUN_FAMILIES[m.group("run")] if m else None


CONFIG = make_config(
    "Kinguin",
    domain="kinguin.net",                  # EXECUTOR_RULES §11 — was the inline registry entry
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    console_noise=("CD Key",),            # NOT the "(valid until …)" note — see OPEN_QUESTION_VALID_UNTIL
    notes=("feed store 58 (&store=58); AKS page merchant 47; title '<Game> [Edition] [<REGION>] "
           "<Platform> CD Key' — region = uppercase code before the platform phrase (2026-09-14)"),
)


def region_kind_of(name: str) -> tuple[str, str] | None:
    """Convenience for reports / tests: :func:`common.region_kind` of the title's code."""

    text = region_text(name)
    return region_kind(text) if text else None
