"""Group A of the dashboard's UI/UX fixes (UX-001, 004, 005, 006, 007, 009, 021, 028, 035): every label tied to its
box and every switch named, messages that are announced and stay long enough, the words kept when the menu is narrow,
text colours that can be read, a skip link, a message with Undo when a flow is switched on or off, the organisation's
own word for a stored value, and plain words under a flow step."""

import asyncio
import colorsys
import json
import re
from pathlib import Path

import asyncpg
import pytest

from app.admin_panel import meta
from app.admin_panel.ui import APP_CSS, APP_JS, css, js_canvas, js_studio_form
from tests.js_page import run_page
from tests.test_migrate import needs_pg

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def _grab(source: str, header: str) -> str:
    """One top-level function of a page module, cut out of its source."""
    start = source.index(header)
    return source[start : source.index("\n}\n", start) + 3]


# ------------------------------------------------------------ A1: labels tied to their boxes, switches with a name


def test_a_label_is_tied_to_its_box_and_the_hint_is_read_with_it():
    got = run_page(
        r"""
        const box = h('input', { type: 'text' });
        const f = field('Email', box, 'We never share it');
        const second = h('input', { type: 'text' });
        const g = field('Name', second);
        return { for: f.childNodes[0].getAttribute('for'), id: box.id, described: box.getAttribute('aria-describedby'),
                 hintId: f.childNodes[2].id, other: second.id, noHint: g.childNodes.length };
        """
    )
    assert got["for"] == got["id"] != ""
    assert got["described"] == got["hintId"] != ""
    assert got["other"] not in ("", got["id"])  # every box has its own id
    assert got["noHint"] == 2  # label and box; no empty hint left behind


def test_a_label_finds_the_box_inside_a_wrapper_and_keeps_an_id_it_already_has():
    got = run_page(
        r"""
        const inner = h('input', { type: 'search', id: 'mine' });
        const wrap = h('div', null, h('span', null, 'chosen'), inner);
        const f = field('Person', wrap);
        const none = field('Nothing to tie', h('div', null, 'text only'));
        return { for: f.childNodes[0].getAttribute('for'), id: inner.id, noBox: none.childNodes[0].getAttribute('for') };
        """
    )
    assert got["for"] == got["id"] == "mine"
    assert got["noBox"] is None  # nothing to tie to: no broken "for"


def test_every_switch_has_a_name_and_says_it_is_a_switch():
    got = run_page(
        r"""
        const withName = switchEl(true, () => {}, false, 'File a complaint');
        const plain = switchEl(false, () => {});
        const a = withName.querySelector('input'), b = plain.querySelector('input');
        return { role: a.getAttribute('role'), name: a.getAttribute('aria-label'), checked: a.checked,
                 type: a.getAttribute('type'), noName: b.getAttribute('aria-label') };
        """
    )
    assert got == {
        "role": "switch",
        "name": "File a complaint",
        "checked": True,
        "type": "checkbox",
        "noName": None,
    }


def test_the_page_names_the_boxes_it_used_to_leave_without_one():
    for label in [
        "'aria-label': 'Search flows'",
        "'aria-label': 'Search what was said'",
        "'aria-label': 'From date'",
        "'aria-label': 'To date'",
        "'aria-label': 'Kind of complaint'",
        "'aria-label': 'Add data the chat bot may look up'",
        "'aria-label': 'Can approve things'",
        "'aria-label': 'Choose a logo image'",
        "'aria-label': 'Role'",
        "'aria-label': 'Kind of resident'",
        "'aria-label': 'Status of the home'",
    ]:
        assert label in APP_JS, label
    # the response-time table: each number says which priority and which time
    assert "pretty(r.priority) + ': target in minutes'" in APP_JS
    assert "pretty(r.priority) + ': remind after, in minutes'" in APP_JS


def test_a_flow_card_is_a_heading_with_a_link_and_a_named_switch_not_a_button_holding_a_button():
    assert "role: 'link', 'aria-label': 'Open ' + w.name" not in APP_JS
    assert (
        "h('h2', { class: 'fname' }, h('a', { href: '#/workflows?w=' + w.id }, w.name))"
        in APP_JS
    )
    assert (
        "const sw = switchEl(w.is_active, v => flip(v, false), false, w.name);"
        in APP_JS
    )


# ------------------------------------------------------------ A2: messages are announced, errors stay, Undo lasts


def test_messages_are_announced_errors_stay_until_closed_and_undo_lasts_fifteen_seconds():
    got = run_page(
        r"""
        const box = toastBox();
        toast('Saved', 'ok');
        toast('It broke', 'bad');
        toast('Deleted', 'ok', { label: 'Undo', run() {} });
        const kids = box.childNodes;
        return {
          region: { role: box.getAttribute('role'), live: box.getAttribute('aria-live') },
          plainRole: kids[0].getAttribute('role'),
          errorRole: kids[1].getAttribute('role'),
          errorClose: kids[1].querySelector('button').getAttribute('aria-label'),
          undoButton: kids[2].querySelector('.tact').textContent,
          waits: timers.map(t => t.ms),
        };
        """
    )
    assert got["region"] == {"role": "status", "live": "polite"}
    assert got["plainRole"] is None and got["errorRole"] == "alert"
    assert got["errorClose"] == "Close this message"
    assert got["undoButton"] == "Undo"
    # ordinary 3.5 s, Undo 15 s, and no timer at all for the error: it stays until it is closed
    assert got["waits"] == [3500, 15000]


def test_the_same_error_shows_once_and_only_the_last_four_errors_are_kept():
    got = run_page(
        r"""
        const box = toastBox();
        toast('Same', 'bad'); toast('Same', 'bad');
        const once = box.querySelectorAll('.toast.bad').length;
        for (const n of [1, 2, 3, 4, 5, 6]) toast('Error ' + n, 'bad');
        return { once, kept: box.querySelectorAll('.toast.bad').map(t => t.textContent.replace('×', '')) };
        """
    )
    assert got["once"] == 1
    assert got["kept"] == ["Error 3", "Error 4", "Error 5", "Error 6"]


def test_only_the_latest_undo_keeps_its_button_and_the_button_runs_its_action():
    got = run_page(
        r"""
        let ran = [];
        const box = toastBox();
        toast('First', 'ok', { label: 'Undo', run() { ran.push('first'); } });
        toast('Second', 'ok', { label: 'Undo', run() { ran.push('second'); } });
        const left = box.querySelectorAll('.toast.has-act').length;
        box.querySelector('.tact').click();
        return { left, ran, after: box.querySelectorAll('.toast').length };
        """
    )
    assert got == {"left": 1, "ran": ["second"], "after": 0}


def test_the_message_place_is_on_the_page_from_the_start():
    got = run_page(
        r"""
        return { early: !!document.querySelector('.toasts'), role: document.querySelector('.toasts').getAttribute('role') };
        """
    )
    assert got == {"early": True, "role": "status"}


# ------------------------------------------------------------ A3 and A5: the narrow menu keeps its words, a skip link


def test_the_words_of_a_narrow_menu_and_bar_are_hidden_by_eye_not_removed_for_screen_readers():
    hidden = "clip:rect(0,0,0,0)"
    for selector in [
        "body.rail .nav .tx,body.rail .sidefoot .tx{",
        ".zoomb .tx{",
        ".cvbar .tx,.zoomb .tx{",
        ".topbar .btn.primary .tx{",
        ".dock.min .dhd span{",
    ]:
        rule = APP_CSS[APP_CSS.index(selector) :].split("}", 1)[0]
        assert hidden in rule and "display:none" not in rule, selector
    # the rule that does take things out with display:none no longer holds the words of any button
    taken_out = APP_CSS[APP_CSS.index("body.rail .sbrand b,") :].split("}", 1)[0]
    assert "display:none" in taken_out and ".tx" not in taken_out
    assert (
        "'aria-label': a.label" in APP_JS
    )  # the main button of a screen is named even when its words are hidden


def test_a_skip_link_is_the_first_thing_in_the_page_and_moves_the_focus_without_changing_the_address():
    assert "h('a', { class: 'skip', href: '#main'" in APP_JS
    assert "'Skip to main content'" in APP_JS
    assert "fill(app, skip, h('div', { class: 'app' }" in APP_JS  # before the menu
    assert "h('main', { class: 'main', id: 'main', tabindex: -1 })" in APP_JS
    assert (
        "e.preventDefault(); const m = document.getElementById('main'); m.focus();"
        in APP_JS
    )
    assert ".skip:focus{top:12px" in APP_CSS and ".main:focus{outline:none}" in APP_CSS


# ------------------------------------------------------------ A4: colours that can be read


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb) -> float:
    def part(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (part(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _mix(a, b, share):
    return tuple(a[i] * share + b[i] * (1 - share) for i in range(3))


def _tokens(block: str) -> dict[str, tuple[int, int, int]]:
    return {
        k: _hex(v) for k, v in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block)
    }


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_colours_reach_4_5_to_1_on_every_background_and_on_their_own_badge(theme):
    t = _tokens(css._LIGHT if theme == "light" else css._DARK)
    backgrounds = [t[k] for k in ("bg", "surface", "surface-2", "sunken")]
    for background in backgrounds:
        assert _ratio(t["muted"], background) >= 4.5, ("muted", background)
        assert _ratio(t["ink-2"], background) >= 4.5
    # a badge is its colour on a 13% tint of itself over the surface (or the sunken panel)
    for tone, base in [
        ("ok", "ok"),
        ("warn", "warn"),
        ("bad", "bad"),
        ("violet", "k-ai"),
        ("teal", "k-block"),
        ("pink", "k-approve"),
        ("orange", "k-tell"),
    ]:
        ink = t[f"t-{tone}"]
        for background in (t["surface"], t["sunken"]):
            assert _ratio(ink, _mix(t[base], background, 0.13)) >= 4.5, (theme, tone)
        assert _ratio(ink, t["surface"]) >= 4.5, (theme, tone)
    # the plain grey badge
    for background in (t["surface"], t["sunken"]):
        assert _ratio(t["t-muted"], _mix(t["t-muted"], background, 0.13)) >= 4.5, (
            theme,
            "muted badge",
        )
    # the text on a solid red or green disc (the menu's count, the "!" on a step, a message)
    assert _ratio(t["on-bad"], t["bad"]) >= 4.5 and _ratio(t["on-ok"], t["ok"]) >= 4.5
    # the brand colour as text and as a button
    assert (
        _ratio(t["brand"], t["surface"]) >= 4.5
        and _ratio(t["on-brand"], t["brand"]) >= 4.5
    )


def test_the_letters_in_an_avatar_can_be_read_on_every_colour_it_can_have():
    lightness = int(re.search(r"'hsl\(' \+ hue \+ ',45%,(\d+)%\)'", APP_JS).group(1))
    worst = min(
        _ratio(
            (255, 255, 255),
            tuple(
                round(v * 255)
                for v in colorsys.hls_to_rgb(hue / 360, lightness / 100, 0.45)
            ),
        )
        for hue in range(360)
    )
    assert worst >= 4.5, (lightness, worst)


def test_text_is_never_drawn_in_the_pale_colour_meant_for_lines_and_icons():
    for rule in [
        ".navlabel{",
        ".crumbs .sep{",
        ".faint{",
    ]:
        assert "var(--faint)" not in APP_CSS[APP_CSS.index(rule) :].split("}", 1)[0], (
            rule
        )
    assert (
        "'aria-hidden': 'true' }, '/')" in APP_JS
    )  # the slash between breadcrumbs is decoration


# ------------------------------------------------------------ A6: switching a flow on or off says what changes


def test_switching_a_flow_off_says_what_people_can_no_longer_do():
    got = run_page(
        r"""
        const w = { name: 'Visitor pass', slash_command: 'visitor', kind: 'workflow' };
        const noCommand = { name: 'File a complaint', kind: 'workflow' };
        const button = { name: 'Close the case', kind: 'case_action' };
        return {
          off: switchNote(w, false), on: switchNote(w, true),
          offNoCommand: switchNote(noCommand, false), onNoCommand: switchNote(noCommand, true),
          offButton: switchNote(button, false),
        };
        """
    )
    assert (
        got["off"] == "Switched off “Visitor pass”. People can no longer use /visitor."
    )
    assert got["on"] == "Switched on “Visitor pass”. People can use /visitor again."
    assert (
        got["offNoCommand"]
        == "Switched off “File a complaint”. People can no longer use it in the chat."
    )
    assert (
        got["onNoCommand"]
        == "Switched on “File a complaint”. People can use it in the chat again."
    )
    assert (
        got["offButton"]
        == "Switched off “Close the case”. People can no longer use its button on a case."
    )


def test_switching_a_building_block_off_says_how_many_flows_will_stop():
    got = run_page(
        r"""
        const block = n => ({ name: 'Find a case', kind: 'block', used_in: Array.from({ length: n }, (_, i) => ({ name: 'F' + i })) });
        return { none: switchNote(block(0), false), one: switchNote(block(1), false), many: switchNote(block(3), false), on: switchNote(block(3), true) };
        """
    )
    assert got["none"] == "Switched off “Find a case”. No flow uses it yet."
    assert (
        got["one"]
        == "Switched off “Find a case”. 1 flow that uses it will stop at that step."
    )
    assert (
        got["many"]
        == "Switched off “Find a case”. 3 flows that use it will stop at that step."
    )
    assert (
        got["on"]
        == "Switched on “Find a case”. The flows that use it can run it again."
    )


def test_the_flow_list_and_the_editor_both_show_the_message_with_an_undo_that_puts_it_back():
    assert (
        "toast(switchNote(w, v), 'ok', undone ? null : { label: 'Undo', run: () => flip(!v, true)"
        in APP_JS
    )
    assert (
        "toast(switchNote({ ...EW.work, name: flowName, used_in: d.used_in }, v), 'ok', undone ? null"
        in APP_JS
    )
    assert (
        "flowSwitch.querySelector('input').checked = v;" in APP_JS
    )  # the switch in the editor follows the undo


# ------------------------------------------------------------ A7: the organisation's own word for a stored value


def test_a_stored_value_is_shown_in_the_organisations_word_or_made_readable():
    got = run_page(
        r"""
        const before = pretty('not_residing');
        Object.assign(VALUE_LABELS, { not_residing: 'Moved out' });
        return { before, after: pretty('not_residing'), other: pretty('first_owner'), empty: pretty(''), none: pretty(null),
                 builtIn: pretty('constructor'), proto: pretty('__proto__'), toString: pretty('toString') };
        """
    )
    assert got["before"] == "Not residing"
    assert got["after"] == "Moved out"
    assert got["other"] == "First owner" and got["empty"] == "" and got["none"] == ""
    # words that happen to be names of built-in object parts are never mistaken for the organisation's words
    assert got["builtIn"] == "Constructor" and got["toString"] == "ToString"
    assert isinstance(got["proto"], str)


def test_the_page_loads_the_organisations_words_with_its_start_up_data():
    assert "Object.assign(VALUE_LABELS, S.boot.labels || {});" in APP_JS


def _labels_of(monkeypatch, settings, fails=False):
    async def fetch_one(sql, *args, source_key):
        if fails:
            raise RuntimeError("no settings column")
        return None if settings is None else {"settings": settings}

    monkeypatch.setattr(meta, "fetch_one", fetch_one)
    ctx = type("Ctx", (), {"org_id": "x", "source_key": "alpha"})()
    return asyncio.run(meta._labels(ctx))


def test_the_start_up_data_carries_the_words_the_organisation_chose(monkeypatch):
    assert _labels_of(monkeypatch, {"labels": {"not_residing": "Moved out"}}) == {
        "not_residing": "Moved out"
    }
    assert _labels_of(monkeypatch, '{"labels": {"a": " Yes "}}') == {
        "a": "Yes"
    }  # text from the database


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {},
        {"labels": None},
        {"labels": ["not_residing"]},
        {"labels": "Moved out"},
        "not json at all",
        {"labels": {"a": 5, "b": None, "c": "", "d": "   ", "e": "x" * 81}},
    ],
)
def test_a_missing_or_odd_setting_gives_no_words_and_never_an_error(
    monkeypatch, settings
):
    assert _labels_of(monkeypatch, settings) == {}


def test_a_database_without_settings_still_starts_the_dashboard(monkeypatch):
    assert _labels_of(monkeypatch, None, fails=True) == {}


@needs_pg
def test_the_housing_word_is_added_once_and_never_overwrites_a_word_someone_chose(
    world,
):
    sql = (
        MIGRATIONS / "features" / "housing" / "housing-0006_status_labels.sql"
    ).read_text(encoding="utf-8")

    async def scenario():
        conn = await asyncpg.connect(world.dsn["alpha"])
        try:
            await conn.execute(
                "CREATE TABLE public.orgs (id serial PRIMARY KEY, settings jsonb)"
            )
            await conn.execute(
                "INSERT INTO public.orgs (settings) VALUES "
                "(NULL), ('{}'), "
                """('{"labels": {"not_residing": "Left", "x": "y"}}'), """
                """('{"labels": {"x": "y"}, "keep": 1}')"""
            )
            await conn.execute(sql)
            first = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT settings FROM public.orgs ORDER BY id"
                )
            ]
            await conn.execute(sql)  # again: nothing changes
            second = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT settings FROM public.orgs ORDER BY id"
                )
            ]
            return first, second
        finally:
            await conn.close()

    first, second = asyncio.run(scenario())
    settings = [json.loads(r["settings"]) for r in first]
    assert settings[0] == {"labels": {"not_residing": "Moved out"}}
    assert settings[1] == {"labels": {"not_residing": "Moved out"}}
    assert settings[2] == {
        "labels": {"not_residing": "Left", "x": "y"}
    }  # their word is kept
    assert settings[3] == {"labels": {"x": "y", "not_residing": "Moved out"}, "keep": 1}
    assert first == second


# ------------------------------------------------------------ A10: plain words under a flow step


def _step_sub(step: dict) -> str:
    code = (
        _grab(js_canvas.JS, "function stepSub(s, f) {")
        + "\nconst S0 = "
        + json.dumps(step)
        + ";\nreturn { sub: stepSub(S0, { blk: false }) };"
    )
    return run_page(code, js_studio_form)["sub"]


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        # the generic records table is named by the kind of record, never by its own name
        (
            {"op": "db.insert_row", "params": {"table": "entity_records", "values": {"entity_type": "expense", "name": "$fields.vendor"}}},
            "expense records",
        ),
        ({"op": "db.insert_row", "params": {"table": "entity_records", "values": {"name": "x"}}}, "records"),
        (
            {"op": "resolve_entity", "params": {"table": "entity_records", "match_columns": {"entity_type": "visitor", "name": "$fields.n"}}},
            "visitor records · several columns",
        ),
        # who a message goes to
        ({"op": "notify.user", "params": {"to": "$user.user_id"}}, "to the person who asked"),
        ({"op": "notify.user", "params": {"to": "$user.phone"}}, "to the person who asked"),
        ({"op": "notify.user", "params": {"to": "$assignee.phone"}}, "to assignee"),
        ({"op": "notify.user", "params": {"to": "$requester.phone"}}, "to requester"),
        ({"op": "notify.user", "params": {"to": "$case.reporter_id"}}, "to reporter"),
        ({"op": "notify.user", "params": {"to": "$handler"}}, "to handler"),
        # a table written in capitals gets spaces
        ({"op": "resolve_entity", "params": {"table": "sheet:PurchaseOrders", "match_column": "name"}}, "purchase orders · by name"),
        # the ordinary tables read as before
        ({"op": "db.update_row", "params": {"table": "cases", "set": {"status": "closed"}}}, "cases · status"),
        # a column that links to something says what, not "id"
        ({"op": "db.update_row", "params": {"table": "cases", "set": {"assigned_to_id": "$x", "category_id": "$y"}}}, "cases · assigned to, category"),
        ({"op": "resolve_entity", "params": {"table": "users", "match_column": "user_id"}}, "users · by user"),
        ({"op": "db.update_row", "params": {"table": "cases", "set": {"valid": "yes"}}}, "cases · valid"),
    ],
)  # fmt: skip
def test_the_words_under_a_step_are_plain(step, expected):
    assert _step_sub(step) == expected


def test_the_title_of_a_step_on_the_generic_table_names_the_kind_too():
    got = run_page(
        r"""
        const s = { op: 'db.insert_row', params: { table: 'entity_records', values: { entity_type: 'expense', name: '$fields.vendor' } } };
        const u = { op: 'db.update_row', params: { table: 'entity_records', where: { entity_type: 'visitor' }, set: { status: 'in' } } };
        const ordinary = { op: 'db.insert_row', params: { table: 'cases', values: { title: '$fields.t' } } };
        return { insert: describeStep(s), update: describeStep(u), ordinary: describeStep(ordinary) };
        """,
        js_studio_form,
    )
    assert got["insert"].startswith("Save a new expense record:")
    assert got["update"].startswith("Change the visitor record:")
    assert got["ordinary"].startswith("Save a new case:")
