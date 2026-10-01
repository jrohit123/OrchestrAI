"""Redesigned admin panel: the page, its assets and the JSON endpoints under
/admin/{org}/api/v2. The classic dashboard stays available at /admin/{org}/legacy."""

from fastapi import APIRouter

from app.admin_panel import (
    activity,
    cases,
    meta,
    overview,
    pages,
    people,
    routing,
    workflows,
)

router = APIRouter()
for _module in (pages, meta, overview, cases, people, routing, workflows, activity):
    router.include_router(_module.router)
