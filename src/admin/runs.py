"""Admin page — read-only run discovery and safe file access.

Every filesystem access of the admin server goes through this module: a run id
is only ever turned into a directory by :func:`safe_run_dir` (anti-traversal),
and only the whitelisted per-run artifacts of :data:`RUN_FILES` can be read.
No generic file service, no directory listing outside ``runs/``. Fail-closed:
anything suspicious raises :class:`RunAccessError` instead of guessing.
Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Run ids observed in runs/: "20260715-151202-gameseal", "2026-07-13_152243_g2a",
# "audit_20260713_142941". Underscore is part of the real vocabulary.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# The only per-run files the admin server will ever read.
RUN_FILES = frozenset(
    {
        "offers.json",
        "candidates.json",
        "skipped.json",
        "validation.template.json",
        "validation.json",
        "approved.json",
        "report.txt",
        "submit_plan.json",
        "submit_report.txt",
        "session_catalog.json",
        "admin_submit.json",
    }
)


class RunAccessError(ValueError):
    """Raised when a run id or file name is not safely resolvable."""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    """Resolve a run id to its directory, refusing anything that escapes runs/."""

    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise RunAccessError(f"invalid run id: {run_id!r}")
    base = runs_dir.resolve()
    candidate = (base / run_id).resolve()
    if candidate.parent != base or not candidate.is_relative_to(base):
        raise RunAccessError(f"run id escapes runs dir: {run_id!r}")
    if not candidate.is_dir():
        raise RunAccessError(f"unknown run: {run_id!r}")
    return candidate


def run_file(run_dir: Path, name: str) -> Path:
    """Path of a whitelisted run artifact (the file may or may not exist)."""

    if name not in RUN_FILES:
        raise RunAccessError(f"file not in run whitelist: {name!r}")
    return run_dir / name


def read_run_json(run_dir: Path, name: str) -> Any:
    """Load a whitelisted JSON artifact; None when the file is absent."""

    path = run_file(run_dir, name)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_run_text(run_dir: Path, name: str) -> str | None:
    """Read a whitelisted text artifact; None when the file is absent."""

    path = run_file(run_dir, name)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def sha256_file(path: Path) -> str | None:
    """Hex sha256 of a file, None when it does not exist."""

    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_merchant_store(run_dir: Path) -> tuple[str, str]:
    """Merchant + the single store_id of the run, from offers.json.

    Never typed by the operator: derived from the extractor's output and
    fail-closed on anything ambiguous (missing file, no offers, several
    distinct store ids).
    """

    offers = read_run_json(run_dir, "offers.json")
    if not isinstance(offers, dict):
        raise RunAccessError("offers.json missing — run not extracted")
    merchant = offers.get("merchant")
    if not merchant or not isinstance(merchant, str):
        raise RunAccessError("offers.json has no merchant")
    store_ids = {
        str(offer.get("store_id"))
        for offer in offers.get("offers", [])
        if offer.get("store_id") not in (None, "")
    }
    if len(store_ids) != 1:
        raise RunAccessError(
            f"store_id is not unique in offers.json: {sorted(store_ids) or 'none found'}"
        )
    return merchant, store_ids.pop()


def load_catalog_options(run_dir: Path) -> dict[str, list[dict[str, str]]] | None:
    """Region/edition choice lists from the run's session_catalog.json.

    Returns ``{"regions": [...], "editions": [...]}`` (each a ``master_options``
    list of ``{key, text}``) or None when the catalog is absent/unusable —
    the caller must then refuse overrides (no free-text ids, fail-closed).
    """

    catalog = read_run_json(run_dir, "session_catalog.json")
    if not isinstance(catalog, dict) or not catalog.get("ok"):
        return None
    try:
        regions = catalog["regions"]["master_options"]
        editions = catalog["editions"]["master_options"]
    except (KeyError, TypeError):
        return None
    if not regions or not editions:
        return None
    return {
        "regions": [{"key": str(o["key"]), "text": str(o["text"])} for o in regions],
        "editions": [{"key": str(o["key"]), "text": str(o["text"])} for o in editions],
    }


def _submit_plan_summary(plan: Any) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    return {
        "dry_run": plan.get("created") is None,
        "created": plan.get("created"),
        "write_attempts": plan.get("write_attempts"),
        "aborted": plan.get("aborted"),
        "stopped": plan.get("stopped"),
        "data_entry_mode": plan.get("data_entry_mode"),
        "limit": plan.get("limit"),
        "plan_count": len(plan.get("plan") or []),
    }


def _stage_status(run_dir: Path) -> dict[str, Any]:
    """Pipeline progress of one run, from artifact presence (never guessed)."""

    status: dict[str, Any] = {
        "extracted": run_file(run_dir, "offers.json").is_file(),
        "matched": run_file(run_dir, "candidates.json").is_file(),
        "candidates_count": None,
        "validated": False,
        "validated_by": None,
        "approved_count": None,
        "submit": None,
    }
    try:
        candidates = read_run_json(run_dir, "candidates.json")
        if isinstance(candidates, list):
            status["candidates_count"] = len(candidates)
        validation = read_run_json(run_dir, "validation.json")
        if isinstance(validation, dict):
            status["validated"] = True
            status["validated_by"] = validation.get("validated_by")
        approved = read_run_json(run_dir, "approved.json")
        if isinstance(approved, list):
            status["approved_count"] = len(approved)
        status["submit"] = _submit_plan_summary(read_run_json(run_dir, "submit_plan.json"))
    except (json.JSONDecodeError, OSError) as exc:
        # A corrupt artifact must not hide the run from the listing; it is
        # surfaced instead so the operator sees something is wrong.
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def list_runs(runs_dir: Path) -> list[dict[str, Any]]:
    """All run directories with their stage status, newest first."""

    runs: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        return runs
    for entry in runs_dir.iterdir():
        if not entry.is_dir() or not RUN_ID_RE.match(entry.name):
            continue
        record: dict[str, Any] = {
            "run_id": entry.name,
            "mtime": _iso(entry.stat().st_mtime),
        }
        try:
            merchant, store_id = derive_merchant_store(entry)
            record["merchant"] = merchant
            record["store_id"] = store_id
        except (RunAccessError, json.JSONDecodeError, OSError):
            record["merchant"] = None
            record["store_id"] = None
        record["stages"] = _stage_status(entry)
        runs.append(record)
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


def run_detail(run_dir: Path) -> dict[str, Any]:
    """Everything the UI needs to render one run's header and panels."""

    detail: dict[str, Any] = {
        "run_id": run_dir.name,
        "mtime": _iso(run_dir.stat().st_mtime),
        "merchant": None,
        "store_id": None,
        "store_id_error": None,
        "stages": _stage_status(run_dir),
        "candidates_sha256": sha256_file(run_file(run_dir, "candidates.json")),
        "catalog": {"present": False, "regions_count": 0, "editions_count": 0},
        "files": {},
    }
    try:
        detail["merchant"], detail["store_id"] = derive_merchant_store(run_dir)
    except (RunAccessError, json.JSONDecodeError, OSError) as exc:
        detail["store_id_error"] = str(exc)
    options = load_catalog_options(run_dir)
    if options is not None:
        detail["catalog"] = {
            "present": True,
            "regions_count": len(options["regions"]),
            "editions_count": len(options["editions"]),
        }
    for name in sorted(RUN_FILES):
        path = run_file(run_dir, name)
        if path.is_file():
            stat = path.stat()
            detail["files"][name] = {"size": stat.st_size, "mtime": _iso(stat.st_mtime)}
    return detail
