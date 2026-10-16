JS = r"""
// ───────────────────────── Build → Data & schema (super admins) ─────────────────────────
// What each use case keeps, and how it changes. Three tabs: the kinds of record, "Describe a change" (the AI drafts it, you
// check and change it), and the history. Every change is checked, tried in a transaction that is rolled back, and only then
// applied. It only ever adds: a field that is no longer wanted is switched off, never dropped.
const SCH = { sel: '', chat: [], draft: null };

function schemaSteps(plan, tried) {
  const st = (ok, t, d) => h('div', { class: 'sch-step ' + (ok === true ? 'ok' : ok === false ? 'bad' : '') }, h('span', { class: 'sch-dot' }, ok === true ? '✓' : ok === false ? '!' : '·'), h('div', null, h('b', { class: 'small' }, t), h('div', { class: 'muted small' }, d)));
  return h('div', { class: 'stack s8' },
    st(plan.issues.length ? false : true, 'Checked against this database', plan.issues.length ? 'Not allowed yet, see below' : 'Names are free and every kind is one the database accepts'),
    st(plan.issues.length ? null : (tried ? true : false), 'Tried, then undone', tried ? 'Every statement ran in a transaction that was rolled back. Nothing was kept' : 'Could not be tried'),
    st(null, 'Apply', 'One transaction, written in the history'));
}

// shows the plan of a list of changes and applies it; plan() is called again whenever the changes change
function changeBox(getOps, onApplied) {
  const box = h('div', { class: 'card' }), body = h('div', { class: 'card-b stack' });
  let last = null, token = 0;
  async function refresh() {
    const ops = getOps(); const my = ++token;
    if (!ops || !ops.length) { fill(body, h('div', { class: 'muted small' }, 'Nothing to change yet.')); last = null; return; }
    fill(body, h('div', { class: 'muted small' }, 'Checking…'));
    let p;
    try { p = await api.post('/schema/plan', { ops }); } catch (e) { if (my === token) fill(body, notice(e.message, 'bad')); last = null; return; }
    if (my !== token) return;
    last = p;
    const apply = h('button', { class: 'btn primary', type: 'button', disabled: !p.ok, onclick: doApply }, 'Apply to the database');
    fill(body, schemaSteps(p, p.tried),
      p.issues.length ? h('div', { class: 'stack s4' }, p.issues.map(i => notice(i, 'bad'))) : null,
      p.summary.length ? h('div', { class: 'stack s4' }, h('b', { class: 'small' }, 'What it does'), h('ul', { class: 'sch-ul' }, p.summary.map(x => h('li', null, x)))) : null,
      p.warnings.map(x => notice(x, 'info')),
      p.sql ? h('details', null, h('summary', { class: 'muted small' }, 'The database change (SQL, read only)'), h('pre', { class: 'code' }, p.sql), h('div', { class: 'muted small', style: { marginTop: '8px' } }, 'The way back, kept in the history (never run by itself):'), h('pre', { class: 'code' }, p.way_back || '—')) : null,
      h('div', { class: 'row' }, apply));
  }
  async function doApply() {
    modal({ title: 'Apply this change?', body: h('div', { class: 'stack' }, h('p', null, 'It was tried and undone first, and it only adds. Before a change on a live organisation, make sure a backup is taken.'), h('ul', { class: 'sch-ul' }, (last ? last.summary : []).map(x => h('li', null, x)))),
      actions: [{ label: 'Cancel' }, { label: 'Apply', primary: true, run: async () => {
        await api.post('/schema/apply', { ops: getOps() });
        toast('Applied and written in the history', 'ok'); S.lookups = null; await refreshBoot(); onApplied && onApplied();
      } }] });
  }
  fill(box, h('div', { class: 'card-h' }, 'Check and apply'), body);
  box.refresh = refresh;
  refresh();
  return box;
}
async function refreshBoot() { try { S.boot = await api.get('/bootstrap'); } catch (e) { /* the page still works */ } }

// the form for a new kind of record; `op` is changed in place and onChange is called after every edit
function typeForm(op, roles, onChange) {
  const box = h('div', { class: 'stack' });
  const ch = () => { onChange(); };
  const text = (k, label, hint, ph) => { const i = h('input', { type: 'text', value: op[k] || '', placeholder: ph || '', maxlength: 60 }); i.addEventListener('input', () => { op[k] = i.value; ch(); }); return field(label, i, hint); };
  const list = (k, label, hint, ph) => { const i = h('input', { type: 'text', value: (op[k] || []).map(x => x.label || x).join(', '), placeholder: ph }); i.addEventListener('input', () => { const v = i.value.split(',').map(x => x.trim()).filter(Boolean); op[k] = k === 'statuses' ? v.map((x, n) => ({ label: x, closed: n === v.length - 1 && v.length > 1 })) : v; ch(); }); return field(label, i, hint); };
  const draw = () => {
    fill(box,
      h('div', { class: 'grid2' }, text('label', 'One of them is called', 'For example Visitor', 'Visitor'), text('plural', 'Many of them are called', 'For example Visitors; this becomes the use case and the table name', 'Visitors')),
      h('div', { class: 'grid2' }, text('icon', 'Icon', '', '🚪'), text('about', 'One line about it', '', 'Guests approved by residents')),
      list('statuses', 'Statuses, in order', 'Separate with commas. The last one means finished.', 'Expected, Arrived, Left'),
      list('people', 'People on it', 'Besides “Created it”. Separate with commas.', 'Host resident, Guard on duty'),
      h('div', { class: 'stack s8' }, h('b', { class: 'small' }, 'Fields: what is asked and kept'),
        (op.fields || []).map((f, i) => {
          const lab = h('input', { type: 'text', value: f.label, placeholder: 'e.g. Vehicle number', 'aria-label': 'Field name' });
          lab.addEventListener('input', () => { f.label = lab.value; ch(); });
          const kind = sel(Object.entries(S.schema.kinds), f.kind || 'text', { 'aria-label': 'Kind' });
          kind.addEventListener('change', () => { f.kind = kind.value; if (f.kind !== 'choice') f.options = []; draw(); ch(); });
          const opts = f.kind === 'choice' ? (() => { const o = h('input', { type: 'text', value: (Array.isArray(f.options) ? f.options : []).join(', '), placeholder: 'Choices, separated by commas', 'aria-label': 'Choices' }); o.addEventListener('input', () => { f.options = o.value.split(',').map(x => x.trim()).filter(Boolean); ch(); }); return o; })() : null;
          return h('div', { class: 'row', style: { flexWrap: 'nowrap', alignItems: 'center' } }, h('div', { style: { flex: 1 } }, lab), kind, opts ? h('div', { style: { flex: 1 } }, opts) : null,
            h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: !!f.required, onchange: e => { f.required = e.target.checked; ch(); } }), 'Required'),
            h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Remove', onclick: () => { op.fields.splice(i, 1); draw(); ch(); } }, '×'));
        }),
        h('div', null, h('button', { class: 'btn sm', type: 'button', onclick: () => { op.fields.push({ label: '', kind: 'text', required: false, options: [] }); draw(); ch(); } }, '＋ Add a field'))),
      roles.length ? h('div', { class: 'stack s4' }, h('b', { class: 'small' }, 'Who may ask the chat bot about them'), h('div', { class: 'row' }, roles.map(r => h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: (op.read_by_roles || []).includes(r), onchange: e => { const s = new Set(op.read_by_roles || []); e.target.checked ? s.add(r) : s.delete(r); op.read_by_roles = [...s]; ch(); } }), r)))) : null);
  };
  draw();
  return box;
}
const blankType = () => ({ op: 'create_record_type', label: '', plural: '', prefix: '', icon: '', about: '', statuses: [], fields: [{ label: '', kind: 'text', required: false, options: [] }], people: [], read_by_roles: [] });
const cleanOp = op => ({ ...op, fields: (op.fields || []).filter(f => (f.label || '').trim()), statuses: (op.statuses || []).filter(s => (s.label || '').trim()) });
const readyType = op => (op.label || '').trim() && (op.plural || '').trim();

function newTypeScreen(root, d, op, intro) {
  const plan = changeBox(() => readyType(op) ? [cleanOp(op)] : [], () => { SCH.draft = null; SCH.sel = ''; go('schema'); });
  let t = null;
  const again = () => { clearTimeout(t); t = setTimeout(() => plan.refresh(), 450); };
  fill(root, h('div', { class: 'stack' },
    intro ? notice(intro, 'info') : null,
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'A new kind of record'), h('div', { class: 'card-b' }, typeForm(op, d.roles, again))),
    plan,
    h('div', null, h('button', { class: 'btn', type: 'button', onclick: () => { SCH.draft = null; go('schema'); } }, 'Cancel'))));
}

function addFieldModal(t, done) {
  const label = h('input', { type: 'text', placeholder: 'e.g. Vehicle number' }), kind = sel(Object.entries(S.schema.kinds), 'text');
  const opts = h('input', { type: 'text', placeholder: 'Choices, separated by commas' }), req = h('input', { type: 'checkbox' });
  const slot = h('div'), planSlot = h('div');
  const op = () => ({ op: 'add_field', record_type: t.key, field: { label: label.value.trim(), kind: kind.value, required: req.checked, options: opts.value.split(',').map(x => x.trim()).filter(Boolean) } });
  const view = () => fill(slot, field('Name', label), field('Kind', kind), kind.value === 'choice' ? field('Choices', opts) : null, h('label', { class: 'row small' }, req, 'People must fill it in'),
    t.is_system ? notice('Kept inside each ' + t.label.toLowerCase() + ', so the table itself does not change.', 'info') : null);
  const plan = changeBox(() => label.value.trim() ? [op()] : [], () => { close.close && close.close(); done(); });
  kind.addEventListener('change', () => { view(); plan.refresh(); });
  [label, opts, req].forEach(x => x.addEventListener('input', () => plan.refresh()));
  view();
  const close = modal({ title: 'Add a field to ' + t.plural.toLowerCase(), wide: true, body: h('div', { class: 'stack' }, slot, plan), actions: [{ label: 'Close' }] });
}
function addStatusModal(t, done) {
  const label = h('input', { type: 'text', placeholder: 'e.g. On hold' }), closed = h('input', { type: 'checkbox' });
  const plan = changeBox(() => label.value.trim() ? [{ op: 'add_status', record_type: t.key, status: { label: label.value.trim(), closed: closed.checked } }] : [], () => { close.close && close.close(); done(); });
  [label, closed].forEach(x => x.addEventListener('input', () => plan.refresh()));
  const close = modal({ title: 'Add a status to ' + t.plural.toLowerCase(), wide: true, body: h('div', { class: 'stack' }, field('Name', label), h('label', { class: 'row small' }, closed, 'It means finished'), plan), actions: [{ label: 'Close' }] });
}

async function typePage(root, d, t, again) {
  const word = t.label.toLowerCase();
  const rec = h('div');
  const showRecords = async () => {
    try { const r = await api.get('/records/' + t.key); fill(rec, r.rows.length ? h('div', { class: 'tablewrap' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, 'Status'), r.columns.map(c => h('th', null, c.label)), h('th', null, 'Added'))),
      h('tbody', null, r.rows.map(x => h('tr', null, h('td', null, pretty(x.status)), r.columns.map(c => h('td', null, x[c.key] == null ? '—' : String(x[c.key]))), h('td', null, ago(x.created_at))))))) : h('div', { class: 'muted small' }, 'No ' + t.plural.toLowerCase() + ' yet.')); }
    catch (e) { fill(rec, notice(e.message, 'bad')); }
  };
  const flip = async (f, on) => {
    const plan = await api.post('/schema/plan', { ops: [{ op: 'set_field_active', record_type: t.key, key: f.key, active: on }] });
    if (!plan.ok) { toast(plan.issues[0], 'bad'); return; }
    await api.post('/schema/apply', { ops: [{ op: 'set_field_active', record_type: t.key, key: f.key, active: on }] });
    toast(on ? f.label + ' is on' : f.label + ' is off; its data stays', 'ok'); again();
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'card' },
      h('div', { class: 'card-h' }, t.plural, t.usecases.map(u => badge(u)), t.is_system ? badge('run by the system') : null, h('span', { class: 'sp' }), t.count != null ? h('span', { class: 'muted small' }, t.count + ' ' + (t.count === 1 ? word : t.plural.toLowerCase())) : null,
        h('button', { class: 'btn sm primary', type: 'button', onclick: () => addFieldModal(t, again) }, '＋ Add a field')),
      h('div', { class: 'card-b' }, t.fields.length ? h('div', { class: 'stack s8' }, t.fields.map(f => h('div', { class: 'row', style: { flexWrap: 'nowrap', alignItems: 'center', opacity: f.is_active ? 1 : .55 } },
        h('div', { style: { flex: 1 } }, h('b', null, f.label), f.is_system ? h('span', { class: 'muted small' }, ' · made by the system') : null, Array.isArray(f.options) && f.options.length ? h('div', { class: 'muted small' }, f.options.join(' · ')) : null),
        h('span', { class: 'small' }, d.kinds[f.kind] || f.kind), h('span', { class: 'small muted', style: { width: '70px' } }, f.required ? 'Required' : ''), h('span', { class: 'small muted', style: { width: '90px' } }, f.storage === 'custom' ? 'inside the record' : 'own column'),
        f.is_system ? h('span', { style: { width: '34px' } }) : switchEl(f.is_active, v => flip(f, v), false, f.label))))
        : h('div', { class: 'muted' }, 'No fields yet.'))),
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Statuses', h('span', { class: 'sp' }), t.is_system ? null : h('button', { class: 'btn sm', type: 'button', onclick: () => addStatusModal(t, again) }, '＋ Add a status')),
      h('div', { class: 'card-b' }, t.is_system ? h('div', { class: 'muted small' }, 'The statuses of ' + t.plural.toLowerCase() + ' are set by their own rules, under Tickets.') : h('div', { class: 'row' }, t.statuses.map((s, i) => [i ? '→' : null, badge(s.label, s.closed ? 'ok' : '')])))),
    t.table_name && !t.is_system ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Latest ' + t.plural.toLowerCase(), h('span', { class: 'sp' }), h('button', { class: 'btn sm', type: 'button', onclick: showRecords }, 'Show')), h('div', { class: 'card-b' }, rec)) : null,
    h('div', { class: 'muted small' }, 'Flows use these fields in their steps. Make the flows in the use case’s box under Flows.'));
}

async function renderSchema(root, route) {
  const mine = S.renderId;
  let d;
  try { d = await api.get('/schema'); } catch (e) { fill(root, errorBox(e)); return; }
  if (mine !== S.renderId) return;
  S.schema = d;
  if (!d.available) { fill(root, h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('Not set up yet', 'This organisation’s database needs one small update first (core-0028).')))); return; }
  const tab = route.tab || '';
  const again = () => renderSchema(root, route);
  if (tab === 'history') {
    setTopAction(null);
    fill(root, d.history.length ? h('div', { class: 'card' }, d.history.map(c => h('div', { class: 'sch-hist' }, h('div', { class: 'row' }, badge(c.status === 'applied' ? 'Applied' : 'Failed', c.status === 'applied' ? 'ok' : 'bad'), h('b', { class: 'small' }, c.by_label || '—'), h('span', { class: 'muted small' }, ago(c.created_at))), h('div', { class: 'small' }, c.summary), c.error ? notice(c.error, 'bad') : null,
      c.sql_up ? h('details', null, h('summary', { class: 'muted small' }, 'The database change and the way back'), h('pre', { class: 'code' }, c.sql_up), h('pre', { class: 'code' }, c.sql_down || '—')) : null)))
      : h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('No changes yet', 'Every change made here is written down, with the way back.'))));
    return;
  }
  if (tab === 'ai') {
    setTopAction(null);
    const log = h('div', { class: 'sch-log' }), input = h('input', { type: 'text', placeholder: 'e.g. Residents should register their vehicles for parking' });
    const say = (who, t, chips) => { const m = h('div', { class: 'sch-msg ' + who }, t); if (chips) m.append(h('div', { class: 'row', style: { marginTop: '6px' } }, chips)); log.append(m); log.scrollTop = 1e6; };
    SCH.chat.forEach(m => say(m.role === 'user' ? 'me' : 'ai', m.content));
    if (!SCH.chat.length) say('ai', 'Tell me what should be kept, in plain words. I read what you have, reuse what fits and draft only what is new. You check and change everything, and nothing is applied until you press Apply.');
    const planHost = h('div');
    const send = async text => {
      text = (text || input.value).trim(); if (!text) return; input.value = '';
      SCH.chat.push({ role: 'user', content: text }); say('me', text);
      const wait = h('div', { class: 'sch-msg ai muted' }, 'Thinking…'); log.append(wait);
      let r;
      try { r = await api.post('/schema/ai', { messages: SCH.chat }); } catch (e) { wait.remove(); say('ai', e.message); return; }
      wait.remove();
      SCH.chat.push({ role: 'assistant', content: r.reply + (r.questions.length ? ' ' + r.questions.join(' ') : '') });
      say('ai', r.reply);
      r.questions.forEach(q => say('ai', q));
      if (r.ops) {
        const create = r.ops.find(o => o.op === 'create_record_type');
        if (create) { SCH.draft = { op: create, intro: r.reply }; newTypeScreen(planHost, d, SCH.draft.op, r.reply); }
        else {
          let ops = r.ops;
          fill(planHost, h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'The draft'), h('div', { class: 'card-b stack' }, notice(r.reply, 'info'), changeBox(() => ops, () => { SCH.chat = []; go('schema'); }))));
        }
      }
    };
    input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
    fill(root, h('div', { class: 'sch-ai' }, h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Describe it'), log,
      h('div', { class: 'row', style: { padding: '0 14px 8px' } }, ['Visitors, with who they visit', 'Residents register vehicles for parking', 'A notice board'].map(x => h('button', { class: 'btn sm', type: 'button', onclick: () => send(x) }, x))),
      h('div', { class: 'row', style: { padding: '0 14px 14px', flexWrap: 'nowrap' } }, input, h('button', { class: 'btn primary', type: 'button', onclick: () => send() }, 'Send'))), planHost));
    if (SCH.draft) newTypeScreen(planHost, d, SCH.draft.op, SCH.draft.intro);
    return;
  }
  if (tab === 'new') {
    setTopAction(null);
    newTypeScreen(root, d, SCH.draft ? SCH.draft.op : blankType());
    return;
  }
  setTopAction({ label: 'New kind of record', run: () => { SCH.draft = null; go('schema', 'new'); } });
  const cur = d.types.find(t => t.key === SCH.sel) || d.types[0];
  if (!cur) { fill(root, h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('No kinds of record yet', 'Add one, like Visitors or Parking.')))); return; }
  const page = h('div');
  fill(root, h('div', { class: 'sch-layout' },
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Kinds of record'), h('div', { class: 'card-b stack s4' }, d.types.map(t => h('button', { class: 'sch-type' + (t.key === cur.key ? ' on' : ''), type: 'button', onclick: () => { SCH.sel = t.key; again(); } }, t.plural, h('span', { class: 'muted small' }, t.fields.length + ' fields'))))), page));
  fill(page, await typePage(root, d, cur, again));
}

SECTIONS.schema = {
  title: 'Data & schema', sub: 'What each use case keeps. Changes are checked, tried and undone first, and only ever add: nothing is removed, so no record is lost.',
  async render(root, route) { return renderSchema(root, route || { tab: '' }); },
};
"""
