# Limitations

[Home](../README.md) · [Validation record](VALIDATION.md) · [Architecture](ARCHITECTURE.md)

## Payment and evidence scope

- Local, single-user, Sandbox-only prototype; no production deployment or multi-user authorization model. Creation uses CAD and fixed localhost return URLs.
- One merchant order, one provider order and one supported full Capture. Partial/multiple Capture structures are not reconciled automatically. No automatic refund, stock, shipping, CSV import or multi-merchant system.
- Merchant terms are user-supplied test records. Recorded order money is creation-time data, not independent Capture proof. Saved Capture gross money is not fee-adjusted net proceeds, bank settlement or evidence of a real commercial sale.
- Local state may be stale. Provider creation time is not completion/settlement time. Missing notifications/step times do not prove payment failure; old missing links cannot be reconstructed automatically.
- The recent list, its counts, search and CSV cover only the latest 20 saved records plus clearly separate retained details. A CSV snapshot is not an all-history report or monthly statement. Descriptions make it non-anonymous.

## AI and simulations

- AI explains whitelisted facts and code results; it can still reason incorrectly. Valid references do not make an inference correct. A few accepted answers do not validate all future prompts/models.
- No tools or payment actions are available to chat. User input and previous model answers are not evidence or permission. Privacy screening is partial, not a guarantee of anonymization.
- Local cancellation/timeout discards results but cannot ensure provider cancellation or no charge. There is no automatic retry. Browser lifecycle checks still have [unconfirmed items](VALIDATION.md#remaining-acceptance).
- Example cases and fixed walkthroughs are simulated. A live OpenAI call about one remains an explanation of simulated data; a sample walkthrough is not live AI.
- Older scores and baselines are manually defined simulation tools, not real spending history, calibrated risk, fraud probability or advice to change payment amounts.

## Storage and operations

- Webhook storage retains minimal normalized fields, processing states and timestamps, not full payloads/payer details/signature headers. It is not a complete signature-verification audit archive.
- Pending events are capped at 1,000, stored events at 100,000 and event text at 255 characters. Canonical Capture records and observations are capped at 100,000 each, with 32 observations per Capture. Capacity failure rolls back/rejects instead of silently dropping pending evidence. Automatic cleanup/alerting is not implemented.
- Legacy events preserve deduplication identity with `LEGACY`; missing data remains missing. Migrations and concurrency protections have offline coverage, not validation of every existing database or provider variation.
- Request-key recovery cannot exceed PayPal's idempotency retention guarantees. Losing the database or recovery URL affects recovery. Git excludes runtime data and is not its backup.
- Dependencies are not fully version-locked. Fresh-install observations apply to the recorded environment; its system-Python TLS warning and the untested final-tree reinstall are disclosed in [validation](VALIDATION.md#fresh-environment-check).
- Real Webhook Simulator delivery and complete responsive acceptance remain unconfirmed. Missing Webhook ID optionality is established by code/mocks, not a separate ID-free real flow.
