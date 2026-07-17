"""OP1 (audit 2026-07-17): the cross-process browser lock — one tab, one
driver. flock-based, advisory, self-releasing on process death."""

import tempfile
import unittest
from pathlib import Path

from src.browser_lock import BrowserBusyError, browser_lock


class BrowserLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_lock_acquires_and_releases(self):
        with browser_lock(self.root, label="test-a"):
            lock_file = self.root / "state" / "browser.lock"
            self.assertTrue(lock_file.is_file())
            self.assertIn("test-a", lock_file.read_text(encoding="utf-8"))
        # released: a second acquisition succeeds
        with browser_lock(self.root, label="test-b"):
            pass

    def test_second_holder_is_refused_with_holder_label(self):
        with browser_lock(self.root, label="05_submit --submit"):
            with self.assertRaises(BrowserBusyError) as ctx:
                with browser_lock(self.root, label="02_extract"):
                    pass
            self.assertIn("05_submit --submit", str(ctx.exception))

    def test_release_on_exception_inside_block(self):
        with self.assertRaises(RuntimeError):
            with browser_lock(self.root, label="test"):
                raise RuntimeError("boom")
        with browser_lock(self.root, label="after"):
            pass  # lock was released despite the exception

    def test_label_cleared_after_release(self):
        with browser_lock(self.root, label="test-a"):
            pass
        content = (self.root / "state" / "browser.lock").read_text(encoding="utf-8")
        self.assertEqual(content.strip(), "")


if __name__ == "__main__":
    unittest.main()
