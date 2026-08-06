#!/usr/bin/env python3
"""Safe-auto data-entry sweep — CLI (Romain's "mode rapide safe auto", 2026-08-04).

For each target ``merchant:store_id``, sweep the feed page by page:
extract (02) → match (03) → auto-approve EVERY matcher candidate → submit (05,
``--mode safe`` real write). NO human validation; the matcher is the safety gate.
A per-page recap is written to ``runs/<run-id>/recap.json`` incrementally; Romain
audits it and deletes any mistake afterwards.

Supervised, NEVER fire-and-forget: this runs as ONE manager-tracked process. A
SIGTERM (the console "Arrêter" button) stops cooperatively — the current child
stage is signalled and the sweep halts between pages. Fail-closed: any stage that
does not finish clean HALTS the whole sweep (no plowing through a broken session);
a NotLoggedIn/feed-unreadable abort stops it, never a re-auth.

  python3 scripts/10_data_entry_auto.py --targets "Kinguin:58" --run-id <id>
  python3 scripts/10_data_entry_auto.py --targets "Kinguin:58,Eneba:70" --max-pages 50
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_entry_auto import (  # noqa: E402
    ExtractOutcome, MatchOutcome, Stages, StageError, SubmitOutcome, SweepConfig, run_sweep,
)
from src.admin.validation_io import apply_overrides_and_validate, ValidationIOError  # noqa: E402
from src.admin.runs import sha256_file  # noqa: E402
from src.validation import candidate_fingerprint  # noqa: E402

_STOP = False
_CHILD: subprocess.Popen | None = None


def _on_term(_signum, _frame):
    # Cooperative stop: set the flag AND forward SIGTERM to the current child.
    # 05_submit/02/03 each stop at their OWN safe boundary (05 at an offer
    # boundary — never mid-Create), then exit; run_sweep then halts between
    # pages. We never SIGKILL the child here (that is what caused mid-write
    # kills); the manager's own escalation guarantees eventual termination.
    global _STOP
    _STOP = True
    child = _CHILD
    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except Exception:
            pass


def _run_child(argv: list[str]) -> int:
    """Run a stage script as a child for cooperative SIGTERM. ``start_new_session``
    puts it in its own process group (a SIGKILL of THIS sweep never cascades to a
    child mid-write), and its stdout/stderr are detached so a lingering child can
    never pin the manager supervisor's pipe."""
    global _CHILD
    _CHILD = subprocess.Popen(argv, cwd=str(ROOT), start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # If a stop arrived during the fork window, terminate immediately.
    if _STOP and _CHILD.poll() is None:
        try:
            _CHILD.terminate()
        except Exception:
            pass
    try:
        return _CHILD.wait()
    finally:
        _CHILD = None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_stages(merchant: str, store_id: str, available: str, pace: str | None) -> Stages:
    py = sys.executable

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
        return ExtractOutcome(ok=(rc == 0), offers=int(n or 0),
                              feed_last_page=int(flp) if flp else None,
                              detail="" if rc == 0 else f"exit {rc}")

    def match(run_id: str) -> MatchOutcome:
        rc = _run_child([py, str(ROOT / "scripts" / "03_match.py"),
                         str(ROOT / "runs" / run_id / "offers.json")])
        cands = _load_json(ROOT / "runs" / run_id / "candidates.json")
        n = len(cands) if isinstance(cands, list) else 0
        return MatchOutcome(ok=(rc == 0), candidates=n, detail="" if rc == 0 else f"exit {rc}")

    def approve(run_id: str) -> int:
        run_dir = ROOT / "runs" / run_id
        cpath = run_dir / "candidates.json"
        cands = _load_json(cpath) or []
        payload = {
            "validated_by": "auto (safe-auto data entry)",
            "candidates_sha256": sha256_file(cpath),
            "decisions": [{"fingerprint": candidate_fingerprint(c), "approve": True} for c in cands],
        }
        try:
            res = apply_overrides_and_validate(run_dir, payload, repo_root=ROOT, created_offer_ids=None)
        except ValidationIOError as exc:
            # A stale candidates.json (feed re-import between match and approve) or
            # any validation refusal is a fail-closed halt, recorded in the recap
            # — never a bare crash that drops the page silently.
            raise StageError(f"{getattr(exc, 'code', 'validation')}: {exc}")
        return int(res.get("approved_count") or 0)

    def submit(run_id: str) -> SubmitOutcome:
        run_dir = ROOT / "runs" / run_id
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
        if pace:
            argv += ["--pace", pace]
        rc = _run_child(argv)
        plan = _load_json(run_dir / "submit_plan.json") or {}
        offers = []
        created = 0
        for e in plan.get("plan", []):
            ps = str(e.get("post_save") or "")
            ok = "gone" in ps.lower()
            if ok:
                created += 1
            offers.append({"name": e.get("merchant_title"), "aks_id": e.get("aks_product_id"),
                           "region_id": e.get("region_id"), "edition_id": e.get("edition_id"),
                           "created": ok, "post_save": ps})
        return SubmitOutcome(ok=(rc == 0), aborted=plan.get("aborted"),
                             stopped=plan.get("stopped"),
                             created=created, offers=offers, detail="" if rc == 0 else f"exit {rc}")

    return Stages(extract=extract, match=match, approve=approve, submit=submit)


def main() -> int:
    ap = argparse.ArgumentParser(description="Safe-auto data-entry sweep (real writes).")
    ap.add_argument("--targets", help="Comma list 'Merchant:store_id[,Merchant:store_id...]'.")
    ap.add_argument("--merchant", help="Single-target merchant (with --store-id).")
    ap.add_argument("--store-id", help="Single-target store id.")
    ap.add_argument("--run-id", default=None, help="Sweep run id (holds recap.json).")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--available", default="all", choices=["all", "pending"])
    ap.add_argument("--pace", default=None)
    args = ap.parse_args()

    targets: list[tuple[str, str]] = []
    if args.targets:
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

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    run_id = args.run_id or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-auto"
    sweep_dir = ROOT / "runs" / run_id
    sweep_dir.mkdir(parents=True, exist_ok=True)
    recap = {"run_id": run_id, "started_at": _clock(), "targets": [], "halted": None,
             "total_created": 0}
    recap_path = sweep_dir / "recap.json"

    def persist():
        recap["updated_at"] = _clock()
        # (t.get("recap") or {}) — a target's recap is None until its sweep starts
        # producing pages; `.get("recap", {})` would return that None (key exists)
        # and crash on None.get().
        recap["total_created"] = sum((t.get("recap") or {}).get("total_created", 0)
                                     for t in recap["targets"])
        recap_path.write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")

    persist()
    for merchant, store_id in targets:
        if _STOP:
            recap["halted"] = "operator_stop"
            break
        slug = re.sub(r"[^a-z0-9]+", "-", merchant.lower()).strip("-") or "merchant"
        cfg = SweepConfig(merchant=merchant, store_id=store_id, start_page=args.start_page,
                          max_pages=args.max_pages)
        stages = _make_stages(merchant, store_id, args.available, args.pace)
        target_entry = {"merchant": merchant, "store_id": store_id, "recap": None}
        recap["targets"].append(target_entry)

        def on_page(live_recap, _t=target_entry):
            # Attach the LIVE sweep recap so the console sees per-page progress
            # BEFORE run_sweep returns (the reference is mutated in place).
            _t["recap"] = live_recap
            persist()

        sweep = run_sweep(cfg, stages,
                          page_run_id=lambda p, sl=slug, sid=store_id: f"{run_id}-{sl}-s{sid}-p{p}",
                          should_stop=lambda: _STOP, on_page=on_page)
        target_entry["recap"] = sweep
        persist()
        # A fail-closed halt on one merchant stops the whole batch (a broken
        # session / login bounce affects every subsequent merchant too).
        if sweep.get("halted") and sweep["halted"] != "operator_stop":
            recap["halted"] = f"{merchant}: {sweep['halted']}"
            break
        if _STOP:
            recap["halted"] = "operator_stop"
            break

    recap["finished_at"] = _clock()
    persist()
    print(json.dumps({"run_id": run_id, "total_created": recap["total_created"],
                      "halted": recap["halted"], "targets": len(recap["targets"]),
                      "recap": str(recap_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
