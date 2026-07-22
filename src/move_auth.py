"""Move-to-List batch authorization (RV3, review 2026-07-22).

A supervised UNIT canary that VERIFIES a move (gone from source AND present on
the target list — RV2) GRANTS a scoped, versioned authorization. This module
records and checks that authorization.

**It does NOT itself unlock the batch.** Re-enabling ``--mode safe`` stays a
separate, explicit decision (Romain 2026-07-22): the mechanism is built and the
authorization is produced and checkable, but ``scripts/06_move.py`` keeps
refusing ``--execute --mode safe`` unconditionally until that decision is taken.

The authorization is bound (at minimum) to: the **mover version**, the
**store**, the **source list**, the validated **target lists** (by stable label),
and the **extraction context** (a hash of the run's ``skipped.json``). Any drift
in one of these → the authorization no longer covers a batch (fail-closed).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.mover import MOVER_VERSION

AUTH_FILE = "move_authorization.json"


def extraction_id(run_dir: Path) -> str:
    """Stable identity of the run's DATA — a hash of ``skipped.json``. A re-match
    rewrites skipped.json, so a stale authorization stops covering refreshed data."""

    path = Path(run_dir) / "skipped.json"
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _scope(run_dir: Path, store_id: str | int, source_feed_page: str) -> dict[str, str]:
    return {
        "mover_version": MOVER_VERSION,
        "store_id": str(store_id),
        "source_feed_page": str(source_feed_page),
        "extraction_id": extraction_id(run_dir),
    }


def load_authorization(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / AUTH_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
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


def grant_from_canary(
    run_dir: Path, *, store_id: str | int, source_feed_page: str,
    moved_entries: list[dict[str, Any]], clock,
) -> dict[str, Any]:
    """Record/extend the authorization from the TARGET LISTS a canary verified.

    Only offers whose move was fully proven (gone from source AND present on the
    target — the caller passes ``result['plan']`` entries with ``moved=True``)
    contribute. The authorization is keyed by the current scope; if the scope
    (mover version / store / source / extraction) changed, it resets."""

    run_dir = Path(run_dir)
    scope = _scope(run_dir, store_id, source_feed_page)
    auth = load_authorization(run_dir)
    if not auth or any(auth.get(k) != v for k, v in scope.items()):
        auth = dict(scope, authorized_target_lists=[], canaries=[], version=0)

    targets = set(auth.get("authorized_target_lists", []))
    canaries = list(auth.get("canaries", []))
    for entry in moved_entries:
        label = str(entry.get("target_list_label", "")).strip()
        if label:
            targets.add(label)
        canaries.append({
            "offer_id": entry.get("current_offer_id") or entry.get("offer_id"),
            "url": entry.get("url"),
            "target_list_label": label,
            "at": clock(),
        })
    auth["authorized_target_lists"] = sorted(targets)
    auth["canaries"] = canaries[-50:]  # keep the tail, bounded
    auth["version"] = int(auth.get("version", 0)) + 1
    auth["granted_at"] = clock()
    _write_atomic(run_dir / AUTH_FILE, auth)
    return auth


def batch_authorized(
    run_dir: Path, plan_entries: list[dict[str, Any]], *,
    store_id: str | int, source_feed_page: str,
) -> tuple[bool, str]:
    """``(ok, reason)`` — would a ``--mode safe`` batch of ``plan_entries`` be
    covered by the current authorization? (Advisory: the CLI still refuses safe
    unconditionally — RV1 — until the explicit re-enable decision.)"""

    run_dir = Path(run_dir)
    auth = load_authorization(run_dir)
    if not auth:
        return False, ("aucune autorisation — lance un canary --mode learning qui "
                       "vérifie chaque liste cible")
    scope = _scope(run_dir, store_id, source_feed_page)
    for key, want in scope.items():
        if auth.get(key) != want:
            return False, (f"hors périmètre: {key} attendu {want!r}, autorisé "
                           f"{auth.get(key)!r} — re-canary requis")
    authorized = set(auth.get("authorized_target_lists", []))
    plan_labels = {str(e.get("target_list_label", "")).strip() for e in plan_entries}
    unvalidated = {label for label in plan_labels if label and label not in authorized}
    if unvalidated:
        return False, (f"listes cibles non validées par un canary: {sorted(unvalidated)} "
                       f"(autorisées: {sorted(authorized)})")
    return True, (f"couvert par l'autorisation v{auth.get('version')} "
                  f"(listes {sorted(authorized)}, mover {MOVER_VERSION})")
