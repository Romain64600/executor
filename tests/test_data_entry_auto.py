"""Safe-auto data-entry sweep engine v2 — reflow-safe highest-first, fail-closed
halting (incl. mid-batch submitter STOP), coverage honesty. No browser."""
import unittest

from src.data_entry_auto import (
    ExtractOutcome, MatchOutcome, Stages, StageError, SubmitOutcome, SweepConfig, run_sweep,
)


class FakeStages:
    """Scripted per-page outcomes. ``feed_last`` is what every extract's nav
    advertises (the probe reads it). ``pages`` maps page -> spec; a missing page
    defaults to a full page with 0 candidates."""

    def __init__(self, feed_last, pages, *, offers_default=100):
        self.feed_last = feed_last
        self.pages = pages
        self.offers_default = offers_default
        self.calls = []
        self.approved = {}

    def _p(self, run_id):
        return int(run_id.rsplit("p", 1)[1])

    def extract(self, page, run_id):
        self.calls.append(("extract", page))
        spec = self.pages.get(page, {})
        if "extract_fail" in spec:
            return ExtractOutcome(ok=False, detail=spec["extract_fail"], feed_last_page=self.feed_last)
        offers = spec.get("offers", self.offers_default)
        return ExtractOutcome(ok=True, offers=offers, feed_last_page=self.feed_last)

    def match(self, run_id):
        p = self._p(run_id)
        self.calls.append(("match", p))
        spec = self.pages.get(p, {})
        if "match_fail" in spec:
            return MatchOutcome(ok=False, detail=spec["match_fail"])
        return MatchOutcome(ok=True, candidates=spec.get("candidates", 0))

    def approve(self, run_id):
        p = self._p(run_id)
        self.calls.append(("approve", p))
        spec = self.pages.get(p, {})
        if "approve_fail" in spec:
            raise StageError(spec["approve_fail"])
        n = spec.get("candidates", 0)
        self.approved[p] = n
        return n

    def submit(self, run_id):
        p = self._p(run_id)
        self.calls.append(("submit", p))
        spec = self.pages.get(p, {})
        n = spec.get("candidates", 0)
        created = spec.get("created", n)
        return SubmitOutcome(ok=not spec.get("submit_exit_fail", False),
                             aborted=spec.get("submit_abort"),
                             stopped=spec.get("submit_stopped"),
                             created=created,
                             offers=[{"name": f"o{p}-{i}", "created": True} for i in range(created)],
                             detail=spec.get("submit_detail", ""))


def _run(fs, *, start=1, max_pages=400, should_stop=lambda: False):
    cfg = SweepConfig(merchant="Kinguin", store_id="58", start_page=start, max_pages=max_pages)
    return run_sweep(cfg, Stages(fs.extract, fs.match, fs.approve, fs.submit),
                     page_run_id=lambda p: f"sweep-p{p}", should_stop=should_stop)


class SweepEngineTests(unittest.TestCase):
    def test_highest_first_order_reflow_safe(self):
        fs = FakeStages(3, {1: {"candidates": 1}, 2: {"candidates": 2}, 3: {"candidates": 3}})
        r = _run(fs)
        # processed highest page first, down to 1
        self.assertEqual([p["page"] for p in r["pages"]], [3, 2, 1])
        self.assertEqual(r["feed_last_page"], 3)
        self.assertEqual(r["total_created"], 6)
        self.assertIsNone(r["halted"])
        # a probe extract of the start page precedes the descent
        self.assertEqual(fs.calls[0], ("extract", 1))
        self.assertEqual([c for c in fs.calls if c[0] == "submit"], [("submit", 3), ("submit", 2), ("submit", 1)])

    def test_single_page_feed(self):
        fs = FakeStages(1, {1: {"offers": 40, "candidates": 2}})
        r = _run(fs)
        self.assertEqual([p["page"] for p in r["pages"]], [1])
        self.assertEqual(r["total_created"], 2)
        self.assertIsNone(r["halted"])

    def test_empty_feed(self):
        fs = FakeStages(1, {1: {"offers": 0}})
        r = _run(fs)
        self.assertTrue(r["pages"][-1]["end_of_feed"])
        self.assertIsNone(r["halted"])

    def test_zero_candidate_page_no_submit_continues(self):
        fs = FakeStages(2, {1: {"candidates": 1}, 2: {"candidates": 0}})
        r = _run(fs)
        self.assertNotIn(("submit", 2), fs.calls)
        self.assertIn(("submit", 1), fs.calls)
        self.assertEqual(r["total_created"], 1)

    def test_submit_aborted_halts(self):
        fs = FakeStages(3, {3: {"candidates": 2, "submit_abort": "not_logged_in", "created": 0},
                            2: {"candidates": 5}, 1: {"candidates": 5}})
        r = _run(fs)
        self.assertEqual(r["halted"], "submit_not_clean_p3")
        self.assertEqual([p["page"] for p in r["pages"]], [3])   # stopped after the highest page
        self.assertNotIn(("extract", 2), fs.calls)

    def test_submit_STOPPED_feed_unreadable_halts(self):
        # CRITICAL regression: the submitter signals a broken session mid-batch via
        # `stopped`, NOT `aborted`. It MUST halt the sweep (no plow-through).
        fs = FakeStages(3, {3: {"candidates": 4, "submit_stopped": "feed_unreadable", "created": 2},
                            2: {"candidates": 5}})
        r = _run(fs)
        self.assertEqual(r["halted"], "submit_not_clean_p3")
        self.assertNotIn(("extract", 2), fs.calls)
        self.assertEqual(r["pages"][0]["stopped"], "feed_unreadable")
        self.assertEqual(r["total_created"], 2)   # the 2 real writes still recorded

    def test_submit_stopped_guard_blocked_halts(self):
        fs = FakeStages(2, {2: {"candidates": 3, "submit_stopped": "guard_blocked"}, 1: {"candidates": 3}})
        r = _run(fs)
        self.assertEqual(r["halted"], "submit_not_clean_p2")

    def test_submit_stopped_limit_reached_is_benign(self):
        # limit_reached never occurs in safe mode, but if seen it must NOT halt.
        fs = FakeStages(2, {2: {"candidates": 1, "submit_stopped": "limit_reached"}, 1: {"candidates": 1}})
        r = _run(fs)
        self.assertIsNone(r["halted"])
        self.assertEqual([p["page"] for p in r["pages"]], [2, 1])

    def test_submit_nonzero_exit_halts(self):
        fs = FakeStages(2, {2: {"candidates": 2, "submit_exit_fail": True}, 1: {"candidates": 2}})
        r = _run(fs)
        self.assertEqual(r["halted"], "submit_not_clean_p2")

    def test_extract_failure_halts(self):
        fs = FakeStages(3, {3: {"extract_fail": "feed_unreadable"}})
        r = _run(fs)
        self.assertEqual(r["halted"], "extract_failed_p3")
        self.assertNotIn(("match", 3), fs.calls)

    def test_probe_failure_halts(self):
        fs = FakeStages(3, {1: {"extract_fail": "feed_unreadable"}})
        r = _run(fs)   # probe is extract(start_page=1)
        self.assertEqual(r["halted"], "extract_failed_p1")

    def test_match_failure_halts(self):
        fs = FakeStages(2, {2: {"match_fail": "probe unreliable"}, 1: {"candidates": 1}})
        r = _run(fs)
        self.assertEqual(r["halted"], "match_failed_p2")
        self.assertNotIn(("submit", 2), fs.calls)

    def test_approve_failure_halts_recorded(self):
        fs = FakeStages(2, {2: {"candidates": 2, "approve_fail": "stale candidates"}, 1: {"candidates": 2}})
        r = _run(fs)
        self.assertEqual(r["halted"], "approve_failed_p2")
        self.assertIn("approve", r["pages"][0]["error"])
        self.assertNotIn(("submit", 2), fs.calls)   # never submitted

    def test_empty_page_mid_feed_continues(self):
        # feed shrank past page 3 → 0 offers there → skip, continue down.
        fs = FakeStages(3, {3: {"offers": 0}, 2: {"candidates": 2}, 1: {"candidates": 1}})
        r = _run(fs)
        self.assertTrue(r["pages"][0]["empty"])
        self.assertEqual(r["total_created"], 3)
        self.assertIsNone(r["halted"])

    def test_max_pages_cap_flags_incomplete(self):
        # feed advertises 10 pages, cap at 3 from start_page 1 → cover pages 1..3
        # (highest-first: 3,2,1), flag the rest as NOT covered.
        fs = FakeStages(10, {p: {"candidates": 0} for p in range(1, 11)})
        r = _run(fs, max_pages=3)
        self.assertIn("coverage_incomplete_max_pages", r["halted"])
        self.assertEqual([p["page"] for p in r["pages"]], [3, 2, 1])

    def test_operator_stop_before_submit(self):
        # stop lands after match, before the write → no submit on that page.
        state = {"n": 0}
        def stop():
            state["n"] += 1
            # #1 run start, #2 loop-top page2 → False; #3 pre-submit page2 → stop
            return state["n"] > 2
        fs = FakeStages(2, {2: {"candidates": 2}, 1: {"candidates": 2}})
        r = _run(fs, should_stop=stop)
        self.assertEqual(r["halted"], "operator_stop")
        self.assertNotIn(("submit", 2), fs.calls)

    def test_operator_stop_upfront(self):
        fs = FakeStages(3, {3: {"candidates": 1}})
        r = _run(fs, should_stop=lambda: True)
        self.assertEqual(r["halted"], "operator_stop")
        self.assertEqual(r["pages"], [])


if __name__ == "__main__":
    unittest.main()
