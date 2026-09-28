#!/usr/bin/env python3
"""Assemble le diaporama de 3 minutes `../presentation.html` (7 diapositives, public non technique).

Python 3 standard uniquement. Entrées :

* `presentation_3min.gabarit.html` — le texte et les pictogrammes des diapositives ;
* `../script_3min.md` — le texte dit, diapositive par diapositive ; il devient les notes de
  l'orateur (touche N). Le compte de mots de chaque en-tête est vérifié ici ;
* `donnees_creations_2026-09-28.json` — les chiffres (méthode : `../chiffres.md`).

    python3 docs/presentation_2026-09-28/outils/generer_3min.py

Rafraîchir les chiffres le jour J (lecture seule sur les deux serveurs de production) :

    python3 outils/compter_creations.py --base <clone de production> > nouvelle.json   # serveur 1
    python3 outils/compter_creations.py --base <clone de production> > ancienne.json   # serveur 2
    python3 outils/generer_3min.py --fusion nouvelle.json ancienne.json \\
        --compte-le-utc "2026-09-28 06:35 UTC" --compte-le "lundi 28/09/2026 à 8 h 35 (heure de Paris)"

La fusion réécrit le fichier de données puis reconstruit le diaporama. Penser à reporter les
nouveaux chiffres dans `../chiffres.md` (et, s'ils changent d'ordre de grandeur, dans le texte dit).
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ICI = pathlib.Path(__file__).resolve().parent
DOSSIER = ICI.parent
GABARIT = ICI / "presentation_3min.gabarit.html"
SCRIPT = DOSSIER / "script_3min.md"
DONNEES = ICI / "donnees_creations_2026-09-28.json"
SORTIE = DOSSIER / "presentation.html"

DEBUT_AUTO = "2026-09-08"   # mise en service de la saisie automatique sur les 2 serveurs
MOTS_MAX = 430              # ≈ 3 min à ~140 mots/min
SECONDES_MAX = 180
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

# Mots interdits à l'écran comme dans le texte dit : le public n'est pas technique.
JARGON = [r"\bfeed\b", r"\bpending\b", r"wp-admin", r"\bVPS\b", r"sitemap", r"fail-closed",
          r"\bmatcher\b", r"pipeline", r"exécuteur", r"\bCDP\b", r"JSONL", r"StepGuard",
          r"\bR\d{2}\b", r"\bAPI\b", r"\bdry-run\b", r"\bscript\b"]

ENCRE, ENCRE_2, TRAIT, GRILLE, BLEU = "#0b0b0b", "#52514e", "#c9c7c0", "#e4e2dc", "#2a78d6"


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def mmss(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def compter_mots(texte: str) -> int:
    return sum(1 for m in texte.split() if re.search(r"[0-9A-Za-zÀ-ÿœŒ]", m))


# ─────────────────────────────────────────────────────────────────────────────────
# Le script dit
# ─────────────────────────────────────────────────────────────────────────────────
ENTETE = re.compile(r"^## (\d+) — (.+?) · (\d+) s · (\d+) mots\s*$")


def lire_script() -> list[dict]:
    sections, cour = [], None
    for ligne in SCRIPT.read_text(encoding="utf-8").splitlines():
        m = ENTETE.match(ligne)
        if m:
            cour = {"n": int(m.group(1)), "titre": m.group(2), "secondes": int(m.group(3)),
                    "mots_annonces": int(m.group(4)), "dit": [], "conseil": []}
            sections.append(cour)
        elif cour is None:
            continue
        elif ligne.startswith("> "):
            cour["dit"].append(ligne[2:].strip())
        elif ligne.strip() and not ligne.startswith("#"):
            cour["conseil"].append(ligne.strip())
    erreurs = []
    for k, s in enumerate(sections, 1):
        s["dit"] = " ".join(s["dit"])
        s["conseil"] = " ".join(s["conseil"])
        s["mots"] = compter_mots(s["dit"])
        if s["n"] != k:
            erreurs.append(f"section {s['n']} : numéro attendu {k}")
        if s["mots"] != s["mots_annonces"]:
            erreurs.append(f"section {s['n']} : l'en-tête annonce {s['mots_annonces']} mots, le texte en a {s['mots']}")
    total_mots = sum(s["mots"] for s in sections)
    total_s = sum(s["secondes"] for s in sections)
    texte = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"\*\*Total : (\d+) mots\*\*", texte)
    if not m or int(m.group(1)) != total_mots:
        erreurs.append(f"la ligne « Total : … mots » doit dire {total_mots}")
    cumul = 0
    for s in sections:
        cumul += s["secondes"]
        rang = re.search(rf"^\| {s['n']} — .*? \| {s['secondes']} s \| {s['mots']} \| {mmss(cumul)} \|$", texte, re.M)
        if not rang:
            erreurs.append(f"tableau : la ligne {s['n']} doit dire {s['secondes']} s, {s['mots']} mots, fin à {mmss(cumul)}")
    if not re.search(rf"^\| \*\*Total\*\* \| \*\*{total_s} s\*\* \| \*\*{total_mots}\*\* \| \|$", texte, re.M):
        erreurs.append(f"tableau : la ligne Total doit dire {total_s} s et {total_mots} mots")
    if total_mots > MOTS_MAX:
        erreurs.append(f"{total_mots} mots > {MOTS_MAX} : trop long pour 3 minutes")
    if total_s > SECONDES_MAX:
        erreurs.append(f"{total_s} s > {SECONDES_MAX} s")
    if erreurs:
        raise SystemExit("script_3min.md :\n  " + "\n  ".join(erreurs))
    return sections


def notes_html(s: dict, fin: int) -> str:
    h = (f"<b>{html.escape(s['titre'], quote=False)} — {s['secondes']} s (fin visée à {mmss(fin)})</b><br>"
         f"{html.escape(s['dit'], quote=False)}")
    if s["conseil"]:
        h += f"<br><i>{html.escape(s['conseil'], quote=False)}</i>"
    return h


# ─────────────────────────────────────────────────────────────────────────────────
# Le graphique : offres saisies par jour, journées complètes depuis la mise en service
# ─────────────────────────────────────────────────────────────────────────────────
def jours_complets(d: dict) -> list[tuple[dt.date, int]]:
    par_jour = collections.Counter({k: v for k, v in d["per_day"]})
    debut = dt.date.fromisoformat(DEBUT_AUTO)
    fin = dt.date.fromisoformat(d["compte_le_utc"][:10]) - dt.timedelta(days=1)  # le jour du comptage est partiel
    out, j = [], debut
    while j <= fin:
        out.append((j, par_jour.get(j.isoformat(), 0)))
        j += dt.timedelta(days=1)
    return out


def jour_long(j: dt.date) -> str:
    return f"{j.day}{'er' if j.day == 1 else ''} {MOIS[j.month - 1]}"


def periode(a: dt.date, b: dt.date) -> str:
    if (a.year, a.month) == (b.year, b.month):
        return f"du {a.day}{'er' if a.day == 1 else ''} au {b.day} {MOIS[b.month - 1]}"
    return f"du {jour_long(a)} au {jour_long(b)}"


def svg_barres(jours: list[tuple[dt.date, int]]) -> str:
    W, H, ml, mr, mt, mb = 1600, 400, 120, 16, 56, 56
    n = len(jours)
    vmax = max(v for _, v in jours)
    ph = H - mt - mb
    base = mt + ph
    pas = (W - ml - mr) / n
    bw = min(26.0, pas * 0.5)
    k_rec = max(range(n), key=lambda k: jours[k][1])
    j0, j1 = jours[0][0], jours[-1][0]
    rec_j, rec_v = jours[k_rec]
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Diagramme en colonnes : offres saisies chaque jour du '
         f'{jour_long(j0)} au {jour_long(j1)} {j1.year} ; record {fmt(rec_v)} le {jour_long(rec_j)}." '
         f'font-family="Inter, Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif">']
    palier = 1000
    for g in range(palier, vmax + 1, palier):
        y = base - ph * g / vmax
        p.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" stroke="{GRILLE}" stroke-width="1"/>')
        p.append(f'<text x="{ml - 14}" y="{y + 10:.1f}" font-size="30" fill="{ENCRE_2}" text-anchor="end">{fmt(g)}</text>')
    for k, (j, v) in enumerate(jours):
        cx = ml + pas * (k + 0.5)
        x0, x1 = cx - bw / 2, cx + bw / 2
        titre = f"{jour_long(j)} : {fmt(v)} offre{'s' if v > 1 else ''} saisie{'s' if v > 1 else ''}" if v else f"{jour_long(j)} : aucune saisie"
        p.append(f'<g><title>{titre}</title>')
        p.append(f'<rect x="{cx - pas / 2:.1f}" y="{mt}" width="{pas:.1f}" height="{ph}" fill="transparent"/>')
        if v:
            h = max(ph * v / vmax, 2.0)
            yt = base - h
            r = min(4.0, h)
            p.append(f'<path d="M{x0:.1f} {base} V{yt + r:.1f} Q{x0:.1f} {yt:.1f} {x0 + r:.1f} {yt:.1f} '
                     f'H{x1 - r:.1f} Q{x1:.1f} {yt:.1f} {x1:.1f} {yt + r:.1f} V{base} Z" fill="{BLEU}"/>')
        p.append('</g>')
        p.append(f'<text x="{cx:.1f}" y="{base + 40}" font-size="30" fill="{ENCRE_2}" text-anchor="middle">{j.day}</text>')
    cx = ml + pas * (k_rec + 0.5)
    p.append(f'<text x="{cx:.1f}" y="{mt - 14}" font-size="34" font-weight="700" fill="{ENCRE}" text-anchor="middle">{fmt(rec_v)}</text>')
    p.append(f'<line x1="{ml}" y1="{base}" x2="{W - mr}" y2="{base}" stroke="{TRAIT}" stroke-width="2"/>')
    p.append("</svg>")
    return "\n".join(p)


# ─────────────────────────────────────────────────────────────────────────────────
# Fusion des comptages des deux serveurs
# ─────────────────────────────────────────────────────────────────────────────────
def fusion(chemins: list[str], compte_le_utc: str, compte_le: str) -> None:
    sorties = []
    for c in chemins:
        lignes = [l for l in pathlib.Path(c).read_text(encoding="utf-8").splitlines() if l.strip().startswith("{")]
        sorties.append(json.loads(lignes[-1]))
    pm, pj = collections.Counter(), collections.Counter()
    for s in sorties:
        for k, v in s["per_merchant"]:
            pm[k] += v
        for k, v in s["per_day"]:
            pj[k] += v
    ancien = json.loads(DONNEES.read_text(encoding="utf-8")) if DONNEES.exists() else {}
    d = {
        "compte_le_utc": compte_le_utc,
        "compte_le": compte_le,
        "methode": ancien.get("methode", "outils/compter_creations.py sur les 2 serveurs, sorties additionnées"),
        "total": sum(pm.values()),
        "serveur_1": sorties[0]["total"],
        "serveur_2": sorties[1]["total"] if len(sorties) > 1 else 0,
        "marchands_couverts": ancien.get("marchands_couverts", 21),
        "tests_automatiques": ancien.get("tests_automatiques", 0),
        "per_merchant": pm.most_common(),
        "per_day": sorted(pj.items()),
    }
    DONNEES.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"données : {fmt(d['total'])} offres ({compte_le_utc}) → {DONNEES.name}")


# ─────────────────────────────────────────────────────────────────────────────────
# Assemblage et contrôles
# ─────────────────────────────────────────────────────────────────────────────────
def texte_visible(doc: str) -> str:
    doc = re.sub(r"<(script|style)\b.*?</\1>", " ", doc, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", doc))


def controler(doc: str) -> dict:
    erreurs = []
    svgs = re.findall(r"<svg\b.*?</svg>", doc, flags=re.S)
    for k, s in enumerate(svgs, 1):
        try:
            ET.fromstring(s)
        except ET.ParseError as e:
            erreurs.append(f"SVG n°{k} mal formé : {e}")
    nb = len(re.findall(r'<section class="slide\b', doc))
    if nb > 7:
        erreurs.append(f"{nb} diapositives > 7")
    for attr in re.findall(r'\b(?:src|href)\s*=\s*"([^"]*)"', doc):
        erreurs.append(f"lien ou ressource : {attr}")
    if re.search(r"https?://|//cdn|@import|url\(\s*['\"]?http", doc):
        erreurs.append("adresse réseau dans le fichier")
    vis = texte_visible(doc)
    for motif in JARGON:
        for m in re.finditer(motif, vis, flags=re.I if motif.islower() else 0):
            erreurs.append(f"jargon « {m.group(0)} » : …{vis[max(0, m.start() - 40):m.end() + 40].strip()}…")
    if erreurs:
        raise SystemExit("presentation.html :\n  " + "\n  ".join(erreurs))
    return {"diapositives": nb, "svg": len(svgs)}


def assembler() -> None:
    d = json.loads(DONNEES.read_text(encoding="utf-8"))
    sections = lire_script()
    jours = jours_complets(d)
    rec_j, rec_v = max(jours, key=lambda jv: jv[1])
    doc = GABARIT.read_text(encoding="utf-8")
    jetons = {
        "TOTAL": fmt(d["total"]),
        "RECORD": fmt(rec_v),
        "MARCHANDS": str(d["marchands_couverts"]),
        "COMPTE_LE": html.escape(d["compte_le"], quote=False),
        "BARRES_TITRE": f"Offres saisies chaque jour, {periode(jours[0][0], jours[-1][0])}",
        "svg:barres": svg_barres(jours),
    }
    cumul = 0
    for s in sections:
        cumul += s["secondes"]
        jetons[f"notes:{s['n']}"] = notes_html(s, cumul)
        jetons[f"secondes:{s['n']}"] = str(s["secondes"])
    for k, v in jetons.items():
        doc = doc.replace("{{" + k + "}}", v)
    reste = re.findall(r"\{\{[^}]+\}\}", doc)
    if reste:
        raise SystemExit(f"jetons non remplacés : {reste}")
    info = controler(doc)
    if info["diapositives"] != len(sections):
        raise SystemExit(f"{info['diapositives']} diapositives mais {len(sections)} sections dans le script")
    SORTIE.write_text(doc, encoding="utf-8")
    total_mots = sum(s["mots"] for s in sections)
    print(f"ok : {SORTIE.name} — {info['diapositives']} diapositives, {info['svg']} SVG bien formés, "
          f"script {total_mots} mots / {sum(s['secondes'] for s in sections)} s "
          f"({', '.join(str(s['mots']) for s in sections)}) ; {fmt(d['total'])} offres au {d['compte_le_utc']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--fusion" in args:
        i = args.index("--fusion")
        chemins = [a for a in args[i + 1:i + 3] if not a.startswith("--")]
        utc = args[args.index("--compte-le-utc") + 1] if "--compte-le-utc" in args else None
        loc = args[args.index("--compte-le") + 1] if "--compte-le" in args else None
        if len(chemins) != 2 or not utc or not loc:
            raise SystemExit("usage : --fusion serveur1.json serveur2.json --compte-le-utc \"AAAA-MM-JJ HH:MM UTC\" --compte-le \"texte\"")
        fusion(chemins, utc, loc)
    assembler()
