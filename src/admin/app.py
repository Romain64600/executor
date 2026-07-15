"""Admin page — HTTP layer (routing, CSRF guard, JSON error model, statics).

No business logic lives here: run access goes through ``src.admin.runs``, the
validation triple through ``src.admin.validation_io``, browser-driving runs
through ``src.admin.submit_manager``. The server binds to loopback and sits
behind nginx (HTTPS + basic auth); it still defends itself: custom-header CSRF
guard on every POST, per-run filename whitelist, security headers, no CORS.
Standard library only.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.admin.runs import (
    RunAccessError,
    list_runs,
    load_catalog_options,
    read_run_json,
    read_run_text,
    run_detail,
    run_file,
    safe_run_dir,
    sha256_file,
)
from src.admin.submit_manager import (
    CANARY_LIMIT,
    MODES,
    SubmitManager,
    SubmitStartError,
)
from src.admin.validation_io import ValidationIOError, apply_overrides_and_validate
from src.matcher import PLATFORM_LABEL, REGION_IDS
from src.validation import candidate_fingerprint

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
MAX_BODY_BYTES = 2 * 1024 * 1024
RUN_ROUTE = re.compile(r"^/api/runs/([^/]+)(/.*)?$")


class ApiError(Exception):
    def __init__(self, http_status: int, code: str, message: str, detail=None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.detail = detail


class AppState:
    """Shared state of the admin server (one per process)."""

    def __init__(
        self,
        repo_root: Path,
        *,
        runs_dir: Path | None = None,
        log_dir: Path | None = None,
        manager: SubmitManager | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.runs_dir = runs_dir or (repo_root / "runs")
        self.log_dir = log_dir or (repo_root / "logs")
        self.manager = manager or SubmitManager(repo_root, log_dir=self.log_dir)
        self.validation_lock = threading.Lock()


class AdminHandler(BaseHTTPRequestHandler):
    state: AppState  # bound by make_server()
    protocol_version = "HTTP/1.1"
    server_version = "aks-admin"
    sys_version = ""

    # -- plumbing ------------------------------------------------------------

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_error_json(self, status: int, code: str, message: str, detail=None) -> None:
        error = {"code": code, "message": message}
        if detail is not None:
            error["detail"] = detail
        self._send_json(status, {"error": error})

    def _json_body(self) -> dict:
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            raise ApiError(400, "bad_request", "Content-Length requis")
        size = int(length)
        if size > MAX_BODY_BYTES:
            raise ApiError(413, "too_large", "corps de requête trop grand")
        raw = self.rfile.read(size)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, "bad_json", f"JSON invalide: {exc}") from exc
        if not isinstance(body, dict):
            raise ApiError(400, "bad_json", "le corps doit être un objet JSON")
        return body

    def _check_csrf(self) -> None:
        if self.headers.get("X-AKS-Admin") != "1":
            raise ApiError(403, "csrf", "en-tête X-AKS-Admin: 1 requis")
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            raise ApiError(403, "csrf", "Content-Type application/json requis")
        origin = self.headers.get("Origin")
        if origin:
            if urlparse(origin).netloc != self.headers.get("Host", ""):
                raise ApiError(403, "csrf", "Origin ne correspond pas à Host")

    def _basic_user(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return None
        try:
            decoded = base64.b64decode(auth[6:], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
        return decoded.split(":", 1)[0] or None

    def _run_dir(self, run_id: str) -> Path:
        try:
            return safe_run_dir(self.state.runs_dir, run_id)
        except RunAccessError as exc:
            raise ApiError(404, "unknown_run", str(exc)) from exc

    # -- GET -------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        try:
            self._route_get()
        except ApiError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except Exception as exc:  # fail-closed: surfaced verbatim, never swallowed
            self._send_error_json(500, "internal", f"{type(exc).__name__}: {exc}")

    def _route_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        name = path.lstrip("/")
        if name in STATIC_FILES:
            return self._serve_static(name)

        if path == "/api/meta":
            return self._send_json(
                200,
                {
                    "platforms": sorted(REGION_IDS),
                    "platform_labels": PLATFORM_LABEL,
                    "modes": list(MODES),
                    "canary_limit": CANARY_LIMIT,
                },
            )
        if path == "/api/runs":
            runs = list_runs(self.state.runs_dir)
            for run in runs:
                try:
                    history = self.state.manager.submit_history(
                        safe_run_dir(self.state.runs_dir, run["run_id"])
                    )
                    run["created_count"] = sum(
                        1 for o in history.values() if o["status"] == "created"
                    )
                except (RunAccessError, OSError):
                    run["created_count"] = None
            return self._send_json(200, {"runs": runs})

        match = RUN_ROUTE.match(path)
        if match:
            run_dir = self._run_dir(match.group(1))
            sub = match.group(2) or ""
            if sub == "":
                detail = run_detail(run_dir)
                history = self.state.manager.submit_history(run_dir)
                detail["created_count"] = sum(
                    1 for o in history.values() if o["status"] == "created"
                )
                detail["failed_count"] = sum(
                    1 for o in history.values() if o["status"] == "failed"
                )
                return self._send_json(200, detail)
            if sub == "/report":
                report = read_run_text(run_dir, "report.txt")
                if report is None:
                    raise ApiError(404, "no_report", "report.txt absent")
                return self._send_bytes(200, "text/plain; charset=utf-8", report.encode("utf-8"))
            if sub == "/validation":
                return self._get_validation(run_dir)
            if sub == "/submit/status":
                query = parse_qs(parsed.query)
                try:
                    offset = int(query.get("offset", ["0"])[0])
                except ValueError:
                    offset = 0
                return self._send_json(200, self.state.manager.status(run_dir, offset=offset))

        raise ApiError(404, "not_found", f"route inconnue: {path}")

    def _serve_static(self, name: str) -> None:
        path = STATIC_DIR / name
        if not path.is_file():
            raise ApiError(404, "not_found", f"asset absent: {name}")
        self._send_bytes(200, STATIC_FILES[name], path.read_bytes())

    def _get_validation(self, run_dir: Path) -> None:
        candidates = read_run_json(run_dir, "candidates.json")
        if not isinstance(candidates, list):
            raise ApiError(404, "no_candidates", "candidates.json absent — run non matché")
        approved = read_run_json(run_dir, "approved.json")
        catalog = load_catalog_options(run_dir)
        self._send_json(
            200,
            {
                "run_id": run_dir.name,
                "candidates": candidates,
                "validation": read_run_json(run_dir, "validation.json"),
                "approved_fingerprints": (
                    [candidate_fingerprint(c) for c in approved]
                    if isinstance(approved, list)
                    else []
                ),
                "candidates_sha256": sha256_file(run_file(run_dir, "candidates.json")),
                "submit_history": self.state.manager.submit_history(run_dir),
                "catalog": {
                    "present": catalog is not None,
                    "regions": catalog["regions"] if catalog else [],
                    "editions": catalog["editions"] if catalog else [],
                },
            },
        )

    # -- POST --------------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        try:
            self._check_csrf()
            self._route_post()
        except ApiError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except ValidationIOError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except SubmitStartError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except Exception as exc:  # fail-closed: surfaced verbatim, never swallowed
            self._send_error_json(500, "internal", f"{type(exc).__name__}: {exc}")

    def _route_post(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/invariants/check":
            return self._post_invariants()

        match = RUN_ROUTE.match(path)
        if match:
            run_dir = self._run_dir(match.group(1))
            sub = match.group(2) or ""
            if sub == "/validation":
                return self._post_validation(run_dir)
            if sub == "/catalog":
                return self._post_catalog(run_dir)
            if sub == "/submit":
                return self._post_submit(run_dir)

        raise ApiError(404, "not_found", f"route inconnue: {path}")

    def _post_invariants(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(self.state.repo_root / "scripts" / "01_check_invariants.py")],
            cwd=str(self.state.repo_root),
            capture_output=True,
            text=True,
            timeout=180,
        )
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = {"raw": proc.stdout, "stderr": proc.stderr}
        self._send_json(200, {"exit_code": proc.returncode, "report": report})

    def _post_validation(self, run_dir: Path) -> None:
        body = self._json_body()
        with self.state.validation_lock:
            result = apply_overrides_and_validate(
                run_dir,
                body,
                repo_root=self.state.repo_root,
                log_dir=self.state.log_dir,
                created_offer_ids=self.state.manager.created_offers(run_dir),
            )
        self._send_json(200, result)

    def _post_catalog(self, run_dir: Path) -> None:
        body = self._json_body()
        by = str(body.get("by") or self._basic_user() or "operateur")
        result = self.state.manager.start_catalog(run_dir, by=by)
        self._send_json(200, result)

    def _post_submit(self, run_dir: Path) -> None:
        body = self._json_body()
        dry_run = bool(body.get("dry_run"))
        if not dry_run and body.get("confirm") != "GO":
            raise ApiError(
                400,
                "confirm_required",
                'un submit réel exige confirm: "GO" (le go explicite de l\'opérateur)',
            )
        limit = body.get("limit")
        if isinstance(limit, str):
            limit = int(limit) if limit.strip().isdigit() else limit
        if isinstance(limit, float) and limit.is_integer():
            limit = int(limit)
        by = str(body.get("by") or self._basic_user() or "operateur")
        result = self.state.manager.start_submit(
            run_dir,
            mode=str(body.get("mode", "safe")),
            limit=limit,
            dry_run=dry_run,
            by=by,
        )
        self._send_json(200, result)


def make_server(state: AppState, host: str = "127.0.0.1", port: int = 8650) -> ThreadingHTTPServer:
    handler = type("BoundAdminHandler", (AdminHandler,), {"state": state})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
