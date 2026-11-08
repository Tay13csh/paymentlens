# PayGuard AI - Web Application
# Day 3: First Streamlit Dashboard

import streamlit as st
from ai_explanation import AIExplanationError, DEFAULT_MODEL, explain_order_risk
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
    get_order_creation_attempt,
    get_orders,
    mark_capture_ready,
    mark_capture_unknown,
    release_capture,
    update_order_status,
)

st.title("PayGuard AI")
st.write("An AI-powered payment risk analysis assistant.")
st.write("Analyze completed payments against a user-provided simulated spending baseline.")

returned_order_id = st.query_params.get("token")
if returned_order_id and returned_order_id != st.session_state.get("paypal_order_id"):
    st.session_state["paypal_order_id"] = returned_order_id
    st.session_state.pop("paypal_approval_url", None)
    st.session_state.pop("paypal_capture_status", None)
    st.session_state.pop("paypal_capture_id", None)

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

st.subheader("Completed Order Risk Analysis")
completed_orders = [order for order in get_orders() if order["status"] == "COMPLETED"]

if not completed_orders:
    st.info("No completed orders are available for analysis yet. Complete a Sandbox payment first.")
else:
    orders_by_id = {order["order_id"]: order for order in completed_orders}
    selected_order_id = st.selectbox(
        "Select a completed order",
        options=list(orders_by_id),
        format_func=lambda order_id: (
            f"{order_id} | {float(orders_by_id[order_id]['amount']):.2f} "
            f"{orders_by_id[order_id]['currency']} | {orders_by_id[order_id]['status']}"
        ),
    )
    selected_order = orders_by_id[selected_order_id]
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

        if st.button("Generate AI Explanation", key="generate_ai_explanation"):
            st.session_state.pop("ai_explanation", None)
            try:
                openai_config = st.secrets["openai"]
                api_key = openai_config["api_key"]
                model = openai_config.get("model", DEFAULT_MODEL)
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

        if "ai_explanation" in st.session_state:
            st.markdown(st.session_state["ai_explanation"])

st.subheader("PayPal Sandbox Orders")
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
        st.success("Sandbox order created. Approve it with a Sandbox buyer account.")
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
    st.write(f"Order ID: {paypal_order_id}")
    if "paypal_approval_url" in st.session_state:
        st.link_button("Approve Order in PayPal", st.session_state["paypal_approval_url"])
    elif returned_order_id:
        st.success("PayPal returned to this app with an approved order.")

    if not saved_capture_order:
        st.error("This order is not present in the local order database, so Capture is unavailable.")
    elif saved_capture_order["status"] == "COMPLETED" or saved_capture_order["capture_state"] == "COMPLETED":
        st.button("Capture Approved Order", disabled=True, help="This order has already been captured.")
        st.success("Capture is already completed.")
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

st.subheader("Recent Sandbox Orders")
for saved_order in get_orders():
    capture_label = f" | Capture ID: {saved_order['capture_id']}" if saved_order["capture_id"] else ""
    st.write(
        f"{saved_order['order_id']} | {saved_order['amount']} {saved_order['currency']} "
        f"| {saved_order['status']}{capture_label}"
    )
