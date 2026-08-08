"""
cerebras_client.py — Cerebras-side price interpretation.

This is the "generator" half of the dual-LLM QA pipeline. It is NEVER
trusted alone — see llm_qa_reviewer.py, which cross-checks this against
an independent OpenAI interpretation before either number is used.
"""
import os
import json
import asyncio
from openai import AsyncOpenAI

from app.config import required

_api_key = required("CEREBRAS_API_KEY")

_client = AsyncOpenAI(
    api_key=_api_key,
    base_url="https://api.cerebras.ai/v1",
    timeout=30.0
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

    max_retries = 3
    base_delay = 2.0  # seconds
    
    for attempt in range(max_retries):
        try:
            response = await _client.chat.completions.create(
                model="gpt-oss-120b",
                max_tokens=200,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.choices[0].message.content.strip()
            if "```" in text:
                text = text[text.find("{"):text.rfind("}") + 1]
            return json.loads(text)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "too_many_requests" in error_str or "queue_exceeded" in error_str:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    print(f"[CEREBRAS] Rate limited (429), retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise Exception(f"Cerebras API rate limited after {max_retries} retries: {e}")
            else:
                raise
    
    raise Exception("Cerebras API failed after retries")
