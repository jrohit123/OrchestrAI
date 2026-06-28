import re
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
    """
    Creates invoice, generates PDF, sends via WhatsApp.
    If item_name + qty provided: verifies stock and deducts after creation.
    """
    # Parse details from raw_text if not provided
    if not customer_name or not amount:
        details = parse_invoice_details(raw_text or "")
        customer_name = customer_name or details.get("customer") or entity_raw
        amount = amount or details.get("amount")
        item_name = item_name or details.get("item")
        qty = qty or details.get("qty")

    if not customer_name:
        return {"success": False, "message": "🤔 Which customer? Try: *invoice Mehta 25000*"}
    if not amount:
        return {"success": False, "message": "🤔 What amount? Try: *invoice Mehta 25000*"}
    # Find customer
    customer = await fetch_one("""
        SELECT id, name, credit_limit, gst_number, city
        FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
        LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

    if not customer:
        first_word = customer_name.split()[0]
        customer = await fetch_one("""
            SELECT id, name, credit_limit, gst_number, city
            FROM customers
            WHERE org_id = $1 AND name ILIKE $2
            ORDER BY similarity(name, $3) DESC
            LIMIT 1
        """, org_id, f"%{first_word}%", first_word)

    if not customer:
        return {
            "success": False,
            "message": f"❌ Customer *{customer_name}* not found."
        }

    # Stock check if item specified
    stock_info = None
    if item_name and qty:
        stock_info = await check_stock_availability(org_id, item_name, qty)
        if not stock_info["available"]:
            return {"success": False, "message": stock_info["message"]}

    # Build line items
    if stock_info and qty:
        unit_price = stock_info["unit_price"] or round(amount / qty, 2)
        gst_rate = 0.03
        subtotal  = round(amount / (1 + gst_rate), 2)
        gst_val   = round(amount - subtotal, 2)
        unit_sub  = round(subtotal / qty, 2)
        items_data = [{
            "description": stock_info["item_name"],
            "qty": qty,
            "unit_price": unit_sub,
            "gst": round(gst_val, 2),
            "total": amount
        }]
    else:
        items_data = items or [{
            "description": "As per order",
            "qty": 1,
            "unit_price": round(amount / 1.03, 2),
            "gst": round(amount - amount / 1.03, 2),
            "total": amount
        }]

    # Auto invoice number
    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM invoices WHERE org_id = $1", org_id
    )
    invoice_number = f"INV-{1100 + int(count_row['cnt'])}"

    # Fetch org name
    org = await fetch_one("SELECT name FROM orgs WHERE id = $1", org_id)
    org_name = org["name"] if org else "Organisation"

    # Save to DB
    await execute("""
        INSERT INTO invoices
        (org_id, invoice_number, customer_id, created_by, items, amount, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'approved')
    """, org_id, invoice_number, customer["id"], user_id,
        json.dumps(items_data), amount)

    # Deduct stock if applicable
    stock_msg = ""
    if stock_info and qty:
        deduct = await deduct_stock(org_id, stock_info["sku"], qty)
        if deduct["success"]:
            stock_msg = f"\n📦 Stock updated: {deduct['remaining']} pcs remaining"

    # Generate + send PDF
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
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%d %b %Y"),
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

    return {
        "success": True,
        "invoice_number": invoice_number,
        "customer": customer["name"],
        "amount": amount,
        "message": (
            f"✅ *Invoice Created*\n\n"
            f"Invoice #: *{invoice_number}*\n"
            f"Customer: {customer['name']}\n"
            f"Amount: *Rs.{amount:,.0f}*\n"
            f"Status: Approved"
            f"{stock_msg}\n\n"
            f"{'📄 PDF sent above ↑' if pdf_sent else '⚠️ PDF unavailable.'}"
        )
    }


def parse_invoice_details(raw_text: str) -> dict:
    """
    Parse invoice command. Handles two formats:
    Full:   'invoice Mehta 15 gold rings 120000'
    Simple: 'invoice Mehta 120000'
    Returns: {customer, qty, item, amount}
    """
    text = raw_text.lower().replace(",", "").strip()
    text = re.sub(r'^(invoice|bill|raise invoice)\s+', '', text)

    # Full format: customer qty item amount
    # Anchor: first small number = qty, last large number = amount
    m = re.search(r'^([\w\s]+?)\s+(\d{1,4})\s+([\w\s]+?)\s+(\d{4,})\s*$', text.strip())
    if m:
        return {
            'customer': m.group(1).strip().title(),
            'qty': int(m.group(2)),
            'item': m.group(3).strip(),
            'amount': float(m.group(4))
        }

    # Simple format: customer amount
    m = re.search(r'^(\w+)\s+(\d{3,})\s*$', text.strip())
    if m:
        return {
            'customer': m.group(1).strip().title(),
            'qty': None,
            'item': None,
            'amount': float(m.group(2))
        }

    return {'customer': None, 'qty': None, 'item': None, 'amount': None}


async def send_invoice_pdf(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    raw_text: str = None,
    **kwargs
) -> dict:
    """
    Send PDF for an existing invoice.
    Usage: "send invoice INV-001 to Mehta" or "invoice pdf INV-001"
    """
    invoice_number = entity_raw or raw_text
    if not invoice_number:
        return {"success": False, "message": "🤔 Which invoice? Try: *send invoice INV-001*"}
    
    # Extract invoice number from text - handle various formats
    invoice_number = invoice_number.upper()
    
    # Remove common words that might be included in entity extraction
    invoice_number = invoice_number.replace("INVOICE", "").replace("SEND", "").replace("PDF", "").strip()
    
    # If it already starts with INV-, use it directly
    if invoice_number.startswith("INV-"):
        pass
    else:
        # Try to extract INV-XXX pattern from text (be specific to avoid matching "invoice" word)
        import re
        match = re.search(r'INV-(\d+)', invoice_number, re.IGNORECASE)
        if match:
            invoice_number = f"INV-{match.group(1)}"
        else:
            return {"success": False, "message": "🤔 Invalid invoice format. Try: *send invoice INV-001*"}
    
    # Fetch invoice with customer details
    invoice = await fetch_one("""
        SELECT i.invoice_number, i.amount, i.items, i.due_date, i.created_at, i.status,
               c.name as customer_name, c.gst_number, c.city, c.id as customer_id
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.org_id = $1 AND i.invoice_number = $2
    """, org_id, invoice_number)
    
    if not invoice:
        return {"success": False, "message": f"❌ Invoice *{invoice_number}* not found."}
    
    # Fetch org name
    org = await fetch_one("SELECT name FROM orgs WHERE id = $1", org_id)
    org_name = org["name"] if org else "Organisation"
    
    # Parse items
    items = invoice.get("items", [])
    if isinstance(items, str):
        items = json.loads(items)
    
    # Generate PDF
    try:
        pdf_bytes = await generate_pdf(
            rows=items,
            title=f"Tax Invoice — {invoice['invoice_number']}",
            org_name=org_name,
            doc_type="invoice",
            extra_context={
                "invoice_number": invoice["invoice_number"],
                "customer_name": invoice["customer_name"],
                "customer_city": invoice.get("city", ""),
                "customer_gstin": invoice.get("gst_number", ""),
                "amount": float(invoice["amount"]),
                "gst_rate": 3.0,
                "due_date": invoice.get("due_date"),
            }
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{invoice_number}.pdf",
            caption=f"🧾 {invoice_number} — {invoice['customer_name']} — Rs.{invoice['amount']:,.0f}"
        )
        return {
            "success": True,
            "invoice_number": invoice_number,
            "customer": invoice["customer_name"],
            "amount": float(invoice["amount"]),
            "message": f"✅ *Invoice PDF sent*\n\nInvoice #: *{invoice_number}*\nCustomer: {invoice['customer_name']}\nAmount: *Rs.{invoice['amount']:,.0f}*\nStatus: {invoice['status']}"
        }
    except Exception as e:
        print(f"[PDF] Error: {e}")
        return {"success": False, "message": f"⚠️ Error generating PDF: {str(e)}"}


async def send_dues_statement(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    raw_text: str = None,
    **kwargs
) -> dict:
    """
    Generate and send PDF statement of all outstanding invoices for a customer.
    Usage: "dues statement Mehta" or "outstanding statement Sharma"
    """
    customer_name = entity_raw or raw_text
    if not customer_name:
        return {"success": False, "message": "🤔 Which customer? Try: *dues statement Mehta*"}
    
    # Remove common words that might be included in entity extraction
    customer_name = customer_name.upper().replace("STATEMENT", "").replace("DUES", "").replace("OUTSTANDING", "").replace("SEND", "").strip()
    
    # Find customer
    customer = await fetch_one("""
        SELECT id, name, city, gst_number, credit_limit
        FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
        LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)
    
    if not customer:
        return {"success": False, "message": f"❌ Customer *{customer_name}* not found."}
    
    # Fetch outstanding invoices
    invoices = await fetch_all("""
        SELECT invoice_number, amount, status, due_date, created_at
        FROM invoices
        WHERE org_id = $1
          AND customer_id = $2
          AND status IN ('pending', 'overdue')
        ORDER BY due_date ASC
    """, org_id, customer["id"])
    
    if not invoices:
        return {
            "success": True,
            "customer": customer["name"],
            "total_outstanding": 0,
            "message": f"✅ *{customer['name']}* has no outstanding dues."
        }
    
    # Calculate totals
    total = sum(r["amount"] for r in invoices)
    overdue_total = sum(r["amount"] for r in invoices if r["status"] == "overdue")
    
    # Fetch org name
    org = await fetch_one("SELECT name FROM orgs WHERE id = $1", org_id)
    org_name = org["name"] if org else "Organisation"
    
    # Generate PDF
    try:
        pdf_bytes = await generate_pdf(
            rows=[dict(inv) for inv in invoices],
            title=f"Dues Statement — {customer['name']}",
            org_name=org_name,
            subtitle=f"As of {datetime.now().strftime('%d %b %Y')}",
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
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"dues_statement_{customer['name'].replace(' ', '_')}.pdf",
            caption=f"📊 Dues Statement — {customer['name']} — Rs.{total:,.0f}"
        )
        return {
            "success": True,
            "customer": customer["name"],
            "total_outstanding": float(total),
            "overdue_total": float(overdue_total),
            "invoice_count": len(invoices),
            "message": f"✅ *Dues Statement sent*\n\nCustomer: {customer['name']}\nTotal Outstanding: *Rs.{total:,.0f}*\nOverdue: *Rs.{overdue_total:,.0f}*\nInvoices: {len(invoices)}"
        }
    except Exception as e:
        print(f"[PDF] Error: {e}")
        return {"success": False, "message": f"⚠️ Error generating PDF: {str(e)}"}
