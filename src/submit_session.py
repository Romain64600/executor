"""Interactive CDP sessions for the submitter — dry-run AND write layers.

Two classes, one strict boundary:

- ``SubmitSession`` (dry-run): read + open-modal + read-only probes only. It can
  list a page's offer ids, open an offer's modal, read the modal context /
  validity / targets field, enumerate Selectize options, and detect the WP login
  bounce. It has **no method that fills a form or clicks "Create offer"**.
  Opening a modal or a dropdown is a harmless UI action (no DB write happens
  until "Create offer"), which is why it is allowed for the rehearsal.
- ``WriteSubmitSession`` (the write layer): adds the single mutating flow —
  fill region/edition/targets and click the visible "Create offer" button
  (trusted CDP path by default; native/dispatch kept as documented
  diagnostics). It is instantiated ONLY under ``--submit``
  (``scripts/05_submit.py``), behind the validation file and the green
  authoritative gate. No ``form.submit()``, no direct XHR (S09); post-save
  (offer gone from the refreshed pending feed) stays the only success proof.

Modal shapes (2026-09-14, ``modal_context()['modal_shape']``):

- ``targets_v2`` — the CURRENT AKS feed tool: region and edition are taken PER
  TARGET PAGE. Row 0 = ``input[name="offer[targets][0][target]"]`` (required,
  ``pattern="(\\d+)|(https?://.+)"``, ``data-target-input``) + the NOT-required
  Selectize overrides ``select[name="offer[targets][0][region]"]`` /
  ``[edition]`` (``data-target-override``); the button right after the target
  input ADDS a row (Romain, 2026-09-14). Written by ``fill_targets_v2_trusted``.
- ``targets_v1`` — the historical single ``input[name="offer[targets][]"]``
  chip field, kept for the old fallback (``fill_then_click_trusted``).
- ``unknown`` — neither: the submitter fails closed, nothing is filled.

The modal ``<form>`` has ``method=get`` and no ``action``: an Enter keypress
inside one of its text inputs would SUBMIT THE FORM natively — an uncontrolled
write. No method of this module ever presses Enter in the modal.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any

from src.cdp_session import ReadOnlyCdpSession
from src.extractor import FEED_MARKER_JS_FIELDS

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

# id + the stable row identity (merchant url, title) + the row details the
# rules require verifying before the modal (price, store — audit P1,
# 2026-07-08). AKS re-imports re-id EVERY row (K4G 2026-07-08: 0/212 ids
# survived 74 minutes), so approved ids go stale while the merchant URL keeps
# identifying the same offer.
_PAGE_ROWS_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll('tr[data-offer]'))"
    ".map(function(e){try{var d=JSON.parse(e.getAttribute('data-offer'));"
    "return {id:String(d.id),url:String(d.url||''),name:String(d.name||''),"
    "price:d.price==null?'':String(d.price),"
    "store_id:d.storeId==null?'':String(d.storeId)};}"
    "catch(x){return null;}}).filter(Boolean))"
)

# Read-only readiness probe of the feed page's scripts (2026-09-10): the create-offer
# click only works once the page's JS has bound the ThickBox handler (``tb_show``). A
# click fired before that is silently lost — "OPENED" with no `#TB_ajaxContent` ever.
_PAGE_SCRIPTS_JS = (
    "JSON.stringify({ready:String(document.readyState),tb:typeof window.tb_show,"
    "jq:typeof window.jQuery})"
)

# Read-only modal context: the select names (S17) + the MODAL SHAPE (2026-09-14).
# ``targets_v2`` when row 0's three controls all exist (the target input and both
# override selects), ``targets_v1`` when the old ``offer[targets][]`` input exists,
# else ``unknown``. v2 wins if both are present. ``modal_shape_detail`` says which
# of the four probes hit so an ``unknown`` shape is diagnosable from the plan.
_MODAL_CTX_JS = (
    "JSON.stringify((function(){var c=document.querySelector('#TB_ajaxContent');"
    "if(!c){return {ok:false,select_names:[],modal_shape:'unknown'};}"
    "var t0=!!c.querySelector('input[name=\"offer[targets][0][target]\"]');"
    "var r0=!!c.querySelector('select[name=\"offer[targets][0][region]\"]');"
    "var e0=!!c.querySelector('select[name=\"offer[targets][0][edition]\"]');"
    "var v1=!!c.querySelector('input[name=\"offer[targets][]\"]');"
    "var shape=(t0&&r0&&e0)?'targets_v2':(v1?'targets_v1':'unknown');"
    "return {ok:true,select_names:Array.from(c.querySelectorAll('select'))"
    ".map(function(s){return s.name;}),modal_shape:shape,"
    "modal_shape_detail:{v2_target0:t0,v2_region0:r0,v2_edition0:e0,v1_input:v1}};})())"
)

MODAL_SHAPE_V1 = "targets_v1"
MODAL_SHAPE_V2 = "targets_v2"
MODAL_SHAPE_UNKNOWN = "unknown"

# Deterministic feed-page markers — the SAME probe fields the extractor
# trusts, imported verbatim (AR3 partial, audit 2026-07-17) so the two
# blank-page classifications can never drift apart: the pagination nav is the
# only element exposing the feed's real page count, and past-the-end pages
# render the same chrome with 0 rows. `href` (submitter-only) lets the
# scanner verify the browser actually landed on the page it navigated to
# (a wedged navigation re-serves the previous DOM — SC6). Read-only.
_FEED_STATE_JS = (
    "JSON.stringify({"
    + FEED_MARKER_JS_FIELDS +
    ",href: String(location.href)"
    "})"
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

# Read-only validity probe (S02-safe). Finds the <form> that owns the modal
# "Create offer" button and reports, per constraint-validated control
# (``willValidate``), whether it is currently valid — WITHOUT calling
# ``form.checkValidity()`` (which would fire ``invalid`` events) and WITHOUT
# reading any field value. This answers the S18 question deterministically: a
# trusted click on a submit button whose form is invalid fires ZERO network
# requests (the browser blocks the submit) — that is HTML5 validation, not
# server-side bot detection. ``invalid_required`` lists the offending controls
# by name so the report says exactly which field to fill.
_FORM_VALIDITY_JS = (
    "JSON.stringify((function(){"
    "var b=document.querySelector('#TB_ajaxContent .button-primary');"
    "var form=b?b.closest('form'):null;"
    "if(!form)return {ok:false,reason:'no_form'};"
    "var inputs=form.querySelectorAll('input,select,textarea');"
    "var invalid=[],checked=0;"
    "for(var i=0;i<inputs.length;i++){var el=inputs[i];"
    "if(!el.willValidate)continue;checked++;"
    "var v=el.validity;if(v.valid)continue;"
    "invalid.push({name:el.name||null,type:el.type||null,"
    "required:!!el.required,visible:el.offsetParent!==null,"
    "valueMissing:v.valueMissing,typeMismatch:v.typeMismatch,"
    "patternMismatch:v.patternMismatch,badInput:v.badInput});}"
    "return {ok:true,form_valid:invalid.length===0,checked:checked,"
    "invalid_required:invalid};"
    "})())"
)

# Read-only forensic probe of the modal's ``offer[targets][]`` control(s) (S18,
# 2026-07-06). The form-validity gate proved `offer[targets][]` is the one
# required field our fill path never populates; this dumps everything static we
# need to learn what value it expects — WITHOUT reading the value itself
# (value_len only) and WITHOUT any mutation. Captures, for every control whose
# name contains "targets": tag/type/id/class, required/willValidate/validity,
# placeholder / list / maxlength / pattern / autocomplete / role / aria-*, all
# ``data-*`` attrs, the associated <label> text, the parent chain + next
# siblings (to reveal a wrapping tag/autocomplete widget), the referenced
# <datalist> options if any, and — if the control is a <select> — its option
# vocabulary. S02-safe: no ``.value=``, ``.click(``, ``fetch(``, setValue, etc.
_TARGETS_PROBE_JS = (
    "JSON.stringify((function(){"
    "function dataAttrs(el){var o={};for(var i=0;i<el.attributes.length;i++){"
    "var a=el.attributes[i];if(a.name.indexOf('data-')!==0)continue;"
    "o[a.name]=String(a.value).slice(0,120);}return o;}"
    "function labelFor(el,form){var lbl=null;"
    "if(el.id){var l=form.querySelector('label[for=\"'+el.id+'\"]');if(l)lbl=l;}"
    "if(!lbl){var p=el.closest('label');if(p)lbl=p;}"
    "if(!lbl){var pr=el.previousElementSibling,d=0;"
    "while(pr&&d<4){if(pr.tagName==='LABEL'||pr.tagName==='LEGEND'){lbl=pr;break;}"
    "pr=pr.previousElementSibling;d++;}}"
    "return lbl?(lbl.textContent||'').trim().slice(0,80):null;}"
    "function chain(el,fn){var out=[],c=fn(el),d=0;"
    "while(c&&d<4){var s=c.tagName.toLowerCase();"
    "if(c.className&&typeof c.className==='string')"
    "s+='.'+c.className.trim().split(/\\s+/).slice(0,3).join('.');"
    "out.push(s);c=fn(c);d++;}return out;}"
    "var content=document.querySelector('#TB_ajaxContent');"
    "if(!content)return {ok:false,reason:'no_modal'};"
    "var form=content.querySelector('form')||content;"
    "var all=form.querySelectorAll('input,select,textarea');"
    "var targets=[];"
    "for(var i=0;i<all.length;i++){var el=all[i];"
    "if((el.name||'').indexOf('targets')<0)continue;"
    "var rec={tag:el.tagName,type:el.type||null,name:el.name||null,id:el.id||null,"
    "klass:el.className||null,required:!!el.required,willValidate:!!el.willValidate,"
    "value_len:(el.value||'').length,visible:el.offsetParent!==null,"
    "placeholder:el.getAttribute('placeholder'),list_attr:el.getAttribute('list'),"
    "maxlength:el.getAttribute('maxlength'),pattern:el.getAttribute('pattern'),"
    "autocomplete:el.getAttribute('autocomplete'),role:el.getAttribute('role'),"
    "aria_label:el.getAttribute('aria-label'),"
    "aria_describedby:el.getAttribute('aria-describedby'),"
    "data_attrs:dataAttrs(el),label:labelFor(el,form),"
    "parents:chain(el,function(x){return x.parentElement;}),"
    "next_sibs:chain(el,function(x){return x.nextElementSibling;})};"
    # Modal v2 (2026-09-14): describe the BUTTON right after a target input. Canary
    # 2 (2026-09-15) proved it is the row's REMOVE button (`data-remove-target`,
    # "×"), NOT the add button — kept as evidence; the add button is read from
    # `inspection.modal_buttons` (`_MODAL_BUTTONS_JS`) and located by
    # `_ADD_ROW_BUTTON_PROBE_JS`.
    "var nb=el.nextElementSibling;"
    "if(nb&&nb.tagName==='BUTTON'){rec.next_sib_button={tag:nb.tagName,"
    "type_prop:String(nb.type||''),type_attr:nb.getAttribute('type'),"
    "klass:nb.className||null,data_attrs:dataAttrs(nb),"
    "text:(nb.textContent||'').trim().slice(0,40)};}"
    "if(rec.list_attr){var dl=document.getElementById(rec.list_attr);"
    "if(dl){rec.datalist=Array.prototype.slice.call(dl.querySelectorAll('option'))"
    ".slice(0,50).map(function(o){return {value:o.value,"
    "label:(o.textContent||o.label||'').trim().slice(0,60)};});}}"
    "if(el.tagName==='SELECT'){rec.has_selectize=!!el.selectize;"
    "rec.options=Array.prototype.slice.call(el.options).slice(0,50)"
    ".map(function(o){return {value:o.value,label:(o.textContent||'').trim().slice(0,60)};});}"
    "targets.push(rec);}"
    "return {ok:true,count:targets.length,targets:targets};"
    "})())"
)

# Read-only enumeration of a Selectize select's FULL option set. The earlier
# option-rect diagnostic capped `$dropdown_content` at 20 entries, which hid the
# real editions: the product's options load into the dropdown (the bare <select>
# is empty) and sort the "+ N …" add-ons before "Standard", so a 20-cap dropped
# it — and the wanted id is product-scoped, not master-catalog "1". This opens
# the dropdown (UI-only, no data written), dumps EVERY rendered option
# (data_value + text), the master `selectize.options` map, and the <select>'s own
# <option>s, then closes it. Used to build the label→product-id mapping.
_SELECT_OPTIONS_PROBE_JS = (
    "(function(){return new Promise(function(resolve){"
    "var name=%s;"
    "var sel=document.querySelector('select[name=\"'+name+'\"]');"
    "if(!sel){resolve({ok:false,reason:'no_select'});return;}"
    "if(!sel.selectize){resolve({ok:false,reason:'no_selectize'});return;}"
    "var stz=sel.selectize;var before=String(stz.getValue());"
    "try{stz.open();}catch(e){}"
    "setTimeout(function(){"
    "var dc=(stz.$dropdown_content&&stz.$dropdown_content[0])||null;"
    "var rendered=[];"
    "if(dc){var all=dc.querySelectorAll('[data-value]');"
    "for(var i=0;i<all.length;i++){rendered.push({data_value:all[i].getAttribute('data-value'),"
    "text:(all[i].textContent||'').trim().slice(0,60)});}}"
    "var master=[];if(stz.options){for(var k in stz.options){"
    "if(stz.options.hasOwnProperty(k)){master.push({key:k,"
    "text:(stz.options[k]&&(stz.options[k].text||stz.options[k].label))||null});}}}"
    "var selOpts=[];for(var j=0;j<sel.options.length;j++){"
    "selOpts.push({value:sel.options[j].value,text:(sel.options[j].text||'').trim().slice(0,60)});}"
    "try{stz.close();}catch(e){}"
    "resolve({ok:true,select_name:name,current_value:before,"
    "rendered_count:rendered.length,rendered_options:rendered,"
    "select_option_count:sel.options.length,select_options:selOpts,"
    "master_count:master.length,master_options:master});"
    "},600);"
    "});})()"
)

_IS_LOGIN_JS = "!!document.querySelector('#loginform') || /wp-login/.test(location.href)"

# Read-only: the bulk "Move to list" <select> options (value = target listId,
# text = "Move to <label>"). The mover resolves target_list_label -> id LIVE
# from these (ids drift — docs/AKS_LISTS.md). No mutation.
_LIST_OPTIONS_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll("
    "'select[name=\"bulk[list]\"] option')).map(function(o){"
    "return {value:String(o.value||''),text:(o.textContent||'').trim().slice(0,80)};}))"
)

# Read-only: is <offer_id>'s row selectable on THIS page? (its bulk checkbox +
# the bulk form both present). The move only ever acts on a row it can see.
_BULK_ROW_PRESENT_JS = (
    "JSON.stringify((function(){var id=%s;"
    "var cb=document.querySelector('input[name=\"bulk[item][]\"][value=\"'+id+'\"]');"
    "var form=document.querySelector('form[data-bulk-form]');"
    "return {checkbox:!!cb,bulk_form:!!form};})())"
)

# Read-only: after the trusted checkbox click, is the offer registered in the
# bulk form (the hidden bulk[item][] the handler injects) and what is bulk[list]?
_BULK_REGISTERED_JS = (
    "JSON.stringify((function(){var id=%s;"
    "var form=document.querySelector('form[data-bulk-form]');"
    "if(!form)return {registered:false,reason:'no_form'};"
    "var hid=form.querySelector('input[name=\"bulk[item][]\"][value=\"'+id+'\"]');"
    "var sel=form.querySelector('select[name=\"bulk[list]\"]');"
    "return {registered:!!hid,bulk_list_value:sel?String(sel.value||''):null};})())"
)

# Write (via _evaluate, unguarded): register the offer by injecting the hidden
# bulk[item][] the checkbox change handler would add. Deterministic — a trusted
# checkbox click proved fragile on paginated feed pages (canary 2026-07-22:
# click=CLICKED but the async handler never injected the hidden). The native
# Apply POST serializes the form, so this injected hidden is sent exactly like a
# real tick. Idempotent (never duplicates the input).
_INJECT_BULK_ITEM_JS = (
    "(function(){var id=%s;"
    "var form=document.querySelector('form[data-bulk-form]');"
    "if(!form)return JSON.stringify({registered:false,reason:'no_form'});"
    "if(!form.querySelector('input[name=\"bulk[item][]\"][value=\"'+id+'\"]')){"
    "var inp=document.createElement('input');inp.type='hidden';"
    "inp.name='bulk[item][]';inp.value=id;form.appendChild(inp);}"
    "var sel=form.querySelector('select[name=\"bulk[list]\"]');"
    "return JSON.stringify({registered:!!form.querySelector("
    "'input[name=\"bulk[item][]\"][value=\"'+id+'\"]'),"
    "bulk_list_value:sel?String(sel.value||''):null});})()"
)

# Write (via _evaluate, unguarded): set bulk[list] to <target_list_id>. The
# native Apply submit reads it at click time.
_SET_BULK_LIST_JS = (
    "(function(){var t=%s;"
    "var sel=document.querySelector('form[data-bulk-form] select[name=\"bulk[list]\"]');"
    "if(!sel)return 'no_select';"
    "for(var i=0;i<sel.options.length;i++){if(sel.options[i].value===t){sel.selectedIndex=i;}}"
    "sel.value=t;return String(sel.value);})()"
)

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


# CDP command timeout for the SUBMIT sessions (2026-09-10): the read-only default is 20 s,
# but the AKS admin page can hang its JS thread / a navigation for 20-30 s under backend
# slowness (the same spikes as the 25 s site search). Twice in ~100 offers a
# `Runtime.evaluate` hit the 20 s wall right after a successful Create → the post-save proof
# died → offer marked UNKNOWN although created (verified read-only in the feed). 45 s only
# delays the detection of a genuinely dead browser; the fail-closed handling is unchanged.
SUBMIT_CDP_CMD_TIMEOUT_S = 45


class SubmitSession(ReadOnlyCdpSession):
    """Read + open-modal only. No fill, no create."""

    def __init__(self, endpoint: str, *, connect_timeout: int = 10,
                 cmd_timeout: int = SUBMIT_CDP_CMD_TIMEOUT_S) -> None:
        super().__init__(endpoint, connect_timeout=connect_timeout, cmd_timeout=cmd_timeout)

    def is_login_page(self) -> bool:
        return bool(self.evaluate_readonly(_IS_LOGIN_JS))

    def page_offer_ids(self) -> list[str]:
        raw = self.evaluate_readonly(_PAGE_IDS_JS)
        if not raw:
            return []
        return list(json.loads(raw))

    def page_offer_rows(self) -> list[dict[str, str]]:
        """Current page's rows as ``{id, url, name}`` (read-only)."""
        raw = self.evaluate_readonly(_PAGE_ROWS_JS)
        if not raw:
            return []
        return list(json.loads(raw))

    def list_options(self) -> list[dict[str, str]]:
        """The bulk "Move to list" <select> options ``[{value, text}]`` (read-only).

        The mover resolves a target list LABEL -> id from these at write time —
        the ids drift, so this is never read from a stored table (AKS_LISTS.md)."""

        raw = self.evaluate_readonly(_LIST_OPTIONS_JS)
        return list(json.loads(raw)) if raw else []

    def bulk_row_present(self, offer_id: str) -> dict[str, bool]:
        """Is ``offer_id``'s bulk checkbox (and the bulk form) on THIS page?"""

        raw = self.evaluate_readonly(_BULK_ROW_PRESENT_JS % json.dumps(str(offer_id)))
        return json.loads(raw) if raw else {"checkbox": False, "bulk_form": False}

    def feed_page_state(self) -> dict[str, Any]:
        """Deterministic feed-page markers ``{feed_ui, nav_max, is_login, href}``.

        The submitter's feed scans use these to PROVE a blank page is a real
        end-of-feed (past-the-end / empty queue) instead of accepting any
        0-row render at face value — the extractor's discipline, carried over
        to the post-save disappearance proof (audit 2026-07-17, SC2/FC1).
        An unreadable result returns ``{}``, which the scanner treats as an
        anomaly, never as an empty feed."""

        raw = self.evaluate_readonly(_FEED_STATE_JS)
        return json.loads(raw) if raw else {}

    def open_offer_modal(self, offer_id: str) -> str:
        # Uses the raw evaluator: this is the one explicitly-allowed interaction.
        return str(self._evaluate(_OPEN_MODAL_JS % json.dumps(str(offer_id))))

    def modal_context(self) -> dict[str, Any]:
        raw = self.evaluate_readonly(_MODAL_CTX_JS)
        return json.loads(raw) if raw else {"ok": False, "select_names": []}

    def page_scripts_state(self) -> dict[str, Any]:
        """Read-only: ``{ready, tb, jq}`` — document.readyState and whether the ThickBox
        opener (``tb_show``) / jQuery are defined yet. The submitter waits for
        ``ready == 'complete'`` and ``tb == 'function'`` before the create-offer click."""

        raw = self.evaluate_readonly(_PAGE_SCRIPTS_JS)
        return json.loads(raw) if raw else {"ready": None, "tb": None, "jq": None}

    def inspect_modal_dom(self) -> dict[str, Any]:
        """Read-only DOM inspection of the currently-open modal (S02).

        Returns a diag dict describing the S09 `.button-primary` target (tag /
        type / id / class / href / data-*), its parent `<form>` if any (action /
        method / onsubmit_attr), other forms in the modal, `[data-success]` /
        `[data-error]` node locations (in modal + doc counts), `#TB_window`
        visibility, and the selects' current state. No clicks, no writes.
        """

        raw = self.evaluate_readonly(_INSPECT_MODAL_JS)
        if not raw:
            return {"modal_ok": False}
        result = json.loads(raw)
        # Canary 2 (2026-09-15): the add-row locator was wrong once because the
        # inspection never listed the modal's buttons — every --inspect now
        # carries them (``inspection.modal_buttons``), read-only.
        result["modal_buttons"] = self.probe_modal_buttons()
        return result

    def probe_modal_buttons(self) -> dict[str, Any]:
        """Read-only dump of every ``<button>`` / ``<a role=button>`` in the open
        modal (``_MODAL_BUTTONS_JS``): ``{ok, count, row_count, container,
        buttons: [{tag, type_prop, type_attr, id, klass, href, role, text,
        data_attrs, visible, in_form, in_targets_container, in_row, path}]}`` —
        the way to READ the real add-row button before a multi-target write
        (canary 2, 2026-09-15: the sibling of the target input is the REMOVE
        button). ``{ok: False, reason, buttons: []}`` without a modal / result."""

        raw = self.evaluate_readonly(_MODAL_BUTTONS_JS)
        return json.loads(raw) if raw else {"ok": False, "reason": "no_result", "buttons": []}

    def form_validity(self) -> dict[str, Any]:
        """Read-only HTML5 validity summary of the modal's "Create offer" form.

        Returns ``{ok, form_valid, checked, invalid_required:[{name, ...}]}`` or
        ``{ok: False, reason}`` when the form can't be located. Never reads a
        field value, never calls ``checkValidity`` (no ``invalid`` events).
        """

        raw = self.evaluate_readonly(_FORM_VALIDITY_JS)
        return json.loads(raw) if raw else {"ok": False, "reason": "no_result"}

    def probe_targets_field(self) -> dict[str, Any]:
        """Read-only forensic dump of the modal's ``offer[targets][]`` control(s).

        Returns ``{ok, count, targets:[{tag, type, placeholder, label, list_attr,
        datalist, data_attrs, parents, next_sibs, ...}]}`` — everything static
        needed to learn what value the field expects, without reading its value
        (``value_len`` only) and without any mutation. ``{ok: False, reason}`` if
        the modal/field can't be located.
        """

        raw = self.evaluate_readonly(_TARGETS_PROBE_JS)
        return json.loads(raw) if raw else {"ok": False, "reason": "no_result"}

    def probe_select_options(self, select_name: str) -> dict[str, Any]:
        """Read-only enumeration of a Selectize select's FULL option set.

        Opens the dropdown (UI-only, no fill, no create), dumps every rendered
        option (``data_value`` + ``text``), the master ``selectize.options`` map,
        and the ``<select>``'s own ``<option>``s, then closes it. Used to learn
        the real product-scoped editions/regions and the label→id mapping.
        Returns ``{ok, select_name, current_value, rendered_options, ...}`` or
        ``{ok: False, reason}``. Uses the raw evaluator — opening a dropdown is an
        explicitly-allowed, non-persisting interaction (same class as
        ``open_offer_modal``).
        """

        result = self._evaluate(_SELECT_OPTIONS_PROBE_JS % json.dumps(select_name))
        return result if isinstance(result, dict) else {"ok": False, "reason": "no_result"}


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
    "if(!sel.selectize)return {ok:false,reason:'no_selectize'};"
    # Prefer Selectize's own accessor for THIS select's active dropdown. Falls
    # back to a wrapper query only if the accessor isn't populated. NO
    # document-wide fallback (too permissive — picks up unrelated data-value=X
    # elements elsewhere in the page).
    "var opt=null;var opt_source='';var is_open=!!sel.selectize.isOpen;"
    "if(sel.selectize.$dropdown_content&&sel.selectize.$dropdown_content[0]){"
    "opt=sel.selectize.$dropdown_content[0].querySelector('[data-value=\"'+val+'\"]');"
    "if(opt)opt_source='$dropdown_content';}"
    "if(!opt){var wrap=(sel.selectize.$wrapper&&sel.selectize.$wrapper[0])||null;"
    "if(!wrap){var nx=sel.nextElementSibling;while(nx){"
    "if(nx.classList&&nx.classList.contains('selectize-control')){wrap=nx;break;}"
    "nx=nx.nextElementSibling;}}"
    "if(wrap){opt=wrap.querySelector('.selectize-dropdown-content [data-value=\"'+val+'\"]');"
    "if(opt)opt_source='wrapper';}}"
    "if(!opt){"
    # Diagnostic: dump the actual option values present so we can compare.
    "var avail=[];"
    "if(sel.selectize.$dropdown_content&&sel.selectize.$dropdown_content[0]){"
    "var all=sel.selectize.$dropdown_content[0].querySelectorAll('[data-value]');"
    "for(var k=0;k<all.length&&k<20;k++){avail.push({data_value:all[k].getAttribute('data-value'),"
    "text:(all[k].textContent||'').trim().slice(0,40)});}}"
    "var stz_opts=[];"
    "if(sel.selectize.options){var oo=sel.selectize.options;"
    "for(var kk in oo){if(oo.hasOwnProperty(kk)){stz_opts.push({key:kk,"
    "value:(oo[kk]&&oo[kk].value)||null,text:(oo[kk]&&(oo[kk].text||oo[kk].label))||null});"
    "if(stz_opts.length>=20)break;}}}"
    # Where did the typed query land? Search-input value + focused element —
    # proves whether the type-to-filter text reached Selectize's search box.
    "var search=null;"
    "try{search=sel.selectize.$control_input?String(sel.selectize.$control_input.val()):null;}catch(e){}"
    "var ae=document.activeElement;"
    "var active=ae?ae.tagName+(ae.className?'.'+String(ae.className).trim().split(/\\s+/)[0]:''):null;"
    "return {ok:false,reason:'no_option',is_open:is_open,"
    "requested_value:val,search_value:search,active_element:active,"
    "dropdown_options:avail,selectize_options:stz_opts};}"
    "opt.scrollIntoView({block:'center',inline:'nearest'});"
    "var r=opt.getBoundingClientRect();"
    "var dd2=opt.closest('.selectize-dropdown');"
    "return {ok:true,x:r.x,y:r.y,width:r.width,height:r.height,"
    "top:r.top,left:r.left,bottom:r.bottom,right:r.right,"
    "opt_source:opt_source,is_open:is_open,"
    "dropdown_display:dd2?getComputedStyle(dd2).display:null,"
    "pageYOffset:window.pageYOffset,"
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
    "is_open:sel.selectize?!!sel.selectize.isOpen:null,"
    "validity_valid:sel.validity?sel.validity.valid:null};"
    "})())"
)

# Pre-click obstruction probe (S02-safe, read-only). Returns what
# document.elementFromPoint sees at the selector's center and whether any
# Selectize dropdown is currently open. Root cause 2026-07-06/07: the edition
# dropdown (body-parented) left open by the old addItem fallback covered the
# "Create offer" button; the trusted click's mousedown landed on the dropdown
# OPTION under the cursor, silently re-picking a random edition ("BTC 1500
# PLN", id 14106) before the form was serialized — the wrong-edition offers.
_CLICK_TARGET_PROBE_JS = (
    "JSON.stringify((function(){"
    "var el=document.querySelector(%s);"
    "if(!el)return {ok:false,reason:'no_element'};"
    "var r=el.getBoundingClientRect();"
    "var at=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);"
    "var dds=document.querySelectorAll('.selectize-dropdown');"
    "var open=false;for(var i=0;i<dds.length;i++){"
    "if(getComputedStyle(dds[i]).display!=='none'){open=true;break;}}"
    "return {ok:true,is_target:at===el||el.contains(at),"
    "at:at?at.tagName+(at.className&&typeof at.className==='string'?"
    "'.'+at.className.trim().split(/\\s+/).slice(0,2).join('.'):''):null,"
    "any_selectize_dropdown_open:open};"
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

# Read-only readback of the modal's target controls, BOTH shapes (S18 2026-07-06;
# modal v2 2026-09-14).
# - v1: ``inputs`` — every ``offer[targets][]`` input with its value_len (never the
#   value), visibility, required flag and HTML5 validity (chip committed = valid).
# - v2: ``rows`` — for each row i (``offer[targets][i][target]`` present, i = 0, 1,
#   …, gap-free), the target VALUE (an AKS product id — compared to the wanted id,
#   the "never a guessed id" gate), its visibility/required/validity, and both
#   override selects read through both channels (``select.value`` +
#   ``selectize.getValue()``) + open state; a missing select reads ``null``.
# S02-safe: no ``.value=`` / click / fetch.
_TARGETS_READBACK_JS = (
    "JSON.stringify((function(){"
    "var content=document.querySelector('#TB_ajaxContent');"
    "if(!content)return {ok:false,reason:'no_modal'};"
    "var inputs=content.querySelectorAll('input[name=\"offer[targets][]\"]');"
    "var vals=[];"
    "for(var i=0;i<inputs.length;i++){var el=inputs[i];"
    "vals.push({value_len:(el.value||'').length,visible:el.offsetParent!==null,"
    "type:el.type||null,required:!!el.required,"
    "valid:el.validity?el.validity.valid:null});}"
    "function sel(s){if(!s)return null;return {present:true,"
    "select_value:String(s.value||''),"
    "selectize_value:s.selectize?String(s.selectize.getValue()):null,"
    "is_open:s.selectize?!!s.selectize.isOpen:null};}"
    "var rows=[];"
    "for(var n=0;n<50;n++){"
    "var t=content.querySelector('input[name=\"offer[targets]['+n+'][target]\"]');"
    "if(!t)break;"
    "var r=content.querySelector('select[name=\"offer[targets]['+n+'][region]\"]');"
    "var e=content.querySelector('select[name=\"offer[targets]['+n+'][edition]\"]');"
    "rows.push({index:n,target_value:String(t.value||''),"
    "target_visible:t.offsetParent!==null,target_required:!!t.required,"
    "target_valid:t.validity?t.validity.valid:null,"
    "region:sel(r),edition:sel(e)});}"
    "return {ok:true,count:inputs.length,inputs:vals,row_count:rows.length,rows:rows};"
    "})())"
)

# Read-only probe of the modal v2 ADD button (2026-09-14; locator rewritten
# 2026-09-15 after canary 2). CANARY-2 FINDING (run 20260914-canary-two-targets,
# NBA 2K25 Xbox One + Series): the <button> that is the next sibling of the LAST
# row's target input is the row's REMOVE button — `button.button
# [data-remove-target]`, text "×"; the trusted click on it added nothing (1 row
# read back → TARGET_ROW_NOT_ADDED, no write). The DOM-relation locator is gone.
# Locator rule, fail-closed:
#   1. NEVER an element carrying `data-remove-target`.
#   2. `#TB_ajaxContent form [data-add-target]` (a <button> or an <a>) — exactly
#      one → chosen, `matched_by: '[data-add-target]'` (UNVERIFIED live: inferred
#      from the tool's `data-target-input` / `data-target-override` /
#      `data-remove-target` naming); several → `ambiguous_add_button`.
#   3. Otherwise the fallback: every <button> of the form whose `type` property
#      is 'button', not `[data-remove-target]`, not submit-like, and whose data-*
#      attribute NAMES or text match /add|ajout|plus|\+/i — chosen ONLY when
#      exactly one exists (`matched_by: 'fallback:data-attr:<name>'` /
#      `'fallback:text'`); 0 → `no_add_button_candidate`, >1 →
#      `ambiguous_add_button`. Every <button> considered is listed in
#      `candidates` with its `rejected` reason so the plan explains itself.
# `submit_like` = not a BUTTON/A, or a BUTTON whose `type` ≠ 'button' (a
# type-less <button> in a form is a submit button), or an <a> whose href
# navigates, or `data-action-submit` / `button-primary` (the Create button's
# marks). The write path clicks the chosen element ONLY when `submit_like` is
# false, then proves the row count went UP by one (ROW_REMOVED if it went down).
# S02-safe: no mutation.
_ADD_ROW_BUTTON_PROBE_JS = (
    "JSON.stringify((function(){"
    "var content=document.querySelector('#TB_ajaxContent');"
    "if(!content)return {ok:false,reason:'no_modal'};"
    "var first=null,idx=-1;"
    "for(var n=0;n<50;n++){"
    "var t=content.querySelector('input[name=\"offer[targets]['+n+'][target]\"]');"
    "if(!t)break;if(!first)first=t;idx=n;}"
    "if(!first)return {ok:false,reason:'no_target_rows'};"
    "var form=first.closest('form')||content;"
    "var ADDISH=/add|ajout|plus|\\+/i;"
    "function dataAttrs(el){var o={};for(var i=0;i<el.attributes.length;i++){"
    "var a=el.attributes[i];if(a.name.indexOf('data-')!==0)continue;"
    "o[a.name]=String(a.value).slice(0,40);}return o;}"
    "function attrNames(el){var out=[];for(var i=0;i<el.attributes.length;i++){"
    "out.push(el.attributes[i].name);}return out;}"
    "function desc(el){"
    "var cls=(el.className&&typeof el.className==='string')?el.className:'';"
    "var isButton=el.tagName==='BUTTON',isAnchor=el.tagName==='A';"
    "var typeProp=isButton?String(el.type||''):null;"
    "var href=isAnchor?(el.getAttribute('href')||''):null;"
    "var navigates=isAnchor&&href!==''&&href!=='#'&&!/^javascript:/i.test(href);"
    "var submitLike=(!isButton&&!isAnchor)||(isButton&&typeProp!=='button')||navigates||"
    "el.hasAttribute('data-action-submit')||/\\bbutton-primary\\b/.test(cls);"
    "return {tag:el.tagName,type_prop:typeProp,type_attr:el.getAttribute('type'),"
    "id:el.id||null,klass:cls,href:href,attrs:attrNames(el),data_attrs:dataAttrs(el),"
    "text:(el.textContent||'').trim().slice(0,40),visible:el.offsetParent!==null,"
    "is_remove:el.hasAttribute('data-remove-target'),submit_like:submitLike};}"
    "function addish(d){var names=Object.keys(d.data_attrs);"
    "for(var i=0;i<names.length;i++){if(ADDISH.test(names[i]))return 'data-attr:'+names[i];}"
    "return ADDISH.test(d.text)?'text':null;}"
    "var chosen=null,matchedBy=null,candidates=[];"
    "var explicit=Array.prototype.slice.call(form.querySelectorAll('[data-add-target]'))"
    ".filter(function(el){return (el.tagName==='BUTTON'||el.tagName==='A')&&"
    "!el.hasAttribute('data-remove-target');});"
    "if(explicit.length===1){chosen=explicit[0];matchedBy='[data-add-target]';}"
    "else if(explicit.length>1){return {ok:false,reason:'ambiguous_add_button',last_row:idx,"
    "matched_by:'[data-add-target]',candidates:explicit.map(desc)};}"
    "else{var all=Array.prototype.slice.call(form.querySelectorAll('button'));"
    "var eligible=[];"
    "for(var j=0;j<all.length;j++){var d=desc(all[j]);var why=null;"
    "if(d.is_remove)why='remove';"
    "else if(d.submit_like)why='submit_like';"
    "else{var m=addish(d);if(m)d.matched_by='fallback:'+m;else why='not_addish';}"
    "d.rejected=why;candidates.push(d);if(!why)eligible.push(j);}"
    "if(eligible.length!==1){return {ok:false,"
    "reason:eligible.length?'ambiguous_add_button':'no_add_button_candidate',"
    "last_row:idx,candidates:candidates};}"
    "chosen=all[eligible[0]];matchedBy=candidates[eligible[0]].matched_by;}"
    "var out=desc(chosen);out.ok=true;out.last_row=idx;out.matched_by=matchedBy;"
    "out.candidates_count=candidates.length;"
    "var r=chosen.getBoundingClientRect();"
    "out.x=r.x;out.y=r.y;out.width=r.width;out.height=r.height;"
    "out.top=r.top;out.left=r.left;out.bottom=r.bottom;out.right=r.right;"
    "out.viewport={w:window.innerWidth,h:window.innerHeight};"
    "return out;"
    "})())"
)

# Read-only dump of EVERY <button> / <a role=button> (+ <a data-add-target> /
# <a data-remove-target>) in the open modal (2026-09-15, canary 2): the write
# path's add-row locator was wrong once because the inspection never showed the
# buttons — this makes --inspect show them all (`inspection.modal_buttons`) so
# the real add button is READ before the next multi-target write. Per button:
# tag, type (property + attribute), id, class, text (60), every data-* attribute
# (values cut to 40), visibility, whether it sits inside the form, inside the
# targets container (the parent of row 0's wrapper — the closest ancestor of row
# 0's target input that also holds its two override selects), the row wrapper it
# sits in (`in_row`), and its ancestor path. S02-safe: no mutation.
_MODAL_BUTTONS_JS = (
    "JSON.stringify((function(){"
    "var content=document.querySelector('#TB_ajaxContent');"
    "if(!content)return {ok:false,reason:'no_modal',buttons:[]};"
    "function dataAttrs(el){var o={};for(var i=0;i<el.attributes.length;i++){"
    "var a=el.attributes[i];if(a.name.indexOf('data-')!==0)continue;"
    "o[a.name]=String(a.value).slice(0,40);}return o;}"
    "function path(el,md){var p=[],c=el,d=0;"
    "while(c&&c!==document.body&&d<md){"
    "var s=c.tagName.toLowerCase();if(c.id)s+='#'+c.id;"
    "else if(c.className&&typeof c.className==='string')"
    "s+='.'+c.className.trim().split(/\\s+/).slice(0,2).join('.');"
    "p.unshift(s);c=c.parentElement;d++;}return p.join(' > ');}"
    "var rows=[];"
    "for(var n=0;n<50;n++){"
    "var t=content.querySelector('input[name=\"offer[targets]['+n+'][target]\"]');"
    "if(!t)break;"
    "var r=content.querySelector('select[name=\"offer[targets]['+n+'][region]\"]');"
    "var e=content.querySelector('select[name=\"offer[targets]['+n+'][edition]\"]');"
    "var w=t.parentElement;"
    "while(w&&w!==content&&!((!r||w.contains(r))&&(!e||w.contains(e))))w=w.parentElement;"
    "rows.push({input:t,wrapper:w});}"
    "var container=(rows.length&&rows[0].wrapper&&rows[0].wrapper!==content)?"
    "rows[0].wrapper.parentElement:null;"
    "var form=content.querySelector('form');"
    "var els=Array.prototype.slice.call(content.querySelectorAll("
    "'button,a[role=\"button\"],a[data-add-target],a[data-remove-target]'));"
    "var buttons=els.map(function(el){"
    "var cls=(el.className&&typeof el.className==='string')?el.className:'';"
    "var inRow=null;for(var i=0;i<rows.length;i++){"
    "if(rows[i].wrapper&&rows[i].wrapper!==content&&rows[i].wrapper.contains(el)){inRow=i;break;}}"
    "return {tag:el.tagName,type_prop:el.tagName==='BUTTON'?String(el.type||''):null,"
    "type_attr:el.getAttribute('type'),id:el.id||null,klass:cls,"
    "href:el.tagName==='A'?el.getAttribute('href'):null,role:el.getAttribute('role'),"
    "text:(el.textContent||'').trim().slice(0,60),data_attrs:dataAttrs(el),"
    "visible:el.offsetParent!==null,in_form:!!(form&&form.contains(el)),"
    "in_targets_container:!!(container&&container.contains(el)),in_row:inRow,"
    "path:path(el,6)};});"
    "return {ok:true,count:buttons.length,row_count:rows.length,"
    "container:container?{tag:container.tagName,id:container.id||null,"
    "klass:(container.className&&typeof container.className==='string')?container.className:'',"
    "path:path(container,6)}:null,buttons:buttons};"
    "})())"
)

# The rect keys of a probe result — stripped from diags so the plan stays readable.
_RECT_KEYS = ("x", "y", "width", "height", "top", "left", "bottom", "right", "viewport")


def _v2_row_complete(row: Any) -> bool:
    """A v2 readback row carrying its target input AND both override selects."""

    if not isinstance(row, dict):
        return False
    region = row.get("region") or {}
    edition = row.get("edition") or {}
    return bool(region.get("present")) and bool(edition.get("present"))


def _add_button_refusal(probe: dict[str, Any], index: int) -> tuple[str, str] | None:
    """Why the probed add button must NOT be clicked for row ``index`` —
    ``(status, reason)`` or ``None`` when it may. Defence in depth over the
    JS locator: a ``data-remove-target`` mark is refused HERE too (canary 2,
    2026-09-15 — the sibling button of the target input is the remove one)."""

    if not probe.get("ok"):
        return ("NO_ADD_BUTTON", (
            f"no unique add button in the modal form ({probe.get('reason')!r}; "
            f"{len(probe.get('candidates') or [])} candidate(s) listed in add_button.candidates)"
        ))
    attrs = list(probe.get("attrs") or []) + list((probe.get("data_attrs") or {}).keys())
    if probe.get("is_remove") or "data-remove-target" in attrs:
        return ("NO_ADD_BUTTON", (
            "the located button carries data-remove-target — the row's REMOVE button "
            "(canary 2, 2026-09-15); not clicked"
        ))
    if probe.get("tag") not in ("BUTTON", "A"):
        return ("NO_ADD_BUTTON", f"add button is a {probe.get('tag')!r}, not a <button>/<a>")
    if probe.get("last_row") != index - 1:
        return ("NO_ADD_BUTTON", (
            f"target rows moved: last row {probe.get('last_row')!r}, expected {index - 1}"
        ))
    if probe.get("submit_like"):
        return ("ADD_BUTTON_UNSAFE", (
            f"add button reads type={probe.get('type_prop')!r} "
            f"(attr {probe.get('type_attr')!r}, class {probe.get('klass')!r}"
            f"{', href ' + repr(probe.get('href')) if probe.get('tag') == 'A' else ''}) — "
            "a submit-type click would natively submit the modal form; not clicked"
        ))
    return None


def _readback_values(state: Any) -> set[str]:
    """The value(s) a select readback reports, through both channels, as a set —
    ``select.value`` always, ``selectize.getValue()`` when the plugin answered."""

    if not isinstance(state, dict):
        return set()
    got = {str(state.get("select_value") or "")}
    if state.get("selectize_value") is not None:
        got.add(str(state.get("selectize_value")))
    return got


class WriteSubmitSession(SubmitSession):
    """SubmitSession + the single mutating op. Instantiated ONLY under ``--submit``.

    ``fill_and_create`` (native/dispatch), ``fill_then_click_trusted`` (Chantier
    n°1 trusted, ``targets_v1`` shape) and ``fill_targets_v2_trusted`` (modal v2,
    2026-09-14 — one row per target) are the only methods that write: they set
    region/edition on the verified select names and cause a click on the visible
    "Create offer" button. No direct XHR, no ``form.submit()`` (S09), never an
    Enter keypress in the modal. Three click_modes are supported:

    - ``native``: DOM ``b.click()`` — the original path, ``isTrusted:false``,
      proven NOT to persist on Driffle; kept only as a documented diagnostic.
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

    def click_target_probe(
        self, selector: str = "#TB_ajaxContent .button-primary",
    ) -> dict[str, Any]:
        """Read-only pre-click guard: is the element at the selector's center
        actually the selector's element? Returns ``{ok, is_target, at,
        any_selectize_dropdown_open}`` (or ``{ok: False, reason}``). Catches the
        2026-07-06/07 wrong-edition root cause: a body-parented Selectize
        dropdown left open OVER the Create button, so the trusted click's
        mousedown re-picked the dropdown option under the cursor and the form
        was serialized with a corrupted edition."""

        raw = self.evaluate_readonly(_CLICK_TARGET_PROBE_JS % json.dumps(selector))
        return json.loads(raw) if raw else {"ok": False, "reason": "no_result"}

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

        # TE5 (audit 2026-07-17): one scroll implementation — this used to be
        # an inline copy of _scroll_rect_into_viewport (same 40 % target, same
        # gesture, same settle) that could silently drift from the tested one.
        scroll = self._scroll_rect_into_viewport(rect)
        if scroll["scrolled"]:
            diag["scrolled"] = True
            diag["scroll_y_distance"] = scroll["scroll_y_distance"]
            rect = self._read_rect(selector)
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

    def _scroll_rect_into_viewport(self, rect: dict[str, Any]) -> dict[str, Any]:
        """If ``rect`` is (partially) outside the viewport, issue one CDP
        ``Input.synthesizeScrollGesture`` (mouse source) to bring it around 40 %
        of viewport height and wait 500 ms for settle. Returns
        ``{scrolled: bool, scroll_y_distance: int}``. ``#TB_window`` is
        ``position: fixed`` so the modal stays put; scrolling the page only
        moves body-attached elements (e.g. Selectize's body-parented dropdown).
        """

        vp = rect.get("viewport") or {}
        top = rect.get("top", rect.get("y", 0))
        bottom = rect.get("bottom", top + rect.get("height", 0))
        if not vp or (top >= 0 and bottom <= vp["h"]):
            return {"scrolled": False}
        target_y = vp["h"] * 0.4
        current_y = (top + bottom) / 2
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
        return {"scrolled": True, "scroll_y_distance": y_distance}

    def _readback_select(self, select_name: str) -> dict[str, Any]:
        """Read-only readback of a select's current value through both
        channels (``select.value`` + ``selectize.getValue()``) + open state."""

        raw = self.evaluate_readonly(_SELECTIZE_READBACK_JS % json.dumps(select_name))
        return json.loads(raw) if raw else {"ok": False}

    def select_via_trusted(
        self, select_name: str, value_id: str, query: str | None = None,
    ) -> dict[str, Any]:
        """Selectize humanisé (Chantier n°1 extension, 2026-07-03).

        1. Read the ``.selectize-input`` rect for the given select name (S02-safe).
        2. Trusted CDP click on it — the dropdown opens naturally.
        3. Wait 500 ms for dropdown render + option layout.
        4. If ``query`` is given, type it into the (now-focused) Selectize search
           box via per-char trusted key events (``_type_text_trusted``) so the
           plugin filters/renders the matching option. This is REQUIRED for the
           edition select: the catalog is ~14009 options and Selectize only
           renders its ``maxOptions`` cap (~1000, sorted), so a target like
           "Standard" (id 1) never renders until searched — the raw dropdown
           scan would fail-closed NO_OPTION (2026-07-07 catalog fetch).
        5. Read the ``[data-value="{value_id}"]`` option rect (S02-safe).
        6. If the option is off-viewport (Selectize v0.x with
           ``dropdownParent:'body'`` puts its dropdown at document coords, which
           can land far below when the pending feed page is long),
           ``Input.synthesizeScrollGesture`` to bring it into view + re-read rect.
        7. Trusted CDP click at the option's center — Selectize applies the
           value, plugin's own listeners fire.
        8. Wait 200 ms for state settle.
        9. Read back ``select.value`` + ``select.selectize.getValue()`` +
           ``select.validity.valid``.

        Returns a diag dict: select_name, value_id, query, status
        ('SELECTED' | 'NO_SELECTIZE_INPUT' | 'NO_OPTION' |
        'NO_OPTION_AFTER_SCROLL'), input_rect, option_rect, open_click,
        option_scroll, option_click, readback.
        """

        input_raw = self.evaluate_readonly(
            _SELECTIZE_INPUT_RECT_JS % json.dumps(select_name)
        )
        input_rect = json.loads(input_raw) if input_raw else {"ok": False}
        diag: dict[str, Any] = {"select_name": select_name, "value_id": str(value_id)}
        if query is not None:
            diag["query"] = str(query)
        if not input_rect.get("ok"):
            diag["status"] = "NO_SELECTIZE_INPUT"
            diag["reason"] = input_rect.get("reason")
            return diag

        diag["input_rect"] = {
            "x": input_rect["x"], "y": input_rect["y"],
            "w": input_rect["width"], "h": input_rect["height"],
        }
        diag["open_click"] = self._trusted_click_at_rect(input_rect)
        time.sleep(0.5)  # dropdown render + option layout (was 250ms — too short)

        if query:
            # Type the label so Selectize filters+renders the wanted option even
            # when it sits beyond the maxOptions render cap. The dropdown-open
            # trusted click focused the plugin's search input. MUST be per-char
            # trusted key events: Selectize v0.x refilters on keyup only, and
            # Input.insertText (input event only) was proven NOT to refilter on
            # the 2026-07-07 canary (NO_EDITION_PICK).
            diag["typed"] = self._type_text_trusted(str(query))
            diag["typed_query"] = str(query)
            time.sleep(0.5)  # keyup → refreshOptions + re-render settle

        option_raw = self.evaluate_readonly(
            _SELECTIZE_OPTION_RECT_JS
            % (json.dumps(select_name), json.dumps(str(value_id)))
        )
        option_rect = json.loads(option_raw) if option_raw else {"ok": False}
        if not option_rect.get("ok"):
            # Fail-closed: the wanted value is NOT one of the product-scoped
            # options rendered in the dropdown. We must NOT force it via
            # `addItem` — that reads Selectize's generic master catalog (which
            # has e.g. "1"→"Standard" for every product) and would submit an
            # edition/region that a human operator never sees for this product.
            # On 2026-07-06 that exact force created 3 offers with the WRONG
            # edition (id "1" not in the rendered dropdown). No degraded mode:
            # stop and surface both lists so the operator sees the mismatch.
            diag["status"] = "NO_OPTION"
            diag["reason"] = option_rect.get("reason")
            diag["is_open"] = option_rect.get("is_open")
            diag["search_value"] = option_rect.get("search_value")
            diag["active_element"] = option_rect.get("active_element")
            diag["dropdown_options"] = option_rect.get("dropdown_options")
            diag["selectize_options"] = option_rect.get("selectize_options")
            return diag
        diag["opt_source"] = option_rect.get("opt_source")
        diag["is_open"] = option_rect.get("is_open")
        diag["dropdown_display"] = option_rect.get("dropdown_display")
        diag["pageYOffset"] = option_rect.get("pageYOffset")

        # Bring the option into viewport if Selectize rendered its dropdown far
        # below (body-parented). #TB_window is position:fixed so the modal
        # itself stays put — we only move the body-attached dropdown.
        scroll = self._scroll_rect_into_viewport(option_rect)
        diag["option_scroll"] = scroll
        if scroll["scrolled"]:
            option_raw = self.evaluate_readonly(
                _SELECTIZE_OPTION_RECT_JS
                % (json.dumps(select_name), json.dumps(str(value_id)))
            )
            option_rect = json.loads(option_raw) if option_raw else {"ok": False}
            if not option_rect.get("ok"):
                diag["status"] = "NO_OPTION_AFTER_SCROLL"
                diag["reason"] = option_rect.get("reason")
                return diag

        diag["option_rect"] = {
            "x": option_rect["x"], "y": option_rect["y"],
            "w": option_rect["width"], "h": option_rect["height"],
        }
        diag["option_click"] = self._trusted_click_at_rect(option_rect)
        time.sleep(0.2)  # dropdown close + state settle

        readback = self._readback_select(select_name)
        diag["readback"] = readback
        # Fail-closed: a dropdown still open after the pick can cover elements
        # below (body-parented) and swallow a later trusted click's mousedown,
        # silently re-picking whatever option sits under the cursor AFTER the
        # readback — the 2026-07-06/07 wrong-edition root cause ("BTC 1500 PLN",
        # id 14106, instead of Standard). A real option click closes the
        # dropdown via onOptionSelect, so open-here means the pick didn't land.
        if readback.get("is_open"):
            diag["status"] = "DROPDOWN_STILL_OPEN"
            return diag
        # Fail-closed: the pick must have landed on the WANTED option. A
        # trusted click can land on a neighbour (layout shift between the rect
        # read and the mousedown, sub-pixel rounding) and every downstream
        # gate would still pass — the form is valid with ANY selected option.
        # Compare both readback channels to the target id; anything else is a
        # mis-pick, not a success (audit 2026-07-17, SC3).
        if not readback.get("ok"):
            diag["status"] = "READBACK_UNREADABLE"
            return diag
        got = {str(readback.get("select_value") or "")}
        if readback.get("selectize_value") is not None:
            got.add(str(readback.get("selectize_value")))
        if got != {str(value_id)}:
            diag["status"] = "WRONG_VALUE"
            diag["reason"] = (
                f"readback {sorted(got)!r} != target {str(value_id)!r} "
                "after the option click"
            )
            return diag
        diag["status"] = "SELECTED"
        return diag

    # ``_press_enter`` (the v1 chip-commit fallback) was REMOVED on 2026-09-14: the
    # modal <form> has method=get and no action, so a trusted Enter inside one of its
    # text inputs can natively submit the form — an uncontrolled write. No method of
    # this class synthesizes an Enter keypress in the modal.

    def _type_text_trusted(self, text: str) -> dict[str, Any]:
        """Type ``text`` into the focused element the human way: one trusted
        ``Input.dispatchKeyEvent`` keyDown(+text)/keyUp pair per character, with
        a small random dwell + inter-key delay.

        Why not ``Input.insertText``: it fires only an ``input`` event, and
        Selectize v0.x filters on **keyup** (``onKeyUp`` → ``refreshOptions()``),
        so insertText leaves the dropdown unfiltered — proven live on the
        2026-07-07 canary (NO_EDITION_PICK: after inserting "Standard" the
        edition dropdown still showed the unfiltered alphabetical head). Real
        per-char key events fire keydown/keypress/input/keyup, all
        ``isTrusted:true``, covering every listener a real keyboard would.
        """

        chars = 0
        for ch in str(text):
            vk = 0
            if ch.isascii() and ch.isalnum():
                vk = ord(ch.upper())
            elif ch == " ":
                vk = 32
            down: dict[str, Any] = {
                "type": "keyDown", "text": ch, "unmodifiedText": ch, "key": ch,
            }
            up: dict[str, Any] = {"type": "keyUp", "key": ch}
            if vk:
                down["windowsVirtualKeyCode"] = vk
                down["nativeVirtualKeyCode"] = vk
                up["windowsVirtualKeyCode"] = vk
                up["nativeVirtualKeyCode"] = vk
            self._cmd("Input.dispatchKeyEvent", down)
            time.sleep(random.randint(20, 50) / 1000.0)
            self._cmd("Input.dispatchKeyEvent", up)
            time.sleep(random.randint(30, 90) / 1000.0)
            chars += 1
        return {"chars": chars}

    def add_target_trusted(self, value: str) -> dict[str, Any]:
        r"""Fill the modal's ``offer[targets][]`` field the human way (S18,
        2026-07-06). The field is a required ``<input type=text>`` with
        ``pattern="(\d+)|(https?://.+)"`` and a sibling add-button — it wants the
        AKS product id (numeric) or URL; ``value`` is the candidate's
        ``aks_product_id``. Flow:

        1. Trusted CDP click on ``#TB_ajaxContent input[name="offer[targets][]"]``
           to focus it (with the usual scroll-into-view handling).
        2. ``Input.insertText`` types ``value`` — a real ``input`` event, no
           ``.value=`` / setValue.
        3. Commit the chip: trusted click on the adjacent add-button
           (``… + button``). If that element isn't found → ``NO_ADD_BUTTON``,
           fail-closed: the historical trusted-Enter fallback was REMOVED
           (2026-09-14) because the modal form (method=get, no action) submits
           natively on Enter — an uncontrolled write.
        4. Read back the ``offer[targets][]`` input state (read-only).

        Returns a diag: ``value, focus, typed, add_button, commit ('button'),
        readback, status ('ADDED' | 'NO_TARGETS_FIELD' | 'NO_ADD_BUTTON')``.
        NOT a success proof — the caller's ``form_validity()`` gate + post-save
        decide. ``NO_TARGETS_FIELD`` (field absent) is non-fatal: some products
        may not require a target, and the validity gate is the backstop.
        ``NO_ADD_BUTTON`` IS fatal for the caller (the typed id sits uncommitted).
        """

        field_sel = "#TB_ajaxContent input[name=\"offer[targets][]\"]"
        diag: dict[str, Any] = {"value": str(value)}
        focus = self.click_trusted_at_element(field_sel)
        diag["focus"] = focus
        if focus.get("status") != "CLICKED":
            diag["status"] = "NO_TARGETS_FIELD"
            return diag
        self._cmd("Input.insertText", {"text": str(value)})
        diag["typed"] = True
        time.sleep(0.2)
        add_button = self.click_trusted_at_element(field_sel + " + button")
        diag["add_button"] = add_button
        if add_button.get("status") != "CLICKED":
            diag["status"] = "NO_ADD_BUTTON"
            diag["reason"] = "add-button not found next to offer[targets][] — no Enter fallback"
            return diag
        diag["commit"] = "button"
        time.sleep(0.3)
        diag["readback"] = self._readback_targets()
        diag["status"] = "ADDED"
        return diag

    # ------------------------------------------------------------------
    # Modal v2 (2026-09-14) — region + edition PER TARGET PAGE. Romain's three
    # confirmations (2026-09-14): (1) a button of the row block ADDS a new target
    # row (works by hand) — canary 2 (2026-09-15) proved the button NEXT TO the
    # target input is the row's REMOVE button (`data-remove-target`, "×"); the add
    # button is located by `_ADD_ROW_BUTTON_PROBE_JS`'s rule and the readback that
    # row i exists after the click stays the gate (row count down → ROW_REMOVED);
    # (2) empty per-target region/edition INHERIT the global
    # offer[region]/offer[edition] (tested by him) — the overrides are still set
    # EXPLICITLY on every row, inheritance is never relied on; (3) the modal takes
    # "3 ou 4 pour le moment" targets — the submitter caps a candidate at
    # MAX_TARGETS_PER_OFFER = 3 before anything is filled.
    # ------------------------------------------------------------------
    def _readback_targets(self) -> dict[str, Any]:
        """Read-only readback of the target controls, both shapes (see
        ``_TARGETS_READBACK_JS``): ``{ok, count, inputs, row_count, rows}``."""

        raw = self.evaluate_readonly(_TARGETS_READBACK_JS)
        return json.loads(raw) if raw else {"ok": False, "reason": "no_result"}

    def _add_row_button_probe(self) -> dict[str, Any]:
        """Read-only probe of the add-row button (``_ADD_ROW_BUTTON_PROBE_JS``)."""

        raw = self.evaluate_readonly(_ADD_ROW_BUTTON_PROBE_JS)
        return json.loads(raw) if raw else {"ok": False, "reason": "no_result"}

    def _add_target_row_trusted(self, index: int) -> dict[str, Any]:
        """Add target row ``index`` (≥ 1) to the v2 modal with a trusted click on
        the ADD button, then PROVE the row exists (fail-closed).

        CANARY 2 (2026-09-15, run ``20260914-canary-two-targets``, NBA 2K25): the
        button that is the next sibling of the last row's target input is the
        row's REMOVE button (``button.button[data-remove-target]``, text "×") —
        clicking it added nothing (``TARGET_ROW_NOT_ADDED``, nothing written). The
        locator is now ``_ADD_ROW_BUTTON_PROBE_JS``'s rule: never a
        ``[data-remove-target]`` element; ``form [data-add-target]`` first, else
        the UNIQUE add-ish ``<button type=button>`` fallback (0 or several →
        nothing clicked). ``add_button.matched_by`` records which rule matched.

        0. Readback BEFORE anything: exactly ``index`` rows must exist
           (``TARGETS_COUNT_MISMATCH``; unreadable → ``TARGETS_READBACK_UNREADABLE``).
        1. Probe the add button (``_add_button_refusal``): no unique candidate,
           a wrong tag, moved rows, or ANY ``data-remove-target`` mark →
           ``NO_ADD_BUTTON``; submit-like (``type`` ≠ 'button', navigating <a>,
           ``data-action-submit``, ``button-primary``) → ``ADD_BUTTON_UNSAFE`` — a
           submit-type click would natively submit the ``method=get`` form.
        2. Scroll it into the viewport if needed (re-probe: same verdicts, same
           ``matched_by``), trusted click.
        3. Readback AFTER: fewer rows than before → ``ROW_REMOVED`` (the click was
           a remove — the flow stops, no Create click); more than ``index + 1``
           rows → ``TARGETS_COUNT_MISMATCH``; row ``index`` absent or without its
           target input + both override selects → ``TARGET_ROW_NOT_ADDED``.

        Returns ``{row, rows_before, add_button (matched_by, candidates…), scroll,
        click, readback, status ('ROW_ADDED' | 'NO_ADD_BUTTON' |
        'ADD_BUTTON_UNSAFE' | 'ROW_REMOVED' | 'TARGET_ROW_NOT_ADDED' |
        'TARGETS_COUNT_MISMATCH' | 'TARGETS_READBACK_UNREADABLE'), reason?}``.
        No Enter, ever.
        """

        diag: dict[str, Any] = {"row": index}
        before = self._readback_targets()
        if not before.get("ok"):
            diag["status"] = "TARGETS_READBACK_UNREADABLE"
            diag["reason"] = f"target rows unreadable before adding row {index}"
            return diag
        rows_before = len(before.get("rows") or [])
        diag["rows_before"] = rows_before
        if rows_before != index:
            diag["status"] = "TARGETS_COUNT_MISMATCH"
            diag["reason"] = (
                f"{rows_before} row(s) in the modal before adding row {index} (expected {index})"
            )
            return diag
        probe = self._add_row_button_probe()
        diag["add_button"] = {k: v for k, v in probe.items() if k not in _RECT_KEYS}
        refusal = _add_button_refusal(probe, index)
        if refusal:
            diag["status"], diag["reason"] = refusal
            return diag
        scroll = self._scroll_rect_into_viewport(probe)
        diag["scroll"] = scroll
        if scroll["scrolled"]:
            matched_by = probe.get("matched_by")
            probe = self._add_row_button_probe()
            if _add_button_refusal(probe, index) or probe.get("matched_by") != matched_by:
                diag["status"] = "NO_ADD_BUTTON"
                diag["reason"] = "add button not re-found identically after the scroll"
                return diag
        diag["click"] = self._trusted_click_at_rect(probe)
        time.sleep(0.3)  # the row is appended by the page's own handler
        readback = self._readback_targets()
        diag["readback"] = readback
        if not readback.get("ok"):
            diag["status"] = "TARGETS_READBACK_UNREADABLE"
            return diag
        rows = readback.get("rows") or []
        if len(rows) < rows_before:
            diag["status"] = "ROW_REMOVED"
            diag["reason"] = (
                f"the click REMOVED a row ({rows_before} → {len(rows)}): the located button "
                f"(matched_by {probe.get('matched_by')!r}) is a remove button — no Create click"
            )
            return diag
        if len(rows) > index + 1:
            diag["status"] = "TARGETS_COUNT_MISMATCH"
            diag["reason"] = f"{len(rows)} rows after adding row {index} (expected {index + 1})"
            return diag
        if len(rows) < index + 1 or not _v2_row_complete(rows[index]):
            diag["status"] = "TARGET_ROW_NOT_ADDED"
            diag["reason"] = (
                f"row {index} absent or incomplete after the add-row click "
                f"({len(rows)} row(s) read back)"
            )
            return diag
        diag["status"] = "ROW_ADDED"
        return diag

    def _fill_target_row_trusted(self, index: int, target: dict[str, Any]) -> dict[str, Any]:
        """Fill v2 row ``index``: the target id + BOTH overrides, explicitly.

        1. Trusted focus click on ``input[name="offer[targets][index][target]"]``
           → ``NO_TARGET_INPUT`` if it can't be clicked (fatal in v2).
        2. ``Input.insertText`` of ``target['aks_product_id']`` (a real ``input``
           event; no ``.value=``). NO add-row click, NO Enter.
        3. Readback: the row's target value must EQUAL the id (``never a guessed
           id``) else ``TARGET_VALUE_MISMATCH``.
        4. ``select_via_trusted`` on the row's region then edition override
           (typed catalog text as the query, SC3 readback inside) →
           ``NO_ROW_REGION_PICK`` / ``NO_ROW_EDITION_PICK``. Always set, even
           though an empty override inherits the global select (Romain,
           2026-09-14) — inheritance is never relied on.

        Returns ``{row, aks_product_id, region_id, edition_id, focus, typed,
        readback, region_pick, edition_pick, status ('ROW_FILLED' | …)}``.
        """

        pid = str(target.get("aks_product_id") or "")
        region_id = str(target.get("region_id") or "")
        edition_id = str(target.get("edition_id") or "")
        diag: dict[str, Any] = {
            "row": index, "aks_product_id": pid,
            "region_id": region_id, "edition_id": edition_id,
        }
        if not pid or not region_id or not edition_id:
            diag["status"] = "NO_TARGET_ID"
            diag["reason"] = f"row {index}: empty target/region/edition id — never guessed"
            return diag
        field_sel = f"#TB_ajaxContent input[name=\"offer[targets][{index}][target]\"]"
        focus = self.click_trusted_at_element(field_sel)
        diag["focus"] = focus
        if focus.get("status") != "CLICKED":
            diag["status"] = "NO_TARGET_INPUT"
            diag["reason"] = f"row {index}: target input not clickable ({focus.get('status')})"
            return diag
        self._cmd("Input.insertText", {"text": pid})
        diag["typed"] = True
        time.sleep(0.2)
        readback = self._readback_targets()
        diag["readback"] = readback
        if not readback.get("ok"):
            diag["status"] = "TARGETS_READBACK_UNREADABLE"
            return diag
        rows = readback.get("rows") or []
        if index >= len(rows) or not _v2_row_complete(rows[index]):
            diag["status"] = "TARGET_ROW_NOT_ADDED"
            diag["reason"] = f"row {index} absent or incomplete after typing its target"
            return diag
        got = str(rows[index].get("target_value") or "")
        if got != pid:
            diag["status"] = "TARGET_VALUE_MISMATCH"
            diag["reason"] = f"row {index} target reads {got!r} after typing {pid!r}"
            return diag
        region_pick = self.select_via_trusted(
            f"offer[targets][{index}][region]", region_id, query=target.get("region_query"),
        )
        diag["region_pick"] = region_pick
        if region_pick.get("status") != "SELECTED":
            diag["status"] = "NO_ROW_REGION_PICK"
            diag["reason"] = f"row {index} region override: {region_pick.get('status')}"
            return diag
        edition_pick = self.select_via_trusted(
            f"offer[targets][{index}][edition]", edition_id, query=target.get("edition_query"),
        )
        diag["edition_pick"] = edition_pick
        if edition_pick.get("status") != "SELECTED":
            diag["status"] = "NO_ROW_EDITION_PICK"
            diag["reason"] = f"row {index} edition override: {edition_pick.get('status')}"
            return diag
        diag["status"] = "ROW_FILLED"
        return diag

    def fill_targets_v2_trusted(
        self,
        targets: list[dict[str, Any]],
        region_select: str,
        edition_select: str,
    ) -> dict[str, Any]:
        """The v2 write: fill every target row, then ONE trusted Create click.

        ``targets`` = ``[{aks_product_id, region_id, edition_id, region_query,
        edition_query}, …]`` in row order; the FIRST is the primary target whose
        ids also go to the global selects. Fail-closed at every step — a failure
        cleans the taps up and returns WITHOUT clicking; "never a partial console
        entry": either every row is proven filled or nothing is created.

        0. Read-only shape check: the open modal must read ``targets_v2``, else
           ``MODAL_SHAPE_MISMATCH``.
        1. Prep JS (taps + pre-existing signal state; NO fill).
        2. Global ``offer[region]`` / ``offer[edition]`` via ``select_via_trusted``
           with the PRIMARY target's ids (SC3 readback) → ``NO_REGION_PICK`` /
           ``NO_EDITION_PICK``.
        3. Row 0: ``_fill_target_row_trusted`` (target id, then the two overrides
           explicitly). Rows i ≥ 1: ``_add_target_row_trusted(i)`` (trusted click on
           the add-row button, row proven present) then the same fill. Any row
           status ≠ ROW_ADDED / ROW_FILLED stops the flow under that status.
        4. ``form_validity()`` hard gate (``FORM_INVALID`` /
           ``FORM_VALIDITY_UNREADABLE``), pre-click obstruction probe
           (``CLICK_PATH_OBSTRUCTED``).
        5. LAST gate before the click — a full readback: both global selects and
           EVERY row (target value, both override selects through both channels)
           must still equal the wanted ids (``VALUE_DRIFTED_BEFORE_CLICK``), and
           the row count must equal ``len(targets)`` (``TARGETS_COUNT_MISMATCH``).
        6. Trusted click on "Create offer" (``NO_TRUSTED_CLICK``), poll.

        Post-save (offer gone from the refreshed pending feed) remains the ONLY
        success proof — this method's ``status`` is diagnostic only. No Enter, no
        ``form.submit()``, no XHR, no ``setValue``.
        """

        targets = [dict(t) for t in (targets or [])]
        base: dict[str, Any] = {
            "click_mode": "trusted", "modal_shape": MODAL_SHAPE_V2,
            "targets_count": len(targets),
        }
        if not targets:
            return {**base, "status": "NO_TARGETS"}
        shape = self.modal_context()
        if shape.get("modal_shape") != MODAL_SHAPE_V2:
            return {**base, "status": "MODAL_SHAPE_MISMATCH",
                    "reason": f"open modal reads shape {shape.get('modal_shape')!r}, "
                              f"expected {MODAL_SHAPE_V2!r}"}

        prep = self._evaluate(
            _TRUSTED_PREP_JS % (json.dumps(region_select), json.dumps(edition_select))
        )
        if not isinstance(prep, dict) or prep.get("status") != "PREPARED":
            return prep if isinstance(prep, dict) else {"status": "NO_RESULT", "raw": prep}
        prep.update(base)
        primary = targets[0]
        prep["region_target"] = str(primary.get("region_id") or "")
        prep["edition_target"] = str(primary.get("edition_id") or "")

        def stop(status: str, reason: str | None = None) -> dict[str, Any]:
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = status
            if reason:
                prep["reason"] = reason
            return prep

        region_pick = self.select_via_trusted(
            region_select, prep["region_target"], query=primary.get("region_query"),
        )
        prep["region_pick"] = region_pick
        if region_pick.get("status") != "SELECTED":
            return stop("NO_REGION_PICK")
        edition_pick = self.select_via_trusted(
            edition_select, prep["edition_target"], query=primary.get("edition_query"),
        )
        prep["edition_pick"] = edition_pick
        if edition_pick.get("status") != "SELECTED":
            return stop("NO_EDITION_PICK")
        prep["region_set"] = str((region_pick.get("readback") or {}).get("selectize_value", ""))
        prep["edition_set"] = str((edition_pick.get("readback") or {}).get("selectize_value", ""))

        rows: list[dict[str, Any]] = []
        prep["rows"] = rows
        for index, target in enumerate(targets):
            row_diag: dict[str, Any] = {"row": index}
            rows.append(row_diag)
            if index >= 1:
                added = self._add_target_row_trusted(index)
                row_diag["add"] = added
                if added.get("status") != "ROW_ADDED":
                    return stop(str(added.get("status")), added.get("reason"))
            filled = self._fill_target_row_trusted(index, target)
            row_diag["fill"] = filled
            if filled.get("status") != "ROW_FILLED":
                return stop(str(filled.get("status")), filled.get("reason"))

        # Hard validity gate (audit P1b) — unchanged from the v1 flow.
        validity = self.form_validity()
        prep["form_validity"] = validity
        if not validity.get("ok"):
            return stop("FORM_VALIDITY_UNREADABLE")
        if validity.get("form_valid") is not True:
            return stop("FORM_INVALID")

        path_probe = self.click_target_probe("#TB_ajaxContent .button-primary")
        prep["click_path"] = path_probe
        if path_probe.get("ok") and not path_probe.get("is_target"):
            return stop("CLICK_PATH_OBSTRUCTED")

        # Last gate before the ONE write: everything must STILL read the wanted
        # ids — the globals (SC3) and every row (VALUE_DRIFTED_BEFORE_CLICK
        # generalised to the v2 rows), and no row appeared or vanished.
        drift: dict[str, Any] = {}
        prep["pre_click_readback"] = drift
        for kind, name, wanted in (
            ("region", region_select, prep["region_target"]),
            ("edition", edition_select, prep["edition_target"]),
        ):
            final = self._readback_select(name)
            drift[kind] = final
            if not final.get("ok") or str(final.get("select_value") or "") != wanted:
                return stop(
                    "VALUE_DRIFTED_BEFORE_CLICK",
                    f"{kind} reads {final.get('select_value')!r} (target {wanted!r}) at click time",
                )
        final_rows = self._readback_targets()
        drift["targets"] = final_rows
        if not final_rows.get("ok"):
            return stop("TARGETS_READBACK_UNREADABLE")
        read_rows = final_rows.get("rows") or []
        if len(read_rows) != len(targets):
            return stop(
                "TARGETS_COUNT_MISMATCH",
                f"{len(read_rows)} row(s) in the modal at click time, {len(targets)} target(s) wanted",
            )
        for index, (row, target) in enumerate(zip(read_rows, targets)):
            wanted_pid = str(target.get("aks_product_id") or "")
            got_pid = str(row.get("target_value") or "")
            if got_pid != wanted_pid:
                return stop(
                    "VALUE_DRIFTED_BEFORE_CLICK",
                    f"row {index} target reads {got_pid!r} (target {wanted_pid!r}) at click time",
                )
            for kind in ("region", "edition"):
                wanted_id = str(target.get(f"{kind}_id") or "")
                got = _readback_values(row.get(kind))
                if got != {wanted_id}:
                    return stop(
                        "VALUE_DRIFTED_BEFORE_CLICK",
                        f"row {index} {kind} reads {sorted(got)!r} (target {wanted_id!r}) at click time",
                    )

        click = self.click_trusted_at_element("#TB_ajaxContent .button-primary")
        prep["click"] = click
        if click.get("status") != "CLICKED":
            return stop("NO_TRUSTED_CLICK")

        poll = self._evaluate(_TRUSTED_POLL_JS)
        if isinstance(poll, dict):
            prep.update(poll)
        return prep

    def fill_then_click_trusted(
        self,
        region_select: str,
        region_id: str,
        edition_select: str,
        edition_id: str,
        target_value: str | None = None,
        region_query: str | None = None,
        edition_query: str | None = None,
    ) -> dict[str, Any]:
        """Trusted-click variant of ``fill_and_create`` — Selectize humanisé
        (Chantier n°1 extension, 2026-07-03):

        1. Prep JS: install network taps + record pre-existing signal state
           (counts + text snapshots) + button visibility. NO setValue.
        2. ``select_via_trusted(region_select, region_id, query=region_query)``:
           trusted CDP click on the Selectize UI (open), type the label to filter
           (renders options beyond the maxOptions cap), pick the option. Selectize
           fires its own events.
        3. ``select_via_trusted(edition_select, edition_id, query=edition_query)``:
           same.
        4. ``add_target_trusted(target_value)`` (when supplied): trusted type of
           the AKS product id / URL into ``offer[targets][]`` + commit — the last
           required field the Selectize picks don't populate. ``NO_ADD_BUTTON``
           (no add-button next to the field) STOPS the flow — no Enter fallback
           since 2026-09-14 (Enter natively submits the modal form).
           This is the ``targets_v1`` shape only; ``targets_v2`` (the current
           tool) goes through ``fill_targets_v2_trusted``.
        5. ``form_validity()``: read-only HTML5 validity gate — HARD (audit
           P1b, 2026-07-08). Form positively invalid → STOP with
           ``status='FORM_INVALID'`` (+ the offending field names); probe
           unreadable (ok:false) → STOP with ``FORM_VALIDITY_UNREADABLE``.
           Either way: do NOT click Create. A click on an invalid form fires
           zero requests and looks like "the site ignored the robot".
        6. ``click_trusted_at_element("#TB_ajaxContent .button-primary")``:
           trusted CDP click on the submit button center.
        7. Poll JS: accept either a NEW [data-success]/[data-error] node OR a
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

        region_pick = self.select_via_trusted(region_select, str(region_id), query=region_query)
        prep["region_pick"] = region_pick
        if region_pick.get("status") != "SELECTED":
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "NO_REGION_PICK"
            return prep

        edition_pick = self.select_via_trusted(edition_select, str(edition_id), query=edition_query)
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

        # offer[targets][] — the last required field the Selectize picks don't
        # touch (S18, 2026-07-06). Fill it (trusted type + commit) when a value
        # is supplied; the validity gate below is the fail-closed proof that it
        # actually cleared `required`. No hard-fail here: a wrong/absent target
        # simply leaves the form invalid, which FORM_INVALID reports.
        if target_value:
            prep["target_add"] = self.add_target_trusted(str(target_value))
            if prep["target_add"].get("status") == "NO_ADD_BUTTON":
                # The typed id sits UNCOMMITTED in the chip field and the Enter
                # fallback is gone (2026-09-14: Enter natively submits the modal
                # form). No click on a half-entered form.
                self._evaluate(_TRUSTED_CLEANUP_JS)
                prep["status"] = "NO_ADD_BUTTON"
                prep["reason"] = prep["target_add"].get("reason")
                return prep

        # Fail-closed validity gate — HARD (Romain's audit P1b, 2026-07-08): a
        # submit button whose form is invalid swallows the trusted click (the
        # browser blocks the submit, ZERO admin-ajax fired) — indistinguishable
        # at the click level from "the site ignored a robot click". Prove
        # validity BEFORE clicking. Positively invalid → FORM_INVALID (+ the
        # offending fields). Probe unreadable (ok:false) → also NO CLICK
        # (FORM_VALIDITY_UNREADABLE): continuing to the click on a form we
        # could not read was an explicit degraded mode, and degraded modes are
        # banned. The rules make form validity a hard gate before any click.
        validity = self.form_validity()
        prep["form_validity"] = validity
        if not validity.get("ok"):
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "FORM_VALIDITY_UNREADABLE"
            return prep
        if validity.get("form_valid") is not True:
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "FORM_INVALID"
            return prep

        # Pre-click obstruction guard (fail-closed): the point we are about to
        # click must actually BE the Create button. A body-parented Selectize
        # dropdown left open over the button made yesterday's mousedown re-pick
        # a random edition before the form was serialized (wrong-edition root
        # cause). Only a positive "something else is at that point" blocks; a
        # probe that can't read (ok:false) degrades to the click's own checks.
        path_probe = self.click_target_probe("#TB_ajaxContent .button-primary")
        prep["click_path"] = path_probe
        if path_probe.get("ok") and not path_probe.get("is_target"):
            self._evaluate(_TRUSTED_CLEANUP_JS)
            prep["status"] = "CLICK_PATH_OBSTRUCTED"
            return prep

        # Last gate before the ONE write of the whole pipeline: both selects
        # must STILL hold the wanted ids at click time. The picks were
        # verified when they landed (select_via_trusted readback, SC3), but
        # everything between then and now — target typing, scrolls, a stray
        # dropdown — could have changed a value; the form stays valid with
        # ANY option so no other gate would notice (audit 2026-07-17, SC3).
        drift: dict[str, Any] = {}
        for kind, name, target in (
            ("region", region_select, str(region_id)),
            ("edition", edition_select, str(edition_id)),
        ):
            final = self._readback_select(name)
            drift[kind] = final
            if not final.get("ok") or str(final.get("select_value") or "") != target:
                self._evaluate(_TRUSTED_CLEANUP_JS)
                prep["pre_click_readback"] = drift
                prep["status"] = "VALUE_DRIFTED_BEFORE_CLICK"
                prep["reason"] = (
                    f"{kind} reads {final.get('select_value')!r} "
                    f"(target {target!r}) at click time"
                )
                return prep
        prep["pre_click_readback"] = drift

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

    # ------------------------------------------------------------------
    # Move to List (brique B) — the second mutating op. The mechanic is a
    # native bulk form POST (docs/AKS_LISTS.md, confirmed read-only 2026-07-21):
    # a TRUSTED checkbox change registers the offer (a scripted .checked is
    # ignored — same isTrusted wall as Create), then a TRUSTED Apply submits.
    # ------------------------------------------------------------------
    def register_row(self, offer_id: str) -> dict[str, Any]:
        """Register ``offer_id`` in the bulk form (inject its hidden bulk[item][]).

        Deterministic: a trusted checkbox click proved fragile on paginated feed
        pages (the async change handler did not inject the hidden). Injecting the
        hidden directly produces the same DOM the tick would, and the native Apply
        POST serializes it identically. Returns ``{registered, bulk_list_value,
        method}`` — ``registered`` confirms the input is present in the form."""

        raw = self._evaluate(_INJECT_BULK_ITEM_JS % json.dumps(str(offer_id)))
        state = json.loads(raw) if raw else {"registered": False, "reason": "no_result"}
        return {"method": "inject", **state}

    def set_bulk_list(self, target_list_id: str) -> str:
        """Set the bulk ``bulk[list]`` select to ``target_list_id`` (read back)."""

        return str(self._evaluate(_SET_BULK_LIST_JS % json.dumps(str(target_list_id))))

    def click_apply(self) -> dict[str, Any]:
        """Trusted-click the bulk-form Apply <button> — fires the native POST."""

        return self.click_trusted_at_element("form[data-bulk-form] button")
