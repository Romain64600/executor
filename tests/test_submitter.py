import json
import re
import unittest

from src.submitter import DryRunSubmitter, InspectSubmitter, Submitter


def _cand(offer_id, region_id="2", edition_id="1"):
    return {
        "fingerprint": f"{offer_id}|1|{region_id}|{edition_id}",
        "offer": {
            "offer_id": offer_id, "name": f"Game {offer_id}", "url": "https://m/x",
            "merchant": "Driffle", "store_id": "127", "price": None, "stock": None,
        },
        "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": f"Game {offer_id}",
        "platform": "STEAM",
        "region": {"label": "GLOBAL", "id": region_id, "implicit": False},
        "edition": {"label": "Standard", "id": edition_id},
    }


class FakeSubmitSession:
    def __init__(self, pages, *, login=False, modal_status="OPENED",
                 select_names=("offer[region]", "offer[edition]"), ctx_ok=True, fail_ids=()):
        self.pages = pages
        self.login = login
        self.modal_status = modal_status
        self.select_names = list(select_names)
        self.ctx_ok = ctx_ok
        self.fail_ids = set(fail_ids)
        self.nav = []
        self._page = 0

    def navigate(self, url, settle=0):
        self.nav.append(url)
        m = re.search(r"[&?]p=(\d+)", url)
        self._page = (int(m.group(1)) - 1) if m else 0

    def is_login_page(self):
        return self.login

    def page_offer_ids(self):
        return list(self.pages[self._page]) if 0 <= self._page < len(self.pages) else []

    def open_offer_modal(self, offer_id):
        return "ROW_NOT_FOUND" if offer_id in self.fail_ids else self.modal_status

    def modal_context(self):
        return {"ok": self.ctx_ok, "select_names": list(self.select_names)}

    def probe_select_options(self, select_name):
        # A minimal live "master catalog" so the write path's catalog resolution
        # (resolve_catalog_id) can map the _cand labels/ids: region GLOBAL→2,
        # Steam EU→9; edition Standard→1, Deluxe→7.
        if "region" in select_name:
            master = [{"key": "2", "text": "GLOBAL"}, {"key": "9", "text": "Steam EU (9)"}]
        else:
            master = [{"key": "1", "text": "Standard"}, {"key": "7", "text": "Deluxe"}]
        return {"ok": True, "select_name": select_name, "rendered_count": 2,
                "rendered_options": [{"data_value": "77", "text": "Standard"}],
                "master_options": master}


def _run(session, approved):
    return DryRunSubmitter(session).run(
        run_id="r", merchant="Driffle", store_id="127", approved=approved, pace=0
    )


class DryRunTests(unittest.TestCase):
    def test_login_preflight_aborts(self):
        result = _run(FakeSubmitSession([["1"]], login=True), [_cand("1")])
        self.assertEqual(result["aborted"], "not_logged_in")
        self.assertEqual(result["plan"], [])

    def test_ready_plan(self):
        result = _run(FakeSubmitSession([["1", "2"]]), [_cand("1"), _cand("2")])
        self.assertIsNone(result["aborted"])
        self.assertIsNone(result["stopped"])
        self.assertTrue(all(p["ready"] for p in result["plan"]))
        self.assertEqual(result["feed_offers"], 2)
        self.assertIn("offer[region]=2", result["plan"][0]["would_submit"])

    def test_offer_not_in_feed_is_skipped(self):
        result = _run(FakeSubmitSession([["1"]]), [_cand("1"), _cand("9")])
        by_id = {p["offer_id"]: p for p in result["plan"]}
        self.assertTrue(by_id["1"]["ready"])
        self.assertFalse(by_id["9"]["ready"])
        self.assertIn("not in current feed", by_id["9"]["blocker"])

    def test_modal_open_failure_is_skipped(self):
        result = _run(FakeSubmitSession([["1", "2"]], fail_ids={"2"}), [_cand("1"), _cand("2")])
        by_id = {p["offer_id"]: p for p in result["plan"]}
        self.assertTrue(by_id["1"]["ready"])
        self.assertFalse(by_id["2"]["ready"])

    def test_region_select_missing_is_skipped(self):
        result = _run(FakeSubmitSession([["1"]], select_names=("offer[edition]",)), [_cand("1")])
        self.assertFalse(result["plan"][0]["ready"])
        self.assertIn("select not found", result["plan"][0]["blocker"])

    def test_region_id_select_convention(self):
        session = FakeSubmitSession([["1"]], select_names=("offer[region_id]", "offer[edition_id]"))
        result = _run(session, [_cand("1")])
        self.assertTrue(result["plan"][0]["ready"])
        self.assertEqual(result["plan"][0]["region_select"], "offer[region_id]")

    def test_stops_after_ten_consecutive_failures(self):
        ids = [str(i) for i in range(12)]
        session = FakeSubmitSession([ids], fail_ids=set(ids))
        result = _run(session, [_cand(i) for i in ids])
        self.assertEqual(result["stopped"], "ten_consecutive_failures")
        self.assertEqual(len(result["plan"]), 10)  # stopped after the 10th consecutive failure


class FakeWriteSession(FakeSubmitSession):
    def __init__(self, pages, *, create_status="SUCCESS", create_signal=None,
                 create_removes=True, form_validity=None, **kw):
        super().__init__(pages, **kw)
        self.create_status = create_status
        self.create_signal = create_signal
        self.create_removes = create_removes
        self.form_validity = form_validity
        self.created = set()
        self.fill_calls = []
        self.last_target_value = None
        self.last_region_query = None
        self.last_edition_query = None
        self._last_opened = None

    def open_offer_modal(self, offer_id):
        self._last_opened = offer_id
        return super().open_offer_modal(offer_id)

    def page_offer_ids(self):
        return [i for i in super().page_offer_ids() if i not in self.created]

    def fill_and_create(self, region_select, region_id, edition_select, edition_id, click_mode="native"):
        self.fill_calls.append((region_select, region_id, edition_select, edition_id, click_mode))
        if self.create_status in ("SUCCESS", "NO_SIGNAL") and self.create_removes:
            self.created.add(self._last_opened)
        diag = {"status": self.create_status, "region_set": region_id, "edition_set": edition_id,
                "region_options": ["1", "2", "9"], "edition_options": ["1"],
                "click_mode": click_mode, "requests": [], "pre_existing": {"success": 0, "error": 0}}
        if self.create_signal:
            diag["signal"] = self.create_signal
        return diag

    def fill_then_click_trusted(self, region_select, region_id, edition_select, edition_id,
                                target_value=None, region_query=None, edition_query=None):
        self.fill_calls.append((region_select, region_id, edition_select, edition_id, "trusted"))
        self.last_target_value = target_value
        self.last_region_query = region_query
        self.last_edition_query = edition_query
        if self.create_status in ("SUCCESS", "NO_SIGNAL") and self.create_removes:
            self.created.add(self._last_opened)
        diag = {"status": self.create_status, "region_set": region_id, "edition_set": edition_id,
                "region_options": ["1", "2", "9"], "edition_options": ["1"],
                "click_mode": "trusted", "requests": [], "pre_existing": {"success": 0, "error": 0},
                "click": {"selector": "#TB_ajaxContent .button-primary", "mode": "trusted",
                          "viewport": {"w": 1280, "h": 720}, "rect": {"x": 500, "y": 400, "w": 120, "h": 40},
                          "scrolled": False, "click_x": 560, "click_y": 420, "delay_ms": 60,
                          "status": "CLICKED"}}
        if self.create_signal:
            diag["signal"] = self.create_signal
        if self.form_validity is not None:
            diag["form_validity"] = self.form_validity
        return diag


def _real(session, approved, click_mode="native", **kw):
    return Submitter(session, click_mode=click_mode).run(
        run_id="r", merchant="Driffle", store_id="127", approved=approved, pace=0, **kw
    )


class RealSubmitTests(unittest.TestCase):
    def test_canary_creates_one_then_stops(self):
        session = FakeWriteSession([["1", "2"]])
        result = _real(session, [_cand("1"), _cand("2")], limit=1)
        self.assertEqual(result["writes"], 1)
        self.assertEqual(result["stopped"], "limit_reached")
        self.assertEqual(len(result["plan"]), 1)
        self.assertTrue(result["plan"][0]["submitted"])
        self.assertEqual(session.fill_calls, [("offer[region]", "2", "offer[edition]", "1", "native")])

    def test_full_batch_creates_all(self):
        session = FakeWriteSession([["1", "2"]])
        result = _real(session, [_cand("1"), _cand("2")], limit=None)
        self.assertEqual(result["writes"], 2)
        self.assertTrue(all(p["submitted"] for p in result["plan"]))

    def test_still_present_after_create_is_failure(self):
        session = FakeWriteSession([["1"]], create_removes=False)
        result = _real(session, [_cand("1")], limit=1)
        self.assertFalse(result["plan"][0]["submitted"])
        self.assertIn("STILL in pending", result["plan"][0]["post_save"])

    def test_create_not_confirmed_is_failure(self):
        session = FakeWriteSession([["1"]], create_status="NO_SELECTS")
        result = _real(session, [_cand("1")], limit=1)
        self.assertEqual(result["plan"][0]["create"]["status"], "NO_SELECTS")
        self.assertIn("create not confirmed", result["plan"][0]["post_save"])

    def test_server_error_is_reported(self):
        session = FakeWriteSession([["1"]], create_status="ERROR", create_signal="region invalid")
        result = _real(session, [_cand("1")], limit=1)
        self.assertFalse(result["plan"][0].get("submitted"))
        self.assertEqual(result["plan"][0]["create"]["status"], "ERROR")
        self.assertIn("region invalid", result["plan"][0]["post_save"])
        self.assertTrue(session.fill_calls)  # it did attempt

    def test_no_signal_still_verifies_feed(self):
        session = FakeWriteSession([["1"]], create_status="NO_SIGNAL")  # settled, no signal
        result = _real(session, [_cand("1")], limit=1)
        self.assertTrue(result["plan"][0]["submitted"])  # gone from feed = success

    def test_not_ready_offer_is_not_written(self):
        session = FakeWriteSession([["1"]])  # offer "9" absent from feed
        result = _real(session, [_cand("9")], limit=1)
        self.assertEqual(session.fill_calls, [])  # never wrote
        self.assertFalse(result["plan"][0]["ready"])

    def test_dispatch_click_mode_is_passed_through(self):
        session = FakeWriteSession([["1"]])
        result = _real(session, [_cand("1")], click_mode="dispatch", limit=1)
        self.assertEqual(session.fill_calls[0][-1], "dispatch")
        self.assertEqual(result["plan"][0]["create"]["click_mode"], "dispatch")
        # The derogation NEVER weakens the proof: post-save still decides.
        self.assertTrue(result["plan"][0]["submitted"])

    def test_dispatch_mode_still_fails_when_still_pending(self):
        session = FakeWriteSession([["1"]], create_removes=False)
        result = _real(session, [_cand("1")], click_mode="dispatch", limit=1)
        self.assertFalse(result["plan"][0]["submitted"])
        self.assertIn("STILL in pending", result["plan"][0]["post_save"])

    def test_default_click_mode_is_trusted(self):
        # native/dispatch are proven dead on Driffle; the class default must be
        # the only working mode. Construct Submitter WITHOUT click_mode to assert
        # the class default (not the _real helper's explicit native).
        session = FakeWriteSession([["1"]])
        Submitter(session).run(
            run_id="r", merchant="Driffle", store_id="127",
            approved=[_cand("1")], pace=0, limit=1,
        )
        self.assertEqual(session.fill_calls[0][-1], "trusted")

    def test_trusted_click_mode_routes_to_fill_then_click_trusted(self):
        session = FakeWriteSession([["1"]])
        result = _real(session, [_cand("1")], click_mode="trusted", limit=1)
        self.assertEqual(session.fill_calls[0][-1], "trusted")
        self.assertEqual(result["plan"][0]["create"]["click_mode"], "trusted")
        self.assertEqual(result["plan"][0]["create"]["click"]["status"], "CLICKED")
        # Non-négociable: post-save reste seul juge, même en trusted.
        self.assertTrue(result["plan"][0]["submitted"])

    def test_trusted_mode_still_fails_when_still_pending(self):
        session = FakeWriteSession([["1"]], create_removes=False)
        result = _real(session, [_cand("1")], click_mode="trusted", limit=1)
        self.assertFalse(result["plan"][0]["submitted"])
        self.assertIn("STILL in pending", result["plan"][0]["post_save"])

    def test_trusted_form_invalid_is_reported_and_not_submitted(self):
        fv = {"ok": True, "form_valid": False, "checked": 4,
              "invalid_required": [{"name": "offer[targets][]", "valueMissing": True}]}
        session = FakeWriteSession([["1"]], create_status="FORM_INVALID", form_validity=fv)
        result = _real(session, [_cand("1")], click_mode="trusted", limit=1)
        self.assertFalse(result["plan"][0].get("submitted"))
        self.assertEqual(result["plan"][0]["create"]["status"], "FORM_INVALID")
        self.assertIn("invalid required fields", result["plan"][0]["post_save"])
        self.assertIn("offer[targets][]", result["plan"][0]["post_save"])

    def test_trusted_threads_aks_product_id_as_target(self):
        # offer[targets][] wants the AKS product id — the trusted path must pass
        # the candidate's aks_product_id down as target_value (S18, 2026-07-06).
        session = FakeWriteSession([["1"]])
        _real(session, [_cand("1")], click_mode="trusted", limit=1)
        self.assertEqual(session.last_target_value, "1")

    def test_native_path_does_not_thread_target(self):
        # Only the trusted path fills offer[targets][]; native never touches it.
        session = FakeWriteSession([["1"]])
        _real(session, [_cand("1")], click_mode="native", limit=1)
        self.assertIsNone(session.last_target_value)


class ClickModeValidationTests(unittest.TestCase):
    def test_unknown_click_mode_is_refused(self):
        from src.submit_session import WriteSubmitSession

        session = WriteSubmitSession.__new__(WriteSubmitSession)  # no socket needed
        with self.assertRaises(ValueError):
            session.fill_and_create("offer[region]", "9", "offer[edition]", "1", click_mode="xhr")

    def test_submitter_refuses_unknown_click_mode_at_init(self):
        session = FakeWriteSession([["1"]])
        with self.assertRaises(ValueError):
            Submitter(session, click_mode="xhr")

    def test_submitter_accepts_all_three_click_modes(self):
        session = FakeWriteSession([["1"]])
        for mode in ("native", "dispatch", "trusted"):
            Submitter(session, click_mode=mode)  # no raise


class FetchSessionCatalogTests(unittest.TestCase):
    def test_fetches_both_dropdowns_from_first_openable_offer(self):
        from src.submitter import fetch_session_catalog

        session = FakeSubmitSession([["10", "11"]])
        result = fetch_session_catalog(session, store_id="127")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offer_id"], "10")
        self.assertEqual(result["region_select"], "offer[region]")
        self.assertEqual(result["edition_select"], "offer[edition]")
        self.assertEqual(result["editions"]["rendered_options"],
                         [{"data_value": "77", "text": "Standard"}])
        self.assertEqual(result["regions"]["rendered_options"],
                         [{"data_value": "77", "text": "Standard"}])

    def test_login_page_aborts(self):
        from src.submitter import fetch_session_catalog

        result = fetch_session_catalog(FakeSubmitSession([["10"]], login=True), store_id="127")
        self.assertEqual(result, {"ok": False, "reason": "not_logged_in"})

    def test_skips_offers_whose_modal_wont_open(self):
        from src.submitter import fetch_session_catalog

        session = FakeSubmitSession([["10", "11"]], fail_ids=("10",))
        result = fetch_session_catalog(session, store_id="127")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offer_id"], "11")

    def test_no_openable_offer_is_fail_closed(self):
        from src.submitter import fetch_session_catalog

        result = fetch_session_catalog(FakeSubmitSession([[]]), store_id="127")
        self.assertEqual(result, {"ok": False, "reason": "no_openable_offer"})


class ResolveCatalogIdTests(unittest.TestCase):
    REGIONS = [{"key": "2", "text": "GLOBAL"}, {"key": "9", "text": "Steam EU (9)"}]
    EDITIONS = [{"key": "1", "text": "Standard"}, {"key": "7", "text": "Deluxe"}]

    def test_unambiguous_label_match_wins_over_stale_id(self):
        from src.submitter import resolve_catalog_id

        # Matcher had a stale id (999) but the label maps cleanly → trust label.
        r = resolve_catalog_id("Deluxe", "999", self.EDITIONS)
        self.assertEqual(r["id"], "7")
        self.assertEqual(r["text"], "Deluxe")
        self.assertEqual(r["source"], "label")
        self.assertTrue(r["changed"])
        self.assertEqual(r["matcher_id"], "999")

    def test_label_match_agrees_with_id_is_not_flagged_changed(self):
        from src.submitter import resolve_catalog_id

        r = resolve_catalog_id("Standard", "1", self.EDITIONS)
        self.assertEqual(r["id"], "1")
        self.assertFalse(r["changed"])

    def test_ambiguous_label_falls_back_to_validated_id(self):
        from src.submitter import resolve_catalog_id

        # A bare "EU" label matches no single catalog text (regions are composite
        # like "Steam EU (9)"); fall back to the matcher's id and take its text.
        r = resolve_catalog_id("EU", "9", self.REGIONS)
        self.assertEqual(r["id"], "9")
        self.assertEqual(r["text"], "Steam EU (9)")
        self.assertEqual(r["source"], "id")
        self.assertFalse(r["changed"])

    def test_region_suffix_is_stripped_for_matching(self):
        from src.submitter import resolve_catalog_id

        # The label carries the "(9)" suffix exactly as the catalog renders it.
        r = resolve_catalog_id("Steam EU (9)", "2", self.REGIONS)
        self.assertEqual(r["id"], "9")
        self.assertEqual(r["source"], "label")
        self.assertTrue(r["changed"])

    def test_unknown_label_and_id_is_fail_closed(self):
        from src.submitter import resolve_catalog_id

        self.assertIsNone(resolve_catalog_id("Nonesuch", "424242", self.EDITIONS))


class CatalogResolutionInWritePathTests(unittest.TestCase):
    def test_write_path_fetches_catalog_and_threads_labels_as_queries(self):
        session = FakeWriteSession([["1"]])
        result = _real(session, [_cand("1")], click_mode="trusted", limit=1)
        # Catalog was fetched once and summarized in the result.
        self.assertEqual(result["catalog"]["regions_count"], 2)
        self.assertEqual(result["catalog"]["editions_count"], 2)
        # The canonical catalog text is threaded down as the type-to-filter query.
        self.assertEqual(session.last_region_query, "GLOBAL")
        self.assertEqual(session.last_edition_query, "Standard")
        entry = result["plan"][0]
        self.assertEqual(entry["edition_resolution"]["source"], "label")
        self.assertEqual(entry["edition_text"], "Standard")

    def test_stale_edition_id_is_overridden_by_catalog_label(self):
        cand = _cand("1", edition_id="999")
        cand["edition"]["label"] = "Deluxe"
        session = FakeWriteSession([["1"]])
        result = Submitter(session, click_mode="trusted").run(
            run_id="r", merchant="Driffle", store_id="127", approved=[cand], pace=0, limit=1,
        )
        # Resolution swapped the stale 999 for the live Deluxe id (7) and the
        # trusted fill used the resolved id, not the matcher's.
        self.assertEqual(result["plan"][0]["edition_id"], "7")
        self.assertTrue(result["plan"][0]["edition_resolution"]["changed"])
        self.assertEqual(session.fill_calls[0], ("offer[region]", "2", "offer[edition]", "7", "trusted"))
        self.assertEqual(session.last_edition_query, "Deluxe")

    def test_label_absent_from_catalog_blocks_offer_no_write(self):
        cand = _cand("1", edition_id="424242")
        cand["edition"]["label"] = "Phantom Edition"
        session = FakeWriteSession([["1"]])
        result = _real(session, [cand], click_mode="trusted", limit=1)
        entry = result["plan"][0]
        self.assertFalse(entry["ready"])
        self.assertIn("edition not in session catalog", entry["blocker"])
        self.assertEqual(session.fill_calls, [])  # fail-closed: never wrote

    def test_catalog_unavailable_aborts_before_any_write(self):
        session = FakeWriteSession([[]])  # no openable offer → catalog fetch fails
        result = _real(session, [_cand("1")], click_mode="trusted", limit=1)
        self.assertEqual(result["aborted"], "catalog_unavailable")
        self.assertEqual(result["plan"], [])
        self.assertEqual(session.fill_calls, [])


class FakeInspectSession(FakeSubmitSession):
    def __init__(self, pages, *, inspection=None, form_validity=None, targets_probe=None, **kw):
        super().__init__(pages, **kw)
        self.inspection = inspection or {
            "modal_ok": True,
            "button": {"tag": "A", "type_prop": None, "href": "#"},
            "button_count_in_modal": 1,
            "form": None,
            "forms_in_modal": 0,
        }
        self._form_validity = form_validity or {
            "ok": True, "form_valid": False, "checked": 3,
            "invalid_required": [{"name": "offer[targets][]", "valueMissing": True}],
        }
        self._targets_probe = targets_probe or {
            "ok": True, "count": 1,
            "targets": [{
                "tag": "INPUT", "type": "text", "name": "offer[targets][]",
                "required": True, "value_len": 0, "placeholder": "Add a target",
                "list_attr": None, "label": "Targets", "data_attrs": {},
                "parents": ["div.form-row"], "next_sibs": [],
            }],
        }
        self.inspect_calls = 0

    def inspect_modal_dom(self):
        self.inspect_calls += 1
        return dict(self.inspection)

    def form_validity(self):
        return dict(self._form_validity)

    def probe_targets_field(self):
        return dict(self._targets_probe)

    def probe_select_options(self, select_name):
        return {"ok": True, "select_name": select_name, "rendered_options": []}


def _inspect(session, approved):
    return InspectSubmitter(session).run(
        run_id="r", merchant="Driffle", store_id="127", approved=approved, pace=0
    )


class InspectSubmitterTests(unittest.TestCase):
    def test_inspects_ready_offers(self):
        session = FakeInspectSession([["1", "2"]])
        result = _inspect(session, [_cand("1"), _cand("2")])
        self.assertEqual(session.inspect_calls, 2)
        self.assertTrue(all("inspection" in p and p["inspection"]["modal_ok"] for p in result["plan"]))
        self.assertIsNone(result["aborted"])
        self.assertIsNone(result["stopped"])

    def test_inspect_captures_form_validity_inventory(self):
        session = FakeInspectSession([["1"]])
        result = _inspect(session, [_cand("1")])
        fv = result["plan"][0]["form_validity"]
        self.assertFalse(fv["form_valid"])
        names = [x["name"] for x in fv["invalid_required"]]
        self.assertIn("offer[targets][]", names)

    def test_inspect_captures_targets_probe(self):
        session = FakeInspectSession([["1"]])
        result = _inspect(session, [_cand("1")])
        probe = result["plan"][0]["targets_probe"]
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["targets"][0]["name"], "offer[targets][]")

    def test_skips_offer_not_in_feed_without_inspecting(self):
        session = FakeInspectSession([["1"]])  # "9" absent
        result = _inspect(session, [_cand("9")])
        self.assertEqual(session.inspect_calls, 0)
        self.assertFalse(result["plan"][0].get("ready"))
        self.assertNotIn("inspection", result["plan"][0])

    def test_login_preflight_aborts_inspect(self):
        session = FakeInspectSession([["1"]], login=True)
        result = _inspect(session, [_cand("1")])
        self.assertEqual(result["aborted"], "not_logged_in")
        self.assertEqual(session.inspect_calls, 0)

    def test_writes_none_in_inspect_mode(self):
        session = FakeInspectSession([["1"]])
        result = _inspect(session, [_cand("1")])
        # write_mode=False → writes reported as None (like dry-run).
        self.assertIsNone(result["writes"])


class TrustedClickTests(unittest.TestCase):
    """Unit tests on the real WriteSubmitSession, mocking the CDP transport."""

    def _fake_session(self, rects, *, patch_sleep=True):
        """Build a WriteSubmitSession with mocked evaluate_readonly + _cmd.

        ``rects`` is a list of dicts returned by successive `_read_rect` calls
        (first call = initial; second call = after-scroll if applicable). Each
        dict is either ``{"ok": False}`` or the full rect payload.
        """

        import unittest.mock as mock
        from src.submit_session import WriteSubmitSession

        sess = WriteSubmitSession.__new__(WriteSubmitSession)
        rect_iter = iter(rects)
        sess.evaluate_readonly = lambda js: json.dumps(next(rect_iter))
        sent = []
        sess._cmd = lambda method, params=None: sent.append((method, params)) or {}
        sess._sent = sent
        if patch_sleep:
            self._sleep_patch = mock.patch("src.submit_session.time.sleep")
            self._sleep_patch.start()
            self.addCleanup(self._sleep_patch.stop)
        self._rand_patch = mock.patch("src.submit_session.random.randint", return_value=60)
        self._rand_patch.start()
        self.addCleanup(self._rand_patch.stop)
        return sess

    def test_no_element_returns_no_element_status(self):
        import json as _json  # local alias to avoid shadow
        sess = self._fake_session([{"ok": False}])
        result = sess.click_trusted_at_element("#nope")
        self.assertEqual(result["status"], "NO_ELEMENT")
        self.assertEqual(sess._sent, [])  # no CDP command sent

    def test_in_viewport_sends_move_press_release_no_scroll(self):
        rect = {"ok": True, "x": 500, "y": 400, "width": 120, "height": 40,
                "top": 400, "left": 500, "bottom": 440, "right": 620,
                "viewport": {"w": 1280, "h": 720}}
        sess = self._fake_session([rect])
        result = sess.click_trusted_at_element("#TB_ajaxContent .button-primary")
        self.assertEqual(result["status"], "CLICKED")
        self.assertFalse(result["scrolled"])
        self.assertEqual(result["click_x"], 560.0)
        self.assertEqual(result["click_y"], 420.0)
        self.assertEqual(result["delay_ms"], 60)
        methods = [c[0] for c in sess._sent]
        self.assertEqual(methods, ["Input.dispatchMouseEvent"] * 3)
        types = [c[1]["type"] for c in sess._sent]
        self.assertEqual(types, ["mouseMoved", "mousePressed", "mouseReleased"])
        press, release = sess._sent[1][1], sess._sent[2][1]
        self.assertEqual(press["button"], "left")
        self.assertEqual(release["button"], "left")
        self.assertEqual(press["clickCount"], 1)
        self.assertEqual(release["clickCount"], 1)
        self.assertEqual(press["buttons"], 1)
        self.assertEqual(release["buttons"], 0)
        self.assertEqual(press["x"], release["x"])
        self.assertEqual(press["y"], release["y"])

    def test_out_of_viewport_triggers_scroll_gesture_then_click(self):
        rect_before = {"ok": True, "x": 500, "y": 1200, "width": 120, "height": 40,
                       "top": 1200, "left": 500, "bottom": 1240, "right": 620,
                       "viewport": {"w": 1280, "h": 720}}
        rect_after = {"ok": True, "x": 500, "y": 300, "width": 120, "height": 40,
                      "top": 300, "left": 500, "bottom": 340, "right": 620,
                      "viewport": {"w": 1280, "h": 720}}
        sess = self._fake_session([rect_before, rect_after])
        result = sess.click_trusted_at_element("#TB_ajaxContent .button-primary")
        self.assertEqual(result["status"], "CLICKED")
        self.assertTrue(result["scrolled"])
        self.assertIn("rect_after_scroll", result)
        methods = [c[0] for c in sess._sent]
        self.assertEqual(methods[0], "Input.synthesizeScrollGesture")
        self.assertEqual(methods[1:], ["Input.dispatchMouseEvent"] * 3)
        scroll = sess._sent[0][1]
        self.assertEqual(scroll["gestureSourceType"], "mouse")
        self.assertEqual(scroll["speed"], 800)
        # Button was below viewport (top=1200, vp=720), target_y=288, current_y=1220.
        # y_distance = current - target = 932 (positive → scroll down, CDP convention).
        self.assertGreater(scroll["yDistance"], 0)

    def test_element_disappears_after_scroll(self):
        rect_before = {"ok": True, "x": 500, "y": 1200, "width": 120, "height": 40,
                       "top": 1200, "left": 500, "bottom": 1240, "right": 620,
                       "viewport": {"w": 1280, "h": 720}}
        sess = self._fake_session([rect_before, {"ok": False}])
        result = sess.click_trusted_at_element("#TB_ajaxContent .button-primary")
        self.assertEqual(result["status"], "NO_ELEMENT_AFTER_SCROLL")
        # Scroll was sent, but no click follow-up.
        methods = [c[0] for c in sess._sent]
        self.assertEqual(methods, ["Input.synthesizeScrollGesture"])

    def test_rect_js_is_readonly(self):
        from src.cdp_session import is_readonly_expression
        from src.submit_session import _RECT_JS

        # It is a %s template; format it with a selector first.
        js = _RECT_JS % json.dumps("#TB_ajaxContent .button-primary")
        self.assertTrue(is_readonly_expression(js))


class FillThenClickTrustedTests(unittest.TestCase):
    def _sess(self, prep_result, region_pick, edition_pick, click_result, poll_result,
              form_validity=None):
        import unittest.mock as mock
        from src.submit_session import _TRUSTED_CLEANUP_JS, WriteSubmitSession

        sess = WriteSubmitSession.__new__(WriteSubmitSession)
        eval_seq = [prep_result, poll_result]
        cleanup_called = []

        def eval_stub(js):
            if js == _TRUSTED_CLEANUP_JS:
                cleanup_called.append(js)
                return True
            return eval_seq.pop(0)

        sess._evaluate = eval_stub
        sess.click_trusted_at_element = lambda selector=None: click_result
        pick_seq = [region_pick, edition_pick]
        sess.select_via_trusted = lambda name, val, query=None: pick_seq.pop(0)
        sess.form_validity = lambda: (
            form_validity if form_validity is not None
            else {"ok": True, "form_valid": True, "checked": 3, "invalid_required": []}
        )
        sess._cleanup_called = cleanup_called
        mock.patch("src.submit_session.time.sleep").start()
        self.addCleanup(mock.patch.stopall)
        return sess

    def _pick(self, value):
        return {"status": "SELECTED", "select_name": "?", "value_id": str(value),
                "readback": {"ok": True, "select_value": str(value),
                             "selectize_value": str(value), "validity_valid": True}}

    def test_success_flow_merges_prep_picks_click_and_poll(self):
        prep = {"status": "PREPARED",
                "region_options": ["9"], "edition_options": ["1"],
                "button": {"disabled": False, "visible": True, "text": "Create offer"},
                "pre_existing": {"success": 1, "error": 1}}
        click = {"status": "CLICKED", "click_x": 500, "click_y": 400,
                 "scrolled": False, "delay_ms": 60, "mode": "trusted"}
        poll = {"status": "SUCCESS", "polls": 3, "requests": [
            {"via": "xhr", "method": "POST", "url": "/wp-admin/admin-ajax.php", "status": 200}
        ], "signal": "Offer created"}
        sess = self._sess(prep, self._pick("9"), self._pick("1"), click, poll)
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["click_mode"], "trusted")
        self.assertEqual(result["click"], click)
        self.assertEqual(result["region_pick"]["status"], "SELECTED")
        self.assertEqual(result["edition_pick"]["status"], "SELECTED")
        self.assertEqual(result["region_target"], "9")
        self.assertEqual(result["region_set"], "9")
        self.assertEqual(result["edition_set"], "1")
        self.assertEqual(result["signal"], "Offer created")
        self.assertEqual(len(result["requests"]), 1)

    def test_no_selects_returns_early_no_click(self):
        prep = {"status": "NO_SELECTS"}
        sess = self._sess(prep, self._pick("9"), self._pick("1"),
                          {"status": "CLICKED"}, {"status": "SUCCESS"})
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "NO_SELECTS")

    def test_no_region_pick_triggers_cleanup(self):
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        region_fail = {"status": "NO_SELECTIZE_INPUT", "reason": "no_wrapper"}
        sess = self._sess(prep, region_fail, self._pick("1"),
                          {"status": "CLICKED"}, {"status": "SUCCESS"})
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "NO_REGION_PICK")
        self.assertEqual(result["region_pick"], region_fail)
        self.assertEqual(len(sess._cleanup_called), 1)

    def test_no_edition_pick_triggers_cleanup(self):
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        edition_fail = {"status": "NO_OPTION", "reason": "no_option"}
        sess = self._sess(prep, self._pick("9"), edition_fail,
                          {"status": "CLICKED"}, {"status": "SUCCESS"})
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "NO_EDITION_PICK")
        self.assertEqual(result["edition_pick"], edition_fail)
        self.assertEqual(len(sess._cleanup_called), 1)

    def test_form_invalid_blocks_click_and_cleans_up(self):
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        invalid = {"ok": True, "form_valid": False, "checked": 4,
                   "invalid_required": [{"name": "offer[targets][]", "valueMissing": True}]}
        sess = self._sess(prep, self._pick("9"), self._pick("1"),
                          {"status": "CLICKED"}, {"status": "SUCCESS"}, form_validity=invalid)
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "FORM_INVALID")
        self.assertEqual(result["form_validity"], invalid)
        self.assertEqual(len(sess._cleanup_called), 1)
        # The click was never attempted (form is invalid → submit would be a no-op).
        self.assertNotIn("click", result)

    def test_unreadable_form_validity_does_not_block(self):
        # A probe that can't read the form (ok:false) must NOT block — post-save
        # stays the real proof, so behaviour degrades to the prior click path.
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        click = {"status": "CLICKED", "mode": "trusted"}
        poll = {"status": "SUCCESS", "polls": 2, "requests": [], "signal": "ok"}
        sess = self._sess(prep, self._pick("9"), self._pick("1"), click, poll,
                          form_validity={"ok": False, "reason": "no_form"})
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["click"], click)

    def test_no_element_click_triggers_cleanup(self):
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        click = {"status": "NO_ELEMENT", "selector": "#TB_ajaxContent .button-primary"}
        sess = self._sess(prep, self._pick("9"), self._pick("1"), click,
                          {"status": "SUCCESS"})
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(result["status"], "NO_TRUSTED_CLICK")
        self.assertEqual(result["click"], click)
        self.assertEqual(len(sess._cleanup_called), 1)

    def test_target_value_fills_targets_and_stores_diag(self):
        # A supplied target_value drives add_target_trusted; its diag lands under
        # prep["target_add"] and the flow still reaches the validity gate + click.
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        click = {"status": "CLICKED", "mode": "trusted"}
        poll = {"status": "SUCCESS", "polls": 2, "requests": [], "signal": "ok"}
        sess = self._sess(prep, self._pick("9"), self._pick("1"), click, poll)
        target_calls = []
        sess.add_target_trusted = lambda val: (
            target_calls.append(val) or {"status": "ADDED", "value": val, "commit": "button"}
        )
        result = sess.fill_then_click_trusted(
            "offer[region]", "9", "offer[edition]", "1", target_value="210529"
        )
        self.assertEqual(target_calls, ["210529"])
        self.assertEqual(result["target_add"]["status"], "ADDED")
        self.assertEqual(result["target_add"]["value"], "210529")
        self.assertEqual(result["status"], "SUCCESS")

    def test_no_target_value_skips_target_fill(self):
        prep = {"status": "PREPARED", "region_options": ["9"], "edition_options": ["1"],
                "button": {}, "pre_existing": {"success": 0, "error": 0}}
        click = {"status": "CLICKED", "mode": "trusted"}
        poll = {"status": "SUCCESS", "polls": 2, "requests": [], "signal": "ok"}
        sess = self._sess(prep, self._pick("9"), self._pick("1"), click, poll)
        called = []
        sess.add_target_trusted = lambda val: called.append(val)
        result = sess.fill_then_click_trusted("offer[region]", "9", "offer[edition]", "1")
        self.assertEqual(called, [])
        self.assertNotIn("target_add", result)


class SelectViaTrustedTests(unittest.TestCase):
    def _sess(self, evaluate_readonly_results):
        import unittest.mock as mock
        from src.submit_session import WriteSubmitSession

        sess = WriteSubmitSession.__new__(WriteSubmitSession)
        seq = list(evaluate_readonly_results)
        sess.evaluate_readonly = lambda js: seq.pop(0) if seq else ""
        sent: list = []
        sess._cmd = lambda method, params=None: sent.append((method, params)) or {}
        sess._sent = sent
        mock.patch("src.submit_session.time.sleep").start()
        mock.patch("src.submit_session.random.randint", return_value=55).start()
        self.addCleanup(mock.patch.stopall)
        return sess

    def test_success_reads_input_option_readback_and_clicks_twice(self):
        input_rect = json.dumps({"ok": True, "x": 100, "y": 200, "width": 240, "height": 32,
                                 "top": 200, "left": 100, "bottom": 232, "right": 340,
                                 "viewport": {"w": 1280, "h": 720}})
        option_rect = json.dumps({"ok": True, "x": 100, "y": 240, "width": 240, "height": 24,
                                  "top": 240, "left": 100, "bottom": 264, "right": 340,
                                  "viewport": {"w": 1280, "h": 720}})
        readback = json.dumps({"ok": True, "select_value": "9",
                               "selectize_value": "9", "validity_valid": True})
        sess = self._sess([input_rect, option_rect, readback])
        result = sess.select_via_trusted("offer[region]", "9")
        self.assertEqual(result["status"], "SELECTED")
        self.assertEqual(result["select_name"], "offer[region]")
        self.assertEqual(result["value_id"], "9")
        self.assertEqual(result["readback"]["selectize_value"], "9")
        # Two trusted clicks: 3 Input.dispatchMouseEvent per click × 2 = 6 events
        methods = [c[0] for c in sess._sent]
        self.assertEqual(methods, ["Input.dispatchMouseEvent"] * 6)
        types = [c[1]["type"] for c in sess._sent]
        self.assertEqual(types, ["mouseMoved", "mousePressed", "mouseReleased"] * 2)
        # First click at input center (100+120, 200+16) = (220, 216)
        self.assertEqual(sess._sent[1][1]["x"], 220.0)
        self.assertEqual(sess._sent[1][1]["y"], 216.0)
        # Second click at option center (100+120, 240+12) = (220, 252)
        self.assertEqual(sess._sent[4][1]["x"], 220.0)
        self.assertEqual(sess._sent[4][1]["y"], 252.0)

    def test_query_types_label_to_filter_then_clicks_option(self):
        # The wanted option may be beyond Selectize's ~1000 render cap, so a
        # query must be TYPED with per-char trusted key events after opening the
        # dropdown and before reading/clicking the option. Key events (not
        # Input.insertText) are mandatory: Selectize v0.x refilters on keyup
        # only — insertText left the dropdown unfiltered on the 2026-07-07
        # canary (NO_EDITION_PICK).
        input_rect = json.dumps({"ok": True, "x": 100, "y": 200, "width": 240, "height": 32,
                                 "top": 200, "left": 100, "bottom": 232, "right": 340,
                                 "viewport": {"w": 1280, "h": 720}})
        option_rect = json.dumps({"ok": True, "x": 100, "y": 240, "width": 240, "height": 24,
                                  "top": 240, "left": 100, "bottom": 264, "right": 340,
                                  "viewport": {"w": 1280, "h": 720}})
        readback = json.dumps({"ok": True, "select_value": "1",
                               "selectize_value": "1", "validity_valid": True})
        sess = self._sess([input_rect, option_rect, readback])
        result = sess.select_via_trusted("offer[edition]", "1", query="Standard")
        self.assertEqual(result["status"], "SELECTED")
        self.assertEqual(result["query"], "Standard")
        self.assertEqual(result["typed_query"], "Standard")
        self.assertEqual(result["typed"], {"chars": 8})
        # Sequence: open click (3 mouse) + 8 chars × (keyDown+keyUp) + option
        # click (3 mouse). Never Input.insertText.
        methods = [c[0] for c in sess._sent]
        self.assertEqual(methods, ["Input.dispatchMouseEvent"] * 3
                         + ["Input.dispatchKeyEvent"] * 16
                         + ["Input.dispatchMouseEvent"] * 3)
        self.assertFalse(any(m == "Input.insertText" for m in methods))
        keys = [c[1] for c in sess._sent if c[0] == "Input.dispatchKeyEvent"]
        self.assertEqual([k["type"] for k in keys], ["keyDown", "keyUp"] * 8)
        # keyDown carries the char text (Chrome inserts it); keyUp does not.
        typed = "".join(k["text"] for k in keys if k["type"] == "keyDown")
        self.assertEqual(typed, "Standard")
        self.assertTrue(all("text" not in k for k in keys if k["type"] == "keyUp"))

    def test_type_text_trusted_key_codes(self):
        sess = self._sess([])
        result = sess._type_text_trusted("Go (6)")
        self.assertEqual(result, {"chars": 6})
        downs = [c[1] for c in sess._sent if c[1]["type"] == "keyDown"]
        by_char = {d["text"]: d for d in downs}
        # ASCII alnum → uppercase char code; space → 32; punctuation → no vk.
        self.assertEqual(by_char["G"]["windowsVirtualKeyCode"], ord("G"))
        self.assertEqual(by_char["o"]["windowsVirtualKeyCode"], ord("O"))
        self.assertEqual(by_char[" "]["windowsVirtualKeyCode"], 32)
        self.assertEqual(by_char["6"]["windowsVirtualKeyCode"], ord("6"))
        self.assertNotIn("windowsVirtualKeyCode", by_char["("])
        self.assertNotIn("windowsVirtualKeyCode", by_char[")"])

    def test_no_query_does_not_type(self):
        input_rect = json.dumps({"ok": True, "x": 100, "y": 200, "width": 240, "height": 32,
                                 "top": 200, "left": 100, "bottom": 232, "right": 340,
                                 "viewport": {"w": 1280, "h": 720}})
        option_rect = json.dumps({"ok": True, "x": 100, "y": 240, "width": 240, "height": 24,
                                  "top": 240, "left": 100, "bottom": 264, "right": 340,
                                  "viewport": {"w": 1280, "h": 720}})
        readback = json.dumps({"ok": True, "select_value": "9",
                               "selectize_value": "9", "validity_valid": True})
        sess = self._sess([input_rect, option_rect, readback])
        result = sess.select_via_trusted("offer[region]", "9")
        self.assertNotIn("typed_query", result)
        self.assertFalse(any(c[0] in ("Input.insertText", "Input.dispatchKeyEvent")
                             for c in sess._sent))

    def test_no_selectize_input_returns_early_no_clicks(self):
        input_rect = json.dumps({"ok": False, "reason": "no_wrapper"})
        sess = self._sess([input_rect])
        result = sess.select_via_trusted("offer[region]", "9")
        self.assertEqual(result["status"], "NO_SELECTIZE_INPUT")
        self.assertEqual(result["reason"], "no_wrapper")
        self.assertEqual(sess._sent, [])

    def test_option_not_in_rendered_dropdown_fails_closed(self):
        # Fail-closed: when the wanted value is NOT a product-scoped option in
        # the rendered dropdown, we must NOT force it (the old addItem fallback
        # read the master catalog and submitted the WRONG edition on
        # 2026-07-06). Expect status NO_OPTION, no _evaluate/addItem call, and
        # no extra CDP events beyond the 3 for the open click.
        input_rect = json.dumps({"ok": True, "x": 100, "y": 200, "width": 240, "height": 32,
                                 "top": 200, "left": 100, "bottom": 232, "right": 340,
                                 "viewport": {"w": 1280, "h": 720}})
        option_rect = json.dumps({
            "ok": False, "reason": "no_option", "is_open": True,
            "dropdown_options": [{"data_value": "636", "text": "+ 1 Month"}],
            "selectize_options": [{"key": "1", "value": "1", "text": "Standard"}],
        })
        sess = self._sess([input_rect, option_rect])
        # _evaluate must never be called on this path — forcing is forbidden.
        def _boom(js):
            raise AssertionError("addItem/_evaluate must not run when option is not rendered")
        sess._evaluate = _boom
        result = sess.select_via_trusted("offer[region]", "1")
        self.assertEqual(result["status"], "NO_OPTION")
        self.assertEqual(result["reason"], "no_option")
        self.assertNotIn("fallback", result)
        self.assertNotIn("readback", result)
        self.assertEqual(result["dropdown_options"], [{"data_value": "636", "text": "+ 1 Month"}])
        self.assertEqual(result["selectize_options"], [{"key": "1", "value": "1", "text": "Standard"}])
        # Only the open click via CDP (3 Input events); no forcing.
        self.assertEqual(len(sess._sent), 3)

    def test_selectize_probe_js_are_readonly_safe(self):
        from src.cdp_session import is_readonly_expression
        from src.submit_session import (
            _SELECTIZE_INPUT_RECT_JS,
            _SELECTIZE_OPTION_RECT_JS,
            _SELECTIZE_READBACK_JS,
        )

        self.assertTrue(is_readonly_expression(
            _SELECTIZE_INPUT_RECT_JS % json.dumps("offer[region]")
        ))
        self.assertTrue(is_readonly_expression(
            _SELECTIZE_OPTION_RECT_JS % (json.dumps("offer[region]"), json.dumps("9"))
        ))
        self.assertTrue(is_readonly_expression(
            _SELECTIZE_READBACK_JS % json.dumps("offer[region]")
        ))


class ProbeSelectOptionsTests(unittest.TestCase):
    def test_returns_full_enumeration_from_evaluate(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        payload = {
            "ok": True, "select_name": "offer[edition]", "current_value": "",
            "rendered_count": 21,
            "rendered_options": [{"data_value": "636", "text": "+ 1 Month"},
                                 {"data_value": "77", "text": "Standard"}],
            "select_option_count": 1, "select_options": [{"value": "", "text": ""}],
            "master_count": 2, "master_options": [{"key": "1", "text": "Standard"}],
        }
        seen = {}
        def _eval(js):
            seen["js"] = js
            return payload
        sess._evaluate = _eval
        result = sess.probe_select_options("offer[edition]")
        self.assertEqual(result["rendered_count"], 21)
        self.assertIn({"data_value": "77", "text": "Standard"}, result["rendered_options"])
        # The probe must target the requested select by name.
        self.assertIn('"offer[edition]"', seen["js"])

    def test_non_dict_result_is_fail_closed(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess._evaluate = lambda js: None
        result = sess.probe_select_options("offer[edition]")
        self.assertEqual(result, {"ok": False, "reason": "no_result"})


class AddTargetTrustedTests(unittest.TestCase):
    def _sess(self, *, focus_status="CLICKED", add_button_status="CLICKED", readback=None):
        import unittest.mock as mock
        from src.submit_session import WriteSubmitSession

        sess = WriteSubmitSession.__new__(WriteSubmitSession)
        calls = {"clicks": [], "cmds": []}

        def click_stub(selector="#TB_ajaxContent .button-primary"):
            calls["clicks"].append(selector)
            status = add_button_status if selector.endswith(" + button") else focus_status
            return {"status": status, "selector": selector}

        sess.click_trusted_at_element = click_stub
        sess._cmd = lambda method, params=None: calls["cmds"].append((method, params)) or {}
        sess.evaluate_readonly = lambda js: (
            readback if readback is not None
            else json.dumps({"ok": True, "count": 1, "inputs": [
                {"value_len": 6, "visible": True, "type": "text", "required": True, "valid": True}
            ]})
        )
        sess._calls = calls
        mock.patch("src.submit_session.time.sleep").start()
        self.addCleanup(mock.patch.stopall)
        return sess

    def test_button_commit_types_via_insert_text(self):
        sess = self._sess()
        diag = sess.add_target_trusted("210529")
        self.assertEqual(diag["status"], "ADDED")
        self.assertEqual(diag["commit"], "button")
        self.assertTrue(diag["typed"])
        self.assertEqual(diag["value"], "210529")
        # Value typed via trusted Input.insertText — never .value= / setValue.
        insert = [c for c in sess._calls["cmds"] if c[0] == "Input.insertText"]
        self.assertEqual(insert, [("Input.insertText", {"text": "210529"})])
        self.assertFalse(any(c[0] == "Input.dispatchKeyEvent" for c in sess._calls["cmds"]))
        self.assertEqual(diag["readback"]["count"], 1)

    def test_no_targets_field_when_focus_fails(self):
        sess = self._sess(focus_status="NO_ELEMENT")
        diag = sess.add_target_trusted("210529")
        self.assertEqual(diag["status"], "NO_TARGETS_FIELD")
        # Nothing typed, no add-button click attempted (field absent = non-fatal).
        self.assertEqual(sess._calls["cmds"], [])
        self.assertEqual(
            sess._calls["clicks"], ["#TB_ajaxContent input[name=\"offer[targets][]\"]"]
        )

    def test_enter_fallback_when_no_add_button(self):
        sess = self._sess(add_button_status="NO_ELEMENT")
        diag = sess.add_target_trusted("210529")
        self.assertEqual(diag["status"], "ADDED")
        self.assertEqual(diag["commit"], "enter")
        # Enter fallback is a trusted keyDown + keyUp (keyCode 13).
        keys = [c for c in sess._calls["cmds"] if c[0] == "Input.dispatchKeyEvent"]
        self.assertEqual([k[1]["type"] for k in keys], ["keyDown", "keyUp"])
        self.assertTrue(all(k[1]["windowsVirtualKeyCode"] == 13 for k in keys))

    def test_only_trusted_input_primitives_used(self):
        sess = self._sess()
        sess.add_target_trusted("210529")
        methods = [c[0] for c in sess._calls["cmds"]]
        self.assertTrue(methods and all(m.startswith("Input.") for m in methods))

    def test_readback_js_is_readonly_safe(self):
        from src.cdp_session import is_readonly_expression
        from src.submit_session import _TARGETS_READBACK_JS

        self.assertTrue(is_readonly_expression(_TARGETS_READBACK_JS))


class InspectModalDomParsingTests(unittest.TestCase):
    def test_parses_raw_json(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess.evaluate_readonly = lambda js: '{"modal_ok": true, "button": null}'
        result = sess.inspect_modal_dom()
        self.assertTrue(result["modal_ok"])
        self.assertIsNone(result["button"])

    def test_empty_response_returns_modal_not_ok(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess.evaluate_readonly = lambda js: ""
        result = sess.inspect_modal_dom()
        self.assertEqual(result, {"modal_ok": False})

    def test_inspect_js_is_readonly(self):
        from src.cdp_session import is_readonly_expression
        from src.submit_session import _INSPECT_MODAL_JS

        self.assertTrue(is_readonly_expression(_INSPECT_MODAL_JS))


class FormValidityTests(unittest.TestCase):
    def test_form_validity_js_is_readonly(self):
        from src.cdp_session import is_readonly_expression
        from src.submit_session import _FORM_VALIDITY_JS

        self.assertTrue(is_readonly_expression(_FORM_VALIDITY_JS))

    def test_parses_invalid_form(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess.evaluate_readonly = lambda js: (
            '{"ok": true, "form_valid": false, "checked": 4, '
            '"invalid_required": [{"name": "offer[targets][]", "valueMissing": true}]}'
        )
        result = sess.form_validity()
        self.assertFalse(result["form_valid"])
        self.assertEqual(result["invalid_required"][0]["name"], "offer[targets][]")

    def test_empty_response_is_not_ok(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess.evaluate_readonly = lambda js: ""
        self.assertFalse(sess.form_validity()["ok"])


class TargetsProbeTests(unittest.TestCase):
    def test_targets_probe_js_is_readonly(self):
        from src.cdp_session import is_readonly_expression
        from src.submit_session import _TARGETS_PROBE_JS

        self.assertTrue(is_readonly_expression(_TARGETS_PROBE_JS))

    def test_parses_targets_inventory(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess.evaluate_readonly = lambda js: (
            '{"ok": true, "count": 1, "targets": [{"tag": "INPUT", '
            '"name": "offer[targets][]", "placeholder": "Add a target", '
            '"list_attr": "targets-list", "datalist": [{"value": "EU", "label": "Europe"}]}]}'
        )
        result = sess.probe_targets_field()
        self.assertTrue(result["ok"])
        t = result["targets"][0]
        self.assertEqual(t["name"], "offer[targets][]")
        self.assertEqual(t["datalist"][0]["value"], "EU")

    def test_empty_response_is_not_ok(self):
        from src.submit_session import SubmitSession

        sess = SubmitSession.__new__(SubmitSession)
        sess.evaluate_readonly = lambda js: ""
        self.assertFalse(sess.probe_targets_field()["ok"])


if __name__ == "__main__":
    unittest.main()
