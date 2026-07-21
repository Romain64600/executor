"""TE6, partial (audit 2026-07-17): syntax-validate every embedded JS template.

~900 lines of browser JS live inside Python string constants; the old suite
only asserted readonly-tokens and substrings, so a stray quote or brace in an
edit shipped straight to the live modal. Full behavioral DOM tests would need
a JS DOM (a new dependency — not without Romain's go, EXECUTOR_RULES coding
prefs); what CAN be tested dependency-free is that every template, formatted
exactly the way its call site formats it, PARSES as a JavaScript expression
(node --check). Skipped cleanly when node is absent.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import src.extractor as extractor
import src.login_session as login_session
import src.submit_session as submit_session

NODE = shutil.which("node")

# Template constant -> the argument tuple its call site formats it with
# (mirror the real `%` usages; None = used verbatim).
TEMPLATES = {
    "extractor.PAGE_STATE_JS": (extractor.PAGE_STATE_JS, None),
    "submit._OPEN_MODAL_JS": (submit_session._OPEN_MODAL_JS, (json.dumps("123"),)),
    "submit._PAGE_IDS_JS": (submit_session._PAGE_IDS_JS, None),
    "submit._PAGE_ROWS_JS": (submit_session._PAGE_ROWS_JS, None),
    "submit._MODAL_CTX_JS": (submit_session._MODAL_CTX_JS, None),
    "submit._FEED_STATE_JS": (submit_session._FEED_STATE_JS, None),
    "submit._INSPECT_MODAL_JS": (submit_session._INSPECT_MODAL_JS, None),
    "submit._FORM_VALIDITY_JS": (submit_session._FORM_VALIDITY_JS, None),
    "submit._TARGETS_PROBE_JS": (submit_session._TARGETS_PROBE_JS, None),
    "submit._SELECT_OPTIONS_PROBE_JS": (
        submit_session._SELECT_OPTIONS_PROBE_JS, (json.dumps("offer[region]"),)
    ),
    "submit._IS_LOGIN_JS": (submit_session._IS_LOGIN_JS, None),
    "submit._LIST_OPTIONS_JS": (submit_session._LIST_OPTIONS_JS, None),
    "submit._BULK_ROW_PRESENT_JS": (submit_session._BULK_ROW_PRESENT_JS, (json.dumps("123"),)),
    "submit._BULK_REGISTERED_JS": (submit_session._BULK_REGISTERED_JS, (json.dumps("123"),)),
    "submit._SET_BULK_LIST_JS": (submit_session._SET_BULK_LIST_JS, (json.dumps("16"),)),
    "submit._RECT_JS": (submit_session._RECT_JS, (json.dumps("#x"),)),
    "submit._FILL_CREATE_JS": (
        submit_session._FILL_CREATE_JS,
        (json.dumps("offer[region]"), json.dumps("2"),
         json.dumps("offer[edition]"), json.dumps("1"), json.dumps("native")),
    ),
    "submit._TRUSTED_PREP_JS": (
        submit_session._TRUSTED_PREP_JS,
        (json.dumps("offer[region]"), json.dumps("offer[edition]")),
    ),
    "submit._TRUSTED_POLL_JS": (submit_session._TRUSTED_POLL_JS, None),
    "submit._SELECTIZE_INPUT_RECT_JS": (
        submit_session._SELECTIZE_INPUT_RECT_JS, (json.dumps("offer[region]"),)
    ),
    "submit._SELECTIZE_OPTION_RECT_JS": (
        submit_session._SELECTIZE_OPTION_RECT_JS,
        (json.dumps("offer[region]"), json.dumps("9")),
    ),
    "submit._SELECTIZE_READBACK_JS": (
        submit_session._SELECTIZE_READBACK_JS, (json.dumps("offer[region]"),)
    ),
    "submit._CLICK_TARGET_PROBE_JS": (
        submit_session._CLICK_TARGET_PROBE_JS, (json.dumps("#x"),)
    ),
    "submit._TRUSTED_CLEANUP_JS": (submit_session._TRUSTED_CLEANUP_JS, None),
    "submit._TARGETS_READBACK_JS": (submit_session._TARGETS_READBACK_JS, None),
    "login._DASHBOARD_MARKER_JS": (login_session._DASHBOARD_MARKER_JS, None),
    "login._LOGIN_FORM_FIELDS_JS": (login_session._LOGIN_FORM_FIELDS_JS, None),
    "login._TWOFA_FIELD_JS": (login_session._TWOFA_FIELD_JS, None),
    "login._LOGIN_ERROR_JS": (login_session._LOGIN_ERROR_JS, None),
}


@unittest.skipUnless(NODE, "node not available — JS syntax validation skipped")
class EmbeddedJsSyntaxTests(unittest.TestCase):
    def test_every_template_parses_as_a_js_expression(self):
        failures = []
        with tempfile.TemporaryDirectory() as tmp:
            for name, (template, args) in TEMPLATES.items():
                js = template % args if args is not None else template
                # Call sites evaluate these as EXPRESSIONS via Runtime.evaluate
                # — wrap the same way so statements-only syntax fails too.
                wrapped = f"(function() {{ return ( {js} ); }});"
                path = Path(tmp) / "probe.js"
                path.write_text(wrapped, encoding="utf-8")
                proc = subprocess.run(
                    [NODE, "--check", str(path)], capture_output=True, text=True
                )
                if proc.returncode != 0:
                    failures.append(f"{name}: {proc.stderr.strip().splitlines()[-1]}")
        self.assertFalse(
            failures, "embedded JS template(s) no longer parse:\n" + "\n".join(failures)
        )

    def test_inventory_is_complete(self):
        # A NEW *_JS constant must be added to TEMPLATES (or explicitly
        # excluded here) — otherwise it ships syntax-unchecked.
        known_missing: set[str] = set()
        for module, prefix in ((submit_session, "submit"), (extractor, "extractor"),
                               (login_session, "login")):
            for attr in dir(module):
                if attr.endswith("_JS") and isinstance(getattr(module, attr), str):
                    key = f"{prefix}.{attr}"
                    if key not in TEMPLATES and key not in known_missing:
                        self.fail(
                            f"{key} is not syntax-checked — add it to TEMPLATES "
                            "in tests/test_embedded_js.py"
                        )


if __name__ == "__main__":
    unittest.main()
