"""Offline visual-summary behavior without changing payment or scoring logic."""

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app

import order_store
import paypal_auth


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class TextContent(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.fragments = []
        self.feed(markup)

    def handle_data(self, value):
        self.fragments.append(value)


class OrderSummaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.start_patch(patch.object(order_store, "DATABASE_PATH", Path(directory.name) / "orders.db"))
        self.start_patch(patch.object(st, "secrets", {}))
        self.network = self.start_patch(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Network forbidden")))
        self.payments = [self.start_patch(patch.object(paypal_auth, name, side_effect=AssertionError("Payment forbidden")))
                         for name in ("get_access_token", "create_order", "capture_order", "get_order_status")]

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def save(self, order_id="A", amount="10.00", currency="CAD", status="COMPLETED"):
        order_store.save_order(order_id, amount, currency)
        if status != "CREATED":
            order_store.update_order_status(order_id, status)

    def app(self):
        app = sandbox_test_app(str(APP_PATH)).run()
        if app.selectbox:
            app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        return app

    def summary(self, app):
        self.assertFalse(app.exception)
        return next(item.value for item in app.markdown if item.value.startswith('<section class="pg-summary"'))

    def assert_no_requests(self):
        self.network.assert_not_called()
        for request in self.payments:
            request.assert_not_called()

    def test_summary_separates_saved_payment_status_and_unanalyzed_session_review(self):
        self.save(amount="12.34", currency="USD")
        app = self.app()
        text = " ".join(TextContent(self.summary(app)).fragments)
        for value in ("12.34", "USD", "Payment status", "COMPLETED", "Rule review", "Not analyzed", "Current session only", "Not saved"):
            self.assertIn(value, text)
        self.assertNotIn("Low Risk", text)
        self.assert_no_requests()

    def test_analyzed_summary_uses_existing_rule_result_without_changing_payment_status(self):
        self.save(amount="600.00")
        app = self.app()
        app.button(key="analyze_saved_order").click().run()
        analysis = app.session_state["risk_analysis"]
        summary = self.summary(app)
        self.assertIn("80/100", summary)
        self.assertIn("High Risk", summary)
        self.assertIn('pg-badge pg-paid">COMPLETED', summary)
        self.assertEqual((analysis["risk_score"], analysis["risk_level"]), (80, "High Risk"))
        self.assertEqual(order_store.get_order("A")["status"], "COMPLETED")
        self.assert_no_requests()

    def test_baseline_order_and_amount_changes_do_not_show_a_stale_review(self):
        self.save()
        self.save("B", "600.00", "USD")
        app = self.app()
        app.selectbox(key="review_order_id").select("A").run()
        app.button(key="open_payment_review").click().run()
        app.button(key="analyze_saved_order").click().run()
        self.assertIn("10/100", self.summary(app))
        app.number_input(key="simulated_average_CAD").set_value(50.0).run()
        self.assertIn("Not analyzed", self.summary(app))
        app.button(key="analyze_saved_order").click().run()
        order_store.save_order("A", "700.00")
        app.run()
        self.assertIn("700.00", self.summary(app))
        self.assertIn("Not analyzed", self.summary(app))
        app.selectbox(key="review_order_id").select("B").run()
        app.button(key="open_payment_review").click().run()
        self.assertIn("USD", self.summary(app))
        self.assertIn("Not analyzed", self.summary(app))
        self.assert_no_requests()

    def test_new_session_does_not_present_prior_analysis_as_saved_history(self):
        self.save()
        app = self.app()
        app.button(key="analyze_saved_order").click().run()
        self.assertIn("10/100", self.summary(app))
        fresh = self.app()
        self.assertIn("Not analyzed", self.summary(fresh))
        self.assertNotIn("Low Risk", self.summary(fresh))
        self.assert_no_requests()

    def test_noncompleted_statuses_show_the_actual_state_without_a_risk_level(self):
        for status in ("CREATED", "APPROVED", "DENIED", "REFUNDED", "REVERSED"):
            with self.subTest(status=status):
                self.save(status, status=status)
                app = self.app()
                app.selectbox(key="review_order_id").select(status).run()
                app.button(key="open_payment_review").click().run()
                summary = next(item.value for item in app.markdown if item.value.startswith('<section class="pg-payment-overview'))
                self.assertIn(f'">{status}</span>', summary)
                self.assertNotIn("Rule review", summary)
                self.assertNotIn("Not analyzed", summary)
                self.assertFalse(any(button.key == "analyze_saved_order" for button in app.button))
        self.assert_no_requests()

    def test_summary_never_changes_payment_target_and_escapes_record_text(self):
        unusual = 'ORDER-<script>alert("test")</script>'
        self.save(unusual)
        self.save("PAYMENT", status="APPROVED")
        app = self.app()
        app.session_state["paypal_order_id"] = "PAYMENT"
        app.selectbox(key="review_order_id").select(unusual).run()
        app.button(key="open_payment_review").click().run()
        summary = self.summary(app)
        self.assertNotIn("<script>", summary)
        self.assertIn("&lt;script&gt;", summary)
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT")
        self.assert_no_requests()


if __name__ == "__main__":
    unittest.main()
