JS = r"""
// ───────────────────────── Roles & access: the roles editor ─────────────────────────
// A role is a name, what its people may start (flows), what the chat bot may look up for them, and
// whether they may approve. Every list here comes from the database; nothing on this screen knows what
// a particular role is for. Making a role starts from a copy of one that exists, so nobody begins empty-handed.
const roleLabel = n => pretty(n);
async function renderRoleEditor(root, route) {
  const mine = S.renderId;
  let d = await api.get('/roles');
  if (mine !== S.renderId) return;
  const st = { sel: null, draft: null, base: null };
  const list = h('div', { class: 'card rl' }), edit = h('div', { class: 'stack s16' });
  root.append(h('div', { class: 'rl-grid' }, list, edit));

  const sorted = a => [...a].sort();
  const mk = r => ({ id: r.id, name: r.name, copy: '', flows: new Set(r.can), tables: new Set(r.tables), approver: !!r.is_approver, max: r.approval_max_amount == null ? '' : String(r.approval_max_amount) });
  const snap = x => JSON.stringify([x.name.trim(), sorted(x.flows), sorted(x.tables), x.approver, x.approver ? x.max.trim() : '']);
  const roleOf = id => d.roles.find(r => r.id === id);
  const isNew = () => st.draft && !st.draft.id;
  const dirty = () => !!st.draft && (isNew() ? true : snap(st.draft) !== st.base);
  const armGuard = () => { const unsaved = st.draft && (isNew() ? !!(st.draft.name.trim() || st.draft.flows.size || st.draft.copy) : dirty()); S.leaveGuard = unsaved ? () => confirm('You have unsaved changes to this role. Leave without saving?') : null; };

  function start(id) {
    if (id === 'new') { st.sel = 'new'; st.draft = { id: null, name: '', copy: '', flows: new Set(), tables: new Set(), approver: false, max: '' }; st.base = ''; }
    else { const r = roleOf(id) || d.roles[0]; st.sel = r ? r.id : null; st.draft = r ? mk(r) : null; st.base = st.draft ? snap(st.draft) : ''; }
    armGuard(); drawList(); drawEdit();
  }
  async function pick(id) {
    if (id === st.sel) return;
    if (st.draft && ((isNew() && (st.draft.name.trim() || st.draft.flows.size)) || (!isNew() && dirty())) && !await confirmBox('You have changes that are not saved. Leave them behind?', { ok: 'Leave them', danger: true })) return;
    start(id);
  }
  async function reload(selectId) {
    d = await api.get('/roles'); getLookups(true).catch(() => {});
    start(selectId || (d.roles[0] && d.roles[0].id));
  }

  function drawList() {
    fill(list, h('div', { class: 'card-h' }, 'Roles', h('span', { class: 'muted small' }, plural(d.roles.length, 'role'))),
      isNew() ? h('a', { class: 'rl-row on', role: 'button', tabindex: '0' }, h('span', { class: 'grow' }, h('b', null, st.draft.name.trim() ? roleLabel(st.draft.name.trim()) : 'New role'), ' ', badge('Not saved yet', 'info'))) : null,
      d.roles.map(r => h('a', { class: 'rl-row' + (r.id === st.sel ? ' on' : ''), role: 'button', tabindex: '0', onclick: () => pick(r.id), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(r.id); } } },
        h('span', { class: 'grow' }, h('b', null, roleLabel(r.name))), r.built_in ? h('span', { 'data-tip': 'Built in: the database uses this role by its name' }, icon('lock', 'sm')) : null, h('span', { class: 'n muted small' }, r.people_count))),
      d.roles.length ? null : h('div', { class: 'card-b muted' }, 'No roles yet. Make the first one.'));
  }

  function drawEdit() {
    const x = st.draft;
    if (!x) { fill(edit, h('div', { class: 'card' }, empty('Pick a role', 'Or make a new one.'))); return; }
    const r = isNew() ? null : roleOf(x.id);
    const locked = !!(r && r.built_in);
    const bar = h('div', { class: 'rl-save' }), paint = () => paintBar(bar, r);
    // 1. about
    const name = h('input', { class: 'input', type: 'text', value: x.name, maxlength: 40, disabled: locked, 'aria-label': 'Name of the role', placeholder: 'e.g. second owner' });
    name.addEventListener('input', () => { x.name = name.value; armGuard(); paint(); drawList(); });
    const copy = isNew() ? sel([['', 'Nothing, start empty'], ...d.roles.map(o => [o.id, roleLabel(o.name)])], x.copy, { onchange: e => {
      x.copy = e.target.value; const o = roleOf(x.copy);
      x.flows = new Set(o ? o.can : []); x.tables = new Set(o ? o.tables : []); x.approver = !!(o && o.is_approver); x.max = o && o.approval_max_amount != null ? String(o.approval_max_amount) : '';
      drawEdit(); if (o) toast('Copied what ' + roleLabel(o.name) + ' can do. Change anything you like.', 'ok');
    } }) : null;
    const about = h('div', { class: 'card' }, h('div', { class: 'card-h' }, isNew() ? 'New role' : roleLabel(r.name), isNew() ? badge('Not saved yet', 'info') : h('span', { class: 'muted small' }, plural(r.people_count, 'person', 'people'))),
      h('div', { class: 'card-b' }, isNew() ? h('div', { class: 'two' }, field('Start from', copy, 'Copies what that role can do. You can change anything after.'), field('Name of the role', name, 'People see this name next to theirs.')) : field('Name of the role', name),
        locked ? h('div', { class: 'notice', style: { marginTop: '12px' } }, icon('lock'), h('div', null, h('b', null, 'Built in. '), 'A database rule (' + pretty(r.built_in_by).toLowerCase() + ') moves people into and out of this role by its name. You can change what it can do, but not its name, and it cannot be deleted.')) : null));
    // 2. what they can do
    const flowRow = f => h('div', { class: 'rl-perm' }, h('label', { class: 'switch' }, h('input', { type: 'checkbox', role: 'switch', 'aria-label': f.name, checked: x.flows.has(f.intent_key), onchange: e => { e.target.checked ? x.flows.add(f.intent_key) : x.flows.delete(f.intent_key); armGuard(); drawEdit(); } }), h('span')),
      h('div', null, h('b', null, f.name), f.is_active ? null : [' ', badge('off')], f.description ? h('span', { class: 'muted small rl-desc' }, f.description) : null));
    const can = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What they can do', h('span', { class: 'muted small' }, 'Each line is a flow the chat bot offers them')),
      d.flows.length ? [d.flows.map(flowRow), x.flows.size ? null : h('div', { class: 'card-b muted small' }, 'This role cannot start anything yet.')] : empty('No flows yet', 'Make one on the Flows screen first.'));
    // 3. what the chat bot may look up
    const needBy = t => d.flows.filter(f => x.flows.has(f.intent_key) && (f.needs_tables || []).includes(t)).map(f => f.name);
    const chosen = sorted(x.tables), spare = d.tables.filter(t => !x.tables.has(t));
    const tableChip = t => { const by = needBy(t); return h('span', { class: 'chip' + (by.length ? ' sunk' : ''), 'data-tip': by.length ? 'Needed by: ' + by.join(', ') : null }, pretty(t),
      by.length ? icon('lock', 'xs') : h('button', { class: 'x', type: 'button', 'aria-label': 'Remove ' + pretty(t), style: { fontSize: '16px', padding: '0 2px' }, onclick: () => { x.tables.delete(t); drawEdit(); } }, '×')); };
    const look = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'What the chat bot may look up for them', h('span', { class: 'muted small' }, 'It never reads anything outside this list')),
      h('div', { class: 'card-b stack s8' }, chosen.length ? h('div', { class: 'chips' }, chosen.map(tableChip)) : h('span', { class: 'muted' }, 'Nothing yet.'),
        spare.length ? sel([['', 'Add data…'], ...spare.map(t => [t, pretty(t)])], '', { 'aria-label': 'Add data the chat bot may look up', onchange: e => { if (e.target.value) { x.tables.add(e.target.value); drawEdit(); } } }) : null,
        r && r.entity_types.length ? h('div', { class: 'muted small' }, 'It also reads these kinds of records: ' + r.entity_types.join(', ') + '.') : null));
    // 4. approvals
    const max = h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: x.max, placeholder: 'No limit', disabled: !x.approver, 'aria-label': 'Largest amount they can approve' });
    max.addEventListener('input', () => { x.max = max.value; paint(); });
    const approve = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Approvals'), h('div', { class: 'card-b stack s8' },
      h('div', { class: 'row between' }, h('span', null, h('b', null, 'Can approve things'), h('div', { class: 'muted small' }, 'Some flows wait for an approver, for example when an amount is large.')),
        h('label', { class: 'switch' }, h('input', { type: 'checkbox', role: 'switch', 'aria-label': 'Can approve things', checked: x.approver, onchange: e => { x.approver = e.target.checked; if (!x.approver) x.max = ''; armGuard(); drawEdit(); } }), h('span'))),
      h('div', { style: { maxWidth: '280px' } }, field('Largest amount they can approve (₹)', max, 'Leave empty for no limit.'))));
    // 5. people
    const people = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'People with this role'), r && r.people.length
      ? h('div', { class: 'card-b' }, h('div', { class: 'row' }, r.people.map(n => h('span', { class: 'chip sunk' }, n)), r.people_count > r.people.length ? h('span', { class: 'muted small' }, '+' + (r.people_count - r.people.length) + ' more') : null, h('span', { class: 'sp' }), h('a', { href: href('people', '', { role: r.id }) }, 'Show on People →')))
      : h('div', { class: 'card-b muted' }, isNew() ? 'Nobody yet. Give it to people from the People screen once it is made.' : 'Nobody has this role yet. Give it to people from the People screen.'));
    // 6. the rest, for the curious
    const other = r && r.other_permissions.length ? h('details', { class: 'card' }, h('summary', { class: 'card-h', style: { cursor: 'pointer' } }, 'Technical: other permissions this role holds'),
      h('div', { class: 'card-b stack s8' }, h('div', { class: 'muted small' }, 'Flows check for these along the way. They come with the flows above, so they are kept in step for you.'), h('div', { class: 'chips' }, r.other_permissions.map(p => h('span', { class: 'chip mono' }, p))))) : null;
    fill(edit, about, can, look, approve, people, other, h('div', { class: 'card' }, bar));
    paint();
  }

  function problems() {
    const x = st.draft, out = [];
    if (x.name.trim().length < 2) out.push('Give the role a name.');
    if (x.approver && x.max.trim() !== '' && !(Number(x.max) >= 0)) out.push('The largest amount must be a number.');
    return out;
  }
  function paintBar(bar, r) {
    const x = st.draft, bad = problems(), n = r ? r.people_count : 0;
    const go = h('button', { class: 'btn primary', type: 'button', disabled: !dirty() || bad.length > 0, onclick: () => (isNew() ? create() : save()) }, isNew() ? 'Create role' : 'Save changes');
    if (isNew()) fill(bar, h('span', { class: 'muted small' }, bad.length ? bad[0] : 'This role is new. It changes nothing until you create it.'), h('span', { class: 'sp' }), h('button', { class: 'btn ghost', type: 'button', onclick: () => start(d.roles[0] && d.roles[0].id) }, 'Cancel'), go);
    else {
      const del = h('button', { class: 'btn danger', type: 'button', disabled: !!r.delete_blocked, onclick: remove }, icon('trash', 'sm'), 'Delete role');
      fill(bar, del, r.delete_blocked ? h('span', { class: 'muted small rl-why' }, r.delete_blocked + (r.built_in ? '' : ' Move them to another role first.')) : null, h('span', { class: 'sp' }),
        h('span', { class: 'muted small' }, bad.length ? bad[0] : dirty() ? (n ? 'Applies to ' + plural(n, 'person', 'people') + ' straight away.' : 'Nobody has this role yet.') : ''), go);
    }
  }
  const payload = x => ({ name: x.name.trim(), flows: [...x.flows], tables: [...x.tables], is_approver: x.approver, approval_max_amount: x.approver && x.max.trim() !== '' ? Number(x.max) : null });
  async function create() {
    const x = st.draft;
    try { const r = await api.post('/roles', { ...payload(x), copy_from: x.copy || null }); toast('Role made: ' + x.name.trim(), 'ok'); S.leaveGuard = null; await reload(r.id); }
    catch (e) { toast(e.message, 'bad'); }
  }
  async function save() {
    const x = st.draft, r = roleOf(x.id), p = payload(x), body = {};
    if (!r.built_in && p.name !== r.name) body.name = p.name;
    if (JSON.stringify(sorted(p.flows)) !== JSON.stringify(sorted(r.can))) body.flows = p.flows;
    if (JSON.stringify(sorted(p.tables)) !== JSON.stringify(sorted(r.tables))) body.tables = p.tables;
    if (p.is_approver !== !!r.is_approver || p.approval_max_amount !== r.approval_max_amount) { body.is_approver = p.is_approver; body.approval_max_amount = p.approval_max_amount; }
    if (!Object.keys(body).length) { toast('Nothing changed.'); return; }
    try { await api.patch('/roles/' + x.id, body); toast('Saved', 'ok'); S.leaveGuard = null; await reload(x.id); }
    catch (e) { toast(e.message, 'bad'); }
  }
  async function remove() {
    const r = roleOf(st.draft.id);
    if (!await confirmBox('Delete the role “' + r.name + '”? Nobody has it right now. It cannot be undone.', { ok: 'Delete', danger: true })) return;
    try { await api.del('/roles/' + r.id); toast('Role deleted', 'ok'); S.leaveGuard = null; await reload(); }
    catch (e) { toast(e.message, 'bad'); }
  }

  setTopAction({ label: 'New role', run: () => pick('new') });
  const wanted = route && route.q && route.q.role && roleOf(route.q.role) ? route.q.role : null;
  start(wanted || (d.roles[0] && d.roles[0].id) || 'new');
}
"""
