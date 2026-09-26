"""La page EN COURS se voit dans la console — Romain, 2026-09-26 (« 4. Go »).

Le 25/09, la console de l'ancienne VM est restée une heure sur « 0 offres créées · 0 marchand »
pendant que Gamesplanet FR saisissait sa page 3 (52 offres à ~58 s) : le recap n'était réécrit
qu'à la FIN d'une page. Le balayage pose maintenant ``recap["current"]`` (page, run, étape) à
chaque changement d'étape et appelle ``on_progress`` ; la console lit les compteurs de la saisie
dans le journal de la page (route ``/api/runs/<run>``, déjà servie par l'admin).

Ce que ces tests épinglent : la suite des étapes, les champs que chaque étape connaît, la remise
à ``None`` à chaque fin de page, et surtout que l'affichage ne change RIEN au balayage — même
recap final avec ou sans ``on_progress``, et un ``on_progress`` qui lève est ignoré.
"""

import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_entry_auto import (  # noqa: E402
    ExtractOutcome, MatchOutcome, MoveOutcome, Stages, SubmitOutcome, SweepConfig, run_sweep,
)

TIMEOUT = ("exit 1 (src.cdp_session.CdpTimeoutError: CDP Runtime.evaluate: "
           "no response within 20s)")


class _Horloge:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"2026-09-26T10:{self.n // 60:02d}:{self.n % 60:02d}Z"


def _stages(candidats=None, extracts=None, submits=None, move=False):
    """Un feed de 3 pages ; ``candidats`` par page (défaut 1), ``extracts`` / ``submits`` =
    issues scriptées par page (None = réussite)."""

    candidats = candidats or {}
    extracts = {k: list(v) for k, v in (extracts or {}).items()}
    submits = {k: list(v) for k, v in (submits or {}).items()}

    def page(run_id):
        return int(run_id.rsplit("p", 1)[1])

    def extract(p, run_id):
        script = extracts.get(p)
        if script:
            issue = script.pop(0)
            if issue is not None:
                return ExtractOutcome(ok=False, offers=0, feed_last_page=3, detail=issue)
        return ExtractOutcome(ok=True, offers=100, feed_last_page=3)

    def match(run_id):
        return MatchOutcome(ok=True, candidates=candidats.get(page(run_id), 1),
                            movable=2 if move else 0)

    def submit(run_id):
        script = submits.get(page(run_id))
        if script:
            return script.pop(0)
        return SubmitOutcome(ok=True, created=1, offers=[{"name": "ok", "created": True}])

    return Stages(
        extract=extract, match=match, approve=lambda run_id: candidats.get(page(run_id), 1),
        submit=submit,
        move=(lambda run_id: MoveOutcome(ok=True, moved=2)) if move else None,
    )


def _balayer(stages, on_progress=None, waits=(120.0, 300.0, 600.0)):
    vus = []

    def suivre(recap):
        vus.append(copy.deepcopy(recap["current"]))
        if on_progress is not None:
            on_progress(recap)

    cfg = SweepConfig(merchant="Gamesplanet FR", store_id="55", max_pages=None,
                      transient_retry_waits=waits)
    recap = run_sweep(cfg, stages, page_run_id=lambda p: f"r-p{p}", on_progress=suivre,
                      sleep=lambda s: None, clock=_Horloge())
    return recap, vus


class LesEtapesSeSuivent(unittest.TestCase):
    def test_sonde_puis_chaque_page_de_la_plus_haute_a_la_premiere(self):
        recap, vus = _balayer(_stages())
        etapes = [(c["page"], c["stage"]) for c in vus]
        self.assertEqual(etapes, [
            (1, "probe"),
            (3, "extract"), (3, "match"), (3, "submit"),
            (2, "extract"), (2, "match"), (2, "submit"),
            (1, "extract"), (1, "match"), (1, "submit"),
        ])
        self.assertIsNone(recap["current"], "à la fin du balayage, plus rien « en cours »")
        self.assertEqual(recap["total_created"], 3)

    def test_chaque_etape_porte_ce_quelle_sait(self):
        _, vus = _balayer(_stages(candidats={3: 52}))
        p3 = [c for c in vus if c["page"] == 3]
        match = next(c for c in p3 if c["stage"] == "match")
        saisie = next(c for c in p3 if c["stage"] == "submit")
        self.assertEqual(match["offers"], 100)
        self.assertEqual((saisie["candidates"], saisie["approved"]), (52, 52))
        self.assertEqual(saisie["offers"], 100, "l'étape suivante garde ce que la page sait déjà")
        self.assertEqual(saisie["run"], "r-p3", "la console lit les compteurs dans CE run")
        self.assertEqual(saisie["since"], p3[0]["since"], "« depuis » = début de la page")
        self.assertLessEqual(saisie["since"], saisie["stage_at"])

    def test_une_page_sans_candidat_na_pas_detape_saisie(self):
        _, vus = _balayer(_stages(candidats={2: 0}))
        self.assertNotIn((2, "submit"), [(c["page"], c["stage"]) for c in vus])

    def test_le_deplacement_se_voit(self):
        _, vus = _balayer(_stages(move=True))
        mv = [c for c in vus if c["stage"] == "move"]
        self.assertEqual([c["page"] for c in mv], [3, 2, 1])
        self.assertEqual(mv[0]["movable"], 2)

    def test_la_page_finie_nest_plus_en_cours(self):
        """Chaque fin de page (on_page) voit ``current`` à None : un recap persisté entre deux
        pages ne montre jamais une page finie comme « en cours »."""

        vus_fin = []
        cfg = SweepConfig(merchant="Gamesplanet FR", store_id="55", max_pages=None)
        run_sweep(cfg, _stages(), page_run_id=lambda p: f"r-p{p}",
                  on_page=lambda r: vus_fin.append(r["current"]), clock=_Horloge())
        self.assertEqual(vus_fin, [None, None, None])


class UneRepriseSeVoit(unittest.TestCase):
    def test_pause_puis_essai_2(self):
        _, vus = _balayer(_stages(extracts={2: [TIMEOUT]}))
        p2 = [c for c in vus if c["page"] == 2]
        self.assertEqual([c["stage"] for c in p2], ["extract", "pause", "extract", "match", "submit"])
        pause = p2[1]
        self.assertEqual(pause["wait_s"], 120.0)
        self.assertIn("CdpTimeoutError", pause["reason"])
        self.assertEqual(p2[2]["attempt"], 2)
        self.assertNotIn("wait_s", p2[2], "la pause ne s'affiche que tant qu'elle dure")
        self.assertEqual(p2[2]["since"], p2[0]["since"], "« depuis » = premier essai de la page")

    def test_pause_de_la_sonde(self):
        _, vus = _balayer(_stages(extracts={1: [TIMEOUT]}))
        self.assertEqual([(c["page"], c["stage"]) for c in vus[:3]],
                         [(1, "probe"), (1, "pause"), (1, "probe")])

    def test_une_saisie_arretee_avant_ecriture_se_reprend_visiblement(self):
        coupe = SubmitOutcome(ok=False, created=2, offers=[{"name": "a", "created": True}] * 2,
                              stopped="feed_unreadable_prewrite")
        recap, vus = _balayer(_stages(submits={3: [coupe]}))
        p3 = [c["stage"] for c in vus if c["page"] == 3]
        self.assertEqual(p3, ["extract", "match", "submit", "pause", "extract", "match", "submit"])
        self.assertIsNone(recap["current"])


class LAffichageNeChangeRienAuBalayage(unittest.TestCase):
    def _sans_current(self, recap):
        return {k: v for k, v in recap.items() if k != "current"}

    def test_meme_recap_avec_ou_sans_on_progress(self):
        cfg = SweepConfig(merchant="Gamesplanet FR", store_id="55", max_pages=None,
                          transient_retry_waits=(1.0,))
        sans = run_sweep(cfg, _stages(extracts={2: [TIMEOUT]}), page_run_id=lambda p: f"r-p{p}",
                         sleep=lambda s: None)
        avec, _ = _balayer(_stages(extracts={2: [TIMEOUT]}), waits=(1.0,))
        self.assertEqual(self._sans_current(sans), self._sans_current(avec))
        self.assertIsNone(sans["current"])

    def test_un_on_progress_qui_leve_est_ignore(self):
        def casse(recap):
            raise OSError("disque plein")

        recap, vus = _balayer(_stages(), on_progress=casse)
        self.assertIsNone(recap["halted"])
        self.assertEqual(recap["total_created"], 3)
        self.assertEqual(len(vus), 10)


class LOrchestrateurEcritLaPageEnCours(unittest.TestCase):
    """scripts/10 : le marchand est au recap DÈS son démarrage, et chaque étape y est écrite."""

    def setUp(self):
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location(
            "m10_live", str(ROOT / "scripts" / "10_data_entry_auto.py"))
        self.MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.MOD)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.MOD.ROOT = pathlib.Path(self.tmp.name)

    def test_le_marchand_puis_letape_sont_sur_disque_avant_la_fin_de_la_page(self):
        import json
        from unittest import mock
        chemin = pathlib.Path(self.tmp.name) / "runs" / "t-live" / "recap.json"
        vu = {}

        def faux_run_sweep(cfg, stages, *, on_page=lambda r: None, on_progress=None,
                           clock=None, **kw):
            # 1. Avant toute page : le marchand est déjà listé (il ne l'était qu'après la
            #    fin de la première page — une heure de console vide le 25/09).
            vu["au_demarrage"] = json.loads(chemin.read_text(encoding="utf-8"))
            live = {"merchant": cfg.merchant, "store_id": cfg.store_id, "pages": [],
                    "total_created": 0, "halted": None,
                    "current": {"page": 3, "run": "t-live-gamesplanet-fr-s55-p3",
                                "stage": "submit", "candidates": 52, "approved": 52,
                                "since": clock(), "stage_at": clock()}}
            # 2. Une étape en cours de page : persistée tout de suite.
            on_progress(live)
            vu["pendant"] = json.loads(chemin.read_text(encoding="utf-8"))
            live["current"] = None
            live["pages"].append({"page": 3, "created": 52})
            live["total_created"] = 52
            on_page(live)
            return live

        with mock.patch.object(self.MOD, "run_sweep", side_effect=faux_run_sweep), \
                mock.patch.object(sys, "argv", ["10_data_entry_auto.py", "--targets",
                                                "Gamesplanet FR:55", "--run-id", "t-live"]):
            code = self.MOD.main()
        self.assertEqual(code, 0)
        cible = vu["au_demarrage"]["targets"]
        self.assertEqual([(t["merchant"], t["store_id"], t["recap"]) for t in cible],
                         [("Gamesplanet FR", "55", None)])
        cur = vu["pendant"]["targets"][0]["recap"]["current"]
        self.assertEqual((cur["page"], cur["stage"], cur["candidates"]), (3, "submit", 52))
        self.assertRegex(cur["stage_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$",
                         "même format que les ts des journaux de page")
        fin = json.loads(chemin.read_text(encoding="utf-8"))
        self.assertIsNone(fin["targets"][0]["recap"]["current"])
        self.assertEqual(fin["total_created"], 52)


from tests.test_admin_app import AppTestCase  # noqa: E402


class LAdminSertDejaLesCompteurs(AppTestCase):
    """Le contrat que lit la console, SANS nouvelle route (donc sans redémarrer l'admin) :
    le recap garde ``current`` tel qu'écrit (et son sha AS1 reste celui des octets du
    fichier), et ``/api/runs/<run de la page>`` compte créées / échecs dans le journal de la
    page pendant que la saisie tourne."""

    SWEEP = "20260926-100000-auto"
    PAGE = "20260926-100000-auto-gamesplanet-fr-s55-p3"

    def _ecrire(self):
        import json
        sweep = self.runs / self.SWEEP
        sweep.mkdir(parents=True)
        self.recap_bytes = json.dumps({
            "run_id": self.SWEEP, "total_created": 0, "halted": None,
            "targets": [{"merchant": "Gamesplanet FR", "store_id": "55", "recap": {
                "pages": [], "total_created": 0,
                "current": {"page": 3, "run": self.PAGE, "stage": "submit",
                            "candidates": 52, "approved": 52,
                            "since": "2026-09-26T10:00:00Z",
                            "stage_at": "2026-09-26T10:03:00Z"}}}],
        }).encode("utf-8")
        (sweep / "recap.json").write_bytes(self.recap_bytes)
        page = self.runs / self.PAGE
        page.mkdir(parents=True)
        (page / "offers.json").write_text(json.dumps({"merchant": "Gamesplanet FR", "offers": [
            {"offer_id": "1", "store_id": "55"}]}), encoding="utf-8")
        self.logs.mkdir(parents=True, exist_ok=True)
        lignes = [
            {"event": "page_scripts_wait", "ts": "2026-09-26T10:03:10Z"},
            {"event": "submit_offer", "offer_id": "a", "success": True, "ts": "2026-09-26T10:04:00Z"},
            {"event": "submit_offer", "offer_id": "b", "success": True, "ts": "2026-09-26T10:05:00Z"},
            {"event": "submit_offer", "offer_id": "c", "success": False, "ts": "2026-09-26T10:06:00Z"},
        ]
        (self.logs / f"{self.PAGE}.jsonl").write_text(
            "".join(json.dumps(l) + "\n" for l in lignes), encoding="utf-8")

    def test_recap_intact_et_compteurs_de_la_page(self):
        import hashlib
        self._ecrire()
        response, body = self._json("GET", f"/api/data-entry/recap?run={self.SWEEP}")
        self.assertEqual(response.status, 200)
        cur = body["recap"]["targets"][0]["recap"]["current"]
        self.assertEqual((cur["page"], cur["run"], cur["stage"]), (3, self.PAGE, "submit"))
        self.assertEqual(body["recap_sha256"], hashlib.sha256(self.recap_bytes).hexdigest(),
                         "AS1 : le sha reste celui des octets du fichier")
        response, detail = self._json("GET", f"/api/runs/{self.PAGE}")
        self.assertEqual(response.status, 200)
        self.assertEqual((detail["created_count"], detail["failed_count"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
