"""Tests for the AI instructions screen's backend (app/admin_panel/ai_instructions.py): what it
accepts, how a save becomes a version, and that the assistant reads the new text at once.

The tests that need a database use the Postgres on this computer given by MIGRATE_TEST_PG (see
test_migrate.py) and its throwaway databases.
"""

import asyncio
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from app.admin_panel import ai_instructions as ai
from app.admin_panel import common
from app.admin_panel.common import Ctx, get_ctx
from app.services import config_store as cs
from app.services import prompt_loader
from tests.test_migrate import needs_pg

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "core"
    / "core-0009_settings_foundation.sql"
)
ORG = {"name": "Godrej Emerald", "industry": "Housing Society", "slug": "godrej"}
ORG_ID = "00000000-0000-0000-0000-000000000001"
URL = "/admin/alpha/api/v2/instructions"
BUILT_IN = prompt_loader.built_in(ORG)


@pytest.fixture(autouse=True)
def _forget():
    cs.invalidate()
    yield
    cs.invalidate()


# ------------------------------------------------------------ the layers


def test_the_layers_are_the_ones_the_assistant_reads():
    assert [k for k, _, _ in prompt_loader._layers(ORG)] == list(ai.LAYERS)


def test_the_built_in_text_is_what_the_prompt_files_say():
    base = (Path(prompt_loader.PROMPTS_DIR) / "_base.txt").read_text(encoding="utf-8")
    housing = (Path(prompt_loader.PROMPTS_DIR) / "housing_society.txt").read_text(
        encoding="utf-8"
    )
    assert BUILT_IN["agent.shared"] == base.strip()
    assert BUILT_IN["agent.industry"] == housing.strip()
    assert (
        BUILT_IN["agent.client"] == ""
    )  # no notes of its own until someone writes some
    assert prompt_loader.industry_of(ORG) == "housing_society"
    assert (
        prompt_loader.industry_of({"industry": "Jewellery-Retail"})
        == "jewellery_retail"
    )
    assert prompt_loader.industry_of({}) == ""


def test_each_layer_is_named_in_the_organisations_words():
    assert ai._name("agent.shared", ORG) == "Shared rules"
    assert ai._name("agent.industry", ORG) == "About housing society"
    assert ai._name("agent.client", ORG) == "Notes for Godrej Emerald"
    assert ai._name("agent.industry", {}) == "About this kind of business"


# ------------------------------------------------------------ what is checked before a save


def test_a_normal_text_passes():
    got = ai.check("agent.shared", "Be kind. " * 100, BUILT_IN["agent.shared"])
    assert got["ok"] and got["problems"] == []
    assert (got["characters"], got["lines"]) == (900, 1)


@pytest.mark.parametrize("key", ["agent.shared", "agent.industry"])
def test_the_main_layers_cannot_be_emptied(key):
    got = ai.check(key, "   \n ", BUILT_IN[key])
    assert not got["ok"] and "cannot be empty" in got["problems"][0]


def test_a_client_with_no_notes_is_normal():
    assert ai.check("agent.client", "", "")["ok"]


def test_a_text_that_is_too_long_or_has_a_nul_is_refused():
    assert (
        "too long"
        in ai.check("agent.client", "x" * (ai.MAX_LENGTH + 1), "")["problems"][0]
    )
    assert "cannot be saved" in ai.check("agent.client", "a\x00b", "")["problems"][0]


def test_a_text_far_shorter_than_the_one_it_replaces_is_a_warning_not_a_refusal():
    got = ai.check("agent.shared", "Be brief.", BUILT_IN["agent.shared"])
    assert (
        got["ok"] and len(got["warnings"]) == 1 and "much shorter" in got["warnings"][0]
    )
    assert not ai.check("agent.client", "Short.", "")[
        "warnings"
    ]  # nothing to be shorter than


# ------------------------------------------------------------ with a database


async def _db(world):
    conn = await asyncpg.connect(world.dsn["alpha"])
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS public.orgs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "name text, industry text, slug text)"
    )
    await conn.execute(MIGRATION.read_text(encoding="utf-8"))
    return conn


def _read_from(monkeypatch, conn):
    async def fetch(sql, *args, source_key):
        return await conn.fetch(sql, *args)

    monkeypatch.setattr(cs, "_fetch", fetch)
    cs.invalidate()


@needs_pg
def test_each_save_is_a_new_version_and_the_assistant_reads_the_newest(
    world, monkeypatch
):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            before = await prompt_loader.load_domain_prompt(ORG, "alpha")
            v1 = await ai.save_version(
                conn, "agent.client", "Towers: A and B.", "", None, "asha"
            )
            same = await ai.save_version(
                conn, "agent.client", "Towers: A and B.", "", None, "asha"
            )
            v2 = await ai.save_version(
                conn, "agent.client", "Towers: A, B and C.", "", "added C", "meera"
            )
            cs.invalidate()
            after = await prompt_loader.load_domain_prompt(ORG, "alpha")
            return before, v1, same, v2, after
        finally:
            await conn.close()

    before, v1, same, v2, after = asyncio.run(scenario())
    assert before == prompt_loader.load_prompt(ORG)  # nothing saved: exactly the files
    assert (v1, same, v2) == (1, None, 2)
    assert (
        after == before + "\n\nTowers: A, B and C."
    )  # the notes follow the other two layers


@needs_pg
def test_changing_the_shared_rules_changes_what_the_assistant_reads(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            await ai.save_version(
                conn,
                "agent.shared",
                "NEW SHARED RULES",
                BUILT_IN["agent.shared"],
                None,
                "a",
            )
            cs.invalidate()
            return await prompt_loader.load_domain_prompt(ORG, "alpha")
        finally:
            await conn.close()

    got = asyncio.run(scenario())
    assert got == "NEW SHARED RULES\n\n" + BUILT_IN["agent.industry"]


@needs_pg
def test_going_back_keeps_every_version_and_restoring_adds_a_new_one(
    world, monkeypatch
):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            await ai.save_version(conn, "agent.client", "One", "", None, "a")
            await ai.save_version(conn, "agent.client", "Two", "", None, "a")
            off = await ai.reset_to_built_in(conn, "agent.client")
            again = await ai.reset_to_built_in(conn, "agent.client")
            cs.invalidate()
            back = await prompt_loader.load_domain_prompt(ORG, "alpha")
            kept = await conn.fetchval("SELECT count(*) FROM prompts")
            restored = await ai.save_version(conn, "agent.client", "One", "", None, "a")
            return off, again, back, kept, restored
        finally:
            await conn.close()

    off, again, back, kept, restored = asyncio.run(scenario())
    assert (off, again) == (2, 0)
    assert back == prompt_loader.load_prompt(ORG)
    assert kept == 2 and restored == 3  # nothing deleted; numbering carries on


@needs_pg
def test_saving_the_built_in_text_or_emptying_the_notes_goes_back(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            shared = BUILT_IN["agent.shared"]
            await ai.save_version(conn, "agent.shared", "Changed", shared, None, "a")
            back = await ai.save_version(
                conn, "agent.shared", shared, shared, None, "a"
            )
            nothing = await ai.save_version(
                conn, "agent.shared", shared, shared, None, "a"
            )
            await ai.save_version(conn, "agent.client", "Notes", "", None, "a")
            cleared = await ai.save_version(conn, "agent.client", "", "", None, "a")
            return back, nothing, cleared
        finally:
            await conn.close()

    assert asyncio.run(scenario()) == (0, None, 0)


# ------------------------------------------------------------ the routes


def _ctx(**caps):
    return Ctx(
        source_key="alpha",
        org_id=ORG_ID,
        org_name=ORG["name"],
        caps=caps,
        actor="tester",
        closed_values=[],
    )


async def _client(world, monkeypatch, ctx, with_events=False):
    pool = await asyncpg.create_pool(world.dsn["alpha"], min_size=1, max_size=3)
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS public.orgs (id uuid PRIMARY KEY, name text, "
            "industry text, slug text)"
        )
        await conn.execute(MIGRATION.read_text(encoding="utf-8"))
        await conn.execute(
            "INSERT INTO orgs (id, name, industry, slug) VALUES ($1, $2, $3, $4)",
            ORG_ID,
            ORG["name"],
            ORG["industry"],
            ORG["slug"],
        )
        if with_events:
            await conn.execute(
                "CREATE TABLE admin_events (org_id uuid, actor_label text, area text, action text, "
                "target_type text, target_id text, summary text, before_state jsonb, "
                "after_state jsonb, created_at timestamptz DEFAULT now())"
            )

    async def get_pool(source_key):
        return pool

    async def fetch(sql, *args, source_key):
        return await pool.fetch(sql, *args)

    monkeypatch.setattr(common, "get_pool", get_pool)
    monkeypatch.setattr("app.db.get_pool", get_pool)
    monkeypatch.setattr(cs, "_fetch", fetch)
    cs.invalidate()
    app = FastAPI()
    app.include_router(ai.router)
    app.dependency_overrides[get_ctx] = lambda: ctx
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return client, pool


@needs_pg
def test_the_screen_shows_the_layers_and_a_save_applies_at_once(world, monkeypatch):
    async def scenario():
        client, pool = await _client(
            world, monkeypatch, _ctx(prompts=True, events=True), True
        )
        try:
            out = {}
            listing = (await client.get(URL)).json()
            out["ready"] = listing["ready"]
            out["layers"] = [
                (x["key"], x["name"], x["source"], x["version"])
                for x in listing["layers"]
            ]
            out["built_in_ok"] = all(
                x["text"] == x["built_in"] for x in listing["layers"]
            )
            out["assembled_before"] = (await client.get(f"{URL}/assembled")).json()[
                "text"
            ]

            put = await client.put(
                f"{URL}/agent.client",
                json={"text": "Towers: A and B.", "note": "first"},
            )
            out["put"] = (put.status_code, put.json())
            out["assembled_after"] = (await client.get(f"{URL}/assembled")).json()[
                "text"
            ]
            again = await client.put(
                f"{URL}/agent.client", json={"text": "Towers: A and B."}
            )
            out["again"] = again.json()
            client_layer = next(
                x
                for x in (await client.get(URL)).json()["layers"]
                if x["key"] == "agent.client"
            )
            out["client"] = {
                k: client_layer[k] for k in ("source", "version", "text", "updated_by")
            }
            hist = (await client.get(f"{URL}/agent.client/history")).json()["versions"]
            out["history"] = [
                (v["version"], v["text"], v["active"], v["note"]) for v in hist
            ]

            out["gone"] = (await client.delete(f"{URL}/agent.client")).json()
            out["gone_again"] = (await client.delete(f"{URL}/agent.client")).json()
            out["assembled_back"] = (await client.get(f"{URL}/assembled")).json()[
                "text"
            ]
            out["log"] = [
                r["summary"]
                for r in await pool.fetch(
                    "SELECT summary FROM admin_events ORDER BY created_at"
                )
            ]
            return out
        finally:
            await client.aclose()
            await pool.close()

    out = asyncio.run(scenario())
    assert out["ready"] is True
    assert out["layers"] == [
        ("agent.shared", "Shared rules", "built_in", None),
        ("agent.industry", "About housing society", "built_in", None),
        ("agent.client", "Notes for Godrej Emerald", "built_in", None),
    ]
    assert out["built_in_ok"]
    assert out["assembled_before"] == prompt_loader.load_prompt(ORG)
    assert out["put"] == (200, {"ok": True, "changed": True, "version": 1})
    assert out["assembled_after"] == out["assembled_before"] + "\n\nTowers: A and B."
    assert out["again"] == {"ok": True, "changed": False, "version": None}
    assert out["client"] == {
        "source": "own",
        "version": 1,
        "text": "Towers: A and B.",
        "updated_by": "tester",
    }
    assert out["history"] == [(1, "Towers: A and B.", True, "first")]
    assert out["gone"] == {"ok": True, "changed": True}
    assert out["gone_again"] == {"ok": True, "changed": False}
    assert out["assembled_back"] == out["assembled_before"]
    assert out["log"] == [
        "Changed the AI instructions: Notes for Godrej Emerald",
        "Went back to the built-in AI instructions: Notes for Godrej Emerald",
    ]


@needs_pg
def test_a_text_with_a_problem_is_refused_before_anything_is_saved(world, monkeypatch):
    async def scenario():
        client, pool = await _client(world, monkeypatch, _ctx(prompts=True))
        try:
            empty = await client.put(f"{URL}/agent.shared", json={"text": "  "})
            unknown = await client.put(f"{URL}/agent.nothing", json={"text": "x"})
            extra = await client.put(
                f"{URL}/agent.client", json={"text": "x", "other": 1}
            )
            checked = await client.post(
                f"{URL}/agent.shared/check", json={"text": "Be brief."}
            )
            saved = await pool.fetchval("SELECT count(*) FROM prompts")
            return empty, unknown, extra, checked, saved
        finally:
            await client.aclose()
            await pool.close()

    empty, unknown, extra, checked, saved = asyncio.run(scenario())
    assert empty.status_code == 400 and "cannot be empty" in empty.json()["detail"]
    assert unknown.status_code == 404
    assert extra.status_code == 422
    assert checked.json()["ok"] is True and len(checked.json()["warnings"]) == 1
    assert saved == 0


@needs_pg
def test_a_database_without_the_tables_still_shows_the_built_in_text_but_saves_nothing(
    world, monkeypatch
):
    async def scenario():
        client, pool = await _client(world, monkeypatch, _ctx(prompts=False))
        try:
            listing = (await client.get(URL)).json()
            put = await client.put(f"{URL}/agent.client", json={"text": "Notes"})
            hist = await client.get(f"{URL}/agent.client/history")
            return listing, put, hist
        finally:
            await client.aclose()
            await pool.close()

    listing, put, hist = asyncio.run(scenario())
    assert listing["ready"] is False
    assert all(x["source"] == "built_in" for x in listing["layers"])
    assert put.status_code == 409 and "core-0009" in put.json()["detail"]
    assert hist.status_code == 409
