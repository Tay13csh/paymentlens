"""Minimal provider evidence normalization and exact, deterministic reconciliation."""

from decimal import Decimal, InvalidOperation
import re


def money(value):
    """Parse bounded, positive two-decimal money without a float conversion."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", value):
        raise ValueError("Use a positive amount with at most two decimal places (maximum 999999999.99).")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid money value.") from None
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return format(amount, ".2f")


def short_text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 255 else None


def money_pair(amount):
    """An amount and currency are usable only as one valid provider observation."""
    if not isinstance(amount, dict):
        return None, None
    currency = amount.get("currency_code")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None, None
    try:
        return money(amount.get("value")), currency
    except ValueError:
        return None, None


def normalize_capture(capture):
    """Whitelist fields only; never retain payer data, headers, or raw payloads."""
    if not isinstance(capture, dict):
        return None
    capture_id = short_text(capture.get("id"))
    if not capture_id:
        return None
    value, currency = money_pair(capture.get("amount"))
    final = capture.get("final_capture")
    return {
        "capture_id": capture_id,
        "amount": value,
        "currency": currency,
        "status": short_text(capture.get("status")),
        "final_capture": final if type(final) is bool else None,
        "occurred_at": short_text(capture.get("create_time")),
        "provider_order_amount": None,
        "provider_order_currency": None,
        "full_capture_verified": False,
    }


def normalize_order(payload, expected_order_id):
    """Inspect all captures; malformed/unsupported structures never become matches."""
    issues, captures = [], []
    if payload.get("id") and payload["id"] != expected_order_id:
        return [], ["Provider order identity differs"]
    units = payload.get("purchase_units", [])
    if not isinstance(units, list):
        return [], ["Unsupported purchase units"]
    if len(units) > 1:
        issues.append("Multiple purchase units are unsupported")
    if len(units) > 100:
        return [], issues + ["Provider evidence exceeds the supported size"]
    for unit in units:
        payments = unit.get("payments", {}) if isinstance(unit, dict) else None
        raw = payments.get("captures", []) if isinstance(payments, dict) else None
        if not isinstance(raw, list) or len(raw) > 100:
            issues.append("Unsupported capture structure")
            continue
        for capture in raw:
            normalized = normalize_capture(capture)
            if normalized:
                order_amount, order_currency = money_pair(unit.get("amount"))
                normalized["provider_order_amount"] = order_amount
                normalized["provider_order_currency"] = order_currency
                comparable = order_amount and normalized["amount"]
                if comparable and (order_amount, order_currency) != (normalized["amount"], normalized["currency"]):
                    issues.append("Capture does not equal the provider purchase unit total")
                normalized["full_capture_verified"] = bool(
                    len(units) == 1 and len(raw) == 1 and comparable
                    and (order_amount, order_currency) == (normalized["amount"], normalized["currency"])
                    and normalized["final_capture"] is True
                    and normalized["status"] == "COMPLETED" and payload.get("status") == "COMPLETED"
                )
                captures.append(normalized)
            else:
                issues.append("Capture identity missing")
    if len({item["capture_id"] for item in captures}) > 1:
        issues.append("Multiple captures are unsupported")
    return captures, issues


class PaymentObservation(tuple):
    """Keep legacy (status, ID) unpacking while carrying explicit new evidence."""
    def __new__(cls, payload, order_id, source):
        captures, issues = normalize_order(payload, order_id)
        capture_id = captures[0]["capture_id"] if len(captures) == 1 else None
        obj = super().__new__(cls, (payload["status"], capture_id))
        obj.captures = captures
        obj.issues = issues
        obj.source = source
        obj.order_id = order_id
        return obj


def reconcile_sale(sale, order, captures, issues):
    """Compare only one completed, explicitly final Capture with merchant terms."""
    if not sale:
        return {"code": "HISTORY", "summary": "Historical data insufficient — no merchant order link"}
    if issues or any(item["conflict"] for item in captures):
        return {"code": "REVIEW", "summary": "Evidence conflict or unsupported payment structure — manual review required"}
    if len(captures) > 1:
        return {"code": "UNSUPPORTED", "summary": "Unsupported payment structure — multiple captures"}
    if not captures:
        return {"code": "INCOMPLETE", "summary": "No independent Capture amount recorded — completion unconfirmed"}
    capture = captures[0]
    if (capture["final_capture"] != 1 or capture["status"] != "COMPLETED"
            or not capture["amount"] or not capture["currency"]
            or not capture.get("amount_pair_valid") or not capture.get("full_capture_verified")):
        return {"code": "INCOMPLETE", "summary": "Full Capture is unconfirmed — a valid provider order query/response must confirm the purchase unit total and Capture together"}
    if order["status"] in {"REFUNDED", "REVERSED", "DENIED"}:
        prefix = "Historical Capture comparison only. Current local status: " + order["status"] + ". "
        terminal = True
    elif order["status"] != "COMPLETED" or order["capture_state"] != "COMPLETED":
        return {"code": "INCOMPLETE", "summary": "Current payment completion is unconfirmed"}
    else:
        prefix, terminal = "", False
    if capture["currency"] != sale["currency"]:
        return {"code": "CURRENCY", "summary": prefix + "Capture currency differs from the merchant order; no conversion performed"}
    difference = Decimal(capture["amount"]) - Decimal(sale["amount"])
    result = {"difference": format(difference, ".2f"), "currency": sale["currency"]}
    if difference:
        direction = "above" if difference > 0 else "below"
        result.update(code="DIFFERENCE", summary=prefix + f"Saved Capture amount is {abs(difference):.2f} {sale['currency']} {direction} merchant expectation")
    else:
        result.update(code="TERMINAL" if terminal else "MATCH", summary=prefix + "Merchant amount and currency match the saved Sandbox Capture record")
    return result
