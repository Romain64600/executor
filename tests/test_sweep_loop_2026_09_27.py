"""La BOUCLE d'un balayage — Romain, 2026-09-27 : « 5 min de pause, sans limite, go pour la
boucle » (src/sweep_loop.py, scripts/10_data_entry_auto.py --loop, src/notify.py).

Ce qu'on prouve ici : une passe finie en relance une autre, dans un nouveau dossier de run,
sur la MÊME liste de cibles ; « Arrêter » agit pendant la pause et ne relance pas ; la boucle
s'arrête d'elle-même sur une déconnexion, un blocage du garde, ou une passe où tous les
marchands se sont arrêtés ; la pause vaut 5 min, 30 après une passe sans création ; l'état
de la boucle est écrit dans loop.json ; les notifications ne lèvent jamais."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import notify as notify_mod  # noqa: E402
from src import sweep_loop  # noqa: E402


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "m10_loop_cli", str(ROOT / "scripts" / "10_data_entry_auto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _recap(merchant, created=1, halted=None, detail=None, pages=None, store="58"):
    r = {"merchant": merchant, "store_id": store, "pages": pages or [],
         "total_created": created, "total_moved": 0, "halted": halted}
    if detail is not None:
        r["halted_detail"] = detail
    return r


def _pass(*targets_recaps, halted=None, halted_merchants=()):
    """Un recap de passe tel que `run_pass` le construit (ce que `stop_reason` lit)."""

    return {"targets": [{"merchant": r["merchant"], "store_id": r["store_id"], "recap": r}
                        for r in targets_recaps],
            "halted": halted, "halted_merchants": list(halted_merchants),
            "total_created": sum(r["total_created"] for r in targets_recaps)}


class LesAidesDeLaBoucle(unittest.TestCase):
    def test_la_passe_1_est_le_lancement_les_suivantes_ont_leur_dossier(self):
        self.assertEqual(sweep_loop.pass_run_id("20260927-auto", 1), "20260927-auto")
        self.assertEqual(sweep_loop.pass_run_id("20260927-auto", 2), "20260927-auto-pass2")
        # …et un dossier de passe n'est PAS un « *-auto » : la route recap « le plus récent »
        # retombe toujours sur le lancement, qui renvoie vers sa passe courante.
        self.assertFalse(sweep_loop.pass_run_id("x-auto", 3).endswith("-auto"))

    def test_une_deconnexion_se_lit_sous_toutes_ses_formes(self):
        for texte in ("exit 2 (not logged in (wp-login))", "NotLoggedInError: feed bounced",
                      "not_logged_in", "feed bounced to wp-login mid-scan"):
            with self.subTest(texte):
                self.assertTrue(sweep_loop.is_login_bounce(texte))
        for texte in ("feed_unreadable", "CdpTimeoutError: no response within 45s", None, ""):
            with self.subTest(texte):
                self.assertFalse(sweep_loop.is_login_bounce(texte))

    def test_les_motifs_d_arret_dans_l_ordre(self):
        ok = _pass(_recap("Kinguin", 3), _recap("Eneba", 0))
        self.assertIsNone(sweep_loop.stop_reason(ok, operator_stopped=False))
        # l'arrêt opérateur d'abord, quoi que dise la passe
        self.assertEqual(sweep_loop.stop_reason(ok, operator_stopped=True), "operator_stop")
        stop = _pass(_recap("Kinguin", 3, halted="extract_failed_p1",
                            detail="exit 2 (not logged in (wp-login))"), halted="Kinguin: extract_failed_p1")
        self.assertEqual(sweep_loop.stop_reason(stop, operator_stopped=False), "session_expired")
        plan = _pass(_recap("Kinguin", 0, halted="submit_not_clean_p2",
                            pages=[{"page": 2, "aborted": "not_logged_in", "error": "submit: not_logged_in"}]),
                     _recap("Eneba", 4))
        self.assertEqual(sweep_loop.stop_reason(plan, operator_stopped=False), "session_expired")
        garde = _pass(_recap("Kinguin", 2, halted="submit_not_clean_p5",
                             pages=[{"page": 5, "stopped": "guard_blocked", "error": "submit: guard_blocked"}]),
                      _recap("Eneba", 4))
        self.assertEqual(sweep_loop.stop_reason(garde, operator_stopped=False), "guard_blocked")
        tous = _pass(_recap("Kinguin", 0, halted="extract_failed_p38", detail="exit 1 (CdpTimeoutError)"),
                     _recap("Eneba", 0, halted="submit_not_clean_p66", detail=None))
        self.assertEqual(sweep_loop.stop_reason(tous, operator_stopped=False), "all_merchants_halted")
        # un seul marchand arrêté : on continue, il sera repris à la passe suivante
        un = _pass(_recap("Kinguin", 0, halted="extract_failed_p38", detail="exit 1 (CdpTimeoutError)"),
                   _recap("Eneba", 0))
        self.assertIsNone(sweep_loop.stop_reason(un, operator_stopped=False))

    def test_un_rebond_apres_un_clic_ne_suffit_pas(self):
        # Kinguin p2, 26/09 01:05 UTC : rebond vers wp-login APRÈS un Create, offre UNKNOWN,
        # la session vivait (CJS a créé 618 offres ensuite). Seul le texte de l'OFFRE le dit —
        # la page est `stopped: feed_unreadable`. La boucle continue ; une session vraiment
        # perdue arrête le marchand suivant à sa première lecture.
        p = _pass(_recap("Kinguin", 9, halted="submit_not_clean_p2",
                         pages=[{"page": 2, "stopped": "feed_unreadable", "error": "submit: feed_unreadable",
                                 "offers_created": [{"post_save": "UNKNOWN: NotLoggedInError: wp-login"}]}]),
                  _recap("CJS-CDKeys", 618))
        self.assertIsNone(sweep_loop.stop_reason(p, operator_stopped=False))

    def test_la_pause_5_min_ou_30_sans_creation(self):
        self.assertEqual(sweep_loop.pause_after_pass({"total_created": 7}, pause_s=300, empty_pause_s=1800), 300)
        self.assertEqual(sweep_loop.pause_after_pass({"total_created": 0}, pause_s=300, empty_pause_s=1800), 1800)

    def test_la_pause_cooperative_s_arrete_sur_demande(self):
        dormi = []
        etat = {"stop": False}

        def sleep(s):
            dormi.append(s)
            if len(dormi) == 2:
                etat["stop"] = True
        self.assertFalse(sweep_loop.cooperative_pause(300, should_stop=lambda: etat["stop"], sleep=sleep))
        self.assertEqual(dormi, [5.0, 5.0])
        dormi.clear()
        self.assertTrue(sweep_loop.cooperative_pause(12, should_stop=lambda: False, sleep=sleep))
        self.assertEqual(dormi, [5.0, 5.0, 2.0])

    def test_loop_json_aller_retour_et_passe_courante(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "r-auto"
            d.mkdir()
            st = sweep_loop.new_status("r-auto", [("Kinguin", "58")], pause_s=300, empty_pause_s=1800,
                                       clock=lambda: "2026-09-27T10:00:00Z")
            sweep_loop.write_status(d, st, lambda: "2026-09-27T10:00:01Z")
            lu = sweep_loop.read_status(d)
            self.assertEqual((lu["run_id"], lu["state"], lu["updated_at"]), ("r-auto", "running", "2026-09-27T10:00:01Z"))
            self.assertIsNone(sweep_loop.current_pass_run_id(d))       # passe 1 = le lancement
            st["current_run_id"] = "r-auto-pass2"
            sweep_loop.write_status(d, st, lambda: "t")
            self.assertEqual(sweep_loop.current_pass_run_id(d), "r-auto-pass2")
            (d / "loop.json").write_text("{pas du json", encoding="utf-8")
            self.assertIsNone(sweep_loop.read_status(d))
            self.assertIsNone(sweep_loop.read_status(Path(tmp) / "absent"))


class LOrchestrateurBoucle(unittest.TestCase):
    """`scripts/10 --loop`, avec `run_sweep` bouchonné et la pause remplacée."""

    def setUp(self):
        self.MOD = _load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.MOD.ROOT = Path(self.tmp.name)
        (self.MOD.ROOT / "runs").mkdir(parents=True)
        self.sent = []
        self.MOD._send_notification = lambda event, text: (self.sent.append((event, text)) or
                                                           {"event": event, "sent": True, "reason": "ok"})
        self.MOD._notify_configured = lambda root=None: True
        self.dormi = []

    def _run(self, argv_extra, sweeps, *, stop_after_sleeps=None, stop_after_passes=None):
        """`sweeps` : les recaps rendus par `run_sweep`, dans l'ordre des appels (un par
        marchand et par passe). `stop_after_sleeps` : « Arrêter » pendant la pause, après N
        tranches ; `stop_after_passes` : « Arrêter » pendant la N-ième passe (dernier marchand)."""

        it = iter(sweeps)
        calls = []
        MOD = self.MOD

        def fake_run_sweep(cfg, stages, *, page_run_id, should_stop, on_page, on_progress, clock):
            calls.append(page_run_id(3))
            rec = next(it)
            if stop_after_passes is not None and len(calls) >= stop_after_passes:
                MOD._RUNNER.stopped = True
            return rec

        def fake_sleep(s):
            self.dormi.append(s)
            if stop_after_sleeps is not None and len(self.dormi) >= stop_after_sleeps:
                MOD._RUNNER.stopped = True

        MOD._loop_sleep = fake_sleep
        out = io.StringIO()
        with mock.patch.object(MOD, "run_sweep", side_effect=fake_run_sweep), \
                mock.patch.object(MOD, "_make_stages", return_value=object()), \
                mock.patch.object(sys, "argv", ["10", "--targets", "Kinguin:58,Eneba:19",
                                                "--run-id", "t-loop", "--continue-on-halt"] + argv_extra), \
                redirect_stdout(out):
            rc = MOD.main()
        loop = sweep_loop.read_status(MOD.ROOT / "runs" / "t-loop")
        return rc, calls, loop, out.getvalue()

    def test_une_passe_finie_en_relance_une_autre_dans_son_propre_dossier(self):
        rc, calls, loop, _ = self._run(
            ["--loop"],
            [_recap("Kinguin", 3), _recap("Eneba", 2, store="19"),          # passe 1
             _recap("Kinguin", 1), _recap("Eneba", 0, store="19")],         # passe 2
            stop_after_sleeps=61)                                            # « Arrêter » pendant la 2e pause
        self.assertEqual(rc, 0)
        self.assertEqual(calls[:2], ["t-loop-kinguin-s58-p3", "t-loop-eneba-s19-p3"])
        self.assertEqual(calls[2:], ["t-loop-pass2-kinguin-s58-p3", "t-loop-pass2-eneba-s19-p3"],
                         "la passe 2 a ses propres ids de page")
        r1 = json.loads((self.MOD.ROOT / "runs" / "t-loop" / "recap.json").read_text(encoding="utf-8"))
        r2 = json.loads((self.MOD.ROOT / "runs" / "t-loop-pass2" / "recap.json").read_text(encoding="utf-8"))
        self.assertEqual((r1["run_id"], r1["loop_pass"], r1["total_created"]), ("t-loop", 1, 5))
        self.assertEqual((r2["run_id"], r2["loop_pass"], r2["launch_run_id"], r2["total_created"]),
                         ("t-loop-pass2", 2, "t-loop", 1))
        self.assertEqual(loop["state"], "stopped")
        self.assertEqual(loop["stopped_reason"], "operator_stop")
        self.assertEqual([p["run_id"] for p in loop["passes"]], ["t-loop", "t-loop-pass2"])
        self.assertEqual([p["total_created"] for p in loop["passes"]], [5, 1])
        self.assertEqual(loop["totals"], {"created": 6, "passes_finished": 2})
        self.assertTrue(all(p["finished_at"] for p in loop["passes"]))
        # la 1re pause : 5 min (des créations) — 60 tranches de 5 s
        self.assertEqual(sum(self.dormi[:60]), 300)
        # le marqueur est rendu à la fin de la boucle
        from src import run_marker
        self.assertIsNone(run_marker.read_marker(self.MOD.ROOT))

    def test_arreter_pendant_la_pause_ne_relance_pas(self):
        rc, calls, loop, _ = self._run(["--loop"], [_recap("Kinguin", 3), _recap("Eneba", 2, store="19")],
                                       stop_after_sleeps=1)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2, "aucune passe 2")
        self.assertFalse((self.MOD.ROOT / "runs" / "t-loop-pass2").exists())
        self.assertEqual((loop["state"], loop["stopped_reason"], loop["pass"]), ("stopped", "operator_stop", 1))
        self.assertEqual([e for e, _ in self.sent], ["loop_pass_finished"],
                         "un arrêt opérateur ne notifie pas : c'est lui qui a arrêté")

    def test_arreter_pendant_une_passe_ne_relance_pas(self):
        rc, calls, loop, _ = self._run(["--loop"], [_recap("Kinguin", 3), _recap("Eneba", 2, store="19")],
                                       stop_after_passes=2)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.dormi, [], "pas de pause après un arrêt opérateur")
        self.assertEqual(loop["stopped_reason"], "operator_stop")

    def test_une_passe_sans_creation_attend_30_min(self):
        self._run(["--loop"], [_recap("Kinguin", 0), _recap("Eneba", 0, store="19")], stop_after_sleeps=360)
        self.assertEqual((len(self.dormi), sum(self.dormi)), (360, 1800))

    def test_la_pause_choisie_par_l_operateur(self):
        self._run(["--loop", "--loop-pause-s", "120"], [_recap("Kinguin", 2), _recap("Eneba", 0, store="19")],
                  stop_after_sleeps=24)
        self.assertEqual((len(self.dormi), sum(self.dormi)), (24, 120))

    def test_une_pause_sous_la_minute_est_refusee(self):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["10", "--targets", "Kinguin:58", "--run-id", "t-x",
                                             "--loop", "--loop-pause-s", "10"]), redirect_stdout(out):
            rc = self.MOD.main()
        self.assertEqual(rc, 2)
        self.assertIn("--loop-pause-s", out.getvalue())

    def test_la_session_expiree_arrete_la_boucle_et_previent(self):
        rc, calls, loop, _ = self._run(
            ["--loop"],
            [_recap("Kinguin", 0, halted="extract_failed_p1", detail="exit 2 (not logged in (wp-login))"),
             _recap("Eneba", 0, store="19", halted="extract_failed_p1", detail="exit 2 (not logged in (wp-login))")])
        self.assertEqual(rc, 2, "une halte fail-closed rend 2")
        self.assertEqual(len(calls), 2, "pas de passe 2 : la boucle ne se reconnecte jamais")
        self.assertEqual(self.dormi, [])
        self.assertEqual((loop["state"], loop["stopped_reason"]), ("stopped", "session_expired"))
        self.assertIn("cookies", loop["stopped_label"])
        self.assertEqual([e for e, _ in self.sent], ["session_expired"])
        self.assertIn("transfert de cookies", self.sent[0][1])

    def test_tous_les_marchands_arretes_arrete_la_boucle(self):
        rc, calls, loop, _ = self._run(
            ["--loop"],
            [_recap("Kinguin", 0, halted="extract_failed_p38", detail="exit 1 (CdpTimeoutError)"),
             _recap("Eneba", 0, store="19", halted="submit_not_clean_p66")])
        self.assertEqual(rc, 2)
        self.assertEqual((len(calls), loop["stopped_reason"]), (2, "all_merchants_halted"))
        self.assertEqual([e for e, _ in self.sent], ["loop_stopped"])
        self.assertIn("tous les marchands", self.sent[0][1])

    def test_un_seul_marchand_arrete_est_repris_a_la_passe_suivante(self):
        rc, calls, loop, _ = self._run(
            ["--loop"],
            [_recap("Kinguin", 0, halted="extract_failed_p38", detail="exit 1 (CdpTimeoutError)"),
             _recap("Eneba", 4, store="19"),
             _recap("Kinguin", 2), _recap("Eneba", 1, store="19")],
            stop_after_sleeps=61)
        self.assertEqual(len(calls), 4, "Kinguin est rebalayé à la passe 2")
        self.assertEqual(loop["passes"][0]["halted_merchants"], 1)
        self.assertIn("arrêts : Kinguin (extract_failed_p38)", self.sent[0][1])
        self.assertEqual(rc, 2)

    def test_le_garde_bloque_arrete_la_boucle(self):
        rc, calls, loop, _ = self._run(
            ["--loop"],
            [_recap("Kinguin", 2, halted="submit_not_clean_p5",
                    pages=[{"page": 5, "created": 2, "stopped": "guard_blocked", "error": "submit: guard_blocked"}]),
             _recap("Eneba", 4, store="19")])
        self.assertEqual((len(calls), loop["stopped_reason"]), (2, "guard_blocked"))

    def test_sans_loop_rien_ne_change(self):
        rc, calls, loop, out = self._run([], [_recap("Kinguin", 3), _recap("Eneba", 2, store="19")])
        self.assertEqual((rc, len(calls)), (0, 2))
        self.assertIsNone(loop, "pas de loop.json hors boucle")
        self.assertEqual(self.dormi, [])
        r1 = json.loads((self.MOD.ROOT / "runs" / "t-loop" / "recap.json").read_text(encoding="utf-8"))
        self.assertNotIn("loop_pass", r1)

    def test_les_notifications_sont_journalisees_sans_secret(self):
        self._run(["--loop"], [_recap("Kinguin", 3), _recap("Eneba", 2, store="19")], stop_after_sleeps=1)
        lignes = [json.loads(l) for l in (self.MOD.ROOT / "logs" / "t-loop.jsonl").read_text(encoding="utf-8").splitlines()]
        ev = [l for l in lignes if l["event"] == "notify"]
        self.assertEqual([e["kind"] for e in ev], ["loop_pass_finished"])
        self.assertNotIn("http", json.dumps(ev))

    def test_une_notification_qui_echoue_n_arrete_rien(self):
        self.MOD._send_notification = lambda event, text: {"event": event, "sent": False, "reason": "URLError"}
        rc, calls, loop, out = self._run(["--loop"], [_recap("Kinguin", 3), _recap("Eneba", 2, store="19")],
                                         stop_after_sleeps=1)
        self.assertEqual(rc, 0)
        self.assertIn('"notify_failed"', out)
        self.assertIn('"URLError"', out)

    def test_les_ajouts_de_la_console_valent_pour_la_passe_ou_ils_sont_pris(self):
        # Un marchand ajouté (file du LANCEMENT) est pris par la passe courante, pas rebalayé
        # par la suivante ; le groupe, lui, repart entier.
        launch = self.MOD.ROOT / "runs" / "t-loop"
        launch.mkdir(parents=True, exist_ok=True)
        (launch / "targets_queue.json").write_text(
            json.dumps([{"merchant": "G2A", "store_id": "38", "by": "romain", "at": "t"}]), encoding="utf-8")
        rc, calls, loop, _ = self._run(
            ["--loop"],
            [_recap("Kinguin", 3), _recap("Eneba", 2, store="19"), _recap("G2A", 1, store="38"),   # passe 1
             _recap("Kinguin", 1), _recap("Eneba", 0, store="19")],                                # passe 2
            stop_after_sleeps=61)
        self.assertEqual([c.split("-s")[0] for c in calls],
                         ["t-loop-kinguin", "t-loop-eneba", "t-loop-g2a", "t-loop-pass2-kinguin", "t-loop-pass2-eneba"])


class LeNotificateur(unittest.TestCase):
    def test_dotenv_lit_les_paires_et_ignore_le_reste(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text("# commentaire\n\nexport AKS_DISCORD_WEBHOOK='https://discord.com/api/webhooks/1/abc'\n"
                         "AUTRE=\"x=y\"\nSANS_EGAL\n", encoding="utf-8")
            d = notify_mod.read_dotenv(p)
            self.assertEqual(d["AKS_DISCORD_WEBHOOK"], "https://discord.com/api/webhooks/1/abc")
            self.assertEqual(d["AUTRE"], "x=y")
            self.assertNotIn("SANS_EGAL", d)
            self.assertEqual(notify_mod.read_dotenv(Path(tmp) / "absent"), {})

    def test_l_environnement_prime_et_seul_https_est_accepte(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("AKS_DISCORD_WEBHOOK=https://h.example/a\n", encoding="utf-8")
            self.assertEqual(notify_mod.webhook_url(root=root, environ={}), "https://h.example/a")
            self.assertEqual(notify_mod.webhook_url(root=root, environ={"AKS_DISCORD_WEBHOOK": "https://env.example/b"}),
                             "https://env.example/b")
            self.assertIsNone(notify_mod.webhook_url(root=root, environ={"AKS_DISCORD_WEBHOOK": "http://clair.example"}))
            self.assertIsNone(notify_mod.webhook_url(root=root / "nope", environ={}))
            self.assertFalse(notify_mod.configured(root=root / "nope", environ={}))

    def test_sans_webhook_c_est_un_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            appels = []
            r = notify_mod.notify("loop_stopped", "x", root=Path(tmp), environ={},
                                  urlopen=lambda *a, **k: appels.append(a))
            self.assertEqual(r, {"event": "loop_stopped", "sent": False, "reason": "no_webhook"})
            self.assertEqual(appels, [])

    def test_le_message_part_en_json_sur_l_url_et_jamais_ailleurs(self):
        vus = {}

        class Resp:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            vus["url"] = req.full_url
            vus["body"] = json.loads(req.data.decode("utf-8"))
            vus["timeout"] = timeout
            vus["ct"] = req.get_header("Content-type")
            return Resp()
        env = {"AKS_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/1/secret"}
        r = notify_mod.notify("loop_stopped", "boucle arrêtée", environ=env, urlopen=urlopen)
        self.assertEqual(r["sent"], True)
        self.assertEqual(vus["url"], env["AKS_DISCORD_WEBHOOK"])
        self.assertEqual(vus["body"], {"content": "boucle arrêtée"})
        self.assertEqual(vus["timeout"], 10.0)
        self.assertEqual(vus["ct"], "application/json")
        self.assertNotIn("secret", json.dumps(r))

    def test_un_echec_ne_leve_jamais(self):
        env = {"AKS_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/1/secret"}

        def boom(req, timeout=None):
            raise OSError("réseau")
        r = notify_mod.notify("loop_stopped", "x", environ=env, urlopen=boom)
        self.assertEqual(r, {"event": "loop_stopped", "sent": False, "reason": "OSError"})

        class Resp:
            status = 429
            def __enter__(self): return self
            def __exit__(self, *a): return False
        r = notify_mod.notify("loop_stopped", "x", environ=env, urlopen=lambda req, timeout=None: Resp())
        self.assertEqual(r["reason"], "HTTP 429")

    def test_le_texte_est_tronque_a_la_limite_discord(self):
        vus = {}

        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            vus["n"] = len(json.loads(req.data.decode("utf-8"))["content"])
            return Resp()
        notify_mod.notify("x", "a" * 5000, environ={"AKS_DISCORD_WEBHOOK": "https://d/x"}, urlopen=urlopen)
        self.assertEqual(vus["n"], notify_mod.MAX_CONTENT)


if __name__ == "__main__":
    unittest.main()
