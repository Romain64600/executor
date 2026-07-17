#!/usr/bin/env bash
# AKS Controlled Executor — environment audit (read-only).
#
# This script only *reads* state: it performs no browser action and mutates
# nothing. `set -e` is intentionally NOT used — an audit must run every probe to
# completion even when individual checks fail. Each check is tagged PASS / FAIL /
# N/A / INFO, and a summary plus a RESULT line are emitted at the end.
#
# Debian-VPS-only checks are reported N/A unless we are on the real target.
# The target is detected by the ROOT-installed marker /etc/aks-executor.target
# whose content must equal this hostname (FC2, audit 2026-07-17 — the old
# AKS_TARGET=vps env force and the user-writable ~/.hermes marker are gone:
# one env var must never unlock write stages), NOT by /etc/debian_version
# (Debian-derived sandboxes carry that too).
set -uo pipefail

OUT_DIR="${1:-runs/audit_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT_DIR"
REPORT="$OUT_DIR/audit.md"

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
TARGET_MARKER="/etc/aks-executor.target"

# FC2: authoritative iff the root marker exists AND names THIS host.
if [ "$(uname -s)" = "Linux" ] && [ -f "$TARGET_MARKER" ] \
    && [ "$(cat "$TARGET_MARKER" 2>/dev/null)" = "$(hostname)" ]; then
  IS_TARGET=1
else
  IS_TARGET=0
fi

PASS=0
FAIL=0
NA=0

status_line() {
  local st="$1"; shift
  local label="$1"; shift
  local disp="$st"
  case "$st" in
    PASS) PASS=$((PASS + 1)) ;;
    FAIL) FAIL=$((FAIL + 1)) ;;
    NA) NA=$((NA + 1)); disp="N/A" ;;
    INFO) ;;
  esac
  if [ "$#" -gt 0 ]; then
    echo "- [$disp] $label — $*"
  else
    echo "- [$disp] $label"
  fi
}

{
  echo "# AKS Controlled Executor — environment audit"
  echo
  echo "- Date UTC: $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "- Host: $(hostname)"
  echo "- User: $(whoami)"
  echo "- Platform: $(uname -srm)"
  if [ "$IS_TARGET" = "1" ]; then
    echo "- Target: Debian VPS — Debian-specific checks are AUTHORITATIVE"
  else
    echo "- Target: NOT the Debian VPS — Debian-specific checks are reported N/A"
    echo "  (write stages unlock only on the VPS: root marker /etc/aks-executor.target)"
  fi
  echo
  echo "## Checks"
  echo

  # --- Universal: AKS direct must work without VPN ---
  # GET, no redirect-follow (curl default), accept only 200/301/302 — identical
  # to the Python invariant checker so the two gates cannot diverge.
  aks_code="$(curl -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 10 \
    https://www.allkeyshop.com/blog/ 2>/dev/null)"
  aks_code="${aks_code:-000}"
  case "$aks_code" in
    200|301|302) status_line PASS "AKS direct reachable without VPN" "HTTP $aks_code" ;;
    *)           status_line FAIL "AKS direct reachable without VPN" "HTTP $aks_code" ;;
  esac

  # --- Universal: OpenVPN must be stopped ---
  if pgrep -x openvpn >/dev/null 2>&1; then
    status_line FAIL "No OpenVPN process running" "openvpn is running — stop it (VPN forbidden while AKS direct works)"
  else
    status_line PASS "No OpenVPN process running"
  fi

  # --- Universal: no stale AKS scripts ---
  stale="$(ps aux 2>/dev/null | grep -Ei 'cdp_submit|cdp_scan|cdp_login|otp_now|aks_h|aks_fix|aks_pre2fa' | grep -v grep || true)"
  if [ -z "$stale" ]; then
    status_line PASS "No stale AKS scripts running"
  else
    status_line FAIL "No stale AKS scripts running" "found processes:"
    printf '%s\n' "$stale" | sed 's/^/    /'
  fi

  # --- Debian-VPS-only: CDP proxy /json/version ---
  if [ "$IS_TARGET" = "1" ]; then
    cdp="$(curl -sS --max-time 5 http://172.17.0.1:9223/json/version 2>/dev/null || true)"
    if printf '%s' "$cdp" | grep -q 'webSocketDebuggerUrl'; then
      status_line PASS "CDP proxy /json/version (172.17.0.1:9223)"
      if printf '%s' "$cdp" | grep -q 'Chrome/149'; then
        status_line PASS "CDP User-Agent is Chrome/149"
      else
        status_line FAIL "CDP User-Agent is Chrome/149" "unexpected User-Agent"
      fi
      if printf '%s' "$cdp" | grep -qi 'HeadlessChrome'; then
        status_line FAIL "CDP User-Agent is not HeadlessChrome"
      else
        status_line PASS "CDP User-Agent is not HeadlessChrome"
      fi
    else
      status_line FAIL "CDP proxy /json/version (172.17.0.1:9223)" "no webSocketDebuggerUrl"
    fi
  else
    status_line NA "CDP proxy /json/version (172.17.0.1:9223)" "Debian runtime only"
    status_line NA "CDP User-Agent is Chrome/149" "Debian runtime only"
    status_line NA "CDP User-Agent is not HeadlessChrome" "Debian runtime only"
  fi

  # --- Debian-VPS-only: systemd services ---
  if [ "$IS_TARGET" = "1" ]; then
    for svc in hermes-cdp-proxy hermes-gateway; do
      if systemctl is-active --quiet "$svc" 2>/dev/null; then
        status_line PASS "service $svc active"
      else
        status_line FAIL "service $svc active" "not active"
      fi
    done
  else
    status_line NA "service hermes-cdp-proxy active" "Debian runtime only"
    status_line NA "service hermes-gateway active" "Debian runtime only"
  fi

  # --- Debian-VPS-only: listening ports (informational) ---
  if [ "$IS_TARGET" = "1" ]; then
    ports="$(ss -lntp 2>/dev/null | grep -E ':9222|:9223|:8648' || true)"
    if [ -n "$ports" ]; then
      status_line INFO "listening ports 9222/9223/8648:"
      printf '%s\n' "$ports" | sed 's/^/    /'
    else
      status_line FAIL "listening ports 9222/9223/8648" "none found"
    fi
  else
    status_line NA "listening ports 9222/9223/8648" "Debian runtime only"
  fi

  # --- Debian-VPS-only: docker snapshot (informational) ---
  if [ "$IS_TARGET" = "1" ] && command -v docker >/dev/null 2>&1; then
    status_line INFO "docker containers:"
    docker ps -a --format '{{.ID}} {{.Image}} {{.Names}} {{.Status}}' 2>/dev/null | sed 's/^/    /'
  else
    status_line NA "docker containers" "Debian runtime only"
  fi

  # --- Debian-VPS-only: hermes network-mode config (whitelisted keys only) ---
  # Whitelist specific non-secret keys instead of dumping the section, so tokens
  # in the config never land in the persisted report (see docs/AUDIT.md S3).
  if [ "$IS_TARGET" = "1" ] && [ -f "$TARGET_MARKER" ]; then
    status_line INFO "hermes network-mode config (whitelisted keys):"
    grep -nE 'docker_extra_args|container_persistent|network' "$TARGET_MARKER" 2>/dev/null | sed 's/^/    /'
  else
    status_line NA "hermes network-mode config" "Debian runtime only"
  fi

  echo
  echo "## Summary"
  echo
  echo "- PASS: $PASS"
  echo "- FAIL: $FAIL"
  echo "- N/A:  $NA"
  echo
  if [ "$IS_TARGET" = "1" ]; then
    if [ "$FAIL" -eq 0 ]; then
      echo "RESULT: GREEN — authoritative Debian target, no failures"
    else
      echo "RESULT: RED — authoritative Debian target, $FAIL failure(s)"
    fi
  else
    echo "RESULT: NON-AUTHORITATIVE — not the Debian VPS; failures here are not production failures"
  fi
} > "$REPORT"

echo "Audit written to $REPORT"

# Fail closed on the authoritative target only.
if [ "$IS_TARGET" = "1" ] && [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
