"""The page shell and its two assets (one stylesheet, one script)."""

import html

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from app.admin_panel.ui import APP_CSS, APP_JS, VERSION
from app.db import get_all_source_keys

router = APIRouter()

_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/admin-assets/panel.css?v={version}">
</head>
<body data-org="{org}">
<div id="app"><p class="boot">Loading…</p></div>
<noscript><p class="boot">This dashboard needs JavaScript.</p></noscript>
<script src="/admin-assets/panel.js?v={version}"></script>
</body>
</html>
"""


def render_page(org_slug: str) -> str:
    return _SHELL.format(version=VERSION, org=html.escape(org_slug, quote=True))


@router.get("/admin/{org_slug}", response_class=HTMLResponse)
async def admin_page(org_slug: str):
    """The dashboard. The address segment is the organisation's key in the routing database, so a
    new organisation needs no change here."""
    if org_slug not in await get_all_source_keys():
        raise HTTPException(status_code=404, detail=f"Unknown org '{org_slug}'")
    return HTMLResponse(
        content=render_page(org_slug),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


def _asset(request: Request, body: str, media_type: str) -> Response:
    headers = {"ETag": f'"{VERSION}"', "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/admin-assets/panel.css")
async def panel_css(request: Request):
    return _asset(request, APP_CSS, "text/css; charset=utf-8")


@router.get("/admin-assets/panel.js")
async def panel_js(request: Request):
    return _asset(request, APP_JS, "application/javascript; charset=utf-8")
