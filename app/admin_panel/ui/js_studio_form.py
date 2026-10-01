JS = r"""
// ───────────────────────── workflow editor: words, context and step forms ─────────────────────────
const ST = { catalog: null, flows: [], byKey: {} };
let EW = null;                       // the workflow being edited (set by the editor)
const SPECIAL = { 'NOW()': 'now', 'TODAY': 'today', 'TODAY+7': 'a week from today', 'TODAY+30': '30 days from today' };
const USERCOL = { user_id: 'id', name: 'name', phone: 'phone', email: 'email', role: 'role' };
const GROUP_ORDER = ['Look up and check', 'Save changes', 'Tell people', 'Approvals', 'Other'];
const STEP_GLYPH = { resolve_entity: '◎', conflict_check: '⛔', require_permission: '✓', derive_field: 'ƒ', compute: '∑', 'db.insert_row': '＋', 'db.update_row': '✎', 'db.upsert_row': '⇅', 'db.delete_row': '✕', 'notify.user': '✉', 'notify.whatsapp': '✉', 'pdf.generate': '▤', otp_gate: '⚿', approval_gate: '☑', ai_price_interpret: '₹', run_workflow: '▣' };
const OPERATORS = [['equals', 'is'], ['not_equals', 'is not'], ['in', 'is one of'], ['not_in', 'is not one of'], ['exists_true', 'has a value'], ['exists_false', 'is empty'], ['gt', 'is more than'], ['gte', 'is at least'], ['lt', 'is less than'], ['lte', 'is at most']];

const tlabel = t => t ? pretty(String(t).replace(/^sheet:/, '')).toLowerCase() : 'record';
const clone = o => JSON.parse(JSON.stringify(o === undefined ? null : o));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
// The forms leave empty optional settings behind (an empty "inputs" box, a blank list). They are
// not part of what a person changed, so they are left out when comparing, checking and saving.
const isBlank = v => v === '' || v === null || v === undefined || (Array.isArray(v) && !v.length) || (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length);
function tidySteps(steps) {
  return (steps || []).map(s => {
    if (!s || typeof s !== 'object' || !s.params || typeof s.params !== 'object') return s;
    const params = {};
    Object.entries(s.params).forEach(([k, v]) => { if (!isBlank(v)) params[k] = v; });
    return { ...s, params };
  });
}
const tidyWork = w => ({ ...w, steps: tidySteps(w.steps) });
function fieldLabel(k) {
  const spec = EW && EW.work.entity_schema && EW.work.entity_schema[k];
  return (spec && spec.label) ? spec.label.toLowerCase() : pretty(k).toLowerCase();
}
const single = t => tlabel(t).replace(/ies$/, 'y').replace(/([^s])s$/, '$1');
function vlabel(v) {
  if (v === null) return 'nothing';
  if (v === undefined || v === '') return '…';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (Array.isArray(v)) return '[' + v.map(vlabel).join(', ') + ']';
  if (typeof v === 'object') return '{' + Object.keys(v).map(k => pretty(k).toLowerCase()).join(', ') + '}';
  if (typeof v !== 'string') return String(v);
  if (!v.startsWith('$')) return SPECIAL[v] || '“' + v + '”';
  const p = v.slice(1).split('.');
  if (p[0] === 'fields') return '‹' + fieldLabel(p[1] || '') + '›';
  if (p[0] === 'user') return '‹the person’s ' + (USERCOL[p[1]] || p[1] || 'record') + '›';
  if (p[0] === 'org_id') return '‹this organisation›';
  if (p[0] === 'inserted') return '‹the new ' + single(p[1]) + '’s ' + pretty(p[2] || 'id').toLowerCase() + '›';
  return '‹' + pretty(p[0]).toLowerCase() + '’s ' + pretty(p.slice(1).join(' ') || 'id').toLowerCase() + '›';
}
function condText(c) {
  if (!c) return '';
  if (c.and) return c.and.map(condText).join(' and ');
  const f = vlabel(c.field).replace(/[‹›]/g, '');
  if ('equals' in c) return f + ' is ' + vlabel(c.equals);
  if ('not_equals' in c) return f + ' is not ' + vlabel(c.not_equals);
  if ('in' in c) return f + ' is one of ' + (c.in || []).map(vlabel).join(', ');
  if ('not_in' in c) return f + ' is not one of ' + (c.not_in || []).map(vlabel).join(', ');
  if ('exists' in c) return f + (c.exists ? ' has a value' : ' is empty');
  for (const [k, w] of [['gt', 'is more than'], ['gte', 'is at least'], ['lt', 'is less than'], ['lte', 'is at most']]) if (k in c) return f + ' ' + w + ' ' + vlabel(c[k]);
  return f;
}
function pairsText(o, max) {
  const e = Object.entries(o || {});
  const shown = e.slice(0, max || 3).map(([k, v]) => pretty(k).toLowerCase() + ' ← ' + vlabel(v));
  return shown.join(', ') + (e.length > (max || 3) ? ' …' : '');
}
function describeStep(s) {
  const p = s.params || {}, t = tlabel(p.table);
  const flow = ST.byKey[p.workflow];
  const by = {
    resolve_entity: () => p.match_columns ? 'Find the ' + single(p.table) + ' where ' + pairsText(p.match_columns, 2).replace(/ ← /g, ' is ') : 'Find the ' + single(p.table) + ' whose ' + pretty(p.match_column || 'name').toLowerCase() + ' is ' + vlabel(p.name_from),
    conflict_check: () => 'Stop if a ' + single(p.table) + ' already has ' + pairsText(p.match_columns, 2).replace(/ ← /g, ' = '),
    require_permission: () => 'Check the person is allowed' + ((p.any_of || []).length ? ' (' + p.any_of.join(' or ') + ')' : p.map ? ' (by ' + vlabel(p.from) + ')' : ''),
    derive_field: () => 'Work out ' + pretty(p.field || 'a value').toLowerCase(),
    compute: () => 'Calculate totals',
    'db.insert_row': () => 'Save a new ' + single(p.table) + ': ' + pairsText(p.values, 3),
    'db.update_row': () => 'Change the ' + single(p.table) + ': ' + pairsText(p.set, 3),
    'db.upsert_row': () => 'Save or change a ' + single(p.table) + ': ' + pairsText(p.values, 3),
    'db.delete_row': () => 'Remove a ' + single(p.table),
    'notify.user': () => 'Message ' + vlabel(p.to) + (p.message_template ? ': “' + p.message_template.replace(/\s+/g, ' ').slice(0, 70) + (p.message_template.length > 70 ? '…' : '') + '”' : ''),
    'notify.whatsapp': () => 'Send the confirmation',
    'pdf.generate': () => 'Make the PDF',
    otp_gate: () => 'Ask for a one-time code',
    approval_gate: () => 'Ask for approval',
    ai_price_interpret: () => 'Read the typed prices',
    run_workflow: () => 'Run ' + (flow ? '“' + flow.name + '”' : p.workflow ? '“' + p.workflow + '” (missing)' : 'a building block'),
  };
  const base = by[s.op] ? by[s.op]() : pretty(s.op);
  return base;
}
function catalogSpec(op) { return (ST.catalog.steps || []).find(x => x.op === op); }

// what is available to a step: fields, records found earlier, rows saved earlier
function addToEnv(env, s) {
  const p = s.params || {};
  if (s.op === 'resolve_entity') {
    const into = p.into || String(p.table || '').replace(/s$/, '');
    if (into) env.aliases[into] = p.table;
    Object.keys(p.expose || {}).forEach(k => env.fields.add(k));
  } else if (s.op === 'derive_field' && p.field) env.fields.add(p.field);
  else if (s.op === 'db.insert_row' && p.table) env.inserted.add(p.table);
  else if (s.op === 'run_workflow' && p.workflow && ST.byKey[p.workflow]) Object.assign(env.aliases, ST.byKey[p.workflow].makes || {});
}
function envBefore(index) {
  const env = { fields: new Set(Object.keys(EW.work.entity_schema || {})), aliases: {}, inserted: new Set() };
  EW.work.steps.slice(0, index).forEach(s => addToEnv(env, s));
  return env;
}
const colsOf = t => (ST.catalog.tables[t] || []);

// ----- a "value" control: pick what the person typed, a record found earlier, who they are… or type text -----
function valueOptions(env) {
  const groups = [];
  const f = [...env.fields].map(k => ['$fields.' + k, pretty(k)]);
  if (f.length) groups.push(['What the person typed', f]);
  const rec = [];
  Object.entries(env.aliases).forEach(([a, t]) => colsOf(t).forEach(c => rec.push(['$' + a + '.' + c, pretty(a) + ' › ' + pretty(c)])));
  if (rec.length) groups.push(['A record found earlier', rec]);
  const ins = [];
  env.inserted.forEach(t => ['id', ...colsOf(t).filter(c => c !== 'id')].forEach(c => ins.push(['$inserted.' + t + '.' + c, 'New ' + tlabel(t) + ' › ' + pretty(c)])));
  if (ins.length) groups.push(['Saved by an earlier step', ins]);
  groups.push(['The person doing it', Object.entries(USERCOL).map(([k, l]) => ['$user.' + k, 'Their ' + l])]);
  groups.push(['Other', [['$org_id', 'This organisation'], ['NOW()', 'Now'], ['TODAY', 'Today'], ['TODAY+7', 'A week from today'], ['TODAY+30', '30 days from today']]]);
  return groups;
}
function valuePicker(env, value, onChange) {
  const groups = valueOptions(env);
  const known = new Set(groups.flatMap(g => g[1].map(o => o[0])));
  const isObj = value !== null && typeof value === 'object';
  const wrap = h('div', { class: 'vp' });
  const sel_ = h('select', null, h('option', { value: '' }, 'Pick a value…'),
    groups.map(g => h('optgroup', { label: g[0] }, g[1].map(o => h('option', { value: o[0] }, o[1])))),
    h('option', { value: '__text' }, 'Fixed text or number…'),
    h('option', { value: '__null' }, 'Nothing (clears it)'),
    isObj ? h('option', { value: '__json' }, 'Structured value (JSON)') : null);
  const text = h('input', { type: 'text', placeholder: 'or type a value', style: { display: 'none' } });
  const json = h('textarea', { rows: 3, style: { display: 'none', fontFamily: 'ui-monospace,monospace' } });
  function show(mode) { text.style.display = mode === 'text' ? '' : 'none'; json.style.display = mode === 'json' ? '' : 'none'; }
  if (isObj) { sel_.value = '__json'; json.value = JSON.stringify(value, null, 2); show('json'); }
  else if (typeof value === 'string' && known.has(value)) sel_.value = value;
  else if (typeof value === 'string' && value.startsWith('$')) { sel_.append(h('option', { value: value }, 'Custom: ' + value)); sel_.value = value; }
  else if (value === null) { sel_.value = '__null'; show(''); }
  else if (value === undefined || value === '') { sel_.value = ''; show('text'); }
  else { sel_.value = '__text'; text.value = String(value); show('text'); }
  sel_.addEventListener('change', () => {
    if (sel_.value === '__text') { show('text'); text.focus(); onChange(text.value === '' ? '' : coerce(text.value), true); }
    else if (sel_.value === '__null') { show(''); onChange(null, true); }
    else if (sel_.value === '__json') { show('json'); }
    else if (sel_.value === '') { show('text'); onChange(text.value === '' ? '' : coerce(text.value), true); }
    else { show(''); onChange(sel_.value, true); }
  });
  text.addEventListener('input', () => { sel_.value = text.value === '' ? '' : '__text'; onChange(coerce(text.value), false); });
  text.addEventListener('change', () => onChange(coerce(text.value), true));
  json.addEventListener('change', () => { try { onChange(JSON.parse(json.value), true); json.style.borderColor = ''; } catch (e) { json.style.borderColor = 'var(--bad)'; } });
  wrap.append(sel_, text, json);
  return wrap;
}
const coerce = t => (t.trim() !== '' && !isNaN(t) && !/^0\d/.test(t.trim())) ? Number(t) : (t === 'true' ? true : t === 'false' ? false : t);

// ----- "only if" conditions -----
function parseWhen(c) {
  const flat = [];
  (function walk(x) { if (!x) return; if (x.and) x.and.forEach(walk); else flat.push(x); })(c);
  return flat.map(a => {
    let op = OPERATORS.find(o => o[0] !== 'exists_true' && o[0] !== 'exists_false' && o[0] in a);
    let key = op ? op[0] : null;
    if (!key && 'exists' in a) key = a.exists ? 'exists_true' : 'exists_false';
    return { field: a.field || '', op: key || 'equals', value: key && a[key] !== undefined ? (Array.isArray(a[key]) ? a[key].join(', ') : a[key]) : '' };
  });
}
function buildWhen(rows) {
  const atoms = rows.filter(r => r.field).map(r => {
    const a = { field: r.field };
    if (r.op === 'exists_true') a.exists = true;
    else if (r.op === 'exists_false') a.exists = false;
    else if (r.op === 'in' || r.op === 'not_in') a[r.op] = String(r.value).split(',').map(x => x.trim()).filter(Boolean);
    else a[r.op] = ['gt', 'gte', 'lt', 'lte'].includes(r.op) ? coerce(String(r.value)) : r.value;
    return a;
  });
  return atoms.length === 0 ? null : atoms.length === 1 ? atoms[0] : { and: atoms };
}
function conditionEditor(step, index, commit) {
  const env = envBefore(index);
  let rows = parseWhen(step.when);
  const box = h('div', { class: 'stack' });
  function save(redraw) { const w = buildWhen(rows); if (w) step.when = w; else delete step.when; commit(redraw); }
  function draw() {
    fill(box, rows.map((r, i) => h('div', { class: 'cond' },
      valuePicker(env, r.field, v => { r.field = v; save(false); }),
      sel(OPERATORS.map(o => [o[0], o[1]]), r.op, { onchange: e => { r.op = e.target.value; save(true); draw(); } }),
      (r.op === 'exists_true' || r.op === 'exists_false') ? null : h('input', { type: 'text', value: r.value, placeholder: r.op === 'in' || r.op === 'not_in' ? 'one, two, three' : 'value', oninput: e => { r.value = e.target.value; save(false); } }),
      h('button', { class: 'x', type: 'button', title: 'Remove', onclick: () => { rows.splice(i, 1); save(true); draw(); } }, '×'))),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { rows.push({ field: '', op: 'equals', value: '' }); draw(); } }, rows.length ? '+ Another condition' : '+ Only run this step if…'));
  }
  draw();
  return box;
}

// ----- editors for lists and maps -----
function tagsEditor(list, suggestions, onChange) {
  const box = h('div', { class: 'tags' });
  const dl = 'dl' + Math.random().toString(36).slice(2, 8);
  const input = h('input', { type: 'text', list: dl, placeholder: 'Type and press Enter' });
  const hints = h('datalist', { id: dl }, (suggestions || []).map(s => h('option', { value: s })));
  function draw() {
    fill(box, list.map((t, i) => h('span', { class: 'chip' }, t, h('button', { class: 'x', type: 'button', onclick: () => { list.splice(i, 1); onChange(list); draw(); } }, '×'))), input, hints);
  }
  input.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) { e.preventDefault(); list.push(input.value.trim()); onChange(list); draw(); box.querySelector('input').focus(); } });
  input.addEventListener('blur', () => { if (input.value.trim()) { list.push(input.value.trim()); onChange(list); draw(); } });
  draw();
  return box;
}
function mapEditor(spec, obj, tableOf, env, commit) {
  // obj is edited in place; keys are columns (kind keys:'column'), free text, or fields
  const box = h('div', { class: 'stack' });
  const colKeys = spec.keys === 'column';
  function draw() {
    const cols = colKeys ? colsOf(tableOf()) : [];
    const entries = Object.entries(obj);
    fill(box, entries.map(([k, v]) => {
      const keyCtl = colKeys
        ? sel([['', 'Column…'], ...cols.map(c => [c, pretty(c)]), ...(cols.includes(k) || !k ? [] : [[k, k + ' (missing)']])], k, { onchange: e => rename(k, e.target.value) })
        : h('input', { type: 'text', value: k, placeholder: spec.kind === 'map_text' ? 'when it is…' : 'name', onchange: e => rename(k, e.target.value.trim()) });
      let valCtl;
      if (spec.kind === 'map_value') valCtl = valuePicker(env, v, (nv, redraw) => { obj[k] = nv; commit(false); });
      else if (spec.kind === 'map_column') valCtl = sel([['', 'Column…'], ...colsOf(tableOf()).map(c => [c, pretty(c)])], v, { onchange: e => { obj[k] = e.target.value; commit(true); } });
      else valCtl = h('input', { type: 'text', value: v, placeholder: 'the permission', list: 'permlist', oninput: e => { obj[k] = e.target.value; commit(false); } });
      return h('div', { class: 'maprow' }, keyCtl, valCtl, h('button', { class: 'x', type: 'button', title: 'Remove', onclick: () => { delete obj[k]; commit(true); draw(); } }, '×'));
    }), h('button', { class: 'btn sm', type: 'button', onclick: () => { obj[''] = ''; draw(); } }, '+ Add'));
  }
  function rename(oldK, newK) {
    if (newK === oldK) return;
    const out = {};
    for (const [k, v] of Object.entries(obj)) out[k === oldK ? newK : k] = v;
    for (const k of Object.keys(obj)) delete obj[k];
    Object.assign(obj, out);
    commit(true); draw();
  }
  draw();
  return box;
}

// ----- one parameter of a step -----
function paramControl(p, step, index, commit, rerender) {
  const params = step.params = step.params || {};
  const env = envBefore(index);
  const set = (v, redraw) => { if (v === '' || v === null || (Array.isArray(v) && !v.length) || (v && typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length)) delete params[p.key]; else params[p.key] = v; commit(!!redraw); };
  const table = () => params.table;
  let ctl;
  switch (p.kind) {
    case 'table': ctl = sel([['', 'Choose a table…'], ...Object.keys(ST.catalog.tables).map(t => [t, pretty(t)]), ...(params.table && !ST.catalog.tables[params.table] ? [[params.table, params.table]] : [])], params.table || '', { onchange: e => { set(e.target.value, true); rerender(); } }); break;
    case 'column': ctl = sel([['', 'Choose a column…'], ...colsOf(table()).map(c => [c, pretty(c)])], params[p.key] || p.default || '', { onchange: e => set(e.target.value, true) }); break;
    case 'alias': ctl = h('input', { type: 'text', value: params[p.key] || '', placeholder: 'e.g. case', pattern: '[a-z_][a-z0-9_]*', oninput: e => set(e.target.value.trim().toLowerCase(), false), onchange: e => { set(e.target.value.trim().toLowerCase(), true); rerender(); } }); break;
    case 'value': ctl = valuePicker(env, params[p.key], (v, redraw) => set(v, redraw)); break;
    case 'text': ctl = h('input', { type: 'text', value: params[p.key] || '', oninput: e => set(e.target.value, false), onchange: e => set(e.target.value, true) }); break;
    case 'longtext': {
      const ta = h('textarea', { rows: 4, oninput: e => set(e.target.value, false), onchange: e => set(e.target.value, true) });
      ta.value = params[p.key] || '';
      const names = [...env.fields, ...(env.aliases.case ? colsOf(env.aliases.case).map(c => 'case_' + c) : [])];
      const ins = sel([['', 'Insert a value…'], ...names.map(n => ['{' + n + '}', pretty(n)])], '', { onchange: e => { if (!e.target.value) return; const a = ta.selectionStart || ta.value.length; ta.value = ta.value.slice(0, a) + e.target.value + ta.value.slice(a); set(ta.value, true); e.target.value = ''; } });
      ctl = h('div', { class: 'stack' }, ta, ins); break;
    }
    case 'number': ctl = h('input', { type: 'number', value: params[p.key] ?? '', onchange: e => set(e.target.value === '' ? '' : Number(e.target.value), true) }); break;
    case 'bool': ctl = h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: !!params[p.key], onchange: e => set(e.target.checked ? true : '', true) }), 'Yes'); break;
    case 'choice': ctl = sel(p.options, params[p.key] || '', { onchange: e => set(e.target.value, true) }); break;
    case 'list_text': {
      const list = Array.isArray(params[p.key]) ? params[p.key] : [];
      ctl = h('div', null, tagsEditor(list, ST.catalog.permissions, l => set(l, false)), h('datalist', { id: 'permlist' }, ST.catalog.permissions.map(x => h('option', { value: x })))); break;
    }
    case 'list_column': {
      const list = Array.isArray(params[p.key]) ? params[p.key] : [];
      ctl = h('div', { class: 'checks' }, colsOf(table()).map(c => h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: list.includes(c), onchange: e => { const l = list.filter(x => x !== c); if (e.target.checked) l.push(c); set(l, false); } }), pretty(c)))); break;
    }
    case 'map_value': case 'map_column': case 'map_text': {
      const obj = params[p.key] && typeof params[p.key] === 'object' && !Array.isArray(params[p.key]) ? params[p.key] : (params[p.key] = {});
      ctl = mapEditor(p, obj, table, env, redraw => { if (!Object.keys(obj).length || Object.keys(obj).includes('')) { /* keep empty rows while editing */ } commit(!!redraw); }); break;
    }
    case 'sequence': {
      const seq = params[p.key] && typeof params[p.key] === 'object' ? params[p.key] : {};
      const upd = () => { const o = { ...seq }; if (!o.field || !o.prefix) delete params[p.key]; else params[p.key] = o; commit(false); };
      ctl = h('div', { class: 'two' },
        field('Column', sel([['', 'Choose…'], ...colsOf(table()).map(c => [c, pretty(c)])], seq.field || '', { onchange: e => { seq.field = e.target.value; upd(); } })),
        field('Starts with', h('input', { type: 'text', value: seq.prefix || '', placeholder: 'CS-{YY}-{MM}-', oninput: e => { seq.prefix = e.target.value; upd(); } })),
        field('Digits', h('input', { type: 'number', value: seq.pad ?? '', oninput: e => { seq.pad = e.target.value === '' ? undefined : Number(e.target.value); upd(); } })),
        field('First number', h('input', { type: 'number', value: seq.start ?? '', oninput: e => { seq.start = e.target.value === '' ? undefined : Number(e.target.value); upd(); } }))); break;
    }
    case 'workflow': {
      const runnable = ST.flows.filter(w => (!EW || w.id !== EW.id) && w.workflow_type !== 'read');
      runnable.sort((a, b) => (b.kind === 'block') - (a.kind === 'block'));
      const options = runnable.map(w => [w.intent_key, w.name + (w.kind === 'block' ? ' (building block)' : '')]);
      ctl = sel([['', 'Choose one…'], ...options, ...(params.workflow && !ST.byKey[params.workflow] ? [[params.workflow, params.workflow + ' (missing)']] : [])], params.workflow || '', { onchange: e => { set(e.target.value, true); rerender(); } }); break;
    }
    default: ctl = h('input', { type: 'text', value: String(params[p.key] ?? ''), onchange: e => set(e.target.value, true) });
  }
  return field(p.label + (p.required ? ' *' : ''), ctl, p.help);
}

// ----- the form that opens inside a step card -----
function stepForm(step, index, commit, rerender) {
  const spec = catalogSpec(step.op);
  const box = h('div', { class: 'stepform' });
  if (!spec) {
    box.append(notice('This step type (' + step.op + ') is not one the editor knows. Edit it as JSON below.', 'warn'));
  } else {
    const main = spec.params.filter(p => !p.advanced), adv = spec.params.filter(p => p.advanced);
    main.forEach(p => box.append(paramControl(p, step, index, commit, rerender)));
    if (adv.length) {
      const open = adv.some(p => step.params && step.params[p.key] !== undefined);
      box.append(h('details', open ? { open: true } : null, h('summary', { class: 'muted small' }, 'More options'), adv.map(p => paramControl(p, step, index, commit, rerender))));
    }
    if (!spec.params.length) box.append(h('div', { class: 'muted small' }, 'Nothing to set for this step.'));
  }
  box.append(h('div', { class: 'field' }, h('label', null, 'Only run this step if…'), conditionEditor(step, index, commit)));
  const jt = h('textarea', { rows: 6, style: { fontFamily: 'ui-monospace,monospace' } });
  jt.value = JSON.stringify(step, null, 2);
  const msg = h('span', { class: 'small', style: { color: 'var(--bad)' } });
  box.append(h('details', null, h('summary', { class: 'muted small' }, 'Edit this step as JSON'), jt,
    h('div', { class: 'row', style: { marginTop: '6px' } }, h('button', { class: 'btn sm', type: 'button', onclick: () => {
      try { const v = JSON.parse(jt.value); if (!v || typeof v !== 'object' || !v.op) throw new Error('A step needs an "op".'); for (const k of Object.keys(step)) delete step[k]; Object.assign(step, v); commit(true); rerender(); }
      catch (e) { msg.textContent = e.message; } } }, 'Apply JSON'), msg)));
  return box;
}
"""
