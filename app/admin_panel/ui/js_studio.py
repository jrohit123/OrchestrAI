JS = r"""
// ───────────────────────── Workflows: shared helpers ─────────────────────────
const PARTY_PLAIN = { requester: 'who raised it', assignee: 'who has it', level2: 'level 2', helper: 'helpers', watcher: 'watchers' };
async function ensureStudio() {
  const [cat, fl] = await Promise.all([api.get('/studio/catalog'), api.get('/workflows')]);
  ST.catalog = cat; ST.flows = fl.rows; ST.roles = fl.roles;
  ST.byKey = Object.fromEntries(fl.rows.map(w => [w.intent_key, w]));
}
const classicUrl = () => '/admin/' + encodeURIComponent(ORG) + '/legacy';
function openWorkflow(id) { go('workflows', '', { w: id }); }

// ───────────────────────── Workflows: the editor ─────────────────────────
const EDIT_KEYS = ['name', 'description', 'steps', 'entity_schema', 'gates', 'training_phrases', 'slash_command', 'kind', 'settings', 'response_format'];
// Where the boxes sit on the canvas is kept in settings.layout, apart from the rest of the workflow:
// moving a box is not a change to what the workflow does, so it never makes a new version or "Unsaved".
const LAYOUT_V = 1;
// The places belong to one size of box (little tiles or full cards). A layout saved before tiles existed was made for full cards.
const layoutFits = (layout, ids, size) => !!layout && layout.v === LAYOUT_V && Array.isArray(layout.steps) && layout.steps.length === ids.length && (layout.view || 'detailed') === size;
function layoutToPos(layout, ids, pids, size) {
  const pos = {};
  if (layoutFits(layout, ids, size)) {
    if (Array.isArray(layout.trigger)) pos.trigger = { x: layout.trigger[0], y: layout.trigger[1] };
    ids.forEach((id, i) => { const p = layout.steps[i]; if (Array.isArray(p)) pos[String(id)] = { x: p[0], y: p[1] }; });
    if (Array.isArray(layout.report)) pos.report = { x: layout.report[0], y: layout.report[1] };
    if (Array.isArray(layout.parked) && layout.parked.length === pids.length) pids.forEach((id, k) => { const p = layout.parked[k]; if (Array.isArray(p)) pos[String(id)] = { x: p[0], y: p[1] }; });
  }
  return pos;
}
function layoutMode(layout, ids, size) {          // how the boxes were arranged: rows, stage or column (empty when placed by hand)
  return layoutFits(layout, ids, size) && ['column', 'rows', 'stage'].includes(layout.mode) ? layout.mode : '';
}
function layoutOut(pos, idList, mode, cols, pidList, size) {
  pos = pos || EW.pos;
  const ids = (idList || EW.ids).map(String), pids = (pidList || EW.pids).map(String);
  const ok = id => pos[id] && isFinite(pos[id].x) && isFinite(pos[id].y);
  if (!ids.every(ok)) return null;
  const pt = id => [Math.round(pos[id].x), Math.round(pos[id].y)];
  const out = { v: LAYOUT_V, n: ids.length, steps: ids.map(pt), view: size || EW.size };
  if (ok('trigger')) out.trigger = pt('trigger');
  if (ok('report')) out.report = pt('report');
  if (pids.length && pids.every(ok)) out.parked = pids.map(pt);
  const m = mode === undefined ? EW.mode : mode, c = cols === undefined ? EW.arrCols : cols;
  if (m) { out.mode = m; if (c && m !== 'column') out.cols = c; }
  return out;
}
function editorState(d, keep) {
  const settings = clone(d.settings) || {};
  const layout = settings.layout || null;
  delete settings.layout;
  const parkedRaw = Array.isArray(settings.parked) ? settings.parked : [];   // steps taken out of the flow: they stay on the canvas and never run
  delete settings.parked;
  const parked = parkedRaw.filter(p => p && p.step && typeof p.step === 'object').map(p => ({ step: p.step, at: Number.isInteger(p.at) ? p.at : 0 }));
  const work = { name: d.name, description: d.description || '', steps: clone(d.steps), entity_schema: clone(d.entity_schema), gates: clone(d.gates), training_phrases: clone(d.training_phrases), slash_command: d.slash_command || '', kind: d.kind, settings, response_format: d.response_format || 'generic', parked };
  const ids = d.steps.map((_, i) => i), pids = parked.map((_, k) => ids.length + k), size = cvSize();
  const E = { id: d.id, d, work, orig: clone(work), ids, pids, nextId: ids.length + pids.length, undo: [], last: '', lastPush: 0, check: { errors: [], warnings: [] }, serverProblems: null, chat: (keep && keep.chat) || [],
    size, stash: {}, pos: layoutToPos(layout, ids, pids, size), mode: layoutMode(layout, ids, size), arrCols: (layoutFits(layout, ids, size) && layout.cols) || null, autoArr: false, layoutCap: !!S.boot.caps.workflow_kind, layoutSent: null, cv: null };
  if (!E.layoutCap) {                // an older database has no settings column: this browser remembers the layout instead
    try { const kept = JSON.parse(store.get('layout:' + ORG + ':' + d.id) || 'null'); E.pos = layoutToPos(kept, ids, pids, size); E.mode = layoutMode(kept, ids, size); E.arrCols = (layoutFits(kept, ids, size) && kept.cols) || null; } catch (e) { /* keep the automatic layout */ }
  }
  E.saw = Object.keys(E.pos).length > 0;           // a saved layout exists (for this size of box): open as it was left
  const sent = E.saw ? layoutOut(E.pos, ids, E.mode, E.arrCols, pids, size) : null;
  E.layoutSent = sent ? JSON.stringify(sent) : null;
  E.last = JSON.stringify({ work, ids, pids, pos: E.pos, mode: E.mode, cols: E.arrCols, size });
  return E;
}
const isDirty = () => !same(tidyWork(EW.work), tidyWork(EW.orig));
let checkTimer = null, ui = {};

const snapJSON = () => JSON.stringify({ work: EW.work, ids: EW.ids, pids: EW.pids, pos: EW.pos, mode: EW.mode, cols: EW.arrCols, size: EW.size });
// remember the state before a change, so Undo can come back to it (quick typing counts as one change)
function snapshot(force) {
  const now = snapJSON();
  if (now === EW.last) return false;
  const t = Date.now();
  if (force || !EW.undo.length || t - EW.lastPush > 1200) { EW.undo.push(EW.last); EW.lastPush = t; if (EW.undo.length > 60) EW.undo.shift(); }
  EW.last = now;
  return true;
}
function commit(redraw, force) {          // force: this change is an undo step of its own, even when it follows another quickly
  snapshot(!!force);
  EW.serverProblems = null;
  updateBar(); scheduleCheck();
  if (redraw) drawPane(); else refreshTitles();
  queueLayoutSave();
}
function commitLayout() { snapshot(true); updateBar(); queueLayoutSave(); }
function undo() {
  if (!EW.undo.length) { toast('Nothing to undo'); return; }
  const prev = JSON.parse(EW.undo.pop());
  EW.work = prev.work; EW.ids = prev.ids; EW.pids = prev.pids || [];
  if ((prev.size || EW.size) === EW.size) { EW.pos = prev.pos || {}; EW.mode = prev.mode || ''; EW.arrCols = prev.cols || null; }   // the places only come back if they were made for this size of box
  EW.arrIds = null; EW.last = snapJSON(); EW.serverProblems = null;
  document.querySelectorAll('.toast.has-act').forEach(t => t.remove());   // what they offered to undo is undone now
  drawPane(); updateBar(); scheduleCheck(); queueLayoutSave();
}
// the layout is saved quietly: no new version, no "Unsaved". While the steps themselves have unsaved
// changes the layout waits and goes along with the next Save.
let layoutTimer = null;
function queueLayoutSave() { clearTimeout(layoutTimer); const mine = EW; layoutTimer = setTimeout(() => { if (mine === EW) saveLayout(); }, 900); }
async function saveLayout() {
  const out = layoutOut();
  if (!out || isDirty()) return;
  const text = JSON.stringify(out);
  if (text === EW.layoutSent) return;
  if (!EW.layoutCap) { store.set('layout:' + ORG + ':' + EW.id, text); EW.layoutSent = text; return; }
  try { await api.put('/workflows/' + EW.id + '/layout', { layout: out }); EW.layoutSent = text; }
  catch (e) { /* a layout that did not save is not worth a message: the next move tries again */ }
}
function scheduleCheck() { clearTimeout(checkTimer); checkTimer = setTimeout(runCheck, 450); }
async function runCheck() {
  if (!EW || EW.d.workflow_type === 'read') return;
  const mine = EW;
  try {
    const r = await api.post('/studio/validate', { steps: tidySteps(EW.work.steps), entity_schema: EW.work.entity_schema, kind: EW.work.kind, intent_key: EW.d.intent_key });
    if (mine === EW) { EW.check = r; drawProblems(); }
  } catch (e) { /* the server will check again on save */ }
}
function problemsFor(n) {
  const re = new RegExp('^Step ' + n + '\\b');
  return [...EW.check.errors.filter(m => re.test(m)).map(m => ['bad', m]), ...EW.check.warnings.filter(m => re.test(m)).map(m => ['warn', m])];
}
// (drawProblems, updateBar and refreshTitles are part of the canvas screen)

async function save() {
  const changes = {}, now = tidyWork(EW.work), was = tidyWork(EW.orig);
  EDIT_KEYS.forEach(k => { if (!same(now[k], was[k])) changes[k] = now[k]; });
  const parkedChanged = !same(now.parked, was.parked);
  if (!Object.keys(changes).length && !parkedChanged) { toast('Nothing to save'); return; }
  const lay = EW.layoutCap ? layoutOut() : null;   // the boxes' places go along, so they follow the steps if these were re-ordered
  if (changes.settings || lay || parkedChanged) {   // the settings are saved as a whole: the layout and the parked steps always travel in them
    const s = { ...(changes.settings || now.settings || {}) }, oldLay = EW.d.settings && EW.d.settings.layout;
    if (lay || oldLay) s.layout = lay || oldLay;
    if (now.parked.length) s.parked = now.parked.map(p => ({ step: p.step, at: p.at })); else delete s.parked;
    changes.settings = s;
  }
  ui.save.disabled = true;
  try {
    const r = await api.put('/workflows/' + EW.id + '/definition', { base_version: EW.d.version, ...changes });
    toast('Saved as version ' + r.version + (r.warnings && r.warnings.length ? ' — ' + plural(r.warnings.length, 'note') + ' to look at' : ''), 'ok');
    await reloadEditor();
  } catch (e) {
    ui.save.disabled = false;
    if (e.status === 409) { modal({ title: 'Someone else saved this', body: h('p', null, e.message), actions: [{ label: 'Keep editing' }, { label: 'Reload their version', primary: true, run: async () => { await reloadEditor(); } }] }); return; }
    const detail = e.data && e.data.detail;
    if (detail && detail.problems) { EW.serverProblems = detail.problems; drawProblems(); }
    toast(detail && detail.problems ? 'Not saved: ' + plural(detail.problems.length, 'problem') + ' to fix' : e.message, 'bad');
  }
}
async function reloadEditor() {
  const d = await api.get('/workflows/' + EW.id);
  await ensureStudio();
  EW = editorState(d, EW);
  drawEditor(); scheduleCheck();
}
function discard() { if (!isDirty()) return; confirmBox('Throw away your unsaved changes?', { ok: 'Discard', danger: true }).then(ok => { if (ok) { EW.work = clone(EW.orig); EW.ids = EW.d.steps.map((_, i) => i); EW.pids = EW.work.parked.map((_, k) => EW.ids.length + k); EW.nextId = EW.ids.length + EW.pids.length; EW.undo = []; EW.last = snapJSON(); drawPane(); updateBar(); scheduleCheck(); } }); }

async function renderEditor(root, id) {
  const mine = S.renderId;
  const [d] = await Promise.all([api.get('/workflows/' + id), ensureStudio()]);
  if (mine !== S.renderId) return;
  EW = editorState(d, null);
  S.leaveGuard = () => !EW || !isDirty() || window.confirm('You have unsaved changes to this workflow. Leave without saving?');
  window.onbeforeunload = () => (EW && isDirty()) ? 'Unsaved changes' : undefined;
  ui = { root };
  drawEditor();
  scheduleCheck();
}

// ----- Plain words / Technical, the Code or AI tag, and Try it -----
const copyText = t => navigator.clipboard.writeText(t).then(() => toast('Copied', 'ok'), () => toast('Could not copy', 'bad'));
function stepTag(step) {
  const ai = isAiStep(step);
  const el = ai ? badge('AI', 'violet') : badge('Code', 'ok');
  el.title = ai ? 'The assistant (a language model) reads the typed price here.' : 'Exact rules and SQL. No AI.';
  return el;
}
function traceView(r) {
  const glyph = { ran: '✓', would: '✎', skipped: '↷', failed: '✕' };
  const tag = { ran: 'looked up', would: 'would do', skipped: 'skipped', failed: 'stopped here' };
  const lines = (r.trace || []).map(t => h('div', { class: 'tr ' + t.status, style: { marginLeft: (t.depth * 18) + 'px' } },
    h('span', { class: 'ic', title: tag[t.status] }, glyph[t.status] || '•'),
    h('div', null, h('div', null, t.text, ' ', h('span', { class: 'muted small' }, '· ' + (tag[t.status] || t.status))), t.detail ? h('div', { class: 'dt' }, t.detail) : null)));
  const end = r.status === 'preview' ? notice('It would go through' + (r.facts && r.facts.length ? ': ' + r.facts.join('. ') + '.' : '.'), 'ok')
    : r.status === 'error' || r.status === 'ambiguous' ? notice(r.message || 'It would stop here.', 'bad') : null;
  return h('div', { class: 'stack' }, end, h('div', { class: 'trace' }, lines.length ? lines : h('div', { class: 'muted' }, 'Nothing ran.')));
}

// ----- details and access -----
function detailsPane() {
  const d = EW.d, w = EW.work, kinds = !!S.boot.caps.workflow_kind;
  const roles = ST.roles || [];
  const checked = new Set(d.granted_roles);
  const boxes = roles.map(r => ({ r, cb: h('input', { type: 'checkbox', checked: checked.has(r.name) }) }));
  const accessMsg = h('span', { class: 'small muted' });
  const access = d.kind === 'block'
    ? h('div', { class: 'muted' }, 'A building block is only run by other workflows, so it is not given to roles. Give the workflow that runs it instead.')
    : h('div', { class: 'stack' }, h('div', { class: 'row' }, boxes.map(b => h('label', { class: 'row' }, b.cb, b.r.name))),
        h('div', { class: 'row' }, h('button', { class: 'btn sm primary', onclick: async () => { try { await api.put('/workflows/' + d.id + '/roles', { roles: boxes.filter(b => b.cb.checked).map(b => b.r.name) }); d.granted_roles = boxes.filter(b => b.cb.checked).map(b => b.r.name); accessMsg.textContent = 'Saved'; toast('Access saved', 'ok'); } catch (e) { toast(e.message, 'bad'); } } }, 'Save who can use it'), accessMsg));
  const desc = h('textarea', { rows: 3, oninput: e => { w.description = e.target.value; commit(false); } }); desc.value = w.description;
  const phrases = tagsEditor(w.training_phrases, [], l => { w.training_phrases = l; commit(false); });
  return h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'About it'), h('div', { class: 'card-b stack' },
      field('What it does', desc, 'One sentence. The assistant reads this to understand when to use it.'),
      kinds ? field('What kind is it?', sel([['workflow', 'A workflow people start'], ['case_action', 'A case action (button on a case)'], ['block', 'A building block']], w.kind, { onchange: e => { w.kind = e.target.value; commit(true); } }), 'A building block is only run by other workflows. A case action is a button on a case.') : null,
      w.kind === 'workflow' || !kinds ? field('Command', h('input', { type: 'text', value: w.slash_command, placeholder: 'e.g. assign (people type /assign)', oninput: e => { w.slash_command = e.target.value.trim().replace(/^\//, ''); commit(false); } })) : null,
      w.kind === 'workflow' || !kinds ? field('Things a person might type to start it', phrases, 'Press Enter after each one. Eight or more works best.') : null)),
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Who can use it'), h('div', { class: 'card-b' }, access)),
    d.kind !== 'block' && S.boot.caps.cases ? peopleOnCaseCard() : null,
    d.used_in.length ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Where it is used'), h('div', { class: 'card-b chips' }, d.used_in.map(u => h('a', { class: 'badge violet', href: '#/workflows?w=' + u.id }, u.name)))) : null);
}

// people on a case: a workflow can be opened to them for the cases they are on
function peopleOnCaseCard() {
  const cfg = EW.work.settings = EW.work.settings || {};
  const roles = [['requester', 'The person who raised the case'], ['assignee', 'The person who has the case'], ['level2', 'Level 2'], ['helper', 'Helpers, such as someone who passed it on'], ['watcher', 'Watchers']];
  const have = new Set(cfg.who_can_use || []);
  const save = () => { const l = roles.map(r => r[0]).filter(r => have.has(r)); if (l.length) cfg.who_can_use = l; else delete cfg.who_can_use; commit(false); };
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'People on a case'),
    h('div', { class: 'card-b stack' }, h('div', { class: 'muted' }, 'Tick who may use this on the cases they are on, even if their role does not allow it. They can only act on their own cases.'),
      roles.map(([k, label]) => h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: have.has(k), onchange: e => { e.target.checked ? have.add(k) : have.delete(k); save(); } }), label)),
      h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: !!cfg.photos, onchange: e => { if (e.target.checked) cfg.photos = true; else delete cfg.photos; commit(false); } }), 'Takes photos sent in the chat while it is being filled in')));
}

// ----- what it asks for (entity_schema) -----
function asksPane() {
  const sch = EW.work.entity_schema, keys = Object.keys(sch);
  const types = ST.catalog.field_types;
  const usedBy = k => EW.work.steps.some(s => JSON.stringify(s).includes('$fields.' + k + '"'));
  const wrap = h('div', { class: 'stack' });
  const rows = keys.map(k => {
    const f = sch[k] && typeof sch[k] === 'object' ? sch[k] : (sch[k] = {});
    const req = f.required_if ? 'cond' : (f.required ? 'yes' : 'no');
    const when = f.required_if || {};
    const condBox = h('div', { class: 'row small', style: { display: req === 'cond' ? '' : 'none' } }, 'when', sel([['', 'a field…'], ...keys.filter(x => x !== k).map(x => [x, pretty(x)])], when.field || '', { onchange: e => { f.required_if = { ...(f.required_if || {}), field: e.target.value }; commit(false); } }),
      sel([['equals', 'is'], ['in', 'is one of']], 'in' in when ? 'in' : 'equals', { onchange: e => { const val = f.required_if.equals ?? (f.required_if.in || []).join(','); delete f.required_if.equals; delete f.required_if.in; f.required_if[e.target.value] = e.target.value === 'in' ? String(val || '').split(',').map(x => x.trim()).filter(Boolean) : val; commit(false); } }),
      h('input', { type: 'text', value: 'in' in when ? (when.in || []).join(', ') : (when.equals ?? ''), placeholder: 'value', oninput: e => { f.required_if = f.required_if || {}; if ('in' in f.required_if) f.required_if.in = e.target.value.split(',').map(x => x.trim()).filter(Boolean); else f.required_if.equals = e.target.value; commit(false); } }));
    return h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
      h('div', { class: 'row between' }, h('b', null, pretty(k), ' ', h('span', { class: 'muted small' }, '(' + k + ')')),
        h('button', { class: 'btn sm danger', type: 'button', onclick: async () => { if (usedBy(k) && !await confirmBox('A step uses this field. Remove it anyway?', { ok: 'Remove', danger: true })) return; delete sch[k]; commit(true); } }, 'Remove')),
      field('Notes for the assistant', h('input', { type: 'text', value: f.description || '', oninput: e => { f.description = e.target.value; commit(false); } }), 'The assistant reads this to know what the field is and how to understand an answer.'),
      h('div', { class: 'two' },
        field('Question the bot asks', h('input', { type: 'text', value: f.question || '', placeholder: 'e.g. Which case? Send the case number.', oninput: e => { if (e.target.value) f.question = e.target.value; else delete f.question; commit(false); } }), 'Shown to the person when the bot asks for this itself. Empty: the notes are used.'),
        field('Short name in the confirmation', h('input', { type: 'text', value: f.label || '', placeholder: pretty(k), oninput: e => { if (e.target.value) f.label = e.target.value; else delete f.label; commit(false); } }))),
      readByEditor(f),
      h('div', { class: 'two' },
        field('Kind of answer', sel(types, f.type || 'string', { onchange: e => { f.type = e.target.value; commit(false); } })),
        field('Must it be given?', sel([['yes', 'Always'], ['no', 'Optional'], ['cond', 'Only in some cases']], req, { onchange: e => { if (e.target.value === 'cond') { delete f.required; f.required_if = f.required_if || { field: '', equals: '' }; } else { delete f.required_if; f.required = e.target.value === 'yes'; } commit(true); } }))),
      condBox,
      field('Allowed answers', tagsEditor(Array.isArray(f.enum) ? f.enum : [], [], l => { if (l.length) f.enum = l; else delete f.enum; commit(false); }), 'Leave empty to allow anything. Otherwise only these.')));
  });
  const addField = () => {
    const el = document.getElementById('newfield');
    const k = el.value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    if (!k) { toast('Type a name for the field first, for example comment_text', 'bad'); el.focus(); return; }
    if (sch[k]) { toast('There is already a field called ' + k, 'bad'); return; }
    sch[k] = { type: 'string', required: false, description: '' };
    commit(true);
  };
  const add = h('div', { class: 'row' },
    h('input', { type: 'text', placeholder: 'New field name, e.g. comment_text', id: 'newfield', onkeydown: e => { if (e.key === 'Enter') { e.preventDefault(); addField(); } } }),
    h('button', { class: 'btn', type: 'button', onclick: addField }, '+ Add a field'));
  wrap.append(h('div', { class: 'muted' }, 'What the assistant collects from the person before it runs the steps. Steps read these as the person’s answers.'), ...rows, add);
  if (!keys.length) wrap.prepend(h('div', { class: 'card' }, empty('Nothing is asked', 'This workflow does not collect anything from the person.')));
  return wrap;
}

// how an answer is read: code (a lookup, as typed, fixed answers) or the assistant
function readMode(f) {
  const rb = f.read_by;
  if (rb === 'typed' || rb === 'as_typed') return 'typed';
  if (rb && typeof rb === 'object' && rb.lookup) return 'lookup';
  if (rb === 'ai') return 'ai';
  if (Array.isArray(f.enum) && f.enum.length) return 'choice';
  return 'ai';
}
function readByEditor(f) {
  const mode = readMode(f);
  const byCode = mode !== 'ai';
  const pick = sel([['ai', 'The assistant works it out (AI)'], ['typed', 'Take the answer exactly as typed (code)'], ['lookup', 'Look it up in a table (code)'], ['choice', 'One of the allowed answers (code)']], mode, { onchange: e => {
    const v = e.target.value;
    if (v === 'ai') { if (Array.isArray(f.enum) && f.enum.length) f.read_by = 'ai'; else delete f.read_by; }
    else if (v === 'typed') f.read_by = 'typed';
    else if (v === 'lookup') f.read_by = { lookup: (f.read_by && f.read_by.lookup) || { table: '', match_column: '' } };
    else delete f.read_by;
    commit(true);
  } });
  const box = h('div', { class: 'stack' }, field('How the answer is read', pick, 'Code is exact and instant, and cannot misread. The assistant is only needed for free sentences. If code is not sure, it hands the message to the assistant.'));
  box.querySelector('label').append(' ', byCode ? badge('Code', 'ok') : badge('AI', 'violet'));
  if (mode === 'choice' && !(Array.isArray(f.enum) && f.enum.length)) box.append(notice('Add the allowed answers below, or choose another way.', 'warn'));
  if (mode === 'lookup') {
    const cfg = f.read_by.lookup, cols = colsOf(cfg.table);
    const showSet = new Set(cfg.show || []);
    box.append(h('div', { class: 'subcfg' },
      h('div', { class: 'two' },
        field('Look in', sel([['', 'Choose a table…'], ...Object.keys(ST.catalog.tables).map(t => [t, pretty(t)])], cfg.table || '', { onchange: e => { cfg.table = e.target.value; cfg.match_column = ''; delete cfg.show; delete cfg.where; commit(true); } })),
        field('Match against', sel([['', 'Choose a column…'], ...cols.map(c => [c, pretty(c)])], cfg.match_column || '', { onchange: e => { cfg.match_column = e.target.value; commit(false); } }))),
      h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: cfg.normalize === 'identifier', onchange: e => { if (e.target.checked) cfg.normalize = 'identifier'; else delete cfg.normalize; commit(false); } }), 'It is a reference number (ignore spaces, dashes and capitals)'),
      cols.includes('is_active') ? h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: !!(cfg.where && cfg.where.is_active), onchange: e => { if (e.target.checked) cfg.where = { ...(cfg.where || {}), is_active: true }; else { delete (cfg.where || {}).is_active; if (cfg.where && !Object.keys(cfg.where).length) delete cfg.where; } commit(false); } }), 'Only records that are still active') : null,
      field('Show these when it is found', h('div', { class: 'checks' }, cols.slice(0, 40).map(c => h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: showSet.has(c), onchange: e => { e.target.checked ? showSet.add(c) : showSet.delete(c); const l = cols.filter(x => showSet.has(x)); if (l.length) cfg.show = l; else delete cfg.show; commit(false); } }), pretty(c)))), 'These columns make up the line the person sees, such as the case number and its title.')));
  }
  return box;
}

// ----- safeguards (gates) -----
const gateText = g => g.type === 'permission' ? 'Only these roles: ' + (g.role_any_of || []).join(', ') : g.type === 'otp' ? 'Asks for a one-time code' + (g.when ? ' when ' + condText(g.when) : '') : g.type === 'approval_chain' ? 'Needs approval from ' + (g.levels || []).map(l => l.role).join(' then ') + (g.when ? ' when ' + condText(g.when) : '') : pretty(g.type);
function safePane() {
  const gates = EW.work.gates || [];
  const text = gateText;
  return h('div', { class: 'stack' }, h('div', { class: 'muted' }, 'Rules that stop or slow a workflow down: who may run it, one-time codes, approvals.'),
    gates.length ? h('div', { class: 'card' }, gates.map(g => h('div', { class: 'row between', style: { padding: '10px 16px', borderBottom: '1px solid var(--line)' } }, h('span', null, text(g)), badge(g.type)))) : h('div', { class: 'card' }, empty('No safeguards', 'Anyone allowed to use the workflow can run it all the way.')),
    h('div', { class: 'muted small' }, 'To change safeguards, edit them as JSON under “Advanced”.'));
}

// ----- history -----
function historyPane() {
  const d = EW.d;
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Earlier versions'),
    d.versions.length ? table([
      { label: 'Version', render: v => h('b', null, 'v' + v.version, v.version === d.version ? [' ', badge('current', 'ok')] : null) },
      { label: 'Saved', render: v => fmtDT(v.published_at) },
      { label: 'Steps', cls: 'num', render: v => v.step_count },
      { label: '', render: v => h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => viewVersion(v.version) }, 'See'),
          v.version === d.version ? null : h('button', { class: 'btn sm', onclick: async () => { if (isDirty() && !await confirmBox('You have unsaved changes. Restoring will replace them.', { ok: 'Restore anyway', danger: true })) return; if (!await confirmBox('Go back to version ' + v.version + '? It is saved as a new version, so nothing is lost.', { ok: 'Restore' })) return; try { const r = await api.post('/workflows/' + d.id + '/restore', { version: v.version, base_version: d.version }); toast('Restored as version ' + r.version, 'ok'); await reloadEditor(); } catch (e) { toast(e.message, 'bad'); } } }, 'Restore')) },
    ], d.versions) : empty('No earlier versions kept', 'Every save from now on is kept here.'));
}
async function viewVersion(n) {
  try {
    const v = await api.get('/workflows/' + EW.id + '/versions/' + n);
    modal({ title: 'Version ' + n + ' · ' + fmtDT(v.published_at), wide: true, body: v.steps.length ? h('ol', { style: { margin: 0, paddingLeft: '20px' } }, v.steps.map(s => h('li', { style: { margin: '4px 0' } }, describeStep(s), s.when ? h('span', { class: 'small', style: { color: 'var(--info)' } }, ' — only if ' + condText(s.when)) : null))) : empty('No steps in this version', ''), actions: [{ label: 'Close' }] });
  } catch (e) { toast(e.message, 'bad'); }
}

// ----- advanced: raw JSON for every part -----
function advancedPane() {
  const part = (key, label, hint) => {
    const ta = h('textarea', { rows: 10, style: { fontFamily: 'ui-monospace,monospace' } }); ta.value = JSON.stringify(EW.work[key], null, 2);
    const msg = h('span', { class: 'small', style: { color: 'var(--bad)' } });
    return h('div', { class: 'card' }, h('div', { class: 'card-h' }, label, h('span', { class: 'muted small' }, hint)), h('div', { class: 'card-b stack' }, ta,
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => { try { const v = JSON.parse(ta.value); EW.work[key] = v; msg.textContent = ''; commit(false); toast('Applied. Save to keep it.', 'ok'); } catch (e) { msg.textContent = 'That is not valid JSON: ' + e.message; } } }, 'Apply'), msg)));
  };
  return h('div', { class: 'stack' }, h('div', { class: 'muted' }, 'For anything the other tabs do not cover. Changes are checked before they can be saved.'),
    part('steps', 'Steps', 'a list'), part('entity_schema', 'What it asks for', 'an object'), part('gates', 'Safeguards', 'a list'),
    S.boot.caps.workflow_kind ? part('settings', 'Settings', 'an object') : null);
}

// ----- the chat beside the editor -----
// a proposal from the chat: steps that stay (same or changed) keep their id, so their boxes stay where they are
function proposalIds(p) {
  const out = []; let oi = 0;
  for (const x of p.diff || []) {
    if (x.type === 'same' || x.type === 'changed') out.push(EW.ids[oi++]);
    else if (x.type === 'removed') oi++;
    else out.push(EW.nextId++);
  }
  if (out.length === p.steps.length && out.every(v => v !== undefined)) return out;
  return p.steps.map(() => EW.nextId++);
}
function chatDock(read) {
  const log = h('div', { class: 'chatlog' });
  const input = h('textarea', { rows: 2, placeholder: read ? 'Chat edits steps, and this workflow has none.' : 'Tell the assistant what to change…', disabled: read });
  const send = h('button', { class: 'btn primary', disabled: read }, 'Send');
  function proposalView(msg) {
    const p = msg.proposal;
    const changed = p.diff.filter(x => x.type !== 'same');
    const lines = changed.flatMap(x => x.type === 'added' ? [['add', '＋ ' + describeStep(x.new)]] : x.type === 'removed' ? [['del', '− ' + describeStep(x.old)]] : [['del', '− ' + describeStep(x.old)], ['add', '＋ ' + describeStep(x.new)]]);
    return h('div', { class: 'proposal' },
      h('div', { class: 'diff' }, lines.length ? lines.map(([k, t]) => h('div', { class: 'dl ' + k }, t)) : h('div', { class: 'dl' }, 'Only the order or small details changed.')),
      p.diff.filter(x => x.type === 'same').length ? h('div', { class: 'muted small', style: { margin: '4px 0' } }, plural(p.diff.filter(x => x.type === 'same').length, 'other step') + ' stay as they are.') : null,
      p.warnings && p.warnings.length ? h('div', { class: 'prob warn' }, p.warnings.join(' ')) : null,
      msg.status ? h('div', { class: 'small muted' }, msg.status === 'applied' ? 'Applied. Save when you are happy with it.' : 'Discarded.') :
        h('div', { class: 'row' }, h('button', { class: 'btn sm primary', onclick: () => { EW.work.steps = clone(p.steps); EW.ids = proposalIds(p); msg.status = 'applied'; commit(true); draw(); } }, 'Apply'),
          h('button', { class: 'btn sm', onclick: () => { msg.status = 'discarded'; draw(); } }, 'Discard')));
  }
  function draw() {
    fill(log, EW.chat.length ? EW.chat.map(m => h('div', { class: 'bubble ' + m.role }, m.text, m.proposal ? proposalView(m) : null)) : h('div', { class: 'muted small', style: { padding: '8px' } }, read ? '' : 'Try: “When a case is closed, also message the person who raised it.” or “Add a note step after assigning.”'));
    log.scrollTop = log.scrollHeight;
  }
  async function submit() {
    const text = input.value.trim();
    if (!text || send.disabled) return;
    EW.chat.push({ role: 'user', text }); input.value = ''; send.disabled = true; send.textContent = '…';
    const wait = { role: 'assistant', text: 'Thinking…' }; EW.chat.push(wait); draw();
    try {
      const hist = EW.chat.filter(m => m !== wait).slice(-7, -1).map(m => ({ role: m.role, content: m.text }));
      const r = await api.post('/studio/chat', { workflow_id: EW.id, message: text, history: hist, working: { name: EW.work.name, description: EW.work.description, steps: tidySteps(EW.work.steps), entity_schema: EW.work.entity_schema } });
      wait.text = r.reply || 'Done.'; if (r.proposal) wait.proposal = r.proposal;
      if (!r.proposal && r.problems && r.problems.length) wait.text += ' (' + r.problems.slice(0, 2).join(' ') + ')';
    } catch (e) { wait.text = e.message; wait.role = 'assistant error'; }
    send.disabled = false; send.textContent = 'Send'; draw();
  }
  send.addEventListener('click', submit);
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
  draw();
  return h('aside', { class: 'chatdock' }, h('div', { class: 'card-h' }, 'Change it by chatting'), log, h('div', { class: 'chatin' }, input, send));
}

SECTIONS.workflows = {
  title: 'Flows', sub: 'What people can ask the assistant to do, and how each one works',
  async render(root, route) {
    S.leaveGuard = null; window.onbeforeunload = null; EW = null;
    if (route.q.w) return renderEditor(root, route.q.w);
    return renderFlows(root, route);
  },
};
"""
