import unittest

from src.mover import DryRunMover, Mover, resolve_list_id, source_feed_page

# The live bulk[list] options as the real select renders them ("Move to <label>").
LIST_OPTIONS = [
    {"value": "", "text": "Don't change the list"},
    {"value": "16", "text": "Move to Softwares"},
    {"value": "21", "text": "Move to Gift cards"},
    {"value": "29", "text": "Move to TEST"},
]


class FakeMoveSession:
    """Minimal feed + bulk-move surface for the mover. Configurable failures."""

    def __init__(self, pages, *, login=False, options=None, register_ok=True,
                 bulk_set_ok=True, apply_ok=True, move_removes=True, rows=None,
                 source_id="9", on_target=True):
        self.pages = [list(p) for p in pages]        # the SOURCE list, paginated
        self.rows = dict(rows or {})  # per-id {url, name} overrides (re-id sim)
        self.login = login
        self.options = options if options is not None else LIST_OPTIONS
        self.register_ok = register_ok
        self.bulk_set_ok = bulk_set_ok
        self.apply_ok = apply_ok
        self.move_removes = move_removes
        self.source_id = source_id
        self.on_target = on_target  # does a moved offer appear on its target list?
        self.moved_to = {}          # target_list_id -> [offer_ids] (RV2 verify)
        self.nav = []
        self._page = 0
        self._list = source_id
        self._registered = None
        self._bulk_list = None
        self.applied = []

    # --- read surface ---
    def navigate(self, url, settle=3.0):
        import re
        self.nav.append(url)
        m = re.search(r"page=aks-merchant-feeds-(\d+)", url)
        self._list = m.group(1) if m else self.source_id
        mp = re.search(r"[&?]p=(\d+)", url)
        self._page = (int(mp.group(1)) - 1) if mp else 0

    def is_login_page(self):
        return self.login

    def _row(self, oid):
        row = {"id": oid, "url": f"https://m/{oid}", "name": f"Game {oid}",
               "price": "", "store_id": "38"}
        row.update(self.rows.get(oid, {}))
        return row

    def _pages_for_current(self):
        if self._list == self.source_id:
            return self.pages
        return [self.moved_to.get(self._list, [])]  # a target list: single page

    def page_offer_rows(self):
        pages = self._pages_for_current()
        if 0 <= self._page < len(pages):
            return [self._row(i) for i in pages[self._page]]
        return []

    def feed_page_state(self):
        pages = self._pages_for_current()
        nav_max = max((i + 1 for i, p in enumerate(pages) if p), default=0)
        return {"feed_ui": True, "nav_max": nav_max, "is_login": self.login,
                "href": self.nav[-1] if self.nav else ""}

    def list_options(self):
        return list(self.options)

    def bulk_row_present(self, oid):
        here = 0 <= self._page < len(self.pages) and oid in self.pages[self._page]
        return {"checkbox": here, "bulk_form": True}

    # --- write surface ---
    def register_row(self, oid):
        if self.register_ok:
            self._registered = oid
        return {"click": {"status": "CLICKED"}, "registered": self.register_ok,
                "bulk_list_value": ""}

    def set_bulk_list(self, target):
        self._bulk_list = str(target) if self.bulk_set_ok else ""
        return self._bulk_list

    def click_apply(self):
        if not self.apply_ok:
            return {"status": "NO_ELEMENT"}
        # a real Apply POSTs: the offer leaves the source list and (RV2) appears
        # on its target list — unless on_target=False (simulates a parallel
        # operator's move/delete: gone from source but NOT on our target).
        if self.move_removes and self._registered is not None:
            for p in self.pages:
                if self._registered in p:
                    p.remove(self._registered)
            if self.on_target and self._bulk_list:
                self.moved_to.setdefault(self._bulk_list, []).append(self._registered)
        self.applied.append((self._registered, self._bulk_list))
        return {"status": "CLICKED"}


def _plan(*offer_ids, label="Softwares", list_id="16"):
    return [{"offer_id": str(o), "name": f"Game {o}", "url": f"https://m/{o}",
             "target_list_id": list_id, "target_list_label": label} for o in offer_ids]


def _run(mover_cls, session, plan, **kw):
    m = mover_cls(session)
    m.post_apply_settle = 0  # no real POST wait in tests (Mover only)
    return m.run(run_id="r", store_id="38", plan=plan,
                 source_feed_page="aks-merchant-feeds-9", max_pages=5, **kw)


class ResolveListIdTests(unittest.TestCase):
    def test_label_match(self):
        self.assertEqual(resolve_list_id("Softwares", LIST_OPTIONS)["id"], "16")

    def test_move_to_prefix_tolerated(self):
        self.assertEqual(resolve_list_id("Move to Gift cards", LIST_OPTIONS)["id"], "21")

    def test_unknown_label_is_none(self):
        self.assertIsNone(resolve_list_id("Nonexistent List", LIST_OPTIONS))
        self.assertIsNone(resolve_list_id("", LIST_OPTIONS))

    def test_ambiguous_label_fail_closed(self):
        # MV5: two options with the same label must NOT silently pick the first.
        dup = LIST_OPTIONS + [{"value": "77", "text": "Move to Softwares"}]
        self.assertIsNone(resolve_list_id("Softwares", dup))


class SourceFeedPageTests(unittest.TestCase):
    def test_parses_list_id_from_source_url(self):
        url = "https://x/admin.php?available=all&store=38&page=aks-merchant-feeds-9&p=2"
        self.assertEqual(source_feed_page(url), "aks-merchant-feeds-9")
        self.assertEqual(source_feed_page("https://x/admin.php?page=aks-merchant-feeds-30"),
                         "aks-merchant-feeds-30")

    def test_default_when_absent(self):
        self.assertEqual(source_feed_page(None), "aks-merchant-feeds-9")
        self.assertEqual(source_feed_page("https://x/nope"), "aks-merchant-feeds-9")


class DryRunMoverTests(unittest.TestCase):
    def test_dry_run_locates_but_never_writes(self):
        session = FakeMoveSession([["100"]])
        result = _run(DryRunMover, session, _plan("100"))
        self.assertIsNone(result["aborted"])
        self.assertEqual(result["moved"], 0)
        entry = result["plan"][0]
        self.assertTrue(entry["selectable"])
        self.assertIn("16 (Softwares)", entry["would_move_to"])
        self.assertEqual(session.applied, [])  # no Apply ever

    def test_login_page_aborts(self):
        session = FakeMoveSession([["100"]], login=True)
        self.assertEqual(_run(DryRunMover, session, _plan("100"))["aborted"], "not_logged_in")

    def test_unresolved_target_aborts_before_any_scan(self):
        session = FakeMoveSession([["100"]])
        result = _run(DryRunMover, session, _plan("100", label="Ghost List", list_id="404"))
        self.assertEqual(result["aborted"], "target_list_unresolved")


class MoverWriteTests(unittest.TestCase):
    def test_move_confirmed_by_departure_and_arrival(self):
        session = FakeMoveSession([["100", "200"]])
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["move_attempts"], 1)
        entry = result["plan"][0]
        self.assertTrue(entry["moved"])
        self.assertTrue(entry["gone_from_source"])
        self.assertTrue(entry["on_target"])  # RV2
        self.assertEqual(entry["post_verify"], "gone from source + present on target list")
        self.assertEqual(session.applied, [("100", "16")])

    def test_left_source_but_not_on_target_is_failure(self):
        # RV2: gone from source but NOT present on the target (a parallel
        # operator's move/delete) must NOT count as our success.
        session = FakeMoveSession([["100"]], on_target=False)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        entry = result["plan"][0]
        self.assertTrue(entry["gone_from_source"])
        self.assertFalse(entry["on_target"])
        self.assertIn("NOT found on target", entry["post_verify"])

    def test_still_present_after_apply_is_failure(self):
        # move_removes=False: the offer stays on the source → NOT confirmed
        session = FakeMoveSession([["100"]], move_removes=False)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        self.assertFalse(result["plan"][0]["moved"])
        self.assertIn("STILL on source", result["plan"][0]["post_verify"])

    def test_registration_failure_blocks_without_submit(self):
        session = FakeMoveSession([["100"]], register_ok=False)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        self.assertIn("registration failed", result["plan"][0]["blocker"])
        self.assertEqual(session.applied, [])  # never reached Apply

    def test_bulk_list_drift_blocks(self):
        session = FakeMoveSession([["100"]], bulk_set_ok=False)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        self.assertIn("bulk[list] reads", result["plan"][0]["blocker"])
        self.assertEqual(session.applied, [])

    def test_apply_not_clicked_blocks(self):
        session = FakeMoveSession([["100"]], apply_ok=False)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        self.assertIn("Apply not clicked", result["plan"][0]["blocker"])

    def test_offer_absent_from_source_is_skipped_not_failed(self):
        session = FakeMoveSession([["200"]])  # 100 not on the source (already moved)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["move_attempts"], 0)
        self.assertIn("proven by full scan", result["plan"][0]["skipped"])
        self.assertEqual(session.applied, [])

    def test_canary_limit_stops_after_one(self):
        session = FakeMoveSession([["100", "200"]])
        result = _run(Mover, session, _plan("100", "200"), limit=1)
        self.assertEqual(result["move_attempts"], 1)
        self.assertEqual(result["stopped"], "limit_reached")

    def test_move_relocates_offer_that_reflowed_to_another_page(self):
        # canary 2026-07-22: an offer can reflow to another page between the
        # start-of-run index and the move. _relocate_before_move re-finds it by
        # URL instead of trusting a fixed page.
        session = FakeMoveSession([["1"], ["100"]])  # target offer sits on page 2
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 1)
        self.assertEqual(session.applied, [("100", "16")])

    def test_relocated_by_url_when_id_rotated(self):
        # the plan's id 100 no longer exists; the same URL now has id 900
        session = FakeMoveSession([["900"]])
        plan = [{"offer_id": "100", "name": "Game 900", "url": "https://m/900",
                 "target_list_id": "16", "target_list_label": "Softwares"}]
        result = _run(Mover, session, plan)
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["plan"][0]["current_offer_id"], "900")
        self.assertEqual(session.applied, [("900", "16")])


class ReverifyRowTests(unittest.TestCase):
    """MV1/SC5 — never write against a row that no longer matches the plan."""

    def _mover(self, session):
        m = Mover(session)
        m.post_apply_settle = 0
        return m

    def test_reverify_blocks_reided_row(self):
        # id 100 on the page is now a DIFFERENT product than the plan's
        session = FakeMoveSession([["100"]])
        entry = {"current_offer_id": "100", "name": "Different Game",
                 "url": "https://m/other", "store_id": "38"}
        ok, reason = self._mover(session)._reverify_row(entry)
        self.assertFalse(ok)
        self.assertIn("mismatch", reason)

    def test_reverify_relocates_by_url_when_id_vanished(self):
        session = FakeMoveSession([["900"]])  # id 100 gone; URL m/900 now id 900
        entry = {"current_offer_id": "100", "name": "Game 900",
                 "url": "https://m/900", "store_id": "38"}
        ok, reason = self._mover(session)._reverify_row(entry)
        self.assertTrue(ok)
        self.assertEqual(entry["current_offer_id"], "900")

    def test_reid_between_locate_and_move_is_never_moved(self):
        # id 100 is the plan's offer at index time (url m/100), but on the fresh
        # page its checkbox value 100 belongs to product m/hijack → block, no write
        session = FakeMoveSession([["100"]], rows={"100": {"url": "https://m/hijack",
                                                           "name": "Hijacked Product"}})
        # plan trusts the START identity (locate uses the same rows here, so this
        # actually surfaces as a locate contradiction → block, not a silent skip)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 0)
        self.assertEqual(session.applied, [])
        self.assertFalse(result["plan"][0].get("skipped"))  # NOT a benign skip
        self.assertTrue(result["plan"][0].get("blocker"))


class FailClosedLocateTests(unittest.TestCase):
    def test_identity_contradiction_blocks_and_feeds_guard(self):
        # id 100 present but its row contradicts the plan (different url) and the
        # plan url is not in the feed → a real doubt, fail-closed (guard failure)
        session = FakeMoveSession([["100"]], rows={"100": {"url": "https://m/wrong"}})
        result = _run(Mover, session, _plan("100"))  # plan url = https://m/100
        self.assertEqual(result["moved"], 0)
        self.assertTrue(result["plan"][0].get("blocker"))
        self.assertFalse(result["plan"][0].get("skipped"))
        self.assertEqual(session.applied, [])

    def test_absent_reconfirmed_by_full_scan_then_relocated(self):
        # MV8: id 999 sits on page 4, but the start index early-terminates
        # (pages 2-3 add no new ids) → locate-miss; the targeted scan finds it.
        pages = [["999", "1"], ["1"], ["1"], ["1"]]  # 999 only on p1 here — see below
        # Reframe: 999 is on a LATER page the early-terminate never reached.
        pages = [["1"], ["1"], ["1"], ["999"]]
        session = FakeMoveSession(pages)
        result = _run(Mover, session, _plan("999"))
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["plan"][0]["current_offer_id"], "999")

    def test_absent_offer_skipped_after_proven_full_scan(self):
        session = FakeMoveSession([["1"], ["2"], ["3"]])  # 999 nowhere
        result = _run(Mover, session, _plan("999"))
        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["move_attempts"], 0)
        self.assertIn("proven by full scan", result["plan"][0]["skipped"])


class DryRunGuardTests(unittest.TestCase):
    def test_dry_run_over_ten_offers_does_not_self_block(self):
        # MV4: 12 selectable offers must ALL appear, no guard_blocked truncation.
        ids = [str(100 + i) for i in range(12)]
        session = FakeMoveSession([ids])
        result = _run(DryRunMover, session, _plan(*ids))
        self.assertEqual(len(result["plan"]), 12)
        self.assertIsNone(result["stopped"])
        self.assertTrue(all(e["selectable"] for e in result["plan"]))


if __name__ == "__main__":
    unittest.main()
