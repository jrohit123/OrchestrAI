JS = r"""
// ───────────────────────── Overview helpers (the Home screen is in js_home.py) ─────────────────────────
function caseLine(c) {
  return h('div', { class: 'row between', style: { padding: '10px 16px', borderBottom: '1px solid var(--line)', cursor: 'pointer' }, onclick: () => go('cases', '', { case: c.id }) },
    h('div', { style: { minWidth: 0 } },
      h('div', null, h('b', null, c.case_number), ' ', c.title),
      h('div', { class: 'muted small' }, (c.category_label ? (c.category_parent_label ? c.category_parent_label + ' › ' : '') + c.category_label + ' · ' : '') +
        (c.assignee_name ? 'with ' + c.assignee_name : 'not assigned') + ' · ' + ago(c.created_at))),
    h('span', { class: 'row' }, prioBadge(c.priority), c.is_overdue ? badge(relDue(c.due_at), 'bad') : null));
}
function trendChart(points) {
  const W = 560, H = 100, n = points.length, bw = W / n;
  const max = Math.max(1, ...points.flatMap(p => [p.created, p.closed]));
  const svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'spark', preserveAspectRatio: 'none' });
  points.forEach((p, i) => {
    const a = p.created / max * H, b = p.closed / max * H, x = i * bw;
    svg.append(svgEl('rect', { x: x + 3, y: H - a, width: Math.max(2, bw / 2 - 4), height: a, fill: 'var(--brand)', rx: 2 }, svgEl('title', {}, fmtD(p.day) + ': ' + p.created + ' new')));
    svg.append(svgEl('rect', { x: x + bw / 2, y: H - b, width: Math.max(2, bw / 2 - 4), height: b, fill: 'var(--ok)', rx: 2 }, svgEl('title', {}, fmtD(p.day) + ': ' + p.closed + ' closed')));
  });
  return svg;
}
// ───────────────────────── Cases ─────────────────────────
// the same person can hold several roles on a case (Level 2, then Handling it): show them once
function onePerPerson(parties) {
  const order = ['assignee', 'level2', 'helper', 'requester', 'watcher'];
  const by = new Map();
  const slot = p => { if (!by.has(p.user_id)) by.set(p.user_id, { user_id: p.user_id, name: p.name, reachable: p.reachable, roles: [], earlier: false }); return by.get(p.user_id); };
  parties.forEach(p => { const e = slot(p); if (p.ended_at) e.earlier = true; else if (!e.roles.some(r => r.key === p.party_role)) e.roles.push({ key: p.party_role, text: PARTY[p.party_role] || pretty(p.party_role), tone: p.party_role === 'assignee' ? 'info' : '', rank: order.indexOf(p.party_role) }); });
  return [...by.values()].map(e => { if (!e.roles.length && e.earlier) e.roles.push({ key: 'earlier', text: 'Handled earlier', tone: '', rank: 9 }); e.roles.sort((x, y) => x.rank - y.rank); e.rank = e.roles.length ? e.roles[0].rank : 9; return e; }).sort((x, y) => x.rank - y.rank);
}
const PARTY = { requester: 'Raised it', assignee: 'Handling it', level2: 'Level 2', helper: 'Helping', watcher: 'Watching' };
function catOptions(lk, any, none) {
  const kids = {};
  lk.categories.forEach(c => (kids[c.parent_id || ''] = kids[c.parent_id || ''] || []).push(c));
  Object.values(kids).forEach(a => a.sort((x, y) => x.sort_order - y.sort_order || x.label.localeCompare(y.label)));
  const out = [];
  if (any !== null) out.push(['', any || 'Any category']);
  if (none) out.push(['none', 'No category']);
  (function walk(pid, depth) { (kids[pid] || []).forEach(c => { out.push([c.id, '  '.repeat(depth) + (depth ? '› ' : '') + c.label + (c.is_active ? '' : ' (hidden)')]); walk(c.id, depth + 1); }); })('', 0);
  return out;
}
function timelineItem(a, caseId) {
  const p = a.payload || {};
  let text = null, extra = null, picture = null;
  switch (a.activity_type) {
    case 'evidence':
      text = p.photo_id ? 'Added a photo' : 'Added a photo (kept on Telegram)';
      if (p.photo_id && caseId) { const src = BASE + '/cases/' + caseId + '/photos/' + p.photo_id; picture = h('a', { href: src, target: '_blank', rel: 'noopener' }, h('img', { class: 'tl-photo', src, alt: 'Photo sent with the request', loading: 'lazy' })); }
      break;
    case 'comment': text = 'Added an update'; extra = p.text; break;
    case 'assignment': text = 'Handed to ' + (p.to_name || 'someone') + (p.from_name ? ' (from ' + p.from_name + ')' : ''); extra = p.note; break;
    case 'status_change': case 'reopen': text = (a.activity_type === 'reopen' ? 'Reopened' : 'Status') + ' → ' + pretty(p.to || ''); extra = p.closing_note || p.note; break;
    case 'priority_change': text = 'Priority ' + (p.from ? pretty(p.from) + ' → ' : '→ ') + pretty(p.to); extra = p.note; break;
    case 'category_change': text = 'Category ' + (p.from_label || 'none') + ' → ' + (p.to_label || 'none'); break;
    default: {
      text = pretty(a.activity_type);
      const rest = Object.entries(p).filter(([k]) => k !== 'by');
      if (rest.length) extra = rest.map(([k, v]) => pretty(k) + ': ' + (typeof v === 'object' ? JSON.stringify(v) : v)).join('\n');
    }
  }
  return h('div', { class: 'tl ' + a.activity_type }, h('span', { class: 'dot' }),
    h('div', null, h('div', null, h('b', null, text)), h('div', { class: 'when' }, (a.actor_name || p.by || 'System') + ' · ' + fmtDT(a.created_at)), extra ? h('div', { class: 'quote' }, extra) : null, picture));
}
// Assign: the dashboard asks the organisation's own flow (set under Settings > case buttons) to hand the case over
function assignDialog(c) {
  let pick = null;
  const who = personPicker({ placeholder: 'Start typing a name', reachable: true, onChange: p => { pick = p; } });
  const note = h('textarea', { rows: 3, maxlength: 500, placeholder: 'A note for them (optional)' });
  modal({
    title: 'Assign ' + c.case_number,
    body: h('div', { class: 'stack' }, h('div', { class: 'muted small' }, c.title),
      field('Give it to', who.el, 'Only people the chat bot can message are listed, so they hear about it.'), field('Note', note)),
    actions: [{ label: 'Cancel' }, { label: 'Assign', primary: true, run: async () => {
      if (!pick) throw new Error('Choose who gets the case.');
      const r = await api.post('/cases/' + c.id + '/assign', { user_id: pick.id, note: note.value.trim() || undefined });
      toast(r.message, 'ok');
      refreshHints(true);
      if (drawer && drawerKey === 'case:' + c.id) showCase(c.id);
      lastSig = ''; onRoute();
    } }],
  });
}
function assignCard(c, as) {
  if (!as.on) return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Hand it to someone'),
    h('div', { class: 'card-b muted' }, 'Assigning from here is switched off, because the “' + as.name + '” flow is off. ' + (isSuper() ? 'Switch it on under Flows.' : 'Ask a super admin to switch it on.')));
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, c.assigned_to_id ? 'Hand it to someone else' : 'Give it to someone'),
    h('div', { class: 'card-b row between' }, h('span', { class: 'muted' }, c.assignee_name ? 'It is with ' + c.assignee_name + ' now.' : 'Nobody has it yet.'),
      h('button', { class: 'btn primary', type: 'button', onclick: () => assignDialog(c) }, icon('usercheck', 'sm'), c.assigned_to_id ? 'Assign to someone else' : 'Assign')));
}
const canAssign = () => !!(S.boot.buttons && S.boot.buttons.assign && S.boot.buttons.assign.on);
async function showCase(id) {
  drawerKey = 'case:' + id;
  const dr = openDrawer('Loading…', h('div', { class: 'empty' }, 'Loading…'));
  try {
    const d = await api.get('/cases/' + id);
    if (!drawer || drawer !== dr) return;
    const c = d.case, closed = (S.boot.enums.closed || []).includes(c.status);
    fill(dr.titleEl, h('div', { class: 'muted small' }, c.case_number), c.title, h('div', { class: 'row', style: { marginTop: '6px' } }, statusBadge(c.status), prioBadge(c.priority), c.is_overdue ? badge('Past target time', 'bad') : null));
    const facts = h('dl', { class: 'kv' },
      h('dt', null, 'Raised by'), h('dd', null, person(c.complainant_id, c.complainant_name)),
      h('dt', null, 'Handled by'), h('dd', null, person(c.assigned_to_id, c.assignee_name, { none: 'Not assigned' })),
      S.boot.caps.case_category ? [h('dt', null, 'Category'), h('dd', null, c.category_label ? (c.category_parent_label ? c.category_parent_label + ' › ' : '') + c.category_label : h('span', { class: 'muted' }, 'None yet'))] : null,
      c.location ? [h('dt', null, 'Where'), h('dd', null, c.location)] : null,
      h('dt', null, 'Raised'), h('dd', null, fmtDT(c.created_at) + ' (' + ago(c.created_at) + ')'),
      h('dt', null, closed ? 'Was due' : 'Due'), h('dd', null, c.due_at ? fmtDT(c.due_at) + (closed ? '' : ' (' + relDue(c.due_at) + ')') : '—'),
      closed ? [h('dt', null, 'Closed'), h('dd', null, fmtDT(c.closed_at))] : null,
      Object.entries(c.custom_fields || {}).map(([k, v]) => [h('dt', null, pretty(k)), h('dd', null, typeof v === 'object' ? JSON.stringify(v) : String(v))]));
    const body = [h('div', { class: 'card' }, h('div', { class: 'card-b' }, facts))];
    if (S.boot.caps.tat_clock) body.push(await clockCard(c));
    if (S.boot.caps.case_model && isSuper()) {
      const r = d.routing;
      let inner;
      if (!c.category_id) inner = h('span', { class: 'muted' }, 'This case has no kind of complaint yet, so no case rule can apply.');
      else if (!r) inner = h('span', null, 'No case rule matches this kind of complaint yet. ', h('a', { href: href('cases', 'teams') }, 'Add one'));
      else inner = h('div', { class: 'stack' },
        h('div', null, 'Rule ', h('b', null, '“' + r.rule_name + '”'), ' would send it to ', r.assignee_name ? h('b', null, r.assignee_name) : h('b', { style: { color: 'var(--bad)' } }, 'nobody (no one it points to can be messaged)'),
          r.via === 'backup' ? ' (the backup, because the first choice is unavailable)' : '', r.level2.length ? ', with ' + r.level2.map(x => x.name).join(', ') + ' as level 2' : '', '.'),
        r.target_minutes ? h('div', { class: 'muted small' }, 'Response target from the rule: ' + minutes(r.target_minutes)) : null,
        r.assignee_id && r.assignee_id !== c.assigned_to_id ? h('div', { class: 'muted small' }, 'That is different from who has it now.') : null);
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What the case rules say'), h('div', { class: 'card-b' }, inner)));
    }
    body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'People on this case'),
      d.parties.length ? h('div', { class: 'card-b stack' }, onePerPerson(d.parties).map(p => h('div', { class: 'row between' },
        person(p.user_id, p.name), h('span', { class: 'row' }, p.roles.map(r => badge(r.text, r.tone)), p.reachable ? null : badge('not on Telegram', 'warn'))))) : empty('Nobody yet', '')));
    if (c.description) body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What was reported'), h('div', { class: 'card-b' }, h('div', { style: { whiteSpace: 'pre-wrap' } }, c.description))));
    body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Timeline'),
      h('div', { class: 'card-b' }, d.timeline.length ? h('div', { class: 'timeline' }, d.timeline.map(a => timelineItem(a, c.id))) : h('span', { class: 'muted' }, 'Nothing has happened on this case yet.'))));
    const as = S.boot.buttons && S.boot.buttons.assign;
    if (as && !closed) body.push(assignCard(c, as));
    body.push(h('div', { class: 'muted small' }, as ? 'To update or close a case, use its flow in ' + chatWord() + '.' : 'To assign, update or close a case, use its flow in ' + chatWord() + '. The dashboard only shows cases.'));
    clear(dr.bodyEl); add(dr.bodyEl, body);
  } catch (e) { if (drawer === dr) { clear(dr.bodyEl); dr.bodyEl.append(notice(e.message, 'bad')); dr.titleEl.textContent = 'Case'; } }
}
// Cases: only the daily work. Search, Open / Closed and one Filters button; how cases are sent and timed is set up under Case rules.
// A ticket's time bar: how much of its time to fix it has used (green, amber from 40%, red when late, grey when paused,
// dashed when it has no time limit). The small dots are the steps of its reminder plan; a filled one has passed.
function timeBar(c, big) {
  const k = c.clock;
  if (!k) return null;
  const closedNow = (S.boot.enums.closed || []).includes(c.status);
  const pct = k.percent || 0;
  const tone = closedNow ? 'done' : k.no_limit ? 'none' : k.paused ? 'paused' : pct >= 100 ? 'late' : pct >= 40 ? 'warn' : 'ok';
  const text = closedNow ? 'Closed after ' + minutes(k.elapsed_minutes)
    : k.no_limit ? 'No time limit · open ' + minutes(k.elapsed_minutes)
    : k.paused ? 'Clock paused · ' + pct + '% used'
    : pct >= 100 ? 'Late by ' + minutes(Math.max(1, k.elapsed_minutes - k.total_minutes))
    : pct + '% used · ' + minutes(Math.max(1, k.total_minutes - k.elapsed_minutes)) + ' left';
  const marks = k.no_limit ? [] : (c.marks || []).filter(m => m < 100).map(m => h('span', { class: 'tmark' + (pct >= m ? ' done' : ''), style: { left: m + '%' }, 'data-tip': m + '% of the time to fix: a reminder step' }));
  return h('div', { class: 'tat' + (big ? ' big' : ''), title: k.total_minutes ? 'Time to fix: ' + minutes(k.total_minutes) : '' },
    h('div', { class: 'tbar ' + tone }, h('i', { style: { width: (k.no_limit ? 100 : Math.min(100, pct)) + '%' } }), marks),
    h('div', { class: 'ttxt ' + tone }, text));
}

// A ticket's clock, on its page: how much of its time to fix is used, and every step of its reminder plan (done, skipped,
// next, later) with when it ran or will run. From GET /cases/{id}/clock; nothing is worked out here.
const CLOCK_STATE = { done: ['✓', 'Done'], skipped: ['⏭', 'Not needed'], failed: ['⚠', 'Nobody could be reached'], next: ['⏳', 'Next'], later: ['○', 'Later'] };
async function clockCard(c) {
  const holder = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Time to fix'), h('div', { class: 'card-b muted small' }, 'Loading…'));
  (async () => {
    let k;
    try { k = await api.get('/cases/' + c.id + '/clock'); } catch (e) { holder.remove(); return; }
    const noLimit = k.total_minutes == null;
    const row = { status: c.status, clock: { percent: k.percent == null ? 0 : Math.round(k.percent), total_minutes: k.total_minutes, elapsed_minutes: k.elapsed_minutes, paused: !!k.paused, no_limit: noLimit },
      marks: (k.steps || []).filter(x => x.at_percent != null && x.at_percent <= 100).map(x => Number(x.at_percent)) };
    const words = a => (typeof remActWords === 'function' ? remActWords(a, []) : ['•', a.do]).join(' ');
    const steps = (k.steps || []).map(x => {
      const [ic, label] = CLOCK_STATE[x.state] || ['•', x.state];
      const when = x.when ? fmtDT(x.when) : '';
      const head = x.every_minutes ? 'Every ' + minutes(x.every_minutes) : Number(x.at_percent) + '%';
      return h('div', { class: 'clk ' + x.state }, h('span', { class: 'clk-i' }, ic),
        h('div', { class: 'grow' }, h('b', null, head), when ? ' · ' + when : '', x.only_if && x.only_if !== 'always' ? h('span', { class: 'muted' }, ' · only if ' + (REM_ONLY[x.only_if] || x.only_if)) : null,
          h('div', { class: 'small' }, (x.actions || []).map(words).join(' · ')),
          x.state === 'skipped' && x.detail && x.detail.why ? h('div', { class: 'muted small' }, 'Not needed: ' + x.detail.why + '.') : null,
          x.state === 'done' && x.detail && x.detail.told && x.detail.told.length ? h('div', { class: 'muted small' }, 'Told: ' + x.detail.told.join(', ') + (x.detail.moved_to ? ' · now with ' + x.detail.moved_to : '')) : null),
        h('span', { class: 'muted small' }, label));
    });
    fill(holder, h('div', { class: 'card-h' }, 'Time to fix', h('span', { class: 'muted small' }, noLimit ? 'No time limit' : minutes(k.total_minutes) + (k.due_at ? ' · due ' + fmtDT(k.due_at) : ''))),
      h('div', { class: 'card-b stack s8' }, timeBar(row, true),
        k.plan ? h('div', { class: 'muted small' }, 'Reminder plan: ', h('a', { href: href('cases', 'reminders') }, k.plan.name)) : h('div', { class: 'muted small' }, 'No reminder plan applies.'),
        steps));
  })();
  return holder;
}

// Tickets: the list, and (as tabs) everything about how tickets are handled, which used to be the Case rules screen
const TICKET_TABS = {
  list: ['Tickets', 'Everything people have reported, and where it stands'],
  teams: ['Who handles what', 'Who gets each kind of ticket, who backs them up, and who is kept informed.'],
  reminders: ['Reminders', 'When the chat bot reminds, tells the backup or hands a ticket over: as a share of each ticket’s time to fix.'],
  categories: ['Kinds of ticket', 'The kinds people choose from, and the words that sort a ticket into one.'],
  rules: ['Rules in detail', 'Every rule, its order and its exceptions. Most days Who handles what is all you need.'],
  times: ['Response times', 'How long each urgency gets before a ticket counts as late.'],
};
SECTIONS.cases = {
  heading: (sec, r) => { const t = TICKET_TABS[r.tab] || TICKET_TABS.list; return { title: t[0], sub: t[1] }; },
  async render(root, route) {
    if (route.tab === 'reminders') return renderReminders(root);
    if (route.tab && route.tab !== 'list') return SECTIONS.rules.render(root, route);
    const mine = S.renderId;
    const lk = S.boot.caps.case_category ? await getLookups() : { categories: [] };
    const closedList = S.boot.enums.closed || [], closedVal = closedList.join(',');
    const q = { sort: 'newest', ...route.q }; delete q.case; delete q.person;
    q.page = Number(q.page || 1);
    const bar = h('div', { class: 'filters' }), chips = h('div', { class: 'chips', style: { marginBottom: '12px' } }), out = h('div', { class: 'card' });
    root.append(bar, chips, out);
    const update = patch => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
    const search = h('input', { type: 'search', placeholder: 'Search number, title, place or person', value: q.q || '', style: { flex: 1, minWidth: '240px', maxWidth: '400px' }, 'aria-label': 'Search cases' });
    search.addEventListener('input', debounce(() => update({ q: search.value }), 300));
    const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Which cases' });
    const filtersBtn = h('button', { class: 'btn', type: 'button', 'data-popkeep': '1', onclick: e => openFilters(e.currentTarget) });
    const sort = sel([['newest', 'Newest first'], ['oldest', 'Oldest first'], ['due', 'Due soonest'], ['priority', 'Most urgent first']], q.sort, { class: 'select sm', style: { width: 'auto' }, 'aria-label': 'Sort', onchange: e => update({ sort: e.target.value }) });
    add(bar, [search, seg, filtersBtn, h('span', { class: 'sp' }), sort]);

    // everything beyond search and Open / Closed lives behind one button
    const extra = () => ['priority', 'category', 'unassigned', 'overdue'].filter(k => q[k]).length + (q.assignee && q.assignee !== 'none' ? 1 : 0) + (q.status && q.status !== 'open' && q.status !== closedVal ? 1 : 0);
    function openFilters(anchor) {
      const statuses = S.boot.enums.statuses || [];
      const who = personPicker({ placeholder: 'Start typing a name', anyStatus: true, initial: q.assignee && q.assignee !== 'none' ? { id: q.assignee, name: q.assignee_name || 'Selected person' } : null,
        onChange: p => update({ assignee: p ? p.id : '', assignee_name: p ? p.name : '' }) });
      const flag = (key, label) => { const cb = h('input', { type: 'checkbox', checked: !!q[key] }); cb.addEventListener('change', () => update({ [key]: cb.checked ? '1' : '' })); return h('label', { class: 'row small flat' }, cb, label); };
      openPop(anchor, h('div', { class: 'stack s8', style: { padding: '10px' } },
        statuses.length ? field('Status', sel([['', 'Any'], ['open', 'Open (not finished)'], ...statuses.map(s => [s, pretty(s)])], q.status || '', { onchange: e => update({ status: e.target.value }) })) : null,
        field('Priority', sel([['', 'Any'], ...(S.boot.enums.priorities || []).map(p => [p, pretty(p)])], q.priority || '', { onchange: e => update({ priority: e.target.value }) })),
        S.boot.caps.case_category ? field('Kind of complaint', sel(catOptions(lk, 'Any', true), q.category || '', { onchange: e => update({ category: e.target.value }) })) : null,
        field('Who has it', who.el),
        h('div', { class: 'stack s8' }, flag('unassigned', 'Not assigned'), flag('overdue', 'Past target time'))), { width: 320 });
    }
    function drawChips() {
      const list = [];
      const chip = (label, patch) => list.push(h('span', { class: 'chip' }, label, h('button', { class: 'x', type: 'button', 'aria-label': 'Remove ' + label, style: { fontSize: '16px', padding: '0 2px' }, onclick: () => update(patch) }, '×')));
      if (q.status && q.status !== 'open' && q.status !== closedVal) chip('Status: ' + pretty(q.status), { status: '' });
      if (q.priority) chip('Priority: ' + pretty(q.priority), { priority: '' });
      if (q.category) chip('Kind: ' + (q.category === 'none' ? 'none yet' : ((lk.categories.find(c => c.id === q.category) || {}).label || 'chosen')), { category: '' });
      if (q.assignee && q.assignee !== 'none') chip('Who has it: ' + (q.assignee_name || 'chosen person'), { assignee: '', assignee_name: '' });
      if (q.unassigned) chip('Not assigned', { unassigned: '' });
      if (q.overdue) chip('Past target time', { overdue: '' });
      fill(chips, list, list.length ? h('button', { class: 'btn ghost sm', type: 'button', onclick: () => { closePop(); search.value = ''; update({ status: '', priority: '', category: '', assignee: '', assignee_name: '', q: '', overdue: '', unassigned: '' }); } }, 'Clear all') : null);
      chips.style.display = list.length ? '' : 'none';
      fill(filtersBtn, icon('filter', 'sm'), extra() ? 'Filters · ' + extra() : 'Filters');
    }
    async function load() {
      if (mine !== S.renderId) return;
      setQuery({ ...q, sort: q.sort === 'newest' ? '' : q.sort });
      drawChips();
      fill(out, h('div', { class: 'empty' }, 'Loading…'));
      try {
        const d = await api.get('/cases', { status: q.status, priority: q.priority, category: q.category, assignee: q.assignee, q: q.q, overdue: q.overdue ? true : '', unassigned: q.unassigned ? true : '', sort: q.sort, page: q.page, page_size: 25 });
        const total = Object.values(d.status_counts).reduce((a, b) => a + b, 0);
        const closed = closedList;
        const openN = Object.entries(d.status_counts).filter(([s]) => !closed.includes(s)).reduce((a, [, n]) => a + n, 0);
        const part = (label, n, val) => h('button', { type: 'button', 'aria-pressed': String((q.status || '') === val), onclick: () => update({ status: val }) }, label + ' ', h('span', { style: { opacity: .7 } }, n));
        fill(seg, part('All', total, ''), part('Open', openN, 'open'), closed.length ? part('Closed', total - openN, closedVal) : null);
        const dot = p => h('span', { class: 'pd ' + prioTone(p) });
        const c0 = d.rows[0];   // a database with the clock (housing-0013) shows the time bar instead of the due date
        fill(out,
          table([
            { label: 'Case', cls: 'wide', render: c => h('div', { class: 'cs' }, h('b', null, c.case_number), ' ', c.title,
              h('div', { class: 'muted small' }, [c.priority ? [dot(c.priority), pretty(c.priority)] : null, c.category_label ? (c.category_parent_label ? c.category_parent_label + ' › ' : '') + c.category_label : null, c.location, c.complainant_name ? 'raised by ' + c.complainant_name : null].filter(Boolean).flatMap((x, i) => [i ? ' · ' : null, x]))) },
            { label: 'Status', render: c => statusBadge(c.status) },
            { label: 'Who has it', render: c => c.assignee_name ? person(null, c.assignee_name) : h('span', { class: 'row' }, badge('Not assigned', 'warn'), canAssign() && !closed.includes(c.status) ? h('button', { class: 'btn sm', type: 'button', onclick: e => { e.stopPropagation(); assignDialog(c); } }, 'Assign') : null) },
            c0 && c0.clock ? { label: 'Time to fix', cls: 'tatcol', render: c => timeBar(c) }
              : { label: 'Due', render: c => closed.includes(c.status) ? h('span', { class: 'muted' }, 'closed ' + fmtD(c.closed_at)) : h('span', { style: c.is_overdue ? { color: 'var(--bad)', fontWeight: 600 } : null }, relDue(c.due_at)) },
          ], d.rows, { onRow: c => go('cases', '', { ...q, case: c.id }), emptyTitle: 'No cases match', emptyText: 'Try removing a filter.' }),
          pager(d.total, d.page, d.page_size, p => update({ page: p })));
      } catch (e) { fill(out, notice(e.message, 'bad')); }
    }
    await load();
  },
};

"""
