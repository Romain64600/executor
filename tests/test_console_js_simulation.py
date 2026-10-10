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
            # 2026-09-29 (« quand le sweep a commencé ») : la ligne de début, les heures du
            # marchand, celles des pages.
            "heure de début": ("renderStart(rec, d && d.loop, running);", ""),
            "heures du marchand": ('" · couverture : " + sr.coverage : "") + merchantTimes(t)',
                                   '" · couverture : " + sr.coverage : "")'),
            "heures des pages": ('isStamp(p.finished_at) ? el("span", { class: "pg-t"',
                                 'false ? el("span", { class: "pg-t"'),
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


OVERVIEW_HARNESS = ROOT / "tests" / "js" / "overview.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class OverviewConsoleSimulationTests(unittest.TestCase):
    """La VUE D'ENSEMBLE des VPS (Romain, 2026-09-30 : « Go pour l'onglet vue d'ensemble »),
    exécutée : UP / DOWN et son motif, la tâche en clair, les alertes, l'avertissement de
    version, le rafraîchissement de 15 s et « mis à jour il y a N s », des GET seulement."""

    def test_the_harness_targets_the_shipped_page(self):
        self.assertTrue(OVERVIEW_HARNESS.is_file(), OVERVIEW_HARNESS)
        self.assertIn('"src", "admin", "static", "overview.js"',
                      OVERVIEW_HARNESS.read_text(encoding="utf-8"))

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(OVERVIEW_HARNESS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("tout passe", proc.stdout)

    def test_the_harness_goes_red_on_each_removed_piece(self):
        """Vert ne prouve rien tant que rouge n'est pas prouvé : sans le badge DOWN, sans
        l'avertissement de version, sans le rafraîchissement, sans la garde d'ordre des
        réponses, ou avec un lien de console non filtré, le harnais doit rougir."""

        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "overview.js").read_text(encoding="utf-8")
        mutations = {
            "badge DOWN": ('text: up ? "UP" : "DOWN"', 'text: "UP"'),
            "motif du DOWN": ("if (!up && reasons.length) {", "if (false) {"),
            "avertissement de version": ("const warn = versionWarning(hosts);", "const warn = null;"),
            "rafraîchissement": ("  setInterval(refresh, REFRESH_MS);\n", ""),
            "garde d'ordre": ("  if (seq !== SEQ) return;   // une réponse plus ancienne", "  //"),
            "lien filtré": ("const url = safeUrl(h.console_url);", "const url = h.console_url;"),
            "ligne price check": ("const pcLine = priceCheckLine(s.price_check);", "const pcLine = null;"),
            "âge de la photo": ("a.textContent = ageText(sec);", ""),
            # revue adverse du 2026-09-30
            "garde des alertes": ("const alerts = liste(s.alerts);", "const alerts = s.alerts || [];"),
            "carte isolée": ("hosts.map(cardOrError)", "hosts.map(renderHost)"),
            "balayage interrompu": ("    if (last.interrupted) {", "    if (false) {"),
        }
        for nom, (avant, apres) in mutations.items():
            with self.subTest(nom):
                self.assertIn(avant, js, f"la forme de « {nom} » a changé")
                casse = js.replace(avant, apres, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    faux = pathlib.Path(tmp) / "overview.js"
                    faux.write_text(casse, encoding="utf-8")
                    proc = subprocess.run([NODE, str(OVERVIEW_HARNESS)], cwd=ROOT,
                                          capture_output=True, text=True, timeout=120,
                                          env=dict(os.environ, OVERVIEW_JS=str(faux)))
                self.assertNotEqual(proc.returncode, 0,
                                    f"le harnais passe sans « {nom} » :\n{proc.stdout}")


PRICECHECK_HARNESS = ROOT / "tests" / "js" / "pricecheck.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class PriceCheckConsoleSimulationTests(unittest.TestCase):
    """La page PRICE CHECK, exécutée (2026-10-01). Romain : « ce rapport interactif de price check devrait
    être dans l'admin ». Le harnais charge le vrai ``pricecheck.js``, sert la forme réelle de
    ``api/price-check/reports`` et regarde ce qui s'affiche et ce qui part quand on tranche."""

    def test_the_harness_targets_the_shipped_console(self):
        self.assertTrue(PRICECHECK_HARNESS.is_file(), PRICECHECK_HARNESS)
        self.assertIn('"src", "admin", "static", "pricecheck.js"',
                      PRICECHECK_HARNESS.read_text(encoding="utf-8"))

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(PRICECHECK_HARNESS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertNotIn("FAIL", proc.stdout)

    def test_the_harness_goes_red_on_each_removed_guard(self):
        """Vert ne prouve rien tant que rouge n'est pas prouvé : sans la garde des liens, sans la note
        envoyée, sans le refus affiché, sans les boutons bloqués pendant l'envoi, le harnais rougit."""

        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "pricecheck.js").read_text(encoding="utf-8")
        mutations = {
            "lien sûr": ('const safe = /^https?:\\/\\//i.test(String(url || ""));', "const safe = true;"),
            "note": ("body: JSON.stringify({ offer, decision: key, note })", "body: JSON.stringify({ offer, decision: key })"),
            "refus affiché": ("ERRORS[offer] = e.message;", ""),
            "envoi en cours": ("b.disabled = BUSY.has(offer);", "b.disabled = false;"),
            "export ancien": ('$("#pc-stale").classList.toggle("hidden", !stale);', ""),
            # 02/10/2026 : les deux boutons de lancement
            "mode du lancement": ("body: JSON.stringify({ mode })", "body: JSON.stringify({})"),
            "bouton grisé pendant le passage": ("btn.disabled = !!pending || !!m.running;", "btn.disabled = false;"),
            # 02/10/2026 : le recontrôle (réparées)
            "réparée affichée": ('const pill = isRuleCleared(r) ? T("FAUX POSITIF LEVÉ") : isVerified(r) ? T("VÉRIFIÉE OK") : isFixed(r) ? T("RÉPARÉE") : LANG === "en" && VERDICT_EN[r.verdict] ? VERDICT_EN[r.verdict] : (r.verdict || "?");',
                                 'const pill = r.verdict || "?";'),
            # 03/10/2026 : les reports des tops identifiés de ceux de la homepage
            "mode affiché": ('MODE_BADGE[r.mode] ? el("span"', 'false ? el("span"'),
            "filtre de mode": ("if (m && r.mode !== m) return false;", ""),
            "premier prix affiché": ('isFirstPrice(r) ? el("span"', 'false ? el("span"'),
            "filtre premiers prix": ('if ($("#f-first").checked && !isFirstPrice(r)) return false;', ""),
            "faux positif levé ≠ réparée": ('const isRepaired = (r) => isFixed(r) && r.fixed_kind !== "rule" && r.fixed_kind !== "verified";',
                                            "const isRepaired = (r) => isFixed(r);"),
            # 05/10/2026 : une note tapée après la décision (les commentaires de Rémy, jamais enregistrés)
            "note seule avec Entrée": ("if (cur && unsavedNote(offer, r)) decide(offer, cur);", ""),
            "note non enregistrée signalée": ("pending.hidden = !open;", "pending.hidden = true;"),
            "garde avant de quitter la page": ("if (!reports.some((r) => unsavedNote(String(r.offer), r))) return undefined;",
                                               "return undefined;"),
            # 05/10/2026 : la décision en deux étapes, la note gardée quand on change d'avis
            "note gardée au changement de décision": (
                'const note = NOTES[offer] != null ? NOTES[offer] : ((current.decision && current.decision.note) || "");',
                'const note = NOTES[offer] || "";'),
            "deux étapes": ('el("div", { class: "pc-step pc-step-note" }', 'el("div", { class: "pc-step-note" }'),
            # 05/10/2026 : qui a traité le report
            "traité par, en tête de carte": (
                ': T("✔ Traité par ") + (handledBy(r) || "?") + " · " + labelOf(cur) + (isToFix(r) ? T(" · à corriger") : "") })',
                ': "" })'),
            "filtre traité par": ('if (by === "none" ? !isOpen(r) : by && handledBy(r) !== by) return false;', ""),
            # 05/10/2026 : les reports des tops séparés de ceux de la homepage
            "à discuter, puis les tops, sous leur titre": (
                'for (const [part, cls, label, what, none] of (TAB === "archive" ? ARCHIVE_PARTS : PARTS)) {',
                'for (const [part, cls, label, what, none] of (TAB === "archive" ? ARCHIVE_PARTS : PARTS.slice().reverse())) {'),
            "carte des tops marquée": ('(MODE_CARD[r.mode] ? " " + MODE_CARD[r.mode] : "")', '""'),
            # 05/10/2026 : un report tranché reste quelques secondes avant de quitter la liste
            "report tranché gardé quelques secondes": ("if (!strict && JUST_DONE.has(String(r.offer))) return true;", ""),
            # 06/10/2026 : la partie « À discuter », en tête, bien visible (« il faut pas qu'on l'oublie »)
            "à discuter, une partie à part": ('const partOf = (r) => (isToDiscuss(r) ? "discuss" : MODE_CARD[r.mode] ? r.mode : "");',
                                              'const partOf = (r) => (MODE_CARD[r.mode] ? r.mode : "");'),
            "à discuter toujours affiché": ('if (only && !discuss && part !== "all" && only !== part) continue;', "if (only && only !== part) continue;"),
            "à discuter masqués comptés": (
                "const hidden = discuss ? reports.filter((r) => shownPart(r) === part && shownTab(r) === TAB).length - items.length : 0;",
                "const hidden = 0;"),
            "carte gardée dans la partie où elle a été tranchée": (
                "const shownPart = (r) => { const j = JUST_DONE.get(String(r.offer)); return j && j.part != null ? j.part : partOf(r); };",
                "const shownPart = (r) => partOf(r);"),
            "compteur à discuter": ('kpi("k-discuss" + (n(isToDiscuss) ? " hot" : ""), n(isToDiscuss), T("à discuter")),', ""),
            "question en tête de carte": ('cur === "a_discuter" ? el("div", { class: "pc-question" }',
                                          'false ? el("div", { class: "pc-question" }'),
            # 06/10/2026 : les reports traités archivés dans un autre onglet
            "archives à part": ("const isArchived = (r) => ARCHIVED.has(stateOf(r));", "const isArchived = (r) => false;"),
            "à discuter jamais archivé": ('  if (isToDiscuss(r)) return "discuss";  // jusqu\'à sa décision finale, même réparé\n', ""),
            # 06/10/2026 : « les stats semblent fausses » : un vrai positif pas encore corrigé reste en cours
            "vrai pas corrigé reste en cours": ('if (decisionKey(r) === "vrai") return "tofix";', 'if (decisionKey(r) === "vrai") return "faux";'),
            "premiers prix en erreur, décidés compris": ('kpi("k-first", n((r) => !isArchived(r) && !isFixed(r) && r.verdict',
                                                          'kpi("k-first", n((r) => isOpen(r) && r.verdict'),
            "onglet suivi": ("const shown = reports.filter((r) => matchesFilters(r)).filter((r) => shownTab(r) === TAB);",
                             "const shown = reports.filter((r) => matchesFilters(r));"),
            "carte gardée dans son onglet": (
                "const shownTab = (r) => { const j = JUST_DONE.get(String(r.offer)); return j && j.tab ? j.tab : tabOf(r); };",
                "const shownTab = (r) => tabOf(r);"),
            "lien vers un report archivé": ("if (target) TAB = tabOf(target);", ""),
            # 06/10/2026 : on tranche sur l'offre, pas sur le commentaire : le sens des boutons en clair
            "sens des boutons en clair": ('(cur === "a_discuter" && MEANING[k] ? T(" : ") + MEANING[k] : "")', '""'),
            # Romain, 09/10/2026 : les archives, le plus récent en haut
            "archives par date de règlement": ('    if (TAB === "archive") items.sort(bySettled);\n', ""),
            # 06/10/2026 : une page sortie des tops : la carte le dit
            "sortie des tops affichée": ('r.left_tops_at ? el("span", { class: "pc-left-tops"', 'false ? el("span", { class: "pc-left-tops"'),
            # audit Codex du 06/10/2026 : la 2e carte tranchée disparaissait aussitôt ; une note retouchée pendant l'envoi perdue
            "toutes les cartes tranchées restent": ("reports.filter((r) => matchesFilters(r))", "reports.filter(matchesFilters)"),
            "note retouchée pendant l'envoi gardée": ("if (NOTES[offer] === typed) delete NOTES[offer];", "delete NOTES[offer];"),
            # 06/10/2026 : un widget par concurrent, vert si AllKeyShop est moins cher, rouge sinon
            "couleurs des concurrents": ('const TONE = { "aks": "pc-win", "same": "pc-even", "competitor": "pc-lose" };', 'const TONE = {};'),
            # 06/10/2026 : « couleur orange quand on est au même prix que le concurrent », même dans un ancien relevé
            "même prix en orange": ('"same": "pc-even", ', ''),
            # 06/10/2026 : une page console n'est pas comparée (EA SPORTS FC 27 PS5), ni comptée introuvable
            "page console non comparée": ('r.skipped === "console" ? T("page console, non comparée") : T("introuvable")', 'T("introuvable")'),
            "page console pas introuvable": ('rows.filter((r) => !r.competitor && !r.skipped).length', 'rows.filter((r) => !r.competitor).length'),
            "égalité d'un ancien relevé en orange": ('return cents(r.aks.price) === cents(best.total) ? "same" :',
                                                    'return false ? "same" :'),
            "concurrent bloqué dit pourquoi": ('el("p", { class: "pc-comp-msg", text: TM(site.message) || "" })', 'el("p", { class: "pc-comp-msg" })'),
            # 06/10/2026 : « à la place de l'écart, mets le prix AKS »
            "prix AKS à la place de l'écart": ('el("th", { text: account ? T("Premier compte AKS") : T("Première clé AKS") })',
                                               'el("th", { text: "Écart" })'),
            # 06/10/2026 : « on compare clé avec clé et compte avec compte. On ne mélange pas »
            "comptes à part": ("const accounts = site.accounts || [];", "const accounts = [];"),
            # 06/10/2026 : fee / error, « plus ou moins d'euros », par concurrent, page et genre
            "fee envoyé avec son genre": ("body: JSON.stringify({ site: siteId, page_url: r.page_url, kind, seller, value })",
                                          "body: JSON.stringify({ site: siteId, page_url: r.page_url, seller, value })"),
            # 06/10/2026 : « pourquoi Instant Gaming reste premier prix alors que j'y ai rajouté 20 € ? »
            "fee chez le marchand affiché": ("body: JSON.stringify({ site: siteId, page_url: r.page_url, kind, seller, value })",
                                             "body: JSON.stringify({ site: siteId, page_url: r.page_url, kind, value })"),
            "prix corrigé du fee": ("total: f ? Math.round((o.price + f.value) * 100) / 100 : o.price", "total: o.price"),
            "l'offre suivante prend la place": ("}).sort((x, y) => x.total - y.total || x.price - y.price);", "});"),
            "couleur avec le fee": ("return cents(r.aks.price) === cents(best.total) ? \"same\" : cents(r.aks.price) < cents(best.total) ? \"aks\" : \"competitor\";",
                                    "return r.cheaper;"),
            "fee tapé gardé après un refus": ("box.value = FEE_DRAFTS[key] != null ? FEE_DRAFTS[key] : (best.fee ? feeText(best.fee.value) : \"\");",
                                              "box.value = best.fee ? feeText(best.fee.value) : \"\";"),
            "fee effaçable": ("for (const o of offers.slice(1).filter((x) => x.fee)) {", "for (const o of []) {"),
            # 06/10/2026 : la console, réservée à Romain et à l'équipe ; la récolte à Romain seul
            "console réservée": ('$("#pc-console").classList.toggle("hidden", !d);', '$("#pc-console").classList.toggle("hidden", false);'),
            "récolte réservée à Romain": ('$("#pc-harvest").classList.toggle("hidden", !owner);', '$("#pc-harvest").classList.toggle("hidden", false);'),
            "message envoyé": ('if (await sendChat("api/price-check/console", { text, lang: LANG },', 'if (await sendChat("api/price-check/console", { lang: LANG },'),
            "lien vers l'onglet Romain": ('el("a", { href: "romain", text: "Romain" })', 'el("span", { text: "Romain" })'),
            # 07/10/2026 : « une version anglaise et une version française » de l'admin
            "traduction": ('const T = (fr) => (LANG === "en" &&', 'const T = (fr) => (false &&'),
            "premier prix AKS à côté": ('text: a ? euros(a.price) + " · " + (a.merchant || "?")', 'text: a ? "" + (a.merchant || "?")'),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name):
                self.assertIn(before, js, f"la forme de « {name} » a changé")
                broken = js.replace(before, after, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    fake = pathlib.Path(tmp) / "pricecheck.js"
                    fake.write_text(broken, encoding="utf-8")
                    proc = subprocess.run([NODE, str(PRICECHECK_HARNESS)], cwd=ROOT,
                                          capture_output=True, text=True, timeout=120,
                                          env=dict(os.environ, PRICECHECK_JS=str(fake)))
                self.assertNotEqual(proc.returncode, 0,
                                    f"le harnais passe sans « {name} » :\n{proc.stdout}")



GUIDE_HARNESS = ROOT / "tests" / "js" / "pricecheck-guide.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class PriceCheckGuideSimulationTests(unittest.TestCase):
    """Le GUIDE DE L'ÉQUIPE de la page Price check (2026-10-03), exécuté. Romain : « quelqu'un qui a accès à l'admin
    a accès à ce guide ». La page porte les deux langues ; le script en montre une et garde le choix."""

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(GUIDE_HARNESS)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertNotIn("FAIL", proc.stdout)

    def test_the_harness_goes_red_on_each_removed_guard(self):
        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "pricecheck-guide.js").read_text(encoding="utf-8")
        mutations = {
            "bascule de langue": ('$("#guide-" + l).classList.toggle("hidden", l !== lang);', ""),
            "#en dans l'adresse": ('hash.startsWith("#en") ? "en" : ', ""),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name):
                self.assertIn(before, js, f"la forme de « {name} » a changé")
                with tempfile.TemporaryDirectory() as tmp:
                    fake = pathlib.Path(tmp) / "pricecheck-guide.js"
                    fake.write_text(js.replace(before, after, 1), encoding="utf-8")
                    proc = subprocess.run([NODE, str(GUIDE_HARNESS)], cwd=ROOT, capture_output=True, text=True,
                                          timeout=120, env=dict(os.environ, PRICECHECK_GUIDE_JS=str(fake)))
                self.assertNotEqual(proc.returncode, 0, f"le harnais passe sans « {name} » :\n{proc.stdout}")


ROMAIN_HARNESS = ROOT / "tests" / "js" / "romain.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class RomainTabSimulationTests(unittest.TestCase):
    """L'onglet ROMAIN, exécuté (2026-10-06). Romain : « un onglet Romain où il y a toutes les questions en cours, que
    tout le monde peut consulter, mais il n'y a que moi qui peux agir dessus »."""

    def test_the_harness_targets_the_shipped_page(self):
        self.assertTrue(ROMAIN_HARNESS.is_file(), ROMAIN_HARNESS)
        self.assertIn('"src", "admin", "static", "romain.js"', ROMAIN_HARNESS.read_text(encoding="utf-8"))

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(ROMAIN_HARNESS)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertNotIn("FAIL", proc.stdout)

    def test_the_harness_goes_red_on_each_removed_guard(self):
        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "romain.js").read_text(encoding="utf-8")
        mutations = {
            "boutons réservés à Romain": ("} else if (owner) {", "} else if (true) {"),
            "réponse envoyée": ('body: JSON.stringify({ question: id, note: ANSWERS[id] || "" })', "body: JSON.stringify({ question: id })"),
            "reports à discuter": ('r.decision.decision === "a_discuter"', "false"),
            "réglée une seule fois": ("SENT.add(id);", ""),
            "traduction": ('const T = (fr) => (LANG === "en" &&', 'const T = (fr) => (false &&'),
            "refus affiché": ('setStatus(id + T(" non réglée : ") + e.message, false);', ""),
        }
        for name, (before, after) in mutations.items():
            with self.subTest(name):
                self.assertIn(before, js, f"la forme de « {name} » a changé")
                with tempfile.TemporaryDirectory() as tmp:
                    fake = pathlib.Path(tmp) / "romain.js"
                    fake.write_text(js.replace(before, after, 1), encoding="utf-8")
                    proc = subprocess.run([NODE, str(ROMAIN_HARNESS)], cwd=ROOT, capture_output=True, text=True,
                                          timeout=120, env=dict(os.environ, ROMAIN_JS=str(fake)))
                self.assertNotEqual(proc.returncode, 0, f"« {name} » retiré, le harnais reste vert :\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()


URLS_LISTS_HARNESS = ROOT / "tests" / "js" / "urls_lists.test.mjs"


@unittest.skipIf(NODE is None, "node absent (dépendance de test)")
class UrlsListsConsoleSimulationTests(unittest.TestCase):
    """La saisie par jeu, EXÉCUTÉE (Romain, 2026-10-06 : « que l'opérateur puisse choisir les
    listes ; toutes cochées par défaut, sauf la blacklist ») : le catalogue dessiné en cases,
    les blacklists décochées et grisées, le corps du lancement qui porte les listes cochées, le
    refus sans aucune liste, et le lot du GO groupé par (magasin, liste)."""

    def test_the_harness_targets_the_shipped_console(self):
        self.assertTrue(URLS_LISTS_HARNESS.is_file(), URLS_LISTS_HARNESS)
        self.assertIn('"src", "admin", "static", "urls.js"',
                      URLS_LISTS_HARNESS.read_text(encoding="utf-8"))

    def test_every_scenario_passes(self):
        proc = subprocess.run([NODE, str(URLS_LISTS_HARNESS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("tout passe", proc.stdout)

    def test_the_harness_goes_red_on_each_removed_piece(self):
        import os
        import tempfile
        js = (ROOT / "src" / "admin" / "static" / "urls.js").read_text(encoding="utf-8")
        mutations = {
            "toutes cochées par défaut": ("    inp.checked = true;                      // toutes cochées par défaut (Romain, 06/10)\n",
                                          "    inp.checked = false;\n"),
            "blacklist grisée": ("    inp.disabled = true;                     // une blacklist n'est pas une liste de travail\n",
                                 "    inp.disabled = false;\n"),
            "les listes dans le corps du lancement": ("consoles: $(\"#consoles\").checked, lists })", "consoles: $(\"#consoles\").checked })"),
            "refus sans liste": ("  if (!lists.length) {\n    $(\"#launch-msg\").textContent = \"✖ Coche au moins une liste AKS à chercher.\";",
                                 "  if (false) {\n    $(\"#launch-msg\").textContent = \"✖ Coche au moins une liste AKS à chercher.\";"),
            "un lot par (magasin, liste)": ("      const gk = sid + \"|\" + lid;", "      const gk = sid;"),
            "la liste sur le bloc marchand": ("      const listTxt = per.list_id ? \" · liste \" + per.list_id", "      const listTxt = false ? \" · liste \" + per.list_id"),
        }
        for nom, (avant, apres) in mutations.items():
            with self.subTest(nom):
                self.assertIn(avant, js, f"la forme de « {nom} » a changé")
                casse = js.replace(avant, apres, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    faux = pathlib.Path(tmp) / "urls.js"
                    faux.write_text(casse, encoding="utf-8")
                    proc = subprocess.run([NODE, str(URLS_LISTS_HARNESS)], cwd=ROOT,
                                          capture_output=True, text=True, timeout=120,
                                          env=dict(os.environ, URLS_JS=str(faux)))
                self.assertNotEqual(proc.returncode, 0,
                                    f"le harnais passe sans « {nom} » :\n{proc.stdout}")
