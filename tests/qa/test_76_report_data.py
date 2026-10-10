"""A stored report a role has been given runs with the data the report itself reads. The role's table list limits only
what the chat bot may look up freely. Before, a role that held a report but not a table the report joined was offered it
on the menu and then told it had no access. Fake chats, as ever."""

from app.admin_panel import roles
from app.services import agent
from tests.qa.harness import needs_qa, qa_run

REPORT = "rpt_people_names"


async def give_report_to_member(w, *, held=True):
    """A read report over the people table, and a member role that may read cases only."""
    await w.run(
        "INSERT INTO workflows (org_id, intent_key, name, workflow_type, sql_template, response_format, menu_section, is_active) "
        "VALUES ($1, $2, 'People names', 'read', 'SELECT u.name FROM users u WHERE u.org_id = $1 ORDER BY u.name', 'generic', 'reports', true)",
        w.ids.org_id,
        REPORT,
    )
    member = await w.user("member")
    await w.run(
        "UPDATE roles SET readable_tables = ARRAY['cases'], "
        "permissions = CASE WHEN $2 THEN array_append(permissions, $3) ELSE array_remove(permissions, $3) END "
        "WHERE id = (SELECT role_id FROM users WHERE id = $1::uuid)",
        member["user_id"],
        held,
        REPORT,
    )
    return await w.user("member")


async def run_report(user):
    return await agent._execute_tool(
        "run_workflow_query",
        {"intent_key": REPORT, "params": {}},
        user,
        user["phone"],
    )


@needs_qa
def test_a_role_that_holds_a_report_can_run_it_though_the_role_cannot_read_the_table_it_joins():
    async def scenario(w):
        user = await give_report_to_member(w)
        assert "users" not in user["readable_tables"]
        got = await run_report(user)
        assert "not permitted" not in str(got) and "ERROR" not in str(got), got
        assert "Test" in str(got) or "[" in str(got), got

    qa_run(scenario)


@needs_qa
def test_a_role_that_does_not_hold_the_report_is_still_refused_it():
    async def scenario(w):
        user = await give_report_to_member(w, held=False)
        got = await run_report(user)
        assert "not permitted to use this workflow" in str(got), got

    qa_run(scenario)


@needs_qa
def test_holding_a_report_does_not_open_the_table_to_the_chat_bots_free_lookups():
    async def scenario(w):
        user = await give_report_to_member(w)
        got = await agent._execute_tool(
            "query_database",
            {"sql": "SELECT name FROM users", "params": []},
            user,
            user["phone"],
        )
        assert "not permitted" in str(got) or "blocked" in str(got).lower(), got

    qa_run(scenario)


def test_the_roles_screen_can_say_which_tables_a_report_reads():
    flow = {
        "sql_template": "SELECT a.x FROM cases a LEFT JOIN users u ON u.id = a.y JOIN roles r ON r.id = u.role_id",
        "entity_schema": {},
    }
    assert roles._tables_read_by_report(flow) == [
        "cases",
        "users",
    ]  # roles is a platform table
    assert roles._tables_read_by_report({"sql_template": None}) == []
