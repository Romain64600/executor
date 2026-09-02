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
import re
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
# The deterministic feed-page markers, shared VERBATIM with the submitter's
# feed_page_state() probe (AR3 partial, audit 2026-07-17: the two copies had
# already been retyped once and could drift — the marker semantics MUST stay
# identical because the submitter's blank-page classification mirrors §3's).
FEED_MARKER_JS_FIELDS = (
    "feed_ui: !!document.querySelector('table.wp-list-table'),"
    "nav_max: (function(){var m=0;var links=document.querySelectorAll('.tablenav a');"
    "for(var i=0;i<links.length;i++){var h=links[i].getAttribute('href')||'';"
    "var mm=h.match(/[?&]p=(\\d+)/);if(mm){var n=parseInt(mm[1],10);if(n>m){m=n;}}}"
    "return m;})(),"
    "is_login: !!document.querySelector('#loginform') || /wp-login/.test(location.href)"
)

PAGE_STATE_JS = (
    "JSON.stringify({"
    "offers: Array.from(document.querySelectorAll('[data-offer]'))"
    ".map(function(e){return e.getAttribute('data-offer');}),"
    + FEED_MARKER_JS_FIELDS +
    # href lets the extractor verify the browser actually LANDED on the page it
    # navigated to — a wedged navigation (Page.navigate commits but re-serves the
    # PREVIOUS page's DOM) leaves location.href on the prior url (P1-5, audit
    # 2026-09-02). Mirrors the submitter's _FEED_STATE_JS SC6 guard.
    ",href: String(location.href)"
    "})"
)


def _page_param(url: str) -> int:
    """The ``&p=N`` pagination param of a feed URL (1 when absent) — the page the
    browser is actually on. Mirrors the submitter's ``_page_param``."""

    match = re.search(r"[?&]p=(\d+)", url or "")
    return int(match.group(1)) if match else 1

# Wait before the single re-fetch of a blank page (on top of navigate's settle).
EMPTY_RETRY_WAIT_S = 5.0

# Backoff for a page whose feed UI has not rendered yet (feed_ui:false, 0 rows):
# a fast sweep can read BEFORE the wp-list-table JS renders, exactly the render
# race the mover polls through (feed_ui_render_waits). Without it a transient
# blank aborted a multi-page sweep — G2A p2 "in-range page rendered 0 rows twice"
# (feed_ui:false), 2026-08-22. Re-read (no re-navigate) with growing waits until
# the table renders (then classify) or rows appear.
FEED_UI_RENDER_WAITS = (1.0, 2.0, 4.0, 8.0)


class NotLoggedInError(RuntimeError):
    """The feed bounced to wp-login — extraction must abort loudly, never
    return a silent empty feed (a 0-offer result is otherwise a legitimate
    state that downstream stages act on)."""


class EmptyPageAnomaly(RuntimeError):
    """An in-range page rendered 0 rows twice without a deterministic
    explanation (empty queue on page 1, or past-the-end after a shrink).
    Transient blank render or feed breakage — abort, do not under-extract."""


class WedgedNavigationError(EmptyPageAnomaly):
    """The browser's location.href does not match the page we navigated to — a
    wedged navigation re-serving the PREVIOUS page's DOM (SC6, P1-5 audit
    2026-09-02). Its rows would all dedupe into ``seen`` (new=0) and the sweep
    would falsely conclude full coverage while pages went silently unread.
    Subclasses EmptyPageAnomaly so existing fail-closed callers already catch it."""


class FeedUnstableError(RuntimeError):
    """Coverage could not be proven: the last allowed sweep still discovered
    new offer ids (feed churning faster than we can sweep), or the feed
    advertises more pages than the configured cap."""


def feed_url(
    store_id: str | int | None,
    *,
    page: int | None = None,
    feed_page: str = DEFAULT_FEED_PAGE,
    available: str = "all",
    admin_url: str = AKS_ADMIN_URL,
) -> str:
    """Build a merchant-feed URL. Pagination is ``&p=N`` (never ``paged=N``).

    ``store_id=None`` omits the ``store=`` filter entirely — that queries the
    list across ALL stores (the "list sorting" all-stores view, probed live
    2026-07-23: ``…&page=aks-merchant-feeds-9`` with no store param returns
    list 9 for every store). ``store=`` empty or ``store=0`` do NOT do this —
    they silently default to one arbitrary store — so None must drop the key.
    """

    store_clause = "" if store_id is None else f"&store={store_id}"
    query = f"?available={available}{store_clause}&page={feed_page}"
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


_ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#[xX][0-9a-fA-F]+);")


def unescape_attribute(value: str) -> str:
    """Decode HTML entities with browser attribute-value semantics.

    Only ``;``-terminated references decode (``&amp;`` → ``&``, ``&#039;`` →
    ``'``). Bare legacy names stay literal: in ``&currency=EUR`` a browser
    keeps ``&curren`` (next char is alphanumeric), while ``html.unescape``
    would mangle it to ``¤cy=EUR`` — seen live on Kinguin URLs 2026-07-08.
    """

    return _ENTITY_RE.sub(lambda m: html.unescape(m.group(0)), value)


def parse_offers_payload(payload: Any) -> list[dict]:
    """Parse a list of ``data-offer`` attribute strings into offer dicts.

    ``payload`` is a JSON array (or its string form) whose elements are the
    ``data-offer`` attribute strings. Each is HTML-entity-encoded, so we
    decode entities before ``json.loads`` (skill rule F05) — with attribute
    semantics (:func:`unescape_attribute`), so raw ``&`` in URL query strings
    survives. Elements that are already objects are passed through.
    """

    if payload in (None, ""):
        return []
    outer = json.loads(payload) if isinstance(payload, str) else payload
    offers: list[dict] = []
    for element in outer:
        if isinstance(element, str):
            offers.append(json.loads(unescape_attribute(element)))
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
        self.feed_ui_render_waits = FEED_UI_RENDER_WAITS
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

    def _reread_page_state(self) -> Any:
        """Re-READ the ALREADY-loaded page (no re-navigate, no guard attempt) — a
        render-race poll waiting for the wp-list-table JS to finish. Re-navigating
        would reset the render clock; the StepGuard bounds real FETCHES, not renders
        (mirrors the mover's list_options / bulk_form render-wait polls)."""

        payload = self.session.evaluate_readonly(PAGE_STATE_JS)
        return json.loads(payload) if isinstance(payload, str) else payload

    def _abort_if_login(self, state: Any, *, sweep: int, page: int) -> None:
        if isinstance(state, dict) and state.get("is_login"):
            self._log("aborted", reason="not logged in (wp-login)", sweep=sweep, page=page)
            raise NotLoggedInError("feed bounced to wp-login — not logged in")

    def _assert_landed(self, state: Any, *, sweep: int, page: int) -> None:
        """P1-5 (audit 2026-09-02): verify the browser actually LANDED on this page.
        A wedged Page.navigate commits but re-serves the PREVIOUS page's DOM; its
        offers would all dedupe into ``seen`` (new=0), so the sweep would read them as
        "already covered" and silently skip the real page N — a sub-covered snapshot
        reported as fully covered. The submitter already guards this (SC6); the
        extractor did not. Applied to BOTH sweep and slice reads. Fail-closed."""
        href = str(state.get("href") or "") if isinstance(state, dict) else ""
        served = _page_param(href)
        if served != page:
            self._log("aborted", reason="wedged navigation (href mismatch)",
                      sweep=sweep, page=page, served=served)
            raise WedgedNavigationError(
                f"sweep {sweep} page {page}: browser is on p={served} "
                f"(location.href {href!r}) after navigating to page {page} — wedged "
                "navigation re-serving a stale DOM; refusing to read it as fresh coverage"
            )

    def _settled_page_state(
        self, *, merchant: str, sweep: int, page: int, url: str
    ) -> dict:
        """Fetch a page's state; on a blank/unrendered read, POLL (re-read, no
        re-navigate) with a growing backoff before letting the caller classify. A
        login bounce aborts immediately — retrying it blind would be pointless.

        Two blank causes, both handled by the poll: a RENDER RACE (feed_ui not up
        yet — a fast sweep beat the wp-list-table JS; the exact race the mover polls
        through, G2A p2 2026-08-22) and a TRANSIENT BLANK (table rendered but a
        momentary 0 rows). Stop as soon as rows appear, OR the table has rendered
        (feed_ui true → the caller can deterministically classify empty/past-end).
        A page still unrendered after the whole backoff is genuinely unreadable →
        the caller fails closed. Fail-closed is unchanged: a blank that renders as
        a real 0-row table is still classified, never silently accepted mid-feed."""

        state = self._page_state(merchant=merchant, sweep=sweep, page=page, url=url)
        self._abort_if_login(state, sweep=sweep, page=page)
        if isinstance(state, dict) and state.get("offers"):
            return state

        # No rows on the first read. If the table has NOT rendered (feed_ui false),
        # it may be a RENDER RACE — a fast sweep beat the wp-list-table JS (the exact
        # G2A p2 blip, 2026-08-22). POLL by re-READING the loaded page (no re-navigate
        # → keep the render clock; no guard attempt → the guard caps real FETCHES, not
        # renders): return as soon as rows appear; stop once the table renders (then
        # fall through to the confirm to classify empty / past-the-end).
        rendered_by_poll = False
        if isinstance(state, dict) and not state.get("feed_ui"):
            for wait in self.feed_ui_render_waits:
                time.sleep(wait)
                state = self._reread_page_state()
                self._abort_if_login(state, sweep=sweep, page=page)
                if isinstance(state, dict) and state.get("offers"):
                    self._log("feed_ui_render_wait", sweep=sweep, page=page,
                              offers=len(parse_offers_payload(state.get("offers"))))
                    return state
                if isinstance(state, dict) and state.get("feed_ui"):
                    rendered_by_poll = True
                    break

        # Confirm a blank before the caller classifies it.
        time.sleep(self.empty_retry_wait_s)
        if rendered_by_poll:
            # The poll already rendered the table WARM — confirm by re-READING, never
            # a cold re-navigate: a reload resets the render clock and can bounce a
            # just-rendered page back to feed_ui:false → a spurious EmptyPageAnomaly
            # that re-opens the very multi-page-sweep abort this poll fixes
            # (adversarial review 2026-08-24). The sleep lets late rows settle in.
            state = self._reread_page_state()
        else:
            # feed_ui:true from the first read (the original transient-blank confirm)
            # OR a page that never rendered (a wedged page, not just slow): ONE fresh
            # re-fetch (guard attempt 2/2), then classify.
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
        store_id: str | int | None,
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
                self._assert_landed(state, sweep=sweep, page=page)
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
            feed_last_page=last_page,
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
        store_id: str | int | None,
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
            self._assert_landed(state, sweep=1, page=page)   # P1-5: wedge guard here too
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
            feed_last_page=feed_last_page,
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
