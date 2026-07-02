#!/usr/bin/env python3
"""Stage 3 — Validation CLI (read-only). Sprint 3.

Two subcommands:

  template <candidates.json> [--run-id ID]
      Write ``validation.template.json`` next to the candidates. Fill approve:true,
      validated_by and validated_at, then run `check`.

  check <candidates.json> <validation.json> [--run-id ID]
      Verify the filled validation against the current candidates and write
      ``approved.json`` (the exact offers cleared for submission). Fail-closed.

``run_id`` defaults to the candidates' parent directory name. No file is submitted
here — this only produces the approval that a future submitter would require.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.validation import ValidationError, load_validation, validation_template  # noqa: E402


def _run_id(candidates_path: str, override: str | None) -> str:
    return override or Path(candidates_path).resolve().parent.name


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_template(args: argparse.Namespace) -> int:
    candidates = _load_json(args.candidates)
    template = validation_template(candidates, run_id=_run_id(args.candidates, args.run_id))
    out = Path(args.candidates).resolve().parent / "validation.template.json"
    out.write_text(json.dumps(template, indent=2), encoding="utf-8")
    print(json.dumps({"template": str(out), "candidates": len(template["candidates"])}, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    candidates = _load_json(args.candidates)
    validation = _load_json(args.validation)
    try:
        approved = load_validation(
            validation, candidates, expected_run_id=_run_id(args.candidates, args.run_id)
        )
    except ValidationError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2

    out = Path(args.candidates).resolve().parent / "approved.json"
    out.write_text(json.dumps(approved, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": True,
                "approved": len(approved),
                "validated_by": validation.get("validated_by"),
                "out": str(out),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AKS candidate validation (read-only).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_tpl = sub.add_parser("template", help="Generate a validation template.")
    p_tpl.add_argument("candidates")
    p_tpl.add_argument("--run-id", default=None)
    p_tpl.set_defaults(func=cmd_template)

    p_chk = sub.add_parser("check", help="Verify a filled validation file.")
    p_chk.add_argument("candidates")
    p_chk.add_argument("validation")
    p_chk.add_argument("--run-id", default=None)
    p_chk.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
