// ---------------- small pieces shared by screens ----------------
function head(title, sub, ...actions) { return h('div', { class: 'ph' }, h('div', null, h('h1', null, title), sub ? h('div', { class: 'sub' }, sub) : null), h('div', { class: 'sp' }), actions); }
function startOf(f) { return f.graph.nodes.find(n => STEPS[n.type] && STEPS[n.type].start); }
function triggerWords(f) {
  const s = startOf(f); if (!s) return 'Not set';
  const c = s.cfg || {};
  switch (s.type) {
    case 'chat': return 'Chat' + (c.menu ? ' · menu: ' + (uc(c.menu.usecase) || {}).name + ' › ' + c.menu.group : '') + (c.command ? ' · /' + c.command : '');
    case 'schedule': return 'Every ' + (c.every || 'day').toLowerCase() + ' at ' + (c.time || '9:00') + (c.working ? ', working days' : '');
    case 'after': return 'After “' + (c.flow || '…') + '”';
    case 'change': return 'When a ' + recLabel(c.record || 'ticket').toLowerCase() + ' ' + (c.when || 'changes');
    case 'button': return 'Button “' + (c.label || '…') + '” on a ' + recLabel(c.record || 'ticket').toLowerCase();
    case 'form': return 'WhatsApp form: ' + (c.form || '…');
    default: return STEPS[s.type].name;
  }
}
function accessWords(a) {
  if (!a || a.everyone) return 'Everyone';
  const roles = a.roles || [], kinds = a.kinds || [];
  const groups = DB.roleGroups.filter(g => g.roles.every(r => roles.includes(r))).map(g => 'all ' + g.name.toLowerCase());
  const loose = roles.filter(r => !DB.roleGroups.some(g => g.roles.every(x => roles.includes(x)) && g.roles.includes(r)));
  const parts = groups.concat(loose);
  return (parts.length ? parts.join(', ') : 'Nobody by role') + (kinds.length ? ' + people on the record' : '');
}
function thumbs(graph) { return h('div', { class: 'thumbs' }, graph.nodes.slice(0, 14).map(n => h('i', { style: { background: KINDS[STEPS[n.type].kind].color } }))); }
function flowCard(f) {
  const u = uc(f.usecase);
  return h('div', { class: 'fc', onclick: () => go('flow', f.id) },
    h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h3', null, f.name), f.on ? pill('On', 'ok') : pill('Off')),
    h('span', { class: 'trg' }, STEPS[(startOf(f) || {}).type || 'chat'].icon, ' ', triggerWords(f)),
    thumbs(f.graph),
    h('div', { class: 'row tiny muted' }, u ? pill(u.icon + ' ' + u.name) : null, '👥 ' + accessWords(f.access), h('span', { class: 'sp' }), 'used ' + f.lastUsed));
}
function blockCard(b) {
  const users = DB.flows.filter(f => f.graph.nodes.some(n => n.type === 'block' && n.cfg.block === b.id));
  const u = uc(b.usecase);
  return h('div', { class: 'fc', onclick: () => go('block', b.id) },
    h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h3', null, '🧩 ', b.name), pill('v' + b.version)),
    h('div', { class: 'small muted' }, b.desc),
    h('div', { class: 'row small' }, h('span', { class: 'muted' }, 'Needs'), b.needs.map(n => pill(n)), h('span', { class: 'muted' }, '→ gives'), b.gives.map(g => pill(g[1], 'brand'))),
    h('div', { class: 'row tiny' }, u ? pill(u.icon + ' ' + u.name) : pill('Shared by every use case', 'brand'),
      users.length ? h('span', { class: 'muted' }, 'Used by ', users.map(f => f.name).join(', ')) : pill('Not used yet', 'warn')));
}

// ---------------- Home ----------------
function screenHome(root) {
  drawTop([h('b', null, 'Home')]);
  const needs = [
    ['🎫', '1 ticket has nobody handling it', 'TK-26-0128 Garbage not collected', () => go('uc', 'tickets')],
    ['⏰', '1 ticket is past its time to fix', 'TK-26-0131 Street light near gate 2', () => go('uc', 'tickets')],
    ['📅', '1 booking waits for approval', 'BK-26-0031 Party hall, Sat 18 Oct', () => go('uc', 'bookings')],
  ];
  add(root, head('Good afternoon, ' + (isSuper() ? 'Kartik' : 'Anuja'), 'What needs you today, across every use case.'),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Needs you'), h('div', { class: 'card-b col' }, needs.map(([i, t, s, fn]) => h('div', { class: 'row', style: { justifyContent: 'space-between', padding: '4px 0' } }, h('div', { class: 'row' }, h('span', { style: { fontSize: '18px' } }, i), h('div', null, h('b', null, t), h('div', { class: 'small muted' }, s))), h('button', { class: 'btn sm', onclick: fn }, 'Open'))))),
      h('div', { class: 'grid g2' }, DB.usecases.map(u => h('div', { class: 'card card-b stat' }, h('div', { class: 'small muted' }, u.icon + ' ' + u.name), h('b', null, (DB.items[u.id] || []).length), h('span', null, 'open now'))))),
    h('h3', { style: { margin: '24px 0 10px' } }, 'Use cases'),
    h('div', { class: 'grid g4' }, DB.usecases.map(usecaseTile), isSuper() ? h('div', { class: 'uc new', onclick: () => newUsecaseModal() }, h('div', { style: { fontSize: '24px' } }, '+'), 'Add a use case', h('div', { class: 'tiny' }, 'Parking, maintenance bills, notices…')) : null));
}
function usecaseTile(u) {
  const flows = DB.flows.filter(f => f.usecase === u.id), blocks = DB.blocks.filter(b => b.usecase === u.id);
  return h('div', { class: 'uc', onclick: () => go('uc', u.id) },
    h('div', { class: 'h' }, h('div', { class: 'ico', style: { background: u.color + '22' } }, u.icon), h('div', null, h('b', null, u.name), h('div', { class: 'tiny muted' }, (DB.items[u.id] || []).length + ' open'))),
    h('div', { class: 'small muted' }, u.desc),
    isSuper() ? h('div', { class: 'row tiny muted' }, flows.length + ' flows · ' + blocks.length + ' blocks · record: ' + recLabel(u.record)) : null);
}

// ---------------- a use case ----------------
function screenUsecase(root, r) {
  const u = uc(r.a); if (!u) return go('home');
  const tabs = isSuper() ? [['records', u.name], ['flows', 'Flows'], ['blocks', 'Building blocks'], ['setup', 'How it is set up'], ['access', 'Who can do what']] : [['records', u.name], ['how', 'What people can do here']];
  const tab = tabs.some(t => t[0] === r.b) ? r.b : 'records';
  drawTop([h('a', { href: '#/home' }, 'Home'), '›', h('b', null, u.icon + ' ' + u.name)]);
  const R = DB.records[u.record];
  const actions = tab === 'flows' ? h('button', { class: 'btn pri', onclick: () => newFlowModal(u.id) }, '+ New flow')
    : tab === 'blocks' ? h('button', { class: 'btn pri', onclick: () => newBlockModal(u.id) }, '+ New building block')
    : tab === 'records' ? h('button', { class: 'btn pri', onclick: () => toast('In the real dashboard this opens the "' + R.label + '" form, made from its fields.') }, '+ New ' + R.label.toLowerCase()) : null;
  add(root, head(u.icon + ' ' + u.name, u.desc, actions),
    h('div', { class: 'tabs' }, tabs.map(([k, l]) => h('button', { class: 'tab' + (k === tab ? ' on' : ''), onclick: () => go('uc', u.id, k) }, l))));
  ({ records: ucRecords, flows: ucFlows, blocks: ucBlocks, setup: ucSetup, access: ucAccess, how: ucHow })[tab](root, u, R);
}
function ucRecords(root, u, R) {
  const rows = DB.items[u.id] || [];
  const cols = { tickets: ['Ticket', 'Where', 'Urgency', 'Status', 'Handling it', 'Time to fix'], bookings: ['Booking', 'Facility', 'When', 'Booked it', 'Status'], visitors: ['Pass', 'Visitor', 'Host flat', 'Expected', 'Status'] }[u.id] || R.fields.map(f => f.label);
  add(root, h('div', { class: 'card' }, rows.length ? h('table', { class: 't' }, h('tr', null, cols.map(c => h('th', null, c))),
    rows.map(row => h('tr', { class: 'click' }, row.map((v, i) => h('td', null, u.id === 'tickets' && i === 6 ? tbar(v) : i === 0 ? h('b', null, v) : (cols[i] === 'Status' ? pill(v, v === 'Closed' || v === 'Confirmed' ? 'ok' : v === 'Pending' || v === 'Reported' ? 'warn' : '') : v)))))) : h('div', { class: 'empty' }, 'No ' + R.plural.toLowerCase() + ' yet.')));
}
function tbar(p) {
  const tone = p >= 100 ? 'var(--bad)' : p >= 40 ? 'var(--warn)' : 'var(--ok)';
  return h('div', { style: { minWidth: '120px' } }, h('div', { style: { height: '6px', borderRadius: '6px', background: 'var(--sunk)', overflow: 'hidden' } }, h('i', { style: { display: 'block', height: '100%', width: Math.min(p, 100) + '%', background: tone } })), h('div', { class: 'tiny muted' }, p >= 100 ? 'Late' : p + '% used'));
}
function ucFlows(root, u) {
  const list = DB.flows.filter(f => f.usecase === u.id);
  add(root, h('div', { class: 'notice', style: { marginBottom: '12px' } }, 'ℹ️', h('div', null, 'Flows are what people can do in ', h('b', null, u.name), '. Each one starts in its own way: someone asks in chat, a schedule, a button on a ' + recLabel(u.record).toLowerCase() + ', a change, a form or another flow.')),
    h('div', { class: 'grid g3' }, list.map(flowCard), h('div', { class: 'uc new', onclick: () => newFlowModal(u.id) }, '+ New flow')));
}
function ucBlocks(root, u) {
  const list = DB.blocks.filter(b => b.usecase === u.id), shared = DB.blocks.filter(b => !b.usecase);
  add(root, h('div', { class: 'grid g3' }, list.map(blockCard), h('div', { class: 'uc new', onclick: () => newBlockModal(u.id) }, '+ New building block')),
    shared.length ? [h('h3', { style: { margin: '22px 0 10px', fontSize: '14px' } }, 'Shared by every use case'), h('div', { class: 'grid g3' }, shared.map(blockCard))] : null);
}
function editableList(title, sub, list, placeholder) {
  const box = h('div', { class: 'chipbox' });
  const draw = () => fill(box, list.map((v, i) => h('span', { class: 'chip' }, typeof v === 'string' ? v : v.label, h('span', { class: 'x', onclick: () => { list.splice(i, 1); draw(); } }, '×'))),
    h('input', { type: 'text', placeholder, style: { width: '170px', padding: '3px 9px', borderRadius: '99px' }, onkeydown: e => { if (e.key === 'Enter' && e.target.value.trim()) { const v = e.target.value.trim(); list.push(typeof list[0] === 'object' ? { key: slug(v), label: v, sample: '…' } : v); draw(); } } }));
  draw();
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, title), h('div', { class: 'card-b col' }, h('div', { class: 'small muted' }, sub), box));
}
function ucSetup(root, u, R) {
  add(root, h('div', { class: 'grid g2' },
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Basics'), h('div', { class: 'card-b col' },
      h('label', { class: 'f' }, 'Name', h('input', { type: 'text', value: u.name, oninput: e => { u.name = e.target.value; drawSide(); } })),
      h('label', { class: 'f' }, 'Icon', h('input', { type: 'text', value: u.icon, oninput: e => { u.icon = e.target.value; drawSide(); } })),
      h('label', { class: 'f' }, 'One line about it', h('input', { type: 'text', value: u.desc, oninput: e => { u.desc = e.target.value; } })),
      h('div', { class: 'row small' }, 'It keeps ', pill(R.plural, 'brand'), h('a', { href: '#/schema/' + u.record }, 'Change its fields in Data & schema →')))),
    editableList('Menu groups in the chat', 'What people see after they choose ' + u.name + ' in the chat menu. Flows are placed in these groups.', u.menu, '+ add a group'),
    editableList('Statuses', 'The steps a ' + R.label.toLowerCase() + ' goes through. Flows, reports and reminders use these words.', R.statuses, '+ add a status'),
    editableList('People on a ' + R.label.toLowerCase(), 'The kinds of people a ' + R.label.toLowerCase() + ' can have. Flows can tell them, and let them act on their own ' + R.plural.toLowerCase() + '.', R.people, '+ add a kind of person')));
}
function ucAccess(root, u) { add(root, roleMatrix(u, true)); }
function ucHow(root, u) {
  const list = DB.flows.filter(f => f.usecase === u.id && f.on);
  add(root, h('div', { class: 'card' }, h('table', { class: 't' }, h('tr', null, h('th', null, 'What people can do'), h('th', null, 'How it starts'), h('th', null, 'Who')), list.map(f => h('tr', null, h('td', null, h('b', null, f.name)), h('td', { class: 'small' }, triggerWords(f)), h('td', { class: 'small' }, accessWords(f.access)))))),
    h('div', { class: 'notice', style: { marginTop: '12px' } }, '🔒', 'Only a super admin can change these.'));
}

// ---------------- roles & access: ticks per use case, with "everyone" and "select all" ----------------
function roleMatrix(u, editable) {
  const P = DB.permissions[u.id], abil = DB.abilities;
  const ed = editable && isSuper();
  const wrap = h('div', { class: 'card' });
  function draw() {
    const all = DB.roleGroups.flatMap(g => g.roles);
    const col = a => all.every(r => a.kind === 'scope' ? P[r][a.key] === 'all' : P[r][a.key]);
    fill(wrap, h('div', { class: 'card-h' }, u.icon + ' ' + u.name, h('span', { class: 'sp' }), ed ? h('span', { class: 'tiny muted' }, 'Tick a group name to change the whole group at once.') : pill('View only')),
      h('div', { style: { overflow: 'auto' } }, h('table', { class: 't matrix' },
        h('tr', null, h('th', null, 'Role'), abil.map(a => h('th', null, a.label, ed && a.kind === 'tick' ? h('div', null, h('a', { href: '#', onclick: e => { e.preventDefault(); const v = !col(a); all.forEach(r => P[r][a.key] = v); draw(); } }, col(a) ? 'none' : 'everyone')) : null))),
        DB.roleGroups.map(g => [
          h('tr', null, h('td', { style: { background: 'var(--sunk)' } }, h('b', null, g.name)), abil.map(a => h('td', { style: { background: 'var(--sunk)' } }, ed ? (a.kind === 'scope'
            ? h('select', { onchange: e => { g.roles.forEach(r => P[r][a.key] = e.target.value); draw(); } }, h('option', { value: '' }, 'Set all…'), Object.entries(DB.scopes).map(([k, l]) => h('option', { value: k }, l)))
            : h('input', { type: 'checkbox', checked: g.roles.every(r => P[r][a.key]), onchange: e => { g.roles.forEach(r => P[r][a.key] = e.target.checked); draw(); } })) : null))),
          g.roles.map(r => h('tr', null, h('td', null, r), abil.map(a => h('td', null, a.kind === 'scope'
            ? (ed ? h('select', { onchange: e => { P[r][a.key] = e.target.value; } }, Object.entries(DB.scopes).map(([k, l]) => h('option', { value: k, selected: P[r][a.key] === k }, l))) : DB.scopes[P[r][a.key]])
            : (ed ? h('input', { type: 'checkbox', checked: !!P[r][a.key], onchange: e => { P[r][a.key] = e.target.checked; } }) : (P[r][a.key] ? '✓' : '—')))))),
        ]))));
  }
  draw();
  return wrap;
}
function screenRoles(root) {
  drawTop([h('b', null, 'Roles & access')]);
  add(root, head('Roles & access', 'What each role may do, use case by use case. "Their flat\'s" lets every member of a flat see the flat\'s tickets.',
    isSuper() ? h('button', { class: 'btn pri', onclick: newRoleModal }, '+ New role') : null),
    h('div', { class: 'grid g3', style: { marginBottom: '16px' } }, DB.roleGroups.map(g => h('div', { class: 'card card-b' }, h('b', null, g.name), h('div', { class: 'chipbox', style: { marginTop: '8px' } }, g.roles.map(r => h('span', { class: 'chip' }, r, h('span', { class: 'tiny muted' }, ' · ' + DB.people.filter(p => p.role === r).length))))))),
    h('div', { class: 'col', style: { gap: '14px' } }, DB.usecases.map(u => roleMatrix(u, true))));
}
function newRoleModal() {
  const name = h('input', { type: 'text', placeholder: 'e.g. Sr. manager, Joint member' });
  const grp = h('select', null, DB.roleGroups.map(g => h('option', { value: g.id }, g.name)));
  const like = h('select', null, h('option', { value: '' }, 'Start with nothing allowed'), DB.roleGroups.flatMap(g => g.roles).map(r => h('option', { value: r }, 'Same as ' + r)));
  modal({ title: 'New role', body: h('div', { class: 'col' }, h('label', { class: 'f' }, 'Name', name), h('label', { class: 'f' }, 'Group', grp), h('label', { class: 'f' }, 'Start from', like, h('span', { class: 'hint' }, 'You can change every tick afterwards.'))),
    actions: [{ label: 'Cancel' }, { label: 'Create role', primary: true, run: () => {
      const n = name.value.trim(); if (!n) { toast('Give it a name'); return false; }
      DB.roleGroups.find(g => g.id === grp.value).roles.push(n);
      DB.usecases.forEach(u => DB.permissions[u.id][n] = like.value ? clone(DB.permissions[u.id][like.value]) : { see: 'none', raise: false, assign: false, close: false, manage: false });
      toast('Role “' + n + '” created'); render();
    } }] });
}

// ---------------- people ----------------
function screenPeople(root) {
  drawTop([h('b', null, 'People')]);
  add(root, head('People', 'Everyone who can use the chat bot or this dashboard.', h('button', { class: 'btn' }, '⬆ Import a CSV'), h('button', { class: 'btn pri' }, '+ Add person')),
    h('div', { class: 'card' }, h('table', { class: 't' }, h('tr', null, ['Name', 'Role', 'Flat', 'On records'].map(c => h('th', null, c))),
      DB.people.map(p => h('tr', null, h('td', null, h('div', { class: 'row' }, h('div', { class: 'av' }, p.name.split(' ').map(x => x[0]).join('').slice(0, 2)), h('b', null, p.name))), h('td', null, pill(p.role)), h('td', null, p.flat || '—'),
        h('td', { class: 'small muted' }, DB.usecases.flatMap(u => DB.records[u.record].people.filter(k => k.sample === p.name).map(k => u.icon + ' ' + k.label)).join(', ') || '—'))))));
}

// ---------------- flows & blocks libraries ----------------
function screenFlows(root) {
  drawTop([h('b', null, 'All flows')]);
  add(root, head('All flows', 'Every flow, grouped by use case.', h('button', { class: 'btn pri', onclick: () => newFlowModal() }, '+ New flow')),
    DB.usecases.map(u => [h('h3', { style: { margin: '18px 0 10px', fontSize: '14px' } }, u.icon + ' ' + u.name), h('div', { class: 'grid g3' }, DB.flows.filter(f => f.usecase === u.id).map(flowCard), h('div', { class: 'uc new', style: { minHeight: '110px' }, onclick: () => newFlowModal(u.id) }, '+ New ' + u.name.toLowerCase() + ' flow'))]));
}
function screenBlocks(root) {
  drawTop([h('b', null, 'Building blocks')]);
  add(root, head('Building blocks', 'Small steps with a name that many flows reuse. Change one here and every flow that uses it changes, after you see which.', h('button', { class: 'btn pri', onclick: () => newBlockModal() }, '+ New building block')),
    DB.usecases.concat([{ id: '', name: 'Shared by every use case', icon: '🌐' }]).map(u => { const l = DB.blocks.filter(b => (b.usecase || '') === u.id); return l.length ? [h('h3', { style: { margin: '18px 0 10px', fontSize: '14px' } }, u.icon + ' ' + u.name), h('div', { class: 'grid g3' }, l.map(blockCard))] : null; }));
}

// ---------------- create things ----------------
function newUsecaseModal() {
  const name = h('input', { type: 'text', placeholder: 'e.g. Parking, Maintenance bills, Notices' });
  const icon = h('input', { type: 'text', value: '🅿️' });
  const desc = h('input', { type: 'text', placeholder: 'One line about it' });
  const keep = h('select', null, h('option', { value: '__new' }, 'Something new: design it in Data & schema'), Object.entries(DB.records).map(([k, R]) => h('option', { value: k }, R.plural + ' (already exists)')));
  modal({ title: 'Add a use case', body: h('div', { class: 'col' }, h('label', { class: 'f' }, 'Name', name), h('label', { class: 'f' }, 'Icon', icon), h('label', { class: 'f' }, 'About it', desc), h('label', { class: 'f' }, 'What does it keep?', keep, h('span', { class: 'hint' }, 'A use case keeps one kind of record, like tickets or bookings. A new kind is designed by a super admin in Data & schema.'))),
    actions: [{ label: 'Cancel' }, { label: 'Add use case', primary: true, run: () => {
      const n = name.value.trim(); if (!n) { toast('Give it a name'); return false; }
      const id = slug(n), rec = keep.value === '__new' ? slug(n).replace(/s$/, '') : keep.value;
      if (!DB.records[rec]) DB.records[rec] = { label: n.replace(/s$/, ''), plural: n, prefix: n.slice(0, 2).toUpperCase(), fields: [{ key: 'number', label: 'Number', type: 'text', system: true, sample: n.slice(0, 2).toUpperCase() + '-26-0001' }], statuses: ['Open', 'Done'], people: [{ key: 'owner', label: 'Created it', sample: 'Venkatesh Batchu' }] };
      DB.usecases.push({ id, name: n, icon: icon.value || '📁', color: '#5b5bd6', record: rec, desc: desc.value || '', menu: ['Create', 'Mine'] });
      DB.usecases.forEach(u => { if (!DB.permissions[u.id]) { DB.permissions[u.id] = {}; DB.roleGroups.forEach(g => g.roles.forEach(r => DB.permissions[u.id][r] = { see: 'own', raise: true, assign: false, close: false, manage: false })); } });
      DB.items[id] = [];
      toast('“' + n + '” added. Next: its fields in Data & schema.');
      go(keep.value === '__new' ? 'schema' : 'uc', keep.value === '__new' ? rec : id);
    } }] });
}
// "What starts this flow?" — the same choices as the canvas, in plain words
function newFlowModal(ucId) {
  let usecase = ucId || DB.usecases[0].id, start = null;
  const body = h('div', { class: 'col' });
  const name = h('input', { type: 'text', placeholder: 'e.g. Cancel a booking' });
  function draw() {
    fill(body,
      h('label', { class: 'f' }, 'Name', name),
      h('label', { class: 'f' }, 'Use case', h('select', { onchange: e => usecase = e.target.value }, DB.usecases.map(u => h('option', { value: u.id, selected: u.id === usecase }, u.icon + ' ' + u.name)))),
      h('div', { class: 'f' }, h('b', { class: 'small' }, 'What starts it?')),
      h('div', { class: 'grid g2' }, Object.entries(STEPS).filter(([k, s]) => s.start && s.kind === 'start').map(([k, s]) => h('div', { class: 'pk' + (start === k ? ' focus' : ''), style: { border: '1px solid ' + (start === k ? 'var(--brand)' : 'var(--line)') }, onclick: () => { start = k; draw(); } }, h('span', { class: 'dot', style: { background: KINDS.start.color } }, s.icon), h('div', null, h('b', null, s.name), h('small', null, s.help))))),
      h('div', { class: 'small muted' }, 'You can describe it to the AI helper instead: ', h('a', { href: '#', onclick: e => { e.preventDefault(); toast('The AI helper drafts the flow on the canvas; you check every step.'); } }, '✨ Describe it')));
  }
  draw();
  modal({ title: 'New flow', size: 'mid', body, actions: [{ label: 'Cancel' }, { label: 'Create and open the canvas', primary: true, run: () => {
    if (!name.value.trim()) { toast('Give it a name'); return false; }
    const s = start || 'chat';
    const f = { id: uid('f_'), usecase, name: name.value.trim(), on: false, access: { everyone: false, roles: [], kinds: [] }, lastUsed: 'never', graph: { nodes: [{ id: 'n1', type: s, x: 80, y: 180, cfg: s === 'chat' ? { menu: { usecase, group: uc(usecase).menu[0] }, phrases: [] } : {} }], edges: [] } };
    DB.flows.push(f); go('flow', f.id);
  } }] });
}
function newBlockModal(ucId) {
  const name = h('input', { type: 'text', placeholder: 'e.g. Cancel a booking and tell the committee' });
  const where = h('select', null, DB.usecases.map(u => h('option', { value: u.id, selected: u.id === ucId }, u.icon + ' ' + u.name)), h('option', { value: '' }, '🌐 Shared by every use case'));
  const needs = [], gives = [];
  modal({ title: 'New building block', size: 'mid', body: h('div', { class: 'col' }, h('label', { class: 'f' }, 'Name', name), h('label', { class: 'f' }, 'Belongs to', where),
    editableList('It needs', 'What a flow must hand it, e.g. Booking, Reason.', needs, '+ add'), editableList('It gives back', 'What later steps of the flow can use.', gives, '+ add')),
    actions: [{ label: 'Cancel' }, { label: 'Create and open', primary: true, run: () => {
      if (!name.value.trim()) { toast('Give it a name'); return false; }
      const b = { id: uid('b_'), usecase: where.value, name: name.value.trim(), desc: '', needs: needs.slice(), gives: gives.map(g => [slug(name.value) + '.' + slug(g), g, '…']), version: 1,
        graph: { nodes: [{ id: 'g', type: 'gets', x: 80, y: 160, cfg: { needs: needs.slice() } }, { id: 'o', type: 'gives', x: 560, y: 160, cfg: { gives: gives.slice() } }], edges: [] } };
      DB.blocks.push(b); go('block', b.id);
    } }] });
}
