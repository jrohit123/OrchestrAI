# What Workflows Are For, What the Agent Handles, and Where PDF Fits

---

## Read This First — The Three Layers

Your system has three completely separate layers.
Every confusion you have comes from mixing them up.

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — THE AGENT  (agent.py)                           │
│                                                             │
│  The brain. Understands any message in any language.        │
│  Decides what to do. Calls tools. Formats responses.        │
│  Has ZERO domain knowledge of its own — reads everything    │
│  from the DB at runtime.                                    │
└─────────────────────────────────────────────────────────────┘
         ↓ calls tools ↓                ↓ calls tools ↓
┌──────────────────────┐    ┌────────────────────────────────┐
│  LAYER 2 — WORKFLOWS │    │  LAYER 2 — WORKFLOWS           │
│  (READ type)         │    │  (ACTION type)                 │
│                      │    │                                │
│  Verified SQL        │    │  Business capabilities.        │
│  patterns. Guides    │    │  Each one says: "to do X,      │
│  agent toward        │    │  call adapter Y, with params   │
│  correct queries.    │    │  Z, OTP if amount > N."        │
│  Admin configures.   │    │  Admin configures.             │
└──────────────────────┘    └────────────────────────────────┘
                                        ↓ importlib ↓
                            ┌────────────────────────────────┐
                            │  LAYER 3 — ADAPTERS            │
                            │  (accounting.py, orders.py,    │
                            │   quotation.py, crm.py)        │
                            │                                │
                            │  Execute actual business       │
                            │  logic. Validate data.         │
                            │  Write to DB. Call pdf_engine. │
                            └────────────────────────────────┘
                                        ↓ always ↓
                            ┌────────────────────────────────┐
                            │  PDF ENGINE  (pdf_engine.py)   │
                            │                                │
                            │  Universal renderer.           │
                            │  Called by BOTH the agent      │
                            │  (for query PDFs) and by       │
                            │  adapters (for formal docs).   │
                            │  LLM → HTML → xhtml2pdf.      │
                            └────────────────────────────────┘
```

---

## The Single Clearest Way to Think About It

**Agent = what the user WANTS to know**
**Workflow = what the system KNOWS HOW to do**
**PDF engine = how results LOOK when printed**

These are three different questions. They are not the same thing.

---

## Part 1 — What the Agent Handles Without Any Workflow

These work on day one, with zero workflow records in the DB,
for any industry, for any schema:

### Any read question about data

```
"show me all overdue invoices"
"top 5 customers by outstanding"
"Mehta ka baaki kitna hai"
"which orders are in production"
"low stock items kya hain"
"customers in Mumbai with credit limit above 3 lakh"
"show me all invoices from last month"
"which Sharma has the highest dues"
"all 22kt gold items in inventory"
```

The agent reads `information_schema`, understands your tables,
writes fresh SQL, executes it, formats the response.
No workflow needed. No admin configuration needed.
Works for jewellery today, pharma tomorrow — same code.

### Any PDF of query results

```
"give me all overdue invoices as PDF"
"Sharma aur Agarwal ka invoice summary PDF mein do"
"top 10 customers by outstanding as PDF"
"ready orders ka PDF bana do"
"low stock report PDF"
"all customers with their credit limits as PDF"
```

Agent queries DB → gets rows → calls `pdf_engine.generate_pdf(rows, title)`
No workflow needed. PDF engine figures out the layout from the data.

### Identity and permissions

```
"who am I"
"what are my permissions"
"what can I ask"
```

Answered from system prompt. No DB query. No workflow.

### Disambiguation

```
"Mehta ka outstanding" (when 4 Mehtas exist)
```

Agent queries customers WHERE name ILIKE '%Mehta%', gets 4 rows,
calls clarify tool, presents options. No workflow.

---

## Part 2 — What Workflows Are For

Workflows define CAPABILITIES — operations your system can perform
that involve business logic beyond just reading data.

The admin panel workflow builder exists to let you add, configure,
and control these capabilities WITHOUT touching code.

### The single test to decide if something needs a workflow

**Ask yourself: "Does this operation write to the database,
call an external service, generate a formal document,
or need OTP/approval gates?"**

If YES → it needs a workflow record.
If NO → the agent handles it directly.

---

## Part 3 — Types of Workflows With Real Examples

### Type A — Action workflows with a known adapter

These call an existing function in your adapters folder.
The workflow record tells the agent: "this capability exists,
here's what it does, here's what params it needs, here's the
function to call."

---

**Example 1: Create Invoice**

Admin adds this workflow from the panel:

```
Name: Create Invoice
Intent key: create_invoice
Type: action
Description: Create a sales invoice for a customer and send PDF via WhatsApp
Adapter method: accounting.create_invoice
Entity schema:
  - customer_name (required, ILIKE search on customers.name)
  - amount (required, float)
  - item_name (optional, string)
  - qty (optional, integer)
OTP required: YES
OTP threshold: 50000
Approval threshold: 100000
Training phrases:
  - "invoice {customer_name} {amount}"
  - "bill karo {customer_name} {amount}"
  - "raise invoice for {customer_name}"
  - "create invoice {customer_name} {amount} for {item_name}"
```

What happens when user says *"invoice Mehta 45000"*:

```
1. Agent sees "invoice" + amount → recognises create_invoice tool
2. Checks OTP threshold: 45000 < 50000 → no OTP needed
3. Calls confirm_action: "Create invoice for Mehta Jewellers — ₹45,000"
4. User says yes
5. importlib calls accounting.create_invoice(customer_name="Mehta", amount=45000)
6. accounting.py validates customer, inserts to invoices table
7. accounting.py calls pdf_engine.generate_pdf(rows=[invoice_data], doc_type="invoice")
8. PDF sent to WhatsApp
```

What happens when user says *"invoice Mehta 150000"*:

```
1. Agent recognises create_invoice tool
2. Checks thresholds: 150000 > 100000 → approval required
3. Agent responds: "This invoice needs Owner approval. Request sent."
4. Owner gets WhatsApp buttons: Approve / Reject
5. On approval → same flow as above
```

---

**Example 2: Create Quotation**

```
Name: Create Quotation
Intent key: create_quotation
Type: action
Description: Generate a price quotation PDF for a customer based on metal type and weight
Adapter method: quotation.create_quotation
Entity schema:
  - customer_name (required)
  - metal_type (required, string — e.g. "22kt", "18kt", "silver")
  - weight_grams (required, float)
  - design_code (optional, string)
OTP required: NO
Training phrases:
  - "quote {customer_name} {metal_type} {weight_grams}g"
  - "{customer_name} ke liye quote banao"
  - "quotation for {customer_name} {metal_type}"
```

What happens when user says *"quote Sharma 22kt 15g"*:

```
1. Agent recognises create_quotation tool
2. Calls confirm_action: "Generate 22kt quotation for Sharma Gold House, 15g"
3. User says yes
4. importlib calls quotation.create_quotation(customer_name="Sharma", metal_type="22kt", weight_grams=15)
5. quotation.py fetches current 22kt rate from pricing table (6200/g)
6. quotation.py calculates: metal cost + making charges + GST
7. quotation.py calls pdf_engine.generate_pdf(extra_context={all calculation details}, doc_type="quotation")
8. Professional quotation PDF sent with full price breakdown
```

---

**Example 3: Update Order Status**

```
Name: Update Order Status
Intent key: update_order_status
Type: action
Description: Move a production order to a new status stage
Adapter method: orders.update_order_status
Entity schema:
  - order_number (required, exact match on orders.order_number)
  - new_status_text (required, string — e.g. "in production", "ready", "delivered")
OTP required: NO
Training phrases:
  - "update {order_number} {new_status_text}"
  - "mark {order_number} as {new_status_text}"
  - "{order_number} ready hai"
  - "delivered {order_number}"
```

What happens when user says *"ORD-1006 ready hai"*:

```
1. Agent recognises update_order_status tool (training phrase matches)
2. Calls confirm_action: "Update ORD-1006 (Mehta Diamond Palace) → Ready for Delivery"
3. User says yes
4. importlib calls orders.update_order_status(order_number="ORD-1006", new_status_text="ready")
5. orders.py updates DB, appends to status_history
6. Response: "✅ ORD-1006 updated. Consider notifying customer."
```

---

**Example 4: Send Dues Statement PDF**

```
Name: Send Dues Statement
Intent key: send_dues_statement
Type: action
Description: Generate and send formal dues statement PDF for a specific customer
Adapter method: accounting.send_dues_statement
Entity schema:
  - customer_name (required)
OTP required: NO
Training phrases:
  - "dues statement {customer_name}"
  - "outstanding statement {customer_name}"
  - "send statement to {customer_name}"
  - "{customer_name} ka statement bhejo"
```

**Why does this need a workflow when a simple PDF query doesn't?**

Because this is a FORMAL document — the same type as an invoice.
The adapter fetches all overdue + pending invoices, calculates
aging buckets, adds payment terms, and generates a proper
account statement with the org's letterhead.

Compare to: *"Sharma ka overdue invoices as PDF"*
That's an informal report. Agent queries DB, calls pdf_engine directly.
No workflow. No adapter.

The difference: formal business document with calculated fields
and specific formatting → workflow + adapter + pdf_engine.
Ad-hoc data export as PDF → agent + pdf_engine directly.

---

**Example 5: Set Metal Rate**

```
Name: Set Metal Rate
Intent key: set_metal_rate
Type: action
Description: Update the rate per gram for a metal type in the pricing table
Adapter method: quotation.set_metal_rate
Entity schema:
  - metal_type (required, string)
  - rate_per_gram (required, float)
  - making_charge_pct (optional, float)
OTP required: YES (changing rates is financial)
OTP threshold: 0  ← always requires OTP, no threshold
Training phrases:
  - "set rate {metal_type} {rate_per_gram}"
  - "{metal_type} ka bhav {rate_per_gram} karo"
  - "update {metal_type} rate to {rate_per_gram}"
  - "gold rate change kar {rate_per_gram}"
```

---

### Type B — Scheduled workflows (cron jobs)

These run automatically on a schedule, not from user messages.
The admin configures them but they're not triggered by the agent.

```
Name: Weekly Dues Report
Intent key: weekly_dues_report
Type: action (but is_scheduled = true)
Adapter method: crm.get_all_overdue
Schedule: every Monday 9 AM IST
```

Admin manages this entirely from the Schedule section of the
admin panel. Already works. No changes needed here.

---

### Type C — READ workflows (verified SQL patterns)

These do NOT become callable tools. They feed into the system
prompt as reference patterns for the LLM.

```
Name: Customer Outstanding Dues
Intent key: get_outstanding
Type: read
SQL template: SELECT c.name, SUM(i.amount) AS total, COUNT(*) AS invoice_count
              FROM invoices i JOIN customers c ON c.id = i.customer_id
              WHERE i.org_id = $1 AND c.name ILIKE $2
              AND i.status IN ('pending','overdue')
              GROUP BY c.name ORDER BY total DESC
SQL params: [customer_name]
Business glossary: {"baaki": "outstanding", "udhaar": "unpaid", "dues": "pending+overdue invoices"}
Training phrases: ["{customer_name} ka baaki", "dues {customer_name}", "outstanding {customer_name}"]
```

When this is saved, the agent's system prompt includes:

```
VERIFIED QUERY PATTERN [get_outstanding]:
  Purpose: Outstanding dues for a specific customer
  SQL (tested): SELECT c.name, SUM(i.amount)...
  Domain terms: baaki = outstanding, udhaar = unpaid
```

Now when someone asks "Mehta ka udhaar kitna", the LLM sees
this pattern, follows the JOIN structure, and writes correct SQL.

**When should admin add a READ workflow vs just let agent figure it out?**

Let agent figure it out for simple queries (most of them).
Add a READ workflow ONLY when:
- The SQL is complex (multi-table join with specific aggregation)
- A business term maps to a non-obvious SQL pattern
- The query is asked very frequently and you want consistency
- You tested the SQL and want to "lock in" the correct version

---

## Part 4 — Where PDF and Workflow Approach Separate

This is the exact line:

```
┌──────────────────────────────────────────────────────────────┐
│  USER ASKS FOR INFORMATION + WANTS IT AS PDF                │
│                                                              │
│  "Give me overdue invoices as PDF"                          │
│  "Top 5 customers by outstanding in PDF"                     │
│  "All ready orders as PDF"                                   │
│  "Low stock items report PDF"                                │
│                                                              │
│  Path: Agent → query_database → generate_pdf (via engine)   │
│  Workflow involved: NONE                                     │
│  Admin panel: nothing to configure                           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  USER TRIGGERS A BUSINESS OPERATION THAT PRODUCES A PDF      │
│                                                              │
│  "Invoice Mehta 45000"                                       │
│  "Quote Sharma 22kt 15g"                                     │
│  "Send dues statement to Agarwal"                            │
│                                                              │
│  Path: Agent → workflow tool → adapter → pdf_engine         │
│  Workflow involved: YES (defines the capability)             │
│  Admin panel: configures OTP threshold, approval limit       │
└──────────────────────────────────────────────────────────────┘
```

The PDF engine is called in BOTH cases. The difference is:
- First case: agent calls pdf_engine directly with raw query rows
- Second case: adapter calls pdf_engine with computed/enriched data
  (invoice number, calculated GST, customer GSTIN, payment terms, etc.)

---

## Part 5 — What Admin Should Generate From the Dashboard

### SHOULD generate (action workflows)

These are business operations your org performs regularly.
Each one needs a workflow record to exist as a callable tool.

| Admin types this description | System generates this |
|------------------------------|----------------------|
| "Create a sales invoice for a customer and send PDF" | create_invoice workflow → accounting.create_invoice |
| "Generate a price quotation based on metal type and weight" | create_quotation workflow → quotation.create_quotation |
| "Create a new production order for a customer" | create_order workflow → orders.create_order |
| "Update the status of a production order" | update_order_status workflow → orders.update_order_status |
| "Send payment reminder to a customer with overdue invoices" | send_payment_reminder workflow → crm.send_payment_reminder |
| "Send formal dues statement PDF to a customer" | send_dues_statement workflow → accounting.send_dues_statement |
| "Update the gold or silver rate per gram" | set_metal_rate workflow → quotation.set_metal_rate |
| "Mark an invoice as paid" | mark_invoice_paid workflow → accounting.mark_invoice_paid |
| "Accept a quotation and convert it to an order" | accept_quotation workflow → orders.accept_quotation |

For each of these, the admin panel generates the correct JSON config
(entity_schema, training_phrases, adapter_method, etc.) and saves it.
The agent immediately starts offering this as a callable tool.

---

### SHOULD also generate (read workflows for complex patterns)

These are for queries that are complex, frequently asked, or
where business terms need explicit mapping.

| Admin types this description | What it creates |
|------------------------------|----------------|
| "Check how much a customer owes including overdue invoices" | get_outstanding READ workflow with verified GROUP BY SQL |
| "Show aging report grouped by risk (overdue >90 days = HIGH RISK)" | aging_report READ workflow with CASE WHEN date logic |
| "Get all quotations that are still valid (not expired)" | active_quotations READ workflow with date filter |
| "Show orders by production stage for a specific customer" | customer_orders_by_stage READ workflow |

These appear in the system prompt as reference patterns.
Agent still writes fresh SQL but uses these as guidance.

---

### SHOULD NOT generate (agent handles automatically)

Do not create workflows for these. The agent handles them natively:

| Query type | Why no workflow needed |
|------------|----------------------|
| "show me all customers" | One table read, no join, no logic |
| "overdue invoices above 50000" | Simple filter, agent writes SQL |
| "top 5 customers by outstanding" | Standard aggregation, agent knows GROUP BY |
| "Mehta ka baaki" | Agent understands "baaki" from LLM training |
| "low stock items" | Agent sees qty <= reorder_level in schema sample |
| "orders in production" | Agent sees status column values in sample rows |
| "any PDF of query results" | Agent → query → pdf_engine, no workflow |
| "who am I" | Answered from system prompt |
| "all invoices from last month" | Date filter, agent writes SQL |
| "customers in Mumbai" | Simple WHERE filter |

Creating workflows for these would be redundant — they work
without any configuration and adding a workflow adds complexity
for zero benefit.

---

## Part 6 — A Complete Worked Example End-to-End

**User says:** *"Sharma ka invoice dues statement PDF mein bhejo"*

**Step 1 — Agent receives message**
Looks at active tools: base tools + dynamic tools from DB.
One of the dynamic tools is `send_dues_statement` (admin configured it).

**Step 2 — Agent calls `send_dues_statement` tool**
```json
{"customer_name": "Sharma"}
```

**Step 3 — `_execute_workflow_tool()` fires**
Finds workflow record: adapter_method = "accounting.send_dues_statement"
No OTP threshold. No amount in params.
Proceeds to call adapter.

**Step 4 — importlib calls `accounting.send_dues_statement()`**
```python
# Inside accounting.py
async def send_dues_statement(org_id, customer_name, phone, ...):
    # But wait — "Sharma" matches 3 customers
    customers = await fetch_all(
        "SELECT * FROM customers WHERE name ILIKE $1", f"%{customer_name}%"
    )
    if len(customers) > 1:
        # Return disambiguation message back to agent
        return {"success": False, "needs_clarification": True,
                "matches": [c["name"] for c in customers]}
```

**Step 5 — Agent receives disambiguation signal**
Calls clarify tool: "Found 3 Sharma customers:
1. Sharma Gold House (Delhi)
2. Sharma Ornaments (Jaipur)
3. Sharma Fine Jewels (Lucknow)
Which one?"

**Step 6 — User replies "1"**

**Step 7 — Agent calls `send_dues_statement` again**
This time with full name: "Sharma Gold House"

**Step 8 — Adapter runs successfully**
Fetches all pending + overdue invoices for Sharma Gold House.
Calculates total outstanding, overdue total.
Calls: `pdf_engine.generate_pdf(rows=invoices, title="Dues Statement — Sharma Gold House", doc_type="statement", extra_context={total, overdue_total, customer_details})`

**Step 9 — pdf_engine.generate_pdf()**
LLM receives: invoice rows + title + doc_type="statement" + totals.
LLM generates professional HTML with:
- Header: org name, "ACCOUNT STATEMENT" badge
- Customer section: Sharma Gold House, Delhi
- Invoice table: invoice_number, date, due_date, amount, status
- Totals block: Total outstanding, Overdue amount
- Aging analysis: 60-90 days overdue section
- Payment reminder text

xhtml2pdf converts HTML → PDF bytes.

**Step 10 — PDF sent to WhatsApp**
Response to user: "✅ Dues statement sent for Sharma Gold House. Total outstanding: ₹1,60,000 (₹1,25,000 overdue)."

---

**Now compare with a similar but workflow-free request:**

**User says:** *"Sharma aur Agarwal ke saare invoices PDF mein do"*

**Step 1 — Agent receives message**
This is NOT "send dues statement". This is "show me data as PDF".
Agent doesn't look for a matching workflow tool.
Agent uses `query_database` directly.

**Step 2 — Agent calls `query_database`**
```sql
SELECT c.name, i.invoice_number, i.amount, i.status, i.due_date
FROM invoices i JOIN customers c ON c.id = i.customer_id
WHERE i.org_id = $1
AND c.name ILIKE ANY(ARRAY['%Sharma%','%Agarwal%'])
ORDER BY c.name, i.due_date
```

**Step 3 — Agent calls `generate_pdf`**
```json
{"rows": [...], "title": "Invoices — Sharma & Agarwal", "doc_type": "report"}
```

**Step 4 — pdf_engine generates PDF**
Generic report layout. All invoice rows. Formatted neatly.

**Step 5 — PDF sent**

No workflow involved. No adapter called. Agent handled everything.

---

## Part 7 — The Admin Panel Decision Tree

When admin wants to add something to the system, they ask:

```
Is this a BUSINESS OPERATION (write to DB, call external service,
send a formal document, needs OTP/approval)?
│
├─ YES → Create an ACTION workflow in admin panel
│         • Set adapter_method to existing function
│         • Set entity_schema (what params to extract)
│         • Set OTP threshold if financial
│         • Set approval threshold if high-value
│         • Write training phrases
│
└─ NO → Is this a COMPLEX READ QUERY that users ask frequently
         and needs specific SQL with joins/aggregations?
         │
         ├─ YES → Create a READ workflow in admin panel
         │         • Write the verified SQL template
         │         • Set entity_schema
         │         • Add business_glossary for domain terms
         │
         └─ NO → Do nothing. Agent handles it automatically.
```

---

## Summary in Three Sentences

**The agent** handles every question about data, any PDF of query results,
and anything that is read-only — with zero configuration needed.

**The workflow records** (managed from admin panel) define which
business operations exist (create invoice, update order, send reminder),
what adapter function to call for each, and what gates (OTP, approval)
to enforce — admin configures these, developers write the adapters.

**The PDF engine** is a utility called by both the agent (for ad-hoc
reports) and by adapters (for formal documents like invoices and
quotations) — it is not a decision-making layer, just a renderer.
