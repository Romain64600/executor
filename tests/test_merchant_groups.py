"""Les groupes de marchands — un par VPS (Romain, 2026-09-21 : « je voudrais qu'on puisse
lancer des marchands aussi par groupe… je compte prendre un troisième et quatrième VPS »)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.admin.auto_merchants import AUTO_MERCHANTS  # noqa: E402
from src.merchant_groups import (  # noqa: E402
    EXCLUDED,
    GROUPS,
    PENDING_2026_09_21,
    coverage,
    group_targets,
    split,
    targets_for,
)


class LesGroupesFigesCouvrentLaListeBlanche(unittest.TestCase):
    def test_aucun_doublon_aucun_inconnu(self):
        c = coverage()
        self.assertEqual(c["doublons"], [], "un marchand ne peut pas être dans deux groupes")
        self.assertEqual(c["inconnus"], [], "un groupe ne cite que des marchands allowlistés")

    def test_le_seul_marchand_hors_groupe_est_difmark_et_la_raison_est_ecrite(self):
        self.assertEqual(coverage()["hors_groupes"], ["Difmark"])
        self.assertIn("liste account", EXCLUDED["Difmark"])

    def test_les_deux_groupes_sont_a_peu_pres_equilibres(self):
        charges = coverage()["charge_estimee"]
        a, b = charges["A"], charges["B"]
        self.assertLess(abs(a - b) / max(a, b), 0.20, f"déséquilibre trop grand : {charges}")

    def test_un_groupe_rend_des_cibles_utilisables(self):
        cibles = group_targets("a")                     # insensible à la casse
        self.assertIn(("GameSeal", "126"), cibles)
        connus = {(n, s) for n, s in AUTO_MERCHANTS}
        self.assertTrue(set(cibles) <= connus)

    def test_un_groupe_inconnu_leve(self):
        with self.assertRaises(KeyError):
            group_targets("Z")


class LeDecoupageSuitLeNombreDeMachines(unittest.TestCase):
    """« Je compte prendre un troisième et quatrième VPS » — les groupes ne sont pas gravés
    à deux."""

    def test_chaque_marchand_apparait_une_fois_et_une_seule(self):
        attendus = sorted(n for n, _ in AUTO_MERCHANTS if n not in EXCLUDED)
        for n in (1, 2, 3, 4, 8):
            with self.subTest(machines=n):
                groupes = split(n)
                self.assertEqual(len(groupes), n)
                plat = sorted(m for g in groupes for m in g)
                self.assertEqual(plat, attendus)

    def test_le_decoupage_est_deterministe(self):
        self.assertEqual(split(4), split(4))

    def test_les_deux_plus_gros_ne_partagent_jamais_une_machine(self):
        """La propriété qui compte vraiment, et qui survit à un nouveau marchand.

        Le test disait avant « GameSeal est SEUL sur sa machine à quatre ». C'était vrai de
        la charge du 2026-09-21, pas du découpage : l'entrée de GOG (3 473 lignes) le
         2026-09-22 a monté la moyenne, et GameSeal partage désormais sa machine avec deux
        petites files — pour un équilibre MEILLEUR qu'avant (6 000 / 5 879 / 5 872 / 5 907).
        Épingler la composition exacte d'un groupe, c'est épingler une mesure ; ce qu'on
        veut garantir, c'est que deux poids lourds ne se retrouvent jamais ensemble."""

        from src.merchant_groups import PENDING_2026_09_21 as P
        lourds = sorted(P, key=lambda m: -P[m])[:2]
        for n in (2, 3, 4):
            with self.subTest(machines=n):
                for g in split(n):
                    ensemble = [m for m in lourds if m in g]
                    if n == 1:
                        continue
                    self.assertLess(len(ensemble), 2,
                                    f"{ensemble} sur la même machine à {n} machines")

    def test_l_equilibre_tient_jusqu_a_quatre(self):
        for n in (2, 3, 4):
            with self.subTest(machines=n):
                charges = [sum(PENDING_2026_09_21.get(m, 0) for m in g) for g in split(n)]
                self.assertLess((max(charges) - min(charges)) / max(charges), 0.16, charges)

    def test_la_forme_i_sur_n(self):
        self.assertEqual([m for m, _ in targets_for("1/4")], split(4)[0])
        for mauvais in ("0/4", "5/4", "a/b", "2/"):
            with self.subTest(spec=mauvais):
                with self.assertRaises(KeyError):
                    targets_for(mauvais)

    def test_le_cli_du_balayage_expose_le_groupe_et_refuse_les_melanges(self):
        src = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")
        self.assertIn('"--group"', src)
        self.assertIn("targets_for(args.group)", src)
        self.assertIn("--group porte déjà sa liste de marchands", src)


if __name__ == "__main__":
    unittest.main()


class LaConsoleVoitLesGroupes(unittest.TestCase):
    """Romain, 2026-09-22 : « je ne vois pas les groupes A et B sur l'admin ». La console ne
    les invente pas : le serveur les SERT et détend lui-même le nom en cibles — un client
    bricolé ne peut pas fabriquer une liste de marchands par ce chemin."""

    def test_la_route_des_marchands_sert_les_groupes(self):
        from src.admin.app import _auto_groups

        groupes = _auto_groups()
        self.assertEqual([g["name"] for g in groupes], ["A", "B"])
        for g in groupes:
            with self.subTest(groupe=g["name"]):
                self.assertTrue(g["merchants"])
                self.assertIn("store_id", g["merchants"][0])
                self.assertGreater(g["pending"], 0)

    def test_le_serveur_detend_le_nom_et_refuse_linconnu(self):
        src = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")
        self.assertIn("targets_for(group)", src)
        self.assertIn("unknown_group", src)
        self.assertIn("targets_conflict", src)

    def test_la_console_est_verifiee_en_lexecutant_pas_en_la_lisant(self):
        """Ce que fait l'écran est vérifié par `tests/js/auto_groups.test.mjs`, qui CHARGE
        le fichier livré dans un DOM bouchonné, clique et regarde ce qui part. Une lecture
        de texte n'aurait pas vu la panne de Romain — le code était écrit, il ne s'affichait
        pas. On ne garde ici que le lien, pour qu'il ne se perde pas."""

        harnais = ROOT / "tests" / "js" / "auto_groups.test.mjs"
        self.assertTrue(harnais.is_file(), "le harnais d'exécution de auto.js a disparu")
        self.assertIn('"src", "admin", "static", "auto.js"',
                      harnais.read_text(encoding="utf-8"),
                      "le harnais doit charger la console LIVRÉE, jamais une copie")
