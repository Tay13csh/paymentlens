"""Generate a short explanation of an existing rules-based risk result."""

import math
import re

from openai import APITimeoutError, AuthenticationError, OpenAI, RateLimitError


DEFAULT_MODEL = "gpt-6-luna"
MAX_OUTPUT_TOKENS = 160
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_OBSERVATION_CHARACTERS = 800
REVIEW_LIMITATIONS = (
    "The spending baseline is user-provided and simulated, not verified spending history. "
    "The rule score is not a fraud probability or PayPal's risk assessment. "
    "An AI observation may be inaccurate and does not establish whether fraud occurred."
)
GENERAL_SUGGESTED_CHECKS = (
    "If available, compare the amount and currency with your own order records.",
    "Check whether the simulated baseline is appropriate for this review.",
)


class AIExplanationError(Exception):
    """Raised when an AI explanation cannot be generated safely."""


def explain_order_risk(
    api_key: str,
    model: str,
    order_amount: float,
    currency: str,
    simulated_baseline: float,
    amount_ratio: float,
    risk_score: int,
    risk_level: str,
) -> str:
    """Generate only an observation from six supplied metrics, without recalculation."""
    if not all(isinstance(value, str) and value.strip() for value in (api_key, model)):
        raise AIExplanationError("AI explanation settings are incomplete.")
    numeric_inputs = (order_amount, simulated_baseline, amount_ratio)
    if (
        any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in numeric_inputs)
        or order_amount < 0 or simulated_baseline <= 0 or amount_ratio < 0
        or isinstance(risk_score, bool) or not isinstance(risk_score, int) or not 0 <= risk_score <= 100
        or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)
        or risk_level not in ("Low Risk", "Medium Risk", "High Risk")
    ):
        raise AIExplanationError("The six review inputs are invalid. Run the rules-based analysis again.")

    instructions = (
        "Write only the Observations content: one short plain-English paragraph of 1-2 sentences. "
        "Explain the supplied comparison qualitatively; authoritative metrics are already displayed by the app. "
        "Use only the supplied values. The amount ratio is the order amount divided by the user-provided "
        "simulated baseline. The score and risk level were already calculated by the application; do not "
        "change or recalculate any value, repeat numerical metrics, or assign a different score or level. "
        "Do not invent historical behavior, payer details, payment status, timestamps, or evidence. "
        "Do not infer intent, fraud, a fraud probability, or PayPal's risk decision. "
        "Do not provide recommendations, payment instructions, headings, or other sections. "
        "Limitations and general manual-check suggestions are supplied separately by the application."
    )
    input_text = (
        f"Order amount: {order_amount:.2f} {currency}\n"
        f"User-provided simulated baseline: {simulated_baseline:.2f} {currency}\n"
        f"Amount ratio: {amount_ratio:.2f}x\n"
        f"Rules-based score: {risk_score}/100\n"
        f"Rules-based level: {risk_level}"
    )

    try:
        client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            reasoning={"effort": "none"},
            store=False,
        )
    except AuthenticationError:
        raise AIExplanationError("OpenAI authentication failed. Check your API Key.") from None
    except RateLimitError as error:
        if error.code == "insufficient_quota":
            raise AIExplanationError(
                "OpenAI API quota is insufficient. Check your API quota or billing."
            ) from None
        raise AIExplanationError("OpenAI is rate-limiting requests. Please try again later.") from None
    except APITimeoutError:
        raise AIExplanationError("The OpenAI service response timed out. Please try again later.") from None
    except Exception:
        raise AIExplanationError(
            "Could not generate an AI explanation. Check the local OpenAI settings and try again."
        ) from None

    if getattr(response, "status", None) != "completed":
        raise AIExplanationError("The AI observation was incomplete. Click Generate AI Explanation to retry.")
    text = getattr(response, "output_text", None)
    if not isinstance(text, str) or not text.strip():
        raise AIExplanationError("The AI service returned an empty explanation. Try again.")
    explanation = text.strip()
    if len(explanation) > MAX_OBSERVATION_CHARACTERS:
        raise AIExplanationError("The AI observation was too long. Click Generate AI Explanation to retry.")

    return explanation
