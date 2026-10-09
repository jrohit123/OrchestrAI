"""Clears out what nothing needs any more, keeping a copy of every row first.

Three kinds of leftovers build up in each client's database, and nothing ever removed them:

* drafts that are finished (user_drafts in stage done or cancelled),
* one-time codes (otp_tokens) that have expired,
* workflow drafts someone abandoned (workflow_drafts).

A row is removed only when it is older than its organisation's retention setting, in days
(orgs.settings.retention, for example {"retention": {"drafts_days": 14}}). With nothing set, the
built-in numbers in config_store.RETENTION are used (7, 1, 30 and 180 days), and
{"retention": {"enabled": false}} switches the cleanup off for that organisation.

Each row is copied to archived_rows (as JSON, so the copy still reads fine if the table changes
later) by the same statement that removes it, so a row is never gone without its copy, and a row
can be put back from the copy. The copies are cleared after archive_days. Only counts are logged,
never what was in a row.

A database that has not been migrated yet (no archived_rows) is left alone.
"""

import json
from dataclasses import dataclass

from app.db import fetch_all
from app.logging_config import get_context_logger
from app.services import config_store

logger = get_context_logger(__name__)

BATCH = 500  # rows per statement, so a run never holds a table for long
MAX_BATCHES = 40  # and a run never goes round forever

_fetch = fetch_all  # a test can swap this for a connection to a throwaway database


@dataclass(frozen=True)
class Rule:
    table: str
    days_setting: str  # name under settings.retention (see config_store.RETENTION)
    old_when: str  # which rows are finished and older than {cut}
    reason: str  # written beside the copy
    leave_out: tuple[str, ...] = ()  # columns not worth keeping in the copy


RULES = (
    Rule(
        "user_drafts",
        "drafts_days",
        "stage IN ('done', 'cancelled') AND expires_at < {cut}",
        "finished draft",
    ),
    Rule(
        "otp_tokens",
        "otp_days",
        "expires_at < {cut}",
        "expired one-time code",
        leave_out=("otp_hash",),  # the code itself is no use to anyone after it expires
    ),
    Rule(
        "workflow_drafts",
        "workflow_drafts_days",
        "status = 'abandoned' AND updated_at < {cut}",
        "abandoned workflow draft",
    ),
    Rule(
        "case_photos",
        "photos_days",
        "case_id IS NULL AND created_at < {cut}",
        "photo that never reached a case",
        leave_out=("data",),  # the picture itself is not copied into the safe copy
    ),
)

# $1 is the organisation (NULL for rows that belong to none), $2 the number of days
_CUT = "now() - make_interval(days => $2)"
_OWNER = "org_id IS NOT DISTINCT FROM $1"


def _move_sql(rule: Rule) -> str:
    """Copy up to BATCH old rows to archived_rows and remove them, in one statement."""
    copy = "to_jsonb(gone)" + "".join(f" - '{c}'" for c in rule.leave_out)
    return f"""
        WITH gone AS (
            DELETE FROM {rule.table}
            WHERE id IN (
                SELECT id FROM {rule.table}
                WHERE {_OWNER} AND {rule.old_when.format(cut=_CUT)}
                LIMIT {BATCH}
            )
            RETURNING *
        ), kept AS (
            INSERT INTO archived_rows (source_table, row_id, org_id, row_data, reason)
            SELECT '{rule.table}', id::text, org_id, {copy}, '{rule.reason}'
            FROM gone
            RETURNING 1
        )
        SELECT count(*) AS n FROM kept
    """


def _count_sql(rule: Rule) -> str:
    return (
        f"SELECT count(*) AS n FROM {rule.table} "
        f"WHERE {_OWNER} AND {rule.old_when.format(cut=_CUT)}"
    )


_PRUNE_SQL = f"""
    WITH gone AS (
        DELETE FROM archived_rows
        WHERE id IN (
            SELECT id FROM archived_rows
            WHERE {_OWNER} AND archived_at < {_CUT}
            LIMIT {BATCH}
        )
        RETURNING 1
    )
    SELECT count(*) AS n FROM gone
"""
_PRUNE_COUNT_SQL = (
    f"SELECT count(*) AS n FROM archived_rows WHERE {_OWNER} AND archived_at < {_CUT}"
)


def _as_dict(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


async def _number(sql: str, source_key: str, org_id, days: int) -> int:
    """Run one statement that answers with a single number n."""
    rows = await _fetch(sql, org_id, days, source_key=source_key)
    return int(rows[0]["n"])


async def _until_done(sql: str, source_key: str, org_id, days: int) -> int:
    total = 0
    for _ in range(MAX_BATCHES):
        n = await _number(sql, source_key, org_id, days)
        total += n
        if n < BATCH:
            break
    return total


async def _clean_owner(
    source_key: str, org_id, settings: dict, dry_run: bool
) -> dict[str, int]:
    """One organisation's rows (or, with org_id None, the rows that belong to none)."""
    if config_store.setting(settings, "retention.enabled", True) is False:
        return {}
    done: dict[str, int] = {}
    for rule in RULES:
        days = config_store.retention_of(settings, rule.days_setting)
        sql = _count_sql(rule) if dry_run else _move_sql(rule)
        try:
            done[rule.table] = (
                await _number(sql, source_key, org_id, days)
                if dry_run
                else await _until_done(sql, source_key, org_id, days)
            )
        except Exception as e:  # one table that is missing must not stop the others
            logger.warning(f"cleanup '{source_key}': skipped {rule.table}: {e}")
    days = config_store.retention_of(settings, "archive_days")
    try:
        done["archive"] = (
            await _number(_PRUNE_COUNT_SQL, source_key, org_id, days)
            if dry_run
            else await _until_done(_PRUNE_SQL, source_key, org_id, days)
        )
    except Exception as e:
        logger.warning(f"cleanup '{source_key}': skipped the archive: {e}")
    return done


async def is_ready(source_key: str) -> bool:
    """True when the database has the table the copies go to (migration core-0010)."""
    rows = await _fetch(
        "SELECT to_regclass('public.archived_rows') IS NOT NULL AS ok",
        source_key=source_key,
    )
    return bool(rows[0]["ok"])


async def clean_source(source_key: str, *, dry_run: bool = False) -> dict[str, int]:
    """Clean one client's database. Returns how many rows went (or, with dry_run, would go)
    from each table, added up over its organisations. A dry run changes nothing."""
    if not dry_run and not await is_ready(source_key):
        logger.info(
            f"cleanup '{source_key}': not migrated yet (no archived_rows), left alone"
        )
        return {}
    orgs = await _fetch("SELECT id, settings FROM orgs", source_key=source_key)
    owners = [(o["id"], _as_dict(o["settings"])) for o in orgs] + [(None, {})]
    total: dict[str, int] = {}
    for org_id, settings in owners:
        for table, n in (
            await _clean_owner(source_key, org_id, settings, dry_run)
        ).items():
            total[table] = total.get(table, 0) + n
    moved = {t: n for t, n in total.items() if n}
    if moved:
        verb = "would remove" if dry_run else "removed"
        logger.info(
            f"cleanup '{source_key}': {verb} "
            + ", ".join(f"{t} {n}" for t, n in moved.items())
        )
    return total


async def run_cleanup(*, dry_run: bool = False) -> dict[str, dict[str, int]]:
    """Clean every client's database. One that fails does not stop the others."""
    from app.db import get_all_source_keys

    result: dict[str, dict[str, int]] = {}
    for source_key in await get_all_source_keys():
        try:
            result[source_key] = await clean_source(source_key, dry_run=dry_run)
        except Exception as e:
            logger.warning(f"cleanup '{source_key}': could not run: {e}")
    return result
