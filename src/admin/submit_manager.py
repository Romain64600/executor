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
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.admin.runs import RunAccessError, derive_merchant_store, run_file, sha256_file
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
        "feed_extracted",
        "match_progress",
        "submit_offer",
        "skip",
        "run_stopped",
        "aborted",
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


def offer_submit_history(
    log_path: Path, submit_plan_path: Path | None = None
) -> dict[str, dict[str, Any]]:
    """Last known submit outcome per offer_id of a run.

    Distinguishes, per offer: ``created`` (confirmed added on AKS — sticky, a
    later "not in feed" failure never demotes it), ``failed`` (attempted, last
    blocker kept, still re-attemptable). Offers absent from the map were never
    attempted (pending — the UI's third state).

    Primary source: the append-only JSONL run log (``submit_offer`` events) —
    it survives ``submit_plan.json`` being overwritten by a later dry-run.
    Secondary: the current ``submit_plan.json`` (entries with ``submitted`` +
    confirmed ``post_save``). Corrupt lines are skipped: missing proof only
    means "not known created" — the submitter itself still fail-closes (a
    created offer is gone from the feed, its row can never be found again).
    """

    history: dict[str, dict[str, Any]] = {}
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") != "submit_offer" or not record.get("offer_id"):
                continue
            offer_id = str(record["offer_id"])
            attempts = history.get(offer_id, {}).get("attempts", 0) + 1
            if record.get("success") is True:
                history[offer_id] = {
                    "status": "created",
                    "at": record.get("ts"),
                    "post_save": record.get("post_save"),
                    "attempts": attempts,
                    "source": "log",
                }
            elif history.get(offer_id, {}).get("status") == "created":
                history[offer_id]["attempts"] = attempts
            else:
                history[offer_id] = {
                    "status": "failed",
                    "at": record.get("ts"),
                    "blocker": record.get("blocker"),
                    "attempts": attempts,
                    "source": "log",
                }
    if submit_plan_path is not None and submit_plan_path.is_file():
        try:
            plan = json.loads(submit_plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan = None
        entries = plan.get("plan") or [] if isinstance(plan, dict) else []
        for entry in entries:
            if entry.get("submitted") and entry.get("post_save") and entry.get("offer_id"):
                offer_id = str(entry["offer_id"])
                if history.get(offer_id, {}).get("status") != "created":
                    history[offer_id] = {
                        "status": "created",
                        "at": None,
                        "post_save": entry["post_save"],
                        "attempts": history.get(offer_id, {}).get("attempts", 1),
                        "source": "submit_plan",
                    }
    return history


def created_offer_ids(
    log_path: Path, submit_plan_path: Path | None = None
) -> dict[str, dict[str, Any]]:
    """Only the confirmed-created offers of :func:`offer_submit_history`."""

    return {
        offer_id: outcome
        for offer_id, outcome in offer_submit_history(log_path, submit_plan_path).items()
        if outcome["status"] == "created"
    }


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
        extract_script: Path | None = None,
        match_script: Path | None = None,
        python: str = sys.executable,
        clock=_utc_now_iso,
    ) -> None:
        self.repo_root = repo_root
        self.log_dir = log_dir or (repo_root / "logs")
        self.submit_script = submit_script or (repo_root / "scripts" / "05_submit.py")
        self.extract_script = extract_script or (repo_root / "scripts" / "02_extract_feed.py")
        self.match_script = match_script or (repo_root / "scripts" / "03_match.py")
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
    def _check_max_pages(max_pages: int | None) -> None:
        # Same default (40) as scripts/05_submit.py — the operator only needs
        # to raise it for a large feed (e.g. Difmark, 382 pages: the default
        # cap made the feed-index scan abort "coverage unproven" even though
        # the feed itself was healthy, 2026-07-17).
        if max_pages is not None and (not isinstance(max_pages, int) or max_pages < 1):
            raise SubmitStartError(
                "bad_max_pages", f"max_pages must be a positive integer, got {max_pages!r}",
                http_status=400,
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
        expected_approved_sha: str | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any]:
        with self._mutex:
            self._ensure_free()
            self._check_mode_limit(mode, limit)
            self._check_max_pages(max_pages)
            approved = self._verify_triple(run_dir)
            if not dry_run:
                # AS1 (audit 2026-07-17): the typed GO must be bound to the
                # exact batch the operator SAW when typing it. Between the
                # dialog render and this request, a concurrent validation
                # save (second operator, other tab) can regenerate
                # approved.json — the triple still verifies, but it is a
                # DIFFERENT batch. The client echoes the sha it displayed;
                # anything else refuses, never silently submits the new lot.
                current_sha = sha256_file(run_file(run_dir, "approved.json"))
                if not expected_approved_sha:
                    raise SubmitStartError(
                        "approved_sha_required",
                        "un submit réel exige approved_sha256 (l'identité du lot "
                        "affiché) — recharger la page",
                        http_status=400,
                    )
                if expected_approved_sha != current_sha:
                    raise SubmitStartError(
                        "approved_changed",
                        "approved.json a changé depuis l'affichage (validation "
                        "concurrente ?) — recharger, re-vérifier le lot, retaper GO",
                        http_status=409,
                    )
                # FC5 mirror (le 05_submit spawné re-vérifie) : un run matché
                # en mode canary ne soumet jamais en safe (lot complet).
                meta_path = run_file(run_dir, "match_meta.json")
                if meta_path.is_file():
                    try:
                        matched_mode = str(
                            json.loads(meta_path.read_text(encoding="utf-8"))
                            .get("data_entry_mode") or ""
                        )
                    except (json.JSONDecodeError, OSError) as exc:
                        raise SubmitStartError(
                            "match_meta_unreadable",
                            f"match_meta.json illisible — mode de match invérifiable (FC5): {exc}",
                        ) from exc
                    if matched_mode in CANARY_MODES and mode == "safe":
                        raise SubmitStartError(
                            "mode_widens_match",
                            f"run matché en mode {matched_mode!r} (canary) — un submit "
                            "'safe' (lot complet) est refusé : re-matcher en safe ou "
                            "soumettre dans le mode matché (FC5)",
                        )
            already = sorted(
                {str(c["offer"]["offer_id"]) for c in approved} & set(self.created_offers(run_dir))
            )
            if already:
                raise SubmitStartError(
                    "already_created",
                    f"{len(already)} offre(s) du lot approuvé déjà ajoutée(s) sur AKS "
                    f"({', '.join(already)}) — ré-ajout interdit : re-valider le run en "
                    "excluant ces offres",
                )
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
            if max_pages is not None:
                argv += ["--max-pages", str(max_pages)]
            return self._spawn(
                run_dir,
                kind="submit" if not dry_run else "dry_run",
                argv=argv,
                meta={"mode": mode, "limit": limit, "dry_run": dry_run, "by": by,
                      "approved_count": len(approved), "max_pages": max_pages},
            )

    def start_catalog(self, run_dir: Path, *, by: str, max_pages: int | None = None) -> dict[str, Any]:
        """Fetch session_catalog.json (read-only stage, but it drives the browser)."""

        with self._mutex:
            self._ensure_free()
            self._check_max_pages(max_pages)
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
            if max_pages is not None:
                argv += ["--max-pages", str(max_pages)]
            return self._spawn(
                run_dir, kind="catalog", argv=argv, meta={"by": by, "max_pages": max_pages}
            )

    def start_extract(
        self, merchant: str, store_id: str, *, by: str, page: str | None = None
    ) -> dict[str, Any]:
        """Stage 1 (read-only): create a fresh run and launch the extractor.

        Two modes (Romain 2026-07-21): ``page=None`` = **full shop** (sweep the
        whole feed, the extractor's default); ``page="N"`` (or ``"N-M"``) =
        **par page** (`--pages N`, one 100-offer page). The page-by-page cadence
        is the norm for a big feed — extract ONE page → match → report →
        validate → submit → next page — so a batch never sits stale while the
        feed re-imports (EXECUTOR_RULES §11).

        There is no existing run_dir yet — the operator types merchant +
        store_id and this mints a new run_id (``<timestamp>-<merchant slug>``),
        pre-creates the directory, then hands off to the unmodified
        `02_extract_feed.py` exactly like a manual CLI run would.
        """

        merchant = merchant.strip()
        store_id = store_id.strip()
        if not merchant:
            raise SubmitStartError("bad_merchant", "merchant requis", http_status=400)
        if not store_id.isdigit():
            raise SubmitStartError(
                "bad_store_id", f"store_id doit être numérique, reçu {store_id!r}",
                http_status=400,
            )
        if page is not None:
            page = str(page).strip()
            if not re.fullmatch(r"\d+(-\d+)?", page):
                raise SubmitStartError(
                    "bad_page", f"page invalide: {page!r} — attendu 'N' ou 'N-M'",
                    http_status=400,
                )
        with self._mutex:
            self._ensure_free()
            stamp = datetime.strptime(self.clock(), "%Y-%m-%dT%H:%M:%SZ").strftime("%Y%m%d-%H%M%S")
            slug = re.sub(r"[^a-z0-9]+", "-", merchant.lower()).strip("-") or "merchant"
            run_id = f"{stamp}-{slug}"
            run_dir = self.repo_root / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            argv = [
                self.python,
                str(self.extract_script),
                "--merchant",
                merchant,
                "--store-id",
                store_id,
                "--run-id",
                run_id,
            ]
            if page is not None:
                argv += ["--pages", page]
            return self._spawn(
                run_dir, kind="extract", argv=argv,
                meta={"merchant": merchant, "store_id": store_id, "by": by, "page": page},
            )

    def start_match(
        self, run_dir: Path, *, by: str, max_candidates: int | None = None
    ) -> dict[str, Any]:
        """Stage 3 (read-only): match an already-extracted run against AKS.

        Produces candidates.json / skipped.json / report.txt / match_meta.json —
        what fills the admin's validation table (Romain 2026-07-20: "un bouton
        pour cette étape"). Read-only HTTP (no browser/CDP, no browser lock),
        but serialized under the same one-run-at-a-time gate as everything else.
        Requires offers.json (the run must have been extracted first).
        """

        if not run_file(run_dir, "offers.json").is_file():
            raise SubmitStartError(
                "not_extracted",
                "offers.json absent — lancer d'abord l'extraction (stage 1)",
                http_status=409,
            )
        if max_candidates is not None and (
            not isinstance(max_candidates, int) or max_candidates < 1
        ):
            raise SubmitStartError(
                "bad_max_candidates",
                f"max_candidates doit être un entier positif, reçu {max_candidates!r}",
                http_status=400,
            )
        with self._mutex:
            self._ensure_free()
            argv = [
                self.python,
                str(self.match_script),
                str(run_file(run_dir, "offers.json")),
            ]
            if max_candidates is not None:
                argv += ["--max-candidates", str(max_candidates)]
            return self._spawn(
                run_dir, kind="match", argv=argv,
                meta={"by": by, "max_candidates": max_candidates},
            )

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
        try:
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
            self._logger(run_dir).log(
                "admin_submit_started", kind=kind, pid=proc.pid, argv=argv, **meta
            )
            thread = threading.Thread(
                target=self._supervise, args=(proc, run_dir, dict(state)), daemon=True
            )
            self._active = {"run_id": run_dir.name, "kind": kind, "pid": proc.pid, "thread": thread}
            thread.start()
        except BaseException:
            # AS2 (audit 2026-07-17): an OSError between Popen and the start of
            # supervision (state file write, log append, thread creation) used
            # to leave a LIVE child — possibly a real submit — running with no
            # supervisor: the one thing AGENTS.md forbids (fire-and-forget).
            # Kill it before propagating; it dies in its pre-flight (invariant
            # gate), long before any write.
            self._active = None
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            raise
        return {"started": True, "kind": kind, "pid": proc.pid, "argv": argv, "run_id": run_dir.name}

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

    def submit_history(self, run_dir: Path) -> dict[str, dict[str, Any]]:
        """Per-offer submit outcome (created / failed; absent = pending)."""

        return offer_submit_history(
            self.log_dir / f"{run_dir.name}.jsonl", run_file(run_dir, "submit_plan.json")
        )

    def created_offers(self, run_dir: Path) -> dict[str, dict[str, Any]]:
        """Offers of this run already created on AKS (never re-submittable)."""

        return created_offer_ids(
            self.log_dir / f"{run_dir.name}.jsonl", run_file(run_dir, "submit_plan.json")
        )

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
