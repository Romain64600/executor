#!/usr/bin/env python3
"""Stage 12 — SUBMIT the by-urls dry-run's candidates (the "Saisir" button).

Reads a finished ``*-by-urls`` run's recap, groups its match-validated candidates
by merchant STORE (deduped by fingerprint), and submits each group as ONE standard
safe batch (R24: safe = full validated batch, no canary on the ADD path). Per
merchant it builds the validation triple exactly like Safe-Auto
(``apply_overrides_and_validate`` + ``04_validate check`` — approved.json is never
hand-authored) and shells the UNMODIFIED ``05_submit.py --mode safe --submit``, so
every fail-closed gate re-enforces itself: locate the CURRENT row (re-locate by
stable URL since the feed drifted since the dry-run), prove success = offer gone
from the refreshed feed, 10-consecutive-failure breaker, NotLoggedInError = STOP
(never re-auth). The FIRST non-clean merchant halts the whole batch fail-closed.

SIGTERM (console "Arrêter") stops cooperatively — the current 05_submit child is
signalled (it stops at an offer boundary, never mid-Create) and the batch halts
BETWEEN merchants. Never fire-and-forget: run supervised by the admin manager.
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.admin.runs import sha256_file  # noqa: E402
from src.admin.validation_io import apply_overrides_and_validate  # noqa: E402
from src.data_entry_auto import SubmitOutcome, run_by_urls_submit  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.validation import candidate_fingerprint  # noqa: E402

_STOP = False
_CHILD: "subprocess.Popen | None" = None


def _on_term(_signum, _frame):
    # Cooperative stop: set the flag AND forward SIGTERM to the current 05_submit
    # child (it stops at an offer boundary — never mid-Create — then exits); the
    # batch then halts between merchants. Never SIGKILL here (that would risk a
    # mid-write kill); the manager's own escalation guarantees termination.
    global _STOP
    _STOP = True
    child = _CHILD
    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except Exception:
            pass


def _run_child(argv: list[str]) -> int:
    global _CHILD
    _CHILD = subprocess.Popen(argv, cwd=str(ROOT), start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if _STOP and _CHILD.poll() is None:
        try:
            _CHILD.terminate()
        except Exception:
            pass
    try:
        return _CHILD.wait()
    finally:
        _CHILD = None


def _read_submit_plan(run_dir: Path, rc: int) -> SubmitOutcome:
    """Deterministic result: success = the offer GONE from the refreshed feed
    (``post_save`` contains "gone"), never a self-assessment (EXECUTOR_RULES)."""
    try:
        plan = json.loads((run_dir / "submit_plan.json").read_text(encoding="utf-8"))
    except Exception:
        plan = {}
    offers, created = [], 0
    for e in plan.get("plan", []):
        ps = str(e.get("post_save") or "")
        ok = "gone" in ps.lower()
        if ok:
            created += 1
        offers.append({"name": e.get("merchant_title"), "aks_id": e.get("aks_product_id"),
                       "region_id": e.get("region_id"), "edition_id": e.get("edition_id"),
                       "created": ok, "post_save": ps})
    return SubmitOutcome(ok=(rc == 0), aborted=plan.get("aborted"), stopped=plan.get("stopped"),
                         created=created, offers=offers, detail="" if rc == 0 else f"exit {rc}")


def _make_submit_merchant(available: str, logger: RunLogger):
    py = sys.executable

    def submit_merchant(merchant: str, store_id: str, candidates: list, sub_run: Path) -> SubmitOutcome:
        logger.log("merchant_submit", merchant=merchant, store_id=store_id,
                   attempted=len(candidates))
        sub_run.mkdir(parents=True, exist_ok=True)
        # The three inputs 05_submit expects, built exactly like Safe-Auto's approve:
        # offers.json (merchant/store derivation), candidates.json (the validated set),
        # match_meta safe (FC5), then the atomic triple via apply_overrides_and_validate.
        (sub_run / "offers.json").write_text(json.dumps(
            {"merchant": merchant, "offers": [c["offer"] for c in candidates]},
            ensure_ascii=False), encoding="utf-8")
        cpath = sub_run / "candidates.json"
        cpath.write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
        (sub_run / "match_meta.json").write_text(json.dumps({"data_entry_mode": "safe"}),
                                                 encoding="utf-8")
        payload = {
            "validated_by": "auto (saisie par jeux)",
            "candidates_sha256": sha256_file(cpath),
            "decisions": [{"fingerprint": candidate_fingerprint(c), "approve": True}
                          for c in candidates],
        }
        try:
            apply_overrides_and_validate(sub_run, payload, repo_root=ROOT, created_offer_ids=None)
        except Exception as exc:
            # A stale/refused triple (ValidationIOError) OR any other failure building
            # it (OSError under disk pressure, a 04_validate spawn error, …) is a
            # per-merchant NON-CLEAN halt — never an uncaught crash of the orchestrator
            # (adversarial review 2026-08-25). The batch then stops fail-closed with a
            # structured recap entry, no plow-forward.
            code = getattr(exc, "code", None) or type(exc).__name__
            logger.log("merchant_submitted", merchant=merchant, created=0,
                       attempted=len(candidates), halted=str(code))
            return SubmitOutcome(ok=False, aborted=f"{code}: {exc}"[:160])
        # UNMODIFIED 05_submit --mode safe. No --page-hint (by-urls offers are
        # scattered across the feed; locate falls back to a whole-feed index and
        # prove-gone is whole-feed anyway). No --limit (safe = full batch, R24).
        argv = [py, str(ROOT / "scripts" / "05_submit.py"), str(sub_run / "approved.json"),
                "--merchant", merchant, "--store-id", store_id,
                "--mode", "safe", "--submit", "--available", available]
        rc = _run_child(argv)
        outcome = _read_submit_plan(sub_run, rc)
        logger.log("merchant_submitted", merchant=merchant, created=outcome.created,
                   attempted=len(candidates), halted=outcome.halt_reason())
        return outcome

    return submit_merchant


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Submit a by-urls dry-run's candidates (safe).")
    ap.add_argument("--from-run", required=True, help="The *-by-urls run whose recap to submit.")
    ap.add_argument("--run-id", required=True, help="This submit run id (holds recap.json).")
    ap.add_argument("--available", default="all", choices=["all", "pending"])
    ap.add_argument("--mode", default="safe", choices=["safe"])  # R24: ADD path is safe only
    args = ap.parse_args(argv)

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(args.run_id, log_dir=ROOT / "logs")

    src_recap_path = ROOT / "runs" / args.from_run / "recap.json"
    try:
        from_recap = json.loads(src_recap_path.read_text(encoding="utf-8"))
    except Exception as exc:
        recap = {"mode": "submit", "aborted": f"source_recap_unreadable: {exc}"[:160],
                 "merchants": [], "totals": {"merchants": 0, "attempted": 0, "created": 0}}
        (run_dir / "recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        print(json.dumps({"run_id": args.run_id, "aborted": recap["aborted"]}))
        return 2

    available = from_recap.get("available") or args.available

    def flush(recap: dict) -> None:
        (run_dir / "recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2),
                                            encoding="utf-8")

    def make_sub_run(store_id: str) -> Path:
        return ROOT / "runs" / f"{args.run_id}-s{store_id}"

    logger.log("submit_run_start", from_run=args.from_run, available=available)
    recap = run_by_urls_submit(
        from_recap, available=available,
        submit_merchant=_make_submit_merchant(available, logger),
        make_sub_run=make_sub_run, flush=flush,
        should_stop=lambda: _STOP)
    if recap.get("aborted"):
        logger.log("submit_run_aborted", reason=recap["aborted"])
    else:
        logger.log("submit_run_done", created=recap["totals"]["created"],
                   merchants=recap["totals"]["merchants"])

    print(json.dumps({"run_id": args.run_id, "mode": "submit",
                      "created": recap["totals"]["created"],
                      "attempted": recap["totals"]["attempted"],
                      "merchants": recap["totals"]["merchants"],
                      "aborted": recap.get("aborted")}))
    return 0 if not recap.get("aborted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
