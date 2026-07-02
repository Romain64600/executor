"""Stage 3 — Validation (read-only). The fail-closed gate before any submission.

No submission is allowed without a validation file that approves the EXACT current
candidates. A candidate is identified by a fingerprint
(``offer_id|aks_product_id|region_id|edition_id``), so a later re-match that changes
a region/edition invalidates a stale approval (skill rule S15: "a previous 'oui'
never authorizes a new/changed batch").

Works on candidate dicts (as written to ``candidates.json`` by the matcher), so it
has no heavy dependencies. Standard library only. Fail-closed: any problem raises
``ValidationError`` rather than silently approving.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


class ValidationError(ValueError):
    """Raised when a validation file is missing, malformed, or stale."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validation_template(
    candidate_dicts: Iterable[dict[str, Any]], run_id: str, clock=_utc_now_iso
) -> dict[str, Any]:
    """Build a validation template the operator fills in (approve + who/when)."""

    entries = []
    for candidate in candidate_dicts:
        entries.append(
            {
                "fingerprint": candidate["fingerprint"],
                "offer_id": candidate["offer"]["offer_id"],
                "merchant_title": candidate["offer"]["name"],
                "aks_product_id": candidate["aks_product_id"],
                "aks_name": candidate["aks_name"],
                "platform": candidate["platform"],
                "region_id": candidate["region"]["id"],
                "edition_id": candidate["edition"]["id"],
                "approve": False,
            }
        )
    return {
        "run_id": run_id,
        "generated_at": clock(),
        "validated_by": "",
        "validated_at": "",
        "instructions": (
            "Set approve:true for the offers to submit, fill validated_by and "
            "validated_at, then run: 04_validate.py check <candidates.json> <this file>."
        ),
        "candidates": entries,
    }


def load_validation(
    data: dict[str, Any],
    candidate_dicts: Iterable[dict[str, Any]],
    *,
    expected_run_id: str,
) -> list[dict[str, Any]]:
    """Verify a filled validation file against the current candidates.

    Returns the approved candidate dicts. Fail-closed — raises if the file is for
    a different run, is missing who/when, or approves anything that is not an exact
    current candidate (the whole file is rejected, never partially honored).
    """

    if not isinstance(data, dict):
        raise ValidationError("validation file must be a JSON object")
    if data.get("run_id") != expected_run_id:
        raise ValidationError(
            f"run_id mismatch: file={data.get('run_id')!r} expected={expected_run_id!r}"
        )
    if not str(data.get("validated_by", "")).strip():
        raise ValidationError("validated_by is required")
    if not str(data.get("validated_at", "")).strip():
        raise ValidationError("validated_at is required")

    by_fingerprint = {c["fingerprint"]: c for c in candidate_dicts}
    approved: list[dict[str, Any]] = []
    for entry in data.get("candidates", []):
        if not entry.get("approve"):
            continue
        fingerprint = entry.get("fingerprint")
        if fingerprint not in by_fingerprint:
            raise ValidationError(
                f"approved candidate is not in the current candidate set (stale?): {fingerprint}"
            )
        approved.append(by_fingerprint[fingerprint])
    return approved
