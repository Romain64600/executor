"""Romain's audit of 2026-09-17 — the sort GO could target a scan the operator never opened.

TWO PASSES, same defect, and the first fix did not go far enough.

**Pass 1 — the action read a MUTABLE global across its awaits.** ``runAction`` read
``PLAN_RUN_ID`` / ``PLAN.plan_digest`` at three moments separated by two ``await``s. A
``loadPlan()`` landing during either await swapped both, so the move went to B carrying B's
digest. The server gate cannot catch that: the digest really is B's current one. Fixed by
capturing the identity in consts at the click.

**Pass 2 — the click was STILL too late** (« le gel au clic arrive trop tard »). Romain
reproduced it:

  1. the load of B starts; A stays on screen;
  2. the operator opens A's offers;
  3. B finishes loading; the modal keeps showing A;
  4. GO sends B, with B's digest.

The click-time capture reads whatever the page has loaded by then, which is B — while the
offers under the operator's eyes are A's. **The identity must be bound where the operator's
context is born**: at the render of the cards. It now travels
``render() → card() → openList() → MODAL_RUN_ID / MODAL_DIGEST``, and the commands shown, the
GO and the polling all read the open modal's identity. Closing the modal drops it.

**A third defect, from the read-only sweep of the same class** (Romain's GO to fix it): the
poll ticks carried no generation, so a tick still in flight from a finished run could clear
the live interval, move the shared log offset and paint the previous run's conclusion. Pinned
by ``TheStalePollTickIsRetiredTests``.

Why freezing the digest for the life of a modal is safe: ``src/sort_move.py`` is pure and
writes nothing, so a move does not rewrite ``sort_plan.json`` — the digest is stable across
the dry-run → canary → batch sequence of one modal, and changes only when the scan is re-run,
which is exactly when the server SHOULD answer 409.

NOTE ON WHAT THIS FILE PROVES. These assertions are STRUCTURAL: they read ``sort.js`` as TEXT
and pin the ordering and ownership the race turns on. They are cheap and they fail loudly if
someone unpicks the shape of the fix — all 25 fail before pass 1, and 14 still fail against
507bdf8 (the pass-1 fix); the rest pin pass 1 itself. But a structural test can only notice
the spelling it was told about.

**The behaviour is proven elsewhere, by execution.** On 2026-09-17 Romain approved node as a
test-only dependency, so ``tests/js/sort_race.test.mjs`` now loads this very file into a
stubbed browser and replays his repro with the network answers released by hand. Read
``tests/test_console_js_simulation.py`` for what that harness discriminates. When the two
disagree, the simulation is the authority and this file is the one to correct.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = (ROOT / "src" / "admin" / "static" / "sort.js").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = JS.index(f"function {name}(")
    depth = 0
    for j in range(JS.index("{", start), len(JS)):
        if JS[j] == "{":
            depth += 1
        elif JS[j] == "}":
            depth -= 1
            if depth == 0:
                return JS[start:j + 1]
    raise AssertionError(f"unbalanced body for {name}")


def _no_comments(src: str) -> str:
    """Comment lines name the very identifiers under test — drop them."""

    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))


RENDER = _body("render")
CARD = _body("card")
OPEN_LIST = _body("openList")
RENDER_CMDS = _body("renderCmds")
RUN_ACTION = _body("runAction")
START_POLL = _body("startPoll")
RUN_ACTION_CODE = _no_comments(RUN_ACTION)


class TheIdentityIsBoundWhereTheCardsArePaintedTests(unittest.TestCase):
    """Pass 2 — the operator's context is born at the render, not at the click."""

    def test_render_captures_the_plan_it_paints(self):
        self.assertIn("const runId = PLAN_RUN_ID, planDigest = PLAN && PLAN.plan_digest;",
                      _no_comments(RENDER))

    def test_the_capture_precedes_the_cards_it_is_handed_to(self):
        code = _no_comments(RENDER)
        self.assertLess(code.index("const runId = PLAN_RUN_ID"), code.index("card(id, g"))

    def test_the_cards_carry_it(self):
        self.assertIn("card(id, g, runId, planDigest)", RENDER)
        self.assertTrue(CARD.startswith("function card(id, g, runId, planDigest)"), CARD[:48])

    def test_every_card_button_opens_the_list_with_it(self):
        opens = re.findall(r"openList\(([^)]*)\)", CARD)
        self.assertTrue(opens)
        for args in opens:
            self.assertEqual(args.strip(), "id, g, runId, planDigest")


class TheOpenModalOwnsThatIdentityTests(unittest.TestCase):
    def test_open_list_takes_it_and_stores_it(self):
        self.assertTrue(OPEN_LIST.startswith("function openList(id, g, runId, planDigest)"),
                        OPEN_LIST[:60])
        self.assertIn("MODAL_RUN_ID = runId || null;", OPEN_LIST)
        self.assertIn("MODAL_DIGEST = planDigest || null;", OPEN_LIST)

    def test_it_is_stored_before_anything_is_rendered(self):
        code = _no_comments(OPEN_LIST)
        self.assertLess(code.index("MODAL_DIGEST = planDigest"), code.index("renderCmds(id)"),
                        "the commands would otherwise be built from the previous modal's run")

    def test_the_copyable_commands_name_the_open_plan(self):
        self.assertIn("runs/${MODAL_RUN_ID}", RENDER_CMDS)
        self.assertNotIn("PLAN_RUN_ID", RENDER_CMDS)

    def test_closing_the_modal_drops_it(self):
        close = _body("closeOffers")
        self.assertIn("MODAL_RUN_ID = null", close)
        self.assertIn("MODAL_DIGEST = null", close)
        self.assertIn("stopPoll()", close)
        self.assertIn("MODAL_SEQ++", close)

    def test_the_window_is_retired_SYNCHRONOUSLY_with_the_gesture(self):
        """Romain, 4e puis 5e passe. First: Escape closed the dialog natively, bypassing our
        button handlers entirely. Hanging the cleanup on the dialog's "close" event fixed the
        coverage — but not the timing: per the HTML standard the close steps QUEUE that event,
        so an awaited continuation resumes between the gesture and the handler and still fires
        its POST. Every closing path we drive now retires the window itself, first; the
        "cancel" listener is the synchronous hook for Escape; the "close" listener is the net
        for endings we do not drive, and only acts while the dialog is still closed, so a
        queued event can never retire the NEXT opening. All of it is exercised live in
        ``tests/js/sort_race.test.mjs`` and dies under mutation."""

        self.assertIn('$("#modal-close").addEventListener("click", () => { closeOffers(); '
                      '$("#offers-modal").close(); });', JS)
        self.assertIn('if (e.target.id === "offers-modal") { closeOffers(); e.target.close(); }', JS)
        self.assertIn('$("#offers-modal").addEventListener("cancel", closeOffers);', JS)
        self.assertIn('$("#offers-modal").addEventListener("close", () => '
                      '{ if (!$("#offers-modal").open) closeOffers(); });', JS)

    def test_the_deferred_event_cannot_retire_the_next_opening(self):
        close_line = [l for l in JS.splitlines()
                      if 'addEventListener("close"' in l and "offers-modal" in l]
        self.assertEqual(len(close_line), 1)
        self.assertIn('!$("#offers-modal").open', close_line[0],
                      "without this check a queued event retires the window reopened since")

class TheActionReadsTheModalNotThePageTests(unittest.TestCase):
    """Pass 1 + 2 — nothing mutable may decide anything once the modal is open."""

    def test_the_action_takes_the_modal_identity(self):
        self.assertIn("const runId = MODAL_RUN_ID;", RUN_ACTION)
        self.assertIn("const planDigest = MODAL_DIGEST;", RUN_ACTION)

    def test_it_is_taken_before_every_await(self):
        self.assertLess(RUN_ACTION_CODE.index("const planDigest"),
                        RUN_ACTION_CODE.index("await "))

    def test_no_open_plan_approves_nothing(self):
        self.assertIn("if (!runId) return;", RUN_ACTION)

    def test_the_two_calls_and_the_digest_use_it(self):
        for needle in ("submit/status?offset=0", "/sort/move"):
            with self.subTest(needle=needle):
                line = [l for l in RUN_ACTION.splitlines() if needle in l]
                self.assertEqual(len(line), 1)
                self.assertIn("encodeURIComponent(runId)", line[0])
        self.assertIn("body.plan_digest = planDigest;", RUN_ACTION)

    def test_the_only_surviving_mention_of_the_mutable_global_is_the_warning(self):
        mentions = [l.strip() for l in RUN_ACTION_CODE.splitlines()
                    if re.search(r"\bPLAN_RUN_ID\b|\bPLAN\.plan_digest\b", l)]
        self.assertEqual(mentions, ["if (PLAN_RUN_ID !== runId) {"], mentions)

    def test_the_operator_is_told_when_the_page_moved_on(self):
        block = RUN_ACTION[RUN_ACTION.index("if (PLAN_RUN_ID !== runId) {"):]
        self.assertIn("appendStatus(", block[:400])
        self.assertIn("scan affiché a changé", block[:400])


class ThePollFollowsTheApprovedRunTests(unittest.TestCase):
    def test_start_poll_takes_the_run(self):
        self.assertTrue(START_POLL.startswith("function startPoll(runId)"), START_POLL[:40])

    def test_it_has_no_fallback_to_the_mutable_global(self):
        code = _no_comments(START_POLL)
        self.assertIn("const rid = runId;", code)
        self.assertNotIn("PLAN_RUN_ID", code,
                         "a fallback would quietly tail another run's event log")

    def test_the_poll_url_uses_it(self):
        line = [l for l in START_POLL.splitlines() if "submit/status?offset=${OFFSET}" in l]
        self.assertEqual(len(line), 1)
        self.assertIn("encodeURIComponent(rid)", line[0])

    def test_every_call_site_passes_the_approved_run(self):
        calls = re.findall(r"(?<!function )startPoll\(([^)]*)\)", JS)
        self.assertTrue(calls)
        for arg in calls:
            self.assertEqual(arg.strip(), "runId")


class TheStalePollTickIsRetiredTests(unittest.TestCase):
    """Third defect of the day, surfaced by the read-only sweep and fixed on Romain's GO.

    ``tick`` is async. ``clearInterval`` cannot cancel a tick whose ``getJSON`` is already in
    flight, and nothing marked which poll a tick belonged to. Closing the modal mid-request
    then starting another action let the OLD tick resume and act on the NEW poll's state: its
    ``stopPoll()`` cleared the LIVE interval (the running action's log froze), its ``OFFSET``
    write moved the new run's log window, and ``finishStatus()`` painted the PREVIOUS run's
    conclusion and exit code, re-enabling the buttons. No wrong write — a lying display."""

    def test_the_poll_has_a_generation_token(self):
        self.assertIn("POLL_SEQ", JS)
        self.assertIn("const seq = POLL_SEQ;", START_POLL)

    def test_stopping_retires_the_generation(self):
        stop = [l for l in JS.splitlines() if l.startswith("function stopPoll(")]
        self.assertEqual(len(stop), 1)
        self.assertIn("POLL_SEQ++", stop[0])
        self.assertIn("clearInterval(POLL)", stop[0])

    def test_the_token_is_taken_after_the_previous_poll_is_retired(self):
        code = _no_comments(START_POLL)
        self.assertLess(code.index("stopPoll();"), code.index("const seq = POLL_SEQ;"),
                        "taking the token first would keep the OLD generation alive")

    def test_a_retired_tick_returns_before_touching_anything(self):
        code = _no_comments(START_POLL)
        guard = code.index("if (seq !== POLL_SEQ) return;")
        self.assertLess(code.index("await getJSON"), guard, "the guard must follow the await")
        for after in ("OFFSET = s.offset", "appendStatus(", "setBusy(", "finishStatus(s)"):
            with self.subTest(after=after):
                self.assertLess(guard, code.index(after))


class TheNeighbouringPollLoopsAreGuardedTests(unittest.TestCase):
    """Romain: « Fix les 2 boucles de sondage voisines ».

    ``pollScan`` (sort.js) and ``startPolling`` (auto.js) carried the same pattern as the move
    poll. ``pollScan`` also read the MUTABLE ``SCAN_RUN`` inside its tick, so a second scan
    redirected the first one's polling; it now takes the run as a parameter and freezes it.

    ``auto.js`` is the honest half of this entry. Its guard is real — a tick that concluded a
    sweep must not be able to conclude a LATER one, clearing the live interval and re-enabling
    the GO while a sweep is still writing on AKS — but the sequence needs two overlapping
    pollings, and the page's own gating (the launch button is disabled while a sweep runs)
    makes it hard to reach through the real UI. It is therefore defence in depth, pinned
    structurally here, with **no live repro** — unlike ``pollScan``, whose fix IS exercised by
    ``tests/js/sort_race.test.mjs`` and dies under mutation."""

    def test_the_fresh_scan_poll_freezes_its_run(self):
        body = _body("pollScan")
        self.assertTrue(body.startswith("function pollScan(runId)"), body[:40])
        self.assertIn("const rid = runId;", body)
        self.assertNotIn("SCAN_RUN", body, "the mutable global must not decide anything")

    def test_the_fresh_scan_poll_has_a_generation(self):
        self.assertIn("const seq = SCAN_SEQ;", _body("pollScan"))
        stop = [l for l in JS.splitlines() if l.startswith("function stopScanPoll(")]
        self.assertEqual(len(stop), 1)
        self.assertIn("SCAN_SEQ++", stop[0])

    def test_the_auto_tab_sweep_poll_has_a_generation(self):
        auto = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
        self.assertIn("POLL_SEQ", auto)
        self.assertIn("const seq = POLL_SEQ;", auto)
        # Trois attentes depuis le 2026-09-26 : l'état du gestionnaire, le recap, et les
        # compteurs de la page en cours pendant sa saisie (`api/runs/<run>`) — une garde après
        # CHACUNE, sinon un tick d'un ancien sweep peindrait dans le nouveau.
        self.assertEqual(auto.count("if (seq !== POLL_SEQ) return;"), 3,
                         "its tick awaits THREE times — one guard after each await")
        end = auto[auto.index("function endSweepUi("):]
        self.assertIn("POLL_SEQ++", end[:400])


class TheLaunchItselfIsGuardedTests(unittest.TestCase):
    """Romain, P2 puis 3e passe : « La génération protège les requêtes de suivi, mais pas le
    lancement », puis « le garde compare uniquement le scan, pas l'ouverture de fenêtre » et
    « une réponse d'erreur contourne entièrement le nouveau garde ».

    Comparing the RUN was not enough: switching to another list of the SAME scan keeps the run
    identical, so one list's outcome landed in another's window. And the ``catch`` ran before
    any check, so a late refusal painted into a foreign window and re-enabled ITS buttons.
    The identity is now the OPENING itself (``MODAL_SEQ``), checked after EVERY await — the
    log-offset read, the POST's success path AND its error path. All three are exercised live
    in ``tests/js/sort_race.test.mjs`` and each dies under mutation."""

    def test_the_action_captures_its_own_window_opening(self):
        self.assertIn("const seq = MODAL_SEQ;", RUN_ACTION)
        self.assertIn("const gone = () => seq !== MODAL_SEQ;", RUN_ACTION)

    def test_every_opening_and_every_close_retires_the_previous_one(self):
        self.assertIn("MODAL_SEQ++", _body("openList"))
        self.assertIn("MODAL_SEQ++", _body("closeOffers"))

    def test_each_of_the_three_awaits_is_followed_by_the_check(self):
        code = _no_comments(RUN_ACTION)
        awaits = [i for i in range(len(code)) if code.startswith("await ", i)]
        self.assertEqual(len(awaits), 2, "offset read + POST")
        self.assertEqual(code.count("gone()"), 3,
                         "one after the offset read, one in the catch, one on the success path")

    def test_the_error_path_checks_BEFORE_it_paints_or_re_enables(self):
        # the POST's catch, not the one-line catch of the offset read above it
        catch = RUN_ACTION[RUN_ACTION.rindex("  } catch (e) {"):]
        catch = catch[:catch.index("\n  }")]
        self.assertIn("refusé", catch, "wrong catch block picked up")
        self.assertLess(catch.index("gone()"), catch.index("appendStatus("),
                        "a late refusal would paint into whatever window is open now")
        self.assertLess(catch.index("gone()"), catch.index("disabled = false"),
                        "a late refusal would re-enable another window's buttons mid-launch")

    def test_abandoning_uses_the_page_status_never_the_pane(self):
        block = RUN_ACTION[RUN_ACTION.index("const abandon = "):]
        block = block[:block.index("\n  };")]
        self.assertIn("setStatus(", block, "the page's own status line, never the pane")
        self.assertNotIn("appendStatus(", block,
                         "appendStatus writes into the modal pane — which is another window's")

    def test_it_is_checked_before_the_poll_starts(self):
        code = _no_comments(RUN_ACTION)
        self.assertLess(code.rindex("gone()"), code.index("startPoll(runId)"))


class ThePreFixSpellingsAreGoneTests(unittest.TestCase):
    def test_no_action_path_reads_the_mutable_globals_any_more(self):
        for gone in (
            "getJSON(`api/runs/${encodeURIComponent(PLAN_RUN_ID)}/submit/status?offset=0`)",
            "postJSON(`api/runs/${encodeURIComponent(PLAN_RUN_ID)}/sort/move`",
            "body.plan_digest = PLAN && PLAN.plan_digest;",
            "runs/${PLAN_RUN_ID} --list",
            "onclick: () => openList(id, g) }",
        ):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, JS)


class TheDocumentedFlagExistsTests(unittest.TestCase):
    """Romain's second point: the note recommended a flag 05_submit does not have."""

    def test_the_manual_note_does_not_prescribe_a_sweep_only_flag(self):
        handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
        note = handoff[handoff.index("**`--prove-gone-by-search` sur toute saisie manuelle"):]
        note = note[:note.index("**Safe-auto sweep")]
        self.assertIn("n'a pas de `--prove-gone-scan`", note)
        self.assertIn("il suffit de retirer", note)

    def test_the_flag_really_is_absent_from_the_manual_script(self):
        submit = (ROOT / "scripts" / "05_submit.py").read_text(encoding="utf-8")
        self.assertNotIn("prove-gone-scan", submit)
        self.assertIn("--prove-gone-by-search", submit)
        sweep = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")
        self.assertIn("prove_gone_scan", sweep)


if __name__ == "__main__":
    unittest.main()
