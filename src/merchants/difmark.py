"""Difmark — page-verified platform/region resolver (migrated 2026-08-28).

Difmark feed titles are bare "<Name> Standard Edition" (no platform token → 77% would
R27-skip), so the platform/region come from the offer's OWN "top offer" API, reached in
one round-trip pair off the product page. Self-contained: uses only http_get (aks_env)
and stdlib — never the match_offer pipeline (see merchants/__init__.py). The generic
AKS-account-page helper ``account_identity`` stays in ``src.matcher`` (not Difmark-only).
"""

from __future__ import annotations

import json
import re  # noqa: F401 — kept for parity / future Difmark parsing; harmless if unused
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.aks_env import http_get
from src.merchant_config import MerchantConfig

DIFMARK_PROBE_DELAY_S = 0.3

# Difmark region-lock vocabulary — confirmed live 2026-07-17 against the
# merchant's own per-offer "top-offer" API (offer_attributes[code=region]).
# Deliberately NOT the site-wide "regions" dropdown embedded on every Difmark
# page ({"value":1,"text":"Europe"}, ...): that is a residence/currency
# continent picker, a different vocabulary — a live check on the Rogue Loops
# example (product 166307, region_product_id=1) showed the dropdown mapping
# "1 -> Europe" while the actual per-offer attribute was "region": "Global".
# Decoding region_product_id through the dropdown would have silently been
# wrong. Any region text outside this map fails closed (G02, doubt → skip)
# instead of being guessed.
DIFMARK_REGION_TEXT_MAP = {
    "GLOBAL": ("GLOBAL", "global"),
    "EUROPE": ("EU", "eu"),
    "UNITED STATES": ("US", "us"),
    "UNITED KINGDOM": ("UK", "uk"),
}
# Difmark platform vocabulary — same source, same policy: only "Steam" is
# confirmed live so far (Romain 2026-07-17: "étends au platform aussi",
# after batch 1 showed 77% of the feed skipped on R27 for lacking a title
# platform token — Difmark titles are typically bare "<Name> Standard
# Edition"). Anything else fails closed rather than being guessed.
DIFMARK_PLATFORM_TEXT_MAP = {"STEAM": "STEAM"}
# AKS's own region dropdown carries a PARALLEL "Account" bucket for many
# platforms. base region key -> AKS region id, Steam platform only (the only
# platform confirmed for Difmark so far). No UK entry exists in the dropdown.
# Ids captured from a live dropdown snapshot 2026-07-08 — re-verify against a
# FRESH catalog fetch before Difmark's first real submit; ids drift over time.
DIFMARK_STEAM_ACCOUNT_REGION_IDS = {
    "global": "412",
    "eu": "480",
    "us": "578",
}
# detect_region/DIFMARK_REGION_TEXT_MAP produce a display label (GLOBAL/EU/
# US/UK); the Account-region lookup above is keyed by the same base region
# key used everywhere else — this reverses label back to that key.
_DIFMARK_REGION_LABEL_TO_BASE = {"GLOBAL": "global", "EU": "eu", "US": "us", "UK": "uk"}

# platform -> the AKS account-PAGE kind (Romain 2026-07-18): an account offer
# must resolve to AKS's dedicated account page (`buy-<slug>-<kind>-compare-
# prices/`), NOT the game key page. Only STEAM is confirmed for Difmark today.
DIFMARK_ACCOUNT_PAGE_KINDS = {"STEAM": "steam-account"}


class DifmarkPageUnreadable(RuntimeError):
    """The Difmark product page or its own 'top offer' API could not be read
    (network error or unexpected shape). Platform/region are unverifiable —
    fail closed, no fallback to the URL/title heuristic that was already
    ambiguous."""


def difmark_product_id(url: str) -> str | None:
    """The trailing numeric product id of a Difmark offer URL
    (``…/buy-<slug>-<id>?<params>``), or None if absent. A Difmark page carries
    one tab PER marketplace (Steam Account, Epic Games Account, …), each a
    DISTINCT product id, so the feed URL's id is what selects the right tab."""

    path = url.split("?", 1)[0].rstrip("/")
    match = re.search(r"(\d+)$", path)
    return match.group(1) if match else None


def extract_difmark_top_offer_url(page_html: str, product_id: str | None = None) -> str | None:
    """Pull the 'top offer' API link Difmark embeds in the product page's SSR
    JSON blob, unescaped.

    Uses the CLEAN ``url_top_offer`` (not ``url_top_offer_with_get_params``):
    since 2026-08-06 Difmark's top-offer API returns 404 when the feed URL's AKS
    tracking params are propagated into the link. The clean link returns the SAME
    attributes.

    A page has one clean link PER marketplace tab, each a distinct product id.
    When ``product_id`` is given (the feed offer's own id), pick the link for THAT
    tab — taking the first would read the wrong marketplace (2026-08-06 mislabel).
    If a product id is given but no tab matches it, fail closed (None). With no
    product id, fall back to the first clean link, then the params variant."""

    clean = [json.loads('"' + m + '"')
             for m in re.findall(r'"url_top_offer":"((?:[^"\\]|\\.)*)"', page_html)]
    if product_id is not None:
        for u in clean:
            if f"/products/{product_id}/" in u:
                return u
        return None
    if clean:
        return clean[0]
    match = re.search(r'"url_top_offer_with_get_params":"((?:[^"\\]|\\.)*)"', page_html)
    if match:
        try:
            return json.loads('"' + match.group(1) + '"')
        except ValueError:
            pass
    return None


def parse_difmark_offer_attributes(body: str) -> dict[str, Any] | None:
    """{code: value} from a Difmark top-offer API JSON response, or None if
    the response isn't the expected shape."""

    try:
        data = json.loads(body)
    except ValueError:
        return None
    offer = data.get("offer") if isinstance(data, dict) else None
    attrs = offer.get("offer_attributes") if isinstance(offer, dict) else None
    if not isinstance(attrs, list):
        return None
    return {a["code"]: a["value"] for a in attrs if isinstance(a, dict) and "code" in a}


def parse_difmark_offer_name(body: str) -> str | None:
    """The offer's own display name from a Difmark top-offer API response —
    e.g. "Numina (Steam Account) / Region GLOBAL / Edition Standard". This is
    the only reliable account-vs-key signal for Difmark (Romain 2026-07-17):
    the AKS-feed title never carries it, and the URL's "steam-account" segment
    is boilerplate on every listing. None if the response isn't the expected shape."""

    try:
        data = json.loads(body)
    except ValueError:
        return None
    offer = data.get("offer") if isinstance(data, dict) else None
    name = offer.get("offer_name") if isinstance(offer, dict) else None
    return name if isinstance(name, str) else None


@dataclass(frozen=True)
class DifmarkOfferAttributes:
    """Raw (upper-stripped) text off a Difmark offer's own top-offer API —
    "" when the API didn't carry that field. Mapping to our internal
    platform/region vocabulary (and the fail-closed decision on an
    unrecognized value) is the caller's job."""

    raw_platform: str
    raw_region: str
    offer_name: str


def resolve_difmark_offer(
    url: str, http_get_fn: Callable[..., Any] = http_get
) -> DifmarkOfferAttributes:
    """Fetch a Difmark offer's page-verified platform/region in ONE round-trip
    pair (Romain, 2026-07-17: plain GETs, no CDP/browser): the product URL itself,
    then the 'top offer' API link that page embeds. Raises DifmarkPageUnreadable if
    either fetch fails or the shape is unrecognized — never silently guesses."""

    if http_get_fn is http_get:
        time.sleep(DIFMARK_PROBE_DELAY_S)  # politeness budget for bulk runs
    page = http_get_fn(url, timeout=15)
    if not (page.ok and page.status == 200 and page.body):
        raise DifmarkPageUnreadable(f"product page unreadable: {page.status or page.error}")
    # The feed URL's product id selects the offer's OWN marketplace tab (Steam vs
    # Epic account, etc.) — never the page's first tab (2026-08-06 mislabel bug).
    top_offer_url = extract_difmark_top_offer_url(page.body, difmark_product_id(url))
    if not top_offer_url:
        raise DifmarkPageUnreadable("no top-offer API link found on product page")
    if http_get_fn is http_get:
        time.sleep(DIFMARK_PROBE_DELAY_S)
    probe = http_get_fn(top_offer_url, timeout=15)
    if not (probe.ok and probe.status == 200 and probe.body):
        raise DifmarkPageUnreadable(f"top-offer API unreadable: {probe.status or probe.error}")
    attrs = parse_difmark_offer_attributes(probe.body)
    if not attrs:
        raise DifmarkPageUnreadable("top-offer API response has an unexpected shape")
    return DifmarkOfferAttributes(
        raw_platform=str(attrs.get("marketplace", "")).strip().upper(),
        raw_region=str(attrs.get("region", "")).strip().upper(),
        offer_name=parse_difmark_offer_name(probe.body) or "",
    )


CONFIG = MerchantConfig(
    "Difmark",
    url_ignore_substrings=("buy-console-account-", "buy-console-account"),
    notes="offer-page resolver (resolve_difmark_offer) still handled in match_offer",
)
