"""La photo d'UNE machine de l'exécuteur, en lecture seule — l'onglet « Vue d'ensemble » (2026-09-30).

Romain : « Est-ce que tu penses qu'il serait bien, dans l'admin, d'avoir un onglet pour monitor
les logs des trois VPS en direct sur la même page ? », puis « Qu'on puisse voir si les serveurs
sont up, le type de tâche actuel, etc. », puis « Go pour l'onglet vue d'ensemble ».

Ce module rend UN dictionnaire JSON qui décrit la machine où il tourne : système (uptime, charge,
disque, mémoire, boot_id), version du code, services, admin joignable, la TÂCHE en cours dite en
français (« Balayage groupe A en boucle — passe 3, GOG page 12, saisie depuis 14:03 UTC »), les
20 derniers événements utiles de son journal, des alertes courtes, la dernière maintenance.

Deux lecteurs, un seul code :

* ``scripts/20_vps_snapshot.py`` l'imprime sur UNE ligne — c'est la commande FORCÉE de la clé ssh
  dédiée des autres VPS (``ops/VUE_D_ENSEMBLE.md``) : l'admin qui lit ne choisit jamais la
  commande exécutée ;
* l'admin local (``src/admin/overview.py``) l'appelle EN PROCESSUS, avec son propre ``busy()``
  au lieu d'un appel HTTP vers lui-même.

**Lecture seule, rapide, jamais une exception.** Rien n'est écrit, aucun verrou n'est pris (le
verrou navigateur est lu par son étiquette, comme ``lock_status``), aucun appel à AKS. Les trois
sondes lentes (git, systemctl, admin) partent en parallèle, chacune avec son délai : < 3 s
d'ordinaire, 6 s au pire — la liste des runs de l'admin (``/api/sort/runs``, qui parcourt tout
``runs/``) a plus de marge que les autres, sa joignabilité se lit sur ``/api/meta`` (revue adverse
du 2026-09-30). Chaque section qui échoue laisse son champ vide et écrit POURQUOI
dans ``errors`` — une photo partielle vaut mieux qu'une machine affichée « injoignable ».

**Aucun secret.** Les événements passent par ``src.run_log.redact`` (clés sensibles), puis par
un filtre de TEXTE (URL de webhook, cookies WordPress, en-têtes d'autorisation) : le journal ne
les contient déjà pas, c'est une ceinture en plus des bretelles. Les chaînes sont tronquées.

On relit les fichiers que le balayage et l'admin écrivent, EXACTEMENT comme ``auto.js`` et la
route recap les lisent (``src/sweep_loop.py`` pour la boucle et la passe courante,
``recap.json`` de la passe, ``current`` du marchand en cours, ``admin_submit.json`` du lancement,
le marqueur ``state/active_run.json`` quand l'admin ne répond pas).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from src import run_marker, sweep_loop
from src.run_log import redact

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
ADMIN_URL = "http://127.0.0.1:8650"
ADMIN_TIMEOUT_S = 2.5
# `/api/sort/runs` parcourt tout `runs/` et relit chaque `sort_plan.json` (≈ 1,1 s au repos pour
# 30 000 dossiers, davantage pendant un balayage) : plus de marge que les autres sondes — la
# maintenance lui en donne 20. 6 s au pire, dans les 10 s du ssh de la vue d'ensemble.
ADMIN_BUSY_TIMEOUT_S = 6.0
PROBE_TIMEOUT_S = 2.5
# Les services qu'on surveille — les mêmes que la maintenance (scripts/18_vps_maintenance.py).
# Un service ABSENT de la machine (``LoadState=not-found``) n'est pas une panne : il est dit
# « absent », jamais « inactif ».
SERVICES = ("aks-admin", "aks-chromium", "hermes-cdp-proxy", "nginx")
LOG_LINES = 20
LOG_TAIL_BYTES = 256 * 1024
TEXT_MAX = 220
DISK_ALERT_PCT = 90.0
REBOOT_REQUIRED = Path("/var/run/reboot-required")
PROC = Path("/proc")
MAINT_DIR = ("state", "maintenance")

# Même vocabulaire d'identifiants de run que l'admin (src/admin/runs.py RUN_ID_RE) : un id lu
# dans un fichier (``current_run_id``, ``current.run``) ne devient un chemin QUE s'il y passe.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# ── les libellés, en français ─────────────────────────────────────────────────────────
STAGE_LABELS = {
    "probe": "lecture de la taille du feed",
    "extract": "lecture du feed",
    "match": "matching",
    "submit": "saisie",
    "move": "déplacement vers les listes",
    "pause": "pause après une erreur passagère",
}
KIND_LABELS = {
    "submit": "Saisie validée (Validation & Submit)",
    "dry_run": "Aperçu de saisie (dry-run)",
    "catalog": "Catalogue AKS (lecture seule)",
    "extract": "Lecture d'un feed (extraction)",
    "match": "Matching (lecture seule)",
    "sort_scan": "Tri des listes — scan (lecture seule)",
    "sort_dry_run": "Tri des listes — aperçu (lecture seule)",
    "sort_canary": "Tri des listes — canary (écriture)",
    "sort_batch": "Tri des listes — lot (écriture)",
}
TASK_TYPES = ("aucune", "balayage", "saisie_par_page", "tri", "maintenance", "autre", "inconnue")

# ── le filtre de texte (secrets) ──────────────────────────────────────────────────────
REDACTED = "***REDACTED***"
_SECRET_TEXT = (
    # l'URL d'un webhook (Discord, Slack) — le secret du salon
    (re.compile(r"https?://[^\s\"'<>]*(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com)"
                r"[^\s\"'<>]*", re.I), REDACTED),
    (re.compile(r"(AKS_DISCORD_WEBHOOK\s*[=:]\s*)\S+", re.I), r"\1" + REDACTED),
    # un cookie de session WordPress, écrit « nom=valeur »
    (re.compile(r"\b(wordpress_[A-Za-z0-9_]*|wp[_-]?settings[A-Za-z0-9_-]*)=([^;\s\"']+)", re.I),
     r"\1=" + REDACTED),
    # un en-tête d'autorisation
    (re.compile(r"\b(authorization\s*[:=]\s*(?:basic|bearer)\s+)\S+", re.I), r"\1" + REDACTED),
    (re.compile(r"\b(cookie\s*:\s*)[^\n]+", re.I), r"\1" + REDACTED),
)


def scrub_text(value: Any, limit: int = TEXT_MAX) -> str:
    """Une chaîne affichable : secrets masqués, espaces repliés, tronquée à ``limit``."""

    text = str(value if value is not None else "")
    for pattern, repl in _SECRET_TEXT:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def scrub(obj: Any) -> Any:
    """``redact`` (par nom de clé) puis le filtre de texte sur chaque chaîne."""

    obj = redact(obj)

    def walk(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            return scrub_text(o, limit=2000)
        return o

    return walk(obj)


# ── petites briques ───────────────────────────────────────────────────────────────────
def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def hhmm(ts: Any) -> str:
    """« 14:03 UTC » d'un horodatage ISO ; vide s'il est illisible."""

    return f"{ts[11:16]} UTC" if isinstance(ts, str) and len(ts) >= 16 and ts[13:14] == ":" else ""


def jour_heure(ts: Any) -> str:
    """« 30/09 à 14:03 UTC » — un balayage dure des heures, le jour part avec."""

    if not (isinstance(ts, str) and len(ts) >= 16):
        return ""
    return f"{ts[8:10]}/{ts[5:7]} à {ts[11:16]} UTC"


Runner = Callable[..., subprocess.CompletedProcess]


def run_cmd(cmd: list[str], timeout: float = PROBE_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Une commande, sans jamais lever : délai dépassé = code 124, binaire absent = 127."""

    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"délai de {timeout:g} s dépassé")
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


# ── le système ────────────────────────────────────────────────────────────────────────
def system_facts(proc_root: Path = PROC, disk_path: str = "/") -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["uptime_s"] = int(float((proc_root / "uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        out["uptime_s"] = None
    try:
        out["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        out["load"] = None
    out["cpus"] = os.cpu_count()
    try:
        import shutil
        du = shutil.disk_usage(disk_path)
        out["disk"] = {"path": disk_path, "used_pct": round(100.0 * du.used / du.total, 1),
                       "free_gb": round(du.free / 1024 ** 3, 1),
                       "total_gb": round(du.total / 1024 ** 3, 1)}
    except (OSError, ZeroDivisionError):
        out["disk"] = None
    try:
        info: dict[str, int] = {}
        for line in (proc_root / "meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                info[key.strip()] = int(parts[0])
        total, avail = info["MemTotal"], info["MemAvailable"]
        out["mem"] = {"total_mb": total // 1024, "available_mb": avail // 1024,
                      "used_pct": round(100.0 * (total - avail) / total, 1)}
    except (OSError, KeyError, ZeroDivisionError):
        out["mem"] = None
    try:
        out["boot_id"] = (proc_root / "sys" / "kernel" / "random" / "boot_id").read_text().strip()
    except OSError:
        out["boot_id"] = None
    return out


def code_version(root: Path, runner: Runner = run_cmd) -> dict[str, Any]:
    """Le commit du clone : sha court, sujet, date, branche. Rien sur ``origin`` (réseau)."""

    res = runner(["git", "-C", str(root), "log", "-1", "--format=%h%x09%cI%x09%D%x09%s"],
                 timeout=PROBE_TIMEOUT_S)
    if res.returncode != 0 or not (res.stdout or "").strip():
        raise RuntimeError(scrub_text(res.stderr or f"git: code {res.returncode}", 160))
    sha, date, refs, subject = ((res.stdout or "").strip().split("\t", 3) + ["", "", ""])[:4]
    branch = None
    for ref in refs.split(","):
        ref = ref.strip()
        if ref.startswith("HEAD -> "):
            branch = ref[len("HEAD -> "):]
    return {"sha": sha, "date": date, "branch": branch, "subject": scrub_text(subject, 120)}


def services_state(runner: Runner = run_cmd, services: tuple[str, ...] = SERVICES) -> dict[str, str]:
    """``{service: active | inactive | failed | activating | … | absent}``, d'un seul appel."""

    res = runner(["systemctl", "show", "-p", "Id", "-p", "LoadState", "-p", "ActiveState",
                  *services], timeout=PROBE_TIMEOUT_S)
    if res.returncode != 0 or not (res.stdout or "").strip():
        raise RuntimeError(scrub_text(res.stderr or f"systemctl: code {res.returncode}", 160))
    out: dict[str, str] = {}
    for block in re.split(r"\n\s*\n", (res.stdout or "").strip()):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        name = props.get("Id", "").removesuffix(".service")
        if name not in services:
            continue
        out[name] = "absent" if props.get("LoadState") == "not-found" \
            else (props.get("ActiveState") or "inconnu")
    for name in services:
        out.setdefault(name, "inconnu")
    return out


def _admin_get(url: str, timeout: float) -> tuple[Any, int]:
    """``GET`` une route de l'admin : ``(json, latence_ms)`` ; lève si elle ne répond pas."""

    started = time.monotonic()
    req = urllib.request.Request(url, headers={"X-AKS-Admin": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8") or "{}")
    return data, int((time.monotonic() - started) * 1000)


def _probe_error(exc: BaseException, timeout: float) -> str:
    if isinstance(exc, TimeoutError) or "timed out" in str(exc):
        return f"délai de {timeout:g} s dépassé"
    return scrub_text(f"{type(exc).__name__}: {exc}", 160)


def admin_probe_http(url: str = ADMIN_URL, timeout: float = ADMIN_TIMEOUT_S,
                     busy_timeout: float = ADMIN_BUSY_TIMEOUT_S) -> dict[str, Any]:
    """L'admin local répond-il, et quel run déclare-t-il ? Deux lectures EN PARALLÈLE (revue
    adverse du 2026-09-30) :

    * ``GET /api/meta`` — réponse constante : c'est elle qui dit « joignable ». Avant, la
      joignabilité se lisait sur ``/api/sort/runs``, qui parcourt tout ``runs/`` et relit
      chaque ``sort_plan.json`` : un admin sain mais chargé (balayage en cours) passait DOWN ;
    * ``GET /api/sort/runs`` — le ``busy`` que les consoles lisent déjà, avec PLUS de marge
      (``busy_timeout``). S'il ne répond pas à temps alors que ``/api/meta`` a répondu, l'admin
      reste joignable et ``busy_unknown`` le dit : la photo retombe sur le marqueur, et ne
      conclut jamais « rien en cours » d'un silence."""

    def meta() -> tuple[Any, int]:
        return _admin_get(url + "/api/meta", timeout)

    def runs() -> tuple[Any, int]:
        return _admin_get(url + "/api/sort/runs", busy_timeout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_meta, f_runs = pool.submit(meta), pool.submit(runs)
        try:
            _, meta_ms = f_meta.result()
            meta_error = None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            meta_ms, meta_error = None, _probe_error(exc, timeout)
        try:
            data, runs_ms = f_runs.result()
            runs_error = None if isinstance(data, dict) else "réponse inattendue de /api/sort/runs"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            data, runs_ms, runs_error = None, None, _probe_error(exc, busy_timeout)
    if meta_error and runs_error:
        return {"reachable": False, "busy": None, "error": meta_error}
    out: dict[str, Any] = {"reachable": True, "error": None,
                           "latency_ms": meta_ms if meta_ms is not None else runs_ms}
    if runs_error:
        out.update(busy=None, busy_unknown=True, busy_error=f"liste des runs : {runs_error}")
    else:
        out.update(busy=data.get("busy"), browser=data.get("browser"))
    return out


# ── la maintenance ────────────────────────────────────────────────────────────────────
def _cmdline(proc_root: Path, pid: int | str) -> list[str]:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]


def maintenance_processes(proc_root: Path = PROC) -> list[dict[str, Any]]:
    """Les processus de maintenance EN COURS : l'agent ``18_vps_maintenance.py run|postboot``
    (jamais ``status``, que le pilote lit en lecture seule) et le pilote ``19_restart_vps.py``."""

    found: list[dict[str, Any]] = []
    me = os.getpid()
    try:
        entries = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except OSError:
        return found
    for entry in entries:
        if int(entry.name) == me:
            continue
        args = _cmdline(proc_root, entry.name)
        for i, arg in enumerate(args):
            base = os.path.basename(arg)
            if base == "18_vps_maintenance.py":
                sub = args[i + 1] if i + 1 < len(args) else ""
                if sub in ("run", "postboot"):
                    found.append({"pid": int(entry.name), "script": base, "command": sub,
                                  "dry_run": "--dry-run" in args[i + 1:]})
                break
            if base == "19_restart_vps.py":
                found.append({"pid": int(entry.name), "script": base, "command": "pilote",
                              "dry_run": "--apply" not in args[i + 1:]})
                break
    return found


def maintenance_state(root: Path, proc_root: Path = PROC) -> dict[str, Any] | None:
    """La maintenance en cours sur cette machine, ou None."""

    pending = (root.joinpath(*MAINT_DIR) / "pending.json").is_file()
    procs = maintenance_processes(proc_root)
    if not pending and not procs:
        return None
    real = [p for p in procs if not p.get("dry_run")]
    if any(p["command"] == "pilote" for p in real):
        label = "Maintenance des VPS en cours (pilote, un VPS après l'autre)"
    elif any(p["command"] == "postboot" for p in real):
        label = "Maintenance — fin après redémarrage (contrôles, puis relance)"
    elif real:
        label = "Maintenance de cette machine en cours (arrêt sûr, apt, redémarrage si requis)"
    elif procs:
        label = "Maintenance à blanc (lecture seule)"
    else:
        label = "Maintenance — redémarrage programmé, la fin se fera au démarrage (pending.json)"
    return {"pending": pending, "processes": procs, "label": label}


def last_maintenance(root: Path) -> dict[str, Any] | None:
    """Le résumé de ``state/maintenance/last_result.json`` (l'agent l'écrit à chaque fin)."""

    raw = read_json(root.joinpath(*MAINT_DIR) / "last_result.json")
    if not isinstance(raw, dict):
        return None
    keep = ("finished_at", "started_at", "exit", "services", "invariants", "session",
            "relaunched", "apt", "reboot", "rebooted", "stopped", "code", "error")
    out: dict[str, Any] = {}
    for key in keep:
        if key in raw and raw[key] is not None:
            value = raw[key]
            out[key] = value if isinstance(value, (bool, int, float)) else scrub_text(value, 200)
    return out


# ── la tâche en cours ─────────────────────────────────────────────────────────────────
def _safe_dir(runs_dir: Path, run_id: Any) -> Path | None:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        return None
    path = runs_dir / run_id
    return path if path.is_dir() else None


def _target_names(targets: Any) -> list[str]:
    out: list[str] = []
    for t in targets or []:
        if isinstance(t, dict) and t.get("merchant"):
            out.append(str(t["merchant"]))
        elif isinstance(t, (list, tuple)) and t:
            out.append(str(t[0]))
    return out


def detect_group(names: list[str]) -> str | None:
    """Le groupe figé (``src/merchant_groups.py``) dont les marchands sont EXACTEMENT ceux-là,
    ou « liste blanche » quand ce sont tous les marchands allowlistés. Le nom d'un groupe n'est
    écrit nulle part (l'admin le détend au lancement) : on le retrouve par l'ensemble."""

    want = {n.casefold() for n in names}
    if not want:
        return None
    try:
        from src.merchant_groups import GROUPS, group_targets
        for name in sorted(GROUPS):
            try:
                if {m.casefold() for m, _ in group_targets(name)} == want:
                    return name
            except KeyError:
                continue
        from src.admin.auto_merchants import AUTO_MERCHANTS
        if {m.casefold() for m, _ in AUTO_MERCHANTS} == want:
            return "liste blanche"
    except Exception:                          # noqa: BLE001 — une photo, jamais une panne
        return None
    return None


def launched_from_terminal(runs_dir: Path, busy: dict[str, Any]) -> bool:
    """Le run a-t-il été lancé AU TERMINAL ? Revue adverse du 2026-09-30 : le marqueur ne le
    dit PAS — ``scripts/10`` et ``scripts/05`` écrivent toujours ``source: "cli"``, même quand
    l'admin les a lancés. Quand l'admin ne répond pas (redémarrage, lenteur), la photo retombe
    sur le marqueur et un balayage lancé depuis la console s'affichait « (lancé au terminal) ».

    Ce qui le dit : ``runs/<id>/admin_submit.json``, que SEUL ``SubmitManager._spawn`` écrit, avec
    le pid de l'enfant — le processus Python lui-même (``argv[0]`` = l'interpréteur), donc le pid
    du marqueur. Un ``admin_submit.json`` d'un AUTRE pid = une relance au terminal avec le même
    ``--run-id`` : terminal."""

    if busy.get("source") == "admin":
        return False
    run_dir = _safe_dir(runs_dir, busy.get("run_id"))
    launch = read_json(run_dir / "admin_submit.json") if run_dir is not None else None
    if not isinstance(launch, dict):
        return True
    pid, launch_pid = busy.get("pid"), launch.get("pid")
    if isinstance(pid, int) and isinstance(launch_pid, int) and pid != launch_pid:
        return True
    return False


def _cli_flags(proc_root: Path, pid: Any) -> dict[str, Any]:
    """``--group X`` / ``--loop`` / ``--all-allowlisted`` d'un balayage lancé au terminal."""

    if not isinstance(pid, int):
        return {}
    args = _cmdline(proc_root, pid)
    out: dict[str, Any] = {}
    if "--group" in args:
        i = args.index("--group")
        if i + 1 < len(args):
            out["group"] = args[i + 1][:16]
    out["loop"] = "--loop" in args
    if "--all-allowlisted" in args:
        out["group"] = "liste blanche"
    return out


def current_page(recap: Any) -> dict[str, Any] | None:
    """La page EN COURS : le premier marchand dont ``recap.current.page`` est posé — la même
    lecture que ``currentPage`` d'``auto.js``. None si le recap est fini."""

    if not isinstance(recap, dict) or recap.get("finished_at"):
        return None
    for t in recap.get("targets") or []:
        cur = ((t or {}).get("recap") or {}).get("current") if isinstance(t, dict) else None
        if isinstance(cur, dict) and cur.get("page") is not None:
            return {"merchant": t.get("merchant"), "page": cur.get("page"),
                    "run": cur.get("run"), "stage": cur.get("stage"),
                    "stage_label": STAGE_LABELS.get(str(cur.get("stage") or ""),
                                                    str(cur.get("stage") or "en cours")),
                    "since": cur.get("since"), "stage_at": cur.get("stage_at"),
                    "candidates": cur.get("approved", cur.get("candidates"))}
    return None


def loop_created(loop: dict[str, Any], recap: dict[str, Any] | None) -> int:
    """Les créations d'une boucle : les passes finies (``totals``), plus la passe COURANTE tant
    que ``loop.json`` dit ``running``. ``run_loop`` n'ajoute une passe aux totaux qu'en
    réécrivant ``loop.json`` en ``pause`` ou ``stopped`` : tant qu'il dit ``running``, la passe
    courante n'y est pas — même si son recap porte déjà ``finished_at`` (processus tué entre les
    deux). En pause, elle y est déjà : ne pas la recompter."""

    total = int(((loop or {}).get("totals") or {}).get("created") or 0)
    if (loop or {}).get("state") == "running" and isinstance(recap, dict):
        total += int(recap.get("total_created") or 0)
    return total


def _page_created_live(root: Path, runs_dir: Path, log_dir: Path, page_run: Any) -> int | None:
    """Les créations de la page EN COURS, lues comme ``api/runs/<run>`` les lit (journal de la
    page + ``submit_plan.json``) — la page n'entre dans ``total_created`` qu'à sa fin."""

    if not isinstance(page_run, str) or not RUN_ID_RE.match(page_run):
        return None
    try:
        from src.admin.submit_manager import offer_submit_history
        history = offer_submit_history(log_dir / f"{page_run}.jsonl",
                                       runs_dir / page_run / "submit_plan.json")
    except Exception:                          # noqa: BLE001
        return None
    return sum(1 for o in history.values() if o.get("status") == "created")


def _who(group: str | None, names: list[str]) -> str:
    if group == "liste blanche":
        return "de toute la liste blanche"
    if group:
        return f"groupe {group}"
    if not names:
        return ""
    head = ", ".join(names[:3])
    return head + (f" +{len(names) - 3}" if len(names) > 3 else "")


def _unknown_in_recap(recap: Any) -> int:
    n = 0
    for t in (recap or {}).get("targets") or [] if isinstance(recap, dict) else []:
        for p in ((t or {}).get("recap") or {}).get("pages") or []:
            for o in (p or {}).get("offers_created") or []:
                if isinstance(o, dict) and "UNKNOWN" in str(o.get("post_save") or ""):
                    n += 1
    return n


def sweep_task(root: Path, busy: dict[str, Any], *, runs_dir: Path, log_dir: Path,
               proc_root: Path = PROC) -> dict[str, Any]:
    """Un balayage ``data_entry_auto`` : groupe, boucle, passe, marchand / page / étape, créées."""

    run_id = str(busy.get("run_id"))
    run_dir = _safe_dir(runs_dir, run_id)
    task: dict[str, Any] = {"type": "balayage", "kind": "data_entry_auto", "run_id": run_id,
                            "source": busy.get("source"), "pid": busy.get("pid")}
    if run_dir is None:
        task["label"] = f"Balayage {run_id} (dossier de run introuvable)"
        return task
    launch = read_json(run_dir / "admin_submit.json")
    launch = launch if isinstance(launch, dict) else {}
    loop = sweep_loop.read_status(run_dir)
    pass_id = sweep_loop.current_pass_run_id(run_dir) or run_dir.name
    pass_dir = _safe_dir(runs_dir, pass_id)
    recap = read_json(pass_dir / "recap.json") if pass_dir is not None else None
    recap = recap if isinstance(recap, dict) else None

    terminal = launched_from_terminal(runs_dir, busy)
    flags = _cli_flags(proc_root, busy.get("pid")) if terminal else {}
    names = (_target_names(launch.get("targets")) or _target_names((loop or {}).get("targets"))
             or _target_names((recap or {}).get("planned")))
    group = flags.get("group") or detect_group(names)
    is_loop = loop is not None or bool(launch.get("loop")) or bool(flags.get("loop"))
    cur = current_page(recap)
    state = (loop or {}).get("state") or ("running" if recap and not recap.get("finished_at")
                                          else ("fini" if recap else "démarrage"))
    pass_no = (loop or {}).get("pass")

    created_loop = int(((loop or {}).get("totals") or {}).get("created") or 0)
    created_pass = int((recap or {}).get("total_created") or 0)
    created_page = _page_created_live(root, runs_dir, log_dir, cur.get("run")) \
        if cur and cur.get("stage") == "submit" else None
    total = loop_created(loop, recap) if loop is not None else created_pass
    total += created_page or 0

    halted = [scrub_text(h, 160) for h in ((recap or {}).get("halted_merchants") or [])]
    started = (loop or {}).get("started_at") or (recap or {}).get("started_at") \
        or launch.get("started_at") or busy.get("started_at")

    parts: list[str] = []
    if is_loop and loop is not None:
        if state == "pause":
            nxt = hhmm(loop.get("next_pass_at"))
            parts.append(f"passe {pass_no} finie, pause" + (f" jusqu'à {nxt}" if nxt else "")
                         + f" (passe {int(pass_no or 0) + 1} ensuite)")
        elif state == "stopped":
            parts.append("boucle arrêtée : " + scrub_text(loop.get("stopped_label")
                                                          or loop.get("stopped_reason") or "?", 120))
        elif pass_no:
            parts.append(f"passe {pass_no}")
    if cur:
        depuis = hhmm(cur.get("stage_at"))
        parts.append(f"{cur.get('merchant')} page {cur.get('page')}, {cur['stage_label']}"
                     + (f" depuis {depuis}" if depuis else ""))
    elif state not in ("pause", "stopped"):
        started_targets = [t for t in (recap or {}).get("targets") or [] if isinstance(t, dict)]
        if started_targets and not (recap or {}).get("finished_at"):
            parts.append(f"{started_targets[-1].get('merchant')}, entre deux pages")
        elif recap is None or not started_targets:
            parts.append("démarrage")
    who = _who(group, names)
    label = "Balayage" + (f" {who}" if who else "") + (" en boucle" if is_loop else "")
    if parts:
        label += " — " + ", ".join(parts)
    if terminal:
        label += " (lancé au terminal)"
    task.update({
        "label": label, "group": group, "merchants": names, "loop": is_loop, "state": state,
        "from_terminal": terminal,
        "pass": pass_no, "pass_run_id": pass_id if pass_id != run_id else None,
        "next_pass_at": (loop or {}).get("next_pass_at"),
        "stopped_label": (loop or {}).get("stopped_label"),
        "current": cur, "started_at": started,
        "created": {"total": total, "loop_finished_passes": created_loop if loop else None,
                    "pass": created_pass, "page": created_page},
        "halted_merchants": halted,
        "unknown_offers": _unknown_in_recap(recap),
        "list_id": launch.get("list_id"),
    })
    task["_recap"] = recap          # pour les alertes et les journaux — retiré avant la sortie
    task["_loop"] = loop
    return task


def by_urls_task(busy: dict[str, Any], *, runs_dir: Path) -> dict[str, Any]:
    """La saisie par page AKS (onglet « Saisie par jeux ») : aperçu, ou saisie réelle."""

    run_id = str(busy.get("run_id"))
    kind = str(busy.get("kind"))
    submit = kind == "data_entry_by_urls_submit"
    run_dir = _safe_dir(runs_dir, run_id)
    recap = read_json(run_dir / "recap.json") if run_dir is not None else None
    recap = recap if isinstance(recap, dict) else {}
    totals = recap.get("totals") if isinstance(recap.get("totals"), dict) else {}
    if submit:
        created = totals.get("created")
        label = "Saisie par page — saisie réelle (onglet « Saisie par jeux »)"
        if created is not None:
            label += f" : {created} créée(s)"
    else:
        created = None
        done = len(recap.get("games") or [])
        label = "Saisie par page — aperçu, lecture seule (onglet « Saisie par jeux »)"
        if totals.get("games"):
            label += f" : {done}/{totals.get('games')} page(s) lue(s)"
            if totals.get("candidates") is not None:
                label += f", {totals.get('candidates')} candidat(s)"
    terminal = launched_from_terminal(runs_dir, busy)
    if terminal:
        label += " (lancé au terminal)"
    return {"type": "saisie_par_page", "kind": kind, "run_id": run_id, "label": label,
            "source": busy.get("source"), "pid": busy.get("pid"), "from_terminal": terminal,
            "started_at": recap.get("started_at") or busy.get("started_at"),
            "created": {"total": created} if created is not None else None}


INTERRUPTED_LABEL = "arrêté sans fin propre (processus disparu)"


def last_sweep(runs_dir: Path, log_dir: Path | None = None) -> dict[str, Any] | None:
    """Le DERNIER balayage (``*-auto`` le plus récent, comme la route recap sans run) : quand
    rien ne tourne, c'est lui qui dit pourquoi la machine est au repos.

    **Fini, ou disparu ?** (revue adverse du 2026-09-30.) Un balayage qui finit ÉCRIT sa fin
    avant de rendre son marqueur : ``run_loop`` passe ``loop.json`` à ``stopped``, ``run_pass``
    pose ``finished_at`` sur le recap. Quand plus rien ne tourne, une boucle encore ``running``
    ou ``pause``, ou un recap commencé sans ``finished_at``, ne peut donc dire qu'une chose : le
    processus a disparu — redémarrage de l'admin (qui tue ses enfants), OOM, SIGKILL. Il était
    affiché « fini le … », sans alerte, et sans les créations de la passe inachevée. Il est
    désormais ``interrupted``, avec sa dernière trace (``last_seen_at``) et jamais ``ended_at``.
    Un dossier SANS recap n'est pas « interrompu » : l'admin le crée avant que l'enfant n'écrive
    quoi que ce soit (lancement en cours, ou refusé au démarrage)."""

    try:
        names = sorted((p.name for p in runs_dir.glob("*-auto") if p.is_dir()), reverse=True)
    except OSError:
        return None
    if not names:
        return None
    run_dir = runs_dir / names[0]
    loop = sweep_loop.read_status(run_dir)
    pass_id = sweep_loop.current_pass_run_id(run_dir) or run_dir.name
    pass_dir = _safe_dir(runs_dir, pass_id)
    raw = read_json(pass_dir / "recap.json") if pass_dir is not None else None
    recap = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {"run_id": run_dir.name, "loop": loop is not None,
                           "started_at": (loop or {}).get("started_at") or recap.get("started_at"),
                           "halted_merchants": [scrub_text(h, 160)
                                                for h in recap.get("halted_merchants") or []]}
    if loop is not None:
        interrupted = loop.get("state") in ("running", "pause")
        out["created"] = loop_created(loop, recap)
        out["stopped_reason"] = loop.get("stopped_reason")
        out["stopped_label"] = loop.get("stopped_label")
        out["passes"] = loop.get("pass")
        if not interrupted:
            out["ended_at"] = loop.get("stopped_at") or loop.get("updated_at")
    else:
        interrupted = bool(isinstance(raw, dict) and raw.get("started_at")
                           and not raw.get("finished_at"))
        out["created"] = int(recap.get("total_created") or 0)
        out["halted"] = scrub_text(recap.get("halted"), 200) if recap.get("halted") else None
        if not interrupted:
            out["ended_at"] = recap.get("finished_at") or recap.get("updated_at")
    if interrupted:
        # La page où il est mort : ses créations ne sont qu'à SON journal (une page n'entre au
        # recap qu'à sa fin), lues comme pour un balayage vivant.
        cur = current_page(recap)
        if cur and cur.get("stage") == "submit" and log_dir is not None:
            out["created"] += _page_created_live(runs_dir.parent, runs_dir, log_dir,
                                                 cur.get("run")) or 0
        stamps = [s for s in ((loop or {}).get("updated_at"), recap.get("updated_at"))
                  if isinstance(s, str) and s]
        out.update(interrupted=True, interrupted_label=INTERRUPTED_LABEL,
                   last_seen_at=max(stamps) if stamps else None, stopped_at_page=cur)
    out["_recap"] = recap
    out["_loop"] = loop
    return out


def classify_task(root: Path, busy: Any, *, runs_dir: Path, log_dir: Path,
                  proc_root: Path = PROC, busy_unknown: bool = False) -> dict[str, Any]:
    """La tâche de la machine, typée et dite en français. ``busy`` = le run que l'admin (ou le
    marqueur) déclare — ``{run_id, kind, source, pid?, started_at?}`` — ou None.
    ``busy_unknown`` : l'admin répond mais n'a pas dit quel run tourne, et le marqueur est vide
    — « Tâche inconnue », jamais « Rien en cours » (un run lancé par l'admin sans marqueur, un
    tri par exemple, peut tourner)."""

    maint = maintenance_state(root, proc_root)
    task: dict[str, Any]
    if isinstance(busy, dict) and busy.get("run_id"):
        kind = str(busy.get("kind") or "")
        if kind == "data_entry_auto":
            task = sweep_task(root, busy, runs_dir=runs_dir, log_dir=log_dir, proc_root=proc_root)
        elif kind in ("data_entry_by_urls", "data_entry_by_urls_submit"):
            task = by_urls_task(busy, runs_dir=runs_dir)
        else:
            label = KIND_LABELS.get(kind, f"Run « {kind or '?'} »")
            terminal = launched_from_terminal(runs_dir, busy)
            if terminal:
                label += " (lancé au terminal)"
            task = {"type": "tri" if kind.startswith("sort_") else "autre", "kind": kind,
                    "run_id": busy.get("run_id"), "label": label, "source": busy.get("source"),
                    "pid": busy.get("pid"), "started_at": busy.get("started_at"),
                    "from_terminal": terminal}
        if maint:
            task["label"] += " · " + maint["label"][0].lower() + maint["label"][1:]
    elif maint:
        task = {"type": "maintenance", "kind": "maintenance", "label": maint["label"]}
    else:
        if busy_unknown:
            task = {"type": "inconnue", "kind": None,
                    "label": "Tâche inconnue — l'admin répond, mais n'a pas dit quel run tourne"}
        else:
            task = {"type": "aucune", "kind": None, "label": "Rien en cours"}
        last = last_sweep(runs_dir, log_dir)
        if last:
            task["last_sweep"] = last
            if last.get("interrupted") and not busy_unknown:
                task["label"] = "Rien en cours — le dernier balayage s'est interrompu sans fin propre"
    task["maintenance"] = maint
    return task


# ── le journal ────────────────────────────────────────────────────────────────────────
# Le bruit : l'instantané du garde (énorme), le rythme, les attentes de rendu.
NOISE_EVENTS = frozenset({"guard_snapshot", "pacing", "search_circuit_preopened",
                          "catalog_cache_hit"})
# Les événements de PROGRESSION : on n'en garde que le dernier par journal, sinon les 20 lignes
# ne seraient que des « matching 45/100 ».
PROGRESS_EVENTS = frozenset({"match_progress", "feed_page", "feed_sweep"})


def _meaningful(event: str) -> bool:
    return bool(event) and event not in NOISE_EVENTS and not event.endswith("_wait")


def read_log_tail(path: Path, max_bytes: int = LOG_TAIL_BYTES) -> list[dict[str, Any]]:
    """Les enregistrements JSONL de la FIN d'un journal (lignes entières seulement)."""

    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()           # la première ligne est coupée
            chunk = handle.read()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _short(value: Any, limit: int = 120) -> str:
    return scrub_text(value, limit)


def event_text(rec: dict[str, Any]) -> str:
    """Une ligne lisible pour un événement connu ; sinon ses trois premiers champs simples."""

    ev = str(rec.get("event") or "")
    g = rec.get
    if ev == "submit_offer":
        if g("success"):
            return f"offre {g('offer_id')} : créée"
        return f"offre {g('offer_id')} : non créée — {_short(g('blocker') or g('post_save') or '?')}"
    if ev == "dry_run_offer":
        if g("success"):
            return f"aperçu offre {g('offer_id')} : prête"
        return f"aperçu offre {g('offer_id')} : refusée — {_short(g('blocker') or g('post_save') or '?')}"
    if ev == "skip":
        return f"offre {g('offer_id')} écartée : {_short(g('reason'))}"
    if ev == "run_stopped":
        return f"arrêt : {_short(g('reason'))}" + (f" ({_short(g('detail'), 80)})" if g("detail") else "")
    if ev in ("aborted", "match_aborted", "run_aborted", "submit_run_aborted"):
        return f"ABANDON : {_short(g('reason'))}" + (f" ({_short(g('detail'), 80)})" if g("detail") else "")
    if ev == "match_progress":
        return f"matching {g('done')}/{g('total')} — {g('candidates')} candidat(s)"
    if ev == "feed_indexed":
        return f"feed indexé : {g('offers')} offre(s)"
    if ev == "admin_submit_started":
        return f"lancé ({g('kind')}) par {_short(g('by'), 60)}"
    if ev == "admin_submit_finished":
        return f"fini : {g('state')} (code {g('exit_code')})"
    if ev in ("notify", "notify_failed", "notify_skipped"):
        state = {"notify": "envoyé", "notify_failed": "ÉCHEC", "notify_skipped": "non configuré"}[ev]
        return f"Discord ({_short(g('kind'), 40)}) : {state}"
    if ev.startswith("add_target_"):
        return f"ajout de {_short(g('merchant'), 40)} : {ev[len('add_target_'):]}"
    if ev == "row_relocated":
        return f"ligne relocalisée (offre {g('approved_offer_id') or g('plan_offer_id')})"
    if ev == "post_save_proof_retry":
        return f"preuve après saisie relancée (offre {g('offer_id')})"
    if ev == "sitemap_index":
        return "index sitemap lu"
    if ev in ("merchant_submit", "merchant_submitted"):
        return f"{ev.replace('_', ' ')} : {_short(g('merchant'), 40)}" + \
            (f" — {g('created')} créée(s)" if g("created") is not None else "")
    skip = {"ts", "run_id", "event"}
    simple = [f"{k}={_short(v, 40)}" for k, v in rec.items()
              if k not in skip and isinstance(v, (str, int, float, bool)) and v not in ("", None)]
    return (ev.replace("_", " ") + (" · " + ", ".join(simple[:3]) if simple else ""))


def collect_logs(log_dir: Path, sources: list[dict[str, Any]], limit: int = LOG_LINES) -> list[dict[str, Any]]:
    """Les ``limit`` derniers événements utiles de plusieurs journaux, les plus récents d'abord.
    ``sources`` : ``[{"run": <id>, "merchant"?: …, "page"?: …}]`` ; un id invalide est ignoré."""

    items: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for src in sources:
        run = src.get("run")
        if not isinstance(run, str) or not RUN_ID_RE.match(run) or run in seen_runs:
            continue
        seen_runs.add(run)
        records = [r for r in read_log_tail(log_dir / f"{run}.jsonl")
                   if _meaningful(str(r.get("event") or ""))]
        last_progress: dict[str, int] = {}
        for i, rec in enumerate(records):
            if rec.get("event") in PROGRESS_EVENTS:
                last_progress[str(rec.get("event"))] = i
        for i, rec in enumerate(records):
            ev = str(rec.get("event") or "")
            if ev in PROGRESS_EVENTS and last_progress.get(ev) != i:
                continue
            clean = scrub(rec)
            item: dict[str, Any] = {"ts": str(clean.get("ts") or ""), "event": ev,
                                    "text": scrub_text(event_text(clean)), "run": run}
            if src.get("merchant"):
                item["merchant"] = str(src["merchant"])
            if src.get("page") is not None:
                item["page"] = src["page"]
            items.append(item)
    # Tri stable sur l'horodatage : à égalité, l'ordre du journal.
    items.sort(key=lambda it: it["ts"])
    return list(reversed(items[-limit:]))


def log_sources(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Les journaux à lire pour la tâche : le lancement, et pour un balayage la page en cours
    (ou la dernière page finie du marchand en cours)."""

    sources: list[dict[str, Any]] = []
    if task.get("run_id"):
        sources.append({"run": task["run_id"]})
    if task.get("pass_run_id"):
        sources.append({"run": task["pass_run_id"]})
    recap = task.get("_recap")
    cur = task.get("current")
    if cur and cur.get("run"):
        sources.append({"run": cur["run"], "merchant": cur.get("merchant"), "page": cur.get("page")})
    elif isinstance(recap, dict):
        targets = [t for t in recap.get("targets") or [] if isinstance(t, dict)]
        if targets:
            pages = ((targets[-1].get("recap") or {}).get("pages")) or []
            if pages and isinstance(pages[-1], dict) and pages[-1].get("run"):
                sources.append({"run": pages[-1]["run"], "merchant": targets[-1].get("merchant"),
                                "page": pages[-1].get("page")})
    last = task.get("last_sweep")
    if isinstance(last, dict) and last.get("run_id"):
        sources.append({"run": last["run_id"]})
        rec = last.get("_recap") or {}
        targets = [t for t in rec.get("targets") or [] if isinstance(t, dict)]
        if targets:
            pages = ((targets[-1].get("recap") or {}).get("pages")) or []
            if pages and isinstance(pages[-1], dict) and pages[-1].get("run"):
                sources.append({"run": pages[-1]["run"], "merchant": targets[-1].get("merchant"),
                                "page": pages[-1].get("page")})
    return sources


# ── les alertes ───────────────────────────────────────────────────────────────────────
# Les événements où une déconnexion ARRÊTE quelque chose. Le texte d'une offre (rebond passager
# après un clic) ne suffit pas seul — même prudence que `sweep_loop.pass_saw_login_bounce`.
STOP_EVENTS = frozenset({"aborted", "run_stopped", "match_aborted", "run_aborted",
                         "submit_run_aborted"})


def build_alerts(*, task: dict[str, Any], logs: list[dict[str, Any]], disk: Any,
                 reboot_required: bool, last_maint: dict[str, Any] | None) -> list[str]:
    """Des phrases courtes, rouges dans la console. Jamais de secret (tout est déjà filtré).
    L'admin injoignable et les services arrêtés ne sont PAS ici : ce sont les motifs du badge
    « DOWN » (``src/admin/overview.py``), affichés à côté de lui."""

    alerts: list[str] = []
    for h in task.get("halted_merchants") or []:
        alerts.append(f"Marchand arrêté — {h}")
    loop = task.get("_loop")
    if isinstance(loop, dict) and loop.get("state") == "stopped" \
            and loop.get("stopped_reason") != "operator_stop":
        alerts.append("Boucle arrêtée : " + scrub_text(loop.get("stopped_label")
                                                       or loop.get("stopped_reason") or "?", 160))
    last = task.get("last_sweep")
    if isinstance(last, dict):
        if last.get("interrupted"):
            where = last.get("stopped_at_page") or {}
            what = "Boucle {} interrompue" if last.get("loop") else "Balayage {} interrompu"
            alerts.append(what.format(last.get("run_id")) + " sans fin propre (processus disparu)"
                          + (f" — {scrub_text(where.get('merchant'), 40)} page {where.get('page')}"
                             if where.get("merchant") else "")
                          + (f" — dernière trace le {jour_heure(last.get('last_seen_at'))}"
                             if last.get("last_seen_at") else "")
                          + " — à relancer depuis la console")
        if last.get("loop") and last.get("stopped_reason") not in (None, "operator_stop"):
            alerts.append(f"Dernière boucle ({last.get('run_id')}) arrêtée : "
                          + scrub_text(last.get("stopped_label") or last.get("stopped_reason"), 160)
                          + (f" — le {jour_heure(last.get('ended_at'))}" if last.get("ended_at") else ""))
        for h in last.get("halted_merchants") or []:
            alerts.append(f"Dernier balayage — marchand arrêté : {h}")
    # Les offres à l'état INCONNU : celles des pages FINIES sont dans le recap ; celles de la page
    # EN COURS n'y sont pas encore — on les lit dans SON journal seulement (pas de double compte).
    unknown = int(task.get("unknown_offers") or 0)
    cur_run = (task.get("current") or {}).get("run")
    unknown += sum(1 for it in logs if cur_run and it.get("run") == cur_run
                   and it.get("event") == "submit_offer" and "UNKNOWN" in str(it.get("text") or ""))
    if unknown:
        alerts.append(f"{unknown} offre(s) à l'état INCONNU dans ce run — vérifier à la main sur AKS")
    login = any(it.get("event") in STOP_EVENTS and sweep_loop.is_login_bounce(it.get("text"))
                for it in logs)
    if isinstance(task.get("_recap"), dict) and sweep_loop.pass_saw_login_bounce(task["_recap"]):
        login = True
    if isinstance(loop, dict) and loop.get("stopped_reason") == "session_expired":
        login = True
    if isinstance(last, dict) and (last.get("stopped_reason") == "session_expired" or (
            isinstance(last.get("_recap"), dict) and sweep_loop.pass_saw_login_bounce(last["_recap"]))):
        login = True
    if login:
        alerts.append("Session AKS expirée (not logged in) — transfert de cookies requis "
                      "dans la console de cette machine")
    if reboot_required:
        alerts.append("Redémarrage requis par Debian (/var/run/reboot-required)")
    if isinstance(last_maint, dict) and last_maint.get("exit") not in (None, 0, 42):
        alerts.append(f"Dernière maintenance : code {last_maint.get('exit')}"
                      + (f" le {jour_heure(last_maint.get('finished_at'))}"
                         if last_maint.get("finished_at") else "")
                      + (f" — {last_maint.get('error')}" if last_maint.get("error") else ""))
    if isinstance(disk, dict) and isinstance(disk.get("used_pct"), (int, float)) \
            and disk["used_pct"] > DISK_ALERT_PCT:
        alerts.append(f"Disque {disk.get('path', '/')} plein à {disk['used_pct']:.0f} %")
    # sans doublon, dans l'ordre
    seen: set[str] = set()
    return [a for a in alerts if not (a in seen or seen.add(a))]


# ── la photo ──────────────────────────────────────────────────────────────────────────
def _public(task: dict[str, Any]) -> dict[str, Any]:
    """La tâche sans ses champs internes (``_recap``, ``_loop``), récursivement."""

    out = {k: v for k, v in task.items() if not k.startswith("_")}
    if isinstance(out.get("last_sweep"), dict):
        out["last_sweep"] = {k: v for k, v in out["last_sweep"].items() if not k.startswith("_")}
    return out


def snapshot(root: Path = ROOT, *, admin_probe: Callable[[], dict[str, Any]] | None = None,
             runner: Runner = run_cmd, proc_root: Path = PROC, runs_dir: Path | None = None,
             log_dir: Path | None = None, reboot_flag: Path = REBOOT_REQUIRED,
             hostname: str | None = None, disk_path: str = "/") -> dict[str, Any]:
    """La photo de CETTE machine. Ne lève jamais : une section en échec laisse son champ vide
    et son motif dans ``errors``.

    ``admin_probe`` : l'état de l'admin, ``{reachable, busy, busy_unknown?, error?}`` — l'admin
    passe le sien (en processus) ; par défaut, ``admin_probe_http`` en local (``/api/meta`` pour
    la joignabilité, ``/api/sort/runs`` pour ``busy``). Quand l'admin ne répond pas, ou pas sur
    la liste de ses runs, le run déclaré retombe sur le marqueur ``state/active_run.json``."""

    root = Path(root)
    runs_dir = Path(runs_dir) if runs_dir is not None else root / "runs"
    log_dir = Path(log_dir) if log_dir is not None else root / "logs"
    errors: dict[str, str] = {}
    snap: dict[str, Any] = {"schema": SCHEMA, "at": utc_now()}

    def guard(name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except Exception as exc:               # noqa: BLE001 — une photo partielle, jamais une panne
            errors[name] = scrub_text(f"{type(exc).__name__}: {exc}" if str(exc) else
                                      type(exc).__name__, 200)
            return default

    snap["host"] = guard("host", lambda: hostname or socket.gethostname())
    probe = admin_probe or admin_probe_http
    # git, systemctl et l'admin partent ensemble (l'admin fait lui-même ses deux lectures en
    # parallèle) : 2,5 s d'ordinaire, 6 s au pire quand l'admin tarde à lister ses runs.
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_code = pool.submit(code_version, root, runner)
        f_svc = pool.submit(services_state, runner)
        f_admin = pool.submit(probe)
        snap["code"] = guard("code", f_code.result)
        snap["services"] = guard("services", f_svc.result)
        admin = guard("admin", f_admin.result, {"reachable": False, "busy": None,
                                                "error": "sonde en échec"})
    snap.update(guard("system", lambda: system_facts(proc_root, disk_path), {}) or {})
    admin = admin if isinstance(admin, dict) else {"reachable": False, "busy": None}
    busy = admin.get("busy")
    busy_unknown = bool(admin.get("busy_unknown"))
    if not admin.get("reachable") or busy_unknown:
        # L'admin ne répond pas, ou pas sur la liste de ses runs : le marqueur dit encore s'il y
        # a un balayage ou une saisie (ils l'écrivent, qu'ils viennent de l'admin ou du terminal).
        marker = guard("marker", lambda: run_marker.read_marker(root))
        if isinstance(marker, dict):
            busy = {"run_id": marker.get("run_id"), "kind": marker.get("kind"),
                    "source": marker.get("source", "cli"), "pid": marker.get("pid"),
                    "started_at": marker.get("started_at")}
            busy_unknown = False
    snap["admin"] = {k: v for k, v in admin.items() if k in
                     ("reachable", "error", "latency_ms", "via", "busy_unknown", "busy_error")}
    snap["admin"]["busy"] = scrub(busy) if isinstance(busy, dict) else None
    task = guard("task", lambda: classify_task(root, busy, runs_dir=runs_dir, log_dir=log_dir,
                                               proc_root=proc_root, busy_unknown=busy_unknown),
                 {"type": "autre", "label": "Tâche illisible", "kind": None})
    logs = guard("logs", lambda: collect_logs(log_dir, log_sources(task)), []) or []
    snap["logs"] = logs
    # « Journal du run en cours » seulement quand un run est déclaré ; sinon ce sont les lignes
    # du dernier balayage (repos, tâche inconnue, maintenance).
    snap["logs_live"] = bool(task.get("run_id"))
    snap["reboot_required"] = bool(guard("reboot_required", reboot_flag.exists, False))
    snap["last_maintenance"] = guard("last_maintenance", lambda: last_maintenance(root))
    snap["alerts"] = guard("alerts", lambda: build_alerts(
        task=task, logs=logs, disk=snap.get("disk"), reboot_required=snap["reboot_required"],
        last_maint=snap["last_maintenance"]), []) or []
    snap["task"] = guard("task_public", lambda: scrub(_public(task)),
                         {"type": "autre", "label": "Tâche illisible"})
    snap["errors"] = errors
    return snap
