"""
workflow_executor.py — Minimal live functions still used by webhook.py.

resume_after_otp     — called after security OTP verification
handle_approval_response — called when owner taps Approve/Reject button

Everything else that was here has been removed:
  - execute_intent        → replaced by run_agent (agent.py)
  - _get_invoice_thresholds → read from workflows table in step_interpreter
  - _parse_schedule       → replaced by manage_schedule tool in agent.py
  - _send_approval_request → now done inside step_interpreter._op_approval_gate
  - accounting.create_invoice calls → replaced by execute_pending_action
  - _log                  → done in webhook.py directly
"""
import json
from app.db import fetch_one, execute
from app.services.messaging import send_text, send_buttons
from app.redis_client import set_session


async def resume_after_otp(user: dict, session_id: str, session: dict) -> str:
    """
    Called after security session OTP is verified.
    The actual pending_action OTP path is handled in webhook.py directly
    via execute_pending_action(otp_verified=True) — this function only
    handles the legacy security_auth OTP path.
    """
    pending = session.get("pending_intent")

    if pending and pending.get("type") == "security_auth":
        await set_session(session_id, {"otp_verified": True})
        return "✅ Identity verified! Session active for 4h. Please resend your request."

    # Fallback for any other legacy pending_intent shapes
    return "✅ Verified! Please resend your original request."


async def handle_approval_response(phone: str, action: str, approval_id: str, user: dict):
    """
    Called when an owner taps Approve or Reject on a pending_approvals button.
    Resumes execution via execute_pending_action(approved=True).
    """
    from app.services.action_executor import execute_pending_action
    import hmac

    org_id = user["org_id"]

    # Fetch by primary key, scoped to org and pending status
    approval = await fetch_one("""
        SELECT id, requester_id, approver_role, intent_key, context, status
        FROM pending_approvals
        WHERE id = $1 AND org_id = $2 AND status = 'pending'
    """, approval_id, org_id, source_key=user["source_key"])

    if not approval:
        await send_text(phone, "No pending approval found or already handled.")
        return

    # Check if already decided (stale case)
    if approval["status"] != "pending":
        await send_text(phone, "This request was already handled.")
        return

    # Check approver role and permissions
    user_role_id = user.get("role_id")
    approver_role = approval["approver_role"]
    user_permissions = user.get("permissions", [])

    if user_role_id != approver_role and "approve" not in user_permissions:
        await send_text(phone, "You are not authorised to approve this request.")
        return

    # Block self-approval
    if str(approval["requester_id"]) == user["user_id"]:
        await send_text(phone, "You cannot approve your own request.")
        # Log rejection
        await execute("""
            INSERT INTO audit_log (org_id, user_id, intent_key, outcome, steps_taken)
            VALUES ($1, $2, $3, 'rejected', $4::jsonb)
        """, org_id, user["user_id"], approval["intent_key"],
            json.dumps({"approval_id": approval_id, "reason": "self_approval_blocked"}),
            source_key=user["source_key"])
        return

    ctx = approval["context"]
    if isinstance(ctx, str):
        ctx = json.loads(ctx)

    # Mark as decided
    new_status = "approved" if action == "action:approve" else "rejected"
    await execute("""
        UPDATE pending_approvals
        SET status = $1, decided_by = $2, decided_at = NOW()
        WHERE id = $3
    """,
        new_status,
        user["user_id"],
        approval["id"],
        source_key=user["source_key"]
    )

    # Extract amount from context for logging
    amount = ctx.get("pending_action", {}).get("fields", {}).get("total_amount", 0)

    # Log approval decision to audit_log
    await execute("""
        INSERT INTO audit_log (org_id, user_id, intent_key, outcome, steps_taken)
        VALUES ($1, $2, $3, $4, $5::jsonb)
    """, org_id, user["user_id"], approval["intent_key"], new_status,
        json.dumps({
            "approval_id": approval_id,
            "amount": amount,
            "decided_by": user["user_id"],
            "decided_by_name": user.get("user_name", "")
        }),
        source_key=user["source_key"]
    )

    requester_phone = ctx.get("requester_phone", "")
    requester_name  = ctx.get("requester_name", "Your colleague")

    if action == "action:reject":
        await send_text(phone, "❌ Action rejected.")
        if requester_phone:
            await send_text(
                requester_phone,
                f"❌ Your request was *rejected* by {user['user_name']}."
            )
        return

    # Approved — resume execution from where it halted
    pending_action = ctx.get("pending_action")
    if not pending_action:
        await send_text(phone, "✅ Approved, but no pending action found to execute.")
        return

    result = await execute_pending_action(
        pending_action=pending_action,
        user={
            "user_id":    ctx.get("requester_id", user["user_id"]),
            "org_id":     org_id,
            "user_name":  requester_name,
            "org_name":   user.get("org_name", ""),
            "email":      ctx.get("requester_email", ""),
            "role":       "owner",
            "role_id":    user.get("role_id", ""),
            "permissions": [],
            "phone":      requester_phone,
            "is_active":  True,
            "org_active": True,
            "source_key": user["source_key"],
        },
        phone=requester_phone,
        approved=True,
    )

    if result.get("success"):
        await send_text(phone, f"✅ Approved.\n\n{result['message']}")
        if requester_phone:
            await send_text(
                requester_phone,
                f"✅ Your request was *approved* by {user['user_name']}.\n\n{result['message']}"
            )
    else:
        await send_text(phone, f"✅ Approved but execution failed: {result.get('message', '?')}")
