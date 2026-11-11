"""Local configuration diagnostics. Never expose values or claim online validity."""

FIELDS = {"paypal": ("client_id", "client_secret", "webhook_id"), "openai": ("api_key", "model")}


def field_status(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return "Missing"
    if not isinstance(value, str):
        return "Format problem"
    if value.strip().upper().startswith("YOUR_"):
        return "Placeholder"
    return "Present — not verified online"


def configuration_status(settings):
    result = {}
    for section, fields in FIELDS.items():
        group = settings.get(section, {})
        if not hasattr(group, "get"):
            result.update({section + "." + field: "Format problem" for field in fields})
        else:
            result.update({section + "." + field: field_status(group.get(field)) for field in fields})
    present = lambda key: result[key] == "Present — not verified online"
    payments = present("paypal.client_id") and present("paypal.client_secret")
    return result, {"paypal": payments, "webhook": payments and present("paypal.webhook_id"),
                    "ai": present("openai.api_key") and (present("openai.model") or result["openai.model"] == "Missing")}


def load_configuration_status():
    import streamlit as st
    try:
        return (*configuration_status(st.secrets), None)
    except FileNotFoundError:
        return (*configuration_status({}), "Configuration file missing. Guided demo works without it.")
    except Exception:
        return (*configuration_status({}), "Configuration format problem. Check local TOML; values are never displayed.")
