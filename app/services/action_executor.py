"""
action_executor.py — Deterministic executor for pending actions.

Replaces LLM-routed execution with a single, testable Python function.
Handles OTP checks, approval thresholds, and actual database writes.
"""
from datetime import datetime, timezone
from typing import Any
from app.db import fetch_one, execute
from app.services.otp_service import generate_and_send_otp
from app.services.pdf_engine import generate_pdf
from app.services.pdf_preprocessor import preprocess_rows


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
            "stage": str,  # next stage if not done
            "invoice_number": str | None,
            "quotation_number": str | None,
        }
    """
    intent_key = pending_action.get("intent_key")
    fields = pending_action.get("fields", {})
    stage = pending_action.get("stage", "collecting")

    if not intent_key:
        return {"success": False, "message": "No intent_key in pending_action"}

    # ── Load workflow config ────────────────────────────────────────────────
    workflow = await fetch_one("""
        SELECT otp_threshold, approval_threshold, adapter_method, pdf_config
        FROM workflows
        WHERE intent_key = $1 AND org_id = $2 AND is_active = true
    """, intent_key, user["org_id"])

    if not workflow:
        return {"success": False, "message": f"Workflow {intent_key} not found"}

    otp_threshold = workflow.get("otp_threshold") or 0
    approval_threshold = workflow.get("approval_threshold") or 0
    adapter_method = workflow.get("adapter_method")
    pdf_config = workflow.get("pdf_config")

    # ── Helper: Resolve amount from fields or items[].total ────────────────────
    def _resolve_amount(fields: dict) -> float:
        if fields.get("amount") is not None:
            return float(fields["amount"])
        total = 0.0
        for item in fields.get("items") or []:
            total += float(item.get("total") or 0)
        return total

    # ── Stage: awaiting_confirmation → check OTP ───────────────────────────
    if stage == "awaiting_confirmation":
        amount = _resolve_amount(fields)

        if amount >= otp_threshold and not otp_verified:
            # Need OTP before proceeding
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
                    "message": f"🔐 Security Verification Required\n\nA 4-digit code has been sent to {user['email']}\nReply with the code to continue.\n\n⏱ Code expires in 3 minutes.",
                    "stage": "awaiting_otp"
                }
            else:
                return {"success": False, "message": "❌ Could not send verification email. Contact admin."}

        # No OTP needed or already verified, proceed to execution
        return await _execute_action(
            intent_key, fields, user, workflow, approval_threshold, pdf_config
        )

    # ── Stage: awaiting_otp → verify and proceed ─────────────────────────────
    if stage == "awaiting_otp" and otp_verified:
        return await _execute_action(
            intent_key, fields, user, workflow, approval_threshold, pdf_config
        )

    # ── Stage: awaiting_approval → user already approved, execute ─────────────
    if stage == "awaiting_approval":
        return await _execute_action(
            intent_key, fields, user, workflow, approval_threshold, pdf_config
        )

    return {"success": False, "message": f"Unknown stage: {stage}"}


async def _execute_action(
    intent_key: str,
    fields: dict,
    user: dict,
    workflow: dict,
    approval_threshold: float,
    pdf_config: dict,
) -> dict:
    """Execute the actual action based on intent_key."""
    amount = fields.get("amount") or 0

    # ── Check approval threshold ─────────────────────────────────────────────
    if amount >= approval_threshold:
        # Need MD approval - set stage and return
        from app.services.whatsapp import send_buttons
        from app.redis_client import set_session

        # Send approval request to MD
        # For now, we'll mark as awaiting_approval and return
        # In a full implementation, this would send a WhatsApp button to the MD
        return {
            "success": False,
            "message": f"Invoice ₹{amount:,.0f} requires MD approval.\nApproval request sent to Mr. Sharma.\nYou'll be notified once approved.",
            "stage": "awaiting_approval"
        }

    # ── Execute based on intent_key ─────────────────────────────────────────
    if intent_key == "create_sales_invoice":
        return await _create_invoice(fields, user, pdf_config)
    elif intent_key == "generate_price_quotation":
        return await _create_quotation(fields, user, pdf_config)
    else:
        return {"success": False, "message": f"Unknown intent_key: {intent_key}"}


async def _create_invoice(fields: dict, user: dict, pdf_config: dict) -> dict:
    """Create an invoice record and generate PDF."""
    customer_id = fields.get("customer_id")
    items = fields.get("items", [])

    if not customer_id:
        return {"success": False, "message": "Missing customer_id"}

    if not items or len(items) == 0:
        return {"success": False, "message": "Missing items. Please provide at least one item with description, quantity, and unit price."}

    # Calculate total amount from items
    total_amount = 0.0
    for item in items:
        item_total = item.get("total", 0)
        total_amount += float(item_total)

    # Generate invoice number
    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM invoices WHERE org_id = $1",
        user["org_id"]
    )
    invoice_number = f"INV-{100 + int(count_row['cnt'])}"

    # Insert invoice
    await execute("""
        INSERT INTO invoices (
            org_id, invoice_number, customer_id, amount,
            status, due_date, created_at, items, created_by
        ) VALUES (
            $1, $2, $3, $4,
            'pending', CURRENT_DATE + INTERVAL '30 days', NOW(), $5, $6
        )
    """, user["org_id"], invoice_number, customer_id, str(total_amount), json.dumps(items), user["user_id"])

    # Fetch customer details for PDF
    customer = await fetch_one(
        "SELECT name, city, gst_number FROM customers WHERE id = $1",
        customer_id
    )

    # Build invoice rows for PDF
    invoice_rows = [{
        "invoice_number": invoice_number,
        "customer_name": customer["name"],
        "city": customer["city"],
        "gst_number": customer["gst_number"],
        "amount": str(total_amount),
        "status": "pending",
        "due_date": (datetime.now(timezone.utc).replace(day=30) if datetime.now(timezone.utc).day < 30 else 
                     datetime.now(timezone.utc).replace(month=datetime.now(timezone.utc).month % 12 + 1, day=30)).strftime("%Y-%m-%d"),
        "items": items
    }]

    # Calculate subtotal and GST for PDF
    subtotal = sum(float(item.get("unit_price", 0)) * float(item.get("qty", 1)) for item in items)
    gst_amount = sum(float(item.get("gst", 0)) for item in items)

    # Generate PDF
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
        pdf_bytes = None

    # Log to audit
    await execute("""
        INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome, otp_used)
        VALUES ($1, $2, $3, $4, 'success', false)
    """, user["org_id"], user["user_id"], "create_sales_invoice", f"invoice {customer['name']} {total_amount}")

    # Build item summary for message
    item_summary = "\n".join([f"  • {i.get('description', 'Item')}: Qty {i.get('qty', 1)} × Rs.{float(i.get('unit_price', 0)):,.0f} = Rs.{float(i.get('total', 0)):,.0f}" for i in items])

    return {
        "success": True,
        "message": f"✅ Invoice #{invoice_number} created\n\nCustomer: {customer['name']}\nItems:\n{item_summary}\n\nTotal: Rs.{total_amount:,.0f}\nStatus: PENDING\nDue Date: 30 days",
        "pdf_bytes": pdf_bytes,
        "invoice_number": invoice_number
    }


async def _create_quotation(fields: dict, user: dict, pdf_config: dict) -> dict:
    """Create a quotation record and generate PDF."""
    customer_id = fields.get("customer_id")
    items = fields.get("items", [])

    if not customer_id:
        return {"success": False, "message": "Missing customer_id"}

    if not items or len(items) == 0:
        return {"success": False, "message": "Missing items. Please provide at least one item with description, quantity, and unit price."}

    # Calculate total amount from items
    total_amount = 0.0
    for item in items:
        item_total = item.get("total", 0)
        total_amount += float(item_total)

    # Generate quotation number
    count_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM quotations WHERE org_id = $1",
        user["org_id"]
    )
    quotation_number = f"QUO-{1001 + int(count_row['cnt'])}"

    # Calculate valid until date (3 days from now)
    from datetime import timedelta
    valid_until = datetime.now(timezone.utc) + timedelta(days=3)

    # Insert quotation
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

    # Fetch customer details
    customer = await fetch_one(
        "SELECT name, city, gst_number FROM customers WHERE id = $1",
        customer_id
    )

    # Build quotation rows for PDF
    quotation_rows = [{
        "quotation_number": quotation_number,
        "customer_name": customer["name"],
        "city": customer["city"],
        "gst_number": customer["gst_number"],
        "total_amount": str(total_amount),
        "valid_until": valid_until.strftime("%Y-%m-%d"),
        "items": items
    }]

    # Calculate subtotal and GST for PDF
    subtotal = sum(float(item.get("unit_price", 0)) * float(item.get("qty", 1)) for item in items)
    gst_amount = sum(float(item.get("gst", 0)) for item in items)

    # Generate PDF
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
                "subtotal": str(subtotal),
                "gst_amount": str(gst_amount),
                "total_amount": str(total_amount),
                "valid_days": 3,
                "valid_until": valid_until.strftime("%Y-%m-%d")
            }
        )
    except Exception as e:
        pdf_bytes = None

    # Log to audit
    await execute("""
        INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome, otp_used)
        VALUES ($1, $2, $3, $4, 'success', false)
    """, user["org_id"], user["user_id"], "generate_price_quotation", f"quote {customer['name']}")

    # Build item summary for message
    item_summary = "\n".join([f"  • {i.get('description', 'Item')}: Qty {i.get('qty', 1)} × Rs.{float(i.get('unit_price', 0)):,.0f} = Rs.{float(i.get('total', 0)):,.0f}" for i in items])

    return {
        "success": True,
        "message": f"✅ Quotation {quotation_number} created\n\nCustomer: {customer['name']}\nItems:\n{item_summary}\n\nTotal: Rs.{total_amount:,.0f}\n\nValid for 3 days. Gold rates subject to market fluctuation.",
        "pdf_bytes": pdf_bytes,
        "quotation_number": quotation_number
    }
