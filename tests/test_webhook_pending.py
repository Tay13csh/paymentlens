"""Offline regressions for verified webhook storage and delayed order creation."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import order_store
import webhook_server


def capture_event(event_id="EVENT-1", order_id="ORDER-1", status="COMPLETED"):
    return {
        "id": event_id,
        "event_type": f"PAYMENT.CAPTURE.{status}",
        "resource": {
            "id": "CAPTURE-1",
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }


class PendingWebhookTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database_patch = patch.object(order_store, "DATABASE_PATH", Path(directory.name) / "orders.db")
        database_patch.start()
        self.addCleanup(database_patch.stop)

    def test_event_before_order_is_automatically_applied(self):
        self.assertFalse(order_store.record_webhook_event(capture_event()))
        self.assertEqual(self.event_row()["processing_state"], "PENDING")
        order_store.save_order("ORDER-1", "10.00")
        self.assertEqual(order_store.get_order("ORDER-1")["status"], "COMPLETED")
        self.assertEqual(self.event_row()["processing_state"], "APPLIED")

    def event_row(self, event_id="EVENT-1"):
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def fail_processing(self):
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("""
                CREATE TRIGGER fail_processing BEFORE UPDATE OF processing_state ON webhook_events
                WHEN NEW.processing_state = 'APPLIED'
                BEGIN SELECT RAISE(ABORT, 'synthetic processing failure'); END
            """)

    def remove_failure(self):
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("DROP TRIGGER fail_processing")

    def test_duplicates_before_and_after_replay_apply_once(self):
        event = capture_event()
        with patch.object(order_store, "_apply_status_update", wraps=order_store._apply_status_update) as apply:
            self.assertFalse(order_store.record_webhook_event(event))
            self.assertFalse(order_store.record_webhook_event(event))
            self.assertEqual(apply.call_count, 0)
            order_store.save_order("ORDER-1", "10.00")
            snapshot = self.event_row()
            order_store.save_order("ORDER-1", "10.00")
            self.assertFalse(order_store.record_webhook_event(event))
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(self.event_row(), snapshot)

    def test_existing_order_ingestion_failure_rolls_back_event_and_order(self):
        order_store.save_order("ORDER-1", "10.00")
        self.fail_processing()
        with self.assertRaises(sqlite3.IntegrityError):
            order_store.record_webhook_event(capture_event())
        self.assertIsNone(self.event_row())
        self.assertEqual(order_store.get_order("ORDER-1")["status"], "CREATED")
        self.remove_failure()
        self.assertTrue(order_store.record_webhook_event(capture_event()))

    def test_order_save_replay_failure_rolls_back_and_retains_pending(self):
        order_store.record_webhook_event(capture_event())
        self.fail_processing()
        with self.assertRaises(sqlite3.IntegrityError):
            order_store.save_order("ORDER-1", "10.00")
        self.assertIsNone(order_store.get_order("ORDER-1"))
        self.assertEqual(self.event_row()["processing_state"], "PENDING")
        self.remove_failure()
        order_store.save_order("ORDER-1", "10.00")
        self.assertEqual(order_store.get_order("ORDER-1")["status"], "COMPLETED")

    def test_creation_completion_replay_and_attempt_update_are_atomic(self):
        request_id = order_store.begin_order_creation("12.00")
        order_store.record_webhook_event(capture_event())
        self.fail_processing()
        with self.assertRaises(sqlite3.IntegrityError):
            order_store.complete_order_creation(request_id, "ORDER-1", "https://example.invalid/approve")
        self.assertIsNone(order_store.get_order("ORDER-1"))
        self.assertIsNone(order_store.get_order_creation_attempt(request_id)["order_id"])
        self.assertEqual(self.event_row()["processing_state"], "PENDING")
        self.remove_failure()
        order_store.complete_order_creation(request_id, "ORDER-1", "https://example.invalid/approve")
        self.assertEqual(order_store.get_order("ORDER-1")["status"], "COMPLETED")
        self.assertEqual(order_store.get_order_creation_attempt(request_id)["order_id"], "ORDER-1")

    def test_terminal_pending_events_reject_late_completed_and_approved(self):
        for terminal in ("REFUNDED", "REVERSED"):
            with self.subTest(terminal=terminal):
                order_id = f"ORDER-{terminal}"
                event_id = f"EVENT-{terminal}"
                order_store.record_webhook_event(capture_event(event_id, order_id, terminal))
                order_store.record_webhook_event(capture_event(f"{event_id}-LATE", order_id))
                order_store.record_webhook_event({
                    "id": f"{event_id}-APPROVED", "event_type": "CHECKOUT.ORDER.APPROVED",
                    "resource": {"id": order_id},
                })
                order_store.save_order(order_id, "10.00")
                order_store.update_order_status(order_id, "COMPLETED", "LATE-CAPTURE")
                order_store.mark_capture_ready(order_id)
                self.assertEqual(order_store.get_order(order_id)["status"], terminal)
                self.assertEqual(self.event_row(event_id)["processing_state"], "APPLIED")
                self.assertEqual(self.event_row(f"{event_id}-LATE")["processing_state"], "IGNORED")
                self.assertEqual(self.event_row(f"{event_id}-APPROVED")["processing_state"], "IGNORED")

    def test_old_schema_migrates_without_changing_existing_records(self):
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.executescript("""
                CREATE TABLE orders (order_id TEXT PRIMARY KEY, amount TEXT NOT NULL,
                    currency TEXT NOT NULL, status TEXT NOT NULL, capture_id TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO orders VALUES ('OLD-ORDER', '7.00', 'CAD', 'COMPLETED', 'OLD-CAPTURE', '2000-01-01');
                CREATE TABLE webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO webhook_events VALUES ('EVENT-1', 'PAYMENT.CAPTURE.COMPLETED', '2000-01-01');
            """)
        order_store.initialize_database()
        order_store.initialize_database()
        row = self.event_row()
        self.assertEqual(row["received_at"], "2000-01-01")
        self.assertEqual(row["processing_state"], "LEGACY")
        self.assertIsNone(row["order_id"])
        self.assertIsNone(row["processed_at"])
        self.assertFalse(order_store.record_webhook_event(capture_event()))
        self.assertEqual(self.event_row(), row)
        order = order_store.get_order("OLD-ORDER")
        self.assertEqual((order["amount"], order["status"], order["capture_id"], order["updated_at"]),
                         ("7.00", "COMPLETED", "OLD-CAPTURE", "2000-01-01"))
        order_store.record_webhook_event(capture_event("NEW-EVENT", "NEW-ORDER"))
        order_store.initialize_database()
        self.assertEqual(self.event_row("NEW-EVENT")["processing_state"], "PENDING")
        order_store.save_order("NEW-ORDER", "10.00")
        self.assertEqual(order_store.get_order("NEW-ORDER")["status"], "COMPLETED")

    def test_pending_capacity_rejects_without_eviction_and_can_recover(self):
        with patch.object(order_store, "MAX_PENDING_WEBHOOK_EVENTS", 1):
            order_store.record_webhook_event(capture_event())
            original = self.event_row()
            self.assertFalse(order_store.record_webhook_event(capture_event()))
            with self.assertRaises(order_store.WebhookStorageFullError):
                order_store.record_webhook_event(capture_event("EVENT-2", "ORDER-2"))
            self.assertEqual(self.event_row(), original)
            self.assertIsNone(self.event_row("EVENT-2"))
            order_store.save_order("EXISTING-ORDER", "10.00")
            self.assertTrue(order_store.record_webhook_event(capture_event("EVENT-3", "EXISTING-ORDER")))
            order_store.save_order("ORDER-1", "10.00")
            self.assertFalse(order_store.record_webhook_event(capture_event("EVENT-2", "ORDER-2")))
            self.assertEqual(self.event_row("EVENT-2")["processing_state"], "PENDING")

    def test_total_capacity_keeps_deduplication_and_existing_pending_replay(self):
        with patch.object(order_store, "MAX_STORED_WEBHOOK_EVENTS", 1):
            order_store.record_webhook_event(capture_event())
            with self.assertRaises(order_store.WebhookStorageFullError):
                order_store.record_webhook_event(capture_event("EVENT-2", "ORDER-2"))
            self.assertFalse(order_store.record_webhook_event(capture_event()))
            order_store.save_order("ORDER-1", "10.00")
            self.assertEqual(self.event_row()["processing_state"], "APPLIED")
            self.assertFalse(order_store.record_webhook_event(capture_event()))

    def test_only_bounded_allowlisted_fields_are_saved(self):
        event = capture_event()
        event["resource"]["payer"] = {"email_address": "PRIVATE-MARKER"}
        event["extra"] = "PRIVATE-MARKER"
        order_store.record_webhook_event(event)
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            self.assertNotIn("PRIVATE-MARKER", "\n".join(connection.iterdump()))
        for field in ("id", "event_type"):
            invalid = capture_event()
            invalid[field] = "X" * (order_store.MAX_WEBHOOK_FIELD_LENGTH + 1)
            with self.assertRaises(order_store.InvalidWebhookEventError):
                order_store.record_webhook_event(invalid)
        invalid = capture_event("EVENT-INVALID")
        invalid["resource"]["supplementary_data"] = {}
        with self.assertRaises(order_store.InvalidWebhookEventError):
            order_store.record_webhook_event(invalid)
        self.assertIsNone(self.event_row("EVENT-INVALID"))

    def test_receiver_verifies_before_storage_and_returns_503_when_full(self):
        class Request:
            headers = {name: "synthetic" for name in (
                "paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id",
                "paypal-transmission-sig", "paypal-transmission-time",
            )}

            async def body(self):
                return json.dumps(capture_event()).encode()

        with patch.object(webhook_server, "load_paypal_settings", return_value={
            "client_id": "synthetic", "client_secret": "synthetic", "webhook_id": "synthetic",
        }), patch.object(webhook_server, "verify_webhook_signature", return_value=False) as verify:
            with patch.object(webhook_server, "record_webhook_event") as store:
                with self.assertRaises(HTTPException) as invalid:
                    asyncio.run(webhook_server.receive_paypal_webhook(Request()))
                self.assertEqual(invalid.exception.status_code, 400)
                store.assert_not_called()
            verify.return_value = True
            with patch.object(order_store, "MAX_PENDING_WEBHOOK_EVENTS", 0):
                with self.assertRaises(HTTPException) as full:
                    asyncio.run(webhook_server.receive_paypal_webhook(Request()))
                self.assertEqual(full.exception.status_code, 503)
                self.assertIsNone(self.event_row())
            self.assertEqual(asyncio.run(webhook_server.receive_paypal_webhook(Request())),
                             {"received": True, "processed": False})


if __name__ == "__main__":
    unittest.main()
