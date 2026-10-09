"""Texts and settings the dashboard can change, with the built-in version as the fallback.

Each client's database can hold three kinds of things the code used to carry itself:

* AI instructions (table `prompts`): the written text the assistant follows,
* the texts the assistant sends by itself (table `system_messages`),
* settings (orgs.settings), such as limits and how long old rows are kept.

Every read goes through this module, and it keeps one promise: **nothing changes until someone
changes it.**

* A row in the database wins when there is one. A client's own text beats its industry's, which
  beats the shared one, and of those the newest active version wins.
* With no row, the text built into the code or the prompt files is used, exactly as before.
* A database that has no such table yet (not migrated), or that cannot be reached, gives the
  built-in text too. A read never fails and never holds a reply up for long: the rows are read
  once a minute and kept in memory.
"""

import json
import string
import time

import asyncpg

from app.db import fetch_all
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# The time zone the whole app runs on today (db.py, the schedulers, the greetings). It is the
# default of orgs.timezone (migration core-0009); choosing another is not wired up yet.
DEFAULT_TIMEZONE = "Asia/Kolkata"

TTL_SECONDS = 60  # how long what was read is kept
RETRY_SECONDS = 15  # after a failed read, look again soon

# The numbers an organisation can change (orgs.settings.limits / .retention), with the number the
# code has always used: name -> (built-in number, smallest allowed, largest allowed). The code and
# the Settings screen both read this, so each built-in number exists in one place only.
LIMITS: dict[str, tuple[int, int, int]] = {
    "draft_stale_minutes": (30, 5, 1440),  # an unfinished request is dropped after this
    "confirm_stale_minutes": (
        10,
        2,
        240,
    ),  # an unanswered "yes to save?" is dropped after this
    "reprompt_max": (3, 1, 10),  # how often the assistant re-asks before starting over
    "photo_max": (5, 1, 20),  # photos kept on one request
    "photo_max_mb": (5, 1, 16),  # the largest photo that is saved, in megabytes
    "turn_wait_seconds": (
        15,
        1,
        60,
    ),  # a second message from the same person waits this long for the first to be answered
    "turn_lock_seconds": (
        90,
        10,
        600,
    ),  # a turn holds the person's lock at most this long (a crash cannot block them longer)
    "reminder_max_failures": (
        3,
        1,
        20,
    ),  # passes in which nobody could be reached before a case reminder is given up
    "photo_hold_minutes": (
        15,
        1,
        120,
    ),  # a photo sent first waits this long for its request
    "hold_days": (
        3,
        1,
        30,
    ),  # a message WhatsApp could not deliver is kept this long for the person to collect
    "hold_max": (
        5,
        1,
        20,
    ),  # at most this many messages are kept for one person (the oldest go first)
    "door_margin_minutes": (
        60,
        1,
        600,
    ),  # WhatsApp's 24 hours are counted with this much to spare
}
RETENTION: dict[str, tuple[int, int, int]] = {
    "drafts_days": (7, 1, 3650),  # finished drafts
    "otp_days": (1, 1, 365),  # expired one-time codes
    "workflow_drafts_days": (30, 1, 3650),  # abandoned workflow drafts
    "photos_days": (7, 1, 3650),  # photos nobody attached to a case
    "archive_days": (180, 1, 3650),  # the copies kept of what was removed
}

_fetch = fetch_all  # a test can swap this for a connection to a throwaway database
_cache: dict[
    tuple[str, str], tuple[float, dict]
] = {}  # (database, what) -> (until, value)


def invalidate(source_key: str | None = None) -> None:
    """Forget what was read, so the next read looks at the database again. The dashboard calls
    this after a save, so a change shows at once on the copy that saved it."""
    if source_key is None:
        _cache.clear()
    else:
        for key in [k for k in _cache if k[0] == source_key]:
            del _cache[key]


def _keep(bucket: dict, index: tuple, row) -> None:
    """Keep the newest version for each (scope, scope_ref) of one text."""
    layers = bucket.setdefault(index, {})
    where = (row["scope"], row["scope_ref"])
    if where not in layers or row["version"] > layers[where][0]:
        layers[where] = (row["version"], row["body"])


async def _load(source_key: str) -> dict:
    now = time.monotonic()
    hit = _cache.get((source_key, "texts"))
    if hit and hit[0] > now:
        return hit[1]
    data: dict = {"prompts": {}, "messages": {}}
    keep_for = TTL_SECONDS
    try:
        for r in await _fetch(
            "SELECT key, scope, scope_ref, version, body FROM prompts WHERE is_active",
            source_key=source_key,
        ):
            _keep(data["prompts"], (r["key"],), r)
        for r in await _fetch(
            "SELECT key, locale, scope, scope_ref, version, body "
            "FROM system_messages WHERE is_active",
            source_key=source_key,
        ):
            _keep(data["messages"], (r["key"], r["locale"]), r)
    except asyncpg.UndefinedTableError:
        data = {
            "prompts": {},
            "messages": {},
        }  # not migrated yet: the built-in text is right
        keep_for = RETRY_SECONDS * 4
    except Exception as e:
        logger.warning(f"config_store: could not read texts for '{source_key}': {e}")
        data = {"prompts": {}, "messages": {}}
        keep_for = RETRY_SECONDS
    _cache[(source_key, "texts")] = (now + keep_for, data)
    return data


def _pick(layers: dict, pack: str | None) -> str | None:
    """The client's own text, else its industry's, else the shared one."""
    for where in (("tenant", ""), ("pack", pack), ("global", "")):
        if where[0] == "pack" and not pack:
            continue
        if where in layers:
            return layers[where][1]
    return None


async def prompt(
    source_key: str | None, key: str, default: str, *, pack: str | None = None
) -> str:
    """The text of one AI instruction. `pack` is the client's industry, so a text written for
    that industry is found."""
    if not source_key:
        return default
    data = await _load(source_key)
    text = _pick(data["prompts"].get((key,), {}), pack)
    return default if text is None else text


class _Keep(dict):
    """Fills {name} from the values given and leaves any other {word} as it is."""

    def __missing__(self, key):
        return "{" + key + "}"


class _Plain(string.Formatter):
    """Takes plain {names} only. {a.b}, {a[0]} and {0} are refused, so a text written on the
    dashboard can never reach into a value it is given."""

    def get_field(self, field_name, args, kwargs):
        if not field_name.isidentifier():
            raise ValueError(f"only plain {{names}} are allowed, not {{{field_name}}}")
        return self.get_value(field_name, args, kwargs), field_name


_plain = _Plain()


def fill(template: str, values: dict) -> str:
    """The template with each {name} replaced by its value. A {name} that is not among the values
    stays as it is. Raises ValueError for anything but plain names."""
    return _plain.vformat(template, (), _Keep(values))


async def message(
    source_key: str | None,
    key: str,
    default: str,
    *,
    locale: str = "en-IN",
    pack: str | None = None,
    **values,
) -> str:
    """A text the assistant sends by itself, with {placeholders} filled in from `values`.
    `default` is the built-in wording, used when nothing was written in the database or when
    what was written cannot be filled in."""
    if source_key:
        data = await _load(source_key)
        text = _pick(data["messages"].get((key, locale), {}), pack)
        if text is not None:
            try:
                return fill(text, values)
            except (ValueError, KeyError, IndexError, AttributeError, TypeError):
                logger.warning(
                    f"config_store: the text for '{key}' cannot be filled in"
                )
    return fill(default, values)


def setting(settings: dict | None, path: str, default=None):
    """One value from an organisation's settings, e.g. setting(s, "limits.draft_stale_minutes")."""
    cur = settings if isinstance(settings, dict) else {}
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def limit(settings: dict | None, name: str, default, *, section: str = "limits"):
    """A number the organisation set under settings.<section> (limits unless said otherwise), else
    `default` (the old built-in number). Zero, negative and non-numbers are ignored, so a typo can
    never switch a limit off."""
    value = setting(settings, f"{section}.{name}")
    ok = (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and 0 < value < float("inf")
    )
    return value if ok else default


def limit_of(settings: dict | None, name: str):
    """One of the numbers in LIMITS, as a whole number: the organisation's own, else the
    built-in one."""
    return int(limit(settings, name, LIMITS[name][0]))


def retention_of(settings: dict | None, name: str) -> int:
    """One of the numbers in RETENTION, as whole days (at least one)."""
    return max(1, int(limit(settings, name, RETENTION[name][0], section="retention")))


async def org_settings(source_key: str | None, org_id) -> dict:
    """orgs.settings of one organisation as a plain dict ({} when there are none, or when they
    cannot be read). Kept for a minute like the texts, so asking on every message costs nothing."""
    if not source_key or not org_id:
        return {}
    key = (source_key, f"settings:{org_id}")
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value: dict = {}
    keep_for = TTL_SECONDS
    try:
        rows = await _fetch(
            "SELECT settings FROM orgs WHERE id = $1", org_id, source_key=source_key
        )
        raw = rows[0]["settings"] if rows else None
        if isinstance(raw, str):
            raw = json.loads(raw)
        value = raw if isinstance(raw, dict) else {}
    except Exception as e:
        logger.warning(f"config_store: could not read settings for '{source_key}': {e}")
        keep_for = RETRY_SECONDS
    _cache[key] = (now + keep_for, value)
    return value
