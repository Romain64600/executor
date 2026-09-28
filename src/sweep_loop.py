"""La BOUCLE d'un balayage — relancer un groupe à sa fin, jusqu'à « Arrêter » (2026-09-27).

Romain : « Comment je peux faire pour que, quand je lance un groupe A ou un groupe B, lorsqu'ils
se finissent, ils se relancent ? […] qu'on puisse quand même aller l'arrêter, mais qu'il boucle,
qu'on ne soit pas obligé d'attendre la fin pour le relancer à la main depuis l'admin. » Puis, sur
la proposition : « 5 min de pause, sans limite, go pour la boucle ».

**Le principe.** `scripts/10_data_entry_auto.py --loop` enchaîne des PASSES dans le MÊME
processus, enfant de l'admin comme aujourd'hui (jamais fire-and-forget) : à la fin du dernier
marchand, une pause, puis une nouvelle passe sur la MÊME liste de cibles (le groupe détendu au
lancement), de la dernière page du feed vers la page 1. « Arrêter » agit à tout moment, pause
comprise, et ne relance jamais.

**Une passe = un recap.** La passe 1 vit dans le dossier du lancement (`runs/<run-id>/`,
inchangé) ; la passe N ≥ 2 dans `runs/<run-id>-passN/`, avec ses propres pages
(`<run-id>-passN-<slug>-s<store>-p<page>`). Le dossier du lancement porte en plus `loop.json`,
l'état de la boucle (ci-dessous), que la console et la route recap lisent pour suivre la passe
COURANTE — le marqueur `state/active_run.json`, lui, garde l'id du lancement d'un bout à l'autre.

**Elle s'arrête d'elle-même** (motif consigné et affiché), par sécurité — boucler ne doit jamais
transformer un arrêt fail-closed en martèlement d'AKS :

1. ``session_expired`` — une déconnexion vue dans la passe (un marchand arrêté avec un détail
   « not logged in », ou un plan de saisie ``not_logged_in``) : il faut le transfert de cookies
   de Romain, la boucle ne se reconnecte JAMAIS ;
2. ``guard_blocked`` — le garde StepGuard a bloqué ;
3. ``all_merchants_halted`` — TOUS les marchands de la passe se sont arrêtés : quelque chose
   casse systématiquement.

Un marchand arrêté seul est simplement repris à la passe suivante. Une passe qui a créé MOINS DE
10 offres n'arrête pas la boucle : elle allonge la pause (30 min au lieu de 5 — Romain,
2026-09-28 : « go pour 30 min si moins de 10 offres » ; avant, seulement une passe à 0).

**`loop.json`** (`runs/<run-id>/loop.json`, écriture atomique) :

```json
{"run_id": "<lancement>", "loop": true, "pause_s": 300, "empty_pause_s": 1800,
 "state": "running" | "pause" | "stopped", "pass": 3, "current_run_id": "<lancement>-pass3",
 "started_at": "…Z", "updated_at": "…Z", "next_pass_at": "…Z" | null,
 "targets": [{"merchant": …, "store_id": …}],
 "passes": [{"pass": 1, "run_id": "<lancement>", "started_at": "…Z", "finished_at": "…Z",
             "total_created": 1343, "halted": null | "…", "halted_merchants": 2}],
 "totals": {"created": 1553, "passes_finished": 2},
 "stopped_reason": null | "operator_stop" | "session_expired" | "guard_blocked" | "all_merchants_halted",
 "stopped_label": null | "…", "stopped_at": null | "…Z"}
```
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LOOP_FILE = "loop.json"
DEFAULT_PAUSE_S = 300          # Romain, 2026-09-27 : « 5 min de pause »
EMPTY_PASS_PAUSE_S = 1800      # une passe qui rapporte peu : le feed se remplit moins vite qu'on ne le vide
# Romain, 2026-09-28 : « go pour 30 min si moins de 10 offres ». Mesure qui l'a motivé : la boucle
# du groupe A, nuit du 27 au 28/09 — passe 1 : 383 créées, passe 2 : 6, passe 3 : 0. Avant, seule
# une passe à 0 allongeait la pause (la passe 2 repartait après 5 min pour 6 offres).
LOW_YIELD_CREATED = 10
MIN_PAUSE_S = 60

STOP_LABELS: dict[str, str] = {
    "operator_stop": "arrêt opérateur",
    "session_expired": "session expirée — transfert de cookies requis",
    "guard_blocked": "garde StepGuard bloqué",
    "all_merchants_halted": "tous les marchands de la passe se sont arrêtés",
}


def pass_run_id(launch_run_id: str, n: int) -> str:
    """L'id de run de la passe ``n`` : la passe 1 EST le lancement (recap inchangé), les
    suivantes ont leur propre dossier ``<lancement>-passN``."""

    return launch_run_id if n <= 1 else f"{launch_run_id}-pass{int(n)}"


def new_status(run_id: str, targets: list[tuple[str, str]], *, pause_s: int,
               empty_pause_s: int, clock, dry_run: bool = False) -> dict[str, Any]:
    now = clock()
    return {
        "run_id": run_id, "loop": True, "dry_run": bool(dry_run),
        "pause_s": int(pause_s), "empty_pause_s": int(empty_pause_s),
        "state": "running", "pass": 0, "current_run_id": None,
        "started_at": now, "updated_at": now, "next_pass_at": None,
        "targets": [{"merchant": m, "store_id": str(s)} for m, s in targets],
        "passes": [], "totals": {"created": 0, "passes_finished": 0},
        "stopped_reason": None, "stopped_label": None, "stopped_at": None,
    }


def write_status(launch_dir: Path, status: dict[str, Any], clock) -> None:
    """Écriture ATOMIQUE (tmp + os.replace), comme `recap.json` : la console le relit en
    direct pendant qu'on l'écrit."""

    status["updated_at"] = clock()
    path = Path(launch_dir) / LOOP_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_status(run_dir: Path) -> dict[str, Any] | None:
    """L'état de la boucle d'un dossier de lancement, ou None (pas de boucle, fichier absent
    ou illisible — jamais une exception : la console et la route recap le lisent)."""

    try:
        raw = json.loads((Path(run_dir) / LOOP_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and raw.get("loop") is True else None


def current_pass_run_id(run_dir: Path) -> str | None:
    """L'id de run de la passe COURANTE (ou dernière) d'un lancement en boucle, quand elle
    n'est pas le lancement lui-même ; None sinon."""

    status = read_status(run_dir)
    if not status:
        return None
    current = str(status.get("current_run_id") or "")
    if not current or current == Path(run_dir).name:
        return None
    return current


# ── ce qu'une passe dit d'elle-même ─────────────────────────────────────────────────────
def is_login_bounce(text: Any) -> bool:
    """Le texte d'une halte, d'une erreur de page ou d'un plan dit-il une DÉCONNEXION ?
    « not logged in », ``NotLoggedInError``, ``not_logged_in`` (le plan de saisie), un rebond
    vers wp-login."""

    low = str(text or "").lower()
    flat = low.replace("_", " ").replace("-", " ")
    return ("not logged in" in flat or "notloggedin" in low or "wp login" in flat)


def _pages(target_recap: dict[str, Any] | None) -> list[dict[str, Any]]:
    pages = (target_recap or {}).get("pages") or []
    return [p for p in pages if isinstance(p, dict)]


def pass_saw_login_bounce(recap: dict[str, Any]) -> bool:
    """Une déconnexion quelque part dans la passe : le détail d'une halte de marchand, l'erreur
    d'une page, ou un plan de saisie arrêté / abandonné ``not_logged_in``. Le texte d'une
    offre UNKNOWN (rebond APRÈS un clic) ne compte pas seul : un rebond passager mi-preuve a
    déjà été vu (Kinguin p2, 26/09 01:05 UTC) alors que la session vivait — une session
    vraiment perdue arrête le marchand suivant à sa première lecture, et c'est là qu'on la voit."""

    for t in recap.get("targets") or []:
        tr = (t or {}).get("recap") or {}
        if is_login_bounce(tr.get("halted_detail")):
            return True
        for p in _pages(tr):
            if is_login_bounce(p.get("error")) or is_login_bounce(p.get("stopped")) \
                    or is_login_bounce(p.get("aborted")):
                return True
    return False


def pass_saw_guard_block(recap: dict[str, Any]) -> bool:
    """Le garde StepGuard a bloqué une page de la passe (``guard_blocked`` dans le plan ou
    l'erreur d'une page)."""

    for t in recap.get("targets") or []:
        for p in _pages((t or {}).get("recap")):
            if any("guard_blocked" in str(p.get(k) or "") for k in ("stopped", "aborted", "error")):
                return True
    return False


def all_merchants_halted(recap: dict[str, Any]) -> bool:
    """TOUS les marchands démarrés de la passe se sont arrêtés (au moins un marchand)."""

    targets = [t for t in (recap.get("targets") or []) if isinstance(t, dict)]
    if not targets:
        return False
    return all(bool(((t.get("recap") or {}).get("halted"))) for t in targets)


def stop_reason(recap: dict[str, Any], *, operator_stopped: bool) -> str | None:
    """Le motif d'arrêt de la boucle après cette passe, ou None (on continue). L'arrêt
    opérateur d'abord, puis les trois arrêts de sécurité, dans l'ordre du module."""

    halted = str(recap.get("halted") or "")
    if operator_stopped or "operator_stop" in halted:
        return "operator_stop"
    if pass_saw_login_bounce(recap):
        return "session_expired"
    if pass_saw_guard_block(recap):
        return "guard_blocked"
    if all_merchants_halted(recap):
        return "all_merchants_halted"
    return None


def pause_after_pass(recap: dict[str, Any], *, pause_s: int, empty_pause_s: int) -> int:
    """5 min (Romain) ; 30 min quand la passe a créé moins de ``LOW_YIELD_CREATED`` (10) offres —
    le feed se remplit moins vite que la boucle ne le vide (Romain, 2026-09-28)."""

    created = int(recap.get("total_created") or 0)
    return int(empty_pause_s) if created < LOW_YIELD_CREATED else int(pause_s)


def cooperative_pause(seconds: float, *, should_stop, sleep, slice_s: float = 5.0,
                      on_tick=None) -> bool:
    """Attend ``seconds`` par tranches de ``slice_s`` au plus, en surveillant l'arrêt
    opérateur — « Arrêter » reste immédiat pendant la pause. False = arrêt demandé.
    ``on_tick(restant)`` est appelé après chaque tranche (battement de cœur du statut)."""

    restant = float(seconds)
    while restant > 0:
        if should_stop():
            return False
        tranche = min(float(slice_s), restant)
        sleep(tranche)
        restant -= tranche
        if on_tick is not None:
            on_tick(restant)
    return not should_stop()
