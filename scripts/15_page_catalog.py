#!/usr/bin/env python3
"""Le catalogue des pages AKS — inspection et entretien (lecture seule par défaut).

Romain, 2026-09-21 : « à la page, je vais faire correspondre un type de page comme early
access, DLC… et aussi renseigner les régions d'édition déjà présentes ». C'est ce que ce
catalogue garde, et ce script est la fenêtre dessus.

    python3 scripts/15_page_catalog.py --stats
    python3 scripts/15_page_catalog.py --get subnautica-2 --kind steam-account
    python3 scripts/15_page_catalog.py --nature early_access --limit 20
    python3 scripts/15_page_catalog.py --db debian@51.38.37.254:/home/debian/executor/state/page_catalog.db --stats

La base par défaut est ``state/page_catalog.db`` (gitignorée comme le reste de `state/`).
Une spécification ``<user>@<hôte>:<chemin>`` lit la base PARTAGÉE de l'autre VPS par le
tunnel SSH existant — connexion multiplexée, accès groupés, disjoncteur après deux échecs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.page_catalog import (  # noqa: E402
    DEFAULT_TTL_DAYS,
    catalog_from_spec,
    describe,
)

DEFAULT_DB = "state/page_catalog.db"


def main() -> int:
    ap = argparse.ArgumentParser(description="Catalogue des pages AKS (lecture seule).")
    ap.add_argument("--db", default=str(ROOT / DEFAULT_DB),
                    help="chemin local, ou '<user>@<hôte>:<chemin>' pour la base partagée")
    ap.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS,
                    help="au-delà, un relevé n'est plus considéré comme frais (défaut 30)")
    ap.add_argument("--stats", action="store_true", help="combien de pages, par nature")
    ap.add_argument("--get", metavar="SLUG", help="une page précise")
    ap.add_argument("--kind", default="cd-key", help="gabarit de page (défaut cd-key)")
    ap.add_argument("--nature", help="lister les pages d'une nature (standard/dlc/early_access/inconnue)")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--stale", action="store_true",
                    help="avec --get : accepter un relevé périmé (sinon il est ignoré)")
    args = ap.parse_args()

    cat = catalog_from_spec(args.db, source="15_page_catalog", ttl_days=args.ttl_days)
    if cat is None:
        print("aucune base indiquée", file=sys.stderr)
        return 2

    if args.get:
        row = cat.get(args.get, args.kind, fresh_only=not args.stale)
        if not row:
            print(json.dumps({"slug": args.get, "page_kind": args.kind, "connue": False,
                              "erreur": cat.last_error or None}, ensure_ascii=False, indent=2))
            return 0
        row["description"] = describe(row)
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0

    if args.nature:
        rows = cat.by_nature(args.nature, limit=args.limit)
        for r in rows:
            print("%-44s %-16s %-14s %s" % (r["slug"][:44], r["page_kind"], r["nature"], r["aks_name"][:40]))
        print("(%d ligne(s)%s)" % (len(rows), " — " + cat.last_error if cat.last_error else ""))
        return 0

    stats = cat.stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if cat.last_error:
        print("erreur:", cat.last_error, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
