"""Stage 11 — data entry from a list of AKS page URLs (dry-run planner).

Search strategy (Romain 2026-08-25): ONE all-merchants search per game (no store
filter), then keep only the vetted-allowlist stores from the results — 2 searches
per game instead of 2×N. Locks: URL→pinned resolution (fail-closed per URL), the
unfiltered search + store filter, candidate building via match_offer on the pinned
page (R01 rejects a search over-match), NotLoggedInError / SearchUnreadable fail-
closed, and the live log events. The browser is faked — no network, no CDP.
"""
import importlib.util
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

AKS_BODY = (
    '<meta property="og:title" content="Buy Neon Beats CD Key Compare Prices">'
    '<div data-product-id="205027"></div>'
    '<script>var x={"regions":{"2":{"filter_name":"GLOBAL"}},'
    '"editions":{"1":{"name":"Standard"}}};</script>'
)
URL = "https://www.allkeyshop.com/blog/buy-neon-beats-cd-key-compare-prices/"
PAGE = AksResolution(slug="neon-beats", url=URL, product_id="205027",
                     aks_name="Neon Beats", editions={"1": "Standard"},
                     regions={"2": "GLOBAL"}, official_platforms=())
TARGETS = [("TestMart", "999"), ("Other", "888")]   # allowlist for the tests


def _ok(body):
    return lambda url, timeout=8, user_agent=None: HttpProbeResult(url=url, ok=True, status=200, body=body)


def _status(code, err=None):
    return lambda url, timeout=8, user_agent=None: HttpProbeResult(
        url=url, ok=False, status=code, body="", error=err)


def _seq(*probes):
    """A fake http_get returning each HttpProbeResult in turn (the last repeats),
    tracking the call count on ``.calls['n']``."""
    calls = {"n": 0}

    def fake(url, timeout=8, user_agent=None):
        p = probes[min(calls["n"], len(probes) - 1)]
        calls["n"] += 1
        return p

    fake.calls = calls
    return fake


def _row(oid, name, url, store="999"):
    return {"id": oid, "name": name, "url": url, "price": "", "store_id": store}


class FakeSearchSession:
    """Serves rows keyed on the ``search[field]`` of the navigated URL. Pagination
    (``p``) beyond page 1 returns nothing (a single short page)."""

    def __init__(self, rows_by_field=None, *, login=False, feed_ui=True, login_after=None):
        self.rows_by_field = rows_by_field or {}
        self.login = login
        self.feed_ui = feed_ui
        self.login_after = login_after
        self._field = None
        self._page = 1
        self.nav = []

    def navigate(self, url, settle=None):
        self.nav.append(url)
        q = _up.parse_qs(_up.urlsplit(url).query)
        self._field = (q.get("search[field]") or [None])[0]
        self._page = int((q.get("p") or ["1"])[0])

    def is_login_page(self):
        return self.login or (self.login_after is not None and len(self.nav) > self.login_after)

    def page_offer_rows(self):
        if self._page > 1:
            return []
        return [dict(r) for r in self.rows_by_field.get(self._field, [])]

    def feed_page_state(self):
        return {"feed_ui": self.feed_ui, "nav_max": 1, "is_login": self.login}


class SlugTests(unittest.TestCase):
    def test_cd_key(self):
        self.assertEqual(M.extract_slug(URL), "neon-beats")

    def test_query_and_slash(self):
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/buy-elden-ring-cd-key-compare-prices?x=1"), "elden-ring")

    def test_account_page(self):
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/buy-fortnite-steam-account-compare-prices/"), "fortnite")

    def test_key_page_without_cd(self):
        # Some AKS pages omit "cd-": buy-the-green-light-KEY-compare-prices/ (id
        # 216255) was rejected "not an AKS product URL" (Romain, 2026-09-01).
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/buy-the-green-light-key-compare-prices/"),
            "the-green-light")

    def test_slug_containing_key_word_not_amputated(self):
        # The non-greedy slug must not eat "cd"/"key" nor stop early inside a
        # word that contains "key".
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/buy-the-key-cd-key-compare-prices/"), "the-key")
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/buy-turnkey-key-compare-prices/"), "turnkey")

    def test_account_page_digit_platform(self):
        # Account platform can carry a digit (ps5/ps4) — was silently unmatched.
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/buy-007-first-light-ps5-account-compare-prices/"),
            "007-first-light")

    def test_wrong_host_is_none(self):
        self.assertIsNone(M.extract_slug("https://evil.com/blog/buy-foo-cd-key-compare-prices/"))

    def test_not_an_aks_url(self):
        self.assertIsNone(M.extract_slug("https://www.allkeyshop.com/other"))


class ResolvePinnedTests(unittest.TestCase):
    def test_ok(self):
        res = M.resolve_pinned(URL, _ok(AKS_BODY))
        self.assertEqual((res.product_id, res.aks_name, res.regions), ("205027", "Neon Beats", {"2": "GLOBAL"}))

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
            M.resolve_pinned(URL, _ok("<html>no id</html>"))

    def test_transient_503_retries_then_resolves(self):
        # A 503 server blip is retried and resolves on a later 200 (Romain 2026-09-01:
        # buy-inner-world 503'd then 200'd seconds later). No sleep under a stub.
        fake = _seq(
            HttpProbeResult(url=URL, ok=False, status=503, body=""),
            HttpProbeResult(url=URL, ok=False, status=503, body=""),
            HttpProbeResult(url=URL, ok=True, status=200, body=AKS_BODY),
        )
        res = M.resolve_pinned(URL, fake)
        self.assertEqual(res.product_id, "205027")
        self.assertEqual(fake.calls["n"], 3)

    def test_timeout_retried_then_resolves(self):
        fake = _seq(
            HttpProbeResult(url=URL, ok=False, status=None, body="", error="timeout"),
            HttpProbeResult(url=URL, ok=True, status=200, body=AKS_BODY),
        )
        res = M.resolve_pinned(URL, fake)
        self.assertEqual(res.product_id, "205027")
        self.assertEqual(fake.calls["n"], 2)

    def test_persistent_503_exhausts_bounded_and_raises(self):
        from src.matcher import AksProbeUnreliable
        fake = _seq(HttpProbeResult(url=URL, ok=False, status=503, body=""))
        with self.assertRaises(AksProbeUnreliable):
            M.resolve_pinned(URL, fake)
        self.assertEqual(fake.calls["n"], M.RESOLVE_ATTEMPTS)   # bounded, never infinite

    def test_404_is_a_real_absence_never_retried(self):
        from src.matcher import AksProbeUnreliable
        fake = _seq(HttpProbeResult(url=URL, ok=False, status=404, body=""))
        with self.assertRaises(AksProbeUnreliable):
            M.resolve_pinned(URL, fake)
        self.assertEqual(fake.calls["n"], 1)                    # 404 → no retry


class SearchUrlTests(unittest.TestCase):
    def test_search_page_list_no_store(self):
        # ONE all-merchants search: page=aks-merchant-feeds-search + list, NO store
        # (we filter results to the allowlist afterwards). Verified live 2026-08-25.
        u = M._search_url("aks-merchant-feeds-9", "all", "Neon Beats", "name")
        q = dict(_up.parse_qsl(_up.urlsplit(u).query))
        self.assertEqual(q["page"], "aks-merchant-feeds-search")
        self.assertEqual(q["list"], "9")
        self.assertNotIn("store", q)
        self.assertEqual(q["search[search]"], "Neon Beats")
        self.assertEqual(q["search[field]"], "name")

    def test_pagination_param(self):
        q = dict(_up.parse_qsl(_up.urlsplit(M._search_url("aks-merchant-feeds-9", "all", "x", "url", 2)).query))
        self.assertEqual(q["p"], "2")


class DedupeTests(unittest.TestCase):
    def test_by_id_and_url(self):
        rows = [_row("1", "A", "u1"), _row("1", "A", "u1"), _row("2", "B", "u1"), _row("3", "C", "u3")]
        self.assertEqual([r["id"] for r in M._dedupe_rows(rows)], ["1", "3"])


class SearchAllMerchantsTests(unittest.TestCase):
    def test_unions_name_and_url(self):
        session = FakeSearchSession({
            "name": [_row("1", "Neon Beats Steam", "https://m/1", store="999")],
            "url": [_row("1", "Neon Beats Steam", "https://m/1", store="999"),
                    _row("2", "Neon Beats Deluxe", "https://m/2", store="888")],
        })
        rows, meta = M.search_all_merchants(session, PAGE, "all", "aks-merchant-feeds-9")
        self.assertEqual({r["id"] for r in rows}, {"1", "2"})
        self.assertEqual(meta["url_term"], "neon-beats")
        self.assertFalse(meta["truncated"])

    def test_empty_rendered_no_poll(self):
        rows, _ = M.search_all_merchants(FakeSearchSession({}, feed_ui=True), PAGE, "all", "aks-merchant-feeds-9")
        self.assertEqual(rows, [])


class ReadSearchPagesTests(unittest.TestCase):
    """P2-13 (resolved live 2026-09-04): the AKS search shows all matches on ONE page,
    capped at SEARCH_RESULT_CAP; read page 1 only, truncated iff the cap was hit."""

    def test_sub_cap_result_is_complete_and_reads_page1_only(self):
        rows = [_row(str(i), f"G{i}", f"https://m/{i}") for i in range(5)]
        s = FakeSearchSession({"name": rows})
        got, truncated = M._read_search_pages(s, "aks-merchant-feeds-9", "all", "term", "name")
        self.assertEqual(len(got), 5)
        self.assertFalse(truncated)                             # sub-cap → complete
        self.assertTrue(all("&p=2" not in u and "?p=2" not in u for u in s.nav))  # page 1 only

    def test_cap_hit_flags_truncated(self):
        rows = [_row(str(i), f"G{i}", f"https://m/{i}") for i in range(M.SEARCH_RESULT_CAP)]
        s = FakeSearchSession({"name": rows})
        got, truncated = M._read_search_pages(s, "aks-merchant-feeds-9", "all", "term", "name")
        self.assertEqual(len(got), M.SEARCH_RESULT_CAP)
        self.assertTrue(truncated)                              # hit the cap → may be cut off

    def test_hundred_rows_is_not_truncated_anymore(self):
        # the old 100-row/3-page heuristic mis-flagged this as truncated (over-block);
        # a 100-row result is well under the 300 cap → COMPLETE.
        rows = [_row(str(i), f"G{i}", f"https://m/{i}") for i in range(100)]
        s = FakeSearchSession({"name": rows})
        _got, truncated = M._read_search_pages(s, "aks-merchant-feeds-9", "all", "term", "name")
        self.assertFalse(truncated)


class PlanFromRowsTests(unittest.TestCase):
    def test_builds_candidate(self):
        rows = [_row("100", "Neon Beats - Steam Key - GLOBAL", "https://testmart.com/neon-beats-global")]
        per = M.plan_from_rows(rows, PAGE, "TestMart", "999")
        self.assertEqual(len(per["candidates"]), 1)
        self.assertEqual(per["candidates"][0]["aks_product_id"], "205027")
        self.assertEqual(per["candidates"][0]["region"]["label"], "GLOBAL")

    def test_name_check_rejects_over_match(self):
        rows = [_row("200", "Totally Different Game - Steam Key - GLOBAL", "https://testmart.com/x")]
        per = M.plan_from_rows(rows, PAGE, "TestMart", "999")
        self.assertEqual(per["candidates"], [])
        self.assertEqual(len(per["skipped"]), 1)


class RunPlanTests(unittest.TestCase):
    def _session(self):
        # a matching row on store 999 (TestMart) + a row on a NON-allowlist store.
        return FakeSearchSession({
            "name": [_row("100", "Neon Beats - Steam Key - GLOBAL", "https://testmart.com/neon-beats", store="999"),
                     _row("300", "Neon Beats - Steam Key - GLOBAL", "https://x/300", store="777")],
        })

    def test_end_to_end_filters_to_allowlist(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            recap = M.run_plan([URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9",
                               endpoint="x", run_dir=run_dir, http_get_fn=_ok(AKS_BODY), session=self._session())
            self.assertIsNone(recap["aborted"])
            self.assertEqual(recap["totals"]["candidates"], 1)       # only the store-999 row
            g = recap["games"][0]
            self.assertEqual(g["search"]["off_allowlist"], 1)        # the store-777 row dropped
            self.assertEqual([m["merchant"] for m in g["merchants"]], ["TestMart"])
            # the off-allowlist row is RECORDED with its url (not just counted) so the
            # operator can see every search result (Romain 2026-08-25).
            self.assertEqual([o["url"] for o in g["off_allowlist_offers"]], ["https://x/300"])
            self.assertEqual(g["off_allowlist_offers"][0]["store_id"], "777")
            M.write_report(recap, run_dir)
            report = (run_dir / "report.txt").read_text()
            self.assertIn("Neon Beats", report)

    def test_unresolvable_url_reported_not_fatal(self):
        def http(url, timeout=8, user_agent=None):
            if "dead-game" in url:
                return HttpProbeResult(url=url, ok=False, status=404, body="")
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_BODY)
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan(
                ["https://www.allkeyshop.com/blog/buy-dead-game-cd-key-compare-prices/", URL],
                TARGETS, available="all", feed_page="aks-merchant-feeds-9", endpoint="x",
                run_dir=Path(d), http_get_fn=http, session=self._session())
            self.assertEqual(recap["totals"]["resolved"], 1)
            self.assertEqual(len([g for g in recap["games"] if not g["resolved"]]), 1)

    def test_any_resolve_error_is_per_url(self):
        def http(url, timeout=8, user_agent=None):
            if "boom" in url:
                raise RuntimeError("markup drift")
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_BODY)
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan(
                ["https://www.allkeyshop.com/blog/buy-boom-cd-key-compare-prices/", URL],
                TARGETS, available="all", feed_page="aks-merchant-feeds-9", endpoint="x",
                run_dir=Path(d), http_get_fn=http, session=self._session())
            self.assertEqual(recap["totals"]["resolved"], 1)
            self.assertEqual(len([g for g in recap["games"] if not g["resolved"]]), 1)

    def test_not_logged_in_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9",
                               endpoint="x", run_dir=Path(d), http_get_fn=_ok(AKS_BODY),
                               session=FakeSearchSession({}, login=True))
            self.assertEqual(recap["aborted"], "not_logged_in")
            self.assertEqual(recap["games"][0]["error"], "not_logged_in")

    def test_search_unreadable_flags_game_not_silent(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(M.time, "sleep", lambda *_: None):
            recap = M.run_plan([URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9",
                               endpoint="x", run_dir=Path(d), http_get_fn=_ok(AKS_BODY),
                               session=FakeSearchSession({}, feed_ui=False))
            self.assertEqual(recap["games"][0]["error"], "search_unreadable")
            self.assertEqual(recap["totals"]["candidates"], 0)

    def test_completed_game_counted_then_abort(self):
        # game 1 completes (1 candidate), game 2's search bounces to login → the
        # total keeps game 1's candidate (login_after=2 = after game 1's 2 searches).
        session = self._session()
        session.login_after = 2
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([URL, URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9",
                               endpoint="x", run_dir=Path(d), http_get_fn=_ok(AKS_BODY), session=session)
            self.assertEqual(recap["aborted"], "not_logged_in")
            self.assertEqual(recap["totals"]["candidates"], 1)


class LogEventsTests(unittest.TestCase):
    def test_run_emits_progress_events(self):
        class FakeLogger:
            def __init__(self): self.events = []
            def log(self, event, **f): self.events.append(event)
        lg = FakeLogger()
        # store 999: one MATCHING row (→ candidate) + one off-page row (→ skipped, so the
        # "skipped" progress event fires and streams live).
        session = FakeSearchSession({
            "name": [_row("100", "Neon Beats - Steam Key - GLOBAL", "https://testmart.com/neon-beats", store="999"),
                     _row("101", "Cyberpunk 2077 - Steam Key - GLOBAL", "https://testmart.com/cp2077", store="999")]})
        with tempfile.TemporaryDirectory() as d:
            M.run_plan([URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9", endpoint="x",
                       run_dir=Path(d), http_get_fn=_ok(AKS_BODY), session=session, logger=lg)
        for ev in ("run_start", "game_resolved", "game_start", "game_searched",
                   "candidate", "skipped", "merchant_done", "game_done", "run_done"):
            self.assertIn(ev, lg.events, ev)


if __name__ == "__main__":
    unittest.main()
