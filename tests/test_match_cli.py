"""CLI seam for scripts/03_match.py (review 2026-09-09): the fail-closed throttle abort
(exit 2, `aborted: aks_throttled`, match_aborted.json sidecar, NOTHING else written) and the
match_meta.probe_unreliable count are stage-boundary contracts the sweep relies on."""
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.aks_env import HttpProbeResult
from src.contracts import NormalizedOffer
from src.matcher import AksThrottled, SkippedOffer


def _load():
    spec = importlib.util.spec_from_file_location(
        "m03_cli", str(Path(__file__).resolve().parents[1] / "scripts" / "03_match.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MatchCliTests(unittest.TestCase):
    def setUp(self):
        self.MOD = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.MOD.ROOT = self.root                       # logs/ go under the temp tree
        self.run = self.root / "runs" / "r1"
        self.run.mkdir(parents=True)
        (self.run / "offers.json").write_text(json.dumps({
            "run_id": "r1", "merchant": "Test", "fetched_at": "t",
            "offers": [{"offer_id": "1", "name": "Neon Beats - Steam GLOBAL",
                        "url": "https://testmart.com/x", "merchant": "Test", "store_id": "999"}],
        }))
        gate_ok = HttpProbeResult(url="u", ok=True, status=200, body="x")
        p = mock.patch.object(self.MOD, "http_get", return_value=gate_ok)
        p.start(); self.addCleanup(p.stop)

    def _main(self):
        with mock.patch.object(sys, "argv", ["03_match.py", str(self.run / "offers.json")]):
            return self.MOD.main()

    def test_throttle_abort_exits_2_writes_only_the_sidecar(self):
        with mock.patch.object(self.MOD, "match_feed", side_effect=AksThrottled("AKS answered 429")):
            rc = self._main()
        self.assertEqual(rc, 2)
        self.assertFalse((self.run / "candidates.json").exists())
        self.assertFalse((self.run / "skipped.json").exists())
        self.assertFalse((self.run / "match_meta.json").exists())
        sidecar = json.loads((self.run / "match_aborted.json").read_text())
        self.assertEqual(sidecar["reason"], "aks_throttled")
        self.assertIn("429", sidecar["detail"])

    def test_clean_match_counts_unreliable_and_clears_a_stale_sidecar(self):
        (self.run / "match_aborted.json").write_text("{}")
        offer = NormalizedOffer(offer_id="1", name="n", url="u", merchant="Test", store_id="999",
                                price=None, stock=None)
        skipped = [SkippedOffer(offer, "AKS probe unreliable (throttled?): x -> 503"),
                   SkippedOffer(offer, "name mismatch, missing AKS words: ['X']")]
        with mock.patch.object(self.MOD, "match_feed", return_value=([], skipped)):
            rc = self._main()
        self.assertEqual(rc, 0)
        self.assertFalse((self.run / "match_aborted.json").exists())
        meta = json.loads((self.run / "match_meta.json").read_text())
        self.assertEqual(meta["probe_unreliable"], 1)
        for key in ("search_failures", "search_circuit_open_offers", "throttle_graces"):
            self.assertEqual(meta[key], 0)        # counters present even when match_feed is mocked
        self.assertEqual(len(json.loads((self.run / "skipped.json").read_text())), 2)

    def test_sitemap_first_counters_are_stamped_and_start_from_zero(self):
        """2026-09-24 : ce que le mode « sitemap d'abord » a évité, page par page. Les
        compteurs repartent de zéro à chaque page — un reste de la page d'avant mentirait."""

        import src.matcher as M
        from src.aks_sitemap import SitemapIndex
        M.SITEMAP_FIRST_STATS["probes_skipped"] = 999          # reste d'un autre match

        def faux_match(*a, **k):
            M.SITEMAP_FIRST_STATS["probes_skipped"] += 7
            M.SITEMAP_FIRST_STATS["valve_unconfirmed"] += 2
            return [], []

        idx = SitemapIndex(entries=frozenset({"a-cd-key"}), fetched_at="2026-09-24T00:00:00Z",
                           incomplete=False, legacy=frozenset({"far-cry-3"}),
                           legacy_indexed=True)
        with mock.patch.object(self.MOD, "match_feed", side_effect=faux_match), \
                mock.patch.object(self.MOD, "sitemap_index", return_value=idx):
            self.assertEqual(self._main(), 0)
        meta = json.loads((self.run / "match_meta.json").read_text())["sitemap_first"]
        self.assertEqual(meta, {"active": True, "fetched_at": "2026-09-24T00:00:00Z",
                                "legacy_indexed": True, "probes_skipped": 7,
                                "valve_unconfirmed": 2})
        M.reset_sitemap_first_stats()


if __name__ == "__main__":
    unittest.main()


class SearchCircuitFileTests(MatchCliTests):
    """Sweep-scoped R30 breaker persistence (Romain GO 2026-09-10)."""

    def _circuit(self, **fields):
        path = self.root / "search_circuit.json"
        path.write_text(json.dumps(fields))
        return path

    def _main_with(self, path, match_feed_stub):
        with mock.patch.object(self.MOD, "match_feed", side_effect=match_feed_stub), \
                mock.patch.object(sys, "argv", ["03_match.py", str(self.run / "offers.json"),
                                                "--search-circuit-file", str(path)]):
            return self.MOD.main()

    def test_open_file_preopens_the_circuit_and_stays_open(self):
        path = self._circuit(open=True, written_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        before = path.read_text()
        seen = {}

        def stub(feed, resolver, **kw):
            seen.update(kw); kw["stats"].update({"search_circuit_open_offers": 4, "search_failures": 0}); return ([], [])
        self.assertEqual(self._main_with(path, stub), 0)
        self.assertTrue(seen["search_circuit_open"])
        self.assertEqual(path.read_text(), before)                        # left in place, untouched

    def test_an_old_file_no_longer_preopens(self):
        """De portée balayage, mais PLUS éternel (2026-09-20, `SEARCH_CIRCUIT_TTL_S`) : un
        marqueur écrit il y a plus de 30 min laisse la page suivante re-sonder la recherche.

        Le balayage 20260919-082932 avait ouvert le disjoncteur 66 secondes après son
        démarrage — 7 h avant que GameSeal ne commence — et ses 60 pages ont résolu au slug
        seul : 434 offres distinctes refusées « no AKS product page found »."""

        path = self._circuit(open=True, written_at="2026-09-10T01:00:00Z")
        seen = {}

        def stub(feed, resolver, **kw):
            seen.update(kw); kw["stats"].update({"search_failures": 0}); return ([], [])
        self.assertEqual(self._main_with(path, stub), 0)
        self.assertFalse(seen["search_circuit_open"])       # la recherche est re-sondée
        self.assertFalse(path.exists())                     # elle a marché → marqueur effacé

    def test_an_expired_marker_is_re_armed_when_the_search_fails_again(self):
        path = self._circuit(open=True, written_at="2026-09-10T01:00:00Z")

        def stub(feed, resolver, **kw):
            kw["stats"].update({"search_failures": 3, "search_circuit_open_offers": 2}); return ([], [])
        self.assertEqual(self._main_with(path, stub), 0)
        import json as _json
        self.assertTrue(_json.loads(path.read_text())["open"])

    def test_closed_or_garbage_file_does_not_preopen(self):
        for body in ('{"open": false}', "not json", "[1, 2]", ""):
            path = self.root / "search_circuit.json"; path.write_text(body)
            seen = {}

            def stub(feed, resolver, **kw):
                seen.update(kw); return ([], [])
            self.assertEqual(self._main_with(path, stub), 0, body)
            self.assertFalse(seen["search_circuit_open"], body)
            self.assertFalse(path.exists(), body)                          # search worked → cleared

    def test_a_tripped_run_writes_the_file(self):
        path = self.root / "search_circuit.json"

        def stub(feed, resolver, **kw):
            kw["stats"].update({"search_failures": 3, "search_circuit_open_offers": 10}); return ([], [])
        self.assertEqual(self._main_with(path, stub), 0)
        data = json.loads(path.read_text())
        self.assertTrue(data["open"]); self.assertNotIn("open_until", data)
        self.assertEqual(data["search_failures"], 3)


class ConsolesFlagTests(MatchCliTests):
    """[R45] --consoles reaches match_feed and is stamped into match_meta. Since Romain's
    decision « 1 » of 2026-09-15 the console branch is the DEFAULT (an explicit --consoles is
    a kept no-op) and --no-consoles is the PC-only opt-out."""

    def _main_flags(self, flags, stub):
        with mock.patch.object(self.MOD, "match_feed", side_effect=stub), \
                mock.patch.object(sys, "argv", ["03_match.py", str(self.run / "offers.json")] + flags):
            return self.MOD.main()

    def test_consoles_flag_is_passed_and_stamped(self):
        seen = {}

        def stub(feed, resolver, **kw):
            seen.update(kw); return ([], [])
        self.assertEqual(self._main_flags(["--consoles"], stub), 0)
        self.assertTrue(seen["consoles"])
        meta = json.loads((self.run / "match_meta.json").read_text())
        self.assertIs(meta["consoles"], True)

    def test_consoles_on_by_default(self):
        # Romain's decision « 1 » (2026-09-15): no flag = the console branch, stamped true.
        seen = {}

        def stub(feed, resolver, **kw):
            seen.update(kw); return ([], [])
        self.assertEqual(self._main_flags([], stub), 0)
        self.assertIs(seen["consoles"], True)
        meta = json.loads((self.run / "match_meta.json").read_text())
        self.assertIs(meta["consoles"], True)

    def test_no_consoles_opts_out(self):
        # --no-consoles = the pre-2026-09-15 PC-only match: console rows keep the 'console'
        # skip (match_feed(consoles=False)) and the stamp says false.
        seen = {}

        def stub(feed, resolver, **kw):
            seen.update(kw); return ([], [])
        self.assertEqual(self._main_flags(["--no-consoles"], stub), 0)
        self.assertIs(seen["consoles"], False)
        meta = json.loads((self.run / "match_meta.json").read_text())
        self.assertIs(meta["consoles"], False)
