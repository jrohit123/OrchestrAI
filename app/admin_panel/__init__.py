"""The admin panel: the page at /admin/{org}, its assets, and the JSON endpoints under
/admin/{org}/api/v2."""

from fastapi import APIRouter

from app.admin_panel import (
    activity,
    ai_instructions,
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
    workflows,
)

router = APIRouter()
for _module in (
    pages,
    meta,
    overview,
    cases,
    people,
    roles,
    routing,
    workflows,
    studio,
    activity,
    org_settings,
    message_texts,
    ai_instructions,
):
    router.include_router(_module.router)
