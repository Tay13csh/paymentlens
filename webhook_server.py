"""PayPal Sandbox webhook receiver with signature verification."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Dict

import toml
from fastapi import FastAPI, HTTPException, Request

from order_store import InvalidWebhookEventError, WebhookStorageFullError, record_webhook_event
from paypal_auth import PayPalAuthError, PayPalWebhookError, verify_webhook_signature


PROJECT_ROOT = Path(__file__).resolve().parent
SECRETS_PATH = PROJECT_ROOT / ".streamlit" / "secrets.toml"
app = FastAPI(title="PayGuard AI PayPal Webhook Receiver")


def load_paypal_settings() -> Dict[str, str]:
    if not SECRETS_PATH.is_file():
        raise ValueError("Local PayPal settings are missing.")
    settings = toml.load(SECRETS_PATH).get("paypal", {})
    client_id = settings.get("client_id")
    client_secret = settings.get("client_secret")
    webhook_id = settings.get("webhook_id")
    if not all(isinstance(value, str) and value for value in (client_id, client_secret, webhook_id)):
        raise ValueError("Required PayPal settings are missing.")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "webhook_id": webhook_id,
    }


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/paypal")
async def receive_paypal_webhook(request: Request) -> Dict[str, bool]:
    raw_body = await request.body()
    if len(raw_body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    try:
        event = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook event.")

    header_names = {
        "auth_algo": "paypal-auth-algo",
        "cert_url": "paypal-cert-url",
        "transmission_id": "paypal-transmission-id",
        "transmission_sig": "paypal-transmission-sig",
        "transmission_time": "paypal-transmission-time",
    }
    transmission_headers = {key: request.headers.get(name) for key, name in header_names.items()}
    if not all(transmission_headers.values()):
        raise HTTPException(status_code=400, detail="Required PayPal signature headers are missing.")

    try:
        settings = load_paypal_settings()
    except (OSError, ValueError, toml.TomlDecodeError):
        raise HTTPException(status_code=503, detail="PayPal webhook settings are not configured.") from None

    try:
        verified = await asyncio.to_thread(
            verify_webhook_signature,
            settings["client_id"],
            settings["client_secret"],
            settings["webhook_id"],
            transmission_headers,
            event,
        )
    except (PayPalAuthError, PayPalWebhookError):
        raise HTTPException(status_code=502, detail="PayPal webhook verification is unavailable.") from None

    if not verified:
        raise HTTPException(status_code=400, detail="PayPal webhook signature is invalid.")

    try:
        processed = record_webhook_event(event)
    except InvalidWebhookEventError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except (WebhookStorageFullError, sqlite3.Error):
        raise HTTPException(status_code=503, detail="Webhook event could not be stored. Retry later.") from None
    return {"received": True, "processed": processed}
