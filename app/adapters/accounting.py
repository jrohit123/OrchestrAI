import re
from app.db import fetch_one, execute


async def create_invoice(
    org_id: str,
    user_id: str,
    customer_name: str,
    amount: float,
    items: list = None
) -> dict:
    """
    Creates an invoice record. OTP gate is handled upstream in executor.
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

    items_data = items or [{"description": "As discussed", "amount": amount}]

    await execute("""
        INSERT INTO invoices
        (org_id, invoice_number, customer_id, created_by, items, amount, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'approved')
    """, org_id, invoice_number, customer["id"], user_id,
        str(items_data).replace("'", '"'), amount)

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
            f"Status: Approved\n\n"
            f"_PDF generation coming in Day 3._"
        )
    }


def parse_amount_from_text(text: str) -> float | None:
    """Extract amount from text like 'invoice Mehta 1,20,000' or '₹50000'"""
    text = text.replace(",", "")
    match = re.search(r"₹?\s*(\d+)", text)
    return float(match.group(1)) if match else None
