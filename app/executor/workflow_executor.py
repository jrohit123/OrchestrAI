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
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)


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
    Called when an approver taps Approve or Reject on a pending_approvals
    button. If the workflow's gate has more levels left in its
    required_queue, this creates the NEXT level's pending_approvals row and
    notifies that approver instead of resuming — the actual workflow only
    resumes once the last level in the chain clears. See
    step_interpreter._op_approval_gate for how the queue is built.
    """
    from app.services.action_executor import execute_pending_action
    from app.services.identity import resolve_identity

    org_id = user["org_id"]

    # Fetch by primary key, scoped to org and pending status
    approval = await fetch_one("""
        SELECT id, requester_id, approver_role, intent_key, context, status, gate_id, level
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

    # Check approver role and permissions.
    # BUGFIX: this used to compare user["role_id"] (a uuid) against
    # approval["approver_role"], which step_interpreter._op_approval_gate has
    # always populated with a role NAME (see approver_role_name there) — the
    # two never matched, so this check silently always fell through to the
    # generic "approve" permission below. Compare role name to role name.
    user_role_name    = user.get("role")
    approver_role     = approval["approver_role"]
    user_permissions  = user.get("permissions", [])

    if user_role_name != approver_role and "approve" not in user_permissions:
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
            "gate_id": approval.get("gate_id"),
            "level": approval.get("level"),
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

    # ── Multi-level chain: advance to the next level instead of resuming ────
    required_queue = ctx.get("required_queue") or []
    queue_index     = ctx.get("queue_index", 0)

    if queue_index + 1 < len(required_queue):
        nxt = required_queue[queue_index + 1]
        next_ctx = {**ctx, "queue_index": queue_index + 1}
        next_approver = await _find_approver_for_role(nxt.get("role"), org_id, user["source_key"])

        next_row = await execute("""
            INSERT INTO pending_approvals
            (org_id, requester_id, approver_role, intent_key, context, status, gate_id, level)
            VALUES ($1, $2, $3, $4, $5::jsonb, 'pending', $6, $7)
            RETURNING id
        """, org_id, ctx.get("requester_id"), nxt.get("role") or "approver",
            approval["intent_key"], json.dumps(next_ctx, default=str),
            nxt.get("gate_id"), nxt.get("level"), source_key=user["source_key"])
        next_approval_id = next_row[0]["id"]

        await send_text(phone, "✅ Your approval is recorded. Escalating to the next approver.")
        if next_approver:
            level_note = f" — level {nxt.get('level')} of {len(required_queue)}"
            await send_buttons(
                to=next_approver["phone"],
                body=(
                    f"📋 *Approval Request*{level_note}\n\n"
                    f"From: {requester_name}\n"
                    f"Action: {approval['intent_key']}\n"
                    f"Amount: Rs.{amount:,.0f}\n\n"
                    f"Please approve or reject:"
                ),
                buttons=[
                    {"id": f"action:approve:{next_approval_id}", "title": "✅ Approve"},
                    {"id": f"action:reject:{next_approval_id}",  "title": "❌ Reject"}
                ]
            )
        else:
            logger.warning(
                f"No active approver found for role '{nxt.get('role')}' "
                f"(org {org_id}) — next approval level has no one to notify."
            )
        return

    # ── Last (or only) level cleared — resume the actual workflow ───────────
    pending_action = ctx.get("pending_action")
    if not pending_action:
        await send_text(phone, "✅ Approved, but no pending action found to execute.")
        return

    # BUGFIX: this used to hand-build a user dict with permissions=[], which
    # made execute_pending_action's permission check ("intent_key not in
    # perms") deny EVERY approval resume unconditionally — approved actions
    # never actually executed. Resolve the requester's real user record
    # (permissions, role, role_id) instead of reconstructing a fake one.
    requester_user = await resolve_identity(requester_phone) if requester_phone else None
    if not requester_user:
        # Requester's phone couldn't be resolved (e.g. missing on record) —
        # fall back to a minimal user carrying just enough permission to
        # pass the check for THIS workflow, so the already-approved action
        # doesn't get silently rejected.
        requester_user = {
            "user_id":     ctx.get("requester_id", user["user_id"]),
            "org_id":      org_id,
            "user_name":   requester_name,
            "org_name":    user.get("org_name", ""),
            "email":       ctx.get("requester_email", ""),
            "role":        None,
            "role_id":     None,
            "permissions": [approval["intent_key"]],
            "phone":       requester_phone,
            "is_active":   True,
            "org_active":  True,
            "source_key":  user["source_key"],
        }

    result = await execute_pending_action(
        pending_action=pending_action,
        user=requester_user,
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


async def _find_approver_for_role(role_name: str | None, org_id: str, source_key: str) -> dict | None:
    """Mirrors step_interpreter._find_approver — kept as a separate copy since
    this module intentionally has no import-time dependency on step_interpreter."""
    if role_name:
        return await fetch_one("""
            SELECT u.phone, u.name, u.id, r.name as role_name FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE u.org_id = $1 AND r.name = $2
              AND u.is_active = true AND u.phone IS NOT NULL
            LIMIT 1
        """, org_id, role_name, source_key=source_key)
    return await fetch_one("""
        SELECT u.phone, u.name, u.id, r.name as role_name FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.org_id = $1 AND r.is_approver = true
          AND u.is_active = true AND u.phone IS NOT NULL
        LIMIT 1
    """, org_id, source_key=source_key)
