"""Une page déjà entièrement vue n'est ni matchée ni saisie une seconde fois (2026-09-24).

Romain : « go pour sauter les pages vides ». Le balayage Wyrel du 24/09 a lu cinq fois les
mêmes cent offres (pages 45 → 41) et retenté « Conclave », qu'AKS refuse à chaque fois, sur les
pages 44, 43, 42 et 41. Mesuré le même jour : Kinguin 44 pages sur 120 entièrement déjà vues,
GameSeal 51 sur 208 — chacune coûtait un matching complet (~2 min) pour rien.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_entry_auto import (  # noqa: E402
    ExtractOutcome, MatchOutcome, Stages, SubmitOutcome, SweepConfig, run_sweep,
)


class _Suivi:
    """Des étapes bouchonnées qui NOTENT ce qu'on leur demande."""

    def __init__(self, ids_par_page, candidats=1, mesure=True, mouvements=0):
        self.ids = ids_par_page
        self.candidats = candidats
        self.mesure = mesure
        self.mouvements = mouvements
        self.matchs, self.saisies, self.deplacements = [], [], []

    def page(self, run_id):
        return int(run_id.rsplit("p", 1)[1])

    def stages(self):
        def extract(page, run_id):
            return ExtractOutcome(ok=True, offers=len(self.ids[page]), feed_last_page=max(self.ids))

        def match(run_id):
            self.matchs.append(self.page(run_id))
            return MatchOutcome(ok=True, candidates=self.candidats, movable=self.mouvements)

        def submit(run_id):
            self.saisies.append(self.page(run_id))
            return SubmitOutcome(ok=True, created=0)

        def move(run_id):
            from src.data_entry_auto import MoveOutcome
            self.deplacements.append(self.page(run_id))
            return MoveOutcome(ok=True, moved=0)

        return Stages(
            extract=extract, match=match, approve=lambda run_id: self.candidats, submit=submit,
            move=move if self.mouvements else None,
            offer_ids=(lambda run_id: tuple(self.ids[self.page(run_id)])) if self.mesure else None,
        )


def _balayer(suivi):
    cfg = SweepConfig(merchant="Wyrel", store_id="162", max_pages=None)
    return run_sweep(cfg, suivi.stages(), page_run_id=lambda p: f"r-p{p}")


class UnePageDejaVueNestPasRejouee(unittest.TestCase):
    def test_la_page_repetee_nest_ni_matchee_ni_saisie(self):
        memes = ["conclave", "b", "c"]
        suivi = _Suivi({1: ["x"], 2: memes, 3: memes, 4: memes})
        recap = _balayer(suivi)
        self.assertEqual(suivi.matchs, [4, 1], "seules les pages qui apportent du neuf sont matchées")
        self.assertEqual(suivi.saisies, [4, 1], "« Conclave » ne doit être tentée qu'une fois")
        sautees = [p["page"] for p in recap["pages"] if p.get("skipped_repeated")]
        self.assertEqual(sautees, [3, 2])
        self.assertIsNone(recap["halted"], "sauter une page n'est pas une halte")

    def test_le_recap_le_dit_et_garde_la_couverture_honnete(self):
        memes = ["a", "b"]
        recap = _balayer(_Suivi({1: memes, 2: memes, 3: memes}))
        page2 = next(p for p in recap["pages"] if p["page"] == 2)
        self.assertEqual((page2["candidates"], page2["created"]), (0, 0))
        self.assertEqual(recap["pages_without_new_offers"], [2, 1])
        self.assertIn("incomplete_repeated_pages", recap["coverage"])

    def test_une_page_partiellement_neuve_est_traitee_comme_avant(self):
        suivi = _Suivi({1: ["a", "b", "NOUVELLE"], 2: ["a", "b"]})
        _balayer(suivi)
        self.assertEqual(suivi.matchs, [2, 1], "une seule offre nouvelle suffit à rejouer la page")

    def test_sans_mesure_rien_nest_saute(self):
        """`offer_ids` absent : on ne SAIT pas que la page est déjà vue — on la traite."""

        memes = ["a", "b"]
        suivi = _Suivi({1: memes, 2: memes, 3: memes}, mesure=False)
        recap = _balayer(suivi)
        self.assertEqual(suivi.matchs, [3, 2, 1])
        self.assertFalse(any(p.get("skipped_repeated") for p in recap["pages"]))

    def test_le_deplacement_vers_les_listes_est_saute_aussi(self):
        memes = ["a", "b"]
        suivi = _Suivi({1: memes, 2: memes}, candidats=0, mouvements=2)
        _balayer(suivi)
        self.assertEqual(suivi.deplacements, [2], "les refus routables ont été déplacés au 1er passage")


if __name__ == "__main__":
    unittest.main()
