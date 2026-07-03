"""Interactive CDP session for the submitter DRY-RUN.

Extends the read-only session with the *minimum* interaction the dry-run needs:
list a page's offer ids, open an offer's modal, read the modal context, and check
whether we've been bounced to the WP login page.

**This build has no method that fills a form or clicks "Create offer".** The create
capability literally does not exist here — the real write path is a separate,
explicitly-authorized build. Opening a modal is a harmless UI action (no DB write
happens until "Create offer"), which is why it is allowed for the rehearsal.
"""

from __future__ import annotations

import json
from typing import Any

from src.cdp_session import ReadOnlyCdpSession

# JS to open the create-offer modal for a given offer id (opens ThickBox; no write).
_OPEN_MODAL_JS = """
(function(){
  var rows=document.querySelectorAll('tr[data-offer]');
  for(var i=0;i<rows.length;i++){
    var d;try{d=JSON.parse(rows[i].getAttribute('data-offer'));}catch(e){continue;}
    if(String(d.id)===%s){
      var b=rows[i].querySelector('[data-create-offer]');
      if(b){b.click();return 'OPENED';}
      return 'NO_BUTTON';
    }
  }
  return 'ROW_NOT_FOUND';
})()
"""

_PAGE_IDS_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll('tr[data-offer]'))"
    ".map(function(e){try{return String(JSON.parse(e.getAttribute('data-offer')).id);}"
    "catch(x){return null;}}).filter(Boolean))"
)

_MODAL_CTX_JS = (
    "JSON.stringify((function(){var c=document.querySelector('#TB_ajaxContent');"
    "if(!c){return {ok:false,select_names:[]};}"
    "return {ok:true,select_names:Array.from(c.querySelectorAll('select'))"
    ".map(function(s){return s.name;})};})())"
)

_IS_LOGIN_JS = "!!document.querySelector('#loginform') || /wp-login/.test(location.href)"


class SubmitSession(ReadOnlyCdpSession):
    """Read + open-modal only. No fill, no create."""

    def is_login_page(self) -> bool:
        return bool(self.evaluate_readonly(_IS_LOGIN_JS))

    def page_offer_ids(self) -> list[str]:
        raw = self.evaluate_readonly(_PAGE_IDS_JS)
        if not raw:
            return []
        return list(json.loads(raw))

    def open_offer_modal(self, offer_id: str) -> str:
        # Uses the raw evaluator: this is the one explicitly-allowed interaction.
        return str(self._evaluate(_OPEN_MODAL_JS % json.dumps(str(offer_id))))

    def modal_context(self) -> dict[str, Any]:
        raw = self.evaluate_readonly(_MODAL_CTX_JS)
        return json.loads(raw) if raw else {"ok": False, "select_names": []}


# The ONE mutating interaction: set region+edition via selectize, then click the
# modal "Create offer" .button-primary (skill S09/S17/S19). A 500 ms settle between
# setValue and the click matches the proven pattern; the Promise lets us await it.
#
# S18 investigation instrumentation (2026-07-03):
# - PRE-CLICK: count the [data-success]/[data-error] nodes already in the DOM.
#   The live canary showed a SUCCESS with an EMPTY signal text — consistent with a
#   pre-existing (template/hidden) node being mistaken for the AJAX result. The
#   poll now only accepts a signal if the node count INCREASED post-click (a new
#   node) — otherwise it keeps polling and ends in NO_SIGNAL (post-save remains
#   the only truth either way).
# - NETWORK: window.fetch and XMLHttpRequest are wrapped (in-page, diagnostic
#   only) just before the click, so the diag reports whether the click actually
#   fired an admin-ajax request and what HTTP status came back. Method+URL(+status)
#   only — never bodies, never headers/cookies.
# - BUTTON STATE: disabled/visible are recorded; `polls` says how fast a signal
#   appeared (polls=1 ⇒ almost certainly pre-existing/instant, not a server ack).
# - CLICK MODE: 'native' (default) uses b.click(); 'dispatch' dispatches a full
#   mousedown/mouseup/click MouseEvent sequence ON THE BUTTON ONLY — an explicit,
#   documented derogation authorized by Romain (2026-07-03) after the native click
#   was proven not to persist on Driffle. Still NO form.submit(), NO XHR.
_FILL_CREATE_JS = (
    "(function(){return new Promise(function(resolve){"
    "var rn=%s,en=%s,rid=%s,eid=%s,mode=%s;"
    "var r=document.querySelector('select[name=\"'+rn+'\"]');"
    "var e=document.querySelector('select[name=\"'+en+'\"]');"
    "function opts(s){return s?Array.prototype.slice.call(s.options).map(function(o){return o.value;}):[];}"
    "function count(sel){return document.querySelectorAll(sel).length;}"
    "if(!r||!e||!r.selectize||!e.selectize){resolve({status:'NO_SELECTS'});return;}"
    "r.selectize.setValue(rid);e.selectize.setValue(eid);"
    "setTimeout(function(){"
    "var diag={region_target:rid,edition_target:eid,"
    "region_set:String(r.selectize.getValue()),edition_set:String(e.selectize.getValue()),"
    "region_options:opts(r),edition_options:opts(e),click_mode:mode,requests:[]};"
    "var b=document.querySelector('#TB_ajaxContent .button-primary');"
    "if(!b){diag.status='NO_BUTTON';resolve(diag);return;}"
    "diag.button={disabled:!!b.disabled,visible:b.offsetParent!==null,"
    "text:(b.textContent||'').trim().slice(0,40)};"
    "var pre_s=count('[data-success]'),pre_er=count('[data-error]');"
    "diag.pre_existing={success:pre_s,error:pre_er};"
    # Diagnostic-only network taps (method + URL + status; never bodies/headers).
    "var reqs=diag.requests;"
    "var _fetch=window.fetch;"
    "if(_fetch){window.fetch=function(u,o){var m=(o&&o.method)||'GET';"
    "var rec={via:'fetch',method:m,url:String(u).slice(0,160),status:null};reqs.push(rec);"
    "return _fetch.apply(this,arguments).then(function(res){rec.status=res.status;return res;});};}"
    "var _open=XMLHttpRequest.prototype.open,_send=XMLHttpRequest.prototype.send;"
    "XMLHttpRequest.prototype.open=function(m,u){this._diag={via:'xhr',method:m,"
    "url:String(u).slice(0,160),status:null};return _open.apply(this,arguments);};"
    "XMLHttpRequest.prototype.send=function(){var x=this;if(x._diag){reqs.push(x._diag);"
    "x.addEventListener('loadend',function(){x._diag.status=x.status;});}"
    "return _send.apply(this,arguments);};"
    "if(mode==='dispatch'){"
    "['mousedown','mouseup','click'].forEach(function(t){"
    "b.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}));});"
    "}else{b.click();}"
    # Wait for the modal AJAX to settle before returning (do NOT navigate away
    # mid-request). Only a NEW signal node (count increased) is accepted.
    "var n=0,iv=setInterval(function(){n++;"
    "var cs=count('[data-success]'),ce=count('[data-error]');"
    "function fin(st,sel){clearInterval(iv);diag.status=st;diag.polls=n;"
    "var nodes=document.querySelectorAll(sel);var el=nodes[nodes.length-1];"
    "diag.signal=el?(el.textContent||'').trim().slice(0,150):'';"
    "window.fetch=_fetch;XMLHttpRequest.prototype.open=_open;XMLHttpRequest.prototype.send=_send;"
    "resolve(diag);}"
    "if(cs>pre_s){fin('SUCCESS','[data-success]');}"
    "else if(ce>pre_er){fin('ERROR','[data-error]');}"
    "else if(n>=40){diag.polls=n;"
    "window.fetch=_fetch;XMLHttpRequest.prototype.open=_open;XMLHttpRequest.prototype.send=_send;"
    "diag.status='NO_SIGNAL';resolve(diag);}"
    "},200);"
    "},500);"
    "});})()"
)


class WriteSubmitSession(SubmitSession):
    """SubmitSession + the single mutating op. Instantiated ONLY under ``--submit``.

    ``fill_and_create`` is the only method that writes: it sets region/edition on the
    verified select names and clicks "Create offer". No direct XHR, no
    ``form.submit()`` (skill S09). ``click_mode='dispatch'`` (a MouseEvent sequence
    on the Create button ONLY — never on the form) is an explicit derogation
    authorized by Romain (2026-07-03) after the native ``.click()`` was proven not
    to persist on Driffle; the post-save feed check remains the only success proof.
    """

    CLICK_MODES = ("native", "dispatch")

    def fill_and_create(
        self,
        region_select: str,
        region_id: str,
        edition_select: str,
        edition_id: str,
        click_mode: str = "native",
    ) -> dict[str, Any]:
        """Set region+edition and click Create. Returns a diagnostic dict with
        ``status`` plus read-back values (region_set/edition_set), the available
        options, the network requests fired by the click (method/url/status only),
        the pre-existing signal-node counts, and the modal signal text.

        ``click_mode='dispatch'`` (MouseEvent sequence on the button only) is an
        explicit, documented derogation — see the JS block comment. Fail-closed:
        an unknown mode raises instead of guessing."""

        if click_mode not in self.CLICK_MODES:
            raise ValueError(f"unknown click_mode: {click_mode!r} (allowed: {self.CLICK_MODES})")
        result = self._evaluate(
            _FILL_CREATE_JS
            % (
                json.dumps(region_select),
                json.dumps(edition_select),
                json.dumps(str(region_id)),
                json.dumps(str(edition_id)),
                json.dumps(click_mode),
            )
        )
        return result if isinstance(result, dict) else {"status": "NO_RESULT", "raw": result}
