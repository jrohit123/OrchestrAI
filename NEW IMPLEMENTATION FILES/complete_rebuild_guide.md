# Complete Rebuild: Unified PDF Engine + Clean Adapters + Fresh Workflows

---

## What This Document Does

Walks you through every file change needed to:
1. Delete all hardcoded PDF generators (pdf_service.py, quotation_pdf.py)
2. Create one unified pdf_engine.py (LLM → HTML → PDF)
3. Clean up all adapters (remove parsing logic, use pdf_engine)
4. Update agent.py to call pdf_engine correctly
5. Generate 8 fresh workflows from admin dashboard

Execute these steps in order. Do not skip steps.

---

## Step 0 — Delete Everything First

### Files to delete completely

```bash
rm app/services/pdf_service.py
rm app/services/quotation_pdf.py
```

### DB: Delete all workflows

```sql
DELETE FROM workflows WHERE org_id = '11111111-0000-0000-0000-000000000001';
```

You will regenerate all workflows from the admin dashboard in Step 5.

### requirements.txt

Remove `fpdf2`. Add `xhtml2pdf`:

```
# Remove this line:
fpdf2

# Add this line:
xhtml2pdf==0.2.17
```

---

## Step 1 — Create app/services/pdf_engine.py

This is the only PDF file in your entire codebase from now on.
It handles invoices, quotations, dues statements, reports — everything.
The LLM writes the HTML. xhtml2pdf converts it. Zero hardcoded layout.

```python
"""
pdf_engine.py — Universal LLM-powered PDF generator.
Replaces pdf_service.py and quotation_pdf.py entirely.

Zero domain hardcoding. Works for jewellery, pharma, IT, hospitals.
The LLM knows what each document type should look like — give it
the data and it generates professional HTML. xhtml2pdf converts to PDF.
"""
import json
import os
from io import BytesIO
from datetime import datetime
from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BRAND_BLUE  = "#185FA5"
BRAND_LIGHT = "#EEF4FB"
BRAND_DARK  = "#1A1A2E"
BRAND_MUTED = "#6B7280"
BRAND_RED   = "#DC2626"
BRAND_GREEN = "#16A34A"


async def generate_pdf(
    rows: list,
    title: str,
    org_name: str,
    subtitle: str = "",
    doc_type: str = "report",
    extra_context: dict = None,
) -> bytes:
    """
    Generate a professional PDF from any data.

    rows         : list of dicts — the query results or line items
    title        : document title e.g. "Tax Invoice INV-1101"
    org_name     : shown in the PDF header
    subtitle     : optional subtitle or date range
    doc_type     : "report" | "invoice" | "quotation" | "statement" | "orders"
    extra_context: pre-computed values not in rows
                   invoice:    {invoice_number, customer_name, customer_city,
                                customer_gstin, amount, gst_rate, due_date, items}
                   quotation:  {quotation_number, customer_name, customer_city,
                                metal_type, weight_grams, rate_per_gram,
                                making_pct, making_charges, subtotal,
                                gst_pct, gst_amount, total_amount, valid_days}
                   statement:  {customer_name, customer_city, customer_gstin,
                                total_outstanding, overdue_total}
    """
    html = await _build_html(
        rows=rows,
        title=title,
        org_name=org_name,
        subtitle=subtitle,
        doc_type=doc_type,
        extra_context=extra_context or {},
    )
    return _html_to_pdf(html)


async def _build_html(
    rows: list,
    title: str,
    org_name: str,
    subtitle: str,
    doc_type: str,
    extra_context: dict,
) -> str:
    """Call LLM to generate professional A4 HTML for this document."""
    today = datetime.now().strftime("%d %b %Y")
    data_for_prompt = rows[:100]
    truncated = len(rows) > 100
    data_json    = json.dumps(data_for_prompt, default=str, indent=2)
    context_json = json.dumps(extra_context, default=str, indent=2)
    trunc_note   = (
        f"\n(Showing first 100 of {len(rows)} rows)"
        if truncated else ""
    )

    doc_type_instructions = {
        "invoice": """
This is a TAX INVOICE. Include:
- Header with org name (left) and "TAX INVOICE" badge (right, blue background)
- Invoice number, date, due date (right column)
- "BILL TO" section with customer name, city, GSTIN
- Line items table: Description | Qty | Unit Price | GST | Total
- Totals block (right-aligned): Subtotal, GST amount, TOTAL (blue row)
- Amount in words (Indian numbering: Rupees X Lakh Y Thousand Only)
- Payment terms footer
- "Powered by OrchestrAI" footer
Use extra_context for all computed values (do not recalculate).
""",
        "quotation": """
This is a PRICE QUOTATION. Include:
- Header with org name and "QUOTATION" badge
- Quotation number, date, valid until (right column)
- Customer section: name, city
- Item details box (light blue background): metal type, weight, rate per gram,
  making charge %, design code if provided
- Price breakdown table: Metal Cost | Calculation | Amount
  rows: Metal Cost, Making Charges, Subtotal, GST, TOTAL (blue row)
- Amount in words
- Validity note: "Valid for X days. Gold rates subject to market fluctuation."
- Terms: advance required, GST as per government norms
Use extra_context for all calculated values (do not recalculate).
""",
        "statement": """
This is an ACCOUNT STATEMENT / DUES STATEMENT. Include:
- Header with org name and "DUES STATEMENT" badge
- Statement date, customer name, total outstanding (right column)
- Customer details section
- Invoice table: Invoice # | Date | Due Date | Amount | Status
  Colour the status: OVERDUE = red text, PENDING = orange text, PAID = green
- Totals block: Total Outstanding, Overdue Amount, Grand Total (blue row)
- Amount in words
- Payment reminder footer: "Please settle at earliest. Late payment: 2% per month."
Use extra_context for total_outstanding and overdue_total.
""",
        "orders": """
This is a PRODUCTION ORDERS LIST. Include:
- Header with org name and "ORDERS REPORT" badge
- Date and total order count
- Orders table with columns from the data
- Status column: use emoji indicators
  confirmed=✅, in_production=🔨, quality_check=🔍, ready=📦, delivered=✅
- Summary row at bottom: total estimated value if available
""",
        "report": """
This is a GENERAL DATA REPORT. Include:
- Header with org name and report title
- Date generated (right-aligned)
- Blue divider line
- Data table: derive column headers from the field names (replace _ with space, title case)
  Format currency columns (amount, total, price, limit, rate) with ₹ and comma separation
  Alternate row shading for readability
- Summary row at bottom: count, and sum of any numeric columns where appropriate
- Add a KEY INSIGHTS section if the data reveals anything notable
  (e.g. "3 items critically below reorder level", "2 customers have overdue > 90 days")
"""
    }

    instructions = doc_type_instructions.get(doc_type, doc_type_instructions["report"])

    prompt = f"""Generate a professional A4 HTML document for printing/PDF.

DOCUMENT TYPE: {doc_type.upper()}
{instructions}

ORGANISATION: {org_name}
TITLE: {title}
{f"SUBTITLE: {subtitle}" if subtitle else ""}
DATE: {today}

BRAND COLOURS:
- Primary blue: {BRAND_BLUE}
- Light blue background: {BRAND_LIGHT}
- Dark text: {BRAND_DARK}
- Muted text: {BRAND_MUTED}
- Red (danger/overdue): {BRAND_RED}
- Green (success/paid): {BRAND_GREEN}

STRUCTURED DATA (rows):
{data_json}{trunc_note}

EXTRA COMPUTED CONTEXT:
{context_json}

REQUIREMENTS:
1. Return ONLY valid HTML. No markdown. No backticks. No explanation.
2. Start with <html> and end with </html>.
3. Use inline CSS only (xhtml2pdf does not support external stylesheets).
4. Font: font-family: Helvetica, Arial, sans-serif
5. Page width: 210mm (A4). Use max-width: 750px in body or a wrapper div.
6. Tables: border-collapse: collapse. Use padding in td/th, not margin.
7. Do NOT use: flexbox, grid, position:fixed, float (xhtml2pdf CSS 2.1 only)
8. Colours: use hex codes directly in style attributes.
9. For currency: always use ₹ symbol with Indian comma formatting (1,00,000)
10. Make it look professional — clean headers, proper spacing, readable fonts.
11. The document should look like it came from a professional accounting system.
"""

    response = await _client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4000,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )

    html = response.choices[0].message.content.strip()

    # Strip any markdown fences if LLM added them
    if html.startswith("```"):
        lines = html.split("\n")
        html  = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    return html


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML string to PDF bytes using xhtml2pdf."""
    from xhtml2pdf import pisa

    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)

    if result.err:
        raise RuntimeError(f"xhtml2pdf error: {result.err}")

    return buffer.getvalue()
```

---

## Step 2 — Rewrite accounting.py

Remove all PDF imports, remove all parse_* functions,
replace PDF calls with pdf_engine. Business logic stays identical.

```python
"""
Accounting adapter — invoice creation, PDF sending, dues statements.
All parsing removed (LLM handles entity extraction).
PDF generation via pdf_engine (universal, domain-agnostic).
"""
import json
from datetime import datetime, timedelta
from app.db import fetch_one, fetch_all, execute
from app.services.pdf_engine import generate_pdf
from app.services.whatsapp import send_document
from app.adapters.inventory import check_stock_availability, deduct_stock


async def create_invoice(
    org_id: str,
    user_id: str = None,
    phone: str = None,
    entity_raw: str = None,
    raw_text: str = None,
    customer_name: str = None,
    amount: float = None,
    item_name: str = None,
    qty: int = None,
    items: list = None,
    **kwargs
) -> dict:
    """Create invoice, generate PDF, send via WhatsApp."""

    customer_name = customer_name or entity_raw
    if not customer_name:
        return {"success": False, "message": "🤔 Which customer?"}
    if not amount:
        return {"success": False, "message": "🤔 What amount?"}

    # Find customer (fuzzy match)
    customer = await fetch_one("""
        SELECT id, name, credit_limit, gst_number, city
        FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

    if not customer:
        return {"success": False,
                "message": f"❌ Customer *{customer_name}* not found."}

    # Multiple match check — return all matches for agent to disambiguate
    all_matches = await fetch_all("""
        SELECT id, name, city FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
    """, org_id, f"%{customer_name}%", customer_name)

    if len(all_matches) > 1:
        names = [f"{r['name']} ({r['city']})" for r in all_matches]
        return {
            "success": False,
            "needs_clarification": True,
            "matches": names,
            "message": (
                f"Found {len(all_matches)} customers matching '{customer_name}':\n"
                + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
                + "\nPlease specify the full customer name."
            )
        }

    # Stock check
    stock_info = None
    if item_name and qty:
        stock_info = await check_stock_availability(
            org_id, entity_raw=item_name, qty=int(qty)
        )
        if not stock_info.get("available"):
            return {"success": False, "message": stock_info["message"]}

    # Build line items
    org_row  = await fetch_one("SELECT name, gst_rate FROM orgs WHERE id = $1", org_id)
    org_name = org_row["name"] if org_row else "Organisation"
    gst_rate = float(org_row["gst_rate"]) if org_row and org_row["gst_rate"] else 3.0

    amount = float(amount)
    if stock_info and qty:
        qty       = int(qty)
        subtotal  = round(amount / (1 + gst_rate / 100), 2)
        gst_val   = round(amount - subtotal, 2)
        items_data = [{
            "description": stock_info["item_name"],
            "qty": qty,
            "unit_price": round(subtotal / qty, 2),
            "gst": gst_val,
            "total": amount
        }]
    else:
        subtotal   = round(amount / (1 + gst_rate / 100), 2)
        gst_val    = round(amount - subtotal, 2)
        items_data = items or [{
            "description": "As per order",
            "qty": 1,
            "unit_price": subtotal,
            "gst": gst_val,
            "total": amount
        }]

    # Auto invoice number
    count_row      = await fetch_one(
        "SELECT COUNT(*) as cnt FROM invoices WHERE org_id = $1", org_id
    )
    invoice_number = f"INV-{1100 + int(count_row['cnt'])}"
    due_date       = (datetime.now() + timedelta(days=30)).strftime("%d %b %Y")

    # Save to DB
    await execute("""
        INSERT INTO invoices
        (org_id, invoice_number, customer_id, created_by, items, amount, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'approved')
    """, org_id, invoice_number, customer["id"], user_id,
        json.dumps(items_data), amount)

    # Deduct stock
    stock_msg = ""
    if stock_info and qty:
        deduct = await deduct_stock(org_id, entity_raw=stock_info["sku"], qty=qty)
        if deduct.get("success"):
            stock_msg = f"\n📦 Stock: {deduct['remaining']} pcs remaining"

    # Generate PDF via universal engine
    pdf_sent = False
    try:
        pdf_bytes = await generate_pdf(
            rows=items_data,
            title=f"Tax Invoice {invoice_number}",
            org_name=org_name,
            doc_type="invoice",
            extra_context={
                "invoice_number": invoice_number,
                "customer_name":  customer["name"],
                "customer_city":  customer.get("city", ""),
                "customer_gstin": customer.get("gst_number", ""),
                "amount":         amount,
                "gst_rate":       gst_rate,
                "due_date":       due_date,
            }
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{invoice_number}.pdf",
            caption=f"🧾 {invoice_number} — {customer['name']} — ₹{amount:,.0f}"
        )
        pdf_sent = True
    except Exception as e:
        print(f"[ACCOUNTING] PDF error: {e}")

    return {
        "success": True,
        "invoice_number": invoice_number,
        "customer": customer["name"],
        "amount": amount,
        "message": (
            f"✅ *Invoice Created*\n\n"
            f"Invoice #: *{invoice_number}*\n"
            f"Customer: {customer['name']}\n"
            f"Amount: *₹{amount:,.0f}*\n"
            f"Due: {due_date}"
            f"{stock_msg}\n\n"
            f"{'📄 PDF sent above ↑' if pdf_sent else '⚠️ PDF generation failed.'}"
        )
    }


async def send_invoice_pdf(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    invoice_number: str = None,
    **kwargs
) -> dict:
    """Resend PDF for an existing invoice by invoice number."""

    inv_num = (invoice_number or entity_raw or "").upper().strip()
    if not inv_num.startswith("INV-"):
        return {"success": False,
                "message": "🤔 Specify invoice number. Example: *send invoice INV-1101*"}

    invoice = await fetch_one("""
        SELECT i.invoice_number, i.amount, i.items, i.due_date,
               i.created_at, i.status,
               c.name as customer_name, c.gst_number, c.city
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.org_id = $1 AND i.invoice_number = $2
    """, org_id, inv_num)

    if not invoice:
        return {"success": False, "message": f"❌ Invoice *{inv_num}* not found."}

    org_row  = await fetch_one("SELECT name, gst_rate FROM orgs WHERE id = $1", org_id)
    org_name = org_row["name"] if org_row else "Organisation"
    gst_rate = float(org_row["gst_rate"]) if org_row and org_row["gst_rate"] else 3.0

    items = invoice.get("items") or []
    if isinstance(items, str):
        items = json.loads(items)

    try:
        pdf_bytes = await generate_pdf(
            rows=items,
            title=f"Tax Invoice {inv_num}",
            org_name=org_name,
            doc_type="invoice",
            extra_context={
                "invoice_number": inv_num,
                "customer_name":  invoice["customer_name"],
                "customer_city":  invoice.get("city", ""),
                "customer_gstin": invoice.get("gst_number", ""),
                "amount":         float(invoice["amount"]),
                "gst_rate":       gst_rate,
                "due_date":       str(invoice.get("due_date", "")),
            }
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{inv_num}.pdf",
            caption=f"🧾 {inv_num} — {invoice['customer_name']} — ₹{invoice['amount']:,.0f}"
        )
        return {
            "success": True,
            "message": (
                f"✅ *Invoice PDF Sent*\n\n"
                f"Invoice: *{inv_num}*\n"
                f"Customer: {invoice['customer_name']}\n"
                f"Amount: ₹{invoice['amount']:,.0f} | Status: {invoice['status']}"
            )
        }
    except Exception as e:
        return {"success": False, "message": f"⚠️ PDF error: {str(e)}"}


async def send_dues_statement(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    customer_name: str = None,
    **kwargs
) -> dict:
    """Generate and send formal dues statement PDF for a customer."""

    customer_name = customer_name or entity_raw
    if not customer_name:
        return {"success": False, "message": "🤔 Which customer?"}

    # Fuzzy customer lookup
    customers = await fetch_all("""
        SELECT id, name, city, gst_number FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
    """, org_id, f"%{customer_name}%", customer_name)

    if not customers:
        return {"success": False,
                "message": f"❌ Customer *{customer_name}* not found."}

    if len(customers) > 1:
        names = [f"{c['name']} ({c['city']})" for c in customers]
        return {
            "success": False,
            "needs_clarification": True,
            "matches": names,
            "message": (
                f"Found {len(customers)} customers matching '{customer_name}':\n"
                + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
            )
        }

    customer = customers[0]

    invoices = await fetch_all("""
        SELECT invoice_number, amount, status, due_date, created_at
        FROM invoices
        WHERE org_id = $1 AND customer_id = $2
          AND status IN ('pending', 'overdue')
        ORDER BY due_date ASC
    """, org_id, customer["id"])

    if not invoices:
        return {
            "success": True,
            "message": f"✅ *{customer['name']}* has no outstanding dues."
        }

    total     = sum(float(r["amount"]) for r in invoices)
    overdue   = sum(float(r["amount"]) for r in invoices if r["status"] == "overdue")

    org_row  = await fetch_one("SELECT name FROM orgs WHERE id = $1", org_id)
    org_name = org_row["name"] if org_row else "Organisation"

    rows = [
        {
            "invoice_number": r["invoice_number"],
            "created_at":     str(r["created_at"])[:10] if r["created_at"] else "",
            "due_date":       str(r["due_date"]) if r["due_date"] else "N/A",
            "amount":         float(r["amount"]),
            "status":         r["status"].upper(),
        }
        for r in invoices
    ]

    try:
        pdf_bytes = await generate_pdf(
            rows=rows,
            title=f"Dues Statement — {customer['name']}",
            org_name=org_name,
            subtitle=f"As of {datetime.now().strftime('%d %b %Y')}",
            doc_type="statement",
            extra_context={
                "customer_name":      customer["name"],
                "customer_city":      customer.get("city", ""),
                "customer_gstin":     customer.get("gst_number", ""),
                "total_outstanding":  total,
                "overdue_total":      overdue,
            }
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"dues_{customer['name'].replace(' ', '_')}.pdf",
            caption=f"📊 Dues Statement — {customer['name']} — ₹{total:,.0f}"
        )
        return {
            "success": True,
            "message": (
                f"✅ *Dues Statement Sent*\n\n"
                f"Customer: {customer['name']}\n"
                f"Total Outstanding: *₹{total:,.0f}*\n"
                f"Overdue: ₹{overdue:,.0f}\n"
                f"Invoices: {len(invoices)}"
            )
        }
    except Exception as e:
        return {"success": False, "message": f"⚠️ PDF error: {str(e)}"}
```

---

## Step 3 — Rewrite quotation.py

Remove parse_* functions, remove quotation_pdf import, use pdf_engine.

```python
"""
Quotation adapter — price quotations and metal rate management.
PDF generation via pdf_engine (universal).
"""
from datetime import datetime, timedelta
from app.db import fetch_one, fetch_all, execute
from app.services.pdf_engine import generate_pdf
from app.services.whatsapp import send_document


async def create_quotation(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    raw_text: str = None,
    customer_name: str = None,
    metal_type: str = None,
    weight_grams: float = None,
    design_code: str = None,
    valid_days: int = 3,
    **kwargs
) -> dict:
    """Generate price quotation and send as PDF."""

    customer_name = customer_name or entity_raw
    if not customer_name:
        return {"success": False,
                "message": "🤔 Specify customer. Example: *quote Mehta 22kt 15g*"}
    if not metal_type:
        return {"success": False,
                "message": "🤔 Specify metal type: 22kt, 18kt, 14kt, silver, platinum"}
    if not weight_grams:
        return {"success": False,
                "message": "🤔 Specify weight in grams. Example: *15.5g*"}

    weight_grams = float(weight_grams)

    # Find customer
    customer = await fetch_one("""
        SELECT id, name, city FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

    if not customer:
        return {"success": False,
                "message": f"❌ Customer *{customer_name}* not found."}

    # Multiple match check
    all_matches = await fetch_all("""
        SELECT name, city FROM customers
        WHERE org_id = $1 AND name ILIKE $2
    """, org_id, f"%{customer_name}%")

    if len(all_matches) > 1:
        names = [f"{r['name']} ({r['city']})" for r in all_matches]
        return {
            "success": False,
            "needs_clarification": True,
            "matches": names,
            "message": (
                f"Found {len(all_matches)} customers matching '{customer_name}':\n"
                + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
            )
        }

    # Fetch metal rate
    rate_row = await fetch_one("""
        SELECT rate_per_gram, making_charge_pct FROM pricing
        WHERE org_id = $1 AND metal_type = $2 AND quotation_number IS NULL
    """, org_id, metal_type.lower())

    if not rate_row:
        rates = await fetch_all(
            "SELECT metal_type FROM pricing WHERE org_id = $1 AND quotation_number IS NULL",
            org_id
        )
        available = ", ".join(r["metal_type"] for r in rates) if rates else "none configured"
        return {
            "success": False,
            "message": (
                f"❌ No rate for *{metal_type}*.\n"
                f"Available: {available}\n"
                f"Set rate: *set rate {metal_type} [amount]*"
            )
        }

    # Fetch org settings
    org     = await fetch_one("SELECT name, gst_rate FROM orgs WHERE id = $1", org_id)
    org_name = org["name"] if org else "Organisation"
    gst_pct  = float(org["gst_rate"]) if org and org["gst_rate"] else 3.0

    # Calculate
    rate_per_gram   = float(rate_row["rate_per_gram"])
    making_pct      = float(rate_row["making_charge_pct"])
    metal_cost      = round(weight_grams * rate_per_gram, 2)
    making_charges  = round(metal_cost * making_pct / 100, 2)
    subtotal        = round(metal_cost + making_charges, 2)
    gst_amount      = round(subtotal * gst_pct / 100, 2)
    total_amount    = round(subtotal + gst_amount, 2)
    valid_until     = (datetime.now() + timedelta(days=valid_days)).strftime("%d %b %Y")

    # Auto quotation number
    count_row        = await fetch_one(
        "SELECT COUNT(*) as cnt FROM pricing WHERE org_id = $1 AND quotation_number IS NOT NULL",
        org_id
    )
    quotation_number = f"QUO-{1001 + int(count_row['cnt'])}"

    # Save
    await execute("""
        INSERT INTO pricing (
            org_id, quotation_number, metal_type, weight_grams,
            rate_per_gram, making_charge_pct, making_charges,
            subtotal, gst_pct, gst_amount, total_amount,
            status, valid_until, created_by
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'sent',$12,$13)
    """, org_id, quotation_number, metal_type.lower(), weight_grams,
        rate_per_gram, making_pct, making_charges, subtotal,
        gst_pct, gst_amount, total_amount,
        datetime.now().date() + timedelta(days=valid_days), user_id)

    # Generate PDF
    pdf_sent = False
    try:
        pdf_bytes = await generate_pdf(
            rows=[],
            title=f"Price Quotation {quotation_number}",
            org_name=org_name,
            doc_type="quotation",
            extra_context={
                "quotation_number": quotation_number,
                "customer_name":    customer["name"],
                "customer_city":    customer.get("city", ""),
                "metal_type":       metal_type.upper(),
                "weight_grams":     weight_grams,
                "design_code":      design_code or "Standard",
                "rate_per_gram":    rate_per_gram,
                "making_pct":       making_pct,
                "making_charges":   making_charges,
                "metal_cost":       metal_cost,
                "subtotal":         subtotal,
                "gst_pct":          gst_pct,
                "gst_amount":       gst_amount,
                "total_amount":     total_amount,
                "valid_days":       valid_days,
                "valid_until":      valid_until,
            }
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{quotation_number}.pdf",
            caption=f"📋 {quotation_number} — {customer['name']} — ₹{total_amount:,.0f}"
        )
        pdf_sent = True
    except Exception as e:
        print(f"[QUOTATION] PDF error: {e}")

    return {
        "success": True,
        "quotation_number": quotation_number,
        "message": (
            f"📋 *Quotation Generated*\n\n"
            f"Quote #: *{quotation_number}*\n"
            f"Customer: {customer['name']}\n"
            f"Metal: {metal_type.upper()} @ ₹{rate_per_gram:,.0f}/g\n"
            f"Weight: {weight_grams:.3f}g\n"
            f"Making ({making_pct:.0f}%): ₹{making_charges:,.0f}\n"
            f"GST ({gst_pct:.0f}%): ₹{gst_amount:,.0f}\n"
            f"*Total: ₹{total_amount:,.0f}*\n\n"
            f"Valid until: {valid_until}\n"
            f"{'📄 PDF sent above ↑' if pdf_sent else '⚠️ PDF unavailable.'}\n\n"
            f"To confirm order: *accept quote {quotation_number}*"
        )
    }


async def set_metal_rate(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    metal_type: str = None,
    rate_per_gram: float = None,
    making_charge_pct: float = None,
    **kwargs
) -> dict:
    """Update metal rate and/or making charges."""

    if not metal_type:
        return {"success": False,
                "message": "🤔 Specify metal type. Example: *set rate 22kt 6200*"}
    if rate_per_gram is None and making_charge_pct is None:
        return {"success": False,
                "message": "🤔 Specify rate or making %. Example: *set rate 22kt 6200*"}

    metal_type = metal_type.lower().strip()

    existing = await fetch_one("""
        SELECT rate_per_gram, making_charge_pct FROM pricing
        WHERE org_id = $1 AND metal_type = $2 AND quotation_number IS NULL
    """, org_id, metal_type)

    if not existing:
        await execute("""
            INSERT INTO pricing (org_id, metal_type, rate_per_gram, making_charge_pct,
                                 updated_by, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
        """, org_id, metal_type,
            rate_per_gram or 0, making_charge_pct or 15.0, user_id)
    else:
        new_rate   = rate_per_gram if rate_per_gram is not None else float(existing["rate_per_gram"])
        new_making = making_charge_pct if making_charge_pct is not None else float(existing["making_charge_pct"])
        await execute("""
            UPDATE pricing SET rate_per_gram=$1, making_charge_pct=$2,
                               updated_by=$3, updated_at=NOW()
            WHERE org_id=$4 AND metal_type=$5 AND quotation_number IS NULL
        """, new_rate, new_making, user_id, org_id, metal_type)

    parts = []
    if rate_per_gram is not None:
        parts.append(f"Rate: ₹{rate_per_gram:,.0f}/g")
    if making_charge_pct is not None:
        parts.append(f"Making: {making_charge_pct:.1f}%")

    return {
        "success": True,
        "message": (
            f"✅ *{metal_type.upper()} Rate Updated*\n\n"
            + "\n".join(parts)
            + "\n\n_New quotations will use this rate._"
        )
    }
```

---

## Step 4 — Clean up orders.py

Remove `parse_order_command()` and `get_orders()`.
The LLM extracts entities. The agent handles reads via query_database.

```python
# In orders.py — DELETE these two functions entirely:
# 1. parse_order_command(raw_text) — all lines
# 2. get_orders(org_id, ...) — all lines

# Also DELETE these from the parse_invoice_details calls in create_order:
# The entire block starting with:
#   if not customer_name or not description:
#       parsed = parse_order_command(raw_text)
#       if parsed["action"] == "accept_quote":
# Replace with simply:
#   customer_name = customer_name or entity_raw

# Keep intact:
# - STATUS_MAP dict
# - STATUS_LABELS dict
# - ACTIVE_STATUSES list
# - create_order() — business logic only
# - update_order_status() — business logic only
# - accept_quotation() — business logic only
```

The cleaned `create_order` signature becomes:

```python
async def create_order(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    raw_text: str = None,
    customer_name: str = None,
    description: str = None,
    metal_type: str = None,
    estimated_amount: float = None,
    quotation_id: str = None,
    **kwargs
) -> dict:
    customer_name = customer_name or entity_raw
    if not customer_name:
        return {"success": False, "message": "🤔 Which customer?"}
    if not description:
        return {"success": False, "message": "🤔 What item/description?"}
    # ... rest of existing logic unchanged ...
```

---

## Step 5 — Update agent.py generate_pdf tool

The generate_pdf tool in agent.py calls pdf_engine now.
Update the `_execute_tool` function's `generate_pdf` block:

```python
elif tool_name == "generate_pdf":
    from app.services.pdf_engine import generate_pdf as engine_generate
    from app.services.whatsapp import send_document

    rows         = tool_input.get("rows", [])
    title        = tool_input.get("title", "Report")
    subtitle     = tool_input.get("subtitle", "")
    doc_type     = tool_input.get("doc_type", "report")
    extra_context = tool_input.get("extra_context", {})

    if not rows and not extra_context:
        return "ERROR: No data to generate PDF from"

    try:
        org_row  = await fetch_one("SELECT name FROM orgs WHERE id = $1", user["org_id"])
        org_name = org_row["name"] if org_row else user["org_name"]

        pdf_bytes = await engine_generate(
            rows=rows,
            title=title,
            org_name=org_name,
            subtitle=subtitle,
            doc_type=doc_type,
            extra_context=extra_context
        )
        filename = f"{title.replace(' ', '_')[:40]}.pdf"
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=filename,
            caption=f"📄 {title}"
        )
        return f"PDF_SENT: {title} ({len(rows)} rows)"

    except Exception as e:
        return f"ERROR generating PDF: {str(e)}"
```

Also update the generate_pdf tool definition in TOOLS to include doc_type:

```python
{
    "type": "function",
    "function": {
        "name": "generate_pdf",
        "description": (
            "Generate a PDF from query results and send it to the user. "
            "Call query_database first to get the data, then call this. "
            "Choose doc_type carefully: "
            "'report' for general data tables and summaries, "
            "'statement' for customer dues/outstanding statements, "
            "'orders' for production order lists, "
            "'invoice' only when generating a formal tax invoice. "
            "'quotation' only when generating a price quotation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rows":    {"type": "array",  "description": "Data rows from query_database"},
                "title":   {"type": "string", "description": "PDF title"},
                "subtitle":{"type": "string", "description": "Optional subtitle"},
                "doc_type":{"type": "string",
                            "enum": ["report", "statement", "orders", "invoice", "quotation"],
                            "description": "Document type — controls layout and formatting"},
                "extra_context": {"type": "object",
                                  "description": "Pre-computed totals or metadata"}
            },
            "required": ["rows", "title"]
        }
    }
}
```

---

## Step 6 — Generate 8 Workflows From Admin Dashboard

Go to `/admin?token=your_token` → AI Workflow Builder.
Type each description below exactly. Generate → Review → Save.

Do these one by one. After each save, the agent immediately
gains that capability.

---

### Workflow 1: Create Invoice

**Type in admin panel:**
```
Create a sales invoice for a customer for a specified amount.
If the item name and quantity are provided, verify stock
availability before creating. Generate a professional tax invoice
PDF and send it via WhatsApp. Support OTP verification for
invoices above ₹50,000 and owner approval for invoices above ₹1,00,000.
```

After generating, manually set:
- `adapter_method`: `accounting.create_invoice`
- `otp_required`: true
- `otp_threshold`: 50000
- `approval_threshold`: 100000
- Roles: owner, accountant, sales

---

### Workflow 2: Send Invoice PDF

**Type in admin panel:**
```
Resend the PDF for an existing invoice by invoice number.
Useful when a customer needs the invoice document again.
```

After generating, manually set:
- `adapter_method`: `accounting.send_invoice_pdf`
- `otp_required`: false
- Roles: owner, accountant, sales

---

### Workflow 3: Send Dues Statement

**Type in admin panel:**
```
Generate and send a formal dues statement PDF showing all
pending and overdue invoices for a specific customer.
This is a formal account statement with aging analysis and total outstanding.
```

After generating, manually set:
- `adapter_method`: `accounting.send_dues_statement`
- `otp_required`: false
- Roles: owner, accountant

---

### Workflow 4: Create Quotation

**Type in admin panel:**
```
Generate a formal price quotation for a customer based on
metal type and weight in grams. Fetch current metal rate and
making charges from the pricing table, calculate metal cost,
making charges and GST, save the quotation, and send a
professional quotation PDF via WhatsApp.
```

After generating, manually set:
- `adapter_method`: `quotation.create_quotation`
- `otp_required`: false
- Roles: owner, sales
- entity_schema should include: customer_name, metal_type, weight_grams, design_code (optional)

---

### Workflow 5: Set Metal Rate

**Type in admin panel:**
```
Update the rate per gram for a specific metal type in the
pricing table. Optionally also update the making charge percentage.
This is a financial operation requiring OTP verification.
Supports metals: 22kt, 18kt, 14kt, silver, platinum.
```

After generating, manually set:
- `adapter_method`: `quotation.set_metal_rate`
- `otp_required`: true
- `otp_threshold`: 0  ← always requires OTP (any rate change)
- Roles: owner only
- entity_schema should include: metal_type (required), rate_per_gram (required), making_charge_pct (optional)

---

### Workflow 6: Create Production Order

**Type in admin panel:**
```
Create a new jewellery production order for a customer.
Requires customer name, item description, and optionally
metal type and estimated amount. Auto-generates an order number
and sets initial status to confirmed.
```

After generating, manually set:
- `adapter_method`: `orders.create_order`
- `otp_required`: false
- Roles: owner, sales
- entity_schema should include: customer_name (required), description (required), metal_type (optional), estimated_amount (optional)

---

### Workflow 7: Update Order Status

**Type in admin panel:**
```
Update the production status of an existing order.
Valid statuses: confirmed, in production, quality check, ready, delivered.
Requires the order number and the new status.
Append to the order's status history.
```

After generating, manually set:
- `adapter_method`: `orders.update_order_status`
- `otp_required`: false
- Roles: owner, sales, warehouse
- entity_schema should include: order_number (required), new_status_text (required)

---

### Workflow 8: Accept Quotation → Convert to Order

**Type in admin panel:**
```
Accept an existing price quotation and convert it into a
confirmed production order. Takes a quotation number,
marks the quotation as converted, and creates a new order
with the quotation details.
```

After generating, manually set:
- `adapter_method`: `orders.accept_quotation`
- `otp_required`: false
- Roles: owner, sales
- entity_schema should include: quotation_number (required)

---

## Step 7 — Verify Installation

```bash
# Confirm xhtml2pdf installed
python -c "from xhtml2pdf import pisa; print('xhtml2pdf OK')"

# Confirm old PDF files are gone
ls app/services/pdf_service.py    # should: No such file
ls app/services/quotation_pdf.py  # should: No such file
ls app/services/pdf_engine.py     # should: exist

# Confirm no old imports remain
grep -rn "from app.services.pdf_service" app/     # should: 0 results
grep -rn "from app.services.quotation_pdf" app/   # should: 0 results
grep -rn "generate_invoice_pdf" app/              # should: 0 results
grep -rn "generate_quotation_pdf" app/            # should: 0 results
grep -rn "from fpdf import" app/                  # should: 0 results
```

---

## Step 8 — Test Queries to Run After Deploy

### Test PDF engine (agent-generated PDFs — no workflow)
```
give me all overdue invoices as PDF
top 5 customers by outstanding as PDF
all ready orders PDF bana do
low stock items report PDF
all customers with their credit limits as PDF
Mehta Jewellers aur Sharma Gold House ke saare invoices PDF mein
```

### Test action workflows (workflow + adapter + pdf_engine)
```
invoice Mehta Jewellers 45000
invoice Singh Bullion Mart 150000      ← should trigger approval
quote Sharma Gold House 22kt 15g
quote Jain Gold Works 18kt 8g DC-001
set rate 22kt 6500                     ← should trigger OTP
new order Mehta Enterprises 22kt gold bangle set
update ORD-1006 to quality check
mark ORD-1011 as delivered
send dues statement Agarwal
send invoice pdf INV-201
accept quote QUO-1001
```

### Test disambiguation
```
Mehta ka invoice banao 30000           ← 4 Mehtas, should ask which one
quote Sharma 22kt 12g                  ← 3 Sharmas, should ask which one
```

### Test that reads still work (no workflow needed)
```
which Mehta has highest dues
all overdue customers list
ORD-1009 ka status kya hai
22kt gold rate kya hai
orders in quality check
pending invoices above 1 lakh
```

---

## Summary: Files Changed

| File | Action |
|------|--------|
| `app/services/pdf_service.py` | **DELETED** |
| `app/services/quotation_pdf.py` | **DELETED** |
| `app/services/pdf_engine.py` | **CREATED** — universal LLM PDF engine |
| `app/adapters/accounting.py` | **REWRITTEN** — uses pdf_engine, no parse functions |
| `app/adapters/quotation.py` | **REWRITTEN** — uses pdf_engine, no parse functions |
| `app/adapters/orders.py` | **CLEANED** — remove parse_order_command and get_orders |
| `app/services/agent.py` | **UPDATED** — generate_pdf tool uses pdf_engine, adds doc_type |
| `requirements.txt` | fpdf2 removed, xhtml2pdf added |
| DB workflows table | All deleted, 8 new ones generated from admin panel |
