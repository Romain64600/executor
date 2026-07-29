"""Move-to-List writer (brique B) — the submitter's sibling for feed triage.

For each entry of a validated move plan, on the SOURCE list feed:

  refresh feed → locate the exact current row (id, then merchant-URL fallback —
  `_url_key`, ids rotate on re-import) → verify title/URL → resolve the target
  list LABEL → id LIVE from the bulk[list] options (ids drift, AKS_LISTS.md) →
  TRUSTED-click the row checkbox to register it → set bulk[list] → TRUSTED-click
  Apply (native POST) → **post-verify: the offer left the source list** at
  refresh — the ONLY success signal, the exact analogue of the submit's "gone
  from feed" (docs/AKS_LISTS.md, EXECUTOR_RULES §13).

Fail-closed throughout: dry-run by default, no catalog/region here, a scripted
change is never trusted (isTrusted wall), an unproven feed scan aborts loudly
rather than standing in for "gone", and a *garder* / still-`suggested`
disposition is never in a plan (filtered by the builder, `move_plan.py`).
"""

from __future__ import annotations

import re
import time
from typing import Any

from src.extractor import DEFAULT_FEED_PAGE, feed_url
from src.submitter import (  # reuse the proven, audited feed machinery
    CdpCommandError,
    FEED_UNREADABLE_EXCS,
    FeedScanError,
    NotLoggedInError,
    StopRequested,
    _SubmitterBase,
    _row_check,
    _url_key,
)

# Robustness (2026-07-29): a batch spanning many stores runs for a long time and
# AKS can hiccup / rate-limit a scan mid-run. A read-only feed scan is safe to
# RETRY (even after an Apply — the Apply already committed), so a bounded retry
# on a TRANSIENT feed/CDP error keeps one blip from aborting the whole batch. A
# NotLoggedInError is NOT retried (the session is gone — hammering is pointless).
FEED_RETRY_ATTEMPTS = 3
FEED_RETRY_PAUSE_S = 10.0

# MV7 (review 2026-07-21): the native Apply POST reloads the source page; let it
# commit before the verify re-scan navigates away, or the in-flight move is raced.
POST_APPLY_SETTLE_S = 2.0

# P1.5 (2026-07-28): the group RV2 scan walks the TARGET list, which GROWS as
# offers move into it (account can reach thousands of pages), and must reach a
# proven end when an offer is genuinely missing — so its max_pages is decoupled
# from the (smaller) source feed's. The scan stops early once every group URL is
# seen, so this generous cap only bites on the missing-offer / not-arrived path.
TARGET_SCAN_MAX_PAGES = 2000

# RV3 (review 2026-07-22): the move/proof mechanics version. A batch authorization
# granted by a canary is bound to this — bump it whenever the move or its proof
# changes, so an authorization from an older mechanism no longer covers a batch.
#   1  initial writer (trusted checkbox click — proved fragile, superseded)
#   2  registration by hidden injection + RV2 target-presence proof
#   3  reflow-resilient fresh-locate right before the move (canary 2026-07-22)
#   4  batched Move-to-List: MANY bulk[item][] serialized into ONE Apply, group-
#      verified (P2, 2026-07-28). A distinct many-item mechanism a cap-1 canary
#      cannot prove, so the version bumps: a v3 authorization no longer covers a
#      run, and a --mode safe BATCH additionally requires a multi-item canary
#      (an Apply that actually carried >=2 items — move_auth `multi_item_proven`).
MOVER_VERSION = "4"

# The source list a run scanned — parsed from raw.json's source_url
# (…&page=aks-merchant-feeds-<id>). Default 9 = "AKS Feeds" (pending queue).
_FEED_PAGE_RE = re.compile(r"aks-merchant-feeds-\d+")


def source_feed_page(source_url: str | None) -> str:
    """The ``aks-merchant-feeds-<id>`` page of a run's source_url, or the default."""

    if source_url:
        m = _FEED_PAGE_RE.search(source_url)
        if m:
            return m.group(0)
    return DEFAULT_FEED_PAGE


def _norm_label(text: str) -> str:
    """Compare list labels loosely: drop a leading 'Move to ', lowercase, squeeze."""

    text = re.sub(r"^\s*move to\s+", "", (text or "").strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip().lower()


def resolve_list_id(
    label: str, options: list[dict[str, str]]
) -> dict[str, Any] | None:
    """Resolve a target list to its LIVE id, by LABEL only (ids drift).

    Returns ``{"id", "text"}`` for a UNIQUE label match, else None (fail-closed —
    the caller blocks). MV5 (review 2026-07-21): a non-unique match is ambiguous
    and must NOT silently pick the first (the region/edition ``resolve_catalog_id``
    requires uniqueness too). The stored id is deliberately not consulted — a
    drifted stored id would resolve to the wrong live list (AKS_LISTS.md)."""

    want = _norm_label(label)
    if not want:
        return None
    matches = [{"id": str(o.get("value", "")), "text": o.get("text", "")}
               for o in options if _norm_label(o.get("text", "")) == want]
    return matches[0] if len(matches) == 1 else None


class _MoverBase(_SubmitterBase):
    """Shared move loop. Subclasses set ``write_mode`` and implement ``_move``."""

    write_mode = False
    event_name = "dry_run_move"

    def _move(self, entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
        raise NotImplementedError

    def run(
        self,
        *,
        run_id: str,
        store_id: str | int,
        plan: list[dict[str, Any]],
        source_feed_page: str = DEFAULT_FEED_PAGE,
        available: str = "all",
        max_pages: int = 40,
        limit: int | None = None,
        should_stop=None,
        batch: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "aborted": None, "stopped": None, "feed_offers": 0,
            "move_attempts": 0, "moved": 0, "plan": [],
            "source_feed_page": source_feed_page,
            # Largest single-Apply item count of this run (batched path only) — the
            # multi-item proof a --mode safe batch authorization requires. 0 = no
            # batched Apply fired (per-offer path, or nothing moved).
            "max_apply_items": 0,
        }

        # Pre-flight login check on the SOURCE list.
        self.session.navigate(feed_url(store_id, feed_page=source_feed_page, available=available))
        if self.session.is_login_page():
            self._log("aborted", reason="not logged in (wp-login)")
            result["aborted"] = "not_logged_in"
            return result

        # Resolve every target list LABEL -> id LIVE from the bulk[list] options.
        # Fail-closed: one unresolvable label aborts before any write — a wrong
        # list id would misfile the offer (the region/edition-drift lesson).
        options = self.session.list_options()
        result["list_options_count"] = len(options)
        for e in plan:
            resolved = resolve_list_id(e.get("target_list_label", ""), options)
            if resolved is None:
                self._log("aborted", reason="target list not in live bulk[list] options",
                          offer_id=e.get("offer_id"), label=e.get("target_list_label"))
                result["aborted"] = "target_list_unresolved"
                result["unresolved"] = {"offer_id": e.get("offer_id"),
                                        "label": e.get("target_list_label")}
                return result
            e["resolved_list_id"] = resolved["id"]
            e["resolved_list_text"] = resolved["text"]

        self.guard.start_task(run_id)
        # Arm the cooperative stop ONLY for the initial index (a slow, read-only
        # scan — the phase a full-list dry-run spends minutes in). It is cleared
        # before any offer is touched, so a move is never interrupted mid-flight.
        self._should_stop = should_stop
        try:
            index, by_url = self._index_feed(store_id, source_feed_page, available, max_pages)
        except StopRequested as exc:
            self._log("run_stopped", reason="operator_stop", detail=str(exc))
            result["stopped"] = "operator_stop"
            return result
        except FEED_UNREADABLE_EXCS as exc:
            self._log("aborted", reason=f"source feed index scan failed closed: {exc}")
            result["aborted"] = "feed_unreadable"
            return result
        finally:
            self._should_stop = None  # per-offer scans are never interruptible
        result["feed_offers"] = len(index)
        self._log("feed_indexed", offers=len(index))
        ctx = {"store_id": store_id, "feed_page": source_feed_page,
               "available": available, "max_pages": max_pages,
               "index": index, "by_url": by_url}

        # P1 (2026-07-28): ``batch`` groups the plan by source page and moves a
        # whole page in ONE Apply, verifying the group at once — the ~50-100x
        # speedup. Gated to the real write path; the per-offer path (dry-run,
        # canary, and any non-batched run) is unchanged.
        if batch and self.write_mode:
            self._drive_batched(plan, ctx, result, limit, should_stop)
        else:
            self._drive_per_offer(plan, ctx, result, limit, should_stop)

        if self.logger is not None:
            if self.page_pacer is not None or self.offer_pacer is not None:
                self._log("pacing",
                          pages=self.page_pacer.snapshot() if self.page_pacer else None,
                          offers=self.offer_pacer.snapshot() if self.offer_pacer else None)
            self.logger.log_guard(self.guard.snapshot())
        return result

    def _drive_per_offer(self, plan, ctx, result, limit, should_stop):
        """The proven one-offer-per-Apply loop (dry-run, canary, non-batched)."""

        store_id = ctx["store_id"]
        for spec in plan:
            # Cooperative stop BETWEEN offers — a safe point (no move in flight).
            if should_stop is not None and should_stop():
                result["stopped"] = "operator_stop"
                self._log("run_stopped", reason=result["stopped"])
                break
            # The limit counts SUCCESSFUL moves, not attempts: a canary must keep
            # trying until it actually MOVES one (a dud first offer — e.g. one
            # whose Apply doesn't take — must not consume the canary). Flailing is
            # still bounded by the 10-consecutive-failure breaker below.
            if self.write_mode and limit is not None and result["moved"] >= limit:
                result["stopped"] = "limit_reached"
                self._log("run_stopped", reason=result["stopped"])
                break
            offer_id = str(spec["offer_id"])
            signature = f"move:{offer_id}"
            if not self.guard.check("move", signature).allowed:
                result["stopped"] = "guard_blocked"
                self._log("run_stopped", reason=result["stopped"])
                break

            entry: dict[str, Any] = {
                "offer_id": offer_id,
                "name": spec.get("name", ""),
                "url": spec.get("url", ""),
                "store_id": str(store_id),
                "target_list_label": spec.get("target_list_label", ""),
                "target_list_id": spec.get("resolved_list_id", ""),
                "ready": False,
                "moved": False,
            }
            candidate = {"offer": {
                "offer_id": offer_id, "name": spec.get("name", ""),
                "url": spec.get("url", ""), "store_id": str(store_id),
            }}
            # MV2/MV8: "absent" (idempotent already-moved — a legitimate SKIP)
            # vs "present-but-contradicts" (a real doubt → fail-closed via the
            # guard), and absence is PROVEN by a targeted full scan (the
            # start-of-run index can early-terminate, so a locate-miss alone is
            # not proof the offer left the source list).
            status, payload = self._resolve_location(candidate, offer_id, ctx)
            if status == "skip":
                entry["skipped"] = payload
                self._log("move_skipped", offer_id=offer_id, reason=payload)
                result["plan"].append(entry)
                continue
            if status == "block":
                entry["blocker"] = payload
                self._log("move_blocked", offer_id=offer_id, reason=payload)
                self.guard.record_result("move", signature, False, detail=payload)
                result["plan"].append(entry)
                if self.guard.snapshot().get("blocked"):
                    result["stopped"] = "ten_consecutive_failures"
                    self._log("run_stopped", reason=result["stopped"])
                    break
                continue
            located = payload
            entry["current_offer_id"] = located["offer_id"]
            entry["page_url"] = located["page_url"]
            if located.get("located_by") == "url":
                self._log("row_relocated", plan_offer_id=offer_id,
                          current_offer_id=located["offer_id"], url=spec.get("url"),
                          page_url=located["page_url"])

            success = False
            unreadable: str | None = None
            try:
                entry["ready"] = True
                success = self._move(entry, ctx)
            except FEED_UNREADABLE_EXCS as exc:
                unreadable = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # MV11: any unexpected write-step error is
                # fail-closed — offer state UNKNOWN, keep the artefact, stop.
                unreadable = f"unexpected {type(exc).__name__}: {exc}"
            if unreadable is not None:
                success = False
                entry["post_verify"] = (
                    "feed/CDP/write error — offer state UNKNOWN, verify the move by "
                    f"hand on AKS before any retry: {unreadable}")

            if self.write_mode and entry.get("ready"):
                result["move_attempts"] += 1
                if entry.get("moved"):
                    result["moved"] += 1
            self.guard.record_result(
                "move", signature, success,
                detail=entry.get("blocker", "") or entry.get("post_verify", ""))
            result["plan"].append(entry)

            if unreadable is not None:
                result["aborted"] = "feed_unreadable_mid_run"
                self._log("run_stopped", reason=result["aborted"], detail=unreadable)
                break
            # MV9: honour the 10-consecutive-failure breaker even when the 10th
            # failure is the last plan entry (no next check() to catch it).
            if self.guard.snapshot().get("blocked"):
                result["stopped"] = "ten_consecutive_failures"
                self._log("run_stopped", reason=result["stopped"])
                break
            # Stop as soon as the target number of MOVES is reached (deterministic
            # even when the winning move is the last plan entry) — the canary
            # stops right after it actually moves one.
            if self.write_mode and limit is not None and result["moved"] >= limit:
                result["stopped"] = "limit_reached"
                self._log("run_stopped", reason=result["stopped"])
                break
            if self.offer_pacer is not None:
                self.offer_pacer.wait()

    def _resolve_location(
        self, candidate: dict[str, Any], offer_id: str, ctx: dict[str, Any]
    ) -> tuple[str, Any]:
        """('proceed', located) | ('skip', reason) | ('block', reason).

        MV8: an "absent per the start index" miss is re-proven by a targeted scan
        (``stop_on`` disables the early-terminate and runs to a proven feed end,
        raising FeedScanError if coverage is unprovable) before it is trusted as
        "already moved". A present-but-contradicting row is never a skip."""

        located = self._locate_row(candidate, offer_id, ctx["index"], ctx["by_url"])
        if not located.get("blocker"):
            return "proceed", located
        if "not in current feed" not in located["blocker"]:
            return "block", located["blocker"]  # identity contradiction
        url = _url_key(str(candidate["offer"].get("url") or ""))
        index, by_url, found = self._scan_feed(
            ctx["store_id"], ctx["feed_page"], ctx["available"], ctx["max_pages"],
            stop_on=offer_id, stop_on_url=url or None)
        if not found:
            return "skip", "not on source list (already moved?) — proven by full scan"
        ctx["index"], ctx["by_url"] = index, by_url
        relocated = self._locate_row(candidate, offer_id, index, by_url)
        if relocated.get("blocker"):
            return "block", relocated["blocker"]
        return "proceed", relocated

    def _relocate_before_move(self, entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
        """Fresh-locate the offer on the SOURCE feed right before the move, then
        confirm identity on that page. A re-import/reflow can move the row to
        another page/id between the start-of-run index and now (canary 2026-07-22:
        TurboTax reflowed off its indexed page → MV1 blocked). Scanning by URL
        (stable) here makes the move resilient to that. Updates
        entry.page_url/current_offer_id; returns False (entry.blocker set) if the
        offer is gone from the source feed or its identity contradicts."""

        url = _url_key(str(entry.get("url") or ""))
        if not url:
            entry["blocker"] = "no merchant URL to relocate before move"
            return False
        _, by_url, found = self._scan_feed(
            ctx["store_id"], ctx["feed_page"], ctx["available"], ctx["max_pages"],
            stop_on_url=url)
        row = by_url.get(url) if found else None
        if row is None:
            entry["blocker"] = "offer not on source feed at move time (moved / re-imported away)"
            return False
        entry["current_offer_id"] = row["offer_id"]
        entry["page_url"] = row["page_url"]
        self.session.navigate(entry["page_url"])  # settle 3.0 for the interactive bulk form
        ok, reason = self._reverify_row(entry)
        if not ok:
            entry["blocker"] = reason
            return False
        return True

    def _reverify_row(self, entry: dict[str, Any]) -> tuple[bool, str]:
        """MV1 (SC5): on the FRESH page, confirm the row at current_offer_id is
        still the plan's offer (name+URL) before any write — a mid-run re-import
        can reassign that id to a DIFFERENT product. Relocates by URL on this page
        if the id vanished; returns (ok, reason). ``check_price=False``: a live
        feed reprices between extract and move (the submitter's rule)."""

        current_id = entry["current_offer_id"]
        candidate = {"offer": {"offer_id": current_id, "name": entry["name"],
                               "url": entry["url"], "store_id": entry.get("store_id", "")}}
        rows = {str(r.get("id")): r for r in self.session.page_offer_rows()}
        row = rows.get(current_id)
        if row is None:
            url = _url_key(str(entry.get("url") or ""))
            match = next((r for r in rows.values()
                          if url and _url_key(str(r.get("url", ""))) == url), None)
            if match is None:
                return False, "row id vanished from the page (re-import?) — URL not here either"
            entry["current_offer_id"] = str(match.get("id"))
            row = match
        mismatches, _ = _row_check(row, candidate, check_price=False)
        if mismatches:
            return False, f"fresh-page identity mismatch ({', '.join(mismatches)}) — NOT moving"
        return True, ""

    def _new_entry(self, spec: dict[str, Any], store_id: str | int) -> dict[str, Any]:
        """A fresh plan-entry dict (the batched path's analogue of the inline one
        the per-offer loop builds) — same shape, so the writer/ledger read it the
        same way."""

        return {
            "offer_id": str(spec["offer_id"]),
            "name": spec.get("name", ""),
            "url": spec.get("url", ""),
            "store_id": str(store_id),
            "target_list_label": spec.get("target_list_label", ""),
            "target_list_id": spec.get("resolved_list_id", ""),
            "ready": False,
            "moved": False,
        }

    def _full_source_scan(self, ctx: dict[str, Any]
                          ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        """A source-feed scan walked to a PROVEN end-of-feed (``full_coverage`` —
        no 2-empty early terminate), so an id/URL ABSENT from the returned maps
        genuinely left the feed: the set-wise analogue of ``_verify_gone``'s
        stop_on proof, for a whole group at once. Raises FeedScanError
        (fail-closed) when coverage cannot be proven."""

        index, by_url, _ = self._scan_feed(
            ctx["store_id"], ctx["feed_page"], ctx["available"], ctx["max_pages"],
            full_coverage=True)
        return index, by_url


class DryRunMover(_MoverBase):
    """Plan the move: locate the row + confirm it is selectable. No write."""

    write_mode = False
    event_name = "dry_run_move"

    def _move(self, entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
        # Same fresh-locate + identity re-check as the real move (reflow-resilient).
        if not self._relocate_before_move(entry, ctx):
            entry["ready"] = False
            entry["selectable"] = False
            self._log(self.event_name, offer_id=entry["offer_id"], selectable=False,
                      blocker=entry.get("blocker"))
            return False
        current_id = entry["current_offer_id"]
        present = self.session.bulk_row_present(current_id)
        entry["selectable"] = bool(present.get("checkbox") and present.get("bulk_form"))
        if not entry["selectable"]:
            entry["ready"] = False
            entry["blocker"] = (
                f"row not selectable on {entry['page_url']} "
                f"(checkbox={present.get('checkbox')}, bulk_form={present.get('bulk_form')})"
            )
        else:
            entry["would_move_to"] = f"{entry['target_list_id']} ({entry['target_list_label']})"
        self._log(self.event_name, offer_id=entry["offer_id"],
                  current_offer_id=current_id, selectable=entry["selectable"],
                  target_list_id=entry["target_list_id"])
        # MV4: success = located + selectable, so a >10-offer dry-run does not
        # self-block the guard (the submitter's DryRunSubmitter records success too).
        return bool(entry.get("selectable"))


class Mover(_MoverBase):
    """REAL Move-to-List: trusted checkbox → set bulk[list] → trusted Apply →
    post-verify the offer left the source list. Instantiated only under go."""

    write_mode = True
    event_name = "move_offer"
    post_apply_settle = POST_APPLY_SETTLE_S  # tests patch to 0
    feed_retry_attempts = FEED_RETRY_ATTEMPTS
    feed_retry_pause = FEED_RETRY_PAUSE_S     # tests patch to 0

    def _scan_retry(self, fn, *, what: str):
        """Run a read-only scan ``fn`` (source or target), retrying a TRANSIENT
        feed/CDP error a bounded number of times before giving up — so one AKS
        blip / rate-limit hiccup does not abort a long multi-store batch. A
        NotLoggedInError is re-raised immediately (session gone). Read-only, so
        safe to retry even when called after an Apply has fired."""

        last: Exception | None = None
        for attempt in range(1, self.feed_retry_attempts + 1):
            try:
                return fn()
            except NotLoggedInError:
                raise
            except (FeedScanError, CdpCommandError) as exc:
                last = exc
                if attempt < self.feed_retry_attempts:
                    self._log("feed_scan_retry", what=what, attempt=attempt,
                              error=f"{type(exc).__name__}: {exc}")
                    if self.feed_retry_pause:
                        time.sleep(self.feed_retry_pause)
        raise last  # type: ignore[misc]

    def _move(self, entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
        target_id = entry["target_list_id"]
        # Fresh-locate + identity re-check on the source feed right before the
        # move (MV1/SC5 + reflow-resilience) — never trust a page/id fixed at the
        # start-of-run index.
        if not self._relocate_before_move(entry, ctx):
            entry["ready"] = False
            self._log("move_blocked", offer_id=entry["offer_id"], reason=entry.get("blocker"))
            return False
        current_id = entry["current_offer_id"]

        present = self.session.bulk_row_present(current_id)
        if not (present.get("checkbox") and present.get("bulk_form")):
            entry["ready"] = False
            entry["blocker"] = "row/bulk-form not present at move time"
            self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
            return False

        reg = self.session.register_row(current_id)
        entry["register"] = {"method": reg.get("method"),
                             "registered": reg.get("registered")}
        if not reg.get("registered"):
            entry["blocker"] = "bulk[item][] registration failed — nothing submitted"
            self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
            return False

        set_value = self.session.set_bulk_list(target_id)
        entry["bulk_list_set"] = set_value
        if set_value != str(target_id):
            entry["blocker"] = f"bulk[list] reads {set_value!r} (target {target_id!r})"
            self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
            return False

        apply_click = self.session.click_apply()
        entry["apply"] = apply_click.get("status")
        if apply_click.get("status") != "CLICKED":
            entry["blocker"] = "Apply not clicked — move not submitted"
            self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
            return False
        self._log("move_submitted", offer_id=entry["offer_id"],
                  current_offer_id=current_id, target_list_id=target_id)

        # MV7: let the native Apply POST commit (it reloads the source page)
        # before the verify re-scan navigates, so we never race the in-flight move.
        if self.post_apply_settle:
            time.sleep(self.post_apply_settle)

        # Post-verify part 1: the offer left the SOURCE list. _verify_gone checks
        # BOTH the id AND the merchant URL, so a re-import that re-ids the still-
        # present offer is caught (no false "gone").
        gone, fresh_index, fresh_by_url = self._verify_gone(
            current_id, entry.get("url"), ctx["store_id"], ctx["feed_page"],
            ctx["available"], ctx["max_pages"])
        entry["gone_from_source"] = bool(gone)
        if gone and fresh_index is not None:
            ctx["index"], ctx["by_url"] = fresh_index, fresh_by_url  # reflow-safe next locate
        if not gone:
            entry["moved"] = False
            entry["post_verify"] = "STILL on source list after Apply — move NOT confirmed"
            self._log("move_verified", offer_id=entry["offer_id"], moved=False)
            return False

        # Post-verify part 2 (RV2, review 2026-07-22): confirm the offer ARRIVED
        # on the TARGET list. Gone-from-source alone would let a parallel
        # operator's move/delete register as our success — insufficient for a
        # batch. Present = found by merchant URL on feed_page=<target list>.
        on_target = self._verify_on_target(
            entry.get("url"), ctx["store_id"], target_id, ctx["available"], ctx["max_pages"])
        entry["on_target"] = bool(on_target)
        entry["moved"] = bool(on_target)
        entry["post_verify"] = ("gone from source + present on target list" if on_target
                                else "left source but NOT found on target list — verify by hand")
        self._log("move_verified", offer_id=entry["offer_id"],
                  moved=entry["moved"], on_target=on_target)
        return bool(on_target)

    def _verify_on_target(self, url: str, store_id: str | int, target_list_id: str,
                          available: str, max_pages: int) -> bool:
        """RV2: is the offer present on the target list (by stable merchant URL)?

        A scan of ``feed_page=aks-merchant-feeds-<target>`` stopping on the URL —
        an unprovable scan (max_pages hit) raises FeedScanError (fail-closed,
        the caller marks the offer UNKNOWN), never a silent "not present"."""

        key = _url_key(str(url or ""))
        if not key:
            return False
        target_page = "aks-merchant-feeds-%s" % str(target_list_id)
        _, _, found = self._scan_feed(store_id, target_page, available, max_pages,
                                      stop_on_url=key)
        return bool(found)

    def _verify_group_on_target(self, urls, target_id, ctx: dict[str, Any]) -> "set[str]":
        """RV2 for a whole group in ONE target-list scan (P1.5, 2026-07-28):
        scan ``feed_page=aks-merchant-feeds-<target>`` collecting which of the
        group's merchant URLs are present, stopping as soon as EVERY one is seen
        (or a proven end). Returns the set of ``_url_key``s actually on the target
        list. This replaces K per-offer ``_verify_on_target`` stop_on scans with
        ONE scan per group — decisive when the target list is large (account's
        list is ~15k rows, so a per-offer scan cost K× a ~150-page walk).

        Fail-closed: an unprovable scan (max_pages hit with the nav advertising
        more) raises FeedScanError, exactly like the per-offer proof — the caller
        marks the whole in-flight group UNKNOWN. ``max_pages`` is decoupled from
        the source feed's (the growing target list can be far longer); the
        early-stop means the generous cap only bites when an offer never arrived."""

        want = {_url_key(str(u)) for u in urls if u}
        if not want:
            return set()
        target_page = "aks-merchant-feeds-%s" % str(target_id)
        max_pages = max(int(ctx["max_pages"]), TARGET_SCAN_MAX_PAGES)
        _, by_url, _ = self._scan_feed(
            ctx["store_id"], target_page, ctx["available"], max_pages, stop_on_urls=want)
        return want & by_url.keys()

    # ------------------------------------------------------------------ batched
    def _drive_batched(self, plan, ctx, result, limit, should_stop) -> None:
        """Batched Move-to-List (P1, 2026-07-28): register MANY offers on one
        source page, fire ONE Apply, verify the whole GROUP at once — the
        ~50-100x speedup (``bulk[item][]`` is repeatable; the native Apply
        serializes the whole form). Safe by construction, per the 2026-07-28
        simplification safety review:

          * group by each offer's CURRENT source page and RE-SCAN the source feed
            fresh before every group — each Apply empties the source list and
            reflows later pages forward (the mover causes its own reflow), so a
            page fixed at index time goes stale;
          * per-offer fresh-page identity re-check (name+URL) BEFORE registering
            each id (EXECUTOR_RULES §6 / MV1) — never trust the start-of-run row;
          * ``moved`` = (WE registered it into THIS Apply) AND gone-from-source
            (proven full scan, dual key) AND present-on-target (RV2). The group
            verifies right after ITS OWN Apply, so the parallel-operator
            attribution window stays seconds, not the whole batch. Residual
            (identical to the per-offer path in production): if OUR Apply
            silently no-ops for an offer while a parallel operator moves that
            SAME offer to the SAME target within the group's ~seconds window, it
            is credited as ours — bounded by the per-group window, tightening it
            needs a server-side per-POST receipt (out of P1 scope);
          * fail-closed: the source verify walks to a PROVEN end-of-feed, and any
            feed/CDP error after the Apply marks the whole in-flight group
            UNKNOWN (never a silent success);
          * per-offer ``guard.record_result`` feeds the 10-consecutive breaker,
            which bites BEFORE the next group's Apply; ``limit`` bounds moves.

        The cooperative stop is honoured only BETWEEN groups (a safe point) — a
        group's navigate→register→Apply→verify is never cut mid-flight.
        """

        store_id = ctx["store_id"]
        # Working set keyed by stable merchant URL (ids can rotate on re-import;
        # the URL path is the always-safe identity). An offer with no URL cannot
        # be batch-verified set-wise → fail-closed skip, surfaced.
        pending: dict[str, dict[str, Any]] = {}
        for spec in plan:
            entry = self._new_entry(spec, store_id)
            key = _url_key(str(entry["url"]))
            if not key:
                entry["blocker"] = "no merchant URL — cannot batch-verify"
                self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
                result["plan"].append(entry)
                continue
            pending[key] = entry

        while pending:
            if should_stop is not None and should_stop():
                result["stopped"] = "operator_stop"
                self._log("run_stopped", reason=result["stopped"])
                break
            if limit is not None and result["moved"] >= limit:
                result["stopped"] = "limit_reached"
                self._log("run_stopped", reason=result["stopped"])
                break
            if self.guard.snapshot().get("blocked"):
                result["stopped"] = "ten_consecutive_failures"
                self._log("run_stopped", reason=result["stopped"])
                break

            # Fresh PROVEN scan → locate every remaining offer (reflow-safe). A
            # feed/CDP error here is before any write this round; retry a
            # transient blip, else clean abort.
            try:
                index, by_url = self._scan_retry(lambda: self._full_source_scan(ctx),
                                                 what="drive_source")
            except FEED_UNREADABLE_EXCS as exc:
                result["aborted"] = "feed_unreadable"
                self._log("aborted", reason=f"source feed scan failed closed: {exc}")
                break
            ctx["index"], ctx["by_url"] = index, by_url

            # Group remaining offers by (current page, target list). An offer gone
            # from the source is an idempotent skip (already moved) — proven by
            # this full scan, so it is not an unscanned-tail false absence.
            groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for key in list(pending):
                entry = pending[key]
                row = by_url.get(key)
                if row is None:
                    entry["skipped"] = "not on source list (already moved?) — proven by full scan"
                    self._log("move_skipped", offer_id=entry["offer_id"], reason=entry["skipped"])
                    result["plan"].append(entry)
                    del pending[key]
                    continue
                entry["current_offer_id"] = row["offer_id"]
                entry["page_url"] = row["page_url"]
                groups.setdefault((row["page_url"], entry["target_list_id"]), []).append(entry)
            if not groups:
                break  # everything remaining is gone from the source

            # Process ONE group per iteration; the loop re-scans before the next
            # (each Apply reflows the feed, so later groups must be re-located).
            (page_url, target_id), group = next(iter(groups.items()))
            if limit is not None:
                room = max(0, limit - result["moved"])
                group = group[:room]
                if not group:
                    result["stopped"] = "limit_reached"
                    self._log("run_stopped", reason=result["stopped"])
                    break
            self._move_group(page_url, target_id, group, ctx, result, pending)
            if result.get("aborted"):
                break
            if self.offer_pacer is not None:
                self.offer_pacer.wait()

    def _move_group(self, page_url, target_id, group, ctx, result, pending) -> None:
        """Register every offer of ONE source page, fire ONE Apply, verify the
        group. Each handled offer is removed from ``pending``, appended to
        ``result['plan']``, and its per-offer guard result recorded."""

        def _done(entry, success, detail):
            self.guard.record_result("move", f"move:{entry['offer_id']}", success, detail=detail)
            result["plan"].append(entry)
            pending.pop(_url_key(str(entry["url"])), None)

        self.session.navigate(page_url)  # settle 3.0 for the interactive bulk form

        # 1) Per-offer fresh-page identity re-check + register. ONLY cleanly
        #    identity-checked, registered ids enter the Apply (never inject an id
        #    that was not re-verified on THIS rendered page).
        registered: list[tuple[dict[str, Any], str]] = []
        for entry in group:
            signature = f"move:{entry['offer_id']}"
            if not self.guard.check("move", signature).allowed:
                result["stopped"] = "guard_blocked"
                self._log("run_stopped", reason=result["stopped"])
                break  # leftover offers stay in pending, unattempted
            present = self.session.bulk_row_present(entry["current_offer_id"])
            if not (present.get("checkbox") and present.get("bulk_form")):
                entry["ready"] = False
                entry["blocker"] = "row/bulk-form not present at move time"
                self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
                _done(entry, False, entry["blocker"])
                continue
            ok, reason = self._reverify_row(entry)
            if not ok:
                entry["ready"] = False
                entry["blocker"] = reason
                self._log("move_blocked", offer_id=entry["offer_id"], reason=reason)
                _done(entry, False, reason)
                continue
            current_id = entry["current_offer_id"]  # _reverify_row may relocate by URL
            reg = self.session.register_row(current_id)
            entry["register"] = {"method": reg.get("method"), "registered": reg.get("registered")}
            if not reg.get("registered"):
                entry["ready"] = False
                entry["blocker"] = "bulk[item][] registration failed — nothing submitted"
                self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
                _done(entry, False, entry["blocker"])
                continue
            entry["ready"] = True
            registered.append((entry, current_id))

        if not registered:
            return  # all handled/blocked, or the guard stopped the group

        # 2) ONE set_bulk_list + ONE Apply for the whole registered group. A
        #    read-back mismatch or an un-clicked Apply means NOTHING was written
        #    → block the whole group before any verify (bounds a systemic
        #    misroute: no Apply fires if bulk[list] didn't take).
        set_value = self.session.set_bulk_list(target_id)
        if set_value != str(target_id):
            for entry, _cid in registered:
                entry["ready"] = False
                entry["blocker"] = f"bulk[list] reads {set_value!r} (target {target_id!r})"
                self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
                _done(entry, False, entry["blocker"])
            return

        self._log("move_group_submitting", page_url=page_url, count=len(registered),
                  offer_ids=[e["offer_id"] for e, _ in registered], target_list_id=target_id)
        apply_click = self.session.click_apply()
        if apply_click.get("status") != "CLICKED":
            for entry, _cid in registered:
                entry["ready"] = False
                entry["blocker"] = "Apply not clicked — move not submitted"
                self._log("move_blocked", offer_id=entry["offer_id"], reason=entry["blocker"])
                _done(entry, False, entry["blocker"])
            return

        # The Apply fired: every registered id is now IN FLIGHT (written).
        result["move_attempts"] += len(registered)
        result["max_apply_items"] = max(result.get("max_apply_items", 0), len(registered))
        self._log("move_group_submitted", page_url=page_url, count=len(registered),
                  target_list_id=target_id)
        if self.post_apply_settle:
            time.sleep(self.post_apply_settle)

        # 3) Verify the GROUP. Source: ONE proven full scan — an id/URL absent
        #    from it genuinely left the feed (dual key). A feed/CDP error now
        #    leaves the N written offers UNKNOWN (fail-closed), never "moved".
        try:
            index, by_url = self._scan_retry(lambda: self._full_source_scan(ctx),
                                             what="verify_source")
        except FEED_UNREADABLE_EXCS as exc:
            detail = ("feed/CDP error after Apply — offer state UNKNOWN, verify the move by "
                      f"hand on AKS before any retry: {type(exc).__name__}: {exc}")
            for entry, _cid in registered:
                entry["moved"] = False
                entry["post_verify"] = detail
                _done(entry, False, detail)
            result["aborted"] = "feed_unreadable_mid_run"
            self._log("run_stopped", reason=result["aborted"], detail=str(exc))
            return
        ctx["index"], ctx["by_url"] = index, by_url

        # The source scan SUCCEEDED, so gone/still-on-source is deterministic for
        # every registered offer — classify all of them in one pass. A still-on-
        # source offer is a confirmed NOT-moved (never UNKNOWN); the gone ones go
        # to the RV2 target proof.
        to_target: list[tuple[dict[str, Any], str]] = []
        for entry, current_id in registered:
            key = _url_key(str(entry["url"]))
            gone = (key not in by_url) and (current_id not in index)  # dual-key absence
            entry["gone_from_source"] = gone
            if not gone:
                entry["moved"] = False
                entry["post_verify"] = "STILL on source list after Apply — move NOT confirmed"
                self._log("move_verified", offer_id=entry["offer_id"], moved=False)
                _done(entry, False, entry["post_verify"])
            else:
                to_target.append((entry, current_id))

        # RV2 for the whole group in ONE target-list scan (P1.5): which gone
        # offers' URLs are present on the target list, stopping as soon as all are
        # seen. A target-scan error is fail-closed for the WHOLE in-flight group
        # (the Apply already wrote them — none may silently vanish from the
        # plan/guard/ledger), then abort.
        if not to_target:
            return
        try:
            present = self._scan_retry(
                lambda: self._verify_group_on_target(
                    [entry["url"] for entry, _cid in to_target], target_id, ctx),
                what="verify_target")
        except FEED_UNREADABLE_EXCS as exc:
            detail = ("target-list scan error after Apply — offer state UNKNOWN, verify by "
                      f"hand: {type(exc).__name__}: {exc}")
            for entry, _cid in to_target:
                entry["moved"] = False
                entry["post_verify"] = detail
                _done(entry, False, detail)
            result["aborted"] = "feed_unreadable_mid_run"
            self._log("run_stopped", reason=result["aborted"], detail=str(exc))
            return
        for entry, current_id in to_target:
            on_target = _url_key(str(entry["url"])) in present
            entry["on_target"] = on_target
            entry["moved"] = bool(on_target)
            entry["post_verify"] = ("gone from source + present on target list" if on_target
                                    else "left source but NOT found on target list — verify by hand")
            if on_target:
                result["moved"] += 1
            self._log("move_verified", offer_id=entry["offer_id"],
                      moved=entry["moved"], on_target=on_target)
            _done(entry, entry["moved"], entry["post_verify"])
