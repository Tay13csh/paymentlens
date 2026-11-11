import asyncio
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from fastapi import HTTPException
from streamlit.testing.v1 import AppTest
from ui_helpers import sandbox_test_app

import order_store
import paypal_auth
import webhook_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.payload = payload

    def json(self):
        return self.payload


class FakeWebhookRequest:
    def __init__(self, event, headers):
        self._body = json.dumps(event).encode("utf-8")
        self.headers = headers

    async def body(self):
        return self._body


class CaptureSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original_database_path = order_store.DATABASE_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        order_store.DATABASE_PATH = Path(self.temp_dir.name) / "orders.db"
        order_store.initialize_database()

    def tearDown(self):
        order_store.DATABASE_PATH = self.original_database_path
        self.temp_dir.cleanup()

    def save_order(self, order_id, amount="10.00", status="CREATED"):
        order_store.save_order(order_id, amount, "CAD")
        if status != "CREATED":
            order_store.update_order_status(order_id, status)

    def run_app_for_order(self, order_id):
        app = sandbox_test_app(str(APP_PATH)).run()
        app.query_params["token"] = order_id
        app.radio(key="main_navigation").set_value("Sandbox tools").run()
        return app

    @staticmethod
    def capture_button(app):
        return next(button for button in app.button if button.label == "Capture Approved Order")

    @staticmethod
    def paypal_secrets():
        return {"paypal": {"client_id": "synthetic-client-id", "client_secret": "synthetic-secret"}}

    def test_existing_database_migrates_capture_state(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE orders (
                    order_id TEXT PRIMARY KEY,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    capture_id TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO orders (order_id, amount, currency, status) VALUES (?, ?, ?, ?)",
                ("LEGACY-ORDER", "10.00", "CAD", "APPROVED"),
            )

        order_store.DATABASE_PATH = legacy_path
        order = order_store.get_order("LEGACY-ORDER")
        self.assertEqual(order["capture_state"], "READY")
        order_store.DATABASE_PATH = Path(self.temp_dir.name) / "orders.db"

    def test_completed_order_is_disabled_and_send_guard_rejects_it(self):
        self.save_order("ORDER-COMPLETED", status="COMPLETED")
        post_calls = []

        def unexpected_post(url, **kwargs):
            post_calls.append(url)
            raise AssertionError("A completed order must not send a request.")

        with patch.object(st, "secrets", self.paypal_secrets()), patch.object(
            paypal_auth.requests, "post", side_effect=unexpected_post
        ):
            app = self.run_app_for_order("ORDER-COMPLETED")
            self.capture_button(app).click().run()

        self.assertTrue(self.capture_button(app).disabled)
        self.assertFalse(order_store.begin_capture("ORDER-COMPLETED"))
        self.assertFalse(post_calls)

    def test_request_id_is_stable_across_process_restart(self):
        request_id = paypal_auth.get_capture_request_id("ORDER-STABLE")
        script = (
            "from paypal_auth import get_capture_request_id; "
            "print(get_capture_request_id('ORDER-STABLE'))"
        )
        restarted_value = subprocess.check_output(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            text=True,
        ).strip()
        self.assertEqual(restarted_value, request_id)

    def test_unapproved_capture_failure_does_not_mark_order_completed(self):
        self.save_order("ORDER-UNAPPROVED")
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/v1/oauth2/token"):
                return FakeResponse(200, {"access_token": "synthetic-token"})
            return FakeResponse(422, {"name": "UNPROCESSABLE_ENTITY"})

        with patch.object(st, "secrets", self.paypal_secrets()), patch.object(
            paypal_auth.requests, "post", side_effect=fake_post
        ):
            app = self.run_app_for_order("ORDER-UNAPPROVED")
            self.capture_button(app).click().run()

        order = order_store.get_order("ORDER-UNAPPROVED")
        self.assertEqual(order["status"], "CREATED")
        self.assertEqual(order["capture_state"], "READY")
        self.assertTrue(app.error)
        self.assertEqual(sum(url.endswith("/capture") for url, _ in calls), 1)

    def test_timeout_query_failure_and_same_id_retry(self):
        order_id = "ORDER-TIMEOUT"
        self.save_order(order_id, status="APPROVED")
        capture_ids = []
        capture_attempts = 0
        get_attempts = 0

        def fake_post(url, **kwargs):
            nonlocal capture_attempts
            if url.endswith("/v1/oauth2/token"):
                return FakeResponse(200, {"access_token": "synthetic-token"})
            capture_attempts += 1
            capture_ids.append(kwargs["headers"]["PayPal-Request-Id"])
            if capture_attempts == 1:
                raise requests.Timeout("synthetic timeout")
            return FakeResponse(
                201,
                {
                    "status": "COMPLETED",
                    "purchase_units": [{"payments": {"captures": [{"id": "SYNTHETIC-CAPTURE"}]}}],
                },
            )

        def fake_get(url, **kwargs):
            nonlocal get_attempts
            get_attempts += 1
            if get_attempts == 1:
                raise requests.Timeout("synthetic status query timeout")
            return FakeResponse(200, {"status": "APPROVED"})

        with patch.object(st, "secrets", self.paypal_secrets()), patch.object(
            paypal_auth.requests, "post", side_effect=fake_post
        ), patch.object(paypal_auth.requests, "get", side_effect=fake_get):
            app = self.run_app_for_order(order_id)
            self.capture_button(app).click().run()

            order = order_store.get_order(order_id)
            self.assertEqual(order["status"], "APPROVED")
            self.assertEqual(order["capture_state"], "UNKNOWN")
            self.assertTrue(any("unconfirmed" in item.value.lower() for item in app.warning))
            self.assertFalse(any(button.label == "Capture Approved Order" for button in app.button))
            self.assertEqual(capture_attempts, 1)

            app = self.run_app_for_order(order_id)
            self.assertTrue(any(button.label == "Check PayPal Order Status" for button in app.button))
            app.button(key="check_paypal_order_status").click().run()
            self.assertEqual(order_store.get_order(order_id)["capture_state"], "UNKNOWN")
            self.assertTrue(any("unconfirmed" in item.value.lower() for item in app.warning))
            self.assertEqual(capture_attempts, 1)

            app.button(key="check_paypal_order_status").click().run()
            self.assertEqual(order_store.get_order(order_id)["capture_state"], "READY")
            self.assertEqual(order_store.get_order(order_id)["status"], "APPROVED")
            self.capture_button(app).click().run()

        order = order_store.get_order(order_id)
        self.assertEqual(order["status"], "COMPLETED")
        self.assertEqual(order["capture_state"], "COMPLETED")
        self.assertEqual(capture_attempts, 2)
        self.assertEqual(capture_ids[0], capture_ids[1])
        self.assertFalse(order_store.begin_capture(order_id))

    def test_webhook_verification_deduplication_and_ordering(self):
        self.save_order("ORDER-WEBHOOK-A")
        self.save_order("ORDER-WEBHOOK-B")
        verifier_result = {"valid": True}
        verifier_calls = []
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://example.invalid/cert",
            "paypal-transmission-id": "synthetic-transmission",
            "paypal-transmission-sig": "synthetic-signature",
            "paypal-transmission-time": "2026-11-07T00:00:00Z",
        }

        def fake_verify(*args):
            verifier_calls.append(True)
            return verifier_result["valid"]

        def deliver(event, event_headers):
            return asyncio.run(
                webhook_server.receive_paypal_webhook(FakeWebhookRequest(event, event_headers))
            )

        approved_a = {
            "id": "EVENT-APPROVED-A",
            "event_type": "CHECKOUT.ORDER.APPROVED",
            "resource": {"id": "ORDER-WEBHOOK-A"},
        }
        with patch.object(webhook_server, "load_paypal_settings", return_value={
            "client_id": "synthetic-id",
            "client_secret": "synthetic-secret",
            "webhook_id": "synthetic-webhook-id",
        }), patch.object(webhook_server, "verify_webhook_signature", side_effect=fake_verify):
            with self.assertRaises(HTTPException) as missing:
                deliver(approved_a, {})
            self.assertEqual(missing.exception.status_code, 400)
            self.assertFalse(verifier_calls)
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-A")["status"], "CREATED")

            verifier_result["valid"] = False
            with self.assertRaises(HTTPException) as invalid:
                deliver(approved_a, headers)
            self.assertEqual(invalid.exception.status_code, 400)
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-A")["status"], "CREATED")

            verifier_result["valid"] = True
            self.assertTrue(deliver(approved_a, headers)["processed"])
            self.assertFalse(deliver(approved_a, headers)["processed"])
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-A")["status"], "APPROVED")

            completed_a = {
                "id": "EVENT-COMPLETED-A",
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {
                    "id": "SYNTHETIC-CAPTURE-A",
                    "supplementary_data": {"related_ids": {"order_id": "ORDER-WEBHOOK-A"}},
                },
            }
            self.assertTrue(deliver(completed_a, headers)["processed"])
            delayed_approved_a = {
                "id": "EVENT-LATE-APPROVED-A",
                "event_type": "CHECKOUT.ORDER.APPROVED",
                "resource": {"id": "ORDER-WEBHOOK-A"},
            }
            self.assertFalse(deliver(delayed_approved_a, headers)["processed"])
            self.assertFalse(deliver(completed_a, headers)["processed"])
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-A")["status"], "COMPLETED")
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-A")["capture_state"], "COMPLETED")

            completed_b = {
                "id": "EVENT-COMPLETED-B",
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {
                    "id": "SYNTHETIC-CAPTURE-B",
                    "supplementary_data": {"related_ids": {"order_id": "ORDER-WEBHOOK-B"}},
                },
            }
            self.assertTrue(deliver(completed_b, headers)["processed"])
            delayed_approved_b = {
                "id": "EVENT-LATE-APPROVED-B",
                "event_type": "CHECKOUT.ORDER.APPROVED",
                "resource": {"id": "ORDER-WEBHOOK-B"},
            }
            self.assertFalse(deliver(delayed_approved_b, headers)["processed"])
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-B")["status"], "COMPLETED")
            self.assertEqual(order_store.get_order("ORDER-WEBHOOK-B")["capture_state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
