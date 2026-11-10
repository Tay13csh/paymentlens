"""Offline expectation checks against local order records, not verified receipts."""

import sqlite3
import unittest

import order_store
import test_first_use as first_use

A, B = first_use.A, first_use.B


class PaymentCheckTests(unittest.TestCase):
    setUp = first_use.FirstUseTests.setUp
    start_patch = first_use.FirstUseTests.start_patch
    save = first_use.FirstUseTests.save
    app = first_use.FirstUseTests.app
    open = first_use.FirstUseTests.open
    assert_no_requests = first_use.FirstUseTests.assert_no_requests

    def tearDown(self):
        self.assert_no_requests()

    def check(self, app, amount="10.00", currency="CAD", order_id=A):
        app.text_input(key=f"expected_amount_{order_id}").set_value(amount).run()
        app.selectbox(key=f"expected_currency_{order_id}").select(currency).run()
        app.button(key="check_expected_payment").click().run()
        self.assertFalse(app.exception)

    def output(self, app):
        return "\n".join(item.value for item in app.markdown) + "\n" + "\n".join(item.value for item in app.warning) + "\n" + "\n".join(item.value for item in app.info)

    def test_compact_match_with_explicit_local_sources_in_collapsed_details(self):
        self.save()
        app = self.app()
        self.open(app)
        self.assertNotIn("payment_check_result", app.session_state)
        self.check(app)
        self.assertTrue(any(item.label == "Recorded order amount" and item.value == "10.00 CAD" for item in app.metric))
        self.assertIn("0.00 CAD — matches expectation", self.output(app))
        self.assertIn("Local status is COMPLETED", self.output(app))
        details = next(item for item in app.expander if item.label == "Details")
        self.assertFalse(details.proto.expanded)
        self.assertIn("Amount check: Match", "\n".join(item.value for item in details.markdown))
        self.assertTrue(any("not an independently verified Capture amount" in item.value for item in details.caption))

    def test_exact_directional_differences_without_float_rounding(self):
        self.save(amount="0.30")
        app = self.app()
        self.open(app)
        for expected, difference, direction in (("0.10", "0.20", "above"), ("0.50", "0.20", "below"), ("0.3000", "0.00", "matches")):
            self.check(app, expected)
            self.assertIn(f"{difference} CAD", self.output(app))
            self.assertIn(direction, self.output(app))
        self.assertNotIn("underpaid", self.output(app))

    def test_currency_mismatch_has_visible_warning_and_no_subtraction(self):
        self.save()
        app = self.app()
        self.open(app)
        self.check(app, "12", "USD")
        self.assertTrue(any("currency differs" in item.value for item in app.warning))
        self.assertIn("Not calculated — currencies differ", self.output(app))
        self.assertIn("Amount check: Not compared across currencies", self.output(app))
        self.assertNotIn("2.00 USD", self.output(app))

    def test_approved_and_other_states_never_claim_completion(self):
        for status in ("CREATED", "APPROVED", "DENIED"):
            with self.subTest(status=status):
                self.save(status, status=status)
                app = self.app()
                self.open(app, status)
                self.check(app, order_id=status)
                self.assertTrue(any("completed payment is not confirmed" in item.value for item in app.warning))
                self.assertNotIn("Local status is COMPLETED", self.output(app))

    def test_refund_and_reversal_override_historical_completed_capture(self):
        for status in ("REFUNDED", "REVERSED"):
            with self.subTest(status=status):
                self.save(status)
                order_store.update_order_status(status, status)
                self.assertEqual(order_store.get_order(status)["capture_state"], "COMPLETED")
                app = self.app()
                self.open(app, status)
                self.check(app, order_id=status)
                self.assertTrue(any(f"Local status is {status}; this is not a currently completed payment" in item.value for item in app.warning))

    def test_unknown_and_in_progress_capture_are_explicitly_unconfirmed(self):
        self.save(status="APPROVED")
        for state in ("UNKNOWN", "IN_PROGRESS"):
            with sqlite3.connect(order_store.DATABASE_PATH) as connection:
                connection.execute("UPDATE orders SET capture_state = ? WHERE order_id = ?", (state, A))
            app = self.app()
            self.open(app)
            self.check(app)
            self.assertTrue(any("Completion is unconfirmed" in item.value and state in item.value for item in app.warning))

    def test_invalid_inputs_clear_previous_result_and_never_round(self):
        self.save()
        app = self.app()
        self.open(app)
        for invalid in ("", "0", "-1", "NaN", "Infinity", "1.001", "nonsense", "1e1000"):
            with self.subTest(invalid=invalid):
                self.check(app)
                app.text_input(key=f"expected_amount_{A}").set_value(invalid).run()
                self.assertNotIn("payment_check_result", app.session_state)
                app.button(key="check_expected_payment").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertFalse(any(item.label == "Recorded order amount" for item in app.metric))

    def test_currency_edit_and_record_update_require_explicit_recheck(self):
        self.save()
        app = self.app()
        self.open(app)
        self.check(app)
        app.selectbox(key=f"expected_currency_{A}").select("USD").run()
        self.assertNotIn("payment_check_result", app.session_state)
        self.check(app)
        order_store.update_order_status(A, "REFUNDED")
        app.run()
        self.assertNotIn("payment_check_result", app.session_state)
        self.assertFalse(any(item.label == "Recorded order amount" for item in app.metric))
        app.button(key="check_expected_payment").click().run()
        self.assertTrue(any("REFUNDED" in item.value for item in app.warning))
        for field, value in (("amount", "11.00"), ("currency", "USD"), ("capture_state", "UNKNOWN"),
                             ("capture_id", "NEW-REFERENCE"), ("updated_at", "2030-01-01 00:00:00")):
            with self.subTest(changed_field=field):
                with sqlite3.connect(order_store.DATABASE_PATH) as connection:
                    connection.execute(f"UPDATE orders SET {field} = ? WHERE order_id = ?", (value, A))
                app.run()
                self.assertNotIn("payment_check_result", app.session_state)
                app.button(key="check_expected_payment").click().run()
                self.assertIn("payment_check_result", app.session_state)

    def test_pending_selection_and_opened_order_changes_invalidate_results(self):
        self.save()
        self.save(B, "25.00", "USD")
        app = self.app()
        self.open(app)
        self.check(app)
        app.selectbox(key="review_order_id").select(B).run()
        self.assertNotIn("payment_check_result", app.session_state)
        self.assertTrue(app.button(key="check_expected_payment").disabled)
        app.button(key="open_payment_review").click().run()
        self.assertNotIn("payment_check_result", app.session_state)
        self.assertEqual(app.text_input(key=f"expected_amount_{B}").value, "")
        self.check(app, "25", "USD", B)
        self.assertTrue(any(item.label == "Recorded order amount" and item.value == "25.00 USD" for item in app.metric))

    def test_check_does_not_change_rule_ai_payment_target_or_database(self):
        self.save()
        app = self.app()
        self.open(app)
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Existing observation"
        app.session_state["paypal_order_id"] = "SEPARATE-PAYMENT-TARGET"
        app.run()
        analysis = dict(app.session_state["risk_analysis"])
        signature = app.session_state["risk_analysis_signature"]
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            original = "\n".join(connection.iterdump())
        self.check(app, "12")
        self.assertEqual(dict(app.session_state["risk_analysis"]), analysis)
        self.assertEqual(app.session_state["risk_analysis_signature"], signature)
        self.assertEqual(app.session_state["ai_explanation"], "Existing observation")
        self.assertEqual(app.session_state["paypal_order_id"], "SEPARATE-PAYMENT-TARGET")
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            self.assertEqual("\n".join(connection.iterdump()), original)

    def test_unsupported_or_imprecise_record_is_not_silently_converted(self):
        for amount, currency in (("10", "JPY"), ("10.001", "CAD")):
            with self.subTest(amount=amount, currency=currency):
                self.save(A, amount, currency)
                app = self.app()
                self.open(app)
                self.check(app)
                self.assertTrue(app.error)
                self.assertNotIn("payment_check_result", app.session_state)


if __name__ == "__main__":
    unittest.main()
