"""
price_interpreter.py — LLM price interpretation for raw pricing text.

Turns a business owner's free-text price statement (e.g. "45000 per gram",
"Rs.55000 total") into a single unit_price. Routed through llm_router's
standard provider fallback ladder (OpenAI -> Gemini -> Groq) — if one
provider fails, the next takes over — same as every other LLM call in this
codebase, rather than maintaining a second hand-rolled provider path.
"""
import json
from app.logging_config import get_context_logger
from app.services.llm_router import chat_completion as _llm_chat
from app.services.prompt_loader import PROMPTS_DIR, _read

logger = get_context_logger(__name__)

_PRICE_PROMPT = _read(PROMPTS_DIR / "price_interpret.txt")

_AMBIGUOUS = {
    "agreed": False,
    "message": (
        "I couldn't confidently interpret that price. Please state it "
        "explicitly, e.g. 'Rs.45,000 per gram' or 'Rs.11,25,000 total'."
    ),
}


async def interpret_price(rate_text: str, weight: float, qty: int) -> dict:
    """
    Interpret a plain-English price statement into a single unit_price
    (ex-GST, ex-making-charges, price for ONE unit of this item).

    Returns {"agreed": True, "unit_price": <float>} on success, or
    {"agreed": False, "message": "<what to tell the user>"} if the answer
    can't be parsed or isn't a usable positive number.
    """
    prompt = _PRICE_PROMPT.format(rate_text=rate_text, weight=weight, qty=qty)
    try:
        response = await _llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
        )
        text = response.choices[0].message.content.strip()
        if "```" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        result = json.loads(text)
        unit_price = float(result.get("unit_price", 0))
    except Exception as e:
        logger.warning(f"Price interpretation failed: {e}")
        return dict(_AMBIGUOUS)

    if unit_price <= 0:
        return dict(_AMBIGUOUS)
    return {"agreed": True, "unit_price": round(unit_price, 2)}
