JS = r"""
// ───────────────────────── Home ─────────────────────────
// What needs attention today. Every line is worked out from facts the dashboard already reads;
// nothing is written here about what the numbers mean for a particular organisation.
const greeting = () => { const hr = new Date().getHours(); return hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening'; };
const isoDay = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
function sparkline(pts, color) {
  const W = 100, H = 26, max = Math.max(...pts, 1), min = Math.min(...pts, 0), n = pts.length;
  const x = i => i * (W / Math.max(1, n - 1)), y = v => H - 3 - ((v - min) / (max - min || 1)) * (H - 8);
  const d = pts.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1)).join(' ');
  const col = 'var(' + color + ')';
  return svgEl('svg', { class: 'sp', viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none' },
    svgEl('path', { d: d + ' L' + W + ' ' + H + ' L0 ' + H + 'Z', style: 'fill:' + col + ';opacity:.13' }),
    svgEl('path', { d, style: 'fill:none;stroke:' + col + ';stroke-width:2', 'vector-effect': 'non-scaling-stroke', 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
}
// "▲ 4 more than the 7 days before": a change worth a colour only when we know which way is good
function deltaLine(now, before, upIsGood) {
  const d = now - before;
  if (!d) return h('span', { class: 'd muted' }, 'same as the week before');
  const good = upIsGood === null ? null : (d > 0) === upIsGood;
  return h('span', { class: 'd', style: { color: good === null ? 'var(--muted)' : good ? 'var(--ok)' : 'var(--bad)' } }, (d > 0 ? '▲ ' : '▼ ') + Math.abs(d) + ' ' + (d > 0 ? 'more' : 'fewer') + ' than the week before');
}
function needCard(tone, ic, title, sub, cta, to) {
  return h('div', { class: 'need ' + tone }, h('span', { class: 'ni' }, icon(ic)), h('div', null,
    h('b', null, title), sub ? h('div', { class: 'muted small' }, sub) : null, h('a', { class: 'cta', href: to }, cta, icon('arrowr', 'xs'))));
}
function kpiTile(label, n, tone, to, extra) {
  return h('button', { class: 'kpi' + (tone ? ' ' + tone : ''), type: 'button', onclick: () => { location.hash = to; } },
    h('span', { class: 'l' }, label), h('span', { class: 'n' }, num(n)), extra && extra.delta, extra && extra.spark);
}
// how a conversation ended, from the same facts the Conversations screen uses
function chatKind(c) {
  if (c.had_error) return 'fail';
  if (new Date(c.started_at).getTime() < CONFIRMS_LOGGED_FROM) return 'ok';
  if (/Reply \*yes\* to save/.test(c.last_reply || '')) return Date.now() - new Date(c.last_at).getTime() > 10 * 60 * 1000 ? 'never' : 'wait';
  return 'ok';
}

SECTIONS.overview = {
  title: 'Home',
  heading: () => ({ title: greeting(), sub: 'What needs you today at ' + S.boot.org.name + ' · ' + new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date()) }),
  actions: () => h('div', { class: 'row' }, h('button', { class: 'btn sm', type: 'button', onclick: () => { lastSig = ''; onRoute(); } }, icon('refresh', 'sm'), 'Refresh')),
  async render(root) {
    const caps = S.boot.caps, soft = p => p.catch(() => null);
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    const [d, legacy, cats, targets, chats] = await Promise.all([
      api.get('/overview'), soft(classic.get('/data')),
      caps.case_model ? soft(api.get('/categories')) : null,
      caps.targets ? soft(api.get('/targets')) : null,
      caps.audit ? soft(api.get('/chats', { date_from: isoDay(since), page_size: 50 })) : null,
    ]);
    clear(root);
    const c = d.cases, k = c && c.kpis, rows24 = chats ? chats.rows.filter(r => new Date(r.last_at) >= since) : [];
    const gaps = cats ? cats.rows.filter(x => x.is_active && !x.covered) : [];
    const silent = d.people.active - d.people.reachable;

    // 1. what needs you
    const needs = [];
    if (k && k.unassigned) needs.push(needCard('warn', 'usercheck', plural(k.unassigned, 'case') + (k.unassigned === 1 ? ' has' : ' have') + ' no one assigned', 'They wait until someone takes them.', 'Open Cases', href('cases', '', { status: 'open', unassigned: '1' })));
    if (k && k.overdue) needs.push(needCard('bad', 'clock', plural(k.overdue, 'case') + (k.overdue === 1 ? ' is' : ' are') + ' past the target time', 'The longest one is ' + (c.overdue[0] ? relDue(c.overdue[0].due_at) : 'late') + '.', 'See them', href('cases', '', { status: 'open', overdue: '1' })));
    if (gaps.length) needs.push(needCard('bad', 'route', plural(gaps.length, 'kind') + ' of complaint ' + (gaps.length === 1 ? 'has' : 'have') + ' nobody to go to', gaps.slice(0, 3).map(g => g.label).join(', ') + '. New cases of ' + (gaps.length === 1 ? 'this kind' : 'these') + ' stay unassigned.', 'Fix in routing', href('cases', 'rules')));
    if (rows24.some(r => r.had_error)) needs.push(needCard('bad', 'chat', plural(rows24.filter(r => r.had_error).length, 'conversation') + ' failed since yesterday', 'Something went wrong while the assistant was working.', 'Open Conversations', href('conversations')));
    if (silent > 0) needs.push(needCard('info', 'send', silent + ' of ' + d.people.active + ' people cannot be messaged yet', 'The assistant has no way to reach them.', 'Open People', href('people', 'people')));
    root.append(h('div', { class: 'need-grid' }, needs.length ? needs : needCard('ok', 'ok', 'All clear', 'Nothing needs you right now.', 'See all cases', href('cases'))));

    // 2. the numbers
    if (c) {
      const t = c.trend, last = f => t.slice(-7).reduce((a, p) => a + p[f], 0), before = f => t.slice(0, 7).reduce((a, p) => a + p[f], 0), top = c.top_priority;
      root.append(h('div', { class: 'kpis' },
        kpiTile('Open cases', k.open, '', href('cases', '', { status: 'open' })),
        kpiTile('Not assigned yet', k.unassigned, k.unassigned ? 'warn' : '', href('cases', '', { status: 'open', unassigned: '1' })),
        kpiTile('Past target time', k.overdue, k.overdue ? 'bad' : '', href('cases', '', { status: 'open', overdue: '1' })),
        top ? kpiTile(pretty(top) + ' and open', k.top_priority_open, k.top_priority_open ? 'bad' : '', href('cases', '', { status: 'open', priority: top })) : null,
        kpiTile('New in 7 days', k.created_7d, '', href('cases'), { delta: deltaLine(last('created'), before('created'), null), spark: sparkline(t.slice(-7).map(p => p.created), '--brand') }),
        kpiTile('Closed in 7 days', k.closed_7d, 'ok', href('cases', '', { status: (c.closed_values || []).join(',') }), { delta: deltaLine(last('closed'), before('closed'), true), spark: sparkline(t.slice(-7).map(p => p.closed), '--ok') })));
    } else if (legacy && legacy.stats && legacy.stats.length) {
      // stat cards some organisations set up for themselves (kept from the classic dashboard)
      root.append(h('div', { class: 'kpis' }, legacy.stats.map(s => h('div', { class: 'kpi', style: { cursor: 'default', borderLeft: '4px solid ' + (s.color || 'var(--line-2)') } }, h('span', { class: 'l' }, s.label), h('span', { class: 'n' }, s.format === 'currency_inr' ? money(s.value) : num(s.value))))));
    }

    // 3. the two columns
    const left = h('div', { class: 'stack' }), right = h('div', { class: 'stack' });
    if (c) {
      const byKind = (c.by_category || []).map(x => ({ label: x.label, n: x.n, id: x.id }));
      left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Last 14 days', h('span', { class: 'row small muted' }, h('span', { style: { color: 'var(--brand)' } }, '■'), 'new', h('span', { style: { color: 'var(--ok)' } }, '■'), 'closed')),
        h('div', { class: 'card-b' }, trendChart(c.trend), h('div', { class: 'row between muted small' }, h('span', null, fmtD(c.trend[0].day)), h('span', null, 'Today')))));
      left.append(h('div', { class: 'cols-2' },
        caps.case_category ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Open cases by kind'), h('div', { class: 'card-b' }, bars(byKind, i => go('cases', '', { status: 'open', category: i.id || 'none' })))) : null,
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Past their target time', h('a', { class: 'small', href: href('cases', '', { status: 'open', overdue: '1' }) }, 'See all')), h('div', { class: 'card-b flush' }, c.overdue.length ? c.overdue.map(caseLine) : empty('Nothing is late', '')))));
      left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Not assigned yet', h('a', { class: 'small', href: href('cases', '', { status: 'open', unassigned: '1' }) }, 'See all')), h('div', { class: 'card-b flush' }, c.unassigned.length ? c.unassigned.map(caseLine) : empty('All open cases have someone', ''))));
    } else if (legacy && legacy.low_stock && legacy.low_stock.rows.length) {
      const ls = legacy.low_stock;
      left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, ls.title), table(ls.columns.map(col => ({ label: col.label, render: r => String(r[col.key] ?? '') })), ls.rows)));
    } else if (!legacy || !legacy.stats) left.append(notice('This organisation does not track cases, so there is no case summary. Use the menu on the left.'));

    if (chats) {
      const ok = rows24.filter(r => chatKind(r) === 'ok').length, wait = rows24.filter(r => chatKind(r) === 'wait').length, never = rows24.filter(r => chatKind(r) === 'never').length, fail = rows24.filter(r => chatKind(r) === 'fail').length;
      const line = (tone, text, n, link) => h('div', { class: 'hl' }, h('span', { class: 'pdot ' + tone }), h('span', { class: 'grow' }, text), h('b', null, n), link && n ? h('a', { class: 'small', href: href('conversations') }, 'view') : null);
      right.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Is the assistant working?', h('span', { class: 'sub' }, 'since yesterday')),
        h('div', { class: 'card-b' }, line('ok', 'Conversations', rows24.length), line('ok', 'Finished normally', ok), line('warn', 'Waiting for “yes”', wait, true), line('warn', 'Never confirmed', never, true), line('bad', 'Something failed', fail, true))));
    }
    // a setup list worked out from live facts, so it ticks itself
    const steps = [];
    steps.push([d.people.active > 0, 'Add your people', null]);
    if (cats) { steps.push([cats.rows.length > 0, 'Create the kinds of complaint', null]); steps.push([!gaps.length && cats.rows.length > 0, 'Give every kind someone to go to', gaps.length ? gaps.length + ' left: ' + gaps.slice(0, 3).map(g => g.label).join(', ') + '.' : null, gaps.length ? ['Open routing', href('cases', 'rules')] : null]); }
    if (targets) steps.push([!targets.missing.length && targets.rows.length > 0, 'Check the response times', targets.missing.length ? 'Not set yet: ' + targets.missing.map(pretty).join(', ') + '.' : null, targets.missing.length ? ['Open response times', href('cases', 'times')] : null]);
    steps.push([d.workflows.active > 0, 'Switch on a flow', null, d.workflows.active ? null : ['Open Flows', href('workflows')]]);
    if (steps.length >= 3) {
      const done = steps.filter(s => s[0]).length;
      right.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Getting set up', h('span', { class: 'sub' }, done + ' of ' + steps.length + ' done')),
        h('div', { class: 'card-b' }, h('div', { class: 'progress', style: { marginBottom: '6px' } }, h('i', { style: { width: Math.round(done / steps.length * 100) + '%' } })),
          steps.map(([ok, title, note, link]) => h('div', { class: 'check' + (ok ? ' done' : '') }, h('span', { class: 'cb' }, ok ? icon('check', 'xs') : null),
            h('div', null, h('b', null, title), note ? h('div', { class: 'muted small' }, note) : null, link ? h('a', { class: 'small', href: link[1] }, link[0] + ' →') : null))))));
    }
    root.append(h('div', { class: 'cols-21' }, left, right));

    // 4. what happened lately
    const feed = [];
    if (caps.events) feed.push(h('div', { class: 'card feed' }, h('div', { class: 'card-h' }, 'Recently changed in the dashboard', h('a', { class: 'small', href: href('activity', 'changes') }, 'See all')),
      d.events.length ? d.events.slice(0, 4).map(e => h('div', { class: 'fi' }, avatar(e.actor_label || '?'), h('div', null, e.summary, h('div', { class: 'muted small' }, ago(e.created_at) + ' · ' + (e.actor_label || '') + ' · ' + pretty(e.area))))) : empty('No changes yet', 'Changes made here are listed with who made them.')));
    if (chats && chats.rows.length) feed.push(h('div', { class: 'card feed' }, h('div', { class: 'card-h' }, 'Latest conversations', h('a', { class: 'small', href: href('conversations') }, 'See all')),
      chats.rows.slice(0, 4).map(r => h('div', { class: 'fi' }, avatar(r.user_name || '?'), h('div', null, h('b', null, r.user_name || 'Unknown'), ' · “' + clip(r.last_input, 70) + '”', ' ', chatState(r), h('div', { class: 'muted small' }, ago(r.last_at) + ((r.workflows || []).length ? ' · ' + r.workflows.join(', ') : '')))))));
    if (feed.length) root.append(h('div', { class: 'cols-2', style: { marginTop: '14px' } }, feed));
  },
};
"""
