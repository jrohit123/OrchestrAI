"""The admin panel: the page at /admin/{org}, its assets, and the JSON endpoints under
/admin/{org}/api/v2."""

from fastapi import APIRouter

from app.admin_panel import (
    activity,
    ai_instructions,
    ask,
    auth_routes,
    case_buttons,
    cases,
    message_texts,
    meta,
    org_settings,
    overview,
    pages,
    people,
    roles,
    routing,
    studio,
    whatsapp_flows,
    workflows,
)

router = APIRouter()
for _module in (
    pages,
    auth_routes,
    meta,
    overview,
    cases,
    case_buttons,
    ask,
    people,
    roles,
    routing,
    workflows,
    studio,
    activity,
    org_settings,
    message_texts,
    ai_instructions,
    whatsapp_flows,
):
    router.include_router(_module.router)
