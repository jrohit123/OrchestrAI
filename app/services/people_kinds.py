"""people_kinds.py — the kinds of people a record can have, read from the database (core-0027 / housing-0014).

A ticket has "Raised it", "Handling it", "Also told" ...; a visitor would have "Host resident". Nothing in the code
lists them: their labels, their order and what each one means to the engine are rows of record_people_kinds that a
super admin can change. The key of a kind is what each record stores and never changes; everything else is read here.

    meaning   raiser (who asked) | handler (who has it) | backup (steps in when the handler does not) |
              informed (is told) | other
    added     a flow may put people on a record as this kind (the system sets the others itself)

On a database without the table every function gives "none" (an empty list) and nothing fails.
"""

import time

from app.db import fetch_all
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

_CACHE_SECONDS = 30
_cache: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}


def invalidate() -> None:
    _cache.clear()


async def kinds(
    source_key: str, org_id, record_type: str = "ticket", *, active_only: bool = True
) -> list[dict]:
    """The kinds of people of one kind of record, in their order. [] when there are none or no table."""
    key = (source_key, str(org_id), record_type)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        found = hit[1]
    else:
        try:
            found = [
                dict(r)
                for r in await fetch_all(
                    "SELECT key, label, description, meaning, added, sort_order, is_active "
                    "FROM record_people_kinds WHERE org_id = $1 AND record_type = $2 ORDER BY sort_order, label",
                    org_id,
                    record_type,
                    source_key=source_key,
                )
            ]
        except Exception as e:  # no table here (an organisation without core-0027)
            logger.debug(f"no kinds of people for {record_type}: {e}")
            found = []
        _cache[key] = (time.monotonic(), found)
    return [k for k in found if k["is_active"]] if active_only else list(found)


def keys(found: list[dict]) -> list[str]:
    """The keys, first to last (who is told first when one person is on a record in several ways)."""
    return [k["key"] for k in found]


def with_meaning(found: list[dict], meaning: str) -> list[str]:
    return [k["key"] for k in found if k["meaning"] == meaning]


def can_be_added(found: list[dict], key: str) -> bool:
    return any(k["key"] == key and k["added"] for k in found)


def labels(found: list[dict]) -> dict[str, str]:
    return {k["key"]: k["label"] for k in found}
