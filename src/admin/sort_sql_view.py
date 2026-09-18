"""Les requêtes de tri, mesurées, prêtes à copier dans phpMyAdmin (2026-09-18).

Romain : « je veux que la voie SQL remplace l'exécution d'un déplacement, tu me donneras les
requêtes dans l'admin en liste et [elles seront] prêtes à copier coller, les requêtes seront
collées à la main dans phpMyAdmin par mes soins pour les exécuter ».

Ce module **ne touche aucune base et n'importe aucun driver**. Il lit un scan de tri déjà
produit, confronte chaque règle de ``src/sort_sql_rules.py`` aux lignes réelles, et rend du
TEXTE. L'exécution reste entièrement manuelle.

Ce que la mesure apporte, et pourquoi elle n'est pas décorative : un ``UPDATE`` collé à la main
n'a ni garde fail-closed, ni preuve, ni retour arrière — contrairement au déplacement par le
navigateur qu'il remplace, dont le succès était la disparition prouvée de la ligne. On ne peut
donc plus vérifier APRÈS ; on vérifie AVANT. Chaque règle porte :

* ``hits``       — lignes du scan dont l'URL matche ;
* ``agree``      — celles que notre routeur enverrait sur la MÊME liste ;
* ``conflict``   — celles qu'il enverrait AILLEURS ;
* ``keep``       — celles qu'il laisse volontairement en attente ;
* ``collateral`` — celles qu'il tient pour de vrais jeux à créer, avec un échantillon nommé.

``collateral`` n'est pas un verdict : c'est un désaccord entre la règle de Romain et notre
routeur, affiché pour qu'il tranche. ``flag`` porte en plus une contradiction connue avec une
décision écrite (voir ``FLAGGED``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.sort_sql_rules import FLAGGED, RULES


def _latest_sort_run(runs_dir: Path, wanted: str = "") -> Path | None:
    if wanted:
        d = runs_dir / wanted
        return d if (d / "sort_plan.json").exists() else None
    best, best_m = None, -1.0
    for d in runs_dir.glob("*"):
        p = d / "sort_plan.json"
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > best_m:
            best, best_m = d, m
    return best


def _slug(url: str) -> str:
    u = (url or "").lower()
    for cut in ("?", "#"):
        if cut in u:
            u = u.split(cut, 1)[0]
    return u


def _classify(run_dir: Path) -> tuple[dict[str, str], dict[str, dict]]:
    """url -> destination selon NOTRE routeur ; url -> ligne du feed."""

    plan = json.loads((run_dir / "sort_plan.json").read_text(encoding="utf-8"))
    try:
        raw = json.loads((run_dir / "offers.json").read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("offers", [])
    except (OSError, ValueError):
        rows = []
    by_url = {str(r.get("url") or ""): r for r in rows if r.get("url")}
    dest = {u: "__candidat__" for u in by_url}
    for r in plan.get("unrouted", []):
        u = str(r.get("url") or "")
        if u:
            dest[u] = "__garder__"
            by_url.setdefault(u, r)
    for list_id, group in (plan.get("by_list") or {}).items():
        for r in group.get("offers", []):
            u = str(r.get("url") or "")
            if u:
                dest[u] = str(list_id)
                by_url.setdefault(u, r)
    return dest, by_url


def _statement(pattern: str, target: str) -> str:
    return (f"UPDATE `aksfeeds_offer` SET `listId`={int(target)} "
            f"WHERE `url` LIKE '{pattern}' AND `listId`=9;")


def sort_sql_payload(runs_dir: Path, wanted: str = "") -> dict[str, Any]:
    run_dir = _latest_sort_run(Path(runs_dir), wanted)
    rules: list[dict[str, Any]] = []
    if run_dir is None:
        for pattern, target in RULES:
            rules.append({"sql": _statement(pattern, target), "pattern": pattern,
                          "target": target, "measured": False,
                          "flag": FLAGGED.get(pattern)})
        return {"run_id": None, "measured": False, "rules": rules,
                "note": "aucun scan de tri — les requêtes sont rendues sans mesure"}

    dest, by_url = _classify(run_dir)
    for pattern, target in RULES:
        needle = pattern.strip("%")
        hits = [u for u in dest if needle in _slug(u)]
        tally: dict[str, int] = {}
        for u in hits:
            tally[dest[u]] = tally.get(dest[u], 0) + 1
        collateral = [by_url[u].get("name", "")[:80] for u in hits
                      if dest[u] == "__candidat__"]
        rules.append({
            "sql": _statement(pattern, target),
            "pattern": pattern,
            "target": target,
            "measured": True,
            "hits": len(hits),
            "agree": tally.get(str(target), 0),
            "conflict": sum(n for k, n in tally.items()
                            if k not in (str(target), "__candidat__", "__garder__")),
            "keep": tally.get("__garder__", 0),
            "collateral": len(collateral),
            "collateral_sample": collateral[:3],
            "flag": FLAGGED.get(pattern),
        })
    return {
        "run_id": run_dir.name,
        "measured": True,
        "offers": len(dest),
        "rules": rules,
        "all_sql": "\n".join(r["sql"] for r in rules),
    }
