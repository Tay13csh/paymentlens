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
- **The user manually verified the linked Handmade mug Sandbox payment**: the merchant expectation of 10 CAD matched the independently returned Capture amount and currency, and the saved result remained after a page refresh. This is a reported manual check, not an automated end-to-end test or confirmation of bank settlement.
- **Failure and edge cases are primarily covered by offline tests**: timeout retries, duplicate events, events arriving before orders, transaction rollback, capacity limits, legacy database migration, and protection of refunded or reversed states.
- **Full wide- and narrow-screen acceptance remains pending.**
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

The state-controlled **Workspace** navigation switches between `Review payments`, `Sandbox tools` and `Test sales orders`. `Review payments` focuses on saved payments and supporting records; `Sandbox tools` keeps test-payment operations and authentication separate. Only the active section renders. Review inputs and session results are preserved when navigating away. No simulated spending baseline is required to view a payment.

1. Use `Select a payment` below the recent-payments list, then click **Review payment**.
2. Read **Payment overview** for the amount, currency, and payment status from the saved local record. This is not a live PayPal query. The overview does not show a rule score or require analysis.
   For a linked merchant sales order, **Merchant reconciliation** automatically compares its saved merchant terms with independent Capture evidence. Only unlinked historical orders use **Check payment against your expectation**: enter an expected amount and currency, then click **Check payment** to compare against the recorded order amount. Neither path requires rule analysis or AI.
3. The default-visible **AI rule explanation** entry after the overview explains simulated rules only, not payment verification. Without a valid rule result, **Open rule analysis** expands **Simulated rule analysis** in that same AI area without calculating or requesting AI. Read **Payment records** for the linked evidence, and its reminder that missing notifications do not mean payment failed. Timestamp definitions remain in details.
4. Expand **Record details** for full identifiers and timestamp definitions, or **Notification records** for the event table and local processing outcomes.
5. Optionally expand **Explore assumptions** to compare simulated baselines or explore a hypothetical amount. These tools are not required for record viewing.

If no payment records exist, the page explicitly directs you to `Sandbox tools`: enter a test amount, click `Create Sandbox Order`, approve it using a Sandbox buyer account, and Capture it there. Return to `Review payments` to open the saved record.

The dropdown retains its selection by stable order ID when records change order, including when that payment leaves the latest 20 records. If it no longer exists, the dropdown clears and asks for explicit reselection; Review payment is disabled until a choice is made. Changing the selector does not automatically open another payment. Until **Review payment** is clicked, a message names the pending selection and explicitly states that the overview still shows the previously opened payment. Its records, simulation inputs, rule results, and AI observation remain attached to that opened payment. A successful review click changes only the viewing target, never the current test-payment target, and does not mark a payment as reviewed or approved in the database.

The recent list shows up to 20 payments sorted by local update time, with associated merchant descriptions, recorded order amounts, currencies, saved statuses, review reasons and shortened references. Selector positions distinguish entries even when shortened references match. Full IDs remain available in collapsed details. Navy text, teal primary actions and selected presets, outlined secondary actions, distinct keyboard focus and disabled states, rounded cards, and responsive layouts are retained; card groups stack at window widths of 900px or less.

Inside **AI rule explanation**, the single **Simulated rule analysis** panel keeps the workflow together: set a simulated comparison baseline → click **Calculate rule result** → optionally click **Generate AI Explanation**. Application metrics, AI output, loading feedback and errors appear in that same panel. Editing the baseline or opening another payment clears stale rule results and observations. Results belong to the current session and are not saved review history.

Inside **Explore assumptions**, two tabs retain the other optional tools:

- **Compare baselines:** the independent simulation controls and `Your comparison result` appear before the fixed example assumptions.
- **Hypothetical amount:** the original amount simulation, available after calculating a rule result, retains its original baseline and state keys.

The outer panel is collapsed by default. Its contents and tab contents are still rendered, so closing it or changing tabs does not erase inputs, rule results, or AI observations. Assumption tools remain limited to `COMPLETED` payments; records for every payment status can still be viewed.

In **Sandbox tools**, the existing `Create orders and payments` area retains creation, approval, Capture, same-attempt creation retries, and uncertain-result status checks. `Current payment order ID` identifies this separate action target. Authentication is inside a default-collapsed **Authentication** panel. Viewing records does not trigger these operations. A saved `COMPLETED` order shows `Payment completed`; returning from PayPal is not proof of approval or completed payment.

The proposed scoring-formula change is not implemented; the existing demo rules remain unchanged.

## Recent descriptions and payment filters

**All / Matched / Needs attention / Insufficient information** always applies to the **most recent 20 saved payments**, ordered by local record update time (order ID breaks timestamp ties). Counts exclude older records and retained selections outside that range. Category counts stay fixed for that snapshot and do not change with search or reason filters. The separate `Showing N of M in this view` count describes the visible results. A zero-result message means no payments match these filters within this view; older history was not checked. `Show all in this view` resets all filters.

Descriptions come only from the associated local merchant sales order. A selector can show `Handmade mug · 10.00 CAD · …AB12CD`, with a position number to distinguish duplicate descriptions and matching reference suffixes. Full PayPal order IDs remain the selection values and are available in details. `No linked merchant order` and `Description not recorded` identify missing data explicitly. Descriptions are escaped/literal display text, never parsed into payment identities or amounts. List and overview amounts are recorded order amounts, not independently verified Capture totals.

The existing reconciliation function supplies both its original conclusion and structured reasons to the list, filter and selected reconciliation. Reasons distinguish **Amount difference**, **Currency mismatch**, **Capture evidence incomplete**, **Payment completion unconfirmed**, **Evidence conflict**, **Unsupported payment structure**, **Historical data insufficient**, and local **Refunded / Reversed / Denied** states. Reasons can coexist. Historical gaps are not confirmed discrepancies; none of these labels are a fraud score or a blanket payment-failure finding. Categories organize the existing result without changing its conclusion: known amount/currency differences, conflicts, unsupported structures, and local refunded/reversed/denied states take priority as **Needs attention**, even with missing evidence. **Matched** requires the existing `MATCH` conclusion and no attention reason. Remaining `HISTORY`/`INCOMPLETE` results are **Insufficient information**; unknown non-matching conclusions remain visible under Needs attention. `DENIED` means **Payment denied**, not a chargeback or dispute. Matched does not establish transaction safety, bank settlement, or absence of further manual checks.

Search matches merchant descriptions, full PayPal order IDs or linked merchant sales-order IDs, case-insensitively, within the recent 20 only. Needs attention supports multiple reason filters using **any selected reason**; a payment can display several known reasons. Earlier reconciliation exits remain authoritative: a conflicting amount is not newly classified as an amount difference. `Clear filters` returns to All and clears search/reasons while retaining valid selections, opened details and review inputs. Category controls wrap on narrow screens and identify the selected category. Search, reasons and categories survive Workspace navigation; reason choices apply only in Needs attention.

One read-only SQLite transaction supplies the complete view, associated descriptions, evidence, conflict observations, and opened-payment reconciliation. Filtering does not initialize or migrate the database, make provider/AI requests, or change payment data. Missing initial databases remain uncreated; an unavailable or older incompatible schema shows an explicit error rather than a healthy count. The snapshot can become stale after reading; no automatic refresh or retry is added.

A still-existing selected payment remains selected by its full ID when the filter changes. It is labeled **Outside current filter** or **Outside recent 20** when applicable and is not counted among filtered results. Retained opened details have the same scope warnings when necessary. Pending selection and opened payment remain separate until **Review payment** is clicked, and neither filter nor description changes the Sandbox payment target. Deleted payments clear with an explicit reselection message. The chosen filter and review inputs survive Workspace navigation.

## Check a payment against your expectation

For an unlinked historical payment, enter your expected amount and currency and click **Check payment**. Linked merchant sales orders use automatic **Merchant reconciliation** instead. Expected values are user-provided and have not been externally verified. The compact result shows **Expected payment**, **Recorded order amount**, the same-currency difference, and a summary. Differences are described as a recorded amount below or above expectation, rather than proof of underpayment or overpayment.

The recorded amount and currency come from the locally saved order-creation details. They are **not an independently verified Capture amount**, net receipt, or bank settlement. The status is also a saved local value, not a fresh PayPal query. The check does not verify receipt of funds or change a payment.

- Supported currencies are CAD, USD and EUR, using exact decimal arithmetic with two-decimal precision. Positive, finite inputs with up to 26 integer digits are supported; extra nonzero decimal places are rejected rather than rounded. Trailing zeroes are accepted. Unsupported or invalid recorded amounts are not silently converted.
- With different currencies, the check reports the mismatch without subtracting amounts or performing currency conversion.
- Amount differences, currency mismatches, refunded/reversed states, and unconfirmed completion remain visible in the summary. An amount match with `APPROVED` is not proof of completed payment. `REFUNDED` and `REVERSED` take precedence over an older completed Capture record. `UNKNOWN` or `IN_PROGRESS` Capture states explicitly leave completion unconfirmed.
- Collapsed **Details** contains separate amount, currency and status checks, full identifiers, and the data-source limitations. A matching result only describes the saved order details and local status.
- Editing either expected input, opening another payment, changing the pending selection, or changing the underlying saved record clears the previous result. Click **Check payment** again to generate a result. While a changed selection awaits **Review payment**, checking is disabled. Each payment uses separate expected-input keys; results do not transfer to another payment.
- This tool is isolated from simulated baselines, rule results, AI observations and the Sandbox payment target. It writes no database records and makes no external requests.

## Test merchant orders and Capture reconciliation

This addition is a **Sandbox-only, CAD-only** sales-to-payment workflow. It is not a deployed merchant platform, an accounting integration, a production settlement checker, or a fraud model. Existing rule scoring and AI input boundaries are unchanged. The AI explanation of expectation-check results remains deferred.

### Start a linked test sale

1. Restart both Python services after this upgrade. Preserve the existing SQLite database; do not delete it to migrate. Back up runtime data separately before using a new version. Schema additions are transactional and idempotent, but migration has only been tested on temporary legacy databases in this development run.
2. Open **Test sales orders**. Enter a non-personal test description and a positive CAD amount (up to two decimal places; maximum 999999999.99), then **Save test sales order**. CAD is fixed in this version. Saved terms cannot be edited; a database trigger also protects the amount, currency, and description.
3. Select that sale and explicitly click **Create or resume linked PayPal order**. The sale terms are copied into one durable creation attempt under a write transaction before a provider request. A database unique index prevents a second attempt for the same sale. Retrying or restarting resumes that attempt and its original request key; no new request is sent on page render. An existing provider order cannot be rebound to a second sale or replaced by a different returned order ID.
4. Open **Sandbox tools**, approve the linked order with the Sandbox buyer, and use the existing Capture button once. If you lost the current payment target, select the sale and use **Open payment in Sandbox tools**; this selects the existing linked order, restores its original saved creation-attempt key and approval link, and immediately switches Workspace to Sandbox tools. The active PayPal order and associated sales-order reference are displayed there. Navigation does not create an attempt or send a provider request; missing associations/attempts produce an error without changing the target. The viewing/review target remains separate. Refreshing with the saved `create_attempt` URL reopens Sandbox tools and restores that attempt without resending it. Returning from PayPal does not create a merchant association.
5. In **Review payments**, open the linked payment. **Merchant reconciliation** automatically reads its immutable sales-order expectation and independent saved Capture fields. A linked sale does not ask you to re-enter an expectation. Unlinked historical orders retain the existing manual local-order comparison, clearly labeled as such.
6. If evidence is incomplete, **Refresh Capture evidence from PayPal** explicitly requests order details and saves the returned Capture fields. This is a provider GET plus authentication; it can use local credentials, but cannot issue a Capture. It never runs automatically. Restart the Webhook receiver as well so incoming verified events use the new storage code.

### Evidence and reconciliation rules

- Capture POST requests ask for `Prefer: return=representation`; an order-level COMPLETED response or Capture ID alone is not an independent monetary record. Orders-query results and signature-verified completion notifications can add Capture fields. Amount and currency are accepted only as a complete valid pair from the same observation; invalid partial pairs cannot be combined. No additional PayPal calls were performed during implementation.
- Only whitelisted Capture fields are saved: identity, associated order, amount/currency pair, Capture status, explicit final flag, provider purchase-unit amount/currency, full-Capture proof, provider creation time, observation source and local insertion time. Provider creation time is not called settlement or payment-completion time. Full provider responses, payer data, signature headers, credentials, fees and net proceeds are not retained.
- Webhook pending events persist the same minimal fields until a local order exists. Evidence merging and allowed status transitions occur in the same transaction. Same-state notifications may add evidence while still returning `processed: false`, which continues to describe only the order-state change.
- Reconciliation reads merchant terms, local payment status, Capture/full-total proof, conflict markers and observations in one explicit SQLite read transaction. The reconciliation area uses that same snapshot rather than the earlier browser order. A consistent snapshot may already be older than a concurrently committed refund or evidence update; it is not guaranteed to be the latest and does not trigger automatic retries or refreshes. Concurrency tests use isolated WAL databases to allow writes during the read; the application database journal mode is unchanged.
- A positive result requires exactly one distinct Capture, status COMPLETED, an explicit final flag, a valid amount/currency pair, no unsupported-structure or conflict markers, and a currently completed local payment state. In addition, one valid Capture response or order query must show exactly one purchase unit and one Capture with equal amounts and currencies, both completed. A final flag alone is insufficient; a completion Webhook alone cannot prove that full total. Missing order totals remain unconfirmed until an explicit valid query supplies them. The result means merchant terms match saved Sandbox Capture evidence, **not bank settlement, net funds, or delivery**. CAD-only sales can still detect an unexpected non-CAD Capture; there is no conversion.
- Same-currency amounts are compared using Decimal directly from strings. Differences are displayed without asserting a customer underpaid. A final flag is necessary, not a claim that every possible provider lifecycle is supported. Multiple purchase units, multiple Captures, partial or unconfirmed finality, and missing fields never yield a green match. Multiple Capture facts are retained, not silently aggregated or reduced to the first item.
- Conflicting amount, currency, finality, or terminal Capture status is retained as a conservative manual-review condition rather than silently overwritten. Immutable, deduplicated observations retain both monetary pairs, sources, provider creation times and local insertion times in **Reconciliation evidence**; invalid monetary pairs are stored as unavailable. Identical observations retain their first insertion time. Previously discarded conflict values cannot be reconstructed. A Capture ID cannot be moved between orders. Automatic conflict resolution is not implemented.
- REFUNDED/REVERSED local status remains protected against late completion responses. The historical Capture value may still be filled, but the result clearly shows the current terminal state. Refund-resource amounts and IDs are never treated as original Capture amounts. A verified refund or reversal without an order reference is durably saved as PENDING when it has a valid Capture reference (refunds may use an allowed Sandbox Capture link). It resolves only through a unique exact local Capture binding. Capture responses, queries, completion notifications and legacy Capture-ID writebacks replay those pending terminal events atomically. Ambiguous bindings remain pending; no amount-based guessing, expiry deletion, polling or external lookup is performed. Partial-refund accounting and all arbitrary refund payload variants are outside this prototype.
- Old orders do not receive fabricated sales associations or Capture amounts. Old LEGACY notifications remain unchanged; they are not reconstructed from the order request. Legacy results show insufficient history. Migration preserves existing rows but does not certify older monetary pairs or full-Capture flags; a fresh valid provider query/response is required before those rows can match. An explicit new provider query can add independently returned Capture facts but cannot invent merchant terms.
- Existing idempotency keys still depend on provider retention. Do not assume an unresolved request can be safely retried indefinitely; uncertain old attempts need manual reconciliation with the provider. No automatic polling, auto-capture, refunds, inventory, shipping, invoice integration, multi-user authentication, CSV import, additional AI calls or synthetic discrepancy page is added.

### Verification boundary

The development run used temporary databases, synthetic API responses, and mocked signature decisions. Two regression tests first reproduced false MATCH outcomes from complementary invalid money fields and a final Capture below the provider order total, then passed after the fixes. Tests cover immutable terms, database one-to-one constraints, concurrent attempt reservation, timeout/restart recovery, Capture/query/Webhook normalization, early notifications, deduplication, atomic rollback, refund/reversal races, malformed money, missing/partial/multiple captures, conflicting evidence, old-schema migration, capacity rejection, and a simulated merchant-to-Capture page journey. These regression results are **offline coverage**, distinct from the user-reported manual Sandbox acceptance: the Handmade mug merchant expectation of 10 CAD matched its independently returned Capture amount and currency, and the saved result persisted after a page refresh. That check does not establish bank settlement or validate every provider payload and failure path. Abnormal scenarios remain primarily covered by offline tests; Webhook Simulator delivery is unconfirmed, and full wide- and narrow-screen acceptance is still pending.

Official payload references: [Orders capture](https://developer.paypal.com/api/orders/v2/orders-capture) and [Orders details](https://developer.paypal.com/api/orders/v2/orders-get).

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

Application-calculated metrics appear in **AI rule explanation → Simulated rule analysis**, directly before the manual AI generation button and explanation cards. The **AI rule explanation** entry is visible immediately after the payment overview, with a statement that it does not verify the payment or review notifications. The three bordered cards appear side by side on wide screens and stack vertically at window widths of 900px or less. The secondary hypothetical-amount What-if is available in the separate **Hypothetical amount** tab inside **Explore assumptions**.

| Card | Content source | Purpose |
| --- | --- | --- |
| Observations | Optional AI-generated text | A short qualitative explanation of the supplied comparison, without recalculating metrics or assigning a new score |
| Limitations | Fixed application text | Explain that the baseline is simulated, the score is not a fraud probability, and AI text may be inaccurate |
| Suggested checks | Fixed application text | Clearly labeled general suggestions for manual review, not findings about the payment or automatic actions |

The cards and manual generation button appear at that entry only when a valid analysis matches the opened payment, amount, currency, and current simulated baseline. Otherwise, a short message and **Open rule analysis** expand the existing controls in place under **AI rule explanation**, with no automatic calculation or AI request. Payments that are not completed retain the existing analysis restriction. The entry explains only the original six analysis inputs, not the payment records. Fixed guidance is available without an API call. Click `Generate AI Explanation` to request an observation; a `Generating observation...` loading indicator is shown while waiting. AI is never requested automatically when selecting an order, analyzing it, rerunning the page, or changing What-if inputs. The SDK is configured with no automatic retries. If a request fails, the previous observation is cleared, the rule results and fixed cards remain, and the button can be clicked again for a manual retry.

Only six business inputs are sent: **order amount, currency, simulated baseline, amount ratio, rule score, and rule level**. What-if values, order/Capture IDs, payer information, payment status, and timeline records are not added. The model is instructed not to invent spending history, infer fraud, recalculate metrics, or issue recommendations or payment instructions. Limitations and manual-check suggestions are supplied by the app, not generated by the model. The explanation has no payment actions attached.

Changing the selected order or baseline, or running the analysis again, clears any previous observation. Empty, incomplete, malformed, or oversized responses are treated as errors rather than displayed as successful observations. These checks do not guarantee that model-generated prose is accurate; the application metrics remain the authoritative values. The current behavior is covered with mocked API responses, not a new live-model evaluation.

## Payment flow evidence

The main area shows three step cards: **Order created**, **Buyer approved**, and **Payment completed**, arranged horizontally on wide screens and vertically on narrow screens. Linked notifications have a teal status label; missing evidence and local-record-only evidence use neutral labels, not failure colors. Cards follow workflow order rather than reconstructed occurrence times. The current payment status is not used as independent event evidence.

- **Local order record only:** a saved order ID is available. An independent order-created event has not been retained.
- **Linked approval notification / Linked completion notification:** a corresponding notification is stored with an explicit reference to the selected order. The current order status or Capture ID alone does not produce either label.
- **No linked record:** no attributable notification is stored for that step. This does not establish that the step never happened.

Expand `Record details` to see the current local payment status, available Capture ID, and last local record update time. Order creation, buyer approval, and payment completion occurrence times in the three-step view remain `Not recorded` where no confirmed step time is available. Capture evidence separately retains provider creation time when supplied, visible under **Reconciliation evidence**; this is not a payment-completion or bank-settlement timestamp and is not substituted for missing step times. An unavailable Capture ID or local timestamp is also marked explicitly. Definitions of timestamps, signature verification, and `LEGACY` records are kept in these collapsed details so the main summary stays brief.

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
2. In that tools section, enter a CAD amount, click `Create Sandbox Order`, approve it using the Sandbox buyer account, and return to **Sandbox tools** to click `Capture Approved Order`.
3. In **Review payments**, select a saved payment and click **Review payment**. Read its saved payment status and supporting records without entering any simulated baseline. Buyer approval alone does not mean payment is complete; missing notifications alone do not mean it failed.
4. For optional simulations on completed payments, expand **Explore assumptions**. Use **Compare baselines**. For the rule/AI workflow, click **Open rule analysis** in the AI area above, set a simulated baseline and click **Calculate rule result**. The **Hypothetical amount** tab uses that result.
5. With OpenAI configured, click `Generate AI Explanation` at the **AI rule explanation** entry after the overview to explain that rule result, not the payment notifications or comparison scenarios. This calls an external API and may incur charges.

If an order-creation result is uncertain, use `Retry Same Order Creation` to reuse the original key and amount. Click `Create New Sandbox Order` only when another order is explicitly intended. To recover an attempt after refreshing, retain the URL's `create_attempt` parameter and the local database. If Capture is uncertain, use `Check PayPal Order Status`; a timeout does not establish that payment failed.

For Webhook responses, `received: true` means the event was accepted after signature verification; `processed: true` means this request changed the order's state. `processed: false` can mean that the event is waiting for an order, is a duplicate, needs no same-state update, or was rejected by the state-transition rules. It does not mean signature verification failed.

## Offline tests

After installing dependencies, run this from the project root. Real credentials, running services, and a PayPal connection are not required:

```sh
python -B -m unittest discover -s tests -v
```

Tests use temporary SQLite databases, synthetic credentials, and mocked responses without operating on the project's real database. Run unittest to obtain the current count; new merchant-reconciliation regressions are in `tests/test_merchant_reconciliation.py`. `tests/test_payment_view.py` covers descriptions and escaping, duplicate identities, structured reasons, exact display amounts, filter/selection state, the recent-20 boundary, read-only/missing-schema behavior, unchanged database/payment/AI state, and concurrent view snapshots. `tests/test_payment_navigation.py` covers direct and repeated linked-payment navigation, review-state isolation, restart recovery, missing attempts, unchanged database contents and forbidden provider calls. The prior baseline contained 100 test methods: 26 original regression tests, 10 workbench page tests, 9 payment-evidence tests, 10 AI-review tests, 6 order-summary tests, 13 baseline-sensitivity tests, 15 first-use tests, and 11 payment-expectation tests. Test counts do not represent real Sandbox verification runs. Page tests cover empty lists, different payment states, isolation between browsing and payment targets, clearing stale review results, preserving rule results during What-if changes or AI failures, English interface text, and accurate payment-completion notices. Evidence tests cover read-only queries, missing or older databases, separate time meanings, duplicate and out-of-order notifications, unlinked legacy records, and the distinction between current state and independent event evidence. AI-review tests cover the six-input boundary, invalid inputs, complete and incomplete responses, fixed card content, loading feedback, manual retries, and clearing stale observations without changing rule results or sending payment requests. Summary tests cover actual payment states, current-session results, fresh sessions, stale-review invalidation, escaped record text, and unchanged payment targeting. Sensitivity tests cover the demo outputs, custom inputs, threshold precision, invalid numeric values, order/currency/amount isolation, the optional hypothetical-amount tab, and unchanged review/AI/payment/database state with no external calls. First-use tests cover the empty-state route to Sandbox tools, explicit review activation, viewing every saved status without running rules, safe pending selections, stable ID selection after reordering, explicit reselection after deletion, selected records outside the recent list, primary/secondary and preset button types, unchanged payment targeting/data, hidden full identifiers, the AI placement boundary, and the single in-place rule-analysis flow with stale-result clearing. Payment-expectation tests cover exact decimal differences, currency mismatches, local-state warnings, refund/reversal precedence, uncertain Capture outcomes, input and record invalidation, pending selections, independent inputs, source disclosures, and unchanged rule/AI/payment/database state. The terminal may print learning examples from `risk.py` and environment warnings; use unittest's final `OK` or `FAILED` as the result.

## Current limitations

- This is a local learning prototype without multi-user isolation or a production deployment setup. Payment creation is configured only for Sandbox, CAD, and local return URLs.
- Scores use manually defined rules, the simulated baseline is not real spending history, and AI text is not a fraud assessment.
- Webhook storage retains event IDs, event types, order/Capture references, processing states, timestamps, and minimal normalized Capture evidence for new completion notifications. It does not retain full requests, payer details, or signature headers, so it is not a complete signature-verification audit snapshot.
- Pending events are capped at 1,000, total events at 100,000, and stored string fields at 255 characters. Capture evidence and observation storage are each capped at 100,000 rows; observations additionally allow up to 32 distinct snapshots per Capture. Duplicates do not consume extra snapshot capacity. Unmatched Capture-only refunds/reversals share the existing 1,000 pending-event limit and are not automatically deleted. Capacity failures roll back the complete write and return 503 for Webhook deliveries rather than silently deleting pending events or conflict snapshots. Automatic cleanup and alerting are not implemented.
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

## License

This project is licensed under the [MIT License](LICENSE). Copyright (c) 2026 Sihan Cheng.
