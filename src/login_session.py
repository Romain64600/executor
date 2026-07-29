"""Session re-auth primitives (cookie transfer).

AKS disabled username/password login (social/OAuth only, 2026-07-29), so the
old password+2FA Stage 0b was retired. ``LoginSession`` now exposes just what
the cookie-transfer re-auth needs (`src/admin/login_manager.py`): inject the
WP session cookies into the tab and PROVE the resulting session with a
deterministic dashboard check. It extends ``WriteSubmitSession`` only to reuse
the audited CDP session plumbing — no new CDP mechanism is introduced.
"""

from __future__ import annotations

from typing import Any

from src.submit_session import WriteSubmitSession

_DASHBOARD_MARKER_JS = "!!document.querySelector('#wpadminbar')"


class LoginSession(WriteSubmitSession):
    """WP-admin session primitives for cookie-transfer re-auth."""

    ADMIN_URL = "https://www.allkeyshop.com/blog/wp-admin/"

    def set_cookies(self, cookies: list[dict[str, Any]]) -> dict[str, Any]:
        """Inject session cookies into the tab (CDP ``Network.setCookies``).

        The authenticated session is transferred as cookies exported from a
        browser where the operator completed the social login. The cookie VALUES
        are session secrets — passed straight to CDP, never logged. The caller
        (``LoginManager.apply_cookies``) then navigates wp-admin and proves the
        session with ``verify_dashboard``."""

        self._cmd("Network.enable", {})
        return self._cmd("Network.setCookies", {"cookies": cookies})

    def has_dashboard_marker(self) -> bool:
        return bool(self.evaluate_readonly(_DASHBOARD_MARKER_JS))

    def verify_dashboard(self) -> dict[str, Any]:
        """Deterministic session proof: URL under ``/wp-admin/`` with no
        login/reauth marker, AND the admin toolbar DOM node present. Both, not
        one — a URL check alone can be fooled by a redirect loop; a DOM check
        alone by a cached partial page."""

        url = str(self.evaluate_readonly("location.href") or "")
        url_ok = (
            "/wp-admin/" in url
            and "wp-login.php" not in url
            and "action=login" not in url
            and "reauth=1" not in url
        )
        dom_ok = self.has_dashboard_marker()
        return {"ok": url_ok and dom_ok, "url_ok": url_ok, "dom_ok": dom_ok, "url": url}
