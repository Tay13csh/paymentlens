# Using PaymentLens

[Home](../README.md) · [Setup](SETUP.md) · [Architecture](ARCHITECTURE.md)

## Choose the discussion source

**Payment analysis** offers **My Sandbox payments / Example cases** in the main area. Examples use isolated in-memory records; your saved payments use local Sandbox records. The current **Discussing** label identifies the opened payment or case.

Existing source selection is retained. The `mode=demo` / `mode=sandbox` URL value preserves it across refreshes. A fresh PayPal return or `create_attempt` URL without an explicit mode opens Sandbox tools. Examples retain `token` and `create_attempt` without consuming them or activating a payment. Source changes do not replace the separate Sandbox action target.

## Review saved payments

Under **My Sandbox payments → Review payments**:

1. Search a merchant description, PayPal order ID or linked sales-order ID. The view contains only the most recent 20 saved records, ordered by local update time.
2. Use **All**, **Matched**, **Needs attention** or **Insufficient information**. Counts describe the fixed recent-20 range and do not change with search/reason filters. Attention reasons use any-selected-reason matching; an order can have multiple reasons.
3. Select a payment and click **Review payment**. Selection alone does not replace the opened details/chat. If selection differs, **Selection pending** appears near both. Full internal IDs determine objects; descriptions and shortened references are labels only.
4. Read the merchant expectation, Capture evidence, local status and program conclusion. Open **Reconciliation evidence** for full references, observations, completeness and typed timestamps; **Payment records** shows the three workflow steps.
5. Ask the payment assistant a question. Inspect **Evidence used for this answer** rather than treating a reference as proof that the prose inference is correct.

Known anomalies such as refunds/conflicts take classification priority over missing information. `DENIED` is **Payment denied**, not chargeback or dispute. Matched is a local reconciliation result, not proof of safety or bank settlement. The [rule table](ARCHITECTURE.md#reconciliation) explains result precedence.

Selections persist by full ID across sorting and filtering. An existing selected/opened payment outside the filter or recent 20 is retained with a scope warning, not counted among results or silently replaced. Deleted selections require reselection. **Clear filters** clears category/search/reasons without changing the payment-action target.

With no saved records, the page points to Sandbox tools. For the merchant-linked flow below, start in **Test sales orders**. Saved legacy orders without a merchant link have an optional manual check against **Recorded order amount**; that creation-time amount is not independently confirmed Capture money.

## Linked Sandbox payment

Use merchant and buyer accounts belonging to PayPal Sandbox, not real-money checkout:

1. In **Test sales orders**, enter a non-personal description and expected CAD amount, then **Save test sales order**. Terms are immutable once saved. Supported values are positive, at most two decimal places, up to 999999999.99 CAD.
2. Select the sale and explicitly choose **Create or resume linked PayPal order**. Its terms supply the normal request amount/currency. The durable attempt preserves its request key for timeout/restart recovery.
3. Use **Open payment in Sandbox tools** to select that existing linked payment and navigate directly. This navigation does not create, approve or Capture it. Confirm the active linked order before any action.
4. Use **Approve Order in PayPal** and a Sandbox buyer, then the explicit Capture action. Buyer approval alone is not completed collection. Do not repeat Capture on a completed payment.
5. Return to **Review payments**, select/open the linked record and inspect automatic merchant reconciliation. No manual expectation input or simulated baseline is required.
6. If appropriate, **Refresh Capture evidence from PayPal** explicitly queries saved provider evidence. It is an authenticated provider GET, not a new Capture, and does not run on page render.

For uncertain creation results, use **Retry Same Order Creation** to reuse the key and amount. Use **Create New Sandbox Order** only for an explicitly new attempt. Recovery depends on the local database and `create_attempt` URL. An uncertain Capture requires status checking; a timeout is not proof of failure. Browsing/filtering never changes the separate action target.

## Example cases and chat

Five **Simulated example** cases reuse the same reconciliation function:

| Case | Recorded premise | Result |
| --- | --- | --- |
| Matching | Expected 10 CAD; complete Capture/provider total 10 CAD | `MATCH` |
| Amount difference | Expected 12 CAD; complete Capture/provider total 10 CAD | `DIFFERENCE`, -2.00 CAD |
| Insufficient information | Approval without independent Capture | `INCOMPLETE` |
| Conflicting evidence | Same simulated Capture observed as 10 CAD and 12 CAD | `REVIEW`; amount disputed |
| Refunded | Historical complete Capture 10 CAD; current local refund | `TERMINAL`; historical equal comparison |

Selecting a case makes no AI request. Without OpenAI configuration, use **View sample walkthrough → Sample explanation — not generated live**. It is fixed application text for listed questions, not a free-text answer or live-error fallback.

With configuration, quick questions send immediately; free text uses **Send question**. Sends may be charged even when the records are simulated. Use natural follow-ups; no background copy/paste is needed. The assistant explains the application's result and general manual checks; it cannot operate payments or establish bank arrival, fraud, discounts or other unrecorded causes.

Each source/payment/case has isolated drafts, history and requests. Evidence changes archive old answers as outdated and invalidate pending work; questions are not automatically resent. Cancel ends local waiting and discards a late result, but cannot guarantee remote cancellation or no charge. Failures retain the question and allow manual retry. [Browser cancellation/late-response acceptance remains pending](VALIDATION.md#remaining-acceptance).

## Payment records and timestamps

Three cards show **Order created**, **Buyer approved**, **Payment completed** in workflow order, not reconstructed occurrence order. A current status or Capture ID is not an independent event.

- **Local order record only**: an ID is saved; no separate order-created event is retained.
- **Linked approval/completion notification**: an attributable event is stored.
- **No linked record**: no attributable record, not proof the payment failed or the step never occurred.

Details label missing step times **Not recorded**. Capture provider creation time is separate from completion/settlement time. Notification rows use local **Stored at (UTC)** time, not payment-event order. `No state change` must not be assumed to mean “already up to date”; several processing paths can produce it. `LEGACY` preserves older deduplication records without reconstructing missing links.

`received: true` follows accepted signature verification. `processed: true` means this request changed state. `processed: false` may mean duplicate, waiting for a link, no same-state update or a disallowed transition; it does not itself identify which, or mean verification failed.

## CSV current view only

**Reconciliation report (current view) → Download CSV** includes only the current recent-20 records satisfying search/category/reason filters. Retained out-of-range selections and opened records outside the filter are excluded; examples are not exportable. Empty results disable download.

The list and CSV use one already-read snapshot. Generation time and exported count identify it; download serves prepared bytes without rerunning or querying. A later render creates a new report. Each row repeats UTC export time, scope, filters, record count and **Local saved Sandbox evidence, not bank settlement**. Search text is omitted because it can contain full identifiers; category, reasons and search-active status are retained.

The UTF-8 BOM CSV has one header, no comment rows, and standard quoting for commas/quotes/newlines. It includes description, order suffix, merchant/Capture money, valid code-provided difference, code, reasons, shared gaps and conflicting observations. Amount strings are not converted through floats, padded or rounded. Invalid/unavailable amounts remain blank. A conflict or unsupported/multiple-Capture structure has no single confirmed amount; both conflict observations retain money/currency/source under local aliases. There is no FX difference.

Formula-like text, including leading whitespace/controls, is prefixed with an apostrophe; non-text controls such as NUL become visible Unicode escapes. A valid negative difference such as `-2.00` remains numeric text. Keep these protections when re-saving. Descriptions remain included: the CSV is not anonymous, a monthly statement, complete history or proof of settlement.

## Secondary simulated-rule tools

**Optional simulated rule tools** retains the original rule analysis, its separate six-input AI explanation and **Explore assumptions**. They are not merchant/Capture reconciliation and do not analyze Webhooks. Baselines are user-provided simulations, not spending history.

The original ratio rule remains: below 2 → 10/100; at least 2 and below 5 → 50/100; at least 5 → 80/100. Its High/Medium/Low labels are uncalibrated demonstrations, not fraud probabilities or payment decisions. Baseline comparison retains 10/5/2 presets and custom input; hypothetical amount remains secondary. These tools do not modify saved merchant terms, evidence, payment targets or the official reconciliation.
