# LOGIN_SPEC.md — RETIRED (2026-07-29)

**This spec described the password + 2FA login (Stage 0b, `scripts/00b_login.py`,
`run_login`), which is DEAD.** AKS disabled username/password login (social /
OAuth only), so a password submit is always rejected — the password flow can
never authenticate. The CLI stage and its orchestration were removed.

## Current re-auth: cookie transfer

The operator completes the social login in their **own** browser, then transfers
the WP session cookies into the VPS tab from the admin console
(`/executor/tri` → 🔑 Se reconnecter): fill Name + Value for
`wordpress_logged_in_<hash>` and `wordpress_sec_<hash>`, and the server injects
them (CDP `Network.setCookies`) and proves the session with `verify_dashboard`.

- Code: `src/admin/login_manager.py` (`normalize_cookies`, `apply_cookies`),
  `src/login_session.py` (`LoginSession.set_cookies`, `verify_dashboard`).
- Non-negotiables preserved: explicit operator submit only (never
  self-triggered); cookie VALUES are session secrets — never logged, echoed, or
  stored; injection restricted to `allkeyshop.com` by exact host/suffix match;
  fail-closed on missing cookies / red invariants / browser busy.
