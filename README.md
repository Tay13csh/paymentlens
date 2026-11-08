# PayGuard AI

A local prototype of a post-payment review assistant for small merchants, built with Streamlit and PayPal Sandbox. After a test payment is completed, the app compares the order amount with a **user-provided simulated spending baseline** and optionally generates an AI explanation of the rule results.

**The rule score is not a fraud probability or PayPal's risk assessment.** The app does not calculate a baseline from real spending history, train a fraud detection model, or block payments before checkout. AI explains existing rule results; it does not calculate scores or make payment decisions.

## Features and scoring

- Sandbox OAuth, order creation, buyer approval, Capture, and SQLite persistence.
- A saved request key and amount for order-creation retries; duplicate-Capture protection and status checks when a Capture result is uncertain.
- Webhook signature verification, event deduplication, pending storage for unmatched events, and automatic processing when the corresponding order is saved.
- Rules-based review of completed orders. What-if simulations change neither saved orders nor payments.
- Optional AI explanations in English. The request includes the amount, currency, simulated baseline, and rule metrics, without order IDs, email addresses, or PayPal credentials.

Amount ratio = order amount / simulated spending baseline:

| Amount ratio | Rule score | Displayed level |
| --- | --- | --- |
| Below 2 | 10/100 | Low Risk |
| At least 2 and below 5 | 50/100 | Medium Risk |
| At least 5 | 80/100 | High Risk |

## Validation status

- **The normal Sandbox flow has been manually verified**: local order creation, buyer approval, Capture, saved order records, and receipt of a real Webhook. This includes a notification returning `processed: false` when the order was already completed. These are the maintainer's manual checks, not an automated end-to-end check performed on every run.
- **Failure and edge cases are primarily covered by offline tests**: timeout retries, duplicate events, events arriving before orders, transaction rollback, capacity limits, legacy database migration, and protection of refunded or reversed states.
- **Webhook Simulator delivery has not yet been confirmed.** Offline mock events do not establish Simulator delivery or real signature verification. Do not disable signature verification for testing.

## Requirements and installation

The following commands target macOS or Linux and should be run from the project root. Python 3.9+ and pip are required; the existing local test environment uses Python 3.9. Dependencies are not fully version-locked, so run the tests to check compatibility in a new environment.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Dependencies include Streamlit, requests, FastAPI, Uvicorn, toml, and the OpenAI Python SDK. The SDK must be installed even when AI explanations are not used, because it is imported at application startup. ngrok is a separate tool and is not included in the Python dependencies.

## Local configuration

```sh
mkdir -p .streamlit
cp -n .streamlit/secrets.toml.example .streamlit/secrets.toml
```

`cp -n` leaves an existing configuration file untouched. Edit `.streamlit/secrets.toml` only on your own machine. Never commit or share real credentials.

| Field | Purpose |
| --- | --- |
| `paypal.client_id` | Client ID of the Sandbox merchant application |
| `paypal.client_secret` | Secret of the same Sandbox application |
| `paypal.webhook_id` | Webhook ID issued after registering the receiver URL for that application; not an event ID or order ID |
| `openai.api_key` | Optional; required only to generate AI explanations |
| `openai.model` | Replace with a model ID available to your account and compatible with the current API call |

Use credentials from a Sandbox merchant application and a separate Sandbox buyer account to approve orders. Do not use a real buyer account. Fill in the Webhook ID after registering the receiver URL as described below.

AI explanations use the Responses API with `reasoning={"effort": "none"}`; not every model supports this parameter. The model name in the example is a placeholder and must be replaced. If AI explanations are not needed, the entire `[openai]` section can be omitted. The app does not automatically load `.env` files.

The real configuration is excluded by `.gitignore`, while `secrets.toml.example` can be tracked in Git. Databases, database sidecar files, logs, and virtual environments are also excluded.

## Start the services

Use three terminals. In the first two, open the same project directory and run `source .venv/bin/activate`. Both services use `payguard.db` beside the project source files.

### 1. Streamlit app

```sh
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open http://localhost:8501 . The PayPal return and cancel URLs are currently fixed to this address, so these instructions assume local use on the same computer.

### 2. Webhook receiver

```sh
python -m uvicorn webhook_server:app --host 127.0.0.1 --port 8000
```

Health checks:

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8501/_stcore/health
```

The expected responses are `{"status":"ok"}` and `ok`, respectively. A healthy endpoint confirms that the service can respond; it does not verify credentials, PayPal connectivity, or signature verification.

### 3. ngrok HTTPS tunnel

If a tunnel already forwards to local port 8000, reuse it without changing its configuration. Otherwise, install ngrok, complete its local authentication setup, and run:

```sh
ngrok http 8000
```

Append `/webhooks/paypal` to the displayed HTTPS domain, for example `https://YOUR_NGROK_DOMAIN/webhooks/paypal`. Register that full receiver URL in the PayPal Sandbox merchant application and subscribe to:

- `CHECKOUT.ORDER.APPROVED`
- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.DENIED`
- `PAYMENT.CAPTURE.REFUNDED`
- `PAYMENT.CAPTURE.REVERSED`

Save the resulting Webhook ID in the local configuration. If the tunnel domain changes, update the registered receiver URL as well. This tunnel exposes the Webhook receiver, not the Streamlit app.

## Order workbench

On wide screens, recent orders and the selected-order review appear on the left, with order creation and payment controls on the right. At window widths of 900px or less, the sections stack vertically: browsing and review first, payment controls below. The order table can scroll horizontally instead of squeezing both columns together.

- **Select an order:** use `View order` below the `Recent orders` table. The list shows up to 20 records sorted by local update time, including amount, currency, and payment status. Risk levels are not persisted and are not shown in the list.
- **View results:** in `Selected order review`, enter a simulated spending baseline and click `Analyze Selected Order` to see rule metrics, What-if comparisons, and optional AI explanations. Only `COMPLETED` orders can be analyzed. Results belong to the current session and are not a saved review history. Changing the order or baseline clears the previous analysis and AI explanation.
- **Manage payments:** `Create orders and payments` contains order creation, approval, Capture, same-attempt creation retries, and status checks for uncertain results. `Current payment order ID` identifies the payment target. Browsing another order on the left neither changes that target nor sends a request.
- **Access developer tools:** expand `Developer tools` in the sidebar to run the Sandbox OAuth authentication check. This section is collapsed by default.
- **Timeline placeholder:** `Payment record and timeline (preview)` at the bottom shows the selected order's available Capture ID and local update time. Creation, approval, and payment completion times display `Not recorded`. The local update time is not a payment completion timestamp.

The workbench uses the existing payment, database, scoring, AI, and Webhook backend logic. Other planned enhancements are not implemented in this version.

## Manual walkthrough

1. Complete the configuration and start the services. Use `Get Sandbox Access Token` to check Sandbox authentication if needed.
2. Enter an amount in CAD, click `Create Sandbox Order`, follow the approval link using the Sandbox buyer account, and click `Capture Approved Order`.
3. Wait for the local order to show `COMPLETED` and a Capture ID. Select the completed order, enter a simulated spending baseline, and click `Analyze Selected Order`.
4. Use What-if to compare hypothetical amounts. With OpenAI configured, click `Generate AI Explanation` for an explanation. This calls an external API and may incur charges.

If an order-creation result is uncertain, use `Retry Same Order Creation` to reuse the original key and amount. Click `Create New Sandbox Order` only when another order is explicitly intended. To recover an attempt after refreshing, retain the URL's `create_attempt` parameter and the local database. If Capture is uncertain, use `Check PayPal Order Status`; a timeout does not establish that payment failed.

For Webhook responses, `received: true` means the event was accepted after signature verification; `processed: true` means this request changed the order's state. `processed: false` can mean that the event is waiting for an order, is a duplicate, needs no same-state update, or was rejected by the state-transition rules. It does not mean signature verification failed.

## Offline tests

After installing dependencies, run this from the project root. Real credentials, running services, and a PayPal connection are not required:

```sh
python -B -m unittest discover -s tests -v
```

Tests use temporary SQLite databases, synthetic credentials, and mocked responses without operating on the project's real database. There are currently 32 test methods: 26 existing regression tests and 6 workbench page tests. Test counts do not represent real Sandbox verification runs. Page tests cover empty lists, different payment states, isolation between browsing and payment targets, clearing stale review results, and preserving rule results during What-if changes or AI failures. The terminal may print learning examples from `risk.py` and environment warnings; use unittest's final `OK` or `FAILED` as the result.

## Current limitations

- This is a local learning prototype without multi-user isolation or a production deployment setup. Payment creation is configured only for Sandbox, CAD, and local return URLs.
- Scores use manually defined rules, the simulated baseline is not real spending history, and AI text is not a fraud assessment.
- Webhook storage retains event IDs, event types, order/Capture references, processing states, and timestamps. It does not retain full requests, payer details, or signature headers, so it is not a complete signature-verification audit snapshot.
- Pending events are capped at 1,000, total events at 100,000, and stored string fields at 255 characters. Capacity failures return 503 rather than silently deleting pending events. Automatic cleanup and alerting are not implemented.
- Legacy events retain their deduplication identities and are marked `LEGACY`; missing references cannot be reconstructed from those records. The event-matching and state models do not cover every payment or refund scenario.
- Saved creation attempts cannot guarantee deduplication for retries beyond PayPal's idempotency-key retention period. Losing the database or attempt URL also affects recovery.
- Dependencies are not fully version-locked. Local Git backups exclude credentials and runtime data and do not replace a disk backup.

## Main files

| File | Responsibility |
| --- | --- |
| `app.py` | Streamlit interface and user flows |
| `paypal_auth.py` | Sandbox OAuth, Orders, Capture, order queries, and remote signature verification |
| `order_store.py` | SQLite, creation attempts, state transitions, and pending-event processing |
| `webhook_server.py` | FastAPI health check and Webhook receiver |
| `risk.py` | Rule scoring and early learning examples |
| `ai_explanation.py` | Optional AI explanations |
| `tests/` | Offline regression tests |
