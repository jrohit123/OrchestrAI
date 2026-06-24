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


# Cache for DB-loaded patterns
_db_patterns_cache = {}


def invalidate_patterns_cache(org_id: str = None):
    """Call after adding/updating workflows so new patterns are loaded immediately."""
    global _db_patterns_cache
    if org_id:
        _db_patterns_cache.pop(org_id, None)
        print(f"[CLASSIFIER] Cache invalidated for org {org_id}")
    else:
        _db_patterns_cache.clear()
        print("[CLASSIFIER] Full pattern cache cleared")


async def load_patterns_from_db(org_id: str) -> list:
    """Load trigger patterns from database for dynamic workflows."""
    global _db_patterns_cache
    
    # Return cached if available
    if org_id in _db_patterns_cache:
        print(f"[CLASSIFIER] Using cached patterns for org {org_id}")
        return _db_patterns_cache[org_id]
    
    print(f"[CLASSIFIER] Loading patterns from DB for org {org_id}")
    
    try:
        from app.db import fetch_all
        rows = await fetch_all("""
            SELECT intent_key, trigger_patterns, description
            FROM workflows
            WHERE org_id = $1 AND is_active = true AND trigger_patterns IS NOT NULL
        """, org_id)
        
        print(f"[CLASSIFIER] Found {len(rows)} workflows with patterns")
        
        db_rules = []
        for row in rows:
            patterns = row.get("trigger_patterns", [])
            if isinstance(patterns, str):
                patterns = json.loads(patterns)
            
            # Only add if patterns exist (skip empty arrays for LLM-based workflows)
            if patterns:  
                db_rules.append({
                    "intent": row["intent_key"],
                    "patterns": patterns,
                    "entity": None,
                    "description": (row.get("description") or "").strip() or f"Custom workflow: {row['intent_key'].replace('_', ' ')}"
                })
                print(f"[CLASSIFIER] Loaded {len(patterns)} patterns for intent: {row['intent_key']}")
            else:
                # Skip patterns but still add for LLM tier3 (description-based matching)
                db_rules.append({
                    "intent": row["intent_key"],
                    "patterns": [],  # Empty - will skip tier2
                    "entity": None,
                    "description": (row.get("description") or "").strip() or f"Custom workflow: {row['intent_key'].replace('_', ' ')}"
                })
                print(f"[CLASSIFIER] Loaded LLM-only workflow: {row['intent_key']}")
        
        _db_patterns_cache[org_id] = db_rules
        print(f"[CLASSIFIER] Total DB rules loaded: {len(db_rules)}")
        return db_rules
    except Exception as e:
        print(f"[CLASSIFIER] Error loading patterns from DB: {e}")
        # Return empty list on error (fallback to hardcoded patterns)
        return []


def tier2_keyword(text: str, db_rules: list = None):
    t = text.strip().lower()
    
    # Combine hardcoded rules with DB-loaded rules
    all_rules = KEYWORD_RULES.copy()
    if db_rules:
        all_rules.extend(db_rules)
    
    for rule in all_rules:
        # Skip rules with empty patterns (LLM-based workflows)
        if not rule.get("patterns"):
            continue
            
        for pattern in rule["patterns"]:
            m = re.search(pattern, t)
            if m:
                # Extract entity from capture group if available
                entity = None
                if m.lastindex:
                    entity = m.group(1).strip() if m.group(1) else None
                
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

                print(f"[CLASSIFIER] Matched pattern: {pattern} -> intent: {rule['intent']}, entity: {entity}")
                return {
                    "intent": rule["intent"],
                    "entity_raw": entity,
                    "limit": limit,
                    "tier": 2,
                    "confidence": 0.85
                }
    print(f"[CLASSIFIER] No pattern matched for: {t}")
    return None


# ── TIER 3: LLM FALLBACK (OpenAI GPT) ────────────────────
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def tier3_llm(text: str, org_name: str, db_rules: list = None) -> dict:
    base_intents = [
        ("check_stock",        "user wants to know stock/inventory/quantity of a product"),
        ("check_outstanding",  "user wants to know pending dues/payments/balance owed by a customer"),
        ("create_invoice",     "user wants to create a bill, invoice, or receipt"),
        ("weekly_dues_report", "user wants a summary of all overdue/outstanding customers"),
        ("manage_schedule",    "user wants to schedule, reschedule, pause, or check a report schedule"),
        ("clear_sessions",     "user wants to clear all sessions, emergency lockout, kick everyone out"),
    ]

    dynamic_intents = []
    if db_rules:
        for rule in db_rules:
            desc = rule.get("description", "").strip()
            if desc:
                dynamic_intents.append((rule["intent"], desc))

    all_intents = base_intents + dynamic_intents + [("unknown", "cannot determine intent")]
    valid_keys  = [k for k, _ in all_intents]
    intent_lines = "\n".join(f"- {k}: {d}" for k, d in all_intents)

    prompt = f"""You are an intent classifier for {org_name}.
Identify the intent and entity from the user message.

VALID INTENTS — return ONLY one of these exact intent keys:
{intent_lines}

RULES:
- You MUST return one of: {json.dumps(valid_keys)}
- Do NOT invent or modify intent keys
- Prefer specific custom intents over generic ones when both could match
- Strip prepositions (of / for / ka / ki / ke) from the START of the entity only

Return ONLY valid JSON, no extra text:
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
        # Hard-reject any key the LLM invented
        if parsed.get("intent") not in valid_keys:
            print(f"[CLASSIFIER] LLM returned invalid intent '{parsed.get('intent')}', defaulting to unknown")
            parsed["intent"] = "unknown"
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
async def classify_message(text: str, org_name: str = "your organisation", org_id: str = None) -> dict:
    # Tier 1 — free, instant
    t1 = tier1_exact(text)
    if t1:
        return {"intent": t1, "tier": 1, "confidence": 1.0, "entity_raw": None}

    # Load DB patterns if org_id provided
    db_rules = []
    if org_id:
        db_rules = await load_patterns_from_db(org_id)

    # Tier 2 — near-free regex (hardcoded + DB-loaded)
    t2 = tier2_keyword(text, db_rules)
    if t2:
        return t2

    # Pass db_rules so LLM knows about dynamic intents
    t3 = await tier3_llm(text, org_name, db_rules)
    return t3
