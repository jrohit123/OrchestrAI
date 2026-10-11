"""The "Who handles what" screen: areas on the left, the team of the chosen one on the right. It runs in Node against a
small stand-in for the page and a fake server, and checks what the screen asks the server to save. Skipped where node
is not installed."""

import json
import shutil
import subprocess

import pytest

from app.admin_panel.ui import js_core, js_routing
from tests.js_page import STUB

PRELUDE = r"""
const icon = () => h('i', null);
const setTopAction = () => {};
const tcalls = [];
const U = { a: 'u-anuja', b: 'u-bhaskar', c: 'u-chetan', e: 'u-elizabeth' };
const tp = (id, name, level, reachable = true) => ({ user_id: id, name, level, reachable });
const tcats = [
  { id: 'k-fin', parent_id: null, label: 'Finance', is_active: true, depth: 0 },
  { id: 'k-bill', parent_id: 'k-fin', label: 'Bill query', is_active: true, depth: 1 },
  { id: 'k-leg', parent_id: null, label: 'Legal', is_active: true, depth: 0 },
  { id: 'k-elec', parent_id: null, label: 'Electrical', is_active: false, depth: 0 },
];
const trules = [
  { id: 'r-fin', name: 'Finance', category_id: 'k-fin', intent_key: null, match: {}, is_active: true, target_minutes: 90, assign_type: 'user', assign_id: 'u-old', assign_name: 'Old Person', backup_type: null, backup_id: null,
    people: [tp(U.b, 'Bhaskar Chatterjee', 1), tp(U.c, 'Chetan Bhandare', 1), tp(U.e, 'Elizabeth Mathai', 2, false)] },
  { id: 'r-catch', name: 'Anything else (catch-all)', category_id: null, intent_key: null, match: {}, is_active: true, people: [tp(U.a, 'Anuja Sinkar', 1)] },
  { id: 'r-x', name: 'Finance big', category_id: 'k-fin', intent_key: null, match: { amount: 'big' }, is_active: true, people: [tp(U.a, 'Anuja Sinkar', 1)] },
];
api.get = async p => (p === '/categories' ? { rows: tcats } : { rows: trules, context_keys: [] });
api.post = async (p, b) => { tcalls.push(['POST', p, b]); return { ok: true, id: 'new-id', route: null }; };
api.put = async (p, b) => { tcalls.push(['PUT', p, b]); return { ok: true }; };
api.patch = async (p, b) => { tcalls.push(['PATCH', p, b]); return { ok: true }; };
api.del = async p => { tcalls.push(['DELETE', p]); return { ok: true }; };
toast = () => {};
confirmBox = async () => true;
openPop = () => {}; closePop = () => {};
const settle = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const isRow = e => e.className.split(' ').includes('wh-r');
const rowNamed = (root, t) => root.all().find(e => isRow(e) && e.textContent.startsWith(t));
const byText = (root, t) => root.all().find(e => e.tagName === 'BUTTON' && e.textContent === t);
const fire = (el, type) => { for (const f of el.l[type] || []) f({ target: el, currentTarget: el }); };
"""


def run(code: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    body = js_core.JS
    routing = js_routing.JS.replace(
        "SECTIONS.rules = {", "const SECTIONS_RULES_UNUSED = {"
    )
    script = (
        STUB
        + "\n(async function () {\n"
        + body
        + "\n"
        + PRELUDE
        + "\n"
        + routing
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


def test_the_table_lists_the_areas_with_owner_and_backups_and_hides_the_hidden_ones():
    out = run(
        """
        await renderTeamsTab(root);
        const head = root.querySelector('.wh-hd').textContent;
        const rows = root.all().filter(isRow).map(e => e.textContent);
        return { head, rows };
        """
    )
    assert "Backups (also told)" in out["head"] and "Informed only" in out["head"]
    assert (
        out["rows"][0].startswith("Finance") and "Bhaskar Chatterjee" in out["rows"][0]
    )
    assert "Chetan B." in out["rows"][0]  # a backup, shown short
    assert any(
        r.startswith("Legal") and "Same team as Everything else" in r
        for r in out["rows"]
    )
    assert not any(r.startswith("Electrical") for r in out["rows"])
    assert out["rows"][-1].startswith("Everything else")


def test_a_kind_is_tucked_under_its_area_and_says_whose_team_it_uses():
    out = run(
        """
        await renderTeamsTab(root);
        const before = root.all().filter(isRow).map(e => e.textContent);
        byText(root, 'Show 1 kind').click();
        const after = root.all().filter(isRow).map(e => e.textContent);
        return { before, after };
        """
    )
    assert not any(r.startswith("Bill query") for r in out["before"])
    assert any(
        r.startswith("Bill query") and "Same team as Finance" in r for r in out["after"]
    )


def test_the_hidden_areas_show_only_when_asked():
    out = run(
        """
        await renderTeamsTab(root);
        const box = root.querySelector('[aria-label=Show hidden areas]');
        box.checked = true; fire(box, 'change');
        return { rows: root.all().filter(isRow).map(e => e.textContent) };
        """
    )
    assert any(r.startswith("Electrical") for r in out["rows"])


def test_opening_a_row_says_in_words_who_gets_it():
    out = run(
        """
        await renderTeamsTab(root);
        rowNamed(root, 'Finance').click();
        await settle();
        return { sentence: root.querySelector('.wh-sent').textContent };
        """
    )
    assert "goes to Bhaskar Chatterjee" in out["sentence"]
    assert "cannot be reached: Chetan" in out["sentence"]
    assert "Also told: Elizabeth" in out["sentence"]


def test_making_a_backup_the_owner_and_saving_sends_the_new_order_and_keeps_the_rules_other_settings():
    out = run(
        """
        await renderTeamsTab(root);
        rowNamed(root, 'Finance').click();
        await settle();
        const pick = root.querySelector('[aria-label=Role of Chetan Bhandare]');
        pick.value = 'owner'; fire(pick, 'change');
        byText(root, 'Save team').click();
        await settle();
        return { calls: tcalls };
        """
    )
    verb, path, body = out["calls"][0]
    assert (verb, path) == ("PUT", "/rules/r-fin")
    assert [p["user_id"] for p in body["people"]] == [
        "u-chetan",
        "u-bhaskar",
        "u-elizabeth",
    ]
    assert [p["level"] for p in body["people"]] == [1, 1, 2]
    assert body["assign"] == {"type": "user", "id": "u-old"}  # the old target is kept
    assert body["target_minutes"] == 90 and body["match"] == {}


def test_a_kind_can_be_given_its_own_team_copied_from_the_one_it_followed():
    out = run(
        """
        await renderTeamsTab(root);
        byText(root, 'Show 1 kind').click();
        rowNamed(root, 'Bill query').click();
        await settle();
        byText(root, 'Give it its own team').click();
        byText(root, 'Save team').click();
        await settle();
        return { calls: tcalls };
        """
    )
    verb, path, body = out["calls"][0]
    assert (verb, path) == ("POST", "/rules")
    assert body["category_id"] == "k-bill" and body["name"] == "Bill query"
    assert [p["user_id"] for p in body["people"]] == [
        "u-bhaskar",
        "u-chetan",
        "u-elizabeth",
    ]


def test_an_area_with_no_team_follows_everything_else_until_given_its_own():
    out = run(
        """
        await renderTeamsTab(root);
        rowNamed(root, 'Legal').click();
        await settle();
        const note = root.querySelector('.wh-note').textContent;
        byText(root, 'Give it its own team').click();
        byText(root, 'Save team').click();
        await settle();
        return { note, calls: tcalls };
        """
    )
    assert "uses the team of Everything else" in out["note"]
    verb, path, body = out["calls"][0]
    assert (verb, path) == ("POST", "/rules") and body["category_id"] == "k-leg"
    assert [p["user_id"] for p in body["people"]] == ["u-anuja"]


def test_going_back_to_the_team_above_removes_only_its_own_rule():
    out = run(
        """
        await renderTeamsTab(root);
        rowNamed(root, 'Finance').click();
        await settle();
        byText(root, 'Use the team above again').click();
        await settle();
        return { calls: tcalls };
        """
    )
    assert out["calls"][0] == ["DELETE", "/rules/r-fin"]


def test_an_owner_is_needed_to_save():
    out = run(
        """
        trules[0].assign_id = null; trules[0].assign_type = null;
        await renderTeamsTab(root);
        rowNamed(root, 'Finance').click();
        await settle();
        for (const n of ['Bhaskar Chatterjee', 'Chetan Bhandare']) root.querySelector('[aria-label=Remove ' + n + ']').click();
        byText(root, 'Save team').click();
        await settle();
        return { calls: tcalls };
        """
    )
    assert out["calls"] == []
