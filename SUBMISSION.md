# PaymentLens

**AI-assisted payment reconciliation**

**Video URL: TODO — add the reviewed final video URL before submission.**

Repository: [Tay13csh/payguard-ai](https://github.com/Tay13csh/payguard-ai).

## The problem

A small merchant may know what a customer was expected to pay but still need to understand whether saved payment evidence supports that expectation. A completed label alone does not explain an amount difference, missing Capture proof, conflicting records or a later refund.

PaymentLens is a local PayPal Sandbox reconciliation and evidence assistant. It keeps merchant terms, saved provider evidence, deterministic conclusions and AI explanations separate. It is a prototype for reviewing test payments, not a production accounting system or fraud detector.

## What it does

- Saves an immutable test merchant order and creates one explicitly linked PayPal Sandbox order from its expected CAD amount.
- Saves independent Capture amount/currency/status and provider total proof from supported provider observations. It does not treat the creation request amount as returned Capture evidence.
- Reconciles locally using Decimal, with distinct results for matching amounts, differences, currency mismatch, incomplete information, conflicts and unsupported structures. Refund/reversal/denial states are kept distinct from historical Capture completion.
- Provides a unified **My Sandbox payments / Example cases** workbench with direct workspace navigation, recent-20 search/classification and evidence details.
- Supports natural-language questions and follow-ups about the current payment or isolated example, with application-validated references and visible supporting facts.
- Exports only the filtered current-view snapshot as CSV, with explicit scope/time/count and spreadsheet text protection.
- Offers five labeled examples and fixed **Sample explanation — not generated live** walkthroughs without credentials. Live AI is optional and clearly separate from fixed samples.

## PayPal's role

PayPal Sandbox supplies OAuth, order creation, buyer approval, Capture and order details. The verified Webhook receiver can add notification evidence and state updates. The integration preserves creation request keys, duplicate/uncertain Capture guards, signature verification, deduplication, pending-event replay, transactional rollback and refunded/reversed-state protection.

These are actual Sandbox API integrations with test funds. Saved Capture gross money is not net proceeds, bank arrival or proof of a real commercial transaction. Partial/multiple Capture structures are not automatically reconciled.

## OpenAI's role

The existing OpenAI Python SDK/Responses API powers explicitly sent payment questions and continuous follow-ups. Each request contains a typed whitelist of the current object's evidence plus fixed, source-checked application rules. It excludes merchant descriptions, full identifiers, payer details, credentials and raw responses. The application computes the conclusion and valid difference; the model explains evidence and gives labeled general manual suggestions.

Full Capture proof compares provider Capture money with the purchase-unit total. Merchant matching is a later independent check: complete Capture/provider total 10 CAD can legitimately differ from merchant expectation 12 CAD. If supplied facts clearly contradict a conclusion, the assistant should admit that it cannot explain it, not invent a justification.

No tools, payment/refund actions, SQL or arbitrary browsing are available to chat. Sending may incur charges. Privacy screening and reference validation reduce some errors but do not guarantee anonymization or correct reasoning. A live answer about an example still uses simulated data.

## Development tools

- VS Code and Codex for assisted implementation, code review, offline tests and documentation; the maintainer performed the reported live checks.
- PayPal AI Toolkit in the development environment; it is not the runtime executor of payments. Runtime PayPal calls use Python requests.
- Streamlit and AppTest, Python unittest/fake clients, temporary SQLite databases, FastAPI/Uvicorn and ngrok for a configured HTTPS receiver.
- Git local recovery commits and GitHub source hosting. Python's standard csv library handles the sole report format.

## Work completed for this submission

The project evolved from an earlier Sandbox/rule-score prototype. Submission preparation focused on:

1. Merchant-order linking and an independent Capture evidence chain, including conservative completeness/conflict handling and consistent read snapshots.
2. A shared own-payment/example workbench, isolated object-bound chat, direct navigation, search and structured review filters.
3. Natural-language follow-ups with whitelist boundaries, fixed application-rule guidance, input limits, local timeout/cancel handling and manual retry.
4. Credential-free examples with explicit fixed-versus-live generation labels, plus a scoped CSV export and clearer first-use/documentation flows.
5. Offline regressions for false matches, early events/refunds, duplicates, rollback, concurrency, migration, stale responses, privacy boundaries and report safety.

Older simulated scoring remains a secondary explanatory tool, not the submission's main value proposition. No user-count, time-saving, uniqueness, award or production-impact claim is made.

## What has been validated

The maintainer reports acceptance of their Sandbox reconciliation/chat, key answers for all five example cases, full Capture proof versus merchant matching, the three workspace entries and the Desk lamp CSV: exactly one row, expected 40 CAD, blank Capture/difference, INCOMPLETE and correct scope/metadata. Earlier checks included a linked 10 CAD Handmade mug Capture match persisting after refresh.

The latest code regression passed 264 offline test methods. A prior independent, credential-free checkout/new virtual environment passed dependency installation after a download retry, imports, health and five-case component checks. These are separate kinds of evidence. Accepted questions do not prove all model answers correct.

## Limitations and next acceptance

Local, single-user, Sandbox/CAD prototype; no production deployment or bank reconciliation. Real-browser cancellation/late responses, complete responsive acceptance and Webhook Simulator delivery are still unconfirmed. Missing Webhook ID optionality has code/mock evidence but no separate deliberately ID-free real Sandbox run. The earlier clean install did not verify every environment or the exact final tree, and emitted a system-Python TLS compatibility warning. Error paths and report edge cases are primarily offline-covered.

No new features are planned for this delivery. Remaining work is final recording/review, filling the video URL, reviewing release files and obtaining separate authorization for commit/push and any contest submission. See [validation](docs/VALIDATION.md), [limitations](docs/LIMITATIONS.md) and the [under-three-minute video plan](docs/VIDEO_SCRIPT.md).

## License

[MIT](LICENSE), copyright (c) 2026 Sihan Cheng.
