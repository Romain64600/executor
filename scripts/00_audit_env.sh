#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-runs/audit_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT_DIR"

REPORT="$OUT_DIR/audit.md"

{
  echo "# AKS executor environment audit"
  echo
  echo "Date UTC: $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "Host: $(hostname)"
  echo "User: $(whoami)"
  echo

  echo "## AKS direct"
  curl -I --max-time 10 https://www.allkeyshop.com/blog/ | head -20 || true
  echo

  echo "## CDP proxy"
  curl -sS --max-time 5 http://172.17.0.1:9223/json/version \
    | grep -E '"Browser"|"User-Agent"|"webSocketDebuggerUrl"' || true
  echo

  echo "## Host CDP"
  curl -sS --max-time 5 http://127.0.0.1:9222/json/version \
    | grep -E '"Browser"|"User-Agent"|"webSocketDebuggerUrl"' || true
  echo

  echo "## OpenVPN"
  pgrep -af openvpn || echo "OK openvpn arrêté"
  echo

  echo "## Old AKS scripts"
  ps aux | grep -Ei "cdp_submit|cdp_scan|cdp_login|otp_now|aks_h|aks_fix|aks_pre2fa" | grep -v grep || echo "OK aucun ancien script AKS actif"
  echo

  echo "## Services"
  sudo systemctl status hermes-cdp-proxy --no-pager -l || true
  echo
  sudo systemctl status hermes-gateway --no-pager -l || true
  echo

  echo "## Ports"
  ss -lntp | grep -E ':9222|:9223|:8648' || true
  echo

  echo "## Docker containers"
  docker ps -a --format '{{.ID}} {{.Image}} {{.Names}} {{.Networks}} {{.Status}}'
  echo

  echo "## Docker network modes"
  docker ps -aq | while read c; do
    docker inspect -f '{{.Name}} image={{.Config.Image}} network={{.HostConfig.NetworkMode}} status={{.State.Status}}' "$c" 2>/dev/null || true
  done
  echo

  echo "## Hermes terminal config excerpt"
  grep -nA30 '^terminal:' /home/debian/.hermes/config.yaml || true
} > "$REPORT"

echo "Audit written to $REPORT"
