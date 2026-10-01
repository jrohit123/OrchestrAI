JS = r"""
// ───────────────────────── Workflows: the list ─────────────────────────
const KIND_GROUPS = [
  ['workflow', 'Things people start', 'Started from the Telegram menu, or by typing.'],
  ['case_action', 'Case actions', 'Buttons on a case, such as Pass to someone.'],
  ['block', 'Building blocks', 'Small steps that other workflows run, such as Find a case. Change one and every workflow that runs it changes.'],
];
async function ensureStudio() {
  const [cat, fl] = await Promise.all([api.get('/studio/catalog'), api.get('/workflows')]);
  ST.catalog = cat; ST.flows = fl.rows; ST.roles = fl.roles;
  ST.byKey = Object.fromEntries(fl.rows.map(w => [w.intent_key, w]));
}
const classicUrl = () => '/admin/' + encodeURIComponent(ORG) + '/legacy';
function openWorkflow(id) { go('workflows', '', { w: id }); }

async function renderWorkflowList(root) {
  const mine = S.renderId;
  await ensureStudio();
  if (mine !== S.renderId) return;
  const kinds = !!S.boot.caps.workflow_kind;
  let text = '';
  const body = h('div', { class: 'stack' });
  const search = h('input', { type: 'search', placeholder: 'Search workflows…', style: { minWidth: '240px' } });
  search.addEventListener('input', debounce(() => { text = search.value.trim().toLowerCase(); draw(); }, 200));
  const again = async () => { await ensureStudio(); draw(); };
  function listTable(rows) {
    return table([
      { label: 'On', render: w => switchEl(w.is_active, async v => { await api.post('/workflows/' + w.id + '/active', { is_active: v }); w.is_active = v; }) },
      { label: 'Name', cls: 'wide', render: w => h('div', null, h('a', { href: '#/workflows?w=' + w.id, onclick: e => e.stopPropagation() }, h('b', null, w.name)), h('div', { class: 'muted small' }, w.description || w.intent_key), w.slash_command ? h('div', { class: 'muted small' }, '/' + w.slash_command) : null) },
      { label: 'Who can use it / where it is used', render: w => w.kind === 'block'
          ? (w.used_in.length ? h('div', { class: 'chips' }, w.used_in.map(u => badge(u.name, 'violet'))) : h('span', { class: 'muted' }, 'Not used yet'))
          : (w.granted_roles.length ? h('div', { class: 'chips' }, w.granted_roles.map(r => badge(r, 'brand'))) : h('span', { class: 'muted' }, 'Nobody')) },
      { label: 'Steps', cls: 'num', render: w => w.workflow_type === 'read' ? h('span', { class: 'muted' }, 'report') : h('div', null, plural(w.step_count, 'step'), w.uses.length ? h('div', { class: 'muted small' }, 'uses ' + plural(w.uses.length, 'block')) : null) },
      { label: 'Last used', render: w => w.last_run ? ago(w.last_run) : h('span', { class: 'muted' }, 'never') },
      { label: '', render: w => h('div', { class: 'row' }, h('button', { class: 'btn sm primary', onclick: () => openWorkflow(w.id) }, 'Open'),
          h('button', { class: 'btn sm danger', onclick: async () => { if (w.is_active) { toast('Switch “' + w.name + '” off first. Then you can delete it. You can always switch it back on.', 'bad'); return; } if (!await confirmBox('Delete “' + w.name + '”? It is switched off already. Deleting takes it out of this list for good. A copy is kept in the history.', { ok: 'Delete', danger: true })) return; try { await api.del('/workflows/' + w.id); toast('Deleted', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } } }, 'Delete')) },
    ], rows, { onRow: w => openWorkflow(w.id) });
  }
  function draw() {
    const match = w => !text || (w.name + ' ' + (w.description || '') + ' ' + w.intent_key).toLowerCase().includes(text);
    const rows = ST.flows.filter(match);
    if (!kinds) { fill(body, h('div', { class: 'card' }, rows.length ? listTable(rows) : empty('No workflows match', ''))); return; }
    fill(body, KIND_GROUPS.map(([k, label, hint]) => {
      const g = rows.filter(w => (w.kind || 'workflow') === k);
      return h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('span', null, label, ' ', h('span', { class: 'muted small' }, g.length)), h('span', { class: 'muted small' }, hint)),
        g.length ? listTable(g) : empty(text ? 'None match' : 'None yet', k === 'block' ? 'Create one with “New workflow”, or ask the chat for it.' : ''));
    }));
  }
  fill(root, h('div', { class: 'row between', style: { marginBottom: '12px' } }, search,
    h('span', { class: 'row' }, h('a', { class: 'btn sm ghost', href: classicUrl(), target: '_blank', rel: 'noopener', title: 'Reports and PDF documents are still built in the classic builder' }, 'Classic builder for reports ↗'),
      h('button', { class: 'btn primary', onclick: () => newWorkflowModal(kinds) }, '+ New workflow'))), body);
  draw();
}

// ----- create: describe it in chat, start blank, or copy one -----
function newWorkflowModal(kinds) {
  let mode = 'chat', proposal = null, history = [];
  const kindOpts = kinds ? [['workflow', 'A workflow people start'], ['case_action', 'A case action (button on a case)'], ['block', 'A building block']] : null;
  const body = h('div', { class: 'stack' }), seg = h('div', { class: 'row' });
  const m = modal({ title: 'New workflow', wide: true, body: h('div', null, seg, h('div', { style: { height: '12px' } }), body), actions: null });
  const modeBtn = (k, label) => h('button', { class: 'btn sm' + (mode === k ? ' primary' : ''), type: 'button', onclick: () => { mode = k; proposal = null; draw(); } }, label);
  async function created(r) { toast('Created', 'ok'); m.close(); await ensureStudio(); openWorkflow(r.id); }
  function draw() {
    fill(seg, modeBtn('chat', 'Describe it in chat'), modeBtn('blank', 'Start blank'), modeBtn('copy', 'Copy an existing one'));
    const err = h('div', { class: 'small', style: { color: 'var(--bad)' } });
    if (mode === 'chat') {
      const text = h('textarea', { rows: 4, placeholder: 'For example: A building block that adds a note to a case. It needs the case number and the note text.' });
      const kind = kindOpts ? sel(kindOpts, 'workflow') : null;
      const go_ = h('button', { class: 'btn primary', type: 'button' }, proposal ? 'Draft it again' : 'Draft it');
      go_.addEventListener('click', async () => {
        if (text.value.trim().length < 5) { err.textContent = 'Say what it should do.'; return; }
        go_.disabled = true; err.textContent = ''; go_.textContent = 'Drafting…';
        try {
          const r = await api.post('/studio/chat', { message: text.value.trim(), kind: kind ? kind.value : 'workflow', history });
          history = [{ role: 'user', content: text.value.trim() }, { role: 'assistant', content: r.reply }];
          proposal = r.proposal; draw();
          if (!r.proposal) body.prepend(notice((r.reply || '') + (r.problems && r.problems.length ? ' (' + r.problems.slice(0, 2).join(' ') + ')' : ''), 'warn'));
          else body.querySelector('textarea').value = text.value;
        } catch (e) { err.textContent = e.message; go_.disabled = false; go_.textContent = 'Draft it'; }
      });
      fill(body, field('What should it do?', text), kind ? field('What kind is it?', kind) : null, h('div', { class: 'row' }, go_, err),
        proposal ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Drafted: ' + proposal.name, badge(pretty(proposal.kind), 'violet')),
          h('div', { class: 'card-b stack' }, proposal.description ? h('div', null, proposal.description) : null,
            Object.keys(proposal.entity_schema).length ? h('div', null, h('b', null, 'Asks for: '), Object.keys(proposal.entity_schema).map(k => pretty(k)).join(', ')) : null,
            h('ol', { style: { margin: 0, paddingLeft: '20px' } }, proposal.steps.map(s => h('li', null, describeStep(s)))),
            proposal.warnings.length ? notice(proposal.warnings.join(' '), 'warn') : null,
            h('div', null, h('button', { class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { await created(await api.post('/workflows', { name: proposal.name, kind: proposal.kind, description: proposal.description, entity_schema: proposal.entity_schema, training_phrases: proposal.training_phrases, steps: proposal.steps })); } catch (x) { toast(x.message, 'bad'); e.target.disabled = false; } } }, 'Create it and open the editor')))) : null);
    } else if (mode === 'blank') {
      const name = h('input', { type: 'text', placeholder: 'e.g. Add a note to a case' });
      const kind = kindOpts ? sel(kindOpts, 'workflow') : null;
      fill(body, field('Name', name), kind ? field('What kind is it?', kind) : null, h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => { if (name.value.trim().length < 2) { err.textContent = 'Give it a name.'; return; } try { await created(await api.post('/workflows', { name: name.value.trim(), kind: kind ? kind.value : 'workflow' })); } catch (x) { err.textContent = x.message; } } }, 'Create'), err));
    } else {
      const src = sel([['', 'Choose one…'], ...ST.flows.filter(w => w.workflow_type !== 'read').map(w => [w.id, w.name])], '');
      const name = h('input', { type: 'text', placeholder: 'Name of the copy' });
      src.addEventListener('change', () => { const w = ST.flows.find(x => x.id === src.value); if (w && !name.value) name.value = w.name + ' (copy)'; });
      const kind = kindOpts ? sel(kindOpts, 'workflow') : null;
      fill(body, field('Copy which one?', src), field('Name of the copy', name), kind ? field('What kind is it?', kind) : null, h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => { if (!src.value) { err.textContent = 'Choose one to copy.'; return; } try { await created(await api.post('/workflows', { name: name.value.trim() || 'Copy', copy_from: src.value, kind: kind ? kind.value : 'workflow' })); } catch (x) { err.textContent = x.message; } } }, 'Copy it'), err),
        h('div', { class: 'muted small' }, 'Reports and PDF documents cannot be copied here. The copy is switched off and nobody can use it until you turn it on.'));
    }
  }
  draw();
}

// ───────────────────────── Workflows: the editor ─────────────────────────
const EDIT_KEYS = ['name', 'description', 'steps', 'entity_schema', 'gates', 'training_phrases', 'slash_command', 'kind', 'settings'];
function editorState(d, keep) {
  const work = { name: d.name, description: d.description || '', steps: clone(d.steps), entity_schema: clone(d.entity_schema), gates: clone(d.gates), training_phrases: clone(d.training_phrases), slash_command: d.slash_command || '', kind: d.kind, settings: clone(d.settings) };
  const ids = d.steps.map((_, i) => i);
  return { id: d.id, d, work, orig: clone(work), ids, nextId: ids.length, open: new Set(), undo: [], last: JSON.stringify({ work, ids }), lastPush: 0,
    tab: (keep && keep.tab) || 'steps', check: { errors: [], warnings: [] }, serverProblems: null, chat: (keep && keep.chat) || [], flash: -1 };
}
const isDirty = () => !same(tidyWork(EW.work), tidyWork(EW.orig));
const showTab = t => { EW.tab = t; drawEditor(); };
let checkTimer = null, ui = {};

function commit(redraw) {
  const now = JSON.stringify({ work: EW.work, ids: EW.ids });
  if (now !== EW.last) {
    const t = Date.now();
    if (!EW.undo.length || t - EW.lastPush > 1200) { EW.undo.push(EW.last); EW.lastPush = t; if (EW.undo.length > 60) EW.undo.shift(); }
    EW.last = now;
  }
  EW.serverProblems = null;
  updateBar(); scheduleCheck();
  if (redraw) drawPane(); else refreshTitles();
}
function undo() {
  if (!EW.undo.length) { toast('Nothing to undo'); return; }
  const prev = JSON.parse(EW.undo.pop());
  EW.work = prev.work; EW.ids = prev.ids; EW.last = JSON.stringify(prev); EW.serverProblems = null;
  drawEditor(); scheduleCheck();
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
function drawProblems() {
  if (ui.banner) {
    const all = EW.serverProblems ? EW.serverProblems : EW.check.errors;
    fill(ui.banner, all.length ? notice([h('b', null, EW.serverProblems ? 'These need fixing before it can be saved:' : plural(all.length, 'problem') + ' to fix before it can be saved:'), h('ul', { style: { margin: '4px 0 0', paddingLeft: '18px' } }, all.slice(0, 6).map(m => h('li', null, m)))], 'bad') : null);
  }
  (ui.probEls || []).forEach((el, i) => { if (el) fill(el, problemsFor(i + 1).map(([t, m]) => h('div', { class: 'prob ' + t }, m.replace(/^Step \d+( \([^)]*\))?:? ?/, '')))); });
}
function updateBar() {
  const dirty = isDirty();
  if (ui.save) { ui.save.disabled = !dirty; ui.save.textContent = dirty ? 'Save changes' : 'Saved'; }
  if (ui.discard) ui.discard.style.display = dirty ? '' : 'none';
  if (ui.undo) ui.undo.disabled = !EW.undo.length;
  if (ui.dirty) ui.dirty.style.display = dirty ? '' : 'none';
}
function refreshTitles() {
  (ui.titleEls || []).forEach((el, i) => { if (el && EW.work.steps[i]) el.textContent = describeStep(EW.work.steps[i]); });
  (ui.whenEls || []).forEach((el, i) => { if (el && EW.work.steps[i]) { const c = EW.work.steps[i].when; el.textContent = c ? 'only if ' + condText(c) : ''; el.style.display = c ? '' : 'none'; } });
}

async function save() {
  const changes = {}, now = tidyWork(EW.work), was = tidyWork(EW.orig);
  EDIT_KEYS.forEach(k => { if (!same(now[k], was[k])) changes[k] = now[k]; });
  if (!Object.keys(changes).length) { toast('Nothing to save'); return; }
  ui.save.disabled = true;
  try {
    const r = await api.put('/workflows/' + EW.id + '/definition', { base_version: EW.d.version, ...changes });
    toast('Saved as version ' + r.version + (r.warnings && r.warnings.length ? ' — ' + plural(r.warnings.length, 'note') + ' to look at' : ''), 'ok');
    await reloadEditor();
  } catch (e) {
    ui.save.disabled = false;
    if (e.status === 409) { modal({ title: 'Someone else saved this', body: h('p', null, e.message), actions: [{ label: 'Keep editing' }, { label: 'Reload their version', primary: true, run: async () => { await reloadEditor(); } }] }); return; }
    const detail = e.data && e.data.detail;
    if (detail && detail.problems) { EW.serverProblems = detail.problems; drawProblems(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
    toast(detail && detail.problems ? 'Not saved: ' + plural(detail.problems.length, 'problem') + ' to fix' : e.message, 'bad');
  }
}
async function reloadEditor() {
  const d = await api.get('/workflows/' + EW.id);
  await ensureStudio();
  EW = editorState(d, EW);
  drawEditor(); scheduleCheck();
}
function discard() { if (!isDirty()) return; confirmBox('Throw away your unsaved changes?', { ok: 'Discard', danger: true }).then(ok => { if (ok) { EW.work = clone(EW.orig); EW.ids = EW.d.steps.map((_, i) => i); EW.nextId = EW.ids.length; EW.undo = []; EW.last = JSON.stringify({ work: EW.work, ids: EW.ids }); EW.open = new Set(); drawEditor(); scheduleCheck(); } }); }

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

function drawEditor() {
  const root = ui.root, d = EW.d, read = d.workflow_type === 'read';
  const name = h('input', { type: 'text', value: EW.work.name, class: 'namebox', 'aria-label': 'Workflow name', oninput: e => { EW.work.name = e.target.value; commit(false); } });
  ui.save = h('button', { class: 'btn primary', onclick: save }, 'Saved');
  ui.discard = h('button', { class: 'btn', onclick: discard }, 'Discard');
  ui.undo = h('button', { class: 'btn', onclick: undo, title: 'Undo the last change' }, '↶ Undo');
  ui.dirty = h('span', { class: 'badge warn' }, 'Unsaved changes');
  ui.banner = h('div');
  const tabs = [['steps', 'Steps'], ['details', 'Details and access'], ['asks', 'What it asks for'], ['safe', 'Safeguards'], ['history', 'History'], ['adv', 'Advanced']];
  ui.pane = h('div');
  const power = h('span', null, d.is_active ? 'Switched on' : 'Switched off');
  fill(root,
    h('div', { class: 'studio-head' },
      h('a', { class: 'btn sm ghost', href: '#/workflows', onclick: e => { if (isDirty() && !window.confirm('You have unsaved changes. Leave without saving?')) e.preventDefault(); } }, '← All workflows'),
      name, badge(pretty(EW.work.kind || 'workflow'), 'violet'), badge('Version ' + d.version), ui.dirty, h('span', { class: 'sp' }),
      h('label', { class: 'row small' }, power, switchEl(d.is_active, async v => { await api.post('/workflows/' + d.id + '/active', { is_active: v }); d.is_active = v; power.textContent = v ? 'Switched on' : 'Switched off'; })),
      ui.undo, ui.discard, ui.save),
    ui.banner,
    h('div', { class: 'studio-grid' },
      h('div', { class: 'stack', style: { minWidth: 0 } },
        h('div', { class: 'tabs', style: { marginBottom: 0 } }, tabs.map(([k, l]) => h('button', { class: 'tab' + (EW.tab === k ? ' active' : ''), onclick: () => showTab(k) }, l))),
        ui.pane),
      chatDock(read)));
  drawPane(); updateBar(); drawProblems();
}
function drawPane() {
  const t = EW.tab;
  fill(ui.pane);
  if (t === 'steps') ui.pane.append(stepsPane());
  else if (t === 'details') ui.pane.append(detailsPane());
  else if (t === 'asks') ui.pane.append(asksPane());
  else if (t === 'safe') ui.pane.append(safePane());
  else if (t === 'history') ui.pane.append(historyPane());
  else ui.pane.append(advancedPane());
  drawProblems();
}

// ----- steps -----
function stepsPane() {
  const d = EW.d;
  if (d.workflow_type === 'read') {
    return h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'This workflow answers with a report'),
      h('div', { class: 'card-b stack' }, h('div', null, 'It looks things up with a saved query instead of steps, so there is nothing to edit step by step.'),
        h('pre', { class: 'code' }, d.sql_template || ''), h('a', { class: 'btn sm', href: classicUrl(), target: '_blank', rel: 'noopener' }, 'Change the report in the classic builder ↗')));
  }
  const wrap = h('div', { class: 'stack' });
  ui.titleEls = []; ui.whenEls = []; ui.probEls = [];
  const list = h('div', { class: 'steps' });
  if (d.used_in.length) wrap.append(notice('This is a building block. It is run by: ' + d.used_in.map(u => u.name).join(', ') + '. Changes here change all of them.'));
  if (d.uses.length) wrap.append(h('div', { class: 'row small muted' }, 'Runs: ', h('span', { class: 'chips' }, d.uses.map(u => badge(u.name, 'violet')))));
  if (!EW.work.steps.length) list.append(h('div', { class: 'card' }, empty('No steps yet', 'Add one below, or describe it to the chat and it will build it.')));
  EW.work.steps.forEach((step, i) => { list.append(insertPoint(i), stepCard(i)); });
  list.append(insertPoint(EW.work.steps.length, true));
  wrap.append(list);
  return wrap;
}
function insertPoint(at, last) {
  return h('div', { class: 'addpt' }, h('button', { class: 'btn sm' + (last ? '' : ' ghost'), type: 'button', onclick: () => addStepModal(at) }, last ? '+ Add a step' : '+'));
}
function addStepModal(at) {
  const groups = GROUP_ORDER.map(g => [g, (ST.catalog.steps || []).filter(s => s.group === g)]).filter(g => g[1].length);
  const m = modal({ title: 'Add a step', wide: true, body: h('div', { class: 'stack' }, groups.map(([g, items]) => h('div', null, h('div', { class: 'muted small', style: { marginBottom: '4px' } }, g),
    h('div', { class: 'addgrid' }, items.map(s => h('button', { class: 'addtile', type: 'button', onclick: () => { m.close(); addStep(at, s.op); } }, h('b', null, (STEP_GLYPH[s.op] || '•') + ' ' + s.label), h('span', { class: 'muted small' }, s.help))))))), actions: [{ label: 'Cancel' }] });
}
function addStep(at, op) {
  const spec = catalogSpec(op), step = { op, params: {} };
  (spec ? spec.params : []).forEach(p => { if (p.default !== undefined && p.kind !== 'column') step.params[p.key] = p.default; });
  EW.work.steps.splice(at, 0, step); EW.ids.splice(at, 0, EW.nextId);
  EW.open.add(EW.nextId); EW.flash = EW.nextId; EW.nextId++;
  commit(true);
  setTimeout(() => { const el = document.querySelector('.stcard.flash'); if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, 50);
}
function moveStep(i, dir) {
  const j = i + dir;
  if (j < 0 || j >= EW.work.steps.length) return;
  [EW.work.steps[i], EW.work.steps[j]] = [EW.work.steps[j], EW.work.steps[i]];
  [EW.ids[i], EW.ids[j]] = [EW.ids[j], EW.ids[i]];
  commit(true);
}
function dupStep(i) { EW.work.steps.splice(i + 1, 0, clone(EW.work.steps[i])); EW.ids.splice(i + 1, 0, EW.nextId++); commit(true); }
function delStep(i) {
  const s = EW.work.steps[i];
  confirmBox('Remove this step? “' + describeStep(s) + '”', { ok: 'Remove', danger: true }).then(ok => { if (!ok) return; EW.work.steps.splice(i, 1); EW.ids.splice(i, 1); commit(true); });
}
function stepCard(i) {
  const step = EW.work.steps[i], id = EW.ids[i], open = EW.open.has(id), spec = catalogSpec(step.op);
  const title = h('div', { class: 'st-title' }, describeStep(step));
  const when = h('div', { class: 'small', style: { color: 'var(--info)', display: step.when ? '' : 'none' } }, step.when ? 'only if ' + condText(step.when) : '');
  const probs = h('div');
  ui.titleEls[i] = title; ui.whenEls[i] = when; ui.probEls[i] = probs;
  const btn = (label, tip, fn) => h('button', { class: 'ib', type: 'button', title: tip, 'aria-label': tip, onclick: e => { e.stopPropagation(); fn(); } }, label);
  const card = h('div', { class: 'stcard' + (open ? ' open' : '') + (EW.flash === id ? ' flash' : '') },
    h('div', { class: 'st-head', onclick: () => { open ? EW.open.delete(id) : EW.open.add(id); EW.flash = -1; drawPane(); } },
      h('span', { class: 'num' }, i + 1), h('span', { class: 'glyph' }, STEP_GLYPH[step.op] || '•'),
      h('div', { style: { minWidth: 0, flex: 1 } }, title, when, h('div', { class: 'muted small' }, spec ? spec.label : step.op)),
      h('span', { class: 'row', style: { gap: '2px' } }, btn('↑', 'Move up', () => moveStep(i, -1)), btn('↓', 'Move down', () => moveStep(i, 1)), btn('⧉', 'Duplicate this step', () => dupStep(i)), btn('✕', 'Remove this step', () => delStep(i)))),
    probs,
    open ? stepForm(step, i, commit, drawPane) : null);
  return card;
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
    d.used_in.length ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Where it is used'), h('div', { class: 'card-b chips' }, d.used_in.map(u => h('a', { class: 'badge violet', href: '#/workflows?w=' + u.id }, u.name)))) : null);
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
      field('How to ask for it', h('input', { type: 'text', value: f.description || '', oninput: e => { f.description = e.target.value; commit(false); } }), 'The assistant reads this to know what to ask and how to understand the answer.'),
      h('div', { class: 'two' },
        field('Kind of answer', sel(types, f.type || 'string', { onchange: e => { f.type = e.target.value; commit(false); } })),
        field('Must it be given?', sel([['yes', 'Always'], ['no', 'Optional'], ['cond', 'Only in some cases']], req, { onchange: e => { if (e.target.value === 'cond') { delete f.required; f.required_if = f.required_if || { field: '', equals: '' }; } else { delete f.required_if; f.required = e.target.value === 'yes'; } commit(true); } }))),
      condBox,
      field('Allowed answers', tagsEditor(Array.isArray(f.enum) ? f.enum : (f.enum = []), [], l => { if (l.length) f.enum = l; else delete f.enum; commit(false); }), 'Leave empty to allow anything. Otherwise only these.')));
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

// ----- safeguards (gates) -----
function safePane() {
  const gates = EW.work.gates || [];
  const text = g => g.type === 'permission' ? 'Only these roles: ' + (g.role_any_of || []).join(', ') : g.type === 'otp' ? 'Asks for a one-time code' + (g.when ? ' when ' + condText(g.when) : '') : g.type === 'approval_chain' ? 'Needs approval from ' + (g.levels || []).map(l => l.role).join(' then ') + (g.when ? ' when ' + condText(g.when) : '') : pretty(g.type);
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
        h('div', { class: 'row' }, h('button', { class: 'btn sm primary', onclick: () => { EW.work.steps = clone(p.steps); EW.ids = p.steps.map(() => EW.nextId++); EW.open = new Set(); msg.status = 'applied'; commit(true); draw(); } }, 'Apply'),
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
  title: 'Workflows', sub: 'What people can ask the assistant to do, and how each one works',
  async render(root, route) {
    S.leaveGuard = null; window.onbeforeunload = null; EW = null;
    if (route.q.w) return renderEditor(root, route.q.w);
    return renderWorkflowList(root);
  },
};
"""
