# PayGuard AI

A local prototype of a post-payment review assistant for small merchants, built with Streamlit and PayPal Sandbox. Select a saved payment to review its locally recorded status, linked notifications, and information that has not been recorded. Optional tools compare simulated assumptions using the existing rules. The interface introduces its purpose as: `Review a payment and its supporting records.`

**The rule score is not a fraud probability or PayPal's risk assessment.** The app does not calculate a baseline from real spending history, train a fraud detection model, or block payments before checkout. AI explains existing rule results; it does not calculate scores or make payment decisions.

## Features and scoring

- Sandbox OAuth, order creation, buyer approval, Capture, and SQLite persistence.
- A saved request key and amount for order-creation retries; duplicate-Capture protection and status checks when a Capture result is uncertain.
- Webhook signature verification, event deduplication, pending storage for unmatched events, and automatic processing when the corresponding order is saved.
- Rules-based review of completed orders, with an independent baseline-sensitivity comparison. Simulations change neither saved orders nor payments.
- Three English review cards: AI-generated Observations, fixed Limitations, and fixed Suggested checks. The AI request includes only the amount, currency, simulated baseline, and rule metrics, without order IDs, email addresses, timeline data, or PayPal credentials.

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

## First-use workflow

The default `Review payments` tab focuses on saved payments and supporting records. `Sandbox tools` is a separate tab for test-payment operations and authentication. No simulated spending baseline is required to view a payment.

1. Use `Select a payment` below the recent-payments list, then click **Review payment**.
2. Read **Payment overview** for the amount, currency, and payment status from the saved local record. This is not a live PayPal query. The overview does not show a rule score or require analysis.
   Use **Check payment against your expectation** below it: enter the expected amount and currency, then click **Check payment**. No rule analysis or AI call is needed.
3. The default-visible **AI rule explanation** entry after the overview explains simulated rules only, not payment verification. Without a valid rule result, **Open rule analysis** opens the optional analysis area without calculating or requesting AI. Read **Payment records** for the linked evidence, and the short notice explaining which occurrence times are not recorded. General manual-check suggestions are explicitly labeled as suggestions, not findings about the payment.
4. Expand **Record details** for full identifiers and timestamp definitions, or **Notification records** for the event table and local processing outcomes.
5. Optionally expand **Explore assumptions** to compare simulated baselines or run the existing rules. These tools are not required for record viewing.

If no payment records exist, the page explicitly directs you to `Sandbox tools`: enter a test amount, click `Create Sandbox Order`, approve it using a Sandbox buyer account, and Capture it there. Return to `Review payments` to open the saved record.

Changing the selector does not automatically open another payment. Until **Review payment** is clicked, a message names the pending selection and explicitly states that the overview still shows the previously opened payment. Its records, simulation inputs, rule results, and AI observation remain attached to that opened payment. A successful review click changes only the viewing target, never the current test-payment target, and does not mark a payment as reviewed or approved in the database.

The recent list shows up to 20 payments sorted by local update time, with amounts, currencies, saved statuses, and shortened references. Selector positions distinguish entries even when shortened references match. Full IDs remain available in collapsed details. Navy text, teal actions, rounded cards, and responsive layouts are retained; card groups stack at window widths of 900px or less.

Inside **Explore assumptions**, three tabs keep optional tools separate without nested disclosure panels:

- **Compare baselines:** the independent simulation controls and `Your comparison result` appear before the fixed example assumptions.
- **Rule review:** enter a **Simulated comparison baseline**, click **Calculate rule result**, and optionally request an AI explanation of those six rule inputs. This result is session-only, not a saved review history. The old summary's `Not analyzed` indicator stays inside these optional tools rather than the payment overview.
- **Hypothetical amount:** the original amount simulation, available after calculating a rule result, retains its original baseline and state keys.

The outer panel is collapsed by default. Its contents and tab contents are still rendered, so closing it or changing tabs does not erase inputs, rule results, or AI observations. Assumption tools remain limited to `COMPLETED` payments; records for every payment status can still be viewed.

In **Sandbox tools**, the existing `Create orders and payments` area retains creation, approval, Capture, same-attempt creation retries, and uncertain-result status checks. `Current payment order ID` identifies this separate action target. Authentication is inside a default-collapsed **Authentication** panel. Viewing records does not trigger these operations. A saved `COMPLETED` order shows `Payment completed`; returning from PayPal is not proof of approval or completed payment.

The proposed scoring-formula change is not implemented; the existing demo rules remain unchanged.

## Check a payment against your expectation

Open a payment, enter your expected amount and currency, and click **Check payment**. Expected values are user-provided and have not been externally verified. The compact result shows **Expected payment**, **Recorded order amount**, the same-currency difference, and a summary. Differences are described as a recorded amount below or above expectation, rather than proof of underpayment or overpayment.

The recorded amount and currency come from the locally saved order-creation details. They are **not an independently verified Capture amount**, net receipt, or bank settlement. The status is also a saved local value, not a fresh PayPal query. The check does not verify receipt of funds or change a payment.

- Supported currencies are CAD, USD and EUR, using exact decimal arithmetic with two-decimal precision. Positive, finite inputs with up to 26 integer digits are supported; extra nonzero decimal places are rejected rather than rounded. Trailing zeroes are accepted. Unsupported or invalid recorded amounts are not silently converted.
- With different currencies, the check reports the mismatch without subtracting amounts or performing currency conversion.
- Amount differences, currency mismatches, refunded/reversed states, and unconfirmed completion remain visible in the summary. An amount match with `APPROVED` is not proof of completed payment. `REFUNDED` and `REVERSED` take precedence over an older completed Capture record. `UNKNOWN` or `IN_PROGRESS` Capture states explicitly leave completion unconfirmed.
- Collapsed **Details** contains separate amount, currency and status checks, full identifiers, and the data-source limitations. A matching result only describes the saved order details and local status.
- Editing either expected input, opening another payment, changing the pending selection, or changing the underlying saved record clears the previous result. Click **Check payment** again to generate a result. While a changed selection awaits **Review payment**, checking is disabled. Each payment uses separate expected-input keys; results do not transfer to another payment.
- This tool is isolated from simulated baselines, rule results, AI observations and the Sandbox payment target. It writes no database records and makes no external requests.

## Baseline sensitivity comparison

Open a completed payment with **Review payment**, then expand **Explore assumptions** and use **Compare baselines**. No formal rule analysis or AI request is needed to use the comparison. The outer panel is collapsed by default. The comparison keeps its inputs rendered and explicitly separates **Payment facts**, **Simulated assumptions**, and **Rule results**:

**Payment evidence is unchanged. Only the simulated baseline changes.**

- **Payment facts:** the selected order's actual amount, currency, and saved payment status remain fixed.
- **Simulated assumptions:** demo baselines of 10, 5, and 2 use the order's currency. These are demonstration assumptions, not spending history or currency conversions. Enter a separate custom simulated baseline to add a custom scenario. The `Use baseline 10`, `Use baseline 5`, and `Use baseline 2` buttons include that currency in their labels and update only the independent custom scenario. The active preset is labeled explicitly; other manual values are labeled `Custom`. The controls state: `Simulation only — does not change or charge the payment.` Preset selections and manual values survive opening or closing the panel, and order-specific keys prevent inputs from being mixed between orders.
- **Rule results:** each scenario calls the existing scoring functions and displays its amount ratio, rule score, and **Rule-based level**. The current `Your comparison result` is displayed immediately below the controls, before `Compare example assumptions`. The latter contains the three fixed demonstration cards, side by side on wide screens and stacked on narrow screens. Changing the selected scenario does not change those fixed examples. Invalid input replaces the selected result with an inline warning instead of leaving a stale result visible.

For a fixed 10 CAD order:

| Demo baseline | Amount ratio | Rule score | Rule-based level |
| --- | --- | --- | --- |
| 10 CAD | 1x | 10/100 | Low Risk |
| 5 CAD | 2x | 50/100 | Medium Risk |
| 2 CAD | 5x | 80/100 | High Risk |

Different actual amounts can produce different results; the presets do not guarantee that all three levels will appear. Custom baselines must be finite positive numbers within the existing floating-point rules' supported range. Inputs that lose decimal precision when converted to that range are rejected rather than silently changed. Baselines and ratios retain round-trip floating-point precision, using scientific notation when needed, so a tiny positive baseline is not displayed as zero and a ratio just below a rule threshold is not rounded up to that threshold.

Comparison inputs use separate `sensitivity_*` widget keys scoped to the order ID, amount, and currency. Changes calculate locally without requesting AI or PayPal, writing to the database, changing the payment target, or replacing the current-session review baseline, result, summary result, or AI observation. There is no action to apply a comparison baseline to that review. The session review remains in its own section with its own controls.

The original hypothetical-amount What-if is retained in **Explore assumptions → Hypothetical amount**. It still requires a current-session rule analysis and uses that analysis's original baseline, not the comparison's custom baseline.

## AI review explanation cards

Application-calculated metrics remain in **Explore assumptions → Rule review**. The **AI rule explanation** entry is visible immediately after the payment overview, with a statement that it does not verify the payment or review notifications. The three bordered cards appear side by side on wide screens and stack vertically at window widths of 900px or less. The secondary hypothetical-amount What-if is available in the separate **Hypothetical amount** tab inside **Explore assumptions**.

| Card | Content source | Purpose |
| --- | --- | --- |
| Observations | Optional AI-generated text | A short qualitative explanation of the supplied comparison, without recalculating metrics or assigning a new score |
| Limitations | Fixed application text | Explain that the baseline is simulated, the score is not a fraud probability, and AI text may be inaccurate |
| Suggested checks | Fixed application text | Clearly labeled general suggestions for manual review, not findings about the payment or automatic actions |

The cards and manual generation button appear at that entry only when a valid analysis matches the opened payment, amount, currency, and current simulated baseline. Otherwise, a short message and **Open rule analysis** route the user to **Explore assumptions → Rule review**, with no automatic calculation or AI request. Payments that are not completed retain the existing analysis restriction. The entry explains only the original six analysis inputs, not the payment records. Fixed guidance is available without an API call. Click `Generate AI Explanation` to request an observation; a `Generating observation...` loading indicator is shown while waiting. AI is never requested automatically when selecting an order, analyzing it, rerunning the page, or changing What-if inputs. The SDK is configured with no automatic retries. If a request fails, the previous observation is cleared, the rule results and fixed cards remain, and the button can be clicked again for a manual retry.

Only six business inputs are sent: **order amount, currency, simulated baseline, amount ratio, rule score, and rule level**. What-if values, order/Capture IDs, payer information, payment status, and timeline records are not added. The model is instructed not to invent spending history, infer fraud, recalculate metrics, or issue recommendations or payment instructions. Limitations and manual-check suggestions are supplied by the app, not generated by the model. The explanation has no payment actions attached.

Changing the selected order or baseline, or running the analysis again, clears any previous observation. Empty, incomplete, malformed, or oversized responses are treated as errors rather than displayed as successful observations. These checks do not guarantee that model-generated prose is accurate; the application metrics remain the authoritative values. The current behavior is covered with mocked API responses, not a new live-model evaluation.

## Payment flow evidence

The main area shows three step cards: **Order created**, **Buyer approved**, and **Payment completed**, arranged horizontally on wide screens and vertically on narrow screens. Linked notifications have a teal status label; missing evidence and local-record-only evidence use neutral labels, not failure colors. Cards follow workflow order rather than reconstructed occurrence times. The current payment status is not used as independent event evidence.

- **Local order record only:** a saved order ID is available. An independent order-created event has not been retained.
- **Linked approval notification / Linked completion notification:** a corresponding notification is stored with an explicit reference to the selected order. The current order status or Capture ID alone does not produce either label.
- **No linked record:** no attributable notification is stored for that step. This does not establish that the step never happened.

Expand `Record details` to see the current local payment status, available Capture ID, and last local record update time. Order creation, buyer approval, and payment completion occurrence times display `Not recorded`, because provider timestamps are not persisted. An unavailable Capture ID or local timestamp is also marked explicitly. Definitions of timestamps, signature verification, and `LEGACY` records are kept in these collapsed details so the main summary stays brief.

Expand `Notification records` for the linked notifications. Rows are ordered by **Stored at (UTC)**, the local event insertion time, not by payment occurrence time. For new deliveries, this timestamp is recorded after signature verification; it is not the exact HTTP arrival time. **Local processed at (UTC)** is when the application decided whether to update the local order. Neither timestamp replaces a provider occurrence time or the order's separate last-update timestamp.

| Stored processing state | Displayed local outcome | Meaning |
| --- | --- | --- |
| `APPLIED` | Applied to local order | The event changed the local order state |
| `IGNORED` | No state change | The event did not change the local state; this is not a payment failure, and the specific reason was not retained |
| `PENDING` | Waiting for local processing | The saved event has not completed local processing |
| `LEGACY` | LEGACY — insufficient historical context | The old record lacks sufficient historical context; it is not used as independent step evidence |

Unlinked `LEGACY` records cannot be assigned to an order and are excluded from that order's event table. New deliveries are verified by the receiver before storage, but the database does not retain a separate verification-response audit. The evidence query uses a read-only SQLite connection and does not create or migrate missing or older databases. No database fields or payment writes were added for this view.

## Manual walkthrough

1. Complete configuration and start the services. In **Sandbox tools**, expand **Authentication** and use `Get Sandbox Access Token` if an authentication check is needed.
2. In that tools tab, enter a CAD amount, click `Create Sandbox Order`, approve it using the Sandbox buyer account, and return to **Sandbox tools** to click `Capture Approved Order`.
3. In **Review payments**, select a saved payment and click **Review payment**. Read its saved payment status and supporting records without entering any simulated baseline. Buyer approval alone does not mean payment is complete; missing notifications alone do not mean it failed.
4. For optional simulations on completed payments, expand **Explore assumptions**. Use **Compare baselines**, or enter a simulated comparison baseline in **Rule review** and click **Calculate rule result**. The **Hypothetical amount** tab then remains available.
5. With OpenAI configured, click `Generate AI Explanation` at the **AI rule explanation** entry after the overview to explain that rule result, not the payment notifications or comparison scenarios. This calls an external API and may incur charges.

If an order-creation result is uncertain, use `Retry Same Order Creation` to reuse the original key and amount. Click `Create New Sandbox Order` only when another order is explicitly intended. To recover an attempt after refreshing, retain the URL's `create_attempt` parameter and the local database. If Capture is uncertain, use `Check PayPal Order Status`; a timeout does not establish that payment failed.

For Webhook responses, `received: true` means the event was accepted after signature verification; `processed: true` means this request changed the order's state. `processed: false` can mean that the event is waiting for an order, is a duplicate, needs no same-state update, or was rejected by the state-transition rules. It does not mean signature verification failed.

## Offline tests

After installing dependencies, run this from the project root. Real credentials, running services, and a PayPal connection are not required:

```sh
python -B -m unittest discover -s tests -v
```

Tests use temporary SQLite databases, synthetic credentials, and mocked responses without operating on the project's real database. There are currently 93 test methods: 26 original regression tests, 10 workbench page tests, 9 payment-evidence tests, 10 AI-review tests, 6 order-summary tests, 13 baseline-sensitivity tests, 8 first-use tests, and 11 payment-expectation tests. Test counts do not represent real Sandbox verification runs. Page tests cover empty lists, different payment states, isolation between browsing and payment targets, clearing stale review results, preserving rule results during What-if changes or AI failures, English interface text, and accurate payment-completion notices. Evidence tests cover read-only queries, missing or older databases, separate time meanings, duplicate and out-of-order notifications, unlinked legacy records, and the distinction between current state and independent event evidence. AI-review tests cover the six-input boundary, invalid inputs, complete and incomplete responses, fixed card content, loading feedback, manual retries, and clearing stale observations without changing rule results or sending payment requests. Summary tests cover actual payment states, current-session results, fresh sessions, stale-review invalidation, escaped record text, and unchanged payment targeting. Sensitivity tests cover the demo outputs, custom inputs, threshold precision, invalid numeric values, order/currency/amount isolation, the optional hypothetical-amount tab, and unchanged review/AI/payment/database state with no external calls. First-use tests cover the empty-state route to Sandbox tools, explicit review activation, viewing every saved status without running rules, safe pending selections, unchanged payment targeting/data, hidden full identifiers, and the AI placement boundary. Payment-expectation tests cover exact decimal differences, currency mismatches, local-state warnings, refund/reversal precedence, uncertain Capture outcomes, input and record invalidation, pending selections, independent inputs, source disclosures, and unchanged rule/AI/payment/database state. The terminal may print learning examples from `risk.py` and environment warnings; use unittest's final `OK` or `FAILED` as the result.

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
