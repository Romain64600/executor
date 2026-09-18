#!/usr/bin/env python3
"""Stage 13 — SQL de tri par listes, à copier-coller dans phpMyAdmin (2026-09-17).

Romain : « j'aimerais bien que tu me génères des requêtes SQL […] sur l'admin on aura un
espace où on pourra les copier-coller et nous aller les exécuter personnellement ». Ses
exemples filtrent sur l'URL :

    UPDATE `aksfeeds_offer` SET `listId`=8 WHERE `url` LIKE '%-furniture-pack%' AND `listId`=9;

**Ce script ne touche à AUCUNE base.** Il lit un scan de tri déjà produit et ÉCRIT DU TEXTE.
L'exécution reste entièrement manuelle, dans phpMyAdmin, par Romain.

Pourquoi c'est prudent malgré tout. Un `UPDATE` lancé à la main n'a ni garde fail-closed, ni
preuve de disparition, ni retour arrière : une fois parti, il est parti. Donc chaque motif est
MESURÉ sur le feed réel avant d'être proposé, et le compte est imprimé à côté de la requête :

* ``vise``       — lignes dont l'URL matche le motif ;
* ``d'accord``   — parmi elles, celles que notre routeur enverrait sur CETTE liste ;
* ``conflit``    — celles qu'il enverrait sur une AUTRE liste ;
* ``à garder``   — celles qu'il laisse volontairement en pending (décision opérateur) ;
* ``collatéral`` — celles qu'il tient pour de VRAIS JEUX à créer. Une seule suffit à écarter
                   le motif : ce serait blacklister un jeu vendable.

Un motif n'est proposé que si ``conflit`` et ``collatéral`` valent zéro. Les autres sont
imprimés dans une section « écartés » avec la raison, parce qu'un motif rejeté est une
information utile, pas un silence.

Deux modes :

    python3 scripts/13_sort_sql.py --run-id <scan de tri>                  # propose
    python3 scripts/13_sort_sql.py --run-id <scan> --check "%puzzle%:8"    # audite un motif

Le second sert à passer au crible un motif écrit à la main (ceux de Romain, par exemple)
AVANT de le lancer : il imprime le même décompte et un échantillon de titres visés.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import sort_sql_promoted  # noqa: E402 — après sys.path

TABLE = "aksfeeds_offer"
PENDING_LIST = 9          # la clause `AND listId=9` de Romain : on ne touche que le pending
MIN_HITS = 2              # un motif vu une seule fois ne se généralise pas
CANDIDATE = "__candidat__"
KEEP = "__garder__"

# Un motif est du texte injecté dans une chaîne SQL. On n'accepte que ce vocabulaire.
# Le motif partagé (`src/sort_sql_promoted.py`) est le bon : il EXIGE les `%` encadrants,
# là où la copie locale s'en passait. Une copie plus lâche que l'original, c'est exactement
# le schéma qui a produit le bug de mesure ci-dessous (audit du 2026-09-18).
SAFE_PATTERN = sort_sql_promoted.SAFE_PATTERN


def _classify(run_dir: Path) -> tuple[dict[str, str], dict[str, dict]]:
    """url → destination selon NOTRE routeur, et url → ligne du feed."""

    plan = json.loads((run_dir / "sort_plan.json").read_text(encoding="utf-8"))
    rows = json.loads((run_dir / "offers.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("offers", [])

    by_url: dict[str, dict] = {}
    for r in rows:
        u = str(r.get("url") or "")
        if u:
            by_url[u] = r

    dest: dict[str, str] = {u: CANDIDATE for u in by_url}
    for r in plan.get("unrouted", []):
        u = str(r.get("url") or "")
        if u:
            dest[u] = KEEP
            by_url.setdefault(u, r)
    for list_id, group in (plan.get("by_list") or {}).items():
        for r in group.get("offers", []):
            u = str(r.get("url") or "")
            if u:
                dest[u] = str(list_id)
                by_url.setdefault(u, r)
    return dest, by_url


def measure(pattern: str, target: str, dest: dict[str, str],
            by_url: dict[str, dict]) -> dict:
    """Ce qu'un motif LIKE toucherait vraiment, de l'avis de NOTRE routeur.

    AUDIT DU 2026-09-18. Cette fonction cherchait une SOUS-CHAÎNE LITTÉRALE dans l'URL
    amputée de ses paramètres. Le correctif « ``_`` est un joker en SQL, et la colonne
    `url` contient les paramètres » n'avait été posé que sur la vue console : ce script —
    celui que le README documente pour auditer la liste quotidienne AVANT de la coller —
    sous-comptait toujours, dans le sens dangereux. ``--check "%digital_extras%:8"``
    répondait « 0 ligne, ne se généralise pas » pendant que l'``UPDATE`` en déplaçait deux.
    La mesure est désormais celle de `src/sort_sql_promoted.py`, partagée avec la vue."""

    hits = [u for u in dest if sort_sql_promoted.like(pattern, u)]
    tally = Counter(dest[u] for u in hits)
    return {
        "pattern": pattern,
        "target": str(target),
        "hits": len(hits),
        "agree": tally.get(str(target), 0),
        "conflict": sum(n for k, n in tally.items()
                        if k not in (str(target), CANDIDATE, KEEP)),
        "keep": tally.get(KEEP, 0),
        "collateral": tally.get(CANDIDATE, 0),
        "sample": [by_url[u].get("name", "")[:70] for u in hits[:4]],
        "sample_collateral": [by_url[u].get("name", "")[:70] for u in hits
                              if dest[u] == CANDIDATE][:4],
    }


def verdict(m: dict) -> str | None:
    """None when the pattern is safe to propose, else why it is refused."""

    if m["hits"] < MIN_HITS:
        return f"{m['hits']} ligne(s) seulement — ne se généralise pas"
    if m["collateral"]:
        return (f"{m['collateral']} vrai(s) jeu(x) visé(s) — les blacklister serait une perte "
                f"sèche (ex. {'; '.join(m['sample_collateral'][:2])})")
    if m["conflict"]:
        return f"{m['conflict']} ligne(s) que le routeur envoie sur une AUTRE liste"
    if not m["agree"]:
        return "aucune ligne que le routeur enverrait sur cette liste"
    return None


# Le VOCABULAIRE seul est candidat, jamais un mot quelconque de l'URL. Première version de ce
# script : je minais tous les jetons de l'URL « purs » dans l'échantillon, et elle proposait
# `%modern-warfare%` → Blacklist, `%agatha-christie%`, `%marvel-tokon%`… Purs sur 10 % du feed,
# catastrophiques sur 100 % : ce sont des NOMS DE JEUX, pas des catégories. Un motif n'est donc
# dérivé que du motif de routage de la ligne — « forbidden region: X » ou « skip category: Y »
# — c'est-à-dire du mot qui a fait décider notre routeur.
REASON_RE = re.compile(r"^(?:forbidden region|skip category)\s*:\s*([A-Z0-9 &+/'-]{3,40})")


def _vocab_term(reason: str) -> str | None:
    m = REASON_RE.match((reason or "").strip())
    if not m:
        return None
    term = m.group(1).strip().rstrip("(,").strip()
    return term or None


def propose(dest: dict[str, str], by_url: dict[str, dict],
            plan: dict) -> list[dict]:
    """Patterns drawn from the ROUTING VOCABULARY, then measured on the feed."""

    seen: dict[tuple[str, str], None] = {}
    for list_id, group in (plan.get("by_list") or {}).items():
        for row in group.get("offers", []):
            term = _vocab_term(row.get("reason", ""))
            if term is None:
                continue
            for pat in {term.lower().replace(" ", "-"), term.lower().replace(" ", "")}:
                if len(pat) >= 4 and SAFE_PATTERN.match(f"%{pat}%"):
                    seen[(f"%{pat}%", str(list_id))] = None

    out = []
    for pattern, target in seen:
        m = measure(pattern, target, dest, by_url)
        if verdict(m) is None:
            out.append(m)
    out.sort(key=lambda m: (int(m["target"]), -m["hits"], m["pattern"]))
    return out


def sql(m: dict) -> str:
    pat = m["pattern"]
    if not SAFE_PATTERN.match(pat):
        raise ValueError(f"motif refusé (caractères non autorisés): {pat!r}")
    return (f"UPDATE `{TABLE}` SET `listId`={int(m['target'])} "
            f"WHERE `url` LIKE '{pat}' AND `listId`={PENDING_LIST};")


def render(items: list[dict], refused: list[tuple[dict, str]]) -> str:
    lines = ["# Requêtes de tri — à exécuter À LA MAIN dans phpMyAdmin",
             "#",
             "# Chaque requête ne touche que le pending (`AND listId=9`) et ne change que",
             "# `listId`. Le compte à droite est mesuré sur le scan de tri, pas estimé.",
             ""]
    by_target: dict[str, list[dict]] = defaultdict(list)
    for m in items:
        by_target[m["target"]].append(m)
    for target in sorted(by_target, key=lambda t: int(t)):
        lines.append(f"-- liste {target} — {len(by_target[target])} requête(s)")
        for m in by_target[target]:
            lines.append(f"{sql(m)}   -- {m['hits']} ligne(s) ; ex. {m['sample'][0] if m['sample'] else ''}")
        lines.append("")
    if refused:
        lines += ["", "# --- motifs ÉCARTÉS (pour information, ne pas exécuter) ---"]
        for m, why in refused[:40]:
            lines.append(f"# {m['pattern']} → liste {m['target']} : {why}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Génère des UPDATE de tri (aucune écriture DB).")
    ap.add_argument("--run-id", required=True, help="scan de tri (runs/<id>)")
    ap.add_argument("--check", action="append", default=[],
                    metavar="'%motif%:listId'",
                    help="audite un motif écrit à la main au lieu de proposer")
    ap.add_argument("--rules", action="store_true",
                    help="audite les règles quotidiennes de Romain (src/sort_sql_rules.py) "
                         "contre ce scan, au lieu d'en proposer de nouvelles")
    ap.add_argument("--out", default=None, help="écrit le résultat dans ce fichier")
    args = ap.parse_args()

    run_dir = ROOT / "runs" / args.run_id
    if not (run_dir / "sort_plan.json").exists():
        print(f"pas de sort_plan.json dans {run_dir}", file=sys.stderr)
        return 2
    dest, by_url = _classify(run_dir)

    if args.check:
        rows = []
        for spec in args.check:
            pat, _, target = spec.rpartition(":")
            if not pat or not target.strip().isdigit():
                print(f"format attendu '%motif%:listId' — reçu {spec!r}", file=sys.stderr)
                return 2
            rows.append(measure(pat, target.strip(), dest, by_url))
        for m in rows:
            why = verdict(m)
            print(f"\n{m['pattern']} → liste {m['target']}")
            print(f"  vise {m['hits']} | d'accord {m['agree']} | conflit {m['conflict']}"
                  f" | à garder {m['keep']} | collatéral {m['collateral']}")
            for s in m["sample"]:
                print("   ·", s)
            if m["sample_collateral"]:
                print("  COLLATÉRAL (vrais jeux) :")
                for s in m["sample_collateral"]:
                    print("   ✖", s)
            print("  verdict:", why or "SÛR — proposable tel quel")
        return 0

    plan = json.loads((run_dir / "sort_plan.json").read_text(encoding="utf-8"))
    if args.rules:
        from src.sort_sql_rules import FLAGGED, RULES
        print(f"# {len(RULES)} règles quotidiennes confrontées au scan {args.run_id}\n")
        safe, risky = [], []
        for pattern, target in RULES:
            m = measure(pattern, target, dest, by_url)
            (risky if (m["collateral"] or m["conflict"]) else safe).append(m)
            flag = FLAGGED.get(pattern)
            mark = "!!" if m["collateral"] else ("!" if m["conflict"] else "  ")
            print(f"{mark} {pattern:32} -> {target:>3} | vise {m['hits']:5} | "
                  f"d'accord {m['agree']:5} | conflit {m['conflict']:4} | "
                  f"collatéral {m['collateral']:5}")
            if m["sample_collateral"]:
                for s in m["sample_collateral"][:2]:
                    print(f"      vrai jeu visé : {s}")
            if flag:
                print(f"      SIGNALÉE : {flag[:150]}")
        print(f"\n# {len(safe)} règle(s) sans collatéral ni conflit, "
              f"{len(risky)} à regarder")
        return 0

    items = propose(dest, by_url, plan)
    refused: list[tuple[dict, str]] = []
    text = render(items, refused)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(items)} requête(s) écrites dans {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
