"""Pure presentation of an existing reconciliation snapshot; no storage/actions."""

from html import escape
import streamlit as st


def render_analysis_summary(evidence):
    """Expose disputed observations without choosing a canonical amount as truth."""
    simulated = evidence.get("context") == "guided_demo"
    conflict = "EVIDENCE_CONFLICT" in evidence["result"]["reasons"]
    def display(value):
        return str(value) if value is not None else "Not recorded"
    st.markdown("""
    <style>
    .guided-status-summary, .guided-observation {
        background: #e5edf7; color: #13263d; border: 1px solid #a9b9c9;
        border-radius: 12px; padding: 1rem; margin: 0.7rem 0;
        overflow-wrap: anywhere;
    }
    .guided-status-summary strong, .guided-status-summary span,
    .guided-observation p, .guided-observation strong { color: #13263d; }
    .guided-status-summary { display: flex; flex-wrap: wrap; gap: 1rem 2rem; }
    .guided-observations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
    .guided-observation { background: #ffffff; margin: 0; }
    .guided-observation .guided-observed-money { color: #13263d; font-size: 1.5rem; font-weight: 700; }
    @media (max-width: 900px) { .guided-observations { grid-template-columns: minmax(0, 1fr); } }
    </style>
    """, unsafe_allow_html=True)
    left, right = st.columns(2)
    sale = evidence["sale"]
    left.metric("Simulated merchant expectation" if simulated else "Merchant expected amount",
                display(sale["amount"]) + " " + display(sale["currency"]) if sale else "No merchant order linked")
    if conflict:
        capture_amount = "Amount disputed"
    elif len(evidence["captures"]) == 1:
        capture = evidence["captures"][0]
        capture_amount = (display(capture["amount"]) + " " + display(capture["currency"])) if capture.get("amount_pair_valid") and capture.get("amount") and capture.get("currency") else "Unconfirmed amount"
    elif len(evidence["captures"]) > 1:
        capture_amount = "Multiple Capture records"
    else:
        capture_amount = "Not recorded"
    right.metric("Simulated Capture amount" if simulated else "Capture evidence", capture_amount)
    st.caption("Simulated premises only." if simulated else "Merchant terms are local records. Capture evidence is saved provider data, not a live query or bank settlement.")
    st.markdown(
        '<div class="guided-status-summary" aria-label="Payment status and rule conclusion">' +
        ('<span>Simulated current status: <strong>' if simulated else '<span>Current local status: <strong>') + escape(evidence["order"]["status"]) + '</strong></span>'
        '<span>Rule conclusion: <strong>' + escape(evidence["result"]["code"]) + '</strong></span></div>',
        unsafe_allow_html=True,
    )
    capture_statuses = sorted({str(item.get("status") or "Not recorded") for item in evidence["captures"]})
    st.caption(("Simulated Capture record status: " if simulated else "Saved Capture record status: ") +
               (", ".join(capture_statuses) if capture_statuses else "Not recorded") +
               ". A historical completed Capture does not override the current local payment status.")
    if conflict:
        observations = evidence["observations"]
        identities = {o["capture_id"] for o in observations}
        if len(identities) == 1:
            st.caption("Both observations refer to the same simulated Capture: " + next(iter(identities)) if simulated else "These observations refer to the same recorded Capture. Full references are available in Reconciliation evidence.")
        labels = {"CAPTURE_RESPONSE": "Capture response", "ORDER_QUERY": "Order query", "VERIFIED_WEBHOOK": "Verified Webhook"}
        cards = ['<div class="guided-observations" aria-label="Conflicting Capture observations">']
        for index, observation in enumerate(observations, 1):
            cards.append(
                '<section class="guided-observation"><strong>Observation ' + str(index) + '</strong>'
                '<p class="guided-observed-money">' + escape(display(observation["amount"])) + ' ' + escape(display(observation["currency"])) + '</p>'
                '<p>Source: ' + escape(("Simulated " if simulated else "Saved ") + labels.get(observation["source"], "unrecognized source")) + ' (' + escape(observation["source"]) + ')</p>' +
                ('<p>Simulated Capture: ' + escape(observation["capture_id"]) if simulated else '<p>Capture: ' + ('same recorded Capture' if len(identities) == 1 else '…' + escape(observation["capture_id"][-6:]))) + '</p></section>'
            )
        cards.append('</div>')
        st.markdown("".join(cards), unsafe_allow_html=True)
        st.info(("The simulated records disagree. " if simulated else "The saved records disagree. ") + "Neither observed amount is confirmed as authoritative; manual review is required. This evidence conflict is not a confirmed difference from the merchant expectation.")
    if simulated:
        st.write(evidence["result"]["summary"])
    elif evidence["result"]["code"] == "MATCH":
        st.success(evidence["result"]["summary"])
    else:
        st.warning(evidence["result"]["summary"])



def discussion_label(evidence):
    """Local UI identity only; not part of any model payload."""
    if evidence.get("context") == "guided_demo":
        return evidence["case_name"]
    sale = evidence.get("sale") or {}
    order = evidence["order"]
    description = sale.get("description") or "No linked merchant description"
    return description + " · recorded order " + str(order.get("amount", "Not recorded")) + " " + str(order.get("currency", "")) + " · …" + order["order_id"][-6:]
