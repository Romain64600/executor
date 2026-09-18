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
import re
from pathlib import Path
from typing import Any

from src import sort_sql_promoted
from src.aks_lists import LISTS, PENDING_LIST_ID
from src.sort_sql_rules import FLAGGED, RETIRED, RULES, SEED_PROPOSALS


class IncompleteScan(RuntimeError):
    """Scan inexploitable : on ne prétend pas l'avoir mesuré."""


def _coverage(plan: dict[str, Any]) -> dict[str, Any]:
    """La couverture du scan, en FAIL-CLOSED : pas de bloc = tronqué.

    AUDIT DU 2026-09-18. `sort_sql_payload` chargeait `sort_plan.json` sans jamais lire son
    bloc `coverage` : un scan qui n'avait lu que 60 pages (le défaut de `08_sort_plan.py`)
    sur les ~639 du feed était rendu « mesuré », et les compteurs `collateral` / `conflict`
    — la SEULE garde de cette voie, puisque Romain exécute les requêtes lui-même et qu'il
    n'y a pas de preuve après coup — étaient calculés sur cet échantillon pendant que
    l'`UPDATE` collé dans phpMyAdmin balaie, lui, toute la table. Un collatéral nul par
    ABSENCE DE DONNÉES se présentait comme un collatéral nul par SÛRETÉ.

    La clef de décision est `truncated` et elle seule : `partial` est câblé à `True` en dur
    (08_sort_plan.py:150) et ne discrimine rien. Un plan sans bloc `coverage` (ancien, écrit
    à la main, autre producteur) est traité comme tronqué."""

    cov = plan.get("coverage")
    if not isinstance(cov, dict):
        return {"truncated": True, "pages_fetched": None, "feed_last_page": None,
                "why": "le scan ne déclare aucune couverture"}
    out = {"truncated": bool(cov.get("truncated", True)),
           "pages_fetched": cov.get("pages_fetched"),
           "feed_last_page": cov.get("feed_last_page")}
    if out["truncated"]:
        out["why"] = (f"scan partiel — {out['pages_fetched']} page(s) lues sur "
                      f"{out['feed_last_page']}")
    return out


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


# La mesure du LIKE vit dans `src/sort_sql_promoted.py`, partagée avec le stage 13 : le
# correctif du 2026-09-18 n'avait été posé qu'ici, et le script CLI sous-comptait encore
# (audit complet du même soir). Une seule implémentation, un seul endroit où se tromper.
_like = sort_sql_promoted.like


def _classify(run_dir: Path) -> tuple[dict[str, str], dict[str, dict], dict[str, Any]]:
    """url -> destination selon NOTRE routeur ; url -> ligne du feed ; et le plan lu."""

    plan = json.loads((run_dir / "sort_plan.json").read_text(encoding="utf-8"))
    try:
        raw = json.loads((run_dir / "offers.json").read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("offers", [])
    except (OSError, ValueError) as exc:
        # Sans offers.json, les CANDIDATS À LA CRÉATION disparaissent de la classification :
        # le compteur « collatéral » deviendrait nul par absence de données, pas par sûreté,
        # et une promotion passerait sans le seul contrôle qui la protège. On refuse de
        # mesurer plutôt que de mesurer à vide (audit de Romain, 2026-09-18).
        raise IncompleteScan(f"offers.json illisible dans {run_dir.name} : {exc}") from exc
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
    return dest, by_url, plan


# Un motif proposé ne vient QUE du vocabulaire qui a fait décider notre routeur — jamais d'un
# mot quelconque de l'URL. La première version minait tous les jetons « purs » de l'échantillon
# et proposait %modern-warfare% vers la Blacklist : des noms de jeux, purs sur 10 % du feed et
# catastrophiques sur 100 %.
_REASON_RE = re.compile(r"^(?:forbidden region|skip category)\s*:\s*([A-Z0-9 &+/'-]{3,40})")


def _vocab_term(reason: str) -> str | None:
    m = _REASON_RE.match((reason or "").strip())
    if not m:
        return None
    return (m.group(1).strip().rstrip("(,").strip()) or None


def _mine(plan: dict, dest: dict[str, str], by_url: dict[str, dict],
          known: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """Motifs candidats, MESURÉS, qui ne sont pas déjà dans la liste."""

    # Les graines d'analyse d'abord : elles viennent d'une lecture du feed, pas du mineur.
    seen: set[tuple[str, str]] = {(p, t) for p, t in SEED_PROPOSALS}
    for list_id, group in (plan.get("by_list") or {}).items():
        for row in group.get("offers", []):
            term = _vocab_term(row.get("reason", ""))
            if term is None:
                continue
            for word in {term.lower().replace(" ", "-"), term.lower().replace(" ", "")}:
                pattern = f"%{word}%"
                if len(word) >= 4 and sort_sql_promoted.SAFE_PATTERN.match(pattern):
                    seen.add((pattern, str(list_id)))

    seeds = {(p, t) for p, t in SEED_PROPOSALS}
    out = []
    for pattern, target in sorted(seen - known):
        # Un motif RETIRÉ ne se repropose pas : le retrait porte sur le motif, pas sur le
        # couple (motif, liste), donc il ne peut pas vivre dans `known` (hygiène, audit
        # du 2026-09-18 — la promotion est de toute façon refusée côté serveur).
        if pattern in RETIRED:
            continue
        m = _measure(pattern, target, dest, by_url)
        # Une proposition n'est offerte que si elle ne vise AUCUN vrai jeu et n'entre en
        # conflit avec aucune autre liste. Le reste n'est pas une proposition, c'est un piège.
        if m["hits"] < 2 or m["collateral"] or m["conflict"]:
            continue
        # Un motif MINÉ vient d'une ligne déjà routée : au moins une ligne doit confirmer la
        # destination, sinon le mot ne prouve rien. Une GRAINE d'analyse, elle, vise justement
        # des lignes que le routeur laisse en attente faute de cible — « agree » y vaut zéro
        # par construction, et l'exiger les rejetait toutes. C'est ce que Romain demande :
        # sortir du pending ce qui n'a aucune raison d'y rester.
        if (pattern, target) in seeds or m["agree"]:
            m["source"] = "analyse" if (pattern, target) in seeds else "vocabulaire"
            out.append(m)
    return out


def _conflicted_seeds(dest: dict[str, str], by_url: dict[str, dict],
                      known: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """Graines écartées pour CONFLIT — montrées quand même, pour arbitrage.

    Les taire serait pire que les proposer : ce sont des motifs à fort volume dont notre
    routeur enverrait une partie ailleurs. Ce n'est pas une erreur du motif, c'est un
    désaccord, et il se tranche à la main."""

    out = []
    for pattern, target in SEED_PROPOSALS:
        if (pattern, target) in known:
            continue
        m = _measure(pattern, target, dest, by_url)
        if m["hits"] >= 2 and not m["collateral"] and m["conflict"]:
            m["source"] = "analyse"
            out.append(m)
    out.sort(key=lambda m: -m["hits"])
    return out


def _measure(pattern: str, target: str, dest: dict[str, str],
             by_url: dict[str, dict]) -> dict[str, Any]:
    hits = [u for u in dest if _like(pattern, u)]
    tally: dict[str, int] = {}
    for u in hits:
        tally[dest[u]] = tally.get(dest[u], 0) + 1
    collateral = [by_url[u].get("name", "")[:80] for u in hits if dest[u] == "__candidat__"]
    return {
        "sql": _statement(pattern, target), "pattern": pattern, "target": str(target),
        "measured": True, "hits": len(hits), "agree": tally.get(str(target), 0),
        "conflict": sum(n for k, n in tally.items()
                        if k not in (str(target), "__candidat__", "__garder__")),
        "keep": tally.get("__garder__", 0), "collateral": len(collateral),
        "collateral_sample": collateral[:3], "flag": FLAGGED.get(pattern),
    }


def _statement(pattern: str, target: str) -> str:
    return (f"UPDATE `aksfeeds_offer` SET `listId`={int(target)} "
            f"WHERE `url` LIKE '{pattern}' AND `listId`=9;")


def sort_sql_payload(runs_dir: Path, wanted: str = "",
                     repo_root: Path | None = None) -> dict[str, Any]:
    run_dir = _latest_sort_run(Path(runs_dir), wanted)
    rules: list[dict[str, Any]] = []
    if run_dir is None:
        for pattern, target in RULES:
            rules.append({"sql": _statement(pattern, target), "pattern": pattern,
                          "target": target, "measured": False,
                          "flag": FLAGGED.get(pattern)})
        return {"run_id": None, "measured": False, "rules": rules, "proposals": [],
                "lists": [{"id": l["id"], "label": l["label"]} for l in LISTS],
                "pending_list": PENDING_LIST_ID,
                "retired": [{"pattern": p, "why": w} for p, w in RETIRED.items()],
                "note": "aucun scan de tri — les requêtes sont rendues sans mesure"}

    try:
        dest, by_url, plan = _classify(run_dir)
    except IncompleteScan as exc:
        for pattern, target in RULES:
            rules.append({"sql": _statement(pattern, target), "pattern": pattern,
                          "target": target, "measured": False, "flag": FLAGGED.get(pattern)})
        return {"run_id": run_dir.name, "measured": False, "rules": rules, "proposals": [],
                "conflicted": [],
                "lists": [{"id": l["id"], "label": l["label"]} for l in LISTS],
                "pending_list": PENDING_LIST_ID,
                "retired": [{"pattern": p, "why": w} for p, w in RETIRED.items()],
                "note": f"scan inexploitable, rien n'est mesuré : {exc}"}
    promoted = [r for r in (sort_sql_promoted.load(repo_root) if repo_root else [])
                if not r.get("dismissed")]
    for pattern, target in RULES:
        rules.append(_measure(pattern, target, dest, by_url))
    for entry in promoted:
        m = _measure(entry["pattern"], entry["target"], dest, by_url)
        m["promoted"] = {k: entry.get(k) for k in ("promoted_at", "promoted_by", "source_run")}
        rules.append(m)
    coverage = _coverage(plan)
    if coverage["truncated"]:
        # Une mesure faite sur un échantillon reste AFFICHÉE — Romain a besoin du texte SQL —
        # mais elle est marquée, et le bouton « sans désaccord » l'exclut : un collatéral nul
        # par absence de données n'est pas un collatéral nul.
        for m in rules:
            if m.get("measured"):
                m["truncated"] = True
    # « connu » = déjà dans la liste, déjà promu, ou explicitement écarté / promu sous une
    # forme éditée. Sans ce dernier point, un motif resserré laisse son original revenir.
    known = ({(p, t) for p, t in RULES}
             | {(e["pattern"], e["target"]) for e in promoted}
             | (sort_sql_promoted.dismissed(repo_root) if repo_root else set()))
    # Une PROPOSITION est une règle PERMANENTE déduite d'un échantillon : sur un scan tronqué
    # on la refuse franchement, on ne se contente pas de l'annoter. C'est exactement le piège
    # « purs sur 10 % du feed, catastrophiques sur 100 % » que ce module cite trois fois.
    proposals = [] if coverage["truncated"] else _mine(plan, dest, by_url, known)
    return {
        "run_id": run_dir.name,
        "measured": True,
        "coverage": coverage,
        "truncated": coverage["truncated"],
        "offers": len(dest),
        "rules": rules,
        # Le catalogue des listes, pour que « 21 » s'affiche « 21 — Gift cards » et qu'on
        # puisse le consulter en entier sans quitter la page (Romain 2026-09-18).
        "lists": [{"id": l["id"], "label": l["label"]} for l in LISTS],
        "pending_list": PENDING_LIST_ID,
        "proposals": proposals,
        "conflicted": [] if coverage["truncated"] else _conflicted_seeds(dest, by_url, known),
        # Une règle retirée reste VISIBLE, avec sa raison : sinon le retrait est invisible et
        # quelqu'un la recolle depuis une vieille liste.
        "retired": [{"pattern": p, "why": w} for p, w in RETIRED.items()],
        "all_sql": "\n".join(r["sql"] for r in rules),
    }


def measure_pattern(runs_dir: Path, pattern: str, target: str,
                    wanted: str = "") -> dict[str, Any]:
    """Mesure UN motif — celui que Romain vient d'éditer — contre le scan courant.

    Romain 2026-09-18 : « faudrait qu'on puisse éditer avant de promouvoir, dans le cas où on
    a besoin d'hésiter, rajouter un tiret ». Un motif édité rend la mesure affichée périmée :
    on la refait, sinon on promeut sur la foi d'un chiffre qui parlait d'un autre motif.
    """

    run_dir = _latest_sort_run(Path(runs_dir), wanted)
    if run_dir is None:
        return {"measured": False, "pattern": pattern, "target": str(target),
                "note": "aucun scan de tri — impossible de mesurer"}
    dest, by_url, plan = _classify(run_dir)
    m = _measure(pattern, str(target), dest, by_url)
    m["run_id"] = run_dir.name
    m["coverage"] = _coverage(plan)
    m["truncated"] = m["coverage"]["truncated"]
    return m
