#!/usr/bin/env python3
"""Read-only probe — what does the AKS feed SEARCH that proves a creation actually return?

Romain, 2026-09-26 : « go pour vérifier et corriger la recherche CJS ». Three CJS
creations ended « offer state UNKNOWN … search page 1 rows do not all match term … — stale/
foreign DOM re-served » (`Submitter._scan_search`). This probe runs the SUBMITTER's own
proof search — the same term (`submitter.search_term`), the same URL
(`Submitter._search_url`: store, list, available, field=url, stable sort) — and prints every
row it gets (id, name, url) plus the page state (href term, nav_max), for each merchant URL
given. It also answers the operator's manual check « is this UNKNOWN offer still in the
pending feed? »: a row with that offer id / URL on the result = still pending.

READ-ONLY: it navigates the search pages and reads the rows — no modal, no fill, no click,
no write of any kind. Modelled on `scripts/probe_p2_13_search_navmax.py`: it fail-closed
REFUSES unless the invariants are green AND authoritative on the OFFICIAL CDP endpoint
(EXECUTOR_RULES §1), runs under the browser lock, and a wp-login bounce is a fail-closed
STOP — NEVER a re-auth trigger (AGENTS.md: cookie transfer by Romain in the console).

    python3 scripts/probe_search_rows.py --store-id 30 \\
        --url 'https://www.cjs-cdkeys.com/products/Resonance-Steam-Key.html'
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.extractor import DEFAULT_FEED_PAGE, NotLoggedInError  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.submit_session import SubmitSession  # noqa: E402
from src.submitter import DryRunSubmitter, _href_search_term, search_term  # noqa: E402

RENDER_WAITS = (1.0, 2.0, 3.0)
MAX_PAGES = 3


def _read_page(session, url) -> tuple[list[dict], dict]:
    """Navigate one search page read-only; poll the render race before concluding 0 rows."""
    session.navigate(url)
    if session.is_login_page():
        raise NotLoggedInError("feed bounced to wp-login — not logged in")
    rows = session.page_offer_rows()
    state = session.feed_page_state()
    if not rows and not state.get("feed_ui"):
        for wait in RENDER_WAITS:
            time.sleep(wait)
            if session.is_login_page():
                raise NotLoggedInError("feed bounced to wp-login — not logged in")
            rows = session.page_offer_rows()
            state = session.feed_page_state()
            if rows or state.get("feed_ui"):
                break
    return rows, state


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    ap.add_argument("--store-id", required=True, help="merchant feed store id (CJS = 30)")
    ap.add_argument("--feed-page", default=DEFAULT_FEED_PAGE, help="feed list, e.g. aks-merchant-feeds-9")
    ap.add_argument("--available", default="all")
    ap.add_argument("--url", action="append", default=[], required=True,
                    help="merchant offer URL whose proof search to run (repeatable)")
    args = ap.parse_args(argv)
    out: dict = {"probe": "search_rows", "store_id": args.store_id,
                 "feed_page": args.feed_page, "available": args.available}

    report = build_report(endpoint=args.endpoint)
    if not (report.get("ok") and report.get("authoritative")):
        out.update(aborted="invariants_not_green", ok=report.get("ok"),
                   authoritative=report.get("authoritative"))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("\nSTOP (fail-closed): invariants not green/authoritative on the official CDP "
              "endpoint — refusing browser access (EXECUTOR_RULES §1).", file=sys.stderr)
        return 2

    try:
        with browser_lock(ROOT, label="probe_search_rows (read-only)"):
            with SubmitSession(args.endpoint) as live:
                builder = DryRunSubmitter(live)          # URL builder only — never run()
                results = []
                for url in args.url:
                    term = search_term(url)
                    pages = []
                    for page in range(1, MAX_PAGES + 1):
                        search_url = builder._search_url(args.store_id, args.feed_page,
                                                         args.available, term, "url", page=page)
                        rows, state = _read_page(live, search_url)
                        pages.append({
                            "page": page, "href_term": _href_search_term(str(state.get("href") or "")),
                            "nav_max": int(state.get("nav_max") or 0), "rows": [
                                {"id": r.get("id"), "name": r.get("name"), "url": r.get("url")}
                                for r in rows]})
                        if not rows or page >= int(state.get("nav_max") or 0):
                            break
                    results.append({"url": url, "term": term, "pages": pages})
                out["results"] = results
    except NotLoggedInError as exc:
        out.update(aborted="not_logged_in", detail=str(exc))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("\nSTOP (fail-closed): session not logged in — cookie transfer in the console, "
              "then re-run. This probe NEVER re-authenticates.", file=sys.stderr)
        return 3
    except BrowserBusyError as exc:
        out.update(aborted="browser_busy", detail=str(exc))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"\nSTOP: browser busy ({exc}) — re-run later.", file=sys.stderr)
        return 4
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
