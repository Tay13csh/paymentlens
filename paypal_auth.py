"""PayPal Sandbox OAuth authentication helpers."""

from typing import Optional
import uuid

import requests
from payment_evidence import PaymentObservation, normalize_order, money


SANDBOX_TOKEN_URL = "https://api-m.sandbox.paypal.com/v1/oauth2/token"
CAPTURE_REQUEST_NAMESPACE = uuid.UUID("8e0192f4-4ad0-4b1f-b5bb-c4ba2d2b3680")


class PayPalAuthError(Exception):
    """Raised when PayPal Sandbox OAuth authentication fails safely."""


class PayPalOrderError(Exception):
    """Raised when a PayPal Sandbox order cannot be created safely."""


class PayPalCaptureUnknownError(PayPalOrderError):
    """Raised when a Capture request may have succeeded but was not confirmed."""


class PayPalWebhookError(Exception):
    """Raised when a PayPal webhook cannot be verified safely."""


def get_access_token(client_id: str, client_secret: str) -> str:
    """Request a PayPal Sandbox access token without exposing it in errors."""
    try:
        response = requests.post(
            SANDBOX_TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException:
        raise PayPalAuthError("Could not connect to PayPal Sandbox. Check your network and try again.") from None

    if not response.ok:
        raise PayPalAuthError(
            f"PayPal Sandbox authentication failed (HTTP {response.status_code}). "
            "Check your local Sandbox credentials."
        )

    try:
        response_data = response.json()
    except ValueError:
        raise PayPalAuthError("PayPal Sandbox returned an unreadable authentication response.") from None

    access_token = response_data.get("access_token") if isinstance(response_data, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise PayPalAuthError("PayPal Sandbox did not return a valid access token.")

    return access_token


def create_order(
    client_id: str, client_secret: str, amount: str, *, request_id: str
) -> tuple[str, str]:
    """Create a Sandbox order and return its ID and buyer approval URL."""
    if not isinstance(request_id, str) or not request_id:
        raise PayPalOrderError("A saved creation attempt is required before creating an order.")
    try:
        amount = money(amount)
    except ValueError as error:
        raise PayPalOrderError(str(error)) from None
    access_token = get_access_token(client_id, client_secret)

    try:
        response = requests.post(
            "https://api-m.sandbox.paypal.com/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "PayPal-Request-Id": request_id,
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {
                            "currency_code": "CAD",
                            "value": amount,
                        }
                    }
                ],
                "application_context": {
                    "return_url": "http://localhost:8501",
                    "cancel_url": "http://localhost:8501",
                    "user_action": "PAY_NOW",
                },
            },
            timeout=20,
        )
    except requests.RequestException:
        raise PayPalOrderError("Could not connect to PayPal Sandbox. Check your network and try again.") from None

    if not response.ok:
        raise PayPalOrderError(f"PayPal Sandbox could not create the order (HTTP {response.status_code}).")

    try:
        response_data = response.json()
    except ValueError:
        raise PayPalOrderError("PayPal Sandbox returned an unreadable order response.") from None

    if not isinstance(response_data, dict):
        raise PayPalOrderError("PayPal Sandbox returned an invalid order response.")

    order_id = response_data.get("id")
    links = response_data.get("links", [])
    approval_url = next(
        (
            link.get("href")
            for link in links
            if isinstance(link, dict) and link.get("rel") == "approve"
        ),
        None,
    ) if isinstance(links, list) else None

    if not isinstance(order_id, str) or not order_id or not isinstance(approval_url, str):
        raise PayPalOrderError("PayPal Sandbox did not return an order ID and approval link.")

    return order_id, approval_url


def get_capture_request_id(order_id: str) -> str:
    """Return a stable UUID idempotency key for this order's Capture operation."""
    return str(uuid.uuid5(CAPTURE_REQUEST_NAMESPACE, f"payguard-ai:capture:{order_id}"))


def _extract_capture_id(response_data: dict) -> Optional[str]:
    captures, _ = normalize_order(response_data, response_data.get("id"))
    return captures[0]["capture_id"] if len(captures) == 1 else None


def capture_order(client_id: str, client_secret: str, order_id: str) -> tuple[str, Optional[str]]:
    """Capture an approved Sandbox order and return its status and capture ID."""
    access_token = get_access_token(client_id, client_secret)

    try:
        response = requests.post(
            f"https://api-m.sandbox.paypal.com/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "PayPal-Request-Id": get_capture_request_id(order_id),
                "Prefer": "return=representation",
            },
            timeout=20,
        )
    except requests.RequestException:
        raise PayPalCaptureUnknownError(
            "Capture result is unconfirmed. Check the PayPal order status before trying again."
        ) from None

    if not response.ok:
        if response.status_code == 409 or response.status_code >= 500:
            raise PayPalCaptureUnknownError(
                "Capture result is unconfirmed. Check the PayPal order status before trying again."
            )
        raise PayPalOrderError(f"PayPal Sandbox could not capture the order (HTTP {response.status_code}).")

    try:
        response_data = response.json()
    except ValueError:
        raise PayPalCaptureUnknownError(
            "Capture result is unconfirmed. Check the PayPal order status before trying again."
        ) from None

    if not isinstance(response_data, dict):
        raise PayPalCaptureUnknownError(
            "Capture result is unconfirmed. Check the PayPal order status before trying again."
        )

    status = response_data.get("status")
    capture_id = _extract_capture_id(response_data)

    if not isinstance(status, str) or not status:
        raise PayPalCaptureUnknownError(
            "Capture result is unconfirmed. Check the PayPal order status before trying again."
        )

    if response_data.get("id") and response_data["id"] != order_id:
        raise PayPalCaptureUnknownError("Provider order identity differs. Capture remains unconfirmed.")
    return PaymentObservation(response_data, order_id, "CAPTURE_RESPONSE")


def get_order_status(client_id: str, client_secret: str, order_id: str) -> tuple[str, Optional[str]]:
    """Query the current PayPal order status without issuing a payment action."""
    access_token = get_access_token(client_id, client_secret)
    try:
        response = requests.get(
            f"https://api-m.sandbox.paypal.com/v2/checkout/orders/{order_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=20,
        )
    except requests.RequestException:
        raise PayPalOrderError("Could not confirm the PayPal order status. The Capture result remains unconfirmed.") from None

    if not response.ok:
        raise PayPalOrderError(
            f"Could not confirm the PayPal order status (HTTP {response.status_code}). "
            "The Capture result remains unconfirmed."
        )

    try:
        response_data = response.json()
    except ValueError:
        raise PayPalOrderError("PayPal returned an unreadable order status. The Capture result remains unconfirmed.") from None

    if not isinstance(response_data, dict):
        raise PayPalOrderError("PayPal returned an invalid order status. The Capture result remains unconfirmed.")

    status = response_data.get("status")
    if not isinstance(status, str) or not status:
        raise PayPalOrderError("PayPal returned no order status. The Capture result remains unconfirmed.")

    if response_data.get("id") and response_data["id"] != order_id:
        raise PayPalOrderError("Provider order identity differs. No status update was applied.")
    return PaymentObservation(response_data, order_id, "ORDER_QUERY")


def verify_webhook_signature(
    client_id: str,
    client_secret: str,
    webhook_id: str,
    transmission_headers: dict,
    webhook_event: dict,
) -> bool:
    """Ask PayPal to verify the signature for the received webhook event."""
    access_token = get_access_token(client_id, client_secret)
    verification_data = {
        "auth_algo": transmission_headers["auth_algo"],
        "cert_url": transmission_headers["cert_url"],
        "transmission_id": transmission_headers["transmission_id"],
        "transmission_sig": transmission_headers["transmission_sig"],
        "transmission_time": transmission_headers["transmission_time"],
        "webhook_id": webhook_id,
        "webhook_event": webhook_event,
    }
    try:
        response = requests.post(
            "https://api-m.sandbox.paypal.com/v1/notifications/verify-webhook-signature",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=verification_data,
            timeout=20,
        )
    except requests.RequestException:
        raise PayPalWebhookError("Could not connect to PayPal Sandbox to verify the webhook.") from None

    if not response.ok:
        raise PayPalWebhookError(f"PayPal Sandbox webhook verification failed (HTTP {response.status_code}).")

    try:
        response_data = response.json()
    except ValueError:
        raise PayPalWebhookError("PayPal Sandbox returned an unreadable verification response.") from None

    return isinstance(response_data, dict) and response_data.get("verification_status") == "SUCCESS"
