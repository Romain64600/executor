#!/usr/bin/env python3
"""Maintenance d'UN VPS de l'exécuteur : mise à jour Debian, redémarrage si Debian l'exige, puis
contrôles et relance du balayage qui tournait — sur la machine elle-même.

Romain, 2026-09-30 : « on va pouvoir travailler sur un script de restart, que tu feras passer sur
les VPS esclaves puis le tien », puis « go pour la v2 » après la revue de son premier jet. Ce que
la v2 corrige, et donc ce que ce script garantit :

* **Une saisie n'est jamais coupée en plein clic.** Les balayages ne vivent pas dans tmux : ce sont
  des enfants du service ``aks-admin``. Avant toute chose, le script demande à l'admin s'il y a un
  run ; un balayage ``data_entry_auto`` lancé par l'admin est ARRÊTÉ par « Arrêter » — mais
  SEULEMENT à un moment sûr (entre deux pages, en lecture, en matching, en pause : jamais pendant
  la saisie ni un déplacement), parce que l'arrêt coopératif a une grâce fixe (75 s pour la saisie
  d'une page, 120 s pour le balayage) au-delà de laquelle l'offre en cours serait tuée. Le script
  attend ensuite qu'il n'ait plus d'enfant, et note de quoi le relancer (les marchands ajoutés en
  cours de route compris, lus dans le recap final). Pas de moment sûr dans le délai, ou tout autre
  run (saisie par page, tri, run lancé au terminal) : la maintenance de ce VPS est REPORTÉE, rien
  n'est touché.
* **La mise à jour ne redémarre aucun service** (``NEEDRESTART_MODE=l`` et ``NEEDRESTART_SUSPEND``),
  garde les fichiers de config modifiés (``--force-confdef --force-confold`` : nginx, ufw…), attend
  le verrou d'apt (``DPkg::Lock::Timeout``) — les mises à jour automatiques tournent aussi.
  Chromium reste bloqué en version (``apt-mark hold``, vérifié et rapporté).
* **Redémarrage seulement si Debian l'exige** (``/var/run/reboot-required``) et si la politique du
  VPS l'autorise (``--reboot never`` pour le VPS de secours, qui porte aussi le projet price check
  du compte ``hermes`` : un redémarrage le couperait). Le redémarrage est programmé 10 s plus tard
  (``systemd-run``) pour que la connexion qui l'a demandé se ferme proprement, avec le code 42.
* **Au démarrage suivant, le service ``aks-maint-postboot``** (``ops/aks-maint-postboot.service``,
  installé par ``run``) fait la fin du travail sur place — contrôles puis relance —, que le pilote
  soit là ou non (c'est ce qui permet de redémarrer la machine qui pilote, en dernier).
* **Rien n'est relancé sans preuve** : services actifs, admin qui répond, invariants verts ET
  faisant foi (``scripts/01_check_invariants.py``), session AKS prouvée (tableau de bord wp-admin,
  même preuve que le transfert de cookies). Une session perdue : aucune relance, message Discord —
  la reconnexion reste le transfert de cookies par Romain, jamais déclenché par le code.
* **Jamais ``tmux kill-server``** : ni utile (le serveur tmux garde son binaire jusqu'à son
  prochain démarrage) ni sûr (il porte des sessions de travail, dont celle de Claude).
* **Ré-audit Codex du 06/10 (sur ``2c5cb19``), quatre défauts de maintenance corrigés :** un recap
  PÉRIMÉ ne donne plus un moment sûr (horodatages bornés — ``STAGE_FRESH_S`` —, et le verrou du
  navigateur tenu par autre chose qu'une extraction interdit l'arrêt, quoi que dise le recap) ;
  le ``git pull`` se fait SOUS le verrou du navigateur après un contrôle relu (un run démarré entre
  l'arrêt et le pull → pull NON fait) ; une erreur de ``pgrep`` est « illisible » (maintenance
  reportée, redémarrage refusé), jamais « zéro processus » ; les marchands ajoutés à une boucle
  depuis la console restent des ajouts d'UNE passe : la boucle repart sur ses cibles de lancement
  et les ajouts encore dus sont remis en file par la route de la console (``add-target``).

Sous-commandes (sorties JSON, une ligne) ::

    python3 scripts/18_vps_maintenance.py status              # lecture seule
    python3 scripts/18_vps_maintenance.py run --dry-run       # le plan, rien ne change
    python3 scripts/18_vps_maintenance.py run [--reboot auto|never]
    python3 scripts/18_vps_maintenance.py postboot            # appelé par le service au démarrage

Codes de sortie : 0 fait (sans redémarrage) · 42 redémarrage programmé · 3 reporté (run en cours
non arrêtable, pas de moment sûr, arrêt non abouti — rien d'autre n'a été fait) · 4 mise à jour en
échec · 5 contrôles d'après-maintenance en échec (rien relancé) · 6 relance refusée par l'admin ·
7 panne APRÈS l'arrêt du balayage (rien relancé, message Discord) · 2 usage. Le redémarrage est
décidé APRÈS la mise à jour, sur un état relu (un run relancé entre-temps l'empêche). Un ``SIGHUP``
(ssh coupé) n'interrompt pas la maintenance.

Tourne sous ``debian`` (le propriétaire du clone et de ``state/``), ``sudo`` sans mot de passe pour
apt / systemctl. État : ``state/maintenance/`` (jamais commité).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADMIN = "http://127.0.0.1:8650"
STATE_DIR = ROOT / "state" / "maintenance"
PENDING = "pending.json"          # écrit avant un redémarrage, lu (puis retiré) par postboot
LAST = "last_result.json"
REBOOT_REQUIRED = Path("/var/run/reboot-required")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
UNIT_NAME = "aks-maint-postboot.service"
UNIT_SRC = ROOT / "ops" / UNIT_NAME
UNIT_DST = Path("/etc/systemd/system") / UNIT_NAME
SERVICES = ("aks-admin", "aks-chromium", "hermes-cdp-proxy", "nginx")
HELD_EXPECTED = ("chromium",)
RELAUNCH_BY = "maintenance VPS (go de Romain, 2026-09-30)"

EXIT_OK, EXIT_USAGE, EXIT_BUSY, EXIT_APT, EXIT_CHECKS, EXIT_RELAUNCH = 0, 2, 3, 4, 5, 6
EXIT_CRASH = 7            # une panne APRÈS l'arrêt du balayage : rien relancé, le dire bien fort
EXIT_REBOOT = 42
# Les étapes où l'on peut demander l'arrêt sans risquer une écriture coupée (revue adverse du
# 30/09, P0) : « Arrêter » est coopératif, mais 10_data_entry_auto tue la saisie de la page après
# 75 s de grâce (et l'admin tue 10 à 120 s) — une offre longue peut être coupée entre le clic
# « Create » et sa preuve. On ne demande donc l'arrêt QUE hors écriture : entre deux pages, en
# lecture / matching, en pause — jamais pendant `submit` ni `move`.
# Ré-audit du 01/10 (P1) : « match » n'en fait plus partie — c'est l'étape qui PRÉCÈDE la saisie,
# et elle peut basculer en `submit` entre la lecture du recap et la demande d'arrêt. Depuis
# `probe` / `extract` / `pause`, l'étape suivante n'est jamais une écriture : l'arrêt coopératif
# est vu par 10 avant tout lancement de 05 (`should_stop` avant la saisie).
SAFE_STAGES = frozenset({"probe", "extract", "pause"})
WRITE_STAGES = frozenset({"submit", "move"})
# Ré-audit du 06/10 (P1) : le recap peut être PÉRIMÉ (une écriture de `recap.json` qui échoue
# est avalée par le balayage, un processus figé ne l'écrit plus) et dire « extract » pendant une
# saisie. Deux gardes indépendantes, lues sans rien toucher : (1) le VERROU DU NAVIGATEUR — une
# saisie (05) ou un déplacement (06) le tient tant qu'il vit ; tenu par autre chose qu'une
# extraction (02), ce n'est jamais un moment sûr, quoi que dise le recap ; (2) la FRAÎCHEUR des
# horodatages — `stage_at` d'une étape sûre, `updated_at` du recap entre deux pages,
# `updated_at` de `loop.json` en pause (battement toutes les ~60 s). Au-delà de la borne, ou
# sans horodatage, le recap est tenu pour périmé : pas d'arrêt, on réessaie 10 s plus tard (une
# borne dépassée à tort ne coûte qu'un délai — jamais une saisie coupée).
STAGE_FRESH_S = 15 * 60          # probe / extract / entre deux pages / avant le 1er marchand
PAUSE_MARGIN_S = 5 * 60          # pause de reprise : stage_at + wait_s + cette marge
LOOP_PAUSE_FRESH_S = 5 * 60      # loop.json en pause : battement de cœur ~60 s
EXTRACT_LABEL = "02_extract"     # le seul détenteur du navigateur compatible avec un moment sûr

# La mise à jour : jamais d'invite, jamais de service redémarré par needrestart, les fichiers de
# config locaux gardés, le verrou d'apt attendu (unattended-upgrades).
APT_ENV = ("DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=l", "NEEDRESTART_SUSPEND=1",
           "APT_LISTCHANGES_FRONTEND=none")
APT_OPTS = ("-o", "DPkg::Lock::Timeout=600",
            "-o", "Dpkg::Options::=--force-confdef",
            "-o", "Dpkg::Options::=--force-confold")


def apt_commands() -> list[list[str]]:
    """Les trois commandes apt, dans l'ordre (``sudo env … apt-get …``)."""

    base = ["sudo", "env", *APT_ENV, "apt-get", *APT_OPTS]
    return [base + ["update"],
            base + ["-y", "full-upgrade"],
            base + ["-y", "autoremove"]]


# ── petites briques (injectables pour les tests) ─────────────────────────────────────
Runner = Callable[..., subprocess.CompletedProcess]


def run_cmd(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"timeout {timeout}s")


def emit(obj: Any) -> None:
    """Une ligne JSON sur stdout — sans jamais lever si le pilote a coupé la connexion."""

    try:
        print(json.dumps(obj, ensure_ascii=False), flush=True)
    except (BrokenPipeError, OSError):
        pass


def admin_request(path: str, body: dict | None = None, timeout: int = 20) -> dict[str, Any]:
    """GET (body None) ou POST JSON vers l'admin local. Lève sur une panne réseau ou un 4xx/5xx
    (le message de l'admin est gardé)."""

    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(ADMIN + path, data=data, method="GET" if body is None else "POST",
                                 headers={"X-AKS-Admin": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"admin {path} → HTTP {exc.code}: {detail}") from exc


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def boot_id() -> str:
    try:
        return BOOT_ID.read_text().strip()
    except OSError:
        return ""


# ── ce qui tourne, et de quoi le relancer ─────────────────────────────────────────────
def _argv_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def remaining_targets(targets: list[dict], recap: dict | None, loop: bool) -> list[dict]:
    """Les marchands à relancer. Une BOUCLE repart entière (c'est sa nature). Un balayage simple
    reprend au marchand qui était EN COURS à l'arrêt (depuis sa page la plus haute, comme tout
    balayage) et garde ceux qui suivent ; ceux qu'il avait finis ne sont pas refaits."""

    if loop or not recap:
        return list(targets)
    started = [t.get("merchant") for t in (recap.get("targets") or []) if isinstance(t, dict)]
    if not started:
        return list(targets)
    current = started[-1]
    names = [t.get("merchant") for t in targets]
    if current not in names:
        return list(targets)
    return list(targets[names.index(current):])


def relaunch_spec(run_dir: Path) -> dict[str, Any] | None:
    """Le corps de ``POST /api/data-entry/auto`` qui relancera ce balayage, lu dans ce que l'admin a
    écrit au lancement (``admin_submit.json`` : cibles, liste, consoles, arrêt par marchand ; son
    ``argv`` : toutes pages, boucle, page de départ). None si le lancement est illisible."""

    meta = read_json(run_dir / "admin_submit.json")
    if not isinstance(meta, dict) or not isinstance(meta.get("targets"), list):
        return None
    argv = [str(a) for a in (meta.get("argv") or [])]
    loop = "--loop" in argv
    recap = read_json(run_dir / "recap.json")
    loop_status = read_json(run_dir / "loop.json") if loop else None
    if loop and isinstance(loop_status, dict):
        current = loop_status.get("current_run_id")
        if current:
            recap = read_json(run_dir.parent / str(current) / "recap.json") or recap
    targets = [{"merchant": str(t.get("merchant")), "store_id": str(t.get("store_id"))}
               for t in meta["targets"] if isinstance(t, dict)]
    body: dict[str, Any] = {
        "targets": remaining_targets(targets, recap if isinstance(recap, dict) else None, loop),
        "confirm": "GO",
        "continue_on_halt": bool(meta.get("continue_on_halt")),
        "consoles": bool(meta.get("consoles", True)),
        "list": int(meta.get("list_id") or 9),
        "loop": loop,
        "all_pages": "--all-pages" in argv,
        "by": RELAUNCH_BY,
    }
    if meta.get("max_pages") is not None and not body["all_pages"]:
        body["max_pages"] = int(meta["max_pages"])
    start = _argv_value(argv, "--start-page")
    if start is not None:
        body["start_page"] = int(start)
    return body


def live_recap(run_dir: Path) -> dict | None:
    """Le recap VIVANT d'un balayage : celui de la passe courante pour une boucle."""

    loop = read_json(run_dir / "loop.json")
    if isinstance(loop, dict) and loop.get("current_run_id"):
        rec = read_json(run_dir.parent / str(loop["current_run_id"]) / "recap.json")
        if isinstance(rec, dict):
            return rec
    rec = read_json(run_dir / "recap.json")
    return rec if isinstance(rec, dict) else None


def parse_stamp(value: Any) -> float | None:
    """Un horodatage du dépôt (« 2026-10-06T10:00:00Z ») en secondes epoch ; None s'il est absent
    ou illisible (et un horodatage illisible n'est jamais « frais »)."""

    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _age_text(age: float | None) -> str:
    return "sans horodatage" if age is None else f"depuis {int(age) // 60} min {int(age) % 60} s"


def browser_holder() -> dict[str, Any]:
    """Qui tient le navigateur, lu SANS toucher au verrou (`lock_status` : étiquette + pid vivant)."""

    from src.browser_lock import lock_status
    return lock_status(ROOT)


def safe_to_stop(run_dir: Path, *, now: float | None = None,
                 holder: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Peut-on demander l'arrêt MAINTENANT sans risquer une écriture coupée ? Illisible = non,
    périmé = non (ré-audit du 06/10, P1 : voir STAGE_FRESH_S), navigateur tenu par une autre
    chose qu'une extraction = non."""

    now = time.time() if now is None else now
    held = browser_holder() if holder is None else holder
    if held.get("held") and not str(held.get("label") or "").startswith(EXTRACT_LABEL):
        return False, (f"navigateur tenu par {held.get('label') or '?'} (pid {held.get('pid')}) "
                       "— une écriture peut être en cours, quoi que dise le recap")

    def fresh(stamp: Any, bound: float) -> tuple[bool, float | None]:
        ts = parse_stamp(stamp)
        age = None if ts is None else now - ts
        return (age is not None and age <= bound), age

    loop = read_json(run_dir / "loop.json")
    if isinstance(loop, dict) and loop.get("state") == "pause":
        ok, age = fresh(loop.get("updated_at"), LOOP_PAUSE_FRESH_S)
        if not ok:
            return False, f"loop.json périmé (pause sans battement, {_age_text(age)})"
        return True, "boucle en pause"
    rec = live_recap(run_dir)
    if rec is None:
        return False, "recap illisible"
    rec_ok, rec_age = fresh(rec.get("updated_at"), STAGE_FRESH_S)
    targets = rec.get("targets") or []
    if not targets:
        if not rec_ok:
            return False, f"recap périmé (aucun marchand démarré, dernière écriture {_age_text(rec_age)})"
        return True, "aucun marchand démarré"
    current = (targets[-1].get("recap") or {}).get("current") if isinstance(targets[-1], dict) else None
    if current is None:
        if not rec_ok:
            return False, f"recap périmé (entre deux pages, dernière écriture {_age_text(rec_age)})"
        return True, "entre deux pages"
    stage = str(current.get("stage") or "")
    if stage in SAFE_STAGES:
        bound = STAGE_FRESH_S
        if stage == "pause":
            try:
                bound = float(current.get("wait_s") or 0) + PAUSE_MARGIN_S
            except (TypeError, ValueError):
                bound = PAUSE_MARGIN_S
        ok, age = fresh(current.get("stage_at"), bound)
        if not ok:
            return False, (f"recap périmé (étape {stage} {_age_text(age)}, borne {int(bound)} s) "
                           "— l'étape réelle est inconnue")
        return True, f"étape {stage}"
    return False, f"écriture en cours ({stage or '?'}, page {current.get('page')})"


def wait_safe_boundary(run_dir: Path, *, timeout: int,
                       sleep: Callable[[float], None] = time.sleep) -> tuple[bool, str]:
    waited, why = 0, ""
    while waited <= timeout:
        ok, why = safe_to_stop(run_dir)
        if ok:
            return True, why
        sleep(10)
        waited += 10
    return False, f"pas de moment sûr en {timeout} s ({why}) — rien n'a été arrêté"


def remaining_after_stop(recap: dict | None) -> list[dict] | None:
    """Après l'arrêt d'un balayage SIMPLE, ce qui reste à faire, lu dans son recap FINAL (revue
    adverse du 30/09 : les marchands ajoutés en cours de route par la console ne sont pas dans
    le lancement) : le marchand interrompu (halte « operator_stop ») puis ``targets_not_reached``
    (cibles prévues jamais démarrées, ajouts tardifs compris — déjà passés par la liste blanche).
    None si le recap n'a pas cette forme (on retombe alors sur le lancement)."""

    if not isinstance(recap, dict) or not isinstance(recap.get("targets"), list):
        return None
    out: list[dict] = []
    targets = recap["targets"]
    if targets and isinstance(targets[-1], dict):
        last = targets[-1]
        if ((last.get("recap") or {}).get("halted") == "operator_stop"):
            out.append({"merchant": str(last.get("merchant")), "store_id": str(last.get("store_id"))})
    for t in recap.get("targets_not_reached") or []:
        if isinstance(t, dict) and t.get("merchant"):
            item = {"merchant": str(t["merchant"]), "store_id": str(t.get("store_id"))}
            if item not in out:
                out.append(item)
    return out


RESOLV_CONF = Path("/etc/resolv.conf")
# Le fichier de /run que chaque gestionnaire DNS régénère au démarrage → son service.
DNS_MANAGERS = (("/run/resolvconf/", "resolvconf"), ("/run/systemd/resolve/", "systemd-resolved"))


def dns_survives_reboot(runner: Runner = run_cmd) -> tuple[bool, str]:
    """Le DNS reviendra-t-il après un redémarrage ? Leçon du 2026-09-30 (ancienne VM) : son
    ``/etc/resolv.conf`` pointe vers ``/run/resolvconf/resolv.conf``, que personne ne régénérait
    au démarrage (``resolvconf.service`` désactivé) — après le redémarrage, plus aucun nom ne se
    résolvait, AKS injoignable, rien relancé. /run est effacé à chaque démarrage : le service qui
    le remplit doit être activé."""

    try:
        target = os.path.realpath(RESOLV_CONF)
    except OSError:
        return False, "resolv.conf illisible"
    for prefix, service in DNS_MANAGERS:
        if target.startswith(prefix):
            res = runner(["systemctl", "is-enabled", service], timeout=20)
            state = (res.stdout or "").strip()
            # Ré-audit du 01/10 (P2) : `enabled-runtime` est une activation TEMPORAIRE (perdue au
            # redémarrage) ; `static` (sans [Install]) ne compte que s'il tourne déjà, donc tiré
            # par une dépendance.
            if state in ("enabled", "alias"):
                return True, f"{service} activé"
            if state == "static" and runner(["systemctl", "is-active", "--quiet", service],
                                            timeout=20).returncode == 0:
                return True, f"{service} statique et actif"
            return False, (f"/etc/resolv.conf → {target}, mais {service} n'est pas activé "
                           f"({state or 'inconnu'}) : le DNS ne reviendrait pas après un redémarrage")
    return True, f"resolv.conf fixe ({target})"


def pgrep_count(res: subprocess.CompletedProcess) -> int | None:
    """Ce que dit un `pgrep` : 0 = des processus (comptés), 1 = aucun, tout autre code (2 usage,
    3 fatal, 124 délai) = ILLISIBLE → None, jamais zéro (ré-audit du 06/10, P2 : une erreur de
    pgrep passait pour « aucun processus », donc pour un feu vert)."""

    if res.returncode == 0:
        return len([x for x in (res.stdout or "").split() if x.strip()])
    if res.returncode == 1:
        return 0
    return None


def admin_children(runner: Runner = run_cmd) -> int | None:
    """Le nombre de processus enfants du service aks-admin (None si illisible)."""

    pid = runner(["systemctl", "show", "aks-admin", "-p", "MainPID", "--value"], timeout=20)
    main = (pid.stdout or "").strip()
    if pid.returncode != 0 or not main.isdigit() or main == "0":
        return None
    return pgrep_count(runner(["pgrep", "-P", main], timeout=20))


def hermes_processes(runner: Runner = run_cmd) -> int | None:
    """Les processus du compte hermes (price check, VPS de secours) : 0 quand le compte n'existe
    pas sur cette machine (A, B — `pgrep -u` y rend 2 « invalid user name », qui n'est PAS un
    zéro), None si illisible."""

    user = runner(["getent", "passwd", "hermes"], timeout=20)
    if user.returncode == 2:
        return 0                              # compte absent : aucun processus possible
    if user.returncode != 0:
        return None
    return pgrep_count(runner(["pgrep", "-u", "hermes"], timeout=20))


# ── l'état (lecture seule) ────────────────────────────────────────────────────────────
def status(runner: Runner = run_cmd, admin: Callable[..., dict] = admin_request) -> dict[str, Any]:
    out: dict[str, Any] = {"host": socket.gethostname(), "at": utc_now(), "boot_id": boot_id(),
                           "reboot_required": REBOOT_REQUIRED.exists()}
    try:
        busy = admin("/api/sort/runs").get("busy")
        out["admin"] = "ok"
    except Exception as exc:                  # noqa: BLE001
        busy, out["admin"] = None, f"injoignable: {exc}"
    out["busy"] = busy
    if isinstance(busy, dict) and busy.get("run_id"):
        run_dir = ROOT / "runs" / str(busy["run_id"])
        out["loop"] = isinstance(read_json(run_dir / "loop.json"), dict)
    out["admin_children"] = admin_children(runner)
    held = runner(["apt-mark", "showhold"], timeout=30)
    out["held"] = sorted((held.stdout or "").split())
    out["chromium_held"] = all(h in out["held"] for h in HELD_EXPECTED)
    up = runner(["apt", "list", "--upgradable"], timeout=120)
    out["upgradable"] = len([ln for ln in (up.stdout or "").splitlines() if "/" in ln])
    out["sudo"] = runner(["sudo", "-n", "true"], timeout=20).returncode == 0
    out["hermes_processes"] = hermes_processes(runner)
    out["dns_boot_ok"], out["dns_boot"] = dns_survives_reboot(runner)
    out["pending"] = (STATE_DIR / PENDING).exists()
    out["last_result"] = read_json(STATE_DIR / LAST)
    return out


# ── les étapes ────────────────────────────────────────────────────────────────────────
def plan_for(st: dict[str, Any], reboot_policy: str) -> dict[str, Any]:
    """Ce que ``run`` ferait, d'après l'état — et s'il doit s'arrêter avant de toucher à quoi
    que ce soit."""

    busy = st.get("busy")
    plan: dict[str, Any] = {"stop": None, "relaunch": None, "apt": True, "reboot": False,
                            "blocked": None}
    if st.get("admin") != "ok":
        plan["blocked"] = f"admin injoignable ({st.get('admin')}) — maintenance reportée"
        return plan
    if not st.get("sudo"):
        plan["blocked"] = "sudo sans mot de passe indisponible — maintenance reportée"
        return plan
    # Romain, 10/10/2026 (« Mets Chromium à jour, lève le hold ») : Chromium suit les mises à jour de sécurité comme les
    # autres paquets ; l'unité force toujours l'UA Chrome/149.0.0.0, l'invariant tient. `status` dit encore si un hold est
    # posé (`chromium_held`), à titre d'information ; un SIGTRAP après mise à jour se voit dans les alertes de la vue d'ensemble.
    if st.get("admin_children") is None:
        plan["blocked"] = ("processus d'aks-admin illisibles (systemctl / pgrep en erreur) — on ne "
                           "saurait ni arrêter ni prouver l'arrêt ; maintenance reportée")
        return plan
    if isinstance(busy, dict) and busy.get("run_id"):
        if busy.get("kind") != "data_entry_auto" or busy.get("source", "admin") != "admin":
            plan["blocked"] = (f"run {busy.get('kind')} ({busy.get('source', 'admin')}) "
                               f"{busy.get('run_id')} en cours — non relançable d'ici, "
                               "maintenance reportée")
            return plan
        plan["stop"] = busy.get("run_id")
    elif st.get("admin_children"):
        plan["blocked"] = (f"{st.get('admin_children')} processus sous aks-admin sans run déclaré "
                           "— maintenance reportée")
        return plan
    if st.get("reboot_required") and st.get("dns_boot_ok") is False and reboot_policy == "auto":
        plan["reboot"] = False
        plan["reboot_note"] = f"redémarrage requis mais NON fait : {st.get('dns_boot')}"
        return plan
    if st.get("reboot_required"):
        if reboot_policy != "auto":
            plan["reboot"] = False
            plan["reboot_note"] = "redémarrage requis par Debian, NON fait (politique « never »)"
        elif st.get("hermes_processes") is None:
            plan["reboot_note"] = ("redémarrage requis mais les processus du compte hermes sont "
                                   "illisibles — NON fait")
        elif st.get("hermes_processes"):
            plan["reboot_note"] = ("redémarrage requis mais le compte hermes (price check) a des "
                                   "processus — NON fait (--allow-hermes pour forcer)")
        else:
            plan["reboot"] = True
    return plan


def stop_and_wait(run_id: str, *, timeout: int, runner: Runner = run_cmd,
                  admin: Callable[..., dict] = admin_request,
                  sleep: Callable[[float], None] = time.sleep,
                  run_dir: Path | None = None) -> tuple[bool, str]:
    """Attendre un moment SÛR (hors écriture), « Arrêter » (coopératif), puis attendre : plus de
    run déclaré ET plus d'enfant. Pas de moment sûr dans le délai → rien n'est arrêté."""

    safe, why_safe = wait_safe_boundary(run_dir or (ROOT / "runs" / run_id), timeout=timeout,
                                        sleep=sleep)
    if not safe:
        return False, why_safe
    try:
        answer = admin("/api/sort/stop", {})
    except Exception as exc:                  # noqa: BLE001
        return False, f"arrêt refusé : {exc}"
    # Filet (ré-audit du 01/10) : si l'étape a basculé en écriture entre la lecture et l'arrêt,
    # on le DIT — l'arrêt coopératif finit l'offre en cours, mais la grâce de 75 s existe.
    rec = live_recap(run_dir or (ROOT / "runs" / run_id)) or {}
    cur = ((rec.get("targets") or [{}])[-1].get("recap") or {}).get("current") or {}
    note = ""
    if str(cur.get("stage") or "") in WRITE_STAGES:
        note = (f" — ATTENTION : une {cur.get('stage')} a démarré entre la lecture et l'arrêt "
                f"(page {cur.get('page')}) ; vérifier ses offres UNKNOWN")
    waited = 0
    busy, kids = "?", None
    while waited <= timeout:
        try:
            busy = admin("/api/sort/runs").get("busy")
        except Exception:                     # noqa: BLE001
            busy = "?"
        kids = admin_children(runner)
        if busy is None and kids == 0:
            return True, f"arrêté ({run_id}, {why_safe}) en {waited} s{note}"
        sleep(10)
        waited += 10
    seen = (f"run {busy.get('run_id') if isinstance(busy, dict) else busy}, enfants d'aks-admin "
            f"{'illisibles' if kids is None else kids}")
    return False, f"toujours actif après {timeout} s ({seen}) — rien d'autre n'est fait"


def apt_upgrade(runner: Runner = run_cmd, log: Path | None = None) -> tuple[bool, str]:
    lines = []
    for cmd in apt_commands():
        res = runner(cmd, timeout=3600)
        lines.append(f"$ {' '.join(cmd)}\n{res.stdout}\n{res.stderr}")
        if res.returncode != 0:
            if log:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("\n".join(lines), encoding="utf-8")
            return False, f"{cmd[-1]} → code {res.returncode}: {(res.stderr or res.stdout)[-300:]}"
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(lines), encoding="utf-8")
    return True, "à jour"


def install_postboot_unit(runner: Runner = run_cmd) -> tuple[bool, str]:
    """Installe (ou garde) le service qui finit le travail au démarrage."""

    want = UNIT_SRC.read_text(encoding="utf-8")
    try:
        have = UNIT_DST.read_text(encoding="utf-8")
    except OSError:
        have = None
    if have != want:
        res = runner(["sudo", "install", "-m", "0644", str(UNIT_SRC), str(UNIT_DST)], timeout=60)
        if res.returncode != 0:
            return False, f"install du service : {res.stderr.strip()[:200]}"
        runner(["sudo", "systemctl", "daemon-reload"], timeout=60)
    res = runner(["sudo", "systemctl", "enable", UNIT_NAME], timeout=60)
    if res.returncode != 0:
        return False, f"enable du service : {res.stderr.strip()[:200]}"
    return True, "service de fin de maintenance prêt"


def schedule_reboot(runner: Runner = run_cmd) -> tuple[bool, str]:
    """Redémarre TOUT DE SUITE (``systemctl reboot``, asynchrone). Appelé sous le verrou du
    navigateur, que l'appelant garde jusqu'à l'extinction : aucun run ne peut écrire entre-temps."""

    res = runner(["sudo", "systemctl", "reboot"], timeout=60)
    return res.returncode == 0, (res.stderr or res.stdout).strip()[:200]


# ── après la maintenance (sur place ; au démarrage si redémarrage) ──────────────────────
def check_session() -> tuple[bool, str]:
    """La session AKS : le tableau de bord wp-admin, prouvé comme au transfert de cookies (URL
    sous /wp-admin/ sans marqueur de connexion ET barre d'admin présente). Lecture seule."""

    try:
        from src.aks_env import OFFICIAL_CDP_ENDPOINT
        from src.browser_lock import browser_lock
        from src.login_session import LoginSession
        with browser_lock(ROOT, label="maintenance: session check"), \
                LoginSession(OFFICIAL_CDP_ENDPOINT) as session:
            session.navigate(LoginSession.ADMIN_URL)
            verdict = session.verify_dashboard()
    except Exception as exc:                  # noqa: BLE001
        return False, f"vérification impossible : {exc}"
    return bool(verdict.get("ok")), ("connectée" if verdict.get("ok")
                                     else f"NON connectée ({verdict.get('url', '')[:80]})")


def check_invariants(runner: Runner = run_cmd) -> tuple[bool, str]:
    res = runner([sys.executable, str(ROOT / "scripts" / "01_check_invariants.py")], timeout=180)
    try:
        report = json.loads(res.stdout)
    except ValueError:
        return False, f"sortie illisible (code {res.returncode})"
    ok = bool(report.get("ok")) and bool(report.get("authoritative"))
    bad = [c.get("name") for c in report.get("checks", []) if not c.get("ok")]
    return ok, ("verts" if ok else f"KO {bad} authoritative={report.get('authoritative')}")


def wait_services(runner: Runner = run_cmd, timeout: int = 300,
                  sleep: Callable[[float], None] = time.sleep) -> tuple[bool, str]:
    waited, down = 0, list(SERVICES)
    while waited <= timeout:
        down = []
        for svc in SERVICES:
            exists = runner(["systemctl", "cat", svc], timeout=20).returncode == 0
            if exists and runner(["systemctl", "is-active", "--quiet", svc], timeout=20).returncode != 0:
                down.append(svc)
        if not down:
            return True, "actifs"
        sleep(10)
        waited += 10
    return False, f"inactifs : {down}"


def notify(text: str) -> None:
    try:
        from src.notify import notify as _notify
        _notify("maintenance", text, root=ROOT)
    except Exception:                         # noqa: BLE001 — un message n'arrête rien
        pass


def finish(relaunch: dict | None, *, context: dict[str, Any], runner: Runner = run_cmd,
           admin: Callable[..., dict] = admin_request,
           session_check: Callable[[], tuple[bool, str]] = check_session,
           sleep: Callable[[float], None] = time.sleep) -> tuple[int, dict[str, Any]]:
    """Contrôles, puis relance si tout est prouvé. Rend (code de sortie, résultat)."""

    result: dict[str, Any] = dict(context)
    result.update({"finished_at": utc_now(), "boot_id": boot_id(), "relaunched": None})
    ok_svc, result["services"] = wait_services(runner, sleep=sleep)
    admin_ok, busy = False, None
    for _ in range(18):                       # l'admin met quelques secondes à répondre
        try:
            busy = admin("/api/sort/runs").get("busy")
            admin_ok = True
            break
        except Exception:                     # noqa: BLE001
            sleep(10)
    result["admin"] = "ok" if admin_ok else "injoignable"
    ok_inv, why_inv = False, "non vérifiés"
    for attempt in range(3):                  # Chromium peut démarrer après l'admin
        ok_inv, why_inv = check_invariants(runner)
        if ok_inv:
            break
        sleep(30)
    result["invariants"] = why_inv
    ok_sess, result["session"] = session_check() if (ok_svc and admin_ok and ok_inv) else (False, "non vérifiée")
    checks_ok = ok_svc and admin_ok and ok_inv and ok_sess
    code = EXIT_OK
    if not checks_ok:
        code = EXIT_CHECKS
        if relaunch:
            result["relaunched"] = "NON — contrôles en échec, relance à faire à la main"
    elif relaunch:
        if busy:
            result["relaunched"] = f"NON — un run tourne déjà ({busy.get('run_id')})"
        else:
            try:
                ans = admin("/api/data-entry/auto", relaunch)
                result["relaunched"] = ans.get("run_id") if ans.get("started") else f"refusé : {ans}"
                if not ans.get("started"):
                    code = EXIT_RELAUNCH
                elif context.get("additions_due"):
                    result["additions"] = requeue_additions(list(context["additions_due"]),
                                                            str(ans.get("run_id") or ""), admin=admin)
            except Exception as exc:          # noqa: BLE001
                result["relaunched"] = f"refusé : {exc}"
                code = EXIT_RELAUNCH
    result["exit"] = code
    write_json(STATE_DIR / LAST, result)
    notify(f"🔧 Maintenance {result.get('host')} : services {result['services']}, invariants "
           f"{result['invariants']}, session AKS {result['session']}"
           + (f", relance : {result['relaunched']}" if relaunch else ", rien à relancer")
           + (f", ajouts remis en file : {sum(1 for a in result['additions'] if a.get('queued'))}"
              f"/{len(result['additions'])}" if result.get("additions") else "")
           + (f", apt : {result.get('apt')}" if result.get('apt') else ""))
    return code, result


# ── les sous-commandes ────────────────────────────────────────────────────────────────
def reboot_decision(policy: str, allow_hermes: bool, *, runner: Runner = run_cmd,
                    admin: Callable[..., dict] = admin_request) -> tuple[bool, str]:
    """Redémarrer MAINTENANT ? Relu juste avant de programmer le redémarrage, jamais pris de
    l'état d'avant apt (revue adverse du 30/09, P0) : un run relancé pendant la mise à jour, ou
    un redémarrage devenu nécessaire à cause d'elle, doivent être vus."""

    if not REBOOT_REQUIRED.exists():
        return False, "pas de redémarrage requis"
    if policy != "auto":
        return False, "redémarrage requis par Debian, NON fait (politique « never »)"
    dns_ok, dns_why = dns_survives_reboot(runner)
    if not dns_ok:
        return False, f"redémarrage requis, NON fait : {dns_why}"
    try:
        busy = admin("/api/sort/runs").get("busy")
    except Exception as exc:                  # noqa: BLE001
        return False, f"redémarrage requis, NON fait : admin injoignable ({exc})"
    if busy:
        return False, f"redémarrage requis, NON fait : un run a démarré entre-temps ({busy.get('run_id')})"
    kids = admin_children(runner)
    if kids is None:
        return False, "redémarrage requis, NON fait : processus d'aks-admin illisibles"
    if kids:
        return False, f"redémarrage requis, NON fait : {kids} processus sous aks-admin"
    hermes = hermes_processes(runner)
    if hermes is None:
        return False, "redémarrage requis, NON fait : processus du compte hermes illisibles"
    if hermes and not allow_hermes:
        return False, ("redémarrage requis, NON fait : le compte hermes (price check) a des "
                       f"processus ({hermes}) (--allow-hermes pour forcer)")
    return True, "redémarrage requis"


def git_pull(runner: Runner = run_cmd) -> str:
    res = runner(["git", "-C", str(ROOT), "pull", "-q", "--ff-only"], timeout=300)
    head = runner(["git", "-C", str(ROOT), "log", "--oneline", "-1"], timeout=30)
    return ("à jour : " if res.returncode == 0 else f"pull refusé ({res.stderr.strip()[:120]}) : ") + \
        (head.stdout or "").strip()[:80]


def pull_under_lock(runner: Runner = run_cmd, admin: Callable[..., dict] = admin_request) -> str:
    """`git pull` SOUS le verrou du navigateur, après un contrôle RELU sous ce verrou (ré-audit du
    06/10, P1) : entre l'arrêt du balayage et le pull, la console était libre — un run lancé dans
    cette fenêtre tournait sur un clone qui changeait sous lui. Désormais un run déjà lancé tient
    le verrou (ou se déclare à l'admin) → pull NON fait, motif nommé, la maintenance continue ; un
    run lancé pendant le pull ne peut pas ouvrir le navigateur. Jamais fatal : le code se tire au
    prochain passage."""

    from src.browser_lock import BrowserBusyError, browser_lock
    try:
        with browser_lock(ROOT, label="maintenance: mise à jour du code"):
            try:
                busy = admin("/api/sort/runs").get("busy")
            except Exception as exc:          # noqa: BLE001
                return f"pull NON fait : admin injoignable ({exc})"
            if busy:
                return f"pull NON fait : un run a démarré entre-temps ({busy.get('run_id')})"
            kids = admin_children(runner)
            if kids is None:
                return "pull NON fait : processus d'aks-admin illisibles"
            if kids:
                return f"pull NON fait : {kids} processus sous aks-admin"
            return git_pull(runner)
    except BrowserBusyError as exc:
        return f"pull NON fait : navigateur tenu ({exc})"


def reboot_under_lock(args: argparse.Namespace, context: dict[str, Any],
                      relaunch: dict | None, *, hold_s: float = 120.0,
                      sleep: Callable[[float], None] = time.sleep) -> int | None:
    """Décide et déclenche le redémarrage sous le verrou du navigateur. Rend 42 si la machine
    redémarre (après avoir émis le résultat), None sinon (``context["reboot"]`` dit pourquoi)."""

    from src.browser_lock import BrowserBusyError, browser_lock
    try:
        with browser_lock(ROOT, label="maintenance: redémarrage imminent"):
            reboot, context["reboot"] = reboot_decision(args.reboot, args.allow_hermes)
            if not reboot:
                return None
            ok_unit, why_unit = install_postboot_unit()
            if not ok_unit:
                context["reboot"] = f"non fait : {why_unit}"
                return None
            write_json(STATE_DIR / PENDING, {"context": context, "relaunch": relaunch,
                                             "at": utc_now()})
            ok_rb, why_rb = schedule_reboot()
            if not ok_rb:
                (STATE_DIR / PENDING).unlink(missing_ok=True)
                context["reboot"] = f"redémarrage refusé : {why_rb}"
                return None
            emit({"rebooting": True, "context": context})
            sleep(hold_s)                      # le verrou tient jusqu'à l'extinction
            return EXIT_REBOOT
    except BrowserBusyError as exc:
        context["reboot"] = f"redémarrage requis, NON fait : navigateur tenu par un run ({exc})"
        return None


def _key(t: Any) -> tuple[str, str]:
    return (str(t.get("merchant") or "").casefold(), str(t.get("store_id") or "")) if isinstance(t, dict) \
        else ("", "")


def loop_additions_due(meta_targets: list[dict], launch_dir: Path) -> list[dict]:
    """Les marchands AJOUTÉS depuis la console à une BOUCLE et encore DUS à l'arrêt (ré-audit du
    06/10, P2). Dans `scripts/10`, un ajout vaut pour UNE passe (`consumed`) ; la version du 01/10
    le mettait dans les cibles de la relance, donc dans TOUTES les passes à venir — un ajout
    temporaire rendu permanent. Désormais la boucle repart sur les cibles du lancement, et ces
    ajouts sont REMIS EN FILE, une fois chacun, par la route de la console (`requeue_additions`).
    Dû = dans `targets_queue.json` du lancement, pas une cible du lancement, ni refusé par une
    passe, ni pris par une passe FINIE, ni pris par la passe courante et balayé jusqu'au bout
    (démarré, fini, sans arrêt opérateur). « Une passe ou permanent » reste la décision 4 de
    l'audit du 02/10, à Romain : ici on suit ce que la boucle fait aujourd'hui."""

    queue = read_json(launch_dir / "targets_queue.json")
    entries = [q for q in (queue if isinstance(queue, list) else [])
               if isinstance(q, dict) and q.get("merchant") and str(q.get("store_id") or "")]
    if not entries:
        return []
    loop = read_json(launch_dir / "loop.json")
    loop = loop if isinstance(loop, dict) else {}
    current = str(loop.get("current_run_id") or "")
    passes = [str(p.get("run_id")) for p in (loop.get("passes") or [])
              if isinstance(p, dict) and p.get("run_id")]
    done = {_key(t) for t in meta_targets}
    refused: set[tuple[str, str]] = set()
    for pid in passes:
        rec = read_json(launch_dir.parent / pid / "recap.json")
        if not isinstance(rec, dict):
            continue
        refused |= {_key(t) for t in rec.get("targets_refused") or []}
        taken = {_key(t) for t in rec.get("targets_added") or []}
        if pid != current:
            done |= taken                     # une passe finie a balayé ce qu'elle avait pris
            continue
        for t in rec.get("targets") or []:    # la passe interrompue : fini sans arrêt = fait
            if (_key(t) in taken and isinstance(t, dict) and t.get("finished_at")
                    and (t.get("recap") or {}).get("halted") != "operator_stop"):
                done.add(_key(t))
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for q in entries:
        k = _key(q)
        if k in seen or k in refused or k in done:
            continue
        seen.add(k)
        out.append({"merchant": str(q["merchant"]), "store_id": str(q["store_id"])})
    return out


def requeue_additions(due: list[dict], run_id: str, *,
                      admin: Callable[..., dict] = admin_request) -> list[dict]:
    """Remet chaque ajout dû en file du balayage relancé, par la route de la console (le SEUL
    écrivain de `targets_queue.json`), avec les mêmes portes qu'un clic : liste blanche, GO, run
    affiché. Un refus est noté, jamais fatal."""

    out: list[dict] = []
    for t in due:
        body = {"merchant": t["merchant"], "store_id": t["store_id"], "confirm": "GO",
                "run_id": run_id, "by": RELAUNCH_BY}
        try:
            ans = admin("/api/data-entry/auto/add-target", body)
            out.append({**t, "queued": bool(ans.get("queued")), "reason": ans.get("reason")})
        except Exception as exc:              # noqa: BLE001
            out.append({**t, "queued": False, "reason": f"refusé : {exc}"[:200]})
    return out


def cmd_run(args: argparse.Namespace) -> int:
    # Une connexion ssh coupée ne doit pas tuer la maintenance au milieu d'apt.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    st = status()
    plan = plan_for(st, args.reboot)
    if args.dry_run and plan["stop"] and not plan["blocked"]:
        # À blanc : montrer ce qui serait relancé et si l'arrêt serait possible tout de suite.
        run_dir = ROOT / "runs" / str(plan["stop"])
        plan["relaunch"] = relaunch_spec(run_dir)
        if plan["relaunch"] and plan["relaunch"].get("loop"):
            plan["additions_due"] = loop_additions_due(plan["relaunch"]["targets"], run_dir)
        plan["safe_to_stop_now"] = safe_to_stop(run_dir)[1]
    if args.dry_run or plan["blocked"]:
        emit({"dry_run": args.dry_run, "status": st, "plan": plan})
        return EXIT_BUSY if plan["blocked"] else EXIT_OK
    context: dict[str, Any] = {"host": st["host"], "started_at": utc_now(),
                               "boot_id_before": st["boot_id"], "stopped": None, "apt": None}
    relaunch = None
    stopped = False
    if plan["stop"]:
        run_dir = ROOT / "runs" / str(plan["stop"])
        relaunch = relaunch_spec(run_dir)
        if relaunch is None:
            emit({"error": f"lancement de {plan['stop']} illisible — rien n'est arrêté"})
            return EXIT_BUSY
        ok, why = stop_and_wait(str(plan["stop"]), timeout=args.stop_timeout, run_dir=run_dir)
        context["stopped"] = why
        if not ok:
            emit({"error": why, "context": context})
            notify(f"🔧 Maintenance {st['host']} reportée : {why}")
            return EXIT_BUSY
        stopped = True
    try:
        if stopped and not relaunch.get("loop"):
            rest = remaining_after_stop(read_json(ROOT / "runs" / str(plan["stop"]) / "recap.json"))
            if rest is not None:
                relaunch["targets"] = rest
            if not relaunch["targets"]:
                relaunch = None               # il était au bout : rien à relancer
        elif stopped:
            # La boucle repart sur ses cibles de lancement ; les ajouts encore dus sont remis en
            # file après la relance (une passe chacun, comme dans la boucle).
            context["additions_due"] = loop_additions_due(relaunch["targets"],
                                                          ROOT / "runs" / str(plan["stop"]))
        if relaunch is not None:
            write_json(STATE_DIR / "relaunch.json", relaunch)
        if args.pull:
            context["code"] = pull_under_lock()
        ok_apt, context["apt"] = apt_upgrade(
            log=STATE_DIR / f"apt-{time.strftime('%Y%m%d-%H%M%S')}.log")
        if ok_apt:
            # Ré-audit du 01/10 (P1) : un run pouvait démarrer entre le contrôle et le
            # redémarrage. Le VERROU DU NAVIGATEUR est pris AVANT le contrôle et gardé jusqu'à
            # l'extinction : un run déjà lancé le tient (→ pas de redémarrage, motif nommé), un
            # run lancé après ne peut rien lire ni écrire (le navigateur lui est refusé).
            code_rb = reboot_under_lock(args, context, relaunch)
            if code_rb is not None:
                return code_rb
        else:
            context["reboot"] = "non fait : mise à jour en échec"
        code, result = finish(relaunch, context=context)
        emit(result)
        return EXIT_APT if not ok_apt else code
    except Exception as exc:                  # noqa: BLE001 — jamais une sortie muette
        context["error"] = repr(exc)[:400]
        context["exit"] = EXIT_CRASH
        context["relaunch_pending"] = relaunch
        try:
            write_json(STATE_DIR / LAST, dict(context, finished_at=utc_now(), boot_id=boot_id()))
        except Exception:                     # noqa: BLE001
            pass
        notify(f"🔧 Maintenance {st['host']} en PANNE après l'arrêt du balayage ({context['error']}) "
               "— rien n'a été relancé ; le corps de relance est dans state/maintenance/relaunch.json")
        emit({"error": context["error"], "context": context})
        return EXIT_CRASH


def cmd_postboot(args: argparse.Namespace) -> int:
    pending = read_json(STATE_DIR / PENDING)
    if not isinstance(pending, dict):
        return EXIT_OK                        # démarrage ordinaire : rien à finir
    context = dict(pending.get("context") or {})
    context["rebooted"] = context.get("boot_id_before") != boot_id()
    try:
        code, result = finish(pending.get("relaunch"), context=context)
    finally:
        (STATE_DIR / PENDING).unlink(missing_ok=True)
    emit(result)
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maintenance d'un VPS de l'exécuteur (voir le module).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="état, lecture seule")
    run = sub.add_parser("run", help="arrêt propre, mise à jour, redémarrage si requis, relance")
    run.add_argument("--dry-run", action="store_true", help="le plan seulement, rien ne change")
    run.add_argument("--reboot", choices=("auto", "never"), default="auto")
    run.add_argument("--allow-hermes", action="store_true",
                     help="redémarrer même si le compte hermes (price check) a des processus")
    run.add_argument("--stop-timeout", type=int, default=2700,
                     help="attente max d'un moment sûr puis de l'arrêt du balayage (s)")
    run.add_argument("--pull", action="store_true",
                     help="git pull --ff-only du clone APRÈS l'arrêt (jamais sous un balayage)")
    sub.add_parser("postboot", help="(service au démarrage) contrôles et relance")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        emit(status())
        return EXIT_OK
    if args.cmd == "run":
        return cmd_run(args)
    return cmd_postboot(args)


if __name__ == "__main__":
    raise SystemExit(main())
