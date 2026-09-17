"""Romain's audit of 2026-09-17 — the sort GO could STILL target the wrong scan.

The 2026-09-16 pass fixed the *repaint* race (a stale plan answer could paint over a newer
one) and added a server-side digest gate. Romain found the REMAINING hole on the WRITE path:

    « Dans src/admin/static/sort.js, l'action attend une réponse réseau avant de relire le
      scan et son empreinte. Si le chargement d'un autre plan termine pendant cette attente :
      GO cliqué sur A ; requête de déplacement envoyée pour B, avec l'empreinte valide de B. »

``runAction`` read ``PLAN_RUN_ID`` / ``PLAN.plan_digest`` at THREE different moments — once
before the status-baseline ``await``, again after it for the POST, and again on every poll
tick. A ``loadPlan()`` landing during either await swaps both globals to another scan, so the
POST goes to B carrying B's digest. **The server gate cannot catch this**: that digest really
is B's current one, so the move is accepted — on a plan the operator never examined.

The fix freezes the approved identity at the CLICK, before any await, and every later step
(status baseline, POST, polling) reads the frozen consts. The operator is told when the screen
moved on under them, so a coherent action is never silently watched on the wrong cards.

NOTE ON SIMULATION. Romain asked for a test driving delayed network answers. That needs a
JavaScript runtime to execute ``sort.js``; none is installed on this box (no node / deno /
quickjs, and no Python JS engine), and AGENTS.md forbids adding a dependency without his go.
These assertions are therefore STRUCTURAL — they pin the exact ordering property the race
turns on, and every one of them fails against the pre-fix file (verified by checking out the
parent revision). If node is ever added, a live harness belongs next to this file.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = (ROOT / "src" / "admin" / "static" / "sort.js").read_text(encoding="utf-8")


def _body(name: str) -> str:
    """The source of one top-level function, brace-matched."""

    start = JS.index(f"function {name}(")
    depth, i = 0, JS.index("{", start)
    for j in range(i, len(JS)):
        if JS[j] == "{":
            depth += 1
        elif JS[j] == "}":
            depth -= 1
            if depth == 0:
                return JS[start:j + 1]
    raise AssertionError(f"unbalanced body for {name}")


RUN_ACTION = _body("runAction")
START_POLL = _body("startPoll")


def _no_comments(src: str) -> str:
    """Comment lines mention the very identifiers under test — drop them."""

    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))


RUN_ACTION_CODE = _no_comments(RUN_ACTION)


class IdentityIsFrozenBeforeAnyAwaitTests(unittest.TestCase):
    """The whole race lives in the gap between the click and the POST."""

    def test_the_run_and_the_digest_are_captured_as_consts(self):
        self.assertIn("const runId = PLAN_RUN_ID;", RUN_ACTION)
        self.assertIn("const planDigest = PLAN && PLAN.plan_digest;", RUN_ACTION)

    def test_the_capture_precedes_every_await(self):
        capture = RUN_ACTION_CODE.index("const planDigest")
        first_await = RUN_ACTION_CODE.index("await ")
        self.assertLess(capture, first_await,
                        "an await before the capture reopens the swap window")

    def test_nothing_is_approved_when_no_plan_is_displayed(self):
        self.assertIn("if (!runId) return;", RUN_ACTION)


class EveryLaterStepReadsTheFrozenValuesTests(unittest.TestCase):
    """PLAN_RUN_ID / PLAN are MUTABLE — after the capture they must not decide anything."""

    def test_the_status_baseline_uses_the_frozen_run(self):
        line = [l for l in RUN_ACTION.splitlines() if "submit/status?offset=0" in l]
        self.assertEqual(len(line), 1)
        self.assertIn("encodeURIComponent(runId)", line[0])

    def test_the_move_posts_to_the_frozen_run_with_the_frozen_digest(self):
        line = [l for l in RUN_ACTION.splitlines() if "/sort/move" in l]
        self.assertEqual(len(line), 1)
        self.assertIn("encodeURIComponent(runId)", line[0])
        self.assertIn("body.plan_digest = planDigest;", RUN_ACTION)

    def test_no_step_after_the_capture_re_reads_the_mutable_globals(self):
        """The ONLY post-capture mention of PLAN_RUN_ID may be the divergence warning."""

        capture_end = RUN_ACTION_CODE.index("const planDigest")
        capture_end = RUN_ACTION_CODE.index("\n", capture_end)
        after = RUN_ACTION_CODE[capture_end:]
        mentions = [l.strip() for l in after.splitlines()
                    if re.search(r"\bPLAN_RUN_ID\b|\bPLAN\.plan_digest\b", l)]
        self.assertEqual(mentions, ["if (PLAN_RUN_ID !== runId) {"], mentions)


class ThePollFollowsTheApprovedRunTests(unittest.TestCase):
    def test_start_poll_takes_the_run_and_uses_it(self):
        self.assertTrue(START_POLL.startswith("function startPoll(runId)"), START_POLL[:40])
        line = [l for l in START_POLL.splitlines() if "submit/status?offset=${OFFSET}" in l]
        self.assertEqual(len(line), 1)
        self.assertIn("encodeURIComponent(rid)", line[0])

    def test_every_call_site_passes_the_frozen_run(self):
        calls = re.findall(r"(?<!function )startPoll\(([^)]*)\)", JS)
        self.assertTrue(calls)
        for arg in calls:
            self.assertEqual(arg.strip(), "runId",
                             "a bare startPoll() would tail whatever scan is displayed")


class TheOperatorIsToldWhenTheScreenMovedOnTests(unittest.TestCase):
    """The action stays the approved one; the CARDS may now be another scan's."""

    def test_a_divergence_is_surfaced_in_the_status_pane(self):
        self.assertIn("if (PLAN_RUN_ID !== runId) {", RUN_ACTION)
        block = RUN_ACTION[RUN_ACTION.index("if (PLAN_RUN_ID !== runId) {"):]
        self.assertIn("appendStatus(", block[:400])
        self.assertIn("scan affiché a changé", block[:400])


class ThePreFixSpellingsAreGoneTests(unittest.TestCase):
    def test_the_three_late_reads_no_longer_exist(self):
        for gone in (
            "getJSON(`api/runs/${encodeURIComponent(PLAN_RUN_ID)}/submit/status?offset=0`)",
            "postJSON(`api/runs/${encodeURIComponent(PLAN_RUN_ID)}/sort/move`",
            "body.plan_digest = PLAN && PLAN.plan_digest;",
        ):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, JS)


if __name__ == "__main__":
    unittest.main()
