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
                 bulk_set_ok=True, apply_ok=True, move_removes=True):
        self.pages = [list(p) for p in pages]
        self.login = login
        self.options = options if options is not None else LIST_OPTIONS
        self.register_ok = register_ok
        self.bulk_set_ok = bulk_set_ok
        self.apply_ok = apply_ok
        self.move_removes = move_removes
        self.nav = []
        self._page = 0
        self._registered = None
        self._bulk_list = None
        self.applied = []

    # --- read surface ---
    def navigate(self, url, settle=3.0):
        import re
        self.nav.append(url)
        m = re.search(r"[&?]p=(\d+)", url)
        self._page = (int(m.group(1)) - 1) if m else 0

    def is_login_page(self):
        return self.login

    def _row(self, oid):
        return {"id": oid, "url": f"https://m/{oid}", "name": f"Game {oid}",
                "price": "", "store_id": "38"}

    def page_offer_rows(self):
        if 0 <= self._page < len(self.pages):
            return [self._row(i) for i in self.pages[self._page]]
        return []

    def feed_page_state(self):
        nav_max = max((i + 1 for i, p in enumerate(self.pages) if p), default=0)
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
        # a real Apply POSTs and the offer leaves the source list
        if self.move_removes and self._registered is not None:
            for p in self.pages:
                if self._registered in p:
                    p.remove(self._registered)
        self.applied.append((self._registered, self._bulk_list))
        return {"status": "CLICKED"}


def _plan(*offer_ids, label="Softwares", list_id="16"):
    return [{"offer_id": str(o), "name": f"Game {o}", "url": f"https://m/{o}",
             "target_list_id": list_id, "target_list_label": label} for o in offer_ids]


def _run(mover_cls, session, plan, **kw):
    return mover_cls(session).run(run_id="r", store_id="38", plan=plan,
                                  source_feed_page="aks-merchant-feeds-9",
                                  max_pages=5, **kw)


class ResolveListIdTests(unittest.TestCase):
    def test_label_match_authoritative(self):
        r = resolve_list_id("Softwares", "999", LIST_OPTIONS)
        self.assertEqual(r["id"], "16")  # label wins over the stale hint id

    def test_move_to_prefix_tolerated(self):
        self.assertEqual(resolve_list_id("Move to Gift cards", "", LIST_OPTIONS)["id"], "21")

    def test_unknown_label_is_none(self):
        self.assertIsNone(resolve_list_id("Nonexistent List", "16", LIST_OPTIONS))
        self.assertIsNone(resolve_list_id("", "16", LIST_OPTIONS))


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
    def test_move_confirmed_by_disappearance(self):
        session = FakeMoveSession([["100", "200"]])
        result = _run(Mover, session, _plan("100"))
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["move_attempts"], 1)
        entry = result["plan"][0]
        self.assertTrue(entry["moved"])
        self.assertEqual(entry["post_verify"], "gone from source list")
        self.assertEqual(session.applied, [("100", "16")])

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
        self.assertIn("offer not in current feed", result["plan"][0]["skipped"])
        self.assertEqual(session.applied, [])

    def test_canary_limit_stops_after_one(self):
        session = FakeMoveSession([["100", "200"]])
        result = _run(Mover, session, _plan("100", "200"), limit=1)
        self.assertEqual(result["move_attempts"], 1)
        self.assertEqual(result["stopped"], "limit_reached")

    def test_relocated_by_url_when_id_rotated(self):
        # the plan's id 100 no longer exists; the same URL now has id 900
        session = FakeMoveSession([["900"]])
        plan = [{"offer_id": "100", "name": "Game 900", "url": "https://m/900",
                 "target_list_id": "16", "target_list_label": "Softwares"}]
        result = _run(Mover, session, plan)
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["plan"][0]["current_offer_id"], "900")
        self.assertEqual(session.applied, [("900", "16")])


if __name__ == "__main__":
    unittest.main()
