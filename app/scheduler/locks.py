"""One lock per every-minute job, so two copies of the app never run the same job at once.

The app can run as more than one copy: a second replica, or the old and the new version side by
side while a deploy switches over. Each copy runs the same every-minute jobs, and a job that
finds what is due, sends it and then marks it as sent would send everything twice if two copies
ran it at the same moment.

A Postgres advisory lock on the shared routing database lets only one copy run a job at a time.
The others skip that minute and try again the next one. The lock belongs to a transaction, so it
is let go by itself when the job finishes, fails, or the copy dies. It changes nothing about what
a job does.
"""

import hashlib
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager


def lock_key(name: str) -> int:
    """The number Postgres wants for a job's name. The same name always gives the same number, and
    the prefix keeps it apart from the number the migration tool uses."""
    digest = hashlib.blake2b(f"orchestrai-job:{name}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@asynccontextmanager
async def job_lock(pool, name: str):
    """`async with job_lock(pool, "case_reminders") as free:`  `free` is True when this copy may
    run the job now, False when another copy is running it right now."""
    async with pool.acquire() as conn, conn.transaction():
        free = await conn.fetchval(
            "SELECT pg_try_advisory_xact_lock($1)", lock_key(name)
        )
        yield bool(free)


async def run_if_free(pool, name: str, job: Callable[[], Awaitable[None]]) -> bool:
    """Run `job` unless another copy is already running it. True when it ran here."""
    async with job_lock(pool, name) as free:
        if not free:
            return False
        await job()
        return True
