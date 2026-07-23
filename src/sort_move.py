"""Build a per-store Move-to-List plan for ONE target list of a sort run.

Stage 8 produces ``sort_plan.json`` (all-stores, offers grouped by target list).
The sort-move writer (Stage 9) executes ONE target list at a time — Romain's
per-list bulk validation (2026-07-23). Because the mover is single-store (its
source/target scans take a ``store_id``), a list that spans many stores is split
into one single-store plan per store; the writer runs the proven ``Mover`` once
per store.

Pure and deterministic — reads ``sort_plan.json`` + ``raw.json``, writes nothing
to the feed. Each entry carries the stable merchant URL (the mover relocates by
URL — ids rotate on re-import) and the target list LABEL (the mover resolves the
label to the LIVE list id at move time; ids drift, labels don't).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.aks_lists import label_for
from src.mover import source_feed_page


def _load(run_dir: Path, name: str) -> Any:
    path = run_dir / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_sort_move_plan(run_dir: Path, target_list_id: str) -> dict[str, Any]:
    """Return ``{run_id, target_list_id, target_list_label, source_feed_page,
    by_store, excluded, counts}`` for one target list of the sort plan.

    ``by_store`` maps each ``store_id`` to its list of confirmed move entries.
    Offers with no ``store_id`` or no merchant URL are EXCLUDED (surfaced, never
    silently dropped) — the mover could not fail-closed relocate them."""

    run_dir = Path(run_dir)
    target_list_id = str(target_list_id)
    plan = _load(run_dir, "sort_plan.json") or {}
    raw = _load(run_dir, "raw.json") or {}
    source = source_feed_page(raw.get("source_url") if isinstance(raw, dict) else None)

    group = (plan.get("by_list") or {}).get(target_list_id) or {}
    # Label is the routing intent's stable name; the mover resolves it live. Fall
    # back to the catalog label if the plan didn't carry one.
    label = group.get("label") or label_for(target_list_id)

    by_store: dict[str, list[dict[str, Any]]] = {}
    excluded: list[dict[str, Any]] = []
    for offer in group.get("offers", []):
        store = str(offer.get("store_id") or "").strip()
        url = str(offer.get("url") or "").strip()
        if not store:
            excluded.append({"offer_id": offer.get("offer_id"), "name": offer.get("name"),
                             "reason": "store_id manquant — mover ne peut pas localiser fail-closed"})
            continue
        if not url:
            excluded.append({"offer_id": offer.get("offer_id"), "name": offer.get("name"),
                             "reason": "URL marchande vide — preuve de disparition non fiable"})
            continue
        by_store.setdefault(store, []).append({
            "offer_id": str(offer.get("offer_id") or ""),
            "name": offer.get("name", ""),
            "url": url,
            "target_list_id": target_list_id,
            "target_list_label": label,
        })

    total = sum(len(v) for v in by_store.values())
    return {
        "run_id": plan.get("run_id") or run_dir.name,
        "target_list_id": target_list_id,
        "target_list_label": label,
        "source_feed_page": source,
        "by_store": by_store,
        "excluded": excluded,
        "counts": {"stores": len(by_store), "offers": total, "excluded": len(excluded)},
    }
