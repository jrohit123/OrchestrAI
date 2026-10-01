JS = r"""
// ───────────────────────── Workflows ─────────────────────────
const refName = x => x ? pretty(String(x).replace(/^\$(fields|user|case|computed)\./, '').replace(/\.(phone|name|id)$/, '')) : 'the person';
function describeStep(s) {
  const p = s.params || {}, t = p.table ? pretty(p.table).toLowerCase() : 'record';
  const known = {
    'resolve_entity': () => 'Find the ' + t + ' that matches “' + refName(p.name_from) + '”',
    'derive_field': () => 'Work out ' + pretty(p.field || 'a value').toLowerCase(),
    'compute': () => 'Do a calculation',
    'conflict_check': () => 'Check for clashes before saving',
    'require_permission': () => 'Check this person is allowed to do it',
    'otp_gate': () => 'Ask for a one-time code',
    'approval_gate': () => 'Ask someone to approve first',
    'db.insert_row': () => 'Save a new ' + t,
    'db.update_row': () => 'Update the ' + t,
    'db.upsert_row': () => 'Save or update the ' + t,
    'db.delete_row': () => 'Delete from ' + t,
    'notify.user': () => 'Send a message to ' + refName(p.to),
    'notify.whatsapp': () => 'Send the confirmation message',
    'pdf.generate': () => 'Make a PDF',
    'ai_price_interpret': () => 'Understand the price the person typed',
  };
  return (known[s.op] ? known[s.op]() : pretty(s.op)) + (s.when ? ' (only in some cases)' : '');
}
async function stepsModal(w) {
  const d = await api.get('/workflows/' + w.id);
  const fields = Object.entries(d.entity_schema || {});
  modal({ title: w.name, wide: true, body: h('div', { class: 'stack' },
    d.description ? h('div', null, d.description) : null,
    h('div', { class: 'muted small' }, 'Technical name: ' + d.intent_key + ' · ' + (d.workflow_type === 'read' ? 'only reads information' : 'does something') + (d.training_phrases.length ? ' · ' + plural(d.training_phrases.length, 'example phrase') : '')),
    fields.length ? h('div', null, h('b', null, 'What it asks for'), h('div', { class: 'chips', style: { marginTop: '6px' } }, fields.map(([k, v]) => h('span', { class: 'chip' }, (v && v.label) || pretty(k))))) : null,
    d.gates.length ? h('div', null, h('b', null, 'Safeguards'), h('div', { class: 'muted small' }, d.gates.map(g => pretty(g.type || 'rule')).join(', '))) : null,
    h('div', null, h('b', null, 'What it does, in order'), d.steps.length ? h('ol', { style: { margin: '6px 0 0', paddingLeft: '20px' } }, d.steps.map(s => h('li', { style: { margin: '4px 0' } }, describeStep(s), ' ', h('span', { class: 'muted small' }, s.op)))) : h('div', { class: 'muted' }, d.workflow_type === 'read' ? 'It answers by looking things up with a saved query, so it has no steps that change anything.' : 'No steps.')),
    h('div', { class: 'muted small' }, 'To change what it does, use the workflow builder in the classic dashboard.')), actions: [{ label: 'Close' }] });
}
function accessModal(w, roles, done) {
  const boxes = roles.map(r => { const cb = h('input', { type: 'checkbox', checked: w.granted_roles.includes(r.name) }); return { r, cb, el: h('label', { class: 'row' }, cb, r.name) }; });
  modal({ title: 'Who can use “' + w.name + '”', body: h('div', { class: 'stack' }, boxes.map(b => b.el), h('div', { class: 'muted small' }, 'Only people with one of these roles see it in their menu or can run it.')),
    actions: [{ label: 'Cancel' }, { label: 'Save', primary: true, run: async () => { await api.put('/workflows/' + w.id + '/roles', { roles: boxes.filter(b => b.cb.checked).map(b => b.r.name) }); toast('Saved', 'ok'); done(); } }] });
}
SECTIONS.workflows = {
  title: 'Workflows', sub: 'What people can ask the assistant to do, and who may use it',
  async render(root) {
    const d = await api.get('/workflows');
    const again = () => { clear(root); SECTIONS.workflows.render(root); };
    root.append(h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('div', { class: 'muted' }, 'Switch a workflow off to hide it from the menu and the assistant without deleting it.'),
      h('a', { class: 'btn', href: '/admin/' + encodeURIComponent(ORG) + '/legacy', target: '_blank', rel: 'noopener' }, 'Build or change a workflow ↗')));
    const kindOn = S.boot.caps.workflow_kind;
    root.append(h('div', { class: 'card' }, table([
      { label: 'On', render: w => switchEl(w.is_active, async v => { await api.post('/workflows/' + w.id + '/active', { is_active: v }); w.is_active = v; }) },
      { label: 'Workflow', render: w => h('div', null, h('b', null, w.name), h('div', { class: 'muted small' }, w.description || w.intent_key), w.slash_command ? h('div', { class: 'muted small' }, '/' + w.slash_command) : null) },
      kindOn ? { label: 'Kind', render: w => badge(w.kind === 'case_action' ? 'Case action' : pretty(w.kind), w.kind === 'workflow' ? '' : 'violet') } : null,
      { label: 'Who can use it', render: w => h('div', { class: 'row' }, w.granted_roles.length ? h('div', { class: 'chips' }, w.granted_roles.map(r => badge(r, 'brand'))) : h('span', { class: 'muted' }, w.kind === 'block' ? 'Used by other workflows' : 'Nobody'),
        w.kind === 'block' ? null : h('button', { class: 'btn sm ghost', onclick: () => accessModal(w, d.roles, again) }, 'Change')) },
      { label: 'Steps', cls: 'num', render: w => w.step_count },
      { label: 'Last used', render: w => w.last_run ? ago(w.last_run) : h('span', { class: 'muted' }, 'never') },
      S.boot.caps.cases ? { label: 'Cases made', cls: 'num', render: w => w.cases_made || '—' } : null,
      { label: '', render: w => h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => stepsModal(w).catch(e => toast(e.message, 'bad')) }, 'See steps'),
        h('button', { class: 'btn sm danger', onclick: async () => { if (!await confirmBox('Delete “' + w.name + '”? This cannot be undone. To just hide it, switch it off instead.', { ok: 'Delete', danger: true })) return; try { await api.del('/workflows/' + w.id); toast('Deleted', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } } }, 'Delete')) },
    ].filter(Boolean), d.rows, { emptyTitle: 'No workflows yet', emptyText: 'Create the first one in the workflow builder.' })));
  },
};

// ───────────────────────── Activity & chats ─────────────────────────
async function transcriptModal(sessionId, fallback) {
  let rows = [];
  if (sessionId) rows = (await classic.get('/activity/session', { session_id: sessionId })).rows;
  else if (fallback) rows = [fallback];
  modal({ title: 'Conversation', wide: true, body: rows.length ? h('div', { class: 'stack' }, rows.map(r => h('div', null,
    h('div', { class: 'muted small' }, (r.user_name || 'Person') + ' · ' + fmtDT(r.created_at)),
    r.input_text ? h('div', { class: 'quote' }, r.input_text) : null,
    r.response_text ? h('div', { class: 'quote', style: { background: 'var(--brand-soft)' } }, r.response_text) : null))) : empty('Nothing recorded', ''), actions: [{ label: 'Close' }] });
}
const clip = (s, n) => !s ? '' : (s.length > n ? s.slice(0, n) + '…' : s);
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
        h('div', { class: 'chips' }, (c.workflows || []).map(w => badge(w, 'brand'))))) : empty('No conversations match', ''),
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
  const inputs = rows.map(r => ({ r, tat: h('input', { type: 'number', min: 1, value: r.tat_minutes, style: { width: '110px' } }), rem: h('input', { type: 'number', min: 0, value: r.reminder_threshold_minutes, style: { width: '110px' } }) }));
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Response times'), h('div', { class: 'card-b stack' },
    h('div', { class: 'muted small' }, 'How long each priority gets, and when the reminder goes to whoever has the case. Changes apply to open cases too.'),
    h('table', { class: 't' }, h('thead', null, h('tr', null, h('th', null, 'Priority'), h('th', null, 'Target (minutes)'), h('th', null, 'Remind after (minutes)'), h('th', null, ''))),
      h('tbody', null, inputs.map(i => h('tr', null, h('td', null, prioBadge(i.r.priority)), h('td', null, i.tat), h('td', null, i.rem), h('td', { class: 'muted small' }, i.tat.value ? '≈ ' + minutes(Number(i.tat.value)) : ''))))),
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
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What this organisation’s database supports'), h('div', { class: 'card-b stack' },
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
    root.append(h('div', { class: 'grid g2', style: { alignItems: 'start' } }, [...parts, mine(getName())].filter(Boolean)));
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
  const head = h('div', { class: 'page-head' }, h('div', null, h('h1', null, sec.label), h('div', { class: 'sub' }, impl.sub || '')));
  const tabs = tab ? h('div', { class: 'tabs' }, sec.tabs.map(t => h('a', { class: 'tab' + (t.key === tab.key ? ' active' : ''), href: href(sec.key, t.key === sec.tabs[0].key ? '' : t.key) }, t.label))) : null;
  const content = h('div', null, h('div', { class: 'empty' }, 'Loading…'));
  fill(document.getElementById('main'), head, tabs, content);
  document.title = sec.label + ' · ' + S.boot.org.name;
  try { clear(content); await impl.render(content, r); }
  catch (e) { if (mine === S.renderId) fill(content, errorBox(e, () => { lastSig = ''; onRoute(); })); }
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
  if (sig !== lastSig) { lastSig = sig; await renderSection(sec, r); }
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
