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

[R45] The requested console mode (``--consoles`` / ``--no-consoles``) must agree with
the preview it submits (``consoles_mode_refusal``: the recap's ``consoles`` stamp, and
under ``--no-consoles`` no console / multi-target candidate) — else exit 2 before
anything is prepared (audit 2026-09-15).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _write_json_atomic(path, payload) -> None:
    """Écriture ATOMIQUE d'un contrat de run (audit du 2026-09-18).

    `recap.json` est relu EN DIRECT par la console pendant que le run tourne. Un
    `write_text` nu tronque puis réécrit en place : une lecture tombant dans la fenêtre voit
    un JSON coupé. Le dépôt a déjà cette convention (`validation_io`, `run_marker`) — tmp
    dans le MÊME dossier, donc même système de fichiers, puis `os.replace`."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)



from src.admin.runs import sha256_file  # noqa: E402
from src.admin.validation_io import apply_overrides_and_validate  # noqa: E402
from src.child_runner import CooperativeChildRunner  # noqa: E402
from src.console_keys import CONSOLE_FAMILIES  # noqa: E402
from src.data_entry_auto import SubmitOutcome, run_by_urls_submit  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.validation import candidate_fingerprint  # noqa: E402

# [R45] the platforms a target may carry ONLY when the run was matched with the console
# branch (XBOX_ONE / XBOX_SERIES / XBOX_PC / PS4 / PS5 / SWITCH / SWITCH2 — the shared
# vocabulary of src/console_keys.py, never a local copy).
CONSOLE_PLATFORMS = frozenset(CONSOLE_FAMILIES)

# Cooperative SIGTERM: forward to the current 05_submit child (it stops at an offer
# boundary — never mid-Create), then the batch halts between merchants; a child that
# hangs past the grace is SIGKILLed by its group so it is never orphaned (see
# src/child_runner.py, adversarial review 2026-08-25).
_RUNNER = CooperativeChildRunner()


def _run_child(argv: list[str]) -> int:
    return _RUNNER.run(argv, str(ROOT))


def _read_submit_plan(run_dir: Path, rc: int) -> SubmitOutcome:
    """Deterministic result: per-offer success is 05_submit's own ``submitted``
    boolean (itself set only from the prove-gone check), never re-derived here from a
    post_save substring (EXECUTOR_RULES)."""
    # [14] Fable re-audit 2026-09-06: an UNREADABLE/missing submit_plan.json after
    # exit 0 must NOT read as a clean merchant (mirror Safe-Auto's P2-14). Track
    # readability and fold it into ok, so clean() halts the batch fail-closed instead
    # of crediting a merchant whose plan we could not even read.
    plan: dict | None
    try:
        plan = json.loads((run_dir / "submit_plan.json").read_text(encoding="utf-8"))
    except Exception:
        plan = None
    plan_readable = isinstance(plan, dict)
    plan = plan or {}
    offers, created = [], 0
    for e in plan.get("plan", []):
        ps = str(e.get("post_save") or "")
        # [13] Fable re-audit 2026-09-06: trust 05_submit's deterministic ``submitted``
        # boolean, not a "gone" SUBSTRING of the human post_save text (which can read
        # "…not gone…" or omit the word) — post_save stays for display only.
        ok = bool(e.get("submitted"))
        if ok:
            created += 1
        offers.append({"name": e.get("merchant_title"), "aks_id": e.get("aks_product_id"),
                       "region_id": e.get("region_id"), "edition_id": e.get("edition_id"),
                       "created": ok, "post_save": ps})
    return SubmitOutcome(ok=(rc == 0 and plan_readable), aborted=plan.get("aborted"),
                         stopped=plan.get("stopped"), created=created, offers=offers,
                         detail="" if (rc == 0 and plan_readable)
                         else (f"exit {rc}" if rc != 0 else "submit_plan.json unreadable after exit 0"))


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
        # UNMODIFIED 05_submit --mode safe, --locate-by-search (below). No --page-hint
        # (by-urls offers are scattered — no feed page). No --limit (safe = full batch, R24).
        argv = [py, str(ROOT / "scripts" / "05_submit.py"), str(sub_run / "approved.json"),
                "--merchant", merchant, "--store-id", store_id,
                "--mode", "safe", "--submit", "--available", available,
                # by-urls offers are scattered (found by search, no feed page) — locate
                # + prove-gone via the SEARCH (fast + fresh; a slow whole-feed scan let
                # the row reflow away, 0 created, 2026-08-25).
                "--locate-by-search"]
        rc = _run_child(argv)
        outcome = _read_submit_plan(sub_run, rc)
        logger.log("merchant_submitted", merchant=merchant, created=outcome.created,
                   attempted=len(candidates), halted=outcome.halt_reason())
        return outcome

    return submit_merchant


def _mode_word(consoles: bool) -> str:
    return "--consoles" if consoles else "--no-consoles"


def consoles_mode_refusal(from_recap: dict, consoles: bool) -> tuple[str, list[dict]] | None:
    """[R45] Audit 2026-09-15 (finding 2): the submit must run in the SAME console mode
    the preview was matched with — checked HERE too, not only by the admin manager's
    ``consoles_mismatch`` guard, because the direct CLI launch has no manager in front
    of it. Fail-closed, BEFORE any validation triple is prepared. Returns
    ``(reason, offenders)`` when the batch must be refused, else ``None``.

    1. The preview recap's ``consoles`` stamp (a bool written by scripts/11; absent on
       older previews) must agree with the requested mode — either direction refuses.
    2. Under ``--no-consoles`` (defence in depth for un-stamped previews): refuse any
       candidate whose targets (or primary ``platform``) carry a console platform, or
       that carries more than one target — a PC-only batch never writes a console page
       and never a multi-target candidate.
    """
    stamped = from_recap.get("consoles")
    if isinstance(stamped, bool) and stamped != bool(consoles):
        return (f"consoles_mismatch: mode consoles de l'aperçu ({str(stamped).lower()} = "
                f"{_mode_word(stamped)}) ≠ mode demandé ({str(bool(consoles)).lower()} = "
                f"{_mode_word(bool(consoles))}) — relancer l'aperçu ou le submit avec le "
                "même mode", [])
    if consoles:
        return None
    offenders: list[dict] = []
    for game in from_recap.get("games") or []:
        for per in game.get("merchants") or []:
            for c in per.get("candidates") or []:
                if not isinstance(c, dict):
                    continue
                targets = [t for t in (c.get("targets") or []) if isinstance(t, dict)]
                plats = {str(t.get("platform") or "") for t in targets}
                if c.get("platform"):
                    plats.add(str(c["platform"]))
                hit = sorted(p for p in plats if p in CONSOLE_PLATFORMS)
                if hit or len(targets) > 1:
                    offer = c.get("offer") or {}
                    offenders.append({"merchant": per.get("merchant"), "store_id": per.get("store_id"),
                                      "offer_id": offer.get("offer_id"), "name": offer.get("name"),
                                      "platforms": hit, "targets": len(targets)})
    if not offenders:
        return None
    shown = "; ".join(
        f"[{o['merchant']}] {o['name'] or o['offer_id']} ({', '.join(o['platforms']) or 'PC'}"
        f", {o['targets']} cible(s))" for o in offenders[:5])
    more = f" …(+{len(offenders) - 5})" if len(offenders) > 5 else ""
    return (f"consoles_mismatch: --no-consoles demandé mais l'aperçu porte {len(offenders)} "
            f"candidat(s) console / multi-cibles : {shown}{more} — relancer l'aperçu ou le "
            "submit avec le même mode", offenders)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Submit a by-urls dry-run's candidates (safe).")
    ap.add_argument("--from-run", required=True, help="The *-by-urls run whose recap to submit.")
    ap.add_argument("--from-recap-file", default=None,
                    help="Immutable snapshot of the validated preview recap (the manager's "
                         "AS1 sha-bound copy). When set, read the preview from THIS file — never "
                         "the mutable source recap — closing the sha-check→read TOCTOU (P1, "
                         "2026-08-25). Absent: fall back to runs/<from-run>/recap.json (standalone).")
    ap.add_argument("--run-id", required=True, help="This submit run id (holds recap.json).")
    ap.add_argument("--available", default="all", choices=["all", "pending"])
    ap.add_argument("--mode", default="safe", choices=["safe"])  # R24: ADD path is safe only
    # [R45] Romain 2026-09-15: the admin launcher passes the SAME --consoles / --no-consoles
    # it gave the preview (scripts/11). It is passed to NOTHING downstream: the preview's
    # candidates carry their ``targets`` (one per platform page) and 05_submit reads them
    # from approved.json; a multi-target candidate travels WHOLE (grouped by store, never
    # split per target). Audit 2026-09-15 (finding 2): the flag is CHECKED against the
    # preview (``consoles_mode_refusal``) — a mismatch refuses the batch before anything
    # is prepared (exit 2), it is no longer informational.
    ap.add_argument("--consoles", dest="consoles", action="store_true", default=True,
                    help="The preview was matched WITH the console branch (DEFAULT). Must "
                         "agree with the preview's `consoles` stamp — else exit 2.")
    ap.add_argument("--no-consoles", dest="consoles", action="store_false",
                    help="The preview was a PC-only run. Must agree with the preview's "
                         "`consoles` stamp; any console / multi-target candidate refuses "
                         "the batch (exit 2).")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    _RUNNER.install()

    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(args.run_id, log_dir=ROOT / "logs")

    # P1 (2026-08-25): prefer the manager's immutable sha-bound snapshot; the mutable
    # source recap is only the standalone fallback (never reached from the console).
    src_recap_path = (Path(args.from_recap_file) if args.from_recap_file
                      else ROOT / "runs" / args.from_run / "recap.json")
    try:
        from_recap = json.loads(src_recap_path.read_text(encoding="utf-8"))
    except Exception as exc:
        recap = {"mode": "submit", "aborted": f"source_recap_unreadable: {exc}"[:160],
                 "merchants": [], "totals": {"merchants": 0, "attempted": 0, "created": 0}}
        _write_json_atomic(run_dir / "recap.json", recap)
        print(json.dumps({"run_id": args.run_id, "aborted": recap["aborted"]}))
        return 2

    available = from_recap.get("available") or args.available

    def flush(recap: dict) -> None:
        _write_json_atomic(run_dir / "recap.json", recap)

    def make_sub_run(store_id: str) -> Path:
        return ROOT / "runs" / f"{args.run_id}-s{store_id}"

    logger.log("submit_run_start", from_run=args.from_run, available=available,
               consoles=bool(args.consoles),
               preview_consoles=from_recap.get("consoles"))   # [R45] what the preview ran with

    # [R45] Audit 2026-09-15 (finding 2): the requested console mode must agree with the
    # preview — refused fail-closed BEFORE any validation triple / sub-run exists, logged
    # in the run JSONL like the other refusals (submit_run_aborted), recap.json aborted.
    refusal = consoles_mode_refusal(from_recap, bool(args.consoles))
    if refusal is not None:
        reason, offenders = refusal
        logger.log("submit_run_aborted", reason=reason, consoles=bool(args.consoles),
                   preview_consoles=from_recap.get("consoles"), offenders=offenders)
        recap = {"mode": "submit", "available": available, "aborted": reason[:400],
                 "merchants": [], "totals": {"merchants": 0, "attempted": 0, "created": 0}}
        flush(recap)
        print(json.dumps({"run_id": args.run_id, "mode": "submit", "consoles": bool(args.consoles),
                          "preview_consoles": from_recap.get("consoles"),
                          "aborted": recap["aborted"]}, ensure_ascii=False))
        return 2

    recap = run_by_urls_submit(
        from_recap, available=available,
        submit_merchant=_make_submit_merchant(available, logger),
        make_sub_run=make_sub_run, flush=flush,
        should_stop=lambda: _RUNNER.stopped)
    if recap.get("aborted"):
        logger.log("submit_run_aborted", reason=recap["aborted"])
    else:
        logger.log("submit_run_done", created=recap["totals"]["created"],
                   merchants=recap["totals"]["merchants"])

    print(json.dumps({"run_id": args.run_id, "mode": "submit", "consoles": bool(args.consoles),
                      "created": recap["totals"]["created"],
                      "attempted": recap["totals"]["attempted"],
                      "merchants": recap["totals"]["merchants"],
                      "aborted": recap.get("aborted")}))
    return 0 if not recap.get("aborted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
