"""Run the dashboard's own helper functions in Node, against a very small stand-in for the browser page.

The page script is kept as Python strings (app/admin_panel/ui). A test names the modules it needs, writes a
few lines that use the page's functions, and gets back what they returned as JSON. Needs node; the tests that
use it are skipped where it is not installed.
"""

import json
import shutil
import subprocess

import pytest

from app.admin_panel.ui import js_core

STUB = r"""
class Node {}
class Text extends Node {
  constructor(t) { super(); this.nodeType = 3; this.t = String(t); this.parentNode = null; }
  get textContent() { return this.t; }
}
const attrTest = (el, expr) => { const i = expr.indexOf('='); const k = i < 0 ? expr : expr.slice(0, i); const v = i < 0 ? undefined : expr.slice(i + 1); const have = el.getAttribute(k); return v === undefined ? have !== null : have === v; };
const matchSimple = (el, s) => {
  const m = s.match(/^([a-zA-Z0-9]+)?((?:[.#][\w-]+|\[[^\]]+\]|:not\(\[[^\]]+\]\))*)$/);
  if (!m) throw new Error('selector not supported by the test page: ' + s);
  if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
  for (const p of (m[2] || '').match(/[.#][\w-]+|:not\(\[[^\]]+\]\)|\[[^\]]+\]/g) || []) {
    if (p[0] === '.') { if (!el.className.split(/\s+/).includes(p.slice(1))) return false; }
    else if (p[0] === '#') { if (el.id !== p.slice(1)) return false; }
    else if (p.startsWith(':not(')) { if (attrTest(el, p.slice(6, -2))) return false; }
    else if (!attrTest(el, p.slice(1, -1))) return false;
  }
  return true;
};
const matchGroup = (el, group) => group.split(',').some(s => matchSimple(el, s.trim()));
class Element extends Node {
  constructor(tag) {
    super(); this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.childNodes = []; this.parentNode = null;
    this.a = {}; this.style = {}; this.l = {}; this.id = ''; this.className = ''; this.hidden = false; this.disabled = false; this.checked = false; this.value = '';
    const self = this;
    this.dataset = new Proxy({}, { get: (_, k) => self.a['data-' + k], set: (_, k, v) => { self.a['data-' + k] = String(v); return true; } });
  }
  setAttribute(k, v) { if (k === 'id') this.id = String(v); else if (k === 'class') this.className = String(v); else this.a[k] = String(v); }
  getAttribute(k) { if (k === 'id') return this.id || null; if (k === 'class') return this.className || null; return Object.prototype.hasOwnProperty.call(this.a, k) ? this.a[k] : null; }
  get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
  set textContent(v) { this.childNodes = [new Text(v)]; }
  get firstChild() { return this.childNodes[0] || null; }
  append(...kids) { for (const k of kids) { const n = k instanceof Node ? k : new Text(k); if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; this.childNodes.push(n); } }
  removeChild(n) { const i = this.childNodes.indexOf(n); if (i >= 0) this.childNodes.splice(i, 1); n.parentNode = null; return n; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  addEventListener(t, f) { (this.l[t] = this.l[t] || []).push(f); }
  click() { const ev = { target: this, currentTarget: this, preventDefault() {}, stopPropagation() {} }; for (const f of this.l.click || []) f(ev); }
  matches(sel) { return matchGroup(this, sel); }
  all() { const out = []; const walk = n => { for (const c of n.childNodes) if (c.nodeType === 1) { out.push(c); walk(c); } }; walk(this); return out; }
  querySelectorAll(sel) { return this.all().filter(e => matchGroup(e, sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) { let n = this; while (n && n.nodeType === 1) { if (matchGroup(n, sel)) return n; n = n.parentNode; } return null; }
}
const document = {
  body: new Element('body'), documentElement: new Element('html'),
  createElement: t => new Element(t), createElementNS: (ns, t) => new Element(t), createTextNode: t => new Text(t),
  addEventListener() {}, querySelector(s) { return this.body.querySelector(s); }, querySelectorAll(s) { return this.body.querySelectorAll(s); },
};
document.body.dataset.org = 'test';
const timers = [];
const setTimeout = (f, ms) => { timers.push({ f, ms }); return timers.length; };
const clearTimeout = () => {};
const location = { search: '', hash: '' }, history = {}, window = { addEventListener() {} }, navigator = {};
const matchMedia = () => ({ matches: false });
const localStorage = { getItem() { return null; }, setItem() {} };
const innerWidth = 1280, innerHeight = 800;
"""


def run_page(code: str, *modules) -> dict:
    """Run `code` inside the page script (the core helpers plus the given modules) and return what it
    returned. `code` must end with `return {...};`."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    body = "\n".join(m.JS for m in (js_core, *modules))
    script = (
        STUB
        + "\nconst result = (function () {\n"
        + body
        + "\n"
        + code
        + "\n})();\nconsole.log(JSON.stringify(result));\n"
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
