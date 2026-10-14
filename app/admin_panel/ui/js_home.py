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
// one thing that needs you: what it is, and one button that goes to it
function needRow(n, primary) {
  return h('div', { class: 'nr' }, h('span', { class: 'nr-i ' + n.tone }, icon(n.ic)), h('div', { class: 'nr-t' }, h('b', null, n.title), n.sub ? h('span', { class: 'muted small' }, n.sub) : null),
    h('a', { class: 'btn sm' + (primary ? ' primary' : ''), href: n.to }, n.cta));
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

// the set-up list as a card, the way the approved prototype shows it: a bar, each step with its button
function setupCard(steps) {
  const done = steps.filter(s => s[0]).length;
  return h('div', { class: 'card setcard' }, h('div', { class: 'card-h' }, 'Set up in ' + steps.length + ' steps', h('span', { class: 'muted small' }, done + ' of ' + steps.length + ' done')),
    h('div', { class: 'card-b stack s8' }, h('div', { class: 'setbar' }, h('i', { style: { width: (done / steps.length * 100) + '%' } })),
      steps.map(([ok, title, note, link]) => h('div', { class: 'check' + (ok ? ' done' : '') }, h('span', { class: 'cb' }, ok ? icon('check', 'xs') : null),
        h('div', { class: 'grow' }, h('b', null, title), note ? h('div', { class: 'muted small' }, note) : null), link && !ok ? h('a', { class: 'btn sm', href: link[1] }, link[0]) : null))));
}
// the open tickets closest to the end of their time to fix
async function timeToFixCard(box) {
  let d;
  try { d = await api.get('/cases', { status: 'open', sort: 'due', page_size: 40 }); } catch (e) { return; }
  const rows = d.rows.filter(x => x.clock && !x.clock.no_limit && !x.clock.paused).sort((a, b) => (b.clock.percent || 0) - (a.clock.percent || 0)).slice(0, 4);
  if (!rows.length || !box.isConnected) return;
  box.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Time to fix', h('a', { class: 'btn sm', href: href('cases', '', { status: 'open', sort: 'due' }) }, 'All tickets')),
    h('div', { class: 'card-b' }, rows.map(x => h('a', { class: 'tfrow', href: href('cases', '', { case: x.id }) },
      h('div', { class: 'row between' }, h('b', null, x.title), h('span', { class: 'muted small' }, x.case_number)), timeBar(x))))));
}

let HOME_HEAD = null;                          // the right side of the Home title: filled once the page knows its set-up list
SECTIONS.overview = {
  title: 'Home',
  heading: () => ({ title: greeting(), sub: 'What needs you today at ' + S.boot.org.name + ' · ' + new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date()) }),
  actions: () => (HOME_HEAD = h('div', { class: 'row' })),
  async render(root) {
    const caps = S.boot.caps, soft = p => p.catch(() => null);
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    const [d, cats, targets, chats] = await Promise.all([
      api.get('/overview'),
      caps.case_model && isSuper() ? soft(api.get('/categories')) : null,
      caps.targets && isSuper() ? soft(api.get('/targets')) : null,
      caps.audit && isSuper() ? soft(api.get('/chats', { date_from: isoDay(since), page_size: 50 })) : null,
    ]);
    clear(root);
    const c = d.cases, k = c && c.kpis, rows24 = chats ? chats.rows.filter(r => new Date(r.last_at) >= since) : [];
    const gaps = cats ? cats.rows.filter(x => x.is_active && !x.covered) : [];
    const silent = d.people.active - d.people.reachable;

    // 1. what needs you: the most important three, the rest one click away
    const needs = [];
    if (k && k.unassigned) needs.push({ tone: 'warn', ic: 'usercheck', title: plural(k.unassigned, 'case') + (k.unassigned === 1 ? ' has' : ' have') + ' no one handling ' + (k.unassigned === 1 ? 'it' : 'them'), sub: 'They wait until someone takes them.', cta: 'See ' + (k.unassigned === 1 ? 'it' : 'them'), to: href('cases', '', { status: 'open', unassigned: '1' }) });
    if (k && k.overdue) needs.push({ tone: 'bad', ic: 'clock', title: plural(k.overdue, 'case') + (k.overdue === 1 ? ' is' : ' are') + ' past the target time', sub: 'The longest one is ' + (c.overdue[0] ? relDue(c.overdue[0].due_at) : 'late') + '.', cta: 'See ' + (k.overdue === 1 ? 'it' : 'them'), to: href('cases', '', { status: 'open', overdue: '1' }) });
    if (gaps.length) needs.push({ tone: 'info', ic: 'route', title: plural(gaps.length, 'kind') + ' of complaint ' + (gaps.length === 1 ? 'has' : 'have') + ' nobody to go to', sub: 'New cases of ' + (gaps.length === 1 ? 'this kind' : 'these kinds') + ' stay unassigned.', cta: 'Fix in Case rules', to: href('cases', 'teams') });
    if (rows24.some(r => r.had_error)) needs.push({ tone: 'bad', ic: 'chat', title: plural(rows24.filter(r => r.had_error).length, 'conversation') + ' failed since yesterday', sub: 'Something went wrong while the chat bot was working.', cta: 'Open Conversations', to: href('conversations') });
    if (silent > 0) needs.push({ tone: 'info', ic: 'send', title: silent + ' of ' + d.people.active + ' people cannot be messaged yet', sub: 'The chat bot has no way to reach them.', cta: 'Open People', to: href('people') });
    const more = needs.slice(3);
    const nbox = h('div', { class: 'card', style: { marginBottom: '16px' } }, h('div', { class: 'card-h' }, 'Needs you', h('span', { class: 'muted small' }, needs.length ? plural(Math.min(3, needs.length), 'thing') + (more.length ? ' of ' + needs.length : '') : '')),
      needs.length ? needs.slice(0, 3).map((n, i) => needRow(n, i === 0)) : h('div', { class: 'nr' }, h('span', { class: 'nr-i ok' }, icon('ok')), h('div', { class: 'nr-t' }, h('b', null, 'All clear'), h('span', { class: 'muted small' }, 'Nothing needs you right now.')), caps.cases ? h('a', { class: 'btn sm', href: href('cases') }, 'See all cases') : null),
      more.length ? h('div', { class: 'nr-more' }, h('button', { class: 'btn ghost sm', type: 'button', onclick: e => { const box = e.currentTarget.closest('.nr-more'); box.classList.toggle('open'); } }, plural(more.length, 'smaller thing'), ' ', icon('chevd', 'xs')),
        h('div', { class: 'extra' }, more.map(n => h('div', null, n.title + '. ', h('a', { href: n.to }, n.cta))))) : null);
    root.append(nbox);

    // 2. four numbers
    if (c) {
      const t = c.trend, last = f => t.slice(-7).reduce((a, p) => a + p[f], 0), before = f => t.slice(0, 7).reduce((a, p) => a + p[f], 0);
      root.append(h('div', { class: 'kpis' },
        kpiTile('Open cases', k.open, '', href('cases', '', { status: 'open' })),
        kpiTile('Not assigned yet', k.unassigned, k.unassigned ? 'warn' : '', href('cases', '', { status: 'open', unassigned: '1' })),
        kpiTile('Past target time', k.overdue, k.overdue ? 'bad' : '', href('cases', '', { status: 'open', overdue: '1' })),
        kpiTile('Closed in 7 days', k.closed_7d, 'ok', href('cases', '', { status: (c.closed_values || []).join(',') }), { delta: deltaLine(last('closed'), before('closed'), true) })));
    } else if (d.stats && d.stats.length) {
      // stat cards some organisations set up for themselves (orgs.settings.dashboard_stats)
      root.append(h('div', { class: 'kpis' }, d.stats.map(s => h('div', { class: 'kpi', style: { cursor: 'default', borderLeft: '4px solid ' + (s.color || 'var(--line-2)') } }, h('span', { class: 'l' }, s.label), h('span', { class: 'n' }, s.format === 'currency_inr' ? money(s.value) : num(s.value))))));
    }

    // 3. the chart, and one line on whether the chat bot is working
    const left = h('div', { class: 'stack' }), right = h('div', { class: 'stack' });
    if (c) {
      left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Last 14 days', h('span', { class: 'row small muted' }, h('span', { style: { color: 'var(--brand)' } }, '■'), 'new', h('span', { style: { color: 'var(--ok)' } }, '■'), 'closed')),
        h('div', { class: 'card-b' }, trendChart(c.trend), h('div', { class: 'row between muted small' }, h('span', null, fmtD(c.trend[0].day)), h('span', null, 'Today')))));
    } else if (d.low_stock && d.low_stock.rows.length) {
      const ls = d.low_stock;
      left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, ls.title), table(ls.columns.map(col => ({ label: col.label, render: r => String(r[col.key] ?? '') })), ls.rows)));
    } else if (!d.stats) left.append(notice('This organisation does not track cases, so there is no case summary. Use the menu on the left.'));
    if (chats) {
      const kinds = rows24.map(chatKind), fail = kinds.filter(x => x === 'fail').length, open = kinds.filter(x => x === 'wait' || x === 'never').length;
      const tone = fail ? 'bad' : open ? 'warn' : 'ok';
      right.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Is the chat bot working?', h('span', { class: 'sub' }, 'since yesterday')),
        h('div', { class: 'okline' }, h('span', { class: 'd ' + tone }), h('div', { class: 'grow' }, h('b', null, fail ? plural(fail, 'conversation') + ' failed' : open ? plural(open, 'conversation') + ' still waiting for a “yes”' : 'Yes, all good'),
          h('div', { class: 'muted small' }, fail || open ? plural(rows24.length, 'conversation') + ' since yesterday' : (rows24.length ? plural(rows24.length, 'conversation') + ', 0 problems' : 'No conversations since yesterday'))),
          fail || open ? h('a', { class: 'btn sm', href: href('conversations') }, 'View') : null)));
    }
    root.append(h('div', { class: 'cols-21' }, left, right));
    if (caps.cases && caps.tat_clock) timeToFixCard(right);

    // a set-up list worked out from live facts, so it ticks itself; it shows only until everything is done
    const steps = [];
    steps.push([d.people.active > 0, 'Add your people', null, d.people.active ? null : ['Open People', href('people')]]);
    if (cats) { steps.push([cats.rows.length > 0, 'Create the kinds of complaint', null]); steps.push([!gaps.length && cats.rows.length > 0, 'Give every kind someone to go to', gaps.length ? gaps.length + ' left: ' + gaps.slice(0, 3).map(g => g.label).join(', ') + '.' : null, gaps.length ? ['Open Case rules', href('cases', 'teams')] : null]); }
    if (targets) steps.push([!targets.missing.length && targets.rows.length > 0, 'Check the response times', targets.missing.length ? 'Not set yet: ' + targets.missing.map(pretty).join(', ') + '.' : null, targets.missing.length ? ['Open response times', href('cases', 'times')] : null]);
    steps.push([d.workflows.active > 0, 'Switch on a flow', null, d.workflows.active ? null : ['Open Flows', href('workflows')]]);
    const done = steps.filter(s => s[0]).length;
    if (isSuper() && steps.length >= 3 && done < steps.length) right.prepend(setupCard(steps));
    if (HOME_HEAD && HOME_HEAD.isConnected) {
      fill(HOME_HEAD, isSuper() && steps.length >= 3 && done < steps.length ? h('button', { class: 'badge brand setchip', type: 'button', 'data-popkeep': '1', title: 'What is left to set up', onclick: e => openPop(e.currentTarget, h('div', { class: 'stack s8', style: { padding: '8px' } }, h('b', null, 'Getting set up · ' + done + ' of ' + steps.length), h('div', { class: 'progress' }, h('i', { style: { width: Math.round(done / steps.length * 100) + '%' } })),
        steps.map(([ok, title, note, link]) => h('div', { class: 'check' + (ok ? ' done' : '') }, h('span', { class: 'cb' }, ok ? icon('check', 'xs') : null), h('div', null, h('b', null, title), note ? h('div', { class: 'muted small' }, note) : null, link ? h('a', { class: 'small', href: link[1] }, link[0] + ' →') : null)))), { align: 'right', width: 340 }) }, 'Getting set up · ' + done + ' of ' + steps.length) : null,
        h('button', { class: 'btn ghost sm icon', type: 'button', 'aria-label': 'Refresh', 'data-tip': 'Refresh', onclick: () => { lastSig = ''; onRoute(); } }, icon('refresh', 'sm')));
    }
  },
};

"""
