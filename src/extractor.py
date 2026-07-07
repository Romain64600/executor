"""Read-only merchant-feed extractor (Sprint 2).

Navigates the WordPress admin merchant feed via a read-only CDP session, extracts
the ``data-offer`` rows page by page (``&p=N``), dedupes by offer id, and produces
a :class:`~src.contracts.RawSnapshot` + :class:`~src.contracts.NormalizedFeed`.

It NEVER opens the submit modal, submits, edits, or logs in. Every page fetch runs
through the :class:`~src.step_guard.StepGuard`; events and the guard snapshot are
written to the JSONL run log. Fail-closed: if a page fetch errors, the guard
records the failure and the exception propagates — no partial silent success.

The extractor depends only on a ``session`` object exposing ``navigate(url)`` and
``evaluate_readonly(expr)``, so it is fully unit-testable with a fake session.
"""

from __future__ import annotations

import html
import json
from typing import Any

from src.contracts import NormalizedFeed, RawSnapshot
from src.run_log import RunLogger
from src.step_guard import StepGuard

AKS_ADMIN_URL = "https://www.allkeyshop.com/blog/wp-admin/admin.php"
DEFAULT_FEED_PAGE = "aks-merchant-feeds-9"

# Returns a JSON array of the raw data-offer attribute strings currently on the page.
EXTRACT_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll('[data-offer]'))"
    ".map(function(e){return e.getAttribute('data-offer');}))"
)

_IS_LOGIN_JS = "!!document.querySelector('#loginform') || /wp-login/.test(location.href)"


class NotLoggedInError(RuntimeError):
    """The feed bounced to wp-login — extraction must abort loudly, never
    return a silent empty feed (a 0-offer result is otherwise a legitimate
    state that downstream stages act on)."""


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


def parse_offers_payload(payload: Any) -> list[dict]:
    """Parse the ``EXTRACT_JS`` return value into a list of offer dicts.

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
    """Paginate a merchant feed read-only and normalize it, through the guard."""

    def __init__(
        self,
        session: Any,
        *,
        guard: StepGuard | None = None,
        logger: RunLogger | None = None,
    ) -> None:
        self.session = session
        self.guard = guard or StepGuard(max_attempts_per_signature=2)
        self.logger = logger

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, **fields)

    def extract(
        self,
        *,
        run_id: str,
        merchant: str,
        store_id: str | int,
        feed_page: str = DEFAULT_FEED_PAGE,
        available: str = "all",
        max_pages: int = 40,
    ) -> tuple[RawSnapshot, NormalizedFeed]:
        self.guard.start_task(run_id)
        seen: set[str] = set()
        raw_offers: list[dict] = []
        empty_streak = 0
        pages_scanned = 0
        source_url = feed_url(store_id, feed_page=feed_page, available=available)

        for page in range(1, max_pages + 1):
            url = feed_url(store_id, page=page, feed_page=feed_page, available=available)

            def _fetch(target: str = url) -> list[dict]:
                self.session.navigate(target)
                return parse_offers_payload(self.session.evaluate_readonly(EXTRACT_JS))

            page_offers = self.guard.run_step(
                "extract",
                f"feed:{merchant}:p{page}",
                action=_fetch,
                success_predicate=lambda offers: isinstance(offers, list),
            )
            pages_scanned = page

            # Fail-closed: an empty first page is ambiguous — either the queue is
            # genuinely empty (legitimate) or we were bounced to wp-login. Probe
            # the already-loaded page (no extra navigation) and abort loudly on
            # the latter instead of returning a silent empty feed.
            if page == 1 and not page_offers and bool(
                self.session.evaluate_readonly(_IS_LOGIN_JS)
            ):
                self._log("aborted", reason="not logged in (wp-login)")
                raise NotLoggedInError("feed bounced to wp-login — not logged in")

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
                merchant=merchant,
                page=page,
                offers_on_page=len(page_offers),
                new_offers=new,
            )

            if not page_offers:
                break
            if new == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0

        snapshot = RawSnapshot.create(
            run_id=run_id,
            merchant=merchant,
            store_id=store_id,
            source_url=source_url,
            raw_offers=raw_offers,
            pages_scanned=pages_scanned,
        )
        feed = NormalizedFeed.from_snapshot(snapshot)
        self._log(
            "feed_extracted",
            merchant=merchant,
            pages_scanned=pages_scanned,
            raw_count=len(raw_offers),
            normalized_count=len(feed.offers),
        )
        if self.logger is not None:
            self.logger.log_guard(self.guard.snapshot())
        return snapshot, feed
