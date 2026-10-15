"""The chat menu by use case (app/services/chat_menu.py): checking what the dashboard saves, what one person sees (their role
decides), paging of long lists, the tap on a group, and the Flow panel data and layout. No database and no network: the few
things read from outside are replaced."""

import asyncio
import json

import pytest

from app.services import chat_menu, config_store, flows, menu

USER = {"org_id": "o1", "source_key": "godrej", "user_id": "u1"}


def run(coro):
    return asyncio.run(coro)


def wf(key, name, section="other", desc=""):
    return {
        "intent_key": key,
        "name": name,
        "menu_section": section,
        "command_description": desc,
        "slash_command": None,
    }


ALL = [
    wf("file_a_complaint", "File a complaint", "create", "Report a problem"),
    wf("my_cases", "My Open Tickets", "reports", "Cases you are on"),
    wf("view_all_cases", "All Tickets", "reports"),
    wf("book_clubhouse", "Book the clubhouse", "create", "Pick a date"),
    wf("lost_property", "Lost property", "other"),
]

TREE = {
    "enabled": True,
    "nodes": [
        {
            "id": "tickets",
            "label": "Tickets",
            "description": "Complaints and cases",
            "children": [
                {
                    "id": "raise",
                    "label": "Raise",
                    "children": [{"flow": "file_a_complaint"}],
                },
                {"flow": "my_cases", "label": "My tickets"},
                {"flow": "view_all_cases"},
            ],
        },
        {
            "id": "bookings",
            "label": "Bookings",
            "children": [{"flow": "book_clubhouse"}],
        },
    ],
}


def tree_of(cfg=TREE, allowed=ALL):
    return chat_menu.resolve(cfg, allowed)


# ------------------------------------------------------------ checking what is saved


def test_a_menu_is_checked_and_stored_in_its_shape():
    got = chat_menu.clean(TREE, {w["intent_key"] for w in ALL})
    assert got["enabled"] is True and got["show_unplaced"] is True
    assert [n["id"] for n in got["nodes"]] == ["tickets", "bookings"]
    raise_group = got["nodes"][0]["children"][0]
    assert raise_group["children"] == [{"flow": "file_a_complaint", "hidden": False}]
    assert got["nodes"][0]["children"][1] == {
        "flow": "my_cases",
        "hidden": False,
        "label": "My tickets",
    }


@pytest.mark.parametrize(
    "bad, words",
    [
        ({"nodes": "x"}, "no list"),
        ({"enabled": True, "nodes": []}, "at least one use case"),
        ({"nodes": [{"label": "", "children": []}]}, "needs a name"),
        ({"nodes": [{"flow": "my_cases"}]}, "holds use cases"),
        ({"nodes": [{"id": "A B", "label": "x", "children": []}]}, "not allowed"),
        (
            {
                "nodes": [
                    {"id": "a", "label": "A", "children": []},
                    {"id": "a", "label": "B", "children": []},
                ]
            },
            "both called",
        ),
        (
            {"nodes": [{"id": "a", "label": "A", "children": [{"flow": "nope"}]}]},
            "does not exist",
        ),
        (
            {
                "nodes": [
                    {
                        "id": "a",
                        "label": "A",
                        "children": [{"flow": "my_cases"}, {"flow": "my_cases"}],
                    }
                ]
            },
            "placed twice",
        ),
        (
            {
                "nodes": [
                    {
                        "id": "a",
                        "label": "A",
                        "children": [
                            {
                                "id": "b",
                                "label": "B",
                                "children": [{"id": "c", "label": "C", "children": []}],
                            }
                        ],
                    }
                ]
            },
            "three levels",
        ),
    ],
)
def test_a_menu_that_cannot_work_is_refused_in_plain_words(bad, words):
    with pytest.raises(ValueError) as e:
        chat_menu.clean(bad, {"my_cases"})
    assert words in str(e.value)


def test_too_many_use_cases_or_entries_are_refused():
    many = [{"id": f"u{i}", "label": f"U{i}", "children": []} for i in range(11)]
    with pytest.raises(ValueError, match="at most 10 use cases"):
        chat_menu.clean({"nodes": many})
    full = {
        "nodes": [
            {
                "id": "a",
                "label": "A",
                "children": [{"flow": f"f{i}"} for i in range(21)],
            }
        ]
    }
    with pytest.raises(ValueError, match="at most 20 entries"):
        chat_menu.clean(full)


def test_a_missing_id_is_made_and_long_text_is_cut():
    got = chat_menu.clean(
        {"nodes": [{"label": "  Tickets   and more  " + "x" * 40, "children": []}]}
    )
    node = got["nodes"][0]
    assert chat_menu.ID_OK.match(node["id"])
    assert len(node["label"]) == chat_menu.LABEL_MAX and "  " not in node["label"]


def test_nothing_is_in_use_until_the_menu_is_switched_on_and_has_something():
    assert chat_menu.config(None) is None and chat_menu.config({}) is None
    assert chat_menu.config({"chat_menu": {**TREE, "enabled": False}}) is None
    assert chat_menu.config({"chat_menu": {"enabled": True, "nodes": []}}) is None
    assert chat_menu.config({"chat_menu": {"enabled": "yes", "nodes": [1]}}) is None
    assert chat_menu.config({"chat_menu": TREE}) == TREE


# ------------------------------------------------------------ what one person sees


def test_use_cases_come_first_and_each_holds_its_flows_and_groups():
    tree = tree_of()
    assert [n["title"] for n in tree] == ["Tickets", "Bookings", "More"]
    tickets = tree[0]["children"]
    assert [(c["kind"], c["title"]) for c in tickets] == [
        ("group", "Raise"),
        ("flow", "My tickets"),  # the organisation's own name for it
        ("flow", "All Tickets"),
    ]
    assert tickets[0]["children"][0]["id"] == "file_a_complaint"
    assert tickets[1]["description"] == "Cases you are on"  # the flow's own words


def test_a_person_only_sees_the_flows_their_role_may_use_and_empty_groups_vanish():
    only = [w for w in ALL if w["intent_key"] in ("my_cases", "book_clubhouse")]
    tree = tree_of(allowed=only)
    assert [n["title"] for n in tree] == ["Tickets", "Bookings"]
    assert [c["title"] for c in tree[0]["children"]] == ["My tickets"]  # no Raise
    none = tree_of(allowed=[])
    assert none == []
    just_one = tree_of(allowed=[w for w in ALL if w["intent_key"] == "book_clubhouse"])
    assert [n["title"] for n in just_one] == ["Bookings"]


def test_hidden_entries_are_not_shown_and_not_counted_as_unplaced():
    cfg = json.loads(json.dumps(TREE))
    cfg["nodes"][0]["children"][2]["hidden"] = True  # All Tickets
    cfg["nodes"][1]["hidden"] = True  # the Bookings use case
    tree = tree_of(cfg)
    titles = [n["title"] for n in tree]
    assert titles == ["Tickets", "More"]
    assert [c["title"] for c in tree[0]["children"]] == ["Raise", "My tickets"]
    assert [c["id"] for c in tree[1]["children"]] == ["lost_property"]


def test_flows_nobody_placed_go_last_under_a_name_the_organisation_can_change():
    cfg = {**TREE, "other_label": "Everything else"}
    assert tree_of(cfg)[-1]["title"] == "Everything else"
    none = {**TREE, "show_unplaced": False}
    assert [n["title"] for n in tree_of(none)] == ["Tickets", "Bookings"]


def test_the_top_list_has_the_use_cases_and_a_group_row_opens_its_list():
    tree = tree_of()
    top = chat_menu.view(tree, TREE)
    assert [r["title"] for r in top["rows"]] == ["Tickets", "Bookings", "More"]
    assert [r["id"] for r in top["rows"]] == [
        "menu:tickets",
        "menu:bookings",
        "menu:_other",
    ]
    inner = chat_menu.view(tree, TREE, "tickets")
    assert [r["id"] for r in inner["rows"]] == [
        "menu:raise",
        "my_cases",
        "view_all_cases",
        "menu:",  # the way back, to the top
    ]
    assert inner["rows"][-1]["title"] == "Back" and inner["description"] == (
        "Complaints and cases"
    )
    deep = chat_menu.view(tree, TREE, "raise")
    assert [r["id"] for r in deep["rows"]] == ["file_a_complaint", "menu:tickets"]
    assert chat_menu.view(tree, TREE, "gone") is None


def test_a_lone_use_case_is_the_top_of_the_menu_itself():
    cfg = {**TREE, "show_unplaced": False}
    top = chat_menu.view(chat_menu.resolve(cfg, ALL[3:4]), cfg)
    assert [r["id"] for r in top["rows"]] == [
        "book_clubhouse"
    ]  # no Back to a top that is the same list


def test_a_list_message_holds_ten_rows_so_a_long_group_is_paged():
    flows_ = [wf(f"f{i:02d}", f"Flow {i:02d}") for i in range(23)]
    cfg = {
        "nodes": [
            {
                "id": "big",
                "label": "Big",
                "children": [{"flow": w["intent_key"]} for w in flows_[:20]],
            }
        ]
    }
    tree = chat_menu.resolve({**cfg, "show_unplaced": False}, flows_)
    cfg = {**cfg, "show_unplaced": False}
    first = chat_menu.view(tree, cfg, "big", 1)
    assert first["pages"] == 3 and len(first["rows"]) == 10
    assert (
        first["rows"][-1]["id"] == "menu:big:p2"
        and first["rows"][-1]["title"] == "More"
    )
    second = chat_menu.view(tree, cfg, "big", 2)
    assert (
        second["rows"][0]["id"] == "f09" and second["rows"][-1]["id"] == "menu:big:p3"
    )
    last = chat_menu.view(tree, cfg, "big", 3)
    assert [r["id"] for r in last["rows"]] == ["f18", "f19"]
    ids = [
        r["id"]
        for p in (first, second, last)
        for r in p["rows"]
        if not r["id"].startswith("menu:")
    ]
    assert ids == [f"f{i:02d}" for i in range(20)]  # every flow once, in order
    assert (
        chat_menu.view(tree, cfg, "big", 99)["page"] == 3
    )  # past the end: the last page


def test_a_group_inside_a_use_case_leaves_room_for_the_back_row():
    flows_ = [wf(f"f{i:02d}", f"Flow {i:02d}") for i in range(10)]
    cfg = {
        "show_unplaced": False,
        "nodes": [
            {
                "id": "a",
                "label": "A",
                "children": [
                    {
                        "id": "g",
                        "label": "G",
                        "children": [{"flow": w["intent_key"]} for w in flows_],
                    }
                ],
            },
            {"id": "b", "label": "B", "children": [{"flow": "f00x"}]},
        ],
    }
    tree = chat_menu.resolve(cfg, flows_ + [wf("f00x", "X")])
    v = chat_menu.view(tree, cfg, "g")
    assert (
        len(v["rows"]) == 10 and v["rows"][-1]["title"] == "Back"
    )  # 8 flows, More, Back
    assert v["pages"] == 2


def test_the_words_of_the_menu_are_the_organisations_own_with_built_in_defaults():
    assert chat_menu.words(None) == chat_menu.DEFAULT_WORDS
    mine = chat_menu.words({"back_label": "Go back", "button_label": "x" * 40})
    assert mine["back_label"] == "Go back" and len(mine["button_label"]) == 20


def test_a_tap_is_read_into_a_group_and_a_page():
    assert chat_menu.parse("menu:tickets") == ("tickets", 1)
    assert chat_menu.parse("menu:tickets:p3") == ("tickets", 3)
    assert chat_menu.parse("menu:") == ("", 1) and chat_menu.parse("menu::p2") == (
        "",
        2,
    )
    assert chat_menu.parse("menu:_other") == ("_other", 1)
    for bad in ("view_all_cases", "menu:A B", "menu:x:y", "menu:x:p2:p3", "", None):
        assert chat_menu.parse(bad) is None


# ------------------------------------------------------------ reading it for a person


def fake_world(monkeypatch, settings, allowed=ALL):
    async def org_settings(source_key, org_id):
        return settings

    async def get_menu_workflows(org_id, user):
        return [dict(w) for w in allowed]

    monkeypatch.setattr(config_store, "org_settings", org_settings)
    monkeypatch.setattr(menu, "get_menu_workflows", get_menu_workflows)


def test_without_a_saved_menu_everything_says_not_set(monkeypatch):
    fake_world(monkeypatch, {})
    assert run(chat_menu.sections_for(USER)) is None
    assert run(chat_menu.open_view(USER, "menu:tickets")) is None
    assert run(chat_menu.flow_data(USER, {})) is None


def test_the_flat_menu_is_unchanged_without_a_saved_menu(monkeypatch):
    fake_world(monkeypatch, {})
    got = run(menu.build_menu_sections("o1", USER))
    assert [s["title"] for s in got] == ["📊 Reports", "✍️ Create", "⚙️ More"]
    assert [r["id"] for r in got[0]["rows"]] == ["my_cases", "view_all_cases"]


def test_with_a_saved_menu_the_list_menu_is_the_use_cases(monkeypatch):
    fake_world(monkeypatch, {"chat_menu": TREE})
    got = run(menu.build_menu_sections("o1", USER))
    assert len(got) == 1
    assert [r["title"] for r in got[0]["rows"]] == ["Tickets", "Bookings", "More"]


def test_a_menu_that_breaks_while_building_leaves_the_flat_menu(monkeypatch):
    fake_world(monkeypatch, {"chat_menu": TREE})

    def boom(*a, **k):
        raise RuntimeError("broken")

    monkeypatch.setattr(chat_menu, "resolve", boom)
    got = run(menu.build_menu_sections("o1", USER))
    assert [s["title"] for s in got] == ["📊 Reports", "✍️ Create", "⚙️ More"]


def test_a_tap_on_a_group_gives_its_list_and_a_gone_group_gives_the_top(monkeypatch):
    fake_world(monkeypatch, {"chat_menu": TREE})
    got = run(chat_menu.open_view(USER, "menu:tickets"))
    assert got["body"] == "Complaints and cases" and got["button"] == "Choose"
    assert [r["id"] for r in got["sections"][0]["rows"]][:2] == [
        "menu:raise",
        "my_cases",
    ]
    top = run(chat_menu.open_view(USER, "menu:long_gone"))
    assert top["sections"][0]["rows"][0]["id"] == "menu:tickets"
    assert run(chat_menu.open_view(USER, "my_cases")) is None


def test_a_persons_role_limits_the_list_they_get_when_they_tap(monkeypatch):
    fake_world(monkeypatch, {"chat_menu": TREE}, allowed=[ALL[1]])
    got = run(chat_menu.open_view(USER, "menu:tickets"))
    # the only use case left is the top of the menu itself, so there is no Back to the same list
    assert [r["id"] for r in got["sections"][0]["rows"]] == ["my_cases"]
    gone = run(
        chat_menu.open_view(USER, "menu:bookings")
    )  # nothing there for them: the top, which is Tickets alone
    assert [r["id"] for r in gone["sections"][0]["rows"]] == ["my_cases"]


# ------------------------------------------------------------ the WhatsApp panel


def test_the_panel_data_is_the_tree_nested_with_a_workflow_at_every_end():
    screen, data = chat_menu.flow_data_for(tree_of())
    assert screen == "MENU"
    tickets = data["items"][0]
    assert tickets["on-click-action"]["next"]["name"] == "SECTION"
    inner = tickets["on-click-action"]["payload"]["items"]
    assert inner[0]["on-click-action"]["next"]["name"] == "SUBSECTION"
    assert inner[0]["on-click-action"]["payload"]["items"][0]["on-click-action"] == {
        "name": "navigate",
        "next": {"type": "screen", "name": "DONE"},
        "payload": {"workflow": "file_a_complaint"},
    }
    assert inner[1]["on-click-action"]["payload"] == {"workflow": "my_cases"}
    assert len(tickets["main-content"]["title"]) <= 30


def test_a_lone_use_case_opens_the_panel_on_its_list_and_nothing_gives_the_list_menu():
    cfg = {**TREE, "show_unplaced": False}
    lone = chat_menu.resolve(cfg, ALL[3:4])
    assert chat_menu.flow_data_for(lone)[0] == "SECTION"
    assert chat_menu.flow_data_for([]) == ("", {})


def test_a_panel_too_big_for_whatsapp_falls_back_to_the_list_menu(monkeypatch):
    monkeypatch.setattr(chat_menu, "FLOW_DATA_MAX_BYTES", 200)
    assert chat_menu.flow_data_for(tree_of()) == ("", {})


def test_the_panel_is_used_for_the_menu_when_one_is_saved(monkeypatch):
    fake_world(monkeypatch, {"chat_menu": TREE})
    screen, data = run(flows.menu_data(USER, {"chat_menu": TREE}))
    assert screen == "MENU" and data["items"][0]["id"] == "tickets"
    # a person whose role allows nothing gets the list menu (None)
    fake_world(monkeypatch, {"chat_menu": TREE}, allowed=[])
    assert run(flows.menu_data(USER, {"chat_menu": TREE})) is None


def test_without_a_saved_menu_the_panel_is_made_exactly_as_before(monkeypatch):
    fake_world(monkeypatch, {})
    with_none = run(flows.menu_data(USER, {}))
    without = run(flows.menu_data(USER))
    assert with_none == without and with_none[0] == "MENU"
    assert [i["id"] for i in with_none[1]["items"]] == ["reports", "create", "other"]


def test_the_layout_is_made_from_the_tree_and_is_ready_for_meta():
    layout = chat_menu.flow_layout(TREE, ALL)
    assert [s["id"] for s in layout["screens"]] == [
        "MENU",
        "SECTION",
        "SUBSECTION",
        "DONE",
    ]
    last = layout["screens"][-1]
    assert last["terminal"] is True
    assert last["layout"]["children"][-1]["on-click-action"]["payload"] == {
        "workflow": "${data.workflow}"
    }
    for s in layout["screens"][:-1]:
        assert s["layout"]["children"][0]["list-items"] == "${data.items}"
        assert s["data"]["items"]["__example__"]
    two = {**TREE, "nodes": [{**TREE["nodes"][1]}], "show_unplaced": False}
    assert [s["id"] for s in chat_menu.flow_layout(two, ALL)["screens"]] == [
        "SECTION",
        "DONE",
    ]
    flat = {
        "nodes": [
            {"id": "a", "label": "A", "children": [{"flow": "my_cases"}]},
            {"id": "b", "label": "B", "children": [{"flow": "lost_property"}]},
        ],
        "show_unplaced": False,
    }
    assert [s["id"] for s in chat_menu.flow_layout(flat, ALL)["screens"]] == [
        "MENU",
        "SECTION",
        "DONE",
    ]
    json.dumps(layout)  # plain JSON all through


def test_a_menu_shown_only_to_some_roles_leaves_everyone_else_with_todays_menu(
    monkeypatch,
):
    fake_world(monkeypatch, {"chat_menu": {**TREE, "only_roles": ["admin"]}})
    admin, committee = {**USER, "role": "admin"}, {**USER, "role": "committee"}
    got = run(menu.build_menu_sections("o1", admin))
    assert [r["title"] for r in got[0]["rows"]] == ["Tickets", "Bookings", "More"]
    flat = run(menu.build_menu_sections("o1", committee))
    assert [s["title"] for s in flat] == ["📊 Reports", "✍️ Create", "⚙️ More"]
    assert (
        run(
            chat_menu.flow_data(
                committee, {"chat_menu": {**TREE, "only_roles": ["admin"]}}
            )
        )
        is None
    )
    assert chat_menu.clean({**TREE, "only_roles": [" admin ", "admin"]})[
        "only_roles"
    ] == ["admin"]
    assert "only_roles" not in chat_menu.clean(TREE)
    with pytest.raises(ValueError):
        chat_menu.clean({**TREE, "only_roles": "admin"})
