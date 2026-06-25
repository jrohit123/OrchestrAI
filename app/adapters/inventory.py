from app.db import fetch_one, fetch_all, execute


async def check_stock(org_id: str, entity_raw: str = None, user_id: str = None, phone: str = None, raw_text: str = None, **kwargs) -> dict:
    """Fuzzy search product by name and return stock info."""
    product_name = entity_raw
    if not product_name:
        return {
            "found": False,
            "message": "🤔 Which product? Try: *stock gold ring* or *stock bangle*"
        }
    row = await fetch_one("""
        SELECT name, qty, location, reorder_level, unit_price, sku
        FROM inventory
        WHERE org_id = $1 AND similarity(name, $2) > 0.1
        ORDER BY similarity(name, $2) DESC
        LIMIT 1
    """, org_id, product_name)

    if not row:
        return {
            "found": False,
            "message": f"❌ No product found matching *{product_name}*.\nTry: *stock gold ring* or *stock bangle*"
        }

    low_stock = row["qty"] <= row["reorder_level"]
    warning = "\n⚠️ _Below reorder level!_" if low_stock else ""

    return {
        "found": True,
        "sku": row["sku"],
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
            f"Unit price: Rs.{row['unit_price']:,.0f}"
            f"{warning}"
        ).strip()
    }


async def check_stock_availability(org_id: str, entity_raw: str = None, user_id: str = None, phone: str = None, raw_text: str = None, qty: int = None, **kwargs) -> dict:
    """Check if required qty is available before creating invoice."""
    item_name = entity_raw
    if not item_name:
        return {
            "available": False,
            "message": "🤔 Which product? Try: *stock gold ring*"
        }
    row = await fetch_one("""
        SELECT name, qty, sku, unit_price
        FROM inventory
        WHERE org_id = $1 AND similarity(name, $2) > 0.1
        ORDER BY similarity(name, $2) DESC
        LIMIT 1
    """, org_id, item_name)

    if not row:
        return {
            "available": False,
            "message": f"❌ Product *{item_name}* not found in inventory."
        }

    if row["qty"] < qty:
        return {
            "available": False,
            "message": (
                f"❌ Insufficient stock for *{row['name']}*.\n"
                f"Requested: {qty} pcs | Available: {row['qty']} pcs"
            )
        }

    return {
        "available": True,
        "item_name": row["name"],
        "sku": row["sku"],
        "unit_price": float(row["unit_price"]) if row["unit_price"] else None,
        "available_qty": row["qty"]
    }


async def deduct_stock(org_id: str, entity_raw: str = None, user_id: str = None, phone: str = None, raw_text: str = None, sku: str = None, qty: int = None, **kwargs) -> dict:
   """Deduct qty from inventory after invoice is created."""
    if not sku or not qty:
        return {"success": False, "message": "❌ SKU and quantity required"}
    await execute("""
        UPDATE inventory
        SET qty = qty - $1, updated_at = NOW()
        WHERE org_id = $2 AND sku = $3
    """, qty, org_id, sku)

    row = await fetch_one(
        "SELECT name, qty FROM inventory WHERE org_id = $1 AND sku = $2",
        org_id, sku
    )
    return {
        "success": True,
        "item": row["name"] if row else sku,
        "remaining": row["qty"] if row else 0
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
