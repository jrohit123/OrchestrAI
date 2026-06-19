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
    org_name: str = 'ShreeJewels Pvt Ltd',
    customer_gstin: str = '',
    customer_address: str = '',
    gst_rate: float = 3.0
) -> bytes:
    """
    Generate professional invoice PDF.
    Returns bytes — upload directly to WhatsApp media API.
    """
    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(14, 14, 14)

    W = 182  # usable width (210 - 28)
    L = 14   # left margin
    R = L + W

    # ── HEADER — Company (left) + Invoice Badge (right) ──
    y0 = 14

    # Company name
    pdf.set_xy(L, y0)
    pdf.set_font('Helvetica', 'B', 19)
    pdf.set_text_color(*BLUE)
    pdf.cell(110, 9, org_name, align='L')

    # Invoice badge (right)
    pdf.set_fill_color(*BLUE)
    pdf.set_xy(140, y0)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(*WHITE)
    pdf.cell(56, 10, 'TAX INVOICE', fill=True, align='C')

    # Company tagline
    pdf.set_xy(L, y0 + 9)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(110, 5, 'Powered by OrchestrAI   |   Automate With AI', align='L')

    # Invoice meta (right of badge)
    from datetime import datetime, timedelta
    today = datetime.now()
    due   = today + timedelta(days=30)

    pdf.set_xy(140, y0 + 11)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(26, 5, 'Invoice No:', align='L')
    pdf.set_text_color(*DARKTEXT)
    pdf.set_font('Helvetica', 'B', 8.5)
    pdf.cell(30, 5, invoice_number, align='R')

    pdf.set_xy(140, y0 + 16)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(26, 5, 'Date:', align='L')
    pdf.set_text_color(*DARKTEXT)
    pdf.set_font('Helvetica', 'B', 8.5)
    pdf.cell(30, 5, today.strftime('%d %b %Y'), align='R')

    pdf.set_xy(140, y0 + 21)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(26, 5, 'Due Date:', align='L')
    pdf.set_text_color(*DARKTEXT)
    pdf.set_font('Helvetica', 'B', 8.5)
    pdf.cell(30, 5, due.strftime('%d %b %Y'), align='R')

    # Company address
    pdf.set_xy(L, y0 + 14)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MUTED)
    addr_lines = [
        '42, Zaveri Bazaar, Mumbai - 400 002',
        'GSTIN: 27AABCS1234A1ZX   |   PAN: AABCS1234A',
        'Tel: +91 98765 43210   |   sales@aitamate.com'
    ]
    for line in addr_lines:
        pdf.cell(120, 4.5, line, align='L')
        pdf.ln(4.5)

    # Blue divider line
    y_div = y0 + 30
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, y_div, R, y_div)
    pdf.set_line_width(0.2)

    # ── BILL TO + PAYMENT INFO ──
    y1 = y_div + 6

    # BILL TO label
    pdf.set_xy(L, y1)
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_text_color(*BLUE)
    pdf.cell(90, 4, 'BILL TO', align='L')

    # PAYMENT INFO label
    pdf.set_xy(L + 95, y1)
    pdf.set_text_color(*BLUE)
    pdf.cell(87, 4, 'PAYMENT DETAILS', align='L')

    # Customer name
    pdf.set_xy(L, y1 + 5)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(90, 6, customer_name, align='L')

    # Customer details
    pdf.set_xy(L, y1 + 12)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MUTED)
    c_addr = customer_address or 'Address on file'
    c_gst  = customer_gstin or 'GSTIN: Provided separately'
    for line in [c_addr, c_gst]:
        pdf.cell(90, 4.2, line, align='L')
        pdf.ln(4.2)

    # Payment details (right column)
    pdf.set_xy(L + 95, y1 + 5)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MUTED)
    pay_lines = [
        'Bank: HDFC Bank Ltd',
        'A/C: 50100123456789',
        'IFSC: HDFC0001234',
        'Mode: NEFT / RTGS / UPI',
    ]
    for line in pay_lines:
        pdf.cell(87, 4.5, line, align='L')
        pdf.ln(4.5)

    # ── ITEMS TABLE ──
    y2 = y1 + 30

    # Column widths
    cw = [78, 14, 28, 22, 30]  # Desc, Qty, Unit Price, GST, Total

    # Table header
    pdf.set_xy(L, y2)
    pdf.set_fill_color(*BLUE)
    pdf.set_text_color(*WHITE)
    pdf.set_font('Helvetica', 'B', 8.5)
    headers = ['Description', 'Qty', 'Unit Price', f'GST {gst_rate:.0f}%', 'Total']
    aligns  = ['L', 'C', 'R', 'R', 'R']
    for i, (h, w, a) in enumerate(zip(headers, cw, aligns)):
        pdf.cell(w, 8, h, fill=True, align=a, border=0)
    pdf.ln(8)

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

        desc   = str(item.get('description', 'Item'))[:52]
        qty    = str(item.get('qty', 1))
        up     = f"Rs.{float(item.get('unit_price', 0)):,.0f}"
        gst_v  = f"Rs.{float(item.get('gst', 0)):,.0f}"
        tot    = f"Rs.{float(item.get('total', amount)):,.0f}"

        row_data = [desc, qty, up, gst_v, tot]
        for val, w, a in zip(row_data, cw, aligns):
            pdf.cell(w, 7.5, val, fill=True, align=a, border=0)
        pdf.ln(7.5)
        row_fill = not row_fill

    # Table bottom border
    pdf.set_draw_color(*BORDER)
    pdf.line(L, pdf.get_y(), R, pdf.get_y())

    # ── TOTALS BOX (right aligned) ──
    y3 = pdf.get_y() + 6
    subtotal_val   = round(amount / (1 + gst_rate / 100), 2)
    gst_val        = round(amount - subtotal_val, 2)
    tx = L + 95  # totals start x

    def total_row(label, value, bold=False, highlight=False):
        nonlocal y3
        if highlight:
            pdf.set_fill_color(*BLUE)
            pdf.set_xy(tx, y3)
            pdf.cell(87, 8, '', fill=True)
            pdf.set_xy(tx, y3)
            pdf.set_font('Helvetica', 'B', 9.5)
            pdf.set_text_color(*WHITE)
            pdf.cell(55, 8, label, align='L')
            pdf.cell(32, 8, value, align='R')
        else:
            pdf.set_xy(tx, y3)
            pdf.set_font('Helvetica', 'B' if bold else '', 8.5)
            pdf.set_text_color(*MUTED)
            pdf.cell(55, 6, label, align='L')
            pdf.set_text_color(*DARKTEXT)
            pdf.cell(32, 6, value, align='R')
            pdf.set_draw_color(*BORDER)
            pdf.line(tx, y3 + 6, tx + 87, y3 + 6)
        y3 += 8 if highlight else 6.5

    total_row('Subtotal', f'Rs.{subtotal_val:,.0f}')
    total_row(f'GST @ {gst_rate:.0f}%', f'Rs.{gst_val:,.0f}')
    total_row('Discount', 'Rs.0')
    y3 += 2
    total_row('TOTAL AMOUNT', f'Rs.{amount:,.0f}', highlight=True)

    # ── AMOUNT IN WORDS ──
    y4 = y3 + 8
    pdf.set_xy(L, y4)
    pdf.set_fill_color(*LIGHTBG)
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.rect(L, y4, W, 9, style='F')
    pdf.line(L, y4, L, y4 + 9)
    pdf.set_line_width(0.2)

    pdf.set_xy(L + 3, y4 + 1.5)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(40, 5, 'Amount in words:', align='L')
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W - 43, 5, _amount_in_words(amount), align='L')

    # ── FOOTER — Terms + Signature ──
    y5 = y4 + 16
    pdf.set_draw_color(*BORDER)
    pdf.line(L, y5, R, y5)

    pdf.set_xy(L, y5 + 5)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    terms = [
        'Terms & Conditions:',
        '1. Payment due within 30 days of invoice date.',
        '2. Late payment attracts 2% interest per month.',
        '3. Subject to Mumbai jurisdiction only.',
        '4. Goods once sold will not be taken back.'
    ]
    for i, line in enumerate(terms):
        pdf.set_font('Helvetica', 'B' if i == 0 else '', 7.5)
        pdf.set_text_color(BLUE if i == 0 else MUTED)
        pdf.cell(100, 4, line, align='L')
        pdf.ln(4)

    # Signature box
    pdf.set_xy(140, y5 + 5)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(56, 4, 'For  ' + org_name, align='C')
    pdf.set_xy(140, y5 + 22)
    pdf.set_draw_color(*DARKTEXT)
    pdf.line(145, y5 + 22, 195, y5 + 22)
    pdf.set_xy(140, y5 + 23)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(56, 4, 'Authorised Signatory', align='C')

    # Company stamp outline box
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.5)
    pdf.rect(148, y5 + 7, 40, 13)
    pdf.set_xy(148, y5 + 10)
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_text_color(*BLUE)
    pdf.cell(40, 4, org_name.upper(), align='C')
    pdf.set_xy(148, y5 + 14)
    pdf.set_font('Helvetica', '', 6)
    pdf.set_text_color(*MUTED)
    pdf.cell(40, 3, 'GSTIN: 27AABCS1234A1ZX', align='C')

    return bytes(pdf.output())