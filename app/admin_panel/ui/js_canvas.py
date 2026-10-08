JS = r"""
// ───────────────────────── the flow canvas ─────────────────────────
// Every step is a box you can drag anywhere. The wires and the numbers say what runs when, so where a
// box sits never changes the flow. What is shown comes from the workflow being edited (EW) and the
// step catalogue (ST); nothing about what a step means is written here.
// A step is drawn as a little tile (a coloured square with its name under it) or as a full card.
// A step can also be "parked": taken out of the flow (so it does not run) but kept on the canvas.
const CV_GAP = 84, CV_TOP = 48, CV_CX = 380;
const CV_GX = 64, CV_GY = 80, CV_X_ROWS = 60, CV_X_STAGE = 200, CV_PORT_Y = 28;   // full cards in rows: space between boxes, between rows, the left edge, and where a side wire meets a card
const CV_SQ = 68, CV_CW = 116;                           // little tiles: the square, and the whole tile (the name sits under the square)
const CV_STAGE = { trigger: 'Start', look: 'Look up and check', block: 'Building blocks', save: 'Save changes', tell: 'Tell people', approve: 'Approvals', other: 'Other steps' };
let CV = null;                                          // the view of the flow that is open (zoom, selection, what is expanded)
const CV_KIND = { 'Look up and check': 'look', 'Save changes': 'save', 'Tell people': 'tell', 'Approvals': 'approve', 'Other': 'other' };
const CV_ICON = { resolve_entity: 'search', conflict_check: 'stop', require_permission: 'shield', derive_field: 'bolt', compute: 'calc', 'db.insert_row': 'plus', 'db.update_row': 'edit', 'db.upsert_row': 'refresh', 'db.delete_row': 'trash', 'notify.user': 'mail', 'notify.whatsapp': 'chat', 'pdf.generate': 'file', otp_gate: 'key', approval_gate: 'usercheck', ai_price_interpret: 'spark', run_workflow: 'layers', 'case.categorize': 'tag', 'case.route': 'route', 'case.authorize': 'shield', 'case.add_parties': 'users', 'case.attach_photos': 'camera', 'notify.parties': 'send' };
// steps that stop the whole workflow with a message the person sees, and where that message is kept
const CV_STOPS = {
  conflict_check: ['error_message', 'It already exists, so it stops.'],
  require_permission: ['denied_message', 'The person is not allowed, so it stops.'],
  'case.authorize': ['denied_message', 'The person is not on the case, so it stops.'],
};
const CV_WAITS = { otp_gate: 'Waits for a one-time code', approval_gate: 'Waits for an approver' };
const CV_ST = { ran: '✓', would: '✎', skipped: '↷', failed: '✕', nr: '' };
const cvKey = s => s.op === 'run_workflow' ? 'block' : (CV_KIND[(catalogSpec(s.op) || {}).group] || 'other');
const cvIcon = op => CV_ICON[op] || 'bolt';
const cvStopText = s => { const k = CV_STOPS[s.op]; return k ? ((s.params || {})[k[0]] || k[1]) : null; };
const nodeW = () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nw'), 10) || 392;
const idAt = i => String(EW.ids[i]);
const idxOf = id => EW.ids.findIndex(x => String(x) === id);
const pidAt = k => String(EW.pids[k]);                 // parked steps have their own list, with ids of the same kind
const pidxOf = id => EW.pids.findIndex(x => String(x) === id);
const isParked = id => pidxOf(id) >= 0;
// a short name for a step in the messages: the building block's own name, or what kind of step it is
const stepName = s => { const f = s.op === 'run_workflow' ? ST.byKey[(s.params || {}).workflow] : null; return s.name || (f ? f.name : ((catalogSpec(s.op) || {}).label || describeStep(s))); };
const isRead = () => EW.d.workflow_type === 'read';
const chain = () => isRead() ? ['trigger', 'report'] : ['trigger', ...EW.ids.map(String)];
const wireIds = () => [...chain(), 'end'];
const primary = () => CV.sel.size === 1 ? [...CV.sel][0] : null;
// how steps are drawn: 'compact' (little tiles), 'detail' (full cards) or 'tech' (full cards with the technical settings); each browser remembers its choice
const cvPref = () => { const v = store.get('panel.cview'); return v === 'detail' || v === 'tech' ? v : 'compact'; };
const cvSize = () => cvPref() === 'compact' ? 'compact' : 'detailed';
function newCanvas() {
  const view = cvPref();
  return { for: EW, view, compact: view === 'compact', tech: view === 'tech', zoom: 1, auto: true, hm: {}, wm: {}, ex: {}, vh: {}, pm: { in: {}, out: {} }, reflow: false, sel: new Set(), panel: 'insp', itab: 'set', ttab: 'start', open: new Set(), peek: {}, loading: new Set(),
    palOpen: new Set(['act', 'act:Look up and check']), run: null, justAdded: null, G: null, frame: false, plusPts: [], inspKey: '', wbar: null, wbarT: 0 };
}
// room around the boxes: little tiles sit closer together than full cards
const colW = () => CV.compact ? CV_CW : nodeW();
const gapX = () => CV.compact ? 40 : CV_GX, gapY = () => CV.compact ? 72 : CV_GY, gapV = () => CV.compact ? 64 : CV_GAP;

// ----- where things sit -----
function posOf(id) {
  if (id === 'end') {
    const ids = chain(), last = ids[ids.length - 1], p = EW.pos[last];
    if (!p) return null;
    return { x: p.x + (CV.wm[last] || colW()) / 2 - (CV.wm.end || 190) / 2, y: p.y + (CV.hm[last] || 100) + gapV() * 0.75 };
  }
  return EW.pos[id] || null;
}
const wOf = id => CV.wm[id] || colW(), hOf = id => CV.hm[id] || 100, exOf = id => CV.ex[id] || 0, vOf = id => CV.vh[id] || hOf(id);
// where a wire leaves a box and enters the next: under and over them, or at the sides when boxes sit in a row
// (a little tile has its side dots on the square, a full card on its own edge)
const tiled = id => CV.compact && id !== 'end';
const sqOff = id => tiled(id) ? (wOf(id) - CV_SQ) / 2 : 0;
const portY = id => tiled(id) ? CV_SQ / 2 : CV_PORT_Y;
const outPt = id => { const p = posOf(id); return (CV.pm.out[id] === 'right') ? { x: p.x + wOf(id) - sqOff(id), y: p.y + portY(id) } : { x: p.x + wOf(id) / 2, y: p.y + hOf(id) + (tiled(id) ? 10 : 0) }; };   // a tile's bottom dot sits just under its name
const inPt = id => { const p = posOf(id); return (CV.pm.in[id] === 'left') ? { x: p.x + sqOff(id), y: p.y + portY(id) } : { x: p.x + wOf(id) / 2, y: p.y }; };
const toStage = (cx, cy) => { const r = CV.sizer.getBoundingClientRect(); return { x: (cx - r.left) / CV.zoom, y: (cy - r.top) / CV.zoom }; };

// ----- the boxes -----
const cvSec = (title, body) => h('div', { class: 'nd-tsec' }, h('div', { class: 'nd-tl' }, title), body);
// the little bar that shows above a box when the pointer is on it
function nodeBar(id, parked) {
  const b = (ic, label, fn, cls) => h('button', { class: 'nd-bb' + (cls ? ' ' + cls : ''), type: 'button', 'aria-label': label, title: label, onclick: e => { e.stopPropagation(); fn(); } }, icon(ic, 'sm'));
  return h('div', { class: 'nd-bar' }, parked
    ? [b('undo', 'Put back in the flow', () => cvUnpark(id)), b('trash', 'Delete', () => cvDel(id), 'del')]
    : [b('edit', 'Open', () => swOpen(id)), b('play', 'Test this step', () => swOpen(id, { test: true })), b('copy', 'Duplicate', () => cvDup(id)), b('trash', 'Delete', () => cvDel(id), 'del')]);
}
function cvTriggerNode() { return CV.compact ? cvTriggerTile() : cvTriggerCard(); }
function cvTriggerTile() {
  const w = EW.work, block = w.kind === 'block', action = w.kind === 'case_action', phrases = w.training_phrases || [];
  const name = block ? 'Run by other flows' : action ? 'A button on a case' : 'Starts when…';
  const sub = block ? '' : phrases.length ? '“' + phrases[0] + '”' : w.slash_command ? '/' + w.slash_command : '';
  return h('div', { class: 'nd nc trig k-trigger' + (CV.sel.has('trigger') ? ' sel' : ''), 'data-id': 'trigger', style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': 'What starts this flow' },
    h('span', { class: 'nd-ord trg' }, icon('bolt', 'xs')), h('span', { class: 'nd-port out' }),
    h('div', { class: 'nc-sq', title: 'What starts this flow' }, icon('bolt')),
    h('div', { class: 'nc-nm' }, name), sub ? h('div', { class: 'nc-sub' }, sub) : null);
}
function cvTriggerCard() {
  const w = EW.work, d = EW.d, block = w.kind === 'block', action = w.kind === 'case_action';
  const phrases = w.training_phrases || [];
  const who = d.granted_roles || [], party = ((w.settings && w.settings.who_can_use) || []).map(r => PARTY_PLAIN[r] || r);
  const asks = Object.entries(w.entity_schema || {}).filter(([, f]) => f && typeof f === 'object' && !f.computed);
  const title = block ? 'Run by other flows' : action ? 'A button on a case' : 'Someone says something like';
  const body = [];
  if (block) body.push(h('div', { class: 'nd-tsec muted small' }, d.used_in.length ? 'Used by: ' + d.used_in.map(u => u.name).join(', ') + '. Change it and they all change.' : 'Nothing runs it yet.'));
  else {
    if (phrases.length) body.push(h('div', { class: 'nd-tsec' }, h('div', { class: 'chips' }, phrases.slice(0, 5).map(t => h('span', { class: 'chip' }, '“' + t + '”')), phrases.length > 5 ? h('span', { class: 'chip sunk' }, '+' + (phrases.length - 5) + ' more') : null)));
    if (w.slash_command) body.push(cvSec('Or types', h('div', null, h('span', { class: 'chip mono' }, '/' + w.slash_command))));
    body.push(cvSec('Who can start it', who.length || party.length ? h('div', { class: 'chips' }, who.map(r => badge(r, 'brand')), party.map(r => h('span', { class: 'chip' }, r))) : h('span', { class: 'muted small' }, 'Nobody yet')));
    body.push(cvSec('Asks for', asks.length ? h('div', { class: 'chips' }, asks.map(([k, f]) => h('span', { class: 'chip' }, (f.label || pretty(k)) + (f.required || f.required_if ? ' *' : '')))) : h('span', { class: 'muted small' }, 'Nothing')));
    const gates = (w.gates || []).map(gateText);
    if (gates.length) body.push(cvSec('Safeguards', h('div', { class: 'chips' }, gates.map(t => h('span', { class: 'badge pink' }, icon('shield', 'xs'), t)))));
  }
  return h('div', { class: 'nd trig k-trigger' + (CV.sel.has('trigger') ? ' sel' : ''), 'data-id': 'trigger', style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': 'What starts this flow' },
    h('span', { class: 'nd-ord trg' }, icon('bolt', 'xs')), h('span', { class: 'nd-port out' }),
    h('div', { class: 'nd-h' }, h('span', { class: 'nd-gi' }, icon('bolt')), h('div', { class: 'grow' }, h('div', { class: 'nd-kind' }, 'When…'), h('div', { class: 'nd-t' }, title)), h('div', { class: 'nd-tags' }, h('span', { class: 'tag' }, 'Starts it'))),
    ...body, h('div', { style: { height: '4px' } }));
}
// a step in the flow (i is its place in the flow) or a parked step (k is its place in the parked list)
const cvStepNode = (s, i, k) => CV.compact ? cvStepTile(s, i, k) : cvStepCard(s, i, k);
function stepFacts(s, id) {
  const blk = s.op === 'run_workflow', flow = blk ? ST.byKey[(s.params || {}).workflow] : null;
  return { spec: catalogSpec(s.op), key: cvKey(s), blk, flow, wait: CV_WAITS[s.op], st: CV.run && CV.run.states[id],
    stops: [cvStopText(s), ...((flow && CV.peek[flow.id]) || []).map(cvStopText)].filter(Boolean) };
}
// the one line under a tile's name: the setting that matters most, short
function stepSub(s, f) {
  const p = s.params || {};
  if (f.blk) return 'Building block';
  const last = v => {                                          // who a message goes to: the person who asked, or the record it comes from (without "phone" or "id")
    if (typeof v !== 'string' || !v.startsWith('$')) return '';
    const parts = v.slice(1).split('.'), tail = parts[parts.length - 1];
    if (parts[0] === 'user') return 'the person who asked';
    return pretty(tail.replace(/(^|_)(phone|id)$/, '') || parts[0]).toLowerCase();   // reporter_id -> reporter, valid stays valid
  };
  const table = p.table ? tableWords(p) : '';
  switch (s.op) {
    case 'resolve_entity': return table + (p.match_column ? ' · by ' + pretty(p.match_column).toLowerCase() : p.match_columns ? ' · several columns' : '');
    case 'db.update_row': { const keys = Object.keys(p.set || {}); return table + (keys.length ? ' · ' + keys.slice(0, 2).map(k => pretty(k).toLowerCase()).join(', ') : ''); }
    case 'notify.user': return p.to ? 'to ' + (last(p.to) || '…') : '';
    case 'derive_field': return p.field ? pretty(p.field).toLowerCase() : '';
    case 'require_permission': return (p.any_of || []).join(' or ');
    default: return table;
  }
}
function cvStepTile(s, i, k) {
  const parked = k != null, id = parked ? pidAt(k) : idAt(i), f = stepFacts(s, id), p = s.params || {};
  const problems = parked ? 0 : problemsFor(i + 1).filter(x => x[0] === 'bad').length;
  const base = f.blk ? (f.flow ? f.flow.name : 'Building block (missing)') : (f.spec ? f.spec.label : s.op);
  const name = s.name || base;                                  // a name the person gave it, with what kind of step it is underneath
  const sub = parked ? 'Parked: does not run' : s.name ? base : stepSub(s, f);
  const bdg = [
    s.note ? h('span', { class: 'nc-b nc-b-note', title: s.note }, icon('file', 'xs')) : null,
    f.stops.length ? h('span', { class: 'nc-b nc-b-stop', title: 'Can stop the flow: ' + f.stops.slice(0, 3).join(' / ') }, icon('stop', 'xs')) : null,
    s.when ? h('span', { class: 'nc-b nc-b-if', title: 'Only if ' + condText(s.when) }, icon('branch', 'xs')) : null,
    f.wait ? h('span', { class: 'nc-b nc-b-wait', title: f.wait }, icon('pause', 'xs')) : null,
    isAiStep(s) ? h('span', { class: 'nc-b nc-b-ai', title: 'The AI is used in this step' }, icon('spark', 'xs')) : null];
  return h('div', { class: 'nd nc k-' + f.key + (f.blk ? ' blk' : '') + (parked ? ' parked' : '') + (CV.sel.has(id) ? ' sel' : ''), 'data-id': id, 'data-st': f.st || null, style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': (parked ? 'Parked, does not run: ' : '') + describeStep(s) },
    parked ? null : h('span', { class: 'nd-ord' }, i + 1), parked ? null : h('span', { class: 'nd-port in' }), parked ? null : h('span', { class: 'nd-port out' }),
    h('span', { class: 'nd-stb' }, f.st ? CV_ST[f.st] || '' : ''),
    problems ? h('span', { class: 'nd-bad', title: 'This step has a problem to fix' }, '!') : null,
    nodeBar(id, parked),
    h('button', { class: 'nd-more', type: 'button', 'aria-label': 'More for this step', 'data-tip': 'More: open, test, rename, duplicate, delete', onclick: e => { e.stopPropagation(); cvMenu(e); } }, icon('dots', 'xs')),
    h('div', { class: 'nc-sq', title: describeStep(s) }, icon(cvIcon(s.op)), bdg.some(Boolean) ? h('div', { class: 'nc-bdg' }, bdg) : null),
    h('div', { class: 'nc-nm' }, name), sub ? h('div', { class: 'nc-sub' }, sub) : null);
}
function cvStepCard(s, i, k) {
  const parked = k != null, id = parked ? pidAt(k) : idAt(i), f = stepFacts(s, id), spec = f.spec, key = f.key, blk = f.blk, flow = f.flow, wait = f.wait, st = f.st, n = flow ? flow.step_count : 0;
  const open = !!(flow && CV.open.has(flow.id));
  const problems = parked ? 0 : problemsFor(i + 1).filter(p => p[0] === 'bad').length;
  const stops = f.stops;
  const tag = blk ? h('span', { class: 'tag blk' }, 'Block') : isAiStep(s) ? h('span', { class: 'tag ai' }, '✦ AI') : h('span', { class: 'tag tcode' }, 'Code');
  const sub = s.name ? describeStep(s) : blk ? ((flow && flow.description) || 'Runs the steps of another flow') : (spec ? spec.label : s.op);
  return h('div', { class: 'nd k-' + key + (blk ? ' blk' : '') + (parked ? ' parked' : '') + (CV.sel.has(id) ? ' sel' : ''), 'data-id': id, 'data-st': st || null, style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': (parked ? 'Parked, does not run: ' : '') + describeStep(s) },
    parked ? null : h('span', { class: 'nd-ord' }, i + 1), parked ? null : h('span', { class: 'nd-port in' }), parked ? null : h('span', { class: 'nd-port out' }), h('span', { class: 'nd-stb' }, st ? CV_ST[st] || '' : ''),
    problems ? h('span', { class: 'nd-bad', title: 'This step has a problem to fix' }, '!') : null,
    nodeBar(id, parked),
    h('div', { class: 'nd-h' },
      h('span', { class: 'nd-gi' }, icon(cvIcon(s.op))),
      h('div', { class: 'grow' }, h('div', { class: 'nd-kind' }, blk ? 'Building block' : (spec ? spec.group : 'Step')), h('div', { class: 'nd-t' }, s.name || describeStep(s)), CV.tech ? null : h('div', { class: 'nd-s' }, sub)),
      h('div', { class: 'nd-tags' }, tag)),
    parked ? h('div', { class: 'nd-parkn' }, icon('unlink', 'sm'), 'Parked: it stays here but does not run') : null,
    CV.tech ? h('pre', { class: 'nd-tech' }, JSON.stringify({ op: s.op, params: s.params || {}, ...(s.when ? { when: s.when } : {}) }, null, 1).replace(/\n\s*/g, ' ')) : null,
    s.when ? h('div', { class: 'nd-cond' }, icon('branch', 'sm'), 'only if ' + condText(s.when)) : null,
    wait ? h('div', { class: 'nd-wait' }, icon('pause', 'sm'), wait) : null,
    s.note ? h('div', { class: 'nd-note' }, icon('file', 'sm'), s.note) : null,
    flow ? h('div', { class: 'nd-foot' },
      n ? h('button', { class: 'nd-exp', type: 'button', onclick: e => { e.stopPropagation(); cvToggle(flow); } }, icon(open ? 'chevd' : 'chevr', 'xs'), 'Inside · ' + plural(n, 'step')) : h('span', null, 'No steps yet'),
      h('span', null, '·'), h('a', { href: '#/workflows?w=' + flow.id, onclick: e => e.stopPropagation(), 'data-tip': 'Open the building block to change it' }, 'Open this block')) : null,
    open ? h('div', { class: 'nd-inside' }, CV.peek[flow.id]
      ? CV.peek[flow.id].map(x => h('div', { class: 'nd-irow k-' + cvKey(x) }, h('i'), h('span', null, describeStep(x)), cvStopText(x) ? h('em', null, 'can stop') : null, x.when ? h('em', { class: 'when' }, 'only if') : null))
      : h('div', { class: 'muted small' }, 'Loading…')) : null,
    stops.length && !parked ? h('div', { class: 'nd-exit' + (st === 'failed' ? ' lit' : '') }, h('div', { class: 'nd-xp' }, h('b', null, icon('stop', 'xs'), 'Stops'), stops.slice(0, 3).map(t => h('div', null, t)))) : null);
}
function cvReportNode() {
  const list = EW.work.response_format === 'list';
  if (CV.compact) {
    return h('div', { class: 'nd nc k-look' + (CV.sel.has('report') ? ' sel' : ''), 'data-id': 'report', style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': 'A saved report' },
      h('span', { class: 'nd-ord' }, '1'), h('span', { class: 'nd-port in' }), h('span', { class: 'nd-port out' }),
      h('div', { class: 'nc-sq', title: 'Looks things up with a saved query' }, icon('table'), list ? null : h('div', { class: 'nc-bdg' }, h('span', { class: 'nc-b nc-b-ai', title: 'The AI words the answer' }, icon('spark', 'xs')))),
      h('div', { class: 'nc-nm' }, 'A saved report'), h('div', { class: 'nc-sub' }, list ? 'Rows shown as stored' : 'Worded by the AI'));
  }
  return h('div', { class: 'nd k-look' + (CV.sel.has('report') ? ' sel' : ''), 'data-id': 'report', style: { visibility: 'hidden' }, tabindex: 0, role: 'button' },
    h('span', { class: 'nd-ord' }, '1'), h('span', { class: 'nd-port in' }), h('span', { class: 'nd-port out' }),
    h('div', { class: 'nd-h' }, h('span', { class: 'nd-gi' }, icon('table')), h('div', { class: 'grow' }, h('div', { class: 'nd-kind' }, 'A saved report'), h('div', { class: 'nd-t' }, 'Looks things up with a saved query'), h('div', { class: 'nd-s' }, list ? 'Every row shown exactly as stored' : 'The AI words the answer')),
      h('div', { class: 'nd-tags' }, list ? h('span', { class: 'tag tcode' }, 'Code') : h('span', { class: 'tag ai' }, '✦ AI'))));
}
function cvEndNode() {
  const block = EW.work.kind === 'block';
  if (CV.compact && !isRead() && !oneStepOnly()) {           // a dashed square at the end of the flow: click it to add a step
    const add = el => cvOpenAdd(EW.work.steps.length, el);
    return h('div', { class: 'nd nc nc-end', role: 'button', tabindex: 0, 'data-id': 'end', 'data-popkeep': '1', style: { visibility: 'hidden' }, 'aria-label': 'Add a step at the end', title: (block ? 'Done: carries on with the flow that ran it' : 'Done: tells the person') + '. Click to add a step here.',
      onclick: e => { e.stopPropagation(); add(e.currentTarget); }, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); add(e.currentTarget); } } },
      h('span', { class: 'nd-port in' }), h('div', { class: 'nc-sq' }, icon('plus')), h('div', { class: 'nc-nm' }, 'Add a step'), h('div', { class: 'nc-sub' }, block ? 'Then it carries on' : 'Then it tells the person'));
  }
  return h('div', { class: 'nd end', 'data-id': 'end', style: { visibility: 'hidden' } }, h('span', { class: 'nd-port in' }), icon('check', 'sm'),
    block ? 'Done: carries on with the flow that ran it' : 'Done: tells the person');
}
// opening a block shows the steps inside it (fetched once)
async function cvToggle(flow) {
  if (CV.open.has(flow.id)) CV.open.delete(flow.id); else CV.open.add(flow.id);
  CV.reflow = true;
  renderNodes();
  if (CV.open.has(flow.id) && !CV.peek[flow.id]) await cvPeek(flow);
}
async function cvPeek(flow) {
  if (CV.peek[flow.id] || CV.loading.has(flow.id)) return;
  CV.loading.add(flow.id);
  const mine = CV;
  try { mine.peek[flow.id] = (await api.get('/workflows/' + flow.id)).steps || []; }
  catch (e) { mine.peek[flow.id] = []; }
  mine.loading.delete(flow.id);
  if (mine === CV) renderNodes();
}
// the steps inside blocks can stop the whole workflow, so they are fetched up front to draw the red "Stops" label
function prefetchBlocks() {
  [...EW.work.steps, ...EW.work.parked.map(p => p.step)].forEach(s => { const f = s.op === 'run_workflow' ? ST.byKey[(s.params || {}).workflow] : null; if (f && f.step_count) cvPeek(f); });
}

function renderNodes() {
  if (!CV || !CV.nodesEl) return;
  const prev = { ...CV.hm }, els = [cvTriggerNode()];
  if (isRead()) els.push(cvReportNode()); else EW.work.steps.forEach((s, i) => els.push(cvStepNode(s, i)));
  EW.work.parked.forEach((p, k) => els.push(cvStepNode(p.step, -1, k)));
  els.push(cvEndNode());
  fill(CV.nodesEl, els);
  CV.el.classList.toggle('rowmode', rowish());
  CV.el.classList.toggle('compact', CV.compact);
  hideWireBar();
  layoutAfterRender(prev);
}
// the key that says which boxes there are and in what order: when it changes, Rows and By stage arrange themselves again
const arrKey = () => chain().join() + '|' + EW.pids.join();
const geoNow = () => geoKey([...chain(), ...EW.pids.map(String)]);
function layoutAfterRender(prev) {
  const NW = colW(), ids = chain(), clean = snapJSON() === EW.last;
  measureNodes();
  ids.forEach((id, k) => {                                   // a new box goes under the one before it
    if (EW.pos[id]) return;
    if (k === 0) EW.pos[id] = { x: CV_CX - NW / 2, y: CV_TOP };
    else { const p = EW.pos[ids[k - 1]]; EW.pos[id] = { x: p.x, y: p.y + (CV.hm[ids[k - 1]] || 100) + gapV() }; }
  });
  const lost = EW.pids.map(String).filter(id => !EW.pos[id]);   // a parked box with no place yet waits under the flow
  if (lost.length) {
    let low = 0, left = 1e9;
    ids.forEach(o => { const q = EW.pos[o]; if (q) { low = Math.max(low, q.y + vOf(o)); left = Math.min(left, q.x); } });
    let x = left < 1e8 ? left : CV_X_ROWS;
    lost.forEach(id => { EW.pos[id] = { x, y: low + 90 }; x += wOf(id) + gapX(); });
  }
  if (CV.justAdded) {                                        // a box added in the middle pushes the ones below it down
    const k = ids.indexOf(CV.justAdded);
    if (k > 0 && k < ids.length - 1) {
      const n = EW.pos[ids[k]], m = EW.pos[ids[k + 1]], need = n.y + CV.hm[ids[k]] + gapV();
      if (Math.abs(m.x - n.x) < NW && m.y < need) { const d = need - m.y; for (let j = k + 1; j < ids.length; j++) EW.pos[ids[j]].y += d; }
    }
    CV.justAdded = null;
  }
  ids.forEach((id, k) => {                                   // a box that grew or shrank (opened block, technical view) moves the ones below it
    const old = prev[id], now = CV.hm[id];
    if (old == null || old === now) return;
    const d = now - old, p = EW.pos[id];
    for (let j = k + 1; j < ids.length; j++) { const q = EW.pos[ids[j]]; if (q.y >= p.y + old - 4 && Math.abs(q.x - p.x) < NW) q.y += d; }
  });
  if (rowish()) {                                            // Rows and By stage stay tidy: the boxes are arranged again when steps are added, removed, parked or re-ordered
    const sk = arrKey(), gk = geoNow();
    if (EW.arrIds == null) { EW.arrIds = sk; EW.arrGeo = gk; }
    else if (EW.arrIds !== sk || CV.reflow || (EW.autoArr && EW.arrGeo !== gk)) {
      const fresh = EW.autoArr && EW.arrIds === sk && !CV.reflow;   // only the sizes changed (the "Stops" notes arrived) and nobody placed anything by hand: pick the row length again and fit the screen again
      const pl = planFor(EW.mode, fresh ? null : EW.arrCols);
      Object.keys(pl.pos).forEach(id => { EW.pos[id] = pl.pos[id]; });
      if (fresh) { EW.arrCols = pl.cols; if (CV.auto) fitView(true); }
      EW.arrIds = sk; EW.arrGeo = gk; CV.reflow = false;
    }
  }
  if (clean) EW.last = snapJSON();                           // where boxes were first put is not a change
  positionNodes(); drawWires(); applyZoom();
}
function positionNodes() {
  [...CV.nodesEl.children].forEach(el => { const p = posOf(el.dataset.id); if (!p) return; el.style.left = p.x + 'px'; el.style.top = p.y + 'px'; el.style.visibility = 'visible'; });
}
// how one wire runs from a box to the next: along a row (h), down and across to the next row (e), or straight down (v)
function connMode(a, b) {
  const pa = posOf(a), pb = posOf(b);
  if (!pa || !pb) return 'v';
  const wa = wOf(a), ha = hOf(a), wb = wOf(b), hb = hOf(b);
  if (pb.x >= pa.x + wa + 30 && pb.y < pa.y + ha && pb.y + hb > pa.y) return 'h';
  if (pb.y >= pa.y + ha + 30 && Math.abs((pb.x + wb / 2) - (pa.x + wa / 2)) > colW() * 0.6) return 'e';
  return 'v';
}
function vPath(A, B) {
  const dy = Math.max(40, Math.min(160, Math.abs(B.y - A.y) / 2));
  return { d: 'M' + A.x + ' ' + A.y + ' C' + A.x + ' ' + (A.y + dy) + ', ' + B.x + ' ' + (B.y - dy) + ', ' + B.x + ' ' + B.y, mx: (A.x + B.x) / 2, my: (A.y + B.y) / 2 };
}
function hPath(A, B) {
  const dx = Math.max(28, Math.min(160, Math.abs(B.x - A.x) / 2));
  return { d: 'M' + A.x + ' ' + A.y + ' C' + (A.x + dx) + ' ' + A.y + ', ' + (B.x - dx) + ' ' + B.y + ', ' + B.x + ' ' + B.y, mx: (A.x + B.x) / 2, my: (A.y + B.y) / 2 };
}
// down out of a box, along the free space under its row, and down into the box in the next row
function ePath(a, b, A, B) {
  let low = A.y;
  [...chain(), 'end'].forEach(id => {
    if (id === a || id === b) return;
    const p = posOf(id); if (!p) return;
    const bottom = p.y + vOf(id);
    if (p.x < Math.max(A.x, B.x) + 20 && p.x + wOf(id) + exOf(id) > Math.min(A.x, B.x) - 20 && p.y < B.y - 4 && bottom > A.y - hOf(a)) low = Math.max(low, bottom);
  });
  const ym = low + 26, r = 14;
  if (ym > B.y - 22) return vPath(A, B);
  const s = B.x > A.x ? 1 : -1;
  return { d: 'M' + A.x + ' ' + A.y + ' V' + (ym - r) + ' Q' + A.x + ' ' + ym + ' ' + (A.x + s * r) + ' ' + ym + ' H' + (B.x - s * r) + ' Q' + B.x + ' ' + ym + ' ' + B.x + ' ' + (ym + r) + ' V' + B.y, mx: (A.x + B.x) / 2, my: ym };
}
// the bar that appears on a wire when the pointer is on it: add a step here, or remove the link (park the next step)
function wireHit(P, info) {
  const el = svgEl('path', { class: 'wirehit', d: P.d });
  el._info = info;
  el.addEventListener('pointerenter', () => { if (!CV.G) showWireBar(info); });
  el.addEventListener('pointerleave', hideWireBarSoon);
  return el;
}
function showWireBar(info) {
  const bar = CV && CV.wbar;
  if (!bar || !bar.isConnected) return;
  clearTimeout(CV.wbarT);
  const b = (ic, label, fn) => h('button', { class: 'nd-bb', type: 'button', 'aria-label': label, title: label, onclick: e => { e.stopPropagation(); const r = e.currentTarget.getBoundingClientRect(); hideWireBar(); fn({ getBoundingClientRect: () => r }); } }, icon(ic, 'sm'));
  fill(bar, b('plus', 'Add a step here', anchor => cvOpenAdd(info.at, anchor)),
    info.next ? b('unlink', 'Remove link: the next step is parked (it stays on the canvas but does not run)', () => cvPark(info.next)) : null);
  bar.style.left = info.x + 'px'; bar.style.top = info.y + 'px'; bar.style.display = 'flex';
}
function hideWireBar() { if (!CV) return; clearTimeout(CV.wbarT); if (CV.wbar) CV.wbar.style.display = 'none'; }
function hideWireBarSoon() { if (!CV) return; clearTimeout(CV.wbarT); CV.wbarT = setTimeout(hideWireBar, 220); }
function drawWires() {
  const ids = wireIds(), run = CV.run, okSt = ['ran', 'would', 'skipped'];
  const stateOf = id => run && run.states[id];
  const completed = id => id === 'trigger' || okSt.includes(stateOf(id));
  const began = id => id === 'end' ? !run.stopped : ['ran', 'would', 'skipped', 'failed'].includes(stateOf(id));
  const paths = [], hits = [], labels = [], modes = [];
  CV.plusPts = [];
  CV.pm = { in: {}, out: {} };                               // boxes side by side: the wire leaves from the side dot
  for (let i = 0; i < ids.length - 1; i++) {
    const m = connMode(ids[i], ids[i + 1]); modes.push(m);
    if (m === 'h') { CV.pm.out[ids[i]] = 'right'; CV.pm.in[ids[i + 1]] = 'left'; }
  }
  [...CV.nodesEl.children].forEach(el => { el.dataset.pin = CV.pm.in[el.dataset.id] || 'top'; el.dataset.pout = CV.pm.out[el.dataset.id] || 'bottom'; });
  for (let i = 0; i < ids.length - 1; i++) {
    const a = ids[i], b = ids[i + 1];
    if (!posOf(a) || !posOf(b)) continue;
    const A = outPt(a), B = inPt(b), m = modes[i], P = m === 'h' ? hPath(A, B) : m === 'e' ? ePath(a, b, A, B) : vPath(A, B);
    const lit = run && completed(a) && began(b);
    paths.push(svgEl('path', { class: 'wire' + (lit ? ' done' : ''), d: P.d, 'marker-end': 'url(#' + (lit ? 'ah-ok' : 'ah') + ')' }));
    if (!run && !isRead() && !oneStepOnly()) {
      const at = a === 'trigger' ? 0 : (b === 'end' ? EW.ids.length : idxOf(b));
      CV.plusPts.push({ at, x: P.mx, y: P.my });
      hits.push(wireHit(P, { at, x: P.mx, y: P.my, next: b === 'end' ? null : b }));
    }
  }
  const bulge = colW() / 2 + 110;                            // "only if": a dashed way around the box
  EW.work.steps.forEach((s, i) => {
    if (!s.when) return;
    const k = ids.indexOf(idAt(i)), a = ids[k - 1], b = ids[k + 1];
    if (!a || !b || !posOf(a) || !posOf(b)) return;
    const A = outPt(a), B = inPt(b), m1 = modes[k - 1], m2 = modes[k];
    if (m1 === 'h' && m2 === 'h') {                          // boxes in a row: an arch over the box
      const up = CV.compact ? 92 : Math.max(80, vOf(ids[k]) * 0.5 + 50);
      paths.push(svgEl('path', { class: 'wire skipw', d: 'M' + A.x + ' ' + A.y + ' C' + A.x + ' ' + (A.y - up) + ', ' + B.x + ' ' + (B.y - up) + ', ' + B.x + ' ' + B.y, 'marker-end': 'url(#ah)' }));
      labels.push(h('span', { class: 'skiptxt c', style: { left: ((A.x + B.x) / 2) + 'px', top: (Math.min(A.y, B.y) - up * 0.75 - 2) + 'px' } }, 'otherwise skipped'));
    } else if (m1 === 'v' && m2 === 'v') {
      paths.push(svgEl('path', { class: 'wire skipw', d: 'M' + A.x + ' ' + A.y + ' C' + (A.x - bulge) + ' ' + (A.y + 50) + ', ' + (B.x - bulge) + ' ' + (B.y - 50) + ', ' + B.x + ' ' + B.y, 'marker-end': 'url(#ah)' }));
      labels.push(h('span', { class: 'skiptxt', style: { left: ((A.x + B.x) / 2 - bulge * 0.75 - 6) + 'px', top: ((A.y + B.y) / 2) + 'px' } }, 'otherwise skipped'));
    }
  });
  if (EW.mode === 'stage') {                                 // the name of each stage, left of its first box
    let prev = null;
    chain().forEach(id => {
      const k = stageOf(id), p = posOf(id);
      if (k !== prev && p) labels.push(h('div', { class: 'stglbl k-' + k, style: { left: (p.x - 172) + 'px', top: (p.y + 6) + 'px' } }, CV_STAGE[k]));
      prev = k;
    });
  }
  fill(CV.wg, [...paths, ...hits]); fill(CV.labels, labels);
}
function applyZoom() {
  const z = CV.zoom, cv = CV.el; let R = 0, B = 0;
  [...CV.nodesEl.children].forEach(el => { const p = posOf(el.dataset.id); if (!p) return; R = Math.max(R, p.x + el.offsetWidth + (el.querySelector('.nd-exit') ? 290 : 30)); B = Math.max(B, p.y + el.offsetHeight); });
  const W = Math.max(R + 140, cv.clientWidth / z), H = Math.max(B + 300, cv.clientHeight / z);
  CV.stage.style.width = W + 'px'; CV.stage.style.height = H + 'px'; CV.stage.style.transform = 'scale(' + z + ')';
  CV.stage.style.setProperty('--zi', String(Math.round(Math.max(1, Math.min(2.2, 1 / z)) * 100) / 100));   // the little bars keep a readable size when zoomed out
  CV.sizer.style.width = W * z + 'px'; CV.sizer.style.height = H * z + 'px'; CV.sizer.style.backgroundSize = (22 * z) + 'px ' + (22 * z) + 'px';
  CV.zval.textContent = Math.round(z * 100) + '%';
}
function setZoom(z, cx, cy) {
  const cv = CV.el, r = cv.getBoundingClientRect(), z0 = CV.zoom;
  z = Math.max(0.4, Math.min(1.6, Math.round(z * 100) / 100));
  const px = (cx == null ? r.left + r.width / 2 : cx) - r.left, py = (cy == null ? r.top + r.height / 2 : cy) - r.top;
  const sx = (cv.scrollLeft + px) / z0, sy = (cv.scrollTop + py) / z0;
  CV.zoom = z; CV.auto = false; applyZoom(); cv.scrollLeft = sx * z - px; cv.scrollTop = sy * z - py;
}
function bounds() {
  let L = 1e9, T = 1e9, R = 0, B = 0;
  [...CV.nodesEl.children].forEach(el => { const p = posOf(el.dataset.id); if (!p) return; L = Math.min(L, p.x); T = Math.min(T, p.y); R = Math.max(R, p.x + el.offsetWidth + (el.querySelector('.nd-exit') ? 270 : 0)); B = Math.max(B, p.y + el.offsetHeight); });
  if (EW.mode === 'stage' && L < 1e8) L -= 180;               // the stage names sit left of the boxes
  return { L, T, R, B };
}
// Fit: everything on screen. Opening a flow only fits the width, so the text stays readable and a long flow scrolls.
function fitView(whole) {
  const cv = CV.el, b = bounds();
  if (b.L > 1e8) return;
  const byWidth = cv.clientWidth / (b.R - b.L + 120), byHeight = cv.clientHeight / (b.B - b.T + 200);
  const z = Math.max(0.4, Math.min(1.1, whole ? Math.min(byWidth, byHeight) : Math.min(1, byWidth)));
  CV.zoom = Math.round(z * 100) / 100; CV.auto = true; applyZoom();
  cv.scrollLeft = Math.max(0, (b.L - 60) * CV.zoom); cv.scrollTop = Math.max(0, (b.T - 90) * CV.zoom);
}
function schedFrame() {
  if (document.hidden) { positionNodes(); drawWires(); applyZoom(); return; }
  if (CV.frame) return;
  CV.frame = true;
  requestAnimationFrame(() => { CV.frame = false; if (CV && CV.nodesEl) { positionNodes(); drawWires(); applyZoom(); } });
}
// on a phone-sized screen the panel covers the lower part of the canvas: bring the chosen box into the upper part
function revealAbove(id) {
  if (innerWidth > 700 || !CV.el) return;
  const p = posOf(id);
  if (p) CV.el.scrollTo({ top: Math.max(0, p.y * CV.zoom - 24), behavior: 'smooth' });
}
function scrollToNode(id) {
  const el = CV.nodesEl && CV.nodesEl.querySelector('[data-id="' + id + '"]');
  if (el) el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
}

// ----- Tidy up: Rows (fit the screen), By stage, or one Column. Only where the boxes sit changes, never what runs when -----
const rowish = () => !!EW && (EW.mode === 'rows' || EW.mode === 'stage');
const stageOf = id => id === 'trigger' ? 'trigger' : id === 'report' ? 'look' : cvKey(EW.work.steps[idxOf(id)]);
function measureNodes() {
  [...CV.nodesEl.children].forEach(el => {
    const id = el.dataset.id, x = el.querySelector('.nd-exit');
    CV.hm[id] = el.offsetHeight; CV.wm[id] = el.offsetWidth;
    CV.ex[id] = x ? x.offsetWidth : 0;                         // the red "Stops" note sits right of its box: room is kept for it
    CV.vh[id] = x ? Math.max(el.offsetHeight, x.offsetTop + x.offsetHeight) : el.offsetHeight;
  });
}
// boxes in order, and where a new row has to start
function rowItems(ids) {
  const hs = ids.filter(id => id !== 'trigger').map(vOf).sort((a, b) => a - b), med = hs.length ? hs[hs.length >> 1] : 100;
  const alone = ids.length > 2 && vOf('trigger') > med * 1.6;   // a tall "When…" box gets its own row
  return ids.map((id, i) => ({ id, brk: alone && i === 1 }));
}
function stageItems(ids) {                                    // steps of the same kind that follow each other share a row
  let prev = null;
  return ids.map(id => { const k = stageOf(id), brk = prev !== null && k !== prev; prev = k; return { id, brk }; });
}
function gridPlan(items, cols, x0) {
  const pos = {}, rows = [], gx = gapX(), gy = gapY(); let row = [];
  items.forEach(it => { if (row.length && (row.length >= cols || it.brk)) { rows.push(row); row = []; } row.push(it.id); });
  if (row.length) rows.push(row);
  let y = CV_TOP, W = 0;
  rows.forEach(r => {
    let x = x0, rh = 0;
    r.forEach(id => { pos[id] = { x, y }; rh = Math.max(rh, vOf(id)); x += wOf(id) + exOf(id) + gx; });
    W = Math.max(W, x - gx); y += rh + gy;
  });
  if (EW.pids.length) {                                        // parked boxes wait in a row of their own, under the flow
    const limit = Math.max(W, x0 + 4 * (wOf(pidAt(0)) + gx));
    let x = x0, rh = 0; y += 36;
    EW.pids.forEach(pid => {
      const id = String(pid);
      if (x > x0 && x + wOf(id) > limit) { x = x0; y += rh + gy; rh = 0; }
      pos[id] = { x, y }; rh = Math.max(rh, vOf(id)); x += wOf(id) + exOf(id) + gx; W = Math.max(W, x - gx);
    });
    y += rh + gy;
  }
  return { pos, cols, W: W + 80, H: y + 80 };
}
// the number of boxes per row that lets the whole flow be shown biggest; a tie goes to fewer boxes per row
function bestPlan(items, x0, maxCols) {
  const cw = CV.el.clientWidth, ch = Math.max(240, CV.el.clientHeight - 70);
  let best = null;
  for (let c = 1; c <= Math.max(1, Math.min(maxCols, items.length)); c++) {
    const p = gridPlan(items, c, x0); p.z = Math.min(1, cw / p.W, ch / p.H);
    if (!best || p.z > best.z * 1.03) best = p;
  }
  return best;
}
function planFor(mode, cols) {
  const ids = chain(), items = mode === 'stage' ? stageItems(ids) : rowItems(ids), x0 = mode === 'stage' ? CV_X_STAGE : CV_X_ROWS;
  return cols ? gridPlan(items, cols, x0) : bestPlan(items, x0, CV.compact ? (mode === 'stage' ? 6 : 8) : (mode === 'stage' ? 5 : 6));
}
const ARRANGED = { rows: 'Arranged in rows.', stage: 'Arranged by stage.', column: 'Arranged in one column.' };
async function arrange(mode, opts) {
  opts = opts || {};
  const mine = CV;
  if (!opts.quiet) { for (let i = 0; i < 20 && CV.loading.size; i++) await new Promise(r => setTimeout(r, 100)); }   // let the "Stops" notes load first: they take room
  if (mine !== CV || !CV.el || !CV.el.isConnected) return;
  const ids = chain();
  EW.mode = mode; CV.el.classList.toggle('rowmode', rowish()); measureNodes();
  let plan;
  if (mode === 'column') {
    const pos = {}; let y = CV_TOP, py = CV_TOP;
    ids.forEach(id => { pos[id] = { x: CV_CX - wOf(id) / 2, y }; y += hOf(id) + gapV(); });
    EW.pids.forEach(pid => { const id = String(pid); pos[id] = { x: CV_CX + colW() / 2 + (CV.compact ? 150 : 330), y: py }; py += hOf(id) + gapY(); });   // parked boxes stack at the right
    plan = { pos, cols: null };
  }
  else plan = planFor(mode, null);
  EW.arrCols = plan.cols; EW.arrIds = arrKey(); EW.arrGeo = geoNow(); EW.autoArr = true;
  const same = Object.keys(plan.pos).every(id => EW.pos[id] && Math.abs(EW.pos[id].x - plan.pos[id].x) < 1 && Math.abs(EW.pos[id].y - plan.pos[id].y) < 1);
  if (opts.quiet) { Object.keys(plan.pos).forEach(id => { EW.pos[id] = plan.pos[id]; }); EW.last = snapJSON(); positionNodes(); drawWires(); applyZoom(); return; }
  if (same) { drawWires(); fitView(mode !== 'column'); commitLayout(); toast('Already arranged like this.'); return; }
  animateTo(plan.pos, () => { if (mode === 'column') CV.el.scrollTo({ left: 0, top: 0, behavior: 'smooth' }); else fitView(true); toast(ARRANGED[mode] + ' The flow still runs in the same order.'); });
}
const geoKey = ids => ids.map(id => vOf(id) + ':' + exOf(id)).join();
function animateTo(to, after) {
  const from = {}; Object.keys(to).forEach(id => { from[id] = { ...(EW.pos[id] || to[id]) }; });
  const done = () => { commitLayout(); if (after) after(); };
  const set = e => { Object.keys(to).forEach(id => { EW.pos[id] = { x: from[id].x + (to[id].x - from[id].x) * e, y: from[id].y + (to[id].y - from[id].y) * e }; }); positionNodes(); drawWires(); applyZoom(); };
  if (document.hidden) { set(1); done(); return; }
  const t0 = performance.now(), dur = 420;
  const step = now => { const t = Math.min(1, (now - t0) / dur); set(1 - Math.pow(1 - t, 3)); if (t < 1) requestAnimationFrame(step); else done(); };
  requestAnimationFrame(step);
}
function tidyMenu(anchor) {
  const thumb = m => {
    const r = (x, y, w, hh) => svgEl('rect', { x, y, width: w, height: hh, rx: 1.2 });
    const kids = m === 'column' ? [r(9, 1, 10, 4.5), r(9, 7.75, 10, 4.5), r(9, 14.5, 10, 4.5)]
      : m === 'rows' ? [r(1, 3, 7.5, 5), r(10.25, 3, 7.5, 5), r(19.5, 3, 7.5, 5), r(1, 12, 7.5, 5), r(10.25, 12, 7.5, 5)]
      : [r(9, 1, 10, 4), r(1, 7.5, 7.5, 5), r(10.25, 7.5, 7.5, 5), r(19.5, 7.5, 7.5, 5), r(1, 15, 7.5, 4), r(10.25, 15, 7.5, 4)];
    return svgEl('svg', { class: 'tthumb', viewBox: '0 0 28 20', width: '28', height: '20', 'aria-hidden': 'true' }, ...kids);
  };
  const item = (m, name, text) => h('button', { class: 'mi' + (EW.mode === m ? ' on' : ''), type: 'button', onclick: () => { closePop(); arrange(m); } },
    thumb(m), h('span', { class: 'grow' }, name, h('small', null, text)), EW.mode === m ? icon('check', 'sm') : null);
  openPop(anchor, [h('div', { class: 'ml' }, 'Arrange the boxes'),
    item('rows', 'Rows', 'Left to right, then down. Fits the screen.'),
    item('stage', 'By stage', 'Rows grouped by what the steps do.'),
    item('column', 'Column', 'One long column, top to bottom.'),
    h('div', { class: 'muted small', style: { padding: '6px 10px 4px' } }, 'The order the steps run in never changes. Only the places do.')], { width: 330, up: true });
}

// ----- the three ways to draw the steps: Compact (little tiles), Detailed (full cards), Technical (cards with the settings) -----
// Where boxes sit is kept for each size on its own (tiles and cards are not the same size); the other size is arranged in rows the first time.
function setView(v) {
  if (!CV || CV.view === v) return;
  const resize = CV.compact !== (v === 'compact');
  store.set('panel.cview', v);
  CV.view = v; CV.tech = v === 'tech'; CV.compact = v === 'compact';
  syncSeg();
  hideWireBar();
  if (!resize) { CV.reflow = true; renderNodes(); return; }
  EW.stash[EW.size] = { pos: clone(EW.pos), mode: EW.mode, cols: EW.arrCols };
  EW.size = CV.compact ? 'compact' : 'detailed';
  const back = EW.stash[EW.size];
  EW.pos = back ? back.pos : {}; EW.mode = back ? back.mode : ''; EW.arrCols = back ? back.cols : null; EW.arrIds = null; EW.autoArr = false;
  EW.last = snapJSON();                                          // changing how the boxes are drawn is not a change to the flow
  CV.hm = {}; CV.wm = {}; CV.ex = {}; CV.vh = {};
  renderNodes();
  if (!back) arrange('rows', { quiet: true });
  fitView(true);
}
function syncSeg() {
  const seg = CV && CV.seg;
  if (seg) [...seg.children].forEach(b => { b.classList.toggle('on', b.dataset.view === CV.view); if (b.dataset.view === 'tech') b.hidden = CV.view !== 'tech'; });   // the technical view is only offered in ⋯ More, until someone is in it
}

// ----- moving boxes, moving the canvas, drawing wires -----
function wireCanvas(cv) {
  cv.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    if (e.target.closest('.plus,button,input,select,textarea,a')) return;
    if (!e.target.closest('.wbar')) hideWireBar();
    const node = e.target.closest('.nd');
    if (node && e.target.closest('.nd-port.out') && node.dataset.id !== 'end') { startWire(e, node); return; }
    if (node && node.dataset.id !== 'end') {
      const id = node.dataset.id, multi = e.shiftKey || e.ctrlKey || e.metaKey, group = CV.sel.has(id) ? [...CV.sel] : [id];
      CV.G = { type: 'node', id, sx: e.clientX, sy: e.clientY, moved: false, multi, wasSel: CV.sel.has(id), group, orig: Object.fromEntries(group.map(g => [g, { ...EW.pos[g] }])) };
      cv.setPointerCapture(e.pointerId); e.preventDefault(); return;
    }
    if (!node) { CV.G = { type: 'pan', sx: e.clientX, sy: e.clientY, sl: cv.scrollLeft, st: cv.scrollTop, moved: false }; cv.setPointerCapture(e.pointerId); }
  });
  cv.addEventListener('pointermove', e => {
    const G = CV.G;
    if (!G) return;
    if (G.type === 'pan') {
      const dx = e.clientX - G.sx, dy = e.clientY - G.sy;
      if (Math.hypot(dx, dy) > 3) G.moved = true;
      cv.scrollLeft = G.sl - dx; cv.scrollTop = G.st - dy; cv.classList.toggle('panning', G.moved); cv.classList.toggle('gest', G.moved); return;
    }
    if (G.type === 'node') {
      const dx = (e.clientX - G.sx) / CV.zoom, dy = (e.clientY - G.sy) / CV.zoom;
      if (!G.moved) {
        if (Math.hypot(dx, dy) * CV.zoom < 4) return;
        G.moved = true; cv.classList.add('gest');
        if (!G.wasSel && !G.multi) { CV.sel = new Set([G.id]); G.group = [G.id]; G.orig = { [G.id]: { ...EW.pos[G.id] } }; }
        [...CV.nodesEl.children].forEach(el => { el.classList.toggle('sel', CV.sel.has(el.dataset.id)); if (G.group.includes(el.dataset.id)) el.classList.add('dragging'); });
      }
      G.group.forEach(id => { const o = G.orig[id], p = EW.pos[id]; p.x = Math.max(8, o.x + dx); p.y = Math.max(8, o.y + dy); });
      schedFrame(); return;
    }
    if (G.type === 'wire') {
      if (Math.hypot(e.clientX - G.sx, e.clientY - G.sy) > 6) G.moved = true;
      const sp = toStage(e.clientX, e.clientY), A = outPt(G.from);
      G.tmp.setAttribute('d', 'M' + A.x + ' ' + A.y + ' C' + A.x + ' ' + (A.y + 60) + ', ' + sp.x + ' ' + (sp.y - 60) + ', ' + sp.x + ' ' + sp.y);
      const el = document.elementFromPoint(e.clientX, e.clientY), n = el && el.closest && el.closest('.nd');
      CV.nodesEl.querySelectorAll('.drop').forEach(x => x.classList.remove('drop'));
      if (n && n.dataset.id !== G.from && !['trigger', 'end', 'report'].includes(n.dataset.id)) { n.classList.add('drop'); G.target = n.dataset.id; } else G.target = null;
    }
  });
  cv.addEventListener('pointerup', e => {
    const g = CV.G;
    if (!g) return;
    CV.G = null;
    try { cv.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
    cv.classList.remove('panning', 'gest');
    if (g.type === 'pan') {
      if (!g.moved) {
        const t = document.elementFromPoint(e.clientX, e.clientY);
        if (t && t._info) { showWireBar(t._info); return; }     // a tap on a wire (there is no mouse to hover with) opens its bar
        if (CV.sel.size) { CV.sel = new Set(); renderNodes(); renderInspector(); }
      }
      return;
    }
    if (g.type === 'node') {
      CV.nodesEl.querySelectorAll('.dragging').forEach(n => n.classList.remove('dragging'));
      if (!g.moved) {
        if (g.multi) { CV.sel.has(g.id) ? CV.sel.delete(g.id) : CV.sel.add(g.id); } else CV.sel = new Set([g.id]);
        if (CV.panel !== 'try') { CV.panel = 'insp'; CV.itab = 'set'; }
        renderNodes(); renderInspector(); revealAbove(g.id);
        const now = Date.now(), tap = CV.tap;                     // two quick clicks on a step open its window
        if (!g.multi && idxOf(g.id) >= 0 && tap && tap.id === g.id && now - tap.at < 500) { CV.tap = null; swOpen(g.id); } else CV.tap = { id: g.id, at: now };
      } else { EW.autoArr = false; commitLayout(); }
      return;
    }
    if (g.type === 'wire') endWire(e, g);
  });
  cv.addEventListener('pointercancel', () => { if (CV.G && CV.G.tmp) CV.G.tmp.remove(); CV.G = null; cv.classList.remove('panning', 'gest'); });
  cv.addEventListener('wheel', e => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); setZoom(CV.zoom * (e.deltaY < 0 ? 1.1 : 0.9), e.clientX, e.clientY); }, { passive: false });
  // a step dragged in from the list on the left: dropped near a "+" it goes there, anywhere else it goes to that spot
  cv.addEventListener('dragover', e => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; });
  cv.addEventListener('drop', e => {
    e.preventDefault();
    let d; try { d = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (_) { return; }
    if (!d) return;
    const sp = toStage(e.clientX, e.clientY); let at = null, best = 80;
    CV.plusPts.forEach(p => { const dist = Math.hypot(p.x - sp.x, p.y - sp.y); if (dist < best) { best = dist; at = p.at; } });
    usePalItem(d, at, at == null ? { x: Math.max(8, sp.x - colW() / 2), y: Math.max(8, sp.y - 30) } : null);
  });
  cv.addEventListener('keydown', e => {
    const n = e.target.closest && e.target.closest('.nd');
    if (!n || e.key !== 'Enter' || n.dataset.id === 'end') return;
    if (idxOf(n.dataset.id) >= 0) { swOpen(n.dataset.id); return; }
    CV.sel = new Set([n.dataset.id]); CV.panel = 'insp'; CV.itab = 'set'; renderNodes(); renderInspector();
  });
  cv.addEventListener('contextmenu', cvMenu);
}
function startWire(e, node) {
  const p = svgEl('path', { class: 'wire tmpw' });
  CV.wg.append(p);
  CV.G = { type: 'wire', from: node.dataset.id, moved: false, sx: e.clientX, sy: e.clientY, tmp: p, target: null };
  CV.el.classList.add('gest');
  CV.el.setPointerCapture(e.pointerId); e.preventDefault();
}
function endWire(e, g) {
  g.tmp.remove(); CV.nodesEl.querySelectorAll('.drop').forEach(x => x.classList.remove('drop'));
  if (g.target) { reorderAfter(g.from, g.target); return; }
  if (!g.moved) { toast('Drag from this dot onto another box to change what runs next.'); return; }
  if (isRead()) return;
  const sp = toStage(e.clientX, e.clientY), at = g.from === 'trigger' ? 0 : idxOf(g.from) + 1;
  const anchor = { getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY, width: 0, height: 0 }) };
  cvOpenAdd(at, anchor, { x: Math.max(8, sp.x - colW() / 2), y: Math.max(8, sp.y) });
}
// drag from a box's dot onto another box: that box now runs right after this one (a parked box is put back into the flow there)
function reorderAfter(aId, bId) {
  const parked = isParked(bId), bi = idxOf(bId);
  if (bi < 0 && !parked) return;
  const before = EW.ids.join();
  let s, id;
  if (parked) { const k = pidxOf(bId); s = EW.work.parked.splice(k, 1)[0].step; id = EW.pids.splice(k, 1)[0]; }
  else { s = EW.work.steps.splice(bi, 1)[0]; id = EW.ids.splice(bi, 1)[0]; }
  const ai = aId === 'trigger' ? -1 : idxOf(aId);
  EW.work.steps.splice(ai + 1, 0, s); EW.ids.splice(ai + 1, 0, id);
  if (!parked && EW.ids.join() === before) { toast('“' + stepName(s) + '” already runs right after that.'); return; }
  CV.run = null; if (parked) CV.sel = new Set([String(id)]); commit(true, true);
  toast(parked ? '“' + stepName(s) + '” is back in the flow, right after the one you picked.' : '“' + stepName(s) + '” now runs right after the one you picked. Boxes stay where they are.', null, { label: 'Undo', run: undo });
}

// ----- adding, removing, parking, re-ordering steps -----
const ONE_STEP = 'A building block is one step. To do several things, make a building block for each and run them one after another in a flow.';
const oneStepOnly = () => EW.work.kind === 'block' && EW.work.steps.length >= 1;
function cvAddStep(op, at, given, pos) {
  if (oneStepOnly()) { toast(ONE_STEP, 'bad'); return; }
  const spec = catalogSpec(op), step = { op, params: {} };
  (spec ? spec.params : []).forEach(p => { if (p.default !== undefined && p.kind !== 'column') step.params[p.key] = p.default; });
  Object.assign(step.params, given || {});
  const idx = at == null ? EW.work.steps.length : at, id = String(EW.nextId);
  EW.work.steps.splice(idx, 0, step); EW.ids.splice(idx, 0, EW.nextId++);
  if (pos) EW.pos[id] = pos; else if (idx < EW.work.steps.length - 1) CV.justAdded = id;
  CV.sel = new Set([id]); if (CV.panel !== 'try') CV.panel = 'insp'; CV.itab = 'set'; CV.run = null;
  commit(true);
  toast('Added “' + (op === 'run_workflow' || !spec ? describeStep(step) : spec.label) + '”. Save when you are happy with it.');
  if (CV.pal && innerWidth <= 1180) CV.pal.classList.add('closed');   // on a narrow screen the list covers the canvas
  scrollToNode(id);
}
// open, duplicate or delete one box (the little bar above a box, and the buttons in the panel, use these)
function cvOpen(id) {
  CV.sel = new Set([id]); if (CV.panel !== 'try') { CV.panel = 'insp'; CV.itab = 'set'; }
  renderNodes(); renderInspector(); revealAbove(id);
}
function cvDup(id) { if (idxOf(id) < 0) return; CV.sel = new Set([id]); stepAct('dup'); }
function cvDel(id) { CV.sel = new Set([id]); removeSelected(); }
// no "are you sure": Undo is in the message, and nothing is kept until Save
function removeSelected() {
  const all = [...CV.sel].filter(id => id !== 'trigger' && id !== 'report');
  if (!all.length) { toast('The first box cannot be removed. Every flow starts somewhere.'); return; }
  const names = all.map(id => stepName(isParked(id) ? EW.work.parked[pidxOf(id)].step : EW.work.steps[idxOf(id)]));
  const ids = all.filter(id => !isParked(id));
  ids.forEach(id => {                                         // the boxes below move up to close the gap
    const p = EW.pos[id], hh = CV.hm[id] || 100;
    chain().forEach(o => { const q = EW.pos[o]; if (o !== id && !ids.includes(o) && q && p && q.y > p.y && Math.abs(q.x - p.x) < colW()) q.y -= hh + gapV(); });
  });
  ids.forEach(id => { const i = idxOf(id); if (i >= 0) { EW.work.steps.splice(i, 1); EW.ids.splice(i, 1); } });
  all.filter(isParked).forEach(id => { const k = pidxOf(id); if (k >= 0) { EW.work.parked.splice(k, 1); EW.pids.splice(k, 1); } });
  CV.sel = new Set(); CV.run = null; commit(true, true);
  toast(all.length === 1 ? 'Deleted “' + names[0] + '”.' : 'Deleted ' + plural(all.length, 'step') + '.', null, { label: 'Undo', run: undo });
}
// Remove link: the step after the wire is parked. It leaves the flow (so it does not run, and the steps around it join up) but stays on the canvas.
function cvPark(id) {
  const i = idxOf(id);
  if (i < 0 || oneStepOnly()) return;
  if (!EW.layoutCap) { toast('This organisation’s database cannot keep parked steps yet.', 'bad'); return; }
  const s = EW.work.steps.splice(i, 1)[0], pid = EW.ids.splice(i, 1)[0];
  EW.work.parked.push({ step: s, at: i }); EW.pids.push(pid);   // the box keeps its id, so it stays where it is
  CV.sel = new Set(); CV.run = null; CV.reflow = true; commit(true, true);
  toast('Link removed. “' + stepName(s) + '” is parked: it stays here but does not run.', null, { label: 'Undo', run: undo });
}
function cvUnpark(id) {
  const k = pidxOf(id);
  if (k < 0) return;
  const p = EW.work.parked.splice(k, 1)[0], pid = EW.pids.splice(k, 1)[0], at = Math.max(0, Math.min(p.at, EW.work.steps.length));
  EW.work.steps.splice(at, 0, p.step); EW.ids.splice(at, 0, pid);
  CV.sel = new Set([String(pid)]); CV.run = null; CV.reflow = true; commit(true, true);
  toast('“' + stepName(p.step) + '” is back in the flow.', null, { label: 'Undo', run: undo });
}
function stepAct(act) {
  const id = primary(), i = idxOf(id);
  if (act === 'del') { removeSelected(); return; }
  if (act === 'park') { cvPark(id); return; }
  if (i < 0) return;
  if (act === 'up' || act === 'down') {
    const j = act === 'up' ? i - 1 : i + 1;
    if (j < 0 || j >= EW.work.steps.length) return;
    const a = idAt(i), b = idAt(j), pa = EW.pos[a], pb = EW.pos[b];
    [EW.work.steps[i], EW.work.steps[j]] = [EW.work.steps[j], EW.work.steps[i]];
    [EW.ids[i], EW.ids[j]] = [EW.ids[j], EW.ids[i]];
    const first = idAt(Math.min(i, j)), second = idAt(Math.max(i, j)), top = Math.min(pa.y, pb.y);
    if (Math.abs(pa.x - pb.x) < colW()) { const x = Math.min(pa.x, pb.x); EW.pos[first] = { x, y: top }; EW.pos[second] = { x, y: top + (CV.hm[first] || 100) + gapV() }; }
    else { EW.pos[a] = pb; EW.pos[b] = pa; }
  }
  if (act === 'dup') {
    if (oneStepOnly()) { toast(ONE_STEP, 'bad'); return; }
    const c = clone(EW.work.steps[i]), nid = String(EW.nextId);
    EW.work.steps.splice(i + 1, 0, c); EW.ids.splice(i + 1, 0, EW.nextId++);
    CV.sel = new Set([nid]); if (i + 1 < EW.work.steps.length - 1) CV.justAdded = nid;
  }
  CV.run = null; commit(true);
}
// N: "What happens next?" for a new step, right after the box that is chosen (or at the end of the flow)
function cvNext() {
  if (isRead()) { toast('This flow answers with a saved report, so it has no steps to add.'); return; }
  if (oneStepOnly()) { toast(ONE_STEP, 'bad'); return; }
  const id = primary(), i = id ? idxOf(id) : -1, at = i >= 0 ? i + 1 : EW.work.steps.length;
  const el = (i >= 0 && CV.nodesEl.querySelector('[data-id="' + id + '"]')) || CV.nodesEl.querySelector('[data-id="end"]') || CV.el;
  cvOpenAdd(at, el);
}

// ----- keys: Tidy up, Undo, Delete, N, Escape (only while a flow is open and nothing is being typed) -----
document.addEventListener('keydown', e => {
  if (!EW || !CV || !CV.el || !CV.el.isConnected) return;
  const t = e.target;
  if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
  if (modalStack.length) return;
  if (e.shiftKey && e.altKey && e.key.toLowerCase() === 't') { e.preventDefault(); arrange(EW.mode || 'rows'); }
  else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && CV.sel.size) { e.preventDefault(); removeSelected(); }
  else if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); cvNext(); }
  else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'd' && primary() && idxOf(primary()) >= 0) { e.preventDefault(); cvDup(primary()); }
  else if ((e.key === 'F2' || e.key === ' ' || e.key === 'Enter') && !e.ctrlKey && !e.metaKey && !e.altKey && primary() && idxOf(primary()) >= 0 && (!t || t === document.body || (t.closest && t.closest('.cv')))) { e.preventDefault(); if (e.key === 'Enter') swOpen(primary()); else cvRename(primary()); }
  else if (e.key === 'Escape' && CV.sel.size && Date.now() - swClosedAt > 150) { CV.sel = new Set(); renderNodes(); renderInspector(); }
});
window.addEventListener('resize', () => { if (CV && CV.el && CV.el.isConnected) applyZoom(); });
"""
