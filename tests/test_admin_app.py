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
        manager = SubmitManager(REPO_ROOT, log_dir=self.logs, submit_script=fake_script)
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

        # real submit without GO refused
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": False},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "confirm_required")

        # with GO: started, then status reaches done with the parsed plan
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": False, "confirm": "GO", "by": "Romain"},
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

    def test_stale_sha_conflict(self):
        response, body = self._json(
            "POST",
            "/api/runs/20260715-000000-test/validation",
            body={"candidates_sha256": "deadbeef", "validated_by": "Romain", "decisions": []},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "stale_candidates")

    def test_submit_without_validation_conflict(self):
        response, body = self._json(
            "POST", "/api/runs/20260715-000000-test/submit",
            body={"mode": "safe", "dry_run": True},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(body["error"]["code"], "not_validated")

    def test_status_events_re_redacted(self):
        self.logs.mkdir(exist_ok=True)
        (self.logs / "20260715-000000-test.jsonl").write_text(
            json.dumps({"event": "submit_offer", "token": "SECRET", "ts": "x", "run_id": "r"}) + "\n",
            encoding="utf-8",
        )
        _, status = self._json("GET", "/api/runs/20260715-000000-test/submit/status?offset=0")
        self.assertEqual(status["events"][0]["token"], "***REDACTED***")
        self.assertNotIn("SECRET", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
