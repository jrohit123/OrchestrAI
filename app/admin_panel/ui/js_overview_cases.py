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
function timelineItem(a) {
  const p = a.payload || {};
  let text = null, extra = null;
  switch (a.activity_type) {
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
    h('div', null, h('div', null, h('b', null, text)), h('div', { class: 'when' }, (a.actor_name || p.by || 'System') + ' · ' + fmtDT(a.created_at)), extra ? h('div', { class: 'quote' }, extra) : null));
}
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
    if (S.boot.caps.case_model) {
      const r = d.routing;
      let inner;
      if (!c.category_id) inner = h('span', { class: 'muted' }, 'This case has no kind of complaint yet, so no case rule can apply.');
      else if (!r) inner = h('span', null, 'No case rule matches this kind of complaint yet. ', h('a', { href: href('rules') }, 'Add one'));
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
      h('div', { class: 'card-b' }, d.timeline.length ? h('div', { class: 'timeline' }, d.timeline.map(timelineItem)) : h('span', { class: 'muted' }, 'Nothing has happened on this case yet.'))));
    body.push(h('div', { class: 'muted small' }, 'To assign, update or close a case, use its flow in ' + chatWord() + '. The dashboard only shows cases.'));
    clear(dr.bodyEl); add(dr.bodyEl, body);
  } catch (e) { if (drawer === dr) { clear(dr.bodyEl); dr.bodyEl.append(notice(e.message, 'bad')); dr.titleEl.textContent = 'Case'; } }
}
// Cases: only the daily work. Search, Open / Closed and one Filters button; how cases are sent and timed is set up under Case rules.
SECTIONS.cases = {
  title: 'Cases', sub: 'Everything people have reported, and where it stands',
  actions: () => S.boot.caps.case_model ? h('a', { class: 'btn ghost', href: href('rules') }, 'How cases are handled', icon('arrowr', 'sm')) : null,
  async render(root, route) {
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
        fill(out,
          table([
            { label: 'Case', cls: 'wide', render: c => h('div', { class: 'cs' }, h('b', null, c.case_number), ' ', c.title,
              h('div', { class: 'muted small' }, [c.priority ? [dot(c.priority), pretty(c.priority)] : null, c.category_label ? (c.category_parent_label ? c.category_parent_label + ' › ' : '') + c.category_label : null, c.location, c.complainant_name ? 'raised by ' + c.complainant_name : null].filter(Boolean).flatMap((x, i) => [i ? ' · ' : null, x]))) },
            { label: 'Status', render: c => statusBadge(c.status) },
            { label: 'Who has it', render: c => c.assignee_name ? person(null, c.assignee_name) : badge('Not assigned', 'warn') },
            { label: 'Due', render: c => closed.includes(c.status) ? h('span', { class: 'muted' }, 'closed ' + fmtD(c.closed_at)) : h('span', { style: c.is_overdue ? { color: 'var(--bad)', fontWeight: 600 } : null }, relDue(c.due_at)) },
          ], d.rows, { onRow: c => go('cases', '', { ...q, case: c.id }), emptyTitle: 'No cases match', emptyText: 'Try removing a filter.' }),
          pager(d.total, d.page, d.page_size, p => update({ page: p })));
      } catch (e) { fill(out, notice(e.message, 'bad')); }
    }
    await load();
  },
};

"""
