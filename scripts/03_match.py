#!/usr/bin/env python3
"""Match a normalized feed to AKS product pages (read-only). Sprint 3.

Reads an ``offers.json`` (a NormalizedFeed), resolves candidates against AKS with
read-only GETs, and writes ``candidates.json`` + ``skipped.json`` + a
normalized-text ``report.txt`` (no tables). It never submits.

Example (on the VPS):
    python3 scripts/03_match.py runs/<run_id>/offers.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import AKS_DIRECT_URL, http_get, validate_aks_direct_status  # noqa: E402
from src.contracts import NormalizedFeed, NormalizedOffer  # noqa: E402
from src.matcher import match_feed, resolve_aks  # noqa: E402


def load_feed(path: str) -> NormalizedFeed:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    offers = tuple(
        NormalizedOffer(
            offer_id=o["offer_id"],
            name=o["name"],
            url=o["url"],
            merchant=o["merchant"],
            store_id=o.get("store_id"),
            price=o.get("price"),
            stock=o.get("stock"),
        )
        for o in data.get("offers", [])
    )
    return NormalizedFeed(
        run_id=data.get("run_id", "unknown"),
        merchant=data.get("merchant", "unknown"),
        fetched_at=data.get("fetched_at", ""),
        offers=offers,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Match a normalized feed to AKS (read-only).")
    parser.add_argument("offers", help="Path to offers.json (a NormalizedFeed).")
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    # Fail-closed: never mass-skip because AKS itself is unreachable.
    probe = http_get(AKS_DIRECT_URL, follow_redirects=False)
    if not validate_aks_direct_status(probe.status).ok:
        print(json.dumps({"aborted": True, "reason": "AKS not reachable", "status": probe.status}, indent=2))
        return 2

    feed = load_feed(args.offers)
    candidates, skipped = match_feed(feed, resolve_aks, max_candidates=args.max_candidates)

    out_dir = Path(args.out_dir) if args.out_dir else Path(args.offers).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(
        json.dumps([c.to_dict() for c in candidates], indent=2), encoding="utf-8"
    )
    (out_dir / "skipped.json").write_text(
        json.dumps([s.to_dict() for s in skipped], indent=2), encoding="utf-8"
    )

    lines = [
        f"AKS candidates — {feed.merchant} — "
        f"{len(candidates)} candidate(s), {len(skipped)} skipped",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(candidate.normalized_block(index))
        lines.append("")
    reasons = Counter(s.reason.split(":")[0].split(",")[0] for s in skipped)
    lines.append("Skipped summary:")
    for reason, count in reasons.most_common():
        lines.append(f"  {count:4d}  {reason}")
    (out_dir / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "merchant": feed.merchant,
                "offers": len(feed.offers),
                "candidates": len(candidates),
                "skipped": len(skipped),
                "out_dir": str(out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
