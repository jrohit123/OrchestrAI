"""The page shell and its two assets (one stylesheet, one script)."""

import gzip
import html

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from app.admin_panel.ui import APP_CSS, APP_JS, VERSION
from app.db import get_all_source_keys

router = APIRouter()

# What every answer of the dashboard carries (its page, its script and style, and the calls it makes).
# The page loads nothing from another site, so a script may only come from this address; no other
# site may put the dashboard in a frame; the browser must not guess what kind of file it got; and
# the address of a dashboard page is not passed on to other sites. An image may come from any https
# address because an organisation's logo is a link to wherever it is kept.
PANEL_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'"
    ),
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}

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

# Shown for an address that names no organisation. It does not repeat what was typed and does not
# say which organisations exist.
_NOT_FOUND = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/admin-assets/panel.css?v={version}">
</head>
<body>
<main class="lost">
<div class="lgn-card">
<h1>We cannot find that page</h1>
<p>The organisation in this address is not one we know. The address may have a typing mistake. Check the link you were given, or sign in and choose your organisation from the list.</p>
<p><a class="btn primary" href="/admin">Go to the sign-in page</a></p>
</div>
</main>
</body>
</html>
"""


def render_page(org_slug: str) -> str:
    return _SHELL.format(version=VERSION, org=html.escape(org_slug, quote=True))


@router.get("/admin", response_class=HTMLResponse)
async def super_page():
    """The page for super admins (and for anyone who signs in here without an organisation in the
    address): it shows the sign-in, then the list of organisations. It holds no data."""
    return HTMLResponse(
        content=render_page(""),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/admin/{org_slug}", response_class=HTMLResponse)
async def admin_page(org_slug: str):
    """The dashboard. The address segment is the organisation's key in the routing database, so a
    new organisation needs no change here."""
    if org_slug not in await get_all_source_keys():
        return HTMLResponse(
            content=_NOT_FOUND.format(version=VERSION),
            status_code=404,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )
    return HTMLResponse(
        content=render_page(org_slug),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


# The script is about 400 KB of text and shrinks to about a quarter when compressed, which is the
# difference between a slow and a quick first page on a phone. Both assets are compressed once,
# when the server starts, so a request costs nothing extra.
_PACKED = {
    "css": gzip.compress(APP_CSS.encode("utf-8"), compresslevel=9, mtime=0),
    "js": gzip.compress(APP_JS.encode("utf-8"), compresslevel=9, mtime=0),
}


def _wants_gzip(request: Request) -> bool:
    for part in request.headers.get("accept-encoding", "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() in ("gzip", "x-gzip"):
            return params.replace(" ", "") not in ("q=0", "q=0.0", "q=0.00", "q=0.000")
    return False


def _etag_matches(header: str | None, etag: str) -> bool:
    """A proxy may turn a strong tag into a weak one (W/"…") when it compresses; both count."""
    tags = [t.strip().removeprefix("W/") for t in (header or "").split(",")]
    return etag in tags or "*" in tags


def _asset(request: Request, kind: str, body: str, media_type: str) -> Response:
    packed = _wants_gzip(request)
    etag = f'"{VERSION}-gzip"' if packed else f'"{VERSION}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    if packed:
        return Response(
            content=_PACKED[kind],
            media_type=media_type,
            headers={**headers, "Content-Encoding": "gzip"},
        )
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/admin-assets/panel.css")
async def panel_css(request: Request):
    return _asset(request, "css", APP_CSS, "text/css; charset=utf-8")


@router.get("/admin-assets/panel.js")
async def panel_js(request: Request):
    return _asset(request, "js", APP_JS, "application/javascript; charset=utf-8")
