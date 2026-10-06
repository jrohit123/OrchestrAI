"""Tests for the every-minute job lock (app/scheduler/locks.py).

Two copies of the app must never run the same every-minute job at once, or a reminder would be
sent twice. The tests that need a database use the Postgres on this computer given by
MIGRATE_TEST_PG (see test_migrate.py) and its throwaway "control" database.
"""

import asyncio

import asyncpg
import pytest

from app.scheduler import locks
from tests.test_migrate import needs_pg
from tools import migrate


def test_each_job_has_its_own_stable_number():
    number = locks.lock_key("case_reminders")
    assert number == locks.lock_key("case_reminders")
    assert number != locks.lock_key("scheduled_reports")
    assert -(2**63) <= number < 2**63
    assert number != migrate.LOCK_KEY  # never clashes with the migration tool's lock


async def _pool(world):
    return await asyncpg.create_pool(world.dsn["control"], min_size=1, max_size=4)


@needs_pg
def test_two_copies_cannot_run_the_same_job_at_once(world):
    async def scenario():
        pool = await _pool(world)
        try:
            async with (
                locks.job_lock(pool, "case_reminders") as mine,
                locks.job_lock(pool, "case_reminders") as other_copy,
                locks.job_lock(pool, "scheduled_reports") as other_job,
            ):
                return mine, other_copy, other_job
        finally:
            await pool.close()

    # the second copy is turned away; a different job is not affected
    assert asyncio.run(scenario()) == (True, False, True)


@needs_pg
def test_the_lock_is_let_go_when_the_job_ends_or_fails(world):
    async def scenario():
        pool = await _pool(world)
        seen = []
        try:
            async with locks.job_lock(pool, "case_reminders") as free:
                seen.append(free)
            async with locks.job_lock(pool, "case_reminders") as free:
                seen.append(free)
            with pytest.raises(RuntimeError):
                async with locks.job_lock(pool, "case_reminders") as free:
                    seen.append(free)
                    raise RuntimeError("the job failed")
            async with locks.job_lock(pool, "case_reminders") as free:
                seen.append(free)
        finally:
            await pool.close()
        return seen

    assert asyncio.run(scenario()) == [True, True, True, True]


@needs_pg
def test_a_copy_that_dies_lets_go_of_its_lock(world):
    async def scenario():
        dying = await asyncpg.connect(world.dsn["control"])
        pool = await _pool(world)
        try:
            await dying.execute("BEGIN")
            assert await dying.fetchval(
                "SELECT pg_try_advisory_xact_lock($1)", locks.lock_key("case_reminders")
            )
            async with locks.job_lock(pool, "case_reminders") as while_alive:
                pass
            dying.terminate()  # the copy crashes: its connection is simply gone
            await asyncio.sleep(0.5)
            async with locks.job_lock(pool, "case_reminders") as after:
                pass
            return while_alive, after
        finally:
            await pool.close()

    assert asyncio.run(scenario()) == (False, True)


@needs_pg
def test_a_job_that_is_already_running_is_not_started_again(world):
    runs = []

    async def slow_job():
        runs.append("start")
        await asyncio.sleep(0.3)
        runs.append("end")

    async def scenario():
        pool = await _pool(world)
        try:
            together = await asyncio.gather(
                locks.run_if_free(pool, "case_reminders", slow_job),
                locks.run_if_free(pool, "case_reminders", slow_job),
            )
            later = await locks.run_if_free(pool, "case_reminders", slow_job)
            return sorted(together), later
        finally:
            await pool.close()

    # started together: one runs, one is turned away; a minute later it runs again
    assert asyncio.run(scenario()) == ([False, True], True)
    assert runs == ["start", "end", "start", "end"]


@needs_pg
def test_a_failing_job_is_not_hidden_and_does_not_keep_the_lock(world):
    async def broken():
        raise RuntimeError("the job failed")

    async def fine():
        return None

    async def scenario():
        pool = await _pool(world)
        try:
            with pytest.raises(RuntimeError):
                await locks.run_if_free(pool, "case_reminders", broken)
            return await locks.run_if_free(pool, "case_reminders", fine)
        finally:
            await pool.close()

    assert asyncio.run(scenario()) is True
