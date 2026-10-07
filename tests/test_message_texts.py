"""Tests for the Messages screen's backend (app/admin_panel/message_texts.py): what it accepts, how a
save becomes a version, and that the assistant uses the new wording at once.

The tests that need a database use the Postgres on this computer given by MIGRATE_TEST_PG (see
test_migrate.py) and its throwaway databases.
"""

import asyncio
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from app.admin_panel import common, message_texts
from app.admin_panel.common import Ctx, get_ctx
from app.services import config_store as cs
from app.services.messages import MESSAGES, say
from tests.test_migrate import needs_pg

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "core"
    / "core-0009_settings_foundation.sql"
)
KEY = "otp.cooldown"  # "⏳ Please wait {wait_seconds}s before requesting another code."
MSG = MESSAGES[KEY]
SEED = MIGRATION.with_name("core-0011_standard_texts.sql")
URL = "/admin/alpha/api/v2/messages"


@pytest.fixture(autouse=True)
def _forget():
    cs.invalidate()
    yield
    cs.invalidate()


# ------------------------------------------------------------ what a wording is checked for


def test_a_good_wording_is_accepted_and_previewed_with_the_examples():
    got = message_texts.check(MSG, "Hold on {wait_seconds} seconds, please.")
    assert got == {
        "ok": True,
        "problems": [],
        "warnings": [],
        "preview": "Hold on 30 seconds, please.",
    }


def test_dropping_a_value_is_a_warning_not_a_refusal():
    got = message_texts.check(MSG, "Please wait a bit.")
    assert got["ok"] is True
    assert len(got["warnings"]) == 1 and "{wait_seconds}" in got["warnings"][0]
    assert got["preview"] == "Please wait a bit."


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("Wait {seconds}s", "{seconds} is not something this message knows"),
        ("Wait {wait_seconds", "is not closed"),
        ("Wait } now", "is not closed"),
        ("Wait {wait_seconds!r}", "Only plain names"),
        ("Wait {wait_seconds:>5}", "Only plain names"),
        ("Wait {wait_seconds.real}", "is not something this message knows"),
        ("Wait {wait_seconds[0]}", "is not something this message knows"),
        ("Wait {0}", "is not something this message knows"),
        ("Wait {}", "is not something this message knows"),
        ("   ", "The text is empty."),
        ("x" * (message_texts.MAX_LENGTH + 1), "too long"),
    ],
)
def test_a_wording_that_would_go_wrong_is_refused_in_plain_words(text, words):
    got = message_texts.check(MSG, text)
    assert got["ok"] is False and got["preview"] is None
    assert any(words in p for p in got["problems"]), got["problems"]


def test_the_refusal_lists_what_can_be_used():
    got = message_texts.check(MESSAGES["onboarding.code_sent"], "Hi {nope}")
    assert "{email}" in got["problems"][0] and "{expiry_minutes}" in got["problems"][0]
    assert (
        "none"
        in message_texts.check(MESSAGES["draft.cancelled"], "x {a}")["problems"][0]
    )


def test_braces_written_twice_show_as_one():
    got = message_texts.check(MSG, "Wait {wait_seconds}s {{ok}}")
    assert got["ok"] and got["preview"] == "Wait 30s {ok}"


def test_every_built_in_wording_passes_its_own_check_with_nothing_to_warn_about():
    for m in MESSAGES.values():
        got = message_texts.check(m, m.text)
        assert got["ok"] and not got["warnings"], m.key


# ------------------------------------------------------------ with a database


async def _db(world):
    conn = await asyncpg.connect(world.dsn["alpha"])
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS public.orgs "
        "(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text)"
    )
    await conn.execute(MIGRATION.read_text(encoding="utf-8"))
    return conn


def _read_from(monkeypatch, conn):
    async def fetch(sql, *args, source_key):
        return await conn.fetch(sql, *args)

    monkeypatch.setattr(cs, "_fetch", fetch)
    cs.invalidate()


@needs_pg
def test_each_save_is_a_new_version_and_the_newest_is_the_one_used(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            out = {}
            out["nothing"] = await say("alpha", KEY, wait_seconds=9)
            out["v1"] = await message_texts.save_version(
                conn, MSG, "One {wait_seconds}", None, "asha"
            )
            out["same"] = await message_texts.save_version(
                conn, MSG, "One {wait_seconds}", None, "asha"
            )
            out["v2"] = await message_texts.save_version(
                conn, MSG, "Two {wait_seconds}", "shorter", "meera"
            )
            cs.invalidate()
            out["used"] = await say("alpha", KEY, wait_seconds=9)
            out["rows"] = [
                (r["version"], r["body"], r["created_by"], r["note"])
                for r in await conn.fetch(
                    "SELECT version, body, created_by, note FROM system_messages ORDER BY version"
                )
            ]
            return out
        finally:
            await conn.close()

    out = asyncio.run(scenario())
    assert out["nothing"] == "⏳ Please wait 9s before requesting another code."
    assert (out["v1"], out["same"], out["v2"]) == (1, None, 2)
    assert out["used"] == "Two 9"
    assert out["rows"] == [
        (1, "One {wait_seconds}", "asha", None),
        (2, "Two {wait_seconds}", "meera", "shorter"),
    ]


@needs_pg
def test_going_back_to_the_built_in_wording_keeps_every_version(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            await message_texts.save_version(conn, MSG, "One {wait_seconds}", None, "a")
            await message_texts.save_version(conn, MSG, "Two {wait_seconds}", None, "a")
            off = await message_texts.reset_to_built_in(conn, KEY)
            again = await message_texts.reset_to_built_in(conn, KEY)
            cs.invalidate()
            back = await say("alpha", KEY, wait_seconds=9)
            kept = await conn.fetchval("SELECT count(*) FROM system_messages")
            # a new save carries on from the numbers already used, and an old wording can be restored
            restored = await message_texts.save_version(
                conn, MSG, "One {wait_seconds}", None, "a"
            )
            cs.invalidate()
            return (
                off,
                again,
                back,
                kept,
                restored,
                await say("alpha", KEY, wait_seconds=9),
            )
        finally:
            await conn.close()

    off, again, back, kept, restored, now = asyncio.run(scenario())
    assert (off, again) == (2, 0)
    assert back == "⏳ Please wait 9s before requesting another code."
    assert kept == 2  # nothing was deleted
    assert restored == 3 and now == "One 9"


@needs_pg
def test_saving_the_built_in_wording_is_going_back_to_it(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _read_from(monkeypatch, conn)
            await message_texts.save_version(conn, MSG, "One {wait_seconds}", None, "a")
            went_back = await message_texts.save_version(conn, MSG, MSG.text, None, "a")
            nothing = await message_texts.save_version(conn, MSG, MSG.text, None, "a")
            cs.invalidate()
            return went_back, nothing, await say("alpha", KEY, wait_seconds=9)
        finally:
            await conn.close()

    went_back, nothing, now = asyncio.run(scenario())
    assert (went_back, nothing) == (0, None)
    assert now == "⏳ Please wait 9s before requesting another code."


# ------------------------------------------------------------ the routes


def _app(ctx):
    app = FastAPI()
    app.include_router(message_texts.router)
    app.dependency_overrides[get_ctx] = lambda: ctx
    return app


def _ctx(**caps):
    return Ctx(
        source_key="alpha",
        org_id="00000000-0000-0000-0000-000000000001",
        org_name="Alpha",
        caps=caps,
        actor="tester",
        closed_values=[],
    )


async def _client(world, monkeypatch, ctx, with_events=False, seeded=False):
    pool = await asyncpg.create_pool(world.dsn["alpha"], min_size=1, max_size=3)
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS public.orgs "
            "(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text)"
        )
        await conn.execute(MIGRATION.read_text(encoding="utf-8"))
        if seeded:  # the standard wording stored in the database (migration core-0011)
            await conn.execute(SEED.read_text(encoding="utf-8"))
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
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(ctx)), base_url="http://test"
    )
    return client, pool


@needs_pg
def test_the_screen_lists_every_message_and_a_save_shows_up_and_applies_at_once(
    world, monkeypatch
):
    async def scenario():
        client, pool = await _client(
            world, monkeypatch, _ctx(texts=True, events=True), True
        )
        try:
            out = {}
            listing = (await client.get(URL)).json()
            out["ready"] = listing["ready"]
            out["count"] = sum(len(g["messages"]) for g in listing["groups"])
            out["sources"] = {
                m["source"] for g in listing["groups"] for m in g["messages"]
            }
            out["before"] = await say(
                "alpha", KEY, wait_seconds=9
            )  # now it is kept for a minute

            put = await client.put(
                f"{URL}/{KEY}",
                json={"text": "Hold on {wait_seconds}s.", "note": "friendlier"},
            )
            out["put"] = (put.status_code, put.json())
            out["after"] = await say(
                "alpha", KEY, wait_seconds=9
            )  # not a minute later: at once

            again = await client.put(
                f"{URL}/{KEY}", json={"text": "Hold on {wait_seconds}s."}
            )
            out["again"] = again.json()
            mine = next(
                m
                for g in (await client.get(URL)).json()["groups"]
                for m in g["messages"]
                if m["key"] == KEY
            )
            out["mine"] = {
                k: mine[k]
                for k in ("source", "version", "text", "updated_by", "default")
            }
            hist = (await client.get(f"{URL}/{KEY}/history")).json()["versions"]
            out["history"] = [
                (v["version"], v["text"], v["active"], v["note"]) for v in hist
            ]

            gone = await client.delete(f"{URL}/{KEY}")
            out["gone"] = gone.json()
            out["gone_again"] = (await client.delete(f"{URL}/{KEY}")).json()
            out["back"] = await say("alpha", KEY, wait_seconds=9)
            out["history_after"] = [
                (v["version"], v["active"])
                for v in (await client.get(f"{URL}/{KEY}/history")).json()["versions"]
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
    assert out["ready"] is True and out["count"] == len(MESSAGES)
    assert out["sources"] == {"built_in"}
    assert out["before"] == "⏳ Please wait 9s before requesting another code."
    assert out["put"] == (200, {"ok": True, "changed": True, "version": 1})
    assert out["after"] == "Hold on 9s."
    assert out["again"] == {"ok": True, "changed": False, "version": None}
    assert out["mine"] == {
        "source": "own",
        "version": 1,
        "text": "Hold on {wait_seconds}s.",
        "updated_by": "tester",
        "default": MSG.text,
    }
    assert out["history"] == [(1, "Hold on {wait_seconds}s.", True, "friendlier")]
    assert out["gone"] == {"ok": True, "changed": True}
    assert out["gone_again"] == {"ok": True, "changed": False}
    assert out["back"] == "⏳ Please wait 9s before requesting another code."
    assert out["history_after"] == [(1, False)]  # kept, switched off
    assert out["log"] == [
        f"Changed the message “{MSG.name}”",
        f"Went back to the standard wording of “{MSG.name}”",
    ]


@needs_pg
def test_a_wording_with_a_problem_is_refused_before_anything_is_saved(
    world, monkeypatch
):
    async def scenario():
        client, pool = await _client(world, monkeypatch, _ctx(texts=True))
        try:
            bad = await client.put(f"{URL}/{KEY}", json={"text": "Wait {seconds}s"})
            unknown = await client.put(f"{URL}/no.such_message", json={"text": "x"})
            extra = await client.put(f"{URL}/{KEY}", json={"text": "x", "other": 1})
            checked = await client.post(
                f"{URL}/{KEY}/check", json={"text": "Hold {wait_seconds}"}
            )
            saved = await pool.fetchval("SELECT count(*) FROM system_messages")
            return bad, unknown, extra, checked, saved
        finally:
            await client.aclose()
            await pool.close()

    bad, unknown, extra, checked, saved = asyncio.run(scenario())
    assert bad.status_code == 400 and "{seconds}" in bad.json()["detail"]
    assert unknown.status_code == 404
    assert extra.status_code == 422
    assert checked.json()["preview"] == "Hold 30"
    assert saved == 0


@needs_pg
def test_a_database_without_the_tables_still_lists_the_built_in_wording_but_saves_nothing(
    world, monkeypatch
):
    async def scenario():
        client, pool = await _client(world, monkeypatch, _ctx(texts=False))
        try:
            listing = (await client.get(URL)).json()
            put = await client.put(
                f"{URL}/{KEY}", json={"text": "Hold on {wait_seconds}s."}
            )
            hist = await client.get(f"{URL}/{KEY}/history")
            return listing, put, hist
        finally:
            await client.aclose()
            await pool.close()

    listing, put, hist = asyncio.run(scenario())
    assert listing["ready"] is False
    assert all(
        m["source"] == "built_in" for g in listing["groups"] for m in g["messages"]
    )
    assert put.status_code == 409 and "core-0009" in put.json()["detail"]
    assert hist.status_code == 409


# ------------------------------------------------------------ with the standard wording stored (core-0011)


@needs_pg
def test_with_the_standard_wording_stored_every_message_says_what_it_always_said(
    world, monkeypatch
):
    async def scenario():
        conn = await _db(world)
        try:
            await conn.execute(SEED.read_text(encoding="utf-8"))
            _read_from(monkeypatch, conn)
            stored = await conn.fetchval(
                "SELECT count(*) FROM system_messages WHERE scope = 'global' AND is_active"
            )
            said = {
                m.key: await say("alpha", m.key, **m.example) for m in MESSAGES.values()
            }
            # and it really is read from the database, not from the code
            await conn.execute(
                "UPDATE system_messages SET body = 'From the database {wait_seconds}' WHERE key = $1",
                KEY,
            )
            cs.invalidate()
            return stored, said, await say("alpha", KEY, wait_seconds=9)
        finally:
            await conn.close()

    stored, said, from_db = asyncio.run(scenario())
    assert stored == len(MESSAGES)
    for m in MESSAGES.values():
        assert said[m.key] == cs.fill(m.text, m.example), m.key
    assert from_db == "From the database 9"


@needs_pg
def test_the_screen_calls_stored_wording_standard_and_going_back_goes_to_it(
    world, monkeypatch
):
    async def scenario():
        client, pool = await _client(
            world, monkeypatch, _ctx(texts=True, events=True), True, seeded=True
        )
        try:
            out = {}

            async def mine():
                found = (await client.get(URL)).json()
                return next(
                    m for g in found["groups"] for m in g["messages"] if m["key"] == KEY
                )

            listing = (await client.get(URL)).json()
            every = [m for g in listing["groups"] for m in g["messages"]]
            out["sources"] = {m["source"] for m in every}
            out["same"] = all(m["text"] == m["standard"] == m["default"] for m in every)
            out["put"] = (
                await client.put(
                    f"{URL}/{KEY}", json={"text": "Hold on {wait_seconds}s."}
                )
            ).json()
            now = await mine()
            out["own"] = (now["source"], now["version"], now["standard"] == MSG.text)
            out["says"] = await say("alpha", KEY, wait_seconds=9)
            # saving the standard wording is going back to it
            out["back"] = (
                await client.put(f"{URL}/{KEY}", json={"text": MSG.text})
            ).json()
            out["after"] = (
                (await mine())["source"],
                await say("alpha", KEY, wait_seconds=9),
            )
            # a later migration changes the standard wording: that is what people get, and what
            # "the same as the standard" means from then on
            await pool.execute(
                "UPDATE system_messages SET body = $1 WHERE key = $2 AND scope = 'global'",
                "Hmm {wait_seconds}",
                KEY,
            )
            cs.invalidate()
            changed = await mine()
            out["changed"] = (
                changed["source"],
                changed["text"],
                changed["default"] == MSG.text,
            )
            out["says_now"] = await say("alpha", KEY, wait_seconds=9)
            out["same_as_standard"] = (
                await client.put(f"{URL}/{KEY}", json={"text": "Hmm {wait_seconds}"})
            ).json()
            out["code_text"] = (
                await client.put(f"{URL}/{KEY}", json={"text": MSG.text})
            ).json()
            out["gone"] = (await client.delete(f"{URL}/{KEY}")).json()
            out["end"] = await say("alpha", KEY, wait_seconds=9)
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
    assert out["sources"] == {"shared"} and out["same"]
    assert out["put"] == {"ok": True, "changed": True, "version": 1}
    assert out["own"] == ("own", 1, True)
    assert out["says"] == "Hold on 9s."
    assert out["back"] == {"ok": True, "changed": True, "version": 0}
    assert out["after"] == (
        "shared",
        "⏳ Please wait 9s before requesting another code.",
    )
    assert out["changed"] == ("shared", "Hmm {wait_seconds}", True)
    assert out["says_now"] == "Hmm 9"
    assert out["same_as_standard"] == {"ok": True, "changed": False, "version": None}
    assert out["code_text"] == {"ok": True, "changed": True, "version": 2}
    assert out["gone"] == {"ok": True, "changed": True}
    assert out["end"] == "Hmm 9"
    assert out["log"] == [
        f"Changed the message “{MSG.name}”",
        f"Went back to the standard wording of “{MSG.name}”",
        f"Changed the message “{MSG.name}”",
        f"Went back to the standard wording of “{MSG.name}”",
    ]
