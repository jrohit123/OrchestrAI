import re
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# ── TIER 1: EXACT MATCH ──────────────────────────────
EXACT_MAP = {
    "1":      "action:approve",
    "2":      "action:reject",
    "hi":     "action:greet",
    "hello":  "action:greet",
    "help":   "action:menu",
    "menu":   "action:menu",
    "stop":   "action:unsubscribe",
    "retry":  "action:retry_otp",
}


def tier1_exact(text: str):
    return EXACT_MAP.get(text.strip().lower())


# ── TIER 2: KEYWORD CLASSIFIER ───────────────────────
# NOTE: weekly_dues_report MUST come before check_outstanding
# to avoid "dues report" matching the dues\s+(.+) pattern first
KEYWORD_RULES = [
    {
        "intent": "weekly_dues_report",
        "patterns": [
            r"dues\s+report",
            r"outstanding\s+report",
            r"dues\s+summary",
            r"all\s+overdue",
            r"all\s+dues",
            r"60\+\s*(days|overdue)",
            r"overdue\s+report",
            r"overdue\s+summary",
        ],
        "entity": None
    },
    {
        "intent": "check_stock",
        "patterns": [
            r"stock\s+(.+)",
            r"how many\s+(.+)",
            r"kitna\s+(.+)\s+hai",
            r"(.+)\s+available",
            r"(.+)\s+stock",
            r"inventory\s+(.+)",
        ],
        "entity": "product"
    },
    {
        "intent": "check_outstanding",
        "patterns": [
            r"dues?\s+(.+)",
            r"outstanding\s+(.+)",
            r"balance\s+(.+)",
            r"(.+)\s+ka bacha",
            r"(.+)\s+owes",
            r"pending\s+(.+)",
        ],
        "entity": "customer"
    },
    {
        "intent": "create_invoice",
        "patterns": [
            r"invoice\s+(.+)\s+₹?([\d,]+)",
            r"bill\s+(.+)\s+₹?([\d,]+)",
            r"raise\s+invoice\s+(.+)",
        ],
        "entity": "customer+amount"
    },
]


def tier2_keyword(text: str):
    t = text.strip().lower()
    for rule in KEYWORD_RULES:
        for pattern in rule["patterns"]:
            m = re.search(pattern, t)
            if m:
                return {
                    "intent": rule["intent"],
                    "entity_raw": m.group(1).strip() if m.lastindex and rule["entity"] else None,
                    "tier": 2,
                    "confidence": 0.85
                }
    return None


# ── TIER 3: LLM FALLBACK (OpenAI GPT) ────────────────────
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def tier3_llm(text: str, org_name: str) -> dict:
    prompt = f"""You are an intent parser for {org_name}, a jewellery business.
Extract the intent and entities from the user's message.

Allowed intents: check_stock, create_invoice, check_outstanding, weekly_dues_report, unknown

Return ONLY valid JSON with no extra text:
{{"intent": "...", "entity_raw": "...", "confidence": 0.0}}

User message: {text}"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"intent": "unknown", "entity_raw": None, "confidence": 0.0}

    return parsed | {"tier": 3}


# ── MAIN ROUTER ──────────────────────────────────────
async def classify_message(text: str, org_name: str = "your organisation") -> dict:
    # Tier 1 — free, instant
    t1 = tier1_exact(text)
    if t1:
        return {"intent": t1, "tier": 1, "confidence": 1.0, "entity_raw": None}

    # Tier 2 — near-free regex
    t2 = tier2_keyword(text)
    if t2:
        return t2

    # Tier 3 — LLM last resort
    t3 = await tier3_llm(text, org_name)
    return t3
