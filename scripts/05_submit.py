#!/usr/bin/env python3
"""Stage 4 — submitter CLI.

Run kinds:
  (default)  DRY-RUN — rehearse the flow, no writes.
  --submit   REAL — fill region/edition + click "Create offer" + verify post-save
             (offer gone from the refreshed feed, same available mode as the
             run).

Data-entry mode (`--mode`, R24) decides how much of the validated batch a run
processes — see DATA_ENTRY_MODES below.

Gates (fail-closed): invariants green + authoritative, `approved.json` present
AND re-verified at load time against its sibling `candidates.json` +
`validation.json` (P1, 2026-07-08 — a fabricated/stale approved.json refuses to
load), pre-flight WP login check. Reads the approved offers (Stage 3), writes
`submit_plan.json` + `submit_report.txt`.

Examples (on the VPS):
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit                    # safe: full approved batch
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit --mode learning    # learning: canary of 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.pacing import Pacer  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.submit_session import SubmitSession, WriteSubmitSession  # noqa: E402
from src.validation import ValidationError, verify_approved_against_source  # noqa: E402
from src.submitter import (  # noqa: E402
    FEED_UNREADABLE_EXCS,
    DryRunSubmitter,
    InspectSubmitter,
    Submitter,
    fetch_session_catalog,
)


# R24 (2026-07-13, Romain) — data-entry modes. Once the normalized report is
# validated we submit; the mode decides the batch size of that submit:
#
#   safe      the frozen matcher behaviour. Validation IS the safety gate, so
#             the FULL approved batch goes in — no canary (R23b).
#   learning  exploring one (category × merchant) unlock. It DOES write —
#             Romain, 2026-07-13: "le learning n'est pas un mode d'observation,
#             il ajoute les offres si le rapport normalisé est valide" — but it
#             stays capped at a canary of 1 for now.
#   advanced  validated unlocks; same canary cap for now.
#
# "Always a canary, for now" is Romain's word ("qui lance tjrs un canary pour le
# moment"), so the cap is enforced, not merely a default: --limit may narrow a
# canary mode, never widen it.
#
# LIMITATION (deliberate, documented): the matcher has no mode profiles yet, so
# the mode is DECLARED on this CLI and cannot be cross-checked against the run.
# When 03_match learns to stamp a mode into candidates.json, this stage MUST
# re-verify it and fail closed on a mismatch — a run matched under an unlock
# must never be able to submit as `safe` and take the full-batch path.
CANARY_MODES = ("learning", "advanced")
CANARY_LIMIT = 1


def mode_limit(mode: str, requested: int | None) -> int | None:
    """Batch size for a data-entry mode. None = full approved batch."""

    if mode not in CANARY_MODES:
        return requested
    if requested is None:
        return CANARY_LIMIT
    return min(requested, CANARY_LIMIT)


def _status(entry, write):
    if not entry.get("ready"):
        return f"SKIP ({entry.get('blocker')})"
    if not write:
        return "READY"
    if entry.get("submitted"):
        return f"CREATED ({entry.get('post_save')})"
    return f"FAILED ({entry.get('post_save')})"


def main() -> int:
    parser = argparse.ArgumentParser(description="AKS submitter.")
    parser.add_argument("approved", help="Path to approved.json (from Stage 3 validation).")
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--submit", action="store_true", help="REAL write (default: dry-run).")
    parser.add_argument(
        "--mode", default="safe", choices=["safe", "learning", "advanced"],
        help="Data-entry mode (R24). 'safe' (DEFAULT) = frozen matcher, submits the FULL "
             "validated batch, no canary. 'learning' / 'advanced' also write, but are capped "
             "at a canary of 1 offer for now — --limit can narrow that cap, never widen it.",
    )
    parser.add_argument("--all", action="store_true", help="With --inspect: full batch (default: canary of 1). No-op with --submit — the batch size comes from --mode.")
    parser.add_argument("--limit", type=int, default=None, help="Max offers to process. With --submit/dry-run it narrows what --mode allows; with --inspect (default: canary of 1).")
    parser.add_argument(
        "--click-mode", default=None, choices=["native", "dispatch", "trusted"],
        help="With --submit: 'trusted' = CDP Input.dispatchMouseEvent at the button's "
             "viewport center (isTrusted:true — Chantier n°1, 2026-07-03; DEFAULT, the "
             "only mode proven to fire Driffle's handler). 'native' = button.click() and "
             "'dispatch' = MouseEvent sequence (S09 derogation) both produce isTrusted:false "
             "and are proven NOT to persist — kept only as documented diagnostics.",
    )
    parser.add_argument(
        "--inspect", action="store_true",
        help="INSPECT mode — open the modal for approved offers and dump a read-only DOM "
             "inspection to modal_inspection.json. No writes, no clicks on Create. "
             "Defaults to a canary of 1 (use --all / --limit N for more).",
    )
    parser.add_argument(
        "--catalog", action="store_true",
        help="CATALOG mode — fetch the full Édition + Région dropdown lists ONCE "
             "(read-only: opens one current offer's modal, no writes). Writes "
             "session_catalog.json next to the approved.json path. Run once per "
             "data-entry session to pick up new regions/editions.",
    )
    parser.add_argument(
        "--pace-pages", default="1-3",
        help="Seconds between feed-scan page loads (index + every post-save verify "
             "re-walk the feed), 'N' or 'MIN-MAX' (bounded-random, burst mitigation). "
             "0 disables. Default: 1-3.",
    )
    parser.add_argument(
        "--pace-offers", default="5-15",
        help="Seconds between successive offers, 'N' or 'MIN-MAX' (bounded-random). "
             "0 disables. Default: 5-15.",
    )
    args = parser.parse_args()

    modes = [m for m in (args.inspect, args.submit, args.catalog) if m]
    if len(modes) > 1:
        print("--inspect, --submit and --catalog are mutually exclusive", file=sys.stderr)
        return 2
    if args.click_mode is not None and not args.submit:
        print("--click-mode is only meaningful with --submit", file=sys.stderr)
        return 2
    # A canary mode is a cap, not a default: refuse a --limit that tries to widen
    # it rather than silently clamping (the operator asked for a batch the mode
    # forbids — say so).
    if (
        not args.inspect
        and args.mode in CANARY_MODES
        and args.limit is not None
        and args.limit > CANARY_LIMIT
    ):
        print(
            f"--mode {args.mode} is capped at a canary of {CANARY_LIMIT} offer "
            f"(--limit {args.limit} would widen it). Use --mode safe for the full batch.",
            file=sys.stderr,
        )
        return 2
    try:
        page_pacer = Pacer.from_spec(args.pace_pages)
        offer_pacer = Pacer.from_spec(args.pace_offers)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    pacer_kw = {"page_pacer": page_pacer, "offer_pacer": offer_pacer}

    # Fail-closed gate: invariants must be green AND authoritative. Retry a couple
    # times — a transient red (e.g. AKS rate-limit right after the matcher's GET
    # burst) should not abort; a persistent one still does.
    report = build_report(endpoint=args.endpoint)
    for _ in range(2):
        if report["ok"] and report["authoritative"]:
            break
        time.sleep(5)
        report = build_report(endpoint=args.endpoint)
    if not (report["ok"] and report["authoritative"]):
        print(json.dumps({
            "aborted": True,
            "reason": "invariants not green/authoritative after retries",
            "ok": report["ok"],
            "authoritative": report["authoritative"],
            "failing_checks": [c for c in report.get("checks", []) if not c["ok"]],
        }, indent=2))
        return 2

    out_dir = Path(args.approved).resolve().parent
    run_id = out_dir.name

    if args.catalog:
        print("CATALOG MODE — fetching full Édition + Région lists once (read-only).", file=sys.stderr)
        try:
            with SubmitSession(args.endpoint) as session:
                catalog = fetch_session_catalog(
                    session, store_id=args.store_id, available=args.available, max_pages=args.max_pages,
                )
        except FEED_UNREADABLE_EXCS as exc:
            print(json.dumps({
                "aborted": True,
                "reason": f"fail-closed abort (feed/CDP unreadable): {exc}",
            }, indent=2))
            return 2
        (out_dir / "session_catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        summary = {"mode": "catalog", "ok": catalog.get("ok"), "out_dir": str(out_dir),
                   "artifact": "session_catalog.json"}
        if catalog.get("ok"):
            ed = catalog.get("editions") or {}
            rg = catalog.get("regions") or {}
            summary["editions_count"] = ed.get("rendered_count")
            summary["regions_count"] = rg.get("rendered_count")
            summary["offer_id"] = catalog.get("offer_id")
        else:
            summary["reason"] = catalog.get("reason")
        print(json.dumps(summary, indent=2))
        return 0 if catalog.get("ok") else 2

    approved = json.loads(Path(args.approved).read_text(encoding="utf-8"))

    # P1 (Romain's audit, 2026-07-08): approved.json alone is never authority.
    # Re-derive the approval from candidates.json + validation.json HERE
    # (run_id, validated_by/at and fingerprints re-checked by load_validation)
    # and require approved.json to match exactly — in every mode that consumes
    # it (dry-run, inspect, submit).
    try:
        candidates_path = out_dir / "candidates.json"
        validation_path = out_dir / "validation.json"
        if not candidates_path.exists() or not validation_path.exists():
            raise ValidationError(
                "candidates.json and validation.json must sit next to approved.json"
            )
        verify_approved_against_source(
            approved,
            json.loads(validation_path.read_text(encoding="utf-8")),
            json.loads(candidates_path.read_text(encoding="utf-8")),
            expected_run_id=run_id,
        )
    except (ValidationError, ValueError) as exc:
        print(json.dumps({
            "aborted": True,
            "reason": f"submit-time validation re-check failed: {exc}",
        }, indent=2))
        return 2

    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))

    if args.inspect:
        limit = args.limit if args.limit is not None else (None if args.all else 1)
        approved_slice = approved if limit is None else approved[:limit]
        print(
            f"INSPECT MODE — will open modal for up to "
            f"{limit if limit is not None else 'ALL'} offer(s) (no writes, no clicks on Create).",
            file=sys.stderr,
        )
        try:
            with SubmitSession(args.endpoint) as session:
                result = InspectSubmitter(session, logger=logger, **pacer_kw).run(
                    run_id=run_id, merchant=args.merchant, store_id=args.store_id,
                    approved=approved_slice, available=args.available, max_pages=args.max_pages,
                )
        except FEED_UNREADABLE_EXCS as exc:
            print(json.dumps({
                "aborted": True,
                "reason": f"fail-closed abort (feed/CDP unreadable): {exc}",
            }, indent=2))
            return 2
        (out_dir / "modal_inspection.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        inspected = sum(1 for p in result["plan"] if p.get("inspection") is not None)
        print(json.dumps({
            "mode": "inspect",
            "aborted": result["aborted"],
            "stopped": result["stopped"],
            "feed_offers": result.get("feed_offers"),
            "inspected": inspected,
            "total": len(result["plan"]),
            "out_dir": str(out_dir),
            "artifact": "modal_inspection.json",
        }, indent=2))
        return 0

    write = args.submit
    # R24: the batch size is the mode's call (safe = full validated batch, R23b;
    # learning/advanced = canary of 1). --all is a no-op here — kept only for
    # --inspect, which retains its own canary-of-1 default above.
    limit = mode_limit(args.mode, args.limit)
    click_mode = args.click_mode if args.click_mode is not None else "trusted"
    if write:
        print(
            f"REAL SUBMISSION (mode={args.mode}) — will create up to "
            f"{limit if limit is not None else 'ALL'} offer(s) (click_mode={click_mode}).",
            file=sys.stderr,
        )

    session_cls = WriteSubmitSession if write else SubmitSession
    submitter_cls = Submitter if write else DryRunSubmitter
    submitter_kw = {"click_mode": click_mode} if write else {}
    # Mid-batch feed/CDP failures are handled INSIDE run() (offer marked
    # UNKNOWN, stopped="feed_unreadable", plan preserved); this wrapper only
    # catches failures outside the batch loop (pre-flight navigate, catalog).
    try:
        with session_cls(args.endpoint) as session:
            result = submitter_cls(session, logger=logger, **pacer_kw, **submitter_kw).run(
                run_id=run_id, merchant=args.merchant, store_id=args.store_id,
                approved=approved, available=args.available, max_pages=args.max_pages, limit=limit,
            )
    except FEED_UNREADABLE_EXCS as exc:
        print(json.dumps({
            "aborted": True,
            "reason": f"fail-closed abort (feed/CDP unreadable): {exc}",
        }, indent=2))
        return 2

    # R24: the mode + the batch size it produced are part of the run's record,
    # so submit_plan.json says under which mode these offers were written.
    result["data_entry_mode"] = args.mode
    result["limit"] = limit
    (out_dir / "submit_plan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    done = [p for p in result["plan"] if (p.get("submitted") if write else p.get("ready"))]
    if write:
        # Audit P2: attempts ≠ creations — both counters explicit in the text
        # header too, not only in the JSON summary.
        counts = (
            f"created={result.get('created')}, "
            f"write_attempts={result.get('write_attempts')}, plan={len(result['plan'])}"
        )
    else:
        counts = f"{len(done)}/{len(result['plan'])} ready"
    batch = "full batch" if limit is None else f"canary {limit}" if limit == CANARY_LIMIT else f"limit {limit}"
    header = (
        f"{'SUBMIT' if write else 'DRY-RUN'} — {args.merchant} — mode={args.mode} ({batch}) — "
        f"{counts}, {result.get('feed_offers')} offers in current feed, "
        f"aborted={result['aborted']}, stopped={result['stopped']}"
    )
    lines = [header, ""]
    for entry in result["plan"]:
        lines.append(f"[{_status(entry, write)}] {entry['offer_id']} — {entry['merchant_title']}")
        for kind in ("region", "edition"):
            res = entry.get(f"{kind}_resolution")
            if isinstance(res, dict):
                flag = " CHANGED" if res.get("changed") else ""
                lines.append(
                    f"    {kind}: id={res.get('id')} ({res.get('text')!r}) "
                    f"via {res.get('source')} matcher_id={res.get('matcher_id')}{flag}"
                )
        if entry.get("ready") and not write:
            lines.append(f"    {entry['would_submit']}")
        if entry.get("ready") and write and not entry.get("submitted"):
            d = entry.get("create") or {}
            lines.append(
                f"    create={d.get('status')} "
                f"region set/target={d.get('region_set')}/{d.get('region_target')} "
                f"edition set/target={d.get('edition_set')}/{d.get('edition_target')} "
                f"signal={d.get('signal')!r}"
            )
            lines.append(f"    region_options={d.get('region_options')} edition_options={d.get('edition_options')}")
            fv = d.get("form_validity")
            if isinstance(fv, dict):
                lines.append(
                    f"    form_valid={fv.get('form_valid')} "
                    f"invalid_required={[x.get('name') for x in fv.get('invalid_required', [])]}"
                )
            ta = d.get("target_add")
            if isinstance(ta, dict):
                rb = ta.get("readback") if isinstance(ta.get("readback"), dict) else {}
                lines.append(
                    f"    target_add={ta.get('status')} commit={ta.get('commit')} "
                    f"value={ta.get('value')!r} readback_count={rb.get('count')}"
                )
            lines.append(
                f"    click_mode={d.get('click_mode')} polls={d.get('polls')} "
                f"pre_existing={d.get('pre_existing')} button={d.get('button')}"
            )
            click = d.get("click") if isinstance(d.get("click"), dict) else None
            if click:
                lines.append(
                    f"    trusted_click: click=({click.get('click_x')},{click.get('click_y')}) "
                    f"delay_ms={click.get('delay_ms')} scrolled={click.get('scrolled')} "
                    f"viewport={click.get('viewport')} rect={click.get('rect')} "
                    f"status={click.get('status')}"
                )
            for req in d.get("requests") or []:
                lines.append(f"    net: {req.get('via')} {req.get('method')} {req.get('url')} -> {req.get('status')}")
    (out_dir / "submit_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "mode": "submit" if write else "dry_run",
        # R24 — `mode` above is the run KIND (dry_run/submit/inspect/catalog);
        # this is the data-entry mode that set the batch size.
        "data_entry_mode": args.mode,
        "limit": limit,
        "aborted": result["aborted"],
        "stopped": result["stopped"],
        "feed_offers": result.get("feed_offers"),
        "created" if write else "ready": len(done),
        "total": len(result["plan"]),
        "out_dir": str(out_dir),
    }
    if write:
        # P2 (audit 2026-07-08): attempts ≠ creations; surface both.
        summary["write_attempts"] = result.get("write_attempts")
    if result.get("catalog"):
        summary["catalog"] = result["catalog"]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
