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
        "intent": "clear_sessions",
        "patterns": [
            r"clear\s+all\s+sessions",
            r"lock\s+all\s+accounts",
            r"emergency\s+lock",
            r"lockdown",
            r"clear\s+sessions",
            r"logout\s+everyone",
            r"revoke\s+all\s+access",
            r"kick\s+everyone",
        ],
        "entity": None
    },
    {
        "intent": "manage_schedule",
        "patterns": [
            r"schedule\s+dues",
            r"schedule\s+report",
            r"send\s+dues\s+report\s+every",
            r"send\s+report\s+every",
            r"change\s+.*report.*to",
            r"reschedule",
            r"stop\s+dues\s+report",
            r"stop\s+schedule",
            r"cancel\s+schedule",
            r"when\s+is\s+due",
            r"when\s+is\s+report",
            r"dues\s+report\s+schedule",
            r"dues\s+report\s+every",
            r"report\s+scheduled",
            r"due\s+report\s +schedul",
        ],
        "entity": None
    },
    {
        "intent": "weekly_dues_report",
        "patterns": [
            r"^dues\s+report$",
            r"outstanding\s+report",
            r"dues\s+summary",
            r"all\s+overdue",
            r"all\s+dues",
            r"60\+\s*(days|overdue)",
            r"overdue\s+report",
            r"overdue\s+summary",
            r"top\s+\d+\s+dues",
            r"top\s+\d+\s+outstanding",
            r"give\s+me\s+top",
        ],
        "entity": None
    },
    {
        "intent": "check_outstanding",
        "patterns": [
            r"(.+)\s+ka\s+kitna",
            r"(.+)\s+ka\s+bacha",
            r"kitna\s+bacha\s+(.+)",
            r"^dues?\s+([a-zA-Z][\w\s]{2,20})$",
            r"outstanding\s+([a-zA-Z][\w\s]{2,20})",
            r"balance\s+([a-zA-Z][\w\s]{2,20})",
            r"(.+)\s+owes",
            r"pending\s+(?:of\s+)?([a-zA-Z][\w\s]{2,20})$",
            r"how\s+much\s+(?:is\s+)?(?:pending|due|owed)\s+(?:of\s+|for\s+)?(.+)",
        ],
        "entity": "customer"
    },
    {
        "intent": "check_stock",
        "patterns": [
            r"stock\s+(.+)",
            r"how many\s+(.+)",
            r"(.+)\s+available",
            r"(.+)\s+stock",
            r"inventory\s+(.+)",
            r"kitna\s+(.+)\s+hai",
        ],
        "entity": "product"
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
                entity = m.group(1).strip() if m.lastindex and rule["entity"] else None
                # Strip leading prepositions
                if entity:
                    for prep in ["of ", "for ", "ka ", "ki ", "ke "]:
                        if entity.startswith(prep):
                            entity = entity[len(prep):]
                    entity = entity.strip().title()

                # Extract limit for "top N" queries
                limit = None
                if rule["intent"] == "weekly_dues_report":
                    lm = re.search(r"top\s+(\d+)", t)
                    if lm:
                        limit = int(lm.group(1))

                return {
                    "intent": rule["intent"],
                    "entity_raw": entity,
                    "limit": limit,
                    "tier": 2,
                    "confidence": 0.85
                }
    return None


# ── TIER 3: LLM FALLBACK (OpenAI GPT) ────────────────────
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def tier3_llm(text: str, org_name: str) -> dict:
    prompt = f"""You are an intent parser for {org_name}, a jewellery business in India.
Extract the intent and entity from the user's message.

Allowed intents:
- check_stock: user wants to know stock/inventory of a product
- check_outstanding: user wants to know pending dues/payments of a customer
- create_invoice: user wants to create a bill or invoice
- weekly_dues_report: user wants summary of all overdue customers
- unknown: cannot determine intent

Rules for entity extraction:
- Remove prepositions from entity: strip "of", "for", "ka", "ki", "ke", "kا" from the START of entity
- Entity should be just the name — no extra words
- For Hindi queries: "ka kitna bacha hai" = check_outstanding, "ka stock" = check_stock
- "pending of Sharma" → entity = "Sharma" (strip "of")
- "Mehta ka kitna bacha hai" → intent = check_outstanding, entity = "Mehta"
- "Sharma Gold House ka dues" → intent = check_outstanding, entity = "Sharma Gold House"
- "kitna gold ring hai" → intent = check_stock, entity = "gold ring"

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
        # Clean entity — strip leading prepositions
        if parsed.get("entity_raw"):
            entity = parsed["entity_raw"].strip()
            for prep in ["of ", "for ", "ka ", "ki ", "ke "]:
                if entity.lower().startswith(prep):
                    entity = entity[len(prep):]
            parsed["entity_raw"] = entity.strip().title()
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
