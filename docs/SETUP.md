# Setup and local configuration

[Home](../README.md) · [User guide](USER_GUIDE.md) · [Validation](VALIDATION.md)

## Installation

Run from the repository root on macOS/Linux with Python 3.9+ and pip:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The runtime dependencies are Streamlit, requests, FastAPI, Uvicorn, toml and `openai>=1.68.2,<2`. The SDK is imported at startup even without AI configuration. ngrok is a separate tool. Dependencies are not fully version-locked.

A separate temporary checkout and new virtual environment passed installation/import checks on Python 3.9.6, without system/user third-party packages or pip-cache reuse. Initial package download timed out; retrying the same install with a longer download timeout succeeded. This does not establish compatibility on every Python/OS combination. That macOS system Python emitted a LibreSSL/urllib3 compatibility warning; its fresh-environment test did not exercise real-service HTTPS. See [the full record](VALIDATION.md#fresh-environment-check).

## Credential-free examples

Do not create a secrets file for this path:

```sh
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Without configuration or payment-return/recovery context, the first view is **Example cases**. Select a case and open **View sample walkthrough**. Its label is **Sample explanation — not generated live**. Chat remains visible with a configuration notice and disabled sends. PayPal, OpenAI and Webhook settings are unnecessary for these examples.

## Local configuration

For optional live services, copy the placeholder example locally:

```sh
mkdir -p .streamlit
cp -n .streamlit/secrets.toml.example .streamlit/secrets.toml
```

`cp -n` preserves an existing file. Edit it locally; do not share, film or commit its contents. The example contains placeholders only. The application does not automatically load `.env` files.

| Setting | Used for |
| --- | --- |
| `openai.api_key` | Live current-payment chat and optional simulated-rule AI explanation |
| `openai.model` | A model available to your account and compatible with the selected call; replace the example placeholder |
| `paypal.client_id` | Sandbox merchant application client ID |
| `paypal.client_secret` | Secret for that same Sandbox application |
| `paypal.webhook_id` | Verified receiver delivery; this is not an order ID or event ID |

For live AI only, omit `[paypal]`; for PayPal only, omit `[openai]`. Example-case data remains simulated even when a real AI request explains it. Requests happen only on explicit sends and may incur charges. Local configuration presence is not proof of authentication or model access.

The payment assistant uses Responses structured JSON-schema output. The older optional rule-explanation call additionally uses `reasoning={"effort": "none"}`; not every model accepts that parameter. No model availability is guaranteed. Failures produce safe feedback without automatic retry or a sample-answer substitution.

Diagnostics report only missing, placeholder, format-problem or present/not-verified status. Missing OpenAI settings do not prevent saved-payment viewing or reconciliation. Missing PayPal credentials disable external payment controls while local records/examples remain accessible.

## Sandbox app

```sh
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Return/cancel URLs are fixed to `http://localhost:8501`, so the documented payment flow is local use on the same machine. If that port is occupied, do not start a second payment app on it. The credential-free isolation check used port 8504 to avoid disturbing the existing 8501 app; it did not validate payment redirects on 8504.

Choose **My Sandbox payments**. Three main-area choices switch directly between **Review payments**, **Sandbox tools** and **Test sales orders**; only the selected screen runs. See the [linked-payment flow](USER_GUIDE.md#linked-sandbox-payment).

## Webhook receiver and HTTPS

In a second terminal, activate the same environment and run:

```sh
source .venv/bin/activate
python -m uvicorn webhook_server:app --host 127.0.0.1 --port 8000
```

If an existing ngrok tunnel already forwards to port 8000, reuse its configuration. Otherwise install/authenticate ngrok separately, then run:

```sh
ngrok http 8000
```

Register `https://YOUR_NGROK_DOMAIN/webhooks/paypal` in the Sandbox merchant application. Subscribe to:

- `CHECKOUT.ORDER.APPROVED`
- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.DENIED`
- `PAYMENT.CAPTURE.REFUNDED`
- `PAYMENT.CAPTURE.REVERSED`

Save its Webhook ID locally. A changed tunnel domain requires updating the registered URL. The tunnel exposes the receiver, not the Streamlit app.

**Optionality boundary:** basic OAuth, create, Capture and query code paths do not require a Webhook ID; offline mocks confirmed this configuration boundary. No separate real Sandbox run with that ID deliberately absent has been confirmed. Signature-verified delivery requires merchant credentials plus the ID. Without them the receiver returns 503 before verification/storage; notification evidence and automatic refund/reversal updates may be unavailable. Do not disable signature verification to make a Simulator event pass.

## Health and offline tests

```sh
curl http://127.0.0.1:8501/_stcore/health
curl http://127.0.0.1:8000/health
python -B -m unittest discover -s tests -v
```

Expected health bodies are `ok` and `{"status":"ok"}`. Health only confirms service response, not credentials, model access or signature verification. Tests need no real configuration or running services. Learning examples from `risk.py` and environment warnings may appear; use unittest's final result.

Keep the SQLite database when upgrading; do not delete it to migrate. Schema migration is covered with temporary legacy databases, not every historical database. Back up runtime data separately: Git intentionally excludes credentials, databases/sidecars, logs and environments. A service restart clears in-memory chat and unsaved UI state; it does not intentionally delete saved records.
