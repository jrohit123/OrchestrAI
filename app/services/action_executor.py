"""
action_executor.py — Deterministic executor for pending actions.

Replaces LLM-routed execution with a single, testable Python function.
Handles OTP checks, approval thresholds, and actual database writes.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from app.db import fetch_one, execute
from app.services.otp_service import generate_and_send_otp
from app.services.pdf_engine import generate_pdf


def _resolve_amount(fields: dict) -> float:
    """Total from top-level amount or sum of items[].total."""
    if fields.get("amount") is not None:
        return float(fields["amount"])
    total = 0.0
    for item in fields.get("items") or []:
        total += float(item.get("total") or 0)
    return total


def _is_valid_uuid(val) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def _resolve_customer_id(fields: dict, org_id: str) -> str | None:
    """Resolve customer_id from fields; fall back to name lookup if needed."""
    customer_id = fields.get("customer_id")
    if customer_id and _is_valid_uuid(customer_id):
        row = await fetch_one(
            "SELECT id FROM customers WHERE id = $1 AND org_id = $2",
            str(customer_id), org_id
        )
        if row:
            return str(row["id"])

    name = fields.get("customer_name")
    if not name:
        return None

    row = await fetch_one(
        "SELECT id FROM customers WHERE org_id = $1 AND name ILIKE $2 LIMIT 1",
        org_id, f"%{name}%"
    )
    return str(row["id"]) if row else None


async def _normalize_items(items: list, org_id: str) -> list:
    """Ensure each line item has qty, unit_price, gst, total as numbers."""
    org = await fetch_one("SELECT gst_rate FROM orgs WHERE id = $1", org_id)
    gst_rate = float(org["gst_rate"]) if org and org.get("gst_rate") is not None else 3.0

    normalized = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        qty = max(1, int(raw.get("qty") or 1))
        unit_price = float(raw.get("unit_price") or 0)
        if unit_price <= 0:
            raise ValueError("Each item needs a positive unit_price")

        if raw.get("gst") is not None:
            gst = float(raw["gst"])
        else:
            gst = round(unit_price * qty * gst_rate / 100, 2)

        if raw.get("total") is not None:
            total = float(raw["total"])
        else:
            total = round(unit_price * qty + gst, 2)

        desc = str(raw.get("description") or "").strip()
        if not desc:
            raise ValueError("Each item needs a description")

        normalized.append({
            "description": desc,
            "qty": qty,
            "unit_price": unit_price,
            "gst": gst,
            "total": total,
        })
    return normalized


async def execute_pending_action(
    pending_action: dict,
    user: dict,
    otp_verified: bool = False,
) -> dict:
    """
    Execute a pending action draft.

    Returns:
        {
            "success": bool,
            "message": str,
            "pdf_bytes": bytes | None,
            "stage": str,
            "invoice_number": str | None,
            "quotation_number": str | None,
        }
    """
    intent_key = pending_action.get("intent_key")
    fields = pending_action.get("fields", {})
    stage = pending_action.get("stage", "collecting")

    if not intent_key:
        return {"success": False, "message": "No intent_key in pending_action"}

    workflow = await fetch_one("""
        SELECT otp_threshold, approval_threshold, adapter_method, pdf_config
        FROM workflows
        WHERE intent_key = $1 AND org_id = $2 AND is_active = true
    """, intent_key, user["org_id"])

    if not workflow:
        return {"success": False, "message": f"Workflow {intent_key} not found"}

    otp_threshold = float(workflow.get("otp_threshold") or 0)
    approval_threshold = float(workflow.get("approval_threshold") or 0)
    pdf_config = workflow.get("pdf_config")

    if stage == "awaiting_confirmation":
        amount = _resolve_amount(fields)

        if amount >= otp_threshold and not otp_verified:
            sent = await generate_and_send_otp(
                user_id=user["user_id"],
                user_email=user["email"],
                user_name=user["user_name"],
                org_name=user["org_name"],
                action_context={"type": "action_otp", "intent_key": intent_key}
            )
            if sent:
                return {
                    "success": False,
                    "message": (
                        f"🔐 *Security Verification Required*\n\n"
                        f"A 4-digit code has been sent to *{user['email']}*\n"
                        f"Reply with the code to continue.\n\n"
                        f"⏱ Code expires in 3 minutes."
                    ),
                    "stage": "awaiting_otp"
                }
            return {"success": False, "message": "❌ Could not send verification email. Contact admin."}

        return await _execute_action(
            intent_key, fields, user, approval_threshold, pdf_config
        )

    if stage == "awaiting_otp" and otp_verified:
        return await _execute_action(
            intent_key, fields, user, approval_threshold, pdf_config
        )

    if stage == "awaiting_approval":
        return await _execute_action(
            intent_key, fields, user, approval_threshold, pdf_config
        )

    return {"success": False, "message": f"Cannot execute action in stage: {stage}"}


async def _execute_action(
    intent_key: str,
    fields: dict,
    user: dict,
    approval_threshold: float,
    pdf_config: dict,
) -> dict:
    """Execute the actual action based on intent_key."""
    amount = _resolve_amount(fields)

    # Bypass approval for owners (role_id for owner is 22220000-0000-0000-0000-000000000001)
    user_role_id = user.get("role_id", "")
    owner_role_id = "22220000-0000-0000-0000-000000000001"
    print(f"[EXECUTOR] Approval check: amount={amount}, threshold={approval_threshold}, user_role_id={user_role_id}, owner_role_id={owner_role_id}")
    if amount >= approval_threshold and user_role_id != owner_role_id:
        return {
            "success": False,
            "message": (
                f"Invoice *Rs.{amount:,.0f}* requires MD approval.\n"
                f"Approval request sent to Mr. Sharma.\n"
                f"You'll be notified once approved."
            ),
            "stage": "awaiting_approval"
        }

    if intent_key == "create_sales_invoice":
        return await _create_invoice(fields, user, pdf_config)
    if intent_key == "generate_price_quotation":
        return await _create_quotation(fields, user, pdf_config)
    return {"success": False, "message": f"Unknown intent_key: {intent_key}"}


async def _create_invoice(fields: dict, user: dict, pdf_config: dict) -> dict:
    """Create an invoice record and generate PDF."""
    items_raw = fields.get("items") or []
    if not items_raw:
        return {
            "success": False,
            "message": "Missing items. Please provide at least one item with description, quantity, and unit price."
        }

    try:
        items = await _normalize_items(items_raw, user["org_id"])
    except ValueError as e:
        return {"success": False, "message": f"❌ Invalid item data: {e}"}

    customer_id = await _resolve_customer_id(fields, user["org_id"])
    if not customer_id:
        return {"success": False, "message": "❌ Customer not found. Please check the customer name."}

    total_amount = sum(float(i["total"]) for i in items)

    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM invoices WHERE org_id = $1",
        user["org_id"]
    )
    invoice_number = f"INV-{100 + int(count_row['cnt'])}"

    try:
        await execute("""
            INSERT INTO invoices (
                org_id, invoice_number, customer_id, amount,
                status, due_date, created_at, items, created_by
            ) VALUES (
                $1, $2, $3, $4,
                'pending', CURRENT_DATE + INTERVAL '30 days', NOW(), $5, $6
            )
        """, user["org_id"], invoice_number, customer_id,
            str(total_amount), json.dumps(items), user["user_id"])
    except Exception as e:
        print(f"[EXECUTOR] Invoice insert failed: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"❌ Could not create invoice: {str(e)}"}

    customer = await fetch_one(
        "SELECT name, city, gst_number FROM customers WHERE id = $1",
        customer_id
    )
    if not customer:
        return {"success": False, "message": "❌ Customer record missing after insert."}

    due = datetime.now(timezone.utc) + timedelta(days=30)
    invoice_rows = [{
        "invoice_number": invoice_number,
        "customer_name": customer["name"],
        "city": customer["city"],
        "gst_number": customer["gst_number"],
        "amount": str(total_amount),
        "status": "pending",
        "due_date": due.strftime("%Y-%m-%d"),
        "items": items
    }]

    subtotal = sum(float(i["unit_price"]) * int(i["qty"]) for i in items)
    gst_amount = sum(float(i["gst"]) for i in items)

    pdf_bytes = None
    try:
        pdf_bytes = await generate_pdf(
            rows=invoice_rows,
            title=f"Tax Invoice — {invoice_number}",
            org_name=user["org_name"],
            subtitle=f"Customer: {customer['name']}",
            doc_type="invoice",
            extra_context={
                "customer_name": customer["name"],
                "city": customer["city"],
                "gstin": customer["gst_number"],
                "invoice_number": invoice_number,
                "amount": str(total_amount),
                "status": "pending",
                "subtotal": str(subtotal),
                "gst_amount": str(gst_amount),
                "total_amount": str(total_amount)
            }
        )
    except Exception as e:
        print(f"[EXECUTOR] Invoice PDF failed: {e}")

    try:
        await execute("""
            INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome, otp_used)
            VALUES ($1, $2, $3, $4, 'success', false)
        """, user["org_id"], user["user_id"], "create_sales_invoice",
            f"invoice {customer['name']} {total_amount}")
    except Exception as e:
        print(f"[EXECUTOR] Audit log failed (non-fatal): {e}")

    item_summary = "\n".join(
        f"  • {i['description']}: Qty {i['qty']} × Rs.{i['unit_price']:,.0f} = Rs.{i['total']:,.0f}"
        for i in items
    )

    return {
        "success": True,
        "message": (
            f"✅ Invoice *#{invoice_number}* created\n\n"
            f"Customer: *{customer['name']}*\n"
            f"Items:\n{item_summary}\n\n"
            f"Total: *Rs.{total_amount:,.0f}*\n"
            f"Status: PENDING\n"
            f"Due Date: 30 days"
        ),
        "pdf_bytes": pdf_bytes,
        "invoice_number": invoice_number
    }


async def _create_quotation(fields: dict, user: dict, pdf_config: dict) -> dict:
    """Create a quotation record and generate PDF."""
    items_raw = fields.get("items") or []
    if not items_raw:
        return {
            "success": False,
            "message": "Missing items. Please provide at least one item with description, quantity, and unit price."
        }

    try:
        items = await _normalize_items(items_raw, user["org_id"])
    except ValueError as e:
        return {"success": False, "message": f"❌ Invalid item data: {e}"}

    customer_id = await _resolve_customer_id(fields, user["org_id"])
    if not customer_id:
        return {"success": False, "message": "❌ Customer not found. Please check the customer name."}

    total_amount = sum(float(i["total"]) for i in items)

    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM quotations WHERE org_id = $1",
        user["org_id"]
    )
    quotation_number = f"QUO-{1001 + int(count_row['cnt'])}"
    valid_until = datetime.now(timezone.utc) + timedelta(days=3)

    try:
        await execute("""
            INSERT INTO quotations (
                org_id, quotation_number, customer_id, items,
                total_amount, status, valid_until, created_at, created_by
            ) VALUES (
                $1, $2, $3, $4,
                $5, 'sent', $6, NOW(), $7
            )
        """, user["org_id"], quotation_number, customer_id, json.dumps(items),
            str(total_amount), valid_until, user["user_id"])
    except Exception as e:
        print(f"[EXECUTOR] Quotation insert failed: {e}")
        return {"success": False, "message": "❌ Could not create quotation. Please try again."}

    customer = await fetch_one(
        "SELECT name, city, gst_number FROM customers WHERE id = $1",
        customer_id
    )
    if not customer:
        return {"success": False, "message": "❌ Customer record missing after insert."}

    quotation_rows = [{
        "quotation_number": quotation_number,
        "customer_name": customer["name"],
        "city": customer["city"],
        "gst_number": customer["gst_number"],
        "total_amount": str(total_amount),
        "valid_until": valid_until.strftime("%Y-%m-%d"),
        "items": items
    }]

    subtotal = sum(float(i["unit_price"]) * int(i["qty"]) for i in items)
    gst_amount = sum(float(i["gst"]) for i in items)

    # Extract design details from first item for PDF
    first_item = items[0] if items else {}
    making_charges_total = sum(float(i.get("making_charges", 0)) for i in items)
    metal_cost = subtotal - making_charges_total

    pdf_bytes = None
    try:
        pdf_bytes = await generate_pdf(
            rows=quotation_rows,
            title=f"Price Quotation — {quotation_number}",
            org_name=user["org_name"],
            subtitle=f"Customer: {customer['name']}",
            doc_type="quotation",
            extra_context={
                "quotation_number": quotation_number,
                "customer_name": customer["name"],
                "city": customer["city"],
                "gstin": customer["gst_number"],
                "design_code": first_item.get("design_code", "N/A"),
                "design_name": first_item.get("design_name", "N/A"),
                "metal_type": first_item.get("metal_type", "N/A"),
                "weight_grams": first_item.get("weight", 0),
                "metal_cost": str(metal_cost),
                "making_charges": str(making_charges_total),
                "making_charge_pct": "0" if metal_cost == 0 else str(round((making_charges_total / metal_cost) * 100, 1)),
                "subtotal": str(subtotal),
                "gst_pct": "3",
                "gst_amount": str(gst_amount),
                "total_amount": str(total_amount),
                "valid_days": 3,
                "valid_until": valid_until.strftime("%Y-%m-%d")
            }
        )
    except Exception as e:
        print(f"[EXECUTOR] Quotation PDF failed: {e}")

    try:
        await execute("""
            INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome, otp_used)
            VALUES ($1, $2, $3, $4, 'success', false)
        """, user["org_id"], user["user_id"], "generate_price_quotation",
            f"quote {customer['name']}")
    except Exception as e:
        print(f"[EXECUTOR] Audit log failed (non-fatal): {e}")

    item_summary = "\n".join(
        f"  • {i['description']}: Qty {i['qty']} × Rs.{i['unit_price']:,.0f} = Rs.{i['total']:,.0f}"
        for i in items
    )

    return {
        "success": True,
        "message": (
            f"✅ Quotation *{quotation_number}* created\n\n"
            f"Customer: *{customer['name']}*\n"
            f"Items:\n{item_summary}\n\n"
            f"Total: *Rs.{total_amount:,.0f}*\n\n"
            f"Valid for 3 days. Gold rates subject to market fluctuation."
        ),
        "pdf_bytes": pdf_bytes,
        "quotation_number": quotation_number
    }
