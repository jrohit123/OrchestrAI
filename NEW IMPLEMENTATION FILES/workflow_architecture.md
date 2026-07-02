# OrchestrAI — Workflow Architecture & Test Definitions

## Current State (Honest Assessment)

### What Works DB-Driven Today
- `entity_schema` — required fields per workflow, validated every turn
- `llm_system_prompt` — per-workflow LLM instructions injected into system prompt
- `business_glossary` — injected into system prompt
- `sql_template` + `sql_params_order` — read workflows execute 100% from DB
- `otp_threshold` / `approval_threshold` — thresholds loaded from DB
- `pdf_config` — **stored but NOT consumed** (gap 1)
- `adapter_method` — **stored but NOT called** (gap 2)

### What Is Hardcoded (The Problem)
1. `action_executor.py` — full if/elif switch on `intent_key`
   Only `create_sales_invoice` and `generate_price_quotation` work.
   Any new action workflow created via admin panel does nothing.

2. `pdf_engine.py` — 5 hardcoded doc_type branches as Python f-strings.
   `pdf_config` from DB is completely ignored.

### Architecture Gap Summary
```
WhatsApp → agent (LLM slot-filling) → "yes" → execute_pending_action
                                                        ↓
                                        if intent_key == "create_sales_invoice":  ← HARDCODED
                                            _create_invoice(...)
                                        elif intent_key == "generate_price_quotation":  ← HARDCODED
                                            _create_quotation(...)
                                        # Any new workflow → silent failure
```

---

## Target Architecture (Nothing Hardcoded)

### Three Layers

```
Layer 1: Intent & Slot-Filling  [ALREADY WORKS]
  LLM reads entity_schema, llm_system_prompt, business_glossary from DB
  Calls update_draft → confirm_action
  _validate_draft checks entity_schema for completeness

Layer 2: Execution Kernel  [NEEDS FIXING]
  Reads adapter_method + execution_config from workflows table
  Dynamically dispatches to the correct handler
  No hardcoding — any workflow in DB gets executed

Layer 3: Document Generation  [NEEDS FIXING]
  Reads pdf_config from workflows table
  Builds PDF prompt using config values, not hardcoded f-strings
```

### What Needs to Change

**1. `execution_config` column on workflows table**
Add a JSONB column that describes the DB operation:
```json
{
  "operation": "insert",
  "table": "invoices",
  "field_mapping": {
    "org_id": "__org_id__",
    "customer_id": "__resolve_customer__",
    "items": "fields.items",
    "amount": "__sum_items_total__",
    "status": "pending",
    "due_date": "__today_plus_30__"
  },
  "number_sequence": {
    "table": "invoices",
    "column": "invoice_number",
    "prefix": "INV-",
    "start": 100
  },
  "post_actions": ["generate_pdf", "send_whatsapp"]
}
```

**2. Generic `_execute_action` in action_executor.py**
```python
async def _execute_action_generic(intent_key, fields, user, execution_config, pdf_config):
    operation = execution_config.get("operation")  # insert / update / upsert
    table = execution_config.get("table")
    field_mapping = execution_config.get("field_mapping", {})
    
    # Resolve special values
    resolved = {}
    for col, source in field_mapping.items():
        if source == "__org_id__":
            resolved[col] = user["org_id"]
        elif source == "__resolve_customer__":
            resolved[col] = await _resolve_customer_id(fields, user["org_id"])
        elif source.startswith("fields."):
            field_key = source[7:]
            resolved[col] = fields.get(field_key)
        else:
            resolved[col] = source  # literal value
    
    # Generate document number
    if execution_config.get("number_sequence"):
        seq = execution_config["number_sequence"]
        count_row = await fetch_one(f"SELECT COUNT(*) as cnt FROM {seq['table']} WHERE org_id = $1", user["org_id"])
        doc_number = f"{seq['prefix']}{seq['start'] + int(count_row['cnt'])}"
        resolved[seq["column"]] = doc_number
    
    # Execute DB operation
    cols = list(resolved.keys())
    vals = list(resolved.values())
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    await execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", *vals)
    
    # Post-actions
    if "generate_pdf" in execution_config.get("post_actions", []):
        # generate PDF using pdf_config from workflow
        pass
    
    return {"success": True, "doc_number": doc_number}
```

**3. pdf_config consumed by pdf_engine.py**
Instead of hardcoded f-strings, read from DB:
```json
{
  "doc_type": "invoice",
  "title_template": "Tax Invoice — {invoice_number}",
  "sections": ["header", "customer_info", "items_table", "totals", "footer"],
  "items_columns": ["description", "qty", "unit_price", "gst", "total"],
  "show_gstin": true,
  "show_due_date": true,
  "footer_text": "Thank you for your business",
  "color_scheme": "blue"
}
```

---

## Test Workflow Definitions

### Workflow 1: Create Sales Invoice

```json
{
  "intent_key": "create_sales_invoice",
  "name": "Create Sales Invoice",
  "description": "Creates a GST tax invoice for a customer and generates a PDF",
  "workflow_type": "action",
  "is_active": true,
  "otp_threshold": 100000,
  "approval_threshold": 500000,

  "training_phrases": [
    "invoice banao {customer_name}",
    "{customer_name} {amount} invoice",
    "bill banao {customer_name}",
    "create invoice {customer_name}",
    "GST invoice {customer_name}",
    "{customer_name} ka invoice",
    "invoice {customer_name} {amount} rupees",
    "bill {customer_name}",
    "{customer_name} invoice {item}",
    "billo {customer_name}",
    "make invoice for {customer_name}"
  ],

  "entity_schema": {
    "customer_name": {
      "type": "string",
      "required": true,
      "table": "customers",
      "column": "name",
      "match": "ILIKE",
      "format": "wildcard"
    },
    "items": {
      "type": "array",
      "required": true,
      "description": "Line items: [{description, qty, unit_price, gst, total}]"
    }
  },

  "business_glossary": {
    "invoice": "create_sales_invoice",
    "bill": "create_sales_invoice",
    "billing": "create_sales_invoice",
    "GST invoice": "create_sales_invoice",
    "tax invoice": "create_sales_invoice",
    "invoice banao": "create sales invoice",
    "bill banao": "create sales invoice",
    "receipt": "create_sales_invoice"
  },

  "llm_system_prompt": "Create a GST tax invoice for a jewellery business.\n\nREQUIRED FIELDS:\n  customer_name (string): Who the invoice is for. Resolve via customers table.\n  items (array): Line items the user specifies. Each item needs:\n    - description: what the item is (e.g. '22kt gold chain 60g')\n    - qty: integer (default 1)\n    - unit_price: float (GST-exclusive price)\n    - gst: float (GST amount = unit_price × qty × gst_rate%)\n    - total: float (unit_price × qty + gst)\n\nGST CALCULATION:\n  Fetch gst_rate from orgs table: SELECT gst_rate FROM orgs WHERE id = $1\n  unit_price = user-provided price (ex-GST)\n  gst = unit_price × qty × gst_rate / 100\n  total = unit_price × qty + gst\n  If user provides an all-inclusive total T:\n    unit_price = T / (1 + gst_rate/100) / qty\n    gst = T - unit_price × qty\n\nDO NOT:\n  - Invent customer names\n  - Query inventory for prices (user provides them)\n  - Call generate_pdf directly (system handles PDF after confirmation)\n\nEXAMPLES:\n  'Singh Bullion Mart 92000 invoice' → customer=Singh Bullion Mart, amount=92000\n  'Mehta Enterprises invoice 22kt chain 60g Rs.45000' → customer=Mehta, item=22kt chain\n  'invoice banao Jain Gold Works' → ask for items and amount",

  "sql_template": null,
  "sql_params_order": [],
  "response_format": "invoices",

  "pdf_config": {
    "doc_type": "invoice",
    "title_template": "Tax Invoice — {invoice_number}",
    "subtitle_template": "Customer: {customer_name}",
    "sections": ["org_header", "invoice_meta", "customer_block", "items_table", "totals_block", "payment_footer"],
    "items_columns": [
      {"key": "description", "label": "Description", "width": "45%"},
      {"key": "qty", "label": "Qty", "width": "10%", "align": "center"},
      {"key": "unit_price", "label": "Unit Price (ex-GST)", "width": "20%", "align": "right", "format": "inr"},
      {"key": "gst", "label": "GST (3%)", "width": "12%", "align": "right", "format": "inr"},
      {"key": "total", "label": "Total", "width": "13%", "align": "right", "format": "inr"}
    ],
    "totals": [
      {"label": "Subtotal (ex-GST)", "source": "sum_unit_price_x_qty"},
      {"label": "GST @3%", "source": "sum_gst"},
      {"label": "TOTAL", "source": "sum_total", "bold": true, "large": true}
    ],
    "show_gstin": true,
    "show_due_date": true,
    "show_status_badge": true,
    "footer_text": "Payment due within 30 days. Thank you for your business.",
    "legal_note": "This is a computer-generated Tax Invoice.",
    "color_scheme": "blue"
  }
}
```

---

### Workflow 2: Generate Price Quotation

```json
{
  "intent_key": "generate_price_quotation",
  "name": "Generate Price Quotation",
  "description": "Generates a price quotation PDF for a customer with custom pricing",
  "workflow_type": "action",
  "is_active": true,
  "otp_threshold": 9999999,
  "approval_threshold": 9999999,

  "training_phrases": [
    "quote {customer_name}",
    "quotation {customer_name}",
    "quote banao {customer_name}",
    "price quote {customer_name}",
    "estimate {customer_name}",
    "{customer_name} ka quote",
    "quote for {customer_name}",
    "price estimate {customer_name}",
    "kitne ka padega {item}",
    "quote {customer_name} {item} {weight}g",
    "quotation chahiye {customer_name}",
    "price batao {customer_name} {item}"
  ],

  "entity_schema": {
    "customer_name": {
      "type": "string",
      "required": true,
      "table": "customers",
      "column": "name",
      "match": "ILIKE",
      "format": "wildcard"
    },
    "items": {
      "type": "array",
      "required": true,
      "description": "Line items: [{description, design_code, design_name, metal_type, weight, qty, unit_price, making_charges, gst, total}]"
    }
  },

  "business_glossary": {
    "quote": "generate_price_quotation",
    "quotation": "generate_price_quotation",
    "estimate": "generate_price_quotation",
    "price quote": "generate_price_quotation",
    "quote banao": "generate price quotation",
    "kitne ka padega": "price estimate / quotation",
    "price batao": "price quotation"
  },

  "llm_system_prompt": "Generate a price quotation for a jewellery business.\n\nREQUIRED FIELDS:\n  customer_name (string): Who the quote is for.\n  items (array): Items the user wants quoted. Each item:\n    - description: item name (e.g. '22kt gold chain 60g')\n    - design_code: optional SKU code (e.g. 'GC-22K-001')\n    - design_name: optional design name\n    - metal_type: optional (e.g. '22kt', 'Platinum')\n    - weight: optional float (grams)\n    - qty: integer (default 1)\n    - unit_price: float (metal cost component, ex-making, ex-GST)\n    - making_charges: float (optional, if user specifies)\n    - gst: float (3% of unit_price×qty + making_charges)\n    - total: float (unit_price×qty + making_charges + gst)\n\nPRICING RULES:\n  There is NO pricing table. User provides all rates.\n  'at 45000 per gram, 25g' → unit_price = 45000 × 25 = 11,25,000\n  'Rs.55000 total, 1 piece' → unit_price = 55000 (treat as all-inclusive subtotal)\n  making_charges: user-specified flat amount or percentage\n  gst = (unit_price × qty + making_charges) × 3%\n\nDO NOT:\n  - Query inventory or pricing table for rates\n  - Invent prices or design codes\n  - Call generate_pdf directly (system handles it after confirmation)\n\nEXAMPLES:\n  'quote Jain Gold Works 22kt chain 60g at 7000/g' → unit_price=7000×60=4,20,000\n  'quote Mehta platinum necklace 25g at 45000/g making 5000' → unit_price=45000×25=11,25,000, making=5000\n  'quote Singh 18kt ring 8g 55000 total making 3000' → unit_price=55000, making=3000\n\nCONFIRMATION:\n  MUST use confirm_action tool — NEVER print ⚠️ block as plain text.",

  "sql_template": null,
  "sql_params_order": [],
  "response_format": "quotations",

  "pdf_config": {
    "doc_type": "quotation",
    "title_template": "Price Quotation — {quotation_number}",
    "subtitle_template": "Customer: {customer_name}",
    "sections": ["org_header", "quotation_meta", "customer_block", "design_details", "pricing_breakdown", "items_table", "totals_block", "validity_footer"],
    "design_details_fields": [
      {"key": "design_code", "label": "Design Code"},
      {"key": "design_name", "label": "Design Name"},
      {"key": "metal_type", "label": "Metal Type"},
      {"key": "weight_grams", "label": "Weight"}
    ],
    "pricing_breakdown_rows": [
      {"label": "Metal Cost", "source": "metal_cost", "format": "inr"},
      {"label": "Making Charges", "source": "making_charges", "format": "inr", "note": "({making_charge_pct}% of metal cost)"},
      {"label": "Subtotal", "source": "subtotal", "format": "inr"},
      {"label": "GST (3%)", "source": "gst_amount", "format": "inr"},
      {"label": "TOTAL AMOUNT", "source": "total_amount", "format": "inr", "bold": true, "large": true}
    ],
    "validity_days": 3,
    "footer_text": "This quotation is valid for 3 days from date of issue. Gold rates are subject to market fluctuation.",
    "legal_notes": [
      "Advance payment required to confirm order.",
      "Final weight may vary ±5% from estimate.",
      "Making charges are fixed at time of confirmation.",
      "GST as per prevailing government rates."
    ],
    "show_signature_block": true,
    "color_scheme": "gold"
  }
}
```

---

## Test Messages

### Invoice Tests

**Single-message, all info:**
```
Singh Bullion Mart invoice: 22kt gold chain 60g 1 piece, Rs.45000 total
```

**Multi-turn:**
```
create invoice
```
→ Bot asks: who is the customer?
```
Mehta Enterprises
```
→ Bot asks: what items?
```
18kt diamond pendant 10g 1 piece, Rs.73000 total
```
→ Confirmation block → `yes` → Invoice created + PDF sent

**Correction before confirm:**
```
Jain Gold Works invoice: platinum bracelet 20g 1 piece Rs.95000
```
→ Confirmation shows
```
actually Rs.98000
```
→ Updated confirmation → `yes`

**Amount in lakhs (Hinglish):**
```
Mehta Enterprises 1.5 lakh ka invoice banao, 22kt necklace 35g 1 piece
```

---

### Quotation Tests

**Single-message, all info:**
```
quote Mehta Enterprises: platinum necklace 25g 1 pc at 45000 per gram, making charges 5000, design code PT-NECK-001, design name Platinum Necklace, metal type Platinum
```

**Multi-turn:**
```
create quotation for Singh Bullion Mart
```
→ Bot asks for item details
```
22kt gold bangle 30g, 2 pieces, Rs.7500 per gram, making charges 12000, design code GB-22K-002, design name Gold Bangle Traditional
```
→ Confirmation → `yes`

**Correction before confirm:**
```
quote Jain Gold Works: 18kt diamond ring 8g 1 pc at 55000 total, making charges 3000
```
→ Confirmation shows
```
actually making charges are 4500
```
→ Updated confirmation → `yes`

**Without design code (bare minimum):**
```
quote Sharma Ornaments: silver anklet 50g at 800 per gram, making charges 2000
```

---

## What To Build Next (Priority Order)

### Priority 1 — Generic Execution Kernel
Replace the if/elif in action_executor.py with DB-driven dispatch.
Add `execution_config` JSONB column to workflows.
Estimated effort: 1-2 days. Unblocks all future action workflows.

### Priority 2 — pdf_config consumed by pdf_engine.py
Have pdf_engine.py read `pdf_config` from the workflow record.
Build PDF prompt dynamically from config rather than hardcoded f-strings.
Estimated effort: 1 day. Makes PDF formatting customisable per workflow.

### Priority 3 — QA Agent / Validation Layer
A validation pass between slot-filling and confirmation:
- Check calculations are correct (GST = amount × rate, totals add up)
- Check customer exists in DB
- Check no invented data
Currently this happens partially via _validate_draft. A dedicated QA step would re-verify all numbers before showing the confirmation block.
Estimated effort: 1 day. Reduces confirmation errors.

### Priority 4 — Admin Panel Workflow Builder improvements
Connect the AI-generated workflow JSON (which already works for reads) to
include execution_config and pdf_config generation as well.
Estimated effort: 0.5 days after Priority 1 and 2 are done.
