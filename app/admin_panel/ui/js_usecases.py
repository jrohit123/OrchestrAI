JS = r"""
// ───────────────────────── Build → Use cases ─────────────────────────
// What the organisation does with the chat bot (Tickets, Bookings, Visitors ...), and the kinds of people each kind of
// record can have. All of it is data (GET /usecases): no use case, kind of record or kind of person is named here.
const MEANING_WORDS = { raiser: 'Raised it (the person who asked)', handler: 'Handles it', backup: 'Backup (steps in when the handler does not)', informed: 'Kept informed', other: 'Something else' };

async function renderUsecases(root) {
  const mine = S.renderId;
  let d;
  try { d = await api.get('/usecases'); } catch (e) { fill(root, errorBox(e)); return; }
  if (mine !== S.renderId) return;
  if (!d.available) { fill(root, h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('Not set up yet', 'This organisation’s database needs one small update first (core-0027).')))); return; }
  setTopAction({ label: 'Add a use case', run: () => newUsecaseModal(d) });
  const again = () => { S.lookups = null; renderUsecases(root); };
  const records = [...new Set([...d.usecases.map(u => u.record_type), ...Object.keys(d.kinds)])];
  const ucCard = u => {
    const save = async (patch, ok) => { try { await api.patch('/usecases/' + u.id, patch); Object.assign(u, patch); if (ok) toast(ok, 'ok'); S.lookups = null; } catch (e) { toast(e.message, 'bad'); } };
    const name = h('input', { type: 'text', value: u.name, maxlength: 40, 'aria-label': 'Name' }), icon = h('input', { type: 'text', value: u.icon, maxlength: 8, style: { width: '64px' }, 'aria-label': 'Icon' });
    const desc = h('input', { type: 'text', value: u.description, maxlength: 200, placeholder: 'One line about it', 'aria-label': 'About it' });
    name.addEventListener('change', () => name.value.trim() && save({ name: name.value.trim() }, 'Renamed'));
    icon.addEventListener('change', () => save({ icon: icon.value.trim() }));
    desc.addEventListener('change', () => save({ description: desc.value.trim() }));
    return h('div', { class: 'card' + (u.is_active ? '' : ' off') },
      h('div', { class: 'card-h' }, h('span', { style: { fontSize: '20px' } }, u.icon || '•'), h('b', null, u.name), badge('keeps ' + u.record_type.replace(/_/g, ' ') + 's'),
        h('span', { class: 'sp' }), h('label', { class: 'row small' }, u.is_active ? 'On' : 'Off', switchEl(u.is_active, v => save({ is_active: v }, v ? 'Switched on' : 'Switched off: its flows stay, it leaves the menu'), false, u.name))),
      h('div', { class: 'card-b stack' }, h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, icon, name), desc,
        h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: u.keeps_photos, onchange: e => save({ keeps_photos: e.target.checked }, 'Saved') }), 'Its ' + u.record_type.replace(/_/g, ' ') + 's keep the photos people send'),
        h('div', { class: 'muted small' }, u.flows + ' flow' + (u.flows === 1 ? '' : 's') + ' and ' + u.blocks + ' building block' + (u.blocks === 1 ? '' : 's') + ' are filed under it. A flow is filed in its editor, under “About it”.')));
  };
  fill(root,
    h('div', { class: 'grid', style: { gridTemplateColumns: 'repeat(auto-fill,minmax(320px,1fr))', gap: '14px' } }, d.usecases.length ? d.usecases.map(ucCard) : h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('No use cases yet', 'Add one, like Tickets or Visitors.')))),
    h('h3', { style: { margin: '24px 0 4px' } }, 'People on a record'),
    h('div', { class: 'muted small', style: { marginBottom: '10px' } }, 'The kinds of people each kind of record can have. Flows can tell them, and can let them act on their own records. A kind is never deleted, only switched off, because records keep it.'),
    h('div', { class: 'stack' }, records.map(r => kindsEditor(r, d.kinds[r] || [], d.meanings || Object.keys(MEANING_WORDS), again))));
}

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

SECTIONS.usecases = {
  title: 'Use cases', sub: 'What the chat bot is used for, like Tickets, Bookings and Visitors, and the people each kind of record can have.',
  async render(root) { return renderUsecases(root); },
};
"""
