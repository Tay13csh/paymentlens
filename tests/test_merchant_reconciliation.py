"""Isolated sales-to-Capture regressions. Never use real secrets or providers."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app
from fastapi import HTTPException

import order_store as store
import paypal_auth
import webhook_server
from payment_evidence import PaymentObservation, money


APP = Path(__file__).resolve().parents[1] / "app.py"


class MerchantReconciliationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / "test.db"
        self.start(patch.object(store, "DATABASE_PATH", self.db))
        self.start(patch.object(st, "secrets", {}))
        self.network = self.start(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Network forbidden")))

    def start(self, patcher):
        obj = patcher.start()
        self.addCleanup(patcher.stop)
        return obj

    def linked(self, amount="10.00", order_id="ORDER"):
        sale = store.create_merchant_sale("Test mug", amount)
        attempt = store.begin_sale_creation(sale)
        store.complete_order_creation(attempt, order_id, "https://example.invalid/approve")
        return sale, attempt

    def capture(self, amount="10.00", capture_id="CAPTURE", final=True, currency="CAD"):
        return {"id": capture_id, "status": "COMPLETED", "amount": {"value": amount, "currency_code": currency}, "final_capture": final, "create_time": "2026-11-10T12:00:00Z"}

    def observation(self, capture=None, source="CAPTURE_RESPONSE", order_id="ORDER", order_amount="10.00", order_currency="CAD"):
        return PaymentObservation({"id": order_id, "status": "COMPLETED", "purchase_units": [{
            "amount": {"value": order_amount, "currency_code": order_currency},
            "payments": {"captures": [capture or self.capture()]},
        }]}, order_id, source)

    def event(self, capture=None, order_id="ORDER", event_id="EVENT"):
        resource = dict(capture or self.capture())
        resource["supplementary_data"] = {"related_ids": {"order_id": order_id}}
        return {"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": resource}

    def code(self, order_id="ORDER"):
        return store.get_sale_reconciliation(order_id)["result"]["code"]

    def test_incomplete_money_observations_cannot_be_joined_into_match(self):
        self.linked()
        first = self.capture()
        first["amount"].pop("currency_code")
        second = self.capture("NaN")
        store.record_payment_observation("ORDER", self.observation(first))
        store.record_payment_observation("ORDER", self.observation(second, source="ORDER_QUERY"))
        self.assertNotEqual(self.code(), "MATCH")
        record = store.get_sale_reconciliation("ORDER")["captures"][0]
        self.assertIsNone(record["amount"])
        self.assertIsNone(record["currency"])

    def test_final_capture_below_provider_order_total_cannot_match(self):
        self.linked()
        payload = {"id": "ORDER", "status": "COMPLETED", "purchase_units": [{
            "amount": {"value": "20.00", "currency_code": "CAD"},
            "payments": {"captures": [self.capture("10.00")]},
        }]}
        store.record_payment_observation("ORDER", PaymentObservation(payload, "ORDER", "ORDER_QUERY"))
        self.assertNotEqual(self.code(), "MATCH")

    def test_webhook_needs_a_complete_query_to_prove_full_capture(self):
        self.linked()
        store.record_webhook_event(self.event())
        self.assertEqual(self.code(), "INCOMPLETE")
        missing_total = PaymentObservation({"id": "ORDER", "status": "COMPLETED", "purchase_units": [
            {"payments": {"captures": [self.capture()]}}
        ]}, "ORDER", "ORDER_QUERY")
        store.record_payment_observation("ORDER", missing_total)
        self.assertEqual(self.code(), "INCOMPLETE")
        for amount, currency in (("10.00", None), ("NaN", "CAD")):
            store.record_payment_observation("ORDER", self.observation(
                source="ORDER_QUERY", order_amount=amount, order_currency=currency))
            self.assertEqual(self.code(), "INCOMPLETE")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(self.code(), "MATCH")
        self.assertEqual(evidence["captures"][0]["provider_order_amount"], "10.00")
        self.assertEqual(evidence["captures"][0]["full_capture_verified"], 1)

    def test_invalid_pair_can_only_recover_from_a_whole_valid_observation(self):
        self.linked()
        first = self.capture()
        first["amount"].pop("currency_code")
        store.record_payment_observation("ORDER", self.observation(first))
        store.record_payment_observation("ORDER", self.observation(self.capture("NaN"), source="ORDER_QUERY"))
        self.assertNotEqual(self.code(), "MATCH")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "MATCH")
        for item in store.get_sale_reconciliation("ORDER")["observations"]:
            self.assertEqual(item["amount"] is None, item["currency"] is None)

    def test_provider_total_currency_must_equal_capture_currency(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation(order_currency="USD"))
        self.assertNotEqual(self.code(), "MATCH")
        self.assertTrue(store.get_sale_reconciliation("ORDER")["issues"])

    def test_conflict_retains_both_money_sources_and_times_without_duplicates(self):
        self.linked()
        first = self.observation()
        second_capture = self.capture("11.00")
        second_capture["create_time"] = "2026-11-10T12:01:00Z"
        second = self.observation(second_capture, source="ORDER_QUERY", order_amount="11.00")
        store.record_payment_observation("ORDER", first)
        store.record_payment_observation("ORDER", second)
        store.record_payment_observation("ORDER", second)
        store.initialize_database()
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(evidence["result"]["code"], "REVIEW")
        snapshots = evidence["observations"]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual({(item["amount"], item["currency"], item["source"], item["occurred_at"]) for item in snapshots}, {
            ("10.00", "CAD", "CAPTURE_RESPONSE", "2026-11-10T12:00:00Z"),
            ("11.00", "CAD", "ORDER_QUERY", "2026-11-10T12:01:00Z"),
        })
        self.assertTrue(all(item["recorded_at"] for item in snapshots))
        app = sandbox_test_app(str(APP)).run()
        app.selectbox(key="review_order_id").select("ORDER").run()
        app.button(key="open_payment_review").click().run()
        details = next(item for item in app.expander if item.label == "Reconciliation evidence")
        self.assertTrue(details.table)
        self.assertFalse(app.exception)

    def capture_only_refund(self, event_id="EARLY-REFUND", capture_id="CAPTURE"):
        return {"id": event_id, "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {
            "id": "REFUND-RESOURCE", "amount": {"value": "1.00", "currency_code": "CAD"},
            "supplementary_data": {"related_ids": {"capture_id": capture_id}},
        }}

    def test_capture_only_refund_persists_until_query_binds_capture(self):
        event = self.capture_only_refund()
        self.assertFalse(store.record_webhook_event(event))
        self.assertFalse(store.record_webhook_event(event))
        store.initialize_database()
        with sqlite3.connect(self.db) as connection:
            rows = connection.execute("SELECT order_id, capture_id, processing_state FROM webhook_events").fetchall()
            self.assertEqual(rows, [(None, "CAPTURE", "PENDING")])
        self.linked()
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(evidence["order"]["status"], "REFUNDED")
        self.assertEqual(evidence["captures"][0]["amount"], "10.00")
        self.assertEqual(self.code(), "TERMINAL")
        self.assertFalse(store.record_webhook_event(event))
        store.record_payment_observation("ORDER", self.observation())
        self.assertEqual(store.get_order("ORDER")["status"], "REFUNDED")
        self.assertFalse(store.begin_capture("ORDER"))

    def test_capture_only_refund_replays_after_completion_webhook_or_legacy_id(self):
        for order_id, operation in (("WEBHOOK", "webhook"), ("LEGACY", "legacy")):
            with self.subTest(operation=operation):
                reference = "CAPTURE-" + order_id
                event = self.capture_only_refund("REFUND-" + order_id, reference)
                store.record_webhook_event(event)
                self.linked(order_id=order_id)
                if operation == "webhook":
                    store.record_webhook_event(self.event(self.capture(capture_id=reference), order_id, "COMPLETE-" + order_id))
                else:
                    store.update_order_status(order_id, "COMPLETED", reference)
                self.assertEqual(store.get_order(order_id)["status"], "REFUNDED")

    def test_capture_only_refund_and_completion_both_precede_local_order(self):
        store.record_webhook_event(self.capture_only_refund())
        store.record_webhook_event(self.event())
        store.initialize_database()
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM webhook_events WHERE processing_state='PENDING'").fetchone()[0], 2)
        self.linked()
        self.assertEqual(store.get_order("ORDER")["status"], "REFUNDED")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "TERMINAL")
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM webhook_events WHERE processing_state='PENDING'").fetchone()[0], 0)

    def test_pending_capture_refund_replay_rolls_back_with_response_failure(self):
        self.linked()
        store.record_webhook_event(self.capture_only_refund())
        original = store._apply_status_update
        def fail_on_refund(connection, order_id, status, *args, **kwargs):
            if status == "REFUNDED":
                raise sqlite3.OperationalError("simulated refund replay failure")
            return original(connection, order_id, status, *args, **kwargs)
        with patch.object(store, "_apply_status_update", side_effect=fail_on_refund):
            with self.assertRaises(sqlite3.OperationalError):
                store.record_payment_observation("ORDER", self.observation())
        self.assertEqual(store.get_order("ORDER")["status"], "CREATED")
        self.assertEqual(store.get_sale_reconciliation("ORDER")["observations"], [])
        self.assertEqual(store.get_sale_reconciliation("ORDER")["captures"], [])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT order_id, processing_state FROM webhook_events").fetchone(), (None, "PENDING"))
        store.record_payment_observation("ORDER", self.observation())
        self.assertEqual(store.get_order("ORDER")["status"], "REFUNDED")

    def test_pending_capture_refunds_enforce_capacity_without_dropping_existing(self):
        first = self.capture_only_refund()
        with patch.object(store, "MAX_PENDING_WEBHOOK_EVENTS", 1):
            store.record_webhook_event(first)
            store.record_webhook_event(first)
            with self.assertRaises(store.WebhookStorageFullError):
                store.record_webhook_event(self.capture_only_refund("SECOND", "OTHER-CAPTURE"))
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT event_id, processing_state FROM webhook_events").fetchall(), [("EARLY-REFUND", "PENDING")])

    def test_observation_capacity_failure_rolls_back_instead_of_losing_conflict(self):
        self.linked()
        first = self.observation()
        store.record_payment_observation("ORDER", first)
        with patch.object(store, "MAX_OBSERVATIONS_PER_CAPTURE", 1):
            store.record_payment_observation("ORDER", first)
            with self.assertRaises(store.WebhookStorageFullError):
                store.record_payment_observation("ORDER", self.observation(self.capture("11.00"), source="ORDER_QUERY", order_amount="11.00"))
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(len(evidence["observations"]), 1)
        self.assertEqual(evidence["captures"][0]["conflict"], 0)
        self.assertEqual(evidence["captures"][0]["amount"], "10.00")

    def test_old_evidence_schema_requires_fresh_pair_and_full_proof(self):
        self.linked()
        with sqlite3.connect(self.db) as connection:
            connection.execute("DROP TABLE capture_evidence")
            connection.execute("""CREATE TABLE capture_evidence (
                capture_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, amount TEXT, currency TEXT,
                status TEXT, final_capture INTEGER, occurred_at TEXT, source TEXT NOT NULL,
                conflict INTEGER NOT NULL DEFAULT 0, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            connection.execute("INSERT INTO capture_evidence(capture_id,order_id,amount,currency,status,final_capture,source) VALUES('CAPTURE','ORDER','10.00','CAD','COMPLETED',1,'CAPTURE_RESPONSE')")
        store.update_order_status("ORDER", "COMPLETED", "CAPTURE")
        store.initialize_database()
        self.assertEqual(self.code(), "INCOMPLETE")
        self.assertEqual(store.get_sale_reconciliation("ORDER")["captures"][0]["full_capture_verified"], 0)
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "MATCH")

    def test_capture_only_refund_verification_and_capacity_response(self):
        event = self.capture_only_refund()
        class Request:
            headers = {name: "synthetic" for name in ("paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig", "paypal-transmission-time")}
            async def body(inner):
                return json.dumps(event).encode()
        with patch.object(webhook_server, "load_paypal_settings", return_value={"client_id": "fake", "client_secret": "fake", "webhook_id": "fake"}), patch.object(webhook_server, "verify_webhook_signature", return_value=False) as verify:
            with self.assertRaises(HTTPException) as rejected:
                asyncio.run(webhook_server.receive_paypal_webhook(Request()))
            self.assertEqual(rejected.exception.status_code, 400)
            self.linked()
            with sqlite3.connect(self.db) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM webhook_events").fetchone()[0], 0)
            verify.return_value = True
            with patch.object(store, "MAX_PENDING_WEBHOOK_EVENTS", 0):
                with self.assertRaises(HTTPException) as full:
                    asyncio.run(webhook_server.receive_paypal_webhook(Request()))
                self.assertEqual(full.exception.status_code, 503)
            self.assertEqual(asyncio.run(webhook_server.receive_paypal_webhook(Request())), {"received": True, "processed": False})
            store.record_payment_observation("ORDER", self.observation())
            self.assertEqual(store.get_order("ORDER")["status"], "REFUNDED")

    def test_ambiguous_capture_binding_does_not_guess_refund_order(self):
        self.linked()
        self.linked(order_id="OTHER")
        store.record_payment_observation("ORDER", self.observation())
        store.record_payment_observation("OTHER", self.observation(order_id="OTHER"))
        self.assertFalse(store.record_webhook_event(self.capture_only_refund()))
        self.assertEqual(store.get_order("ORDER")["status"], "COMPLETED")
        self.assertEqual(store.get_order("OTHER")["status"], "COMPLETED")
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT order_id, processing_state FROM webhook_events WHERE event_id='EARLY-REFUND'").fetchone(), (None, "PENDING"))

    def test_capture_only_reversal_and_refund_survive_late_completed_query(self):
        store.record_webhook_event(self.capture_only_refund())
        store.record_webhook_event({"id": "EARLY-REVERSAL", "event_type": "PAYMENT.CAPTURE.REVERSED", "resource": {"id": "CAPTURE"}})
        self.linked()
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        store.record_payment_observation("ORDER", self.observation())
        self.assertEqual(store.get_order("ORDER")["status"], "REVERSED")
        self.assertEqual(self.code(), "TERMINAL")
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM webhook_events WHERE processing_state='PENDING'").fetchone()[0], 0)

    def test_exact_money_and_reject_invalid_terms(self):
        self.assertEqual(money("0.10"), "0.10")
        for value in ("0", "-1", "NaN", "Infinity", "1.001", "1e2", "1000000000", True, 0.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                store.create_merchant_sale("Test", value)
        with self.assertRaises(ValueError):
            store.create_merchant_sale("", "10")

    def test_terms_immutable_and_retry_identity_survives_refresh(self):
        sale, attempt = self.linked()
        self.assertEqual(store.begin_sale_creation(sale), attempt)
        store.initialize_database()
        self.assertEqual(store.begin_sale_creation(sale), attempt)
        with sqlite3.connect(self.db) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE merchant_sales_orders SET amount='12.00' WHERE sale_id=?", (sale,))
        self.assertEqual(store.get_merchant_sales()[0]["amount"], "10.00")
        self.assertTrue(store.get_merchant_sales()[0]["locked_at"])

    def test_unconfirmed_creation_reuses_key_and_rejects_rebinding(self):
        sale = store.create_merchant_sale("Test", "12.00")
        first = store.begin_sale_creation(sale)
        self.assertEqual(store.begin_sale_creation(sale), first)
        store.complete_order_creation(first, "ORDER", "https://example.invalid")
        with self.assertRaises(ValueError):
            store.complete_order_creation(first, "OTHER", "https://example.invalid")
        self.assertIsNone(store.get_order("OTHER"))
        other_sale = store.create_merchant_sale("Other", "12.00")
        other_attempt = store.begin_sale_creation(other_sale)
        with self.assertRaises(ValueError):
            store.complete_order_creation(other_attempt, "ORDER", "https://example.invalid")

    def test_matching_capture_three_sources_are_idempotent(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation())
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertFalse(store.record_webhook_event(self.event()))
        self.assertFalse(store.record_webhook_event(self.event()))
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(evidence["result"]["code"], "MATCH")
        self.assertEqual(len(evidence["captures"]), 1)
        self.assertEqual(evidence["captures"][0]["amount"], "10.00")
        self.network.assert_not_called()

    def test_pending_event_before_local_order_retains_capture_fields(self):
        sale = store.create_merchant_sale("Test", "10.00")
        attempt = store.begin_sale_creation(sale)
        self.assertFalse(store.record_webhook_event(self.event()))
        store.complete_order_creation(attempt, "ORDER", "https://example.invalid")
        self.assertEqual(self.code(), "INCOMPLETE")
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT processing_state FROM webhook_events").fetchone()[0], "APPLIED")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "MATCH")

    def test_refund_before_late_evidence_preserves_terminal_state(self):
        self.linked()
        refund = {"id": "REFUND-EVENT", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {
            "id": "REFUND-ID", "amount": {"value": "2.00", "currency_code": "CAD"},
            "supplementary_data": {"related_ids": {"order_id": "ORDER", "capture_id": "CAPTURE"}}}}
        store.record_webhook_event(refund)
        store.record_webhook_event(self.event())
        store.record_payment_observation("ORDER", self.observation())
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(evidence["order"]["status"], "REFUNDED")
        self.assertEqual(evidence["captures"][0]["amount"], "10.00")
        self.assertEqual(evidence["result"]["code"], "TERMINAL")
        self.assertFalse(store.begin_capture("ORDER"))

    def test_conflicting_amount_is_not_overwritten(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation())
        store.record_webhook_event(self.event(self.capture("11.00")))
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(evidence["captures"][0]["amount"], "10.00")
        self.assertEqual(evidence["captures"][0]["conflict"], 1)
        self.assertEqual(self.code(), "REVIEW")

    def test_missing_fields_can_be_filled_by_query_without_inventing_money(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation({"id": "CAPTURE", "status": "COMPLETED"}))
        self.assertEqual(self.code(), "INCOMPLETE")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "MATCH")
        self.assertEqual(store.get_sale_reconciliation("ORDER")["captures"][0]["source"], "ORDER_QUERY")

    def test_unknown_partial_multiple_units_and_captures_cannot_match(self):
        for final in (None, False):
            with self.subTest(final=final):
                sale, attempt = self.linked(order_id="ORDER-" + str(final))
                observation = self.observation(self.capture(final=final, capture_id="C-" + str(final)), order_id="ORDER-" + str(final))
                store.record_payment_observation("ORDER-" + str(final), observation)
                self.assertEqual(self.code("ORDER-" + str(final)), "INCOMPLETE")
        self.linked()
        payload = {"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [self.capture(), self.capture(capture_id="SECOND")]}}]}
        observation = PaymentObservation(payload, "ORDER", "ORDER_QUERY")
        self.assertIsNone(observation[1])
        store.record_payment_observation("ORDER", observation)
        self.assertEqual(len(store.get_sale_reconciliation("ORDER")["captures"]), 2)
        self.assertEqual(self.code(), "REVIEW")
        self.linked(order_id="MULTI-UNIT")
        payload["purchase_units"] = [{"payments": {"captures": [self.capture(capture_id="UNIT-C")]}}, {}]
        store.record_payment_observation("MULTI-UNIT", PaymentObservation(payload, "MULTI-UNIT", "ORDER_QUERY"))
        self.assertEqual(self.code("MULTI-UNIT"), "REVIEW")

    def test_currency_conflict_and_exact_difference(self):
        self.linked("0.30")
        store.record_payment_observation("ORDER", self.observation(self.capture("0.10"), order_amount="0.10"))
        result = store.get_sale_reconciliation("ORDER")["result"]
        self.assertEqual(result["difference"], "-0.20")
        self.assertEqual(result["code"], "DIFFERENCE")
        self.linked(order_id="USD")
        store.record_payment_observation("USD", self.observation(self.capture(currency="USD", capture_id="USD-C"), order_id="USD", order_currency="USD"))
        self.assertEqual(self.code("USD"), "CURRENCY")
        self.assertNotIn("difference", store.get_sale_reconciliation("USD")["result"])

    def test_capture_id_cannot_move_between_orders(self):
        self.linked()
        self.linked(order_id="OTHER")
        store.record_payment_observation("ORDER", self.observation())
        store.record_payment_observation("OTHER", self.observation(order_id="OTHER"))
        self.assertEqual(self.code(), "REVIEW")
        self.assertEqual(self.code("OTHER"), "REVIEW")

    def test_pending_event_rolls_back_with_evidence_failure(self):
        sale = store.create_merchant_sale("Test", "10.00")
        attempt = store.begin_sale_creation(sale)
        store.record_webhook_event(self.event())
        with patch.object(store, "_store_capture_evidence", side_effect=sqlite3.OperationalError("test failure")):
            with self.assertRaises(sqlite3.OperationalError):
                store.complete_order_creation(attempt, "ORDER", "https://example.invalid")
        self.assertIsNone(store.get_order("ORDER"))
        self.assertIsNone(store.get_merchant_sales()[0]["paypal_order_id"])
        self.assertIsNone(store.get_order_creation_attempt(attempt)["order_id"])
        store.complete_order_creation(attempt, "ORDER", "https://example.invalid")
        self.assertEqual(self.code(), "INCOMPLETE")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "MATCH")

    def test_old_database_migration_does_not_fabricate_capture_or_sale(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE orders(order_id TEXT PRIMARY KEY, amount TEXT, currency TEXT, status TEXT, capture_id TEXT, updated_at TEXT)")
            connection.execute("INSERT INTO orders VALUES('OLD','10.00','CAD','COMPLETED','OLD-C',NULL)")
            connection.execute("CREATE TABLE webhook_events(event_id TEXT PRIMARY KEY,event_type TEXT,received_at TEXT)")
            connection.execute("INSERT INTO webhook_events VALUES('OLD-E','PAYMENT.CAPTURE.COMPLETED',NULL)")
        store.initialize_database()
        store.initialize_database()
        result = store.get_sale_reconciliation("OLD")
        self.assertEqual(result["result"]["code"], "HISTORY")
        self.assertEqual(result["captures"], [])
        self.assertEqual(store.get_merchant_sales(), [])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT processing_state FROM webhook_events").fetchone()[0], "LEGACY")

    def test_api_capture_and_query_return_evidence_without_personal_fields(self):
        payload = {"id": "ORDER", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [self.capture()]}}], "payer": {"email_address": "not-stored@example.invalid"}}
        for method, operation in (("post", paypal_auth.capture_order), ("get", paypal_auth.get_order_status)):
            with patch.object(paypal_auth, "get_access_token", return_value="synthetic"), patch.object(paypal_auth.requests, method, return_value=Mock(ok=True, json=Mock(return_value=payload))) as call:
                observation = operation("fake", "fake", "ORDER")
                self.assertEqual(tuple(observation), ("COMPLETED", "CAPTURE"))
                self.assertEqual(observation.captures[0]["amount"], "10.00")
                self.assertNotIn("email", repr(observation.captures))
                if method == "post":
                    self.assertEqual(call.call_args.kwargs["headers"]["Prefer"], "return=representation")

    def test_wrong_provider_order_identity_is_rejected(self):
        for method, operation in (("post", paypal_auth.capture_order), ("get", paypal_auth.get_order_status)):
            with patch.object(paypal_auth, "get_access_token", return_value="synthetic"), patch.object(paypal_auth.requests, method, return_value=Mock(ok=True, json=Mock(return_value={"id": "OTHER", "status": "COMPLETED"}))):
                with self.assertRaises(paypal_auth.PayPalOrderError):
                    operation("fake", "fake", "ORDER")

    def test_unverified_delivery_cannot_store_evidence(self):
        self.linked()
        class Request:
            headers = {name: "synthetic" for name in ("paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig", "paypal-transmission-time")}
            async def body(inner):
                return json.dumps(self.event()).encode()
        with patch.object(webhook_server, "load_paypal_settings", return_value={"client_id": "fake", "client_secret": "fake", "webhook_id": "fake"}), patch.object(webhook_server, "verify_webhook_signature", return_value=False):
            with self.assertRaises(HTTPException):
                asyncio.run(webhook_server.receive_paypal_webhook(Request()))
        self.assertEqual(store.get_sale_reconciliation("ORDER")["captures"], [])

    def test_capacity_failure_does_not_acknowledge_or_persist_new_evidence(self):
        self.linked()
        with patch.object(store, "MAX_STORED_WEBHOOK_EVENTS", 0):
            with self.assertRaises(store.WebhookStorageFullError):
                store.record_webhook_event(self.event())
        self.assertEqual(store.get_sale_reconciliation("ORDER")["captures"], [])

    def test_page_saves_merchant_expectation_without_external_requests(self):
        app = sandbox_test_app(str(APP)).run()
        app.radio(key="main_navigation").set_value("Test sales orders").run()
        next(item for item in app.text_input if item.label == "Test order description").set_value("Test mug")
        next(item for item in app.text_input if item.label == "Merchant expected amount (CAD)").set_value("12.00")
        next(item for item in app.button if item.label == "Save test sales order").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(store.get_merchant_sales()[0]["amount"], "12.00")
        self.assertEqual(store.get_orders(), [])
        self.network.assert_not_called()

    def test_page_merchant_timeout_resume_capture_and_reconciliation(self):
        sale = store.create_merchant_sale("Test mug", "12.00")
        observation = self.observation(self.capture("12.00"), order_amount="12.00")
        settings = {"paypal": {"client_id": "synthetic-id", "client_secret": "synthetic-secret"}}
        with patch.object(st, "secrets", settings), patch.object(paypal_auth, "create_order", side_effect=[
            paypal_auth.PayPalOrderError("simulated timeout"), ("ORDER", "https://example.invalid/approve")
        ]) as create, patch.object(paypal_auth, "capture_order", return_value=observation) as capture:
            app = sandbox_test_app(str(APP)).run()
            app.radio(key="main_navigation").set_value("Test sales orders").run()
            app.button(key="create_merchant_payment").click().run()
            self.assertFalse(app.exception)
            first_attempt = store.begin_sale_creation(sale)
            app = sandbox_test_app(str(APP)).run()
            app.radio(key="main_navigation").set_value("Test sales orders").run()
            app.button(key="create_merchant_payment").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(create.call_args_list[0].kwargs["request_id"], create.call_args_list[1].kwargs["request_id"])
            self.assertEqual(create.call_args_list[1].args[2], "12.00")
            self.assertEqual(store.begin_sale_creation(sale), first_attempt)
            app.button(key="activate_merchant_payment").click().run()
            next(button for button in app.button if button.label == "Capture Approved Order").click().run()
            self.assertFalse(app.exception)
            capture.assert_called_once()
            app.radio(key="main_navigation").set_value("Review payments").run()
            app.selectbox(key="review_order_id").select("ORDER").run()
            app.button(key="open_payment_review").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Merchant amount and currency match" in item.value for item in app.success))
            self.assertEqual(self.code(), "MATCH")
            # Browsing, changing tabs and restarting must not create/pay again.
            app.run()
            self.assertEqual(create.call_count, 2)
            self.assertEqual(capture.call_count, 1)
        self.network.assert_not_called()

    def test_api_evidence_storage_and_status_are_atomic(self):
        self.linked()
        with patch.object(store, "_apply_status_update", side_effect=sqlite3.OperationalError("write failed")):
            with self.assertRaises(sqlite3.OperationalError):
                store.record_payment_observation("ORDER", self.observation())
        evidence = store.get_sale_reconciliation("ORDER")
        self.assertEqual(evidence["order"]["status"], "CREATED")
        self.assertEqual(evidence["captures"], [])

    def test_reversed_state_and_malformed_money_never_match(self):
        self.linked()
        for amount in ("NaN", "-10", "10.001", 10.0):
            store.record_payment_observation("ORDER", self.observation(self.capture(amount=amount)))
            self.assertNotEqual(self.code(), "MATCH")
        store.record_payment_observation("ORDER", self.observation())
        store.update_order_status("ORDER", "REVERSED")
        store.record_payment_observation("ORDER", self.observation(source="ORDER_QUERY"))
        self.assertEqual(self.code(), "TERMINAL")
        self.assertEqual(store.get_order("ORDER")["status"], "REVERSED")

    def test_concurrent_sale_creation_reserves_only_one_attempt(self):
        sale = store.create_merchant_sale("Test", "10.00")
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(store.begin_sale_creation, [sale, sale]))
        self.assertEqual(attempts[0], attempts[1])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM order_creation_attempts WHERE sale_id=?", (sale,)).fetchone()[0], 1)

    def test_refund_capture_link_resolves_without_storing_refund_as_capture(self):
        self.linked()
        store.record_payment_observation("ORDER", self.observation())
        event = {"id": "REFUND", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {
            "id": "REFUND-RESOURCE", "amount": {"value": "1.00", "currency_code": "CAD"},
            "links": [{"rel": "up", "href": "https://api.sandbox.paypal.com/v2/payments/captures/CAPTURE"}]}}
        self.assertTrue(store.record_webhook_event(event))
        result = store.get_sale_reconciliation("ORDER")
        self.assertEqual(result["order"]["status"], "REFUNDED")
        self.assertEqual(result["captures"][0]["amount"], "10.00")
        self.assertEqual(result["result"]["code"], "TERMINAL")

    def test_database_rejects_second_merchant_attempt_even_outside_helper(self):
        sale, _ = self.linked()
        with sqlite3.connect(self.db) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO order_creation_attempts(request_id,amount,currency,sale_id) VALUES('SECOND','10.00','CAD',?)", (sale,))

    def test_observation_cannot_be_applied_to_another_opened_payment(self):
        self.linked()
        with self.assertRaises(ValueError):
            store.record_payment_observation("ORDER", self.observation(order_id="OTHER"))
        self.assertEqual(self.code(), "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
