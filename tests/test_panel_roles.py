"""Roles and people from the dashboard: making, changing and deleting a role (with the guards that
keep the system whole) and adding a person.

The role and person tests run against throwaway databases on this computer (MIGRATE_TEST_PG, see
test_migrate.py). The menu tests need no database."""

import asyncio

import asyncpg
import pytest
from fastapi import HTTPException

from app import db
from app.admin_panel import common, meta, people, roles
from app.admin_panel.common import Ctx
from tests.test_migrate import needs_pg

ORG = "00000000-0000-0000-0000-00000000000a"

SCHEMA = """
CREATE TABLE roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, name text NOT NULL,
    permissions text[] DEFAULT '{}', created_at timestamptz DEFAULT now(),
    readable_tables text[] NOT NULL DEFAULT '{}', is_approver boolean NOT NULL DEFAULT false,
    approval_max_amount numeric(12,2), readable_entity_types text[] NOT NULL DEFAULT '{}',
    UNIQUE (org_id, name));
CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, role_id uuid REFERENCES roles(id),
    name text NOT NULL, phone text, email text NOT NULL, channel text DEFAULT 'telegram',
    is_active boolean DEFAULT true, created_at timestamptz DEFAULT now(),
    UNIQUE (org_id, email), UNIQUE (org_id, phone));
CREATE TABLE workflows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, intent_key text NOT NULL,
    name text NOT NULL, description text, steps jsonb DEFAULT '[]', entity_schema jsonb NOT NULL DEFAULT '{}',
    gates jsonb NOT NULL DEFAULT '[]', sql_template text, is_active boolean DEFAULT true, created_at timestamptz DEFAULT now(),
    kind text NOT NULL DEFAULT 'workflow', UNIQUE (org_id, intent_key));
CREATE TABLE access_grants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    role_id uuid REFERENCES roles(id) ON DELETE CASCADE);
CREATE TABLE routing_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    assign_role_id uuid REFERENCES roles(id) ON DELETE RESTRICT,
    backup_role_id uuid REFERENCES roles(id) ON DELETE SET NULL);
CREATE TABLE admin_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, actor_user_id uuid,
    actor_label text, area text NOT NULL, action text NOT NULL, target_type text, target_id text,
    summary text NOT NULL, before_state jsonb, after_state jsonb, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE cases (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid, case_number text);
CREATE TABLE residents (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid, flat_no text);
CREATE TABLE schema_migrations (version text);
-- a database rule that moves people between two roles by name
CREATE FUNCTION move_people() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a uuid; b uuid;
BEGIN
  SELECT id INTO a FROM roles WHERE org_id = NEW.org_id AND name = 'committee';
  SELECT id INTO b FROM roles WHERE org_id = NEW.org_id AND name = 'member';
  RETURN NEW;
END; $$;
"""

CAPS = {
    "grants": True,
    "routing": True,
    "events": True,
    "role_editor": True,
    "workflow_kind": True,
}


def ctx():
    return Ctx(
        source_key="alpha",
        org_id=ORG,
        org_name="Alpha",
        caps=dict(CAPS),
        actor="test",
        closed_values=["closed"],
    )


def run(world, work):
    """Run `work(conn)` (an async function) with the app's database helpers pointed at the throwaway database."""

    async def go():
        pool = await asyncpg.create_pool(
            world.dsn["alpha"], min_size=1, max_size=4, statement_cache_size=0
        )
        db._pools["alpha"] = pool
        try:
            async with pool.acquire() as conn:
                return await work(conn)
        finally:
            db._pools.pop("alpha", None)
            await pool.close()

    return asyncio.run(go())


async def refused(coro):
    try:
        await coro
    except HTTPException as e:
        return e
    raise AssertionError("expected the request to be refused")


async def seed(conn):
    await conn.execute(SCHEMA)
    ids = {}
    for name, perms, tables in [
        ("admin", ["case_close", "view_my_cases", "close_case", "general_read"], ["cases", "users"]),
        ("committee", ["view_my_cases"], ["cases"]),
        ("member", [], []),
        ("owner", ["view_my_cases"], ["cases"]),
    ]:  # fmt: skip
        ids[name] = await conn.fetchval(
            "INSERT INTO roles (org_id, name, permissions, readable_tables) VALUES ($1, $2, $3, $4) RETURNING id",
            ORG, name, perms, tables,
        )  # fmt: skip
    await conn.execute(
        "INSERT INTO workflows (org_id, intent_key, name, description, steps, entity_schema, kind) VALUES "
        "($1, 'case_close', 'Close a case', 'Closes a case.', $2::jsonb, $3::jsonb, 'workflow'),"
        "($1, 'view_my_cases', 'My cases', 'Your open cases.', '[]'::jsonb, '{}'::jsonb, 'workflow'),"
        "($1, 'find_case', 'Find a case', NULL, '[]'::jsonb, '{}'::jsonb, 'block')",
        ORG,
        '[{"op": "require_permission", "params": {"any_of": ["close_case"]}}]',
        '{"case_number": {"type": "text", "table": "cases", "column": "case_number"}}',
    )
    for n, who in [("Asha", "admin"), ("Bela", "admin"), ("Chitra", "committee")]:
        await conn.execute(
            "INSERT INTO users (org_id, role_id, name, email) VALUES ($1, $2, $3, $4)",
            ORG, ids[who], n, f"{n.lower()}@example.com",
        )  # fmt: skip
    return ids


def by_name(listing):
    return {r["name"]: r for r in listing["roles"]}


# ------------------------------------------------------------ the list


@needs_pg
def test_the_list_says_what_each_role_can_do_and_what_protects_it(world):
    async def work(conn):
        await seed(conn)
        d = await roles.list_roles(ctx())
        r = by_name(d)
        assert [f["intent_key"] for f in d["flows"]] == [
            "case_close",
            "view_my_cases",
        ]  # a building block is not offered
        assert r["admin"]["can"] == ["case_close", "view_my_cases"]
        assert set(r["admin"]["other_permissions"]) == {"close_case", "general_read"}
        assert r["admin"]["people_count"] == 2 and r["admin"]["people"] == [
            "Asha",
            "Bela",
        ]
        # two names are used by a database rule, so they are built in
        assert r["committee"]["built_in"] and r["member"]["built_in"]
        assert not r["admin"]["built_in"] and not r["owner"]["built_in"]
        assert r["owner"]["delete_blocked"] is None
        assert "2 people have this role" in r["admin"]["delete_blocked"]
        assert "cases" in d["tables"] and "workflows" not in d["tables"]
        assert "roles" not in d["tables"] and "schema_migrations" not in d["tables"]

    run(world, work)


# ------------------------------------------------------------ making a role


@needs_pg
def test_a_new_role_starts_as_a_copy_and_the_flows_bring_what_they_need(world):
    async def work(conn):
        ids = await seed(conn)
        made = await roles.create_role(
            ctx(),
            roles.RoleBody(name="  second   owner ", copy_from=ids["owner"], flows=["case_close"], tables=[]),
        )  # fmt: skip
        row = await conn.fetchrow("SELECT * FROM roles WHERE id = $1", made["id"])
        assert row["name"] == "second owner"  # spaces tidied
        # the flow it may start, and the finer permission and the data that flow needs, came with it
        assert "case_close" in row["permissions"] and "close_case" in row["permissions"]
        assert "cases" in row["readable_tables"]
        assert (
            "view_my_cases" not in row["permissions"]
        )  # the copy was told exactly which flows
        event = await conn.fetchrow("SELECT * FROM admin_events WHERE area = 'roles'")
        assert event["action"] == "create" and "second owner" in event["summary"]

    run(world, work)


@needs_pg
def test_a_copy_without_a_list_of_flows_keeps_everything_the_original_could_do(world):
    async def work(conn):
        ids = await seed(conn)
        made = await roles.create_role(
            ctx(), roles.RoleBody(name="deputy", copy_from=ids["admin"])
        )
        row = await conn.fetchrow("SELECT * FROM roles WHERE id = $1", made["id"])
        assert set(row["permissions"]) == {
            "case_close",
            "view_my_cases",
            "close_case",
            "general_read",
        }
        assert set(row["readable_tables"]) == {"cases", "users"}
        assert not row["is_approver"] and row["approval_max_amount"] is None

    run(world, work)


@needs_pg
def test_an_empty_role_can_start_nothing(world):
    async def work(conn):
        await seed(conn)
        made = await roles.create_role(ctx(), roles.RoleBody(name="guest"))
        row = await conn.fetchrow("SELECT * FROM roles WHERE id = $1", made["id"])
        assert row["permissions"] == [] and row["readable_tables"] == []

    run(world, work)


@needs_pg
@pytest.mark.parametrize(
    ("body", "status", "words"),
    [
        ({"name": "Owner"}, 409, "already a role called"),
        ({"name": "x"}, 400, "2 to 40 characters"),
        ({"name": "ok", "flows": ["nope"]}, 400, "Unknown flow: nope"),
        ({"name": "ok", "tables": ["nope"]}, 400, "Unknown data: nope"),
        ({"name": "ok", "flows": ["find_case"]}, 400, "Unknown flow"),  # a building block is not given to roles
    ],
)  # fmt: skip
def test_a_role_that_makes_no_sense_is_refused_in_plain_words(
    world, body, status, words
):
    async def work(conn):
        await seed(conn)
        e = await refused(roles.create_role(ctx(), roles.RoleBody(**body)))
        assert e.status_code == status and words in e.detail
        assert await conn.fetchval("SELECT count(*) FROM roles") == 4

    run(world, work)


# ------------------------------------------------------------ changing a role


@needs_pg
def test_taking_a_flow_away_removes_it_and_what_only_it_needed(world):
    async def work(conn):
        ids = await seed(conn)
        await roles.update_role(
            ctx(), ids["admin"], roles.RolePatch(flows=["view_my_cases"])
        )
        row = await conn.fetchrow("SELECT * FROM roles WHERE id = $1", ids["admin"])
        assert (
            "case_close" not in row["permissions"]
            and "close_case" not in row["permissions"]
        )
        assert "view_my_cases" in row["permissions"]
        # the other roles are untouched
        other = await conn.fetchrow(
            "SELECT permissions FROM roles WHERE id = $1", ids["owner"]
        )
        assert other["permissions"] == ["view_my_cases"]

    run(world, work)


@needs_pg
def test_data_a_flow_reads_cannot_be_taken_away_while_the_flow_stays(world):
    async def work(conn):
        ids = await seed(conn)
        await roles.update_role(ctx(), ids["admin"], roles.RolePatch(tables=["users"]))
        row = await conn.fetchrow(
            "SELECT readable_tables FROM roles WHERE id = $1", ids["admin"]
        )
        assert set(row["readable_tables"]) == {
            "users",
            "cases",
        }  # "Close a case" reads cases

    run(world, work)


@needs_pg
def test_approval_limits_are_kept_and_cleared_with_the_switch(world):
    async def work(conn):
        ids = await seed(conn)
        await roles.update_role(
            ctx(),
            ids["owner"],
            roles.RolePatch(is_approver=True, approval_max_amount=5000),
        )
        row = await conn.fetchrow(
            "SELECT is_approver, approval_max_amount FROM roles WHERE id = $1",
            ids["owner"],
        )
        assert row["is_approver"] and float(row["approval_max_amount"]) == 5000
        await roles.update_role(ctx(), ids["owner"], roles.RolePatch(is_approver=False))
        row = await conn.fetchrow(
            "SELECT is_approver, approval_max_amount FROM roles WHERE id = $1",
            ids["owner"],
        )
        assert not row["is_approver"] and row["approval_max_amount"] is None

    run(world, work)


def test_a_negative_approval_limit_is_not_accepted():
    with pytest.raises(ValueError):
        roles.RolePatch(approval_max_amount=-1)


@needs_pg
def test_a_plain_role_can_be_renamed_and_the_change_is_logged(world):
    async def work(conn):
        ids = await seed(conn)
        await roles.update_role(ctx(), ids["owner"], roles.RolePatch(name="flat owner"))
        assert (
            await conn.fetchval("SELECT name FROM roles WHERE id = $1", ids["owner"])
            == "flat owner"
        )
        event = await conn.fetchrow(
            "SELECT * FROM admin_events WHERE action = 'update'"
        )
        assert event["before_state"] and event["after_state"]

    run(world, work)


@needs_pg
def test_a_role_a_database_rule_uses_by_name_cannot_be_renamed(world):
    async def work(conn):
        ids = await seed(conn)
        e = await refused(
            roles.update_role(ctx(), ids["committee"], roles.RolePatch(name="board"))
        )
        assert e.status_code == 409 and "cannot be renamed" in e.detail
        # what it may do can still be changed
        await roles.update_role(
            ctx(), ids["committee"], roles.RolePatch(flows=["case_close"])
        )
        assert "case_close" in await conn.fetchval(
            "SELECT permissions FROM roles WHERE id = $1", ids["committee"]
        )

    run(world, work)


@needs_pg
def test_a_role_named_in_a_flows_safeguards_cannot_be_renamed(world):
    async def work(conn):
        ids = await seed(conn)
        await conn.execute(
            "UPDATE workflows SET gates = $1::jsonb WHERE intent_key = 'case_close'",
            '[{"type": "permission", "role_any_of": ["owner"]}]',
        )
        e = await refused(
            roles.update_role(ctx(), ids["owner"], roles.RolePatch(name="flat owner"))
        )
        assert (
            e.status_code == 409
            and "Close a case" in e.detail
            and "safeguards" in e.detail
        )

    run(world, work)


@needs_pg
def test_two_roles_cannot_share_a_name_even_in_other_capitals(world):
    async def work(conn):
        ids = await seed(conn)
        e = await refused(
            roles.update_role(ctx(), ids["owner"], roles.RolePatch(name="ADMIN"))
        )
        assert e.status_code == 409

    run(world, work)


# ------------------------------------------------------------ deleting a role


@needs_pg
def test_a_role_that_is_still_used_cannot_be_deleted_and_says_by_whom(world):
    async def work(conn):
        ids = await seed(conn)
        e = await refused(roles.delete_role(ctx(), ids["admin"]))
        assert e.status_code == 409 and "2 people have this role" in e.detail
        await conn.execute(
            "UPDATE users SET role_id = $1 WHERE role_id = $2",
            ids["owner"],
            ids["admin"],
        )
        await conn.execute(
            "INSERT INTO access_grants (org_id, role_id) VALUES ($1, $2)",
            ORG,
            ids["admin"],
        )
        e = await refused(roles.delete_role(ctx(), ids["admin"]))
        assert (
            "special access" in e.detail
        )  # deleting it would have silently removed the access
        await conn.execute("DELETE FROM access_grants")
        await conn.execute(
            "INSERT INTO routing_rules (org_id, backup_role_id) VALUES ($1, $2)",
            ORG,
            ids["admin"],
        )
        e = await refused(roles.delete_role(ctx(), ids["admin"]))
        assert "routing rule" in e.detail

    run(world, work)


@needs_pg
def test_a_built_in_role_cannot_be_deleted_even_when_nobody_has_it(world):
    async def work(conn):
        ids = await seed(conn)
        e = await refused(roles.delete_role(ctx(), ids["member"]))
        assert e.status_code == 409 and "database rule" in e.detail
        assert (
            await conn.fetchval("SELECT count(*) FROM roles WHERE name = 'member'") == 1
        )

    run(world, work)


@needs_pg
def test_a_role_nobody_uses_can_be_deleted_and_it_is_logged(world):
    async def work(conn):
        ids = await seed(conn)
        made = await roles.create_role(ctx(), roles.RoleBody(name="guest"))
        await roles.delete_role(ctx(), made["id"])
        assert (
            await conn.fetchval("SELECT count(*) FROM roles WHERE name = 'guest'") == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM admin_events WHERE action = 'delete'"
            )
            == 1
        )
        assert ids

    run(world, work)


@needs_pg
def test_changing_or_deleting_a_role_that_is_not_there_says_so(world):
    async def work(conn):
        await seed(conn)
        gone = "00000000-0000-0000-0000-0000000000ff"
        for call in (
            roles.delete_role(ctx(), gone),
            roles.update_role(ctx(), gone, roles.RolePatch(name="zz")),
        ):
            e = await refused(call)
            assert e.status_code == 404

    run(world, work)


# ------------------------------------------------------------ adding a person


@needs_pg
def test_a_person_can_be_added_by_name_email_and_role_where_people_are_found_by_email(
    world,
):
    async def work(conn):
        ids = await seed(conn)
        made = await people.add_person(
            ctx(), people.PersonNew(name=" Dev  Rao ", email=" Dev.Rao@Example.com ", role_id=ids["owner"])
        )  # fmt: skip
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", made["id"])
        assert row["name"] == "Dev Rao" and row["email"] == "dev.rao@example.com"
        assert (
            row["phone"] is None and row["channel"] == "telegram" and row["is_active"]
        )
        assert (
            await conn.fetchrow(
                "SELECT summary FROM admin_events WHERE action = 'create'"
            )
        )["summary"] == "Added Dev Rao as owner"

    run(world, work)


@needs_pg
@pytest.mark.parametrize(
    ("patch", "status", "words"),
    [
        ({"email": "not-an-email"}, 400, "does not look like an email"),
        ({"email": "asha@example.com"}, 409, "Asha is already here"),
        ({"name": " "}, 400, "name"),
    ],
)  # fmt: skip
def test_a_person_who_cannot_be_added_is_told_why_and_nothing_is_written(
    world, patch, status, words
):
    async def work(conn):
        ids = await seed(conn)
        body = {
            "name": "Dev Rao",
            "email": "dev@example.com",
            "role_id": ids["owner"],
            **patch,
        }
        e = await refused(people.add_person(ctx(), people.PersonNew(**body)))
        assert e.status_code == status and words in e.detail
        assert await conn.fetchval("SELECT count(*) FROM users") == 3

    run(world, work)


@needs_pg
def test_a_role_that_is_not_there_cannot_be_given(world):
    async def work(conn):
        await seed(conn)
        e = await refused(
            people.add_person(
                ctx(),
                people.PersonNew(
                    name="Dev Rao",
                    email="dev@example.com",
                    role_id="00000000-0000-0000-0000-0000000000ff",
                ),
            )
        )
        assert e.status_code == 404

    run(world, work)


@needs_pg
def test_where_people_are_known_by_their_number_it_is_kept_tidied_and_may_be_left_out(
    world,
):
    async def work(conn):
        ids = await seed(conn)
        await conn.execute(
            "ALTER TABLE users ALTER COLUMN channel SET DEFAULT 'whatsapp'"
        )
        common._channel_cache.clear()
        # no number: the person links themselves with their email, as on Telegram
        left_out = await people.add_person(
            ctx(),
            people.PersonNew(
                name="Kim Rao", email="kim@example.com", role_id=ids["owner"]
            ),
        )
        row = await conn.fetchrow(
            "SELECT phone, channel FROM users WHERE id = $1", left_out["id"]
        )
        assert row["phone"] is None and row["channel"] == "whatsapp"
        e = await refused(
            people.add_person(
                ctx(),
                people.PersonNew(
                    name="Dev Rao",
                    email="dev@example.com",
                    role_id=ids["owner"],
                    phone="98765 43210",
                ),
            )
        )
        assert e.status_code == 400
        made = await people.add_person(
            ctx(),
            people.PersonNew(
                name="Dev Rao",
                email="dev@example.com",
                role_id=ids["owner"],
                phone="+91 98765-43210",
            ),
        )
        row = await conn.fetchrow(
            "SELECT phone, channel FROM users WHERE id = $1", made["id"]
        )
        assert row["phone"] == "+919876543210" and row["channel"] == "whatsapp"
        e = await refused(
            people.add_person(
                ctx(),
                people.PersonNew(
                    name="Eva Rao",
                    email="eva@example.com",
                    role_id=ids["owner"],
                    phone="0091 98765 43210",
                ),
            )
        )
        assert e.status_code == 409 and "email or number" in e.detail
        common._channel_cache.clear()

    run(world, work)


# ------------------------------------------------------------ the menu (no database)

HOUSING = {
    "cases": True, "case_model": True, "targets": True, "seats": True, "grants": True,
    "events": True, "audit": True, "texts": True, "prompts": True, "role_editor": True,
}  # fmt: skip


def keys(caps):
    return [s["key"] for s in meta._sections(caps)]


def test_a_housing_organisation_gets_the_whole_menu_in_the_new_order():
    assert keys(HOUSING) == [
        "overview", "cases", "conversations", "people", "access", "assistant", "workflows", "settings",
    ]  # fmt: skip
    tabs = {
        s["key"]: [t["key"] for t in s.get("tabs", [])] for s in meta._sections(HOUSING)
    }
    assert tabs["cases"] == [
        "list",
        "teams",
        "categories",
        "rules",
        "times",
    ]  # Tickets holds the old Case rules
    assert tabs["access"] == ["roles", "seats", "special"]
    assert tabs["assistant"] == ["messages", "instructions", "whatsapp"]
    assert tabs["settings"] == ["general", "history"]


def test_an_organisation_without_cases_has_no_case_screens():
    caps = {"audit": True, "events": True, "texts": True, "prompts": True}
    assert keys(caps) == [
        "overview",
        "conversations",
        "people",
        "access",
        "assistant",
        "workflows",
        "settings",
    ]
    tabs = {
        s["key"]: [t["key"] for t in s.get("tabs", [])] for s in meta._sections(caps)
    }
    assert tabs["access"] == ["roles"]


def test_set_up_screens_that_the_database_cannot_do_are_left_out_and_never_shown_empty():
    assert keys({"cases": True}) == [
        "overview",
        "cases",
        "people",
        "access",
        "assistant",
        "workflows",
        "settings",
    ]
    only_times = [
        s
        for s in meta._sections({"cases": True, "targets": True})
        if s["key"] == "cases"
    ]
    assert [t["key"] for t in only_times[0]["tabs"]] == ["list", "times"]


def test_an_admin_gets_the_day_to_day_screens_only():
    admin = meta._sections(HOUSING, "admin")
    assert [s["key"] for s in admin] == ["overview", "cases", "conversations", "people"]
    assert [t["key"] for t in admin[1]["tabs"]] == [
        "list",
        "teams",
    ]  # Who handles what, read only
    clock = meta._sections(
        {**HOUSING, "tat_clock": True}, "admin"
    )  # with the clock (housing-0013): Reminders too
    assert [t["key"] for t in clock[1]["tabs"]] == ["list", "teams", "reminders"]
    # the super admin's copy is not changed by working out the admin's
    assert [t["key"] for t in meta._sections(HOUSING)[1]["tabs"]] == [
        "list",
        "teams",
        "categories",
        "rules",
        "times",
    ]


def test_the_menu_numbers_never_turn_a_problem_into_an_error(monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("no route_case here")

    monkeypatch.setattr(meta, "fetch_one", broken)
    got = asyncio.run(
        meta.nav_hints(Ctx("alpha", "o", "Alpha", {"cases": True}, "t", ["closed"]))
    )
    assert got == {"unassigned": None, "rule_gaps": None}


def test_building_blocks_get_their_own_screen_for_super_admins_only():
    caps = {**HOUSING, "workflow_kind": True}
    assert keys(caps)[-3:] == ["workflows", "blocks", "settings"]
    assert "blocks" not in [s["key"] for s in meta._sections(caps, "admin")]
    assert "blocks" not in keys(
        HOUSING
    )  # without kinds in the database there are no blocks to show
