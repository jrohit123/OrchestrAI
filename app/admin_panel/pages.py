"""The page shell and its two assets (one stylesheet, one script)."""

import html

from fastapi import APIRouter, Request, Response

from app.admin_panel.ui import APP_CSS, APP_JS, VERSION

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
