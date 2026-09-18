"""Les règles de tri PROMUES depuis les propositions mesurées (2026-09-18).

Romain : « go pour les propositions avec promotion manuelle ». Le mineur de motifs propose,
mesuré, à partir du vocabulaire qui fait décider notre routeur ; c'est Romain qui promeut, et
une règle promue rejoint la liste et y reste — d'un run à l'autre elle est là, et de nouvelles
propositions s'ajoutent en dessous.

**Pourquoi la promotion est manuelle.** La première version du mineur proposait très
sérieusement ``%modern-warfare%`` vers la Blacklist, plus ``%agatha-christie%`` et
``%marvel-tokon%`` : des mots « purs » sur un échantillon de 10 %, mais des NOMS DE JEUX. Une
règle qui s'ajouterait toute seule et que Romain lancerait chaque jour rendrait une erreur de
ce genre permanente et silencieuse. Le mineur propose donc, il ne décide pas.

Le fichier de données est du JSON, pas du code : il se relit, se corrige à la main et se
versionne. Il vit sous ``data/`` et non ``state/``, justement pour être commité — sans quoi les
deux serveurs divergeraient, chacun avec ses promotions.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Le même vocabulaire restreint que le générateur : un motif est du texte injecté dans une
# chaîne SQL, on n'accepte rien d'autre.
SAFE_PATTERN = re.compile(r"^%[A-Za-z0-9._/+-]+%$")


# LA mesure d'un motif — une seule implémentation, partagée par la vue console et par le
# stage 13. Elle doit reproduire le ``LIKE`` de MySQL, sinon elle ment sur la SEULE garde de
# la voie SQL : Romain exécute les requêtes lui-même, il n'y a pas de preuve après coup.
# Deux écarts trouvés le 2026-09-18 :
#   * ``_`` est un JOKER en SQL. ``%digital_extras%`` sélectionne « digital-extras », alors
#     que la recherche littérale annonçait 0 ligne — un compteur « collatéral » nul, et des
#     offres déplacées quand même.
#   * la mesure retirait les paramètres d'URL, que la colonne `url` contient. Un motif qui
#     vise un paramètre était donc compté à zéro.
# L'audit complet du même soir a montré que le correctif n'avait été posé QUE sur la vue :
# le stage 13, celui que le README documente pour auditer la liste quotidienne AVANT de la
# lancer, sous-comptait toujours. D'où ce module commun — et non un import depuis la vue
# admin, qu'un script CLI n'a pas à tirer derrière lui.
@lru_cache(maxsize=512)
def like_re(pattern: str) -> "re.Pattern[str]":
    out = []
    for ch in pattern or "":
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)


def like(pattern: str, url: str) -> bool:
    """``url LIKE pattern`` comme MySQL le ferait, sur l'URL ENTIÈRE, sans casse."""

    return bool(like_re(pattern).match(url or ""))


def _path(repo_root: Path | str) -> Path:
    return Path(repo_root) / "data" / "sort_sql_promoted.json"


def load(repo_root: Path | str) -> list[dict[str, Any]]:
    """Les promotions, ou une liste vide. Un fichier illisible ne casse pas la page."""

    try:
        raw = json.loads(_path(repo_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        pattern, target = str(r.get("pattern", "")), str(r.get("target", ""))
        if SAFE_PATTERN.match(pattern) and target.isdigit():
            out.append({**r, "pattern": pattern, "target": target})
    return out


def dismissed(repo_root: Path | str) -> set[tuple[str, str]]:
    """Les propositions à ne plus reproposer : celles écartées, et l'ORIGINE d'une promotion.

    Romain 2026-09-18 : « une fois après avoir modifié, mesuré et promu, on devrait plus avoir
    l'entrée proposée ». Quand il resserre ``%puzzle%`` en ``%-puzzles-%`` et promeut, c'est
    le motif ÉDITÉ qui entre dans la liste ; sans mémoire de l'origine, ``%puzzle%`` revenait
    à chaque run comme si rien ne s'était passé. On retient donc d'où vient la promotion.
    """

    out: set[tuple[str, str]] = set()
    for r in load(repo_root):
        if r.get("dismissed"):
            out.add((r["pattern"], r["target"]))
        origin = r.get("origin")
        if isinstance(origin, dict) and origin.get("pattern"):
            out.add((str(origin["pattern"]), str(origin.get("target", r["target"]))))
    return out


def dismiss(repo_root: Path | str, *, pattern: str, target: str, by: str) -> dict[str, Any]:
    """Écarte une proposition sans la promouvoir : elle ne sera plus reproposée."""

    if not SAFE_PATTERN.match((pattern or "").strip()):
        raise ValueError(f"motif refusé : {pattern!r}")
    entry = {
        "pattern": pattern.strip(), "target": str(target), "dismissed": True,
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "promoted_by": str(by or "?"),
    }
    rows = [r for r in load(repo_root)
            if not (r["pattern"] == entry["pattern"] and r["target"] == entry["target"])]
    rows.append(entry)
    path = _path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return entry


def promote(repo_root: Path | str, *, pattern: str, target: str, by: str,
            run_id: str = "", hits: int | None = None,
            origin: dict[str, str] | None = None) -> dict[str, Any]:
    """Ajoute une règle promue. Refuse un motif malformé, une liste inconnue, un doublon.

    Le refus du DOUBLON compte : deux fois le même motif, c'est une requête qui ne fera rien
    la seconde fois (la ligne a quitté ``listId=9``) mais qui allonge la liste que Romain
    relit avant de coller. On garde la liste courte et vraie.
    """

    from src.aks_lists import LISTS
    from src.sort_sql_rules import RULES

    pattern = (pattern or "").strip()
    target = str(target or "").strip()
    if not SAFE_PATTERN.match(pattern):
        raise ValueError(f"motif refusé : {pattern!r} — attendu %texte% sans espace ni quote")
    known = {l["id"] for l in LISTS}
    if target not in known:
        raise ValueError(f"liste inconnue : {target!r}")
    existing = {(p, t) for p, t in RULES} | {
        (r["pattern"], r["target"]) for r in load(repo_root) if not r.get("dismissed")}
    if (pattern, target) in existing:
        raise ValueError(f"{pattern} → {target} est déjà dans la liste")

    entry = {
        "pattern": pattern,
        "target": target,
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "promoted_by": str(by or "?"),
        "source_run": str(run_id or ""),
        "hits_when_promoted": hits,
        # D'où vient cette promotion : la proposition telle qu'elle était AVANT édition.
        # Sans ça, un motif resserré laisse son original revenir à chaque run.
        "origin": ({"pattern": str(origin.get("pattern", "")),
                    "target": str(origin.get("target", target))}
                   if isinstance(origin, dict) and origin.get("pattern") else None),
    }
    rows = load(repo_root)
    rows.append(entry)
    path = _path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)          # atomique : jamais de liste à moitié écrite
    return entry


def demote(repo_root: Path | str, *, pattern: str, target: str) -> bool:
    """Retire une promotion. Les règles d'origine de Romain, elles, ne se retirent pas d'ici."""

    rows = load(repo_root)
    keep = [r for r in rows if not (r["pattern"] == pattern and r["target"] == str(target))]
    if len(keep) == len(rows):
        return False
    path = _path(repo_root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return True
