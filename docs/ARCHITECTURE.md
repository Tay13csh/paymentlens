# Architecture and evidence boundaries

[Home](../README.md) · [Setup](SETUP.md) · [Limitations](LIMITATIONS.md)

## Runtime components

| File | Responsibility |
| --- | --- |
| `app.py` | Streamlit source/workspace navigation, review and explicit payment actions |
| `analysis_view.py` | Shared real/example summary and local discussion identity |
| `order_store.py` | SQLite records, immutable merchant terms, creation attempts, transitions and pending-event replay |
| `payment_evidence.py` | Provider normalization and deterministic merchant/Capture reconciliation |
| `paypal_auth.py` | Sandbox OAuth, Orders/Capture/query and remote Webhook signature verification |
| `webhook_server.py` | FastAPI receiver and health route |
| `payment_assistant.py` | Typed whitelist, fixed application rules, privacy/citation validation, request budgets and local request lifecycle |
| `payment_assistant_ui.py` | Shared source/object-bound chat and snapshot rechecks |
| `guided_demo.py` | Five versioned in-memory examples and fixed rule-derived walkthroughs |
| `reconciliation_facts.py` | Shared pure money/gap presentation helpers |
| `reconciliation_report.py` | Pure standard-library CSV of already-filtered records; no clients or database access |
| `runtime_config.py` | Value-free presence/format diagnostics |
| `risk.py`, `ai_explanation.py` | Secondary simulated score and its separate six-input AI explanation |
| `tests/` | Offline unit, temporary-SQLite, mock-client and Streamlit component regressions |

Runtime is Streamlit/Python REST calls to PayPal Sandbox, plus an explicit OpenAI Responses request when a user sends a question. PayPal AI Toolkit and Codex are development tools, not runtime payment agents. The receiver is a separate process exposed through ngrok when configured.

## Sources that must stay separate

- **Merchant terms**: locally supplied immutable expected amount/currency and description.
- **Recorded order amount**: creation-time local order record; not independent Capture confirmation.
- **Capture evidence**: saved provider money, status, finality, source and completeness; not net proceeds or bank settlement.
- **Local status**: last accepted saved state, not a fresh provider query.
- **Example cases**: explicitly simulated in-memory evidence, never inserted into normal storage.
- **Assumptions**: optional user-entered scoring simulations, not saved merchant terms.
- **AI explanations**: fallible interpretations, not a new authoritative event or computed result.

The historical `payguard.db` filename and deterministic capture-request namespace are compatibility identifiers. They are not the display name; renaming them is outside the branding update. The GitHub repository is now `Tay13csh/paymentlens`; its development history is retained.

## Reconciliation

The application compares one merchant order with one linked PayPal order and one supported full Capture. Full-total proof requires one valid provider response/query containing a single purchase unit and Capture, completed provider order/Capture statuses, explicit finality, and equal valid Capture/purchase-unit amount/currency. A final flag or notification alone is insufficient.

**Merchant agreement is a later independent check.** Expected 12 CAD with complete Capture/provider total 10 CAD can have valid full-total proof and `DIFFERENCE = -2.00 CAD`. Provider Capture 10 against provider total 12 lacks that proof; it cannot be promoted to a normal merchant difference. A notification lacking its own proof does not negate an earlier complete observation or create a conflict.

Branches in [the implementation](../payment_evidence.py) have priority:

| Result | Condition |
| --- | --- |
| `HISTORY` | No merchant link; earlier than later checks |
| `REVIEW` | Recorded issue or Capture conflict; reasons distinguish conflict and unsupported structure |
| `UNSUPPORTED` | Multiple saved Captures when no earlier issue branch applies |
| `INCOMPLETE` | No Capture, unconfirmed required Capture evidence, or unconfirmed nonterminal local completion |
| `CURRENCY` | After earlier checks, merchant/Capture currency mismatch; no conversion/difference |
| `DIFFERENCE` | Nonzero exact Decimal Capture-minus-merchant difference; may be historical |
| `TERMINAL` | Equal historical comparison with local `REFUNDED`, `REVERSED` or `DENIED` |
| `MATCH` | Equal amount/currency with supported evidence and current local completion |

Terminal reasons are appended to earlier results too. `DENIED` means payment denied, `REFUNDED` locally recorded refund and `REVERSED` locally recorded reversal; none establishes bank possession. Structural issues such as multiple purchase units often produce `REVIEW + UNSUPPORTED_STRUCTURE`, not necessarily the `UNSUPPORTED` code. The assistant must explain supplied results, not recalculate them. If facts clearly contradict a result, it must acknowledge that it cannot explain the inconsistency.

## Consistent reads and isolated state

`get_review_view_snapshot` uses a read-only SQLite connection and explicit read transaction. Merchant terms, order state, Capture proof, conflicts and observations are read in that snapshot. Retained selections outside the recent 20 can be read in it but are not counted/exported as recent results. A consistent snapshot can be old; it is not guaranteed forever current.

The review summary and initial chat packet use the opened object's snapshot, not the pending dropdown value or payment-action target. Before sending and accepting an answer, saved evidence is rechecked. Fingerprint/generation/request identity invalidates stale work. Source/case changes preserve isolated drafts/history and discard late results. The worker makes the SDK call without database or Streamlit access; UI polling rechecks evidence. CSV uses the exact visible list from the existing snapshot and prebuilt immutable bytes; download does not re-query.

## Writes and payment safety

- Creation persists a request key and terms; retry/reload reuses the attempt. A new key requires explicit new-order intent. Idempotency retention at the provider is not unlimited.
- Capture uses a deterministic per-order request key and local concurrency/uncertainty guards. An unknown outcome requires checking status, not automatic recapture.
- Allowed transitions prevent late responses from replacing refunded/reversed states with approved/completed.
- Only same-observation valid money pairs are accepted. They are not assembled from complementary invalid records.
- Canonical Capture rows retain conflict flags; immutable observations retain both sides. Legacy migration does not certify old money or full proof automatically.
- Webhooks are signature-verified before storage, deduplicated and transactionally replayed when linked. Capture-only early refunds/reversals have bounded durable matching. Capacity rejection fails closed rather than silently evicting pending events; writes/replay can roll back together.

## AI contract

The whitelist excludes descriptions, full IDs, names, email, credentials and raw responses. It supplies typed money/status/completeness, application results/differences, gaps and necessary conflict observations under local aliases. It never serializes the whole snapshot. The fixed `APPLICATION_RULES` is general logic, not current-payment facts; it distinguishes provider completeness from merchant matching. Simulated contexts are labeled **simulated example**.

Responses contain explanation, general manual checks and validated evidence references. Reference membership is checked; that does not prove semantic correctness. Questions and prior model answers cannot change permissions or stored facts. No tools, payment/refund execution, SQL or arbitrary browsing are exposed. Screening catches obvious sensitive input but does not guarantee anonymization.

Limits: 1,500 characters/question, six successful exchanges in current context, five local payment sessions, two archived conversations; at most 16 canonical Captures/32 observations, 18,000 serialized fact characters and 32,000 canonical-JSON characters across the complete explicit request, including instructions/rules/schema. This is not exact token counting. Excess input is rejected without silently truncating evidence. Output stays capped at 900 tokens, with bounded structured fields. SDK timeout is 20 seconds, local wait 30 seconds, no automatic retry. Cancel discards locally; remote work/charges can continue. Browser lifecycle acceptance remains separate from offline tests.
