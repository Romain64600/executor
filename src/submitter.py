"""Stage 4 — submitters (dry-run and real).

Shared flow (`_SubmitterBase`): pre-flight login check, refresh + index the current
feed, locate each approved offer's exact row, open its modal, verify context +
select names.

- `DryRunSubmitter` stops there and reports what it *would* submit — **no writes**.
- `Submitter` (real) additionally fills region/edition and clicks "Create offer",
  then verifies post-save that the offer **disappeared** from the refreshed
  feed, in the same ``available`` mode the run scans — success = gone (skill
  S18; never `[data-success]`).

Fail-closed per Romain's decisions (SUBMITTER_SPEC §6): one attempt per offer; on
failure log + skip + continue; stop the run after 10 consecutive failures.

``run(limit=None)`` means the full approved batch. The batch size is NOT decided
here: it is the data-entry mode's call, applied by ``scripts/05_submit.py``
(R24 — `safe` = full validated batch, `learning`/`advanced` = canary of 1).
Depends only on a ``session`` object, so both are unit-testable with a fake.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

from src.cdp_session import CdpCommandError
from src.extractor import (
    AKS_ADMIN_URL,
    DEFAULT_FEED_PAGE,
    EMPTY_RETRY_WAIT_S,
    NotLoggedInError,
    feed_url,
)
from src.pacing import Pacer
from src.run_log import RunLogger
from src.step_guard import StepGuard


class FeedScanError(RuntimeError):
    """The feed walk could not prove complete, faithful coverage of the live
    feed: a blank in-range page that survived one re-fetch, a page whose
    browser URL does not match the one navigated to (wedged navigation
    re-serving the previous DOM), unreadable markers, or a feed advertising
    more pages than the walk covered (``max_pages`` hit). The batch index and
    the post-save 'gone' proof are both built on this walk — an unproven walk
    must abort loudly, never stand in for "the offer disappeared" (audit
    2026-07-17: FC1/SC2/SC4/FC6)."""


# Exceptions that mean "the feed/browser is unreadable — the run must stop
# fail-closed, the current offer's state is UNKNOWN, nothing may be inferred".
FEED_UNREADABLE_EXCS = (NotLoggedInError, FeedScanError, CdpCommandError)


class StopRequested(RuntimeError):
    """The operator asked to stop the run. Raised only at a SAFE point (a
    read-only page-scan boundary while the stop hook is armed) — never mid-write.
    A clean, expected stop, not a failure."""

# Post-navigate settle for FEED-SCAN reads only (index + post-save re-walk).
# These just read data-offer rows from the server-rendered HTML, so a short
# wait is enough (proven live: extraction reads the same rows fine at 1 s).
# The navigate BEFORE a modal open (row page in _prepare, catalog fetch) keeps
# the 3 s default, because the page's interactive JS (ThickBox) must be
# initialised before the create-offer click — 1 s there broke every modal
# ("modal context missing", 2026-07-20). Splitting the two is the correct
# speedup: the full-feed post-save re-scan after each creation is the bulk of a
# submit's time and needs no modal.
FEED_SCAN_SETTLE = 1.0
# Render-wait backoff (2026-08-18): under sustained CDP load (~30 min into a
# sweep) a feed page's HTML loads but its JS-built feed UI can lag the first read,
# so it reads feed_ui=False ("rendered without the feed UI"). Before concluding the
# page is blank we POLL the DOM (re-read, no re-navigate) with this backoff, letting
# a slow render finish. Tests patch to ().
FEED_UI_RENDER_WAITS = (1.0, 2.0, 4.0)

# by-urls search-locate page budget (2026-08-25 review): the feed SEARCH is filtered
# to ONE offer's slug, so it normally returns a single result page — but the slug is a
# SUBSTRING match, so a short/common slug in a big store can overflow. The scan walks
# every result page to a PROVEN end; if the results still advertise more than this many
# pages the coverage is unproven and the scan raises FeedScanError (never a false
# "gone"). ~1000 matching rows for one slug is already pathological.
SEARCH_SCAN_MAX_PAGES = 10


def _page_param(url: str) -> int:
    """The ``&p=N`` pagination param of a feed URL (1 when absent)."""

    match = re.search(r"[?&]p=(\d+)", url or "")
    return int(match.group(1)) if match else 1


def _url_key(url: str) -> str:
    """Merchant-URL identity key: the URL path, query params stripped.

    The path is the stable per-product identity across feed re-imports
    (G2A 2026-07-08 vs 07-07: path stable 716/716 common products, FULL url
    only 690/716 — the ``uuid=`` param drifts; K4G's hash lives in the path).
    Unique in-feed for both (G2A 741/741, K4G 250/250 distinct paths)."""

    return (url or "").split("?", 1)[0]


def _href_search_term(href: str) -> str | None:
    """The ``search[search]`` query param of a feed-search URL, or None. Used to
    confirm the browser is genuinely on THIS search before trusting an EMPTY result
    page as a real 0-result 'gone' — a wedged navigation re-serving a foreign/prior
    DOM leaves ``location.href`` on the PRIOR url (a different term, or none), which
    the page-number (&p=) SC6 check alone cannot catch when there are no rows."""

    try:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(href or "").query)
    except ValueError:
        return None
    values = params.get("search[search]")
    return values[0] if values else None


def _row_check(row: dict[str, str], candidate: dict[str, Any], *,
               check_price: bool) -> tuple[list[str], list[str]]:
    """(mismatches, checked): feed-row fields verified against the candidate.

    Audit P1 (Romain, 2026-07-08): the nominal by-id path accepted a row on id
    membership alone, verifying nothing — AGENTS.md requires "verify title,
    URL, price, page, merchant" before the modal. name and URL path are always
    compared; price and store only when BOTH sides carry a value. Price is a
    ROUTING signal, never a blocker (audit 3, 2026-07-08): on the by-id path
    (check_price=True) a mismatch distrusts the id — possibly reused by a
    re-import for a different row — and reroutes to the URL identity; it is
    not compared across a URL relocation (check_price=False) because live
    feeds reprice constantly between extract and submit and price is never
    part of what the modal enters. Once name + URL (+ store) confirm the row,
    price drift is deliberately non-blocking.
    """

    offer = candidate["offer"]
    mismatches: list[str] = []
    checked = ["name", "url"]
    if row.get("name", "") != offer["name"]:
        mismatches.append("name")
    if _url_key(row.get("url", "")) != _url_key(str(offer.get("url") or "")):
        mismatches.append("url")
    row_store, cand_store = row.get("store_id", ""), str(offer.get("store_id") or "")
    if row_store and cand_store:
        checked.append("store_id")
        if row_store != cand_store:
            mismatches.append("store_id")
    if check_price:
        row_price, cand_price = row.get("price", ""), str(offer.get("price") or "")
        if row_price and cand_price:
            checked.append("price")
            if row_price != cand_price:
                mismatches.append("price")
    return mismatches, checked


def _norm_option_text(text: str) -> str:
    """Normalize a catalog option label for comparison: drop the trailing
    ``(id)`` suffix regions carry (e.g. "Steam EU (9)"), lowercase, collapse
    whitespace. Editions carry no suffix so are unaffected."""

    text = re.sub(r"\s*\(\d+\)\s*$", "", (text or "").strip())
    return re.sub(r"\s+", " ", text).lower()


def resolve_catalog_id(
    label: str, candidate_id: str, master_options: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a region/edition to its LIVE catalog id + canonical text.

    The dropdowns are a global catalog whose ids drift as AKS adds
    editions/regions, so the matcher's hardcoded id is not authoritative
    ([[session-catalog-editions-regions]]). Resolution order:

    1. **Unambiguous label match** — exactly one catalog option whose normalized
       text equals ``label``. Prefer it (this is the wrong-edition fix: trust the
       live label→id over a possibly-stale matcher id). e.g. edition "Standard".
    2. **Validate the matcher id** — if the label is absent/ambiguous (regions
       carry composite text like "Steam EU (9)" that a bare "EU" label can't
       uniquely hit) but ``candidate_id`` exists in the catalog, use it and take
       the catalog's canonical text.
    3. **Fail-closed** — neither resolves → return ``None`` (caller blocks the
       offer; never force, that created wrong-edition offers on 2026-07-06).

    Returns ``{"id", "text", "source": "label"|"id", "matcher_id",
    "changed": bool}`` or ``None``.
    """

    label_n = _norm_option_text(label)
    if label_n:
        matches = [o for o in master_options if _norm_option_text(o.get("text", "")) == label_n]
        if len(matches) == 1:
            key = str(matches[0].get("key"))
            return {
                "id": key, "text": matches[0].get("text"), "source": "label",
                "matcher_id": str(candidate_id), "changed": key != str(candidate_id),
            }

    by_id = {str(o.get("key")): o for o in master_options}
    if str(candidate_id) in by_id:
        o = by_id[str(candidate_id)]
        # FC4 (audit 2026-07-17) REVERTED 2026-07-20 — it wrongly required the
        # matcher label to appear as a word in the catalog text, but the two
        # are legitimately synonyms with the SAME id: the AKS dropdown labels
        # Steam's global/worldwide region "Steam (2)" while the matcher calls
        # it "GLOBAL". "global" is not in "steam (2)", so FC4 blocked GLOBAL —
        # the most common region — on every live submit (Driffle 2026-07-20:
        # all offers `region not in session catalog (label='GLOBAL' id='2')`).
        # The id-path validates EXISTENCE only, as it did for the project's
        # whole history; the label-path above already remaps a drifted id when
        # the label DOES match a unique option, and the human validates the
        # region label in the report. FC4's "id drifted to a different region"
        # was a PLAUSIBLE (unconfirmed) finding — a synonym-aware guard would
        # need the dropdown's own region vocabulary, out of scope here.
        return {
            "id": str(candidate_id), "text": o.get("text"), "source": "id",
            "matcher_id": str(candidate_id), "changed": False,
        }
    return None


def fetch_session_catalog(
    session: Any,
    *,
    store_id: str | int,
    feed_page: str = DEFAULT_FEED_PAGE,
    available: str = "all",
    max_pages: int = 40,
) -> dict[str, Any]:
    """Fetch the full Édition + Région dropdown lists ONCE per data-entry session.

    Both dropdowns are a global catalog (same across products); the ids can
    change as AKS adds editions/regions, so they must come from the live dropdown
    at session start rather than a hardcoded table. Read-only: opens one offer's
    modal (any current offer), enumerates both selects in full, no fill/create.
    Returns ``{ok, offer_id, region_select, edition_select, regions, editions}``
    or ``{ok: False, reason}``. Callers should do this once and reuse the result
    for every offer in the session.
    """

    session.navigate(feed_url(store_id, feed_page=feed_page, available=available))
    if session.is_login_page():
        return {"ok": False, "reason": "not_logged_in"}

    for page in range(1, max_pages + 1):
        session.navigate(feed_url(store_id, page=page, feed_page=feed_page, available=available))
        ids = session.page_offer_ids()
        # Render-poll: a slow JS-built feed list can read EMPTY on the first read under
        # CDP load; re-read the DOM (no re-navigate) before concluding the page is blank.
        # Without this a single transient empty read on page 1 breaks the whole catalog
        # fetch → no_openable_offer → catalog_unavailable → the submit halts fail-closed
        # (observed live 2026-08-26 on a healthy Driffle feed). Mirrors the extractor/
        # search render-poll (FEED_UI_RENDER_WAITS).
        for wait in FEED_UI_RENDER_WAITS:
            if ids or session.feed_page_state().get("feed_ui"):
                break
            time.sleep(wait)
            ids = session.page_offer_ids()
        if session.is_login_page():
            return {"ok": False, "reason": "not_logged_in"}
        if not ids:
            break
        for offer_id in ids:
            if session.open_offer_modal(offer_id) != "OPENED":
                continue
            names = set(session.modal_context().get("select_names", []))
            region_select = "offer[region]" if "offer[region]" in names else (
                "offer[region_id]" if "offer[region_id]" in names else None
            )
            edition_select = "offer[edition]" if "offer[edition]" in names else (
                "offer[edition_id]" if "offer[edition_id]" in names else None
            )
            if not region_select or not edition_select:
                continue
            return {
                "ok": True,
                "offer_id": offer_id,
                "region_select": region_select,
                "edition_select": edition_select,
                "regions": session.probe_select_options(region_select),
                "editions": session.probe_select_options(edition_select),
            }
    return {"ok": False, "reason": "no_openable_offer"}


class _SubmitterBase:
    write_mode = False
    event_name = "dry_run_offer"

    def __init__(
        self,
        session: Any,
        *,
        guard: StepGuard | None = None,
        logger: RunLogger | None = None,
        page_pacer: Pacer | None = None,
        offer_pacer: Pacer | None = None,
    ) -> None:
        self.session = session
        self.guard = guard or StepGuard(
            max_attempts_per_signature=1,
            max_failures_per_signature=2,
            max_consecutive_failures=10,
            max_failures_per_task=10 ** 9,
        )
        self.logger = logger
        # Burst mitigation (chantier n°2): page_pacer spaces the feed-scan page
        # loads (index + every post-save verify re-walk the feed), offer_pacer
        # spaces successive offers. Never a correctness mechanism.
        self.page_pacer = page_pacer
        self.offer_pacer = offer_pacer
        self.empty_retry_wait_s = EMPTY_RETRY_WAIT_S
        self.feed_scan_settle = FEED_SCAN_SETTLE
        self.feed_ui_render_waits = FEED_UI_RENDER_WAITS
        self.search_scan_max_pages = SEARCH_SCAN_MAX_PAGES
        self.catalog: dict[str, Any] | None = None
        self._region_master: list[dict[str, Any]] = []
        # Cooperative stop hook (default: never checked → submit pipeline
        # unaffected). When set to a callable, the feed-scan page loop raises
        # StopRequested at the next page boundary — a SAFE stop point (a scan is
        # read-only). Callers that also write (the mover) additionally check it
        # between offers and DISABLE it during a single offer's move, so a move
        # is never interrupted mid-Apply.
        self._should_stop = None
        self._edition_master: list[dict[str, Any]] = []

    def _load_catalog(self, catalog: dict[str, Any]) -> None:
        """Cache the session catalog + its master option lists for id resolution."""

        self.catalog = catalog
        self._region_master = ((catalog.get("regions") or {}).get("master_options")) or []
        self._edition_master = ((catalog.get("editions") or {}).get("master_options")) or []

    def _resolve_from_catalog(self, entry: dict[str, Any], candidate: dict[str, Any]) -> None:
        """Re-resolve the offer's region/edition ids against the live session
        catalog and stash the canonical text for type-to-filter. Fail-closed:
        an unresolvable label/id blocks the offer (no forcing — that created the
        2026-07-06 wrong-edition offers)."""

        for kind, master in (("region", self._region_master), ("edition", self._edition_master)):
            src = candidate.get(kind) or {}
            resolved = resolve_catalog_id(src.get("label", ""), src.get("id", ""), master)
            if resolved is None:
                entry["ready"] = False
                entry["blocker"] = (
                    f"{kind} not in session catalog "
                    f"(label={src.get('label')!r} id={src.get('id')!r})"
                )
                return
            entry[f"{kind}_id"] = resolved["id"]
            entry[f"{kind}_text"] = resolved["text"]
            entry[f"{kind}_resolution"] = resolved

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, **fields)

    def _wait_for_feed_ui(self, rows: list[dict[str, str]], state: dict[str, Any]
                          ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Poll the current DOM (re-read, NO re-navigate) with a backoff until the
        feed UI renders. A slow JS render under sustained CDP load leaves
        feed_ui=False on the first read though the page is loading fine (2026-08-18:
        batched sweeps halted on 'page rendered without the feed UI' after ~30 min).
        Returns the first (rows, state) that shows rows / login / a rendered feed UI,
        else the last read after the backoff (the caller then re-navigates / fails
        closed). Read-only, so safe to call anywhere in a scan."""
        for wait in self.feed_ui_render_waits:
            time.sleep(wait)
            rows = self.session.page_offer_rows()
            state = self.session.feed_page_state()
            if rows or state.get("is_login") or bool(state.get("feed_ui")):
                break
        self._log("feed_ui_render_wait", feed_ui=bool(state.get("feed_ui")),
                  rows=len(rows))
        return rows, state

    def _read_feed_page(self, url: str, page: int
                        ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Navigate to one feed page and read its rows + deterministic markers,
        retrying a blank or contradictory render ONCE (the extractor's blank-page
        discipline, EXECUTOR_RULES §3, carried over to the scans that back the
        post-save proof — audit 2026-07-17, SC2/FC1).

        Returns ``(rows, state)``. Empty ``rows`` is only ever returned as a
        PROVEN end-of-feed: past-the-end page (feed UI rendered, nav advertises
        fewer pages) or an empty queue on page 1 (feed UI, no pagination).
        A login bounce raises :class:`NotLoggedInError`; anything else that
        cannot be classified after the retry raises :class:`FeedScanError` —
        including a browser URL whose ``&p=`` does not match the page we
        navigated to (wedged navigation re-serving the previous DOM, SC6).
        """

        reason = ""
        for attempt in (1, 2):
            if attempt == 2:
                time.sleep(self.empty_retry_wait_s)
            # Feed-scan settle (no modal follows) — short by design; see
            # FEED_SCAN_SETTLE. _prepare's pre-modal navigate keeps the 3 s.
            self.session.navigate(url, settle=self.feed_scan_settle)
            rows = self.session.page_offer_rows()
            state = self.session.feed_page_state()
            # A slow JS render under sustained CDP load can leave the feed UI
            # unrendered on the first read (2026-08-18). Poll the DOM (re-read, NO
            # re-navigate) before concluding the page is blank/UI-less.
            if not rows and not state.get("is_login") and not bool(state.get("feed_ui")):
                rows, state = self._wait_for_feed_ui(rows, state)
            if state.get("is_login"):
                raise NotLoggedInError("feed bounced to wp-login mid-scan")
            href = str(state.get("href") or "")
            if _page_param(href) != page:
                reason = (
                    f"browser is on {href!r} (p={_page_param(href)}) "
                    f"after navigating to page {page}"
                )
                continue
            if rows:
                return rows, state
            nav_max = int(state.get("nav_max") or 0)
            feed_ui = bool(state.get("feed_ui"))
            if page == 1 and feed_ui and nav_max == 0:
                return [], state  # empty queue — proven
            if page > 1 and feed_ui and nav_max < page:
                return [], state  # past-the-end — proven
            reason = (
                f"blank page {page} with feed_ui={feed_ui} nav_max={nav_max}"
                if feed_ui else f"page {page} rendered without the feed UI"
            )
        raise FeedScanError(f"feed page unreadable after retry: {reason}")

    def _scan_feed(self, store_id, feed_page, available, max_pages,
                   stop_on: str | None = None, stop_on_url: str | None = None,
                   full_coverage: bool = False, stop_on_urls: "set[str] | None" = None,
                   ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], bool]:
        """Walk the feed pages building offer_id → row details AND
        merchant-url-path (`_url_key`) → current row. Both maps carry the full
        row details ``{page_url, name, url, price, store_id}`` so `_locate_row`
        can verify the row against the candidate BEFORE the modal opens
        (audit P1, 2026-07-08 — previously the id map held the page url only,
        so the nominal by-id path verified nothing).

        The url map exists because AKS re-imports re-id EVERY row (K4G
        2026-07-08: 0/212 ids survived the 74 minutes between extraction and
        submit; G2A: 0/716 in 24h) — the merchant URL path is the stable row
        identity across imports (full-URL params drift on G2A, see `_url_key`).

        With ``stop_on``/``stop_on_url``, stop as soon as the offer is seen
        under EITHER key and report found=True (the partial index is then
        unusable as a feed snapshot) — a disappearance proof must fail when
        the row survived a mid-run re-import under a fresh id. Without them
        (plain indexing), two consecutive pages with no NEW ids end the walk
        (G2A reflow renders duplicate pages); with them, only a PROVEN
        end-of-feed does — a verify scan must reach the end of the feed
        before concluding the offer is gone, and every ending is now
        positively classified (audit 2026-07-17, FC1/SC2/SC4): a blank page
        must carry the past-the-end/empty-queue markers, and exhausting
        ``max_pages`` with the nav advertising MORE pages raises
        :class:`FeedScanError` instead of silently truncating coverage.

        ``full_coverage`` (no ``stop_on``): index the WHOLE feed with the same
        proven-end discipline as the stop_on path — the 2-empty-new-id early
        terminate is disabled, so the returned maps are a COMPLETE membership
        snapshot (a batched move's set-wise "gone from source" proof needs this;
        the plain early terminate could call an offer on an unscanned tail page
        absent — audit 2026-07-28). ``found`` is always False in this mode.

        ``stop_on_urls`` (a SET of merchant URLs): stop as soon as EVERY url in
        the set has been seen (``found=True``), else walk to a proven end. The
        set-wise analogue of ``stop_on_url`` for a whole GROUP — one target-list
        scan proves RV2 presence for K offers at once instead of K stop_on scans
        (decisive when the target list is large, e.g. account ~15k — P1.5
        2026-07-28). The caller reads membership from the returned ``by_url``.
        """
        index: dict[str, dict[str, str]] = {}
        by_url: dict[str, dict[str, str]] = {}
        stop_on_url = _url_key(stop_on_url) if stop_on_url else None
        stop_on_urls = {_url_key(u) for u in stop_on_urls if u} if stop_on_urls else None
        found = False
        empty = 0
        nav_max_seen = 0
        for page in range(1, max_pages + 1):
            # Cooperative stop at a page boundary (read-only, always safe). The
            # mover only leaves this hook armed during the initial index and
            # clears it during a move, so no write is ever cut mid-flight.
            if self._should_stop is not None and self._should_stop():
                raise StopRequested(f"scan interrompu par l'opérateur (page {page})")
            url = feed_url(store_id, page=page, feed_page=feed_page, available=available)
            if page > 1 and self.page_pacer is not None:
                self.page_pacer.wait()
            rows, state = self._read_feed_page(url, page)
            nav_max_seen = max(nav_max_seen, int(state.get("nav_max") or 0))
            if not rows:
                break  # proven end-of-feed (_read_feed_page classified it)
            new = 0
            for row in rows:
                offer_id = str(row.get("id") or "")
                if not offer_id:
                    continue
                details = {
                    "offer_id": offer_id,
                    "page_url": url,
                    "name": str(row.get("name") or ""),
                    "url": str(row.get("url") or ""),
                    "price": str(row.get("price") or ""),
                    "store_id": str(row.get("store_id") or ""),
                }
                if offer_id not in index:
                    index[offer_id] = details
                    new += 1
                row_url = _url_key(details["url"])
                if row_url and row_url not in by_url:
                    by_url[row_url] = details
            if (stop_on is not None and stop_on in index) or (
                stop_on_url is not None and stop_on_url in by_url
            ) or (
                stop_on_urls is not None and stop_on_urls <= by_url.keys()
            ):
                found = True
                break
            if (stop_on is None and stop_on_url is None and stop_on_urls is None
                    and not full_coverage):
                if new == 0:
                    empty += 1
                    if empty >= 2:
                        break
                else:
                    empty = 0
        else:
            # Loop exhausted at max_pages with rows still present on the last
            # page. Coverage is proven ONLY when the feed's own nav never
            # advertised more pages than we walked; otherwise the tail was
            # never scanned and a verify built on this walk would prove a
            # false disappearance (audit 2026-07-17, SC4/FC6).
            if not (0 < nav_max_seen <= max_pages):
                raise FeedScanError(
                    f"feed scan hit max_pages={max_pages} without reaching the "
                    f"feed's end (nav advertises "
                    f"{nav_max_seen if nav_max_seen else 'an unreadable number of'} "
                    "page(s)) — coverage unproven"
                )
        return index, by_url, found

    def _index_feed(self, store_id, feed_page, available, max_pages
                    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        index, by_url, _ = self._scan_feed(store_id, feed_page, available, max_pages)
        return index, by_url

    def _scan_page_window(self, store_id, feed_page, available, pages,
                          *, stop_on: str | None = None, stop_on_url: str | None = None
                          ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], bool]:
        """Build index/by_url from ONLY the given feed pages, navigating DIRECTLY
        to each (``&p=N``) — a targeted alternative to the sequential
        ``_index_feed`` for a feed too deep/reflow-heavy to reach from page 1
        (submit-index-shallow-feed, 2026-08-05: the sequential scan terminates
        ~28 pages so deep offers are never located). The caller knows the offer's
        page from the extract, so we read that page + a small neighbourhood.

        Every page is read with ``_read_feed_page`` (same blank-page discipline,
        fail-closed): a proven past-the-end page yields no rows and is skipped; an
        unreadable page raises. ``found`` is True iff ``stop_on`` (id) or
        ``stop_on_url`` (merchant URL) is seen — the post-save membership check.
        The whole window is always read (≤ a few pages) so the maps are complete
        for the next candidate; there is no early stop."""

        index: dict[str, dict[str, str]] = {}
        by_url: dict[str, dict[str, str]] = {}
        stop_key = _url_key(stop_on_url) if stop_on_url else None
        found = False
        for page in pages:
            if page < 1:
                continue
            url = feed_url(store_id, page=page, feed_page=feed_page, available=available)
            rows, _state = self._read_feed_page(url, page)  # raises fail-closed; [] = proven end
            for row in rows:
                offer_id = str(row.get("id") or "")
                if not offer_id:
                    continue
                details = {
                    "offer_id": offer_id,
                    "page_url": url,
                    "name": str(row.get("name") or ""),
                    "url": str(row.get("url") or ""),
                    "price": str(row.get("price") or ""),
                    "store_id": str(row.get("store_id") or ""),
                }
                if offer_id not in index:
                    index[offer_id] = details
                key = _url_key(details["url"])
                if key and key not in by_url:
                    by_url[key] = details
                if (stop_on and offer_id == stop_on) or (stop_key and key == stop_key):
                    found = True
        return index, by_url, found

    def _search_url(self, store_id, feed_page, available, term, field="url", page=1) -> str:
        """The AKS feed SEARCH form (page=aks-merchant-feeds-search) filtered by ONE
        offer's slug. It is a whole-feed FILTERED query (NOT a page window): an absence
        across ALL its result pages is a genuine whole-feed absence, so it is a VALID
        gone-proof — unlike a single page window, which can miss a live offer on a
        later result page (the CRITICAL phantom-creation trap). Used for the by-urls
        submit's locate + prove-gone (Romain 2026-08-25)."""
        list_no = str(feed_page).rsplit("-", 1)[-1]
        params = {"page": "aks-merchant-feeds-search", "available": available,
                  "list": list_no, "store": str(store_id),
                  "search[search]": term, "search[field]": field}
        if page and int(page) > 1:
            params["p"] = str(int(page))
        return AKS_ADMIN_URL + "?" + urllib.parse.urlencode(params)

    def _scan_search(self, store_id, feed_page, available, url):
        """Locate ``url`` via the feed SEARCH; return (index_by_id, by_url) of the
        matching rows, each with ``page_url`` = the exact result page it was found on
        (so ``_prepare``'s navigate re-reads that filtered view). The search is walked
        to a PROVEN end across ALL result pages with the same fail-closed discipline as
        the feed scan (``_read_feed_page``: blank-page retry, render-poll, nav_max
        proven-end, the ``&p=`` wedged-navigation guard SC6): the term (the offer's
        slug) is a SUBSTRING match that can overflow one page, and reading only page 1
        would let a live offer on a later page read as absent → a false 'gone' →
        phantom creation (2026-08-25 review). On top of ``_read_feed_page`` it adds a
        term DATA-check — the server filtered by the slug, so every legit row's URL
        contains it; rows that do NOT are a stale/foreign DOM re-served under the same
        ``&p=`` (a prior candidate's search, or a plain feed page) that the page-number
        href check alone cannot catch. FAIL-CLOSED: an unrendered/wedged page, or
        results still advertising more pages than the budget covers, raises
        FeedScanError so prove-gone is UNKNOWN and never a false 'gone'; a login bounce
        raises NotLoggedInError."""
        key = _url_key(str(url or ""))
        term = key.rstrip("/").rsplit("/", 1)[-1] or key    # the offer's distinctive slug
        index: dict[str, dict[str, str]] = {}
        by_url: dict[str, dict[str, str]] = {}
        max_pages = self.search_scan_max_pages
        nav_max_seen = 0
        for page in range(1, max_pages + 1):
            search_url = self._search_url(store_id, feed_page, available, term, "url", page=page)
            rows, state = self._read_feed_page(search_url, page)
            nav_max_seen = max(nav_max_seen, int(state.get("nav_max") or 0))
            if not rows:
                # Proven end (_read_feed_page classified empty-queue/past-the-end). An
                # empty page has NO rows for the term data-check, so confirm the browser
                # is genuinely on THIS search before trusting the emptiness as a real
                # 0-result 'gone' — a wedge re-serving a foreign/prior empty DOM (a
                # different-term search, an empty feed page) keeps location.href on the
                # PRIOR url, which the &p= SC6 check misses at 0 rows (2026-08-25 review).
                on_term = _href_search_term(str(state.get("href") or ""))
                if on_term is not None and on_term != term:
                    raise FeedScanError(
                        f"empty search page is on term {on_term!r}, expected {term!r} "
                        "— stale/foreign DOM, cannot prove absence")
                break
            if not all(term in _url_key(str(r.get("url") or "")) for r in rows):
                raise FeedScanError(
                    f"search page {page} rows do not all match term {term!r} "
                    "— stale/foreign DOM re-served")
            for r in rows:
                rid = str(r.get("id") or "")
                rk = _url_key(str(r.get("url") or ""))
                details = {"offer_id": rid, "page_url": search_url,
                           "name": str(r.get("name") or ""), "url": str(r.get("url") or ""),
                           "price": str(r.get("price") or ""), "store_id": str(r.get("store_id") or "")}
                if rid:
                    index[rid] = details
                if rk:
                    by_url[rk] = details
            if nav_max_seen and page >= nav_max_seen:
                break  # read every advertised result page — coverage proven
        else:
            # Ran the whole page budget with rows still on the last page and the nav
            # advertising MORE (or an unreadable nav_max): coverage is NOT proven
            # complete, so an absence here cannot stand as a 'gone' proof.
            if not (0 < nav_max_seen <= max_pages):
                raise FeedScanError(
                    f"search for {term!r} hit max_pages={max_pages} without reaching "
                    f"the end (nav advertises "
                    f"{nav_max_seen if nav_max_seen else 'an unreadable number of'} "
                    "page(s)) — coverage unproven")
        return index, by_url

    def _index_by_search(self, store_id, feed_page, available, approved):
        """Build the locate index from the SEARCH (one filtered query per candidate
        URL) instead of a whole-feed scan — fast, and each row is FRESH (it cannot
        reflow away during a multi-minute scan, the by-urls submit's failure mode).
        A candidate whose search is momentarily unreadable is simply not pre-indexed
        (its per-offer relocate retries, else it skips) — never a batch abort; a
        login bounce propagates (session gone)."""
        index: dict[str, dict[str, str]] = {}
        by_url: dict[str, dict[str, str]] = {}
        for c in approved:
            url = str((c.get("offer") or {}).get("url") or "")
            if not url:
                continue
            try:
                idx, bu = self._scan_search(store_id, feed_page, available, url)
            except FeedScanError:
                continue
            index.update(idx)
            by_url.update(bu)
        return index, by_url

    def _locate_row(self, candidate: dict[str, Any], offer_id: str,
                    index: dict[str, dict[str, str]], by_url: dict[str, dict[str, str]]
                    ) -> dict[str, Any]:
        """Resolve an approved candidate to a row of the CURRENT feed.

        By approved offer id while the import batch is unchanged — the row's
        name/URL-path (+ price/store when present) must match the candidate
        (audit P1, 2026-07-08: id membership alone verified nothing, and a
        re-import can reuse an id for a DIFFERENT row). On any contradiction
        the id is treated as stale and the merchant-URL identity decides.
        After a re-import, by merchant URL with an exact-title (+ store)
        check, adopting the row's current id; price is not compared there —
        a re-import legitimately refreshes it, so a price-only drift on an
        otherwise confirmed row NEVER blocks: it is surfaced as
        ``id_mismatches`` in the plan entry and the ``row_relocated`` log
        instead (deliberate, audit 3 2026-07-08). AGENTS.md: "locate exact
        current row; verify title, URL, price, page, merchant". "Page" is
        deliberately RECOMPUTED by the current scan (`page_url` in the row
        details), never compared to an approved-time value: no page is stored
        at approval and pagination reflows constantly (2026-07-07 G2A: 8
        creations moved a live row from page 2 to page 1).
        """
        id_mismatches: list[str] = []
        row = index.get(offer_id)
        if row is not None:
            id_mismatches, checked = _row_check(row, candidate, check_price=True)
            if not id_mismatches:
                return {"offer_id": offer_id, "page_url": row["page_url"],
                        "row_checked": checked}
        url = _url_key(str(candidate["offer"].get("url") or ""))
        row = by_url.get(url) if url else None
        if row is None:
            if id_mismatches:
                return {"blocker": (
                    "row at the approved id contradicts the candidate "
                    f"({', '.join(id_mismatches)}) and the approved URL is "
                    "not in the current feed"
                )}
            return {"blocker": "offer not in current feed (by id and by URL)"}
        mismatches, checked = _row_check(row, candidate, check_price=False)
        if "name" in mismatches:
            return {"blocker": (
                "feed row at the approved URL has a different title — "
                f"feed {row['name']!r} != approved {candidate['offer']['name']!r}"
            )}
        if mismatches:
            return {"blocker": (
                "feed row at the approved URL contradicts the candidate "
                f"({', '.join(mismatches)})"
            )}
        located = {"offer_id": row["offer_id"], "page_url": row["page_url"],
                   "approved_offer_id": offer_id, "located_by": "url",
                   "row_checked": checked}
        if id_mismatches:
            # The by-id row existed but contradicted the candidate (id reuse /
            # price drift) — non-blocking once the URL identity confirmed, but
            # surfaced so the drift is visible in the plan and the log.
            located["id_mismatches"] = id_mismatches
        return located

    def _relocate_by_url(self, candidate: dict[str, Any], ctx: dict[str, Any]
                         ) -> dict[str, str] | None:
        """A reflow/re-import BETWEEN the index scan and this candidate's modal open
        (e.g. an earlier creation this run shifted the feed, or the pending feed
        re-imported and rotated every id) can move the located row off its page or
        rotate its id → the by-id read on the located page finds nothing. Fresh-scan
        the feed by the candidate's STABLE merchant URL to find its CURRENT row (id +
        page) before giving up — mirrors the mover's ``_relocate_before_move``.
        Read-only. Returns the row details, or None when the URL is not in the feed
        OR now points at a DIFFERENT product (fail closed — never open a modal on a
        mismatched identity). A feed/CDP-unreadable scan propagates to the caller's
        fail-closed handler (as elsewhere in ``_prepare``)."""
        url = _url_key(str(candidate["offer"].get("url") or ""))
        if not url:
            return None
        try:
            if ctx.get("search_locate"):
                # by-urls: re-locate via the SEARCH (fast + fresh) — no whole-feed scan.
                _, by_url = self._scan_search(
                    ctx["store_id"], ctx["feed_page"], ctx["available"], url)
            else:
                _, by_url, found = self._scan_feed(
                    ctx["store_id"], ctx["feed_page"], ctx["available"], ctx["max_pages"],
                    stop_on_url=url)
                by_url = by_url if found else {}
        except (FeedScanError, CdpCommandError):
            # The recovery scan is unreadable — this is BEFORE any write for this
            # candidate, so treat it as "not found" → the caller keeps the vanished
            # block (skip, retry on a fresh run). A NotLoggedInError is NOT caught
            # (session gone) and propagates, exactly like the rest of _prepare.
            return None
        row = by_url.get(url)
        if row is None:
            return None
        mismatches, _ = _row_check(row, candidate, check_price=False)
        if "name" in mismatches:
            return None   # URL now points at a DIFFERENT product → do not touch it
        return row

    def _prepare(self, candidate: dict[str, Any], located: dict[str, Any],
                 ctx: dict[str, Any]) -> dict[str, Any]:
        offer_id = str(located.get("offer_id") or candidate["offer"]["offer_id"])
        entry: dict[str, Any] = {
            "offer_id": offer_id,
            "merchant_title": candidate["offer"]["name"],
            "aks_url": candidate["aks_url"],
            "aks_product_id": candidate.get("aks_product_id"),
            "region_id": candidate["region"]["id"],
            "edition_id": candidate["edition"]["id"],
            "ready": False,
        }
        if located.get("located_by") == "url":
            entry["approved_offer_id"] = located["approved_offer_id"]
            entry["located_by"] = "url"
        if located.get("id_mismatches"):
            entry["id_mismatches"] = located["id_mismatches"]
        if located.get("row_checked"):
            entry["row_checked"] = located["row_checked"]
        if located.get("blocker"):
            entry["blocker"] = located["blocker"]
            return entry
        entry["page_url"] = located["page_url"]
        self.session.navigate(located["page_url"])  # refresh the row's page
        # The index scan's row check is now minutes old and this navigate just
        # produced a NEW render — re-verify the row on the FRESH DOM before
        # opening its modal by id (audit 2026-07-17, SC5): a re-import in the
        # window can hand this id to a different product, and the modal would
        # open on it without any identity check.
        fresh = next(
            (r for r in self.session.page_offer_rows()
             if str(r.get("id") or "") == offer_id),
            None,
        )
        if fresh is None:
            # A reflow/re-import mid-run shifted the row off this page or rotated its
            # id. Re-locate by the stable merchant URL (fresh scan) before giving up,
            # like the mover — the offer usually just moved to an adjacent page.
            relocated = self._relocate_by_url(candidate, ctx)
            if relocated is None:
                entry["blocker"] = (
                    "row vanished from its page between the index scan and the "
                    "modal open, and not found by URL re-locate (genuinely gone / "
                    "re-imported away)"
                )
                return entry
            stale_offer_id = offer_id
            offer_id = relocated["offer_id"]
            entry["offer_id"] = offer_id
            entry["page_url"] = relocated["page_url"]
            entry["relocated_by_url"] = True
            self._log("submit_row_relocated", stale_offer_id=stale_offer_id,
                      current_offer_id=offer_id, page_url=relocated["page_url"],
                      url=candidate["offer"].get("url"))
            self.session.navigate(relocated["page_url"])   # go to its NEW page
            fresh = next(
                (r for r in self.session.page_offer_rows()
                 if str(r.get("id") or "") == offer_id),
                None,
            )
            if fresh is None:
                entry["blocker"] = (
                    "row vanished again after URL re-locate + navigate — the feed is "
                    "reflowing too fast to pin (retry on a fresh run)"
                )
                return entry
        fresh_details = {
            "offer_id": offer_id,
            "page_url": located["page_url"],
            "name": str(fresh.get("name") or ""),
            "url": str(fresh.get("url") or ""),
            "price": str(fresh.get("price") or ""),
            "store_id": str(fresh.get("store_id") or ""),
        }
        mismatches, fresh_checked = _row_check(fresh_details, candidate, check_price=False)
        if mismatches:
            entry["blocker"] = (
                "fresh page row at the located id contradicts the candidate "
                f"({', '.join(mismatches)}) — id reused by a mid-run re-import?"
            )
            return entry
        entry["fresh_row_checked"] = fresh_checked
        status = self.session.open_offer_modal(offer_id)
        entry["modal"] = status
        if status != "OPENED":
            entry["blocker"] = f"modal open: {status}"
            return entry
        context = self.session.modal_context()
        names = set(context.get("select_names", []))
        entry["select_names"] = sorted(names)
        if not context.get("ok"):
            entry["blocker"] = "modal context missing (#TB_ajaxContent)"
            return entry
        region_select = "offer[region]" if "offer[region]" in names else (
            "offer[region_id]" if "offer[region_id]" in names else None
        )
        edition_select = "offer[edition]" if "offer[edition]" in names else (
            "offer[edition_id]" if "offer[edition_id]" in names else None
        )
        entry["region_select"], entry["edition_select"] = region_select, edition_select
        if not region_select or not edition_select:
            entry["blocker"] = "region/edition select not found"
            return entry
        entry["ready"] = True
        if self.catalog is not None:
            self._resolve_from_catalog(entry, candidate)
        return entry

    def _verify_gone(self, offer_id, merchant_url, store_id, feed_page, available,
                     max_pages, *, search_locate: bool = False
                     ) -> tuple[bool, dict[str, dict[str, str]] | None, dict[str, dict[str, str]] | None]:
        """Post-save: re-scan the feed. Returns (gone, fresh_index, fresh_by_url).

        gone is True iff the offer is absent under BOTH keys — the row id we
        just acted on AND the merchant URL. An id-only check would prove a
        false disappearance whenever a re-import re-ids the row mid-run (K4G
        2026-07-08) while it is in fact still in the feed. When gone, the scan ran
        to the end of the feed and the collected maps ARE the current feed
        state — callers reuse them to locate the next candidate on the
        refreshed feed (AGENTS.md: "refresh current merchant feed; locate exact
        current row". 2026-07-07 G2A: 8 creations reflowed the pagination and
        the stale batch-start index yielded ROW_NOT_FOUND on a live offer).
        Both maps are None when the offer was found (partial scan, unusable).

        ``search_locate`` (by-urls): prove-gone via the feed SEARCH — a whole-feed
        FILTERED query, so an absence is a genuine whole-feed absence (a valid
        gone-proof, NOT a page window). A search page that never renders raises
        FeedScanError → the caller's FEED_UNREADABLE handler marks the offer UNKNOWN,
        NEVER a false "gone" (phantom-creation guard).
        """
        if search_locate and merchant_url:
            index, by_url = self._scan_search(store_id, feed_page, available, merchant_url)
            key = _url_key(merchant_url)
            found = (key in by_url) or (str(offer_id) in index)
            if found:
                return False, None, None
            return True, index, by_url
        index, by_url, found = self._scan_feed(
            store_id, feed_page, available, max_pages,
            stop_on=offer_id, stop_on_url=merchant_url or None)
        if found:
            return False, None, None
        return True, index, by_url

    def _process(self, entry: dict[str, Any], candidate: dict[str, Any], ctx: dict[str, Any]) -> bool:
        raise NotImplementedError

    def run(
        self,
        *,
        run_id: str,
        merchant: str,
        store_id: str | int,
        approved: list[dict[str, Any]],
        feed_page: str = DEFAULT_FEED_PAGE,
        available: str = "all",
        max_pages: int = 40,
        limit: int | None = None,
        catalog: dict[str, Any] | None = None,
        page_hint: int | None = None,
        page_window: int = 1,
        locate_by_search: bool = False,
    ) -> dict[str, Any]:
        # Pre-flight login check.
        self.session.navigate(feed_url(store_id, feed_page=feed_page, available=available))
        if self.session.is_login_page():
            self._log("aborted", reason="not logged in (wp-login)")
            return {"aborted": "not_logged_in", "stopped": None, "feed_offers": 0,
                    "write_attempts": 0, "created": 0, "plan": []}

        # Write path resolves every offer's region/edition id against the LIVE
        # dropdown catalog (ids drift; the matcher's are not authoritative). Fetch
        # it once per run if the caller didn't pass one. Fail-closed: no catalog =
        # no writes.
        if self.write_mode:
            if catalog is None:
                catalog = fetch_session_catalog(
                    self.session, store_id=store_id, feed_page=feed_page,
                    available=available, max_pages=max_pages,
                )
            if not catalog.get("ok"):
                self._log("aborted", reason="catalog fetch failed", detail=catalog.get("reason"))
                return {"aborted": "catalog_unavailable", "stopped": None, "feed_offers": 0,
                        "write_attempts": 0, "created": 0, "plan": [], "catalog": catalog}
            self._load_catalog(catalog)

        # ``page_hint`` (submit-index-shallow-feed fix, 2026-08-06): the caller
        # (the safe-auto sweep) knows the offers' feed page from the extract, so
        # index only a small WINDOW of pages around it (navigating directly)
        # instead of the sequential scan that terminates ~28 pages and can't reach
        # deep pages. This is a LOCATE optimisation ONLY — it finds the row cheaply.
        # The post-save gone-proof stays a WHOLE-FEED scan (see _process): a bounded
        # window cannot prove global disappearance (a parallel operator / re-import
        # can shift a live offer out of the window → false gone, 2026-08-06 review).
        # A window > 0 tolerates the modest reflow between extract and this run so
        # the row is still found; being wrong here only fails the locate closed
        # (offer not found → skipped), never a false create.
        window_pages: list[int] | None = None
        if page_hint is not None:
            window_pages = [p for p in range(page_hint - page_window, page_hint + page_window + 1)
                            if p >= 1]

        self.guard.start_task(run_id)
        try:
            if locate_by_search:
                # by-urls: the offers were found by SEARCH (their feed page is unknown
                # and Driffle-class feeds reflow too fast for a multi-minute whole-feed
                # scan to pin them). Build the locate index from per-offer searches —
                # fast + fresh (Romain 2026-08-25). Locate/relocate/prove-gone all use
                # the search via ctx["search_locate"].
                index, by_url = self._index_by_search(store_id, feed_page, available, approved)
            elif window_pages is not None:
                index, by_url, _ = self._scan_page_window(store_id, feed_page, available, window_pages)
            else:
                index, by_url = self._index_feed(store_id, feed_page, available, max_pages)
        except StopRequested as exc:
            # Operator stop DURING the read-only index scan — before any offer is
            # touched. A clean stop (no writes), not a crash.
            self._log("run_stopped", reason="operator_stop", detail=str(exc))
            return {"aborted": None, "stopped": "operator_stop", "feed_offers": 0,
                    "write_attempts": 0, "created": 0, "plan": []}
        except FEED_UNREADABLE_EXCS as exc:
            # Nothing has been attempted yet — abort before the first offer
            # rather than working from an unproven feed snapshot (audit
            # 2026-07-17, FC1/SC2).
            self._log("aborted", reason=f"feed index scan failed closed: {exc}")
            return {"aborted": "feed_unreadable", "stopped": None, "feed_offers": 0,
                    "write_attempts": 0, "created": 0, "plan": []}
        self._log("feed_indexed", offers=len(index), window=window_pages)
        ctx = {"store_id": store_id, "feed_page": feed_page, "available": available,
               "max_pages": max_pages, "index": index, "by_url": by_url,
               "window_pages": window_pages, "search_locate": locate_by_search}

        # Disarm the scan-level stop hook now that the index is done: each offer's
        # post-save verify / reflow re-scan MUST complete (a stop mid-verify would
        # leave the just-created offer in an UNKNOWN state). The operator stop is
        # honored instead at the OFFER BOUNDARY below, via this captured hook —
        # exactly the mover's discipline (arm for the read-only index, clear
        # before any write, check cooperatively between units).
        offer_boundary_stop = self._should_stop
        self._should_stop = None

        plan: list[dict[str, Any]] = []
        stopped: str | None = None
        # --limit counts ATTEMPTS (every ready offer we tried to write) —
        # deliberately conservative. `created` counts VERIFIED creations only
        # (post-save proof: gone from the refreshed feed). Reported separately
        # since Romain's audit P2 (2026-07-08): the old single `writes` field
        # was the attempt counter but read like a creation count.
        write_attempts = 0
        created = 0
        for candidate in approved:
            # Cooperative stop at an OFFER BOUNDARY only (before locating/opening
            # the next offer) — never mid-Create/post-save. A SIGTERM (console
            # "Arrêter") sets this via 05_submit.py, so a stop finishes the
            # in-flight offer cleanly instead of hard-killing it mid-write.
            if offer_boundary_stop is not None and offer_boundary_stop():
                stopped = "operator_stop"
                self._log("run_stopped", reason=stopped)
                break
            if self.write_mode and limit is not None and write_attempts >= limit:
                stopped = "limit_reached"
                self._log("run_stopped", reason=stopped)
                break
            offer_id = str(candidate["offer"]["offer_id"])
            signature = f"submit:{offer_id}"
            if not self.guard.check("submit", signature).allowed:
                stopped = "guard_blocked"
                self._log("run_stopped", reason=stopped)
                break

            located = self._locate_row(candidate, offer_id, ctx["index"], ctx["by_url"])
            if located.get("located_by") == "url":
                self._log(
                    "row_relocated",
                    approved_offer_id=offer_id,
                    current_offer_id=located["offer_id"],
                    url=candidate["offer"].get("url"),
                    page_url=located["page_url"],
                    id_mismatches=located.get("id_mismatches"),
                )
            # A feed/CDP-unreadable exception here means the current offer's
            # state is UNKNOWN (on the write path, Create may already have
            # been clicked when the verify scan died). Fail closed: record the
            # attempt, mark the entry for a manual check, stop the run — the
            # plan/logs keep everything known so far (audit 2026-07-17, FC1).
            entry: dict[str, Any] | None = None
            feed_unreadable: str | None = None
            try:
                entry = self._prepare(candidate, located, ctx)
                success = self._process(entry, candidate, ctx)
            except FEED_UNREADABLE_EXCS as exc:
                if entry is None:
                    entry = {
                        "offer_id": offer_id,
                        "merchant_title": candidate["offer"]["name"],
                        "aks_url": candidate.get("aks_url"),
                        "ready": False,
                    }
                success = False
                feed_unreadable = f"{type(exc).__name__}: {exc}"
                entry["post_save"] = (
                    "feed/CDP unreadable — offer state UNKNOWN, verify it by "
                    f"hand on AKS before any retry: {feed_unreadable}"
                )
            if self.write_mode and entry.get("ready"):
                write_attempts += 1
                if entry.get("submitted"):
                    created += 1
            self.guard.record_result(
                "submit", signature, success, detail=entry.get("blocker", "") or entry.get("post_save", "")
            )
            self._log(
                self.event_name,
                offer_id=offer_id, ready=entry["ready"], success=success,
                blocker=entry.get("blocker"), post_save=entry.get("post_save"),
            )
            if not success:
                self._log("skip", offer_id=offer_id, reason=entry.get("blocker") or entry.get("post_save"))
            plan.append(entry)

            if feed_unreadable is not None:
                stopped = "feed_unreadable"
                self._log("run_stopped", reason=stopped, detail=feed_unreadable)
                break
            if self.guard.blocked:
                stopped = "ten_consecutive_failures"
                self._log("run_stopped", reason=stopped)
                break
            if self.offer_pacer is not None and (not self.write_mode or entry.get("ready")):
                self.offer_pacer.wait()

        if self.logger is not None:
            if self.page_pacer is not None or self.offer_pacer is not None:
                self._log(
                    "pacing",
                    pages=self.page_pacer.snapshot() if self.page_pacer else None,
                    offers=self.offer_pacer.snapshot() if self.offer_pacer else None,
                )
            self.logger.log_guard(self.guard.snapshot())
        result = {
            "aborted": None,
            "stopped": stopped,
            "feed_offers": len(index),
            "write_attempts": write_attempts if self.write_mode else None,
            "created": created if self.write_mode else None,
            "plan": plan,
        }
        if self.catalog is not None:
            result["catalog"] = {
                "offer_id": self.catalog.get("offer_id"),
                "regions_count": len(self._region_master),
                "editions_count": len(self._edition_master),
            }
        return result


class DryRunSubmitter(_SubmitterBase):
    """Rehearsal — never writes."""

    write_mode = False
    event_name = "dry_run_offer"

    def _process(self, entry, candidate, ctx):
        if entry.get("ready"):
            entry["would_submit"] = (
                f"set {entry['region_select']}={entry['region_id']}, "
                f"{entry['edition_select']}={entry['edition_id']}, "
                "click .button-primary (NOT clicked — dry-run)"
            )
        return bool(entry.get("ready"))


class InspectSubmitter(_SubmitterBase):
    """S18 investigation — open each ready offer's modal and dump a read-only
    DOM inspection (`session.inspect_modal_dom()`). No fill, no clicks on
    Create, no writes. Used to identify the true submit-trigger element after
    the canary #3 diag showed native/dispatch clicks producing zero network
    requests on Driffle (2026-07-03).
    """

    write_mode = False
    event_name = "inspect_offer"

    def _process(self, entry, candidate, ctx):
        if not entry.get("ready"):
            return False
        entry["inspection"] = self.session.inspect_modal_dom()
        # Read-only HTML5 validity summary (covers input/select/textarea — the
        # Selectize region/edition selects included). At rest the form is
        # expected invalid; the value is the *inventory* of required fields
        # beyond region/edition (e.g. offer[targets][]) that a real operator
        # fills and the robot currently does not — the S18 lead, obtainable with
        # NO write.
        entry["form_validity"] = self.session.form_validity()
        # Forensic read-only dump of `offer[targets][]` — the one required field
        # the fill path never populates (S18, 2026-07-06). Tells us what value it
        # expects (placeholder / datalist / label / widget) with NO write.
        entry["targets_probe"] = self.session.probe_targets_field()
        return True


class Submitter(_SubmitterBase):
    """Real submitter — WRITES. Requires a WriteSubmitSession.

    ``click_mode`` is passed through to the session: 'trusted' (default —
    Chantier n°1, 2026-07-03 — CDP `Input.dispatchMouseEvent` at the button
    center, produces `event.isTrusted:true`; the *only* mode that reliably fires
    Driffle's handler), 'native' (`b.click()`) or 'dispatch' (documented S09
    derogation — MouseEvent on the Create button only). native/dispatch produce
    `isTrusted:false` and are proven NOT to persist on Driffle — kept only as
    documented diagnostics. Post-save (offer gone from the refreshed feed, same
    available mode as the run) remains the ONLY success proof in every mode.
    """

    write_mode = True
    event_name = "submit_offer"
    ALL_CLICK_MODES = ("native", "dispatch", "trusted")

    def __init__(self, session: Any, *, click_mode: str = "trusted", **kw: Any) -> None:
        if click_mode not in self.ALL_CLICK_MODES:
            raise ValueError(
                f"unknown click_mode: {click_mode!r} (allowed: {self.ALL_CLICK_MODES})"
            )
        super().__init__(session, **kw)
        self.click_mode = click_mode

    def _process(self, entry, candidate, ctx):
        if not entry.get("ready"):
            return False
        if self.click_mode == "trusted":
            diag = self.session.fill_then_click_trusted(
                entry["region_select"], entry["region_id"],
                entry["edition_select"], entry["edition_id"],
                target_value=entry.get("aks_product_id"),
                region_query=entry.get("region_text"),
                edition_query=entry.get("edition_text"),
            )
        else:
            diag = self.session.fill_and_create(
                entry["region_select"], entry["region_id"],
                entry["edition_select"], entry["edition_id"],
                click_mode=self.click_mode,
            )
        entry["create"] = diag  # dict: status + read-back values + options + signal
        status = diag.get("status") if isinstance(diag, dict) else diag
        # Only a settled click (success signal, or no signal but no error) proceeds to
        # the real post-save proof. ERROR / NO_SELECTS / NO_BUTTON / NO_ELEMENT /
        # NO_TRUSTED_CLICK / NO_ELEMENT_AFTER_SCROLL / FORM_INVALID is a hard fail.
        if status not in ("SUCCESS", "NO_SIGNAL"):
            reason = diag.get("signal") if isinstance(diag, dict) else ""
            if status == "FORM_INVALID" and isinstance(diag, dict):
                fields = [
                    x.get("name") for x in (diag.get("form_validity") or {}).get("invalid_required", [])
                ]
                reason = "invalid required fields: " + ", ".join(str(f) for f in fields)
            entry["post_save"] = f"create not confirmed: {status}" + (f" — {reason}" if reason else "")
            return False
        # The post-save gone-proof is ALWAYS a whole-feed scan to a PROVEN end —
        # NEVER the page window, even under page_hint. A bounded-window absence is
        # not a disappearance proof: a parallel operator or a mid-run re-import
        # (both routine on these feeds — parallel-human-operators,
        # feed-reimport-id-rotation) can shift a STILL-LIVE offer outside the
        # window, and the window scan would falsely conclude "gone" → a phantom
        # creation (2026-08-06 review, CRITICAL). page_hint only makes the LOCATE
        # cheap (find the row without a deep sequential scan); proving it left the
        # feed still requires covering the whole feed under both id and URL keys.
        gone, fresh_index, fresh_by_url = self._verify_gone(
            entry["offer_id"], str(candidate["offer"].get("url") or ""),
            ctx["store_id"], ctx["feed_page"], ctx["available"], ctx["max_pages"],
            search_locate=ctx.get("search_locate", False),
        )
        if fresh_index is not None:
            ctx["index"].clear()
            ctx["index"].update(fresh_index)
            ctx["by_url"].clear()
            ctx["by_url"].update(fresh_by_url)
        entry["submitted"] = gone
        mode = ctx["available"]
        entry["post_save"] = (
            f"gone from feed (available={mode})" if gone
            else f"STILL in feed (available={mode}) — FAILED"
        )
        return gone
