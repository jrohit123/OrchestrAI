from app.db import fetch_one, fetch_all
from datetime import datetime, timezone


async def get_outstanding(org_id: str, customer_name: str) -> dict:
    """
    Fuzzy search customer and return all overdue invoices with totals.
    """
    customer = await fetch_one("""
        SELECT id, name, city, credit_limit
        FROM customers
        WHERE org_id = $1
          AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
        LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

    if not customer:
        return {
            "found": False,
            "message": f"❌ No customer found matching *{customer_name}*.\nCheck spelling or contact admin."
        }

    invoices = await fetch_all("""
        SELECT invoice_number, amount, status, due_date, created_at
        FROM invoices
        WHERE org_id = $1
          AND customer_id = $2
          AND status IN ('overdue', 'approved', 'draft')
        ORDER BY due_date ASC
    """, org_id, customer["id"])

    if not invoices:
        return {
            "found": True,
            "customer": customer["name"],
            "total_outstanding": 0,
            "message": f"✅ *{customer['name']}* has no outstanding dues."
        }

    total = sum(r["amount"] for r in invoices)
    overdue_total = sum(r["amount"] for r in invoices if r["status"] == "overdue")
    now = datetime.now(timezone.utc)

    lines = []
    for inv in invoices:
        days = (now.date() - inv["due_date"]).days if inv["due_date"] else 0
        status_icon = "🔴" if inv["status"] == "overdue" else "🟡"
        days_str = f"{days}d overdue" if days > 0 else "due soon"
        lines.append(f"{status_icon} {inv['invoice_number']} — ₹{inv['amount']:,.0f} ({days_str})")

    return {
        "found": True,
        "customer": customer["name"],
        "total_outstanding": float(total),
        "overdue_total": float(overdue_total),
        "invoice_count": len(invoices),
        "message": (
            f"💰 *{customer['name']}* — Outstanding\n\n"
            + "\n".join(lines)
            + f"\n\n*Total: ₹{total:,.0f}*"
            + (f"\n🔴 Overdue: ₹{overdue_total:,.0f}" if overdue_total > 0 else "")
        )
    }


async def get_all_overdue(org_id: str) -> dict:
    """Used for weekly dues report — all overdue invoices across all customers."""
    rows = await fetch_all("""
        SELECT c.name as customer_name, c.city,
               SUM(i.amount) as total_overdue,
               COUNT(i.id) as invoice_count,
               MIN(i.due_date) as oldest_due
        FROM invoices i
        JOIN customers c ON c.id = i.customer_id
        WHERE i.org_id = $1 AND i.status = 'overdue'
        GROUP BY c.id, c.name, c.city
        ORDER BY total_overdue DESC
    """, org_id)

    if not rows:
        return {
            "count": 0,
            "message": "✅ No overdue invoices! All accounts are clear."
        }

    grand_total = sum(r["total_overdue"] for r in rows)
    lines = []
    for r in rows:
        lines.append(
            f"• *{r['customer_name']}* ({r['city']}) — "
            f"₹{r['total_overdue']:,.0f} ({r['invoice_count']} invoice{'s' if r['invoice_count'] > 1 else ''})"
        )

    return {
        "count": len(rows),
        "grand_total": float(grand_total),
        "message": (
            f"📊 *Overdue Dues Report*\n\n"
            + "\n".join(lines)
            + f"\n\n*Grand Total: ₹{grand_total:,.0f}*"
        )
    }
