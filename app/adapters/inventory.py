from app.db import fetch_one, fetch_all


async def check_stock(org_id: str, product_name: str) -> dict:
    """
    Fuzzy search product by name and return stock info.
    Uses pg_trgm similarity for partial matches.
    """
    row = await fetch_one("""
        SELECT name, qty, location, reorder_level, unit_price
        FROM inventory
        WHERE org_id = $1
          AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC
        LIMIT 1
    """, org_id, f"%{product_name}%", product_name)

    if not row:
        return {
            "found": False,
            "message": f"❌ No product found matching *{product_name}*.\nTry: *stock gold ring* or *stock bangle*"
        }

    low_stock = row["qty"] <= row["reorder_level"]
    warning = "⚠️ _Below reorder level!_" if low_stock else ""

    return {
        "found": True,
        "name": row["name"],
        "qty": row["qty"],
        "location": row["location"],
        "reorder_level": row["reorder_level"],
        "unit_price": float(row["unit_price"]) if row["unit_price"] else None,
        "low_stock": low_stock,
        "message": (
            f"📦 *{row['name']}*\n"
            f"Available: *{row['qty']} pcs*\n"
            f"Location: {row['location']}\n"
            f"Reorder level: {row['reorder_level']}\n"
            f"Unit price: ₹{row['unit_price']:,.0f}\n"
            f"{warning}"
        ).strip()
    }


async def get_low_stock_items(org_id: str) -> list:
    """Return all items at or below reorder level."""
    rows = await fetch_all("""
        SELECT name, qty, location, reorder_level
        FROM inventory
        WHERE org_id = $1 AND qty <= reorder_level
        ORDER BY qty ASC
    """, org_id)

    return [dict(r) for r in rows]
