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

SECTIONS.rules = {
  title: 'Case rules', sub: 'How new cases are sorted, who gets them, and how fast they must be answered.',
  async render(root, route) {
    if (route.tab === 'categories') return renderCategoriesTab(root);
    if (route.tab === 'times') { root.append(h('div', { class: 'grid' }, await targetsCard())); return; }
    return renderRulesTab(root);
  },
};

"""
