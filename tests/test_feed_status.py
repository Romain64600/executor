import json
import tempfile
import unittest
from pathlib import Path

from src.feed_status import build_report, categorize_reason, created_by_day, find_sweeps


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


class CategorizeReasonTests(unittest.TestCase):
    def test_taxonomy(self):
        cases = {
            "console": "console",
            "no AKS product page found (slug not 200)": "no_page",
            "DLC in title but AKS page 'x' carries no DLC edition — base game or wrong product, not entered (R43)": "dlc_no_own_page",
            "DLC in title": "dlc_no_own_page",
            "skip category: BUNDLE (no bundles/skins)": "bundle",
            "possible multi-game bundle": "bundle",
            "skip category: POINTS": "currency",
            "skip category: GIFT CARD": "prepaid",
            "skip category: PASS (in-game/battle pass)": "pass",
            "skip category: SUBSCRIPTION": "subscription",
            "skip category: MICROSOFT STORE": "microsoft",
            "forbidden region: RUSSIA": "region",
            "different/expanded product — extra words: ['ULTIMATE']": "variant",
            "name mismatch, missing AKS words: ['BUNDLE']": "wrong_page",
            "no platform in title and AKS page does not confirm Direct Publisher — platform unverifiable, not defaulted": "platform",
            "software edition unresolved on the AKS page": "software",
            "AKS page carries no editions map — edition unverifiable (R19)": "stub_page",
            "no region id for ROCKSTAR/GLOBAL": "rockstar",
            "AKS probe unreliable (throttled?): site search -> timeout": "transient",
            "region US read from 'UNITED STATES', which is part of the AKS product name — region ambiguous, not entered (R44)": "region_ambiguous",
            "dangerous qualifier absent from AKS name: REMASTERED": "qualifier",
            "something new": "other",
        }
        for reason, key in cases.items():
            self.assertEqual(categorize_reason(reason), key, reason)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self.tmp.name)
        # sweep 1 (older) — 2 pages
        _write(self.runs / "20260910-170123-auto" / "recap.json", {
            "run_id": "20260910-170123-auto", "started_at": "2026-09-10T17:01:23Z", "finished_at": "2026-09-11T03:00:14Z",
            "halted": None, "total_created": 3,
            "targets": [{"merchant": "MMOGA", "store_id": "12", "recap": {"merchant": "MMOGA", "halted": None, "coverage": None, "total_created": 3,
                "pages": [{"page": 2, "run": "20260910-170123-auto-mmoga-s12-p2", "offers": 100, "candidates": 2, "created": 2},
                          {"page": 1, "run": "20260910-170123-auto-mmoga-s12-p1", "offers": 100, "candidates": 1, "created": 1}]}}]})
        _write(self.runs / "20260910-170123-auto-mmoga-s12-p2" / "submit_plan.json", {"plan": [
            {"merchant_title": "Game A", "aks_url": "https://www.allkeyshop.com/blog/buy-game-a-cd-key-compare-prices/", "edition_text": "Standard", "region_text": "Steam (2)", "submitted": True},
            {"merchant_title": "Game B", "aks_url": "https://www.allkeyshop.com/blog/buy-game-b-cd-key-compare-prices/", "edition_text": "Deluxe", "region_text": "Steam (2)", "submitted": True}]})
        _write(self.runs / "20260910-170123-auto-mmoga-s12-p1" / "submit_plan.json", {"plan": [
            {"merchant_title": "Game C", "aks_url": "https://www.allkeyshop.com/blog/buy-game-c-cd-key-compare-prices/", "edition_text": "Standard", "region_text": "Steam (2)", "submitted": True}]})
        # sweep 2 (latest) — 1 page, one refusal, skips
        _write(self.runs / "20260911-083407-auto" / "recap.json", {
            "run_id": "20260911-083407-auto", "started_at": "2026-09-11T08:34:07Z", "finished_at": "2026-09-11T08:55:00Z",
            "halted": None, "total_created": 1,
            "targets": [{"merchant": "MMOGA", "store_id": "12", "recap": {"merchant": "MMOGA", "halted": None, "coverage": None, "total_created": 1,
                "pages": [{"page": 1, "run": "20260911-083407-auto-mmoga-s12-p1", "offers": 5, "candidates": 2, "created": 1}]}}]})
        _write(self.runs / "20260911-083407-auto-mmoga-s12-p1" / "submit_plan.json", {"plan": [
            {"merchant_title": "Game D (DLC)", "aks_url": "https://www.allkeyshop.com/blog/buy-game-d-cd-key-compare-prices/", "edition_text": "DLC", "region_text": "Steam (2)", "submitted": True},
            {"merchant_title": "Game E", "aks_url": "https://www.allkeyshop.com/blog/buy-game-e-cd-key-compare-prices/", "edition_text": "Standard", "region_text": "Steam (2)", "submitted": False,
             "post_save": "create not confirmed: ERROR — Error: Bad request: paramètre \"offer\" manquant ou invalide."}]})
        _write(self.runs / "20260911-083407-auto-mmoga-s12-p1" / "skipped.json", [
            {"offer": {"name": "Halo Xbox One", "url": "https://www.mmoga.com/Xbox-Live/Halo.html"}, "reason": "console"},
            {"offer": {"name": "Halo 2 Xbox", "url": "https://www.mmoga.com/Xbox-Live/Halo-2.html"}, "reason": "console"},
            {"offer": {"name": "Unknown Game", "url": "https://www.mmoga.com/Steam-Games/Unknown.html"}, "reason": "no AKS product page found (slug not 200)"},
            {"offer": {"name": "Game F - DLC Pack", "url": "https://www.mmoga.com/Steam-Games/F.html"}, "reason": "skip category: DLC PACK (DLC collection — no bundles)"}])
        # a by-urls submit run for the same store
        _write(self.runs / "20260910-092830-by-urls-submit-s12" / "submit_plan.json", {"plan": [
            {"merchant_title": "Crusader Kings III", "aks_url": "https://www.allkeyshop.com/blog/buy-crusader-kings-3-cd-key-compare-prices/", "edition_text": "Standard", "region_text": "Steam (2)", "submitted": True}]})
        # another merchant's run must be ignored
        _write(self.runs / "20260909-121458-auto-gamivo-s51-p1" / "submit_plan.json", {"plan": [{"merchant_title": "X", "submitted": True}]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_sweeps_found_oldest_first(self):
        self.assertEqual([s for s, _ in find_sweeps(self.runs, "MMOGA")], ["20260910-170123-auto", "20260911-083407-auto"])
        self.assertEqual(find_sweeps(self.runs, "Gamivo"), [])

    def test_created_by_day_counts_pages_and_by_urls_only_for_the_store(self):
        by_day, editions, regions, total = created_by_day(self.runs, "MMOGA", "12")
        self.assertEqual(total, 5)
        self.assertEqual(by_day, {"20260910": 4, "20260911": 1})
        self.assertEqual(editions["Standard"], 3); self.assertEqual(editions["DLC"], 1); self.assertEqual(editions["Deluxe"], 1)
        self.assertEqual(regions["Steam (2)"], 5)

    def test_markdown_sections(self):
        md = build_report(self.runs, "MMOGA", "12", generated_at="2026-09-11 15:00 UTC")
        self.assertIn("# État du feed — MMOGA (store 12)", md)
        self.assertIn("`20260911-083407-auto`", md)                      # last pass
        self.assertIn("**Total : 5 offres créées**", md)
        self.assertIn("Game E — create not confirmed", md)                # not created listed
        self.assertIn("| Consoles (Xbox / PlayStation / Switch) | 2 |", md)
        self.assertIn("| Sans page produit AKS | 1 |", md)
        self.assertIn("| Bundles / packs multi-jeux | 1 |", md)
        self.assertIn("Game D (DLC) → `game-d-cd-key-compare-prices`", md)
        self.assertNotIn("gamivo", md.lower())
        # deterministic
        self.assertEqual(md, build_report(self.runs, "MMOGA", "12", generated_at="2026-09-11 15:00 UTC"))

    def test_no_sweep_yet(self):
        md = build_report(self.runs, "Kinguin", "58", generated_at="x")
        self.assertIn("Aucun passage safe-auto enregistré", md)
        self.assertIn("**Total : 0 offres créées**", md)


if __name__ == "__main__":
    unittest.main()
