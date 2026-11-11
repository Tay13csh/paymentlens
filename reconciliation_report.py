"""CSV of an already-filtered local snapshot. Standard library and pure facts only."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
import re
import unicodedata

from payment_evidence import REVIEW_REASON_LABELS
from reconciliation_facts import CODES, SOURCES, information_gaps

CATEGORIES = {"All", "Matched", "Needs attention", "Insufficient information"}
SCOPE = "Most recent 20 saved Sandbox payments; current view filters only"
NOTICE = "Local saved Sandbox evidence, not bank settlement"
HEADERS = (
    "Description", "Order suffix", "Merchant expected amount", "Merchant currency",
    "Capture amount", "Capture currency", "Difference", "Difference currency",
    "Reconciliation code", "Structured reasons", "Information gaps", "Conflicting observations",
    "Exported at UTC", "Scope", "Filters", "Record count", "Evidence notice",
)


def csv_text(value):
    """Neutralize spreadsheet formulas, including whitespace/control prefixes."""
    if not isinstance(value, str):
        return ""
    probe = unicodedata.normalize("NFKC", value)
    probe = probe.lstrip()
    while probe and (probe[0].isspace() or unicodedata.category(probe[0]).startswith("C")):
        probe = probe[1:]
    dangerous = (probe.startswith(("=", "+", "-", "@")) or
                 (value and unicodedata.category(value[0]).startswith("C")))
    # NUL and other non-text controls are not portable CSV text (Python 3.9's
    # reader rejects NUL). Preserve their identity as visible Unicode escapes;
    # tabs and line endings remain native CSV content.
    text = "".join("\\u%04x" % ord(c) if unicodedata.category(c) == "Cc" and c not in "\t\r\n" else c for c in value)
    return "'" + text if dangerous else text


def decimal_string(value, signed=False):
    """Validate, never format/round/pad. Only differences may be negative or zero."""
    pattern = r"-?[0-9]{1,26}(?:\.[0-9]{1,2})?" if signed else r"[0-9]{1,26}(?:\.[0-9]{1,2})?"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        return ""
    if not signed and Decimal(value) <= 0:
        return ""
    return value


def money_columns(amount, currency, signed=False):
    amount = decimal_string(amount, signed)
    if not amount or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return "", ""
    return amount, currency


def enum(value, choices):
    return value if isinstance(value, str) and value in choices else "UNRECOGNIZED_OR_MISSING"


def structured(value):
    return csv_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


@dataclass(frozen=True)
class Report:
    generated_at_utc: str
    record_count: int
    data: bytes


def build_report(records, generated_at, category="All", search_active=False, reason_filters=()):
    """Consume only visible records; never query, select a Capture, or recalculate."""
    records = tuple(records)
    if len(records) > 20 or any(item.get("context") == "guided_demo" for item in records):
        raise ValueError("Only the current recent-20 Sandbox view can be exported.")
    if not isinstance(generated_at, datetime) or generated_at.utcoffset() is None:
        raise ValueError("An aware report timestamp is required.")
    timestamp = generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    filters = structured({"category": enum(category, CATEGORIES),
                          "search": "applied (text omitted for identifier privacy)" if search_active else "none",
                          "attention_reasons_any": [enum(r, REVIEW_REASON_LABELS) for r in reason_filters]})
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(HEADERS)
    for evidence in records:
        sale = evidence.get("sale") or {}
        result = evidence["result"]
        captures = evidence.get("captures", [])
        reasons = result.get("reasons", [])
        conflict = "EVIDENCE_CONFLICT" in reasons or any(c.get("conflict") for c in captures)
        unsupported = bool(evidence.get("issues")) or "UNSUPPORTED_STRUCTURE" in reasons or result.get("code") == "UNSUPPORTED"
        expected = money_columns(sale.get("amount"), sale.get("currency"))
        captured = ("", "")
        if not conflict and not unsupported and len(captures) == 1 and captures[0].get("amount_pair_valid") == 1:
            captured = money_columns(captures[0].get("amount"), captures[0].get("currency"))
        difference = ("", "")
        if (not conflict and not unsupported and len(captures) == 1
                and result.get("code") in {"MATCH", "DIFFERENCE", "TERMINAL"}):
            difference = money_columns(result.get("difference"), result.get("currency"), signed=True)
        observations = []
        if conflict:
            aliases = {}
            for item in evidence.get("observations", []):
                alias = aliases.setdefault(item.get("capture_id"), "Capture " + str(len(aliases) + 1))
                amount, currency = money_columns(item.get("amount"), item.get("currency"))
                observations.append({"capture": alias, "amount": amount, "currency": currency,
                                     "source": enum(item.get("source"), SOURCES)})
        order_id = evidence["order"].get("order_id")
        suffix = "…" + order_id[-6:] if isinstance(order_id, str) and len(order_id) > 6 else ""
        writer.writerow((
            csv_text(sale.get("description")), csv_text(suffix), *expected, *captured, *difference,
            enum(result.get("code"), CODES), structured([enum(r, REVIEW_REASON_LABELS) for r in reasons]),
            structured(information_gaps(evidence)), structured(observations), timestamp,
            SCOPE, filters, len(records), NOTICE,
        ))
    return Report(timestamp, len(records), output.getvalue().encode("utf-8-sig"))
