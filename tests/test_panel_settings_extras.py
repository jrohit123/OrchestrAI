"""The logo and "end every conversation" endpoints of the Settings screen. They came over from the
classic dashboard, so they are tested here with a pretend database and a pretend Redis."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import redis_client
from app.admin_panel import org_settings as os_
from app.admin_panel.common import Ctx, get_ctx

LOGO = "/admin/alpha/api/v2/logo"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def panel(monkeypatch):
    seen = {"updates": [], "logo": None, "cleared": []}
    ctx = Ctx(
        source_key="alpha",
        org_id="o1",
        org_name="Alpha",
        caps={},
        actor="test",
        closed_values=["closed"],
    )
    app = FastAPI()
    app.include_router(os_.router)
    app.dependency_overrides[get_ctx] = lambda: ctx

    async def execute(sql, *args, source_key):
        seen["updates"].append((sql, args))

    async def fetch_one(sql, *args, source_key):
        return {"logo_url": seen["logo"]}

    async def clear_all_sessions(org_id):
        seen["cleared"].append(org_id)

    monkeypatch.setattr(os_, "execute", execute)
    monkeypatch.setattr(os_, "fetch_one", fetch_one)
    monkeypatch.setattr(redis_client, "clear_all_sessions", clear_all_sessions)
    return TestClient(app), seen


def test_the_logo_is_read_from_the_organisation(panel):
    client, seen = panel
    seen["logo"] = "data:image/png;base64,AAAA"
    assert client.get(LOGO).json() == {"logo_url": "data:image/png;base64,AAAA"}


def test_a_picture_becomes_the_logo(panel):
    client, seen = panel
    got = client.post(LOGO, files={"logo_file": ("logo.png", PNG, "image/png")})
    assert got.status_code == 200
    uri = got.json()["logo_url"]
    assert uri.startswith("data:image/png;base64,")
    sql, args = seen["updates"][0]
    assert sql == "UPDATE orgs SET logo_url = $1 WHERE id = $2"
    assert args == (uri, "o1")


@pytest.mark.parametrize(
    ("files", "words"),
    [
        ({"logo_file": ("a.txt", b"hello", "text/plain")}, "must be an image"),
        (
            {"logo_file": ("a.png", b"0" * (os_.LOGO_MAX_BYTES + 1), "image/png")},
            "too large",
        ),
        ({"other": ("a.png", PNG, "image/png")}, "logo_file is required"),
    ],
)
def test_anything_that_is_not_a_small_picture_is_refused_and_nothing_changes(
    panel, files, words
):
    client, seen = panel
    got = client.post(LOGO, files=files)
    assert got.status_code == 400 and words in got.json()["detail"]
    assert seen["updates"] == []


def test_ending_every_conversation_asks_redis_for_this_organisation_only(panel):
    client, seen = panel
    got = client.post("/admin/alpha/api/v2/sessions/clear")
    assert got.status_code == 200 and got.json() == {"cleared": True}
    assert seen["cleared"] == ["o1"]
