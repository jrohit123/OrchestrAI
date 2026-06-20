import re
import json
from app.db import fetch_one, execute
from app.services.pdf_service import generate_invoice_pdf
from app.services.whatsapp import send_document
from app.adapters.inventory import check_stock_availability, deduct_stock


async def create_invoice(
    org_id: str,
    user_id: str,
    customer_name: str,
    amount: float,
    phone: str,
    item_name: str = None,
    qty: int = None,
    items: list = None
) -> dict:
    """
    Creates invoice, generates PDF, sends via WhatsApp.
    If item_name + qty provided: verifies stock and deducts after creation.
    """
    # Find customer
    customer = await fetch_one("""
        SELECT id, name, credit_limit, gst_number, city
        FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
        LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

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
    m = re.search(r'^([\w\s]+?)\s+(\d{4,})\s*$', text.strip())
    if m:
        return {
            'customer': m.group(1).strip().title(),
            'qty': None,
            'item': None,
            'amount': float(m.group(2))
        }

    return {'customer': None, 'qty': None, 'item': None, 'amount': None}
