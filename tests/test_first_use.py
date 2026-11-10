"""Offline checks for opening payments explicitly before optional simulations."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

import ai_explanation
import order_store
import paypal_auth


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
A = "PAYMENT-REFERENCE-111111"
B = "PAYMENT-REFERENCE-222222"


class FirstUseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.start_patch(patch.object(order_store, "DATABASE_PATH", Path(directory.name) / "orders.db"))
        self.start_patch(patch.object(st, "secrets", {}))
        self.network = self.start_patch(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Network forbidden")))
        self.ai = self.start_patch(patch.object(ai_explanation, "explain_order_risk", side_effect=AssertionError("AI forbidden")))
        self.payment_calls = [self.start_patch(patch.object(paypal_auth, name, side_effect=AssertionError("Payment forbidden")))
                              for name in ("get_access_token", "create_order", "capture_order", "get_order_status")]

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def save(self, order_id=A, amount="10.00", currency="CAD", status="COMPLETED"):
        order_store.save_order(order_id, amount, currency)
        order_store.update_order_status(order_id, status)

    def app(self):
        app = AppTest.from_file(str(APP_PATH)).run()
        self.assertFalse(app.exception)
        return app

    def open(self, app, order_id=A):
        app.selectbox(key="review_order_id").select(order_id).run()
        app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)

    def overview(self, app):
        return next(item.value for item in app.markdown if item.value.startswith('<section class="pg-payment-overview'))

    def assert_no_requests(self):
        self.network.assert_not_called()
        self.ai.assert_not_called()
        for call in self.payment_calls:
            call.assert_not_called()

    def test_empty_first_use_has_a_clear_route_to_separate_sandbox_tools(self):
        app = self.app()
        review = next(tab for tab in app.tabs if tab.label == "Review payments")
        sandbox = next(tab for tab in app.tabs if tab.label == "Sandbox tools")
        self.assertTrue(any("No saved payments" in item.value and "Sandbox tools tab" in item.value and "Create Sandbox Order" in item.value for item in review.info))
        self.assertTrue(any(button.label == "Create Sandbox Order" for button in sandbox.button))
        self.assertTrue(any(button.label == "Get Sandbox Access Token" for button in sandbox.button))
        self.assertFalse(review.button)
        self.assertFalse(review.number_input)
        self.assert_no_requests()

    def test_initial_selection_requires_review_action_without_a_baseline(self):
        self.save()
        app = self.app()
        review = next(tab for tab in app.tabs if tab.label == "Review payments")
        self.assertTrue(any(button.label == "Review payment" for button in review.button))
        self.assertFalse(any(item.value.startswith('<section class="pg-payment-overview') for item in app.markdown))
        self.assertFalse(review.number_input)
        self.assertFalse(any(item.label == "Explore assumptions" for item in app.expander))
        self.open(app)
        self.assertIn("10.00", self.overview(app))
        self.assertNotIn("Not analyzed", self.overview(app))
        self.assertNotIn("risk_analysis", app.session_state)
        self.assertFalse(next(item for item in app.expander if item.label == "Explore assumptions").proto.expanded)
        self.assert_no_requests()

    def test_every_payment_state_can_be_viewed_without_running_rules(self):
        for status in ("CREATED", "APPROVED", "COMPLETED", "DENIED", "REFUNDED", "REVERSED"):
            with self.subTest(status=status):
                self.save(status, status=status)
                app = self.app()
                self.open(app, status)
                self.assertIn(f'">{status}</span>', self.overview(app))
                self.assertTrue(any(item.value == "Payment records" for item in app.subheader))
                self.assertTrue(any(item.label == "Record details" for item in app.expander))
                self.assertTrue(any("Buyer approval does not mean payment is complete" in item.value for item in app.caption))
                self.assertNotIn("risk_analysis", app.session_state)
        self.assert_no_requests()

    def test_pending_selection_keeps_old_overview_identified_until_review_is_clicked(self):
        self.save()
        self.save(B, "25.00", "USD", "APPROVED")
        app = self.app()
        self.open(app)
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Observation for the open CAD payment."
        app.session_state["paypal_order_id"] = B
        app.run()
        custom = next(field for field in app.text_input if field.label.startswith("Custom simulated comparison"))
        custom.set_value("4").run()
        original_analysis = dict(app.session_state["risk_analysis"])
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            original_database = "\n".join(connection.iterdump())
        app.selectbox(key="review_order_id").select(B).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["opened_payment_id"], A)
        self.assertIn("…111111", self.overview(app))
        self.assertNotIn("…222222", self.overview(app))
        self.assertTrue(any("Selection changed" in item.value and "still shows …111111" in item.value for item in app.info))
        self.assertEqual(dict(app.session_state["risk_analysis"]), original_analysis)
        self.assertEqual(app.session_state["ai_explanation"], "Observation for the open CAD payment.")
        self.assertEqual(next(field for field in app.text_input if field.label.startswith("Custom simulated comparison")).value, "4")
        app.button(key="open_payment_review").click().run()
        self.assertIn("…222222", self.overview(app))
        self.assertIn("25.00", self.overview(app))
        self.assertEqual(app.session_state["opened_payment_id"], B)
        self.assertEqual(app.session_state["paypal_order_id"], B)
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            self.assertEqual("\n".join(connection.iterdump()), original_database)
        self.assert_no_requests()

    def test_visible_ai_entry_requires_rule_results_and_does_not_claim_payment_verification(self):
        self.save()
        app = self.app()
        self.open(app)
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in app.button))
        app.button(key="analyze_saved_order").click().run()
        rules = next(tab for tab in app.tabs if tab.label == "Rule review")
        sandbox = next(tab for tab in app.tabs if tab.label == "Sandbox tools")
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in rules.button))
        self.assertTrue(any(button.key == "generate_ai_explanation" for button in app.button))
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in sandbox.button))
        self.assertTrue(any("does not verify the payment or review payment notifications" in item.value for item in app.caption))
        self.assert_no_requests()

    def test_ai_entry_opens_rule_analysis_without_calculating_or_requesting_ai(self):
        self.save()
        app = self.app()
        self.open(app)
        headings = [item.value for item in app.subheader]
        self.assertLess(headings.index("Payment overview"), headings.index("AI rule explanation"))
        self.assertLess(headings.index("AI rule explanation"), headings.index("Payment records"))
        app.button(key="open_rule_analysis").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(next(item for item in app.expander if item.label == "Explore assumptions").proto.expanded)
        self.assertEqual(app.session_state["open_rule_analysis_for"], A)
        self.assertNotIn("risk_analysis", app.session_state)
        self.assertNotIn("ai_explanation", app.session_state)
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in app.button))
        self.assert_no_requests()

    def test_ai_entry_rejects_stale_analysis_and_preserves_completed_only_gate(self):
        self.save()
        self.save(B, status="APPROVED")
        app = self.app()
        self.open(app)
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Old rule observation."
        app.run()
        app.number_input(key="simulated_average_CAD").set_value(50.0).run()
        self.assertNotIn("risk_analysis", app.session_state)
        self.assertNotIn("ai_explanation", app.session_state)
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in app.button))
        self.assertNotIn("Old rule observation.", "\n".join(item.value for item in app.markdown))
        self.assertTrue(any(button.key == "open_rule_analysis" for button in app.button))
        self.open(app, B)
        self.assertTrue(app.button(key="open_rule_analysis").disabled)
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in app.button))
        self.assert_no_requests()

    def test_full_identifiers_are_in_collapsed_record_details_not_the_overview(self):
        self.save()
        app = self.app()
        self.open(app)
        self.assertNotIn(A, self.overview(app))
        table = next(item.value for item in app.markdown if item.value.startswith("| Payment |"))
        self.assertNotIn(A, table)
        details = next(item for item in app.expander if item.label == "Record details")
        self.assertFalse(details.proto.expanded)
        self.assertIn(f"Payment ID: {A}", "\n".join(item.value for item in details.markdown))
        self.assertTrue(any("General manual check, not a finding" in item.value for item in app.caption))
        self.assert_no_requests()


if __name__ == "__main__":
    unittest.main()
