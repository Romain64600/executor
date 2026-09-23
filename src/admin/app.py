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
import hashlib
import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.admin.runs import (
    RunAccessError,
    list_runs,
    list_sort_runs,
    load_catalog_options,
    read_run_json,
    read_run_text,
    run_detail,
    run_file,
    safe_run_dir,
    sha256_file,
)
from src.browser_lock import lock_status
from src import sort_sql_promoted
from src.admin.sort_sql_view import measure_pattern, sort_sql_payload
from src.admin.submit_manager import (
    BY_URLS_EVENTS,
    CANARY_LIMIT,
    MODES,
    SubmitManager,
    SubmitStartError,
    tail_log_events,
)
from src.admin.learning_io import (
    ANNOTATION_PLATFORMS,
    ANNOTATION_SCOPES,
    LearningError,
    group_skipped,
    learning_sha,
    list_catalog,
    load_annotations,
    save_annotations,
)
from src.admin.validation_io import ValidationIOError, apply_overrides_and_validate
from src.admin.login_manager import LoginError, LoginManager
from src.admin.auto_merchants import allowed_list as auto_allowed_list, rejection_reason
from src.aks_lists import LISTS as AKS_LISTS, PENDING_LIST_ID, is_blacklist_label
from src.extractor import FEED_LIST_BLACKLIST
from src.matcher import PLATFORM_LABEL, REGION_IDS
from src.validation import candidate_fingerprint


def _auto_groups() -> list[dict[str, object]]:
    """Les groupes de marchands, tels que la console doit les afficher : nom, membres et
    charge estimée. Lus du même module que le CLI (`src/merchant_groups.py`)."""

    from src.merchant_groups import GROUPS, PENDING_2026_09_21, group_targets

    out: list[dict[str, object]] = []
    for nom in sorted(GROUPS):
        try:
            cibles = group_targets(nom)
        except KeyError:
            continue                  # un groupe désynchronisé ne s'affiche pas
        out.append({
            "name": nom,
            "merchants": [{"name": m, "store_id": s} for m, s in cibles],
            "pending": sum(PENDING_2026_09_21.get(m, 0) for m, _ in cibles),
        })
    return out


STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    # Stage 8/9 — the dedicated "list sorting" triage console (its own tool).
    "sort.html": "text/html; charset=utf-8",
    "sort.js": "application/javascript; charset=utf-8",
    "sort.css": "text/css; charset=utf-8",
    # Safe-auto data entry — its own console (sweep a merchant, auto-add, recap).
    "auto.html": "text/html; charset=utf-8",
    "auto.js": "application/javascript; charset=utf-8",
    "auto.css": "text/css; charset=utf-8",
    # Stage 13 — le tri par SQL : les requêtes prêtes à copier dans phpMyAdmin.
    "sql.html": "text/html; charset=utf-8",
    "sql.js": "application/javascript; charset=utf-8",
    # Data entry from a list of AKS page URLs (search the feed, dry-run preview).
    "urls.html": "text/html; charset=utf-8",
    "urls.js": "application/javascript; charset=utf-8",
    "urls.css": "text/css; charset=utf-8",
}
MAX_BODY_BYTES = 2 * 1024 * 1024
RUN_ROUTE = re.compile(r"^/api/runs/([^/]+)(/.*)?$")


def _parse_int(value: Any) -> int | None:
    """Accept an int, a numeric string, or an integer-valued float from a
    JSON body — anything else (incl. None) passes through unchanged so the
    manager's own validation reports it, rather than swallowing a typo."""

    if isinstance(value, str):
        return int(value) if value.strip().isdigit() else value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _work_lists() -> list[dict[str, object]]:
    """Les listes AKS que la console peut proposer comme file de TRAVAIL.

    La file Pending (9) vient en tête — c'est le défaut. La Blacklist (8) et ses variantes
    sont écartées : on ne re-travaille pas des exclusions définitives (Romain, 2026-09-21),
    et le serveur les refuserait de toute façon. Le catalogue vient de `src/aks_lists.py`,
    la même source que le CLI : la console ne réinvente pas la liste des listes."""

    out: list[dict[str, object]] = [{"id": int(PENDING_LIST_ID), "label": "Pending offers"}]
    for entree in AKS_LISTS:
        try:
            lid = int(entree["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if lid == int(PENDING_LIST_ID) or lid == FEED_LIST_BLACKLIST:
            continue
        if is_blacklist_label(entree.get("label")):
            continue
        out.append({"id": lid, "label": str(entree.get("label") or lid)})
    return out


def _parse_list_id(body: dict[str, Any]) -> int:
    """La liste AKS demandée par la console — ``9`` (file Pending) par défaut.

    Romain, 2026-09-23 : « je voudrais pouvoir choisir la liste depuis l'admin. Par défaut on
    sera en pending offers, liste 9, mais je voudrais pouvoir en sélectionner d'autres. »

    Deux refus, pour les mêmes raisons qu'ailleurs sur ce chemin d'écriture :

    * une valeur qui n'est pas un ENTIER est refusée plutôt que devinée — la chaîne "9" d'un
      `<select>` mal câblé passerait, mais "neuf" ou "9; DROP" ne doivent jamais construire
      une URL de feed ;
    * la **liste 8 (Blacklist)** est interdite comme liste de travail (Romain, 2026-09-21 :
      les exclusions définitives ne se re-travaillent pas). L'extracteur la refuse déjà, mais
      le serveur doit le dire AVANT de lancer un balayage, pas après une page perdue.

    Le reste est laissé passer : la liste 30 (account), la 12 (pages à trier), etc. Celles-là
    sont des files de travail légitimes, et c'est tout l'objet de la demande."""

    brut = body.get("list", body.get("list_id"))
    if brut is None or brut == "":
        return int(PENDING_LIST_ID)
    try:
        val = int(str(brut).strip())
    except (TypeError, ValueError):
        raise ApiError(400, "bad_list",
                       f"list doit être un entier (9 = file Pending), reçu {brut!r}") from None
    if val < 1:
        raise ApiError(400, "bad_list", f"list doit être un entier positif, reçu {val}")
    if val == FEED_LIST_BLACKLIST:
        raise ApiError(400, "forbidden_list",
                       f"liste {FEED_LIST_BLACKLIST} (Blacklist) : interdite comme liste de "
                       "travail — les exclusions définitives ne se re-travaillent pas")
    return val


def _parse_consoles(body: dict[str, Any]) -> bool:
    """[R45] The admin body field ``consoles`` — ABSENT = ``True`` (Romain's decision « 1 »
    of 2026-09-15: consoles are taken into account by default everywhere; the UI checkbox
    is checked by default, unticking it sends ``false`` for a PC-only run). Only a JSON
    boolean is accepted: a string like ``"false"`` is refused (400) rather than guessed, so
    the mode of a real-write launch is never ambiguous."""

    value = body.get("consoles", True)
    if not isinstance(value, bool):
        raise ApiError(400, "bad_consoles", "consoles doit être un booléen JSON (true / false)")
    return value


def _sort_plan_digest(run_dir: Path) -> str:
    """A short content digest of the run's ``sort_plan.json``, or "" when it is absent.

    Computed from the FILE BYTES, so it needs no change to the plans already on disk and
    changes the moment the plan is re-scanned."""

    path = run_dir / "sort_plan.json"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


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
        self.login = LoginManager(repo_root)
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

    def _drain_body(self) -> None:
        """Read the FULL request body up front, before any routing/response.

        AS3 (audit 2026-07-17): handlers that never touched the body
        (`/api/invariants/check`) and every error path that responded before
        reading it left the unread bytes on the HTTP/1.1 keep-alive stream —
        the next request on that connection then parsed from mid-body. An
        over-limit body is refused WITHOUT reading it, and the connection is
        closed after the 413 (the only way to stay in sync)."""

        self._raw_body = None
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            return  # no body bytes on the wire — nothing to drain
        size = int(length)
        if size > MAX_BODY_BYTES:
            self.close_connection = True
            raise ApiError(413, "too_large", "corps de requête trop grand")
        self._raw_body = self.rfile.read(size)

    def _json_body(self) -> dict:
        if self._raw_body is None:
            raise ApiError(400, "bad_request", "Content-Length requis")
        try:
            body = json.loads(self._raw_body.decode("utf-8"))
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
            # [36] Fable re-audit 2026-09-06: a GET can carry a body (Content-Length). If
            # left unread it desyncs the HTTP/1.1 keep-alive stream — the next request
            # parses from mid-body. Drain it up front exactly as do_POST does (the 413/
            # close path lives in _drain_body).
            self._drain_body()
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
        if path in ("/tri", "/sort"):
            return self._serve_static("sort.html")
        if path in ("/auto", "/data-entry"):
            return self._serve_static("auto.html")
        if path in ("/sql", "/tri-sql"):
            return self._serve_static("sql.html")
        if path in ("/games", "/urls"):
            return self._serve_static("urls.html")
        if path == "/api/data-entry/recap":
            run = parse_qs(parsed.query).get("run", [""])[0]
            return self._get_data_entry_recap(run)
        if path == "/api/data-entry/by-urls/recap":
            run = parse_qs(parsed.query).get("run", [""])[0]
            return self._get_data_entry_recap(run, suffix="-by-urls")
        if path == "/api/data-entry/by-urls/submit/recap":
            run = parse_qs(parsed.query).get("run", [""])[0]
            return self._get_data_entry_recap(run, suffix="-by-urls-submit")
        if path == "/api/data-entry/by-urls/log":
            q = parse_qs(parsed.query)
            return self._get_by_urls_log(q.get("run", [""])[0], q.get("offset", ["0"])[0])
        if path == "/api/data-entry/merchants":
            # The safe-auto allowlist — the only merchants the UI may offer and
            # the server will accept for unvalidated auto entry.
            # Les GROUPES voyagent avec (Romain, 2026-09-22 : « je ne vois pas les groupes
            # A et B sur l'admin ») : la console ne les invente pas, elle les REÇOIT — même
            # source que le CLI, donc aucune dérive possible entre les deux.
            return self._send_json(200, {"merchants": auto_allowed_list(),
                                         "groups": _auto_groups(),
                                         "lists": _work_lists(),
                                         "default_list": int(PENDING_LIST_ID)})
        name = path.lstrip("/")
        if name in STATIC_FILES:
            return self._serve_static(name)

        if path == "/api/sort/sql":
            # Les requêtes de tri prêtes à copier, MESURÉES contre le dernier scan de tri.
            # Lecture seule de bout en bout : on rend du texte, Romain l'exécute lui-même
            # dans phpMyAdmin. Aucun accès base ici, aucun driver importé.
            return self._send_json(200, sort_sql_payload(
                self.state.runs_dir, parse_qs(parsed.query).get("run", [""])[0],
                repo_root=self.state.repo_root))

        if path == "/api/sort/runs":
            # C'est CETTE route que les deux consoles interrogent (sort.js refreshBusy,
            # auto.js fetchBusy) : "busy" y retombe sur le marqueur d'un run lancé en ligne
            # de commande, et "browser" dit si l'onglet unique est pris, lu SANS toucher au
            # verrou. La première version de ce champ était posée sur /api/runs, qu'aucune
            # des deux pages ne lit — corrigé le 2026-09-18 après vérification en production.
            return self._send_json(200, {"runs": list_sort_runs(self.state.runs_dir),
                                         "busy": self.state.manager.busy(),
                                         "browser": lock_status(self.state.repo_root)})

        if path == "/api/login/status":
            return self._send_json(200, self.state.login.status())

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
            # "browser" says whether the single CDP tab is taken and by whom, read
            # WITHOUT touching the lock (Romain 2026-09-17). "busy" already falls back
            # to the CLI run marker, so a terminal-launched run shows up like ours.
            return self._send_json(200, {"runs": runs, "busy": self.state.manager.busy(),
                                         "browser": lock_status(self.state.repo_root)})

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
            if sub == "/learning":
                return self._send_json(200, {
                    "run_id": run_dir.name,
                    "groups": group_skipped(run_dir),
                    "annotations": load_annotations(run_dir),
                    "lists": list_catalog(),
                    # D3/D4: single source of truth for the UI dropdowns.
                    "scopes": list(ANNOTATION_SCOPES),
                    "platforms": list(ANNOTATION_PLATFORMS),
                    # L2 (AS1 pattern): the client echoes this with its save so a
                    # concurrent write 409s instead of being silently clobbered.
                    "learning_sha256": learning_sha(run_dir),
                })
            if sub == "/sort":
                plan = read_run_json(run_dir, "sort_plan.json")
                if plan is None:
                    raise ApiError(404, "no_sort_plan", "sort_plan.json absent")
                # Attach the cumulative moved tally + the scan timestamp so the
                # console shows what each list actually received AND how stale the
                # plan is (a stale plan is mostly phantoms — churned/identity-drift).
                offers = read_run_json(run_dir, "offers.json") or {}
                plan = dict(plan,
                            moved_tally=read_run_json(run_dir, "sort_move_tally.json") or {},
                            fetched_at=offers.get("fetched_at"),
                            # Identity of the plan the operator is LOOKING AT. A real move
                            # must carry it back so the server can prove the two agree
                            # (audit de Romain 2026-09-16: switching scans quickly could
                            # leave plan A on screen while the move targeted run B).
                            plan_digest=_sort_plan_digest(run_dir))
                return self._send_json(200, plan)
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
        body = path.read_bytes()
        # Cache-bust: stamp app.js/style.css in index.html with the sha8 of
        # their current bytes. Even a tab open across a redeploy pulls the new
        # JS/CSS on its next reload (index.html itself is no-store). Deterministic
        # (content hash, no timestamps).
        if name in ("index.html", "sort.html", "auto.html", "urls.html"):
            body = self._version_assets(body)
        self._send_bytes(200, STATIC_FILES[name], body)

    def _version_assets(self, html: bytes) -> bytes:
        text = html.decode("utf-8")
        # Stamp any referenced JS/CSS asset with the sha8 of its bytes, so a tab
        # open across a redeploy pulls the new asset on its next reload (the HTML
        # itself is no-store). Covers both pages' assets; a no-op for those absent.
        for asset in ("app.js", "style.css", "sort.js", "sort.css", "auto.js", "auto.css",
                      "urls.js", "urls.css"):
            asset_path = STATIC_DIR / asset
            if not asset_path.is_file():
                continue
            tag = hashlib.sha256(asset_path.read_bytes()).hexdigest()[:8]
            text = text.replace(f'"{asset}"', f'"{asset}?v={tag}"')
        return text.encode("utf-8")

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
                # AS1 (audit 2026-07-17): the client echoes this sha with a
                # REAL submit so the typed GO is bound to the exact batch the
                # operator saw — a concurrent validation save changes the sha
                # and the submit refuses instead of sending the new batch.
                "approved_sha256": sha256_file(run_file(run_dir, "approved.json")),
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
        self._raw_body: bytes | None = None
        try:
            self._drain_body()  # AS3: body fully read before ANY response
            self._check_csrf()
            self._route_post()
        except ApiError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except ValidationIOError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except LearningError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except SubmitStartError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message, exc.detail)
        except LoginError as exc:
            self._send_error_json(exc.http_status, exc.code, exc.message)
        except Exception as exc:  # fail-closed: surfaced verbatim, never swallowed
            self._send_error_json(500, "internal", f"{type(exc).__name__}: {exc}")

    def _route_post(self) -> None:

        if self.path.split("?")[0] == "/api/sort/sql/measure":
            # Mesure d'un motif ÉDITÉ. Lecture seule : elle ne promeut rien.
            body = self._json_body()
            return self._send_json(200, measure_pattern(
                self.state.runs_dir, str(body.get("pattern", "")),
                str(body.get("target", "")), str(body.get("run_id") or "")))

        if self.path.split("?")[0] == "/api/sort/sql/promote":
            # Promotion d'un motif PROPOSÉ vers la liste. N'exécute rien : la liste sert à
            # être copiée dans phpMyAdmin. Le garde est dans sort_sql_promoted.promote —
            # vocabulaire du motif, liste connue, pas de doublon — et une erreur en ressort
            # en 400 explicite plutôt qu'en 500.
            body = self._json_body()
            action = str(body.get("action") or "promote").strip()
            try:
                if action == "dismiss":
                    entry = sort_sql_promoted.dismiss(
                        self.state.repo_root, pattern=str(body.get("pattern", "")),
                        target=str(body.get("target", "")),
                        by=str(body.get("by") or "console"))
                    return self._send_json(200, {"dismissed": entry})
                if action == "demote":
                    ok = sort_sql_promoted.demote(
                        self.state.repo_root, pattern=str(body.get("pattern", "")),
                        target=str(body.get("target", "")))
                    return self._send_json(200, {"demoted": ok})
                # Un motif ÉDITÉ rend la mesure affichée périmée : on la REFAIT ici, côté
                # serveur, et on refuse s'il vise désormais de vrais jeux. Sans ce contrôle,
                # éditer serait un moyen de contourner la seule garde qui protège cette voie.
                check = measure_pattern(self.state.runs_dir, str(body.get("pattern", "")),
                                        str(body.get("target", "")),
                                        str(body.get("run_id") or ""))
                # AUDIT DU 2026-09-18 — la porte ne se fermait que sur un collatéral NON NUL
                # d'une mesure RÉUSSIE. Une mesure impossible (pas de scan, scan illisible)
                # la désarmait entièrement : promouvoir sans mesure passait. Et un scan
                # TRONQUÉ rendait un collatéral nul par absence de données, indiscernable
                # d'un collatéral nul par sûreté. Une promotion est une règle PERMANENTE
                # qu'on ne peut pas prouver après coup — on exige donc une mesure complète.
                if not check.get("measured"):
                    raise ApiError(
                        400, "promotion_unmeasured",
                        "impossible de mesurer ce motif — "
                        f"{check.get('note') or 'aucun scan de tri exploitable'} ; "
                        "relance un scan de tri avant de promouvoir",
                        detail=check)
                if check.get("truncated"):
                    cov = check.get("coverage") or {}
                    raise ApiError(
                        400, "promotion_truncated",
                        f"mesuré sur un scan INCOMPLET ({cov.get('why') or 'couverture inconnue'}) : "
                        "le collatéral affiché ne prouve rien — relance un scan complet "
                        "(--max-pages 800) avant de promouvoir",
                        detail=check)
                if check.get("collateral"):
                    raise ApiError(
                        400, "promotion_collateral",
                        f"ce motif vise {check['collateral']} offre(s) que le routeur tient "
                        f"pour de vrais jeux — ex. "
                        f"{'; '.join(check.get('collateral_sample') or [])}",
                        detail=check)
                entry = sort_sql_promoted.promote(
                    self.state.repo_root,
                    pattern=str(body.get("pattern", "")),
                    target=str(body.get("target", "")),
                    by=str(body.get("by") or "console"),
                    run_id=str(body.get("run_id") or ""),
                    hits=body.get("hits") if isinstance(body.get("hits"), int) else None,
                    origin=body.get("origin") if isinstance(body.get("origin"), dict) else None)
            except ValueError as exc:
                raise ApiError(400, "bad_promotion", str(exc))
            return self._send_json(200, {"promoted": entry})
        path = urlparse(self.path).path

        if path == "/api/invariants/check":
            return self._post_invariants()
        if path == "/api/extract":
            return self._post_extract()
        if path == "/api/data-entry/auto":
            return self._post_data_entry_auto()
        if path == "/api/data-entry/auto/add-target":
            return self._post_data_entry_auto_add_target()
        if path == "/api/data-entry/by-urls":
            return self._post_data_entry_by_urls()
        if path == "/api/data-entry/by-urls/submit":
            return self._post_data_entry_by_urls_submit()
        if path == "/api/sort/stop":
            return self._send_json(200, self.state.manager.stop_active())
        if path == "/api/sort/scan":
            body = self._json_body()
            by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
            mp = _parse_int(body.get("max_pages"))
            result = self.state.manager.start_sort_scan(by=by, max_pages=mp if mp is not None else 800)
            return self._send_json(200, result)
        if path == "/api/login/cookies":
            # Re-auth by cookie transfer (AKS is social-login only). The cookie
            # VALUES are session secrets — passed STRAIGHT to the injector, never
            # logged/echoed/stored. Explicit operator submit only.
            cookies = self._json_body().get("cookies")
            by = str(self._basic_user() or "operateur")
            return self._send_json(200, self.state.login.apply_cookies(cookies, by=by))

        match = RUN_ROUTE.match(path)
        if match:
            run_dir = self._run_dir(match.group(1))
            sub = match.group(2) or ""
            if sub == "/validation":
                return self._post_validation(run_dir)
            if sub == "/learning":
                return self._post_learning(run_dir)
            if sub == "/match":
                return self._post_match(run_dir)
            if sub == "/catalog":
                return self._post_catalog(run_dir)
            if sub == "/submit":
                return self._post_submit(run_dir)
            if sub == "/sort/move":
                return self._post_sort_move(run_dir)

        raise ApiError(404, "not_found", f"route inconnue: {path}")

    def _post_sort_move(self, run_dir: Path) -> None:
        body = self._json_body()
        list_id = str(body.get("list_id") or "").strip()
        action = str(body.get("action") or "").strip()
        store = str(body.get("store") or "").strip() or None
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        if not list_id:
            raise ApiError(400, "list_required", "list_id requis")
        # A REAL move (canary/batch) needs the operator's explicit typed GO at the
        # API layer too (the console types it in the dialog) — a dry-run does not.
        if action in ("canary", "batch") and \
                str(body.get("confirm") or "").strip().upper() != "GO":
            raise ApiError(400, "go_required",
                           "un déplacement réel exige confirm=GO (le go explicite de l'opérateur)")
        # The operator approves WHAT IS ON SCREEN. A real move must name the plan it was
        # approved against, and the server proves it is still this run's current plan
        # (audit de Romain 2026-09-16: a slow response from a previously selected scan
        # could leave plan A displayed while the move posted to run B — « un canary peut
        # alors déplacer une offre d'un lot que tu n'as pas examiné »).
        if action in ("canary", "batch"):
            sent = str(body.get("plan_digest") or "").strip()
            current = _sort_plan_digest(run_dir)
            if not sent:
                raise ApiError(400, "plan_digest_required",
                               "un déplacement réel exige plan_digest (l'empreinte du plan "
                               "affiché, rendue par GET …/sort)")
            if not current or sent != current:
                raise ApiError(409, "plan_changed",
                               "le plan affiché n'est plus celui de ce scan (re-scanné, ou "
                               "un autre scan est à l'écran) — recharge avant de déplacer")
        result = self.state.manager.start_sort_move(
            run_dir, list_id=list_id, action=action, store=store, by=by,
            limit=_parse_int(body.get("limit")), batched=bool(body.get("batched")),
            deferred=bool(body.get("deferred")))
        self._send_json(200, result)

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
        # P2-9 / A3 (audit 2026-09-02): validated_by AUTHORIZES live offer creation — it
        # is the single approval gate, so it MUST be the AUTHENTICATED (nginx basic-auth)
        # user, never a client free-text field. With NO reliable authenticated identity
        # (Authorization header absent or malformed → _basic_user() None) there is no
        # operator to attribute the approval to: REFUSE fail-closed rather than trust a
        # client-supplied value (A3 — no unauthenticated validation fallback). Otherwise
        # the authenticated identity WINS over any body-supplied value.
        authed = self._basic_user()
        if not authed:
            raise ApiError(
                403, "authentication_required",
                "validation refusée : identité Basic authentifiée requise "
                "(l'approbation autorise une écriture live)")
        body["validated_by"] = authed
        # [15] Fable re-audit 2026-09-06 (defense in depth): refuse to regenerate the
        # triple while a run is ACTIVE on THIS run_dir. The submit path already snapshots
        # the sha-bound approved.json, so a concurrent save can never swap the SUBMITTED
        # batch; this stops the save from making that submit's live-triple re-verify
        # mismatch and fail-closed abort. The operator waits for the run to end, re-reads,
        # re-verifies and edits — no lost work, no silent swap.
        busy = self.state.manager.busy()
        if busy and busy.get("run_id") == run_dir.name:
            raise ApiError(
                409, "run_active",
                f"un run est en cours sur ce run ({busy.get('kind')}) — attends sa fin "
                "avant de re-valider (évite d'écraser le lot en cours de soumission)")
        with self.state.validation_lock:
            result = apply_overrides_and_validate(
                run_dir,
                body,
                repo_root=self.state.repo_root,
                log_dir=self.state.log_dir,
                created_offer_ids=self.state.manager.created_offers(run_dir),
            )
        # AS1: the freshly (re)generated batch's identity, for the GO binding.
        result["approved_sha256"] = sha256_file(run_file(run_dir, "approved.json"))
        self._send_json(200, result)

    def _post_data_entry_auto(self) -> None:
        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        raw = body.get("targets")
        targets: list[tuple[str, str]] = []
        # "Sweep de nuit" button (Romain 2026-09-16: « je voudrais un bouton pour lancer un
        # sweep sur tout les marchands whitelisted (sauf si ce sweep est deja en cours) »).
        # The target list is READ from the allowlist here, server-side, so the button can
        # never drift from it — same source as the CLI's --all-allowlisted. "Already
        # running" is enforced by the manager's _ensure_free (one run at a time, whatever
        # its kind), which answers 409 — the UI greys the button out on top of that.
        # Un GROUPE (Romain, 2026-09-21/22) : la console envoie son NOM, le serveur le
        # détend lui-même sur la liste blanche — exactement comme le bouton « sweep de
        # nuit ». Un client bricolé ne peut donc pas fabriquer une liste de cibles par ce
        # chemin, et la console ne peut pas dériver du CLI.
        group = body.get("group")
        if group is not None:
            if not isinstance(group, str) or not group.strip():
                raise ApiError(400, "bad_group", "group doit être un nom de groupe ('A', '2/4')")
            if raw:
                raise ApiError(400, "targets_conflict",
                               "group porte déjà ses marchands — n'envoie pas targets en plus")
            try:
                from src.merchant_groups import targets_for
                targets = list(targets_for(group))
            except KeyError as exc:
                raise ApiError(400, "unknown_group", str(exc)) from None
            if not targets:
                raise ApiError(500, "group_empty", f"groupe {group!r} vide — lancement refusé")
        all_allowlisted = body.get("all_allowlisted", False)
        if not isinstance(all_allowlisted, bool):
            # audit de Romain 2026-09-16 : la valeur de vérité Python acceptait la CHAÎNE
            # "false" et lançait les 14 marchands. Même exigence que ``consoles`` : un vrai
            # booléen JSON, jamais une valeur devinée — c'est un chemin d'écriture réelle.
            raise ApiError(400, "bad_all_allowlisted",
                           "all_allowlisted doit être un booléen JSON (true / false)")
        if all_allowlisted and group is not None:
            raise ApiError(400, "targets_conflict",
                           "all_allowlisted balaie déjà toute la liste blanche — pas avec group")
        if all_allowlisted:
            if raw:
                raise ApiError(400, "targets_conflict",
                               "all_allowlisted balaie déjà toute la liste blanche — "
                               "n'envoie pas targets en plus")
            targets = [(m["name"], m["store_id"]) for m in auto_allowed_list()]
            if not targets:
                raise ApiError(500, "allowlist_empty",
                               "liste blanche vide — lancement refusé (fail-closed)")
        elif group is not None:
            pass                      # déjà détendu ci-dessus
        elif isinstance(raw, list):
            for t in raw:
                if isinstance(t, dict):
                    targets.append((str(t.get("merchant", "")), str(t.get("store_id", ""))))
        if not targets:
            raise ApiError(400, "targets_required",
                           "au moins un marchand (targets: [{merchant, store_id}]) requis")
        # Authoritative allowlist gate: safe-auto writes without validation, so a
        # merchant absent from the suggested list is refused server-side even if
        # the UI is bypassed (fail-closed). Reject the whole batch on any miss.
        for merchant, store_id in targets:
            reason = rejection_reason(merchant, store_id)
            if reason is not None:
                raise ApiError(403, "merchant_not_allowed", reason)
        # [11] Fable re-audit 2026-09-06: safe-auto WRITES with no per-offer validation,
        # so it needs the same server-side typed GO every other real-write path enforces
        # (_post_sort_move, by-urls submit) — never launch a real sweep on a bare POST.
        if str(body.get("confirm") or "").strip().upper() != "GO":
            raise ApiError(400, "confirm_required",
                           "tape GO pour confirmer le sweep safe-auto réel")
        all_pages = body.get("all_pages", False)
        if not isinstance(all_pages, bool):
            # Même exigence que all_allowlisted / consoles : un vrai booléen JSON. La chaîne
            # "false" avait déjà lancé les 14 marchands une fois (audit du 2026-09-16).
            raise ApiError(400, "bad_all_pages",
                           "all_pages doit être un booléen JSON (true / false)")
        result = self.state.manager.start_data_entry_auto(
            targets, by=by, all_pages=all_pages,
            max_pages=_parse_int(body.get("max_pages")),
            start_page=_parse_int(body.get("start_page")),
            continue_on_halt=bool(body.get("continue_on_halt")),
            list_id=_parse_list_id(body),     # Romain 2026-09-23 : la liste est choisie ici
            consoles=_parse_consoles(body))   # [R45] default True (Romain 2026-09-15)
        self._send_json(200, result)

    def _post_data_entry_auto_add_target(self) -> None:
        """Ajoute UN marchand au sweep en cours (Romain 2026-09-19).

        Mêmes portes qu'un lancement, parce que c'est la même autorisation : un marchand
        ajouté écrit sur AKS SANS relecture humaine. La liste blanche fait autorité côté
        serveur (un client bricolé ne la contourne pas), et le GO tapé est exigé comme sur
        toutes les voies d'écriture réelle. Le manager, lui, vérifie qu'un sweep tourne
        vraiment — sinon l'ajout partirait dans le vide."""

        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")
        merchant = str(body.get("merchant") or "").strip()
        store_id = str(body.get("store_id") or "").strip()
        if not merchant or not store_id:
            raise ApiError(400, "target_required",
                           "merchant et store_id requis")
        reason = rejection_reason(merchant, store_id)
        if reason is not None:
            raise ApiError(403, "merchant_not_allowed", reason)
        if str(body.get("confirm") or "").strip().upper() != "GO":
            raise ApiError(400, "confirm_required",
                           "tape GO pour confirmer l'ajout au sweep en cours")
        self._send_json(200, self.state.manager.add_sweep_target(
            merchant, store_id, by=by,
            run_id=str(body.get("run_id") or "") or None))

    def _post_data_entry_by_urls(self) -> None:
        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        raw = body.get("urls")
        urls: list[str] = []
        if isinstance(raw, list):
            urls = [str(u).strip() for u in raw if str(u).strip()]
        elif isinstance(raw, str):
            urls = [u.strip() for u in re.split(r"[\s,]+", raw) if u.strip()]
        if not urls:
            raise ApiError(400, "urls_required",
                           "au moins une URL de page AKS (urls: [..]) requise")
        # Bound the blast: each URL fans out a search across the whole allowlist.
        if len(urls) > 200:
            raise ApiError(400, "too_many_urls",
                           f"{len(urls)} URLs — plafonné à 200 par run (relance en lots)")
        result = self.state.manager.start_data_entry_by_urls(
            urls, by=by, consoles=_parse_consoles(body))   # [R45] default True (2026-09-15)
        self._send_json(200, result)

    def _get_by_urls_log(self, run_id: str, offset_raw: str) -> None:
        # Read-only live tail of the by-urls run's JSONL log (offset-based, like the
        # submit console). run_id is validated to a real run dir (path-traversal
        # guarded) before we touch its log file.
        if not run_id:
            byurls = sorted(
                (p.name for p in self.state.runs_dir.glob("*-by-urls") if p.is_dir()),
                reverse=True)
            if not byurls:
                return self._send_json(200, {"events": [], "offset": 0, "run_id": None})
            run_id = byurls[0]
        run_dir = self._run_dir(run_id)   # raises 404 on a bogus/absent run id
        try:
            offset = max(0, int(offset_raw))
        except (TypeError, ValueError):
            offset = 0
        log_path = self.state.manager.log_dir / f"{run_dir.name}.jsonl"
        events, new_offset = tail_log_events(log_path, offset, allowed=BY_URLS_EVENTS)
        self._send_json(200, {"run_id": run_dir.name, "events": events, "offset": new_offset})

    def _get_data_entry_recap(self, run_id: str, *, suffix: str = "-auto") -> None:
        # Read-only: the live recap.json of a sweep run (no run_id → the newest
        # run of this kind: *-auto, or *-by-urls). Safe run-dir access via runs.py
        # (path traversal guarded).
        if not run_id:
            autos = sorted(
                (p.name for p in self.state.runs_dir.glob("*" + suffix) if p.is_dir()),
                reverse=True)
            if not autos:
                return self._send_json(200, {"recap": None})
            run_id = autos[0]
        run_dir = self._run_dir(run_id)
        recap_path = run_dir / "recap.json"
        # recap_sha256 binds the "Saisir" typed-GO to the EXACT preview shown (AS1):
        # the client echoes it, the manager re-checks the sha of the same recap.
        # P1 (2026-08-25 review): read ONCE and derive BOTH the displayed recap and
        # the bound sha from the same bytes — a concurrent dry-run flush must not be
        # able to hand the operator one generation on screen and another in the sha
        # (mirrors the manager's single-read; the old two reads — read_run_json then
        # sha256_file — could split across a flush).
        recap, sha = None, None
        if recap_path.is_file():
            try:
                raw = recap_path.read_bytes()
                recap = json.loads(raw)
                sha = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError):
                recap, sha = None, None
        self._send_json(200, {"run_id": run_id, "recap": recap, "recap_sha256": sha})

    def _post_data_entry_by_urls_submit(self) -> None:
        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        from_run = str(body.get("from_run") or "").strip()
        if not from_run:
            raise ApiError(400, "from_run_required", "from_run (l'aperçu à saisir) requis")
        # Server-side typed-GO — the same explicit-operator gate every other write path
        # enforces (parity with _post_submit / _post_sort_move); the sha binding alone
        # is anti-race, not an operator confirmation (adversarial review 2026-08-25).
        if str(body.get("confirm") or "").strip().upper() != "GO":
            raise ApiError(400, "confirm_required", "tape GO pour confirmer la saisie réelle")
        # SubmitStartError (bad/absent/aborted source, sha mismatch, busy) → do_POST
        # translates it to the right HTTP status. This is a WRITE — the manager binds
        # the GO to recap_sha256 (AS1) and spawns a supervised orchestrator.
        result = self.state.manager.start_data_entry_by_urls_submit(
            from_run, by=by, expected_recap_sha=body.get("recap_sha256"),
            consoles=_parse_consoles(body))   # [R45] default True (2026-09-15)
        self._send_json(200, result)

    def _post_catalog(self, run_dir: Path) -> None:
        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        result = self.state.manager.start_catalog(run_dir, by=by, max_pages=_parse_int(body.get("max_pages")))
        self._send_json(200, result)

    def _post_extract(self) -> None:
        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        raw_page = body.get("page")
        page = str(raw_page).strip() if raw_page not in (None, "") else None
        result = self.state.manager.start_extract(
            str(body.get("merchant", "")), str(body.get("store_id", "")), by=by, page=page,
        )
        self._send_json(200, result)

    def _post_match(self, run_dir: Path) -> None:
        body = self._json_body()
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        result = self.state.manager.start_match(
            run_dir, by=by, max_candidates=_parse_int(body.get("max_candidates")),
        )
        self._send_json(200, result)

    def _post_learning(self, run_dir: Path) -> None:
        body = self._json_body()
        # L11: the authenticated identity wins over the free-text field.
        by = str(self._basic_user() or body.get("by") or "operateur")
        base_sha = body.get("base_sha")
        if base_sha is not None and not isinstance(base_sha, str):
            raise ApiError(400, "bad_request", "base_sha doit être une chaîne ou null")
        # L2: same coarse lock as the validation writes — one run-artifact
        # writer at a time, the sha precondition handles cross-session races.
        with self.state.validation_lock:
            result = save_annotations(
                run_dir, body.get("annotations"), by=by, base_sha=base_sha
            )
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
        limit = _parse_int(body.get("limit"))
        by = str(self._basic_user() or body.get("by") or "operateur")  # [35] authed wins; body "by" cannot forge attribution
        approved_sha = body.get("approved_sha256")
        result = self.state.manager.start_submit(
            run_dir,
            mode=str(body.get("mode", "safe")),
            limit=limit,
            dry_run=dry_run,
            by=by,
            expected_approved_sha=str(approved_sha) if approved_sha else None,
            max_pages=_parse_int(body.get("max_pages")),
        )
        self._send_json(200, result)


def make_server(state: AppState, host: str = "127.0.0.1", port: int = 8650) -> ThreadingHTTPServer:
    handler = type("BoundAdminHandler", (AdminHandler,), {"state": state})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
