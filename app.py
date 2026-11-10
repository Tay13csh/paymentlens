# PayGuard AI - Web Application
# Day 3: First Streamlit Dashboard

import streamlit as st
from ai_explanation import (
    AIExplanationError,
    DEFAULT_MODEL,
    GENERAL_SUGGESTED_CHECKS,
    REVIEW_LIMITATIONS,
    explain_order_risk,
)
from risk import calculate_score, risk_level, transaction_ratio
from paypal_auth import (
    PayPalAuthError,
    PayPalCaptureUnknownError,
    PayPalOrderError,
    capture_order,
    create_order,
    get_access_token,
    get_order_status,
)
from order_store import (
    begin_capture,
    begin_order_creation,
    complete_order_creation,
    get_order,
    get_order_events,
    get_order_creation_attempt,
    get_orders,
    mark_capture_ready,
    mark_capture_unknown,
    release_capture,
    update_order_status,
)

st.set_page_config(page_title="PayGuard AI | Order workbench", layout="wide")
st.markdown(
    """
    <style>
    .st-key-workbench table, .st-key-payment_evidence table {
        display: block;
        max-width: 100%;
        overflow-x: auto;
        white-space: nowrap;
    }
    @media (max-width: 900px) {
        .st-key-workbench [data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
        }
        .st-key-workbench [data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 0 !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("PayGuard AI")
st.write("Post-payment review assistant")
st.caption("Sandbox test environment. Rules-based scores are not fraud probabilities or PayPal risk decisions.")

returned_order_id = st.query_params.get("token")
if returned_order_id and returned_order_id != st.session_state.get("paypal_order_id"):
    st.session_state["paypal_order_id"] = returned_order_id
    st.session_state.pop("paypal_approval_url", None)
    st.session_state.pop("paypal_capture_status", None)
    st.session_state.pop("paypal_capture_id", None)

with st.sidebar.expander("Developer tools", expanded=False):
    st.subheader("PayPal Sandbox Authentication")
    if st.button("Get Sandbox Access Token"):
        try:
            paypal_config = st.secrets["paypal"]
            client_id = paypal_config["client_id"]
            client_secret = paypal_config["client_secret"]

            if not client_id or not client_secret:
                st.error("Enter your Sandbox Client ID and Secret in .streamlit/secrets.toml.")
            elif client_id == "YOUR_SANDBOX_CLIENT_ID" or client_secret == "YOUR_SANDBOX_SECRET":
                st.error("Replace the placeholders in .streamlit/secrets.toml with your Sandbox credentials.")
            else:
                get_access_token(client_id, client_secret)
                st.success("PayPal Sandbox OAuth authentication succeeded. An access token was received.")
        except PayPalAuthError as error:
            st.error(str(error))
        except Exception:
            st.error("Could not read the local PayPal configuration. Check the format and fields in .streamlit/secrets.toml.")


def clear_review():
    for key in ("risk_analysis", "risk_analysis_signature", "ai_explanation"):
        st.session_state.pop(key, None)


def render_review():
    st.subheader("Recent orders")
    st.caption("Up to 20 orders, sorted by local record update time. Review results are not stored.")
    orders = get_orders()
    if not orders:
        clear_review()
        st.info("No saved orders yet. Create a Sandbox order in Create orders and payments.")
        return None

    # A small read-only table avoids a data-grid dependency on the browsing path.
    def table_cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    rows = ["| Order ID | Amount | Currency | Payment status |", "| --- | --- | --- | --- |"]
    for order in orders:
        cells = (order["order_id"], f"{float(order['amount']):.2f}", order["currency"], order["status"])
        rows.append("| " + " | ".join(table_cell(value) for value in cells) + " |")
    st.markdown("\n".join(rows))
    orders_by_id = {order["order_id"]: order for order in orders}
    selected_order_id = st.selectbox(
        "View order",
        options=list(orders_by_id),
        format_func=lambda order_id: (
            f"{order_id} | {float(orders_by_id[order_id]['amount']):.2f} "
            f"{orders_by_id[order_id]['currency']} | {orders_by_id[order_id]['status']}"
        ),
        key="review_order_id",
    )
    selected_order = orders_by_id[selected_order_id]
    st.subheader("Selected order review")
    st.write(f"Review order ID: {selected_order_id}")
    st.write(
        f"{float(selected_order['amount']):.2f} {selected_order['currency']} "
        f"| Payment status: {selected_order['status']}"
    )
    st.caption("No saved review history. Any result shown below belongs to this session only.")
    if selected_order["status"] != "COMPLETED":
        clear_review()
        st.info("Review is available only for completed payments. No risk level is inferred for this order.")
        return selected_order

    order_amount = float(selected_order["amount"])
    currency = selected_order["currency"]
    average_amount = st.number_input(
        f"Simulated Average Spending Baseline ({currency})",
        min_value=0.01,
        value=100.00,
        step=1.00,
        key=f"simulated_average_{currency}",
    )
    st.caption("Enter a simulated baseline yourself. This is not actual historical spending data.")

    analysis_signature = (selected_order_id, order_amount, currency, average_amount)
    if st.session_state.get("risk_analysis_signature") != analysis_signature:
        st.session_state.pop("risk_analysis", None)
        st.session_state.pop("ai_explanation", None)
        st.session_state.pop("risk_analysis_signature", None)

    if st.button("Analyze Selected Order", key="analyze_saved_order"):
        ratio = transaction_ratio(order_amount, average_amount)
        score = calculate_score(order_amount, average_amount)
        level = risk_level(score)
        st.session_state["risk_analysis"] = {
            "order_id": selected_order_id,
            "order_amount": order_amount,
            "currency": currency,
            "simulated_baseline": average_amount,
            "amount_ratio": ratio,
            "risk_score": score,
            "risk_level": level,
        }
        st.session_state["risk_analysis_signature"] = analysis_signature
        st.session_state.pop("ai_explanation", None)

    analysis = st.session_state.get("risk_analysis")
    if analysis and st.session_state.get("risk_analysis_signature") == analysis_signature:
        st.subheader("Order Risk Analysis Result")
        st.caption("Current session review. This result is not saved.")
        st.write(f"Order ID: {analysis['order_id']}")
        col1, col2, col3 = st.columns(3)
        col1.metric("Order Amount", f"{analysis['order_amount']:.2f} {analysis['currency']}")
        col2.metric(
            "Simulated Average Baseline",
            f"{analysis['simulated_baseline']:.2f} {analysis['currency']}",
        )
        col3.metric("Amount Ratio", f"{analysis['amount_ratio']:.2f}x")
        col4, col5 = st.columns(2)
        col4.metric("Risk Score", f"{analysis['risk_score']}/100")
        col5.metric("Risk Level", analysis["risk_level"])
        st.progress(analysis["risk_score"])
        st.caption(
            "This is a rules-based post-payment analysis. It is not PayPal's risk decision "
            "and does not represent a probability of fraud."
        )

        st.subheader("Review explanation")
        st.caption("The metrics above come from the application. Only Observations uses AI; requests and retries are manual.")
        if st.button("Generate AI Explanation", key="generate_ai_explanation"):
            st.session_state.pop("ai_explanation", None)
            try:
                openai_config = st.secrets["openai"]
                api_key = openai_config["api_key"]
                model = openai_config.get("model", DEFAULT_MODEL)
                with st.spinner("Generating observation..."):
                    st.session_state["ai_explanation"] = explain_order_risk(
                        api_key=api_key,
                        model=model,
                        order_amount=analysis["order_amount"],
                        currency=analysis["currency"],
                        simulated_baseline=analysis["simulated_baseline"],
                        amount_ratio=analysis["amount_ratio"],
                        risk_score=analysis["risk_score"],
                        risk_level=analysis["risk_level"],
                    )
            except AIExplanationError as error:
                st.error(str(error))
            except Exception:
                st.error("AI explanation is unavailable. Check the local [openai] settings and try again.")

        with st.container(key="ai_review_cards"):
            observation_card, limitations_card, checks_card = st.columns(3, gap="small")
            with observation_card:
                with st.container(border=True):
                    st.markdown("### Observations")
                    if "ai_explanation" in st.session_state:
                        st.write(st.session_state["ai_explanation"])
                    else:
                        st.caption("Click Generate AI Explanation to request an observation. You can click again to retry.")
            with limitations_card:
                with st.container(border=True):
                    st.markdown("### Limitations")
                    st.write(REVIEW_LIMITATIONS)
            with checks_card:
                with st.container(border=True):
                    st.markdown("### Suggested checks")
                    st.caption("General suggestions for manual review, not findings about this payment.")
                    for suggestion in GENERAL_SUGGESTED_CHECKS:
                        st.write(f"- {suggestion}")

        st.subheader("What-if Scenario Simulation")
        st.caption("Simulation only. This does not change the saved order or trigger a payment.")
        hypothetical_amount = st.number_input(
            f"Hypothetical Order Amount ({analysis['currency']})",
            min_value=0.0,
            value=analysis["order_amount"],
            step=1.00,
            key=f"what_if_amount_{analysis['order_id']}_{analysis['simulated_baseline']:.2f}",
        )
        hypothetical_ratio = transaction_ratio(
            hypothetical_amount,
            analysis["simulated_baseline"],
        )
        hypothetical_score = calculate_score(
            hypothetical_amount,
            analysis["simulated_baseline"],
        )
        hypothetical_level = risk_level(hypothetical_score)
        score_change = hypothetical_score - analysis["risk_score"]

        st.caption(
            f"Both results use the same simulated baseline: "
            f"{analysis['simulated_baseline']:.2f} {analysis['currency']}."
        )
        original_column, hypothetical_column = st.columns(2)
        with original_column:
            st.markdown("**Original Completed Order**")
            st.metric("Amount", f"{analysis['order_amount']:.2f} {analysis['currency']}")
            st.metric("Amount Ratio", f"{analysis['amount_ratio']:.2f}x")
            st.metric("Risk Score", f"{analysis['risk_score']}/100")
            st.metric("Risk Level", analysis["risk_level"])
        with hypothetical_column:
            st.markdown("**Hypothetical Scenario**")
            st.metric("Amount", f"{hypothetical_amount:.2f} {analysis['currency']}")
            st.metric("Amount Ratio", f"{hypothetical_ratio:.2f}x")
            st.metric("Risk Score", f"{hypothetical_score}/100")
            st.metric("Risk Level", hypothetical_level)
        st.metric("Score Change", f"{score_change:+d} points")

    return selected_order


def render_payment():
    st.subheader("Create orders and payments")
    st.caption("Sandbox test payments. Browsing orders does not change the current payment target.")
    order_amount = st.number_input("Sandbox Order Amount (CAD)", min_value=0.01, value=10.00, step=1.00)

    creation_attempt_id = st.query_params.get("create_attempt")
    creation_attempt = get_order_creation_attempt(creation_attempt_id) if creation_attempt_id else None
    if creation_attempt_id and not creation_attempt:
        st.warning("The saved creation attempt is unavailable. Restore the original database to retry it safely.")
    elif creation_attempt:
        if creation_attempt["order_id"]:
            if not returned_order_id:
                st.session_state["paypal_order_id"] = creation_attempt["order_id"]
                st.session_state["paypal_approval_url"] = creation_attempt["approval_url"]
        else:
            st.warning(
                f"Creation is unconfirmed for {creation_attempt['amount']} CAD. "
                "Retry the same creation to recover its result. Creating a new order may create an additional order."
            )

    creation_error = st.session_state.pop("paypal_creation_error", None)
    if creation_error:
        st.error(creation_error)

    new_creation = st.button("Create New Sandbox Order" if creation_attempt_id else "Create Sandbox Order")
    retry_creation = False
    if creation_attempt and not creation_attempt["order_id"]:
        retry_creation = st.button("Retry Same Order Creation")
        st.caption("Retry uses the saved amount, even if the amount input above has changed.")

    if new_creation or retry_creation:
        try:
            paypal_config = st.secrets["paypal"]
            client_id = paypal_config["client_id"]
            client_secret = paypal_config["client_secret"]

            if not client_id or not client_secret:
                st.session_state["paypal_creation_error"] = "Enter your Sandbox Client ID and Secret in .streamlit/secrets.toml."
            elif client_id == "YOUR_SANDBOX_CLIENT_ID" or client_secret == "YOUR_SANDBOX_SECRET":
                st.session_state["paypal_creation_error"] = "Replace the placeholders in .streamlit/secrets.toml with your Sandbox credentials."
            else:
                if new_creation:
                    creation_attempt_id = begin_order_creation(f"{order_amount:.2f}")
                    st.query_params["create_attempt"] = creation_attempt_id
                    st.query_params.pop("token", None)
                    creation_attempt = get_order_creation_attempt(creation_attempt_id)
                order_id, approval_url = create_order(
                    client_id, client_secret, creation_attempt["amount"], request_id=creation_attempt_id
                )
                complete_order_creation(creation_attempt_id, order_id, approval_url)
                st.session_state["paypal_order_id"] = order_id
                st.session_state["paypal_approval_url"] = approval_url
                st.session_state.pop("paypal_capture_status", None)
                st.session_state.pop("paypal_capture_id", None)
        except PayPalAuthError as error:
            st.session_state["paypal_creation_error"] = str(error)
        except PayPalOrderError as error:
            st.session_state["paypal_creation_error"] = str(error)
        except Exception:
            st.session_state["paypal_creation_error"] = "Could not finish order creation. Any saved attempt is retained for retry."
        st.rerun()

    if "paypal_order_id" in st.session_state:
        paypal_order_id = st.session_state["paypal_order_id"]
        saved_capture_order = get_order(paypal_order_id)
        st.write(f"Current payment order ID: {paypal_order_id}")
        payment_completed = saved_capture_order and saved_capture_order["status"] == "COMPLETED"
        if payment_completed:
            st.success("Payment completed")
        elif saved_capture_order:
            st.caption(f"Current payment status: {saved_capture_order['status']}")
            if creation_attempt and creation_attempt["order_id"] == paypal_order_id:
                st.caption("Sandbox order created. Approve it with a Sandbox buyer account.")
        if "paypal_approval_url" in st.session_state and not payment_completed:
            st.link_button("Approve Order in PayPal", st.session_state["paypal_approval_url"])
        if returned_order_id == paypal_order_id:
            with st.expander("Payment details", expanded=False):
                st.write("PayPal returned to this app with this order reference.")
                st.caption("Returning from PayPal is not proof of buyer approval or completed payment.")

        if not saved_capture_order:
            st.error("This order is not present in the local order database, so Capture is unavailable.")
        elif saved_capture_order["status"] == "COMPLETED" or saved_capture_order["capture_state"] == "COMPLETED":
            st.button("Capture Approved Order", disabled=True, help="This order has already been captured.")
            if saved_capture_order["capture_id"]:
                st.write(f"Capture ID: {saved_capture_order['capture_id']}")
        elif saved_capture_order["capture_state"] in {"UNKNOWN", "IN_PROGRESS"}:
            st.warning("Capture result is unconfirmed. Check PayPal order status before trying again.")
            if st.button("Check PayPal Order Status", key="check_paypal_order_status"):
                try:
                    paypal_config = st.secrets["paypal"]
                    remote_status, capture_id = get_order_status(
                        paypal_config["client_id"],
                        paypal_config["client_secret"],
                        paypal_order_id,
                    )
                except Exception:
                    st.error("Could not confirm the PayPal order status. The Capture result remains unconfirmed.")
                else:
                    if remote_status == "COMPLETED":
                        update_order_status(paypal_order_id, remote_status, capture_id)
                        st.rerun()
                    elif remote_status == "APPROVED":
                        mark_capture_ready(paypal_order_id)
                        st.rerun()
                    else:
                        st.warning(
                            f"PayPal reports {remote_status}. The Capture result remains unconfirmed; "
                            "no new Capture request was sent."
                        )
        else:
            if st.button("Capture Approved Order"):
                if not begin_capture(paypal_order_id):
                    st.warning("The order state changed. Refresh the page and check the saved order status.")
                else:
                    try:
                        paypal_config = st.secrets["paypal"]
                        client_id = paypal_config["client_id"]
                        client_secret = paypal_config["client_secret"]
                    except Exception:
                        release_capture(paypal_order_id)
                        st.error("Could not read the local PayPal configuration. Check .streamlit/secrets.toml.")
                    else:
                        try:
                            capture_status, capture_id = capture_order(
                                client_id,
                                client_secret,
                                paypal_order_id,
                            )
                        except PayPalCaptureUnknownError:
                            mark_capture_unknown(paypal_order_id)
                            st.rerun()
                        except (PayPalAuthError, PayPalOrderError) as error:
                            release_capture(paypal_order_id)
                            st.error(str(error))
                        except Exception:
                            mark_capture_unknown(paypal_order_id)
                            st.rerun()
                        else:
                            if capture_status == "COMPLETED":
                                update_order_status(paypal_order_id, capture_status, capture_id)
                                st.rerun()
                            else:
                                mark_capture_unknown(paypal_order_id)
                                st.rerun()

    else:
        st.info("No active payment order. Create a Sandbox order here to begin.")

with st.container(key="workbench"):
    review_column, payment_column = st.columns([2, 1], gap="large")
    with review_column:
        selected_order = render_review()
    with payment_column:
        render_payment()

with st.container(key="payment_evidence"):
    st.subheader("Payment flow evidence")
    if selected_order:
        st.caption(f"Evidence for review order: {selected_order['order_id']}")
        events = get_order_events(selected_order["order_id"])
        linked_types = {
            event["event_type"] for event in events
            if event["processing_state"] != "LEGACY"
        }
        approval_evidence = "Linked approval notification" if "CHECKOUT.ORDER.APPROVED" in linked_types else "No linked record"
        completion_evidence = "Linked completion notification" if "PAYMENT.CAPTURE.COMPLETED" in linked_types else "No linked record"
        st.markdown(
            "| Step | Evidence status |\n"
            "| --- | --- |\n"
            "| Order created | Local order record only |\n"
            f"| Buyer approved | {approval_evidence} |\n"
            f"| Payment completed | {completion_evidence} |"
        )
        st.caption(
            "Evidence comes from saved records. A missing record does not mean a step was skipped."
        )

        with st.expander("Evidence details", expanded=False):
            st.write(f"Current local payment status: {selected_order['status']}")
            st.write(f"Capture ID: {selected_order.get('capture_id') or 'Not recorded'}")
            st.write(f"Local record updated (UTC): {selected_order.get('updated_at') or 'Not recorded'}")
            st.write("Order created at: Not recorded")
            st.write("Buyer approved at: Not recorded")
            st.write("Payment completed at: Not recorded")
            st.markdown("**How to read these records**")
            st.caption(
                "A current order status or Capture ID is not independent event evidence. "
                "No linked record means no attributable notification is stored, not that the step did not happen."
            )
            st.caption(
                "Provider occurrence times are not stored. Local record update time is not the payment completion time. "
                "Steps are shown in workflow order, not a reconstructed chronology."
            )
            st.caption(
                "Ordered by local storage time (UTC), not payment occurrence time. "
                "For new deliveries, Stored at is recorded after signature verification, not at the exact HTTP arrival time. "
                "Local processing time is when the application decided whether to update the order."
            )
            st.caption(
                "No state change is not a payment failure; the specific reason was not saved. "
                "Unlinked LEGACY events cannot be assigned to an order and are excluded. "
                "The receiver verifies new deliveries before storage, but no separate verification-response audit is retained."
            )

        with st.expander("Webhook records — local storage times", expanded=False):
            st.caption("Local record times (UTC), not the order in which payments happened.")
            outcomes = {
                "APPLIED": "Applied to local order",
                "IGNORED": "No state change",
                "PENDING": "Waiting for local processing",
                "LEGACY": "LEGACY — insufficient historical context",
            }
            if events:
                rows = [
                    "| Event ID | Event | Stored at (UTC) | Local processed at (UTC) | Local outcome |",
                    "| --- | --- | --- | --- | --- |",
                ]
                for event in events:
                    cells = (
                        event["event_id"], event["event_type"], event.get("received_at") or "Not recorded",
                        event.get("processed_at") or "Not recorded",
                        outcomes.get(event["processing_state"], "Unknown local outcome"),
                    )
                    rows.append("| " + " | ".join(
                        str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ") for value in cells
                    ) + " |")
                st.markdown("\n".join(rows))
            else:
                st.info("No linked record for this order.")
    else:
        st.info("Select a saved order to view payment flow evidence.")
