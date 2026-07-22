"""Build a Move-to-List plan from a run's Learning annotations.

The plan is the move writer's validation file. It is the operator's confirmed
human intent (learning.json is the trusted authority — MV13, review 2026-07-21:
there is deliberately no cryptographic freeze/fingerprint gate like the submit's
``verify_approved_against_source``; the writer's own fresh-page identity re-check
(mover ``_reverify_row``, SC5) is what guards against a stale/wrong pairing at
move time). It contains ONLY confirmed dispositions:

  * ``target_list_id`` set (a *garder* / "don't change" row has none), AND
  * NOT ``suggested`` — D1 option (b), Romain 2026-07-21: a pre-selected
    suggestion the operator never manipulated is never a move.

Each entry is joined with ``skipped.json`` for the offer's merchant name + URL
(the stable identity the writer relocates by — ids rotate on re-import). An
annotation whose offer_id is no longer in ``skipped.json`` is EXCLUDED (surfaced,
never silently dropped) — without a URL the writer could not fail-closed locate
it. Read-only: builds a plan, writes nothing to the feed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.mover import source_feed_page
from src.submitter import _url_key


def _load(run_dir: Path, name: str) -> Any:
    path = run_dir / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_move_plan(run_dir: Path) -> dict[str, Any]:
    """Return ``{run_id, store_id, source_feed_page, entries, excluded, counts}``.

    ``entries`` are the confirmed Move-to-List dispositions ready for the writer;
    ``excluded`` lists dispositions dropped (with a reason)."""

    run_dir = Path(run_dir)
    learning = _load(run_dir, "learning.json") or {}
    annotations = learning.get("annotations") if isinstance(learning, dict) else None
    annotations = annotations if isinstance(annotations, dict) else {}

    skipped = _load(run_dir, "skipped.json")
    skipped_map: dict[str, dict[str, str]] = {}
    by_url: dict[str, dict[str, str]] = {}  # F3: stable-identity fallback index
    for entry in skipped if isinstance(skipped, list) else []:
        if not isinstance(entry, dict):
            continue
        offer = entry.get("offer") or {}
        oid = str(offer.get("offer_id", "")).strip()
        if oid:
            info = {"offer_id": oid, "name": str(offer.get("name", "")),
                    "url": str(offer.get("url", ""))}
            skipped_map[oid] = info
            key = _url_key(info["url"])
            if key:
                by_url.setdefault(key, info)

    raw = _load(run_dir, "raw.json") or {}
    store_id = str(raw.get("store_id", "")) if isinstance(raw, dict) else ""
    feed_page = source_feed_page(raw.get("source_url") if isinstance(raw, dict) else None)

    entries: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for offer_id, ann in annotations.items():
        if not isinstance(ann, dict):
            continue
        target = str(ann.get("target_list_id", "")).strip()
        if not target:
            continue  # *garder* / no disposition — never a move
        # F1 (seam audit 2026-07-21): fail-CLOSED on the truthiness contract —
        # exclude on ANY truthy `suggested` (a non-canonical JSON 1/"true" must
        # never slip through as a confirmed move), not only strict `is True`.
        if ann.get("suggested"):
            excluded.append({"offer_id": offer_id, "reason": "suggestion non confirmée (D1-b)",
                             "target_list_label": ann.get("target_list_label", "")})
            continue
        info = skipped_map.get(str(offer_id))
        if info is None:
            # F3: the offer_id rotated (re-import); relocate the confirmed
            # disposition by the frozen merchant URL against the current feed.
            frozen = _url_key(str(ann.get("merchant_url", "")))
            info = by_url.get(frozen) if frozen else None
            if info is None:
                excluded.append({"offer_id": offer_id,
                                 "reason": "offer_id absent de skipped.json (orphelin) — URL non retrouvée dans le feed courant",
                                 "target_list_label": ann.get("target_list_label", "")})
                continue
        if not info["url"].strip():
            # MV3 (review 2026-07-21): without a merchant URL the writer's
            # disappearance proof degrades to id-only, which a re-import falsifies
            # (false "gone"). Exclude — the exact guarantee this join promised.
            excluded.append({"offer_id": offer_id,
                             "reason": "URL marchande vide dans skipped.json — preuve de disparition non fiable",
                             "target_list_label": ann.get("target_list_label", "")})
            continue
        entries.append({
            "offer_id": info["offer_id"],  # current feed id (may differ after re-import)
            "annotated_offer_id": str(offer_id),
            "name": info["name"],
            "url": info["url"],
            "target_list_id": target,
            "target_list_label": str(ann.get("target_list_label", "")),
        })

    return {
        "run_id": learning.get("run_id") if isinstance(learning, dict) else run_dir.name,
        "store_id": store_id,
        "source_feed_page": feed_page,
        "entries": entries,
        "excluded": excluded,
        "counts": {"entries": len(entries), "excluded": len(excluded),
                   "annotations": len(annotations)},
    }
