"""Repository-only startup: no real secrets, databases, global HOME or services."""

import os
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ("docs/SETUP.md", "docs/USER_GUIDE.md", "docs/ARCHITECTURE.md", "docs/VALIDATION.md", "docs/LIMITATIONS.md", "docs/VIDEO_SCRIPT.md",
                "reconciliation_report.py", "reconciliation_facts.py", "analysis_view.py", "SUBMISSION.md", "app.py", "paypal_auth.py", "order_store.py", "payment_evidence.py", "ai_explanation.py", "risk.py", "webhook_server.py",
                "payment_assistant.py", "payment_assistant_ui.py", "runtime_config.py", "guided_demo.py", "README.md", "LICENSE", "requirements.txt", ".gitignore", ".streamlit/secrets.toml.example")


def export_repository(target):
    for name in DELIVERABLES:
        source, destination = ROOT / name, target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


class IsolatedStartupTests(unittest.TestCase):
    def test_unconfigured_repository_and_malformed_placeholder_configuration(self):
        with tempfile.TemporaryDirectory(prefix="payguard-repository-only-") as temporary:
            root=Path(temporary);checkout=root/"checkout";checkout.mkdir();home=root/"home";home.mkdir()
            export_repository(checkout)
            self.assertFalse((checkout/".streamlit/secrets.toml").exists())
            self.assertFalse((checkout/"payguard.db").exists())
            env={key:value for key,value in os.environ.items() if not key.startswith(("OPENAI_","PAYPAL_","STREAMLIT_","GH_","GITHUB_"))}
            env.update(HOME=str(home),PYTHONPATH=site.getusersitepackages(),PYTHONDONTWRITEBYTECODE="1")
            script=r'''
import os,sys,logging,asyncio
from pathlib import Path
from unittest.mock import patch
logging.disable(logging.CRITICAL)
root=Path.cwd();home=Path.home()
assert not (root/".streamlit/secrets.toml").exists()
assert not (home/".streamlit/secrets.toml").exists()
assert not (root/"payguard.db").exists()
demo_db_attempts=[]
allow_local_database=False
def guard(event,args):
    if event in ("socket.connect","socket.getaddrinfo"):
        raise AssertionError("External networking forbidden during isolated startup")
    if event=="sqlite3.connect" and not allow_local_database:
        demo_db_attempts.append(True)
        raise AssertionError("Demo database access forbidden")
    if event=="open" and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0]))
        if path.name=="secrets.toml" and path.exists():
            assert path.resolve()==(root/".streamlit/secrets.toml").resolve(), "Non-test secret path forbidden"
sys.addaudithook(guard)
import streamlit as st
from streamlit.testing.v1 import AppTest
import guided_demo,payment_assistant,paypal_auth,webhook_server
from fastapi import HTTPException
with patch.object(payment_assistant,"OpenAI",side_effect=AssertionError("No live AI")),patch.object(paypal_auth.requests.sessions.Session,"request",side_effect=AssertionError("No PayPal")):
    app=AppTest.from_file("app.py").run()
    assert not app.exception
    assert app.radio(key="application_mode").value=="Guided demo"
    assert app.query_params["mode"]==["demo"]
    for case in guided_demo.CASES:
        app.selectbox(key="guided_demo_case").select(case).run()
        assert not app.exception
        assert any(x.value=="Sample explanation — not generated live" for x in app.subheader)
    demo_id=guided_demo.demo_snapshot(app.selectbox(key="guided_demo_case").value)["order"]["order_id"]
    assert not app.exception and app.button(key="demo_"+demo_id+"_assistant_send").disabled
    assert len(app.text_area)==1
    assert any(x.label=="View sample walkthrough" for x in app.expander)
    assert not (root/"payguard.db").exists()
    assert not demo_db_attempts
    allow_local_database=True
    app.radio(key="application_mode").set_value("PayPal Sandbox").run()
    for section in ("Review payments","Sandbox tools","Test sales orders"):
        app.radio(key="main_navigation").set_value(section).run()
        assert not app.exception
        for button in app.button:
            if button.label in ("Create Sandbox Order","Get Sandbox Access Token","Create or resume linked PayPal order"):
                assert button.disabled
    assert webhook_server.health_check()=={"status":"ok"}
    # Only synthetic test configs are created, after the initial repository-only proof.
    for content in ("[broken", '[paypal]\nclient_id="YOUR_SANDBOX_CLIENT_ID"\nclient_secret="YOUR_SANDBOX_SECRET"\nwebhook_id="YOUR_SANDBOX_WEBHOOK_ID"\n[openai]\napi_key="YOUR_OPENAI_API_KEY"\nmodel="YOUR_OPENAI_MODEL"\n'):
        Path(".streamlit/secrets.toml").write_text(content)
        st.secrets._reset()
        fresh=AppTest.from_file("app.py").run()
        assert not fresh.exception
        assert fresh.radio(key="application_mode").value=="Guided demo"
        fresh.radio(key="application_mode").set_value("PayPal Sandbox").run()
        assert not fresh.exception
        fresh.radio(key="main_navigation").set_value("Sandbox tools").run()
        assert not fresh.exception
        assert next(b for b in fresh.button if b.label=="Create Sandbox Order").disabled
print("ISOLATED_STARTUP_OK: no credentials; five cases; no Demo SQLite; all Sandbox pages; malformed/placeholders handled")
'''
            result=subprocess.run([sys.executable,"-B","-c",script],cwd=checkout,env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn("ISOLATED_STARTUP_OK",result.stdout)
