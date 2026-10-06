"""Tests for app/services/config_store.py and the core-0009 tables it reads.

The promise being tested: nothing changes until someone changes it. With no rows, a missing
table or an unreachable database, every read gives the built-in text.

The tests that need a database use the Postgres on this computer given by MIGRATE_TEST_PG (see
test_migrate.py) and its throwaway databases.
"""

import asyncio
from pathlib import Path

import asyncpg
import pytest

from app.services import config_store as cs
from app.services import prompt_loader
from tests.test_migrate import needs_pg

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "core"
    / "core-0009_settings_foundation.sql"
)
HOUSING = "housing_society"


# ------------------------------------------------------------ no database needed


def test_fill_puts_values_in_and_leaves_unknown_words_alone():
    assert cs.fill("Hello {name}, case {case}", {"name": "Asha"}) == (
        "Hello Asha, case {case}"
    )


def test_setting_reads_a_nested_value():
    s = {"limits": {"draft_stale_minutes": 45}, "retention": {"chats_days": 365}}
    assert cs.setting(s, "retention.chats_days") == 365
    assert cs.setting(s, "retention.nothing", "x") == "x"
    assert cs.setting(None, "limits.a", 7) == 7
    assert cs.setting({"limits": 5}, "limits.a", 7) == 7


@pytest.mark.parametrize("junk", [0, -3, "30", None, True, [5], {}])
def test_limit_ignores_zero_negative_and_junk(junk):
    # a typo can never switch a limit off
    assert cs.limit({"limits": {"x": junk}}, "x", 30) == 30


def test_limit_uses_a_good_number():
    assert cs.limit({"limits": {"x": 45}}, "x", 30) == 45
    assert cs.limit({}, "x", 30) == 30


def test_with_no_database_every_read_is_the_built_in_text():
    assert asyncio.run(cs.prompt(None, "agent.shared", "built in")) == "built in"
    assert asyncio.run(cs.message(None, "otp.sent", "Hi {n}", n="Asha")) == "Hi Asha"


def test_the_prompt_is_the_files_when_nothing_is_saved():
    org = {"industry": "Housing Society", "slug": "godrej"}
    assert asyncio.run(prompt_loader.load_domain_prompt(org, None)) == (
        prompt_loader.load_prompt(org)
    )
    assert prompt_loader.load_prompt(org)  # and there is something to compare


# ------------------------------------------------------------ with a database


async def _connect(world, which="alpha", migrated=True):
    conn = await asyncpg.connect(world.dsn[which])
    if migrated:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS public.orgs "
            "(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text)"
        )
        await conn.execute(MIGRATION.read_text(encoding="utf-8"))
    return conn


def _read_from(monkeypatch, conn, counter=None):
    async def fetch(sql, *args, source_key):
        if counter is not None:
            counter.append(sql)
        return await conn.fetch(sql, *args)

    monkeypatch.setattr(cs, "_fetch", fetch)
    cs.invalidate()


async def _add(conn, table, key, scope, ref, version, body, active=True):
    cols = "key, scope, scope_ref, version, body, is_active"
    await conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ($1, $2, $3, $4, $5, $6)",
        key,
        scope,
        ref,
        version,
        body,
        active,
    )


@needs_pg
def test_the_migration_runs_twice_and_keeps_its_rules(world):
    async def scenario():
        conn = await _connect(world)
        try:
            await conn.execute(MIGRATION.read_text(encoding="utf-8"))  # second time
            cols = await conn.fetch(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name = 'orgs' AND column_name IN ('timezone', 'locale')"
            )
            await _add(conn, "prompts", "k", "tenant", "", 1, "one")
            with pytest.raises(asyncpg.UniqueViolationError):
                await _add(conn, "prompts", "k", "tenant", "", 1, "again")
            with pytest.raises(asyncpg.CheckViolationError):
                await _add(conn, "prompts", "k", "nowhere", "", 1, "x")
            with pytest.raises(asyncpg.CheckViolationError):
                await _add(conn, "system_messages", "k", "tenant", "", 0, "x")
            return {r["column_name"]: r["column_default"] for r in cols}
        finally:
            await conn.close()

    found = asyncio.run(scenario())
    assert "Asia/Kolkata" in found["timezone"]
    assert "en-IN" in found["locale"]


@needs_pg
def test_the_client_beats_its_industry_beats_the_shared_text(world, monkeypatch):
    async def scenario():
        conn = await _connect(world)
        try:
            _read_from(monkeypatch, conn)
            seen = []

            async def ask(pack=HOUSING):
                cs.invalidate()
                return await cs.prompt("alpha", "agent.industry", "BUILT IN", pack=pack)

            seen.append(await ask())  # nothing saved
            await _add(conn, "prompts", "agent.industry", "global", "", 1, "G1")
            await _add(conn, "prompts", "agent.industry", "global", "", 2, "G2")
            seen.append(await ask())  # the newest shared version
            await _add(conn, "prompts", "agent.industry", "pack", HOUSING, 1, "P1")
            seen.append(await ask())  # its industry's
            seen.append(await ask("jewellery"))  # another industry does not see it
            await _add(conn, "prompts", "agent.industry", "tenant", "", 1, "T1")
            await _add(conn, "prompts", "agent.industry", "tenant", "", 2, "T2", False)
            seen.append(
                await ask()
            )  # the client's own; the switched-off version is ignored
            return seen
        finally:
            await conn.close()

    assert asyncio.run(scenario()) == ["BUILT IN", "G2", "P1", "G2", "T1"]


@needs_pg
def test_messages_fill_in_and_fall_back_when_the_text_is_broken(world, monkeypatch):
    async def scenario():
        conn = await _connect(world)
        try:
            _read_from(monkeypatch, conn)
            out = [await cs.message("alpha", "otp.sent", "Code {code}", code="123")]
            await _add(
                conn,
                "system_messages",
                "otp.sent",
                "tenant",
                "",
                1,
                "Your code is {code}",
            )
            cs.invalidate()
            out.append(await cs.message("alpha", "otp.sent", "Code {code}", code="123"))
            await _add(
                conn, "system_messages", "otp.sent", "tenant", "", 2, "Broken {code"
            )
            cs.invalidate()
            out.append(await cs.message("alpha", "otp.sent", "Code {code}", code="123"))
            return out
        finally:
            await conn.close()

    # built in, then the client's wording, then a broken text falls back to the built-in one
    assert asyncio.run(scenario()) == ["Code 123", "Your code is 123", "Code 123"]


@needs_pg
def test_a_database_without_the_tables_or_one_that_fails_gives_the_built_in_text(
    world, monkeypatch
):
    async def scenario():
        conn = await _connect(world, "beta", migrated=False)  # never migrated
        try:
            asked = []
            _read_from(monkeypatch, conn, asked)
            first = await cs.prompt("beta", "k", "BUILT IN")
            second = await cs.prompt("beta", "k", "BUILT IN")  # kept: not asked again
            return first, second, len(asked)
        finally:
            await conn.close()

    first, second, asked = asyncio.run(scenario())
    assert (first, second) == ("BUILT IN", "BUILT IN")
    assert asked == 1  # the first table was missing, so it stopped there

    async def broken(sql, *args, source_key):
        raise RuntimeError("the database is busy")

    monkeypatch.setattr(cs, "_fetch", broken)
    cs.invalidate()
    assert asyncio.run(cs.prompt("beta", "k", "BUILT IN")) == "BUILT IN"


@needs_pg
def test_what_was_read_is_kept_until_it_is_forgotten(world, monkeypatch):
    async def scenario():
        conn = await _connect(world)
        try:
            asked = []
            _read_from(monkeypatch, conn, asked)
            await cs.prompt("alpha", "k", "d")
            await cs.prompt("alpha", "k", "d")
            kept = len(asked)  # two tables, read once
            await _add(conn, "prompts", "k", "tenant", "", 1, "new")
            still = await cs.prompt(
                "alpha", "k", "d"
            )  # not yet visible: kept in memory
            cs.invalidate("alpha")  # the dashboard does this after a save
            now = await cs.prompt("alpha", "k", "d")
            return kept, still, now
        finally:
            await conn.close()

    assert asyncio.run(scenario()) == (2, "d", "new")


@needs_pg
def test_the_assistants_prompt_takes_a_saved_industry_text(world, monkeypatch):
    org = {"industry": "Housing Society", "slug": "no-such-client"}
    files = prompt_loader.load_prompt(org)
    industry_file = prompt_loader._read(prompt_loader.PROMPTS_DIR / f"{HOUSING}.txt")

    async def scenario():
        conn = await _connect(world)
        try:
            _read_from(monkeypatch, conn)
            same = await prompt_loader.load_domain_prompt(org, "alpha")
            await _add(
                conn, "prompts", "agent.industry", "pack", HOUSING, 1, "HOUSING RULES"
            )
            cs.invalidate()
            changed = await prompt_loader.load_domain_prompt(org, "alpha")
            return same, changed
        finally:
            await conn.close()

    same, changed = asyncio.run(scenario())
    assert same == files  # an empty table changes nothing
    assert changed == files.replace(industry_file, "HOUSING RULES")
