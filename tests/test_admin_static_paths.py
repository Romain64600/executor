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

# Même piège, côté HTML : la console vit sous /executor/, donc un href ABSOLU ("/sort")
# sort du préfixe et tombe sur la racine du domaine. Régression du 2026-09-18 : la barre
# d'onglets de sql.html était écrite en absolu et aucun de ses liens ne retombait sur la
# bonne page ("le bouton ne renvoie pas sur la bonne page"). Les liens internes doivent être
# RELATIFS ("tri", "auto", "games", "."). On ne vise que les chemins internes : une URL
# externe (http://…, mailto:) n'est pas concernée.
ABSOLUTE_HREF = re.compile(r"""\b(?:href|src|action)=["']/(?!/)""")


class InternalLinksAreRelativeTests(unittest.TestCase):
    """Un lien absolu sort du préfixe /executor/ du reverse proxy et casse la navigation."""

    def test_no_absolute_internal_links_in_admin_html(self):
        offenders = []
        for html in sorted(STATIC_DIR.glob("*.html")):
            for i, line in enumerate(html.read_text(encoding="utf-8").splitlines(), 1):
                if ABSOLUTE_HREF.search(line):
                    offenders.append(f"{html.name}:{i}: {line.strip()[:90]}")
        self.assertEqual(
            offenders, [],
            "liens absolus — ils ignorent le préfixe /executor/ :\n" + "\n".join(offenders))

    def test_the_sql_tab_bar_points_at_the_same_targets_as_the_others(self):
        """Les cinq onglets doivent être les mêmes partout, sinon la navigation diverge."""

        import re as _re
        def tabs(name):
            t = (STATIC_DIR / name).read_text(encoding="utf-8")
            block = t[t.index('<nav class="tabs">'):]
            block = block[:block.index("</nav>")]
            return _re.findall(r'href="([^"]+)"', block)
        ref = tabs("sort.html")
        self.assertEqual(ref, [".", "tri", "auto", "games", "sql"], ref)
        for page in ("auto.html", "urls.html", "sql.html"):
            with self.subTest(page=page):
                self.assertEqual(tabs(page), ref)


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
