"""The WhatsApp forms Questions builder (app/admin_panel/ui/js_whatsapp_builder.py): the plain-words editor that writes the Flow JSON.

The builder's functions run in Node against the page script (tests/js_page.py). Needs node; the tests are skipped without it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.admin_panel.ui import APP_JS, js_whatsapp_builder, js_whatsapp_templates
from app.services import flow_admin
from tests.js_page import run_page

ROOT = Path(__file__).resolve().parents[1]
COMPLAINT = json.loads(
    (ROOT / "docs" / "design" / "whatsapp-complaint-form-flow.json").read_text(
        encoding="utf-8"
    )
)


def go(code: str, **given) -> dict:
    prelude = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in given.items())
    return run_page(prelude + code, js_whatsapp_builder, js_whatsapp_templates)


def test_the_page_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    path = tmp_path / "app.js"
    path.write_text(APP_JS, encoding="utf-8")
    done = subprocess.run(
        [node, "--check", str(path)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]


def test_the_builder_knows_every_component_of_the_complaint_form_and_says_nothing_is_odd():
    got = go(
        "const f = COMPLAINT; return { kinds: f.screens[0].layout.children.map(wfbKindOf), report: wfbReport(f) };",
        COMPLAINT=COMPLAINT,
    )
    assert got["kinds"] == ["short", "long", "dropdown", "single", "photo", None]
    assert got["report"] == {
        "ok": True,
        "notes": [],
    }  # the Footer is the button, not a question


def test_a_question_added_is_in_the_button_s_answers_and_taken_out_again():
    got = go(
        """
        const f = JSON.parse(JSON.stringify(SAMPLE));
        const n = wfbAdd(f, 0, 'dropdown', 'Which tower');
        const afterAdd = JSON.parse(JSON.stringify(f));
        wfbRemove(f, 0, f.screens[0].layout.children.indexOf(n));
        return { name: n.name, afterAdd, afterRemove: f, kinds: afterAdd.screens[0].layout.children.map(c => c.type) };
        """,
        SAMPLE=flow_admin.SAMPLE,
    )
    assert got["name"] == "which_tower"
    first, thanks = got["afterAdd"]["screens"]
    assert first["layout"]["children"][-2]["type"] == "Dropdown"  # before the button
    assert first["layout"]["children"][-1]["type"] == "Footer"
    assert (
        first["layout"]["children"][-1]["on-click-action"]["payload"]["which_tower"]
        == "${form.which_tower}"
    )
    assert (
        thanks["data"]["which_tower"]["type"] == "string"
    )  # the next screen is told about it
    assert (
        thanks["layout"]["children"][-1]["on-click-action"]["payload"]["which_tower"]
        == "${data.which_tower}"
    )
    assert (
        got["afterRemove"] == flow_admin.SAMPLE
    )  # and out again, leaving nothing behind


def test_questions_move_rename_and_change_kind_and_keep_the_payload_right():
    got = go(
        """
        const f = JSON.parse(JSON.stringify(SAMPLE));
        const kids = f.screens[0].layout.children;
        const moved = wfbMove(f, 0, 2, -1);                                   // Your name is index 2: up past the intro
        const edge = wfbMove(f, 0, 0, -1), footerEdge = wfbMove(f, 0, kids.length - 2, 1);
        const node = kids.find(c => c.name === 'full_name');
        const renamed = wfbRenameAnswer(f, 0, node, 'Your Full Name');
        const clash = wfbRenameAnswer(f, 0, node, 'colour');
        wfbChangeKind(node, 'email');
        wfbSetRequired(node, false);
        wfbSetHelp(node, 'We never share it');
        return { moved, edge, footerEdge, renamed, clash, node, order: kids.map(c => c.name || c.type),
                 pay: kids[kids.length - 1]['on-click-action'].payload, thanks: f.screens[1] };
        """,
        SAMPLE=flow_admin.SAMPLE,
    )
    assert got["moved"] and not got["edge"] and not got["footerEdge"]
    assert got["renamed"] and not got["clash"]
    assert got["node"]["name"] == "your_full_name"
    assert got["node"]["type"] == "TextInput" and got["node"]["input-type"] == "email"
    assert (
        got["node"]["required"] is False
        and got["node"]["helper-text"] == "We never share it"
    )
    assert (
        "full_name" not in got["pay"]
        and got["pay"]["your_full_name"] == "${form.your_full_name}"
    )
    assert (
        "full_name" not in got["thanks"]["data"]
        and "your_full_name" in got["thanks"]["data"]
    )


def test_choices_keep_the_id_of_a_choice_whose_words_did_not_change():
    got = go(
        """
        const n = { type: 'Dropdown', name: 'c', label: 'C', 'data-source': [{ id: 'r', title: 'Red' }, { id: 'g', title: 'Green' }] };
        wfbSetChoices(n, 'Green\\nBlue\\n\\n Red ');
        return { src: n['data-source'], text: wfbChoicesText(n) };
        """
    )
    assert got["src"] == [
        {"id": "g", "title": "Green"},
        {"id": "blue", "title": "Blue"},
        {"id": "r", "title": "Red"},
    ]
    assert got["text"] == "Green\nBlue\nRed"


def test_a_photo_question_is_required_by_its_minimum():
    got = go(
        """
        const f = JSON.parse(JSON.stringify(COMPLAINT));
        const p = f.screens[0].layout.children.find(c => c.type === 'PhotoPicker');
        const before = wfbIsRequired(p);
        wfbSetRequired(p, true); const on = wfbIsRequired(p), min = p['min-uploaded-photos'];
        wfbSetRequired(p, false);
        return { before, on, min, off: wfbIsRequired(p) };
        """,
        COMPLAINT=COMPLAINT,
    )
    assert got == {"before": False, "on": True, "min": 1, "off": False}


def test_what_the_builder_does_not_understand_is_named_and_left_exactly_as_it_was():
    odd = json.loads(json.dumps(COMPLAINT))
    odd["screens"][0]["layout"]["children"].insert(
        1, {"type": "If", "condition": "${form.location} == 'x'", "then": []}
    )
    odd["screens"][0]["layout"]["children"][0]["visible"] = (
        True  # a setting it does not show
    )
    odd["screens"].append(
        {"id": "WEIRD", "title": "Odd", "layout": {"type": "Other", "children": []}}
    )
    got = go(
        """
        const f = JSON.parse(JSON.stringify(ODD));
        const report = wfbReport(f);
        wfbAdd(f, 0, 'short', 'Extra');
        return { report, f };
        """,
        ODD=odd,
    )
    notes = " ".join(got["report"]["notes"])
    assert "does not understand (If)" in notes and "stays exactly as it is" in notes
    assert "“Odd”" in notes and "cannot change" in notes
    kids = got["f"]["screens"][0]["layout"]["children"]
    assert kids[1] == odd["screens"][0]["layout"]["children"][1]  # the If is untouched
    assert kids[0]["visible"] is True  # and so is the setting
    assert got["f"]["screens"][1] == odd["screens"][1]


def test_screens_are_added_and_removed_and_the_form_still_ends_correctly():
    got = go(
        """
        const f = JSON.parse(JSON.stringify(BLANK));
        wfbAdd(f, 0, 'short', 'Your name');
        const second = wfbAddScreen(f, 'Check it');
        const afterAdd = JSON.parse(JSON.stringify(f));
        const refused = wfbRemoveScreen(JSON.parse(JSON.stringify(BLANK)), 0);
        const ok = wfbRemoveScreen(f, 1);
        return { id: second.id, afterAdd, ok, refused, after: f };
        """,
        BLANK=flow_admin.BLANK,
    )
    first, second = got["afterAdd"]["screens"]
    assert got["id"] == "CHECK_IT" and second["id"] == "CHECK_IT"
    foot = first["layout"]["children"][-1]
    assert (
        foot["on-click-action"]["name"] == "navigate"
        and foot["on-click-action"]["next"]["name"] == "CHECK_IT"
    )
    assert "terminal" not in first and second["terminal"] is True
    assert second["data"]["your_name"]["type"] == "string"
    assert second["layout"]["children"][-1]["on-click-action"] == {
        "name": "complete",
        "payload": {"your_name": "${data.your_name}"},
    }
    assert got["refused"] is False and got["ok"] is True
    last = got["after"]["screens"][0]
    assert last["terminal"] is True and last["success"] is True
    assert last["layout"]["children"][-1]["on-click-action"] == {
        "name": "complete",
        "payload": {"your_name": "${form.your_name}"},
    }


def test_screen_ids_use_letters_and_underscores_only():
    got = go(
        """
        const f = { screens: [{ id: 'SCREEN' }, { id: 'SCREEN_A' }] };
        return [wfbScreenId(f, 'Screen 2'), wfbScreenId(f, 'Tower & flat'), wfbScreenId({ screens: [] }, '123')];
        """
    )
    assert got == ["SCREEN_B", "TOWER_FLAT", "SCREEN"]


def test_the_builder_draws_a_card_for_each_question_and_writes_changes_back():
    got = go(
        """
        const flow = JSON.parse(JSON.stringify(COMPLAINT));
        let text = JSON.stringify(flow);
        const io = { flow: () => JSON.parse(text), apply: (fn, redraw) => { const f = JSON.parse(text); fn(f); text = JSON.stringify(f); if (redraw) wfbDraw(box, io); } };
        const box = h('div');
        wfbDraw(box, io);
        const cards = box.querySelectorAll('.wfb-q').length;
        const selects = box.querySelectorAll('select').length;
        io.apply(f => wfbAdd(f, 0, 'date', 'Visit date'), true);
        const after = box.querySelectorAll('.wfb-q').length;
        const mistaken = h('div'); wfbDraw(mistaken, { flow: () => null, apply() {} });
        return { cards, selects, after, saved: JSON.parse(text).screens[0].layout.children.map(c => c.name || c.type), warn: mistaken.textContent };
        """,
        COMPLAINT=COMPLAINT,
    )
    assert got["cards"] == 5 and got["after"] == 6
    assert "visit_date" in got["saved"]
    assert "mistake" in got["warn"]


def test_the_template_preview_helpers_fill_blanks_with_their_examples():
    got = go(
        """
        return { n: tplBlanks('Hi {{1}}, {{ 2 }} and {{1}}'), t: tplFill('Hi {{1}}, ticket {{2}}', ['Asha']),
                 s: tplSlug('Ticket Update!'), st: tplStatus({ status: 'PENDING' }), bad: tplStatus({ status: 'REJECTED' })[1] };
        """
    )
    assert got["n"] == [1, 2, 1]
    assert got["t"] == "Hi Asha, ticket {{2}}"
    assert (
        got["s"] == "ticket_update"
        and got["st"] == ["Waiting for Meta", "warn"]
        and got["bad"] == "bad"
    )


def test_the_bubble_preview_shows_header_body_footer_and_buttons():
    got = go(
        """
        const b = tplBubble({ category: 'UTILITY', header: { text: 'Update {{1}}', example: 'CS-12' }, body: 'Hello {{1}}', examples: ['Asha'],
                              footer: 'Thanks', buttons: [{ kind: 'url', text: 'Track' }, { kind: 'quick_reply', text: 'Got it' }] });
        const a = tplBubble({ category: 'AUTHENTICATION', body: '' });
        return { text: b.textContent, auth: a.textContent };
        """
    )
    for part in ["Update CS-12", "Hello Asha", "Thanks", "Track", "Got it"]:
        assert part in got["text"]
    assert "verification code" in got["auth"] and "Copy code" in got["auth"]


def test_the_screens_say_chat_bot_and_never_assistant():
    for js in (js_whatsapp_builder.JS, js_whatsapp_templates.JS):
        assert "assistant" not in js.lower()
    assert "renderWhatsappTemplates" in APP_JS and "wfbDraw(builderBox" in APP_JS
