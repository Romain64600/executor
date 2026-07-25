#!/usr/bin/env python3
"""Stage 9 — sort-move writer: execute ONE target list of an all-stores sort plan.

Consumes ``sort_plan.json`` (Stage 8) and moves the offers of ONE target list to
that list — Romain's per-list bulk validation (2026-07-23). The list spans many
stores, so the plan is split per store and the proven single-store ``Mover``
(RV2: gone-from-source AND present-on-target) runs once per store.

Same fail-closed discipline as Stage 6: invariants green AND authoritative, one
CDP tab under the browser lock, dry-run by default (``--execute`` writes), R24
modes (``learning`` = canary of 1; ``safe`` = the full list behind
``--i-authorize-batch`` + a canary-granted sort authorization). A verified canary
authorizes that list's LABEL for the batch, across stores. NEVER fire-and-forget.

Examples (on the VPS):
  python3 scripts/09_sort_move.py runs/<sort-id> --list 8                       # dry-run (plan only)
  python3 scripts/09_sort_move.py runs/<sort-id> --list 8 --execute --mode learning         # canary of 1 (REAL)
  python3 scripts/09_sort_move.py runs/<sort-id> --list 8 --execute --mode safe --i-authorize-batch  # full list (REAL)
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.mover import DryRunMover, Mover, FEED_UNREADABLE_EXCS  # noqa: E402
from src.move_auth import grant_from_sort_canary, sort_batch_authorized  # noqa: E402
from src.pacing import Pacer  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.sort_move import build_sort_move_plan  # noqa: E402
from src.step_guard import BlockLedger, StepGuard  # noqa: E402
from src.submit_session import SubmitSession, WriteSubmitSession  # noqa: E402

DEFAULT_MAX_PAGES = 40
AUTO_MAX_PAGES_HEADROOM = 1.3
CANARY_MODES = ("learning", "advanced")
CANARY_LIMIT = 1
# How many stores may trip the per-store 10-failure breaker before the whole
# list batch is deemed systemically broken and stops. Below this, a breaker-
# tripped store is skipped and the batch continues to the next store (one stale
# store must not kill the list).
BREAKER_STORE_LIMIT = 3

# Cooperative stop: SIGTERM (from the admin "Arrêter" button, or the CLI) sets
# this flag; the mover checks it at safe points (page boundary / between offers)
# and stops without cutting a move mid-Apply. A plain kill still works, but this
# is the clean path.
_STOP = False


def _on_term(_signum, _frame):
    global _STOP
    _STOP = True


def mode_limit(mode: str, requested: int | None) -> int | None:
    if mode not in CANARY_MODES:
        return requested
    return CANARY_LIMIT if requested is None else min(requested, CANARY_LIMIT)


def derive_max_pages(explicit: int | None, run_dir: Path) -> tuple[int, str]:
    if explicit is not None:
        return explicit, f"explicit --max-pages {explicit}"
    feed_pages = 0
    try:
        feed = json.loads((run_dir / "offers.json").read_text(encoding="utf-8"))
        feed_pages = int(feed.get("feed_last_page") or 0)
    except (OSError, ValueError, TypeError):
        feed_pages = 0
    if feed_pages <= 0:
        return DEFAULT_MAX_PAGES, f"auto: feed page count unknown → default {DEFAULT_MAX_PAGES}"
    derived = max(DEFAULT_MAX_PAGES, math.ceil(feed_pages * AUTO_MAX_PAGES_HEADROOM))
    return derived, f"auto: feed advertises {feed_pages} page(s) → max_pages {derived}"


def _status(entry: dict, write: bool) -> str:
    if entry.get("skipped"):
        return f"SKIP ({entry['skipped']})"
    if not entry.get("ready"):
        return f"BLOCKED ({entry.get('blocker')})"
    if not write:
        return "READY"
    if entry.get("moved"):
        return f"MOVED ({entry.get('post_verify')})"
    return f"FAILED ({entry.get('blocker') or entry.get('post_verify')})"


def main() -> int:
    signal.signal(signal.SIGTERM, _on_term)  # clean cooperative stop on SIGTERM
    try:
        with browser_lock(ROOT, label="09_sort_move " + " ".join(sys.argv[1:])[:160]):
            return _main()
    except BrowserBusyError as exc:
        print(json.dumps({"aborted": True, "reason": str(exc)}, indent=2))
        return 2


def _main() -> int:
    parser = argparse.ArgumentParser(description="AKS sort-move writer (Stage 9).")
    parser.add_argument("run_dir", help="Path to the sort run directory (runs/<id>).")
    parser.add_argument("--list", dest="list_id", required=True,
                        help="Target list id to process (from sort_plan.json), e.g. 8.")
    parser.add_argument("--store", default=None,
                        help="Limit to this store id (default: every store in the list).")
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--execute", action="store_true", help="REAL move (default: dry-run).")
    parser.add_argument("--mode", default="safe", choices=["safe", "learning", "advanced"],
                        help="R24: safe = full list (batch); learning/advanced = canary of 1.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Global cap on moves across stores. Narrows a canary, never widens.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--pace-pages", default="0.4-0.6")
    parser.add_argument("--pace-offers", default="0.5-1.5")
    parser.add_argument("--acknowledge-block", action="store_true")
    parser.add_argument("--i-authorize-batch", action="store_true",
                        help="Explicit second intention for --mode safe (the full list). Required "
                             "IN ADDITION to a canary-granted sort authorization covering the list.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(json.dumps({"aborted": True, "reason": f"run dir absent: {run_dir}"}, indent=2))
        return 2
    if args.mode in CANARY_MODES and args.limit is not None and args.limit > CANARY_LIMIT:
        print(json.dumps({"aborted": True, "reason": (
            f"--mode {args.mode} is capped at a canary of {CANARY_LIMIT} "
            f"(--limit {args.limit} would widen it). Use --mode safe for the full list.")}, indent=2))
        return 2

    plan_doc = build_sort_move_plan(run_dir, args.list_id)
    (run_dir / f"sort_move_plan_{args.list_id}_source.json").write_text(
        json.dumps(plan_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    source_list = plan_doc["source_feed_page"]
    label = plan_doc["target_list_label"]
    by_store = plan_doc["by_store"]
    if args.store:
        by_store = {args.store: by_store[args.store]} if args.store in by_store else {}
    all_entries = [e for entries in by_store.values() for e in entries]
    if not all_entries:
        print(json.dumps({"aborted": False,
                          "reason": f"aucune offre à déplacer pour la liste {args.list_id}"
                          + (f" sur le store {args.store}" if args.store else ""),
                          "excluded": plan_doc["excluded"], "counts": plan_doc["counts"]}, indent=2))
        return 0

    write = args.execute
    # Batch gate: --execute --mode safe requires the explicit flag AND a
    # canary-granted sort authorization covering THIS list's label (RV3), across
    # stores. RV2 still proves each individual move (gone-from-source + on-target).
    if write and args.mode == "safe":
        covered, why = sort_batch_authorized(run_dir, all_entries, source_feed_page=source_list)
        if not args.i_authorize_batch:
            print(json.dumps({"aborted": True, "reason": (
                "batch (--execute --mode safe) requiert le flag --i-authorize-batch "
                "(double intention). " + ("L'autorisation couvrirait cette liste."
                                          if covered else "De plus, l'autorisation ne la couvre pas.")),
                "batch_would_be_covered": covered, "authorization": why}, indent=2))
            return 2
        if not covered:
            print(json.dumps({"aborted": True, "reason": (
                "batch (--execute --mode safe) refusé — autorisation insuffisante : " + why
                + ". Valide la liste par un canary --mode learning d'abord.")}, indent=2))
            return 2
        print(f"BATCH AUTORISÉ (--i-authorize-batch + {why}) — {len(all_entries)} offre(s) "
              f"→ {label} sur {len(by_store)} store(s) ; chaque move prouve source+cible (RV2).",
              file=sys.stderr)

    report = None
    for attempt in range(3):
        report = build_report(endpoint=args.endpoint)
        if report["ok"] and report["authoritative"]:
            break
        if attempt < 2:
            time.sleep(2)
    if not (report["ok"] and report["authoritative"]):
        print(json.dumps({"aborted": True, "reason": "invariants not green/authoritative after retries",
                          "ok": report["ok"], "authoritative": report["authoritative"]}, indent=2))
        return 2

    max_pages, max_pages_note = derive_max_pages(args.max_pages, run_dir)
    limit = mode_limit(args.mode, args.limit)
    run_id = plan_doc.get("run_id") or run_dir.name
    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))

    ledger = BlockLedger(run_dir / f"sort_move_guard_ledger_{args.list_id}.json")
    if write:
        if args.acknowledge_block:
            ledger.acknowledge("operator --acknowledge-block on the CLI")
        elif ledger.requires_ack():
            print(json.dumps({"aborted": True, "reason": (
                "les DEUX dernières passes réelles de cette liste ont fini guard-blocked "
                "— inspecte le feed puis relance avec --acknowledge-block (FC3)"),
                "last_block": ledger.load().get("last_block") or {}}, indent=2))
            return 2

    try:
        page_pacer = Pacer.from_spec(args.pace_pages)
        offer_pacer = Pacer.from_spec(args.pace_offers)
    except ValueError as exc:
        print(json.dumps({"aborted": True, "reason": f"bad --pace spec: {exc}"}, indent=2))
        return 2

    if write:
        print(f"REAL MOVE (mode={args.mode}) — up to {limit if limit is not None else 'ALL'} "
              f"offer(s) → {label} across {len(by_store)} store(s). Source={source_list}, "
              f"{max_pages_note}.", file=sys.stderr)
    else:
        print(f"DRY-RUN — {len(all_entries)} offre(s) → {label} across {len(by_store)} store(s), "
              f"source={source_list}, {max_pages_note}.", file=sys.stderr)

    session_cls = WriteSubmitSession if write else SubmitSession
    mover_cls = Mover if write else DryRunMover
    agg = {"list_id": args.list_id, "target_list_label": label, "source_feed_page": source_list,
           "mode": args.mode, "write": write, "stores": {}, "moved": 0, "move_attempts": 0,
           "plan": [], "aborted": None, "stopped": None}
    moved_entries: list[dict] = []
    remaining = limit
    blocked_any = False

    try:
        with session_cls(args.endpoint) as session:
            for store, entries in by_store.items():
                if _STOP:
                    agg["stopped"] = "operator_stop"
                    break
                if remaining is not None and remaining <= 0:
                    agg["stopped"] = "limit_reached"
                    break
                store_guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=2,
                                        max_consecutive_failures=10, max_failures_per_task=10 ** 9)
                mover = mover_cls(session, logger=logger, guard=store_guard,
                                  page_pacer=page_pacer, offer_pacer=offer_pacer)
                try:
                    result = mover.run(run_id=f"{run_id}:{args.list_id}:store{store}",
                                       store_id=store, plan=entries, source_feed_page=source_list,
                                       available=args.available, max_pages=max_pages,
                                       limit=remaining, should_stop=lambda: _STOP)
                except FEED_UNREADABLE_EXCS as exc:
                    agg["aborted"] = f"feed_unreadable (store {store}): {exc}"
                    break
                agg["stores"][store] = {"moved": result.get("moved"),
                                        "attempts": result.get("move_attempts"),
                                        "aborted": result.get("aborted"),
                                        "stopped": result.get("stopped"),
                                        "offers": len(entries)}
                agg["moved"] += result.get("moved", 0)
                agg["move_attempts"] += result.get("move_attempts", 0)
                for e in result["plan"]:
                    e["store_id"] = str(store)
                    agg["plan"].append(e)
                    if e.get("moved"):
                        moved_entries.append(e)
                if remaining is not None:
                    remaining -= result.get("move_attempts", 0)
                if store_guard.snapshot().get("blocked"):
                    blocked_any = True
                # A hard abort or an operator stop halts the whole list immediately.
                if result.get("aborted"):
                    agg["aborted"] = agg["aborted"] or result.get("aborted")
                    break
                if result.get("stopped") == "operator_stop":
                    agg["stopped"] = "operator_stop"
                    break
                # A per-store breaker (10 consecutive failures / guard-blocked)
                # means THAT store's plan data is stale (identity churn) — skip it
                # and continue to the next store, so one churned store no longer
                # kills the whole list. Stop only if TOO MANY stores trip (that IS
                # a systemic problem, not one stale store).
                if result.get("stopped") in ("ten_consecutive_failures", "guard_blocked"):
                    agg.setdefault("breaker_stores", []).append(str(store))
                    if len(agg["breaker_stores"]) >= BREAKER_STORE_LIMIT:
                        agg["stopped"] = "too_many_breaker_stores"
                        break
                    continue
    except FEED_UNREADABLE_EXCS as exc:
        print(json.dumps({"aborted": True,
                          "reason": f"fail-closed abort (feed/CDP unreadable): {exc}"}, indent=2))
        return 2

    if write:
        ledger.record(task_id=f"{run_id}:{args.list_id}", blocked=blocked_any,
                      rule="sort-move", reason=agg.get("aborted") or agg.get("stopped"))

    # RV3: a verified canary grants/extends the sort authorization for this label.
    if write and args.mode in CANARY_MODES and agg["moved"] > 0:
        auth = grant_from_sort_canary(
            run_dir, source_feed_page=source_list, moved_entries=moved_entries,
            clock=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        agg["authorization"] = {"version": auth["version"],
                                "authorized_target_lists": auth["authorized_target_lists"],
                                "note": "canary sort authorization recorded — batch stays a separate go"}

    agg["excluded"] = plan_doc["excluded"]
    agg["limit"] = limit
    (run_dir / f"sort_move_result_{args.list_id}.json").write_text(
        json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8")

    # Cumulative moved tally per target list. The per-run result file is
    # overwritten by the next run on the same list, but this tally ACCUMULATES so
    # the console can show what a list has actually received. Real moves only
    # (write runs); idempotent re-runs add 0 (they skip already-moved offers), so
    # it never double-counts. Runs are serialized by the browser flock → no race.
    if write:
        tally_path = run_dir / "sort_move_tally.json"
        try:
            tally = json.loads(tally_path.read_text(encoding="utf-8")) if tally_path.is_file() else {}
        except (json.JSONDecodeError, OSError):
            tally = {}
        cur = tally.get(args.list_id) or {"moved_total": 0, "attempts_total": 0, "runs": 0}
        cur["label"] = label
        cur["moved_total"] = int(cur.get("moved_total", 0)) + int(agg["moved"])
        cur["attempts_total"] = int(cur.get("attempts_total", 0)) + int(agg["move_attempts"])
        cur["runs"] = int(cur.get("runs", 0)) + 1
        cur["last_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur["last_mode"] = args.mode
        tally[args.list_id] = cur
        tally_path.write_text(json.dumps(tally, indent=2, ensure_ascii=False), encoding="utf-8")
        agg["moved_total_for_list"] = cur["moved_total"]

    # Coherent, append-only history: one line PER RUN (never clobbered, unlike the
    # per-run result file). Reasons are broken out so a re-run on a stale plan is
    # legible (few moves + many "already gone" / "identity contradicted").
    hist = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "list_id": args.list_id, "label": label, "mode": args.mode, "write": write,
        "moved": agg["moved"], "attempts": agg["move_attempts"], "stores": len(agg["stores"]),
        "already_gone": sum(1 for e in agg["plan"] if e.get("skipped")),
        "identity_blocked": sum(1 for e in agg["plan"] if e.get("blocker") and not e.get("ready")),
        "apply_not_confirmed": sum(1 for e in agg["plan"] if e.get("ready") and not e.get("moved")),
        "stopped": agg["stopped"], "aborted": agg["aborted"],
    }
    with (run_dir / "sort_move_history.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(hist, ensure_ascii=False) + "\n")

    print(f"\n{'MOVE' if write else 'DRY-RUN'} — liste {args.list_id} ({label}), mode={args.mode} — "
          f"moved={agg['moved']}, attempts={agg['move_attempts']}, stores={len(agg['stores'])}, "
          f"aborted={agg['aborted']}, stopped={agg['stopped']}")
    for entry in agg["plan"][:40]:
        print(f"  [{_status(entry, write)}] store {entry.get('store_id')} · {entry.get('name', '')[:46]}")
    if len(agg["plan"]) > 40:
        print(f"  … (+{len(agg['plan']) - 40} autres, voir sort_move_result_{args.list_id}.json)")
    print(json.dumps({"list_id": args.list_id, "label": label, "moved": agg["moved"],
                      "attempts": agg["move_attempts"], "aborted": agg["aborted"],
                      "stopped": agg["stopped"], "excluded": len(plan_doc["excluded"]),
                      "artifact": str(run_dir / f"sort_move_result_{args.list_id}.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
