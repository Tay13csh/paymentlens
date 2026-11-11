"""Read-only recent-payment descriptions, shared reasons and bounded filtering."""

import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import ai_explanation
import order_store as store
import paypal_auth
import test_merchant_reconciliation as fixtures
from payment_evidence import PaymentObservation, REVIEW_REASON_LABELS, reconcile_sale


class PaymentViewTests(unittest.TestCase):
    start = fixtures.MerchantReconciliationTests.start

    def setUp(self):
        fixtures.MerchantReconciliationTests.setUp(self)
        self.provider_calls = [self.start(patch.object(paypal_auth, name, side_effect=AssertionError("Provider forbidden")))
                               for name in ("create_order", "capture_order", "get_order_status", "get_access_token")]
        self.ai = self.start(patch.object(ai_explanation, "explain_order_risk", side_effect=AssertionError("AI forbidden")))

    def tearDown(self):
        self.network.assert_not_called()
        self.ai.assert_not_called()
        for call in self.provider_calls:
            call.assert_not_called()

    def sale(self, order_id, description="Handmade mug", expected="10.00", captured="10.00", currency="CAD"):
        sale = store.create_merchant_sale(description, expected)
        attempt = store.begin_sale_creation(sale)
        store.complete_order_creation(attempt, order_id, "https://example.invalid/approve")
        if captured is not None:
            store.record_payment_observation(order_id, self.observation(order_id, captured, currency))
        return sale

    def observation(self, order_id, amount="10.00", currency="CAD"):
        return PaymentObservation({"id": order_id, "status": "COMPLETED", "purchase_units": [{
            "amount": {"value": amount, "currency_code": currency},
            "payments": {"captures": [{"id": "CAPTURE-" + order_id, "status": "COMPLETED", "final_capture": True,
                                       "amount": {"value": amount, "currency_code": currency}}]},
        }]}, order_id, "ORDER_QUERY")

    def app(self):
        app = AppTest.from_file(str(fixtures.APP)).run()
        self.assertFalse(app.exception)
        return app

    def open(self, app, order_id):
        app.selectbox(key="review_order_id").select(order_id).run()
        app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)

    def table(self, app):
        return next(item.value for item in app.markdown if item.value.startswith("| Payment |"))

    def dump(self):
        with sqlite3.connect(self.db) as connection:
            return "\n".join(connection.iterdump())

    def test_duplicate_descriptions_keep_full_ids_and_distinct_labels(self):
        first, second = "FIRST-SAME99", "SECOND-SAME99"
        self.sale(first)
        self.sale(second)
        app = self.app()
        options = app.selectbox(key="review_order_id").options
        self.assertEqual(len(set(options)), 2)
        self.assertTrue(all("Handmade mug · 10.00 CAD" in option and "…SAME99" in option for option in options))
        app.session_state["paypal_order_id"] = "SEPARATE-PAYMENT"
        self.open(app, second)
        self.assertEqual(app.selectbox(key="review_order_id").value, second)
        self.assertEqual(app.session_state["opened_payment_id"], second)
        self.assertEqual(app.session_state["paypal_order_id"], "SEPARATE-PAYMENT")
        self.assertEqual(self.table(app).count("Handmade mug"), 2)
        details = next(item for item in app.expander if item.label == "Record details")
        self.assertTrue(any("Merchant description: Handmade mug" in item.value for item in details.text))

    def test_description_is_literal_text_in_table_overview_and_details(self):
        description = 'Mug | <script>bad()</script> [link](https://example.invalid)'
        self.sale("ESCAPED", description)
        app = self.app()
        self.open(app, "ESCAPED")
        table = self.table(app)
        self.assertIn("&lt;script&gt;", table)
        self.assertIn("\\|", table)
        self.assertIn("\\[link\\]", table)
        self.assertNotIn("<script>", table)
        overview = next(item.value for item in app.markdown if item.value.startswith('<section class="pg-payment-overview'))
        self.assertIn("&lt;script&gt;", overview)
        details = next(item for item in app.expander if item.label == "Record details")
        self.assertTrue(any(item.value == "Merchant description: " + description for item in details.text))

    def test_legacy_history_and_missing_description_are_explicit(self):
        store.save_order("HISTORICAL", "10.00")
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO merchant_sales_orders(sale_id,description,amount,currency) VALUES('EMPTY-DESCRIPTION','','10.00','CAD')")
        attempt = store.begin_sale_creation("EMPTY-DESCRIPTION")
        store.complete_order_creation(attempt, "MISSING-DESCRIPTION", "https://example.invalid")
        app = self.app()
        self.assertIn("No linked merchant order", self.table(app))
        self.assertIn("Description not recorded", self.table(app))
        self.assertIn("Historical data insufficient", self.table(app))
        self.assertNotIn("Amount difference", self.table(app))

    def test_reasons_distinguish_discrepancies_history_conflict_and_terminal_states(self):
        self.sale("MATCH")
        self.sale("DIFFERENCE", expected="12.00")
        self.sale("CURRENCY", currency="USD")
        self.sale("INCOMPLETE", captured=None)
        self.sale("CONFLICT")
        store.record_payment_observation("CONFLICT", self.observation("CONFLICT", "11.00"))
        self.sale("REFUND", expected="12.00")
        store.update_order_status("REFUND", "REFUNDED")
        self.sale("REVERSAL")
        store.update_order_status("REVERSAL", "REVERSED")
        store.save_order("HISTORY", "10.00")
        expected = {
            "MATCH": ("MATCH", set()), "DIFFERENCE": ("DIFFERENCE", {"AMOUNT_DIFFERENCE"}),
            "CURRENCY": ("CURRENCY", {"CURRENCY_MISMATCH"}), "INCOMPLETE": ("INCOMPLETE", {"CAPTURE_EVIDENCE_INCOMPLETE"}),
            "CONFLICT": ("REVIEW", {"EVIDENCE_CONFLICT"}), "REFUND": ("DIFFERENCE", {"AMOUNT_DIFFERENCE", "REFUNDED"}),
            "REVERSAL": ("TERMINAL", {"REVERSED"}), "HISTORY": ("HISTORY", {"HISTORY"}),
        }
        view = store.get_review_view_snapshot()
        for order_id, (code, reasons) in expected.items():
            result = view["by_id"][order_id]["result"]
            self.assertEqual(result["code"], code)
            self.assertEqual(set(result["reasons"]), reasons)
            self.assertEqual(result["needs_review"], code != "MATCH")
        app = self.app()
        app.radio(key="review_filter").set_value("Needs review").run()
        table = self.table(app)
        for reason in ("AMOUNT_DIFFERENCE", "CURRENCY_MISMATCH", "EVIDENCE_CONFLICT", "CAPTURE_EVIDENCE_INCOMPLETE", "REFUNDED", "REVERSED", "HISTORY"):
            self.assertIn(REVIEW_REASON_LABELS[reason], table)
        self.assertNotIn("high risk", table.lower())
        self.assertNotIn("payment failed", table.lower())

    def test_filter_retains_match_selection_review_inputs_and_payment_target(self):
        self.sale("MATCH", description="Matching mug")
        self.sale("DIFFERENCE", description="Different mug", expected="12.00")
        app = self.app()
        self.open(app, "MATCH")
        app.number_input(key="simulated_average_CAD").set_value(5.0).run()
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Saved rule observation"
        app.session_state["paypal_order_id"] = "PAYMENT-TARGET"
        app.run()
        analysis = dict(app.session_state["risk_analysis"])
        before = self.dump()
        app.radio(key="review_filter").set_value("Needs review").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="review_order_id").value, "MATCH")
        self.assertTrue(any("Outside current filter" in item.value for item in app.info))
        self.assertNotIn("Matching mug", self.table(app))
        self.assertEqual(app.session_state["opened_payment_id"], "MATCH")
        self.assertEqual(dict(app.session_state["risk_analysis"]), analysis)
        self.assertEqual(app.session_state["ai_explanation"], "Saved rule observation")
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT-TARGET")
        app.selectbox(key="review_order_id").select("DIFFERENCE").run()
        self.assertEqual(app.session_state["opened_payment_id"], "MATCH")
        app.button(key="open_payment_review").click().run()
        self.assertEqual(app.session_state["opened_payment_id"], "DIFFERENCE")
        app.radio(key="review_filter").set_value("All in this view").run()
        self.assertEqual(app.selectbox(key="review_order_id").value, "DIFFERENCE")
        self.assertEqual(self.dump(), before)

    def test_unsupported_structure_and_unconfirmed_status_keep_original_conclusions(self):
        self.sale("UNSUPPORTED", captured=None)
        capture = {"id": "CAPTURE-UNSUPPORTED", "status": "COMPLETED", "final_capture": True,
                   "amount": {"value": "10.00", "currency_code": "CAD"}}
        payload = {"id": "UNSUPPORTED", "status": "COMPLETED", "purchase_units": [
            {"amount": {"value": "10.00", "currency_code": "CAD"}, "payments": {"captures": [capture]}}, {},
        ]}
        store.record_payment_observation("UNSUPPORTED", PaymentObservation(payload, "UNSUPPORTED", "ORDER_QUERY"))
        result = store.get_review_view_snapshot()["by_id"]["UNSUPPORTED"]["result"]
        self.assertEqual(result["code"], "REVIEW")
        self.assertEqual(result["reasons"], ["UNSUPPORTED_STRUCTURE"])
        self.sale("COMPLETE")
        evidence = store.get_review_view_snapshot()["by_id"]["COMPLETE"]
        order = {**evidence["order"], "status": "APPROVED", "capture_state": "READY"}
        result = reconcile_sale(evidence["sale"], order, evidence["captures"], [])
        self.assertEqual(result["code"], "INCOMPLETE")
        self.assertEqual(result["summary"], "Current payment completion is unconfirmed")
        self.assertEqual(result["reasons"], ["PAYMENT_NOT_COMPLETED"])

    def test_saved_decimal_amount_is_not_rounded_through_float_for_display(self):
        amount = "12345678901234567890123456.78"
        store.save_order("LEGACY-LARGE", amount)
        app = self.app()
        self.open(app, "LEGACY-LARGE")
        self.assertIn(amount, self.table(app))
        overview = next(item.value for item in app.markdown if item.value.startswith('<section class="pg-payment-overview'))
        self.assertIn(amount, overview)

    def test_zero_matches_does_not_hide_an_older_selected_discrepancy(self):
        self.sale("OLDER", expected="12.00")
        for index in range(20):
            self.sale(f"RECENT-{index:02}")
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE orders SET updated_at='2030-01-01' WHERE order_id<>'OLDER'")
            connection.execute("UPDATE orders SET updated_at='2000-01-01' WHERE order_id='OLDER'")
        app = AppTest.from_file(str(fixtures.APP))
        app.session_state["selected_payment_id"] = "OLDER"
        app.session_state["opened_payment_id"] = "OLDER"
        app.run()
        app.radio(key="review_filter").set_value("Needs review").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Needs review: 0 of 20" in item.value for item in app.caption))
        self.assertTrue(any("Outside recent 20" in item.value for item in app.info))
        self.assertTrue(any("Older records were not checked" in item.value for item in app.info))
        self.assertEqual(app.selectbox(key="review_order_id").value, "OLDER")
        self.assertTrue(any("below merchant expectation" in item.value for item in app.warning))
        self.assertFalse(any(item.value.startswith("| Payment |") for item in app.markdown))

    def test_filter_persists_across_navigation_without_changing_target(self):
        self.sale("ORDER", expected="12.00")
        app = self.app()
        self.open(app, "ORDER")
        app.session_state["paypal_order_id"] = "PAYMENT-TARGET"
        app.radio(key="review_filter").set_value("Needs review").run()
        app.radio(key="main_navigation").set_value("Test sales orders").run()
        app.radio(key="main_navigation").set_value("Review payments").run()
        self.assertEqual(app.radio(key="review_filter").value, "Needs review")
        self.assertEqual(app.session_state["paypal_order_id"], "PAYMENT-TARGET")
        self.assertEqual(app.session_state["opened_payment_id"], "ORDER")

    def test_deleted_merchant_payment_clears_selection_without_inventing_another(self):
        self.sale("DELETED")
        self.sale("REMAINING")
        app = self.app()
        self.open(app, "DELETED")
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM orders WHERE order_id='DELETED'")
        app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.selectbox(key="review_order_id").value)
        self.assertNotIn("opened_payment_id", app.session_state)
        self.assertTrue(app.button(key="open_payment_review").disabled)
        self.assertTrue(any("no longer available" in item.value for item in app.warning))

    def test_filter_reads_no_migrations_or_separate_order_snapshots(self):
        self.sale("ORDER")
        before = self.dump()
        with patch.object(store, "initialize_database", side_effect=AssertionError("No migration during filtering")), \
             patch.object(store, "get_orders", side_effect=AssertionError("No old list read")), \
             patch.object(store, "get_order", side_effect=AssertionError("No separate order read")), \
             patch.object(store, "get_sale_reconciliation", side_effect=AssertionError("Use shared view snapshot")):
            app = self.app()
            self.open(app, "ORDER")
            app.radio(key="review_filter").set_value("Needs review").run()
            app.radio(key="review_filter").set_value("All in this view").run()
            self.assertFalse(app.exception)
        self.assertEqual(self.dump(), before)

    def test_missing_database_and_old_schema_are_not_created_or_migrated(self):
        self.assertFalse(self.db.exists())
        app = self.app()
        app.radio(key="review_filter").set_value("Needs review").run()
        self.assertFalse(self.db.exists())
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE orders(order_id TEXT PRIMARY KEY, amount TEXT, currency TEXT, status TEXT, updated_at TEXT)")
            connection.execute("INSERT INTO orders VALUES('OLD','10.00','CAD','COMPLETED','2020-01-01')")
        before = self.dump()
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Payment view unavailable" in item.value for item in app.error))
        self.assertFalse(any("Needs review:" in item.value for item in app.caption))
        self.assertEqual(self.dump(), before)

    def test_recent_view_is_one_read_only_snapshot_during_concurrent_fill(self):
        self.sale("A", captured=None)
        self.sale("B", captured=None)
        before = store.get_review_view_snapshot()
        with sqlite3.connect(self.db) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("UPDATE orders SET updated_at=updated_at")
        ready, committed = threading.Event(), threading.Event()
        reader_ident = []
        case = self
        class Row:
            def __init__(self, row):
                self.row = row
            def fetchone(self):
                return self.row
        class Connection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                cursor = super().execute(sql, *args, **kwargs)
                if (reader_ident and threading.get_ident() == reader_ident[0]
                        and sql == "SELECT * FROM orders WHERE order_id=?" and not ready.is_set()):
                    row = cursor.fetchone()
                    cursor.close()
                    case.assertTrue(self.in_transaction)
                    case.assertEqual(super().execute("PRAGMA query_only").fetchone()[0], 1)
                    ready.set()
                    if not committed.wait(5):
                        raise AssertionError("Writer did not commit")
                    return Row(row)
                return cursor
        def connect():
            connection = sqlite3.connect(self.db.resolve().as_uri() + "?mode=ro", uri=True, factory=Connection)
            connection.row_factory = sqlite3.Row
            return connection
        def reader():
            reader_ident.append(threading.get_ident())
            return store.get_review_view_snapshot()
        def writer():
            if not ready.wait(5):
                raise AssertionError("Reader did not pause")
            try:
                store.record_payment_observation("B", self.observation("B"))
            finally:
                committed.set()
        with patch.object(store, "_connect_review_view", side_effect=connect), ThreadPoolExecutor(max_workers=2) as pool:
            read, write = pool.submit(reader), pool.submit(writer)
            snapshot = read.result(timeout=12)
            write.result(timeout=12)
        self.assertEqual(snapshot, before)
        self.assertEqual(snapshot["by_id"]["B"]["result"]["code"], "INCOMPLETE")
        self.assertEqual(store.get_review_view_snapshot()["by_id"]["B"]["result"]["code"], "MATCH")


if __name__ == "__main__":
    unittest.main()
