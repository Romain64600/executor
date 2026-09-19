"""Audit complet du 2026-09-18 — les constats corrigés, verrouillés un par un.

Rapport : docs/AUDIT_2026-09-18_complet.md. Chaque classe porte l'emplacement du constat
et rouvre la porte exacte qui était ouverte : ces tests doivent passer au ROUGE si on
revient en arrière, pas seulement décrire le comportement souhaité.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts import NormalizedOffer
from src.matcher import (  # noqa: E402
    REGION_IDS, AksResolution, Candidate, SkippedOffer, match_offer,
)


def _page(editions, *, aks_name="DLC Quest", platforms=("Steam",), regions=None):
    return AksResolution(slug="s", url="https://aks/x", product_id="1", aks_name=aks_name,
                         editions=editions, regions=regions or {"2": "GLOBAL"},
                         official_platforms=platforms)


def _match(name, url, page, merchant="Gamivo"):
    offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant)
    return match_offer(offer, resolver=lambda n, **k: page)


class R18IsTheSoleAuthorityOnTheDlcBucket(unittest.TestCase):
    """`src/matcher.py:3169` et `:3217` — le durcissement du 17/09 ne fermait qu'une porte
    sur trois vers le seau DLC(16).

    « DLC Quest » est un VRAI JEU DE BASE — EXECUTOR_RULES §4.3 (f) le nomme explicitement.
    Son titre contient le mot DLC, donc `detect_edition` rend DLC(16) ; deux autres
    producteurs adoptaient ensuite le seau DLC de la page par simple égalité de libellé,
    sans exiger de marqueur et sans la condition « seul seau » de [R18]."""

    NAME = "DLC Quest - Steam Key GLOBAL"
    URL = "https://gamivo.com/product/dlc-quest"

    def test_a_base_game_is_NOT_dlc_when_the_page_also_offers_standard(self):
        # La porte E05/R23 : « DLC » est dans le nom AKS, la page vend le seau 16.
        res = _match(self.NAME, self.URL, _page({"1": "Standard", "16": "DLC"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual((res.edition_label, res.edition_id), ("Standard", "1"))

    def test_a_named_dlc_bucket_is_not_adopted_either(self):
        # Même porte, seau nommé « DLC Pack » sous un id quelconque : PACK est du bruit de
        # format, donc la clé de comparaison valait {DLC} et le seau était adopté.
        res = _match(self.NAME, self.URL, _page({"1": "Standard", "4711": "DLC Pack"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual((res.edition_label, res.edition_id), ("Standard", "1"))

    def test_R18_itself_is_untouched_on_a_single_bucket_page(self):
        # La décision de Romain du 17/09 : le seau DLC décide quand il est le SEUL.
        res = _match(self.NAME, self.URL, _page({"16": "DLC"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_the_refusal_names_R18_instead_of_lying_about_the_page(self):
        """La réconciliation P1-1 disait « not sold on the resolved AKS page » alors que la
        page VEND le seau — un motif faux, et qui alimente le routeur de tri des listes."""
        res = _match("Some Game DLC - Steam Key GLOBAL",
                     "https://gamivo.com/product/some-game-dlc",
                     _page({"1": "Standard", "7": "Deluxe", "16": "DLC"},
                           aks_name="Some Game"))
        if isinstance(res, SkippedOffer):
            self.assertNotIn("not sold on the resolved", res.reason)


class MicrosoftIsAStoreWordNotAProductWord(unittest.TestCase):
    """`src/matcher.py:579` — exactement l'histoire de ROCKSTAR du 2026-09-16, rejouée.

    Les seaux MICROSOFT sont mappés depuis [R50], donc la ligne passe la garde de région
    et vient mourir un cran plus loin sur « extra words: ['MICROSOFT'] »."""

    def test_a_microsoft_store_row_is_entered(self):
        res = _match("Test Game (Microsoft Store)",
                     "https://gamerall.com/pc/test-game-microsoft-store-europe",
                     _page({"1": "Standard"}, aks_name="Test Game",
                           platforms=("Microsoft Store",),
                           regions={"2": "GLOBAL", "244": "EU"}),
                     merchant="Gamerall")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.platform, "MICROSOFT")

    def test_the_bucket_mapping_alone_was_not_enough(self):
        """Les deux moitiés sont un seul correctif : sans le jeton de bruit, le mapping des
        seaux ne livre rien (c'est ce que dit déjà la note ROCKSTAR)."""
        self.assertIn("MICROSOFT", REGION_IDS)


class AMerchantFileNeverInventsAPlatformToken(unittest.TestCase):
    """`src/merchants/gamerall.py:60` — le fichier rendait « UPLAY », nom commercial absent
    de REGION_IDS. Le matcher lisait UBISOFT dans le titre et UPLAY dans l'URL : 100 % des
    lignes Ubisoft Connect étaient refusées sur un faux conflit interne au fichier."""

    def test_a_gamerall_ubisoft_row_is_no_longer_refused_on_an_internal_conflict(self):
        res = _match("Anno 1800 (Ubisoft Connect)",
                     "https://gamerall.com/pc/anno-1800-ubisoft-connect-europe",
                     _page({"1": "Standard"}, aks_name="Anno 1800",
                           platforms=("Ubisoft Connect",),
                           regions={"2": "GLOBAL", "244": "EU"}),
                     merchant="Gamerall")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.platform, "UBISOFT")


if __name__ == "__main__":
    unittest.main()


class ACountryNameInTheGameTitleIsNotARegionLock(unittest.TestCase):
    """`src/matcher.py:930` — le balayage s'appliquait au titre ENTIER : tout jeu dont le NOM
    contient China / India / Japan / Ukraine / Poland était refusé « forbidden region » puis
    routé vers la Blacklist(8), alors qu'il déclare GLOBAL dans son titre ET dans son URL.

    Règle retenue : la région est la DERNIÈRE chose déclarée. Un nom de pays suivi d'un
    marqueur vendable appartient au nom du produit."""

    ENTRENT = [
        ("Assassin's Creed Chronicles: China (PC) - Steam Key - GLOBAL",
         "https://www.g2a.com/assassins-creed-chronicles-china-steam-key-global-i1"),
        ("Crusader Kings II: Rajas of India - Steam Key - GLOBAL",
         "https://www.g2a.com/crusader-kings-ii-rajas-of-india-steam-key-global-i2"),
        ("Cities: Skylines - Content Creator Pack: Modern Japan Steam Key GLOBAL",
         "https://www.g2a.com/cities-skylines-modern-japan-steam-key-global-i3"),
        ("Ukraine War Stories - Steam Key - GLOBAL",
         "https://www.g2a.com/ukraine-war-stories-steam-key-global-i4"),
        ("Civilization VI - Poland Civilization and Scenario Pack Steam Key GLOBAL",
         "https://www.g2a.com/civ-vi-poland-steam-key-global-i5"),
    ]
    VERROUS = [
        ("Cyberpunk 2077 Steam Key BRAZIL", "https://www.g2a.com/cyberpunk-2077-steam-key-brazil-i6"),
        # Le cas qui protège le P1 du 2026-09-06 : le verrou vient APRÈS le mot vendable.
        ("Cyberpunk 2077 Global Steam Key BRAZIL",
         "https://www.g2a.com/cyberpunk-2077-global-steam-key-brazil-i7"),
        ("Hades RUSSIA PC Steam CD Key", "https://www.kinguin.net/x/hades-pc-steam-cd-key-russia"),
        ("Hades Steam Key RUSSIA", "https://www.eneba.com/steam-hades-steam-key-russia"),
    ]

    def test_a_country_in_the_product_name_does_not_blacklist_a_global_key(self):
        from src.matcher import precheck_skip
        for name, url in self.ENTRENT:
            with self.subTest(name=name[:40]):
                offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant="G2A")
                self.assertIsNone(precheck_skip(offer))

    def test_a_real_region_lock_is_still_refused(self):
        from src.matcher import precheck_skip
        for name, url in self.VERROUS:
            with self.subTest(name=name[:40]):
                offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant="G2A")
                reason = precheck_skip(offer)
                self.assertIsNotNone(reason, "un verrou réel doit rester refusé")
                self.assertIn("forbidden region", reason)

    def test_the_slug_keeps_the_country_when_it_is_part_of_the_name(self):
        """Troisième site du même défaut : le strip itératif amputait « Rajas of India » en
        « Rajas of » une fois GLOBAL / KEY / STEAM retirés — mauvaise page sondée."""
        from src.matcher import cleaned_title
        self.assertEqual(cleaned_title("Crusader Kings II: Rajas of India - Steam Key - GLOBAL"),
                         "Crusader Kings II: Rajas of India")
        self.assertEqual(cleaned_title("Cities: Skylines - Content Creator Pack: Modern Japan "
                                       "Steam Key GLOBAL"),
                         "Cities: Skylines - Content Creator Pack: Modern Japan")
        # Mais un vrai verrou est toujours retiré du slug.
        self.assertEqual(cleaned_title("Hades Steam Key RUSSIA"), "Hades")


class ApproveMustBeAJsonBoolean(unittest.TestCase):
    """`src/validation.py:146` — « if not entry.get("approve") » lisait la VÉRITÉ PYTHON :
    la chaîne "false" approuve. Et `verify_approved_against_source` re-dérivant avec le même
    prédicat, la re-vérification au submit CONFIRMAIT l'approbation au lieu de la refuser."""

    def _files(self, approve):
        from src.validation import candidate_fingerprint
        cand = {"offer": {"offer_id": "1", "name": "Hades", "url": "https://m/x",
                          "merchant": "Kinguin"},
                "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": "Hades",
                "platform": "STEAM", "region": {"label": "GLOBAL", "id": "2", "implicit": False},
                "edition": {"label": "Standard", "id": "1"}}
        fp = candidate_fingerprint(cand)
        validation = {"run_id": "r1", "validated_by": "romain", "validated_at": "2026-09-18",
                      "candidates": [{"fingerprint": fp, "approve": approve}]}
        return [cand], validation

    def test_the_string_false_no_longer_approves(self):
        from src.validation import ValidationError, load_validation
        cands, validation = self._files("false")
        with self.assertRaises(ValidationError) as ctx:
            load_validation(validation, cands, expected_run_id="r1")
        self.assertIn("booléen", str(ctx.exception))

    def test_a_real_boolean_still_works_in_both_directions(self):
        from src.validation import load_validation
        cands, validation = self._files(True)
        self.assertEqual(len(load_validation(validation, cands, expected_run_id="r1")), 1)
        cands, validation = self._files(False)
        self.assertEqual(load_validation(validation, cands, expected_run_id="r1"), [])


class RegionBucketsArePerPlatformInBothDirections(unittest.TestCase):
    """`src/admin/validation_io.py:177` — la garde « les seaux de région sont PAR PLATEFORME »
    n'existait que dans le sens « je change la plateforme ». Changer la SEULE région acceptait
    un seau d'une autre famille, et le `<select>` de la console présente toutes les options de
    toutes les plateformes sans filtrage."""

    CATALOG = {"regions": [{"key": "2", "text": "Steam (2)"},
                           {"key": "9", "text": "Steam EU (9)"},
                           {"key": "88ps5h", "text": "PS5 (88ps5h)"}],
               "editions": [{"key": "1", "text": "Standard"}]}

    def _candidate(self):
        return {"offer": {"offer_id": "1", "name": "Hades", "url": "https://m/x",
                          "merchant": "Kinguin"},
                "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": "Hades",
                "platform": "STEAM", "region": {"label": "GLOBAL", "id": "2", "implicit": False},
                "edition": {"label": "Standard", "id": "1"}}

    def test_a_foreign_bucket_is_refused_when_only_the_region_changes(self):
        from src.admin.validation_io import ValidationIOError, _apply_override
        cand = self._candidate()
        with self.assertRaises(ValidationIOError) as ctx:
            _apply_override(cand, {"region_id": "88ps5h"}, self.CATALOG,
                            by="romain", now="2026-09-18T00:00:00Z")
        self.assertEqual(ctx.exception.code, "platform_region_mismatch")

    def test_a_bucket_of_the_right_platform_still_passes(self):
        from src.admin.validation_io import _apply_override
        cand = self._candidate()
        _apply_override(cand, {"region_id": "9"}, self.CATALOG,
                        by="romain", now="2026-09-18T00:00:00Z")
        self.assertEqual(cand["region"]["id"], "9")


class TheLanguageRegionMirrorCannotDrift(unittest.TestCase):
    """`src/matcher.py:617` — le commentaire revendique de MIROITER la décision P2-6b (« the
    SAME trailing code a forbidden region »), mais TH était verrou dans l'URL et langue dans
    le titre. Verrouillé ici pour que le miroir ne puisse plus diverger."""

    def test_every_url_lock_code_that_is_also_a_language_is_protected(self):
        import src.matcher as M
        codes = {c.upper() for c, _ in M._URL_FORBIDDEN_CODES}
        drift = (M.LANGUAGE_TOKENS & codes) - M._REGION_LOCK_LANG_CODES
        self.assertEqual(drift, set(),
                         f"codes verrous dans l'URL mais avalés comme langue dans le titre : {drift}")


class NoBundleEverIsActuallyLocked(unittest.TestCase):
    """`src/matcher.py:3352` — la règle dure de Romain (2026-07-07) « on n'entre JAMAIS de
    bundle » avait son garde-fou (`edition_id == "8"` → skip) exécuté par AUCUN des 2 245
    tests : le supprimer laissait la suite verte ET faisait entrer un bundle.

    On assert le MOTIF EXACT, pas seulement le type : la réconciliation P1-1 deux lignes plus
    bas émet elle aussi un skip, et un `assertIsInstance` lâche resterait vert après la
    régression."""

    RAISON = "bundle edition resolved — no bundles ever"

    def _run(self, title, editions):
        return _match(title, "https://gamivo.com/product/neon-beats",
                      _page(editions, aks_name="Neon Beats", platforms=("Steam",)))

    def test_a_bundle_tier_on_the_page_is_still_refused(self):
        res = self._run("Neon Beats Pack (PC) - Steam Key - GLOBAL",
                        {"1": "Standard", "444": "Bundle Edition"})
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, self.RAISON)

    def test_the_defence_in_depth_in_front_of_it(self):
        """Les deux autres orthographes n'ATTEIGNENT pas ce garde-fou — elles sont arrêtées
        plus tôt, et c'est très bien : « Bundle » par la catégorie du precheck, « Trilogy »
        par la garde de mots supplémentaires. C'est « Pack » qui traverse tout (le mot est
        du bruit de format, donc jamais un extra) et qui fait du garde-fou final le SEUL
        filet — d'où le test ci-dessus."""

        res = self._run("Neon Beats Bundle Steam Key GLOBAL", {"1": "Standard"})
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("BUNDLE", res.reason)
        res = self._run("Neon Beats Trilogy Steam Key GLOBAL", {"1": "Standard", "8": "Bundle"})
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("TRILOGY", res.reason)


class ARetiredRuleCannotComeBack(unittest.TestCase):
    """`tests/test_sort_sql_console.py:399` — `%valid-until%` a été RETIRÉ le matin même parce
    qu'il contredit une décision de `AGENTS.md` (« Kinguin valid until juin 2027 on rentre »),
    mais rien n'empêchait de le re-promouvoir depuis la console, vers cette liste ou une
    autre. Le retrait porte sur le MOTIF, pas sur le couple (motif, liste)."""

    def test_promoting_a_retired_pattern_is_refused_towards_any_list(self):
        import tempfile
        from src.sort_sql_promoted import promote
        from src.sort_sql_rules import RETIRED
        pattern = next(iter(RETIRED))
        for target in ("8", "21", "41"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError) as ctx:
                    promote(Path(tempfile.mkdtemp()), pattern=pattern, target=target, by="test")
                self.assertIn("RETIR", str(ctx.exception).upper())


class ALiveRunsMarkerIsNeverStolen(unittest.TestCase):
    """`scripts/10_data_entry_auto.py:506` — `write_marker` écrasait inconditionnellement.
    Un simple `--dry-run` volait le marqueur d'un sweep de 30 h : le sweep devenait INVISIBLE
    dans les consoles et `_ensure_free` rouvrait le lancement. Un pid mort reste écrasé."""

    def test_another_live_run_is_refused_but_the_same_run_id_is_not(self):
        import tempfile
        from src import run_marker
        root = Path(tempfile.mkdtemp())
        run_marker.write_marker(root, run_id="sweep-1", kind="data_entry_auto", source="cli")
        with self.assertRaises(run_marker.ActiveRunExists):
            run_marker.write_marker(root, run_id="dry-run-2", kind="sort_dry_run", source="cli")
        # Le MÊME run_id reste écrasable (relance explicite avec --run-id).
        again = run_marker.write_marker(root, run_id="sweep-1", kind="data_entry_auto")
        self.assertEqual(again["run_id"], "sweep-1")

    def test_a_dead_pid_is_still_overwritten(self):
        import json
        import tempfile
        from src import run_marker
        root = Path(tempfile.mkdtemp())
        (root / "state").mkdir(parents=True)
        (root / "state" / run_marker.MARKER_NAME).write_text(json.dumps(
            {"run_id": "mort", "kind": "x", "pid": 2 ** 22, "started_at": "2026-09-18T00:00:00Z"}),
            encoding="utf-8")
        self.assertEqual(
            run_marker.write_marker(root, run_id="neuf", kind="y")["run_id"], "neuf")


class AnOperatorStopDoesNotAmnestyFailClosedHalts(unittest.TestCase):
    """`scripts/10_data_entry_auto.py:567` — `recap["halted"] = "operator_stop"` ÉCRASAIT les
    haltes fail-closed accumulées par `--continue-on-halt`, et comme le code de sortie rend 0
    sur « operator_stop », un run qui avait échoué sur plusieurs marchands sortait VERT."""

    def test_the_source_concatenates_instead_of_overwriting(self):
        source = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")
        self.assertNotIn('recap["halted"] = "operator_stop"', source,
                         "le stop opérateur ne doit plus écraser les haltes déjà enregistrées")
        self.assertEqual(source.count('[*(recap.get("halted_merchants") or []), "operator_stop"]'), 2,
                         "les deux points de stop doivent concaténer")


class TwoEntriesForTheSameFingerprintAreRefused(unittest.TestCase):
    """`src/validation.py:153` — deux entrées portant la même empreinte passaient, et le lot
    se terminait après le PREMIER ajout : une édition manuelle malformée produisait un lot
    silencieusement tronqué. §5 ne connaît pas l'approbation partielle."""

    def _files(self, entries):
        from src.validation import candidate_fingerprint
        cand = {"offer": {"offer_id": "1", "name": "Hades", "url": "https://m/x",
                          "merchant": "Kinguin"},
                "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": "Hades",
                "platform": "STEAM", "region": {"label": "GLOBAL", "id": "2", "implicit": False},
                "edition": {"label": "Standard", "id": "1"}}
        fp = candidate_fingerprint(cand)
        return [cand], {"run_id": "r1", "validated_by": "r", "validated_at": "2026-09-18",
                        "candidates": [{"fingerprint": fp, **e} for e in entries]}

    def test_a_duplicate_fingerprint_rejects_the_whole_file(self):
        from src.validation import ValidationError, load_validation
        for entries in ([{"approve": True}, {"approve": True}],
                        [{"approve": True}, {"approve": False}]):
            with self.subTest(entries=entries):
                cands, validation = self._files(entries)
                with self.assertRaises(ValidationError) as ctx:
                    load_validation(validation, cands, expected_run_id="r1")
                self.assertIn("deux fois", str(ctx.exception))


class AnOperatorStopIsNotAStageFailure(unittest.TestCase):
    """2026-09-19, vécu en direct — Romain clique « Arrêter » pour réordonner ses marchands.
    Le stop SIGTERM l'enfant du stage en vol, celui-ci rend `exit -15`, et le sweep l'étiquette
    `GameSeal: match_failed_p103` : un arrêt DÉLIBÉRÉ présenté comme une panne fail-closed,
    avec un code de sortie 2. Les trois étages testaient `should_stop()` AVANT de se lancer,
    aucun ne le re-testait APRÈS un échec — or le signal arrive justement pendant l'attente."""

    def test_a_stage_failure_under_a_requested_stop_reads_as_operator_stop(self):
        from src.data_entry_auto import _halt_label
        self.assertEqual(_halt_label("match_failed_p103", lambda: True), "operator_stop")
        self.assertEqual(_halt_label("extract_failed_p1", lambda: True), "operator_stop")

    def test_a_real_failure_keeps_its_own_label(self):
        from src.data_entry_auto import _halt_label
        self.assertEqual(_halt_label("match_failed_p103", lambda: False), "match_failed_p103")

    def test_every_stage_failure_goes_through_the_helper(self):
        source = (ROOT / "src" / "data_entry_auto.py").read_text(encoding="utf-8")
        for label in ("extract_failed_p", "match_failed_p", "approve_failed_p"):
            for line in source.splitlines():
                if f'"{label}' in line and 'recap["halted"]' in line:
                    self.assertIn("_halt_label", line,
                                  f"{label} doit passer par _halt_label")


class TheREGIONIsTheLastOneDeclared(unittest.TestCase):
    """`src/matcher.py:956` — Romain, 2026-09-19. Le départage « la région est la DERNIÈRE
    chose déclarée » partait de la PREMIÈRE occurrence du pays. Un verrou RÉPÉTÉ disparaissait
    donc : « Assassin's Creed Chronicles China Global Steam Key CHINA » s'arrêtait au CHINA du
    NOM DU JEU, voyait GLOBAL après lui, concluait « nom de produit » — et la clé verrouillée
    Chine entrait en GLOBAL(2)."""

    NAME = "Assassin's Creed Chronicles China Global Steam Key CHINA"

    def test_a_repeated_lock_is_caught(self):
        from src.matcher import precheck_skip
        for merchant, url in (("Kinguin", "https://www.kinguin.net/category/1/ac-pc-steam-cd-key"),
                              ("Gamivo", "https://www.gamivo.com/product/ac-pc-steam")):
            with self.subTest(merchant=merchant):
                offer = NormalizedOffer(offer_id="1", name=self.NAME, url=url, merchant=merchant)
                reason = precheck_skip(offer)
                self.assertIsNotNone(reason, "le second CHINA est le créneau de région")
                self.assertIn("CHINA", reason)

    def test_the_country_in_the_product_name_alone_still_enters(self):
        from src.matcher import precheck_skip
        offer = NormalizedOffer(
            offer_id="1", name="Assassin's Creed Chronicles: China (PC) - Steam Key - GLOBAL",
            url="https://www.g2a.com/ac-chronicles-china-steam-key-global-i1", merchant="G2A")
        self.assertIsNone(precheck_skip(offer))


class AMerchantPageRegionIsReadBeforeTheGenericScan(unittest.TestCase):
    """`src/matcher.py:3547` — Romain, 2026-09-19. La garde posée la veille vivait dans le
    dernier `else` de la branche console : le balayage GÉNÉRIQUE la précédait, et ce balayage
    lit les mots du NOM DU JEU. « 51 Worldwide Games (Nintendo Switch) », sans région dans
    l'URL, donnait un GLOBAL *explicite* sur le seul mot « Worldwide » du titre — la page
    marchande n'était jamais ouverte, même simulée indisponible."""

    URL = "https://gamerall.com/nintendo/51-worldwide-games-nintendo-switch"
    TITLE = "51 Worldwide Games (Nintendo Switch)"

    def _match_with(self, resolver):
        import dataclasses
        from src.merchants.registry import MERCHANT_CONFIGS
        page = AksResolution(slug="s", url="https://aks/sw", product_id="1",
                             aks_name="51 Worldwide Games", editions={"1": "Standard"},
                             regions={"99": "GLOBAL"}, official_platforms=("Nintendo",),
                             console_pages={"nintendo-switch": "https://aks/sw"})
        # On restaure l'OBJET d'origine, pas le champ : `dataclasses.replace` fabrique une
        # NOUVELLE config, et `test_registered_config_is_the_module_config` vérifie que le
        # registre porte bien l'objet du module — restaurer par un second `replace` laissait
        # un sosie derrière soi et faisait rougir deux tests… mais seulement dans la suite
        # complète, jamais en ciblé. C'est exactement la pollution de test qu'ils surveillent.
        original = MERCHANT_CONFIGS["GAMERALL"]
        MERCHANT_CONFIGS["GAMERALL"] = dataclasses.replace(
            original, offer_page_resolver=resolver)
        try:
            offer = NormalizedOffer(offer_id="1", name=self.TITLE, url=self.URL,
                                    merchant="Gamerall")
            return match_offer(offer, resolver=lambda n, **k: page,
                               page_resolver=lambda u: page, consoles=True)
        finally:
            MERCHANT_CONFIGS["GAMERALL"] = original

    def test_an_unreachable_page_fails_closed_instead_of_reading_the_game_name(self):
        from src.merchants.gamerall import GamerallPageUnreadable
        calls = []

        def boom(url, name=""):
            calls.append(url)
            raise GamerallPageUnreadable("page simulée indisponible")

        res = self._match_with(boom)
        self.assertTrue(calls, "le résolveur marchand DOIT être appelé")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("unreadable", res.reason)

    def test_the_page_region_wins_over_the_word_in_the_title(self):
        from src.merchant_config import MerchantOfferSignals

        def eu(url, name=""):
            return MerchantOfferSignals(platform="NINTENDO", region_resolved=True,
                                        region_base="eu", region_label="Europe")

        res = self._match_with(eu)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertIn("EU", res.region_label.upper())


class GamerallReadsOneParenthesisEverywhere(unittest.TestCase):
    """`src/merchants/gamerall.py:232` — Romain, 2026-09-19. `title_region` lisait la DERNIÈRE
    parenthèse depuis le 18/09, mais `title_platform`, `resolve_name` et `precheck` exigeaient
    encore qu'elle TERMINE le titre. « Hades (Steam) EUROPE » était donc refusé au précontrôle,
    et la lecture de région du titre — que `[R54]` place en PREMIER — devenait inaccessible."""

    def test_a_region_tail_no_longer_blocks_the_precheck(self):
        import src.merchants.gamerall as g
        self.assertIsNone(g.precheck("Hades (Steam) EUROPE", "https://gamerall.com/pc/hades-steam"))
        self.assertEqual(g.title_platform("Hades (Steam) EUROPE"), "STEAM")
        self.assertEqual(g.title_region("Hades (Steam) EUROPE"), "eu")

    def test_the_slug_name_drops_the_region_tail_too(self):
        """Sinon le slug sondé serait « hades-europe »."""
        import src.merchants.gamerall as g
        self.assertEqual(g.resolve_name("Hades (Steam) EUROPE"), "Hades")
        self.assertEqual(g.resolve_name("Anno 1800 (Ubisoft Connect) GLOBAL"), "Anno 1800")

    def test_an_unknown_parenthesis_is_still_refused_by_name(self):
        import src.merchants.gamerall as g
        reason = g.precheck("Some Game (Amiga)", "https://gamerall.com/a/some-game-amiga")
        self.assertIsNotNone(reason)
        self.assertIn("Amiga", reason)


class GamerallRefusesTwoContradictoryRegionsInOneTitle(unittest.TestCase):
    """`src/merchants/gamerall.py:title_region` — Romain, 2026-09-19 : « Gamerall accepte des
    régions contradictoires. Avec "Hades (Nintendo Switch) GLOBAL US", le classifieur détecte
    deux régions incompatibles. Le résolveur marchand prend ensuite la première et produit un
    candidat GLOBAL (99). "EUROPE USA" produit pareillement EU (99eu). »

    La queue du titre était lue au `search` — la PREMIÈRE région gagnait et la seconde
    disparaissait en silence. Mesuré avant le correctif, sur `match_offer` : « GLOBAL US » →
    CANDIDAT 99, « EUROPE USA » → CANDIDAT 99eu en console ; et 2 (GLOBAL) / 9 (EU) sur la
    branche PC, `title_region` étant partagé. Deux régions incompatibles = un titre ILLISIBLE,
    et `[R54]` dit qu'un signal illisible est un REFUS, jamais une supposition."""

    URL_SWITCH = "https://gamerall.com/nintendo/hades-nintendo-switch"
    URL_PC = "https://gamerall.com/pc/hades-steam"

    def _switch_page(self):
        return AksResolution(slug="s", url="https://aks/sw", product_id="1",
                             aks_name="Hades", editions={"1": "Standard"},
                             regions={"99": "GLOBAL"}, official_platforms=("Nintendo",),
                             console_pages={"nintendo-switch": "https://aks/sw"})

    def test_the_title_reader_reports_BOTH_regions(self):
        import src.merchants.gamerall as g
        self.assertEqual(g.title_regions("Hades (Nintendo Switch) GLOBAL US"), ("global", "us"))
        self.assertEqual(g.title_regions("Hades (Nintendo Switch) EUROPE USA"), ("eu", "us"))
        # deux MOTS pour la même base ne se contredisent pas
        self.assertEqual(g.title_regions("Hades (Steam) WORLDWIDE GLOBAL"), ("global",))
        # une seule région, et aucune : inchangé
        self.assertEqual(g.title_regions("Hades (Steam) EUROPE"), ("eu",))
        self.assertEqual(g.title_regions("Hades (Steam)"), ())

    def test_the_precheck_refuses_and_NAMES_the_two_regions(self):
        import src.merchants.gamerall as g
        # le MOTIF exact, sur le cas canonique de Romain — pas seulement le type du refus
        self.assertEqual(
            g.precheck("Hades (Nintendo Switch) GLOBAL US", self.URL_SWITCH),
            "Gamerall: deux régions contradictoires dans le titre (GLOBAL, US) — "
            "refus plutôt que supposition (R54)")
        for title, expected in (("Hades (Nintendo Switch) GLOBAL US", ("GLOBAL", "US")),
                                ("Hades (Nintendo Switch) EUROPE USA", ("EU", "US"))):
            with self.subTest(title=title):
                reason = g.precheck(title, self.URL_SWITCH)
                self.assertIsNotNone(reason, "un titre contradictoire ne s'entre pas")
                self.assertIn("deux régions contradictoires", reason)
                self.assertIn("R54", reason)
                for word in expected:
                    self.assertIn(word, reason)

    def test_the_hook_called_alone_raises_instead_of_guessing(self):
        """Rendre None laisserait `offer_signals` descendre sur l'URL puis la page et entrer
        la clé sur une région que le titre CONTREDIT — un repli déguisé."""
        import src.merchants.gamerall as g
        with self.assertRaises(g.GamerallTitleAmbiguous):
            g.title_region("Hades (Nintendo Switch) GLOBAL US")
        calls = []

        def never(url, **kw):
            calls.append(url)
            raise AssertionError("aucune requête ne doit partir sur un titre illisible")

        with self.assertRaises(g.GamerallTitleAmbiguous):
            g.offer_signals(self.URL_SWITCH, "Hades (Nintendo Switch) GLOBAL US", never)
        self.assertEqual(calls, [])
        # une seule région : le hook répond toujours, sans réseau (le titre suffit)
        self.assertEqual(g.title_region("Hades (Steam) EUROPE"), "eu")
        self.assertEqual(g.offer_signals(self.URL_PC, "Hades (Steam) EUROPE", never).region_base,
                         "eu")

    def test_end_to_end_neither_branch_enters_the_contradiction(self):
        page = self._switch_page()
        pc = AksResolution(slug="s", url="https://aks/pc", product_id="1", aks_name="Hades",
                           editions={"1": "Standard"}, regions={"2": "GLOBAL", "9": "EU"},
                           official_platforms=("Steam",))
        cases = ((self.URL_SWITCH, "Hades (Nintendo Switch) GLOBAL US", page, True),
                 (self.URL_SWITCH, "Hades (Nintendo Switch) EUROPE USA", page, True),
                 (self.URL_PC, "Hades (Steam) GLOBAL US", pc, False),
                 (self.URL_PC, "Hades (Steam) EUROPE USA", pc, False))
        for url, title, target, consoles in cases:
            with self.subTest(title=title, consoles=consoles):
                offer = NormalizedOffer(offer_id="1", name=title, url=url, merchant="Gamerall")
                res = match_offer(offer, resolver=lambda n, **k: target,
                                  page_resolver=lambda u: target, consoles=consoles)
                self.assertIsInstance(res, SkippedOffer)
                self.assertIn("deux régions contradictoires", res.reason)

    def test_a_single_region_title_still_enters_on_both_branches(self):
        """Le correctif REFUSE la contradiction, il ne ferme pas la lecture du titre."""
        page = self._switch_page()
        offer = NormalizedOffer(offer_id="1", name="Hades (Nintendo Switch) GLOBAL",
                                url=self.URL_SWITCH, merchant="Gamerall")
        res = match_offer(offer, resolver=lambda n, **k: page, page_resolver=lambda u: page,
                          consoles=True)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.region_id, "99")
        pc = AksResolution(slug="s", url="https://aks/pc", product_id="1", aks_name="Hades",
                           editions={"1": "Standard"}, regions={"2": "GLOBAL", "9": "EU"},
                           official_platforms=("Steam",))
        offer = NormalizedOffer(offer_id="1", name="Hades (Steam) EUROPE", url=self.URL_PC,
                                merchant="Gamerall")
        res = match_offer(offer, resolver=lambda n, **k: pc, page_resolver=lambda u: pc)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.region_id, "9")


class TheConsoleRegionSlotRefusesTwoSellableBasesBeforeOpeningThePage(unittest.TestCase):
    """`src/matcher.py:_console_plan` — second étage du même défaut du 2026-09-19.

    Le contrat de `ConsoleSignal` dit depuis le 14/09 : des mots de région qui ne désignent
    pas UNE base vendable unique sont un refus. Le déplacement du résolveur marchand au-dessus
    de cette garde (même jour, correctif « 51 Worldwide Games ») l'a court-circuitée : la
    branche `elif _page_resolver is not None:` ne contrôlait RIEN et « Hades (Nintendo Switch)
    GLOBAL US » descendait jusqu'à elle.

    `precheck` est neutralisé ici EXPRÈS : sans cela le fichier marchand refuserait la ligne
    en premier et ce test resterait vert même sans la garde — il ne prouverait rien.

    Le prédicat retenu est `sig.region_words`, PAS un désaccord avec le balayage générique :
    celui-ci lit les mots du NOM DU JEU et se tromperait sur « 51 Worldwide Games » (la classe
    voisine `AMerchantPageRegionIsReadBeforeTheGenericScan` verrouille ce cas — `region_words`
    y vaut `()`, mesuré)."""

    URL = "https://gamerall.com/nintendo/hades-nintendo-switch"

    def _match(self, title):
        import dataclasses
        from src.merchant_config import MerchantOfferSignals
        from src.merchants.registry import MERCHANT_CONFIGS
        page = AksResolution(slug="s", url="https://aks/sw", product_id="1",
                             aks_name="Hades", editions={"1": "Standard"},
                             regions={"99": "GLOBAL"}, official_platforms=("Nintendo",),
                             console_pages={"nintendo-switch": "https://aks/sw"})
        calls = []

        def stub(url, name=""):
            calls.append(url)
            return MerchantOfferSignals(platform="NINTENDO", region_resolved=True,
                                        region_base="global", region_label="Global")

        # On restaure l'OBJET d'origine, pas le champ — `dataclasses.replace` fabrique une
        # NOUVELLE config et `test_registered_config_is_the_module_config` vérifie que le
        # registre porte bien celle du module (pollution visible en suite complète seulement).
        original = MERCHANT_CONFIGS["GAMERALL"]
        MERCHANT_CONFIGS["GAMERALL"] = dataclasses.replace(
            original, precheck=None, offer_page_resolver=stub)
        try:
            offer = NormalizedOffer(offer_id="1", name=title, url=self.URL, merchant="Gamerall")
            return match_offer(offer, resolver=lambda n, **k: page,
                               page_resolver=lambda u: page, consoles=True), calls
        finally:
            MERCHANT_CONFIGS["GAMERALL"] = original

    def test_two_sellable_bases_are_refused_without_costing_a_page(self):
        # le MOTIF exact, sur le cas canonique de Romain — pas seulement le type du refus
        res, calls = self._match("Hades (Nintendo Switch) GLOBAL US")
        self.assertEqual(
            getattr(res, "reason", None),
            "console: merchant region contradiction GLOBAL / US — "
            "no single sellable base, not entered (R45)")
        for title, words in (("Hades (Nintendo Switch) GLOBAL US", ("GLOBAL", "US")),
                             ("Hades (Nintendo Switch) EUROPE USA", ("EUROPE", "USA"))):
            with self.subTest(title=title):
                res, calls = self._match(title)
                self.assertIsInstance(res, SkippedOffer)
                self.assertIn("merchant region contradiction", res.reason)
                self.assertIn("no single sellable base", res.reason)
                for word in words:
                    self.assertIn(word, res.reason)
                # la garde est AU-DESSUS du résolveur : un titre illisible ne tire pas 550 ko
                self.assertEqual(calls, [])

    def test_the_resolver_is_still_consulted_when_the_title_says_nothing(self):
        """La garde ne doit pas voler la parole au résolveur — le correctif du 19/09 matin."""
        res, calls = self._match("Hades (Nintendo Switch)")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.region_id, calls), ("99", [self.URL]))

    def test_the_shared_helper_ignores_a_forbidden_word(self):
        """« GLOBAL CANADA » n'est pas une contradiction entre deux zones VENDABLES : c'est un
        verrou interdit, et il garde son aiguillage propre (`forbidden region:`)."""
        from src.console_keys import distinct_region_bases
        self.assertEqual(distinct_region_bases(("GLOBAL", "US")), ("global", "us"))
        self.assertEqual(distinct_region_bases(("EUROPE", "USA")), ("eu", "us"))
        self.assertEqual(distinct_region_bases(("GLOBAL", "CANADA")), ("global",))
        self.assertEqual(distinct_region_bases(("EU", "European Union")), ("eu",))
        self.assertEqual(distinct_region_bases(("CA",)), ())
        self.assertEqual(distinct_region_bases(()), ())
