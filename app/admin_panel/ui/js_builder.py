JS = r"""
// ───────────────────────── Workflows: the plain-words builder ─────────────────────────
// The default view of a flow or building block: boxes in a list, + between them, If boxes with a
// ✓ YES and an ✗ OTHERWISE lane, and on the right the settings of the chosen box next to the data
// that is known there. It edits the same steps as the canvas ("Map view") and saves the same way
// (PUT …/definition): the boxes are only another way of showing EW.work.steps.
// Steps that share an "only if" are shown as one If box; see app/services/builder_model.py, which
// does the same translation (tests check that every live flow comes back unchanged).

const blOn = () => !!EW && (store.get('panel.editorview') || 'builder') !== 'map';
function drawEditor() { if (blOn()) blDrawEditor(); else { CV = null; cvDrawEditor(); } }
function drawPane() { if (blOn()) blDrawPane(); else cvDrawPane(); }
function refreshTitles() { if (blOn()) { blDrawList(); blQueueData(); } else cvRefreshTitles(); }
function drawProblems() { if (blOn()) blDrawProblems(); else cvDrawProblems(); }
function setEditorView(v) { store.set('panel.editorview', v); drawEditor(); }

// ----- the translation (the same rules as builder_model.py) -----
const BL_OPP = { equals: 'not_equals', not_equals: 'equals', in: 'not_in', not_in: 'in', gte: 'lt', lt: 'gte', lte: 'gt', gt: 'lte' };
const blCanon = v => JSON.stringify(v === undefined ? null : v, (k, x) => x && typeof x === 'object' && !Array.isArray(x) ? Object.keys(x).sort().reduce((o, key) => { o[key] = x[key]; return o; }, {}) : x);
const blSame = (a, b) => blCanon(a) === blCanon(b);
const isObj = x => !!x && typeof x === 'object' && !Array.isArray(x);
function blOpposite(c) {
  if (isObj(c) && Object.keys(c).length === 1 && 'not' in c) return c.not;
  if (isObj(c) && 'field' in c && Object.keys(c).length === 2) {
    const op = Object.keys(c).find(k => k !== 'field');
    if (op === 'exists') return { field: c.field, exists: !c.exists };
    if (BL_OPP[op]) return { field: c.field, [BL_OPP[op]]: c[op] };
  }
  return { not: c };
}
const blIsOpp = (a, b) => blSame(blOpposite(a), b) || blSame(blOpposite(b), a);
function blSplit(w) {
  if (isObj(w) && Array.isArray(w.and) && Object.keys(w).length === 1 && w.and.length >= 2) return [w.and[0], w.and.length === 2 ? w.and[1] : { and: w.and.slice(1) }];
  return [w, null];
}
function blJoin(outer, inner) {
  if (!inner || (isObj(inner) && !Object.keys(inner).length)) return outer;
  if (isObj(inner) && Array.isArray(inner.and) && Object.keys(inner).length === 1) return { and: [outer, ...inner.and] };
  return { and: [outer, inner] };
}
const blHasWhen = s => isObj(s) && isObj(s.when) && Object.keys(s.when).length > 0;
const blHeadOf = (s, whole) => blHasWhen(s) ? (whole ? s.when : blSplit(s.when)[0]) : null;
function blWithout(s, whole) { const c = clone(s), w = c.when; delete c.when; if (!whole) { const rest = blSplit(w)[1]; if (rest) c.when = rest; } return c; }
function blWholeHead(steps, i) {
  const whole = steps[i].when; let j = i;
  while (j < steps.length && isObj(steps[j]) && blSame(steps[j].when, whole)) j++;
  return j < steps.length && blHasWhen(steps[j]) && blIsOpp(whole, steps[j].when) ? whole : null;
}
function blIfBox(steps, i, head, whole) {
  let yes = i; while (yes < steps.length && blSame(blHeadOf(steps[yes], whole), head)) yes++;
  let noHead = null, no = yes;
  const nxt = yes < steps.length ? blHeadOf(steps[yes], whole) : null;
  if (nxt !== null && blIsOpp(head, nxt)) { noHead = nxt; while (no < steps.length && blSame(blHeadOf(steps[no], whole), noHead)) no++; }
  const box = { kind: 'if', rule: clone(head), yes: blGroup(steps.slice(i, yes).map(s => blWithout(s, whole))), no: blGroup(steps.slice(yes, no).map(s => blWithout(s, whole))) };
  if (noHead !== null && !blSame(noHead, blOpposite(head))) box.rule_no = clone(noHead);
  return yes > i && blSame(blFromBoxes([box]), steps.slice(i, no)) ? [box, no] : null;
}
function blGroup(steps) {
  const out = []; let i = 0;
  while (i < steps.length) {
    const head = blHeadOf(steps[i], false);
    if (head === null) { out.push({ kind: 'step', step: clone(steps[i]) }); i++; continue; }
    const whole = blWholeHead(steps, i);
    let got = whole !== null && !blSame(whole, head) ? blIfBox(steps, i, whole, true) : null;
    if (!got) got = blIfBox(steps, i, head, false);
    if (got) { out.push(got[0]); i = got[1]; continue; }
    let j = i; while (j < steps.length && blSame(blHeadOf(steps[j], false), head)) j++;
    j = Math.max(j, i + 1);
    steps.slice(i, j).forEach(s => out.push({ kind: 'step', step: clone(s) }));
    i = j;
  }
  return out;
}
function blToBoxes(steps) {
  const boxes = blGroup(steps || []);
  return blSame(blFromBoxes(boxes), steps || []) ? boxes : (steps || []).map(s => ({ kind: 'step', step: clone(s) }));
}
function blFromBoxes(boxes) {
  const out = [];
  (boxes || []).forEach(b => {
    if (b.kind === 'step') out.push(clone(b.step));
    else if (b.kind === 'if') {
      const noRule = b.rule_no || blOpposite(b.rule);
      blFromBoxes(b.yes).forEach(s => { s.when = blJoin(b.rule, s.when); out.push(s); });
      blFromBoxes(b.no).forEach(s => { s.when = blJoin(noRule, s.when); out.push(s); });
    }
  });
  return out;
}

// ----- the boxes, kept on the editor state -----
function blEnsure() {
  const sig = blCanon(EW.work.steps);
  if (!EW.bl) EW.bl = { boxes: blToBoxes(EW.work.steps), sig, sel: null, tab: 'edit', multi: new Set(), data: null, try: { people: null, as: '', fields: {}, out: null } };
  else if (sig !== EW.bl.sig) { EW.bl.boxes = blToBoxes(EW.work.steps); EW.bl.sig = sig; EW.bl.multi.clear(); if (EW.bl.sel && !['start', 'ask', 'out', 'report', 'hist'].includes(EW.bl.sel) && !blGet(EW.bl.sel)) EW.bl.sel = null; }
}
// the boxes become the steps: called by commit() before every change is kept
function blSync() {
  if (!blOn() || !EW || !EW.bl || EW.d.workflow_type === 'read') return;
  EW.work.steps = blFromBoxes(EW.bl.boxes);
  EW.bl.sig = blCanon(EW.work.steps);
  EW.ids = EW.work.steps.map((_, i) => i);
  EW.pids = (EW.work.parked || []).map((_, k) => EW.ids.length + k);
  EW.nextId = EW.ids.length + EW.pids.length;
  EW.pos = {}; EW.saw = false;                 // the canvas arranges the boxes again when it is opened
}
// a box's place: "2" at the top, "2.yes.0" in a lane
const blParts = path => String(path).split('.');
function blListAt(base) { if (!base) return EW.bl.boxes; const p = blParts(base); let l = EW.bl.boxes; for (let i = 0; i < p.length; i += 2) { const b = l[+p[i]]; if (!b || b.kind !== 'if') return null; l = b[p[i + 1]]; } return l; }
function blBaseOf(path) { const p = blParts(path); p.pop(); return p.join('.'); }
const blIdx = path => +blParts(path).pop();
function blGet(path) { const l = blListAt(blBaseOf(path)); return l ? l[blIdx(path)] : null; }
// where each box's steps run in the flat list: the index of a step box, and how many steps run before any box
function blIndex() {
  const index = {}, before = {}; let n = 0;
  (function walk(list, base) {
    list.forEach((b, i) => {
      const path = (base ? base + '.' : '') + i; before[path] = n;
      if (b.kind === 'step') { index[path] = n; n++; }
      else { walk(b.yes, path + '.yes'); walk(b.no, path + '.no'); }
    });
  })(EW.bl.boxes, '');
  EW.bl.index = index; EW.bl.before = before; EW.bl.count = n;
}
const blStepCount = b => b.kind === 'step' ? 1 : b.yes.reduce((a, x) => a + blStepCount(x), 0) + b.no.reduce((a, x) => a + blStepCount(x), 0);

// ----- the screen -----
function blDrawEditor() {
  const root = ui.root, d = EW.d, read = isRead();
  blEnsure();
  ui.name = h('input', { class: 'nm', type: 'text', value: EW.work.name, 'aria-label': 'Name', oninput: e => { EW.work.name = e.target.value; const cn = document.getElementById('crumbname'); if (cn) cn.textContent = e.target.value; commit(false); } });
  ui.save = h('button', { class: 'btn sm primary', type: 'button', onclick: save }, 'Saved');
  ui.discard = h('button', { class: 'btn sm', type: 'button', onclick: discard }, 'Discard');
  ui.undo = h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Undo the last change', 'data-tip': 'Undo the last change (Ctrl+Z)', onclick: undo }, icon('undo', 'sm'));
  ui.dirty = h('span', { class: 'badge warn' }, 'Unsaved');
  const power = h('span', null, d.is_active ? 'On' : 'Off'), flowName = EW.work.name || d.name;
  const flipActive = async (v, undone) => {
    await api.post('/workflows/' + d.id + '/active', { is_active: v });
    d.is_active = v; power.textContent = v ? 'On' : 'Off'; flowSwitch.querySelector('input').checked = v;
    toast(switchNote({ ...EW.work, name: flowName, used_in: d.used_in }, v), 'ok', undone ? null : { label: 'Undo', run: () => flipActive(!v, true).catch(x => toast(x.message, 'bad')) });
  };
  const flowSwitch = switchEl(d.is_active, v => flipActive(v, false), false, flowName);
  const lbl = text => h('span', { class: 'tx' }, text);
  const head = h('div', { class: 'cvbar' },
    h('div', { class: 'titlechip' },
      h('a', { class: 'btn sm ghost icon', href: '#/workflows', 'aria-label': 'Back to all flows' }, icon('chevl', 'sm')), ui.name,
      badge(KIND_LABEL[EW.work.kind] || pretty(EW.work.kind || 'workflow'), EW.work.kind === 'block' ? 'teal' : 'violet'), ui.dirty,
      h('label', { class: 'row small flat', style: { gap: '6px' } }, flowSwitch, power)),
    h('div', { class: 'actbar' }, ui.undo,
      h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Earlier versions', 'data-tip': 'Earlier versions: see or restore (this is version ' + d.version + ')', onclick: () => blSelect('hist') }, icon('hist', 'sm')),
      read ? null : h('button', { class: 'btn sm', type: 'button', onclick: () => { EW.bl.tab = 'try'; blDrawSide(); } }, icon('play', 'sm'), lbl('Try it')),
      h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'The same flow drawn as a map of boxes and wires', onclick: () => setEditorView('map') }, icon('map', 'sm'), lbl('Map view')),
      // back to the plain editor (chat, Card, chart): every flow people start opens there
      h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'The plain editor: chat with the AI, the Card, the simple chart and Try it', onclick: () => openWorkflow(EW.id) }, icon('spark', 'sm'), lbl('Plain editor')),
      ui.discard, ui.save));
  EW.bl.banner = h('div', { class: 'cvprob' });
  EW.bl.selbar = h('div', { class: 'bl-selbar' });
  EW.bl.listEl = h('div', { class: 'bl-list' });
  EW.bl.sideEl = h('aside', { class: 'bl-side', 'aria-label': 'The chosen box' });
  const dock = read ? null : h('div', { class: 'dock min bl-dock' },
    h('button', { class: 'dhd', type: 'button', onclick: () => dock.classList.toggle('min') }, icon('spark'), h('span', null, 'Ask the AI helper to change this'), icon('chevd', 'sm')),
    chatDock(read));
  fill(root, h('div', { class: 'wsp bl' }, head,
    h('div', { class: 'bl-row' }, h('div', { class: 'bl-left' }, EW.bl.banner, EW.bl.selbar, EW.bl.listEl, dock), EW.bl.sideEl)));
  blWireDrops();
  const cn = document.getElementById('crumbname'); if (cn) cn.textContent = EW.work.name;
  blDrawList(); blDrawSide(); updateBar(); blDrawProblems(); blQueueData();
}
function blDrawPane() { if (!EW || !EW.bl || !EW.bl.listEl) return; blEnsure(); blDrawList(); blDrawSide(); blQueueData(); }
function blSelect(sel) { EW.bl.sel = sel; EW.bl.tab = 'edit'; EW.bl.multi.clear(); blDrawList(); blDrawSide(); }

function blSpecial(sel, ic, title, sub, k) {
  return h('div', { class: 'bl-box bl-sp k-' + k + (EW.bl.sel === sel ? ' sel' : ''), role: 'button', tabindex: '0', onclick: () => blSelect(sel), onkeydown: e => { if (e.key === 'Enter') blSelect(sel); } },
    h('div', { class: 'bl-h' }, h('span', { class: 'bl-ic' }, icon(ic)), h('div', { class: 'bl-t' }, h('b', null, title), h('small', null, sub))));
}
function blStartSummary() {
  const w = EW.work, cmd = w.slash_command ? '/' + w.slash_command : '';
  const words = (w.training_phrases || []).slice(0, 2).map(t => '“' + t + '”').join(', ');
  const who = (EW.d.granted_roles || []).length ? (EW.d.granted_roles || []).join(', ') : 'nobody yet';
  return [cmd, words].filter(Boolean).join(' · ') + (cmd || words ? ' · ' : '') + 'who: ' + who;
}
function blAskSummary() {
  const f = Object.entries(EW.work.entity_schema || {}).filter(([, s]) => isObj(s) && !s.computed);
  return f.length ? f.map(([k, s]) => (s.label || pretty(k)) + (s.required ? '' : ' (optional)')).join(' · ') : (EW.work.kind === 'block' ? 'Nothing: it uses what the flow already has' : 'Nothing is asked');
}
function blOutSummary() {
  const o = (EW.work.settings || {}).outputs || [];
  return o.length ? o.map(x => x.label).join(' · ') : 'Everything its steps find (nothing named)';
}

function blDrawList() {
  if (!EW || !EW.bl || !EW.bl.listEl) return;
  blEnsure(); blIndex();
  const w = EW.work, block = w.kind === 'block';
  const parts = [];
  if (isRead()) parts.push(blSpecial('report', 'table', 'A saved report', 'It answers with a saved query, so it has no steps to change here.', 'look'));
  else {
    if (!block) parts.push(blSpecial('start', 'bolt', 'When it starts', blStartSummary(), 'trigger'));
    parts.push(blSpecial('ask', block ? 'layers' : 'chat', block ? 'What it needs' : 'Ask questions', blAskSummary(), 'look'));
    parts.push(blLane(EW.bl.boxes, ''));
    parts.push(block ? blSpecial('out', 'send', 'What it gives back', blOutSummary(), 'block') : h('div', { class: 'bl-end' }, '● Done: it tells the person'));
  }
  fill(EW.bl.listEl, parts);
  blDrawSelBar();
}
function blLane(list, base) {
  const el = h('div', { class: 'bl-lane', 'data-base': base });
  const plus = at => h('div', { class: 'bl-conn' }, h('button', { class: 'bl-add', type: 'button', 'aria-label': 'Add a step here', 'data-tip': 'Add a step here', onclick: e => { e.stopPropagation(); blPick(base, at); } }, icon('plus', 'sm')));
  if (base && !list.length) el.append(h('div', { class: 'bl-none' }, 'Nothing: it carries on'));
  el.append(plus(0));
  list.forEach((b, i) => { const path = (base ? base + '.' : '') + i; el.append(blBox(b, path), plus(i + 1)); });
  return el;
}
function blStepTitle(s) {
  if (s.name) return s.name;
  if (s.op === 'run_workflow') { const f = ST.byKey[(s.params || {}).workflow]; return f ? f.name : 'A building block (missing)'; }
  const spec = catalogSpec(s.op); return spec ? spec.label : pretty(s.op);
}
function blProblems(path) {
  const b = blGet(path); if (!b) return [];
  if (b.kind === 'if') {
    const out = [];
    if (!blRuleAtoms(b.rule).some(a => a.field)) out.push(['bad', 'Choose what this If looks at.']);
    if (!blStepCount(b)) out.push(['bad', 'This If has no steps in its lanes, so it is not saved. Press + in a lane.']);
    return out;
  }
  const i = EW.bl.index[path];
  return i === undefined ? [] : problemsFor(i + 1);
}
function blBox(b, path) {
  const sel = EW.bl.sel === path, multi = EW.bl.multi.has(path);
  const probs = blProblems(path).filter(p => p[0] === 'bad');
  if (b.kind === 'if') {
    return h('div', { class: 'bl-box bl-if k-other' + (sel ? ' sel' : '') + (multi ? ' multi' : ''), 'data-path': path, onclick: e => { if (!e.target.closest('.bl-lanes')) blClick(e, path); } },
      blHead('branch', 'If… otherwise', blRuleAtoms(b.rule).some(a => a.field) ? condText(b.rule) : 'Choose what to look at', path, probs),
      h('div', { class: 'bl-lanes' },
        h('div', { class: 'bl-lcol yes' }, h('div', { class: 'bl-lab' }, '✓ YES'), blLane(b.yes, path + '.yes')),
        h('div', { class: 'bl-lcol no' }, h('div', { class: 'bl-lab' }, '✗ OTHERWISE'), blLane(b.no, path + '.no'))));
  }
  const s = b.step;
  const sub = describeStep(s) + (blHasWhen(s) ? ' · only if ' + condText(s.when) : '');
  return h('div', { class: 'bl-box k-' + cvKey(s) + (isAiStep(s) ? ' ai' : '') + (sel ? ' sel' : '') + (multi ? ' multi' : ''), 'data-path': path, onclick: e => blClick(e, path) },
    blHead(cvIcon(s.op), blStepTitle(s), sub, path, probs, isAiStep(s)));
}
function blHead(ic, title, sub, path, probs, ai) {
  return h('div', { class: 'bl-h' },
    h('span', { class: 'bl-grip', draggable: 'true', title: 'Drag to move', 'aria-hidden': 'true', ondragstart: e => { EW.bl.drag = path; e.dataTransfer.setData('text/x-orch-box', path); e.dataTransfer.effectAllowed = 'move'; } }, '⋮⋮'),
    h('span', { class: 'bl-ic' }, icon(ic)),
    h('div', { class: 'bl-t' }, h('b', null, title, ai ? h('span', { class: 'badge violet', style: { marginLeft: '6px' } }, 'AI') : null), h('small', null, sub)),
    probs.length ? h('span', { class: 'bl-dot', title: probs.map(p => p[1]).join('\n') }, String(probs.length)) : null,
    h('span', { class: 'bl-acts' },
      h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Duplicate', 'data-tip': 'Duplicate', onclick: e => { e.stopPropagation(); blDup(path); } }, icon('copy', 'sm')),
      h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Delete', 'data-tip': 'Delete', onclick: e => { e.stopPropagation(); blDel(path); } }, icon('trash', 'sm'))));
}
function blClick(e, path) {
  e.stopPropagation();
  if (e.ctrlKey || e.metaKey || e.shiftKey) {          // pick several boxes in one lane, to save them as a building block
    const m = EW.bl.multi, base = blBaseOf(path);
    if ([...m].some(p => blBaseOf(p) !== base)) m.clear();
    if (m.has(path)) m.delete(path); else m.add(path);
    blDrawList(); return;
  }
  blSelect(path);
}
function blDrawSelBar() {
  const m = EW.bl.multi, el = EW.bl.selbar;
  if (!el) return;
  if (!m.size) { fill(el); el.style.display = 'none'; return; }
  el.style.display = '';
  fill(el, h('span', null, plural(m.size, 'box', 'boxes') + ' chosen'), h('span', { class: 'grow' }),
    h('button', { class: 'btn sm primary', type: 'button', onclick: blSaveAsBlock }, icon('layers', 'sm'), 'Save as a building block'),
    h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { m.clear(); blDrawList(); } }, 'Clear'));
}

// ----- adding, moving, copying, removing -----
function blNewStep(op) {
  const spec = catalogSpec(op), step = { op, params: {} };
  (spec ? spec.params : []).forEach(p => { if (p.default !== undefined && p.kind !== 'column') step.params[p.key] = p.default; });
  return step;
}
function blInsert(base, at, box) {
  const list = blListAt(base); if (!list) return;
  list.splice(at, 0, box);
  const path = (base ? base + '.' : '') + at;
  EW.bl.sel = path; EW.bl.tab = 'edit';
  commit(true, true);
}
function blPick(base, at) {
  const q = h('input', { type: 'search', class: 'input', placeholder: 'Search: approve, message, AI, find…', 'aria-label': 'Search the steps' });
  const body = h('div', { class: 'bl-picks' });
  const close = () => m.close();
  const item = (ic, title, help, k, run) => h('button', { class: 'bl-pick k-' + k, type: 'button', onclick: () => { close(); run(); } }, h('span', { class: 'bl-ic' }, icon(ic)), h('span', { class: 'grow' }, h('b', null, title), h('small', null, help || '')));
  function draw() {
    const t = q.value.trim().toLowerCase(), hit = (...x) => !t || x.join(' ').toLowerCase().includes(t);
    const groups = {};
    const put = (g, el) => (groups[g] = groups[g] || []).push(el);
    put('Decide', hit('if otherwise decide condition') ? item('branch', 'If… otherwise', 'Do different things depending on the data.', 'other', () => blInsert(base, at, { kind: 'if', rule: { field: '', equals: '' }, yes: [], no: [] })) : null);
    (ST.catalog.steps || []).filter(s => s.op !== 'run_workflow').forEach(s => { if (hit(s.label, s.help, s.group)) put(s.group, item(cvIcon(s.op), s.label, s.help, cvKey({ op: s.op }), () => blInsert(base, at, { kind: 'step', step: blNewStep(s.op) }))); });
    ST.flows.filter(w => w.kind === 'block' && w.id !== EW.id && w.is_active).forEach(w => { if (hit(w.name, w.description, 'block')) put('Your building blocks', item('layers', w.name, w.description, 'block', () => blInsert(base, at, { kind: 'step', step: { op: 'run_workflow', params: { workflow: w.intent_key } } }))); });
    const shown = Object.entries(groups).map(([g, l]) => [g, l.filter(Boolean)]).filter(([, l]) => l.length);
    fill(body, shown.length ? shown.map(([g, l]) => h('div', { class: 'bl-pg' }, h('div', { class: 'bl-pgl' }, g), h('div', { class: 'bl-pgr' }, l))) : h('div', { class: 'muted' }, 'Nothing matches. Ask the AI helper under the flow.'));
  }
  q.addEventListener('input', draw);
  draw();
  const m = modal({ title: 'Add a step', body: h('div', { class: 'stack' }, q, body), wide: true });
  setTimeout(() => q.focus(), 30);
}
function blDup(path) {
  const list = blListAt(blBaseOf(path)), i = blIdx(path);
  list.splice(i + 1, 0, clone(list[i]));
  EW.bl.sel = blBaseOf(path) ? blBaseOf(path) + '.' + (i + 1) : String(i + 1);
  commit(true, true);
}
async function blDel(path) {
  const b = blGet(path), n = b.kind === 'if' ? blStepCount(b) : 0;
  if (n && !await confirmBox('Delete this If and the ' + plural(n, 'step') + ' in its lanes?', { ok: 'Delete', danger: true })) return;
  blListAt(blBaseOf(path)).splice(blIdx(path), 1);
  EW.bl.sel = null;
  commit(true, true);
  toast('Deleted “' + (b.kind === 'if' ? 'If… otherwise' : blStepTitle(b.step)) + '”.', null, { label: 'Undo', run: undo });
}
function blMove(from, to) {
  if (from === to || blBaseOf(from) !== blBaseOf(to)) return;
  const list = blListAt(blBaseOf(from)), i = blIdx(from), j = blIdx(to);
  const [b] = list.splice(i, 1); list.splice(j, 0, b);
  EW.bl.sel = blBaseOf(from) ? blBaseOf(from) + '.' + j : String(j);
  commit(true, true);
  toast('Moved. A red dot shows if a step now uses data that is not known yet.');
}
async function blSaveAsBlock() {
  const paths = [...EW.bl.multi].sort((a, b) => blIdx(a) - blIdx(b)), base = blBaseOf(paths[0]);
  const idx = paths.map(blIdx);
  if (idx.some((v, k) => k && v !== idx[k - 1] + 1)) { toast('Choose boxes that follow each other.', 'bad'); return; }
  const name = h('input', { type: 'text', class: 'input', placeholder: 'e.g. Check the slot is free' });
  const ok = await new Promise(res => {
    modal({ title: 'Save as a building block', onClose: () => res(false), body: h('div', { class: 'stack' }, h('p', { class: 'muted small' }, 'These steps become one building block. Here they are replaced by one box that uses it, and any flow can use it too.'), field('Name', name)),
      actions: [{ label: 'Cancel', run: () => res(false) }, { label: 'Save the block', primary: true, run: () => res(true) }] });
    setTimeout(() => name.focus(), 30);
  });
  if (!ok || name.value.trim().length < 2) return;
  const list = blListAt(base), chosen = list.slice(idx[0], idx[idx.length - 1] + 1);
  try {
    const r = await api.post('/workflows', { name: name.value.trim(), kind: 'block', steps: blFromBoxes(chosen) });
    await ensureStudio();
    list.splice(idx[0], chosen.length, { kind: 'step', step: { op: 'run_workflow', params: { workflow: r.intent_key } } });
    EW.bl.multi.clear(); EW.bl.sel = (base ? base + '.' : '') + idx[0];
    commit(true, true);
    toast('Saved the building block “' + name.value.trim() + '”. Save this flow to use it here.', 'ok');
  } catch (e) {
    const dd = e.data && e.data.detail;
    toast(dd && dd.problems ? dd.error + ' ' + dd.problems.join(' ') : e.message, 'bad');
  }
}

// ----- dragging: boxes to move them, data into a setting -----
function blTakeAt(node, stop) {
  for (let n = node; n && n !== stop; n = n.parentNode) {
    if (n._take) return n;
    if (n.querySelector && n.classList && (n.classList.contains('vp') || n.classList.contains('field'))) { const c = n.querySelector('select,input,textarea'); if (c && c._take) return c; }
  }
  return null;
}
function blWireDrops() {
  const L = EW.bl.listEl, R = EW.bl.sideEl;
  L.addEventListener('dragover', e => {
    if (!EW.bl.drag) return;
    const t = e.target.closest('[data-path]');
    if (t && blBaseOf(t.dataset.path) === blBaseOf(EW.bl.drag)) { e.preventDefault(); L.querySelectorAll('.bl-over').forEach(x => x.classList.remove('bl-over')); t.classList.add('bl-over'); }
  });
  L.addEventListener('drop', e => {
    const t = e.target.closest('[data-path]'), from = EW.bl.drag; EW.bl.drag = null;
    if (t && from) { e.preventDefault(); e.stopPropagation(); blMove(from, t.dataset.path); }
  });
  document.addEventListener('dragend', () => { if (EW && EW.bl) EW.bl.drag = null; document.querySelectorAll('.bl-over').forEach(x => x.classList.remove('bl-over')); document.body.classList.remove('bl-dragdata'); });
  R.addEventListener('dragover', e => {
    if (![...e.dataTransfer.types].includes('text/x-orch-data')) return;
    const t = blTakeAt(e.target, R);
    if (t) { e.preventDefault(); R.querySelectorAll('.bl-over').forEach(x => x.classList.remove('bl-over')); t.classList.add('bl-over'); }
  });
  R.addEventListener('drop', e => {
    const path = e.dataTransfer.getData('text/x-orch-data'); if (!path) return;
    const t = blTakeAt(e.target, R); if (!t) return;
    e.preventDefault(); t.classList.remove('bl-over'); t.focus && t.focus(); t._take(path);
  });
}

// ----- what is known at a place in the flow -----
let blDataTimer = null;
function blQueueData() {
  clearTimeout(blDataTimer);
  const mine = EW;
  blDataTimer = setTimeout(async () => {
    if (mine !== EW || !EW.bl || isRead()) return;
    try {
      const r = await api.post('/studio/builder/compile', { boxes: EW.bl.boxes, entity_schema: EW.work.entity_schema || {}, kind: EW.work.kind || 'workflow', intent_key: EW.d.intent_key });
      if (mine !== EW) return;
      EW.bl.data = { base: r.base_data, step: r.step_data };
      blRefreshData();
    } catch (e) { /* the panel keeps what it has: the dashboard's own list below */ }
  }, 350);
}
function blDataBefore(n) {
  let items;
  if (EW.bl.data && EW.bl.data.step.length === EW.work.steps.length) items = [...EW.bl.data.base, ...EW.bl.data.step.slice(0, n).flat()];
  else items = valueOptions(envBefore(n)).filter(g => g[0] !== 'Other').flatMap(([g, l]) => l.map(([path, label]) => ({ group: g, label, path, token: tokenFor(path) })));
  const seen = new Set(), groups = new Map();
  items.forEach(it => { if (!it.path || seen.has(it.path)) return; seen.add(it.path); if (!groups.has(it.group)) groups.set(it.group, []); groups.get(it.group).push(it); });
  return [...groups.entries()];
}
function blUse(path) {
  if (!FOCUSED_VALUE || !document.body.contains(FOCUSED_VALUE.el)) { toast('Click inside a setting on the right first, then click the data. Or drag it there.'); return; }
  FOCUSED_VALUE.take(path);
}
function blDataPanel(n) {
  const list = h('div', { class: 'bl-dl' });
  const q = h('input', { type: 'search', class: 'input', placeholder: 'Search data…', 'aria-label': 'Search the data', oninput: () => draw() });
  function draw() {
    const t = q.value.trim().toLowerCase();
    fill(list, blDataBefore(n).map(([g, items]) => {
      const shown = items.filter(it => !t || (it.label + ' ' + g).toLowerCase().includes(t));
      return shown.length ? h('div', { class: 'bl-dg' }, h('div', { class: 'bl-dgl' }, g), shown.map(it => h('button', { type: 'button', class: 'bl-chip', draggable: 'true', title: (it.token ? 'In a message it is written ' + it.token : it.path), onmousedown: e => e.preventDefault(), onclick: () => blUse(it.path),
        ondragstart: e => { e.dataTransfer.setData('text/x-orch-data', it.path); e.dataTransfer.setData('text/plain', it.token || it.path); e.dataTransfer.effectAllowed = 'copy'; } }, h('span', { class: 'g', 'aria-hidden': 'true' }, '⋮⋮'), it.label))) : null;
    }));
  }
  draw();
  const el = h('aside', { class: 'bl-data', 'data-n': String(n) }, h('div', { class: 'bl-dh' }, h('b', null, 'Data you can use here'), h('div', { class: 'muted small' }, 'Drag it into a setting, or click a setting and then the data. Only data from boxes above this one is here.')), q, list);
  el._redraw = draw;
  return el;
}
function blRefreshData() { if (!EW.bl.sideEl) return; const el = EW.bl.sideEl.querySelector('.bl-data'); if (el && el._redraw) el._redraw(); }

// ----- the right side: the chosen box, Try it, Technical -----
function blDrawSide() {
  const el = EW.bl.sideEl; if (!el) return;
  const old = el.querySelector('.bl-sb'), top = old ? old.scrollTop : 0, key = EW.bl.tab + '|' + EW.bl.sel;
  const tabs = h('div', { class: 'itabs' }, [['edit', 'Edit'], ['try', 'Try it'], ['tech', 'Technical']].map(([k, l]) => h('button', { class: 'tab', type: 'button', 'aria-selected': String(EW.bl.tab === k), onclick: () => { EW.bl.tab = k; blDrawSide(); } }, l)));
  const body = EW.bl.tab === 'try' ? blTryPane() : EW.bl.tab === 'tech' ? blTechPane() : blEditPane();
  fill(el, tabs, h('div', { class: 'bl-sb' }, body));
  const nb = el.querySelector('.bl-sb'); if (nb && EW.bl.sideKey === key) nb.scrollTop = top;
  EW.bl.sideKey = key;
}
function blEditPane() {
  const sel = EW.bl.sel, block = EW.work.kind === 'block';
  if (!sel) return h('div', { class: 'empty' }, h('b', null, 'Click a box to change it'), 'Press + between boxes to add a step. Each box opens here, with the data you can use next to it.');
  if (sel === 'start') return h('div', { class: 'stack' }, detailsPane(), h('details', null, h('summary', { class: 'muted small' }, 'Safeguards (codes, approvals by amount, roles)'), h('div', { style: { marginTop: '10px' } }, safePane())));
  if (sel === 'ask') return h('div', { class: 'stack' }, h('p', { class: 'muted small' }, block ? 'What a flow must give this block when it uses it. Inside the block each one is data you can use.' : 'The bot asks these before the steps run, one by one (and skips what the person already said). Each answer is data the boxes below can use.'), asksPane());
  if (sel === 'report') return h('div', { class: 'stack' }, reportPanel());
  if (sel === 'hist') return h('div', { class: 'stack' }, historyPane());
  if (sel === 'out') return blOutPane();
  const b = blGet(sel);
  if (!b) return h('div', { class: 'empty' }, 'This box is gone.');
  return b.kind === 'if' ? blIfPane(b, sel) : blStepPane(b, sel);
}
const blProbList = probs => probs.length ? h('div', { class: 'stack s8' }, probs.map(([t, m]) => h('div', { class: 'prob ' + t }, m.replace(/^Step \d+( \([^)]*\))?:? ?/, '')))) : null;
function blStepPane(b, path) {
  const s = b.step, i = EW.bl.index[path], spec = catalogSpec(s.op), again = () => blDrawSide();
  const name = h('input', { type: 'text', class: 'input bl-name', value: s.name || '', placeholder: blStepTitle({ ...s, name: '' }), 'aria-label': 'Name of this box', oninput: e => { const v = e.target.value.trim(); if (v) s.name = v; else delete s.name; commit(false); } });
  const form = s.op === 'run_workflow' ? blBlockPane(s, i) : settingsTab(s, i, again);
  return h('div', { class: 'bl-edit' }, blDataPanel(i),
    h('div', { class: 'bl-form stack' },
      h('div', { class: 'bl-kicker k-' + cvKey(s) }, icon(cvIcon(s.op), 'sm'), s.op === 'run_workflow' ? 'Building block' : (spec ? spec.group : 'Step')),
      field('Name of this box', name, 'Optional: what it does, in your words.'),
      spec && spec.help ? h('div', { class: 'muted small' }, spec.help) : null,
      blProbList(blProblems(path)),
      form,
      blHasWhen(s) ? field('Only if', conditionEditor(s, i, commit), 'This box keeps its own condition.') : null));
}
function blBlockPane(s, i) {
  const params = s.params = s.params || {}, key = params.workflow, flow = ST.byKey[key];
  const pick = paramControl((catalogSpec('run_workflow') || { params: [] }).params.find(p => p.key === 'workflow') || { key: 'workflow', label: 'Which one', kind: 'workflow' }, s, i, commit, () => blDrawSide());
  if (!flow) return h('div', { class: 'stack' }, pick);
  const needs = Object.entries(flow.entity_schema || {}).filter(([, f]) => isObj(f));
  const inputs = isObj(params.inputs) ? params.inputs : null, env = envBefore(i);
  const need = ([k, f]) => field((f.label || pretty(k)) + (f.required ? ' *' : ''),
    valuePicker(env, inputs ? inputs[k] : undefined, v => { const inp = isObj(params.inputs) ? params.inputs : (params.inputs = {}); if (isBlank(v)) delete inp[k]; else inp[k] = v; if (!Object.keys(inp).length) delete params.inputs; commit(false); }),
    (f.description || '') + (EW.work.entity_schema && EW.work.entity_schema[k] ? ' Left empty, it uses this flow’s own answer.' : ''));
  const outs = ((flow.settings || {}).outputs || []);
  return h('div', { class: 'stack' }, pick,
    flow.description ? h('div', { class: 'notice teal' }, icon('layers'), h('div', { class: 'small' }, flow.description, ' ', h('a', { href: '#/workflows?f=' + flow.id }, 'Open the block'))) : h('a', { class: 'small', href: '#/workflows?f=' + flow.id }, 'Open the block'),
    needs.length ? h('div', { class: 'stack' }, h('div', { class: 'bl-sub' }, 'Fill in what it needs'), needs.map(need)) : h('div', { class: 'muted small' }, 'It needs nothing: it uses what this flow already has.'),
    h('div', { class: 'bl-sub' }, 'It gives back'),
    outs.length ? h('div', { class: 'chips' }, outs.map(o => h('span', { class: 'chip' }, (flow.name) + ' – ' + o.label))) : h('div', { class: 'muted small' }, 'Everything its steps find. The boxes below can use it.'));
}
// ----- an If box: its rules -----
function blRuleAtoms(rule) {
  if (!isObj(rule)) return [];
  if (Array.isArray(rule.or)) return rule.or;
  if (Array.isArray(rule.and)) return rule.and;
  return [rule];
}
const blJoinOf = rule => isObj(rule) && Array.isArray(rule.or) ? 'or' : 'and';
function blIfPane(b, path) {
  const env = envBefore(EW.bl.before[path] || 0);
  let join = blJoinOf(b.rule);
  let rows = blRuleAtoms(b.rule).map(a => parseWhen(a)[0] || { field: '', op: 'equals', value: '' });
  if (!rows.length) rows = [{ field: '', op: 'equals', value: '' }];
  const box = h('div', { class: 'stack' });
  function save(redraw) {
    const atoms = buildWhen(rows);
    const list = !atoms ? [] : Array.isArray(atoms.and) && Object.keys(atoms).length === 1 ? atoms.and : [atoms];
    b.rule = !list.length ? { field: '', equals: '' } : list.length === 1 ? list[0] : { [join]: list };
    delete b.rule_no;
    commit(!!redraw);
  }
  function draw() {
    fill(box,
      field('Look at', h('div', { class: 'seg' }, [['and', 'All of these are true'], ['or', 'Any one is true']].map(([v, l]) => h('button', { type: 'button', class: join === v ? 'on' : '', onclick: () => { join = v; save(true); } }, l)))),
      rows.map((r, k) => h('div', { class: 'cond' },
        valuePicker(env, r.field, v => { r.field = v; save(false); }),
        sel(OPERATORS.map(o => [o[0], o[1]]), r.op, { onchange: e => { r.op = e.target.value; save(false); draw(); } }),
        (r.op === 'exists_true' || r.op === 'exists_false') ? null : h('input', { type: 'text', value: r.value, placeholder: r.op === 'in' || r.op === 'not_in' ? 'one, two, three' : 'value, e.g. Approve', oninput: e => { r.value = e.target.value; save(false); } }),
        h('button', { class: 'x', type: 'button', title: 'Remove', onclick: () => { rows.splice(k, 1); if (!rows.length) rows.push({ field: '', op: 'equals', value: '' }); save(true); } }, '×'))),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { rows.push({ field: '', op: 'equals', value: '' }); draw(); } }, '+ Add a rule'));
  }
  draw();
  return h('div', { class: 'bl-edit' }, blDataPanel(EW.bl.before[path] || 0),
    h('div', { class: 'bl-form stack' },
      h('div', { class: 'bl-kicker k-other' }, icon('branch', 'sm'), 'If… otherwise'),
      blProbList(blProblems(path)),
      box,
      h('div', { class: 'notice' }, icon('branch'), h('div', { class: 'small' }, 'The boxes in ✓ YES run when this is true, the boxes in ✗ OTHERWISE when it is not. After both, the flow carries on below the If.'))));
}
// ----- a building block: what it gives back -----
function blOutPane() {
  const settings = EW.work.settings = EW.work.settings || {};
  const outs = Array.isArray(settings.outputs) ? settings.outputs : [];
  const env = envBefore(EW.work.steps.length);
  const box = h('div', { class: 'stack' });
  const keep = () => { const ok = outs.filter(o => o.label || o.path); if (ok.length) settings.outputs = ok; else delete settings.outputs; commit(false); };
  function draw() {
    fill(box, outs.map((o, k) => h('div', { class: 'maprow' },
      h('input', { type: 'text', value: o.label || '', placeholder: 'Name, e.g. Already booked', oninput: e => { o.label = e.target.value; keep(); } }),
      valuePicker(env, o.path, v => { o.path = v; keep(); }),
      h('button', { class: 'x', type: 'button', title: 'Remove', onclick: () => { outs.splice(k, 1); keep(); draw(); } }, '×'))),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { outs.push({ label: '', path: '' }); settings.outputs = outs; draw(); } }, '+ Give back something'));
  }
  draw();
  return h('div', { class: 'bl-edit' }, blDataPanel(EW.work.steps.length),
    h('div', { class: 'bl-form stack' },
      h('div', { class: 'bl-kicker k-block' }, icon('send', 'sm'), 'What it gives back'),
      h('p', { class: 'muted small' }, 'Name what a flow gets back from this block. The flow then sees it as “' + (EW.work.name || 'this block') + ' – the name”. Leave it empty and the flow sees everything the steps found.'),
      box));
}

// ----- Try it: a rehearsal, shown as the chat it would be -----
function blTryPane() {
  const T = EW.bl.try, out = h('div', { class: 'bl-chat' }), asked = Object.entries(EW.work.entity_schema || {}).filter(([, f]) => isObj(f) && !f.computed);
  const run = h('button', { class: 'btn primary', type: 'button' }, icon('play', 'sm'), 'Play the chat');
  const asBox = h('div');
  if (!T.people) { asBox.append(h('span', { class: 'muted small' }, 'Loading people…')); api.get('/studio/people').then(r => { T.people = r.people; if (EW.bl.tab === 'try') blDrawSide(); }).catch(e => { T.people = []; toast(e.message, 'bad'); }); }
  else if (!T.people.length) asBox.append(notice('No one is linked to the chat yet, so there is no one to try it as.', 'bad'));
  else { const as = sel(T.people.map(p => [p.id, p.name + ' (' + p.role + ')']), T.as || T.people[0].id, { onchange: e => { T.as = e.target.value; } }); T.as = as.value; asBox.append(field('Try it as', as)); }
  const answers = h('div', { class: 'stack' }, asked.map(([k, f]) => field(f.question || f.label || pretty(k), Array.isArray(f.enum) && f.enum.length ? sel([['', 'Choose…'], ...f.enum.map(x => [x, x])], T.fields[k] || '', { onchange: e => { T.fields[k] = e.target.value; } }) : h('input', { type: 'text', value: T.fields[k] || '', placeholder: 'Their answer', oninput: e => { T.fields[k] = e.target.value; } }))));
  if (T.out) blDrawChat(out, T.out, asked);
  run.disabled = !T.people || !T.people.length;
  run.addEventListener('click', async () => {
    run.disabled = true;
    try {
      const fields = {}; Object.entries(T.fields).forEach(([k, v]) => { if (String(v).trim() !== '') fields[k] = String(v).trim(); });
      T.out = await api.post('/studio/try', { steps: tidySteps(EW.work.steps), entity_schema: EW.work.entity_schema, fields, as_user: T.as, intent_key: EW.d.intent_key, name: EW.work.name, kind: EW.work.kind });
      T.answers = fields; blDrawChat(out, T.out, asked);
    } catch (e) { fill(out, notice(e.message, 'bad')); }
    run.disabled = false;
  });
  return h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, 'A rehearsal: looking things up runs on your real data, but nothing is saved and nobody is messaged. An approval is taken as Approve, and the AI is not asked.'),
    asBox, asked.length ? answers : null, h('div', { class: 'row' }, run, h('button', { class: 'btn ghost', type: 'button', onclick: () => { T.out = null; blDrawSide(); } }, 'Clear')), out);
}
function blDrawChat(out, r, asked) {
  const T = EW.bl.try, bubbles = [];
  const first = EW.work.slash_command ? '/' + EW.work.slash_command : ((EW.work.training_phrases || [])[0] || 'Hi');
  if (EW.work.kind !== 'block') bubbles.push(h('div', { class: 'msg me' }, first));
  asked.forEach(([k, f]) => { bubbles.push(h('div', { class: 'msg bot' }, f.question || f.label || pretty(k))); bubbles.push(h('div', { class: 'msg me' }, (T.answers || {})[k] || '(no answer)')); });
  const glyph = { ran: '✓', would: '✎', skipped: '↷', failed: '✕' };
  (r.trace || []).forEach(t => {
    bubbles.push(h('div', { class: 'msg sys ' + t.status, style: { marginLeft: (t.depth * 14) + 'px' } }, (glyph[t.status] || '•') + ' ' + t.text + (t.detail ? ' — ' + t.detail : '')));
    const said = t.data && typeof t.data.message === 'string' ? t.data.message : '';   // the message the step would send, word for word
    if (said && t.status !== 'skipped') bubbles.push(h('div', { class: 'msg bot' }, said));
  });
  bubbles.push(r.status === 'preview' ? h('div', { class: 'msg bot' }, '✅ It would go through' + (r.facts && r.facts.length ? ': ' + r.facts.join('. ') + '.' : '.'))
    : h('div', { class: 'msg bot bad' }, r.message || 'It would stop here.'));
  fill(out, bubbles);
}
function blTechPane() {
  const text = JSON.stringify({ entity_schema: EW.work.entity_schema, steps: tidySteps(EW.work.steps) }, null, 2);
  return h('div', { class: 'stack' }, h('p', { class: 'muted small' }, 'What is saved, in the form the engine runs. You never need this to build a flow.'),
    h('div', { class: 'row' }, h('button', { class: 'btn sm', type: 'button', onclick: () => copyText(text) }, 'Copy'), h('button', { class: 'btn sm ghost', type: 'button', onclick: () => setEditorView('map') }, 'Open the Map view')),
    h('pre', { class: 'code' }, text));
}

// ----- problems -----
function blDrawProblems() {
  if (!EW || !EW.bl || !EW.bl.banner) return;
  const all = EW.serverProblems ? EW.serverProblems : EW.check.errors;
  fill(EW.bl.banner, all.length ? notice([h('div', null, h('b', null, EW.serverProblems ? 'These need fixing before it can be saved:' : plural(all.length, 'problem') + ' to fix before it can be saved:'),
    h('ul', { style: { margin: '4px 0 0', paddingLeft: '18px' } }, all.slice(0, 6).map(m => {
      const n = /^Step (\d+)\b/.exec(m), path = n ? Object.keys(EW.bl.index || {}).find(p => EW.bl.index[p] === +n[1] - 1) : null;
      return h('li', path ? { class: 'jump', title: 'Show this box', onclick: () => blSelect(path) } : null, m.replace(/^Step \d+( \([^)]*\))?:? ?/, ''));
    })))], 'bad') : null);
  const sig = JSON.stringify(EW.check);
  if (sig !== EW.bl.checkSig) { EW.bl.checkSig = sig; blDrawList(); }   // the red dots on the boxes
}
"""
