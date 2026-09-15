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


class NumeralSearchTermTests(unittest.TestCase):
    def test_search_tries_the_other_numeral_spelling_by_name_and_url(self):
        # [R42] 2026-09-10: MMOGA "Crusader Kings III" was invisible to the feed search for
        # the AKS page "Crusader Kings 3" (terms "Crusader Kings 3" / "crusader-kings-3").
        res = AksResolution("crusader-kings-3", "https://aks/x", "1", "Crusader Kings 3", {"1": {"name": "Standard"}})
        session = FakeSearchSession({"name": [], "url": []})
        rows, meta = M.search_all_merchants(session, res, "all", "aks-merchant-feeds-9")
        self.assertEqual(rows, [])
        self.assertEqual(meta["alt_terms"], ["Crusader Kings III", "crusader-kings-iii"])
        self.assertEqual(len(session.nav), 4)                       # 2 spellings × name/url
        terms = [_up.parse_qs(_up.urlsplit(u).query) for u in session.nav]
        self.assertTrue(any("Crusader Kings III" in str(q) for q in terms))
        self.assertTrue(any("crusader-kings-iii" in str(q) for q in terms))

    def test_no_numeral_means_no_extra_search(self):
        res = AksResolution("neon-beats", "https://aks/x", "1", "Neon Beats", {"1": {"name": "Standard"}})
        session = FakeSearchSession({"name": [], "url": []})
        _, meta = M.search_all_merchants(session, res, "all", "aks-merchant-feeds-9")
        self.assertEqual(meta["alt_terms"], [])
        self.assertEqual(len(session.nav), 2)


class PacingTests(unittest.TestCase):
    def test_paces_between_urls_only_for_the_real_http_get(self):
        # Audit 2026-09-09: the by-urls resolve loop had no inter-URL pacing (densest
        # staff-UA burst once keep-alive landed). Same budget as the matcher; never under
        # a test stub, never before the first URL.
        from unittest import mock
        with mock.patch.object(M.time, "sleep") as sleep:
            M._pace_between_urls(M.http_get, 0)
            M._pace_between_urls(lambda *a, **k: None, 1)
            sleep.assert_not_called()
            M._pace_between_urls(M.http_get, 1)
            sleep.assert_called_once_with(M.AKS_PROBE_DELAY_S)

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


class TransientBlankSearchSession(FakeSearchSession):
    """feed_ui=True but the rows render ``blank_reads`` reads LATE — the transient blank
    that must be polled through, not read as a real empty result on the first read."""

    def __init__(self, rows_by_field=None, *, blank_reads=1, **kw):
        super().__init__(rows_by_field, **kw)
        self._blank = blank_reads

    def page_offer_rows(self):
        if self._blank > 0:
            self._blank -= 1
            return []
        return super().page_offer_rows()


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

    def test_legacy_compare_and_buy_page(self):
        # Romain 2026-09-07: a few older products live under the compare-and-buy prefix
        # (Minecraft: compare-and-buy-cd-key-for-digital-download-minecraft/ — the modern
        # buy-…-compare-prices form 404s). Accept compare-and-buy GENERALLY (known middle
        # stripped when present), else a genuine top-popular URL is rejected "not an AKS
        # product URL".
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/compare-and-buy-cd-key-for-digital-download-minecraft/"),
            "minecraft")
        self.assertEqual(M.extract_slug(
            "https://www.allkeyshop.com/blog/compare-and-buy-some-old-game/"), "some-old-game")

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

    def test_429_is_never_retried_and_carries_status(self):
        # Review 2026-09-09: an explicit rate limit is a STOP signal for the throttle guard,
        # not a transient to retry 3× with backoff.
        calls = []

        def fake(url, timeout=8, user_agent=None):
            calls.append(url)
            return HttpProbeResult(url=url, ok=False, status=429, body="")

        with self.assertRaises(M.AksProbeUnreliable) as ctx:
            M.resolve_pinned(URL, fake)
        self.assertEqual(len(calls), 1)
        self.assertEqual(ctx.exception.status, 429)

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

    def test_transient_blank_feed_ui_up_is_polled_not_false_empty(self):
        # Romain audit 2026-09-07: feed_ui=True with rows still loading (a transient blank)
        # must NOT be read as a real empty result on the FIRST read — the confirming
        # re-read finds the rows. The prior code returned [] immediately → false empty.
        s = TransientBlankSearchSession(
            {"name": [_row("1", "Game 1", "https://m/1")]}, blank_reads=1)
        got, truncated = M._read_search_pages(s, "aks-merchant-feeds-9", "all", "term", "name")
        self.assertEqual([r["id"] for r in got], ["1"])
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

    def test_run_plan_aborts_on_aks_throttle(self):
        # Review 2026-09-09: a throttled AKS must stop the preview (aborted=aks_throttled),
        # not walk the whole URL list to a "completed" 0-résolu run.
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([URL, URL, URL], TARGETS, available="all",
                               feed_page="aks-merchant-feeds-9", endpoint="x", run_dir=Path(d),
                               http_get_fn=_status(429), session=self._session())
        self.assertEqual(recap["aborted"], "aks_throttled")
        self.assertEqual(len(recap["games"]), 1)          # stopped at the first 429
        self.assertEqual(recap["totals"]["resolved"], 0)

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


class InvariantsGateTests(unittest.TestCase):
    """[24] (Fable re-audit 2026-09-06): scripts/11 drives the shared AKS tab, so it gates
    on invariants (green + authoritative, official CDP endpoint) BEFORE opening it."""

    def test_non_green_invariants_abort_before_browser(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(M, "ROOT", Path(d)), \
                mock.patch.object(M.time, "sleep"), \
                mock.patch.object(M, "build_report",
                                  return_value={"ok": False, "authoritative": True}) as br, \
                mock.patch.object(M, "run_plan") as rp:
            rc = M.main(["--run-id", "t24", "--urls", URL,
                         "--endpoint", "http://127.0.0.1:9999/json/version"])
        self.assertEqual(rc, 2)
        br.assert_called()          # the gate ran
        rp.assert_not_called()      # the browser was never driven

    def test_green_authoritative_proceeds_to_plan(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(M, "ROOT", Path(d)), \
                mock.patch.object(M, "build_report",
                                  return_value={"ok": True, "authoritative": True}), \
                mock.patch.object(M, "run_plan",
                                  return_value={"aborted": None,
                                                "totals": {"games": 0, "resolved": 0, "candidates": 0}}) as rp:
            rc = M.main(["--run-id", "t24b", "--urls", URL,
                         "--endpoint", "http://127.0.0.1:9999/json/version"])
        self.assertEqual(rc, 0)
        rp.assert_called_once()     # gate passed → the planner ran


# ── Console pages [R45] (Romain 2026-09-15: consoles by default, page-driven entry too) ──
AKS_BLOG = "https://www.allkeyshop.com/blog/"
HADES_PC_URL = AKS_BLOG + "buy-hades-cd-key-compare-prices/"
HADES_PS5_URL = AKS_BLOG + "buy-hades-ps5-compare-prices/"
HADES_PS4_URL = AKS_BLOG + "buy-hades-ps4-compare-prices/"
HADES_ONE_URL = AKS_BLOG + "buy-hades-xbox-one-compare-prices/"
HADES_SERIES_URL = AKS_BLOG + "buy-hades-xbox-series-compare-prices/"
HADES_SWITCH_URL = AKS_BLOG + "buy-hades-nintendo-switch-compare-prices/"
HADES_PAGES = {"cd-key": (HADES_PC_URL, "26712", "Hades CD Key"),
               "ps5": (HADES_PS5_URL, "85105", "Hades PS5"),
               "ps4": (HADES_PS4_URL, "85104", "Hades PS4"),
               "xbox-one": (HADES_ONE_URL, "85102", "Hades Xbox One"),
               "xbox-series": (HADES_SERIES_URL, "85103", "Hades Xbox Series"),
               "nintendo-switch": (HADES_SWITCH_URL, "47979", "Hades Nintendo Switch")}


def _page_body(kind, *, tabs=None, platforms=""):
    """An AKS page of one platform kind: og:title, product id, editions/regions, the
    platform tab bar (the active tab is a <span>, the others link the sibling pages)."""
    url, pid, title = HADES_PAGES[kind]
    tabs = HADES_PAGES.keys() if tabs is None else tabs
    lis = "".join(
        f'<li><span class="active">{k}</span></li>' if k == kind
        else f'<li><a href="{HADES_PAGES[k][0]}" class="inactive">{k}</a></li>' for k in tabs)
    body = (f'<meta property="og:title" content="Buy {title} Compare Prices">'
            f'<ul class="aks-offer-tabulations">{lis}</ul>'
            f'<div data-product-id="{pid}"></div>'
            '<script>var x={"regions":{"2":{"filter_name":"GLOBAL"}},'
            '"editions":{"1":{"name":"Standard"}}};</script>')
    if platforms:
        body += f"<p>Official platforms: {platforms}.</p>"
    return body


def _http_by_url(bodies, calls=None):
    """A fake http_get serving ``bodies`` {url: body} (200) and 404 for anything else;
    ``calls`` collects every requested URL."""
    calls = calls if calls is not None else []

    def fake(url, timeout=8, user_agent=None):
        calls.append(url)
        body = bodies.get(url)
        if body is None:
            return HttpProbeResult(url=url, ok=False, status=404, body="")
        return HttpProbeResult(url=url, ok=True, status=200, body=body)

    fake.calls = calls
    return fake


def _hades_site(*, pa=False, tabs=None):
    """Every Hades page; ``pa`` lists Xbox Play Anywhere on the PC page."""
    return {HADES_PAGES[k][0]: _page_body(k, tabs=tabs, platforms=("Steam, Xbox Play Anywhere" if pa and k == "cd-key" else ""))
            for k in (tabs or HADES_PAGES.keys())}


class ConsoleUrlTests(unittest.TestCase):
    """Every console page kind is parsed to (slug, kind); the PC / account / legacy
    shapes keep their reading; extract_slug is unchanged for callers."""

    def test_every_console_kind(self):
        for kind in ("ps4", "ps5", "xbox-one", "xbox-series", "nintendo-switch", "nintendo-switch-2"):
            ref = M.parse_page_url(f"{AKS_BLOG}buy-street-fighter-6-{kind}-compare-prices/?utm=1")
            self.assertEqual((ref.slug, ref.kind), ("street-fighter-6", kind), kind)
            self.assertTrue(ref.console)
            self.assertEqual(M.extract_slug(f"{AKS_BLOG}buy-street-fighter-6-{kind}-compare-prices/"),
                             "street-fighter-6")
        self.assertEqual(M.CONSOLE_URL_KINDS,
                         ("ps4", "ps5", "xbox-one", "xbox-series", "nintendo-switch", "nintendo-switch-2"))

    def test_switch_2_is_not_switch_plus_a_slug_tail(self):
        ref = M.parse_page_url(AKS_BLOG + "buy-hades-nintendo-switch-2-compare-prices/")
        self.assertEqual((ref.slug, ref.kind), ("hades", "nintendo-switch-2"))

    def test_pc_account_legacy_kinds(self):
        self.assertEqual(M.parse_page_url(URL), M.PageRef("neon-beats", "cd-key"))
        self.assertFalse(M.parse_page_url(URL).console)
        self.assertEqual(M.parse_page_url(AKS_BLOG + "buy-the-green-light-key-compare-prices/"),
                         M.PageRef("the-green-light", "cd-key"))
        self.assertEqual(M.parse_page_url(AKS_BLOG + "buy-007-first-light-ps5-account-compare-prices/"),
                         M.PageRef("007-first-light", "account"))
        self.assertEqual(M.parse_page_url(AKS_BLOG + "compare-and-buy-cd-key-for-digital-download-minecraft/"),
                         M.PageRef("minecraft", "cd-key"))

    def test_kind_word_inside_a_pc_slug_stays_pc(self):
        # the KEY alternative wins first: a PC slug containing "ps4" is the PC page …
        self.assertEqual(M.parse_page_url(AKS_BLOG + "buy-some-ps4-emulator-cd-key-compare-prices/"),
                         M.PageRef("some-ps4-emulator", "cd-key"))
        # … and a console slug containing "key" is still the console page.
        self.assertEqual(M.parse_page_url(AKS_BLOG + "buy-the-key-ps5-compare-prices/"),
                         M.PageRef("the-key", "ps5"))

    def test_wrong_host_and_non_product(self):
        self.assertIsNone(M.parse_page_url("https://evil.com/blog/buy-hades-ps5-compare-prices/"))
        self.assertIsNone(M.parse_page_url(AKS_BLOG + "some-article/"))
        self.assertEqual(M.page_kind_of("https://aks/x"), "cd-key")     # synthetic → PC reading
        self.assertEqual(M.page_kind_of(HADES_SERIES_URL), "xbox-series")


class ConsolePageRefusalTests(unittest.TestCase):
    """--no-consoles: a console page URL is refused BEFORE any fetch, per-URL, with an
    explicit message; nothing is done for it."""

    def test_resolve_pinned_refuses_without_a_fetch(self):
        http = _http_by_url(_hades_site())
        with self.assertRaises(M.ConsolePageRefused) as ctx:
            M.resolve_pinned(HADES_PS5_URL, http, consoles=False)
        self.assertIn("--consoles", str(ctx.exception))
        self.assertIn("ps5", str(ctx.exception))
        self.assertEqual(http.calls, [])                          # nothing fetched

    def test_resolve_pinned_reads_a_console_page_like_the_pc_page(self):
        res = M.resolve_pinned(HADES_PS5_URL, _http_by_url(_hades_site()))
        self.assertEqual((res.slug, res.product_id, res.aks_name), ("hades", "85105", "Hades PS5"))
        self.assertEqual(res.official_platforms, ())              # no such line on a console page — fine
        self.assertEqual(res.console_pages["cd-key"], HADES_PC_URL)
        self.assertEqual(res.console_pages["ps4"], HADES_PS4_URL)

    def test_run_plan_reports_the_refusal_per_url_and_does_the_pc_urls(self):
        http = _http_by_url({**_hades_site(), URL: AKS_BODY})
        session = FakeSearchSession({"name": [_row("100", "Neon Beats - Steam Key - GLOBAL",
                                                   "https://testmart.com/neon-beats", store="999")]})
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([HADES_PS5_URL, URL], TARGETS, available="all",
                               feed_page="aks-merchant-feeds-9", endpoint="x", run_dir=Path(d),
                               http_get_fn=http, session=session, consoles=False)
        self.assertFalse(recap["consoles"])
        self.assertIsNone(recap["aborted"])
        refused, done = recap["games"]
        self.assertFalse(refused["resolved"])
        self.assertIn("ConsolePageRefused", refused["reason"])
        self.assertNotIn(HADES_PS5_URL, http.calls)               # never fetched
        self.assertTrue(done["resolved"])
        self.assertEqual(recap["totals"]["candidates"], 1)        # the PC URL still ran


class ConsoleSearchTermTests(unittest.TestCase):
    def test_console_page_searches_the_identity_name_not_the_platform_suffix(self):
        res = M.resolve_pinned(HADES_SERIES_URL, _http_by_url(_hades_site()))
        self.assertEqual(res.aks_name, "Hades Xbox Series")
        session = FakeSearchSession({"name": [], "url": []})
        _rows, meta = M.search_all_merchants(session, res, "all", "aks-merchant-feeds-9")
        self.assertEqual(meta["name_term"], "Hades")
        self.assertEqual(meta["url_term"], "hades")
        self.assertEqual(meta["page_kind"], "xbox-series")
        terms = [_up.parse_qs(_up.urlsplit(u).query)["search[search]"][0] for u in session.nav]
        self.assertEqual(terms, ["Hades", "hades"])
        self.assertFalse(any("Series" in t or "Xbox" in t for t in terms))

    def test_pc_page_term_unchanged(self):
        _rows, meta = M.search_all_merchants(FakeSearchSession({}), PAGE, "all", "aks-merchant-feeds-9")
        self.assertEqual((meta["name_term"], meta["page_kind"]), ("Neon Beats", "cd-key"))


class PinnedPageTests(unittest.TestCase):
    """The matcher's page protocol on a pinned page: own kind from memory; a PC or
    account page answers the plain PC request; other kinds via the tab bar, cached."""

    def _pinned(self, kind, tabs=None):
        site = _hades_site(tabs=tabs)
        res = M.resolve_pinned(HADES_PAGES[kind][0], _http_by_url(site))
        reads = []

        def page_resolver(url):
            reads.append(url)
            return M.resolve_aks_url(url, _http_by_url(site))

        return M.PinnedPage(res, kind, page_resolver), reads

    def test_console_pin_answers_own_kind_and_hops_the_tab_bar_for_the_rest(self):
        pinned, reads = self._pinned("ps5")
        self.assertIs(pinned("Hades", page_kind="ps5"), pinned.resolution)      # own kind, no read
        pc = pinned("Hades")                                                     # the PC request
        self.assertEqual(pc.product_id, "26712")
        self.assertEqual(reads, [HADES_PC_URL])
        self.assertIs(pinned("Hades"), pc)                                        # cached
        self.assertEqual(reads, [HADES_PC_URL])
        ps4 = pinned("Hades", page_kind="ps4")
        self.assertEqual(ps4.product_id, "85104")
        self.assertEqual(reads, [HADES_PC_URL, HADES_PS4_URL])
        self.assertIs(pinned.page(HADES_PS5_URL.rstrip("/") + "?x=1"), pinned.resolution)  # itself, no read
        self.assertEqual(reads, [HADES_PC_URL, HADES_PS4_URL])

    def test_no_tab_is_none_never_a_guess(self):
        pinned, reads = self._pinned("nintendo-switch", tabs=("nintendo-switch",))   # console-only game
        self.assertIsNone(pinned("Hades"))                                        # no PC tab
        self.assertIsNone(pinned("Hades", page_kind="ps5"))
        self.assertEqual(reads, [])

    def test_pc_pin_answers_the_pc_request_from_memory(self):
        pinned, reads = self._pinned("cd-key")
        self.assertIs(pinned("anything"), pinned.resolution)
        self.assertIs(pinned("anything", page_kind="cd-key", search=False), pinned.resolution)
        self.assertEqual(reads, [])

    def test_account_pin_keeps_the_historical_pc_answer(self):
        res = AksResolution(slug="fortnite", url=AKS_BLOG + "buy-fortnite-steam-account-compare-prices/",
                            product_id="1", aks_name="Fortnite Steam Account", editions={"1": "Standard"})
        pinned = M.PinnedPage(res, "account", lambda url: None)
        self.assertIs(pinned("Fortnite"), res)

    def test_a_probe_error_is_never_cached(self):
        res = M.resolve_pinned(HADES_PS5_URL, _http_by_url(_hades_site()))
        n = {"calls": 0}

        def boom(url):
            n["calls"] += 1
            raise M.AksProbeUnreliable("503", status=503, slug="hades")
        pinned = M.PinnedPage(res, "ps5", boom)
        for _ in range(2):
            with self.assertRaises(M.AksProbeUnreliable):
                pinned("Hades")
        self.assertEqual(n["calls"], 2)


class ConsoleQualificationTests(unittest.TestCase):
    """A candidate qualifies for the requested page iff ANY of its targets is that
    page; multi-target candidates are kept WHOLE (all their pages)."""

    def _plan(self, page_url, rows, *, pa=False, tabs=None, consoles=True):
        site = _hades_site(pa=pa, tabs=tabs)
        http = _http_by_url(site)
        res = M.resolve_pinned(page_url, http)
        page_resolver = lambda url: M.resolve_aks_url(url, http)  # noqa: E731
        return M.plan_from_rows([_row(str(i), name, f"https://testmart.com/hades-{i}")
                                 for i, name in enumerate(rows, 1)],
                                res, "TestMart", "999", consoles=consoles, page_resolver=page_resolver)

    def test_cross_gen_key_from_a_console_page_targets_all_its_pages(self):
        per = self._plan(HADES_PS5_URL, ["Hades (PS4 / PS5)"])
        self.assertEqual(per["skipped"], [])
        (cand,) = per["candidates"]
        pids = [t["aks_product_id"] for t in cand["targets"]]
        self.assertEqual(sorted(pids), ["85104", "85105"])       # PS4 + PS5 — never split
        self.assertIn("85105", pids)                              # the requested page is one of them
        self.assertEqual({t["platform"] for t in cand["targets"]}, {"PS4", "PS5"})
        self.assertIn("|+", cand["fingerprint"])                  # extended fingerprint (R45)

    def test_lone_other_platform_key_is_not_entered_from_this_page(self):
        per = self._plan(HADES_PS5_URL, ["Hades PS4"])
        self.assertEqual(per["candidates"], [])
        (sk,) = per["skipped"]
        self.assertIn("not on the requested page 85105", sk["reason"])
        self.assertIn("PS4 85104", sk["reason"])

    def test_xbox_cross_gen_from_the_series_page(self):
        per = self._plan(HADES_SERIES_URL, ["Hades (Xbox One / Series X|S)"])
        (cand,) = per["candidates"]
        self.assertEqual(sorted(t["aks_product_id"] for t in cand["targets"]), ["85102", "85103"])
        self.assertEqual({t["region"]["id"] for t in cand["targets"]}, {"24", "300"})   # Xbox buckets, no PA

    def test_pc_page_keeps_pc_rows_and_qualifies_play_anywhere_console_rows(self):
        per = self._plan(HADES_PC_URL, ["Hades - Steam Key - GLOBAL",
                                        "Hades (Xbox One / Series X|S / PC)",
                                        "Hades PS5"], pa=True)
        names = {c["offer"]["name"]: c for c in per["candidates"]}
        self.assertEqual(set(names), {"Hades - Steam Key - GLOBAL", "Hades (Xbox One / Series X|S / PC)"})
        pc = names["Hades - Steam Key - GLOBAL"]
        self.assertEqual([t["aks_product_id"] for t in pc["targets"]], ["26712"])       # as before
        pa = names["Hades (Xbox One / Series X|S / PC)"]
        self.assertEqual(sorted(t["aks_product_id"] for t in pa["targets"]), ["26712", "85102", "85103"])
        self.assertEqual({t["region"]["id"] for t in pa["targets"]}, {"306"})           # XBOX/PC GLOBAL
        (sk,) = per["skipped"]                                    # the PS5 key targets the PS5 page only
        self.assertEqual(sk["name"], "Hades PS5")
        self.assertIn("not on the requested page 26712", sk["reason"])

    def test_console_only_game_anchors_on_the_pinned_console_page(self):
        per = self._plan(HADES_SWITCH_URL, ["Hades Nintendo Switch"], tabs=("nintendo-switch",))
        (cand,) = per["candidates"]
        self.assertEqual(cand["aks_product_id"], "47979")
        self.assertEqual([t["aks_product_id"] for t in cand["targets"]], ["47979"])
        self.assertEqual(cand["region"]["id"], "99")

    def test_no_consoles_keeps_the_historical_console_skip(self):
        per = self._plan(HADES_PC_URL, ["Hades (PS4 / PS5)"], consoles=False)
        self.assertEqual(per["candidates"], [])
        self.assertEqual(per["skipped"][0]["reason"], "console")

    def test_pc_regression_default_consoles_true(self):
        rows = [_row("100", "Neon Beats - Steam Key - GLOBAL", "https://testmart.com/neon-beats-global")]
        per = M.plan_from_rows(rows, PAGE, "TestMart", "999")
        self.assertEqual(per["candidates"][0]["aks_product_id"], "205027")


class ConsoleRunPlanTests(unittest.TestCase):
    def _session(self):
        return FakeSearchSession({
            "name": [_row("100", "Hades (PS4 / PS5)", "https://testmart.com/hades-ps", store="999"),
                     _row("101", "Hades PS4", "https://testmart.com/hades-ps4", store="999")]})

    def test_end_to_end_console_page_recap_and_report(self):
        http = _http_by_url(_hades_site())
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            recap = M.run_plan([HADES_PS5_URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9",
                               endpoint="x", run_dir=run_dir, http_get_fn=http, session=self._session())
            self.assertIsNone(recap["aborted"])
            self.assertTrue(recap["consoles"])
            g = recap["games"][0]
            self.assertEqual((g["page_kind"], g["aks_product_id"], g["aks_name"]), ("ps5", "85105", "Hades PS5"))
            self.assertEqual(g["search"]["name_term"], "Hades")
            self.assertEqual(recap["totals"]["candidates"], 1)
            (per,) = g["merchants"]
            self.assertEqual(len(per["candidates"][0]["targets"]), 2)
            self.assertIn("not on the requested page", per["skipped"][0]["reason"])
            # the sibling pages were read ONCE each (cache), the pinned page never re-read
            self.assertEqual(http.calls.count(HADES_PC_URL), 1)
            self.assertEqual(http.calls.count(HADES_PS4_URL), 1)
            self.assertEqual(http.calls.count(HADES_PS5_URL), 1)
            M.write_report(recap, run_dir)
            report = (run_dir / "report.txt").read_text()
        self.assertIn("[page ps5]", report)
        self.assertIn("↳ PS5 85105 — Hades PS5", report)
        self.assertIn("écrite sur toutes ses pages déclarées", report)

    def test_429_during_a_target_page_read_aborts_the_run(self):
        # a 429 on a console target page STOPS the preview (aborted=aks_throttled) —
        # never a per-row "error:" skip that plows on.
        def page_boom(url):
            raise M.AksProbeUnreliable(f"{url} -> 429", status=429, slug="hades")
        with tempfile.TemporaryDirectory() as d:
            recap = M.run_plan([HADES_PS5_URL], TARGETS, available="all", feed_page="aks-merchant-feeds-9",
                               endpoint="x", run_dir=Path(d), http_get_fn=_http_by_url(_hades_site()),
                               session=self._session(), page_resolver=page_boom)
        self.assertEqual(recap["aborted"], "aks_throttled")
        self.assertEqual(recap["games"][0]["error"], "aks_throttled")
        self.assertEqual(recap["totals"]["candidates"], 0)


class ConsoleFlagTests(unittest.TestCase):
    def test_flags(self):
        p = M.build_parser()
        self.assertTrue(p.parse_args(["--run-id", "x"]).consoles)                 # default ON
        self.assertTrue(p.parse_args(["--run-id", "x", "--consoles"]).consoles)
        self.assertFalse(p.parse_args(["--run-id", "x", "--no-consoles"]).consoles)

    def test_main_threads_no_consoles_to_run_plan(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(M, "ROOT", Path(d)), \
                mock.patch.object(M, "build_report", return_value={"ok": True, "authoritative": True}), \
                mock.patch.object(M, "run_plan",
                                  return_value={"aborted": None,
                                                "totals": {"games": 0, "resolved": 0, "candidates": 0}}) as rp:
            rc = M.main(["--run-id", "t45", "--urls", HADES_PS5_URL, "--no-consoles",
                         "--endpoint", "http://127.0.0.1:9999/json/version"])
            self.assertEqual(rc, 0)
            self.assertFalse(rp.call_args.kwargs["consoles"])
            rc = M.main(["--run-id", "t45b", "--urls", HADES_PS5_URL,
                         "--endpoint", "http://127.0.0.1:9999/json/version"])
            self.assertEqual(rc, 0)
            self.assertTrue(rp.call_args.kwargs["consoles"])


if __name__ == "__main__":
    unittest.main()
