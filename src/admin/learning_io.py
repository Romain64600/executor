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

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.admin.runs import load_catalog_options, read_run_json, run_file
from src.aks_lists import LISTS, label_for, suggest_target_list, year_in_name


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


# Audit Learning 2026-07-21, L5: server-side field caps + AKS page format.
_MAX_FIELD_CHARS = 2000
_AKS_PAGE_PREFIX = "https://www.allkeyshop.com/blog/"
_LIST_IDS = frozenset(x["id"] for x in LISTS)

_ANNOTATION_FIELDS = ("region_id", "region_text", "edition_id", "edition_text",
                      "comment", "aks_url", "target_list_id", "target_list_label")


def learning_sha(run_dir: Path) -> str | None:
    """sha256 of learning.json, or None when absent — the save precondition."""

    path = run_file(run_dir, "learning.json")
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skipped_offer_ids(run_dir: Path) -> set[str]:
    """Whitelist of annotatable offer_ids (L10: malformed entries / empty ids
    are ignored here exactly as group_skipped never renders them)."""

    skipped = read_run_json(run_dir, "skipped.json")
    ids: set[str] = set()
    for entry in skipped if isinstance(skipped, list) else []:
        if not isinstance(entry, dict):
            continue
        oid = str((entry.get("offer") or {}).get("offer_id", "")).strip()
        if oid:
            ids.add(oid)
    return ids


def _validate_fields(
    fields: dict[str, str], oid: str, existing: dict[str, Any],
    catalog: dict[str, list[dict[str, str]]] | None,
) -> None:
    """L5 — the server is the fail-closed boundary, not the dropdowns.

    A region/edition id must belong to the run's session catalog (or already be
    stored for this offer — the grandfather case of a catalog re-fetched with
    drifted ids, L3); a target list must exist in the catalog with a coherent
    label; an AKS page must look like an AKS blog page."""

    for key, value in fields.items():
        if len(value) > _MAX_FIELD_CHARS:
            raise LearningError("too_long", f"{key} dépasse {_MAX_FIELD_CHARS} caractères")
    target = fields.get("target_list_id")
    if target:
        if target not in _LIST_IDS:
            raise LearningError("bad_list", f"target_list_id {target!r} inconnu du catalogue de listes")
        expected = label_for(target)
        label = fields.get("target_list_label")
        if label and label != expected:
            raise LearningError(
                "bad_list_label",
                f"target_list_label {label!r} incohérent avec l'id {target!r} ({expected!r})",
            )
        fields["target_list_label"] = expected
    prior = existing.get(oid) or {}
    for id_key, options_key, code in (
        ("region_id", "regions", "bad_region"), ("edition_id", "editions", "bad_edition"),
    ):
        value = fields.get(id_key)
        if not value:
            continue
        if value == str(prior.get(id_key, "")):
            continue  # unchanged stored value survives a catalog drift (L3)
        if catalog is None:
            raise LearningError(code, f"{id_key} fourni mais catalogue de session absent")
        if value not in {o["key"] for o in catalog[options_key]}:
            raise LearningError(code, f"{id_key} {value!r} absent du catalogue de session")
    url = fields.get("aks_url")
    if url and not url.startswith(_AKS_PAGE_PREFIX):
        raise LearningError("bad_url", f"aks_url doit commencer par {_AKS_PAGE_PREFIX}")


def _append_log(run_dir: Path, event: dict[str, Any]) -> None:
    """L6 — one JSONL event per save (AGENTS.md: JSONL logs for every action)."""

    with run_file(run_dir, "learning_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def save_annotations(
    run_dir: Path, annotations: Any, *, by: str, base_sha: str | None = None,
    clock=_utc_now_iso,
) -> dict[str, Any]:
    """Merge Learning annotations into ``learning.json`` (fail-closed).

    ``annotations`` is a list of ``{offer_id, region_id, region_text,
    edition_id, edition_text, comment, aks_url, target_list_id,
    target_list_label}`` rows, plus ``{offer_id, cleared: true}`` to delete a
    stored row explicitly. Audit Learning 2026-07-21:

    - **L2** — MERGE, never replace: offer_ids absent from the POST keep their
      stored annotation; deletion only via the explicit ``cleared`` signal.
      ``base_sha`` must match the current learning.json sha (None = absent) or
      the save is refused 409 — the AS1 anti-clobber pattern.
    - **L5** — fields are validated server-side (_validate_fields).
    - **L6** — every save appends a JSONL event to learning_log.jsonl.
    - **L11** — the first author/timestamp of a row survives edits
      (``first_at``); ``at`` is the last edit."""

    if not isinstance(annotations, list):
        raise LearningError("bad_body", "annotations doit être une liste")
    current_sha = learning_sha(run_dir)
    if base_sha != current_sha:
        raise LearningError(
            "conflict",
            "learning.json a changé depuis le chargement — recharge avant d'enregistrer",
            http_status=409,
        )
    valid_ids = _skipped_offer_ids(run_dir)
    stored = dict(load_annotations(run_dir))
    catalog = load_catalog_options(run_dir)
    touched: list[str] = []
    cleared: list[str] = []
    for item in annotations:
        if not isinstance(item, dict):
            raise LearningError("bad_body", "chaque annotation doit être un objet")
        oid = str(item.get("offer_id", ""))
        if oid not in valid_ids:
            raise LearningError(
                "bad_offer", f"offer_id {oid!r} absent de skipped.json de ce run"
            )
        if item.get("cleared") is True:
            if stored.pop(oid, None) is not None:
                cleared.append(oid)
            continue
        fields = {
            k: str(item.get(k)).strip()
            for k in _ANNOTATION_FIELDS
            if str(item.get(k) or "").strip()
        }
        # keep only rows the operator actually filled (any of
        # region/edition/comment/aks_url/target_list present).
        if not any(fields.get(k) for k in ("region_id", "edition_id", "comment",
                                           "aks_url", "target_list_id")):
            continue
        _validate_fields(fields, oid, stored, catalog)
        now = clock()
        prior = stored.get(oid) or {}
        fields["by"] = by
        fields["at"] = now
        fields["first_at"] = prior.get("first_at", prior.get("at", now))
        fields["first_by"] = prior.get("first_by", prior.get("by", by))
        stored[oid] = fields
        touched.append(oid)
    payload = {
        "run_id": run_dir.name,
        "updated_at": clock(),
        "annotations": stored,
    }
    _write_json_atomic(run_file(run_dir, "learning.json"), payload)
    new_sha = learning_sha(run_dir)
    _append_log(run_dir, {
        "at": clock(), "by": by, "event": "learning_save",
        "before_sha": current_sha, "after_sha": new_sha,
        "touched": touched, "cleared": cleared, "total": len(stored),
    })
    return {
        "saved": len(touched), "cleared": len(cleared),
        "annotations": stored, "learning_sha256": new_sha,
    }
