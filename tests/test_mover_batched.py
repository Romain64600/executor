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

from src.cdp_session import CdpCommandError
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
                 rename_on_page=None, raise_reads_after_apply=None, raise_on_apply=False,
                 hide_on_target_when_store_scoped=None):
        self.lists = {k: [dict(o) for o in v] for k, v in lists.items()}
        self.page_size = page_size
        self.fail_register = set(fail_register)
        self.swallow_target = set(swallow_target)
        self.bulk_list_lies = bulk_list_lies
        self.break_after_apply = break_after_apply
        self.break_target_scan = break_target_scan   # target-list reads unreadable after an Apply
        self.rename_on_page = rename_on_page or {}   # id -> new name (identity churn)
        # Once apply_count reaches this, per-offer page reads RAISE (a transient CDP
        # blip mid-pass) — distinct from break_after_apply, which returns empty reads.
        self.raise_reads_after_apply = raise_reads_after_apply
        self.raise_on_apply = raise_on_apply   # click_apply itself raises (Apply outcome UNKNOWN)
        # ids that are on the TARGET list globally but HIDDEN under a store-scoped
        # (?store=…) target view — models the re-import store/id rotation that made
        # a moved offer invisible to a store-filtered RV2 scan (2026-07-31 fix).
        self.hide_on_target_when_store_scoped = set(hide_on_target_when_store_scoped or ())
        self._store_scoped = False
        self._fp = None
        self._page = 1
        self._url = ""
        self._registered = []
        self._bulk_list = ""
        self._broken = False
        self._applied = False
        self.apply_count = 0
        self.target_scan_starts = 0   # navigations to (target list, page 1) = # target scans

    def _read_broken(self):
        return self._broken or (self.break_target_scan and self._applied and self._fp == TGT)

    # -- navigation --
    def navigate(self, url, settle=None):
        self._url = url
        m = _FP_RE.search(url)
        self._fp = m.group(1) if m else None
        pm = _P_RE.search(url)
        self._page = int(pm.group(1)) if pm else 1
        self._store_scoped = "store=" in url   # a ?store=… filter vs the global list view
        if self._fp == TGT and self._page == 1:
            self.target_scan_starts += 1   # each target scan restarts at page 1
        self._registered = []
        self._bulk_list = ""

    def is_login_page(self):
        return False

    def list_options(self):
        return [{"value": TGT, "text": "Blacklist"}, {"value": "21", "text": "Gift cards"}]

    # -- page reads --
    def _cur(self):
        lst = self.lists.get(self._fp, [])
        # A store-scoped view of the TARGET list hides the re-import-rotated ids —
        # the global (store=None) view shows them. Source scans are unaffected.
        if self._fp == TGT and self._store_scoped and self.hide_on_target_when_store_scoped:
            lst = [o for o in lst if o["id"] not in self.hide_on_target_when_store_scoped]
        return lst

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

    def _maybe_raise_reads(self):
        if (self.raise_reads_after_apply is not None
                and self.apply_count >= self.raise_reads_after_apply):
            raise CdpCommandError("transient CDP read failure mid-pass")

    def page_offer_rows(self):
        self._maybe_raise_reads()
        return [] if self._read_broken() else self._rows()

    def feed_page_state(self):
        if self._read_broken():
            return {"feed_ui": False, "nav_max": 0, "is_login": False, "href": self._url}
        n = len(self._cur())
        nav_max = (n + self.page_size - 1) // self.page_size
        return {"feed_ui": True, "nav_max": nav_max, "is_login": False, "href": self._url}

    # -- bulk form --
    def bulk_row_present(self, offer_id):
        self._maybe_raise_reads()
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
        if self.raise_on_apply:
            # The Apply request failed mid-flight — it MAY have committed server-side,
            # so the outcome of every registered id is genuinely UNKNOWN.
            raise CdpCommandError("apply request failed mid-flight")
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


def _new_mover(feed):
    guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=2,
                      max_consecutive_failures=10, max_failures_per_task=10 ** 9)
    mover = Mover(feed, guard=guard)
    mover.post_apply_settle = 0
    mover.empty_retry_wait_s = 0
    mover.feed_scan_settle = 0
    mover.feed_retry_pause = 0      # keep the transient-error retries instant in tests
    mover.feed_ui_render_waits = ()  # no real render-wait sleep in tests
    return mover


def _run(feed, specs, *, limit=None, page_size=None, max_pages=20, deferred=False):
    if page_size is not None:
        feed.page_size = page_size
    return _new_mover(feed).run(run_id="t", store_id="38", plan=specs,
                                source_feed_page="aks-merchant-feeds-%s" % SRC,
                                max_pages=max_pages, limit=limit, batch=True, deferred=deferred)


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

    def test_target_verify_is_global_not_store_scoped(self):
        # Regression (2026-07-31): a moved offer that a re-import hides from its
        # STORE-scoped target view but that IS on the list globally must still
        # verify as moved — the RV2 target scan runs global (store=None). A
        # store-scoped scan gave false "left source but NOT on target" negatives
        # (undercount + guard/FC3 blocks). o1 is hidden under ?store=…, visible
        # globally; it must score moved.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10,
                        hide_on_target_when_store_scoped={"o1"})
        res = _run(feed, [_spec(1), _spec(2)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"], "o1 must verify on the GLOBAL target list")
        self.assertTrue(by_id["o2"]["moved"])
        self.assertEqual(res["moved"], 2)

    def test_feed_error_after_apply_marks_group_unknown_and_aborts(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10, break_after_apply=True)
        res = _run(feed, [_spec(1), _spec(2)])
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)                    # nothing confirmed
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])       # written but unverifiable

    def test_batched_drive_error_is_caught_not_propagated(self):
        # A feed/CDP raise ESCAPING a batched drive must be caught by run() and the
        # partial result returned with aborted set — never propagated, or 09 breaks
        # without capturing result and the in-flight plan is lost.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        mover = _new_mover(feed)

        def boom(*a, **k):
            raise CdpCommandError("drive blew up past every inner guard")

        mover._register_apply_page = boom
        res = mover.run(run_id="t", store_id="38", plan=[_spec(1), _spec(2)],
                        source_feed_page="aks-merchant-feeds-%s" % SRC, max_pages=20,
                        limit=None, batch=True)              # per-group path
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)

    def test_apply_call_raise_records_group_unknown(self):
        # click_apply itself raises → the Apply MAY have committed, so every
        # registered offer is recorded UNKNOWN (Fix B in _register_apply_page)
        # before the error unwinds — not silently dropped.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10, raise_on_apply=True)
        res = _run(feed, [_spec(1), _spec(2)])               # per-group path
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)
        self.assertEqual({e["offer_id"] for e in res["plan"]}, {"o1", "o2"})
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])

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

    def test_group_target_verify_is_one_scan_not_per_offer(self):
        # P1.5: 3 offers in ONE group → the RV2 target-presence check is ONE
        # target-list scan for all 3, not 3 per-offer scans (the account fix).
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 4)]}, page_size=10)
        res = _run(feed, [_spec(i) for i in range(1, 4)])
        self.assertEqual(res["moved"], 3)
        self.assertEqual(feed.target_scan_starts, 1)      # ONE target scan for the whole group

    def test_group_target_verify_mixed_presence(self):
        # One group, o2 swallowed by the target → the single group scan marks
        # o1/o3 moved and o2 not, from one target walk.
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 4)]}, page_size=10,
                        swallow_target={"o2"})
        res = _run(feed, [_spec(i) for i in range(1, 4)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"])
        self.assertTrue(by_id["o3"]["moved"])
        self.assertFalse(by_id["o2"]["moved"])
        self.assertIn("NOT found on target", by_id["o2"]["post_verify"])
        self.assertEqual(res["moved"], 2)
        self.assertEqual(feed.target_scan_starts, 1)      # still ONE scan even with a miss

    def test_target_verify_uses_decoupled_cap_for_deep_target(self):
        # P1.5's whole point: the source cap is SMALL (max_pages=3) but the target
        # list spans more pages and the moved offers land DEEP (page 5). The
        # decoupled TARGET_SCAN_MAX_PAGES must let the group scan reach them →
        # moved=True. A revert to ctx['max_pages'] would FeedScanError here (target
        # nav_max=5 > cap 3) → whole group UNKNOWN: the account regression.
        decoys = [_offer(100 + i) for i in range(8)]      # 8 decoys on TGT → 4 pages (page_size 2)
        feed = FakeFeed({SRC: [_offer(1), _offer(2)], TGT: decoys}, page_size=2)
        res = _run(feed, [_spec(1), _spec(2)], max_pages=3)
        self.assertEqual(res["max_apply_items"], 2)        # both moved in ONE Apply
        self.assertEqual(res["moved"], 2)                  # found DEEP in the target (page 5)
        self.assertTrue(all(e["moved"] for e in res["plan"]))
        self.assertIsNone(res["aborted"])
        self.assertEqual(feed.target_scan_starts, 1)

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

    def test_batch_recovers_from_transient_scan_error_and_continues(self):
        # The core of the 2026-07-29 robustness change: a transient feed/CDP error
        # on the post-Apply source scan is RETRIED (not fatal), and the batch
        # keeps moving — with NO double-Apply on the recovery.
        from src.submitter import FeedScanError
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=2,
                          max_consecutive_failures=10, max_failures_per_task=10 ** 9)
        mover = Mover(feed, guard=guard)
        mover.post_apply_settle = 0
        mover.empty_retry_wait_s = 0
        mover.feed_scan_settle = 0
        mover.feed_retry_pause = 0
        mover.feed_ui_render_waits = ()
        real = mover._full_source_scan
        state = {"calls": 0}

        def flaky(ctx):
            state["calls"] += 1
            if state["calls"] == 2:      # 1=drive locate, 2=post-Apply verify → one blip
                raise FeedScanError("transient blip")
            return real(ctx)

        mover._full_source_scan = flaky
        res = mover.run(run_id="t", store_id="38", plan=[_spec(1), _spec(2)],
                        source_feed_page="aks-merchant-feeds-%s" % SRC, max_pages=20, batch=True)
        self.assertIsNone(res["aborted"])        # recovered — did NOT abort
        self.assertEqual(res["moved"], 2)         # both still moved
        self.assertEqual(feed.apply_count, 1)     # ONE Apply — the retry did not re-fire it
        self.assertEqual(self._tgt_ids(feed), {"o1", "o2"})

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

    def test_stop_on_urls_stops_early_when_all_seen(self):
        # P1.5 group target scan: the two wanted URLs are on page 1; the scan
        # stops there (found) without walking further (page 3 would even error) —
        # so a group of K near the front costs ~one page, not a full walk.
        pages = {1: [_offer(1), _offer(2)], 2: [_offer(3)]}
        sub = self._sub(pages, nav_max=9)          # nav says 9 pages: it COULD keep going
        want = {_url_key("https://m/1"), _url_key("https://m/2")}
        index, by_url, found = sub._scan_feed("38", "aks-merchant-feeds-8", "all", 20,
                                              stop_on_urls=want)
        self.assertTrue(found)                                     # all wanted seen
        self.assertNotIn(_url_key("https://m/3"), by_url)          # stopped at page 1

    def test_stop_on_urls_walks_to_proven_end_when_one_missing(self):
        # If a wanted URL never appears, the scan cannot stop early — it walks to
        # a proven end and reports found=False (the missing offer → not on target).
        pages = {1: [_offer(1)], 2: [_offer(2)]}                   # o9 is absent
        sub = self._sub(pages, nav_max=2)
        want = {_url_key("https://m/1"), _url_key("https://m/9")}
        _, by_url, found = sub._scan_feed("38", "aks-merchant-feeds-8", "all", 20,
                                          stop_on_urls=want)
        self.assertFalse(found)
        self.assertIn(_url_key("https://m/1"), by_url)
        self.assertNotIn(_url_key("https://m/9"), by_url)

    def test_stop_on_urls_raises_when_coverage_unprovable(self):
        # Fail-closed for the group verify: a wanted URL never appears, every page
        # is full, and nav advertises MORE than max_pages → FeedScanError (the
        # caller marks the whole in-flight group UNKNOWN), never a false absent.
        from src.submitter import FeedScanError
        pages = {p: [_offer(p)] for p in range(1, 10)}             # 9 full pages, o99 absent
        sub = self._sub(pages, nav_max=9)
        want = {_url_key("https://m/99")}
        with self.assertRaises(FeedScanError):
            sub._scan_feed("38", "aks-merchant-feeds-8", "all", 3, stop_on_urls=want)


class DeferredBatchedTests(unittest.TestCase):
    """P1.6: process a store's pages highest-first from ONE scan, verify the whole
    store ONCE (deferred), reflow-safe."""

    def _tgt_ids(self, feed):
        return {o["id"] for o in feed.lists.get(TGT, [])}

    def _run_deferred(self, feed, specs):
        return _new_mover(feed).run(run_id="t", store_id="38", plan=specs,
                                    source_feed_page="aks-merchant-feeds-%s" % SRC,
                                    max_pages=20, limit=None, batch=True, deferred=True)

    def test_moves_all_across_pages_with_two_source_scans_and_one_target_scan(self):
        # 4 offers on 2 pages → highest-first, reflow-safe → all moved with ONE
        # initial locate scan + ONE deferred verify scan (not ~2 per group), and
        # ONE target scan for the whole store (vs one per group).
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 5)]}, page_size=2)
        mover = _new_mover(feed)
        real = mover._full_source_scan
        state = {"n": 0}
        mover._full_source_scan = lambda ctx: (state.__setitem__("n", state["n"] + 1) or real(ctx))
        res = mover.run(run_id="t", store_id="38", plan=[_spec(i) for i in range(1, 5)],
                        source_feed_page="aks-merchant-feeds-%s" % SRC, max_pages=20,
                        limit=None, batch=True, deferred=True)
        self.assertEqual(res["moved"], 4)
        self.assertEqual(self._tgt_ids(feed), {"o1", "o2", "o3", "o4"})
        self.assertEqual(feed.lists[SRC], [])
        self.assertEqual(state["n"], 2)            # ONE locate + ONE deferred verify
        self.assertEqual(feed.target_scan_starts, 1)

    def test_reflow_safe_highest_first(self):
        # 6 offers over 3 pages — the real reflow (each Apply shrinks the source)
        # must not drop any: highest-first keeps lower pages valid.
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 7)]}, page_size=2)
        res = self._run_deferred(feed, [_spec(i) for i in range(1, 7)])
        self.assertEqual(res["moved"], 6)
        self.assertEqual(self._tgt_ids(feed), {f"o{i}" for i in range(1, 7)})

    def test_identity_mismatch_blocks_only_that_offer(self):
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10,
                        rename_on_page={"o1": "A DIFFERENT GAME"})
        res = self._run_deferred(feed, [_spec(1), _spec(2)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertFalse(by_id["o1"]["moved"])
        self.assertIn("identity mismatch", by_id["o1"]["blocker"])
        self.assertTrue(by_id["o2"]["moved"])
        self.assertEqual(res["moved"], 1)

    def test_already_gone_skipped(self):
        feed = FakeFeed({SRC: [_offer(1)]}, page_size=10)
        res = self._run_deferred(feed, [_spec(1), _spec(3)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"])
        self.assertIn("already moved", by_id["o3"]["skipped"])

    def test_deferred_verify_error_marks_whole_store_unknown(self):
        from src.submitter import FeedScanError
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        mover = _new_mover(feed)
        real = mover._full_source_scan
        state = {"n": 0}

        def flaky(ctx):
            state["n"] += 1
            if state["n"] >= 2:          # 1=locate ok; the deferred verify keeps failing
                raise FeedScanError("verify blip that never clears")
            return real(ctx)

        mover._full_source_scan = flaky
        res = mover.run(run_id="t", store_id="38", plan=[_spec(1), _spec(2)],
                        source_feed_page="aks-merchant-feeds-%s" % SRC, max_pages=20,
                        limit=None, batch=True, deferred=True)
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])   # the whole in-flight store set

    def test_deferred_verify_source_error_marks_MULTIPAGE_store_unknown(self):
        # The scenario deferred exists for: offers Applied across SEVERAL pages
        # accumulate into registered_all, then the ONE deferred source scan fails →
        # every offer from every page must be UNKNOWN (none silently dropped).
        from src.submitter import FeedScanError
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 5)]}, page_size=2)   # 2 pages
        mover = _new_mover(feed)
        real = mover._full_source_scan
        state = {"n": 0}

        def flaky(ctx):
            state["n"] += 1
            if state["n"] >= 2:            # 1=locate ok; the Applies don't scan; verify fails
                raise FeedScanError("deferred verify blip that never clears")
            return real(ctx)

        mover._full_source_scan = flaky
        res = mover.run(run_id="t", store_id="38", plan=[_spec(i) for i in range(1, 5)],
                        source_feed_page="aks-merchant-feeds-%s" % SRC, max_pages=20,
                        limit=None, batch=True, deferred=True)
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)
        self.assertEqual(feed.apply_count, 2)              # both pages really Applied
        self.assertEqual(res["move_attempts"], 4)          # all 4 in flight
        self.assertEqual({e["offer_id"] for e in res["plan"]}, {"o1", "o2", "o3", "o4"})
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])

    def test_deferred_target_scan_error_marks_MULTIPAGE_store_unknown(self):
        # After multi-page Applies the deferred source scan proves everything gone,
        # but the ONE target (RV2) scan is unreadable → the whole in-flight set is
        # UNKNOWN (left source, on-target unprovable), not falsely scored moved.
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 5)]}, page_size=2,
                        break_target_scan=True)
        res = self._run_deferred(feed, [_spec(i) for i in range(1, 5)])
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)
        self.assertEqual(feed.apply_count, 2)
        self.assertEqual({e["offer_id"] for e in res["plan"]}, {"o1", "o2", "o3", "o4"})
        for e in res["plan"]:
            self.assertFalse(e["moved"])
            self.assertTrue(e["gone_from_source"])         # source proof succeeded
            self.assertIn("UNKNOWN", e["post_verify"])     # but target unprovable

    def test_mid_pass_error_marks_all_already_applied_offers_unknown(self):
        # Bug 2 (review): pages fire highest-first; after an EARLIER page's Apply
        # lands offers, a later page's read blips (CdpCommandError). Those already-
        # Applied offers accumulate un-verified — they must be forced UNKNOWN +
        # recorded + abort, NEVER silently dropped when the error unwinds run().
        feed = FakeFeed({SRC: [_offer(i) for i in range(1, 5)]}, page_size=2,
                        raise_reads_after_apply=1)   # 1st page applies, 2nd page's read raises
        res = self._run_deferred(feed, [_spec(i) for i in range(1, 5)])
        self.assertEqual(res["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(res["moved"], 0)
        # The highest page (o3,o4) Applied before the blip → recorded UNKNOWN, not lost.
        applied = [e for e in res["plan"] if e["offer_id"] in {"o3", "o4"}]
        self.assertEqual(len(applied), 2)
        for e in applied:
            self.assertFalse(e["moved"])
            self.assertIn("UNKNOWN", e["post_verify"])
        # o1,o2 were never reached (the blip aborted the pass before their page) —
        # so they are NOT recorded at all: still on source, un-ledgered, a re-run
        # retries them. The invariant is that no APPLIED offer is silently dropped,
        # not that un-attempted offers get a phantom record.
        self.assertEqual({e["offer_id"] for e in res["plan"]}, {"o3", "o4"})

    def test_true_identity_mismatch_is_terminal_transient_miss_is_not(self):
        # The ledger's terminal/transient split hinges on this flag: a real
        # URL→different-product contradiction sets identity_mismatch (→ permanent
        # skip); a row merely gone from the page this pass does NOT (→ retried).
        feed = FakeFeed({SRC: [_offer(1)]}, page_size=10, rename_on_page={"o1": "OTHER GAME"})
        mover = _new_mover(feed)
        entry = {"offer_id": "o1", "current_offer_id": "o1", "name": "Game o1",
                 "url": "https://g2a/o1"}
        mover.session.navigate("aks-merchant-feeds-%s" % SRC)
        ok, reason = mover._reverify_row(entry)
        self.assertFalse(ok)
        self.assertIn("identity mismatch", reason)
        self.assertTrue(entry.get("identity_mismatch"))          # terminal

        gone = {"offer_id": "z9", "current_offer_id": "z9", "name": "Vanished",
                "url": "https://g2a/z9"}                          # not on the page at all
        ok2, reason2 = mover._reverify_row(gone)
        self.assertFalse(ok2)
        self.assertIn("vanished", reason2)
        self.assertFalse(gone.get("identity_mismatch"))          # transient → retriable

    def test_deferred_partitions_verify_by_target_list(self):
        # Defensive parity: a deferred set spanning TWO target lists must RV2 each
        # offer against ITS OWN target (the per-group path does). Before the fix a
        # single last-seen target_id was used → the other list's offer scored a
        # false NOT-moved. list_options maps Blacklist→8, "Gift cards"→21.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        specs = [
            {"offer_id": "o1", "name": "Game 1", "url": "https://m/1",
             "target_list_label": "Blacklist"},
            {"offer_id": "o2", "name": "Game 2", "url": "https://m/2",
             "target_list_label": "Gift cards"},
        ]
        res = self._run_deferred(feed, specs)
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"])
        self.assertTrue(by_id["o2"]["moved"])
        self.assertEqual(res["moved"], 2)
        self.assertEqual({o["id"] for o in feed.lists["8"]}, {"o1"})    # its own list
        self.assertEqual({o["id"] for o in feed.lists["21"]}, {"o2"})

    def test_deferred_target_verify_is_global_not_store_scoped(self):
        # The deferred per-store verify shares _verify_group_on_target — same fix:
        # an offer hidden from the store-scoped target view but on the list
        # globally must score moved (this is the exact prod false-negative that
        # tripped FC3 on Gift cards, 2026-07-31).
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10,
                        hide_on_target_when_store_scoped={"o2"})
        res = self._run_deferred(feed, [_spec(1), _spec(2)])
        by_id = {e["offer_id"]: e for e in res["plan"]}
        self.assertTrue(by_id["o1"]["moved"])
        self.assertTrue(by_id["o2"]["moved"], "o2 must verify on the GLOBAL target list")
        self.assertEqual(res["moved"], 2)

    def test_deferred_falls_back_to_per_group_when_limit_set(self):
        # deferred + a canary limit must NOT use the deferred path (tight verify
        # stays for canaries) — the run still moves within the limit.
        feed = FakeFeed({SRC: [_offer(1), _offer(2)]}, page_size=10)
        res = _new_mover(feed).run(run_id="t", store_id="38", plan=[_spec(1), _spec(2)],
                                   source_feed_page="aks-merchant-feeds-%s" % SRC, max_pages=20,
                                   limit=1, batch=True, deferred=True)
        self.assertEqual(res["moved"], 1)
        self.assertEqual(res["stopped"], "limit_reached")


class ScanRetryTests(unittest.TestCase):
    """The bounded retry that keeps one transient feed/CDP blip from aborting a
    long multi-store batch (2026-07-29)."""

    def _mover(self):
        m = Mover(object())
        m.feed_retry_pause = 0
        m.feed_retry_attempts = 3
        return m

    def test_recovers_after_transient_error(self):
        from src.submitter import FeedScanError
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise FeedScanError("blip")
            return "OK"

        self.assertEqual(self._mover()._scan_retry(fn, what="t"), "OK")
        self.assertEqual(calls["n"], 3)

    def test_aborts_after_max_attempts(self):
        from src.submitter import FeedScanError
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise FeedScanError("persistent")

        with self.assertRaises(FeedScanError):
            self._mover()._scan_retry(fn, what="t")
        self.assertEqual(calls["n"], 3)          # tried exactly feed_retry_attempts

    def test_not_logged_in_is_not_retried(self):
        from src.submitter import NotLoggedInError
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise NotLoggedInError("session gone")

        with self.assertRaises(NotLoggedInError):
            self._mover()._scan_retry(fn, what="t")
        self.assertEqual(calls["n"], 1)          # session gone → NO retry

    def test_non_feed_exception_propagates_without_retry(self):
        # An unexpected (non-feed) error must NOT be caught/retried/swallowed.
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("a bug, not a feed blip")

        with self.assertRaises(ValueError):
            self._mover()._scan_retry(fn, what="t")
        self.assertEqual(calls["n"], 1)          # propagated immediately, no retry


if __name__ == "__main__":
    unittest.main()
