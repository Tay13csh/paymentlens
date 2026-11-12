# Validation record

[Home](../README.md) · [Setup](SETUP.md) · [Limitations](LIMITATIONS.md)

Status recorded on **November 11, 2026**. “Maintainer-reported manual acceptance” means the user performed the check and reported the outcome; it is not a new automated external call made during documentation preparation. No real configuration, database contents or full conversation was read for this update.

## Maintainer-reported manual acceptance

| Check | Confirmed scope | What it does not establish |
| --- | --- | --- |
| Normal Sandbox flow | Earlier reported creation, buyer approval, Capture, saved records and a real notification; a completed order can receive `processed: false` | Every provider payload/failure case, a full retained signature audit, or Simulator delivery |
| Linked Handmade mug | 10 CAD merchant expectation matched independent Capture money; persisted after refresh | Bank arrival, net proceeds or all historical orders |
| Own Sandbox payment review and AI | Current saved-payment reconciliation and Q&A | Every possible follow-up or asynchronous lifecycle path |
| Five example cases | Key live-AI questions for Matching, Amount difference, Insufficient information, Conflicting evidence and Refunded | All rephrasings, future model outputs, or real abnormal payment events |
| Completeness versus merchant matching | Manually checked the distinction after the instruction fix | A model guarantee; instructions/citations remain fallible |
| Workspace navigation | Three direct entries: Review payments, Sandbox tools, Test sales orders | Complete responsive/keyboard acceptance across the application |
| Desk lamp CSV | Filtered export has exactly one data row; expected 40 CAD; Capture and difference blank; `INCOMPLETE`; correct scope and metadata | Live spreadsheet validation of every export state, all filters, conflicts or formula-injection variants |
| Earlier assistant stall | User reported the assistant no longer stayed stuck | Confirmed cancellation timing, timeout timing or late-result rejection in a real browser |

These are bounded observations, not claims of user scale, time savings, fraud detection or universal model correctness.

## Offline coverage

The latest full code regression before this documentation reorganization passed **264 test methods**. Tests use synthetic client responses/credentials and temporary SQLite databases. They do not spend money or verify real model prose.

Covered areas include:

- Creation retry/request-key persistence; duplicate/uncertain Capture handling; immutable merchant terms and one-to-one links.
- Atomic money pairs, full-total proof, unsupported partial/multiple structures, conflicts, old-schema migration, capacity rejection and transactional rollback.
- Early/unmatched Webhook replay, Capture-only refunds, duplicate events and refunded/reversed protection against late writes.
- Single-transaction snapshots under concurrent Capture completion, terminal updates and conflicts; coherent old or new versions are allowed, mixed versions are not.
- Recent-20 scope, filters/search, stable full-ID selection, source/payment/case isolation and pending versus opened objects.
- No-credential startup, placeholders and malformed configuration; no implicit Demo SQLite or service calls.
- Mocked natural follow-ups, drafts, duplicate sends, loading/failure/manual retry, local timeout/cancel and discarded stale results.
- Actual fake-client requests carrying fixed rules; eight codes, priority/reason combinations, provider completeness independent of merchant matching, unchanged serialized facts, complete-request character limits, no tools.
- CSV formula protection (including whitespace/controls), legitimate negative differences, Unicode/quoting, conflict sides, missing fields, empty results, filtered scope, immutable snapshot bytes and no writes/service calls.

Keyword coverage is auxiliary. Branch/case fixtures and source checks provide separate evidence; neither establishes that a live model always follows the rules. Run the [documented test command](SETUP.md#health-and-offline-tests) for the current count.

Documentation handoff checks passed for local file/anchor links, English display naming, placeholder TOML and the delivery-file inventory. The isolated-startup export now includes the docs; its credential-free startup test passed again. This documentation pass did not repeat dependency downloads or call a real model/payment service.

## Fresh-environment check

A temporary checkout contained only delivery sources, tests, documentation and the placeholder example, with an empty HOME, no real secrets/database and a newly created virtual environment. User/system third-party packages and pip-cache reuse were disabled.

| Stage | Result |
| --- | --- |
| README install command | Passed after the initial package-download timeout; same requirements, longer download timeout on retry |
| Python | 3.9.6 on macOS arm64 |
| Installed runtime versions | Streamlit 1.50.0; OpenAI 1.109.1; requests 2.32.5; FastAPI 0.128.8; Uvicorn 0.39.0; toml 0.10.2 |
| Import origins and `pip check` | All inspected dependencies came from the new virtual environment; no broken requirements |
| Credential-free HTTP startup | Independent loopback port 8504, health 200; existing 8501 untouched |
| Five cases and missing settings | Streamlit component checks passed; correct simulation/sample labels, disabled live sends and PayPal/OpenAI/Webhook missing notices |
| Regression at that checkpoint | 243 passed on the complete rerun; first run had one default 3-second AppTest timeout; the affected test group and full rerun passed |
| Browser rendering | Automated browser channel unavailable; component tests were not called browser acceptance |

The initial service attempt was blocked by an over-strict test harness disallowing loopback address resolution. Fixing that harness allowed startup while outgoing connections stayed blocked; this was not an application fix. The Python build emitted a LibreSSL/urllib3 compatibility warning. No real-service HTTPS compatibility or model availability was established by this clean install. Later changes were primarily documentation, CSV and assistant rules; the exact final tree has not undergone a second fully fresh dependency download/install.

## Configuration boundary

Offline mocks verified that missing OpenAI settings leave payment viewing/local reconciliation available. Basic OAuth/create/Capture/query paths work without a Webhook ID in code/mocks; a deliberately ID-free real Sandbox flow has not been separately confirmed. Verified notification delivery requires full receiver configuration and returns 503 without it. Health is not a signature/model/authentication test.

## Remaining acceptance

Still unconfirmed, and not promoted to “passed” by the checks above:

- Real-browser cancellation while waiting, timeout timing and late-result rejection after cancel/source/object/evidence changes.
- Complete wide/narrow-screen, keyboard and focus acceptance. Specific navigation was accepted; the whole responsive interface was not.
- Focused typing followed immediately by Send, and the search focus-color change, as dedicated real-browser checks.
- Webhook Simulator delivery with normal signature protection intact.
- Exhaustive live-AI phrasing, citation semantics, privacy screening and failure/quota/model variations. Reported sample answers are not a permanent guarantee.
- CSV real-browser/spreadsheet edge cases beyond the reported Desk lamp export; these remain offline-covered.
- Production deployment, multi-user security and other environments. These are outside this prototype, not promised submission capabilities.

Before publishing, review these disclosures, record/check the video, replace its placeholder URL, review the exact release diff and sensitive-file exclusions, then separately authorize a local commit/push or contest submission. This documentation task does not perform those actions. Unconfirmed features should not be demonstrated as verified.
