"""The "sweep de nuit" button of the Data entry auto tab (2026-09-16).

Romain: « Dans l'onglet Data entry auto, je voudrais un bouton pour lancer un sweep sur tout
les marchands whitelisted (sauf si ce sweep est deja en cours) ».

Two properties matter and both are pinned here:

1. **the target list is READ from the allowlist, server-side** — the button sends
   ``all_allowlisted: true`` and never a merchant list, so it cannot drift from
   ``AUTO_MERCHANTS`` the day a merchant is added (same source as the CLI's
   ``--all-allowlisted``);
2. **"sauf si ce sweep est deja en cours"** — refused server-side by the manager's
   one-run-at-a-time guard, not merely greyed out in the page.

The typed GO of every real-write path still applies."""

import pathlib
import unittest

from src.admin.auto_merchants import AUTO_MERCHANTS, allowed_list

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "admin" / "static"
APP = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")
HTML = (STATIC / "auto.html").read_text(encoding="utf-8")
JS = (STATIC / "auto.js").read_text(encoding="utf-8")
MANAGER = (ROOT / "src" / "admin" / "submit_manager.py").read_text(encoding="utf-8")


class ButtonExistsTests(unittest.TestCase):
    def test_the_button_is_in_the_auto_tab(self):
        self.assertIn('id="launch-all"', HTML)
        self.assertIn("sweep de nuit", HTML.lower())

    def test_it_starts_disabled(self):
        # the markup ships disabled; syncGo enables it only on a typed GO with no run active
        button = HTML[HTML.index('id="launch-all"'):]
        self.assertIn("disabled", button[:200])

    def test_it_is_wired(self):
        self.assertIn('$("#launch-all").addEventListener("click"', JS)


class TargetsComeFromTheAllowlistTests(unittest.TestCase):
    def test_the_client_sends_no_merchant_list(self):
        handler = JS[JS.index('$("#launch-all").addEventListener'):]
        handler = handler[:handler.index("$(\"#stop-btn\")")]
        self.assertIn("all_allowlisted: true", handler)
        self.assertNotIn("collectTargets", handler,
                         "the night sweep must not send a client-built merchant list")

    def test_the_server_reads_the_allowlist(self):
        self.assertIn('body.get("all_allowlisted", False)', APP)
        self.assertIn("auto_allowed_list()", APP)

    def test_the_server_refuses_a_mixed_request(self):
        self.assertIn("targets_conflict", APP)

    def test_an_empty_allowlist_fails_closed(self):
        self.assertIn("allowlist_empty", APP)

    def test_the_allowlist_endpoint_feeds_the_count(self):
        self.assertIn("api/data-entry/merchants", JS)
        self.assertIn("all-count", JS)
        self.assertIn('id="all-count"', HTML)


class AlreadyRunningIsRefusedTests(unittest.TestCase):
    """« sauf si ce sweep est deja en cours » — server-side, not just in the page."""

    def test_the_manager_allows_one_run_at_a_time(self):
        self.assertIn("submit_in_progress", MANAGER)
        self.assertIn("_ensure_free", MANAGER)

    def test_the_sweep_launcher_calls_the_guard(self):
        launcher = MANAGER[MANAGER.index("def start_data_entry_auto"):]
        launcher = launcher[:launcher.index("argv = [")]
        self.assertIn("self._ensure_free()", launcher)

    def test_the_button_is_also_greyed_while_a_sweep_runs(self):
        self.assertIn("SWEEP_RUNNING", JS)
        sync = JS[JS.index("const all = $(\"#launch-all\")"):]
        self.assertIn("!SWEEP_RUNNING", sync[:200])


class TypedGoStillRequiredTests(unittest.TestCase):
    def test_the_client_sends_the_typed_go(self):
        handler = JS[JS.index('$("#launch-all").addEventListener'):]
        self.assertIn('confirm: "GO"', handler[:600])

    def test_the_server_enforces_it(self):
        self.assertIn("confirm_required", APP)


class WhatTheSweepWouldCoverTests(unittest.TestCase):
    def test_it_covers_every_allowlisted_merchant(self):
        served = {(m["name"], m["store_id"]) for m in allowed_list()}
        self.assertEqual(served, set(AUTO_MERCHANTS))

    def test_continue_on_halt_is_on_for_the_night(self):
        """One merchant's fail-closed stop must not end the whole night."""

        handler = JS[JS.index('$("#launch-all").addEventListener'):]
        self.assertIn("continue_on_halt", handler[:900])


if __name__ == "__main__":
    unittest.main()
