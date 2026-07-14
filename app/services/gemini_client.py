"""
cerebras_client.py — Cerebras-side price interpretation.

This is the "generator" half of the dual-LLM QA pipeline. It is NEVER
trusted alone — see llm_qa_reviewer.py, which cross-checks this against
an independent OpenAI interpretation before either number is used.
"""
import os
import json
from openai import AsyncOpenAI

_api_key = os.getenv("CEREBRAS_API_KEY")
if not _api_key:
    raise ValueError("CEREBRAS_API_KEY environment variable not set")

_client = AsyncOpenAI(
    api_key=_api_key,
    base_url="https://api.cerebras.ai/v1"
)


async def interpret_price(rate_text: str, weight: float, qty: int) -> dict:
    """
    Interpret a plain-English price statement into a single unit_price
    (ex-GST, ex-making-charges, price for ONE unit of this item).
    Returns {"unit_price": float, "reasoning": str}.
    """
    prompt = f"""A jeweller said this about pricing an item:
"{rate_text}"
Item weight: {weight} grams. Quantity: {qty}.

Interpret this into a single unit_price in Rupees (the ex-GST, ex-making-charges
price for ONE unit of this item). Common patterns:
  "45000 per gram" / "45000/g" / "6200 a gram" -> unit_price = rate * weight
  "Rs.55000 total" / "55000 flat" -> unit_price = 55000 (already the total for 1 unit)

Return ONLY this JSON, no markdown, no explanation:
{{"unit_price": <number>, "reasoning": "<one sentence>"}}"""

    response = await _client.chat.completions.create(
        model="llama3.1-70b",
        max_tokens=200,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.choices[0].message.content.strip()
    if "```" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)
