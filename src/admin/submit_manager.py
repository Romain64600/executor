"""Admin page — supervised, one-at-a-time submit/catalog runs.

The page's "Soumettre" click spawns the unmodified ``scripts/05_submit.py`` as
a subprocess and NEVER lets go of it (no fire-and-forget): a supervisor thread
waits for the exit code, parses ``submit_plan.json``, persists the outcome to
``runs/<id>/admin_submit.json`` and logs to the run's JSONL. One global lock
serializes everything that drives the browser (submit, dry-run, catalog).

The child lives in the admin service's cgroup: stopping/restarting the service
kills an in-flight submit rather than orphaning it — supervision is never
silently lost. On startup :meth:`SubmitManager.recover_orphans` marks the
state files of interrupted runs so the operator is told to inspect the feed.
Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.admin.runs import RunAccessError, derive_merchant_store, run_file
from src.run_log import RunLogger, redact
from src.validation import ValidationError, verify_approved_against_source

# Mirror of scripts/05_submit.py (R24). The script re-enforces all of this at
# argv level — these copies only give the operator the refusal before a spawn.
MODES = ("safe", "learning", "advanced")
CANARY_MODES = ("learning", "advanced")
CANARY_LIMIT = 1

STDOUT_TAIL_BYTES = 65536

# JSONL events worth streaming to the UI (guard_snapshot is huge — excluded).
UI_EVENTS = frozenset(
    {
        "feed_page",
        "feed_sweep",
        "feed_indexed",
        "submit_offer",
        "skip",
        "run_stopped",
        "pacing",
        "operator_override",
        "validation_saved",
        "admin_submit_started",
        "admin_submit_finished",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def tail_log_events(
    log_path: Path, offset: int, allowed: frozenset[str] = UI_EVENTS
) -> tuple[list[dict[str, Any]], int]:
    """New JSONL records since byte ``offset`` (complete lines only), re-redacted."""

    if not log_path.is_file():
        return [], 0
    size = log_path.stat().st_size
    if offset < 0 or offset > size:
        offset = 0
    events: list[dict[str, Any]] = []
    with open(log_path, "rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset
    for line in chunk[: end + 1].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if record.get("event") in allowed:
            events.append(redact(record))
    return events, offset + end + 1


class SubmitStartError(Exception):
    """A refused start. ``code`` is machine-readable, ``message`` verbatim."""

    def __init__(
        self, code: str, message: str, *, http_status: int = 409, detail: Any = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail


class SubmitManager:
    """Serialized, supervised runs of the real submitter script."""

    def __init__(
        self,
        repo_root: Path,
        *,
        log_dir: Path | None = None,
        submit_script: Path | None = None,
        python: str = sys.executable,
        clock=_utc_now_iso,
    ) -> None:
        self.repo_root = repo_root
        self.log_dir = log_dir or (repo_root / "logs")
        self.submit_script = submit_script or (repo_root / "scripts" / "05_submit.py")
        self.python = python
        self.clock = clock
        self._mutex = threading.Lock()
        self._active: dict[str, Any] | None = None
        self._orphans: list[dict[str, Any]] = []

    # -- startup -----------------------------------------------------------

    def recover_orphans(self, runs_dir: Path) -> list[dict[str, Any]]:
        """Reconcile state files left "running" by a previous server process."""

        found: list[dict[str, Any]] = []
        if not runs_dir.is_dir():
            return found
        for state_path in runs_dir.glob("*/admin_submit.json"):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if state.get("state") != "running":
                continue
            pid = state.get("pid")
            if isinstance(pid, int) and _pid_alive(pid):
                # Should not happen (cgroup kill), but fail closed: keep the
                # record and refuse any new run while this pid is alive.
                state["state"] = "orphaned"
                self._orphans.append({"run_id": state_path.parent.name, "pid": pid})
            else:
                state["state"] = "interrupted"
                state["note"] = (
                    "serveur admin redémarré pendant le run — inspecter le feed et "
                    "submit_plan.json avant toute reprise"
                )
            state["finished_at"] = self.clock()
            _write_atomic(state_path, json.dumps(state, indent=2))
            found.append({"run_id": state_path.parent.name, "state": state["state"]})
        return found

    # -- gates -------------------------------------------------------------

    def _ensure_free(self) -> None:
        still_alive = [o for o in self._orphans if _pid_alive(o["pid"])]
        self._orphans = still_alive
        if still_alive:
            raise SubmitStartError(
                "orphan_alive",
                f"un ancien process submit est encore vivant (pid {still_alive[0]['pid']}, "
                f"run {still_alive[0]['run_id']}) — aucun nouveau run tant qu'il existe",
            )
        if self._active is not None:
            raise SubmitStartError(
                "submit_in_progress",
                f"un run est déjà en cours ({self._active['kind']} sur "
                f"{self._active['run_id']}) — un seul à la fois",
            )

    @staticmethod
    def _check_mode_limit(mode: str, limit: int | None) -> None:
        if mode not in MODES:
            raise SubmitStartError("bad_mode", f"unknown mode: {mode!r}", http_status=400)
        if limit is not None:
            if not isinstance(limit, int) or limit < 1:
                raise SubmitStartError(
                    "bad_limit", f"limit must be a positive integer, got {limit!r}", http_status=400
                )
            if mode in CANARY_MODES and limit > CANARY_LIMIT:
                raise SubmitStartError(
                    "limit_widens_canary",
                    f"--mode {mode} est plafonné à un canary de {CANARY_LIMIT} offre "
                    f"(--limit {limit} l'élargirait). Utiliser --mode safe pour le lot complet.",
                    http_status=400,
                )

    def _verify_triple(self, run_dir: Path) -> list[dict[str, Any]]:
        approved_path = run_file(run_dir, "approved.json")
        candidates_path = run_file(run_dir, "candidates.json")
        validation_path = run_file(run_dir, "validation.json")
        if not (approved_path.is_file() and candidates_path.is_file() and validation_path.is_file()):
            raise SubmitStartError(
                "not_validated",
                "validation absente — candidates.json, validation.json et approved.json "
                "sont tous les trois requis avant un submit",
            )
        try:
            approved = json.loads(approved_path.read_text(encoding="utf-8"))
            verify_approved_against_source(
                approved,
                json.loads(validation_path.read_text(encoding="utf-8")),
                json.loads(candidates_path.read_text(encoding="utf-8")),
                expected_run_id=run_dir.name,
            )
        except (ValidationError, ValueError) as exc:
            raise SubmitStartError("revalidation_failed", str(exc)) from exc
        if not approved:
            raise SubmitStartError("nothing_approved", "approved.json est vide — rien à soumettre")
        return approved

    # -- start -------------------------------------------------------------

    def start_submit(
        self,
        run_dir: Path,
        *,
        mode: str,
        limit: int | None,
        dry_run: bool,
        by: str,
    ) -> dict[str, Any]:
        with self._mutex:
            self._ensure_free()
            self._check_mode_limit(mode, limit)
            approved = self._verify_triple(run_dir)
            try:
                merchant, store_id = derive_merchant_store(run_dir)
            except (RunAccessError, json.JSONDecodeError) as exc:
                raise SubmitStartError("store_ambiguous", str(exc)) from exc
            argv = [
                self.python,
                str(self.submit_script),
                str(run_file(run_dir, "approved.json")),
                "--merchant",
                merchant,
                "--store-id",
                store_id,
                "--mode",
                mode,
            ]
            if not dry_run:
                argv.append("--submit")
            if limit is not None:
                argv += ["--limit", str(limit)]
            return self._spawn(
                run_dir,
                kind="submit" if not dry_run else "dry_run",
                argv=argv,
                meta={"mode": mode, "limit": limit, "dry_run": dry_run, "by": by,
                      "approved_count": len(approved)},
            )

    def start_catalog(self, run_dir: Path, *, by: str) -> dict[str, Any]:
        """Fetch session_catalog.json (read-only stage, but it drives the browser)."""

        with self._mutex:
            self._ensure_free()
            try:
                merchant, store_id = derive_merchant_store(run_dir)
            except (RunAccessError, json.JSONDecodeError) as exc:
                raise SubmitStartError("store_ambiguous", str(exc)) from exc
            # --catalog only uses the approved path for its parent dir and runs
            # before approved.json is loaded — a fresh, unvalidated run is fine.
            argv = [
                self.python,
                str(self.submit_script),
                str(run_file(run_dir, "approved.json")),
                "--merchant",
                merchant,
                "--store-id",
                store_id,
                "--catalog",
            ]
            return self._spawn(run_dir, kind="catalog", argv=argv, meta={"by": by})

    def _spawn(
        self, run_dir: Path, *, kind: str, argv: list[str], meta: dict[str, Any]
    ) -> dict[str, Any]:
        proc = subprocess.Popen(
            argv,
            cwd=str(self.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        state = {
            "state": "running",
            "kind": kind,
            "pid": proc.pid,
            "argv": argv,
            "started_at": self.clock(),
            "finished_at": None,
            "exit_code": None,
            **meta,
        }
        _write_atomic(run_file(run_dir, "admin_submit.json"), json.dumps(state, indent=2))
        self._logger(run_dir).log("admin_submit_started", kind=kind, pid=proc.pid, argv=argv, **meta)
        thread = threading.Thread(
            target=self._supervise, args=(proc, run_dir, dict(state)), daemon=True
        )
        self._active = {"run_id": run_dir.name, "kind": kind, "pid": proc.pid, "thread": thread}
        thread.start()
        return {"started": True, "kind": kind, "pid": proc.pid, "argv": argv}

    # -- supervision ---------------------------------------------------------

    def _logger(self, run_dir: Path) -> RunLogger:
        return RunLogger(run_dir.name, log_dir=self.log_dir, clock=self.clock)

    def _supervise(self, proc: subprocess.Popen, run_dir: Path, state: dict[str, Any]) -> None:
        stdout, _ = proc.communicate()
        outcome_state = "done" if proc.returncode == 0 else "failed"
        state.update(
            state=outcome_state,
            exit_code=proc.returncode,
            finished_at=self.clock(),
            stdout_tail=(stdout or "")[-STDOUT_TAIL_BYTES:],
        )
        try:
            _write_atomic(run_file(run_dir, "admin_submit.json"), json.dumps(state, indent=2))
            self._logger(run_dir).log(
                "admin_submit_finished",
                kind=state["kind"],
                exit_code=proc.returncode,
                state=outcome_state,
            )
        finally:
            with self._mutex:
                self._active = None

    # -- status --------------------------------------------------------------

    def busy(self) -> dict[str, Any] | None:
        with self._mutex:
            if self._active is None:
                return None
            return {"run_id": self._active["run_id"], "kind": self._active["kind"]}

    def status(self, run_dir: Path, *, offset: int = 0) -> dict[str, Any]:
        """Current state for one run: state file + live log tail + submit plan."""

        state: dict[str, Any] = {"state": "idle"}
        state_path = run_file(run_dir, "admin_submit.json")
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {"state": "unknown", "error": "admin_submit.json illisible"}
        events, new_offset = tail_log_events(self.log_dir / f"{run_dir.name}.jsonl", offset)
        submit_plan = None
        plan_path = run_file(run_dir, "submit_plan.json")
        if plan_path.is_file() and state.get("state") != "running":
            try:
                submit_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                submit_plan = {"error": "submit_plan.json illisible"}
        return {
            **redact(state),
            "busy": self.busy(),
            "events": events,
            "offset": new_offset,
            "submit_plan": redact(submit_plan) if submit_plan is not None else None,
        }

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Test seam: block until the active run's supervisor finished."""

        with self._mutex:
            active = self._active
        if active is None:
            return True
        active["thread"].join(timeout)
        return not active["thread"].is_alive()
