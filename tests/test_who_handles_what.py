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
];
const trules = [
  { id: 'r-fin', name: 'Finance', category_id: 'k-fin', intent_key: null, match: {}, is_active: true, target_minutes: 90, assign_type: 'user', assign_id: 'u-old', assign_name: 'Old Person', backup_type: null, backup_id: null,
    people: [tp(U.b, 'Bhaskar', 1), tp(U.c, 'Chetan', 1), tp(U.e, 'Elizabeth', 2, false)] },
  { id: 'r-x', name: 'Finance big', category_id: 'k-fin', intent_key: null, match: { amount: 'big' }, is_active: true, people: [tp(U.a, 'Anuja', 1)] },
];
api.get = async p => (p === '/categories' ? { rows: tcats } : { rows: trules, context_keys: [] });
api.post = async (p, b) => { tcalls.push(['POST', p, b]); return { ok: true, id: 'new-id', route: null }; };
api.put = async (p, b) => { tcalls.push(['PUT', p, b]); return { ok: true }; };
api.patch = async (p, b) => { tcalls.push(['PATCH', p, b]); return { ok: true }; };
api.del = async p => { tcalls.push(['DELETE', p]); return { ok: true }; };
toast = () => {};
confirmBox = async () => true;
openPop = () => {}; closePop = () => {};
const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const byText = (root, t) => root.all().find(e => e.tagName === 'BUTTON' && e.textContent === t);
const rowNamed = (root, t) => root.all().find(e => e.className.includes('wh-row') && e.textContent.includes(t));
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


def test_the_screen_lists_the_areas_and_shows_the_chosen_ones_team_in_words():
    out = run(
        """
        await renderTeamsTab(root);
        const rows = root.all().filter(e => e.className.includes('wh-row')).map(e => e.textContent);
        const sentence = root.querySelector('.wh-sent').textContent;
        return { rows, sentence };
        """
    )
    assert out["rows"][:3] == ["Finance", "Bill query", "Legal"]
    assert out["rows"][-1] == "Everything else"
    assert "goes to Bhaskar" in out["sentence"]
    assert "Chetan takes it" in out["sentence"]
    assert "Elizabeth is kept in the loop" in out["sentence"]


def test_moving_someone_down_and_saving_sends_the_new_order_and_keeps_the_rules_other_settings():
    out = run(
        """
        await renderTeamsTab(root);
        root.querySelectorAll('[aria-label=Move down]')[0].click();
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
    assert (
        body["target_minutes"] == 90
        and body["match"] == {}
        and body["intent_key"] is None
    )


def test_a_kind_without_its_own_team_follows_its_area_and_can_be_given_one():
    out = run(
        """
        await renderTeamsTab(root);
        await rowNamed(root, 'Bill query').click();
        await settle();
        const follows = root.querySelector('.wh-note').textContent;
        byText(root, 'Give it its own team').click();
        byText(root, 'Save team').click();
        await settle();
        return { follows, calls: tcalls };
        """
    )
    assert "Follows the team of Finance" in out["follows"]
    verb, path, body = out["calls"][0]
    assert (verb, path) == ("POST", "/rules")
    assert body["category_id"] == "k-bill" and body["name"] == "Bill query"
    assert [p["user_id"] for p in body["people"]] == [
        "u-bhaskar",
        "u-chetan",
        "u-elizabeth",
    ]


def test_an_area_with_nobody_says_so_and_refuses_to_save_an_empty_team():
    out = run(
        """
        await renderTeamsTab(root);
        await rowNamed(root, 'Legal').click();
        await settle();
        const sentence = root.querySelector('.wh-sent').textContent;
        return { sentence, hasSave: !!byText(root, 'Save team'), calls: tcalls };
        """
    )
    assert "Nobody handles this yet" in out["sentence"]
    assert out["hasSave"] is False and out["calls"] == []


def test_a_kind_with_its_own_team_can_go_back_to_following_its_area():
    out = run(
        """
        trules.push({ id: 'r-bill', name: 'Bill query', category_id: 'k-bill', intent_key: null, match: {}, is_active: true, people: [tp(U.a, 'Anuja', 1)] });
        await renderTeamsTab(root);
        await rowNamed(root, 'Bill query').click();
        await settle();
        byText(root, 'Follow its area instead').click();
        await settle();
        return { calls: tcalls };
        """
    )
    assert out["calls"][0] == ["DELETE", "/rules/r-bill"]
