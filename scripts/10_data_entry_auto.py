#!/usr/bin/env python3
"""Safe-auto data-entry sweep — CLI (Romain's "mode rapide safe auto", 2026-08-04).

For each target ``merchant:store_id``, sweep the feed page by page:
extract (02) → match (03) → auto-approve EVERY matcher candidate → submit (05,
``--mode safe`` real write, post-save proven by the feed SEARCH filtered by the offer
URL since Romain's GO of 2026-09-10 — ``--prove-gone-scan`` restores the whole-feed
re-walk). NO human validation; the matcher is the safety gate.
A per-page recap is written to ``runs/<run-id>/recap.json`` incrementally; Romain
audits it and deletes any mistake afterwards.

Supervised, NEVER fire-and-forget: this runs as ONE manager-tracked process. A
SIGTERM (the console "Arrêter" button) stops cooperatively — the current child
stage is signalled and the sweep halts between pages. Fail-closed: any stage that
does not finish clean HALTS the whole sweep (no plowing through a broken session);
a NotLoggedIn/feed-unreadable abort stops it, never a re-auth.

  python3 scripts/10_data_entry_auto.py --targets "Kinguin:58" --run-id <id>
  python3 scripts/10_data_entry_auto.py --targets "Kinguin:58,Eneba:19" --max-pages 50
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import run_marker
from src.data_entry_auto import (  # noqa: E402
    ExtractOutcome, MatchOutcome, MoveOutcome, Stages, StageError, SubmitOutcome,
    SweepConfig, run_sweep,
)
from src.admin.validation_io import apply_overrides_and_validate  # noqa: E402
from src.admin.runs import sha256_file  # noqa: E402
from src.admin.auto_merchants import rejection_reason  # noqa: E402
from src.child_runner import CooperativeChildRunner  # noqa: E402
from src.triage import execute_page_moves, plan_moves_from_skipped  # noqa: E402
from src.validation import candidate_fingerprint  # noqa: E402

# Cooperative stop: forward SIGTERM to the current child (05_submit/02/03/06 each
# stop at their OWN safe boundary — 05 at an offer boundary, never mid-Create — then
# exit; run_sweep then halts between pages). ``start_new_session`` isolates a child
# from an orchestrator SIGKILL cascade; a child that HANGS past the grace is SIGKILLed
# by its group so it is never orphaned (see src/child_runner.py, review 2026-08-25).
_RUNNER = CooperativeChildRunner()


TARGETS_QUEUE = "targets_queue.json"


def read_targets_queue(sweep_dir: "Path | None") -> list[tuple[str, str]]:
    """Les marchands AJOUTÉS au sweep pendant qu'il tourne, dans l'ordre d'ajout.

    Le canal est un fichier du dossier de run, et il a UN SEUL écrivain : la console
    (``SubmitManager.add_sweep_target``, sous son mutex, en écriture atomique). Le sweep, lui,
    ne fait que LIRE — jamais de lecture-modification-écriture des deux côtés, donc pas de
    course à gérer. Il le relit à chaque FRONTIÈRE de marchand, jamais au milieu d'une page :
    une cible ajoutée n'interrompt rien, elle prend la file.

    Un fichier illisible ne casse pas un run de 30 h : on rend une liste vide et l'appelant
    le signale dans le recap. C'est le bon arbitrage ici — le pire cas est « le marchand que
    Romain vient d'ajouter n'est pas pris », visible immédiatement dans la console, pas une
    écriture fausse sur AKS."""

    if sweep_dir is None:
        return []
    try:
        raw = json.loads((sweep_dir / TARGETS_QUEUE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        merchant = str(entry.get("merchant") or "").strip()
        store_id = str(entry.get("store_id") or "").strip()
        if merchant and store_id:
            out.append((merchant, store_id))
    return out


def take_from_queue(sweep_dir: "Path | None", planned: set, refused_keys: set,
                    recap: dict, clock, taken_keys: "set | None" = None) -> list[tuple[str, str]]:
    """Ce que la file apporte de NOUVEAU et de VETTÉ ; le reste est ignoré ou inscrit refusé.

    Revue de Romain (2026-09-19, P1) : la route HTTP filtrait la liste blanche, mais pas le
    lecteur — `Difmark:167`, interdit au lancement, écrit directement dans le fichier,
    rejoignait l'exécution. Même argument que la garde de `--targets` dans `main` : le point
    qui DÉCLENCHE les écritures vérifie lui-même, quel que soit le chemin d'arrivée. Un ajout
    refusé n'arrête pas un run de 30 h : il est inscrit dans le recap (`targets_refused`) et
    ignoré.

    `planned` = le plan complet (initial + pris), `taken_keys` = ce que CE run a pris dans la
    file. Revue `/code-review` (2026-09-19) : sans cette distinction, chaque ajout accepté
    était re-tracé « déjà cible » à toutes les relectures suivantes — la file n'est jamais
    vidée, et la clé était désormais dans `planned`. Une entrée prise se relit en silence ;
    seul un doublon du PLAN INITIAL, écrit à la main, laisse une trace `targets_ignored`.
    Tous les ensembles sont mutés en place (clés en minuscules)."""

    taken: list[tuple[str, str]] = []
    if taken_keys is None:
        taken_keys = set()
    ignored = recap.setdefault("targets_ignored", [])
    for added in read_targets_queue(sweep_dir):
        key = (added[0].casefold(), str(added[1]))
        if key in refused_keys or key in taken_keys:
            continue
        if key in planned:
            if not any((i.get("merchant", "").casefold(), str(i.get("store_id"))) == key for i in ignored):
                ignored.append({"merchant": added[0], "store_id": added[1],
                                "reason": "déjà cible du sweep", "at": clock()})
            continue
        why = rejection_reason(added[0], added[1])
        if why is not None:
            refused_keys.add(key)
            recap.setdefault("targets_refused", []).append(
                {"merchant": added[0], "store_id": added[1], "reason": why, "at": clock()})
            continue
        planned.add(key); taken_keys.add(key)
        recap.setdefault("targets_added", []).append(
            {"merchant": added[0], "store_id": added[1], "at": clock()})
        taken.append(added)
    return taken


# L'état « file fermée » vit dans le RECAP (`queue_closed`), écrit atomiquement par
# `persist()`, et non dans un fichier à part. Revue `/code-review` (2026-09-19) : le fichier
# `targets_queue.closed` de la version précédente avait dû être complété par deux cas
# spéciaux (fermeture après la boucle, effacement au démarrage), et chacun a ouvert un défaut
# (ajout accepté puis détruit au démarrage, marqueur collé pendant qu'une retardataire
# balayait des heures). Le recap est déjà relu par la console à chaque ajout, il est rebâti
# à chaque lancement, et il porte `finished_at` sur toute sortie : un seul état, un seul
# écrivain, aucun héritage entre deux lancements.


def _run_child(argv: list[str]) -> int:
    return _RUNNER.run(argv, str(ROOT))


def _last_abort_reason(run_id: str) -> str:
    """The reason of the LAST ``aborted`` event in ``logs/<run_id>.jsonl`` ("" if none).
    The child stages' stdout is not captured, so this is how the sweep learns WHY an
    extract failed — twice on 2026-09-11 a sweep halted `extract_failed_p1` and the only
    trace of "not logged in (wp-login)" sat in the page log (Romain had to be told by
    hand that a cookie transfer was needed)."""

    path = ROOT / "logs" / f"{run_id}.jsonl"
    reason = ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "aborted" and event.get("reason"):
                reason = str(event["reason"])
    except OSError:
        pass
    return reason[:160]


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_stages(merchant: str, store_id: str, available: str, pace: str | None,
                 *, triage: bool = False, move_execute: bool = False,
                 dry_run: bool = False, prove_gone_scan: bool = False,
                 sweep_dir: Path | None = None, consoles: bool = True) -> Stages:
    py = sys.executable
    # A fully read-only preview (Romain: "teste le dry-run"): extract (browser read)
    # + match (AKS read) + triage plan, but NEVER a real write — the ADD submit is
    # counted from candidates.json without invoking 05, and moves stay planned. Used
    # to preview a merchant's ADD/MOVE/SKIP breakdown before any real sweep.
    if dry_run:
        move_execute = False

    def extract(page: int, run_id: str) -> ExtractOutcome:
        argv = [py, str(ROOT / "scripts" / "02_extract_feed.py"),
                "--merchant", merchant, "--store-id", store_id,
                "--run-id", run_id, "--pages", str(page), "--available", available]
        if pace:
            argv += ["--pace", pace]
        rc = _run_child(argv)
        offers = _load_json(ROOT / "runs" / run_id / "offers.json") or {}
        n = offers.get("offer_count") if isinstance(offers, dict) else None
        if n is None and isinstance(offers, dict):
            n = offers.get("count") or len(offers.get("offers", []))
        flp = offers.get("feed_last_page") if isinstance(offers, dict) else None
        detail = "" if rc == 0 else f"exit {rc}"
        if rc != 0:
            why = _last_abort_reason(run_id)
            if why:
                detail = f"exit {rc} ({why})"       # e.g. "exit 2 (not logged in (wp-login))"
        return ExtractOutcome(ok=(rc == 0), offers=int(n or 0),
                              feed_last_page=int(flp) if flp else None, detail=detail)

    def match(run_id: str) -> MatchOutcome:
        argv = [py, str(ROOT / "scripts" / "03_match.py"),
                str(ROOT / "runs" / run_id / "offers.json")]
        if sweep_dir is not None:
            # Romain GO 2026-09-10: the R30 breaker state travels across the sweep's pages
            # (no 3 × timeout tax per page while AKS search is down; expires on its own).
            argv += ["--search-circuit-file", str(sweep_dir / "search_circuit.json")]
        # [R45] console branch of the matcher — the DEFAULT since Romain's decision « 1 » of
        # 2026-09-15 (after the two modal-v2 canaries and the MMOGA console dry-run: 174
        # candidates). Explicit either way so a run dir's argv shows the mode; --no-consoles
        # = PC-only match (console rows keep the 'console' skip).
        argv.append("--consoles" if consoles else "--no-consoles")
        rc = _run_child(argv)
        cands = _load_json(ROOT / "runs" / run_id / "candidates.json")
        n = len(cands) if isinstance(cands, list) else 0
        # Review 2026-09-09: surface WHY 03 aborted (its stdout is not captured) and how
        # many offers were skipped on an unreliable AKS probe below the abort threshold —
        # a throttled page must not read like an empty one in the recap.
        detail = "" if rc == 0 else f"exit {rc}"
        if rc != 0:
            aborted = _load_json(ROOT / "runs" / run_id / "match_aborted.json")
            if isinstance(aborted, dict) and aborted.get("reason"):
                detail = f"exit {rc} ({aborted['reason']}: {str(aborted.get('detail') or '')[:120]})"
        meta = _load_json(ROOT / "runs" / run_id / "match_meta.json")
        unreliable = int((meta or {}).get("probe_unreliable") or 0) if isinstance(meta, dict) else 0
        movable = 0
        if triage:
            # Count this page's routable skips (→ Move-to-List). Pure read of the
            # match's skipped.json — the reasons already reflect the FULL match
            # decision (incl. Instant Gaming page-resolved regions).
            skipped = _load_json(ROOT / "runs" / run_id / "skipped.json") or []
            movable = int(plan_moves_from_skipped(skipped).get("movable", 0))
        return MatchOutcome(ok=(rc == 0), candidates=n, movable=movable,
                            probe_unreliable=unreliable, detail=detail)

    def approve(run_id: str) -> int:
        run_dir = ROOT / "runs" / run_id
        cpath = run_dir / "candidates.json"
        # P3-5 (audit 2026-09-02): wrap the WHOLE approve body — the payload build too
        # (a malformed/stale candidates.json crashes candidate_fingerprint with a
        # KeyError, the SAME class as a validator error). ANY failure must become a
        # StageError so run_sweep records it (approve_failed_p<N>), halts fail-closed,
        # and main() still reaches the finished_at/persist() stamp — before, only a
        # ValidationIOError was caught, so an OSError/KeyError crashed the supervised
        # sweep with a half-written recap. Approve failing means the page is NEVER
        # submitted (over-skip, never a wrong entry); mirrors the by-urls orchestrator.
        try:
            cands = _load_json(cpath) or []
            payload = {
                "validated_by": "auto (safe-auto data entry)",
                "candidates_sha256": sha256_file(cpath),
                "decisions": [{"fingerprint": candidate_fingerprint(c), "approve": True} for c in cands],
            }
            res = apply_overrides_and_validate(run_dir, payload, repo_root=ROOT, created_offer_ids=None)
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__
            raise StageError(f"{code}: {exc}")
        return int(res.get("approved_count") or 0)

    def submit(run_id: str) -> SubmitOutcome:
        run_dir = ROOT / "runs" / run_id
        if dry_run:
            # READ-ONLY preview: count the candidates that WOULD be created; never
            # call 05 (no browser write path, no offer created).
            cands = _load_json(run_dir / "candidates.json") or []
            offers = [{"name": (c.get("offer") or {}).get("name"),
                       "aks_id": c.get("aks_product_id"), "created": False}
                      for c in cands] if isinstance(cands, list) else []
            return SubmitOutcome(ok=True, created=0, offers=offers,
                                 detail=f"dry-run (would create {len(offers)})")
        # The offers were all extracted from ONE feed page (the run id ends
        # -p<N>); pass it as --page-hint so the submit locates + verifies them in
        # a small window around that page instead of a sequential scan that can't
        # reach deep pages (submit-index-shallow-feed).
        argv = [py, str(ROOT / "scripts" / "05_submit.py"),
                str(run_dir / "approved.json"), "--merchant", merchant,
                "--store-id", store_id, "--mode", "safe", "--submit", "--available", available]
        try:
            argv += ["--page-hint", run_id.rsplit("-p", 1)[1]]
        except IndexError:
            pass
        if not prove_gone_scan:
            # Romain GO 2026-09-10: prove each post-save disappearance with the feed
            # SEARCH (whole-feed filtered query) instead of a whole-feed re-walk per
            # creation — ~100 s → ~2 s per offer on a 66-page feed. --prove-gone-scan
            # restores the walk.
            argv.append("--prove-gone-by-search")
        if sweep_dir is not None:
            # Romain GO 2026-09-10: one live catalog fetch per sweep, not per page.
            argv += ["--catalog-cache", str(sweep_dir / "catalog.json")]
        if pace:
            # [33] Fable re-audit 2026-09-06: 05_submit has NO --pace flag — only
            # --pace-pages / --pace-offers, so a bare "--pace" is an AMBIGUOUS prefix and
            # argparse errored, halting every paced sweep at its first submit. Map the
            # sweep's single pace spec onto both real flags (same Pacer spec format).
            argv += ["--pace-pages", pace, "--pace-offers", pace]
        rc = _run_child(argv)
        # P2-14 (audit 2026-09-02): on exit 0 an UNREADABLE submit_plan.json (None from
        # _load_json — external corruption / interrupted write) leaves the post-write
        # state UNKNOWN. Do NOT collapse it to {} and record a benign 0-created page:
        # fold unreadability into `ok` so `.clean()` HALTS the sweep (uncertainty →
        # STOP). A genuine empty page (valid JSON, plan=[]) stays benign (not None).
        plan = _load_json(run_dir / "submit_plan.json")
        plan_readable = plan is not None
        plan = plan or {}
        offers = []
        created = 0
        for e in plan.get("plan", []):
            ps = str(e.get("post_save") or "")
            created_ok = "gone" in ps.lower()
            if created_ok:
                created += 1
            offers.append({"name": e.get("merchant_title"), "aks_id": e.get("aks_product_id"),
                           "region_id": e.get("region_id"), "edition_id": e.get("edition_id"),
                           "created": created_ok, "post_save": ps})
        ok = (rc == 0 and plan_readable)
        detail = "" if ok else (f"exit {rc}" if rc else "submit_plan.json unreadable after exit 0")
        if rc:
            # 2026-09-19 : 05 journalise chaque abandon fail-closed (sa sortie standard est
            # jetée) — le recap dit POURQUOI la page s'est arrêtée, pas seulement « exit 2 ».
            why = _last_abort_reason(run_id)
            if why:
                detail = f"exit {rc} ({why})"
        return SubmitOutcome(ok=ok, aborted=plan.get("aborted"),
                             stopped=plan.get("stopped"),
                             created=created, offers=offers, detail=detail)

    def move(run_id: str) -> MoveOutcome:
        # Move-to-List step of the unified per-page workflow. The plan comes from
        # this page's skipped.json (FULL match reasons) — pure, no browser.
        run_dir = ROOT / "runs" / run_id
        skipped = _load_json(run_dir / "skipped.json") or []
        plan = plan_moves_from_skipped(skipped)
        (run_dir / "triage_moves.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        planned = [row for rows in plan["by_list"].values() for row in rows]

        if not move_execute:
            # DRY-RUN default (Romain 2026-08-13): plan only, NOTHING moved. The
            # ADDs were submitted for real; the moves are previewed for the operator
            # to execute via the canary→batch path once each target list is
            # authorized. No browser, no 06_move, always clean.
            return MoveOutcome(ok=True, moved=0, offers=planned,
                               detail=f"dry-run (plan only): {plan['movable']} à déplacer "
                                      f"vers {plan['target_lists']} liste(s)")

        if not plan["by_list"]:
            return MoveOutcome(ok=True, moved=0, detail="rien à déplacer")

        # --move-execute: real moves via the Stage-6 writer (06_move). The batch
        # authorization is bound to THIS page's extraction (a hash of skipped.json,
        # src.move_auth), so it can't be pre-granted — each target list must
        # self-authorize on this page: a CANARY (RV2-proven → grants the authorization)
        # then a BATCH (safe, covered). BATCHED VERIFY (Romain 2026-08-17): a list of
        # >=2 offers uses --batch (one Apply + one group feed-scan instead of a scan
        # per move — ~G× fewer scans, fixing the deep-feed slowness + CDP load), which
        # needs a MULTI-ITEM canary (--batch --limit 2, a >=2-item Apply proving the
        # batched mechanism); a lone-offer list stays unitary. Fail-closed: any unclean
        # phase halts the sweep (never a silent un-vetted bulk move).
        def _06move(mode: str, rows: list[dict[str, Any]], extra: list[str]) -> dict[str, Any]:
            annotations = {
                r["offer_id"]: {
                    "target_list_id": r["list_id"],
                    "target_list_label": r["list_label"],
                    "merchant_url": r["url"],   # stable identity if the id rotated
                }
                for r in rows
            }
            (run_dir / "learning.json").write_text(
                json.dumps({"run_id": run_id, "annotations": annotations},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            # Remove any prior move_plan.json first: 06_move writes it only at the
            # END, so an EARLY abort (exit 2 before the mover) would otherwise leave
            # the PREVIOUS phase's file — the batch would read the canary's moved
            # count and double-count it (adversarial review, 2026-08-17).
            try:
                (run_dir / "move_plan.json").unlink()
            except FileNotFoundError:
                pass
            argv = [py, str(ROOT / "scripts" / "06_move.py"), str(run_dir),
                    "--store-id", store_id, "--available", available,
                    "--execute", "--mode", mode] + extra
            # The offers were extracted from ONE feed page (run id ends -p<N>) —
            # pass it so the mover indexes a small window instead of the full deep
            # feed (~25 min/run on Kinguin). Same page-hint the submit stage uses.
            try:
                argv += ["--page-hint", run_id.rsplit("-p", 1)[1]]
            except IndexError:
                pass
            rc = _run_child(argv)
            res = _load_json(run_dir / "move_plan.json") or {}
            moved = int(res.get("moved") or 0)
            plan = res.get("plan") or []
            # all_gone: the canary moved 0 because EVERY offer it walked was already
            # relocated (skipped as "not on source list", proven by a full scan) with
            # NO real block/failure → nothing to move for this list, not a failure.
            # [31] Fable re-audit 2026-09-06: only a WHOLE-FEED absence proves "gone". A
            # WINDOWED skip (page-hint) means "not in the window" — the offer may still be
            # on the source outside it, so it must NOT count as all_gone (that silently
            # skipped a list's moves). A windowed miss surfaces window_missed so the
            # operator re-runs that list without a page-hint.
            skipped = [e for e in plan if e.get("skipped")]
            clean = (moved == 0 and bool(plan) and len(skipped) == len(plan)
                     and not any(e.get("blocker") for e in plan))
            window_missed = clean and any(e.get("skip_scope") == "window" for e in skipped)
            all_gone = clean and not window_missed
            return {"ok": (rc == 0 and not res.get("aborted")),
                    "moved": moved, "all_gone": all_gone, "window_missed": window_missed,
                    "aborted": res.get("aborted") or (None if rc == 0 else f"exit {rc}"),
                    "stopped": res.get("stopped")}

        def _canary(lid: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
            # >=2 offers → multi-item batched canary (proves the batched Apply);
            # a lone offer can't fire a >=2-item Apply → unitary canary.
            extra = ["--batch", "--limit", "2"] if len(rows) >= 2 else []
            return _06move("learning", rows, extra)

        def _batch(lid: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
            extra = (["--batch", "--deferred", "--i-authorize-batch"] if len(rows) >= 2
                     else ["--i-authorize-batch"])
            return _06move("safe", rows, extra)

        result = execute_page_moves(plan["by_list"], run_canary=_canary, run_batch=_batch)
        return MoveOutcome(ok=result["ok"], aborted=result.get("aborted"),
                           stopped=result.get("stopped"), moved=result["moved"],
                           offers=result.get("phases", []), detail=result["detail"])

    def offer_ids(run_id: str) -> tuple[str, ...]:
        """Les offer_id de la page extraite — la matière de la mesure de couverture."""
        data = _load_json(ROOT / "runs" / run_id / "offers.json")
        rows = data if isinstance(data, list) else (data or {}).get("offers") or []
        return tuple(str(r.get("offer_id")) for r in rows if isinstance(r, dict) and r.get("offer_id"))

    return Stages(offer_ids=offer_ids, extract=extract, match=match, approve=approve, submit=submit,
                  move=(move if triage else None))


def main() -> int:
    ap = argparse.ArgumentParser(description="Safe-auto data-entry sweep (real writes).")
    ap.add_argument("--targets", help="Comma list 'Merchant:store_id[,Merchant:store_id...]'.")
    ap.add_argument(
        "--all-allowlisted", action="store_true",
        help="Sweep EVERY merchant of the safe-auto allowlist (src/admin/auto_merchants.py "
             "AUTO_MERCHANTS), in its order. This is the NIGHT SWEEP entrypoint (Romain "
             "2026-09-16: « donne moi la commande a jour pour lancer tout les marchands "
             "whitelist … et maintien la dans le readme a chaque whitelist de nouveaux "
             "marchands »): the target list is READ from the allowlist, so it can never "
             "drift from it and no command has to be rewritten when a merchant is added. "
             "Mutually exclusive with --targets / --merchant.")
    ap.add_argument("--continue-on-halt", action="store_true",
                    help="Multi-merchant batch: a fail-closed halt on one merchant (UNKNOWN offer, "
                         "feed unreadable, 10 failures…) is recorded and the NEXT merchant is still "
                         "swept (its feed is independent). Default: the first halt stops the batch. "
                         "A login bounce (not logged in) always stops it: every merchant would fail.")
    ap.add_argument("--merchant", help="Single-target merchant (with --store-id).")
    ap.add_argument("--store-id", help="Single-target store id.")
    ap.add_argument("--run-id", default=None, help="Sweep run id (holds recap.json).")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument(
        "--all-pages", action="store_true",
        help="Couvre TOUTES les pages que le feed annonce, sans plafond (Romain 2026-09-18 : "
             "« on fait toutes les pages sauf lors d'un arrêt pour sécurité »). Seul un arrêt "
             "fail-closed — extract/match/submit en échec, ou stop opérateur — écourte alors "
             "la passe. La nuit du 17/09, le plafond de 10 avait laissé de côté 97 pages chez "
             "GameSeal, 54 chez Kinguin, 42 chez Gamivo, 36 chez Eneba et 23 chez G2A. "
             "Incompatible avec --max-pages.")
    ap.add_argument(
        "--max-pages", type=int, default=30,
        help="Cap pages processed per merchant (default 30). The sweep runs highest-page-"
             "first down to page 1, and the submit index is only productive on the ~28-30 "
             "shallowest pages — deeper pages are old/obscure titles that mostly 404 on "
             "resolve (slowest matching, ~0 candidate). Capping skips that junk for a big "
             "wall-clock win at ~0 productive loss; hitting the cap over a longer feed is "
             "recorded as coverage=incomplete_max_pages in the merchant's recap (honest, never "
             "a silent clean end) — it is NOT a halt: the batch continues and exits 0 (audit "
             "2026-09-09). Raise it for a deliberate deep sweep.")
    ap.add_argument("--available", default="all", choices=["all", "pending"])
    ap.add_argument("--pace", default=None)
    ap.add_argument("--triage", action="store_true",
                    help="Unified per-page workflow: after the ADDs, also plan the "
                         "routable skips' Move-to-List (dry-run plan by default).")
    ap.add_argument("--move-execute", action="store_true",
                    help="With --triage: REALLY move (06_move --mode safe, "
                         "canary-authorized lists only). Default: dry-run plan only.")
    ap.add_argument("--prove-gone-scan", action="store_true",
                    help="Prove each post-save disappearance by re-walking the WHOLE feed "
                         "(the pre-2026-09-10 behaviour) instead of the feed SEARCH filtered "
                         "by the offer URL (default since Romain's GO, ~50x faster per offer).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fully READ-ONLY preview: extract + match + triage plan, "
                         "NO submit and NO move (nothing written). ADDs are counted "
                         "from candidates.json, not created.")
    ap.add_argument("--consoles", dest="consoles", action="store_true", default=True,
                    help="[R45] match with the CONSOLE branch (03_match --consoles): console "
                         "keys resolve their AKS platform pages (Xbox One / Series, PS4 / PS5, "
                         "Switch / Switch 2) instead of the 'console' skip. This is the DEFAULT "
                         "since Romain's decision « 1 » of 2026-09-15 (after the two modal-v2 "
                         "canaries and the MMOGA console dry-run: 663 offers -> 174 console "
                         "candidates) — the flag is kept as an explicit no-op; --no-consoles "
                         "opts out. Real writes allowed since Romain's GO of 2026-09-15 (the "
                         "per-target modal v2 was observed with --inspect and proven by two "
                         "canaries: one target, then two targets); the --dry-run-only guard of "
                         "2026-09-14 is lifted.")
    ap.add_argument("--no-consoles", dest="consoles", action="store_false",
                    help="[R45] PC-only sweep: console rows keep the 'console' skip (the "
                         "pre-2026-09-15 behaviour). Recorded as recap.json['consoles'] = false "
                         "and passed to 03_match as --no-consoles.")
    args = ap.parse_args()
    # [R45] the "--consoles requires --dry-run" guard (review fix 2026-09-14) was LIFTED on
    # Romain's GO of 2026-09-15: the per-target modal v2 was observed (--inspect, run
    # 20260914-inspect-consoles) and proven by two real canaries (Legend of Mana Switch, one
    # target; Diablo 2 Resurrected Xbox One + Series, two targets via [data-add-target]).
    # 05_submit still gates every entry one by one (shape targets_v2, cap 3, readbacks).
    if args.all_pages and any(a.startswith("--max-pages") for a in sys.argv[1:]):
        print(json.dumps({"aborted": True,
                          "reason": "--all-pages et --max-pages sont exclusifs : choisis "
                                    "la couverture complète ou un plafond explicite"}))
        return 2
    if args.max_pages < 1 or args.start_page < 1:
        # Review 2026-09-09: with the cap now benign coverage (not a halt), a zero/negative
        # cap would be a silent exit-0 "done" run that processes NO page. Fail loud instead.
        print(json.dumps({"aborted": True,
                          "reason": f"--max-pages ({args.max_pages}) and --start-page "
                                    f"({args.start_page}) must be >= 1"}))
        return 2

    # Audit (Romain 2026-08-14): --move-execute only has an effect with --triage
    # (the Move stage is installed only then). Accepting it silently would let an
    # operator believe they requested real moves. Fail loud instead.
    if args.move_execute and not args.triage:
        print(json.dumps({"aborted": True, "reason": (
            "--move-execute n'a d'effet qu'avec --triage (le pas Move n'est installé "
            "que sous --triage). Ajoute --triage, ou retire --move-execute.")}))
        return 2

    if args.all_allowlisted and (args.targets or args.merchant or args.store_id):
        print(json.dumps({"aborted": True, "reason": (
            "--all-allowlisted balaie déjà toute la liste blanche — ne le combine pas avec "
            "--targets / --merchant / --store-id")}))
        return 2

    targets: list[tuple[str, str]] = []
    if args.all_allowlisted:
        from src.admin.auto_merchants import AUTO_MERCHANTS
        targets = [(name, store) for name, store in AUTO_MERCHANTS]
    elif args.targets:
        for tok in args.targets.split(","):
            tok = tok.strip()
            if not tok:
                continue
            if ":" not in tok:
                print(json.dumps({"aborted": True, "reason": f"bad target {tok!r} — attendu Merchant:store_id"}))
                return 2
            m, s = tok.rsplit(":", 1)
            targets.append((m.strip(), s.strip()))
    elif args.merchant and args.store_id:
        targets.append((args.merchant.strip(), args.store_id.strip()))
    if not targets:
        print(json.dumps({"aborted": True, "reason": "aucun marchand — --targets ou --merchant/--store-id"}))
        return 2
    for m, s in targets:
        if not s.isdigit():
            print(json.dumps({"aborted": True, "reason": f"store_id non numérique pour {m!r}: {s!r}"}))
            return 2
        # P2-2 (audit 2026-09-02): safe-auto WRITES without human validation, so the
        # merchant allowlist is an AUTHORITATIVE gate, not a UI suggestion. The HTTP
        # handler re-checks it (app.py _post_data_entry_auto), but this deterministic
        # CLI entrypoint — the one that actually spawns the writes — only validated
        # `store_id.isdigit()`, so `--targets 'Difmark:167'` (parked, non-vetted) could
        # sweep and create offers bypassing the gate. Enforce the SAME allowlist here,
        # fail-closed, refusing the whole batch on any miss (canonical store enforced).
        reason = rejection_reason(m, s)
        if reason is not None:
            print(json.dumps({"aborted": True, "reason": reason}))
            return 2

    _RUNNER.install()

    run_id = args.run_id or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-auto"
    sweep_dir = ROOT / "runs" / run_id
    # Le marqueur AVANT la création du dossier : un refus ne doit pas laisser derrière lui un
    # `runs/<run-id>/` vide (audit du 2026-09-18).
    try:
        run_marker.write_marker(ROOT, run_id=run_id, kind="data_entry_auto", source="cli")
    except run_marker.ActiveRunExists as exc:
        print(json.dumps({"aborted": True, "reason": str(exc), "active": exc.marker},
                         ensure_ascii=False, indent=2))
        return 2
    atexit.register(run_marker.clear_marker, ROOT, run_id)
    # Réfuteur du 2026-09-19 : une relance explicite avec le MÊME --run-id héritait du
    # `targets_queue.closed` du run précédent (tout ajout refusé « sweep_finishing » dès le
    # premier marchand) ET de son ancienne file (un marchand non demandé rebalayé). Un
    # lancement démarre avec un canal PROPRE : `--targets` est tout le plan. `missing_ok`
    # couvre aussi le dossier absent, donc unlink → mkdir tient dans les deux cas.
    # …mais SEULEMENT sur une relance (un recap.json existe déjà). Revue `/code-review` : la
    # console déclare le run occupé (dossier créé, marqueur `_active`) AVANT de lancer ce
    # processus — un ajout accepté pendant notre démarrage vivait déjà dans la file et
    # l'effacement inconditionnel le détruisait. Un dossier neuf de la console ne contient
    # qu'admin_submit.json : sa file est pour NOUS.
    if (sweep_dir / "recap.json").exists():
        (sweep_dir / TARGETS_QUEUE).unlink(missing_ok=True)
    sweep_dir.mkdir(parents=True, exist_ok=True)
    recap = {"run_id": run_id, "started_at": _clock(), "targets": [], "halted": None,
             "halted_merchants": [],
             "coverage_incomplete": [], "total_created": 0, "total_moved": 0,
             "consoles": bool(args.consoles)}          # [R45] console branch on? (default since 2026-09-15)
    recap_path = sweep_dir / "recap.json"

    # DISCOVERY for the console (Romain 2026-09-17: « un monitoring sur l'admin même lorsqu'on
    # lance en ligne de commande »). SubmitManager only knows the children it spawned, so a
    # sweep started from a terminal was invisible there and the "Lancer" button did not even
    # refuse while it ran. The marker makes it discoverable; ``/submit/status`` already reads
    # this run's artefacts from disk, so the console shows its progress like any other.
    # Liveness is decided by the PID (src/run_marker.py), so a SIGKILL can never wedge the
    # console: the marker simply stops being active. A dry-run is marked too — it drives the
    # browser just the same, and a console launch during one must be refused.
    def persist():
        recap["updated_at"] = _clock()
        # (t.get("recap") or {}) — a target's recap is None until its sweep starts
        # producing pages; `.get("recap", {})` would return that None (key exists)
        # and crash on None.get().
        recap["total_created"] = sum((t.get("recap") or {}).get("total_created", 0)
                                     for t in recap["targets"])
        recap["total_moved"] = sum((t.get("recap") or {}).get("total_moved", 0)
                                   for t in recap["targets"])
        # ÉCRITURE ATOMIQUE (audit du 2026-09-18) : `recap.json` est le contrat que la console
        # relit EN DIRECT, et il était réécrit en place (troncature puis réécriture) après
        # CHAQUE page, toute la nuit. Une lecture tombant dans la fenêtre voyait un JSON
        # tronqué. Le dépôt a déjà cette convention (`validation_io`, `run_marker`) : tmp dans
        # le MÊME dossier, donc même système de fichiers, puis `os.replace`.
        tmp = recap_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, recap_path)

    persist()
    # Boucle INDEXÉE, pas un `for … in targets` : la file peut s'allonger pendant le run
    # (Romain 2026-09-19 : « on a l'option pour ajouter un marchand à un sweep en cours ? »).
    # On relit la file de la console à CHAQUE frontière de marchand — jamais au milieu d'une
    # page : une cible ajoutée ne coupe rien, elle attend son tour. `planned` porte la liste
    # déjà connue, en minuscules, pour qu'un double clic n'ajoute pas deux fois le même
    # marchand, et pour qu'un marchand déjà balayé ne soit pas rebalayé.
    planned = {(m.casefold(), str(sid)) for m, sid in targets}
    refused_keys: set[tuple[str, str]] = set()
    taken_keys: set[tuple[str, str]] = set()
    # Réfuteur du 2026-09-19 : la console ne POUVAIT pas savoir qu'un marchand était déjà cible
    # — `recap["targets"]` ne liste que ceux déjà démarrés. `planned` est le plan complet, tenu
    # à jour à chaque ajout pris ; la console le lit avant de promettre quoi que ce soit.
    recap["planned"] = [{"merchant": m, "store_id": str(sid)} for m, sid in targets]
    recap["queue_closed"] = False
    persist()

    def drain_queue() -> list[tuple[str, str]]:
        before = tuple(len(recap.get(k) or []) for k in ("targets_added", "targets_refused", "targets_ignored"))
        new_targets = take_from_queue(sweep_dir, planned, refused_keys, recap, _clock, taken_keys)
        targets.extend(new_targets)
        recap["planned"].extend({"merchant": m, "store_id": str(sid)} for m, sid in new_targets)
        after = tuple(len(recap.get(k) or []) for k in ("targets_added", "targets_refused", "targets_ignored"))
        if after != before:
            persist()          # le recap dit d'où vient chaque marchand, et ce qui a été refusé
        return new_targets

    def close_queue(closed: bool) -> None:
        recap["queue_closed"] = bool(closed)
        persist()              # atomique : la console voit l'état AVANT la relecture qui suit

    index = 0
    while True:
        # La file est relue à chaque frontière de marchand — jamais au milieu d'une page.
        drain_queue()
        if index >= len(targets):
            if recap["queue_closed"]:
                break
            # Sur le point de sortir : on FERME d'abord (la console refuse dès maintenant),
            # PUIS on relit une dernière fois. Un ajout que la console a accepté sans voir la
            # fermeture a été écrit avant elle, donc cette relecture le voit. Si une
            # retardataire arrive, on la traite ET ON ROUVRE — revue `/code-review` : la
            # version précédente laissait la file fermée pendant tout son balayage (des
            # heures) alors que le lecteur continuait de relire à chaque frontière.
            close_queue(True)
            if drain_queue():
                close_queue(False)
            continue
        merchant, store_id = targets[index]
        # L'index n'avance qu'APRÈS le contrôle du stop (revue de Romain, 2026-09-19) : sinon
        # un arrêt tombant entre deux marchands excluait de `targets_not_reached` celui qui
        # venait d'être pris et n'avait JAMAIS démarré — le bilan d'arrêt l'oubliait purement.
        # Les `break` d'APRÈS le balayage, eux, trouvent l'index déjà avancé : le marchand
        # traité n'y figure pas, ce qui est correct.
        if _RUNNER.stopped:
            # AUDIT DU 2026-09-18 : ceci ÉCRASAIT les haltes fail-closed déjà accumulées par
            # `--continue-on-halt`, et comme le code de sortie rend 0 sur « operator_stop », un
            # run qui avait échoué sur plusieurs marchands sortait VERT dès qu'un stop
            # opérateur survenait ensuite. On CONCATÈNE : le stop est un événement de plus,
            # pas une amnistie.
            recap["halted"] = "; ".join(
                [*(recap.get("halted_merchants") or []), "operator_stop"])
            break
        index += 1
        slug = re.sub(r"[^a-z0-9]+", "-", merchant.lower()).strip("-") or "merchant"
        cfg = SweepConfig(merchant=merchant, store_id=store_id, start_page=args.start_page,
                          max_pages=(None if args.all_pages else args.max_pages),
                          consoles=args.consoles)
        stages = _make_stages(merchant, store_id, args.available, args.pace,
                              triage=args.triage, move_execute=args.move_execute,
                              dry_run=args.dry_run, prove_gone_scan=args.prove_gone_scan,
                              sweep_dir=sweep_dir, consoles=args.consoles)
        target_entry = {"merchant": merchant, "store_id": store_id, "recap": None}
        recap["targets"].append(target_entry)

        def on_page(live_recap, _t=target_entry):
            # Attach the LIVE sweep recap so the console sees per-page progress
            # BEFORE run_sweep returns (the reference is mutated in place).
            _t["recap"] = live_recap
            persist()

        sweep = run_sweep(cfg, stages,
                          page_run_id=lambda p, sl=slug, sid=store_id: f"{run_id}-{sl}-s{sid}-p{p}",
                          should_stop=lambda: _RUNNER.stopped, on_page=on_page)
        target_entry["recap"] = sweep
        if sweep.get("coverage"):
            # Benign coverage cap (max_pages / feed grew): surfaced at batch level for the
            # operator, but NOT a halt — the next merchant is still swept (audit 2026-09-09).
            recap["coverage_incomplete"].append(f"{merchant}: {sweep['coverage']}")
        persist()
        # A fail-closed halt on one merchant stops the whole batch (a broken
        # session / login bounce affects every subsequent merchant too) — unless
        # --continue-on-halt (Romain 2026-09-11, unattended multi-merchant nights): the
        # halt is recorded per merchant and the next feed is still swept. A login bounce
        # ("not logged in") stops the batch either way: no merchant can be read.
        if sweep.get("halted") and sweep["halted"] != "operator_stop":
            label = f"{merchant}: {sweep['halted']}"
            login_bounce = "not logged in" in str(sweep.get("halted_detail") or "").lower()
            if args.continue_on_halt and not login_bounce:
                recap["halted_merchants"].append(label)
                recap["halted"] = "; ".join(recap["halted_merchants"])
                persist()
                continue
            recap["halted"] = label
            break
        if _RUNNER.stopped:
            recap["halted"] = "; ".join(
                [*(recap.get("halted_merchants") or []), "operator_stop"])
            break

    # Réfuteur du 2026-09-19 : les `break` (stop opérateur, halte fail-closed) sortaient de la
    # boucle SANS fermer la file — pendant tout l'arrêt coopératif la console répondait encore
    # `queued: true` à des ajouts que plus personne ne lirait. Fermer ici couvre toute sortie ;
    # sur la fin naturelle c'est un second appel sans effet.
    # Toute sortie ferme la file — y compris les `break` (stop opérateur, halte). Puis UNE
    # relecture d'ENREGISTREMENT : revue `/code-review` (2026-09-19) — sur un `break`, un ajout
    # que la console avait accepté n'était ni balayé ni inscrit nulle part. Il est désormais
    # inscrit `targets_not_reached`, avec les cibles prises mais jamais démarrées.
    # …et elle est PUBLIÉE (persist) AVANT cette relecture, pas seulement mise en mémoire.
    # Revue de Romain (2026-09-19) : sur une sortie par `break` (stop, halte), le drapeau ne
    # touchait le disque qu'au tout dernier `persist()`. Entre les deux, la console lisait
    # encore « ouverte », répondait `queued: true`, et l'entrée tombait APRÈS la relecture
    # finale : ni balayée, ni inscrite dans `targets_not_reached`. Promesse tenue par personne.
    # Publier d'abord rétablit le même happens-before que dans la boucle : un ajout accepté
    # sans avoir vu la fermeture a été écrit avant elle, donc la relecture qui suit le voit.
    close_queue(True)
    late = take_from_queue(sweep_dir, planned, refused_keys, recap, _clock, taken_keys)
    not_reached = [{"merchant": m, "store_id": str(sid)} for m, sid in targets[index:]]
    not_reached += [{"merchant": m, "store_id": str(sid)} for m, sid in late]
    if not_reached:
        recap["targets_not_reached"] = not_reached
    recap["finished_at"] = _clock()
    persist()
    print(json.dumps({"run_id": run_id, "total_created": recap["total_created"],
                      "total_moved": recap["total_moved"],
                      "halted": recap["halted"], "targets": len(recap["targets"]),
                      "coverage_incomplete": recap["coverage_incomplete"],
                      "recap": str(recap_path)}, ensure_ascii=False, indent=2))
    # [34] Fable re-audit 2026-09-06: exit non-zero when the sweep HALTED fail-closed, so
    # a supervising caller (manager / CI) sees the failure instead of a green exit 0. A
    # clean run or a cooperative operator stop is a 0.
    # Le marqueur est rendu ICI, pas seulement à la sortie du processus : depuis que
    # `write_marker` refuse d'écraser un run vivant (audit du 2026-09-18), le garder jusqu'à
    # l'`atexit` ferait refuser un second sweep lancé dans le MÊME processus. L'`atexit` reste
    # en place pour les sorties brutales.
    run_marker.clear_marker(ROOT, run_id)
    # Un stop opérateur SEUL reste un 0 ([34], inchangé) ; un stop qui suit des haltes
    # fail-closed rend 2, parce que les haltes, elles, sont des échecs (audit 2026-09-18).
    return 0 if recap["halted"] in (None, "operator_stop") else 2


if __name__ == "__main__":
    raise SystemExit(main())
