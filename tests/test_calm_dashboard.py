"""The calmer dashboard: two menu groups with nothing dead in them, one main button per screen,
one set of words, a roles editor, and old links that still lead somewhere."""

import json
import re
import shutil
import subprocess

import pytest

from app.admin_panel import meta
from app.admin_panel.ui import APP_CSS, APP_JS, js_home
from app.main import app
from app.services import step_catalog


def _routes():
    return {
        (r.path, m)
        for r in app.routes
        for m in getattr(r, "methods", None) or ()
        if m != "HEAD"
    }


# ------------------------------------------------------------ the menu and the frame


def test_the_menu_is_grouped_like_the_approved_prototype_and_has_nothing_that_is_not_there_yet():
    assert "['Your work', ['cases', 'conversations']]" in APP_JS
    assert "['Your team', ['people', 'access']]" in APP_JS
    assert "['Chat bot', ['assistant']]" in APP_JS
    assert "['Build', ['usecases', 'workflows', 'blocks']]" in APP_JS
    assert "NAV_SOON" not in APP_JS  # no greyed "Soon" items
    assert (
        "not active yet)" not in APP_JS
    )  # the tab no longer carries it; the note inside says so
    assert "'Soon'" not in APP_JS


def test_the_set_up_screens_are_told_apart_in_the_page_frame():
    assert (
        "const SETUP = new Set(['access', 'assistant', 'usecases', 'workflows', 'blocks', 'settings'])"
        in APP_JS
    )
    assert "sec.tabs.length > 1" in APP_JS  # a tab bar for one tab is not drawn
    assert "S.leaveGuard = null; window.onbeforeunload = null;" in APP_JS


def test_each_screen_has_one_main_button_in_the_top_bar_and_no_global_one():
    assert "New workflow / building block" not in APP_JS
    assert "function setTopAction" in APP_JS
    for label in ["Add person", "New role", "New rule", "New seat", "Give access"]:
        assert f"label: '{label}'" in APP_JS, label
    # Flows: the label follows the tab
    assert "'New building block' : 'New flow'" in APP_JS
    assert "id: 'topact'" in APP_JS


def test_the_words_are_explained_once_and_are_the_same_everywhere():
    for word in ["Flow", "Trigger", "Step", "Building block", "Role", "Seat"]:
        assert f"['{word}'," in APP_JS, word
    assert "Help & words" in APP_JS
    assert (
        "Reusable piece" not in APP_JS
    )  # the user's own word, "building block", stays
    assert "How a flow works" in APP_JS and "Learn the words" in APP_JS
    for old in [
        "New workflow",
        "A workflow people start",
        "Make your own node",
        "Where complaints go",
    ]:
        assert old not in APP_JS, old
    assert (
        step_catalog.STEP_TYPES
    )  # the step list says "Use a building block", not "Run"
    labels = {s["op"]: s["label"] for s in step_catalog.STEP_TYPES}
    assert labels["run_workflow"] == "Use a building block"


def test_what_is_not_built_yet_is_not_offered_in_the_step_list():
    # "On a schedule" is a way to START a flow now (the How does it start card), not a step
    for later in [
        "If / else branch",
        "Repeat for each",
        "Decide with the assistant",
    ]:
        assert later not in APP_JS, later
    assert "Make a new building block" in APP_JS


def test_a_step_has_its_own_menu_button_and_the_technical_view_is_tucked_away():
    assert "nd-more" in APP_JS and "nd-more" in APP_CSS
    assert "function moreMenu" in APP_JS
    assert "'Simple'" in APP_JS
    assert (
        "Double-click" in APP_JS and "panel.cvhint" in APP_JS
    )  # the first-time hint is said once


# ------------------------------------------------------------ the screens


def test_home_shows_what_needs_you_and_four_numbers():
    assert "needRow" in APP_JS and "smaller thing" in APP_JS
    assert (
        js_home.JS.count("kpiTile('") == 4
    )  # the Home screen's own four (the super admin page has its own)
    assert "Getting set up" in APP_JS and "setchip" in APP_CSS


def test_cases_is_search_open_closed_and_one_filters_button():
    assert "TICKET_TABS" in APP_JS  # the old Case rules live in the Tickets tabs
    assert "Filters · " in APP_JS
    housing = {"cases": True, "case_model": True, "targets": True}
    tickets = next(s for s in meta._sections(housing) if s["key"] == "cases")
    assert [t["label"] for t in tickets["tabs"]] == [
        "All tickets",
        "Who handles what",
        "Kinds of ticket",
        "Rules in detail",
        "Response times",
    ]


def test_people_can_be_added_and_roles_are_filters():
    assert "function addPersonModal" in APP_JS
    assert "api.post('/people'" in APP_JS
    assert "Manage roles" in APP_JS


def test_the_roles_editor_has_all_its_parts():
    for part in [
        "async function renderRoleEditor",
        "Start from",
        "Nothing, start empty",
        "What they can do",
        "What the chat bot may look up for them",
        "Largest amount they can approve",
        "Built in. ",
        "Delete role",
        "Create role",
    ]:
        assert part in APP_JS, part


def test_the_routes_for_the_editor_and_the_menu_numbers_exist():
    routes = _routes()
    for want in [
        ("/admin/{org_slug}/api/v2/roles", "GET"),
        ("/admin/{org_slug}/api/v2/roles", "POST"),
        ("/admin/{org_slug}/api/v2/roles/{role_id}", "PATCH"),
        ("/admin/{org_slug}/api/v2/roles/{role_id}", "DELETE"),
        ("/admin/{org_slug}/api/v2/people", "POST"),
        ("/admin/{org_slug}/api/v2/nav-hints", "GET"),
    ]:
        assert want in routes, want


def test_the_chat_bot_section_says_what_it_is():
    section = next(
        s
        for s in meta._sections({"texts": True, "prompts": True})
        if s["key"] == "assistant"
    )
    assert section["label"] == "Chat bot"
    assert [t["label"] for t in section["tabs"]] == ["Messages", "AI notes", "Menu"]
    assert [t["key"] for t in section["tabs"]] == [
        "messages",
        "instructions",
        "menu",
    ]  # old links work
    for part in [
        "Tell the chat bot about your place",
        "Advanced: the shared rules, the industry text and the reply style",
        "See everything the AI reads",
        "Clear notes",
        "Nothing written yet",
        "What the AI reads",
        "Words you can use: ",  # the reply style lists the names it fills in
        "Back to the standard text",
        "Back to standard wording",
    ]:
        assert part in APP_JS, part
    for old in ["Use built-in wording", "Use built-in text"]:
        assert old not in APP_JS, old  # the wording that is stored is called standard


def test_each_thing_has_one_name_chat_bot_ai_and_ai_helper():
    for word in ["Chat bot", "AI helper"]:
        assert f"['{word}'," in APP_JS, word  # said once, under Help & words
    assert "Assistant" not in APP_JS  # no screen is called that any more
    assert not re.search(r"\b(?:the|The|an|this) assistant\b", APP_JS)
    assert "The AI helper drafts it" in APP_JS
    assert "Ask the AI helper to change this flow" in APP_JS


# ------------------------------------------------------------ old links still lead somewhere


def _remap(r):
    """Run the page's own remapRoute() on a route (needs node; skipped where it is not installed)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    start = APP_JS.index("function remapRoute(r) {")
    end = APP_JS.index("\n}\n", start) + 3
    script = (
        APP_JS[start:end]
        + f"\nconsole.log(JSON.stringify(remapRoute({json.dumps(r)})));"
    )
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ({"section": "routing", "tab": "", "q": {}}, {"section": "cases", "tab": "teams"}),
        ({"section": "routing", "tab": "categories", "q": {}}, {"section": "cases", "tab": "categories"}),
        ({"section": "rules", "tab": "", "q": {}}, {"section": "cases", "tab": "teams"}),
        ({"section": "rules", "tab": "times", "q": {}}, {"section": "cases", "tab": "times"}),
        ({"section": "cases", "tab": "rules", "q": {}}, None),  # the Tickets tabs are where these live now
        ({"section": "cases", "tab": "categories", "q": {}}, None),
        ({"section": "cases", "tab": "times", "q": {}}, None),
        ({"section": "people", "tab": "seats", "q": {}}, {"section": "access", "tab": "seats"}),
        ({"section": "people", "tab": "access", "q": {}}, {"section": "access", "tab": "special"}),
        ({"section": "people", "tab": "roles", "q": {}}, {"section": "access", "tab": ""}),
        ({"section": "people", "tab": "people", "q": {}}, {"section": "people", "tab": ""}),
        ({"section": "activity", "tab": "chats", "q": {}}, {"section": "conversations", "tab": ""}),
        ({"section": "activity", "tab": "changes", "q": {}}, {"section": "settings", "tab": "history"}),
        ({"section": "activity", "tab": "", "q": {}}, {"section": "settings", "tab": "history"}),
    ],
)  # fmt: skip
def test_links_and_bookmarks_from_the_old_menu_still_work(old, new):
    got = _remap(old)
    if new is None:
        assert got is None
        return
    assert {k: got[k] for k in new} == new


@pytest.mark.parametrize(
    "route",
    [
        {"section": "cases", "tab": "", "q": {"status": "open"}},
        {"section": "people", "tab": "", "q": {"person": "x"}},
        {"section": "workflows", "tab": "", "q": {"w": "x"}},
        {"section": "settings", "tab": "history", "q": {}},
    ],
)
def test_current_addresses_are_left_alone(route):
    assert _remap(route) is None


def test_the_css_has_what_the_new_screens_use():
    for cls in [
        ".rl-grid",
        ".nr{",
        ".nf-start",
        ".hw-steps",
        ".navdot",
        ".cvhint",
        ".words",
    ]:
        assert cls in APP_CSS, cls
    assert re.search(r"\.seg button\[hidden\]\{display:none\}", APP_CSS)
