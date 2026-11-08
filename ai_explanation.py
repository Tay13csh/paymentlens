"""Generate a short explanation of an existing rules-based risk result."""

from openai import APITimeoutError, AuthenticationError, OpenAI, RateLimitError


DEFAULT_MODEL = "gpt-6-luna"
MAX_OUTPUT_TOKENS = 160
REQUEST_TIMEOUT_SECONDS = 20.0


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
    """Explain supplied risk metrics without receiving identifying order data."""
    if not api_key or not model:
        raise AIExplanationError("AI explanation settings are incomplete.")

    instructions = (
        "Explain these rules-based post-payment metrics in 2-3 short sentences in plain English. "
        "Use only the supplied values. The amount ratio is the order amount divided by the user-provided "
        "simulated baseline. The score and risk level were already calculated by the application; do not "
        "change or recalculate them. Do not invent historical behavior or infer intent, fraud, a fraud "
        "probability, or PayPal's risk decision."
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
        explanation = response.output_text.strip()
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

    if not explanation:
        raise AIExplanationError("The AI service returned an empty explanation. Try again.")

    return explanation