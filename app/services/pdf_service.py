"""
OrchestrAI — Professional Invoice PDF Generator
Uses fpdf2. Returns PDF as bytes — no file saved to disk.
Blue color scheme: RGB(24, 95, 165) = #185FA5
"""
from fpdf import FPDF

# ── Brand Colors ──────────────────────────────────────
BLUE     = (24, 95, 165)
DARKTEXT = (26, 26, 46)
MUTED    = (100, 100, 120)
LIGHTBG  = (240, 245, 255)
WHITE    = (255, 255, 255)
BORDER   = (220, 228, 240)


# ── Amount In Words (Indian numbering) ───────────────
def _amount_in_words(amount: float) -> str:
    ones = [
        '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
        'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
        'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'
    ]
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty',
            'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def two(n):
        if n < 20:
            return ones[n]
        return tens[n // 10] + ((' ' + ones[n % 10]) if n % 10 else '')

    def three(n):
        if n >= 100:
            return ones[n // 100] + ' Hundred' + ((' ' + two(n % 100)) if n % 100 else '')
        return two(n)

    n = int(amount)
    if n == 0:
        return 'Zero Only'

    result = ''
    if n >= 10000000:
        result += three(n // 10000000) + ' Crore '
        n %= 10000000
    if n >= 100000:
        result += three(n // 100000) + ' Lakh '
        n %= 100000
    if n >= 1000:
        result += two(n // 1000) + ' Thousand '
        n %= 1000
    if n > 0:
        result += three(n)

    return 'Rupees ' + result.strip() + ' Only'


class InvoicePDF(FPDF):

    def header(self):
        pass  # Custom header drawn in generate_invoice_pdf

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', 'I', 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5,
            'Computer generated invoice. Powered by OrchestrAI | sales@aitamate.com',
            align='C')


def generate_invoice_pdf(
    invoice_number: str,
    customer_name: str,
    amount: float,
    items: list = None,
    org_name: str = 'Baanganga Gold And Diamond (I) Ltd.',
    customer_gstin: str = '',
    customer_city: str = '',
    gst_rate: float = 3.0
) -> bytes:
    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(14, 14, 14)

    W = 182
    L = 14

    from datetime import datetime, timedelta
    today = datetime.now()
    due   = today + timedelta(days=30)

    # ── HEADER ───────────────────────────────────────────
    y = 14

    # Company name — left
    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', 'B', 20)
    pdf.set_text_color(*BLUE)
    pdf.cell(100, 10, org_name, align='L')

    # TAX INVOICE badge — right
    pdf.set_fill_color(*BLUE)
    pdf.set_xy(142, y)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(*WHITE)
    pdf.cell(54, 10, 'TAX INVOICE', fill=True, align='C')

    # Tagline — below company name
    pdf.set_xy(L, y + 11)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(100, 4.5, 'Powered by OrchestrAI   |   Automate With AI', align='L')

    # Invoice meta — below badge
    meta = [
        ('Invoice No:', invoice_number),
        ('Date:', today.strftime('%d %b %Y')),
        ('Due Date:', due.strftime('%d %b %Y')),
    ]
    my = y + 11
    for label, value in meta:
        pdf.set_xy(142, my)
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(28, 5, label, align='L')
        pdf.set_font('Helvetica', 'B', 8.5)
        pdf.set_text_color(*DARKTEXT)
        pdf.cell(26, 5, value, align='R')
        my += 5.5

    # Blue divider
    y_div = y + 27
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, y_div, L + W, y_div)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(*BORDER)

    # ── BILL TO ───────────────────────────────────────────
    y = y_div + 7

    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_text_color(*BLUE)
    pdf.cell(W, 4.5, 'BILL TO', align='L')

    y += 6
    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W, 7, customer_name, align='L')

    y += 8
    sub_lines = []
    if customer_city:
        sub_lines.append(customer_city)
    if customer_gstin:
        sub_lines.append(f'GSTIN: {customer_gstin}')
    if not sub_lines:
        sub_lines.append('Customer details on file')

    for line in sub_lines:
        pdf.set_xy(L, y)
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(W, 5, line, align='L')
        y += 5

    y += 6

    # ── ITEMS TABLE ───────────────────────────────────────
    # Column widths: Desc, Qty, Unit Price, GST, Total
    cw     = [80, 14, 30, 24, 34]
    aligns = ['L', 'C', 'R', 'R', 'R']

    # Header row
    pdf.set_xy(L, y)
    pdf.set_fill_color(*BLUE)
    pdf.set_text_color(*WHITE)
    pdf.set_font('Helvetica', 'B', 8.5)
    for col, w, a in zip(
        ['Description', 'Qty', 'Unit Price', f'GST {gst_rate:.0f}%', 'Total'],
        cw, aligns
    ):
        pdf.cell(w, 8.5, col, fill=True, align=a, border=0)
    pdf.ln(8.5)

    # Items
    if not items:
        subtotal   = round(amount / (1 + gst_rate / 100), 2)
        gst_amount = round(amount - subtotal, 2)
        items = [{
            'description': 'As per order',
            'qty': 1,
            'unit_price': subtotal,
            'gst': gst_amount,
            'total': amount
        }]

    row_fill = False
    for item in items:
        pdf.set_fill_color(*LIGHTBG) if row_fill else pdf.set_fill_color(*WHITE)
        pdf.set_text_color(*DARKTEXT)
        pdf.set_font('Helvetica', '', 8.5)
        vals = [
            str(item.get('description', 'Item'))[:50],
            str(item.get('qty', 1)),
            f"Rs.{float(item.get('unit_price', 0)):,.0f}",
            f"Rs.{float(item.get('gst', 0)):,.0f}",
            f"Rs.{float(item.get('total', amount)):,.0f}",
        ]
        for val, w, a in zip(vals, cw, aligns):
            pdf.cell(w, 8, val, fill=True, align=a, border=0)
        pdf.ln(8)
        row_fill = not row_fill

    # Bottom border
    pdf.set_draw_color(*BORDER)
    pdf.line(L, pdf.get_y(), L + W, pdf.get_y())

    # ── TOTALS (right-aligned block) ──────────────────────
    subtotal_val = round(amount / (1 + gst_rate / 100), 2)
    gst_val      = round(amount - subtotal_val, 2)

    ty = pdf.get_y() + 5
    tx = L + 92   # totals block x start
    tw = W - 92   # totals block width = 90

    def _trow(label, value, highlight=False):
        nonlocal ty
        pdf.set_xy(tx, ty)
        if highlight:
            pdf.set_fill_color(*BLUE)
            pdf.set_text_color(*WHITE)
            pdf.set_font('Helvetica', 'B', 9.5)
            pdf.cell(tw, 9, label, fill=True, align='L', border=0)
            pdf.set_xy(tx, ty)
            pdf.cell(tw, 9, value, fill=True, align='R', border=0)
            ty += 9
        else:
            pdf.set_font('Helvetica', '', 8.5)
            pdf.set_text_color(*MUTED)
            pdf.cell(55, 6.5, label, align='L')
            pdf.set_text_color(*DARKTEXT)
            pdf.cell(tw - 55, 6.5, value, align='R')
            pdf.set_draw_color(*BORDER)
            pdf.line(tx, ty + 6.5, tx + tw, ty + 6.5)
            ty += 7

    _trow('Subtotal', f'Rs.{subtotal_val:,.0f}')
    _trow(f'GST @ {gst_rate:.0f}%', f'Rs.{gst_val:,.0f}')
    _trow('Discount', 'Rs.0')
    ty += 2
    _trow('TOTAL AMOUNT', f'Rs.{amount:,.0f}', highlight=True)

    # ── AMOUNT IN WORDS ───────────────────────────────────
    wy = ty + 8
    pdf.set_xy(L, wy)
    pdf.set_fill_color(*LIGHTBG)
    pdf.rect(L, wy, W, 9, style='F')
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, wy, L, wy + 9)
    pdf.set_line_width(0.2)
    pdf.set_xy(L + 3, wy + 2)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(38, 5, 'Amount in words:', align='L')
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W - 41, 5, _amount_in_words(amount), align='L')

    # ── FOOTER ────────────────────────────────────────────
    fy = wy + 16
    pdf.set_draw_color(*BORDER)
    pdf.line(L, fy, L + W, fy)

    # Terms (left)
    terms = [
        ('Terms & Conditions:', True),
        ('1. Payment due within 30 days of invoice date.', False),
        ('2. Late payment attracts 2% interest per month.', False),
        ('3. Subject to Mumbai jurisdiction only.', False),
        ('4. Goods once sold will not be taken back.', False),
    ]
    ty2 = fy + 5
    for text, bold in terms:
        pdf.set_xy(L, ty2)
        pdf.set_font('Helvetica', 'B' if bold else '', 7.5)
        pdf.set_text_color(*BLUE if bold else MUTED)
        pdf.cell(100, 4.5, text, align='L')
        ty2 += 4.5

    # Signature (right)
    pdf.set_xy(140, fy + 5)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(56, 4, f'For  {org_name}', align='C')

    # Stamp box
    # Calculations
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.5)
    pdf.rect(148, fy + 10, 40, 13)
    pdf.set_xy(148, fy + 13)
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_text_color(*BLUE)
    pdf.cell(40, 4, org_name.upper(), align='C')

    # Signature line
    pdf.set_draw_color(*DARKTEXT)
    pdf.set_line_width(0.3)
    pdf.line(143, fy + 28, 195, fy + 28)
    pdf.set_xy(140, fy + 29)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(56, 4, 'Authorised Signatory', align='C')

    return bytes(pdf.output())


def generate_dues_statement_pdf(
    customer_name: str,
    invoices: list,
    total_outstanding: float,
    overdue_total: float,
    org_name: str = 'Baanganga Gold And Diamond (I) Ltd.',
    customer_city: str = '',
    customer_gstin: str = ''
) -> bytes:
    """Generate PDF statement of outstanding invoices for a customer."""
    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(14, 14, 14)

    W = 182
    L = 14

    from datetime import datetime
    today = datetime.now()

    # ── HEADER ───────────────────────────────────────────
    y = 14

    # Company name — left
    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', 'B', 20)
    pdf.set_text_color(*BLUE)
    pdf.cell(100, 10, org_name, align='L')

    # STATEMENT badge — right
    pdf.set_fill_color(*BLUE)
    pdf.set_xy(142, y)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(*WHITE)
    pdf.cell(54, 10, 'DUES STATEMENT', fill=True, align='C')

    # Tagline — below company name
    pdf.set_xy(L, y + 11)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(100, 4.5, 'Powered by OrchestrAI   |   Automate With AI', align='L')

    # Statement meta — below badge
    meta = [
        ('Statement Date:', today.strftime('%d %b %Y')),
        ('Customer:', customer_name[:25]),
        ('Total Outstanding:', f'Rs.{total_outstanding:,.0f}'),
    ]
    my = y + 11
    for label, value in meta:
        pdf.set_xy(142, my)
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(28, 5, label, align='L')
        pdf.set_font('Helvetica', 'B', 8.5)
        pdf.set_text_color(*DARKTEXT)
        pdf.cell(26, 5, value, align='R')
        my += 5.5

    # Blue divider
    y_div = y + 27
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, y_div, L + W, y_div)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(*BORDER)

    # ── BILL TO ───────────────────────────────────────────
    y = y_div + 7

    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_text_color(*BLUE)
    pdf.cell(W, 4.5, 'CUSTOMER DETAILS', align='L')

    y += 6
    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W, 7, customer_name, align='L')

    y += 8
    sub_lines = []
    if customer_city:
        sub_lines.append(customer_city)
    if customer_gstin:
        sub_lines.append(f'GSTIN: {customer_gstin}')
    if not sub_lines:
        sub_lines.append('Customer details on file')

    for line in sub_lines:
        pdf.set_xy(L, y)
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(W, 5, line, align='L')
        y += 5

    y += 6

    # ── INVOICES TABLE ───────────────────────────────────────
    # Column widths: Invoice, Date, Due Date, Amount, Status
    cw     = [35, 28, 28, 45, 46]
    aligns = ['L', 'C', 'C', 'R', 'C']

    # Header row
    pdf.set_xy(L, y)
    pdf.set_fill_color(*BLUE)
    pdf.set_text_color(*WHITE)
    pdf.set_font('Helvetica', 'B', 8.5)
    for col, w, a in zip(
        ['Invoice #', 'Date', 'Due Date', 'Amount', 'Status'],
        cw, aligns
    ):
        pdf.cell(w, 8.5, col, fill=True, align=a, border=0)
    pdf.ln(8.5)

    # Items
    row_fill = False
    for inv in invoices:
        pdf.set_fill_color(*LIGHTBG) if row_fill else pdf.set_fill_color(*WHITE)
        pdf.set_text_color(*DARKTEXT)
        pdf.set_font('Helvetica', '', 8.5)
        
        inv_date = inv.get('created_at')
        if inv_date and hasattr(inv_date, 'strftime'):
            inv_date = inv_date.strftime('%d %b %Y')
        else:
            inv_date = 'N/A'
        
        due_date = inv.get('due_date')
        if due_date and hasattr(due_date, 'strftime'):
            due_date = due_date.strftime('%d %b %Y')
        else:
            due_date = 'N/A'
        
        status = inv.get('status', 'pending').upper()
        status_color = DARKTEXT if status == 'PENDING' else (200, 50, 50) if status == 'OVERDUE' else DARKTEXT
        
        vals = [
            str(inv.get('invoice_number', '')),
            inv_date,
            due_date,
            f"Rs.{float(inv.get('amount', 0)):,.0f}",
            status,
        ]
        
        for i, (val, w, a) in enumerate(zip(vals, cw, aligns)):
            if i == 4:  # Status column
                pdf.set_text_color(*status_color)
            else:
                pdf.set_text_color(*DARKTEXT)
            pdf.cell(w, 8, val, fill=True, align=a, border=0)
        pdf.ln(8)
        row_fill = not row_fill

    # Bottom border
    pdf.set_draw_color(*BORDER)
    pdf.line(L, pdf.get_y(), L + W, pdf.get_y())

    # ── TOTALS (right-aligned block) ──────────────────────
    ty = pdf.get_y() + 5
    tx = L + 92
    tw = W - 92

    def _trow(label, value, highlight=False):
        nonlocal ty
        pdf.set_xy(tx, ty)
        if highlight:
            pdf.set_fill_color(*BLUE)
            pdf.set_text_color(*WHITE)
            pdf.set_font('Helvetica', 'B', 9.5)
            pdf.cell(tw, 9, label, fill=True, align='L', border=0)
            pdf.set_xy(tx, ty)
            pdf.cell(tw, 9, value, fill=True, align='R', border=0)
            ty += 9
        else:
            pdf.set_font('Helvetica', '', 8.5)
            pdf.set_text_color(*MUTED)
            pdf.cell(55, 6.5, label, align='L')
            pdf.set_text_color(*DARKTEXT)
            pdf.cell(tw - 55, 6.5, value, align='R')
            pdf.set_draw_color(*BORDER)
            pdf.line(tx, ty + 6.5, tx + tw, ty + 6.5)
            ty += 7

    _trow('Total Outstanding', f'Rs.{total_outstanding:,.0f}')
    _trow('Overdue Amount', f'Rs.{overdue_total:,.0f}')
    ty += 2
    _trow('GRAND TOTAL', f'Rs.{total_outstanding:,.0f}', highlight=True)

    # ── AMOUNT IN WORDS ───────────────────────────────────
    wy = ty + 8
    pdf.set_xy(L, wy)
    pdf.set_fill_color(*LIGHTBG)
    pdf.rect(L, wy, W, 9, style='F')
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, wy, L, wy + 9)
    pdf.set_line_width(0.2)
    pdf.set_xy(L + 3, wy + 2)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(38, 5, 'Amount in words:', align='L')
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W - 41, 5, _amount_in_words(total_outstanding), align='L')

    # ── FOOTER ────────────────────────────────────────────
    fy = wy + 16
    pdf.set_draw_color(*BORDER)
    pdf.line(L, fy, L + W, fy)

    # Terms (left)
    terms = [
        ('Terms & Conditions:', True),
        ('1. Please pay outstanding amount at the earliest.', False),
        ('2. Late payment attracts 2% interest per month.', False),
        ('3. Contact us for any discrepancies.', False),
    ]
    ty2 = fy + 5
    for text, bold in terms:
        pdf.set_xy(L, ty2)
        pdf.set_font('Helvetica', 'B' if bold else '', 7.5)
        pdf.set_text_color(*BLUE if bold else MUTED)
        pdf.cell(100, 4.5, text, align='L')
        ty2 += 4.5

    # Signature (right)
    pdf.set_xy(140, fy + 5)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(56, 4, f'For  {org_name}', align='C')

    # Stamp box
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.5)
    pdf.rect(148, fy + 10, 40, 13)
    pdf.set_xy(148, fy + 13)
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_text_color(*BLUE)
    pdf.cell(40, 4, org_name.upper(), align='C')

    # Signature line
    pdf.set_draw_color(*DARKTEXT)
    pdf.set_line_width(0.3)
    pdf.line(143, fy + 28, 195, fy + 28)
    pdf.set_xy(140, fy + 29)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(56, 4, 'Authorised Signatory', align='C')

    return bytes(pdf.output())