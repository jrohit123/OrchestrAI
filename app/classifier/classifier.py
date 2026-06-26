import re

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


# ── TIER 2: SYSTEM INTENTS ONLY ───────────────────────
# NOTE: Only system admin intents are hardcoded. Business routing now via Intent Analyzer.
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
        ],
        "entity": None
    },
]


def tier2_keyword(text: str, db_rules: list = None):
    """System-only regex — no DB patterns in Intent+Action routing."""
    t = text.strip().lower()
    
    for rule in KEYWORD_RULES:
        for pattern in rule["patterns"]:
            m = re.search(pattern, t)
            if m:
                print(f"[CLASSIFIER] System intent matched: {rule['intent']}")
                return {
                    "intent": rule["intent"],
                    "entity_raw": None,
                    "tier": 2,
                    "confidence": 0.95
                }
    return None


def invalidate_patterns_cache(org_id: str = None):
    """No-op — patterns cache removed in Intent+Action routing."""
    pass


# ── MAIN ROUTER ──────────────────────────────────────
async def classify_message(text: str, org_name: str = "your organisation", 
                           org_id: str = None, user_role: str = "owner") -> dict:
    # Tier 1 — exact match, free
    t1 = tier1_exact(text)
    if t1:
        return {"intent": t1, "tier": 1, "confidence": 1.0,
                "route_type": "system", "entity_raw": None}

    # Tier 2 — system-only regex (NOT DB patterns)
    t2 = tier2_keyword(text, db_rules=None)
    if t2:
        return {**t2, "route_type": "system"}

    # Tier 3 — Intent Analyzer
    if not org_id:
        return {"route_type": "unknown", "tier": 3, "intent": "unknown",
                "entity_raw": None, "confidence": 0.0}

    from app.services.intent_analyzer import analyze_intent
    result = await analyze_intent(text, org_id, org_name, user_role)
    return result
