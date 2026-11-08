"""Offline tests for durable order-creation attempts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

import order_store
import paypal_auth


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class CreateIdempotencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database_patch = patch.object(order_store, "DATABASE_PATH", Path(temporary.name) / "orders.db")
        database_patch.start()
        self.addCleanup(database_patch.stop)
        secrets_patch = patch.object(st, "secrets", {
            "paypal": {"client_id": "synthetic-client", "client_secret": "synthetic-secret"}
        })
        secrets_patch.start()
        self.addCleanup(secrets_patch.stop)
        self.calls = []
        self.remote_orders = {}
        self.timeout_next = True
        post_patch = patch.object(paypal_auth.requests, "post", side_effect=self.fake_post)
        post_patch.start()
        self.addCleanup(post_patch.stop)

    def fake_post(self, url, **kwargs):
        if url.endswith("/v1/oauth2/token"):
            return Mock(ok=True, json=Mock(return_value={"access_token": "synthetic-token"}))
        self.assertTrue(url.endswith("/v2/checkout/orders"))
        self.calls.append(kwargs)
        key = kwargs["headers"].get("PayPal-Request-Id")
        # Simulate successful creation followed by a lost response.
        identity = key or f"missing-key-{len(self.calls)}"
        order_id = self.remote_orders.setdefault(identity, f"ORDER-{len(self.remote_orders) + 1}")
        if self.timeout_next:
            self.timeout_next = False
            raise requests.Timeout("synthetic lost response")
        return Mock(ok=True, json=Mock(return_value={
            "id": order_id,
            "links": [{"rel": "approve", "href": f"https://example.invalid/approve/{order_id}"}],
        }))

    def click(self, app, label):
        next(button for button in app.button if button.label == label).click().run()
        self.assertFalse(app.exception)

    def test_timeout_retry_reuses_request_key_and_payload(self):
        app = AppTest.from_file(str(APP_PATH)).run()
        self.click(app, "Create Sandbox Order")
        self.click(app, "Retry Same Order Creation")
        first_key = self.calls[0]["headers"].get("PayPal-Request-Id")
        self.assertTrue(first_key, "Creation must send an idempotency key")
        self.assertEqual(first_key, self.calls[1]["headers"].get("PayPal-Request-Id"))
        self.assertEqual(self.calls[0]["json"], self.calls[1]["json"])
        self.assertEqual(len(self.remote_orders), 1)
        self.assertEqual(len(order_store.get_orders()), 1)

    def refresh(self, app):
        # A new AppTest has no previous session_state, like a browser refresh.
        refreshed = AppTest.from_file(str(APP_PATH))
        refreshed.query_params.update(app.query_params)
        refreshed.run()
        self.assertFalse(refreshed.exception)
        return refreshed

    def test_refresh_restores_retry_key_and_original_amount_then_new_order_gets_new_key(self):
        app = AppTest.from_file(str(APP_PATH)).run()
        self.click(app, "Create Sandbox Order")
        attempt_id = app.query_params["create_attempt"]
        if isinstance(attempt_id, list):
            attempt_id = attempt_id[0]
        app = self.refresh(app)
        self.assertEqual(len(self.calls), 1, "Refresh must not send a request")
        amount_input = next(field for field in app.number_input if field.label == "Sandbox Order Amount (CAD)")
        amount_input.set_value(25.0).run()
        self.click(app, "Retry Same Order Creation")
        self.assertEqual(self.calls[1]["headers"]["PayPal-Request-Id"], attempt_id)
        self.assertEqual(self.calls[1]["json"]["purchase_units"][0]["amount"]["value"], "10.00")
        app.query_params["token"] = "PREVIOUS-RETURNED-ORDER"
        app.run()
        self.click(app, "Create New Sandbox Order")
        self.assertNotEqual(self.calls[2]["headers"]["PayPal-Request-Id"], attempt_id)
        self.assertEqual(self.calls[2]["json"]["purchase_units"][0]["amount"]["value"], "25.00")
        self.assertEqual(len(self.remote_orders), 2)
        self.assertEqual(len(order_store.get_orders()), 2)
        self.assertEqual(app.session_state["paypal_order_id"], "ORDER-2")

    def test_successful_creation_refresh_restores_order_without_resending(self):
        self.timeout_next = False
        app = AppTest.from_file(str(APP_PATH)).run()
        self.click(app, "Create Sandbox Order")
        app = self.refresh(app)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(app.session_state["paypal_order_id"], "ORDER-1")
        self.assertEqual(app.session_state["paypal_approval_url"], "https://example.invalid/approve/ORDER-1")
        self.assertFalse(any(button.label == "Retry Same Order Creation" for button in app.button))

    def test_local_save_failure_retains_key_for_recovery(self):
        self.timeout_next = False
        app = AppTest.from_file(str(APP_PATH)).run()
        with patch("order_store.complete_order_creation", side_effect=RuntimeError("synthetic write failure")):
            self.click(app, "Create Sandbox Order")
        self.assertEqual(order_store.get_orders(), [])
        app = self.refresh(app)
        self.click(app, "Retry Same Order Creation")
        self.assertEqual(self.calls[0]["headers"]["PayPal-Request-Id"], self.calls[1]["headers"]["PayPal-Request-Id"])
        self.assertEqual(len(self.remote_orders), 1)
        self.assertEqual(len(order_store.get_orders()), 1)

    def test_missing_attempt_does_not_silently_retry_with_new_key(self):
        app = AppTest.from_file(str(APP_PATH))
        app.query_params["create_attempt"] = "missing-attempt"
        app.run()
        self.assertTrue(app.warning)
        self.assertFalse(any(button.label == "Retry Same Order Creation" for button in app.button))
        self.assertEqual(self.calls, [])

    def test_invalid_request_key_is_rejected_before_network(self):
        with patch.object(paypal_auth, "get_access_token") as token:
            with self.assertRaises(paypal_auth.PayPalOrderError):
                paypal_auth.create_order("synthetic-id", "synthetic-secret", "10.00", request_id="")
            token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
