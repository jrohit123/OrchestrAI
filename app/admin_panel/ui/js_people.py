JS = r"""
// ───────────────────────── People & access ─────────────────────────
const LEVELS = { 1: 'See only', 2: 'Can start', 3: 'Can work on', 4: 'Full control' };
const GRANT_STATE = { live: ['Live', 'ok'], scheduled: ['Starts later', 'info'], expired: ['Expired', ''], revoked: ['Revoked', ''] };
// Remove this line when the chat bot starts reading special access.
const ACCESS_NOTICE = 'Not active yet. What you add here is only a note: the chat bot does not read it, so it does not change what anyone can do. To let a role use a flow, tick it under Roles. To let someone act on complaints sent to them, make them the holder of a seat or name them in a rule under Case rules.';
const homeText = x => (x.wing ? x.wing + '-' : '') + x.flat_no + ' · ' + pretty(x.residential_status);

function kvEditor(initial, keyHints) {
  const rows = h('div', { class: 'stack' });
  const listId = 'kv' + Math.random().toString(36).slice(2, 8);
  const hints = h('datalist', { id: listId }, (keyHints || []).map(k => h('option', { value: k })));
  function addRow(k, v) {
    const row = h('div', { class: 'row' }, h('input', { type: 'text', placeholder: 'field (e.g. tower)', list: listId, value: k || '', style: { width: '40%' } }),
      h('input', { type: 'text', placeholder: 'value', value: v == null ? '' : v, style: { flex: 1 } }),
      h('button', { class: 'x', type: 'button', onclick: () => row.remove() }, '×'));
    rows.append(row);
  }
  Object.entries(initial || {}).forEach(([k, v]) => addRow(k, v));
  return {
    el: h('div', null, hints, rows, h('button', { class: 'btn sm', type: 'button', onclick: () => addRow('', '') }, '+ Add a condition')),
    value() {
      const out = {};
      rows.querySelectorAll('.row').forEach(r => { const [k, v] = r.querySelectorAll('input'); if (k.value.trim()) { const t = v.value.trim(); out[k.value.trim()] = t === 'true' ? true : t === 'false' ? false : (t !== '' && !isNaN(t) ? Number(t) : t); } });
      return out;
    },
  };
}
function targetEditor(lk, initial, allowNone) {
  const type = sel([...(allowNone ? [['', 'Nobody (no backup)']] : []), ['user', 'A person'], ['seat', 'Whoever holds a seat'], ['role', 'Everyone with a role']], initial ? initial.type : (allowNone ? '' : 'user'));
  const slot = h('div', { style: { marginTop: '6px' } });
  let ctl = null;
  function draw() {
    clear(slot); ctl = null;
    const t = type.value;
    if (t === 'user') { ctl = personPicker({ placeholder: 'Type a name…', initial: initial && initial.type === 'user' ? { id: initial.id, name: initial.name } : null }); slot.append(ctl.el); }
    else if (t === 'seat') { ctl = sel([['', 'Choose a seat…'], ...lk.seats.map(s => [s.id, s.name])], initial && initial.type === 'seat' ? initial.id : ''); slot.append(ctl); }
    else if (t === 'role') { ctl = sel([['', 'Choose a role…'], ...lk.roles.map(r => [r.id, r.name])], initial && initial.type === 'role' ? initial.id : ''); slot.append(ctl); }
  }
  type.addEventListener('change', draw); draw();
  return { el: h('div', null, type, slot), value() { if (!type.value) return null; const id = ctl && (ctl.value !== undefined ? ctl.value : null); return id ? { type: type.value, id } : false; } };
}

// ----- person drawer -----
async function showPerson(id) {
  drawerKey = 'person:' + id;
  const dr = openDrawer('Loading…', h('div', { class: 'empty' }, 'Loading…'));
  try {
    const [d, lk] = await Promise.all([api.get('/people/' + id), getLookups()]);
    if (drawer !== dr) return;
    const p = d.person, body = [];
    const reload = () => showPerson(id);
    fill(dr.titleEl, p.name, h('div', { class: 'row', style: { marginTop: '6px' } }, badge(p.role || 'No role', 'brand'), p.is_active ? badge('Active', 'ok') : badge('Inactive'), p.reachable ? badge('Can be messaged', 'info') : badge('Cannot be messaged yet', 'warn')));
    // account
    const role = sel([['', 'No role'], ...lk.roles.map(r => [r.id, r.name])], p.role_id || '');
    const saveRole = h('button', { class: 'btn sm primary', disabled: true, onclick: async e => { e.target.disabled = true; try { await api.patch('/people/' + id, { role_id: role.value }); toast('Role saved', 'ok'); reload(); } catch (x) { toast(x.message, 'bad'); e.target.disabled = false; } } }, 'Save role');
    role.addEventListener('change', () => { saveRole.disabled = !role.value || role.value === (p.role_id || ''); });
    body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Account'), h('div', { class: 'card-b stack' },
      h('div', { class: 'row' }, h('span', { class: 'muted', style: { width: '90px' } }, 'Role'), role, saveRole, h('a', { class: 'small', href: href('access', '', { role: p.role_id || '' }) }, 'What can this role do?')),
      h('div', { class: 'row' }, h('span', { class: 'muted', style: { width: '90px' } }, 'Active'), switchEl(p.is_active, async v => { await api.patch('/people/' + id, { is_active: v }); toast(v ? 'Switched on' : 'Switched off', 'ok'); reload(); }),
        h('span', { class: 'muted small' }, 'Inactive people cannot use the chat bot and cannot be given cases.')),
      h('div', { class: 'row' }, h('span', { class: 'muted', style: { width: '90px' } }, 'Email'), p.email || '—'),
      h('div', { class: 'row' }, h('span', { class: 'muted', style: { width: '90px' } }, 'Messaging'), p.reachable ? 'Linked (' + (p.phone_hint || '') + ')' : h('span', null, h('b', null, 'Not on ' + chatWord() + ' yet. '), 'Ask them to send their email address to the chat bot once. It links them straight away. ',
        h('button', { class: 'btn sm', type: 'button', style: { marginTop: '6px' }, onclick: () => navigator.clipboard && navigator.clipboard.writeText('Hi ' + p.name.split(' ')[0] + ', you can now use the ' + S.boot.org.name + ' chat bot. Open its chat on ' + chatWord() + ' and send it your email address (' + (p.email || '') + ') once. It will link you to your account.').then(() => toast('Message copied. Send it to ' + p.name.split(' ')[0] + '.', 'ok')) }, icon('copy', 'sm'), 'Copy the message to send'))),
      h('div', { class: 'row' }, h('span', { class: 'muted', style: { width: '90px' } }, 'Added'), fmtD(p.created_at)),
      d.chats && d.chats.turns ? h('div', { class: 'row' }, h('span', { class: 'muted', style: { width: '90px' } }, 'Chats'), plural(d.chats.turns, 'message'), ' · last ' + ago(d.chats.last_at), h('a', { class: 'btn sm', href: href('conversations', '', { user: id }) }, 'View chats →')) : null)));
    // homes
    if (S.boot.caps.residents && d.homes.length) {
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Home'), h('div', { class: 'card-b stack' }, d.homes.map(x => {
        const type = sel((lk.enums.resident_types || [x.residential_status]).map(v => [v, pretty(v)]), x.residential_status);
        const stat = sel((lk.enums.resident_statuses || [x.status]).map(v => [v, pretty(v)]), x.status);
        const wing = h('input', { type: 'text', value: x.wing || '', placeholder: 'Wing', style: { width: '90px' } });
        const flat = h('input', { type: 'text', value: x.flat_no, placeholder: 'Flat', style: { width: '110px' } });
        return h('div', { class: 'stack', style: { paddingBottom: '10px', borderBottom: '1px solid var(--line)' } },
          h('div', { class: 'row' }, wing, flat, type, stat),
          h('div', { class: 'row' }, h('button', { class: 'btn sm primary', onclick: async e => {
            e.target.disabled = true;
            try { const r = await api.patch('/people/' + id + '/homes/' + x.id, { wing: wing.value.trim() || null, flat_no: flat.value.trim(), residential_status: type.value, status: stat.value });
              toast('Saved. ' + p.name + ' is now ' + (r.user_is_active ? 'active' : 'inactive') + '.', 'ok'); reload(); }
            catch (err) { toast(err.message, 'bad'); e.target.disabled = false; } } }, 'Save home'),
            h('span', { class: 'muted small' }, 'Changing the status also updates whether the person is active.')));
      }))));
    }
    // seats
    if (S.boot.caps.seats) {
      const cur = d.seat_history.filter(s => s.status === 'active'), past = d.seat_history.filter(s => s.status !== 'active');
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Seats', h('a', { class: 'small', href: href('access', 'seats') }, 'Manage seats')), h('div', { class: 'card-b stack' },
        cur.length ? h('div', { class: 'chips' }, cur.map(s => badge(s.seat, 'brand'))) : h('span', { class: 'muted' }, 'Holds no seat right now.'),
        past.length ? h('div', { class: 'muted small' }, 'Held before: ' + past.map(s => s.seat + ' (' + fmtD(s.start_date) + ' – ' + fmtD(s.end_date) + ')').join(', ')) : null)));
    }
    // special access
    if (S.boot.caps.grants) {
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Special access', h('button', { class: 'btn sm', onclick: () => grantModal(lk, { subject_type: 'user', subject_id: id, name: p.name }, reload) }, 'Give access')),
        d.grants.length ? grantTable(d.grants, reload, true) : h('div', { class: 'card-b muted' }, 'None. They can do what their role allows.')));
    }
    // cases
    if (S.boot.caps.cases && (d.cases.handling.length || d.cases.raised.length)) {
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Handling now'), d.cases.handling.length ? d.cases.handling.map(caseLine) : h('div', { class: 'card-b muted' }, 'Nothing.')));
      body.push(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Raised by them', h('a', { class: 'small', href: href('cases', '', { q: p.name }) }, 'Search cases')), d.cases.raised.length ? d.cases.raised.map(caseLine) : h('div', { class: 'card-b muted' }, 'Nothing.')));
    }
    clear(dr.bodyEl); add(dr.bodyEl, body);
  } catch (e) { if (drawer === dr) { dr.titleEl.textContent = 'Person'; clear(dr.bodyEl); dr.bodyEl.append(notice(e.message, 'bad')); } }
}

// ----- special access -----
function scopeChips(scope) {
  const e = Object.entries(scope || {});
  return e.length ? h('div', { class: 'chips' }, e.map(([k, v]) => h('span', { class: 'chip' }, pretty(k) + ': ' + v))) : h('span', { class: 'muted' }, 'Everything');
}
function grantTable(rows, reload, compact) {
  return table([
    compact ? null : { label: 'Who', render: g => h('div', null, person(g.subject_type === 'user' ? g.subject_id : null, g.subject_name), h('div', { class: 'muted small' }, g.subject_type === 'user' ? '' : (g.subject_type === 'seat' ? 'Whoever holds this seat' : 'Everyone with this role'))) },
    { label: 'Can use', render: g => g.workflow_key === '*' ? 'Everything' : (g.workflow_name || g.workflow_key) },
    { label: 'How much', render: g => LEVELS[g.level] || g.level },
    { label: 'Limited to', render: g => scopeChips(g.scope) },
    { label: 'When', render: g => g.valid_from || g.valid_to ? (g.valid_from ? fmtD(g.valid_from) : 'now') + ' → ' + (g.valid_to ? fmtD(g.valid_to) : 'no end') : 'No end date' },
    { label: '', render: g => h('div', { class: 'row' }, badge(GRANT_STATE[g.state][0], GRANT_STATE[g.state][1]), g.revoked_at ? null : h('button', { class: 'btn sm danger', onclick: async () => {
      if (!await confirmBox('Take this access away? It stays in the list as revoked.', { ok: 'Revoke', danger: true })) return;
      try { await api.post('/grants/' + g.id + '/revoke'); toast('Revoked', 'ok'); reload(); } catch (e) { toast(e.message, 'bad'); } } }, 'Revoke')) },
  ].filter(Boolean), rows);
}
function grantModal(lk, preset, done) {
  preset = preset || {};
  const type = sel([['user', 'A person'], ['seat', 'Whoever holds a seat'], ['role', 'Everyone with a role']], preset.subject_type || 'user');
  const slot = h('div', { style: { marginTop: '6px' } });
  let ctl;
  function drawSubject() {
    clear(slot);
    if (type.value === 'user') { ctl = personPicker({ initial: preset.subject_type === 'user' && preset.subject_id ? { id: preset.subject_id, name: preset.name } : null }); slot.append(ctl.el); }
    else if (type.value === 'seat') { ctl = sel([['', 'Choose a seat…'], ...lk.seats.map(s => [s.id, s.name])], ''); slot.append(ctl); }
    else { ctl = sel([['', 'Choose a role…'], ...lk.roles.map(r => [r.id, r.name])], ''); slot.append(ctl); }
  }
  type.addEventListener('change', drawSubject); drawSubject();
  const flows = lk.workflows.filter(w => w.kind !== 'block');
  const what = sel([['*', 'Everything'], ...flows.map(w => [w.intent_key, w.name])], '*');
  const level = sel(Object.entries(LEVELS).map(([k, v]) => [k, k + ' · ' + v]), 3);
  const cat = S.boot.caps.categories ? sel(catOptions(lk, 'Any category'), '') : null;
  const extra = kvEditor({}, []);
  const from = h('input', { type: 'date' }), until = h('input', { type: 'date' });
  const note = h('input', { type: 'text', placeholder: 'Why (optional)' });
  modal({
    title: 'Give special access', wide: true,
    body: h('div', null, notice(ACCESS_NOTICE), field('Who gets it', h('div', null, type, slot)), h('div', { class: 'two' }, field('What they can use', what), field('How much', level)),
      cat ? field('Only for this category', cat, 'Leave on “Any category” to cover everything. Sub-categories are included.') : null,
      field('Other conditions (optional)', extra.el, 'For example tower = B. Leave empty for no extra limit.'),
      h('div', { class: 'two' }, field('From', from), field('Until', until, 'Leave empty for no end date.')), field('Note', note)),
    actions: [{ label: 'Cancel' }, { label: 'Give access', primary: true, run: async () => {
      const subject = ctl.value !== undefined ? ctl.value : null;
      if (!subject) throw new Error('Choose who gets the access.');
      const scope = { ...extra.value() };
      if (cat && cat.value) scope.category = lk.categories.find(c => c.id === cat.value).key;
      await api.post('/grants', { subject_type: type.value, subject_id: subject, workflow_key: what.value, level: Number(level.value), scope, valid_from: from.value || null, valid_to: until.value || null, note: note.value.trim() || null });
      toast('Access saved', 'ok'); if (done) done();
    } }],
  });
}

// ───────────────────────── People ─────────────────────────
// How this organisation reaches people, in the words a person would use ("Telegram", "WhatsApp")
const chatWord = () => pretty((S.boot.org && S.boot.org.channel) || 'telegram');

function addPersonModal(lk) {
  const byNumber = (S.boot.org.channel || 'telegram') !== 'telegram';
  const name = h('input', { class: 'input', type: 'text', placeholder: 'Full name', maxlength: 80 });
  const email = h('input', { class: 'input', type: 'text', placeholder: 'name@example.com', maxlength: 160 });
  const phone = byNumber ? h('input', { class: 'input', type: 'text', placeholder: '+91 98765 43210', maxlength: 40 }) : null;
  const role = sel([['', 'Choose a role…'], ...lk.roles.map(r => [r.id, roleLabel(r.name)])], '');
  modal({ title: 'Add person',
    body: h('div', null, field('Name', name), field('Email', email, byNumber ? 'Needed to tell people apart.' : 'The chat bot links them to this account when they send it.'),
      phone ? field('WhatsApp number', phone, 'With the country code, like +91 98765 43210. The chat bot knows them by this number.') : null,
      field('Role', role, h('span', null, 'Not sure? ', h('a', { href: href('access') }, 'See what each role can do'), '.'))),
    actions: [{ label: 'Cancel' }, { label: 'Add person', primary: true, run: async () => {
      if (name.value.trim().length < 2) throw new Error('Write the person’s name.');
      if (!email.value.trim()) throw new Error('Write their email address.');
      if (!role.value) throw new Error('Choose a role.');
      if (phone && !phone.value.trim()) throw new Error('Write their WhatsApp number.');
      const r = await api.post('/people', { name: name.value.trim(), email: email.value.trim(), role_id: role.value, phone: phone ? phone.value.trim() : null });
      toast('Added ' + name.value.trim(), 'ok');
      getLookups(true).catch(() => {});
      lastSig = ''; location.hash = href('people', '', { person: r.id });
    } }] });
}

async function renderPeopleTab(root, route) {
  const mine = S.renderId;
  const lk = await getLookups();
  const q = { ...route.q }; delete q.person; q.page = Number(q.page || 1);
  setTopAction({ label: 'Add person', run: () => addPersonModal(lk) });
  const bar = h('div', { class: 'filters' }), chips = h('div', { class: 'chips', style: { marginBottom: '12px' } }), out = h('div', { class: 'card' });
  root.append(bar, chips, out);
  const update = patch => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
  const search = h('input', { type: 'search', placeholder: 'Search name, email or flat', value: q.q || '', style: { flex: 1, minWidth: '220px', maxWidth: '340px' }, 'aria-label': 'Search people' });
  search.addEventListener('input', debounce(() => update({ q: search.value }), 300));
  const roleChips = h('div', { class: 'chips' });
  const filtersBtn = h('button', { class: 'btn', type: 'button', 'data-popkeep': '1', onclick: e => openFilters(e.currentTarget) });
  add(bar, [search, roleChips, filtersBtn, h('span', { class: 'sp' }), h('a', { class: 'btn ghost sm', href: href('access') }, 'Manage roles', icon('arrowr', 'xs'))]);
  const extra = () => ['status', 'reachable', 'seat'].filter(k => q[k]).length;
  function openFilters(anchor) {
    openPop(anchor, h('div', { class: 'stack s8', style: { padding: '10px' } },
      field('Active or not', sel([['', 'Either'], ['active', 'Active'], ['inactive', 'Inactive']], q.status || '', { onchange: e => update({ status: e.target.value }) })),
      field('Can be messaged', sel([['', 'Either'], ['true', 'Yes'], ['false', 'Not yet']], q.reachable || '', { onchange: e => update({ reachable: e.target.value }) })),
      S.boot.caps.seats ? field('Holds the seat', sel([['', 'Any'], ...lk.seats.map(s => [s.id, s.name])], q.seat || '', { onchange: e => update({ seat: e.target.value }) })) : null), { width: 280 });
  }
  function drawBar() {
    const everyone = lk.roles.reduce((a, r) => a + r.users, 0);
    const rc = (label, n, val) => h('button', { type: 'button', class: 'chip' + ((q.role || '') === val ? ' on' : ''), onclick: () => update({ role: val }) }, label + ' ', h('span', { style: { opacity: .7 } }, n));
    fill(roleChips, rc('Everyone', everyone, ''), lk.roles.filter(r => r.users || r.id === q.role).map(r => rc(roleLabel(r.name), r.users, r.id)));
    const list = [];
    const chip = (label, patch) => list.push(h('span', { class: 'chip' }, label, h('button', { class: 'x', type: 'button', 'aria-label': 'Remove ' + label, style: { fontSize: '16px', padding: '0 2px' }, onclick: () => update(patch) }, '×')));
    if (q.status) chip(q.status === 'active' ? 'Active' : 'Inactive', { status: '' });
    if (q.reachable) chip(q.reachable === 'true' ? 'Can be messaged' : 'Cannot be messaged yet', { reachable: '' });
    if (q.seat) chip('Seat: ' + ((lk.seats.find(s => s.id === q.seat) || {}).name || 'chosen'), { seat: '' });
    fill(chips, list, list.length ? h('button', { class: 'btn ghost sm', type: 'button', onclick: () => { closePop(); update({ status: '', reachable: '', seat: '' }); } }, 'Clear') : null);
    chips.style.display = list.length ? '' : 'none';
    fill(filtersBtn, icon('filter', 'sm'), extra() ? 'Filters · ' + extra() : 'Filters');
  }
  async function load() {
    if (mine !== S.renderId) return;
    setQuery(q);
    drawBar();
    fill(out, h('div', { class: 'empty' }, 'Loading…'));
    try {
      const d = await api.get('/people', { q: q.q, role: q.role, status: q.status, reachable: q.reachable, seat: q.seat, page: q.page, page_size: 50 });
      fill(out, table([
        { label: 'Person', cls: 'wide', render: p => h('div', { class: 'person' }, avatar(p.name), h('div', null, h('div', null, h('b', null, p.name), p.is_active ? null : [' ', badge('Inactive')]), h('div', { class: 'muted small' }, p.email || ''))) },
        { label: 'Role', render: p => p.role ? badge(roleLabel(p.role), 'brand') : h('span', { class: 'muted' }, '—') },
        S.boot.caps.residents || S.boot.caps.seats ? { label: 'Home or seat', render: p => (p.homes.length || p.seats.length) ? h('div', null, p.homes.slice(0, 2).map(x => h('div', { class: 'small' }, homeText(x), x.status !== 'active' ? ' ' : '', x.status !== 'active' ? badge(pretty(x.status), 'warn') : null)),
          p.seats.length ? h('div', { class: 'chips' }, p.seats.map(s => badge(s.name))) : null) : h('span', { class: 'muted' }, '—') } : null,
        { label: 'On ' + chatWord(), render: p => p.reachable ? badge('Yes', 'ok') : badge('Not yet', 'warn') },
      ].filter(Boolean), d.rows, { onRow: p => go('people', '', { ...q, person: p.id }), emptyTitle: 'No one matches', emptyText: 'Try removing a filter.' }),
      pager(d.total, d.page, d.page_size, p => update({ page: p })));
    } catch (e) { fill(out, notice(e.message, 'bad')); }
  }
  await load();
}

// ───────────────────────── Seats tab ─────────────────────────
async function renderSeatsTab(root) {
  const [d, lk] = await Promise.all([api.get('/seats'), getLookups(true)]);
  const again = () => { clear(root); renderSeatsTab(root); };
  setTopAction({ label: 'New seat', run: () => seatModal(d.kinds, null, again) });
  root.append(h('div', { class: 'muted', style: { marginBottom: '12px' } }, 'A seat is a named job — Chairman, Lift in-charge — held by one person at a time. Case rules can point at a seat, so changing the holder never means editing rules.'));
  root.append(h('div', { class: 'seatgrid' }, d.rows.map(s => h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
    h('div', { class: 'row between' }, h('b', null, s.name), s.kind ? badge(pretty(s.kind), s.kind === 'committee' ? 'brand' : '') : null),
    s.description ? h('div', { class: 'muted small' }, s.description) : null,
    s.holder_id ? h('div', { class: 'row' }, person(s.holder_id, s.holder_name), h('span', { class: 'muted small' }, 'since ' + fmtD(s.holder_since)), s.holder_active ? null : badge('inactive', 'warn')) : badge('Empty', 'warn'),
    h('div', { class: 'muted small' }, plural(s.rules_using, 'case rule') + ' use this seat' + (s.grants_using ? ' · ' + plural(s.grants_using, 'special access') : '')),
    h('div', { class: 'row' },
      h('button', { class: 'btn sm primary', onclick: () => holderModal(s, again) }, 'Change holder'),
      h('button', { class: 'btn sm', onclick: () => seatModal(d.kinds, s, again) }, 'Edit'),
      h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'More for ' + s.name, 'data-popkeep': '1', onclick: e => openPop(e.currentTarget, [
        h('button', { class: 'mi', type: 'button', onclick: () => { closePop(); historyModal(s); } }, icon('hist'), 'History'),
        h('button', { class: 'mi', type: 'button', style: { color: 'var(--bad)' }, onclick: async () => { closePop(); if (!await confirmBox('Delete the seat “' + s.name + '”?', { ok: 'Delete', danger: true })) return; try { await api.del('/seats/' + s.id); toast('Deleted', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('trash'), 'Delete')], { align: 'right', width: 180 }) }, icon('dots', 'sm'))))))));
  if (!d.rows.length) root.append(empty('No seats yet', 'Create one, then put someone in it.'));
}
function seatModal(kinds, seat, done) {
  const name = h('input', { type: 'text', value: seat ? seat.name : '', placeholder: 'e.g. Lift in-charge' });
  const kind = sel((kinds.length ? kinds : ['volunteer']).map(k => [k, pretty(k)]), seat ? seat.kind : 'volunteer');
  const descr = h('textarea', { placeholder: 'What this job is for (optional)' }, seat && seat.description ? seat.description : '');
  descr.value = seat && seat.description ? seat.description : '';
  modal({ title: seat ? 'Edit seat' : 'New seat', body: h('div', null, field('Name', name), field('Kind', kind, 'A committee seat also switches its holder to the committee role. Other kinds never touch roles.'), field('Description', descr)),
    actions: [{ label: 'Cancel' }, { label: 'Save', primary: true, run: async () => {
      const b = { name: name.value.trim(), kind: kind.value, description: descr.value.trim() || null };
      if (seat) await api.patch('/seats/' + seat.id, b); else await api.post('/seats', b);
      toast('Saved', 'ok'); done();
    } }] });
}
function holderModal(s, done) {
  const pick = personPicker({ initial: s.holder_id ? { id: s.holder_id, name: s.holder_name } : null });
  modal({ title: 'Who holds “' + s.name + '”?', body: h('div', null, field('Holder', pick.el, 'The earlier holder is kept in the history, not deleted.'),
      s.kind === 'committee' ? notice('This is a committee seat: the system also switches the person’s role when they take or leave it.', 'warn') : null),
    actions: [{ label: 'Cancel' }, s.holder_id ? { label: 'Leave empty', danger: true, run: async () => { await api.put('/seats/' + s.id + '/holder', { user_id: null }); toast('Seat is empty now', 'ok'); done(); } } : null,
      { label: 'Save holder', primary: true, run: async () => { if (!pick.value) throw new Error('Choose a person (or use “Leave empty”).'); const r = await api.put('/seats/' + s.id + '/holder', { user_id: pick.value }); toast('Saved' + (r.role_now ? ' · role is now ' + r.role_now : ''), 'ok'); done(); } }].filter(Boolean) });
}
async function historyModal(s) {
  const d = await api.get('/seats/' + s.id + '/history');
  modal({ title: 'History of “' + s.name + '”', body: d.rows.length ? table([{ label: 'Person', render: r => person(r.user_id, r.name) }, { label: 'From', render: r => fmtD(r.start_date) }, { label: 'Until', render: r => r.status === 'active' ? badge('Current', 'ok') : fmtD(r.end_date) }], d.rows) : empty('Nobody has held it yet', ''), actions: [{ label: 'Close' }] });
}

// ───────────────────────── Special access tab ─────────────────────────
async function renderAccessTab(root, route) {
  const lk = await getLookups();
  const state = route.q.state === 'all' ? 'all' : 'live';
  const d = await api.get('/grants', { state });
  const again = () => { clear(root); renderAccessTab(root, parseRoute()); };
  setTopAction({ label: 'Give access', run: () => grantModal(lk, null, again) });
  root.append(notice(ACCESS_NOTICE, 'warn'), h('div', { style: { marginBottom: '12px' } },
    sel([['live', 'Live and upcoming'], ['all', 'Everything, including old']], state, { onchange: e => { setQuery({ state: e.target.value }); clear(root); renderAccessTab(root, parseRoute()); } })),
    h('div', { class: 'card' }, d.rows.length ? grantTable(d.rows, again, false) : empty('No special access', 'Everyone can do what their role allows.')));
}

// ───────────────────────── Roles tab (who may use which workflow) ─────────────────────────
async function renderRolesTab(root) {
  const [d, lk] = await Promise.all([api.get('/workflows'), getLookups(true)]);
  const roles = d.roles, users = Object.fromEntries(lk.roles.map(r => [r.id, r.users]));
  root.append(h('div', { class: 'muted', style: { marginBottom: '12px' } }, 'Tick a box to let a role use that flow. This is the same setting as “Who can use it” on the Flows screen.'));
  const flows = d.rows.filter(w => w.kind !== 'block');
  root.append(h('div', { class: 'card' }, !flows.length ? empty('No flows yet', '') : h('div', { class: 'tablewrap' }, h('table', { class: 't matrix' },
    h('thead', null, h('tr', null, h('th', null, 'Flow'), roles.map(r => h('th', null, r.name, h('div', { class: 'muted small', style: { textTransform: 'none', letterSpacing: 0 } }, plural(users[r.id] || 0, 'person', 'people')))))),
    h('tbody', null, flows.map(w => h('tr', null,
      h('td', null, h('b', null, w.name), w.is_active ? null : [' ', badge('off')], h('div', { class: 'muted small' }, w.description || w.intent_key)),
      roles.map(r => { const cb = h('input', { type: 'checkbox', checked: w.granted_roles.includes(r.name) });
        cb.addEventListener('change', async () => {
          const next = cb.checked ? [...w.granted_roles, r.name] : w.granted_roles.filter(x => x !== r.name);
          cb.disabled = true;
          try { await api.put('/workflows/' + w.id + '/roles', { roles: next }); w.granted_roles = next; }
          catch (e) { cb.checked = !cb.checked; toast(e.message, 'bad'); } finally { cb.disabled = false; } });
        return h('td', null, cb); }))))))));
}

SECTIONS.people = {
  title: 'People', sub: 'Everyone who can use the chat bot, and what their role lets them do',
  async render(root, route) { return renderPeopleTab(root, route); },
};
SECTIONS.access = {
  title: 'Roles & access', sub: 'Who may do what. Make a role, or change what an existing one can do.',
  async render(root, route) {
    if (route.tab === 'seats') return renderSeatsTab(root);
    if (route.tab === 'special') return renderAccessTab(root, route);
    return S.boot.caps.role_editor ? renderRoleEditor(root, route) : renderRolesTab(root);
  },
};

"""
