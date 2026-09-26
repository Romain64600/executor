"""The console's JavaScript is now EXECUTED, not just spell-checked (2026-09-17).

Romain: « nos tests sont avec un simulateur formel ? » — the honest answer was no, and worse:
for the browser console we had no execution at all. Every assertion on ``sort.js`` read the
file as TEXT and checked that certain strings were present. That proves the code is WRITTEN a
certain way; it proves nothing about what it does. It is exactly why his two repros found
defects my tests could not see.

He then approved the dependency — « Installe node pour les tests JS ». Node is a **test-only**
dependency (Debian ``nodejs`` 20, no npm packages, no lockfile, nothing added to the runtime).

``tests/js/sort_race.test.mjs`` loads the real ``src/admin/static/sort.js`` into a stubbed
browser (``tests/js/dom_stub.mjs``) whose ``fetch`` answers are released BY HAND, so two plan
loads can be interleaved exactly as Romain described. It drives the real UI path — picker,
card button, GO field, canary button — and asserts on the requests that leave the page.

Discrimination measured on 2026-09-17, which is what makes these tests worth their cost:

* against ``507bdf8~1`` (before any fix) — 3 failures;
* against ``507bdf8`` (the click-time freeze) — 3 failures, reproducing Romain's exact repro:
  the move leaves for ``scan-B`` while the operator is looking at ``scan-A``'s offers;
* against HEAD with the poll generation token removed — the stale-tick test fails;
* against HEAD — all pass.

This is still a SIMULATION, not a formal method: no model checker, no proof, no property-based
exploration. It exercises the scenarios we wrote down. It cannot tell us about the ones we
did not think of.
"""

import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "js" / "sort_race.test.mjs"
NODE = shutil.which("node") or shutil.which("nodejs")


@unittest.skipIf(NODE is None,
                 "node absent — installer le paquet Debian 'nodejs' (dépendance de test, "
                 "approuvée par Romain le 2026-09-17)")
class SortConsoleLiveSimulationTests(unittest.TestCase):
    """Runs the node harness and surfaces its output on failure."""

    def test_the_harness_exists_and_targets_the_real_file(self):
        self.assertTrue(HARNESS.is_file(), HARNESS)
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn('"src", "admin", "static", "sort.js"', text,
                      "the harness must load the SHIPPED console, never a copy")

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(HARNESS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("tout passe", proc.stdout)

    def test_the_harness_would_catch_the_defect_it_was_written_for(self):
        """A green harness proves nothing unless it goes RED on the broken code. Replay it
        against the revision Romain took in fault (the click-time freeze)."""

        old = subprocess.run(["git", "show", "507bdf8:src/admin/static/sort.js"],
                             cwd=ROOT, capture_output=True, text=True)
        if old.returncode != 0:          # shallow clone / rewritten history
            self.skipTest("révision 507bdf8 absente de ce clone")
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                         delete=False) as fh:
            fh.write(old.stdout)
            path = fh.name
        try:
            import os
            env = dict(os.environ, SORT_JS=path)   # keep PATH etc. — CI runners differ
            proc = subprocess.run([NODE, str(HARNESS)], cwd=ROOT, capture_output=True,
                                  text=True, timeout=120, env=env)
            self.assertNotEqual(proc.returncode, 0,
                                "le harnais passe sur le code fautif — il ne prouve rien")
            self.assertIn("scan-B", proc.stdout,
                          "l'échec doit montrer le déplacement parti sur le mauvais scan")
        finally:
            pathlib.Path(path).unlink(missing_ok=True)


AUTO_HARNESS = ROOT / "tests" / "js" / "auto_groups.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class AutoConsoleGroupsSimulationTests(unittest.TestCase):
    """La console de SAISIE AUTO, exécutée — les groupes de marchands (2026-09-22).

    Romain : « je ne vois pas les groupes A et B sur l'admin ». Aucun test de texte n'aurait
    vu cette panne : le code était écrit, il ne s'affichait pas. Écrire le harnais a d'ailleurs
    trouvé la même classe de défaut dans le bouchon lui-même (`appendChild` manquant : la
    console levait, l'init avalait, l'écran restait muet)."""

    def test_the_harness_targets_the_shipped_console(self):
        self.assertTrue(AUTO_HARNESS.is_file(), AUTO_HARNESS)
        self.assertIn('"src", "admin", "static", "auto.js"',
                      AUTO_HARNESS.read_text(encoding="utf-8"))

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(AUTO_HARNESS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertNotIn("FAIL", proc.stdout)

    def test_the_harness_goes_red_when_the_console_stops_rendering(self):
        """Vert ne prouve rien tant que rouge n'est pas prouvé : on retire l'appel à
        `renderGroups()` et le harnais doit s'effondrer — c'est la panne de Romain."""

        js = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
        casse = js.replace("    renderGroups();\n", "", 1)
        self.assertNotEqual(casse, js, "l'appel à renderGroups a changé de forme")
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            faux = pathlib.Path(tmp) / "auto.js"
            faux.write_text(casse, encoding="utf-8")
            env = dict(os.environ, AUTO_JS=str(faux))
            proc = subprocess.run([NODE, str(AUTO_HARNESS)], cwd=ROOT, capture_output=True,
                                  text=True, timeout=120, env=env)
        self.assertNotEqual(proc.returncode, 0,
                            "le harnais passe sur une console qui n'affiche rien")


class AutoConsoleGroupLaunchIsFollowed(unittest.TestCase):
    """REVUE DE ROMAIN (2026-09-23) : « lancement par groupe sans suivi du run — aucun
    startPolling() : l'écran reste Prêt, le récapitulatif ne s'actualise pas et les boutons
    restent bloqués après la fin, jusqu'au rechargement ». Le harnais rejoue le scénario ;
    ce test prouve qu'il ROUGIT quand on retire le suivi du bouton de groupe."""

    @unittest.skipIf(NODE is None, "node absent (dépendance de test)")
    def test_le_harnais_rougit_sans_le_suivi_du_groupe(self):
        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
        debut = js.index("async function launchGroup(")
        fin = js.index("\n}", debut)
        corps = js[debut:fin]
        self.assertIn("startPolling(r.run_id);", corps, "le bouton de groupe ne suit plus le run")
        casse = js[:debut] + corps.replace("startPolling(r.run_id);", "") + js[fin:]
        with tempfile.TemporaryDirectory() as tmp:
            faux = pathlib.Path(tmp) / "auto.js"
            faux.write_text(casse, encoding="utf-8")
            proc = subprocess.run([NODE, str(AUTO_HARNESS)], cwd=ROOT, capture_output=True,
                                  text=True, timeout=120, env=dict(os.environ, AUTO_JS=str(faux)))
        self.assertNotEqual(proc.returncode, 0, "le harnais passe sur un groupe non suivi")
        self.assertIn("SUIVI", proc.stdout)


LIVE_HARNESS = ROOT / "tests" / "js" / "auto_live_page.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class AutoConsoleLivePageSimulationTests(unittest.TestCase):
    """La PAGE EN COURS dans la console de saisie auto (Romain, 2026-09-26 : « 4. Go »).

    Le 25/09, une heure de « 0 offres créées · 0 marchand » pendant que Gamesplanet FR saisissait
    sa page 3. Le harnais charge le vrai ``auto.js``, adopte un sweep en cours et regarde ce
    qui s'affiche à chaque étape — et ce qui part vers l'admin (les compteurs de la page, lus
    sur ``api/runs/<run>``, seulement pendant la saisie)."""

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(LIVE_HARNESS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertNotIn("FAIL", proc.stdout)

    def test_the_harness_goes_red_on_each_removed_piece(self):
        """Vert ne prouve rien tant que rouge n'est pas prouvé : sans la lecture des
        compteurs, sans la ligne du résumé, ou sans la garde « run vivant », le harnais
        doit rougir."""

        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
        mutations = {
            "compteurs": ('const r = await api("api/runs/" + encodeURIComponent(cur.run));',
                          "const r = null;"),
            "résumé": ('cur ? el("div", { class: "live-line"', 'false ? el("div", { class: "live-line"'),
            "run vivant": ("const pc = running && !rec.finished_at ? sr.current : null;",
                           "const pc = sr.current;"),
        }
        for nom, (avant, apres) in mutations.items():
            with self.subTest(nom):
                self.assertIn(avant, js, f"la forme de « {nom} » a changé")
                casse = js.replace(avant, apres, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    faux = pathlib.Path(tmp) / "auto.js"
                    faux.write_text(casse, encoding="utf-8")
                    proc = subprocess.run([NODE, str(LIVE_HARNESS)], cwd=ROOT,
                                          capture_output=True, text=True, timeout=120,
                                          env=dict(os.environ, AUTO_JS=str(faux)))
                self.assertNotEqual(proc.returncode, 0,
                                    f"le harnais passe sans « {nom} » :\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()
