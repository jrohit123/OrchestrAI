JS = r"""
// ───────────────────────── Activity & chats ─────────────────────────
async function transcriptModal(sessionId, fallback) {
  let rows = [];
  if (sessionId) rows = (await api.get('/activity/session', { session_id: sessionId })).rows;
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
  const first = await api.get('/activity', { page_size: 1 });
  const who = sel([['', 'Everyone'], ...(first.users || []).map(u => [u.id, u.name])], q.user || '', { onchange: e => update({ user: e.target.value }) });
  const text = h('input', { type: 'search', placeholder: 'Search…', value: q.q || '' });
  text.addEventListener('input', debounce(() => update({ q: text.value }), 300));
  bar.append(who, text);
  async function load() {
    if (mine !== S.renderId) return;
    setQuery(q);
    fill(out, h('div', { class: 'empty' }, 'Loading…'));
    try {
      const d = await api.get('/activity', { user_id: q.user, search: q.q, page: q.page, page_size: 20 });
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
SECTIONS.conversations = {
  title: 'Conversations', sub: 'What people asked the assistant, and how it answered',
  async render(root, route) { return renderChats(root, route); },
};
SECTIONS.activity = {
  title: 'Activity log', sub: 'Everything the assistant did, and what was changed from this dashboard',
  async render(root, route) {
    if (route.tab === 'changes') return renderChanges(root, route);
    return renderAll(root, route);
  },
};

// ───────────────────────── Settings ─────────────────────────
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


// ───────────────────────── Cases: the list, with routing and response times as tabs ─────────────────────────
const casesList = SECTIONS.cases.render;
SECTIONS.cases.render = async function (root, route) {
  if (route.tab === 'rules' || route.tab === 'categories') return SECTIONS.routing.render(root, route);
  if (route.tab === 'times') { root.append(h('div', { class: 'grid' }, await targetsCard())); return; }
  return casesList(root, route);
};
"""
