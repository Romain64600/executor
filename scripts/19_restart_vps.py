#!/usr/bin/env python3
"""Pilote de la maintenance des VPS : un VPS après l'autre, les « esclaves » d'abord, la machine
qui pilote en dernier (Romain, 2026-09-30 : « que tu feras passer sur les VPS esclaves puis le
tien »). Chaque VPS fait son propre travail avec ``scripts/18_vps_maintenance.py`` ; ce pilote
l'y lance, attend son retour s'il redémarre, lit son résultat, et S'ARRÊTE au premier VPS qui ne
revient pas au vert — il ne propage pas une panne à la machine suivante.

**À blanc par défaut** : sans ``--apply``, il ne fait que lire l'état de chaque VPS et le plan que
``run`` y suivrait (``18_vps_maintenance.py run --dry-run``) — rien n'est arrêté, rien n'est mis à
jour, aucun ``git pull``. En ``--apply``, le code du VPS est tiré par l'agent APRÈS l'arrêt du
balayage (jamais sous un run). Lancer le pilote dans tmux : il peut durer des heures, et une
connexion coupée ne doit pas l'interrompre (l'agent, lui, ignore la coupure).

    python3 scripts/19_restart_vps.py                          # à blanc, tous les VPS
    python3 scripts/19_restart_vps.py --only ancienne-vm       # à blanc, un VPS
    python3 scripts/19_restart_vps.py --apply                  # pour de vrai, dans l'ordre
    python3 scripts/19_restart_vps.py --apply --only secours --reboot-secours

Les VPS (``HOSTS``, ou ``--hosts-file`` au même format JSON) :

* ``secours`` — 169.58.5.63, partagé avec le projet price check (compte ``hermes``) :
  **jamais redémarré** par défaut (``reboot: never`` ; ``--reboot-secours`` pour l'autoriser, et
  le script refuse encore si ``hermes`` a des processus, sauf ``--allow-hermes``) ;
* ``ancienne-vm`` — 51.38.37.254 (groupe A) ;
* ``cette-vm`` — la machine qui pilote (groupe B), TOUJOURS en dernier : si elle redémarre, le
  pilote s'arrête là, et la fin (contrôles, relance, message Discord) est faite au démarrage par
  le service ``aks-maint-postboot`` de la machine elle-même.

Codes de sortie : 0 tout est vert · 1 un VPS n'est pas revenu au vert (la suite n'a PAS été
faite) · 2 usage · 42 cette machine redémarre (la fin est faite sur place).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIVE = "/home/debian/executor"
AGENT = f"{LIVE}/scripts/18_vps_maintenance.py"
SSH_KEY = os.path.expanduser("~/.ssh/aks_executor_deploy")
HOSTS: list[dict[str, Any]] = [
    {"name": "secours", "ssh": "debian@169.58.5.63", "reboot": "never"},
    {"name": "ancienne-vm", "ssh": "debian@51.38.37.254", "reboot": "auto"},
    {"name": "cette-vm", "ssh": None, "reboot": "auto"},
]
EXIT_REBOOT = 42
EXIT_ABSENT = 127        # le script de maintenance n'est pas sur le VPS (déployer d'abord)
AGENT_TIMEOUT_S = 18000  # arrêt sûr (≤ 45 min) + apt (3 × ≤ 1 h) + contrôles : 5 h au plus
BOOT_WAIT_S = 900        # le VPS doit être revenu (nouveau boot_id) en 15 min
POSTBOOT_WAIT_S = 1500   # … et avoir fini ses contrôles / sa relance en 25 min

Runner = Callable[..., subprocess.CompletedProcess]


def run_cmd(cmd: list[str], timeout: int = 7200) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, exc.stdout or "", f"timeout {timeout}s")


def remote(host: dict[str, Any], shell: str, key: str = SSH_KEY) -> list[str]:
    """La commande qui exécute ``shell`` sur le VPS, sous ``debian``."""

    if host.get("ssh"):
        return ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                "-o", "ServerAliveInterval=30", host["ssh"], shell]
    if os.geteuid() == 0:
        return ["sudo", "-u", "debian", "-H", "bash", "-lc", shell]
    return ["bash", "-lc", shell]


def last_json(text: str) -> dict[str, Any] | None:
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def ordered(hosts: list[dict[str, Any]], only: list[str], skip: list[str]) -> list[dict[str, Any]]:
    """Les VPS retenus, la machine locale TOUJOURS en dernier."""

    keep = [h for h in hosts if (not only or h["name"] in only) and h["name"] not in skip]
    return [h for h in keep if h.get("ssh")] + [h for h in keep if not h.get("ssh")]


def agent_args(host: dict[str, Any], *, dry_run: bool, reboot_secours: bool,
               allow_hermes: bool) -> str:
    policy = host.get("reboot", "auto")
    if host["name"] == "secours" and reboot_secours:
        policy = "auto"
    parts = ["run", "--reboot", policy]
    if dry_run:
        parts.append("--dry-run")
    if allow_hermes:
        parts.append("--allow-hermes")
    return " ".join(parts)


def wait_for_return(host: dict[str, Any], boot_before: str, *, runner: Runner, key: str,
                    sleep: Callable[[float], None] = time.sleep,
                    boot_wait: int = BOOT_WAIT_S, postboot_wait: int = POSTBOOT_WAIT_S) -> dict[str, Any]:
    """Attend un NOUVEAU boot_id (un ssh qui répond avant la coupure ne compte pas), puis le
    résultat de fin de maintenance écrit après ce démarrage."""

    waited, new_boot = 0, ""
    sleep(20)
    while waited <= boot_wait:
        res = runner(remote(host, "cat /proc/sys/kernel/random/boot_id", key), timeout=30)
        now = (res.stdout or "").strip()
        if res.returncode == 0 and now and now != boot_before:
            new_boot = now
            break
        sleep(15)
        waited += 15
    if not new_boot:
        return {"ok": False, "why": f"pas revenu en {boot_wait} s (boot_id inchangé ou ssh muet)"}
    waited = 0
    while waited <= postboot_wait:
        res = runner(remote(host, f"python3 {AGENT} status", key), timeout=180)
        st = last_json(res.stdout) or {}
        last = st.get("last_result") or {}
        if last.get("boot_id") == new_boot and not st.get("pending"):
            return {"ok": last.get("exit") == 0, "why": "revenu", "result": last}
        sleep(30)
        waited += 30
    return {"ok": False, "why": f"revenu, mais pas de résultat de fin de maintenance en {postboot_wait} s"}


def maintain(host: dict[str, Any], args: argparse.Namespace, *, runner: Runner = run_cmd,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Un VPS. Le pilote ne fait AUCUN ``git pull`` lui-même (revue adverse du 30/09 : tirer le
    code sous un run qu'on va ensuite déclarer « reporté », c'est changer le code d'un run en
    cours) : en ``--apply``, c'est l'agent qui tire, APRÈS avoir arrêté le balayage."""

    out: dict[str, Any] = {"host": host["name"]}
    shell = (f"test -f {AGENT} || exit {EXIT_ABSENT}; python3 {AGENT} "
             + agent_args(host, dry_run=not args.apply, reboot_secours=args.reboot_secours,
                          allow_hermes=args.allow_hermes)
             + (" --pull" if args.apply else ""))
    res = runner(remote(host, shell, args.ssh_key), timeout=AGENT_TIMEOUT_S)
    payload = last_json(res.stdout)
    out["exit"] = res.returncode
    out["payload"] = payload
    if res.returncode == EXIT_ABSENT:
        out.update(ok=False, blocked=True,
                   why="script de maintenance absent — déployer d'abord (git pull entre deux balayages)")
        return out
    if not args.apply:
        plan = (payload or {}).get("plan") or {}
        if payload is None:
            out.update(ok=False, blocked=False, why=f"à blanc illisible (code {res.returncode})")
            return out
        out.update(ok=not plan.get("blocked"), blocked=bool(plan.get("blocked")),
                   why=plan.get("blocked") or "plan prêt")
        return out
    if res.returncode == EXIT_REBOOT:
        if not host.get("ssh"):
            out.update(ok=True, rebooting_self=True,
                       why="cette machine redémarre — la fin est faite sur place au démarrage")
            return out
        boot_before = ((payload or {}).get("context") or {}).get("boot_id_before", "")
        back = wait_for_return(host, boot_before, runner=runner, key=args.ssh_key, sleep=sleep)
        out.update(back)
        return out
    if res.returncode == 3 and payload is not None:
        out.update(ok=False, blocked=True,
                   why=((payload or {}).get("plan") or {}).get("blocked") or (payload or {}).get("error")
                   or "maintenance reportée")
        return out
    # 0 = vert ; tout le reste (4, 5, 6, 7, une panne sans JSON, ssh coupé…) arrête la chaîne.
    why = (payload or {}).get("error") or f"code {res.returncode}"
    out.update(ok=res.returncode == 0 and payload is not None, blocked=False, why=why)
    return out


def notify(text: str) -> None:
    try:
        from src.notify import notify as _notify
        root = Path(LIVE) if Path(LIVE, ".env").exists() else ROOT
        _notify("maintenance", text, root=root)
    except Exception:                         # noqa: BLE001
        pass


def main(argv: list[str] | None = None, *, runner: Runner = run_cmd,
         sleep: Callable[[float], None] = time.sleep) -> int:
    ap = argparse.ArgumentParser(description="Maintenance des VPS, un par un (voir le module).")
    ap.add_argument("--apply", action="store_true", help="exécuter (sinon : à blanc)")
    ap.add_argument("--only", action="append", default=[], help="nom d'un VPS (répétable)")
    ap.add_argument("--skip", action="append", default=[], help="nom d'un VPS à sauter")
    ap.add_argument("--reboot-secours", action="store_true",
                    help="autoriser le redémarrage du VPS de secours (price check dessus)")
    ap.add_argument("--allow-hermes", action="store_true",
                    help="redémarrer même si le compte hermes a des processus")
    ap.add_argument("--hosts-file", help="liste des VPS (JSON, même format que HOSTS)")
    ap.add_argument("--ssh-key", default=SSH_KEY)
    args = ap.parse_args(argv)
    hosts = HOSTS
    if args.hosts_file:
        hosts = json.loads(Path(args.hosts_file).read_text(encoding="utf-8"))
    names = {h["name"] for h in hosts}
    unknown = [n for n in args.only + args.skip if n not in names]
    if unknown:
        print(json.dumps({"error": f"VPS inconnu(s) : {unknown}", "connus": sorted(names)}))
        return 2
    report: list[dict[str, Any]] = []
    code = 0
    for host in ordered(hosts, args.only, args.skip):
        res = maintain(host, args, runner=runner, sleep=sleep)
        report.append(res)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        if res.get("rebooting_self"):
            code = EXIT_REBOOT
            break
        if not res.get("ok") and not res.get("blocked"):
            code = 1
            break                             # jamais propager une panne au VPS suivant
    summary = {"apply": args.apply, "hosts": [
        {"host": r["host"], "ok": r.get("ok"), "why": r.get("why")} for r in report]}
    print(json.dumps(summary, ensure_ascii=False))
    if args.apply:
        notify("🔧 Maintenance des VPS : " + " · ".join(
            f"{r['host']} {'OK' if r.get('ok') else 'KO'} ({r.get('why')})" for r in report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
