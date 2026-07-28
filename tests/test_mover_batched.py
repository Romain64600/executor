"""P1 batched Move-to-List (2026-07-28): register MANY offers on one source page,
ONE Apply, verify the group at once. These tests drive the real ``Mover`` with a
FAKE paginated feed that reflows exactly like AKS — each Apply removes the moved
rows from the source list, so later pages shift forward. They lock the safety
properties the simplification safety review required:

  * reflow-safe: a multi-page batch moves EVERY offer (re-scan between Applies),
    and fires ONE Apply per source page — not one per offer (the speedup);
  * per-offer fresh-page identity re-check before register (a changed row is
    blocked, the rest of its group still moves);
  * moved = registered-by-us AND gone-from-source (proven full scan) AND
    present-on-target (RV2) — a swallowed-by-target Apply scores NOT moved;
  * fail-closed: a feed error AFTER the Apply marks the whole in-flight group
    UNKNOWN + aborts, never a silent success;
  * a bulk[list] read-back mismatch blocks the group BEFORE any Apply fires;
  * an already-gone offer is an idempotent skip; --limit caps moves.
"""

import re
import unittest

from src.mover import Mover
from src.step_guard import StepGuard
from src.submitter import _SubmitterBase, _url_key

SRC = "9"          # source list → page aks-merchant-feeds-9
TGT = "8"          # target list (Blacklist)
_FP_RE = re.compile(r"aks-merchant-feeds-(\d+)")
_P_RE = re.compile(r"[?&]p=(\d+)")


def _offer(i, store="38"):
    return {"id": f"o{i}", "url": f"https://m/{i}", "name": f"Game {i}",
            "price": "10", "store_id": store}


def _spec(i):
    o = _offer(i)
    return {"offer_id": o["id"], "name": o["name"], "url": o["url"],
            "target_list_label": "Blacklist"}


class FakeFeed:
    """A paginated source+target feed. ``click_apply`` moves the registered ids
    from the current (source) page's list to the ``bulk[list]`` target — and the
    source list SHRINKS, so the next scan sees the reflowed pagination."""

    def __init__(self, lists, page_size=2, *, fail_register=(), swallow_target=(),
                 bulk_list_lies=False, break_after_apply=False, break_target_scan=False,
                 rename_on_page=None):
        self.lists = {k: [dict(o) for o in v] for k, v in lists.items()}
        self.page_size = page_size
        self.fail_register = set(fail_register)
        self.swallow_target = set(swallow_target)
        self.bulk_list_lies = bulk_list_lies
        self.break_after_apply = break_after_apply
        self.break_target_scan = break_target_scan   # target-list reads unreadable after an Apply
        self.rename_on_page = rename_on_page or {}   # id -> new name (identity churn)
        self._fp = None
        self._page = 1
        self._url = ""
        self._registered = []
        self._bulk_list = ""
        self._broken = False
        self._applied = False
        self.apply_count = 0

    def _read_broken(self):
        return self._broken or (self.break_target_scan and self._applied and self._fp == TGT)

    # -- navigation --
    def navigate(self, url, settle=None):
        self._url = url
        m = _FP_RE.search(url)
        self._fp = m.group(1) if m else None
        pm = _P_RE.search(url)
        self._page = int(pm.group(1)) if pm else 1
        self._registered = []
        self._bulk_list = ""

    def is_login_page(self):
        return False

    def list_options(self):
        return [{"value": TGT, "text": "Blacklist"}, {"value": "21", "text": "Gift cards"}]

    # -- page reads --
    def _cur(self):
        return self.lists.get(self._fp, [])

    def _rows(self):
        s = self.page_size
        rows = self._cur()[(self._page - 1) * s: self._page * s]
        out = []
        for o in rows:
            r = dict(o)
            if o["id"] in self.rename_on_page:
                r["name"] = self.rename_on_page[o["id"]]
            out.append(r)
        return out

    def page_offer_rows(self):
        return [] if self._read_broken() else self._rows()

    def feed_page_state(self):
        if self._read_broken():
            return {"feed_ui": False, "nav_max": 0, "is_login": False, "href": self._url}
        n = len(self._cur())
        nav_max = (n + self.page_size - 1) // self.page_size
        return {"feed_ui": True, "nav_max": nav_max, "is_login": False, "href": self._url}

    # -- bulk form --
    def bulk_row_present(self, offer_id):
        return {"checkbox": offer_id in {o["id"] for o in self._rows()}, "bulk_form": True}

    def register_row(self, offer_id):
        if offer_id in self.fail_register:
            return {"registered": False, "method": "inject", "reason": "test"}
        if offer_id not in self._registered:
            self._registered.append(offer_id)
        return {"registered": True, "method": "inject", "bulk_list_value": self._bulk_list}

    def set_bulk_list(self, v):
        self._bulk_list = str(v)
        return "WRONG" if self.bulk_list_lies else str(v)

    def click_apply(self):
        self.apply_count += 1
        src = self.lists.get(self._fp, [])
        tgt = self.lists.setdefault(self._bulk_list, [])
        moving = [o for o in src if o["id"] in self._registered]
        self.lists[self._fp] = [o for o in src if o["id"] not in self._registered]
        for o in moving:
            if o["id"] not in self.swallow_target:
                tgt.append(o)
        self._registered = []
        self._applied = True
        if self.break_after_apply:
            self._broken = True
        return {"status": "CLICKED"}


def _run(feed, specs, *, limit=None, page_size=None):
    if page_size is not None:
        feed.page_size = page_size
    guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=2,
                      max_consecutive_failures=10, max_failures_per_task=10 ** 9)
    mover = Mover(feed, guard=guard)
    mover.post_apply_settle = 0
    mover.empty_retry_wait_s = 0
    mover.feed_scan_settle = 0
    return mover.run(run_id="t", store_id="38", plan=specs,
                     source_feed_page="aks-merchant-feeds-%s" % SRC,
                     max_pages=20, limit=limit, batch=True)


class BatchedMoverTests(unittest.TestCase):
    def _tgt_ids(self, feed):
        return {o["id"] for o in feed.lists.get(TGT, [])}

    def test_multipage_reflow_moves_all_with_one_apply_per_page(self):
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 5)]}, page_size=2)
        res = _run(feed, [_spec(i) for i in range(1, 5)])
        self.assertEqual(res["moved"], 4)
        self.assertEqual(self._tgt_ids(feed), {"o1", "o2", "o3", "o4"})
        self.assertEqual(feed.lists[SRC], [])                 # source drained
        # 4 offers over 2 pages → 2 Applies (one per page-group), NOT 4.
        self.assertEqual(feed.apply_count, 2)
        self.assertTrue(all(e["moved"] for e in res["plan"]))

    def test_single_page_group_is_one_apply(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["moved"], 2)
        self.assertEqual(feed.apply_count, 1)                 # both in ONE Apply

    def test_identity_mismatch_blocks_only_that_offer(self):
        # o1's row name changed on the fresh page → blocked; o2 still moves.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10,
                        rename_on_page={"o1": "A DIFFERENT GAME"})
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["moved"], 1)
        self.assertEqual(self._tgt_ids(feed), {"o2"})
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertFalse(by_id["o1"]["moved"])
        self.assertIn("identity mismatch", by_id["o1"]["blocker"])
        self.assertTrue(by_id["o2"]["moved"])

    def test_swallowed_by_target_is_not_scored_moved(self):
        # Apply removes o1 from source but it never lands on target → RV2 fails.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10, swallow_target={"o1"})
        res = _run(feed, [_spec(1), _spec(2)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertFalse(by_id["o1"]["moved"])
        self.assertTrue(by_id["o1"]["gone_from_source"])
        self.assertIn("NOT found on target", by_id["o1"]["post_verify"])
        self.assertTrue(by_id["o2"]["moved"])                # o2 unaffected
        self.assertEqual(res["moved"], 1)

    def test_feed_error_after_apply_marks_group_unknown_and_aborts(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10, break_after_apply=True)
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)                    # nothing confirmed
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])       # written but unverifiable

    def test_bulk_list_mismatch_blocks_group_before_any_apply(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10, bulk_list_lies=True)
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["moved"], 0)
        self.assertEqual(feed.apply_count, 0)                # no Apply fired
        self.assertEqual(self._tgt_ids(feed), set())
        for e in res["plan"]:
            self.assertIn("bulk[list] reads", e["blocker"])

    def test_register_failure_excludes_only_that_offer(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10, fail_register={"o1"})
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["moved"], 1)
        self.assertEqual(self._tgt_ids(feed), {"o2"})
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertIn("registration failed", by_id["o1"]["blocker"])

    def test_already_gone_offer_is_skipped(self):
        # Plan references o3 which is not on the source feed at all → skip.
        feed = FakeFeed({SRC: [_offer(1)]}, page_size=10)
        res = _run(feed, [_spec(1), _spec(3)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"])
        self.assertIn("already moved", by_id["o3"]["skipped"])
        self.assertEqual(res["moved"], 1)

    def test_limit_caps_moves(self):
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 5)]}, page_size=10)
        res = _run(feed, [_spec(i) for i in range(1, 5)], limit=1)
        self.assertEqual(res["moved"], 1)
        self.assertEqual(res["stopped"], "limit_reached")
        self.assertEqual(len(self._tgt_ids(feed)), 1)

    def test_move_attempts_counts_applied_offers(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["move_attempts"], 2)

    def test_max_apply_items_reports_largest_apply(self):
        # 3 offers on ONE page → ONE Apply of 3 → the multi-item proof (>=2) that a
        # --mode safe --batch authorization requires (P2).
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 4)]}, page_size=10)
        res = _run(feed, [_spec(i) for i in range(1, 4)])
        self.assertEqual(res["max_apply_items"], 3)

    def test_single_item_apply_is_not_multi_item(self):
        # One offer alone on its page → a 1-item Apply → max_apply_items=1, which
        # does NOT satisfy the >=2 multi-item proof.
        feed = FakeFeed({SRC: [_offer(1)]}, page_size=10)
        res = _run(feed, [_spec(1)])
        self.assertEqual(res["max_apply_items"], 1)

    def test_target_scan_error_marks_whole_group_unknown_not_just_current(self):
        # Regression (review 2026-07-28): the ONE Apply writes all 3 offers; the
        # source verify succeeds (all gone) but the TARGET-list scan is
        # unreadable. EVERY in-flight offer must be marked UNKNOWN + recorded —
        # the except once marked only the current offer and returned, silently
        # dropping the rest from the plan/guard/ledger.
        feed = FakeFeed({SRC: [_offer(1), _offer(2), _offer(3)]}, page_size=10,
                        break_target_scan=True)
        res = _run(feed, [_spec(1), _spec(2), _spec(3)])
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)
        self.assertEqual({e["offer_id"] for e in res["plan"]}, {"o1", "o2", "o3"})  # NONE dropped
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])
        self.assertEqual(res["move_attempts"], 3)                 # all 3 were written

    def test_breaker_trips_after_ten_consecutive_failures_before_next_group(self):
        # 10 swallowed offers on page 1 → 10 consecutive post-Apply failures →
        # the 10-consecutive breaker blocks BEFORE page 2's Apply ever fires.
        offers = [_offer(i) for i in range(1, 13)]            # 12 offers
        feed = FakeFeed({SRC: offers}, page_size=10, swallow_target={o["id"] for o in offers})
        res = _run(feed, [_spec(i) for i in range(1, 13)])
        self.assertEqual(res["stopped"], "ten_consecutive_failures")
        self.assertEqual(res["moved"], 0)
        self.assertEqual(feed.apply_count, 1)                    # page 2 never applied
        self.assertEqual(len(res["plan"]), 10)                   # only page-1 group processed

    def test_parallel_move_to_target_before_group_is_skipped_not_credited(self):
        # A parallel operator already moved o2 to the target (gone from source,
        # present on target) — it never entered OUR Apply, so it must be an
        # idempotent SKIP, never credited as our move (invariant 3).
        feed = FakeFeed({SRC: [_offer(1)], TGT: [_offer(2)]}, page_size=10)
        res = _run(feed, [_spec(1), _spec(2)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"])                    # ours
        self.assertFalse(by_id["o2"].get("moved"))
        self.assertIn("already moved", by_id["o2"]["skipped"])   # skipped, not credited
        self.assertEqual(res["moved"], 1)


class _PagedSession:
    """Serves fixed pages so a reflowed feed (duplicate middle pages, a fresh
    offer on a tail page) can be built deterministically."""

    def __init__(self, pages, nav_max):
        self.pages, self.nav_max = pages, nav_max
        self._page, self._url = 1, ""

    def navigate(self, url, settle=None):
        self._url = url
        m = _P_RE.search(url)
        self._page = int(m.group(1)) if m else 1

    def page_offer_rows(self):
        return [dict(r) for r in self.pages.get(self._page, [])]

    def feed_page_state(self):
        return {"feed_ui": True, "nav_max": self.nav_max, "is_login": False, "href": self._url}


class FullCoverageScanTests(unittest.TestCase):
    """The fail-closed property that makes the batched group-verify SOUND: a
    ``full_coverage`` scan walks to a PROVEN end-of-feed, so an offer on a tail
    page past a run of reflow-duplicate pages is NOT falsely judged absent (the
    plain 2-empty-new-id early terminate WOULD miss it → a false 'gone')."""

    def _sub(self, pages, nav_max):
        sub = _SubmitterBase(_PagedSession(pages, nav_max))
        sub.empty_retry_wait_s = 0
        sub.feed_scan_settle = 0
        return sub

    def _pages(self):
        a, b, c = _offer(1), _offer(2), _offer(3)
        # pages 2-3 repeat page 1 (reflow, no NEW ids); page 4 carries a fresh
        # offer; page 5 is the proven past-the-end (nav_max=4).
        return {1: [a, b], 2: [a, b], 3: [a, b], 4: [c]}, 4

    def test_plain_scan_early_terminates_and_misses_the_tail(self):
        pages, nav_max = self._pages()
        sub = self._sub(pages, nav_max)
        _, by_url, _ = sub._scan_feed("38", "aks-merchant-feeds-9", "all", 20)
        self.assertNotIn(_url_key("https://m/3"), by_url)      # the plain heuristic misses o3

    def test_full_coverage_walks_to_proven_end_and_sees_the_tail(self):
        pages, nav_max = self._pages()
        sub = self._sub(pages, nav_max)
        index, by_url, found = sub._scan_feed("38", "aks-merchant-feeds-9", "all", 20,
                                              full_coverage=True)
        self.assertIn(_url_key("https://m/3"), by_url)         # o3 IS seen → no false 'gone'
        self.assertIn("o3", index)
        self.assertFalse(found)                                # no stop_on target

    def test_full_coverage_raises_when_coverage_unprovable(self):
        # nav advertises 9 pages but we cap at 3 and every page is full → the tail
        # was never scanned → FeedScanError (never a truncated/false-absent map).
        pages = {p: [_offer(p)] for p in range(1, 10)}
        sub = self._sub(pages, nav_max=9)
        from src.submitter import FeedScanError
        with self.assertRaises(FeedScanError):
            sub._scan_feed("38", "aks-merchant-feeds-9", "all", 3, full_coverage=True)


if __name__ == "__main__":
    unittest.main()
