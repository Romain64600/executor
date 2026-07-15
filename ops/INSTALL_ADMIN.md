# Admin page — installation (Debian VPS)

The admin page lets the operator validate the normalized report (with optional
region/edition overrides) and trigger a supervised submit from a browser.
Architecture: `nginx (HTTPS + basic auth, /executor/) → 127.0.0.1:8650
(scripts/07_admin_server.py, stdlib only) → subprocess of the real stage
scripts (04_validate.py check, 05_submit.py)`.

## 1. Basic auth (htpasswd)

```sh
# prompts for the password, apr1 hash (nginx-compatible without apache2-utils)
sudo sh -c 'printf "romain:%s\n" "$(openssl passwd -apr1)" > /etc/nginx/.htpasswd_executor'
sudo chown root:www-data /etc/nginx/.htpasswd_executor
sudo chmod 640 /etc/nginx/.htpasswd_executor
```

To rotate the password, re-run the same commands.

## 2. nginx vhost

```sh
sudo cp ops/nginx-51.38.37.254.sslip.io.conf /etc/nginx/sites-available/51.38.37.254.sslip.io.conf
# (already symlinked in sites-enabled on this VPS)
sudo nginx -t && sudo systemctl reload nginx
```

## 3. HTTPS (Let's Encrypt, certbot already installed)

```sh
sudo certbot --nginx -d 51.38.37.254.sslip.io --redirect --agree-tos --no-eff-email -m rl64600@gmail.com
```

`--redirect` rewrites the vhost so port 80 forwards to HTTPS — basic auth
credentials never travel in clear text. Renewal is automatic
(`certbot.timer`).

## 4. systemd service

```sh
sudo cp ops/aks-admin.service /etc/systemd/system/aks-admin.service
sudo systemctl daemon-reload
sudo systemctl enable --now aks-admin
systemctl status aks-admin --no-pager
```

Notes:
- The app refuses any non-loopback bind without `--allow-external`; auth
  lives in nginx only.
- Stopping/restarting `aks-admin` kills an in-flight submit child (cgroup) —
  never restart it casually during a submit. At next startup the run is
  marked `interrupted` and the UI tells the operator to inspect the feed and
  `submit_plan.json`.

## 5. End-to-end check

1. `https://51.38.37.254.sslip.io/executor/` → basic auth prompt → page loads.
2. Pick a matched run → the normalized report renders verbatim.
3. Toggle one approve + save → `candidates.json` / `validation.json` /
   `approved.json` regenerated in the run dir, `operator_override` /
   `validation_saved` events in `logs/<run_id>.jsonl`.
4. "Vérifier les invariants" → green (ok + authoritative) on this VPS.
5. "Dry-run" → progress streams, `submit_plan.json` panel renders, exit 0.
6. Real submit only on Romain's go: mode safe = full validated batch,
   learning/advanced = canary of 1 (R24). The confirmation modal requires
   typing `GO` and shows the exact command.
7. A second submit while one runs must be refused (`submit_in_progress`).

## Files

- `scripts/07_admin_server.py` — CLI entry (loopback bind, orphan recovery).
- `src/admin/` — `app.py` (HTTP), `runs.py` (safe run access),
  `validation_io.py` (triple regeneration), `submit_manager.py` (supervised
  subprocess), `static/` (frontend).
- `runs/<id>/admin_submit.json` — submit supervision state (gitignored with
  the rest of `runs/`).
