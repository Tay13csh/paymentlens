"""Offline page tests for browsing, review isolation, and payment targeting."""

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


class OrderWorkbenchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.start_patch(patch.object(order_store, "DATABASE_PATH", Path(directory.name) / "orders.db"))
        self.start_patch(patch.object(st, "secrets", {
            "paypal": {"client_id": "synthetic-id", "client_secret": "synthetic-secret"},
            "openai": {"api_key": "synthetic-key", "model": "synthetic-model"},
        }))
        self.requests = self.start_patch(patch.object(
            requests.sessions.Session, "request", side_effect=AssertionError("Network forbidden")
        ))
        self.api = {
            name: self.start_patch(patch.object(paypal_auth, name, side_effect=AssertionError("Unexpected payment operation")))
            for name in ("get_access_token", "create_order", "capture_order", "get_order_status")
        }
        self.explain = self.start_patch(patch.object(ai_explanation, "explain_order_risk", return_value="Synthetic explanation"))

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def save(self, order_id, status="COMPLETED", amount="10.00", currency="CAD"):
        order_store.save_order(order_id, amount, currency)
        if status != "CREATED":
            order_store.update_order_status(order_id, status)

    def app(self):
        app = AppTest.from_file(str(APP_PATH)).run()
        self.assertFalse(app.exception)
        return app

    def select(self, app, order_id):
        app.selectbox(key="review_order_id").select(order_id).run()
        self.assertFalse(app.exception)

    def assert_no_requests(self):
        for mock in self.api.values():
            mock.assert_not_called()
        self.explain.assert_not_called()
        self.requests.assert_not_called()

    def test_empty_page_has_visible_payment_entry_and_collapsed_developer_tools(self):
        app = self.app()
        self.assertFalse(app.selectbox)
        self.assertTrue(any(button.label == "Create Sandbox Order" for button in app.button))
        tools = next(expander for expander in app.sidebar.expander if expander.label == "Developer tools")
        self.assertFalse(tools.proto.expanded)
        self.assertTrue(any(button.label == "Get Sandbox Access Token" for button in app.sidebar.button))
        self.assertTrue(any("No saved orders" in item.value for item in app.info))
        self.assert_no_requests()

    def test_list_displays_saved_payment_fields_without_invented_risk_or_payment_time(self):
        self.save("COMPLETE", amount="12.34", currency="USD")
        self.save("PENDING", status="APPROVED")
        self.save("REFUND", status="REFUNDED")
        app = self.app()
        table = next(item.value for item in app.markdown if item.value.startswith("| Order ID |"))
        self.assertIn("| COMPLETE | 12.34 | USD | COMPLETED |", table)
        self.assertIn("| PENDING | 10.00 | CAD | APPROVED |", table)
        self.assertIn("| REFUND | 10.00 | CAD | REFUNDED |", table)
        self.assertNotIn("Risk Level", table)
        self.select(app, "COMPLETE")
        text = "\n".join(item.value for item in app.markdown)
        self.assertIn("Payment completed at: Not recorded", text)
        self.assertIn("Order created at: Not recorded", text)
        self.assertTrue(any("No saved review history" in item.value for item in app.caption))
        self.assert_no_requests()

    def test_browsing_does_not_change_payment_target_or_send_requests(self):
        self.save("REVIEW-A")
        self.save("REVIEW-B")
        self.save("PAYMENT", status="APPROVED")
        app = self.app()
        app.session_state["paypal_order_id"] = "PAYMENT"
        app.run()
        self.select(app, "REVIEW-A")
        self.select(app, "REVIEW-B")
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT")
        self.assertTrue(any("Current payment order ID: PAYMENT" in item.value for item in app.markdown))
        self.assert_no_requests()

    def test_switching_order_or_baseline_clears_review_and_ai(self):
        self.save("A")
        self.save("B")
        self.save("PENDING", status="APPROVED")
        app = self.app()
        self.select(app, "A")
        app.button(key="analyze_saved_order").click().run()
        app.button(key="generate_ai_explanation").click().run()
        self.assertEqual(app.session_state["ai_explanation"], "Synthetic explanation")
        self.select(app, "B")
        self.assertNotIn("risk_analysis", app.session_state)
        self.assertNotIn("ai_explanation", app.session_state)
        app.button(key="analyze_saved_order").click().run()
        app.number_input(key="simulated_average_CAD").set_value(50.0).run()
        self.assertNotIn("risk_analysis", app.session_state)
        app.button(key="analyze_saved_order").click().run()
        self.select(app, "PENDING")
        self.assertNotIn("risk_analysis", app.session_state)
        self.assertFalse(any(button.key == "analyze_saved_order" for button in app.button))
        self.assertTrue(any("only for completed payments" in item.value for item in app.info))
        self.requests.assert_not_called()
        for mock in self.api.values():
            mock.assert_not_called()

    def test_capture_still_uses_payment_target_while_viewing_another_order(self):
        self.save("REVIEW")
        self.save("PAYMENT", status="APPROVED")
        app = self.app()
        app.session_state["paypal_order_id"] = "PAYMENT"
        app.run()
        self.select(app, "REVIEW")
        capture = self.api["capture_order"]
        capture.side_effect = None
        capture.return_value = ("COMPLETED", "SYNTHETIC-CAPTURE")
        next(button for button in app.button if button.label == "Capture Approved Order").click().run()
        self.assertFalse(app.exception)
        capture.assert_called_once_with("synthetic-id", "synthetic-secret", "PAYMENT")
        self.assertEqual(app.selectbox(key="review_order_id").value, "REVIEW")
        self.assertEqual(order_store.get_order("PAYMENT")["status"], "COMPLETED")
        self.requests.assert_not_called()

    def test_what_if_and_ai_failure_preserve_original_review(self):
        self.save("REVIEW")
        app = self.app()
        app.button(key="analyze_saved_order").click().run()
        original = dict(app.session_state["risk_analysis"])
        next(field for field in app.number_input if field.label.startswith("Hypothetical Order Amount")).set_value(1000.0).run()
        self.assertEqual(dict(app.session_state["risk_analysis"]), original)
        self.explain.side_effect = ai_explanation.AIExplanationError("Synthetic AI failure")
        app.button(key="generate_ai_explanation").click().run()
        self.assertEqual(dict(app.session_state["risk_analysis"]), original)
        self.assertTrue(any("Synthetic AI failure" in item.value for item in app.error))
        self.requests.assert_not_called()


if __name__ == "__main__":
    unittest.main()
