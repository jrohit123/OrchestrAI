"""Tests for tools/orphans.py (the read-only report) and migrations/core/core-0008.

Like test_migrate.py, the database tests need MIGRATE_TEST_PG (a Postgres on this
computer); the others always run.
"""

import json
import re

import asyncpg

from tests.test_migrate import needs_pg
from tools import migrate, orphans

ORG = "00000000-0000-0000-0000-000000000001"
OTHER_ORG = "00000000-0000-0000-0000-000000000002"

SCHEMA = """
CREATE TABLE workflows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    intent_key text NOT NULL, is_active boolean NOT NULL DEFAULT true,
    steps jsonb NOT NULL DEFAULT '[]');
CREATE TABLE roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    name text NOT NULL, permissions text[] NOT NULL DEFAULT '{}');
CREATE TABLE user_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    user_id uuid NOT NULL DEFAULT gen_random_uuid(), intent_key text NOT NULL,
    stage text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '1 day');
CREATE TABLE workflow_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    status text NOT NULL,
    published_workflow_id uuid REFERENCES workflows (id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now());
"""
TABLES = ("workflows", "roles", "user_drafts", "workflow_drafts")


def seed(w):
    """One business with: a live workflow, a switched-off one whose steps ask for two
    labels, drafts pointing at a workflow that is gone, and roles holding dead labels."""
    w.execute("alpha", SCHEMA)
    steps = json.dumps(
        [
            {
                "op": "require_permission",
                "params": {"any_of": ["sub_perm"], "map": {"close": "close_perm"}},
            }
        ]
    )
    w.execute(
        "alpha",
        "INSERT INTO workflows (org_id, intent_key, is_active, steps) VALUES "
        "($1, 'real_one', true, '[]'), ($1, 'switched_off', false, $2::jsonb), "
        "($3, 'only_other', true, '[]')",
        ORG,
        steps,
        OTHER_ORG,
    )
    w.execute(
        "alpha",
        "INSERT INTO roles (org_id, name, permissions) VALUES ($1, 'admin', $2), "
        "($1, 'staff', $3)",
        ORG,
        [
            "real_one",
            "switched_off",
            "sub_perm",
            "close_perm",
            "approve",
            "dead_label",
            "only_other",
        ],
        ["real_one", "dead_label"],
    )
    w.execute(
        "alpha",
        "INSERT INTO user_drafts (org_id, intent_key, stage) VALUES "
        "($1, 'gone_workflow', 'collecting'), ($1, 'gone_workflow', 'done'), "
        "($1, 'gone_workflow', 'cancelled'), ($1, 'real_one', 'collecting'), "
        "($1, 'real_one', 'done'), ($1, 'switched_off', 'collecting')",
        ORG,
    )
    real_id = w.rows("alpha", "SELECT id FROM workflows WHERE intent_key = 'real_one'")[
        0
    ]["id"]
    w.execute(
        "alpha",
        "INSERT INTO workflow_drafts (org_id, status, published_workflow_id) VALUES "
        "($1, 'published', $2), ($1, 'published', NULL), ($1, 'chatting', NULL)",
        ORG,
        real_id,
    )


def snapshot(w):
    """A fingerprint of every table's contents, to prove nothing changed."""
    out = {}
    for table in TABLES:
        sql = f"SELECT md5(coalesce(string_agg(t::text, ',' ORDER BY t::text), '')) AS h FROM {table} t"
        out[table] = w.rows("alpha", sql)[0]["h"]
    return out


# ------------------------------------------------------------ no database needed


def test_labels_asked_for_by_steps_reads_any_of_and_map_values():
    steps = [
        {"op": "require_permission", "params": {"any_of": ["a", "b"]}},
        {
            "op": "require_permission",
            "params": {"from": "$f", "map": {"x": "c", "y": "d"}},
        },
        {"op": "notify", "params": {"any_of": ["not_this"]}},
        "not a step",
        json.dumps({"op": "require_permission", "params": {"any_of": ["e"]}}),
    ]
    assert orphans.labels_asked_for_by_steps(steps) == {"a", "b", "c", "d", "e"}
    assert orphans.labels_asked_for_by_steps(json.dumps(steps)) == {
        "a",
        "b",
        "c",
        "d",
        "e",
    }
    assert orphans.labels_asked_for_by_steps(None) == set()
    assert orphans.labels_asked_for_by_steps("{not json") == set()


def test_classify_labels_rules():
    workflows = [
        {"org_id": "A", "intent_key": "live", "is_active": True, "steps": []},
        {"org_id": "A", "intent_key": "off", "is_active": False, "steps": []},
        {
            "org_id": "A",
            "intent_key": "has_gate",
            "is_active": True,
            "steps": [{"op": "require_permission", "params": {"any_of": ["fine"]}}],
        },
        {"org_id": "B", "intent_key": "elsewhere", "is_active": True, "steps": []},
    ]
    holders = [
        ("A", "admin", ["live", "off", "fine", "approve", "dead", "elsewhere"]),
        ("A", "staff", ["dead"]),
        ("B", "admin", ["elsewhere", "live"]),
    ]
    unused, switched = orphans.classify_labels(workflows, holders)
    assert unused == {
        "dead": ["admin", "staff"],
        "elsewhere": ["admin"],  # a live key, but of another business
        "live": ["admin"],  # same: business B has no workflow called live
    }
    assert switched == {"off": ["admin"]}


def test_a_remote_database_is_refused_and_no_secret_is_printed(monkeypatch, capsys):
    monkeypatch.setenv(
        migrate.ROUTING_ENV, "postgresql://user:topsecret@db.example.invalid:5432/x"
    )
    assert orphans.main([]) == 1
    out = capsys.readouterr().out
    assert "not on this computer" in out
    assert "topsecret" not in out
    assert "example.invalid" not in out


# ------------------------------------------------------- a local database needed


@needs_pg
def test_the_report_finds_orphans_and_unused_labels_and_changes_nothing(world):
    seed(world)
    before = snapshot(world)
    code, out = world.call(orphans.main, "--tenant", "alpha")
    assert code == 0, out
    assert "drafts people started: 6 in total, 3 still open" in out
    assert "no longer exists: 3 (1 open, 2 finished or cancelled)" in out
    assert "gone_workflow 3" in out
    assert "3 in total; 1 are marked published but lost their workflow" in out
    assert re.search(r"dead_label\s+held by: admin, staff", out)
    assert re.search(
        r"only_other\s+held by: admin", out
    )  # live, but in another business
    assert "label of a switched-off workflow: switched_off (held by: admin)" in out
    for used in ("sub_perm", "close_perm", "approve", "real_one"):
        assert used not in out.split("permission labels")[1], used
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", out)  # no ids are printed
    assert snapshot(world) == before
    assert "Read-only report" in out


@needs_pg
def test_a_database_without_the_tables_is_skipped_not_a_failure(world):
    code, out = world.call(orphans.main, "--tenant", "beta")
    assert code == 0, out
    assert out.count("skipped:") == 3


@needs_pg
def test_without_a_name_every_client_is_reported_but_not_the_control_database(world):
    code, out = world.call(orphans.main)
    assert code == 0, out
    assert "== alpha" in out
    assert "== beta" in out
    assert "== control" not in out
    code, out = world.call(orphans.main, "--tenant", "control")
    assert code == 1
    assert "nothing to look at" in out


@needs_pg
def test_the_report_session_is_read_only(world, monkeypatch):
    seen = {}

    async def sneaky(conn, findings):
        try:
            await conn.execute("CREATE TABLE sneaky (id int)")
            seen["wrote"] = True
        except asyncpg.PostgresError as exc:
            seen["blocked"] = type(exc).__name__

    monkeypatch.setattr(orphans, "look", sneaky)
    world.call(orphans.main, "--tenant", "alpha")
    assert "wrote" not in seen
    assert seen["blocked"] == "ReadOnlySQLTransactionError"


@needs_pg
def test_housing_0001_removes_only_the_two_unused_labels_and_is_safe_to_repeat(world):
    world.execute("alpha", SCHEMA)
    world.execute(
        "alpha",
        "INSERT INTO roles (org_id, name, permissions) VALUES "
        "($1, 'owner', $2), ($1, 'admin', $3), ($1, 'quiet', $4)",
        ORG,
        [
            "general_read",
            "get_resident_cases_status",
            "view_my_cases",
            "file_a_complaint",
        ],
        ["view_my_cases", "general_read", "other_label"],
        ["general_read"],
    )
    sql = (
        migrate.MIGRATIONS_DIR
        / "features"
        / "housing"
        / "housing-0001_remove_unused_labels.sql"
    ).read_text(encoding="utf-8")

    def roles():
        rows = world.rows("alpha", "SELECT name, permissions FROM roles")
        return {r["name"]: list(r["permissions"]) for r in rows}

    world.execute("alpha", sql)
    expected = {
        "owner": ["general_read", "file_a_complaint"],  # order of the others is kept
        "admin": ["general_read", "other_label"],
        "quiet": ["general_read"],  # nothing to remove: untouched, general_read stays
    }
    assert roles() == expected
    world.execute("alpha", sql)
    assert roles() == expected


@needs_pg
def test_core_0008_cancels_only_open_orphan_drafts_and_is_safe_to_repeat(world):
    seed(world)
    sql = (
        migrate.MIGRATIONS_DIR / "core" / "core-0008_cancel_orphan_drafts.sql"
    ).read_text(encoding="utf-8")

    def stages():
        rows = world.rows(
            "alpha",
            "SELECT intent_key, stage, expires_at <= now() AS expired FROM user_drafts",
        )
        return sorted((r["intent_key"], r["stage"], r["expired"]) for r in rows)

    def builder():
        rows = world.rows(
            "alpha",
            "SELECT status, published_workflow_id IS NULL AS unlinked FROM workflow_drafts",
        )
        return sorted((r["status"], r["unlinked"]) for r in rows)

    world.execute("alpha", sql)
    after = stages()
    # the open orphan is now cancelled and expired; nothing else moved
    assert ("gone_workflow", "cancelled", True) in after
    assert [s for _, s, _ in after].count("collecting") == 2
    assert ("real_one", "collecting", False) in after
    assert ("switched_off", "collecting", False) in after  # switched off, but it exists
    assert ("gone_workflow", "done", False) in after
    assert builder() == [("abandoned", True), ("chatting", True), ("published", False)]
    # nothing was deleted, and a second run changes nothing
    assert len(after) == 6
    first = (after, builder(), snapshot(world))
    world.execute("alpha", sql)
    assert (stages(), builder(), snapshot(world)) == first
