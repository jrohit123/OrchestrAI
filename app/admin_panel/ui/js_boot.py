JS = r"""
// ───────────────────────── page shell and start-up ─────────────────────────
// The menu is grouped by what you are doing. The server decides which sections exist for this
// organisation; this only says where each one goes and what it looks like.
const NAV = [
  ['Run the day', ['overview', 'cases', 'conversations', 'people']],
  ['Shape the assistant', ['workflows', 'assistant', 'connections']],
  ['Admin', ['activity', 'settings']],
];
const NAV_ICON = { overview: 'home', cases: 'cases', conversations: 'chat', people: 'users', workflows: 'flow', assistant: 'spark', connections: 'plug', activity: 'hist', settings: 'sliders' };
// parts that are planned but not built yet: shown greyed so the shape of the dashboard is visible
const NAV_SOON = {
  assistant: ['Assistant', 'The words the assistant says. This database needs one update first (migration core-0009).'],
  connections: ['Connections', 'Connect other systems. Comes after the security work.'],
};

// links and bookmarks from older versions of the dashboard keep working
function remapRoute(r) {
  if (r.section === 'routing') return { section: 'cases', tab: r.tab === 'categories' ? 'categories' : 'rules', q: r.q };
  if (r.section === 'activity' && r.tab === 'chats') return { section: 'conversations', tab: '', q: r.q };
  return null;
}

function errorBox(e, retry) {
  return h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, notice(e.message || String(e), 'bad'), retry ? h('div', null, h('button', { class: 'btn', onclick: retry }, 'Try again')) : null));
}
function setCrumbs(parts) {
  const el = document.getElementById('crumbs');
  if (!el) return;
  fill(el, parts.flatMap((p, i) => [i ? h('span', { class: 'sep' }, '/') : null, p]));
}
function applyRail() { document.body.classList.toggle('rail', !!S.userRail || !!S.editing || (innerWidth <= 1000 && innerWidth > 700)); }

async function renderSection(sec, r) {
  const mine = ++S.renderId;
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.key === sec.key));
  document.body.classList.remove('menu-open');
  const impl = SECTIONS[sec.key];
  const tab = sec.tabs ? (sec.tabs.find(t => t.key === r.tab) || sec.tabs[0]) : null;
  r.tab = tab ? tab.key : '';
  const editing = sec.key === 'workflows' && !!r.q.w;
  S.editing = editing; applyRail();
  closePop();
  setCrumbs(editing ? [h('a', { href: href('workflows') }, 'Flows'), h('span', { id: 'crumbname' }, '…')]
    : tab && tab !== sec.tabs[0] ? [h('a', { href: href(sec.key) }, sec.label), h('span', null, tab.label)] : [h('span', null, sec.label)]);
  const heading = impl.heading ? impl.heading(sec) : { title: sec.label, sub: impl.sub };
  const head = editing ? null : h('div', { class: 'ph' }, h('div', null, h('h1', null, heading.title), heading.sub ? h('div', { class: 'sub' }, heading.sub) : null), impl.actions ? impl.actions(r) : null);
  const tabs = tab && !editing ? h('div', { class: 'tabs' }, sec.tabs.map(t => h('a', { class: 'tab' + (t.key === tab.key ? ' active' : ''), href: href(sec.key, t.key === sec.tabs[0].key ? '' : t.key) }, t.label))) : null;
  const loading = h('div', { class: 'empty' }, 'Loading…'), content = h('div');
  fill(document.getElementById('main'), h('div', { class: 'screen' + (editing ? ' bleed' : '') }, head, tabs, loading, content));
  document.title = (editing ? 'Flow' : sec.label) + ' · ' + S.boot.org.name;
  try { await impl.render(content, r); }
  catch (e) { if (mine === S.renderId) fill(content, errorBox(e, () => { lastSig = ''; onRoute(); })); }
  loading.remove();
  if (mine === S.renderId && !editing) window.scrollTo(0, 0);
}
function syncDrawer(r) {
  const key = r.q.case ? 'case:' + r.q.case : r.q.person ? 'person:' + r.q.person : '';
  if (key === drawerKey) return;
  drawerKey = key;
  if (!key) closeDrawer(true);
  else if (r.q.case) showCase(r.q.case);
  else showPerson(r.q.person);
}
async function onRoute() {
  const r = parseRoute();
  const mapped = remapRoute(r);
  if (mapped) { location.replace(href(mapped.section, mapped.tab, mapped.q)); return; }
  const sec = S.boot.sections.find(s => s.key === r.section);
  if (!sec) { location.replace(href(S.boot.sections[0].key)); return; }
  const sig = sigOf(r);
  if (sig !== lastSig) {
    if (S.leaveGuard && !S.leaveGuard()) { history.replaceState(null, '', lastHash); return; }
    lastSig = sig; lastHash = location.hash;
    await renderSection(sec, r);
  }
  syncDrawer(r);
}

// ----- search or jump to (Ctrl+K) -----
function openCmd() {
  closePop();
  const input = h('input', { type: 'text', placeholder: 'Search screens, flows, people and cases…', autocomplete: 'off', 'aria-label': 'Search' });
  const res = h('div', { class: 'res' });
  const wrap = h('div', { class: 'cmdk', onmousedown: e => { if (e.target === wrap) shut(); } }, h('div', { class: 'box' }, input, res));
  let items = [], at = 0, seq = 0;
  const shut = () => { wrap.remove(); document.removeEventListener('keydown', onKey, true); };
  const run = i => { const x = items[i]; if (!x) return; shut(); x.run(); };
  function draw() {
    at = Math.min(at, Math.max(0, items.length - 1));
    let last = '';
    fill(res, items.length ? items.map((x, i) => [x.g !== last ? h('div', { class: 'grp' }, last = x.g) : null, h('button', { type: 'button', class: i === at ? 'sel' : '', onclick: () => run(i) }, h('span', { class: 'grow' }, x.t), x.s ? h('span', { class: 'muted small' }, x.s) : null)]) : h('div', { class: 'empty' }, 'Nothing matches'));
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.stopPropagation(); shut(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); at = (at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % Math.max(1, items.length); draw(); }
    else if (e.key === 'Enter') { e.preventDefault(); run(at); }
  }
  document.addEventListener('keydown', onKey, true);
  const screens = () => S.boot.sections.map(s => ({ g: 'Screens', t: s.label, run: () => go(s.key) }));
  async function search(q) {
    const mine = ++seq, low = q.trim().toLowerCase();
    items = screens().filter(x => !low || x.t.toLowerCase().includes(low));
    if (low) {
      try { if (!ST.catalog) await ensureStudio(); } catch (e) { /* the screens still work */ }
      items = items.concat((ST.flows || []).filter(w => (w.name + ' ' + w.intent_key).toLowerCase().includes(low)).slice(0, 5).map(w => ({ g: 'Flows', t: w.name, s: w.kind === 'block' ? 'Building block' : '', run: () => openWorkflow(w.id) })));
    }
    draw();
    if (low.length < 2) return;
    const more = [];
    await Promise.all([
      api.get('/people', { q, page_size: 5 }).then(d => d.rows.forEach(p => more.push({ g: 'People', t: p.name, s: p.role || '', run: () => go('people', 'people', { person: p.id }) }))).catch(() => {}),
      S.boot.caps.cases ? api.get('/cases', { q, page_size: 5 }).then(d => d.rows.forEach(c => more.push({ g: 'Cases', t: c.case_number + '  ' + c.title, s: pretty(c.status), run: () => go('cases', '', { case: c.id }) }))).catch(() => {}) : null,
    ]);
    if (mine !== seq) return;
    items = items.concat(more); draw();
  }
  input.addEventListener('input', debounce(() => search(input.value), 180));
  document.body.append(wrap); input.focus(); search('');
}
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && S.boot) { e.preventDefault(); if (!document.querySelector('.cmdk')) openCmd(); } });

// ----- the "New" menu -----
function newMenu(anchor) {
  const caps = S.boot.caps, row = (ic, t, sub, fn) => h('button', { class: 'mi', type: 'button', onclick: () => { closePop(); fn(); } }, icon(ic), h('span', null, t, h('small', null, sub)));
  openPop(anchor, [h('div', { class: 'ml' }, 'Create'),
    row('flow', 'New flow', 'Describe it, start blank or copy one', async () => { try { await ensureStudio(); newWorkflowModal(!!caps.workflow_kind); } catch (e) { toast(e.message, 'bad'); } }),
    caps.case_model ? row('route', 'New kind of complaint', 'And who it goes to', () => go('cases', 'categories')) : null,
    caps.seats ? row('tag', 'New seat', 'A named job held by one person', () => go('people', 'seats')) : null], { align: 'right', width: 290 });
}

function buildShell(app) {
  const o = S.boot.org, have = new Map(S.boot.sections.map(s => [s.key, s]));
  const logo = h('span', { class: 'logo' }, o.name[0]);
  if (o.has_logo) classic.get('/settings/logo').then(d => { if (d.logo_url) fill(logo, h('img', { src: d.logo_url, alt: '' })); }).catch(() => {});
  const link = sec => h('a', { href: href(sec.key), 'data-key': sec.key }, icon(NAV_ICON[sec.key] || 'list'), h('span', { class: 'tx' }, sec.label));
  const soon = k => h('div', { class: 'soon', 'data-tip': NAV_SOON[k][1] }, icon(NAV_ICON[k]), h('span', { class: 'tx' }, NAV_SOON[k][0]), h('span', { class: 'navtag' }, 'Soon'));
  const nav = h('nav', { class: 'nav', 'aria-label': 'Sections' });
  const placed = new Set();
  NAV.forEach(([label, keys]) => {
    const items = keys.map(k => { placed.add(k); return have.has(k) ? link(have.get(k)) : NAV_SOON[k] ? soon(k) : null; }).filter(Boolean);
    if (items.length) nav.append(h('div', { class: 'navlabel' }, label), ...items);
  });
  const extra = S.boot.sections.filter(s => !placed.has(s.key));
  if (extra.length) nav.append(...extra.map(link));
  const side = h('aside', { class: 'side', id: 'side', 'aria-label': 'Main menu' },
    h('div', { class: 'sbrand' }, logo, h('div', null, h('b', null, o.name), h('small', null, 'Admin'))),
    h('button', { class: 'jump', type: 'button', 'aria-label': 'Search or jump to', onclick: openCmd }, icon('search', 'sm'), h('span', null, 'Search or jump to…'), h('span', { class: 'kbd' }, 'Ctrl K')),
    nav, h('div', { class: 'grow' }),
    h('div', { class: 'sidefoot' },
      h('a', { href: '/admin/' + encodeURIComponent(ORG) + '/legacy' }, icon('ext'), h('span', { class: 'tx' }, 'Classic dashboard')),
      h('button', { type: 'button', onclick: () => { S.userRail = !S.userRail; applyRail(); } }, icon('panel'), h('span', { class: 'tx' }, 'Collapse menu')),
      h('button', { type: 'button', onclick: () => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark') }, icon('moon'), h('span', { class: 'tx' }, 'Light / dark'))));
  const top = h('header', { class: 'topbar' },
    h('button', { class: 'iconbtn menubtn', type: 'button', 'aria-label': 'Menu', onclick: () => document.body.classList.toggle('menu-open') }, icon('list')),
    h('div', { class: 'crumbs', id: 'crumbs' }), h('div', { class: 'sp' }),
    h('button', { class: 'btn primary', type: 'button', 'data-popkeep': '1', onclick: e => newMenu(e.currentTarget) }, icon('plus', 'sm'), 'New', icon('chevd', 'xs')));
  fill(app, h('div', { class: 'app' }, side, h('div', { class: 'col' }, top, h('main', { class: 'main', id: 'main' }))));
  window.addEventListener('resize', applyRail);
}
async function boot() {
  S.renderId = 0;
  const app = document.getElementById('app');
  try { S.boot = await api.get('/bootstrap'); }
  catch (e) { fill(app, h('div', { class: 'boot' }, 'The dashboard could not start: ' + e.message)); return; }
  buildShell(app);
  window.addEventListener('hashchange', onRoute);
  await onRoute();
}
boot();
"""
