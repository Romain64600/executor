#!/usr/bin/env python3
"""Admin page server — human validation + supervised submit trigger.

Serves the operator page (list runs, read the normalized report, approve/reject
candidates with optional region/edition overrides, launch a supervised
dry-run/submit/catalog). Binds to loopback only by default — nginx terminates
HTTPS and enforces basic auth in front (see ops/INSTALL_ADMIN.md).

Fail-closed: refuses a non-loopback bind without --allow-external, reconciles
orphaned submit state files at startup before accepting any request.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.admin.app import AppState, make_server  # noqa: E402


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="AKS executor admin page (validation + submit).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8650)
    parser.add_argument("--root", default=str(ROOT), help="Repo root (test seam).")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Allow a non-loopback bind. NOT recommended: auth lives in nginx, "
        "the app itself is unauthenticated.",
    )
    args = parser.parse_args()

    if not _is_loopback(args.host) and not args.allow_external:
        print(
            f"refus: bind non-loopback {args.host!r} sans --allow-external "
            "(l'app n'a pas d'auth propre — nginx est le frontal)",
            file=sys.stderr,
        )
        return 2

    state = AppState(Path(args.root).resolve())
    orphans = state.manager.recover_orphans(state.runs_dir)
    print(
        json.dumps(
            {
                "listening": f"http://{args.host}:{args.port}/",
                "repo_root": str(state.repo_root),
                "recovered_orphans": orphans,
            }
        ),
        file=sys.stderr,
    )
    server = make_server(state, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
