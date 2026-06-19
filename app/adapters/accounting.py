import re
import json
from app.db import fetch_one, execute
from app.services.pdf_service import generate_invoice_pdf
from app.services.whatsapp import send_document


async def create_invoice(
    org_id: str,
    user_id: str,
    customer_name: str,
    amount: float,
    phone: str,
    items: list = None
) -> dict:
    """
    Creates invoice record, generates PDF, sends via WhatsApp.
    """
    customer = await fetch_one("""
        SELECT id, name, credit_limit
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

    # Auto-generate invoice number
    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM invoices WHERE org_id = $1", org_id
    )
    invoice_number = f"INV-{1100 + int(count_row['cnt'])}"

    items_data = items or [{"description": "As per order", "qty": 1,
                            "unit_price": amount, "total": amount}]

    await execute("""
        INSERT INTO invoices
        (org_id, invoice_number, customer_id, created_by, items, amount, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'approved')
    """, org_id, invoice_number, customer["id"], user_id,
        json.dumps(items_data), amount)

    # Generate PDF
    try:
        pdf_bytes = generate_invoice_pdf(
            invoice_number=invoice_number,
            customer_name=customer["name"],
            amount=amount,
            items=items_data
        )
        # Send PDF via WhatsApp
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{invoice_number}.pdf",
            caption=f"🧾 Invoice {invoice_number} for {customer['name']} — ₹{amount:,.0f}"
        )
        pdf_sent = True
    except Exception as e:
        print(f"[PDF] Error generating/sending PDF: {e}")
        pdf_sent = False

    return {
        "success": True,
        "invoice_number": invoice_number,
        "customer": customer["name"],
        "amount": amount,
        "pdf_sent": pdf_sent,
        "message": (
            f"✅ *Invoice Created*\n\n"
            f"Invoice #: *{invoice_number}*\n"
            f"Customer: {customer['name']}\n"
            f"Amount: *₹{amount:,.0f}*\n"
            f"Status: Approved\n\n"
            f"{'📄 PDF sent above ↑' if pdf_sent else '⚠️ PDF could not be sent.'}"
        )
    }


def parse_amount_from_text(text: str) -> float | None:
    """Extract amount from text like 'invoice Mehta 1,20,000' or '₹50000'"""
    text = text.replace(",", "")
    match = re.search(r"₹?\s*(\d+)", text)
    return float(match.group(1)) if match else None
