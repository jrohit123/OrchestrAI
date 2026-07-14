"""
gemini_client.py — Gemini-side price interpretation.

This is the "generator" half of the dual-LLM QA pipeline. It is NEVER
trusted alone — see llm_qa_reviewer.py, which cross-checks this against
an independent OpenAI interpretation before either number is used.
"""
import os
import json
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
_model = genai.GenerativeModel("gemini-2.0-flash")


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

    response = await _model.generate_content_async(prompt)
    text = response.text.strip()
    if "```" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)
