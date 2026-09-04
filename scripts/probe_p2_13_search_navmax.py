#!/usr/bin/env python3
"""P2-13 read-only probe — does the AKS *search* page's ``nav_max`` report the
FILTERED result's page count, or the WHOLE feed's?

This is the ONE live fact that gates the DEFERRED P2-13 fix. Today
``scripts/11_data_entry_by_urls._read_search_pages`` bounds the all-merchants search
by a short-page heuristic (a page with < 100 rows ends it, 3-page cap) and ignores
``nav_max``. EXECUTOR_RULES §3 prefers bounding by the authoritative ``.tablenav``
``nav_max``. But wiring ``truncated = nav_max > SEARCH_MAX_PAGES`` blindly is unsafe:

  • if ``nav_max`` on ``page=aks-merchant-feeds-search`` reports the FILTERED result's
    page count → the wiring is correct and safe;
  • if it reports the WHOLE feed's page count → the wiring would fire on EVERY search
    and the manager's incomplete-preview gate would block EVERY /games-tab submit
    (a hard over-block regression).

This probe answers that question, READ-ONLY. It navigates + reads the feed-page
state only — no modal, no fill, no submit, no write of any kind. It must run on the
authoritative VPS through the official CDP endpoint, under the browser lock, on a
logged-in WP session. A wp-login bounce is a fail-closed STOP — NEVER a re-auth
trigger (AGENTS.md): complete the cookie transfer in the console first, then re-run.

METHOD (the decisive comparison):
  1. Read the PLAIN feed page's ``nav_max`` — the whole list's page count (reference).
  2. Read the SEARCH page's ``nav_max`` + row count for terms with very different
     result sizes (a nonsense control that returns 0, plus the operator's terms).
  AKS reports ``nav_max = 0`` for a SINGLE result page (no pagination nav). So:
     • a narrow search (0 < rows < 100, i.e. one page) whose ``nav_max`` is 0  →
       the nav reflects the FILTERED result  → SAFE to wire nav_max→truncated.
     • a narrow search whose ``nav_max`` equals the plain-feed ``nav_max`` (or ≥ 2)  →
       the nav reflects the WHOLE feed  → KEEP the heuristic, do NOT wire.

Pass at least one term you expect to match a HANDFUL of offers on the run's list
(fewer than 100, so it fits one page) — that is the term that decides it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.extractor import DEFAULT_FEED_PAGE, NotLoggedInError, feed_url  # noqa: E402
from src.submit_session import SubmitSession  # noqa: E402


def _load_by_urls():
    """Load scripts/11 (numeric module name) to reuse the EXACT production
    ``_search_url`` builder and render-wait budget — no reconstruction / drift."""
    spec = importlib.util.spec_from_file_location(
        "m11_by_urls", str(ROOT / "scripts" / "11_data_entry_by_urls.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_page(session, url, render_waits) -> dict:
    """Navigate a feed/search URL read-only and return {rows, nav_max, feed_ui, href}.

    Polls the render race (feed_ui late) exactly like ``_read_one_page`` before
    concluding a 0-row read; a wp-login bounce raises NotLoggedInError (fail-closed)."""
    session.navigate(url)
    if session.is_login_page():
        raise NotLoggedInError("feed bounced to wp-login — not logged in")
    rows = session.page_offer_rows()
    state = session.feed_page_state()
    if not rows and not state.get("feed_ui"):
        for wait in render_waits:                 # not rendered yet → poll, don't conclude
            time.sleep(wait)
            if session.is_login_page():
                raise NotLoggedInError("feed bounced to wp-login — not logged in")
            rows = session.page_offer_rows()
            state = session.feed_page_state()
            if rows or state.get("feed_ui"):
                break
    return {
        "rows": len(rows),
        "nav_max": int(state.get("nav_max") or 0),
        "feed_ui": bool(state.get("feed_ui")),
        "href": str(state.get("href") or ""),
    }


def _verdict(feed_navmax: int, term_reads: list[dict]) -> tuple[str, str]:
    """Decide FILTERED vs WHOLE-FEED from the narrow-search rows/nav_max evidence."""
    # a "narrow" observation = one that fits a single page (0 < rows < 100), where a
    # FILTERED nav reports 0 (single result page) but a WHOLE-FEED nav reports many.
    narrow = [t for t in term_reads if 0 < t["rows"] < 100 and t["feed_ui"]]
    if not narrow:
        return ("INCONCLUSIVE",
                "No search returned a partial single page (0 < rows < 100). Re-run with "
                "a --term you expect to match a HANDFUL of offers on this list.")
    whole_feed = [t for t in narrow if t["nav_max"] >= 2 or t["nav_max"] == feed_navmax]
    filtered = [t for t in narrow if t["nav_max"] <= 1 and t["nav_max"] != feed_navmax]
    if whole_feed and not filtered:
        return ("WHOLE-FEED",
                "A narrow search (one page of results) still reports the whole feed's "
                "nav_max → nav_max does NOT reflect the filtered result. KEEP the "
                "short-page heuristic; do NOT wire truncated = nav_max > SEARCH_MAX_PAGES "
                "(it would over-block every /games-tab submit).")
    if filtered and not whole_feed:
        return ("FILTERED",
                "A narrow search (one page of results) reports nav_max ≈ 0 (< the whole "
                "feed's) → nav_max reflects the FILTERED result. It is SAFE to wire "
                "truncated = nav_max > SEARCH_MAX_PAGES in _read_search_pages (bound by "
                "the authoritative nav, EXECUTOR_RULES §3).")
    return ("MIXED",
            "Narrow searches disagree — inspect the per-term table by hand before wiring.")


def main(argv: list[str] | None = None) -> int:
    m11 = _load_by_urls()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    ap.add_argument("--feed-page", default=DEFAULT_FEED_PAGE, help="feed list, e.g. aks-merchant-feeds-9")
    ap.add_argument("--available", default="all")
    ap.add_argument("--field", default="name", choices=["name", "url", "productId"])
    ap.add_argument("--term", action="append", default=[],
                    help="search term to probe (repeatable). Pass at least one you expect "
                         "to match a HANDFUL of offers (< 100) — that term decides it.")
    args = ap.parse_args(argv)

    # A nonsense control (expected 0 rows → nav_max 0) always runs; then the operator's
    # terms. No default 'broad' term — result sizes are list-specific, so the operator
    # supplies the meaningful narrow term(s).
    control = "zzq-nonexistent-product-" + "x" * 12
    terms = [control] + list(args.term)

    out: dict = {"probe": "p2_13_search_navmax", "feed_page": args.feed_page,
                 "available": args.available, "field": args.field}
    try:
        with browser_lock(ROOT, label="probe_p2_13_search_navmax (read-only)"):
            with SubmitSession(args.endpoint) as live:
                waits = m11.FEED_UI_RENDER_WAITS
                plain = _read_page(live, feed_url(None, feed_page=args.feed_page,
                                                  available=args.available), waits)
                out["plain_feed"] = plain
                term_reads = []
                for term in terms:
                    url = m11._search_url(args.feed_page, args.available, term, args.field, 1)
                    r = _read_page(live, url, waits)
                    r["term"] = term
                    term_reads.append(r)
                out["searches"] = term_reads
    except NotLoggedInError as exc:
        out["aborted"] = "not_logged_in"
        out["detail"] = str(exc)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("\nSTOP (fail-closed): session not logged in — do the cookie transfer in the "
              "console, then re-run. This probe NEVER re-authenticates.", file=sys.stderr)
        return 3
    except BrowserBusyError as exc:
        out["aborted"] = "browser_busy"
        out["detail"] = str(exc)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"\nSTOP: browser busy ({exc}) — a submit/sort/extract holds the lock. Re-run later.",
              file=sys.stderr)
        return 4

    verdict, why = _verdict(out["plain_feed"]["nav_max"], out["searches"])
    out["verdict"] = verdict
    out["verdict_reason"] = why
    print(json.dumps(out, ensure_ascii=False, indent=2))

    print("\n" + "=" * 72, file=sys.stderr)
    print(f"plain feed '{args.feed_page}': nav_max={out['plain_feed']['nav_max']} "
          f"rows(p1)={out['plain_feed']['rows']}", file=sys.stderr)
    for r in out["searches"]:
        tag = "control" if r["term"] == control else "term"
        print(f"  [{tag}] rows={r['rows']:>3} nav_max={r['nav_max']:>3} feed_ui={r['feed_ui']}"
              f"  ← {r['term']!r}", file=sys.stderr)
    print(f"\nVERDICT: {verdict}\n{why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
