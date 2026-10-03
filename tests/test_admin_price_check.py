"""Price check — the admin page of the first-price monitor's reports (2026-10-01).

Romain: « ce rapport interactif de price check devrait être dans l'admin ». The price-check
monitor writes reports.json into a shared directory; the admin reads it and appends the
operator's decisions to decisions.jsonl, which the monitor re-reads before its next pass.
These tests hold the contract of both files and the guards of the two routes.
"""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from src.admin import price_check_io as pc
from tests.test_admin_app import AppTestCase

TORO = {
    "offer": "140421891", "verdict": "SUSPECT", "product": "TORO 2 Nintendo Switch",
    "edition": "Standard", "merchant": "Nintendo eShop FR", "price": 5.99, "region": "GLOBAL",
    "region_filter": "", "platform": "nintendo-eshop",
    "reasons": ["autre produit chez le marchand : « Metal Garden » au lieu de "
                "« TORO 2 Nintendo Switch » (URL de la version en-GB)"],
    "notes": [], "method": "URL de la version en-GB",
    "merchant_url": "https://www.nintendo.com/fr-fr/Jeux/Jeux-a-telecharger/Metal-Garden-3177422.html",
    "page_url": "https://www.allkeyshop.com/blog/buy-toro-2-nintendo-switch-compare-prices/",
    "list": "TOP 50 · Nintendo Popular", "rank": 56, "at": "2026-09-30 16:15", "decision": None,
}
AMAZON = dict(TORO, offer="140500001", verdict="NON VÉRIFIABLE", merchant="Amazon",
              reasons=["nom du produit introuvable (URL)"], merchant_url="https://www.amazon.fr/dp/B0X")


def write_export(directory, reports=None, **extra):
    payload = {"generated_at": "2026-10-01T12:38:40+0200",
               "decisions": dict(pc.DEFAULT_DECISIONS),
               "reports": [TORO, AMAZON] if reports is None else reports}
    payload.update(extra)
    (directory / pc.REPORTS_FILE).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def monitor_reads(directory):
    """The monitor's own acceptance rule (price_check.read_decisions), replayed: the last valid
    line per offer wins, a digit offer id and a known decision are required."""

    known = set(pc.DEFAULT_DECISIONS)
    out = {}
    for line in (directory / pc.DECISIONS_FILE).read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and str(d.get("offer", "")).isdigit() and d.get("decision") in known:
            out[str(d["offer"])] = {k: d.get(k) for k in ("decision", "note", "by", "at")}
    return out


class _Dir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)


class ReadReportsTests(_Dir):
    def test_a_missing_export_is_an_error_never_an_empty_list(self):
        with self.assertRaises(pc.PriceCheckError) as ctx:
            pc.load_reports(self.dir)
        self.assertEqual((ctx.exception.code, ctx.exception.http_status), ("no_reports", 404))

    def test_a_broken_export_is_refused(self):
        (self.dir / pc.REPORTS_FILE).write_text('{"reports": [', encoding="utf-8")
        with self.assertRaises(pc.PriceCheckError) as ctx:
            pc.load_reports(self.dir)
        self.assertEqual((ctx.exception.code, ctx.exception.http_status), ("bad_reports", 500))
        (self.dir / pc.REPORTS_FILE).write_text('{"generated_at": "x"}', encoding="utf-8")
        with self.assertRaises(pc.PriceCheckError):
            pc.load_reports(self.dir)

    def test_reports_come_with_the_latest_decision_and_its_history(self):
        write_export(self.dir)
        pc.record_decision(self.dir, "140421891", "a_discuter", "", by="romain",
                           clock=lambda: "2026-10-01T12:40:00+02:00")
        pc.record_decision(self.dir, "140421891", "vrai", "Metal Garden", by="remi",
                           clock=lambda: "2026-10-01T12:45:00+02:00")
        out = pc.load_reports(self.dir)
        toro = next(r for r in out["reports"] if r["offer"] == "140421891")
        self.assertEqual(toro["decision"], {"decision": "vrai", "note": "Metal Garden", "by": "remi",
                                            "at": "2026-10-01T12:45:00+02:00"})
        self.assertEqual([h["decision"] for h in toro["history"]], ["a_discuter", "vrai"])
        amazon = next(r for r in out["reports"] if r["offer"] == "140500001")
        self.assertIsNone(amazon["decision"])
        self.assertEqual(amazon["history"], [])
        self.assertEqual(out["decisions"], pc.DEFAULT_DECISIONS)
        self.assertEqual(out["generated_at"], "2026-10-01T12:38:40+0200")
        self.assertIsInstance(out["age_seconds"], int)

    def test_the_monitor_copy_of_a_decision_stands_when_the_file_has_none(self):
        decided = dict(TORO, decision={"decision": "faux", "note": "", "by": "romain", "at": "x"})
        write_export(self.dir, [decided])
        self.assertEqual(pc.load_reports(self.dir)["reports"][0]["decision"]["decision"], "faux")

    def test_a_line_the_monitor_ignores_is_ignored_here_too(self):
        write_export(self.dir)
        lines = ['{"offer": "140421891", "decision": "vrai"',              # cut line
                 '{"offer": "140421891", "decision": "peut-etre"}',        # unknown decision
                 '{"offer": "14042189x", "decision": "vrai"}',             # bad offer id
                 '{"offer": "140421891", "decision": ["vrai"]}',           # not a string
                 '["140421891", "vrai"]']
        (self.dir / pc.DECISIONS_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = pc.load_reports(self.dir)
        self.assertTrue(all(r["decision"] is None and r["history"] == [] for r in out["reports"]))

    def test_seen_tells_how_long_ago_the_offer_last_led_its_page(self):
        write_export(self.dir, [dict(TORO, seen=1_000_000.0)])
        os.utime(self.dir / pc.REPORTS_FILE, (1_000_000 + 7200, 1_000_000 + 7200))
        report = pc.load_reports(self.dir, now=lambda: 1_000_000 + 7300)["reports"][0]
        self.assertEqual(report["seen_lag_seconds"], 7200)
        self.assertRegex(report["seen_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        write_export(self.dir, [TORO])  # un export d'avant le 01/10/2026, sans « seen »
        self.assertNotIn("seen_lag_seconds", pc.load_reports(self.dir)["reports"][0])

    def test_an_export_without_labels_falls_back_to_the_monitor_set(self):
        write_export(self.dir, decisions=None)
        self.assertEqual(pc.load_reports(self.dir)["decisions"], pc.DEFAULT_DECISIONS)


class RecordDecisionTests(_Dir):
    def setUp(self):
        super().setUp()
        write_export(self.dir)

    def test_a_decision_is_one_line_the_monitor_reads(self):
        entry = pc.record_decision(self.dir, 140421891, "vrai", "  Metal Garden  ", by="romain",
                                   clock=lambda: "2026-10-01T12:45:00+02:00")
        self.assertEqual(entry, {"offer": "140421891", "decision": "vrai", "note": "Metal Garden",
                                 "by": "romain", "at": "2026-10-01T12:45:00+02:00"})
        lines = (self.dir / pc.DECISIONS_FILE).read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line) for line in lines], [entry])
        self.assertEqual(monitor_reads(self.dir)["140421891"]["decision"], "vrai")

    def test_the_last_decision_wins_for_the_monitor(self):
        pc.record_decision(self.dir, "140421891", "vrai", "", by="romain")
        pc.record_decision(self.dir, "140421891", "faux", "page AKS bien DLC", by="romain")
        self.assertEqual(monitor_reads(self.dir)["140421891"]["decision"], "faux")
        self.assertEqual(len((self.dir / pc.DECISIONS_FILE).read_text(encoding="utf-8").splitlines()), 2)

    def test_refusals(self):
        cases = [
            (("abc", "vrai", ""), "bad_offer", 400),
            ((None, "vrai", ""), "bad_offer", 400),
            (("999", "vrai", ""), "unknown_offer", 404),
            (("140421891", "peut-etre", ""), "bad_decision", 400),
            (("140421891", ["vrai"], ""), "bad_decision", 400),
            (("140421891", "vrai", 12), "bad_note", 400),
            (("140421891", "vrai", "x" * (pc.MAX_NOTE + 1)), "bad_note", 400),
        ]
        for args, code, status in cases:
            with self.subTest(args=args[:2]):
                with self.assertRaises(pc.PriceCheckError) as ctx:
                    pc.record_decision(self.dir, *args, by="romain")
                self.assertEqual((ctx.exception.code, ctx.exception.http_status), (code, status))
        self.assertFalse((self.dir / pc.DECISIONS_FILE).exists(), "a refused decision wrote a line")

    def test_no_decision_without_a_readable_export(self):
        (self.dir / pc.REPORTS_FILE).unlink()
        with self.assertRaises(pc.PriceCheckError) as ctx:
            pc.record_decision(self.dir, "140421891", "vrai", "", by="romain")
        self.assertEqual(ctx.exception.code, "no_reports")
        self.assertFalse((self.dir / pc.DECISIONS_FILE).exists())

    def test_a_note_on_several_lines_stays_one_jsonl_line(self):
        pc.record_decision(self.dir, "140421891", "a_discuter", "ligne 1\nligne 2", by="romain")
        lines = (self.dir / pc.DECISIONS_FILE).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["note"], "ligne 1\nligne 2")


class PriceCheckRoutesTests(AppTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pc_dir = Path(tmp.name)
        self.state.price_check_dir = self.pc_dir

    def test_the_page_is_served_with_versioned_assets(self):
        for path in ("/price-check", "/pricecheck.html"):
            with self.subTest(path=path):
                response, data = self._request("GET", path)
                self.assertEqual(response.status, 200)
                html = data.decode("utf-8")
                self.assertRegex(html, r'pricecheck\.js\?v=[0-9a-f]{8}')
                self.assertRegex(html, r'pricecheck\.css\?v=[0-9a-f]{8}')
                self.assertRegex(html, r'auto\.css\?v=[0-9a-f]{8}')
        for asset in ("/pricecheck.js", "/pricecheck.css"):
            response, _ = self._request("GET", asset)
            self.assertEqual(response.status, 200, asset)

    def test_the_team_guide_is_a_page_of_the_admin(self):
        # Romain, 03/10/2026 : « je préférerais que tu l'intègres à l'admin. Quelqu'un qui a accès à l'admin a accès à
        # ce guide. » La page Price check y mène (en-tête, aide) ; le guide est servi par l'admin, en français et en anglais
        response, data = self._request("GET", "/price-check")
        page = data.decode("utf-8")
        self.assertIn('id="guide-link" class="topbar-link" href="price-check-guide"', page)
        self.assertNotIn("claude.ai/code/artifact", page)  # plus de lien vers une doc qu'il faudrait partager
        for path in ("/price-check-guide", "/pricecheck-guide", "/pricecheck-guide.html"):
            with self.subTest(path=path):
                response, data = self._request("GET", path)
                self.assertEqual(response.status, 200)
                html = data.decode("utf-8")
                self.assertRegex(html, r'pricecheck-guide\.js\?v=[0-9a-f]{8}')
                self.assertRegex(html, r'pricecheck-guide\.css\?v=[0-9a-f]{8}')
        self.assertIn('<article id="guide-fr" lang="fr"', html)
        self.assertIn('<article id="guide-en" lang="en"', html)
        for words in ("Les trois salons Discord", "The three Discord channels", "Une alerte est suivie jusqu’à sa réparation",
                      "An alert is followed until it is fixed"):
            self.assertIn(words, html)
        self.assertNotRegex(html, r"\sstyle=|<script>[^<]")  # rien en ligne : la CSP de l'admin le refuserait
        for link in re.findall(r'<a [^>]*href="https?://[^"]*"[^>]*>', html):
            self.assertIn('rel="noopener noreferrer"', link)
        for asset in ("/pricecheck-guide.js", "/pricecheck-guide.css"):
            response, _ = self._request("GET", asset)
            self.assertEqual(response.status, 200, asset)

    def test_the_reports_route(self):
        write_export(self.pc_dir)
        response, body = self._json("GET", "/api/price-check/reports")
        self.assertEqual(response.status, 200)
        self.assertEqual([r["offer"] for r in body["reports"]], ["140421891", "140500001"])
        self.assertEqual(body["dir"], str(self.pc_dir))

    def test_no_export_is_a_named_404(self):
        response, body = self._json("GET", "/api/price-check/reports")
        self.assertEqual(response.status, 404)
        self.assertEqual(body["error"]["code"], "no_reports")

    def test_a_decision_is_signed_by_the_authenticated_user_never_the_body(self):
        write_export(self.pc_dir)
        response, body = self._json("POST", "/api/price-check/decision",
                                    {"offer": "140421891", "decision": "vrai", "note": "Metal Garden",
                                     "by": "quelquun"})
        self.assertEqual(response.status, 200, body)
        self.assertEqual(body["recorded"]["by"], "operateur")
        self.assertEqual(monitor_reads(self.pc_dir)["140421891"]["by"], "operateur")
        _, after = self._json("GET", "/api/price-check/reports")
        self.assertEqual(after["reports"][0]["decision"]["decision"], "vrai")

    def test_the_csrf_guard_applies(self):
        write_export(self.pc_dir)
        response, body = self._json("POST", "/api/price-check/decision",
                                    {"offer": "140421891", "decision": "vrai"}, csrf=False)
        self.assertEqual(response.status, 403)
        self.assertEqual(body["error"]["code"], "csrf")
        self.assertFalse((self.pc_dir / pc.DECISIONS_FILE).exists())

    def test_no_identity_no_decision(self):
        write_export(self.pc_dir)
        response, body = self._json("POST", "/api/price-check/decision",
                                    {"offer": "140421891", "decision": "vrai"},
                                    headers={"Authorization": ""})
        self.assertEqual(response.status, 403)
        self.assertEqual(body["error"]["code"], "authentication_required")
        self.assertFalse((self.pc_dir / pc.DECISIONS_FILE).exists())

    def test_a_refused_decision_is_a_named_error(self):
        write_export(self.pc_dir)
        response, body = self._json("POST", "/api/price-check/decision",
                                    {"offer": "140421891", "decision": "peut-etre"})
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "bad_decision")


class RunRequestTests(AppTestCase):
    """Romain, 02/10/2026 : « on prépare les deux différents boutons » — Price check top / homepage. The admin
    writes a request file; the monitor (root, its own process) runs the pass. Nothing is executed here."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pc_dir = Path(tmp.name)
        self.state.price_check_dir = self.pc_dir

    def test_status_without_the_monitor_is_not_an_error(self):
        response, body = self._json("GET", "/api/price-check/status")
        self.assertEqual(response.status, 200)
        self.assertEqual((body["available"], body["modes"], body["pending"]),
                         (False, {}, {"top-games": None, "homepage": None}))

    def test_status_from_the_monitor_file(self):
        (self.pc_dir / "status.json").write_text(json.dumps({
            "offers": "top-offers", "updated_at": "2026-10-02T15:00:00+0200",
            "modes": {"top-games": {"label": "Price check top", "running": False, "pages": 9, "last_checked": 3,
                                    "last_alerts": 1, "next_at": "2026-10-02T15:02:30+0200"},
                      "homepage": {"label": "Price check homepage", "running": True, "progress": [120, 430]}}}),
            encoding="utf-8")
        (self.pc_dir / "run-top-games.request").write_text('{"mode": "top-games", "by": "romain", "at": "x"}', encoding="utf-8")
        response, body = self._json("GET", "/api/price-check/status")
        self.assertEqual(response.status, 200)
        self.assertTrue(body["available"])
        self.assertEqual(body["modes"]["homepage"]["progress"], [120, 430])
        self.assertEqual(body["pending"]["top-games"]["by"], "romain")
        self.assertIsNone(body["pending"]["homepage"])
        self.assertIsInstance(body["age_seconds"], int)

    def test_a_run_request_is_a_file_signed_by_the_operator_once(self):
        response, body = self._json("POST", "/api/price-check/run", {"mode": "homepage", "by": "quelquun"})
        self.assertEqual(response.status, 200, body)
        self.assertEqual((body["requested"]["mode"], body["requested"]["by"]), ("homepage", "operateur"))
        on_disk = json.loads((self.pc_dir / "run-homepage.request").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["by"], "operateur")  # what the monitor logs: « passage demandé par operateur »
        response, body = self._json("POST", "/api/price-check/run", {"mode": "homepage"})
        self.assertEqual((response.status, body["error"]["code"]), (409, "already_requested"))
        self.assertFalse((self.pc_dir / "run-top-games.request").exists())

    def test_run_refusals(self):
        response, body = self._json("POST", "/api/price-check/run", {"mode": "full-page"})
        self.assertEqual((response.status, body["error"]["code"]), (400, "bad_mode"))
        response, body = self._json("POST", "/api/price-check/run", {"mode": "top-games"}, csrf=False)
        self.assertEqual((response.status, body["error"]["code"]), (403, "csrf"))
        response, body = self._json("POST", "/api/price-check/run", {"mode": "top-games"}, headers={"Authorization": ""})
        self.assertEqual((response.status, body["error"]["code"]), (403, "authentication_required"))
        self.assertEqual(list(self.pc_dir.iterdir()), [], "a refused request left a file")


if __name__ == "__main__":
    unittest.main()
