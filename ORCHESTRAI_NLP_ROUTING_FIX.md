# OrchestrAI — NLP Routing Fix + Fresh Workflow Seed

## Overview
This implements the 5-layer routing fix. Run SQL first, then apply code changes.
The interactive demo you saw is exactly what this builds — pre-classifier → DB filter → Tier2 → entity validation → LLM fallback.

---

## PART 1 — SQL (Run ALL in Neon SQL Editor in order)

```sql
-- 1. Add intent_metadata column to workflows
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS
    intent_metadata JSONB DEFAULT '{}';

-- 2. CLEAR all existing workflows (you have backup)
DELETE FROM workflows WHERE org_id = '11111111-0000-0000-0000-000000000001';

-- 3. Seed workflows fresh — correct patterns, negative signals, metadata

-- ── ENTITY QUERY WORKFLOWS ──────────────────────────

-- check_stock: specific product lookup
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'check_stock',
    'Check Product Stock',
    'Check current stock level of a specific product.',
    true,
    'inventory.check_stock',
    jsonb_build_array(
        'stock (.+)',
        'how many (.+) do we have',
        'kitna (.+) hai',
        '(.+) available',
        '(.+) ka stock',
        'inventory of (.+)',
        'how much (.+) is left',
        'show stock of (.+)'
    ),
    '{
        "query_type": "entity_query",
        "requires_entity": true,
        "entity_type": "product",
        "short_description": "Check stock for ONE specific product by name.",
        "negative_signals": ["all stock", "full inventory", "list all", "show all", "stock all", "complete inventory"],
        "entity_blocklist": ["product", "products", "item", "items", "stock", "all", "inventory"],
        "example_queries": ["stock gold ring", "how many bangles do we have", "kitna necklace hai", "22kt ring available"]
    }'::jsonb
);

-- check_outstanding: single customer dues
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'check_outstanding',
    'Check Customer Dues',
    'Check pending/overdue invoices for ONE specific customer.',
    true,
    'crm.get_outstanding',
    jsonb_build_array(
        '^dues (.+)',
        'outstanding (.+)',
        '(.+) ka kitna bacha',
        '(.+) ka kitna',
        'kitna bacha (.+)',
        'pending payment (.+)',
        'how much does (.+) owe',
        '(.+) owes',
        'balance (.+)'
    ),
    '{
        "query_type": "entity_query",
        "requires_entity": true,
        "entity_type": "customer",
        "short_description": "Check dues for ONE specific named customer.",
        "negative_signals": ["dues report", "all dues", "top dues", "customer wise", "all outstanding", "overdue report", "dues summary", "all customers", "everyone", "top 3", "top \\d+"],
        "entity_blocklist": ["customer", "customers", "report", "all", "everyone", "top", "summary", "payment", "outstanding", "dues"],
        "example_queries": ["dues Mehta", "outstanding Sharma", "Kapoor ka kitna bacha hai", "how much does Patel owe", "Agarwal balance"]
    }'::jsonb
);

-- check_credit_limit: single customer credit
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'check_credit_limit',
    'Check Credit Limit',
    'Check credit limit assigned to ONE specific customer.',
    true,
    'crm.get_credit_limit',
    jsonb_build_array(
        'credit limit (.+)',
        'credit limit of (.+)',
        'credit limit for (.+)',
        '(.+) credit limit',
        'what is the credit limit of (.+)',
        'what is the credit limit for (.+)',
        'how much credit does (.+) have',
        'credit available for (.+)',
        '(.+) ka credit'
    ),
    '{
        "query_type": "entity_query",
        "requires_entity": true,
        "entity_type": "customer",
        "short_description": "Check credit limit for ONE specific named customer.",
        "negative_signals": ["set credit", "update credit", "all customers", "every customer"],
        "entity_blocklist": ["customer", "customers", "all", "credit", "limit", "everyone"],
        "example_queries": ["credit limit Mehta", "Sharma ka credit limit kitna hai", "how much credit does Kapoor have", "Patel credit available"]
    }'::jsonb
);

-- ── REPORT WORKFLOWS ────────────────────────────────

-- get_all_overdue: overdue report (THE MISSING WORKFLOW)
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'get_all_overdue',
    'All Overdue Dues Report',
    'Show all overdue customers and their outstanding amounts.',
    true,
    'crm.get_all_overdue',
    jsonb_build_array(
        '^dues report$',
        'all overdue',
        'all dues',
        'overdue report',
        'top \\d+ dues',
        'dues summary',
        'outstanding report',
        'who owes us',
        'overdue summary',
        'customer wise dues',
        'give me top',
        'top dues',
        'top \\d+ outstanding',
        'all outstanding customers',
        'dues of all customers',
        'show all dues'
    ),
    '{
        "query_type": "report",
        "requires_entity": false,
        "entity_type": null,
        "short_description": "Show ALL overdue customers sorted by amount. Use for reports, summaries, top-N queries.",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["dues report", "top 3 dues customer wise", "all overdue customers", "who owes us money", "show all dues", "give me dues summary", "overdue report"]
    }'::jsonb
);

-- list_all_stock: full inventory report
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'list_all_stock',
    'Full Inventory List',
    'Show all products in inventory with quantities.',
    true,
    'inventory.list_all_stock',
    jsonb_build_array(
        'stock all',
        'all stock',
        'full inventory',
        'list all stock',
        'show all inventory',
        'what all do we have',
        'what do we have in stock',
        'complete inventory',
        'show all products',
        'entire inventory',
        'all items in stock'
    ),
    '{
        "query_type": "report",
        "requires_entity": false,
        "entity_type": null,
        "short_description": "Show complete list of ALL products in inventory.",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["stock all", "full inventory", "what all do we have", "show all products", "complete inventory list"]
    }'::jsonb
);

-- view_orders: active orders list
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'view_orders',
    'View Orders',
    'View active, pending, or delivered orders.',
    true,
    'orders.get_orders',
    jsonb_build_array(
        'pending orders',
        'orders ready',
        'active orders',
        'show orders',
        'all orders',
        'orders today',
        'my orders',
        'list orders',
        'orders in production',
        'delivered orders',
        'order status (ord-\\d+)',
        'order status (\\d+)',
        'check order (ord-\\d+)',
        'check order (\\d+)'
    ),
    '{
        "query_type": "report",
        "requires_entity": false,
        "entity_type": null,
        "short_description": "View list of orders by status (active/ready/delivered) or check a specific order by ID.",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["pending orders", "orders ready", "active orders", "order status ORD-1001", "show all orders"]
    }'::jsonb
);

-- ── ACTION WORKFLOWS ────────────────────────────────

-- create_invoice: generate invoice
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata,
    otp_required, otp_threshold, approval_threshold)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'create_invoice',
    'Create Invoice',
    'Create a sales invoice for a customer.',
    true,
    'accounting.create_invoice',
    jsonb_build_array(
        'invoice (.+) \\d+',
        'bill (.+) \\d+',
        'raise invoice (.+)',
        'create bill (.+)',
        'generate invoice (.+)'
    ),
    '{
        "query_type": "action",
        "requires_entity": true,
        "entity_type": "customer",
        "short_description": "Create invoice for a customer with amount. Format: invoice [customer] [amount].",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["invoice Mehta 25000", "bill Kapoor 50000", "invoice Sharma 2 gold rings 90000", "raise invoice Patel 75000"]
    }'::jsonb,
    true, 60000.00, 100000.00
);

-- create_quotation: price quotation
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'create_quotation',
    'Generate Price Quotation',
    'Generate a price quotation PDF for a customer.',
    true,
    'quotation.create_quotation',
    jsonb_build_array(
        'quote (.+)',
        'quotation (.+)',
        'give quote (.+)',
        'price for (.+)',
        'how much for (.+)',
        'generate quote (.+)',
        'make quote (.+)'
    ),
    '{
        "query_type": "action",
        "requires_entity": true,
        "entity_type": "customer",
        "short_description": "Generate price quotation. Format: quote [customer] [metal] [weight]g.",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["quote Mehta 22kt 15.5g", "quotation for Kapoor 18kt 8g", "quote Sharma 22kt 10g DC-001"]
    }'::jsonb
);

-- set_metal_rate: update rates (owner only)
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'set_metal_rate',
    'Update Metal Rate',
    'Update gold/silver rate or making charges.',
    true,
    'quotation.set_metal_rate',
    jsonb_build_array(
        'set rate (.+)',
        'update rate (.+)',
        'gold rate (.+)',
        'set gold (.+)',
        'set silver (.+)',
        'set making (.+)',
        'update making (.+)',
        'set gst (.+)',
        'update gst (.+)',
        'change rate (.+)'
    ),
    '{
        "query_type": "action",
        "requires_entity": false,
        "entity_type": null,
        "short_description": "Update metal rate or making charges. Owner only. Format: set rate 22kt 6200.",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["set rate 22kt 6200", "update making 22kt 15", "set gst 3", "gold rate 22kt 6500", "set silver rate 90"]
    }'::jsonb
);

-- create_order: new production order
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'create_order',
    'Create Production Order',
    'Create a new production order for a customer.',
    true,
    'orders.create_order',
    jsonb_build_array(
        'new order (.+)',
        'create order (.+)',
        'place order (.+)',
        'book order (.+)',
        'accept quote (.+)',
        'confirm quote (.+)',
        'start production (.+)',
        'order (.+) production'
    ),
    '{
        "query_type": "action",
        "requires_entity": true,
        "entity_type": "customer",
        "short_description": "Create new production order. Format: new order [customer] [description].",
        "negative_signals": ["pending orders", "active orders", "show orders", "order status"],
        "entity_blocklist": ["order", "orders", "production", "all"],
        "example_queries": ["new order Mehta 22kt gold ring", "new order Kapoor diamond bangle", "accept quote QUO-1001", "place order Sharma silver anklet"]
    }'::jsonb
);

-- update_order: update order status
INSERT INTO workflows (org_id, intent_key, name, description, is_active,
    adapter_method, trigger_patterns, intent_metadata)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'update_order',
    'Update Order Status',
    'Update production/delivery status of an order.',
    true,
    'orders.update_order_status',
    jsonb_build_array(
        'update (ord-\\d+) (.+)',
        'update (\\d+) (.+)',
        'mark (ord-\\d+) (.+)',
        'mark (\\d+) (.+)',
        'delivered (ord-\\d+)',
        'order (ord-\\d+) (.+)',
        '(ord-\\d+) ready',
        '(ord-\\d+) delivered'
    ),
    '{
        "query_type": "action",
        "requires_entity": false,
        "entity_type": null,
        "short_description": "Update order status. Format: update ORD-001 [status].",
        "negative_signals": [],
        "entity_blocklist": [],
        "example_queries": ["update ORD-1001 ready", "mark ORD-1002 delivered", "update ORD-1003 in production", "ORD-1001 ready", "delivered ORD-1002"]
    }'::jsonb
);

-- ── VERIFY ───────────────────────────────────────────
SELECT intent_key, adapter_method,
       intent_metadata->>'query_type' as qtype,
       intent_metadata->>'requires_entity' as needs_entity,
       jsonb_array_length(trigger_patterns) as patterns
FROM workflows
WHERE org_id = '11111111-0000-0000-0000-000000000001'
ORDER BY intent_metadata->>'query_type', intent_key;
```

---

## PART 2 — Updated Classifier with Pre-Classifier

### MODIFY: `app/classifier/classifier.py`
```python
import re
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── TIER 1: EXACT MATCH ──────────────────────────────
EXACT_MAP = {
    "1":      "action:select_1",
    "2":      "action:select_2",
    "3":      "action:select_3",
    "hi":     "action:greet",
    "hello":  "action:greet",
    "help":   "action:menu",
    "menu":   "action:menu",
    "stop":   "action:unsubscribe",
    "retry":  "action:retry_otp",
}

# ── SYSTEM INTENT PATTERNS (never from DB) ────────────
SYSTEM_RULES = [
    {
        "intent": "clear_sessions",
        "patterns": [
            r"clear\s+all\s+sessions", r"lock\s+all\s+accounts",
            r"emergency\s+lock", r"^lockdown$", r"clear\s+sessions",
            r"logout\s+everyone", r"revoke\s+all\s+access",
        ]
    },
    {
        "intent": "manage_schedule",
        "patterns": [
            r"schedule\s+dues", r"schedule\s+report",
            r"send\s+dues\s+report\s+every", r"send\s+report\s+every",
            r"change\s+.*report.*to", r"^reschedule",
            r"stop\s+dues\s+report", r"stop\s+schedule",
            r"cancel\s+schedule", r"when\s+is\s+(due|report)",
            r"dues\s+report\s+schedule", r"dues\s+report\s+every",
        ]
    },
]

# ── ENTITY BLOCKLIST (generic words that are NOT valid entity names) ──
ENTITY_BLOCKLIST = {
    # Generic structural words
    "customer", "customers", "report", "all", "dues", "stock", "order", "orders",
    "top", "summary", "everyone", "payment", "payments", "invoice", "invoices",
    "overdue", "outstanding", "pending", "balance", "credit", "limit",
    "product", "products", "item", "items",
    # Common function words
    "today", "now", "me", "us", "our", "the", "this", "that", "who",
    # Report signal words
    "wise", "wise?", "list", "show", "full", "complete", "entire",
}


# ── PRE-CLASSIFIER — deterministic, runs before everything ────────────
def pre_classify_query_type(text: str) -> str:
    """
    Detect query structure before any regex or LLM.
    Returns: entity_query | report | action | lookup | unknown
    
    This is Layer 1 — pure logic, no ML.
    It shrinks the candidate workflow set before classification runs.
    """
    t = text.strip().lower()

    # LOOKUP — specific ID reference
    if re.search(r'\b(ord|inv|quo)-\d+\b', t, re.IGNORECASE):
        return "lookup"

    # REPORT signals — aggregate / list / summary requests
    report_patterns = [
        r'\btop\s+\d+\b',
        r'\ball\s+(customers?|orders?|dues?|stock|overdue|outstanding)\b',
        r'\bcustomer\s*wise\b',
        r'\b(dues|overdue|outstanding)\s+(report|summary)\b',
        r'\breport\b',
        r'\bsummary\b',
        r'\beveryone\b',
        r'\blist\s+all\b',
        r'\bshow\s+all\b',
        r'\bfull\s+inventory\b',
        r'\bstock\s+all\b',
        r'\ball\s+stock\b',
        r'\bcomplete\s+inventory\b',
        r'\bpending\s+orders\b',
        r'\bactive\s+orders\b',
        r'\borders\s+ready\b',
        r'\bshow\s+orders\b',
        r'\bmy\s+orders\b',
        r'\ball\s+dues\b',
        r'\bwho\s+owes\b',
        r'\bshow\s+all\s+(dues|outstanding)\b',
    ]
    for p in report_patterns:
        if re.search(p, t):
            return "report"

    # ACTION signals — create/update operations with strong structural cues
    action_patterns = [
        r'\b(invoice|bill)\s+\w+\s+\d{3,}',  # invoice Mehta 25000
        r'\bnew\s+order\b',
        r'\bcreate\s+order\b',
        r'\bplace\s+order\b',
        r'\b(update|mark)\s+(ord-\d+|\d{3,})',  # update ORD-001
        r'\bset\s+(rate|making|gst)\b',
        r'\b(quote|quotation)\s+\w+\s+\d+kt\b',  # quote Mehta 22kt
        r'\b(accept|confirm)\s+quote\b',
        r'\bdelivered\s+(ord-\d+|\d{3,})\b',
    ]
    for p in action_patterns:
        if re.search(p, t):
            return "action"

    # Default to entity_query
    return "entity_query"


def _clean_entity(entity: str) -> str:
    if not entity:
        return entity
    for prep in ["of ", "for ", "ka ", "ki ", "ke "]:
        if entity.lower().startswith(prep):
            entity = entity[len(prep):]
    return entity.strip().title()


def _is_valid_entity(entity: str, entity_type: str,
                     workflow_blocklist: list = None) -> bool:
    """Returns True if entity looks like a real name, not a generic word."""
    if not entity:
        return False
    entity_lower = entity.lower().strip()
    if entity_lower in ENTITY_BLOCKLIST:
        return False
    if workflow_blocklist:
        if entity_lower in [b.lower() for b in workflow_blocklist]:
            return False
    if len(entity_lower) < 2:
        return False
    return True


def tier1_exact(text: str):
    return EXACT_MAP.get(text.strip().lower())


def _run_system_tier2(text: str) -> dict | None:
    t = text.strip().lower()
    for rule in SYSTEM_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, t):
                return {
                    "intent": rule["intent"],
                    "entity_raw": None,
                    "tier": 2,
                    "confidence": 0.95,
                    "limit": None
                }
    return None


# ── IN-MEMORY CACHE with TTL ─────────────────────────
_pattern_cache: dict = {}


def invalidate_patterns_cache(org_id: str = None):
    global _pattern_cache
    if org_id:
        _pattern_cache.pop(org_id, None)
    else:
        _pattern_cache.clear()
    print(f"[CLASSIFIER] Cache invalidated for {org_id or 'all'}")


async def _load_org_rules(org_id: str) -> list:
    """Load workflow rules from DB with metadata. Cached per org."""
    global _pattern_cache
    if org_id in _pattern_cache:
        return _pattern_cache[org_id]

    try:
        from app.db import fetch_all
        rows = await fetch_all("""
            SELECT intent_key, trigger_patterns, description,
                   intent_metadata, adapter_method
            FROM workflows
            WHERE org_id = $1 AND is_active = true
        """, org_id)

        rules = []
        for row in rows:
            patterns = row.get("trigger_patterns") or []
            if isinstance(patterns, str):
                patterns = json.loads(patterns)

            metadata = row.get("intent_metadata") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            rules.append({
                "intent": row["intent_key"],
                "patterns": patterns,
                "metadata": metadata,
                "short_description": metadata.get("short_description", row.get("description", "")),
                "query_type": metadata.get("query_type", "entity_query"),
                "requires_entity": metadata.get("requires_entity", True),
                "entity_type": metadata.get("entity_type"),
                "negative_signals": metadata.get("negative_signals", []),
                "entity_blocklist": metadata.get("entity_blocklist", []),
                "example_queries": metadata.get("example_queries", []),
            })
            print(f"[CLASSIFIER] Loaded: {row['intent_key']} ({metadata.get('query_type', '?')}) {len(patterns)} patterns")

        _pattern_cache[org_id] = rules
        return rules
    except Exception as e:
        print(f"[CLASSIFIER] DB load error: {e}")
        return []


def _run_db_tier2(text: str, rules: list, query_type: str) -> dict | None:
    """
    Run Tier2 regex with:
    1. Query type pre-filter (only match same-type workflows)
    2. Negative signal check (even if pattern matches, block if negative)
    3. Entity validation
    """
    t = text.strip().lower()

    # Extract limit for report queries
    limit = None
    lm = re.search(r'\btop\s+(\d+)\b', t)
    if lm:
        limit = int(lm.group(1))

    for rule in rules:
        # Skip if query_type doesn't match (core of the fix)
        rule_qt = rule.get("query_type", "entity_query")

        # Type-based pre-filter
        # entity_query can also match action (invoice parsing handled separately)
        if query_type == "report" and rule_qt not in ("report", "lookup"):
            continue
        if query_type == "lookup" and rule_qt != "report":
            continue
        if query_type == "action" and rule_qt not in ("action", "entity_query"):
            continue

        if not rule.get("patterns"):
            continue

        for pattern in rule["patterns"]:
            try:
                m = re.search(pattern, t)
                if not m:
                    continue

                # Negative signal check — even if pattern matched, block it
                neg_signals = rule.get("negative_signals", [])
                blocked = False
                for neg in neg_signals:
                    if re.search(neg, t):
                        print(f"[CLASSIFIER] Blocked {rule['intent']} by negative signal: {neg}")
                        blocked = True
                        break
                if blocked:
                    continue

                # Extract entity
                entity = None
                if m.lastindex and m.lastindex >= 1:
                    entity = m.group(1).strip() if m.group(1) else None
                entity = _clean_entity(entity) if entity else None

                # Validate entity if required
                if rule.get("requires_entity") and entity:
                    if not _is_valid_entity(entity, rule.get("entity_type"),
                                            rule.get("entity_blocklist", [])):
                        print(f"[CLASSIFIER] Entity '{entity}' blocked by blocklist for {rule['intent']}")
                        continue

                print(f"[CLASSIFIER] Matched: {pattern} → {rule['intent']} entity={entity}")
                return {
                    "intent": rule["intent"],
                    "entity_raw": entity,
                    "tier": 2,
                    "confidence": 0.85,
                    "limit": limit,
                    "query_type": query_type
                }
            except re.error:
                continue

    return None


async def tier3_llm(text: str, org_name: str, rules: list = None,
                    query_type: str = "entity_query") -> dict:
    """
    LLM fallback — receives small, pre-filtered candidate set.
    Prompt is structured by query_type, not a flat list.
    """
    # Separate rules by type
    entity_intents, report_intents, action_intents = [], [], []
    for r in (rules or []):
        qt = r.get("query_type", "entity_query")
        desc = r.get("short_description", "")
        examples = r.get("example_queries", [])
        ex_str = " | ".join(examples[:3])
        entry = f"- {r['intent']}: {desc}" + (f"\n  Examples: {ex_str}" if ex_str else "")
        if qt == "report":
            report_intents.append(entry)
        elif qt == "action":
            action_intents.append(entry)
        else:
            entity_intents.append(entry)

    # System intents always available
    system_block = """SYSTEM INTENTS:
- manage_schedule: Schedule or change timing of automated reports.
- clear_sessions: Emergency lockout — clear all active user sessions."""

    # Build intent section based on query_type
    if query_type == "report":
        intent_block = "REPORT INTENTS (aggregate, summary, top-N, all-customers):\n" + \
                       "\n".join(report_intents) if report_intents else ""
        context = "The user is asking for a LIST or SUMMARY, not about one specific entity."
    elif query_type == "action":
        intent_block = "ACTION INTENTS (create, update, set):\n" + \
                       "\n".join(action_intents) if action_intents else ""
        context = "The user wants to CREATE or UPDATE something."
    else:
        intent_block = "ENTITY INTENTS (one specific customer/product by name):\n" + \
                       "\n".join(entity_intents) if entity_intents else ""
        context = "The user is asking about ONE specific named entity (customer or product)."

    all_valid_keys = [r["intent"] for r in (rules or [])] + \
                     ["manage_schedule", "clear_sessions", "unknown"]

    prompt = f"""You are an intent classifier for {org_name}, a jewellery business in India.

Query context: {context}

{intent_block}

{system_block}

CRITICAL RULES:
1. Return ONLY one of these exact keys: {json.dumps(all_valid_keys)}
2. Query type is "{query_type}" — prefer intents that match this type
3. Strip prepositions (of / for / ka / ki / ke) from entity_raw
4. If entity would be a generic word (customers/all/report/top/dues/stock) → set entity_raw to null
5. If no good match → return "unknown"
6. "top N", "customer wise", "all customers" → ALWAYS report-type intent
7. "dues [Name]" where Name is a proper noun → ALWAYS check_outstanding

Return ONLY valid JSON:
{{"intent": "...", "entity_raw": "...", "confidence": 0.0}}

User message: {text}"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1  # Lower temp for more deterministic classification
    )

    raw = response.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
        if parsed.get("intent") not in all_valid_keys:
            print(f"[CLASSIFIER] LLM returned invalid intent '{parsed.get('intent')}' → unknown")
            parsed["intent"] = "unknown"
        if parsed.get("entity_raw"):
            parsed["entity_raw"] = _clean_entity(parsed["entity_raw"])
            # Validate entity even from LLM
            if parsed["entity_raw"] and \
               parsed["entity_raw"].lower() in ENTITY_BLOCKLIST:
                print(f"[CLASSIFIER] LLM entity '{parsed['entity_raw']}' blocked")
                parsed["entity_raw"] = None
    except Exception:
        parsed = {"intent": "unknown", "entity_raw": None, "confidence": 0.0}

    return parsed | {"tier": 3, "limit": None, "query_type": query_type}


async def classify_message(text: str, org_name: str = "your organisation",
                           org_id: str = None) -> dict:
    """
    5-layer classification:
    Pre-classify → Tier1 exact → System Tier2 → DB Tier2 → LLM Tier3
    """
    # Layer 0: Pre-classify query type (deterministic, no ML)
    query_type = pre_classify_query_type(text)
    print(f"[CLASSIFIER] Pre-classify: '{text[:40]}' → {query_type}")

    # Tier 1 — exact match
    t1 = tier1_exact(text)
    if t1:
        return {"intent": t1, "tier": 1, "confidence": 1.0,
                "entity_raw": None, "limit": None, "query_type": query_type}

    # Tier 2a — system intents (static)
    t2s = _run_system_tier2(text)
    if t2s:
        return t2s | {"query_type": query_type}

    # Load org rules
    rules = []
    if org_id:
        rules = await _load_org_rules(org_id)

    # Tier 2b — DB patterns with type-filter + negative signals
    t2 = _run_db_tier2(text, rules, query_type)
    if t2:
        return t2

    # Tier 3 — LLM with filtered candidates + query_type context
    return await tier3_llm(text, org_name, rules, query_type)
```

---

## PART 3 — Entity Validation Gate in Executor

### MODIFY: `app/executor/workflow_executor.py`

Add this function before `execute_intent`:

```python
async def _find_report_sibling(org_id: str, failed_intent: str) -> dict | None:
    """
    When an entity_query fails entity validation,
    try to find a report-type sibling to reroute to.
    e.g. check_outstanding fails → get_all_overdue
    e.g. check_stock fails → list_all_stock
    """
    SIBLING_MAP = {
        "check_outstanding": "get_all_overdue",
        "get_outstanding":   "get_all_overdue",
        "check_stock":       "list_all_stock",
        "check_credit_limit": None,  # no report sibling
    }
    sibling_key = SIBLING_MAP.get(failed_intent)
    if not sibling_key:
        return None
    return await _get_workflow(org_id, sibling_key)
```

Update `execute_intent` — add entity validation right after workflow lookup:

```python
    # ── LOAD WORKFLOW FROM DB ─────────────────────────────
    workflow = await _get_workflow(org_id, intent)
    if not workflow:
        return "🤔 Didn't understand that. Type *help* for the menu."

    adapter_method = workflow.get("adapter_method", "")
    if not adapter_method:
        return f"⚙️ Workflow *{intent}* has no adapter configured. Contact admin."

    # ── ENTITY VALIDATION GATE ────────────────────────────
    metadata = workflow.get("intent_metadata") or {}
    if isinstance(metadata, str):
        import json as _json
        metadata = _json.loads(metadata)

    if metadata.get("requires_entity") and entity_raw:
        entity_blocklist = metadata.get("entity_blocklist", [])
        from app.classifier.classifier import ENTITY_BLOCKLIST, _is_valid_entity
        entity_valid = _is_valid_entity(entity_raw, metadata.get("entity_type"), entity_blocklist)

        if not entity_valid:
            print(f"[EXECUTOR] Entity '{entity_raw}' invalid for {intent} — trying reroute")
            # Try to find a report-type sibling
            sibling = await _find_report_sibling(org_id, intent)
            if sibling:
                print(f"[EXECUTOR] Rerouting to {sibling['intent_key']}")
                workflow = sibling
                intent = sibling["intent_key"]
                adapter_method = sibling.get("adapter_method", "")
                entity_raw = None  # report needs no entity
            else:
                return (
                    f"🤔 Didn't find a customer named *{entity_raw}*.\n"
                    f"Try: *dues Mehta* or *dues report* for all customers"
                )

    elif metadata.get("requires_entity") and not entity_raw:
        entity_type = metadata.get("entity_type", "name")
        examples = metadata.get("example_queries", [])
        hint = f"\nTry: *{examples[0]}*" if examples else ""
        return f"🤔 Which {entity_type}?{hint}"
```

---

## PART 4 — Fix inventory.py deduct_stock call in accounting.py

### MODIFY: `app/adapters/accounting.py`

The `deduct_stock` function signature changed — update the call:

```python
# CHANGE THIS in create_invoice():
deduct = await deduct_stock(org_id, stock_info["sku"], qty)

# TO THIS:
from app.adapters.inventory import deduct_stock as _deduct
deduct = await _deduct(org_id=org_id, sku=stock_info["sku"], qty=qty)
```

---

## PART 5 — Updated Admin Workflow Generator

### MODIFY: `app/routers/admin.py` — replace `generate_workflow` route

```python
@router.post("/admin/api/workflow/generate")
async def generate_workflow(request: Request):
    _check_token(request)
    body = await request.json()
    description = body.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Description required")

    from app.adapters import ADAPTER_REGISTRY, get_available_methods
    from openai import AsyncOpenAI
    import os, json

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    org = await fetch_one("SELECT name, industry FROM orgs WHERE is_active = true LIMIT 1")

    registry_list = "\n".join(
        f"  - {m['method']}: {m['description']}"
        for m in get_available_methods()
        if m.get('method')
    )

    prompt = f"""You are building a workflow config for {org['name']}, a {org.get('industry','business')}.

Admin request: "{description}"

Available adapter_methods:
{registry_list}

QUERY TYPE RULES:
- "entity_query": workflow needs a specific named entity (customer name, product name, order ID) to work
  Examples: "check dues for Mehta", "stock gold ring", "credit limit Kapoor"
  adapter_methods: crm.get_outstanding, crm.get_credit_limit, inventory.check_stock

- "report": workflow returns aggregate/list data, no specific entity needed
  Examples: "show all overdue", "full inventory", "all active orders", "top 3 dues"
  adapter_methods: crm.get_all_overdue, inventory.list_all_stock, orders.get_orders

- "action": workflow creates or updates something
  Examples: "create invoice", "new order", "update status", "set gold rate"
  adapter_methods: accounting.create_invoice, orders.create_order, orders.update_order_status

- "lookup": workflow needs a specific ID (ORD-xxx, INV-xxx, QUO-xxx)
  adapter_methods: orders.get_orders (with ID filter)

CRITICAL INSTRUCTIONS:
1. Pick adapter_method EXACTLY from the list above
2. Set query_type based on the rules above — this is the most important field
3. trigger_patterns must be Python regex strings
   - For entity_query: include (.+) capture group for the entity name
   - For report: NO capture groups, just literal phrases
   - Test mentally: does "dues Mehta" match your patterns? Does "dues report" match your negative_signals?
4. negative_signals: phrases that LOOK relevant but should NOT trigger this workflow
   For get_outstanding: ["dues report", "all dues", "top \\\\d+", "customer wise", "all outstanding"]
5. entity_blocklist: generic words that are NOT valid entity values
   For customer entity: ["customer", "customers", "all", "report", "everyone"]
6. short_description: ONE sentence only. No keywords, no lists. Just what it does.
7. example_queries: 4 real WhatsApp-style messages. Keep them short, realistic.

Return ONLY valid JSON:
{{
  "intent_key": "snake_case_under_30_chars",
  "name": "Short Name (max 40 chars)",
  "adapter_method": "exact.method.from.list",
  "intent_metadata": {{
    "query_type": "entity_query|report|action|lookup",
    "requires_entity": true|false,
    "entity_type": "customer|product|order|invoice|null",
    "short_description": "One sentence what this does.",
    "negative_signals": ["phrase1", "phrase2"],
    "entity_blocklist": ["word1", "word2"],
    "example_queries": ["query1", "query2", "query3", "query4"]
  }},
  "trigger_patterns": ["pattern1", "pattern2", "pattern3", "pattern4"]
}}"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        config = json.loads(raw)

        # Validate adapter_method exists
        if config.get("adapter_method") not in ADAPTER_REGISTRY:
            config["warning"] = f"⚠️ Adapter '{config.get('adapter_method')}' not in registry. Check adapter_method."

        # Validate trigger patterns work on example queries
        pattern_warnings = []
        examples = config.get("intent_metadata", {}).get("example_queries", [])
        patterns = config.get("trigger_patterns", [])
        import re as _re
        for example in examples[:2]:
            matched = any(_re.search(p, example.lower()) for p in patterns)
            if not matched:
                pattern_warnings.append(f"'{example}' does not match any trigger pattern")

        if pattern_warnings:
            config["pattern_warnings"] = pattern_warnings

        return {"success": True, "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {str(e)}\nRaw: {raw[:300]}")


@router.post("/admin/api/workflow/save-generated")
async def save_generated_workflow(request: Request):
    _check_token(request)
    body = await request.json()
    config = body.get("config", {})

    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    org_id = str(org["id"])

    import json
    metadata = config.get("intent_metadata", {})

    await execute("""
        INSERT INTO workflows
        (org_id, intent_key, name, description, trigger_patterns,
         adapter_method, intent_metadata, is_active)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, true)
        ON CONFLICT (org_id, intent_key) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            trigger_patterns = EXCLUDED.trigger_patterns,
            adapter_method = EXCLUDED.adapter_method,
            intent_metadata = EXCLUDED.intent_metadata
    """, org_id, config["intent_key"],
        config.get("name", config["intent_key"]),
        metadata.get("short_description", ""),
        json.dumps(config.get("trigger_patterns", [])),
        config.get("adapter_method", ""),
        json.dumps(metadata))

    # Invalidate caches immediately
    from app.classifier.classifier import invalidate_patterns_cache
    from app.executor.workflow_executor import invalidate_workflow_cache
    invalidate_patterns_cache(org_id)
    invalidate_workflow_cache(org_id)

    # Auto-add to owner permissions
    await execute("""
        UPDATE roles SET permissions = array_append(permissions, $1)
        WHERE name = 'owner' AND org_id = $2
        AND NOT ($1 = ANY(permissions))
    """, config["intent_key"], org_id)

    return {
        "success": True,
        "intent_key": config["intent_key"],
        "message": f"Workflow '{config.get('name')}' is LIVE immediately."
    }
```

---

## PART 6 — Push to Railway

```bash
git add .
git commit -m "fix: 5-layer NLP routing — pre-classifier, entity validation, negative signals"
git push origin dev
```

---

## PART 7 — Test Workflows to Create from Admin Panel

After push, go to admin panel → AI Workflow Builder and create these one by one.

### Workflow 1
**Type in box:** `I want users to be able to send a PDF of an existing invoice by invoice number`

**Expected output:**
- intent_key: `send_invoice_pdf`
- adapter_method: `accounting.send_invoice_pdf`
- query_type: `lookup`
- patterns: `send invoice (inv-\d+)`, `invoice pdf (inv-\d+)`, `resend (inv-\d+)`

---

### Workflow 2
**Type in box:** `Users should be able to get a statement of all outstanding dues for a customer as a PDF`

**Expected output:**
- intent_key: `send_dues_statement`
- adapter_method: `accounting.send_dues_statement`
- query_type: `entity_query`
- entity_type: `customer`
- patterns: `dues statement (.+)`, `outstanding statement (.+)`, `send dues statement (.+)`

---

### Workflow 3
**Type in box:** `Admin should be able to accept a quotation and convert it to a production order`

**Expected output:**
- intent_key: `accept_quotation`
- adapter_method: `orders.accept_quotation`
- query_type: `action`
- patterns: `accept quote (quo-\d+)`, `confirm quote (quo-\d+)`, `convert quote (quo-\d+)`

---

## PART 8 — Complete Test Queries

**Run these in order. Each tests a different layer.**

### Pre-classifier Test (Layer 1)
```
# These should NEVER misroute
dues Mehta                         → check_outstanding (entity_query + specific name)
top 3 dues customer wise           → get_all_overdue (report signal: "top 3", "customer wise")
give me top 3 dues                 → get_all_overdue (report signal: "top 3")
all outstanding customers          → get_all_overdue (report signal: "all outstanding")
dues report                        → get_all_overdue (report: "report")
stock gold ring                    → check_stock (entity_query + product name)
stock all                          → list_all_stock (report signal: "stock all")
full inventory                     → list_all_stock (report signal)
what all do we have in stock       → list_all_stock (report signal)
```

### Entity Validation Test (Layer 4)
```
# These should NEVER reach the DB adapter
top 3 outstanding customers        → reroutes to get_all_overdue (entity "Customers" blocked)
show me all dues                   → get_all_overdue (reroute)
outstanding all customers          → get_all_overdue (reroute)
```

### Single Customer Queries
```
dues Mehta                         → Mehta Jewellers outstanding (pending: INV-001 Rs.45k, INV-004 Rs.62k)
outstanding Sharma                 → Sharma Gold House (INV-002 Rs.1.25L)
Kapoor ka kitna bacha hai          → Kapoor Trading Co dues (none — they have no invoices)
balance Patel                      → Patel Fine Jewellery (INV-005 Rs.35k overdue)
Agarwal owes us how much           → Agarwal Ornaments (INV-006 Rs.71k overdue)
how much does Sharma owe           → Sharma Gold House dues
```

### Report Queries
```
dues report                        → All 4 overdue customers listed
top 3 dues                         → Top 3 by amount
top 2 outstanding                  → Top 2 by amount
all overdue                        → Full overdue report
who owes us money                  → Full overdue report
```

### Stock Queries
```
stock gold ring                    → 22kt Gold Ring: 41 pcs (below reorder 50 ⚠️)
stock necklace                     → 22kt Gold Necklace: 2 pcs ⚠️
how many bangles do we have        → 18kt Diamond Bangle: 12 pcs
kitna necklace hai                 → 22kt Gold Necklace: 2 pcs
gold ring available                → 22kt Gold Ring: 41 pcs
stock all                          → Full inventory list (10 items)
full inventory                     → Full inventory list
what all do we have in stock       → Full inventory list
```

### Credit Limit Queries
```
credit limit Mehta                 → Mehta Jewellers: ₹5,00,000
Sharma ka credit limit kitna hai   → Sharma Gold House: ₹3,00,000
how much credit does Kapoor have   → Kapoor Trading Co: ₹2,00,000
Patel credit available             → Patel Fine Jewellery: ₹4,00,000
```

### Invoice Queries (OTP triggers at ₹60k)
```
invoice Mehta 25000                → Direct invoice (below threshold)
invoice Kapoor 30000               → Direct invoice
invoice Sharma 70000               → OTP triggered (above 60k)
invoice Mehta 2 gold rings 90000   → OTP triggered + stock check
```

### Quotation Queries
```
set rate 22kt 6200                 → Update 22kt gold rate
set making 22kt 15                 → Update making charges
set gst 3                          → Update GST
quote Mehta 22kt 15.5g             → Generate quotation PDF
quote Kapoor 18kt 8.2g             → Generate quotation PDF
```

### Order Queries
```
new order Mehta 22kt gold ring     → Create order
new order Kapoor diamond bangle    → Create order
pending orders                     → List active orders
orders ready                       → Orders ready for delivery
update ORD-1001 in production      → Update status
update ORD-1001 ready              → Mark ready
delivered ORD-1001                 → Mark delivered
order status ORD-1001              → Check specific order
```

### Hindi + Mixed Language (LLM Tier3)
```
Mehta ka kitna bacha hai           → check_outstanding → Mehta dues
Kapoor ka credit kitna hai         → check_credit_limit → Kapoor credit
kitna necklace bacha hai           → check_stock → necklace stock
sab customers ka dues batao        → get_all_overdue (report: "sab")
top 3 customers ka dues            → get_all_overdue (report: "top 3")
```

### Disambiguation Test (multiple matches)
```
dues Mehta                         → If Mehta Jewellers + Mehta Enterprises both exist:
                                     "Found 2: 1. Mehta Jewellers 2. Mehta Enterprises"
                                     Reply: 1 → Mehta Jewellers dues
                                     Reply: 2 → Mehta Enterprises dues
```

### Admin + Security
```
clear all sessions                 → Emergency lockout
schedule dues report every Tuesday 9 AM → Schedule
when is dues report scheduled      → Check schedule
```

### Edge Cases (should fail gracefully)
```
xyz customer dues                  → "No customer found matching Xyz Customer"
stock abc product                  → "No product found matching Abc Product"
dues                               → "Which customer? Try: dues Mehta"
invoice 25000                      → "Which customer? Try: invoice Mehta 25000"
```

---

## PART 9 — Verify Routing in Railway Logs

After push, send these messages and check Railway logs for pre-classifier output:

```
[CLASSIFIER] Pre-classify: 'top 3 dues customer wise' → report
[CLASSIFIER] Blocked check_outstanding by negative signal: top \d+
[CLASSIFIER] Matched: top \d+ dues → get_all_overdue entity=None

[CLASSIFIER] Pre-classify: 'dues Mehta' → entity_query
[CLASSIFIER] Matched: ^dues (.+) → check_outstanding entity=Mehta

[CLASSIFIER] Pre-classify: 'dues report' → report
[CLASSIFIER] Matched: dues report → get_all_overdue entity=None
```

If you see these log lines — routing is working correctly.
