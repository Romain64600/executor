# Non-negotiable invariants

## Browser / network

Official CDP endpoint from Docker bridge:
http://172.17.0.1:9223/json/version

Host Chrome endpoint:
http://127.0.0.1:9222/json/version

Required User-Agent:
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36

AKS must work directly without VPN:
https://www.allkeyshop.com/blog/

No OpenVPN process may be running (a tunnel coming up mid-session would flip
the egress IP under an authenticated AKS session). Enforced by
`scripts/01_check_invariants.py` (`no_openvpn_process`, fail-closed: an
undeterminable process state also fails) and `scripts/00_audit_env.sh`.

## Forbidden

- Browserbase
- browser_navigate for AKS execution
- Playwright fallback
- VPN fallback when AKS direct works
- /root/start-chromium.sh
- random 0.0.0.x CDP checks
- submitting without explicit validation file
- submitting without modal context verification
- fire-and-forget submission
- using old candidates from memory
- using previous feed state
