"""
Pending orders tracker adapter.
"""
import json
import re
from datetime import datetime, timezone
from app.db import fetch_one, fetch_all, execute


STATUS_MAP = {
    "confirmed":    "confirmed",
    "confirm":      "confirmed",
    "production":   "in_production",
    "in production":"in_production",
    "in_production":"in_production",
    "making":       "in_production",
    "qc":           "quality_check",
    "quality":      "quality_check",
    "quality check":"quality_check",
    "ready":        "ready",
    "complete":     "ready",
    "delivered":    "delivered",
    "deliver":      "delivered",
    "done":         "delivered",
}

STATUS_LABELS = {
    "confirmed":     "✅ Confirmed",
    "in_production": "🔨 In Production",
    "quality_check": "🔍 Quality Check",
    "ready":         "📦 Ready for Delivery",
    "delivered":     "✅ Delivered",
}

ACTIVE_STATUSES = ["confirmed", "in_production", "quality_check", "ready"]


async def create_order(
    org_id: str,
    user_id: str,
    customer_name: str,
    description: str,
    metal_type: str = None,
    estimated_amount: float = None,
    quotation_id: str = None
) -> dict:
    # Find customer
    customer = await fetch_one("""
        SELECT id, name FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

    if not customer:
        return {"success": False,
                "message": f"❌ Customer *{customer_name}* not found."}

    # Auto order number
    count = await fetch_one(
        "SELECT COUNT(*) as cnt FROM orders WHERE org_id = $1", org_id
    )
    order_number = f"ORD-{1001 + int(count['cnt'])}"

    # Status history as JSONB
    status_history = [{
        "status": "confirmed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": str(user_id)
    }]

    await execute("""
        INSERT INTO orders (
            org_id, order_number, customer_id, customer_name,
            description, metal_type, estimated_amount,
            quotation_id, status, status_history, created_by
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'confirmed',$9,$10)
    """, org_id, order_number, customer["id"], customer["name"],
        description, metal_type, estimated_amount, quotation_id,
        json.dumps(status_history), user_id)

    amount_str = f"\nEstimated: Rs.{estimated_amount:,.0f}" if estimated_amount else ""

    return {
        "success": True,
        "order_number": order_number,
        "message": (
            f"✅ *Order Created*\n\n"
            f"Order #: *{order_number}*\n"
            f"Customer: {customer['name']}\n"
            f"Item: {description}"
            + (f"\nMetal: {metal_type.upper()}" if metal_type else "")
            + amount_str
            + f"\nStatus: ✅ Confirmed\n\n"
            f"Update status: *update {order_number} in production*"
        )
    }


async def update_order_status(
    org_id: str,
    user_id: str,
    order_number_or_text: str,
    new_status_text: str
) -> dict:
    # Normalize order number
    order_num = order_number_or_text.upper()
    if not order_num.startswith("ORD-"):
        order_num = "ORD-" + order_num

    new_status = STATUS_MAP.get(new_status_text.lower().strip())
    if not new_status:
        valid = ", ".join(STATUS_MAP.keys())
        return {"success": False,
                "message": f"❌ Unknown status.\nValid: {valid}"}

    order = await fetch_one(
        "SELECT id, status, customer_name, description, status_history FROM orders "
        "WHERE org_id = $1 AND order_number = $2",
        org_id, order_num
    )

    if not order:
        return {"success": False,
                "message": f"❌ Order *{order_num}* not found."}

    old_status = order["status"]
    
    # Append to status history
    status_history = json.loads(order["status_history"]) if order["status_history"] else []
    status_history.append({
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": str(user_id)
    })

    await execute("""
        UPDATE orders SET status = $1, status_updated_at = NOW(), status_history = $2
        WHERE org_id = $3 AND order_number = $4
    """, new_status, json.dumps(status_history), org_id, order_num)

    label = STATUS_LABELS.get(new_status, new_status)

    msg = (
        f"✅ *Order Updated*\n\n"
        f"Order: *{order_num}*\n"
        f"Customer: {order['customer_name']}\n"
        f"Item: {order['description']}\n"
        f"Status: {label}"
    )

    if new_status == "ready":
        msg += "\n\n📱 _Consider notifying the customer their order is ready._"
    elif new_status == "delivered":
        msg += "\n\n🎉 Order complete!"

    return {"success": True, "message": msg}


async def get_orders(org_id: str, filter_type: str = "active") -> dict:
    """
    filter_type: 'active', 'ready', 'all', 'delivered', or order_number
    """
    if filter_type.upper().startswith("ORD-") or filter_type.isdigit():
        order_num = filter_type.upper()
        if not order_num.startswith("ORD-"):
            order_num = "ORD-" + order_num
        order = await fetch_one("""
            SELECT order_number, customer_name, description,
                   metal_type, estimated_amount, status, created_at
            FROM orders WHERE org_id = $1 AND order_number = $2
        """, org_id, order_num)
        if not order:
            return {"message": f"❌ Order *{order_num}* not found."}
        label = STATUS_LABELS.get(order["status"], order["status"])
        return {
            "message": (
                f"📦 *Order Status*\n\n"
                f"Order #: *{order['order_number']}*\n"
                f"Customer: {order['customer_name']}\n"
                f"Item: {order['description']}"
                + (f"\nMetal: {order['metal_type'].upper()}" if order["metal_type"] else "")
                + (f"\nEstimate: Rs.{order['estimated_amount']:,.0f}" if order["estimated_amount"] else "")
                + f"\nStatus: {label}"
            )
        }

    if filter_type == "ready":
        rows = await fetch_all("""
            SELECT order_number, customer_name, description, status
            FROM orders WHERE org_id = $1 AND status = 'ready'
            ORDER BY status_updated_at ASC
        """, org_id)
    elif filter_type == "delivered":
        rows = await fetch_all("""
            SELECT order_number, customer_name, description, status
            FROM orders WHERE org_id = $1 AND status = 'delivered'
            ORDER BY status_updated_at DESC LIMIT 10
        """, org_id)
    else:  # active (default)
        rows = await fetch_all("""
            SELECT order_number, customer_name, description, status
            FROM orders WHERE org_id = $1 AND status = ANY($2)
            ORDER BY created_at ASC
        """, org_id, ACTIVE_STATUSES)

    if not rows:
        labels = {
            "ready": "No orders ready for delivery.",
            "delivered": "No recent delivered orders.",
            "active": "No active orders."
        }
        return {"message": f"📦 {labels.get(filter_type, 'No orders found.')}"}

    lines = []
    for r in rows:
        label = STATUS_LABELS.get(r["status"], r["status"])
        lines.append(f"• *{r['order_number']}* — {r['customer_name']}\n  {r['description'][:40]} | {label}")

    title_map = {
        "ready": "Orders Ready for Delivery",
        "delivered": "Recently Delivered",
        "active": "Active Orders"
    }
    title = title_map.get(filter_type, "Orders")

    return {
        "count": len(rows),
        "message": (
            f"📦 *{title}* ({len(rows)} order{'s' if len(rows) > 1 else ''})\n\n"
            + "\n\n".join(lines)
        )
    }


async def accept_quotation(org_id: str, user_id: str, quotation_number: str) -> dict:
    """Convert accepted quotation to an order."""
    qt = await fetch_one("""
        SELECT * FROM quotations
        WHERE org_id = $1 AND quotation_number = $2
    """, org_id, quotation_number.upper())

    if not qt:
        return {"success": False, "message": f"❌ Quotation *{quotation_number}* not found."}

    if qt["status"] == "converted":
        return {"success": False, "message": f"❌ Quotation *{quotation_number}* already converted to order."}

    result = await create_order(
        org_id=org_id, user_id=user_id,
        customer_name=qt["customer_name"],
        description=f"{qt['metal_type'].upper()} {qt['weight_grams']}g jewellery",
        metal_type=qt["metal_type"],
        estimated_amount=float(qt["total_amount"]),
        quotation_id=str(qt["id"])
    )

    if result["success"]:
        await execute("""
            UPDATE quotations SET status = 'converted'
            WHERE org_id = $1 AND quotation_number = $2
        """, org_id, quotation_number.upper())

    return result


def parse_order_command(raw_text: str) -> dict:
    """Parse order commands."""
    t = raw_text.lower().strip()

    # Accept quote
    m = re.search(r'(?:accept|confirm)\s+quote\s+(quo-\d+|\d+)', t)
    if m:
        num = m.group(1).upper()
        return {"action": "accept_quote", "quotation_number": f"QUO-{num}" if num.isdigit() else num}

    # Update order status
    m = re.search(r'(?:update|mark|order)\s+(ord-\d+|\d+)\s+(.+)$', t)
    if m:
        num = m.group(1).upper()
        return {
            "action": "update",
            "order_number": f"ORD-{num}" if num.isdigit() else num,
            "status": m.group(2).strip()
        }

    # Delivered (shorthand)
    m = re.search(r'delivered\s+(ord-\d+|\d+)', t)
    if m:
        num = m.group(1).upper()
        return {
            "action": "update",
            "order_number": f"ORD-{num}" if num.isdigit() else num,
            "status": "delivered"
        }

    # Check specific order
    m = re.search(r'(?:order|status)\s+(ord-\d+|\d+)', t)
    if m:
        num = m.group(1).upper()
        return {"action": "status", "filter": f"ORD-{num}" if num.isdigit() else num}

    # List queries
    if "ready" in t:
        return {"action": "list", "filter": "ready"}
    if "delivered" in t:
        return {"action": "list", "filter": "delivered"}

    return {"action": "list", "filter": "active"}
