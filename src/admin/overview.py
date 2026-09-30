"""La vue d'ensemble des VPS — lecture seule (Romain, 2026-09-30 : « Go pour l'onglet vue
d'ensemble »).

``GET /api/overview`` rend l'état de CHAQUE machine de l'exécuteur sur une seule page : UP / DOWN
et pourquoi, la tâche en cours en français, les créations, la version du code, la charge, les
alertes et les 20 derniers événements. La photo de chaque machine est ``src/vps_snapshot.py`` :

* **cette machine** : la photo est prise EN PROCESSUS, avec le ``busy()`` de l'admin (jamais un
  appel HTTP de l'admin vers lui-même) ;
* **les autres** : ``ssh`` avec une clé DÉDIÉE, bridée côté distant par une commande forcée
  (``command="python3 /home/debian/executor/scripts/20_vps_snapshot.py",restrict,…`` —
  ``ops/VUE_D_ENSEMBLE.md``). L'admin n'envoie AUCUNE commande : la ligne ssh n'en porte pas,
  et la clé ne sait rien faire d'autre que prendre la photo. ``IdentitiesOnly=yes`` : seule cette
  clé est présentée (jamais la clé de déploiement, qui ouvrirait un shell).

**Rien n'est piloté d'ici.** Pas de route d'écriture, aucune action relayée : pour agir sur une
machine, le lien « Ouvrir la console » mène à SA console.

Les machines viennent de ``state/overview_hosts.json`` (jamais commité — ``state/``). Sans ce
fichier, la page ne montre que cette machine. Format ::

    {"ssh_key": "/home/debian/.ssh/aks_overview_ed25519",
     "hosts": [
       {"name": "cette-vm", "label": "…", "ssh": null, "console_url": "https://…/executor/"},
       {"name": "ancienne-vm", "label": "…", "ssh": "debian@51.38.37.254",
        "console_url": "https://51.38.37.254.sslip.io/executor/"}]}

``ssh: null`` = cette machine (au plus une ; absente, elle est ajoutée en tête). ``key`` par
machine remplace ``ssh_key``. Une entrée invalide s'affiche en DOWN avec son motif, jamais en
silence.

Toutes les machines sont lues EN PARALLÈLE, 10 s au plus chacune ; une machine qui ne répond pas
est DOWN avec son erreur, jamais une exception. Le résultat est gardé 10 s : plusieurs onglets
ouverts ne multiplient pas les connexions ssh (un seul calcul à la fois, les autres attendent
puis relisent le cache). Bibliothèque standard seule.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from src import vps_snapshot
from src.vps_snapshot import scrub, scrub_text

CONFIG_NAME = "overview_hosts.json"
SSH_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 5
CACHE_TTL_S = 10.0
MAX_OUTPUT_BYTES = 512 * 1024
# Les services dont l'arrêt met la machine « DOWN ». Un service absent de la machine ne compte
# pas (la photo le dit « absent »).
KEY_SERVICES = vps_snapshot.SERVICES
OK_SERVICE_STATES = frozenset({"active", "reloading", "absent"})

# Un utilisateur@hôte, jamais une option : une cible qui commencerait par « - » serait lue par
# ssh comme une option (``-oProxyCommand=…``).
SSH_TARGET_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
# Le lien « Ouvrir la console » : http(s) seulement — jamais « javascript: » ni « data: ».
URL_RE = re.compile(r"^https?://[^\s\"'<>\\]{1,300}$")


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ssh_argv(key: str, target: str) -> list[str]:
    """La ligne ssh — SANS commande : c'est la commande forcée de la clé qui s'exécute."""

    return ["ssh", "-i", key, "-T",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "IdentitiesOnly=yes",
            target]


def run_ssh(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Lance ssh sans jamais lever : délai dépassé = 124, ssh absent = 127."""

    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"délai de {timeout:g} s dépassé")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"{type(exc).__name__}: {exc}")


def last_json(text: str) -> dict[str, Any] | None:
    """La DERNIÈRE ligne JSON d'une sortie (comme ``19_restart_vps.last_json``)."""

    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            return value if isinstance(value, dict) else None
    return None


def load_config(path: Path) -> dict[str, Any]:
    """``{"configured", "error", "hosts": [...]}`` — jamais une exception. Chaque hôte :
    ``{name, label, ssh, key, console_url, local, error}``."""

    local_default = {"name": "cette-vm", "label": "Cette machine", "ssh": None, "key": None,
                     "console_url": ".", "local": True, "error": None}
    out: dict[str, Any] = {"configured": False, "error": None, "hosts": []}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["hosts"] = [local_default]
        return out
    except (OSError, ValueError) as exc:
        out["error"] = scrub_text(f"{Path(path).name} illisible : {type(exc).__name__}: {exc}", 200)
        out["hosts"] = [local_default]
        return out
    if not isinstance(raw, dict) or not isinstance(raw.get("hosts", []), list):
        out["error"] = f"{Path(path).name} : un objet {{\"hosts\": [...]}} est attendu"
        out["hosts"] = [local_default]
        return out
    out["configured"] = True
    default_key = raw.get("ssh_key")
    seen: set[str] = set()
    hosts: list[dict[str, Any]] = []
    for i, entry in enumerate(raw.get("hosts") or []):
        if not isinstance(entry, dict):
            hosts.append({"name": f"hôte-{i + 1}", "label": "", "ssh": None, "key": None,
                          "console_url": None, "local": False,
                          "error": "entrée de configuration invalide (objet attendu)"})
            continue
        name = str(entry.get("name") or "").strip()
        host: dict[str, Any] = {
            "name": name if NAME_RE.match(name) else (scrub_text(name, 40) or f"hôte-{i + 1}"),
            "label": scrub_text(entry.get("label") or "", 80),
            "ssh": None, "key": None, "console_url": None, "local": False, "error": None,
        }
        url = entry.get("console_url")
        if isinstance(url, str) and URL_RE.match(url.strip()):
            host["console_url"] = url.strip()
        ssh = entry.get("ssh")
        if not NAME_RE.match(name):
            host["error"] = "nom invalide (lettres, chiffres, . _ -)"
        elif name in seen:
            host["error"] = "nom en double dans la configuration"
        elif ssh is None:
            if any(h.get("local") for h in hosts):
                host["error"] = "deux machines locales (ssh: null) — une seule autorisée"
            else:
                host["local"] = True
                host["console_url"] = host["console_url"] or "."
        elif not isinstance(ssh, str) or not SSH_TARGET_RE.match(ssh):
            host["error"] = "cible ssh invalide (attendu utilisateur@hôte)"
        else:
            host["ssh"] = ssh
            key = entry.get("key") or default_key
            if not isinstance(key, str) or not key.strip():
                host["error"] = "clé ssh non configurée (ssh_key)"
            elif not os.path.isabs(key) or "\n" in key:
                host["error"] = "clé ssh : chemin absolu attendu"
            else:
                host["key"] = key
        seen.add(name)
        hosts.append(host)
    if not any(h.get("local") for h in hosts):
        hosts.insert(0, local_default)
    out["hosts"] = hosts
    return out


def health(host: dict[str, Any]) -> list[str]:
    """Pourquoi la machine est DOWN — liste vide = UP. Injoignable, admin qui ne répond pas, un
    service clé arrêté : chacun est NOMMÉ."""

    if host.get("error"):
        return [str(host["error"])]
    snap = host.get("snapshot")
    if not isinstance(snap, dict):
        return ["pas de photo de la machine"]
    reasons: list[str] = []
    admin = snap.get("admin") if isinstance(snap.get("admin"), dict) else {}
    if not admin.get("reachable"):
        reasons.append("admin injoignable" + (f" ({admin['error']})" if admin.get("error") else ""))
    services = snap.get("services")
    if not isinstance(services, dict):
        why = (snap.get("errors") or {}).get("services") if isinstance(snap.get("errors"), dict) else None
        reasons.append("services illisibles" + (f" ({why})" if why else ""))
    else:
        for name in KEY_SERVICES:
            state = services.get(name)
            if state is not None and state not in OK_SERVICE_STATES:
                reasons.append(f"service {name} {state}")
    return reasons


class Overview:
    """L'état des machines, gardé ``ttl`` secondes. Coutures de test : ``runner`` (ssh),
    ``local_snapshot`` (la photo locale), ``clock`` (le cache)."""

    def __init__(self, repo_root: Path, *, runs_dir: Path | None = None,
                 log_dir: Path | None = None, busy: Callable[[], Any] | None = None,
                 config_path: Path | None = None,
                 runner: Callable[[list[str], float], subprocess.CompletedProcess] = run_ssh,
                 local_snapshot: Callable[[], dict[str, Any]] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 ttl: float = CACHE_TTL_S, timeout: float = SSH_TIMEOUT_S) -> None:
        self.repo_root = Path(repo_root)
        self.runs_dir = Path(runs_dir) if runs_dir is not None else self.repo_root / "runs"
        self.log_dir = Path(log_dir) if log_dir is not None else self.repo_root / "logs"
        self.busy = busy or (lambda: None)
        self.config_path = Path(config_path) if config_path is not None \
            else self.repo_root / "state" / CONFIG_NAME
        self.runner = runner
        self.local_snapshot = local_snapshot or self._local_snapshot
        self.clock = clock
        self.ttl = float(ttl)
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0

    # -- la photo de chaque machine ------------------------------------------------------
    def _local_snapshot(self) -> dict[str, Any]:
        busy = self.busy
        return vps_snapshot.snapshot(
            self.repo_root, runs_dir=self.runs_dir, log_dir=self.log_dir,
            admin_probe=lambda: {"reachable": True, "busy": busy(), "error": None,
                                 "via": "en processus"})

    def _read_local(self, host: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            snap = self.local_snapshot()
        except Exception as exc:              # noqa: BLE001 — la page s'affiche quoi qu'il arrive
            host.update(reachable=False, error=scrub_text(f"photo locale en échec : "
                                                          f"{type(exc).__name__}: {exc}", 200))
            return host
        host.update(reachable=True, snapshot=snap,
                    latency_ms=int((time.monotonic() - started) * 1000))
        return host

    def _read_remote(self, spec: dict[str, Any], *, into: dict[str, Any]) -> dict[str, Any]:
        host = into
        started = time.monotonic()
        res = self.runner(ssh_argv(spec["key"], spec["ssh"]), self.timeout)
        host["latency_ms"] = int((time.monotonic() - started) * 1000)
        stdout = res.stdout or ""
        if len(stdout.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES:
            host.update(reachable=False, error="réponse trop longue — refusée")
            return host
        snap = last_json(stdout)
        if snap is None:
            err = (res.stderr or "").strip().splitlines()
            detail = err[-1] if err else (stdout.strip()[:120] or f"code {res.returncode}")
            if res.returncode == 124:
                why = f"délai de {self.timeout:g} s dépassé"
            elif res.returncode == 255:
                why = f"ssh : {detail}"
            elif stdout.strip():
                why = f"réponse illisible : {detail}"
            else:
                why = f"aucune réponse (code {res.returncode}) : {detail}"
            host.update(reachable=False, error=scrub_text(why, 240))
            return host
        # Défense en profondeur : la machine distante filtre déjà, on refiltre ce qu'on relaie.
        host.update(reachable=True, snapshot=scrub(snap))
        return host

    def _read(self, host: dict[str, Any]) -> dict[str, Any]:
        base = {"name": host["name"], "label": host.get("label") or "",
                "console_url": host.get("console_url"), "local": bool(host.get("local")),
                "ssh": host.get("ssh"), "reachable": False, "latency_ms": None,
                "snapshot": None, "error": host.get("error")}
        try:
            if base["error"]:
                pass
            elif base["local"]:
                self._read_local(base)
            elif not self.key_exists(host["key"]):
                base["error"] = f"clé ssh absente : {host['key']}"
            else:
                # la clé sert à la ligne ssh ; elle ne part pas dans la réponse
                self._read_remote(dict(base, key=host["key"]), into=base)
        except Exception as exc:              # noqa: BLE001 — une machine DOWN, jamais une page en panne
            base.update(reachable=False, error=scrub_text(f"{type(exc).__name__}: {exc}", 200))
        reasons = health(base)
        base["status"] = "down" if reasons else "up"
        base["down_reasons"] = reasons
        return base

    @staticmethod
    def key_exists(path: str) -> bool:
        return os.path.isfile(path)

    # -- la réponse ----------------------------------------------------------------------
    def compute(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        hosts = config["hosts"]
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(hosts)))) as pool:
            results = list(pool.map(self._read, hosts))
        return {"at": _utc_now(), "hosts": results, "ttl_s": self.ttl,
                "config": {"file": f"state/{CONFIG_NAME}", "configured": config["configured"],
                           "error": config["error"]}}

    def payload(self) -> dict[str, Any]:
        """La réponse de ``GET /api/overview`` — depuis le cache s'il a moins de ``ttl`` s."""

        with self._lock:
            now = self.clock()
            if self._cache is not None and now - self._cache_at < self.ttl:
                return dict(self._cache, cached=True, age_s=round(now - self._cache_at, 1))
            payload = self.compute()
            self._cache, self._cache_at = payload, self.clock()
            return dict(payload, cached=False, age_s=0.0)
