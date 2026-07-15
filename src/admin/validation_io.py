"""Admin page — operator decisions to a consistent validation triple.

The submitter re-derives ``approved.json`` from its sibling ``candidates.json``
+ ``validation.json`` and refuses to run on any mismatch, so the admin page can
never patch one file alone: every save regenerates the whole triple, and
``approved.json`` itself is only ever written by the real stage script
(``scripts/04_validate.py check``), exactly as in the manual flow.

Operator overrides (region/edition/platform) rewrite the candidate entry in
``candidates.json``, recompute its fingerprint, and leave an
``operator_override`` audit field plus JSONL events — the matcher's original
pick is never lost. Region/edition choices must come from the run's own
``session_catalog.json``; without a catalog the save is refused (no free-text
ids — fail-closed). Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.admin.runs import load_catalog_options, run_file, sha256_file
from src.matcher import REGION_IDS
from src.run_log import RunLogger
from src.validation import (
    ValidationError,
    candidate_fingerprint,
    validation_template,
    verify_approved_against_source,
)

OVERRIDE_FIELDS = ("region_id", "edition_id", "platform")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ValidationIOError(Exception):
    """A refused save. ``code`` is machine-readable, ``message`` verbatim."""

    def __init__(
        self, code: str, message: str, *, http_status: int = 409, detail: Any = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _catalog_entry(options: list[dict[str, str]], key: str) -> dict[str, str] | None:
    for option in options:
        if option["key"] == str(key):
            return option
    return None


def _apply_override(
    candidate: dict[str, Any],
    override: dict[str, Any],
    catalog: dict[str, list[dict[str, str]]] | None,
    *,
    by: str,
    now: str,
) -> bool:
    """Mutate one candidate in place; True when anything actually changed."""

    unknown = set(override) - set(OVERRIDE_FIELDS)
    if unknown:
        raise ValidationIOError(
            "bad_override", f"unknown override fields: {sorted(unknown)}", http_status=400
        )

    changes: dict[str, Any] = {}
    region_id = override.get("region_id")
    if region_id is not None and str(region_id) != str(candidate["region"]["id"]):
        changes["region_id"] = str(region_id)
    edition_id = override.get("edition_id")
    if edition_id is not None and str(edition_id) != str(candidate["edition"]["id"]):
        changes["edition_id"] = str(edition_id)
    platform = override.get("platform")
    if platform is not None and platform != candidate.get("platform"):
        if platform not in REGION_IDS:
            raise ValidationIOError(
                "bad_option", f"unknown platform: {platform!r}", http_status=400
            )
        changes["platform"] = platform
    if not changes:
        return False

    if ("region_id" in changes or "edition_id" in changes) and catalog is None:
        raise ValidationIOError(
            "no_catalog",
            "session_catalog.json absent ou inutilisable — lancez la récupération du "
            "catalogue avant de modifier région/édition",
        )

    original = {
        "fingerprint": candidate_fingerprint(candidate),
        "region": dict(candidate["region"]),
        "edition": dict(candidate["edition"]),
        "platform": candidate.get("platform"),
    }

    if "region_id" in changes:
        entry = _catalog_entry(catalog["regions"], changes["region_id"])
        if entry is None:
            raise ValidationIOError(
                "bad_option",
                f"region id {changes['region_id']!r} is not in the session catalog",
                http_status=400,
            )
        candidate["region"] = {"label": entry["text"], "id": entry["key"], "implicit": False}
    if "edition_id" in changes:
        entry = _catalog_entry(catalog["editions"], changes["edition_id"])
        if entry is None:
            raise ValidationIOError(
                "bad_option",
                f"edition id {changes['edition_id']!r} is not in the session catalog",
                http_status=400,
            )
        candidate["edition"] = {"label": entry["text"], "id": entry["key"]}
    if "platform" in changes:
        candidate["platform"] = changes["platform"]

    candidate["fingerprint"] = candidate_fingerprint(candidate)
    audit = candidate.get("operator_override")
    if not isinstance(audit, dict) or "original" not in audit:
        # First override: freeze the matcher's original pick forever.
        candidate["operator_override"] = {"by": by, "at": now, "via": "admin-page", "original": original}
    else:
        candidate["operator_override"] = {**audit, "by": by, "at": now, "via": "admin-page"}
    return True


def apply_overrides_and_validate(
    run_dir: Path,
    payload: dict[str, Any],
    *,
    repo_root: Path,
    log_dir: Path | None = None,
    clock=_utc_now_iso,
    created_offer_ids=None,
) -> dict[str, Any]:
    """Save operator decisions: rewrite candidates, validation, approved (triple).

    ``created_offer_ids`` — offers of this run already created on AKS: any
    decision that approves one is refused whole (``already_created``), re-adding
    is impossible from the page.

    Raises :class:`ValidationIOError` (never partially honored — any refusal
    happens before the first write, and a failure between writes leaves a
    triple the submitter refuses).
    """

    validated_by = str(payload.get("validated_by", "")).strip()
    if not validated_by:
        raise ValidationIOError(
            "missing_validated_by", "validated_by is required", http_status=400
        )
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ValidationIOError("bad_request", "decisions must be a list", http_status=400)

    candidates_path = run_file(run_dir, "candidates.json")
    if not candidates_path.is_file():
        raise ValidationIOError(
            "no_candidates", "candidates.json absent — run not matched", http_status=404
        )
    current_sha = sha256_file(candidates_path)
    if payload.get("candidates_sha256") != current_sha:
        raise ValidationIOError(
            "stale_candidates",
            "les candidats ont changé depuis le chargement de la page — rechargez le run",
        )
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise ValidationIOError("bad_candidates", "candidates.json is not a list", http_status=500)

    by_fingerprint: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        by_fingerprint[candidate_fingerprint(candidate)] = candidate

    created_set = frozenset(str(offer_id) for offer_id in (created_offer_ids or ()))
    already_created: list[str] = []
    seen: set[str] = set()
    approve_by_fp: dict[str, bool] = {}
    overrides: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        fingerprint = decision.get("fingerprint")
        if fingerprint not in by_fingerprint:
            raise ValidationIOError(
                "unknown_fingerprint",
                f"decision references a candidate not in the current set: {fingerprint!r}",
                http_status=400,
            )
        if fingerprint in seen:
            raise ValidationIOError(
                "duplicate_decision",
                f"two decisions for the same candidate: {fingerprint!r}",
                http_status=400,
            )
        seen.add(fingerprint)
        approve_by_fp[fingerprint] = bool(decision.get("approve"))
        offer_id = str(by_fingerprint[fingerprint]["offer"]["offer_id"])
        if approve_by_fp[fingerprint] and offer_id in created_set:
            already_created.append(offer_id)
        override = decision.get("override")
        if override:
            if not isinstance(override, dict):
                raise ValidationIOError(
                    "bad_override", "override must be an object", http_status=400
                )
            overrides[fingerprint] = override

    if already_created:
        raise ValidationIOError(
            "already_created",
            "offre(s) déjà ajoutée(s) sur AKS — ré-approbation refusée : "
            + ", ".join(sorted(already_created)),
        )

    catalog = load_catalog_options(run_dir)
    now = clock()
    changed: list[dict[str, Any]] = []
    for old_fingerprint, override in overrides.items():
        candidate = by_fingerprint[old_fingerprint]
        if _apply_override(candidate, override, catalog, by=validated_by, now=now):
            new_fingerprint = candidate_fingerprint(candidate)
            changed.append(
                {
                    "offer_id": candidate["offer"]["offer_id"],
                    "old_fingerprint": old_fingerprint,
                    "new_fingerprint": new_fingerprint,
                    "fields": sorted(set(override)),
                }
            )
            approve_by_fp[new_fingerprint] = approve_by_fp.pop(old_fingerprint)

    fingerprints = [candidate_fingerprint(c) for c in candidates]
    duplicates = {fp for fp in fingerprints if fingerprints.count(fp) > 1}
    if duplicates:
        raise ValidationIOError(
            "duplicate_fingerprint",
            f"overrides make two candidates identical: {sorted(duplicates)}",
            http_status=400,
        )

    # From here on we write. Drop any stale approval first so a failure below
    # can never leave a green-looking but outdated approved.json behind.
    approved_path = run_file(run_dir, "approved.json")
    if approved_path.is_file():
        approved_path.unlink()

    _write_atomic(candidates_path, json.dumps(candidates, indent=2))

    validation = validation_template(candidates, run_id=run_dir.name, clock=clock)
    for entry in validation["candidates"]:
        entry["approve"] = approve_by_fp.get(entry["fingerprint"], False)
    validation["validated_by"] = validated_by
    validation["validated_at"] = now
    validation_path = run_file(run_dir, "validation.json")
    _write_atomic(validation_path, json.dumps(validation, indent=2))

    check = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "04_validate.py"),
            "check",
            str(candidates_path),
            str(validation_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    try:
        check_output = json.loads(check.stdout)
    except json.JSONDecodeError:
        check_output = {"raw": check.stdout, "stderr": check.stderr}
    if check.returncode != 0:
        raise ValidationIOError(
            "check_failed",
            f"04_validate.py check refused the validation (exit {check.returncode})",
            detail=check_output,
        )

    # Belt and braces: re-verify the just-written triple with the same code
    # path the submitter uses.
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    try:
        verify_approved_against_source(
            approved, validation, candidates, expected_run_id=run_dir.name
        )
    except ValidationError as exc:
        raise ValidationIOError("selfcheck_failed", str(exc), http_status=500) from exc

    logger = RunLogger(run_dir.name, log_dir=log_dir or (repo_root / "logs"), clock=clock)
    for change in changed:
        logger.log("operator_override", via="admin-page", by=validated_by, **change)
    logger.log(
        "validation_saved",
        via="admin-page",
        validated_by=validated_by,
        approved=len(approved),
        total=len(candidates),
        overrides=len(changed),
    )

    return {
        "approved_count": len(approved),
        "candidates_sha256": sha256_file(candidates_path),
        "overrides": changed,
        "check_output": check_output,
    }
