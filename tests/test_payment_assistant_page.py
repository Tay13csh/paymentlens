"""Payment assistant UI with temporary SQLite and mocked responses only."""

from copy import deepcopy
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app
import streamlit as st

import ai_explanation
import order_store as store
import paypal_auth
import payment_assistant as assistant
import test_merchant_reconciliation as fixtures
from test_payment_assistant import answer


class PaymentAssistantPageTests(unittest.TestCase):
    start = fixtures.MerchantReconciliationTests.start
    linked = fixtures.MerchantReconciliationTests.linked
    capture = fixtures.MerchantReconciliationTests.capture
    observation = fixtures.MerchantReconciliationTests.observation

    def setUp(self):
        fixtures.MerchantReconciliationTests.setUp(self)
        self.start(patch.object(st, "secrets", {"openai": {"api_key": "synthetic-key", "model": "synthetic-model"}}))
        self.payments = [self.start(patch.object(paypal_auth, name, side_effect=AssertionError("Payment operation forbidden")))
                         for name in ("create_order", "capture_order", "get_order_status", "get_access_token")]
        self.old_ai = self.start(patch.object(ai_explanation, "explain_order_risk", side_effect=AssertionError("Old rule AI forbidden")))
        self.ai = self.start(patch.object(assistant, "ask_payment", return_value=answer()))
        self.linked(order_id="PAYMENT-A-PRIVATE")
        store.record_payment_observation("PAYMENT-A-PRIVATE", self.observation(order_id="PAYMENT-A-PRIVATE"))
        self.linked(order_id="PAYMENT-B-PRIVATE")

    def tearDown(self):
        self.network.assert_not_called();self.old_ai.assert_not_called()
        for call in self.payments:call.assert_not_called()

    def app(self):
        app = sandbox_test_app(str(fixtures.APP)).run()
        self.open(app, "PAYMENT-A-PRIVATE")
        return app

    def open(self, app, order_id):
        app.selectbox(key="review_order_id").select(order_id).run()
        app.button(key="open_payment_review").click().run()
        self.settle(app)
        self.assertFalse(app.exception)

    def settle(self, app):
        for _ in range(30):
            if not self.session(app)["pending"]:
                return
            time.sleep(0.005)
            app.run()
        self.fail("Mock request did not settle")

    def chat_key(self, app, name):
        return "sandbox_" + self.state(app).active + "_assistant_" + name

    def state(self, app):return app.session_state["payment_assistant_state"]
    def session(self, app):return self.state(app).sessions[self.state(app).active]
    def draft(self, app, text):
        app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").set_value(text).run()

    def test_quick_sends_immediately_free_input_only_on_send_and_no_rerun_duplicates(self):
        app = self.app()
        self.ai.assert_not_called()
        app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.ai.assert_called_once()
        app.run();app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.ai.assert_called_once()
        self.draft(app, "Can you explain that in simpler words?")
        self.ai.assert_called_once()
        app.button(key=self.chat_key(app,"send")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.assertEqual(self.ai.call_count, 2)
        args = self.ai.call_args.args
        self.assertEqual(args[3], "Can you explain that in simpler words?")
        self.assertEqual(len(args[4]), 1)
        self.assertEqual(len(self.session(app)["turns"]), 2)
        self.assertTrue(any(x.label == "Evidence used for this answer" for x in app.expander))
        self.assertTrue(any("supplied by the application" in x.value for x in app.markdown))

    def test_send_is_available_before_blur_but_empty_and_whitespace_never_call(self):
        app = self.app()
        self.assertFalse(app.button(key=self.chat_key(app, "send")).disabled)
        app.button(key=self.chat_key(app, "send")).click().run()
        self.assertTrue(any("Enter a question" in item.value for item in app.error))
        app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").set_value("   ")
        app.button(key=self.chat_key(app, "send")).click().run()
        self.assertFalse(app.exception)
        self.assertFalse(self.session(app)["turns"])
        self.assertIsNone(self.session(app)["pending"])
        self.ai.assert_not_called()

    def test_send_uses_latest_text_in_same_submission_not_previous_draft(self):
        app = self.app()
        self.draft(app, "Older unsent draft")
        newest = "What can these saved records tell me about bank settlement?"
        # One combined client event: edited text plus click, without a prior
        # run() that would simulate a separate blur/update round trip.
        app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").set_value(newest)
        app.button(key=self.chat_key(app, "send")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.ai.assert_called_once()
        self.assertEqual(self.ai.call_args.args[3], newest)
        app.run()
        app.button(key=self.chat_key(app, "send")).click().run()
        self.settle(app)
        self.ai.assert_called_once()

    def test_rerun_before_client_call_cannot_leave_pending_forever(self):
        from contextlib import contextmanager
        from streamlit.runtime.scriptrunner import RerunData, RerunException
        app = self.app()
        interrupted = []
        @contextmanager
        def interrupted_spinner(*args, **kwargs):
            if not interrupted:
                interrupted.append(True)
                raise RerunException(RerunData())
            yield
        with patch.object(st, "spinner", interrupted_spinner):
            app.button(key=self.chat_key(app,"quick_0")).click().run()
            self.settle(app)
        self.assertFalse(app.exception)
        self.ai.assert_not_called()
        self.assertIsNone(self.session(app)["pending"])
        self.assertTrue(app.button(key=self.chat_key(app,"quick_0")).disabled is False)
        self.assertEqual(self.session(app)["draft"], assistant.QUICK_QUESTIONS[0])
        app.run()
        self.ai.assert_not_called()

    def test_rerun_after_client_started_releases_wait_without_resending(self):
        from streamlit.runtime.scriptrunner import RerunData, RerunException
        self.ai.side_effect = RerunException(RerunData())
        app = self.app()
        app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.ai.assert_called_once()
        self.assertIsNone(self.session(app)["pending"])
        self.assertEqual(self.session(app)["draft"], assistant.QUICK_QUESTIONS[0])
        self.assertTrue(any("interrupted" in item.value for item in app.error))
        app.run();self.ai.assert_called_once()

    def test_sdk_timeout_and_invalid_response_clear_wait_and_offer_manual_retry(self):
        import httpx
        self.ai.side_effect = assistant.PaymentAssistantError("The assistant timed out. Retry manually.")
        app = self.app()
        app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.assertIsNone(self.session(app)["pending"])
        self.assertTrue(any("timed out" in item.value for item in app.error))
        self.assertFalse(app.button(key=self.chat_key(app,"retry")).disabled)
        app.run();self.ai.assert_called_once()
        self.ai.side_effect = None
        self.ai.return_value = dict(answer(), evidence_refs=["E999"])
        app.button(key=self.chat_key(app,"retry")).click().run()
        self.settle(app)
        self.assertIsNone(self.session(app)["pending"])
        self.assertFalse(self.session(app)["turns"])
        self.assertEqual(self.ai.call_count, 2)

    def test_cancel_waiting_invalidates_ticket_without_clearing_draft_or_answers(self):
        app = self.app()
        app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        state = self.state(app)
        evidence = store.get_review_view_snapshot()["by_id"]["PAYMENT-A-PRIVATE"]
        ticket = state.begin(evidence, "What information is missing now?")
        app.run()
        self.assertFalse(app.button(key=self.chat_key(app,"cancel_waiting")).disabled)
        app.button(key=self.chat_key(app,"cancel_waiting")).click().run()
        self.settle(app)
        self.assertIsNone(self.session(app)["pending"])
        self.assertEqual(self.session(app)["draft"], "What information is missing now?")
        self.assertEqual(len(self.session(app)["turns"]), 1)
        self.assertFalse(state.finish(ticket, answer(), evidence))
        self.assertTrue(any("charges" in item.value.lower() for item in app.info))
        self.assertEqual(self.ai.call_count, 1)

    def test_pending_ui_returns_before_provider_and_cancel_is_interactive(self):
        from threading import Event
        entered, release, exited = Event(), Event(), Event()
        def delayed(*args, **kwargs):
            entered.set()
            try:
                self.assertTrue(release.wait(3))
                return answer()
            finally:exited.set()
        self.ai.side_effect = delayed
        app = self.app()
        try:
            with patch.object(st, "fragment", wraps=st.fragment) as fragment:
                app.button(key=self.chat_key(app,"quick_0")).click().run()
                self.assertTrue(entered.wait(1))
                self.assertFalse(exited.is_set())
                self.assertIsNotNone(self.session(app)["pending"])
                self.assertFalse(app.button(key=self.chat_key(app,"cancel_waiting")).disabled)
                self.assertTrue(any(call.kwargs.get("run_every") == 0.5 for call in fragment.call_args_list))
                app.button(key=self.chat_key(app,"cancel_waiting")).click().run()
                self.assertIsNone(self.session(app)["pending"])
                self.assertFalse(exited.is_set())
                self.assertFalse(app.button(key=self.chat_key(app,"quick_0")).disabled)
                self.assertTrue(any("cancelled" in item.value for item in app.info))
                self.ai.assert_called_once()
        finally:
            release.set();self.assertTrue(exited.wait(2))
        app.run()
        self.assertFalse(self.session(app)["turns"])
        self.ai.assert_called_once()

    def test_timeout_state_changes_without_render_then_poll_updates_controls(self):
        from threading import Event
        entered, release, exited = Event(), Event(), Event()
        original_start = assistant.start_request
        jobs = []
        def delayed(*args, **kwargs):
            entered.set()
            try:
                self.assertTrue(release.wait(3));return answer()
            finally:exited.set()
        def short_deadline(*args, **kwargs):
            job=original_start(*args, **kwargs, timeout=0.1)
            jobs.append(job)
            return job
        self.ai.side_effect = delayed
        app = self.app()
        try:
            with patch.object(assistant, "start_request", side_effect=short_deadline):
                app.button(key=self.chat_key(app,"quick_0")).click().run()
            self.assertTrue(jobs[0]["expired"].wait(1))
            self.assertIsNone(self.session(app)["pending"])
            self.assertFalse(exited.is_set())
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("timed out" in item.value for item in app.info))
            self.assertFalse(app.button(key=self.chat_key(app,"retry")).disabled)
            self.ai.assert_called_once()
        finally:
            release.set();self.assertTrue(exited.wait(2))

    def test_missing_settings_does_not_crash_and_never_replaces_live_answer_with_example(self):
        with patch.object(st, "secrets", {}):
            app = self.app()
            self.assertTrue(app.button(key=self.chat_key(app,"send")).disabled)
            self.assertTrue(app.button(key=self.chat_key(app,"quick_0")).disabled)
            self.assertTrue(any("Payment assistant unavailable" in item.value for item in app.info))
            self.assertFalse(app.exception)
            self.assertTrue(any(item.value == "Merchant reconciliation" for item in app.subheader))
            self.ai.assert_not_called()

    def test_failure_keeps_question_and_manual_retry_only(self):
        self.ai.side_effect = assistant.PaymentAssistantError("Synthetic safe failure")
        app = self.app();app.button(key=self.chat_key(app,"quick_2")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.assertEqual(self.session(app)["draft"], assistant.QUICK_QUESTIONS[2])
        app.run();self.ai.assert_called_once()
        self.ai.side_effect = None
        app.button(key=self.chat_key(app,"retry")).click().run()
        self.settle(app)
        self.assertEqual(self.ai.call_count, 2)
        self.assertEqual(len(self.session(app)["turns"]), 1)

    def test_failed_quick_double_click_does_not_issue_second_request(self):
        self.ai.side_effect = assistant.PaymentAssistantError("Synthetic safe failure")
        app = self.app()
        app.button(key=self.chat_key(app,"quick_2")).click().run()
        self.settle(app)
        app.button(key=self.chat_key(app,"quick_2")).click().run()
        self.settle(app)
        self.ai.assert_called_once()
        self.assertTrue(any("Retry failed question" in item.value for item in app.info))

    def test_preflight_evidence_update_sends_nothing_and_preserves_question(self):
        original = store.get_review_view_snapshot
        app = self.app()
        count = []
        def change_before_preflight(*args):
            count.append(1)
            if len(count) == 2:
                store.update_order_status("PAYMENT-A-PRIVATE", "REFUNDED")
            return original(*args)
        with patch.object(store, "get_review_view_snapshot", side_effect=change_before_preflight):
            app.button(key=self.chat_key(app,"quick_0")).click().run()
            self.settle(app)
        self.ai.assert_not_called()
        self.assertFalse(app.exception)
        self.assertEqual(self.session(app)["draft"], assistant.QUICK_QUESTIONS[0])
        self.assertTrue(any("Records changed" in item.value for item in app.info))

    def test_record_changes_keep_draft_archive_answers_and_never_auto_call(self):
        app=self.app();app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.draft(app, "What does this mean for my next step?")
        store.update_order_status("PAYMENT-A-PRIVATE", "REFUNDED")
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.ai.call_count, 1)
        self.assertEqual(self.session(app)["draft"], "What does this mean for my next step?")
        self.assertEqual(len(self.session(app)["turns"]), 0)
        self.assertEqual(len(self.session(app)["archives"]), 1)
        self.assertTrue(any("outdated" in item.value.lower() for item in app.info))
        self.assertTrue(any("Outdated conversation" in item.value for item in app.warning))

    def test_refund_during_request_discards_late_response_and_keeps_question(self):
        def refund(*args):
            store.update_order_status("PAYMENT-A-PRIVATE", "REVERSED")
            return answer()
        self.ai.side_effect=refund
        app=self.app();app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.assertFalse(self.session(app)["turns"])
        self.assertEqual(self.session(app)["draft"], assistant.QUICK_QUESTIONS[0])
        self.ai.assert_called_once()

    def test_pending_selection_does_not_change_chat_or_payment_target_and_opening_isolates(self):
        app=self.app();app.session_state["paypal_order_id"]="SANDBOX-TARGET"
        app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        app.selectbox(key="review_order_id").select("PAYMENT-B-PRIVATE").run()
        self.assertEqual(self.state(app).active,"PAYMENT-A-PRIVATE")
        app.button(key="open_payment_review").click().run()
        self.settle(app)
        self.assertEqual(self.state(app).active,"PAYMENT-B-PRIVATE")
        self.assertFalse(self.session(app)["turns"])
        self.assertEqual(app.session_state["paypal_order_id"],"SANDBOX-TARGET")
        self.ai.assert_called_once()

    def test_success_preserves_database_creation_recovery_and_original_rule_state(self):
        app = self.app()
        app.session_state["paypal_order_id"] = "SANDBOX-TARGET"
        app.session_state["paypal_approval_url"] = "https://example.invalid/approval"
        app.button(key="analyze_saved_order").click().run()
        self.settle(app)
        app.session_state["ai_explanation"] = "Original rule explanation"
        app.query_params["create_attempt"] = "PRESERVED-RECOVERY-KEY"
        app.run()
        rules = deepcopy(app.session_state["risk_analysis"])
        with sqlite3.connect(self.db) as connection: before = "\n".join(connection.iterdump())
        app.button(key=self.chat_key(app,"quick_0")).click().run()
        self.settle(app)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["risk_analysis"], rules)
        self.assertEqual(app.session_state["ai_explanation"], "Original rule explanation")
        self.assertEqual(app.session_state["paypal_order_id"], "SANDBOX-TARGET")
        self.assertEqual(app.query_params["create_attempt"], ["PRESERVED-RECOVERY-KEY"])
        with sqlite3.connect(self.db) as connection: after = "\n".join(connection.iterdump())
        self.assertEqual(before, after)

    def test_clear_and_privacy_rejection_never_send_or_write(self):
        app=self.app()
        with sqlite3.connect(self.db) as connection:before="\n".join(connection.iterdump())
        self.draft(app,"person@example.invalid please check this")
        app.button(key=self.chat_key(app,"send")).click().run()
        self.settle(app)
        self.ai.assert_not_called()
        self.assertFalse(self.session(app)["turns"])
        self.assertTrue(any("Possible private" in item.value for item in app.error))
        app.button(key=self.chat_key(app,"clear")).click().run()
        self.settle(app)
        self.assertEqual(self.session(app)["draft"],"")
        self.assertFalse(self.session(app)["archives"])
        with sqlite3.connect(self.db) as connection:after="\n".join(connection.iterdump())
        self.assertEqual(before,after)
