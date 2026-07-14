"""
llm_qa_reviewer.py — Dual-model price interpretation cross-check.

Cerebras interprets the user's raw pricing statement first (cerebras_client.py).
OpenAI independently interprets the SAME raw statement, blind to Cerebras's
answer. If both agree (within tolerance) the price is accepted; if they
disagree, we surface a clarification instead of guessing.

This module is the ONLY place either LLM's numeric output feeds into a
workflow. Everything downstream (GST, making charges, totals) is still
100% calc_engine — no LLM, ever, touches multiplication/addition. This
only decides "what number did the human mean", never "what does the
math work out to".
"""
import os
import json
from openai import AsyncOpenAI

_openai_client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=30.0
)

_TOLERANCE_PCT = 0.5  # 0.5% relative difference counts as "agreement"


async def _openai_interpret_price(rate_text: str, weight: float, qty: int) -> dict:
    prompt = f"""A jeweller said this about pricing an item:
"{rate_text}"
Item weight: {weight} grams. Quantity: {qty}.

Interpret this into a single unit_price in Rupees (ex-GST, ex-making-charges,
price for ONE unit). Return ONLY JSON, no markdown: {{"unit_price": <number>}}"""

    resp = await _openai_client.chat.completions.create(
        model="gpt-4o",
        max_tokens=200,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.choices[0].message.content.strip()
    if "```" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


async def dual_verify_price(rate_text: str, weight: float, qty: int) -> dict:
    """
    Returns either:
      {"agreed": True, "unit_price": <float>}
    or:
      {"agreed": False, "message": "<what to tell the user>"}
    """
    from app.services.gemini_client import interpret_price as _cerebras_interpret

    try:
        cerebras_result = await _cerebras_interpret(rate_text, weight, qty)
        openai_result = await _openai_interpret_price(rate_text, weight, qty)
    except (json.JSONDecodeError, KeyError) as e:
        return {
            "agreed": False,
            "message": (
                "I couldn't confidently interpret that price. Please state it "
                "explicitly, e.g. 'Rs.45,000 per gram' or 'Rs.11,25,000 total'."
            )
        }

    c_price = float(cerebras_result.get("unit_price", 0))
    o_price = float(openai_result.get("unit_price", 0))

    if c_price <= 0 or o_price <= 0:
        return {
            "agreed": False,
            "message": (
                "I couldn't confidently interpret that price. Please state it "
                "explicitly, e.g. 'Rs.45,000 per gram' or 'Rs.11,25,000 total'."
            )
        }

    diff_pct = abs(c_price - o_price) / max(c_price, o_price) * 100
    if diff_pct <= _TOLERANCE_PCT:
        return {"agreed": True, "unit_price": round((c_price + o_price) / 2, 2)}

    return {
        "agreed": False,
        "message": (
            f"I got two different readings of that price — Rs.{c_price:,.0f} vs "
            f"Rs.{o_price:,.0f} per unit. Could you state it more explicitly? "
            f"e.g. 'Rs.45,000 per gram' or 'Rs.11,25,000 total'."
        )
    }
