#!/usr/bin/env python3
"""Reachability probe of allkeyshop.com — the ONLY way to "ping" AKS from a shell.

Romain 2026-09-11: every probe towards AKS must carry the ``AKS/Staff`` User-Agent,
otherwise the anti-bot bans the VPS IP (a network-level drop that no header can undo).
``http_get`` already defaults to the staff UA for allkeyshop.com hosts; this script exists
so nobody reaches for ``curl`` with the browser UA. One request per call, no retries —
pace calls yourself (a probe every 15 min is plenty while banned).

    python3 scripts/13_aks_ping.py            # the blog root
    python3 scripts/13_aks_ping.py --url https://www.allkeyshop.com/blog/buy-x-cd-key-compare-prices/
    python3 scripts/13_aks_ping.py --wait 900 --max 16    # one probe every 15 min until AKS answers

Exit code 0 when AKS answered 2xx/3xx, 1 otherwise. Output is one JSON line per probe.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.aks_env import AKS_DIRECT_URL, AKS_STAFF_UA, _allkeyshop_host, http_get  # noqa: E402


def probe(url: str, timeout: int) -> dict:
    t0 = time.monotonic()
    r = http_get(url, timeout=timeout, follow_redirects=False, user_agent=AKS_STAFF_UA)
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "url": url,
        "status": r.status, "ok": bool(r.status and 200 <= r.status < 400),
        "seconds": round(time.monotonic() - t0, 2), "error": (str(r.error)[:160] if r.error else None),
        "user_agent": AKS_STAFF_UA,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe allkeyshop.com with the AKS/Staff User-Agent (read-only).")
    ap.add_argument("--url", default=AKS_DIRECT_URL)
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--wait", type=int, default=0, help="seconds between probes (0 = single probe)")
    ap.add_argument("--max", type=int, default=1, help="maximum number of probes when --wait is set")
    args = ap.parse_args()
    if not _allkeyshop_host(args.url):
        print(json.dumps({"error": "refusing a non-allkeyshop.com URL (the staff UA is host-locked)"}))
        return 2
    for i in range(max(1, args.max)):
        res = probe(args.url, args.timeout)
        print(json.dumps(res), flush=True)
        if res["ok"] or not args.wait or i + 1 >= args.max:
            return 0 if res["ok"] else 1
        time.sleep(args.wait)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
