"""Eneba — platform from the URL's leading path segment (R29, migrated 2026-08-28);
console grammar through the ``MerchantConfig`` console hooks (R32 / R45, 2026-09-14).

Eneba titles often omit the PC platform, but its URL convention
(``eneba.com/<platform>-<slug>``) declares it. Pure data + config for the PC side — no
resolver code, no matcher import.

Console grammar (2026-09-14, Romain: « un fichier de config par marchand »). Eneba's URL
is the leading STORE segment plus the slugified title:
``eneba.com/<store>-<title slug>-<platform run>-<store>-key-<region>``, e.g.
``xbox-nickelodeon-extreme-tennis-next-xbox-series-x-s-xbox-live-key-europe`` for the
title "Nickelodeon Extreme Tennis: Next! (Xbox Series X|S) XBOX LIVE Key EUROPE". Hence:

* the leading ``xbox-`` / ``psn-`` / ``nintendo-`` segment is the STORE, NEVER a
  generation — ``xbox-one-last-breath-xbox-live-key-europe`` is the game "One Last
  Breath" sold through Xbox Live, not an Xbox One key (13/16 "Xbox One" rows of the
  2026-09-12 batch were this artefact);
* the platform run sits right BEFORE the store-key marker (``-xbox-live-key-``,
  ``-xbox-key-``, ``-psn-key-``, ``-eshop-key-``, ``-nintendo-eshop-key-``) — the slot
  the ``console_url_families`` hook reads with the SHARED slug vocabulary
  (``src.console_keys.slug_families``: xbox-one / xbox-series-x-s / ps4-ps5 /
  nintendo-switch-2 …); a run elsewhere in the slug is part of the game name
  ("nintendo-nintendo-switch-sports-eshop-key-europe" → nothing declared); no marker →
  the URL says nothing (fail-closed);
* ``-pc-`` / ``-windows-`` right before the marker with no console run is a PC key sold
  through Xbox Live / the Microsoft Store (174 rows of the 2026-09-12 batch) — and so is
  the ``xbox-`` store's own ``-windows-key-`` / ``-pc-key-`` form ("Call of Duty®: Black
  Ops II (2012) (Windows) Key UNITED STATES", ``xbox-call-of-duty-…-windows-key-united-
  states``): the hook answers ``(XBOX_WINDOWS_KEY,)`` since 2026-09-26 (Romain, « 1. » — Play
  Anywhere if the AKS PC page says so, else Microsoft Store if it lists Microsoft Windows,
  else refusal; before: "console: PC-only Xbox Live key (R45)"); ``-windows-`` / ``-pc-``
  next to the run → PC declared (``console_pc_declared``, a Play Anywhere candidate);
* the region is the UPPERCASE text after the key word — "… XBOX LIVE Key EUROPE",
  "… eShop Key HONG KONG" (``console_region_slot``); the shared classifier maps it.

The shared classifier consults the URL hook ONLY when the title phrase declares no
generation. The "<Game> XBOX LIVE Key <REGION>" rows without any platform phrase (704 of the
2026-09-12 batch) were "no declared generation" until P4 (Romain 2026-09-25, « Xbox sur les
deux »): the shared classifier now reads the title's generation-less "XBOX LIVE" as Xbox One
+ Series (``generation_inferred``), and "(Windows) XBOX LIVE Key" as a PC-only key.
``src/console_keys.py`` names no merchant.
"""

from __future__ import annotations

import re

from src.console_keys import XBOX_WINDOWS_KEY, path_tokens, slug_families
from src.merchant_config import MerchantConfig

# Only prefixes we have a platform constant + region mapping for; console/currency/
# software prefixes (nintendo, xbox, psn, top, other, riot, …) are left unmapped —
# already caught by the console/currency/software-app categorical skips.
ENEBA_URL_PLATFORM_PREFIXES = {
    "steam": "STEAM",
    "gog": "GOG",
    "epic": "EPIC",
    "uplay": "UBISOFT",
    "origin": "EA",
    "blizzard": "BATTLENET",
    "windows": "MICROSOFT",  # seaux Windows mappés depuis [R50] — la ligne ENTRE
}

# ── console hooks (R45, 2026-09-14) ──────────────────────────────────────────────────
# The leading STORE segments of a console row's URL — never a generation.
CONSOLE_STORE_SEGMENTS = frozenset({"xbox", "psn", "nintendo"})
# The slugified "<STORE> Key" marker that closes the platform slot; the LAST one counts
# ("xbox-key-of-heaven-xbox-one-xbox-live-key-europe" opens with a game called "Key of
# Heaven").
CONSOLE_KEY_MARKER_RE = re.compile(r"(?:^|-)(?:xbox-live|xbox|psn|nintendo-eshop|eshop)-key(?=-|$)")
# The ``xbox-`` store's Windows key (2026-09-26): "<Title> (Windows) Key <REGION>" →
# ``xbox-<title slug>-windows-key-<region>`` — no store-key marker, the delivery closes it.
CONSOLE_WINDOWS_KEY_RE = re.compile(r"-(?:windows|pc)-key(?=-|$)")
# "<Title> (<Platform>) <STORE> Key <REGION>" — the region is the UPPERCASE tail after
# the key word ("EUROPE", "UNITED STATES", "HONG KONG"; "EU" too).
CONSOLE_REGION_AFTER_KEY_RE = re.compile(r"\bKey\s+([A-Z]{2,}(?:\s+[A-Z]{2,})*)\s*$")


def _slot_tokens(url: str) -> list[str] | None:
    """The slug tokens BEFORE the last store-key marker, the leading store segment
    dropped; None when the URL carries no marker (nothing to read, fail-closed)."""

    slug = (url or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()
    matches = list(CONSOLE_KEY_MARKER_RE.finditer(slug))
    if not matches:
        return None
    tokens = path_tokens(slug[:matches[-1].start()])
    if tokens and tokens[0] in CONSOLE_STORE_SEGMENTS:
        tokens = tokens[1:]
    return tokens


def _console_slot(url: str) -> tuple[tuple[str, ...] | str | None, bool]:
    """``(declaration, pc)`` from the platform slot before the store-key marker."""

    tokens = _slot_tokens(url)
    if tokens is None:
        slug = (url or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()
        if slug.startswith("xbox-") and CONSOLE_WINDOWS_KEY_RE.search(slug):
            return (XBOX_WINDOWS_KEY,), False    # the Xbox store's "(Windows) Key" (2026-09-26)
        return None, False
    read = slug_families(tokens)
    if read.skip_reason:
        return read.skip_reason, False          # "xbox-360" anywhere before the marker
    if read.families and read.span is not None:
        tail = tokens[read.span[1]:]
        if not tail or tail in (["pc"], ["windows"]):
            return read.families, read.pc_declared
        return None, False                       # a run inside the game name, not the slot
    if tokens and tokens[-1] in ("pc", "windows"):
        return (XBOX_WINDOWS_KEY,), False        # a PC key sold through Xbox Live / MS Store
    return None, False


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """The families of the platform slot before the store-key marker,
    ``(XBOX_WINDOWS_KEY,)`` for a PC key sold through Xbox Live (2026-09-26), "console: Xbox
    360 (R45)", or None (no slot, no marker)."""

    return _console_slot(url)[0]


def console_pc_declared(name: str, url: str) -> bool:
    """"-windows-" / "-pc-" immediately next to the platform slot
    ("…-windows-xbox-series-x-s-xbox-live-key-…") — PC declared next to the console."""

    return _console_slot(url)[1]


def console_region_slot(name: str) -> str | None:
    """"… XBOX LIVE Key UNITED STATES" → "UNITED STATES"; "… eShop Key HONG KONG" →
    "HONG KONG"; None when no uppercase region follows the key word."""

    m = CONSOLE_REGION_AFTER_KEY_RE.search(name or "")
    return m.group(1) if m else None


CONFIG = MerchantConfig(
    "Eneba",
    url_platform_prefixes=ENEBA_URL_PLATFORM_PREFIXES,  # URL leading segment = platform (R29)
    # console grammar (R45, 2026-09-14): slot before the store-key marker, region after Key
    console_url_families=console_url_families,
    console_pc_declared=console_pc_declared,
    console_region_slot=console_region_slot,
)
