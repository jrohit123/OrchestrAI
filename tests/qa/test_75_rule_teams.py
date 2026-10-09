"""A case rule can name a team: people with a level (1 or 2) instead of one person, one seat or one role.
Level 1: the first one who can be messaged owns the case, the other Level 1 people are told too. Level 2: supporting
people, also told. Everything is asked of the database's own route_case(), the way a new case does. Fake chats, as ever."""

import uuid

import pytest
from fastapi import HTTPException

from app.admin_panel import routing
from app.admin_panel.common import Ctx
from tests.qa.harness import needs_qa, qa_run


async def make_rule(w, people, assign_user=None, name="Team rule"):
    """A category with one rule on it and the given people: [(person name in the world, level)]."""
    cat = uuid.uuid4()
    await w.run(
        "INSERT INTO case_categories (id, org_id, key, label) VALUES ($1, $2, $3, 'Team area')",
        cat,
        w.ids.org_id,
        f"team_{cat.hex[:8]}",
    )
    rule = uuid.uuid4()
    await w.run(
        "INSERT INTO routing_rules (id, org_id, name, category_id, assign_user_id) VALUES ($1, $2, $3, $4, $5)",
        rule,
        w.ids.org_id,
        name,
        cat,
        assign_user,
    )
    ids = {}
    for i, (who, level) in enumerate(people):
        user = await w.user(who)
        ids[who] = user["user_id"]
        await w.run(
            "INSERT INTO routing_rule_people (org_id, rule_id, user_id, level, sort_order) VALUES ($1, $2, $3, $4, $5)",
            w.ids.org_id,
            rule,
            uuid.UUID(user["user_id"]),
            level,
            i * 10,
        )
    return cat, rule, ids


async def route(w, cat):
    row = await w.one(
        "SELECT * FROM route_case($1, $2, '{}'::jsonb, NULL, NULL)", w.ids.org_id, cat
    )
    return dict(row) if row else None


def names(ids, who):
    return {str(ids[x]) for x in who}


@needs_qa
def test_the_first_level_1_person_owns_the_case_and_everyone_else_on_the_team_is_told():
    async def scenario(w):
        cat, _rule, ids = await make_rule(
            w, [("member", 1), ("approver", 1), ("staff", 2)]
        )
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(ids["member"]) and got["via"] == "rule"
        assert {str(x) for x in got["level2_ids"]} == names(ids, ["approver", "staff"])

    qa_run(scenario)


@needs_qa
def test_the_order_the_team_was_given_decides_the_owner():
    async def scenario(w):
        cat, _rule, ids = await make_rule(w, [("staff", 1), ("member", 1)])
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(ids["staff"])

    qa_run(scenario)


@needs_qa
def test_a_level_1_person_who_cannot_be_messaged_is_skipped_for_the_next_one():
    async def scenario(w):
        cat, _rule, ids = await make_rule(
            w, [("member", 1), ("approver", 1), ("staff", 2)]
        )
        await w.run(
            "UPDATE users SET is_active = false WHERE id = $1", uuid.UUID(ids["member"])
        )
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(ids["approver"]) and got["via"] == "rule"
        assert {str(x) for x in got["level2_ids"]} == names(ids, ["staff"])

    qa_run(scenario)


@needs_qa
def test_when_no_level_1_person_can_be_reached_a_level_2_person_takes_it():
    async def scenario(w):
        cat, _rule, ids = await make_rule(w, [("member", 1), ("staff", 2)])
        await w.run(
            "UPDATE users SET is_active = false WHERE id = $1", uuid.UUID(ids["member"])
        )
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(ids["staff"]) and got["via"] == "backup"

    qa_run(scenario)


@needs_qa
def test_when_nobody_on_the_team_can_be_reached_the_rules_old_target_is_used():
    async def scenario(w):
        admin = await w.user("admin")
        cat, _rule, ids = await make_rule(
            w, [("member", 1)], assign_user=uuid.UUID(admin["user_id"])
        )
        await w.run(
            "UPDATE users SET is_active = false WHERE id = $1", uuid.UUID(ids["member"])
        )
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(admin["user_id"])

    qa_run(scenario)


@needs_qa
def test_a_rule_without_a_team_works_as_before():
    async def scenario(w):
        admin = await w.user("admin")
        cat, _rule, _ids = await make_rule(
            w, [], assign_user=uuid.UUID(admin["user_id"])
        )
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(admin["user_id"]) and got["via"] == "rule"

    qa_run(scenario)


@needs_qa
def test_a_rule_may_have_a_team_and_no_single_target_but_not_two_targets():
    async def scenario(w):
        admin = await w.user("admin")
        _cat, rule, _ids = await make_rule(w, [("member", 1)])
        assert await w.one(
            "SELECT assign_user_id FROM routing_rules WHERE id = $1", rule
        )
        role = await w.one("SELECT id FROM roles LIMIT 1")
        with pytest.raises(Exception, match="at_most_one_target"):
            await w.run(
                "UPDATE routing_rules SET assign_user_id = $2, assign_role_id = $3 WHERE id = $1",
                rule,
                uuid.UUID(admin["user_id"]),
                role["id"],
            )

    qa_run(scenario)


def panel_ctx(w):
    return Ctx(
        source_key=w.key,
        org_id=w.ids.org_id,
        org_name="QA",
        caps={"case_model": True},
        actor="test",
        closed_values=["closed"],
    )


@needs_qa
def test_the_panel_saves_a_rule_with_a_team_and_lists_it():
    async def scenario(w):
        ctx = panel_ctx(w)
        a, b, c = await w.user("admin"), await w.user("member"), await w.user("staff")
        cat = uuid.uuid4()
        await w.run(
            "INSERT INTO case_categories (id, org_id, key, label) VALUES ($1, $2, 'api_area', 'Api area')",
            cat,
            w.ids.org_id,
        )
        body = routing.RuleBody(
            name="Api team",
            category_id=cat,
            people=[
                routing.PersonOnRule(user_id=b["user_id"], level=1),
                routing.PersonOnRule(user_id=a["user_id"], level=1),
                routing.PersonOnRule(user_id=c["user_id"], level=2),
            ],
        )
        made = await routing.create_rule(ctx, body)
        listed = await routing.list_rules(ctx)
        row = next(r for r in listed["rows"] if str(r["id"]) == str(made["id"]))
        assert [(p["level"], str(p["user_id"])) for p in row["people"]] == [
            (1, str(b["user_id"])),
            (1, str(a["user_id"])),
            (2, str(c["user_id"])),
        ]
        assert row["assign_type"] is None and all(p["reachable"] for p in row["people"])
        got = await route(w, cat)
        assert str(got["assignee_id"]) == str(
            b["user_id"]
        )  # the first Level 1 in the list

    qa_run(scenario)


@needs_qa
def test_an_edit_that_says_nothing_about_the_team_keeps_it_and_an_empty_list_clears_it():
    async def scenario(w):
        ctx = panel_ctx(w)
        cat, rule, _ids = await make_rule(w, [("member", 1), ("staff", 2)])
        admin = await w.user("admin")
        keep = routing.RuleBody(
            name="Renamed",
            category_id=cat,
            assign=routing.Target(type="user", id=admin["user_id"]),
        )
        await routing.update_rule(ctx, rule, keep)
        assert (
            await w.one(
                "SELECT count(*) AS n FROM routing_rule_people WHERE rule_id = $1", rule
            )
        )["n"] == 2
        clear = routing.RuleBody(
            name="Renamed",
            category_id=cat,
            assign=routing.Target(type="user", id=admin["user_id"]),
            people=[],
        )
        await routing.update_rule(ctx, rule, clear)
        assert (
            await w.one(
                "SELECT count(*) AS n FROM routing_rule_people WHERE rule_id = $1", rule
            )
        )["n"] == 0

    qa_run(scenario)


@needs_qa
def test_a_rule_with_nobody_to_handle_it_is_refused_and_so_is_the_same_person_twice():
    async def scenario(w):
        ctx = panel_ctx(w)
        b = await w.user("member")
        cat = uuid.uuid4()
        await w.run(
            "INSERT INTO case_categories (id, org_id, key, label) VALUES ($1, $2, 'nobody_area', 'Nobody area')",
            cat,
            w.ids.org_id,
        )
        for body in (
            routing.RuleBody(name="No one", category_id=cat),
            routing.RuleBody(
                name="Only level 2",
                category_id=cat,
                people=[routing.PersonOnRule(user_id=b["user_id"], level=2)],
            ),
        ):
            with pytest.raises(HTTPException) as nope:
                await routing.create_rule(ctx, body)
            assert (
                nope.value.status_code == 400
                and "Choose who handles it" in nope.value.detail
            )
        twice = routing.RuleBody(
            name="Twice",
            category_id=cat,
            people=[
                routing.PersonOnRule(user_id=b["user_id"], level=1),
                routing.PersonOnRule(user_id=b["user_id"], level=2),
            ],
        )
        with pytest.raises(HTTPException) as nope:
            await routing.create_rule(ctx, twice)
        assert (
            nope.value.status_code == 400
            and "only be on a rule once" in nope.value.detail
        )
        unknown = routing.RuleBody(
            name="Ghost",
            category_id=cat,
            people=[routing.PersonOnRule(user_id=uuid.uuid4(), level=1)],
        )
        with pytest.raises(HTTPException) as nope:
            await routing.create_rule(ctx, unknown)
        assert nope.value.status_code == 404

    qa_run(scenario)
