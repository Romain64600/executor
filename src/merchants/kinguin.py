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
* ``<Delivery>`` — ``CD Key`` (the norm), ``Key``, ``Steam Gift`` (5), ``Altergift`` (1 —
  a Steam gift, entered as the Steam GIFT bucket: Romain 2026-09-14, see below),
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
    Sons Of The Forest PC Steam Altergift  (hypothetical, no code) → STEAM, GIFT (25), "Sons Of The Forest"
    Rocket League UAE PC Steam Gift                               → forbidden region: UNITED ARAB EMIRATES
    Shardstorm PC Steam CD Key                                    → no code, name "Shardstorm"
    Project MIKHAIL: A Muv-Luv War Story PC Steam CD Key (valid until May 2027)
                                                                  → entered, note stripped from the guard (2026-09-14)
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
* ``resolve_name`` — the code and the platform phrase peeled so the slug is the game's;
  the ``(valid until <Month> <Year>)`` note too.
* ``guard_name`` — **Romain's ruling (2026-09-14): « Kinguin valid until juin 2027 on
  rentre »** — the note is an ACTIVATION DEADLINE, not a product word. It is stripped from
  the title the identity guards (R01 missing words / R16 extras / R01b qualifier) and
  ``detect_edition`` read (with the delivery word "Altergift", below — nothing else);
  before, the guards read the raw title and the 79 rows/batch carrying the note were
  skipped "different/expanded product — extra words: ['VALID', 'UNTIL', 'MARCH', '2027']"
  (61 of them — rows de-duplicated by offer id — had resolved their page with NO other
  extra word: candidates now — 2026-09-12 batch). The same phrase is in ``console_noise``
  so a console row with the note resolves too. Only the TRAILING "(valid until <Month>[,]
  <Year>)" form exists in the corpus (89 / 89 rows of the batch, 158 / 158 with the
  duplicates; ``VALID_UNTIL_RE`` is anchored to the title end — review fix 2026-09-14); any
  other spelling or position stays in the guard → the usual extra-words skip (fail-closed,
  never a wider strip).
* ``gift_delivery`` / ``altergift_verdict`` — **Romain (2026-09-14): « Steam Altergift =
  Steam Gift on rentre sous gift tous les altergifts »** applies to Kinguin's own
  "Altergift" delivery too (review fix 2026-09-14, finding [3]: the ruling was K4G-only at
  first): a "<Game> [<REGION>] PC Steam Altergift" row is the Steam GIFT bucket layered on
  the base region (GIFT 25 / GIFT EU 259 / GIFT US 2577 / GIFT UK 2572 — the US / UK buckets
  were mapped on 2026-09-16, `[R50]`: this file used to state they did not exist and that
  such a row failed closed, which was false, the AKS dropdown has carried them all along;
  a forbidden code keeps its precheck skip — the batch's one row, "Sons Of The Forest DE …",
  is GERMANY). The same two gates as
  K4G: the store phrase must be Steam (a non-Steam Altergift is a grammar never seen →
  fail-closed precheck skip, never another platform's gift bucket), and the slug must not
  contradict — Kinguin's slug mirrors the title (``…-pc-steam-altergift``) but is often
  TRUNCATED (~80 chars), so a slug that says nothing is accepted, while a ``-cd-key`` /
  ``-key`` / account tail against an Altergift title is the "Kinguin delivery conflict"
  skip. "Altergift" is never a product word: ``guard_name`` drops it, ``resolve_name`` too
  (the grammar already peels the delivery). "Steam Gift" rows are untouched (the generic
  " GIFT " read, ``gift_delivery`` → None).
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

# DECIDED (Romain 2026-09-14): « Kinguin valid until juin 2027 on rentre ». The
# "(valid until <Month> <Year>)" activation-deadline note (79 rows of the 2026-09-12 batch)
# is entered: ``guard_name`` strips the note — and nothing else — from the title the
# identity guards read, ``resolve_name`` peels it for the slug, ``console_noise`` carries
# it for console rows. Formerly the open question OPEN_QUESTION_VALID_UNTIL (skipped as
# "extra words: ['VALID', 'UNTIL', …]").

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
# The note alone, TRAILING (anchored ``\s*$`` — review fix 2026-09-14, finding [2]: the
# pre-ruling pattern was anchored too, and the note is trailing in every corpus row, 158 /
# 158; a note in the middle of a title is a spelling never seen and stays in the guard →
# the usual extra-words skip, fail-closed): used by ``guard_name`` / ``resolve_name`` here
# and declared as Kinguin's ``console_noise`` for the shared console classifier (a compiled
# pattern — a literal cannot spell the month / year; the classifier applies it to the raw
# title first, where the note is still trailing).
VALID_UNTIL_RE = re.compile(_VALID_UNTIL + r"\s*$", re.IGNORECASE)
_ACCOUNT_DELIVERIES = frozenset({"ACCOUNT", "ACCESS"})
_ACCOUNT_URL_RE = re.compile(r"(?:-account|-access)/?$|online-account-activation")
# DECIDED (Romain 2026-09-14): « Steam Altergift = Steam Gift on rentre sous gift tous les
# altergifts » — Kinguin's own "Altergift" delivery too (review fix 2026-09-14). The word,
# whole and case-insensitive; the slug tails that AGREE ("-altergift", "-gift": the same
# GIFT bucket class) and the tails that CONTRADICT it ("-cd-key", "-key", "-activation-
# link", the account / access markers); a truncated slug says nothing (accepted).
_ALTERGIFT_RE = re.compile(r"\bAltergift\b", re.IGNORECASE)
_URL_GIFT_TAIL_RE = re.compile(r"-(?:altergift|gift)/?$")
_URL_KEY_TAIL_RE = re.compile(r"-(?:cd-key|key|activation-link)/?$")
_STEAM_RE = re.compile(r"\bSteam\b", re.IGNORECASE)
# A store / console phrase that is NOT Steam (the bare "PC" / "Mac" / "Windows" items are not
# stores; a bare "Origin" is a name word for the matcher too, R14).
_STORE_ITEM = (
    r"GOG(?:\.com)?|Epic\s+Games(?:\s+Store)?|EA\s+App|EA\s+Origin|Ubisoft\s+Connect|Uplay|"
    r"Rockstar(?:\s+Games)?(?:\s+Launcher)?|Battle\.net|Microsoft\s+Store|Official\s+Website"
)
_OTHER_PLATFORM_RE = re.compile(
    rf"\b(?:{_STORE_ITEM}|Xbox|PS4|PS5|PlayStation|Nintendo)\b", re.IGNORECASE
)
_NOT_A_STORE_RE = re.compile(r"\b(?:PC|Mac|Windows(?:\s+1[01])?)\b", re.IGNORECASE)


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


def is_altergift(name: str) -> bool:
    """The title carries the whole word ALTERGIFT (case-insensitive) — Kinguin's Steam-gift
    delivery ("Sons Of The Forest DE PC Steam Altergift"); "… PC Steam Gift" does not."""

    return _ALTERGIFT_RE.search(name or "") is not None


def drop_altergift(name: str) -> str:
    """``name`` without the word "Altergift" — and nothing else (whitespace collapsed);
    unchanged when the word is absent."""

    if not is_altergift(name):
        return name or ""
    return re.sub(r"\s+", " ", _ALTERGIFT_RE.sub(" ", name)).strip()


def is_steam_altergift(name: str) -> bool:
    """The title is an Altergift AND its platform phrase is Steam — Romain's « Steam
    Altergift = Steam Gift » (2026-09-14). In the grammar: the run before "Altergift", its
    PC / Mac / Windows items removed, is exactly "Steam" ("PC Steam Altergift", "Steam
    Altergift"; "PC Epic Games Altergift" is not). Outside the grammar: the whole word Steam
    is present and no other store / console phrase is."""

    if not is_altergift(name):
        return False
    m = parse_title(name)
    if m is not None:
        run = re.sub(r"\s+", " ", _NOT_A_STORE_RE.sub(" ", m.group("run")).replace("/", " ")).strip()
        return m.group("delivery").upper() == "ALTERGIFT" and run.upper() == "STEAM"
    return _STEAM_RE.search(name) is not None and _OTHER_PLATFORM_RE.search(name) is None


def url_delivery(url: str) -> str | None:
    """What the Kinguin slug tail says about the delivery: ``"gift"`` for ``-altergift`` /
    ``-gift``, ``"key"`` for ``-cd-key`` / ``-key`` / ``-activation-link`` or an account /
    access marker, None when the (often truncated) slug says nothing. Path only — the
    ``?params`` never speak for the product (§4.6)."""

    path = urlsplit(url or "").path.lower()
    if _URL_GIFT_TAIL_RE.search(path):
        return "gift"
    if _URL_KEY_TAIL_RE.search(path) or _ACCOUNT_URL_RE.search(path):
        return "key"
    return None


def altergift_verdict(name: str, url: str) -> str | None:
    """The one Altergift decision of the Kinguin grammar, shared by ``precheck`` and
    ``gift_delivery`` (Romain 2026-09-14: « Steam Altergift = Steam Gift on rentre sous gift
    tous les altergifts » + the fail-closed rule — review fix of the same day):

    * ``"gift"`` — a Steam Altergift whose slug agrees or says nothing (truncated):
      entered as the Steam GIFT bucket;
    * a skip reason (str) — the store phrase is not Steam (never seen — never another
      platform's gift bucket, never a plain key), or the slug tail contradicts the title
      ("-cd-key" / "-key" / account marker against "Altergift"; 0 rows);
    * None — not an Altergift row: the generic read decides ("… PC Steam Gift" keeps its
      " GIFT " reading).
    """

    if not is_altergift(name):
        return None
    if not is_steam_altergift(name):
        return ("Kinguin Altergift outside the Steam collocation (title's platform phrase is "
                "not Steam) — not entered (Romain 2026-09-14: « Steam Altergift = Steam Gift »)")
    if url_delivery(url) == "key":
        return ("Kinguin delivery conflict: title Altergift but URL says key / account (no "
                "altergift tail) — not entered (2026-09-14)")
    return "gift"


# ── hooks (PC pipeline) ──────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """Categorical skips of the Kinguin grammar, before the generic scans:
    1. an account / access listing → ``skip category: ACCOUNT (…)`` (never a key);
    2. a region code that is not sellable → ``forbidden region: <LABEL>`` (the matcher
       vocabulary: CA → CANADA, AU → AUSTRALIA, RoW → ROW, SEA → SOUTH EAST ASIA …);
    3. the Altergift gates of :func:`altergift_verdict` — a non-Steam Altergift or a
       title / URL delivery conflict → its fail-closed reason (review fix 2026-09-14).
    A sellable code (EU / US / UK / GB / European Union) or no code, and a Steam Altergift
    whose slug agrees → None."""

    if is_account_listing(name, url):
        return "skip category: ACCOUNT (Kinguin account / access listing — not a key)"
    text = region_text(name)
    reason = forbidden_reason(text) if text else None
    if reason:
        return reason
    verdict = altergift_verdict(name, url)
    return verdict if verdict not in (None, "gift") else None


def gift_delivery(name: str, url: str) -> bool | None:
    """Kinguin's own gift-delivery verdict for ``detect_region`` (Romain 2026-09-14: « on
    rentre sous gift tous les altergifts »): True when :func:`altergift_verdict` says
    ``"gift"`` → the Steam GIFT bucket layered on the base region (25 / 259); None
    otherwise → the generic read decides ("… PC Steam Gift" keeps its " GIFT " reading; a
    refused Altergift row was already stopped by ``precheck`` — the merchant does not vouch
    for it)."""

    return True if altergift_verdict(name, url) == "gift" else None


def title_region(name: str) -> str | None:
    """"Game US PC Steam CD Key" → "us"; "Game EU …" → "eu"; "Game European Union …" →
    "eu"; no code / forbidden code → None (precheck already skipped the latter)."""

    text = region_text(name)
    return sellable_base(text) if text else None


def strip_valid_until(name: str) -> str:
    """``name`` without its TRAILING "(valid until <Month> <Year>)" note — and nothing else
    (the whitespace it leaves is collapsed). Unchanged when there is no note, or when the
    note sits elsewhere in the title (a spelling never seen: it stays, fail-closed —
    review fix 2026-09-14)."""

    if not name or VALID_UNTIL_RE.search(name) is None:
        return name or ""
    return re.sub(r"\s+", " ", VALID_UNTIL_RE.sub(" ", name)).strip()


def guard_name(name: str) -> str:
    """The title the identity guards (R01 / R16 / R01b) and ``detect_edition`` read
    (Romain 2026-09-14: « Kinguin valid until juin 2027 on rentre », « … on rentre sous gift
    tous les altergifts »): the raw title with the trailing "(valid until …)" note stripped
    and the delivery word "Altergift" dropped — nothing else is touched ("Vampyr PC Steam CD
    Key (valid until March 2027)" → "Vampyr PC Steam CD Key"; "Sons Of The Forest PC Steam
    Altergift" → "Sons Of The Forest PC Steam"; every other word, platform / delivery /
    region / edition included, stays for the guards to weigh as before)."""

    return drop_altergift(strip_valid_until(name)) or name


def resolve_name(name: str) -> str:
    """The text handed to AKS resolution: the region code, the platform phrase, the
    delivery word, the "by Digital Distribution Hub" note and the "(valid until …)" note
    peeled ("Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key" → "Hobo: Tough Life").
    A title outside the grammar is returned unchanged but for a trailing validity note and
    the word "Altergift" (2026-09-14)."""

    m = parse_title(name)
    if m is None:
        return drop_altergift(strip_valid_until(name)) or name
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
    guard_name=guard_name,                # the "(valid until …)" note / "Altergift" are not product words (Romain 2026-09-14)
    gift_delivery=gift_delivery,          # "… PC Steam Altergift" = Steam GIFT bucket (Romain 2026-09-14, « tous les altergifts »)
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    console_noise=("CD Key", VALID_UNTIL_RE),   # the note is noise for console rows too (Romain 2026-09-14)
    notes=("feed store 58 (&store=58); AKS page merchant 47; title '<Game> [Edition] [<REGION>] "
           "<Platform> CD Key [(valid until <Month> <Year>)]' — region = uppercase code before "
           "the platform phrase; the validity note is entered, 'PC Steam Altergift' = Steam gift "
           "(2026-09-14)"),
)


def region_kind_of(name: str) -> tuple[str, str] | None:
    """Convenience for reports / tests: :func:`common.region_kind` of the title's code."""

    text = region_text(name)
    return region_kind(text) if text else None
