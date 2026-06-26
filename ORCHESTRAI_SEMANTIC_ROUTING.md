# OrchestrAI — Semantic Embedding Routing: Full Implementation Guide

---

## The Exact Bug (from screenshot)

```
User: "Give me the top 3 dues customer wise"
Bot:  "🤔 Which customer? Try: dues Mehta"   ← WRONG

User: "Top 3 outstanding customers"
Bot:  "❌ No customer found matching Customers." ← WRONG
```

**Root cause:** Both queries fall through to `tier3_llm`. The LLM sees the word
"dues" / "outstanding" and maps them to `get_outstanding` (specific customer lookup).
It hallucinates entity_raw = `"Customers"` — a category word, not a proper noun.
`crm.get_outstanding` then literally queries for a customer named "Customers" and
fails. The correct intent is `weekly_dues_report` → `crm.get_all_overdue` (no entity).

**Why the old plan (ORCHESTRAI_NLP_ROUTING_FIX.md) still fails:** It adds a
blocklist + negative-signal regex. These are hardcoded English vocabulary assumptions.
A new org, a Hindi phrase, or an untested phrasing bypasses all of it.

**The right fix:** Semantic similarity via embeddings. Two intents that are genuinely
different ("dues Mehta" vs "all dues customers") will naturally cluster into different
regions of the embedding space — in any language, any phrasing.

---

## Architecture: New Three-Tier System

```
Tier 1  Exact match          hi / help / 1 / 2 / retry     instant, free
         ↓ miss
Tier 2a System regex          clear sessions / schedule      security-critical, hardcoded
         ↓ miss
Tier 2b Embedding search      embed query → pgvector cosine  ~80ms, $0.00002/msg
         → returns top-3 candidate workflows
         ↓
Tier 3  LLM param extract     sees top-3 only, extracts      focused, cheap
         required params — customer_name / invoice_number etc
         ↓ required param is null but intent needs one
Sibling  DB lookup             same adapter module, no entity  pure SQL, instant
discovery                      → reroute to report intent
```

---

## Step 1 — Database Changes

Run **all of these** in the Neon SQL editor in order.

```sql
-- ────────────────────────────────────────────────────────────────────────────
-- 1. Enable pgvector
-- ────────────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ────────────────────────────────────────────────────────────────────────────
-- 2. New table: workflow_utterances
--    Stores example phrases per workflow + their 1536-dim embeddings.
--    pgvector cosine search runs against this table on every message.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_utterances (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    intent_key  TEXT NOT NULL,
    utterance   TEXT NOT NULL,
    embedding   vector(1536),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index — fast cosine similarity, works well even on small datasets
CREATE INDEX IF NOT EXISTS idx_utterances_embedding
    ON workflow_utterances USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_utterances_org
    ON workflow_utterances (org_id);

CREATE INDEX IF NOT EXISTS idx_utterances_intent
    ON workflow_utterances (org_id, intent_key);

-- ────────────────────────────────────────────────────────────────────────────
-- 3. Add two columns to workflows
--    required_parameters: describes what entity this workflow needs (or {})
--    utterance_count:     how many utterances are stored (for monitoring)
-- ────────────────────────────────────────────────────────────────────────────
ALTER TABLE workflows
    ADD COLUMN IF NOT EXISTS required_parameters JSONB DEFAULT '{}';

ALTER TABLE workflows
    ADD COLUMN IF NOT EXISTS utterance_count INTEGER DEFAULT 0;

-- ────────────────────────────────────────────────────────────────────────────
-- 4. Backup current workflow rows before clearing
--    Run SELECT first — verify you see your 8 workflows
-- ────────────────────────────────────────────────────────────────────────────
-- SELECT intent_key, adapter_method FROM workflows
-- WHERE org_id = '11111111-0000-0000-0000-000000000001'
-- ORDER BY created_at;

-- ────────────────────────────────────────────────────────────────────────────
-- 5. Clear existing workflows for fresh seed
--    (Run only after you have a DB export / backup confirmed)
-- ────────────────────────────────────────────────────────────────────────────
DELETE FROM workflow_utterances
    WHERE org_id = '11111111-0000-0000-0000-000000000001';

DELETE FROM workflows
    WHERE org_id = '11111111-0000-0000-0000-000000000001';

-- ────────────────────────────────────────────────────────────────────────────
-- 6. Insert 12 fresh workflows (utterances come separately via Python script)
-- ────────────────────────────────────────────────────────────────────────────

-- 6.1  check_stock — requires product_name
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'check_stock',
    'Check Product Stock',
    'Check stock level of a specific product item. Entity type: product. '
    'Used by sales and warehouse staff to check availability before promising to a customer.',
    'inventory.check_stock',
    '[]'::jsonb,
    '{"product_name": {"required": true, "type": "proper_noun",
      "description": "Specific product name like gold ring, diamond bangle, silver chain. NOT generic words like product, item, stock, inventory."}}'::jsonb,
    true
);

-- 6.2  get_outstanding — requires customer_name
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'get_outstanding',
    'Check Customer Dues',
    'Check outstanding and overdue invoices for a SPECIFIC customer. Entity type: customer. '
    'Returns list of unpaid invoices with amounts. Used by accounts team.',
    'crm.get_outstanding',
    '[]'::jsonb,
    '{"customer_name": {"required": true, "type": "proper_noun",
      "description": "A specific customer name — a proper noun like Mehta, Sharma & Sons, Kapoor. NOT generic words like customer, all, everyone, top, list."}}'::jsonb,
    true
);

-- 6.3  weekly_dues_report — NO entity, all customers aggregate report
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'weekly_dues_report',
    'Dues Report (All Customers)',
    'Get overdue dues report across ALL customers — no specific customer needed. '
    'Supports top-N filters. Entity type: none. Used for management reporting.',
    'crm.get_all_overdue',
    '[]'::jsonb,
    '{}'::jsonb,
    true
);

-- 6.4  create_invoice — requires customer_name + amount
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active, otp_required, otp_threshold, approval_threshold)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'create_invoice',
    'Create Invoice',
    'Create a new sales invoice for a customer. Entity type: customer. '
    'Requires customer name and amount. Optionally qty and item name.',
    'accounting.create_invoice',
    '[]'::jsonb,
    '{"customer_name": {"required": true, "type": "proper_noun",
      "description": "Customer name (proper noun). Amount and item name also in the message."}}'::jsonb,
    true,
    false,
    50000,
    100000
);

-- 6.5  send_invoice_pdf — requires invoice_number
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'send_invoice_pdf',
    'Send Invoice PDF',
    'Send PDF of an existing invoice. Entity type: invoice number (INV-XXX format). '
    'Used by accounts team to resend invoices.',
    'accounting.send_invoice_pdf',
    '[]'::jsonb,
    '{"invoice_number": {"required": true, "type": "invoice_id",
      "description": "Invoice number in format INV-1101 or similar. NOT customer name."}}'::jsonb,
    true
);

-- 6.6  send_dues_statement — requires customer_name
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'send_dues_statement',
    'Send Dues Statement PDF',
    'Generate and send a PDF statement of all outstanding dues for a specific customer. '
    'Entity type: customer. Used by accounts team for customer-facing summaries.',
    'accounting.send_dues_statement',
    '[]'::jsonb,
    '{"customer_name": {"required": true, "type": "proper_noun",
      "description": "Specific customer name (proper noun) to generate statement for."}}'::jsonb,
    true
);

-- 6.7  create_quotation — requires customer_name + metal_type + weight
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'create_quotation',
    'Generate Price Quotation',
    'Generate and send a gold/jewellery price quotation PDF for a customer. '
    'Entity type: customer. Requires metal type (22kt, 18kt, silver) and weight in grams. '
    'Used by sales team to quote prices.',
    'quotation.create_quotation',
    '[]'::jsonb,
    '{"customer_name": {"required": true, "type": "proper_noun",
      "description": "Customer name (proper noun). Metal type and weight in grams also needed."}}'::jsonb,
    true
);

-- 6.8  set_metal_rate — requires metal_type + rate value
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'set_metal_rate',
    'Update Metal Rates',
    'Update the rate per gram for a specific metal type (22kt, 18kt, 14kt, silver, platinum). '
    'Also supports updating making charges % and GST rate. Entity type: metal type. '
    'Used by owner/manager when gold/silver market rates change.',
    'quotation.set_metal_rate',
    '[]'::jsonb,
    '{"metal_type": {"required": true, "type": "category",
      "description": "Metal type: 22kt, 18kt, 14kt, silver, or platinum. Plus the new rate value."}}'::jsonb,
    true
);

-- 6.9  create_order — requires customer_name + description
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'create_order',
    'Create Production Order',
    'Create a new manufacturing/production order for a customer. Entity type: customer. '
    'Includes item description and optional metal type. Used by production manager.',
    'orders.create_order',
    '[]'::jsonb,
    '{"customer_name": {"required": true, "type": "proper_noun",
      "description": "Customer name (proper noun) and description of the jewellery to be made."}}'::jsonb,
    true
);

-- 6.10  update_order_status — requires order_number + new_status
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'update_order_status',
    'Update Order Status',
    'Change the status of a specific production order (ORD-XXXX). '
    'Valid statuses: confirmed, in production, quality check, ready, delivered. '
    'Entity type: order number. Used by production and delivery staff.',
    'orders.update_order_status',
    '[]'::jsonb,
    '{"order_number": {"required": true, "type": "order_id",
      "description": "Order number in ORD-XXXX format, and the new status."}}'::jsonb,
    true
);

-- 6.11  get_orders — NO entity required (aggregate list)
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'get_orders',
    'View Active Orders',
    'View all active production orders in the system. No customer name needed. '
    'Supports filters: active (default), ready, delivered. Entity type: none.',
    'orders.get_orders',
    '[]'::jsonb,
    '{}'::jsonb,
    true
);

-- 6.12  get_credit_limit — requires customer_name
INSERT INTO workflows (org_id, intent_key, name, description, adapter_method,
    trigger_patterns, required_parameters, is_active)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'get_credit_limit',
    'Check Credit Limit',
    'Check the credit limit set for a specific customer. Entity type: customer. '
    'Used by sales team before accepting large orders.',
    'crm.get_credit_limit',
    '[]'::jsonb,
    '{"customer_name": {"required": true, "type": "proper_noun",
      "description": "Specific customer name (proper noun) to look up credit limit for."}}'::jsonb,
    true
);

-- ────────────────────────────────────────────────────────────────────────────
-- 7. Restore role permissions (owner gets all, accountant/sales/warehouse as before)
-- ────────────────────────────────────────────────────────────────────────────
UPDATE roles SET permissions = ARRAY[
    'check_stock','create_invoice','get_outstanding','weekly_dues_report',
    'manage_schedule','clear_sessions','get_credit_limit','create_quotation',
    'set_metal_rate','create_order','update_order_status','get_orders',
    'send_invoice_pdf','send_dues_statement'
]
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'owner';

UPDATE roles SET permissions = ARRAY[
    'get_outstanding','create_invoice','weekly_dues_report','get_orders',
    'send_invoice_pdf','send_dues_statement','check_stock'
]
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'accountant';

UPDATE roles SET permissions = ARRAY[
    'check_stock','create_invoice','create_quotation','create_order',
    'get_orders','get_credit_limit'
]
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'sales';

UPDATE roles SET permissions = ARRAY['check_stock']
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'warehouse';
```

---

## Step 2 — Complete Replacement: `app/classifier/classifier.py`

```python
"""
OrchestrAI — Three-Tier Semantic Classifier
Tier 1: Exact match (free, instant)
Tier 2a: System security intents (hardcoded regex, security-critical)
Tier 2b: Embedding similarity search via pgvector
Tier 3: LLM parameter extraction from top-3 candidates
Sibling: Dynamic DB lookup when entity required but absent
"""
import re
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ── TIER 1: EXACT MATCH ──────────────────────────────────────────────────────
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


# ── TIER 2A: SYSTEM INTENTS — hardcoded, security-critical ───────────────────
# These must NEVER be overrideable by a DB workflow. Keep them here.
SYSTEM_RULES = [
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
    },
]


def tier2a_system(text: str):
    t = text.strip().lower()
    for rule in SYSTEM_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, t):
                print(f"[CLASSIFIER] System intent matched: {rule['intent']}")
                return {
                    "intent": rule["intent"],
                    "entity_raw": None,
                    "tier": 2,
                    "confidence": 0.95,
                }
    return None


# ── TIER 2B: EMBEDDING SIMILARITY SEARCH ─────────────────────────────────────
async def _embed_text(text: str) -> list[float]:
    """Get 1536-dim embedding for a text string via OpenAI text-embedding-3-small."""
    response = await _client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


async def tier2b_embedding(text: str, org_id: str) -> list[dict]:
    """
    Embed the user's message and run cosine similarity search against all
    stored utterances for this org. Returns top-3 unique intent candidates.
    """
    from app.db import fetch_all

    embedding = await _embed_text(text)
    # Build vector literal for pgvector — safe because it's a float list
    vec_str = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

    rows = await fetch_all(
        """
        SELECT
            wu.intent_key,
            wu.utterance,
            w.adapter_method,
            w.required_parameters,
            w.description,
            1 - (wu.embedding <=> $2::vector) AS similarity
        FROM workflow_utterances wu
        JOIN workflows w ON w.id = wu.workflow_id
        WHERE wu.org_id = $1
          AND w.is_active = true
          AND wu.embedding IS NOT NULL
        ORDER BY wu.embedding <=> $2::vector
        LIMIT 10
        """,
        org_id,
        vec_str,
    )

    # Deduplicate — keep highest similarity score per intent
    seen: dict[str, dict] = {}
    for row in rows:
        key = row["intent_key"]
        sim = float(row["similarity"])
        if key not in seen or sim > seen[key]["similarity"]:
            req_params = row["required_parameters"]
            if isinstance(req_params, str):
                req_params = json.loads(req_params)
            seen[key] = {
                "intent":              key,
                "adapter_method":      row["adapter_method"],
                "required_parameters": req_params or {},
                "description":         row["description"] or "",
                "similarity":          sim,
                "best_utterance":      row["utterance"],
            }

    candidates = sorted(seen.values(), key=lambda x: x["similarity"], reverse=True)[:3]
    for c in candidates:
        print(
            f"[CLASSIFIER] Candidate: {c['intent']} "
            f"sim={c['similarity']:.3f} | '{c['best_utterance']}'"
        )
    return candidates


# ── TIER 3: LLM PARAMETER EXTRACTION ─────────────────────────────────────────
async def tier3_llm(text: str, org_name: str, candidates: list[dict]) -> dict:
    """
    Given top-3 candidates from embedding search, the LLM does two things:
    1. Picks the best matching intent (from candidates only — no hallucination)
    2. Extracts required parameters from the message

    Key rule injected into the prompt: if entity_raw would be a generic/category
    word (customer, all, everyone, customers, sabka) rather than a specific
    proper noun (Mehta, Sharma), it returns entity_raw = null. This is the fix
    for "Top 3 outstanding customers" → entity=null → sibling reroute.
    """
    if not candidates:
        return {"intent": "unknown", "entity_raw": None, "confidence": 0.0, "tier": 3}

    valid_keys = [c["intent"] for c in candidates] + ["unknown"]

    intent_lines = []
    for c in candidates:
        req = c.get("required_parameters", {})
        param_str = ""
        if req:
            parts = []
            for param_name, info in req.items():
                if isinstance(info, dict):
                    parts.append(f"{param_name} ({info.get('description', '')})")
                else:
                    parts.append(param_name)
            param_str = f"\n    Required params: {'; '.join(parts)}"
        intent_lines.append(f"- {c['intent']}: {c['description']}{param_str}")

    prompt = f"""You are an intent classifier for {org_name}, a jewellery business.
Given the user's WhatsApp message, pick the best intent and extract required parameters.

TOP CANDIDATE INTENTS (from semantic search — return ONLY one of these exact keys):
{chr(10).join(intent_lines)}
- unknown: message clearly doesn't match any of the above

CRITICAL RULES:
1. Return ONLY one of: {json.dumps(valid_keys)}
2. For required customer_name or product_name params:
   — Set entity_raw to the extracted PROPER NOUN (e.g. Mehta, Sharma, gold ring)
   — If the message has ONLY a generic/category word (customers, all, everyone,
     sabka, list, top, product, item) set entity_raw to null
   — "top 3", "sabse zyada", "top N" are NOT customer names; they mean report mode
3. For intents that say "Entity type: none" — always set entity_raw to null
4. Strip prepositions from start of entity: "for Mehta" → "Mehta"
5. Hindi/Hinglish entities: "Mehta ka" → "Mehta"

Return ONLY valid JSON, no extra text:
{{"intent": "...", "entity_raw": "...", "confidence": 0.0}}

User message: {text}"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=150,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
        # Hard-reject hallucinated intent keys
        if parsed.get("intent") not in valid_keys:
            print(f"[CLASSIFIER] LLM invented key '{parsed.get('intent')}' — defaulting unknown")
            parsed["intent"] = "unknown"
        # Clean entity
        entity = parsed.get("entity_raw")
        if entity:
            entity = entity.strip()
            for prep in ["of ", "for ", "ka ", "ki ", "ke "]:
                if entity.lower().startswith(prep):
                    entity = entity[len(prep):]
            parsed["entity_raw"] = entity.strip().title()
        else:
            parsed["entity_raw"] = None
    except Exception:
        parsed = {"intent": "unknown", "entity_raw": None, "confidence": 0.0}

    return parsed | {"tier": 3}


# ── SIBLING DISCOVERY — dynamic DB lookup ─────────────────────────────────────
async def find_report_sibling(intent_key: str, org_id: str) -> str | None:
    """
    When an entity-requiring intent can't find its entity (entity_raw = null),
    look for a sibling in the same adapter module that requires NO entity.

    Example: get_outstanding (crm.*) fails → look for crm.* with empty
    required_parameters → finds weekly_dues_report (crm.get_all_overdue).

    This is fully dynamic — no hardcoded map. Any org's custom workflows benefit.
    """
    from app.db import fetch_one

    # Find the failed workflow's adapter module
    wf = await fetch_one(
        "SELECT adapter_method FROM workflows WHERE intent_key = $1 AND org_id = $2",
        intent_key, org_id,
    )
    if not wf or "." not in (wf["adapter_method"] or ""):
        return None

    module = wf["adapter_method"].split(".")[0]  # e.g. "crm"

    # Find sibling: same module, is_active, no required parameters
    sibling = await fetch_one(
        """
        SELECT intent_key FROM workflows
        WHERE org_id = $1
          AND is_active = true
          AND intent_key != $2
          AND adapter_method LIKE $3
          AND (
              required_parameters IS NULL
              OR required_parameters::text IN ('{}', 'null', '""')
              OR required_parameters = '{}'::jsonb
          )
        LIMIT 1
        """,
        org_id,
        intent_key,
        f"{module}.%",
    )
    result = sibling["intent_key"] if sibling else None
    if result:
        print(f"[CLASSIFIER] Sibling reroute: {intent_key} → {result}")
    return result


# ── MAIN ROUTER ────────────────────────────────────────────────────────────────
async def classify_message(
    text: str, org_name: str = "your organisation", org_id: str = None
) -> dict:

    # Tier 1 — exact match, free
    t1 = tier1_exact(text)
    if t1:
        return {"intent": t1, "tier": 1, "confidence": 1.0, "entity_raw": None}

    # Tier 2a — system security intents, hardcoded
    t2a = tier2a_system(text)
    if t2a:
        return t2a

    if not org_id:
        return {"intent": "unknown", "tier": 3, "confidence": 0.0, "entity_raw": None}

    # Tier 2b — embedding similarity search
    candidates = await tier2b_embedding(text, org_id)

    if not candidates:
        print("[CLASSIFIER] No utterances found — org may not have workflows embedded yet")
        return {"intent": "unknown", "tier": 3, "confidence": 0.0, "entity_raw": None}

    top = candidates[0]

    # Fast path: very high confidence + no entity required → skip LLM entirely
    if (
        top["similarity"] >= 0.85
        and not top.get("required_parameters")
        and (len(candidates) < 2 or top["similarity"] - candidates[1]["similarity"] > 0.08)
    ):
        print(f"[CLASSIFIER] Fast path (no-entity, high-conf): {top['intent']} ({top['similarity']:.3f})")
        return {
            "intent":     top["intent"],
            "entity_raw": None,
            "tier":       2,
            "confidence": top["similarity"],
        }

    # Tier 3 — LLM parameter extraction from top candidates
    result = await tier3_llm(text, org_name, candidates)
    print(f"[CLASSIFIER] LLM result: intent={result['intent']} entity={result.get('entity_raw')}")

    # Sibling check: entity required by chosen intent, but entity_raw is null
    if result["intent"] != "unknown" and not result.get("entity_raw"):
        chosen = next((c for c in candidates if c["intent"] == result["intent"]), None)
        if chosen:
            req = chosen.get("required_parameters", {})
            needs_entity = any(
                (isinstance(v, dict) and v.get("required")) or v
                for v in req.values()
            ) if req else False

            if needs_entity:
                sibling = await find_report_sibling(result["intent"], org_id)
                if sibling:
                    return {
                        "intent":     sibling,
                        "entity_raw": None,
                        "tier":       3,
                        "confidence": 0.75,
                    }

    return result


# Backward-compat shim — kept so admin.py import doesn't break
def invalidate_patterns_cache(org_id: str = None):
    """No-op — patterns cache removed. Embeddings are queried live from pgvector."""
    pass
```

---

## Step 3 — Updated `app/api/admin.py` (changed sections only)

Replace the `generate_workflow_config` endpoint and add the `save_generated_workflow` endpoint + a new helper. All other endpoints in `admin.py` are **unchanged**.

### 3.1  New helper function (add near top of file, after imports)

```python
import numpy as np   # add this import at top

async def _embed_and_store_utterances(
    workflow_id: str, org_id: str, intent_key: str, utterances: list[str]
) -> int:
    """
    Embed utterances via OpenAI and store in workflow_utterances table.
    Returns number of utterances successfully stored.
    """
    from app.db import execute as db_execute, fetch_one as db_fetch_one

    if not utterances:
        return 0

    # Embed all at once (batch call)
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=utterances,
    )

    stored = 0
    for i, emb_obj in enumerate(response.data):
        utterance = utterances[i]
        embedding = emb_obj.embedding
        # Format as pgvector literal
        vec_str = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

        await db_execute(
            """
            INSERT INTO workflow_utterances
                (org_id, workflow_id, intent_key, utterance, embedding)
            VALUES ($1, $2, $3, $4, $5::vector)
            """,
            org_id, workflow_id, intent_key, utterance, vec_str,
        )
        stored += 1

    # Update utterance_count on workflow
    await db_execute(
        "UPDATE workflows SET utterance_count = $1 WHERE id = $2",
        stored, workflow_id,
    )
    return stored
```

### 3.2  Replace `generate_workflow_config` endpoint

```python
@router.post("/admin/api/workflow/generate")
async def generate_workflow_config(request: Request):
    _check_token(request)
    body = await request.json()
    description = body.get("description", "")

    if not description:
        raise HTTPException(status_code=400, detail="Description is required")

    prompt = f"""You are a workflow configuration generator for an Indian WhatsApp
business automation platform used by jewellery shops, traders, and SMBs.

User wants to add this workflow:
"{description}"

Generate ONLY this JSON structure with no other text:
{{
  "name": "2-4 word name",
  "intent_key": "exact_function_name_from_adapter_method",
  "description": "What this workflow does, who uses it, business context (2-3 sentences)",
  "adapter_method": "module.function",
  "required_parameters": {{
    "customer_name": {{
      "required": true,
      "type": "proper_noun",
      "description": "Specific customer name — a proper noun like Mehta, Sharma. NOT generic words."
    }}
  }},
  "utterances": [
    "20 diverse example phrases a real user would send for this intent",
    "Include Hindi/Hinglish variants like 'Mehta ka kitna bacha hai'",
    "Include formal English: 'What is the outstanding balance for Mehta'",
    "Include short forms: 'dues Mehta', 'Mehta outstanding'",
    "Include question forms: 'How much does Sharma owe?'",
    "Include command forms: 'Show me Kapoor dues'",
    "Include context-rich: 'invoice Mehta 25000 gold ring'",
    "...all 20 phrases here..."
  ]
}}

RULES:
- name: 2-4 words
- intent_key: MUST match the function name from adapter_method exactly
- description: 2-3 sentences — what, who, when
- adapter_method: MUST be ONE of these EXACT values:
  * "inventory.check_stock"           — check product stock level
  * "inventory.check_stock_availability" — check if qty available
  * "crm.get_credit_limit"            — customer credit limit
  * "crm.get_outstanding"             — customer specific dues
  * "crm.get_all_overdue"             — all customers dues report (no entity)
  * "accounting.create_invoice"       — create sales invoice
  * "accounting.send_invoice_pdf"     — send existing invoice as PDF
  * "accounting.send_dues_statement"  — send dues statement PDF
  * "quotation.create_quotation"      — create price quotation
  * "quotation.set_metal_rate"        — update metal/gold rates
  * "orders.create_order"             — create production order
  * "orders.update_order_status"      — update order status
  * "orders.get_orders"               — list/view orders (no entity)
  DO NOT use any other adapter methods.
- required_parameters:
  * If the workflow needs a specific ENTITY (customer name, product name, order number):
    include it with required=true and a clear description of what type of value
  * If the workflow works WITHOUT any entity (report, list, all-customers):
    set required_parameters to {{}}
  * NEVER mark generic filters (top N, status filter) as required params
- utterances: exactly 20 phrases covering:
  * 5 short/command forms (1-4 words)
  * 5 natural English questions
  * 5 Hindi/Hinglish phrases (mix of scripts is fine)
  * 3 full business context phrases
  * 2 edge case phrasings

Return ONLY the JSON. No explanations, no markdown fences."""

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1500,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    content = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    for fence in ("```json", "```"):
        if fence in content:
            start = content.find(fence) + len(fence)
            end = content.find("```", start)
            content = content[start:end].strip() if end != -1 else content[start:].strip()
            break

    # Extract JSON boundaries
    start_idx = content.find("{")
    end_idx = content.rfind("}") + 1
    if start_idx != -1 and end_idx > start_idx:
        content = content[start_idx:end_idx]

    try:
        config = json.loads(content)
        return config
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse AI response: {str(e)}. Raw: {content[:500]}",
        )
```

### 3.3  Replace `save_generated_workflow` endpoint

```python
@router.post("/admin/api/workflow/save")
async def save_generated_workflow(request: Request):
    _check_token(request)
    body = await request.json()

    adapter_method = body.get("adapter_method", "generic")
    utterances     = body.get("utterances", [])

    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")

    org_id = str(org["id"])

    # Check for duplicate intent_key
    existing = await fetch_one(
        "SELECT id FROM workflows WHERE org_id = $1 AND intent_key = $2",
        org_id, body.get("intent_key"),
    )
    if existing:
        raise HTTPException(status_code=400, detail="Intent key already exists")

    # Save workflow
    new_wf = await fetch_one(
        """
        INSERT INTO workflows (
            org_id, name, intent_key, description,
            required_parameters, trigger_patterns,
            adapter_method, otp_required, otp_threshold,
            approval_threshold, is_active
        ) VALUES ($1,$2,$3,$4,$5::jsonb,'[]'::jsonb,$6,$7,$8,$9,true)
        RETURNING id
        """,
        org_id,
        body.get("name"),
        body.get("intent_key"),
        body.get("description"),
        json.dumps(body.get("required_parameters", {})),
        adapter_method,
        body.get("otp_required", False),
        body.get("otp_threshold"),
        body.get("approval_threshold"),
    )
    workflow_id = str(new_wf["id"])

    # Embed and store utterances
    intent_key = body.get("intent_key")
    stored = 0
    if utterances:
        stored = await _embed_and_store_utterances(
            workflow_id, org_id, intent_key, utterances
        )

    # Add permissions to selected roles
    selected_roles = body.get("roles", ["owner"])
    for role_name in selected_roles:
        await execute(
            """
            UPDATE roles
            SET permissions = array_append(permissions, $1)
            WHERE name = $2 AND org_id = $3 AND NOT $1 = ANY(permissions)
            """,
            intent_key, role_name, org_id,
        )

    # Invalidate classifier cache (no-op in new system, kept for compat)
    invalidate_patterns_cache(org_id)

    return {
        "success": True,
        "message": (
            f"Workflow saved. {stored} utterances embedded and indexed. "
            f"Permission added to {len(selected_roles)} role(s)."
        ),
    }
```

### 3.4  Update admin HTML form (in `_build_html`) to show utterances

In the `workflowForm` div, add a textarea to display the generated utterances
(readonly, for review before saving):

Find the existing `wfDescription` block and add after it:
```html
<div style="margin-bottom:12px">
  <div class="stat-label">Generated Utterances (20 example phrases)</div>
  <textarea id="wfUtterances" rows="6" readonly
    style="width:100%;border:1px solid #e8edf5;border-radius:6px;padding:8px;
           font-size:12px;font-family:monospace;resize:vertical"></textarea>
  <div style="font-size:11px;color:#888;margin-top:3px">
    These will be embedded and stored — they power the semantic search
  </div>
</div>
```

And in the `generateWorkflow()` JS function, add after setting `wfDescription`:
```javascript
const utterances = config.utterances || [];
document.getElementById('wfUtterances').value = utterances.join('\n');
```

And in the `saveWorkflow()` config object, add:
```javascript
utterances: document.getElementById('wfUtterances').value
    .split('\n')
    .map(s => s.trim())
    .filter(s => s.length > 0),
```

---

## Step 4 — Migration Script: Embed All 12 Workflows

Create `scripts/embed_workflows.py` — run this ONCE after inserting the SQL above.
This embeds all utterances for every workflow and stores them in `workflow_utterances`.

```python
"""
scripts/embed_workflows.py

Run from project root:
    python -m scripts.embed_workflows

This embeds all utterances defined below and stores them in workflow_utterances.
Run once after inserting the new workflows via SQL migration.
"""
import asyncio
import asyncpg
import os
from openai import AsyncOpenAI

DATABASE_URL = os.environ["DATABASE_URL"]   # your Neon connection string
OPENAI_KEY   = os.environ["OPENAI_API_KEY"]
ORG_ID       = "11111111-0000-0000-0000-000000000001"

openai_client = AsyncOpenAI(api_key=OPENAI_KEY)


# ── DEFINE ALL UTTERANCES PER WORKFLOW ───────────────────────────────────────
# 20 diverse utterances per intent. Mix of short, long, Hindi, Hinglish, English.
WORKFLOW_UTTERANCES = {

    "check_stock": [
        "stock gold ring",
        "how many diamond bangles",
        "inventory silver chain",
        "gold ring kitna hai",
        "check stock pendant",
        "is 22kt necklace available",
        "how many gold rings do we have",
        "mangalsutra stock check",
        "bracelet available hai kya",
        "what is the stock of diamond bangle",
        "gold earrings kitni hain",
        "silver anklet quantity",
        "check inventory of 18kt pendant",
        "how much gold chain is left",
        "bangle stock batao",
        "warehouse mein ring hai kya",
        "earrings ka stock kya hai",
        "available pieces of 22kt bracelet",
        "necklace inventory Safe A2",
        "mangalsutra kitna bacha hai",
    ],

    "get_outstanding": [
        "dues Mehta",
        "Mehta outstanding",
        "Sharma ka kitna bacha hai",
        "how much Kapoor owes",
        "Patel dues",
        "Agarwal ka balance",
        "Mehta ki pending payment",
        "check dues for Sharma Gold House",
        "how much is pending from Patel",
        "Kapoor ka outstanding amount",
        "outstanding Mehta Jewellers",
        "Sharma ka pending invoice",
        "kya Mehta ne diya",
        "Kapoor ka kuch baki hai",
        "pending dues of Agarwal",
        "show me Patel outstanding",
        "Mehta ka baki kitna hai",
        "what does Sharma owe us",
        "Agarwal outstanding balance check",
        "dues for Kapoor Trading",
    ],

    "weekly_dues_report": [
        "dues report",
        "top 3 dues customers",
        "overdue report",
        "all overdue customers",
        "customer wise dues",
        "who owes the most",
        "sabse zyada kiska bacha hai",
        "top 5 outstanding",
        "give me the overdue list",
        "dues customer wise",
        "all customers outstanding",
        "show overdue summary",
        "weekly dues report",
        "kitne customers ne nahi diya",
        "sabka dues",
        "report of all pending payments",
        "which customers have dues",
        "top outstanding customers list",
        "give me top 3 dues customer wise",
        "overdue summary report",
    ],

    "create_invoice": [
        "invoice Mehta 25000",
        "bill Sharma 50000",
        "raise invoice Kapoor 75000",
        "invoice Mehta 15 gold rings 120000",
        "create invoice Patel 45000",
        "bill bana do Mehta ka 30000",
        "invoice Sharma Gold House 18kt diamond bangle 125000",
        "invoice for Kapoor 5 bangles 45000",
        "raise a bill for Agarwal 60000",
        "Mehta ka invoice 25000 gold ring",
        "generate invoice Patel 90000",
        "create bill Kapoor Trading 50000",
        "invoice Sharma 22kt necklace 185000",
        "bill nikalo Mehta 25000",
        "invoice raise karo Kapoor 75000",
        "Agarwal ka bill 45000 ki gold chain",
        "invoice 70000 Sharma",
        "patel ka 30000 ka invoice banao",
        "invoice Mehta for the gold ring 45000",
        "make invoice for Kapoor 2 bangles 50000",
    ],

    "send_invoice_pdf": [
        "send INV-1101 PDF",
        "invoice PDF INV-1102",
        "send me PDF of INV-001",
        "INV-1103 ka PDF bhejo",
        "resend invoice INV-1104",
        "PDF for invoice 1105",
        "send invoice document INV-1101",
        "INV-001 PDF chahiye",
        "can you send the invoice PDF for INV-1102",
        "invoice INV-1103 PDF send karo",
        "get me the PDF for INV-1104",
        "send invoice PDF 1105",
        "INV-1101 document send",
        "invoice copy send karo 1102",
        "email invoice INV-003",
        "send invoice 1103",
        "PDF of INV-004",
        "invoice INV-1105 resend",
        "send document for invoice 001",
        "INV-1106 bhejo",
    ],

    "send_dues_statement": [
        "dues statement Mehta",
        "send statement Sharma",
        "outstanding statement PDF Kapoor",
        "Mehta ka statement bhejo",
        "Patel outstanding statement",
        "send dues PDF for Agarwal",
        "Kapoor ka dues statement",
        "generate statement Mehta Jewellers",
        "Sharma Gold House statement",
        "outstanding PDF Patel Fine Jewellery",
        "account statement Mehta",
        "dues summary PDF Kapoor",
        "Agarwal ka baki ka statement",
        "send account summary Sharma",
        "statement of outstanding for Patel",
        "outstanding dues PDF Mehta",
        "Kapoor ka account statement bhejo",
        "Agarwal outstanding document",
        "statement for all Sharma dues",
        "Patel ka dues ka PDF chahiye",
    ],

    "create_quotation": [
        "quote Mehta 22kt 15.5g",
        "quotation Kapoor 18kt 8g",
        "price quote Sharma 22kt 12g",
        "quote Patel 22kt 20g DC-001",
        "generate quotation Mehta 18kt 10g",
        "give quote Agarwal 22kt 15g",
        "Mehta ko quote do 22kt 8 gram",
        "18kt 12g ka quote Kapoor",
        "gold ring quote Sharma 22kt 5g",
        "price quote for Patel 22kt bangle 25g",
        "quotation for 22kt 15 gram",
        "Kapoor ka quotation 18kt 10 gram",
        "Mehta Jewellers price quote 22kt",
        "gold necklace quotation 22kt 30g",
        "silver quote Agarwal 50g",
        "Patel ka quote banao 22kt 12g",
        "generate price for Sharma 18kt pendant 5g",
        "quote 22kt gold ring Mehta 7.5 grams",
        "quotation Kapoor platinum 8g",
        "price quote 14kt 10g Sharma",
    ],

    "set_metal_rate": [
        "set rate 22kt 6200",
        "update gold rate 6500",
        "22kt rate update 6300",
        "change 18kt rate to 5800",
        "set making 22kt 15",
        "update silver rate 85",
        "set gold rate 22kt 6400",
        "18kt ka rate update karo 5900",
        "22kt rate change 6100",
        "update making charges 22kt 12 percent",
        "set platinum rate 2500",
        "gold rate set 6200",
        "22kt making 15%",
        "18kt rate 5800 set karo",
        "silver making charges 10%",
        "update 22kt to 6300",
        "gold rate aaj 6250 hai",
        "set GST 3",
        "making charge 22kt update 14%",
        "rate update 18kt 5700",
    ],

    "create_order": [
        "new order Mehta 22kt gold ring",
        "book order Kapoor diamond bangle",
        "create order Sharma gold necklace",
        "place order Patel 22kt bracelet",
        "new order Agarwal 18kt pendant",
        "production order Mehta mangalsutra 22kt",
        "Kapoor ka order daal do gold bangle",
        "Sharma new order 22kt chain",
        "order create karo Patel gold ring",
        "Agarwal ka production order diamond pendant",
        "book production Mehta 22kt necklace",
        "new jewellery order Kapoor Trading",
        "order Sharma Gold House 22kt bangle",
        "Mehta ka naya order 18kt earrings",
        "Patel ka order 22kt gold ring 15g",
        "create manufacturing order Agarwal",
        "production start Mehta mangalsutra",
        "order dalo Kapoor 22kt ring",
        "new order Sharma bangle 22kt",
        "book order for Mehta 22kt necklace",
    ],

    "update_order_status": [
        "update ORD-1001 ready",
        "mark ORD-1002 delivered",
        "ORD-1003 in production",
        "set ORD-1004 quality check",
        "ORD-1001 done",
        "mark order 1002 as ready",
        "ORD-1003 delivered hai",
        "update 1004 to production",
        "order ORD-1001 status change delivered",
        "ORD-1002 QC",
        "mark ORD-1003 complete",
        "order 1004 ready karo",
        "ORD-1001 production mein hai",
        "set order 1002 as delivered",
        "order status update ORD-1003 ready",
        "ORD-1004 quality check mein daalo",
        "delivered ORD-1001",
        "ORD-1002 making",
        "order 1003 ab ready hai",
        "ORD-1004 ko delivered mark karo",
    ],

    "get_orders": [
        "show active orders",
        "all active orders",
        "pending orders",
        "orders list",
        "current orders",
        "view orders in progress",
        "active order list",
        "kaun kaun se orders hain",
        "orders status",
        "production orders",
        "show all orders",
        "ready orders",
        "orders ready for delivery",
        "delivered orders",
        "recent orders",
        "order list dikhao",
        "active production orders",
        "kya kya orders hain",
        "orders pending",
        "all orders summary",
    ],

    "get_credit_limit": [
        "credit limit Mehta",
        "Sharma ka credit",
        "how much credit Kapoor has",
        "Patel credit check",
        "Agarwal credit limit",
        "Mehta ki credit limit kya hai",
        "check credit for Sharma",
        "what is Kapoor's credit limit",
        "Patel ka credit",
        "credit limit Agarwal Ornaments",
        "Sharma Gold House credit",
        "Mehta Jewellers credit limit check",
        "kitna credit hai Kapoor ka",
        "credit status Patel",
        "show Agarwal credit limit",
        "what credit does Mehta have",
        "Sharma ka credit limit batao",
        "is Kapoor's credit limit exceeded",
        "credit available for Patel",
        "Mehta credit balance",
    ],
}


async def embed_and_store(pool: asyncpg.Pool, org_id: str) -> None:
    print(f"\n{'='*60}")
    print(f"Starting utterance embedding for org: {org_id}")
    print(f"{'='*60}")

    async with pool.acquire() as conn:
        for intent_key, utterances in WORKFLOW_UTTERANCES.items():
            # Get workflow_id
            wf_row = await conn.fetchrow(
                "SELECT id FROM workflows WHERE intent_key = $1 AND org_id = $2",
                intent_key, org_id,
            )
            if not wf_row:
                print(f"  ⚠️  Workflow '{intent_key}' not found in DB — skipping")
                continue

            workflow_id = str(wf_row["id"])

            # Delete any existing utterances for this workflow
            await conn.execute(
                "DELETE FROM workflow_utterances WHERE workflow_id = $1", workflow_id
            )

            print(f"\n  ↪ Embedding {len(utterances)} utterances for: {intent_key}")

            # Batch embed (max 100 at a time per OpenAI limits)
            batch_size = 50
            total_stored = 0
            for batch_start in range(0, len(utterances), batch_size):
                batch = utterances[batch_start:batch_start + batch_size]

                resp = await openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch,
                )

                for i, emb_obj in enumerate(resp.data):
                    utterance = batch[i]
                    embedding  = emb_obj.embedding
                    vec_str    = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

                    await conn.execute(
                        """
                        INSERT INTO workflow_utterances
                            (org_id, workflow_id, intent_key, utterance, embedding)
                        VALUES ($1, $2, $3, $4, $5::vector)
                        """,
                        org_id, workflow_id, intent_key, utterance, vec_str,
                    )
                    total_stored += 1

            # Update utterance_count
            await conn.execute(
                "UPDATE workflows SET utterance_count = $1 WHERE id = $2",
                total_stored, workflow_id,
            )
            print(f"    ✅ Stored {total_stored} utterances")

    print(f"\n{'='*60}")
    print(f"Done! All utterances embedded and indexed.")
    print(f"{'='*60}\n")


async def main():
    pool = await asyncpg.create_pool(DATABASE_URL)
    try:
        await embed_and_store(pool, ORG_ID)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Run it:**
```bash
DATABASE_URL="postgresql://user:pass@host/db" \
OPENAI_API_KEY="sk-..." \
python -m scripts.embed_workflows
```

Expected output: ~240 utterances embedded, takes ~10 seconds, costs < $0.01.

---

## Step 5 — Verify the Migration

Run in Neon SQL editor after the Python script finishes:

```sql
-- Check utterance counts per workflow
SELECT w.intent_key, w.utterance_count,
       COUNT(wu.id) AS actual_count
FROM workflows w
LEFT JOIN workflow_utterances wu ON wu.workflow_id = w.id
WHERE w.org_id = '11111111-0000-0000-0000-000000000001'
GROUP BY w.intent_key, w.utterance_count
ORDER BY w.intent_key;
-- Expected: 12 rows, each with utterance_count = 20, actual_count = 20

-- Quick similarity test — should return weekly_dues_report as top hit
-- (Run from Python or via a quick test script, not from SQL console)
```

---

## Step 6 — New Workflow Ideas to Add Later (via admin panel)

Once the base system works, these can be created via the AI Workflow Builder:

| Workflow description to type in admin | Intent key | Adapter |
|---------------------------------------|-----------|---------|
| "List all inventory items below reorder level" | `low_stock_alert` | Add to inventory adapter |
| "Show all pending invoices across all customers" | `all_pending_invoices` | Add to accounting adapter |
| "Check status of a specific order by ORD number" | already covered by get_orders | — |
| "Show quotations sent this month" | `list_quotations` | Add to quotation adapter |
| "Get all paid invoices for a customer" | `paid_invoices` | Add to accounting adapter |
| "Mark invoice as paid" | `mark_invoice_paid` | Add to accounting adapter |

Each one created through the admin panel will now automatically get 20 embedded utterances
and work in Hindi, English, and Hinglish without any code changes.

---

## Step 7 — Test Queries After Migration

Run all of these via WhatsApp. Verify correct intent + correct response.

### 7.1 — Queries that FAILED before (must all work now)

| Query | Expected intent | Expected behaviour |
|---|---|---|
| `Give me the top 3 dues customer wise` | `weekly_dues_report` | Shows top 3 overdue |
| `Top 3 outstanding customers` | `weekly_dues_report` | Shows top 3 overdue |
| `Who owes the most` | `weekly_dues_report` | Shows all overdue sorted |
| `Sabse zyada kiska bacha hai` | `weekly_dues_report` | Shows all overdue |
| `All customers dues report` | `weekly_dues_report` | Full report |
| `Overdue list dikhao` | `weekly_dues_report` | Full report |

### 7.2 — Specific customer queries (entity extraction)

| Query | Expected intent | Expected entity |
|---|---|---|
| `dues Mehta` | `get_outstanding` | Mehta |
| `Mehta ka kitna bacha hai` | `get_outstanding` | Mehta |
| `Sharma outstanding` | `get_outstanding` | Sharma |
| `How much does Kapoor owe` | `get_outstanding` | Kapoor |
| `Patel ka balance batao` | `get_outstanding` | Patel |
| `Check credit Mehta` | `get_credit_limit` | Mehta |
| `Sharma ka credit kya hai` | `get_credit_limit` | Sharma |

### 7.3 — Inventory queries

| Query | Expected intent | Notes |
|---|---|---|
| `stock gold ring` | `check_stock` | Returns 22kt Gold Ring qty |
| `diamond bangle available hai kya` | `check_stock` | Returns 18kt Diamond Bangle |
| `how many mangalsutra` | `check_stock` | Below reorder level warning |
| `inventory silver anklet` | `check_stock` | Returns Silver Anklet |

### 7.4 — Invoice creation

| Query | Expected intent | Notes |
|---|---|---|
| `invoice Mehta 25000` | `create_invoice` | Creates INV-1100+ |
| `bill Sharma 50000` | `create_invoice` | Creates invoice |
| `invoice Mehta 15 gold rings 120000` | `create_invoice` | With stock deduction |

### 7.5 — Orders

| Query | Expected intent | Notes |
|---|---|---|
| `show active orders` | `get_orders` | Lists all confirmed/in-prod etc. |
| `active orders list karo` | `get_orders` | Same in Hinglish |
| `new order Mehta 22kt gold ring` | `create_order` | Creates ORD-1001+ |
| `update ORD-1001 ready` | `update_order_status` | Status updated |
| `ORD-1001 delivered` | `update_order_status` | Delivered + celebration msg |

### 7.6 — Quotations and rates

| Query | Expected intent | Notes |
|---|---|---|
| `quote Mehta 22kt 15.5g` | `create_quotation` | PDF sent |
| `18kt rate update 5800` | `set_metal_rate` | Rate updated |
| `set GST 3` | `set_metal_rate` | GST updated |
| `22kt ka rate kya hai` | `set_metal_rate` | (LLM correctly routes to rate query) |

### 7.7 — System queries (tier 1 + tier 2a)

| Query | Expected tier | Notes |
|---|---|---|
| `hi` | Tier 1 | Greeting message |
| `help` | Tier 1 | Menu |
| `1` | Tier 1 | Approve action |
| `schedule dues report every Monday 9 AM` | Tier 2a | Schedule set |
| `stop schedule` | Tier 2a | Schedule paused |
| `clear sessions` | Tier 2a | Emergency lockdown |

### 7.8 — Edge cases + disambiguation

| Query | Expected behaviour |
|---|---|
| `Mehta` alone | get_outstanding with entity=Mehta OR disambiguation |
| `statement` alone | Should ask "Which customer?" |
| `invoice` alone | Should ask "Which customer and amount?" |
| `give me the dues` | Should route to weekly_dues_report (no entity) via sibling |
| `Mehta ka kuch baki hai kya` | get_outstanding, entity=Mehta |
| `top 5 dues` | weekly_dues_report, no entity |

---

## Step 8 — install dependency

```bash
pip install openai asyncpg --break-system-packages
# pgvector is already available in Neon — no install needed server-side
# openai SDK already present from existing usage
```

The embedding call is:
- Model: `text-embedding-3-small`
- Cost: $0.02 / 1M tokens ≈ $0.00002 per WhatsApp message
- Latency: ~50–100ms per classification
- No caching needed — pgvector HNSW index handles fast retrieval

---

## Summary of File Changes

| File | Change |
|------|--------|
| `app/classifier/classifier.py` | **Complete replacement** |
| `app/api/admin.py` | `generate_workflow_config` prompt + `save_generated_workflow` + new `_embed_and_store_utterances` helper |
| `app/executor/workflow_executor.py` | **No change needed** |
| `app/services/webhook.py` | **No change needed** |
| `scripts/embed_workflows.py` | **New file** — run once for migration |
| Neon DB | pgvector extension + `workflow_utterances` table + 2 columns on `workflows` |

The rest of the codebase (adapters, PDF service, OTP, WhatsApp sender, scheduler) is untouched.
