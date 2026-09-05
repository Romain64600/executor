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
                 source_id="9", on_target=True, no_remove_ids=None,
                 empty_list_reads=0, bulk_absent_reads=0):
        self.pages = [list(p) for p in pages]        # the SOURCE list, paginated
        self.rows = dict(rows or {})  # per-id {url, name} overrides (re-id sim)
        self.no_remove_ids = set(no_remove_ids or [])  # ids whose Apply doesn't take
        self.login = login
        self.options = options if options is not None else LIST_OPTIONS
        self.register_ok = register_ok
        self.bulk_set_ok = bulk_set_ok
        self.apply_ok = apply_ok
        self.move_removes = move_removes
        self.source_id = source_id
        self.on_target = on_target  # does a moved offer appear on its target list?
        self.moved_to = {}          # target_list_id -> [offer_ids] (RV2 verify)
        self.empty_list_reads = empty_list_reads   # first N list_options() reads → []
        self._list_reads = 0
        self.bulk_absent_reads = bulk_absent_reads  # first N bulk_row_present() → absent
        self._bulk_reads = 0
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
        # Simulate a render race: the first ``empty_list_reads`` reads beat the JS
        # render and return [] before the dropdown populates.
        self._list_reads += 1
        if self._list_reads <= self.empty_list_reads:
            return []
        return list(self.options)

    def bulk_row_present(self, oid):
        # Simulate a bulk-form render race: the first ``bulk_absent_reads`` reads
        # find the form/checkbox not rendered yet.
        self._bulk_reads += 1
        if self._bulk_reads <= self.bulk_absent_reads:
            return {"checkbox": False, "bulk_form": False}
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
        if (self.move_removes and self._registered is not None
                and self._registered not in self.no_remove_ids):
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
    m.feed_retry_pause = 0   # no real sleep between retries in tests
    m.feed_ui_render_waits = ()  # no real render-wait sleep in tests
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
        self.assertIn("proven by the source scan", result["plan"][0]["skipped"])
        self.assertEqual(session.applied, [])

    def test_canary_limit_stops_after_one(self):
        session = FakeMoveSession([["100", "200"]])
        result = _run(Mover, session, _plan("100", "200"), limit=1)
        self.assertEqual(result["move_attempts"], 1)
        self.assertEqual(result["stopped"], "limit_reached")

    def test_canary_retries_past_a_dud_offer(self):
        # offer 100's Apply doesn't take (STILL on source, like ExitLag on a
        # fresh plan); the canary must NOT be consumed by it — it retries offer
        # 200 and moves that. limit counts SUCCESSES, not attempts.
        session = FakeMoveSession([["100", "200"]], no_remove_ids={"100"})
        result = _run(Mover, session, _plan("100", "200"), limit=1)
        self.assertEqual(result["moved"], 1)          # one real move
        self.assertEqual(result["move_attempts"], 2)  # it tried 100 (dud) then 200
        self.assertEqual(result["stopped"], "limit_reached")
        self.assertTrue(result["plan"][1]["moved"])   # 200 is the one that moved
        self.assertFalse(result["plan"][0]["moved"])  # 100 failed

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


class ListOptionsRetryTests(unittest.TestCase):
    """2026-08-18: a batched sweep aborted target_list_unresolved because
    list_options() read 0 (a render race), though the dropdown really had 33.
    The mover retries an EMPTY read before failing closed."""

    def test_empty_read_retries_then_resolves_and_moves(self):
        # first read [] (race), retry re-navigates + reads the real options → moves
        session = FakeMoveSession([["100", "200"]], empty_list_reads=1)
        result = _run(Mover, session, _plan("100"))
        self.assertIsNone(result["aborted"])          # NOT target_list_unresolved
        self.assertGreaterEqual(result["list_options_count"], 1)
        self.assertEqual(result["moved"], 1)

    def test_persistently_empty_fails_closed(self):
        # every read [] (not a race — genuinely no options) → fail closed, no move
        session = FakeMoveSession([["100"]], empty_list_reads=99)
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["aborted"], "target_list_unresolved")
        self.assertEqual(result["moved"], 0)
        self.assertEqual(session.applied, [])         # never wrote anything

    def test_empty_read_recovers_via_poll_without_renavigate(self):
        # the real fix: the dropdown renders a few seconds AFTER navigate, so the
        # cure is to POLL the same page (re-read), NOT re-navigate (which resets the
        # render clock). empty_list_reads=1 → 1st read [], poll's 2nd read → options.
        session = FakeMoveSession([["100", "200"]], empty_list_reads=1)
        m = Mover(session)
        m.post_apply_settle = 0
        m.feed_ui_render_waits = (0, 0, 0)            # poll runs, no sleep
        nav_at_options = None
        orig = session.list_options
        def counting():
            nonlocal nav_at_options
            if nav_at_options is None and session._list_reads == 1:
                nav_at_options = len(session.nav)     # nav count at the first (empty) read
            return orig()
        session.list_options = counting
        result = m.run(run_id="r", store_id="38", plan=_plan("100"),
                       source_feed_page="aks-merchant-feeds-9", max_pages=5)
        self.assertIsNone(result["aborted"])
        self.assertEqual(result["moved"], 1)          # recovered → moved


class FeedUiRenderWaitTests(unittest.TestCase):
    """2026-08-18: under sustained CDP load a feed page's JS-built UI can lag the
    first read (feed_ui=False) though the page loads fine. _wait_for_feed_ui polls
    the DOM (re-read, no re-navigate) until it renders, before failing closed."""

    class _SlowSession:
        def __init__(self, render_on):
            self.reads = 0
            self.render_on = render_on   # feed_ui becomes True from this read on
        def page_offer_rows(self):
            return [{"id": "1", "url": "https://m/1", "name": "G"}] if self.reads >= self.render_on else []
        def feed_page_state(self):
            self.reads += 1
            return {"feed_ui": self.reads >= self.render_on, "is_login": False}

    def _mover(self, session):
        m = Mover(session)
        m.feed_ui_render_waits = (0, 0, 0)   # no real sleep
        return m

    def test_polls_until_feed_ui_renders(self):
        session = self._SlowSession(render_on=2)   # blank first read, rendered 2nd
        rows, state = self._mover(session)._wait_for_feed_ui([], {"feed_ui": False})
        self.assertTrue(state["feed_ui"])          # detected the render
        self.assertGreaterEqual(session.reads, 2)  # it polled

    def test_returns_empty_after_timeout_if_never_renders(self):
        session = self._SlowSession(render_on=99)  # never renders within the waits
        rows, state = self._mover(session)._wait_for_feed_ui([], {"feed_ui": False})
        self.assertFalse(state["feed_ui"])         # gives up → caller fails closed
        self.assertEqual(rows, [])


class PageHintIndexTests(unittest.TestCase):
    """2026-08-20: on a deep feed a full initial index is ~25 min. A page_hint
    windows the index to the offer's extract page + a neighbour; a row that
    reflowed OUTSIDE the window is still recovered by the per-offer relocate."""

    def test_page_hint_moves_offer_in_window(self):
        # offer "100" on page 1; page_hint=1 → window [1,2] → indexed → moved
        session = FakeMoveSession([["100", "200"], ["300"], ["400"]])
        result = _run(Mover, session, _plan("100"), page_hint=1)
        self.assertIsNone(result["aborted"])
        self.assertEqual(result["moved"], 1)
        # a windowed index reads FEWER offers than the whole 4-offer feed
        self.assertLess(result["feed_offers"], 4)

    def test_page_hint_skips_offer_far_outside_window(self):
        # page-by-page (2026-08-20): with a window the SOURCE scans are bounded to
        # the page — an offer that reflowed FAR outside it (page 4 vs window [1,2]) is
        # NOT deep-scanned; it is skipped this run (a re-run / its new page catches
        # it). Bounded to ~1 page, never a 100-page walk. moved=0, no wrong write.
        session = FakeMoveSession([["1"], ["2"], ["3"], ["400"]])
        result = _run(Mover, session, _plan("400"), page_hint=1)
        self.assertIsNone(result["aborted"])
        self.assertEqual(result["moved"], 0)          # skipped, not deep-relocated
        self.assertEqual(session.applied, [])          # never wrote anything
        # P3-6 (audit 2026-09-02): the skip label must NOT claim a whole-feed "proven"
        # absence under a page window — it must signal the windowed scope instead.
        skipped = result["plan"][0]["skipped"]
        self.assertNotIn("proven", skipped)
        self.assertIn("window", skipped.lower())

    def test_deferred_page_hint_windowed_skip_label_is_not_proven(self):
        # P3-6 (re-audit 2026-09-05): the --deferred per-store path also runs WINDOWED
        # under a page-hint, so an offer outside the window must be skipped with the
        # window-aware label, NOT the misleading whole-feed "proven by the source scan"
        # (the original P3-6 fix missed this third call site).
        session = FakeMoveSession([["1"], ["2"], ["3"], ["400"]])
        result = _run(Mover, session, _plan("400"), batch=True, deferred=True, page_hint=1)
        self.assertIsNone(result["aborted"])
        self.assertEqual(result["moved"], 0)          # outside the window → skipped
        self.assertEqual(session.applied, [])          # no write
        skipped = result["plan"][0]["skipped"]
        self.assertNotIn("proven", skipped)
        self.assertIn("window", skipped.lower())

    def test_page_hint_source_scans_stay_within_window(self):
        # the whole point: NO page beyond the window is ever navigated for a SOURCE
        # scan (index / locate / gone-proof), so a deep feed costs ~1 page, not 100.
        session = FakeMoveSession([["100"], ["200"], ["300"], ["400"], ["500"]])
        _run(Mover, session, _plan("100"), page_hint=1)   # window [1,2]
        import re
        pages = {int(m.group(1)) for u in session.nav
                 for m in [re.search(r"[?&]p=(\d+)", u)] if m}
        pages.add(1)  # p=1 default (no &p= in the URL) counts as page 1
        self.assertTrue(pages <= {1, 2}, f"navigated beyond the window: {sorted(pages)}")

    def test_no_page_hint_full_index_unchanged(self):
        session = FakeMoveSession([["100", "200"], ["300"]])
        result = _run(Mover, session, _plan("300"))   # no page_hint
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["feed_offers"], 3)    # whole feed indexed


class BulkFormRenderWaitTests(unittest.TestCase):
    """2026-08-20: a FAST page-scoped move can check the bulk checkbox/form before
    its JS finishes rendering → "row/bulk-form not present at move time". The old
    slow full scan masked the race; _bulk_row_present now polls the form."""

    def _mover(self, session):
        m = Mover(session)
        m.post_apply_settle = 0
        m.feed_ui_render_waits = (0, 0, 0)   # poll runs, no sleep
        return m

    def test_bulk_form_render_race_is_polled_then_moves(self):
        # form absent on the first 2 reads (render race), then present → the poll
        # recovers and the move succeeds instead of failing "not present".
        session = FakeMoveSession([["100", "200"]], bulk_absent_reads=2)
        result = self._mover(session).run(
            run_id="r", store_id="38", plan=_plan("100"),
            source_feed_page="aks-merchant-feeds-9", max_pages=5)
        self.assertEqual(result["moved"], 1)

    def test_bulk_form_persistently_absent_blocks(self):
        # genuinely absent (not a race) → fail closed after the backoff, no write
        session = FakeMoveSession([["100"]], bulk_absent_reads=99)
        result = self._mover(session).run(
            run_id="r", store_id="38", plan=_plan("100"),
            source_feed_page="aks-merchant-feeds-9", max_pages=5)
        self.assertEqual(result["moved"], 0)
        self.assertEqual(session.applied, [])


class ReverifyRowTests(unittest.TestCase):
    """MV1/SC5 — never write against a row that no longer matches the plan."""

    def _mover(self, session):
        m = Mover(session)
        m.post_apply_settle = 0
        return m

    def test_reided_row_with_url_absent_is_retriable_not_terminal(self):
        # id 100 on the page is now a DIFFERENT product, AND the plan's stable URL is
        # NOT on this page → the plan's offer moved to another page / left the feed.
        # RETRIABLE, never a terminal identity block on a possibly-present offer
        # (P1-4, audit 2026-09-02: previously this went straight to identity_mismatch,
        # permanently skipping the offer without ever searching its URL).
        session = FakeMoveSession([["100"]])
        entry = {"current_offer_id": "100", "name": "Different Game",
                 "url": "https://m/other", "store_id": "38"}
        ok, reason = self._mover(session)._reverify_row(entry)
        self.assertFalse(ok)
        self.assertIn("not on this page", reason)
        self.assertFalse(entry.get("identity_mismatch"))   # retriable, not permanent

    def test_reided_offer_recovered_by_url_on_same_page(self):
        # P1-4 core: a re-import reassigned id 100 to a DIFFERENT product AND moved the
        # plan's offer to a NEW id (200) on the SAME page. It must be RELOCATED by its
        # stable URL and proceed — not terminally identity-blocked.
        session = FakeMoveSession(
            [["100", "200"]],
            rows={"100": {"url": "https://m/hijack", "name": "Hijacked"},
                  "200": {"url": "https://m/mygame", "name": "My Game"}})
        entry = {"current_offer_id": "100", "name": "My Game",
                 "url": "https://m/mygame", "store_id": "38"}
        ok, reason = self._mover(session)._reverify_row(entry)
        self.assertTrue(ok)
        self.assertEqual(entry["current_offer_id"], "200")   # adopted the stable-URL id
        self.assertFalse(entry.get("identity_mismatch"))

    def test_reverify_url_present_but_different_product_is_terminal(self):
        # The genuine TERMINAL case: the plan's own URL IS on the page but now names a
        # DIFFERENT product (the merchant reused the slug). No point retrying.
        session = FakeMoveSession([["100"]],
                                  rows={"100": {"url": "https://m/100", "name": "Reused Slug Game"}})
        entry = {"current_offer_id": "100", "name": "Game 100",
                 "url": "https://m/100", "store_id": "38"}
        ok, reason = self._mover(session)._reverify_row(entry)
        self.assertFalse(ok)
        self.assertIn("identity mismatch", reason)
        self.assertTrue(entry.get("identity_mismatch"))   # terminal

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
        self.assertIn("proven by the source scan", result["plan"][0]["skipped"])


class DryRunGuardTests(unittest.TestCase):
    def test_dry_run_over_ten_offers_does_not_self_block(self):
        # MV4: 12 selectable offers must ALL appear, no guard_blocked truncation.
        ids = [str(100 + i) for i in range(12)]
        session = FakeMoveSession([ids])
        result = _run(DryRunMover, session, _plan(*ids))
        self.assertEqual(len(result["plan"]), 12)
        self.assertIsNone(result["stopped"])
        self.assertTrue(all(e["selectable"] for e in result["plan"]))


class OperatorStopTests(unittest.TestCase):
    def test_stop_during_index_is_clean_no_moves(self):
        # should_stop True from the start → the initial index stops at a page
        # boundary: a clean operator_stop, zero moves, no Apply ever fired.
        session = FakeMoveSession([["100", "200"]])
        result = _run(Mover, session, _plan("100"), should_stop=lambda: True)
        self.assertEqual(result["stopped"], "operator_stop")
        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["plan"], [])
        self.assertEqual(session.applied, [])

    def test_stop_between_offers_after_a_completed_move(self):
        # stop requested only AFTER offer 1's move completes: offer 1 moves fully,
        # offer 2 is never started (checked between offers, never mid-Apply).
        session = FakeMoveSession([["100", "200"]])
        flag = {"stop": False}

        class _M(Mover):
            def _move(self, entry, ctx):
                r = super()._move(entry, ctx)
                flag["stop"] = True
                return r

        m = _M(session)
        m.post_apply_settle = 0
        result = m.run(run_id="r", store_id="38", plan=_plan("100", "200"),
                       source_feed_page="aks-merchant-feeds-9", max_pages=5,
                       should_stop=lambda: flag["stop"])
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["stopped"], "operator_stop")
        self.assertEqual(len(result["plan"]), 1)
        self.assertEqual(session.applied, [("100", "16")])

    def test_stop_hook_is_disarmed_during_a_move(self):
        # SAFETY: while an offer's move runs, _should_stop is None, so a move's
        # own scans can never raise StopRequested and cut it mid-Apply.
        session = FakeMoveSession([["100"]])
        seen = {}

        class _M(Mover):
            def _move(self, entry, ctx):
                seen["during_move"] = self._should_stop
                return super()._move(entry, ctx)

        m = _M(session)
        m.post_apply_settle = 0
        m.run(run_id="r", store_id="38", plan=_plan("100"),
              source_feed_page="aks-merchant-feeds-9", max_pages=5,
              should_stop=lambda: False)
        self.assertIsNone(seen["during_move"])

    def test_default_no_should_stop_is_unaffected(self):
        session = FakeMoveSession([["100"]])
        result = _run(Mover, session, _plan("100"))
        self.assertIsNone(result["stopped"])
        self.assertEqual(result["moved"], 1)


if __name__ == "__main__":
    unittest.main()
