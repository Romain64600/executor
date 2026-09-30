"""L'onglet « Vue d'ensemble » des VPS (Romain, 2026-09-30 : « Go pour l'onglet vue d'ensemble »).

Deux moitiés, toutes deux sans réseau ni machine réelle :

* la PHOTO d'une machine (``src/vps_snapshot.py``) sur des dossiers de run fabriqués — balayage
  de groupe en boucle, boucle en pause, saisie par page, rien en cours, maintenance, run lancé au
  terminal quand l'admin ne répond pas —, le filtre des secrets du journal et les alertes ;
* la route ``GET /api/overview`` (``src/admin/overview.py``) avec un faux ssh : machine UP,
  délai dépassé, JSON illisible, cache de 10 s, configuration invalide, et la route est en
  LECTURE SEULE (un POST ne fait rien, aucun ssh ne part).
"""

from __future__ import annotations

import http.server
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from src import vps_snapshot
from src.admin import overview as ov
from src.merchant_groups import group_targets
from tests.test_admin_app import AppTestCase

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = "20260930-080000-auto"


def fake_runner(calls=None, *, git_ok=True, services=None):
    """Répond à ``git log`` et ``systemctl show`` comme une machine saine."""

    services = services or {"aks-admin": ("loaded", "active"), "aks-chromium": ("loaded", "active"),
                            "hermes-cdp-proxy": ("not-found", "inactive"),
                            "nginx": ("loaded", "active")}

    def run(cmd, timeout=None):
        if calls is not None:
            calls.append(list(cmd))
        if cmd[0] == "git":
            if not git_ok:
                return subprocess.CompletedProcess(cmd, 128, "", "fatal: not a git repository")
            return subprocess.CompletedProcess(
                cmd, 0, "2272e92\t2026-09-30T16:33:30+02:00\tHEAD -> main, origin/main\tfix: maintenance\n", "")
        if cmd[0] == "systemctl":
            blocks = [f"Id={n}.service\nLoadState={ls}\nActiveState={st}"
                      for n, (ls, st) in services.items()]
            return subprocess.CompletedProcess(cmd, 0, "\n\n".join(blocks) + "\n", "")
        return subprocess.CompletedProcess(cmd, 127, "", "inconnu")

    return run


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runs = self.root / "runs"
        self.logs = self.root / "logs"
        self.proc = self.root / "proc"
        for d in (self.runs, self.logs, self.proc / "sys" / "kernel" / "random", self.root / "state"):
            d.mkdir(parents=True)
        (self.proc / "uptime").write_text("90061.5 100.0\n")
        (self.proc / "meminfo").write_text("MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n")
        (self.proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-1\n")
        self.reboot = self.root / "reboot-required"

    # -- fabriques ---------------------------------------------------------------------
    def write(self, rel, obj):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
        return path

    def log(self, run_id, *records):
        with open(self.logs / f"{run_id}.jsonl", "a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(dict({"run_id": run_id}, **rec)) + "\n")

    def proc_cmd(self, pid, *args):
        d = self.proc / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")

    def snap(self, busy=None, *, reachable=True, runner=None, probe=None):
        return vps_snapshot.snapshot(
            self.root, runner=runner or fake_runner(), proc_root=self.proc,
            reboot_flag=self.reboot, hostname="test-vm",
            admin_probe=probe or (lambda: {"reachable": reachable, "busy": busy,
                                           "error": None if reachable else "refusé"}))

    def group_a_sweep(self, *, state="running", pass_no=3, current=True, halted=None,
                      offers_created=None, admin=True, admin_pid=None):
        names = group_targets("A")
        if admin:
            # `SubmitManager._spawn` l'écrit, avec le pid de l'enfant (= celui du marqueur)
            launch = {"state": "running", "kind": "data_entry_auto",
                      "started_at": "2026-09-30T08:00:00Z",
                      "targets": [{"merchant": m, "store_id": s} for m, s in names], "loop": True,
                      "list_id": 9}
            if admin_pid is not None:
                launch["pid"] = admin_pid
            self.write(f"runs/{LAUNCH}/admin_submit.json", launch)
        pass_id = f"{LAUNCH}-pass{pass_no}"
        self.write(f"runs/{LAUNCH}/loop.json", {
            "run_id": LAUNCH, "loop": True, "state": state, "pass": pass_no,
            "current_run_id": pass_id, "started_at": "2026-09-30T08:00:00Z",
            "next_pass_at": "2026-09-30T15:35:00Z" if state == "pause" else None,
            "targets": [{"merchant": m, "store_id": s} for m, s in names],
            "passes": [], "totals": {"created": 1553, "passes_finished": pass_no - 1},
            "stopped_reason": None, "stopped_label": None})
        page_run = f"{pass_id}-gog-s34-p12"
        gog = {"merchant": "GOG", "store_id": "34", "started_at": "2026-09-30T13:00:00Z",
               "recap": {"pages": [], "total_created": 0,
                         "current": ({"page": 12, "run": page_run, "stage": "submit",
                                      "since": "2026-09-30T13:50:00Z",
                                      "stage_at": "2026-09-30T14:03:00Z", "approved": 20}
                                     if current else None)}}
        seal = {"merchant": "GameSeal", "store_id": "126",
                "recap": {"total_created": 40, "halted": halted,
                          "pages": [{"page": 1, "run": f"{pass_id}-gameseal-s126-p1", "created": 40,
                                     "offers_created": offers_created or []}]}}
        recap = {"run_id": pass_id, "started_at": "2026-09-30T12:00:00Z", "targets": [seal, gog],
                 "halted": None, "halted_merchants": [f"GameSeal: {halted}"] if halted else [],
                 "total_created": 40, "loop_pass": pass_no, "launch_run_id": LAUNCH}
        if state == "pause":
            recap["finished_at"] = "2026-09-30T15:05:00Z"
        self.write(f"runs/{pass_id}/recap.json", recap)
        return pass_id, page_run


class SnapshotClassificationTests(SnapshotCase):
    def test_rien_en_cours(self):
        s = self.snap(None)
        self.assertEqual(s["task"]["type"], "aucune")
        self.assertEqual(s["task"]["label"], "Rien en cours")
        self.assertEqual(s["logs"], [])
        self.assertEqual(s["alerts"], [])
        self.assertEqual(s["host"], "test-vm")
        self.assertEqual(s["code"]["sha"], "2272e92")
        self.assertEqual(s["services"]["hermes-cdp-proxy"], "absent")
        self.assertEqual(s["uptime_s"], 90061)
        self.assertEqual(s["boot_id"], "boot-1")
        self.assertEqual(s["mem"]["used_pct"], 50.0)
        json.dumps(s)          # sérialisable tel quel

    def test_balayage_de_groupe_en_boucle_dit_passe_marchand_page_etape(self):
        pass_id, page_run = self.group_a_sweep()
        self.log(page_run,
                 {"ts": "2026-09-30T14:00:00Z", "event": "match_progress", "done": 5, "total": 100, "candidates": 1},
                 {"ts": "2026-09-30T14:01:00Z", "event": "match_progress", "done": 100, "total": 100, "candidates": 20},
                 {"ts": "2026-09-30T14:03:10Z", "event": "pacing", "pages": None},
                 {"ts": "2026-09-30T14:04:00Z", "event": "submit_offer", "offer_id": "7", "success": True},
                 {"ts": "2026-09-30T14:05:00Z", "event": "guard_snapshot", "guard": {"x": 1}},
                 {"ts": "2026-09-30T14:05:30Z", "event": "modal_ctx_render_wait", "waited_s": 1},
                 {"ts": "2026-09-30T14:06:00Z", "event": "submit_offer", "offer_id": "8", "success": True})
        s = self.snap({"run_id": LAUNCH, "kind": "data_entry_auto", "source": "admin"})
        t = s["task"]
        self.assertEqual(t["type"], "balayage")
        self.assertEqual(t["label"],
                         "Balayage groupe A en boucle — passe 3, GOG page 12, saisie depuis 14:03 UTC")
        self.assertEqual(t["group"], "A")
        self.assertTrue(t["loop"])
        self.assertEqual(t["pass_run_id"], pass_id)
        self.assertEqual(t["current"]["merchant"], "GOG")
        self.assertEqual(t["started_at"], "2026-09-30T08:00:00Z")
        # 1553 (passes finies) + 40 (pages finies de la passe) + 2 (page en cours, lues au journal)
        self.assertEqual(t["created"], {"total": 1595, "loop_finished_passes": 1553, "pass": 40, "page": 2})
        events = [it["event"] for it in s["logs"]]
        self.assertNotIn("guard_snapshot", events)
        self.assertNotIn("pacing", events)
        self.assertNotIn("modal_ctx_render_wait", events)
        self.assertEqual(events.count("match_progress"), 1, "seule la DERNIÈRE progression reste")
        self.assertEqual(s["logs"][0]["text"], "offre 8 : créée", "les plus récents d'abord")
        self.assertEqual(s["logs"][0]["merchant"], "GOG")
        self.assertEqual(s["logs"][0]["page"], 12)
        self.assertIn("matching 100/100 — 20 candidat(s)", [it["text"] for it in s["logs"]])
        self.assertNotIn("_recap", t)
        self.assertNotIn("_loop", t)

    def test_boucle_en_pause_ne_recompte_pas_la_passe_finie(self):
        self.group_a_sweep(state="pause", pass_no=2, current=False)
        s = self.snap({"run_id": LAUNCH, "kind": "data_entry_auto", "source": "admin"})
        t = s["task"]
        self.assertEqual(t["state"], "pause")
        self.assertEqual(t["label"], "Balayage groupe A en boucle — passe 2 finie, pause jusqu'à "
                                     "15:35 UTC (passe 3 ensuite)")
        self.assertEqual(t["created"]["total"], 1553, "en pause, la passe finie est déjà dans les totaux")
        self.assertIsNone(t["current"])

    def test_balayage_simple_de_quelques_marchands_entre_deux_pages(self):
        run = "20260930-090000-auto"
        self.write(f"runs/{run}/admin_submit.json", {
            "targets": [{"merchant": "Kinguin", "store_id": "58"}, {"merchant": "Eneba", "store_id": "19"}],
            "loop": False, "started_at": "2026-09-30T09:00:00Z"})
        self.write(f"runs/{run}/recap.json", {
            "run_id": run, "started_at": "2026-09-30T09:00:01Z", "total_created": 12,
            "halted_merchants": [], "targets": [{"merchant": "Kinguin", "recap": {
                "total_created": 12, "current": None,
                "pages": [{"page": 4, "run": f"{run}-kinguin-s58-p4", "created": 12}]}}]})
        self.log(f"{run}-kinguin-s58-p4", {"ts": "2026-09-30T09:40:00Z", "event": "feed_indexed", "offers": 90})
        s = self.snap({"run_id": run, "kind": "data_entry_auto", "source": "admin"})
        self.assertEqual(s["task"]["label"], "Balayage Kinguin, Eneba — Kinguin, entre deux pages")
        self.assertEqual(s["task"]["created"]["total"], 12)
        self.assertFalse(s["task"]["loop"])
        self.assertEqual(s["logs"][0]["text"], "feed indexé : 90 offre(s)",
                         "entre deux pages, le journal de la dernière page finie")

    def test_saisie_par_page_apercu_puis_saisie(self):
        run = "20260930-100000-by-urls"
        self.write(f"runs/{run}/recap.json", {"mode": "dry-run", "games": [{}, {}],
                                               "totals": {"games": 5, "resolved": 2, "candidates": 3}})
        self.log(run, {"ts": "2026-09-30T10:01:00Z", "event": "game_done", "url": "https://x/y"})
        s = self.snap({"run_id": run, "kind": "data_entry_by_urls", "source": "admin"})
        self.assertEqual(s["task"]["type"], "saisie_par_page")
        self.assertIn("Saisie par page — aperçu", s["task"]["label"])
        self.assertIn("2/5 page(s) lue(s), 3 candidat(s)", s["task"]["label"])
        self.assertEqual(s["logs"][0]["event"], "game_done")

        run2 = "20260930-101000-by-urls-submit"
        self.write(f"runs/{run2}/recap.json", {"mode": "submit", "totals": {"created": 7, "attempted": 8}})
        s = self.snap({"run_id": run2, "kind": "data_entry_by_urls_submit", "source": "admin"})
        self.assertIn("saisie réelle", s["task"]["label"])
        self.assertIn("7 créée(s)", s["task"]["label"])
        self.assertEqual(s["task"]["created"], {"total": 7})

    def test_tri_et_autres_runs_par_leur_nom(self):
        s = self.snap({"run_id": "20260930-sort", "kind": "sort_canary", "source": "admin"})
        self.assertEqual(s["task"]["type"], "tri")
        self.assertEqual(s["task"]["label"], "Tri des listes — canary (écriture)")
        s = self.snap({"run_id": "x", "kind": "catalog", "source": "cli"})
        self.assertEqual(s["task"]["type"], "autre")
        self.assertEqual(s["task"]["label"], "Catalogue AKS (lecture seule) (lancé au terminal)")
        s = self.snap({"run_id": "x", "kind": "mystere", "source": "admin"})
        self.assertEqual(s["task"]["label"], "Run « mystere »")

    def test_maintenance_en_attente_de_fin_apres_redemarrage(self):
        self.write("state/maintenance/pending.json", {"relaunch": None})
        s = self.snap(None)
        self.assertEqual(s["task"]["type"], "maintenance")
        self.assertIn("pending.json", s["task"]["label"])

    def test_maintenance_en_cours_vue_dans_les_processus(self):
        self.proc_cmd(4242, "python3", "/home/debian/executor/scripts/18_vps_maintenance.py", "run",
                      "--reboot", "auto")
        s = self.snap(None)
        self.assertEqual(s["task"]["type"], "maintenance")
        self.assertEqual(s["task"]["label"],
                         "Maintenance de cette machine en cours (arrêt sûr, apt, redémarrage si requis)")
        # pendant un balayage : la tâche reste le balayage, la maintenance est dite à côté
        self.group_a_sweep()
        s = self.snap({"run_id": LAUNCH, "kind": "data_entry_auto", "source": "admin"})
        self.assertEqual(s["task"]["type"], "balayage")
        self.assertIn("· maintenance de cette machine en cours", s["task"]["label"])

    def test_le_statut_lu_par_le_pilote_n_est_pas_une_maintenance(self):
        self.proc_cmd(4243, "python3", "/home/debian/executor/scripts/18_vps_maintenance.py", "status")
        self.assertEqual(self.snap(None)["task"]["type"], "aucune")
        self.proc_cmd(4244, "python3", "scripts/19_restart_vps.py", "--only", "secours")
        s = self.snap(None)
        self.assertEqual(s["task"]["label"], "Maintenance à blanc (lecture seule)")

    def test_admin_injoignable_le_marqueur_montre_le_run_lance_au_terminal(self):
        self.group_a_sweep(admin=False)
        (self.root / "state" / "active_run.json").write_text(json.dumps({
            "run_id": LAUNCH, "kind": "data_entry_auto", "source": "cli", "pid": os.getpid(),
            "started_at": "2026-09-30T08:00:00Z"}))
        # l'id de run du lancement dit « groupe A » par ses cibles ; la ligne de commande du
        # processus dit le groupe EXPLICITEMENT — elle l'emporte
        self.proc_cmd(os.getpid(), "python3", "scripts/10_data_entry_auto.py", "--group", "B", "--loop")
        s = self.snap(None, reachable=False)
        self.assertFalse(s["admin"]["reachable"])
        self.assertEqual(s["admin"]["busy"]["source"], "cli")
        self.assertEqual(s["task"]["group"], "B")
        self.assertTrue(s["task"]["label"].startswith("Balayage groupe B en boucle — passe 3"))
        self.assertTrue(s["task"]["label"].endswith("(lancé au terminal)"))

    def test_toute_la_liste_blanche(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        run = "20260930-110000-auto"
        self.write(f"runs/{run}/admin_submit.json", {
            "targets": [{"merchant": m, "store_id": s} for m, s in AUTO_MERCHANTS]})
        s = self.snap({"run_id": run, "kind": "data_entry_auto", "source": "admin"})
        self.assertTrue(s["task"]["label"].startswith("Balayage de toute la liste blanche — démarrage"))

    def test_un_id_de_run_hostile_ne_devient_jamais_un_chemin(self):
        self.write(f"runs/{LAUNCH}/loop.json", {"run_id": LAUNCH, "loop": True, "state": "running",
                                               "pass": 2, "current_run_id": "../../etc",
                                               "totals": {"created": 0}})
        self.write(f"runs/{LAUNCH}/recap.json", {"targets": [{"merchant": "GOG", "recap": {
            "current": {"page": 1, "run": "../../../etc/passwd", "stage": "extract"}}}]})
        s = self.snap({"run_id": LAUNCH, "kind": "data_entry_auto", "source": "admin"})
        self.assertEqual(s["task"]["type"], "balayage")
        json.dumps(s)
        s = self.snap({"run_id": "../x", "kind": "data_entry_auto", "source": "admin"})
        self.assertIn("introuvable", s["task"]["label"])


class SnapshotRobustnessTests(SnapshotCase):
    def test_ne_leve_jamais_et_dit_pourquoi(self):
        def cassé(cmd, timeout=None):
            raise RuntimeError("boum")

        def sonde():
            raise OSError("admin mort")

        s = vps_snapshot.snapshot(self.root / "absent", runner=cassé, proc_root=self.root / "rien",
                                  reboot_flag=self.reboot, admin_probe=sonde, hostname="h")
        self.assertIsNone(s["code"])
        self.assertIsNone(s["services"])
        self.assertIn("code", s["errors"])
        self.assertIn("services", s["errors"])
        self.assertIn("admin", s["errors"])
        self.assertFalse(s["admin"]["reachable"])
        self.assertEqual(s["task"]["type"], "aucune")
        json.dumps(s)

    def test_git_en_echec_est_une_erreur_nommee(self):
        s = self.snap(None, runner=fake_runner(git_ok=False))
        self.assertIsNone(s["code"])
        self.assertIn("not a git repository", s["errors"]["code"])

    def test_les_sondes_lentes_partent_en_parallele(self):
        def lent(cmd, timeout=None):
            time.sleep(0.4)
            return fake_runner()(cmd, timeout)

        def sonde_lente():
            time.sleep(0.4)
            return {"reachable": True, "busy": None}

        t0 = time.monotonic()
        self.snap(None, runner=lent, probe=sonde_lente)
        self.assertLess(time.monotonic() - t0, 1.0, "git, systemctl et l'admin doivent partir ensemble")


class LogScrubbingTests(SnapshotCase):
    def test_aucun_secret_ne_sort_du_journal(self):
        run = "20260930-120000-auto"
        self.write(f"runs/{run}/admin_submit.json", {"targets": [{"merchant": "K4G", "store_id": "92"}]})
        hook = "https://discord.com/api/webhooks/123456/SECRETTOKENabc"
        self.log(run,
                 {"ts": "2026-09-30T12:00:01Z", "event": "aborted",
                  "reason": f"notify via {hook} failed", "cookie": "wordpress_logged_in_x=S3CR3T"},
                 {"ts": "2026-09-30T12:00:02Z", "event": "login_probe",
                  "detail": "Cookie: wordpress_logged_in_abc=TOPSECRETVALUE; wp-settings-1=zz",
                  "value": "OTP123456"},
                 {"ts": "2026-09-30T12:00:03Z", "event": "http_debug",
                  "header": "Authorization: Basic cm9tYWluOnBhc3N3b3Jk", "token": "tok-SECRET"},
                 {"ts": "2026-09-30T12:00:04Z", "event": "env_dump",
                  "line": "AKS_DISCORD_WEBHOOK=https://discordapp.com/api/webhooks/9/ZZZ"})
        s = self.snap({"run_id": run, "kind": "data_entry_auto", "source": "admin"})
        dump = json.dumps(s, ensure_ascii=False)
        for secret in ("SECRETTOKENabc", "S3CR3T", "TOPSECRETVALUE", "OTP123456",
                       "cm9tYWluOnBhc3N3b3Jk", "tok-SECRET", "/api/webhooks/9/ZZZ"):
            self.assertNotIn(secret, dump, secret)
        self.assertEqual(len(s["logs"]), 4)
        self.assertTrue(s["logs"][-1]["text"].startswith("ABANDON : notify via ***REDACTED***"))

    def test_scrub_text_tronque_et_replie(self):
        self.assertEqual(vps_snapshot.scrub_text("a\n  b", 10), "a b")
        self.assertEqual(len(vps_snapshot.scrub_text("x" * 500, 50)), 50)

    def test_vingt_lignes_au_plus_les_plus_recentes_d_abord(self):
        run = "20260930-130000-auto"
        self.write(f"runs/{run}/admin_submit.json", {"targets": [{"merchant": "K4G", "store_id": "92"}]})
        self.log(run, *[{"ts": f"2026-09-30T13:{i:02d}:00Z", "event": "skip", "offer_id": str(i),
                         "reason": "r"} for i in range(40)])
        s = self.snap({"run_id": run, "kind": "data_entry_auto", "source": "admin"})
        self.assertEqual(len(s["logs"]), 20)
        self.assertEqual(s["logs"][0]["text"], "offre 39 écartée : r")
        self.assertEqual(s["logs"][-1]["text"], "offre 20 écartée : r")


class AlertTests(SnapshotCase):
    def test_marchand_arrete_offres_inconnues_redemarrage_maintenance(self):
        pass_id, page_run = self.group_a_sweep(
            halted="extract_failed_p3",
            offers_created=[{"name": "X", "created": False,
                             "post_save": "feed/CDP unreadable — offer state UNKNOWN, verify it by hand"}])
        self.log(page_run, {"ts": "2026-09-30T14:04:00Z", "event": "submit_offer", "offer_id": "9",
                            "success": False, "post_save": "offer state UNKNOWN, verify"})
        self.reboot.write_text("*** System restart required ***\n")
        self.write("state/maintenance/last_result.json", {"exit": 5, "finished_at": "2026-09-30T14:40:00Z"})
        s = self.snap({"run_id": LAUNCH, "kind": "data_entry_auto", "source": "admin"})
        alerts = s["alerts"]
        self.assertIn("Marchand arrêté — GameSeal: extract_failed_p3", alerts)
        self.assertIn("2 offre(s) à l'état INCONNU dans ce run — vérifier à la main sur AKS", alerts)
        self.assertIn("Redémarrage requis par Debian (/var/run/reboot-required)", alerts)
        self.assertIn("Dernière maintenance : code 5 le 30/09 à 14:40 UTC", alerts)
        self.assertEqual(s["last_maintenance"]["exit"], 5)
        self.assertTrue(s["reboot_required"])

    def test_boucle_arretee_session_expiree_quand_la_machine_est_au_repos(self):
        self.write(f"runs/{LAUNCH}/loop.json", {
            "run_id": LAUNCH, "loop": True, "state": "stopped", "pass": 4, "current_run_id": None,
            "totals": {"created": 900}, "stopped_reason": "session_expired",
            "stopped_label": "session expirée — transfert de cookies requis",
            "stopped_at": "2026-09-30T03:10:00Z"})
        self.write(f"runs/{LAUNCH}/recap.json", {"targets": [], "halted_merchants": []})
        s = self.snap(None)
        self.assertEqual(s["task"]["type"], "aucune")
        self.assertEqual(s["task"]["last_sweep"]["run_id"], LAUNCH)
        self.assertEqual(s["task"]["last_sweep"]["created"], 900)
        self.assertIn(f"Dernière boucle ({LAUNCH}) arrêtée : session expirée — transfert de cookies "
                      "requis — le 30/09 à 03:10 UTC", s["alerts"])
        self.assertTrue(any(a.startswith("Session AKS expirée") for a in s["alerts"]))
        self.assertFalse(s["logs_live"])

    def test_deconnexion_vue_dans_un_arret_du_journal(self):
        run = "20260930-140000-auto"
        self.write(f"runs/{run}/admin_submit.json", {"targets": [{"merchant": "K4G", "store_id": "92"}]})
        self.log(run, {"ts": "2026-09-30T14:00:00Z", "event": "aborted", "reason": "not logged in (wp-login)"})
        s = self.snap({"run_id": run, "kind": "data_entry_auto", "source": "admin"})
        self.assertTrue(any(a.startswith("Session AKS expirée") for a in s["alerts"]))

    def test_disque_plein(self):
        alerts = vps_snapshot.build_alerts(task={}, logs=[], disk={"path": "/", "used_pct": 93.4},
                                           reboot_required=False, last_maint={"exit": 0})
        self.assertEqual(alerts, ["Disque / plein à 93 %"])
        self.assertEqual(vps_snapshot.build_alerts(task={}, logs=[], disk={"used_pct": 50},
                                                   reboot_required=False, last_maint={"exit": 42}), [])


# ── revue adverse du 2026-09-30 ─────────────────────────────────────────────────────────
class InterruptedSweepTests(SnapshotCase):
    """Un balayage TUÉ (redémarrage de l'admin qui tue ses enfants, OOM, SIGKILL) n'est jamais
    affiché « fini » : ``run_loop`` écrit ``stopped`` et ``run_pass`` pose ``finished_at`` AVANT
    de rendre le marqueur — machine au repos + boucle ``running`` / ``pause`` ou recap sans
    ``finished_at`` = processus disparu."""

    def killed_loop(self, *, state="running", finished=False):
        pass_id = f"{LAUNCH}-pass3"
        page_run = f"{pass_id}-gog-s34-p7"
        self.write(f"runs/{LAUNCH}/loop.json", {
            "run_id": LAUNCH, "loop": True, "state": state, "pass": 3, "current_run_id": pass_id,
            "started_at": "2026-09-30T08:00:00Z", "updated_at": "2026-09-30T11:00:00Z",
            "next_pass_at": "2026-09-30T12:30:00Z" if state == "pause" else None,
            "totals": {"created": 500, "passes_finished": 2 if state == "running" else 3},
            "stopped_reason": None, "stopped_label": None, "stopped_at": None})
        recap = {"run_id": pass_id, "started_at": "2026-09-30T11:00:00Z",
                 "updated_at": "2026-09-30T12:00:00Z", "total_created": 120,
                 "halted_merchants": [], "loop_pass": 3,
                 "targets": [{"merchant": "GOG", "store_id": "34", "recap": {
                     "total_created": 120, "pages": [],
                     "current": None if (finished or state == "pause") else
                     {"page": 7, "run": page_run, "stage": "submit",
                      "stage_at": "2026-09-30T11:58:00Z"}}}]}
        if finished or state == "pause":
            recap["finished_at"] = "2026-09-30T12:00:00Z"
        self.write(f"runs/{pass_id}/recap.json", recap)
        self.log(page_run,
                 {"ts": "2026-09-30T11:59:00Z", "event": "submit_offer", "offer_id": "1", "success": True},
                 {"ts": "2026-09-30T11:59:30Z", "event": "submit_offer", "offer_id": "2", "success": True})
        return pass_id

    def test_boucle_tuee_en_pleine_passe(self):
        self.killed_loop()
        s = self.snap(None)
        t = s["task"]
        self.assertEqual(t["type"], "aucune")
        self.assertEqual(t["label"], "Rien en cours — le dernier balayage s'est interrompu sans fin propre")
        last = t["last_sweep"]
        self.assertTrue(last["interrupted"])
        self.assertNotIn("ended_at", last, "jamais « fini le … » pour un processus disparu")
        self.assertEqual(last["last_seen_at"], "2026-09-30T12:00:00Z")
        # 500 (passes finies) + 120 (pages finies de la passe tuée) + 2 (page tuée, lues au journal)
        self.assertEqual(last["created"], 622)
        self.assertIn(f"Boucle {LAUNCH} interrompue sans fin propre (processus disparu) — GOG page 7 "
                      "— dernière trace le 30/09 à 12:00 UTC — à relancer depuis la console",
                      s["alerts"])
        self.assertFalse(s["logs_live"], "le journal du DERNIER run, pas d'un run en cours")

    def test_boucle_tuee_pendant_la_pause_ne_recompte_pas_la_passe(self):
        self.killed_loop(state="pause")
        last = self.snap(None)["task"]["last_sweep"]
        self.assertTrue(last["interrupted"])
        self.assertEqual(last["created"], 500, "en pause, la passe finie est déjà dans les totaux")

    def test_boucle_tuee_entre_la_fin_de_passe_et_l_ecriture_de_loop_json(self):
        # recap fini, loop.json encore « running » (totaux pas encore mis à jour) : la passe compte
        self.killed_loop(finished=True)
        last = self.snap(None)["task"]["last_sweep"]
        self.assertTrue(last["interrupted"])
        self.assertEqual(last["created"], 620)

    def test_balayage_simple_tue(self):
        run = "20260930-090000-auto"
        self.write(f"runs/{run}/admin_submit.json", {"targets": [{"merchant": "K4G", "store_id": "92"}]})
        self.write(f"runs/{run}/recap.json", {
            "run_id": run, "started_at": "2026-09-30T09:00:00Z", "updated_at": "2026-09-30T10:00:00Z",
            "total_created": 12, "halted": None, "halted_merchants": [], "targets": []})
        s = self.snap(None)
        last = s["task"]["last_sweep"]
        self.assertTrue(last["interrupted"])
        self.assertNotIn("ended_at", last)
        self.assertIn(f"Balayage {run} interrompu sans fin propre (processus disparu) — dernière trace "
                      "le 30/09 à 10:00 UTC — à relancer depuis la console", s["alerts"])

    def test_une_fin_propre_reste_une_fin(self):
        run = "20260930-090000-auto"
        self.write(f"runs/{run}/recap.json", {
            "run_id": run, "started_at": "2026-09-30T09:00:00Z", "updated_at": "2026-09-30T10:00:00Z",
            "finished_at": "2026-09-30T10:00:00Z", "total_created": 12, "halted_merchants": [],
            "targets": []})
        s = self.snap(None)
        last = s["task"]["last_sweep"]
        self.assertNotIn("interrupted", last)
        self.assertEqual(last["ended_at"], "2026-09-30T10:00:00Z")
        self.assertEqual(s["task"]["label"], "Rien en cours")
        self.assertEqual(s["alerts"], [])
        # une boucle arrêtée par l'opérateur non plus
        self.write(f"runs/{LAUNCH}/loop.json", {
            "run_id": LAUNCH, "loop": True, "state": "stopped", "pass": 2, "totals": {"created": 9},
            "stopped_reason": "operator_stop", "stopped_at": "2026-09-30T11:00:00Z"})
        self.assertEqual(self.snap(None)["alerts"], [])

    def test_un_dossier_sans_recap_n_est_pas_un_balayage_tue(self):
        # l'admin crée le dossier (admin_submit.json) avant que l'enfant n'écrive quoi que ce soit
        run = "20260930-090000-auto"
        self.write(f"runs/{run}/admin_submit.json", {"targets": [{"merchant": "K4G", "store_id": "92"}]})
        s = self.snap(None)
        self.assertNotIn("interrupted", s["task"]["last_sweep"])
        self.assertEqual(s["alerts"], [])


class LaunchSourceTests(SnapshotCase):
    """« (lancé au terminal) » se lit sur ``admin_submit.json`` (écrit par ``_spawn`` seul, avec
    le pid de l'enfant), jamais sur ``marker.source`` : ``scripts/10`` et ``scripts/05`` écrivent
    toujours ``source: "cli"``, même lancés par l'admin."""

    def marker(self, run_id, kind, pid):
        (self.root / "state" / "active_run.json").write_text(json.dumps({
            "run_id": run_id, "kind": kind, "source": "cli", "pid": pid,
            "started_at": "2026-09-30T08:00:00Z"}))

    def test_admin_injoignable_balayage_lance_par_l_admin(self):
        self.group_a_sweep(admin_pid=os.getpid())
        self.marker(LAUNCH, "data_entry_auto", os.getpid())
        s = self.snap(None, reachable=False)
        self.assertEqual(s["admin"]["busy"]["source"], "cli", "le marqueur dit toujours « cli »")
        self.assertFalse(s["task"]["from_terminal"])
        self.assertEqual(s["task"]["group"], "A")
        self.assertFalse(s["task"]["label"].endswith("(lancé au terminal)"), s["task"]["label"])

    def test_relance_au_terminal_avec_le_meme_run_id(self):
        self.group_a_sweep(admin_pid=os.getpid() + 100000)
        self.marker(LAUNCH, "data_entry_auto", os.getpid())
        s = self.snap(None, reachable=False)
        self.assertTrue(s["task"]["from_terminal"])
        self.assertTrue(s["task"]["label"].endswith("(lancé au terminal)"))

    def test_saisie_validee_lancee_par_l_admin(self):
        run = "20260930-150000-k4g"
        self.write(f"runs/{run}/admin_submit.json", {"state": "running", "kind": "submit",
                                                     "pid": os.getpid()})
        self.marker(run, "submit", os.getpid())
        s = self.snap(None, reachable=False)
        self.assertEqual(s["task"]["label"], "Saisie validée (Validation & Submit)")
        (self.runs / run / "admin_submit.json").unlink()
        s = self.snap(None, reachable=False)
        self.assertEqual(s["task"]["label"], "Saisie validée (Validation & Submit) (lancé au terminal)")

    def test_liste_des_runs_muette_retombe_sur_le_marqueur_jamais_sur_rien(self):
        probe = lambda: {"reachable": True, "busy": None, "busy_unknown": True,  # noqa: E731
                         "busy_error": "liste des runs : délai de 6 s dépassé", "error": None}
        s = self.snap(None, probe=probe)
        self.assertEqual(s["task"]["type"], "inconnue")
        self.assertIn("Tâche inconnue", s["task"]["label"])
        self.assertTrue(s["admin"]["reachable"])
        self.assertTrue(s["admin"]["busy_unknown"])
        self.group_a_sweep(admin_pid=os.getpid())
        self.marker(LAUNCH, "data_entry_auto", os.getpid())
        s = self.snap(None, probe=probe)
        self.assertEqual(s["task"]["type"], "balayage")
        self.assertTrue(s["task"]["label"].startswith("Balayage groupe A en boucle — passe 3"))


class _Admin(http.server.BaseHTTPRequestHandler):
    """Un faux admin : ``/api/meta`` tout de suite, ``/api/sort/runs`` après ``runs_delay``."""

    meta_delay = 0.0
    runs_delay = 0.0

    def do_GET(self):  # noqa: N802
        delay = self.meta_delay if self.path == "/api/meta" else self.runs_delay
        if delay:
            time.sleep(delay)
        body = {"platforms": []} if self.path == "/api/meta" else \
            {"runs": [], "busy": {"run_id": "r1", "kind": "sort_scan", "source": "admin"}}
        data = json.dumps(body).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def log_message(self, *args):
        pass


class AdminProbeTests(unittest.TestCase):
    """La sonde RÉELLE de l'admin, contre de vrais serveurs locaux (jamais le port 8650)."""

    def serve(self, *, meta_delay=0.0, runs_delay=0.0):
        handler = type("H", (_Admin,), {"meta_delay": meta_delay, "runs_delay": runs_delay})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_admin_sain(self):
        out = vps_snapshot.admin_probe_http(self.serve(), timeout=1.0, busy_timeout=1.0)
        self.assertTrue(out["reachable"])
        self.assertEqual(out["busy"]["run_id"], "r1")
        self.assertNotIn("busy_unknown", out)

    def test_admin_lent_a_lister_ses_runs_reste_joignable(self):
        url = self.serve(runs_delay=1.5)
        t0 = time.monotonic()
        out = vps_snapshot.admin_probe_http(url, timeout=0.5, busy_timeout=0.5)
        self.assertLess(time.monotonic() - t0, 1.3, "les deux lectures partent ensemble")
        self.assertTrue(out["reachable"], out)
        self.assertIsNone(out["busy"])
        self.assertTrue(out["busy_unknown"])
        self.assertIn("délai de 0.5 s dépassé", out["busy_error"])

    def test_admin_qui_ne_repond_plus(self):
        out = vps_snapshot.admin_probe_http(self.serve(meta_delay=1.5, runs_delay=1.5),
                                            timeout=0.4, busy_timeout=0.4)
        self.assertFalse(out["reachable"])
        self.assertIn("délai de 0.4 s dépassé", out["error"])

    def test_admin_arrete_connexion_refusee(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        out = vps_snapshot.admin_probe_http(f"http://127.0.0.1:{port}", timeout=0.5, busy_timeout=0.5)
        self.assertFalse(out["reachable"])
        self.assertTrue(out["error"])
        self.assertIsNone(out["busy"])


class RealTimeoutTests(unittest.TestCase):
    """Le code 124 n'est pas fabriqué par un faux : un vrai processus qui dépasse son délai."""

    def test_run_cmd_et_run_ssh_rendent_124(self):
        for fn in (vps_snapshot.run_cmd, ov.run_ssh):
            t0 = time.monotonic()
            res = fn(["sleep", "5"], 0.3)
            self.assertLess(time.monotonic() - t0, 3.0)
            self.assertEqual(res.returncode, 124, fn.__name__)
            self.assertIn("délai de 0.3 s dépassé", res.stderr)
        self.assertEqual(ov.run_ssh(["/nonexistent/ssh-absent"], 1.0).returncode, 127)

    def test_une_machine_qui_ne_repond_pas_a_temps_est_down_delai_depasse(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            key = d / "k"
            key.write_text("x")
            cfg = d / "c.json"
            cfg.write_text(json.dumps({"ssh_key": str(key), "hosts": [{"name": "lente",
                                                                       "ssh": "debian@10.0.0.9"}]}))
            o = ov.Overview(d, config_path=cfg, local_snapshot=lambda: local_snap(), timeout=0.3,
                            runner=lambda argv, t: ov.run_ssh(["sleep", "5"], t))
            by = {h["name"]: h for h in o.payload()["hosts"]}
        self.assertEqual(by["lente"]["status"], "down")
        self.assertEqual(by["lente"]["down_reasons"], ["délai de 0.3 s dépassé"])


class SnapshotScriptTests(unittest.TestCase):
    """``scripts/20_vps_snapshot.py`` : UNE ligne JSON, code 0, même quand tout casse."""

    def _main(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("snap20", ROOT / "scripts" / "20_vps_snapshot.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.main

    def test_une_ligne_json(self):
        main = self._main()
        out = io.StringIO()
        with mock.patch("src.vps_snapshot.snapshot", return_value={"schema": 1, "host": "h"}), \
                redirect_stdout(out):
            self.assertEqual(main([]), 0)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["host"], "h")

    def test_une_ligne_json_meme_en_panne(self):
        main = self._main()
        out = io.StringIO()
        with mock.patch("src.vps_snapshot.snapshot", side_effect=RuntimeError("boum")), \
                redirect_stdout(out):
            self.assertEqual(main([]), 0)
        data = json.loads(out.getvalue().strip())
        self.assertIn("boum", data["errors"]["snapshot"])


# ── la route ─────────────────────────────────────────────────────────────────────────
def local_snap(**kw):
    snap = {"schema": 1, "host": "vmi-local", "at": "2026-09-30T15:00:00Z",
            "code": {"sha": "2272e92", "subject": "fix"},
            "services": {"aks-admin": "active", "aks-chromium": "active",
                         "hermes-cdp-proxy": "absent", "nginx": "active"},
            "admin": {"reachable": True, "busy": None},
            "task": {"type": "aucune", "label": "Rien en cours"}, "logs": [], "alerts": [],
            "errors": {}}
    snap.update(kw)
    return snap


class FakeSsh:
    def __init__(self, answers, delay=0.0):
        self.answers = answers
        self.calls = []
        self.delay = delay
        self.lock = threading.Lock()

    def __call__(self, argv, timeout):
        with self.lock:
            self.calls.append(list(argv))
        if self.delay:
            time.sleep(self.delay)
        kind = self.answers.get(argv[-1], "down")
        if kind == "up":
            snap = local_snap(host=argv[-1].split("@")[1])
            return subprocess.CompletedProcess(argv, 0, "Warning: something\n" + json.dumps(snap) + "\n", "")
        if kind == "timeout":
            return subprocess.CompletedProcess(argv, 124, "", f"délai de {timeout:g} s dépassé")
        if kind == "badjson":
            return subprocess.CompletedProcess(argv, 0, "Traceback: not json\n", "")
        if kind == "secret":
            snap = local_snap(logs=[{"ts": "t", "event": "x",
                                     "text": "hook https://discord.com/api/webhooks/1/LEAKED"}])
            return subprocess.CompletedProcess(argv, 0, json.dumps(snap), "")
        if kind == "chromium_down":
            snap = local_snap(services={"aks-admin": "active", "aks-chromium": "failed", "nginx": "active"})
            return subprocess.CompletedProcess(argv, 0, json.dumps(snap), "")
        if kind == "skew":
            # une machine sur un autre commit : autre format, autre forme
            snap = local_snap(schema=2, services={"aks-admin": "active", "nginx": {"state": "active"}},
                              alerts="pas une liste", logs={"0": "pas une liste"})
            return subprocess.CompletedProcess(argv, 0, json.dumps(snap), "")
        if kind == "malformed":
            snap = local_snap(alerts=["ok", {"x": 1}], logs=[None, {"ts": "t", "event": "e", "text": "t"}],
                              services={"aks-admin": "active", "nginx": ["active"]}, task="texte")
            return subprocess.CompletedProcess(argv, 0, json.dumps(snap), "")
        if kind == "admin_down":
            snap = local_snap(admin={"reachable": False, "error": "URLError: refused", "busy": None})
            return subprocess.CompletedProcess(argv, 0, json.dumps(snap), "")
        return subprocess.CompletedProcess(argv, 255, "", "ssh: connect to host x port 22: Connection refused")


class OverviewUnitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.key = self.dir / "aks_overview_ed25519"
        self.key.write_text("clé factice")
        self.config = self.dir / "overview_hosts.json"

    def make(self, hosts, answers, **kw):
        self.config.write_text(json.dumps({"ssh_key": str(self.key), "hosts": hosts}))
        fake = FakeSsh(answers, delay=kw.pop("delay", 0.0))
        o = ov.Overview(self.dir, config_path=self.config, runner=fake,
                        local_snapshot=lambda: local_snap(), **kw)
        return o, fake

    def test_up_delai_json_illisible_injoignable(self):
        hosts = [{"name": "cette-vm", "ssh": None, "console_url": "https://a.example/executor/"},
                 {"name": "ancienne-vm", "ssh": "debian@10.0.0.1", "console_url": "https://b.example/executor/"},
                 {"name": "lente", "ssh": "debian@10.0.0.2"},
                 {"name": "cassee", "ssh": "debian@10.0.0.3"},
                 {"name": "eteinte", "ssh": "debian@10.0.0.4"}]
        o, fake = self.make(hosts, {"debian@10.0.0.1": "up", "debian@10.0.0.2": "timeout",
                                    "debian@10.0.0.3": "badjson"})
        d = o.payload()
        by = {h["name"]: h for h in d["hosts"]}
        self.assertEqual([h["name"] for h in d["hosts"]], ["cette-vm", "ancienne-vm", "lente", "cassee", "eteinte"])
        self.assertEqual(by["cette-vm"]["status"], "up")
        self.assertTrue(by["cette-vm"]["local"])
        self.assertEqual(by["ancienne-vm"]["status"], "up")
        self.assertEqual(by["ancienne-vm"]["snapshot"]["host"], "10.0.0.1")
        self.assertEqual(by["lente"]["status"], "down")
        self.assertIn("délai de 10 s dépassé", by["lente"]["down_reasons"][0])
        self.assertEqual(by["cassee"]["status"], "down")
        self.assertIn("réponse illisible", by["cassee"]["error"])
        self.assertIn("Connection refused", by["eteinte"]["error"])
        # la ligne ssh : la clé dédiée seule, sans commande après la cible
        argv = next(c for c in fake.calls if c[-1] == "debian@10.0.0.1")
        self.assertEqual(argv[:4], ["ssh", "-i", str(self.key), "-T"])
        for opt in ("BatchMode=yes", "ConnectTimeout=5", "StrictHostKeyChecking=accept-new",
                    "IdentitiesOnly=yes"):
            self.assertIn(opt, argv)
        self.assertEqual(argv[-1], "debian@10.0.0.1", "aucune commande envoyée : c'est la commande forcée")
        self.assertNotIn(str(self.key), json.dumps(d), "le chemin de la clé ne part pas dans la réponse")
        self.assertEqual(len(fake.calls), 4, "la machine locale n'est jamais lue par ssh")

    def test_down_admin_ou_service_cle_et_service_absent(self):
        hosts = [{"name": "a", "ssh": "debian@10.0.0.1"}, {"name": "b", "ssh": "debian@10.0.0.2"}]
        o, _ = self.make(hosts, {"debian@10.0.0.1": "chromium_down", "debian@10.0.0.2": "admin_down"})
        by = {h["name"]: h for h in o.payload()["hosts"]}
        self.assertEqual(by["a"]["down_reasons"], ["service aks-chromium failed"])
        self.assertEqual(by["b"]["down_reasons"], ["admin injoignable (URLError: refused)"])
        self.assertEqual(by["cette-vm"]["status"], "up", "hermes-cdp-proxy absent n'est pas une panne")

    def test_le_cache_evite_de_multiplier_les_ssh(self):
        now = [100.0]
        o, fake = self.make([{"name": "a", "ssh": "debian@10.0.0.1"}], {"debian@10.0.0.1": "up"},
                            clock=lambda: now[0])
        first = o.payload()
        self.assertFalse(first["cached"])
        now[0] += 5
        second = o.payload()
        self.assertTrue(second["cached"])
        self.assertEqual(second["age_s"], 5.0)
        self.assertEqual(len(fake.calls), 1)
        now[0] += 6
        self.assertFalse(o.payload()["cached"])
        self.assertEqual(len(fake.calls), 2)

    def test_onglets_simultanes_un_seul_calcul(self):
        o, fake = self.make([{"name": "a", "ssh": "debian@10.0.0.1"}], {"debian@10.0.0.1": "up"},
                            delay=0.2)
        threads = [threading.Thread(target=o.payload) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(fake.calls), 1)

    def test_les_machines_sont_lues_en_parallele(self):
        hosts = [{"name": f"h{i}", "ssh": f"debian@10.0.0.{i}"} for i in range(1, 5)]
        o, _ = self.make(hosts, {f"debian@10.0.0.{i}": "up" for i in range(1, 5)}, delay=0.4)
        t0 = time.monotonic()
        o.payload()
        self.assertLess(time.monotonic() - t0, 1.2)

    def test_ce_que_relaie_l_admin_est_refiltre(self):
        o, _ = self.make([{"name": "a", "ssh": "debian@10.0.0.1"}], {"debian@10.0.0.1": "secret"})
        self.assertNotIn("LEAKED", json.dumps(o.payload()))

    def test_une_photo_d_un_autre_format_est_down_jamais_un_500(self):
        """Revue adverse du 2026-09-30 : ``services.nginx`` en objet faisait lever ``health()``
        HORS de la garde — 500 pour toutes les machines, cache jamais écrit."""

        now = [100.0]
        o, fake = self.make([{"name": "saine", "ssh": "debian@10.0.0.1"},
                             {"name": "autre-version", "ssh": "debian@10.0.0.2"},
                             {"name": "tordue", "ssh": "debian@10.0.0.3"}],
                            {"debian@10.0.0.1": "up", "debian@10.0.0.2": "skew",
                             "debian@10.0.0.3": "malformed"}, clock=lambda: now[0])
        d = o.payload()
        by = {h["name"]: h for h in d["hosts"]}
        self.assertEqual(by["saine"]["status"], "up")
        self.assertEqual(by["cette-vm"]["status"], "up")
        skew = by["autre-version"]
        self.assertEqual(skew["status"], "down")
        self.assertTrue(any("format 2 inconnu" in r for r in skew["down_reasons"]), skew["down_reasons"])
        self.assertIn("service nginx illisible", skew["down_reasons"])
        self.assertTrue(any(r.startswith("photo mal formée : ") and "alerts" in r and "logs" in r
                            for r in skew["down_reasons"]), skew["down_reasons"])
        # ce qui est relayé a la forme que la page sait dessiner
        self.assertEqual(skew["snapshot"]["alerts"], [])
        self.assertEqual(skew["snapshot"]["logs"], [])
        self.assertEqual(skew["snapshot"]["services"]["nginx"], "illisible")
        bad = by["tordue"]
        self.assertEqual(bad["status"], "down")
        self.assertEqual(bad["snapshot"]["alerts"], ["ok"])
        self.assertEqual(bad["snapshot"]["logs"], [{"ts": "t", "event": "e", "text": "t"}])
        self.assertIsNone(bad["snapshot"]["task"])
        json.dumps(d)
        # le cache est écrit : un second onglet ne relance aucun ssh
        now[0] += 3
        self.assertTrue(o.payload()["cached"])
        self.assertEqual(len(fake.calls), 3)

    def test_un_verdict_qui_leve_est_une_machine_down(self):
        o, _ = self.make([{"name": "a", "ssh": "debian@10.0.0.1"}], {"debian@10.0.0.1": "up"})
        with mock.patch.object(ov, "health", side_effect=TypeError("unhashable type: 'dict'")):
            d = o.payload()
        self.assertEqual({h["status"] for h in d["hosts"]}, {"down"})
        self.assertTrue(d["hosts"][1]["down_reasons"][0].startswith("photo illisible : TypeError"))

    def test_sans_configuration_seule_cette_machine(self):
        o = ov.Overview(self.dir, config_path=self.dir / "absent.json",
                        runner=FakeSsh({}), local_snapshot=lambda: local_snap())
        d = o.payload()
        self.assertEqual([h["name"] for h in d["hosts"]], ["cette-vm"])
        self.assertEqual(d["hosts"][0]["console_url"], ".")
        self.assertFalse(d["config"]["configured"])

    def test_configuration_illisible_ou_invalide(self):
        self.config.write_text("{pas du json")
        o = ov.Overview(self.dir, config_path=self.config, runner=FakeSsh({}),
                        local_snapshot=lambda: local_snap())
        d = o.payload()
        self.assertIn("illisible", d["config"]["error"])
        self.assertEqual(len(d["hosts"]), 1)

        cfg = ov.load_config(self._cfg({"ssh_key": "relative/key", "hosts": [
            {"name": "opt", "ssh": "-oProxyCommand=sh@x"},
            {"name": "rel", "ssh": "debian@10.0.0.9"},
            {"name": "js", "ssh": None, "console_url": "javascript:alert(1)"},
            {"name": "js", "ssh": None},
            "pas un objet",
            {"name": "../../x", "ssh": "debian@10.0.0.8"}]}))
        by = {h["name"]: h for h in cfg["hosts"]}
        self.assertIn("cible ssh invalide", by["opt"]["error"])
        self.assertIn("chemin absolu", by["rel"]["error"])
        js = [h for h in cfg["hosts"] if h["name"] == "js"]
        self.assertTrue(js[0]["local"])
        self.assertEqual(js[0]["console_url"], ".", "un lien javascript: n'est jamais gardé")
        self.assertIn("nom en double", js[1]["error"])
        deux = ov.load_config(self._cfg({"hosts": [{"name": "a", "ssh": None}, {"name": "b", "ssh": None}]}))
        self.assertIn("deux machines locales", deux["hosts"][1]["error"])
        self.assertIn("nom invalide", cfg["hosts"][-1]["error"])
        self.assertTrue(any("objet attendu" in (h.get("error") or "") for h in cfg["hosts"]))

    def test_une_entree_invalide_s_affiche_down_sans_ssh(self):
        fake = FakeSsh({})
        self.config.write_text(json.dumps({"ssh_key": str(self.key),
                                           "hosts": [{"name": "opt", "ssh": "-oProxyCommand=x@y"},
                                                     {"name": "nokey", "ssh": "debian@10.0.0.5",
                                                      "key": str(self.dir / "absente")}]}))
        o = ov.Overview(self.dir, config_path=self.config, runner=fake, local_snapshot=lambda: local_snap())
        by = {h["name"]: h for h in o.payload()["hosts"]}
        self.assertEqual(by["opt"]["status"], "down")
        self.assertIn("clé ssh absente", by["nokey"]["down_reasons"][0])
        self.assertEqual(fake.calls, [])

    def test_photo_locale_en_echec(self):
        def boum():
            raise RuntimeError("disque")
        o = ov.Overview(self.dir, config_path=self.dir / "absent.json", runner=FakeSsh({}),
                        local_snapshot=boum)
        h = o.payload()["hosts"][0]
        self.assertEqual(h["status"], "down")
        self.assertIn("photo locale en échec", h["down_reasons"][0])

    def _cfg(self, obj):
        path = self.dir / "cfg.json"
        path.write_text(json.dumps(obj))
        return path


class OverviewRouteTests(AppTestCase):
    def setUp(self):
        super().setUp()
        tmp = Path(self.tmp.name)
        key = tmp / "key"
        key.write_text("x")
        cfg = tmp / "overview_hosts.json"
        cfg.write_text(json.dumps({"ssh_key": str(key), "hosts": [
            {"name": "prod", "ssh": None, "console_url": "https://p.example/executor/"},
            {"name": "ancienne-vm", "ssh": "debian@10.0.0.1"}]}))
        self.fake = FakeSsh({"debian@10.0.0.1": "up"})
        self.state.overview = ov.Overview(tmp, config_path=cfg, runner=self.fake,
                                          local_snapshot=lambda: local_snap())

    def test_get_api_overview(self):
        response, data = self._json("GET", "/api/overview")
        self.assertEqual(response.status, 200)
        self.assertEqual([h["name"] for h in data["hosts"]], ["prod", "ancienne-vm"])
        self.assertEqual({h["status"] for h in data["hosts"]}, {"up"})
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_une_machine_d_une_autre_version_ne_met_pas_la_route_en_panne(self):
        self.fake.answers["debian@10.0.0.1"] = "skew"
        response, data = self._json("GET", "/api/overview")
        self.assertEqual(response.status, 200)
        by = {h["name"]: h for h in data["hosts"]}
        self.assertEqual(by["prod"]["status"], "up")
        self.assertEqual(by["ancienne-vm"]["status"], "down")

    def test_la_route_est_en_lecture_seule(self):
        for method in ("POST", "PUT", "DELETE"):
            response, _ = self._request(method, "/api/overview", body={"hosts": []})
            self.assertIn(response.status, (404, 501), method)
        self.assertEqual(self.fake.calls, [], "aucun ssh sur une requête d'écriture")

    def test_les_pages_servies_avec_leurs_actifs_versionnes(self):
        for path in ("/overview", "/vue-d-ensemble"):
            response, data = self._request("GET", path)
            self.assertEqual(response.status, 200, path)
            html = data.decode("utf-8")
            self.assertRegex(html, r'"overview\.js\?v=[0-9a-f]{8}"')
            self.assertRegex(html, r'"overview\.css\?v=[0-9a-f]{8}"')
        for asset in ("overview.js", "overview.css"):
            response, _ = self._request("GET", "/" + asset)
            self.assertEqual(response.status, 200, asset)

    def test_la_photo_locale_en_processus_utilise_le_busy_du_manager(self):
        """Sans couture : l'admin prend SA photo avec son propre ``busy()`` — jamais un appel
        HTTP vers lui-même."""

        seen = {}

        def fake_snapshot(root, **kw):
            seen["probe"] = kw["admin_probe"]()
            return local_snap()

        o = ov.Overview(ROOT, busy=lambda: {"run_id": "r", "kind": "data_entry_auto", "source": "admin"},
                        config_path=Path(self.tmp.name) / "absent.json", runner=self.fake)
        with mock.patch("src.vps_snapshot.snapshot", side_effect=fake_snapshot), \
                mock.patch("src.vps_snapshot.admin_probe_http",
                           side_effect=AssertionError("pas d'appel HTTP vers soi-même")):
            d = o.payload()
        self.assertEqual(seen["probe"]["busy"]["run_id"], "r")
        self.assertTrue(seen["probe"]["reachable"])
        self.assertEqual(d["hosts"][0]["status"], "up")


if __name__ == "__main__":
    unittest.main()
