"""Persistent ledger of RESOLVED sort offers, keyed by the stable merchant-URL
path (:func:`src.submitter._url_key`).

Since Romain stopped deleting the pending list before a merchant re-import
(2026-07-27), an offer keeps its identity across scans — so an offer we already
handled must not be re-attempted every cycle (the churn/phantom waste). The
**incremental** sort-move skips offers whose URL is already resolved here, so a
re-scan + re-batch only processes the DELTA (genuinely new offers).

``--full`` ignores this ledger — the OLD behaviour, for when delete-then-reimport
is re-enabled and every offer is genuinely fresh (ids rotate, urls re-appear).

Keyed by URL (not offer_id) so it is correct in BOTH modes: the URL path is the
stable identity whether or not ids rotate.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from src.submitter import _url_key

LEDGER_FILE = "sort_ledger.json"
# Outcomes that mean "we've dealt with this offer — don't re-attempt it in
# incremental mode": the move succeeded, the offer already left the list, or its
# URL now resolves to a DIFFERENT product (identity contradicted — never self-
# heals). Everything else is TRANSIENT and stays out of the ledger so the next
# incremental run retries it — a not-present/vanished row (a parallel operator
# reflowing the feed), a bulk/register/Apply glitch, a feed-error UNKNOWN, or an
# Apply-not-confirmed still-on-source offer. ``apply_not_confirmed`` is kept
# recognised (older ledgers may carry it) but is NO LONGER resolved: it always
# meant "retry" (see test_persists_and_counts_tries), and treating it as resolved
# was the transient-miss-skipped-forever bug the deferred window exposed.
RESOLVED_STATUSES = ("moved", "already_gone", "identity_blocked")


def ledger_path(root: Path | str) -> Path:
    return Path(root) / "state" / LEDGER_FILE


def load(root: Path | str) -> dict[str, Any]:
    path = ledger_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def resolved_keys(ledger: dict[str, Any]) -> set[str]:
    """URL keys the ledger considers resolved (skip them in incremental mode)."""

    return {k for k, v in ledger.items()
            if isinstance(v, dict) and v.get("status") in RESOLVED_STATUSES}


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def record(root: Path | str, entries: Iterable[dict[str, Any]], *, clock) -> dict[str, Any]:
    """Merge a run's outcomes into the ledger. Each entry: ``{url, offer_id,
    list_id, status}`` (status one of RESOLVED_STATUSES or anything else — only
    resolved statuses are skipped later). Keyed by ``_url_key``; entries without
    a URL are ignored (the ledger is URL-addressed)."""

    ledger = load(root)
    for entry in entries:
        key = _url_key(str(entry.get("url") or ""))
        if not key:
            continue
        prev = ledger.get(key) if isinstance(ledger.get(key), dict) else {}
        ledger[key] = {
            "status": entry.get("status"),
            "offer_id": entry.get("offer_id"),
            "list_id": entry.get("list_id"),
            "at": clock(),
            "tries": int(prev.get("tries", 0)) + 1,
        }
    _write_atomic(ledger_path(root), ledger)
    return ledger
