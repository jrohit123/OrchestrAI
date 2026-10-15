"""The Chat bot > Menu screen as a person uses it: add a use case, name it, put flows in it, move one, hide one, save. It runs in
Node against a small stand-in for the page and a fake server, and checks what the screen asks the server to save. Skipped where
node is not installed."""

import json
import shutil
import subprocess

import pytest

from app.admin_panel.ui import js_core, js_menu
from tests.js_page import STUB

PRELUDE = r"""
S.renderId = 1;
const roleLabel = n => n;
const errorBox = e => h('div', { class: 'err' }, e.message);
const calls = [];
const FLOWS = [
  { intent_key: 'file_a_complaint', name: 'File a complaint', command_description: 'Report a problem', menu_section: 'create', is_active: true },
  { intent_key: 'my_cases', name: 'My Open Tickets', command_description: '', menu_section: 'reports', is_active: true },
  { intent_key: 'old_flow', name: 'Old flow', command_description: '', menu_section: 'other', is_active: false },
];
const DATA = (cfg) => ({ configured: false, config: cfg, flows: FLOWS, roles: [{ id: 'r1', name: 'member' }],
  words: { other_label: 'More', back_label: 'Back', more_label: 'More', button_label: 'Choose' },
  word_max: { other_label: 24, back_label: 24, more_label: 24, button_label: 20 },
  limits: { use_cases: 10, entries: 20, label: 24, description: 72, rows_per_message: 10 } });
let start = { enabled: false, nodes: [], show_unplaced: true };
api.get = async p => DATA(JSON.parse(JSON.stringify(start)));
api.post = async (p, b) => { calls.push(['POST', p, b]); return p.endsWith('/suggest')
  ? { config: { enabled: false, show_unplaced: true, nodes: [{ id: 'create', label: 'Create', description: '', hidden: false, children: [{ flow: 'file_a_complaint', hidden: false }] }] } }
  : { screens: [], empty: true, flow_json: '{}', panel: { fits: false, bytes: 0, max_bytes: 30000 } }; };
api.put = async (p, b) => { calls.push(['PUT', p, b]); return { ok: true, config: b.config }; };
toast = () => {};
confirmBox = async () => true;
const settle = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
const byText = (root, t) => root.all().find(e => e.tagName === 'BUTTON' && e.textContent === t);
const fire = (el, type) => { for (const f of el.l[type] || []) f({ target: el, currentTarget: el }); };
const typeInto = (el, v) => { el.value = v; fire(el, 'input'); };
const choose = (el, v) => { el.value = v; fire(el, 'change'); };
const byLabel = (root, name) => root.all().find(e => e.getAttribute('aria-label') === name);
"""


def run(code: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (
        STUB
        + "\n(async function () {\n"
        + js_core.JS
        + "\n"
        + PRELUDE
        + "\n"
        + js_menu.JS
        + "\nconst root = new Element('div');\n"
        + code
        + "\n})().then(r => console.log(JSON.stringify(r))).catch(e => { console.error(e.stack || e); process.exit(1); });\n"
    )
    done = subprocess.run(
        [node, "--input-type=commonjs"],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_an_empty_menu_offers_a_first_use_case_and_the_flows_waiting_to_be_placed():
    out = run(
        """
        await renderChatMenu(root); await settle();
        return { add: !!byText(root, '＋ Add a use case'), text: root.textContent,
                 save: root.querySelector('.cm-save').className };
        """
    )
    assert out["add"] is True
    assert "No use cases yet" in out["text"] and "Not placed yet" in out["text"]
    assert "File a complaint" in out["text"] and "Old flow" in out["text"]
    assert "switched off" in out["text"]  # a flow that is off says so
    assert out["save"] == "cm-save"  # nothing to save yet


def test_naming_a_use_case_and_putting_flows_in_it_saves_the_tree_the_server_expects():
    out = run(
        """
        await renderChatMenu(root); await settle();
        byText(root, '＋ Add a use case').click();
        typeInto(byLabel(root, 'Use case name'), 'Tickets');
        choose(byLabel(root, 'Add a flow to this group'), 'my_cases');
        byText(root, '＋ Add a group').click();
        typeInto(byLabel(root, 'Group name'), 'Raise');
        const put = byLabel(root, 'Put File a complaint under a use case or group');
        choose(put, put.childNodes[1].value);   // the first place offered: the use case itself
        const barOn = root.querySelector('.cm-save').className;
        byText(root, 'Save menu').click(); await settle();
        const sent = calls.find(c => c[0] === 'PUT');
        return { barOn, put: sent && sent[2].config };
        """
    )
    assert out["barOn"] == "cm-save on"
    cfg = out["put"]
    use_case = cfg["nodes"][0]
    assert use_case["label"] == "Tickets" and use_case["id"].startswith("use_case")
    kinds = [
        ("flow" in c, c.get("flow") or c.get("label")) for c in use_case["children"]
    ]
    assert kinds[0] == (True, "my_cases") and kinds[1] == (False, "Raise")
    # File a complaint was put under the first group offered in the list (the use case itself)
    placed = [c.get("flow") for c in use_case["children"] if "flow" in c]
    assert "file_a_complaint" in placed


def test_a_flow_can_be_hidden_renamed_moved_and_taken_out():
    out = run(
        """
        start = { enabled: true, show_unplaced: true, nodes: [
          { id: 'tickets', label: 'Tickets', description: '', hidden: false, children: [
            { id: 'raise', label: 'Raise', description: '', hidden: false, children: [] },
            { flow: 'my_cases', hidden: false }, { flow: 'file_a_complaint', hidden: false }] }] };
        await renderChatMenu(root); await settle();
        typeInto(byLabel(root, 'Name in the menu for My Open Tickets'), 'My tickets');
        const sw = byLabel(root, 'Show File a complaint in the menu');
        sw.checked = false; fire(sw, 'change'); await settle();
        const mover = byLabel(root, 'Move My Open Tickets to another place');
        choose(mover, 'raise'); await settle();
        byText(root, 'Save menu').click(); await settle();
        const put = calls.find(c => c[0] === 'PUT')[2].config;
        const t = put.nodes[0].children;
        return { top: t.map(c => c.flow || c.id), inRaise: t[0].children, hidden: t[1] };
        """
    )
    assert out["top"] == ["raise", "file_a_complaint"]
    assert out["inRaise"] == [
        {"flow": "my_cases", "hidden": False, "label": "My tickets"}
    ]
    assert out["hidden"]["hidden"] is True


def test_starting_from_todays_menu_fills_the_tree_and_the_menu_is_switched_on_by_the_switch():
    out = run(
        """
        await renderChatMenu(root); await settle();
        byText(root, 'Start from today’s menu').click(); await settle();
        const sw = byLabel(root, 'Use this menu in the chat');
        sw.checked = true; fire(sw, 'change'); await settle();
        byText(root, 'Save menu').click(); await settle();
        return { put: calls.find(c => c[0] === 'PUT')[2].config, text: root.textContent };
        """
    )
    assert out["put"]["enabled"] is True
    assert out["put"]["nodes"][0]["label"] == "Create"
    assert "Create" in out["text"]


def test_discard_goes_back_to_what_was_saved():
    out = run(
        """
        await renderChatMenu(root); await settle();
        byText(root, '＋ Add a use case').click();
        const before = !!byText(root, 'Discard');
        byText(root, 'Discard').click(); await settle();
        return { before, after: !!byText(root, 'Discard'), noCases: root.textContent.includes('No use cases yet') };
        """
    )
    assert out["before"] is True and out["after"] is False and out["noCases"] is True
