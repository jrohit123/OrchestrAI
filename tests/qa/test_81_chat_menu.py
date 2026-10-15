"""The chat menu by use case, through the real chat bot code on a throwaway database (Meta and the model are fake).

An organisation with no saved menu gets the very same flat list it always had; one with a saved menu gets its use cases on top,
a tap on one opens its list, and what each person sees follows their role."""

import json

from app.services import config_store, menu
from tests.qa.harness import needs_qa, qa_run

MENU = {
    "enabled": True,
    "nodes": [
        {
            "id": "tickets",
            "label": "Tickets",
            "description": "Complaints and notes",
            "children": [
                {
                    "id": "raise",
                    "label": "Raise",
                    "children": [{"flow": "qa_case_file", "label": "Make a complaint"}],
                },
                {"flow": "qa_note"},
            ],
        },
        {
            "id": "money",
            "label": "Money",
            "children": [{"flow": "qa_note_big"}, {"flow": "qa_big_spend"}],
        },
    ],
    "show_unplaced": False,
}


async def save_menu(w, cfg):
    await w.run(
        "UPDATE orgs SET settings = settings || $1::jsonb WHERE id = $2",
        json.dumps({"chat_menu": cfg}),
        w.ids.org_id,
    )
    config_store.invalidate()


def lists_to(w, phone):
    return [m for m in w.sent if m["kind"] == "list" and m["to"] == phone]


def ids_of(message):
    return [r["id"] for s in message["sections"] for r in s["rows"]]


@needs_qa
def test_an_organisation_with_no_saved_menu_gets_the_flat_menu_it_always_had():
    async def scenario(w):
        phone = w.ids.phone_member
        await w.login("member")
        user = await w.user("member")
        expected = await menu.build_menu_sections(user["org_id"], user)
        assert expected  # the flat menu, built with no saved menu
        await w.say(phone, "/menu")
        sent = lists_to(w, phone)
        assert len(sent) == 1 and sent[0]["sections"] == expected
        flat = [r["id"] for s in expected for r in s["rows"]]
        assert sorted(flat) == ["qa_case_file", "qa_note", "qa_partial_fail"]
        assert not any(i.startswith("menu:") for i in flat)

    qa_run(scenario)


@needs_qa
def test_a_saved_menu_that_is_switched_off_changes_nothing():
    async def scenario(w):
        user = await w.user("member")
        flat = await menu.build_menu_sections(user["org_id"], user)
        await save_menu(w, {**MENU, "enabled": False})
        assert await menu.build_menu_sections(user["org_id"], user) == flat

    qa_run(scenario)


@needs_qa
def test_a_saved_menu_groups_the_flows_by_use_case_and_a_tap_opens_a_group():
    async def scenario(w):
        phone = w.ids.phone_approver
        await w.login("approver")
        await save_menu(w, MENU)
        await w.say(phone, "/menu")
        top = lists_to(w, phone)[-1]
        assert [r["title"] for s in top["sections"] for r in s["rows"]] == [
            "Tickets",
            "Money",
        ]
        await w.say(phone, "menu:tickets")
        inner = lists_to(w, phone)[-1]
        assert top is not inner
        assert ids_of(inner) == [
            "menu:raise",
            "qa_note",
            "menu:",
        ]  # and the way back to the top
        assert inner["text"] == "Complaints and notes"
        await w.say(phone, "menu:raise")
        deep = lists_to(w, phone)[-1]
        assert ids_of(deep) == ["qa_case_file", "menu:tickets"]
        assert deep["sections"][0]["rows"][0]["title"] == "Make a complaint"
        await w.say(phone, "menu:")  # Back, all the way up
        assert ids_of(lists_to(w, phone)[-1]) == ["menu:tickets", "menu:money"]

    qa_run(scenario)


@needs_qa
def test_a_person_with_one_use_case_goes_straight_into_it():
    async def scenario(w):
        phone = w.ids.phone_member
        await w.login("member")
        await save_menu(w, MENU)
        await w.say(phone, "/menu")
        # the member may use qa_case_file and qa_note, nothing of Money: Tickets is the whole menu
        assert ids_of(lists_to(w, phone)[-1]) == ["menu:raise", "qa_note"]

    qa_run(scenario)


@needs_qa
def test_each_role_sees_only_its_own_use_cases():
    async def scenario(w):
        await save_menu(w, MENU)
        member, approver = await w.user("member"), await w.user("approver")
        got_member = await menu.build_menu_sections(member["org_id"], member)
        got_approver = await menu.build_menu_sections(approver["org_id"], approver)
        # the member has Tickets only, so the top of their menu is Tickets itself
        assert [r["id"] for r in got_member[0]["rows"]] == ["menu:raise", "qa_note"]
        # the approver may use qa_case_file, qa_note and qa_note_big: both use cases
        assert [r["id"] for r in got_approver[0]["rows"]] == [
            "menu:tickets",
            "menu:money",
        ]
        from app.services import chat_menu

        opened = await chat_menu.open_view(approver, "menu:money")
        assert [r["id"] for r in opened["sections"][0]["rows"]] == [
            "qa_note_big",
            "menu:",
        ]
        refused = await chat_menu.open_view(
            member, "menu:money"
        )  # not theirs: they get their own top
        assert [r["id"] for r in refused["sections"][0]["rows"]] == [
            "menu:raise",
            "qa_note",
        ]
        assert all("qa_note_big" not in r["id"] for r in refused["sections"][0]["rows"])

    qa_run(scenario)


@needs_qa
def test_flows_nobody_placed_are_not_lost_unless_the_organisation_says_so():
    async def scenario(w):
        user = await w.user("member")
        await save_menu(w, {**MENU, "show_unplaced": True})
        got = await menu.build_menu_sections(user["org_id"], user)
        assert [r["id"] for r in got[0]["rows"]] == ["menu:tickets", "menu:_other"]
        from app.services import chat_menu

        other = await chat_menu.open_view(user, "menu:_other")
        assert [r["id"] for r in other["sections"][0]["rows"]] == [
            "qa_partial_fail",
            "menu:",
        ]

    qa_run(scenario)


@needs_qa
def test_the_menu_panel_follows_the_saved_menu_for_the_persons_role():
    async def scenario(w):
        from app.services import flows

        await save_menu(w, MENU)
        approver = await w.user("approver")
        settings = await config_store.org_settings(
            approver["source_key"], approver["org_id"]
        )
        screen, data = await flows.menu_data(approver, settings)
        assert screen == "MENU"
        assert [i["id"] for i in data["items"]] == ["tickets", "money"]
        money = data["items"][1]["on-click-action"]["payload"]["items"]
        assert [i["on-click-action"]["payload"] for i in money] == [
            {"workflow": "qa_note_big"}
        ]

    qa_run(scenario)
