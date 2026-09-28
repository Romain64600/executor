#!/usr/bin/env python3
"""Génère les schémas SVG (`../schemas/`) et assemble l'annexe technique
`../annexe_technique/presentation_technique.html` (19 diapositives, chiffres arrêtés au 27/09).

Le diaporama de 3 minutes (`../presentation.html`) a son propre générateur : `generer_3min.py`.

Python 3 standard uniquement (pas de graphviz, pas de bibliothèque). Les schémas sont
dessinés « à la main » : des boîtes, des flèches, du texte — lisibles en 1920×1080 et à
l'impression. Le diaporama inline chaque SVG (fichier autonome, aucune requête externe).

    python3 docs/presentation_2026-09-28/outils/generer.py

Les chiffres viennent de `donnees_creations.json` (méthode : `../chiffres.md`).
"""
from __future__ import annotations

import json
import pathlib
import re
from xml.sax.saxutils import escape

ICI = pathlib.Path(__file__).resolve().parent
DOSSIER = ICI.parent
SCHEMAS = DOSSIER / "schemas"
DONNEES = json.loads((ICI / "donnees_creations.json").read_text(encoding="utf-8"))

# Palette (référence dataviz, mode clair) — le texte porte toujours une couleur de texte,
# jamais la couleur d'une série.
SURFACE = "#fcfcfb"
ENCRE = "#0b0b0b"
ENCRE_2 = "#52514e"
TRAIT = "#c9c7c0"
BLEU = "#2a78d6"      # série 1 / accent
BLEU_CLAIR = "#e3eefb"
AQUA = "#1baf7a"      # preuve / ok
AQUA_CLAIR = "#e0f5ec"
ORANGE = "#eb6834"    # refus / attention
ORANGE_CLAIR = "#fde7dd"
ROUGE = "#e34948"     # arrêt
ROUGE_CLAIR = "#fbe1e1"
VIOLET = "#4a3aa7"
VIOLET_CLAIR = "#e9e6f7"
GRIS_CLAIR = "#f1f0ec"
POLICE = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"


class Svg:
    """Un dessin : on empile des primitives, on écrit le fichier."""

    def __init__(self, w: int, h: int, titre: str, description: str):
        self.w, self.h = w, h
        self.titre = titre
        self.parts: list[str] = []
        self.parts.append(
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="{SURFACE}"/>')
        self.description = description

    # ── primitives ──────────────────────────────────────────────────────────────
    def texte(self, x, y, s, taille=22, poids="normal", ancre="start", couleur=ENCRE,
              italique=False, espace=None):
        style = f"font-family:{POLICE};font-size:{taille}px;font-weight:{poids};fill:{couleur}"
        if italique:
            style += ";font-style:italic"
        extra = f' letter-spacing="{espace}"' if espace else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" text-anchor="{ancre}" style="{style}"{extra}>{escape(s)}</text>')

    def lignes(self, x, y, lignes, taille=20, interligne=None, couleur=ENCRE_2, ancre="start",
               poids="normal"):
        il = interligne or int(taille * 1.35)
        for i, l in enumerate(lignes):
            self.texte(x, y + i * il, l, taille, poids, ancre, couleur)
        return y + len(lignes) * il

    def boite(self, x, y, w, h, titre=None, corps=(), fond="#ffffff", bord=TRAIT, rayon=14,
              taille_titre=24, taille_corps=19, bord_epais=2, couleur_titre=ENCRE, pointille=False):
        dash = ' stroke-dasharray="10 8"' if pointille else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rayon}" ry="{rayon}" '
            f'fill="{fond}" stroke="{bord}" stroke-width="{bord_epais}"{dash}/>')
        cy = y + 34
        if titre:
            self.texte(x + w / 2, cy, titre, taille_titre, "600", "middle", couleur_titre)
            cy += 30
        if corps:
            self.lignes(x + w / 2, cy, corps, taille_corps, None, ENCRE_2, "middle")
        return (x, y, w, h)

    def fleche(self, x1, y1, x2, y2, etiquette=None, couleur=ENCRE_2, epais=3, pointille=False,
               taille=18, decal=(0, -10)):
        dash = ' stroke-dasharray="9 7"' if pointille else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{couleur}" '
            f'stroke-width="{epais}" marker-end="url(#pointe)"{dash}/>')
        if etiquette:
            mx, my = (x1 + x2) / 2 + decal[0], (y1 + y2) / 2 + decal[1]
            self.texte(mx, my, etiquette, taille, "normal", "middle", ENCRE_2, italique=True)

    def coude(self, points, etiquette=None, couleur=ENCRE_2, epais=3, pointille=False, taille=18,
              pos_etiquette=None):
        """Flèche brisée passant par `points` (liste de (x, y))."""
        d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(points))
        dash = ' stroke-dasharray="9 7"' if pointille else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{couleur}" stroke-width="{epais}" '
            f'marker-end="url(#pointe)"{dash}/>')
        if etiquette:
            x, y = pos_etiquette or points[len(points) // 2]
            self.texte(x, y - 10, etiquette, taille, "normal", "middle", ENCRE_2, italique=True)

    def pastille(self, x, y, s, fond=BLEU, couleur="#ffffff", r=18, taille=18):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fond}"/>')
        self.texte(x, y + 6, s, taille, "700", "middle", couleur)

    def legende(self, x, y, items, taille=18):
        """items = [(couleur_fond, couleur_bord, libellé)]"""
        cx = x
        for fond, bord, lib in items:
            self.parts.append(
                f'<rect x="{cx}" y="{y - 14}" width="26" height="18" rx="4" fill="{fond}" '
                f'stroke="{bord}" stroke-width="2"/>')
            self.texte(cx + 34, y, lib, taille, "normal", "start", ENCRE_2)
            cx += 34 + len(lib) * taille * 0.56 + 36

    def ecrire(self, chemin: pathlib.Path):
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" role="img" aria-labelledby="t d">\n'
            f'<title id="t">{escape(self.titre)}</title>\n'
            f'<desc id="d">{escape(self.description)}</desc>\n'
            '<defs><marker id="pointe" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{ENCRE_2}"/></marker></defs>\n'
        )
        chemin.write_text(head + "\n".join(self.parts) + "\n</svg>\n", encoding="utf-8")


def titre_schema(s: Svg, titre: str, sous_titre: str | None = None):
    s.texte(60, 62, titre, 34, "700", "start", ENCRE)
    if sous_titre:
        s.texte(60, 96, sous_titre, 20, "normal", "start", ENCRE_2, italique=True)


# ─────────────────────────────────────────────────────────────────────────────────
# 01 — vue d'ensemble
# ─────────────────────────────────────────────────────────────────────────────────
def schema_vue_d_ensemble():
    s = Svg(1600, 900, "Vue d'ensemble du système",
            "L'opérateur pilote, depuis la console d'admin, un exécuteur qui lit le feed AKS "
            "à travers un Chrome piloté par CDP, lit les pages AKS en HTTP, et écrit chaque "
            "action dans un journal. Deux VPS, un groupe de marchands chacun.")
    titre_schema(s, "Vue d'ensemble — qui parle à qui",
                 "Un VPS = une console, un exécuteur, un navigateur, un groupe de marchands. Deux VPS en parallèle.")

    # Opérateur
    s.boite(60, 330, 250, 200, "Opérateur", ["lance un groupe, un marchand", "suit la page en cours",
                                             "relit le récap", "transfère les cookies", "quand la session expire"],
            fond=GRIS_CLAIR)

    # Cadre VPS
    s.boite(380, 150, 760, 690, None, fond="#ffffff", bord=BLEU, rayon=22, bord_epais=3, pointille=True)
    s.texte(400, 190, "VPS (×2 — chacun balaie un groupe de marchands, une nuit)", 22, "600", "start", BLEU)

    s.boite(420, 220, 300, 150, "Console d'admin", ["/executor/auto : groupes, pages",
                                                    "N→1, page en cours, récap, arrêt",
                                                    "/executor/tri : cookies (reconnexion)"], fond=BLEU_CLAIR, bord=BLEU, taille_corps=17)
    s.boite(420, 420, 300, 190, "Exécuteur", ["scripts 02 → 05 par page :",
                                              "extraction · matching · validation",
                                              "· saisie · preuve",
                                              "orchestrateur 10 (sweep),",
                                              "StepGuard entre chaque étape"], fond=BLEU_CLAIR, bord=BLEU, taille_corps=17)
    s.boite(420, 660, 300, 150, "Journal", ["logs/<run>.jsonl : chaque action",
                                            "runs/<run>/ : offers, candidates,",
                                            "approved, submit_plan, recap"], fond=GRIS_CLAIR, taille_corps=17)
    s.boite(800, 420, 310, 190, "Chrome piloté par CDP", ["session WordPress connectée",
                                                          "(cookies transférés par l'opérateur)",
                                                          "un seul onglet, un verrou :",
                                                          "un balayage à la fois par machine",
                                                          "UA officiel, endpoint officiel"], fond=VIOLET_CLAIR, bord=VIOLET, taille_corps=17)

    # AKS
    s.boite(1220, 200, 330, 230, "AKS — wp-admin", ["outil « merchant feeds »",
                                                    "Pending offers (liste 9)",
                                                    "formulaire de création d'offre",
                                                    "(région / édition / cibles)"], fond=ORANGE_CLAIR, bord=ORANGE)
    s.boite(1220, 480, 330, 200, "AKS — site public", ["pages produit (éditions, régions,",
                                                        "plateformes officielles)",
                                                        "sitemap : 213 599 pages",
                                                        "lecture HTTP, UA « AKS/Staff »"], fond=ORANGE_CLAIR, bord=ORANGE)
    s.boite(1220, 730, 330, 110, "Marchands", ["feeds importés par AKS",
                                                "pages produits (lues pour certains)"], fond=GRIS_CLAIR)

    # Flèches
    s.fleche(310, 400, 420, 320, "navigateur", decal=(0, -14))
    s.fleche(570, 370, 570, 420, "lance, suit", decal=(70, 0))
    s.fleche(570, 610, 570, 660, "écrit")
    s.fleche(720, 515, 800, 515, "CDP", decal=(0, -12))
    s.coude([(1110, 470), (1170, 470), (1170, 315), (1220, 315)], "lit le feed · remplit · clique « Create »",
            pos_etiquette=(1165, 150 + 20))
    s.fleche(720, 560, 1220, 580, "HTTP lecture seule (matching)", decal=(0, 62), pointille=True)
    s.fleche(1385, 730, 1385, 680, "", pointille=True)
    s.texte(1395, 712, "import", 16, "normal", "start", ENCRE_2, italique=True)
    s.fleche(1385, 480, 1385, 430, "", pointille=True)
    s.texte(1395, 460, "même catalogue", 16, "normal", "start", ENCRE_2, italique=True)
    s.coude([(1220, 800), (1000, 800), (1000, 610)], "page produit marchand",
            pointille=True, pos_etiquette=(1000, 840))

    s.ecrire(SCHEMAS / "01_vue_d_ensemble.svg")


# ─────────────────────────────────────────────────────────────────────────────────
# 02 — pipeline d'une page
# ─────────────────────────────────────────────────────────────────────────────────
def schema_pipeline_page():
    s = Svg(1600, 900, "Le pipeline d'une page du feed",
            "Cinq étapes enchaînées par page : extraction, matching, validation, saisie, preuve. "
            "Chaque étape lit et écrit des fichiers du run ; StepGuard sépare les étapes ; "
            "le journal JSONL reçoit chaque action.")
    titre_schema(s, "Le pipeline — ce qui arrive à UNE page du feed (100 offres)",
                 "Le balayage prend les pages de la plus haute à la 1 ; chaque page repasse par les cinq étapes, avec le code du moment.")

    etapes = [
        ("1 · Extraction", "02_extract_feed", ["lit la page du feed", "via le navigateur (CDP)", "lecture seule"],
         ["offers.json", "raw.json"], BLEU_CLAIR, BLEU),
        ("2 · Matching", "03_match", ["règles + HTTP lecture seule", "sitemap → page AKS → plateforme,", "région, édition, cibles"],
         ["candidates.json", "skipped.json", "report.txt"], BLEU_CLAIR, BLEU),
        ("3 · Validation", "approve", ["le lot validé est figé", "(mode safe : tout le lot ;", "learning/advanced : canary de 1)"],
         ["approved.json", "validation.json"], VIOLET_CLAIR, VIOLET),
        ("4 · Saisie", "05_submit", ["pour chaque candidate :", "retrouver la ligne (titre, URL,", "magasin), ouvrir la modale,", "vérifier, remplir, « Create »"],
         ["submit_plan.json", "guard_ledger.json"], ORANGE_CLAIR, ORANGE),
        ("5 · Preuve", "dans le submitter", ["feed rafraîchi :", "l'offre a disparu = succès", "sinon échec ; illisible après", "un clic = état INCONNU → arrêt"],
         ["submit_report.txt", "recap.json"], AQUA_CLAIR, AQUA),
    ]
    x0, w, gap, y = 60, 280, 22, 150
    for i, (t, script, corps, sorties, fond, bord) in enumerate(etapes):
        x = x0 + i * (w + gap)
        s.boite(x, y, w, 300, t, [script] + [""] + corps, fond=fond, bord=bord, taille_corps=17)
        s.boite(x + 20, y + 330, w - 40, 40 + 30 * len(sorties), None, sorties, fond="#ffffff", taille_corps=18)
        s.texte(x + w / 2, y + 330 - 8, "écrit", 15, "normal", "middle", ENCRE_2, italique=True)
        s.fleche(x + w / 2, y + 300, x + w / 2, y + 330, epais=2)
        if i < len(etapes) - 1:
            s.fleche(x + w, y + 120, x + w + gap, y + 120, epais=3)
            s.pastille(x + w + gap / 2, y + 60, "G", fond=ENCRE_2, r=14, taille=15)
    s.texte(60, 128, "G = StepGuard : l'étape suivante ne démarre que si la précédente a rendu un résultat valide (fichier présent, lisible, complet). Un blocage = arrêt, pas de reprise « en discutant ».",
            16, "normal", "start", ENCRE_2, italique=True)

    # journal
    s.boite(60, 640, 1480, 100, None, ["Journal logs/<run>.jsonl — une ligne par action, horodatée : feed_page, match_progress, validation_saved, submit_offer (success, post_save), run_stopped…",
                                        "recap.json — l'état du balayage, lu par la console : marchand, page en cours et son étape, créées, échecs, arrêts."],
            fond=GRIS_CLAIR, taille_corps=18)
    s.boite(60, 770, 1480, 90, None, ["Après la dernière page : le marchand suivant du groupe. Un arrêt fail-closed (état inconnu, 10 échecs, session perdue) arrête CE marchand ; le groupe continue.",
                                       "Une panne passagère AVANT toute écriture (navigateur muet, feed illisible) : la page est refaite après 2, 5 puis 10 min, trois fois au plus."],
            fond="#ffffff", taille_corps=18)
    s.ecrire(SCHEMAS / "02_pipeline_page.svg")


# ─────────────────────────────────────────────────────────────────────────────────
# 03 — parcours d'une offre
# ─────────────────────────────────────────────────────────────────────────────────
def schema_parcours_offre():
    s = Svg(1600, 900, "Le parcours d'une offre dans le matching",
            "Une ligne du feed traverse six décisions : precheck, page AKS, plateforme, région, "
            "édition, cibles. À chaque étape, un refus explicite est possible ; ce qui reste "
            "est une candidate.")
    titre_schema(s, "Le parcours d'une offre — six décisions, et un refus possible à chacune",
                 "Chaque décision est une règle écrite ([Rnn] dans EXECUTOR_RULES.md) ou une grammaire propre au marchand (src/merchants/<marchand>.py).")

    etapes = [
        ("Ligne du feed", ["titre · URL · marchand · prix", "« Dune: Awakening US PS5 CD Key »"], GRIS_CLAIR, TRAIT,
         None),
        ("1 · Precheck", ["catégories hors jeu (cartes, monnaies,", "comptes, bundles…), régions interdites,", "console sans génération lisible"], BLEU_CLAIR, BLEU,
         ["carte cadeau, points, compte", "région ROW / Amérique du Nord", "PlayStation sans PS4/PS5"]),
        ("2 · Page AKS", ["sitemap d'abord (213 599 pages),", "puis le slug, puis une recherche bornée ;", "le nom doit correspondre (R01)"], BLEU_CLAIR, BLEU,
         ["pas de page AKS", "produit différent ou élargi"]),
        ("3 · Plateforme", ["Steam, Epic, GOG, Ubisoft, EA, Microsoft…", "lue dans le titre, l'URL ou la page produit ;", "la page AKS doit la vendre (R20)"], BLEU_CLAIR, BLEU,
         ["plateforme non vendue sur la page", "« PC » sans boutique (sauf règle marchand)"]),
        ("4 · Région", ["grammaire du marchand → case AKS :", "GLOBAL (2), EU (9), US (8)… ;", "consoles : PS5 EU → 88eu, Xbox US → 24us"], BLEU_CLAIR, BLEU,
         ["verrou non vendable", "région absente et non implicite"]),
        ("5 · Édition", ["Standard, Deluxe, Ultimate… ; DLC par R18/R43 ;", "« <Jeu> <X> Edition » = jeu + DLC →", "page du jeu, édition « X Edition » (R18c)"], BLEU_CLAIR, BLEU,
         ["édition non vendue sur la page (E06)", "palier absent de la page (R18b)"]),
        ("6 · Cibles", ["PC : la page ; consoles : une page par", "plateforme déclarée (PS4/PS5, One/Series,", "Switch) ; Xbox + PC = Play Anywhere"], BLEU_CLAIR, BLEU,
         ["page console absente", "tout ou rien : jamais une cible sur deux"]),
    ]
    y0, h, pas = 120, 90, 96
    x, w = 330, 620
    for i, (t, corps, fond, bord, refus) in enumerate(etapes):
        y = y0 + i * pas
        s.boite(x, y, w, h, None, [], fond=fond, bord=bord, rayon=12)
        s.texte(x + 20, y + 30, t, 21, "600", "start", ENCRE)
        s.lignes(x + 20, y + 52, corps, 15, 17, ENCRE_2)
        if i < len(etapes) - 1:
            s.fleche(x + w / 2, y + h, x + w / 2, y + pas, epais=3)
        if refus:
            rx = x + w + 60
            s.boite(rx, y + 6, 520, h - 12, None, [], fond=ORANGE_CLAIR, bord=ORANGE, rayon=10)
            s.texte(rx + 16, y + 30, "refus typiques :", 14, "600", "start", ORANGE)
            s.lignes(rx + 16, y + 50, refus, 14, 16, ENCRE_2)
            s.fleche(x + w, y + h / 2, rx, y + h / 2, epais=2, couleur=ORANGE)
    # sortie
    y = y0 + len(etapes) * pas
    s.boite(x, y, w, 70, None, [], fond=AQUA_CLAIR, bord=AQUA, rayon=12)
    s.texte(x + w / 2, y + 30, "Candidate", 22, "700", "middle", ENCRE)
    s.texte(x + w / 2, y + 54, "page(s) AKS · plateforme · case de région · édition — prête pour la validation, puis la saisie", 14, "normal", "middle", ENCRE_2)
    # légende gauche
    s.lignes(60, 200, ["Ce qui décide :", "", "• le fichier du marchand", "  (21 fichiers, un par", "  marchand en liste blanche)", "", "• les règles générales", "  [R01] … [R62]", "", "• jamais le prix", "  (signal de routage,", "  pas un juge)", "", "• au moindre doute :", "  refus explicite,", "  jamais une valeur", "  par défaut"], 18, 24, ENCRE_2)
    s.ecrire(SCHEMAS / "03_parcours_offre.svg")


# ─────────────────────────────────────────────────────────────────────────────────
# 04 — fail-closed
# ─────────────────────────────────────────────────────────────────────────────────
def schema_fail_closed():
    s = Svg(1600, 900, "Les gardes fail-closed de la saisie",
            "De l'ouverture du navigateur à la preuve : invariants, StepGuard, validation, "
            "vérification de la ligne et de la modale, clic sur le vrai bouton, preuve de "
            "disparition. Sur les côtés, ce qui arrête tout et ce qui est repris.")
    titre_schema(s, "Fail-closed — on n'écrit que ce qu'on a prouvé, et on prouve ce qu'on a écrit",
                 "Chaque garde est du code déterministe et testé : jamais une appréciation « au jugé ».")

    gardes = [
        ("Invariants", ["VPS autoritaire,", "endpoint CDP officiel,", "UA officiel,", "AKS joignable,", "pas de VPN"]),
        ("StepGuard", ["chaque étape rend", "un résultat valide,", "ou tout s'arrête ;", "pas de « retry", "en discutant »"]),
        ("Validation", ["seul approved.json", "est saisi ; son", "empreinte est liée", "à l'aperçu montré", "au GO tapé"]),
        ("La ligne", ["retrouvée sur le", "feed courant : titre,", "URL (identité) et", "magasin vérifiés ;", "sinon ignorée"]),
        ("La modale", ["ouverte depuis", "CETTE ligne ;", "contexte vérifié ;", "champs visibles :", "région, édition, cibles"]),
        ("Le clic", ["le vrai bouton", "« Create », visible ;", "jamais un appel", "AJAX fabriqué"]),
        ("La preuve", ["feed rafraîchi,", "même liste, même", "mode : l'offre a", "disparu = succès.", "Jamais un message", "de la page"]),
    ]
    x0, w, gap, y = 60, 196, 18, 150
    for i, (t, corps) in enumerate(gardes):
        x = x0 + i * (w + gap)
        fond, bord = (AQUA_CLAIR, AQUA) if i == len(gardes) - 1 else (BLEU_CLAIR, BLEU)
        s.boite(x, y, w, 230, None, [], fond=fond, bord=bord, rayon=12)
        s.pastille(x + 28, y + 30, str(i + 1), fond=bord, r=16, taille=16)
        s.texte(x + 54, y + 36, t, 20, "600", "start", ENCRE)
        s.lignes(x + 16, y + 74, corps, 14, 20, ENCRE_2)
        if i < len(gardes) - 1:
            s.fleche(x + w, y + 115, x + w + gap, y + 115, epais=2)

    # Arrêts
    s.texte(60, 440, "Ce qui ARRÊTE (jamais repris automatiquement)", 22, "700", "start", ROUGE)
    arrets = [
        ("État inconnu après un clic", "feed illisible ou session perdue juste après « Create » : arrêt, vérification à la main"),
        ("Dix échecs d'affilée", "garde inter-processus (guard ledger) : une série d'échecs arrête le marchand, la console le montre"),
        ("Session perdue", "arrêt du marchand ; la reconnexion est un transfert de cookies fait par l'opérateur, jamais par le code"),
        ("Garde StepGuard bloquée", "un fichier absent, illisible ou incohérent entre deux étapes : arrêt et rapport d'erreur"),
    ]
    for i, (t, d) in enumerate(arrets):
        y = 470 + i * 62
        s.boite(60, y, 720, 52, None, [], fond=ROUGE_CLAIR, bord=ROUGE, rayon=10)
        s.texte(76, y + 22, t, 17, "600", "start", ENCRE)
        s.texte(76, y + 42, d, 14, "normal", "start", ENCRE_2)

    # Repris
    s.texte(820, 440, "Ce qui est REPRIS (rien n'a pu être écrit)", 22, "700", "start", AQUA)
    reprises = [
        ("Navigateur muet à la lecture", "extraction ou sonde qui n'obtient pas de réponse : page refaite après 2, 5 puis 10 min"),
        ("Feed illisible avant la première offre", "contrôle de connexion, catalogue, scan d'index : aucune offre ouverte, aucun clic → reprise"),
        ("Panne avant le clic « Create »", "la modale n'a pas été soumise : l'offre est intacte → reprise de la page"),
        ("Un doute sur une offre = un refus", "pas une reprise, pas une valeur par défaut : la ligne reste au feed pour un humain"),
    ]
    for i, (t, d) in enumerate(reprises):
        y = 470 + i * 62
        s.boite(820, y, 720, 52, None, [], fond=AQUA_CLAIR, bord=AQUA, rayon=10)
        s.texte(836, y + 22, t, 17, "600", "start", ENCRE)
        s.texte(836, y + 42, d, 14, "normal", "start", ENCRE_2)

    s.boite(60, 740, 1480, 110, None, ["Hors du code, deux règles humaines : le submit n'est jamais « lancé et oublié » (processus attaché ou supervisé, code de sortie et plan relus avant toute suite),",
                                        "et une décision de Romain devient une règle écrite, un test qui la fige, et une entrée « décision revue » pour qu'un audit futur ne la défasse pas."],
            fond=GRIS_CLAIR, taille_corps=17)
    s.ecrire(SCHEMAS / "04_fail_closed.svg")


# ─────────────────────────────────────────────────────────────────────────────────
# 05 — exploitation
# ─────────────────────────────────────────────────────────────────────────────────
def schema_exploitation():
    s = Svg(1600, 900, "L'exploitation : deux VPS, deux groupes, des nuits de balayage",
            "Le groupe A tourne sur un VPS, le groupe B sur l'autre. L'opérateur lance depuis la "
            "console, suit la page en cours, transfère les cookies quand la session expire.")
    titre_schema(s, "L'exploitation — deux machines, deux groupes, une console par machine",
                 "Un balayage tient un onglet de navigateur ; une machine = un groupe. Les groupes sont équilibrés sur la charge en attente, et éditables.")

    groupes = [
        ("VPS n° 1 — groupe A", "11 marchands · ~13 810 lignes en attente (21/09)",
         ["GameSeal", "G2A", "GameBoost", "Driffle", "Instant Gaming", "MMOGA", "GamersOutlet", "GOG", "Gamesplanet FR", "Discover.games", "Loaded"]),
        ("VPS n° 2 — groupe B", "9 marchands · ~15 555 lignes en attente (21/09)",
         ["Gamivo", "Eneba", "Kinguin", "CJS-CDKeys", "Gamerall", "Electronicfirst", "Allyouplay", "K4G", "Wyrel"]),
    ]
    for i, (t, charge, membres) in enumerate(groupes):
        x = 60 + i * 520
        s.boite(x, 140, 480, 470, None, [], fond="#ffffff", bord=BLEU, rayon=18, bord_epais=3)
        s.texte(x + 24, 180, t, 24, "700", "start", BLEU)
        s.texte(x + 24, 208, charge, 16, "normal", "start", ENCRE_2, italique=True)
        s.boite(x + 24, 230, 200, 60, None, ["Console"], fond=BLEU_CLAIR, bord=BLEU, rayon=10, taille_corps=18)
        s.boite(x + 256, 230, 200, 60, None, ["Chrome (CDP)"], fond=VIOLET_CLAIR, bord=VIOLET, rayon=10, taille_corps=18)
        s.boite(x + 24, 310, 432, 60, None, ["Exécuteur — pages N → 1, marchand après marchand"], fond=BLEU_CLAIR, bord=BLEU, rayon=10, taille_corps=17)
        col = 0
        for j, m in enumerate(membres):
            cx = x + 24 + (j % 3) * 146
            cy = 400 + (j // 3) * 48
            s.boite(cx, cy, 136, 36, None, [], fond=GRIS_CLAIR, rayon=8)
            s.texte(cx + 68, cy + 24, m, 15, "normal", "middle", ENCRE)
    s.texte(1130, 180, "Difmark : hors groupe", 18, "600", "start", ENCRE)
    s.lignes(1130, 206, ["(ses lignes vivent dans la liste", "« account », saisie à la main)"], 15, 19, ENCRE_2)

    # opérateur + cadence
    s.boite(1130, 270, 410, 150, "Opérateur", ["tape GO, choisit le groupe, les pages (toutes,", "ou de N à 1) et la liste ; suit la page en cours ;", "relance un marchand arrêté ; transfère les cookies"], fond=GRIS_CLAIR, taille_corps=15)
    s.boite(1130, 450, 410, 160, "Cadence mesurée", ["≈ 2,5 min pour lire et matcher une page", "≈ 1 min par offre créée (preuve comprise)", "une nuit de groupe : 20 à 40 h selon la charge", "record : 2 627 offres créées le 26/09"], fond=AQUA_CLAIR, bord=AQUA, taille_corps=15)

    s.boite(60, 650, 1480, 200, None, [
        "Ce que voit l'opérateur pendant la nuit : le marchand dès son démarrage, la page en cours et son étape (lecture, matching, saisie), les créées et les échecs en direct,",
        "puis le récap : par marchand, par page, chaque offre créée avec son id AKS. Un arrêt fail-closed est nommé (état inconnu, 10 échecs, session) et le groupe passe au marchand suivant.",
        "",
        "Deux règles : jamais de submit « lancé et oublié » ; jamais de reconnexion automatique — la session est renouvelée par l'opérateur (transfert de cookies dans /executor/tri).",
    ], fond="#ffffff", taille_corps=17)
    s.ecrire(SCHEMAS / "05_exploitation.svg")


# ─────────────────────────────────────────────────────────────────────────────────
# 06 — résultats par marchand (barres) · 07 — par jour (colonnes)
# ─────────────────────────────────────────────────────────────────────────────────
def _barre_h(s: Svg, x, y, w, h, fond):
    """Barre horizontale : base carrée à gauche, bout arrondi (4 px) à droite."""
    r = 4 if w >= 8 else 0
    d = (f"M{x},{y} h{max(w - r, 0)} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r} a{r},{r} 0 0 1 {-r},{r} "
         f"H{x} Z")
    s.parts.append(f'<path d="{d}" fill="{fond}"/>')


def _colonne(s: Svg, x, y_base, w, h, fond):
    """Colonne : base carrée, sommet arrondi (4 px)."""
    r = 4 if h >= 8 else 0
    y = y_base - h
    d = (f"M{x},{y_base} V{y + r} a{r},{r} 0 0 1 {r},{-r} h{w - 2 * r} a{r},{r} 0 0 1 {r},{r} "
         f"V{y_base} Z")
    s.parts.append(f'<path d="{d}" fill="{fond}"/>')


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def schema_resultats():
    data = DONNEES["per_merchant"]
    total = DONNEES["total"]
    s = Svg(1600, 900, "Offres créées par marchand",
            f"Diagramme en barres : {fmt(total)} offres créées et prouvées disparues du feed, "
            "par marchand, du 6 juillet au 27 septembre 2026, sur les deux VPS.")
    titre_schema(s, f"Offres créées par marchand — {fmt(total)} au total (6 juillet → 27 septembre 2026, 2 VPS)",
                 "Une offre est comptée quand la saisie est PROUVÉE : l'offre a disparu du feed rafraîchi. Source : journaux JSONL des deux machines (méthode dans chiffres.md).")
    x_lib, x_bar, larg_max = 60, 300, 1180
    y0, pas, ep = 140, 40, 22
    vmax = max(v for _, v in data)
    for i, (m, v) in enumerate(data):
        y = y0 + i * pas
        s.texte(x_bar - 16, y + ep - 5, m, 18, "normal", "end", ENCRE)
        w = larg_max * v / vmax
        _barre_h(s, x_bar, y, w, ep, BLEU)
        s.texte(x_bar + w + 12, y + ep - 5, fmt(v), 17, "normal", "start", ENCRE_2)
    # axe recessif
    s.parts.append(f'<line x1="{x_bar}" y1="{y0 - 8}" x2="{x_bar}" y2="{y0 + len(data) * pas}" stroke="{TRAIT}" stroke-width="1.5"/>')
    s.texte(60, 880, "Les valeurs par marchand reflètent aussi la taille de leur file et la date de leur entrée en liste blanche (Wyrel le 24/09, Gamesplanet FR le 25/09, Discover.games et Loaded le 26/09 : pas encore balayés).",
            15, "normal", "start", ENCRE_2, italique=True)
    s.ecrire(SCHEMAS / "06_resultats.svg")


def schema_par_jour():
    jours = [(d, v) for d, v in DONNEES["per_day"] if d >= "2026-09-14"]
    s = Svg(1600, 900, "Offres créées par jour, 14 derniers jours",
            "Diagramme en colonnes : offres créées chaque jour du 14 au 27 septembre 2026, "
            "deux VPS confondus.")
    tot14 = sum(v for _, v in jours)
    titre_schema(s, f"Offres créées par jour — {fmt(tot14)} sur les 14 derniers jours (14 → 27 septembre 2026)",
                 "Les creux sont des jours sans balayage de nuit ou consacrés aux corrections ; le 27 est une journée partielle (arrêté le matin).")
    x0, y_base, hmax = 120, 760, 540
    vmax = max(v for _, v in jours)
    n = len(jours)
    pas = 1400 / n
    # grille recessive (4 lignes)
    for k in range(1, 5):
        yy = y_base - hmax * k / 4
        s.parts.append(f'<line x1="{x0}" y1="{yy}" x2="{x0 + 1400}" y2="{yy}" stroke="{TRAIT}" stroke-width="1" stroke-dasharray="4 6"/>')
        s.texte(x0 - 12, yy + 6, fmt(int(vmax * k / 4)), 15, "normal", "end", ENCRE_2)
    s.parts.append(f'<line x1="{x0}" y1="{y_base}" x2="{x0 + 1400}" y2="{y_base}" stroke="{TRAIT}" stroke-width="1.5"/>')
    imax = max(range(n), key=lambda i: jours[i][1])
    for i, (d, v) in enumerate(jours):
        cx = x0 + pas * i + pas / 2
        h = hmax * v / vmax
        _colonne(s, cx - 12, y_base, 24, h, BLEU)
        s.texte(cx, y_base + 28, d[8:10] + "/" + d[5:7], 16, "normal", "middle", ENCRE_2)
        if i in (imax, n - 1) or v == min(x for _, x in jours):
            s.texte(cx, y_base - h - 10, fmt(v), 16, "600", "middle", ENCRE)
    s.texte(60, 850, "Lecture : les gros jours (19-20/09, 26/09) sont des nuits de groupe complètes sur les deux machines ; le 26/09 cumule le groupe A, la fin du groupe B et les nouvelles règles console.",
            15, "normal", "start", ENCRE_2, italique=True)
    s.ecrire(SCHEMAS / "07_offres_par_jour.svg")


# ─────────────────────────────────────────────────────────────────────────────────
# Assemblage du diaporama
# ─────────────────────────────────────────────────────────────────────────────────
def assembler():
    gabarit = (ICI / "presentation.gabarit.html").read_text(encoding="utf-8")

    def inline(m):
        nom = m.group(1)
        svg = (SCHEMAS / f"{nom}.svg").read_text(encoding="utf-8")
        # on retire la taille fixe : le CSS du diaporama dimensionne par viewBox
        svg = re.sub(r'\swidth="\d+" height="\d+"', "", svg, count=1)
        # ids uniques par schéma (title/desc/marker) pour un document qui en inline plusieurs
        svg = svg.replace('id="t"', f'id="t-{nom}"').replace('id="d"', f'id="d-{nom}"')
        svg = svg.replace('aria-labelledby="t d"', f'aria-labelledby="t-{nom} d-{nom}"')
        svg = svg.replace('id="pointe"', f'id="pointe-{nom}"').replace('url(#pointe)', f'url(#pointe-{nom})')
        return svg

    html = re.sub(r"\{\{svg:([a-z0-9_]+)\}\}", inline, gabarit)
    chiffres = {
        "TOTAL": fmt(DONNEES["total"]),
        "DEPUIS_0809": fmt(sum(v for d, v in DONNEES["per_day"] if d >= "2026-09-08")),
        "QUATORZE_JOURS": fmt(sum(v for d, v in DONNEES["per_day"] if d >= "2026-09-14")),
        "RECORD": fmt(max(v for _, v in DONNEES["per_day"])),
        "RECORD_JOUR": (lambda d: f"{d[8:10]}/{d[5:7]}")(max(DONNEES["per_day"], key=lambda dv: dv[1])[0]),
    }
    for k, v in chiffres.items():
        html = html.replace("{{" + k + "}}", v)
    reste = re.findall(r"\{\{[^}]+\}\}", html)
    if reste:
        raise SystemExit(f"jetons non remplacés : {reste}")
    (DOSSIER / "annexe_technique" / "presentation_technique.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    SCHEMAS.mkdir(exist_ok=True)
    schema_vue_d_ensemble()
    schema_pipeline_page()
    schema_parcours_offre()
    schema_fail_closed()
    schema_exploitation()
    schema_resultats()
    schema_par_jour()
    assembler()
    print("ok :", sorted(p.name for p in SCHEMAS.glob("*.svg")), "→ annexe_technique/presentation_technique.html")
