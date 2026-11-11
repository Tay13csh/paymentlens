"""Streamlit payment chat. Provider and database writes are intentionally absent."""

import os
import hashlib
from pathlib import Path
from html import escape

import streamlit as st

from analysis_view import discussion_label
from ai_explanation import DEFAULT_MODEL
import payment_assistant as assistant


def assistant_settings():
    """Read optional runtime configuration safely; never display or persist keys."""
    try:
        settings = st.secrets.get("openai", {})
        key, model = settings.get("api_key"), settings.get("model", DEFAULT_MODEL)
        if all(isinstance(v, str) and v.strip() and not v.strip().upper().startswith("YOUR_") for v in (key, model)):
            return key, model
    except Exception:
        pass
    return None


def render_answer(turn, outdated=False):
    """Render the actual response first, with explicit colors and escaped plain text."""
    packet, answer = turn["packet"], turn["answer"]
    simulated = packet["scope"] == "simulated_example_not_actual_paypal_evidence"
    with st.chat_message("user"):
        st.markdown('<div class="payment-assistant-question" style="color:#13263d;background:#e5edf7;padding:0.7rem;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere">' + escape(turn["question"]) + '</div>', unsafe_allow_html=True)
    with st.chat_message("assistant"):
        if outdated:
            st.warning("Outdated conversation — previous records, not the current conclusion.")
        label = "Simulated · AI-generated · may be inaccurate" if simulated else "AI-generated · may be inaccurate"
        st.markdown(
            '<div class="payment-assistant-answer" aria-label="AI answer" style="color:#13263d;background:#ffffff;padding:1rem;border:1px solid #a9b9c9;border-radius:12px">'
            '<div style="color:#526277;font-size:0.8rem;margin-bottom:0.5rem">' + label + '</div>'
            '<div class="payment-assistant-answer-body" style="color:#13263d;font-size:1rem;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere">' + escape(answer["explanation"]) + '</div></div>',
            unsafe_allow_html=True,
        )
        if answer["general_checks"]:
            st.markdown('<div class="payment-assistant-checks" style="color:#13263d;background:#f4f7fb;padding:0.7rem;border-radius:10px">'
                        '<strong style="color:#13263d">General manual checks — suggestions</strong><ul>'
                        + ''.join('<li style="color:#13263d;overflow-wrap:anywhere">' + escape(text) + '</li>' for text in answer["general_checks"])
                        + '</ul></div>', unsafe_allow_html=True)
        with st.expander("Evidence used for this answer", expanded=False):
            st.markdown("**Simulated facts**" if simulated else "**Saved facts — supplied by the application**")
            conclusion = next(item["values"]["code"] for item in packet["evidence"] if item["kind"] == "application_reconciliation")
            status = next(item["values"]["status"] for item in packet["evidence"] if item["kind"] == "local_payment_state")
            st.markdown('<div style="color:#13263d;overflow-wrap:anywhere">' + escape(f"Application conclusion: {conclusion} | Local status: {status}") + '</div>', unsafe_allow_html=True)
            refs = set(answer["evidence_refs"])
            st.caption("References belong to this answer's snapshot; that check does not prove that the AI's wording or reasoning is correct.")
            st.caption("Simulated premises only; not actual payment or bank evidence." if simulated else "Saved Capture facts are not live PayPal checks, bank settlement or net proceeds. Times retain their stated meaning.")
            if refs:
                st.json([item for item in packet["evidence"] if item["ref"] in refs])
            else:
                st.caption("No evidence references supplied; unsupported information cannot be established.")
            with st.expander("Full fact packet supplied for this answer", expanded=False):
                st.json(packet)


def _render_payment_chat(evidence, read_snapshot, polling=False, context="sandbox", quick_questions=None):
    """Use the opened payment, never the pending selection or Sandbox action target."""
    expected_mode = "Guided demo" if context == "guided_demo" else "PayPal Sandbox"
    if st.session_state.get("application_mode", expected_mode) != expected_mode:
        return
    if context == "guided_demo" and st.session_state.get("guided_demo_case") != evidence.get("case_name"):
        return
    order_id = evidence["order"]["order_id"]
    if context == "sandbox" and (
        st.session_state.get("opened_payment_id", order_id) != order_id
        or st.session_state.get("main_navigation", "Review payments") != "Review payments"
    ):
        return
    ui_prefix = ("demo_" if context == "guided_demo" else "sandbox_") + order_id + "_"
    st.subheader("Live AI on simulated evidence" if context == "guided_demo" else "Payment assistant")
    if context == "sandbox":
        st.markdown('<div class="discussion-label" style="color:#13263d;overflow-wrap:anywhere"><strong>Discussing: </strong>' + escape(discussion_label(evidence)) + '</div>', unsafe_allow_html=True)
        if st.session_state.get("selected_payment_id", order_id) != order_id:
            st.warning("Selection pending. This assistant still discusses opened payment …" + order_id[-6:] + ". Click Review payment to change the discussion object.")
    st.caption("Ask about this simulated example. All facts are fabricated; this is not payment verification." if context == "guided_demo" else "Ask naturally and follow up about this payment's saved reconciliation records. AI explains; it does not verify or operate payments.")
    st.caption("Messages go to OpenAI only when sent; charges may apply. Do not enter personal information, descriptions, full identifiers or credentials. Screening cannot guarantee complete de-identification.")
    state_key = "demo_payment_assistant_state" if context == "guided_demo" else "payment_assistant_state"
    state = st.session_state.get(state_key)
    if state is None:
        state = assistant.AssistantState()
        st.session_state[state_key] = state
    # An already-open browser session can contain the older state class/marker.
    if not hasattr(state, "jobs"):
        upgraded = assistant.AssistantState()
        upgraded.sessions, upgraded.active = state.sessions, state.active
        state = upgraded
        st.session_state[state_key] = state
    try:
        session = state.bind(evidence)
        assistant.make_fact_packet(evidence)
    except assistant.PaymentAssistantError as error:
        st.info(str(error))
        return
    order_id = evidence["order"]["order_id"]
    response = assistant.take_response(state, order_id)
    if response:
        ticket, success, value = response
        try:
            if success:
                try:
                    after = read_snapshot(order_id)
                except Exception:
                    after = None
                state.finish(ticket, value, after)
            else:
                state.fail(ticket, str(value))
        except assistant.PaymentAssistantError as error:
            state.fail(ticket, str(error))
        except Exception:
            state.fail(ticket)
        finally:
            state.release_wait(ticket)
        st.rerun()
    if polling and session["pending"] is None:
        # Completion/cancellation/timeout must repaint the entire page, not just a stale widget tree.
        st.rerun()
    settings = assistant_settings()
    with st.expander("Assistant diagnostics — no message content", expanded=False):
        st.caption(f"Runtime PID {os.getpid()} | core {assistant.CODE_BUILD} | UI {CODE_BUILD} | polling 0.5s while pending")
        if context == "guided_demo":
            st.caption("Only the latest six successful exchanges for this snapshot are sent as context. No tools or automatic retries are available.")
        for event in session.get("diagnostics", []):
            st.text(f"{event['request']} · {event['stage']} · {event['elapsed_seconds']:.2f}s")
    if not settings:
        st.info("Live AI unavailable: configure OpenAI locally to discuss this case. Review the case or open View sample walkthrough below; the sample is not generated live and does not answer your typed question." if context == "guided_demo" else "Payment assistant unavailable: configure [openai] locally to send questions. Payment viewing, reconciliation and local rules still work. No example or live answer is generated.")
    elif context == "guided_demo":
        st.caption("Live AI uses this case's simulated evidence automatically. Quick questions send immediately; free text requires Send. Model access has not been verified by local configuration checks.")
    if context != "guided_demo":
        st.caption("Only the latest six successful exchanges for this snapshot are sent as context. No tools or automatic retries are available.")
    if session["notice"]:
        st.info(session["notice"])
    if session["archives"]:
        with st.expander("Outdated conversations — not current conclusions", expanded=False):
            st.caption("Evidence changed. These answers are retained for reference only and are never sent as current context. At most two older conversations are retained.")
            for archived in session["archives"]:
                for turn in archived:
                    render_answer(turn, outdated=True)
    for turn in session["turns"]:
        render_answer(turn)
    pending = session["pending"] is not None
    if pending:
        st.info("An assistant request is in progress. Additional sends are disabled.")
        phase = session.get("pending_phase", "unknown")
        elapsed = max(0, state.clock() - session.get("pending_started_at", state.clock()))
        st.caption(f"Request {session['pending'][:10]} · {phase} · {elapsed:.1f}s. Remote receipt and billing are not established by this local stage.")
        st.button("Cancel waiting", key=ui_prefix + "assistant_cancel_waiting", on_click=state.cancel_wait,
                  args=(evidence["order"]["order_id"], session["pending"]))
        st.caption("Cancel stops local waiting only. Remote processing may continue and charges may apply.")
    selected_question = None
    retry_requested = False
    # No columns: these full-width native buttons also work on narrow screens.
    for index, question in enumerate(quick_questions or assistant.QUICK_QUESTIONS):
        if st.button(question, key=ui_prefix + "assistant_quick_" + str(index), disabled=not settings or pending):
            selected_question = question
    order_id = evidence["order"]["order_id"]
    draft_key = ("demo_assistant_draft_" if context == "guided_demo" else "assistant_draft_") + order_id
    if selected_question is not None:
        session["draft"] = selected_question
    st.session_state[draft_key] = session["draft"]
    def remember_draft():
        with state.lock:
            saved = state.sessions.get(order_id)
            if saved is not None:
                saved["draft"] = st.session_state.get(draft_key, "")
    st.text_area("Ask about this case or follow up" if context == "guided_demo" else "Ask a follow-up about this payment", key=draft_key, max_chars=assistant.MAX_QUESTION,
                 on_change=remember_draft, disabled=pending)
    # A focused text area may still have an unsynced browser edit. Do not disable
    # Send based on the previous server draft: clicking submits the widget state,
    # and the callback preserves that latest value before this fragment reruns.
    # Empty/whitespace input is rejected by validate_question before any request.
    if st.button("Send question", key=ui_prefix + "assistant_send", type="primary", disabled=not settings or pending,
                 on_click=remember_draft):
        selected_question = st.session_state.get(draft_key, "")
    if session["error"]:
        st.error(session["error"])
    if session["retry"]:
        if st.button("Retry failed question", key=ui_prefix + "assistant_retry", disabled=not settings or pending or session["draft"] != session.get("failed_question")):
            selected_question = session.get("failed_question") or session["draft"]
            retry_requested = True
    if st.button("Clear conversation", key=ui_prefix + "assistant_clear", on_click=state.clear):
        st.rerun()
    if selected_question is None or not settings:
        return
    ticket = None
    launched = False
    session["draft"] = selected_question
    try:
        assistant.validate_question(selected_question, assistant.private_values(evidence))
        fresh = read_snapshot(order_id)
        if not fresh or not fresh.get("order") or fresh["order"].get("order_id") != order_id:
            session.update(error="Could not read current records. Your draft is retained; no question was sent.", retry=False)
        elif assistant.fingerprint(fresh) != assistant.fingerprint(evidence):
            state.bind(fresh)
        else:
            ticket = state.begin(fresh, selected_question, allow_retry=retry_requested)
            if ticket:
                request_function = assistant.ask_payment
                with st.spinner("Scheduling this saved-snapshot request…"):
                    assistant.start_request(state, ticket, lambda: request_function(
                        settings[0], settings[1], ticket["packet"], ticket["question"], ticket["history"],
                        assistant.private_values(fresh), progress=lambda stage: state.stage(ticket, stage)))
                    launched = True
    except assistant.PaymentAssistantError as error:
        if ticket:
            state.fail(ticket, str(error))
        else:
            session.update(error=str(error), retry=False)
    except Exception:
        if ticket:
            state.fail(ticket)
        else:
            session.update(error="Could not read the current snapshot. Nothing was sent; your draft is retained.", retry=False)
    finally:
        if ticket and not launched:
            state.release_wait(ticket)
    st.rerun()


CODE_BUILD = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def render_payment_assistant(evidence, read_snapshot, context="sandbox", quick_questions=None):
    """Only an active wait schedules fragment ticks; idle typing is not refreshed."""
    state_key = "demo_payment_assistant_state" if context == "guided_demo" else "payment_assistant_state"
    state = st.session_state.get(state_key)
    order_id = evidence["order"]["order_id"]
    session = state.sessions.get(order_id, {}) if state is not None else {}
    polling = session.get("pending") is not None
    fragment = st.fragment(run_every=0.5 if polling else None)(_render_payment_chat)
    fragment(evidence, read_snapshot, polling, context, quick_questions)
