JS = r"""
// ───────────────────────── the flow editor screen: step drawers, the panel, the bars ─────────────────────────

// ----- the step list on the left: sections that open like drawers -----
const palItem = o => h('button', { class: 'pi k-' + o.k + (o.later ? ' later' : ''), type: 'button', draggable: o.later ? 'false' : 'true', 'aria-disabled': o.later ? 'true' : null,
    'data-op': o.op, 'data-block': o.block, 'data-trig': o.trig, 'data-logic': o.logic },
  h('span', { class: 'gi' }, icon(o.icon)), h('span', { class: 'grow' }, o.label), o.ai ? h('span', { class: 'tag ai' }, 'AI') : null, o.later ? h('span', { class: 'soonp' }, 'later') : null,
  h('span', { class: 'hq', 'data-tip': o.help }, '?'));
function palSec(key, title, k, ic, count, kids, o) {
  o = o || {};
  return h('details', { class: 'ps k-' + k + (o.sub ? ' sub' : ''), 'data-ps': key, open: CV.palOpen.has(key) },
    h('summary', null, h('span', { class: 'chev' }, icon('chevr', 'xs')), h('span', { class: 'pg' }, o.dot ? h('i') : icon(ic)), h('b', null, title), h('span', { class: 'n' }, count)),
    h('div', { class: 'pb' }, kids));
}
function paletteNode(compact) {
  const steps = (ST.catalog && ST.catalog.steps) || [];
  const blocks = ST.flows.filter(w => w.kind === 'block' && w.is_active && w.id !== EW.id);
  const stepItem = s => palItem({ op: s.op, k: CV_KIND[s.group] || 'other', icon: cvIcon(s.op), label: s.label, help: s.help, ai: isAiStep(s) });
  const groups = GROUP_ORDER.filter(g => g !== 'Other').map(g => [g, steps.filter(s => s.group === g && !isAiStep(s) && s.op !== 'run_workflow')]).filter(g => g[1].length);
  const ai = steps.filter(isAiStep);
  const secs = [];
  if (!compact) secs.push(palSec('trig', 'Triggers', 'trigger', 'bolt', 5, [
    palItem({ trig: 'say', k: 'trigger', icon: 'chat', label: 'Someone says something', help: 'Starts the flow when a person writes something like the phrases you list.' }),
    palItem({ trig: 'cmd', k: 'trigger', icon: 'msg', label: 'Someone types a command', help: 'Starts it when a person types a /command.' }),
    palItem({ trig: 'btn', k: 'trigger', icon: 'cases', label: 'A button on a case', help: 'Starts it from a button on a case (the kind “case action”).' }),
    palItem({ later: true, k: 'trigger', icon: 'cal', label: 'On a schedule', help: 'Starts it at a set time, every day or every week. Later: schedules come with the next engine step.' }),
    palItem({ later: true, k: 'trigger', icon: 'bolt', label: 'When something happens', help: 'For example when a case is created. Later: the engine does not listen for events yet.' })]));
  secs.push(palSec('act', 'Actions', 'save', 'layers', groups.reduce((n, g) => n + g[1].length, 0),
    groups.map(([g, items]) => palSec('act:' + g, g, CV_KIND[g] || 'other', '', items.length, items.map(stepItem), { sub: true, dot: true }))));
  if (!compact) secs.push(palSec('logic', 'Logic', 'other', 'branch', 3, [
    palItem({ logic: 'if', k: 'other', icon: 'branch', label: 'Only run if…', help: 'Skips a step unless something is true. Click a step first, then choose this.' }),
    palItem({ later: true, k: 'other', icon: 'flow', label: 'If / else branch', help: 'Two paths from one step. Later: the engine runs one chain today.' }),
    palItem({ later: true, k: 'other', icon: 'refresh', label: 'Repeat for each…', help: 'Do the same steps for every item in a list. Later: needs engine work.' })]));
  secs.push(palSec('ai', 'AI', 'ai', 'spark', ai.length + 1, [...ai.map(stepItem),
    palItem({ later: true, k: 'ai', icon: 'spark', label: 'Decide with the assistant', help: 'Let the assistant choose between paths. An idea only: AI is used where it is needed and nowhere else.' })]));
  secs.push(palSec('block', 'Building blocks', 'block', 'layers', blocks.length, blocks.length
    ? blocks.map(b => palItem({ op: 'run_workflow', block: b.intent_key, k: 'block', icon: 'layers', label: b.name, help: (b.description || 'A shared building block.') + ((b.needs || []).length ? ' It needs: ' + b.needs.join(', ') + ' found first.' : '') }))
    : h('div', { class: 'pmine' }, 'No other building blocks yet.')));
  secs.push(palSec('mine', 'My nodes', 'trigger', 'star', 0, [h('div', { class: 'pmine' }, 'Soon: pick several boxes on the canvas and save them as one node of your own, with a name and a colour.'),
    h('button', { class: 'mnew', type: 'button', 'data-newnode': '1', 'data-popkeep': '1' }, icon('plus', 'sm'), 'Make your own node')]));
  return h('div', null, secs);
}
function filterPal(root, q) {
  q = (q || '').trim().toLowerCase();
  root.querySelectorAll('.pi').forEach(b => b.classList.toggle('hide', !!q && !b.textContent.toLowerCase().includes(q)));
  [...root.querySelectorAll('details.ps')].reverse().forEach(d => {
    const any = d.querySelectorAll('.pi:not(.hide)').length > 0;
    d.classList.toggle('hide', !!q && !any);
    if (q) { if (any) d.open = true; } else d.open = CV.palOpen.has(d.dataset.ps);
  });
}
const palData = b => ({ op: b.dataset.op, block: b.dataset.block, trig: b.dataset.trig, logic: b.dataset.logic });
function usePalItem(d, at, pos) {
  if (d.trig) { CV.sel = new Set(['trigger']); CV.panel = 'insp'; CV.ttab = 'start'; renderNodes(); renderInspector(); toast('A flow has one trigger. This is where you change how it starts.'); return; }
  if (d.logic === 'if') {
    const id = primary();
    if (!id || id === 'trigger' || id === 'report') { toast('Click a step first, then choose “Only run if…”.'); return; }
    CV.itab = 'if'; CV.panel = 'insp'; renderInspector(); return;
  }
  if (!d.op) return;
  if (isRead()) { toast('This workflow answers with a saved report, so it has no steps to add.'); return; }
  if (at == null && !pos) { const id = primary(); if (id && idxOf(id) >= 0) at = idxOf(id) + 1; }   // with a step selected, a click adds right after it
  cvAddStep(d.op, at, d.block ? { workflow: d.block } : null, pos);
}
function cvOpenAdd(at, anchor, pos) {
  const input = h('input', { class: 'input sm', placeholder: 'Search steps…' });
  const p = openPop(anchor, [h('div', { style: { padding: '6px' } }, input), paletteNode(true)], { width: 310 });
  input.focus(); input.addEventListener('input', () => filterPal(p, input.value));
  p.addEventListener('click', e => {
    const b = e.target.closest('.pi');
    if (!b || b.classList.contains('later') || e.target.closest('.hq')) return;
    closePop(); usePalItem(palData(b), at, pos);
  });
}
function newNodeHelp(anchor) {
  const row = (ic, t, badgeEl, text, dim) => h('div', { class: 'mi', style: { cursor: 'default', opacity: dim ? '.65' : '' } }, icon(ic), h('span', null, h('b', null, t), ' ', badgeEl, h('small', null, text)));
  openPop(anchor, [h('div', { class: 'ml' }, 'Make your own node'),
    row('layers', '1 · From boxes on the canvas', badge('next', 'info'), 'Select boxes, press Save as my node. Made only of steps that exist, so it is safe.'),
    row('db', '2 · In code, added for you', badge('later'), 'A new kind of box with its own fields. Needs a deploy.', true),
    row('plug', '3 · Open node', badge('later'), 'Call a web address or run your own code. Waits for Connections and the security work.', true)], { width: 340, up: true });
}
function paletteAside() {
  const list = h('div', { class: 'pl' }, paletteNode(false));
  const search = h('input', { class: 'input', placeholder: 'Search steps…', oninput: e => filterPal(list, e.target.value) });
  list.addEventListener('toggle', e => { const d = e.target; if (d.dataset && d.dataset.ps && !search.value) { d.open ? CV.palOpen.add(d.dataset.ps) : CV.palOpen.delete(d.dataset.ps); } }, true);
  list.addEventListener('click', e => {
    const n = e.target.closest('[data-newnode]'); if (n) { newNodeHelp(n); return; }
    const b = e.target.closest('.pi');
    if (!b || b.classList.contains('later') || e.target.closest('.hq')) return;
    usePalItem(palData(b));
  });
  list.addEventListener('dragstart', e => {
    const b = e.target.closest('.pi');
    if (!b || b.classList.contains('later')) { e.preventDefault(); return; }
    e.dataTransfer.setData('text/plain', JSON.stringify(palData(b))); e.dataTransfer.effectAllowed = 'copy';
  });
  CV.pal = h('aside', { class: 'pal' + (innerWidth < 1500 ? ' closed' : ''), 'aria-label': 'Steps you can add' },
    h('div', { class: 'pp' }, h('div', { class: 'row between flat' }, h('b', null, 'Add a step'), h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Hide this list', onclick: () => { CV.pal.classList.add('closed'); applyZoom(); } }, icon('chevl', 'sm'))),
      h('div', { class: 'srch' }, icon('search', 'sm'), search),
      h('div', { class: 'muted small' }, 'Open a section. ', h('b', null, 'Drag'), ' a step onto the canvas, or click it to add it.')),
    list);
  return CV.pal;
}

// ----- the panel on the right: settings of what you clicked -----
const insHead = (k, ic, kicker, title, sub) => h('div', { class: 'ih k-' + k }, h('span', { class: 'gi' }, icon(ic)),
  h('div', { class: 'grow' }, h('div', { class: 'kicker' }, kicker), h('h3', null, title), sub ? h('div', { class: 'muted small' }, sub) : null),
  h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Close', onclick: closeInspector }, icon('x', 'sm')));
function closeInspector() { CV.sel = new Set(); CV.panel = 'insp'; clearRun(); renderNodes(); renderInspector(); }
const insTabs = (list, cur, set) => h('div', { class: 'itabs' }, list.map(([k, l]) => h('button', { class: 'tab', type: 'button', 'aria-selected': String(cur === k), onclick: () => { set(k); renderInspector(); } }, l)));
function renderInspector() {
  if (!CV || !CV.insp) return;
  const el = CV.insp, keyNow = CV.panel + '|' + [...CV.sel].join() + '|' + CV.itab + '|' + CV.ttab;
  const old = el.querySelector('.ib'), top = old ? old.scrollTop : 0;
  CV.probEl = null;
  if (CV.panel === 'try') { el.classList.remove('closed'); fill(el, tryPanel()); }
  else if (!CV.sel.size) { el.classList.add('closed'); fill(el); }
  else { el.classList.remove('closed'); fill(el, inspectorContent()); }
  const nb = el.querySelector('.ib');
  if (nb && CV.inspKey === keyNow) nb.scrollTop = top;          // typing in a form redraws it; keep the place
  CV.inspKey = keyNow;
  drawProblems(); applyZoom();
}
function inspectorContent() {
  if (CV.sel.size > 1) return multiPanel();
  const id = primary();
  if (id === 'trigger') return triggerPanel();
  if (id === 'report') return reportPanel();
  const i = idxOf(id);
  return i < 0 ? [] : stepPanel(i);
}
function multiPanel() {
  const steps = EW.work.steps.filter((_, i) => CV.sel.has(idAt(i)));
  return [insHead('block', 'layers', 'Several boxes', CV.sel.size + ' boxes selected', 'Drag any of them to move them all together.'),
    h('div', { class: 'ib' }, h('div', { class: 'stack s8' }, steps.map(s => h('div', { class: 'row flat k-' + cvKey(s), style: { padding: '7px 10px', border: '1px solid var(--line)', borderRadius: '9px' } }, h('i', { style: { width: '9px', height: '9px', borderRadius: '3px', background: 'var(--kc)', flex: 'none' } }), h('span', { class: 'grow' }, describeStep(s))))),
      h('div', { class: 'notice' }, icon('star'), h('div', { class: 'small' }, h('b', null, 'Make your own node.'), ' Soon you can save these as one node with a name and a colour, and use it in any flow.'))),
    h('div', { class: 'if' }, h('button', { class: 'btn sm danger', type: 'button', onclick: () => stepAct('del') }, icon('trash', 'sm'), 'Remove'))];
}
function triggerPanel() {
  const w = EW.work, tabs = [['start', 'Starts it'], ['asks', 'Asks for'], ['safe', 'Safeguards'], ['hist', 'History'], ['json', 'JSON']];
  const body = { start: detailsPane, asks: asksPane, safe: safePane, hist: historyPane, json: advancedPane }[CV.ttab] || detailsPane;
  return [insHead('trigger', 'bolt', w.kind === 'block' ? 'Building block' : 'What starts it', w.kind === 'block' ? w.name : 'When someone…', w.kind === 'block' ? 'It has no trigger of its own and does exactly one thing. Other flows run it as one step.' : 'The words, the command, who may start it and what it asks for.'),
    insTabs(tabs, CV.ttab, k => { CV.ttab = k; }), h('div', { class: 'ib' }, body())];
}
function reportPanel() {
  const d = EW.d;
  const worded = sel([['list', 'By code: every row is shown exactly as stored'], ['generic', 'By the assistant (AI): it may shorten or reword']], EW.work.response_format, { onchange: e => { EW.work.response_format = e.target.value; commit(true); } });
  return [insHead('look', 'table', 'A saved report', 'This workflow answers with a report', 'It looks things up with a saved query instead of steps.'),
    h('div', { class: 'ib' },
      h('div', { class: 'stack s8' }, h('div', { class: 'techlabel' }, h('span', null, 'The SQL it runs'), h('button', { class: 'btn sm', type: 'button', onclick: () => copyText(d.sql_template || '') }, 'Copy')), h('pre', { class: 'code' }, d.sql_template || '')),
      field('How the answer is worded', worded, 'The query always finds the rows. This only chooses who words the reply: code never drops a row or changes a number; the assistant may.'),
      h('a', { class: 'btn sm', href: classicUrl(), target: '_blank', rel: 'noopener' }, 'Change the report in the classic builder ↗'))];
}
function stepPanel(i) {
  const s = EW.work.steps[i], spec = catalogSpec(s.op), key = cvKey(s), blk = s.op === 'run_workflow', n = EW.work.steps.length;
  const tabs = [['set', 'Settings'], ['if', 'Only if'], ['tech', 'Technical']];
  CV.probEl = h('div', { class: 'stack s8' });
  const body = CV.itab === 'if' ? onlyIfTab(s, i) : CV.itab === 'tech' ? techTab(s, i) : settingsTab(s, i);
  const act = (a, ic, label, extra) => h('button', { class: 'btn sm' + (extra || ''), type: 'button', disabled: (a === 'up' && i === 0) || (a === 'down' && i === n - 1), onclick: () => stepAct(a) }, icon(ic, 'sm'), label);
  return [insHead(key, cvIcon(s.op), (blk ? 'Building block' : (spec ? spec.group : 'Step')) + ' · step ' + (i + 1), describeStep(s), spec ? spec.help : ''),
    insTabs(tabs, CV.itab, k => { CV.itab = k; }), h('div', { class: 'ib' }, CV.probEl, body),
    h('div', { class: 'if' }, act('up', 'up', 'Move up'), act('down', 'down', 'Move down'), act('dup', 'copy', 'Duplicate'), act('del', 'trash', 'Remove', ' danger'))];
}
function settingsTab(s, i) {
  const spec = catalogSpec(s.op), box = h('div', { class: 'stack' });
  if (!spec) { box.append(notice('This step type (' + s.op + ') is not one the editor knows. Edit it as JSON under “Technical”.', 'warn')); return box; }
  const main = spec.params.filter(p => !p.advanced), adv = spec.params.filter(p => p.advanced);
  main.forEach(p => box.append(paramControl(p, s, i, commit, renderInspector)));
  if (adv.length) {
    const open = adv.some(p => s.params && s.params[p.key] !== undefined);
    box.append(h('details', open ? { open: true } : null, h('summary', { class: 'muted small' }, 'More options'), h('div', { class: 'stack', style: { marginTop: '10px' } }, adv.map(p => paramControl(p, s, i, commit, renderInspector)))));
  }
  if (!spec.params.length) box.append(h('div', { class: 'muted small' }, 'Nothing to set for this step.'));
  const flow = s.op === 'run_workflow' ? ST.byKey[(s.params || {}).workflow] : null;
  if (flow) box.append(h('div', { class: 'notice teal' }, icon('layers'), h('div', { class: 'small' }, h('b', null, 'A building block.'), ' Change it by opening it. It then changes in every workflow that runs it. ', h('a', { href: '#/workflows?w=' + flow.id }, 'Open this block'))));
  return box;
}
function onlyIfTab(s, i) {
  return h('div', { class: 'stack' }, conditionEditor(s, i, commit),
    h('div', { class: 'notice' }, icon('branch'), h('div', { class: 'small' }, 'When it is not true the step is skipped, and the canvas draws a dashed way around it. Several conditions (“and”) all have to be true.')));
}
function techTab(s, i) {
  const box = h('div', { class: 'stack' }), sqlBox = h('div', null, h('div', { class: 'muted small' }, 'Working out the SQL…'));
  const ta = h('textarea', { rows: 9, style: { fontFamily: 'ui-monospace,monospace' } }), msg = h('span', { class: 'small', style: { color: 'var(--bad)' } });
  ta.value = JSON.stringify(s, null, 2);
  const step = s, mine = CV;
  api.post('/studio/technical', { steps: tidySteps([s]) }).then(r => {
    if (mine !== CV || !sqlBox.isConnected) return;
    const sqls = r.steps[0] ? r.steps[0].sql : [];
    fill(sqlBox, !sqls.length ? h('div', { class: 'muted small' }, s.op === 'run_workflow' ? 'This step runs the steps of another workflow. Open it to see its SQL.' : 'This step runs no SQL.')
      : sqls.map(q => h('div', { style: { marginBottom: '10px' } }, h('div', { class: 'techlabel' }, h('span', null, q.title), h('button', { class: 'btn sm', type: 'button', onclick: () => copyText(q.sql) }, 'Copy')), h('pre', { class: 'code' }, q.sql),
        q.values.length ? h('ul', { class: 'vals' }, q.values.map(v => h('li', null, v))) : null, q.note ? h('div', { class: 'muted small' }, q.note) : null)));
  }).catch(() => { if (sqlBox.isConnected) fill(sqlBox, h('div', { class: 'muted small' }, 'The SQL could not be worked out right now.')); });
  box.append(h('div', null, h('div', { class: 'techlabel' }, h('span', null, 'SQL'), stepTag(s)), sqlBox),
    h('div', null, h('div', { class: 'techlabel' }, h('span', null, 'The step as JSON')), ta,
      h('div', { class: 'row', style: { marginTop: '6px' } }, h('button', { class: 'btn sm', type: 'button', onclick: () => {
        try { const v = JSON.parse(ta.value); if (!v || typeof v !== 'object' || !v.op) throw new Error('A step needs an "op".'); for (const k of Object.keys(step)) delete step[k]; Object.assign(step, v); commit(true); }
        catch (e) { msg.textContent = e.message; } } }, 'Apply JSON'), msg)),
    h('div', { class: 'muted small' }, 'Nothing here runs anything. The SQL is written out by the same rules the engine uses.'));
  return box;
}

// ----- Try it: a rehearsal that lights up the canvas -----
function clearRun() { if (CV) { CV.run = null; CV.tryOut = null; } }
function runFromTrace(r) {                                    // the top-level lines of the trace belong to the steps, in order
  const states = {}, top = (r.trace || []).filter(t => t.depth === 0); let k = 0, stopped = false;
  EW.work.steps.forEach((s, i) => {
    const t = top[k];
    if (t && t.op === s.op) { states[idAt(i)] = t.status; k++; if (t.status === 'failed') stopped = true; } else states[idAt(i)] = 'nr';
  });
  return { states, stopped };
}
function tryPanel() {
  const T = CV.try = CV.try || { people: null, as: '', fields: {} };
  const out = h('div', { class: 'stack' }), inputs = {};
  const asked = Object.entries(EW.work.entity_schema || {}).filter(([, f]) => f && typeof f === 'object' && !f.computed);
  const asBox = h('div', null, T.people ? '' : h('span', { class: 'muted small' }, 'Loading people…'));
  const run = h('button', { class: 'btn primary', type: 'button' }, icon('play', 'sm'), 'Run the rehearsal');
  const as = T.people && T.people.length ? sel(T.people.map(p => [p.id, p.name + ' (' + p.role + ')']), T.as || T.people[0].id, { onchange: e => { T.as = e.target.value; } }) : null;
  if (as) { T.as = as.value; asBox.append(field('Try it as', as)); }
  else if (T.people) asBox.append(notice('No one is linked to the chat yet, so there is no one to try it as.', 'bad'));
  else api.get('/studio/people').then(r => { T.people = r.people; if (CV.panel === 'try') renderInspector(); }).catch(e => { T.people = []; toast(e.message, 'bad'); if (CV.panel === 'try') renderInspector(); });
  const fieldsBox = h('div', { class: 'stack' }, asked.map(([k, f]) => {
    const ctl = Array.isArray(f.enum) && f.enum.length ? sel([['', 'Choose…'], ...f.enum.map(x => [x, x])], T.fields[k] || '', { onchange: e => { T.fields[k] = e.target.value; } }) : h('input', { type: 'text', value: T.fields[k] || '', placeholder: f.question || f.description || '', oninput: e => { T.fields[k] = e.target.value; } });
    inputs[k] = ctl;
    return field((f.label || pretty(k)) + (f.required ? ' *' : ''), ctl);
  }));
  if (CV.tryOut) fill(out, traceView(CV.tryOut));
  run.disabled = !as;
  run.addEventListener('click', async () => {
    run.disabled = true;
    try {
      const fields = {};
      Object.entries(T.fields).forEach(([k, v]) => { if (String(v).trim() !== '') fields[k] = String(v).trim(); });
      const r = await api.post('/studio/try', { steps: tidySteps(EW.work.steps), entity_schema: EW.work.entity_schema, fields, as_user: T.as, intent_key: EW.d.intent_key, name: EW.work.name, kind: EW.work.kind });
      CV.tryOut = r; CV.run = runFromTrace(r); renderNodes(); renderInspector();
    } catch (e) { fill(out, notice(e.message, 'bad')); run.disabled = false; }
  });
  return [insHead('look', 'play', 'Rehearsal', 'Try “' + EW.work.name + '”', 'Looking things up runs for real. Saving and sending are only described: nothing is saved and nobody is messaged.'),
    h('div', { class: 'ib' }, asBox, asked.length ? fieldsBox : h('div', { class: 'muted small' }, 'This workflow asks for nothing.'),
      h('div', { class: 'row' }, run, h('button', { class: 'btn ghost', type: 'button', onclick: () => { clearRun(); renderNodes(); renderInspector(); } }, 'Clear')), out)];
}

// ----- the bars, the problems banner, and the screen itself -----
function updateBar() {
  const dirty = isDirty();
  if (ui.save) { ui.save.disabled = !dirty; ui.save.textContent = dirty ? 'Save changes' : 'Saved'; }
  if (ui.discard) ui.discard.style.display = dirty ? '' : 'none';
  if (ui.undo) ui.undo.disabled = !EW.undo.length;
  if (ui.dirty) ui.dirty.style.display = dirty ? '' : 'none';
}
function refreshTitles() { renderNodes(); }
function drawProblems() {
  if (!CV || !EW) return;
  const all = EW.serverProblems ? EW.serverProblems : EW.check.errors;
  if (CV.banner) fill(CV.banner, all.length ? notice([h('div', null, h('b', null, EW.serverProblems ? 'These need fixing before it can be saved:' : plural(all.length, 'problem') + ' to fix before it can be saved:'), h('ul', { style: { margin: '4px 0 0', paddingLeft: '18px' } }, all.slice(0, 6).map(m => h('li', null, m))))], 'bad') : null);
  const i = CV.sel.size === 1 ? idxOf(primary()) : -1;
  if (CV.probEl) fill(CV.probEl, i >= 0 ? problemsFor(i + 1).map(([t, m]) => h('div', { class: 'prob ' + t }, m.replace(/^Step \d+( \([^)]*\))?:? ?/, ''))) : null);
  const sig = JSON.stringify(EW.check);
  if (sig !== CV.checkSig) { CV.checkSig = sig; renderNodes(); }     // the little "!" on a box
}
function legendPop(anchor) {
  const row = (c, t) => h('div', { class: 'lgrow' }, h('i', { style: { background: 'var(' + c + ')' } }), t);
  openPop(anchor, [h('div', { class: 'ml' }, 'Colour = what a step does'), row('--k-trigger', 'When… (what starts it)'), row('--k-look', 'Look up and check'), row('--k-save', 'Save changes'), row('--k-tell', 'Tell people'), row('--k-approve', 'Approvals (code or approver)'), row('--k-other', 'Other'), row('--k-block', 'Building block (stacked card)'), row('--k-ai', 'AI is only used where marked'),
    h('div', { class: 'ml' }, 'Wires and numbers'), h('div', { class: 'lgrow' }, 'Number on a box: when it runs'), h('div', { class: 'lgrow' }, 'Dot under a box: drag it onto another box to re-order'), h('div', { class: 'lgrow' }, 'Boxes side by side: the wire runs from the dot on the side'),
    h('div', { class: 'lgrow muted' }, 'Dashed way around: skipped unless “only if” is true'), h('div', { class: 'lgrow', style: { color: 'var(--k-stop)' } }, 'Red dashed exit: stops and says…'), h('div', { class: 'lgrow', style: { color: 'var(--k-approve)' } }, 'Pink bar: waits for a person')], { width: 340, up: true });
}
function drawEditor() {
  const root = ui.root, d = EW.d, read = isRead();
  if (!CV || CV.for !== EW) CV = newCanvas();
  CV.pal = null;
  ui.name = h('input', { class: 'nm', type: 'text', value: EW.work.name, 'aria-label': 'Workflow name', oninput: e => { EW.work.name = e.target.value; const cn = document.getElementById('crumbname'); if (cn) cn.textContent = e.target.value; commit(false); } });
  ui.save = h('button', { class: 'btn sm primary', type: 'button', onclick: save }, 'Saved');
  ui.discard = h('button', { class: 'btn sm', type: 'button', onclick: discard }, 'Discard');
  ui.undo = h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Undo the last change', 'data-tip': 'Undo the last change (Ctrl+Z)', onclick: undo }, icon('undo', 'sm'));
  ui.dirty = h('span', { class: 'badge warn' }, 'Unsaved');
  const power = h('span', null, d.is_active ? 'On' : 'Off');
  CV.banner = h('div', { class: 'cvprob' });
  const wg = svgEl('g', {});
  const marker = (id, cls) => svgEl('marker', { id, viewBox: '0 0 10 10', refX: '8.5', refY: '5', markerWidth: '8', markerHeight: '8', orient: 'auto' }, svgEl('path', { d: 'M1 1 L9 5 L1 9z', class: cls }));
  const wires = svgEl('svg', { class: 'wires', 'aria-hidden': 'true' }, svgEl('defs', {}, marker('ah', 'arrow'), marker('ah-ok', 'arrow ok')), wg);
  const nodesEl = h('div', { class: 'nodes' }), labels = h('div', { class: 'wlabels' });
  const stage = h('div', { class: 'stage' }, wires, nodesEl, labels), sizer = h('div', { class: 'sizer' }, stage);
  const cv = h('div', { class: 'cv', tabindex: '-1' }, sizer);
  const zval = h('span', { class: 'zv' }, '100%');
  const insp = h('aside', { class: 'insp closed', 'aria-label': 'Settings of the selected step' });
  Object.assign(CV, { el: cv, sizer, stage, wg, nodesEl, labels, zval, insp });
  wireCanvas(cv);
  const zb = (label, ic, fn) => h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': label, 'data-tip': label, onclick: fn }, icon(ic, 'sm'));
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Plain words or technical' },
    h('button', { type: 'button', class: CV.tech ? '' : 'on', onclick: e => { CV.tech = false; CV.reflow = true; seg.children[0].classList.add('on'); seg.children[1].classList.remove('on'); renderNodes(); } }, 'Plain words'),
    h('button', { type: 'button', class: CV.tech ? 'on' : '', onclick: e => { CV.tech = true; CV.reflow = true; seg.children[1].classList.add('on'); seg.children[0].classList.remove('on'); renderNodes(); } }, 'Technical'));
  const dock = h('div', { class: 'dock min' },
    h('button', { class: 'dhd', type: 'button', onclick: () => dock.classList.toggle('min') }, icon('spark'), h('span', null, 'Ask the assistant to change this flow'), icon('chevd', 'sm')),
    chatDock(read));
  const lbl = text => h('span', { class: 'tx' }, text);
  const head = h('div', { class: 'cvbar' },
    h('div', { class: 'titlechip' },
      h('a', { class: 'btn sm ghost icon', href: '#/workflows', 'aria-label': 'Back to all flows' }, icon('chevl', 'sm')), ui.name,
      badge(pretty(EW.work.kind || 'workflow'), EW.work.kind === 'block' ? 'teal' : 'violet'), badge('v' + d.version), ui.dirty,
      h('label', { class: 'row small flat', style: { gap: '6px' } }, switchEl(d.is_active, async v => { await api.post('/workflows/' + d.id + '/active', { is_active: v }); d.is_active = v; power.textContent = v ? 'On' : 'Off'; }), power)),
    h('div', { class: 'actbar' }, ui.undo,
      h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'Earlier versions', 'data-tip': 'Earlier versions: see or restore', onclick: () => { CV.sel = new Set(['trigger']); CV.panel = 'insp'; CV.ttab = 'hist'; renderNodes(); renderInspector(); } }, icon('hist', 'sm')),
      read ? null : h('button', { class: 'btn sm', type: 'button', onclick: () => { CV.panel = 'try'; renderInspector(); } }, icon('play', 'sm'), lbl('Try it')),
      ui.discard, ui.save));
  fill(root, h('div', { class: 'wsp' }, head,
    h('div', { class: 'wsprow' },
      paletteAside(),
      h('div', { class: 'cvwrap' },
        CV.banner, cv,
        h('div', { class: 'zoomb' }, zb('Zoom out', 'minus', () => setZoom(CV.zoom - 0.1)), zval, zb('Zoom in', 'plus', () => setZoom(CV.zoom + 0.1)), zb('Fit everything on screen', 'fit', () => fitView(true)),
          h('span', { class: 'vdiv' }),
          h('button', { class: 'btn sm ghost tidy', type: 'button', 'data-popkeep': '1', 'data-tip': 'Arrange the boxes: rows, by stage or a column (Shift+Alt+T)', onclick: e => tidyMenu(e.currentTarget) }, icon('tidy', 'sm'), lbl('Tidy up'), icon('chevd', 'xs')),
          h('span', { class: 'vdiv opt' }), seg, h('span', { class: 'vdiv' }),
          h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { CV.pal.classList.toggle('closed'); applyZoom(); } }, icon('panel', 'sm'), lbl('Steps')),
          h('button', { class: 'btn sm ghost', type: 'button', 'data-popkeep': '1', onclick: e => legendPop(e.currentTarget) }, icon('help', 'sm'), lbl('Legend'))),
        dock),
      insp)));
  const cn = document.getElementById('crumbname'); if (cn) cn.textContent = EW.work.name;
  renderNodes(); renderInspector(); updateBar(); prefetchBlocks();
  if (CV.panel === 'try') renderInspector();
  const arranged = !EW.saw && tidyFirst();
  fitView(!!arranged || rowish());                   // rows and stages were made to fit the screen: open them that way
}
// a flow that has never had a layout saved opens in rows that fit the screen, as Tidy up > Rows would make it (nothing is saved until someone moves or arranges a box)
function tidyFirst() {
  if (EW.mode || chain().length < 3 || !CV.el) return false;
  arrange('rows', { quiet: true });
  return true;
}
function drawPane() {
  if (!CV || !CV.nodesEl) return;
  const ok = new Set(chain());
  CV.sel = new Set([...CV.sel].filter(id => ok.has(id)));
  renderNodes(); renderInspector(); prefetchBlocks();
}
"""
