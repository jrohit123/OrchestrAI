"""Look at what the daily cleanup would remove. Changes nothing.

Run from the project folder:

    python -m tools.cleanup

It lists, for each client database, how many finished drafts, expired one-time codes and abandoned
workflow drafts are old enough to go (using each organisation's retention setting, or the
built-in numbers), and how many archived copies are old enough to be cleared. The real cleanup
runs by itself every night in the app; it copies each row to archived_rows before removing it.

The databases come from the control (routing) database, using the ROUTING_DATABASE_URL
environment variable. No connection string is ever printed.
"""

from __future__ import annotations

import asyncio
import sys

LABELS = {
    "user_drafts": "finished drafts",
    "otp_tokens": "expired one-time codes",
    "workflow_drafts": "abandoned workflow drafts",
    "archive": "archived copies past their time",
}


def report(result: dict[str, dict[str, int]], ready: dict[str, bool]) -> str:
    """The plain-words list printed for a dry run. `ready` says which databases already have
    the archive table; the others would be left alone until the migration is applied."""
    if not result:
        return "No databases were looked at."
    lines = []
    for source_key in sorted(result):
        counts = result[source_key]
        if not ready.get(source_key, False):
            lines.append(
                f"{source_key}: NOT READY, archived_rows is missing (apply core-0010 first)"
            )
        elif not any(counts.values()):
            lines.append(f"{source_key}: nothing to do")
            continue
        else:
            lines.append(f"{source_key}:")
        for key, label in LABELS.items():
            if counts.get(key):
                lines.append(f"    {counts[key]:>6}  {label}")
    total = sum(
        n
        for key, counts in result.items()
        if ready.get(key, False)
        for n in counts.values()
    )
    lines.append("")
    lines.append(
        f"{total} row(s) would be copied to archived_rows and removed. Nothing was changed."
        if total
        else "Nothing is old enough to be removed. Nothing was changed."
    )
    return "\n".join(lines)


async def _preview() -> str:
    from app import db  # imported here: it reads the app's settings when it loads
    from app.services import cleanup

    await db.init_db()
    try:
        result = await cleanup.run_cleanup(dry_run=True)
        ready = {}
        for source_key in result:
            try:
                ready[source_key] = await cleanup.is_ready(source_key)
            except Exception:
                ready[source_key] = False
        return report(result, ready)
    finally:
        await db.close_db()


def main() -> int:
    if sys.argv[1:]:
        print(__doc__)
        return 1
    print(asyncio.run(_preview()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
