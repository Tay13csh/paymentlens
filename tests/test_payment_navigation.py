"""Local navigation selects durable links without invoking payment operations."""

import sqlite3
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import order_store as store
import paypal_auth
import test_merchant_reconciliation as fixtures


class PaymentNavigationTests(unittest.TestCase):
    start = fixtures.MerchantReconciliationTests.start
    linked = fixtures.MerchantReconciliationTests.linked

    def setUp(self):
        fixtures.MerchantReconciliationTests.setUp(self)
        self.provider_calls = [self.start(patch.object(paypal_auth, name, side_effect=AssertionError("Provider call forbidden")))
                               for name in ("get_access_token", "create_order", "capture_order", "get_order_status")]

    def tearDown(self):
        self.network.assert_not_called()
        for call in self.provider_calls:
            call.assert_not_called()

    def app(self):
        app = AppTest.from_file(str(fixtures.APP)).run()
        self.assertFalse(app.exception)
        return app

    def go(self, app, section):
        app.radio(key="main_navigation").set_value(section).run()
        self.assertFalse(app.exception)

    def database_dump(self):
        with sqlite3.connect(self.db) as connection:
            return "\n".join(connection.iterdump())

    def activate(self, app, sale):
        self.go(app, "Test sales orders")
        app.selectbox(key="merchant_sale_id").select(sale).run()
        with patch.object(store, "begin_sale_creation", side_effect=AssertionError("Navigation must not reserve an attempt")) as reserve:
            app.button(key="activate_merchant_payment").click().run()
            reserve.assert_not_called()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="main_navigation").value, "Sandbox tools")

    def test_link_button_opens_correct_payment_and_keeps_review_state(self):
        sale, attempt = self.linked(order_id="PAYMENT-A")
        store.save_order("REVIEW", "10.00")
        store.update_order_status("REVIEW", "COMPLETED")
        app = self.app()
        app.selectbox(key="review_order_id").select("REVIEW").run()
        app.button(key="open_payment_review").click().run()
        app.number_input(key="simulated_average_CAD").set_value(5.0).run()
        app.button(key="analyze_saved_order").click().run()
        app.text_input(key="expected_amount_REVIEW").set_value("12").run()
        app.session_state["ai_explanation"] = "Existing observation"
        app.session_state["paypal_order_id"] = "OTHER-TARGET"
        app.query_params["token"] = "OTHER-TARGET"
        app.run()
        analysis = dict(app.session_state["risk_analysis"])
        before = self.database_dump()
        self.activate(app, sale)
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT-A")
        self.assertEqual(app.session_state["opened_payment_id"], "REVIEW")
        self.assertEqual(app.session_state["selected_payment_id"], "REVIEW")
        self.assertEqual(app.query_params["create_attempt"], [attempt])
        self.assertNotIn("token", app.query_params)
        self.assertTrue(any("Active linked PayPal order: PAYMENT-A" in item.value and sale in item.value for item in app.info))
        self.assertEqual(self.database_dump(), before)
        self.go(app, "Review payments")
        self.assertEqual(dict(app.session_state["risk_analysis"]), analysis)
        self.assertEqual(app.session_state["ai_explanation"], "Existing observation")
        self.assertEqual(app.number_input(key="simulated_average_CAD").value, 5.0)
        self.assertEqual(app.text_input(key="expected_amount_REVIEW").value, "12")
        self.assertEqual(app.selectbox(key="review_order_id").value, "REVIEW")
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT-A")

    def test_repeated_navigation_can_switch_between_existing_links(self):
        first, _ = self.linked(order_id="PAYMENT-A")
        second, second_attempt = self.linked("25.00", order_id="PAYMENT-B")
        app = self.app()
        before = self.database_dump()
        self.activate(app, first)
        self.activate(app, second)
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT-B")
        self.assertEqual(app.query_params["create_attempt"], [second_attempt])
        self.assertTrue(any("Active linked PayPal order: PAYMENT-B" in item.value and second in item.value and "25.00 CAD" in item.value for item in app.info))
        self.assertEqual(self.database_dump(), before)

    def test_refresh_restores_the_selected_saved_attempt_without_request(self):
        sale, attempt = self.linked(order_id="PAYMENT-A")
        app = self.app()
        self.activate(app, sale)
        refreshed = AppTest.from_file(str(fixtures.APP))
        refreshed.query_params.update(app.query_params)
        refreshed.run()
        self.assertFalse(refreshed.exception)
        self.assertEqual(refreshed.radio(key="main_navigation").value, "Sandbox tools")
        self.assertEqual(refreshed.session_state["paypal_order_id"], "PAYMENT-A")
        self.assertEqual(refreshed.session_state["paypal_approval_url"], "https://example.invalid/approve")
        self.assertEqual(refreshed.query_params["create_attempt"], [attempt])
        self.assertTrue(any(sale in item.value for item in refreshed.info))

    def test_missing_attempt_reports_error_without_creating_or_changing_target(self):
        sale, attempt = self.linked()
        app = self.app()
        self.go(app, "Test sales orders")
        app.session_state["paypal_order_id"] = "UNCHANGED-TARGET"
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM order_creation_attempts WHERE request_id=?", (attempt,))
        before = self.database_dump()
        with patch.object(store, "begin_sale_creation", side_effect=AssertionError("No new attempt")):
            app.button(key="activate_merchant_payment").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="main_navigation").value, "Test sales orders")
        self.assertEqual(app.session_state["paypal_order_id"], "UNCHANGED-TARGET")
        self.assertTrue(any("creation attempt is unavailable" in item.value for item in app.error))
        self.assertEqual(self.database_dump(), before)


if __name__ == "__main__":
    unittest.main()
