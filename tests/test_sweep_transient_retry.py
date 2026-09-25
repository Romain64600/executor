"""Reprise automatique d'une page après une erreur PASSAGÈRE (2026-09-24).

Romain : « pour Wyrel j'ai dû relancer 3 fois, tu vois pas le pb ? », puis « go pour les deux
correctifs ». Les trois arrêts du 24/09 étaient passagers et sans écriture en jeu : une page du
feed muette 20 s pendant l'extraction (`CdpTimeoutError`, deux fois) et AKS qui refuse la
connexion avant tout clic sur « Create » (`net::ERR_CONNECTION_REFUSED`). La page est désormais
refaite après une pause ; un doute APRÈS un clic reste une halte immédiate.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_entry_auto import (  # noqa: E402
    ExtractOutcome, MatchOutcome, Stages, SubmitOutcome, SweepConfig, run_sweep,
    transient_reason,
)

TIMEOUT = ("exit 1 (src.cdp_session.CdpTimeoutError: CDP Runtime.evaluate: "
           "no response within 20s)")


class _Horloge:
    def __init__(self, stop_after=None):
        self.total = 0.0
        self.appels = 0
        self.stop_after = stop_after

    def sleep(self, s):
        self.appels += 1
        self.total += s

    def should_stop(self):
        return self.stop_after is not None and self.total >= self.stop_after


class _Scenario:
    """Un feed de pages 3 → 1 ; chaque étape suit un script d'issues par page."""

    def __init__(self, extracts=None, submits=None, match_ok=True, ids=None):
        self.extracts = {k: list(v) for k, v in (extracts or {}).items()}
        self.submits = {k: list(v) for k, v in (submits or {}).items()}
        self.match_ok = match_ok
        self.ids = ids
        self.appels = []
        self.archives = []

    @staticmethod
    def page(run_id):
        return int(run_id.rsplit("p", 1)[1])

    def stages(self):
        def extract(page, run_id):
            self.appels.append(("extract", page))
            script = self.extracts.get(page)
            if script:
                issue = script.pop(0)
                if issue is not None:
                    return ExtractOutcome(ok=False, offers=0, feed_last_page=3, detail=issue)
            return ExtractOutcome(ok=True, offers=2, feed_last_page=3)

        def match(run_id):
            self.appels.append(("match", self.page(run_id)))
            return MatchOutcome(ok=self.match_ok, candidates=1,
                                detail="" if self.match_ok else "exit 1")

        def submit(run_id):
            self.appels.append(("submit", self.page(run_id)))
            script = self.submits.get(self.page(run_id))
            if script:
                return script.pop(0)
            return SubmitOutcome(ok=True, created=1, offers=[{"name": "ok", "created": True}])

        return Stages(
            extract=extract, match=match, approve=lambda run_id: 1, submit=submit,
            offer_ids=(lambda run_id: tuple(self.ids[self.page(run_id)])) if self.ids else None,
            archive_attempt=lambda run_id, n: self.archives.append((self.page(run_id), n)),
        )


def _balayer(sc, horloge=None, waits=(120.0, 300.0, 600.0)):
    horloge = horloge or _Horloge()
    cfg = SweepConfig(merchant="Wyrel", store_id="162", max_pages=None,
                      transient_retry_waits=waits)
    recap = run_sweep(cfg, sc.stages(), page_run_id=lambda p: f"r-p{p}",
                      should_stop=horloge.should_stop, sleep=horloge.sleep)
    return recap, horloge


def _page(recap, n):
    return [p for p in recap["pages"] if p["page"] == n][-1]


class LaSignaturePassagere(unittest.TestCase):
    def test_les_signatures_du_24_09_sont_passageres(self):
        self.assertEqual(transient_reason(TIMEOUT), "CdpTimeoutError")
        self.assertEqual(transient_reason(
            "CdpCommandError: Page.navigate to https://x failed: net::ERR_CONNECTION_REFUSED"),
            "net::ERR_CONNECTION_REFUSED")

    def test_une_deconnexion_ou_un_crash_ne_le_sont_pas(self):
        self.assertIsNone(transient_reason("exit 2 (not logged in (wp-login))"))
        self.assertIsNone(transient_reason("not logged in — CdpTimeoutError"))
        self.assertIsNone(transient_reason("exit 1 (KeyError: 'offers')"))
        self.assertIsNone(transient_reason(None))


class UneExtractionPassagereEstRefaite(unittest.TestCase):
    def test_un_timeout_puis_la_reussite(self):
        sc = _Scenario(extracts={2: [TIMEOUT]})
        recap, h = _balayer(sc)
        self.assertIsNone(recap["halted"], recap.get("halted"))
        p2 = _page(recap, 2)
        self.assertEqual(p2["transient_retries"][0]["wait_s"], 120.0)
        self.assertEqual(p2["transient_retries"][0]["stage"], "extract")
        self.assertEqual(recap["transient_retries"], 1)
        self.assertEqual(h.total, 120.0)
        self.assertIn(("submit", 2), sc.appels, "la page refaite doit aller jusqu'à la saisie")
        self.assertEqual(recap["total_created"], 3)

    def test_trois_reprises_puis_la_halte_d_avant(self):
        sc = _Scenario(extracts={2: [TIMEOUT] * 5})
        recap, h = _balayer(sc)
        self.assertEqual(recap["halted"], "extract_failed_p2")
        self.assertEqual([r["wait_s"] for r in _page(recap, 2)["transient_retries"]],
                         [120.0, 300.0, 600.0])
        self.assertEqual(h.total, 1020.0)
        self.assertEqual(sc.appels.count(("extract", 2)), 4, "1 essai + 3 reprises")
        self.assertEqual(sc.appels.count(("extract", 1)), 1,
                         "après la halte, la page 1 n'est plus lue (seule la sonde de départ)")

    def test_une_erreur_non_passagere_arrete_tout_de_suite(self):
        sc = _Scenario(extracts={2: ["exit 1 (KeyError: 'offers')"]})
        recap, h = _balayer(sc)
        self.assertEqual(recap["halted"], "extract_failed_p2")
        self.assertEqual(h.total, 0)
        self.assertNotIn("transient_retries", _page(recap, 2))

    def test_la_sonde_de_depart_est_reprise_aussi(self):
        sc = _Scenario(extracts={1: [TIMEOUT]})
        recap, h = _balayer(sc)
        self.assertIsNone(recap["halted"])
        self.assertEqual(recap["transient_retries"], 1)
        self.assertEqual(recap["feed_last_page"], 3)

    def test_arreter_pendant_la_pause_arrete_tout_de_suite(self):
        sc = _Scenario(extracts={2: [TIMEOUT]})
        recap, h = _balayer(sc, horloge=_Horloge(stop_after=20))
        self.assertEqual(recap["halted"], "operator_stop")
        self.assertLessEqual(h.total, 25, "« Arrêter » ne doit pas attendre la fin des 2 min")


class UneSaisieCoupeeAvantLeClicEstRefaite(unittest.TestCase):
    def _prewrite(self, created=2):
        return SubmitOutcome(ok=False, stopped="feed_unreadable_prewrite", created=created,
                             offers=[{"name": f"avant {i}", "created": True} for i in range(created)],
                             detail="exit 2")

    def test_la_page_est_refaite_et_ses_creations_gardees(self):
        sc = _Scenario(submits={2: [self._prewrite(created=2)]})
        recap, h = _balayer(sc)
        self.assertIsNone(recap["halted"])
        p2 = _page(recap, 2)
        self.assertEqual(p2["created"], 3, "2 créées avant la coupure + 1 à la reprise")
        self.assertEqual(len(p2["offers_created"]), 3)
        self.assertEqual(p2["transient_retries"][0]["stage"], "submit")
        self.assertEqual(p2["transient_retries"][0]["created_before"], 2)
        self.assertEqual(sc.archives, [(2, 1)], "les traces de la tentative ratée sont gardées")
        self.assertEqual(recap["total_created"], 5)

    def test_revue_2026_09_25_arreter_pendant_la_pause_ne_double_pas_les_creations(self):
        """REVUE DE ROMAIN (2026-09-25, [P2]) : « deux créations avant l'erreur deviennent quatre
        dans le récapitulatif si l'opérateur arrête pendant la pause ; les offres sont également
        dupliquées »."""

        sc = _Scenario(submits={2: [self._prewrite(created=2)]})
        recap, h = _balayer(sc, horloge=_Horloge(stop_after=20))
        self.assertEqual(recap["halted"], "operator_stop")
        p2 = _page(recap, 2)
        self.assertEqual(p2["created"], 2)
        self.assertEqual(len(p2["offers_created"]), 2)
        self.assertEqual(recap["total_created"], 3, "page 3 (1) + les 2 de la page 2, une fois")
        self.assertEqual(len([p for p in recap["pages"] if p["page"] == 2]), 1)

    def test_un_scan_d_index_rate_avant_toute_offre_est_refait(self):
        sc = _Scenario(submits={2: [SubmitOutcome(ok=False, aborted="feed_unreadable",
                                                 detail="exit 2")]})
        recap, _ = _balayer(sc)
        self.assertIsNone(recap["halted"])
        self.assertEqual(_page(recap, 2)["transient_retries"][0]["reason"], "feed_unreadable")

    def test_un_doute_apres_le_clic_reste_une_halte(self):
        inconnu = SubmitOutcome(ok=False, stopped="feed_unreadable", created=0, detail="exit 2")
        sc = _Scenario(submits={2: [inconnu]})
        recap, h = _balayer(sc)
        self.assertEqual(recap["halted"], "submit_not_clean_p2")
        self.assertEqual(h.total, 0, "état INCONNU : jamais de reprise")

    def test_une_deconnexion_reste_une_halte(self):
        sc = _Scenario(submits={2: [SubmitOutcome(ok=False, aborted="not_logged_in",
                                                 detail="exit 2")]})
        recap, h = _balayer(sc)
        self.assertEqual(recap["halted"], "submit_not_clean_p2")
        self.assertEqual(h.total, 0)

    def test_dix_echecs_ou_garde_restent_des_haltes(self):
        for stop in ("ten_consecutive_failures", "guard_blocked"):
            sc = _Scenario(submits={2: [SubmitOutcome(ok=False, stopped=stop, detail="exit 2")]})
            recap, h = _balayer(sc)
            self.assertEqual(recap["halted"], "submit_not_clean_p2", stop)
            self.assertEqual(h.total, 0, stop)

    def test_un_echec_de_match_reste_une_halte(self):
        sc = _Scenario(match_ok=False)
        recap, h = _balayer(sc)
        self.assertTrue(recap["halted"].startswith("match_failed"))
        self.assertEqual(h.total, 0)

    def test_la_reprise_n_est_pas_prise_pour_une_page_deja_vue(self):
        """Sans restaurer la mesure de couverture, la reprise verrait « ses » ids déjà vus
        et serait SAUTÉE (`skipped_repeated`) sans rien refaire."""

        sc = _Scenario(submits={2: [self._prewrite(created=0)]},
                       ids={1: ["c"], 2: ["a", "b"], 3: ["z"]})
        recap, _ = _balayer(sc)
        p2 = _page(recap, 2)
        self.assertFalse(p2.get("skipped_repeated"), p2)
        self.assertEqual(sc.appels.count(("submit", 2)), 2)
        self.assertEqual(recap["pages_without_new_offers"], [])


if __name__ == "__main__":
    unittest.main()
