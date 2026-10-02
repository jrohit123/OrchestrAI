JS = r"""
// ───────────────────────── Activity & chats ─────────────────────────
async function transcriptModal(sessionId, fallback) {
  let rows = [];
  if (sessionId) rows = (await classic.get('/activity/session', { session_id: sessionId })).rows;
  else if (fallback) rows = [fallback];
  const thread = h('div', { class: 'thread' });
  rows.forEach(r => {
    if (r.input_text) thread.append(h('div', { class: 'msg them' }, h('div', { class: 'who' }, (r.user_name || 'Person') + ' · ' + fmtDT(r.created_at)), h('div', { class: 'b' }, rich(r.input_text))));
    if (r.response_text) thread.append(h('div', { class: 'msg bot' }, h('div', { class: 'who' }, 'Assistant'), h('div', { class: 'b' }, rich(r.response_text))));
  });
  modal({ title: 'Conversation', wide: true, body: rows.length ? thread : empty('Nothing recorded', ''), actions: [{ label: 'Close' }] });
  setTimeout(() => { thread.scrollTop = thread.scrollHeight; }, 0);
}
// WhatsApp-style *bold* shown as bold instead of with the stars
function rich(text) {
  const out = [];
  String(text).split(/(\*[^*\n]+\*)/g).forEach(part => {
    if (/^\*[^*\n]+\*$/.test(part)) out.push(h('b', null, part.slice(1, -1)));
    else if (part) out.push(part);
  });
  return out;
}
const clip = (s, n) => !s ? '' : (s.length > n ? s.slice(0, n) + '…' : s);
// what became of a chat: still waiting for “yes”, failed, or nothing special
// Before 3 Oct 2026 the “yes” step was not written to the log, so older chats would wrongly look unfinished.
const CONFIRMS_LOGGED_FROM = new Date('2026-10-03T00:00:00+05:30').getTime();
function chatState(c) {
  if (c.had_error) return badge('Something failed', 'bad');
  if (new Date(c.started_at).getTime() < CONFIRMS_LOGGED_FROM) return null;
  if (/Reply \*yes\* to save/.test(c.last_reply || '')) {
    const old = Date.now() - new Date(c.last_at).getTime() > 10 * 60 * 1000;
    return old ? badge('Never confirmed', 'warn') : badge('Waiting for “yes”', 'info');
  }
  return null;
}
async function renderChats(root, route) {
  const mine = S.renderId;
  const q = { ...route.q }; q.page = Number(q.page || 1);
  const bar = h('div', { class: 'filters' }), out = h('div', { class: 'card' });
  root.append(bar, out);
  const update = patch => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
  const first = await api.get('/chats', { user_id: q.user, page_size: 1 });
  const who = sel([['', 'Everyone'], ...first.people.map(p => [p.id, p.name])], q.user || '', { onchange: e => update({ user: e.target.value }) });
  const text = h('input', { type: 'search', placeholder: 'Search what was said…', value: q.q || '', style: { minWidth: '240px' } });
  text.addEventListener('input', debounce(() => update({ q: text.value }), 300));
  const from = h('input', { type: 'date', value: q.from || '', onchange: e => update({ from: e.target.value }) }), to = h('input', { type: 'date', value: q.to || '', onchange: e => update({ to: e.target.value }) });
  bar.append(who, text, h('span', { class: 'row small muted' }, 'From', from, 'to', to));
  async function load() {
    if (mine !== S.renderId) return;
    setQuery(q);
    fill(out, h('div', { class: 'empty' }, 'Loading…'));
    try {
      const d = await api.get('/chats', { user_id: q.user, q: q.q, date_from: q.from, date_to: q.to, page: q.page, page_size: 20 });
      fill(out, d.rows.length ? d.rows.map(c => h('div', { class: 'row between', style: { padding: '12px 16px', borderBottom: '1px solid var(--line)', cursor: 'pointer', alignItems: 'flex-start' }, onclick: () => transcriptModal(c.session_id, { created_at: c.last_at, user_name: c.user_name, input_text: c.last_input, response_text: c.last_reply }).catch(e => toast(e.message, 'bad')) },
        h('div', { style: { minWidth: 0, flex: 1 } }, h('div', { class: 'row' }, person(null, c.user_name || 'Unknown'), h('span', { class: 'muted small' }, plural(c.turns, 'message') + ' · ' + fmtDT(c.started_at) + (c.turns > 1 ? ' → ' + fmtDT(c.last_at) : ''))),
          h('div', { style: { marginTop: '4px' } }, clip(c.last_input, 140)), h('div', { class: 'muted small' }, clip(c.last_reply, 160))),
        h('div', { class: 'chips', style: { justifyContent: 'flex-end' } }, chatState(c), (c.workflows || []).map(w => badge(w, 'brand'))))) : empty('No conversations match', ''),
        pager(d.total, d.page, d.page_size, p => update({ page: p })));
    } catch (e) { fill(out, notice(e.message, 'bad')); }
  }
  await load();
}
async function renderAll(root, route) {
  const mine = S.renderId;
  const q = { ...route.q }; q.page = Number(q.page || 1);
  const bar = h('div', { class: 'filters' }), out = h('div', { class: 'card' });
  root.append(bar, out);
  const update = patch => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
  const first = await classic.get('/activity', { page_size: 1 });
  const who = sel([['', 'Everyone'], ...(first.users || []).map(u => [u.id, u.name])], q.user || '', { onchange: e => update({ user: e.target.value }) });
  const text = h('input', { type: 'search', placeholder: 'Search…', value: q.q || '' });
  text.addEventListener('input', debounce(() => update({ q: text.value }), 300));
  bar.append(who, text);
  async function load() {
    if (mine !== S.renderId) return;
    setQuery(q);
    fill(out, h('div', { class: 'empty' }, 'Loading…'));
    try {
      const d = await classic.get('/activity', { user_id: q.user, search: q.q, page: q.page, page_size: 20 });
      fill(out, table([
        { label: 'When', render: r => h('span', { class: 'small' }, fmtDT(r.created_at)) },
        { label: 'Person', render: r => r.user_name || '—' },
        { label: 'Workflow', render: r => badge(r.workflow, r.workflow === 'Chat' ? '' : 'brand') },
        { label: 'They said', render: r => clip(r.input_text, 120) },
        { label: 'Reply', render: r => h('span', { class: 'muted' }, clip(r.response_text, 120)) },
        { label: 'Outcome', render: r => r.outcome ? badge(r.outcome, /fail|error|denied|block/i.test(r.outcome) ? 'bad' : 'ok') : '' },
      ], d.rows, { onRow: r => transcriptModal(r.session_id, r).catch(e => toast(e.message, 'bad')), emptyTitle: 'No activity matches' }), pager(d.total, d.page, d.page_size, p => update({ page: p })));
    } catch (e) { fill(out, notice(e.message, 'bad')); }
  }
  await load();
}
async function renderChanges(root, route) {
  const mine = S.renderId;
  const q = { ...route.q }; q.page = Number(q.page || 1);
  const bar = h('div', { class: 'filters' }), out = h('div', { class: 'card' });
  root.append(notice('Every change made from this dashboard is recorded here, with who made it.'), bar, out);
  const update = patch => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
  const first = await api.get('/events', { page_size: 1 });
  const area = sel([['', 'Everything'], ...first.areas.map(a => [a, pretty(a)])], q.area || '', { onchange: e => update({ area: e.target.value }) });
  const text = h('input', { type: 'search', placeholder: 'Search…', value: q.q || '' });
  text.addEventListener('input', debounce(() => update({ q: text.value }), 300));
  bar.append(area, text);
  async function load() {
    if (mine !== S.renderId) return;
    setQuery(q);
    fill(out, h('div', { class: 'empty' }, 'Loading…'));
    try {
      const d = await api.get('/events', { area: q.area, q: q.q, page: q.page, page_size: 30 });
      fill(out, table([
        { label: 'When', render: e => h('span', { class: 'small' }, fmtDT(e.created_at)) },
        { label: 'Area', render: e => badge(pretty(e.area)) },
        { label: 'What changed', render: e => h('div', null, e.summary, (e.before_state || e.after_state) ? h('details', null, h('summary', { class: 'muted small', style: { cursor: 'pointer' } }, 'Details'), h('pre', { class: 'small', style: { whiteSpace: 'pre-wrap', margin: '4px 0 0' } }, JSON.stringify({ before: e.before_state, after: e.after_state }, null, 2))) : null) },
        { label: 'By', render: e => h('span', { class: 'muted' }, e.actor_label || '—') },
      ], d.rows, { emptyTitle: 'No changes recorded yet' }), pager(d.total, d.page, d.page_size, p => update({ page: p })));
    } catch (e) { fill(out, notice(e.message, 'bad')); }
  }
  await load();
}
SECTIONS.activity = {
  title: 'Activity & chats', sub: 'What people asked the assistant, and what was changed here',
  async render(root, route) {
    if (route.tab === 'all') return renderAll(root, route);
    if (route.tab === 'changes') return renderChanges(root, route);
    return renderChats(root, route);
  },
};

// ───────────────────────── Settings ─────────────────────────
async function logoCard() {
  const box = h('div', { class: 'card' });
  const lg = await classic.get('/settings/logo').catch(() => ({}));
  const img = h('div', { class: 'brand' }, h('span', { class: 'logo', style: { width: '56px', height: '56px', color: '#fff' } }, lg.logo_url ? h('img', { src: lg.logo_url, alt: '' }) : S.boot.org.name[0]));
  const file = h('input', { type: 'file', accept: 'image/*' });
  box.append(h('div', { class: 'card-h' }, 'Organisation'), h('div', { class: 'card-b stack' },
    h('div', { class: 'row' }, h('b', null, S.boot.org.name), S.boot.org.industry ? badge(pretty(S.boot.org.industry)) : null),
    h('div', { class: 'row' }, h('div', { style: { color: 'var(--ink)' } }, img), file, h('button', { class: 'btn sm primary', onclick: async () => {
      if (!file.files[0]) { toast('Choose an image first.', 'bad'); return; }
      const fd = new FormData(); fd.append('logo_file', file.files[0]);
      try { await classic.post('/settings/logo', fd); toast('Logo saved', 'ok'); location.reload(); } catch (e) { toast(e.message, 'bad'); } } }, 'Upload logo')),
    h('div', { class: 'muted small' }, 'The logo also appears on PDFs the workflows make. Up to 2 MB.')));
  return box;
}
async function targetsCard() {
  const d = await api.get('/targets');
  const rows = [...d.rows, ...d.missing.map(p => ({ priority: p, tat_minutes: '', reminder_threshold_minutes: '' }))];
  // each box shows what its minutes mean ("≈ 8 h") underneath, and keeps it up to date as you type
  const nice = (input, out) => { const upd = () => { out.textContent = input.value !== '' ? '≈ ' + minutes(Number(input.value)) : ''; }; input.addEventListener('input', upd); upd(); return h('div', { class: 'tcell' }, input, out); };
  const inputs = rows.map(r => {
    const tat = h('input', { type: 'number', min: 1, value: r.tat_minutes }), rem = h('input', { type: 'number', min: 0, value: r.reminder_threshold_minutes });
    return { r, tat, rem, tatCell: nice(tat, h('span', { class: 'muted small' })), remCell: nice(rem, h('span', { class: 'muted small' })) };
  });
  const oddTimes = h('div');
  const order = ['urgent', 'high', 'medium', 'low'];
  const checkTimes = () => {
    const got = order.map(p => { const i = inputs.find(x => x.r.priority === p); return i && i.tat.value !== '' ? [p, Number(i.tat.value)] : null; }).filter(Boolean);
    const bad = got.filter((x, k) => k > 0 && x[1] < got[k - 1][1]).map(x => pretty(x[0]));
    fill(oddTimes, bad.length ? notice('Check these: ' + bad.join(', ') + ' gets less time than a more urgent priority. Normally Urgent is the shortest and Low the longest.', 'warn') : null);
  };
  inputs.forEach(i => i.tat.addEventListener('input', checkTimes));
  checkTimes();
  return h('div', { class: 'card', style: { gridColumn: '1 / -1' } }, h('div', { class: 'card-h' }, 'Response times'), h('div', { class: 'card-b stack' },
    h('div', { class: 'muted small' }, 'How long each priority gets, and when the reminder goes to whoever has the case. Changes apply to open cases too. A category with its own response time (under “Where complaints go”) uses that instead.'),
    oddTimes,
    h('div', { class: 'tablewrap' }, h('table', { class: 't' }, h('thead', null, h('tr', null, h('th', null, 'Priority'), h('th', null, 'Target (minutes)'), h('th', null, 'Remind after (minutes)'))),
      h('tbody', null, inputs.map(i => h('tr', null, h('td', null, prioBadge(i.r.priority)), h('td', null, i.tatCell), h('td', null, i.remCell)))))),
    h('div', null, h('button', { class: 'btn primary', onclick: async () => {
      try { await api.put('/targets', { rows: inputs.filter(i => i.tat.value !== '').map(i => ({ priority: i.r.priority, tat_minutes: Number(i.tat.value), reminder_threshold_minutes: Number(i.rem.value || 0) })) }); toast('Saved', 'ok'); }
      catch (e) { toast(e.message, 'bad'); } } }, 'Save response times'))));
}
async function sessionCard() {
  const sec = await classic.get('/security').catch(() => null);
  if (!sec) return null;
  const mins = h('input', { type: 'number', min: 5, max: 10080, value: sec.session_ttl_minutes, style: { width: '120px' } });
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Chat sessions'), h('div', { class: 'card-b stack' },
    h('div', { class: 'row' }, 'A conversation with the assistant is forgotten after', mins, 'minutes of silence', h('button', { class: 'btn sm primary', onclick: async () => {
      try { await classic.post('/security/ttl', { minutes: Number(mins.value), org_id: sec.org_id }); toast('Saved', 'ok'); } catch (e) { toast(e.message, 'bad'); } } }, 'Save')),
    h('div', null, h('button', { class: 'btn danger', onclick: async () => { if (!await confirmBox('End every ongoing conversation with the assistant? People can simply start again.', { ok: 'End them all', danger: true })) return; try { await classic.post('/sessions/clear'); toast('Cleared', 'ok'); } catch (e) { toast(e.message, 'bad'); } } }, 'End all conversations now'))));
}
async function statusCard() {
  const d = await api.get('/status');
  const LABELS = { cases: 'Cases', categories: 'Categories', routing: 'Routing rules', parties: 'People on a case', grants: 'Special access', events: 'Change log', seats: 'Seats', residents: 'Residents', audit: 'Chat log', targets: 'Response times', workflow_kind: 'Workflow kinds' };
  return h('details', { class: 'card', style: { gridColumn: '1 / -1' } }, h('summary', { class: 'card-h', style: { cursor: 'pointer' } }, 'Technical details, for support (what this database supports)'), h('div', { class: 'card-b stack' },
    d.caps.cases && !d.case_model_installed ? notice('The case model (categories, routing, seats, special access) is not fully installed in this database, so those screens are hidden. Missing: ' + d.case_model_missing.map(pretty).join(', ') + '.', 'warn') : null,
    h('div', { class: 'chips' }, Object.entries(LABELS).map(([k, l]) => h('span', { class: 'badge ' + (d.caps[k] ? 'ok' : '') }, (d.caps[k] ? '✓ ' : '✗ ') + l))),
    h('div', { class: 'muted small' }, 'Cases count as finished when their status is: ' + d.closed_values.join(', ') + '. ' + plural(d.counts.users, 'person', 'people') + ', ' + plural(d.counts.workflows, 'workflow') + '.')));
}
SECTIONS.settings = {
  title: 'Settings', sub: 'Organisation, response times and housekeeping',
  async render(root) {
    const mine = name => h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'This browser'), h('div', { class: 'card-b stack' },
      h('div', { class: 'row' }, 'Your name', h('input', { type: 'text', value: name, placeholder: 'e.g. Kartik', style: { width: '220px' }, onchange: e => { setName(e.target.value.trim()); toast('Saved on this browser', 'ok'); } })),
      h('div', { class: 'muted small' }, 'Written next to every change you make, so the change log shows who did it. It is a label, not a login.')));
    const parts = await Promise.all([logoCard(), S.boot.caps.targets ? targetsCard() : null, sessionCard(), statusCard()]);
    const [logo, targets, session, status] = parts;
    root.append(h('div', { class: 'grid g2', style: { alignItems: 'start' } }, [logo, session, targets, mine(getName()), status].filter(Boolean)));
  },
};

// ───────────────────────── page shell and start-up ─────────────────────────
const ICONS = { overview: '◧', cases: '☰', people: '☺', routing: '⇄', workflows: '⚙', activity: '✉', settings: '⚒' };
function errorBox(e, retry) {
  return h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, notice(e.message || String(e), 'bad'), retry ? h('div', null, h('button', { class: 'btn', onclick: retry }, 'Try again')) : null));
}
async function renderSection(sec, r) {
  const mine = ++S.renderId;
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.key === sec.key));
  document.querySelector('.side').classList.remove('open');
  const impl = SECTIONS[sec.key];
  const tab = sec.tabs ? (sec.tabs.find(t => t.key === r.tab) || sec.tabs[0]) : null;
  r.tab = tab ? tab.key : '';
  const editing = sec.key === 'workflows' && r.q.w;
  const head = editing ? null : h('div', { class: 'page-head' }, h('div', null, h('h1', null, sec.label), h('div', { class: 'sub' }, impl.sub || '')));
  const tabs = tab && !editing ? h('div', { class: 'tabs' }, sec.tabs.map(t => h('a', { class: 'tab' + (t.key === tab.key ? ' active' : ''), href: href(sec.key, t.key === sec.tabs[0].key ? '' : t.key) }, t.label))) : null;
  const loading = h('div', { class: 'empty' }, 'Loading…'), content = h('div');
  fill(document.getElementById('main'), head, tabs, loading, content);
  document.title = sec.label + ' · ' + S.boot.org.name;
  try { await impl.render(content, r); }
  catch (e) { if (mine === S.renderId) fill(content, errorBox(e, () => { lastSig = ''; onRoute(); })); }
  loading.remove();
  if (mine === S.renderId) window.scrollTo(0, 0);
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
function buildShell(app) {
  const o = S.boot.org;
  const logo = h('span', { class: 'logo' }, o.name[0]);
  if (o.has_logo) classic.get('/settings/logo').then(d => { if (d.logo_url) fill(logo, h('img', { src: d.logo_url, alt: '' })); }).catch(() => {});
  const side = h('aside', { class: 'side' },
    h('div', { class: 'brand' }, logo, h('div', null, o.name, h('small', null, 'Admin'))),
    h('nav', { class: 'nav' }, S.boot.sections.map(s => h('a', { href: href(s.key), 'data-key': s.key }, h('span', { class: 'ic' }, ICONS[s.key] || '•'), s.label))),
    h('div', { class: 'grow' }),
    h('div', { class: 'foot' }, h('a', { href: '/admin/' + encodeURIComponent(ORG) + '/legacy' }, 'Classic dashboard ↗')));
  fill(app, 
    h('div', { class: 'mobilebar' }, h('button', { onclick: () => side.classList.toggle('open') }, '☰'), o.name),
    h('div', { class: 'shell' }, side, h('main', { class: 'main', id: 'main' })));
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
