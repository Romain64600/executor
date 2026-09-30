#!/usr/bin/env python3
"""La photo de CETTE machine sur UNE ligne JSON — l'onglet « Vue d'ensemble » (2026-09-30).

Romain : « Qu'on puisse voir si les serveurs sont up, le type de tâche actuel, etc. », puis « Go
pour l'onglet vue d'ensemble ». La logique vit dans ``src/vps_snapshot.py`` (l'admin local
l'appelle en processus) ; ce script l'imprime, pour les AUTRES machines :

* c'est la **commande forcée** de la clé ssh dédiée à la vue d'ensemble — l'admin qui lit une
  machine distante ne choisit jamais ce qui s'y exécute (``ops/VUE_D_ENSEMBLE.md``) :

      command="python3 /home/debian/executor/scripts/20_vps_snapshot.py",restrict,…

* à la main, pour voir la même chose que la console : ``python3 scripts/20_vps_snapshot.py``
  (``--pretty`` pour l'indenter).

Lecture seule, < 3 s d'ordinaire (6 s au pire quand l'admin tarde à lister ses runs), n'échoue
jamais : code de sortie 0 et une ligne JSON, même quand une section n'a pas pu être lue (son motif
est dans ``errors``). Aucun argument venu de ssh n'est lu
(la commande forcée n'en passe pas ; ``SSH_ORIGINAL_COMMAND`` est ignorée).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    pretty = "--pretty" in args
    try:
        from src.vps_snapshot import snapshot
        snap = snapshot(ROOT)
    except Exception as exc:                  # noqa: BLE001 — une ligne JSON, toujours
        snap = {"schema": 1, "errors": {"snapshot": f"{type(exc).__name__}: {exc}"[:300]}}
    try:
        print(json.dumps(snap, ensure_ascii=False, indent=2 if pretty else None), flush=True)
    except (BrokenPipeError, OSError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
