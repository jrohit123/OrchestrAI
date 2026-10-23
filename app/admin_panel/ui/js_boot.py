JS = r"""
// ───────────────────────── page shell and start-up ─────────────────────────
// The menu has two groups: what people do every day, and what is set up once and changed now and then.
// The server decides which screens exist for this organisation; this only says where each one goes.
const NAV = [
  ['', ['overview']],
  ['Your work', ['cases', 'conversations', 'announcements']],
  ['Your team', ['people', 'access']],
  ['Chat bot', ['assistant']],
  ['Build', ['workflows', 'blocks', 'schema']],
  ['', ['settings']],
];
const SETUP = new Set(['access', 'assistant', 'workflows', 'blocks', 'schema', 'settings']);
const NAV_ICON = { overview: 'home', cases: 'cases', conversations: 'chat', people: 'users', announcements: 'megaphone', workflows: 'flow', blocks: 'layers', schema: 'board', assistant: 'spark', rules: 'route', access: 'shield', settings: 'sliders' };
// the few words a newcomer meets, said once and the same everywhere
const GLOSSARY = [
  ['Flow', 'One thing the chat bot can do for people, like filing a complaint.'],
  ['Trigger', 'What starts a flow: a phrase someone says or a button they tap.'],
  ['Step', 'One box in a flow: look something up, save it, ask for approval, send a message.'],
  ['Building block', 'A small ready-made step that many flows use. Change it once and they all change.'],
  ['Role', 'A group of people who may do the same things, like Admin or Tenant.'],
  ['Seat', 'A job someone holds, like Secretary. Holding it can change their role.'],
  ['Chat bot', 'What people talk to on Telegram or WhatsApp. It understands what they write and starts the right flow.'],
  ['AI helper', 'Helps you in this dashboard: describe a flow and it drafts it for you to check.'],
];
function openWords(anchor, up) {
  openPop(anchor, h('div', { class: 'words' }, h('b', null, 'Words used here'), h('dl', null, GLOSSARY.map(([w, m]) => h('div', null, h('dt', null, w), h('dd', null, m))))), { width: 360, up: !!up });
}

// links and bookmarks from older versions of the dashboard keep working
function remapRoute(r) {
  const t = r.tab, q = r.q;
  if (r.section === 'usecases') return { section: 'workflows', tab: '', q: {} };
  if (r.section === 'build') return { section: 'workflows', tab: '', q: q.f ? { f: q.f } : {} };   // Build with AI is part of Flows now   // the use case settings are on the Flows boxes now
  if (r.section === 'routing') return { section: 'cases', tab: t === 'categories' ? 'categories' : 'teams', q };
  if (r.section === 'rules') return { section: 'cases', tab: t || 'teams', q };   // Case rules is now part of Tickets
  if (r.section === 'people' && t === 'seats') return { section: 'access', tab: 'seats', q };
  if (r.section === 'people' && t === 'access') return { section: 'access', tab: 'special', q };
  if (r.section === 'people' && t === 'roles') return { section: 'access', tab: '', q };
  if (r.section === 'people' && t === 'people') return { section: 'people', tab: '', q };
  if (r.section === 'activity') return t === 'chats' ? { section: 'conversations', tab: '', q } : { section: 'settings', tab: 'history', q: { ...q, show: t === 'changes' ? 'changes' : 'assistant' } };
  return null;
}

function errorBox(e, retry) {
  return h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, notice(e.message || String(e), 'bad'), retry ? h('div', null, h('button', { class: 'btn', onclick: retry }, 'Try again')) : null));
}
function setCrumbs(parts) {
  const el = document.getElementById('crumbs');
  if (!el) return;
  fill(el, parts.flatMap((p, i) => [i ? h('span', { class: 'sep', 'aria-hidden': 'true' }, '/') : null, p]));
}
function applyRail() { document.body.classList.toggle('rail', !!S.userRail || !!S.editing || (innerWidth <= 1000 && innerWidth > 700)); }

// the one main button of a screen, in the top bar: { label, run, icon? }, or nothing
function setTopAction(a) {
  const slot = document.getElementById('topact');
  if (slot) fill(slot, a ? h('button', { class: 'btn primary', type: 'button', 'aria-label': a.label, onclick: a.run }, icon(a.icon || 'plus', 'sm'), h('span', { class: 'tx' }, a.label)) : null);
}
async function renderSection(sec, r) {
  const mine = ++S.renderId;
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.key === sec.key));
  document.body.classList.remove('menu-open');
  const impl = SECTIONS[sec.key];
  const tab = sec.tabs ? (sec.tabs.find(t => t.key === r.tab) || sec.tabs[0]) : null;
  r.tab = tab ? tab.key : '';
  const editing = sec.key === 'workflows' && (!!r.q.w || !!r.q.f);
  S.editing = editing; applyRail();
  closePop(); setTopAction(null);
  S.leaveGuard = null; window.onbeforeunload = null;
  const group = SETUP.has(sec.key) ? [h('span', { class: 'muted' }, 'Set up')] : [];
  setCrumbs(editing ? [...group, h('a', { href: href(sec.key) }, 'Flows'), h('span', { id: 'crumbname' }, '…')]
    : tab && tab !== sec.tabs[0] ? [...group, h('a', { href: href(sec.key) }, sec.label), h('span', null, tab.label)] : [...group, h('span', null, sec.label)]);
  const heading = impl.heading ? impl.heading(sec, r) : { title: sec.label, sub: impl.sub };
  const head = editing ? null : h('div', { class: 'ph' }, h('div', null, h('h1', null, heading.title), heading.sub ? h('div', { class: 'sub' }, heading.sub) : null), impl.actions ? impl.actions(r) : null);
  const tabs = tab && !editing && sec.tabs.length > 1 ? h('div', { class: 'tabs' }, sec.tabs.map(t => h('a', { class: 'tab' + (t.key === tab.key ? ' active' : ''), href: href(sec.key, t.key === sec.tabs[0].key ? '' : t.key) }, t.label))) : null;
  const loading = h('div', { class: 'empty' }, 'Loading…'), content = h('div');
  fill(document.getElementById('main'), h('div', { class: 'screen' + (editing ? ' bleed' : '') }, head, tabs, loading, content));
  document.title = (editing ? 'Flow' : sec.label) + ' · ' + S.boot.org.name;
  try { await impl.render(content, r); }
  catch (e) { if (mine === S.renderId) fill(content, errorBox(e, () => { lastSig = ''; onRoute(); })); }
  loading.remove();
  if (mine === S.renderId && !editing) window.scrollTo(0, 0);
}

// two little numbers on the menu: open cases nobody has yet, and kinds of complaint nobody is sent to
let hintsAt = 0;
function paintHints() {
  const hn = S.hints || {}, un = hn.unassigned, gaps = hn.rule_gaps;
  const ct = document.querySelector('.nav a[data-key="cases"] .ct');
  if (ct) { ct.hidden = !un; ct.textContent = un > 99 ? '99+' : String(un || ''); ct.title = un ? plural(un, 'open case') + ' with no one handling ' + (un === 1 ? 'it' : 'them') : ''; }
  const dot = document.querySelector('.nav a[data-key="cases"] .navdot');
  if (dot) { dot.hidden = !gaps; dot.title = gaps ? plural(gaps, 'kind of complaint') + ' with nobody to go to' : ''; }
}
async function refreshHints(force) {
  if (!force && Date.now() - hintsAt < 20000) return;
  hintsAt = Date.now();
  try { S.hints = await api.get('/nav-hints'); paintHints(); } catch (e) { /* the numbers are a courtesy */ }
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
    refreshHints();
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
    if (low && isSuper()) {
      try { if (!ST.catalog) await ensureStudio(); } catch (e) { /* the screens still work */ }
      items = items.concat((ST.flows || []).filter(w => (w.name + ' ' + w.intent_key).toLowerCase().includes(low)).slice(0, 5).map(w => ({ g: 'Flows', t: w.name, s: w.kind === 'block' ? 'Building block' : '', run: () => openWorkflow(w.id) })));
    }
    draw();
    if (low.length < 2) return;
    const more = [];
    await Promise.all([
      api.get('/people', { q, page_size: 5 }).then(d => d.rows.forEach(p => more.push({ g: 'People', t: p.name, s: p.role || '', run: () => go('people', '', { person: p.id }) }))).catch(() => {}),
      S.boot.caps.cases ? api.get('/cases', { q, page_size: 5 }).then(d => d.rows.forEach(c => more.push({ g: 'Cases', t: c.case_number + '  ' + c.title, s: pretty(c.status), run: () => go('cases', '', { case: c.id }) }))).catch(() => {}) : null,
    ]);
    if (mine !== seq) return;
    items = items.concat(more); draw();
  }
  input.addEventListener('input', debounce(() => search(input.value), 180));
  document.body.append(wrap); input.focus(); search('');
}
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && S.boot) { e.preventDefault(); if (!document.querySelector('.cmdk')) openCmd(); } });

function buildShell(app) {
  const o = S.boot.org, have = new Map(S.boot.sections.map(s => [s.key, s]));
  const logo = h('span', { class: 'logo' }, o.name[0]);
  if (o.has_logo) api.get('/logo').then(d => { if (d.logo_url) fill(logo, h('img', { src: d.logo_url, alt: '' })); }).catch(() => {});
  const link = sec => h('a', { href: href(sec.key), 'data-key': sec.key }, icon(NAV_ICON[sec.key] || 'list'), h('span', { class: 'tx' }, sec.label),
    sec.key === 'cases' ? h('span', { class: 'ct', hidden: true }) : null, sec.key === 'cases' ? h('i', { class: 'navdot', hidden: true }) : null);
  const nav = h('nav', { class: 'nav', 'aria-label': 'Sections' });
  const placed = new Set();
  NAV.forEach(([label, keys]) => {
    const items = keys.map(k => { placed.add(k); return have.has(k) ? link(have.get(k)) : null; }).filter(Boolean);
    if (items.length) nav.append(...(label ? [h('div', { class: 'navlabel' }, label)] : []), ...items);
  });
  const extra = S.boot.sections.filter(s => !placed.has(s.key));
  if (extra.length) nav.append(...extra.map(link));
  const side = h('aside', { class: 'side', id: 'side', 'aria-label': 'Main menu' },
    h('div', { class: 'sbrand' }, logo, h('div', null, h('b', null, o.name), h('small', null, isSuper() ? 'Super admin view' : 'Admin'))),
    h('button', { class: 'jump', type: 'button', 'aria-label': 'Search or jump to', onclick: openCmd }, icon('search', 'sm'), h('span', null, 'Search or jump to…'), h('span', { class: 'kbd' }, 'Ctrl K')),
    nav, isSuper() ? null : adminHelpCard(), h('div', { class: 'grow' }),
    h('div', { class: 'sidefoot' }, accountChip(), signOutButton(),
      h('button', { type: 'button', 'data-popkeep': '1', onclick: e => openWords(e.currentTarget, true) }, icon('help'), h('span', { class: 'tx' }, 'Help & words')),
      h('button', { type: 'button', onclick: () => { S.userRail = !S.userRail; applyRail(); } }, icon('panel'), h('span', { class: 'tx' }, 'Collapse menu')),
      h('button', { type: 'button', onclick: () => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark') }, icon('moon'), h('span', { class: 'tx' }, 'Light / dark')),
      poweredBy('poweredby')));
  const top = h('header', { class: 'topbar' },
    h('button', { class: 'iconbtn menubtn', type: 'button', 'aria-label': 'Menu', onclick: () => document.body.classList.toggle('menu-open') }, icon('list')),
    h('a', { class: 'btn ghost sm sa-back', href: '/admin' }, icon('chevl', 'sm'), isSuper() ? 'All organisations' : 'My organisations'),
    h('div', { class: 'crumbs', id: 'crumbs' }), h('div', { class: 'sp' }), h('span', { id: 'topact' }));
  // first thing a keyboard user reaches: skip the menu (15 more stops) and go to the page. It is a link to #main, but the address
  // bar is the page's own router, so the click moves the focus instead of changing the address.
  const skip = h('a', { class: 'skip', href: '#main', onclick: e => { e.preventDefault(); const m = document.getElementById('main'); m.focus(); m.scrollIntoView(); } }, 'Skip to main content');
  fill(app, skip, h('div', { class: 'app' }, side, h('div', { class: 'col' }, top, h('main', { class: 'main', id: 'main', tabindex: -1 }))));
  window.addEventListener('resize', applyRail);
}
async function boot() {
  S.renderId = 0;
  const app = document.getElementById('app');
  let me;
  try { me = await authMe(); }
  catch (e) { fill(app, h('div', { class: 'boot' }, 'The dashboard could not start: ' + e.message)); return; }
  if (!me) { await showSignIn(); return; }
  S.me = me;
  if (!ORG) { await startSuperPage(me); return; }
  if (!(isSuper() || me.orgs.some(o => o.key === ORG))) { showNoAccess(me); return; }
  try { S.boot = await api.get('/bootstrap'); }
  catch (e) { fill(app, h('div', { class: 'boot' }, 'The dashboard could not start: ' + e.message)); return; }
  Object.assign(VALUE_LABELS, S.boot.labels || {});
  buildShell(app);
  window.addEventListener('hashchange', onRoute);
  refreshHints(true);
  await onRoute();
}
boot();
"""
