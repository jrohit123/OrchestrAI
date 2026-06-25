"""
Quotation generation and management adapter.
"""
import json
import re
from datetime import datetime, timedelta
from app.db import fetch_one, fetch_all, execute
from app.services.quotation_pdf import generate_quotation_pdf
from app.services.whatsapp import send_document


async def get_metal_rates(org_id: str) -> dict:
    """Fetch all current metal rates for org."""
    rows = await fetch_all(
        "SELECT metal_type, rate_per_gram, making_charge_pct "
        "FROM metal_rates WHERE org_id = $1 ORDER BY metal_type",
        org_id
    )
    return {r["metal_type"]: dict(r) for r in rows}


async def create_quotation(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    raw_text: str = None,
    customer_name: str = None,
    metal_type: str = None,
    weight_grams: float = None,
    design_code: str = None,
    valid_days: int = 3,
    **kwargs
) -> dict:
    """Generate and send quotation PDF."""

    # Parse from raw_text if not provided
    if not customer_name or not metal_type or not weight_grams:
        details = parse_quotation_command(raw_text)
        customer_name = details.get("customer") or entity_raw
        metal_type = details.get("metal")
        weight_grams = details.get("weight")
        design_code = details.get("design_code") or design_code

    if not customer_name:
        return {
            "success": False,
            "message": (
                "🤔 Format: *quote [customer] [metal] [weight]g*\n\n"
                "Examples:\n"
                "• *quote Mehta 22kt 15.5g*\n"
                "• *quote Kapoor 18kt 8g DC-001*\n\n"
                "Available metals: 22kt, 18kt, 14kt, silver, platinum"
            )
        }

    if not metal_type:
        return {"success": False, "message": "🤔 Specify metal type: 22kt, 18kt, 14kt, silver, or platinum"}

    if not weight_grams:
        return {"success": False, "message": "🤔 Specify weight in grams. Example: *15.5g*"}

    # Fetch customer
    customer = await fetch_one("""
        SELECT id, name, city FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY similarity(name, $3) DESC LIMIT 1
    """, org_id, f"%{customer_name}%", customer_name)

    if not customer:
        return {
            "success": False,
            "message": f"❌ Customer *{customer_name}* not found."
        }

    # Fetch metal rate
    rate_row = await fetch_one(
        "SELECT rate_per_gram, making_charge_pct FROM metal_rates "
        "WHERE org_id = $1 AND metal_type = $2",
        org_id, metal_type.lower()
    )

    if not rate_row:
        rates = await get_metal_rates(org_id)
        available = ", ".join(rates.keys()) if rates else "none configured"
        return {
            "success": False,
            "message": (
                f"❌ No rate found for *{metal_type}*.\n"
                f"Available: {available}\n"
                f"Ask admin to set rate: *set rate {metal_type} [amount]*"
            )
        }

    # Fetch org settings
    org = await fetch_one(
        "SELECT name, gst_rate FROM orgs WHERE id = $1", org_id
    )
    org_name = org["name"] if org else "Organisation"
    gst_pct = float(org["gst_rate"]) if org and org["gst_rate"] else 3.0

    # Calculate
    rate_per_gram = float(rate_row["rate_per_gram"])
    making_pct = float(rate_row["making_charge_pct"])
    metal_cost = weight_grams * rate_per_gram
    making_charges = round(metal_cost * making_pct / 100, 2)
    subtotal = round(metal_cost + making_charges, 2)
    gst_amount = round(subtotal * gst_pct / 100, 2)
    total_amount = round(subtotal + gst_amount, 2)

    # Auto quotation number
    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM quotations WHERE org_id = $1", org_id
    )
    quotation_number = f"QUO-{1001 + int(count_row['cnt'])}"

    # Save to DB
    await execute("""
        INSERT INTO quotations (
            org_id, quotation_number, customer_id, customer_name,
            metal_type, weight_grams, design_code, rate_per_gram,
            making_charge_pct, making_charges, subtotal,
            gst_pct, gst_amount, total_amount, status,
            valid_until, created_by
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'sent',$15,$16)
    """, org_id, quotation_number, customer["id"], customer["name"],
        metal_type.lower(), weight_grams, design_code,
        rate_per_gram, making_pct, making_charges, subtotal,
        gst_pct, gst_amount, total_amount,
        datetime.now().date() + timedelta(days=valid_days), user_id)

    # Generate PDF
    try:
        pdf_bytes = generate_quotation_pdf(
            quotation_number=quotation_number,
            customer_name=customer["name"],
            metal_type=metal_type,
            weight_grams=weight_grams,
            design_code=design_code,
            rate_per_gram=rate_per_gram,
            making_charge_pct=making_pct,
            making_charges=making_charges,
            subtotal=subtotal,
            gst_pct=gst_pct,
            gst_amount=gst_amount,
            total_amount=total_amount,
            org_name=org_name,
            customer_city=customer.get("city", ""),
            valid_days=valid_days
        )
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=f"{quotation_number}.pdf",
            caption=f"📋 {quotation_number} for {customer['name']} — Rs.{total_amount:,.0f}"
        )
        pdf_sent = True
    except Exception as e:
        print(f"[QUOTATION PDF] Error: {e}")
        pdf_sent = False

    return {
        "success": True,
        "quotation_number": quotation_number,
        "message": (
            f"📋 *Quotation Generated*\n\n"
            f"Quote #: *{quotation_number}*\n"
            f"Customer: {customer['name']}\n"
            f"Metal: {metal_type.upper()} @ Rs.{rate_per_gram:,.0f}/g\n"
            f"Weight: {weight_grams:.3f}g\n"
            f"Making ({making_pct:.0f}%): Rs.{making_charges:,.0f}\n"
            f"GST ({gst_pct:.0f}%): Rs.{gst_amount:,.0f}\n"
            f"*Total: Rs.{total_amount:,.0f}*\n\n"
            f"Valid for {valid_days} days.\n"
            f"{'📄 PDF sent above ↑' if pdf_sent else '⚠️ PDF unavailable.'}\n\n"
            f"To accept: *accept quote {quotation_number}*"
        )
    }


async def set_metal_rate(
    org_id: str,
    entity_raw: str = None,
    user_id: str = None,
    phone: str = None,
    raw_text: str = None,
    metal_type: str = None,
    rate_per_gram: float = None,
    making_charge_pct: float = None,
    **kwargs
) -> dict:
    """Update metal rate and/or making charges."""
    
    # Parse from raw_text if not provided
    if not metal_type or (rate_per_gram is None and making_charge_pct is None):
        parsed = parse_rate_command(raw_text)
        
        if parsed["type"] == "gst":
            # GST is handled separately via orgs table
            await execute(
                "UPDATE orgs SET gst_rate = $1 WHERE id = $2",
                parsed["value"], org_id
            )
            return {
                "success": True,
                "message": f"✅ GST rate updated to *{parsed['value']:.1f}%*"
            }
        
        if parsed["type"] == "making":
            metal_type = parsed["metal"]
            making_charge_pct = parsed["value"]
        elif parsed["type"] == "rate":
            metal_type = parsed["metal"]
            rate_per_gram = parsed["value"]
        else:
            return {
                "success": False,
                "message": (
                    "🤔 Format:\n"
                    "• *set rate 22kt 6200* — update gold rate\n"
                    "• *set making 22kt 15* — update making charges %\n"
                    "• *set gst 3* — update GST rate"
                )
            }
    existing = await fetch_one(
        "SELECT * FROM metal_rates WHERE org_id = $1 AND metal_type = $2",
        org_id, metal_type.lower()
    )

    if not existing:
        if rate_per_gram is None:
            return {"success": False, "message": f"❌ No rate found for {metal_type}. Provide rate to create one."}
        await execute("""
            INSERT INTO metal_rates (org_id, metal_type, rate_per_gram, making_charge_pct, updated_by)
            VALUES ($1, $2, $3, $4, $5)
        """, org_id, metal_type.lower(),
            rate_per_gram, making_charge_pct or 15.0, user_id)
    else:
        new_rate = rate_per_gram if rate_per_gram is not None else float(existing["rate_per_gram"])
        new_making = making_charge_pct if making_charge_pct is not None else float(existing["making_charge_pct"])
        await execute("""
            UPDATE metal_rates SET rate_per_gram = $1, making_charge_pct = $2,
            updated_by = $3, updated_at = NOW()
            WHERE org_id = $4 AND metal_type = $5
        """, new_rate, new_making, user_id, org_id, metal_type.lower())

    parts = []
    if rate_per_gram is not None:
        parts.append(f"Rate: Rs.{rate_per_gram:,.0f}/g")
    if making_charge_pct is not None:
        parts.append(f"Making: {making_charge_pct:.1f}%")

    return {
        "success": True,
        "message": (
            f"✅ *{metal_type.upper()} Rate Updated*\n\n"
            + "\n".join(parts)
            + f"\n\n_All new quotations will use this rate._"
        )
    }


def parse_quotation_command(raw_text: str) -> dict:
    """
    Parse: 'quote Mehta 22kt 15.5g' or 'quote Mehta 22kt 15.5g DC-001'
    Returns: {customer, metal, weight, design_code}
    """
    t = raw_text.lower().strip()
    t = re.sub(r'^(quote|quotation for|give quote|price quote|generate quote|make quote)\s+', '', t)

    # Match: customer metal weight [design_code]
    m = re.search(
        r'^([\w\s]+?)\s+(22kt|18kt|14kt|silver|platinum)\s+([\d.]+)\s*g(?:rams?)?\s*(.*)$',
        t, re.IGNORECASE
    )
    if m:
        return {
            "customer": m.group(1).strip().title(),
            "metal": m.group(2).lower(),
            "weight": float(m.group(3)),
            "design_code": m.group(4).strip().upper() or None
        }

    return {"customer": None, "metal": None, "weight": None, "design_code": None}


def parse_rate_command(raw_text: str) -> dict:
    """
    Parse:
    'set rate 22kt 6200'          → metal rate
    'set making 22kt 15'          → making charges
    'set gst 3'                   → GST rate
    'update rate 18kt 5100'       → same as set rate
    """
    t = raw_text.lower().strip()

    # GST
    m = re.search(r'(?:set|update)\s+gst\s+([\d.]+)', t)
    if m:
        return {"type": "gst", "value": float(m.group(1))}

    # Making charges
    m = re.search(r'(?:set|update)\s+making\s+(22kt|18kt|14kt|silver|platinum)\s+([\d.]+)', t)
    if m:
        return {"type": "making", "metal": m.group(1), "value": float(m.group(2))}

    # Metal rate
    m = re.search(r'(?:set|update|gold|silver)\s+(?:rate\s+)?(22kt|18kt|14kt|silver|platinum)\s+([\d,]+)', t)
    if m:
        rate = float(m.group(2).replace(",", ""))
        return {"type": "rate", "metal": m.group(1), "value": rate}

    return {"type": None}
