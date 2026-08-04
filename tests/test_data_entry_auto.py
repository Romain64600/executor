"""Safe-auto data-entry sweep engine — stop conditions + recap, no browser."""
import unittest

from src.data_entry_auto import (
    ExtractOutcome, MatchOutcome, Stages, SubmitOutcome, SweepConfig, run_sweep,
)


class FakeStages:
    """Scripted per-page stage outcomes. ``pages`` maps page number -> dict with
    offers / candidates / submit params; missing pages default to a full page
    with 0 candidates."""

    def __init__(self, pages, *, page_size=100):
        self.pages = pages
        self.page_size = page_size
        self.calls = []           # (stage, page/run) for ordering assertions
        self.approved = {}

    def _p(self, run_id):
        return int(run_id.rsplit("p", 1)[1])

    def extract(self, page, run_id):
        self.calls.append(("extract", page))
        spec = self.pages.get(page, {})
        if "extract_fail" in spec:
            return ExtractOutcome(ok=False, detail=spec["extract_fail"])
        offers = spec.get("offers", self.page_size)
        return ExtractOutcome(ok=True, offers=offers)

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
        n = self.pages.get(p, {}).get("candidates", 0)
        self.approved[p] = n
        return n

    def submit(self, run_id):
        p = self._p(run_id)
        self.calls.append(("submit", p))
        spec = self.pages.get(p, {})
        if "submit_abort" in spec:
            return SubmitOutcome(ok=True, aborted=spec["submit_abort"], created=spec.get("created", 0))
        if "submit_exit_fail" in spec:
            return SubmitOutcome(ok=False, detail="exit 2")
        n = spec.get("candidates", 0)
        created = spec.get("created", n)
        return SubmitOutcome(ok=True, created=created,
                             offers=[{"name": f"o{p}-{i}", "created": True} for i in range(created)])


def _stages(fs):
    return Stages(extract=fs.extract, match=fs.match, approve=fs.approve, submit=fs.submit)


def _run(fs, *, start=1, max_pages=200, page_size=100, should_stop=lambda: False):
    cfg = SweepConfig(merchant="Kinguin", store_id="58", start_page=start,
                      max_pages=max_pages, page_size=page_size)
    return run_sweep(cfg, _stages(fs), page_run_id=lambda p: f"sweep-p{p}",
                     should_stop=should_stop, on_page=lambda e: None)


class SweepEngineTests(unittest.TestCase):
    def test_full_shop_ends_on_short_page(self):
        # 3 full pages then a short page (40 offers) = end of feed.
        fs = FakeStages({1: {"offers": 100, "candidates": 3},
                         2: {"offers": 100, "candidates": 2},
                         3: {"offers": 100, "candidates": 0},
                         4: {"offers": 40, "candidates": 1}})
        r = _run(fs)
        self.assertEqual([p["page"] for p in r["pages"]], [1, 2, 3, 4])
        self.assertTrue(r["pages"][-1]["last_page"])
        self.assertEqual(r["total_created"], 3 + 2 + 0 + 1)
        self.assertIsNone(r["halted"])

    def test_empty_page_is_end_of_feed(self):
        fs = FakeStages({1: {"offers": 100, "candidates": 1}, 2: {"offers": 0}})
        r = _run(fs)
        self.assertTrue(r["pages"][-1]["end_of_feed"])
        self.assertIsNone(r["halted"])
        self.assertEqual([p["page"] for p in r["pages"]], [1, 2])

    def test_zero_candidates_page_continues(self):
        # a page with 0 candidates must NOT submit, and the sweep continues.
        fs = FakeStages({1: {"offers": 100, "candidates": 0},
                         2: {"offers": 40, "candidates": 2}})
        r = _run(fs)
        self.assertEqual(r["total_created"], 2)
        self.assertNotIn(("approve", 1), fs.calls)
        self.assertNotIn(("submit", 1), fs.calls)
        self.assertIn(("submit", 2), fs.calls)

    def test_submit_abort_halts_fail_closed(self):
        fs = FakeStages({1: {"offers": 100, "candidates": 3},
                         2: {"offers": 100, "candidates": 2, "submit_abort": "feed_unreadable_mid_run", "created": 1},
                         3: {"offers": 100, "candidates": 5}})  # must never be reached
        r = _run(fs)
        self.assertEqual(r["halted"], "submit_not_clean_p2")
        self.assertEqual([p["page"] for p in r["pages"]], [1, 2])
        self.assertNotIn(("extract", 3), fs.calls)   # chain stopped, page 3 untouched
        self.assertEqual(r["pages"][1]["aborted"], "feed_unreadable_mid_run")
        # page-2's partial created (1) is still recorded (nothing lost)
        self.assertEqual(r["total_created"], 3 + 1)

    def test_submit_nonzero_exit_halts(self):
        fs = FakeStages({1: {"offers": 100, "candidates": 2, "submit_exit_fail": True},
                         2: {"offers": 100, "candidates": 2}})
        r = _run(fs)
        self.assertEqual(r["halted"], "submit_not_clean_p1")
        self.assertNotIn(("extract", 2), fs.calls)

    def test_extract_failure_halts(self):
        fs = FakeStages({1: {"extract_fail": "feed_unreadable"}})
        r = _run(fs)
        self.assertEqual(r["halted"], "extract_failed_p1")
        self.assertNotIn(("match", 1), fs.calls)

    def test_match_failure_halts(self):
        fs = FakeStages({1: {"offers": 100, "match_fail": "probe unreliable"}})
        r = _run(fs)
        self.assertEqual(r["halted"], "match_failed_p1")
        self.assertNotIn(("submit", 1), fs.calls)

    def test_operator_stop_between_pages(self):
        seen = {"n": 0}
        def stop():
            seen["n"] += 1
            return seen["n"] > 2   # stop before the 3rd page
        fs = FakeStages({1: {"offers": 100, "candidates": 1},
                         2: {"offers": 100, "candidates": 1},
                         3: {"offers": 100, "candidates": 1}})
        r = _run(fs, should_stop=stop)
        self.assertEqual(r["halted"], "operator_stop")
        self.assertEqual([p["page"] for p in r["pages"]], [1, 2])

    def test_max_pages_cap(self):
        fs = FakeStages({p: {"offers": 100, "candidates": 0} for p in range(1, 10)})
        r = _run(fs, max_pages=3)
        self.assertEqual([p["page"] for p in r["pages"]], [1, 2, 3])
        self.assertIsNone(r["halted"])   # cap reached is a normal end

    def test_start_page_offset(self):
        fs = FakeStages({5: {"offers": 40, "candidates": 1}})
        r = _run(fs, start=5)
        self.assertEqual([p["page"] for p in r["pages"]], [5])
        self.assertTrue(r["pages"][0]["last_page"])

    def test_approve_called_only_with_candidates_and_before_submit(self):
        fs = FakeStages({1: {"offers": 40, "candidates": 2}})
        _run(fs)
        # order: extract, match, approve, submit
        self.assertEqual(fs.calls, [("extract", 1), ("match", 1), ("approve", 1), ("submit", 1)])
        self.assertEqual(fs.approved[1], 2)


if __name__ == "__main__":
    unittest.main()
