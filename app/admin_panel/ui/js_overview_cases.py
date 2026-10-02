JS = r"""
// ───────────────────────── Overview ─────────────────────────
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
SECTIONS.overview = {
  title: 'Overview', sub: 'What needs attention right now',
  async render(root) {
    const [d, legacy] = await Promise.all([api.get('/overview'), classic.get('/data').catch(() => null)]);
    clear(root);
    const c = d.cases;
    if (c) {
      const k = c.kpis, top = c.top_priority;
      const kpi = (n, label, tone, to) => h('div', { class: 'card kpi ' + tone, onclick: () => go('cases', '', to) }, h('div', { class: 'n' }, num(n)), h('div', { class: 'l' }, label));
      root.append(h('div', { class: 'grid kpis' },
        kpi(k.open, 'Open cases', 'info', { status: 'open' }),
        kpi(k.unassigned, 'Not assigned yet', k.unassigned ? 'warn' : 'ok', { status: 'open', unassigned: '1' }),
        kpi(k.overdue, 'Past their target time', k.overdue ? 'bad' : 'ok', { status: 'open', overdue: '1' }),
        top ? kpi(k.top_priority_open, pretty(top) + ' and open', k.top_priority_open ? 'bad' : 'ok', { status: 'open', priority: top }) : null,
        kpi(k.created_7d, 'New in the last 7 days', '', {}),
        kpi(k.closed_7d, 'Closed in the last 7 days', 'ok', { status: (c.closed_values || []).join(',') })));
      root.append(h('div', { class: 'grid g2', style: { marginBottom: '14px' } },
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Not assigned yet', h('a', { class: 'small', href: href('cases', '', { status: 'open', unassigned: '1' }) }, 'See all')),
          c.unassigned.length ? c.unassigned.map(caseLine) : empty('All open cases have someone', '')),
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Past their target time', h('a', { class: 'small', href: href('cases', '', { status: 'open', overdue: '1' }) }, 'See all')),
          c.overdue.length ? c.overdue.map(caseLine) : empty('Nothing is late', ''))));
      const byStatus = (c.statuses.length ? c.statuses : c.by_status.map(x => x.status)).map(s => ({ label: pretty(s), n: (c.by_status.find(x => x.status === s) || { n: 0 }).n, key: s }));
      const byPrio = (c.priorities.length ? c.priorities : c.by_priority.map(x => x.priority)).map(p => ({ label: pretty(p), n: (c.by_priority.find(x => x.priority === p) || { n: 0 }).n, key: p }));
      root.append(h('div', { class: 'grid g2', style: { marginBottom: '14px' } },
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'All cases by status'),
          h('div', { class: 'card-b' }, bars(byStatus, i => go('cases', '', { status: i.key })))),
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Open cases by priority'),
          h('div', { class: 'card-b' }, bars(byPrio, i => go('cases', '', { status: 'open', priority: i.key }))))));
      root.append(h('div', { class: 'grid g2', style: { marginBottom: '14px' } },
        S.boot.caps.case_category ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Open cases by category'),
          h('div', { class: 'card-b' }, bars(c.by_category.map(x => ({ label: x.label, n: x.n, id: x.id })), i => go('cases', '', { status: 'open', category: i.id || 'none' })))) : null,
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Last 14 days', h('span', { class: 'row small muted' }, h('span', null, '■ new'), h('span', { style: { color: 'var(--ok)' } }, '■ closed'))),
          h('div', { class: 'card-b' }, trendChart(c.trend), h('div', { class: 'row between muted small' }, h('span', null, fmtD(c.trend[0].day)), h('span', null, 'Today'))))));
    } else if (!legacy || !legacy.stats) {
      root.append(notice('This organisation does not track cases, so there is no case summary. Use the other sections on the left.'));
    }
    // stat cards some organisations configure for themselves (kept from the classic dashboard)
    if (legacy && legacy.stats && legacy.stats.length) {
      root.append(h('div', { class: 'grid kpis' }, legacy.stats.map(s => h('div', { class: 'card kpi', style: { cursor: 'default', borderLeftColor: s.color || 'var(--line2)' } },
        h('div', { class: 'n' }, s.format === 'currency_inr' ? money(s.value) : num(s.value)), h('div', { class: 'l' }, s.label)))));
    }
    if (legacy && legacy.low_stock && legacy.low_stock.rows.length) {
      const ls = legacy.low_stock;
      root.append(h('div', { class: 'card', style: { marginBottom: '14px' } }, h('div', { class: 'card-h' }, ls.title),
        table(ls.columns.map(col => ({ label: col.label, render: r => String(r[col.key] ?? '') })), ls.rows)));
    }
    root.append(h('div', { class: 'grid g2' },
      S.boot.caps.events ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Recently changed in the dashboard', h('a', { class: 'small', href: href('activity', 'changes') }, 'See all')),
        d.events.length ? d.events.map(e => h('div', { style: { padding: '9px 16px', borderBottom: '1px solid var(--line)' } }, e.summary, h('div', { class: 'muted small' }, ago(e.created_at) + ' · ' + e.actor_label))) : empty('No changes yet', 'Changes made here are listed with who made them.')) : null,
      h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'At a glance'),
        h('div', { class: 'card-b stack' },
          h('div', { class: 'row between' }, h('span', null, 'People'), h('span', null, h('b', null, num(d.people.active)), ' active · ', h('b', null, num(d.people.reachable)), ' can be messaged')),
          h('div', { class: 'row between' }, h('span', null, 'Workflows'), h('span', null, h('b', null, num(d.workflows.active)), ' on · ', h('b', null, num(d.workflows.total - d.workflows.active)), ' off')),
          h('div', { class: 'row' }, h('a', { class: 'btn sm', href: href('people', 'people') }, 'People'), h('a', { class: 'btn sm', href: href('workflows') }, 'Workflows'))))));
  },
};

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
      if (!c.category_id) inner = h('span', { class: 'muted' }, 'This case has no category yet, so no routing rule can apply.');
      else if (!r) inner = h('span', null, 'No routing rule matches this category yet. ', h('a', { href: href('routing', 'rules') }, 'Add one'));
      else inner = h('div', { class: 'stack' },
        h('div', null, 'Rule ', h('b', null, '“' + r.rule_name + '”'), ' would send it to ', r.assignee_name ? h('b', null, r.assignee_name) : h('b', { style: { color: 'var(--bad)' } }, 'nobody (no one it points to can be messaged)'),
          r.via === 'backup' ? ' (the backup, because the first choice is unavailable)' : '', r.level2.length ? ', with ' + r.level2.map(x => x.name).join(', ') + ' as level 2' : '', '.'),
        r.target_minutes ? h('div', { class: 'muted small' }, 'Response target from the rule: ' + minutes(r.target_minutes)) : null,
        r.assignee_id && r.assignee_id !== c.assigned_to_id ? h('div', { class: 'muted small' }, 'That is different from who has it now.') : null);
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What the routing rules say'), h('div', { class: 'card-b' }, inner)));
    }
    body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'People on this case'),
      d.parties.length ? h('div', { class: 'card-b stack' }, onePerPerson(d.parties).map(p => h('div', { class: 'row between' },
        person(p.user_id, p.name), h('span', { class: 'row' }, p.roles.map(r => badge(r.text, r.tone)), p.reachable ? null : badge('not on Telegram', 'warn'))))) : empty('Nobody yet', '')));
    if (c.description) body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What was reported'), h('div', { class: 'card-b' }, h('div', { style: { whiteSpace: 'pre-wrap' } }, c.description))));
    body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Timeline'),
      h('div', { class: 'card-b' }, d.timeline.length ? h('div', { class: 'timeline' }, d.timeline.map(timelineItem)) : h('span', { class: 'muted' }, 'Nothing has happened on this case yet.'))));
    body.push(h('div', { class: 'muted small' }, 'To assign, update or close a case, use its workflow in Telegram. The dashboard only shows cases.'));
    clear(dr.bodyEl); add(dr.bodyEl, body);
  } catch (e) { if (drawer === dr) { clear(dr.bodyEl); dr.bodyEl.append(notice(e.message, 'bad')); dr.titleEl.textContent = 'Case'; } }
}
SECTIONS.cases = {
  title: 'Cases', sub: 'Everything that has been reported, and where it stands',
  async render(root, route) {
    const mine = S.renderId;
    const lk = S.boot.caps.case_category ? await getLookups() : { categories: [] };
    const q = { sort: 'newest', ...route.q }; delete q.case; delete q.person;
    q.page = Number(q.page || 1);
    const chips = h('div', { class: 'chips', style: { marginBottom: '10px' } });
    const bar = h('div', { class: 'filters' });
    const out = h('div', { class: 'card' });
    root.append(chips, bar, out);
    let assigneePick;
    const update = (patch) => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
    const search = h('input', { type: 'search', placeholder: 'Search number, title, place or person…', value: q.q || '', style: { minWidth: '260px' } });
    search.addEventListener('input', debounce(() => update({ q: search.value }), 300));
    const cat = S.boot.caps.case_category ? sel(catOptions(lk, 'Any category', true), q.category || '', { onchange: e => update({ category: e.target.value }) }) : null;
    const prio = sel([['', 'Any priority'], ...(S.boot.enums.priorities || []).map(p => [p, pretty(p)])], q.priority || '', { onchange: e => update({ priority: e.target.value }) });
    const sort = sel([['newest', 'Newest first'], ['oldest', 'Oldest first'], ['due', 'Due soonest'], ['priority', 'Most urgent first']], q.sort, { onchange: e => update({ sort: e.target.value }) });
    assigneePick = personPicker({ placeholder: 'Handled by…', anyStatus: true, initial: q.assignee && q.assignee !== 'none' ? { id: q.assignee, name: q.assignee_name || 'Selected person' } : null,
      onChange: p => update({ assignee: p ? p.id : '', assignee_name: p ? p.name : '' }) });
    const flag = (key, label) => { const cb = h('input', { type: 'checkbox', checked: !!q[key] }); cb.addEventListener('change', () => update({ [key]: cb.checked ? '1' : '' })); return h('label', { class: 'row small' }, cb, label); };
    const clearBtn = h('button', { class: 'btn sm ghost', onclick: () => { for (const k of ['status', 'priority', 'category', 'assignee', 'assignee_name', 'q', 'overdue', 'unassigned']) delete q[k]; q.page = 1; route.q = {}; setQuery({}); SECTIONS.cases.render(clear(root), { ...route, q: {} }); } }, 'Clear filters');
    add(bar, [search, cat, prio, assigneePick.el, flag('unassigned', 'Not assigned'), flag('overdue', 'Past target time'), sort, clearBtn]);
    async function load() {
      if (mine !== S.renderId) return;
      setQuery({ ...q, sort: q.sort === 'newest' ? '' : q.sort });
      fill(out, h('div', { class: 'empty' }, 'Loading…'));
      try {
        const d = await api.get('/cases', { status: q.status, priority: q.priority, category: q.category, assignee: q.assignee, q: q.q, overdue: q.overdue ? true : '', unassigned: q.unassigned ? true : '', sort: q.sort, page: q.page, page_size: 25 });
        const total = Object.values(d.status_counts).reduce((a, b) => a + b, 0);
        const closed = S.boot.enums.closed || [];
        const openN = Object.entries(d.status_counts).filter(([s]) => !closed.includes(s)).reduce((a, [, n]) => a + n, 0);
        const chip = (label, n, val) => h('button', { class: 'btn sm' + ((q.status || '') === val ? ' primary' : ''), onclick: () => update({ status: val }) }, label + ' ', h('span', { style: { opacity: .75 } }, n));
        fill(chips, chip('All', total, ''), chip('Open', openN, 'open'), (S.boot.enums.statuses || Object.keys(d.status_counts)).map(s => chip(pretty(s), d.status_counts[s] || 0, s)));
        fill(out, 
          table([
            { label: 'Case', cls: 'wide', render: c => h('div', null, h('b', null, c.case_number), h('div', null, c.title), h('div', { class: 'muted small' }, [c.location, c.complainant_name ? 'raised by ' + c.complainant_name : null].filter(Boolean).join(' · '))) },
            { label: 'Status', render: c => statusBadge(c.status) },
            { label: 'Priority', render: c => prioBadge(c.priority) },
            S.boot.caps.case_category ? { label: 'Category', render: c => c.category_label ? h('span', null, c.category_parent_label ? h('span', { class: 'muted' }, c.category_parent_label + ' › ') : null, c.category_label) : h('span', { class: 'muted' }, '—') } : null,
            { label: 'Handled by', render: c => c.assignee_name ? person(null, c.assignee_name) : badge('Not assigned', 'warn') },
            { label: 'Due', render: c => closed.includes(c.status) ? h('span', { class: 'muted' }, 'closed ' + fmtD(c.closed_at)) : h('span', { style: c.is_overdue ? { color: 'var(--bad)', fontWeight: 600 } : null }, relDue(c.due_at)) },
          ].filter(Boolean), d.rows, { onRow: c => go('cases', '', { ...q, case: c.id }), emptyTitle: 'No cases match', emptyText: 'Try clearing a filter.' }),
          pager(d.total, d.page, d.page_size, p => update({ page: p })));
      } catch (e) { fill(out, notice(e.message, 'bad')); }
    }
    await load();
  },
};
"""
