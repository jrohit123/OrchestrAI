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
    chat_menu,
    message_texts,
    meta,
    org_settings,
    overview,
    pages,
    people,
    people_import,
    reminders,
    roles,
    routing,
    studio,
    triggers,
    usecases,
    whatsapp_flows,
    whatsapp_templates,
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
    people_import,
    roles,
    routing,
    reminders,
    workflows,
    studio,
    triggers,
    activity,
    org_settings,
    message_texts,
    ai_instructions,
    whatsapp_flows,
    whatsapp_templates,
    chat_menu,
    usecases,
):
    router.include_router(_module.router)
