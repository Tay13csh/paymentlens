"""Offline mode isolation, fabricated evidence and configuration boundaries."""

from contextlib import ExitStack
from copy import deepcopy
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import json
import sqlite3

import streamlit as st
from streamlit.testing.v1 import AppTest
from fastapi import HTTPException

import guided_demo as demo
import order_store as store
import paypal_auth
import webhook_server
import payment_assistant as assistant
from payment_evidence import reconcile_sale
from runtime_config import configuration_status

ROOT = Path(__file__).resolve().parents[1]


class GuidedDemoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "isolated.db"
        self.start(patch.object(store, "DATABASE_PATH", self.db))
        self.start(patch.object(st, "secrets", {}))
        self.api = self.start(patch.object(assistant, "ask_payment", side_effect=AssertionError("No implicit AI request")))
        self.providers = [self.start(patch.object(paypal_auth, name, side_effect=AssertionError("No PayPal request")))
                          for name in ("get_access_token", "create_order", "capture_order", "get_order_status")]

    def start(self, patcher):
        result=patcher.start();self.addCleanup(patcher.stop);return result

    def tearDown(self):
        for call in self.providers:call.assert_not_called()

    def app(self):
        app=AppTest.from_file(str(ROOT / "app.py")).run()
        self.assertFalse(app.exception)
        return app

    def chat_key(self, app, name):
        case=app.selectbox(key="guided_demo_case").value
        return "demo_" + demo.demo_snapshot(case)["order"]["order_id"] + "_assistant_" + name

    def settle(self, app):
        import time
        for _ in range(30):
            state=app.session_state["demo_payment_assistant_state"]
            if not state.sessions[state.active]["pending"]:return
            time.sleep(.005);app.run()
        self.fail("Mock case request did not settle")

    def forbid_database(self):
        stack=ExitStack()
        for name,value in vars(store).items():
            if callable(value) and getattr(value,"__module__",None)=="order_store":
                stack.enter_context(patch.object(store,name,side_effect=AssertionError("Demo must not access database")))
        stack.enter_context(patch.object(sqlite3,"connect",side_effect=AssertionError("Demo SQLite forbidden")))
        return stack

    def test_all_five_cases_use_original_rules_and_preserve_conflict_sides(self):
        expected=["MATCH","DIFFERENCE","INCOMPLETE","REVIEW","TERMINAL"]
        for case,code in zip(demo.CASES,expected):
            evidence=demo.demo_snapshot(case)
            self.assertEqual(evidence["result"],reconcile_sale(evidence["sale"],evidence["order"],evidence["captures"],evidence["issues"]))
            self.assertEqual(evidence["result"]["code"],code)
            self.assertIn(evidence["result"]["summary"],demo.sample_explanation(evidence,demo.QUESTIONS[0]))
            packet=assistant.make_fact_packet(evidence)
            self.assertEqual(packet["scope"],"simulated_example_not_actual_paypal_evidence")
            self.assertTrue(all(e["simulated"] for e in packet["evidence"]))
        conflict=demo.demo_snapshot("Conflicting evidence")
        self.assertEqual({o["amount"] for o in conflict["observations"]},{"10.00","12.00"})
        refund=demo.demo_snapshot("Refunded")
        self.assertEqual(refund["order"]["status"],"REFUNDED")
        with self.assertRaises(ValueError):demo.sample_explanation(refund,"An arbitrary free question")
        conflict["sale"]["amount"]="999.00"
        self.assertEqual(demo.demo_snapshot("Conflicting evidence")["sale"]["amount"],"10.00")

    def test_no_configuration_defaults_demo_and_every_case_has_no_database_access(self):
        with self.forbid_database():
            app=self.app()
            self.assertEqual(app.radio(key="application_mode").value,"Guided demo")
            for case in demo.CASES:
                app.selectbox(key="guided_demo_case").select(case).run()
                self.assertFalse(app.exception)
                self.assertTrue(any(x.value=="Sample explanation — not generated live" for x in app.subheader))
                self.assertEqual(len(app.text_area),1)
                self.assertTrue(app.button(key=self.chat_key(app,"send")).disabled)
                self.assertTrue(any(x.label=="View sample walkthrough" for x in app.expander))
            self.assertTrue(app.button(key=self.chat_key(app,"send")).disabled)
            self.assertTrue(any("unavailable" in x.value.lower() for x in app.info))
            self.api.assert_not_called()
        self.assertFalse(self.db.exists())

    def test_conflict_summary_shows_both_observations_not_a_confirmed_capture_amount(self):
        with self.forbid_database():
            app=self.app()
            app.selectbox(key="guided_demo_case").select("Conflicting evidence").run()
            self.assertFalse(app.exception)
            metric=next(item for item in app.metric if item.label=="Simulated Capture amount")
            self.assertEqual(metric.value,"Amount disputed")
            cards=next(item.value for item in app.markdown if item.value.startswith('<div class="guided-observations"'))
            self.assertIn("10.00 CAD",cards)
            self.assertIn("12.00 CAD",cards)
            self.assertIn("CAPTURE_RESPONSE",cards)
            self.assertIn("ORDER_QUERY",cards)
            evidence=demo.demo_snapshot("Conflicting evidence")
            capture_id=evidence["captures"][0]["capture_id"]
            self.assertEqual(cards.count(capture_id),2)
            self.assertTrue(any("same simulated Capture" in item.value for item in app.caption))
            self.assertTrue(any("manual review is required" in item.value and "not a confirmed difference" in item.value for item in app.info))
            status=next(item.value for item in app.markdown if item.value.startswith('<div class="guided-status-summary"'))
            self.assertIn("COMPLETED",status)
            self.assertIn("REVIEW",status)
            self.assertNotIn("AMOUNT_DIFFERENCE",evidence["result"]["reasons"])
            self.api.assert_not_called()

    def test_every_demo_state_has_explicit_contrast_and_conflict_cards_stack(self):
        with self.forbid_database():
            app=self.app()
            for case in demo.CASES:
                app.selectbox(key="guided_demo_case").select(case).run()
                status=next(item.value for item in app.markdown if item.value.startswith('<div class="guided-status-summary"'))
                evidence=demo.demo_snapshot(case)
                self.assertIn(evidence["order"]["status"],status)
                self.assertIn(evidence["result"]["code"],status)
                style=next(item.value for item in app.markdown if '.guided-status-summary strong' in item.value)
                self.assertIn("color: #13263d",style)
                self.assertIn("background: #e5edf7",style)
                self.assertIn("grid-template-columns: minmax(0, 1fr)",style)
                metric=next(item for item in app.metric if item.label=="Simulated Capture amount")
                self.assertEqual(metric.value,"Amount disputed" if case=="Conflicting evidence" else "Not recorded" if case=="Insufficient information" else "10.00 CAD")
                self.assertFalse(app.exception)

    def test_mode_and_return_parameters_survive_demo_refresh_without_target_mutation(self):
        with self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"))
            app.query_params.update({"mode":"demo","token":"PRESERVED-RETURN","create_attempt":"PRESERVED-ATTEMPT"})
            app.session_state["paypal_order_id"]="SEPARATE-TARGET"
            app.run();app.run()
            self.assertEqual(app.radio(key="application_mode").value,"Guided demo")
            self.assertEqual(app.session_state["paypal_order_id"],"SEPARATE-TARGET")
            self.assertEqual(app.query_params["token"],["PRESERVED-RETURN"])
            self.assertEqual(app.query_params["create_attempt"],["PRESERVED-ATTEMPT"])
            fresh=AppTest.from_file(str(ROOT/"app.py"))
            fresh.query_params.update({"mode":"demo","token":"PRESERVED-RETURN","create_attempt":"PRESERVED-ATTEMPT"})
            fresh.run()
            self.assertEqual(fresh.radio(key="application_mode").value,"Guided demo")
            self.assertNotIn("paypal_order_id",fresh.session_state)

    def test_fresh_return_or_creation_attempt_selects_sandbox_without_a_new_request(self):
        for key in ("token","create_attempt"):
            app=AppTest.from_file(str(ROOT/"app.py"))
            app.query_params[key]="SYNTHETIC-RETURN"
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio(key="application_mode").value,"PayPal Sandbox")
            self.assertEqual(app.radio(key="main_navigation").value,"Sandbox tools")
        self.api.assert_not_called()

    def test_configuration_status_never_exposes_values_or_asserts_online_validity(self):
        status,cap=configuration_status({"paypal":{"client_id":"private-value-not-to-display","client_secret":"YOUR_SANDBOX_SECRET"},"openai":{"api_key":32}})
        text=json.dumps(status)
        self.assertNotIn("private-value",text)
        self.assertIn("Placeholder",text)
        self.assertIn("Format problem",text)
        self.assertFalse(cap["paypal"])
        self.assertFalse(cap["ai"])
        status,cap=configuration_status({"paypal":{"client_id":"synthetic-client","client_secret":"synthetic-secret"}})
        self.assertTrue(cap["paypal"])
        self.assertFalse(cap["webhook"])
        self.assertIn("not verified online",status["paypal.client_id"])

    def test_demo_live_chat_is_explicit_and_separate_from_sample_and_sandbox(self):
        with patch.object(st,"secrets",{"openai":{"api_key":"synthetic-key","model":"synthetic-model"}}),self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"))
            app.session_state["application_mode"]="Guided demo"
            sandbox=assistant.AssistantState();evidence=demo.demo_snapshot("Matching")
            evidence["context"]="sandbox"
            sandbox.bind(evidence);sandbox.sessions[sandbox.active]["draft"]="Preserved Sandbox question"
            app.session_state["payment_assistant_state"]=sandbox
            app.run()
            self.api.assert_not_called()
            self.assertTrue(any(x.value=="Discussing: Matching" for x in app.caption))
            self.assertFalse(app.button(key=self.chat_key(app,"quick_0")).disabled)
            self.api.assert_not_called()
            self.api.side_effect=None
            self.api.return_value={"explanation":"This is a simulated example only.","general_checks":[],"evidence_refs":["E1","E3"]}
            app.button(key=self.chat_key(app,"quick_0")).click().run()
            import time
            for _ in range(20):
                state=app.session_state["demo_payment_assistant_state"]
                if not state.sessions[state.active]["pending"]:break
                time.sleep(.005);app.run()
            self.assertFalse(app.exception)
            self.api.assert_called_once()
            self.assertEqual(self.api.call_args.args[2]["scope"],"simulated_example_not_actual_paypal_evidence")
            self.assertEqual(sandbox.sessions[sandbox.active]["draft"],"Preserved Sandbox question")
            app.selectbox(key="guided_demo_case").select("Refunded").run()
            state=app.session_state["demo_payment_assistant_state"]
            self.assertFalse(state.sessions[state.active]["turns"])
            self.assertEqual(self.api.call_count,1)

    def test_experience_selector_is_in_main_content_not_collapsible_sidebar(self):
        app=self.app()
        self.assertTrue(any(item.key=="application_mode" for item in app.radio))
        self.assertFalse(any(item.key=="application_mode" for item in app.sidebar.radio))
        self.assertTrue(any(".st-key-experience_navigation" in item.value and "flex-wrap: wrap" in item.value for item in app.markdown))

    def test_question_specific_answers_are_visible_and_followup_evidence_matches_case(self):
        settings={"openai":{"api_key":"synthetic-key","model":"synthetic-model"}}
        matching="The example expects 10.00 CAD and records a completed 10.00 CAD Capture with matching currency and full-total proof."
        bank="No. Matching saved Capture evidence does not prove bank arrival; no bank settlement record is supplied."
        conflict="The same simulated Capture has two conflicting observations: 10.00 CAD from the Capture response and 12.00 CAD from the order query. Neither amount can be confirmed."
        def respond(*args,**kwargs):
            packet,question,history=args[2:5]
            rule=next(item["values"] for item in packet["evidence"] if item["kind"]=="application_reconciliation")
            if rule["code"]=="REVIEW":
                refs=[item["ref"] for item in packet["evidence"] if item["kind"]=="capture_observation"]
                return {"explanation":conflict,"general_checks":["Inspect both source records manually."],"evidence_refs":refs}
            if "bank" in question.lower():
                self.assertEqual(len(history),1)
                self.assertEqual(history[0]["answer"]["explanation"],matching)
                return {"explanation":bank,"general_checks":[],"evidence_refs":["E2","E3"]}
            self.assertEqual(history,[])
            return {"explanation":matching,"general_checks":[],"evidence_refs":["E1","E3","E4"]}
        self.api.side_effect=respond
        with patch.object(st,"secrets",settings),self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"));app.session_state["application_mode"]="Guided demo";app.run()
            app.button(key=self.chat_key(app,"quick_0")).click().run();self.settle(app)
            bodies=[item.value for item in app.markdown if item.value.startswith('<div class="payment-assistant-answer"')]
            self.assertTrue(any(matching in text for text in bodies))
            oid=demo.demo_snapshot("Matching")["order"]["order_id"]
            app.text_area(key="demo_assistant_draft_"+oid).set_value("Does that prove the money arrived at the bank?").run()
            app.button(key=self.chat_key(app,"send")).click().run();self.settle(app)
            bodies=[item.value for item in app.markdown if item.value.startswith('<div class="payment-assistant-answer"')]
            self.assertEqual(len(bodies),2)
            self.assertIn(bank,bodies[-1])
            app.selectbox(key="guided_demo_case").select("Conflicting evidence").run()
            app.button(key=self.chat_key(app,"quick_0")).click().run();self.settle(app)
            bodies=[item.value for item in app.markdown if item.value.startswith('<div class="payment-assistant-answer"')]
            self.assertEqual(len(bodies),1)
            self.assertIn(conflict,bodies[0])
            self.assertNotIn(matching,bodies[0])
            state=app.session_state["demo_payment_assistant_state"]
            turn=state.sessions[state.active]["turns"][0]
            refs=set(turn["answer"]["evidence_refs"])
            pairs=[e["values"]["money"]["amount"] for e in turn["packet"]["evidence"] if e["ref"] in refs]
            self.assertEqual(set(pairs),{"10.00","12.00"})
            self.assertFalse(app.exception)
            self.assertEqual(self.api.call_count,3)

    def test_actual_answer_is_escaped_wrapped_and_outside_evidence_details(self):
        settings={"openai":{"api_key":"synthetic-key","model":"synthetic-model"}}
        self.api.side_effect=None
        self.api.return_value={"explanation":"Compare <strong>10.00 CAD</strong> with 10.00 CAD.\nNo bank evidence is supplied.","general_checks":["Check <records> manually."],"evidence_refs":["E1","E3"]}
        with patch.object(st,"secrets",settings),self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"));app.session_state["application_mode"]="Guided demo";app.run()
            app.button(key=self.chat_key(app,"quick_0")).click().run();self.settle(app)
            body=next(item.value for item in app.markdown if item.value.startswith('<div class="payment-assistant-answer"'))
            self.assertIn("&lt;strong&gt;10.00 CAD&lt;/strong&gt;",body)
            self.assertNotIn("<strong>10.00 CAD</strong>",body)
            self.assertIn("color:#13263d",body)
            self.assertIn("background:#ffffff",body)
            self.assertIn("white-space:pre-wrap",body)
            self.assertIn("overflow-wrap:anywhere",body)
            details=next(item for item in app.expander if item.label=="Evidence used for this answer")
            self.assertFalse(any(item.value.startswith('<div class="payment-assistant-answer"') for item in details.markdown))
            self.assertTrue(any("&lt;records&gt;" in item.value for item in app.markdown))
            self.assertFalse(app.exception)

    def test_case_specific_questions_and_natural_followups_use_current_evidence(self):
        settings={"openai":{"api_key":"synthetic-key","model":"synthetic-model"}}
        with patch.object(st,"secrets",settings),self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"));app.session_state["application_mode"]="Guided demo";app.run()
            self.api.side_effect=None
            self.api.return_value={"explanation":"A mock explanation of this simulated case.","general_checks":["Compare the example records manually."],"evidence_refs":["E1","E3"]}
            for index,case in enumerate(demo.CASES):
                app.selectbox(key="guided_demo_case").select(case).run()
                self.assertTrue(any(item.value=="Discussing: "+case for item in app.caption))
                self.assertEqual(app.button(key=self.chat_key(app,"quick_0")).label,demo.CASE_QUESTIONS[case][0])
                self.assertEqual(self.api.call_count,index)
                app.button(key=self.chat_key(app,"quick_0")).click().run();self.settle(app)
                packet=self.api.call_args.args[2]
                rule=next(item["values"] for item in packet["evidence"] if item["kind"]=="application_reconciliation")
                self.assertEqual(rule["code"],demo.demo_snapshot(case)["result"]["code"])
                self.assertEqual(self.api.call_args.args[3],demo.CASE_QUESTIONS[case][0])
                self.assertEqual(self.api.call_args.args[4],[])
            app.selectbox(key="guided_demo_case").select("Matching").run()
            oid=demo.demo_snapshot("Matching")["order"]["order_id"]
            app.text_area(key="demo_assistant_draft_"+oid).set_value("Could you explain this simulated example in simpler terms?").run()
            self.assertEqual(self.api.call_count,5)
            app.button(key=self.chat_key(app,"send")).click().run();self.settle(app)
            self.assertEqual(self.api.call_count,6)
            self.assertEqual(self.api.call_args.args[3],"Could you explain this simulated example in simpler terms?")
            self.assertEqual(len(self.api.call_args.args[4]),1)
            self.assertEqual(len(app.text_area),1)
            self.assertTrue(any(item.label=="View sample walkthrough" for item in app.expander))
            self.assertFalse(app.exception)

    def test_conflict_answer_can_reference_both_observations_and_preserves_review(self):
        settings={"openai":{"api_key":"synthetic-key","model":"synthetic-model"}}
        def respond(*args,**kwargs):
            packet=args[2]
            observations=[item for item in packet["evidence"] if item["kind"]=="capture_observation"]
            self.assertEqual({item["values"]["money"]["amount"] for item in observations},{"10.00","12.00"})
            self.assertEqual(len({item["values"]["alias"] for item in observations}),1)
            return {"explanation":"The two simulated observations disagree; neither is confirmed.","general_checks":["Review both example sources manually."],"evidence_refs":[item["ref"] for item in observations]}
        self.api.side_effect=respond
        with patch.object(st,"secrets",settings),self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"));app.session_state["application_mode"]="Guided demo";app.run()
            app.selectbox(key="guided_demo_case").select("Conflicting evidence").run()
            app.button(key=self.chat_key(app,"quick_0")).click().run();self.settle(app)
            state=app.session_state["demo_payment_assistant_state"]
            turn=state.sessions[state.active]["turns"][0]
            refs=set(turn["answer"]["evidence_refs"])
            self.assertEqual(len(refs),2)
            cited=[item for item in turn["packet"]["evidence"] if item["ref"] in refs]
            self.assertEqual({item["values"]["money"]["amount"] for item in cited},{"10.00","12.00"})
            rule=next(item["values"] for item in turn["packet"]["evidence"] if item["kind"]=="application_reconciliation")
            self.assertEqual(rule["code"],"REVIEW")
            self.assertIsNone(rule["difference"])
            self.assertEqual(next(item.value for item in app.metric if item.label=="Simulated Capture amount"),"Amount disputed")
            self.assertTrue(any(item.label=="Evidence used for this answer" for item in app.expander))
            self.assertFalse(app.exception)

    def test_case_switch_preserves_drafts_and_discards_late_result(self):
        from threading import Event
        settings={"openai":{"api_key":"synthetic-key","model":"synthetic-model"}}
        entered,release,exited=Event(),Event(),Event()
        def delayed(*args,**kwargs):
            entered.set()
            try:
                self.assertTrue(release.wait(3))
                return {"explanation":"A late mock explanation.","general_checks":[],"evidence_refs":["E1"]}
            finally:exited.set()
        self.api.side_effect=delayed
        with patch.object(st,"secrets",settings),self.forbid_database():
            app=AppTest.from_file(str(ROOT/"app.py"));app.session_state["application_mode"]="Guided demo";app.run()
            a_id=demo.demo_snapshot("Matching")["order"]["order_id"]
            b_id=demo.demo_snapshot("Refunded")["order"]["order_id"]
            try:
                app.button(key=self.chat_key(app,"quick_0")).click().run()
                self.assertTrue(entered.wait(1))
                app.selectbox(key="guided_demo_case").select("Refunded").run()
                state=app.session_state["demo_payment_assistant_state"]
                self.assertEqual(state.active,b_id)
                self.assertFalse(state.sessions[b_id]["turns"])
                self.assertEqual(state.sessions[b_id]["draft"],"")
                self.assertIsNone(state.sessions[a_id]["pending"])
                self.assertEqual(state.sessions[a_id]["draft"],demo.CASE_QUESTIONS["Matching"][0])
                app.text_area(key="demo_assistant_draft_"+b_id).set_value("Explain the refund status next.").run()
            finally:
                release.set();self.assertTrue(exited.wait(2))
            app.run()
            self.assertFalse(state.sessions[b_id]["turns"])
            self.assertFalse(state.sessions[a_id]["turns"])
            app.selectbox(key="guided_demo_case").select("Matching").run()
            self.assertEqual(app.text_area(key="demo_assistant_draft_"+a_id).value,demo.CASE_QUESTIONS["Matching"][0])
            app.selectbox(key="guided_demo_case").select("Refunded").run()
            self.assertEqual(app.text_area(key="demo_assistant_draft_"+b_id).value,"Explain the refund status next.")
            self.api.assert_called_once()
            self.assertFalse(app.exception)

    def test_unconfigured_free_question_is_not_answered_by_sample_walkthrough(self):
        with self.forbid_database():
            app=self.app()
            oid=demo.demo_snapshot("Matching")["order"]["order_id"]
            app.text_area(key="demo_assistant_draft_"+oid).set_value("Please answer my arbitrary free question.").run()
            self.assertTrue(app.button(key=self.chat_key(app,"send")).disabled)
            state=app.session_state["demo_payment_assistant_state"]
            self.assertFalse(state.sessions[state.active]["turns"])
            sample=next(item for item in app.expander if item.label=="View sample walkthrough")
            self.assertTrue(any(item.value=="Sample explanation — not generated live" for item in sample.subheader))
            self.assertFalse(sample.chat_message)
            self.api.assert_not_called()

    def test_switching_mode_cancels_wait_without_losing_sandbox_target_or_draft(self):
        app=AppTest.from_file(str(ROOT/"app.py"))
        app.session_state["application_mode"]="PayPal Sandbox"
        sandbox=assistant.AssistantState();evidence=demo.demo_snapshot("Matching")
        evidence["context"]="sandbox"
        session=sandbox.bind(evidence)
        ticket=sandbox.begin(evidence,"Explain the current evidence")
        app.session_state["payment_assistant_state"]=sandbox
        app.session_state["paypal_order_id"]="PRESERVED-PAYMENT-TARGET"
        app.session_state["main_navigation"]="Review payments"
        app.run()
        app.query_params["create_attempt"]="PRESERVED-CREATION-ATTEMPT"
        app.radio(key="application_mode").set_value("Guided demo").run()
        self.assertIsNone(session["pending"])
        self.assertEqual(session["draft"],"Explain the current evidence")
        self.assertFalse(sandbox.finish(ticket,{"explanation":"Late","general_checks":[],"evidence_refs":[]},evidence))
        self.assertEqual(app.session_state["paypal_order_id"],"PRESERVED-PAYMENT-TARGET")
        self.assertEqual(app.query_params["create_attempt"],["PRESERVED-CREATION-ATTEMPT"])
        app.run()
        self.assertEqual(app.radio(key="application_mode").value,"Guided demo")
        app.radio(key="application_mode").set_value("PayPal Sandbox").run()
        self.assertEqual(app.session_state["paypal_order_id"],"PRESERVED-PAYMENT-TARGET")
        self.assertEqual(session["draft"],"Explain the current evidence")
        self.api.assert_not_called()

    def test_unconfigured_sandbox_has_disabled_external_actions_and_visible_warnings(self):
        app=self.app();app.radio(key="application_mode").set_value("PayPal Sandbox").run()
        app.radio(key="main_navigation").set_value("Sandbox tools").run()
        self.assertFalse(app.exception)
        for button in app.button:
            if button.label in {"Create Sandbox Order","Get Sandbox Access Token"}:self.assertTrue(button.disabled)
        self.assertTrue(any("Webhook ID" in x.value for x in app.warning))
        app.radio(key="application_mode").set_value("Guided demo").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.query_params["mode"],["demo"])

    def test_missing_webhook_id_does_not_block_basic_mocked_api_but_receiver_fails_closed(self):
        # New mocks override the forbidden outer mocks, with no real network.
        settings={"client_id":"synthetic-client","client_secret":"synthetic-secret"}
        payload={"id":"SYNTHETIC-ORDER","status":"COMPLETED","purchase_units":[{"amount":{"value":"10.00","currency_code":"CAD"},"payments":{"captures":[{"id":"SYNTHETIC-CAPTURE","amount":{"value":"10.00","currency_code":"CAD"},"status":"COMPLETED","final_capture":True}]}}]}
        # Use original functions from the source module without calling the outer mock objects.
        import importlib.util
        spec=importlib.util.spec_from_file_location("synthetic_paypal_auth",ROOT/"paypal_auth.py")
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        def response(data):
            result=Mock(ok=True,status_code=200);result.json.return_value=data;return result
        def post(url,**kwargs):
            if url.endswith("/token"):return response({"access_token":"synthetic-token"})
            return response(payload if url.endswith("/capture") else {"id":"SYNTHETIC-ORDER","links":[{"rel":"approve","href":"https://example.invalid/approve"}]})
        with patch.object(api.requests,"post",side_effect=post),patch.object(api.requests,"get",return_value=response(payload)):
            api.get_access_token(**settings)
            oid,_=api.create_order(**settings,amount="10.00",request_id="synthetic-attempt")
            self.assertEqual(api.capture_order(**settings,order_id=oid)[0],"COMPLETED")
            self.assertEqual(api.get_order_status(**settings,order_id=oid)[0],"COMPLETED")
        class Request:
            headers={name:"synthetic" for name in ("paypal-auth-algo","paypal-cert-url","paypal-transmission-id","paypal-transmission-sig","paypal-transmission-time")}
            async def body(self):return b'{"id":"SYNTHETIC-EVENT"}'
        with patch.object(webhook_server,"SECRETS_PATH",Mock(is_file=Mock(return_value=True))),patch.object(webhook_server.toml,"load",return_value={"paypal":settings}),patch.object(webhook_server,"verify_webhook_signature") as verify,patch.object(webhook_server,"record_webhook_event") as write:
            with self.assertRaises(HTTPException) as caught:asyncio.run(webhook_server.receive_paypal_webhook(Request()))
            self.assertEqual(caught.exception.status_code,503)
            verify.assert_not_called();write.assert_not_called()
            self.assertEqual(webhook_server.health_check(),{"status":"ok"})
