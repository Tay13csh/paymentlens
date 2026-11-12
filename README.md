# PaymentLens

**AI-assisted payment reconciliation**

For a small merchant, a payment status alone does not answer: **Does this payment match my sales order? What records support that conclusion? What is still missing?**

PaymentLens is a local PayPal Sandbox prototype that puts merchant expectations, independent saved Capture evidence, program-calculated reconciliation and a payment-bound AI conversation in one workspace.

**Demo video: TODO — add the final video URL before submission.**

Repository: [Tay13csh/paymentlens](https://github.com/Tay13csh/paymentlens). [Submission introduction](SUBMISSION.md) · [Video script and shot list](docs/VIDEO_SCRIPT.md)

## The core flow

1. Save a test merchant sales order with a description and expected CAD amount.
2. Create its linked PayPal Sandbox order, approve it with a Sandbox buyer and Capture it explicitly.
3. Open **My Sandbox payments → Review payments**. Compare saved merchant terms with independent Capture evidence; inspect missing or conflicting records.
4. Ask the current-payment assistant a question, follow up and inspect the evidence supplied for that answer. The application decides the reconciliation; AI explains it.
5. Optionally download **Reconciliation report (current view)** for the filtered recent-20 view. It is not a complete-history or settlement report.

Five isolated **Example cases** demonstrate matching amounts, an amount difference, insufficient information, conflicting evidence and a refund. Their conclusions use the same reconciliation code as saved payments.

## Quick start

Use Python 3.9+ and pip on macOS/Linux, from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Install may download dependencies. A fresh-environment check with Python 3.9.6 passed after a download-timeout retry; dependencies are not fully locked. See [setup details and compatibility notes](docs/SETUP.md).

### No credentials: examples and sample walkthroughs

No configuration file, database, PayPal account, OpenAI key or Webhook ID is required. First launch without configuration or return/recovery context opens **Example cases**. Select a case and open **View sample walkthrough**.

**Sample explanation — not generated live** is fixed application text based on the rule result. It does not answer arbitrary typed questions. Live sends stay disabled without OpenAI configuration.

### OpenAI configuration: live questions

Follow [local configuration](docs/SETUP.md#local-configuration) to supply an OpenAI key and a model available to your account. Live AI works with saved-payment evidence or a selected simulated case. **Sending may incur charges.** Quick questions send immediately; free text requires **Send question**. Selecting a payment/case does not send a request.

Live AI about an example still uses simulated data. A fixed sample walkthrough is never presented as a live answer or substituted after a request fails.

### PayPal Sandbox configuration: test-payment flow

Configure a Sandbox merchant client ID/secret and use a separate Sandbox buyer. Choose **My Sandbox payments → Test sales orders**, then follow the [linked-payment walkthrough](docs/USER_GUIDE.md#linked-sandbox-payment).

The code and offline mocks support basic OAuth/create/Capture/query without a Webhook ID; a fresh real flow with that ID absent has **not** been separately verified. Verified notifications require the receiver, its Webhook ID and HTTPS registration. See [Webhook setup and boundary](docs/SETUP.md#webhook-receiver-and-https).

## What has been checked

The maintainer reports manual acceptance of their Sandbox reconciliation/chat, key answers for all five examples, the distinction between full Capture proof and merchant matching, the three workspace navigation choices, and a one-row Desk lamp CSV. These checks cover those interactions, **not all future model answers**.

Offline regressions cover payment safety and many failure cases. Browser cancellation/late-response acceptance, complete responsive acceptance and Webhook Simulator delivery remain unconfirmed. See the [validation record](docs/VALIDATION.md).

## Boundaries

This is a local, single-user, Sandbox-only prototype. Saved status is not a live query or proof of bank settlement; Capture amount is not net proceeds. Partial/multiple Captures are not reconciled automatically. AI can be wrong, cannot operate payments and must not infer fraud or unexplained causes. Do not enter credentials or personal data in chat. CSV retains merchant descriptions and is not anonymous.

The older simulated score tools remain secondary: their scores are uncalibrated demonstrations, not fraud probabilities. See [limitations](docs/LIMITATIONS.md).

## Tests and documentation

```sh
python -B -m unittest discover -s tests -v
```

Tests use temporary databases and mocked services; credentials and running services are not required.

- [Setup, configuration and service commands](docs/SETUP.md)
- [User guide, CSV and optional tools](docs/USER_GUIDE.md)
- [Architecture, rules and data boundaries](docs/ARCHITECTURE.md)
- [Validation evidence and remaining checks](docs/VALIDATION.md)
- [Limitations](docs/LIMITATIONS.md)
- [English video script and shot list](docs/VIDEO_SCRIPT.md)

Licensed under [MIT](LICENSE). Copyright (c) 2026 Sihan Cheng.
