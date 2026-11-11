"""Real concurrent SQLite reads/writes using isolated WAL databases only."""

import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app

import order_store as store
import test_merchant_reconciliation as fixtures


class ReconciliationSnapshotTests(unittest.TestCase):
    setUp = fixtures.MerchantReconciliationTests.setUp
    start = fixtures.MerchantReconciliationTests.start
    linked = fixtures.MerchantReconciliationTests.linked
    capture = fixtures.MerchantReconciliationTests.capture
    observation = fixtures.MerchantReconciliationTests.observation
    capture_only_refund = fixtures.MerchantReconciliationTests.capture_only_refund

    def tearDown(self):
        self.network.assert_not_called()

    def concurrent_read(self, write, pause_after_captures=False):
        before = store.get_sale_reconciliation("ORDER")
        # WAL permits the writer to commit while an explicit reader snapshot lives.
        # This PRAGMA changes this temporary fixture only, never the application mode.
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        reader_ready, writer_committed = threading.Event(), threading.Event()
        reader_ident, read_threads, reader_transactions = [], [], []
        case = self

        def pause(connection):
            read_threads.append(threading.get_ident())
            reader_transactions.append(connection.in_transaction)
            reader_ready.set()
            if not writer_committed.wait(5):
                raise AssertionError("Writer did not complete while reader was paused")

        class RowResult:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        class PausingConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                cursor = super().execute(sql, *args, **kwargs)
                is_reader = reader_ident and threading.get_ident() == reader_ident[0]
                target = "SELECT * FROM capture_evidence" if pause_after_captures else "SELECT * FROM orders WHERE order_id=?"
                if is_reader and sql.startswith(target) and not reader_ready.is_set():
                    if pause_after_captures:
                        rows = cursor.fetchall()
                        cursor.close()
                        pause(self)
                        return iter(rows)
                    row = cursor.fetchone()
                    cursor.close()
                    pause(self)
                    return RowResult(row)
                return cursor

        def connect():
            connection = sqlite3.connect(case.db, factory=PausingConnection)
            connection.row_factory = sqlite3.Row
            return connection

        def read():
            reader_ident.append(threading.get_ident())
            return store.get_sale_reconciliation("ORDER")

        def writer():
            if not reader_ready.wait(5):
                raise AssertionError("Reader did not reach the planned interleaving")
            try:
                write()
                return threading.get_ident()
            finally:
                writer_committed.set()

        with patch.object(store, "_connect", side_effect=connect), ThreadPoolExecutor(max_workers=2) as pool:
            read_future, write_future = pool.submit(read), pool.submit(writer)
            try:
                snapshot = read_future.result(timeout=12)
                writer_thread = write_future.result(timeout=12)
            finally:
                writer_committed.set()
        self.assertEqual(len(read_threads), 1, "No automatic retry or repeated read")
        self.assertNotEqual(read_threads[0], writer_thread)
        self.assertEqual(snapshot, before, "A reconciliation must not combine different committed versions")
        self.assertEqual(reader_transactions, [True], "The snapshot must use an explicit read transaction")
        return snapshot, store.get_sale_reconciliation("ORDER")

    def test_capture_completion_while_reading_keeps_the_old_incomplete_snapshot(self):
        self.linked()
        store.update_order_status("ORDER", "COMPLETED")
        snapshot, current = self.concurrent_read(lambda: store.record_payment_observation("ORDER", self.observation()))
        self.assertEqual(snapshot["result"]["code"], "INCOMPLETE")
        self.assertEqual(snapshot["captures"], [])
        self.assertEqual(current["result"]["code"], "MATCH")

    def test_early_refund_replay_during_capture_fill_never_creates_a_mixed_match(self):
        self.linked()
        store.update_order_status("ORDER", "COMPLETED")
        store.record_webhook_event(self.capture_only_refund())
        snapshot, current = self.concurrent_read(lambda: store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY")))
        self.assertEqual(snapshot["result"]["code"], "INCOMPLETE")
        self.assertEqual(current["order"]["status"], "REFUNDED")
        self.assertEqual(current["result"]["code"], "TERMINAL")

    def test_reversal_during_read_returns_one_complete_old_version(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation())
        event = {"id": "REVERSAL", "event_type": "PAYMENT.CAPTURE.REVERSED", "resource": {"id": "CAPTURE"}}
        snapshot, current = self.concurrent_read(lambda: store.record_webhook_event(event))
        self.assertEqual(snapshot["order"]["status"], "COMPLETED")
        self.assertEqual(snapshot["result"]["code"], "MATCH")
        self.assertEqual(current["order"]["status"], "REVERSED")
        self.assertEqual(current["result"]["code"], "TERMINAL")

    def test_conflict_during_read_cannot_attach_new_observations_to_old_match(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation())
        conflict = self.observation(self.capture("11.00"), source="ORDER_QUERY", order_amount="11.00")
        snapshot, current = self.concurrent_read(lambda: store.record_payment_observation("ORDER", conflict), pause_after_captures=True)
        self.assertEqual(snapshot["result"]["code"], "MATCH")
        self.assertEqual(len(snapshot["observations"]), 1)
        self.assertEqual(current["result"]["code"], "REVIEW")
        self.assertEqual(len(current["observations"]), 2)

    def test_page_reconciliation_uses_snapshot_status_instead_of_old_browser_order(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation())
        stale_order = store.get_order("ORDER")
        store.update_order_status("ORDER", "REFUNDED")
        with patch.object(store, "get_order", return_value=stale_order):
            app = sandbox_test_app(str(fixtures.APP)).run()
            app.selectbox(key="review_order_id").select("ORDER").run()
            app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        details = next(item for item in app.expander if item.label == "Reconciliation evidence")
        self.assertIn("Local status in this snapshot: REFUNDED", "\n".join(item.value for item in details.markdown))
        self.assertNotIn("Current local status: COMPLETED", "\n".join(item.value for item in details.markdown))
        self.assertTrue(any("Current local status: REFUNDED" in item.value for item in app.warning))
        self.assertTrue(any("not guaranteed to be the latest" in item.value for item in app.caption))


if __name__ == "__main__":
    unittest.main()
