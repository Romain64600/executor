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
