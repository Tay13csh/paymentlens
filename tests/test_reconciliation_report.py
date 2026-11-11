"""CSV safety, scope and snapshot regressions using synthetic/temporary records."""

from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import streamlit as st
import order_store as store
import payment_assistant as assistant
from reconciliation_report import HEADERS, NOTICE, SCOPE, build_report, csv_text
from reconciliation_facts import information_gaps
import test_payment_view as fixtures

NOW = datetime(2026, 11, 11, 12, 30, tzinfo=timezone.utc)


def evidence():
    return {"sale": {"description": "Mug", "amount": "12.00", "currency": "CAD"},
            "order": {"order_id": "PRIVATE-ORDER-123456", "status": "COMPLETED", "capture_state": "COMPLETED"},
            "captures": [{"capture_id": "PRIVATE-CAPTURE", "amount": "10.00", "currency": "CAD", "status": "COMPLETED",
                          "amount_pair_valid": 1, "full_capture_verified": 1, "final_capture": 1, "conflict": 0}],
            "observations": [], "issues": [],
            "result": {"code": "DIFFERENCE", "reasons": ["AMOUNT_DIFFERENCE"], "difference": "-2.00", "currency": "CAD"}}


def rows(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))


class ReconciliationReportTests(unittest.TestCase):
    def test_standard_csv_bom_unicode_quotes_newlines_and_exact_decimal_strings(self):
        item = evidence()
        item["sale"].update(description='中文 mug, "handmade"\r\nSecond line', amount="12")
        item["captures"][0]["amount"] = "10.0"
        report = build_report([item], NOW)
        self.assertTrue(report.data.startswith(b"\xef\xbb\xbf"))
        table = list(csv.reader(io.StringIO(report.data.decode("utf-8-sig"), newline="")))
        self.assertEqual(len(table), 2)
        self.assertEqual(tuple(table[0]), HEADERS)
        row = rows(report.data)[0]
        self.assertEqual(row["Description"], item["sale"]["description"])
        self.assertEqual((row["Merchant expected amount"], row["Capture amount"], row["Difference"]), ("12", "10.0", "-2.00"))
        self.assertEqual(row["Exported at UTC"], "2026-11-11T12:30:00Z")
        self.assertEqual(row["Record count"], "1")
        self.assertEqual(row["Scope"], SCOPE)
        self.assertEqual(row["Evidence notice"], NOTICE)

    def test_formula_prefixes_and_controls_are_protected_but_negative_numbers_are_not_text(self):
        for text in ("=1+2", " +SUM(A1)", "\t@SUM(A1)", "\r\n-2+3", "\x00=1", "\ufeff=1", "\u200b \t=1", "＝1+1", "-2.00"):
            with self.subTest(text=repr(text)):
                item = evidence();item["sale"]["description"] = text
                row = rows(build_report([item], NOW).data)[0]
                self.assertEqual(row["Description"], "'" + text.replace("\x00", r"\u0000"))
                self.assertEqual(row["Difference"], "-2.00")
        self.assertEqual(csv_text("Ordinary 中文 text"), "Ordinary 中文 text")

    def test_invalid_amounts_are_blank_never_coerced_or_rounded(self):
        for value in (10.0, "1e2", "NaN", "+10", "10.001", "10\n", "\t=1", "١٠.٠٠", "-10.00"):
            with self.subTest(value=value):
                item = evidence();item["sale"]["amount"] = value;item["captures"][0]["amount"] = value
                row = rows(build_report([item], NOW).data)[0]
                self.assertEqual(row["Merchant expected amount"], "")
                self.assertEqual(row["Merchant currency"], "")
                self.assertEqual(row["Capture amount"], "")
        for value in (2.0, "2.001", "=2", "2e0", "+2.00"):
            item = evidence();item["result"]["difference"] = value
            self.assertEqual(rows(build_report([item], NOW).data)[0]["Difference"], "")
        item = evidence();item["result"].update(code="MATCH", difference="0.00")
        self.assertEqual(rows(build_report([item], NOW).data)[0]["Difference"], "0.00")

    def test_conflict_retains_both_observations_without_selecting_a_confirmed_amount(self):
        item = evidence();item["captures"][0]["conflict"] = 1
        item["result"] = {"code": "REVIEW", "reasons": ["EVIDENCE_CONFLICT"]}
        item["observations"] = [dict(item["captures"][0], amount=amount, source=source)
                                for amount, source in (("10.00", "CAPTURE_RESPONSE"), ("12.00", "ORDER_QUERY"))]
        row = rows(build_report([item], NOW).data)[0]
        for field in ("Capture amount", "Capture currency", "Difference", "Difference currency"):
            self.assertEqual(row[field], "")
        observations = json.loads(row["Conflicting observations"])
        self.assertEqual({o["amount"] for o in observations}, {"10.00", "12.00"})
        self.assertEqual({o["currency"] for o in observations}, {"CAD"})
        self.assertEqual({o["source"] for o in observations}, {"CAPTURE_RESPONSE", "ORDER_QUERY"})
        self.assertEqual({o["capture"] for o in observations}, {"Capture 1"})
        self.assertNotIn("PRIVATE-", str(row))

    def test_multiple_or_unsupported_captures_never_take_first_or_export_difference(self):
        for change in ("multiple", "unsupported"):
            item = evidence()
            if change == "multiple":item["captures"].append(dict(item["captures"][0], capture_id="SECOND"))
            else:item["result"].update(code="REVIEW", reasons=["UNSUPPORTED_STRUCTURE"])
            row = rows(build_report([item], NOW).data)[0]
            self.assertEqual(row["Capture amount"], "")
            self.assertEqual(row["Difference"], "")

    def test_missing_fields_and_noncomparable_difference_use_existing_gaps(self):
        item = evidence();item.update(sale=None, captures=[], result={"code": "HISTORY", "reasons": ["HISTORY"]})
        row = rows(build_report([item], NOW).data)[0]
        for field in ("Description", "Merchant expected amount", "Capture amount", "Difference"):
            self.assertEqual(row[field], "")
        self.assertEqual(json.loads(row["Information gaps"]), information_gaps(item))
        self.assertEqual(json.loads(row["Information gaps"]), assistant.make_fact_packet(item)["evidence"][2]["values"]["information_gaps"])
        item = evidence();item["result"].update(code="CURRENCY", reasons=["CURRENCY_MISMATCH"])
        self.assertEqual(rows(build_report([item], NOW).data)[0]["Difference"], "")

    def test_metadata_does_not_leak_search_identifiers_or_raw_fields_and_enums_are_whitelisted(self):
        item = evidence();item["raw_payload"] = {"email": "private@example.invalid", "token": "NEVER-EXPORT"}
        item["result"].update(code="=BAD()", reasons=["=BAD()"])
        row = rows(build_report([item], NOW, category="=BAD()", search_active=True, reason_filters=["=BAD() "]).data)[0]
        self.assertEqual(row["Order suffix"], "…123456")
        self.assertEqual(row["Reconciliation code"], "UNRECOGNIZED_OR_MISSING")
        self.assertNotIn("=BAD", str(row))
        for private in ("PRIVATE-ORDER", "PRIVATE-CAPTURE", "private@example", "NEVER-EXPORT"):
            self.assertNotIn(private, str(row))
        self.assertIn("text omitted", json.loads(row["Filters"])["search"])
        item["order"]["order_id"] = "SHORT"
        self.assertEqual(rows(build_report([item], NOW).data)[0]["Order suffix"], "")

    def test_report_bytes_are_immutable_and_empty_report_has_one_header_only(self):
        item = evidence();report = build_report([item], NOW);before = report.data
        item["sale"]["amount"] = "999.00"
        self.assertEqual(report.data, before)
        self.assertEqual(rows(report.data)[0]["Merchant expected amount"], "12.00")
        empty = build_report([], NOW)
        self.assertEqual(empty.record_count, 0)
        self.assertEqual(rows(empty.data), [])
        self.assertEqual(len(list(csv.reader(io.StringIO(empty.data.decode("utf-8-sig"))))), 1)
        for records in ([dict(evidence(), context="guided_demo")], [evidence()] * 21):
            with self.assertRaises(ValueError):build_report(records, NOW)

    def test_export_imports_without_site_packages_or_clients(self):
        script = "import sys,reconciliation_report; assert not {'openai','requests','paypal_auth','sqlite3'}.intersection(sys.modules)"
        completed = subprocess.run([sys.executable, "-S", "-c", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


class ReportPageTests(unittest.TestCase):
    start = fixtures.PaymentViewTests.start
    sale = fixtures.PaymentViewTests.sale
    observation = fixtures.PaymentViewTests.observation
    app = fixtures.PaymentViewTests.app
    open = fixtures.PaymentViewTests.open
    table = fixtures.PaymentViewTests.table
    dump = fixtures.PaymentViewTests.dump

    def setUp(self):
        fixtures.PaymentViewTests.setUp(self)
        self.chat = self.start(patch.object(assistant, "ask_payment", side_effect=AssertionError("AI forbidden")))
        self.download = self.start(patch.object(st, "download_button", wraps=st.download_button))

    def tearDown(self):
        fixtures.PaymentViewTests.tearDown(self)
        self.chat.assert_not_called()

    def exported(self):
        return rows(self.download.call_args.kwargs["data"])

    def test_download_uses_existing_snapshot_even_if_database_changes_after_read(self):
        self.sale("PAYMENT-ORIGINAL", expected="12.00")
        original = st.download_button.__wrapped__ if hasattr(st.download_button, "__wrapped__") else self.download._mock_wraps
        payloads = []
        def changed_database(*args, **kwargs):
            payloads.append(kwargs["data"])
            store.record_payment_observation("PAYMENT-ORIGINAL", self.observation("PAYMENT-ORIGINAL", "11.00"))
            return original(*args, **kwargs)
        self.download.side_effect = changed_database
        with patch.object(store, "get_review_view_snapshot", wraps=store.get_review_view_snapshot) as read:
            app = self.app()
            self.assertEqual(read.call_count, 1)
        self.assertEqual(rows(payloads[0])[0]["Reconciliation code"], "DIFFERENCE")
        self.assertEqual(rows(payloads[0])[0]["Difference"], "-2.00")
        self.assertIn("Amount difference", self.table(app))
        self.assertEqual(store.get_review_view_snapshot()["by_id"]["PAYMENT-ORIGINAL"]["result"]["code"], "REVIEW")
        self.assertEqual(self.download.call_args.kwargs["on_click"], "ignore")

    def test_filtered_recent_twenty_exclude_retained_selection_and_opened_order(self):
        self.sale("OLD-PAYMENT", description="Old mug")
        app = self.app();self.open(app, "OLD-PAYMENT")
        for i in range(22):
            self.sale(f"NEW-PAYMENT-{i:06d}", description="Blue mug" if i % 2 == 0 else "Green mug", expected="12.00" if i % 3 == 0 else "10.00")
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE orders SET updated_at='2000-01-01 00:00:00' WHERE order_id='OLD-PAYMENT'")
        before = self.dump()
        app.run()
        self.assertEqual(len(self.exported()), 20)
        self.assertNotIn("Old mug", str(self.exported()))
        app.radio(key="review_filter").set_value("Needs attention").run()
        app.multiselect(key="payment_reason_filters").set_value(["AMOUNT_DIFFERENCE"]).run()
        app.text_input(key="payment_search").set_value("Blue").run()
        exported = self.exported()
        self.assertTrue(exported)
        self.assertTrue(all(row["Description"] == "Blue mug" and row["Reconciliation code"] == "DIFFERENCE" for row in exported))
        self.assertTrue(all(row["Record count"] == str(len(exported)) for row in exported))
        self.assertEqual(app.session_state["opened_payment_id"], "OLD-PAYMENT")
        self.assertEqual(app.session_state["selected_payment_id"], "OLD-PAYMENT")
        self.assertEqual(self.dump(), before)

    def test_empty_results_disable_download_and_examples_have_no_export(self):
        app = self.app()
        self.assertTrue(self.download.call_args.kwargs["disabled"])
        self.sale("REAL-PAYMENT", description="Mug")
        app.run()
        app.text_input(key="payment_search").set_value("No results here").run()
        self.assertTrue(self.download.call_args.kwargs["disabled"])
        self.assertEqual(self.exported(), [])
        self.assertTrue(any("No records to export" in item.value for item in app.info))
        self.download.reset_mock()
        app.radio(key="application_mode").set_value("Guided demo").run()
        self.download.assert_not_called()
        self.assertFalse(any("Reconciliation report" in item.value for item in app.markdown))
