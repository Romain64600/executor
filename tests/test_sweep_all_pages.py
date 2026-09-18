"""Le sweep couvre TOUTES les pages, sauf arrêt de sécurité (2026-09-18).

Romain, au vu du bilan de la nuit : « je ne veux pas couvrir les marchands seulement sur
10 pages, on fait toutes les pages sauf lors d'un arrêt pour sécurité ». Le plafond de 10 avait
laissé de côté 97 pages chez GameSeal (107 au total), 54 chez Kinguin, 42 chez Gamivo, 36 chez
Eneba et 23 chez G2A — signalées honnêtement en ``coverage_incomplete``, mais laissées.

``max_pages=None`` fait descendre la passe jusqu'à la page 1 depuis la dernière page que le
feed ANNONCE. Ce qui écourte alors une passe ne peut plus être un plafond : seulement un arrêt
fail-closed (extract / match / submit en échec) ou le stop opérateur. La croissance du feed en
cours de passe reste signalée comme avant (``incomplete_feed_grew``) — un plafond retiré n'est
pas une promesse de tout voir, c'est la fin d'une troncature silencieuse.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_entry_auto import SweepConfig, run_sweep


class _Stages:
    """Un feed de N pages, toutes extractibles, aucun candidat : on mesure la COUVERTURE."""

    def __init__(self, feed_last, fail_on=None):
        self.feed_last = feed_last
        self.fail_on = fail_on
        self.seen = []

    class _R:
        """Stub permissif : ce test mesure la COUVERTURE, pas le contenu d'une étape.
        Tout champ non fixé vaut une valeur neutre, pour ne pas réécrire ce bouchon à
        chaque champ ajouté à une étape."""

        def __init__(self, **kw):
            self.__dict__.update(kw)

        def __getattr__(self, name):
            return None

    def probe(self, page, run_id):
        return self._R(ok=True, offers=100, feed_last_page=self.feed_last, detail=None)

    def extract(self, page, run_id):
        self.seen.append(page)
        if self.fail_on is not None and page == self.fail_on:
            return self._R(ok=False, offers=0, feed_last_page=self.feed_last,
                           detail="extract: exit 1")
        return self._R(ok=True, offers=100, feed_last_page=self.feed_last, detail=None)

    def match(self, run_id):
        return self._R(ok=True, candidates=0, movable=0, detail=None)

    def approve(self, run_id):
        return self._R(ok=True, approved=0, detail=None)

    def submit(self, run_id, page):
        return self._R(ok=True, created=0, detail=None, offers_created=[])

    def move(self, *a, **k):
        return self._R(ok=True, moved=0, detail=None)

    def __getattr__(self, name):
        """Toute étape non implémentée répond « rien fait, tout va bien » : ce test ne
        mesure que la couverture en pages."""

        def _noop(*a, **k):
            return _Stages._R(ok=True, detail=None)
        return _noop


def _sweep(feed_last, max_pages, fail_on=None):
    """Renvoie (recap, pages du BALAYAGE). La sonde initiale extrait la page de départ pour
    lire le nombre de pages annoncé : elle précède le balayage et n'en fait pas partie."""

    stages = _Stages(feed_last, fail_on=fail_on)
    cfg = SweepConfig(merchant="M", store_id="1", start_page=1, max_pages=max_pages)
    recap = run_sweep(cfg, stages, page_run_id=lambda p: f"r-p{p}", should_stop=lambda: False)
    return recap, stages.seen[1:]


class AllPagesCoversTheWholeFeedTests(unittest.TestCase):
    def test_none_walks_every_advertised_page(self):
        recap, seen = _sweep(feed_last=107, max_pages=None)
        self.assertEqual(seen, list(range(107, 0, -1)),
                         "de la dernière page annoncée jusqu'à la page 1, plus haute d'abord")
        self.assertIsNone(recap.get("coverage"),
                          "sans plafond, plus de troncature à signaler")

    def test_a_cap_still_truncates_and_says_so(self):
        recap, seen = _sweep(feed_last=107, max_pages=10)
        self.assertEqual(seen, list(range(10, 0, -1)))
        self.assertIn("incomplete_max_pages", str(recap.get("coverage")))
        self.assertIn("107", str(recap.get("coverage")), "le compte réel est nommé")

    def test_the_default_is_unchanged_for_callers_that_pass_nothing(self):
        self.assertEqual(SweepConfig(merchant="M", store_id="1").max_pages, 30)


class OnlyASafetyHaltShortensTheRunTests(unittest.TestCase):
    """« sauf lors d'un arrêt pour sécurité » — c'est la SEULE chose qui écourte."""

    def test_a_failed_extract_halts_and_names_the_page(self):
        recap, seen = _sweep(feed_last=20, max_pages=None, fail_on=14)
        self.assertEqual(recap["halted"], "extract_failed_p14")
        self.assertEqual(seen, [20, 19, 18, 17, 16, 15, 14],
                         "la passe s'arrête à la page fautive, elle ne saute pas par-dessus")

    def test_without_a_halt_nothing_stops_it_early(self):
        recap, seen = _sweep(feed_last=45, max_pages=None)
        self.assertIsNone(recap["halted"])
        self.assertEqual(len(seen), 45)


class TheCliRefusesAnAmbiguousRequestTests(unittest.TestCase):
    def test_all_pages_and_max_pages_are_exclusive(self):
        src = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")
        self.assertIn('"--all-pages", action="store_true"', src)
        self.assertIn("--all-pages et --max-pages sont exclusifs", src)
        self.assertIn("max_pages=(None if args.all_pages else args.max_pages)", src)

    def test_the_readme_night_sweep_uses_it(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        block = readme[readme.index("The real night sweep"):]
        block = block[:block.index("```", block.index("```") + 3)]
        self.assertIn("--all-pages", block)
        self.assertNotIn("--max-pages 10", block,
                         "le plafond de 10 laissait 97 pages de GameSeal de côté")


if __name__ == "__main__":
    unittest.main()
