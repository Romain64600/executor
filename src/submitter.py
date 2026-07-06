"""Stage 4 — submitters (dry-run and real).

Shared flow (`_SubmitterBase`): pre-flight login check, refresh + index the current
feed, locate each approved offer's exact row, open its modal, verify context +
select names.

- `DryRunSubmitter` stops there and reports what it *would* submit — **no writes**.
- `Submitter` (real) additionally fills region/edition and clicks "Create offer",
  then verifies post-save that the offer **disappeared** from the pending feed —
  success = gone (skill S18; never `[data-success]`).

Fail-closed per Romain's decisions (SUBMITTER_SPEC §6): one attempt per offer; on
failure log + skip + continue; stop the run after 10 consecutive failures. The real
submitter defaults to a **canary of 1 write** unless a larger limit is given.
Depends only on a ``session`` object, so both are unit-testable with a fake.
"""

from __future__ import annotations

import time
from typing import Any

from src.extractor import DEFAULT_FEED_PAGE, feed_url
from src.run_log import RunLogger
from src.step_guard import StepGuard


class _SubmitterBase:
    write_mode = False
    event_name = "dry_run_offer"

    def __init__(self, session: Any, *, guard: StepGuard | None = None, logger: RunLogger | None = None) -> None:
        self.session = session
        self.guard = guard or StepGuard(
            max_attempts_per_signature=1,
            max_failures_per_signature=2,
            max_consecutive_failures=10,
            max_failures_per_task=10 ** 9,
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

    def _prepare(self, candidate: dict[str, Any], offer_id: str, index: dict[str, str]) -> dict[str, Any]:
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
        return entry

    def _verify_gone(self, offer_id, store_id, feed_page, available, max_pages) -> bool:
        """Post-save: re-scan the feed; True iff the offer id is no longer present."""

        for page in range(1, max_pages + 1):
            self.session.navigate(feed_url(store_id, page=page, feed_page=feed_page, available=available))
            ids = self.session.page_offer_ids()
            if not ids:
                break
            if offer_id in ids:
                return False
        return True

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
        pace: float = 0.5,
        limit: int | None = None,
    ) -> dict[str, Any]:
        # Pre-flight login check.
        self.session.navigate(feed_url(store_id, feed_page=feed_page, available=available))
        if self.session.is_login_page():
            self._log("aborted", reason="not logged in (wp-login)")
            return {"aborted": "not_logged_in", "stopped": None, "feed_offers": 0, "writes": 0, "plan": []}

        self.guard.start_task(run_id)
        index = self._index_feed(store_id, feed_page, available, max_pages)
        self._log("feed_indexed", offers=len(index))
        ctx = {"store_id": store_id, "feed_page": feed_page, "available": available, "max_pages": max_pages}

        plan: list[dict[str, Any]] = []
        stopped: str | None = None
        writes = 0
        for candidate in approved:
            if self.write_mode and limit is not None and writes >= limit:
                stopped = "limit_reached"
                self._log("run_stopped", reason=stopped)
                break
            offer_id = str(candidate["offer"]["offer_id"])
            signature = f"submit:{offer_id}"
            if not self.guard.check("submit", signature).allowed:
                stopped = "guard_blocked"
                self._log("run_stopped", reason=stopped)
                break

            entry = self._prepare(candidate, offer_id, index)
            success = self._process(entry, candidate, ctx)
            if self.write_mode and entry.get("ready"):
                writes += 1
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

            if self.guard.blocked:
                stopped = "ten_consecutive_failures"
                self._log("run_stopped", reason=stopped)
                break
            if pace and (not self.write_mode or entry.get("ready")):
                time.sleep(pace)

        if self.logger is not None:
            self.logger.log_guard(self.guard.snapshot())
        return {
            "aborted": None,
            "stopped": stopped,
            "feed_offers": len(index),
            "writes": writes if self.write_mode else None,
            "plan": plan,
        }


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
    documented diagnostics. Post-save (offer gone from refreshed pending) remains
    the ONLY success proof in every mode.
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
        gone = self._verify_gone(
            entry["offer_id"], ctx["store_id"], ctx["feed_page"], ctx["available"], ctx["max_pages"]
        )
        entry["submitted"] = gone
        entry["post_save"] = "gone from pending" if gone else "STILL in pending — FAILED"
        return gone
