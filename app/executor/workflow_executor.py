import json
from app.adapters import inventory, crm, accounting
from app.services.otp_service import generate_and_send_otp
from app.services.whatsapp import send_text, send_buttons
from app.redis_client import set_session
from app.db import fetch_one, execute

OTP_THRESHOLD      = 50000.0   # OTP required above this
APPROVAL_THRESHOLD = 100000.0  # MD approval required above this


async def execute_intent(
    intent: str,
    entity_raw: str | None,
    user: dict,
    session_id: str,
    session: dict,
    raw_text: str
) -> str:
    org_id  = user["org_id"]
    user_id = user["user_id"]
    phone   = user["phone"]

    # ── CHECK STOCK ───────────────────────────────────
    if intent == "check_stock":
        if not entity_raw:
            return "🤔 Which product? Try: *stock gold ring*"
        result = await inventory.check_stock(org_id, entity_raw)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── CHECK OUTSTANDING ─────────────────────────────
    if intent == "check_outstanding":
        if not entity_raw:
            return "🤔 Which customer? Try: *dues Mehta*"
        result = await crm.get_outstanding(org_id, entity_raw)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── WEEKLY DUES REPORT ────────────────────────────
    if intent == "weekly_dues_report":
        result = await crm.get_all_overdue(org_id)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── CREATE INVOICE ────────────────────────────────
    if intent == "create_invoice":
        details = accounting.parse_invoice_details(raw_text)

        customer_name = details.get("customer") or entity_raw
        amount        = details.get("amount")
        qty           = details.get("qty")
        item_name     = details.get("item")

        if not customer_name:
            return "🤔 Which customer? Try: *invoice Mehta 120000*"
        if not amount:
            return "🤔 What amount? Try: *invoice Mehta 120000*\nWith items: *invoice Mehta 15 gold rings 120000*"

        # Stock check if item specified
        if item_name and qty:
            stock = await inventory.check_stock_availability(org_id, item_name, qty)
            if not stock["available"]:
                return stock["message"]

        # OTP gate
        if amount >= OTP_THRESHOLD and not session.get("otp_verified"):
            action_context = {
                "intent": "create_invoice",
                "customer_name": customer_name,
                "amount": amount,
                "qty": qty,
                "item_name": item_name,
                "raw_text": raw_text,
                "phone": phone,
                "description": f"create invoice for {customer_name} — Rs.{amount:,.0f}"
                + (f" ({qty} × {item_name})" if item_name and qty else "")
            }
            sent = await generate_and_send_otp(
                user_id=user_id,
                user_email=user["email"],
                user_name=user["user_name"],
                org_name=user["org_name"],
                action_context=action_context
            )
            if sent:
                await set_session(session_id, {
                    **session,
                    "state": "awaiting_otp",
                    "pending_intent": action_context
                })
                return (
                    f"🔐 *Verification Required*\n\n"
                    f"Invoice for *{customer_name}* — Rs.{amount:,.0f}"
                    + (f"\n{qty} × {item_name}" if item_name and qty else "")
                    + f"\n\nA 4-digit code was sent to *{user['email']}*.\n"
                    f"Reply with the code to confirm.\n\n"
                    f"_Expires in 3 minutes. Reply 'retry' to cancel._"
                )
            else:
                return "❌ Could not send verification email. Contact admin."

        # Approval gate (after OTP or for below-threshold)
        if amount >= APPROVAL_THRESHOLD and user["role"] != "owner":
            sent = await _send_approval_request(
                user=user,
                customer_name=customer_name,
                amount=amount,
                qty=qty,
                item_name=item_name,
                raw_text=raw_text,
                session_id=session_id
            )
            if sent:
                await _log(org_id, user_id, intent, raw_text, "pending_approval",
                           otp_used=session.get("otp_verified", False))
                return (
                    f"✅ Identity verified!\n\n"
                    f"Invoice for *{customer_name}* — Rs.{amount:,.0f} requires MD approval.\n"
                    f"Approval request sent. You'll be notified once approved."
                )
            else:
                return "❌ Could not find owner to send approval. Contact admin."

        # Create invoice directly
        result = await accounting.create_invoice(
            org_id=org_id,
            user_id=user_id,
            customer_name=customer_name,
            amount=amount,
            phone=phone,
            item_name=item_name,
            qty=qty
        )
        await _log(org_id, user_id, intent, raw_text,
                   "success" if result["success"] else "failed",
                   otp_used=session.get("otp_verified", False))
        # Clear otp_verified so next transaction needs fresh OTP
        await set_session(session_id, {})
        return result["message"]

    return "🤔 Didn't understand that. Type *help* for the menu."


async def resume_after_otp(user: dict, session_id: str, session: dict) -> str:
    """Called after OTP verified — resumes the pending intent."""
    pending = session.get("pending_intent")
    if not pending:
        return "✅ Verified! Please resend your original request."

    if pending.get("intent") == "create_invoice":
        amount    = pending["amount"]
        org_id    = user["org_id"]
        user_id   = user["user_id"]
        phone     = pending.get("phone", user["phone"])
        customer  = pending["customer_name"]
        item_name = pending.get("item_name")
        qty       = pending.get("qty")

        # Check approval gate after OTP
        if amount >= APPROVAL_THRESHOLD and user["role"] != "owner":
            sent = await _send_approval_request(
                user=user,
                customer_name=customer,
                amount=amount,
                qty=qty,
                item_name=item_name,
                raw_text=pending.get("raw_text", ""),
                session_id=session_id
            )
            if sent:
                await _log(org_id, user_id, "create_invoice",
                           pending.get("raw_text", ""), "pending_approval", otp_used=True)
                return (
                    f"✅ Identity verified!\n\n"
                    f"Invoice for *{customer}* — Rs.{amount:,.0f} requires MD approval.\n"
                    f"Approval request sent to Owner. You'll be notified once approved."
                )

        result = await accounting.create_invoice(
            org_id=org_id,
            user_id=user_id,
            customer_name=customer,
            amount=amount,
            phone=phone,
            item_name=item_name,
            qty=qty
        )
        await _log(org_id, user_id, "create_invoice",
                   pending.get("raw_text", ""), "success", otp_used=True)
        # Clear otp_verified so next transaction needs fresh OTP
        await set_session(session_id, {})
        return result["message"]

    return "✅ Verified! Please resend your original request."


async def _send_approval_request(
    user, customer_name, amount, qty, item_name, raw_text, session_id
) -> bool:
    """Send WhatsApp approval buttons to Owner."""
    org_id = user["org_id"]

    owner = await fetch_one("""
        SELECT u.phone, u.name FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.org_id = $1 AND r.name = 'owner'
        AND u.is_active = true AND u.phone IS NOT NULL
        LIMIT 1
    """, org_id)

    if not owner:
        return False

    context = {
        "intent": "create_invoice",
        "customer_name": customer_name,
        "amount": amount,
        "qty": qty,
        "item_name": item_name,
        "raw_text": raw_text,
        "requester_id": user["user_id"],
        "requester_phone": user["phone"],
        "requester_name": user["user_name"],
        "session_id": session_id
    }

    await execute("""
        INSERT INTO pending_approvals
        (org_id, requester_id, approver_role, intent_key, context, status)
        VALUES ($1, $2, 'owner', 'create_invoice', $3::jsonb, 'pending')
    """, org_id, user["user_id"], json.dumps(context))

    item_line = f"\nItems: {qty} × {item_name}" if item_name and qty else ""

    await send_buttons(
        to=owner["phone"],
        body=(
            f"📋 *Invoice Approval Request*\n\n"
            f"From: {user['user_name']} ({user['role']})\n"
            f"Customer: {customer_name}\n"
            f"Amount: Rs.{amount:,.0f}"
            f"{item_line}\n\n"
            f"Please approve or reject:"
        ),
        buttons=[
            {"id": "action:approve", "title": "✅ Approve"},
            {"id": "action:reject",  "title": "❌ Reject"}
        ]
    )
    return True


async def handle_approval_response(phone: str, action: str, user: dict):
    """Called when Owner taps Approve/Reject button."""
    org_id = user["org_id"]

    approval = await fetch_one("""
        SELECT id, requester_id, context
        FROM pending_approvals
        WHERE org_id = $1 AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    """, org_id)

    if not approval:
        await send_text(phone, "No pending approvals found.")
        return

    ctx = approval["context"]
    if isinstance(ctx, str):
        ctx = json.loads(ctx)

    await execute("""
        UPDATE pending_approvals
        SET status = $1, decided_by = $2, decided_at = NOW()
        WHERE id = $3
    """, "approved" if action == "action:approve" else "rejected",
        user["user_id"], approval["id"])

    if action == "action:reject":
        await send_text(phone, f"❌ Invoice rejected.")
        await send_text(
            ctx["requester_phone"],
            f"❌ Your invoice request for *{ctx['customer_name']}* "
            f"— Rs.{ctx['amount']:,.0f} was *rejected* by {user['user_name']}."
        )
        return

    # Approved — create invoice
    result = await accounting.create_invoice(
        org_id=org_id,
        user_id=ctx["requester_id"],
        customer_name=ctx["customer_name"],
        amount=ctx["amount"],
        phone=ctx["requester_phone"],
        item_name=ctx.get("item_name"),
        qty=ctx.get("qty")
    )

    await send_text(phone, f"✅ Approved.\n\n{result['message']}")
    await send_text(
        ctx["requester_phone"],
        f"✅ Your invoice was *approved* by {user['user_name']}.\n\n{result['message']}"
    )


async def _log(org_id, user_id, intent, text, outcome, otp_used=False):
    await execute("""
        INSERT INTO audit_log
        (org_id, user_id, intent_key, input_text, outcome, otp_used)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, org_id, user_id, intent, text, outcome, otp_used)
