# Demo video script and shot list

[Home](../README.md) · [Submission text](../SUBMISSION.md) · [Validation](VALIDATION.md)

**Target edited runtime: 2:30. Hard ceiling: 2:50**, leaving a 10-second margin below three minutes. The 20-second difference between target and ceiling is for visible waiting/transitions; the script must not grow to fill it. Record real service latency, then shorten waiting with a clearly marked cut. Recordings may take longer than the final edit.

## Before recording

- Record the current local build only after reviewing the delivery diff. This file is a plan, not evidence that a video has been recorded.
- Prepare a Sandbox merchant and buyer; complete buyer login off-camera. Use a non-personal test description such as **Demo mug**, expected **10.00 CAD**. Creation/approval/Capture and live questions below are actions for the maintainer to perform deliberately while recording; none were run to write this script.
- Confirm the active linked order before payment actions. Use a fresh explicitly intended Sandbox order if a new Capture shot is needed; never repeat Capture on an already completed order for filming.
- Match narration to the actual displayed result. If proof is incomplete or a request fails, do not narrate the planned match over that screen; resolve/re-record manually or disclose the outcome.
- Close editor/config, token/authorization output, terminal logs, ngrok inspector and unrelated tabs. Crop/redact buyer name/email, credentials and full identifiers. Show amount/status and short references; do not film buyer login or secrets.
- Keep provenance overlays visible: **Live PayPal Sandbox API — test funds**, **Live OpenAI answer — saved Sandbox evidence**, and **Simulated example — not an actual payment**. If using the fixed walkthrough instead, label it **Sample explanation — not generated live** and do not narrate it as an AI request.

## Shot list and spoken English

| Edited time | Screen/action | Narration | Provenance/edit note |
| --- | --- | --- | --- |
| 0:00–0:12 | PaymentLens title, then My Sandbox payments | “A payment status is only part of the story. PaymentLens helps a small merchant compare a sales order with saved PayPal Capture evidence, then ask what the result means.” | Local app; no external call just for navigation |
| 0:12–0:30 | Test sales orders: save Demo mug, 10 CAD; show immutable expectation | “I start with a test merchant order for ten Canadian dollars. These are the merchant's expected terms, saved before creating the linked payment.” | Local merchant record; show no personal description |
| 0:30–0:48 | Explicit linked-order creation, Open payment in Sandbox tools, cropped buyer approval | “The app creates a linked PayPal Sandbox order from those terms. I approve it with a Sandbox buyer. Approval alone is not completed collection.” | Live PayPal Sandbox API and buyer approval; test funds. Login off-camera. Label shortened waiting |
| 0:48–1:05 | Explicit Capture once; show saved completion evidence | “Now I Capture it. PaymentLens saves the amount and currency returned by PayPal, separately from the original merchant expectation.” | Live PayPal Sandbox Capture. Do not substitute a request amount for returned evidence |
| 1:05–1:25 | Review payments → select/open linked payment; expectation, Capture, status, conclusion; briefly open evidence | “Here the saved Capture agrees with the merchant order. Full Capture proof comes from provider evidence; matching the merchant amount is a separate check. Saved records still do not prove bank settlement.” | Current saved Sandbox snapshot; show actual returned result, not a simulated match |
| 1:25–1:50 | Send a matching question, then natural follow-up about bank arrival; show evidence drawer | “I can ask why it matches, then follow up about bank arrival. The assistant explains this payment's records and references. The program owns the result; AI cannot move money or confirm bank settlement.” | Live OpenAI calls, explicitly sent and potentially charged. Mark cuts **Waiting shortened**; preserve the actual answer and request context |
| 1:50–2:15 | Switch to Example cases → Amount difference; show 12 expected, 10 Capture/provider total, -2 difference | “This is a simulated example, not my payment. The complete Capture is ten dollars, while the example merchant expected twelve. The program reports a two-dollar difference. Full Capture proof does not require matching merchant expectations.” | Simulated data, deterministic calculation. No PayPal call. If showing AI, make a deliberate live send and label both data and generation provenance |
| 2:15–2:30 | Briefly switch to Conflicting evidence, then end on app title | “When observations conflict, neither amount is confirmed as the answer. PaymentLens keeps facts, missing information and explanations separate. It is a Sandbox prototype, not fraud detection or proof of bank arrival.” | Simulated conflict: show both observations and REVIEW. End card can show repository URL |

## Recording and edit checks

- Keep the main sequence merchant terms → real Sandbox approval/Capture → reconciliation → live follow-up → labeled simulated abnormality. Do not present a simulated case as the actual linked order.
- Allow up to 20 extra edited seconds for waits/transitions and stay below 2:50. If over, shorten navigation pauses or the closing conflict shot; do not speed through unreadable evidence or remove provenance labels. Retain a readable slice of each real answer.
- An inaccurate live answer must not be hidden behind a fixed walkthrough labeled as live. Review/re-record transparently, or disclose the limitation. Do not imply that the assistant has proven settlement.
- Do not demonstrate cancellation/late-response or full responsive support as accepted unless those checks are separately completed. Simulator delivery is not part of this video plan.
- Review the final frame-by-frame recording for credentials, buyer information, full IDs and unintended tabs. Confirm audio/subtitles, duration and video access manually before filling the URL placeholder.

**Video URL: TODO — record, review and upload manually, then update README and SUBMISSION.** This task does not upload a video or submit a contest entry.
