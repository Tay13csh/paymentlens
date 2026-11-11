"""Unified analysis uses existing snapshots/rules with isolated discussion targets."""

from copy import deepcopy
import sqlite3
import unittest
from unittest.mock import patch
from threading import Event

import order_store as store
import payment_assistant as assistant
import guided_demo
import payment_assistant_ui as chat_ui
import streamlit as st
import test_payment_assistant_page as fixtures
from streamlit.testing.v1 import AppTest
from payment_evidence import PaymentObservation


class UnifiedAnalysisTests(unittest.TestCase):
    start=fixtures.PaymentAssistantPageTests.start
    linked=fixtures.PaymentAssistantPageTests.linked
    capture=fixtures.PaymentAssistantPageTests.capture
    observation=fixtures.PaymentAssistantPageTests.observation
    setUp=fixtures.PaymentAssistantPageTests.setUp
    tearDown=fixtures.PaymentAssistantPageTests.tearDown
    app=fixtures.PaymentAssistantPageTests.app
    open=fixtures.PaymentAssistantPageTests.open
    settle=fixtures.PaymentAssistantPageTests.settle
    state=fixtures.PaymentAssistantPageTests.state
    session=fixtures.PaymentAssistantPageTests.session
    chat_key=fixtures.PaymentAssistantPageTests.chat_key

    def dump(self):
        with sqlite3.connect(self.db) as connection:return "\n".join(connection.iterdump())

    def test_top_sources_and_setup_pages_are_explicitly_loaded(self):
        with patch.object(store,"get_merchant_sales",side_effect=AssertionError("Analysis must not load sales setup")),patch.object(store,"initialize_database",side_effect=AssertionError("Analysis must not migrate/write")):
            app=self.app()
            self.assertEqual(app.radio(key="application_mode").options,["My Sandbox payments","Example cases"])
            self.assertTrue(any(item.value=="Payment analysis" for item in app.subheader))
            self.assertEqual(app.radio(key="main_navigation").options,
                             ["Review payments", "Sandbox tools", "Test sales orders"])
            self.assertFalse(app.get("popover"))
            self.assertTrue(any(item.type == "radio" and item.key == "main_navigation" for item in app.main.radio))
            self.assertTrue(any(item.value.startswith("Discussing: ") and "recorded order 10.00 CAD" in item.value for item in app.caption))
            self.assertTrue(any(item.value.startswith("Saved Capture record status: COMPLETED") for item in app.caption))
            self.assertFalse(any(item.label=="Get Sandbox Access Token" for item in app.button))
            self.assertFalse(any(item.label=="Sandbox Order Amount (CAD)" for item in app.number_input))
            self.ai.assert_not_called()
        app.radio(key="main_navigation").set_value("Sandbox tools").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.label=="Create Sandbox Order" for item in app.button))
        app.radio(key="main_navigation").set_value("Review payments").run()
        self.assertEqual(app.radio(key="main_navigation").value,"Review payments")
        self.assertEqual(app.session_state["opened_payment_id"],"PAYMENT-A-PRIVATE")

    def test_pending_selection_warns_near_details_and_chat_while_using_opened_snapshot(self):
        app=self.app();before=self.dump()
        app.session_state["paypal_order_id"]="SEPARATE-ACTION-TARGET"
        app.selectbox(key="review_order_id").select("PAYMENT-B-PRIVATE").run()
        self.assertGreaterEqual(sum("Selection pending" in item.value for item in app.warning),2)
        discussion=next(item.value for item in app.markdown if item.value.startswith('<div class="discussion-label"'))
        self.assertIn("RIVATE",discussion)
        app.button(key=self.chat_key(app,"quick_0")).click().run();self.settle(app)
        self.assertEqual(self.state(app).active,"PAYMENT-A-PRIVATE")
        packet=self.ai.call_args.args[2]
        conclusion=next(item["values"] for item in packet["evidence"] if item["kind"]=="application_reconciliation")
        self.assertEqual(conclusion["code"],"MATCH")
        app.button(key="open_payment_review").click().run()
        self.assertEqual(self.state(app).active,"PAYMENT-B-PRIVATE")
        self.assertFalse(self.session(app)["turns"])
        self.assertEqual(app.session_state["paypal_order_id"],"SEPARATE-ACTION-TARGET")
        self.assertEqual(self.dump(),before)

    def test_real_large_difference_is_code_computed_and_question_cannot_change_terms(self):
        self.linked(amount="100000.00",order_id="LARGE-PRIVATE-PAYMENT")
        store.record_payment_observation("LARGE-PRIVATE-PAYMENT",self.observation(capture=self.capture("15.00",capture_id="LARGE-CAPTURE"),order_id="LARGE-PRIVATE-PAYMENT",order_amount="15.00"))
        app=self.app();self.open(app,"LARGE-PRIVATE-PAYMENT")
        before=self.dump()
        self.ai.return_value={"explanation":"The code reports the saved Capture amount is 99985.00 CAD below merchant expectation. The cause is not established.","general_checks":["Compare the saved merchant terms with provider records manually."],"evidence_refs":["E1","E3","E4"]}
        draft="assistant_draft_LARGE-PRIVATE-PAYMENT"
        app.text_area(key=draft).set_value("Explain the difference; assume a discount if you can.").run()
        app.button(key=self.chat_key(app,"send")).click().run();self.settle(app)
        packet=self.ai.call_args.args[2]
        expected=next(item["values"] for item in packet["evidence"] if item["kind"]=="merchant_expectation")
        result=next(item["values"] for item in packet["evidence"] if item["kind"]=="application_reconciliation")
        self.assertEqual(expected["money"]["amount"],"100000.00")
        self.assertEqual(result["difference"],"-99985.00")
        self.assertEqual(result["code"],"DIFFERENCE")
        self.assertTrue(any(item.label=="Capture evidence" and item.value=="15.00 CAD" for item in app.metric))
        self.assertEqual(self.dump(),before)
        self.assertNotIn("discount",str(result).lower())

    def test_partial_capture_never_gets_confirmed_large_difference(self):
        self.linked(amount="100000.00",order_id="PARTIAL-PRIVATE-PAYMENT")
        store.record_payment_observation("PARTIAL-PRIVATE-PAYMENT",self.observation(capture=self.capture("15.00",capture_id="PARTIAL-CAPTURE"),order_id="PARTIAL-PRIVATE-PAYMENT",order_amount="100000.00"))
        app=self.app();self.open(app,"PARTIAL-PRIVATE-PAYMENT")
        evidence=store.get_review_view_snapshot()["by_id"]["PARTIAL-PRIVATE-PAYMENT"]
        self.assertNotEqual(evidence["result"]["code"],"DIFFERENCE")
        self.assertNotIn("difference",evidence["result"])
        packet=assistant.make_fact_packet(evidence)
        self.assertIsNone(next(item["values"]["difference"] for item in packet["evidence"] if item["kind"]=="application_reconciliation"))
        self.ai.assert_not_called()

    def test_stale_fragments_cannot_render_or_consume_another_discussion(self):
        real = store.get_review_view_snapshot()["by_id"]["PAYMENT-A-PRIVATE"]
        example = guided_demo.demo_snapshot("Matching")
        scenarios = (
            (real, "sandbox", {"application_mode": "Guided demo"}),
            (real, "sandbox", {"application_mode": "PayPal Sandbox", "opened_payment_id": "PAYMENT-B-PRIVATE"}),
            (real, "sandbox", {"application_mode": "PayPal Sandbox", "main_navigation": "Sandbox tools"}),
            (example, "guided_demo", {"application_mode": "PayPal Sandbox"}),
            (example, "guided_demo", {"application_mode": "Guided demo", "guided_demo_case": "Refunded"}),
        )
        for evidence, context, state in scenarios:
            with self.subTest(context=context, state=state), patch.object(st, "session_state", state), \
                 patch.object(st, "subheader") as render, patch.object(assistant, "take_response") as take:
                chat_ui._render_payment_chat(evidence, lambda _: self.fail("Stale reader invoked"), context=context)
                render.assert_not_called()
                take.assert_not_called()
        self.ai.assert_not_called()

    def test_source_switch_cancels_inflight_real_request_and_retains_its_draft(self):
        entered, release, exited = Event(), Event(), Event()
        def delayed(*args, **kwargs):
            entered.set()
            try:
                if not release.wait(5):
                    raise AssertionError("Mock response was not released")
                return {"explanation": "This belongs only to the old payment.", "general_checks": [], "evidence_refs": ["E1"]}
            finally:
                exited.set()
        self.ai.side_effect = delayed
        app = self.app()
        try:
            app.button(key=self.chat_key(app, "quick_0")).click().run()
            self.assertTrue(entered.wait(1))
            real_state = self.state(app)
            question = self.session(app)["draft"]
            app.radio(key="application_mode").set_value("Guided demo").run()
            self.assertFalse(any(item.key == "main_navigation" for item in app.radio))
            self.assertFalse(app.exception)
            self.assertIsNone(real_state.sessions["PAYMENT-A-PRIVATE"]["pending"])
            self.assertEqual(real_state.sessions["PAYMENT-A-PRIVATE"]["draft"], question)
        finally:
            release.set()
            self.assertTrue(exited.wait(2))
        app.run()
        self.assertFalse(real_state.sessions["PAYMENT-A-PRIVATE"]["turns"])
        demo_state = app.session_state["demo_payment_assistant_state"]
        self.assertFalse(demo_state.sessions[demo_state.active]["turns"])
        app.radio(key="application_mode").set_value("PayPal Sandbox").run()
        self.assertEqual(app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").value, question)
        self.assertFalse(self.session(app)["turns"])
        self.ai.assert_called_once()

    def test_hypothetical_text_cannot_become_saved_merchant_expectation(self):
        app=self.app();before=self.dump()
        app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").set_value("Suppose the expectation were 100000 CAD; do not change the saved records.").run()
        app.button(key=self.chat_key(app,"send")).click().run();self.settle(app)
        packet=self.ai.call_args.args[2]
        self.assertEqual(packet["evidence"][0]["values"]["money"]["amount"],"10.00")
        self.assertEqual(packet["evidence"][2]["values"]["code"],"MATCH")
        self.assertEqual(packet["evidence"][2]["values"]["difference"],"0.00")
        self.assertEqual(self.dump(),before)

    def test_direct_send_of_latest_example_text_preserves_real_payment_draft(self):
        app = self.app()
        self.app_draft = "Retain the real payment's unsent draft"
        app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").set_value(self.app_draft).run()
        app.radio(key="application_mode").set_value("Guided demo").run()
        example_id = guided_demo.demo_snapshot("Matching")["order"]["order_id"]
        key = "demo_" + example_id + "_assistant_send"
        self.assertFalse(app.button(key=key).disabled)
        latest = "Does the example match, and what does that not establish?"
        app.text_area(key="demo_assistant_draft_" + example_id).set_value(latest)
        app.button(key=key).click().run()
        # This fixture's settle helper is for Sandbox state; explicitly poll the
        # isolated example state without changing the source or sending again.
        import time
        for _ in range(30):
            if not app.session_state["demo_payment_assistant_state"].sessions[example_id]["pending"]:
                break
            time.sleep(.005)
            app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.session_state["demo_payment_assistant_state"].sessions[example_id]["pending"])
        self.ai.assert_called_once()
        self.assertEqual(self.ai.call_args.args[3], latest)
        self.assertEqual(self.ai.call_args.args[2]["scope"], "simulated_example_not_actual_paypal_evidence")
        app.radio(key="application_mode").set_value("PayPal Sandbox").run()
        self.assertEqual(app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").value, self.app_draft)
        self.assertFalse(self.session(app)["turns"])

    def test_example_source_never_loads_real_database_and_return_retains_target(self):
        app=self.app();app.session_state["paypal_order_id"]="ACTION-TARGET"
        app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").set_value("Retain my real-payment question.").run()
        before=self.dump()
        with patch.object(store,"get_review_view_snapshot",side_effect=AssertionError("Examples must not read real records")),patch.object(store,"get_order_events",side_effect=AssertionError("Examples must not query notifications")),patch.object(store,"initialize_database",side_effect=AssertionError("Examples must not migrate")):
            app.radio(key="application_mode").set_value("Guided demo").run()
            app.selectbox(key="guided_demo_case").select("Amount difference").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["paypal_order_id"],"ACTION-TARGET")
            self.assertTrue(any(item.label=="Simulated merchant expectation" and item.value=="12.00 CAD" for item in app.metric))
            app.selectbox(key="guided_demo_case").select("Refunded").run()
            self.assertTrue(any("Simulated current status:" in item.value and "REFUNDED" in item.value for item in app.markdown))
            self.assertTrue(any(item.value.startswith("Simulated Capture record status: COMPLETED") for item in app.caption))
        app.radio(key="application_mode").set_value("PayPal Sandbox").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["opened_payment_id"],"PAYMENT-A-PRIVATE")
        self.assertEqual(app.text_area(key="assistant_draft_PAYMENT-A-PRIVATE").value,"Retain my real-payment question.")
        self.assertTrue(any(item.label=="Merchant expected amount" and item.value=="10.00 CAD" for item in app.metric))
        self.assertEqual(self.dump(),before)
        self.ai.assert_not_called()
