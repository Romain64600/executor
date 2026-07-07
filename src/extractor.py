"""Read-only merchant-feed extractor (Sprint 2).

Navigates the WordPress admin merchant feed via a read-only CDP session and
unions the ``data-offer`` rows over repeated full sweeps, because some feeds
(G2A, 2026-07-07: 762 rows seen / 482 distinct in one pass) re-order between
page fetches — a single pass provably misses offers. A sweep walks pages
``1..last_page`` where ``last_page`` comes from the feed's own pagination nav
(deterministic, rendered on every page); sweeps repeat until a full sweep adds
zero new offer ids, which is what proves coverage.

Each page fetch evaluates ONE page-state expression returning the offer rows
plus three deterministic markers:

- ``feed_ui``  — the ``table.wp-list-table`` rendered (page actually loaded);
- ``nav_max``  — highest ``&p=N`` in the pagination nav (real page count);
- ``is_login`` — bounced to wp-login.

A blank in-range page is ambiguous (transient blank render vs genuinely empty
feed vs feed shrank mid-sweep) — seen live 2026-07-07 when page 1 rendered 0
rows once and a clean "empty feed" was wrongly accepted. Policy: wait, re-fetch
once, then classify; anything not provably "empty queue" or "past the end"
raises :class:`EmptyPageAnomaly`. Fail-closed, never a silent empty feed.

It NEVER opens the submit modal, submits, edits, or logs in. Every page fetch
runs through the :class:`~src.step_guard.StepGuard` with sweep-scoped
signatures (``feed:<merchant>:s<sweep>:p<page>``, so the blank retry is attempt
2/2 and a third same-page fetch in the same sweep is refused).

The extractor depends only on a ``session`` object exposing ``navigate(url)``
and ``evaluate_readonly(expr)``, so it is fully unit-testable with a fake
session.

Chantier n°2 (2026-07-07): :meth:`FeedExtractor.extract_pages` is the
page-par-page mode — it fetches ONE explicit page range once, so an iteration
works a slice of the feed instead of sweeping all of it. A slice never proves
coverage and is always reported ``partial``. An optional
:class:`~src.pacing.Pacer` inserts a bounded-random delay between page fetches
(both modes) so large feeds are not walked in a burst.
"""

from __future__ import annotations

import html
import json
import time
from typing import Any

from src.contracts import NormalizedFeed, RawSnapshot
from src.pacing import Pacer
from src.run_log import RunLogger
from src.step_guard import StepGuard

AKS_ADMIN_URL = "https://www.allkeyshop.com/blog/wp-admin/admin.php"
DEFAULT_FEED_PAGE = "aks-merchant-feeds-9"

# One evaluate per page: raw data-offer attribute strings + deterministic
# page-state markers (probed live on G2A 2026-07-07: past-the-end pages render
# the same chrome with 0 rows, and the pagination nav is the only element that
# exposes the feed's real page count — there is no WP ".no-items" marker here).
PAGE_STATE_JS = (
    "JSON.stringify({"
    "offers: Array.from(document.querySelectorAll('[data-offer]'))"
    ".map(function(e){return e.getAttribute('data-offer');}),"
    "feed_ui: !!document.querySelector('table.wp-list-table'),"
    "nav_max: (function(){var m=0;var links=document.querySelectorAll('.tablenav a');"
    "for(var i=0;i<links.length;i++){var h=links[i].getAttribute('href')||'';"
    "var mm=h.match(/[?&]p=(\\d+)/);if(mm){var n=parseInt(mm[1],10);if(n>m){m=n;}}}"
    "return m;})(),"
    "is_login: !!document.querySelector('#loginform') || /wp-login/.test(location.href)"
    "})"
)

# Wait before the single re-fetch of a blank page (on top of navigate's settle).
EMPTY_RETRY_WAIT_S = 5.0


class NotLoggedInError(RuntimeError):
    """The feed bounced to wp-login — extraction must abort loudly, never
    return a silent empty feed (a 0-offer result is otherwise a legitimate
    state that downstream stages act on)."""


class EmptyPageAnomaly(RuntimeError):
    """An in-range page rendered 0 rows twice without a deterministic
    explanation (empty queue on page 1, or past-the-end after a shrink).
    Transient blank render or feed breakage — abort, do not under-extract."""


class FeedUnstableError(RuntimeError):
    """Coverage could not be proven: the last allowed sweep still discovered
    new offer ids (feed churning faster than we can sweep), or the feed
    advertises more pages than the configured cap."""


def feed_url(
    store_id: str | int,
    *,
    page: int | None = None,
    feed_page: str = DEFAULT_FEED_PAGE,
    available: str = "all",
    admin_url: str = AKS_ADMIN_URL,
) -> str:
    """Build a merchant-feed URL. Pagination is ``&p=N`` (never ``paged=N``)."""

    query = f"?available={available}&store={store_id}&page={feed_page}"
    if page is not None and int(page) > 1:
        query += f"&p={int(page)}"
    return admin_url + query


def parse_page_range(spec: str) -> tuple[int, int]:
    """Parse a CLI page-range spec: ``"3"`` → (3, 3), ``"3-5"`` → (3, 5)."""

    parts = str(spec).strip().split("-")
    try:
        if len(parts) == 1:
            first = last = int(parts[0])
        elif len(parts) == 2:
            first, last = int(parts[0]), int(parts[1])
        else:
            raise ValueError
    except ValueError:
        raise ValueError(f"invalid page range {spec!r} — want 'N' or 'FIRST-LAST'") from None
    if first < 1:
        raise ValueError(f"invalid page range {spec!r} — pages start at 1")
    if first > last:
        raise ValueError(f"invalid page range {spec!r} — first must be <= last")
    return first, last


def parse_offers_payload(payload: Any) -> list[dict]:
    """Parse a list of ``data-offer`` attribute strings into offer dicts.

    ``payload`` is a JSON array (or its string form) whose elements are the
    ``data-offer`` attribute strings. Each is HTML-entity-encoded, so we
    ``html.unescape`` before ``json.loads`` (skill rule F05). Elements that are
    already objects are passed through.
    """

    if payload in (None, ""):
        return []
    outer = json.loads(payload) if isinstance(payload, str) else payload
    offers: list[dict] = []
    for element in outer:
        if isinstance(element, str):
            offers.append(json.loads(html.unescape(element)))
        elif isinstance(element, dict):
            offers.append(element)
    return offers


class FeedExtractor:
    """Sweep a merchant feed read-only until stable and normalize it."""

    def __init__(
        self,
        session: Any,
        *,
        guard: StepGuard | None = None,
        logger: RunLogger | None = None,
        pacer: Pacer | None = None,
    ) -> None:
        self.session = session
        self.guard = guard or StepGuard(max_attempts_per_signature=2)
        self.logger = logger
        self.pacer = pacer
        self.empty_retry_wait_s = EMPTY_RETRY_WAIT_S
        self.last_stats: dict[str, Any] = {}
        self._fetched_once = False

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, **fields)

    def _pace(self) -> None:
        """Bounded-random wait between page fetches — never before the first."""

        if self.pacer is not None and self._fetched_once:
            self.pacer.wait()

    def _page_state(self, *, merchant: str, sweep: int, page: int, url: str) -> Any:
        def _fetch() -> Any:
            self._fetched_once = True
            self.session.navigate(url)
            payload = self.session.evaluate_readonly(PAGE_STATE_JS)
            return json.loads(payload) if isinstance(payload, str) else payload

        return self.guard.run_step(
            "extract",
            f"feed:{merchant}:s{sweep}:p{page}",
            action=_fetch,
            success_predicate=lambda s: isinstance(s, dict)
            and isinstance(s.get("offers"), list),
        )

    def _abort_if_login(self, state: Any, *, sweep: int, page: int) -> None:
        if isinstance(state, dict) and state.get("is_login"):
            self._log("aborted", reason="not logged in (wp-login)", sweep=sweep, page=page)
            raise NotLoggedInError("feed bounced to wp-login — not logged in")

    def _settled_page_state(
        self, *, merchant: str, sweep: int, page: int, url: str
    ) -> dict:
        """Fetch a page's state; on a blank/unreadable render, wait and re-fetch
        ONCE (guard attempt 2/2), then let the caller classify. A login bounce
        aborts immediately — retrying it blind would be pointless."""

        state = self._page_state(merchant=merchant, sweep=sweep, page=page, url=url)
        self._abort_if_login(state, sweep=sweep, page=page)
        if isinstance(state, dict) and state.get("offers"):
            return state

        time.sleep(self.empty_retry_wait_s)
        state = self._page_state(merchant=merchant, sweep=sweep, page=page, url=url)
        self._abort_if_login(state, sweep=sweep, page=page)
        if not isinstance(state, dict):
            self._log("aborted", reason="page state unreadable after retry", sweep=sweep, page=page)
            raise EmptyPageAnomaly(
                f"sweep {sweep} page {page}: page state unreadable after retry"
            )
        return state

    def extract(
        self,
        *,
        run_id: str,
        merchant: str,
        store_id: str | int,
        feed_page: str = DEFAULT_FEED_PAGE,
        available: str = "all",
        max_pages: int = 40,
        max_sweeps: int = 5,
    ) -> tuple[RawSnapshot, NormalizedFeed]:
        if max_sweeps < 2:
            raise ValueError("max_sweeps must be >= 2 — the extra sweep is what proves coverage")

        self.guard.start_task(run_id)
        seen: set[str] = set()
        raw_offers: list[dict] = []
        rows_seen = 0
        last_page = 1
        max_page_reached = 1
        sweeps_done = 0
        stable = False
        source_url = feed_url(store_id, feed_page=feed_page, available=available)

        for sweep in range(1, max_sweeps + 1):
            sweeps_done = sweep
            new_in_sweep = 0
            page = 1
            while page <= last_page:
                if last_page > max_pages:
                    self._log(
                        "aborted",
                        reason=f"feed advertises {last_page} pages > max_pages {max_pages}",
                    )
                    raise FeedUnstableError(
                        f"feed advertises {last_page} pages, above the max_pages cap "
                        f"({max_pages}) — refusing to silently truncate coverage; "
                        "re-run with a higher --max-pages"
                    )

                url = feed_url(store_id, page=page, feed_page=feed_page, available=available)
                self._pace()
                state = self._settled_page_state(
                    merchant=merchant, sweep=sweep, page=page, url=url
                )
                page_offers = parse_offers_payload(state.get("offers"))
                nav_max = int(state.get("nav_max") or 0)
                feed_ui = bool(state.get("feed_ui"))

                if not page_offers:
                    if page == 1 and feed_ui and nav_max == 0:
                        # Feed UI rendered, no rows, no pagination: the queue is
                        # genuinely empty (confirmed by the re-fetch above).
                        self._log(
                            "feed_page",
                            merchant=merchant, sweep=sweep, page=page,
                            offers_on_page=0, new_offers=0, nav_max=0,
                            empty_feed=True,
                        )
                        break
                    if page > 1 and feed_ui and nav_max < page:
                        # The feed shrank mid-sweep; this page is now past the
                        # end (its nav advertises fewer pages than requested).
                        last_page = max(1, nav_max)
                        self._log(
                            "feed_page",
                            merchant=merchant, sweep=sweep, page=page,
                            offers_on_page=0, new_offers=0, nav_max=nav_max,
                            past_end=True,
                        )
                        break
                    self._log(
                        "aborted",
                        reason="in-range page rendered 0 rows twice",
                        sweep=sweep, page=page, feed_ui=feed_ui, nav_max=nav_max,
                    )
                    raise EmptyPageAnomaly(
                        f"sweep {sweep} page {page}: 0 rows twice while "
                        + (
                            f"the feed UI is rendered and its nav advertises {nav_max} page(s)"
                            if feed_ui
                            else "the feed UI did not render"
                        )
                        + " — transient blank render or feed breakage; refusing to "
                        "treat this as an empty feed"
                    )

                last_page = max(last_page, nav_max, page)
                max_page_reached = max(max_page_reached, page)
                rows_seen += len(page_offers)
                new = 0
                for offer in page_offers:
                    offer_id = str(offer.get("id", "")).strip()
                    if not offer_id or offer_id in seen:
                        continue
                    seen.add(offer_id)
                    raw_offers.append(offer)
                    new += 1
                new_in_sweep += new

                self._log(
                    "feed_page",
                    merchant=merchant, sweep=sweep, page=page,
                    offers_on_page=len(page_offers), new_offers=new, nav_max=nav_max,
                )
                page += 1

            self._log(
                "feed_sweep",
                merchant=merchant, sweep=sweep, new_offers=new_in_sweep,
                distinct=len(seen), rows_seen=rows_seen, last_page=last_page,
            )
            if new_in_sweep == 0:
                stable = True
                break

        if not stable:
            self._log(
                "aborted",
                reason=f"{max_sweeps} sweeps exhausted, feed ordering unstable",
                distinct=len(seen), rows_seen=rows_seen,
            )
            raise FeedUnstableError(
                f"after {max_sweeps} full sweeps the last sweep still discovered new "
                f"offers ({len(seen)} distinct so far) — feed ordering too unstable "
                "to prove coverage; re-run (possibly with --max-sweeps raised)"
            )

        self.last_stats = {
            "mode": "sweeps",
            "partial": False,
            "sweeps": sweeps_done,
            "last_page": last_page,
            "pages_scanned": max_page_reached,
            "rows_seen": rows_seen,
            "distinct_offers": len(seen),
        }
        snapshot = RawSnapshot.create(
            run_id=run_id,
            merchant=merchant,
            store_id=store_id,
            source_url=source_url,
            raw_offers=raw_offers,
            pages_scanned=max_page_reached,
        )
        feed = NormalizedFeed.from_snapshot(snapshot)
        self._log(
            "feed_extracted",
            merchant=merchant,
            sweeps=sweeps_done,
            pages_scanned=max_page_reached,
            rows_seen=rows_seen,
            raw_count=len(raw_offers),
            normalized_count=len(feed.offers),
        )
        if self.logger is not None:
            if self.pacer is not None:
                self.logger.log("pacing", **self.pacer.snapshot())
            self.logger.log_guard(self.guard.snapshot())
        return snapshot, feed

    def extract_pages(
        self,
        *,
        run_id: str,
        merchant: str,
        store_id: str | int,
        first_page: int,
        last_page: int,
        feed_page: str = DEFAULT_FEED_PAGE,
        available: str = "all",
    ) -> tuple[RawSnapshot, NormalizedFeed]:
        """Page-par-page mode: fetch ONE explicit page range, once, read-only.

        A slice NEVER proves coverage — the result is always ``partial`` and
        downstream must treat it as "these offers were on pages first..last at
        fetch time", nothing more. Fail-closed classification is identical to
        sweep mode (login bounce and unexplained blank pages abort); the two
        legitimate early stops are an empty queue (page 1) and a slice that
        extends past the feed's current end (``past_end``).
        """

        if first_page < 1:
            raise ValueError("first_page must be >= 1")
        if first_page > last_page:
            raise ValueError("first_page must be <= last_page")

        self.guard.start_task(run_id)
        seen: set[str] = set()
        raw_offers: list[dict] = []
        rows_seen = 0
        pages_fetched = 0
        feed_last_page = 0
        source_url = feed_url(
            store_id, page=first_page, feed_page=feed_page, available=available
        )

        for page in range(first_page, last_page + 1):
            url = feed_url(store_id, page=page, feed_page=feed_page, available=available)
            self._pace()
            state = self._settled_page_state(merchant=merchant, sweep=1, page=page, url=url)
            pages_fetched += 1
            page_offers = parse_offers_payload(state.get("offers"))
            nav_max = int(state.get("nav_max") or 0)
            feed_ui = bool(state.get("feed_ui"))
            feed_last_page = max(feed_last_page, nav_max, 1 if feed_ui else 0)

            if not page_offers:
                if page == 1 and feed_ui and nav_max == 0:
                    self._log(
                        "feed_page",
                        merchant=merchant, mode="pages", page=page,
                        offers_on_page=0, new_offers=0, nav_max=0, empty_feed=True,
                    )
                    break
                if feed_ui and nav_max < page:
                    # The slice extends past the feed's current end — a
                    # legitimate stop in slice mode, not an anomaly.
                    self._log(
                        "feed_page",
                        merchant=merchant, mode="pages", page=page,
                        offers_on_page=0, new_offers=0, nav_max=nav_max, past_end=True,
                    )
                    break
                self._log(
                    "aborted",
                    reason="in-range page rendered 0 rows twice",
                    mode="pages", page=page, feed_ui=feed_ui, nav_max=nav_max,
                )
                raise EmptyPageAnomaly(
                    f"page {page}: 0 rows twice while "
                    + (
                        f"the feed UI is rendered and its nav advertises {nav_max} page(s)"
                        if feed_ui
                        else "the feed UI did not render"
                    )
                    + " — transient blank render or feed breakage; refusing to "
                    "treat this as an empty feed"
                )

            rows_seen += len(page_offers)
            new = 0
            for offer in page_offers:
                offer_id = str(offer.get("id", "")).strip()
                if not offer_id or offer_id in seen:
                    continue
                seen.add(offer_id)
                raw_offers.append(offer)
                new += 1
            self._log(
                "feed_page",
                merchant=merchant, mode="pages", page=page,
                offers_on_page=len(page_offers), new_offers=new, nav_max=nav_max,
            )

        self.last_stats = {
            "mode": "pages",
            "partial": True,
            "pages_requested": [first_page, last_page],
            "pages_fetched": pages_fetched,
            "feed_last_page": feed_last_page,
            "rows_seen": rows_seen,
            "distinct_offers": len(seen),
        }
        snapshot = RawSnapshot.create(
            run_id=run_id,
            merchant=merchant,
            store_id=store_id,
            source_url=source_url,
            raw_offers=raw_offers,
            pages_scanned=pages_fetched,
        )
        feed = NormalizedFeed.from_snapshot(snapshot)
        self._log(
            "feed_extracted",
            merchant=merchant,
            mode="pages",
            partial=True,
            pages_requested=[first_page, last_page],
            pages_fetched=pages_fetched,
            feed_last_page=feed_last_page,
            rows_seen=rows_seen,
            raw_count=len(raw_offers),
            normalized_count=len(feed.offers),
        )
        if self.logger is not None:
            if self.pacer is not None:
                self.logger.log("pacing", **self.pacer.snapshot())
            self.logger.log_guard(self.guard.snapshot())
        return snapshot, feed
