"""Who is driving a run, whatever launched it (2026-09-17).

Romain: « On peut faire en sorte d'avoir un monitoring sur l'admin même lorsqu'on lance en
ligne de commande ? ». The console could already SHOW any run — ``/submit/status`` reads the
run's artefacts from disk, not from the service's memory — but it could not DISCOVER one:
``SubmitManager`` only knows the children it spawned itself, so a sweep started from a
terminal was invisible, and the "Lancer" button did not even refuse while it ran.

This module is the missing discovery half: the orchestrator stamps a marker when it starts and
drops it when it leaves, and anyone can read it.

**Fail-closed by construction, and self-healing.** Liveness is decided by the PID, never by a
timestamp or a heuristic on file age: a marker whose process is gone is NOT active, so a
crashed or SIGKILLed run can never wedge the console forever, and a live one can never be
mistaken for stale however long it runs. A marker is only ever cleared by its own owner
(``run_id`` must match), so a late exit cannot erase the marker of the run that replaced it.
An unreadable or malformed marker reads as "nothing active" — the browser lock remains the
hard mutual exclusion, this is the readable label on top of it.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MARKER_NAME = "active_run.json"


def _path(repo_root: Path | str) -> Path:
    return Path(repo_root) / "state" / MARKER_NAME


def pid_alive(pid: int) -> bool:
    """True when the process exists. PermissionError = alive but not ours."""

    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


class ActiveRunExists(RuntimeError):
    """Un AUTRE run est vivant : on n'écrase pas son marqueur.

    AUDIT DU 2026-09-18. `write_marker` écrasait INCONDITIONNELLEMENT, alors que sa docstring
    ne promet que « overwrites any marker left by a dead process ». `scripts/05_submit.py` avait
    reçu la garde le matin même ; `scripts/10` appelait sans garde. Conséquence mesurée : un
    simple `--dry-run` lancé pendant un sweep de 30 h volait le marqueur, le sweep devenait
    INVISIBLE dans les consoles, et `_ensure_free` rouvrait le lancement depuis la console —
    deux runs concurrents sur le même onglet. Comme `clear_marker` n'efface que le sien, le
    marqueur du dry-run restait ensuite en place à sa mort. La garde vit ici, pas au point
    d'appel, pour que tout appelant futur en hérite."""

    def __init__(self, marker: dict[str, Any]) -> None:
        super().__init__(
            f"un run est déjà en cours ({marker.get('kind')} sur {marker.get('run_id')}, "
            f"pid {marker.get('pid')}) — attends sa fin ou arrête-le dans son terminal"
        )
        self.marker = marker


def write_marker(repo_root: Path | str, *, run_id: str, kind: str,
                 source: str = "cli", pid: int | None = None) -> dict[str, Any]:
    """Stamp the active run. Overwrites any marker left by a dead process.

    Refuse (``ActiveRunExists``) si un marqueur VIVANT porte un AUTRE ``run_id`` — un pid mort
    reste écrasé (l'auto-guérison documentée est préservée), et le MÊME ``run_id`` reste
    écrasable (relance explicite avec ``--run-id``)."""

    existing = read_marker(repo_root)
    if existing is not None and str(existing.get("run_id")) != str(run_id):
        raise ActiveRunExists(existing)

    marker = {
        "run_id": str(run_id),
        "kind": str(kind),
        "source": str(source),
        "pid": int(pid if pid is not None else os.getpid()),
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = _path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    tmp.replace(path)          # atomic: a reader never sees a half-written marker
    return marker


def read_marker(repo_root: Path | str) -> dict[str, Any] | None:
    """The ACTIVE run, or None. A marker whose process is dead is not active."""

    path = _path(repo_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    pid = raw.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return None
    if not raw.get("run_id"):
        return None
    return raw


def clear_marker(repo_root: Path | str, run_id: str | None = None) -> bool:
    """Drop the marker. With ``run_id``, only if it is ours — a run that exits late must
    never erase the marker of the run that replaced it. Returns True when removed."""

    path = _path(repo_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if run_id is not None and str(raw.get("run_id")) != str(run_id):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


@contextmanager
def active_run(repo_root: Path | str, *, run_id: str, kind: str,
               source: str = "cli") -> Iterator[dict[str, Any]]:
    """Hold the marker for the duration of the block, whatever the exit path."""

    marker = write_marker(repo_root, run_id=run_id, kind=kind, source=source)
    try:
        yield marker
    finally:
        clear_marker(repo_root, run_id=run_id)
