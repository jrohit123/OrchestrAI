JS = r"""
// ───────────────────────── Routing & categories ─────────────────────────
const FIELD_TYPES = [['text', 'Short text'], ['number', 'Number'], ['choice', 'Pick one'], ['yes_no', 'Yes / no'], ['date', 'Date']];   // suggestions for the form; stored as written
function descendantsOf(lk, id) {
  const out = new Set([id]);
  let grew = true;
  while (grew) { grew = false; lk.categories.forEach(c => { if (c.parent_id && out.has(c.parent_id) && !out.has(c.id)) { out.add(c.id); grew = true; } }); }
  return out;
}
// The people on a rule: Level 1 (the first owns the case, the others are told at once) and Level 2 (supporting)
function teamText(people) {
  const part = level => people.filter(p => p.level === level).map((p, i) => h('span', { style: p.reachable ? null : { color: 'var(--bad)' }, title: p.reachable ? '' : 'Cannot be messaged right now' }, (i ? ', ' : '') + p.name + (level === 1 && i === 0 ? ' (owner)' : '') + (p.reachable ? '' : ' (cannot be messaged)')));
  const one = part(1), two = part(2);
  return h('span', null, h('b', null, 'Level 1: '), one.length ? one : 'nobody', two.length ? [h('span', { class: 'muted' }, ' · '), h('b', null, 'Level 2: '), two] : null);
}
function teamEditor(initial) {
  const lists = { 1: h('div', { class: 'stack' }), 2: h('div', { class: 'stack' }) }, rows = { 1: [], 2: [] };
  function add(level, person) {
    const ctl = personPicker({ placeholder: 'Type a name…', initial: person ? { id: person.user_id, name: person.name } : null });
    const item = { ctl };
    const row = h('div', { class: 'row' }, ctl.el, h('button', { class: 'x', type: 'button', 'aria-label': 'Remove this person', onclick: () => { row.remove(); rows[level] = rows[level].filter(x => x !== item); } }, '×'));
    rows[level].push(item); lists[level].append(row);
  }
  (initial || []).forEach(p => add(p.level, p));
  if (!rows[1].length) add(1);
  const block = (level, title, help) => h('div', { class: 'stack', style: { marginBottom: '10px' } }, h('div', null, h('b', null, title), ' ', h('span', { class: 'muted small' }, help)), lists[level], h('button', { class: 'btn sm', type: 'button', onclick: () => add(level) }, '+ Add a person'));
  return {
    el: h('div', null, block(1, 'Level 1', 'The first one owns the case. The others here are told at once.'), block(2, 'Level 2', 'Supporting people. Also told.')),
    value() { return [1, 2].flatMap(level => rows[level].map(x => x.ctl.value).filter(Boolean).map(id => ({ user_id: id, level }))); },
  };
}
function ruleSentence(r) {
  const who = (name, people, type) => h('span', null, h('b', null, name), ' ', h('span', { class: 'muted small' }, type === 'seat' ? '(seat)' : type === 'role' ? '(role)' : ''),
    people.length ? h('span', { class: 'muted small' }, ' — today: ' + people.join(', ')) : h('span', { style: { color: 'var(--bad)' } }, ' — nobody it points to can be messaged right now'));
  const conds = Object.entries(r.match || {});
  return h('div', { class: 'sentence' },
    'When ', h('b', null, r.category_label || 'any case'), conds.length ? [' and ', conds.map(([k, v]) => h('span', { class: 'chip' }, pretty(k) + ' = ' + v))] : null,
    r.intent_key ? [' via ', h('b', null, r.intent_key)] : null, ' comes in → ',
    (r.people && r.people.length) ? teamText(r.people) : (r.assign_name ? who(r.assign_name, r.assign_people.filter(Boolean), r.assign_type) : h('span', { style: { color: 'var(--bad)' } }, 'nobody is chosen')),
    r.backup_name ? h('div', null, ((r.people && r.people.length) ? 'If none of them can be messaged → ' : 'If they are unavailable → '), who(r.backup_name, r.backup_people.filter(Boolean), r.backup_type)) : null);
}
function routeResultText(res) {
  if (!res) return h('div', null, h('b', null, 'No rule matches.'), ' A case like this stays unassigned until someone assigns it.');
  return h('div', { class: 'stack' },
    h('div', null, 'Rule ', h('b', null, '“' + res.rule_name + '”'), ' → ', res.assignee_name ? h('b', null, res.assignee_name) : h('b', { style: { color: 'var(--bad)' } }, 'nobody available'),
      res.via === 'backup' ? ' (the backup, because the first choice is unavailable)' : '', res.via === 'nobody available' ? ' — the rule matched but no one it points to can be messaged.' : ''),
    res.level2.length ? h('div', null, 'Level 2: ', res.level2.map(x => x.name).join(', ')) : null,
    res.target_minutes ? h('div', { class: 'muted' }, 'Response target: ' + minutes(res.target_minutes)) : null);
}
async function ruleModal(lk, rule, contextKeys, done, preset) {
  const base = rule || preset || {};
  const name = h('input', { type: 'text', value: base.name || '', placeholder: 'e.g. Lift issues' });
  const cat = sel(catOptions(lk, 'Any category'), base.category_id || '');
  const conds = kvEditor(base.match || {}, contextKeys);
  const flow = sel([['', 'Any flow'], ...lk.workflows.filter(w => w.kind !== 'block').map(w => [w.intent_key, w.name])], base.intent_key || '');
  const assign = targetEditor(lk, rule ? { type: rule.assign_type, id: rule.assign_id, name: rule.assign_name } : null, false);
  const backup = targetEditor(lk, rule && rule.backup_type ? { type: rule.backup_type, id: rule.backup_id, name: rule.backup_name } : null, true);
  const team = teamEditor(rule ? rule.people : []);
  const hasTeam = !!(rule && rule.people && rule.people.length);
  const target = h('input', { type: 'number', min: 1, placeholder: 'minutes (optional)', value: rule && rule.target_minutes ? rule.target_minutes : '' });
  const active = h('input', { type: 'checkbox', checked: rule ? rule.is_active : true });
  modal({
    title: rule ? 'Edit rule' : 'New rule', wide: true,
    body: h('div', null, field('Name', name, 'Only for you to recognise it.'),
      h('div', { class: 'two' }, field('When the case is about', cat, 'Sub-categories are included. The most specific rule wins.'), field('Coming from flow', flow)),
      field('Only if (optional)', conds.el, 'Extra conditions on the case’s own answers, for example tower = B. A rule with more conditions wins over a plainer one.'),
      field('Who handles it', team.el, 'Level 1 and Level 2 people are all put on the case and told. The first Level 1 person is its owner.'),
      h('details', { open: !!rule && !hasTeam }, h('summary', { class: 'muted small', style: { cursor: 'pointer' } }, 'Or point it at one person, a seat or a role instead'),
        field('Gets handled by', assign.el), field('If nobody above can be messaged, then', backup.el, 'Also becomes the “level 2” person who is kept in the loop.')),
      field('Response target (optional)', target, 'Overrides the category’s and the priority’s response time for cases this rule picks up.'),
      h('label', { class: 'row' }, active, 'Rule is on')),
    actions: [{ label: 'Cancel' }, { label: 'Save rule', primary: true, run: async () => {
      const a = assign.value() || null, b = backup.value(), people = team.value();
      if (!a && !people.some(p => p.level === 1)) throw new Error('Choose who handles it: at least one Level 1 person.');
      if (b === false) throw new Error('Choose the backup, or set it to “Nobody”.');
      const body = { name: name.value.trim(), category_id: cat.value || null, intent_key: flow.value || null, match: conds.value(), assign: a, backup: b, people, target_minutes: target.value ? Number(target.value) : null, is_active: active.checked };
      if (rule) await api.put('/rules/' + rule.id, body); else await api.post('/rules', body);
      toast('Rule saved', 'ok'); done();
    } }],
  });
}
async function renderRulesTab(root) {
  const [r, cats, lk] = await Promise.all([api.get('/rules'), api.get('/categories'), getLookups(true)]);
  const again = () => { clear(root); renderRulesTab(root); };
  // "who would get it?"
  const tCat = sel(catOptions(lk, null), '', { 'aria-label': 'Kind of complaint' });
  const tPrio = sel([['', 'Any priority'], ...(S.boot.enums.priorities || []).map(p => [p, pretty(p)])], '', { 'aria-label': 'Priority' });
  const tCond = kvEditor({}, r.context_keys);
  const result = h('div', { class: 'quote', hidden: true });
  root.append(h('div', { class: 'card', style: { marginBottom: '14px' } }, h('div', { class: 'card-h' }, 'Try it: who would get a case like this?'),
    h('div', { class: 'card-b stack' }, h('div', { class: 'row' }, tCat, tPrio, h('button', { class: 'btn primary', onclick: async () => {
      if (!tCat.value) { toast('Choose a category first.', 'bad'); return; }
      try { const d = await api.post('/rules/test', { category_id: tCat.value, priority: tPrio.value || null, context: tCond.value() }); clear(result); result.hidden = false; result.append(routeResultText(d.route)); }
      catch (e) { toast(e.message, 'bad'); } } }, 'Who would get it?')),
      h('details', null, h('summary', { class: 'muted small', style: { cursor: 'pointer' } }, 'Add conditions'), tCond.el), result)));
  const gaps = cats.rows.filter(c => c.is_active && !c.covered && !c.children);
  if (gaps.length) root.append(notice(plural(gaps.length, 'kind of complaint', 'kinds of complaint') + ' has nobody to go to yet (' + gaps.slice(0, 6).map(c => c.label).join(', ') + (gaps.length > 6 ? ', …' : '') + '). Those stay unassigned until someone assigns them. One rule on a main kind, such as Plumbing, covers every kind under it.', 'warn'));
  setTopAction({ label: 'New rule', run: () => ruleModal(lk, null, r.context_keys, again) });
  root.append(h('div', { class: 'muted', style: { marginBottom: '12px' } }, 'Rules are checked from the most specific to the most general. The first one that fits decides.'));
  if (!r.rows.length) root.append(h('div', { class: 'card' }, empty('No rules yet', 'Without a rule, new cases stay unassigned until someone assigns them.')));
  root.append(h('div', { class: 'stack' }, r.rows.map(x => h('div', { class: 'card rule' + (x.is_active ? '' : ' off') },
    h('div', { class: 'row between' }, h('b', null, x.name), h('span', { class: 'row' }, h('span', { class: 'muted small' }, 'Specificity ' + x.score), h('label', { class: 'row small' }, 'On', switchEl(x.is_active, async v => { await api.post('/rules/' + x.id + '/active', { is_active: v }); x.is_active = v; again(); }, false, 'Rule on: ' + x.name)))),
    ruleSentence(x), x.target_minutes ? h('div', { class: 'muted small' }, 'Response target ' + minutes(x.target_minutes)) : null,
    h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => ruleModal(lk, x, r.context_keys, again) }, 'Edit'),
      h('button', { class: 'btn sm danger', onclick: async () => { if (!await confirmBox('Delete the rule “' + x.name + '”?', { ok: 'Delete', danger: true })) return; try { await api.del('/rules/' + x.id); toast('Deleted', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } } }, 'Delete'))))));
}

// ───────────────────────── Categories ─────────────────────────
function extraEditor(initial) {
  const rows = h('div', { class: 'stack' });
  function addRow(f) {
    f = f || {};
    const type = sel(FIELD_TYPES, f.type || 'text');
    const opts = h('input', { type: 'text', placeholder: 'choices, comma separated', value: (f.options || []).join(', '), style: { flex: 1 } });
    const showOpts = () => { opts.hidden = type.value !== 'choice'; };
    type.addEventListener('change', showOpts); showOpts();
    const row = h('div', { class: 'row', 'data-row': '1' }, h('input', { type: 'text', placeholder: 'Question, e.g. Which lift?', value: f.label || '', style: { flex: 2 } }), type, opts,
      h('button', { class: 'x', type: 'button', onclick: () => row.remove() }, '×'));
    row._key = f.key || '';
    rows.append(row);
  }
  (initial || []).forEach(addRow);
  return {
    el: h('div', null, rows, h('button', { class: 'btn sm', type: 'button', onclick: () => addRow() }, '+ Add a question')),
    value() {
      const used = new Set();
      return [...rows.querySelectorAll('[data-row]')].map(row => {
        const [label, , opts] = row.querySelectorAll('input'), type = row.querySelector('select');
        if (!label.value.trim()) return null;
        let key = row._key || label.value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40) || 'field';
        while (used.has(key)) key += '_2';
        used.add(key);
        const f = { key, label: label.value.trim(), type: type.value };
        if (type.value === 'choice') f.options = opts.value.split(',').map(x => x.trim()).filter(Boolean);
        return f;
      }).filter(Boolean);
    },
  };
}
function categoryModal(lk, prios, cat, parentId, done) {
  const exclude = cat ? descendantsOf(lk, cat.id) : new Set();
  const parentOpts = catOptions(lk, 'Top level').filter(o => !exclude.has(o[0]));
  const label = h('input', { type: 'text', value: cat ? cat.label : '', placeholder: 'e.g. Stuck or entrapment' });
  const parent = sel(parentOpts, cat ? (cat.parent_id || '') : (parentId || ''));
  const prio = sel([['', 'No default'], ...prios.map(p => [p, pretty(p)])], cat ? (cat.default_priority || '') : '');
  const target = h('input', { type: 'number', min: 1, placeholder: 'minutes (optional)', value: cat && cat.target_minutes ? cat.target_minutes : '' });
  const words = h('input', { type: 'text', placeholder: 'lift, elevator, stuck…', value: cat ? (cat.keywords || []).join(', ') : '' });
  const extra = extraEditor(cat ? cat.extra_fields : []);
  modal({ title: cat ? 'Edit kind of complaint' : 'New kind of complaint', wide: true,
    body: h('div', null, field('Name', label), h('div', { class: 'two' }, field('Sits under', parent), field('Default priority', prio, 'Used when the person does not say how urgent it is.')),
      h('div', { class: 'two' }, field('Response target', target, 'How long this kind of case should take. Optional; the priority’s time is used otherwise.'), field('Words that point to it', words, 'Helps the chat bot recognise this kind of complaint.')),
      field('Extra questions to ask', extra.el, 'Asked on top of the usual ones when someone reports this kind of case.')),
    actions: [{ label: 'Cancel' }, { label: 'Save', primary: true, run: async () => {
      const b = { label: label.value.trim(), parent_id: parent.value || null, default_priority: prio.value || null, target_minutes: target.value ? Number(target.value) : null, keywords: words.value.split(',').map(x => x.trim()).filter(Boolean), extra_fields: extra.value() };
      if (cat) await api.patch('/categories/' + cat.id, b); else await api.post('/categories', b);
      toast('Saved', 'ok'); done();
    } }] });
}
async function renderCategoriesTab(root) {
  const [d, lk] = await Promise.all([api.get('/categories'), getLookups(true)]);
  const again = () => { clear(root); renderCategoriesTab(root); };
  setTopAction({ label: 'New kind of complaint', run: () => categoryModal(lk, d.priorities, null, null, again) });
  root.append(h('div', { class: 'muted', style: { marginBottom: '12px' } }, 'What a case can be about. Each kind can have a default priority, a response time and its own extra questions. Click a row to change it.'));
  const unc = d.uncategorised || {};
  root.append(h('div', { class: 'card' }, table([
    { label: 'Category', render: c => h('div', { style: { paddingLeft: (c.depth * 22) + 'px' } }, c.depth ? h('span', { class: 'muted' }, '› ') : null, h('b', null, c.label), c.is_active ? null : [' ', badge('hidden')], h('div', { class: 'muted small' }, c.key)) },
    { label: 'Priority', render: c => c.default_priority ? prioBadge(c.default_priority) : h('span', { class: 'muted' }, '—') },
    { label: 'Response target', render: c => c.target_minutes ? minutes(c.target_minutes) : h('span', { class: 'muted' }, '—') },
    { label: 'Words', render: c => c.keywords.length ? h('div', { class: 'chips' }, c.keywords.slice(0, 4).map(k => h('span', { class: 'chip' }, k)), c.keywords.length > 4 ? h('span', { class: 'muted small' }, '+' + (c.keywords.length - 4)) : null) : h('span', { class: 'muted' }, '—') },
    { label: 'Cases', render: c => c.cases_total ? h('a', { href: href('cases', '', { category: c.id }) }, c.cases_open + ' open / ' + c.cases_total) : h('span', { class: 'muted' }, '0') },
    { label: 'Handled by rule', render: c => c.covered ? badge('Yes', 'ok') : (c.is_active ? badge('No rule', 'warn') : '—') },
    { label: '', render: c => h('div', { class: 'row flat', onclick: e => e.stopPropagation() },
      h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'More for ' + c.label, 'data-popkeep': '1', onclick: e => openPop(e.currentTarget, [
        h('button', { class: 'mi', type: 'button', onclick: () => { closePop(); categoryModal(lk, d.priorities, null, c.id, again); } }, icon('plus'), 'Add a kind under it'),
        h('button', { class: 'mi', type: 'button', onclick: async () => { closePop(); try { await api.patch('/categories/' + c.id, { is_active: !c.is_active }); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('eye'), c.is_active ? 'Hide it' : 'Show it again'),
        h('button', { class: 'mi', type: 'button', style: { color: 'var(--bad)' }, onclick: async () => { closePop(); if (!await confirmBox('Delete “' + c.label + '”? This only works if nothing uses it. Otherwise hide it.', { ok: 'Delete', danger: true })) return; try { await api.del('/categories/' + c.id); toast('Deleted', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('trash'), 'Delete')], { align: 'right', width: 220 }) }, icon('dots', 'sm'))) },
  ], d.rows, { onRow: c => categoryModal(lk, d.priorities, c, null, again), emptyTitle: 'No kinds of complaint yet', emptyText: 'Add the first one.' }),
    unc.total ? h('div', { class: 'card-b muted small' }, h('a', { href: href('cases', '', { category: 'none' }) }, plural(unc.total, 'case') + ' have no category'), ' (' + unc.open + ' open).') : null));
}

// ───────────────────────── Who handles what ─────────────────────────
// One screen for "who looks after what": the areas on the left, the team of the chosen one on the right. It only reads
// and writes case rules (one plain rule per area; a sub-kind follows its area until it is given a team of its own).
// It never decides who gets a case: the database does, and "Try it" asks it.
let WH_SEL = null;
const whPlain = r => !r.intent_key && !Object.keys(r.match || {}).length;
const whOrd = i => ['1st choice', '2nd choice', '3rd choice', '4th choice'][i] || (i + 1) + 'th choice';
async function renderTeamsTab(root) {
  const [cd, rd] = await Promise.all([api.get('/categories'), api.get('/rules')]);
  const cats = cd.rows, byId = Object.fromEntries(cats.map(c => [c.id, c]));
  const teamRule = id => rd.rows.find(r => (r.category_id || null) === id && whPlain(r)) || null;
  const specials = id => rd.rows.filter(r => r.category_id === id && !whPlain(r)).length;
  const inherited = c => { let p = c && c.parent_id ? byId[c.parent_id] : null, n = 0; while (p && n++ < 9) { if (teamRule(p.id)) return p; p = p.parent_id ? byId[p.parent_id] : null; } return null; };
  const again = () => { clear(root); renderTeamsTab(root); };
  let sel = WH_SEL === 'catch' || byId[WH_SEL] ? WH_SEL : ((cats.find(c => !c.depth) || {}).id || 'catch');
  let draft = null, result = null;
  const person = p => ({ id: p.user_id, name: p.name, reachable: p.reachable });
  function load() {
    WH_SEL = sel; result = null;
    const c = sel === 'catch' ? null : byId[sel], rule = teamRule(sel === 'catch' ? null : sel);
    draft = { rule, own: sel === 'catch' || !c.parent_id || !!rule, dirty: false,
      handles: rule ? rule.people.filter(p => p.level === 1).map(person) : [], loop: rule ? rule.people.filter(p => p.level === 2).map(person) : [] };
  }
  async function leaveOk() { return !draft || !draft.dirty || await confirmBox('You have changes that are not saved. Leave them behind?', { ok: 'Leave them', danger: true }); }
  async function pickArea(id) { if (id === sel) return; if (!await leaveOk()) return; sel = id; load(); paint(); }
  function addModal(parentId) {
    const name = h('input', { type: 'text', placeholder: parentId ? 'e.g. Lift stuck' : 'e.g. Finance' });
    modal({ title: parentId ? 'New kind under ' + byId[parentId].label : 'New area', body: field('Name', name, parentId ? 'It follows the team of ' + byId[parentId].label + ' until you give it its own.' : 'You choose who handles it on the next screen.'),
      actions: [{ label: 'Cancel' }, { label: 'Add', primary: true, run: async () => {
        if (!name.value.trim()) throw new Error('Give it a name.');
        const d = await api.post('/categories', { label: name.value.trim(), parent_id: parentId || null });
        WH_SEL = d.id; toast('Added', 'ok'); again();
      } }] });
  }
  async function save() {
    const people = [...draft.handles.map(p => ({ user_id: p.id, level: 1 })), ...draft.loop.map(p => ({ user_id: p.id, level: 2 }))];
    if (!draft.handles.length && !(draft.rule && draft.rule.assign_id)) { toast('Choose at least one person who handles it.', 'bad'); return; }
    const r = draft.rule, c = sel === 'catch' ? null : byId[sel];
    const body = r
      ? { name: r.name, category_id: r.category_id, intent_key: null, match: {}, assign: r.assign_type ? { type: r.assign_type, id: r.assign_id } : null, backup: r.backup_type ? { type: r.backup_type, id: r.backup_id } : null, people, target_minutes: r.target_minutes, is_active: r.is_active }
      : { name: c ? (c.label.length < 2 ? c.label + ' team' : c.label) : 'Anything else (catch-all)', category_id: c ? c.id : null, intent_key: null, match: {}, people, is_active: true };
    try { if (r) await api.put('/rules/' + r.id, body); else await api.post('/rules', body); toast('Saved', 'ok'); again(); }
    catch (e) { toast(e.message, 'bad'); }
  }
  const sentence = (title, handles, loop) => {
    if (!handles.length) return h('span', { style: { color: 'var(--bad)' } }, 'Nobody handles this yet. A case would fall to the “Everything else” team.');
    return h('span', null, 'A case about ', h('b', null, title), ' goes to ', h('b', null, handles[0].name), '.',
      handles.length > 1 ? ' If ' + handles[0].name + ' cannot be reached, ' + handles[1].name + ' takes it.' : '',
      loop.length ? ' ' + loop.map(p => p.name).join(', ') + (loop.length > 1 ? ' are' : ' is') + ' kept in the loop.' : '', ' Everyone listed is told.');
  };
  function listBlock(key, title, help, editable, shown) {
    const arr = shown || draft[key], rows = arr.map((p, i) => h('div', { class: 'wh-pr' }, avatar(p.name),
      h('span', { class: 'wh-nm', style: p.reachable === false ? { color: 'var(--bad)' } : null }, p.name, p.reachable === false ? h('span', { class: 'muted small' }, ' · cannot be messaged right now') : null),
      key === 'handles' ? badge(i === 0 ? 'Owner' : whOrd(i), i === 0 ? 'ok' : null) : badge('In the loop'),
      editable ? h('span', { class: 'wh-ctl' },
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move up', style: { visibility: i ? 'visible' : 'hidden' }, onclick: () => { [arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]; draft.dirty = true; paint(); } }, '↑'),
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move down', style: { visibility: i < arr.length - 1 ? 'visible' : 'hidden' }, onclick: () => { [arr[i + 1], arr[i]] = [arr[i], arr[i + 1]]; draft.dirty = true; paint(); } }, '↓'),
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Remove ' + p.name, onclick: () => { arr.splice(i, 1); draft.dirty = true; paint(); } }, '×')) : null));
    const adder = editable ? personPicker({ placeholder: '+ Add a person…', onChange: p => {
      if (!p) return;
      if (draft.handles.concat(draft.loop).some(x => x.id === p.id)) { toast(p.name + ' is already on this team.', 'bad'); adder.set(null); return; }
      draft[key].push({ id: p.id, name: p.name, reachable: true }); draft.dirty = true; paint();
    } }) : null;
    return h('div', { class: 'wh-blk' }, h('div', { class: 'wh-lab' }, h('b', null, title), ' ', h('span', { class: 'muted small' }, help)),
      rows.length ? rows : h('div', { class: 'muted small', style: { marginBottom: '6px' } }, key === 'handles' ? 'Nobody yet' : 'Nobody yet. This part is optional.'), adder ? adder.el : null);
  }
  function leftCard() {
    const dot = c => { const own = !!teamRule(c.id); return h('span', { class: 'wh-dot ' + (own ? 'ok' : inherited(c) ? 'follow' : 'none'), title: own ? 'Has a team' : inherited(c) ? 'Follows its area' : 'Nobody set up' }); };
    const rows = cats.map(c => h('button', { class: 'wh-row' + (sel === c.id ? ' on' : '') + (c.is_active ? '' : ' off'), type: 'button', style: { paddingLeft: (10 + c.depth * 18) + 'px' }, onclick: () => pickArea(c.id) },
      dot(c), h('span', { class: 'wh-nm' }, c.label), c.is_active ? null : h('span', { class: 'muted small' }, 'hidden')));
    return h('div', { class: 'card wh-left' }, h('div', { class: 'wh-hd' }, 'Areas'), rows,
      h('div', { class: 'wh-sep' }),
      h('button', { class: 'wh-row' + (sel === 'catch' ? ' on' : ''), type: 'button', onclick: () => pickArea('catch') }, h('span', { class: 'wh-dot ' + (teamRule(null) ? 'ok' : 'none') }), h('span', { class: 'wh-nm' }, 'Everything else')),
      h('div', { class: 'wh-sep' }),
      h('div', { class: 'row', style: { padding: '4px 8px 8px', flexWrap: 'wrap' } },
        h('button', { class: 'btn sm', type: 'button', onclick: () => addModal(null) }, '+ Area'),
        sel !== 'catch' ? h('button', { class: 'btn sm', type: 'button', onclick: () => addModal(sel) }, '+ Kind under it') : null));
  }
  function rightCol() {
    const c = sel === 'catch' ? null : byId[sel], col = h('div', { class: 'stack' });
    const from = draft.own ? null : inherited(c), shownRule = from ? teamRule(from.id) : null;
    const handles = draft.own ? draft.handles : (shownRule ? shownRule.people.filter(p => p.level === 1).map(person) : []);
    const loop = draft.own ? draft.loop : (shownRule ? shownRule.people.filter(p => p.level === 2).map(person) : []);
    const head = h('div', { class: 'row' });
    if (!c) head.append(h('b', { style: { fontSize: '16px', flex: 1 } }, 'Everything else'));
    else {
      const ren = h('input', { type: 'text', value: c.label, 'aria-label': 'Name', style: { flex: 1, fontWeight: 600 } });
      ren.addEventListener('change', async () => { const v = ren.value.trim(); if (!v) { ren.value = c.label; return; } try { await api.patch('/categories/' + c.id, { label: v }); toast('Renamed', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); ren.value = c.label; } });
      head.append(ren, h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'More for ' + c.label, 'data-popkeep': '1', onclick: e => openPop(e.currentTarget, [
        h('button', { class: 'mi', type: 'button', onclick: async () => { closePop(); try { await api.patch('/categories/' + c.id, { is_active: !c.is_active }); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('eye'), c.is_active ? 'Hide it' : 'Show it again'),
        h('button', { class: 'mi', type: 'button', style: { color: 'var(--bad)' }, onclick: async () => { closePop(); if (!await confirmBox('Delete “' + c.label + '”? This only works if nothing uses it. Otherwise hide it.', { ok: 'Delete', danger: true })) return; try { await api.del('/categories/' + c.id); WH_SEL = null; toast('Deleted', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('trash'), 'Delete')], { align: 'right', width: 200 }) }, icon('dots', 'sm')));
    }
    col.append(h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, head,
      c && !c.is_active ? notice('This one is hidden, so people cannot pick it. Its team is kept.', 'warn') : null,
      !c ? h('div', { class: 'muted small' }, 'Used when a case has no kind, or its kind has nobody set up.') : null,
      c && c.parent_id && !draft.own ? h('div', { class: 'wh-note' }, h('span', { style: { flex: 1 } }, from ? ['Follows the team of ', h('b', null, from.label), '. Change that team and this follows.'] : 'Nobody is set up above it either. Add a team to it, or to its area.'),
        h('button', { class: 'btn sm', type: 'button', onclick: () => { draft.own = true; if (shownRule) { draft.handles = shownRule.people.filter(p => p.level === 1).map(person); draft.loop = shownRule.people.filter(p => p.level === 2).map(person); } draft.dirty = true; paint(); } }, 'Give it its own team')) : null,
      c && c.parent_id && draft.own && draft.rule ? h('div', { class: 'wh-note warm' }, h('span', { style: { flex: 1 } }, 'Has its own team.'),
        h('button', { class: 'btn sm', type: 'button', onclick: async () => { if (!await confirmBox('Remove its own team? It will follow its area again.', { ok: 'Remove', danger: true })) return; try { await api.del('/rules/' + draft.rule.id); toast('It follows its area again', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } } }, 'Follow its area instead')) : null,
      draft.rule && !draft.rule.people.length && draft.rule.assign_name ? notice('This one points at ' + draft.rule.assign_name + ' the old way (' + draft.rule.assign_type + '). Add people below and save to replace that.', 'warn') : null,
      h('div', { class: 'wh-sent' }, sentence(c ? c.label : 'anything else', handles, loop)),
      listBlock('handles', 'Handles it, in order', 'If the first cannot be reached, the next takes it.', draft.own, draft.own ? null : handles),
      listBlock('loop', 'Kept in the loop', 'Told about every case. Takes it only if nobody above can be reached.', draft.own, draft.own ? null : loop),
      c && specials(c.id) ? h('div', { class: 'muted small' }, plural(specials(c.id), 'extra rule') + ' with conditions also apply to this kind. ', h('a', { href: href('rules', 'rules') }, 'See them')) : null,
      draft.dirty ? h('div', { class: 'wh-save' }, h('span', { style: { flex: 1 } }, 'You have changes that are not saved.'), h('button', { class: 'btn', type: 'button', onclick: () => { load(); paint(); } }, 'Discard'), h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save team')) : null)));
    if (c) {
      const out = h('div', { class: 'quote', hidden: !result });
      if (result) out.append(routeResultText(result.route));
      col.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Try it'), h('div', { class: 'card-b stack' },
        h('div', { class: 'muted small' }, 'Asks the system who would get a new case of this kind today, using what is saved. Names in red cannot be messaged right now.'),
        h('div', null, h('button', { class: 'btn', type: 'button', onclick: async () => {
          if (draft.dirty) { toast('Save your changes first, then try it.', 'bad'); return; }
          try { result = await api.post('/rules/test', { category_id: c.id, context: {} }); paint(); } catch (e) { toast(e.message, 'bad'); } } }, 'Who would get it?')), out)));
    }
    const first = {};
    rd.rows.filter(whPlain).forEach(r => { const p = r.people.find(x => x.level === 1); if (p) first[p.name] = (first[p.name] || 0) + 1; });
    const names = Object.keys(first).sort((a, b) => first[b] - first[a] || a.localeCompare(b));
    col.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'First choice on how many'), h('div', { class: 'card-b chips' },
      names.length ? names.map(n => h('span', { class: 'chip' + (first[n] >= 3 ? ' wh-busy' : '') }, n + ' · ' + first[n] + (first[n] >= 3 ? ' (a lot)' : ''))) : h('span', { class: 'muted small' }, 'Nobody yet'))));
    return col;
  }
  function paint() { clear(root); root.append(h('div', { class: 'wh' }, leftCard(), rightCol())); }
  setTopAction({ label: 'New area', run: () => addModal(null) });
  load(); paint();
}

SECTIONS.rules = {
  title: 'Case rules', sub: 'How new cases are sorted, who gets them, and how fast they must be answered.',
  async render(root, route) {
    if (route.tab === 'rules') return renderRulesTab(root);
    if (route.tab === 'categories') return renderCategoriesTab(root);
    if (route.tab === 'times') { root.append(h('div', { class: 'grid' }, await targetsCard())); return; }
    return renderTeamsTab(root);
  },
};

"""
