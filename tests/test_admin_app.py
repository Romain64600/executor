import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from src.admin.app import AppState, make_server
from src.admin.submit_manager import SubmitManager, SubmitStartError

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
        self.state = state   # tests may swap a component (e.g. state.login) before requesting
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

    def test_index_cache_busts_assets(self):
        # index.html stamps app.js/style.css with a content hash so a redeploy
        # is never masked by a stale browser copy.
        _, data = self._request("GET", "/")
        html = data.decode("utf-8")
        self.assertRegex(html, r'app\.js\?v=[0-9a-f]{8}')
        self.assertRegex(html, r'style\.css\?v=[0-9a-f]{8}')
        self.assertNotIn('"app.js"', html)  # no un-versioned reference left

    def test_versioned_asset_is_served(self):
        # the ?v= query must not break the static lookup
        response, data = self._request("GET", "/app.js?v=deadbeef")
        self.assertEqual(response.status, 200)
        self.assertIn(b"loadLearning", data)


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
    def test_validated_by_is_the_authenticated_user_not_the_body(self):
        # P2-9 (audit 2026-09-02): validated_by authorizes live offer creation — it must
        # be the AUTHENTICATED (basic-auth) user, never a client free-text field an
        # operator could spoof to someone else. The authenticated identity WINS.
        import base64
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        fp = payload["candidates"][0]["fingerprint"]
        auth = "Basic " + base64.b64encode(b"alice:secret").decode()
        resp, _ = self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={"candidates_sha256": payload["candidates_sha256"],
                  "validated_by": "Romain",   # spoofed — must be ignored
                  "decisions": [{"fingerprint": fp, "approve": True}]},
            headers={"Authorization": auth})
        self.assertEqual(resp.status, 200)
        stored = json.loads((self.run / "validation.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["validated_by"], "alice")   # authed wins, not "Romain"

    def test_validated_by_falls_back_to_body_without_auth(self):
        # No basic auth (standalone/dev) → the body field is used, as before.
        _, payload = self._json("GET", "/api/runs/20260715-000000-test/validation")
        fp = payload["candidates"][0]["fingerprint"]
        resp, _ = self._json(
            "POST", "/api/runs/20260715-000000-test/validation",
            body={"candidates_sha256": payload["candidates_sha256"],
                  "validated_by": "Bob",
                  "decisions": [{"fingerprint": fp, "approve": True}]})
        self.assertEqual(resp.status, 200)
        stored = json.loads((self.run / "validation.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["validated_by"], "Bob")

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
        # D3/D4 vocab served (single source of truth for the UI)
        self.assertIn("regle_marchand", body["scopes"])
        self.assertIn("STEAM", body["platforms"])

    def test_post_saves_annotations_and_get_returns_them(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/learning",
            body={"annotations": [
                {"offer_id": "10", "region_id": "2", "region_text": "Steam (2)",
                 "edition_id": "1", "edition_text": "Standard",
                 "comment": "le « / » casse le slug — éàç",
                 "aks_url": "https://www.allkeyshop.com/blog/buy-re2-cd-key-compare-prices/"},
                {"offer_id": "11", "target_list_id": "16", "target_list_label": "Softwares",
                 "platform": "PS5", "scope": "exception_offre", "suggested": True},
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
        self.assertEqual(got["annotations"]["11"]["platform"], "PS5")
        self.assertEqual(got["annotations"]["11"]["scope"], "exception_offre")
        self.assertIs(got["annotations"]["11"]["suggested"], True)  # D1 (b)
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


class DataEntryAutoAllowlistTests(AppTestCase):
    """Safe-auto is gated to a server-vetted merchant allowlist (Romain
    2026-08-07): the UI only offers these, and the route re-checks so a
    hand-crafted request can't bypass the picker (fail-closed)."""

    def test_merchants_list_served(self):
        response, body = self._json("GET", "/api/data-entry/merchants")
        self.assertEqual(response.status, 200)
        names = {m["name"] for m in body["merchants"]}
        self.assertIn("Kinguin", names)
        self.assertNotIn("Difmark", names)
        self.assertNotIn("Gameboost", names)

    def test_non_suggested_merchant_refused_without_launching(self):
        calls = []
        self.manager.start_data_entry_auto = lambda *a, **k: calls.append((a, k)) or {}
        response, body = self._json(
            "POST", "/api/data-entry/auto",
            body={"targets": [{"merchant": "Difmark", "store_id": "167"}], "by": "Romain"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(body["error"]["code"], "merchant_not_allowed")
        self.assertEqual(calls, [])  # gate refused before the manager was touched

    def test_store_mismatch_refused(self):
        self.manager.start_data_entry_auto = lambda *a, **k: {}
        response, body = self._json(
            "POST", "/api/data-entry/auto",
            body={"targets": [{"merchant": "Kinguin", "store_id": "999"}]},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(body["error"]["code"], "merchant_not_allowed")

    def test_mixed_batch_refused_if_any_not_allowed(self):
        calls = []
        self.manager.start_data_entry_auto = lambda *a, **k: calls.append((a, k)) or {}
        response, _ = self._json(
            "POST", "/api/data-entry/auto",
            body={"targets": [
                {"merchant": "Kinguin", "store_id": "58"},
                {"merchant": "Gameboost", "store_id": "157"},
            ]},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(calls, [])  # whole batch rejected, nothing launched

    def test_suggested_merchant_accepted(self):
        seen = {}
        def fake(targets, *, by, max_pages=None, start_page=None):
            seen["targets"] = targets
            return {"run_id": "20260807-000000-auto", "started": True}
        self.manager.start_data_entry_auto = fake
        response, body = self._json(
            "POST", "/api/data-entry/auto",
            body={"targets": [{"merchant": "Kinguin", "store_id": "58"}], "by": "Romain"},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(body["run_id"], "20260807-000000-auto")
        self.assertEqual(seen["targets"], [("Kinguin", "58")])


class DataEntryRecapRouteTests(AppTestCase):
    """The safe-auto live recap is read through /api/data-entry/recap; recap.json
    must be whitelisted (regression: it 500'd 'file not in run whitelist')."""

    def _auto_run(self, name="20260807-115728-auto", created=3, finished=None):
        d = self.runs / name
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath("recap.json").write_text(json.dumps({
            "run_id": name, "total_created": created, "finished_at": finished,
            "halted": None, "targets": [{"merchant": "K4G", "store_id": "92", "recap": {}}],
        }), encoding="utf-8")
        return name

    def test_recap_by_explicit_run(self):
        name = self._auto_run()
        response, body = self._json("GET", f"/api/data-entry/recap?run={name}")
        self.assertEqual(response.status, 200)
        self.assertEqual(body["run_id"], name)
        self.assertEqual(body["recap"]["total_created"], 3)

    def test_recap_defaults_to_newest_auto_run(self):
        self._auto_run("20260807-100000-auto", created=1)
        newest = self._auto_run("20260807-115728-auto", created=9)
        response, body = self._json("GET", "/api/data-entry/recap")
        self.assertEqual(response.status, 200)
        self.assertEqual(body["run_id"], newest)
        self.assertEqual(body["recap"]["total_created"], 9)

    def test_recap_none_when_no_auto_runs(self):
        response, body = self._json("GET", "/api/data-entry/recap")
        self.assertEqual(response.status, 200)
        self.assertIsNone(body["recap"])


class DataEntryByUrlsRouteTests(AppTestCase):
    """Data entry from a list of AKS page URLs — the read-only dry-run tab."""

    def test_games_page_served(self):
        response, data = self._request("GET", "/games")
        self.assertEqual(response.status, 200)
        self.assertIn(b"<", data)

    def test_launch_passes_urls_to_manager(self):
        seen = {}
        def fake(urls, *, by, targets_spec=None):
            seen["urls"] = urls
            return {"run_id": "20260824-000000-by-urls", "started": True}
        self.manager.start_data_entry_by_urls = fake
        url = "https://www.allkeyshop.com/blog/buy-neon-beats-cd-key-compare-prices/"
        response, body = self._json("POST", "/api/data-entry/by-urls",
                                    body={"urls": [url], "by": "Romain"})
        self.assertEqual(response.status, 200)
        self.assertEqual(body["run_id"], "20260824-000000-by-urls")
        self.assertEqual(seen["urls"], [url])

    def test_urls_as_string_are_split(self):
        seen = {}
        self.manager.start_data_entry_by_urls = lambda urls, **k: seen.setdefault("urls", urls) or {}
        self._json("POST", "/api/data-entry/by-urls", body={"urls": "u1\nu2 u3"})
        self.assertEqual(seen["urls"], ["u1", "u2", "u3"])

    def test_no_urls_refused(self):
        calls = []
        self.manager.start_data_entry_by_urls = lambda *a, **k: calls.append(1) or {}
        response, body = self._json("POST", "/api/data-entry/by-urls", body={"urls": []})
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "urls_required")
        self.assertEqual(calls, [])

    def test_too_many_urls_refused(self):
        calls = []
        self.manager.start_data_entry_by_urls = lambda *a, **k: calls.append(1) or {}
        response, body = self._json("POST", "/api/data-entry/by-urls",
                                    body={"urls": [f"u{i}" for i in range(201)]})
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "too_many_urls")
        self.assertEqual(calls, [])

    def _byurls_run(self, name="20260824-115728-by-urls", candidates=2):
        d = self.runs / name
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath("recap.json").write_text(json.dumps({
            "mode": "dry-run", "aborted": None, "games": [],
            "totals": {"games": 1, "resolved": 1, "candidates": candidates},
        }), encoding="utf-8")
        return name

    def test_recap_by_explicit_run(self):
        name = self._byurls_run()
        response, body = self._json("GET", f"/api/data-entry/by-urls/recap?run={name}")
        self.assertEqual(response.status, 200)
        self.assertEqual(body["run_id"], name)
        self.assertEqual(body["recap"]["totals"]["candidates"], 2)

    def test_recap_defaults_to_newest_by_urls_run(self):
        self._byurls_run("20260824-100000-by-urls", candidates=1)
        newest = self._byurls_run("20260824-115728-by-urls", candidates=9)
        response, body = self._json("GET", "/api/data-entry/by-urls/recap")
        self.assertEqual(response.status, 200)
        self.assertEqual(body["run_id"], newest)
        self.assertEqual(body["recap"]["totals"]["candidates"], 9)

    def test_log_route_tails_allowed_events_and_advances_offset(self):
        name = self._byurls_run("20260824-121500-by-urls")
        self.logs.mkdir(parents=True, exist_ok=True)
        self.logs.joinpath(f"{name}.jsonl").write_text(
            json.dumps({"event": "run_start", "urls": 1, "merchants": 10}) + "\n"
            + json.dumps({"event": "game_resolved", "ok": True, "aks_name": "Neon Beats"}) + "\n"
            + json.dumps({"event": "guard_snapshot", "guard": {}}) + "\n",  # not a UI event
            encoding="utf-8")
        response, body = self._json("GET", f"/api/data-entry/by-urls/log?run={name}&offset=0")
        self.assertEqual(response.status, 200)
        self.assertEqual([e["event"] for e in body["events"]], ["run_start", "game_resolved"])
        self.assertGreater(body["offset"], 0)
        # a second tail from the new offset returns nothing new
        r2, b2 = self._json("GET", f"/api/data-entry/by-urls/log?run={name}&offset={body['offset']}")
        self.assertEqual(b2["events"], [])

    def test_log_route_bogus_run_404(self):
        response, _ = self._json("GET", "/api/data-entry/by-urls/log?run=../etc&offset=0")
        self.assertIn(response.status, (400, 404))

    def test_recap_returns_sha_for_saisir_binding(self):
        name = self._byurls_run()
        _, body = self._json("GET", f"/api/data-entry/by-urls/recap?run={name}")
        self.assertTrue(body.get("recap_sha256"))       # AS1 binding for the Saisir GO
        # P1 review: the bound sha must be the hash of the EXACT bytes displayed
        # (single read) — mirror it and confirm they agree.
        import hashlib
        raw = (self.runs / name / "recap.json").read_bytes()
        self.assertEqual(body["recap_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(body["recap"], json.loads(raw))

    # ---- stage 2: the "Saisir" (submit) route ----
    def test_submit_route_passes_from_run_and_sha(self):
        seen = {}
        def fake(from_run, *, by, expected_recap_sha=None):
            seen.update(from_run=from_run, sha=expected_recap_sha)
            return {"run_id": "20260825-000000-by-urls-submit", "started": True}
        self.manager.start_data_entry_by_urls_submit = fake
        response, body = self._json(
            "POST", "/api/data-entry/by-urls/submit",
            body={"from_run": "20260825-000000-by-urls", "recap_sha256": "abc", "confirm": "GO"})
        self.assertEqual(response.status, 200)
        self.assertEqual((seen["from_run"], seen["sha"]), ("20260825-000000-by-urls", "abc"))

    def test_submit_route_requires_from_run(self):
        calls = []
        self.manager.start_data_entry_by_urls_submit = lambda *a, **k: calls.append(1) or {}
        response, body = self._json("POST", "/api/data-entry/by-urls/submit", body={"confirm": "GO"})
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "from_run_required")
        self.assertEqual(calls, [])

    def test_submit_route_requires_typed_go(self):
        # server-side typed-GO gate (parity with the other write paths).
        calls = []
        self.manager.start_data_entry_by_urls_submit = lambda *a, **k: calls.append(1) or {}
        response, body = self._json("POST", "/api/data-entry/by-urls/submit",
                                    body={"from_run": "x", "recap_sha256": "y"})
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "confirm_required")
        self.assertEqual(calls, [])

    def test_submit_route_propagates_submit_start_error(self):
        def fake(*a, **k):
            raise SubmitStartError("recap_changed", "changed", http_status=409)
        self.manager.start_data_entry_by_urls_submit = fake
        response, body = self._json("POST", "/api/data-entry/by-urls/submit",
                                    body={"from_run": "x", "recap_sha256": "y", "confirm": "GO"})
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "recap_changed")


class SortMoveRouteTests(AppTestCase):
    def _sort_run(self):
        # a run carrying a sort_plan.json, readable by the console + sort routes
        self.run.joinpath("sort_plan.json").write_text(json.dumps({
            "run_id": self.run.name, "counts": {"routed": 2, "target_lists": 1},
            "by_list": {"8": {"list_id": "8", "label": "Blacklist", "count": 2, "offers": [
                {"offer_id": "a1", "store_id": "38", "name": "Random Game Key", "url": "https://g2a/a1"},
            ]}},
        }), encoding="utf-8")

    def test_sort_plan_route_returns_plan(self):
        self._sort_run()
        response, data = self._json("GET", f"/api/runs/{self.run.name}/sort")
        self.assertEqual(response.status, 200)
        self.assertEqual(data["counts"]["routed"], 2)

    def test_sort_runs_lists_the_run(self):
        self._sort_run()
        response, data = self._json("GET", "/api/sort/runs")
        self.assertEqual(response.status, 200)
        self.assertIn(self.run.name, [r["run_id"] for r in data["runs"]])

    def test_sort_plan_route_attaches_moved_tally(self):
        self._sort_run()
        self.run.joinpath("sort_move_tally.json").write_text(
            json.dumps({"8": {"moved_total": 30, "label": "Blacklist"}}), encoding="utf-8")
        response, data = self._json("GET", f"/api/runs/{self.run.name}/sort")
        self.assertEqual(response.status, 200)
        self.assertEqual(data["moved_tally"]["8"]["moved_total"], 30)

    def test_sort_plan_route_tally_defaults_empty(self):
        self._sort_run()   # no tally file
        response, data = self._json("GET", f"/api/runs/{self.run.name}/sort")
        self.assertEqual(data["moved_tally"], {})

    def test_sort_plan_route_attaches_fetched_at(self):
        self._sort_run()
        self.run.joinpath("offers.json").write_text(
            json.dumps({"merchant": "X", "fetched_at": "2026-07-24T10:00:00Z", "offers": []}),
            encoding="utf-8")
        response, data = self._json("GET", f"/api/runs/{self.run.name}/sort")
        self.assertEqual(data["fetched_at"], "2026-07-24T10:00:00Z")

    def test_real_move_requires_typed_go(self):
        # a canary WITHOUT confirm=GO is refused BEFORE anything is spawned
        self._sort_run()
        response, data = self._json("POST", f"/api/runs/{self.run.name}/sort/move",
                                    body={"list_id": "8", "action": "canary"})
        self.assertEqual(response.status, 400)
        self.assertEqual(data["error"]["code"], "go_required")

    def test_move_requires_list_id(self):
        self._sort_run()
        response, data = self._json("POST", f"/api/runs/{self.run.name}/sort/move",
                                    body={"action": "canary", "confirm": "GO"})
        self.assertEqual(response.status, 400)
        self.assertEqual(data["error"]["code"], "list_required")

    def test_move_passes_batched_and_deferred_through(self):
        from unittest import mock
        self._sort_run()
        with mock.patch.object(self.manager, "start_sort_move",
                               return_value={"started": True, "run_id": self.run.name}) as m:
            response, data = self._json("POST", f"/api/runs/{self.run.name}/sort/move",
                                        body={"list_id": "8", "action": "batch", "confirm": "GO",
                                              "batched": True, "deferred": True})
        self.assertEqual(response.status, 200)
        m.assert_called_once()
        self.assertTrue(m.call_args.kwargs["batched"])
        self.assertTrue(m.call_args.kwargs["deferred"])

    def test_sort_stop_when_idle(self):
        response, data = self._json("POST", "/api/sort/stop", body={})
        self.assertEqual(response.status, 200)
        self.assertIsNone(data["stopped"])

    def test_data_entry_auto_passes_targets(self):
        from unittest import mock
        with mock.patch.object(self.manager, "start_data_entry_auto",
                               return_value={"started": True, "run_id": "20260804-000000-auto"}) as m:
            response, data = self._json("POST", "/api/data-entry/auto",
                                        body={"targets": [{"merchant": "Kinguin", "store_id": "58"}],
                                              "max_pages": 5})
        self.assertEqual(response.status, 200)
        m.assert_called_once()
        self.assertEqual(m.call_args.kwargs["max_pages"], 5)
        self.assertEqual(m.call_args.args[0], [("Kinguin", "58")])

    def test_data_entry_auto_requires_targets(self):
        response, data = self._json("POST", "/api/data-entry/auto", body={"targets": []})
        self.assertEqual(response.status, 400)
        self.assertEqual(data["error"]["code"], "targets_required")

    def test_data_entry_recap_empty_when_none(self):
        response, data = self._json("GET", "/api/data-entry/recap")
        self.assertEqual(response.status, 200)
        self.assertIsNone(data["recap"])

    def test_sort_scan_route_starts_a_run(self):
        from unittest import mock
        with mock.patch.object(self.manager, "start_sort_scan",
                               return_value={"started": True, "run_id": "20260101-000000-sort"}) as m:
            response, data = self._json("POST", "/api/sort/scan", body={})
        self.assertEqual(response.status, 200)
        self.assertTrue(data["started"])
        m.assert_called_once()


class LoginRouteTests(AppTestCase):
    def test_status(self):
        resp, data = self._json("GET", "/api/login/status")
        self.assertEqual(resp.status, 200)
        self.assertFalse(data["busy"])

    def test_cookies_bad_json_400(self):
        resp, data = self._json("POST", "/api/login/cookies", body={"cookies": "[ not json"})
        self.assertEqual(resp.status, 400)
        self.assertEqual(data["error"]["code"], "bad_cookies_json")

    def test_cookies_no_aks_aborts_without_browser(self):
        # foreign-domain cookies normalize to empty → aborted BEFORE any browser
        # action (no CDP touched — safe against the real LoginManager). The field
        # UI sends a LIST of cookie objects.
        body = {"cookies": [{"name": "_ga", "value": "z", "domain": ".google.com"}]}
        resp, data = self._json("POST", "/api/login/cookies", body=body)
        self.assertEqual(resp.status, 200)
        self.assertEqual(data["status"], "aborted")

    def test_cookies_requires_csrf(self):
        resp, _ = self._request("POST", "/api/login/cookies", body={"cookies": "[]"}, csrf=False)
        self.assertEqual(resp.status, 403)

    def test_cookie_value_never_echoed_in_response(self):
        # inject a fake manager; POST a distinctive cookie value; the response
        # must never reflect it (a regression echoing the input would fail here).
        from unittest import mock
        fake = mock.Mock()
        fake.apply_cookies.return_value = {"status": "logged_in", "cookies_injected": 1}
        self.state.login = fake
        body = {"cookies": [{"name": "wordpress_logged_in_x", "value": "SECRETVAL-9", "domain": ".allkeyshop.com"}]}
        resp, raw = self._request("POST", "/api/login/cookies", body=body)
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(raw)["status"], "logged_in")
        fake.apply_cookies.assert_called_once()
        self.assertNotIn(b"SECRETVAL-9", raw)


if __name__ == "__main__":
    unittest.main()
