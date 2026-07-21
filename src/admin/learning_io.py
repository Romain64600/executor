"""Learning mode — annotate non-matched offers from the admin page.

For a matched run, the matcher produced ``skipped.json`` (every offer that did
NOT become a candidate, with its reason). The Learning view groups those by
reason and lets the operator attach, per offer, a **region id**, an **edition
id** (both real ids from the live session catalog — Romain 2026-07-21) and a
free-text **comment**. The annotations are stored in ``learning.json``; the
builder agent reads them to (a) learn a matcher rule for a recurring type, and
(b) enter that specific offer by hand with the given region/edition.

Read-only grouping + a fail-closed atomic save. Standard library only.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.admin.runs import read_run_json, run_file
from src.aks_lists import LISTS, suggest_target_list, year_in_name


class LearningError(Exception):
    """A refused Learning save. ``code`` machine-readable, ``message`` verbatim."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _category(reason: str) -> str:
    """The coarse skip category: the reason up to the first ':' / ',' / ' — '."""

    return reason.split(":")[0].split(",")[0].split(" — ")[0].strip() or "autre"


def group_skipped(run_dir: Path) -> list[dict[str, Any]]:
    """The run's non-matched offers grouped by reason category, biggest first."""

    skipped = read_run_json(run_dir, "skipped.json")
    if not isinstance(skipped, list):
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in skipped:
        if not isinstance(entry, dict):
            continue
        offer = entry.get("offer") or {}
        reason = str(entry.get("reason", ""))
        name = str(offer.get("name", ""))
        cat = _category(reason)
        groups.setdefault(cat, []).append(
            {
                "offer_id": str(offer.get("offer_id", "")),
                "name": name,
                "url": str(offer.get("url", "")),
                "reason": reason,
                # deterministic triage suggestion (docs/AKS_LISTS.md); None = garder.
                "suggested_list_id": suggest_target_list(reason),
                # weak hint for the 22-vs-27 human call on "no AKS page" offers.
                "year": year_in_name(name),
            }
        )
    return [
        {"reason": cat, "count": len(offers), "offers": offers}
        for cat, offers in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    ]


def list_catalog() -> list[dict[str, str]]:
    """The movable target lists (id -> label) for the Learning dropdown.

    The UI adds its own "garder (ne pas changer)" default; the writer re-resolves
    the chosen label -> id live at write time (ids may drift — docs/AKS_LISTS.md)."""

    return [dict(x) for x in LISTS]


def load_annotations(run_dir: Path) -> dict[str, Any]:
    """Existing per-offer annotations (offer_id -> {region_id, ...}), or {}."""

    data = read_run_json(run_dir, "learning.json")
    if isinstance(data, dict) and isinstance(data.get("annotations"), dict):
        return data["annotations"]
    return {}


def save_annotations(
    run_dir: Path, annotations: Any, *, by: str, clock=_utc_now_iso
) -> dict[str, Any]:
    """Persist Learning annotations to ``learning.json`` (fail-closed).

    ``annotations`` is a list of ``{offer_id, region_id, region_text,
    edition_id, edition_text, comment, aks_url, target_list_id,
    target_list_label}`` — each offer_id MUST be a real non-matched offer of
    this run (else the annotation is meaningless). ``aks_url`` is the AKS product
    page the matcher failed to find (assisted manual entry of the "no AKS page"
    bucket); ``target_list_id`` is a Move-to-List disposition (garder = empty =
    dropped). An entry with no region/edition/comment/aks_url/target_list is
    dropped (a cleared row)."""

    if not isinstance(annotations, list):
        raise LearningError("bad_body", "annotations doit être une liste")
    skipped = read_run_json(run_dir, "skipped.json")
    valid_ids = {
        str((s.get("offer") or {}).get("offer_id", ""))
        for s in (skipped if isinstance(skipped, list) else [])
    }
    stored: dict[str, Any] = {}
    for item in annotations:
        if not isinstance(item, dict):
            raise LearningError("bad_body", "chaque annotation doit être un objet")
        oid = str(item.get("offer_id", ""))
        if oid not in valid_ids:
            raise LearningError(
                "bad_offer", f"offer_id {oid!r} absent de skipped.json de ce run"
            )
        fields = {
            k: str(item.get(k)).strip()
            for k in ("region_id", "region_text", "edition_id", "edition_text",
                      "comment", "aks_url", "target_list_id", "target_list_label")
            if str(item.get(k) or "").strip()
        }
        # a region/edition id must carry meaning: keep only rows the operator
        # actually filled (any of region/edition/comment/aks_url/target_list present).
        if any(fields.get(k) for k in ("region_id", "edition_id", "comment",
                                       "aks_url", "target_list_id")):
            fields["by"] = by
            fields["at"] = clock()
            stored[oid] = fields
    payload = {
        "run_id": run_dir.name,
        "updated_at": clock(),
        "annotations": stored,
    }
    _write_json_atomic(run_file(run_dir, "learning.json"), payload)
    return {"saved": len(stored), "annotations": stored}
