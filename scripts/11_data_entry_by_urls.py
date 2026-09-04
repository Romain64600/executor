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
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.admin import auto_merchants  # noqa: E402
from src.aks_env import OFFICIAL_CDP_ENDPOINT, _allkeyshop_host  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.extractor import AKS_ADMIN_URL, DEFAULT_FEED_PAGE, NotLoggedInError  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.matcher import (  # noqa: E402
    AKS_PROBE_UA,
    AksNameUnreadable,
    AksProbeUnreliable,
    AksResolution,
    Candidate,
    SkippedOffer,
    _resolution_from_body,
    cleaned_title,
    http_get,
)
from src.submit_session import SubmitSession  # noqa: E402

# Same render-race backoff the extractor/mover poll through (feed_ui renders late).
FEED_UI_RENDER_WAITS = (1.0, 2.0, 4.0)
# One AKS feed page holds up to 100 rows. The all-merchants search for one game
# rarely exceeds a page or two; read up to SEARCH_MAX_PAGES and FLAG (never silently
# drop) a deeper result.
SEARCH_MAX_ROWS_LOGGED = 100
SEARCH_MAX_PAGES = 3

# resolve_pinned retries a TRANSIENT probe failure (a 5xx/429 server blip or a
# timeout/connection error) with a bounded backoff before giving up — an AKS 503
# wrongly failed an aperçu that resolved fine seconds later (Romain 2026-09-01).
# A 404/410 is a REAL absence and is never retried; a 200 short-circuits.
RESOLVE_ATTEMPTS = 3
RESOLVE_RETRY_WAIT_S = 1.5
_TRANSIENT_RESOLVE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Two AKS product-page shapes. KEY pages: buy-<slug>-cd-key-compare-prices/ —
# but some omit the "cd-" (buy-the-green-light-key-compare-prices/, id 216255);
# the slug is captured NON-greedily so the "cd-"/"key" marker is never absorbed
# into it (greedy + optional cd- would eat "…-cd" for a bare "key"). ACCOUNT
# pages: buy-<slug>-<platform>-account-compare-prices/ — slug stays greedy so the
# game name keeps its own hyphens before the <platform>-account marker.
_SLUG_RE = re.compile(
    r"/blog/buy-(?:([a-z0-9-]+?)-(?:cd-)?key|([a-z0-9-]+)-[a-z0-9-]+-account)"
    r"-compare-prices/?"
)


class SearchUnreadable(RuntimeError):
    """A search page never rendered its feed table (not a login bounce, not a real
    empty result). Surfaced per-merchant so a broken/errored search is never read as
    a genuine "0 offers found" (adversarial review 2026-08-24)."""


def extract_slug(url: str) -> str | None:
    """Slug from an AKS product URL, tolerant of query/fragment/trailing slash.

    Host-validated: only allkeyshop.com URLs qualify. A pasted wrong-host URL that
    happens to match the product path (a domain typo, a mirror/scraper) would
    otherwise reach http_get with the staff UA and raise a bare ValueError (the UA
    is allkeyshop-only) — here it returns None → reported+skipped per-URL, never a
    crash (adversarial review 2026-08-24)."""
    if not _allkeyshop_host(url or ""):
        return None
    m = _SLUG_RE.search((url or "").split("?", 1)[0].split("#", 1)[0])
    return (m.group(1) or m.group(2)) if m else None


def resolve_pinned(url: str, http_get_fn: Callable[..., Any] = http_get) -> AksResolution:
    """Resolve the OPERATOR-provided AKS page directly (no slug guessing).

    Raises on anything that is not a clean, parseable 200 — fail-closed, so a
    typo'd / dead / throttled URL is reported and skipped, never guessed around.
    A TRANSIENT probe failure (5xx/429 server blip or timeout/connection error) is
    RETRIED with a bounded backoff (``RESOLVE_ATTEMPTS``) before failing closed — an
    AKS 503 wrongly failed an aperçu that resolved fine seconds later. A 404/410 is a
    REAL absence and is never retried; a 200 short-circuits.
    """
    slug = extract_slug(url)
    if not slug:
        raise AksProbeUnreliable(f"not an AKS product URL: {url!r}")
    probe = None
    for attempt in range(1, RESOLVE_ATTEMPTS + 1):
        probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
        if probe.ok and probe.status == 200 and probe.body:
            break                                    # got the page
        if probe.status in (404, 410):
            break                                    # real absence — never retry
        transient = probe.status is None or probe.status in _TRANSIENT_RESOLVE_STATUSES
        if not transient or attempt == RESOLVE_ATTEMPTS:
            break                                    # persistent / exhausted → fail closed
        if http_get_fn is http_get:
            time.sleep(RESOLVE_RETRY_WAIT_S)         # backoff (no sleep under test stubs)
    if not (probe.ok and probe.status == 200 and probe.body):
        raise AksProbeUnreliable(f"{url} -> {probe.status or probe.error}")
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
         "list": list_no, "search[search]": term, "search[field]": field}
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
    if session.feed_page_state().get("feed_ui"):
        return []              # table rendered with 0 matches — a real empty result
    for wait in render_waits:  # not rendered yet → render race, poll before concluding
        time.sleep(wait)
        if session.is_login_page():
            raise NotLoggedInError("feed bounced to wp-login — not logged in")
        rows = session.page_offer_rows()
        if rows:
            return rows
        if session.feed_page_state().get("feed_ui"):
            return []          # rendered, genuinely 0 matches
    raise SearchUnreadable(f"search page never rendered: {url}")


def _read_search_pages(session: Any, feed_page: str, available: str, term: str,
                       field: str) -> tuple[list[dict], bool]:
    """Read a search's result pages (all-merchants) up to SEARCH_MAX_PAGES. A full
    page (100 rows) means there may be more → read the next; a short page ends it.
    Returns (rows, hit_cap) — hit_cap flags a result deeper than the cap (never a
    silent cut).

    P2-13 (audit 2026-09-02, DEFERRED — NOT wired): EXECUTOR_RULES §3 prefers bounding
    by the authoritative `.tablenav` nav_max over a short-page heuristic, and
    `feed_page_state()` already returns nav_max. It is deliberately NOT wired in here
    yet: on this SEARCH page (page=aks-merchant-feeds-search) it is UNCONFIRMED whether
    nav_max reports the FILTERED result's page count or the whole feed's. If it reports
    the whole feed, a `truncated = nav_max > SEARCH_MAX_PAGES` OR would fire on EVERY
    search → the manager's preview_incomplete gate would block every /games-tab submit
    (a hard over-block regression). The additive nav_max→truncated wiring must be gated
    on a one-time LIVE confirmation of the search page's nav semantics first — run the
    read-only probe `scripts/probe_p2_13_search_navmax.py` on the VPS (verdict FILTERED
    → safe to wire; WHOLE-FEED → keep this heuristic). Until then the fail-safe
    short-page heuristic stands (under-read = under-entry on a re-run, never a wrong
    entry)."""
    rows: list[dict] = []
    for page in range(1, SEARCH_MAX_PAGES + 1):
        found = _read_one_page(session, _search_url(feed_page, available, term, field, page))
        rows.extend(found)
        if len(found) < SEARCH_MAX_ROWS_LOGGED:
            return rows, False
    return rows, True


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
    the page cap (never silently cut)."""
    name_term = cleaned_title(resolution.aks_name) or resolution.aks_name
    url_term = resolution.slug
    meta: dict[str, Any] = {"name_term": name_term, "url_term": url_term, "truncated": False}
    rows: list[dict] = []
    for term, field in ((name_term, "name"), (url_term, "url")):
        if not term:
            continue
        found, hit_cap = _read_search_pages(session, feed_page, available, term, field)
        meta["truncated"] = meta["truncated"] or hit_cap
        rows.extend(found)
    return _dedupe_rows(rows), meta


def plan_from_rows(rows: list[dict], resolution: AksResolution, merchant: str,
                   store_id: str) -> dict:
    """Build candidates for ONE merchant from its already-fetched search rows, via
    match_offer pinned to the operator's AKS page (its R01 name check rejects a
    search over-match)."""
    pinned = lambda _name, _res=resolution: _res  # noqa: E731 — inject the pinned page
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
            result = match_offer_pinned(offer, pinned)
        except Exception as exc:  # a resolver/probe error on THIS offer → skip, keep going
            skipped.append({"name": offer.name, "url": offer.url, "reason": f"error: {exc}"})
            continue
        if isinstance(result, Candidate):
            candidates.append(result.to_dict())
        else:  # SkippedOffer
            skipped.append({"name": offer.name, "url": offer.url, "reason": result.reason})
    return {"merchant": merchant, "store_id": str(store_id), "found": len(rows),
            "candidates": candidates, "skipped": skipped}


def match_offer_pinned(offer: NormalizedOffer, pinned_resolver: Callable[[str], AksResolution]):
    """``match_offer`` with the AKS page PINNED to the operator-provided one — its
    R01 name check still rejects an offer the search over-matched (import here to
    keep the module import-light for unit tests of the pure helpers)."""
    from src.matcher import match_offer
    return match_offer(offer, resolver=pinned_resolver)


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
             logger: Any = None) -> dict:
    recap: dict[str, Any] = {"mode": "dry-run", "available": available,
                             "merchants": [m for m, _ in targets], "games": [],
                             "aborted": None,
                             "totals": {"games": len(urls), "resolved": 0, "candidates": 0}}
    emit = logger.log if logger is not None else (lambda *a, **k: None)

    def _flush() -> None:
        (run_dir / "recap.json").write_text(
            json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")

    emit("run_start", urls=len(urls), merchants=len(targets))
    # Resolve every URL first (read-only http_get, no browser) so a bad URL is
    # reported without holding the browser lock.
    resolved: list[tuple[str, AksResolution]] = []
    for url in urls:
        try:
            resolution = resolve_pinned(url, http_get_fn)
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
        _plan_games(session, resolved, targets, recap, available, feed_page, _flush, emit)
    else:
        with browser_lock(ROOT,
                          label="11_data_entry_by_urls (read-only) " + " ".join(urls)[:120]):
            with SubmitSession(endpoint) as live:
                _plan_games(live, resolved, targets, recap, available, feed_page, _flush, emit)
    if recap.get("aborted"):
        emit("run_aborted", reason=recap["aborted"])
    else:
        emit("run_done", resolved=recap["totals"]["resolved"],
             candidates=recap["totals"]["candidates"])
    _flush()
    return recap


def _plan_games(session: Any, resolved: list[tuple[str, AksResolution]], targets, recap: dict,
                available: str, feed_page: str, flush: Callable[[], None],
                emit: Callable[..., Any] = lambda *a, **k: None) -> None:
    # store_id -> merchant name, the vetted allowlist we keep from the results.
    store_to_merchant = {str(store): merchant for merchant, store in targets}
    for url, resolution in resolved:
        game: dict[str, Any] = {
            "url": url, "resolved": True,
            "aks_product_id": resolution.product_id,
            "aks_name": resolution.aks_name,
            "aks_url": resolution.url,
            "merchants": [], "total_candidates": 0}
        emit("game_start", aks_name=resolution.aks_name, aks_product_id=resolution.product_id)
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
            per = plan_from_rows(mrows, resolution, merchant, str(store_id))
            game["merchants"].append(per)
            game["total_candidates"] += len(per["candidates"])
            for c in per["candidates"]:
                o, reg, ed = c.get("offer", {}), c.get("region", {}), c.get("edition", {})
                emit("candidate", aks_name=resolution.aks_name, merchant=merchant,
                     name=o.get("name", ""), region=f"{reg.get('label')}({reg.get('id')})",
                     edition=f"{ed.get('label')}({ed.get('id')})")
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
        lines.append(f"🎯 {game['aks_product_id']} — {game['aks_name']}")
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
        if n == 0:
            lines.append("   (aucune offre à saisir trouvée)")
        lines.append("")
    lines.append(f"— {recap['totals']['candidates']} offre(s) à saisir sur "
                 f"{recap['totals']['resolved']}/{recap['totals']['games']} jeu(x) résolu(s).")
    (run_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
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
    args = ap.parse_args(argv)

    urls = _parse_urls(args)
    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if not urls:
        recap = {"mode": "dry-run", "aborted": "no_urls", "games": [],
                 "totals": {"games": 0, "resolved": 0, "candidates": 0}}
        (run_dir / "recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        print(json.dumps({"run_id": args.run_id, "aborted": "no_urls"}))
        return 2

    logger = RunLogger(args.run_id, log_dir=ROOT / "logs")
    try:
        recap = run_plan(urls, _targets(args.targets), available=args.available,
                         feed_page=args.feed_page, endpoint=args.endpoint, run_dir=run_dir,
                         logger=logger)
    except BrowserBusyError as exc:
        print(json.dumps({"run_id": args.run_id, "aborted": f"browser_busy: {exc}"}))
        return 2
    write_report(recap, run_dir)
    print(json.dumps({"run_id": args.run_id, "mode": "dry-run",
                      "resolved": recap["totals"]["resolved"],
                      "games": recap["totals"]["games"],
                      "candidates": recap["totals"]["candidates"],
                      "aborted": recap.get("aborted")}))
    return 0 if not recap.get("aborted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
