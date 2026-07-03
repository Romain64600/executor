import re
import unittest

from src.submitter import DryRunSubmitter


def _cand(offer_id, region_id="2", edition_id="1"):
    return {
        "fingerprint": f"{offer_id}|1|{region_id}|{edition_id}",
        "offer": {
            "offer_id": offer_id, "name": f"Game {offer_id}", "url": "https://m/x",
            "merchant": "Driffle", "store_id": "127", "price": None, "stock": None,
        },
        "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": f"Game {offer_id}",
        "platform": "STEAM",
        "region": {"label": "GLOBAL", "id": region_id, "implicit": False},
        "edition": {"label": "Standard", "id": edition_id},
    }


class FakeSubmitSession:
    def __init__(self, pages, *, login=False, modal_status="OPENED",
                 select_names=("offer[region]", "offer[edition]"), ctx_ok=True, fail_ids=()):
        self.pages = pages
        self.login = login
        self.modal_status = modal_status
        self.select_names = list(select_names)
        self.ctx_ok = ctx_ok
        self.fail_ids = set(fail_ids)
        self.nav = []
        self._page = 0

    def navigate(self, url, settle=0):
        self.nav.append(url)
        m = re.search(r"[&?]p=(\d+)", url)
        self._page = (int(m.group(1)) - 1) if m else 0

    def is_login_page(self):
        return self.login

    def page_offer_ids(self):
        return list(self.pages[self._page]) if 0 <= self._page < len(self.pages) else []

    def open_offer_modal(self, offer_id):
        return "ROW_NOT_FOUND" if offer_id in self.fail_ids else self.modal_status

    def modal_context(self):
        return {"ok": self.ctx_ok, "select_names": list(self.select_names)}


def _run(session, approved):
    return DryRunSubmitter(session).run(
        run_id="r", merchant="Driffle", store_id="127", approved=approved, pace=0
    )


class DryRunTests(unittest.TestCase):
    def test_login_preflight_aborts(self):
        result = _run(FakeSubmitSession([["1"]], login=True), [_cand("1")])
        self.assertEqual(result["aborted"], "not_logged_in")
        self.assertEqual(result["plan"], [])

    def test_ready_plan(self):
        result = _run(FakeSubmitSession([["1", "2"]]), [_cand("1"), _cand("2")])
        self.assertIsNone(result["aborted"])
        self.assertIsNone(result["stopped"])
        self.assertTrue(all(p["ready"] for p in result["plan"]))
        self.assertEqual(result["feed_offers"], 2)
        self.assertIn("offer[region]=2", result["plan"][0]["would_submit"])

    def test_offer_not_in_feed_is_skipped(self):
        result = _run(FakeSubmitSession([["1"]]), [_cand("1"), _cand("9")])
        by_id = {p["offer_id"]: p for p in result["plan"]}
        self.assertTrue(by_id["1"]["ready"])
        self.assertFalse(by_id["9"]["ready"])
        self.assertIn("not in current feed", by_id["9"]["blocker"])

    def test_modal_open_failure_is_skipped(self):
        result = _run(FakeSubmitSession([["1", "2"]], fail_ids={"2"}), [_cand("1"), _cand("2")])
        by_id = {p["offer_id"]: p for p in result["plan"]}
        self.assertTrue(by_id["1"]["ready"])
        self.assertFalse(by_id["2"]["ready"])

    def test_region_select_missing_is_skipped(self):
        result = _run(FakeSubmitSession([["1"]], select_names=("offer[edition]",)), [_cand("1")])
        self.assertFalse(result["plan"][0]["ready"])
        self.assertIn("select not found", result["plan"][0]["blocker"])

    def test_region_id_select_convention(self):
        session = FakeSubmitSession([["1"]], select_names=("offer[region_id]", "offer[edition_id]"))
        result = _run(session, [_cand("1")])
        self.assertTrue(result["plan"][0]["ready"])
        self.assertEqual(result["plan"][0]["region_select"], "offer[region_id]")

    def test_stops_after_ten_consecutive_failures(self):
        ids = [str(i) for i in range(12)]
        session = FakeSubmitSession([ids], fail_ids=set(ids))
        result = _run(session, [_cand(i) for i in ids])
        self.assertEqual(result["stopped"], "ten_consecutive_failures")
        self.assertEqual(len(result["plan"]), 10)  # stopped after the 10th consecutive failure


if __name__ == "__main__":
    unittest.main()
