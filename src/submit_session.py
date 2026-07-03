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
import random
import time
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

# Read-only DOM probe of the currently-open modal (S02). Passes the
# ReadOnlyCdpSession's mutation guard (no click/submit/fetch/dispatchEvent/
# setValue/.value=/createElement etc.). Returns a structured diag of the button
# targeted by S09 (`.button-primary`), its parent <form> if any, other forms in
# the modal, [data-success]/[data-error] node locations, #TB_window visibility,
# and the current selects state. Used by --inspect to diagnose why the S09 click
# does not reach the network on Driffle (canary #3, 2026-07-03).
_INSPECT_MODAL_JS = (
    "JSON.stringify((function(){"
    "function attrs(el,pre){return Array.prototype.filter.call(el.attributes,"
    "function(a){return pre?a.name.indexOf(pre)===0:true;})"
    ".map(function(a){return a.name+'='+String(a.value).slice(0,80);});}"
    "function path(el,md){var p=[],c=el,d=0;"
    "while(c&&c!==document.body&&d<md){"
    "var s=c.tagName.toLowerCase();if(c.id)s+='#'+c.id;"
    "else if(c.className&&typeof c.className==='string')"
    "s+='.'+c.className.trim().split(/\\s+/).slice(0,2).join('.');"
    "p.unshift(s);c=c.parentElement;d++;}return p.join(' > ');}"
    "function elDesc(el){if(!el)return null;return {"
    "tag:el.tagName,type_prop:el.type||null,type_attr:el.getAttribute('type'),"
    "id:el.id||null,klass:el.className||null,href:el.getAttribute('href'),"
    "name:el.name||null,text:(el.textContent||'').trim().slice(0,60),"
    "data_attrs:attrs(el,'data-'),path:path(el,8)};}"
    "var content=document.querySelector('#TB_ajaxContent');"
    "var tbwin=document.querySelector('#TB_window');var tbstyle=null;"
    "if(tbwin){var cs=getComputedStyle(tbwin);"
    "tbstyle={display:cs.display,visibility:cs.visibility,opacity:cs.opacity};}"
    "if(!content)return {modal_ok:false,tbwindow_present:!!tbwin,tbwindow_style:tbstyle};"
    "var buttons=Array.prototype.slice.call(content.querySelectorAll('.button-primary'));"
    "var button=buttons[0]||null;"
    "var form=button?button.closest('form'):null;"
    "var formDesc=form?{"
    "tag:form.tagName,id:form.id||null,klass:form.className||null,"
    "action:form.getAttribute('action'),method:form.getAttribute('method')||form.method,"
    "onsubmit_attr:!!form.getAttribute('onsubmit')}:null;"
    "var forms=Array.prototype.slice.call(content.querySelectorAll('form')).map(function(f){"
    "return {id:f.id||null,action:f.getAttribute('action'),"
    "method:f.getAttribute('method')||f.method};});"
    "function locate(sel,scope){"
    "return Array.prototype.slice.call(scope.querySelectorAll(sel)).slice(0,10)"
    ".map(function(el){return {path:path(el,6),text:(el.textContent||'').trim().slice(0,60)};});}"
    # Compute what elementFromPoint returns at the button center — if the answer
    # is not the button (or its child), an overlay is intercepting our click.
    "var elementAtCenter=null;var buttonStyle=null;"
    "if(button){var br=button.getBoundingClientRect();"
    "var cx=br.x+br.width/2,cy=br.y+br.height/2;"
    "var atPoint=document.elementFromPoint(cx,cy);"
    "elementAtCenter={cx:cx,cy:cy,el:elDesc(atPoint),is_button:atPoint===button,"
    "is_button_child:!!(atPoint&&button.contains(atPoint))};"
    "var cs=getComputedStyle(button);"
    "buttonStyle={pointer_events:cs.pointerEvents,z_index:cs.zIndex,"
    "position:cs.position,visibility:cs.visibility,opacity:cs.opacity,"
    "display:cs.display};}"
    # Form <input>: expose name/type/required/value_len (never the value). Also
    # look for common auth field names in the form (nonce/_token/security).
    "var formInputs=[];var formHasNonce=false;var allValid=true;"
    "if(form){var inputs=form.querySelectorAll('input');"
    "for(var i=0;i<inputs.length;i++){var inp=inputs[i];"
    "var val=inp.value||'';var v=inp.validity;"
    "var visible=inp.offsetParent!==null;"
    "var validState={valid:v.valid,valueMissing:v.valueMissing,"
    "typeMismatch:v.typeMismatch,badInput:v.badInput};"
    "if(!v.valid)allValid=false;"
    "formInputs.push({name:inp.name||null,type:inp.type||null,"
    "required:!!inp.required,value_len:val.length,visible:visible,"
    "willValidate:!!inp.willValidate,validity:validState,"
    "aria_hidden:inp.getAttribute('aria-hidden'),"
    "parent_class:inp.parentElement?inp.parentElement.className:null});"
    "if(/nonce|_token|security/i.test(inp.name||'')&&val.length>0)formHasNonce=true;}}"
    "return {modal_ok:true,tbwindow_present:!!tbwin,tbwindow_style:tbstyle,"
    "button:elDesc(button),button_count_in_modal:buttons.length,"
    "button_style:buttonStyle,element_at_center:elementAtCenter,"
    "form:formDesc,forms_in_modal:forms.length,forms:forms,"
    "form_inputs:formInputs,form_has_nonce:formHasNonce,form_all_inputs_valid:allValid,"
    "data_success_in_modal:locate('[data-success]',content),"
    "data_error_in_modal:locate('[data-error]',content),"
    "data_success_in_doc:document.querySelectorAll('[data-success]').length,"
    "data_error_in_doc:document.querySelectorAll('[data-error]').length,"
    "modal_selects:Array.prototype.slice.call(content.querySelectorAll('select'))"
    ".map(function(s){return {name:s.name,has_selectize:!!s.selectize,"
    "options:Array.prototype.slice.call(s.options).map(function(o){return o.value;})};})"
    "};})())"
)

_IS_LOGIN_JS = "!!document.querySelector('#loginform') || /wp-login/.test(location.href)"

# Read-only rect probe (S02-safe): returns the target's getBoundingClientRect
# and the viewport dims. Used by the trusted click to compute the mouse
# coordinates. No mutation of any kind.
_RECT_JS = (
    "JSON.stringify((function(){"
    "var el=document.querySelector(%s);"
    "if(!el)return {ok:false};"
    "var r=el.getBoundingClientRect();"
    "return {ok:true,x:r.x,y:r.y,width:r.width,height:r.height,"
    "top:r.top,left:r.left,bottom:r.bottom,right:r.right,"
    "viewport:{w:window.innerWidth,h:window.innerHeight}};"
    "})())"
)


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

    def inspect_modal_dom(self) -> dict[str, Any]:
        """Read-only DOM inspection of the currently-open modal (S02).

        Returns a diag dict describing the S09 `.button-primary` target (tag /
        type / id / class / href / data-*), its parent `<form>` if any (action /
        method / onsubmit_attr), other forms in the modal, `[data-success]` /
        `[data-error]` node locations (in modal + doc counts), `#TB_window`
        visibility, and the selects' current state. No clicks, no writes.
        """

        raw = self.evaluate_readonly(_INSPECT_MODAL_JS)
        return json.loads(raw) if raw else {"modal_ok": False}


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


# Chantier n°1 extension (2026-07-03) — "Selectize humanisé".
#
# Inspect on Driffle canary-trusted-1625 proved the DOM-level `setValue()` path
# leaves the form invalid (`form_all_inputs_valid: false`): Selectize's own
# .selectize-input text field stays empty with `required invalid not-full`,
# blocking HTML5 form validation and preventing any `submit` event. On top of
# that, the form has an `offer[targets][]` required text field that a real user
# interaction likely populates.
#
# The new flow no longer touches `setValue` at all. Instead:
#   1. PREP JS installs the network taps + records pre-existing signal counts
#      *and* text snapshots (so text UPDATES on existing template nodes count
#      as ACKs, not just new nodes). NO fill.
#   2. Python drives `select_via_trusted(select_name, value_id)` twice (region,
#      edition): trusted CDP click on the .selectize-input → dropdown opens →
#      trusted click on the .option[data-value="{id}"] → dropdown closes,
#      Selectize applies value, plugin's own listeners fire naturally.
#   3. Python drives `click_trusted_at_element("#TB_ajaxContent .button-primary")`
#      (unchanged path — trusted CDP click on the submit button center).
#   4. POLL JS observes signal ACK.
#
# All events land in Chrome with `isTrusted: true`. No `form.submit()`, no XHR,
# no `.click()`, no `setValue`, no `dispatchEvent`. Post-save (offer gone from
# refreshed pending feed) remains the ONLY success proof.
#
# Taps live on ``window.__s18taps`` (prep) and ``window.__s18orig`` (originals
# to restore). Between prep and poll, no other JS should run in this tab.
_TRUSTED_PREP_JS = (
    "(function(){return new Promise(function(resolve){"
    "var rn=%s,en=%s;"
    "var r=document.querySelector('select[name=\"'+rn+'\"]');"
    "var e=document.querySelector('select[name=\"'+en+'\"]');"
    "function opts(s){return s?Array.prototype.slice.call(s.options).map(function(o){return o.value;}):[];}"
    "function count(sel){return document.querySelectorAll(sel).length;}"
    "function texts(sel){return Array.prototype.slice.call(document.querySelectorAll(sel))"
    ".map(function(el){return (el.textContent||'').trim();});}"
    "if(!r||!e||!r.selectize||!e.selectize){resolve({status:'NO_SELECTS'});return;}"
    "var b=document.querySelector('#TB_ajaxContent .button-primary');"
    "if(!b){resolve({status:'NO_BUTTON'});return;}"
    "var diag={region_options:opts(r),edition_options:opts(e),"
    "button:{disabled:!!b.disabled,visible:b.offsetParent!==null,"
    "text:(b.textContent||'').trim().slice(0,40)}};"
    "window.__s18taps={reqs:[],"
    "pre_s:count('[data-success]'),pre_er:count('[data-error]'),"
    "pre_s_texts:texts('[data-success]'),pre_er_texts:texts('[data-error]')};"
    "var _f=window.fetch,_o=XMLHttpRequest.prototype.open,_s=XMLHttpRequest.prototype.send;"
    "window.__s18orig={f:_f,o:_o,s:_s};"
    "if(_f){window.fetch=function(u,o){var m=(o&&o.method)||'GET';"
    "var rec={via:'fetch',method:m,url:String(u).slice(0,160),status:null};"
    "window.__s18taps.reqs.push(rec);"
    "return _f.apply(this,arguments).then(function(res){rec.status=res.status;return res;});};}"
    "XMLHttpRequest.prototype.open=function(m,u){this._d18={via:'xhr',method:m,"
    "url:String(u).slice(0,160),status:null};return _o.apply(this,arguments);};"
    "XMLHttpRequest.prototype.send=function(){var x=this;if(x._d18){"
    "window.__s18taps.reqs.push(x._d18);"
    "x.addEventListener('loadend',function(){x._d18.status=x.status;});}"
    "return _s.apply(this,arguments);};"
    "diag.pre_existing={success:window.__s18taps.pre_s,error:window.__s18taps.pre_er};"
    "diag.status='PREPARED';resolve(diag);"
    "});})()"
)

# Poll for an ACK after the trusted click. Accepts EITHER a NEW
# [data-success]/[data-error] node (count increased) OR a TEXT CHANGE on an
# existing template node (Driffle's actual pattern: the plugin updates the
# pre-existing <p data-success> textContent on ACK, doesn't add a node). The
# taps installed by prep are restored on resolution.
_TRUSTED_POLL_JS = (
    "(function(){return new Promise(function(resolve){"
    "function count(sel){return document.querySelectorAll(sel).length;}"
    "function texts(sel){return Array.prototype.slice.call(document.querySelectorAll(sel))"
    ".map(function(el){return (el.textContent||'').trim();});}"
    "var t=window.__s18taps||{reqs:[],pre_s:0,pre_er:0,pre_s_texts:[],pre_er_texts:[]};"
    "function textChanged(cur,pre){"
    "for(var i=0;i<Math.min(cur.length,pre.length);i++){"
    "if(cur[i]!==(pre[i]||'')&&cur[i].length>0)return cur[i];}"
    "return null;}"
    "var n=0,iv=setInterval(function(){n++;"
    "var cs=count('[data-success]'),ce=count('[data-error]');"
    "var cs_t=texts('[data-success]'),ce_t=texts('[data-error]');"
    "var s_txt=textChanged(cs_t,t.pre_s_texts);"
    "var e_txt=textChanged(ce_t,t.pre_er_texts);"
    "function fin(st,sig){clearInterval(iv);"
    "var out={status:st,polls:n,requests:t.reqs,signal:sig||''};"
    "var o=window.__s18orig;if(o){window.fetch=o.f;XMLHttpRequest.prototype.open=o.o;"
    "XMLHttpRequest.prototype.send=o.s;delete window.__s18orig;}"
    "delete window.__s18taps;resolve(out);}"
    # NEW node → SUCCESS/ERROR
    "if(cs>t.pre_s){var ns=document.querySelectorAll('[data-success]');"
    "var els=ns[ns.length-1];fin('SUCCESS',els?(els.textContent||'').trim().slice(0,150):'');}"
    "else if(ce>t.pre_er){var ne=document.querySelectorAll('[data-error]');"
    "var ele=ne[ne.length-1];fin('ERROR',ele?(ele.textContent||'').trim().slice(0,150):'');}"
    # TEXT CHANGE on pre-existing template node → SUCCESS/ERROR (Driffle pattern)
    "else if(s_txt){fin('SUCCESS',s_txt.slice(0,150));}"
    "else if(e_txt){fin('ERROR',e_txt.slice(0,150));}"
    "else if(n>=40){fin('NO_SIGNAL','');}"
    "},200);"
    "});})()"
)

# Selectize UI probes — S02-safe (read-only). Locate the .selectize-input rect
# (for trusted click-to-open) and the .option[data-value="X"] rect (for
# trusted click-to-select once the dropdown is visible). The wrapper is found
# via `sel.selectize.$wrapper[0]` (Selectize's own jQuery accessor) with a DOM
# sibling walk as fallback.
_SELECTIZE_INPUT_RECT_JS = (
    "JSON.stringify((function(){"
    "var name=%s;"
    "var sel=document.querySelector('select[name=\"'+name+'\"]');"
    "if(!sel)return {ok:false,reason:'no_select'};"
    "var wrap=null;"
    "if(sel.selectize&&sel.selectize.$wrapper&&sel.selectize.$wrapper[0])"
    "{wrap=sel.selectize.$wrapper[0];}else{"
    "var nx=sel.nextElementSibling;while(nx){"
    "if(nx.classList&&nx.classList.contains('selectize-control')){wrap=nx;break;}"
    "nx=nx.nextElementSibling;}}"
    "if(!wrap)return {ok:false,reason:'no_wrapper'};"
    "var inp=wrap.querySelector('.selectize-input');"
    "if(!inp)return {ok:false,reason:'no_input'};"
    "var r=inp.getBoundingClientRect();"
    "return {ok:true,x:r.x,y:r.y,width:r.width,height:r.height,"
    "top:r.top,left:r.left,bottom:r.bottom,right:r.right,"
    "viewport:{w:window.innerWidth,h:window.innerHeight}};"
    "})())"
)

_SELECTIZE_OPTION_RECT_JS = (
    "JSON.stringify((function(){"
    "var name=%s,val=%s;"
    "var sel=document.querySelector('select[name=\"'+name+'\"]');"
    "if(!sel)return {ok:false,reason:'no_select'};"
    "var wrap=null;"
    "if(sel.selectize&&sel.selectize.$wrapper&&sel.selectize.$wrapper[0])"
    "{wrap=sel.selectize.$wrapper[0];}else{"
    "var nx=sel.nextElementSibling;while(nx){"
    "if(nx.classList&&nx.classList.contains('selectize-control')){wrap=nx;break;}"
    "nx=nx.nextElementSibling;}}"
    "if(!wrap)return {ok:false,reason:'no_wrapper'};"
    "var dd=wrap.querySelector('.selectize-dropdown');"
    "if(!dd||getComputedStyle(dd).display==='none')"
    "return {ok:false,reason:'dropdown_not_open'};"
    "var opt=wrap.querySelector('.selectize-dropdown-content [data-value=\"'+val+'\"]');"
    "if(!opt)return {ok:false,reason:'no_option'};"
    "var r=opt.getBoundingClientRect();"
    "return {ok:true,x:r.x,y:r.y,width:r.width,height:r.height,"
    "top:r.top,left:r.left,bottom:r.bottom,right:r.right,"
    "viewport:{w:window.innerWidth,h:window.innerHeight}};"
    "})())"
)

_SELECTIZE_READBACK_JS = (
    "JSON.stringify((function(){"
    "var name=%s;"
    "var sel=document.querySelector('select[name=\"'+name+'\"]');"
    "if(!sel)return {ok:false};"
    "var stz=sel.selectize?String(sel.selectize.getValue()):null;"
    "return {ok:true,select_value:sel.value||'',selectize_value:stz,"
    "validity_valid:sel.validity?sel.validity.valid:null};"
    "})())"
)

# Emergency tap cleanup used if prep succeeded but the trusted click could not
# be dispatched (rare — e.g. NO_ELEMENT). Restores fetch/XHR to their originals
# so the tab is not left with our wrappers.
_TRUSTED_CLEANUP_JS = (
    "(function(){var o=window.__s18orig;if(o){window.fetch=o.f;"
    "XMLHttpRequest.prototype.open=o.o;XMLHttpRequest.prototype.send=o.s;"
    "delete window.__s18orig;}delete window.__s18taps;return true;})()"
)


class WriteSubmitSession(SubmitSession):
    """SubmitSession + the single mutating op. Instantiated ONLY under ``--submit``.

    ``fill_and_create`` (native/dispatch) and ``fill_then_click_trusted`` (Chantier
    n°1 trusted) are the only methods that write: they set region/edition on the
    verified select names and cause a click on the visible "Create offer" button.
    No direct XHR, no ``form.submit()`` (S09). Three click_modes are supported:

    - ``native``: DOM ``b.click()`` — default, was the original path.
    - ``dispatch``: a MouseEvent sequence dispatched on the button ONLY (S09
      derogation authorized by Romain 2026-07-03 after native was proven not
      to persist on Driffle). ``event.isTrusted`` is false — Driffle ignores it.
    - ``trusted`` (Chantier n°1, 2026-07-03): trusted click via CDP
      ``Input.dispatchMouseEvent`` at the button's viewport center — `isTrusted`
      is true, indistinguishable from a real mouse. No form.submit(), no XHR,
      no keyboard synthesis. If the button is off-viewport, one
      ``Input.synthesizeScrollGesture`` (mouse source) precedes the click with a
      500 ms settle. Post-save (offer gone from refreshed pending feed) remains
      the ONLY success proof in every mode.
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

    # ------------------------------------------------------------------
    # Chantier n°1 (2026-07-03) — trusted click via CDP `Input` domain.
    # ------------------------------------------------------------------
    def _read_rect(self, selector: str) -> dict[str, Any]:
        """Read the target's viewport rect + window inner dims. Read-only."""

        raw = self.evaluate_readonly(_RECT_JS % json.dumps(selector))
        return json.loads(raw) if raw else {"ok": False}

    def _trusted_click_at_rect(self, rect: dict[str, Any]) -> dict[str, Any]:
        """Fire a trusted mousedown → dwell → mouseup at the rect's center.

        ``rect`` must have ``x``, ``y``, ``width``, ``height`` (viewport coords).
        Caller must ensure the rect is in the current viewport. Returns
        ``{cx, cy, delay_ms}``.
        """

        cx = rect["x"] + rect["width"] / 2
        cy = rect["y"] + rect["height"] / 2
        self._cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy})
        self._cmd(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": cx, "y": cy,
             "button": "left", "buttons": 1, "clickCount": 1},
        )
        delay_ms = random.randint(40, 90)
        time.sleep(delay_ms / 1000.0)
        self._cmd(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": cx, "y": cy,
             "button": "left", "buttons": 0, "clickCount": 1},
        )
        return {"cx": cx, "cy": cy, "delay_ms": delay_ms}

    def click_trusted_at_element(
        self, selector: str = "#TB_ajaxContent .button-primary",
    ) -> dict[str, Any]:
        """Trusted click at the element's viewport center via CDP `Input.*`.

        Reads the rect via ``_read_rect``. If the element is outside the viewport,
        issues one ``Input.synthesizeScrollGesture`` (mouse source, speed 800) to
        bring its center around 40 % of viewport height, waits 500 ms, re-reads
        the rect. Then fires the trusted mouse sequence at the center.
        Events land in Chrome with ``isTrusted:true``.

        Returns a diag dict: selector, rect, viewport, scrolled, scroll_y_distance
        (if scrolled), rect_after_scroll (if scrolled), click_x, click_y, delay_ms,
        status ('CLICKED' | 'NO_ELEMENT' | 'NO_ELEMENT_AFTER_SCROLL'), mode='trusted'.
        """

        rect = self._read_rect(selector)
        if not rect.get("ok"):
            return {"status": "NO_ELEMENT", "selector": selector, "mode": "trusted"}

        vp = rect["viewport"]
        diag: dict[str, Any] = {
            "selector": selector,
            "mode": "trusted",
            "viewport": vp,
            "rect": {"x": rect["x"], "y": rect["y"], "w": rect["width"], "h": rect["height"]},
            "scrolled": False,
        }

        needs_scroll = rect["top"] < 0 or rect["bottom"] > vp["h"]
        if needs_scroll:
            target_y = vp["h"] * 0.4
            current_y = (rect["top"] + rect["bottom"]) / 2
            y_distance = int(current_y - target_y)
            self._cmd(
                "Input.synthesizeScrollGesture",
                {
                    "x": vp["w"] // 2,
                    "y": vp["h"] // 2,
                    "xDistance": 0,
                    "yDistance": y_distance,
                    "gestureSourceType": "mouse",
                    "speed": 800,
                },
            )
            time.sleep(0.5)
            rect = self._read_rect(selector)
            diag["scrolled"] = True
            diag["scroll_y_distance"] = y_distance
            if rect.get("ok"):
                diag["rect_after_scroll"] = {
                    "x": rect["x"], "y": rect["y"], "w": rect["width"], "h": rect["height"],
                }
            else:
                diag["status"] = "NO_ELEMENT_AFTER_SCROLL"
                return diag

        click = self._trusted_click_at_rect(rect)
        diag["click_x"] = click["cx"]
        diag["click_y"] = click["cy"]
        diag["delay_ms"] = click["delay_ms"]
        diag["status"] = "CLICKED"
        return diag

    def select_via_trusted(self, select_name: str, value_id: str) -> dict[str, Any]:
        """Selectize humanisé (Chantier n°1 extension, 2026-07-03).

        1. Read the ``.selectize-input`` rect for the given select name (S02-safe).
        2. Trusted CDP click on it — the dropdown opens naturally.
        3. Wait 250 ms for dropdown render + option layout.
        4. Read the ``[data-value="{value_id}"]`` option rect (S02-safe).
        5. Trusted CDP click on it — Selectize applies the value, plugin's own
           listeners fire.
        6. Wait 200 ms for state settle.
        7. Read back ``select.value`` + ``select.selectize.getValue()`` +
           ``select.validity.valid``.

        Returns a diag dict: select_name, value_id, status
        ('SELECTED' | 'NO_SELECTIZE_INPUT' | 'NO_OPTION'), input_rect,
        option_rect, open_click, option_click, readback.
        """

        input_raw = self.evaluate_readonly(
            _SELECTIZE_INPUT_RECT_JS % json.dumps(select_name)
        )
        input_rect = json.loads(input_raw) if input_raw else {"ok": False}
        diag: dict[str, Any] = {"select_name": select_name, "value_id": str(value_id)}
        if not input_rect.get("ok"):
            diag["status"] = "NO_SELECTIZE_INPUT"
            diag["reason"] = input_rect.get("reason")
            return diag

        diag["input_rect"] = {
            "x": input_rect["x"], "y": input_rect["y"],
            "w": input_rect["width"], "h": input_rect["height"],
        }
        diag["open_click"] = self._trusted_click_at_rect(input_rect)
        time.sleep(0.25)  # dropdown render + option layout

        option_raw = self.evaluate_readonly(
            _SELECTIZE_OPTION_RECT_JS
            % (json.dumps(select_name), json.dumps(str(value_id)))
        )
        option_rect = json.loads(option_raw) if option_raw else {"ok": False}
        if not option_rect.get("ok"):
            diag["status"] = "NO_OPTION"
            diag["reason"] = option_rect.get("reason")
            return diag

        diag["option_rect"] = {
            "x": option_rect["x"], "y": option_rect["y"],
            "w": option_rect["width"], "h": option_rect["height"],
        }
        diag["option_click"] = self._trusted_click_at_rect(option_rect)
        time.sleep(0.2)  # dropdown close + state settle

        readback_raw = self.evaluate_readonly(
            _SELECTIZE_READBACK_JS % json.dumps(select_name)
        )
        diag["readback"] = json.loads(readback_raw) if readback_raw else {"ok": False}
        diag["status"] = "SELECTED"
        return diag

    def fill_then_click_trusted(
        self,
        region_select: str,
        region_id: str,
        edition_select: str,
        edition_id: str,
    ) -> dict[str, Any]:
        """Trusted-click variant of ``fill_and_create`` — Selectize humanisé
        (Chantier n°1 extension, 2026-07-03):

        1. Prep JS: install network taps + record pre-existing signal state
           (counts + text snapshots) + button visibility. NO setValue.
        2. ``select_via_trusted(region_select, region_id)``: trusted CDP click on
           Selectize UI (open + pick option). Selectize fires its own events.
        3. ``select_via_trusted(edition_select, edition_id)``: same.
        4. ``click_trusted_at_element("#TB_ajaxContent .button-primary")``:
           trusted CDP click on the submit button center.
        5. Poll JS: accept either a NEW [data-success]/[data-error] node OR a
           TEXT CHANGE on the existing template node (Driffle's actual pattern),
           report captured requests, restore taps.

        Post-save (offer gone from refreshed pending) remains the ONLY success
        proof — this method's ``status`` is diagnostic only.
        """

        prep = self._evaluate(
            _TRUSTED_PREP_JS
            % (json.dumps(region_select), json.dumps(edition_select))
        )
        if not isinstance(prep, dict) or prep.get("status") != "PREPARED":
            return prep if isinstance(prep, dict) else {"status": "NO_RESULT", "raw": prep}

        prep["click_mode"] = "trusted"
        prep["region_target"] = str(region_id)
        prep["edition_target"] = str(edition_id)

        region_pick = self.select_via_trusted(region_select, str(region_id))
        prep["region_pick"] = region_pick
        if region_pick.get("status") != "SELECTED":
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "NO_REGION_PICK"
            return prep

        edition_pick = self.select_via_trusted(edition_select, str(edition_id))
        prep["edition_pick"] = edition_pick
        if edition_pick.get("status") != "SELECTED":
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "NO_EDITION_PICK"
            return prep

        prep["region_set"] = str(
            (region_pick.get("readback") or {}).get("selectize_value", "")
        )
        prep["edition_set"] = str(
            (edition_pick.get("readback") or {}).get("selectize_value", "")
        )

        click = self.click_trusted_at_element("#TB_ajaxContent .button-primary")
        prep["click"] = click
        if click.get("status") != "CLICKED":
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "NO_TRUSTED_CLICK"
            return prep

        poll = self._evaluate(_TRUSTED_POLL_JS)
        if isinstance(poll, dict):
            prep.update(poll)
        return prep
