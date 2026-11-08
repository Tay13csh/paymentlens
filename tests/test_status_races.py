"""Offline regressions for webhook updates racing with delayed API responses."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import order_store
import paypal_auth


class StatusRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        database_patch = patch.object(
            order_store, "DATABASE_PATH", Path(self.temp_dir.name) / "orders.db"
        )
        database_patch.start()
        self.addCleanup(database_patch.stop)

    def deliver_terminal_event(self, order_id, terminal_status):
        event = {
            "id": f"EVENT-{order_id}",
            "event_type": f"PAYMENT.CAPTURE.{terminal_status}",
            "resource": {
                "id": "WEBHOOK-RESOURCE-ID",
                "supplementary_data": {"related_ids": {"order_id": order_id}},
            },
        }
        self.assertTrue(order_store.record_webhook_event(event))
        return order_store.get_order(order_id)

    def test_terminal_webhook_before_delayed_capture_or_query_response(self):
        for terminal_status in ("REFUNDED", "REVERSED"):
            for operation in ("capture", "query_completed", "query_approved"):
                with self.subTest(terminal_status=terminal_status, operation=operation):
                    order_id = f"ORDER-{terminal_status}-{operation}"
                    order_store.save_order(order_id, "10.00")
                    order_store.update_order_status(order_id, "APPROVED")
                    self.assertTrue(order_store.begin_capture(order_id))
                    if operation != "capture":
                        order_store.mark_capture_unknown(order_id)
                    expected = {}

                    def delayed_response(*args, **kwargs):
                        expected.update(self.deliver_terminal_event(order_id, terminal_status))
                        status = "APPROVED" if operation == "query_approved" else "COMPLETED"
                        return Mock(ok=True, json=Mock(return_value={
                            "status": status,
                            "purchase_units": [{"payments": {"captures": [{"id": "LATE-CAPTURE"}]}}],
                        }))

                    method = "post" if operation == "capture" else "get"
                    with patch.object(paypal_auth, "get_access_token", return_value="synthetic-token"), patch.object(
                        paypal_auth.requests, method, side_effect=delayed_response
                    ) as request:
                        api_call = paypal_auth.capture_order if operation == "capture" else paypal_auth.get_order_status
                        status, capture_id = api_call("synthetic-id", "synthetic-secret", order_id)
                        # Apply the same response writeback used by app.py.
                        if status == "APPROVED":
                            order_store.mark_capture_ready(order_id)
                        else:
                            order_store.update_order_status(order_id, status, capture_id)
                        request.assert_called_once()

                    self.assertEqual(order_store.get_order(order_id), expected)
                    self.assertFalse(order_store.begin_capture(order_id))

    def test_approved_query_still_releases_unknown_capture(self):
        order_id = "ORDER-RETRY"
        order_store.save_order(order_id, "10.00")
        order_store.update_order_status(order_id, "APPROVED")
        self.assertTrue(order_store.begin_capture(order_id))
        order_store.mark_capture_unknown(order_id)
        order_store.mark_capture_ready(order_id)
        order = order_store.get_order(order_id)
        self.assertEqual((order["status"], order["capture_state"]), ("APPROVED", "READY"))
        self.assertTrue(order_store.begin_capture(order_id))

    def test_normal_progression_and_repeated_completion_preserve_capture_id(self):
        order_id = "ORDER-PROGRESSION"
        order_store.save_order(order_id, "10.00")
        order_store.update_order_status(order_id, "APPROVED")
        order_store.update_order_status(order_id, "COMPLETED", "CAPTURE-ID")
        order_store.update_order_status(order_id, "COMPLETED")
        order = order_store.get_order(order_id)
        self.assertEqual((order["status"], order["capture_state"]), ("COMPLETED", "COMPLETED"))
        self.assertEqual(order["capture_id"], "CAPTURE-ID")
        self.deliver_terminal_event(order_id, "REFUNDED")
        self.assertEqual(order_store.get_order(order_id)["status"], "REFUNDED")
        event = {
            "id": "EVENT-REVERSED-AFTER-REFUND",
            "event_type": "PAYMENT.CAPTURE.REVERSED",
            "resource": {
                "id": "WEBHOOK-RESOURCE-ID",
                "supplementary_data": {"related_ids": {"order_id": order_id}},
            },
        }
        self.assertTrue(order_store.record_webhook_event(event))
        self.assertFalse(order_store.record_webhook_event(event))
        self.assertEqual(order_store.get_order(order_id)["status"], "REVERSED")


if __name__ == "__main__":
    unittest.main()
