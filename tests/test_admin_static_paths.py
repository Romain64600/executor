import re
import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "admin" / "static"

# nginx serves the console under /executor/ and strips that prefix via
# `proxy_pass http://127.0.0.1:8650/;`. There is NO `location /api/`, so an
# ABSOLUTE "/api/..." request from the page falls through to the SPA `location /`
# (try_files -> index.html) and returns HTML, not JSON — the fetch then fails
# silently. Every API path MUST be relative ("api/...") so it resolves under
# /executor/. Regression: auto.js used absolute paths and the merchant picker
# came up empty in the browser ("page HS").
ABSOLUTE_API = re.compile(r"""["'`]/api/""")


class StaticApiPathsAreRelativeTests(unittest.TestCase):
    def test_no_absolute_api_paths_in_admin_js(self):
        offenders = []
        for js in sorted(STATIC_DIR.glob("*.js")):
            for i, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
                if ABSOLUTE_API.search(line):
                    offenders.append(f"{js.name}:{i}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            "absolute /api/ paths break through nginx (/executor/ is stripped); "
            "use relative 'api/...':\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
