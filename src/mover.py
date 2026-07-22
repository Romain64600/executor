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
    FEED_UNREADABLE_EXCS,
    _SubmitterBase,
    _row_check,
    _url_key,
)

# MV7 (review 2026-07-21): the native Apply POST reloads the source page; let it
# commit before the verify re-scan navigates away, or the in-flight move is raced.
POST_APPLY_SETTLE_S = 2.0

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
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "aborted": None, "stopped": None, "feed_offers": 0,
            "move_attempts": 0, "moved": 0, "plan": [],
            "source_feed_page": source_feed_page,
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
        try:
            index, by_url = self._index_feed(store_id, source_feed_page, available, max_pages)
        except FEED_UNREADABLE_EXCS as exc:
            self._log("aborted", reason=f"source feed index scan failed closed: {exc}")
            result["aborted"] = "feed_unreadable"
            return result
        result["feed_offers"] = len(index)
        self._log("feed_indexed", offers=len(index))
        ctx = {"store_id": store_id, "feed_page": source_feed_page,
               "available": available, "max_pages": max_pages,
               "index": index, "by_url": by_url}

        for spec in plan:
            if self.write_mode and limit is not None and result["move_attempts"] >= limit:
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
            if self.offer_pacer is not None:
                self.offer_pacer.wait()

        if self.logger is not None:
            if self.page_pacer is not None or self.offer_pacer is not None:
                self._log("pacing",
                          pages=self.page_pacer.snapshot() if self.page_pacer else None,
                          offers=self.offer_pacer.snapshot() if self.offer_pacer else None)
            self.logger.log_guard(self.guard.snapshot())
        return result

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


class DryRunMover(_MoverBase):
    """Plan the move: locate the row + confirm it is selectable. No write."""

    write_mode = False
    event_name = "dry_run_move"

    def _move(self, entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
        self.session.navigate(entry["page_url"])  # default 3.0 s — bulk form interactive
        ok, reason = self._reverify_row(entry)  # MV1/SC5 even in dry-run
        if not ok:
            entry["ready"] = False
            entry["selectable"] = False
            entry["blocker"] = reason
            self._log(self.event_name, offer_id=entry["offer_id"], selectable=False, blocker=reason)
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

    def _move(self, entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
        target_id = entry["target_list_id"]
        self.session.navigate(entry["page_url"])  # 3.0 s: bulk form must be interactive

        # MV1/SC5: re-confirm this is still the plan's offer on the fresh page
        # before touching anything — a re-import can have re-ided the row.
        ok, reason = self._reverify_row(entry)
        if not ok:
            entry["ready"] = False
            entry["blocker"] = reason
            self._log("move_blocked", offer_id=entry["offer_id"], reason=reason)
            return False
        current_id = entry["current_offer_id"]  # may have been relocated by URL

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

        # Post-verify: the ONLY success signal — the offer left the SOURCE list
        # (MV12, Romain 2026-07-21: "gone from source" is the proof; we do NOT
        # confirm arrival on the target list, so `moved` means exactly "left the
        # source", nothing about the destination). Same discipline as the submit's
        # "gone from feed"; a re-import that re-ids the still-present offer is
        # caught because _verify_gone checks BOTH the id AND the merchant URL.
        gone, fresh_index, fresh_by_url = self._verify_gone(
            current_id, entry.get("url"), ctx["store_id"], ctx["feed_page"],
            ctx["available"], ctx["max_pages"])
        entry["moved"] = bool(gone)
        entry["post_verify"] = "gone from source list" if gone else (
            "STILL on source list after Apply — move NOT confirmed")
        if gone and fresh_index is not None:
            # reuse the proven fresh scan to locate the next offer (reflow-safe)
            ctx["index"], ctx["by_url"] = fresh_index, fresh_by_url
        self._log("move_verified", offer_id=entry["offer_id"], moved=entry["moved"])
        return bool(gone)
