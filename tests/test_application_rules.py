"""Source-backed branch cases and actual fake-client payload/budget checks."""

import ast
from copy import deepcopy
import hashlib
import inspect
import json
import re
import unittest
from unittest.mock import patch

import guided_demo
import payment_assistant as assistant
from payment_evidence import normalize_order, reconcile_sale
import test_payment_assistant as api_fixtures

snapshot = api_fixtures.snapshot

# Recorded before adding APPLICATION_RULES. A prompt-only change must not alter
# even the serialized fact representation of these synthetic real/example cases.
BASELINE_PACKET_HASHES = {'sandbox': 'afd332b38e2ed79a47a49d79986f8ec412a56a88eb4d7a7300d70995247876f4', 'Matching': '1c8acca48586c62cdba3e58552b595aacc009e2b1d6a2ded52e44440c5cb7af9', 'Amount difference': 'd4aaab7984ba2b452f0d33057a54fde1ed6725fcddc9d9d6febd1af45af8ee47', 'Insufficient information': 'dbf4deba571eeb4850963a1abb74e49896ceb248bdf957931f32761703c99997', 'Conflicting evidence': 'c366d9c06879098946215f65e1b2e9a1865442d22e2d5a895602f76969b2ddd1', 'Refunded': 'a63eb360528413cec4dbd5cba1fcb130f6ff985cb9f2ee12646c32650edc6e1c'}


def branch_cases():
    cases = []
    def case(name, mutate, code, reasons=(), difference=None):
        evidence = snapshot()
        mutate(evidence)
        cases.append((name, evidence, code, set(reasons), difference))
    case("match", lambda e: None, "MATCH", difference="0.00")
    case("no link precedes conflict", lambda e: (e.update(sale=None), e["captures"][0].update(conflict=1)), "HISTORY", ["HISTORY"])
    case("explicit conflict", lambda e: e["captures"][0].update(conflict=1), "REVIEW", ["EVIDENCE_CONFLICT"])
    case("structural issue precedes absent Capture", lambda e: e.update(captures=[], issues=["Multiple purchase units are unsupported"]), "REVIEW", ["UNSUPPORTED_STRUCTURE"])
    case("identity conflict", lambda e: e.update(issues=["Provider order identity differs"]), "REVIEW", ["EVIDENCE_CONFLICT"])
    case("both issue types", lambda e: e.update(issues=["Provider order identity differs", "Multiple purchase units are unsupported"]), "REVIEW", ["EVIDENCE_CONFLICT", "UNSUPPORTED_STRUCTURE"])
    case("multiple without earlier issue", lambda e: e["captures"].append(dict(e["captures"][0])), "UNSUPPORTED", ["UNSUPPORTED_STRUCTURE"])
    case("missing Capture", lambda e: e.update(captures=[]), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"])
    for field, value in (("final_capture", 0), ("status", "PENDING"), ("amount", None), ("currency", None),
                         ("amount_pair_valid", 0), ("full_capture_verified", 0)):
        case("incomplete " + field, lambda e, f=field, v=value: e["captures"][0].update({f: v}), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"])
    case("approval not collection", lambda e: e["order"].update(status="APPROVED"), "INCOMPLETE", ["PAYMENT_NOT_COMPLETED"])
    case("local Capture state precedes currency", lambda e: (e["order"].update(capture_state="UNKNOWN"), e["captures"][0].update(currency="USD", provider_order_currency="USD")), "INCOMPLETE", ["PAYMENT_NOT_COMPLETED"])
    case("proof precedes currency", lambda e: e["captures"][0].update(full_capture_verified=0, currency="USD", provider_order_currency="USD"), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"])
    case("currency", lambda e: e["captures"][0].update(currency="USD", provider_order_currency="USD"), "CURRENCY", ["CURRENCY_MISMATCH"])
    case("below", lambda e: e["sale"].update(amount="12.00"), "DIFFERENCE", ["AMOUNT_DIFFERENCE"], "-2.00")
    case("above", lambda e: e["sale"].update(amount="5.00"), "DIFFERENCE", ["AMOUNT_DIFFERENCE"], "5.00")
    for status in ("REFUNDED", "REVERSED", "DENIED"):
        case(status + " equal", lambda e, s=status: e["order"].update(status=s), "TERMINAL", [status], "0.00")
        case(status + " different", lambda e, s=status: (e["order"].update(status=s), e["sale"].update(amount="12.00")), "DIFFERENCE", ["AMOUNT_DIFFERENCE", status], "-2.00")
        case(status + " different currency", lambda e, s=status: (e["order"].update(status=s), e["captures"][0].update(currency="USD", provider_order_currency="USD")), "CURRENCY", ["CURRENCY_MISMATCH", status])
        case(status + " absent Capture", lambda e, s=status: (e["order"].update(status=s), e.update(captures=[])), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE", status])
    return cases


class ApplicationRulesTests(unittest.TestCase):
    setUp = api_fixtures.PaymentAssistantAPITests.setUp
    ask = api_fixtures.PaymentAssistantAPITests.ask

    def test_source_branches_and_reasons_agree_with_cases_and_every_request(self):
        codes = set()
        for name, evidence, code, reasons, difference in branch_cases():
            with self.subTest(name=name):
                result = reconcile_sale(evidence["sale"], evidence["order"], evidence["captures"], evidence["issues"])
                self.assertEqual((result["code"], set(result["reasons"]), result.get("difference")), (code, reasons, difference))
                self.assertEqual(result["needs_review"], code != "MATCH")
                evidence["result"] = result
                before = deepcopy(evidence)
                packet = assistant.make_fact_packet(evidence)
                packet_before = deepcopy(packet)
                self.client.responses.create.return_value.output_text = json.dumps({
                    "explanation": "The application reports " + code + " based on saved records.",
                    "general_checks": [], "evidence_refs": ["E3"]})
                self.ask(packet=packet, question="Why did the application reach this conclusion?")
                request = self.client.responses.create.call_args.kwargs
                wire_packet = json.loads(request["input"][0]["content"].split("\n", 1)[1])
                self.assertEqual(wire_packet, packet_before)
                self.assertEqual(wire_packet["evidence"][2]["values"]["code"], code)
                self.assertEqual(set(wire_packet["evidence"][2]["values"]["reasons"]), reasons)
                self.assertEqual(wire_packet["evidence"][2]["values"]["difference"], difference)
                self.assertEqual(packet, packet_before)
                self.assertEqual(evidence, before)
                self.assertIn(assistant.APPLICATION_RULES, request["instructions"])
                self.assertEqual((request["tools"], request["tool_choice"], request["max_output_tokens"]), ([], "none", 900))
                codes.add(code)
        # Auxiliary coverage guard: derive returned codes from the actual source,
        # rather than relying only on an independently maintained enumeration.
        source_codes = set()
        for node in ast.walk(ast.parse(inspect.getsource(reconcile_sale))):
            values = []
            if isinstance(node, ast.Dict):
                values = [value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant) and key.value == "code"]
            elif isinstance(node, ast.keyword) and node.arg == "code":
                values = [node.value]
            for value in values:
                source_codes.update(n.value for n in ast.walk(value) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        self.assertEqual(codes, source_codes)
        self.assertEqual(codes, assistant.CODES)
        self.assertTrue(all(code in assistant.APPLICATION_RULES for code in codes))

    def test_full_total_rule_matches_normalization_then_reconciliation(self):
        payload = {"id": "SYNTHETIC", "status": "COMPLETED", "purchase_units": [{
            "amount": {"value": "10.00", "currency_code": "CAD"}, "payments": {"captures": [{
                "id": "CAPTURE", "amount": {"value": "10.00", "currency_code": "CAD"},
                "status": "COMPLETED", "final_capture": True}]}}]}
        variants = (
            ("complete", lambda p: None, "MATCH", []),
            ("total missing", lambda p: p["purchase_units"][0].pop("amount"), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"]),
            ("provider order incomplete", lambda p: p.update(status="APPROVED"), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"]),
            ("not final", lambda p: p["purchase_units"][0]["payments"]["captures"][0].update(final_capture=False), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"]),
            ("Capture incomplete", lambda p: p["purchase_units"][0]["payments"]["captures"][0].update(status="PENDING"), "INCOMPLETE", ["CAPTURE_EVIDENCE_INCOMPLETE"]),
            ("total differs", lambda p: p["purchase_units"][0]["amount"].update(value="12.00"), "REVIEW", ["UNSUPPORTED_STRUCTURE"]),
            ("multiple units", lambda p: p["purchase_units"].append(deepcopy(p["purchase_units"][0])), "REVIEW", ["UNSUPPORTED_STRUCTURE"]),
        )
        for name, change, code, reasons in variants:
            with self.subTest(name=name):
                observation = deepcopy(payload);change(observation)
                captures, issues = normalize_order(observation, "SYNTHETIC")
                for capture in captures:
                    capture.update(amount_pair_valid=bool(capture["amount"] and capture["currency"]), conflict=0)
                result = reconcile_sale(snapshot()["sale"], snapshot()["order"], captures, issues)
                self.assertEqual((result["code"], set(result["reasons"])), (code, set(reasons)))
                self.assertEqual(captures[0]["full_capture_verified"], name == "complete")

    def test_full_provider_proof_is_independent_of_merchant_amount_matching_in_request(self):
        payload = {"id": "SYNTHETIC", "status": "COMPLETED", "purchase_units": [{
            "amount": {"value": "10.00", "currency_code": "CAD"}, "payments": {"captures": [{
                "id": "CAPTURE", "amount": {"value": "10.00", "currency_code": "CAD"},
                "status": "COMPLETED", "final_capture": True}]}}]}
        captures, issues = normalize_order(payload, "SYNTHETIC")
        self.assertTrue(captures[0]["full_capture_verified"])
        self.assertFalse(issues)
        for capture in captures:
            capture.update(amount_pair_valid=1, conflict=0, source="CAPTURE_RESPONSE")
        evidence = snapshot(expected="12.00")
        evidence.update(captures=captures, issues=issues)
        evidence["result"] = reconcile_sale(evidence["sale"], evidence["order"], captures, issues)
        self.assertEqual(evidence["result"]["code"], "DIFFERENCE")
        self.assertEqual(evidence["result"]["difference"], "-2.00")
        for name, item in (("complete but different", evidence),
                           ("missing evidence", guided_demo.demo_snapshot("Insufficient information"))):
            with self.subTest(name=name):
                packet = assistant.make_fact_packet(item);before = deepcopy(packet)
                self.ask(packet=packet, question="What does full Capture proof require, separately from merchant matching?")
                request = self.client.responses.create.call_args.kwargs
                wire = json.loads(request["input"][0]["content"].split("\n", 1)[1])
                self.assertEqual(wire, before)
                self.assertEqual(packet, before)
                self.assertIn("Merchant terms are not part of this proof", assistant.APPLICATION_RULES)
                self.assertIn("A complete Capture can yield DIFFERENCE", assistant.APPLICATION_RULES)
                self.assertIn("not with merchant terms", request["instructions"])
                self.assertIn("later independent reconciliation step", request["instructions"])
                if name == "complete but different":
                    expected = wire["evidence"][0]["values"]["money"]
                    result = wire["evidence"][2]["values"]
                    capture = next(f["values"] for f in wire["evidence"] if f["kind"] == "saved_capture")
                    self.assertEqual(expected, {"amount": "12.00", "currency": "CAD", "availability": "recorded"})
                    self.assertEqual(capture["money"]["amount"], "10.00")
                    self.assertEqual(capture["provider_unit_total"]["amount"], "10.00")
                    self.assertTrue(capture["full_capture_verified"])
                    self.assertEqual((result["code"], result["difference"]), ("DIFFERENCE", "-2.00"))
                    self.assertNotIn("full_capture_total_proof_unconfirmed", result["information_gaps"])
                    self.assertFalse(result["explicit_conflict_reported"])

    def test_simulated_evidence_instructions_use_natural_example_wording(self):
        self.ask(packet=assistant.make_fact_packet(guided_demo.demo_snapshot("Matching")))
        instructions = self.client.responses.create.call_args.kwargs["instructions"]
        self.assertIn("simulated example", instructions)
        self.assertNotRegex(instructions.lower(), r"fabricated? premises?|fabricated? facts?|fabricated? evidence")

    def test_five_demo_cases_keep_original_results_and_serialized_fact_hashes(self):
        samples = {"sandbox": snapshot(), **{name: guided_demo.demo_snapshot(name) for name in guided_demo.CASES}}
        self.assertEqual(set(samples), set(BASELINE_PACKET_HASHES))
        expected_codes = ["MATCH", "DIFFERENCE", "INCOMPLETE", "REVIEW", "TERMINAL"]
        for name, code in zip(guided_demo.CASES, expected_codes):
            item = samples[name]
            self.assertEqual(item["result"], reconcile_sale(item["sale"], item["order"], item["captures"], item["issues"]))
            self.assertEqual(item["result"]["code"], code)
        for name, item in samples.items():
            digest = hashlib.sha256(assistant.encoded(assistant.make_fact_packet(item)).encode()).hexdigest()
            self.assertEqual(digest, BASELINE_PACKET_HASHES[name])

    def test_rules_are_bounded_general_logic_and_admit_unexplainable_contradictions(self):
        rules = assistant.APPLICATION_RULES
        self.assertLessEqual(len(rules.split()), 250)
        for text in ("not payment facts", "cannot explain", "Branches take precedence", "neither negates existing proof nor establishes conflict",
                     "DENIED means payment denied, not dispute", "the application rules and saved records here don't cover this"):
            self.assertIn(text, rules)
        self.assertNotRegex(rules, r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b[A-Z0-9]{17}\b|https?://")
        for text in ("PRIVATE-", "Private mug description", "SYNTHETIC-", "sk-"):
            self.assertNotIn(text, rules)
        self.ask()
        instructions = self.client.responses.create.call_args.kwargs["instructions"]
        self.assertIn("facts clearly contradict", instructions)
        self.assertNotIn("never recalculate, overrule or invent them", instructions)

    def test_character_budget_counts_the_complete_payload_at_exact_boundary(self):
        self.ask()
        payload = self.client.responses.create.call_args.kwargs
        size = len(assistant.encoded(payload))
        with patch.object(assistant, "MAX_INPUT", size):
            self.ask()
        self.constructor.reset_mock();self.client.responses.create.reset_mock()
        with patch.object(assistant, "MAX_INPUT", size - 1):
            with self.assertRaisesRegex(assistant.PaymentAssistantError, "character"):
                self.ask()
        self.constructor.assert_not_called()
        self.client.responses.create.assert_not_called()

    def test_fixed_instructions_and_schema_overhead_cannot_bypass_limit(self):
        self.ask(history=[{"question": "Why?", "answer": {"explanation": "Only saved evidence is known.", "general_checks": [], "evidence_refs": ["E1"]}}])
        payload = self.client.responses.create.call_args.kwargs
        messages_only = len(assistant.encoded(payload["input"]))
        self.constructor.reset_mock()
        with patch.object(assistant, "MAX_INPUT", messages_only + 1):
            with self.assertRaisesRegex(assistant.PaymentAssistantError, "character"):
                self.ask()
        self.constructor.assert_not_called()
        # Adding schema/instruction text must increase the measured request even
        # when the packet, question and history have not changed.
        normal_size = len(assistant.encoded(payload))
        schema = deepcopy(assistant.ANSWER_SCHEMA);schema["description"] = "x" * 1000
        for changes in ({"ANSWER_SCHEMA": schema}, {"INSTRUCTIONS": assistant.INSTRUCTIONS + "x" * 1000}):
            with patch.multiple(assistant, **changes), patch.object(assistant, "MAX_INPUT", normal_size + 200):
                with self.assertRaisesRegex(assistant.PaymentAssistantError, "character"):
                    self.ask()
        self.constructor.assert_not_called()

    def test_oversize_facts_reject_without_truncating_or_constructing_client(self):
        packet = deepcopy(self.packet);packet["test_padding"] = "x" * assistant.MAX_PACKET
        before = deepcopy(packet)
        with self.assertRaisesRegex(assistant.PaymentAssistantError, "character"):
            self.ask(packet=packet)
        self.assertEqual(packet, before)
        self.constructor.assert_not_called()
