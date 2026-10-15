"""Chat bot > Menu (app/admin_panel/chat_menu.py): reading, checking and saving the menu by use case, the starting suggestion, the
preview (the same code the chat bot runs) and the WhatsApp Flow layout, who may use these calls, and the new tab.

Run through the real code on a throwaway database (tests/qa/harness.py), with the endpoint functions called directly."""

import json

from fastapi import HTTPException

from app.admin_panel import access_rules, chat_menu, common, meta
from app.admin_panel.common import Ctx
from tests.qa.harness import needs_qa, qa_run

GOOD = {
    "enabled": True,
    "nodes": [
        {
            "id": "tickets",
            "label": "Tickets",
            "children": [
                {
                    "id": "raise",
                    "label": "Raise",
                    "children": [{"flow": "qa_case_file"}],
                },
                {"flow": "qa_note", "label": "Leave a note"},
            ],
        },
        {"id": "money", "label": "Money", "children": [{"flow": "qa_note_big"}]},
    ],
}


async def start(w, level="super") -> Ctx:
    common._caps_cache.clear()
    return Ctx(
        source_key=w.key,
        org_id=w.ids.org_id,
        org_name=w.ids.org_name,
        caps=await common.get_caps(w.key),
        actor="test",
        closed_values=["closed"],
        level=level,
    )


async def refused(coro) -> HTTPException:
    try:
        await coro
    except HTTPException as e:
        return e
    raise AssertionError("expected the request to be refused")


async def stored(w) -> dict:
    row = await w.one("SELECT settings FROM orgs WHERE id = $1", w.ids.org_id)
    return json.loads(row["settings"])


async def fresh(w, level="super") -> Ctx:
    """A new context, so it carries the organisation's settings as saved by now."""
    ctx = await start(w, level)
    row = await w.one("SELECT settings FROM orgs WHERE id = $1", w.ids.org_id)
    ctx.settings = json.loads(row["settings"])
    return ctx


# ------------------------------------------------------------ reading


@needs_qa
def test_a_new_menu_starts_empty_and_lists_the_flows_to_place():
    async def scenario(w):
        ctx = await fresh(w)
        got = await chat_menu.read_menu(ctx)
        assert got["configured"] is False
        assert got["config"] == {"enabled": False, "nodes": [], "show_unplaced": True}
        keys = {f["intent_key"] for f in got["flows"]}
        assert {"qa_case_file", "qa_note", "qa_note_big"} <= keys
        assert {r["name"] for r in got["roles"]} >= {"member", "approver"}
        assert got["words"]["back_label"] == "Back" and got["limits"]["use_cases"] == 10

    qa_run(scenario)


# ------------------------------------------------------------ saving


@needs_qa
def test_a_good_menu_is_saved_in_the_settings_and_read_back():
    async def scenario(w):
        ctx = await fresh(w)
        out = await chat_menu.save_menu(ctx, chat_menu.MenuBody(config=GOOD))
        assert out["ok"] and out["config"]["nodes"][0]["id"] == "tickets"
        assert (await stored(w))["chat_menu"] == out["config"]
        again = await chat_menu.read_menu(await fresh(w))
        assert again["configured"] is True and again["config"]["enabled"] is True
        assert again["config"]["nodes"][0]["children"][1]["label"] == "Leave a note"
        # the rest of the settings is untouched (the vocabulary the QA organisation was made with)
        assert "vocabulary" in await stored(w)

    qa_run(scenario)


@needs_qa
def test_saving_is_written_in_the_change_log():
    async def scenario(w):
        ctx = await fresh(w)
        if not ctx.caps.get("events"):
            return
        await chat_menu.save_menu(ctx, chat_menu.MenuBody(config=GOOD))
        row = await w.one(
            "SELECT summary, area FROM admin_events WHERE action = 'chat_menu' ORDER BY created_at DESC LIMIT 1"
        )
        assert row and row["area"] == "settings" and "switched on" in row["summary"]

    qa_run(scenario)


@needs_qa
def test_a_menu_that_cannot_work_is_refused_and_nothing_changes():
    async def scenario(w):
        ctx = await fresh(w)
        for bad, words in [
            (
                {
                    "enabled": True,
                    "nodes": [
                        {
                            "id": "a",
                            "label": "A",
                            "children": [{"flow": "no_such_flow"}],
                        }
                    ],
                },
                "does not exist",
            ),
            ({"enabled": True, "nodes": []}, "at least one use case"),
            (
                {"enabled": True, "nodes": [{"label": "", "children": []}]},
                "needs a name",
            ),
        ]:
            err = await refused(
                chat_menu.save_menu(ctx, chat_menu.MenuBody(config=bad))
            )
            assert err.status_code == 400 and words in err.detail
        assert "chat_menu" not in await stored(w)

    qa_run(scenario)


@needs_qa
def test_an_admin_who_is_not_a_super_admin_cannot_change_it():
    async def scenario(w):
        ctx = await fresh(w, level="admin")
        err = await refused(chat_menu.save_menu(ctx, chat_menu.MenuBody(config=GOOD)))
        assert err.status_code == 403
        err = await refused(
            chat_menu.preview_menu(ctx, chat_menu.PreviewBody(config=GOOD))
        )
        assert err.status_code == 403
        assert "chat_menu" not in await stored(w)

    qa_run(scenario)


# ------------------------------------------------------------ the starting suggestion


@needs_qa
def test_the_suggestion_is_todays_menu_as_use_cases_and_saves_nothing():
    async def scenario(w):
        ctx = await fresh(w)
        got = (await chat_menu.suggest_menu(ctx))["config"]
        assert got["enabled"] is False
        placed = {c["flow"] for n in got["nodes"] for c in n["children"]}
        assert placed >= {"qa_case_file", "qa_note"}
        assert all(chat_menu.chat_menu.ID_OK.match(n["id"]) for n in got["nodes"])
        assert "chat_menu" not in await stored(w)
        # it is itself a menu that can be saved
        await chat_menu.save_menu(
            ctx, chat_menu.MenuBody(config={**got, "enabled": True})
        )

    qa_run(scenario)


# ------------------------------------------------------------ the preview


@needs_qa
def test_the_preview_shows_every_list_and_the_flow_layout_without_saving():
    async def scenario(w):
        ctx = await fresh(w)
        got = await chat_menu.preview_menu(ctx, chat_menu.PreviewBody(config=GOOD))
        paths = [s["path"] for s in got["screens"]]
        assert (
            paths[0] == "Menu"
            and "Tickets" in paths
            and "Tickets › Raise" in paths
            and "Money" in paths
        )
        top = got["screens"][0]["pages"][0]
        assert [r["title"] for r in top["rows"]][:2] == ["Tickets", "Money"]
        layout = json.loads(got["flow_json"])
        assert [s["id"] for s in layout["screens"]] == [
            "MENU",
            "SECTION",
            "SUBSECTION",
            "DONE",
        ]
        assert got["panel"]["fits"] is True and got["empty"] is False
        assert "chat_menu" not in await stored(w)  # looking is not saving

    qa_run(scenario)


@needs_qa
def test_the_preview_as_a_role_shows_only_what_that_role_may_use():
    async def scenario(w):
        ctx = await fresh(w)
        member = w.ids.role["member"]  # qa_case_file, qa_note, qa_partial_fail
        got = await chat_menu.preview_menu(
            ctx, chat_menu.PreviewBody(config=GOOD, role_id=member)
        )
        shown = {
            r["title"] for s in got["screens"] for p in s["pages"] for r in p["rows"]
        }
        assert "Money" not in shown and "Leave a note" in shown
        err = await refused(
            chat_menu.preview_menu(
                ctx,
                chat_menu.PreviewBody(
                    config=GOOD, role_id="00000000-0000-0000-0000-000000000000"
                ),
            )
        )
        assert err.status_code == 404

    qa_run(scenario)


@needs_qa
def test_the_preview_of_a_long_group_shows_every_page():
    async def scenario(w):
        ctx = await fresh(w)
        keys = [f["intent_key"] for f in (await chat_menu.read_menu(ctx))["flows"]]
        for i in range(14):  # enough flows for a group of more than ten
            await w.run(
                "INSERT INTO workflows (org_id, intent_key, name, steps, entity_schema, gates, is_active, workflow_type) "
                "VALUES ($1, $2, $3, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, true, 'action')",
                w.ids.org_id, f"extra_{i:02d}", f"Extra {i:02d}",
            )  # fmt: skip
        ctx = await fresh(w)
        cfg = {"enabled": True, "show_unplaced": False, "nodes": [
            {"id": "big", "label": "Big", "children": [{"flow": f"extra_{i:02d}"} for i in range(14)]},
            {"id": "small", "label": "Small", "children": [{"flow": keys[0]}]},
        ]}  # fmt: skip
        admin_view = await chat_menu.preview_menu(
            ctx, chat_menu.PreviewBody(config=cfg)
        )
        big = next(s for s in admin_view["screens"] if s["path"] == "Big")
        assert len(big["pages"]) == 2 and len(big["pages"][0]["rows"]) == 10

    qa_run(scenario)


# ------------------------------------------------------------ who may use it, and the tab


def test_these_calls_are_for_super_admins_only():
    for call in [
        ("GET", "/chat-menu"),
        ("PUT", "/chat-menu"),
        ("POST", "/chat-menu/preview"),
        ("POST", "/chat-menu/suggest"),
    ]:
        assert call in access_rules.SUPER_CALLS and call not in access_rules.ADMIN_CALLS


def test_the_chat_bot_section_has_a_menu_tab_for_a_super_admin_and_not_for_an_admin():
    caps = {"texts": True, "prompts": True, "cases": True}
    section = next(s for s in meta._sections(caps) if s["key"] == "assistant")
    tabs = [t["key"] for t in section["tabs"]]
    assert tabs == ["messages", "instructions", "whatsapp", "templates", "menu"]
    assert next(t["label"] for t in section["tabs"] if t["key"] == "menu") == "Menu"
    # an organisation with nothing else in the section still gets the menu tab
    bare = next(s for s in meta._sections({}) if s["key"] == "assistant")
    assert [t["key"] for t in bare["tabs"]] == ["menu"]
    assert "assistant" not in meta.ADMIN_SECTIONS


def test_the_screen_says_it_in_plain_words():
    from app.admin_panel.ui import APP_JS

    for part in [
        "renderChatMenu",
        "Use this menu in the chat",
        "Start from today’s menu",
        "Add a use case",
        "Not placed yet",
        "As a WhatsApp panel",
        "Nothing is sent to Meta from this page",
    ]:
        assert part in APP_JS, part
    assert "Assistant" not in APP_JS
