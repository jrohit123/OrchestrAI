// ---------------- tiny helpers ----------------
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else if (k in el && k !== 'list' && k !== 'form') { try { el[k] = v; } catch (e) { el.setAttribute(k, v); } }
    else el.setAttribute(k, v === true ? '' : v);
  }
  add(el, kids);
  return el;
}
function add(el, ...kids) { for (const k of kids.flat(Infinity)) { if (k == null || k === false) continue; el.append(k instanceof Node ? k : document.createTextNode(String(k))); } return el; }
function fill(el, ...kids) { el.replaceChildren(); return add(el, kids); }
const $ = s => document.querySelector(s);
function clone(o) { return JSON.parse(JSON.stringify(o)); }
function uid(p) { return (p || 'n') + Math.random().toString(36).slice(2, 8); }
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]); }
function toast(msg) { const t = h('div', { class: 'toast' }, msg); document.body.append(t); setTimeout(() => t.remove(), 2600); }
function pill(text, tone) { return h('span', { class: 'pill' + (tone ? ' ' + tone : '') }, text); }
function sw(on, change, label) { const i = h('input', { type: 'checkbox', checked: !!on, onchange: e => change(e.target.checked) }); return h('label', { class: 'sw', title: label || '' }, i, h('i')); }

// ---------------- state ----------------
const S = { role: 'super', route: { name: 'home', a: '', b: '' }, dirty: false };
function isSuper() { return S.role === 'super'; }
function uc(id) { return DB.usecases.find(u => u.id === id); }

// ---------------- modal / overlay ----------------
function modal({ title, body, actions, size, onClose }) {
  const layer = $('#layer');
  const close = () => { ov.remove(); onClose && onClose(); };
  const foot = actions ? h('div', { class: 'modal-f' }, actions.map(a => h('button', { class: 'btn' + (a.primary ? ' pri' : '') + (a.danger ? ' danger' : ''), onclick: async () => { if (a.run && (await a.run()) === false) return; close(); } }, a.label))) : null;
  const m = h('div', { class: 'modal' + (size ? ' ' + size : '') }, h('div', { class: 'modal-h' }, typeof title === 'string' ? h('h2', null, title) : title, h('button', { class: 'x-btn', onclick: close, 'aria-label': 'Close' }, '×')), h('div', { class: 'modal-b' }, body), foot);
  const ov = h('div', { class: 'ov', onmousedown: e => { if (e.target === ov) close(); } }, m);
  layer.append(ov);
  return { close, el: m };
}
function confirmBox(text, ok) {
  return new Promise(res => modal({ title: 'Please check', body: h('p', { style: { margin: 0 } }, text), actions: [{ label: 'Cancel', run: () => res(false) }, { label: ok || 'Yes', primary: true, run: () => res(true) }] }));
}

// ---------------- routing ----------------
function go(name, a, b) { location.hash = '#/' + [name, a, b].filter(Boolean).join('/'); }
function parse() { const p = location.hash.replace(/^#\/?/, '').split('/'); return { name: p[0] || 'home', a: p[1] || '', b: p[2] || '' }; }
window.addEventListener('hashchange', () => render());

// ---------------- side menu: drawn from the use cases, never a fixed list ----------------
function drawSide() {
  const r = S.route, side = $('#side');
  const item = (key, icon, label, onclick, count, extra) => h('button', { class: 'ni' + (key ? (isOn(key) ? ' on' : '') : '') + (extra || ''), onclick }, h('span', { class: 'ic' }, icon), label, count != null ? h('span', { class: 'ct' }, count) : null);
  function isOn(key) { return key === [r.name, r.a].filter(Boolean).join('/') || key === r.name; }
  fill(side,
    h('div', { class: 'org' }, h('div', { class: 'lg' }, DB.org.short), h('div', null, h('b', null, DB.org.name), h('small', null, isSuper() ? 'Super admin' : 'Admin'))),
    item('home', '🏠', 'Home', () => go('home')),
    h('div', { class: 'nh' }, 'Use cases', isSuper() ? h('button', { title: 'Add a use case', onclick: () => newUsecaseModal() }, '+') : null),
    DB.usecases.map(u => item('uc/' + u.id, u.icon, u.name, () => go('uc', u.id), (DB.items[u.id] || []).length)),
    h('div', { class: 'nh' }, 'Your team'),
    item('people', '👥', 'People', () => go('people')),
    item('roles', '🛡️', isSuper() ? 'Roles & access' : 'Roles (view)', () => go('roles')),
    isSuper() ? [
      h('div', { class: 'nh' }, 'Build'),
      item('flows', '🔀', 'All flows', () => go('flows'), DB.flows.length),
      item('blocks', '🧩', 'Building blocks', () => go('blocks'), DB.blocks.length),
      item('schema', '🗄️', 'Data & schema', () => go('schema')),
    ] : null,
    h('div', { class: 'side-foot' }, h('div', { class: 'who' }, h('div', { class: 'av' }, isSuper() ? 'KB' : 'AS'), h('div', null, h('b', { class: 'small' }, isSuper() ? 'Kartik B.' : 'Anuja Sinkar'), h('div', { class: 'tiny muted' }, isSuper() ? 'Super admin' : 'Admin')))));
}

function drawTop(crumbs) {
  const seg = h('div', { class: 'seg', title: 'See the dashboard as' },
    ['super', 'admin'].map(k => h('button', { class: S.role === k ? 'on' : '', onclick: () => setRole(k) }, k === 'super' ? 'Super admin' : 'Admin')));
  const theme = h('button', { class: 'btn sm ghost', title: 'Light or dark', onclick: () => { const d = document.documentElement; d.dataset.theme = d.dataset.theme === 'dark' ? 'light' : 'dark'; } }, '🌓');
  fill($('#top'), h('div', { class: 'crumbs' }, crumbs), h('div', { class: 'sp' }), h('span', { class: 'tiny muted' }, 'Prototype · see it as'), seg, theme);
}
function setRole(k) {
  S.role = k;
  const r = S.route;
  // an admin cannot open the build screens: take them home instead of showing an empty page
  if (k === 'admin' && ['flows', 'blocks', 'schema', 'flow', 'block'].includes(r.name)) { go('home'); return; }
  render();
}

// ---------------- render ----------------
function render() {
  S.route = parse();
  const r = S.route, scr = $('#screen');
  scr.className = ''; scr.replaceChildren();
  $('#layer').replaceChildren();
  drawSide();
  const screens = { home: screenHome, uc: screenUsecase, flows: screenFlows, blocks: screenBlocks, flow: screenFlowEditor, block: screenBlockEditor, roles: screenRoles, people: screenPeople, schema: screenSchema };
  (screens[r.name] || screenHome)(scr, r);
}
function boot() { render(); }
