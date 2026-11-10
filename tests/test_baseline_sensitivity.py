"""Offline tests for baseline-only simulations isolated from the session review."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

import ai_explanation
import order_store
import paypal_auth


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class BaselineSensitivityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.start_patch(patch.object(order_store, "DATABASE_PATH", Path(directory.name) / "orders.db"))
        self.start_patch(patch.object(st, "secrets", {}))
        self.network = self.start_patch(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Network forbidden")))
        self.ai = self.start_patch(patch.object(ai_explanation, "OpenAI", side_effect=AssertionError("AI forbidden")))
        self.payments = [self.start_patch(patch.object(paypal_auth, name, side_effect=AssertionError("Payment forbidden")))
                         for name in ("get_access_token", "create_order", "capture_order", "get_order_status")]
        self.save("A", "10.00", "CAD")

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def save(self, order_id, amount, currency, status="COMPLETED"):
        order_store.save_order(order_id, amount, currency)
        order_store.update_order_status(order_id, status)

    def app(self):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.selectbox(key="review_order_id").select("A").run()
        app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        return app

    def custom(self, app):
        return next(field for field in app.text_input if field.label.startswith("Custom simulated comparison baseline"))

    def section(self, app, title):
        return next(
            node for node in app.main
            if hasattr(node, "children") and any(
                getattr(child, "value", None) == f"**{title}**" for child in node.children.values()
            )
        )

    def scores(self, app):
        if not any(item.value == "**Your comparison result**" for item in app.markdown):
            return []
        # Logical scenario assertions should not depend on the visual section order.
        examples = self.section(app, "Compare example assumptions")
        selected = self.section(app, "Your comparison result")
        return [metric.value for section in (examples, selected) for metric in section.metric if metric.label == "Rule score"]

    def assert_no_requests(self):
        self.network.assert_not_called()
        self.ai.assert_not_called()
        for request in self.payments:
            request.assert_not_called()

    def test_ten_cad_demo_has_expected_ratios_scores_and_explicit_assumption_labels(self):
        app = self.app()
        self.assertEqual(self.scores(app), ["10/100", "50/100", "80/100", "10/100"])
        self.assertEqual([metric.value for metric in self.section(app, "Compare example assumptions").metric if metric.label == "Amount ratio"], ["1×", "2×", "5×"])
        text = "\n".join(item.value for item in app.markdown)
        for heading in ("Payment facts", "Simulated assumptions", "Rule results"):
            self.assertIn(f"**{heading}**", text)
        self.assertIn("Payment evidence is unchanged. Only the simulated baseline changes.", text)
        for level in ("Low Risk", "Medium Risk", "High Risk"):
            self.assertIn(f"Rule-based level: **{level}**", text)
        self.assertTrue(any("demonstration assumptions" in item.value and "not historical" in item.value for item in app.caption))
        self.assertNotIn("risk_analysis", app.session_state)
        self.assert_no_requests()

    def test_custom_baseline_changes_only_its_local_result(self):
        app = self.app()
        self.custom(app).set_value("4").run()
        self.assertFalse(app.exception)
        self.assertEqual(self.scores(app), ["10/100", "50/100", "80/100", "50/100"])
        ratios = [metric.value for metric in self.section(app, "Your comparison result").metric if metric.label == "Amount ratio"]
        self.assertEqual(ratios[-1], "2.5×")
        self.assertEqual(order_store.get_order("A")["amount"], "10.00")
        self.assert_no_requests()

    def test_formal_review_ai_payment_target_and_database_are_unchanged(self):
        app = self.app()
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Existing observation for the formal review."
        app.session_state["paypal_order_id"] = "A"
        app.run()
        analysis = dict(app.session_state["risk_analysis"])
        signature = app.session_state["risk_analysis_signature"]
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            original = "\n".join(connection.iterdump())
        self.custom(app).set_value("2").run()
        self.custom(app).set_value("5").run()
        self.assertFalse(app.exception)
        self.assertEqual(dict(app.session_state["risk_analysis"]), analysis)
        self.assertEqual(app.session_state["risk_analysis_signature"], signature)
        self.assertEqual(app.session_state["simulated_average_CAD"], 100.0)
        self.assertEqual(app.session_state["ai_explanation"], "Existing observation for the formal review.")
        self.assertEqual(app.session_state["paypal_order_id"], "A")
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            self.assertEqual("\n".join(connection.iterdump()), original)
        summary = next(item.value for item in app.markdown if item.value.startswith('<section class="pg-summary"'))
        self.assertIn("10/100", summary)
        self.assert_no_requests()

    def test_invalid_baselines_keep_presets_and_formal_review_intact(self):
        app = self.app()
        app.button(key="analyze_saved_order").click().run()
        original = dict(app.session_state["risk_analysis"])
        app.session_state["ai_explanation"] = "Existing observation."
        invalid = ("", "not-a-number", "0", "-2", "NaN", "Infinity", "1e309", "1e-9999", "1e-309", "1.000000000000000000000000001")
        for value in invalid:
            with self.subTest(value=value):
                self.custom(app).set_value(value).run()
                self.assertFalse(app.exception)
                self.assertTrue(app.warning)
                self.assertEqual(self.scores(app), ["10/100", "50/100", "80/100"])
                self.assertEqual(dict(app.session_state["risk_analysis"]), original)
                self.assertEqual(app.session_state["ai_explanation"], "Existing observation.")
        self.assert_no_requests()

    def test_threshold_precision_and_tiny_positive_baselines_are_not_hidden_by_rounding(self):
        app = self.app()
        cases = (
            ("5.000000000000001", "10/100", "1.999"),
            ("5", "50/100", "2×"),
            ("4.999999999999999", "50/100", "2.000"),
            ("2.0000000000000004", "50/100", "4.999"),
            ("2", "80/100", "5×"),
            ("1.9999999999999998", "80/100", "5.000"),
        )
        for baseline, score, ratio_prefix in cases:
            with self.subTest(baseline=baseline):
                self.custom(app).set_value(baseline).run()
                self.assertFalse(app.exception)
                self.assertEqual(self.scores(app)[-1], score)
                ratios = [metric.value for metric in self.section(app, "Your comparison result").metric if metric.label == "Amount ratio"]
                self.assertTrue(ratios[-1].startswith(ratio_prefix), ratios[-1])
        self.custom(app).set_value("0.00000001").run()
        self.assertFalse(app.exception)
        self.assertEqual(self.scores(app)[-1], "80/100")
        self.assertTrue(any("Selected baseline: 1e-08 CAD" in item.value for item in app.markdown))
        self.assert_no_requests()

    def test_sensitivity_input_is_scoped_to_order_amount_and_currency(self):
        self.save("B", "20.00", "USD")
        app = self.app()
        key_a = self.custom(app).key
        self.custom(app).set_value("4").run()
        app.selectbox(key="review_order_id").select("B").run()
        app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        key_b = self.custom(app).key
        self.assertNotEqual(key_a, key_b)
        self.assertEqual(self.custom(app).value, "10")
        self.assertIn("USD", self.custom(app).label)
        self.assertEqual(self.scores(app)[-1], "50/100")
        self.save("B", "40.00", "USD")
        app.run()
        self.assertNotEqual(self.custom(app).key, key_b)
        self.assertEqual(self.custom(app).value, "10")
        self.assert_no_requests()

    def test_original_amount_simulation_is_collapsed_and_keeps_original_review_baseline(self):
        app = self.app()
        self.assertFalse(any(item.label == "Advanced: hypothetical order amount" for item in app.expander))
        app.button(key="analyze_saved_order").click().run()
        self.assertTrue(any(item.label == "Hypothetical amount" for item in app.tabs))
        advanced = next(item for item in app.expander if item.label == "Explore assumptions")
        self.assertFalse(advanced.proto.expanded)
        original = dict(app.session_state["risk_analysis"])
        next(field for field in app.number_input if field.label.startswith("Hypothetical Order Amount")).set_value(1000.0).run()
        self.assertFalse(app.exception)
        self.assertEqual(dict(app.session_state["risk_analysis"]), original)
        self.assertEqual(self.scores(app), ["10/100", "50/100", "80/100", "10/100"])
        self.assert_no_requests()

    def test_noncompleted_order_does_not_gain_a_review_or_sensitivity_result(self):
        self.save("PENDING", "10.00", "CAD", "APPROVED")
        app = self.app()
        app.selectbox(key="review_order_id").select("PENDING").run()
        app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(any(field.label.startswith("Custom simulated comparison") for field in app.text_input))
        self.assertFalse(self.scores(app))
        self.assertNotIn("risk_analysis", app.session_state)
        self.assert_no_requests()

    def test_collapsed_panel_keeps_hint_and_open_closed_rendering_preserves_state(self):
        title = "Explore assumptions"
        app = self.app()
        panel = next(item for item in app.expander if item.label == title)
        self.assertFalse(panel.proto.expanded)
        self.assertTrue(any(item.value == "Same payment, different simulated baselines." for item in app.caption))
        self.assertTrue(any(field.label.startswith("Custom simulated comparison baseline") for field in panel.text_input))
        self.custom(app).set_value("4").run()
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Existing observation."
        app.run()
        analysis = dict(app.session_state["risk_analysis"])
        signature = app.session_state["risk_analysis_signature"]
        input_key = self.custom(app).key
        original_expander = st.expander

        def expanded_view(label, *args, **kwargs):
            if label == title:
                kwargs["expanded"] = True
            return original_expander(label, *args, **kwargs)

        # AppTest does not simulate the browser's disclosure click. Verify both
        # rendered states using the native expander while keeping its contents.
        with patch.object(st, "expander", side_effect=expanded_view):
            app.run()
            self.assertTrue(next(item for item in app.expander if item.label == title).proto.expanded)
        app.run()
        self.assertFalse(next(item for item in app.expander if item.label == title).proto.expanded)
        self.assertFalse(app.exception)
        self.assertEqual((self.custom(app).key, self.custom(app).value), (input_key, "4"))
        self.assertEqual(dict(app.session_state["risk_analysis"]), analysis)
        self.assertEqual(app.session_state["risk_analysis_signature"], signature)
        self.assertEqual(app.session_state["ai_explanation"], "Existing observation.")
        self.assertEqual(self.scores(app)[-1], "50/100")
        self.assert_no_requests()

    def test_preset_buttons_update_custom_scenario_and_manual_values_show_custom(self):
        app = self.app()
        for value, score in ((5, "50/100"), (2, "80/100"), (10, "10/100")):
            next(button for button in app.button if button.label == f"Use baseline {value} CAD").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(self.custom(app).value, str(value))
            self.assertEqual(self.scores(app)[-1], score)
            self.assertIn(f"**Selected preset: {value} CAD**", [item.value for item in app.markdown])
            self.assertEqual(self.scores(app)[:3], ["10/100", "50/100", "80/100"])
        self.custom(app).set_value("4").run()
        self.assertIn("**Custom**", [item.value for item in app.markdown])
        self.assertEqual(self.scores(app)[-1], "50/100")
        self.custom(app).set_value("5.00").run()
        self.assertIn("**Selected preset: 5 CAD**", [item.value for item in app.markdown])
        self.assertTrue(any(item.value == "Simulation only — does not change or charge the payment." for item in app.caption))
        self.assert_no_requests()

    def test_preset_clicks_preserve_review_ai_payment_database_and_folded_content(self):
        title = "Explore assumptions"
        app = self.app()
        app.button(key="analyze_saved_order").click().run()
        app.session_state["ai_explanation"] = "Existing observation."
        app.session_state["paypal_order_id"] = "A"
        app.run()
        analysis = dict(app.session_state["risk_analysis"])
        signature = app.session_state["risk_analysis_signature"]
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            original = "\n".join(connection.iterdump())
        real_expander = st.expander

        def open_panel(label, *args, **kwargs):
            if label == title:
                kwargs["expanded"] = True
            return real_expander(label, *args, **kwargs)

        with patch.object(st, "expander", side_effect=open_panel):
            app.run()
            panel = next(item for item in app.expander if item.label == title)
            self.assertTrue(panel.proto.expanded)
            next(button for button in panel.button if button.label == "Use baseline 2 CAD").click().run()
            self.assertEqual(self.custom(app).value, "2")
        app.run()
        self.assertFalse(next(item for item in app.expander if item.label == title).proto.expanded)
        self.assertEqual(self.custom(app).value, "2")
        self.assertEqual(dict(app.session_state["risk_analysis"]), analysis)
        self.assertEqual(app.session_state["risk_analysis_signature"], signature)
        self.assertEqual(app.session_state["simulated_average_CAD"], 100.0)
        self.assertEqual(app.session_state["ai_explanation"], "Existing observation.")
        self.assertEqual(app.session_state["paypal_order_id"], "A")
        with sqlite3.connect(order_store.DATABASE_PATH) as connection:
            self.assertEqual("\n".join(connection.iterdump()), original)
        self.assert_no_requests()

    def test_preset_buttons_follow_currency_and_do_not_mix_order_inputs(self):
        self.save("B", "20.00", "USD")
        app = self.app()
        next(button for button in app.button if button.label == "Use baseline 2 CAD").click().run()
        key_a = self.custom(app).key
        app.selectbox(key="review_order_id").select("B").run()
        app.button(key="open_payment_review").click().run()
        self.assertFalse(app.exception)
        self.assertNotEqual(self.custom(app).key, key_a)
        self.assertEqual(self.custom(app).value, "10")
        for value in (10, 5, 2):
            self.assertTrue(any(button.label == f"Use baseline {value} USD" for button in app.button))
        next(button for button in app.button if button.label == "Use baseline 5 USD").click().run()
        self.assertEqual(self.custom(app).value, "5")
        self.assertEqual(self.scores(app)[-1], "50/100")
        app.selectbox(key="review_order_id").select("A").run()
        app.button(key="open_payment_review").click().run()
        self.assertNotEqual(self.custom(app).value, "5")
        self.assertIn("CAD", self.custom(app).label)
        self.assert_no_requests()

    def test_selected_scenario_is_first_and_invalid_input_clears_only_its_result(self):
        app = self.app()
        headings = [item.value for item in app.markdown]
        self.assertLess(headings.index("**Your comparison result**"), headings.index("**Compare example assumptions**"))
        next(button for button in app.button if button.label == "Use baseline 5 CAD").click().run()
        selected = self.section(app, "Your comparison result")
        self.assertEqual([item.value for item in selected.metric if item.label == "Rule score"], ["50/100"])
        self.custom(app).set_value("invalid").run()
        self.assertFalse(app.exception)
        selected = self.section(app, "Your comparison result")
        self.assertFalse(selected.metric)
        self.assertTrue(selected.warning)
        self.assertFalse(any("Selected baseline:" in item.value for item in selected.markdown))
        self.assertEqual(self.scores(app), ["10/100", "50/100", "80/100"])
        self.assertTrue(any("Fixed demonstration examples" in item.value for item in self.section(app, "Compare example assumptions").caption))
        next(button for button in app.button if button.label == "Use baseline 2 CAD").click().run()
        self.assertEqual(self.scores(app)[-1], "80/100")
        self.assert_no_requests()


if __name__ == "__main__":
    unittest.main()
