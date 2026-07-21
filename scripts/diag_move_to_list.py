#!/usr/bin/env python3
"""READ-ONLY diagnostic: capture the "Move to List" mechanic of the AKS feed.

Romain 2026-07-21 wants a Learning-side "Move to List" action to route the
non-addable offers (console, not-on-AKS, bundles) out of the pending feed —
with the same fail-closed discipline as the submit. Before writing any write
path we must know, deterministically:

  * which lists exist (the feed is per-list: ``page=aks-merchant-feeds-<id>``);
  * the DOM control that performs the move (bulk action / row action / picker);
  * the request it would fire (form action + field names) so the writer can be
    a deterministic replay behind validation + explicit go.

This script ONLY reads: it navigates the feed (same read-only session as the
extractor) and evaluates one expression that returns the relevant markup. It
never clicks, submits, or moves anything. Nonce VALUES are masked (they are
single-use, page-scoped, and re-read live at write time) so the output is safe
to paste into a log. Not a pipeline stage; a one-off read-only probe.

Example (on the VPS, no pipeline running):
    python3 scripts/diag_move_to_list.py
    python3 scripts/diag_move_to_list.py --url '<feed url>' --out /tmp/lists.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.cdp_session import ReadOnlyCdpSession  # noqa: E402

# The list-9 (default pending) G2A feed — a known-good page to inspect. Any
# merchant feed shows the same admin chrome; override with --url if needed.
DEFAULT_URL = (
    "https://www.allkeyshop.com/blog/wp-admin/admin.php"
    "?available=all&store=38&page=aks-merchant-feeds-9&p=1"
)

# Pure read: returns the "Move to List" surface as a JSON-able object. No writes.
PROBE_JS = r"""
(function () {
  function txt(e) { return ((e && e.textContent) || '').replace(/\s+/g, ' ').trim().slice(0, 90); }
  var out = {
    href: location.href,
    is_login: !!document.querySelector('#loginform') || /wp-login/.test(location.href),
    feed_ui: !!document.querySelector('table.wp-list-table')
  };
  // 1) The lists themselves: every link to a per-list feed page.
  var pages = {};
  Array.prototype.forEach.call(document.querySelectorAll('a[href*="aks-merchant-feeds-"]'), function (a) {
    var m = /aks-merchant-feeds-(\d+)/.exec(a.href || '');
    if (!m) return;
    if (!pages[m[1]]) pages[m[1]] = { id: m[1], label: txt(a), href: a.href };
  });
  out.list_pages = Object.keys(pages).map(function (k) { return pages[k]; });
  // 2) All <select> (WP bulk actions live here; a "Move to list X" option or a
  //    target-list picker would show up).
  out.selects = Array.prototype.slice.call(document.querySelectorAll('select'), 0, 25).map(function (s) {
    return {
      name: s.name || s.id || '',
      options: Array.prototype.slice.call(s.options, 0, 80).map(function (o) {
        return { value: o.value, text: txt(o) };
      })
    };
  });
  // 3) Any control mentioning "list" (row action, button, link, option, input).
  var seen = {}, controls = [];
  Array.prototype.forEach.call(document.querySelectorAll('a,button,option,input'), function (e) {
    var hay = ((e.textContent || '') + ' ' + (e.value || '') + ' ' + (e.name || '') + ' ' + (e.className || '')).toLowerCase();
    if (hay.indexOf('list') < 0) return;
    var key = (e.tagName + '|' + (e.name || '') + '|' + txt(e)).slice(0, 140);
    if (seen[key]) return; seen[key] = 1;
    controls.push({
      tag: e.tagName.toLowerCase(), name: e.name || '',
      value: (e.value || '').slice(0, 80), text: txt(e),
      href: (e.href || '').slice(0, 200), cls: (e.className || '').slice(0, 80)
    });
  });
  out.list_controls = controls.slice(0, 50);
  // 4) The form wrapping the offers table: action/method + hidden field names
  //    (nonce/token values MASKED — re-read live at write time).
  var tbl = document.querySelector('table.wp-list-table');
  var form = tbl ? tbl.closest('form') : document.querySelector('form#posts-filter, form');
  if (form) {
    out.form = {
      action: form.getAttribute('action') || location.href,
      method: (form.getAttribute('method') || 'get').toLowerCase(),
      hidden: Array.prototype.slice.call(form.querySelectorAll('input[type=hidden]'), 0, 50).map(function (i) {
        var v = i.value || '';
        var mask = /nonce|_wpnonce|token/i.test(i.name || '');
        return { name: i.name || '', value: mask ? ('<' + v.length + ' chars, masked>') : v.slice(0, 80) };
      })
    };
  }
  // 5) One sample offer row: its checkbox + per-row action controls.
  var cell = document.querySelector('[data-offer]');
  var tr = cell ? cell.closest('tr') : null;
  if (tr) {
    var cb = tr.querySelector('input[type=checkbox]');
    out.sample_row = {
      checkbox: cb ? { name: cb.name || '', value: cb.value || '' } : null,
      actions: Array.prototype.slice.call(tr.querySelectorAll('a,button'), 0, 25).map(function (a) {
        return { text: txt(a), href: (a.href || '').slice(0, 200), cls: (a.className || '').slice(0, 80) };
      })
    };
  }
  return out;
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="READ-ONLY probe of the AKS 'Move to List' mechanic.")
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--url", default=DEFAULT_URL, help="Feed page to inspect (a per-list admin page).")
    parser.add_argument("--settle", type=float, default=3.0, help="Seconds to let the page settle before reading.")
    parser.add_argument("--out", default=None, help="Optional path to also write the JSON (NOT committed).")
    args = parser.parse_args()

    try:
        with browser_lock(ROOT, label="diag_move_to_list"), \
                ReadOnlyCdpSession(args.endpoint) as session:
            session.navigate(args.url, settle=args.settle)
            result = session.evaluate_readonly(PROBE_JS)
    except BrowserBusyError as exc:
        print(json.dumps({"error": "browser_busy", "detail": str(exc)}), file=sys.stderr)
        return 2

    if isinstance(result, dict) and result.get("is_login"):
        print(json.dumps({"error": "not_logged_in", "href": result.get("href")}), file=sys.stderr)
        return 3

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    print(payload)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
