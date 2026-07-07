#!/usr/bin/env python3
"""Stage 4 — submitter CLI.

Modes:
  (default)  DRY-RUN — rehearse the flow, no writes.
  --submit   REAL — fill region/edition + click "Create offer" + verify post-save
             (offer gone from pending). Defaults to a **canary of 1 offer**; pass
             --all for the full batch, or --limit N.

Gates (fail-closed): invariants green + authoritative, `approved.json` present,
pre-flight WP login check. Reads the approved offers (Stage 3), writes
`submit_plan.json` + `submit_report.txt`.

Examples (on the VPS):
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit          # canary (1)
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit --all     # full batch
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
from src.run_log import RunLogger  # noqa: E402
from src.submit_session import SubmitSession, WriteSubmitSession  # noqa: E402
from src.submitter import (  # noqa: E402
    DryRunSubmitter,
    InspectSubmitter,
    Submitter,
    fetch_session_catalog,
)


def _status(entry, write):
    if not entry.get("ready"):
        return f"SKIP ({entry.get('blocker')})"
    if not write:
        return "READY"
    return "CREATED (gone from pending)" if entry.get("submitted") else f"FAILED ({entry.get('post_save')})"


def main() -> int:
    parser = argparse.ArgumentParser(description="AKS submitter.")
    parser.add_argument("approved", help="Path to approved.json (from Stage 3 validation).")
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--submit", action="store_true", help="REAL write (default: dry-run).")
    parser.add_argument("--all", action="store_true", help="With --submit / --inspect: full batch (default: canary of 1).")
    parser.add_argument("--limit", type=int, default=None, help="With --submit / --inspect: max offers to process.")
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
    args = parser.parse_args()

    modes = [m for m in (args.inspect, args.submit, args.catalog) if m]
    if len(modes) > 1:
        print("--inspect, --submit and --catalog are mutually exclusive", file=sys.stderr)
        return 2
    if args.click_mode is not None and not args.submit:
        print("--click-mode is only meaningful with --submit", file=sys.stderr)
        return 2

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
        with SubmitSession(args.endpoint) as session:
            catalog = fetch_session_catalog(
                session, store_id=args.store_id, available=args.available, max_pages=args.max_pages,
            )
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
    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))

    if args.inspect:
        limit = args.limit if args.limit is not None else (None if args.all else 1)
        approved_slice = approved if limit is None else approved[:limit]
        print(
            f"INSPECT MODE — will open modal for up to "
            f"{limit if limit is not None else 'ALL'} offer(s) (no writes, no clicks on Create).",
            file=sys.stderr,
        )
        with SubmitSession(args.endpoint) as session:
            result = InspectSubmitter(session, logger=logger).run(
                run_id=run_id, merchant=args.merchant, store_id=args.store_id,
                approved=approved_slice, available=args.available, max_pages=args.max_pages,
            )
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
    limit = args.limit if args.limit is not None else (None if args.all else 1)
    click_mode = args.click_mode if args.click_mode is not None else "trusted"
    if write:
        print(
            f"REAL SUBMISSION — will create up to {limit if limit is not None else 'ALL'} offer(s)"
            f" (click_mode={click_mode}).",
            file=sys.stderr,
        )

    session_cls = WriteSubmitSession if write else SubmitSession
    submitter_cls = Submitter if write else DryRunSubmitter
    submitter_kw = {"click_mode": click_mode} if write else {}
    with session_cls(args.endpoint) as session:
        result = submitter_cls(session, logger=logger, **submitter_kw).run(
            run_id=run_id, merchant=args.merchant, store_id=args.store_id,
            approved=approved, available=args.available, max_pages=args.max_pages, limit=limit,
        )

    (out_dir / "submit_plan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    done = [p for p in result["plan"] if (p.get("submitted") if write else p.get("ready"))]
    header = (
        f"{'SUBMIT' if write else 'DRY-RUN'} — {args.merchant} — "
        f"{len(done)}/{len(result['plan'])} {'created' if write else 'ready'}, "
        f"{result.get('feed_offers')} offers in current feed, "
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
        "aborted": result["aborted"],
        "stopped": result["stopped"],
        "feed_offers": result.get("feed_offers"),
        "created" if write else "ready": len(done),
        "total": len(result["plan"]),
        "out_dir": str(out_dir),
    }
    if result.get("catalog"):
        summary["catalog"] = result["catalog"]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
