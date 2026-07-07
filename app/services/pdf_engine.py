"""
pdf_engine.py — LLM-powered PDF generator using WeasyPrint.

When a workflow has pdf_config.render_instructions, those instructions drive the layout.
When not, the hardcoded doc_type branches below are used as defaults.
This way existing behaviour is preserved and new DB-configured workflows get custom layouts.
"""
import json
import os
from io import BytesIO
from datetime import datetime
from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BRAND_BLUE   = "#185FA5"
BRAND_LIGHT  = "#EEF4FB"
BRAND_DARK   = "#1A1A2E"
BRAND_MUTED  = "#6B7280"

RISK_COLORS = {
    "HIGH":     {"bg": "#B71C1C", "row": "#FFEBEE", "text": "#FFFFFF"},
    "MEDIUM":   {"bg": "#E65100", "row": "#FFF3E0", "text": "#FFFFFF"},
    "LOW":      {"bg": "#2E7D32", "row": "#F1F8E9", "text": "#FFFFFF"},
    "UPCOMING": {"bg": "#1565C0", "row": "#E3F2FD", "text": "#FFFFFF"},
}


async def generate_pdf(
    rows: list,
    title: str,
    org_name: str,
    subtitle: str = "",
    doc_type: str = "report",
    extra_context: dict = None,
    pdf_config: dict = None,
) -> bytes:
    """Generate a professional A4 PDF. Returns bytes. Raises on error."""
    html = await _build_html(
        rows=rows,
        title=title,
        org_name=org_name,
        subtitle=subtitle,
        doc_type=doc_type,
        extra_context=extra_context or {},
        pdf_config=pdf_config or {},
    )
    return _html_to_pdf(html)


def _build_doctype_instructions(doc_type: str, risk_mode: bool,
                                 extra_context: dict, today_long: str,
                                 org_name: str, primary: str, light_bg: str) -> str:
    """Build the doc-type specific section of the PDF prompt (default/fallback path)."""

    if risk_mode:
        return f"""
── AGING REPORT (risk_bucket data detected) ──

The rows already have `risk_bucket` (HIGH / MEDIUM / LOW / UPCOMING) and
`days_overdue` pre-computed. Use this to render THREE colour-coded sections.

STRUCTURE:
1. EXECUTIVE SUMMARY BOX (light blue bg, rounded corners, 8px padding):
   Show grand_total, high_risk_total, medium_risk_total from extra_context.
   If top_debtors in extra_context, list them here.
   Format: "Total Outstanding: Rs.X | High Risk: Rs.X | Medium Risk: Rs.X"

2. THREE SECTION BLOCKS (render only non-empty buckets):

   HIGH RISK — Over 90 Days
   Header row bg: #B71C1C, white text, bold
   Data rows bg: #FFEBEE (light red)
   Show: Invoice # | Customer | Amount | Days Overdue | Status

   MEDIUM RISK — 31 to 90 Days
   Header row bg: #E65100, white text, bold
   Data rows bg: #FFF3E0 (light orange)

   LOW RISK — Up to 30 Days
   Header row bg: #2E7D32, white text, bold
   Data rows bg: #F1F8E9 (light green)

   UPCOMING — Not Yet Due
   Header row bg: {primary}, white text, bold
   Data rows bg: {light_bg}

3. KEY ACTIONS SECTION (below all tables):
   Heading: "Key Actions" in {primary} bold
   Bullet list of 3-5 specific, actionable items based on the data.
   Use the top_debtors from extra_context if available.
"""

    doctype_map = {
        "report": f"""
── REPORT (multi-row table) ──
- Header row bg: {primary}, white text. Alternating row stripes (white / {light_bg})
- All numeric amount/total columns: right-align, Indian comma formatting (Rs.X,XX,XXX)
- Summary row at bottom (bold, light blue bg): row count + SUM of any amount/total column
- KEY INSIGHTS section: 2-4 bullet points synthesising notable patterns in the data
""",
        "invoice": f"""
── TAX INVOICE ──
- TOP RIGHT badge: <div style="background:{primary};color:#fff;padding:4px 12px;font-weight:700;display:inline-block">TAX INVOICE</div>
- BILL TO section (left): customer_name, city, GSTIN from extra_context
- Invoice meta (right): Invoice #, Date, Due Date, STATUS from extra_context
  Status badge colours: paid=#16a34a, overdue=#dc2626, pending=#f59e0b
- Items table: Description | Qty | Unit Price (ex-GST) | GST | Total
- Totals block (right-align, 40% width):
    Subtotal  : use subtotal from extra_context if present; else = amount / 1.03 rounded
    GST       : use gst_amount from extra_context if present; else = amount - subtotal
    TOTAL     : use total_amount or amount from extra_context
    CRITICAL: NEVER add GST on top of amount. amount IS the GST-inclusive total.
- TOTAL in words (Indian number system)
- Payment terms: "Payment due within 30 days."
""",
        "quotation": f"""
── PRICE QUOTATION — GOLD/AMBER colour scheme ──

COLOUR SCHEME: Primary #B8860B, Light bg #FFFBEB, Accent #C9A84C, Text #3B2800
HEADER OVERRIDE: Use #B8860B for header rule and org name. Sub-label: "Price Quotation"

BADGE (top right, PROMINENT):
  background:#B8860B, white text, bold, font-size:13pt, letter-spacing:1px
  Text: PRICE QUOTATION

DOCUMENT META (two-column table):
  Left (40%): "PREPARED FOR:", customer_name bold 13pt, city, GSTIN muted 10pt
  Right (60%): Quote # from extra_context quotation_number (bold)
               Date: {today_long}
               Valid Until: extra_context valid_until (RED bold if within 2 days)

DESIGN DETAILS CARD:
  Full-width box, background #FFFBEB, border 2px solid #C9A84C, border-radius 8px:
  Heading "DESIGN DETAILS" #B8860B bold.
  Left: Design Code (monospace bold), Design Name (bold)
  Right: Metal Type, Weight (grams)

PRICING BREAKDOWN TABLE (right-aligned, width 55%):
  Border: 1px solid #C9A84C
  Row 1: Metal Cost      | Rs.X from extra_context metal_cost
  Row 2: Making Charges  | Rs.X from extra_context making_charges
         sub-note: making_charge_pct% of metal cost (muted 9pt)
  Row 3: Subtotal        | Rs.X from extra_context subtotal
  Row 4: GST (gst_pct%)  | Rs.X from extra_context gst_amount
  TOTAL ROW bold background:#B8860B white text 13pt | Rs.X from total_amount

ALL values from extra_context. Do NOT recalculate. Indian comma formatting.

VALIDITY BOX: background #FFF3CD, border-left 4px solid #B8860B
  Warning about validity period and rate fluctuation.

TERMS: advance payment, weight variance +-5%, making charges fixed, GST as applicable.

ACCEPTANCE SECTION: Customer signature + date (left), Authorised Signatory (right)
FOOTER NOTE (red small): "This is a QUOTATION, not a Tax Invoice."
""",
        "statement": """
── DUES / ACCOUNT STATEMENT ──
- Heading: ACCOUNT STATEMENT (bold, large)
- Customer block: name, city, GSTIN, total_outstanding from extra_context
- Invoices table with colour-coded rows: overdue=light red, pending=light yellow
  Columns: Invoice # | Date | Due Date | Amount | Status | Days Overdue
- AGING ANALYSIS box: 0-30 days, 31-90 days, >90 days amounts
- Terms: "Please clear outstanding at the earliest."
""",
        "orders": """
── PRODUCTION ORDERS ──
- Orders table: Order # | Customer | Description | Metal | Status | Est. Amount
- STATUS column coloured cells:
    confirmed=light blue, in_production=light amber, quality_check=light purple,
    ready=light green (highlight boldly), delivered=grey
- Summary row: total orders, count by status
""",
    }

    return doctype_map.get(doc_type, """
── GENERIC REPORT ──
Clean table with blue header, alternating stripes, summary row.
""")


async def _build_html(rows, title, org_name, subtitle, doc_type,
                       extra_context, pdf_config=None) -> str:
    today      = datetime.now().strftime("%d %b %Y")
    today_long = datetime.now().strftime("%d %B %Y")

    pdf_config = pdf_config or {}
    render_instructions = pdf_config.get("render_instructions")
    theme     = pdf_config.get("theme") or {}
    primary   = theme.get("primary",  BRAND_BLUE)
    light_bg  = theme.get("light_bg", BRAND_LIGHT)
    text_col  = theme.get("text",     BRAND_DARK)
    muted_col = theme.get("muted",    BRAND_MUTED)

    data_for_prompt = rows[:100]
    trunc_note = f"\n(Note: showing first 100 of {len(rows)} rows)" if len(rows) > 100 else ""
    data_json  = json.dumps(data_for_prompt, default=str, indent=2)
    ctx_json   = json.dumps(extra_context,   default=str, indent=2)

    has_risk_buckets = any("risk_bucket" in r for r in data_for_prompt)
    has_days_overdue = any("days_overdue" in r for r in data_for_prompt)
    risk_mode = (has_risk_buckets or has_days_overdue) and doc_type not in ("invoice", "quotation")

    # Choose layout instructions: DB-configured (new path) vs hardcoded defaults (legacy path)
    if render_instructions:
        layout_section = f"""===== WORKFLOW-CONFIGURED LAYOUT =====
(These instructions override the defaults — follow them exactly.)
{render_instructions}
"""
    else:
        layout_section = f"""===== DOC-TYPE SPECIFIC INSTRUCTIONS =====
{_build_doctype_instructions(doc_type, risk_mode, extra_context, today_long, org_name, primary, light_bg)}
"""

    # Build canonical totals block — explicit values to prevent the LLM from
    # guessing or recalculating amounts that are already correct
    canonical_keys  = ("subtotal", "gst_amount", "total_amount", "grand_total", "amount",
                       "metal_cost", "making_charges")
    canonical_lines = [
        f"  {k} = {extra_context[k]}"
        for k in canonical_keys
        if extra_context.get(k) is not None
    ]
    if canonical_lines:
        canonical_block = (
            "===== CANONICAL TOTALS — use these EXACT values verbatim, never recalculate =====\n"
            + "\n".join(canonical_lines)
            + "\n===== END CANONICAL TOTALS ====="
        )
    else:
        canonical_block = (
            "===== NOTE: no pre-computed total fields supplied. "
            "Derive totals ONLY by summing the per-row values in DATA above — "
            "do not assume a tax rate or invent a formula. ====="
        )

    prompt = f"""You are generating a professional PDF document for a business using WeasyPrint.
WeasyPrint supports full CSS3 including flexbox, border-radius, and proper Unicode.

===== DOCUMENT DETAILS =====
Organization  : {org_name}
Document Type : {doc_type}
Title         : {title}
Subtitle      : {subtitle or "(none)"}
Date          : {today_long}
Total Rows    : {len(rows)}{trunc_note}

===== DATA =====
{data_json}

===== PRE-COMPUTED CONTEXT =====
(Use these values directly. Do NOT recalculate from the rows above.)
{ctx_json}

{canonical_block}

===== FONTS AND COLORS =====
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  body {{ font-family: 'Inter', 'Noto Sans', 'DejaVu Sans', Arial, sans-serif; font-size: 11pt; color: {text_col}; }}
  @page {{ size: A4; margin: 12mm 15mm 15mm 15mm; }}
</style>
Primary: {primary} | Light bg: {light_bg} | Text: {text_col} | Muted: {muted_col}

CRITICAL — Use ONLY "Rs." for currency, NOT the ₹ symbol.

===== ALWAYS INCLUDE =====
1. HEADER BLOCK (table-based, full width):
   Left: org name bold {primary} 18pt | doc type label 11pt muted
   Right: date right-aligned | subtitle if provided
2. <hr style="border:2px solid {primary}; margin:8px 0"> below header
3. FOOTER: "Generated by OrchestrAI on {today}" (small, muted, bottom)

{layout_section}

===== WEASYPRINT COMPATIBILITY =====
- Table-based layouts only — NO CSS float
- width="100%" on all tables + explicit column widths
- No position:fixed/absolute, no transform, no CSS variables (--name)
- Flexbox OK. border-radius OK. box-shadow OK. calc() OK.
- Use <br/> not <br>. Font sizes in pt units.

===== OUTPUT =====
Return ONLY complete HTML starting with <!DOCTYPE html>.
No markdown fences. No explanation. No preamble.
"""

    response = await _client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )

    html = response.choices[0].message.content.strip()
    if html.startswith("```"):
        lines = html.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        html  = "\n".join(lines[start:end]).strip()

    return html


def _html_to_pdf(html: str) -> bytes:
    """WeasyPrint: HTML string → PDF bytes. Raises ValueError on failure."""
    from weasyprint import HTML
    try:
        buf = BytesIO()
        HTML(string=html).write_pdf(buf)
        return buf.getvalue()
    except Exception as e:
        raise ValueError(f"WeasyPrint conversion failed: {e}")
