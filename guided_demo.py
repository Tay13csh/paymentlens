"""Versioned, fixed in-memory examples. No database or payment module imports."""

from copy import deepcopy
from decimal import Decimal
import streamlit as st
from analysis_view import render_analysis_summary
from payment_evidence import reconcile_sale
from payment_assistant_ui import render_payment_assistant

VERSION = "v1"
CASES = ("Matching", "Amount difference", "Insufficient information", "Conflicting evidence", "Refunded")
CASE_QUESTIONS = {
    "Matching": ("Why does this example match?", "What evidence supports the match?", "Does a match prove bank settlement?"),
    "Amount difference": ("How far below the expectation is this Capture?", "Why is this an amount difference?", "What should I check manually?"),
    "Insufficient information": ("What information is missing?", "Why is buyer approval not enough?", "What evidence would help confirm completion?"),
    "Conflicting evidence": ("Why do these two Capture observations disagree?", "Can either observed amount be confirmed?", "What should I check manually?"),
    "Refunded": ("What does the refund mean for this example?", "Why does the older matching Capture not mean current collection?", "What should I check manually?"),
}
QUESTIONS = ("Does this example match?", "Why might this example need attention?", "What information is missing?")


def demo_snapshot(case):
    if case not in CASES:
        raise ValueError("Unknown example")
    case_id = "SIMULATED-" + VERSION + "-" + str(CASES.index(case))
    sale = {"sale_id": case_id + "-SALE", "description": "Simulated example", "amount": "12.00" if case == "Amount difference" else "10.00", "currency": "CAD"}
    order = {"order_id": case_id, "status": "REFUNDED" if case == "Refunded" else "COMPLETED", "capture_state": "COMPLETED", "updated_at": None}
    capture = {"capture_id": case_id + "-CAPTURE", "amount": "10.00", "currency": "CAD", "status": "COMPLETED", "final_capture": 1,
               "amount_pair_valid": 1, "full_capture_verified": 1, "conflict": int(case == "Conflicting evidence"),
               "provider_order_amount": "10.00", "provider_order_currency": "CAD", "source": "CAPTURE_RESPONSE", "occurred_at": None, "recorded_at": None}
    captures, observations = [capture], []
    if case == "Insufficient information":
        order.update(status="APPROVED", capture_state="READY")
        captures = []
    if case == "Conflicting evidence":
        observations = [dict(capture, amount="10.00", source="CAPTURE_RESPONSE"), dict(capture, amount="12.00", provider_order_amount="12.00", source="ORDER_QUERY")]
    return {"context": "guided_demo", "case_name": case, "case_version": VERSION, "sale": sale, "order": order, "captures": captures,
            "observations": observations, "issues": [], "result": reconcile_sale(sale, order, captures, [])}


def sample_explanation(evidence, question):
    """Templates use the computed result, never a separately hard-coded case verdict."""
    if question not in QUESTIONS:
        raise ValueError("Sample explanations cover only the listed example questions")
    result = evidence["result"]
    text = "In this simulated example: " + result["summary"] + ". "
    if result.get("difference"):
        difference = Decimal(result["difference"])
        if difference:
            text += f"The simulated Capture amount is {abs(difference):.2f} {result['currency']} {'below' if difference < 0 else 'above'} the example expectation. "
    if not evidence["captures"]:
        text += "An independent Capture and full-total proof are missing. Approval is not completed collection. "
    if "EVIDENCE_CONFLICT" in result["reasons"]:
        text += "Two conflicting observations are retained; neither is chosen as authoritative. "
    return text + "These are fabricated records, not evidence of a real transaction or bank settlement."




def render_guided_demo():
    st.warning("GUIDED DEMO — Simulated example. No actual payment or saved Sandbox record.")
    st.caption("Choose a case, review the result, then discuss it with the payment assistant. All values are simulated.")
    case = st.selectbox("Choose a simulated example", CASES, key="guided_demo_case")
    evidence = demo_snapshot(case)
    # Changing examples invalidates any pending response before either explanation surface renders.
    state = st.session_state.get("demo_payment_assistant_state")
    if state:
        state.bind(evidence)
    st.subheader("Simulated merchant reconciliation")
    render_analysis_summary(evidence)
    st.caption("Discussing: " + case)
    render_payment_assistant(evidence, lambda order_id: deepcopy(demo_snapshot(case)) if order_id == evidence["order"]["order_id"] else None,
                             context="guided_demo", quick_questions=CASE_QUESTIONS[case])
    with st.expander("View sample walkthrough", expanded=False):
        st.subheader("Sample explanation — not generated live")
        st.caption("A separate, fixed walkthrough based on this case's rule result. It does not answer arbitrary text in the chat and is never added to live conversation history.")
        question = st.selectbox("Sample walkthrough question", QUESTIONS, key="guided_sample_question_" + str(CASES.index(case)))
        st.write(sample_explanation(evidence, question))
    with st.expander("Simulated evidence", expanded=False):
        st.caption("All values and completeness proofs are fabricated premises. No occurrence times were supplied.")
        st.json({"expected": evidence["sale"]["amount"], "currency": "CAD", "captures": evidence["captures"], "conflict_observations": evidence["observations"], "reasons": evidence["result"]["reasons"]})
