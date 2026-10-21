"""Tests for "every building block is one step": the Godrej migration housing-0002, the rule the
editor and the AI builder now follow, and the words that tell the builder about it.

The migration tests use the Postgres on this computer given by MIGRATE_TEST_PG (see test_migrate.py)
and its throwaway databases. They load the real definitions of Godrej's twelve blocks and four
flows (tests/fixtures/godrej_case_workflows.json: steps and wording only, no people or cases).
"""

import asyncio
import json
from pathlib import Path

import asyncpg
import pytest

from app.services import step_catalog
from tests.test_migrate import needs_pg
from tools import migrate

ROOT = Path(__file__).resolve().parent.parent
FEATURE = ROOT / "migrations" / "features" / "housing"
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "godrej_case_workflows.json").read_text(
        encoding="utf-8"
    )
)

# the blocks that had several steps and are cut, and the ones that are only switched off
CUT = [
    "case_find", "case_create", "case_set_priority", "case_set_status",
    "case_apply_route", "case_assign", "case_close", "case_tell_parties",
]  # fmt: skip
SWITCHED_OFF = ["case_tell_handler", "case_tell_requester"]
KEPT = ["case_comment", "case_tell_assignee"]  # already one step
NEW = [
    "case_find_by_number", "case_check_access",
    "case_look_up_response_time", "case_due_from_priority", "case_due_from_route", "case_save_new",
    "case_set_category", "case_record_reported",
    "case_due_from_new_priority", "case_save_priority", "case_record_priority",
    "case_save_status", "case_stamp_closed_time", "case_clear_closed_time", "case_record_status",
    "case_give_to_routed_person", "case_record_routed_assignment", "case_add_level2_people",
    "case_find_new_handler", "case_save_handler", "case_record_assignment",
    "case_save_closed", "case_record_closed",
    "case_tell_everyone_with_buttons", "case_tell_everyone",
]  # fmt: skip

# what each flow runs afterwards, in order
FLOWS_AFTER = {
    "file_a_complaint": [
        "case.categorize", "case.route", "run case_look_up_response_time", "run case_due_from_priority",
        "run case_due_from_route", "run case_save_new", "run case_set_category", "run case_record_reported",
        "run case_give_to_routed_person", "run case_record_routed_assignment", "run case_add_level2_people",
        "case.attach_photos", "notify.parties", "notify.whatsapp",
    ],
    "case_add_update": [
        "run case_find_by_number", "run case_check_access", "run case_comment", "case.attach_photos",
        "run case_tell_everyone_with_buttons", "run case_tell_everyone",
    ],
    "case_close_with_note": [
        "run case_find_by_number", "run case_check_access", "run case_save_closed", "run case_record_closed",
        "case.attach_photos", "run case_tell_everyone_with_buttons", "run case_tell_everyone",
    ],
    "case_pass_on": [
        "run case_find_by_number", "run case_check_access", "case.add_parties", "run case_find_new_handler",
        "run case_save_handler", "run case_record_assignment", "run case_comment",
        "run case_tell_everyone_with_buttons", "run case_tell_everyone",
    ],
}  # fmt: skip


def seq(steps):
    return [
        "run " + s["params"]["workflow"] if s["op"] == "run_workflow" else s["op"]
        for s in steps
    ]


def canon(step):
    return json.dumps(step, sort_keys=True, ensure_ascii=False)


# ------------------------------------------------------------ the rule in the editor and the builder


def check(steps, kind):
    return step_catalog.validate_steps(steps, schema={}, kind=kind)["errors"]


def many(n):
    return [{"op": "notify.whatsapp", "params": {}} for _ in range(n)]


# Since the plain-words builder (2026-10-21) a block may hold several steps again: it does one
# whole job and says what it needs. The blocks the migration below made stay one step each.


@pytest.mark.parametrize("n", [0, 1, 3])
def test_a_building_block_is_not_refused_for_its_size(n):
    assert not any("is one step" in e for e in check(many(n), "block"))


@pytest.mark.parametrize("kind", ["workflow", "case_action"])
def test_other_kinds_may_have_as_many_steps_as_they_need(kind):
    assert not any("is one step" in e for e in check(many(5), kind))


def test_the_ai_builder_is_told_a_block_does_one_whole_job():
    creator = (ROOT / "app" / "prompts" / "workflow_creator.txt").read_text(
        encoding="utf-8"
    )
    dsl = (ROOT / "app" / "prompts" / "workflow_dsl.txt").read_text(encoding="utf-8")
    for text in (creator, dsl):
        assert "ONE whole job" in text
        assert "exactly ONE step" not in text


# ------------------------------------------------------------ the migration


def test_the_migration_tool_accepts_the_file_and_it_is_for_godrej_only():
    versions = [m.version for m in migrate.load_group(FEATURE, "housing")]
    assert "housing-0002" in versions
    assert json.loads((FEATURE / "feature.json").read_text(encoding="utf-8"))[
        "tenants"
    ] == ["godrej"]


SCHEMA = """
CREATE TABLE orgs (id uuid PRIMARY KEY, name text);
CREATE TABLE roles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid, name text,
                    permissions text[] NOT NULL DEFAULT '{}');
CREATE TABLE workflows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, intent_key text NOT NULL,
    name text NOT NULL, steps jsonb DEFAULT '[]', is_active boolean DEFAULT true, version integer DEFAULT 1,
    created_at timestamptz DEFAULT now(), description text,
    workflow_type varchar NOT NULL DEFAULT 'action', training_phrases jsonb NOT NULL DEFAULT '[]',
    entity_schema jsonb NOT NULL DEFAULT '{}', response_format varchar NOT NULL DEFAULT 'generic',
    menu_section varchar NOT NULL DEFAULT 'other', gates jsonb NOT NULL DEFAULT '[]',
    kind text NOT NULL DEFAULT 'workflow' CHECK (kind IN ('workflow', 'block', 'case_action')),
    settings jsonb NOT NULL DEFAULT '{}', calc_rules jsonb DEFAULT '{}', sql_template text,
    slash_command varchar, UNIQUE (org_id, intent_key));
CREATE TABLE workflow_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workflow_id uuid NOT NULL, org_id uuid NOT NULL,
    version integer NOT NULL, intent_key text NOT NULL, name text, entity_schema jsonb, gates jsonb,
    granted_roles text[], steps jsonb, calc_rules jsonb, sql_template text, slash_command text,
    source_draft_id uuid, published_at timestamptz NOT NULL DEFAULT now(), kind text, settings jsonb);
CREATE TABLE admin_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, actor_user_id uuid,
    actor_label text, area text NOT NULL, action text NOT NULL, target_type text, target_id text,
    summary text NOT NULL, before_state jsonb, after_state jsonb, created_at timestamptz NOT NULL DEFAULT now());
"""
ORG = "00000000-0000-0000-0000-00000000000a"
OTHER_ORG = "00000000-0000-0000-0000-00000000000b"


async def _insert(conn, org, row):
    await conn.execute(
        "INSERT INTO workflows (org_id, intent_key, name, description, kind, workflow_type, is_active, "
        "version, steps, entity_schema, gates, settings, response_format, menu_section) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13, $14)",
        org,
        row["intent_key"],
        row["name"],
        row.get("description"),
        row["kind"],
        row["workflow_type"],
        row["is_active"],
        row["version"],
        json.dumps(row["steps"]),
        json.dumps(row["entity_schema"]),
        json.dumps(row["gates"]),
        json.dumps(row["settings"]),
        row["response_format"],
        row["menu_section"],
    )


async def _database(world, extra=()):
    conn = await asyncpg.connect(world.dsn["alpha"])
    await conn.execute(SCHEMA)
    await conn.execute(
        "INSERT INTO orgs (id, name) VALUES ($1, 'Godrej'), ($2, 'Other')",
        ORG,
        OTHER_ORG,
    )
    await conn.execute(
        "INSERT INTO roles (org_id, name, permissions) VALUES ($1, 'owner', ARRAY['file_a_complaint', 'case_pass_on'])",
        ORG,
    )
    for row in FIXTURE:
        await _insert(conn, ORG, row)
    for org, row in extra:
        await _insert(conn, org, row)
    return conn


def _flow(key, steps, kind="workflow"):
    return {
        "intent_key": key, "name": key, "description": None, "kind": kind, "workflow_type": "action",
        "is_active": True, "version": 1, "steps": steps, "entity_schema": {}, "gates": [], "settings": {},
        "response_format": "generic", "menu_section": "other",
    }  # fmt: skip


async def _apply(conn):
    migration = next(
        m for m in migrate.load_group(FEATURE, "housing") if m.version == "housing-0002"
    )
    async with conn.transaction():
        await conn.execute(migration.sql)


async def _rows(conn):
    out = {}
    for r in await conn.fetch("SELECT * FROM workflows WHERE org_id = $1", ORG):
        out[r["intent_key"]] = {
            "name": r["name"], "kind": r["kind"], "on": r["is_active"], "version": r["version"],
            "steps": json.loads(r["steps"]), "description": r["description"],
        }  # fmt: skip
    return out


def _fixture(key):
    return next(r for r in FIXTURE if r["intent_key"] == key)


@needs_pg
def test_every_active_block_is_one_step_and_the_old_ones_are_kept_but_switched_off(
    world,
):
    async def scenario():
        conn = await _database(world)
        try:
            before = await _rows(conn)
            await _apply(conn)
            return before, await _rows(conn)
        finally:
            await conn.close()

    before, after = asyncio.run(scenario())
    assert sorted(
        k for k, v in before.items() if v["kind"] == "block" and len(v["steps"]) > 1
    ) == sorted(CUT + SWITCHED_OFF)
    on = {k for k, v in after.items() if v["kind"] == "block" and v["on"]}
    assert on == set(NEW) | set(KEPT)
    assert all(len(after[k]["steps"]) == 1 for k in on)
    for key in CUT:
        assert (
            after[key]["on"] is False
            and after[key]["name"] == before[key]["name"] + " (replaced)"
        )
        assert after[key]["steps"] == before[key]["steps"]  # kept exactly as it was
    for key in SWITCHED_OFF:
        assert after[key]["on"] is False and after[key]["name"] == before[key]["name"]
    for key in KEPT:
        assert after[key] == before[key]  # untouched
    assert all(
        len(v["steps"]) > 1
        for k, v in after.items()
        if v["kind"] == "block" and not v["on"]
    )


@needs_pg
def test_each_small_block_holds_exactly_one_of_the_steps_the_big_ones_had(world):
    async def scenario():
        conn = await _database(world)
        try:
            await _apply(conn)
            return await _rows(conn)
        finally:
            await conn.close()

    after = asyncio.run(scenario())
    had = {canon(s) for key in CUT for s in _fixture(key)["steps"]}
    now = {canon(after[key]["steps"][0]) for key in NEW}
    assert now == had and len(NEW) == len(had)
    for key in NEW:
        b = after[key]
        assert (
            b["kind"] == "block"
            and b["name"]
            and b["description"]
            and b["version"] == 1
        )


@needs_pg
def test_the_workflows_run_the_small_blocks_in_the_same_order_with_the_same_inputs(
    world,
):
    extra = [
        (
            ORG,
            _flow(
                "with_condition",
                [
                    {
                        "op": "run_workflow",
                        "when": {"field": "$fields.x", "exists": True},
                        "params": {"workflow": "case_close", "inputs": {"note": "n"}},
                    },
                    {"op": "notify.whatsapp", "params": {}},
                ],
            ),
        )
    ]

    async def scenario():
        conn = await _database(world, extra)
        try:
            before = await _rows(conn)
            await _apply(conn)
            return before, await _rows(conn)
        finally:
            await conn.close()

    before, after = asyncio.run(scenario())
    for key, want in FLOWS_AFTER.items():
        assert seq(after[key]["steps"]) == want, key
    # everything else about a step is kept: its inputs and its "only if", on every small step
    tell = next(
        s
        for s in before["case_pass_on"]["steps"]
        if s["params"].get("workflow") == "case_tell_parties"
    )
    now = [
        s
        for s in after["case_pass_on"]["steps"]
        if s["params"].get("workflow", "").startswith("case_tell_everyone")
    ]
    assert len(now) == 2 and all(
        s["params"]["inputs"] == tell["params"]["inputs"] for s in now
    )
    comment = next(
        s
        for s in after["case_pass_on"]["steps"]
        if s["params"].get("workflow") == "case_comment"
    )
    assert comment["when"] == {"field": "$fields.comment_text", "exists": True}
    guarded = after["with_condition"]["steps"]
    assert seq(guarded) == [
        "run case_save_closed",
        "run case_record_closed",
        "notify.whatsapp",
    ]
    assert all(
        s["when"] == {"field": "$fields.x", "exists": True}
        and s["params"]["inputs"] == {"note": "n"}
        for s in guarded[:2]
    )
    # steps that are not blocks are untouched
    assert (
        after["file_a_complaint"]["steps"][0] == before["file_a_complaint"]["steps"][0]
    )


@needs_pg
def test_nothing_is_deleted_and_the_history_keeps_what_each_workflow_was(world):
    async def scenario():
        conn = await _database(world)
        try:
            await _apply(conn)
            versions = {}
            for r in await conn.fetch(
                "SELECT intent_key, version, steps, granted_roles, kind FROM workflow_versions ORDER BY intent_key, version"
            ):
                versions.setdefault(r["intent_key"], []).append(
                    (
                        r["version"],
                        len(json.loads(r["steps"])),
                        list(r["granted_roles"]),
                        r["kind"],
                    )
                )
            total = await conn.fetchval("SELECT count(*) FROM workflows")
            events = [
                r["summary"]
                for r in await conn.fetch("SELECT summary FROM admin_events")
            ]
            return versions, total, events
        finally:
            await conn.close()

    versions, total, events = asyncio.run(scenario())
    assert total == len(FIXTURE) + len(NEW)  # only added
    assert versions["file_a_complaint"] == [
        (1, 7, ["owner"], "workflow"),
        (2, 14, ["owner"], "workflow"),
    ]
    assert versions["case_create"] == [(1, 6, [], "block"), (2, 6, [], "block")]
    assert versions["case_save_new"] == [(1, 1, [], "block")]
    assert "case_comment" not in versions  # unchanged, so no new copy
    assert events == [
        "Cut the building blocks into one-step blocks (migration housing-0002)"
    ]


@needs_pg
def test_running_it_a_second_time_changes_nothing_more(world):
    async def scenario():
        conn = await _database(world)
        try:
            await _apply(conn)
            first = await _rows(conn)
            first_versions = await conn.fetchval(
                "SELECT count(*) FROM workflow_versions"
            )
            await _apply(conn)
            second = await _rows(conn)
            return (
                first == second,
                first_versions
                == await conn.fetchval("SELECT count(*) FROM workflow_versions"),
                await conn.fetchval("SELECT count(*) FROM admin_events"),
            )
        finally:
            await conn.close()

    same_rows, same_versions, events = asyncio.run(scenario())
    assert same_rows and same_versions and events == 1


EDITS = {
    "a block was edited after the file was written": (
        'UPDATE workflows SET steps = steps || \'[{"op": "notify.whatsapp", "params": {}}]\'::jsonb WHERE intent_key = \'case_close\'',
        "has 3 steps but 2 were expected",
    ),
    "a workflow still runs a block that would only be switched off": (
        'UPDATE workflows SET steps = steps || \'[{"op": "run_workflow", "params": {"workflow": "case_tell_handler"}}]\'::jsonb WHERE intent_key = \'case_add_update\'',
        "is run by",
    ),
    "a different workflow already has one of the new names": (
        "INSERT INTO workflows (org_id, intent_key, name, kind) VALUES ('"
        + ORG
        + "', 'case_save_new', 'Mine', 'workflow')",
        "already exists and is not a one-step block",
    ),
    "two blocks no longer share the same first step": (
        "UPDATE workflows SET steps = jsonb_set(steps, '{0,params,name_from}', '\"$fields.other\"') WHERE intent_key = 'case_set_priority'",
        "no longer have the same step",
    ),
    "a one-step block with one of the new names holds a different step": (
        "INSERT INTO workflows (org_id, intent_key, name, kind, steps) VALUES ('"
        + ORG
        + "', 'case_save_new', 'Mine', 'block', '[{\"op\": \"notify.whatsapp\", \"params\": {}}]')",
        "already exists and holds a different step",
    ),
    "an old unused block was edited after the file was written": (
        'UPDATE workflows SET steps = steps || \'[{"op": "notify.whatsapp", "params": {}}]\'::jsonb WHERE intent_key = \'case_tell_handler\'',
        "has 3 steps but 2 were expected",
    ),
}


@needs_pg
@pytest.mark.parametrize("what", list(EDITS))
def test_it_refuses_and_changes_nothing_when_things_are_not_as_expected(world, what):
    edit, words = EDITS[what]

    async def scenario():
        conn = await _database(world)
        try:
            await conn.execute(edit)
            before = await conn.fetch(
                "SELECT intent_key, version, is_active, name, steps FROM workflows ORDER BY intent_key"
            )
            versions = await conn.fetchval("SELECT count(*) FROM workflow_versions")
            try:
                await _apply(conn)
                refused = None
            except asyncpg.PostgresError as e:
                refused = str(e)
            after = await conn.fetch(
                "SELECT intent_key, version, is_active, name, steps FROM workflows ORDER BY intent_key"
            )
            return (
                refused,
                before == after,
                versions
                == await conn.fetchval("SELECT count(*) FROM workflow_versions"),
            )
        finally:
            await conn.close()

    refused, nothing_changed, no_new_history = asyncio.run(scenario())
    assert refused and "housing-0002" in refused and words in refused, refused
    assert nothing_changed and no_new_history


@needs_pg
def test_a_run_that_stopped_part_way_can_simply_be_run_again(world):
    # a block a half-finished run had already added is the very step this run would add
    half_done = _flow(
        "case_find_by_number", [_fixture("case_find")["steps"][0]], kind="block"
    )

    async def scenario():
        conn = await _database(world, [(ORG, half_done)])
        try:
            await _apply(conn)
            return await _rows(conn)
        finally:
            await conn.close()

    after = asyncio.run(scenario())
    on = {k for k, v in after.items() if v["kind"] == "block" and v["on"]}
    assert on == set(NEW) | set(KEPT)
    assert all(len(after[k]["steps"]) == 1 for k in on)
    assert after["case_find_by_number"]["version"] == 1
    for key, want in FLOWS_AFTER.items():
        assert seq(after[key]["steps"]) == want, key


@needs_pg
def test_another_organisation_is_left_alone(world):
    mine = _flow(
        "my_flow", [{"op": "run_workflow", "params": {"workflow": "case_find"}}]
    )
    # the other organisation has its own block with that key, already one step: nothing to cut there
    theirs_block = _flow(
        "case_find", [{"op": "notify.whatsapp", "params": {}}], kind="block"
    )
    theirs_flow = _flow(
        "their_flow", [{"op": "run_workflow", "params": {"workflow": "case_find"}}]
    )

    async def scenario():
        conn = await _database(
            world, [(ORG, mine), (OTHER_ORG, theirs_block), (OTHER_ORG, theirs_flow)]
        )
        try:
            await _apply(conn)
            other = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT intent_key, version, is_active, steps FROM workflows WHERE org_id = $1 ORDER BY intent_key",
                    OTHER_ORG,
                )
            ]
            mine_after = json.loads(
                await conn.fetchval(
                    "SELECT steps FROM workflows WHERE org_id = $1 AND intent_key = 'my_flow'",
                    ORG,
                )
            )
            return other, mine_after
        finally:
            await conn.close()

    other, mine_after = asyncio.run(scenario())
    assert [(r["intent_key"], r["version"], r["is_active"]) for r in other] == [
        ("case_find", 1, True),
        ("their_flow", 1, True),
    ]
    assert json.loads(other[1]["steps"]) == theirs_flow["steps"]
    assert seq(mine_after) == ["run case_find_by_number", "run case_check_access"]
