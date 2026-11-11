"""Existing payment regressions explicitly select the Sandbox surface."""
from streamlit.testing.v1 import AppTest


def sandbox_test_app(path):
    app = AppTest.from_file(path)
    app.session_state["application_mode"] = "PayPal Sandbox"
    return app
