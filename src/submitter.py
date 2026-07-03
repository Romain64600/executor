"""Stage 4 — DRY-RUN submitter (no writes).

For each approved offer, it rehearses the submit flow read-only: pre-flight login
check, refresh + locate the exact current row, open the modal, verify the modal
context and select names, and report exactly what it *would* set and click — but it
never fills a form or clicks "Create offer" (that capability does not exist in this
build).

Fail-closed per Romain's decisions (SUBMITTER_SPEC §6/§11): one attempt per offer;
on failure log + skip + continue; stop the whole run after 10 consecutive failures.
The flow depends only on a ``session`` object, so it is unit-testable with a fake.
"""

from __future__ import annotations

import time
from typing import Any

from src.extractor import DEFAULT_FEED_PAGE, feed_url
from src.run_log import RunLogger
from src.step_guard import StepGuard


class DryRunSubmitter:
    def __init__(self, session: Any, *, guard: StepGuard | None = None, logger: RunLogger | None = None) -> None:
        self.session = session
        self.guard = guard or StepGuard(
            max_attempts_per_signature=1,
            max_failures_per_signature=2,   # a single per-offer failure must not global-block
            max_consecutive_failures=10,    # stop the run after 10 consecutive failures
            max_failures_per_task=10 ** 9,  # disable the total-budget rule; only "10 in a row" stops
        )
        self.logger = logger

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, **fields)

    def _index_feed(self, store_id, feed_page, available, max_pages) -> dict[str, str]:
        index: dict[str, str] = {}
        empty = 0
        for page in range(1, max_pages + 1):
            url = feed_url(store_id, page=page, feed_page=feed_page, available=available)
            self.session.navigate(url)
            ids = self.session.page_offer_ids()
            if not ids:
                break
            new = 0
            for offer_id in ids:
                if offer_id not in index:
                    index[offer_id] = url
                    new += 1
            if new == 0:
                empty += 1
                if empty >= 2:
                    break
            else:
                empty = 0
        return index

    def _dry_one(self, candidate: dict[str, Any], offer_id: str, index: dict[str, str]) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "offer_id": offer_id,
            "merchant_title": candidate["offer"]["name"],
            "aks_url": candidate["aks_url"],
            "region_id": candidate["region"]["id"],
            "edition_id": candidate["edition"]["id"],
            "ready": False,
        }
        if offer_id not in index:
            entry["blocker"] = "offer not in current feed"
            return entry
        self.session.navigate(index[offer_id])  # refresh the row's page
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
        entry["would_submit"] = (
            f"set {region_select}={entry['region_id']}, "
            f"{edition_select}={entry['edition_id']}, "
            "click .button-primary (NOT clicked — dry-run)"
        )
        return entry

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
        pace: float = 0.5,
    ) -> dict[str, Any]:
        # Pre-flight login check (SUBMITTER_SPEC §2.4).
        self.session.navigate(feed_url(store_id, feed_page=feed_page, available=available))
        if self.session.is_login_page():
            self._log("aborted", reason="not logged in (wp-login)")
            return {"aborted": "not_logged_in", "stopped": None, "feed_offers": 0, "plan": []}

        self.guard.start_task(run_id)
        index = self._index_feed(store_id, feed_page, available, max_pages)
        self._log("feed_indexed", offers=len(index))

        plan: list[dict[str, Any]] = []
        stopped: str | None = None
        for candidate in approved:
            offer_id = str(candidate["offer"]["offer_id"])
            signature = f"submit:{offer_id}"
            if not self.guard.check("submit", signature).allowed:
                stopped = "guard_blocked"
                self._log("run_stopped", reason=stopped)
                break

            entry = self._dry_one(candidate, offer_id, index)
            self.guard.record_result("submit", signature, entry["ready"], detail=entry.get("blocker", ""))
            self._log("dry_run_offer", offer_id=offer_id, ready=entry["ready"], blocker=entry.get("blocker"))
            if not entry["ready"]:
                self._log("skip", offer_id=offer_id, reason=entry.get("blocker"))
            plan.append(entry)

            if self.guard.blocked:
                stopped = "ten_consecutive_failures"
                self._log("run_stopped", reason=stopped)
                break
            if pace:
                time.sleep(pace)

        if self.logger is not None:
            self.logger.log_guard(self.guard.snapshot())
        return {"aborted": None, "stopped": stopped, "feed_offers": len(index), "plan": plan}
