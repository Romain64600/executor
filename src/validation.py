"""Stage 3 — Validation (read-only). The fail-closed gate before any submission.

No submission is allowed without a validation file that approves the EXACT current
candidates. A candidate is identified by a fingerprint
(``offer_id|aks_product_id|region_id|edition_id``), so a later re-match that changes
a region/edition invalidates a stale approval (skill rule S15: "a previous 'oui'
never authorizes a new/changed batch").

R45 (console keys, 2026-09-12): a candidate may carry several TARGETS (one AKS
console page + region bucket + edition per declared platform, ``candidates.json``
``"targets": [...]``). The fingerprint of a multi-target candidate appends
``|+<pid>:<rid>:<eid>,...`` for every target after the primary one, so a re-match
that adds/drops/changes a second platform invalidates the approval exactly like a
region change does. One target = the historical formula, byte-identical; a
candidates.json written before R45 (no ``targets`` key) is one target.

Works on candidate dicts (as written to ``candidates.json`` by the matcher), so it
has no heavy dependencies. Standard library only. Fail-closed: any problem raises
``ValidationError`` rather than silently approving.

Lot 2 (2026-09-15): the identity itself — target normalisation and the fingerprint
formula — is defined ONCE in ``src/candidate_contract.py``; ``candidate_fingerprint``
and ``candidate_targets`` below are thin aliases kept for their callers (scripts,
the admin I/O, the safe-auto sweep, tests) that translate the contract's refusals
into ``ValidationError``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from src import candidate_contract


class ValidationError(ValueError):
    """Raised when a validation file is missing, malformed, or stale."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _contract(call: Callable[..., Any], *args: Any) -> Any:
    """Run a ``candidate_contract`` helper, re-raising its refusal as
    ``ValidationError`` (same message — "malformed target entry (R45): …",
    "targets[0] does not mirror …") so every caller of this module is unchanged."""

    try:
        return call(*args)
    except candidate_contract.CandidateContractError as exc:
        raise ValidationError(str(exc)) from exc


def candidate_targets(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """The candidate's targets in the FLAT template shape
    ``{platform, aks_product_id, region_id, edition_id}`` (R45, 2026-09-12) —
    ``candidate_contract.template_targets``: a candidates.json without ``targets``
    (pre-R45), or with a single one, yields ONE target built from the PRIMARY
    fields (the validated identity — an operator override rewrites the primary,
    validation_io keeps ``targets[0]`` mirrored); several targets are flattened as
    they are, a malformed one refused (``ValidationError``)."""

    return _contract(candidate_contract.template_targets, candidate)


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    """Compute the fingerprint from fields, so it works on any candidates.json
    (robust to files written before the matcher stored a ``fingerprint`` key) —
    ``candidate_contract.fingerprint``, the ONE formula shared with
    ``matcher.Candidate.fingerprint`` and the admin page's ``app.js fp()``:
    ``offer_id|aks_product_id|region_id|edition_id`` for one target (or no
    ``targets`` key — pre-R45 file), plus ``|+pid:rid:eid,…`` over the EXTRA
    targets (R45). ``targets[0]`` must mirror the primary fields; a file where it
    does not, or a target with a missing / null id, raises ``ValidationError``
    rather than fingerprinting on a guess."""

    return _contract(candidate_contract.fingerprint, candidate)


def validation_template(
    candidate_dicts: Iterable[dict[str, Any]], run_id: str, clock=_utc_now_iso
) -> dict[str, Any]:
    """Build a validation template the operator fills in (approve + who/when)."""

    entries = []
    for candidate in candidate_dicts:
        entries.append(
            {
                "fingerprint": candidate_fingerprint(candidate),
                "offer_id": candidate["offer"]["offer_id"],
                "merchant_title": candidate["offer"]["name"],
                "aks_product_id": candidate["aks_product_id"],
                "aks_name": candidate["aks_name"],
                "platform": candidate["platform"],
                "region_id": candidate["region"]["id"],
                "edition_id": candidate["edition"]["id"],
                # R45 (2026-09-12): every target the approval covers (one for a PC /
                # single-platform key; several for a console key declared on
                # several platforms) — the operator sees what "approve" commits to.
                "targets": candidate_targets(candidate),
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

    by_fingerprint = {candidate_fingerprint(c): c for c in candidate_dicts}
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


def verify_approved_against_source(
    approved: list[dict[str, Any]],
    validation: dict[str, Any],
    candidate_dicts: Iterable[dict[str, Any]],
    *,
    expected_run_id: str,
) -> None:
    """Submit-time re-verification (Romain's audit P1, 2026-07-08).

    ``approved.json`` alone is never authority: re-derive the approval from
    candidates + validation (run_id, validated_by/at and fingerprints are all
    re-checked by ``load_validation``) and require the approved list to match
    the re-derivation exactly. A fabricated, hand-edited or stale approved.json
    raises ``ValidationError`` instead of loading.
    """

    rederived = load_validation(validation, candidate_dicts, expected_run_id=expected_run_id)
    if json.dumps(approved, sort_keys=True) != json.dumps(rederived, sort_keys=True):
        raise ValidationError(
            "approved.json does not match candidates.json + validation.json "
            "(stale, edited, or fabricated) — re-run 04_validate.py check"
        )
