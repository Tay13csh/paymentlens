"""Offline evidence display tests: no provider-time inference or payment actions."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app

import order_store
import paypal_auth


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class PaymentEvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.patch(patch.object(order_store, "DATABASE_PATH", Path(directory.name) / "orders.db"))
        self.patch(patch.object(st, "secrets", {}))
        self.network = self.patch(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Network forbidden")))
        self.payment = [self.patch(patch.object(paypal_auth, name, side_effect=AssertionError("Payment forbidden")))
                        for name in ("get_access_token", "create_order", "capture_order", "get_order_status")]

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def save(self, order_id="ORDER", status="CREATED"):
        order_store.save_order(order_id, "10.00")
        if status != "CREATED":
            order_store.update_order_status(order_id, status, "LOCAL-CAPTURE")

    def event(self, event_id, order_id="ORDER", event_type="PAYMENT.CAPTURE.COMPLETED"):
        resource = {"id": "EVENT-CAPTURE", "create_time": "2040-01-01T00:00:00Z"}
        if event_type == "CHECKOUT.ORDER.APPROVED":
            resource["id"] = order_id
        else:
            resource["supplementary_data"] = {"related_ids": {"order_id": order_id}}
        return {"id": event_id, "event_type": event_type, "resource": resource}

    def app(self):
        app = sandbox_test_app(str(APP_PATH)).run()
        if app.selectbox:
            app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        return app

    def steps(self, app):
        return next(item.value for item in app.markdown if item.value.startswith('<div class="pg-evidence-grid"'))

    def webhook_table(self, app):
        return next(item.value for item in app.markdown if item.value.startswith("| Event ID |"))

    def assert_no_requests(self):
        self.network.assert_not_called()
        for request in self.payment:
            request.assert_not_called()

    def test_query_filters_orders_sorts_by_local_time_and_does_not_write(self):
        self.save()
        self.save("OTHER")
        order_store.record_webhook_event(self.event("LATER"))
        order_store.record_webhook_event(self.event("EARLIER", event_type="CHECKOUT.ORDER.APPROVED"))
        order_store.record_webhook_event(self.event("OTHER-EVENT", "OTHER"))
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("UPDATE webhook_events SET received_at='2026-01-02 00:00:00' WHERE event_id='LATER'")
            connection.execute("UPDATE webhook_events SET received_at='2026-01-01 00:00:00' WHERE event_id='EARLIER'")
        original = order_store.DATABASE_PATH.read_bytes()
        with patch.object(order_store, "initialize_database", side_effect=AssertionError("Read must not migrate")):
            events = order_store.get_order_events("ORDER")
            self.assertEqual([event["event_id"] for event in events], ["EARLIER", "LATER"])
            self.assertEqual(order_store.get_order_events("' OR 1=1 --"), [])
        self.assertEqual(order_store.DATABASE_PATH.read_bytes(), original)
        self.assertNotIn("create_time", events[0])

    def test_missing_or_old_database_is_not_created_or_migrated(self):
        self.assertEqual(order_store.get_order_events("ORDER"), [])
        self.assertFalse(order_store.DATABASE_PATH.exists())
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("CREATE TABLE webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT, received_at TEXT)")
            connection.execute("INSERT INTO webhook_events VALUES ('OLD', 'PAYMENT.CAPTURE.COMPLETED', '2000-01-01')")
        original = order_store.DATABASE_PATH.read_bytes()
        self.assertEqual(order_store.get_order_events("ORDER"), [])
        self.assertEqual(order_store.DATABASE_PATH.read_bytes(), original)

    def test_completed_local_state_does_not_invent_independent_step_evidence(self):
        self.save(status="COMPLETED")
        app = self.app()
        steps = self.steps(app)
        self.assertIn("<h3>Order created</h3>", steps)
        self.assertIn("pg-evidence-neutral\">Local order record only", steps)
        self.assertIn("<h3>Buyer approved</h3>", steps)
        self.assertIn("pg-evidence-neutral\">No linked record", steps)
        self.assertIn("<h3>Payment completed</h3>", steps)
        self.assertEqual(steps.count("No linked record"), 2)
        self.assertNotIn("Not recorded", steps)
        details = next(item for item in app.expander if item.label == "Record details")
        self.assertFalse(details.proto.expanded)
        text = "\n".join(item.value for item in details.markdown)
        self.assertIn("Current local payment status: COMPLETED", text)
        self.assertIn("Capture ID: LOCAL-CAPTURE", text)
        for label in ("Order created at", "Buyer approved at", "Payment completed at"):
            self.assertIn(label + ": Not recorded", text)
        self.assert_no_requests()

    def test_ignored_event_is_evidence_without_claiming_payment_failure_or_occurrence_time(self):
        self.save(status="COMPLETED")
        self.assertFalse(order_store.record_webhook_event(self.event("COMPLETION")))
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("UPDATE orders SET updated_at='2026-01-01 01:00:00'")
            connection.execute("UPDATE webhook_events SET received_at='2026-01-01 02:00:00', processed_at='2026-01-01 03:00:00'")
        app = self.app()
        self.assertIn("Linked completion notification", self.steps(app))
        table = self.webhook_table(app)
        self.assertIn("Stored at (UTC)", table)
        self.assertIn("Local processed at (UTC)", table)
        self.assertIn("2026-01-01 02:00:00", table)
        self.assertIn("2026-01-01 03:00:00", table)
        self.assertIn("No state change", table)
        self.assertNotIn("2040-01-01", table)
        details = next(item for item in app.expander if item.label == "Record details")
        self.assertIn("Local record updated (UTC): 2026-01-01 01:00:00", "\n".join(item.value for item in details.markdown))
        self.assertTrue(any("not payment occurrence time" in item.value for item in app.caption))
        self.assertTrue(any("No state change is not a payment failure" in item.value for item in app.caption))
        details_text = "\n".join(item.value for item in details.caption)
        self.assertIn("signature verification", details_text)
        self.assertIn("LEGACY", details_text)
        self.assertIn("not payment occurrence time", details_text)
        main_explanation = next(item.value for item in app.caption if "Evidence comes from saved records" in item.value)
        self.assertNotIn("LEGACY", main_explanation)
        self.assertNotIn("signature", main_explanation)
        self.assert_no_requests()

    def test_duplicate_out_of_order_and_unlinked_legacy_records_are_not_misrepresented(self):
        self.save()
        complete = self.event("COMPLETE-FIRST")
        order_store.record_webhook_event(complete)
        order_store.record_webhook_event(self.event("APPROVED-LATER", event_type="CHECKOUT.ORDER.APPROVED"))
        self.assertFalse(order_store.record_webhook_event(complete))
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            connection.execute("INSERT INTO webhook_events (event_id,event_type) VALUES ('UNLINKED-OLD','CHECKOUT.ORDER.APPROVED')")
        app = self.app()
        self.assertIn("Linked approval notification", self.steps(app))
        table = self.webhook_table(app)
        self.assertLess(table.index("COMPLETE-FIRST"), table.index("APPROVED-LATER"))
        self.assertEqual(table.count("COMPLETE-FIRST"), 1)
        self.assertNotIn("UNLINKED-OLD", table)
        self.assertTrue(any("Unlinked LEGACY events cannot be assigned" in item.value for item in app.caption))
        self.assert_no_requests()

    def test_refunded_or_reversed_state_is_not_changed_by_viewing_historical_evidence(self):
        for status in ("REFUNDED", "REVERSED"):
            order_id = f"ORDER-{status}"
            self.save(order_id)
            order_store.record_webhook_event(self.event(f"EVENT-{status}", order_id))
            order_store.update_order_status(order_id, status)
            original = order_store.get_order(order_id)
            app = self.app()
            app.selectbox(key="review_order_id").select(order_id).run()
            app.button(key="open_payment_review").click().run()
            self.assertFalse(app.exception)
            self.assertIn("Linked completion notification", self.steps(app))
            self.assertEqual(order_store.get_order(order_id), original)
        self.assert_no_requests()

    def test_switching_orders_switches_evidence_without_switching_payment_target(self):
        self.save("WITH-EVIDENCE")
        self.save("NO-EVIDENCE", "COMPLETED")
        order_store.record_webhook_event(self.event("ONLY-A", "WITH-EVIDENCE", "CHECKOUT.ORDER.APPROVED"))
        app = self.app()
        app.session_state["paypal_order_id"] = "WITH-EVIDENCE"
        app.selectbox(key="review_order_id").select("WITH-EVIDENCE").run()
        app.button(key="open_payment_review").click().run()
        self.assertIn("Linked approval notification", self.steps(app))
        app.selectbox(key="review_order_id").select("NO-EVIDENCE").run()
        app.button(key="open_payment_review").click().run()
        self.assertIn("<h3>Buyer approved</h3>", self.steps(app))
        self.assertEqual(self.steps(app).count("No linked record"), 2)
        self.assertFalse(any(item.value.startswith("| Event ID |") for item in app.markdown))
        self.assertEqual(app.session_state["paypal_order_id"], "WITH-EVIDENCE")
        self.assert_no_requests()

    def test_empty_workbench_explains_how_to_view_evidence(self):
        app = self.app()
        self.assertFalse(any(item.value.startswith('<div class="pg-evidence-grid"') for item in app.markdown))
        self.assertTrue(any("No saved payments yet" in item.value for item in app.info))
        self.assert_no_requests()

    def test_three_step_cards_use_neutral_missing_evidence_not_failure(self):
        self.save()
        order_store.record_webhook_event(self.event("APPROVAL", event_type="CHECKOUT.ORDER.APPROVED"))
        app = self.app()
        cards = self.steps(app)
        self.assertEqual(cards.count('<section class="pg-evidence-card">'), 3)
        self.assertEqual(cards.count("pg-evidence-linked"), 1)
        self.assertEqual(cards.count("pg-evidence-neutral"), 2)
        self.assertIn("Linked approval notification", cards)
        self.assertIn("No linked record", cards)
        self.assertNotIn("failure", cards.lower())
        self.assertNotIn("Not recorded", cards)
        self.assert_no_requests()


if __name__ == "__main__":
    unittest.main()
