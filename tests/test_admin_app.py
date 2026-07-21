import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from src.admin.app import AppState, make_server
from src.admin.submit_manager import SubmitManager

REPO_ROOT = Path(__file__).resolve().parents[1]

FAKE_SCRIPT = """\
import json, sys
from pathlib import Path
out = Path(sys.argv[1]).resolve().parent
if "--catalog" not in sys.argv:
    out.joinpath("submit_plan.json").write_text(
        json.dumps({"created": 1, "write_attempts": 1, "plan": [], "aborted": None,
                    "stopped": None, "data_entry_mode": "safe", "limit": None}),
        encoding="utf-8",
    )
print(json.dumps({"ok": True}))
sys.exit(0)
"""

FAKE_MATCH = """\
import argparse, json, sys
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("offers")
p.add_argument("--max-candidates", type=int, default=100)
args = p.parse_args()
Path(args.offers).resolve().parent.joinpath("candidates.json").write_text(
    json.dumps([]), encoding="utf-8"
)
print(json.dumps({"candidates": 0}))
sys.exit(0)
"""


def _cand(offer_id="1", pid="207861", region="2", edition="1"):
    return {
        "fingerprint": f"{offer_id}|{pid}|{region}|{edition}",
        "offer": {
            "offer_id": offer_id, "name": "Game", "url": "https://m/x", "merchant": "GameSeal",
            "store_id": "126", "price": None, "stock": None,
        },
        "aks_product_id": pid, "aks_url": "https://aks/x", "aks_name": "Game", "platform": "STEAM",
        "region": {"label": "GLOBAL", "id": region, "implicit": False},
        "edition": {"label": "Standard", "id": edition},
    }


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.runs = root / "runs"
        self.run = self.runs / "20260715-000000-test"
        self.run.mkdir(parents=True)
        self.logs = root / "logs"
        (self.run / "offers.json").write_text(
            json.dumps({"merchant": "GameSeal", "offers": [{"offer_id": "1", "store_id": "126"}]}),
            encoding="utf-8",
        )
        (self.run / "report.txt").write_text("AKS candidates — GameSeal — 1 candidate(s)\n", encoding="utf-8")
        candidate = _cand()
        (self.run / "candidates.json").write_text(json.dumps([candidate]), encoding="utf-8")

        fake_script = root / "fake_submit.py"
        fake_script.write_text(FAKE_SCRIPT, encoding="utf-8")
        fake_match = root / "fake_match.py"
        fake_match.write_text(FAKE_MATCH, encoding="utf-8")
        manager = SubmitManager(
            REPO_ROOT, log_dir=self.logs, submit_script=fake_script, match_script=fake_match
        )
        self.manager = manager
        state = AppState(REPO_ROOT, runs_dir=self.runs, log_dir=self.logs, manager=manager)
        self.server = make_server(state, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def _request(self, method, path, body=None, csrf=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        send_headers = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body)
            if csrf:
                send_headers.setdefault("X-AKS-Admin", "1")
                send_headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=send_headers)
        response = conn.getresponse()
        data = response.read()
        return response, data

    def _json(self, method, path, body=None, **kw):
        response, data = self._request(method, path, body=body, **kw)
        return response, json.loads(data)


class StaticAndHeadersTests(AppTestCase):
    def test_index_served_with_security_headers(self):
        response, data = self._request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"<", data)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")

    def test_no_generic_file_service(self):
        for path in ("/etc/passwd", "/../etc/passwd", "/src/admin/app.py", "/runs/x"):
            response, data = self._request("GET", path)
            self.assertEqual(response.status, 404, path)


class ApiGetTests(AppTestCase):
    def test_meta(self):
        response, body = self._json("GET", "/api/meta")
        self.assertEqual(response.status, 200)
        self.assertIn("STEAM", body["platforms"])
        self.assertIn("PUBLISHER", body["platforms"])
        self.assertEqual(body["modes"], ["safe", "learning", "advanced"])
        self.assertEqual(body["canary_limit"], 1)

    def test_runs_list_and_detail(self):
        response, body = self._json("GET", "/api/runs")
        self.assertEqual(response.status, 200)
        self.assertEqual(body["runs"][0]["run_id"], "20260715-000000-test")
        self.assertIsNone(body["busy"])  # rien en cours → badge éteint côté UI
        response, detail = self._json("GET", "/api/runs/20260715-000000-test")
        self.assertEqual(detail["merchant"], "GameSeal")
        self.assertEqual(detail["store_id"], "126")

    def test_unknown_run_error_model(self):
        response, body = self._json("GET", "/api/runs/20990101-000000-nope")
        self.assertEqual(response.status, 404)
        self.assertEqual(body["error"]["code"], "unknown_run")
        self.assertIn("message", body["error"])

    def test_bad_run_id_rejected(self):
        response, body = self._json("GET", "/api/runs/..%2f..%2fetc")
        self.assertEqual(response.status, 404)

    def test_report_text(self):
        response, data = self._request("GET", "/api/runs/20260715-000000-test/report")
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/plain"))
        self.assertIn(b"AKS candidates", data)

    def test_validation_payload(self):
        response, body = self._json("GET", "/api/runs/20260715-000000-test/validation")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(body["candidates"]), 1)
        self.assertIsNone(body["validation"])
        self.assertEqual(body["approved_fingerprints"], [])
        self.assertFalse(body["catalog"]["present"])
        self.assertTrue(body["candidates_sha256"])


class CsrfTests(AppTestCase):
    def test_post_without_header_403(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={}, csrf=False, headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(body["error"]["code"], "csrf")

    def test_post_wrong_content_type_403(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={}, csrf=False,
            headers={"X-AKS-Admin": "1", "Content-Type": "text/plain"},
        )
        self.assertEqual(response.status, 403)

    def test_post_cross_origin_403(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={}, headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status, 403)

    def test_post_same_origin_passes_csrf(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={}, headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        # passes CSRF, fails later on missing validated_by (400, not 403)
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "missing_validated_by")


class ValidationFlowTests(AppTestCase):
    def test_save_validation_and_submit_flow(self):
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        fingerprint = payload["candidates"][0]["fingerprint"]
        response, result = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={
                "candidates_sha256": payload["candidates_sha256"],
                "validated_by": "Romain",
                "decisions": [{"fingerprint": fingerprint, "approve": True}],
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(result["approved_count"], 1)
        self.assertTrue((self.run / "approved.json").exists())
        approved_sha = result["approved_sha256"]
        self.assertTrue(approved_sha)

        # real submit without GO refused
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": False, "approved_sha256": approved_sha},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "confirm_required")

        # AS1: GO without the displayed batch's sha refused
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": False, "confirm": "GO"},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "approved_sha_required")

        # AS1: GO bound to a DIFFERENT batch than the current one refused
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": False, "confirm": "GO",
                  "approved_sha256": "0" * 64},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "approved_changed")

        # with GO + the displayed sha: started, then status reaches done
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": False, "confirm": "GO", "by": "Romain",
                  "approved_sha256": approved_sha},
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(body["started"])
        self.assertIn("--submit", body["argv"])
        self.assertTrue(self.manager.wait_idle(timeout=10))
        response, status = self._json(
            "GET", "/api/runs/20260715-000000-test/submit/status?offset=0"
        )
        self.assertEqual(status["state"], "done")
        self.assertEqual(status["exit_code"], 0)
        self.assertEqual(status["submit_plan"]["created"], 1)
        events = [e["event"] for e in status["events"]]
        self.assertIn("admin_submit_started", events)
        self.assertIn("admin_submit_finished", events)

    def test_max_pages_threaded_through_dry_run(self):
        # Difmark (2026-07-17): a 382-page feed needs a higher --max-pages
        # than the script's default 40 — the admin page's field must reach
        # the spawned argv, string-or-number JSON bodies both accepted.
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        fingerprint = payload["candidates"][0]["fingerprint"]
        self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={
                "candidates_sha256": payload["candidates_sha256"],
                "validated_by": "Romain",
                "decisions": [{"fingerprint": fingerprint, "approve": True}],
            },
        )
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": True, "max_pages": 400},
        )
        self.assertEqual(response.status, 200)
        self.assertIn("--max-pages", body["argv"])
        self.assertEqual(body["argv"][body["argv"].index("--max-pages") + 1], "400")
        self.assertTrue(self.manager.wait_idle(timeout=10))

        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": True, "max_pages": "400"},
        )
        self.assertEqual(response.status, 200)
        self.assertIn("--max-pages", body["argv"])
        self.assertTrue(self.manager.wait_idle(timeout=10))

    def test_stale_sha_conflict(self):
        response, body = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={"candidates_sha256": "deadbeef", "validated_by": "Romain", "decisions": []},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "stale_candidates")

    def test_keepalive_not_desynced_by_error_before_body_read(self):
        # AS3 (audit 2026-07-17): a 403 (CSRF) used to be sent WITHOUT reading
        # the request body — the unread bytes then desynced the next request
        # on the same HTTP/1.1 keep-alive connection.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        payload = json.dumps({"padding": "x" * 2048})
        conn.request("POST", "/api/extract", body=payload,
                     headers={"Content-Type": "application/json"})  # no X-AKS-Admin
        first = conn.getresponse()
        first_body = first.read()
        self.assertEqual(first.status, 403)
        self.assertIn(b"csrf", first_body)
        conn.request("GET", "/api/meta")
        second = conn.getresponse()
        data = second.read()
        self.assertEqual(second.status, 200)
        self.assertIn("platforms", json.loads(data))

    def test_submit_without_validation_conflict(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": True},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "not_validated")

    def test_created_offers_visible_and_blocked(self):
        # an earlier supervised submit confirmed offer "1" as created (JSONL log)
        self.logs.mkdir(exist_ok=True)
        (self.logs / "20260715-000000-test.jsonl").write_text(
            json.dumps({"event": "submit_offer", "offer_id": "1", "success": True,
                        "post_save": "gone from feed (available=all)",
                        "ts": "2026-07-15T15:00:00Z", "run_id": "20260715-000000-test"}) + "\n",
            encoding="utf-8",
        )
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        self.assertEqual(payload["submit_history"]["1"]["status"], "created")
        _, detail = self._json("GET", "/api/runs/20260715-000000-test")
        self.assertEqual(detail["created_count"], 1)
        self.assertEqual(detail["failed_count"], 0)
        _, listing = self._json("GET", "/api/runs")
        self.assertEqual(listing["runs"][0]["created_count"], 1)

        # re-approving the created offer is refused whole
        response, body = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={
                "candidates_sha256": payload["candidates_sha256"],
                "validated_by": "Romain",
                "decisions": [{"fingerprint": payload["candidates"][0]["fingerprint"], "approve": True}],
            },
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "already_created")

    def test_failed_offer_reported_but_still_approvable(self):
        self.logs.mkdir(exist_ok=True)
        (self.logs / "20260715-000000-test.jsonl").write_text(
            json.dumps({"event": "submit_offer", "offer_id": "1", "success": False,
                        "blocker": "offer not in current feed",
                        "ts": "2026-07-15T15:00:00Z", "run_id": "20260715-000000-test"}) + "\n",
            encoding="utf-8",
        )
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        self.assertEqual(payload["submit_history"]["1"]["status"], "failed")
        response, result = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={
                "candidates_sha256": payload["candidates_sha256"],
                "validated_by": "Romain",
                "decisions": [{"fingerprint": payload["candidates"][0]["fingerprint"], "approve": True}],
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(result["approved_count"], 1)

    def test_delete_entry_from_page(self):
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        response, result = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={
                "candidates_sha256": payload["candidates_sha256"],
                "validated_by": "Romain",
                "decisions": [{"fingerprint": payload["candidates"][0]["fingerprint"], "delete": True}],
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(len(result["deleted"]), 1)
        self.assertEqual(result["approved_count"], 0)
        self.assertEqual(
            json.loads((self.run / "candidates.json").read_text(encoding="utf-8")), []
        )

    def test_delete_created_entry_refused(self):
        self.logs.mkdir(exist_ok=True)
        (self.logs / "20260715-000000-test.jsonl").write_text(
            json.dumps({"event": "submit_offer", "offer_id": "1", "success": True,
                        "post_save": "gone", "ts": "T", "run_id": "20260715-000000-test"}) + "\n",
            encoding="utf-8",
        )
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        response, body = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={
                "candidates_sha256": payload["candidates_sha256"],
                "validated_by": "Romain",
                "decisions": [{"fingerprint": payload["candidates"][0]["fingerprint"], "delete": True}],
            },
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "delete_created")

    def test_status_events_re_redacted(self):
        self.logs.mkdir(exist_ok=True)
        (self.logs / "20260715-000000-test.jsonl").write_text(
            json.dumps({"event": "submit_offer", "token": "SECRET", "ts": "x", "run_id": "r"}) + "\n",
            encoding="utf-8",
        )
        _, status = self._json("GET", "/api/runs/20260715-000000-test/submit/status?offset=0")
        self.assertEqual(status["events"][0]["token"], "***REDACTED***")
        self.assertNotIn("SECRET", json.dumps(status))


class LearningEndpointTests(AppTestCase):
    """Romain 2026-07-21: annotate non-matched offers (region/edition/comment)."""

    def setUp(self):
        super().setUp()
        (self.run / "skipped.json").write_text(json.dumps([
            {"offer": {"offer_id": "10", "name": "Resident Evil 2 / Biohazard",
                       "url": "https://g2a/10"},
             "reason": "no AKS product page found (slug not 200)"},
            {"offer": {"offer_id": "11", "name": "Halo Xbox", "url": "https://g2a/11"},
             "reason": "console"},
        ]), encoding="utf-8")
        (self.run / "session_catalog.json").write_text(json.dumps({
            "ok": True,
            "regions": {"master_options": [{"key": "2", "text": "Steam (2)"}]},
            "editions": {"master_options": [{"key": "1", "text": "Standard"}]},
        }), encoding="utf-8")

    def test_get_groups_non_matched_by_reason(self):
        response, body = self._json("GET", "/api/runs/20260715-000000-test/learning")
        self.assertEqual(response.status, 200)
        reasons = {g["reason"]: g["count"] for g in body["groups"]}
        self.assertEqual(reasons["no AKS product page found (slug not 200)"], 1)
        self.assertEqual(reasons["console"], 1)
        self.assertEqual(body["annotations"], {})
        # the Move-to-List catalog is served for the per-offer dropdown
        self.assertTrue(any(l["id"] == "16" for l in body["lists"]))
        self.assertIsNone(body["learning_sha256"])  # no learning.json yet

    def test_post_saves_annotations_and_get_returns_them(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/learning",
            body={"annotations": [
                {"offer_id": "10", "region_id": "2", "region_text": "Steam (2)",
                 "edition_id": "1", "edition_text": "Standard",
                 "comment": "le « / » casse le slug — éàç",
                 "aks_url": "https://www.allkeyshop.com/blog/buy-re2-cd-key-compare-prices/"},
                {"offer_id": "11", "target_list_id": "16", "target_list_label": "Softwares"},
            ], "by": "Romain", "base_sha": None},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(body["saved"], 2)
        self.assertTrue((self.run / "learning.json").is_file())
        self.assertTrue(body["learning_sha256"])
        _, got = self._json("GET", "/api/runs/20260715-000000-test/learning")
        self.assertEqual(got["annotations"]["10"]["region_id"], "2")
        # unicode round-trips through HTTP (ensure_ascii=False)
        self.assertEqual(got["annotations"]["10"]["comment"], "le « / » casse le slug — éàç")
        self.assertEqual(got["annotations"]["10"]["aks_url"],
                         "https://www.allkeyshop.com/blog/buy-re2-cd-key-compare-prices/")
        self.assertEqual(got["annotations"]["11"]["target_list_id"], "16")
        self.assertEqual(got["annotations"]["11"]["target_list_label"], "Softwares")
        self.assertEqual(got["learning_sha256"], body["learning_sha256"])

    def test_post_stale_sha_conflict(self):
        first, body = self._json(
            "POST", "/api/runs/20260715-000000-test/learning",
            body={"annotations": [{"offer_id": "10", "comment": "v1"}], "base_sha": None},
        )
        self.assertEqual(first.status, 200)
        # a second save that did NOT reload (base_sha still None) must 409,
        # and the stored annotation must be untouched
        response, err = self._json(
            "POST", "/api/runs/20260715-000000-test/learning",
            body={"annotations": [{"offer_id": "11", "comment": "v2"}], "base_sha": None},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(err["error"]["code"], "conflict")
        _, got = self._json("GET", "/api/runs/20260715-000000-test/learning")
        self.assertEqual(got["annotations"]["10"]["comment"], "v1")
        self.assertNotIn("11", got["annotations"])

    def test_post_bad_offer_id_refused(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/learning",
            body={"annotations": [{"offer_id": "999", "comment": "x"}], "base_sha": None},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "bad_offer")

    def test_post_without_csrf_header_refused(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/learning",
            body={"annotations": []}, csrf=False,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(body["error"]["code"], "csrf")
        self.assertFalse((self.run / "learning.json").is_file())


class MatchEndpointTests(AppTestCase):
    """Romain 2026-07-20: launch the matching step (stage 3) from the admin."""

    def test_match_launches_and_produces_candidates(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/match",
            body={"max_candidates": 3, "by": "Romain"},
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(body["started"])
        self.assertEqual(body["kind"], "match")
        self.assertIn("--max-candidates", body["argv"])
        self.assertTrue(self.manager.wait_idle(timeout=10))
        self.assertTrue((self.run / "candidates.json").is_file())

    def test_match_requires_csrf(self):
        response, _ = self._json(
            "POST", "/api/runs/20260715-000000-test/match",
            body={}, csrf=False, headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
