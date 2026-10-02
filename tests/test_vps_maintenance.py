"""Maintenance des VPS — scripts/18_vps_maintenance.py (sur chaque VPS) et scripts/19_restart_vps.py
(le pilote), 2026-09-30.

Romain : « on va pouvoir travailler sur un script de restart, que tu feras passer sur les VPS
esclaves puis le tien », puis « go pour la v2 ». Ce que ces tests épinglent : une saisie n'est
jamais coupée en plein clic (arrêt coopératif et attente, sinon rien), la mise à jour ne redémarre
aucun service et garde les fichiers de config, le redémarrage n'a lieu que si Debian l'exige et
que la politique du VPS l'autorise, rien n'est relancé sans preuve (services, invariants, session),
le pilote attend un NOUVEAU démarrage et s'arrête au premier VPS en échec. Aucun test ne touche à
un vrai VPS : tout passe par des doublures."""

import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, str(ROOT / "scripts" / fichier))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _charger("vps_maintenance", "18_vps_maintenance.py")
P = _charger("restart_vps", "19_restart_vps.py")


def _cp(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


# Le vrai lancement du groupe B du 29/09 (runs/20260929-081658-auto/admin_submit.json).
LANCEMENT_B = {
    "state": "running", "kind": "data_entry_auto", "run_id": "20260929-081658-auto",
    "targets": [{"merchant": m, "store_id": s} for m, s in (
        ("Gamivo", "51"), ("Eneba", "19"), ("Kinguin", "58"), ("CJS-CDKeys", "30"),
        ("Gamerall", "13"), ("Electronicfirst", "70"), ("Allyouplay", "17"), ("K4G", "92"),
        ("Wyrel", "162"))],
    "by": "romain", "max_pages": None, "continue_on_halt": True, "consoles": True, "list_id": 9,
    "argv": ["/usr/bin/python3", "/home/debian/executor/scripts/10_data_entry_auto.py", "--targets",
             "Gamivo:51,Eneba:19,Kinguin:58,CJS-CDKeys:30,Gamerall:13,Electronicfirst:70,"
             "Allyouplay:17,K4G:92,Wyrel:162", "--run-id", "20260929-081658-auto",
             "--sitemap-refresh", "--all-pages", "--continue-on-halt", "--consoles"],
}


class LaMiseAJourNeCoupeRien(unittest.TestCase):
    def test_options_apt(self):
        cmds = M.apt_commands()
        self.assertEqual([c[-1] for c in cmds], ["update", "full-upgrade", "autoremove"])
        for c in cmds:
            with self.subTest(c[-1]):
                texte = " ".join(c)
                for attendu in ("DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=l",
                                "NEEDRESTART_SUSPEND=1", "DPkg::Lock::Timeout=600",
                                "--force-confdef", "--force-confold"):
                    self.assertIn(attendu, texte)
                self.assertEqual(c[0], "sudo")

    def test_jamais_de_tmux_kill_server_ni_de_reboot_sec(self):
        for f in ("18_vps_maintenance.py", "19_restart_vps.py"):
            source = (ROOT / "scripts" / f).read_text(encoding="utf-8")
            with self.subTest(f):
                self.assertNotIn('"kill-server"', source)
        # le seul redémarrage : `systemctl reboot`, sous le verrou du navigateur (ré-audit 01/10)
        agent = (ROOT / "scripts" / "18_vps_maintenance.py").read_text(encoding="utf-8")
        lignes = [ln for ln in agent.splitlines() if '"systemctl", "reboot"' in ln]
        self.assertEqual(len(lignes), 1, lignes)
        self.assertNotIn('["sudo", "reboot"]', agent)
        self.assertNotIn('"shutdown"', agent)
        self.assertIn('with browser_lock(ROOT, label="maintenance: redémarrage imminent")', agent)


class CeQuiEstRelance(unittest.TestCase):
    def test_un_balayage_simple_reprend_au_marchand_en_cours(self):
        recap = {"targets": [{"merchant": m} for m in ("Gamivo", "Eneba", "Kinguin", "CJS-CDKeys")]}
        rest = M.remaining_targets(LANCEMENT_B["targets"], recap, loop=False)
        self.assertEqual([t["merchant"] for t in rest],
                         ["CJS-CDKeys", "Gamerall", "Electronicfirst", "Allyouplay", "K4G", "Wyrel"])

    def test_une_boucle_repart_entiere(self):
        recap = {"targets": [{"merchant": "GameSeal"}, {"merchant": "G2A"}]}
        self.assertEqual(M.remaining_targets(LANCEMENT_B["targets"], recap, loop=True),
                         LANCEMENT_B["targets"])

    def test_un_recap_illisible_relance_tout(self):
        self.assertEqual(M.remaining_targets(LANCEMENT_B["targets"], None, loop=False),
                         LANCEMENT_B["targets"])
        inconnu = {"targets": [{"merchant": "Inconnu"}]}
        self.assertEqual(M.remaining_targets(LANCEMENT_B["targets"], inconnu, loop=False),
                         LANCEMENT_B["targets"])

    def _run_dir(self, tmp, meta, recap=None, loop=None, pass_recap=None):
        run = pathlib.Path(tmp) / meta["run_id"]
        run.mkdir()
        (run / "admin_submit.json").write_text(json.dumps(meta), encoding="utf-8")
        if recap is not None:
            (run / "recap.json").write_text(json.dumps(recap), encoding="utf-8")
        if loop is not None:
            (run / "loop.json").write_text(json.dumps(loop), encoding="utf-8")
            passe = pathlib.Path(tmp) / loop["current_run_id"]
            passe.mkdir()
            (passe / "recap.json").write_text(json.dumps(pass_recap or {}), encoding="utf-8")
        return run

    def test_le_corps_de_relance_du_groupe_b(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run_dir(tmp, LANCEMENT_B, recap={"targets": [
                {"merchant": "Gamivo"}, {"merchant": "Eneba"}, {"merchant": "Kinguin"},
                {"merchant": "CJS-CDKeys"}]})
            body = M.relaunch_spec(run)
        self.assertEqual(body["targets"][0], {"merchant": "CJS-CDKeys", "store_id": "30"})
        self.assertEqual(len(body["targets"]), 6)
        self.assertEqual((body["confirm"], body["continue_on_halt"], body["consoles"], body["list"],
                          body["loop"], body["all_pages"]), ("GO", True, True, 9, False, True))
        self.assertNotIn("max_pages", body)
        self.assertIn("maintenance", body["by"])

    def test_une_boucle_se_relance_en_boucle(self):
        meta = dict(LANCEMENT_B, run_id="20260929-170428-auto",
                    argv=LANCEMENT_B["argv"] + ["--loop"])
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run_dir(tmp, meta, loop={"loop": True, "current_run_id": "20260929-170428-auto-pass3"},
                                pass_recap={"targets": [{"merchant": "Kinguin"}]})
            body = M.relaunch_spec(run)
        self.assertTrue(body["loop"])
        self.assertEqual(len(body["targets"]), 9, "une boucle repart entière")

    def test_un_lancement_illisible_ne_se_relance_pas(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp) / "x"
            run.mkdir()
            self.assertIsNone(M.relaunch_spec(run))


class LePlan(unittest.TestCase):
    BASE = {"admin": "ok", "sudo": True, "busy": None, "admin_children": 0,
            "reboot_required": False, "hermes_processes": 0}

    def _plan(self, policy="auto", **kw):
        st = dict(self.BASE)
        st.update(kw)
        return M.plan_for(st, policy)

    def test_rien_ne_tourne(self):
        plan = self._plan()
        self.assertEqual((plan["blocked"], plan["stop"], plan["reboot"]), (None, None, False))

    def test_les_reports(self):
        for kw, motif in (
            ({"admin": "injoignable: x"}, "admin injoignable"),
            ({"sudo": False}, "sudo"),
            ({"busy": {"run_id": "r", "kind": "data_entry_by_urls_submit", "source": "admin"}},
             "data_entry_by_urls_submit"),
            ({"busy": {"run_id": "r", "kind": "data_entry_auto", "source": "cli"}}, "(cli)"),
            ({"admin_children": 2}, "sans run déclaré"),
            ({"chromium_held": False}, "Chromium n'est pas bloqué"),
        ):
            with self.subTest(motif):
                plan = self._plan(**kw)
                self.assertIn(motif, plan["blocked"] or "")
                self.assertIsNone(plan["stop"])

    def test_un_balayage_de_l_admin_est_arrete(self):
        plan = self._plan(busy={"run_id": "20260929-081658-auto", "kind": "data_entry_auto",
                                "source": "admin"}, admin_children=1)
        self.assertEqual(plan["stop"], "20260929-081658-auto")
        self.assertIsNone(plan["blocked"])

    def test_le_redemarrage(self):
        self.assertTrue(self._plan(reboot_required=True)["reboot"])
        never = self._plan("never", reboot_required=True)
        self.assertFalse(never["reboot"])
        self.assertIn("never", never["reboot_note"])
        hermes = self._plan(reboot_required=True, hermes_processes=4)
        self.assertFalse(hermes["reboot"])
        self.assertIn("hermes", hermes["reboot_note"])


def _recap_dir(tmp, current=None, loop_state=None, targets=None):
    run = pathlib.Path(tmp) / "20260930-100000-auto"
    run.mkdir(exist_ok=True)
    if targets is None:
        targets = [{"merchant": "CJS-CDKeys", "store_id": "30", "recap": {"current": current}}]
    (run / "recap.json").write_text(json.dumps({"targets": targets}), encoding="utf-8")
    if loop_state is not None:
        (run / "loop.json").write_text(json.dumps({"loop": True, "state": loop_state}), encoding="utf-8")
    return run


class LeMomentSur(unittest.TestCase):
    """Revue adverse du 30/09 (P0) : « Arrêter » a une grâce fixe (75 s pour la saisie d'une page,
    120 s pour le balayage) — demandé en pleine saisie, il peut tuer une offre entre le clic et sa
    preuve. La maintenance n'arrête donc QUE hors écriture."""

    def test_les_etapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for current, attendu in ((None, True), ({"stage": "extract"}, True),
                                     ({"stage": "match"}, False), ({"stage": "pause"}, True),
                                     ({"stage": "probe"}, True), ({"stage": "submit", "page": 7}, False),
                                     ({"stage": "move"}, False), ({"stage": "inconnue"}, False)):
                with self.subTest(current):
                    self.assertEqual(M.safe_to_stop(_recap_dir(tmp, current))[0], attendu)

    def test_boucle_en_pause_et_recap_illisible(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _recap_dir(tmp, {"stage": "submit"}, loop_state="pause")
            self.assertTrue(M.safe_to_stop(run)[0])
            vide = pathlib.Path(tmp) / "vide"
            vide.mkdir()
            self.assertFalse(M.safe_to_stop(vide)[0], "illisible = pas sûr")

    def test_jamais_d_arret_pendant_la_saisie(self):
        appels = []
        with tempfile.TemporaryDirectory() as tmp:
            run = _recap_dir(tmp, {"stage": "submit", "page": 9})
            ok, why = M.stop_and_wait("r", timeout=60, run_dir=run,
                                      admin=lambda p, b=None: appels.append(p) or {"busy": None},
                                      runner=lambda *a, **k: _cp(0, "0"), sleep=lambda s: None)
        self.assertFalse(ok)
        self.assertNotIn("/api/sort/stop", appels, "aucun arrêt demandé en pleine saisie")
        self.assertIn("rien n'a été arrêté", why)


class LArret(unittest.TestCase):
    def _runner(self, enfants):
        suite = iter(enfants)

        def runner(cmd, timeout=0):
            if cmd[:2] == ["systemctl", "show"]:
                return _cp(0, "1234\n")
            if cmd[:2] == ["pgrep", "-P"]:
                return _cp(0, "\n".join(str(9000 + i) for i in range(next(suite))))
            return _cp(1)
        return runner

    def test_arrete_puis_plus_d_enfant(self):
        appels = []

        def admin(path, body=None):
            appels.append(path)
            if path == "/api/sort/stop":
                return {"stopped": "r"}
            return {"busy": {"run_id": "r"}} if appels.count("/api/sort/runs") < 3 else {"busy": None}

        with tempfile.TemporaryDirectory() as tmp:
            ok, why = M.stop_and_wait("r", timeout=300, runner=self._runner([1, 1, 0, 0]),
                                      admin=admin, sleep=lambda s: None,
                                      run_dir=_recap_dir(tmp, {"stage": "extract"}))
        self.assertTrue(ok, why)
        self.assertEqual(appels[0], "/api/sort/stop")

    def test_toujours_actif_rien_d_autre(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, why = M.stop_and_wait("r", timeout=30, runner=self._runner([1] * 10),
                                      admin=lambda p, b=None: {"busy": {"run_id": "r"}},
                                      sleep=lambda s: None, run_dir=_recap_dir(tmp, None))
        self.assertFalse(ok)
        self.assertIn("rien d'autre", why)


class CeQuiResteApresLArret(unittest.TestCase):
    """Revue adverse du 30/09 (P1) : les marchands AJOUTÉS au balayage par la console ne sont pas
    dans le lancement — la relance se lit dans le recap FINAL."""

    def test_le_marchand_interrompu_puis_ceux_jamais_atteints(self):
        recap = {"targets": [
            {"merchant": "Gamivo", "store_id": "51", "recap": {"halted": None}},
            {"merchant": "CJS-CDKeys", "store_id": "30", "recap": {"halted": "operator_stop"}}],
            "targets_not_reached": [{"merchant": "Gamerall", "store_id": "13"},
                                    {"merchant": "K4G", "store_id": "92"}]}   # K4G : ajouté
        self.assertEqual([t["merchant"] for t in M.remaining_after_stop(recap)],
                         ["CJS-CDKeys", "Gamerall", "K4G"])

    def test_un_arret_entre_deux_marchands(self):
        recap = {"targets": [{"merchant": "Gamivo", "store_id": "51", "recap": {"halted": None}}],
                 "targets_not_reached": [{"merchant": "Eneba", "store_id": "19"}]}
        self.assertEqual(M.remaining_after_stop(recap), [{"merchant": "Eneba", "store_id": "19"}])

    def test_forme_inconnue(self):
        self.assertIsNone(M.remaining_after_stop(None))
        self.assertIsNone(M.remaining_after_stop({"x": 1}))


class LeRedemarrageEstReluJusteAvant(unittest.TestCase):
    """Revue adverse du 30/09 (P0) : décidé sur l'état d'AVANT apt, le redémarrage aurait coupé un
    run relancé pendant la mise à jour — ou manqué un redémarrage devenu nécessaire."""

    def _runner(self, hermes=""):
        def runner(cmd, timeout=0):
            if cmd[:2] == ["systemctl", "show"]:
                return _cp(0, "1234")
            if cmd[:2] == ["pgrep", "-P"]:
                return _cp(1, "")
            if cmd[:3] == ["pgrep", "-u", "hermes"]:
                return _cp(0 if hermes else 1, hermes)
            if cmd[:2] == ["systemctl", "is-enabled"]:
                return _cp(0, "enabled\n")
            return _cp(0)
        return runner

    def test_les_cas(self):
        libre = lambda p, b=None: {"busy": None}             # noqa: E731
        occupe = lambda p, b=None: {"busy": {"run_id": "x"}}  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            requis = pathlib.Path(tmp) / "reboot-required"
            with mock.patch.object(M, "REBOOT_REQUIRED", requis):
                self.assertFalse(M.reboot_decision("auto", False, runner=self._runner(), admin=libre)[0])
                requis.write_text("*** System restart required ***")
                self.assertTrue(M.reboot_decision("auto", False, runner=self._runner(), admin=libre)[0])
                self.assertFalse(M.reboot_decision("never", False, runner=self._runner(), admin=libre)[0])
                ok, why = M.reboot_decision("auto", False, runner=self._runner(), admin=occupe)
                self.assertFalse(ok)
                self.assertIn("entre-temps", why)
                self.assertFalse(M.reboot_decision("auto", False, runner=self._runner("4242"), admin=libre)[0])
                self.assertTrue(M.reboot_decision("auto", True, runner=self._runner("4242"), admin=libre)[0])


class LaRelanceSeLitDansLeRecapFinal(unittest.TestCase):
    def test_cmd_run_relance_le_marchand_interrompu_et_l_ajout(self):
        vu = {}
        with tempfile.TemporaryDirectory() as tmp:
            racine = pathlib.Path(tmp)
            (racine / "runs" / "r").mkdir(parents=True)
            (racine / "runs" / "r" / "recap.json").write_text(json.dumps({
                "targets": [{"merchant": "Gamivo", "store_id": "51", "recap": {"halted": None}},
                            {"merchant": "Eneba", "store_id": "19", "recap": {"halted": "operator_stop"}}],
                "targets_not_reached": [{"merchant": "K4G", "store_id": "92"}]}), encoding="utf-8")

            def fin(relaunch, context):
                vu["relaunch"] = relaunch
                return 0, {"exit": 0}
            with mock.patch.object(M, "STATE_DIR", racine / "state"), \
                    mock.patch.object(M, "ROOT", racine), \
                    mock.patch.object(M, "status", return_value={"host": "h", "boot_id": "b"}), \
                    mock.patch.object(M, "plan_for", return_value={"blocked": None, "stop": "r",
                                                                   "reboot": False}), \
                    mock.patch.object(M, "relaunch_spec", return_value={
                        "targets": [{"merchant": "Gamivo", "store_id": "51"},
                                    {"merchant": "Eneba", "store_id": "19"}], "loop": False}), \
                    mock.patch.object(M, "stop_and_wait", return_value=(True, "arrêté")), \
                    mock.patch.object(M, "apt_upgrade", return_value=(True, "à jour")), \
                    mock.patch.object(M, "reboot_decision", return_value=(False, "pas requis")), \
                    mock.patch.object(M, "finish", side_effect=fin), \
                    mock.patch.object(M.signal, "signal"):
                code = M.cmd_run(M.argparse.Namespace(dry_run=False, reboot="auto", allow_hermes=False,
                                                     stop_timeout=60, pull=False))
        self.assertEqual(code, 0)
        self.assertEqual([t["merchant"] for t in vu["relaunch"]["targets"]], ["Eneba", "K4G"])


class LeDnsDoitSurvivreAuRedemarrage(unittest.TestCase):
    """2026-09-30, ancienne VM : resolv.conf → /run/resolvconf/…, resolvconf.service désactivé —
    après le redémarrage, plus de DNS, AKS injoignable, rien relancé."""

    def _avec(self, cible, etat):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lien = pathlib.Path(tmp.name) / "resolv.conf"
        lien.symlink_to(cible)
        p = mock.patch.object(M, "RESOLV_CONF", lien)
        p.start()
        self.addCleanup(p.stop)
        return lambda cmd, timeout=0: _cp(0 if etat == "enabled" else 1, etat + "\n")

    def test_resolvconf_desactive_interdit_le_redemarrage(self):
        runner = self._avec("/run/resolvconf/resolv.conf", "disabled")
        ok, why = M.dns_survives_reboot(runner)
        self.assertFalse(ok)
        self.assertIn("resolvconf", why)
        with tempfile.TemporaryDirectory() as tmp:
            requis = pathlib.Path(tmp) / "reboot-required"
            requis.write_text("x")
            with mock.patch.object(M, "REBOOT_REQUIRED", requis):
                ok, why = M.reboot_decision("auto", False, runner=runner,
                                            admin=lambda p, b=None: {"busy": None})
        self.assertFalse(ok)
        self.assertIn("DNS", why)

    def test_les_bons_cas(self):
        self.assertTrue(M.dns_survives_reboot(self._avec("/run/resolvconf/resolv.conf", "enabled"))[0])
        self.assertTrue(M.dns_survives_reboot(self._avec("/run/systemd/resolve/resolv.conf", "enabled"))[0])

    def test_le_plan_le_dit(self):
        plan = M.plan_for({"admin": "ok", "sudo": True, "busy": None, "admin_children": 0,
                           "reboot_required": True, "hermes_processes": 0, "dns_boot_ok": False,
                           "dns_boot": "resolvconf n'est pas activé"}, "auto")
        self.assertFalse(plan["reboot"])
        self.assertIn("resolvconf", plan["reboot_note"])


class ReAuditDu0110(unittest.TestCase):
    """Ré-audit de 2272e92 (Romain, 01/10) : cinq défauts confirmés, chacun épinglé ici."""

    def test_p1_le_matching_n_est_plus_un_moment_sur(self):
        # « match » précède la saisie : il peut basculer en `submit` entre la lecture et l'arrêt.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(M.safe_to_stop(_recap_dir(tmp, {"stage": "match"}))[0])
            self.assertTrue(M.safe_to_stop(_recap_dir(tmp, {"stage": "extract"}))[0])

    def test_p1_bascule_vers_l_ecriture_signalee_apres_l_arret(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _recap_dir(tmp, {"stage": "extract"})
            etats = iter([{"busy": None}])

            def admin(path, body=None):
                if path == "/api/sort/stop":
                    # pendant la demande, l'étape bascule en saisie
                    (run / "recap.json").write_text(json.dumps({"targets": [{"merchant": "K4G",
                        "recap": {"current": {"stage": "submit", "page": 2}}}]}), encoding="utf-8")
                    return {"stopped": True}
                return next(etats, {"busy": None})
            ok, why = M.stop_and_wait("r", timeout=30, run_dir=run, admin=admin,
                                      runner=lambda cmd, timeout=0: _cp(0, "1234") if cmd[:2] == ["systemctl", "show"] else _cp(1, ""),
                                      sleep=lambda s: None)
        self.assertTrue(ok)
        self.assertIn("ATTENTION", why)

    def test_p1_le_redemarrage_tient_le_verrou_du_navigateur(self):
        from src.browser_lock import browser_lock
        args = M.argparse.Namespace(reboot="auto", allow_hermes=False)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(M, "ROOT", pathlib.Path(tmp)), \
                mock.patch.object(M, "STATE_DIR", pathlib.Path(tmp) / "state" / "maintenance"), \
                mock.patch.object(M, "reboot_decision", return_value=(True, "requis")) as dec, \
                mock.patch.object(M, "install_postboot_unit", return_value=(True, "ok")), \
                mock.patch.object(M, "schedule_reboot", return_value=(True, "")) as rb:
            # un run tient déjà le navigateur → aucun redémarrage, motif nommé
            with browser_lock(pathlib.Path(tmp), label="run en cours"):
                ctx = {}
                self.assertIsNone(M.reboot_under_lock(args, ctx, None, sleep=lambda s: None))
            self.assertIn("navigateur tenu", ctx["reboot"])
            rb.assert_not_called()
            dec.assert_not_called()
            # navigateur libre → contrôle ET redémarrage sous le verrou
            ctx = {}
            self.assertEqual(M.reboot_under_lock(args, ctx, None, sleep=lambda s: None), M.EXIT_REBOOT)
            rb.assert_called_once()

    def test_p2_une_boucle_garde_ses_ajouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch = pathlib.Path(tmp) / "20261001-100000-auto"
            launch.mkdir()
            passe = pathlib.Path(tmp) / "20261001-100000-auto-pass2"
            passe.mkdir()
            (launch / "loop.json").write_text(json.dumps({"loop": True, "current_run_id": passe.name}))
            (passe / "recap.json").write_text(json.dumps({
                "planned": [{"merchant": "GOG", "store_id": "34"}, {"merchant": "K4G", "store_id": "92"}],
                "targets_refused": [{"merchant": "Difmark", "store_id": "167"}]}))
            (launch / "targets_queue.json").write_text(json.dumps([
                {"merchant": "Wyrel", "store_id": "162"}, {"merchant": "Difmark", "store_id": "167"}]))
            out = M.loop_targets([{"merchant": "GOG", "store_id": "34"}], launch)
        self.assertEqual([t["merchant"] for t in out], ["GOG", "K4G", "Wyrel"])

    def test_p2_processus_illisibles_pas_de_redemarrage(self):
        with tempfile.TemporaryDirectory() as tmp:
            requis = pathlib.Path(tmp) / "reboot-required"
            requis.write_text("x")

            def runner(cmd, timeout=0):
                if cmd[:2] == ["systemctl", "is-enabled"]:
                    return _cp(0, "enabled\n")
                if cmd[:2] == ["systemctl", "show"]:
                    return _cp(1, "")            # MainPID illisible
                return _cp(1, "")
            with mock.patch.object(M, "REBOOT_REQUIRED", requis):
                ok, why = M.reboot_decision("auto", False, runner=runner,
                                            admin=lambda p, b=None: {"busy": None})
        self.assertFalse(ok)
        self.assertIn("illisibles", why)

    def test_p2_enabled_runtime_n_est_pas_une_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            lien = pathlib.Path(tmp) / "resolv.conf"
            lien.symlink_to("/run/resolvconf/resolv.conf")
            with mock.patch.object(M, "RESOLV_CONF", lien):
                for etat, actif, attendu in (("enabled-runtime", 0, False), ("static", 1, False),
                                             ("static", 0, True), ("enabled", 1, True)):
                    def runner(cmd, timeout=0, etat=etat, actif=actif):
                        if cmd[:2] == ["systemctl", "is-enabled"]:
                            return _cp(0 if etat == "enabled" else 1, etat + "\n")
                        return _cp(actif, "")
                    with self.subTest(etat=etat, actif=actif):
                        self.assertEqual(M.dns_survives_reboot(runner)[0], attendu)


class UnePanneApresLArretNEstJamaisMuette(unittest.TestCase):
    def test_code_7_resultat_ecrit_et_discord(self):
        messages = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(M, "STATE_DIR", pathlib.Path(tmp)), \
                mock.patch.object(M, "ROOT", pathlib.Path(tmp)), \
                mock.patch.object(M, "status", return_value={"host": "h", "boot_id": "b"}), \
                mock.patch.object(M, "plan_for", return_value={"blocked": None, "stop": "r",
                                                               "reboot": False}), \
                mock.patch.object(M, "relaunch_spec", return_value={"targets": [{"merchant": "K4G",
                                                                                  "store_id": "92"}],
                                                                     "loop": False}), \
                mock.patch.object(M, "stop_and_wait", return_value=(True, "arrêté")), \
                mock.patch.object(M, "apt_upgrade", side_effect=OSError("disque plein")), \
                mock.patch.object(M, "notify", side_effect=messages.append), \
                mock.patch.object(M.signal, "signal"):
            args = M.argparse.Namespace(dry_run=False, reboot="auto", allow_hermes=False,
                                        stop_timeout=60, pull=False)
            code = M.cmd_run(args)
            last = json.loads((pathlib.Path(tmp) / M.LAST).read_text())
        self.assertEqual(code, M.EXIT_CRASH)
        self.assertEqual(last["exit"], M.EXIT_CRASH)
        self.assertIn("disque plein", last["error"])
        self.assertIn("rien n'a été relancé", messages[-1])


class LaFin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(M, "STATE_DIR", pathlib.Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        n = mock.patch.object(M, "notify", lambda text: self.messages.append(text))
        n.start()
        self.addCleanup(n.stop)
        self.messages = []

    def _runner(self, invariants_ok=True):
        rapport = {"ok": invariants_ok, "authoritative": True,
                   "checks": [{"name": "aks_direct_status", "ok": invariants_ok}]}

        def runner(cmd, timeout=0):
            if cmd[:2] == ["systemctl", "cat"] or cmd[:2] == ["systemctl", "is-active"]:
                return _cp(0)
            if cmd[-1].endswith("01_check_invariants.py"):
                return _cp(0 if invariants_ok else 1, json.dumps(rapport))
            return _cp(0)
        return runner

    def _admin(self, busy=None):
        self.posts = []

        def admin(path, body=None):
            if body is not None:
                self.posts.append((path, body))
                return {"started": True, "run_id": "20260930-120000-auto"}
            return {"busy": busy}
        return admin

    def test_tout_prouve_la_relance_part(self):
        spec = {"targets": [{"merchant": "K4G", "store_id": "92"}], "confirm": "GO"}
        code, res = M.finish(spec, context={"host": "h"}, runner=self._runner(),
                             admin=self._admin(), session_check=lambda: (True, "connectée"),
                             sleep=lambda s: None)
        self.assertEqual(code, M.EXIT_OK)
        self.assertEqual(self.posts, [("/api/data-entry/auto", spec)])
        self.assertEqual(res["relaunched"], "20260930-120000-auto")
        self.assertEqual(json.loads((M.STATE_DIR / M.LAST).read_text())["exit"], 0)

    def test_session_perdue_aucune_relance(self):
        code, res = M.finish({"targets": []}, context={"host": "h"}, runner=self._runner(),
                             admin=self._admin(), session_check=lambda: (False, "NON connectée"),
                             sleep=lambda s: None)
        self.assertEqual(code, M.EXIT_CHECKS)
        self.assertEqual(self.posts, [])
        self.assertIn("NON", res["relaunched"])
        self.assertIn("NON connectée", self.messages[-1])

    def test_invariants_rouges_aucune_relance_ni_session(self):
        vu = []
        code, _ = M.finish({"targets": []}, context={"host": "h"},
                           runner=self._runner(invariants_ok=False), admin=self._admin(),
                           session_check=lambda: vu.append(1) or (True, "x"), sleep=lambda s: None)
        self.assertEqual(code, M.EXIT_CHECKS)
        self.assertEqual((self.posts, vu), ([], []))

    def test_un_run_deja_en_cours_n_est_pas_double(self):
        code, res = M.finish({"targets": []}, context={"host": "h"}, runner=self._runner(),
                             admin=self._admin(busy={"run_id": "autre"}),
                             session_check=lambda: (True, "ok"), sleep=lambda s: None)
        self.assertEqual(self.posts, [])
        self.assertIn("déjà", res["relaunched"])

    def test_postboot_sans_maintenance_ne_fait_rien(self):
        with mock.patch.object(M, "finish") as fin:
            self.assertEqual(M.cmd_postboot(None), M.EXIT_OK)
        fin.assert_not_called()

    def test_postboot_retire_le_fichier_quoi_qu_il_arrive(self):
        M.write_json(M.STATE_DIR / M.PENDING, {"context": {"host": "h", "boot_id_before": "a"},
                                               "relaunch": None})
        with mock.patch.object(M, "finish", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                M.cmd_postboot(None)
        self.assertFalse((M.STATE_DIR / M.PENDING).exists(), "une seule tentative par maintenance")


class LeServiceDeDemarrage(unittest.TestCase):
    def test_le_fichier_unit(self):
        unit = (ROOT / "ops" / "aks-maint-postboot.service").read_text(encoding="utf-8")
        for attendu in ("User=debian", "Type=oneshot",
                        "ConditionPathExists=/home/debian/executor/state/maintenance/pending.json",
                        "18_vps_maintenance.py postboot", "After=network-online.target aks-admin.service"):
            self.assertIn(attendu, unit)


class LePilote(unittest.TestCase):
    def test_la_machine_locale_toujours_en_dernier(self):
        hosts = [{"name": "cette-vm", "ssh": None}, {"name": "a", "ssh": "x@a"}, {"name": "b", "ssh": "x@b"}]
        self.assertEqual([h["name"] for h in P.ordered(hosts, [], [])], ["a", "b", "cette-vm"])
        self.assertEqual([h["name"] for h in P.ordered(hosts, ["cette-vm", "b"], [])], ["b", "cette-vm"])
        self.assertEqual([h["name"] for h in P.ordered(hosts, [], ["a"])], ["b", "cette-vm"])

    def test_le_secours_ne_redemarre_jamais_par_defaut(self):
        secours = next(h for h in P.HOSTS if h["name"] == "secours")
        self.assertIn("--reboot never", P.agent_args(secours, dry_run=False, reboot_secours=False,
                                                     allow_hermes=False))
        self.assertIn("--reboot auto", P.agent_args(secours, dry_run=False, reboot_secours=True,
                                                    allow_hermes=False))
        self.assertEqual(P.HOSTS[-1]["ssh"], None, "la machine qui pilote est la dernière déclarée")

    def test_a_blanc_par_defaut_sans_pull(self):
        vus = []

        def runner(cmd, timeout=0):
            vus.append(cmd[-1])
            return _cp(0, json.dumps({"dry_run": True, "plan": {"blocked": None}}))
        with mock.patch.object(P, "notify") as notif:
            code = P.main(["--only", "ancienne-vm"], runner=runner, sleep=lambda s: None)
        self.assertEqual(code, 0)
        self.assertTrue(all("git" not in c for c in vus), vus)
        self.assertTrue(any("--dry-run" in c for c in vus), vus)
        notif.assert_not_called()

    def test_un_vps_qui_ne_revient_pas_arrete_la_suite(self):
        vus = []

        def runner(cmd, timeout=0):
            vus.append(cmd)
            dernier = cmd[-1]
            if "git" in dernier:
                return _cp(0)
            if "boot_id" in dernier:
                return _cp(0, "ancien\n")         # jamais redémarré
            if "run --reboot" in dernier:
                return _cp(42, json.dumps({"rebooting": True, "context": {"boot_id_before": "ancien"}}))
            return _cp(0, "{}")
        with mock.patch.object(P, "notify"):
            code = P.main(["--apply", "--only", "ancienne-vm", "--only", "cette-vm"],
                          runner=runner, sleep=lambda s: None)
        self.assertEqual(code, 1)
        self.assertTrue(all(c[0] == "ssh" for c in vus),
                        "la machine suivante (cette-vm) ne doit pas être touchée")

    def test_le_retour_d_un_vps_redemarre(self):
        etat = {"boot": 0}

        def runner(cmd, timeout=0):
            dernier = cmd[-1]
            if "boot_id" in dernier:
                etat["boot"] += 1
                return _cp(0, "ancien\n" if etat["boot"] < 3 else "nouveau\n")
            if dernier.endswith(" status"):
                return _cp(0, json.dumps({"pending": False, "last_result": {"boot_id": "nouveau", "exit": 0}}))
            return _cp(0)
        host = {"name": "ancienne-vm", "ssh": "debian@x"}
        res = P.wait_for_return(host, "ancien", runner=runner, key="k", sleep=lambda s: None)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["result"]["boot_id"], "nouveau")

    def test_la_machine_locale_qui_redemarre_arrete_le_pilote(self):
        def runner(cmd, timeout=0):
            if "git" in cmd[-1]:
                return _cp(0)
            return _cp(42, json.dumps({"rebooting": True, "context": {"boot_id_before": "a"}}))
        with mock.patch.object(P, "notify"):
            code = P.main(["--apply", "--only", "cette-vm"], runner=runner, sleep=lambda s: None)
        self.assertEqual(code, 42)

    def test_un_vps_reporte_n_arrete_pas_la_suite(self):
        vus = []

        def runner(cmd, timeout=0):
            vus.append(cmd)
            if "git" in cmd[-1]:
                return _cp(0)
            return _cp(3, json.dumps({"plan": {"blocked": "run data_entry_by_urls_submit en cours"}}))
        with mock.patch.object(P, "notify"):
            code = P.main(["--apply", "--only", "secours", "--only", "ancienne-vm"],
                          runner=runner, sleep=lambda s: None)
        self.assertEqual(code, 0)
        cibles = {c[-2] for c in vus if c[0] == "ssh"}
        self.assertEqual(cibles, {"debian@169.58.5.63", "debian@51.38.37.254"})

    def test_script_absent_reporte_sans_arreter_la_suite(self):
        with mock.patch.object(P, "notify"):
            code = P.main(["--apply", "--only", "ancienne-vm"], runner=lambda cmd, timeout=0: _cp(127),
                          sleep=lambda s: None)
        self.assertEqual(code, 0)

    def test_une_panne_sans_json_arrete_la_chaine(self):
        vus = []

        def runner(cmd, timeout=0):
            vus.append(cmd)
            return _cp(1, "", "Traceback …")
        with mock.patch.object(P, "notify"):
            code = P.main(["--apply", "--only", "secours", "--only", "ancienne-vm"],
                          runner=runner, sleep=lambda s: None)
        self.assertEqual(code, 1)
        self.assertEqual(len(vus), 1, "le VPS suivant n'est pas touché")

    def test_le_pilote_ne_tire_jamais_le_code_lui_meme(self):
        vus = []

        def runner(cmd, timeout=0):
            vus.append(cmd[-1])
            return _cp(0, json.dumps({"host": "h", "exit": 0}))
        with mock.patch.object(P, "notify"):
            P.main(["--apply", "--only", "ancienne-vm"], runner=runner, sleep=lambda s: None)
        self.assertTrue(all("git" not in c for c in vus), vus)
        self.assertTrue(vus[0].endswith("--pull"), "l'agent tire APRÈS l'arrêt")

    def test_ssh_coupe_par_le_redemarrage_vaut_42(self):
        # Le redémarrage est immédiat : ssh peut finir en 255 après avoir imprimé « rebooting ».
        def runner(cmd, timeout=0):
            return _cp(255, json.dumps({"rebooting": True, "context": {"boot_id_before": "a"}}))
        with mock.patch.object(P, "notify"):
            code = P.main(["--apply", "--only", "cette-vm"], runner=runner, sleep=lambda s: None)
        self.assertEqual(code, 42)

    def test_vps_inconnu(self):
        self.assertEqual(P.main(["--only", "nulle-part"], runner=lambda *a, **k: _cp(0)), 2)


if __name__ == "__main__":
    unittest.main()
