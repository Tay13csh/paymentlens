"""Offline checks for opening payments explicitly before optional simulations."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app

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
        app = sandbox_test_app(str(APP_PATH)).run()
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
        review = app
        self.assertTrue(any("No saved payments" in item.value and "Sandbox tools section" in item.value and "Create Sandbox Order" in item.value for item in review.info))
        self.assertEqual([button.key for button in review.button], ["clear_payment_filters"])
        self.assertFalse(review.number_input)
        app.radio(key="main_navigation").set_value("Sandbox tools").run()
        self.assertTrue(any(button.label == "Create Sandbox Order" for button in app.button))
        self.assertTrue(any(button.label == "Get Sandbox Access Token" for button in app.button))
        self.assert_no_requests()

    def test_initial_selection_requires_review_action_without_a_baseline(self):
        self.save()
        app = self.app()
        review = app
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
        rules = next(item for item in app.expander if item.label == "Simulated rule analysis")
        self.assertTrue(any(button.key == "generate_ai_explanation" for button in rules.button))
        self.assertFalse(any(tab.label == "Rule review" for tab in app.tabs))
        self.assertTrue(any(button.key == "generate_ai_explanation" for button in app.button))
        self.assertTrue(any("does not verify the payment or review payment notifications" in item.value for item in app.caption))
        app.radio(key="main_navigation").set_value("Sandbox tools").run()
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in app.button))
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
        panel = next(item for item in app.expander if item.label == "Simulated rule analysis")
        self.assertTrue(panel.proto.expanded)
        self.assertFalse(next(item for item in app.expander if item.label == "Explore assumptions").proto.expanded)
        self.assertEqual(sum(field.key == "simulated_average_CAD" for field in app.number_input), 1)
        self.assertTrue(any(field.key == "simulated_average_CAD" for field in panel.number_input))
        self.assertTrue(any(button.key == "analyze_saved_order" for button in panel.button))
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

    def test_inline_rule_flow_uses_one_control_set_and_clears_stale_results(self):
        self.save()
        app = self.app()
        self.open(app)
        app.button(key="open_rule_analysis").click().run()
        panel = next(item for item in app.expander if item.label == "Simulated rule analysis")
        panel.number_input(key="simulated_average_CAD").set_value(5.0).run()
        self.assertNotIn("risk_analysis", app.session_state)
        self.ai.assert_not_called()
        app.button(key="analyze_saved_order").click().run()
        panel = next(item for item in app.expander if item.label == "Simulated rule analysis")
        self.assertTrue(any(metric.label == "Risk Score" and metric.value == "50/100" for metric in panel.metric))
        self.assertEqual(sum(button.key == "analyze_saved_order" for button in app.button), 1)
        self.assertEqual(sum(button.key == "generate_ai_explanation" for button in app.button), 1)
        self.assertTrue(any(button.key == "generate_ai_explanation" for button in panel.button))
        headings = [item.value for item in app.subheader]
        self.assertLess(headings.index("AI rule explanation"), headings.index("Order Risk Analysis Result"))
        self.assertLess(headings.index("Order Risk Analysis Result"), headings.index("Payment records"))
        app.session_state["ai_explanation"] = "Old observation"
        app.number_input(key="simulated_average_CAD").set_value(2.0).run()
        self.assertNotIn("risk_analysis", app.session_state)
        self.assertNotIn("ai_explanation", app.session_state)
        self.assertFalse(any(button.key == "generate_ai_explanation" for button in app.button))
        panel = next(item for item in app.expander if item.label == "Simulated rule analysis")
        self.assertTrue(panel.proto.expanded)
        self.assertTrue(any(button.key == "analyze_saved_order" for button in panel.button))
        self.assertTrue(any(tab.label == "Compare baselines" for tab in app.tabs))
        self.assertTrue(any(tab.label == "Hypothetical amount" for tab in app.tabs))
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
        self.assertEqual(sum("A missing notification does not mean payment failed" in item.value for item in app.caption), 1)
        self.assertFalse(any("Payment occurrence time is not recorded" in item.value for item in app.info))
        self.assert_no_requests()

    def test_reordering_keeps_pending_selection_and_opened_payment_separate(self):
        self.save()
        self.save(B)
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("UPDATE orders SET updated_at = '2020-01-01' WHERE order_id = ?", (A,))
            connection.execute("UPDATE orders SET updated_at = '2030-01-01' WHERE order_id = ?", (B,))
        app = self.app()
        self.open(app)
        app.session_state["paypal_order_id"] = A
        app.selectbox(key="review_order_id").select(B).run()
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("UPDATE orders SET updated_at = '2030-01-01' WHERE order_id = ?", (A,))
            connection.execute("UPDATE orders SET updated_at = '2020-01-01' WHERE order_id = ?", (B,))
        app.run()
        self.assertEqual(app.selectbox(key="review_order_id").value, B)
        self.assertEqual(app.session_state["opened_payment_id"], A)
        self.assertEqual(app.session_state["paypal_order_id"], A)
        self.assertIn("…111111", self.overview(app))
        app.button(key="open_payment_review").click().run()
        self.assertEqual(app.session_state["opened_payment_id"], B)
        self.assert_no_requests()

    def test_missing_pending_selection_requires_explicit_reselection(self):
        self.save()
        self.save(B)
        app = self.app()
        self.open(app)
        app.selectbox(key="review_order_id").select(B).run()
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("DELETE FROM orders WHERE order_id = ?", (B,))
        app.run()
        self.assertIsNone(app.selectbox(key="review_order_id").value)
        self.assertTrue(app.button(key="open_payment_review").disabled)
        self.assertEqual(app.session_state["opened_payment_id"], A)
        self.assertIn("…111111", self.overview(app))
        self.assertTrue(any("no longer available" in item.value and "Select a payment again" in item.value for item in app.warning))
        app.run()
        self.assertIsNone(app.selectbox(key="review_order_id").value)
        app.selectbox(key="review_order_id").select(A).run()
        self.assertFalse(app.button(key="open_payment_review").disabled)
        self.assert_no_requests()

    def test_missing_opened_payment_clears_results_without_opening_another(self):
        self.save()
        self.save(B)
        app = self.app()
        self.open(app)
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Old observation"
        app.text_input(key=f"expected_amount_{A}").set_value("10").run()
        app.button(key="check_expected_payment").click().run()
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("DELETE FROM orders WHERE order_id = ?", (A,))
        app.run()
        self.assertIsNone(app.selectbox(key="review_order_id").value)
        for key in ("opened_payment_id", "risk_analysis", "ai_explanation", "payment_check_result"):
            self.assertNotIn(key, app.session_state)
        self.assertFalse(any(item.value.startswith('<section class="pg-payment-overview') for item in app.markdown))
        app.selectbox(key="review_order_id").select(B).run()
        self.assertNotIn("opened_payment_id", app.session_state)
        app.button(key="open_payment_review").click().run()
        self.assertEqual(app.session_state["opened_payment_id"], B)
        self.assert_no_requests()

    def test_existing_selection_outside_recent_list_is_not_treated_as_deleted(self):
        self.save()
        self.save(B)
        app = self.app()
        self.open(app)
        for index in range(20):
            self.save(f"RECENT-{index:02}")
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("UPDATE orders SET updated_at='2030-01-01' WHERE order_id<>?", (A,))
            connection.execute("UPDATE orders SET updated_at='2000-01-01' WHERE order_id=?", (A,))
        app.run()
        self.assertEqual(app.selectbox(key="review_order_id").value, A)
        self.assertEqual(app.session_state["opened_payment_id"], A)
        self.assertFalse(any("no longer available" in item.value for item in app.warning))
        self.assertTrue(any("Outside recent 20" in item.value for item in app.info))
        self.assert_no_requests()

    def test_removing_all_orders_does_not_auto_select_a_later_record(self):
        self.save()
        app = self.app()
        self.open(app)
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("DELETE FROM orders")
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn("opened_payment_id", app.session_state)
        self.assertTrue(any("Select a payment again" in item.value for item in app.warning))
        self.save(B)
        app.run()
        self.assertIsNone(app.selectbox(key="review_order_id").value)
        self.assertTrue(app.button(key="open_payment_review").disabled)
        self.assertNotIn("opened_payment_id", app.session_state)
        self.assert_no_requests()

    def test_primary_actions_and_selected_preset_keep_distinct_button_types(self):
        self.save()
        app = self.app()
        self.open(app)
        self.assertEqual(app.button(key="open_payment_review").proto.type, "primary")
        self.assertEqual(app.button(key="check_expected_payment").proto.type, "primary")
        self.assertEqual(app.button(key="open_rule_analysis").proto.type, "secondary")
        presets = {button.label: button for button in app.button if button.label.startswith("Use baseline")}
        self.assertEqual(presets["Use baseline 10 CAD"].proto.type, "primary")
        self.assertEqual(presets["Use baseline 5 CAD"].proto.type, "secondary")
        presets["Use baseline 5 CAD"].click().run()
        presets = {button.label: button for button in app.button if button.label.startswith("Use baseline")}
        self.assertEqual(presets["Use baseline 5 CAD"].proto.type, "primary")
        self.assertEqual(presets["Use baseline 10 CAD"].proto.type, "secondary")
        self.assertTrue(any(item.value == "**Selected preset: 5 CAD**" for item in app.markdown))
        self.assert_no_requests()


if __name__ == "__main__":
    unittest.main()
