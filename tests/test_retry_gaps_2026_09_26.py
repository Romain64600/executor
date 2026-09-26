"""Les deux trous de la reprise automatique vus sur le balayage du groupe B (2026-09-25/26).

Run ``20260925-194851-auto`` (VM vmi3565249), trois haltes dans la nuit :

* **Gamivo p38** (`extract_failed_p38`) — 1re tentative : le scan d'index d'avant la première
  offre ne répond pas (`aborted: feed_unreadable`, write_attempts 0) → reprise à 2 min, juste.
  2e tentative : l'extraction CRASHE (`CdpTimeoutError`, traceback dans la sortie capturée).
  Deux fautes : le détail relu est l'abandon de la 1re tentative (« feed index scan failed
  closed: CDP Runtime.evaluate: no response within 45s »), et ce texte ne porte pas le mot
  « CdpTimeoutError » → pas reconnu passager → halte au lieu des reprises à 5 puis 10 min.
* **Eneba p66** (`submit_not_clean_p66`) — le contrôle de connexion d'avant la première offre
  (`is_login_page`, un `Runtime.evaluate`) reste 45 s muet ; l'exception s'échappait de
  `Submitter.run()`, 05 abandonnait en exit 2 SANS submit_plan.json, rien à reprendre. Rien
  n'avait pu être écrit : journal = validation_saved → catalog_cache_hit → aborted.
* **Kinguin p2** (`submit_not_clean_p2`) — rebond vers wp-login APRÈS le clic « Create » de
  l'offre 101140732 : état INCONNU. Doit rester une halte, jamais une reprise (épinglé ici).

Romain, règle du 2026-09-24 (AGENTS.md) : reprendre une page seulement quand RIEN n'a pu être
écrit. Les journaux / plans de ``tests/fixtures/retry_2026_09_26/`` sont les vrais, élagués.
"""

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cdp_session import CdpTimeoutError  # noqa: E402
from src.data_entry_auto import (  # noqa: E402
    ExtractOutcome, MatchOutcome, Stages, SubmitOutcome, SweepConfig, run_sweep,
    transient_reason,
)
from src.submitter import NotLoggedInError, Submitter  # noqa: E402
from tests.test_submitter import FakeWriteSession, _cand, _real  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "retry_2026_09_26"
GAMIVO_RUN = "20260925-194851-auto-gamivo-s51-p38"
ENEBA_RUN = "20260925-194851-auto-eneba-s19-p66"
KINGUIN_RUN = "20260925-194851-auto-kinguin-s58-p2"
# Le détail que le balayage a réellement enregistré pour la 2e tentative Gamivo (recap).
DETAIL_GAMIVO_PERIME = ("exit 1 (feed index scan failed closed: CDP Runtime.evaluate: "
                        "no response within 45s)")


def _load_sweep_cli():
    spec = importlib.util.spec_from_file_location(
        "m10_retry_gaps", str(ROOT / "scripts" / "10_data_entry_auto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _TmpRoot(unittest.TestCase):
    """scripts/10 pointé sur un ROOT jetable (journaux et dossiers de run)."""

    def setUp(self):
        self.MOD = _load_sweep_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        orig = self.MOD.ROOT
        self.MOD.ROOT = pathlib.Path(self.tmp.name)
        self.addCleanup(lambda: setattr(self.MOD, "ROOT", orig))
        (self.MOD.ROOT / "logs").mkdir()
        (self.MOD.ROOT / "runs").mkdir()

    def _log(self, name):
        return self.MOD.ROOT / "logs" / name

    def _append(self, name, text):
        with self._log(name).open("a", encoding="utf-8") as fh:
            fh.write(text)


# ── Trou A : la signature et le détail d'une extraction ratée ────────────────────────────
class LeTimeoutCdpEstReconnuAuMessage(unittest.TestCase):
    def test_le_detail_enregistre_pour_gamivo_p38_est_passager(self):
        self.assertEqual(transient_reason(DETAIL_GAMIVO_PERIME), "CdpTimeoutError")

    def test_toutes_les_methodes_cdp(self):
        for texte in ("CDP Page.navigate: no response within 20s",
                      "exit 1 (src.cdp_session.CdpTimeoutError: CDP Runtime.evaluate: "
                      "no response within 20s)",
                      "CDP Input.dispatchMouseEvent: no response within 12.5s"):
            with self.subTest(texte):
                self.assertEqual(transient_reason(texte), "CdpTimeoutError")

    def test_une_deconnexion_n_est_jamais_passagere_meme_avec_un_timeout(self):
        for texte in ("exit 2 (not logged in (wp-login))",
                      "NotLoggedInError: feed bounced to wp-login mid-scan — "
                      "CDP Runtime.evaluate: no response within 45s",
                      "feed bounced to wp-login; CdpTimeoutError"):
            with self.subTest(texte):
                self.assertIsNone(transient_reason(texte))

    def test_un_message_incomplet_n_est_pas_une_signature(self):
        self.assertIsNone(transient_reason("no response within 45s"))
        self.assertIsNone(transient_reason("exit 1 (KeyError: 'offers')"))


class LeDetailEstCeluiDeLaTentativeCourante(_TmpRoot):
    """La page refaite réutilise son journal et la sortie capturée de ses stages."""

    def _gamivo_apres_la_tentative_1(self):
        self._append(f"{GAMIVO_RUN}.jsonl", (FIX / "gamivo_p38_try1.jsonl").read_text())
        self._append(f"{GAMIVO_RUN}-stages.log", (FIX / "gamivo_p38_stages_try1.log").read_text())

    def test_gamivo_p38_le_crash_de_la_2e_extraction_est_son_propre_detail(self):
        self._gamivo_apres_la_tentative_1()

        def crash(argv, run_id=None):        # 02_extract_feed : traceback, aucun évènement
            self._append(f"{run_id}-stages.log",
                         (FIX / "gamivo_p38_stages_try2.log").read_text())
            return 1

        with mock.patch.object(self.MOD, "_run_child", side_effect=crash):
            ex = self.MOD._make_stages("Gamivo", "51", "all", None).extract(38, GAMIVO_RUN)
        self.assertFalse(ex.ok)
        self.assertEqual(ex.detail, "exit 1 (src.cdp_session.CdpTimeoutError: CDP "
                                    "Runtime.evaluate: no response within 20s)")
        self.assertNotIn("feed index scan", ex.detail, "l'abandon de la 1re tentative")
        self.assertEqual(transient_reason(ex.detail), "CdpTimeoutError")

    def test_un_abandon_journalise_par_ce_stage_reste_prefere(self):
        self._gamivo_apres_la_tentative_1()

        def abandon(argv, run_id=None):
            self._append(f"{run_id}.jsonl", json.dumps(
                {"event": "aborted", "reason": "not logged in (wp-login)"}) + "\n")
            return 2

        with mock.patch.object(self.MOD, "_run_child", side_effect=abandon):
            ex = self.MOD._make_stages("Gamivo", "51", "all", None).extract(38, GAMIVO_RUN)
        self.assertEqual(ex.detail, "exit 2 (not logged in (wp-login))")
        self.assertIsNone(transient_reason(ex.detail))

    def test_un_stage_muet_ne_rend_pas_le_texte_d_une_autre_tentative(self):
        self._gamivo_apres_la_tentative_1()
        with mock.patch.object(self.MOD, "_run_child", return_value=1):
            ex = self.MOD._make_stages("Gamivo", "51", "all", None).extract(38, GAMIVO_RUN)
        self.assertEqual(ex.detail, "exit 1")

    def test_le_submit_aussi_ne_lit_que_sa_tentative(self):
        self._gamivo_apres_la_tentative_1()
        (self.MOD.ROOT / "runs" / GAMIVO_RUN).mkdir()
        with mock.patch.object(self.MOD, "_run_child", return_value=2):
            sub = self.MOD._make_stages("Gamivo", "51", "all", None).submit(GAMIVO_RUN)
        self.assertEqual(sub.detail, "exit 2")

    def test_un_journal_remplace_par_un_plus_court_est_relu_en_entier(self):
        chemin = self._log("x.jsonl")
        chemin.write_text(json.dumps({"event": "aborted", "reason": "r"}) + "\n")
        self.assertEqual(self.MOD._last_abort_reason("x", since=10 ** 6), "r")


class _Scenario:
    """Une page 2 d'un feed de 3 pages ; chaque étape suit son script d'issues."""

    def __init__(self, extracts=None, submits=None):
        self.extracts = {k: list(v) for k, v in (extracts or {}).items()}
        self.submits = {k: list(v) for k, v in (submits or {}).items()}
        self.appels = []

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
                    return ExtractOutcome(ok=False, offers=100, feed_last_page=3, detail=issue)
            return ExtractOutcome(ok=True, offers=2, feed_last_page=3)

        def submit(run_id):
            self.appels.append(("submit", self.page(run_id)))
            script = self.submits.get(self.page(run_id))
            if script:
                return script.pop(0)
            return SubmitOutcome(ok=True, created=1, offers=[{"name": "ok", "created": True}])

        return Stages(extract=extract,
                      match=lambda run_id: MatchOutcome(ok=True, candidates=1),
                      approve=lambda run_id: 1, submit=submit,
                      archive_attempt=lambda run_id, n: None)


def _balayer(sc):
    pauses = []
    cfg = SweepConfig(merchant="Gamivo", store_id="51", max_pages=None,
                      transient_retry_waits=(120.0, 300.0, 600.0))
    recap = run_sweep(cfg, sc.stages(), page_run_id=lambda p: f"r-p{p}",
                      sleep=pauses.append)
    return recap, sum(pauses)


def _page(recap, n):
    return [p for p in recap["pages"] if p["page"] == n][-1]


class GamivoP38LaPageEstRefaiteJusquAuBout(unittest.TestCase):
    def test_scan_rate_puis_extraction_crashee_puis_reussite(self):
        index_rate = SubmitOutcome(ok=True, aborted="feed_unreadable", created=0)
        sc = _Scenario(extracts={2: [None, DETAIL_GAMIVO_PERIME, None]},
                       submits={2: [index_rate]})
        recap, attendu = _balayer(sc)
        self.assertIsNone(recap["halted"], recap.get("halted_detail"))
        p2 = _page(recap, 2)
        self.assertEqual([(r["stage"], r["wait_s"]) for r in p2["transient_retries"]],
                         [("submit", 120.0), ("extract", 300.0)])
        self.assertEqual(attendu, 420.0)
        self.assertEqual(sc.appels.count(("submit", 2)), 2, "la page va jusqu'à la saisie")

    def test_trois_reprises_au_plus_comme_avant(self):
        sc = _Scenario(extracts={2: [DETAIL_GAMIVO_PERIME] * 5})
        recap, attendu = _balayer(sc)
        self.assertEqual(recap["halted"], "extract_failed_p2")
        self.assertEqual(attendu, 1020.0)


# ── Trou B : l'échec d'avant la boucle des offres ────────────────────────────────────────
class _PreflightMuet(FakeWriteSession):
    """Eneba p66 : navigate passe, le `Runtime.evaluate` du contrôle de connexion reste muet
    45 s. Toute tentative d'ouvrir une modale ou de cliquer ferait échouer le test."""

    def __init__(self, pages, exc=None, **kw):
        super().__init__(pages, **kw)
        self.exc = exc or CdpTimeoutError("CDP Runtime.evaluate: no response within 45s")
        self.touches = []

    def is_login_page(self):
        raise self.exc

    def open_offer_modal(self, offer_id):
        self.touches.append(("modal", offer_id))
        raise AssertionError("aucune offre ne doit être ouverte")

    def fill_then_click_trusted(self, *a, **kw):
        self.touches.append(("click",))
        raise AssertionError("aucun clic ne doit partir")


class EnebaP66LeControleDeConnexionMuetEstAvantToute(unittest.TestCase):
    def test_c_est_un_feed_unreadable_sans_aucune_tentative(self):
        session = _PreflightMuet([["1", "2"]])
        res = _real(session, [_cand("1"), _cand("2")])
        self.assertEqual(res["aborted"], "feed_unreadable")
        self.assertIsNone(res["stopped"])
        self.assertEqual((res["write_attempts"], res["created"], res["plan"]), (0, 0, []))
        self.assertEqual(session.touches, [])

    def test_une_deconnexion_au_meme_endroit_reste_not_logged_in(self):
        session = _PreflightMuet([["1"]], exc=NotLoggedInError("feed bounced to wp-login"))
        res = _real(session, [_cand("1")])
        self.assertEqual(res["aborted"], "not_logged_in")

    def test_le_catalogue_illisible_aussi(self):
        session = FakeWriteSession([["1"]])
        with mock.patch("src.submitter.fetch_session_catalog",
                        side_effect=CdpTimeoutError("CDP Runtime.evaluate: no response within 45s")):
            res = _real(session, [_cand("1")])
        self.assertEqual((res["aborted"], res["write_attempts"]), ("feed_unreadable", 0))

    def test_le_journal_dit_ou_et_pourquoi(self):
        events = []

        class _Log:
            def log(self, event, **fields):
                events.append({"event": event, **fields})

            def log_guard(self, *a, **k):
                pass

        sub = Submitter(_PreflightMuet([["1"]]), logger=_Log())
        sub.run(run_id="r", merchant="Eneba", store_id="19", approved=[_cand("1")])
        aborted = [e for e in events if e["event"] == "aborted"]
        self.assertEqual(len(aborted), 1)
        self.assertIn("pre-flight", aborted[0]["reason"])
        self.assertIn("no response within 45s", aborted[0]["reason"])


class EnebaP66LeBalayageRefaitLaPage(_TmpRoot):
    def test_le_plan_ecrit_par_05_est_lu_comme_un_abandon_avant_ecriture(self):
        """Du submitter réel jusqu'au verdict du balayage : le dict de `run()` est ce que 05
        écrit dans submit_plan.json (exit 0, comme le scan d'index raté de Gamivo p38)."""

        resultat = _real(_PreflightMuet([["1"]]), [_cand("1")])
        run_dir = self.MOD.ROOT / "runs" / ENEBA_RUN
        run_dir.mkdir()
        self._append(f"{ENEBA_RUN}.jsonl", (FIX / "eneba_p66.jsonl").read_text())

        def enfant(argv, run_id=None):
            (run_dir / "submit_plan.json").write_text(json.dumps(resultat))
            return 0

        with mock.patch.object(self.MOD, "_run_child", side_effect=enfant):
            sub = self.MOD._make_stages("Eneba", "19", "all", None).submit(ENEBA_RUN)
        self.assertEqual((sub.aborted, sub.stopped, sub.created), ("feed_unreadable", None, 0))
        self.assertFalse(sub.clean())

        sc = _Scenario(submits={2: [sub]})
        recap, attendu = _balayer(sc)
        self.assertIsNone(recap["halted"])
        self.assertEqual(_page(recap, 2)["transient_retries"][0]["stage"], "submit")
        self.assertEqual(attendu, 120.0)


# ── Kinguin p2 : un doute APRÈS le clic reste une halte ──────────────────────────────────
class _RebondApresLeClic(FakeWriteSession):
    """Le feed rebondit vers wp-login juste après le clic « Create » (01:05 UTC)."""

    def fill_then_click_trusted(self, *a, **kw):
        diag = super().fill_then_click_trusted(*a, **kw)
        self.login = True
        return diag


class KinguinP2ResteUneHalte(_TmpRoot):
    def test_le_submitter_rend_un_etat_inconnu(self):
        res = _real(_RebondApresLeClic([["1", "2"]]), [_cand("1"), _cand("2")])
        self.assertEqual(res["stopped"], "feed_unreadable")
        self.assertIsNone(res["aborted"])
        self.assertEqual(res["write_attempts"], 1)
        self.assertIn("UNKNOWN", res["plan"][0]["post_save"])
        self.assertIn("NotLoggedInError", res["plan"][0]["post_save"])

    def test_le_vrai_plan_de_la_page_arrete_le_balayage_sans_pause(self):
        run_dir = self.MOD.ROOT / "runs" / KINGUIN_RUN
        run_dir.mkdir()
        plan = (FIX / "kinguin_p2_submit_plan.json").read_text()

        def enfant(argv, run_id=None):
            (run_dir / "submit_plan.json").write_text(plan)
            return 0

        with mock.patch.object(self.MOD, "_run_child", side_effect=enfant):
            sub = self.MOD._make_stages("Kinguin", "58", "all", None).submit(KINGUIN_RUN)
        self.assertEqual((sub.aborted, sub.stopped), (None, "feed_unreadable"))
        inconnue = [o for o in sub.offers if "UNKNOWN" in o["post_save"]]
        self.assertEqual([o["name"] for o in inconnue], ["Void Crew US Xbox Series X|S CD Key"])

        sc = _Scenario(submits={2: [sub]})
        recap, attendu = _balayer(sc)
        self.assertEqual(recap["halted"], "submit_not_clean_p2")
        self.assertEqual(attendu, 0, "état INCONNU : jamais de reprise")
        self.assertEqual(sc.appels.count(("submit", 2)), 1)


if __name__ == "__main__":
    unittest.main()
