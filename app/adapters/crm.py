from app.db import fetch_one, fetch_all
from datetime import datetime, timezone


async def get_credit_limit(org_id: str, entity_raw: str = None, user_id: str = None, phone: str = None, raw_text: str = None, **kwargs) -> dict:
    """
    Fetch the credit limit for a customer.
    Returns multiple matches if found for disambiguation.
    """
    customer_name = entity_raw
    if not customer_name:
        return {
            "found": False,
            "message": "🤔 Which customer? Try: *credit limit Mehta*"
        }
    customers = await fetch_all("""
        SELECT id, name, city, credit_limit
        FROM customers
        WHERE org_id = $1
          AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
    """, org_id, f"%{customer_name}%", customer_name)

    if not customers:
        return {
            "found": False,
            "matches": [],
            "message": f"❌ No customer found matching *{customer_name}*.\nCheck spelling or contact admin."
        }

    # If only one match, return the result directly
    if len(customers) == 1:
        customer = customers[0]
        credit_limit = customer.get("credit_limit")
        if credit_limit is None:
            return {
                "found": True,
                "single_match": True,
                "customer": customer["name"],
                "customer_id": customer["id"],
                "credit_limit": None,
                "message": f"ℹ️ *{customer['name']}* has no credit limit set."
            }

        return {
            "found": True,
            "single_match": True,
            "customer": customer["name"],
            "customer_id": customer["id"],
            "credit_limit": float(credit_limit),
            "message": f"💳 *{customer['name']}* — Credit Limit\n\n₹{credit_limit:,.0f}"
        }

    # Multiple matches - return for disambiguation
    return {
        "found": True,
        "single_match": False,
        "matches": [{"id": c["id"], "name": c["name"], "city": c["city"]} for c in customers],
        "message": f"Found {len(customers)} customers matching *{customer_name}*."
    }


async def get_outstanding(org_id: str, entity_raw: str = None, user_id: str = None, phone: str = None, raw_text: str = None, **kwargs) -> dict:
    """
    Fuzzy search customer and return all overdue invoices with totals.
    Returns multiple matches if found for disambiguation.
    """
    customer_name = entity_raw
    if not customer_name:
        return {
            "found": False,
            "message": "🤔 Which customer? Try: *dues Mehta*"
        }
    customers = await fetch_all("""
        SELECT id, name, city, credit_limit
        FROM customers
        WHERE org_id = $1
          AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
    """, org_id, f"%{customer_name}%", customer_name)

    if not customers:
        return {
            "found": False,
            "matches": [],
            "message": f"❌ No customer found matching *{customer_name}*.\nCheck spelling or contact admin."
        }

    # If only one match, proceed with invoice lookup
    if len(customers) == 1:
        customer = customers[0]
        
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
                "found": True,
                "single_match": True,
                "customer": customer["name"],
                "customer_id": customer["id"],
                "total_outstanding": 0,
                "message": f"✅ *{customer['name']}* has no outstanding dues."
            }

        total = sum(r["amount"] for r in invoices)
        overdue_total = sum(r["amount"] for r in invoices if r["status"] == "overdue")
        now = datetime.now(timezone.utc)

        lines = []
        for inv in invoices:
            if inv["due_date"]:
                days = (now.date() - inv["due_date"]).days
                status_icon = "🔴" if inv["status"] == "overdue" else "🟡"
                days_str = f"{days}d overdue" if days > 0 else "due soon"
            else:
                days = 0
                status_icon = "🟡"
                days_str = "no due date"
            lines.append(f"{status_icon} {inv['invoice_number']} — ₹{inv['amount']:,.0f} ({days_str})")

        return {
            "found": True,
            "single_match": True,
            "customer": customer["name"],
            "customer_id": customer["id"],
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

    # Multiple matches - return for disambiguation
    return {
        "found": True,
        "single_match": False,
        "matches": [{"id": c["id"], "name": c["name"], "city": c["city"]} for c in customers],
        "message": f"Found {len(customers)} customers matching *{customer_name}*."
    }


async def get_all_overdue(org_id: str, entity_raw: str = None, user_id: str = None, phone: str = None, raw_text: str = None, limit: int = None, **kwargs) -> dict:
    """Used for weekly dues report — all overdue invoices across all customers."""
    # Extract limit from raw_text if not passed
    if not limit and raw_text:
        import re
        lm = re.search(r'top\s+(\d+)', raw_text.lower())
        if lm:
            limit = int(lm.group(1))
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
        return {"count": 0, "message": "✅ No overdue invoices! All clear."}

    # Apply limit if specified
    total_count = len(rows)
    if limit:
        rows = rows[:limit]

    grand_total = sum(r["total_overdue"] for r in rows)
    lines = []
    for r in rows:
        lines.append(
            f"• *{r['customer_name']}* ({r['city']}) — "
            f"₹{r['total_overdue']:,.0f} ({r['invoice_count']} invoice{'s' if r['invoice_count'] > 1 else ''})"
        )

    title = f"Top {limit}" if limit else "All"
    return {
        "count": total_count,
        "shown": len(rows),
        "grand_total": float(grand_total),
        "message": (
            f"📊 *{title} Overdue Customers*\n\n"
            + "\n".join(lines)
            + f"\n\n*Total shown: ₹{grand_total:,.0f}*"
            + (f"\n_(showing {limit} of {total_count})_" if limit and limit < total_count else "")
        )
    }
