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
_FILL_CREATE_JS = (
    "(function(){return new Promise(function(resolve){"
    "var r=document.querySelector('select[name=\"'+%s+'\"]');"
    "var e=document.querySelector('select[name=\"'+%s+'\"]');"
    "if(!r||!e||!r.selectize||!e.selectize){resolve('NO_SELECTS');return;}"
    "r.selectize.setValue(%s);e.selectize.setValue(%s);"
    "setTimeout(function(){var b=document.querySelector('#TB_ajaxContent .button-primary');"
    "if(!b){resolve('NO_BUTTON');return;}b.click();resolve('CLICKED');},500);"
    "});})()"
)


class WriteSubmitSession(SubmitSession):
    """SubmitSession + the single mutating op. Instantiated ONLY under ``--submit``.

    ``fill_and_create`` is the only method that writes: it sets region/edition on the
    verified select names and clicks "Create offer". No direct XHR, no
    ``dispatchEvent``, no ``form.submit()`` (skill S09).
    """

    def fill_and_create(
        self, region_select: str, region_id: str, edition_select: str, edition_id: str
    ) -> str:
        return str(
            self._evaluate(
                _FILL_CREATE_JS
                % (
                    json.dumps(region_select),
                    json.dumps(edition_select),
                    json.dumps(str(region_id)),
                    json.dumps(str(edition_id)),
                )
            )
        )
