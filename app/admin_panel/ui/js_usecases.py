JS = r"""
// ───────────────────────── Build → Use cases ─────────────────────────
// What the organisation does with the chat bot (Tickets, Bookings, Visitors ...), and the kinds of people each kind of
// record can have. All of it is data (GET /usecases): no use case, kind of record or kind of person is named here.
const MEANING_WORDS = { raiser: 'Raised it (the person who asked)', handler: 'Handles it', backup: 'Backup (steps in when the handler does not)', informed: 'Kept informed', other: 'Something else' };

function kindsEditor(record, kinds, meanings, again) {
  const list = kinds.map(k => ({ ...k })), box = h('div', { class: 'card-b stack s8' }), msg = h('span', { class: 'small muted' });
  const word = record.replace(/_/g, ' ');
  const draw = () => fill(box,
    list.map((k, i) => {
      const fixed = k.key && k.added === false;   // set by the system itself (who raised it, who handles it)
      const label = h('input', { type: 'text', value: k.label, maxlength: 40, 'aria-label': 'Name', oninput: e => k.label = e.target.value });
      const desc = h('input', { type: 'text', value: k.description || '', maxlength: 200, placeholder: 'What it means', 'aria-label': 'What it means', oninput: e => k.description = e.target.value });
      const mean = sel(meanings.map(m => [m, MEANING_WORDS[m] || m]), k.meaning || 'other', { 'aria-label': 'What the chat bot takes it to mean', disabled: fixed });
      mean.addEventListener('change', () => k.meaning = mean.value);
      return h('div', { class: 'row', style: { flexWrap: 'nowrap', alignItems: 'center', opacity: k.is_active === false ? .55 : 1 } },
        h('div', { class: 'stack s4', style: { flex: '0 0 auto' } },
          h('button', { class: 'btn sm ghost', type: 'button', disabled: i === 0, 'aria-label': 'Move up', onclick: () => { [list[i - 1], list[i]] = [list[i], list[i - 1]]; draw(); } }, '↑'),
          h('button', { class: 'btn sm ghost', type: 'button', disabled: i === list.length - 1, 'aria-label': 'Move down', onclick: () => { [list[i + 1], list[i]] = [list[i], list[i + 1]]; draw(); } }, '↓')),
        h('div', { class: 'stack s4', style: { flex: 1 } }, label, desc),
        h('div', { class: 'stack s4', style: { flex: '0 0 230px' } }, mean, fixed ? h('span', { class: 'muted small' }, 'Set by the system') : (k.in_use ? h('span', { class: 'muted small' }, 'On ' + k.in_use + ' ' + word + (k.in_use === 1 ? '' : 's')) : null)),
        fixed ? h('span', { style: { width: '34px' } }) : switchEl(k.is_active !== false, v => { k.is_active = v; draw(); }, false, k.label));
    }),
    h('div', { class: 'row' },
      h('button', { class: 'btn sm', type: 'button', onclick: () => { list.push({ label: '', description: '', meaning: 'informed', added: true, is_active: true }); draw(); box.querySelectorAll('input[aria-label="Name"]')[list.length - 1].focus(); } }, '＋ Add a kind of person'),
      h('span', { class: 'sp' }), msg,
      h('button', { class: 'btn sm primary', type: 'button', onclick: async () => {
        if (list.some(k => !k.label.trim())) { toast('Every kind needs a name', 'bad'); return; }
        try { await api.put('/record-kinds/' + record, { kinds: list.map(k => ({ key: k.key || null, label: k.label.trim(), description: (k.description || '').trim(), meaning: k.meaning || 'other', added: k.added !== false, is_active: k.is_active !== false })) }); toast('Saved', 'ok'); again(); }
        catch (e) { toast(e.message, 'bad'); }
      } }, 'Save')));
  draw();
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'People on a ' + word, badge(list.filter(k => k.is_active !== false).length + ' in use')), box);
}

function newUsecaseModal(d) {
  const records = [...new Set([...d.usecases.map(u => u.record_type), ...Object.keys(d.kinds)])];
  const name = h('input', { type: 'text', placeholder: 'e.g. Visitors', maxlength: 40 }), icon = h('input', { type: 'text', placeholder: 'e.g. 🚪', maxlength: 8 });
  const desc = h('input', { type: 'text', placeholder: 'One line about it', maxlength: 200 });
  const keep = sel([['', 'Something new'], ...records.map(r => [r, 'The same as ' + r.replace(/_/g, ' ') + 's'])], '', { 'aria-label': 'What it keeps' });
  const newRec = h('input', { type: 'text', placeholder: 'One of them is called a… e.g. visitor', maxlength: 40 });
  const photos = h('input', { type: 'checkbox' });
  modal({ title: 'Add a use case', body: h('div', { class: 'stack' }, field('Name', name), field('Icon', icon, 'Shown in the chat menu and on the dashboard.'), field('About it', desc),
    field('What does it keep?', keep, 'Each use case keeps one kind of record: tickets, bookings, visitors…'), field('A new kind of record', newRec, 'Only when it keeps something new. Its fields are designed separately.'),
    h('label', { class: 'row small' }, photos, 'It keeps the photos people send')),
    actions: [{ label: 'Cancel' }, { label: 'Add use case', primary: true, run: async () => {
      const rec = keep.value || newRec.value.trim();
      if (!name.value.trim() || !rec) { toast('Give it a name and say what it keeps', 'bad'); return false; }
      try { await api.post('/usecases', { name: name.value.trim(), icon: icon.value.trim(), description: desc.value.trim(), record_type: rec, keeps_photos: photos.checked }); toast('Added', 'ok'); S.lookups = null; lastSig = ''; onRoute(); }
      catch (e) { toast(e.message, 'bad'); return false; }
    } }] });
}

// ───────────────────────── Flows and Building blocks, one box per use case ─────────────────────────
// A flow or block lives in the box it was made in; click it (or Edit) to open it on the canvas. The box's switch decides whether
// the use case is in the chat menu. The use case's own settings (name, icon, photos, people on a record) are behind ⚙ Settings
// of its box, so there is no separate Use cases screen. The menu preview calls the same code the chat bot calls.
const UCB = { open: {}, role: '' };   // use case id -> settings open; the role the preview is for

function ucSettings(u, d, again) {
  const save = async (patch, ok) => { try { await api.patch('/usecases/' + u.id, patch); Object.assign(u, patch); if (ok) toast(ok, 'ok'); S.lookups = null; } catch (e) { toast(e.message, 'bad'); } };
  const name = h('input', { type: 'text', value: u.name, maxlength: 40, 'aria-label': 'Name' }), icon = h('input', { type: 'text', value: u.icon, maxlength: 8, style: { width: '64px' }, 'aria-label': 'Icon' });
  const desc = h('input', { type: 'text', value: u.description, maxlength: 200, placeholder: 'One line about it', 'aria-label': 'About it' });
  name.addEventListener('change', () => name.value.trim() && save({ name: name.value.trim() }, 'Renamed').then(again));
  icon.addEventListener('change', () => save({ icon: icon.value.trim() }).then(again));
  desc.addEventListener('change', () => save({ description: desc.value.trim() }, 'Saved'));
  const word = u.record_type.replace(/_/g, ' ');
  return h('div', { class: 'ucb-set stack' },
    h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, icon, name), desc,
    h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: u.keeps_photos, onchange: e => save({ keeps_photos: e.target.checked }, 'Saved') }), 'Its ' + word + 's keep the photos people send'),
    kindsEditor(u.record_type, d.kinds[u.record_type] || [], d.meanings || Object.keys(MEANING_WORDS), again));
}

async function menuPreview() {
  const box = h('aside', { class: 'ucb-phone' });
  const draw = async () => {
    let m;
    try { m = await api.get('/menu-preview' + (UCB.role ? '?role_id=' + UCB.role : '')); } catch (e) { fill(box, h('div', { class: 'muted small' }, 'The preview is not available: ' + e.message)); return; }
    UCB.role = m.role_id || '';
    const pick = sel(m.roles.map(r => [String(r.id), r.name]), UCB.role, { 'aria-label': 'See the menu as' });
    pick.addEventListener('change', () => { UCB.role = pick.value; draw(); });
    fill(box, h('b', { class: 'small' }, 'What people see on WhatsApp'),
      h('div', { class: 'muted small' }, 'Made by the chat bot’s own code from the switches here. Turn a use case or a flow off and it leaves.'),
      field('See it as', pick),
      h('div', { class: 'ucb-dev' }, h('div', { class: 'ucb-bar' }, 'Chat'), h('div', { class: 'ucb-chat' },
        h('div', { class: 'ucb-b' }, 'What would you like to do?'), h('div', { class: 'ucb-menu' }, '☰ Menu'),
        m.groups.length ? m.groups.map(g => h('div', { class: 'ucb-sec' }, h('b', null, g.title), g.flows.map(n => h('div', null, n)))) : h('div', { class: 'ucb-sec' }, 'Nothing here for this role.'))));
  };
  await draw();
  return box;
}

async function renderBoxes(root, kind) {   // kind: 'flows' or 'blocks'
  const mine = S.renderId;
  let d;
  try { [d] = await Promise.all([api.get('/usecases'), ensureStudio()]); } catch (e) { fill(root, errorBox(e)); return; }
  if (mine !== S.renderId) return;
  const again = async () => { S.lookups = null; await ensureStudio(); if (mine === S.renderId) renderBoxes(root, kind); };
  setTopAction({ label: 'New use case', run: () => newUsecaseModal(d) });
  const inBox = id => ST.flows.filter(w => String(w.usecase_id || '') === String(id || ''));
  const moveSel = w => {
    const s = sel([['', 'Move to…'], ...d.usecases.filter(u => String(u.id) !== String(w.usecase_id || '')).map(u => [u.id, (u.icon ? u.icon + ' ' : '') + u.name])], '', { 'aria-label': 'Move ' + w.name + ' to another use case' });
    s.addEventListener('change', async () => { if (!s.value) return; try { await api.put('/workflows/' + w.id + '/usecase', { usecase_id: s.value }); toast('Moved', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } });
    return s;
  };
  const row = w => h('div', { class: 'ucb-row' + (w.is_active ? '' : ' off') },
    h('a', { href: '#/workflows?w=' + w.id, class: 'grow' }, w.name),
    w.kind === 'case_action' ? badge('button on a ticket') : null,
    moveSel(w),
    h('a', { class: 'btn sm', href: '#/workflows?w=' + w.id }, 'Edit'),
    switchEl(w.is_active, async v => { try { await api.post('/workflows/' + w.id + '/active', { is_active: v }); w.is_active = v; toast(switchNote(w, v), 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } }, false, w.name));
  const box = u => {
    const list = inBox(u ? u.id : null), flows = list.filter(w => w.kind !== 'block'), blocks = list.filter(w => w.kind === 'block');
    const items = kind === 'flows' ? flows : blocks;
    if (!u && !items.length) return null;
    const make = k => () => { FV.intoUsecase = u ? u.id : null; newWorkflowModal(!!S.boot.caps.workflow_kind, k); };
    const count = kind === 'flows' ? flows.length + ' flow' + (flows.length === 1 ? '' : 's') + ' · ' + blocks.length + ' block' + (blocks.length === 1 ? '' : 's') : blocks.length + ' building block' + (blocks.length === 1 ? '' : 's');
    const open = u && UCB.open[u.id];
    const head = u
      ? h('div', { class: 'ucb-h' }, h('span', { class: 'ucb-ic' }, u.icon || '•'), h('b', null, u.name), h('span', { class: 'muted small' }, count),
          h('span', { class: 'sp' }),
          h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { UCB.open[u.id] = !open; renderBoxes(root, kind); } }, open ? 'Hide settings' : '⚙ Settings'),
          h('span', { class: 'muted small' }, u.is_active ? 'In the menu' : 'Off: not in the menu'),
          switchEl(u.is_active, async v => { try { await api.patch('/usecases/' + u.id, { is_active: v }); u.is_active = v; toast(v ? u.name + ' is in the menu again' : u.name + ' left the menu; its flows are kept', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } }, false, u.name))
      : h('div', { class: 'ucb-h' }, h('b', null, 'Not in a use case yet'), h('span', { class: 'muted small' }, 'Shown in the menu after the use cases. Move each one into its use case.'));
    return h('div', { class: 'card ucb' + (u && !u.is_active ? ' off' : '') }, head,
      open ? ucSettings(u, d, again) : null,
      items.length ? items.map(row) : h('div', { class: 'ucb-row muted small' }, kind === 'flows' ? 'No flows yet.' : 'No building blocks yet.'),
      kind === 'flows' && blocks.length ? h('details', { class: 'ucb-blocks' }, h('summary', null, 'Building blocks (' + blocks.length + ')'), blocks.map(row)) : null,
      u ? h('div', { class: 'ucb-row' }, kind === 'flows' ? [h('button', { class: 'btn sm', type: 'button', onclick: make('workflow') }, '＋ New flow in ' + u.name), h('button', { class: 'btn sm ghost', type: 'button', onclick: make('block') }, '＋ New building block')]
        : h('button', { class: 'btn sm', type: 'button', onclick: make('block') }, '＋ New building block in ' + u.name)) : null);
  };
  const boxes = h('div', { class: 'ucb-main' }, d.usecases.map(box), box(null));
  fill(root, kind === 'flows' ? h('div', { class: 'ucb-layout' }, boxes, await menuPreview()) : boxes);
}
const renderFlowBoxes = root => renderBoxes(root, 'flows');
const renderBlockBoxes = root => renderBoxes(root, 'blocks');
"""
