"""An admin asking a super admin for something (add a person, change the set-up): an email to every
super admin who can sign in, and a line in the sign-in log."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.admin_panel import auth_mail
from app.admin_panel.auth import audit
from app.admin_panel.common import CtxDep, PanelRoute
from app.db import routing_pool

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


class AskBody(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


@router.post("/ask")
async def ask(body: AskBody, ctx: CtxDep, request: Request):
    supers = await routing_pool().fetch(
        "SELECT email, name FROM panel_accounts WHERE level = 'super' AND status = 'active' "
        "ORDER BY name"
    )
    if not supers:
        raise HTTPException(
            status_code=409,
            detail="There is no super admin who can be asked right now.",
        )
    text = body.text.strip()
    sent = 0
    for s in supers:
        if await auth_mail.send_request(
            s["email"], s["name"], ctx.account_name, ctx.org_name, text
        ):
            sent += 1
    await audit(
        "ask",
        request=request,
        account_id=ctx.account_id or None,
        email=ctx.account_email,
        ok=sent > 0,
        source_key=ctx.source_key,
        detail=f"Asked the super admins ({sent} of {len(supers)} emails sent): {text[:200]}",
    )
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="The message could not be sent just now. Try again in a minute.",
        )
    return {"ok": True, "sent": sent}
