import tempfile
import unittest
from pathlib import Path

from src.run_log import REDACTED, RunLogger, redact


class RedactTests(unittest.TestCase):
    def test_redacts_secret_keys_case_insensitively(self):
        data = {
            "Browser": "Chrome/149",
            "webSocketDebuggerUrl": "ws://172.17.0.1:9223/devtools/x",
            "nested": {"Cookie": "abc", "keep": "yes"},
            "list": [{"googleotp": "123456"}],
        }
        out = redact(data)
        self.assertEqual(out["webSocketDebuggerUrl"], REDACTED)
        self.assertEqual(out["nested"]["Cookie"], REDACTED)
        self.assertEqual(out["list"][0]["googleotp"], REDACTED)
        self.assertEqual(out["Browser"], "Chrome/149")
        self.assertEqual(out["nested"]["keep"], "yes")

    def test_does_not_redact_lookalike_keys(self):
        out = redact({"token_count": 5, "secret_sauce": "ok"})
        self.assertEqual(out["token_count"], 5)
        self.assertEqual(out["secret_sauce"], "ok")

    def test_p2_11_cookie_jar_value_is_redacted_name_preserved(self):
        # P2-11 (audit 2026-09-02): the secret in a cookie descriptor lives under
        # "value" (the key run_log used to omit). It must be scrubbed; "name" and
        # "domain" are kept (auditable, non-secret).
        out = redact({"jar": [
            {"name": "wordpress_logged_in_x", "value": "SECRET-SESSION", "domain": ".allkeyshop.com"},
        ]})
        cookie = out["jar"][0]
        self.assertEqual(cookie["value"], REDACTED)
        self.assertEqual(cookie["name"], "wordpress_logged_in_x")   # name kept (not a secret)
        self.assertEqual(cookie["domain"], ".allkeyshop.com")

    def test_p2_11_otp_under_value_key_is_redacted(self):
        self.assertEqual(redact({"otp_field": {"value": "123456"}})["otp_field"]["value"], REDACTED)

    def test_p2_11_secret_scrubbers_converge(self):
        # run_log.REDACT_KEYS and login_manager._SECRET_KEYS must not silently drift
        # apart on the key that carries the cookie/OTP secret: every login-manager
        # secret key must also be a run_log redact key (fail-closed superset).
        from src.run_log import REDACT_KEYS
        from src.admin.login_manager import _SECRET_KEYS
        missing = {k.lower() for k in _SECRET_KEYS} - REDACT_KEYS
        self.assertEqual(missing, set(), f"REDACT_KEYS missing login-manager secrets: {missing}")


class RunLoggerTests(unittest.TestCase):
    def test_empty_run_id_raises(self):
        with self.assertRaises(ValueError):
            RunLogger("")

    def test_log_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger("run-1", log_dir=tmp, clock=lambda: "2026-07-02T00:00:00Z")
            logger.log("start", merchant="Driffle")
            logger.log("done", count=3)

            records = logger.read()
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["event"], "start")
            self.assertEqual(records[0]["run_id"], "run-1")
            self.assertEqual(records[0]["ts"], "2026-07-02T00:00:00Z")
            self.assertEqual(records[0]["merchant"], "Driffle")
            self.assertEqual(records[1]["count"], 3)

    def test_is_append_only_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger("run-1", log_dir=tmp)
            logger.log("a")
            logger.log("b")
            lines = Path(tmp, "run-1.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)

    def test_secrets_are_redacted_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger("run-1", log_dir=tmp)
            rec = logger.log("probe", cdp={"Browser": "Chrome", "webSocketDebuggerUrl": "ws://x"}, token_count=5)
            self.assertEqual(rec["cdp"]["webSocketDebuggerUrl"], REDACTED)
            self.assertEqual(rec["cdp"]["Browser"], "Chrome")
            self.assertEqual(rec["token_count"], 5)
            # and never on disk
            self.assertNotIn("ws://x", Path(tmp, "run-1.jsonl").read_text(encoding="utf-8"))

    def test_log_guard_persists_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger("run-1", log_dir=tmp)
            logger.log_guard({"task_id": "t", "blocked": False, "counters": {"total_failures": 0}})
            records = logger.read()
            self.assertEqual(records[0]["event"], "guard_snapshot")
            self.assertEqual(records[0]["guard"]["task_id"], "t")


if __name__ == "__main__":
    unittest.main()
