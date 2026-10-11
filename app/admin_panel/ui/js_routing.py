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
// One table: every area with its owner, its backups (also told) and the people only kept informed. Click a row to edit
// its team under it. A kind that has no team of its own says "Same team as ..." and follows its area; an area with none
// follows "Everything else". It only reads and writes case rules (one plain rule per area or kind). It never decides who
// gets a case: the database does, and "Try it" asks it.
let WH_OPEN = null, WH_HIDDEN = false;
const WH_KIDS = {};
const whPlain = r => !r.intent_key && !Object.keys(r.match || {}).length;
const whShort = n => { const p = String(n).split(' '); return p.length > 1 ? p[0] + ' ' + p[p.length - 1][0] + '.' : n; };
async function renderTeamsTab(root) {
  const [cd, rd] = await Promise.all([api.get('/categories'), api.get('/rules')]);
  const cats = cd.rows, byId = Object.fromEntries(cats.map(c => [c.id, c]));
  const teamRule = id => rd.rows.find(r => (r.category_id || null) === id && whPlain(r)) || null;
  const specials = id => rd.rows.filter(r => r.category_id === id && !whPlain(r)).length;
  const kidsOf = id => cats.filter(c => c.parent_id === id);
  const hiddenCount = cats.filter(c => !c.is_active && !c.parent_id).length;
  const again = () => { clear(root); renderTeamsTab(root); };
  const person = p => ({ id: p.user_id, name: p.name, reachable: p.reachable });
  const lists = rule => ({ handles: rule ? rule.people.filter(p => p.level === 1).map(person) : [], loop: rule ? rule.people.filter(p => p.level === 2).map(person) : [] });
  const CATCH = { id: 'catch', label: 'Everything else', parent_id: null, depth: 0, is_active: true };
  const effective = c => {
    if (c.id === 'catch') return { rule: teamRule(null), from: null };
    if (teamRule(c.id)) return { rule: teamRule(c.id), from: null };
    let p = c.parent_id ? byId[c.parent_id] : null, n = 0;
    while (p && n++ < 9) { if (teamRule(p.id)) return { rule: teamRule(p.id), from: p.label }; p = p.parent_id ? byId[p.parent_id] : null; }
    return { rule: teamRule(null), from: 'Everything else' };
  };
  let draft = null, result = null;
  function load(id) {
    WH_OPEN = id; result = null; draft = null;
    const c = id === 'catch' ? CATCH : byId[id];
    if (!c) { WH_OPEN = null; return; }
    const e = effective(c);
    draft = { own: !e.from, dirty: false, rule: e.from ? null : e.rule, ...lists(e.rule) };
  }
  async function leaveOk() { return !draft || !draft.dirty || await confirmBox('You have changes that are not saved. Leave them behind?', { ok: 'Leave them', danger: true }); }
  async function toggle(id) { if (!await leaveOk()) return; if (WH_OPEN === id) { WH_OPEN = null; draft = null; } else load(id); paint(); }
  function addModal(parentId) {
    const name = h('input', { type: 'text', placeholder: parentId ? 'e.g. Lift stuck' : 'e.g. Finance' });
    modal({ title: parentId ? 'New kind under ' + byId[parentId].label : 'New area', body: field('Name', name, parentId ? 'It uses the team of ' + byId[parentId].label + ' until you give it its own.' : 'It uses the “Everything else” team until you give it its own.'),
      actions: [{ label: 'Cancel' }, { label: 'Add', primary: true, run: async () => {
        if (!name.value.trim()) throw new Error('Give it a name.');
        const d = await api.post('/categories', { label: name.value.trim(), parent_id: parentId || null });
        WH_OPEN = d.id; if (parentId) WH_KIDS[parentId] = true; toast('Added', 'ok'); again();
      } }] });
  }
  async function save(c) {
    const people = [...draft.handles.map(p => ({ user_id: p.id, level: 1 })), ...draft.loop.map(p => ({ user_id: p.id, level: 2 }))];
    if (!draft.handles.length && !(draft.rule && draft.rule.assign_id)) { toast('Choose an owner first.', 'bad'); return; }
    const r = draft.rule;
    const body = r
      ? { name: r.name, category_id: r.category_id, intent_key: null, match: {}, assign: r.assign_type ? { type: r.assign_type, id: r.assign_id } : null, backup: r.backup_type ? { type: r.backup_type, id: r.backup_id } : null, people, target_minutes: r.target_minutes, is_active: r.is_active }
      : { name: c.id === 'catch' ? 'Anything else (catch-all)' : (c.label.length < 2 ? c.label + ' team' : c.label), category_id: c.id === 'catch' ? null : c.id, intent_key: null, match: {}, people, is_active: true };
    try { if (r) await api.put('/rules/' + r.id, body); else await api.post('/rules', body); toast('Saved', 'ok'); again(); }
    catch (e) { toast(e.message, 'bad'); }
  }
  const nameSpan = p => h('span', { class: 'wh-pn', style: p.reachable === false ? { color: 'var(--bad)' } : null, title: p.reachable === false ? 'Cannot be messaged right now' : null }, p.name);
  const chips = (arr, max, short) => arr.length ? h('span', { class: 'chips' }, arr.slice(0, max).map(p => h('span', { class: 'chip', style: p.reachable === false ? { color: 'var(--bad)' } : null }, short ? whShort(p.name) : p.name)), arr.length > max ? h('span', { class: 'chip sunk' }, '+' + (arr.length - max)) : null) : h('span', { class: 'muted' }, 'none');
  const first = p => String(p.name).split(' ')[0];
  const sentence = (title, handles, loop) => {
    if (!handles.length) return h('span', { style: { color: 'var(--bad)' } }, 'Nobody is the owner yet, so a case would fall to the “Everything else” team.');
    const back = handles.slice(1);
    return h('span', null, 'A case about ', h('b', null, title), ' goes to ', h('b', null, handles[0].name), '.',
      back.length ? ' If ' + first(handles[0]) + ' cannot be reached: ' + back.map(first).join(', then ') + '.' : '',
      loop.length ? ' Also told: ' + loop.map(first).join(', ') + '.' : '');
  };
  function roleOf(p) { return draft.handles[0] === p ? 'owner' : draft.handles.includes(p) ? 'backup' : 'informed'; }
  function setRole(p, role) {
    draft.handles = draft.handles.filter(x => x !== p); draft.loop = draft.loop.filter(x => x !== p);
    if (role === 'owner') draft.handles.unshift(p); else if (role === 'backup') draft.handles.push(p); else draft.loop.push(p);
    draft.dirty = true; paint();
  }
  function personRow(p) {
    const role = roleOf(p), i = draft.handles.indexOf(p);
    const pick = sel([['owner', 'Owner'], ['backup', 'Backup (also told)'], ['informed', 'Informed only']], role, { 'aria-label': 'Role of ' + p.name });
    pick.addEventListener('change', () => setRole(p, pick.value));
    return h('div', { class: 'wh-pr' }, avatar(p.name), h('span', { class: 'wh-pnm' }, nameSpan(p), p.reachable === false ? h('span', { class: 'muted small' }, ' · cannot be messaged right now') : null), pick,
      role === 'backup' ? [
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move up', style: { visibility: i > 1 ? 'visible' : 'hidden' }, onclick: () => { [draft.handles[i - 1], draft.handles[i]] = [draft.handles[i], draft.handles[i - 1]]; draft.dirty = true; paint(); } }, '↑'),
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move down', style: { visibility: i < draft.handles.length - 1 ? 'visible' : 'hidden' }, onclick: () => { [draft.handles[i + 1], draft.handles[i]] = [draft.handles[i], draft.handles[i + 1]]; draft.dirty = true; paint(); } }, '↓')] : null,
      h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Remove ' + p.name, onclick: () => { draft.handles = draft.handles.filter(x => x !== p); draft.loop = draft.loop.filter(x => x !== p); draft.dirty = true; paint(); } }, '×'));
  }
  function editor(c, e) {
    const box = h('div', { class: 'wh-ed' }), editable = draft.own;
    const head = h('div', { class: 'row' });
    if (c.id === 'catch') head.append(h('b', { style: { flex: 1 } }, 'Everything else'), h('span', { class: 'muted small' }, 'Used when a case has no kind, or its kind has nobody set up.'));
    else {
      const ren = h('input', { type: 'text', value: c.label, 'aria-label': 'Name', style: { flex: 1, fontWeight: 600 } });
      ren.addEventListener('change', async () => { const v = ren.value.trim(); if (!v) { ren.value = c.label; return; } try { await api.patch('/categories/' + c.id, { label: v }); toast('Renamed', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); ren.value = c.label; } });
      head.append(ren, h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'More for ' + c.label, 'data-popkeep': '1', onclick: ev => openPop(ev.currentTarget, [
        h('button', { class: 'mi', type: 'button', onclick: async () => { closePop(); try { await api.patch('/categories/' + c.id, { is_active: !c.is_active }); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('eye'), c.is_active ? 'Hide it' : 'Show it again'),
        h('button', { class: 'mi', type: 'button', style: { color: 'var(--bad)' }, onclick: async () => { closePop(); if (!await confirmBox('Delete “' + c.label + '”? This only works if nothing uses it. Otherwise hide it.', { ok: 'Delete', danger: true })) return; try { await api.del('/categories/' + c.id); WH_OPEN = null; toast('Deleted', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); } } }, icon('trash'), 'Delete')], { align: 'right', width: 200 }) }, icon('dots', 'sm')));
    }
    box.append(head);
    if (c.id !== 'catch' && !c.is_active) box.append(notice('This one is hidden, so people cannot pick it. Its team is kept.', 'warn'));
    box.append(h('div', { class: 'wh-sent' }, sentence(c.id === 'catch' ? 'anything else' : c.label, editable ? draft.handles : lists(e.rule).handles, editable ? draft.loop : lists(e.rule).loop)));
    if (!editable) box.append(h('div', { class: 'wh-note' }, h('span', { style: { flex: 1 } }, ['This one uses the team of ', h('b', null, e.from), '. Change that team and this follows.']),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { draft.own = true; draft.dirty = true; Object.assign(draft, lists(e.rule)); paint(); } }, 'Give it its own team')));
    else if (c.id !== 'catch' && draft.rule) box.append(h('div', { class: 'wh-note warm' }, h('span', { style: { flex: 1 } }, 'Has its own team.'),
      h('button', { class: 'btn sm', type: 'button', onclick: async () => { if (!await confirmBox('Remove its own team? It will use the team of ' + (c.parent_id && byId[c.parent_id] ? byId[c.parent_id].label : 'Everything else') + ' again.', { ok: 'Remove', danger: true })) return; try { await api.del('/rules/' + draft.rule.id); toast('Done', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); } } }, 'Use the team above again')));
    if (draft.rule && !draft.rule.people.length && draft.rule.assign_name) box.append(notice('This one points at ' + draft.rule.assign_name + ' the old way (' + draft.rule.assign_type + '). Add people below and save to replace that.', 'warn'));
    const all = editable ? [...draft.handles, ...draft.loop] : [];
    if (editable) {
      all.sort((a, b) => ({ owner: 0, backup: 1, informed: 2 }[roleOf(a)] - { owner: 0, backup: 1, informed: 2 }[roleOf(b)]));
      all.forEach(p => box.append(personRow(p)));
      const adder = personPicker({ placeholder: '+ Add a person…', onChange: p => {
        if (!p) return;
        if (all.some(x => x.id === p.id)) { toast(p.name + ' is already on this team.', 'bad'); adder.set(null); return; }
        draft.handles.push({ id: p.id, name: p.name, reachable: true }); draft.dirty = true; paint();
      } });
      box.append(adder.el, h('div', { class: 'muted small', style: { marginTop: '6px' } }, 'The owner takes the case. Backups take it in that order if the owner cannot be reached, and are also told. Informed people are only told.'));
    }
    if (draft.dirty) box.append(h('div', { class: 'wh-save' }, h('span', { style: { flex: 1 } }, 'You have changes that are not saved.'), h('button', { class: 'btn', type: 'button', onclick: () => { load(c.id); paint(); } }, 'Discard'), h('button', { class: 'btn primary', type: 'button', onclick: () => save(c) }, 'Save team')));
    if (c.id !== 'catch') {
      const out = h('div', { class: 'quote', hidden: !result });
      if (result) out.append(routeResultText(result.route));
      box.append(h('div', { class: 'wh-try' }, h('button', { class: 'btn sm', type: 'button', onclick: async () => {
        if (draft.dirty) { toast('Save your changes first, then try it.', 'bad'); return; }
        try { result = await api.post('/rules/test', { category_id: c.id, context: {} }); paint(); } catch (x) { toast(x.message, 'bad'); } } }, 'Who would get a new case today?'), out));
      box.append(h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn sm', type: 'button', onclick: () => addModal(c.id) }, '+ Add a kind under ' + c.label)));
      if (specials(c.id)) box.append(h('div', { class: 'muted small', style: { marginTop: '6px' } }, plural(specials(c.id), 'extra rule') + ' with conditions also apply to this kind. ', h('a', { href: href('rules', 'rules') }, 'See them')));
    }
    return box;
  }
  function rowFor(c, depth) {
    const e = effective(c), L = lists(e.rule), kids = kidsOf(c.id).filter(k => WH_HIDDEN || k.is_active), on = WH_OPEN === c.id;
    const nm = h('div', { class: 'wh-name', style: { paddingLeft: (depth * 22) + 'px' } }, h('span', null, c.label), c.is_active ? null : [' ', badge('hidden')],
      kids.length ? h('button', { class: 'wh-kids', type: 'button', onclick: ev => { ev.stopPropagation(); WH_KIDS[c.id] = !WH_KIDS[c.id]; paint(); } }, (WH_KIDS[c.id] ? 'Hide ' : 'Show ') + plural(kids.length, 'kind')) : null);
    const cells = e.from
      ? [h('div', { class: 'wh-same' }, 'Same team as ' + e.from)]
      : [h('div', { class: 'wh-own' }, L.handles.length ? nameSpan(L.handles[0]) : h('span', { style: { color: 'var(--bad)' } }, 'Nobody')), h('div', null, chips(L.handles.slice(1), 2, true)), h('div', null, chips(L.loop, 1, true))];
    const out = [h('div', { class: 'wh-r' + (on ? ' on' : '') + (e.from ? ' same' : ''), role: 'button', tabindex: 0, 'aria-expanded': on ? 'true' : 'false', onclick: () => toggle(c.id), onkeydown: ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(c.id); } } }, nm, ...cells)];
    if (on && draft) out.push(editor(c, e));
    if (WH_KIDS[c.id]) kids.forEach(k => out.push(...rowFor(k, depth + 1)));
    return out;
  }
  function paint() {
    clear(root);
    const tops = cats.filter(c => !c.parent_id && (WH_HIDDEN || c.is_active));
    const sw = h('input', { type: 'checkbox', checked: WH_HIDDEN, 'aria-label': 'Show hidden areas' });
    sw.addEventListener('change', () => { WH_HIDDEN = sw.checked; paint(); });
    root.append(h('div', { class: 'row between', style: { marginBottom: '10px' } },
      hiddenCount ? h('label', { class: 'row small' }, sw, 'Show hidden areas (' + hiddenCount + ')') : h('span'),
      h('button', { class: 'btn', type: 'button', onclick: () => addModal(null) }, '+ Area')));
    root.append(h('div', { class: 'wh-t' }, h('div', { class: 'wh-hd' }, h('div', null, 'Area'), h('div', null, 'Owner'), h('div', null, 'Backups (also told)'), h('div', null, 'Informed only')),
      ...tops.flatMap(c => rowFor(c, 0)), h('div', { class: 'wh-sep' }), ...rowFor(CATCH, 0)));
  }
  setTopAction({ label: 'New area', run: () => addModal(null) });
  if (WH_OPEN && (WH_OPEN === 'catch' || byId[WH_OPEN])) load(WH_OPEN); else { WH_OPEN = null; }
  paint();
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
