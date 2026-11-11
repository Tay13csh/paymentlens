"""Synthetic persisted evidence: missing observation proof is not a contradiction.

These tests exercise storage/rules and the actual whitelist builder, not live-model
reasoning. Webhook records stand in for input already verified by the receiver.
"""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import order_store as store
import payment_assistant as assistant
from payment_evidence import PaymentObservation


class AssistantCompletenessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        replacement = patch.object(store, "DATABASE_PATH", Path(temporary.name) / "evidence.db")
        replacement.start()
        self.addCleanup(replacement.stop)
        sale = store.create_merchant_sale("Synthetic item", "10.00")
        attempt = store.begin_sale_creation(sale)
        store.complete_order_creation(attempt, "SYNTHETIC-ORDER", "https://example.invalid/approve")

    def capture(self, amount="10.00"):
        return {"id": "SYNTHETIC-CAPTURE", "amount": {"value": amount, "currency_code": "CAD"},
                "status": "COMPLETED", "final_capture": True}

    def record_response(self):
        payload = {"id": "SYNTHETIC-ORDER", "status": "COMPLETED", "purchase_units": [{
            "amount": {"value": "10.00", "currency_code": "CAD"},
            "payments": {"captures": [self.capture()]}}]}
        store.record_payment_observation("SYNTHETIC-ORDER", PaymentObservation(payload, "SYNTHETIC-ORDER", "CAPTURE_RESPONSE"))

    def record_webhook(self, amount="10.00"):
        resource = self.capture(amount)
        resource["supplementary_data"] = {"related_ids": {"order_id": "SYNTHETIC-ORDER"}}
        store.record_webhook_event({"id": "SYNTHETIC-EVENT", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": resource})

    def facts(self):
        evidence = store.get_review_view_snapshot()["by_id"]["SYNTHETIC-ORDER"]
        # Assert the serialized payload actually supplied to the SDK, not objects
        # that could differ from the transport representation.
        return evidence, json.loads(assistant.encoded(assistant.make_fact_packet(evidence)))

    def test_valid_response_and_webhook_without_total_proof_still_match(self):
        self.record_response()
        self.record_webhook()
        evidence, packet = self.facts()
        self.assertEqual(evidence["result"]["code"], "MATCH")
        self.assertEqual(evidence["result"]["difference"], "0.00")
        self.assertFalse(evidence["issues"])
        saved = next(f["values"] for f in packet["evidence"] if f["kind"] == "saved_capture")
        observations = [f["values"] for f in packet["evidence"] if f["kind"] == "capture_observation"]
        response = next(o for o in observations if o["source"] == "CAPTURE_RESPONSE")
        webhook = next(o for o in observations if o["source"] == "VERIFIED_WEBHOOK")
        self.assertEqual(response["alias"], webhook["alias"])
        self.assertEqual(response["money"], webhook["money"])
        self.assertTrue(saved["full_capture_verified"])
        self.assertEqual(saved["completeness_scope"], "saved_capture_across_observations")
        self.assertEqual(response["full_total_proof_in_this_observation"], "established")
        self.assertEqual(webhook["full_total_proof_in_this_observation"], "not_established")
        self.assertNotIn("full_capture_verified", webhook)
        self.assertIn("provider_unit_total", webhook["observation_missing_fields"])
        self.assertEqual(response["observation_missing_fields"], [])
        self.assertIsNone(webhook["provider_unit_total"]["amount"])
        self.assertFalse(saved["conflict"])
        result = packet["evidence"][2]["values"]
        self.assertNotIn("full_capture_total_proof_unconfirmed", result["information_gaps"])
        self.assertNotIn("EVIDENCE_CONFLICT", result["reasons"])
        self.assertFalse(result["explicit_conflict_reported"])

    def test_webhook_alone_remains_incomplete_not_conflicting(self):
        self.record_webhook()
        evidence, packet = self.facts()
        self.assertEqual(evidence["result"]["code"], "INCOMPLETE")
        result = packet["evidence"][2]["values"]
        self.assertIn("full_capture_total_proof_unconfirmed", result["information_gaps"])
        self.assertNotIn("EVIDENCE_CONFLICT", result["reasons"])
        self.assertIsNone(result["difference"])
        self.assertFalse(result["explicit_conflict_reported"])

    def test_real_amount_conflict_is_retained_despite_valid_response_proof(self):
        self.record_response()
        self.record_webhook("12.00")
        evidence, packet = self.facts()
        self.assertEqual(evidence["result"]["code"], "REVIEW")
        self.assertIn("EVIDENCE_CONFLICT", packet["evidence"][2]["values"]["reasons"])
        self.assertTrue(packet["evidence"][2]["values"]["explicit_conflict_reported"])
        saved = next(f["values"] for f in packet["evidence"] if f["kind"] == "saved_capture")
        self.assertTrue(saved["full_capture_verified"])
        self.assertTrue(saved["conflict"])
        observations = [f["values"] for f in packet["evidence"] if f["kind"] == "capture_observation"]
        self.assertEqual({o["money"]["amount"] for o in observations}, {"10.00", "12.00"})
        self.assertEqual(len({o["alias"] for o in observations}), 1)
