"""The classic dashboard is gone: no page, no address, no link. The new dashboard has everything
it still needs of the old one under /admin/{org}/api/v2."""

import importlib.util

from app.admin_panel.ui import APP_CSS, APP_JS
from app.main import app


def _routes():
    return {
        (r.path, m)
        for r in app.routes
        for m in getattr(r, "methods", None) or ()
        if m != "HEAD"
    }


def test_the_classic_router_is_not_in_the_code_any_more():
    assert importlib.util.find_spec("app.routers.admin") is None


def test_no_page_or_address_of_the_classic_dashboard_is_left():
    paths = {p for p, _ in _routes()}
    assert not [p for p in paths if "/legacy" in p]
    assert not [p for p in paths if "workflow-builder" in p]
    # every address under /admin/{org}/api now belongs to the new dashboard
    stray = [
        p
        for p in paths
        if p.startswith("/admin/{org_slug}/api/")
        and not p.startswith("/admin/{org_slug}/api/v2/")
    ]
    assert not stray, stray


def test_the_new_dashboard_still_has_its_page_and_what_it_took_from_the_old_one():
    routes = _routes()
    for want in [
        ("/admin/{org_slug}", "GET"),
        ("/admin-assets/panel.js", "GET"),
        ("/admin-assets/panel.css", "GET"),
        ("/admin/{org_slug}/api/v2/overview", "GET"),
        ("/admin/{org_slug}/api/v2/activity", "GET"),
        ("/admin/{org_slug}/api/v2/activity/session", "GET"),
        ("/admin/{org_slug}/api/v2/logo", "GET"),
        ("/admin/{org_slug}/api/v2/logo", "POST"),
        ("/admin/{org_slug}/api/v2/sessions/clear", "POST"),
    ]:
        assert want in routes, want


def test_the_screens_have_no_link_to_the_classic_dashboard():
    text = (APP_JS + APP_CSS).lower()
    assert "/legacy" not in text
    assert "classic" not in text


def test_the_buttons_say_what_they_make():
    # each screen has its own main button now (Flows: New flow, or New building block on that tab)
    assert "New flow" in APP_JS
    assert "New building block" in APP_JS
    assert "New workflow" not in APP_JS
