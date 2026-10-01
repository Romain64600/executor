"""Price check — the first-price monitor's reports, read and decided from the admin page.

The price-check monitor (its own repository, systemd unit ``price-check``, runs as root)
checks the first offer of every AllKeyShop page it follows. After every pass it writes
``reports.json`` into a shared directory (``/var/lib/price-check``, root:debian, mode 2775):
every SUSPECT, À VÉRIFIER or NON VÉRIFIABLE offer with its AllKeyShop URL, its merchant URL
and its reason (Romain, 2026-10-01: « ce rapport interactif de price check devrait être dans
l'admin »).

The admin READS that file as is and APPENDS the operator's decisions to ``decisions.jsonl``
in the same directory, one JSON line per decision; the monitor re-reads it before each pass
and the last line per offer wins. Nothing else is written: no page is opened, no AKS offer
is touched, no message is sent. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path("/var/lib/price-check")
REPORTS_FILE = "reports.json"
DECISIONS_FILE = "decisions.jsonl"
# The decisions the monitor understands (price_check.DECISIONS). reports.json carries them;
# this copy only serves an export written before it did.
DEFAULT_DECISIONS = {
    "vrai": "Vrai positif : alerter",
    "faux": "Faux positif : ne pas alerter",
    "a_discuter": "À discuter",
}
MAX_NOTE = 1000
OFFER_ID = re.compile(r"^[0-9]{1,20}$")
_APPEND_LOCK = threading.Lock()  # one line at a time from this process (ThreadingHTTPServer)


class PriceCheckError(Exception):
    """A refused read or decision. ``code`` machine-readable, ``message`` verbatim."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_export(directory: Path) -> tuple[dict[str, Any], float]:
    """reports.json and its mtime — fail-closed: a missing or broken export is an error
    the page shows, never an empty list that would read as « nothing to check »."""

    path = directory / REPORTS_FILE
    try:
        raw = path.read_bytes()
        mtime = path.stat().st_mtime
    except FileNotFoundError as exc:
        raise PriceCheckError(
            "no_reports",
            f"{path} absent — le moniteur price-check n'a encore rien exporté "
            "(PRICE_CHECK_REPORTS_DIR dans son .env)",
            http_status=404) from exc
    except OSError as exc:
        raise PriceCheckError("reports_unreadable", f"{path} illisible : {exc}",
                              http_status=500) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PriceCheckError("bad_reports", f"{path} n'est pas un JSON valide : {exc}",
                              http_status=500) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("reports"), list):
        raise PriceCheckError("bad_reports", f"{path} : liste « reports » absente",
                              http_status=500)
    return payload, mtime


def _decision_labels(payload: dict[str, Any]) -> dict[str, str]:
    labels = payload.get("decisions")
    if isinstance(labels, dict) and labels and all(
            isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
        return labels
    return dict(DEFAULT_DECISIONS)


def read_decisions(directory: Path, allowed) -> dict[str, list[dict[str, Any]]]:
    """Every decision per offer, in file order (the last one stands). A line the monitor
    would ignore (unreadable JSON, unknown decision, bad offer id) is ignored here too, so
    the page never shows a decision the monitor does not apply."""

    history: dict[str, list[dict[str, Any]]] = {}
    path = directory / DECISIONS_FILE
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(item, dict):
                    continue
                offer = str(item.get("offer", ""))
                decision = item.get("decision")
                if OFFER_ID.match(offer) and isinstance(decision, str) and decision in allowed:
                    history.setdefault(offer, []).append(
                        {k: item.get(k) for k in ("decision", "note", "by", "at")})
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PriceCheckError("decisions_unreadable", f"{path} illisible : {exc}",
                              http_status=500) from exc
    return history


def load_reports(directory: Path, *, now=time.time) -> dict[str, Any]:
    """The export, with each report's decision taken from decisions.jsonl when it is newer
    than the monitor's copy (the monitor only re-reads the file at its next pass, up to
    15 minutes later: the page must show a decision the moment it is recorded)."""

    payload, mtime = _read_export(directory)
    labels = _decision_labels(payload)
    history = read_decisions(directory, labels)
    reports = []
    for report in payload["reports"]:
        if not isinstance(report, dict):
            continue
        item = dict(report)
        past = history.get(str(item.get("offer", "")), [])
        if past:
            item["decision"] = past[-1]
        item["history"] = past
        # `seen` (epoch) = the start of the last pass where the offer was still the first
        # price. Measured against the export time, a long lag means it no longer leads.
        seen = item.get("seen")
        if isinstance(seen, (int, float)) and not isinstance(seen, bool):
            item["seen_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(seen))
            item["seen_lag_seconds"] = max(0, int(mtime - seen))
        reports.append(item)
    return {
        "dir": str(directory),
        "generated_at": payload.get("generated_at"),
        "age_seconds": max(0, int(now() - mtime)),
        "decisions": labels,
        "reports": reports,
    }


def record_decision(directory: Path, offer: Any, decision: Any, note: Any, *, by: str,
                    clock=_now_iso) -> dict[str, Any]:
    """Append one decision to decisions.jsonl, after checking it against the CURRENT export:
    a known offer, a decision the monitor understands, a short text note."""

    offer = str(offer if offer is not None else "").strip()
    if not OFFER_ID.match(offer):
        raise PriceCheckError("bad_offer", "offre invalide : un identifiant numérique est attendu")
    payload, _ = _read_export(directory)
    labels = _decision_labels(payload)
    if not isinstance(decision, str) or decision not in labels:
        raise PriceCheckError(
            "bad_decision", f"décision inconnue : {decision!r} (attendu : {', '.join(labels)})")
    if not any(isinstance(r, dict) and str(r.get("offer", "")) == offer
               for r in payload["reports"]):
        raise PriceCheckError(
            "unknown_offer", f"l'offre {offer} n'est pas dans {REPORTS_FILE}", http_status=404)
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise PriceCheckError("bad_note", "la note doit être un texte")
    note = note.strip()
    if len(note) > MAX_NOTE:
        raise PriceCheckError("bad_note",
                              f"note trop longue ({len(note)} caractères, {MAX_NOTE} au plus)")
    entry = {"offer": offer, "decision": decision, "note": note, "by": by, "at": clock()}
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    path = directory / DECISIONS_FILE
    with _APPEND_LOCK:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o664)
        except OSError as exc:
            raise PriceCheckError("decisions_unwritable", f"{path} : écriture impossible : {exc}",
                                  http_status=500) from exc
        try:
            view = memoryview(line)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
    return entry
