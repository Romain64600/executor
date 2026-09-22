#!/usr/bin/env python3
"""Le tri SQL par identifiants — les lignes qu'aucun motif d'URL ne sait désigner.

Romain, 2026-09-22 : « liste 22, go ».

    python3 scripts/17_sort_sql_ids.py --run 20260921-140728-auto --list 22
    python3 scripts/17_sort_sql_ids.py --run 20260921-140728-auto --list 22 \\
        --out docs/tri/20260922-no-page.sql --chunk 500

Lecture seule de bout en bout : on lit les ``skipped.json`` d'un balayage, on confronte chaque
ligne au sitemap d'AKS, et on ÉCRIT DU TEXTE. Aucune connexion à la base, aucun driver. Romain
colle les requêtes dans phpMyAdmin lui-même, en commençant par l'étape 0 de vérification.

Le rapport affiché distingue trois cas, et c'est le cœur du garde-fou :
  * **à déplacer** — le sitemap ne publie aucune page pour ce slug ;
  * **page existe** — une page existe sous un gabarit qu'on ne sonde pas (``-key``,
    ``-steam-account``…) : à rematcher, surtout pas à déplacer ;
  * **doute** — une page voisine partage le préfixe du slug : on s'abstient.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_sitemap import DEFAULT_PATH, DEFAULT_TTL_DAYS, SitemapIndex  # noqa: E402
from src.matcher import build_slug_candidates  # noqa: E402
from src.admin.auto_merchants import AUTO_MERCHANTS  # noqa: E402
from src.sort_sql_ids import (  # noqa: E402
    DEFAULT_CHUNK,
    ExportRefused,
    FAMILIES,
    collect,
    collect_from_sort_scan,
    domain_of,
    partition,
    render_sql,
)

# `--others` = « toutes les boutiques SAUF les nôtres », et le filtre porte sur le
# **store_id**, pas sur le domaine. J'avais d'abord écrit une table de domaines à la main :
# deux entrées sur seize étaient fausses — GamersOutlet est sur `gamers-outlet.net` (tiret)
# et Allyouplay n'a pas de domaine propre, ses liens passent par `anandadigitalbv.sjv.io`.
# Leurs lignes partaient donc dans l'export « des autres », en double. Le store_id est la
# clé de la liste blanche elle-même : il ne peut pas diverger.
NOS_STORES = {store for _, store in AUTO_MERCHANTS}


def main() -> int:
    ap = argparse.ArgumentParser(description="Tri SQL par identifiants (lecture seule).")
    ap.add_argument("--run", required=True,
                    help="préfixe du balayage, ou dossier du scan de tri avec --sort-scan")
    ap.add_argument("--sort-scan", action="store_true",
                    help="lire un scan de TRI tous-magasins au lieu d'un balayage : c'est la "
                         "seule source pour les boutiques jamais balayées")
    ap.add_argument("--others", action="store_true",
                    help="avec --sort-scan : ne garder que les boutiques HORS liste blanche")
    ap.add_argument("--only-domain", action="append", default=[],
                    help="avec --sort-scan : ne garder que ce domaine (répétable)")
    ap.add_argument("--runs-dir", default=str(ROOT / "runs"))
    ap.add_argument("--family", default="no_aks_page", choices=sorted(FAMILIES))
    ap.add_argument("--list", dest="target", type=int, required=True,
                    help="liste AKS cible (22 = Pages for creation)")
    ap.add_argument("--sitemap", default=str(ROOT / DEFAULT_PATH))
    ap.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS)
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    ap.add_argument("--out", default=None, help="écrire le .sql ici (défaut : stdout)")
    ap.add_argument("--held-out", default=None,
                    help="écrire en JSON les lignes RETENUES (page existante / doute)")
    ap.add_argument("--allow-stale", action="store_true",
                    help="accepter un index périmé (déconseillé : on déplace à l'aveugle)")
    args = ap.parse_args()

    index = SitemapIndex.load(args.sitemap)
    if index is None:
        print(f"aucun index sitemap en {args.sitemap} — lancer "
              "`python3 scripts/16_sitemap_index.py --refresh`", file=sys.stderr)
        return 2
    if index.incomplete:
        print("index sitemap INCOMPLET (des sous-sitemaps ont échoué) — "
              "relancer --refresh avant d'exporter", file=sys.stderr)
        return 2
    if not index.fresh(args.ttl_days) and not args.allow_stale:
        age = index.age_days()
        print(f"index sitemap périmé ({age:.1f} j > {args.ttl_days} j) — relancer --refresh, "
              "ou --allow-stale en connaissance de cause", file=sys.stderr)
        return 2

    if args.sort_scan:
        if args.family != "no_aks_page":
            print("--sort-scan ne sait produire que la famille no_aks_page : un scan de tri "
                  "n'a pas sondé les pages, c'est l'index sitemap qui tranche", file=sys.stderr)
            return 2
        dossier = Path(args.runs_dir) / args.run
        if not (dossier / "sort_plan.json").exists():
            print(f"pas de sort_plan.json dans {dossier}", file=sys.stderr)
            return 2
        offres = collect_from_sort_scan(
            dossier,
            exclude_stores=NOS_STORES if args.others else (),
            only_domains=args.only_domain)
    else:
        if args.others or args.only_domain:
            print("--others / --only-domain n'ont de sens qu'avec --sort-scan", file=sys.stderr)
            return 2
        offres = collect(args.runs_dir, args.run, args.family)
    if not offres:
        print(f"aucune ligne « {FAMILIES[args.family]['label']} » dans {args.run}",
              file=sys.stderr)
        return 1
    part = partition(offres, index, build_slug_candidates)

    source = ("scan de tri tous-magasins" if args.sort_scan else "balayage")
    entete = (
        f"{source} {args.run} — famille « {FAMILIES[args.family]['label']} »\n"
        f"index sitemap : {len(index.entries)} pages, relevé {index.fetched_at}\n"
        f"lues {len(offres)} — retenues {len(part.page_exists)} (page existante) "
        f"+ {len(part.doubtful)} (doute par préfixe) + {len(part.not_a_game)} (pas un jeu)"
    )
    try:
        sql = render_sql(part.to_move, args.target, chunk=args.chunk, header=entete)
    except ExportRefused as exc:
        print(f"export refusé : {exc}", file=sys.stderr)
        return 2

    if args.out:
        chemin = Path(args.out)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(sql, encoding="utf-8")
    else:
        sys.stdout.write(sql)

    if args.held_out:
        Path(args.held_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.held_out).write_text(json.dumps(
            {"page_existe": part.page_exists, "doute_prefixe": part.doubtful,
             "pas_un_jeu": part.not_a_game},
            ensure_ascii=False, indent=2), encoding="utf-8")

    rapport = {
        "run": args.run,
        "famille": args.family,
        "liste_cible": args.target,
        "lues": len(offres),
        **part.counts(),
        "lots": (len(part.to_move) + args.chunk - 1) // max(1, args.chunk),
        "out": args.out,
        "held_out": args.held_out,
    }
    print(json.dumps(rapport, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
