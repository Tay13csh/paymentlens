# PayGuard AI - Web Application
# Day 3: First Streamlit Dashboard

from decimal import Decimal, InvalidOperation
from html import escape
import math

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
    create_merchant_sale,
    get_merchant_sales,
    begin_sale_creation,
    get_sale_reconciliation,
    record_payment_observation,
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
    .stApp, [data-testid="stAppViewContainer"] {
        background: #f4f7fb;
        color: #13263d;
    }
    [data-testid="stMainBlockContainer"] { max-width: 1520px; }
    [data-testid="stSidebar"] {
        background: #eaf0f7;
        border-right: 1px solid #d7e2ee;
    }
    .stApp h1, .stApp h2, .stApp h3,
    .stApp [data-testid="stMarkdownContainer"], .stApp label {
        color: #13263d;
        overflow-wrap: anywhere;
    }
    .stApp h1 { letter-spacing: -0.035em; }
    .stApp h2 { font-size: 1.35rem; margin-top: 0.6rem; }
    .stApp h3 { font-size: 1.1rem; }
    .stApp [data-testid="stCaptionContainer"] { color: #526277; }
    .stButton > button {
        background: #ffffff;
        color: #0f766e;
        border: 1px solid #0f766e;
        border-radius: 10px;
        font-weight: 600;
    }
    .stButton > button:hover:not(:disabled) {
        background: #eaf4f2;
        color: #115e59;
        border-color: #115e59;
    }
    .stButton > button[kind="primary"] {
        background: #0f766e;
        color: #ffffff;
    }
    .stButton > button[kind="primary"]:hover:not(:disabled) {
        background: #115e59;
        color: #ffffff;
        border-color: #115e59;
    }
    .stButton > button [data-testid="stMarkdownContainer"] { color: inherit; }
    .stButton > button:focus-visible {
        outline: 3px solid #13263d;
        outline-offset: 3px;
    }
    .stButton > button:disabled, .stButton > button[kind="primary"]:disabled {
        background: #e5ebf1;
        color: #526277;
        border-color: #d7e2ee;
    }
    .stApp [data-testid="stLinkButton"] a {
        background: #0f766e;
        color: #ffffff;
        border: 1px solid #0f766e;
        border-radius: 10px;
        font-weight: 600;
        text-decoration: none;
    }
    .stApp [data-testid="stLinkButton"] a [data-testid="stMarkdownContainer"] {
        color: inherit;
    }
    .stApp [data-testid="stLinkButton"] a p { color: inherit; }
    .stApp [data-testid="stLinkButton"] a:hover:not([aria-disabled="true"]) {
        background: #115e59;
        color: #ffffff;
        border-color: #115e59;
    }
    .stApp [data-testid="stLinkButton"] a:focus-visible {
        outline: 3px solid #13263d;
        outline-offset: 3px;
        box-shadow: 0 0 0 2px #ffffff;
    }
    .stApp [data-testid="stLinkButton"] a[aria-disabled="true"] {
        background: #e5ebf1;
        color: #526277;
        border-color: #d7e2ee;
    }
    .stApp [data-testid="stFormSubmitButton"] button {
        background: #0f766e;
        color: #ffffff;
        border: 1px solid #0f766e;
        border-radius: 10px;
        font-weight: 600;
    }
    .stApp [data-testid="stFormSubmitButton"] button [data-testid="stMarkdownContainer"],
    .stApp [data-testid="stFormSubmitButton"] button p { color: inherit; }
    .stApp [data-testid="stFormSubmitButton"] button:hover:not(:disabled) {
        background: #115e59;
        color: #ffffff;
        border-color: #115e59;
    }
    .stApp [data-testid="stFormSubmitButton"] button:focus-visible {
        outline: 3px solid #13263d;
        outline-offset: 3px;
        box-shadow: 0 0 0 2px #ffffff;
    }
    .stApp [data-testid="stFormSubmitButton"] button:disabled {
        background: #e5ebf1;
        color: #526277;
        border-color: #d7e2ee;
    }
    .stApp [data-testid="stExpander"] details {
        background: #ffffff;
        color: #13263d;
        border-color: #d7e2ee;
    }
    .stApp [data-testid="stExpander"] summary {
        background: #eaf0f7;
        color: #13263d;
        border-radius: 10px;
        cursor: pointer;
    }
    .stApp [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"],
    .stApp [data-testid="stExpander"] summary p { color: inherit; }
    .stApp [data-testid="stExpander"] summary svg { color: #0f766e; }
    .stApp [data-testid="stExpander"] summary:hover { background: #d8f1e9; }
    .stApp [data-testid="stExpander"] summary:focus-visible {
        outline: 3px solid #0f766e;
        outline-offset: -3px;
    }
    .stApp input, .stApp textarea,
    .stApp [data-baseweb="select"] > div {
        background: #ffffff;
        color: #13263d;
        border-radius: 10px;
    }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #d7e2ee;
        border-radius: 12px;
        padding: 0.85rem;
    }
    [data-testid="stMetricValue"] {
        color: #13263d;
        font-size: clamp(1.15rem, 2vw, 1.8rem);
        overflow-wrap: anywhere;
        white-space: normal;
    }
    .stApp [data-testid="stAlert"] { border-radius: 12px; }
    .pg-summary {
        background: #ffffff;
        border: 1px solid #d7e2ee;
        border-top: 4px solid #0f766e;
        border-radius: 16px;
        padding: 1.2rem;
        margin: 0.3rem 0 1rem;
        box-shadow: 0 5px 20px rgba(19, 38, 61, 0.05);
    }
    .pg-summary-grid {
        display: grid;
        grid-template-columns: 1.1fr 0.9fr 1fr;
        gap: 1.1rem;
        align-items: start;
    }
    .pg-summary .pg-label {
        color: #526277;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin: 0 0 0.45rem;
    }
    .pg-summary .pg-order-id {
        color: #526277;
        font-size: 0.85rem;
        margin: 0 0 1rem;
        overflow-wrap: anywhere;
    }
    .pg-summary .pg-amount {
        color: #13263d;
        font-size: clamp(1.6rem, 2.6vw, 2.3rem);
        font-weight: 750;
        line-height: 1.2;
        margin: 0;
        overflow-wrap: anywhere;
    }
    .pg-summary .pg-currency { font-size: 0.95rem; font-weight: 600; }
    .pg-summary .pg-badge {
        display: inline-block;
        max-width: 100%;
        border-radius: 999px;
        padding: 0.35rem 0.65rem;
        font-size: 0.8rem;
        font-weight: 700;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }
    .pg-summary .pg-paid { background: #d8f1e9; color: #075b43; }
    .pg-summary .pg-pending { background: #e5edf7; color: #243e64; }
    .pg-summary .pg-terminal { background: #fbe9e9; color: #8b2735; }
    .pg-summary .pg-review {
        color: #13263d;
        font-size: 1.05rem;
        font-weight: 700;
        margin: 0;
        overflow-wrap: anywhere;
    }
    .pg-summary .pg-note { color: #526277; font-size: 0.8rem; margin: 0.4rem 0 0; }
    .st-key-workbench table, .st-key-payment_evidence table {
        display: block;
        max-width: 100%;
        overflow-x: auto;
        white-space: nowrap;
    }
    .st-key-sensitivity_comparison [data-testid="stExpander"] summary {
        cursor: pointer;
        background: #eaf0f7;
        color: #13263d;
        border-radius: 10px;
        padding: 0.85rem 1rem;
        font-weight: 600;
        overflow-wrap: anywhere;
    }
    .st-key-sensitivity_comparison [data-testid="stExpander"] summary:hover {
        background: #d8f1e9;
    }
    .st-key-sensitivity_comparison [data-testid="stExpander"] summary:focus-visible {
        outline: 3px solid #0f766e;
        outline-offset: 3px;
    }
    .st-key-sensitivity_comparison [data-testid="stExpander"] summary svg {
        color: #0f766e;
        flex-shrink: 0;
    }
    .pg-evidence-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem;
        margin: 0.5rem 0 1rem;
    }
    .pg-evidence-card {
        background: #ffffff;
        border: 1px solid #d7e2ee;
        border-radius: 14px;
        padding: 1rem;
        min-width: 0;
    }
    .pg-evidence-number { color: #526277; font-size: 0.8rem; font-weight: 700; }
    .pg-evidence-status {
        display: inline-block;
        max-width: 100%;
        border-radius: 10px;
        padding: 0.4rem 0.65rem;
        font-size: 0.85rem;
        font-weight: 600;
        overflow-wrap: anywhere;
    }
    .pg-evidence-linked { background: #d8f1e9; color: #075b43; }
    .pg-evidence-neutral { background: #e5edf7; color: #243e64; }
    @media (max-width: 900px) {
        .pg-evidence-grid { grid-template-columns: minmax(0, 1fr); }
        .pg-summary-grid { grid-template-columns: minmax(0, 1fr); gap: 1rem; }
        .pg-summary { padding: 1rem; }
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
st.write("Review a payment and its supporting records.")
st.caption("Sandbox test environment. Start by selecting a payment, then click Review payment.")

returned_order_id = st.query_params.get("token")
if returned_order_id and returned_order_id != st.session_state.get("paypal_order_id"):
    st.session_state["paypal_order_id"] = returned_order_id
    st.session_state.pop("paypal_approval_url", None)
    st.session_state.pop("paypal_capture_status", None)
    st.session_state.pop("paypal_capture_id", None)

def render_authentication():
    with st.expander("Authentication", expanded=False):
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


def render_order_summary(order, analysis=None):
    """Present stored payment status separately from the current session's rule result."""
    status = order["status"]
    status_class = "pg-paid" if status == "COMPLETED" else (
        "pg-terminal" if status in {"DENIED", "REFUNDED", "REVERSED"} else "pg-pending"
    )
    review = "Not analyzed"
    if analysis:
        review = f"{analysis['risk_score']}/100 · {analysis['risk_level']}"
    st.markdown(
        '<section class="pg-summary" aria-label="Selected order summary">'
        f'<p class="pg-order-id">Review order ID: {escape(order["order_id"])}</p>'
        '<div class="pg-summary-grid">'
        '<div><p class="pg-label">Order amount</p>'
        f'<p class="pg-amount">{float(order["amount"]):.2f} '
        f'<span class="pg-currency">{escape(order["currency"])}</span></p></div>'
        '<div><p class="pg-label">Payment status</p>'
        f'<span class="pg-badge {status_class}">{escape(status)}</span></div>'
        '<div><p class="pg-label">Rule review</p>'
        f'<p class="pg-review">{escape(review)}</p>'
        '<p class="pg-note">Current session only · Not saved</p></div>'
        '</div></section>',
        unsafe_allow_html=True,
    )


def render_baseline_sensitivity(order):
    """Calculate display-only scenarios without touching review or payment state."""
    amount = float(order["amount"])
    currency = order["currency"]

    def number(value):
        # Keep the float's round-trip precision, especially near rule thresholds.
        text = repr(float(value))
        return text[:-2] if text.endswith(".0") else text

    def scenario(baseline):
        ratio = transaction_ratio(amount, baseline)
        if not math.isfinite(ratio):
            raise ValueError("The amount ratio is outside the supported numeric range.")
        score = calculate_score(amount, baseline)
        return ratio, score, risk_level(score)

    def result_card(label, baseline, result):
        ratio, score, level = result
        with st.container(border=True):
            st.markdown(f"**{label}: {number(baseline)} {escape(currency)}**")
            st.metric("Amount ratio", f"{number(ratio)}×")
            st.metric("Rule score", f"{score}/100")
            st.markdown(f"Rule-based level: **{level}**")

    with st.container(key="sensitivity_comparison"):
        st.caption("Same payment, different simulated baselines.")
        with st.container():
            st.markdown("**Payment evidence is unchanged. Only the simulated baseline changes.**")
            st.markdown("**Payment facts**")
            st.write(f"Actual order amount: {amount:.2f} {currency} | Payment status: {order['status']}")
            st.caption("The saved order amount and currency are fixed in this comparison.")
            st.markdown("**Simulated assumptions**")
            st.caption(
                "Demo baselines: 10, 5, and 2 in the order currency. These are demonstration assumptions, "
                "not historical spending data. No currency conversion is performed."
            )
            input_key = f"sensitivity_baseline_{order['order_id']}_{order['amount']}_{currency}"
            if input_key not in st.session_state:
                st.session_state[input_key] = "10"

            def use_baseline(key, value):
                st.session_state[key] = value

            selected_preset = None
            try:
                selected_value = Decimal(st.session_state[input_key].strip())
                if selected_value.is_finite():
                    selected_preset = next((value for value in (10, 5, 2) if selected_value == value), None)
            except InvalidOperation:
                pass
            preset_columns = st.columns(3, gap="small")
            for column, value in zip(preset_columns, (10, 5, 2)):
                with column:
                    st.button(
                        f"Use baseline {value} {currency}",
                        key=f"{input_key}_preset_{value}",
                        type="primary" if selected_preset == value else "secondary",
                        on_click=use_baseline,
                        args=(input_key, str(value)),
                    )
            st.caption("Simulation only — does not change or charge the payment.")
            st.markdown(f"**Selected preset: {selected_preset} {escape(currency)}**" if selected_preset else "**Custom**")
            raw_baseline = st.text_input(
                f"Custom simulated comparison baseline ({currency})",
                key=input_key,
            )
            custom = None
            custom_error = None
            try:
                decimal_baseline = Decimal(raw_baseline.strip())
                if not decimal_baseline.is_finite() or decimal_baseline <= 0:
                    raise ValueError("Enter a finite simulated baseline greater than zero.")
                baseline = float(decimal_baseline)
                if not math.isfinite(baseline) or baseline <= 0:
                    raise ValueError("The baseline is outside the supported numeric range.")
                if Decimal(str(baseline)) != decimal_baseline:
                    raise ValueError("Use fewer significant digits; the current rules cannot preserve this baseline's precision.")
                custom = (baseline, scenario(baseline))
            except InvalidOperation:
                custom_error = "Enter a numeric simulated baseline greater than zero."
            except (ValueError, OverflowError) as error:
                custom_error = str(error)

            st.markdown("**Rule results**")
            st.caption("Simulation only. These results do not update the current session review, AI observation, or payment target.")
            with st.container(key="selected_scenario"):
                st.markdown("**Your comparison result**")
                if custom:
                    result_card("Selected baseline", custom[0], custom[1])
                else:
                    st.warning(custom_error)
            with st.container(key="example_assumptions"):
                st.markdown("**Compare example assumptions**")
                st.caption("Fixed demonstration examples — not historical data. These examples do not change when you select a scenario.")
                columns = st.columns(3, gap="small")
                for column, baseline in zip(columns, (10.0, 5.0, 2.0)):
                    with column:
                        result_card("Demo baseline", baseline, scenario(baseline))


def short_payment_reference(order_id):
    return "…" + order_id[-6:]


def remember_payment_selection():
    """Keep a stable ID separate from the widget's changing option identity."""
    st.session_state["selected_payment_id"] = st.session_state.get("review_order_id")
    st.session_state.pop("payment_selection_missing", None)


def render_payment_browser():
    st.subheader("Recent payments")
    st.caption("Up to 20 saved payments, sorted by local record update time.")
    orders = get_orders()
    orders_by_id = {order["order_id"]: order for order in orders}
    if "selected_payment_id" not in st.session_state:
        st.session_state["selected_payment_id"] = next(iter(orders_by_id), None)
    selected_id = st.session_state["selected_payment_id"]
    if selected_id and selected_id not in orders_by_id:
        retained_order = get_order(selected_id)
        if retained_order:
            # The recent list is limited; leaving it does not imply deletion.
            orders_by_id[selected_id] = retained_order
        else:
            st.session_state["selected_payment_id"] = None
            st.session_state["payment_selection_missing"] = True
            st.session_state.pop("payment_check_result", None)
    if st.session_state.get("payment_selection_missing"):
        st.warning("The selected payment is no longer available. Select a payment again and click Review payment.")
    if not orders:
        clear_review()
        st.session_state.pop("opened_payment_id", None)
        st.session_state.pop("payment_check_result", None)
        st.info("No saved payments yet. Open the Sandbox tools section, enter a test amount, and click Create Sandbox Order. Approve and Capture it there, then return to Review payments.")
        return None
    rows = ["| Payment | Amount | Currency | Payment status |", "| --- | --- | --- | --- |"]
    for order in orders:
        cells = (short_payment_reference(order["order_id"]), f"{float(order['amount']):.2f}", order["currency"], order["status"])
        rows.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in cells) + " |")
    st.markdown("\n".join(rows))
    positions = {order_id: index + 1 for index, order_id in enumerate(orders_by_id)}
    # Restore by ID before registration, even when labels or order have changed.
    st.session_state["review_order_id"] = st.session_state["selected_payment_id"]
    selected_order_id = st.selectbox(
        "Select a payment",
        options=list(orders_by_id),
        format_func=lambda order_id: (
            f"{positions[order_id]}. {float(orders_by_id[order_id]['amount']):.2f} "
            f"{orders_by_id[order_id]['currency']} | {orders_by_id[order_id]['status']} "
            f"| {short_payment_reference(order_id)}"
        ),
        key="review_order_id",
        index=None,
        placeholder="Choose a payment",
        on_change=remember_payment_selection,
    )
    if st.button("Review payment", key="open_payment_review", type="primary", disabled=selected_order_id is None):
        st.session_state["opened_payment_id"] = selected_order_id
    opened_id = st.session_state.get("opened_payment_id")
    if not opened_id:
        st.info("Choose a payment and click Review payment to see its status and supporting records. No simulated baseline is required.")
        return None
    order = get_order(opened_id)
    if not order:
        clear_review()
        st.session_state.pop("opened_payment_id", None)
        st.session_state.pop("payment_check_result", None)
        st.warning("The previously opened payment is no longer available. Select a payment and click Review payment.")
        return None
    if selected_order_id is None:
        st.info(f"Select a payment and click Review payment. The overview below still shows {short_payment_reference(opened_id)}.")
    elif opened_id != selected_order_id:
        st.info(
            f"Selection changed. Click Review payment to open {short_payment_reference(selected_order_id)}. "
            f"The overview below still shows {short_payment_reference(opened_id)}."
        )
    return order


def render_payment_overview(order):
    st.subheader("Payment overview")
    status = order["status"]
    tone = "pg-paid" if status == "COMPLETED" else ("pg-terminal" if status in {"DENIED", "REFUNDED", "REVERSED"} else "pg-pending")
    st.markdown(
        '<section class="pg-payment-overview pg-summary" aria-label="Opened payment overview">'
        f'<p class="pg-order-id">Reviewing payment: {escape(short_payment_reference(order["order_id"]))}</p>'
        '<div class="pg-summary-grid"><div><p class="pg-label">Payment amount</p>'
        f'<p class="pg-amount">{float(order["amount"]):.2f} <span class="pg-currency">{escape(order["currency"])}</span></p></div>'
        '<div><p class="pg-label">Payment status</p>'
        f'<span class="pg-badge {tone}">{escape(status)}</span></div>'
        '<div><p class="pg-label">Source</p><p class="pg-review">Saved local record</p>'
        '<p class="pg-note">Not a live PayPal status check</p></div></div></section>',
        unsafe_allow_html=True,
    )


def checked_money(raw):
    """Parse supported two-decimal amounts without silently rounding."""
    try:
        value = Decimal(str(raw).strip())
        if not value.is_finite() or value <= 0:
            raise ValueError
        cents = value.quantize(Decimal("0.01"))
        if value != cents:
            raise ValueError
        return cents
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a positive, finite amount with at most two decimal places and up to 26 integer digits.") from None


def render_payment_check(order):
    with st.container(key="payment_expectation_check"):
        st.subheader("Check payment against your expectation")
        st.caption("Your expectation is user-provided and not externally verified. This checks saved order details only.")
        order_id = order["order_id"]
        amount_column, currency_column = st.columns(2)
        with amount_column:
            raw_amount = st.text_input("Expected amount", key=f"expected_amount_{order_id}")
        with currency_column:
            currencies = ("CAD", "USD", "EUR")
            currency = st.selectbox("Expected currency", currencies,
                                    index=currencies.index(order["currency"]) if order["currency"] in currencies else 0,
                                    key=f"expected_currency_{order_id}")
        snapshot = tuple(order.get(key) for key in ("order_id", "amount", "currency", "status", "capture_state", "capture_id", "updated_at"))
        signature = (snapshot, raw_amount, currency)
        pending = st.session_state.get("review_order_id") != order_id
        result = st.session_state.get("payment_check_result")
        if pending or (result and result["signature"] != signature):
            st.session_state.pop("payment_check_result", None)
            result = None
        if pending:
            st.info("Click Review payment to open the selected payment before checking it.")
        if st.button("Check payment", key="check_expected_payment", type="primary", disabled=pending):
            st.session_state.pop("payment_check_result", None)
            result = None
            try:
                expected = checked_money(raw_amount)
                if order["currency"] not in currencies:
                    raise ValueError("This check supports CAD, USD and EUR only; the recorded currency is unsupported.")
                try:
                    recorded = checked_money(order["amount"])
                except ValueError:
                    raise ValueError("The recorded order amount cannot be checked without rounding. No result was generated.") from None
                result = {"signature": signature, "expected": expected, "recorded": recorded}
                st.session_state["payment_check_result"] = result
            except ValueError as exc:
                st.error(str(exc))
        if not result:
            return
        expected, recorded = result["expected"], result["recorded"]
        same_currency = currency == order["currency"]
        if same_currency:
            difference = recorded - expected
            amount_check = "Match" if difference == 0 else ("Below expectation" if difference < 0 else "Above expectation")
            difference_text = (f"{abs(difference):.2f} {currency} " + ("below expected" if difference < 0 else "above expected")) if difference else f"0.00 {currency} — matches expectation"
        else:
            amount_check = "Not compared across currencies"
            difference_text = "Not calculated — currencies differ; no currency conversion."
        left, right = st.columns(2)
        left.metric("Expected payment", f"{expected:.2f} {currency}")
        right.metric("Recorded order amount", f"{recorded:.2f} {order['currency']}")
        st.write(f"Difference: {difference_text}")
        status = order["status"]
        uncertain = order.get("capture_state") in {"UNKNOWN", "IN_PROGRESS"}
        if status in {"REFUNDED", "REVERSED"}:
            status_check = f"Local status is {status}; this is not a currently completed payment."
        elif uncertain:
            status_check = f"Completion is unconfirmed: local status is {status}, capture state is {order['capture_state']}."
        elif status == "COMPLETED":
            status_check = "Local status is COMPLETED."
        elif status == "APPROVED":
            status_check = "Buyer approval is recorded; completed payment is not confirmed."
        else:
            status_check = f"Local status is {status}; completed payment is not confirmed."
        if not same_currency:
            summary = "The recorded order currency differs from your expectation."
        elif recorded == expected:
            summary = "The recorded order amount and currency match your expectation."
        else:
            direction = "below" if recorded < expected else "above"
            summary = f"The recorded order amount is {direction} your expectation."
        summary += " " + status_check
        if not same_currency or recorded != expected or status != "COMPLETED" or uncertain:
            st.warning(summary)
        else:
            st.info(summary)
        with st.expander("Details", expanded=False):
            st.write(f"Amount check: {amount_check}")
            st.write(f"Currency check: {'Match' if same_currency else 'Mismatch'}")
            st.write(f"Payment status check: {status_check}")
            st.write(f"Order ID: {order_id}")
            st.write(f"Capture ID: {order.get('capture_id') or 'Not recorded'}")
            st.caption("Recorded order amount comes from the locally saved order-creation amount and currency. It is not an independently verified Capture amount, net receipt, or bank settlement.")
            st.caption("Status comes from the saved local record, not a fresh PayPal query. This check does not verify receipt of funds or change the payment.")


def open_rule_analysis(order_id):
    st.session_state["open_rule_analysis_for"] = order_id


def render_inline_rule_analysis(selected_order):
    selected_order_id = selected_order["order_id"]
    st.caption("No saved review history. Any result shown below belongs to this session only.")
    order_amount = float(selected_order["amount"])
    currency = selected_order["currency"]
    st.markdown("**1. Set a simulated baseline**")
    average_amount = st.number_input(
        f"Simulated comparison baseline ({currency})",
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

    st.markdown("**2. Calculate the rule result**")
    if st.button("Calculate rule result", key="analyze_saved_order", type="primary"):
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
    render_order_summary(
        selected_order,
        analysis if st.session_state.get("risk_analysis_signature") == analysis_signature else None,
    )
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

    return analysis if st.session_state.get("risk_analysis_signature") == analysis_signature else None


def render_ai_rule_explanation(order):
    st.subheader("AI rule explanation")
    st.caption("Explains simulated rule results only. It does not verify the payment or review payment notifications.")
    if order["status"] != "COMPLETED":
        clear_review()
        st.button("Open rule analysis", key="open_rule_analysis", disabled=True)
        st.caption("Rule analysis is available only for completed payments. Payment records remain available below.")
        return
    signature = (
        order["order_id"], float(order["amount"]), order["currency"],
        st.session_state.get(f"simulated_average_{order['currency']}"),
    )
    valid = bool(st.session_state.get("risk_analysis")) and st.session_state.get("risk_analysis_signature") == signature
    opened = st.session_state.get("open_rule_analysis_for") == order["order_id"]
    if not opened and not valid:
        st.caption("Set a simulated baseline, calculate the rule result, then optionally request an AI explanation here.")
        st.button("Open rule analysis", key="open_rule_analysis", on_click=open_rule_analysis, args=(order["order_id"],))
    with st.expander("Simulated rule analysis", expanded=opened or valid):
        analysis = render_inline_rule_analysis(order)
        if not analysis:
            st.info("Calculate the rule result above before generating an AI explanation. AI is never requested automatically.")
            return
        st.markdown("**3. Generate an AI explanation manually**")
        if st.button("Generate AI Explanation", key="generate_ai_explanation", type="primary"):
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


def render_assumption_tools(selected_order):
    with st.expander("Explore assumptions", expanded=False):
        st.caption("Optional simulations. They do not verify payment records or change the payment.")
        if selected_order["status"] != "COMPLETED":
            clear_review()
            st.info("Assumption tools are available only for completed payments. Payment records remain available above.")
            return
        comparison_tab, amount_tab = st.tabs(["Compare baselines", "Hypothetical amount"])
        analysis = st.session_state.get("risk_analysis")
        analysis_signature = (
            selected_order["order_id"], float(selected_order["amount"]), selected_order["currency"],
            st.session_state.get(f"simulated_average_{selected_order['currency']}"),
        )
        with comparison_tab:
            render_baseline_sensitivity(selected_order)

        with amount_tab:
            if analysis and st.session_state.get("risk_analysis_signature") == analysis_signature:
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
            else:
                st.info("Calculate a rule result in AI rule explanation above first to explore a hypothetical amount.")


def render_payment():
    st.subheader("Create orders and payments")
    st.caption("Sandbox test payments. Browsing orders does not change the current payment target.")
    order_amount = st.number_input("Sandbox Order Amount (CAD)", min_value=0.01, value=10.00, step=1.00, key="sandbox_order_amount")

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
                    observation = get_order_status(
                        paypal_config["client_id"],
                        paypal_config["client_secret"],
                        paypal_order_id,
                    )
                except Exception:
                    st.error("Could not confirm the PayPal order status. The Capture result remains unconfirmed.")
                else:
                    remote_status, capture_id = observation
                    try:
                        record_payment_observation(paypal_order_id, observation)
                    except Exception:
                        st.error("Provider evidence could not be saved. No payment retry has been enabled.")
                        return
                    if remote_status == "COMPLETED":
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
                            observation = capture_order(
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
                            capture_status, capture_id = observation
                            try:
                                record_payment_observation(paypal_order_id, observation)
                            except Exception:
                                mark_capture_unknown(paypal_order_id)
                                st.error("Provider response could not be saved. Query status before any retry.")
                                return
                            if capture_status == "COMPLETED":
                                st.rerun()
                            else:
                                mark_capture_unknown(paypal_order_id)
                                st.rerun()

    else:
        st.info("No active payment order. Create a Sandbox order here to begin.")

def render_payment_records(selected_order):
    with st.container(key="payment_evidence"):
        st.subheader("Payment records")
        if selected_order:
            st.caption("Supporting records for the payment shown above. Buyer approval does not mean payment is complete.")
            events = get_order_events(selected_order["order_id"])
            linked_types = {
                event["event_type"] for event in events
                if event["processing_state"] != "LEGACY"
            }
            approval_evidence = "Linked approval notification" if "CHECKOUT.ORDER.APPROVED" in linked_types else "No linked record"
            completion_evidence = "Linked completion notification" if "PAYMENT.CAPTURE.COMPLETED" in linked_types else "No linked record"
            steps = (
                ("01", "Order created", "Local order record only", False),
                ("02", "Buyer approved", approval_evidence, "CHECKOUT.ORDER.APPROVED" in linked_types),
                ("03", "Payment completed", completion_evidence, "PAYMENT.CAPTURE.COMPLETED" in linked_types),
            )
            cards = ['<div class="pg-evidence-grid" aria-label="Payment workflow evidence">']
            for step, title, evidence, linked in steps:
                tone = "pg-evidence-linked" if linked else "pg-evidence-neutral"
                cards.append(
                    '<section class="pg-evidence-card">'
                    f'<p class="pg-evidence-number">{step}</p><h3>{title}</h3>'
                    f'<span class="pg-evidence-status {tone}">{escape(evidence)}</span></section>'
                )
            cards.append('</div>')
            st.markdown("".join(cards), unsafe_allow_html=True)
            st.caption(
                "Evidence comes from saved records. A missing notification does not mean payment failed."
            )

            with st.expander("Record details", expanded=False):
                st.write(f"Payment ID: {selected_order['order_id']}")
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

            with st.expander("Notification records", expanded=False):
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
            st.info("Select a payment and click Review payment to view its records.")


def render_merchant_reconciliation(order):
    evidence = get_sale_reconciliation(order["order_id"])
    order = evidence["order"]
    sale = evidence["sale"]
    if not sale:
        with st.expander("Merchant reconciliation", expanded=False):
            st.caption("Historical data insufficient — no merchant order link. Manual expectation checking below compares only the recorded order amount.")
        return False
    st.subheader("Merchant reconciliation")
    st.caption("Sandbox only. Compares immutable merchant terms with saved provider Capture evidence, not bank settlement or net proceeds.")
    st.caption("All reconciliation values use one local snapshot, not guaranteed to be the latest after reading. No automatic refresh or retry.")
    left, right = st.columns(2)
    left.metric("Merchant expected amount", f"{sale['amount']} {sale['currency']}")
    captures = evidence["captures"]
    if len(captures) == 1 and captures[0]["amount"] and captures[0]["currency"]:
        right.metric("Saved Sandbox Capture amount", f"{captures[0]['amount']} {captures[0]['currency']}")
    else:
        right.write("Capture amount: not confirmed as a single supported Capture")
    result = evidence["result"]
    if result["code"] == "MATCH":
        st.success(result["summary"])
    else:
        st.warning(result["summary"])
    with st.expander("Reconciliation evidence", expanded=False):
        st.write(f"Test sales order: {sale['sale_id']}")
        st.write(f"Local status in this snapshot: {order['status']}")
        for capture in captures:
            st.write(f"Capture: {capture['capture_id']} | Status: {capture['status'] or 'Not recorded'} | Final: {capture['final_capture']}")
            st.write(f"Amount observation source: {capture['source']} | Provider creation time: {capture['occurred_at'] or 'Not recorded'} | First locally stored: {capture['recorded_at']} UTC")
            st.write(f"Full Capture proof: {'Confirmed' if capture['full_capture_verified'] else 'Not confirmed'} | Provider purchase unit total: {capture['provider_order_amount'] or 'Not recorded'} {capture['provider_order_currency'] or ''}")
        if evidence["observations"]:
            st.markdown("**Saved Capture observations — including conflicting values**")
            st.table([{
                "Capture ID": item["capture_id"],
                "Amount": item["amount"] or "Not recorded",
                "Currency": item["currency"] or "Not recorded",
                "Source": item["source"],
                "Provider creation time": item["occurred_at"] or "Not recorded",
                "Locally stored (UTC)": item["recorded_at"],
                "Provider order amount": item["provider_order_amount"] or "Not recorded",
                "Provider order currency": item["provider_order_currency"] or "Not recorded",
            } for item in evidence["observations"]])
        for issue in evidence["issues"]:
            st.warning(issue)
        st.caption("Merchant terms are locally supplied test records, not externally verified invoices. Multiple or partial captures are not reconciled automatically. Refunds do not erase the historical Capture amount.")
    # A read-only provider GET is explicit and never issues a Capture request.
    if st.button("Refresh Capture evidence from PayPal", key="refresh_merchant_evidence"):
        try:
            settings = st.secrets["paypal"]
            observation = get_order_status(settings["client_id"], settings["client_secret"], order["order_id"])
            record_payment_observation(order["order_id"], observation)
            st.rerun()
        except Exception:
            st.error("Could not refresh and save provider evidence. Existing records were retained; no payment was initiated.")
    return True


def open_linked_payment(sale_id):
    """Select an existing linked payment and its saved retry identity, without creating anything."""
    sale = next((item for item in get_merchant_sales() if item["sale_id"] == sale_id), None)
    attempt = get_order_creation_attempt(sale["creation_request_id"]) if sale and sale["creation_request_id"] else None
    if not sale or not sale["paypal_order_id"] or not attempt or attempt["order_id"] != sale["paypal_order_id"]:
        st.session_state["merchant_navigation_error"] = "The saved payment link or creation attempt is unavailable. No payment was selected or created."
        return
    st.query_params["create_attempt"] = attempt["request_id"]
    st.query_params.pop("token", None)
    st.session_state["paypal_order_id"] = sale["paypal_order_id"]
    st.session_state["paypal_approval_url"] = attempt["approval_url"]
    st.session_state["main_navigation"] = "Sandbox tools"
    st.session_state.pop("merchant_navigation_error", None)


def render_merchant_orders():
    st.subheader("Test sales orders — Sandbox only")
    st.caption("Create a merchant expectation, then create exactly one linked PayPal order. Saved terms cannot be edited. Do not enter personal information.")
    with st.form("new_merchant_sale"):
        description = st.text_input("Test order description", max_chars=120)
        amount = st.text_input("Merchant expected amount (CAD)", value="10.00")
        saved = st.form_submit_button("Save test sales order")
    if saved:
        try:
            sale_id = create_merchant_sale(description, amount)
            st.success("Test sales order saved. Select it below to start its payment.")
        except ValueError as error:
            st.error(str(error))
    sales = get_merchant_sales()
    if not sales:
        st.info("No merchant sales orders yet. Save a test order above.")
        return
    by_id = {sale["sale_id"]: sale for sale in sales}
    selected = st.selectbox("Select a test sales order", list(by_id),
        format_func=lambda key: f"{by_id[key]['description']} | {by_id[key]['amount']} CAD | {key[-8:]}", key="merchant_sale_id")
    sale = by_id[selected]
    if st.session_state.get("merchant_navigation_error"):
        st.error(st.session_state["merchant_navigation_error"])
    st.write(f"Merchant order: {sale['sale_id']} | Expected: {sale['amount']} CAD")
    st.caption("Terms immutable from saving. Payment binding locked before the first provider request.")
    if st.button("Create or resume linked PayPal order", key="create_merchant_payment", type="primary"):
        try:
            attempt_id = begin_sale_creation(selected)
            attempt = get_order_creation_attempt(attempt_id)
            st.query_params["create_attempt"] = attempt_id
            st.query_params.pop("token", None)
            if not attempt["order_id"]:
                settings = st.secrets["paypal"]
                order_id, approval_url = create_order(settings["client_id"], settings["client_secret"], attempt["amount"], request_id=attempt_id)
                complete_order_creation(attempt_id, order_id, approval_url)
            attempt = get_order_creation_attempt(attempt_id)
            st.session_state["paypal_order_id"] = attempt["order_id"]
            st.session_state["paypal_approval_url"] = attempt["approval_url"]
            st.rerun()
        except Exception:
            st.error("Creation not confirmed. The saved attempt is retained; resume this same sales order, do not create a replacement to retry.")
    if sale["paypal_order_id"]:
        st.write(f"Linked PayPal order: {sale['paypal_order_id']}")
        st.info("Open Sandbox tools for this order's approval/Capture controls. View its saved reconciliation in Review payments.")
        st.button("Open payment in Sandbox tools", key="activate_merchant_payment",
                  on_click=open_linked_payment, args=(selected,))


# Preserve owned inputs while their section is not rendered by native navigation.
for input_key in list(st.session_state):
    if input_key in {"review_order_id", "merchant_sale_id", "sandbox_order_amount"} or (
        input_key.startswith(("simulated_average_", "expected_amount_", "expected_currency_", "sensitivity_baseline_", "what_if_amount_"))
        and "_preset_" not in input_key
    ):
        st.session_state[input_key] = st.session_state[input_key]
sections = ["Review payments", "Sandbox tools", "Test sales orders"]
initial_section = "Sandbox tools" if st.query_params.get("create_attempt") or st.query_params.get("token") else "Review payments"
if "main_navigation" not in st.session_state:
    st.session_state["main_navigation"] = initial_section
active_section = st.radio("Workspace", sections, horizontal=True, key="main_navigation")
if active_section == "Review payments":
    with st.container(key="workbench"):
        selected_order = render_payment_browser()
        if selected_order:
            render_payment_overview(selected_order)
            if not render_merchant_reconciliation(selected_order):
                render_payment_check(selected_order)
            render_ai_rule_explanation(selected_order)
            render_payment_records(selected_order)
            render_assumption_tools(selected_order)
elif active_section == "Sandbox tools":
    st.caption("Development tools for Sandbox test payments. This is separate from viewing payment records.")
    linked_payment_notice = st.container()
    render_authentication()
    render_payment()
    with linked_payment_notice:
        linked_sale = next((sale for sale in get_merchant_sales() if sale["paypal_order_id"] == st.session_state.get("paypal_order_id")), None)
        if linked_sale:
            st.info(f"Active linked PayPal order: {linked_sale['paypal_order_id']} | Test sales order: {linked_sale['sale_id']} | Expected: {linked_sale['amount']} {linked_sale['currency']}")

elif active_section == "Test sales orders":
    render_merchant_orders()
