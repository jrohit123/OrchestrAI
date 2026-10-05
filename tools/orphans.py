"""Read-only report of leftovers in the client databases.

Run from the project folder:

    python -m tools.orphans                     every client database on this computer
    python -m tools.orphans --tenant godrej
    python -m tools.orphans --allow-remote      live databases (still read-only)

For each client database it shows:
  * drafts that point at a workflow that no longer exists: the drafts people started in
    chat, and the dashboard builder's drafts, counted by workflow name
  * permission labels held by roles that nothing uses: no workflow has that key, no
    workflow step asks for it, and it is not a built-in label

It only reads (the session is read-only), reads the database list the same safe way as
tools/migrate.py, never prints a connection string, and prints workflow keys, role names
and counts only: no names of people and no message text.

Exit codes: 0 fine, 1 refused or set up wrong (nothing was touched), 2 a database failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress
from dataclasses import dataclass, field

from tools.migrate import (
    MigrationError,
    Options,
    Target,
    describe,
    discover_targets,
    dsn_is_local,
    open_connection,
    redact,
)

# The one permission label the app checks by name (app/executor/workflow_executor.py:
# "approve" in user_permissions). Every other label is a workflow key, or a label that a
# workflow step asks for.
BUILT_IN_LABELS = {"approve"}

TABLES_SQL = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
"""
USER_DRAFTS_SQL = """
SELECT d.intent_key AS key,
       (d.stage NOT IN ('done', 'cancelled')) AS is_open,
       NOT EXISTS (SELECT 1 FROM public.workflows w
                   WHERE w.org_id = d.org_id AND w.intent_key = d.intent_key) AS orphan,
       count(*) AS n
FROM public.user_drafts d
GROUP BY 1, 2, 3
"""
BUILDER_DRAFTS_SQL = """
SELECT count(*) AS total,
       count(*) FILTER (WHERE status = 'published'
                          AND published_workflow_id IS NULL) AS unlinked
FROM public.workflow_drafts
"""
WORKFLOWS_SQL = "SELECT org_id, intent_key, is_active, steps FROM public.workflows"
ROLES_SQL = "SELECT org_id, name, permissions FROM public.roles"
POSITIONS_SQL = (
    "SELECT org_id, name, default_permissions AS permissions "
    "FROM public.committee_positions"
)


# ----------------------------------------------------------------------- pure logic


def _as_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def labels_asked_for_by_steps(steps) -> set[str]:
    """The labels a workflow's require_permission steps accept (`any_of`, and every value
    of `map`). Same rule as extract_required_permissions in
    app/services/workflow_publisher.py, copied because importing the app would read .env."""
    found: set[str] = set()
    for step in _as_list(steps):
        if isinstance(step, str):
            try:
                step = json.loads(step)
            except ValueError:
                continue
        if not isinstance(step, dict) or step.get("op") != "require_permission":
            continue
        params = step.get("params") or {}
        found.update(params.get("any_of") or [])
        found.update((params.get("map") or {}).values())
    return found


def classify_labels(workflows, holders):
    """Which held labels does nothing use?

    workflows: dicts with org_id, intent_key, is_active, steps.
    holders:   (org_id, holder name, labels) for every role (and position).
    Returns (unused, switched_off): each {label: [holder names]}. A label is unused when
    no workflow in the same business has it as its key, no step of any workflow asks for
    it, and it is not built in. A label that is the key of a switched-off workflow is
    reported separately: the workflow still exists."""
    keys: dict[str, set[str]] = {}
    off: dict[str, set[str]] = {}
    asked: dict[str, set[str]] = {}
    for w in workflows:
        org = str(w["org_id"])
        keys.setdefault(org, set()).add(w["intent_key"])
        if not w["is_active"]:
            off.setdefault(org, set()).add(w["intent_key"])
        asked.setdefault(org, set()).update(labels_asked_for_by_steps(w["steps"]))
    unused: dict[str, set[str]] = {}
    switched: dict[str, set[str]] = {}
    for org_id, holder, labels in holders:
        org = str(org_id)
        for label in labels or []:
            if label in BUILT_IN_LABELS or label in asked.get(org, set()):
                continue
            if label in keys.get(org, set()):
                if label in off.get(org, set()):
                    switched.setdefault(label, set()).add(holder)
                continue
            unused.setdefault(label, set()).add(holder)
    return (
        {k: sorted(v) for k, v in sorted(unused.items())},
        {k: sorted(v) for k, v in sorted(switched.items())},
    )


# -------------------------------------------------------------------- the database


@dataclass
class Findings:
    label: str
    local: bool
    skipped: list[str] = field(default_factory=list)
    drafts_total: int = 0
    drafts_open: int = 0
    orphan_drafts: list[tuple[str, bool, int]] = field(default_factory=list)
    builder_total: int | None = None
    builder_unlinked: int = 0
    unused: dict[str, list[str]] | None = None
    switched_off: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None


async def look(conn, findings: Findings) -> None:
    tables = {r["relname"] for r in await conn.fetch(TABLES_SQL)}

    if {"user_drafts", "workflows"} <= tables:
        for r in await conn.fetch(USER_DRAFTS_SQL):
            findings.drafts_total += r["n"]
            if r["is_open"]:
                findings.drafts_open += r["n"]
            if r["orphan"]:
                findings.orphan_drafts.append((r["key"], r["is_open"], r["n"]))
    else:
        findings.skipped.append("drafts people started (no such table here)")

    if "workflow_drafts" in tables:
        row = await conn.fetchrow(BUILDER_DRAFTS_SQL)
        findings.builder_total = row["total"]
        findings.builder_unlinked = row["unlinked"]
    else:
        findings.skipped.append("dashboard builder drafts (no such table here)")

    if {"workflows", "roles"} <= tables:
        workflows = [dict(r) for r in await conn.fetch(WORKFLOWS_SQL)]
        holders = [
            (r["org_id"], r["name"], list(r["permissions"] or []))
            for r in await conn.fetch(ROLES_SQL)
        ]
        if "committee_positions" in tables:
            holders += [
                (r["org_id"], f"position {r['name']}", list(r["permissions"] or []))
                for r in await conn.fetch(POSITIONS_SQL)
            ]
        findings.unused, findings.switched_off = classify_labels(workflows, holders)
    else:
        findings.skipped.append("permission labels (no roles or workflows here)")


async def process(target: Target, opts: Options) -> Findings:
    findings = Findings(label=target.label, local=dsn_is_local(target.dsn))
    conn = None
    try:
        conn = await open_connection(target.dsn, opts)
        await look(conn, findings)
    except Exception as exc:
        findings.error = describe(exc)
    finally:
        if conn is not None:
            with suppress(Exception):
                await conn.close()
    return findings


# ------------------------------------------------------------------------ the report


def _holders(names: list[str]) -> str:
    return ", ".join(names)


def print_findings(f: Findings) -> None:
    where = "on this computer" if f.local else "NOT on this computer"
    print(f"== {f.label}  (client database, {where})")
    if f.error:
        print(f"   PROBLEM: {f.error}")
        return
    for note in f.skipped:
        print(f"   skipped: {note}")
    if not any(s.startswith("drafts people") for s in f.skipped):
        gone_open = sum(n for _, is_open, n in f.orphan_drafts if is_open)
        gone_all = sum(n for _, _, n in f.orphan_drafts)
        print(
            f"   drafts people started: {f.drafts_total} in total, "
            f"{f.drafts_open} still open"
        )
        print(
            f"     pointing at a workflow that no longer exists: {gone_all} "
            f"({gone_open} open, {gone_all - gone_open} finished or cancelled)"
        )
        by_key: dict[str, int] = {}
        for key, _, n in f.orphan_drafts:
            by_key[key] = by_key.get(key, 0) + n
        if by_key:
            parts = sorted(by_key.items(), key=lambda kv: (-kv[1], kv[0]))
            print("       " + ", ".join(f"{k} {n}" for k, n in parts))
    if f.builder_total is not None:
        print(
            f"   dashboard builder drafts: {f.builder_total} in total; "
            f"{f.builder_unlinked} are marked published but lost their workflow"
        )
    if f.unused is not None:
        if f.unused:
            print(f"   permission labels that nothing uses ({len(f.unused)}):")
            for label, holders in f.unused.items():
                print(f"       {label:<30} held by: {_holders(holders)}")
        else:
            print("   permission labels that nothing uses: none")
        for label, holders in f.switched_off.items():
            print(
                f"   label of a switched-off workflow: {label} "
                f"(held by: {_holders(holders)})"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.orphans",
        description=(
            "Read-only report of drafts that point at removed workflows and of "
            "permission labels that nothing uses. Changes nothing."
        ),
    )
    parser.add_argument(
        "--tenant",
        action="append",
        default=[],
        metavar="NAME",
        help="only this client database (repeat or use commas)",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow databases that are not on this computer (still read-only)",
    )
    return parser


async def run(opts: Options) -> int:
    targets = await discover_targets(opts, include_control=False)
    if not targets:
        raise MigrationError(
            "nothing to look at: name a client database, not 'control'"
        )
    results: list[Findings] = []
    for target in targets:
        findings = await process(target, opts)
        print_findings(findings)
        sys.stdout.flush()
        results.append(findings)
    print()
    print("Read-only report: nothing was changed.")
    return 2 if any(r.error for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    opts = Options(
        tenants=[
            name.strip()
            for item in args.tenant
            for name in item.split(",")
            if name.strip()
        ],
        allow_remote=args.allow_remote,
    )
    with suppress(Exception):
        sys.stdout.reconfigure(errors="replace")
    try:
        return asyncio.run(run(opts))
    except MigrationError as exc:
        print(f"STOPPED - {redact(str(exc))}")
        return 1
    except Exception as exc:
        print(f"UNEXPECTED PROBLEM - {describe(exc)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
