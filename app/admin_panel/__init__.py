"""Redesigned admin panel: the page, its assets and the JSON endpoints under
/admin/{org}/api/v2. The classic dashboard stays available at /admin/{org}/legacy."""

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
    routing,
    workflows,
    studio,
    activity,
    org_settings,
    message_texts,
    ai_instructions,
):
    router.include_router(_module.router)
