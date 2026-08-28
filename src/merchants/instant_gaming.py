"""Instant Gaming — offer-page platform/region resolver (R32, migrated 2026-08-28).

IG feed titles are token-less (a STEAM key looks like a bare "<Game>"), so the real
platform must be read from the OFFER PAGE (``data-platform``), and the region from the
page ``<title>``/``og:title`` trailing segment. A whole IG sweep once entered 32/54
region-locked offers as GLOBAL and every offer as Publisher before this. Self-contained:
depends only on ``src.aks_env`` (http_get) and ``src.merchant_config`` (the dataclass) —
never on ``src.matcher`` (see merchants/__init__.py for the dependency direction).
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.aks_env import REQUIRED_USER_AGENT, http_get
from src.merchant_config import MerchantConfig, MerchantOfferSignals

IG_PROBE_DELAY_S = 0.3  # Instant Gaming offer-page probe courtesy (R32), like Difmark

IG_PLATFORM_TEXT_MAP = {
    "STEAM": "STEAM",
    "EPIC": "EPIC", "EPIC GAMES": "EPIC", "EPIC GAMES STORE": "EPIC",
    "GOG": "GOG", "GOG.COM": "GOG",
    "UBISOFT": "UBISOFT", "UBISOFT CONNECT": "UBISOFT", "UPLAY": "UBISOFT",
    "ORIGIN": "EA", "EA": "EA", "EA APP": "EA", "EA PLAY": "EA",
    "BATTLE.NET": "BATTLENET", "BATTLENET": "BATTLENET",
}


class IgPageUnreadable(RuntimeError):
    """Instant Gaming offer page could not be fetched/parsed — fail closed."""


@dataclass(frozen=True)
class IgOfferAttributes:
    """Raw (upper-stripped) signals off an Instant Gaming offer page. Mapping to
    our vocabulary and the fail-closed decision are the caller's job."""

    raw_platform: str          # e.g. "STEAM" (from the offer's data-platform), "" if ambiguous
    raw_region: str | None     # "LATIN AMERICA"/"EUROPE"/…; "" = worldwide; None = unparseable


# R33 (2026-08-13): IG feed titles/URLs carry NO region, but the offer page's
# <title>/og:title trailing segment does ("… - PC (Steam) - Latin America"; no
# suffix = worldwide). Map the clean sellable regions; ANY other suffix (Latin
# America / ROW / North America / Asia …) → None → the offer is region-locked to a
# region we don't sell → SKIP (never enter it as GLOBAL). A whole IG sweep entered
# 32/54 region-locked offers as GLOBAL before this.
IG_REGION_TEXT_MAP = {
    "": "global", "WORLDWIDE": "global", "WW": "global", "GLOBAL": "global",
    "EUROPE": "eu", "EU": "eu",
    "UNITED STATES": "us", "US": "us", "USA": "us",
    "UK": "uk", "UNITED KINGDOM": "uk",
}
# Region policy (Romain 2026-08-13): "on est sur Global, Europe et US. Le reste, on
# skippe et certaines régions qu'on va blacklist, comme les Latam, le Brésil et les
# régions d'Asie" + "les régions russes aussi". This policy is MERCHANT-AGNOSTIC and
# lives in ONE place — ``aks_lists.suggest_target_list`` decides, from a
# ``forbidden region: <label>`` reason, whether the label is blacklisted (→ Blacklist
# list) or merely skipped. A non-sellable IG region therefore just emits that reason
# with its raw label; it does NOT re-implement the blacklist here (Romain: "si on
# connaît déjà ta région, on peut te trier" — same routing whether the region came
# from the feed title or the offer page).

# The IG page <title>/og:title trailing structure anchors on the platform in
# parens: "<Game> … (<Platform>)" = worldwide, "… (<Platform>) - <Region>" =
# region-locked. Each regex CAPTURES the parens content (group 1) so the caller can
# verify it is really a platform — audit #2b (Romain 2026-08-14): a bare
# "…)$" ending is NOT enough (a title like "Game (Deluxe)" must NOT read as
# worldwide/GLOBAL). REGION_RE requires "(…) - <Region>" (so a region that itself
# contains parens still parses — "(…)" must be FOLLOWED by " - ").
_IG_TITLE_REGION_RE = re.compile(r".*\(([^)]*)\)\s*-\s*(.+?)\s*$")
_IG_TITLE_WORLDWIDE_RE = re.compile(r".*\(([^)]*)\)\s*$")
# Platform names that appear inside the IG title parens (PC storefronts + consoles).
# Keyword containment (all >=3 chars, safe as substrings of a short parens) absorbs
# naming variants: "Epic Games Store"⊃EPIC, "Ubisoft Connect"⊃UBISOFT,
# "PlayStation 5"⊃PLAYSTATION, "Nintendo Switch"⊃NINTENDO, "GOG.com"⊃GOG.
_IG_TITLE_PLATFORM_KEYWORDS = (
    "STEAM", "EPIC", "GOG", "UBISOFT", "UPLAY", "ORIGIN", "EA APP", "EA PLAY",
    "BATTLE.NET", "BATTLENET", "BLIZZARD", "ROCKSTAR", "BETHESDA",
    "MICROSOFT", "WINDOWS", "XBOX", "PLAYSTATION", "PSN", "NINTENDO", "SWITCH",
)


def _is_ig_platform_parens(parens: str) -> bool:
    """True when the IG title's "(…)" content names a platform (not an edition/year
    /decorator like "(Deluxe)" / "(2007)"). The worldwide/region anchor is only
    trusted when this holds; otherwise the title structure is unrecognized → skip."""
    p = parens.strip().upper()
    return any(kw in p for kw in _IG_TITLE_PLATFORM_KEYWORDS)


def extract_ig_region(body: str) -> str | None:
    """The offer's region from the IG page <title>/og:title trailing segment:
    - a region label (UPPERCASED) for "… (<Platform>) - <Region>";
    - ``""`` for a POSITIVELY-worldwide title ("… (<Platform>)" with no suffix);
    - ``None`` when no og:title/<title> carries a recognizable "(<Platform>)" anchor
      (layout change / malformed / reordered metadata, OR the parens is not a
      platform — e.g. "(Deluxe)"). Audit #2 (Romain 2026-08-14): a missing/
      unparseable region must FAIL CLOSED (the caller skips), never silently default
      to GLOBAL. The anchor parens is validated as a real platform (audit #2b)."""
    m = (re.search(r'og:title"\s+content="([^"]*)"', body)
         or re.search(r"<title>([^<]*)</title>", body))
    if not m:
        return None
    title = html.unescape(m.group(1))
    rm = _IG_TITLE_REGION_RE.match(title)
    if rm and _is_ig_platform_parens(rm.group(1)):
        return rm.group(2).strip().upper()
    wm = _IG_TITLE_WORLDWIDE_RE.match(title)
    if wm and _is_ig_platform_parens(wm.group(1)):
        return ""
    return None


def extract_ig_platform(body: str) -> str:
    """The offer's platform from the IG page's `data-platform` attributes. Returns
    the value ONLY when every `data-platform` on the page AGREES — a page also
    carries platform-filter sidebars / "you may also like" carousels, so a first
    match could read a foreign platform. Not unanimous (or none) → "" → the caller
    fails closed (mirrors the Difmark product-id tab lesson, 2026-08-06)."""
    vals = {m.strip().upper() for m in re.findall(r'data-platform="([^"]+)"', body) if m.strip()}
    return next(iter(vals)) if len(vals) == 1 else ""


def resolve_ig_offer(url: str, http_get_fn: Callable[..., Any] = http_get) -> IgOfferAttributes:
    """Fetch an Instant Gaming offer page (a normal browser UA — NEVER the AKS
    staff UA on a non-AKS host) and read its platform + region. Raises
    :class:`IgPageUnreadable` on any fetch/parse failure so the caller skips."""
    if http_get_fn is http_get:
        time.sleep(IG_PROBE_DELAY_S)  # politeness for bulk IG sweeps, like Difmark
    try:
        page = http_get_fn(url, timeout=15, user_agent=REQUIRED_USER_AGENT)
    except Exception as exc:  # noqa: BLE001 — any transport failure → fail closed
        raise IgPageUnreadable(f"fetch failed: {exc}") from exc
    if not (page.ok and page.status == 200 and page.body):
        raise IgPageUnreadable(f"bad response: {page.status or page.error}")
    return IgOfferAttributes(
        raw_platform=extract_ig_platform(page.body),
        raw_region=extract_ig_region(page.body),
    )


def ig_offer_signals(url: str) -> MerchantOfferSignals:
    """Instant Gaming config hook: read the offer page ONCE, map platform + region
    to our vocabulary. The IG page ALWAYS yields a region signal, so
    ``region_resolved=True`` and either:
    - a sellable base (global/eu/us/uk) → ENTER with it; or
    - ``region_base`` None + the raw region label → the caller emits a
      ``forbidden region: <label>`` skip, whose blacklist-vs-park-vs-skip routing is
      decided centrally (LATAM / Brazil / Asia / Russia → Blacklist).
    platform None = unrecognized platform → the caller skips. Raises
    IgPageUnreadable on an unreadable page OR when the region metadata is missing/
    unparseable (audit #2: never default a malformed page to GLOBAL)."""
    attrs = resolve_ig_offer(url)
    if attrs.raw_region is None:
        raise IgPageUnreadable(
            "IG offer page region metadata missing/unparseable (layout change?) — "
            "not defaulting to GLOBAL (audit #2)")
    base = IG_REGION_TEXT_MAP.get(attrs.raw_region)
    return MerchantOfferSignals(
        platform=IG_PLATFORM_TEXT_MAP.get(attrs.raw_platform),
        region_resolved=True,
        region_base=base,
        region_label=(attrs.raw_region or "worldwide") if base is None else "",
    )


CONFIG = MerchantConfig(
    "Instant Gaming",
    offer_page_resolver=ig_offer_signals,
    notes="token-less titles — platform (data-platform) + region (<title> suffix) on the offer page",
)
