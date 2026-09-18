"""Candidate identity — the ONE definition shared by every stage (Lot 2, 2026-09-15).

Before this module the identity of a candidate (its target list and its validation
fingerprint) was written four times — ``matcher.Candidate.fingerprint`` /
``Target.to_dict``, ``validation.candidate_fingerprint`` / ``candidate_targets`` /
``_target_ids``, ``submitter.normalize_targets`` / ``_primary_target`` and the admin
page's ``app.js fp()`` / ``targetRegion()``. Romain's go (2026-09-15): centralise it.
The matcher, the validation gate, the submitter and the admin I/O now IMPORT this
module (it imports nothing from them — standard library only); ``app.js`` carries a
literal port, verified against the same examples
(``tests/fixtures/candidate_contract_examples.json``) by ``tests/test_candidate_contract.py``
and ``tests/js/candidate_contract_check.js``.

Shapes
------

**Candidate dict** (``candidates.json`` entry = ``matcher.Candidate.to_dict()``)::

    {
      "fingerprint": "...",                       # informational — always recomputed
      "offer": {"offer_id": "101050001", ...},    # NormalizedOffer.to_dict()
      "aks_product_id": "85104", "aks_url": "...", "aks_name": "Hades PS4",
      "platform": "PS4",
      "region": {"label": "Playstation Game Code GLOBAL", "id": "88", "implicit": true},
      "edition": {"label": "Standard", "id": "1"},
      "targets": [ <nested target>, ... ]         # R45; absent in files written before 2026-09-12
    }

The top-level ``aks_product_id`` / ``region`` / ``edition`` are the PRIMARY target —
the validated identity, what an operator override rewrites (``validation_io`` keeps
``targets[0]`` mirrored on them).

**Nested target** (``candidates.json`` ``targets[]`` entry = ``matcher.Target.to_dict()``,
``to_nested_target``)::

    {"platform": "PS5", "aks_product_id": "85105", "aks_url": "...", "aks_name": "Hades PS5",
     "region": {"label": "PS5", "id": "88ps5h"}, "edition": {"label": "Standard", "id": "1"}}

**Flat target** (the canonical form returned by ``normalize_targets`` — the
``submit_plan.json`` ``targets[]`` shape, ``TARGET_KEYS``)::

    {"platform": "PS5", "aks_product_id": "85105", "aks_url": "...", "aks_name": "Hades PS5",
     "region_label": "PS5", "region_id": "88ps5h", "edition_label": "Standard", "edition_id": "1"}

**Template target** (``validation.template.json`` ``targets[]`` = the flat target reduced
to ``TEMPLATE_TARGET_KEYS``)::

    {"platform": "PS5", "aks_product_id": "85105", "region_id": "88ps5h", "edition_id": "1"}

Rules (byte-identical to the four former implementations)
--------------------------------------------------------

- ``normalize_targets(candidate)``: no ``targets`` key, ``None``, a non-list, an empty
  list or a SINGLE entry (whatever it contains — ``[{}]``, ``["x"]``, a drifted hand
  edit) → ONE flat target built from the PRIMARY fields (the validated identity wins).
  Two or more entries → each flattened as written, nested (``region: {label, id}``) or
  flat (``region_id``) form, in order; an entry that is not a dict or whose
  ``aks_product_id`` / region id / edition id is MISSING or ``None`` raises
  ``CandidateContractError("malformed target entry (R45): …")`` — an identity is never
  guessed (review fix 2026-09-14: ``str(None)`` would stamp the literal "None" into a
  fingerprint, "null" in the page's mirror). Ids are returned as ``str``; labels,
  ``aks_url`` / ``aks_name`` / ``platform`` verbatim (a missing one is ``None``).
- ``fingerprint(candidate)``: ``offer_id|aks_product_id|region_id|edition_id`` from the
  primary fields for zero / one target — the historical formula, unchanged since
  Stage 3 — and, with several targets (R45), ``|+`` then ``pid:rid:eid`` of every EXTRA
  target joined by ``,`` (``…|+85105:88ps5h:1,26712:241:1``). ``targets[0]`` must mirror
  the primary ids or the candidate is refused (``CandidateContractError``) — the
  matcher's contract, a file where it does not hold is malformed. A missing primary key
  raises ``KeyError`` as before (callers such as the safe-auto sweep turn it into a
  stage error).
- ``MAX_TARGETS_PER_OFFER`` (3): Romain, 2026-09-14 — the modal takes "3 ou 4 pour le
  moment" targets; the submitter blocks a candidate with more BEFORE its row is located.

The refusals raise ``CandidateContractError`` (a ``ValueError``); ``validation`` re-raises
them as its ``ValidationError`` so its callers are unchanged.
"""

from __future__ import annotations

from typing import Any

# Hard cap on the targets of ONE candidate (Romain, 2026-09-14: the modal takes "3 ou 4
# pour le moment" targets). Enforced by the submitter (``_prepare`` blocks the entry with
# ``too_many_targets`` before any navigate / modal open); defined here so the identity
# and its bound live together.
MAX_TARGETS_PER_OFFER = 3

# The canonical FLAT target (submit_plan.json shape), in key order.
TARGET_KEYS = (
    "platform", "aks_product_id", "aks_url", "aks_name",
    "region_label", "region_id", "edition_label", "edition_id",
)
# The validation-template projection of a flat target.
TEMPLATE_TARGET_KEYS = ("platform", "aks_product_id", "region_id", "edition_id")


class CandidateContractError(ValueError):
    """A candidate dict that cannot carry an identity: a malformed ``targets[]`` entry
    (non-dict, or a missing / ``None`` id) or a ``targets[0]`` that contradicts the
    primary fields. Never guessed around — the caller refuses the candidate."""


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _nested_or_flat(target: dict[str, Any], kind: str) -> tuple[Any, Any]:
    """``(label, id)`` of ``region`` / ``edition`` from a nested dict (``{label, id}``)
    or the flat keys (``<kind>_label`` / ``<kind>_id``). The nested dict wins when present."""

    nested = target.get(kind)
    if isinstance(nested, dict):
        return nested.get("label"), nested.get("id")
    return target.get(f"{kind}_label"), target.get(f"{kind}_id")


def flatten_target(target: Any) -> dict[str, Any]:
    """One ``targets[]`` entry (nested or flat) → the canonical flat target.

    Raises :class:`CandidateContractError` for a non-dict entry or a missing / ``None``
    ``aks_product_id`` / region id / edition id. Ids come back as ``str``.
    """

    if not isinstance(target, dict):
        raise CandidateContractError(f"malformed target entry (R45): {target!r}")
    product_id = target.get("aks_product_id")
    region_label, region_id = _nested_or_flat(target, "region")
    edition_label, edition_id = _nested_or_flat(target, "edition")
    if product_id is None or region_id is None or edition_id is None:
        raise CandidateContractError(f"malformed target entry (R45): {target!r}")
    return {
        "platform": target.get("platform"),
        "aks_product_id": str(product_id),
        "aks_url": target.get("aks_url"),
        "aks_name": target.get("aks_name"),
        "region_label": region_label,
        "region_id": str(region_id),
        "edition_label": edition_label,
        "edition_id": str(edition_id),
    }


def target_ids(target: Any) -> tuple[str, str, str]:
    """``(aks_product_id, region_id, edition_id)`` of one ``targets[]`` entry — the
    identity part of :func:`flatten_target`, same refusals."""

    flat = flatten_target(target)
    return flat["aks_product_id"], flat["region_id"], flat["edition_id"]


def primary_ids(candidate: dict[str, Any]) -> tuple[str, str, str]:
    """``(aks_product_id, region_id, edition_id)`` of the PRIMARY fields, as ``str``.
    A missing key raises ``KeyError`` (a candidate without a primary has no identity).

    AUDIT DU 2026-09-18. Le refus « un id null n'entre jamais dans une identité », posé le
    2026-09-14 sur ``flatten_target``, ne couvrait que ``targets[1:]`` : l'empreinte
    interpolait les ids PRIMAIRES dans une f-string sans contrôle, si bien que le même dict
    était REFUSÉ en position 1 et ACCEPTÉ en position 0 — ``None`` y devenait la chaîne
    littérale « None », une identité stable et fausse. Le test doit porter sur les valeurs
    BRUTES, avant ``str()`` : après conversion il ne reste plus rien à détecter."""

    raw = (candidate["aks_product_id"], candidate["region"]["id"], candidate["edition"]["id"])
    if any(v is None or v == "" for v in raw):
        raise CandidateContractError(
            f"identité primaire incomplète (id nul) : {raw!r}")
    return (str(raw[0]), str(raw[1]), str(raw[2]))


def primary_target(candidate: dict[str, Any]) -> dict[str, Any]:
    """The primary fields as one canonical flat target (tolerant: a missing field is
    ``None`` — the submitter's catalog resolution blocks such an entry explicitly)."""

    region = candidate.get("region")
    region = region if isinstance(region, dict) else {}
    edition = candidate.get("edition")
    edition = edition if isinstance(edition, dict) else {}
    return {
        "platform": candidate.get("platform"),
        "aks_product_id": _str_or_none(candidate.get("aks_product_id")),
        "aks_url": candidate.get("aks_url"),
        "aks_name": candidate.get("aks_name"),
        "region_label": region.get("label"),
        "region_id": _str_or_none(region.get("id")),
        "edition_label": edition.get("label"),
        "edition_id": _str_or_none(edition.get("id")),
    }


def is_multi_target(candidate: dict[str, Any]) -> bool:
    """R45: more than one entry under ``candidate["targets"]``. A missing key, a
    non-list or a single entry is the historical one-target candidate. Never raises."""

    raw = candidate.get("targets")
    return isinstance(raw, list) and len(raw) > 1


def normalize_targets(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """The candidate's targets as canonical flat dicts, primary first (see the module
    docstring). Zero / one raw entry → the primary target; several → each flattened,
    a malformed one raising :class:`CandidateContractError` (never dropped, never
    guessed)."""

    raw = candidate.get("targets")
    if not isinstance(raw, list) or len(raw) <= 1:
        return [primary_target(candidate)]
    return [flatten_target(target) for target in raw]


def template_targets(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """:func:`normalize_targets` reduced to ``TEMPLATE_TARGET_KEYS`` — the
    ``validation.template.json`` ``targets[]`` shape."""

    return [{key: target[key] for key in TEMPLATE_TARGET_KEYS}
            for target in normalize_targets(candidate)]


def to_nested_target(flat: dict[str, Any]) -> dict[str, Any]:
    """A flat target → the nested ``candidates.json`` entry (``matcher.Target.to_dict``
    shape). Values verbatim — no refusal here, the flat side already carries them."""

    return {
        "platform": flat.get("platform"),
        "aks_product_id": flat.get("aks_product_id"),
        "aks_url": flat.get("aks_url"),
        "aks_name": flat.get("aks_name"),
        "region": {"label": flat.get("region_label"), "id": flat.get("region_id")},
        "edition": {"label": flat.get("edition_label"), "id": flat.get("edition_id")},
    }


def fingerprint(candidate: dict[str, Any]) -> str:
    """The exact submission identity Stage 3 keys on (module docstring, "Rules").

    Computed from the fields — never read from the candidate's own ``fingerprint`` key —
    so it works on any candidates.json (files written before the matcher stored the key,
    files rewritten by an operator override).
    """

    primary = (
        f"{candidate['offer']['offer_id']}|{candidate['aks_product_id']}"
        f"|{candidate['region']['id']}|{candidate['edition']['id']}"
    )
    raw = candidate.get("targets")
    if not isinstance(raw, list) or len(raw) <= 1:
        return primary
    if target_ids(raw[0]) != primary_ids(candidate):
        raise CandidateContractError(
            "targets[0] does not mirror the primary aks_product_id/region/edition "
            f"(R45) — re-run the match: {candidate['offer']['offer_id']}"
        )
    extra = ",".join(":".join(target_ids(target)) for target in raw[1:])
    return f"{primary}|+{extra}"
