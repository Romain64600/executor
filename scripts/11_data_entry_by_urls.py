#!/usr/bin/env python3
"""Stage 11 — data entry driven by a LIST of AKS product-page URLs.

The operator pastes AKS page URLs (e.g. .../buy-<slug>-cd-key-compare-prices/).
For each game we PIN that AKS page (no slug-guessing), then find the pending
MERCHANT offers to enter by driving the AKS feed tool's SEARCH field
(``search[search]`` + ``search[field]=name|url``) across the vetted merchant
allowlist, and run each found row through the SAME match logic (games-only,
region blacklist, region/edition) against the pinned page.

STAGE 1 is DRY-RUN ONLY (read-only): resolve + search + plan + report. It never
writes. The submit half is a separate, explicitly-gated step (stage 2).

Correctness leans on the existing pipeline: ``match_offer`` with a pinned
resolver still runs R01 (name check), so a search that over-matches an unrelated
offer is rejected — the search only proposes rows; match_offer decides.

CONSOLE PAGES (Romain 2026-09-15: consoles are taken into account by default
everywhere, « travailler sur une page de jeu » included). The operator may paste a
console page (``buy-<slug>-<kind>-compare-prices/``, kind ∈ ps4 / ps5 / xbox-one /
xbox-series / nintendo-switch / nintendo-switch-2 — its own product id) as well as the
PC page. ``--consoles`` (default) runs the matcher's console branch [R45]; the search
term for a console page is the page IDENTITY ("Hades PS5" → "Hades" — the merchant
title carries the platform phrase, never the AKS suffix); the pinned page answers the
console branch's page protocol (:class:`PinnedPage` — the PC anchor / sibling pages are
read from the pinned page's tab bar, read-only, cached per game); and a candidate
QUALIFIES for the requested page iff ANY of its targets is that page — so a cross-gen
key ("Xbox One / Series X|S") requested from the Xbox Series page is still written on
ALL its declared pages (never split), and a Play Anywhere key requested from the PC
page qualifies through its XBOX_PC target. ``--no-consoles`` = the historical PC-only
run: a console page URL is REFUSED with an explicit message (nothing fetched, nothing
done for that URL) and console rows keep the historical "console" skip.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _write_json_atomic(path, payload) -> None:
    """Écriture ATOMIQUE d'un contrat de run (audit du 2026-09-18).

    `recap.json` est relu EN DIRECT par la console pendant que le run tourne. Un
    `write_text` nu tronque puis réécrit en place : une lecture tombant dans la fenêtre voit
    un JSON coupé. Le dépôt a déjà cette convention (`validation_io`, `run_marker`) — tmp
    dans le MÊME dossier, donc même système de fichiers, puis `os.replace`."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)



from src.admin import auto_merchants  # noqa: E402
from src.aks_env import OFFICIAL_CDP_ENDPOINT, _allkeyshop_host  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.console_keys import CONSOLE_PAGE_KINDS, console_page_identity  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.extractor import AKS_ADMIN_URL, DEFAULT_FEED_PAGE, NotLoggedInError  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.matcher import (  # noqa: E402
    AKS_PROBE_DELAY_S,
    AKS_PROBE_UA,
    AksNameUnreadable,
    AksProbeUnreliable,
    AksResolution,
    AksThrottled,
    _ThrottleGuard,
    Candidate,
    SkippedOffer,
    _resolution_from_body,
    cleaned_title,
    http_get,
    resolve_aks_url,
    swap_numerals,
)
from src.submit_session import SubmitSession  # noqa: E402

# Same render-race backoff the extractor/mover poll through (feed_ui renders late).
FEED_UI_RENDER_WAITS = (1.0, 2.0, 4.0)
# The AKS all-merchants SEARCH renders ALL matches on a SINGLE page (P2-13, resolved
# live 2026-09-04 by scripts/probe_p2_13_search_navmax.py): nav_max is ALWAYS 0, `&p=N`
# re-serves the SAME page, and the result is capped SERVER-SIDE at SEARCH_RESULT_CAP
# distinct rows. The cap is GLOBAL, not list-specific — confirmed across lists: broad
# term "a" → exactly 300 on both list 8 (Blacklist) and list 21 (Gift cards), while
# smaller lists return their true count (< 300). So a search is COMPLETE iff it
# returned FEWER than the cap; a result AT the cap may have been cut off → truncated.
SEARCH_RESULT_CAP = 300

# resolve_pinned retries a TRANSIENT probe failure (a 5xx/429 server blip or a
# timeout/connection error) with a bounded backoff before giving up — an AKS 503
# wrongly failed an aperçu that resolved fine seconds later (Romain 2026-09-01).
# A 404/410 is a REAL absence and is never retried; a 200 short-circuits.
RESOLVE_ATTEMPTS = 3
RESOLVE_RETRY_WAIT_S = 1.5
_TRANSIENT_RESOLVE_STATUSES = frozenset({429, 500, 502, 503, 504})

# AKS product-page shapes. KEY pages: buy-<slug>-cd-key-compare-prices/ — but some
# omit the "cd-" (buy-the-green-light-key-compare-prices/, id 216255); the slug is
# captured NON-greedily so the "cd-"/"key" marker is never absorbed into it (greedy +
# optional cd- would eat "…-cd" for a bare "key"). ACCOUNT pages: buy-<slug>-<platform>
# -account-compare-prices/ — slug stays greedy so the game name keeps its own hyphens
# before the <platform>-account marker. LEGACY pages (Romain 2026-09-07): a handful of
# older products live under compare-and-buy-cd-key-for-digital-download-<slug>/ (e.g.
# Minecraft — the modern buy-…-compare-prices form 404s), so recognise it too, else a
# genuine top-popular URL is wrongly rejected as "not an AKS product URL".
# CONSOLE pages [R45] (Romain 2026-09-15): buy-<slug>-<kind>-compare-prices/ with kind ∈
# CONSOLE_URL_KINDS (the page kinds of src/console_keys minus the PC "cd-key"), longest
# kind first so "nintendo-switch-2" is never read as "nintendo-switch" + a "-2" slug tail.
# The KEY alternative stays FIRST: a PC slug that happens to contain a kind word
# ("some-ps4-emulator-cd-key") is still the PC page.
CONSOLE_URL_KINDS: tuple[str, ...] = tuple(k for k in CONSOLE_PAGE_KINDS if k != "cd-key")
_CONSOLE_KIND_ALT = "|".join(re.escape(k) for k in sorted(CONSOLE_URL_KINDS, key=len, reverse=True))
_SLUG_RE = re.compile(
    r"/blog/(?:"
    r"buy-(?:([a-z0-9-]+?)-(?:cd-)?key|([a-z0-9-]+)-[a-z0-9-]+-account"
    r"|([a-z0-9-]+)-(" + _CONSOLE_KIND_ALT + r"))-compare-prices"
    r"|compare-and-buy-(?:cd-key-for-digital-download-)?([a-z0-9-]+)"
    r")/?"
)


class SearchUnreadable(RuntimeError):
    """A search page never rendered its feed table (not a login bounce, not a real
    empty result). Surfaced per-merchant so a broken/errored search is never read as
    a genuine "0 offers found" (adversarial review 2026-08-24)."""


class ConsolePageRefused(RuntimeError):
    """A console page URL was pasted while the run is ``--no-consoles`` (PC-only).
    Raised BEFORE any fetch — nothing is done for that URL; it is reported per-URL
    (``resolved: false``) with this explicit message, never guessed to the PC page."""


class PageRef:
    """What an operator URL names: the game ``slug`` and the page ``kind`` — "cd-key"
    (key pages, the bare "-key-" shape and the legacy compare-and-buy shape), "account"
    (``<platform>-account`` pages) or one of CONSOLE_URL_KINDS [R45]. (A plain class,
    not a dataclass: this script is loaded by ``spec_from_file_location`` without a
    ``sys.modules`` entry, which a dataclass under ``from __future__ import annotations``
    cannot resolve on Python 3.13.)"""

    __slots__ = ("slug", "kind")

    def __init__(self, slug: str, kind: str) -> None:
        self.slug = slug
        self.kind = kind

    @property
    def console(self) -> bool:
        return self.kind in CONSOLE_URL_KINDS

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PageRef) and (self.slug, self.kind) == (other.slug, other.kind)

    def __repr__(self) -> str:
        return f"PageRef(slug={self.slug!r}, kind={self.kind!r})"


def parse_page_url(url: str) -> PageRef | None:
    """Slug + page kind from an AKS product URL, tolerant of query/fragment/trailing
    slash. None for anything else (wrong host, not a product path).

    Host-validated: only allkeyshop.com URLs qualify. A pasted wrong-host URL that
    happens to match the product path (a domain typo, a mirror/scraper) would
    otherwise reach http_get with the staff UA and raise a bare ValueError (the UA
    is allkeyshop-only) — here it returns None → reported+skipped per-URL, never a
    crash (adversarial review 2026-08-24)."""
    if not _allkeyshop_host(url or ""):
        return None
    m = _SLUG_RE.search((url or "").split("?", 1)[0].split("#", 1)[0])
    if not m:
        return None
    key_slug, account_slug, console_slug, console_kind, legacy_slug = m.groups()
    if key_slug:
        return PageRef(key_slug, "cd-key")
    if account_slug:
        return PageRef(account_slug, "account")
    if console_slug:
        return PageRef(console_slug, console_kind)
    return PageRef(legacy_slug, "cd-key")


def extract_slug(url: str) -> str | None:
    """Slug from an AKS product URL (see :func:`parse_page_url`)."""
    ref = parse_page_url(url)
    return ref.slug if ref else None


def page_kind_of(url: str) -> str:
    """The page kind of a resolved page URL; "cd-key" when the URL is not in the product
    grammar (a synthetic test resolution) — i.e. the historical PC reading."""
    ref = parse_page_url(url or "")
    return ref.kind if ref else "cd-key"


def _pace_between_urls(http_get_fn: Callable[..., Any], index: int) -> None:
    """Politeness pacing between consecutive operator URLs (audit 2026-09-09): the
    resolve loop had NO pacing at all, and keep-alive made it the densest staff-UA
    burst (~30 req/s on a long list). Same budget as the matcher's slug probes; never
    under an injected test stub, never before the first URL."""

    if index and http_get_fn is http_get:
        time.sleep(AKS_PROBE_DELAY_S)


def resolve_pinned(url: str, http_get_fn: Callable[..., Any] = http_get, *,
                   consoles: bool = True) -> AksResolution:
    """Resolve the OPERATOR-provided AKS page directly (no slug guessing).

    Raises on anything that is not a clean, parseable 200 — fail-closed, so a
    typo'd / dead / throttled URL is reported and skipped, never guessed around.
    A TRANSIENT probe failure (5xx/429 server blip or timeout/connection error) is
    RETRIED with a bounded backoff (``RESOLVE_ATTEMPTS``) before failing closed — an
    AKS 503 wrongly failed an aperçu that resolved fine seconds later. A 404/410 is a
    REAL absence and is never retried; a 200 short-circuits.

    [R45] a CONSOLE page URL (CONSOLE_URL_KINDS) is read exactly like the PC page (same
    probe, same ``_resolution_from_body`` — a console page has no "official platforms"
    line, that is fine); under ``consoles=False`` it is REFUSED before any fetch
    (:class:`ConsolePageRefused`) — a PC-only run never works a console page.
    """
    ref = parse_page_url(url)
    if ref is None:
        raise AksProbeUnreliable(f"not an AKS product URL: {url!r}")
    slug = ref.slug
    if ref.console and not consoles:
        raise ConsolePageRefused(
            f"console page ({ref.kind}) refused under --no-consoles — re-run with "
            f"--consoles to work on it: {url}")
    probe = None
    for attempt in range(1, RESOLVE_ATTEMPTS + 1):
        probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
        if probe.ok and probe.status == 200 and probe.body:
            break                                    # got the page
        if probe.status in (404, 410):
            break                                    # real absence — never retry
        if probe.status == 429:
            break                                    # explicit rate limit: STOP, never retry
        transient = probe.status is None or probe.status in _TRANSIENT_RESOLVE_STATUSES
        if not transient or attempt == RESOLVE_ATTEMPTS:
            break                                    # persistent / exhausted → fail closed
        if http_get_fn is http_get:
            time.sleep(RESOLVE_RETRY_WAIT_S)         # backoff (no sleep under test stubs)
    if not (probe.ok and probe.status == 200 and probe.body):
        raise AksProbeUnreliable(f"{url} -> {probe.status or probe.error}",
                                 status=probe.status, slug=slug)
    resolution = _resolution_from_body(slug, url, probe.body)
    if resolution is None:
        raise AksNameUnreadable(f"{url} -> 200 but no product id / name")
    return resolution


def _search_url(feed_page: str, available: str, term: str, field: str, page: int = 1) -> str:
    """The AKS feed tool's SEARCH form is a GET to ``page=aks-merchant-feeds-search``
    with ``list`` (the feed list number). We OMIT ``store`` so ONE search returns
    matches across ALL merchants — we then keep only the vetted-allowlist stores
    from the results (Romain 2026-08-25: 2 searches/game instead of 2×N). Appending
    the search to the feed page is silently ignored (verified live 2026-08-24);
    ``search[field]`` = name|url|productId; ``p`` paginates."""
    list_no = str(feed_page).rsplit("-", 1)[-1]     # "aks-merchant-feeds-9" -> "9"
    q = {"page": "aks-merchant-feeds-search", "available": available,
         "list": list_no, "search[search]": term, "search[field]": field,
         # Le tri stable du feed (`extractor.FEED_ORDER`, 2026-09-24) — revue de Romain du 25/09.
         "orderBy": "id", "order": "desc"}
    if page > 1:
        q["p"] = page
    return AKS_ADMIN_URL + "?" + urllib.parse.urlencode(q)


def _read_one_page(session: Any, url: str,
                   render_waits: tuple[float, ...] = FEED_UI_RENDER_WAITS) -> list[dict]:
    """Navigate a search URL and return ONE page of rows [{id,url,name,price,store_id}].

    Polls the render race (feed_ui late) before concluding "no results": rows →
    return; feed_ui rendered with 0 rows → a real empty result; login bounce →
    fail-closed; never rendered after the backoff → SearchUnreadable (never a silent 0)."""
    session.navigate(url)
    if session.is_login_page():
        raise NotLoggedInError("feed bounced to wp-login — not logged in")
    rows = session.page_offer_rows()
    if rows:
        return rows
    # 0 rows on the FIRST read is never trusted directly (Romain audit 2026-09-07): a
    # transient blank shows feed_ui=True with rows still loading — the same empty-confirm
    # the extractor/submitter do — and a not-yet-rendered table shows feed_ui=False. Both
    # are resolved by a confirming re-read (0-wait first, then the render-race backoff):
    # rows → return; feed_ui + 0 rows on the RE-READ → a real empty result; never rendered
    # after the whole backoff → SearchUnreadable (never a silent 0). The prior code
    # trusted feed_ui + 0 rows on the first read → a transient blank became a false empty.
    for wait in (0.0, *render_waits):
        time.sleep(wait)
        if session.is_login_page():
            raise NotLoggedInError("feed bounced to wp-login — not logged in")
        rows = session.page_offer_rows()
        if rows:
            return rows
        if session.feed_page_state().get("feed_ui"):
            return []          # confirmed rendered with 0 matches — a real empty result
    raise SearchUnreadable(f"search page never rendered/settled: {url}")


def _read_search_pages(session: Any, feed_page: str, available: str, term: str,
                       field: str) -> tuple[list[dict], bool]:
    """Read an all-merchants search. Returns (rows, truncated).

    P2-13 (resolved live 2026-09-04, scripts/probe_p2_13_search_navmax.py): the AKS
    search shows ALL matches on ONE page — nav_max is always 0, `&p=N` re-serves the
    same page, and the result is capped server-side at SEARCH_RESULT_CAP distinct rows.
    So read page 1 ONLY and flag `truncated` iff the result HIT the cap — the one case
    where matches may have been cut off (the manager's preview_incomplete gate then
    blocks that game). A sub-cap result is COMPLETE.

    (The old code read up to 3 pages bounded by a 100-row short-page heuristic. Given
    `&p=N` re-serves page 1, that re-read the same page twice AND mis-flagged truncated
    for ANY ≥100-row result — a false over-block. The once-considered nav_max→truncated
    wiring is moot: nav_max is always 0 on the search page.)"""
    rows = _read_one_page(session, _search_url(feed_page, available, term, field, 1))
    return rows, len(rows) >= SEARCH_RESULT_CAP


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    """Union by offer id, then by url (a re-import can rotate the id)."""
    out: list[dict] = []
    seen_id: set[str] = set()
    seen_url: set[str] = set()
    for r in rows:
        rid = str(r.get("id") or "")
        rurl = str(r.get("url") or "")
        if (rid and rid in seen_id) or (rurl and rurl in seen_url):
            continue
        if rid:
            seen_id.add(rid)
        if rurl:
            seen_url.add(rurl)
        out.append(r)
    return out


def search_all_merchants(session: Any, resolution: AksResolution, available: str,
                         feed_page: str) -> tuple[list[dict], dict]:
    """ONE all-merchants search per game, by NAME and by URL(slug), unioned. Returns
    (rows, meta) — rows across every merchant (each carries its store_id); the caller
    filters to the vetted allowlist. ``meta.truncated`` flags a result deeper than
    the page cap (never silently cut).

    [R45] for a CONSOLE page the name term is the page IDENTITY (``console_page_identity``:
    "Hades PS5" → "Hades", "Hades Xbox Series" → "Hades") — the merchant title carries
    its own platform phrase ("Hades (PS4 / PS5)"), never the AKS page suffix, so a
    search by "Hades Xbox Series" would find nothing; the URL term is the game slug
    (the page kind is not part of it). A PC page is searched exactly as before."""
    page_kind = page_kind_of(resolution.url)
    page_name = (console_page_identity(resolution.aks_name) if page_kind in CONSOLE_URL_KINDS
                 else resolution.aks_name)
    name_term = cleaned_title(page_name) or page_name
    url_term = resolution.slug
    meta: dict[str, Any] = {"name_term": name_term, "url_term": url_term, "truncated": False,
                            "page_kind": page_kind}
    # [R42] a merchant may spell the sequel number the other way ("Crusader Kings III" for
    # the AKS page "Crusader Kings 3") — search both spellings, name and URL (2026-09-10).
    terms = [(name_term, "name"), (url_term, "url")]
    for term, field in list(terms):
        alt = swap_numerals(term or "")
        if alt and alt != term:
            terms.append((alt, field))
    meta["alt_terms"] = [t for t, _ in terms[2:]]
    rows: list[dict] = []
    for term, field in terms:
        if not term:
            continue
        found, hit_cap = _read_search_pages(session, feed_page, available, term, field)
        meta["truncated"] = meta["truncated"] or hit_cap
        rows.extend(found)
    return _dedupe_rows(rows), meta


def _page_key(url: str) -> str:
    """URL identity for the pinned-page cache: no query / fragment / trailing slash (a
    tab-bar href and the operator's paste may differ in those only)."""
    return (url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")


class PinnedPage:
    """The resolver handed to ``match_offer`` for ONE operator page [R45].

    The matcher asks a resolver for pages by KIND: ``resolver(name)`` = the PC page
    (``page_kind`` "cd-key", the ``_pc_plan`` path and the console branch's PC anchor),
    ``resolver(name, page_kind=<kind>)`` = the console page of that kind (the console
    anchor when no PC page exists), then ``page_resolver(url)`` for every declared
    platform page linked from the anchor's tab bar. Pinned semantics, never a guess:

    * the pinned page answers its OWN kind — and, when it is not a console page (a PC
      or account page), the plain PC request too (the historical by-urls behaviour:
      the operator's page is the page, R01 decides);
    * any OTHER kind is answered from the pinned page's tab bar (``console_pages``,
      the platform tabs AKS itself links — "Hades PS5" → its PC / PS4 tabs) through
      ``page_resolver`` (read-only, guarded), or None when the page has no such tab
      (→ the matcher's own fail-closed skip). So a console row found from a console
      page still resolves its PC anchor (Play Anywhere is the PC page's truth) and
      ALL its declared pages, exactly like a sweep;
    * page reads are CACHED per pinned page (one read per sibling page per game, not
      per row; the pinned page itself is served from memory when a tab points back to
      it). A probe error is never cached — it stays a per-row outcome the throttle
      guard sees every time.
    """

    def __init__(self, resolution: AksResolution, kind: str,
                 page_resolver: Callable[[str], AksResolution | None]) -> None:
        self.resolution = resolution
        self.kind = kind
        self.page_resolver = page_resolver
        self._cache: dict[str, AksResolution | None] = {}
        self.reads: list[str] = []          # every URL actually read (tests / audit)

    def __call__(self, _name: str, *, page_kind: str = "cd-key", **_kwargs: Any) -> AksResolution | None:
        if page_kind == self.kind or (page_kind == "cd-key" and self.kind not in CONSOLE_URL_KINDS):
            return self.resolution
        url = self.resolution.console_pages.get(page_kind)
        if not url:
            return None
        return self.page(url)

    def page(self, url: str) -> AksResolution | None:
        key = _page_key(url)
        if key == _page_key(self.resolution.url):
            return self.resolution
        if key in self._cache:
            return self._cache[key]
        self.reads.append(url)
        result = self.page_resolver(url)     # errors propagate, never cached
        self._cache[key] = result
        return result


def _off_page_reason(candidate: dict, page_id: str) -> str | None:
    """[R45] a candidate QUALIFIES for the requested page iff ANY of its targets is
    that page — else the explicit reason it is not entered from here. A PC candidate's
    only target is the pinned page (no-op); a console candidate found from the PC
    page qualifies only through a Play Anywhere XBOX_PC target; a lone PS4 key found
    from the PS5 page targets the PS4 page only → not entered from the PS5 page."""
    targets = candidate.get("targets") or []
    if any(str(t.get("aks_product_id")) == str(page_id) for t in targets):
        return None
    where = ", ".join(f"{t.get('platform')} {t.get('aks_product_id')}" for t in targets) or "no page"
    return (f"not on the requested page {page_id}: this offer targets {where} — "
            "not entered from this page (R45)")


def plan_from_rows(rows: list[dict], resolution: AksResolution, merchant: str,
                   store_id: str, *, consoles: bool = True,
                   page_resolver: Callable[[str], AksResolution | None] = resolve_aks_url) -> dict:
    """Build candidates for ONE merchant from its already-fetched search rows, via
    match_offer pinned to the operator's AKS page (its R01 name check rejects a
    search over-match). [R45] ``consoles`` runs the console branch; every candidate
    must then TARGET the requested page (:func:`_off_page_reason`) — a multi-target
    candidate is kept WHOLE (all its pages), never trimmed to the requested one.
    An :class:`AksThrottled` (429 / consecutive unreliable page reads) propagates: it
    stops the run, never a per-row "error:" skip."""
    pinned = PinnedPage(resolution, page_kind_of(resolution.url), page_resolver)
    candidates: list[dict] = []
    skipped: list[dict] = []
    for r in rows:
        offer = NormalizedOffer(
            offer_id=str(r.get("id") or ""),
            name=str(r.get("name") or ""),
            url=str(r.get("url") or ""),
            merchant=merchant,
            store_id=str(store_id),
            price=r.get("price"),
        )
        try:
            result = match_offer_pinned(offer, pinned, consoles=consoles, page_resolver=pinned.page)
        except AksThrottled:
            raise                        # fail-closed STOP of the whole run (never a row skip)
        except Exception as exc:  # a resolver/probe error on THIS offer → skip, keep going
            skipped.append({"name": offer.name, "url": offer.url, "reason": f"error: {exc}"})
            continue
        if isinstance(result, Candidate):
            cand = result.to_dict()
            off_page = _off_page_reason(cand, resolution.product_id)
            if off_page is not None:
                skipped.append({"name": offer.name, "url": offer.url, "reason": off_page})
                continue
            candidates.append(cand)
        else:  # SkippedOffer
            skipped.append({"name": offer.name, "url": offer.url, "reason": result.reason})
    return {"merchant": merchant, "store_id": str(store_id), "found": len(rows),
            "candidates": candidates, "skipped": skipped}


def match_offer_pinned(offer: NormalizedOffer, pinned_resolver: Callable[..., AksResolution | None],
                       *, consoles: bool = True,
                       page_resolver: Callable[[str], AksResolution | None] | None = None):
    """``match_offer`` with the AKS page PINNED to the operator-provided one — its
    R01 name check still rejects an offer the search over-matched (import here to
    keep the module import-light for unit tests of the pure helpers). [R45]
    ``consoles`` is threaded to the matcher; ``page_resolver`` reads the console
    target pages (the pinned page's cached reader in production)."""
    from src.matcher import match_offer
    kwargs: dict[str, Any] = {"consoles": consoles}
    if page_resolver is not None:
        kwargs["page_resolver"] = page_resolver
    return match_offer(offer, resolver=pinned_resolver, **kwargs)


def _targets(arg: str | None) -> list[tuple[str, str]]:
    """Merchant scope. Default = the full vetted allowlist (Romain: all allowed)."""
    if not arg:
        return [(m["name"], m["store_id"]) for m in auto_merchants.allowed_list()]
    out: list[tuple[str, str]] = []
    for tok in arg.split(","):
        tok = tok.strip()
        if not tok:
            continue
        merchant, _, store = tok.partition(":")
        out.append((merchant.strip(), store.strip()))
    return out


def _parse_urls(args: argparse.Namespace) -> list[str]:
    raw = ""
    if args.urls_file:
        raw = Path(args.urls_file).read_text(encoding="utf-8")
    if args.urls:
        raw += "\n" + args.urls
    urls: list[str] = []
    for line in re.split(r"[\s,]+", raw):
        u = line.strip()
        if u and u not in urls:
            urls.append(u)
    return urls


def run_plan(urls: list[str], targets: list[tuple[str, str]], *, available: str,
             feed_page: str, endpoint: str, run_dir: Path,
             http_get_fn: Callable[..., Any] = http_get, session: Any = None,
             logger: Any = None, consoles: bool = True,
             page_resolver: Callable[[str], AksResolution | None] | None = None) -> dict:
    """[R45] ``consoles`` (default True, Romain 2026-09-15) is threaded to every match
    call and to the URL resolution (a console page URL is refused per-URL without it).
    ``page_resolver`` reads the console target pages by URL (default: the matcher's
    ``resolve_aks_url`` through ``http_get_fn``); in production it is wrapped in a
    throttle guard SHARING the URL-resolution guard's state — one consecutive-unreliable
    count / grace budget for the whole run, like ``match_feed``."""
    recap: dict[str, Any] = {"mode": "dry-run", "available": available,
                             "consoles": bool(consoles),
                             "merchants": [m for m, _ in targets], "games": [],
                             "aborted": None,
                             "totals": {"games": len(urls), "resolved": 0, "candidates": 0}}
    emit = logger.log if logger is not None else (lambda *a, **k: None)

    def _flush() -> None:
        _write_json_atomic(run_dir / "recap.json", recap)

    emit("run_start", urls=len(urls), merchants=len(targets), consoles=bool(consoles))
    # Resolve every URL first (read-only http_get, no browser) so a bad URL is
    # reported without holding the browser lock.
    resolved: list[tuple[str, AksResolution]] = []
    # Review 2026-09-09: the same throttle backstop as match_feed — a 429 or 5 consecutive
    # unreliable probes on distinct pages STOP the run (recap.aborted = aks_throttled)
    # instead of hammering one throttled URL after another to a "completed" 0-résolu preview.
    real_http = http_get_fn is http_get
    guard = _ThrottleGuard(lambda u: resolve_pinned(u, http_get_fn, consoles=consoles),
                           sleep=time.sleep if real_http else (lambda s: None))
    if page_resolver is None:
        page_resolver = lambda u, _h=http_get_fn: resolve_aks_url(u, _h)  # noqa: E731
    # [R45] console target-page reads share the run's throttle state (one stream of
    # probes, one abort) — an injected test reader is guarded the same way, no sleep.
    page_guard = _ThrottleGuard(page_resolver, sleep=time.sleep if real_http else (lambda s: None),
                                shared=guard)
    for index, url in enumerate(urls):
        _pace_between_urls(http_get_fn, index)
        try:
            resolution = guard(url)
        except AksThrottled as exc:
            recap["aborted"] = "aks_throttled"
            recap["games"].append({"url": url, "resolved": False,
                                   "reason": f"AksThrottled: {exc}"[:200]})
            emit("game_resolved", url=url, ok=False, reason=f"AksThrottled: {exc}"[:160])
            emit("run_aborted", reason="aks_throttled", detail=str(exc)[:160])
            _flush()
            return recap
        except Exception as exc:
            # Per-URL fail-closed isolation: ANY resolution error (bad URL, throttle,
            # markup drift → AksPageUnparseable, wrong-host ValueError, …) is reported
            # for THIS url and skipped — never aborts the whole batch (adversarial
            # review 2026-08-24). Resolution uses http_get only (no browser session),
            # so NotLoggedInError cannot arise here.
            recap["games"].append({"url": url, "resolved": False,
                                   "reason": f"{type(exc).__name__}: {exc}"[:200]})
            emit("game_resolved", url=url, ok=False, reason=f"{type(exc).__name__}: {exc}"[:160])
            _flush()
            continue
        resolved.append((url, resolution))
        recap["totals"]["resolved"] += 1
        emit("game_resolved", url=url, ok=True,
             aks_product_id=resolution.product_id, aks_name=resolution.aks_name)

    if not resolved:
        emit("run_done", resolved=0, candidates=0)
        _flush()
        return recap

    if session is not None:                       # injected (tests) — no real browser
        _plan_games(session, resolved, targets, recap, available, feed_page, _flush, emit,
                    consoles=consoles, page_resolver=page_guard)
    else:
        with browser_lock(ROOT,
                          label="11_data_entry_by_urls (read-only) " + " ".join(urls)[:120]):
            with SubmitSession(endpoint) as live:
                _plan_games(live, resolved, targets, recap, available, feed_page, _flush, emit,
                            consoles=consoles, page_resolver=page_guard)
    if recap.get("aborted"):
        emit("run_aborted", reason=recap["aborted"])
    else:
        emit("run_done", resolved=recap["totals"]["resolved"],
             candidates=recap["totals"]["candidates"])
    _flush()
    return recap


def _plan_games(session: Any, resolved: list[tuple[str, AksResolution]], targets, recap: dict,
                available: str, feed_page: str, flush: Callable[[], None],
                emit: Callable[..., Any] = lambda *a, **k: None, *, consoles: bool = True,
                page_resolver: Callable[[str], AksResolution | None] = resolve_aks_url) -> None:
    # store_id -> merchant name, the vetted allowlist we keep from the results.
    store_to_merchant = {str(store): merchant for merchant, store in targets}
    for url, resolution in resolved:
        page_kind = page_kind_of(resolution.url)
        game: dict[str, Any] = {
            "url": url, "resolved": True,
            "aks_product_id": resolution.product_id,
            "aks_name": resolution.aks_name,
            "aks_url": resolution.url,
            "page_kind": page_kind,                 # [R45] "cd-key" / "account" / a console kind
            "merchants": [], "total_candidates": 0}
        emit("game_start", aks_name=resolution.aks_name, aks_product_id=resolution.product_id,
             page_kind=page_kind)
        try:
            rows, meta = search_all_merchants(session, resolution, available, feed_page)
        except NotLoggedInError:
            # Fail-closed STOP — NEVER a re-auth trigger (AGENTS.md).
            recap["aborted"] = "not_logged_in"
            game["error"] = "not_logged_in"
            recap["games"].append(game)
            emit("game_done", aks_name=resolution.aks_name, error="not_logged_in")
            flush()
            return
        except SearchUnreadable as exc:
            game["error"] = "search_unreadable"
            game["detail"] = str(exc)[:160]
            recap["games"].append(game)
            emit("game_done", aks_name=resolution.aks_name, error="search_unreadable")
            flush()
            continue

        # Group the all-merchants results by store, keeping only the vetted allowlist.
        # Off-allowlist rows (non-vetted merchants) are recorded WITH their URL so the
        # operator can still see every search result, not just a count (Romain 2026-08-25).
        by_store: dict[str, list[dict]] = {}
        off_allowlist_offers: list[dict] = []
        for r in rows:
            sid = str(r.get("store_id") or "")
            if sid in store_to_merchant:
                by_store.setdefault(sid, []).append(r)
            else:
                off_allowlist_offers.append({"store_id": sid, "name": str(r.get("name") or ""),
                                             "url": str(r.get("url") or "")})
        game["search"] = {**meta, "found": len(rows), "off_allowlist": len(off_allowlist_offers)}
        game["off_allowlist_offers"] = off_allowlist_offers
        emit("game_searched", aks_name=resolution.aks_name, found=len(rows),
             off_allowlist=len(off_allowlist_offers), truncated=meta["truncated"])

        for merchant, store_id in targets:
            mrows = by_store.get(str(store_id))
            if not mrows:                      # merchant absent from the results — omit
                continue
            try:
                per = plan_from_rows(mrows, resolution, merchant, str(store_id),
                                     consoles=consoles, page_resolver=page_resolver)
            except AksThrottled as exc:
                # [R45] a 429 / consecutive unreliable console-page reads STOP the run
                # (same fail-closed abort as the URL resolution loop), never a silent
                # per-row "error:" skip that plows on to the next merchant.
                recap["aborted"] = "aks_throttled"
                game["error"] = "aks_throttled"
                game["detail"] = str(exc)[:160]
                recap["games"].append(game)
                emit("game_done", aks_name=resolution.aks_name, error="aks_throttled")
                flush()
                return
            game["merchants"].append(per)
            game["total_candidates"] += len(per["candidates"])
            for c in per["candidates"]:
                o, reg, ed = c.get("offer", {}), c.get("region", {}), c.get("edition", {})
                emit("candidate", aks_name=resolution.aks_name, merchant=merchant,
                     name=o.get("name", ""), region=f"{reg.get('label')}({reg.get('id')})",
                     edition=f"{ed.get('label')}({ed.get('id')})",
                     targets=len(c.get("targets") or []))
            # Stream each SKIPPED search result live, with its URL + reason, so the
            # operator sees what was ignored in real time (Romain 2026-08-25).
            for sk in per["skipped"]:
                emit("skipped", aks_name=resolution.aks_name, merchant=merchant,
                     name=sk.get("name", ""), url=sk.get("url", ""), reason=sk.get("reason", ""))
            emit("merchant_done", aks_name=resolution.aks_name, merchant=merchant,
                 found=per["found"], candidates=len(per["candidates"]),
                 skipped=len(per["skipped"]))
        recap["totals"]["candidates"] += game["total_candidates"]
        recap["games"].append(game)
        emit("game_done", aks_name=resolution.aks_name, candidates=game["total_candidates"])
        flush()


def write_report(recap: dict, run_dir: Path) -> None:
    """Human preview in the skill's normalized block form (no tables/prices)."""
    lines: list[str] = []
    for game in recap.get("games", []):
        if not game.get("resolved"):
            lines.append(f"❌ {game['url']} — non résolu : {game.get('reason', '')}")
            lines.append("")
            continue
        kind = game.get("page_kind") or "cd-key"
        kind_note = f" [page {kind}]" if kind in CONSOLE_URL_KINDS else ""
        lines.append(f"🎯 {game['aks_product_id']} — {game['aks_name']}{kind_note}")
        lines.append(f"   {game['url']}")
        if game.get("error"):                       # game-level (search/login) failure
            lines.append(f"   ⚠ {game['error']}{(' — ' + game['detail']) if game.get('detail') else ''}")
            lines.append("")
            continue
        n = 0
        for per in game.get("merchants", []):
            for cand in per.get("candidates", []):
                n += 1
                o = cand["offer"]
                reg, ed = cand["region"], cand["edition"]
                lines.append(f"   #{n} [{per['merchant']}] {o['name']}")
                lines.append(f"      {o['url']}")
                lines.append(f"      {reg['label']}({reg['id']}), {ed['label']}({ed['id']})")
                # [R45] every EXTRA target page of a multi-target candidate, and the rule
                # the operator must know: a cross-gen key requested from one console page
                # is written on ALL its declared pages (the candidate is never split).
                targets = cand.get("targets") or []
                for t in targets[1:]:
                    treg = t.get("region") or {}
                    lines.append(f"      ↳ {t.get('platform')} {t.get('aks_product_id')} — "
                                 f"{t.get('aks_name')} · {treg.get('label')}({treg.get('id')})")
                if len(targets) > 1:
                    lines.append(f"      ({len(targets)} cibles : une clé cross-gen demandée depuis une "
                                 "page console est écrite sur toutes ses pages déclarées)")
        if n == 0:
            lines.append("   (aucune offre à saisir trouvée)")
        lines.append("")
    lines.append(f"— {recap['totals']['candidates']} offre(s) à saisir sur "
                 f"{recap['totals']['resolved']}/{recap['totals']['games']} jeu(x) résolu(s).")
    (run_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Data entry from a list of AKS page URLs (dry-run).")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--urls", help="Whitespace/comma-separated AKS page URLs.")
    ap.add_argument("--urls-file", help="File with one AKS page URL per line.")
    ap.add_argument("--targets", help="Override merchant scope 'M:store,...' (default: full allowlist).")
    ap.add_argument("--available", default="all", choices=["all", "pending"])
    ap.add_argument("--feed-page", default=DEFAULT_FEED_PAGE)
    ap.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Read-only preview (the only mode in stage 1).")
    # [R45] Romain 2026-09-15: consoles by default everywhere, the page-driven entry
    # included. --no-consoles = the historical PC-only run (console rows → "console"
    # skip; a console page URL is refused per-URL with an explicit message).
    ap.add_argument("--consoles", dest="consoles", action="store_true", default=True,
                    help="Match console keys too (DEFAULT): console rows resolve their AKS "
                         "platform pages; console page URLs (…-ps5-/-xbox-series-/… "
                         "-compare-prices/) are accepted.")
    ap.add_argument("--no-consoles", dest="consoles", action="store_false",
                    help="PC-only run: console rows keep the 'console' skip and a console "
                         "page URL is refused (nothing done for it).")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    urls = _parse_urls(args)
    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if not urls:
        recap = {"mode": "dry-run", "aborted": "no_urls", "games": [],
                 "totals": {"games": 0, "resolved": 0, "candidates": 0}}
        _write_json_atomic(run_dir / "recap.json", recap)
        print(json.dumps({"run_id": args.run_id, "aborted": "no_urls"}))
        return 2

    # [24] Fable re-audit 2026-09-06: this stage drives the shared AKS tab (a live
    # SubmitSession), so it MUST pass the same fail-closed gate as every other browser
    # stage BEFORE touching it — invariants green AND authoritative on the VPS target.
    # build_report includes validate_official_cdp_endpoint, so an unvalidated/non-official
    # --endpoint also fails the gate here (never drive the tab through a bogus endpoint).
    report = None
    for attempt in range(3):
        report = build_report(endpoint=args.endpoint)
        if report["ok"] and report["authoritative"]:
            break
        if attempt < 2:
            time.sleep(2)
    if not (report["ok"] and report["authoritative"]):
        recap = {"mode": "dry-run", "aborted": "invariants not green/authoritative",
                 "games": [], "totals": {"games": 0, "resolved": 0, "candidates": 0}}
        _write_json_atomic(run_dir / "recap.json", recap)
        print(json.dumps({"run_id": args.run_id, "aborted": recap["aborted"],
                          "invariants": {"ok": report["ok"],
                                         "authoritative": report["authoritative"]}}))
        return 2

    logger = RunLogger(args.run_id, log_dir=ROOT / "logs")
    try:
        recap = run_plan(urls, _targets(args.targets), available=args.available,
                         feed_page=args.feed_page, endpoint=args.endpoint, run_dir=run_dir,
                         logger=logger, consoles=args.consoles)
    except BrowserBusyError as exc:
        print(json.dumps({"run_id": args.run_id, "aborted": f"browser_busy: {exc}"}))
        return 2
    write_report(recap, run_dir)
    print(json.dumps({"run_id": args.run_id, "mode": "dry-run", "consoles": bool(args.consoles),
                      "resolved": recap["totals"]["resolved"],
                      "games": recap["totals"]["games"],
                      "candidates": recap["totals"]["candidates"],
                      "aborted": recap.get("aborted")}))
    return 0 if not recap.get("aborted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
