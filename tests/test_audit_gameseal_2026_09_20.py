"""Audit GameSeal du 2026-09-20 — les correctifs, chacun ancré sur une offre réelle.

Contexte : le balayage `20260919-082932-auto` a écrit 1 090 offres GameSeal (pages 103→46).
Les écritures étaient justes à une près ; l'essentiel des constats portait sur ce qui N'A PAS
été écrit. Chaque classe ci-dessous verrouille un correctif, avec l'offre qui l'a révélé.

Romain, 2026-09-20 : « Le correctif que tu veux » — les cinq décisions prises ici sont donc
miennes, et chacune est mesurée sur le corpus écrit avant d'être appliquée.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts import NormalizedOffer                                   # noqa: E402
from src.data_entry_auto import (                                           # noqa: E402
    ExtractOutcome, MatchOutcome, Stages, SweepConfig, run_sweep,
)
from src.matcher import (                                                   # noqa: E402
    AksResolution, Candidate, SkippedOffer, build_slug_candidates,
    match_extras_to_page_edition, match_offer,
)
from src.merchants import gameseal                                          # noqa: E402


def _load_match_cli():
    """Le script est chargé depuis son TEXTE (jamais depuis __pycache__ : un .pyc périmé a
    déjà fait passer une mutation pour détectée le 19/09)."""

    path = ROOT / "scripts" / "03_match.py"
    spec = importlib.util.spec_from_loader("m03_cli_gs", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def _load_sweep_cli():
    """`scripts/10`, compilé depuis son texte (jamais depuis __pycache__)."""

    path = ROOT / "scripts" / "10_data_entry_auto.py"
    spec = importlib.util.spec_from_loader("m10_cli_gs", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def _page(editions, *, aks_name, regions=None, platforms=("Steam",), slug="s"):
    return AksResolution(slug=slug, url="https://aks/x", product_id="1", aks_name=aks_name,
                         editions=editions, regions=regions or {"2": "GLOBAL", "9": "EU"},
                         official_platforms=platforms)


class TheRegionTailLeavesTheProbedSlug(unittest.TestCase):
    """`src/merchants/gameseal.py::resolve_name` — 44 offres EU perdues sur un tiret collé.

    « Zombies Invasion (PC) Steam Gift- EU » sondait `zombies-invasion-steam-gift-eu` :
    le nettoyage générique ne connaît « GLOBAL » que par sa liste de bruit (EU n'y est pas)
    et son découpage de queue exige un tiret ENTOURÉ d'espaces. 44 offres, 0 création, alors
    que les EU bien espacées entrent à 66 %."""

    REELLES = {
        "Zombies Invasion (PC) Steam Gift- EU": "zombies-invasion",
        "ZeroRanger (PC) Steam Gift- EU": "zeroranger",
        "Wild Frontera (PC) Steam Key -EU": "wild-frontera",           # tiret collé à droite
        "Bad Guys at School (PC) Steam Gift- EU": "bad-guys-at-school",
        "NieR:Automata (PC) Steam Key - GLOBAL": "nier-automata",       # cas déjà sain
        "War Thunder - US Starter Bundle (DFC) (PC) Steam Gift – GLOBAL":
            "war-thunder-us-starter-bundle",                            # tiret demi-cadratin
    }

    def test_the_bare_slug_is_probed_for_every_real_row(self):
        for title, slug in self.REELLES.items():
            with self.subTest(title=title):
                cands = build_slug_candidates(gameseal.resolve_name(title))
                self.assertIn(slug, cands, f"{title!r} → {cands}")

    def test_the_junk_slug_is_gone(self):
        cands = build_slug_candidates(gameseal.resolve_name("Zombies Invasion (PC) Steam Gift- EU"))
        self.assertNotIn("zombies-invasion-steam-gift-eu", cands)

    def test_a_game_whose_name_ends_in_gift_keeps_its_name(self):
        """La pelure magasin+livraison n'est faite QU'UNE fois, donc « Christmas Gift Steam
        Key » redevient « Christmas Gift » et jamais « Christmas ».

        (Le nettoyage GÉNÉRIQUE, lui, retire de toute façon un « Gift » de queue pour bâtir
        le slug — c'est son comportement d'avant, hors du périmètre de ce hook : ce test
        verrouille ce que le FICHIER MARCHAND rend, pas ce que le slug devient.)"""

        self.assertEqual(gameseal.resolve_name("Christmas Gift Steam Key - EU"), "Christmas Gift")
        self.assertEqual(gameseal.resolve_name("Gift of Life (PC) Steam Key - GLOBAL"),
                         "Gift of Life (PC)")

    def test_the_console_platform_block_survives_the_peel(self):
        peeled = gameseal.resolve_name(
            "Another World - 20th Anniversary Edition (Xbox One / Xbox Series X|S) Xbox Live Key - EU")
        self.assertEqual(peeled, "Another World - 20th Anniversary Edition (Xbox One / Xbox Series X|S)")

    def test_the_hook_is_declared_in_the_config(self):
        from src.merchants.registry import MERCHANT_CONFIGS

        self.assertIs(MERCHANT_CONFIGS["GAMESEAL"].resolve_name, gameseal.resolve_name)

    def test_an_empty_or_unreadable_title_never_raises(self):
        for title in ("", "   ", "Steam Key - EU", "- GLOBAL"):
            with self.subTest(title=title):
                self.assertIsInstance(gameseal.resolve_name(title), str)


class TheDigitalFormatWordIsNotAProduct(unittest.TestCase):
    """`src/matcher.py::_TRAILING_EDITION_PHRASES` — « Alien: Isolation Digital Deluxe
    Edition » s'arrêtait sur `alien-isolation-digital`, jamais sur `alien-isolation`."""

    def test_the_base_slug_becomes_reachable(self):
        self.assertIn("alien-isolation",
                      build_slug_candidates("Alien: Isolation Digital Deluxe Edition (PC)"))

    def test_the_specific_page_is_still_probed_first(self):
        cands = build_slug_candidates("Alien: Isolation Digital Deluxe Edition (PC)")
        self.assertEqual(cands[0], "alien-isolation-digital-deluxe-edition")

    def test_definitive_remastered_anniversary_keep_their_word(self):
        """Ces trois-là n'ont AUCUN seau dans EDITION_HINTS : atteindre la page de base leur
        donnerait Standard(1) sur un AUTRE produit. 15 lignes justes du balayage en dépendent."""

        for title, interdit in (
            ("Age of Empires III: Definitive Edition (PC)", "age-of-empires-iii"),
            ("StarCraft: Remastered (PC)", "starcraft"),
            ("Beyond Good & Evil 20th Anniversary Edition (PC)", "beyond-good-evil-20th"),
        ):
            with self.subTest(title=title):
                self.assertNotIn(interdit, build_slug_candidates(title))


class TheGotyAliasIsAppliedByTheEditionRescue(unittest.TestCase):
    """`src/matcher.py::match_extras_to_page_edition` — l'alias GOTY existait depuis
    `_EDITION_LABEL_ALIASES` mais le sauvetage comparait des tokens BRUTS.

    « Fallout 4: Game of the Year Edition » (offre 100713069) sortait « extra words:
    ['YEAR'] » alors que son jumeau « Fallout 4 GOTY Edition » (100709222) entrait le même
    jour sur le MÊME produit 6675 en GOTY(9)."""

    def test_the_page_goty_bucket_answers_a_game_of_the_year_title(self):
        self.assertEqual(match_extras_to_page_edition({"YEAR"}, {"9": "GOTY"}), ("9", "GOTY"))

    def test_it_still_answers_next_to_a_standard_bucket(self):
        self.assertEqual(
            match_extras_to_page_edition({"YEAR"}, {"1": "Standard", "9": "GOTY"}), ("9", "GOTY"))

    def test_the_endorsed_knights_rescue_is_untouched(self):
        self.assertEqual(
            match_extras_to_page_edition({"KNIGHTS"}, {"2723": "Knights Editon"}),
            ("2723", "Knights Editon"))

    def test_a_tier_word_in_the_residue_still_fails_closed(self):
        """Fable 2026-09-06 : un extra compatible ne doit JAMAIS faire monter de palier."""

        self.assertIsNone(match_extras_to_page_edition({"KNIGHTS"}, {"7": "Knights Deluxe Edition"}))


class R18StandsDownOnATierThePageDoesNotName(unittest.TestCase):
    """`src/matcher.py` [R18b] — la seule écriture fausse du balayage.

    Offre 100700366, page 72 : « Call of Duty: Black Ops III Zombies Chronicles Deluxe
    Edition (PC) Steam Gift - GLOBAL » écrite en DLC(16) sur `…-zombies-chronicles`, la page
    du DLC seul. `detect_edition` lisait bien Deluxe(7) ; R18 s'exécutait avant et l'écrasait.

    Mesure avant application sur 1 818 lignes écrites (GameSeal + le crible de 728) : 43 en
    DLC(16), 10 sans marqueur de DLC, UNE SEULE bascule — celle-ci."""

    def _match(self, title, aks_name, editions, slug="s"):
        offer = NormalizedOffer(offer_id="1", name=title,
                                url="https://gameseal.com/x-pc-steam-gift-global",
                                merchant="GameSeal")
        return match_offer(offer,
                           resolver=lambda n, **k: _page(editions, aks_name=aks_name, slug=slug))

    def test_the_wrong_write_becomes_a_refusal(self):
        res = self._match(
            "Call of Duty: Black Ops III Zombies Chronicles Deluxe Edition (PC) Steam Gift - GLOBAL",
            "Call of Duty Black Ops III Zombies Chronicles", {"16": "DLC"})
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("not sold on the resolved", res.reason)

    def test_a_tier_the_page_also_names_keeps_R18(self):
        """« Wortox Deluxe Chest » sur la page du même nom : la page EST ce produit."""

        res = self._match("Don't Starve Together Wortox Deluxe Chest (PC) Steam Gift - GLOBAL",
                          "Don't Starve Together Wortox Deluxe Chest", {"16": "DLC"})
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_the_markerless_hidden_dlc_still_enters(self):
        """La décision de Romain du 17/09 est intacte : un DLC caché SANS palier garde sa
        page mono-seau et entre en DLC(16)."""

        res = self._match("Surviving Mars Exoplanets Pack (PC) Steam Key - GLOBAL",
                          "Surviving Mars Exoplanets Pack", {"16": "DLC"})
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_a_marked_dlc_is_out_of_scope(self):
        """Un titre MARQUÉ relève de R43 : le palier ne le concerne pas."""

        res = self._match("Cities: Skylines - Financial Districts (DLC) (PC) Steam Key - GLOBAL",
                          "Cities Skylines Financial Districts", {"1": "Standard", "16": "DLC"},
                          slug="cities-skylines-financial-districts")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))


class ThePlayAnywhereGuardStaysInItsDomain(unittest.TestCase):
    """`src/matcher.py` (f) — le motif nommait Xbox pour une clé Nintendo.

    Offre 100703022, « FINAL FANTASY VIII - REMASTERED (PC) (Nintendo Switch) Nintendo Key
    - EU », refusée 22 fois (pages 93→72) avec « merchant declares Xbox + PC » alors que
    `classify_console` ne déclare que SWITCH. Xbox Play Anywhere n'existe ni sur Nintendo ni
    sur PlayStation (docs/EXECUTOR_RULES.md §4.12 P2 : « next to an Xbox family »).

    Le refus RESTE — une clé eShop ne s'active pas sur PC, la déclaration marchande se
    contredit — c'est le MOTIF qui devient vrai."""

    URL_SWITCH = "https://gameseal.com/hades-pc-nintendo-switch-nintendo-key-eu"
    URL_XBOX = "https://gameseal.com/hades-pc-xbox-one-xbox-live-key-eu"

    def _switch_page(self):
        return AksResolution(
            slug="s", url="https://aks/sw", product_id="1", aks_name="Hades",
            editions={"1": "Standard"}, regions={"99eu": "EU", "99": "GLOBAL"},
            official_platforms=("Nintendo",),
            console_pages={"nintendo-switch": "https://aks/sw", "cd-key": "https://aks/pc"})

    def _pc_page(self, platforms=("Steam",)):
        return AksResolution(slug="pc", url="https://aks/pc", product_id="1", aks_name="Hades",
                             editions={"1": "Standard"}, regions={"2": "GLOBAL", "9": "EU"},
                             official_platforms=platforms)

    def _match(self, title, url, target, pc_page):
        offer = NormalizedOffer(offer_id="1", name=title, url=url, merchant="GameSeal")
        return match_offer(offer, resolver=lambda n, **k: target,
                           page_resolver=lambda u: (pc_page if "pc" in u else target),
                           consoles=True)

    def test_a_switch_key_is_not_refused_in_the_name_of_xbox(self):
        res = self._match("Hades (PC) (Nintendo Switch) Nintendo Key - EU",
                          self.URL_SWITCH, self._switch_page(), self._pc_page())
        self.assertIsInstance(res, SkippedOffer)
        self.assertNotIn("Xbox Play Anywhere", res.reason)
        self.assertIn("contradictory delivery", res.reason)
        self.assertIn("SWITCH", res.reason)

    def test_an_xbox_key_without_play_anywhere_keeps_its_own_refusal(self):
        res = self._match("Hades (PC) (Xbox One) Xbox Live Key - EU",
                          self.URL_XBOX, self._switch_page(), self._pc_page())
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("Xbox Play Anywhere", res.reason)


class TheSearchCircuitBreakerExpires(unittest.TestCase):
    """`scripts/03_match.py::_search_circuit_is_open` — « portée balayage » voulait dire 30 h.

    Le balayage 20260919-082932 a ouvert le disjoncteur 66 secondes après son démarrage
    (5 échecs pendant Gamivo), 7 heures avant que GameSeal ne commence : ses 60 pages ont
    résolu au slug seul, sans jamais chercher. 434 offres DISTINCTES en sont ressorties
    « no AKS product page found »."""

    def setUp(self):
        self.MOD = _load_match_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "search_circuit.json")

    def _write(self, written_at, *, open_=True):
        Path(self.path).write_text(json.dumps({"open": open_, "search_failures": 5,
                                               "written_at": written_at}), encoding="utf-8")

    def test_a_fresh_marker_still_silences_the_search(self):
        self._write("2026-09-19T08:30:38Z")
        with mock.patch.object(self.MOD.time, "time", return_value=self._epoch("2026-09-19T08:40:00Z")):
            self.assertTrue(self.MOD._search_circuit_is_open(self.path))

    def test_the_marker_of_the_gameseal_sweep_would_have_expired(self):
        self._write("2026-09-19T08:30:38Z")
        with mock.patch.object(self.MOD.time, "time", return_value=self._epoch("2026-09-19T15:27:00Z")):
            self.assertFalse(self.MOD._search_circuit_is_open(self.path))

    def test_the_window_edge(self):
        self._write("2026-09-19T08:30:38Z")
        base = self._epoch("2026-09-19T08:30:38Z")
        with mock.patch.object(self.MOD.time, "time", return_value=base + self.MOD.SEARCH_CIRCUIT_TTL_S - 1):
            self.assertTrue(self.MOD._search_circuit_is_open(self.path))
        with mock.patch.object(self.MOD.time, "time", return_value=base + self.MOD.SEARCH_CIRCUIT_TTL_S + 1):
            self.assertFalse(self.MOD._search_circuit_is_open(self.path))

    def test_a_closed_or_unreadable_or_undated_marker_is_not_open(self):
        self._write("2026-09-19T08:30:38Z", open_=False)
        self.assertFalse(self.MOD._search_circuit_is_open(self.path))
        Path(self.path).write_text('{"open": true}', encoding="utf-8")     # sans date
        self.assertFalse(self.MOD._search_circuit_is_open(self.path))
        Path(self.path).write_text("pas du json", encoding="utf-8")
        self.assertFalse(self.MOD._search_circuit_is_open(self.path))
        self.assertFalse(self.MOD._search_circuit_is_open(None))

    def _epoch(self, stamp):
        import calendar as _c
        import time as _t
        return _c.timegm(_t.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))


class TheWarhammer40kSpellingIsFoldedOnBothSides(unittest.TestCase):
    """`src/matcher.py::fold_franchise_spellings` — le seul constat que l'audit avait laissé
    en attente d'une lecture en ligne.

    Les marchands écrivent « Warhammer 40,000 », AKS écrit « Warhammer 40K ». Vérifié le
    2026-09-20 sur six pages vivantes (`warhammer-40k-darktide`, `…-space-marine-2`,
    `…-boltgun`, `…-rogue-trader`, `…-gladius-relics-of-war`, `…-battlesector`) ; ni
    `warhammer-40000-…` ni `warhammer-40-000-…` n'existent. La ligne échouait DEUX fois : le
    slug sondé 404, puis la garde d'identité (« missing AKS words: ['40K'] »)."""

    TITRE = "Warhammer 40,000: Battlesector (PC) Steam Gift - EU"

    def test_both_spellings_tokenize_the_same(self):
        from src.matcher import tokenize

        self.assertEqual(tokenize("Warhammer 40,000: Battlesector"),
                         tokenize("Warhammer 40K Battlesector"))

    def test_the_aks_slug_becomes_reachable(self):
        self.assertEqual(build_slug_candidates(gameseal.resolve_name(self.TITRE)),
                         ["warhammer-40k-battlesector"])

    def test_the_row_enters_end_to_end(self):
        page = AksResolution(slug="warhammer-40k-battlesector", url="https://aks/x",
                             product_id="1", aks_name="Warhammer 40K Battlesector",
                             editions={"1": "Standard"}, regions={"2": "GLOBAL", "9": "EU"},
                             official_platforms=("Steam",))
        offer = NormalizedOffer(
            offer_id="1", name=self.TITRE, merchant="GameSeal",
            url="https://gameseal.com/warhammer-40-000-battlesector-pc-steam-gift-eu")
        res = match_offer(offer, resolver=lambda n, **k: page)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.region_id, res.edition_id), ("259", "1"))   # Steam Gift EU

    def test_other_comma_numbers_are_untouched(self):
        """Le repli est une orthographe de FRANCHISE vérifiée, pas une règle de nombres :
        AKS ne réécrit pas « 10,000 » en « 10K »."""

        from src.matcher import tokenize

        self.assertEqual(tokenize("10,000,000"), ["10", "000", "000"])
        self.assertEqual(tokenize("Sid Meier's Civilization VI"), ["SID", "MEIERS", "CIVILIZATION", "6"])


class TheSweepMeasuresOffersNotPages(unittest.TestCase):
    """`src/data_entry_auto.py` — « 58 pages faites » ne disait pas ce qu'elles contenaient.

    Sur 20260919-082932, les pages 86→73 ont rendu QUATORZE FOIS la même centaine d'offres
    (empreinte identique) et 58→53 six fois de plus : 5 861 lignes lues pour 2 059 distinctes.
    Le recap publiait `coverage: null`."""

    def _stages(self, ids_par_page):
        def extract(page, run_id):
            return ExtractOutcome(ok=True, offers=len(ids_par_page[page]), feed_last_page=3)

        return Stages(
            offer_ids=lambda run_id: tuple(ids_par_page[int(run_id.rsplit("p", 1)[1])]),
            extract=extract,
            match=lambda run_id: MatchOutcome(ok=True, candidates=0),
            approve=lambda run_id: 0,
            submit=lambda run_id: None,
        )

    def _run(self, ids_par_page):
        cfg = SweepConfig(merchant="GameSeal", store_id="126", max_pages=None)
        return run_sweep(cfg, self._stages(ids_par_page), page_run_id=lambda p: f"r-p{p}")

    def test_a_repeated_page_is_named_in_the_recap(self):
        memes = ["a", "b", "c"]
        recap = self._run({1: memes, 2: memes, 3: memes})
        pages = [p for p in recap["pages"] if p.get("repeated_page")]
        self.assertEqual([p["page"] for p in pages], [2, 1])     # la 3 est servie la première
        self.assertEqual(recap["pages_without_new_offers"], [2, 1])
        self.assertEqual(recap["distinct_offers"], 3)
        self.assertIn("incomplete_repeated_pages", recap["coverage"])

    def test_distinct_pages_leave_the_coverage_clean(self):
        recap = self._run({1: ["a"], 2: ["b"], 3: ["c"]})
        self.assertEqual(recap["pages_without_new_offers"], [])
        self.assertEqual(recap["distinct_offers"], 3)
        self.assertIsNone(recap["coverage"])
        self.assertTrue(all(p.get("new_offers") == 1 for p in recap["pages"]))

    def test_a_cap_still_wins_the_coverage_line(self):
        memes = ["a"]
        cfg = SweepConfig(merchant="GameSeal", store_id="126", max_pages=2)
        recap = run_sweep(cfg, self._stages({1: memes, 2: memes, 3: memes}),
                          page_run_id=lambda p: f"r-p{p}")
        self.assertIn("incomplete_max_pages", recap["coverage"])

    def test_the_measure_is_optional_and_never_fails_a_sweep(self):
        """`offer_ids=None` (ou qui lève) = le balayage d'avant, à l'identique."""

        cfg = SweepConfig(merchant="GameSeal", store_id="126", max_pages=None)
        stages = self._stages({1: ["a"], 2: ["a"], 3: ["a"]})
        recap = run_sweep(cfg, Stages(extract=stages.extract, match=stages.match,
                                      approve=stages.approve, submit=stages.submit),
                          page_run_id=lambda p: f"r-p{p}")
        self.assertEqual(recap["pages_without_new_offers"], [])
        self.assertIsNone(recap["coverage"])

        def boom(run_id):
            raise OSError("offers.json illisible")

        recap = run_sweep(cfg, Stages(offer_ids=boom, extract=stages.extract, match=stages.match,
                                      approve=stages.approve, submit=stages.submit),
                          page_run_id=lambda p: f"r-p{p}")
        self.assertIsNone(recap["halted"])
        self.assertIsNone(recap["coverage"])


class AStageCrashLeavesItsReason(unittest.TestCase):
    """`src/child_runner.py` + `scripts/10` — troisième perte de motif en deux jours.

    Le 19/09 un submit sortait en 2 sans rien dire (corrigé : chaque abandon fail-closed
    écrit un évènement). Le 20/09 l'extract de la page 7 du run `20260920-154717` a CRASHÉ
    (exit 1) AVANT de créer son journal : aucun évènement possible, traceback jeté avec la
    sortie de l'enfant, recap réduit à « extract: exit 1 ». La sortie des stages est
    désormais appendue dans `logs/<run-de-page>-stages.log`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_runner_appends_stdout_and_stderr_to_the_file(self):
        from src.child_runner import CooperativeChildRunner

        out = self.root / "stages.log"
        rc = CooperativeChildRunner().run(
            [sys.executable, "-c", "import sys; print('resume'); print('boom', file=sys.stderr); sys.exit(1)"],
            str(self.root), output_path=str(out))
        self.assertEqual(rc, 1)
        body = out.read_text(encoding="utf-8")
        self.assertIn("resume", body)
        self.assertIn("boom", body)

        rc = CooperativeChildRunner().run([sys.executable, "-c", "print('seconde page')"],
                                          str(self.root), output_path=str(out))
        self.assertEqual(rc, 0)
        self.assertIn("resume", out.read_text(encoding="utf-8"))      # appendu, jamais écrasé

    def test_an_unwritable_path_never_fails_the_stage(self):
        from src.child_runner import CooperativeChildRunner

        rc = CooperativeChildRunner().run([sys.executable, "-c", "pass"], str(self.root),
                                          output_path=str(self.root / "nulle-part" / "x.log"))
        self.assertEqual(rc, 0)

    def test_the_sweep_reads_the_exception_line_back(self):
        MOD = _load_sweep_cli()
        MOD.ROOT = self.root
        (self.root / "logs").mkdir(parents=True)
        (self.root / "logs" / "r-p7-stages.log").write_text(
            "max-pages: auto\nTraceback (most recent call last):\n"
            '  File "scripts/02_extract_feed.py", line 80, in main\n'
            "ConnectionResetError: [Errno 104] Connection reset by peer\n", encoding="utf-8")
        self.assertEqual(MOD._stage_crash_tail("r-p7"),
                         "ConnectionResetError: [Errno 104] Connection reset by peer")

    def test_a_crashed_extract_carries_the_reason_into_the_recap(self):
        MOD = _load_sweep_cli()
        MOD.ROOT = self.root
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / "logs" / "r-p7-stages.log").write_text(
            "Traceback (most recent call last):\nRuntimeError: CDP a disparu\n", encoding="utf-8")
        with mock.patch.object(MOD, "_run_child", return_value=1):
            stages = MOD._make_stages("Gamerall", "13", "all", None)
            ex = stages.extract(7, "r-p7")
        self.assertFalse(ex.ok)
        self.assertEqual(ex.detail, "exit 1 (RuntimeError: CDP a disparu)")

    def test_a_logged_abort_still_wins_over_the_raw_output(self):
        MOD = _load_sweep_cli()
        MOD.ROOT = self.root
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / "logs" / "r-p7.jsonl").write_text(
            json.dumps({"event": "aborted", "reason": "not logged in (wp-login)", "run_id": "r-p7"}) + "\n",
            encoding="utf-8")
        (self.root / "logs" / "r-p7-stages.log").write_text("RuntimeError: bruit\n", encoding="utf-8")
        with mock.patch.object(MOD, "_run_child", return_value=2):
            ex = MOD._make_stages("Gamerall", "13", "all", None).extract(7, "r-p7")
        self.assertEqual(ex.detail, "exit 2 (not logged in (wp-login))")

    def test_a_crashed_SUBMIT_carries_the_reason_too(self):
        """Revue de Romain (2026-09-21, 8c2f7d8 → e596cd3) : « le récapitulatif reste muet
        sur les crashs du submitter — submit() ne consulte que les événements aborted ».
        Exact : extract et match avaient le recours, pas submit. Ce test l'épingle."""

        MOD = _load_sweep_cli()
        MOD.ROOT = self.root
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / "logs" / "r-p9-stages.log").write_text(
            "REAL SUBMISSION (mode=safe)\nTraceback (most recent call last):\n"
            "ConnectionResetError: [Errno 104] Connection reset by peer\n", encoding="utf-8")
        (self.root / "runs" / "r-p9").mkdir(parents=True, exist_ok=True)
        (self.root / "runs" / "r-p9" / "submit_plan.json").write_text(
            json.dumps({"plan": [], "aborted": None}), encoding="utf-8")
        with mock.patch.object(MOD, "_run_child", return_value=1):
            sub = MOD._make_stages("GameSeal", "126", "all", None).submit("r-p9")
        self.assertFalse(sub.ok)
        self.assertEqual(sub.detail,
                         "exit 1 (ConnectionResetError: [Errno 104] Connection reset by peer)")

    def test_a_logged_submit_abort_still_wins(self):
        MOD = _load_sweep_cli()
        MOD.ROOT = self.root
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / "logs" / "r-p9.jsonl").write_text(
            json.dumps({"event": "aborted", "reason": "invariants not green", "run_id": "r-p9"}) + "\n",
            encoding="utf-8")
        (self.root / "logs" / "r-p9-stages.log").write_text("RuntimeError: bruit\n", encoding="utf-8")
        (self.root / "runs" / "r-p9").mkdir(parents=True, exist_ok=True)
        (self.root / "runs" / "r-p9" / "submit_plan.json").write_text(
            json.dumps({"plan": [], "aborted": None}), encoding="utf-8")
        with mock.patch.object(MOD, "_run_child", return_value=2):
            sub = MOD._make_stages("GameSeal", "126", "all", None).submit("r-p9")
        self.assertEqual(sub.detail, "exit 2 (invariants not green)")

    def test_a_clean_stage_says_nothing(self):
        MOD = _load_sweep_cli()
        MOD.ROOT = self.root
        (self.root / "runs" / "r-p7").mkdir(parents=True)
        (self.root / "runs" / "r-p7" / "offers.json").write_text(
            json.dumps({"offer_count": 3, "feed_last_page": 9}), encoding="utf-8")
        with mock.patch.object(MOD, "_run_child", return_value=0):
            ex = MOD._make_stages("Gamerall", "13", "all", None).extract(7, "r-p7")
        self.assertTrue(ex.ok)
        self.assertEqual(ex.detail, "")


class LaRevueDuVingtEtUnSeptembre(unittest.TestCase):
    """Revue de Romain, e596cd3 → 5d163e1 : quatre points, quatre reproductions.

    Aucun des 700 tests ciblés qu'il a lancés ne les couvrait — ceux-ci les couvrent."""

    # ── [P1] E06 ne doit pas adopter un seau BUNDLE ────────────────────────────────
    def test_e06_ne_prend_jamais_un_bundle(self):
        """« Une offre Standard face à une page {8: Bundle} devient un candidat Bundle.
        L'adoption du seul seau intervient après le contrôle anti-bundle et le contourne. »"""

        offer = NormalizedOffer(offer_id="1", name="Neon Beats (PC) Steam Key - GLOBAL",
                                url="https://gameseal.com/x-pc-steam-key-global", merchant="GameSeal")
        for editions in ({"8": "Bundle"}, {"4711": "Deluxe Pack"}, {"77": "Trilogy"}):
            with self.subTest(editions=editions):
                res = match_offer(offer, resolver=lambda n, **k: _page(editions, aks_name="Neon Beats"))
                self.assertIsInstance(res, SkippedOffer, f"{editions} ne doit JAMAIS entrer")
                self.assertIn("bundle", res.reason.lower())

    def test_e06_adopte_toujours_un_seau_legitime(self):
        offer = NormalizedOffer(offer_id="1", name="Neon Beats (PC) Steam Key - GLOBAL",
                                url="https://gameseal.com/x-pc-steam-key-global", merchant="GameSeal")
        res = match_offer(offer, resolver=lambda n, **k: _page({"5": "Early Access"}, aks_name="Neon Beats"))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "5")

    # ── [P1] la branche compte ne doit pas produire une clé ────────────────────────
    def _difmark(self, url, offer_name, raw_platform="STEAM", raw_region="GLOBAL"):
        from src.merchants.difmark import DifmarkOfferAttributes

        offer = NormalizedOffer(offer_id="1", name="Un Jeu Standard Edition", url=url,
                                merchant="Difmark")
        attrs = DifmarkOfferAttributes(raw_platform=raw_platform, raw_region=raw_region,
                                       offer_name=offer_name)
        page = _page({"1": "Standard"}, aks_name="Un Jeu")
        return match_offer(offer, resolver=lambda n, **k: page,
                           difmark_offer_resolver=lambda u: attrs, consoles=True)

    def test_un_offer_name_vide_ne_devient_pas_une_cle(self):
        """La reproduction de Romain : URL ps5-account, titre sans « (Account) », API STEAM,
        offer_name VIDE → c'était un candidat sur la page de clé, région GLOBAL(2)."""

        res = self._difmark("https://difmark.com/en/buy-console-account-un-jeu-ps5-account-1", "")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("offer_name vide", res.reason)

    def test_une_url_ps5_contre_une_page_steam_est_une_contradiction(self):
        res = self._difmark("https://difmark.com/en/buy-console-account-un-jeu-ps5-account-1",
                            "Un Jeu (Steam Account)")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("contradictoire", res.reason)

    def test_une_vraie_cle_difmark_passe_toujours(self):
        """Le segment « account » de l'URL est du GABARIT chez Difmark : il ne doit pas, à
        lui seul, refuser une vraie clé (sinon on casserait le chemin historique)."""

        res = self._difmark("https://difmark.com/en/buy-console-account-un-jeu-steam-account-1",
                            "Un Jeu (Steam)")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))

    # ── [P1] un scan d'une autre liste n'est pas une mesure du pending ─────────────
    def test_un_scan_de_la_liste_30_nest_pas_une_mesure_pour_la_9(self):
        """« Avec --list 30, le plan déclare encore la liste 9. La vue SQL sélectionne ce
        scan comme complet et "mesuré", alors que ses requêtes ciblent listId=9. »"""

        import tempfile
        from src.admin.sort_sql_view import sort_sql_payload

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "runs" / "scan30"
            d.mkdir(parents=True)
            (d / "offers.json").write_text(json.dumps({"offers": [
                {"offer_id": "1", "name": "Jeu", "url": "https://m.test/a-gift-card-20"}]}),
                encoding="utf-8")
            (d / "sort_plan.json").write_text(json.dumps({
                "by_list": {}, "unrouted": [], "source_list": 30,
                "coverage": {"truncated": False}}), encoding="utf-8")
            payload = sort_sql_payload(Path(tmp) / "runs", "scan30", repo_root=Path(tmp))
        self.assertFalse(payload["measured"])
        self.assertIn("liste 30", payload["note"])
        self.assertEqual(payload["proposals"], [])

    def test_un_scan_du_pending_reste_mesure(self):
        import tempfile
        from src.admin.sort_sql_view import sort_sql_payload

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "runs" / "scan9"
            d.mkdir(parents=True)
            (d / "offers.json").write_text(json.dumps({"offers": [
                {"offer_id": "1", "name": "Jeu", "url": "https://m.test/a-gift-card-20"}]}),
                encoding="utf-8")
            (d / "sort_plan.json").write_text(json.dumps({
                "by_list": {}, "unrouted": [], "source_list": 9,
                "coverage": {"truncated": False}}), encoding="utf-8")
            payload = sort_sql_payload(Path(tmp) / "runs", "scan9", repo_root=Path(tmp))
        self.assertTrue(payload["measured"])

    def test_le_scan_ecrit_la_liste_quil_a_lue(self):
        src = (ROOT / "scripts" / "08_sort_plan.py").read_text(encoding="utf-8")
        self.assertIn('plan["source_list"] = int(args.list_id)', src)


if __name__ == "__main__":
    unittest.main()


class TheListParameterOpensTheOtherAksLists(unittest.TestCase):
    """`src/extractor.py::feed_page_for_list` — Romain, 2026-09-21 : « ajoute un paramètre
    liste pour pouvoir travailler sur les autres listes sauf la liste 8 (blacklist) ».

    Déclencheur : le feed pending de Difmark est VIDE (0 ligne, vérifié le 21/09) alors que
    ses lignes existent toujours — elles ont été déplacées vers la liste *account* (30). Or
    l'extracteur ne savait lire QUE la liste 9 (`docs/AKS_LISTS.md`)."""

    def test_a_list_id_becomes_its_admin_page(self):
        from src.extractor import feed_page_for_list

        self.assertEqual(feed_page_for_list(9), "aks-merchant-feeds-9")
        self.assertEqual(feed_page_for_list("30"), "aks-merchant-feeds-30")
        self.assertEqual(feed_page_for_list(" 12 "), "aks-merchant-feeds-12")

    def test_the_blacklist_is_refused(self):
        from src.extractor import FEED_LIST_BLACKLIST, feed_page_for_list

        self.assertEqual(FEED_LIST_BLACKLIST, 8)
        for value in (8, "8", " 8 "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    feed_page_for_list(value)
                self.assertIn("Blacklist", str(ctx.exception))

    def test_a_malformed_id_never_builds_a_silent_query(self):
        from src.extractor import feed_page_for_list

        for value in (0, -1, "abc", 3.7, "", "9a", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    feed_page_for_list(value)

    def test_the_url_carries_the_chosen_list(self):
        from src.extractor import feed_page_for_list, feed_url

        url = feed_url("167", page=2, feed_page=feed_page_for_list(30), available="all")
        self.assertIn("page=aks-merchant-feeds-30", url)
        self.assertIn("&store=167", url)
        self.assertIn("&p=2", url)

    def test_moving_TO_the_blacklist_is_untouched(self):
        """Le tri route vers la 8 (391 lignes le 21/09) et le mover scanne la liste cible
        pour prouver le déplacement : ces chemins ne passent pas par le sélecteur."""

        from src.extractor import feed_url

        self.assertIn("page=aks-merchant-feeds-8",
                      feed_url(None, feed_page="aks-merchant-feeds-8"))

    def test_both_clis_declare_the_flag_and_refuse_the_blacklist(self):
        for name in ("02_extract_feed.py", "08_sort_plan.py"):
            with self.subTest(script=name):
                src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
                self.assertIn('"--list"', src)
                self.assertIn("feed_page_for_list", src)
                self.assertIn("feed_page=feed_page", src)


class TheCoverageIsJudgedOnWhatWasObserved(unittest.TestCase):
    """`src/extractor.py` + `scripts/08_sort_plan.py` — 2026-09-21.

    Le scan de tri du 21/09 a lu `nav_max=566` en page 1, puis la liste a rétréci sous lui
    pendant 1 h 38 : `nav_max=488` en page 489, qui est revenue VIDE (fin atteinte).
    `feed_last_page` étant un maximum courant, l'ancien test comparait 566 à 489 pages lues
    et déclarait la couverture tronquée — et la console taisait alors toute proposition de
    requête (`sort_sql_view` : `proposals = [] if coverage["truncated"]`). Romain : « le tri
    est fini mais je ne vois pas de proposition d'ajouts de requêtes »."""

    def _coverage(self, stats, *, page_range=None, first_page=1):
        """LE code de production, pas une copie : `08_sort_plan` appelle cette fonction."""
        from src.sort_plan import coverage_from_stats

        return coverage_from_stats(stats, first_page=first_page,
                                   sliced=bool(page_range))["truncated"]

    def test_the_shrinking_list_of_the_21_09_is_not_truncated(self):
        stats = {"pages_fetched": 489, "feed_last_page": 566,
                 "feed_last_page_final": 488, "ended_past_end": True}
        self.assertFalse(self._coverage(stats))

    def test_a_real_truncation_is_still_caught(self):
        """Marche arrêtée par le plafond : la liste annonçait encore des pages."""
        stats = {"pages_fetched": 40, "feed_last_page": 566,
                 "feed_last_page_final": 566, "ended_past_end": False}
        self.assertTrue(self._coverage(stats))

    def test_an_explicit_slice_stays_truncated(self):
        stats = {"pages_fetched": 3, "feed_last_page": 3, "feed_last_page_final": 3,
                 "ended_past_end": True}
        self.assertTrue(self._coverage(stats, page_range=(1, 3)))

    def test_legacy_stats_without_the_witnesses_stay_fail_closed(self):
        """Un vieux `last_stats` (sans les deux témoins) ne doit pas devenir complet par
        accident : on retombe sur le maximum, donc sur l'ancien verdict."""
        stats = {"pages_fetched": 489, "feed_last_page": 566}
        self.assertTrue(self._coverage(stats))

    def test_the_extractor_really_publishes_both_witnesses(self):
        """Marche réelle sur une session simulée : pages 1-2 pleines, page 3 au-delà de la
        fin (nav_max retombé à 2) — exactement la forme du scan du 21/09, en miniature."""

        from tests.test_extractor import FakeSession, _extractor, _offer, _state

        session = FakeSession({
            1: [_state([_offer(1)], nav_max=9)],      # la liste en annonce 9 au départ…
            2: [_state([_offer(2)], nav_max=2)],      # …puis elle a rétréci à 2
            3: [_state([], nav_max=2)],               # page d'après-la-fin
        })
        extractor = _extractor(session)
        extractor.extract_pages(run_id="r1", merchant="M", store_id=1,
                                first_page=1, last_page=9)
        stats = extractor.last_stats
        self.assertTrue(stats["ended_past_end"])
        self.assertEqual(stats["feed_last_page_final"], 2)
        self.assertEqual(stats["feed_last_page"], 9)          # le maximum, conservé tel quel
        self.assertFalse(self._coverage(stats))               # couverture COMPLÈTE

    def test_a_walk_stopped_by_the_cap_is_truncated_end_to_end(self):
        from tests.test_extractor import FakeSession, _extractor, _offer, _state

        session = FakeSession({
            1: [_state([_offer(1)], nav_max=9)],
            2: [_state([_offer(2)], nav_max=9)],
        })
        extractor = _extractor(session)
        extractor.extract_pages(run_id="r1", merchant="M", store_id=1,
                                first_page=1, last_page=2)
        stats = extractor.last_stats
        self.assertFalse(stats["ended_past_end"])
        self.assertEqual(stats["feed_last_page_final"], 9)
        self.assertTrue(self._coverage(stats))

    def test_the_sort_cli_uses_the_shared_rule(self):
        plan = (ROOT / "scripts" / "08_sort_plan.py").read_text(encoding="utf-8")
        self.assertIn("coverage_from_stats(", plan)


class TheSubmitCanWorkOnAnotherList(unittest.TestCase):
    """`scripts/05_submit.py --list` — 2026-09-21, Romain : « passe sur une page difmark et
    rentre les offres que t'y trouves ».

    Les lignes Difmark ne sont plus dans la file Pending (liste 9, vide) mais dans la liste
    *account* (30). Le submit localise la ligne et PROUVE sa disparition en scannant le feed :
    sans le drapeau il scannerait la 9 et refuserait « offer not in current feed ». Le
    plombage existait déjà côté `src/submitter.py` (`feed_page` traversait scan, index,
    recherche et preuve) — seul le CLI ne l'exposait pas."""

    def test_the_cli_declares_the_flag_and_threads_it(self):
        src = (ROOT / "scripts" / "05_submit.py").read_text(encoding="utf-8")
        self.assertIn('"--list"', src)
        self.assertIn("feed_page = feed_page_for_list(args.list_id)", src)
        # les QUATRE chemins qui lisent le feed doivent le recevoir : mode --catalog,
        # inspect, submit, et le catalogue rafraîchi quand le cache est absent ou périmé
        # (ce dernier manquait — revue de Romain du 2026-09-21).
        self.assertEqual(src.count("feed_page=feed_page"), 4,
                         "catalogue, inspect, submit, et le catalogue hors cache")

    def test_the_blacklist_is_refused_here_too(self):
        from src.extractor import feed_page_for_list

        with self.assertRaises(ValueError):
            feed_page_for_list(8)

    def test_the_submitter_scans_the_list_it_is_given(self):
        """Le paramètre n'est pas décoratif : c'est l'URL scannée qui change."""
        from src.extractor import feed_page_for_list, feed_url

        url = feed_url("167", page=3, feed_page=feed_page_for_list(30), available="all")
        self.assertIn("page=aks-merchant-feeds-30", url)
        self.assertNotIn("aks-merchant-feeds-9", url)


class AnAccountRowTakesTheAccountBranch(unittest.TestCase):
    """`MerchantConfig.account_row` + l'aiguillage de `match_offer` — Romain, 2026-09-21 :
    « elle ne doit pas continuer à passer par la branche console. Elle doit être routée vers
    une branche compte. Elle utilisera la branche jeu ou la branche console selon le type
    d'account. »

    Avant : 107 lignes de la page lue (PS5 61, Xbox Series 27, PS4 12, Xbox 7) étaient
    refusées « console: ACCOUNT — not a game (R45) » — le compte traité comme un marqueur
    non-jeu. La sécurité ne tient plus au refus mais à l'AIGUILLAGE : une ligne compte prend
    la branche compte, qui exige une page AKS « <plateforme> Account » ET un seau « Account »
    — jamais le chemin des clés console (l'incident du 12/09)."""

    PS5 = "https://difmark.com/en/buy-console-account-phantom-blade-zero-ps5-account-177232"
    STEAM = "https://difmark.com/en/buy-console-account-subnautica-2-steam-account-199942"
    CLE = "https://difmark.com/en/buy-console-account-some-game-xbox-series-12345"

    def test_difmark_declares_its_account_rows(self):
        from src.merchants.difmark import CONFIG, account_row

        self.assertIs(CONFIG.account_row, account_row)
        self.assertTrue(account_row("Phantom Blade Zero (Account) Standard Edition", self.PS5))
        self.assertTrue(account_row("Subnautica 2 Standard Edition", self.STEAM))
        self.assertFalse(account_row("X", "https://difmark.com/en/buy-x-cd-key-12"))
        self.assertFalse(account_row("", ""))

    def test_the_console_classifier_no_longer_claims_the_row(self):
        """L'ancien refus « ACCOUNT — not a game » ne doit plus être le verdict d'une ligne
        compte : elle descend jusqu'à la branche compte, qui refuse sur ce qui manque
        VRAIMENT (la page marchande n'est pas lisible ici, donc c'est ce refus-là qu'on voit)."""

        offer = NormalizedOffer(offer_id="1", name="Phantom Blade Zero (Account) Standard Edition",
                                url=self.PS5, merchant="Difmark")
        page = _page({"1": "Standard"}, aks_name="Phantom Blade Zero")
        res = match_offer(offer, resolver=lambda n, **k: page,
                          difmark_offer_resolver=lambda u: (_ for _ in ()).throw(
                              __import__("src.merchants.difmark", fromlist=["x"]).DifmarkPageUnreadable("hors ligne")),
                          consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertNotIn("not a game", res.reason)

    def test_a_pending_account_platform_is_named_in_the_refusal(self):
        """« compte EPIC — pas encore de page ni de seau » : le refus dit ce qui manque, pour
        qu'on sache quoi ajouter le jour où AKS publie la page."""

        from src.merchants.difmark import DIFMARK_ACCOUNT_PLATFORMS_PENDING, DifmarkOfferAttributes

        self.assertEqual(DIFMARK_ACCOUNT_PLATFORMS_PENDING.get("EPIC GAMES"), "EPIC")
        offer = NormalizedOffer(
            offer_id="1", name="Phantom Blade Zero Standard Edition",
            url="https://difmark.com/en/buy-console-account-phantom-blade-zero-epic-games-account-177234",
            merchant="Difmark")
        attrs = DifmarkOfferAttributes(raw_platform="EPIC GAMES", raw_region="GLOBAL",
                                       offer_name="Phantom Blade Zero (Epic Games Account)")
        res = match_offer(offer, resolver=lambda n, **k: _page({"1": "Standard"}, aks_name="Phantom Blade Zero"),
                          difmark_offer_resolver=lambda u: attrs, consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("compte EPIC", res.reason)
        self.assertIn("Steam seul", res.reason)

    def test_only_steam_is_wired_today(self):
        """Romain : « ajoute le Steam account ; quand tu trouveras du Epic account, tu
        ajouteras l'Epic account ». Une seule page-compte et un seul jeu de seaux."""

        from src.merchants.difmark import (DIFMARK_ACCOUNT_PAGE_KINDS,
                                           DIFMARK_STEAM_ACCOUNT_REGION_IDS)

        self.assertEqual(DIFMARK_ACCOUNT_PAGE_KINDS, {"STEAM": "steam-account"})
        self.assertEqual(DIFMARK_STEAM_ACCOUNT_REGION_IDS,
                         {"global": "412", "eu": "480", "us": "578"})

    def test_the_net_still_refuses_a_row_the_hook_would_miss(self):
        """Le filet du 14/09 reste : si la grammaire d'URL nous échappait, le classifieur
        console refuse encore — un compte n'entre JAMAIS comme clé console."""

        from src.merchants.difmark import console_url_families

        self.assertIn("not a game", console_url_families(self.PS5) or "")

    def test_a_non_game_account_row_is_still_refused(self):
        """L'aiguillage ne doit pas ouvrir une porte : une carte cadeau ou un Game Pass
        vendus « (Account) » restent des non-jeux, et une région interdite reste interdite.
        (Ma première version de l'aiguillage sautait TOUS les scans suivants.)"""

        from src.matcher import precheck_skip

        cas = [
            ("PSN Card 20 EUR (Account) Standard Edition",
             "https://difmark.com/en/buy-console-account-psn-card-20-eur-ps5-account-2",
             "PSN CARD"),
            ("Xbox Game Pass Ultimate 3 Months (Account) Standard Edition",
             "https://difmark.com/en/buy-console-account-xbox-game-pass-xbox-one-account-3",
             "GAME PASS"),
            ("Jeu (Account) Standard Edition Turkey",
             "https://difmark.com/en/buy-console-account-jeu-ps5-account-1",
             "forbidden region: TURKEY"),
        ]
        for name, url, attendu in cas:
            with self.subTest(name=name):
                offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant="Difmark")
                reason = precheck_skip(offer, consoles=True)
                self.assertIsNotNone(reason, "cette ligne doit rester refusée")
                self.assertIn(attendu, reason)

    def test_a_plain_account_game_row_passes_the_precheck(self):
        from src.matcher import precheck_skip

        for url in (self.PS5, self.STEAM):
            with self.subTest(url=url):
                offer = NormalizedOffer(offer_id="1", name="Phantom Blade Zero (Account) Standard Edition",
                                        url=url, merchant="Difmark")
                self.assertIsNone(precheck_skip(offer, consoles=True))

    def test_other_merchants_are_untouched(self):
        from src.merchants.registry import MERCHANT_CONFIGS

        sans = [c.name for c in MERCHANT_CONFIGS.values() if c.account_row is not None]
        self.assertEqual(sans, ["Difmark"])


class TheWrittenEditionMustBeSoldByThePage(unittest.TestCase):
    """[E06] — Romain, 2026-09-21, sur une écriture qu'il a repérée lui-même : « t'as rentré
    un DLC en standard ».

    « Diablo IV Lord of Hatred » est entrée Standard(1) sur une page qui vend
    {16: DLC, 7: Deluxe, 21: Ultimate} — un id que la page n'offre même pas. La page était
    pourtant LUE : c'est Standard qui était exempté du contrôle (la réconciliation P1-1 ne
    tourne que `if edition_id != "1"`). Mesure du jour : 5 des 10 offres Difmark créées (1 DLC
    + 4 accès anticipé), et 1 page sur 60 tirées au sort chez GameSeal."""

    def _match(self, title, editions, aks_name="Neon Beats"):
        offer = NormalizedOffer(offer_id="1", name=title,
                                url="https://gameseal.com/x-pc-steam-key-global", merchant="GameSeal")
        return match_offer(offer, resolver=lambda n, **k: _page(editions, aks_name=aks_name))

    def test_standard_is_not_written_on_a_page_that_does_not_sell_it(self):
        res = self._match("Neon Beats (PC) Steam Key - GLOBAL",
                          {"16": "DLC", "7": "Deluxe", "21": "Ultimate"})
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("not sold on the resolved AKS page", res.reason)
        self.assertIn("(E06)", res.reason)
        self.assertIn("Deluxe", res.reason)      # le refus DIT ce que la page vend

    def test_a_sole_early_access_bucket_is_adopted(self):
        res = self._match("Neon Beats (PC) Steam Key - GLOBAL", {"5": "Early Access"})
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("Early Access", "5"))

    def test_a_page_selling_standard_is_untouched(self):
        for editions in ({"1": "Standard"}, {"1": "Standard", "5": "Early Access"},
                         {"1": "Standard", "7": "Deluxe"}):
            with self.subTest(editions=editions):
                res = self._match("Neon Beats (PC) Steam Key - GLOBAL", editions)
                self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
                self.assertEqual(res.edition_id, "1")

    def test_R18_keeps_its_canonical_dlc_id(self):
        """[R18] reste le seul juge du seau DLC : il émet 16 même si la page range son DLC
        sous un autre id — E06 ne doit pas le contredire (AGENTS.md)."""

        res = self._match("Neon Beats (PC) Steam Key - GLOBAL", {"99": "dlc"})
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "16")

    def test_the_console_rule_and_the_pc_rule_now_say_the_same_thing(self):
        """La branche console appliquait déjà « l'édition doit être vendue par la page »
        depuis le 12/09 ; c'était la page PRIMAIRE qui y échappait."""

        src = (ROOT / "src" / "matcher.py").read_text(encoding="utf-8")
        self.assertIn("not sold on the {fam} page (R45)", src)
        self.assertIn("(E06)", src)
