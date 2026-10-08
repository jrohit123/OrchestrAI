"""The dashboard's page, script and style: sent compressed, carrying safety headers, and a friendly
page for an address that names no organisation (UX-046, UX-054, UX-045)."""

import re

import pytest
from fastapi.testclient import TestClient

from app.admin_panel import pages
from app.admin_panel.ui import APP_CSS, APP_JS, VERSION
from app.main import app

client = TestClient(app)
ASSETS = [
    ("/admin-assets/panel.js", APP_JS),
    ("/admin-assets/panel.css", APP_CSS),
]


# ------------------------------------------------------------ compression


@pytest.mark.parametrize(("url", "text"), ASSETS, ids=["js", "css"])
def test_the_script_and_style_are_sent_compressed_to_a_browser_that_accepts_it(
    url, text
):
    r = client.get(url, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()
    assert r.text == text  # what the browser unpacks is exactly the page's code
    assert int(r.headers["content-length"]) < len(text.encode("utf-8")) / 2


@pytest.mark.parametrize(("url", "text"), ASSETS, ids=["js", "css"])
@pytest.mark.parametrize("accept", ["identity", "gzip;q=0", "br"])
def test_a_browser_that_does_not_take_gzip_gets_the_plain_text(url, text, accept):
    r = client.get(url, headers={"Accept-Encoding": accept})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers
    assert r.text == text
    assert "accept-encoding" in r.headers["vary"].lower()


@pytest.mark.parametrize("accept", ["gzip", "identity"])
@pytest.mark.parametrize("weak", [False, True])
def test_a_browser_that_already_has_the_file_is_told_so_in_either_form(accept, weak):
    url = "/admin-assets/panel.js"
    tag = client.get(url, headers={"Accept-Encoding": accept}).headers["etag"]
    sent = ("W/" + tag) if weak else tag
    again = client.get(url, headers={"Accept-Encoding": accept, "If-None-Match": sent})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == tag


def test_the_tag_of_one_form_does_not_stand_for_the_other():
    url = "/admin-assets/panel.js"
    plain = client.get(url, headers={"Accept-Encoding": "identity"}).headers["etag"]
    packed = client.get(url, headers={"Accept-Encoding": "gzip"}).headers["etag"]
    assert plain != packed and VERSION in plain and VERSION in packed
    wrong = client.get(url, headers={"Accept-Encoding": "gzip", "If-None-Match": plain})
    assert wrong.status_code == 200


# ------------------------------------------------------------ safety headers


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/admin-assets/panel.js",
        "/admin-assets/panel.css",
        "/admin/zz/api/v2/bootstrap",
    ],
)
def test_every_dashboard_answer_carries_the_safety_headers(path):
    h = client.get(path).headers
    csp = h["content-security-policy"]
    for want in [
        "default-src 'self'",
        "script-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'self'",
    ]:
        assert want in csp, want
    assert "unsafe-eval" not in csp and "script-src 'self' 'unsafe" not in csp
    assert h["x-frame-options"] == "SAMEORIGIN"
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "same-origin"


def test_the_rest_of_the_service_is_left_as_it_was():
    h = client.get("/").headers
    assert "content-security-policy" not in h and "x-frame-options" not in h


def test_the_page_loads_nothing_from_another_site_so_the_policy_cannot_break_it():
    # the policy lets scripts, styles and calls come from this address only; a link to a font, a
    # script or a stylesheet elsewhere would be blocked, so adding one must be a deliberate choice
    assert "@import" not in APP_CSS
    assert not re.search(r"url\(\s*['\"]?https?:", APP_CSS)
    shell = pages.render_page("x")
    assert not re.search(r"(?:src|href)=[\"']https?:", shell)
    assert not re.search(r"fetch\(\s*['\"`]https?:", APP_JS)


# ------------------------------------------------------------ an address that names no organisation


def _known(monkeypatch, keys):
    async def fake():
        return keys

    monkeypatch.setattr(pages, "get_all_source_keys", fake)


def test_an_address_that_names_no_organisation_gets_a_friendly_page_not_raw_json(
    monkeypatch,
):
    _known(monkeypatch, ["alpha"])
    r = client.get("/admin/nosuchplace")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "detail" not in r.text and "Unknown org" not in r.text
    assert 'href="/admin"' in r.text and "sign-in" in r.text.lower()
    assert "content-security-policy" in r.headers


def test_the_friendly_page_neither_repeats_the_address_nor_names_any_organisation(
    monkeypatch,
):
    _known(monkeypatch, ["alpha", "beta"])
    r = client.get("/admin/%3Cb%3Enosuchplace")
    assert r.status_code == 404
    for word in ["nosuchplace", "<b>", "alpha", "beta"]:
        assert word not in r.text, word


def test_a_known_organisation_still_gets_its_dashboard(monkeypatch):
    _known(monkeypatch, ["alpha"])
    r = client.get("/admin/alpha")
    assert r.status_code == 200 and 'data-org="alpha"' in r.text


def test_the_friendly_page_has_a_style_of_its_own():
    assert ".lost{" in APP_CSS
