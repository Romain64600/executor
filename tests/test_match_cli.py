"""CLI seam for scripts/03_match.py (review 2026-09-09): the fail-closed throttle abort
(exit 2, `aborted: aks_throttled`, match_aborted.json sidecar, NOTHING else written) and the
match_meta.probe_unreliable count are stage-boundary contracts the sweep relies on."""
import importlib.util
import json
import sys
import tempfile
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
        self.assertEqual(len(json.loads((self.run / "skipped.json").read_text())), 2)


if __name__ == "__main__":
    unittest.main()
