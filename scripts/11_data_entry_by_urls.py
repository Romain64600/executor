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
# A single game should not have hundreds of pending offers per merchant; read the
# first search page and flag (never silently drop) if the filter advertises more.
SEARCH_MAX_ROWS_LOGGED = 100

_SLUG_RE = re.compile(r"/blog/buy-([a-z0-9-]+)-(?:cd-key|[a-z-]+-account)-compare-prices/?")


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
    return m.group(1) if m else None


def resolve_pinned(url: str, http_get_fn: Callable[..., Any] = http_get) -> AksResolution:
    """Resolve the OPERATOR-provided AKS page directly (no slug guessing).

    Raises on anything that is not a clean, parseable 200 — fail-closed, so a
    typo'd / dead / throttled URL is reported and skipped, never guessed around.
    """
    slug = extract_slug(url)
    if not slug:
        raise AksProbeUnreliable(f"not an AKS product URL: {url!r}")
    probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
    if not (probe.ok and probe.status == 200 and probe.body):
        raise AksProbeUnreliable(f"{url} -> {probe.status or probe.error}")
    resolution = _resolution_from_body(slug, url, probe.body)
    if resolution is None:
        raise AksNameUnreadable(f"{url} -> 200 but no product id / name")
    return resolution


def _search_url(store_id: str, feed_page: str, available: str, term: str, field: str) -> str:
    """The AKS feed tool's SEARCH form is a GET to ``page=aks-merchant-feeds-search``
    with ``list`` (the feed list number) + ``store`` as SEPARATE params — NOT the
    feed page with the search appended (which is silently ignored and returns the
    unfiltered feed, verified live 2026-08-24). ``search[field]`` = name|url|productId."""
    list_no = str(feed_page).rsplit("-", 1)[-1]     # "aks-merchant-feeds-9" -> "9"
    return AKS_ADMIN_URL + "?" + urllib.parse.urlencode({
        "page": "aks-merchant-feeds-search", "available": available,
        "list": list_no, "store": store_id,
        "search[search]": term, "search[field]": field})


def _read_search_rows(session: Any, url: str,
                      render_waits: tuple[float, ...] = FEED_UI_RENDER_WAITS) -> list[dict]:
    """Navigate a search-filtered feed URL and return its rows [{id,url,name}].

    Polls the render race (feed_ui late) before concluding "no results": rows →
    return; feed_ui rendered with 0 rows → a real empty result; login bounce →
    fail-closed. Reads the first page only (a game's per-merchant matches fit one
    page); a deeper filtered result is flagged by the caller, never silently cut.
    """
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
    # Never rendered through the whole backoff, and not a login bounce → the search
    # page is broken/errored. Fail-closed: raise so the caller records a per-merchant
    # error, never a silent "0 offers found" (adversarial review 2026-08-24).
    raise SearchUnreadable(f"search page never rendered: {url}")


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


def search_offers_for_game(session: Any, resolution: AksResolution, store_id: str,
                           available: str, feed_page: str) -> tuple[list[dict], dict]:
    """Search a merchant feed for a game by NAME and by URL(slug); union the rows.

    Returns (rows, meta). ``meta`` records the two terms and whether either search
    saw a full page (more results may exist — flagged, never silently dropped)."""
    name_term = cleaned_title(resolution.aks_name) or resolution.aks_name
    url_term = resolution.slug
    meta: dict[str, Any] = {"name_term": name_term, "url_term": url_term, "truncated": False}
    rows: list[dict] = []
    for term, field in ((name_term, "name"), (url_term, "url")):
        if not term:
            continue
        found = _read_search_rows(session, _search_url(store_id, feed_page, available, term, field))
        if len(found) >= SEARCH_MAX_ROWS_LOGGED:
            meta["truncated"] = True
        rows.extend(found)
    return _dedupe_rows(rows), meta


def plan_merchant(session: Any, resolution: AksResolution, merchant: str, store_id: str,
                  available: str, feed_page: str) -> dict:
    """Search one merchant for the game and build candidates via the pinned match."""
    try:
        rows, meta = search_offers_for_game(session, resolution, store_id, available, feed_page)
    except SearchUnreadable as exc:
        # non-fatal per-merchant: flag it (never a silent found=0), keep going.
        return {"merchant": merchant, "store_id": str(store_id), "found": 0,
                "candidates": [], "skipped": [], "error": "search_unreadable",
                "detail": str(exc)[:160]}
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
            "candidates": candidates, "skipped": skipped, "search": meta}


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
             http_get_fn: Callable[..., Any] = http_get, session: Any = None) -> dict:
    recap: dict[str, Any] = {"mode": "dry-run", "available": available,
                             "merchants": [m for m, _ in targets], "games": [],
                             "aborted": None,
                             "totals": {"games": len(urls), "resolved": 0, "candidates": 0}}

    def _flush() -> None:
        (run_dir / "recap.json").write_text(
            json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")

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
            _flush()
            continue
        resolved.append((url, resolution))
        recap["totals"]["resolved"] += 1

    if not resolved:
        _flush()
        return recap

    if session is not None:                       # injected (tests) — no real browser
        _plan_games(session, resolved, targets, recap, available, feed_page, _flush)
    else:
        with browser_lock(ROOT,
                          label="11_data_entry_by_urls (read-only) " + " ".join(urls)[:120]):
            with SubmitSession(endpoint) as live:
                _plan_games(live, resolved, targets, recap, available, feed_page, _flush)
    _flush()
    return recap


def _plan_games(session: Any, resolved: list[tuple[str, AksResolution]], targets, recap: dict,
                available: str, feed_page: str, flush: Callable[[], None]) -> None:
    for url, resolution in resolved:
        game: dict[str, Any] = {
            "url": url, "resolved": True,
            "aks_product_id": resolution.product_id,
            "aks_name": resolution.aks_name,
            "aks_url": resolution.url,
            "merchants": [], "total_candidates": 0}
        for merchant, store_id in targets:
            try:
                per = plan_merchant(session, resolution, merchant, store_id, available, feed_page)
            except NotLoggedInError:
                # Fail-closed STOP — NEVER a re-auth trigger (AGENTS.md).
                recap["aborted"] = "not_logged_in"
                game["merchants"].append({"merchant": merchant, "store_id": store_id,
                                          "error": "not_logged_in"})
                # Count what THIS game already planned before the bounce, so the
                # total agrees with the recap body/report (review 2026-08-24).
                recap["totals"]["candidates"] += game["total_candidates"]
                recap["games"].append(game)
                flush()
                return
            game["merchants"].append(per)
            game["total_candidates"] += len(per["candidates"])
        recap["totals"]["candidates"] += game["total_candidates"]
        recap["games"].append(game)
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
        n = 0
        for per in game.get("merchants", []):
            if per.get("error"):
                lines.append(f"   ⚠ {per['merchant']} : {per['error']}")
                continue
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

    try:
        recap = run_plan(urls, _targets(args.targets), available=args.available,
                         feed_page=args.feed_page, endpoint=args.endpoint, run_dir=run_dir)
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
