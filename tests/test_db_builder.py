"""Your databases and the AI change builder (app/admin_panel/database.py). The AI is never called for real here."""

import json
from types import SimpleNamespace

from fastapi import HTTPException

from app.admin_panel import access_rules, common, database
from app.admin_panel.common import Ctx
from tests.qa.harness import needs_qa, qa_run

GOOD_SQL = """
CREATE TABLE public.visitors (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    guest_name text NOT NULL,
    note text DEFAULT 'drop by; update later',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_visitors_org ON public.visitors (org_id);
COMMENT ON TABLE public.visitors IS 'Guests; delete never';
"""


def plan(**kw) -> database.PlanBody:
    base = {
        "sql": GOOD_SQL,
        "seed": "",
        "rollback": "DROP TABLE public.visitors;",
        "workflows": "[]",
        "permissions": "{}",
        "summary": "Visitors",
    }
    base.update(kw)
    return database.PlanBody(**base)


# ------------------------------------------------------------ no database needed


def test_every_call_is_for_super_admins_only():
    calls = {
        (m, r.path[len(access_rules.PREFIX) :])
        for r in database.router.routes
        for m in r.methods
    }
    assert calls <= access_rules.SUPER_CALLS and not (calls & access_rules.ADMIN_CALLS)


def test_statements_are_split_outside_quotes_dollar_bodies_and_comments():
    got = database.split_sql(
        "CREATE TABLE a (x text DEFAULT 'a;b'); -- c; d\nCOMMENT ON TABLE a IS $t$x;y$t$;\n;"
    )
    assert got == [
        "CREATE TABLE a (x text DEFAULT 'a;b')",
        "COMMENT ON TABLE a IS $t$x;y$t$",
    ]


def test_only_additions_pass_and_ordinary_words_are_not_mistaken_for_danger():
    tables = {"orgs": {"id"}, "cases": {"id", "org_id"}}
    issues, made = database.lint(plan(), tables, set(), {})
    assert not [i for i in issues if i["level"] == "error"], (
        issues
    )  # ON DELETE CASCADE and words in text are fine
    assert made["visitors"] >= {"id", "org_id", "guest_name"}
    for bad in ("DROP TABLE cases;", "DELETE FROM cases;", "UPDATE cases SET title = 'x';", "TRUNCATE cases;",
                "ALTER TABLE cases DROP COLUMN title;", "CREATE EXTENSION IF NOT EXISTS plpython3u;",
                "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;"):  # fmt: skip
        issues, _ = database.lint(plan(sql=bad), tables, set(), {})
        assert any(i["level"] == "error" for i in issues), bad
    issues, _ = database.lint(
        plan(sql="ALTER TABLE nope ADD COLUMN x text;"), tables, set(), {}
    )
    assert any("no table nope" in i["msg"] for i in issues)
    issues, _ = database.lint(plan(rollback=""), tables, set(), {})
    assert any(i["tab"] == "rollback" and i["level"] == "warn" for i in issues)
    issues, _ = database.lint(
        plan(permissions='{"Pre-approve": ["astronaut"]}'), tables, {"owner"}, {}
    )
    assert any("no role called" in i["msg"] for i in issues)


def test_the_ai_answer_is_shaped_for_the_screen(monkeypatch):
    import asyncio

    from app.services import llm_router

    answer = {"say": "Here is the plan.", "reading": [["Keep visitors", "a new table", "new"]],
              "plan": {"intro": "Residents approve guests.", "new": ["visitors"], "sql": GOOD_SQL, "rollback": "DROP TABLE public.visitors;",
                       "workflows": [{"name": "Pre-approve a visitor", "steps": []}], "permissions": {"Pre-approve a visitor": ["owner"]}}}  # fmt: skip

    async def fake(**kw):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="```json\n" + json.dumps(answer) + "\n```"
                    )
                )
            ]
        )

    async def ctx_text(ctx):
        return "Tables: ..."

    monkeypatch.setattr(llm_router, "chat_completion", fake)
    monkeypatch.setattr(database, "context_text", ctx_text)
    ctx = SimpleNamespace(org_name="QA")
    r = asyncio.run(
        database.builder_chat(
            ctx, database.ChatBody(messages=[{"role": "user", "content": "visitors"}])
        )
    )
    assert r["reading"] == [["Keep visitors", "a new table", "new"]]
    assert (
        r["plan"]["sql"].strip().startswith("CREATE TABLE")
        and json.loads(r["plan"]["workflows"])[0]["name"] == "Pre-approve a visitor"
    )
    assert json.loads(r["plan"]["permissions"]) == {"Pre-approve a visitor": ["owner"]}


# ------------------------------------------------------------ on a real copy of the schema


async def start(w) -> Ctx:
    common._caps_cache.clear()
    return Ctx(
        source_key=w.key,
        org_id=w.ids.org_id,
        org_name=w.ids.org_name,
        caps=await common.get_caps(w.key),
        actor="test",
        closed_values=["closed"],
    )


async def refused(coro) -> HTTPException:
    try:
        await coro
    except HTTPException as e:
        return e
    raise AssertionError("expected the request to be refused")


@needs_qa
def test_the_database_view_lists_every_table_with_its_columns():
    async def scenario(w):
        ctx = await start(w)
        d = await database.db_schema(ctx, source="org")
        names = {t["name"]: t for t in d["tables"]}
        assert "cases" in names and any(
            c["name"] == "case_number" for c in names["cases"]["columns"]
        )
        assert "orgs" in names["cases"]["links"]
        assert (
            d["stats"]["tables"] == len(d["tables"])
            and d["stats"]["workflows"] is not None
        )
        assert "visitors" not in names

    qa_run(scenario)


@needs_qa
def test_a_plan_is_tried_and_undone_and_applied_only_as_checked_after_a_backup():
    async def scenario(w):
        ctx = await start(w)
        flows = json.dumps([{"name": "Pre-approve a visitor", "training_phrases": ["guest coming"],
                             "entity_schema": {"guest_name": {"type": "string", "label": "Guest", "question": "Who is coming?", "required": True}},
                             "steps": [{"op": "db.insert_row", "params": {"table": "visitors", "values": {"guest_name": "$fields.guest_name"}}}]}])  # fmt: skip
        p = plan(workflows=flows, permissions=json.dumps({"Pre-approve a visitor": ["member"]}),
                 seed="INSERT INTO public.visitors (org_id, guest_name) SELECT id, 'Sample guest' FROM public.orgs;")  # fmt: skip
        checked = await database.builder_validate(ctx, p)
        assert checked["ok"] and checked["tried"] and len(checked["ran"]) == 4, checked[
            "issues"
        ]
        assert (await w.one("SELECT to_regclass('public.visitors') IS NULL AS gone"))[
            "gone"
        ]  # nothing was kept
        e = await refused(
            database.builder_apply(
                ctx,
                database.ApplyBody(
                    **p.model_dump(),
                    fingerprint=checked["fingerprint"],
                    backup_taken=False,
                ),
            )
        )
        assert e.status_code == 409 and "backup" in e.detail
        changed = p.model_copy(
            update={
                "sql": p.sql + "\nCREATE INDEX idx_x ON public.visitors (guest_name);"
            }
        )
        e = await refused(
            database.builder_apply(
                ctx,
                database.ApplyBody(
                    **changed.model_dump(),
                    fingerprint=checked["fingerprint"],
                    backup_taken=True,
                ),
            )
        )
        assert "changed after it was checked" in e.detail
        done = await database.builder_apply(
            ctx,
            database.ApplyBody(
                **p.model_dump(), fingerprint=checked["fingerprint"], backup_taken=True
            ),
        )
        assert done["ok"] and done["flows"] == ["Pre-approve a visitor"], done
        assert (await w.one("SELECT count(*) AS n FROM visitors"))["n"] == 1
        flow = await w.one(
            "SELECT is_active FROM workflows WHERE name = 'Pre-approve a visitor'"
        )
        assert flow["is_active"] is False  # made switched off
        role = await w.one(
            "SELECT 'pre_approve_a_visitor' = ANY(permissions) OR EXISTS (SELECT 1 FROM workflows w WHERE w.name = 'Pre-approve a visitor' AND w.intent_key = ANY(r.permissions)) AS ok FROM roles r WHERE name = 'member'"
        )
        assert role["ok"]
        if (
            await w.one(
                "SELECT to_regclass('public.schema_changes') IS NOT NULL AS has"
            )
        )["has"]:
            assert (
                await w.one(
                    "SELECT count(*) AS n FROM schema_changes WHERE status = 'applied'"
                )
            )["n"] == 1
        again = await database.builder_validate(
            ctx, p
        )  # the same plan cannot be applied twice
        assert not again["ok"] and any(
            "already exists" in i["msg"] for i in again["issues"]
        )

    qa_run(scenario)
