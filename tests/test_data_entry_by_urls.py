"""Stage 11 — data entry from a list of AKS page URLs (dry-run planner).

Locks the read-only planner's seams: URL→pinned resolution (fail-closed on a bad
URL), the feed SEARCH (name ∪ url, deduped), candidate building via match_offer
with the PINNED page (its R01 name check rejects a search over-match), and the
NotLoggedInError fail-closed STOP. The browser is faked — no network, no CDP.
"""
import importlib.util
import json
import tempfile
import unittest
import urllib.parse as _up
from pathlib import Path

from src.aks_env import HttpProbeResult
from src.matcher import AksResolution, Candidate, SkippedOffer


def _load():
    spec = importlib.util.spec_from_file_location(
        "m11", str(Path(__file__).resolve().parents[1] / "scripts" / "11_data_entry_by_urls.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()

# A real 200 AKS product page body the resolver can parse (id + og:title + region/edition).
AKS_BODY = (
    '<meta property="og:title" content="Buy Neon Beats CD Key Compare Prices">'
    '<div data-product-id="205027"></div>'
    '<script>var x={"regions":{"2":{"filter_name":"GLOBAL"}},'
    '"editions":{"1":{"name":"Standard"}}};</script>'
)
URL = "https://www.allkeyshop.com/blog/buy-neon-beats-cd-key-compare-prices/"

# A pinned resolution for the planner tests (built directly, like test_matcher's PAGE).
PAGE = AksResolution(slug="neon-beats", url=URL, product_id="205027",
                     aks_name="Neon Beats", editions={"1": "Standard"},
                     regions={"2": "GLOBAL"}, official_platforms=())


def _ok(body):
    return lambda url, timeout=8, user_agent=None: HttpProbeResult(url=url, ok=True, status=200, body=body)


def _status(code, err=None):
    return lambda url, timeout=8, user_agent=None: HttpProbeResult(
        url=url, ok=False, status=code, body="", error=err)


class FakeSearchSession:
    """Serves rows keyed on the ``search[field]`` of the navigated URL."""

    def __init__(self, rows_by_field=None, *, login=False, feed_ui=True, login_after=None):
        self.rows_by_field = rows_by_field or {}
        self.login = login
        self.feed_ui = feed_ui
        self.login_after = login_after   # bounce to login once nav count exceeds this
        self._field = None
        self.nav = []

    def navigate(self, url, settle=None):
        self.nav.append(url)
        q = _up.parse_qs(_up.urlsplit(url).query)
        self._field = (q.get("search[field]") or [None])[0]

    def is_login_page(self):
        return self.login or (self.login_after is not None and len(self.nav) > self.login_after)

    def page_offer_rows(self):
        return [dict(r) for r in self.rows_by_field.get(self._field, [])]

    def feed_page_state(self):
        return {"feed_ui": self.feed_ui, "nav_max": 1, "is_login": self.login}


def _row(oid, name, url):
    return {"id": oid, "name": name, "url": url}


class SlugTests(unittest.TestCase):
    def test_cd_key(self):
        self.assertEqual(M.extract_slug(URL), "neon-beats")

    def test_query_and_slash(self):
        self.assertEqual(
            M.extract_slug("https://www.allkeyshop.com/blog/buy-elden-ring-cd-key-compare-prices?x=1"),
            "elden-ring")

    def test_account_page(self):
        self.assertEqual(
            M.extract_slug("https://www.allkeyshop.com/blog/buy-fortnite-steam-account-compare-prices/"),
            "fortnite")

    def test_not_an_aks_url(self):
        self.assertIsNone(M.extract_slug("https://g2a.com/some-game"))


class ResolvePinnedTests(unittest.TestCase):
    def test_ok(self):
        res = M.resolve_pinned(URL, _ok(AKS_BODY))
        self.assertEqual(res.product_id, "205027")
        self.assertEqual(res.aks_name, "Neon Beats")
        self.assertEqual(res.regions, {"2": "GLOBAL"})

    def test_bad_url_raises(self):
        from src.matcher import AksProbeUnreliable
        with self.assertRaises(AksProbeUnreliable):
            M.resolve_pinned("https://g2a.com/not-aks", _ok(AKS_BODY))

    def test_404_raises(self):
        from src.matcher import AksProbeUnreliable
        with self.assertRaises(AksProbeUnreliable):
            M.resolve_pinned(URL, _status(404))

    def test_transient_raises(self):
        from src.matcher import AksProbeUnreliable
        with self.assertRaises(AksProbeUnreliable):
            M.resolve_pinned(URL, _status(403, "403"))

    def test_200_no_product_raises(self):
        from src.matcher import AksNameUnreadable
        with self.assertRaises(AksNameUnreadable):
            M.resolve_pinned(URL, _ok("<html>no id here</html>"))


class DedupeTests(unittest.TestCase):
    def test_by_id_and_url(self):
        rows = [_row("1", "A", "u1"), _row("1", "A", "u1"),   # dup id
                _row("2", "B", "u1"),                          # dup url
                _row("3", "C", "u3")]
        out = M._dedupe_rows(rows)
        self.assertEqual([r["id"] for r in out], ["1", "3"])


class SearchUrlTests(unittest.TestCase):
    def test_targets_the_search_page_with_list_and_store(self):
        # The search form GETs page=aks-merchant-feeds-search with list+store as
        # SEPARATE params (verified live 2026-08-24 — appending to the feed page is
        # silently ignored and returns the unfiltered feed).
        u = M._search_url("38", "aks-merchant-feeds-9", "all", "Neon Beats", "name")
        q = dict(_up.parse_qsl(_up.urlsplit(u).query))
        self.assertEqual(q["page"], "aks-merchant-feeds-search")
        self.assertEqual(q["list"], "9")
        self.assertEqual(q["store"], "38")
        self.assertEqual(q["search[search]"], "Neon Beats")
        self.assertEqual(q["search[field]"], "name")


class SearchTests(unittest.TestCase):
    def test_unions_name_and_url_searches(self):
        session = FakeSearchSession({
            "name": [_row("1", "Neon Beats Steam", "https://m/1")],
            "url": [_row("1", "Neon Beats Steam", "https://m/1"),   # overlap → deduped
                    _row("2", "Neon Beats Deluxe", "https://m/2")],
        })
        rows, meta = M.search_offers_for_game(session, PAGE, "38", "all", "aks-merchant-feeds-9")
        self.assertEqual({r["id"] for r in rows}, {"1", "2"})
        self.assertEqual(meta["url_term"], "neon-beats")

    def test_empty_rendered_result_no_poll(self):
        session = FakeSearchSession({}, feed_ui=True)   # rendered, 0 matches
        rows, _ = M.search_offers_for_game(session, PAGE, "38", "all", "aks-merchant-feeds-9")
        self.assertEqual(rows, [])


class PlanMerchantTests(unittest.TestCase):
    def test_builds_candidate_for_matching_offer(self):
        session = FakeSearchSession({
            "name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                          "https://testmart.com/neon-beats-steam-global")],
        })
        per = M.plan_merchant(session, PAGE, "TestMart", "999", "all", "aks-merchant-feeds-9")
        self.assertEqual(len(per["candidates"]), 1)
        cand = per["candidates"][0]
        self.assertEqual(cand["aks_product_id"], "205027")
        self.assertEqual(cand["region"]["label"], "GLOBAL")

    def test_name_check_rejects_search_over_match(self):
        # the search returned an UNRELATED offer; match_offer's R01 must reject it
        # (the search only proposes rows — the pinned page's name check decides).
        session = FakeSearchSession({
            "name": [_row("200", "Totally Different Game - Steam Key - GLOBAL",
                          "https://testmart.com/totally-different-game")],
        })
        per = M.plan_merchant(session, PAGE, "TestMart", "999", "all", "aks-merchant-feeds-9")
        self.assertEqual(per["candidates"], [])
        self.assertEqual(len(per["skipped"]), 1)


class RunPlanTests(unittest.TestCase):
    def test_end_to_end_dry_run(self):
        session = FakeSearchSession({
            "name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                          "https://testmart.com/neon-beats-steam-global")],
        })
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            recap = M.run_plan([URL], [("TestMart", "999")], available="all",
                               feed_page="aks-merchant-feeds-9", endpoint="x",
                               run_dir=run_dir, http_get_fn=_ok(AKS_BODY), session=session)
            self.assertIsNone(recap["aborted"])
            self.assertEqual(recap["totals"]["resolved"], 1)
            self.assertEqual(recap["totals"]["candidates"], 1)
            self.assertTrue((run_dir / "recap.json").exists())
            M.write_report(recap, run_dir)
            report = (run_dir / "report.txt").read_text()
            self.assertIn("Neon Beats", report)
            self.assertIn("205027", report)

    def test_unresolvable_url_is_reported_not_fatal(self):
        session = FakeSearchSession({"name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                                                    "https://testmart.com/neon-beats")]})
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            # first URL 404s (unresolved), second resolves
            def http(url, timeout=8, user_agent=None):
                if "dead-game" in url:
                    return HttpProbeResult(url=url, ok=False, status=404, body="")
                return HttpProbeResult(url=url, ok=True, status=200, body=AKS_BODY)
            recap = M.run_plan(
                ["https://www.allkeyshop.com/blog/buy-dead-game-cd-key-compare-prices/", URL],
                [("TestMart", "999")], available="all", feed_page="aks-merchant-feeds-9",
                endpoint="x", run_dir=run_dir, http_get_fn=http, session=session)
            self.assertEqual(recap["totals"]["resolved"], 1)          # only the good one
            unresolved = [g for g in recap["games"] if not g["resolved"]]
            self.assertEqual(len(unresolved), 1)

    def test_not_logged_in_aborts_fail_closed(self):
        session = FakeSearchSession({"name": [_row("1", "Neon Beats", "u")]}, login=True)
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([URL], [("TestMart", "999")], available="all",
                               feed_page="aks-merchant-feeds-9", endpoint="x",
                               run_dir=Path(d), http_get_fn=_ok(AKS_BODY), session=session)
            self.assertEqual(recap["aborted"], "not_logged_in")

    def test_wrong_host_url_reported_not_crash(self):
        # a non-allkeyshop URL that matches the product path → reported unresolved,
        # never a crash (host-validated slug; review 2026-08-24).
        bad = "https://evil.com/blog/buy-foo-cd-key-compare-prices/"
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([bad], [("TestMart", "999")], available="all",
                               feed_page="aks-merchant-feeds-9", endpoint="x",
                               run_dir=Path(d), http_get_fn=_ok(AKS_BODY),
                               session=FakeSearchSession({}))
            self.assertEqual(recap["totals"]["resolved"], 0)
            self.assertFalse(recap["games"][0]["resolved"])

    def test_any_resolve_error_is_per_url_not_fatal(self):
        # a resolver blowing up (e.g. markup drift → AksPageUnparseable, or any
        # exception) is reported for THAT url and the batch continues.
        def http(url, timeout=8, user_agent=None):
            if "boom" in url:
                raise RuntimeError("markup drift")
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_BODY)
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan(
                ["https://www.allkeyshop.com/blog/buy-boom-cd-key-compare-prices/", URL],
                [("TestMart", "999")], available="all", feed_page="aks-merchant-feeds-9",
                endpoint="x", run_dir=Path(d), http_get_fn=http,
                session=FakeSearchSession({"name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                                                          "https://testmart.com/neon-beats")]}))
            self.assertEqual(recap["totals"]["resolved"], 1)      # the good one still planned
            self.assertEqual(len([g for g in recap["games"] if not g["resolved"]]), 1)

    def test_search_unreadable_flags_merchant_not_silent_zero(self):
        from unittest import mock
        # search page never renders (feed_ui False, no rows, not login) → per-merchant
        # error, never a silent found=0 (review 2026-08-24). Patch sleep to skip the backoff.
        session = FakeSearchSession({}, feed_ui=False)
        with mock.patch.object(M.time, "sleep", lambda *_: None):
            per = M.plan_merchant(session, PAGE, "TestMart", "999", "all", "aks-merchant-feeds-9")
        self.assertEqual(per.get("error"), "search_unreadable")
        self.assertEqual(per["candidates"], [])

    def test_abort_total_counts_pre_bounce_candidates(self):
        # merchant 1 yields a candidate, merchant 2 bounces to login: the total must
        # include merchant 1's candidate (review 2026-08-24). login_after=2 = after the
        # 2 searches (name+url) of the first merchant.
        session = FakeSearchSession(
            {"name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                           "https://testmart.com/neon-beats")]}, login_after=2)
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([URL], [("TestMart", "999"), ("Other", "888")],
                               available="all", feed_page="aks-merchant-feeds-9", endpoint="x",
                               run_dir=Path(d), http_get_fn=_ok(AKS_BODY), session=session)
            self.assertEqual(recap["aborted"], "not_logged_in")
            self.assertEqual(recap["totals"]["candidates"], 1)   # merchant 1's candidate counted


class LogEventsTests(unittest.TestCase):
    def test_run_emits_progress_events(self):
        class FakeLogger:
            def __init__(self): self.events = []
            def log(self, event, **f): self.events.append(event)
        lg = FakeLogger()
        session = FakeSearchSession({
            "name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                          "https://testmart.com/neon-beats")]})
        with tempfile.TemporaryDirectory() as d:
            M.run_plan([URL], [("TestMart", "999")], available="all",
                       feed_page="aks-merchant-feeds-9", endpoint="x", run_dir=Path(d),
                       http_get_fn=_ok(AKS_BODY), session=session, logger=lg)
        for ev in ("run_start", "game_resolved", "game_start", "candidate",
                   "merchant_done", "game_done", "run_done"):
            self.assertIn(ev, lg.events, ev)


if __name__ == "__main__":
    unittest.main()
