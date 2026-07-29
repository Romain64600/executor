"""Stage 0b login, driven from the admin page (Romain 2026-07-29).

Same login as ``scripts/00b_login.py`` — the SAME audited ``run_login`` control
flow (`src/login_session.py`) — but the 2FA code is supplied LIVE by the
operator through the web UI instead of a terminal ``getpass``. Every
LOGIN_SPEC.md rule is preserved, unchanged:

  * the password is read from the admin server's ENVIRONMENT only
    (``AKS_WP_PASSWORD``) — it never enters the UI, the API, a log, or a result;
  * the 2FA code is requested ONLY once ``run_login`` confirms the 2FA field is
    visible and ready (never pre-requested), passed straight into the trusted
    type, and never logged or stored;
  * ONE attempt each for the password and the 2FA code — a timeout waiting for
    the operator's code, or a wrong code, is a hard STOP, no retry loop;
  * it NEVER self-triggers — it runs only when the operator clicks "Se
    reconnecter" (the explicit go), exactly like ``--submit``.

``run_login`` runs in a daemon thread; its ``get_2fa_code`` callback blocks on a
one-slot queue that the ``/api/login/2fa`` route fills. The browser lock is held
for the whole attempt (a login must not race a submit/sort), and released when
the attempt ends.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from src.aks_env import OFFICIAL_CDP_ENDPOINT
from src.browser_lock import BrowserBusyError, browser_lock
from src.invariants import build_report
from src.login_session import LoginSession, run_login
from src.run_log import RunLogger
from src.step_guard import StepGuard

# Keys that must never appear in a status/result surfaced to the UI, as a
# belt-and-suspenders scrub on top of run_login never constructing them.
_SECRET_KEYS = ("password", "otp", "googleotp", "authcode", "2fa", "code", "user", "username")


class LoginError(RuntimeError):
    """A refusal the route turns into an HTTP error (mirrors SubmitStartError)."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _scrub(obj: Any) -> Any:
    """Drop any secret-ish keys before a result leaves the process (defensive —
    run_login's result never contains them, but status is operator-facing)."""

    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k.lower() not in _SECRET_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


class LoginManager:
    """Supervises ONE admin-driven login attempt at a time."""

    # How long we hold for the operator to type the 2FA code before failing
    # closed (one attempt — no re-prompt within the same run).
    TWOFA_WAIT_S = 180.0

    def __init__(
        self,
        repo_root: Path,
        *,
        endpoint: str = OFFICIAL_CDP_ENDPOINT,
        login_runner: Callable[..., dict[str, Any]] = run_login,
        session_factory: Callable[[str], Any] = LoginSession,
        report_fn: Callable[..., dict[str, Any]] = build_report,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.endpoint = endpoint
        self._login_runner = login_runner
        self._session_factory = session_factory
        self._report_fn = report_fn
        self._clock = clock
        self._mutex = threading.Lock()
        self._state = "idle"          # idle | running | awaiting_2fa | done
        self._result: dict[str, Any] | None = None
        self._code_q: "queue.Queue[str] | None" = None
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._by: str | None = None

    # -- queries -------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._mutex:
            return {
                "state": self._state,
                "result": _scrub(self._result) if self._result is not None else None,
                "started_at": self._started_at,
                "by": self._by,
                "awaiting_2fa": self._state == "awaiting_2fa",
                "busy": self._state in ("running", "awaiting_2fa"),
            }

    # -- actions -------------------------------------------------------------
    def start(self, *, by: str) -> dict[str, Any]:
        with self._mutex:
            if self._state in ("running", "awaiting_2fa"):
                raise LoginError("login_busy", "un login est déjà en cours", http_status=409)
            username = os.environ.get("AKS_WP_USER", "").strip()
            password = os.environ.get("AKS_WP_PASSWORD", "")
            if not username or not password:
                # Fail-closed BEFORE any browser action — distinct, actionable.
                self._state = "done"
                self._result = {"status": "aborted", "reason": (
                    "AKS_WP_USER / AKS_WP_PASSWORD absents de l'environnement du serveur "
                    "admin — ajoute-les au service aks-admin puis relance")}
                self._by = by
                raise LoginError("no_creds", self._result["reason"], http_status=400)
            self._code_q = queue.Queue(maxsize=1)
            self._state = "running"
            self._result = None
            self._by = by
            self._started_at = self._clock()
            self._thread = threading.Thread(
                target=self._run, args=(username, password), name="aks-login", daemon=True)
            self._thread.start()
            return {"started": True, "state": self._state}

    def submit_2fa(self, code: str) -> dict[str, Any]:
        with self._mutex:
            if self._state != "awaiting_2fa" or self._code_q is None:
                raise LoginError("no_2fa_wait", "aucun code 2FA attendu actuellement",
                                 http_status=409)
            q = self._code_q
        try:
            q.put_nowait(str(code or ""))
        except queue.Full:
            raise LoginError("already_submitted", "un code 2FA a déjà été soumis",
                             http_status=409)
        return {"accepted": True}

    # -- internals -----------------------------------------------------------
    def _get_2fa_code(self) -> str:
        """Called by run_login ONLY after the 2FA field is confirmed ready. Blocks
        for the operator's code (posted to /api/login/2fa); a timeout returns ""
        → run_login treats it as 2FA_EMPTY_CODE → hard STOP (never a re-prompt)."""

        with self._mutex:
            self._state = "awaiting_2fa"
            q = self._code_q
        if q is None:
            return ""
        try:
            return q.get(timeout=self.TWOFA_WAIT_S)
        except queue.Empty:
            return ""

    def _run(self, username: str, password: str) -> None:
        run_id = f"login-{int(self._clock())}"
        logger = RunLogger(run_id, log_dir=str(self.repo_root / "logs"))
        guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=1,
                          max_consecutive_failures=1)
        result: dict[str, Any]
        try:
            report = self._report_fn(endpoint=self.endpoint)
            if not (report.get("ok") and report.get("authoritative")):
                result = {"status": "aborted", "reason":
                          "invariants pas au vert/authoritative — login refusé"}
            else:
                with browser_lock(self.repo_root, label="admin_login"), \
                        self._session_factory(self.endpoint) as session:
                    result = self._login_runner(
                        session, username=username, password=password,
                        get_2fa_code=self._get_2fa_code, guard=guard,
                        run_id=run_id, logger=logger)
        except BrowserBusyError as exc:
            result = {"status": "aborted", "reason": f"navigateur occupé (submit/sort en cours ?): {exc}"}
        except Exception as exc:  # fail-closed: any error is a clean aborted result
            result = {"status": "aborted", "reason": f"login error: {type(exc).__name__}: {exc}"}
        finally:
            with self._mutex:
                self._result = _scrub(result if isinstance(result, dict) else {"status": "aborted"})
                self._state = "done"
                self._code_q = None  # drop the queue (and any unused code) immediately
