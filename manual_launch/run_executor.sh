#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'USAGE'
Manual launcher for AKS Controlled Executor.

Usage:
  manual_launch/run_executor.sh prepare --merchant NAME --store-id ID [--pages N|A-B] [--pace MIN-MAX]
  manual_launch/run_executor.sh check RUN_DIR
  manual_launch/run_executor.sh dry-run RUN_DIR --merchant NAME --store-id ID [--mode M] [--limit N]
  manual_launch/run_executor.sh submit RUN_DIR --merchant NAME --store-id ID [--mode M] [--limit N]

Flow:
  1. prepare  Runs audit, invariants, extraction, matcher, validation template.
              Stops before approval. No AKS writes.
  2. Edit RUN_DIR/validation.template.json manually.
  3. check    Verifies the validation file and writes RUN_DIR/approved.json.
  4. dry-run  Rehearses the submitter. No AKS writes.
  5. submit   Real write. Requires approved.json and explicit command.

Data-entry mode (--mode, default: safe) — decides the batch size of a submit:
  safe      Frozen matcher. Submits the FULL validated batch (no canary): the
            validated report IS the safety gate.
  learning  Exploring one (category x merchant) unlock. It DOES write, but is
            capped at a canary of 1 offer for now.
  advanced  Validated unlocks. Same canary cap for now.
  --limit N can narrow a canary mode, never widen it.

Examples:
  manual_launch/run_executor.sh prepare --merchant Driffle --store-id 127
  manual_launch/run_executor.sh check runs/2026-07-13_101500_driffle
  manual_launch/run_executor.sh dry-run runs/2026-07-13_101500_driffle --merchant Driffle --store-id 127
  manual_launch/run_executor.sh submit runs/2026-07-13_101500_driffle --merchant Driffle --store-id 127
  manual_launch/run_executor.sh submit runs/2026-07-13_101500_driffle --merchant Driffle --store-id 127 --mode learning
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 2
}

need_value() {
  local name="${1:-}"
  local value="${2:-}"
  [[ -n "$value" ]] || die "$name requires a value"
}

require_file() {
  [[ -f "$1" ]] || die "missing file: $1"
}

require_dir() {
  [[ -d "$1" ]] || die "missing directory: $1"
}

run_prepare() {
  local merchant=""
  local store_id=""
  local pages=""
  local pace="2-5"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --merchant)
        need_value "$1" "${2:-}"
        merchant="$2"
        shift 2
        ;;
      --store-id)
        need_value "$1" "${2:-}"
        store_id="$2"
        shift 2
        ;;
      --pages)
        need_value "$1" "${2:-}"
        pages="$2"
        shift 2
        ;;
      --pace)
        need_value "$1" "${2:-}"
        pace="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown prepare argument: $1"
        ;;
    esac
  done

  [[ -n "$merchant" ]] || die "--merchant is required"
  [[ -n "$store_id" ]] || die "--store-id is required"

  local slug
  slug="$(printf '%s' "$merchant" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//')"
  local run_id
  run_id="$(date -u '+%Y-%m-%d_%H%M%S')_${slug}"
  local run_dir="$ROOT/runs/$run_id"

  mkdir -p "$run_dir"

  echo "== Audit environment =="
  "$ROOT/scripts/00_audit_env.sh"

  echo "== Check invariants =="
  python3 "$ROOT/scripts/01_check_invariants.py"

  echo "== Extract feed =="
  local extract_args=(
    "$ROOT/scripts/02_extract_feed.py"
    --merchant "$merchant"
    --store-id "$store_id"
    --run-id "$run_id"
    --out-dir "$run_dir"
    --pace "$pace"
  )
  if [[ -n "$pages" ]]; then
    extract_args+=(--pages "$pages")
  fi
  python3 "${extract_args[@]}"

  echo "== Match candidates =="
  python3 "$ROOT/scripts/03_match.py" "$run_dir/offers.json"

  echo "== Generate validation template =="
  python3 "$ROOT/scripts/04_validate.py" template "$run_dir/candidates.json"

  cat <<EOF

Prepared run:
  $run_dir

Next manual step:
  Edit:
    $run_dir/validation.template.json

Then run:
  manual_launch/run_executor.sh check "$run_dir"

No submit was performed.
EOF
}

run_check() {
  [[ $# -eq 1 ]] || die "check expects RUN_DIR"
  local run_dir="$1"
  require_dir "$run_dir"
  require_file "$run_dir/candidates.json"
  require_file "$run_dir/validation.template.json"

  python3 "$ROOT/scripts/04_validate.py" check \
    "$run_dir/candidates.json" \
    "$run_dir/validation.template.json"

  cp "$run_dir/validation.template.json" "$run_dir/validation.json"
  echo "Saved canonical validation file: $run_dir/validation.json"
}

parse_submit_args() {
  merchant=""
  store_id=""
  mode=""
  limit=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --merchant)
        need_value "$1" "${2:-}"
        merchant="$2"
        shift 2
        ;;
      --store-id)
        need_value "$1" "${2:-}"
        store_id="$2"
        shift 2
        ;;
      --mode)
        need_value "$1" "${2:-}"
        case "$2" in
          safe|learning|advanced) mode="$2" ;;
          *) die "--mode must be safe, learning or advanced (got: $2)" ;;
        esac
        shift 2
        ;;
      --limit)
        need_value "$1" "${2:-}"
        limit="$2"
        shift 2
        ;;
      --all)
        # No-op since R23b: in safe mode the full validated batch is already the
        # default. Kept so an old command line still runs instead of dying.
        echo "WARNING: --all is a no-op since R23b — the batch size comes from --mode." >&2
        shift
        ;;
      *)
        die "unknown submit argument: $1"
        ;;
    esac
  done

  [[ -n "$merchant" ]] || die "--merchant is required"
  [[ -n "$store_id" ]] || die "--store-id is required"
}

# Fills the global `submit_extra` array from the parsed --mode / --limit.
build_submit_extra() {
  submit_extra=()
  [[ -n "$mode" ]] && submit_extra+=(--mode "$mode")
  [[ -n "$limit" ]] && submit_extra+=(--limit "$limit")
  return 0
}

run_dry_run() {
  [[ $# -ge 1 ]] || die "dry-run expects RUN_DIR"
  local run_dir="$1"
  shift
  require_dir "$run_dir"
  require_file "$run_dir/approved.json"
  parse_submit_args "$@"
  build_submit_extra

  python3 "$ROOT/scripts/05_submit.py" "$run_dir/approved.json" \
    --merchant "$merchant" \
    --store-id "$store_id" \
    "${submit_extra[@]+"${submit_extra[@]}"}"
}

run_submit() {
  [[ $# -ge 1 ]] || die "submit expects RUN_DIR"
  local run_dir="$1"
  shift
  require_dir "$run_dir"
  require_file "$run_dir/approved.json"
  parse_submit_args "$@"
  build_submit_extra

  local args=(
    "$ROOT/scripts/05_submit.py"
    "$run_dir/approved.json"
    --merchant "$merchant"
    --store-id "$store_id"
    --submit
  )
  args+=("${submit_extra[@]+"${submit_extra[@]}"}")
  python3 "${args[@]}"
}

main() {
  [[ $# -gt 0 ]] || {
    usage
    exit 2
  }

  local command="$1"
  shift

  case "$command" in
    prepare) run_prepare "$@" ;;
    check) run_check "$@" ;;
    dry-run) run_dry_run "$@" ;;
    submit) run_submit "$@" ;;
    -h|--help) usage ;;
    *) die "unknown command: $command" ;;
  esac
}

main "$@"
