"""Tests for the cleanup job (app/services/cleanup.py) and the core-0010 archive table.

The promise being tested: a row is never gone without a copy, only finished or expired rows older
than the organisation's number of days go, and a database that is not ready is left alone.

The tests that need a database use the Postgres on this computer given by MIGRATE_TEST_PG (see
test_migrate.py) and its throwaway databases.
"""

import asyncio
import json
from pathlib import Path

import asyncpg
import pytest

from app.scheduler import jobs
from app.services import cleanup, config_store
from tests.test_migrate import needs_pg
from tools import cleanup as preview

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "core"
    / "core-0010_archived_rows.sql"
)

# the columns the cleanup looks at, shaped like the real tables
SCHEMA = """
CREATE TABLE orgs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), settings jsonb);
CREATE TABLE user_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid, user_id uuid,
    intent_key text, fields jsonb NOT NULL DEFAULT '{}', stage varchar(30) NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE otp_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid, otp_hash text NOT NULL,
    action_context jsonb, expires_at timestamptz NOT NULL, used boolean NOT NULL DEFAULT false,
    attempts int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), org_id uuid);
CREATE TABLE workflow_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid, intent_key text,
    status varchar(30) NOT NULL, name text, chat_history jsonb NOT NULL DEFAULT '[]',
    updated_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now());
"""


# ------------------------------------------------------------ no database needed


@pytest.mark.parametrize("junk", [0, -3, "30", None, True, [5], {}])
def test_a_bad_number_of_days_falls_back_to_the_built_in_one(junk):
    # a typo can never make the cut-off "right now"
    assert (
        config_store.retention_of({"retention": {"drafts_days": junk}}, "drafts_days")
        == 7
    )


def test_days_are_whole_and_at_least_one():
    assert config_store.retention_of({"retention": {"otp_days": 3}}, "otp_days") == 3
    assert config_store.retention_of({"retention": {"otp_days": 0.2}}, "otp_days") == 1
    assert (
        config_store.retention_of({"limits": {"otp_days": 9}}, "otp_days") == 1
    )  # wrong place


def test_the_built_in_days_are_the_ones_the_job_was_agreed_with():
    assert {k: v[0] for k, v in config_store.RETENTION.items()} == {
        "drafts_days": 7,
        "otp_days": 1,
        "workflow_drafts_days": 30,
        "photos_days": 7,
        "archive_days": 180,
    }


def test_settings_may_arrive_as_text_or_be_missing():
    assert cleanup._as_dict('{"retention": {"otp_days": 2}}') == {
        "retention": {"otp_days": 2}
    }
    assert cleanup._as_dict("not json") == {}
    assert cleanup._as_dict(None) == {}


def test_the_preview_says_in_plain_words_what_would_go():
    text = preview.report(
        {
            "godrej": {
                "user_drafts": 66,
                "otp_tokens": 69,
                "workflow_drafts": 0,
                "archive": 0,
            },
            "baanganga": {},
            "newcomer": {"user_drafts": 4},
        },
        {"godrej": True, "baanganga": True, "newcomer": False},
    )
    assert "66  finished drafts" in text and "69  expired one-time codes" in text
    assert "baanganga: nothing to do" in text
    assert "newcomer: NOT READY" in text
    # a database that is not ready is not counted: nothing would be removed there
    assert "135 row(s) would be copied to archived_rows and removed" in text
    assert "Nothing was changed." in text


def test_the_preview_with_nothing_to_remove():
    text = preview.report({"godrej": {"user_drafts": 0}}, {"godrej": True})
    assert "Nothing is old enough to be removed." in text


def test_the_job_runs_once_a_day_under_its_own_lock(monkeypatch):
    seen = []

    async def fake(pool, name, job):
        seen.append((pool, name, job))
        return True

    monkeypatch.setattr(jobs, "routing_pool", lambda: "the shared pool")
    monkeypatch.setattr(jobs, "run_if_free", fake)
    asyncio.run(jobs._tick_cleanup())
    assert seen == [("the shared pool", "cleanup", cleanup.run_cleanup)]


# ------------------------------------------------------------ with a database


async def _db(world, which="alpha", migrated=True):
    conn = await asyncpg.connect(world.dsn[which])
    await conn.execute(SCHEMA)
    if migrated:
        await conn.execute(MIGRATION.read_text(encoding="utf-8"))
    return conn


def _use(monkeypatch, conn):
    async def fetch(sql, *args, source_key):
        return await conn.fetch(sql, *args)

    monkeypatch.setattr(cleanup, "_fetch", fetch)


async def _org(conn, settings=None):
    return await conn.fetchval(
        "INSERT INTO orgs (settings) VALUES ($1::jsonb) RETURNING id",
        None if settings is None else json.dumps(settings),
    )


async def _draft(conn, org, stage, days_ago):
    return await conn.fetchval(
        "INSERT INTO user_drafts (org_id, stage, intent_key, fields, expires_at, updated_at) "
        "VALUES ($1, $2, 'x', '{\"flat\": \"A-101\"}', now() - make_interval(days => $3), "
        "now() - make_interval(days => $3)) RETURNING id",
        org,
        stage,
        days_ago,
    )


async def _code(conn, org, expired_days_ago):
    await conn.execute(
        "INSERT INTO otp_tokens (org_id, otp_hash, action_context, expires_at) "
        "VALUES ($1, 'a-hash', '{\"action\": \"close\"}', "
        "now() - make_interval(days => $2))",
        org,
        expired_days_ago,
    )


async def _wf(conn, org, status, days_ago):
    await conn.execute(
        "INSERT INTO workflow_drafts (org_id, status, name, updated_at) "
        "VALUES ($1, $2, 'x', now() - make_interval(days => $3))",
        org,
        status,
        days_ago,
    )


async def _left(conn, table):
    return await conn.fetchval(f"SELECT count(*) FROM {table}")


@needs_pg
def test_the_migration_runs_twice_and_makes_the_archive(world):
    async def scenario():
        conn = await _db(world)
        try:
            await conn.execute(MIGRATION.read_text(encoding="utf-8"))  # second time
            return await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'archived_rows' ORDER BY ordinal_position"
            )
        finally:
            await conn.close()

    cols = [r["column_name"] for r in asyncio.run(scenario())]
    assert cols == [
        "id",
        "source_table",
        "row_id",
        "org_id",
        "row_data",
        "reason",
        "archived_at",
    ]


@needs_pg
def test_only_finished_old_rows_go_and_each_one_is_copied_first(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            await _draft(conn, org, "done", 10)  # goes
            await _draft(conn, org, "cancelled", 8)  # goes
            await _draft(conn, org, "done", 3)  # too recent
            await _draft(conn, org, "collecting", 30)  # not finished
            await _code(conn, org, 2)  # goes
            await _code(conn, org, 0)  # expired an hour ago at most, too recent
            await _wf(conn, org, "abandoned", 40)  # goes
            await _wf(conn, org, "abandoned", 5)  # too recent
            await _wf(conn, org, "published", 90)  # not abandoned
            await _wf(conn, org, "chatting", 90)  # not abandoned
            done = await cleanup.clean_source("alpha")
            left = {
                t: await _left(conn, t)
                for t in ("user_drafts", "otp_tokens", "workflow_drafts")
            }
            copies = await conn.fetch(
                "SELECT source_table, count(*) AS n FROM archived_rows "
                "GROUP BY source_table ORDER BY 1"
            )
            return done, left, {r["source_table"]: r["n"] for r in copies}
        finally:
            await conn.close()

    done, left, copies = asyncio.run(scenario())
    assert done == {
        "user_drafts": 2,
        "otp_tokens": 1,
        "workflow_drafts": 1,
        "archive": 0,
    }
    assert left == {"user_drafts": 2, "otp_tokens": 1, "workflow_drafts": 3}
    assert copies == {"otp_tokens": 1, "user_drafts": 2, "workflow_drafts": 1}


@needs_pg
def test_a_removed_row_can_be_put_back_from_its_copy(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            draft = await _draft(conn, org, "done", 10)
            await _code(conn, org, 2)
            before = dict(await conn.fetchrow("SELECT * FROM user_drafts"))
            await cleanup.clean_source("alpha")
            assert await _left(conn, "user_drafts") == 0
            await conn.execute(
                "INSERT INTO user_drafts SELECT (jsonb_populate_record("
                "NULL::user_drafts, row_data)).* FROM archived_rows "
                "WHERE source_table = 'user_drafts'"
            )
            after = dict(await conn.fetchrow("SELECT * FROM user_drafts"))
            code_copy = await conn.fetchval(
                "SELECT row_data FROM archived_rows WHERE source_table = 'otp_tokens'"
            )
            return draft, before, after, code_copy
        finally:
            await conn.close()

    draft, before, after, code_copy = asyncio.run(scenario())
    assert after == before and after["id"] == draft  # exactly as it was
    assert "otp_hash" not in code_copy  # the expired code itself is not kept
    assert "action_context" in code_copy


@needs_pg
def test_each_organisation_uses_its_own_numbers(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            patient = await _org(conn, {"retention": {"drafts_days": 30}})
            default = await _org(conn, {})
            off = await _org(conn, {"retention": {"enabled": False}})
            junk = await _org(conn, {"retention": {"drafts_days": 0}})  # a typo
            for org in (patient, default, off, junk):
                await _draft(conn, org, "done", 10)
            done = await cleanup.clean_source("alpha")
            kept = await conn.fetch("SELECT org_id FROM user_drafts")
            return done, {r["org_id"] for r in kept}, patient, off
        finally:
            await conn.close()

    done, kept, patient, off = asyncio.run(scenario())
    assert done["user_drafts"] == 2  # the default org and the one with the typo
    assert kept == {patient, off}  # 30 days is longer than 10; switched off stays


@needs_pg
def test_rows_that_belong_to_no_organisation_use_the_built_in_numbers(
    world, monkeypatch
):
    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            await _org(conn, {"retention": {"otp_days": 30}})
            await _code(conn, None, 5)  # nobody's: built-in number (1 day) applies
            done = await cleanup.clean_source("alpha")
            return done, await _left(conn, "otp_tokens")
        finally:
            await conn.close()

    done, left = asyncio.run(scenario())
    assert done["otp_tokens"] == 1 and left == 0


@needs_pg
def test_the_copies_are_cleared_after_their_own_number_of_days(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            short = await _org(conn, {"retention": {"archive_days": 5}})
            for who, age in ((org, 200), (org, 10), (short, 10), (short, 2)):
                await conn.execute(
                    "INSERT INTO archived_rows (source_table, org_id, row_data, archived_at) "
                    "VALUES ('user_drafts', $1, '{}', now() - make_interval(days => $2))",
                    who,
                    age,
                )
            done = await cleanup.clean_source("alpha")
            kept = await conn.fetch(
                "SELECT org_id, count(*) AS n FROM archived_rows GROUP BY org_id"
            )
            return done, {r["org_id"]: r["n"] for r in kept}, org, short
        finally:
            await conn.close()

    done, kept, org, short = asyncio.run(scenario())
    assert done["archive"] == 2  # 200 days (built-in 180) and 10 days (own 5)
    assert kept == {org: 1, short: 1}


@needs_pg
def test_a_dry_run_changes_nothing_and_does_not_need_the_archive(world, monkeypatch):
    async def scenario():
        conn = await _db(world, migrated=False)  # no archived_rows at all
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            await _draft(conn, org, "done", 10)
            await _code(conn, org, 2)
            would = await cleanup.clean_source("alpha", dry_run=True)
            return (
                would,
                await _left(conn, "user_drafts"),
                await _left(conn, "otp_tokens"),
            )
        finally:
            await conn.close()

    would, drafts, codes = asyncio.run(scenario())
    assert would["user_drafts"] == 1 and would["otp_tokens"] == 1
    assert (drafts, codes) == (1, 1)


@needs_pg
def test_a_database_without_the_archive_is_left_alone(world, monkeypatch):
    async def scenario():
        conn = await _db(world, migrated=False)
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            await _draft(conn, org, "done", 10)
            done = await cleanup.clean_source("alpha")
            return done, await _left(conn, "user_drafts")
        finally:
            await conn.close()

    # nothing may be removed when there is nowhere to keep the copy
    assert asyncio.run(scenario()) == ({}, 1)


@needs_pg
def test_a_big_backlog_goes_in_several_rounds(world, monkeypatch):
    monkeypatch.setattr(cleanup, "BATCH", 3)

    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            for _ in range(8):
                await _draft(conn, org, "done", 10)
            done = await cleanup.clean_source("alpha")
            return (
                done,
                await _left(conn, "user_drafts"),
                await _left(conn, "archived_rows"),
            )
        finally:
            await conn.close()

    done, left, copies = asyncio.run(scenario())
    assert (done["user_drafts"], left, copies) == (8, 0, 8)


@needs_pg
def test_one_missing_table_does_not_stop_the_others(world, monkeypatch):
    async def scenario():
        conn = await _db(world)
        try:
            _use(monkeypatch, conn)
            org = await _org(conn)
            await _draft(conn, org, "done", 10)
            await conn.execute("DROP TABLE workflow_drafts")  # a throwaway database
            done = await cleanup.clean_source("alpha")
            return done, await _left(conn, "user_drafts")
        finally:
            await conn.close()

    done, left = asyncio.run(scenario())
    assert done["user_drafts"] == 1 and left == 0
    assert "workflow_drafts" not in done


def test_every_database_is_cleaned_and_one_that_fails_does_not_stop_the_rest(
    monkeypatch,
):
    async def keys():
        return ["alpha", "broken", "beta"]

    async def clean(source_key, *, dry_run=False):
        if source_key == "broken":
            raise RuntimeError("the database is busy")
        return {"user_drafts": 1}

    monkeypatch.setattr("app.db.get_all_source_keys", keys)
    monkeypatch.setattr(cleanup, "clean_source", clean)
    assert asyncio.run(cleanup.run_cleanup()) == {
        "alpha": {"user_drafts": 1},
        "beta": {"user_drafts": 1},
    }
