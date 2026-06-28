# Universal PDF Engine — Eliminating Every Hardcoded PDF Generator

---

## What This Document Is

A step-by-step plan to delete `pdf_service.py`, `quotation_pdf.py`, and every
hardcoded PDF function, replacing them with a single, domain-agnostic engine
that generates professional PDFs for any client in any industry — jewellery,
pharma, IT, hospitals — without touching a line of code.

**The core idea:** instead of writing Python that knows how to lay out an invoice,
let the LLM write the HTML for each document based on the actual data it
receives. A converter turns that HTML into a PDF. You write zero layout code.

---

## Part 1 — The Audit: What Is Currently Hardcoded and Why It Breaks

### 1A — Files that must die

| File | Functions | Lines of hardcoded layout | What they assume |
|------|-----------|--------------------------|-----------------|
| `pdf_service.py` | `generate_invoice_pdf()` | ~180 lines | column names: `invoice_number`, `amount`, `status`, `due_date` |
| `pdf_service.py` | `generate_dues_statement_pdf()` | ~120 lines | column names, total/overdue split, 3-column invoice table |
| `pdf_service.py` | `_generate_generic_pdf()` | ~90 lines | arbitrary columns but produces mediocre layout |
| `quotation_pdf.py` | `generate_quotation_pdf()` | ~200 lines | jewellery-specific sections: "ITEM DETAILS", "Metal Type", "Making Charges" |

**Total: ~590 lines of layout code that breaks the moment you onboard a pharma client.**

### 1B — What each function hardcodes

**`generate_invoice_pdf()`:**
- Hardcodes 5 columns: Description, Qty, Unit Price, GST%, Total
- Hardcodes section headers: "BILL TO", "TAX INVOICE"
- Hardcodes terms text: "Late payment attracts 2% interest per month"
- Hardcodes gst_rate=3.0 default
- Hardcodes the fact that invoices have exactly these fields

**`generate_dues_statement_pdf()`:**
- Hardcodes columns: Invoice #, Date, Due Date, Amount, Status
- Hardcodes section: total_outstanding and overdue_total as separate rows
- Hardcodes terms: "Please pay at the earliest"
- Hardcodes the fact that "dues" = invoices

**`generate_quotation_pdf()`:**
- Hardcodes the "ITEM DETAILS" box with Metal Type, Weight, Rate
- Hardcodes the price breakdown: Metal Cost → Making Charges → Subtotal → GST
- Hardcodes jewellery-specific terms: "Gold rates subject to market fluctuation"
- Hardcodes 5 validity terms specific to jewellery
- Hardcodes valid_days, customer_city, design_code fields

### 1C — Why this is unsustainable

If you onboard a pharma client:
- Their invoices have: prescription_number, drug_name, batch_number, expiry_date, MRP, discount
- Their dues statements track: supplier invoices, credit notes, partial payments
- Their quotations quote: drug quantities, pack sizes, storage conditions

None of your current functions handle any of this.
You would write a new `generate_pharma_invoice_pdf()`, a new `generate_pharma_dues_pdf()`,
and a new `generate_pharma_quotation_pdf()`. Then again for a hospital. Then again for IT.

The correct answer is: **the LLM knows what an invoice looks like across all industries.
Give it the data, tell it what kind of document it is, and it writes the HTML.**

---

## Part 2 — The Architecture

```
User says: "Mehta ka dues statement PDF mein do"
               ↓
Agent: query_database → gets invoice rows for Mehta
Agent: generate_pdf(rows, "Dues Statement — Mehta Jewellers", doc_type="statement")
               ↓
pdf_engine.generate_pdf() is called
               ↓
STEP 1: Call LLM with rows + title + doc_type
        LLM generates professional A4 HTML
               ↓
STEP 2: xhtml2pdf converts HTML → PDF bytes
               ↓
STEP 3: send_document() → WhatsApp
```

The same flow handles: invoices, quotations, dues statements, aging reports,
stock reports, order lists, custom summaries — for any industry. Zero code changes.

### Why xhtml2pdf over WeasyPrint for Railway deployment

| Criterion | xhtml2pdf | WeasyPrint |
|-----------|-----------|------------|
| System deps | None — pure Python pip install | Needs pango, cairo, gdk-pixbuf |
| Railway setup | `pip install xhtml2pdf` in requirements | Needs `NIXPACKS_PKGS="cairo pango gobject-introspection glib libffi pkg-config"` |
| CSS support | CSS 2.1 + partial 3 (tables, colors, fonts) | Full CSS3 (flexbox, grid, @page) |
| Output quality | Good for tables, professional documents | Excellent, browser-level |
| JS required | No | No |

For invoices, dues statements, reports, quotations — tabular layouts using
CSS 2.1 are entirely sufficient. xhtml2pdf handles all of these cleanly.

**Optional upgrade to WeasyPrint:** if you later want browser-quality output,
add `NIXPACKS_PKGS="cairo pango gobject-introspection glib libffi pkg-config"`
to Railway env vars, add `weasyprint` to requirements.txt, and swap the converter
(one function change in pdf_engine.py, documented at the bottom of this file).

---

## Part 3 — Installation

### Step 1: Update requirements.txt

Remove `fpdf2` (no longer needed). Add `xhtml2pdf`:

```
# REMOVE:
fpdf2

# ADD:
xhtml2pdf==0.2.17
```

Both changes in the same commit. `xhtml2pdf` pulls in `reportlab` automatically.

### Step 2: Verify install works locally

```bash
pip install xhtml2pdf==0.2.17
python -c "from xhtml2pdf import pisa; print('xhtml2pdf OK')"
```

No system packages needed. If this passes, Railway will pass too.

---

## Part 4 — The New File: `app/services/pdf_engine.py`

Create this file. It replaces `pdf_service.py` and `quotation_pdf.py` entirely.

```python
"""
pdf_engine.py — Universal LLM-powered PDF generator.

Completely domain-agnostic. Replaces:
  - generate_invoice_pdf()
  - generate_dues_statement_pdf()
  - generate_quotation_pdf()
  - _generate_generic_pdf()

How it works:
  1. Caller passes: data rows + document title + doc_type hint + extra computed context
  2. LLM generates professional A4 HTML for the document
  3. xhtml2pdf converts HTML → PDF bytes
  4. Bytes returned to caller for WhatsApp delivery

Works for jewellery, pharma, IT, hospitals — no code changes per client.
The LLM knows what each document type should look like from its training.
"""
import json
import os
from io import BytesIO
from datetime import datetime
from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ── Brand colours (used in the prompt so LLM includes them in HTML) ──────────
BRAND_BLUE  = "#185FA5"
BRAND_LIGHT = "#EEF4FB"
BRAND_DARK  = "#1A1A2E"
BRAND_MUTED = "#6B7280"


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

    Parameters
    ----------
    rows         : list of dicts — the data to show in the document.
                   Can be empty if all data is in extra_context (e.g. quotations).
    title        : str — shown at the top of the PDF (e.g. "Tax Invoice INV-001")
    org_name     : str — company name in the header
    subtitle     : str — optional secondary title or date range
    doc_type     : str — hint for the LLM. One of:
                   "report"     → general data table with summary row
                   "invoice"    → tax invoice with GST breakdown, BILL TO section
                   "quotation"  → price quotation with item details, price breakdown
                   "statement"  → dues/account statement with aging analysis
                   "orders"     → production order list with status indicators
    extra_context: dict — pre-computed values the LLM needs but are not in rows.
                   For invoices: invoice_number, customer details, due_date, gst_rate
                   For quotations: full calculation breakdown (metal_cost, making, gst, total)
                   For statements: total_outstanding, overdue_total, customer details
                   For reports: optional summary totals

    Returns
    -------
    bytes — PDF file contents. Raise on error.
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
    """Call the LLM to generate professional A4 HTML for this document."""
    today = datetime.now().strftime("%d %b %Y")

    # Limit rows to 100 for the prompt (large datasets would overflow token limit)
    data_for_prompt = rows[:100]
    truncated = len(rows) > 100
    data_json = json.dumps(data_for_prompt, default=str, indent=2)
    context_json = json.dumps(extra_context, default=str, indent=2)

    truncation_note = (
        f"\n(Note: data truncated to first 100 of {len(rows)} rows for brevity)"
        if truncated else ""
    )

    prompt = f"""You are generating a professional PDF document for a business.

===== DOCUMENT DETAILS =====
Organization: {org_name}
Document Type: {doc_type}
Title: {title}
Subtitle: {subtitle or "(none)"}
Date: {today}
Total Rows: {len(rows)}{truncation_note}

===== DATA =====
{data_json}

===== PRE-COMPUTED CONTEXT =====
(Use these values directly — do not recalculate from the data above)
{context_json}

===== WHAT TO GENERATE =====
Write a complete, professional A4 HTML document for PDF conversion using xhtml2pdf.

DESIGN:
- Primary blue: {BRAND_BLUE}
- Light blue bg: {BRAND_LIGHT}
- Dark text: {BRAND_DARK}
- Muted text: {BRAND_MUTED}
- Font: Arial, Helvetica, sans-serif
- Page: A4 (210mm × 297mm), margins 15mm

STRUCTURE (always include):
1. Header: org name (large, blue) | document title (medium) | date (right-aligned)
   — Blue divider line beneath header
2. Document body: appropriate for doc_type (see rules below)
3. Footer: "Generated by OrchestrAI on {today}" in muted small text

DOC_TYPE RULES:

report:
  - Data in a clean table with blue header row (white text), alternating light-blue rows
  - Column headers derived from dict keys (convert underscores to spaces, Title Case)
  - Summary row at bottom: count of rows + SUM of any numeric "amount"/"total" columns
  - Add KEY INSIGHTS section below table if data shows notable patterns
    (e.g., "3 items below reorder level — urgent restocking needed")

invoice:
  - "TAX INVOICE" badge in header (right side, blue fill, white text)
  - "BILL TO" section with customer name, city, GSTIN from extra_context
  - Invoice #, Date, Due Date in upper right (from extra_context)
  - Items table: Description | Qty | Unit Price | GST% | Total
  - Totals block (right-aligned): Subtotal, GST amount, TOTAL (blue highlight)
  - Amount in words (Indian system: Rupees X Lakh Y Thousand Only)
  - Terms: "Payment due within 30 days. Late payment: 2% per month."

quotation:
  - "QUOTATION" badge in header
  - "PREPARED FOR" section with customer name and city from extra_context
  - Item Details box (light-blue bg): Metal Type | Weight | Rate per gram | Making%
  - Price Breakdown table:
      Metal Cost = weight × rate_per_gram
      Making Charges = metal_cost × making_charge_pct / 100
      Subtotal
      GST = subtotal × gst_pct / 100
      TOTAL (blue highlight row)
  - All values from extra_context — use them directly, do not recalculate
  - "Quotation valid for 3 days from date of issue" note
  - Terms: Gold rates subject to market fluctuation. Advance required to confirm.

statement:
  - "ACCOUNT STATEMENT" heading
  - Customer details from extra_context (name, city, GSTIN)
  - Outstanding summary box:
      Total Outstanding: ₹X (from extra_context.total_outstanding)
      Overdue Amount: ₹X (from extra_context.overdue_total)
  - Invoice table: Invoice # | Date | Due Date | Amount | Status | Days Overdue
    Colour-code status: overdue rows → light red (#FFF0F0), pending → light yellow (#FFFBE6)
  - Aging analysis if dates available:
      0–30 days: ₹X
      31–90 days: ₹X
      >90 days: ₹X (HIGH RISK)
  - Terms: "Please clear outstanding at the earliest. Late interest: 2% per month."

orders:
  - Orders table with: Order # | Customer | Description | Metal | Status | Est. Amount
  - Status column with emoji indicators:
      confirmed → ✅ Confirmed
      in_production → 🔨 In Production
      quality_check → 🔍 Quality Check
      ready → 📦 Ready for Delivery
      delivered → ✅ Delivered
  - Summary: count by status at the bottom

MONETARY FORMATTING:
  - Always format with ₹ and Indian commas: ₹1,07,000 (not $107,000)
  - Round to nearest rupee for display

XHTML2PDF COMPATIBILITY (critical — follow these or the PDF will break):
  - Use only inline CSS or <style> inside <head> — no external stylesheets
  - Tables: always set width="100%" and explicit column widths via style="width:X%"
  - Use table-based layouts for multi-column sections (no flexbox, no grid, no float)
  - Use <br/> not <br>
  - Do not use CSS variables (--var-name) — use literal hex values
  - Do not use: position:fixed, position:absolute, transform, animation
  - Font sizes in pt preferred (e.g., 10pt, 12pt, 14pt)
  - Page break hints: use style="page-break-before:always" on elements

Return ONLY the complete HTML. Start with <!DOCTYPE html>. No markdown, no code fences, no explanation."""

    response = await _client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )

    html = response.choices[0].message.content.strip()

    # Strip any markdown fences if LLM accidentally adds them
    if html.startswith("```"):
        lines = html.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines) - 1 if lines[-1] == "```" else len(lines)
        html = "\n".join(lines[start:end])
    html = html.strip()

    return html


def _html_to_pdf(html: str) -> bytes:
    """
    Convert HTML string → PDF bytes using xhtml2pdf.
    Raises ValueError if conversion fails.
    """
    from xhtml2pdf import pisa

    buf = BytesIO()
    status = pisa.CreatePDF(html, dest=buf, encoding="utf-8")

    if status.err:
        raise ValueError(
            f"xhtml2pdf conversion failed with {status.err} error(s). "
            f"Check HTML output for malformed tags."
        )

    return buf.getvalue()


# ── Optional: WeasyPrint converter (higher quality, needs system libs) ────────
# To use: add NIXPACKS_PKGS="cairo pango gobject-introspection glib libffi pkg-config"
# to Railway env vars, add "weasyprint" to requirements.txt, and replace
# _html_to_pdf with _html_to_pdf_weasyprint below.

def _html_to_pdf_weasyprint(html: str) -> bytes:
    """WeasyPrint converter — higher quality, needs system-level pango/cairo."""
    from weasyprint import HTML
    return HTML(string=html).write_pdf()
```

---

## Part 5 — Files to Delete

Delete these files completely. Nothing in them survives.

```bash
rm app/services/pdf_service.py
rm app/services/quotation_pdf.py
```

**Verify nothing else imports them:**
```bash
grep -r "from app.services.pdf_service" app/
grep -r "from app.services.quotation_pdf" app/
grep -r "import pdf_service" app/
grep -r "import quotation_pdf" app/
```

Expected output after the changes in Part 6: **zero results.**

---

## Part 6 — Minimal Changes to Each Affected File

### 6A — `accounting.py`

**Old imports (lines 4-5):**
```python
from app.services.pdf_service import generate_invoice_pdf, generate_dues_statement_pdf
from app.services.whatsapp import send_document
from app.adapters.inventory import check_stock_availability, deduct_stock
```

**New imports:**
```python
from app.services.pdf_engine import generate_pdf
from app.services.whatsapp import send_document
from app.adapters.inventory import check_stock_availability, deduct_stock
```

---

**Old PDF block in `create_invoice()` (around line 95–115):**
```python
    try:
        pdf_bytes = generate_invoice_pdf(
            invoice_number=invoice_number,
            customer_name=customer["name"],
            amount=amount,
            items=items_data,
            org_name=org_name,
            customer_gstin=customer.get("gst_number", ""),
            customer_city=customer.get("city", "")
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{invoice_number}.pdf",
            caption=f"🧾 {invoice_number} — {customer['name']} — Rs.{amount:,.0f}"
        )
        pdf_sent = True
    except Exception as e:
        print(f"[PDF] Error: {e}")
        pdf_sent = False
```

**New PDF block:**
```python
    try:
        pdf_bytes = await generate_pdf(
            rows=items_data,
            title=f"Tax Invoice — {invoice_number}",
            org_name=org_name,
            doc_type="invoice",
            extra_context={
                "invoice_number": invoice_number,
                "customer_name": customer["name"],
                "customer_city": customer.get("city", ""),
                "customer_gstin": customer.get("gst_number", ""),
                "amount": amount,
                "gst_rate": 3.0,
                "due_date": (
                    __import__("datetime").date.today() +
                    __import__("datetime").timedelta(days=30)
                ).strftime("%d %b %Y"),
            }
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{invoice_number}.pdf",
            caption=f"🧾 {invoice_number} — {customer['name']} — Rs.{amount:,.0f}"
        )
        pdf_sent = True
    except Exception as e:
        print(f"[PDF] Error: {e}")
        pdf_sent = False
```

---

**Old PDF block in `send_dues_statement()` (around line 175–195):**
```python
    try:
        pdf_bytes = generate_dues_statement_pdf(
            customer_name=customer["name"],
            customer_city=customer.get("city", ""),
            customer_gstin=customer.get("gst_number", ""),
            invoices=invoices,
            total_outstanding=float(total),
            overdue_total=float(overdue_total),
            org_name=org_name
        )
        await send_document(...)
```

**New PDF block:**
```python
    try:
        pdf_bytes = await generate_pdf(
            rows=[dict(inv) for inv in invoices],
            title=f"Dues Statement — {customer['name']}",
            org_name=org_name,
            subtitle=f"As of {__import__('datetime').date.today().strftime('%d %b %Y')}",
            doc_type="statement",
            extra_context={
                "customer_name": customer["name"],
                "customer_city": customer.get("city", ""),
                "customer_gstin": customer.get("gst_number", ""),
                "total_outstanding": float(total),
                "overdue_total": float(overdue_total),
                "invoice_count": len(invoices),
            }
        )
        await send_document(...)
```

---

### 6B — `quotation.py`

**Old imports (line 7-8):**
```python
from app.services.quotation_pdf import generate_quotation_pdf
from app.services.whatsapp import send_document
```

**New imports:**
```python
from app.services.pdf_engine import generate_pdf
from app.services.whatsapp import send_document
```

---

**Old PDF block in `create_quotation()` (around line 130-155):**
```python
    try:
        pdf_bytes = generate_quotation_pdf(
            quotation_number=quotation_number,
            customer_name=customer["name"],
            metal_type=metal_type,
            weight_grams=weight_grams,
            design_code=design_code,
            rate_per_gram=rate_per_gram,
            making_charge_pct=making_pct,
            making_charges=making_charges,
            subtotal=subtotal,
            gst_pct=gst_pct,
            gst_amount=gst_amount,
            total_amount=total_amount,
            org_name=org_name,
            customer_city=customer.get("city", ""),
            valid_days=valid_days
        )
```

**New PDF block:**
```python
    try:
        pdf_bytes = await generate_pdf(
            rows=[],          # quotations have no data rows — all values are pre-computed
            title=f"Price Quotation — {quotation_number}",
            org_name=org_name,
            doc_type="quotation",
            extra_context={
                "quotation_number": quotation_number,
                "customer_name": customer["name"],
                "customer_city": customer.get("city", ""),
                "metal_type": metal_type.upper(),
                "weight_grams": weight_grams,
                "design_code": design_code or "Standard",
                "rate_per_gram": rate_per_gram,
                "making_charge_pct": making_pct,
                "metal_cost": round(weight_grams * rate_per_gram, 0),
                "making_charges": making_charges,
                "subtotal": subtotal,
                "gst_pct": gst_pct,
                "gst_amount": gst_amount,
                "total_amount": total_amount,
                "valid_days": valid_days,
                "valid_until": (
                    __import__("datetime").date.today() +
                    __import__("datetime").timedelta(days=valid_days)
                ).strftime("%d %b %Y"),
            }
        )
```

Same change for `generate_quotation_with_rate_update()` — identical pattern,
just different variable names for `making_pct` → `making_charge_pct`.

---

### 6C — `agent.py` — the `generate_pdf` tool in `_execute_tool`

The tool definition itself **stays exactly the same** (rows, title, subtitle parameters).
Only the implementation block changes:

**Old (around line 356-390):**
```python
    elif tool_name == "generate_pdf":
        from app.services.pdf_service import _generate_generic_pdf
        from app.services.whatsapp import send_document

        rows = tool_input.get("rows", [])
        title = tool_input.get("title", "Report")
        subtitle = tool_input.get("subtitle", "")

        if not rows:
            return "ERROR: No data to generate PDF from"

        try:
            org_row = await fetch_one("SELECT name FROM orgs WHERE id = $1", user["org_id"])
            org_name = org_row["name"] if org_row else user["org_name"]

            pdf_bytes = _generate_generic_pdf(
                title=title, subtitle=subtitle, rows=rows, org_name=org_name
            )
            await send_document(
                to=phone,
                pdf_bytes=pdf_bytes,
                filename=f"{title.replace(' ', '_')}.pdf",
                caption=f"📄 {title}"
            )
            return f"PDF_SENT: {title} ({len(rows)} rows)"
        except Exception as e:
            return f"ERROR generating PDF: {str(e)}"
```

**New:**
```python
    elif tool_name == "generate_pdf":
        from app.services.pdf_engine import generate_pdf as _gen_pdf
        from app.services.whatsapp import send_document

        rows     = tool_input.get("rows", [])
        title    = tool_input.get("title", "Report")
        subtitle = tool_input.get("subtitle", "")

        if not rows:
            return "ERROR: No data to generate PDF from"

        try:
            org_row  = await fetch_one("SELECT name FROM orgs WHERE id = $1", user["org_id"])
            org_name = org_row["name"] if org_row else user["org_name"]

            # Infer doc_type from the title so the LLM formats it appropriately.
            # The agent does not need to pass doc_type explicitly — the title is enough.
            title_lower = title.lower()
            if "invoice" in title_lower:
                doc_type = "invoice"
            elif "quotation" in title_lower or "quote" in title_lower:
                doc_type = "quotation"
            elif "statement" in title_lower or "dues" in title_lower:
                doc_type = "statement"
            elif "order" in title_lower:
                doc_type = "orders"
            else:
                doc_type = "report"

            pdf_bytes = await _gen_pdf(
                rows=rows,
                title=title,
                org_name=org_name,
                subtitle=subtitle,
                doc_type=doc_type,
            )
            safe_filename = title.replace(" ", "_").replace("/", "-")[:50] + ".pdf"
            await send_document(
                to=phone,
                pdf_bytes=pdf_bytes,
                filename=safe_filename,
                caption=f"📄 {title}"
            )
            return f"PDF_SENT: {title} ({len(rows)} rows)"

        except Exception as e:
            print(f"[PDF_ENGINE] Error: {e}")
            import traceback; traceback.print_exc()
            return f"ERROR generating PDF: {str(e)}"
```

---

## Part 7 — What The Deletion List Looks Like

After all changes above are applied, run:

```bash
# Should show ZERO results for each:
grep -rn "from app.services.pdf_service" app/
grep -rn "from app.services.quotation_pdf" app/
grep -rn "generate_invoice_pdf" app/
grep -rn "generate_dues_statement_pdf" app/
grep -rn "generate_quotation_pdf" app/
grep -rn "_generate_generic_pdf" app/
grep -rn "from fpdf import" app/
```

Then:
```bash
rm app/services/pdf_service.py
rm app/services/quotation_pdf.py
```

Remove from `requirements.txt`:
```
fpdf2    ← remove this line
```

Add to `requirements.txt`:
```
xhtml2pdf==0.2.17
```

---

## Part 8 — Test Scenarios After Migration

Run these in WhatsApp immediately after deploying to verify every PDF path works.

### 8A — Agent-initiated PDFs (from user requests)

```
give me all overdue invoices as PDF
```
Expected: LLM queries invoices WHERE status='overdue', calls generate_pdf with
doc_type="report" (inferred from title "Overdue Invoices Report"). PDF has table
with invoice_number, customer name, amount, due_date columns.

```
Sharma aur Agarwal ka dues statement PDF mein do
```
Expected: LLM queries invoices for both customers, calls generate_pdf with
doc_type="statement" (inferred from "Dues Statement" in title). PDF has aging
analysis, colour-coded rows (overdue = red, pending = yellow), totals block.

```
all ready orders ka PDF bana do
```
Expected: LLM queries orders WHERE status='ready', calls generate_pdf with
doc_type="orders". PDF has order number, customer, description, status emoji,
estimated amount. Summary row shows count.

```
low stock items report PDF
```
Expected: LLM queries inventory WHERE qty <= reorder_level, calls generate_pdf
with doc_type="report". PDF shows name, qty, reorder_level, units_to_reorder.
KEY INSIGHTS section: "X items critically low — immediate reorder required."

```
all customers with their credit limits as PDF
```
Expected: Generic report PDF with customer name, city, credit_limit columns.

### 8B — System-initiated PDFs (from accounting/quotation flows)

```
invoice Mehta Jewellers 45000
```
(After OTP/confirmation if applicable)
Expected: PDF generated via `create_invoice()` → `generate_pdf()` with
doc_type="invoice". Has BILL TO section, items table, GST breakdown, total,
payment terms.

```
quote Mehta 22kt 15g
```
Expected: PDF generated via `create_quotation()` → `generate_pdf()` with
doc_type="quotation". Has customer section, item details box, full price
breakdown (metal cost → making → subtotal → GST → TOTAL), validity note,
jewellery terms.

```
dues statement Sharma Gold House
```
(Via send_dues_statement adapter)
Expected: PDF with outstanding invoice table, total outstanding, overdue total,
aging analysis if multiple invoices.

### 8C — Multi-customer PDFs

```
give me invoice summary for Mehta Jewellers and Agarwal Ornaments as PDF
```
Expected: LLM queries invoices for both, calls generate_pdf. PDF shows
all invoices for both customers, grouped by customer name if LLM is smart enough.

```
top 5 customers by outstanding in PDF
```
Expected: Aggregate query → PDF showing customer name, city, total_outstanding,
invoice_count. Summary row: grand total.

### 8D — Edge cases

```
generate PDF for all stock items
```
Expected: Large table, all 10 inventory items, headers from column names
(sku → SKU, unit_price → Unit Price, reorder_level → Reorder Level).

```
daily sales report PDF
```
Expected: Agent queries invoices created today (or recent). PDF with whatever
columns come back. No hardcoded layout assumptions.

---

## Part 9 — How This Works for a New Industry Client

### Pharma client onboarded tomorrow

Their `invoices` table has:
```
prescription_number, drug_name, batch_number, expiry_date, quantity, mrp, discount, net_amount, gst_pct, total
```

User says: "give me pending invoice summary for Sharma Medicals as PDF"

The agent:
1. Queries `invoices WHERE status='pending' AND customer ILIKE '%Sharma%'`
2. Gets rows with `prescription_number, drug_name, batch_number, net_amount, total`
3. Calls `generate_pdf(rows, "Pending Invoices — Sharma Medicals", doc_type="report")`

The LLM:
1. Sees columns: prescription_number, drug_name, batch_number, net_amount, total
2. Generates HTML with table headers: Prescription #, Drug Name, Batch, Amount, Total
3. Formats ₹ amounts, adds row count, adds grand total row

PDF sent. **Zero code changes required for the pharma client.**

Same for hospital (patient_id, ward, procedure, doctor_name), IT (ticket_number, service_type,
hours, rate, total), any domain.

---

## Part 10 — Optional: Upgrade to WeasyPrint for Better Quality

When you want browser-quality PDF rendering:

**1. Add to Railway Variables:**
```
NIXPACKS_PKGS=cairo pango gobject-introspection glib libffi pkg-config
```

**2. Add to `requirements.txt`:**
```
weasyprint
```
Remove `xhtml2pdf`.

**3. In `pdf_engine.py`, change only `_html_to_pdf`:**
```python
def _html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()
```

**4. In `_build_html`, remove the xhtml2pdf compatibility notes from the prompt:**
Replace the XHTML2PDF COMPATIBILITY section in the LLM prompt with:
```
COMPATIBILITY:
- Standard modern HTML and CSS3 is fine
- Flexbox and grid layouts work
- Use @page rule for margins: @page { margin: 15mm; }
- External fonts are NOT available — use system fonts (Arial, Helvetica, sans-serif)
- No JavaScript
```

That's it. One function change. All callers are unaffected.

---

## Summary: What Changes, What Gets Deleted, What Stays

### DELETE (completely)
| File | Reason |
|------|--------|
| `app/services/pdf_service.py` | Replaced by pdf_engine.py |
| `app/services/quotation_pdf.py` | Replaced by pdf_engine.py |

### CREATE (new)
| File | What it does |
|------|-------------|
| `app/services/pdf_engine.py` | Universal LLM→HTML→PDF engine |

### CHANGE (minimal edits)
| File | Change |
|------|--------|
| `accounting.py` | Import + 2 function calls updated |
| `quotation.py` | Import + 2 function calls updated |
| `agent.py` | generate_pdf tool implementation updated |
| `requirements.txt` | fpdf2 → xhtml2pdf |

### UNTOUCHED (completely unchanged)
| Files |
|-------|
| `webhook.py`, `workflow_executor.py`, `crm.py`, `inventory.py`, `orders.py` |
| `admin.py`, `db.py`, `redis_client.py`, `identity.py`, `whatsapp.py` |
| All the DB tables, migrations, seed data |
| All the agent tool definitions (TOOLS list in agent.py) |

**Net result:** 590 lines of hardcoded layout code → 0.
One 200-line `pdf_engine.py` handles everything, for any industry, forever.
