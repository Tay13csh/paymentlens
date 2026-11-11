"""Shared presentation facts; no reconciliation decisions, storage or clients."""

from decimal import Decimal, InvalidOperation
import re

CODES = {"MATCH", "HISTORY", "REVIEW", "UNSUPPORTED", "INCOMPLETE", "TERMINAL", "CURRENCY", "DIFFERENCE"}
SOURCES = {"CAPTURE_RESPONSE", "ORDER_QUERY", "VERIFIED_WEBHOOK", "LEGACY_API_RESULT"}


def pair(amount, currency):
    if (not isinstance(amount, str) or not re.fullmatch(r"\d{1,26}(?:\.\d{1,2})?", amount)
            or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
        return {"amount": None, "currency": None, "availability": "not_recorded_or_invalid"}
    try:
        valid = Decimal(amount).is_finite() and Decimal(amount) > 0
    except InvalidOperation:
        valid = False
    return {"amount": amount if valid else None, "currency": currency if valid else None,
            "availability": "recorded" if valid else "not_recorded_or_invalid"}


def information_gaps(evidence):
    """Preserve the existing assistant gap mapping for reports and explanations."""
    sale = evidence.get("sale")
    captures = evidence.get("captures", [])
    reasons = evidence["result"].get("reasons", [])
    gaps = []
    if not sale:
        gaps.append("merchant_order_link_missing")
    elif pair(sale.get("amount"), sale.get("currency"))["amount"] is None:
        gaps.append("merchant_amount_or_currency_unavailable")
    if not captures:
        gaps.append("independent_capture_missing")
    if any(not c.get("amount_pair_valid") for c in captures):
        gaps.append("valid_capture_money_pair_unconfirmed")
    if any(not c.get("full_capture_verified") for c in captures):
        gaps.append("full_capture_total_proof_unconfirmed")
    if any(pair(c.get("amount"), c.get("currency"))["amount"] is None for c in captures):
        gaps.append("capture_amount_or_currency_unavailable")
    if "PAYMENT_NOT_COMPLETED" in reasons:
        gaps.append("local_completion_unconfirmed")
    return gaps
