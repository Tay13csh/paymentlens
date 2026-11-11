# PaymentLens

**AI-assisted payment reconciliation**

PaymentLens is a local prototype that helps small merchants understand how their saved PayPal Sandbox Capture evidence compares with a merchant order. It separates expected amounts, recorded payment evidence, deterministic reconciliation results, and AI explanations.

Merchants can review linked test sales orders, inspect missing or conflicting evidence, and ask natural-language follow-up questions about the currently opened payment. The AI receives a limited evidence packet; it explains the application's conclusion and offers general manual checks without operating payments or changing records.

The unified **Payment analysis** workbench offers **My Sandbox payments / Example cases** above the selection controls. Saved payments and examples share reconciliation presentation and the existing chat, while their evidence, drafts, histories and requests remain isolated. Separate, explicitly selected Sandbox tools retain test-payment operations.

A credential-free Guided demo under Example cases provides five clearly labeled simulated cases: matching amounts, an amount difference, insufficient information, conflicting observations, and a refunded payment. Live AI and fixed sample walkthroughs are identified separately.

This is a Sandbox prototype, not proof of bank settlement or a fraud-detection system. The maintainer has manually checked a normal Sandbox flow and a linked 10 CAD payment; edge cases primarily have offline coverage. Webhook Simulator delivery, complete browser acceptance, clean dependency installation, and model answer quality remain subject to the validation boundaries in the [README](README.md).

Repository: [Tay13csh/payguard-ai](https://github.com/Tay13csh/payguard-ai).
