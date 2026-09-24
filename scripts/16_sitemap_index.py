#!/usr/bin/env python3
"""L'index des pages produit d'AKS, depuis son sitemap (lecture seule, 2026-09-22).

    python3 scripts/16_sitemap_index.py --refresh
    python3 scripts/16_sitemap_index.py --stats
    python3 scripts/16_sitemap_index.py --has hades-cd-key
    python3 scripts/16_sitemap_index.py --kinds hades

Pourquoi : la recherche interne d'AKS (R30) répond ``HTTP 200`` avec un corps VIDE depuis les
deux VPS (mesuré le 2026-09-22) — elle ne peut plus confirmer qu'une page manque. Le sitemap,
lui, publie les 213 000 pages produit et se télécharge en quatre minutes. L'index sert à
PROUVER qu'une page n'existe pas avant de déplacer des milliers de lignes en liste 22.

Aucun secret, aucune session, aucune écriture AKS : on lit un fichier public avec l'UA
``AKS/Staff`` et le ``Crawl-delay`` annoncé par leur ``robots.txt``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_sitemap import (  # noqa: E402
    DEFAULT_PATH,
    DEFAULT_TTL_DAYS,
    SitemapIndex,
    SitemapUnavailable,
    refresh,
)
from src.sort_sql_ids import PAGE_KINDS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Index des pages produit AKS (lecture seule).")
    ap.add_argument("--path", default=str(ROOT / DEFAULT_PATH))
    ap.add_argument("--refresh", action="store_true", help="retélécharger le sitemap")
    ap.add_argument("--stats", action="store_true", help="ce que l'index contient")
    ap.add_argument("--has", metavar="SLUG_COMPLET",
                    help="ex. hades-cd-key — le segment ENTIER, gabarit compris")
    ap.add_argument("--legacy", metavar="SLUG",
                    help="ex. far-cry-3 — la page ANCIENNE compare-and-buy-… existe-t-elle ?")
    ap.add_argument("--kinds", metavar="SLUG",
                    help="ex. hades — sous quels gabarits ce slug a-t-il une page ?")
    ap.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS)
    ap.add_argument("--quiet", action="store_true", help="pas de progression ligne à ligne")
    args = ap.parse_args()

    if args.refresh:
        def progres(url: str, i: int, n: int) -> None:
            if not args.quiet:
                print("  %2d/%d %s" % (i, n, url.rsplit("/", 1)[-1]), file=sys.stderr)
        try:
            resume = refresh(args.path, on_progress=progres)
        except SitemapUnavailable as exc:
            print(f"sitemap illisible : {exc}", file=sys.stderr)
            return 2
        except Exception as exc:                        # noqa: BLE001
            print(f"échec du téléchargement : {exc}", file=sys.stderr)
            return 2
        print(json.dumps(resume, ensure_ascii=False, indent=2))
        return 1 if resume.get("incomplete") else 0

    index = SitemapIndex.load(args.path)
    if index is None:
        print(f"aucun index en {args.path} — lancer --refresh", file=sys.stderr)
        return 2

    if args.has:
        trouve = index.has_page(args.has)
        print(json.dumps({"slug": args.has, "page": trouve,
                          "voisine": index.any_page_starting_with(args.has)},
                         ensure_ascii=False, indent=2))
        return 0 if trouve else 1

    if args.legacy:
        trouve = index.has_legacy(args.legacy)
        print(json.dumps({"slug": args.legacy, "legacy_indexed": index.legacy_indexed,
                          "page_ancienne": trouve}, ensure_ascii=False, indent=2))
        return 0 if trouve else 1
    if args.kinds:
        gabarits = index.kinds_for(args.kinds, PAGE_KINDS)
        print(json.dumps({"slug": args.kinds, "gabarits": gabarits,
                          "voisine": index.any_page_starting_with(args.kinds)},
                         ensure_ascii=False, indent=2))
        return 0 if gabarits else 1

    age = index.age_days()
    print(json.dumps({
        "path": args.path,
        "pages": len(index.entries),
        "fetched_at": index.fetched_at,
        "age_days": round(age, 2) if age is not None else None,
        "fresh": index.fresh(args.ttl_days),
        "incomplete": index.incomplete,
        "legacy_indexed": index.legacy_indexed,
        "legacy_pages": len(index.legacy),
        "source": index.source,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
